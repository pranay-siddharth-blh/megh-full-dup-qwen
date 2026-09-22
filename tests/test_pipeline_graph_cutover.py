"""
openspec/changes/multi-tenant-rls-scheme-scaleout — the actual production
cutover wiring: settings.PIPELINE_GRAPH_ENABLED, previously defined but
read nowhere (confirmed by grep before this change existed), now gates a
real branch in app.pipeline._run_pipeline that calls
app.pipeline_graph.answer_data_via_graph_compat instead of
app.pipeline._answer_data.

Two things are checked, deliberately kept separate:
  1. answer_data_via_graph_compat's own new logic: a pause from the graph
     (interrupt()) is converted back into a ClarificationNeeded raise with
     the same shape _answer_data itself would raise — this is genuinely
     new code, not covered by tests/test_pipeline_graph.py (which tests
     answer_data_via_graph's OWN paused-dict-return contract, not this
     compat wrapper). Uses the same mocking boundary as
     tests/test_pipeline_graph.py.
  2. The _run_pipeline branch itself: flag off -> _answer_data called;
     flag on -> the graph adapter called instead. Checked by patching
     answer_data_via_graph_compat to a spy (not re-mocking the whole graph
     internals a second time) and sending a plain, non-edge-case,
     non-scheme-listing DATA question through the real _run_pipeline
     routing maze, so this also incidentally proves the flag doesn't
     disturb any of the routing that happens before the DATA route.

No DB, no live model gateway. Run: `python tests/test_pipeline_graph_cutover.py`,
exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import pipeline  # noqa: E402
from app import pipeline_graph as pg  # noqa: E402
from app.auth import UserScope  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import session_store  # noqa: E402

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


_SCOPE = UserScope(user_id="u1", role="admin", granularity_cap="village",
                    schemes=["MGNREGA"], geographies="all")


print("1. answer_data_via_graph_compat converts a graph pause into ClarificationNeeded "
      "(new logic — not covered by test_pipeline_graph.py, which tests the paused-dict "
      "return of the lower-level answer_data_via_graph it wraps)")


async def _fake_paused(*_a, **_kw):
    return {
        "paused": True,
        "clarification": {"question": "Which district?", "options": [{"label": "EKH", "question": "in EKH"}],
                          "rule": "scope-not-specified", "village_hint": None},
        "thread_id": "whatever",
    }


async def _fake_normal(*_a, **_kw):
    return {"route": "data", "answer": "42 workers", "schemes": ["MGNREGA"]}


async def _run_compat_pause():
    with _Patcher(pg, "answer_data_via_graph", _fake_paused):
        try:
            await pg.answer_data_via_graph_compat("how many workers", scope=_SCOPE)
            return None
        except pipeline.ClarificationNeeded as e:
            return e


e = asyncio.run(_run_compat_pause())
check("a paused graph result raises ClarificationNeeded, not returns a dict", e is not None)
if e is not None:
    check("question carried through", e.question == "Which district?", e.question)
    check("rule carried through", e.rule == "scope-not-specified", e.rule)
    check("options carried through", e.options == [{"label": "EKH", "question": "in EKH"}], e.options)
    check("village_hint carried through (None here, not a KeyError)", e.village_hint is None)


async def _run_compat_normal():
    with _Patcher(pg, "answer_data_via_graph", _fake_normal):
        return await pg.answer_data_via_graph_compat("how many workers", scope=_SCOPE)


normal = asyncio.run(_run_compat_normal())
check("a normal (non-paused) graph result is returned as-is",
      normal == {"route": "data", "answer": "42 workers", "schemes": ["MGNREGA"]}, normal)


print("1b. a converted pause cleans up its now-guaranteed-orphaned checkpoint "
     "thread (found+fixed 2026-09-17: this adapter never resumes via "
     "resume_via_graph, so every uncleaned pause was a permanent row leak)")

_delete_calls: list[str] = []


async def _spy_delete(thread_id):
    _delete_calls.append(thread_id)


async def _run_compat_pause_checks_cleanup():
    _delete_calls.clear()
    with _Patcher(pg, "answer_data_via_graph", _fake_paused), \
         _Patcher(pg, "_delete_orphaned_thread", _spy_delete):
        try:
            await pg.answer_data_via_graph_compat("how many workers", scope=_SCOPE)
        except pipeline.ClarificationNeeded:
            pass
    return _delete_calls


calls_after_pause = asyncio.run(_run_compat_pause_checks_cleanup())
check("the orphaned thread's checkpoint delete was called exactly once",
      calls_after_pause == ["whatever"], calls_after_pause)


async def _run_compat_normal_no_cleanup():
    _delete_calls.clear()
    with _Patcher(pg, "answer_data_via_graph", _fake_normal), \
         _Patcher(pg, "_delete_orphaned_thread", _spy_delete):
        await pg.answer_data_via_graph_compat("how many workers", scope=_SCOPE)
    return _delete_calls


calls_after_normal = asyncio.run(_run_compat_normal_no_cleanup())
check("a normal (non-paused) result never triggers cleanup — nothing to orphan",
      calls_after_normal == [], calls_after_normal)


print("1c. same cleanup, but end-to-end against the REAL graph + REAL SQLite "
     "checkpointer (not mocked) — proves the row is actually gone from disk, "
     "not just that the cleanup function was called")


async def _classify_ok(_q):
    return ["MGNREGA"], pipeline.ScopeMeta(confidence=0.9, source="shortcut", reason="named")


async def _resolve_ambiguous(*_a, **_kw):
    raise pipeline.ClarificationNeeded(
        "Which village?", options=[{"label": "A"}], rule="entity-ambiguous", village_hint="Rongram")


async def _run_real_pause_then_check_disk():
    pg._CHECKPOINT_DB_PATH.unlink(missing_ok=True)
    with _Patcher(pipeline, "_classify_scheme_detailed", _classify_ok), \
         _Patcher(pipeline, "resolve_entities", _resolve_ambiguous), \
         _Patcher(pipeline.schema_retrieval, "retrieve", lambda *_a, **_kw: asyncio.sleep(0, result=[])), \
         _Patcher(pipeline.clarification_engine, "check_clarifications", lambda *_a, **_kw: None):
        raised = None
        try:
            await pg.answer_data_via_graph_compat("job cards under MGNREGA", scope=_SCOPE)
        except pipeline.ClarificationNeeded as e:
            raised = e
    check("the real graph genuinely paused (entity-ambiguous)", raised is not None
          and raised.rule == "entity-ambiguous", raised)
    check("checkpoint file exists on disk (the pause really wrote one before cleanup)",
          pg._CHECKPOINT_DB_PATH.exists())
    # Every thread this test run could plausibly have created — since
    # answer_data_via_graph_compat never exposes the thread_id to us
    # (that's the whole point: the caller can't resume it even if it
    # wanted to), the only way to prove no LIVE thread survived is to
    # inspect the checkpointer's own state for every thread_id LangGraph's
    # internal machinery could have used. We know there's exactly one
    # (this call made exactly one graph invocation), so open the
    # checkpointer, list its threads via the sqlite table directly, and
    # confirm zero rows remain.
    import sqlite3
    conn = sqlite3.connect(str(pg._CHECKPOINT_DB_PATH))
    try:
        n = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
    finally:
        conn.close()
    check("zero checkpoint rows remain on disk after cleanup — not just "
          "deleted-in-theory, actually gone from the real SQLite file",
          n == 0, n)


asyncio.run(_run_real_pause_then_check_disk())

print("2. _run_pipeline's flag branch actually reroutes to the graph adapter, "
      "and leaves everything else (routing before the DATA route) unaffected")

_QUESTION = "how many MGNREGA workers are there in East Khasi Hills"
_calls: list[str] = []


async def _spy_graph(*_a, **_kw):
    _calls.append("graph")
    return {"route": "data", "answer": "graph-answer", "schemes": ["MGNREGA"], "data": [], "rows": []}


async def _spy_bespoke(*_a, **_kw):
    _calls.append("bespoke")
    return {"route": "data", "answer": "bespoke-answer", "schemes": ["MGNREGA"], "data": [], "rows": []}


async def _run_flagged(flag: bool):
    _calls.clear()
    session = session_store.ensure(f"test-cutover-{flag}", _SCOPE.user_id)
    session.scope = _SCOPE
    orig_flag = settings.PIPELINE_GRAPH_ENABLED
    settings.PIPELINE_GRAPH_ENABLED = flag
    try:
        with _Patcher(pg, "answer_data_via_graph_compat", _spy_graph), \
             _Patcher(pipeline, "_answer_data", _spy_bespoke):
            result = await pipeline._run_pipeline(_QUESTION, session=session, scope=_SCOPE)
    finally:
        settings.PIPELINE_GRAPH_ENABLED = orig_flag
    return result


result_off = asyncio.run(_run_flagged(False))
check("flag OFF -> _answer_data (bespoke path) is called", _calls == ["bespoke"], _calls)
check("flag OFF -> response is the bespoke path's own answer",
      result_off.get("answer") == "bespoke-answer", result_off)

result_on = asyncio.run(_run_flagged(True))
check("flag ON -> pipeline_graph.answer_data_via_graph_compat is called instead", _calls == ["graph"], _calls)
check("flag ON -> response is the graph path's own answer",
      result_on.get("answer") == "graph-answer", result_on)

print("3. PIPELINE_GRAPH_CANARY_PERCENT staged rollout (5.2) — session-sticky, "
      "ignored once PIPELINE_GRAPH_ENABLED itself is True")


def _with_flags(enabled: bool, pct: int):
    orig_enabled, orig_pct = settings.PIPELINE_GRAPH_ENABLED, settings.PIPELINE_GRAPH_CANARY_PERCENT
    settings.PIPELINE_GRAPH_ENABLED, settings.PIPELINE_GRAPH_CANARY_PERCENT = enabled, pct
    return orig_enabled, orig_pct


def _restore_flags(orig_enabled, orig_pct):
    settings.PIPELINE_GRAPH_ENABLED, settings.PIPELINE_GRAPH_CANARY_PERCENT = orig_enabled, orig_pct


_S1 = session_store.ensure("test-canary-session-1", "u1")
_S2 = session_store.ensure("test-canary-session-2", "u1")

orig = _with_flags(False, 0)
check("0% canary, flag off -> never selected", pipeline._pipeline_graph_selected(_S1) is False)
_restore_flags(*orig)

orig = _with_flags(False, 100)
check("100% canary, flag off -> always selected", pipeline._pipeline_graph_selected(_S1) is True)
_restore_flags(*orig)

orig = _with_flags(False, 1)
check("1% canary -> no session (no stable identity) never selected",
      pipeline._pipeline_graph_selected(None) is False)
_restore_flags(*orig)

orig = _with_flags(False, 50)
r1a = pipeline._pipeline_graph_selected(_S1)
r1b = pipeline._pipeline_graph_selected(_S1)
check("same session -> deterministic, repeated calls agree", r1a == r1b, (r1a, r1b))
_restore_flags(*orig)

orig = _with_flags(True, 0)
check("PIPELINE_GRAPH_ENABLED=True overrides a 0% canary -> always selected",
      pipeline._pipeline_graph_selected(_S1) is True)
_restore_flags(*orig)

# Spread check: with enough distinct sessions at 50%, both paths should be hit
# at least once — not a strict distribution assertion (that would be flaky),
# just proof the bucketing isn't degenerate (e.g. always the same branch).
orig = _with_flags(False, 50)
_seen = {pipeline._pipeline_graph_selected(session_store.ensure(f"test-canary-spread-{i}", f"user-{i}"))
         for i in range(40)}
check("50% canary across 40 distinct users hits both branches", _seen == {True, False}, _seen)
_restore_flags(*orig)

print()
if _fails:
    print(f"FAILED: {len(_fails)} check(s) — {_fails}")
    sys.exit(1)
print("ALL CHECKS PASSED")
