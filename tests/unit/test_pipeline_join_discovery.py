"""
Group 3 (proposal.md/tasks.md) — join discovery wired into
app/orchestration/pipeline.py's generate_sql(). Pure-logic + monkeypatched-dependency
checks, no DB, no model gateway, no pgvector. Run:
`python tests/unit/test_pipeline_join_discovery.py`, exit code 0 = pass.

Confirms the enforcement-tier split from design.md: generate_sql() raises
the existing ClarificationNeeded (app/orchestration/pipeline.py:83) BEFORE calling the
SQL generator when schema-retrieval itself names 2 tables with no safe
join path, but proceeds normally (additive hint only, or no hint at all)
whenever retrieval returns fewer than 2 table-granularity candidates —
which is every scheme piloted so far, since each has exactly one fact
table.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.sql import join_graph  # noqa: E402
from app.clients import llm
from app.orchestration import pipeline
from app.sql import schema_retrieval

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


join_graph.build(force=True)
_ENTITY_RESULT = {"resolved": {}, "notes": [], "display": {}}

_UNSAFE_PAIR = [
    {"score": 0.9, "scheme_id": "PMAY-G", "granularity": "table",
     "ref": "curated.v_pmay", "shared": False, "content": "PMAY house facts.", "metadata": {}},
    {"score": 0.85, "scheme_id": "MGNREGA", "granularity": "table",
     "ref": "curated.fact_mgnrega_employment", "shared": False,
     "content": "MGNREGA employment facts.", "metadata": {}},
]
_SAFE_PAIR = [
    {"score": 0.9, "scheme_id": "MGNREGA", "granularity": "table",
     "ref": "curated.fact_mgnrega_employment", "shared": False,
     "content": "MGNREGA employment facts.", "metadata": {}},
    {"score": 0.85, "scheme_id": "shared", "granularity": "table",
     "ref": "curated.dim_geography", "shared": True,
     "content": "Geography dimension.", "metadata": {}},
]
_SINGLE_TABLE = [
    {"score": 0.9, "scheme_id": "CM Elevate", "granularity": "table",
     "ref": "curated.v_cm_elevate", "shared": False,
     "content": "CM Elevate applications.", "metadata": {}},
]


async def _run():
    captured_prompts: list[str] = []

    async def _fake_sql_generator(prompt, **_kw):
        captured_prompts.append(prompt)
        return "SELECT 1;"

    orig_call_sql_generator = llm.call_sql_generator
    llm.call_sql_generator = _fake_sql_generator

    orig_retrieve = schema_retrieval.retrieve
    _next_retrieved: list[dict] = []

    async def _fake_retrieve(question, scheme_ids):
        return _next_retrieved

    schema_retrieval.retrieve = _fake_retrieve
    try:
        # ── 1. An unsafe (cross-scheme, no-path) pair gates generation ──────
        print("1. UNSAFE RETRIEVED PAIR RAISES CLARIFICATION BEFORE GENERATION")
        _next_retrieved[:] = _UNSAFE_PAIR
        raised = False
        try:
            await pipeline.generate_sql("compare PMAY and MGNREGA directly",
                                        ["PMAY-G", "MGNREGA"], _ENTITY_RESULT)
        except pipeline.ClarificationNeeded as e:
            raised = True
            check("ClarificationNeeded carries a join-related rule tag",
                  e.rule in ("join-no-path", "join-fan-out"), e.rule)
        check("generate_sql raised ClarificationNeeded instead of calling the SQL generator", raised)
        check("the SQL generator was never invoked for the unsafe pair",
              len(captured_prompts) == 0, str(len(captured_prompts)))

        # ── 2. A safe pair (real FK) proceeds and gets the hint in-prompt ───
        print("2. SAFE RETRIEVED PAIR PROCEEDS, HINT FOLDED INTO THE PROMPT")
        _next_retrieved[:] = _SAFE_PAIR
        await pipeline.generate_sql("person days by village", ["MGNREGA"], _ENTITY_RESULT)
        check("SQL generator was called (no gate)", len(captured_prompts) == 1)
        check("prompt includes the additive REQUIRED JOIN(S) hint",
              "REQUIRED JOIN(S)" in captured_prompts[-1])

        # ── 3. Fewer than 2 table candidates: no gate, no hint ──────────────
        print("3. FEWER THAN 2 TABLE CANDIDATES: UNCHANGED BEHAVIOR")
        _next_retrieved[:] = _SINGLE_TABLE
        await pipeline.generate_sql("how many applications are on hold?",
                                    ["CM Elevate"], _ENTITY_RESULT)
        check("SQL generator was called (no gate)", len(captured_prompts) == 2)
        check("no REQUIRED JOIN(S) hint when fewer than 2 tables were retrieved",
              "REQUIRED JOIN(S)" not in captured_prompts[-1])

        _next_retrieved[:] = []
        await pipeline.generate_sql("how many applications total?", ["CM Elevate"], _ENTITY_RESULT)
        check("zero retrieved tables: SQL generator still called normally",
              len(captured_prompts) == 3)
    finally:
        llm.call_sql_generator = orig_call_sql_generator
        schema_retrieval.retrieve = orig_retrieve


asyncio.run(_run())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL PIPELINE JOIN-DISCOVERY WIRING CHECKS PASSED")
