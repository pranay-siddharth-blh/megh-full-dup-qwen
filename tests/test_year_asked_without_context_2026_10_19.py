"""D-053 (2026-10-19): a data question that names no financial year asks which
year unless the conversation already carries one. The all-years default of
D-045 stays for a question whose context has a year (a follow-up inherits it)
and for the chip replies, which name the year themselves.

Live 2026-10-18: "total beneficiaries for MGNREGA" on a fresh thread was
answered as 1,494,437 household-years across every year without asking."""
import asyncio

import pytest

from app import pipeline as p


# The new-chat district / year asks these tests cover are the rollback path since the user's
# 2026-10-29 decision (D-089, NEW_CHAT_ASKS_SCOPE=false answers statewide / all years instead;
# tests/test_rag_fix_report_2026_10_29.py). They still guard that path with the switch on.
@pytest.fixture(autouse=True)
def _new_chat_asks_scope(monkeypatch):
    from app.config import settings as _s
    monkeypatch.setattr(_s, "NEW_CHAT_ASKS_SCOPE", True)


def _run(d):
    return asyncio.run(p._data_clarification_stage(d))


def _turn(question, schemes, prior_resolved=None, resolved=None, chat_has_scope=True, skip=False):
    # chat_has_scope=True: a chat that has answered before, so no D-056 district
    # pause; the new-chat district pause is in tests/test_new_chat_and_scheme_switch_2026_10_21.py.
    d = p._new_data_turn(question, prior_resolved=prior_resolved, skip_scope_clarify=skip)
    d["schemes"] = schemes
    d["chat_has_scope"] = chat_has_scope
    d["entity_result"] = {"resolved": dict(resolved or {}), "display": {}, "question": None}
    return d


@pytest.fixture(autouse=True)
def _defaults_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ANSWER_DEFAULTS_ENABLED", True)
    monkeypatch.setattr(settings, "YEAR_CLARIFY_ENABLED", True)


def test_fresh_question_with_no_year_asks_which_year():
    # D-056: a new chat asks the district first; its chip resumes the question
    # (skip_scope_clarify) and THEN the year is asked.
    d = _turn("total beneficiaries for MGNREGA", ["MGNREGA"], chat_has_scope=False)
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "scope-not-specified"
    d = _turn("total beneficiaries for MGNREGA for West Garo Hills", ["MGNREGA"], chat_has_scope=False,
              skip=True, resolved={"district": "WEST GARO HILLS"})
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "year-not-specified"
    labels = [o["label"] for o in exc.value.options]
    assert "All financial years combined" in labels
    assert any(l.startswith("FY ") for l in labels)
    # the chips resume with a standalone question that names the year
    assert all(" for FY " in o["question"] or "across all financial years" in o["question"]
               for o in exc.value.options)


def test_fresh_pmay_question_with_a_district_but_no_year_asks_too():
    d = _turn("how many PMAY-G houses were completed in East Khasi Hills", ["PMAY-G"],
              resolved={"district": "EAST KHASI HILLS"})
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "year-not-specified"


def test_follow_up_with_a_year_in_context_is_not_asked():
    # a follow-up seeds prior_resolved from the previous turn (data_context stage)
    d = _turn("total beneficiaries for MGNREGA", ["MGNREGA"], prior_resolved={"year_key": 2023})
    assert _run(d) is None
    assert d["question"].endswith("across all financial years")


def test_follow_up_after_an_all_years_choice_is_not_asked():
    d = _turn("total beneficiaries for MGNREGA", ["MGNREGA"], prior_resolved={"year_all": True})
    assert _run(d) is None


def test_chip_reply_naming_the_year_is_not_asked_again():
    d = _turn("total beneficiaries for MGNREGA for all of Meghalaya for FY 2023-24", ["MGNREGA"])
    assert _run(d) is None
    d = _turn("total beneficiaries for MGNREGA for all of Meghalaya across all financial years", ["MGNREGA"])
    assert _run(d) is None


def test_time_series_is_not_asked_but_job_cards_are():
    d = _turn("how have MGNREGA person-days changed over the last three years in Meghalaya", ["MGNREGA"])
    assert _run(d) is None
    # Job cards were exempt and silently read FY 2025-26 whatever was asked; the
    # user's rule (2026-10-21): the year asked, else the chat's year, else ask.
    d = _turn("total MGNREGA job cards issued in Meghalaya", ["MGNREGA"])
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "year-not-specified"


def test_scheme_without_years_is_never_asked():
    d = _turn("total CM Elevate applications in Meghalaya", ["CM Elevate"])
    assert _run(d) is None


# ── KI-324: a typed "all of them combined" answers the year pause ──────────────
@pytest.mark.parametrize("reply", [
    "all of them combined", "All financial years combined", "all of them", "all", "combined",
    "all years", "every year", "all the years together", "overall", "everything",
])
def test_typed_all_years_replies_are_read_as_the_all_years_chip(reply):
    assert p._is_all_years_reply(reply)


@pytest.mark.parametrize("reply", [
    "2023-24", "FY 2024-25", "all person-days", "all of Meghalaya", "all districts", "show it year-wise",
    "what about PMAY-G", "all MGNREGA households", "total expenditure", "",
])
def test_other_replies_are_not_all_years(reply):
    assert not p._is_all_years_reply(reply)
