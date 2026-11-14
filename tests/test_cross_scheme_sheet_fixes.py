"""
Cross Scheme Test Cases sheet (reference_documents/Cross Scheme Test Cases.xlsx,
CROSS-1..CROSS-20) and the generated cross-scheme permutations, 2026-10-13.

Before the fixes 18 of the 20 sheet questions paused (a nine-year "which FY?" list
merged across schemes, "which area?", "which scheme?") and the two that answered
were wrong ("(no label)" rows; a "total across all schemes" adding MGNREGA
expenditure to PMAY-G releases). Cross-scheme comparisons were then answered by a
fixed table in app/cross_scheme.py (D-044); since D-062 (2026-10-22) they are
answered by one model-written query per scheme and the composer
(tests/test_cross_scheme_llm_2026_10_22.py). What stays tested here: detection,
the place handling and the twin-village chips. Every test calls the real function.
"""
import pytest

from app import cross_scheme as cs
from app import pipeline as p
from app import pipeline_graph as pg


def _named(q):
    return [s for s, pat in p._SCHEME_NAME_MATCHER.items() if pat.search(q)]


def _detect(q):
    return cs.detect(q, _named(q))


# ── detection ────────────────────────────────────────────────────────────────

def test_sheet_question_with_what_is_is_a_comparison():
    # CROSS-1 was dropped by the knowledge filter on "What is"
    assert _detect("What is the beneficiary count across MGNREGA, PMAY-G, Focus+, and FOCUS?") == \
        ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy"]


def test_bare_focus_beside_focus_plus_is_focus_legacy():
    assert _detect("Compare the number of beneficiaries in Focus+ and FOCUS.") == ["Focus Plus", "Focus Legacy"]


def test_bare_focus_alone_is_not_guessed():
    assert _detect("Compare MGNREGA and FOCUS beneficiaries") == ["MGNREGA"] or \
        _detect("Compare MGNREGA and FOCUS beneficiaries") is None


def test_which_scheme_without_a_name_means_all_six():
    assert _detect("Which scheme has the highest beneficiary or application count in each district?") == cs.ORDER
    assert _detect("Which scheme provided the highest total financial assistance across Meghalaya?") == cs.ORDER


def test_which_scheme_inside_cm_elevate_is_its_programmes():
    assert _detect("Which scheme under CM Elevate has the most applications?") is None


def test_other_measures_keep_the_normal_path():
    assert _detect("Compare MGNREGA person days and PMAY-G houses completed") is None
    assert _detect("What is MGNREGA and PMAY-G?") is None
    assert _detect("How does MGNREGA and PMAY-G work?") is None


def test_rephrased_how_does_compare_is_still_a_comparison():
    # the rephrase node turned "Compare the coverage of …" into this on some runs
    assert _detect("How does the coverage of MGNREGA, PMAY-G, and CM Elevate Legacy compare in Mylliem block?") == \
        ["MGNREGA", "PMAY-G", "CM Elevate Legacy"]


def test_listing_the_schemes_is_not_a_comparison():
    # General TC-001 / TC-016 of the finished sheets
    assert _detect("What schemes are available?") is None
    assert _detect("What schemes can I get in Meghalaya?") is None


def test_compare_the_schemes_is_all_schemes():
    assert _detect("Compare the schemes district-wise") == cs.ORDER


# ── years ────────────────────────────────────────────────────────────────────

def test_fy_without_a_space_is_read():
    assert cs.years_in_text("beneficiaries in FY2022-23") == [2022]
    assert cs.years_in_text("in 2017-2018") == [2017]
    assert cs.years_in_text("in 2022-25") == []


# ── the pipeline wiring ─────────────────────────────────────────────────────

def test_graph_carries_the_cross_plan_and_the_users_own_words():
    assert "cross" in pg._DATA_KEYS and "pre_rephrase_question" in pg._DATA_KEYS
    assert "pre_rephrase_question" in pg._DATA_READ_ONLY
    d = p._new_data_turn("q")
    assert d["cross"] is None and d["pre_rephrase_question"] is None


@pytest.mark.parametrize("q", ["Compare all six schemes", "Compare all eight schemes", "Compare all 8 schemes",
                               "compare all the schemes", "compare every scheme"])
def test_compare_all_schemes_is_not_asked_back(q):
    """Never the pick-a-pair pause; since 2026-11-14 (W4-XS-06) the figures of every scheme: the comparison stage
    steps aside (None), the cross-scheme detector claims it over every scheme and the intent cues say DATA."""
    assert p._scheme_comparison_answer(q) is None
    assert cs.detect(q, []) == list(cs.ORDER)
    assert p._c13_intent_by_cues(q) == "DATA"


def test_a_description_of_every_scheme_keeps_the_side_by_side():
    for q in ("difference between all the schemes", "Compare all eight schemes' eligibility"):
        out = p._scheme_comparison_answer(q)
        assert out is not None, q
        for s in cs.ORDER:
            assert f"**{s}**" in out["answer"], (q, s)


def test_a_district_wise_comparison_goes_to_data():
    assert p._SCHEME_COMPARISON_METRIC_GUARD.search("Compare the schemes district-wise")
    assert not p._SCHEME_COMPARISON_METRIC_GUARD.search("how do the schemes differ otherwise")


# ── village run fixes ────────────────────────────────────────────────────────

def test_a_village_named_wage_is_not_a_wages_question():
    q = "Show the beneficiary count for MGNREGA and PMAY-G in BIJASIK WAGE APAL village."
    assert _detect(q) is None                                   # the raw text trips "wage"
    assert cs.detect(q, _named(q), measure_text="Show the beneficiary count for MGNREGA and PMAY-G "
                     "in the village village.") == ["MGNREGA", "PMAY-G"]


def test_twin_villages_with_data_are_both_offered(monkeypatch):
    import asyncio

    async def rows(sql, params=None):
        return [{"village_code": 272895, "lgd_village_name": "BOLDAMGRE", "lgd_block": "SELSELLA",
                 "lgd_district": "WEST GARO HILLS"},
                {"village_code": 272933, "lgd_village_name": "Boldamgre", "lgd_block": "SELSELLA",
                 "lgd_district": "WEST GARO HILLS"}]

    async def active(schemes, codes):
        return {272895, 272933}

    monkeypatch.setattr(p, "fetch_rows", rows)
    monkeypatch.setattr(cs, "villages_with_records", active)
    d = {"question": "Compare MGNREGA and Focus Plus in boldamgre village",
         "cross": {"schemes": ["MGNREGA", "Focus Plus"], "text": "Compare MGNREGA and Focus Plus in boldamgre village"}}
    try:
        asyncio.run(p._cross_twin_village_pause(d, ["MGNREGA", "Focus Plus"], {"village_code": 272895}))
        raised = None
    except p.ClarificationNeeded as e:
        raised = e
    assert raised is not None and raised.rule == "entity-ambiguous"
    labels = [o["label"] for o in raised.options]
    assert any("LGD 272895" in x for x in labels) and any("LGD 272933" in x for x in labels)
    assert all("(LGD " in o["question"] for o in raised.options)


def test_a_chip_already_naming_the_lgd_code_is_not_asked_again(monkeypatch):
    import asyncio

    async def boom(*a, **k):
        raise AssertionError("no lookup expected")
    monkeypatch.setattr(p, "fetch_rows", boom)
    d = {"question": "Compare MGNREGA and Focus Plus in Boldamgre (LGD 272933), SELSELLA block, WEST GARO HILLS",
         "cross": {"schemes": ["MGNREGA", "Focus Plus"], "text": "x"}}
    asyncio.run(p._cross_twin_village_pause(d, ["MGNREGA", "Focus Plus"], {"village_code": 272933}))


def test_a_twin_chip_is_split_by_lgd_code(monkeypatch):
    import asyncio

    async def rows(sql, params=None):
        if params and str(params[1]).upper() == "SELSELLA":
            return [{"village_code": 272895, "lgd_village_name": "BOLDAMGRE", "lgd_block": "SELSELLA",
                     "lgd_district": "WEST GARO HILLS"},
                    {"village_code": 272933, "lgd_village_name": "Boldamgre", "lgd_block": "SELSELLA",
                     "lgd_district": "WEST GARO HILLS"}]
        return [{"village_code": 273125, "lgd_village_name": "Boldamgre", "lgd_block": "DADENGGIRI",
                 "lgd_district": "WEST GARO HILLS"}]

    async def active(schemes, codes):
        return set(codes)

    monkeypatch.setattr(p, "fetch_rows", rows)
    monkeypatch.setattr(cs, "villages_with_records", active)
    e = p.ClarificationNeeded("which village?", rule="entity-ambiguous", options=[
        {"label": "BOLDAMGRE — SELSELLA block, WEST GARO HILLS",
         "question": "Compare MGNREGA and Focus Plus in BOLDAMGRE village, SELSELLA block, WEST GARO HILLS"},
        {"label": "Boldamgre — DADENGGIRI block, WEST GARO HILLS",
         "question": "Compare MGNREGA and Focus Plus in Boldamgre village, DADENGGIRI block, WEST GARO HILLS"}])
    out = asyncio.run(p._cross_split_twin_chips(e, ["MGNREGA", "Focus Plus"]))
    labels = [o["label"] for o in out.options]
    assert labels == ["BOLDAMGRE (LGD 272895) — SELSELLA block, WEST GARO HILLS",
                      "BOLDAMGRE (LGD 272933) — SELSELLA block, WEST GARO HILLS",
                      "Boldamgre — DADENGGIRI block, WEST GARO HILLS"]
    assert "BOLDAMGRE (LGD 272933) village, SELSELLA block" in out.options[1]["question"]
