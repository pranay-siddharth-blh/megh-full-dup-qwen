"""
"Understood as" / "Assumed" lines and frame-built next-step suggestions
— understand.prepend_understanding (via frame_merge.after_answer) and
app/response/followups.build_followups(frame=...).

Covers: the answer is prefixed with "Understood as: <rewritten>" only when it
differs meaningfully from what was typed, and with "Assumed: ..." carrying
every applied default's own assumption_text; the composer's text (and its
locked numbers) is kept verbatim after the prefix and the defaults are no
longer ALSO fed to the composer as notes; suggestions are built from the
frame's metric / scheme / grain (a bare "and block wise?" follow-up gets the
inherited metric's suggestions); no model frame (Understand failed) and
nothing assumed => nothing prefixed. Model/SQL/DB stubbed.
Run: `python tests/unit/test_understood_as.py`, exit code 0 = pass.
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
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.main import app  # noqa: E402
from app.nlu import entity_resolver  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402
from app.response import followups  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


entity_resolver.load_all()
scheme_registry.load_all()

print("\n=== when is the reading worth showing? ===")
check("typo-fixed + scheme-named rewrite differs meaningfully",
      u.meaningfully_different("total manrega expendture", "What is the total MGNREGA expenditure?"))
check("near-identical rewrite is NOT shown",
      not u.meaningfully_different("What is the total MGNREGA expenditure?",
                                           "what is the total mgnrega expenditure"))
check("a follow-up fragment always differs from its standalone rewrite",
      u.meaningfully_different("and block wise?", "What is the MGNREGA expenditure in EKH, block wise?"))

print("\n=== suggestions from the frame, not the question text ===")
frame = {"rewritten_question": "What is the total MGNREGA expenditure in EKH, block wise?",
         "metric": "total expenditure", "resolved_schemes": ["MGNREGA"], "group_by": "block",
         "query_type": "distribution"}
ents = {"district": "EAST KHASI HILLS", "year_key": 2025}
from_text = followups.build_followups("data", "and block wise?", ["MGNREGA"], ents)
from_frame = followups.build_followups("data", "and block wise?", ["MGNREGA"], ents, frame=frame)
q_frame = " | ".join(o["question"] for o in from_frame).casefold()
check("frame path: the inherited metric (total expenditure) is not re-suggested as-is",
      not any("total mgnrega expenditure" in o["question"].casefold() for o in from_frame), q_frame)
check("frame path: leads with the next metric for an expenditure question (person-days)",
      from_frame and "person-days" in from_frame[0]["question"].casefold(), q_frame)
check("frame path: offers the NEXT MGNREGA metric (person-days)", "person" in q_frame, q_frame)
check("text path differs for the same fragment (it can't see the metric)",
      [o["question"] for o in from_text] != [o["question"] for o in from_frame])
check("no frame => identical to the old behaviour",
      followups.build_followups("data", "and block wise?", ["MGNREGA"], ents, frame=None) == from_text)

print("\n=== end to end: the answer shows what was understood and assumed ===")
_SCOPE = UserScope(user_id="ua-u1", role="admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"], geographies="all",
                   tenant_id=1, db_user_id=1, username="ua-tester")
app.dependency_overrides[query_router._identity] = lambda: _SCOPE
client = TestClient(app, raise_server_exceptions=False)
FRAMES = {
    "total manrega expendture": dict(rewritten_question="What is the total MGNREGA expenditure?",
                                     schemes=["MGNREGA"], metric="total expenditure", query_type="value"),
    "What is the total MGNREGA expenditure in EKH for FY 2023-24?": dict(
        rewritten_question="What is the total MGNREGA expenditure in EKH for FY 2023-24?", schemes=["MGNREGA"],
        metric="total expenditure", query_type="value", geo_mentions=[{"text": "EKH"}], year_text="FY 2023-24"),
}
composer_notes: list[list[str]] = []
COMPOSED = "Total MGNREGA expenditure was **3628.67** crore."


async def _build_frame(message, ctx):
    return {"frame": u.QueryFrame(intent="DATA", **FRAMES[message]).model_dump(), "meta": {"flags": []}}


async def _generate_sql(question, schemes, entity_result):
    return "SELECT 1"


async def _execute(question, schemes, entity_result, initial_sql=None, *, scope=None, max_repairs=None):
    return initial_sql, [{"total_expenditure_crore": 3628.67}]


async def _one_attempt(sql, question, schemes, entity_result, scope, retrieved):
    return sql, [{"total_expenditure_crore": 3628.67}]


async def _compose(question, sql, rows, notes=None, **kw):
    composer_notes.append(list(notes or []))
    return COMPOSED


async def _no_state(session_id):
    return {}

patches = [
    (u, "build_frame", _build_frame), (pipeline, "generate_sql", _generate_sql),
    (pipeline, "execute_with_repair", _execute), (pipeline, "_execute_one_attempt", _one_attempt),
    (pipeline, "compose_response", _compose),
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
try:
    r = client.post("/api/query", json={"question": "total manrega expendture", "session_id": "ua-1"}).json()
    ans = r.get("answer") or ""
    lines = ans.split("\n")
    check("line 1: Understood as <the frame's reading>",
          lines[0] == "_Understood as: What is the total MGNREGA expenditure?_", lines[0])
    check("line 2: Assumed <every default's own assumption text>",
          lines[1].startswith("_Assumed: ") and "Covering all 12 districts of Meghalaya." in lines[1]
          and "Showing FY 2025-26, the latest year available." in lines[1], lines[1] if len(lines) > 1 else ans)
    check("the composer's answer follows verbatim (numbers locked from the rows)", ans.endswith(COMPOSED))
    check("defaults are NOT also fed to the composer as notes (stated once)",
          not any("12 districts" in n or "FY 2025-26" in n for n in composer_notes[-1]), str(composer_notes[-1]))
    check("result carries understood_as + assumptions for the UI/audit",
          r.get("understood_as") == "What is the total MGNREGA expenditure?" and len(r.get("assumptions") or []) == 2)
    check("suggestions were built (frame path)", bool(r.get("follow_up_options")))

    q = "What is the total MGNREGA expenditure in EKH for FY 2023-24?"
    r = client.post("/api/query", json={"question": q, "session_id": "ua-2"}).json()
    check("typed ~= understood and nothing assumed -> no prefix at all",
          (r.get("answer") or "") == COMPOSED and not r.get("understood_as"), r.get("answer"))

    async def _no_frame(message, ctx):                  # the Understand call failed
        return {"frame": None, "meta": {"error": "timeout"}}
    _o0 = u.build_frame
    u.build_frame = _no_frame
    async def _cls(q):
        return ["MGNREGA"], pipeline.ScopeMeta(1.0, "shortcut", "")
    async def _ment(q):
        return {"district": "EKH", "year": "2023-24"}
    _o1, _o2 = pipeline._classify_scheme_detailed, pipeline.extract_entity_mentions
    pipeline._classify_scheme_detailed, pipeline.extract_entity_mentions = _cls, _ment
    async def _intent(q):
        return "DATA"
    _o3 = pipeline.classify_intent
    pipeline.classify_intent = _intent
    try:
        r = client.post("/api/query", json={"question": q, "session_id": "ua-3"}).json()
    finally:
        pipeline._classify_scheme_detailed, pipeline.extract_entity_mentions = _o1, _o2
        pipeline.classify_intent = _o3
        u.build_frame = _o0
    check("no model frame, nothing assumed: answer exactly the composer's, no prefix",
          (r.get("answer") or "") == COMPOSED, r.get("answer"))
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
print("ALL UNDERSTOOD-AS CHECKS PASSED")
