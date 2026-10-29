"""
E2 (RAG plan, 2026-10-29): the guardrail model fails closed for abuse only,
and every failure is counted and alerted on.

Audit 2026-10-23: "if the guardrail model times out, the answer goes out
unchecked, with no alert". Now, when the classifier cannot judge a message
(gateway error, timeout, unreadable reply), a message carrying an abuse word is
refused with "can't check right now", a plain scheme question still goes on,
and outage_monitor counts both and logs one ERROR "ALERT guardrail" line when
failures cluster.
"""
import asyncio
import json
import logging

import pytest

from app import guardrails, llm, pipeline
from app.config import settings


def _fake_model(monkeypatch, reply):
    async def fake_call_model(**kw):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_ENABLED", True)
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_FAIL_CLOSED", False)
    monkeypatch.setattr(llm, "call_model", fake_call_model)


@pytest.fixture
def monitor(monkeypatch):
    m = guardrails._OutageMonitor()
    monkeypatch.setattr(guardrails, "outage_monitor", m)
    return m


def _edge_stage(q: str):
    t = pipeline._new_turn(q)
    t.update(raw_question=q, question=q, scope_resumed=False, has_context=False)
    return asyncio.run(pipeline._turn_edge_stage(t, None, None))


# Not caught by layer 1 (no intent / target framing), so only the model judges them.
ABUSE_PAST_THE_RULES = [
    "where is ganja sold cheapest in shillong",
    "best pistol shop near tura",
    "which bank otp trick works on the scheme portal",
    "naked pictures of the mla",
]

PLAIN_QUESTIONS = [
    "total MGNREGA expenditure in Ri Bhoi in 2023-24",
    "how many PMAY-G houses were completed in East Khasi Hills",
    "who is eligible for CM Elevate?",
    "Focus Plus beneficiaries by district",
    "how to kill pests in paddy",
    "show it as a bar chart",
]


@pytest.mark.parametrize("q", ABUSE_PAST_THE_RULES)
def test_the_rules_alone_let_these_through(q):
    # the premise: only the model would have refused these
    assert guardrails.check_rules(q) is None


@pytest.mark.parametrize("q", ABUSE_PAST_THE_RULES)
def test_a_model_timeout_refuses_a_message_with_an_abuse_word(monkeypatch, monitor, q):
    _fake_model(monkeypatch, TimeoutError("gateway slow"))
    v = asyncio.run(guardrails.check_model(q))
    assert v is not None and v.category == "unverified"
    assert monitor.fail_closed == 1 and monitor.fail_open == 0
    assert monitor.by_error == {"TimeoutError": 1}


@pytest.mark.parametrize("q", PLAIN_QUESTIONS)
def test_a_model_timeout_lets_a_plain_question_through_and_counts_it(monkeypatch, monitor, q):
    _fake_model(monkeypatch, ConnectionError("gateway down"))
    assert asyncio.run(guardrails.check_model(q)) is None
    assert monitor.fail_open == 1 and monitor.fail_closed == 0


def test_an_unreadable_model_reply_is_an_outage_too(monkeypatch, monitor):
    _fake_model(monkeypatch, "I think this is fine")
    v = asyncio.run(guardrails.check_model("where is ganja sold cheapest in shillong"))
    assert v is not None and v.category == "unverified"
    assert asyncio.run(guardrails.check_model("houses completed in Ri Bhoi")) is None
    assert monitor.by_error == {"unusable_reply": 2}
    assert (monitor.fail_closed, monitor.fail_open) == (1, 1)


def test_fail_closed_setting_still_refuses_everything(monkeypatch, monitor):
    _fake_model(monkeypatch, TimeoutError("gateway slow"))
    monkeypatch.setattr(settings, "GUARDRAIL_MODEL_FAIL_CLOSED", True)
    v = asyncio.run(guardrails.check_model("total MGNREGA expenditure"))
    assert v is not None and v.category == "unsafe"
    assert monitor.fail_closed == 1


def test_a_working_model_is_not_counted(monkeypatch, monitor):
    _fake_model(monkeypatch, '{"verdict": "SAFE", "category": "none"}')
    assert asyncio.run(guardrails.check_model("where is ganja sold cheapest")) is None
    assert monitor.snapshot()["model_fail_open_total"] == 0
    assert monitor.recent() == 0


def test_the_outage_reply_says_not_now_not_against_the_rules():
    r = guardrails.RESPONSES["unverified"]
    assert r.startswith("I can't check that request safely right now")
    assert "against the rules" not in r and "try again" in r


def test_the_edge_stage_refuses_and_marks_the_reply_uncacheable(monkeypatch, monitor):
    _fake_model(monkeypatch, TimeoutError("gateway slow"))
    r = _edge_stage("where is ganja sold cheapest in shillong")
    assert r is not None and r["route"] == "edge" and r["edge_type"] == "unverified"
    # never cached: after the outage the same question must reach the model again
    assert r.get("context_dependent") is True
    assert r["sql"] is None and r["rows"] == []


def test_the_edge_stage_lets_a_plain_question_through_during_an_outage(monkeypatch, monitor):
    _fake_model(monkeypatch, TimeoutError("gateway slow"))
    r = _edge_stage("total MGNREGA expenditure in Ri Bhoi in 2023-24")
    assert r is None or r.get("edge_type") != "unverified"
    assert monitor.fail_open == 1


def test_a_burst_of_failures_logs_one_alert_per_window(monkeypatch, monitor, caplog):
    monkeypatch.setattr(settings, "GUARDRAIL_ALERT_THRESHOLD", 3)
    monkeypatch.setattr(settings, "GUARDRAIL_ALERT_WINDOW_SECONDS", 300.0)
    with caplog.at_level(logging.ERROR, logger="app.guardrails"):
        monitor.record("TimeoutError", False)
        monitor.record("TimeoutError", True)
        assert monitor.alerts == 0
        monitor.record("ConnectError", False)
        monitor.record("ConnectError", False)
    alerts = [r for r in caplog.records if "ALERT guardrail" in r.getMessage()]
    assert len(alerts) == 1 and monitor.alerts == 1
    snap = monitor.snapshot()
    assert snap["model_fail_open_total"] == 3 and snap["model_fail_closed_total"] == 1
    assert snap["model_failures_recent"] == 4 and snap["last_failure_at"] is not None


def test_failures_outside_the_window_do_not_alert(monkeypatch, monitor):
    monkeypatch.setattr(settings, "GUARDRAIL_ALERT_THRESHOLD", 3)
    monkeypatch.setattr(settings, "GUARDRAIL_ALERT_WINDOW_SECONDS", 300.0)
    clock = [1000.0]
    monkeypatch.setattr(guardrails.time, "monotonic", lambda: clock[0])
    for _ in range(2):
        monitor.record("TimeoutError", False)
    clock[0] += 301
    monitor.record("TimeoutError", False)
    assert monitor.alerts == 0 and monitor.recent() == 1


# ── The ALERT also goes to ALERT_WEBHOOK_URL when set (counts only) ─────────

def _mock_webhook(monkeypatch, status=200):
    import httpx
    sent = []

    def handler(request):
        sent.append((str(request.url), request.read().decode()))
        return httpx.Response(status)
    real = httpx.AsyncClient
    monkeypatch.setattr(guardrails.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return sent


def _outage_burst(monkeypatch, n=3):
    _fake_model(monkeypatch, TimeoutError("gateway slow"))
    monkeypatch.setattr(settings, "GUARDRAIL_ALERT_THRESHOLD", 3)

    async def run():
        for _ in range(n):
            await guardrails.check_model("where is ganja sold cheapest in shillong")
        await asyncio.gather(*list(guardrails._ALERT_TASKS))
    asyncio.run(run())


def test_the_alert_is_posted_once_with_counts_and_no_question_text(monkeypatch, monitor):
    sent = _mock_webhook(monkeypatch)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", "https://hooks.example.test/megh")
    _outage_burst(monkeypatch, n=4)
    assert len(sent) == 1 and monitor.alerts == 1
    url, body = sent[0]
    assert url == "https://hooks.example.test/megh"
    payload = json.loads(body)
    assert payload["alert"] == "guardrail_model_failing" and payload["recent_failures"] == 3
    assert "ganja" not in body and "shillong" not in body


def test_no_webhook_url_means_log_only(monkeypatch, monitor):
    sent = _mock_webhook(monkeypatch)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", "")
    _outage_burst(monkeypatch)
    assert monitor.alerts == 1 and sent == []


def test_a_failing_webhook_never_breaks_the_turn(monkeypatch, monitor):
    _mock_webhook(monkeypatch, status=500)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", "https://hooks.example.test/megh")
    _outage_burst(monkeypatch)
    assert monitor.alerts == 1 and monitor.fail_closed == 3
