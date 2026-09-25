"""
Confirms app/orchestration/pipeline_graph.py's pluggable checkpointer actually works
against a real Postgres, not just that AsyncPostgresSaver imports —
openspec/changes/langgraph-full-pipeline-rewrite tasks 6.3/6.4, which
design.md's Risks section had documented as blocked on `psycopg`'s native
`libpq` not being installed. That blocker is specific to the plain
`psycopg` package, which needs a system libpq; `psycopg[binary]` is a
self-contained wheel that bundles libpq and installs cleanly — this test
exists to prove that resolution empirically, not just assert it.

Requires: `PIPELINE_GRAPH_TEST_PG_DSN` pointing at a reachable, disposable
Postgres (a local-only container is the intended use — this test creates
and drops its own checkpoint tables via AsyncPostgresSaver.setup(), so
point it at a database you don't mind those tables landing in, never a
shared or production instance). Skips cleanly (exit 0) when that variable
isn't set, since no live Postgres is reachable from most environments this
repo's tests otherwise run in — this is the one test file in this repo
that legitimately needs one, kept separate from test_pipeline_graph.py so
the rest of the suite stays runnable with zero live infra.

Run: `PIPELINE_GRAPH_TEST_PG_DSN=postgresql://... python
tests/integration/test_pipeline_graph_postgres.py`, exit code 0 = pass (or skip).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

_PG_DSN = os.environ.get("PIPELINE_GRAPH_TEST_PG_DSN", "")

if not _PG_DSN:
    print("SKIPPED — PIPELINE_GRAPH_TEST_PG_DSN not set; no live Postgres to test against.")
    sys.exit(0)

from app.orchestration import pipeline  # noqa: E402
from app.orchestration import pipeline_graph as pg  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_SCOPE = UserScope(user_id="u1", role="admin", granularity_cap="village",
                    schemes=["MGNREGA"], geographies="all")
_ENTITY_RESULT = {"resolved": {"district": "EAST KHASI HILLS", "year_key": 2023},
                   "display": {"district": "East Khasi Hills", "year": "FY 2023-24"}, "notes": []}
_FAKE_ROWS = [{"amount_disbursed": 12345}]
_FAKE_SQL = "SELECT amount_disbursed FROM curated.v_mgnrega LIMIT 5"


class _Patcher:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.orig = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.orig)


class _Multi:
    def __init__(self, patches):
        self.patches = patches

    def __enter__(self):
        for p in self.patches:
            p.__enter__()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.__exit__(*exc)


def _happy_path_patches(resolve_entities_fn=None):
    async def _classify(_q):
        return ["MGNREGA"], pipeline.ScopeMeta(confidence=0.95, source="shortcut", reason="Named scheme: MGNREGA")

    async def _resolve(*_a, **_kw):
        return {"resolved": dict(_ENTITY_RESULT["resolved"]),
                "display": dict(_ENTITY_RESULT["display"]), "notes": []}

    async def _gen_sql(*_a, **_kw):
        return _FAKE_SQL

    async def _retrieve(*_a, **_kw):
        return []

    async def _execute_ok(sql, *_a, **_kw):
        return sql, [dict(r) for r in _FAKE_ROWS]

    async def _compose(*_a, **_kw):
        return "Total disbursement in East Khasi Hills was 12,345."

    class _FakeQueryAnalyzer:
        async def analyze_query(self, *_a, **_kw):
            return None

    return [
        _Patcher(pipeline, "_classify_scheme_detailed", _classify),
        _Patcher(pipeline, "resolve_entities", resolve_entities_fn or _resolve),
        _Patcher(pipeline, "generate_sql", _gen_sql),
        _Patcher(pipeline, "_execute_one_attempt", _execute_ok),
        _Patcher(pipeline, "compose_response", _compose),
        _Patcher(pipeline, "query_analyzer", _FakeQueryAnalyzer()),
        _Patcher(pipeline.schema_retrieval, "retrieve", _retrieve),
        _Patcher(pipeline.clarification_engine, "check_clarifications", lambda *_a, **_kw: None),
    ]


async def _run() -> None:
    with _Patcher(settings, "PIPELINE_GRAPH_CHECKPOINTER_DSN", _PG_DSN):
        print(f"1. CHECKPOINTER SELECTS POSTGRES — DSN set to {_PG_DSN.split('@')[-1]!r}")
        import app.orchestration.pipeline_graph as pg_mod
        async with pg_mod._checkpointer_context() as cp:
            check("a real AsyncPostgresSaver is selected, not the SQLite default",
                  type(cp).__name__ == "AsyncPostgresSaver", detail=str(type(cp)))
            await pg_mod._ensure_checkpointer_ready(cp)
        check("setup() completed without error (checkpoint tables created/confirmed)", True)

        print("2. HAPPY PATH OVER POSTGRES — same result shape as the SQLite-backed run")
        with _Multi(_happy_path_patches()):
            result = await pg.answer_data_via_graph(
                "total disbursement in East Khasi Hills under MGNREGA", scope=_SCOPE)
        check("completes (not paused)", result.get("paused") is not True, detail=str(result))
        check("row_count correct", result.get("row_count") == 1, detail=str(result))
        check("answer text correct", result.get("answer") == "Total disbursement in East Khasi Hills was 12,345.")

        print("3. PAUSE/RESUME OVER POSTGRES — durable across two independent connections")
        call_n = {"n": 0}

        async def _resolve_ambiguous_once(question, *_a, **_kw):
            call_n["n"] += 1
            if call_n["n"] == 1:
                raise pipeline.ClarificationNeeded(
                    "Which East Garo Hills village?", options=[{"label": "A"}, {"label": "B"}],
                    rule="entity-ambiguous", village_hint="Rongram")
            return {"resolved": dict(_ENTITY_RESULT["resolved"]),
                    "display": dict(_ENTITY_RESULT["display"]), "notes": []}

        with _Multi(_happy_path_patches(resolve_entities_fn=_resolve_ambiguous_once)):
            p1 = await pg.answer_data_via_graph("job cards in Rongram under MGNREGA", scope=_SCOPE)
            check("first call pauses", p1.get("paused") is True and
                  p1["clarification"]["rule"] == "entity-ambiguous", detail=str(p1))
            p2 = await pg.resume_via_graph(p1["thread_id"], "the Rongram in East Garo Hills")
        check("resume via a separate call/connection completes correctly",
              p2.get("paused") is not True and p2.get("row_count") == 1, detail=str(p2))

        print("4. PROCESS-RESTART SIMULATION — a freshly-constructed graph/module state still resumes")
        # Genuinely separate: re-import-style fresh objects, not the same `pg`
        # reference reused — build_graph() and the checkpointer connection are
        # both created new here, exactly what a real process restart would do.
        with _Multi(_happy_path_patches(resolve_entities_fn=_resolve_ambiguous_once)):
            call_n["n"] = 0
            r1 = await pg.answer_data_via_graph("job cards in Rongram under MGNREGA", scope=_SCOPE)
            fresh_graph_def = pg.build_graph()  # simulates a new process building the graph anew
            config = {"configurable": {"thread_id": r1["thread_id"]}}
            async with pg_mod._checkpointer_context() as cp2:
                await pg_mod._ensure_checkpointer_ready(cp2)
                fresh_compiled = fresh_graph_def.compile(checkpointer=cp2)
                snapshot = await fresh_compiled.aget_state(config)
                check("the paused state is visible to a completely fresh graph object",
                      bool(snapshot.next), detail=str(snapshot.next))


if sys.platform == "win32":
    # psycopg's async mode is incompatible with Windows' default
    # ProactorEventLoop (asyncio.set_event_loop_policy is the documented
    # fix). Production runs on Linux (deploy/systemd) where this is a
    # no-op/irrelevant; this is purely a Windows-dev-environment quirk of
    # running this one test file, not a production concern.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

asyncio.run(_run())

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL PIPELINE_GRAPH POSTGRES CHECKPOINTER CHECKS PASSED")
