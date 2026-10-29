"""
Semantic conversation memory — the "relevant older turns" leg of the context
layer (see app/context_manager.py), for a conversation long enough that the
answer to the current question was actually said several turns back, past
what session_store's in-process turn window or a short recent-turns slice
would still hold.

Deliberately NOT the same thing as:
  - app/vectorstore.py       — the scheme-KB collection for RAG. Different
                                content (reference docs, not conversation
                                turns), different collection, same client.
  - app/semantic_cache.py    — near-duplicate QUESTION -> cached ANSWER, keyed
                                on an authorization fingerprint, in-process
                                only. This module stores conversation TURNS in
                                Qdrant, keyed by tenant/user/session, for
                                retrieval as *context* to feed a rewrite — it
                                never short-circuits the pipeline or serves an
                                answer directly.

Reuses the existing Qdrant client (app.vectorstore.get_client) and the
existing embedding pipeline (app.llm.call_embedding) — no new connection, no
new embedding model. A dedicated collection (CONTEXT_MEMORY_COLLECTION) keeps
it out of the KB collection's point count / filters.

Every write and read is scoped by tenant_id + user_id (+ session_id for a
single-conversation lookup) as a Qdrant payload filter — the same fields the
Postgres conversation tables already partition on (see app/auth.py,
app/conversation_store.py). This is a convenience index over conversation
turns the user is already authorized to see; it grants no authorization of
its own, and nothing read from it is ever used to build or execute SQL
directly (see context_manager.py) — only to enrich a rewrite prompt.

Every function here is best-effort: indexing runs as a fire-and-forget
background task (mirroring conversation_store.persist_turn), and a search
failure (Qdrant down, collection missing, embedding error) returns an empty
list rather than raising, so the pipeline always has PostgreSQL + in-session
turns to fall back to.
"""
import asyncio
import logging
import time
import uuid

from qdrant_client import models

from app import llm, vectorstore
from app.config import settings

logger = logging.getLogger(__name__)

_bg: set[asyncio.Task] = set()
_collection_ready = False
_collection_wrong_size = False


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def _ensure_collection(dim: int) -> bool:
    """Create the conversation-memory collection on first use. Cheap after the
    first call (module-level flag); any failure just disables memory for this
    request — the collection may already exist from a previous worker, in
    which case get_collection succeeds and we skip creation.

    An existing collection of another vector size (an EMBEDDING_PROVIDER change
    without a new CONTEXT_MEMORY_COLLECTION, D-067) is never deleted — it holds
    officers' chats — so memory stays off with one ERROR naming the fix, instead
    of a warning on every turn."""
    global _collection_ready, _collection_wrong_size
    if _collection_ready:
        return True
    if _collection_wrong_size:
        return False
    client = vectorstore.get_client()
    try:
        info = await client.get_collection(settings.CONTEXT_MEMORY_COLLECTION)
    except Exception:  # noqa: BLE001 — collection doesn't exist yet
        info = None
    if info is not None:
        size = vectorstore.vector_size(info)
        if size and size != dim:
            _collection_wrong_size = True
            logger.error("conversation_memory: %s holds %d-dim vectors but the embedding "
                         "model returns %d — memory is off; set CONTEXT_MEMORY_COLLECTION "
                         "to a %d-dim collection", settings.CONTEXT_MEMORY_COLLECTION,
                         size, dim, dim)
            return False
        _collection_ready = True
        return True
    try:
        await client.create_collection(
            collection_name=settings.CONTEXT_MEMORY_COLLECTION,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        _collection_ready = True
        logger.info("conversation_memory: created collection %s (dim=%d)",
                    settings.CONTEXT_MEMORY_COLLECTION, dim)
    except Exception as e:  # noqa: BLE001
        logger.warning("conversation_memory: could not create collection: %s", e)
        return False
    await create_payload_indexes(client, settings.CONTEXT_MEMORY_COLLECTION)
    return True


# Every search filters on these (scope + retention) and the purge on `ts`.
PAYLOAD_INDEXES = (("tenant_id", "integer"), ("user_id", "integer"),
                   ("session_id", "keyword"), ("ts", "float"))


async def create_payload_indexes(client, name: str) -> None:
    """Index the filtered fields of a memory collection. Best-effort: without
    them search still works, only slower to plan."""
    for field, schema in PAYLOAD_INDEXES:
        try:
            await client.create_payload_index(collection_name=name, field_name=field,
                                              field_schema=schema, wait=True)
        except Exception as e:  # noqa: BLE001 — never block memory on an index
            logger.warning("conversation_memory: could not index %s.%s: %s", name, field, e)


# ── Retention (RAG upgrade Phase 7, 2026-10-15) ─────────────────────────────
# Every answered turn was indexed and nothing was ever deleted, so officers'
# chat history piled up in Qdrant for good. Turns older than
# CONTEXT_MEMORY_RETENTION_DAYS are never returned (search filter) and are
# deleted by purge_old_turns, run at startup and then once a day (app/main.py).
# 0 keeps everything.

def _retention_floor() -> float:
    days = settings.CONTEXT_MEMORY_RETENTION_DAYS
    return time.time() - days * 86400 if days and days > 0 else 0.0


async def _purge_collection(client, name: str, old: models.Filter, why: str = "") -> int | None:
    try:
        if not await client.collection_exists(name):
            return None
        n = (await client.count(name, count_filter=old, exact=True)).count
        if n:
            await client.delete(collection_name=name,
                                points_selector=models.FilterSelector(filter=old), wait=True)
            logger.info("conversation_memory: deleted %d turns %s from %s", n,
                        why or f"older than {settings.CONTEXT_MEMORY_RETENTION_DAYS} days", name)
        return n
    except Exception as e:  # noqa: BLE001 — housekeeping must never break startup
        logger.warning("conversation_memory: purge of %s failed (non-fatal): %s", name, e)
        return None


async def purge_old_turns() -> int | None:
    """Delete conversation-memory turns older than the retention window.
    Returns how many were deleted from the live collection, or None when there
    was nothing to do or Qdrant could not be reached (never raises).

    The other memory collections in CONTEXT_MEMORY_PURGE_ALSO are purged too:
    after the 1024-dim switch (D-067) the 384-dim collection is kept for
    rollback, and its officers' chats must still go after the window."""
    floor = _retention_floor()
    if not floor or not settings.CONTEXT_SEMANTIC_MEMORY_ENABLED:
        return None
    client = vectorstore.get_client()
    old = models.Filter(must=[models.FieldCondition(key="ts", range=models.Range(lt=floor))])
    n = await _purge_collection(client, settings.CONTEXT_MEMORY_COLLECTION, old)
    for name in (s.strip() for s in settings.CONTEXT_MEMORY_PURGE_ALSO.split(",")):
        if name and name != settings.CONTEXT_MEMORY_COLLECTION:
            await _purge_collection(client, name, old)
    return n


def _memory_collections() -> list[str]:
    """Every collection that holds officers' chat turns: the live one and the
    CONTEXT_MEMORY_PURGE_ALSO list (the rollback copy, D-067)."""
    names = [settings.CONTEXT_MEMORY_COLLECTION]
    for name in (s.strip() for s in settings.CONTEXT_MEMORY_PURGE_ALSO.split(",")):
        if name and name not in names:
            names.append(name)
    return names


async def delete_session(*, tenant_id: int | None, user_id: int | None, session_id: str | None) -> int | None:
    """Delete one conversation's turns from conversation memory (the officer
    deleted the chat, CTX-04, 2026-10-29). Returns how many went from the live
    collection, or None when nothing was done (never raises).

    The filter always names the session AND its owner, plus the tenant when it
    is known: with either missing nothing is deleted, so a bad call can never
    reach another officer's turns."""
    if not session_id or user_id is None:
        return None
    must = [models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id)),
            models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
    if tenant_id is not None:
        must.append(models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)))
    try:
        client = vectorstore.get_client()
    except Exception as e:  # noqa: BLE001
        logger.warning("conversation_memory: delete_session skipped, no Qdrant client: %s", e)
        return None
    deleted = None
    for name in _memory_collections():
        n = await _purge_collection(client, name, models.Filter(must=must), why="of a deleted conversation")
        if name == settings.CONTEXT_MEMORY_COLLECTION:
            deleted = n
    return deleted


async def _purge_old_conversations() -> None:
    """The database side of retention (CTX-04): conversations, their turns and
    the query audit older than CONVERSATION_RETENTION_DAYS /
    QUERY_AUDIT_RETENTION_DAYS. Both default to 0 (keep everything) until the
    periods are chosen. Never raises."""
    if not (settings.CONVERSATION_RETENTION_DAYS > 0 or settings.QUERY_AUDIT_RETENTION_DAYS > 0):
        return
    try:
        from app import appdb
        await appdb.purge_old_conversations(conversation_days=settings.CONVERSATION_RETENTION_DAYS,
                                            audit_days=settings.QUERY_AUDIT_RETENTION_DAYS)
    except Exception as e:  # noqa: BLE001 — housekeeping must never break the worker
        logger.warning("conversation_memory: conversation retention purge failed (non-fatal): %s", e)


async def purge_loop(every_seconds: int = 86400) -> None:
    """Purge now, then once a day, for the life of the worker: conversation
    memory in Qdrant, then the conversation tables (CTX-04)."""
    while True:
        await purge_old_turns()
        await _purge_old_conversations()
        await asyncio.sleep(every_seconds)


def index_turn(*, tenant_id: int | None, user_id: int | None, session_id: str,
               question: str, standalone_question: str, answer: str,
               schemes: list[str] | None = None) -> None:
    """Fire-and-forget: embed one turn and upsert it into conversation memory.
    Never raises into the caller — see module docstring."""
    if not settings.CONTEXT_SEMANTIC_MEMORY_ENABLED:
        return
    # The turn's time is now, when it was answered, not when its embedding
    # comes back: a slow gateway stamped turn N-1 after a quick "start a new
    # topic", and it came back past memory_since (CTX-14, 2026-10-29).
    _spawn(_index_turn(tenant_id, user_id, session_id, question,
                       standalone_question, answer, schemes or [], time.time()))


async def _index_turn(tenant_id, user_id, session_id, question, standalone_question,
                      answer, schemes, ts: float) -> None:
    try:
        text = standalone_question or question
        if not text or not text.strip():
            return
        vecs = await llm.call_embedding(text)
        if not vecs:
            return
        vec = vecs[0]
        if not await _ensure_collection(len(vec)):
            return
        point = models.PointStruct(
            id=uuid.uuid4().hex,
            vector=vec,
            payload={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
                "question": question[:2000],
                "standalone_question": (standalone_question or "")[:2000],
                "answer": (answer or "")[:1000],
                "schemes": schemes,
                "ts": ts,
            },
        )
        await vectorstore.get_client().upsert(
            collection_name=settings.CONTEXT_MEMORY_COLLECTION, points=[point], wait=False)
    except Exception as e:  # noqa: BLE001 — indexing must never break a request
        logger.warning("conversation_memory: index_turn failed (non-fatal): %s", e)


async def search_relevant_turns(*, question: str, tenant_id: int | None, user_id: int | None,
                                session_id: str | None = None, top_k: "int | None" = None,
                                exclude_session: bool = False, since: float = 0.0) -> list[dict]:
    """Up to `top_k` older turns semantically relevant to `question`, scoped to
    this tenant/user (and, unless exclude_session, this session too — the
    normal case is "this same conversation, further back than the in-process
    window"). Returns [] on ANY failure (embedding, Qdrant unreachable,
    collection missing) — callers must already have a PostgreSQL/in-session
    fallback and treat this purely as an enrichment, per the failure-tolerance
    requirement (Qdrant/memory retrieval failing must never break the core
    pipeline).

    `since` (wall-clock seconds) returns only turns indexed after it: the
    moment the conversation was last cleared ("start a new topic", reset, idle
    expiry), so the turns before it never come back (KI-224). Turns older than
    CONTEXT_MEMORY_RETENTION_DAYS never come back either."""
    if not settings.CONTEXT_SEMANTIC_MEMORY_ENABLED or not question or not question.strip():
        return []
    top_k = top_k or settings.CONTEXT_MEMORY_TOP_K
    try:
        vecs = await llm.call_embedding(question)
        if not vecs:
            return []
        must: list[models.FieldCondition] = []
        if tenant_id is not None:
            must.append(models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)))
        if user_id is not None:
            must.append(models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)))
        if session_id and not exclude_session:
            must.append(models.FieldCondition(key="session_id", match=models.MatchValue(value=session_id)))
        floor = max(float(since or 0.0), _retention_floor())
        if floor > 0:
            must.append(models.FieldCondition(key="ts", range=models.Range(gte=floor)))
        query_filter = models.Filter(must=must) if must else None

        client = vectorstore.get_client()
        # Exact, not HNSW (2026-10-24): one officer's 30-day turns are few, and the
        # approximate graph under a user/session filter missed a usable turn (60 real
        # queries: 58/60 top-5 equal to exact, 1 of 300 usable turns lost; exact 60/60,
        # same p50 ~105 ms with the payload indexes below).
        response = await client.query_points(
            collection_name=settings.CONTEXT_MEMORY_COLLECTION,
            query=vecs[0],
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
            search_params=models.SearchParams(exact=True),
        )
        out = []
        for h in response.points:
            if float(h.score) < settings.CONTEXT_MEMORY_MIN_SCORE:
                continue
            p = h.payload or {}
            out.append({
                "score": float(h.score),
                "question": p.get("question", ""),
                "standalone_question": p.get("standalone_question", ""),
                "answer": p.get("answer", ""),
                "schemes": p.get("schemes", []),
                "session_id": p.get("session_id"),
            })
        return out
    except Exception as e:  # noqa: BLE001 — see docstring: memory is best-effort
        logger.warning("conversation_memory: search failed, falling back (non-fatal): %s", e)
        return []
