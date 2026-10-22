"""A follow-up that RANKS a place level drops the chat's place at that level
(user report 2026-10-22). After "MGNREGA 100 day completion percentage in
Demdema block, West Garo Hills", "Which block has highest number of households?"
kept block DEMDEMA in the resolver's prior_resolved and answered Demdema's single
row (0) instead of ranking the blocks. D-056: a span below the district keeps the
district, so the ranking is over West Garo Hills' blocks (DB: TIKRIKILLA 58,306)."""
import pytest

from app import context_policy as cp

_PRIOR = {"district": "WEST GARO HILLS", "block": "DEMDEMA", "year_all": True}


def _kept(question, prior=_PRIOR):
    return cp.apply_merge_plan(dict(prior), cp.plan_state_merge(question))


@pytest.mark.parametrize("question", [
    "Which block has highest number of households?",
    "which block has the most job cards",
    "Which blocks had the lowest expenditure?",
    "top 5 blocks by person days",
    "blocks with the highest women employment",
    "most households in which block?",
    "rank the blocks by households employed",
])
def test_ranking_blocks_drops_the_block_keeps_the_district(question):
    kept = _kept(question)
    assert "block" not in kept
    assert kept.get("district") == "WEST GARO HILLS"
    assert kept.get("year_all") is True


def test_ranking_villages_drops_the_village_keeps_block_and_district():
    prior = {"district": "WEST GARO HILLS", "block": "DEMDEMA", "village_code": 123}
    kept = _kept("Which village has the highest number of households?", prior)
    assert "village_code" not in kept
    assert kept.get("block") == "DEMDEMA" and kept.get("district") == "WEST GARO HILLS"


def test_ranking_districts_drops_the_whole_place():
    kept = _kept("Which district had the highest women employment?")
    assert "district" not in kept and "block" not in kept


@pytest.mark.parametrize("question", [
    "and the job cards?",
    "how many households?",
    "What is the highest number of households here?",
    "and the person days?",
])
def test_non_ranking_questions_keep_the_place(question):
    kept = _kept(question)
    assert kept.get("block") == "DEMDEMA" and kept.get("district") == "WEST GARO HILLS"


def test_new_question_path_already_drops_the_ranked_level():
    # A question read as NEW gets the chat's place from _c14_kept_place_fields
    # (D-056: a span below the district keeps the district only).
    from app import pipeline as p
    assert p._c14_kept_place_fields("Which block has highest number of households?") == ("district",)
    # D-061: the asked level and below are cleared, every parent kept (village -> block, district)
    assert p._c14_kept_place_fields("which village has the most job cards") == ("district", "block")
    assert p._c14_kept_place_fields("which district had the highest expenditure") == ()
    assert p._c14_kept_place_fields("how many households?") == ("district", "block", "village")


def _prev_turn(scheme="MGNREGA"):
    from app.session_store import Turn
    return Turn(question="How many households were employed under MGNREGA in Demdema block, West Garo Hills "
                         "across all financial years?", raw_question="q", route="data", schemes=[scheme],
                resolved_entities={"district": "WEST GARO HILLS", "block": "DEMDEMA", "year_all": True},
                answer="0")


def _state():
    from app.session_store import ConversationState
    s = ConversationState()
    s.scheme, s.district, s.block, s.year_all = "MGNREGA", "WEST GARO HILLS", "DEMDEMA", True
    return s


def _ranking_rewrite(question, state=None):
    from app import pipeline as p
    return p._ranking_followup_question(question, _prev_turn(), cp.plan_state_merge(question, state),
                                        state)


@pytest.mark.parametrize("state", [None, "state"])
def test_ranking_followup_is_the_users_words_plus_the_scope_above_it(state):
    st = _state() if state else None
    q = _ranking_rewrite("Which block has highest number of households?", st)
    assert q == "Which block has highest number of households under MGNREGA in West Garo Hills across all financial years?"
    # the live failure: the model rewrite summed the top three (145,498)
    q = _ranking_rewrite("top 3 blocks by households employed", st)
    assert q.startswith("top 3 blocks by households employed under MGNREGA in West Garo Hills")
    assert "Demdema" not in q


def test_ranking_districts_carries_no_place():
    q = _ranking_rewrite("Which district has the highest number of households?", _state())
    assert q == "Which district has the highest number of households under MGNREGA across all financial years?"


def test_ranking_with_its_own_year_keeps_that_year_only():
    q = _ranking_rewrite("Which block has the most person days in FY 2023-24?", _state())
    assert q is not None and "across all financial years" not in q


@pytest.mark.parametrize("question", [
    "which block has the highest?",            # no measure of its own: the model rewrite reads it
    "how many households?",                    # not a ranking
    "which block has the most of those?",      # points back at the previous measure
])
def test_other_followups_are_left_to_the_model_rewrite(question):
    assert _ranking_rewrite(question, _state()) is None
