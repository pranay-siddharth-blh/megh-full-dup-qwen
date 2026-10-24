"""
Local keyword vectors and re-ranking for the RAG path (RAG upgrade Phase 3,
2026-10-14). Both run on CPU via fastembed (ONNX), like local_embed.py, and for
the same reason on the calling (event-loop) thread: onnxruntime's Run()
deadlocks on Windows when driven from a ThreadPoolExecutor worker.

  sparse  BM25 keyword vectors (RAG_SPARSE_MODEL, "Qdrant/bm25", ~10 MB). The
          meaning model (bge-small or qwen3-embedding) reads a bare acronym or an exact term
          poorly — "SECC", "Form 6", "job card" — and keyword search finds the
          pieces that literally contain it. kb_ingest stores one per piece;
          vectorstore.search fuses it with the meaning search (RRF).
  rerank  a cross-encoder (RAG_LOCAL_RERANKER) that reads the question together
          with each candidate piece and scores how well the piece answers it —
          more precise than comparing two separate vectors. Used only to ORDER
          the candidates; the confidence tiers keep using the meaning (cosine)
          score, whose scale they were tuned on.

The first call downloads the weights to the HuggingFace cache; every later call
is offline. A model that cannot load is logged once and the step is skipped, so
the knowledge path degrades to meaning search instead of failing.
"""
import asyncio
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_sparse = None
_reranker = None
_failed: set[str] = set()
_lock = asyncio.Lock()
_YIELD_EVERY = 16


async def _load(kind: str):
    global _sparse, _reranker
    name = settings.RAG_SPARSE_MODEL if kind == "sparse" else settings.RAG_LOCAL_RERANKER
    if not name or name in _failed:
        return None
    current = _sparse if kind == "sparse" else _reranker
    if current is not None and current[0] == name:
        return current[1]
    async with _lock:
        try:
            logger.info("local_rank: loading %s %s (first run downloads it)", kind, name)
            if kind == "sparse":
                from fastembed import SparseTextEmbedding
                _sparse = (name, SparseTextEmbedding(model_name=name))
                return _sparse[1]
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            _reranker = (name, TextCrossEncoder(model_name=name))
            return _reranker[1]
        except Exception as e:  # noqa: BLE001 — degrade to meaning search, never fail the turn
            _failed.add(name)
            logger.warning("local_rank: could not load %s (%s) — %s step skipped", name, e, kind)
            return None


def _as_pair(v) -> tuple[list[int], list[float]]:
    return [int(i) for i in v.indices.tolist()], [float(x) for x in v.values.tolist()]


async def sparse_docs(texts: list[str]) -> list[tuple[list[int], list[float]]] | None:
    """BM25 vectors (indices, values) for the pieces, in order; None when off."""
    model = await _load("sparse")
    if model is None:
        return None
    out: list[tuple[list[int], list[float]]] = []
    for i in range(0, len(texts), _YIELD_EVERY):
        out.extend(_as_pair(v) for v in model.embed(texts[i:i + _YIELD_EVERY], parallel=1))
        await asyncio.sleep(0)
    return out


async def sparse_query(text: str) -> tuple[list[int], list[float]] | None:
    """The question's BM25 vector; None when off or empty."""
    model = await _load("sparse")
    if model is None or not (text or "").strip():
        return None
    v = next(iter(model.query_embed(text)))
    pair = _as_pair(v)
    return pair if pair[0] else None


async def rerank(question: str, texts: list[str]) -> list[float] | None:
    """A relevance score per text (higher = better), in input order; None when off."""
    if not texts:
        return []
    model = await _load("rerank")
    if model is None:
        return None
    try:
        return [float(s) for s in model.rerank(question, texts)]
    except Exception as e:  # noqa: BLE001
        logger.warning("local_rank: rerank failed (%s) — keeping search order", e)
        return None
