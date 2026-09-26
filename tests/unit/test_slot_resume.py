"""
Slot-filling clarification resume — end to end through
the real POST /api/query router, across separate requests of one session:

  "what is the expenditure"      -> "which scheme?"  (options carry {slot, value})
  click MGNREGA                  -> slot filled with NO Understand call; answered
                                    with the disclosed statewide / FY defaults and
                                    "Change area" correction chips
  click District                 -> "Which district?"
  type "westgaro hils"           -> Understand with the pause as context, merged
                                    into the paused frame -> West Garo Hills -> the
                                    exact figure; the question built from the frame,
                                    never by gluing the reply onto the paused text.

Plus: the pending frame is persisted with the conversation state and a reply
landing on ANOTHER worker still resumes; a brand-new question drops the pause;
no text-glue (pending_scope_q) resume path is left. Model/SQL/DB are stubbed —
resolver, gates, routing and the router are real.
Run: `python tests/unit/test_slot_resume.py`, exit code 0 = pass.
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
from app.nlu import entity_resolver  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


entity_resolver.load_all()
scheme_registry.load_all()

_SCOPE = UserScope(user_id="slot-u1", role="admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"], geographies="all",
                   tenant_id=1, db_user_id=1, username="slot-tester")
app.dependency_overrides[query_router._identity] = lambda: _SCOPE
client = TestClient(app, raise_server_exceptions=False)

# ── stubs: model calls, SQL, DB, durable store ─────────────────────────────
understand_calls: list[tuple[str, dict]] = []
FRAMES = {
    "what is the expenditure": {
        "rewritten_question": "What is the expenditure?", "intent": "DATA",
        "metric": "expenditure", "query_type": "value", "unclear": "scheme not stated"},
    "westgaro hils": {
        "rewritten_question": "What is the MGNREGA expenditure in westgaro hils?", "intent": "DATA",
        "answers_pending": True, "geo_mentions": [{"text": "westgaro hils", "level": None}]},
    "how many houses completed": {       # the model names no scheme; normalise infers PMAY-G ("houses")
        "rewritten_question": "How many houses have been completed?", "intent": "DATA",
        "metric": "houses completed", "query_type": "value"},
    "ekh": {                             # a bare reply the model does not merge into a full question
        "rewritten_question": "How many in ekh?", "intent": "DATA",
        "answers_pending": True, "geo_mentions": [{"text": "ekh", "level": None}]},
    "how many houses completed in ekh": {
        "rewritten_question": "How many PMAY-G houses were completed in ekh?", "intent": "DATA",
        "schemes": ["PMAY-G"], "metric": "houses completed", "query_type": "value",
        "geo_mentions": [{"text": "ekh", "level": None}]},
}


async def _build_frame(message, ctx):
    understand_calls.append((message, ctx))
    return {"frame": u.QueryFrame(**FRAMES[message]).model_dump(), "meta": {"flags": []}}

sql_seen: list[dict] = []
FIGURES = {"WEST GARO HILLS": 812.45, "EAST KHASI HILLS": 4321.0, None: 3628.67}


async def _classify_intent(q):
    return "DATA"


async def _generate_sql(question, schemes, entity_result):
    sql_seen.append({"question": question, "schemes": list(schemes),
                     "resolved": dict(entity_result["resolved"]), "notes": list(entity_result.get("notes") or [])})
    return "SELECT 1"


async def _execute(question, schemes, entity_result, initial_sql=None, *, scope=None, max_repairs=None):
    return initial_sql, [{"total": FIGURES.get(entity_result["resolved"].get("district"))}]


async def _one_attempt(sql, question, schemes, entity_result, scope, retrieved):
    # The LangGraph path (PIPELINE_GRAPH_ENABLED) executes through its own
    # attempt/repair nodes on top of this function, not execute_with_repair.
    return sql, [{"total": FIGURES.get(entity_result["resolved"].get("district"))}]


async def _compose(question, sql, rows, notes=None, **kw):
    return f"The figure is **{rows[0]['total']}**."


async def _no_village(text, district=None, block=None):
    return entity_resolver.Resolved("not_found", "village", text)

saved_states: list[dict] = []


async def _load_state(session_id):
    return {"context_state": saved_states[-1]} if saved_states else {}

patches = [
    (u, "build_frame", _build_frame),
    (pipeline, "classify_intent", _classify_intent),
    (pipeline, "generate_sql", _generate_sql),
    (pipeline, "execute_with_repair", _execute),
    (pipeline, "_execute_one_attempt", _one_attempt),
    (pipeline, "compose_response", _compose),
    (pipeline, "resolve_village", _no_village),
    (conversation_store, "persist_turn", lambda **k: None),
    (conversation_store, "save_context_state", lambda **k: saved_states.append(dict(k["context_state"]))),
    (conversation_store, "load_context_state", _load_state),
    (conversation_memory, "index_turn", lambda **k: None),
    (pipeline.clarification_engine, "check_clarifications", lambda *a, **k: None),
]
originals = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]
for obj, name, fn in patches:
    setattr(obj, name, fn)
flag_names = ("LANGGRAPH_FOLLOWUP_ENABLED", "PIPELINE_GRAPH_ENABLED", "PIPELINE_GRAPH_CANARY_PERCENT",
              "ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED", "QUERY_ANALYZER_ENABLED",
              "CONTEXT_SUMMARY_ENABLED", "CONTEXT_SEMANTIC_MEMORY_ENABLED", "RESPONSE_CACHE_ENABLED",
              "SEMANTIC_CACHE_ENABLED", "FOLLOWUP_REWRITE_ENABLED")
flags_before = {n: getattr(settings, n) for n in flag_names}
# This file tests the frame's own resume (app/nlu/frame_merge.py). The two
# LangGraph checkpointer resume owners own the pauses they checkpoint when
# their flags are on, so they are pinned off here (as test_query_stream does).
settings.LANGGRAPH_FOLLOWUP_ENABLED = False
settings.PIPELINE_GRAPH_ENABLED = False
settings.PIPELINE_GRAPH_CANARY_PERCENT = 0
settings.ENTITY_RESOLVER_SQUASH_FUZZY_ENABLED = True       # 'westgaro hils' needs resolver stage 6b
settings.QUERY_ANALYZER_ENABLED = False
settings.CONTEXT_SUMMARY_ENABLED = False
settings.CONTEXT_SEMANTIC_MEMORY_ENABLED = False
settings.RESPONSE_CACHE_ENABLED = False
settings.SEMANTIC_CACHE_ENABLED = False


def post(question, sid, choice=None):
    body = {"question": question, "session_id": sid}
    if choice:
        body.update(choice)
    r = client.post("/api/query", json=body)
    return r.status_code, r.json()


def opt(resp, label_start):
    return next((o for o in (resp.get("clarification") or {}).get("options") or []
                 if str(o.get("label", "")).startswith(label_start)), None)


try:
    SID = "slot-flow-1"
    print("\n=== turn 1: 'what is the expenditure' -> which scheme? ===")
    st, r = post("what is the expenditure", SID)
    check("200 + clarification", st == 200 and r.get("route") == "clarification", str(r)[:200])
    check("rule scheme-not-specified", (r.get("clarification") or {}).get("rule") == "scheme-not-specified")
    mg = opt(r, "MGNREGA")
    check("options carry {slot, value} next to the text question",
          mg is not None and mg.get("slot") == "scheme" and mg.get("value") == "MGNREGA" and mg.get("question"),
          str(mg))
    check("pending frame persisted with the conversation state (any worker can resume)",
          saved_states and (saved_states[-1].get("pending_frame") or {}).get("slot") == "scheme"
          and not saved_states[-1].get("pending_scope_q"), str(saved_states[-1] if saved_states else None)[:300])
    n_understand = len(understand_calls)

    print("\n=== turn 2: click MGNREGA -> slot filled, no model call ===")
    st, r = post(mg["question"], SID, {"slot": mg["slot"], "value": mg["value"]})
    check("200 + data answer", st == 200 and r.get("route") == "data", str(r)[:300])
    check("NO Understand call for a click", len(understand_calls) == n_understand)
    check("question rebuilt from the frame's scheme slot",
          r.get("rewritten_question") == "What is the expenditure for MGNREGA?", str(r.get("rewritten_question")))
    check("scheme from the filled slot", r.get("schemes") == ["MGNREGA"])
    check("statewide + FY 2025-26 defaults applied and disclosed",
          any("12 districts" in a for a in r.get("assumptions") or [])
          and any("FY 2025-26" in a for a in r.get("assumptions") or []), str(r.get("assumptions")))
    check("SQL question states the defaults (not the reply glued on)",
          sql_seen[-1]["question"] == "What is the expenditure for MGNREGA for all of Meghalaya for FY 2025-26",
          sql_seen[-1]["question"])
    check("statewide figure", "3628.67" in (r.get("answer") or ""))
    district_chip = next((o for o in r.get("correction_options") or [] if o.get("label") == "District"), None)
    check("'Change area' correction chips offered", district_chip is not None
          and district_chip.get("slot") == "area_level" and district_chip.get("value") == "district",
          str(r.get("correction_options")))

    print("\n=== turn 3: click District -> which district? ===")
    st, r = post(district_chip["question"], SID, {"slot": "area_level", "value": "district"})
    check("asks for the district name", st == 200 and r.get("route") == "clarification"
          and (r.get("clarification") or {}).get("rule") == "area-level-name"
          and "Which district" in (r.get("answer") or ""), str(r)[:200])
    check("still no Understand call", len(understand_calls) == n_understand)
    check("pending frame now asks the area slot at district level",
          (saved_states[-1].get("pending_frame") or {}).get("slot") == "area"
          and saved_states[-1]["pending_frame"].get("level") == "district")

    print("\n=== turn 4: type 'westgaro hils' -> exact answer ===")
    st, r = post("westgaro hils", SID)
    msg, ctx = understand_calls[-1]
    check("typed reply goes through Understand", len(understand_calls) == n_understand + 1 and msg == "westgaro hils")
    check("... WITH the pause as context", "Which district" in ((ctx.get("pending") or {}).get("asked") or ""),
          str(ctx.get("pending")))
    check("200 + data answer", st == 200 and r.get("route") == "data", str(r)[:300])
    check("'westgaro hils' resolved to WEST GARO HILLS", sql_seen[-1]["resolved"].get("district") == "WEST GARO HILLS",
          str(sql_seen[-1]["resolved"]))
    check("exact figure for West Garo Hills", "812.45" in (r.get("answer") or ""), r.get("answer"))
    q = r.get("rewritten_question") or ""
    check("question from the merged frame, not concatenation",
          q.startswith("What is the MGNREGA expenditure in westgaro hils") and q.count("westgaro hils") == 1
          and "What is the expenditure" not in q, q)
    check("pause consumed", not (session_store.get(SID).state.pending_frame or {}).get("kind") == "pause")

    print("\n=== durability: the reply lands on another worker ===")
    SID2 = "slot-flow-2"
    st, r = post("what is the expenditure", SID2)
    mg = opt(r, "MGNREGA")
    session_store._store.pop(SID2, None)                     # a different worker: no in-process session
    st, r = post(mg["question"], SID2, {"slot": "scheme", "value": "MGNREGA"})
    check("resumed from the persisted pending frame", st == 200 and r.get("route") == "data"
          and r.get("schemes") == ["MGNREGA"], str(r)[:200])

    print("\n=== a brand-new question drops the pause ===")
    SID3 = "slot-flow-3"
    post("what is the expenditure", SID3)
    st, r = post("how many houses completed in ekh", SID3)
    check("answered as its own question", st == 200 and r.get("route") == "data" and r.get("schemes") == ["PMAY-G"]
          and sql_seen[-1]["resolved"].get("district") == "EAST KHASI HILLS", str(r)[:200])
    check("pending frame dropped", session_store.get(SID3).state.pending_frame is None
          or session_store.get(SID3).state.pending_frame.get("kind") == "correction")

    print("\n=== a scheme settled by vocabulary survives the resume ===")
    SID5 = "slot-flow-5"
    st, r = post("how many houses completed", SID5)
    chip = next((o for o in r.get("correction_options") or [] if o.get("label") == "District"), None)
    check("'houses' -> PMAY-G answered statewide with a District chip",
          r.get("schemes") == ["PMAY-G"] and chip is not None, str(r)[:200])
    post(chip["question"], SID5, {"slot": "area_level", "value": "district"})
    st, r = post("ekh", SID5)
    check("bare 'ekh' reply keeps PMAY-G (no 'which scheme?') and pins EKH",
          r.get("route") == "data" and r.get("schemes") == ["PMAY-G"]
          and sql_seen[-1]["resolved"].get("district") == "EAST KHASI HILLS", str(r)[:200])
    check("... and the rebuilt question states the chosen level",
          "district" in (r.get("rewritten_question") or "").casefold(), str(r.get("rewritten_question")))

    print("\n=== node 5.3 engine chips are slot-filled too (the frame survives) ===")
    f5 = u.QueryFrame(rewritten_question="Which district has the worst PMAY-G completion rate?",
                      schemes=["PMAY-G"], metric="completion rate", query_type="ranking",
                      group_by="district", top_n=1)
    eopts = u.annotate_options("column-not-held", [
        {"label": "Report the overall rate",
         "question": "Which district has the worst completion rate for PMAY-G, Report the overall rate"}])
    check("engine chip carries {slot: engine_choice, value}", eopts[0].get("slot") == "engine_choice"
          and eopts[0]["value"]["label"] == "Report the overall rate")
    ef, eq = u.fill_slot({"frame": f5.model_dump(), "slot": "engine_choice",
                          "base_question": f5.rewritten_question}, "engine_choice", eopts[0]["value"])
    check("click keeps ranking / top 1 / district breakdown (not re-read as 'overall rate')",
          ef.query_type == "ranking" and ef.top_n == 1 and ef.group_by == "district", str(ef)[:200])
    check("... the chosen reading joins the metric, question = the chip's own wording",
          "Report the overall rate" in (ef.metric or "") and eq.startswith("Which district has the worst"))

    print("\n=== the chosen level is stated in the standalone question ===")
    g = [u.GeoMention(text="selsella", level="block")]
    check("'Which block?' + 'selsella' -> '... selsella block' (resolver reads the level)",
          u._with_level("What is the total disbursement for Focus Plus in selsella?", g, "block")
          == "What is the total disbursement for Focus Plus in selsella block?")
    check("level already stated -> unchanged",
          u._with_level("How many houses in selsella block?", g, "block") == "How many houses in selsella block?")

    print("\n=== no text-glue resume left ===")
    import inspect
    check("the pipeline body no longer merges a reply into a paused question",
          "pending_scope_q" not in inspect.getsource(pipeline._run_pipeline_body)
          and not hasattr(pipeline, "_run_pipeline_frame_mode"))
    check("the router stores only the frame pause (never pending_scope_q)",
          "pending_scope_q =" not in inspect.getsource(query_router._clarification_result))

    print("\n=== web/ai_query.html sends {slot, value} ===")
    html = (Path(__file__).resolve().parents[2] / "web" / "ai_query.html").read_text(encoding="utf-8")
    check("chips carry data-slot / data-value", "data-slot=" in html and "data-value=" in html)
    check("request body gets slot + value from the clicked chip only",
          "body.slot = pendingChoice.slot" in html and "pendingChoice.text === String(question).trim()" in html)
    check("correction chips rendered", "buildCorrections(response)" in html)
finally:
    for obj, name, fn in originals:
        setattr(obj, name, fn)
    for n, v in flags_before.items():
        setattr(settings, n, v)
    app.dependency_overrides.pop(query_router._identity, None)

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL SLOT-RESUME CHECKS PASSED")
