"""
Pipeline architecture doc §5.2 ("Query analyzer") — this codebase implements
that node's responsibilities as several separate pieces rather than one
structured analyser object (see docs/baseline-audit.md §1, row 5.2). This
file covers the one piece that is directly analogous to §5.1's classifier and
was still untested: app/orchestration/pipeline.py's classify_intent() (DATA vs KNOWLEDGE
routing). extract_entity_mentions (span-finding) and the ~10
_needs_*_clarification predicates are deliberately out of scope here — the
audit maps those to §5.3's clarification gate, a separate node.
No DB, no live model gateway — classify_intent's model-dependent path is
exercised via a monkeypatched llm.call_classifier, same stance as
test_scope_scheme_classifier.py.
Run: `python tests/unit/test_intent_classifier.py`, exit code 0 = pass.
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

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def _no_model_call(*_a, **_kw):
    raise AssertionError("classify_intent should not call the model when a keyword hint decides it")


# ── 1. Keyword fast-path — no model call needed ─────────────────────────────
print("1. CLASSIFY_INTENT — KEYWORD FAST-PATH")


async def _run_fastpath_checks():
    orig = llm.call_classifier
    llm.call_classifier = _no_model_call
    try:
        result = await pipeline.classify_intent("how many person-days were generated in East Garo Hills?")
        check("a data-hint question ('how many') routes to DATA, no model call",
              result == "DATA", detail=result)

        result = await pipeline.classify_intent("what documents are required to apply for PMAY-G?")
        check("a knowledge-hint question ('what documents') routes to KNOWLEDGE, no model call",
              result == "KNOWLEDGE", detail=result)

        result = await pipeline.classify_intent("what are common districts in both schemes?")
        check("cross-scheme-set phrasing forces DATA despite the 'what are' knowledge cue",
              result == "DATA", detail=result)
    finally:
        llm.call_classifier = orig


asyncio.run(_run_fastpath_checks())


# ── 2. Model path + fallback on unusable output ─────────────────────────────
print("2. CLASSIFY_INTENT — MODEL PATH AND FALLBACK")


async def _run_model_checks():
    orig = llm.call_classifier

    async def _returns_knowledge(*_a, **_kw):
        return '{"intent": "KNOWLEDGE"}'

    llm.call_classifier = _returns_knowledge
    try:
        # No strong DATA or KNOWLEDGE keyword hint here, so it must fall to the model.
        result = await pipeline.classify_intent("tell me about the state cash benefit scheme")
        check("a question with no keyword hint uses the model's answer",
              result == "KNOWLEDGE", detail=result)
    finally:
        llm.call_classifier = orig

    async def _returns_garbage(*_a, **_kw):
        return "not json at all"

    llm.call_classifier = _returns_garbage
    try:
        result = await pipeline.classify_intent("tell me about the state cash benefit scheme")
        check("unusable model output falls back to DATA",
              result == "DATA", detail=result)
    finally:
        llm.call_classifier = orig


asyncio.run(_run_model_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL INTENT CLASSIFIER (5.2, partial) CHECKS PASSED")
