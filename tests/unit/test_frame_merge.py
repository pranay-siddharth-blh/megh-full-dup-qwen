"""
Follow-ups on the QueryFrame — app/nlu/frame_merge.py (frame_for_turn,
merge_followup) and its wiring in pipeline._run_pipeline / _run_pipeline_body.

Unit: a follow-up inherits the previous frame's slots, the new non-empty slots
win, a scheme change clears metric + tranche, "compare with X" adds X to the
inherited place, a new question starts fresh.

End to end through POST /api/query, one session:
  "total MGNREGA expenditure in EKH"
  "and block wise?"      -> same scheme/place, broken down by block
  "same for 2022-23"     -> year replaced, block breakdown kept
  "what about PMAY"      -> scheme switched, metric cleared, place/year kept
  "compare with EGH"     -> EKH and EGH together
Frame decides the follow-up (not looks_like_followup); the old text-rewrite
follow-up path (rewrite_followup) no longer exists.
Model/SQL/DB stubbed; resolver, gates, routing and the router are real.
Run: `python tests/unit/test_frame_merge.py`, exit code 0 = pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from starlette.testclient import TestClient  # noqa: E402

from app.api.routers import query as query_router  # noqa: E402
from app.conversation import conversation_memory, conversation_store  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.main import app  # noqa: E402
from app.nlu import entity_resolver, frame_merge  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


entity_resolver.load_all()
scheme_registry.load_all()


def Q(**kw):
    kw.setdefault("rewritten_question", "q")
    kw.setdefault("intent", "DATA")
    return u.QueryFrame(**kw)


print("\n=== merge rules ===")
prev = frame_merge.remember(Q(rewritten_question="Total MGNREGA expenditure in EKH?", schemes=["MGNREGA"],
                              metric="total expenditure", geo_mentions=[{"text": "EKH"}], query_type="value",
                              tranche=None))
m = frame_merge.merge_followup(prev, Q(is_followup=True, group_by="block", rewritten_question="...by block?"))
check("inherits scheme / metric / place", m.schemes == ["MGNREGA"] and m.metric == "total expenditure"
      and [g.text for g in m.geo_mentions] == ["EKH"])
check("new non-empty slot wins (group_by)", m.group_by == "block")
check("standalone question is the follow-up's own rewrite", m.rewritten_question == "...by block?")
m = frame_merge.merge_followup(prev, Q(is_followup=True, year_text="2022-23"))
check("'same for 2022-23' replaces only the year", m.year_text == "2022-23" and m.metric == "total expenditure")
focus_prev = frame_merge.remember(Q(schemes=["Focus Plus"], metric="disbursement", tranche="Tranch 2",
                                    geo_mentions=[{"text": "wgh"}]))
m = frame_merge.merge_followup(focus_prev, Q(is_followup=True, schemes=["MGNREGA"]))
check("scheme change clears metric and tranche", m.schemes == ["MGNREGA"] and m.metric is None and m.tranche is None)
check("... keeps the place", [g.text for g in m.geo_mentions] == ["wgh"])
m = frame_merge.merge_followup(prev, Q(is_followup=True, query_type="comparison", geo_mentions=[{"text": "EGH"}]))
check("'compare with EGH' adds EGH to the inherited place", [g.text for g in m.geo_mentions] == ["EKH", "EGH"])
m = frame_merge.merge_followup(prev, Q(is_followup=True, geo_mentions=[{"text": "wgh"}]))
check("a new place (not a comparison) replaces the old one", [g.text for g in m.geo_mentions] == ["wgh"])

print("\n=== end to end: frame-driven follow-ups ===")
_SCOPE = UserScope(user_id="fu-u1", role="admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"], geographies="all",
                   tenant_id=1, db_user_id=1, username="fu-tester")
app.dependency_overrides[query_router._identity] = lambda: _SCOPE
client = TestClient(app, raise_server_exceptions=False)

FRAMES = {
    "total MGNREGA expenditure in EKH": dict(
        rewritten_question="What is the total MGNREGA expenditure in EKH?", schemes=["MGNREGA"],
        metric="total expenditure", query_type="value", geo_mentions=[{"text": "EKH"}]),
    "and block wise?": dict(
        rewritten_question="What is the total MGNREGA expenditure in EKH, block wise?", is_followup=True,
        group_by="block", query_type="distribution"),
    "same for 2022-23": dict(
        rewritten_question="What is the total MGNREGA expenditure in EKH, block wise, for 2022-23?",
        is_followup=True, year_text="2022-23"),
    "what about PMAY": dict(
        rewritten_question="What about PMAY-G in EKH and EGH for 2022-23?", is_followup=True,
        schemes=["PMAY-G"]),
    "compare with EGH": dict(
        rewritten_question="Compare the total MGNREGA expenditure in EKH with EGH for 2022-23",
        is_followup=True, query_type="comparison", geo_mentions=[{"text": "EGH"}]),
    "how many houses completed in wgh": dict(
        rewritten_question="How many PMAY-G houses were completed in wgh?", schemes=["PMAY-G"],
        metric="houses completed", query_type="value", geo_mentions=[{"text": "wgh"}]),
}
understand_seen: list[str] = []


async def _build_frame(message, ctx):
    understand_seen.append(message)
    return {"frame": Q(**FRAMES[message]).model_dump(), "meta": {"flags": []}}

sql_seen: list[dict] = []


intent_calls: list[str] = []


async def _classify_intent(q):
    # Deliberately WRONG for every data question below: frame mode must route
    # on the frame's own intent, never on this separate classifier.
    intent_calls.append(q)
    return "KNOWLEDGE"


async def _generate_sql(question, schemes, entity_result):
    sql_seen.append({"question": question, "schemes": list(schemes), "resolved": dict(entity_result["resolved"])})
    return "SELECT 1"


async def _execute(question, schemes, entity_result, initial_sql=None, *, scope=None, max_repairs=None):
    return initial_sql, [{"total": 1.0}]


async def _one_attempt(sql, question, schemes, entity_result, scope, retrieved):
    return sql, [{"total": 1.0}]


async def _compose(question, sql, rows, notes=None, **kw):
    return "The figure is **1.0**."


async def _no_village(text, district=None, block=None):
    return entity_resolver.Resolved("not_found", "village", text)


async def _no_state(session_id):
    return {}


async def _no_mentions(q):
    return {}

patches = [
    (u, "build_frame", _build_frame),
    (pipeline, "classify_intent", _classify_intent), (pipeline, "generate_sql", _generate_sql),
    (pipeline, "execute_with_repair", _execute), (pipeline, "_execute_one_attempt", _one_attempt),
    (pipeline, "compose_response", _compose), (pipeline, "resolve_village", _no_village),
    (pipeline, "extract_entity_mentions", _no_mentions),
    (conversation_store, "persist_turn", lambda **k: None),
    (conversation_store, "save_context_state", lambda **k: None),
    (conversation_store, "load_context_state", _no_state),
    (conversation_memory, "index_turn", lambda **k: None),
    (pipeline.clarification_engine, "check_clarifications", lambda *a, **k: None),
]
originals = [(o, n, getattr(o, n)) for o, n, _ in patches]
for o, n, fn in patches:
    setattr(o, n, fn)
flag_names = ("QUERY_ANALYZER_ENABLED", "CONTEXT_SUMMARY_ENABLED",
              "CONTEXT_SEMANTIC_MEMORY_ENABLED", "RESPONSE_CACHE_ENABLED", "SEMANTIC_CACHE_ENABLED")
flags_before = {n: getattr(settings, n) for n in flag_names}
settings.QUERY_ANALYZER_ENABLED = False
settings.CONTEXT_SUMMARY_ENABLED = False
settings.CONTEXT_SEMANTIC_MEMORY_ENABLED = False
settings.RESPONSE_CACHE_ENABLED = False
settings.SEMANTIC_CACHE_ENABLED = False


def post(q, sid):
    r = client.post("/api/query", json={"question": q, "session_id": sid})
    return r.json()


def last_meta(sid):
    return (session_store.get(sid).understand_frame or {}).get("meta") or {}


try:
    SID = "fu-chain"
    r = post("total MGNREGA expenditure in EKH", SID)
    check("turn 1 answered for EKH", r.get("route") == "data" and sql_seen[-1]["resolved"].get("district")
          == "EAST KHASI HILLS", str(r)[:200])
    check("last_frame remembered", (session_store.get(SID).state.last_frame or {}).get("schemes") == ["MGNREGA"])

    r = post("and block wise?", SID)
    s = sql_seen[-1]
    check("'and block wise?': frame decided it is a follow-up and merged",
          last_meta(SID).get("followup") == "merged", str(last_meta(SID)))
    check("... same scheme + place, now broken down by block",
          r.get("route") == "data" and s["schemes"] == ["MGNREGA"]
          and s["resolved"].get("district") == "EAST KHASI HILLS" and "block wise" in s["question"], str(s))
    check("... the text-rewrite follow-up path is gone from the pipeline",
          not hasattr(pipeline, "rewrite_followup") and not hasattr(pipeline, "_scheme_swap_rewrite"))

    r = post("same for 2022-23", SID)
    s = sql_seen[-1]
    check("'same for 2022-23': year replaced, place + breakdown kept",
          s["resolved"].get("year_key") == 2022 and s["resolved"].get("district") == "EAST KHASI HILLS"
          and s["schemes"] == ["MGNREGA"], str(s))

    r = post("compare with EGH", SID)
    s = sql_seen[-1]
    check("'compare with EGH': EKH and EGH together (MGNREGA metric inherited)",
          sorted(s["resolved"].get("district_list") or []) == ["EAST GARO HILLS", "EAST KHASI HILLS"]
          and s["schemes"] == ["MGNREGA"], str(s))

    r = post("what about PMAY", SID)
    f = (session_store.get(SID).understand_frame or {}).get("frame") or {}
    check("'what about PMAY': scheme switched, both places + year kept on the frame",
          f.get("resolved_schemes") == ["PMAY-G"] and f.get("year_text") == "2022-23"
          and [g["text"] for g in f.get("geo_mentions") or []] == ["EKH", "EGH"], str(f)[:300])
    check("... MGNREGA metric cleared on the scheme change", f.get("metric") is None, str(f.get("metric")))
    # A PMAY-G comparison with no metric left: rule 2 asks which figure — MGNREGA
    # "expenditure" has no PMAY-G equivalent to carry over, so it is not guessed.
    check("... so the comparison asks which PMAY-G figure (not guessed)",
          r.get("route") == "clarification" and (r.get("clarification") or {}).get("rule") == "metric-not-specified",
          str(r)[:200])
    check("routing came from the frame's intent: classify_intent never called",
          intent_calls == [], str(intent_calls))

    r = post("how many houses completed in wgh", SID)
    s = sql_seen[-1]
    f = (session_store.get(SID).understand_frame or {}).get("frame") or {}
    check("a new question starts fresh (nothing inherited)",
          s["resolved"].get("district") == "WEST GARO HILLS" and not f.get("group_by")
          and "followup" not in last_meta(SID), str(s))

finally:
    for o, n, fn in originals:
        setattr(o, n, fn)
    for n, v in flags_before.items():
        setattr(settings, n, v)
    app.dependency_overrides.pop(query_router._identity, None)

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL FRAME-MERGE CHECKS PASSED")
