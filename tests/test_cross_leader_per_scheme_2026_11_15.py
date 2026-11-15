"""Question bank A10 (2026-11-15): "Which district leads in each scheme?" compared the schemes' state totals. "leads"
is a rank word now, and a HIGH district ranking asked in the singular, with no number, per scheme ("each / every /
per") is the one leader per scheme, one plain line each. Everything else is unchanged ("sabse kam district", "top 1
and bottom 1 districts", "second highest district", "top 1 districts … per beneficiary money")."""
import pytest

from app import cross_figures as cf


@pytest.mark.parametrize("q", ["Which district leads in each scheme?", "Which district is top in each scheme?",
                               "Top district for every scheme", "Which district is leading in every scheme?"])
def test_singular_district_ranking_per_scheme_is_the_leader(q):
    ask = cf.rank_ask(q)
    assert ask is not None and ask.level == "district"
    assert cf._one_place_asked(q, ask.level)


@pytest.mark.parametrize("q", ["Which districts lead in each scheme?", "Top 3 districts in each scheme",
                               "Rank the districts in every scheme", "MGNREGA and PMAY-G sabse kam district",
                               "top 1 and bottom 1 districts in MGNREGA and PMAY-G",
                               "Which district has the most MGNREGA and PMAY-G?"])
def test_other_rankings_are_not_the_one_leader_reading(q):
    ask = cf.rank_ask(q)
    assert ask is None or not cf._one_place_asked(q, ask.level)
