"""A typed (or spoken) pick at the D-099 CM Elevate dataset pause resumes the paused question (2026-11-15).

The context stage pinned the bare reply "CM Elevate" to "CM Elevate (applications)" (the pending question names CM
Elevate) BEFORE the pause resume, which then did not read it as a pick: the paused "CM Elevate applications WGH" was
dropped and the reply answered statewide (7,375 instead of 1,625; no-model gold bank PF-CE-*, CV-CE-01, W2-CED-*).
A tapped chip sends the full question and was never affected. Offline: the context stage alone, no DB, no model."""
from __future__ import annotations

import asyncio

import pytest

from app import entity_resolver as er
from app import pipeline as p
from app.session_store import Session

PAUSED = "CM Elevate applications WGH"


def _paused_session():
    s = Session(session_id="t", user_id="u", created=0.0, last_seen=0.0)
    ask = p._cm_elevate_dataset_pause(PAUSED)
    # what routers.query.remember_pause stores for a scheme pause
    s.pending_scope_q, s.pending_scope_rule = PAUSED, ask.rule
    s.pending_scope_options, s.pending_village_hint = list(ask.options), None
    return s


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    monkeypatch.setattr(er, "village_index_loaded", lambda: True)


@pytest.mark.parametrize("reply,want", [
    ("CM Elevate", "CM Elevate (applications) applications WGH"),
    ("cm elevate", "CM Elevate (applications) applications WGH"),
    ("CM Elevate please", "CM Elevate (applications) applications WGH"),
    ("CM Elevate Legacy", "CM Elevate Legacy applications WGH"),
    ("legacy", "CM Elevate Legacy applications WGH"),
])
def test_typed_pick_resumes_the_paused_question(reply, want):
    s = _paused_session()
    t = {"question": reply}
    asyncio.run(p._turn_context_stage(t, session=s))       # the stage updates the turn dict in place
    assert t["question"] == want, t["question"]
    assert s.pending_scope_q is None                       # the pause is consumed


def test_a_new_question_still_abandons_the_pause():
    s = _paused_session()
    t = {"question": "How many PMAY-G houses in Ri Bhoi?"}
    asyncio.run(p._turn_context_stage(t, session=s))
    assert "WGH" not in t["question"] and s.pending_scope_q is None
