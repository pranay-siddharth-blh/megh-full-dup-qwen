"""KI-333 (live 2026-10-19 16:00-16:02): after "... by district as a chart",
"But give me only pie chart." lost "by district" in the model rewrite, and "So I asked
about pie chart, right? But why you are giving line chart? Give me a wide frame, okay."
went to the scheme documents. A message that only asks how to show the last answer is
the previous data question again, with that view (c15 _chart_view_question)."""
import pytest

from app import pipeline as p

PREV_Q = ("Show the number of households that provided 100 days of work in MGNREGA for all of Meghalaya "
          "across all financial years by district as a chart")
BASE = PREV_Q[:-len(" as a chart")]


def _prev(q=PREV_Q, resolved=None):
    t = type("T", (), {})()
    t.route, t.question, t.resolved_entities = "data", q, resolved or {}
    return t


def _turn(raw):
    t = type("T", (), {})()
    t.raw_question = raw
    return t


def test_the_users_complaint_redraws_as_the_pie_asked_for_with_an_apology_and_wide():
    q, preface, wide = p._chart_view_question(
        "So I asked about pie chart, right? But why you are giving line chart? Give me a wide frame, okay.", _prev())
    assert q == f"{BASE} as a pie chart"
    assert preface and preface.startswith("Sorry") and "pie chart" in preface
    assert wide is True


@pytest.mark.parametrize("msg, view", [
    ("But give me only pie chart.", "a pie chart"),
    ("But give me only pie chart. for above query", "a pie chart"),
    ("But in Meghalaya only pie chart.", "a pie chart"),
    ("I want only in Barchart", "a bar chart"),
    ("show it as a table", "a table"),
    ("line chart please", "a line chart"),
])
def test_view_only_messages_keep_the_breakdown(msg, view):
    q, preface, wide = p._chart_view_question(msg, _prev())
    assert q == f"{BASE} as {view}"
    assert preface is None and wide is False


def test_a_complaint_alone_uses_the_last_type_asked_never_the_one_complained_of():
    q, preface, _ = p._chart_view_question("why are you giving line chart", _prev(),
                                           [_turn("But give me only pie chart.")])
    assert q.endswith("as a pie chart") and preface
    q, _, _ = p._chart_view_question("why are you giving line chart", _prev(), [])
    assert q.endswith("as a bar chart")


def test_wide_alone_keeps_the_last_type():
    q, _, wide = p._chart_view_question("give me a wide frame", _prev(), [_turn("But give me only pie chart.")])
    assert q.endswith("as a pie chart") and wide


@pytest.mark.parametrize("msg", ["what about East Khasi Hills", "How many PMAY-G houses in pie chart",
                                 "line please", "pie chart for each year"])
def test_questions_with_their_own_content_are_not_view_requests(msg):
    assert p._chart_view_question(msg, _prev()) is None


def test_meghalaya_after_a_district_answer_is_a_new_scope():
    assert p._chart_view_question("Meghalaya pie chart", _prev(resolved={"district": "EAST GARO HILLS"})) is None


def test_the_chart_hint_reads_the_rewritten_question_first():
    rows = [{"district": "A", "n": 1}, {"district": "B", "n": 2}]
    assert p._chart_hint(f"{BASE} as a pie chart",
                         "I asked about pie chart, why you are giving line chart", rows) == "pie"
    assert p._chart_hint(f"{BASE} as a bar chart",
                         "I asked for line chart, why are you giving pie chart", rows) == "bar"


def test_a_chart_complaint_is_not_a_reference_to_an_earlier_question(monkeypatch):
    # live 2026-10-19 16:12: topic memory read "I asked about pie chart" as a pointer
    # to an earlier question and cut it off; the redraw then came out as a bar chart
    import asyncio
    from app import llm, topic_memory as tm

    async def no_model(*_a, **_k):
        raise AssertionError("the reference model must not be asked")
    monkeypatch.setattr(tm, "_enabled", lambda s: True)
    monkeypatch.setattr(tm, "_ledger_on", lambda: True)
    monkeypatch.setattr(tm, "_memory", lambda s: {})
    monkeypatch.setattr(tm, "_ledger_entries", lambda m: [("MGNREGA", {"n": 1, "question": PREV_Q})])
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    session = type("S", (), {"pending_scope_q": None, "turn_context": {}})()
    msg = "So I asked about pie chart, right? But why you are giving line chart? Give me a wide frame, okay."
    assert asyncio.run(tm.resolve_reference(session, msg)) is None
