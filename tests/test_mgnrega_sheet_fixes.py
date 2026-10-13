"""MGNREGA sheet test run 2026-10-09 (Test Case Results - 30th Sep 26.xlsx,
DATA-001..030): regression tests for the failures, against the real functions."""
import pytest

from app import pipeline as p


# ── "expenditure" is MGNREGA's word (DATA-001/002/003/022/024) ──────────────
@pytest.mark.parametrize("q", [
    "What was the total expenditure in ADUGRE during 2023-24?",
    "What was the total expenditure in Ri Bhoi during 2023-24?",
    "Which district had the highest expenditure during 2024-25?",
    "Give me the expenditure breakdown for Myriem during 2023-24.",
])
def test_expenditure_pins_mgnrega(q):
    assert p._infer_scheme_from_terms(q) == ["MGNREGA"]


@pytest.mark.parametrize("q", [
    "which scheme has the highest expenditure?",
    "compare expenditure across all schemes",
    "total expenditure on houses in Ri Bhoi",          # PMAY-G vocabulary too: ambiguous
])
def test_expenditure_about_schemes_still_asks(q):
    assert p._infer_scheme_from_terms(q) is None


# ── guardrail model scope verdicts never refuse a figure question ──────────
@pytest.mark.parametrize("q", [
    "Give me the expenditure breakdown for Myriem during 2023-24.",
    "What was the total expenditure in MAWJYRSIM during 2022-23?",
    "How many person-days were generated in DILBOT?",
])
def test_data_questions_overrule_a_scope_verdict(q):
    assert p._overrules_scope_verdict(q)


@pytest.mark.parametrize("q", [
    "craft some lines for my page praising PMAY-G houses",
    "Who won the last IPL final?",
    "book a train ticket for me to Shillong",
    "What should I invest my money in?",
])
def test_off_topic_still_refusable(q):
    assert not p._overrules_scope_verdict(q)


# ── the rephraser keeps a multi-word village whole (DATA-012/023) ──────────
def test_rephrase_rejects_a_split_village_name():
    o = "How much was spent on semi-skilled wages in MAWNGAP MAWSMAI?"
    assert p._unknown_word_runs(o) == ["mawngap mawsmai"]
    assert p._rephrase_violation(o, "How much money was spent on semi-skilled wages under MAWNGAP in "
                                    "MAWSMAI?") == "name:mawngap mawsmai"


# ── AVG / SUM mixes become the ratio of the sums (DATA-021) ────────────────
@pytest.mark.parametrize("sql", [
    "SELECT ROUND(AVG(person_days)::numeric / NULLIF(SUM(households_employed), 0), 2) AS x FROM v",
    "SELECT AVG(person_days) / AVG(households_employed) FROM v",
    "SELECT AVG(person_days / NULLIF(households_employed, 0)) FROM v",
])
def test_mixed_average_ratio_rewritten(sql):
    out = p._mgnrega_avg_of_ratio(["MGNREGA"], sql)
    assert "SUM(person_days)::numeric / NULLIF(SUM(households_employed), 0)" in out
    assert "AVG(" not in out


def test_sum_ratio_and_plain_average_untouched():
    for sql in ("SELECT SUM(person_days)::numeric / NULLIF(SUM(households_employed), 0) FROM v",
                "SELECT AVG(person_days) FROM v"):
        assert p._mgnrega_avg_of_ratio(["MGNREGA"], sql) == sql


# ── "<X> constituency" typed by the user: no whole-or-part pause (DATA-004/014)
def test_user_named_constituency_detected():
    assert p._USER_NAMED_CONSTITUENCY.search("How many persons received employment in Amlarem constituency?")
    assert p._AC_COLLISION_CHIP.search("persons employed in Sohra, the assembly constituency, not another area type")


# ── deterministic answers: every figure stated (DATA-022 / DATA-028..030) ──
def test_combined_facts_answer_states_both_figures():
    a = p._mgnrega_combined_facts_answer({"total_expenditure_lakh": 2453.65, "person_days": 625270},
                                         {"district": "West Khasi Hills", "year": "FY 2025-26"})
    assert "2,453.65 lakh" in a and "625,270 person-days" in a and "FY 2025-26" in a


def test_breakdown_query_and_answer():
    q = "Give me the expenditure breakdown for Myriem during 2023-24."
    sql, params, shown = p._mgnrega_breakdown_query(q, ["MGNREGA"], {"village_code": 1, "year_key": 2023})
    assert p._MG_BREAKDOWN_SQL_RE.search(sql) and params == [1, 2023]
    row = {"unskilled_wages_lakh": 17.52, "semi_skilled_wages_lakh": 4.58, "materials_lakh": 8.77,
           "tax_lakh": 0, "administrative_lakh": 0, "total_lakh": 30.87}
    a = p._mgnrega_breakdown_answer(row, {"village": "Myriem", "year": "FY 2023-24"})
    for s in ("30.87 lakh", "17.52 lakh", "4.58 lakh", "8.77 lakh"):
        assert s in a
    assert p._mgnrega_breakdown_query("expenditure breakdown by district for 2024-25", ["MGNREGA"],
                                      {"year_key": 2024}) is None


# ── a list answer must state the list's true size (DATA-014) ───────────────
@pytest.mark.parametrize("answer,wrong", [
    ("Ten villages in the Dadenggre constituency received employment", True),
    ("Here are the 40 results:", True),
    ("135 villages received employment in Dadenggre.", False),
    ("The top 5 villages by person-days are A, B, C, D and E.", False),
])
def test_list_count_guard(answer, wrong):
    assert p._states_wrong_list_count(answer, 135) is wrong


# ── "which villages" lists are whole; spend words survive the rephraser ───
def test_village_list_limit_dropped_unless_top_n():
    q = "Which villages in Ampathi constituency received employment during FY 2023-24?"
    assert p._mgnrega_village_list_no_limit(q, ["MGNREGA"], "SELECT a FROM v ORDER BY b DESC LIMIT 100") == \
        "SELECT a FROM v ORDER BY b DESC"
    q5 = "Which top 5 villages had the most person-days?"
    assert p._mgnrega_village_list_no_limit(q5, ["MGNREGA"], "SELECT a FROM v LIMIT 5") == "SELECT a FROM v LIMIT 5"


def test_rephrase_must_keep_the_spend_word():
    assert p._rephrase_violation(
        "Compare expenditure and person-days in Gambegre block during 22-23.",
        "How much money and how many person-days were generated in Gambegre block during FY 2022-23?") == "measure"


def test_rephrase_must_not_widen_to_all_schemes():
    assert p._rephrase_violation(
        "Compare total expenditure and employment generated in East Khasi Hills during 25-26.",
        "What is the total expenditure and employment generated under all schemes in East Khasi Hills "
        "during FY 2025-26?") == "scheme"


# ── KI-235: the single-figure fallback names the measure and states the unit once
@pytest.mark.parametrize("row,want", [
    ({"financial_year_short": "2023-24", "total_expenditure_lakh": 8.71}, "2023-24: total expenditure 8.71 lakh."),
    ({"women_pct": 41.2}, "women 41.20%."),
    ({"households_employed": 59114}, "59,114 households employed."),
])
def test_single_figure_fallback_wording(row, want):
    out = p._deterministic_answer([row])
    assert out == want
    assert p._mgnrega_money_units(out, "SELECT SUM(total_exp) AS total_expenditure_lakh FROM v", [row]) == want


# ── all-villages run (6,491 villages) fixes ─────────────────────────────────
def test_exact_village_name_has_no_fuzzy_block_or_ac_reading():
    from app import entity_resolver as er
    # with the fuzzy stage, a village spelled exactly would still collide with a look-alike
    assert "block" not in er.collides_across_dimensions("AMOKGRE", "MGNREGA", village_hit=True,
                                                       exact_village=True)


@pytest.mark.parametrize("orig,rewrite,bad", [
    ("How much was spent and how many person-days were generated in rimrangpara a during 2025-26?",
     "How much money was spent and how many person-days were generated in Rimrangpara during FY 2025-26?", True),
    ("What was the total expenditure in RAMJONGGRE ( R ) during 2022-23?",
     "What was the total expenditure in RAMJONGGRE (R) during FY 2022-23?", True),
    ("How many households received employment in nokatgre i?",
     "How many households received employment in Nokatgre I?", False),
])
def test_rephrase_keeps_name_suffixes_exactly(orig, rewrite, bad):
    assert bool(p._rephrase_violation(orig, rewrite)) is bad


def test_during_is_not_a_name():
    assert p._is_known_word("during")


def test_wage_material_deterministic():
    sql, params, _ = p._mgnrega_wage_material_query("Was more spent on wages or materials in JAKREM?",
                                                     ["MGNREGA"], {"village_code": 1, "year_key": 2024})
    assert p._MG_WAGE_MATERIAL_SQL_RE.search(sql) and params == [1, 2024]
    a = p._mgnrega_wage_material_answer({"wage_exp_lakh": 219.48, "material_exp_lakh": 113.89, "source_rows": 4},
                                        {"village": "Jakrem", "year": "FY 2024-25"})
    assert "More was spent on wages" in a and "219.48 lakh" in a and "113.89 lakh" in a
    z = p._mgnrega_wage_material_answer({"wage_exp_lakh": None, "material_exp_lakh": None, "source_rows": 0},
                                        {"village": "Upper Wadagokgre", "year": "FY 2024-25"})
    assert "both are 0 lakh" in z


def test_chip_question_tolerates_bracket_spacing():
    c = {"name": "DATHBANGA ( KOCH )", "block": "ZIKZAK", "district": "SOUTH WEST GARO HILLS", "village_code": 273962}
    assert p._village_chip_question_text("How many job cards were issued in DATHBANGA (KOCH)?", "DATHBANGA", c,
                                         ["MGNREGA"]) == \
        "How many job cards were issued in DATHBANGA ( KOCH ), ZIKZAK block, SOUTH WEST GARO HILLS"


def test_place_word_inside_village_name_is_kept(monkeypatch):
    # "MYNRI UMSNING" came back "MYNRI in Umsning": UMSNING is also a block name
    monkeypatch.setattr(p, "_place_words", lambda: frozenset({"umsning", "ri", "bhoi"}))
    o = "What was the total expenditure in MYNRI UMSNING during 2022-23?"
    assert p._unknown_word_runs(o) == ["mynri umsning"]
    assert p._rephrase_violation(o, "What was the total expenditure under MYNRI in Umsning during FY 2022-23?") \
        == "name:mynri umsning"
    assert p._unknown_word_runs("How many person-days in Ri Bhoi in 2023-24?") == []


def test_village_name_masked_for_guardrails(monkeypatch):
    import asyncio

    async def scan(text, scheme):
        return ("CHOTTA KILLING", [{"village_code": 277475}]) if "killing" in text.lower() else None
    monkeypatch.setattr(p, "_scan_village_in_question", scan)
    assert asyncio.run(p._mask_village_names("Give me the expenditure breakdown for CHOTTA KILLING during 2023-24.")) \
        == "Give me the expenditure breakdown for the village during 2023-24."


def test_exact_village_check_ignores_trailing_punctuation():
    keys = p._village_name_keys({"BETASING BLOCK HQ.": [], "JAKREM": []})
    assert p._strip_end_punct("BETASING BLOCK HQ") in keys
    assert p._strip_end_punct("Jakrem?") in keys
    assert p._strip_end_punct("BETASING") not in keys


def test_village_row_list_is_distinct():
    q = "Which villages in Mawryngkneng constituency received employment during 2025-26?"
    out = p._mgnrega_village_list_no_limit(q, ["MGNREGA"], "SELECT lgd_village_name, village_code FROM v WHERE x > 0")
    assert out.startswith("SELECT DISTINCT")
    grouped = "SELECT a, SUM(b) FROM v GROUP BY a"
    assert p._mgnrega_village_list_no_limit(q, ["MGNREGA"], grouped) == grouped


def test_distinct_only_when_order_by_columns_are_selected():
    q = "Which villages in Ampathi constituency received employment?"
    assert p._mgnrega_village_list_no_limit(q, ["MGNREGA"], "SELECT a, b FROM v ORDER BY b DESC LIMIT 100") == \
        "SELECT DISTINCT a, b FROM v ORDER BY b DESC"
    assert p._mgnrega_village_list_no_limit(q, ["MGNREGA"], "SELECT a FROM v ORDER BY b DESC") == \
        "SELECT a FROM v ORDER BY b DESC"
