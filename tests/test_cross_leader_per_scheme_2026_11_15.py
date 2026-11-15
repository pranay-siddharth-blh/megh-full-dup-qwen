"""Question bank A10 (2026-11-15): "Which district leads in each scheme?" compared the schemes' state totals. "leads"
is a rank word now, and a ranking asked in the SINGULAR with no number ("which district", "top district") is the one
leader per scheme; plural / numbered rankings are unchanged."""
import pytest

from app import cross_figures as cf


@pytest.mark.parametrize("q", ["Which district leads in each scheme?", "Which district is top in each scheme?",
                               "Top district for every scheme", "Which district is leading in every scheme?"])
def test_singular_district_ranking_is_the_leader(q):
    ask = cf.rank_ask(q)
    assert ask is not None and ask.level == "district"
    assert cf._one_place_asked(q, ask.level)


@pytest.mark.parametrize("q", ["Which districts lead in each scheme?", "Top 3 districts in each scheme",
                               "Rank the districts in every scheme"])
def test_plural_or_numbered_rankings_are_not_one_place(q):
    ask = cf.rank_ask(q)
    assert ask is None or not cf._one_place_asked(q, ask.level)


def test_which_scheme_leads_in_each_district_is_not_a_district_ranking():
    ask = cf.rank_ask("Which scheme leads in each district?")
    assert ask is None or ask.level != "district" or not cf._one_place_asked("Which scheme leads in each district?",
                                                                           ask.level)
