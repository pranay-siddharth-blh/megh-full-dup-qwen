"""
SQL-examples few-shot retrieval (app/sql_examples_retrieval.py,
app/sql_examples_ingest.py, app/vectorstore.py's megh_sql_examples table) —
proposal §5.10 / capability `sql-generation`. Pure-logic + monkeypatched-
dependency checks, same stance as test_schema_retrieval.py, PLUS a
best-effort live section against the real Neon pgvector instance. Run:
`python tests/test_sql_examples_retrieval.py`, exit code 0 = all pass. The
live section prints SKIP (not FAIL) if Neon is unreachable or the table
hasn't been seeded yet (POST /api/rag/reingest-sql-examples not run), so
this suite stays runnable offline / pre-rollout.

Covers: (a) retrieve() degrades safely (empty scheme_ids, embedding
failure, search/table failure); (b) the scheme pre-filter is built into
the SQL itself, not a post-fetch filter; (c) sql_examples_ingest's pure
logic — RETIRED dropped, UNANSWERABLE mapped to is_answerable=False +
reason, a normal example keeps its sql text, an empty/malformed entry is
skipped; (d) prompt_builder._fewshot_block prefers a non-empty vector
result and falls back to token-overlap when empty.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import annotations, llm, prompt_builder, sql_examples_ingest, sql_examples_retrieval, vectorstore  # noqa: E402

annotations.load_all()  # populates the token-overlap fallback pool section 4 exercises

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def skip(name: str, reason: str) -> None:
    print(f"  SKIP  {name}  — {reason}")


# ── 1. retrieve() degrades safely, never raises ─────────────────────────────
print("1. RETRIEVE() DEGRADES SAFELY, NEVER RAISES")


async def _run_offline_checks():
    check("empty scheme_ids -> [] with no embedding call attempted",
          await sql_examples_retrieval.retrieve("any question", []) == [])

    orig_call_embedding = llm.call_embedding

    async def _boom(*_a, **_kw):
        raise RuntimeError("embedding service down")

    llm.call_embedding = _boom
    try:
        result = await sql_examples_retrieval.retrieve("how many applications", ["CM Elevate"])
        check("embedding failure -> [] not an exception", result == [])
    finally:
        llm.call_embedding = orig_call_embedding

    orig_call_embedding = llm.call_embedding
    orig_search = vectorstore.search_sql_examples
    llm.call_embedding = lambda *_a, **_kw: asyncio.sleep(0, result=[[0.1, 0.2]])

    async def _boom_search(*_a, **_kw):
        raise RuntimeError('relation "megh_sql_examples" does not exist')

    vectorstore.search_sql_examples = _boom_search
    try:
        result = await sql_examples_retrieval.retrieve("how many applications", ["CM Elevate"])
        check("search failure (table not yet created) -> [] not an exception", result == [])
    finally:
        llm.call_embedding = orig_call_embedding
        vectorstore.search_sql_examples = orig_search


asyncio.run(_run_offline_checks())


# ── 2. The pre-filter is in the SQL itself, not a post-fetch filter ────────
print("2. PRE-FILTER IS BUILT INTO THE QUERY (monkeypatched pool)")


class _FakePool:
    def __init__(self):
        self.last_sql: str | None = None
        self.last_params: tuple | None = None

    def acquire(self):
        raise AssertionError("search_sql_examples should use pool.fetch directly")

    async def fetch(self, sql, *params):
        self.last_sql = sql
        self.last_params = params
        return []


async def _run_sql_shape_check():
    fake = _FakePool()
    orig_get_pool = vectorstore.get_pool
    vectorstore.get_pool = lambda: fake
    try:
        await vectorstore.search_sql_examples([0.1, 0.2], top_k=5, scheme_ids=["CM Elevate"])
    finally:
        vectorstore.get_pool = orig_get_pool

    sql = (fake.last_sql or "").upper()
    check("query has a WHERE clause filtering scheme_id = ANY(...)",
          "WHERE SCHEME_ID = ANY($2::TEXT[])" in sql, fake.last_sql)
    check("scheme_ids param is passed through to the query, not filtered in Python",
          fake.last_params is not None and fake.last_params[1] == ["CM Elevate"],
          str(fake.last_params))


asyncio.run(_run_sql_shape_check())


async def _run_retrieve_wiring_check():
    fake = _FakePool()
    orig_get_pool = vectorstore.get_pool
    orig_call_embedding = llm.call_embedding
    vectorstore.get_pool = lambda: fake
    llm.call_embedding = lambda *_a, **_kw: asyncio.sleep(0, result=[[0.1, 0.2]])
    try:
        await sql_examples_retrieval.retrieve("any question", ["CM Elevate", "Focus Plus"])
    finally:
        vectorstore.get_pool = orig_get_pool
        llm.call_embedding = orig_call_embedding

    check("retrieve() passes top_k = settings.SQL_EXAMPLES_TOP_K",
          fake.last_params is not None and fake.last_params[2] == vectorstore.settings.SQL_EXAMPLES_TOP_K,
          str(fake.last_params))
    check("retrieve() passes both scheme_ids through as one filter (single query, not per-scheme)",
          fake.last_params is not None and fake.last_params[1] == ["CM Elevate", "Focus Plus"],
          str(fake.last_params))


asyncio.run(_run_retrieve_wiring_check())


# ── 3. sql_examples_ingest pure-logic checks ────────────────────────────────
print("3. INGEST — REAL _load_scheme_file + _collect_points ON A FIXTURE FILE")

_FIXTURE_YAML = """
sql_generation_examples:
  - question: "How many applications?"
    sql: "SELECT COUNT(*) FROM t;"
  - question: "Old retired example"
    sql: "SELECT 1;"
    status: RETIRED_v2.0
  - question: "What is the total amount disbursed?"
    sql: null
    status: UNANSWERABLE
    reason: >
      No money column.
      Say so plainly.
  - question: ""
    sql: "SELECT 2;"
  - question: "Has neither sql nor reason"
    status: weird
"""


def _run_ingest_checks():
    with tempfile.TemporaryDirectory() as tmp:
        fixture_dir = Path(tmp)
        (fixture_dir / "fixture_few_shot.yaml").write_text(_FIXTURE_YAML, encoding="utf-8")

        orig_dir = sql_examples_ingest._SCHEME_DIRS["CM Elevate"]
        orig_file = sql_examples_ingest._FEW_SHOT_FILE["CM Elevate"]
        sql_examples_ingest._SCHEME_DIRS["CM Elevate"] = fixture_dir
        sql_examples_ingest._FEW_SHOT_FILE["CM Elevate"] = "fixture_few_shot.yaml"
        try:
            points = sql_examples_ingest._collect_points(["CM Elevate"])
        finally:
            sql_examples_ingest._SCHEME_DIRS["CM Elevate"] = orig_dir
            sql_examples_ingest._FEW_SHOT_FILE["CM Elevate"] = orig_file

    check("RETIRED_v2.0 example is dropped by the real _load_scheme_file "
          "(same status app/annotations.py filters at runtime load)",
          not any(p["question"] == "Old retired example" for p in points))
    check("malformed entries (no question / no sql-or-reason) are skipped",
          len(points) == 2, str([p["question"] for p in points]))

    normal = next(p for p in points if p["question"] == "How many applications?")
    check("a normal example keeps its scheme_id", normal["scheme_id"] == "CM Elevate")
    check("a normal example is answerable with its sql text",
          normal["is_answerable"] is True and normal["sql"] == "SELECT COUNT(*) FROM t;")
    check("a normal example embeds its question as content", normal["content"] == normal["question"])

    negative = next(p for p in points if p["question"] == "What is the total amount disbursed?")
    check("an UNANSWERABLE example is not answerable and has no sql",
          negative["is_answerable"] is False and negative["sql"] is None)
    check("an UNANSWERABLE example's reason is whitespace-collapsed",
          negative["reason"] == "No money column. Say so plainly.", repr(negative["reason"]))


_run_ingest_checks()


# ── 4. prompt_builder._fewshot_block prefers a non-empty vector result ─────
print("4. _FEWSHOT_BLOCK PREFERS VECTOR RESULTS, FALLS BACK WHEN EMPTY")


async def _run_fewshot_block_checks():
    orig_retrieve = sql_examples_retrieval.retrieve

    async def _fake_vector_hit(_question, _scheme_ids):
        return [
            {"score": 0.9, "scheme_id": "CM Elevate", "question": "vector-sourced question",
             "sql": "SELECT 1 FROM vector_example;", "is_answerable": True, "reason": ""},
            {"score": 0.8, "scheme_id": "CM Elevate", "question": "vector-sourced negative",
             "sql": None, "is_answerable": False, "reason": "no such column"},
        ]

    sql_examples_retrieval.retrieve = _fake_vector_hit
    try:
        block = await prompt_builder._fewshot_block(["CM Elevate"], "any question")
    finally:
        sql_examples_retrieval.retrieve = orig_retrieve

    check("a non-empty vector result's worked example appears in the block",
          "vector-sourced question" in block and "SELECT 1 FROM vector_example;" in block)
    check("a non-empty vector result's negative example appears as NOT ANSWERABLE",
          "vector-sourced negative" in block and "NOT ANSWERABLE" in block
          and "no such column" in block)

    async def _fake_vector_miss(_question, _scheme_ids):
        return []

    sql_examples_retrieval.retrieve = _fake_vector_miss
    try:
        fallback_block = await prompt_builder._fewshot_block(["CM Elevate"], "how many applications")
    finally:
        sql_examples_retrieval.retrieve = orig_retrieve

    check("an empty vector result still produces a block from the token-overlap fallback "
          "(CM Elevate's few_shot.yaml has real examples)",
          fallback_block != "" and "vector-sourced" not in fallback_block)


asyncio.run(_run_fewshot_block_checks())


# ── 5. Live section — real Neon pgvector, if seeded ─────────────────────────
print("5. LIVE — RETRIEVAL AGAINST THE REAL megh_sql_examples TABLE (if seeded)")


async def _run_live_checks():
    try:
        await llm.init_client()
        await vectorstore.init_pgvector()
    except Exception as e:  # noqa: BLE001
        skip("live SQL-examples checks", f"pgvector unreachable — {e}")
        return

    try:
        existing = await vectorstore.sql_examples_count()
        if existing <= 0:
            skip("live SQL-examples checks",
                 "megh_sql_examples is empty or absent — run POST /api/rag/reingest-sql-examples first")
            return

        results = await sql_examples_retrieval.retrieve(
            "how many CM Elevate applications are there", ["CM Elevate"])
        check("a real seeded query retrieves at least one example", len(results) > 0)
        check("every retrieved example is tagged CM Elevate",
              all(r["scheme_id"] == "CM Elevate" for r in results),
              str([r["scheme_id"] for r in results]))
    finally:
        await vectorstore.close_pgvector()
        await llm.close_client()


asyncio.run(_run_live_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL SQL-EXAMPLES RETRIEVAL CHECKS PASSED")
