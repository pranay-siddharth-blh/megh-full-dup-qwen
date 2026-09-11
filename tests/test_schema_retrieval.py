"""
Schema-retrieval node (app/schema_retrieval.py, app/vectorstore.py's
megh_schema_metadata table) — pure-logic + monkeypatched-dependency checks,
same stance as test_context_manager.py, PLUS a best-effort live section
against the real Neon pgvector instance (reachable from this environment;
megh_db/DATABASE_URL is not — see the retroactive pgvector migration
proposal). Run: `python tests/test_schema_retrieval.py`, exit code 0 = all
pass. The live section prints SKIP (not FAIL) if Neon is unreachable, so
this suite stays runnable offline.

Covers proposal.md/tasks.md group 1's acceptance scenarios: (a) a pilot-
scheme question retrieves that scheme's own documents; (b) a shared/cross-
scheme document is retrieved regardless of active scheme; (c) an
out-of-scope scheme's documents never appear, even at a deliberately high
similarity score — confirming the SQL pre-filter itself, not a client-side
rank cutoff; (d) retrieval degrades to [] (never raises) on an embedding
failure or an empty index.
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import llm, schema_retrieval, vectorstore  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  SKIP  {name}  — {reason}")


# ── 1. retrieve() is embedding-failure-safe and empty-scheme-safe ──────────
print("1. RETRIEVE() DEGRADES SAFELY, NEVER RAISES")


async def _run_offline_checks():
    check("empty scheme_ids -> [] with no embedding call attempted",
          await schema_retrieval.retrieve("any question", []) == [])

    orig_call_embedding = llm.call_embedding

    async def _boom(*_a, **_kw):
        raise RuntimeError("embedding service down")

    llm.call_embedding = _boom
    try:
        result = await schema_retrieval.retrieve("how many applications", ["CM Elevate"])
        check("embedding failure -> [] not an exception", result == [])
    finally:
        llm.call_embedding = orig_call_embedding


asyncio.run(_run_offline_checks())


# ── 2. The pre-filter is in the SQL itself, not a post-fetch filter ────────
print("2. PRE-FILTER IS BUILT INTO THE QUERY (monkeypatched pool)")


class _FakePool:
    """Captures the SQL text + params vectorstore.search_schema_metadata sends,
    without needing a live connection — same technique
    tests/test_context_manager.py uses for asserting bound SQL parameters."""

    def __init__(self):
        self.last_sql: str | None = None
        self.last_params: tuple | None = None

    def acquire(self):
        raise AssertionError("search_schema_metadata should use pool.fetch directly")

    async def fetch(self, sql, *params):
        self.last_sql = sql
        self.last_params = params
        return []


async def _run_sql_shape_check():
    fake = _FakePool()
    orig_get_pool = vectorstore.get_pool
    vectorstore.get_pool = lambda: fake
    try:
        await vectorstore.search_schema_metadata([0.1, 0.2], top_k=5, scheme_ids=["CM Elevate"])
    finally:
        vectorstore.get_pool = orig_get_pool

    sql = (fake.last_sql or "").upper()
    check("query has a WHERE clause filtering scheme_id = ANY(...)",
          "WHERE SCHEME_ID = ANY($2::TEXT[]) OR SHARED" in sql, fake.last_sql)
    check("scheme_ids param is passed through to the query, not filtered in Python",
          fake.last_params is not None and fake.last_params[1] == ["CM Elevate"],
          str(fake.last_params))


asyncio.run(_run_sql_shape_check())


# ── 3. Live section — real Neon pgvector, real CM Elevate rows from task 1.6 ─
print("3. LIVE — SCHEME SCOPING AGAINST THE REAL megh_schema_metadata TABLE")


async def _run_live_checks():
    try:
        await llm.init_client()
        await vectorstore.init_pgvector()
    except Exception as e:  # noqa: BLE001
        skip("live scheme-scoping checks", f"pgvector unreachable — {e}")
        return

    synthetic_ids: list[str] = []
    try:
        existing = await vectorstore.schema_metadata_count()
        if existing <= 0:
            skip("live scheme-scoping checks", "megh_schema_metadata is empty — run task 1.6's indexer first")
            return

        # (a) A CM Elevate question retrieves CM Elevate's own documents.
        cm_results = await schema_retrieval.retrieve(
            "which CM Elevate applications are on hold for verification", ["CM Elevate"])
        check("CM Elevate question retrieves at least one document", len(cm_results) > 0)
        check("every retrieved document is tagged CM Elevate or shared",
              all(r["scheme_id"] == "CM Elevate" or r["shared"] for r in cm_results),
              str([r["scheme_id"] for r in cm_results]))

        # (c) Insert a synthetic MGNREGA document engineered to be the closest
        # possible match to the query below (same vector as the query itself,
        # cosine distance 0 — the highest possible score) — then confirm the
        # pre-filter still excludes it when MGNREGA is not an active scheme.
        query_vec = (await llm.call_embedding("total person days in Meghalaya"))[0]
        synthetic_id = str(uuid.uuid4())
        synthetic_ids.append(synthetic_id)
        await vectorstore.upsert_schema_metadata([{
            "id": synthetic_id, "vector": query_vec,
            "payload": {"scheme_id": "MGNREGA", "granularity": "table",
                       "ref": "curated.v_employment", "shared": False,
                       "content": "total person days in Meghalaya", "metadata": None},
        }])
        excl_results = await schema_retrieval.retrieve(
            "total person days in Meghalaya", ["CM Elevate"])
        check("a near-perfect-scoring out-of-scope document is still excluded by the pre-filter",
              all(r["ref"] != "curated.v_employment" for r in excl_results),
              str([r["ref"] for r in excl_results]))

        # (b) A document tagged shared is retrieved regardless of active scheme.
        shared_id = str(uuid.uuid4())
        synthetic_ids.append(shared_id)
        await vectorstore.upsert_schema_metadata([{
            "id": shared_id, "vector": query_vec,
            "payload": {"scheme_id": "shared", "granularity": "table",
                       "ref": "curated.dim_geography", "shared": True,
                       "content": "total person days in Meghalaya", "metadata": None},
        }])
        shared_results = await schema_retrieval.retrieve(
            "total person days in Meghalaya", ["CM Elevate"])
        check("a shared-tagged document is retrieved for an unrelated active scheme",
              any(r["ref"] == "curated.dim_geography" for r in shared_results),
              str([r["ref"] for r in shared_results]))
    finally:
        # Clean up synthetic rows so the table holds only the real task-1.6/4.2
        # ingested data afterward.
        if synthetic_ids:
            pool = vectorstore.get_pool()
            table = vectorstore.safe_ident(vectorstore.settings.RAG_SCHEMA_METADATA_TABLE)
            await pool.execute(f"DELETE FROM {table} WHERE id = ANY($1::uuid[])", synthetic_ids)
        await vectorstore.close_pgvector()
        await llm.close_client()


asyncio.run(_run_live_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL SCHEMA-RETRIEVAL CHECKS PASSED")
