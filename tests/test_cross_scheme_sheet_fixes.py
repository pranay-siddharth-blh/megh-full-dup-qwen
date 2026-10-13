"""
Cross Scheme Test Cases sheet (reference_documents/Cross Scheme Test Cases.xlsx,
CROSS-1..CROSS-20) and the generated cross-scheme permutations, 2026-10-13.

Before the fixes 18 of the 20 sheet questions paused (a nine-year "which FY?" list
merged across schemes, "which area?", "which scheme?") and the two that answered
were wrong ("(no label)" rows; a "total across all schemes" adding MGNREGA
expenditure to PMAY-G releases). Cross-scheme comparisons are now answered by
app/cross_scheme.py, deterministically. Every test calls the real function.
"""
from app import cross_scheme as cs
from app import pipeline as p
from app import pipeline_graph as pg


def _named(q):
    return [s for s, pat in p._SCHEME_NAME_PATTERN.items() if pat.search(q)]


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


# ── the measure plan ─────────────────────────────────────────────────────────

def test_performance_based_on_counts_is_counts_only():
    pl = cs.plan("Compare the performance of Focus+ and CM-ELEVATE across districts based on "
                 "beneficiary/application counts.", ["Focus Plus", "CM Elevate Legacy"], {})
    assert (pl.count, pl.money, pl.group) == (True, False, "district")


def test_coverage_and_financial_performance():
    pl = cs.plan("Give me an overall performance comparison of MGNREGA, PMAY-G, Focus+, FOCUS, and CM-ELEVATE "
                 "based on coverage and financial performance.", cs.ORDER[:5], {})
    assert pl.coverage and pl.count and pl.money and pl.group is None


def test_widest_coverage_across_districts_is_places_reached():
    pl = cs.plan("Which scheme has the widest coverage across districts of Meghalaya?", cs.ORDER, {})
    assert pl.coverage and pl.group is None and not pl.leader_per_group


def test_leader_per_district():
    pl = cs.plan("For each district, identify which scheme has the highest beneficiary/application count.",
                 cs.ORDER, {})
    assert pl.group == "district" and pl.leader_per_group and pl.count and not pl.money


def test_scheme_name_applicants_is_not_a_count_request():
    pl = cs.plan("Give me a summary comparing mgnrega vs cm elevate applicants", ["MGNREGA", "CM Elevate"], {})
    assert pl.count and pl.money


def test_bigger_is_a_ranking():
    pl = cs.plan("Which is bigger, Focus+ or FOCUS, by amount disbursed?", ["Focus Plus", "Focus Legacy"], {})
    assert pl.rank and pl.money and not pl.count


def test_a_named_block_is_not_grouped_by_district():
    pl = cs.plan("Compare MGNREGA and PMAY-G across districts in Mylliem block", ["MGNREGA", "PMAY-G"],
                 {"block": "MYLLIEM"})
    assert pl.group is None


# ── years, blocks, money format ─────────────────────────────────────────────

def test_fy_without_a_space_is_read():
    assert cs.years_in_text("beneficiaries in FY2022-23") == [2022]
    assert cs.years_in_text("in 2017-2018") == [2017]
    assert cs.years_in_text("in 2022-25") == []


def test_tura_is_one_block_spelled_two_ways():
    assert cs._canon_block("TURA MUNICIPAL BOARD-MUNICIPAL BOARD") == cs._canon_block("Tura Municipal Board")
    assert cs._canon_block("BAGHMARA-MUNICIPAL BOARD") != cs._canon_block("BAGHMARA")


def test_money_unit_follows_the_size():
    assert cs._cr(3_628_67_00_000) == "₹3,628.67 crore"
    assert cs._cr(89_62_000) == "₹89.62 lakh"
    assert cs._cr(5_000) == "₹5,000"


def test_years_note_lists_a_gap():
    assert cs._years_text({"Focus Plus": ["2022-23", "2025-26"]}, "Focus Plus") == "FY 2022-23 and 2025-26"
    assert cs._years_text({"MGNREGA": ["2022-23", "2023-24", "2024-25"]}, "MGNREGA") == "FY 2022-23 to FY 2024-25"


# ── the pipeline wiring ─────────────────────────────────────────────────────

def test_graph_carries_the_cross_plan_and_the_users_own_words():
    assert "cross" in pg._DATA_KEYS and "pre_rephrase_question" in pg._DATA_KEYS
    assert "pre_rephrase_question" in pg._DATA_READ_ONLY
    d = p._new_data_turn("q")
    assert d["cross"] is None and d["pre_rephrase_question"] is None


def test_literal_sql_inlines_parameters():
    assert p._literal_sql("SELECT 1 WHERE a = ANY($1::text[]) AND b = $2", [["X", "Y'Z"], 3]) == \
        "SELECT 1 WHERE a = ANY(ARRAY['X', 'Y''Z']::text[]) AND b = 3"


def test_compare_all_six_schemes_is_not_asked_back():
    out = p._scheme_comparison_answer("Compare all six schemes")
    assert out is not None
    for s in cs.ORDER:
        assert f"**{s}**" in out["answer"]


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
