"""KI-332 (live 2026-10-19 15:08): "now give me for cm elevate" right after "Compare
PMAY-G and MGNREGA beneficiaries in a graph ..." became "Compare CM Elevate and CM
Elevate beneficiaries ..." — the swap replaced EACH compared scheme — and the dataset
chip made it "Compare CM Elevate applications and CM Elevate applications
beneficiaries". The compared schemes are one list: a swap asks for the same
comparison card for the new scheme alone (in the comparison's scope), an "and X" /
"X too" adds X to the list."""
import pytest

from app import pipeline as p

PREV = "Compare PMAY-G and MGNREGA beneficiaries in a graph for Meghalaya (statewide), all financial years."
TAIL = " beneficiaries in a graph for Meghalaya (statewide), all financial years."


@pytest.mark.parametrize("followup, scheme", [
    ("now give me for cm elevate", "CM Elevate"),
    ("what about focus plus", "Focus Plus"),
    ("give me for cm elevate legacy", "CM Elevate Legacy"),
    ("give me for mgnrega", "MGNREGA"),              # one of the compared: narrows to it
])
def test_a_swap_replaces_the_whole_compared_list(followup, scheme):
    assert p._scheme_swap_rewrite(PREV, followup) == f"Same comparison for {scheme}:{TAIL}"


@pytest.mark.parametrize("followup, scheme", [
    ("and cm elevate legacy too", "CM Elevate Legacy"),
    ("focus plus as well", "Focus Plus"),
    ("and cm elevate?", "CM Elevate"),
])
def test_an_and_cue_adds_the_scheme_to_the_comparison(followup, scheme):
    assert p._scheme_swap_rewrite(PREV, followup) == f"Compare PMAY-G, MGNREGA and {scheme}{TAIL}"


def test_the_cm_elevate_chips_name_the_scheme_once():
    sw = p._scheme_swap_rewrite(PREV, "now give me for cm elevate")
    pause = p._cm_elevate_dataset_pause(p._pin_cm_elevate_dataset(sw, None))
    assert pause is not None
    for opt in pause.options:
        assert opt["question"].count("CM Elevate") == 1, opt["question"]
        assert opt["question"].startswith("Same comparison for CM Elevate")


@pytest.mark.parametrize("followup, scheme", [
    ("now give me for cm elevate", "CM Elevate"), ("what about focus plus", "Focus Plus")])
def test_the_rewrite_is_answered_by_the_comparison_card_for_one_scheme(followup, scheme):
    from app import cross_scheme
    q = p._scheme_swap_rewrite(PREV, followup)
    named = [s for s, pat in p._SCHEME_NAME_MATCHER.items() if pat.search(q)]
    assert cross_scheme.detect(q, named) == [scheme]


def test_a_plain_one_scheme_question_is_not_a_comparison():
    from app import cross_scheme
    assert cross_scheme.detect("How many Focus Plus beneficiaries in FY 2025-26?", ["Focus Plus"]) is None


def test_a_non_compare_list_drops_both():
    prev = "Which villages have both MGNREGA and PMAY-G activity in Meghalaya?"
    assert p._scheme_swap_rewrite(prev, "now for focus plus") == \
        "Which villages have Focus Plus activity in Meghalaya?"


def test_single_scheme_swaps_are_unchanged():
    assert p._scheme_swap_rewrite("Total MGNREGA person-days in 2023-24", "give me for pmay") == \
        "Total PMAY-G person-days in 2023-24"


def test_names_not_side_by_side_are_not_one_list():
    # two schemes in different roles: the old per-name swap still applies
    prev = "MGNREGA households in villages that also have PMAY-G houses"
    assert p._comparison_swap(prev, "for focus plus", "Focus Plus", "Focus Plus") is None


def test_a_tapped_dataset_chip_is_a_standalone_question():
    # live 2026-10-19 15:44: the short Legacy chip was rewritten back into "Compare
    # CM Elevate Legacy and MGNREGA ..." as a "same"-cued substitution
    chip = "Same comparison for CM Elevate Legacy: beneficiaries and amount"
    prev = type("T", (), {"route": "data", "schemes": ["MGNREGA", "PMAY-G"]})()
    assert not p.looks_like_followup(chip)
    assert not p.is_scheme_substitution(chip, prev)
