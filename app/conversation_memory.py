"""
Semantic conversation memory — the "relevant older turns" leg of the context
layer (see app/context_manager.py), for a conversation long enough that the
answer to the current question was actually said several turns back, past
what session_store's in-process turn window or a short recent-turns slice
would still hold.

Deliberately NOT the same thing as:
  - app/vectorstore.py       — the scheme-KB table for RAG. Different
                                content (reference docs, not conversation
                                turns), different table, same pgvector pool.
  - app/semantic_cache.py    — near-duplicate QUESTION -> cached ANSWER, keyed
                                on an authorization fingerprint, in-process
                                only. This module stores conversation TURNS in
                                Postgres/pgvector, keyed by tenant/user/session,
                                for retrieval as *context* to feed a rewrite —
                                it never short-circuits the pipeline or serves
                                an answer directly.

Reuses the existing pgvector pool (app.vectorstore.get_pool) and the existing
embedding pipeline (app.llm.call_embedding) — no new connection, no new
embedding model. A dedicated table (CONTEXT_MEMORY_TABLE) keeps it out of the
KB table's row count / filters.

Every write and read is scoped by tenant_id + user_id (+ session_id for a
single-conversation lookup) as a SQL WHERE filter — the same fields the
Postgres conversation tables already partition on (see app/auth.py,
app/conversation_store.py). This is a convenience index over conversation
turns the user is already authorized to see; it grants no authorization of
its own, and nothing read from it is ever used to build or execute SQL
directly (see context_manager.py) — only to enrich a rewrite prompt.

Every function here is best-effort: indexing runs as a fire-and-forget
background task (mirroring conversation_store.persist_turn), and a search
failure (pgvector down, table missing, embedding error) returns an empty
list rather than raising, so the pipeline always has PostgreSQL + in-session
turns to fall back to.
"""
import asyncio
import logging
import time
import uuid

from app import llm, vectorstore
from app.config import settings

logger = logging.getLogger(__name__)

_bg: set[asyncio.Task] = set()
_table_ready = False


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def _ensure_table(dim: int) -> bool:
    """Create the conversation-memory table on first use. Cheap after the
    first call (module-level flag); any failure just disables memory for this
    request — the table may already exist from a previous worker, since
    CREATE TABLE IF NOT EXISTS is idempotent."""
    global _table_ready
    if _table_ready:
        return True
    try:
        table = vectorstore.safe_ident(settings.CONTEXT_MEMORY_TABLE)
        pool = vectorstore.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id uuid PRIMARY KEY,
                    tenant_id int,
                    user_id int,
                    session_id text,
                    question text,
                    standalone_question text,
                    answer text,
                    schemes text[],
                    ts double precision,
                    embedding vector({dim})
                )
            """)
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {table}_embedding_idx "
                f"ON {table} USING hnsw (embedding vector_cosine_ops)"
            )
            await conn.execute(
                f"CREATE INDEX IF NOT EXISTS {table}_scope_idx "
                f"ON {table} (tenant_id, user_id, session_id)"
            )
        _table_ready = True
        logger.info("conversation_memory: table %s ready (dim=%d)", table, dim)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("conversation_memory: could not ensure table: %s", e)
        return False


def index_turn(*, tenant_id: int | None, user_id: int | None, session_id: str,
               question: str, standalone_question: str, answer: str,
               schemes: list[str] | None = None) -> None:
    """Fire-and-forget: embed one turn and upsert it into conversation memory.
    Never raises into the caller — see module docstring."""
    if not settings.CONTEXT_SEMANTIC_MEMORY_ENABLED:
        return
    _spawn(_index_turn(tenant_id, user_id, session_id, question,
                       standalone_question, answer, schemes or []))


async def _index_turn(tenant_id, user_id, session_id, question, standalone_question,
                      answer, schemes) -> None:
    try:
        text = standalone_question or question
        if not text or not text.strip():
            return
        vecs = await llm.call_embedding(text)
        if not vecs:
            return
        vec = vecs[0]
        if not await _ensure_table(len(vec)):
            return
        table = vectorstore.safe_ident(settings.CONTEXT_MEMORY_TABLE)
        pool = vectorstore.get_pool()
        await pool.execute(
            f"""INSERT INTO {table}
                (id, tenant_id, user_id, session_id, question, standalone_question,
                 answer, schemes, ts, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::vector)""",
            uuid.uuid4(), tenant_id, user_id, session_id, question[:2000],
            (standalone_question or "")[:2000], (answer or "")[:1000],
            schemes, time.time(), vectorstore.vec_literal(vec),
        )
    except Exception as e:  # noqa: BLE001 — indexing must never break a request
        logger.warning("conversation_memory: index_turn failed (non-fatal): %s", e)


async def search_relevant_turns(*, question: str, tenant_id: int | None, user_id: int | None,
                                session_id: str | None = None, top_k: "int | None" = None,
                                exclude_session: bool = False) -> list[dict]:
    """Up to `top_k` older turns semantically relevant to `question`, scoped to
    this tenant/user (and, unless exclude_session, this session too — the
    normal case is "this same conversation, further back than the in-process
    window"). Returns [] on ANY failure (embedding, pgvector unreachable,
    table missing) — callers must already have a PostgreSQL/in-session
    fallback and treat this purely as an enrichment, per the failure-tolerance
    requirement (pgvector/memory retrieval failing must never break the core
    pipeline)."""
    if not settings.CONTEXT_SEMANTIC_MEMORY_ENABLED or not question or not question.strip():
        return []
    top_k = top_k or settings.CONTEXT_MEMORY_TOP_K
    try:
        vecs = await llm.call_embedding(question)
        if not vecs:
            return []
        vec = vecs[0]
        if not await _ensure_table(len(vec)):
            return []

        table = vectorstore.safe_ident(settings.CONTEXT_MEMORY_TABLE)
        params: list = [vectorstore.vec_literal(vec)]
        conditions: list[str] = []
        if tenant_id is not None:
            params.append(tenant_id)
            conditions.append(f"tenant_id = ${len(params)}")
        if user_id is not None:
            params.append(user_id)
            conditions.append(f"user_id = ${len(params)}")
        if session_id and not exclude_session:
            params.append(session_id)
            conditions.append(f"session_id = ${len(params)}")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(top_k)

        sql = f"""
            SELECT question, standalone_question, answer, schemes, session_id,
                   1 - (embedding <=> $1::vector) AS score
            FROM {table}
            {where}
            ORDER BY embedding <=> $1::vector
            LIMIT ${len(params)}
        """
        pool = vectorstore.get_pool()
        rows = await pool.fetch(sql, *params)

        out = []
        for r in rows:
            score = float(r["score"])
            if score < settings.CONTEXT_MEMORY_MIN_SCORE:
                continue
            out.append({
                "score": score,
                "question": r["question"] or "",
                "standalone_question": r["standalone_question"] or "",
                "answer": r["answer"] or "",
                "schemes": r["schemes"] or [],
                "session_id": r["session_id"],
            })
        return out
    except Exception as e:  # noqa: BLE001 — see docstring: memory is best-effort
        logger.warning("conversation_memory: search failed, falling back (non-fatal): %s", e)
        return []
