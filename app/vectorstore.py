"""
Qdrant access for the scheme-knowledge base (the RAG path).

One module-level AsyncQdrantClient, opened at startup and closed at shutdown —
same reasoning as the shared httpx client and the asyncpg pool: a fresh client
per request wastes connections at the 20-40 concurrent target.

Qdrant runs on its own server (115.124.102.167:6335, since 2026-10-03; no VPN needed). It
is only used for scheme-knowledge retrieval; all numeric
answers come from megh_db, never from here.
"""
import logging

from qdrant_client import AsyncQdrantClient, models

from app.config import settings

logger = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


async def init_qdrant() -> None:
    global _client
    _client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY or None,
        timeout=30,
    )
    logger.info("qdrant client ready (%s)", settings.QDRANT_URL)


async def close_qdrant() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def get_client() -> AsyncQdrantClient:
    if _client is None:
        raise RuntimeError("qdrant client not initialized — call init_qdrant() at startup")
    return _client


async def collection_count() -> int:
    """Point count for the KB collection, or -1 if the collection is absent."""
    client = get_client()
    try:
        info = await client.get_collection(settings.QDRANT_COLLECTION)
        return info.points_count or 0
    except Exception:  # noqa: BLE001 — missing collection is not an error here
        return -1


async def distinct_schemes() -> set[str]:
    """Every distinct `scheme` payload tag currently in the collection.

    Used by kb_ingest to tell a merely-smaller collection from a stale one: a
    scheme present in data/ but absent here can never be retrieved (search
    filters on an exact scheme match), so its questions all answer "not
    covered". Returns an empty set on any error, which the caller reads as
    "cannot confirm" and rebuilds — the safe direction.
    """
    client = get_client()
    schemes: set[str] = set()
    offset = None
    try:
        while True:
            points, offset = await client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                limit=512,
                offset=offset,
                with_payload=["scheme"],
                with_vectors=False,
            )
            for p in points:
                tag = (p.payload or {}).get("scheme")
                if tag:
                    schemes.add(tag)
            if offset is None:
                break
    except Exception as e:  # noqa: BLE001 — missing/unreachable collection
        logger.warning("qdrant: could not list scheme tags (%s)", e)
        return set()
    return schemes


SPARSE_NAME = "bm25"   # the keyword vector's name; the meaning vector stays unnamed

# Per collection: does it carry the keyword vector? Read once (a v2 collection
# built before Phase 3 has none, and its search stays meaning-only).
_has_sparse: dict[str, bool] = {}


async def recreate_collection(dim: int, sparse: bool = False) -> None:
    """(Re)create the KB collection: the unnamed meaning vector, plus — with
    `sparse` — the BM25 keyword vector (IDF weighting done by Qdrant)."""
    client = get_client()
    name = settings.QDRANT_COLLECTION
    if await client.collection_exists(name):
        await client.delete_collection(name)
    await client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        sparse_vectors_config=(
            {SPARSE_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)} if sparse else None),
    )
    _has_sparse[name] = sparse
    logger.info("qdrant collection %s (re)created, dim=%d, keyword vector=%s", name, dim, sparse)


async def has_sparse() -> bool:
    name = settings.QDRANT_COLLECTION
    if name not in _has_sparse:
        try:
            info = await get_client().get_collection(name)
            _has_sparse[name] = SPARSE_NAME in (info.config.params.sparse_vectors or {})
        except Exception:  # noqa: BLE001 — unknown: search meaning-only this time
            return False
    return _has_sparse[name]


async def upsert(points: list[models.PointStruct]) -> None:
    client = get_client()
    await client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points, wait=True)


def _cosine(a: list[float], b) -> float:
    b = list(b or [])
    if not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def search(vector: list[float], top_k: int, scheme: str | None = None,
                 sparse: tuple[list[int], list[float]] | None = None) -> list[dict]:
    """Returns [{score, text, doc, heading, scheme}, ...] best first.

    With `sparse` (the question's BM25 vector) on a collection that holds the
    keyword vector, meaning search and keyword search each fetch `top_k`
    candidates and Qdrant fuses the two lists by rank (RRF) — a piece that
    literally contains "SECC" or "job card" is found even when the meaning
    model reads the question poorly. The order is the fused one, but `score`
    stays the meaning (cosine) similarity, so the confidence tiers in rag.py
    keep the scale they were tuned on.
    `scheme`, when given, restricts the search to chunks payload-tagged with
    that exact scheme — every chunk carries a `scheme` tag at ingest time
    (kb_ingest.py), but without this filter search runs unscoped across the
    whole collection and can blend another scheme's content into the answer."""
    client = get_client()
    query_filter = None
    if scheme:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="scheme", match=models.MatchValue(value=scheme))]
        )
    if sparse and sparse[0] and await has_sparse():
        response = await client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            prefetch=[
                models.Prefetch(query=vector, filter=query_filter, limit=top_k),
                models.Prefetch(query=models.SparseVector(indices=sparse[0], values=sparse[1]),
                                using=SPARSE_NAME, filter=query_filter, limit=top_k),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
            with_vectors=[""],
        )
        out = []
        for rank, h in enumerate(response.points, 1):
            vec = h.vector.get("") if isinstance(h.vector, dict) else h.vector
            out.append({
                "score": _cosine(vector, vec),
                "fused_rank": rank,
                "text": h.payload.get("text", ""),
                "doc": h.payload.get("doc", ""),
                "heading": h.payload.get("heading", ""),
                "scheme": h.payload.get("scheme", ""),
                "source_type": h.payload.get("source_type", "sme"),
            })
        return out

    # qdrant-client >= 1.10 replaced .search() with .query_points().
    response = await client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )
    hits = response.points
    return [
        {
            "score": float(h.score),
            "text": h.payload.get("text", ""),
            "doc": h.payload.get("doc", ""),
            "heading": h.payload.get("heading", ""),
            "scheme": h.payload.get("scheme", ""),
            "source_type": h.payload.get("source_type", "sme"),
        }
        for h in hits
    ]
