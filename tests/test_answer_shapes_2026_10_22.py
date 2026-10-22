"""
Answer shapes (user report 2026-10-22): "if I ask top 10, top 5 or compare, different things,
you need to give different answers". Every data answer read as the same briefing line — the
composer prompt fixed one sentence shape for every question, and the number-check fallback
wrote the same "Under X, … here are the N results:" for every multi-row result.

Now the shape is read from the SQL tree and the rows (app/pipeline/common/c12_answer_shapes.py):
ranking / compare / trend / breakdown / cross_tab / list / profile / single_value. The composer
gets that shape's instructions + example and the derived figures (gaps, % change, shares) the
shape needs; the faithfulness check accepts those figures; the fallback keeps the shape.

No model or DB: the composer is stubbed.
    python -m pytest tests/test_answer_shapes_2026_10_22.py -q
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import pipeline as p  # noqa: E402

TOP5_SQL = ("SELECT block, SUM(persondays) AS person_days FROM curated.v_mgnrega WHERE year_key = 2023 "
            "GROUP BY block ORDER BY person_days DESC LIMIT 5")
TOP5_ROWS = [{"block": "Mylliem", "person_days": 412300}, {"block": "Mawphlang", "person_days": 398150},
             {"block": "Mawkynrew", "person_days": 301020}, {"block": "Pynursla", "person_days": 250000},
             {"block": "Laitkroh", "person_days": 120500}]
CMP_SQL = "SELECT district, SUM(job_cards) AS job_cards FROM curated.v_mgnrega GROUP BY district"
CMP_ROWS = [{"district": "East Khasi Hills", "job_cards": 38200}, {"district": "West Khasi Hills", "job_cards": 25750}]
TREND_SQL = ("SELECT financial_year, SUM(total_exp) AS total_expenditure_lakh FROM curated.v_mgnrega "
             "GROUP BY 1 ORDER BY 1")
TREND_ROWS = [{"financial_year": "2020-21", "total_expenditure_lakh": 6120.5},
              {"financial_year": "2021-22", "total_expenditure_lakh": 6880.25},
              {"financial_year": "2022-23", "total_expenditure_lakh": 8215.0},
              {"financial_year": "2023-24", "total_expenditure_lakh": 7904.1}]
SPLIT_SQL = "SELECT category, COUNT(*) AS beneficiaries FROM curated.v_focus_plus GROUP BY 1"
SPLIT_ROWS = [{"category": "General", "beneficiaries": 9870}, {"category": "ST", "beneficiaries": 7300},
              {"category": "SC", "beneficiaries": 400}, {"category": "Other", "beneficiaries": 1250}]


def run(coro):
    return asyncio.run(coro)


# ── shape detection ──────────────────────────────────────────────────────────
def test_top_n_is_a_ranking_from_the_sql_tree():
    s = p._answer_shape("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS)
    assert (s.kind, s.metric, s.desc, s.limit) == ("ranking", "person_days", True, 5)


def test_bottom_n_by_ordinal_is_an_ascending_ranking():
    s = p._answer_shape("lowest 3 districts", "SELECT district, COUNT(*) AS houses FROM t GROUP BY 1 ORDER BY 2 ASC "
                        "LIMIT 3", [{"district": "A", "houses": 10}, {"district": "B", "houses": 20},
                                    {"district": "C", "houses": 35}])
    assert (s.kind, s.metric, s.desc, s.limit) == ("ranking", "houses", False, 3)


def test_order_by_an_aggregate_expression_is_read():
    s = p._answer_shape("which block has the most person days",
                        "SELECT block, SUM(persondays) AS pd FROM t GROUP BY block ORDER BY SUM(persondays) DESC",
                        [{"block": "A", "pd": 9}, {"block": "B", "pd": 5}, {"block": "C", "pd": 1}])
    assert (s.kind, s.metric) == ("ranking", "pd")


def test_two_rows_are_a_comparison():
    assert p._answer_shape("compare EKH and WKH job cards", CMP_SQL, CMP_ROWS).kind == "compare"


def test_years_are_a_trend_not_a_ranking():
    s = p._answer_shape("how has expenditure changed", TREND_SQL, TREND_ROWS)
    assert (s.kind, s.metric) == ("trend", "total_expenditure_lakh")


def test_a_year_key_column_is_a_period_label():
    rows = [{"year_key": 2021 + i, "houses": 10 * (i + 1)} for i in range(4)]
    assert p._answer_shape("houses by year", "SELECT year_key, COUNT(*) AS houses FROM t GROUP BY 1", rows).kind \
        == "trend"


def test_split_without_order_is_a_breakdown():
    assert p._answer_shape("category wise beneficiaries", SPLIT_SQL, SPLIT_ROWS).kind == "breakdown"


def test_two_varying_labels_are_a_cross_tab():
    rows = [{"district": "A", "financial_year": "2022-23", "pd": 5}, {"district": "B", "financial_year": "2023-24", "pd": 7}]
    assert p._answer_shape("district wise yearly", "SELECT 1", rows).kind == "cross_tab"


def test_names_only_are_a_list_and_one_row_is_single_or_profile():
    assert p._answer_shape("which villages", "SELECT village FROM t", [{"village": "X"}, {"village": "Y"}]).kind == "list"
    assert p._answer_shape("total", "SELECT 1", [{"person_days": 5}]).kind == "single_value"
    assert p._answer_shape("summary", "SELECT 1", [{"a_count": 1, "b_count": 2}]).kind == "profile"


def test_yes_no_question_is_flagged():
    assert p._answer_shape("Is total person days above 1 crore?", "SELECT 1", [{"person_days": 5}]).yes_no
    assert not p._answer_shape("total person days", "SELECT 1", [{"person_days": 5}]).yes_no


def test_cross_scheme_rows_keep_their_own_path():
    rows = [{"scheme": "MGNREGA", "v": 1}, {"scheme": "PMAY-G", "v": 2}]
    assert p._answer_shape("top villages in mgnrega and pmay", "SELECT 1", rows) is None


# ── derived figures ──────────────────────────────────────────────────────────
def test_ranking_facts_give_the_gaps():
    text, nums = p._shape_facts(p._answer_shape("top 5", TOP5_SQL, TOP5_ROWS), TOP5_ROWS)
    assert "#1: Mylliem = 412,300" in text and "14,150 ahead of #2" in text
    assert {"14150", "291800"} <= nums                       # #1 - #2, #1 - #5


def test_compare_facts_give_difference_and_percent():
    text, nums = p._shape_facts(p._answer_shape("compare", CMP_SQL, CMP_ROWS), CMP_ROWS)
    assert "higher by 12,450, 48.3% more" in text and {"12450", "48.3"} <= nums


def test_trend_facts_give_first_to_last_peak_and_direction():
    text, nums = p._shape_facts(p._answer_shape("trend", TREND_SQL, TREND_ROWS), TREND_ROWS)
    assert "change +1,783.60 (+29.1%)" in text and "peak 8,215 in 2022-23" in text
    assert "mixed: rose in 2, fell in 1" in text and {"1783.6", "29.1"} <= nums


def test_breakdown_facts_give_total_and_shares():
    text, nums = p._shape_facts(p._answer_shape("split", SPLIT_SQL, SPLIT_ROWS), SPLIT_ROWS)
    assert "total beneficiaries = 18,820" in text and "General = 9,870 (52.4% of the total)" in text
    assert {"18820", "52.4"} <= nums


def test_rates_are_not_summed_into_shares():
    rows = [{"district": "A", "completion_pct": 40.5}, {"district": "B", "completion_pct": 60.0},
            {"district": "C", "completion_pct": 10.0}]
    text, _ = p._shape_facts(p._answer_shape("split", "SELECT 1", rows), rows)
    assert "total" not in text and "highest: B = 60; lowest: C = 10" in text


# ── composer wiring ──────────────────────────────────────────────────────────
def test_composer_gets_the_shape_and_its_figures_and_may_quote_them(monkeypatch):
    seen = []

    async def _composer(prompt):
        seen.append(prompt)
        return ("Mylliem leads with 412,300 person-days in East Khasi Hills in FY 2023-24 under MGNREGA.\n"
                "1. **Mylliem** — 412,300\n2. **Mawphlang** — 398,150\n3. **Mawkynrew** — 301,020\n"
                "4. **Pynursla** — 250,000\n5. **Laitkroh** — 120,500\nMylliem is 14,150 ahead of Mawphlang.")
    monkeypatch.setattr(p.llm, "call_response_composer", _composer)
    out = run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"],
                                 entities={"district": "East Khasi Hills", "year": "FY 2023-24"}))
    assert len(seen) == 1                                    # the derived 14,150 is not a misquote
    assert "Answer shape — A RANKING" in seen[0] and "Derived figures" in seen[0]
    assert "one to three plain sentences" not in seen[0]
    assert "14,150 ahead of Mawphlang" in out


def test_single_figure_keeps_the_briefing_line_prompt(monkeypatch):
    seen = []

    async def _composer(prompt):
        seen.append(prompt)
        return "MGNREGA provided 27,264,054 person-days across Meghalaya in FY 2023-24."
    monkeypatch.setattr(p.llm, "call_response_composer", _composer)
    run(p.compose_response("total person days", "SELECT SUM(x) AS person_days FROM t", [{"person_days": 27264054}],
                           schemes=["MGNREGA"]))
    assert "one to three plain sentences" in seen[0] and "Answer shape" not in seen[0]


def test_misquoting_ranking_falls_back_to_a_ranked_list(monkeypatch):
    async def _composer(_prompt):
        return "Mylliem leads with 999,999 person-days."
    monkeypatch.setattr(p.llm, "call_response_composer", _composer)
    out = run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"],
                                 entities={"district": "East Khasi Hills", "year": "FY 2023-24"}))
    assert out.startswith("Top 5 blocks by person-days of employment (MGNREGA, East Khasi Hills district, FY 2023-24):")
    assert "1. **Mylliem** — 412,300" in out and "5. **Laitkroh** — 120,500" in out
    assert "here are the" not in out


def test_misquoting_comparison_falls_back_to_the_verdict(monkeypatch):
    async def _composer(_prompt):
        return "East Khasi Hills has 99,999 job cards."
    monkeypatch.setattr(p.llm, "call_response_composer", _composer)
    out = run(p.compose_response("compare EKH and WKH job cards", CMP_SQL, CMP_ROWS, schemes=["MGNREGA"]))
    assert out.startswith("East Khasi Hills is ahead on job cards issued: 38,200 against 25,750 for West Khasi "
                          "Hills — a difference of 12,450, 48.3% more")


def test_misquoting_trend_falls_back_to_first_to_last(monkeypatch):
    async def _composer(_prompt):
        return "Expenditure was 1,111.11 lakh."
    monkeypatch.setattr(p.llm, "call_response_composer", _composer)
    out = run(p.compose_response("how has expenditure changed", TREND_SQL, TREND_ROWS, schemes=["MGNREGA"]))
    assert "went from 6,120.50 in 2020-21 to 7,904.10 in 2023-24 (+1,783.60, +29.1%" in out
    assert "It peaked at 8,215 in 2022-23." in out and "- 2021-22: 6,880.25" in out


# ── live findings, 2026-10-22 ────────────────────────────────────────────────
def test_compare_words_beat_an_ordered_limited_sql():
    # "Compare EKH and WKH" — the 30B ordered and limited the two rows; it was read as a ranking
    sql = CMP_SQL + " ORDER BY job_cards DESC LIMIT 2"
    assert p._answer_shape("Compare job cards in EKH and WKH", sql, CMP_ROWS).kind == "compare"


def test_financial_year_and_year_key_together_are_one_period():
    rows = [{"financial_year": f"20{20 + i}-{21 + i}", "year_key": 2020 + i, "total_expenditure_lakh": 100.0 + i}
            for i in range(4)]
    s = p._answer_shape("expenditure year by year", "SELECT 1", rows)
    assert (s.kind, s.labels) == ("trend", ["financial_year"])


def test_lowest_first_ranking_is_told_not_to_say_leads():
    s = p._answer_shape("lowest 3 districts", "SELECT district, COUNT(*) AS houses FROM t GROUP BY 1 ORDER BY 2 "
                        "LIMIT 3", [{"district": "A", "houses": 1}, {"district": "B", "houses": 2},
                                    {"district": "C", "houses": 3}])
    assert "LOWEST first" in p._shape_guide_block(s) and "never 'leads'" in p._shape_guide_block(s)


def test_breakdown_fallback_lists_largest_first():
    out = p._shaped_fallback(p._answer_shape("split", SPLIT_SQL, SPLIT_ROWS), SPLIT_ROWS, ["Focus Plus"], {})
    assert out.index("**General**") < out.index("**ST**") < out.index("**Other**") < out.index("**SC**")


def test_composer_sees_a_breakdown_largest_first(monkeypatch):
    seen = []

    async def _composer(prompt):
        seen.append(prompt)
        return "Focus Plus has 18,820 beneficiaries across 4 categories."
    monkeypatch.setattr(p.llm, "call_response_composer", _composer)
    run(p.compose_response("category wise beneficiaries", SPLIT_SQL, SPLIT_ROWS, schemes=["Focus Plus"]))
    shown = seen[0].split("Result (4 row(s)", 1)[1]
    assert shown.index('"General"') < shown.index('"ST"') < shown.index('"Other"') < shown.index('"SC"')
