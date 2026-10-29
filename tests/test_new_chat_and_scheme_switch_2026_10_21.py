"""D-056 (user rule 2026-10-21): a new chat asks what it does not know, in order —
scheme, then district, then year; a chat that already has a scope carries it
forward into every new question, on ANY scheme, and the user's new words replace
only what they name.

Live 2026-10-21 (new chat): "how many households" -> scheme chips -> MGNREGA ->
asked the YEAR only (the district was silently "all of Meghalaya"). Then, after
"MGNREGA · West Garo Hills · FY 2022-23", "how many households for PMAY-G" asked
the year again and dropped West Garo Hills."""
import asyncio

import pytest

from app import entity_resolver
from app import pipeline as p
from app.session_store import ConversationState


# The new-chat district / year asks these tests cover are the rollback path since the user's
# 2026-10-29 decision (D-089, NEW_CHAT_ASKS_SCOPE=false answers statewide / all years instead;
# tests/test_rag_fix_report_2026_10_29.py). They still guard that path with the switch on.
@pytest.fixture(autouse=True)
def _new_chat_asks_scope(monkeypatch):
    from app.config import settings as _s
    monkeypatch.setattr(_s, "NEW_CHAT_ASKS_SCOPE", True)


@pytest.fixture(scope="module", autouse=True)
def _catalogues():
    entity_resolver.load_all()


@pytest.fixture(autouse=True)
def _defaults_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ANSWER_DEFAULTS_ENABLED", True)
    monkeypatch.setattr(settings, "YEAR_CLARIFY_ENABLED", True)
    monkeypatch.setattr(settings, "SCOPE_CLARIFY_ENABLED", True)


def _turn(question, schemes, *, chat_has_scope=False, prior_resolved=None, resolved=None, skip=False):
    d = p._new_data_turn(question, prior_resolved=prior_resolved, skip_scope_clarify=skip)
    d["schemes"] = schemes
    d["chat_has_scope"] = chat_has_scope
    d["entity_result"] = {"resolved": dict(resolved or {}), "display": {}, "question": None}
    return d


def _run(d, scope=None):
    return asyncio.run(p._data_clarification_stage(d, scope))


# ── a new chat: district before year ──────────────────────────────────────────
def test_new_chat_without_a_place_asks_the_district_first():
    # J-4 / J-5 (chat UI audit 2026-10-29, user decision): only a question that does
    # not name its own scheme still asks the district first
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(_turn("how many households", ["MGNREGA"]))
    e = exc.value
    assert e.rule == "scope-not-specified"
    labels = [o["label"] for o in e.options]
    assert "West Garo Hills" in labels and labels[-1] == "All of Meghalaya"
    assert "time period" not in str(e)          # the year is its own next question
    assert all(o["question"].startswith("how many households") for o in e.options)


def test_new_chat_naming_its_scheme_is_statewide_and_asks_only_the_year():
    # J-5: one tap (the year, D-053), not two; the area is all of Meghalaya, said in
    # the question the year chips carry
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(_turn("how many households for MGNREGA", ["MGNREGA"]))
    e = exc.value
    assert e.rule == "year-not-specified"
    assert all("all of Meghalaya" in o["question"] for o in e.options)


def test_new_chat_district_chip_then_asks_the_year():
    d = _turn("how many households for MGNREGA for West Garo Hills", ["MGNREGA"], skip=True,
              resolved={"district": "WEST GARO HILLS"})
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "year-not-specified"


def test_new_chat_statewide_chip_then_asks_the_year():
    d = _turn("how many households for MGNREGA for all of Meghalaya", ["MGNREGA"], skip=True)
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "year-not-specified"


def test_new_chat_naming_a_year_but_no_place_still_asks_the_district():
    # J-4 (user decision 2026-10-29): with its scheme named, it is answered statewide
    d = _turn("how many households for MGNREGA in FY 2022-23", ["MGNREGA"], resolved={"year_key": 2022})
    assert _run(d) is None
    # with no scheme of its own, the district is still asked first
    d = _turn("how many households in FY 2022-23", ["MGNREGA"], resolved={"year_key": 2022})
    with pytest.raises(p.ClarificationNeeded) as exc:
        _run(d)
    assert exc.value.rule == "scope-not-specified"


def test_new_chat_naming_place_and_year_is_answered():
    d = _turn("how many households for MGNREGA in West Garo Hills in FY 2022-23", ["MGNREGA"],
              resolved={"district": "WEST GARO HILLS", "year_key": 2022})
    assert _run(d) is None


def test_new_chat_breakdown_or_statewide_question_is_not_asked_the_district():
    assert _run(_turn("MGNREGA households by district in FY 2022-23", ["MGNREGA"],
                      resolved={"year_key": 2022})) is None
    assert _run(_turn("how many households for MGNREGA in Meghalaya in FY 2022-23", ["MGNREGA"],
                      resolved={"year_key": 2022})) is None


def test_a_chat_with_a_scope_is_not_asked_the_district():
    d = _turn("how many households for MGNREGA", ["MGNREGA"], chat_has_scope=True, prior_resolved={"year_key": 2022},
              resolved={"year_key": 2022})
    assert _run(d) is None          # statewide context stays statewide, no pause


def test_a_district_restricted_officer_is_not_asked():
    from app.auth import UserScope
    scope = UserScope(user_id="u", role="district_officer", granularity_cap="village", schemes=["MGNREGA"],
                      geographies={"districts": ["WEST GARO HILLS"], "blocks": []})
    d = _turn("how many households for MGNREGA in FY 2022-23", ["MGNREGA"], resolved={"year_key": 2022})
    assert _run(d, scope) is None


def test_chat_has_data_scope_reads_the_structured_state():
    class _S:
        state = ConversationState()
    assert not p._chat_has_data_scope(_S())
    assert not p._chat_has_data_scope(None)
    _S.state = ConversationState(scheme="MGNREGA")
    assert p._chat_has_data_scope(_S())


# ── a chat with a scope: carried forward, on any scheme ───────────────────────
MG_WGH_2022 = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", year=2022)


def _carry(q, st=MG_WGH_2022):
    return p._same_scheme_context_year(q, q, st)


# D-061 (user addendum 2026-10-22, "New Question = New Answer") narrows D-056 §2:
# a question with its OWN scheme and measure and no reference cue is a new
# question and carries nothing ("how many households for PMAY-G" after an MGNREGA
# West Garo Hills FY 2022-23 answer is statewide, latest FY). What still carries
# is a question that leaves the scope out on purpose: a measure with no scheme
# named ("how many job cards", "how many houses") or a reference ("there").

@pytest.mark.parametrize("q", ["how many households for PMAY-G", "how many households for Focus Plus",
                               "how many households for PMAY-G in FY 2017-18",
                               "how many households for PMAY-G for all of Meghalaya", "PMAY-G houses by district",
                               "PMAY-G houses by block", "houses for PMAY-G", "how many applications for CM Elevate",
                               "Which district has the highest beneficiaries in MGNREGA?",
                               "How many person-days in MGNREGA in 2022-23?"])
def test_a_standalone_question_carries_nothing(q):
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", block="DALU", year=2022)
    assert _carry(q, st) is None


def test_a_question_without_a_scheme_carries():
    assert _carry("how many job cards") == {"year_key": 2022, "district": "WEST GARO HILLS"}


def test_a_typed_year_replaces_only_the_year():
    assert _carry("how many job cards there in FY 2023-24") == {"district": "WEST GARO HILLS"}


def test_statewide_or_by_district_drops_the_place_but_keeps_the_year():
    assert _carry("how many job cards for all of Meghalaya") == {"year_key": 2022}
    assert _carry("job cards by district") == {"year_key": 2022}


def test_the_asked_level_and_below_are_never_the_filter():
    # D-061 slot-conflict guard: "which district" cannot be filtered by a district
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", block="DALU", year=2022)
    assert _carry("which district has the most job cards", st) == {"year_key": 2022}
    assert _carry("which block has the most job cards", st) == {"year_key": 2022, "district": "WEST GARO HILLS"}
    assert _carry("top 5 villages by job cards", st) == {"year_key": 2022, "district": "WEST GARO HILLS",
                                                          "block": "DALU"}


def test_a_breakdown_below_the_district_keeps_the_district():
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", block="DALU", year=2022)
    assert _carry("houses by block", st) == {"year_key": 2022, "district": "WEST GARO HILLS"}
    assert _carry("how many houses", st) == {"year_key": 2022, "district": "WEST GARO HILLS", "block": "DALU"}


def test_a_year_the_new_scheme_does_not_hold_is_not_carried():
    # MGNREGA FY 2025-26 -> PMAY-G (2017-18 .. 2023-24): the year chips ask; the place stays
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", year=2025)
    assert _carry("how many houses", st) == {"district": "WEST GARO HILLS"}


def test_all_years_carries_across_schemes():
    st = ConversationState(scheme="MGNREGA", district="RI BHOI", year_all=True)
    assert _carry("how many houses", st) == {"year_all": True, "district": "RI BHOI"}


def test_a_comparison_or_an_empty_chat_carries_nothing():
    assert _carry("compare MGNREGA and PMAY-G spending") is None
    assert _carry("how many houses for PMAY-G", ConversationState()) is None


def test_a_model_inferred_place_is_not_carried():
    st = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", year=2022)
    st.provenance = {"district": {"source": "model_inference"}}
    assert _carry("how many houses", st) == {"year_key": 2022}


# ── the resolver never keeps an old block under a new district ────────────────
def _stub(monkeypatch, mentions):
    async def _extract(q):
        return dict(mentions)

    async def _no_village(*a, **k):
        return entity_resolver.Resolved("not_found", "village", str(a[0]) if a else "")

    async def _none(*a, **k):
        return None

    async def _no_contents(*a, **k):
        return {"districts": [], "blocks": [], "villages": 0}

    async def _no_names():
        return {}

    async def _no_exact(cands):
        return {}

    monkeypatch.setattr(p, "extract_entity_mentions", _extract)
    monkeypatch.setattr(p, "resolve_village", _no_village)
    monkeypatch.setattr(p, "_scan_village_in_question", _none)
    monkeypatch.setattr(p, "constituency_contents", _no_contents)
    monkeypatch.setattr(p, "_mgnrega_village_names", _no_names)
    monkeypatch.setattr(p, "village_names_exact", _no_exact)


PRIOR = {"district": "WEST GARO HILLS", "block": "DALU", "year_key": 2022}


def test_a_new_district_does_not_inherit_the_old_block(monkeypatch):
    _stub(monkeypatch, {"district": "Ri Bhoi"})
    out = asyncio.run(p.resolve_entities("how many houses in Ri Bhoi under PMAY-G", ["PMAY-G"],
                                         prior_resolved=PRIOR))
    assert out["resolved"]["district"] == "RI BHOI"
    assert "block" not in out["resolved"]
    assert out["resolved"]["year_key"] == 2022


def test_no_place_named_inherits_district_block_and_year(monkeypatch):
    _stub(monkeypatch, {})
    out = asyncio.run(p.resolve_entities("how many houses under PMAY-G", ["PMAY-G"], prior_resolved=PRIOR))
    assert out["resolved"]["district"] == "WEST GARO HILLS"
    assert out["resolved"]["block"] == "DALU"
    assert out["resolved"]["year_key"] == 2022
    # the closing scope sentence reads display: it must not call this "statewide" (live 2026-10-21)
    assert out["display"]["district"] == "West Garo Hills" and out["display"]["year"] == "FY 2022-23"
    text = p._finish_answer("69838 households were recorded for MGNREGA.", [{"beneficiary_households": 69838}],
                            ["MGNREGA"], {"district": "West Garo Hills", "year": "FY 2022-23"})
    assert "statewide" not in text and "West Garo Hills" in text


# ── the year callback reads time forwards ─────────────────────────────────────
def test_callback_to_a_later_year_reads_forwards():
    # PMAY-G WGH FY 2017-18 3,597 asked AFTER FY 2022-23 572 (live 2026-10-21)
    head = {"value": 3597, "year": 2017, "col": "houses"}
    earlier = {"value": 572, "year": 2022, "col": "houses"}
    s = p._callback_sentence(head, earlier)
    assert s.startswith("By FY 2022-23 it was 572") and "lower" in s and "up from" not in s


def test_callback_to_an_earlier_year_is_unchanged():
    s = p._callback_sentence({"value": 3059000, "year": 2023, "col": "person_days"},
                             {"value": 3408697, "year": 2022, "col": "person_days"})
    assert s.startswith("That's down from 3,408,697 in FY 2022-23")


# ── the shared answer cache never carries one chat's scope into another ───────
def test_a_question_that_inherits_the_chat_scope_is_not_cacheable():
    from app.routers.query import is_cacheable
    from app.session_store import Session

    s = Session(session_id="t", user_id="u", created=0.0, last_seen=0.0)
    s.state = ConversationState(scheme="MGNREGA", district="WEST GARO HILLS", year=2022)
    assert not is_cacheable("how many houses", s)
    # fully specified words mean the same in every chat
    assert is_cacheable("how many households for PMAY-G in Ri Bhoi in FY 2019-20", s) is True


def test_a_question_naming_no_scheme_in_a_chat_with_one_is_not_cacheable():
    # KI-337 (2026-10-21): inside a chat on MGNREGA, words that name no scheme take
    # the chat's scheme, so their answer must not be shared with another chat.
    from app.routers.query import is_cacheable
    from app.session_store import Session

    q = "how many households in South Garo Hills in FY 2023-24"
    s = Session(session_id="t", user_id="u", created=0.0, last_seen=0.0)
    s.state = ConversationState(scheme="MGNREGA", year=2023)
    assert not is_cacheable(q, s)
    # a new chat holds no scheme: the same words mean the same everywhere
    fresh = Session(session_id="t2", user_id="u", created=0.0, last_seen=0.0)
    assert is_cacheable(q, fresh) is True


def test_inherited_scope_or_an_answer_default_marks_the_answer_context_dependent():
    r = {}
    p._mark_context_dependent(r, None, raw_question="q", followup=False, plan=None, scope_resumed=False,
                              inherited=True)
    assert r.get("context_dependent") is True
    r = {}
    p._mark_context_dependent(r, None, raw_question="q", followup=False, plan=None, scope_resumed=False)
    assert "context_dependent" not in r


def test_answer_defaults_are_flagged_on_the_entity_result():
    d = _turn("how many households for MGNREGA", ["MGNREGA"], chat_has_scope=True, prior_resolved={"year_key": 2022})
    assert _run(d) is None
    assert d["entity_result"].get("answer_defaults") is True


def test_show_me_for_a_place_is_a_followup():
    # Live 2026-10-21 (harness F3): "show me for south garo hills district" after an
    # MGNREGA households answer went to SQL with no measure and ended in the KB fallback.
    assert p.looks_like_followup("show me for south garo hills district")
    assert p.looks_like_followup("give me for Ri Bhoi")
    assert p.looks_like_followup("get me the same for PMAY-G")
    # a request that names its own measure stands on its own
    assert not p.looks_like_followup("show me the expenditure for East Khasi Hills in 2023-24")
    assert not p.looks_like_followup("give me MGNREGA person-days for Ri Bhoi")
    assert not p.looks_like_followup("show me the districts, I'll choose one")
