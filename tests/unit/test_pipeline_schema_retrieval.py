"""
Group 2 (proposal.md/tasks.md) — schema retrieval wired into
app/orchestration/pipeline.py's generate_sql(), via app/sql/prompt_builder.py's new
`retrieved` parameter. Pure-logic + monkeypatched-dependency checks, no DB,
no model gateway, no pgvector — same stance as test_context_manager.py.
Run: `python tests/unit/test_pipeline_schema_retrieval.py`, exit code 0 = pass.

Confirms: (1) prompt_builder.build_sql_prompt is byte-for-byte unchanged
from its pre-Phase-3 output when `retrieved` is empty/omitted — the
additive, never-gating contract from design.md; (2) a non-empty `retrieved`
list appends a clearly-labelled block, not a silent mutation of the
existing schema-context sections; (3) app/orchestration/pipeline.py's generate_sql()
actually calls schema_retrieval.retrieve() and threads its result into the
prompt the SQL generator sees.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.clients import llm  # noqa: E402
from app.orchestration import pipeline
from app.sql import prompt_builder, schema_retrieval, sql_examples_retrieval

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_ENTITY_RESULT = {"resolved": {}, "notes": [], "display": {}}

# §5.10: prompt_builder.build_sql_prompt now awaits
# sql_examples_retrieval.retrieve() before falling back to the
# token-overlap YAML path. Force the fallback deterministically for every
# call in this file — this suite's own stated stance is "no model gateway,
# no pgvector", and a live embedding/pgvector call here would silently
# violate that (and make the byte-for-byte-unchanged assertions below
# depend on network reachability). See tests/unit/test_sql_examples_retrieval.py
# for the vector-path-itself coverage.
_orig_sql_examples_retrieve = sql_examples_retrieval.retrieve


async def _no_vector_examples(*_a, **_kw):
    return []


sql_examples_retrieval.retrieve = _no_vector_examples


async def _build(*args, **kwargs) -> str:
    return await prompt_builder.build_sql_prompt(*args, **kwargs)


# ── 1. Empty/omitted `retrieved` leaves the prompt unchanged ───────────────
print("1. RETRIEVED=[] IS BYTE-FOR-BYTE UNCHANGED FROM BEFORE PHASE 3")


async def _run_group1():
    baseline = await _build("how many applications are on hold?",
                            ["CM Elevate"], _ENTITY_RESULT)
    with_empty = await _build("how many applications are on hold?",
                              ["CM Elevate"], _ENTITY_RESULT, retrieved=[])
    with_none = await _build("how many applications are on hold?",
                             ["CM Elevate"], _ENTITY_RESULT, retrieved=None)
    check("retrieved=[] produces the exact same prompt as omitting the argument",
          with_empty == baseline)
    check("retrieved=None produces the exact same prompt as omitting the argument",
          with_none == baseline)
    check("no 'RETRIEVED SCHEMA NOTES' block appears when nothing was retrieved",
          "RETRIEVED SCHEMA NOTES" not in baseline)


asyncio.run(_run_group1())


# ── 2. A non-empty `retrieved` list appends a clearly-labelled block ───────
print("2. NON-EMPTY RETRIEVED APPENDS A LABELLED, ADDITIVE BLOCK")

sample_retrieved = [
    {"score": 0.81, "scheme_id": "CM Elevate", "granularity": "column",
     "ref": "curated.v_cm_elevate.data_verified", "shared": False,
     "content": "data_verified is the verification-outcome status column.",
     "metadata": {}},
]
question = "which applications are on hold?"


async def _run_group2():
    without_retrieval = await _build(question, ["CM Elevate"], _ENTITY_RESULT)
    with_retrieval = await _build(question, ["CM Elevate"], _ENTITY_RESULT,
                                  retrieved=sample_retrieved)
    check("the labelled block is present", "RETRIEVED SCHEMA NOTES" in with_retrieval)
    check("the retrieved document's ref appears in the prompt",
          "curated.v_cm_elevate.data_verified" in with_retrieval)
    check("the retrieved document's content appears in the prompt",
          "verification-outcome status column" in with_retrieval)
    check("every line of the un-retrieved prompt still appears in the retrieval-augmented "
          "prompt (additive, not a replacement)",
          all(line in with_retrieval for line in without_retrieval.splitlines()))


asyncio.run(_run_group2())


# ── 3. pipeline.generate_sql() actually calls retrieve() and threads it through ─
print("3. GENERATE_SQL WIRES SCHEMA-RETRIEVAL INTO THE SQL-GENERATION PROMPT")


async def _run():
    captured_prompts: list[str] = []

    async def _fake_sql_generator(prompt, **_kw):
        captured_prompts.append(prompt)
        return "SELECT 1;"

    orig_call_sql_generator = llm.call_sql_generator
    llm.call_sql_generator = _fake_sql_generator

    orig_retrieve = schema_retrieval.retrieve

    async def _fake_retrieve(question, scheme_ids):
        if "CM Elevate" in scheme_ids:
            return sample_retrieved
        return []

    schema_retrieval.retrieve = _fake_retrieve
    try:
        await pipeline.generate_sql("which applications are on hold?", ["CM Elevate"], _ENTITY_RESULT)
        check("generate_sql's prompt to the SQL generator includes the retrieved block",
              "RETRIEVED SCHEMA NOTES" in captured_prompts[-1])

        await pipeline.generate_sql("how many person days in East Garo Hills?", ["MGNREGA"], _ENTITY_RESULT)
        check("an un-indexed scheme (MGNREGA) produces a prompt with no retrieved block",
              "RETRIEVED SCHEMA NOTES" not in captured_prompts[-1])
    finally:
        llm.call_sql_generator = orig_call_sql_generator
        schema_retrieval.retrieve = orig_retrieve


asyncio.run(_run())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL PIPELINE SCHEMA-RETRIEVAL WIRING CHECKS PASSED")
