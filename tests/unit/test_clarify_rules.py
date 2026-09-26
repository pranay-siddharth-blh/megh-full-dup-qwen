"""
Frame-driven clarification gates — app/nlu/clarify_rules.py and the shared
gate helpers (clarify_rules.gates_*) that _answer_data AND the LangGraph
nodes call.

Covers each of the 5 ordered rules (ask vs. default), that defaults come from
data/*/*_default_rules.yaml with their assumption_text recorded, that asks
reuse the existing builders' exact questions/options (the UI does not
change), that a turn with no model frame gates on the fallback frame,
_answer_data end to end on a frame (frame schemes/entities reused, assumptions
reach compose_response), LangGraph node parity with _answer_data, and the
_run_pipeline wrapper publishing/resetting the frame. No DB, no gateway.
Run: `python tests/unit/test_clarify_rules.py`, exit code 0 = pass.
"""
import asyncio
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.nlu import clarify_rules, defaults_engine, entity_resolver  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline, pipeline_graph  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


entity_resolver.load_all()
scheme_registry.load_all()


def F(**kw):
    kw.setdefault("rewritten_question", "q")
    schemes = kw.pop("resolved_schemes", kw.get("schemes", []))
    f = u.QueryFrame(**kw)
    f.resolved_schemes = list(schemes)
    return f


def asks(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except pipeline.ClarificationNeeded as e:
        return e


print("\n=== rule 1: scheme missing -> ask (never defaulted) ===")
e = asks(clarify_rules.before_resolution, F(metric="total expenditure", query_type="value"),
         "What is the total expenditure?")
ref = pipeline._scheme_clarification("What is the total expenditure?")
check("asks scheme-not-specified", e is not None and e.rule == "scheme-not-specified")
check("same question + options as the existing _scheme_clarification (UI unchanged)",
      e is not None and e.question == ref.question and e.options == ref.options)

print("\n=== rule 2: metric / top-N ===")
e = asks(clarify_rules.before_resolution, F(schemes=["PMAY-G"], metric="best performance", query_type="ranking",
                                            group_by="district"), "Best district on PMAY")
check("vague qualifier ('best performance') asks metric-not-specified", e is not None and e.rule == "metric-not-specified",
      getattr(e, "rule", None))
e = asks(clarify_rules.before_resolution, F(schemes=["MGNREGA"], metric=None, query_type="ranking", group_by="district"),
         "top districts mgnrega")
check("missing metric on a ranking asks", e is not None and e.rule == "metric-not-specified")
out = clarify_rules.before_resolution(F(schemes=["MGNREGA"], metric="expenditure", query_type="ranking",
                                        group_by="district"), "Top districts by MGNREGA expenditure?")
check("ranking with no N -> missing_top_n default injected (top 5)", "top 5" in out.question, out.question)
check("... assumption text from mgnrega_default_rules.yaml", out.assumptions == ["Showing the top 5."], str(out.assumptions))
out = clarify_rules.before_resolution(F(schemes=["MGNREGA"], metric="expenditure", query_type="value"),
                                      "Total MGNREGA expenditure?")
check("a plain value question passes rules 1-2 untouched",
      out.question == "Total MGNREGA expenditure?" and not out.assumptions and out.fired == ["scheme:ok", "metric:ok"])

print("\n=== rule 3: area ===")
A = clarify_rules.after_resolution
out = A(F(schemes=["PMAY-G"], metric="houses completed", query_type="value"), "How many PMAY-G houses completed",
        ["PMAY-G"], {})
check("no area -> statewide default", out.question.startswith("How many PMAY-G houses completed for all of Meghalaya"),
      out.question)
check("... disclosed with the yaml assumption", "Covering all 12 districts of Meghalaya." in out.assumptions,
      str(out.assumptions))
out = A(F(schemes=["PMAY-G"]), "houses in EKH", ["PMAY-G"], {"district": "EAST KHASI HILLS"})
check("area resolved -> no area default", "area:ok" in out.fired and "all of Meghalaya" not in out.question)
out = A(F(schemes=["PMAY-G"], group_by="district"), "houses by district", ["PMAY-G"], {})
check("a breakdown needs no area", "area:breakdown" in out.fired)
out = A(F(schemes=["PMAY-G"], geo_mentions=[{"text": "meghalaya", "level": "state"}]), "houses in meghalaya",
        ["PMAY-G"], {})
check("'Meghalaya' stated -> statewide, no assumption needed", "area:statewide-stated" in out.fired
      and not any("12 districts" in a for a in out.assumptions))
out = A(F(schemes=["PMAY-G"]), "houses", ["PMAY-G"], {}, skip_scope_clarify=True)
check("resuming a scope pause -> area rule skipped (no loop)", "area:skip" in out.fired)

print("\n=== rule 4: year (once the place is settled) ===")
out = A(F(schemes=["MGNREGA"], metric="expenditure", query_type="value"), "MGNREGA expenditure in EKH",
        ["MGNREGA"], {"district": "EAST KHASI HILLS"})
check("MGNREGA no year -> missing_time_period default FY 2025-26 pinned",
      out.pins.get("year_key") == 2025 and out.display.get("year") == "FY 2025-26"
      and out.question.endswith("for FY 2025-26"), f"{out.pins} {out.question}")
check("... disclosed", "Showing FY 2025-26, the latest year available." in out.assumptions, str(out.assumptions))
out = A(F(schemes=["PMAY-G"]), "PMAY-G houses in EKH", ["PMAY-G"], {"district": "EAST KHASI HILLS"})
check("PMAY-G no year -> its own default: all years (no pin)",
      "year_key" not in out.pins and out.question.endswith("across all financial years"), out.question)
out = A(F(schemes=["MGNREGA"], query_type="trend"), "MGNREGA person-days trend", ["MGNREGA"], {"district": "X"})
check("trend -> trend_without_period (all years)", out.question.endswith("across all financial years")
      and any("Trend shown" in a for a in out.assumptions), str(out.assumptions))
out = A(F(schemes=["MGNREGA"], year_text="last year"), "MGNREGA spend last year", ["MGNREGA"], {"district": "X"})
check("'last year' -> relative_year_previous default (FY 2024-25)", out.pins.get("year_key") == 2024, str(out.pins))
out = A(F(schemes=["MGNREGA"], year_text="all years"), "MGNREGA spend all years", ["MGNREGA"], {"district": "X"})
check("'all years' stated -> all years, nothing assumed", "year:all-stated" in out.fired and not any(
      "FY" in a for a in out.assumptions))
out = A(F(schemes=["MGNREGA"]), "MGNREGA spend 2023-24", ["MGNREGA"], {"district": "X", "year_key": 2023})
check("year already resolved -> ok", "year:ok" in out.fired and not out.pins)
out = A(F(schemes=["CM Elevate"]), "CM Elevate applications", ["CM Elevate"], {"district": "X"})
check("CM Elevate has no time dimension -> no year rule", "year:no-time-dimension" in out.fired)

print("\n=== rule 5: Focus Plus tranche ===")
out = A(F(schemes=["Focus Plus"], metric="disbursement"), "Focus Plus disbursement in EKH", ["Focus Plus"],
        {"district": "EAST KHASI HILLS", "year_key": 2025})
check("no tranche -> tranche_unspecified default (all tranches)", out.question.endswith("across all tranches")
      and "Covering all four tranches." in out.assumptions, f"{out.question} {out.assumptions}")
out = A(F(schemes=["Focus Plus"], group_by="tranche"), "Focus Plus disbursement by tranche", ["Focus Plus"],
        {"district": "X", "year_key": 2025})
check("a per-tranche breakdown needs no tranche", "tranche:ok" in out.fired)
out = A(F(schemes=["Focus Plus", "MGNREGA"]), "Focus Plus vs MGNREGA", ["Focus Plus", "MGNREGA"],
        {"district": "X", "year_key": 2025})
check("cross-scheme question: tranche rule not applied (as the old gate)", not any(
      f.startswith("tranche") for f in out.fired))

print("\n=== no default in the rules file -> ask with the existing builder ===")
orig_rules = defaults_engine._load_scheme_rules
defaults_engine._load_scheme_rules = lambda scheme: {}
try:
    e = asks(A, F(schemes=["PMAY-G"]), "How many PMAY-G houses", ["PMAY-G"], {})
    ref = pipeline._scope_clarification("How many PMAY-G houses", ["PMAY-G"])
    check("area -> the existing scope clarification, same options",
          e is not None and e.rule == "scope-not-specified" and e.options == ref.options)
    e = asks(A, F(schemes=["MGNREGA"]), "MGNREGA spend in EKH", ["MGNREGA"], {"district": "EAST KHASI HILLS"})
    check("year -> the existing year clarification", e is not None and e.rule == "year-not-specified")
    e = asks(clarify_rules.before_resolution, F(schemes=["MGNREGA"], metric="expenditure", query_type="ranking",
                                                group_by="district"), "Top districts by MGNREGA expenditure?")
    check("top-N -> the existing top-N clarification", e is not None and e.rule == "ranking-count-not-specified")
finally:
    defaults_engine._load_scheme_rules = orig_rules

print("\n=== no model frame: the gates read the fallback frame (no regex predicates left) ===")
check("the old _needs_* regex predicates are gone",
      not any(hasattr(pipeline, n) for n in ("_needs_scheme_clarification", "_needs_topn_clarification",
                                             "_needs_scope_clarification", "_needs_year_clarification",
                                             "_needs_tranche_clarification")))
check("no frame published this turn", u.current_frame.get() is None)
q, assumed, trace = clarify_rules.gates_before_resolution("total manrega expenditure")
check("fallback frame: scheme read from the text (misspelt), nothing guessed",
      q == "total manrega expenditure" and assumed == [] and trace[:1] == ["scheme:ok"], str(trace))
e = asks(clarify_rules.gates_before_resolution, "how many beneficiaries were there last year?")
check("fallback frame: no scheme in the text -> rule 1 asks", e is not None and e.rule == "scheme-not-specified")
check("gate_frame() with no published frame -> the fallback frame",
      clarify_rules.gate_frame("anything").source == "fallback")
_tok = u.current_frame.set(F(schemes=["PMAY-G"], resolved_schemes=["PMAY-G"]))
try:
    check("... and returns it when one is published", clarify_rules.gate_frame("x").resolved_schemes == ["PMAY-G"])
finally:
    u.current_frame.reset(_tok)

print("\n=== _answer_data end to end on a frame ===")
frame = F(rewritten_question="What is the total MGNREGA expenditure in EKH?", schemes=["MGNREGA"],
          metric="total expenditure", query_type="value", geo_mentions=[{"text": "EKH"}])
frame.entity_result = {"resolved": {"district": "EAST KHASI HILLS"}, "notes": [],
                       "display": {"district": "East Khasi Hills"}}
seen = {}


async def _no_classify(q):
    seen["classifier"] = True
    return ["PMAY-G"], pipeline.ScopeMeta(0.1, "llm", "")


async def _no_resolve(*a, **k):
    seen["resolver"] = True
    return {"resolved": {}, "notes": [], "display": {}}


async def _gen(q, schemes, er):
    seen["sql_question"], seen["sql_entities"] = q, copy.deepcopy(er)
    return "SELECT 1"


async def _exec(q, schemes, er, initial_sql=None, *, scope=None, max_repairs=None):
    return initial_sql, [{"total_expenditure_crore": 12.3}]


async def _compose(q, sql, rows, notes=None, **kw):
    seen["notes"] = list(notes or [])
    return "It is **12.3 crore**."

patches = {"_classify_scheme_detailed": _no_classify, "resolve_entities": _no_resolve,
           "generate_sql": _gen, "execute_with_repair": _exec, "compose_response": _compose}
saved = {k: getattr(pipeline, k) for k in patches}
saved_engine = pipeline.clarification_engine.check_clarifications
for k, v in patches.items():
    setattr(pipeline, k, v)
pipeline.clarification_engine.check_clarifications = lambda *a, **k: None
_saved_qa = settings.QUERY_ANALYZER_ENABLED
settings.QUERY_ANALYZER_ENABLED = False          # an LLM call; not what this test is about
token = u.current_frame.set(frame)
try:
    res = asyncio.run(pipeline._answer_data("What is the total MGNREGA expenditure in EKH?"))
    check("schemes taken from the frame (no second classifier call)",
          res["schemes"] == ["MGNREGA"] and "classifier" not in seen and res["scope"]["source"] == "frame")
    check("frame's own entity resolution reused (no second resolver call)", "resolver" not in seen)
    check("year default applied: SQL sees FY 2025-26 pinned",
          seen["sql_entities"]["resolved"].get("year_key") == 2025 and seen["sql_question"].endswith("for FY 2025-26"),
          f"{seen.get('sql_question')} {seen.get('sql_entities')}")
    # Step 8: defaults are disclosed by the deterministic "Assumed: ..." line the
    # frame-mode wrapper prepends (tests/unit/test_understood_as.py), NOT via the
    # composer's notes — so they are stated exactly once, verbatim.
    check("assumption NOT fed to compose_response's notes (the Assumed line discloses it)",
          "Showing FY 2025-26, the latest year available." not in seen["notes"], str(seen["notes"]))
    check("result carries assumptions + gate_trace",
          res.get("assumptions") == ["Showing FY 2025-26, the latest year available."]
          and "year:default:2025" in res.get("gate_trace", []), str(res.get("gate_trace")))
    check("frame entity_result not mutated by the gates (deep copy)", "year_key" not in frame.entity_result["resolved"])

    print("\n=== LangGraph nodes: same shared gates, same outcome ===")
    st = {"question": "What is the total MGNREGA expenditure in EKH?", "is_followup": False}
    st.update(asyncio.run(pipeline_graph.node_scope_scheme(st)))
    check("node 5.1: schemes from the frame", st["schemes"] == ["MGNREGA"] and st["scope_trace"]["source"] == "frame")
    st.update(asyncio.run(pipeline_graph.node_entities(st)))
    st.update(asyncio.run(pipeline_graph.node_clarification_gate(st)))
    check("node 5.3: same defaulted question as _answer_data", st["question"] == seen["sql_question"],
          f"{st['question']} vs {seen['sql_question']}")
    check("node 5.3: same assumptions as _answer_data",
          st["entity_result"]["assumptions"] == res["assumptions"])
    e = None
    try:
        asyncio.run(pipeline_graph.node_scope_scheme({"question": "total expenditure?"}))
    except pipeline.ClarificationNeeded as ex:
        e = ex
    token2 = u.current_frame.set(F(metric="total expenditure", query_type="value"))
    try:
        asyncio.run(pipeline_graph.node_scope_scheme({"question": "total expenditure?"}))
    except pipeline.ClarificationNeeded as ex:
        e = ex
    finally:
        u.current_frame.reset(token2)
    check("node 5.1: scheme missing asks the same scheme clarification", e is not None and e.rule == "scheme-not-specified")
finally:
    u.current_frame.reset(token)
    for k, v in saved.items():
        setattr(pipeline, k, v)
    pipeline.clarification_engine.check_clarifications = saved_engine
    settings.QUERY_ANALYZER_ENABLED = _saved_qa

print("\n=== _run_pipeline publishes the frame for the body, then resets it ===")
seen_frames = []


async def _body(question, session=None, scope=None, frame_followup=None, frame_intent=None):
    seen_frames.append(u.current_frame.get())
    return {"route": "data"}


async def _build_ok(message, ctx):
    return {"frame": F(schemes=["MGNREGA"], rewritten_question="x").model_dump(), "meta": {}}


async def _build_fail(message, ctx):
    return {"frame": None, "meta": {"error": "boom"}}


async def _normalise_keep(f, message):
    f.resolved_schemes = list(f.schemes)
    return f

orig_body, orig_build, orig_norm = pipeline._run_pipeline_body, u.build_frame, u.normalise_frame
pipeline._run_pipeline_body = _body
u.normalise_frame = _normalise_keep
try:
    u.build_frame = _build_ok
    asyncio.run(pipeline._run_pipeline("x"))
    check("body sees the frame", seen_frames[-1] is not None and seen_frames[-1].resolved_schemes == ["MGNREGA"])
    check("frame reset after the turn", u.current_frame.get() is None)
    u.build_frame = _build_fail
    asyncio.run(pipeline._run_pipeline("x"))
    check("frame failed -> body sees None (the gates then read the fallback frame)", seen_frames[-1] is None)
finally:
    pipeline._run_pipeline_body, u.build_frame, u.normalise_frame = orig_body, orig_build, orig_norm

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL CLARIFY-RULES CHECKS PASSED")
