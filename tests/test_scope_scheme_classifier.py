"""
Pipeline architecture doc §5.1 ("Scope and scheme classifier") — pure-logic
checks for all three pieces of that node: app/pipeline.py's classify_scheme()
(scheme routing), looks_like_followup() (follow-up detection), and the
OutOfScope guard inside resolve_entities() (place-scope check). No DB, no
live model gateway — classify_scheme's model-dependent path is exercised via
a monkeypatched llm.call_classifier (same stance as
test_pipeline_schema_retrieval.py); the OutOfScope path is exercised by
monkeypatching extract_entity_mentions (the one LLM call in resolve_entities)
and resolve_village (the one live-DB call), leaving resolve_dimension's real,
fully in-memory Meghalaya district/block catalogue doing the actual scope
check.
Run: `python tests/test_scope_scheme_classifier.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import llm, pipeline  # noqa: E402
from app.entity_resolver import Resolved  # noqa: E402
from app.entity_resolver import load_all as _load_entity_resolver  # noqa: E402

# Section 4 needs the real district/block catalogue (local YAML, no network —
# same call app/main.py makes at startup) so the OutOfScope check runs against
# actual Meghalaya districts rather than an empty, always-not_found catalogue.
_load_entity_resolver()

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# ── 1. looks_like_followup — pure regex, no mocks needed ───────────────────
print("1. LOOKS_LIKE_FOLLOWUP")

check("scheme-swap fragment is a follow-up",
      pipeline.looks_like_followup("what about PMAY-G?"))
check("bare pronoun fragment with no anchor is a follow-up",
      pipeline.looks_like_followup("what about that?"))
check("bare short fragment with no anchor is a follow-up",
      pipeline.looks_like_followup("in East Garo Hills"))
check("a question naming its own scheme is standalone, not a follow-up",
      not pipeline.looks_like_followup("What benefits will I get under Focus Plus?"))
check("a fresh self-contained question is not a follow-up",
      not pipeline.looks_like_followup("How many houses were completed under PMAY-G in 2023-24?"))
check("a long question (>12 words) is never treated as a fragment",
      not pipeline.looks_like_followup(
          "Is there any government scheme that can help my family with housing support this year?"))
check("'documents?' right after a scheme answer reads as a follow-up (TC anchor list)",
      pipeline.looks_like_followup("documents?"))


# ── 2. classify_scheme — deterministic shortcut path (no model call) ───────
print("2. CLASSIFY_SCHEME — SHORTCUT (NAMED SCHEME) PATH")


def _no_model_call(*_a, **_kw):
    raise AssertionError("classify_scheme should not call the model when the text pins the scheme")


async def _run_shortcut_checks():
    orig = llm.call_classifier
    llm.call_classifier = _no_model_call
    try:
        result = await pipeline.classify_scheme("how many person-days under MGNREGA?")
        check("single named scheme resolves to just that scheme, no model call",
              result == ["MGNREGA"], detail=str(result))

        result = await pipeline.classify_scheme("compare MGNREGA and PMAY-G")
        check("two named schemes resolve to exactly those two, in catalog order, no model call",
              result == ["MGNREGA", "PMAY-G"], detail=str(result))

        result = await pipeline.classify_scheme("give me numbers across both schemes")
        check("explicit cross-scheme phrasing resolves to the whole catalog, no model call",
              set(result) == set(pipeline.SCHEME_CATALOG), detail=str(result))

        # Focus Plus / CM Elevate were never exercised in this shortcut path
        # before this section — found missing during a 5.1 end-to-end pass.
        result = await pipeline.classify_scheme("Focus Plus tranche 1 disbursement")
        check("Focus Plus named outright resolves via shortcut, no model call",
              result == ["Focus Plus"], detail=str(result))

        result = await pipeline.classify_scheme("how many CM Elevate applications for piggery?")
        check("CM Elevate named outright resolves via shortcut, no model call",
              result == ["CM Elevate"], detail=str(result))

        result = await pipeline.classify_scheme("compare CM Elevate and Focus Plus applications")
        check("Focus Plus + CM Elevate named together resolve in catalog order, no model call",
              result == ["Focus Plus", "CM Elevate"], detail=str(result))

        # Vocabulary-only inference (_infer_scheme_from_terms) for the two
        # schemes not previously covered by this shortcut section.
        result = await pipeline.classify_scheme("how many piggery applications were received")
        check("CM Elevate-only vocabulary infers the scheme with no name and no model call",
              result == ["CM Elevate"], detail=str(result))

        result = await pipeline.classify_scheme("tranche 1 disbursement amount this year")
        check("Focus Plus-only vocabulary infers the scheme with no name and no model call",
              result == ["Focus Plus"], detail=str(result))

        # Misspelling of a named scheme, via _fuzzy_named_schemes — not
        # previously exercised through the full async classify_scheme path.
        result = await pipeline.classify_scheme("manrega person days this year")
        check("a misspelled scheme name still shortcuts via fuzzy matching, no model call",
              result == ["MGNREGA"], detail=str(result))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_shortcut_checks())


# ── 2b. _correct_scheme_spelling / _fuzzy_named_schemes / _infer_scheme_ ───
# from_terms — the three helper functions classify_scheme's shortcut path
# depends on, exercised directly rather than only indirectly through it.
print("2b. SPELLING CORRECTION / FUZZY MATCHING / TERM INFERENCE (direct)")

check("misspelled MGNREGA is fuzzy-matched",
      pipeline._fuzzy_named_schemes("manrega workers count") == ["MGNREGA"])
check("misspelled PMAY-G is fuzzy-matched",
      pipeline._fuzzy_named_schemes("pamay houses built") == ["PMAY-G"])
check("misspelled Focus Plus is fuzzy-matched",
      pipeline._fuzzy_named_schemes("facus plus payment") == ["Focus Plus"])
check("misspelled CM Elevate is fuzzy-matched",
      pipeline._fuzzy_named_schemes("cmelavate applications") == ["CM Elevate"])
check("no scheme-like word fuzzy-matches nothing",
      pipeline._fuzzy_named_schemes("totally unrelated sentence about weather") == [])

check("_correct_scheme_spelling fixes a single-word misspelling",
      pipeline._correct_scheme_spelling("manrega expenditure") == "MGNREGA expenditure")
# Regression test for a real bug found during a 5.1 end-to-end verification
# pass: a single-word misspelling of the two-word canonical "Focus Plus"
# ("facus") landing directly next to the text's own real trailing word
# ("plus") produced a doubled "Focus Plus plus" before this was fixed.
check("_correct_scheme_spelling does not duplicate the trailing word of a "
      "multi-word canonical name (regression: 'facus plus' -> 'Focus Plus plus')",
      pipeline._correct_scheme_spelling("facus plus card") == "Focus Plus card",
      pipeline._correct_scheme_spelling("facus plus card"))
check("_correct_scheme_spelling still corrects a misspelling with no adjacent "
      "duplicate word",
      pipeline._correct_scheme_spelling("facus payment for the year")
      == "Focus Plus payment for the year")

check("_infer_scheme_from_terms infers MGNREGA from person-days vocabulary",
      pipeline._infer_scheme_from_terms("how many person-days were generated") == ["MGNREGA"])
check("_infer_scheme_from_terms infers PMAY-G from pucca-house vocabulary",
      pipeline._infer_scheme_from_terms("how many pucca houses were sanctioned") == ["PMAY-G"])
check("_infer_scheme_from_terms infers Focus Plus from tranche vocabulary",
      pipeline._infer_scheme_from_terms("tranche 1 disbursement amount") == ["Focus Plus"])
check("_infer_scheme_from_terms infers CM Elevate from piggery vocabulary",
      pipeline._infer_scheme_from_terms("how many piggery applications") == ["CM Elevate"])
check("ambiguous vocabulary (no scheme-specific term) infers nothing",
      pipeline._infer_scheme_from_terms("how many beneficiaries received the money") is None)
# Regression test for a real bug found during the same pass: the PMAY-only
# "received (qualifier) amount" pattern had its qualifier word optional,
# so a scheme-generic "received amount" (equally plausible for Focus Plus's
# own disbursement vocabulary) silently inferred PMAY-G alone — exactly the
# mis-routing risk this vocabulary block's own design comment warns against.
check("_infer_scheme_from_terms does NOT infer PMAY-G from a bare, scheme-"
      "generic 'received amount' with no qualifier word "
      "(regression: the qualifier was previously optional)",
      pipeline._infer_scheme_from_terms("how many beneficiaries received amount") is None,
      pipeline._infer_scheme_from_terms("how many beneficiaries received amount"))
check("_infer_scheme_from_terms still infers PMAY-G when the qualifier word IS present",
      pipeline._infer_scheme_from_terms("how many beneficiaries received any amount") == ["PMAY-G"])
check("_infer_scheme_from_terms still infers PMAY-G for 'received sanctioned amount' "
      "(no qualifier word, but 'sanctioned amount' matches an earlier alternative)",
      pipeline._infer_scheme_from_terms("beneficiaries received sanctioned amount") == ["PMAY-G"])


# ── 3. classify_scheme — model path + fallback on unusable output ──────────
print("3. CLASSIFY_SCHEME — MODEL PATH AND FALLBACK")


async def _run_model_checks():
    from app.schema_context import SCHEME_CATALOG
    orig = llm.call_classifier

    async def _returns_focus_plus(*_a, **_kw):
        return '{"schemes": ["Focus Plus"]}'

    llm.call_classifier = _returns_focus_plus
    try:
        result = await pipeline.classify_scheme("who is eligible for the state cash benefit?")
        check("vocabulary-only question with no named scheme uses the model's answer",
              result == ["Focus Plus"], detail=str(result))
    finally:
        llm.call_classifier = orig

    async def _returns_garbage(*_a, **_kw):
        return "not json at all"

    llm.call_classifier = _returns_garbage
    try:
        result = await pipeline.classify_scheme("who is eligible for the state cash benefit?")
        check("unusable model output falls back to every scheme, not an empty/partial result",
              set(result) == set(SCHEME_CATALOG), detail=str(result))
    finally:
        llm.call_classifier = orig

    async def _drops_named_scheme(*_a, **_kw):
        # Model omits a scheme the user named outright — the safety-net union
        # in classify_scheme must add it back in.
        return '{"schemes": ["PMAY-G"]}'

    llm.call_classifier = _drops_named_scheme
    try:
        result = await pipeline.classify_scheme("MGNREGA numbers vs the housing scheme, roughly")
        check("a scheme named outright is never dropped even if the model omits it",
              "MGNREGA" in result, detail=str(result))
    finally:
        llm.call_classifier = orig

    # CM Elevate was never exercised on the model path before this check —
    # found missing during a 5.1 end-to-end pass (only Focus Plus was).
    async def _returns_cm_elevate(*_a, **_kw):
        return '{"schemes": ["CM Elevate"]}'

    llm.call_classifier = _returns_cm_elevate
    try:
        result = await pipeline.classify_scheme("what programmes cover livelihood support?")
        check("vocabulary-only question routes to CM Elevate via the model path",
              result == ["CM Elevate"], detail=str(result))
    finally:
        llm.call_classifier = orig


asyncio.run(_run_model_checks())


# ── 4. OutOfScope — a place named outside Meghalaya, inside resolve_entities ─
print("4. RESOLVE_ENTITIES — OUT-OF-SCOPE PLACE GUARD")


async def _run_out_of_scope_checks():
    orig_extract = pipeline.extract_entity_mentions
    orig_resolve_village = pipeline.resolve_village

    async def _mentions_foreign_district(_question):
        return {"district": "Guwahati"}

    async def _village_not_found(text, *_a, **_kw):
        return Resolved("not_found", "village", text, message=f"'{text}' is not a known village")

    pipeline.extract_entity_mentions = _mentions_foreign_district
    pipeline.resolve_village = _village_not_found
    try:
        try:
            await pipeline.resolve_entities("how many houses were completed in Guwahati?", ["PMAY-G"])
            check("a district outside Meghalaya raises OutOfScope", False,
                  "no exception was raised")
        except pipeline.OutOfScope as e:
            check("a district outside Meghalaya raises OutOfScope", True)
            check("the OutOfScope message names the offending place", "Guwahati" in str(e), detail=str(e))
        except Exception as e:  # noqa: BLE001
            check("a district outside Meghalaya raises OutOfScope", False,
                  f"raised {type(e).__name__} instead: {e}")
    finally:
        pipeline.extract_entity_mentions = orig_extract
        pipeline.resolve_village = orig_resolve_village

    # A real Meghalaya district must resolve normally, not raise OutOfScope —
    # guards against a test/mock that would pass even if the check were wired backwards.
    pipeline.extract_entity_mentions = lambda _q: asyncio.sleep(0, result={"district": "East Garo Hills"})
    try:
        result = await pipeline.resolve_entities("how many houses were completed in East Garo Hills?", ["PMAY-G"])
        check("a real Meghalaya district resolves normally, no OutOfScope",
              result.get("resolved", {}).get("district") is not None, detail=str(result))
    except pipeline.OutOfScope as e:
        check("a real Meghalaya district resolves normally, no OutOfScope", False, str(e))
    finally:
        pipeline.extract_entity_mentions = orig_extract


asyncio.run(_run_out_of_scope_checks())


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL SCOPE/SCHEME CLASSIFIER (5.1) CHECKS PASSED")
