"""
D-112 (2026-11-15): streaming without changing a figure.

  * POST /api/query/stream sends `answer` (the final result) BEFORE the turn's
    bookkeeping (durable save, history, cache writes) and `done` after it, with
    the same result; a clarification pause too. A client that leaves after the
    answer does not cancel the turn: its bookkeeping completes.
  * The rolling summary's model call runs beside a streamed answer and is
    awaited before the durable save (the next turn sees it, as before); the
    plain endpoint still writes it in line; a stopped turn cancels it.
  * The guardrail's village masking: the scheme scans run at once, the first
    scheme in the old order still wins; exact village reads are shared and kept
    for the turn (and in the app for 30 min), never across a swapped reader and
    never when the read failed.

Nothing here needs the VPN.
    .venv/Scripts/python.exe -m pytest tests/test_streaming_2026_11_15.py -q
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import context_manager, entity_resolver, turn_events  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import query as router  # noqa: E402
from app.session_store import Session  # noqa: E402


def _request():
    async def receive():
        await asyncio.sleep(3600)
    return Request({"type": "http", "method": "POST", "path": "/api/query/stream", "headers": [],
                    "client": ("127.0.0.1", 1), "query_string": b""}, receive)


def _frames(chunks):
    out = []
    for c in chunks:
        for frame in c.split("\n\n"):
            if frame.startswith("data: "):
                out.append(json.loads(frame[6:]))
    return out


async def _drain(resp):
    return [c async for c in resp.body_iterator]


@pytest.fixture
def turn(monkeypatch):
    """_answer with its side effects stubbed; the durable save marks the stream."""
    seen = SimpleNamespace(sync_out=0, pipeline=0, raise_pause=False, slow_save=0.0, summary_at_save=None)

    async def answer_question(q, session=None, scope=None):
        seen.pipeline += 1
        if seen.raise_pause:
            raise router.ClarificationNeeded("Which financial year?", options=[{"label": "FY 2023-24"}])
        return {"answer": "MGNREGA generated 27,666,670 person-days.", "route": "data", "row_count": 1,
                "data": [{"person_days": 27666670}]}

    async def sync_in(*a, **k):
        return None

    async def sync_out(session, *a, **k):
        turn_events.emit({"type": "step", "node": "SAVED"})        # where the save happened in the stream
        seen.summary_at_save = getattr(session, "summary", None)
        if seen.slow_save:
            await asyncio.sleep(seen.slow_save)
        seen.sync_out += 1

    async def noop(*a, **k):
        return None

    async def cache_miss(*a, **k):
        return None

    async def sem_miss(*a, **k):
        return None, None
    monkeypatch.setattr(router.response_cache, "get", cache_miss)
    monkeypatch.setattr(router.response_cache, "put", noop)
    monkeypatch.setattr(router.semantic_cache, "lookup", sem_miss)
    monkeypatch.setattr(router.semantic_cache, "put", noop)
    monkeypatch.setattr(router, "answer_question", answer_question)
    monkeypatch.setattr(router.session_sync, "sync_in", sync_in)
    monkeypatch.setattr(router.session_sync, "sync_out", sync_out)
    monkeypatch.setattr(router.conversation_store, "persist_turn", lambda **k: None)
    monkeypatch.setattr(router.conversation_memory, "index_turn", lambda **k: None)
    monkeypatch.setattr(router, "_mirror_audit", lambda *a, **k: None)
    seen.scope = SimpleNamespace(user_id="u", db_user_id=None, tenant_id=None, username="",
                                 cache_fingerprint=lambda: "fp")
    return seen


def _stream(turn, question, sid):
    async def go():
        resp = await router.query_stream(router.QueryRequest(question=question, session_id=sid, skip_cache=True),
                                         _request(), scope=turn.scope)
        return _frames(await _drain(resp))
    return asyncio.run(go())


# ── the `answer` event ──────────────────────────────────────────────────────

def test_answer_is_sent_before_the_bookkeeping_and_done_after_it_with_the_same_result(turn):
    frames = _stream(turn, "MGNREGA person-days in 2023-24", "s-d112-1")
    kinds = [f["type"] if f["type"] != "step" else f["node"] for f in frames]
    assert kinds.index("answer") < kinds.index("SAVED") < kinds.index("done")
    assert kinds[-1] == "done"
    answer = next(f for f in frames if f["type"] == "answer")["result"]
    done = frames[-1]["result"]
    assert answer == done
    assert answer["answer"] == "MGNREGA generated 27,666,670 person-days."


def test_a_clarification_pause_is_sent_as_an_answer_first(turn):
    turn.raise_pause = True
    frames = _stream(turn, "MGNREGA person-days", "s-d112-2")
    kinds = [f["type"] if f["type"] != "step" else f["node"] for f in frames]
    assert kinds.index("answer") < kinds.index("SAVED") < kinds.index("done")
    assert frames[-1]["result"]["intent"] == "CLARIFY"
    assert next(f for f in frames if f["type"] == "answer")["result"] == frames[-1]["result"]


def test_the_plain_endpoint_sends_nothing_and_answers_the_same(turn):
    out = asyncio.run(router._answer(router.QueryRequest(question="MGNREGA person-days in 2023-24",
                                                         session_id="s-d112-3", skip_cache=True),
                                     _request(), turn.scope))
    assert out["answer"] == "MGNREGA generated 27,666,670 person-days." and turn.sync_out == 1


def test_a_client_that_leaves_after_the_answer_does_not_cancel_the_turn(turn, monkeypatch):
    turn.slow_save = 0.2
    stopped = []
    monkeypatch.setattr(router, "_remember_stopped", lambda *a, **k: stopped.append(1))

    async def go():
        resp = await router.query_stream(router.QueryRequest(question="MGNREGA person-days in 2023-24",
                                                             session_id="s-d112-4", skip_cache=True),
                                         _request(), scope=turn.scope)
        it = resp.body_iterator
        got = []
        while True:
            chunk = await it.__anext__()
            got += _frames([chunk])
            if any(f["type"] == "answer" for f in got):
                break
        await it.aclose()               # the client goes away right after the answer
        await asyncio.sleep(0.5)        # the bookkeeping finishes in the background
        return got
    got = asyncio.run(go())
    assert any(f["type"] == "answer" for f in got)
    assert turn.sync_out == 1, "the durable save still ran"
    assert not stopped, "a delivered answer is not recorded as a stopped question"


def test_stop_before_the_answer_still_cancels_the_turn(turn, monkeypatch):
    state = {}
    stopped = []
    monkeypatch.setattr(router, "_remember_stopped", lambda *a, **k: stopped.append(1))

    async def slow(q, session=None, scope=None):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
    monkeypatch.setattr(router, "answer_question", slow)

    async def go():
        resp = await router.query_stream(router.QueryRequest(question="MGNREGA person-days in 2023-24",
                                                             session_id="s-d112-5", skip_cache=True),
                                         _request(), scope=turn.scope)
        it = resp.body_iterator
        task = asyncio.ensure_future(it.__anext__())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        await it.aclose()
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert state.get("cancelled") is True and stopped == [1] and turn.sync_out == 0


# ── the rolling summary beside the answer ───────────────────────────────────

def _summary_session(monkeypatch, delay=0.3):
    from app import llm
    calls = []

    async def rewriter(prompt, role=None):
        await asyncio.sleep(delay)
        calls.append(time.monotonic())
        return "The officer asked about MGNREGA person-days in Ri Bhoi."
    monkeypatch.setattr(llm, "call_rewriter", rewriter)
    monkeypatch.setattr(settings, "CONTEXT_SUMMARY_ENABLED", True)
    s = Session(session_id="s-sum", user_id="u", created=time.time(), last_seen=time.time())
    s.state.turn_count = settings.CONTEXT_SUMMARY_EVERY_N_TURNS
    s.turns.append(SimpleNamespace(question="MGNREGA person-days in Ri Bhoi"))
    return s, calls


def test_without_a_stream_the_summary_is_written_in_line(monkeypatch):
    s, calls = _summary_session(monkeypatch, delay=0.01)
    asyncio.run(context_manager.maybe_update_summary(s))
    assert s.summary.startswith("The officer asked") and len(calls) == 1
    assert s.summary_turn_count == settings.CONTEXT_SUMMARY_EVERY_N_TURNS


def test_a_deferred_summary_returns_at_once_and_lands_when_finished(monkeypatch):
    s, calls = _summary_session(monkeypatch)

    async def go():
        token, pending = context_manager.defer_summaries()
        try:
            t0 = time.monotonic()
            await context_manager.maybe_update_summary(s)
            returned = time.monotonic() - t0
            before = s.summary
            await context_manager.finish_summaries(pending)
            return returned, before
        finally:
            context_manager.end_defer(token, pending)
    returned, before = asyncio.run(go())
    assert returned < 0.1, "the answer does not wait for the summary"
    assert before is None
    assert s.summary.startswith("The officer asked")
    assert s.summary_turn_count == settings.CONTEXT_SUMMARY_EVERY_N_TURNS


def test_a_stopped_turn_cancels_its_summary(monkeypatch):
    s, calls = _summary_session(monkeypatch)

    async def go():
        token, pending = context_manager.defer_summaries()
        await context_manager.maybe_update_summary(s)
        context_manager.end_defer(token, pending)       # the turn failed / was stopped
        await asyncio.sleep(0.5)
    asyncio.run(go())
    assert s.summary is None and not calls


def test_the_stream_saves_the_summary_with_the_turn_after_the_answer(turn, monkeypatch):
    """The summary written beside a streamed answer is in the durable save, so the next
    turn (on this worker, or on another one through sync_in) sees it as before."""
    from app import llm
    monkeypatch.setattr(settings, "CONTEXT_SUMMARY_ENABLED", True)

    async def rewriter(prompt, role=None):
        await asyncio.sleep(0.2)
        return "A rolling summary."
    monkeypatch.setattr(llm, "call_rewriter", rewriter)

    async def answer_question(q, session=None, scope=None):
        session.state.turn_count = settings.CONTEXT_SUMMARY_EVERY_N_TURNS
        session.turns.append(SimpleNamespace(question=q))
        result = {"answer": "MGNREGA generated 27,666,670 person-days.", "route": "data", "row_count": 1}
        await context_manager.maybe_update_summary(session)     # what the context_update node does
        return result
    monkeypatch.setattr(router, "answer_question", answer_question)
    frames = _stream(turn, "MGNREGA person-days in 2023-24", "s-d112-6")
    kinds = [f["type"] if f["type"] != "step" else f["node"] for f in frames]
    assert kinds.index("answer") < kinds.index("SAVED")
    assert turn.summary_at_save == "A rolling summary."


# ── village masking ─────────────────────────────────────────────────────────

def test_the_first_scheme_in_the_old_order_still_wins(monkeypatch):
    order = []

    async def scan(text, scheme):
        order.append(scheme)
        if scheme == "PMAY-G":
            await asyncio.sleep(0.05)
            return ("MAWKYRWAT", [{}])
        if scheme == "Homestay":
            return ("KYRWAT", [{}])
        return None
    monkeypatch.setattr(p, "_scan_village_in_question", scan)
    out = asyncio.run(p._mask_village_names("houses in MAWKYRWAT during 2021-22"))
    assert out == "houses in the village during 2021-22"
    assert set(order) == set(p._C14_MASK_SCHEMES)


def test_the_scans_run_at_once(monkeypatch):
    async def scan(text, scheme):
        await asyncio.sleep(0.1)
        return None

    async def names(scheme):
        return {}
    monkeypatch.setattr(p, "_scan_village_in_question", scan)
    monkeypatch.setattr(p, "_scheme_village_names", names)
    t0 = time.monotonic()
    asyncio.run(p._mask_village_names("Top 5 districts by MGNREGA person-days in 2023-24"))
    assert time.monotonic() - t0 < 0.5, "eight 0.1 s scans one after another took 0.8 s"


def _counting_reader(monkeypatch, rows):
    calls = []

    async def fetch_rows(sql, params):
        calls.append(tuple(params[0]))
        await asyncio.sleep(0.02)
        return [dict(r) for r in rows]
    monkeypatch.setattr(entity_resolver, "fetch_rows", fetch_rows)
    return calls


ROW = {"village_code": 1, "lgd_village_name": "Selsella", "lgd_district": "WEST GARO HILLS",
       "lgd_block": "SELSELLA", "matched": "SELSELLA"}


def test_identical_reads_at_once_share_one_round_trip(monkeypatch):
    calls = _counting_reader(monkeypatch, [ROW])

    async def go():
        return await asyncio.gather(*(entity_resolver.village_names_exact(["Selsella"]) for _ in range(8)))
    outs = asyncio.run(go())
    assert len(calls) == 1
    assert all(o == {"SELSELLA": [{"village_code": 1, "name": "Selsella", "district": "WEST GARO HILLS",
                                   "block": "SELSELLA"}]} for o in outs)
    outs[0]["SELSELLA"].append("edited")
    assert outs[1]["SELSELLA"][-1] != "edited", "each caller gets its own copy"


def test_reads_are_kept_for_the_turn_only_outside_the_app(monkeypatch):
    calls = _counting_reader(monkeypatch, [ROW])
    monkeypatch.setattr(entity_resolver, "EXACT_VILLAGE_PROCESS_CACHE", False)

    async def turn():
        tok = entity_resolver.exact_village_turn()
        try:
            await entity_resolver.village_names_exact(["Selsella"])
            await entity_resolver.village_names_exact(["Selsella"])
        finally:
            entity_resolver.exact_village_turn_end(tok)
    asyncio.run(turn())
    assert len(calls) == 1, "kept within the turn"
    asyncio.run(turn())
    assert len(calls) == 2, "not kept across turns (a test process swaps the data under the reader)"
    asyncio.run(entity_resolver.village_names_exact(["Selsella"]))
    assert len(calls) == 3, "outside a turn: read every time"


def test_the_app_keeps_reads_until_the_catalogue_reload(monkeypatch):
    calls = _counting_reader(monkeypatch, [ROW])
    monkeypatch.setattr(entity_resolver, "EXACT_VILLAGE_PROCESS_CACHE", True)
    entity_resolver.clear_exact_village_cache()
    try:
        asyncio.run(entity_resolver.village_names_exact(["Selsella"]))
        asyncio.run(entity_resolver.village_names_exact(["Selsella"]))
        assert len(calls) == 1
        entity_resolver.clear_exact_village_cache()
        asyncio.run(entity_resolver.village_names_exact(["Selsella"]))
        assert len(calls) == 2
    finally:
        entity_resolver.clear_exact_village_cache()


def test_a_failed_read_is_never_kept(monkeypatch):
    calls = []

    async def broken(sql, params):
        calls.append(1)
        raise ConnectionError("db down")
    monkeypatch.setattr(entity_resolver, "fetch_rows", broken)
    monkeypatch.setattr(entity_resolver, "EXACT_VILLAGE_PROCESS_CACHE", True)
    entity_resolver.clear_exact_village_cache()
    try:
        assert asyncio.run(entity_resolver.village_names_exact(["Selsella"])) == {}
        assert asyncio.run(entity_resolver.village_names_exact(["Selsella"])) == {}
        assert len(calls) == 2
    finally:
        entity_resolver.clear_exact_village_cache()


def test_the_guardrail_masks_one_text_once(monkeypatch):
    masked = []

    async def mask(text):
        masked.append(text)
        return text
    monkeypatch.setattr(p, "_mask_village_names", mask)
    src = Path(p.__file__).parent.joinpath("common", "c14_turn_stages.py").read_text(encoding="utf-8")
    assert "if question == raw_question:" in src


# ── the SQL verifier beside the query ───────────────────────────────────────

VQ = "How many houses were sanctioned under PMAY-G?"
VSQL = "SELECT COUNT(*) AS houses_sanctioned FROM curated.v_pmay"


@pytest.fixture
def slow_db_and_verifier(monkeypatch):
    log = SimpleNamespace(verdict={"ok": True}, db_error=None, verifier_started=0, verifier_finished=0,
                          verifier_cancelled=0, verifier_s=0.3)

    async def precheck(sql):
        await asyncio.sleep(0.05)
        return None

    async def run_readonly(sql):
        await asyncio.sleep(0.3)
        if log.db_error:
            raise log.db_error
        return [{"houses_sanctioned": 12}]

    async def verifier(prompt, **_k):
        log.verifier_started += 1
        try:
            await asyncio.sleep(log.verifier_s)
        except asyncio.CancelledError:
            log.verifier_cancelled += 1
            raise
        log.verifier_finished += 1
        return json.dumps(log.verdict)
    monkeypatch.setattr(p, "db_precheck_readonly", precheck)
    monkeypatch.setattr(p, "run_readonly", run_readonly)
    monkeypatch.setattr(p.llm, "call_sql_verifier", verifier)
    monkeypatch.setattr(settings, "SQL_VERIFY_ENABLED", True)
    return log


def _attempt():
    async def go():
        t0 = time.monotonic()
        try:
            return await p._execute_one_attempt(VQ, ["PMAY-G"], {"resolved": {}, "unresolved": []}, VSQL), \
                time.monotonic() - t0
        finally:
            await asyncio.sleep(0.1)        # let a cancelled verifier settle before the loop closes
    return asyncio.run(go())


def test_the_verifier_runs_beside_the_query(slow_db_and_verifier):
    rows, took = _attempt()
    assert rows == [{"houses_sanctioned": 12}]
    assert took < 0.55, f"query 0.35 s + verifier 0.3 s overlapped, not added (took {took:.2f} s)"
    assert slow_db_and_verifier.verifier_finished == 1


def test_its_verdict_still_sends_the_query_to_repair(slow_db_and_verifier):
    slow_db_and_verifier.verdict = {"ok": False, "issue": "check 4: it sums a column unrelated to the question"}
    with pytest.raises(ValueError, match="semantic verifier flagged this query: check 4"):
        _attempt()


def test_a_database_error_cancels_the_verifier(slow_db_and_verifier):
    slow_db_and_verifier.db_error = RuntimeError('column "houses" does not exist')
    slow_db_and_verifier.verifier_s = 0.8
    with pytest.raises(RuntimeError, match="does not exist"):
        _attempt()
    assert slow_db_and_verifier.verifier_cancelled == 1 and slow_db_and_verifier.verifier_finished == 0


def test_a_row_check_failure_cancels_the_verifier(slow_db_and_verifier, monkeypatch):
    monkeypatch.setattr(p, "_c17_figure_reference_mismatch", lambda q, rows: "the figure does not match")
    slow_db_and_verifier.verifier_s = 0.8
    with pytest.raises(ValueError, match="the figure does not match"):
        _attempt()
    assert slow_db_and_verifier.verifier_finished == 0 and slow_db_and_verifier.verifier_cancelled == 1
