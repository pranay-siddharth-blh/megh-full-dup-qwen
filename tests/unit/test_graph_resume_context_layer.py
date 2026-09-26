"""
tests/unit/test_graph_resume_context_layer.py — the context layer (app/conversation/context_manager.py)
must run on EVERY answered turn, including a turn answered by
app/orchestration/pipeline_graph.py's cross-request resume path.

Background. `app/api/routers/query.py`'s graph-resume branch calls
`pipeline_graph.resume_via_graph(session_id, question)` directly and assigns
the result, deliberately bypassing `answer_question`/`_run_pipeline` (a paused
graph thread must resume at the node it paused at, not restart from node 5.1).
But `context_manager.update_state()` / `maybe_update_summary()` and
`_attach_followups()` live inside `answer_question`, NOT inside
`_run_pipeline` — so bypassing `answer_question` silently skipped them:

  * ConversationState (scheme / district / block / village / year / metric)
    was never updated for the resumed turn, so the NEXT follow-up
    ("what about Ri Bhoi?") had no context to inherit — the exact multi-turn
    behavior app/conversation/context_manager.py exists to provide, and which the
    pre-LangGraph code in Old_meghalaya got for free because every turn there
    went through answer_question.
  * query.py then calls `conversation_store.save_context_state(...)` with that
    stale state, so the L2 durable mirror was overwritten with pre-turn data —
    the regression outlived the worker.
  * No `follow_up_options` ("Next steps" chips) on a resumed answer.

The same bypass does NOT affect `LANGGRAPH_FOLLOWUP_ENABLED`: that component's
`_classify_node` calls `pipeline.answer_question` itself, so the context layer
already ran there. Only the pipeline_graph resume path was affected.

`python tests/unit/test_graph_resume_context_layer.py`, exit code 0 = all pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.update(
    ENV="prod",
    AUTH_ENABLED="true",
    JWT_SECRET="test-secret-at-least-32-characters-long",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from starlette.testclient import TestClient  # noqa: E402

from app.orchestration import pipeline  # noqa: E402
from app.orchestration import pipeline_graph as pg  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.api.routers import query as query_router  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402

client = TestClient(app, raise_server_exceptions=False)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


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


_SCOPE = UserScope(user_id="ctxres-u1", role="admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "FOCUS_PLUS", "CM_ELEVATE"],
                   geographies="all", tenant_id=1, db_user_id=1, username="ctxres-tester")

app.dependency_overrides[query_router._identity] = lambda: _SCOPE


def _patches(scheme: str, district_display: str, district_resolved: str, year_key: int):
    """Mocks the LLM/DB-touching layer only — the REAL StateGraph, REAL SQLite
    checkpointer and REAL HTTP route still run, same pattern as
    tests/unit/test_query_pipeline_graph_resume.py."""
    async def _classify(_q):
        return [scheme], pipeline.ScopeMeta(confidence=0.95, source="shortcut",
                                            reason=f"Named scheme: {scheme}")

    calls: list[str] = []

    async def _resolve_scope_gate(question, *_a, **_kw):
        calls.append(question)
        if district_display.lower() not in question.lower():
            raise pipeline.ClarificationNeeded(
                "Which area?",
                options=[{"label": district_display,
                          "question": f"expenditure for {district_display}"}],
                rule="scope-not-specified")
        return {"resolved": {"district": district_resolved, "year_key": year_key},
                "display": {"district": district_display, "year": "FY 2023-24"},
                "notes": []}

    async def _gen_sql(*_a, **_kw):
        return "SELECT amount_disbursed FROM curated.v_expenditure LIMIT 5"

    async def _retrieve(*_a, **_kw):
        return []

    async def _execute_ok(sql, *_a, **_kw):
        return sql, [{"amount_disbursed": 12345}]

    async def _compose(*_a, **_kw):
        return "Total disbursement was 12,345."

    class _FakeQueryAnalyzer:
        async def analyze_query(self, *_a, **_kw):
            return None

    patches = [_Patcher(pipeline, n, f) for n, f in {
        "_classify_scheme_detailed": _classify,
        "resolve_entities": _resolve_scope_gate,
        "generate_sql": _gen_sql,
        "_execute_one_attempt": _execute_ok,
        "compose_response": _compose,
        "query_analyzer": _FakeQueryAnalyzer(),
    }.items()]
    patches.append(_Patcher(pipeline.schema_retrieval, "retrieve", _retrieve))
    patches.append(_Patcher(pipeline.clarification_engine, "check_clarifications",
                            lambda *_a, **_kw: None))
    # Focus Plus only: the tranche rule (clarify_rules rule 5) reads a
    # catalogue that is loaded at app startup from data/focus_plus/*.yaml,
    # which never happens in a test process — leaving it live makes
    # _tranche_clarification raise IndexError on an empty label list, which is
    # an artifact of the unloaded catalogue, not of the context-layer behavior
    # under test here. Switched off so all four schemes exercise the same
    # pause -> resume -> context path.
    patches.append(_Patcher(pipeline.settings, "TRANCHE_CLARIFY_ENABLED", False))
    return patches, calls


def _saved_states() -> list[dict]:
    """Captures what query.py hands conversation_store.save_context_state — the
    L2 durable mirror. A stale blob here is the part of the bug that survives a
    worker restart, so it is checked separately from in-process session.state."""
    return _CAPTURED


_CAPTURED: list[dict] = []


def _fake_save_context_state(*, session_id: str, context_state: dict) -> None:
    _CAPTURED.append(dict(context_state))


# `followups.build_followups` returns [] for every input in a test process (the
# suggestion catalogues are loaded at app startup from data/, which never
# happens here), so asserting on `follow_up_options` in the response would test
# the environment, not the wiring. Spy on the call instead: what this file is
# proving is that the resume branch RUNS the post-answer step at all.
_FOLLOWUP_CALLS: list[str] = []


# ── scenario: pause on turn 1, resume on turn 2, follow up on turn 3 ────────
try:
    settings.CONTEXT_LAYER_ENABLED = True
    settings.CONTEXT_STATE_ENABLED = True
    settings.LANGGRAPH_FOLLOWUP_ENABLED = False
    settings.PIPELINE_GRAPH_ENABLED = True
    settings.PIPELINE_GRAPH_CANARY_PERCENT = 0
    settings.FOLLOWUP_SUGGEST_ENABLED = True

    # Scheme ids exactly as scheme_registry.yaml spells them — the question text
    # has to name the scheme the way a user would, or node 5.1 raises its own
    # "which scheme?" clarification before the scope gate is ever reached.
    for scheme, disp, res in (("MGNREGA", "West Garo Hills", "WEST GARO HILLS"),
                              ("PMAY-G", "Ri Bhoi", "RI BHOI"),
                              ("Focus Plus", "East Khasi Hills", "EAST KHASI HILLS"),
                              ("CM Elevate", "South Garo Hills", "SOUTH GARO HILLS")):
        print(f"\n=== {scheme}: pause -> graph resume -> context layer must have run ===")
        pg._CHECKPOINT_DB_PATH.unlink(missing_ok=True)
        _CAPTURED.clear()
        sid = f"ctxres-{scheme.lower().replace(' ', '-')}"
        patches, calls = _patches(scheme, disp, res, 2023)

        _FOLLOWUP_CALLS.clear()
        _real_build = pipeline.followups.build_followups

        def _spy_build(route, question, *a, **kw):
            _FOLLOWUP_CALLS.append(question)
            return _real_build(route, question, *a, **kw)

        with _Multi(patches + [
            _Patcher(query_router.conversation_store,
                     "save_context_state", _fake_save_context_state),
            _Patcher(pipeline.followups, "build_followups", _spy_build),
        ]):
            r1 = client.post("/api/query",
                             json={"question": f"total {scheme} expenditure", "session_id": sid})
            check("turn 1 pauses for scope",
                  r1.status_code == 200 and r1.json().get("needs_clarification") is True,
                  r1.text[:300])
            check("turn 1 leaves the graph paused under this session_id",
                  asyncio.run(pg.is_paused(sid)) is True)

            r2 = client.post("/api/query", json={"question": disp, "session_id": sid})

        check("turn 2 (the resume) answered, not another clarification",
              r2.status_code == 200 and r2.json().get("needs_clarification") is not True,
              r2.text[:300])
        b2 = r2.json()
        check("turn 2 really went through the graph resume (row_count from the "
              "mocked execution)", b2.get("row_count") == 1, b2)

        sess = session_store.ensure(sid, _SCOPE.user_id)
        st = sess.state

        # ── the regression this file exists for ───────────────────────────
        check("CONTEXT LAYER RAN: scheme recorded in ConversationState after a "
              "graph-resumed turn", st.scheme == scheme,
              f"state.scheme={st.scheme!r} expected {scheme!r}")
        check("CONTEXT LAYER RAN: district recorded in ConversationState after a "
              "graph-resumed turn", (st.district or "").upper() == res,
              f"state.district={st.district!r} expected {res!r}")
        check("CONTEXT LAYER RAN: turn_count advanced for the resumed turn",
              st.turn_count >= 1, f"turn_count={st.turn_count}")
        check("FOLLOW-UP BUILDER RAN for the resumed turn (_attach_followups is "
              "reached, not skipped with the rest of answer_question's tail)",
              len(_FOLLOWUP_CALLS) == 1, _FOLLOWUP_CALLS)
        check("FOLLOW-UP BUILDER got the MERGED question, not the bare reply — "
              "the same standalone text the bespoke path would have passed",
              _FOLLOWUP_CALLS == [f"total {scheme} expenditure, {disp}"],
              _FOLLOWUP_CALLS)
        check("RESUMED TURN records the merged question as rewritten_question",
              b2.get("rewritten_question") == f"total {scheme} expenditure, {disp}",
              b2.get("rewritten_question"))
        check("L2 MIRROR FRESH: the context_state persisted after the resumed "
              "turn already carries that turn's scheme (not the stale pre-turn "
              "blob)",
              bool(_CAPTURED) and _CAPTURED[-1].get("scheme") == scheme,
              _CAPTURED[-1] if _CAPTURED else "nothing captured")

    # ── a resumed turn whose SQL can't be made to work must NOT 502 ────────
    # Reported from the live UI 2026-09-21: the §5.11 semantic verifier
    # rejected both the generated SQL and its one repair, so
    # _execute_one_attempt raised ValueError once the repair budget was spent.
    # On the bespoke path and the non-resume graph path _run_pipeline's
    # except-ladder turns that into a KB fallback / "try rephrasing" reply; the
    # resume branch bypassed _run_pipeline, so it escaped raw as 502 Bad
    # Gateway. See app/orchestration/pipeline.py::data_path_fallback_or_reraise.
    print("\n=== resumed turn, SQL unfixable: graceful answer, never a 502 ===")
    pg._CHECKPOINT_DB_PATH.unlink(missing_ok=True)
    _CAPTURED.clear()
    sid = "ctxres-verifier-fail"
    patches, calls = _patches("MGNREGA", "West Garo Hills", "WEST GARO HILLS", 2023)

    async def _execute_always_rejected(sql, *_a, **_kw):
        raise ValueError("semantic verifier flagged this query: Check 2 ...")

    async def _kb_miss(*_a, **_kw):
        return None  # KB has nothing either -> the "try rephrasing" reply

    with _Multi(patches + [
        _Patcher(pipeline, "_execute_one_attempt", _execute_always_rejected),
        _Patcher(pipeline.rag, "answer_from_kb", _kb_miss),
        _Patcher(query_router.conversation_store,
                 "save_context_state", _fake_save_context_state),
    ]):
        r1 = client.post("/api/query",
                         json={"question": "total MGNREGA expenditure", "session_id": sid})
        check("turn 1 pauses for scope", r1.json().get("needs_clarification") is True,
              r1.text[:200])
        r2 = client.post("/api/query",
                         json={"question": "West Garo Hills", "session_id": sid})

    check("resumed turn does NOT return 502 (the reported bug)",
          r2.status_code != 502, f"status={r2.status_code} body={r2.text[:200]}")
    check("resumed turn returns 200 with a usable reply",
          r2.status_code == 200, f"status={r2.status_code} body={r2.text[:200]}")
    check("the reply is the graceful fallback, carrying an answer string",
          bool((r2.json() or {}).get("answer")), r2.text[:200])

except Exception:  # noqa: BLE001
    import traceback
    traceback.print_exc()
    _fails.append("unexpected exception")

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + "; ".join(_fails))
    sys.exit(1)
print("ALL GRAPH-RESUME CONTEXT-LAYER CHECKS PASSED")
