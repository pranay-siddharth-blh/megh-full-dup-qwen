"""
PostgreSQL + pgvector access for the scheme-knowledge base (the RAG path).

One module-level asyncpg pool, opened at startup and closed at shutdown —
same reasoning as the megh_db pool in app/database/db.py and the shared httpx client.
This pool talks to a dedicated Postgres instance (VECTOR_DB_URL, falls back
to DATABASE_URL when blank) with the pgvector extension enabled, kept
separate from megh_db so RAG writes (KB ingest, conversation-memory inserts)
never need anything beyond the read-only megh_readonly role that
DATABASE_URL uses in production.

Public shape (collection_count / recreate_collection / upsert / search)
mirrors the Qdrant-backed store this replaced, so app/knowledge/rag.py and
app/knowledge/kb_ingest.py needed no logic changes — only app/main.py's init/close
calls and app/conversation/conversation_memory.py's storage internals moved over.
"""
import json
import logging
import re

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def safe_ident(name: str) -> str:
    """Validate a config-supplied table/index name before interpolating it into
    SQL (asyncpg has no way to bind identifiers as parameters). Table names
    here come from settings, not user input, but this keeps a bad config
    value from doing anything worse than a clear startup error."""
    if not _IDENT.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def vec_literal(vector: list[float]) -> str:
    """pgvector's text input format, e.g. "[0.1,0.2,...]" — passed as a plain
    string parameter and cast with ::vector in SQL, so no extra client-side
    codec (the `pgvector` package's asyncpg registration) is needed."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def _dsn() -> str:
    url = settings.VECTOR_DB_URL or settings.DATABASE_URL
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def init_pgvector() -> None:
    global _pool
    _pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=10, timeout=30)
    async with _pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    logger.info("pgvector pool ready")


async def close_pgvector() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("pgvector pool not initialized — call init_pgvector() at startup")
    return _pool


async def collection_count() -> int:
    """Row count for the KB table, or -1 if the table is absent."""
    pool = get_pool()
    table = safe_ident(settings.RAG_KB_TABLE)
    try:
        return await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
    except asyncpg.UndefinedTableError:
        return -1


async def recreate_collection(dim: int) -> None:
    pool = get_pool()
    table = safe_ident(settings.RAG_KB_TABLE)
    async with pool.acquire() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await conn.execute(f"""
            CREATE TABLE {table} (
                id uuid PRIMARY KEY,
                scheme text,
                doc text,
                heading text,
                text text,
                source_type text,
                embedding vector({dim})
            )
        """)
        await conn.execute(
            f"CREATE INDEX ON {table} USING hnsw (embedding vector_cosine_ops)"
        )
        await conn.execute(f"CREATE INDEX ON {table} (scheme)")
    logger.info("pgvector table %s (re)created, dim=%d", table, dim)


async def upsert(points: list[dict]) -> None:
    """Each point: {id, vector, payload: {scheme, doc, heading, text, source_type}}."""
    pool = get_pool()
    table = safe_ident(settings.RAG_KB_TABLE)
    rows = [
        (
            p["id"],
            p["payload"].get("scheme"),
            p["payload"].get("doc"),
            p["payload"].get("heading"),
            p["payload"].get("text"),
            p["payload"].get("source_type"),
            vec_literal(p["vector"]),
        )
        for p in points
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            f"""INSERT INTO {table} (id, scheme, doc, heading, text, source_type, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7::vector)
                ON CONFLICT (id) DO UPDATE SET
                    scheme = EXCLUDED.scheme, doc = EXCLUDED.doc, heading = EXCLUDED.heading,
                    text = EXCLUDED.text, source_type = EXCLUDED.source_type,
                    embedding = EXCLUDED.embedding""",
            rows,
        )


async def schema_metadata_count() -> int:
    """Row count for the schema-metadata table, or -1 if the table is absent."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SCHEMA_METADATA_TABLE)
    try:
        return await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
    except asyncpg.UndefinedTableError:
        return -1


async def recreate_schema_metadata_table(dim: int) -> None:
    """megh_schema_metadata — scheme/table/column-granularity schema descriptions
    for the schema-retrieval node (see openspec/changes/
    phase-3-schema-retrieval-join-discovery). One table for the whole
    collection, mirroring megh_scheme_kb's shape rather than a kind-discriminated
    table shared with the KB or SQL-example collections."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SCHEMA_METADATA_TABLE)
    async with pool.acquire() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await conn.execute(f"""
            CREATE TABLE {table} (
                id uuid PRIMARY KEY,
                scheme_id text,
                granularity text,
                ref text,
                shared boolean NOT NULL DEFAULT false,
                content text,
                embedding vector({dim}),
                metadata jsonb,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        await conn.execute(
            f"CREATE INDEX ON {table} USING hnsw (embedding vector_cosine_ops)"
        )
        await conn.execute(f"CREATE INDEX ON {table} (scheme_id)")
    logger.info("pgvector table %s (re)created, dim=%d", table, dim)


async def upsert_schema_metadata(points: list[dict]) -> None:
    """Each point: {id, vector, payload: {scheme_id, granularity, ref, shared,
    content, metadata}}. `metadata` is an arbitrary JSON-able dict (synonyms,
    sample values, business-glossary terms) or None."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SCHEMA_METADATA_TABLE)
    rows = [
        (
            p["id"],
            p["payload"].get("scheme_id"),
            p["payload"].get("granularity"),
            p["payload"].get("ref"),
            bool(p["payload"].get("shared", False)),
            p["payload"].get("content"),
            vec_literal(p["vector"]),
            json.dumps(p["payload"]["metadata"]) if p["payload"].get("metadata") is not None else None,
        )
        for p in points
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            f"""INSERT INTO {table}
                    (id, scheme_id, granularity, ref, shared, content, embedding, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8::jsonb)
                ON CONFLICT (id) DO UPDATE SET
                    scheme_id = EXCLUDED.scheme_id, granularity = EXCLUDED.granularity,
                    ref = EXCLUDED.ref, shared = EXCLUDED.shared, content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding, metadata = EXCLUDED.metadata,
                    updated_at = now()""",
            rows,
        )


async def search_schema_metadata(vector: list[float], top_k: int,
                                 scheme_ids: list[str] | None = None) -> list[dict]:
    """Returns [{score, scheme_id, granularity, ref, content, shared, metadata}, ...]
    best score first. When `scheme_ids` is given, the pre-filter (WHERE clause,
    not a post-rank cutoff) restricts rows to scheme_id = ANY(scheme_ids) OR
    shared — an out-of-scope scheme's document is excluded even if it would
    otherwise rank highly."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SCHEMA_METADATA_TABLE)
    vec = vec_literal(vector)
    if scheme_ids:
        rows = await pool.fetch(
            f"""SELECT scheme_id, granularity, ref, content, shared, metadata,
                       1 - (embedding <=> $1::vector) AS score
                FROM {table}
                WHERE scheme_id = ANY($2::text[]) OR shared
                ORDER BY embedding <=> $1::vector
                LIMIT $3""",
            vec, scheme_ids, top_k,
        )
    else:
        rows = await pool.fetch(
            f"""SELECT scheme_id, granularity, ref, content, shared, metadata,
                       1 - (embedding <=> $1::vector) AS score
                FROM {table}
                ORDER BY embedding <=> $1::vector
                LIMIT $2""",
            vec, top_k,
        )
    return [
        {
            "score": float(r["score"]),
            "scheme_id": r["scheme_id"] or "",
            "granularity": r["granularity"] or "",
            "ref": r["ref"] or "",
            "content": r["content"] or "",
            "shared": bool(r["shared"]),
            "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
        }
        for r in rows
    ]


async def sql_examples_count() -> int:
    """Row count for the SQL-examples table, or -1 if the table is absent."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SQL_EXAMPLES_TABLE)
    try:
        return await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
    except asyncpg.UndefinedTableError:
        return -1


async def recreate_sql_examples_table(dim: int) -> None:
    """megh_sql_examples — seed question/SQL examples for testing SQL generation
    end to end (full example-pool growth is ongoing SME work, out of scope for
    this phase). Same one-table-per-collection pattern as the KB and
    schema-metadata tables."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SQL_EXAMPLES_TABLE)
    async with pool.acquire() as conn:
        await conn.execute(f"DROP TABLE IF EXISTS {table}")
        await conn.execute(f"""
            CREATE TABLE {table} (
                id uuid PRIMARY KEY,
                scheme_id text,
                question text,
                sql text,
                is_answerable boolean NOT NULL DEFAULT true,
                reason text,
                content text,
                embedding vector({dim}),
                updated_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        await conn.execute(
            f"CREATE INDEX ON {table} USING hnsw (embedding vector_cosine_ops)"
        )
        await conn.execute(f"CREATE INDEX ON {table} (scheme_id)")
    logger.info("pgvector table %s (re)created, dim=%d", table, dim)


async def upsert_sql_examples(points: list[dict]) -> None:
    """Each point: {id, vector, payload: {scheme_id, question, sql,
    is_answerable, reason, content}}."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SQL_EXAMPLES_TABLE)
    rows = [
        (
            p["id"],
            p["payload"].get("scheme_id"),
            p["payload"].get("question"),
            p["payload"].get("sql"),
            bool(p["payload"].get("is_answerable", True)),
            p["payload"].get("reason"),
            p["payload"].get("content"),
            vec_literal(p["vector"]),
        )
        for p in points
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            f"""INSERT INTO {table}
                    (id, scheme_id, question, sql, is_answerable, reason, content, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
                ON CONFLICT (id) DO UPDATE SET
                    scheme_id = EXCLUDED.scheme_id, question = EXCLUDED.question,
                    sql = EXCLUDED.sql, is_answerable = EXCLUDED.is_answerable,
                    reason = EXCLUDED.reason, content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding, updated_at = now()""",
            rows,
        )


async def search_sql_examples(vector: list[float], top_k: int,
                              scheme_ids: list[str] | None = None) -> list[dict]:
    """Returns [{score, scheme_id, question, sql, is_answerable, reason}, ...]
    best score first, pre-filtered to scheme_ids when given."""
    pool = get_pool()
    table = safe_ident(settings.RAG_SQL_EXAMPLES_TABLE)
    vec = vec_literal(vector)
    if scheme_ids:
        rows = await pool.fetch(
            f"""SELECT scheme_id, question, sql, is_answerable, reason,
                       1 - (embedding <=> $1::vector) AS score
                FROM {table}
                WHERE scheme_id = ANY($2::text[])
                ORDER BY embedding <=> $1::vector
                LIMIT $3""",
            vec, scheme_ids, top_k,
        )
    else:
        rows = await pool.fetch(
            f"""SELECT scheme_id, question, sql, is_answerable, reason,
                       1 - (embedding <=> $1::vector) AS score
                FROM {table}
                ORDER BY embedding <=> $1::vector
                LIMIT $2""",
            vec, top_k,
        )
    return [
        {
            "score": float(r["score"]),
            "scheme_id": r["scheme_id"] or "",
            "question": r["question"] or "",
            "sql": r["sql"],
            "is_answerable": bool(r["is_answerable"]),
            "reason": r["reason"] or "",
        }
        for r in rows
    ]


async def search(vector: list[float], top_k: int, scheme: str | None = None) -> list[dict]:
    """Returns [{score, text, doc, heading, scheme, source_type}, ...] best score
    first. `scheme`, when given, restricts the search to rows tagged with that
    exact scheme — every row carries a `scheme` tag at ingest time
    (kb_ingest.py), but without this filter search runs unscoped across the
    whole table and can blend another scheme's content into the answer."""
    pool = get_pool()
    table = safe_ident(settings.RAG_KB_TABLE)
    vec = vec_literal(vector)
    if scheme:
        rows = await pool.fetch(
            f"""SELECT text, doc, heading, scheme, source_type,
                       1 - (embedding <=> $1::vector) AS score
                FROM {table}
                WHERE scheme = $2
                ORDER BY embedding <=> $1::vector
                LIMIT $3""",
            vec, scheme, top_k,
        )
    else:
        rows = await pool.fetch(
            f"""SELECT text, doc, heading, scheme, source_type,
                       1 - (embedding <=> $1::vector) AS score
                FROM {table}
                ORDER BY embedding <=> $1::vector
                LIMIT $2""",
            vec, top_k,
        )
    return [
        {
            "score": float(r["score"]),
            "text": r["text"] or "",
            "doc": r["doc"] or "",
            "heading": r["heading"] or "",
            "scheme": r["scheme"] or "",
            "source_type": r["source_type"] or "sme",
        }
        for r in rows
    ]
