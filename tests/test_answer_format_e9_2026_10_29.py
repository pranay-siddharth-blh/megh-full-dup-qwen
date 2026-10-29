"""
E9 answer formatting (2026-10-29; RAG plan item E9, composer audit 2026-10-27):

1. One money formatter (_c12_money): ₹, Indian grouping, the column's own lakh / crore, a rupee
   column by size; a non-zero amount never prints as ₹0.00 crore.
2. Each figure next to its own label (_c12_label_misbinds): a row's figure beside another row's
   name, a % written as lakh (MG-10), a row's own figure written as a gap (CL-05), a measure's
   figure labelled as another measure — each sends the composer to its strict retry.
3. Templated number sentences per shape (_c12s_e9_body): a ranking / comparison / trend / split
   gets every figure from code; the composer writes only an opening line with no figure.

No model or DB: the composer is stubbed.
    python -m pytest tests/test_answer_format_e9_2026_10_29.py -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

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
LENDER_ROWS = [{"lender": "Bank", "loans_cr": 11.10}, {"lender": "LIFCOM", "loans_cr": 9.79}]
PROFILE_ROW = [{"households_employed": 41210, "person_days": 2134560}]
EKH = {"district": "East Khasi Hills", "year": "FY 2023-24"}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def templates_on(monkeypatch):
    monkeypatch.setattr(p.settings, "ANSWER_TEMPLATES_ENABLED", True)


def _composer(monkeypatch, *replies):
    """Stub the composer with fixed replies (the last one repeats); returns the prompts it saw."""
    seen = []

    async def _call(prompt):
        seen.append(prompt)
        return replies[min(len(seen), len(replies)) - 1]
    monkeypatch.setattr(p.llm, "call_response_composer", _call)
    return seen


# ── 1. one money formatter ───────────────────────────────────────────────────
@pytest.mark.parametrize("value,unit,want", [
    (149443700, "rupees", "₹14.94 crore"),
    (118447500.0, "rupees", "₹11.84 crore"),        # FP-05 was "₹118,447,500.00"
    (1234567.5, "rupees", "₹12.35 lakh"),
    (62500, "rupees", "₹62,500"),                    # KI-171: never "₹0.01 crore"
    (1234.5, "rupees", "₹1,234.50"),
    (0, "rupees", "₹0"),
    (8996.36, "lakh", "₹8,996.36 lakh"),             # MGNREGA keeps its lakh
    (123456.78, "lakh", "₹1,23,456.78 lakh"),        # Indian grouping
    (0.05, "lakh", "₹5,000"),
    (0.58, "crore", "₹0.58 crore"),
    (2185.256, "crore", "₹2,185.26 crore"),
    (0.0125, "crore", "₹1.25 lakh"),                 # ₹1,25,000 is not "0.01 crore"
    (0.0035, "crore", "₹35,000"),                    # CMP-05: never ₹0.00 crore
    (-2185.256, "crore", "-₹2,185.26 crore"),
])
def test_one_money_formatter(value, unit, want):
    assert p._c12_money(value, unit) == want


def test_value_formatter_reads_the_column_suffix():
    assert p._c12_fmt_value("total_disbursed_cr", 119.73925) == "₹119.74 crore"
    assert p._c12_fmt_value("amount_rupees", 940000) == "₹9.40 lakh"
    assert p._c12_fmt_value("completion_100_day_pct", 3.39) == "3.39%"
    assert p._c12_fmt_value("person_days", 27264054) == "27,264,054"     # counts: grouping is an open decision


def test_fallbacks_write_money_through_the_formatter():
    out = p._framed_fallback([{"total_expenditure_lakh": 8996.36}], ["MGNREGA"],
                             {"district": "EAST KHASI HILLS", "year": "FY 2023-24"})
    assert out == ("Under MGNREGA, in FY 2023-24 in East Khasi Hills district, the recorded total is "
                   "₹8,996.36 lakh total expenditure.")
    assert p._deterministic_answer([{"total_disbursed_cr": 0.0035}]) == "total disbursed ₹35,000."
    rows = [{"lgd_district": f"D{i}", "total_disbursed_cr": 1.5} for i in range(3)]
    assert "- D0 — total disbursed: ₹1.50 crore" in p._deterministic_answer(rows)


# ── 2. each figure next to its own label ─────────────────────────────────────
@pytest.mark.parametrize("answer,rows", [
    ("Mylliem leads with 412,300 person-days.\n1. **Mylliem** — 412,300\n2. **Mawphlang** — 398,150\n"
     "Mylliem is 14,150 ahead of Mawphlang.", TOP5_ROWS),
    ("412,300 for Mylliem and 398,150 for Mawphlang.", TOP5_ROWS),
    ("Mylliem leads Mawphlang with 412,300 person-days.", TOP5_ROWS),         # not tied tightly: left alone
    ("Bank disbursed 1.31 crore more than LIFCOM: Bank 11.10, LIFCOM 9.79.", LENDER_ROWS),
    ("1. MAWHATI — 82.91%\n2. UMLING — 80.10%", [{"block": "MAWHATI", "wage_pct": 82.91},
                                                 {"block": "UMLING", "wage_pct": 80.10}]),
    ("In EKH, MGNREGA recorded 41,210 households employed and 2,134,560 person-days of employment.", PROFILE_ROW),
    ("- **Households employed**: 41,210\n- **Person-days**: 2,134,560", PROFILE_ROW),
    ("Expenditure rose from 6,120.50 lakh in FY 2020-21 to 7,904.10 lakh in FY 2023-24. It peaked in "
     "FY 2022-23 at 8,215.00 lakh.", TREND_ROWS),
    ("West Garo Hills sanctioned 3,410 more houses than East Garo Hills. West Garo Hills sanctioned 11,690 "
     "houses; East Garo Hills sanctioned 8,280.", [{"district": "West Garo Hills", "houses": 11690},
                                                   {"district": "East Garo Hills", "houses": 8280}]),
    ("Mylliem is in the top 5 with 412,300.", TOP5_ROWS),
])
def test_figures_in_their_place_pass(answer, rows):
    assert p._c12_label_misbinds(answer, rows) == []


@pytest.mark.parametrize("answer,rows,word", [
    ("1. **Mylliem** — 398,150\n2. **Mawphlang** — 412,300", TOP5_ROWS, "next to Mylliem"),
    ("Mylliem 398,150 and Mawphlang 412,300.", TOP5_ROWS, "next to Mylliem"),
    ("It peaked in FY 2022-23 at 7,904.10 lakh.", TREND_ROWS, "figure for 2023-24"),
    ("Bank disbursed 11.10 crore more loans than LIFCOM.", LENDER_ROWS, "difference"),          # CL-05
    ("1. MAWHATI — 82.91 lakh", [{"block": "MAWHATI", "wage_pct": 82.91},
                                 {"block": "UMLING", "wage_pct": 80.10}], "percentage"),      # MG-10
    ("Disbursed: 45.5% of the target.", [{"scheme_name": "A", "disbursed_cr": 45.5},
                                         {"scheme_name": "B", "disbursed_cr": 12.0}], "money"),
    ("MGNREGA recorded 2,134,560 households employed and 41,210 person-days.", PROFILE_ROW, "labelled as"),
    ("- **Households employed**: 2,134,560\n- **Person-days**: 41,210", PROFILE_ROW, "labelled as"),
])
def test_figures_out_of_place_are_named(answer, rows, word):
    found = p._c12_label_misbinds(answer, rows)
    assert found and any(word in f for f in found), found


def test_mgnrega_lakh_pass_leaves_a_share_of_expenditure_alone():
    # MG-10, reproduced live 2026-10-29: the composer wrote 24.09%, the lakh pass made it "24.09 lakh"
    rows = [{"lgd_district": "WEST GARO HILLS", "expenditure_share_pct": 24.09, "total_exp_lakh": 3533.1},
            {"lgd_district": "RI BHOI", "expenditure_share_pct": 4.72, "total_exp_lakh": 692.4}]
    sql = "SELECT lgd_district, SUM(total_exp) AS total_exp_lakh FROM curated.v_expenditure GROUP BY 1"
    out = p._mgnrega_money_units("1. **WEST GARO HILLS** — 24.09 share, 3,533.10\n2. **RI BHOI** — 4.72", sql, rows)
    assert "24.09 lakh" not in out and "4.72 lakh" not in out and "3,533.10 lakh" in out


def test_a_code_computed_figure_is_never_a_rows_own():
    # 14,150 is the gap (derived); 1,481,970 the total — neither belongs to a row
    ans = "The 5 blocks add up to 1,481,970; Mylliem holds 27.8% of that."
    assert p._c12_label_misbinds(ans, TOP5_ROWS, {"1481970", "27.8"}) == []


def test_compose_retries_a_misplaced_figure_then_keeps_the_good_retry(monkeypatch):
    seen = _composer(monkeypatch,
                     "MGNREGA recorded 2,134,560 households employed and 41,210 person-days in EKH.",
                     "MGNREGA recorded 41,210 households employed and 2,134,560 person-days in EKH.")
    out = run(p.compose_response("households and person days", "SELECT 1", PROFILE_ROW, schemes=["MGNREGA"],
                                 entities=EKH))
    assert len(seen) == 2 and "wrong label" in seen[1]
    assert out.startswith("MGNREGA recorded 41,210 households employed")


def test_compose_never_ships_a_row_figure_as_a_gap(monkeypatch):            # CL-05
    seen = _composer(monkeypatch, "Bank disbursed 11.10 crore more loans than LIFCOM.")
    out = run(p.compose_response("loans per lender", "SELECT lender, SUM(x) AS loans_cr FROM t GROUP BY 1",
                                 LENDER_ROWS, schemes=["CM Elevate Legacy"]))
    assert len(seen) == 2 and "11.10 crore more" not in out
    assert "a difference of 1.31" in out


# ── 3. templated number sentences per shape ──────────────────────────────────
def test_ranking_figures_come_from_code_and_the_composer_writes_the_opening(monkeypatch, templates_on):
    seen = _composer(monkeypatch, "Here are the five East Khasi Hills blocks with the most MGNREGA person-days "
                                  "in FY 2023-24:")
    out = run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"],
                                 entities=EKH))
    assert len(seen) == 1 and "contain NO figures" in seen[0] and '"top 5 blocks by person days"' in seen[0]
    assert out.split("\n")[0] == ("Here are the five East Khasi Hills blocks with the most MGNREGA person-days "
                                  "in FY 2023-24:")
    assert "1. **Mylliem** — 412,300" in out and "5. **Laitkroh** — 120,500" in out
    assert "ahead" not in out and "higher than" not in out                 # no gap line nobody asked for


def test_ranking_gap_line_only_when_asked(monkeypatch, templates_on):
    _composer(monkeypatch, "The top MGNREGA blocks by person-days:")
    out = run(p.compose_response("how far ahead is the top block in person days", TOP5_SQL, TOP5_ROWS,
                                 schemes=["MGNREGA"], entities=EKH))
    assert out.endswith("Mylliem is 14,150 higher than Mawphlang.")


@pytest.mark.parametrize("reply", [
    "Mylliem leads with 412,300 person-days:",                             # a figure
    "The data does not cover this.",                                       # a hedge
    "The blocks with the lowest person-days:",                             # the wrong direction
    "",
])
def test_an_unusable_opening_line_becomes_codes_own(monkeypatch, templates_on, reply):
    _composer(monkeypatch, reply)
    out = run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"],
                                 entities=EKH))
    assert out.split("\n")[0] == ("Top 5 blocks by person-days of employment (MGNREGA, East Khasi Hills "
                                  "district, FY 2023-24):")


def test_a_failed_opening_call_still_answers(monkeypatch, templates_on):
    async def _boom(_prompt):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(p.llm, "call_response_composer", _boom)
    out = run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"],
                                 entities=EKH))
    assert out.startswith("Top 5 blocks by person-days") and "1. **Mylliem** — 412,300" in out


def test_comparison_verdict_is_written_by_code(monkeypatch, templates_on):
    _composer(monkeypatch, "Job cards issued under MGNREGA in East and West Khasi Hills:")
    out = run(p.compose_response("compare EKH and WKH job cards", CMP_SQL, CMP_ROWS, schemes=["MGNREGA"]))
    assert ("East Khasi Hills is higher than West Khasi Hills on job cards issued: 38,200 against 25,750, a "
            "difference of 12,450 (48.3% more).") in out


def test_percentage_comparison_states_points(monkeypatch, templates_on):
    rows = [{"district": "A", "completion_pct": 40.5}, {"district": "B", "completion_pct": 20.5}]
    _composer(monkeypatch, "Completion in the two districts:")
    out = run(p.compose_response("compare A and B completion", "SELECT 1", rows, schemes=["MGNREGA"]))
    assert "40.50% against 20.50%, a difference of 20 percentage points." in out and "% more" not in out


def test_trend_sentence_money_and_direction(monkeypatch, templates_on):
    _composer(monkeypatch, "MGNREGA expenditure in Meghalaya, year by year:")
    out = run(p.compose_response("how has expenditure changed", TREND_SQL, TREND_ROWS, schemes=["MGNREGA"]))
    assert ("Total expenditure rose from ₹6,120.50 lakh in FY 2020-21 to ₹7,904.10 lakh in FY 2023-24, up "
            "₹1,783.60 lakh (29.1%).") in out
    assert "- FY 2022-23: ₹8,215.00 lakh" in out and "highest" not in out   # no peak line nobody asked for
    falling = list(reversed([dict(r, financial_year=r["financial_year"]) for r in TREND_ROWS]))
    for r, fy in zip(falling, ("2020-21", "2021-22", "2022-23", "2023-24")):
        r["financial_year"] = fy
    out = run(p.compose_response("what was the peak year for expenditure", TREND_SQL, falling, schemes=["MGNREGA"]))
    assert "fell from ₹7,904.10 lakh in FY 2020-21 to ₹6,120.50 lakh in FY 2023-24, down" in out
    assert "The highest was ₹8,215.00 lakh in FY 2021-22" in out


def test_year_key_periods_read_as_financial_years(templates_on):
    rows = [{"year_key": 2021 + i, "houses": 10 * (i + 1)} for i in range(3)]
    shape = p._answer_shape("houses by year", "SELECT year_key, COUNT(*) AS houses FROM t GROUP BY 1", rows)
    body = p._c12s_e9_body(shape, rows, "houses by year")
    assert body.startswith("Houses rose from 10 in FY 2021-22 to 30 in FY 2023-24, up 20 (200.0%).")


def test_breakdown_total_and_shares_only_when_asked(monkeypatch, templates_on):
    shape = p._answer_shape("category wise beneficiaries", SPLIT_SQL, SPLIT_ROWS)
    plain = p._c12s_e9_body(shape, SPLIT_ROWS, "category wise beneficiaries")
    assert plain.split("\n")[0] == "General is the largest with 9,870; SC is the smallest with 400."
    assert "total" not in plain and "%" not in plain
    assert plain.index("**General**") < plain.index("**ST**") < plain.index("**Other**") < plain.index("**SC**")
    asked = p._c12s_e9_body(shape, SPLIT_ROWS, "total beneficiaries and each category's share")
    assert asked.startswith("18,820 beneficiaries in total across 4 categories.\nGeneral is the largest with "
                            "9,870 (52.4%)")


@pytest.mark.parametrize("kw", [
    {"notes": ['The question treats "1.71 L" (~171,000) as an established figure, but no value in this result is '
               'close to it.']},                                           # a premise: the composer reconciles
    {"extra_numbers": {"999"}},
])
def test_composer_path_kept_where_words_must_reconcile(monkeypatch, templates_on, kw):
    seen = _composer(monkeypatch, "Mylliem leads with 412,300 person-days.\n1. **Mylliem** — 412,300")
    run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"], **kw))
    assert "Answer shape — A RANKING" in seen[0]


def test_wording_notes_go_to_the_opening_line_not_the_composer_path(monkeypatch, templates_on):
    # live 2026-10-29: every MGNREGA list carries "Name places in plain words …", which kept templates off
    note = "Name places in plain words. Never write column names such as lgd_district."
    seen = _composer(monkeypatch, "MGNREGA person-days in the top East Khasi Hills blocks, FY 2023-24:")
    out = run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"],
                                 entities=EKH, notes=[note]))
    assert len(seen) == 1 and "contain NO figures" in seen[0] and note in seen[0]
    assert "1. **Mylliem** — 412,300" in out


def test_style_shots_do_not_keep_the_composer_writing_figures(monkeypatch, templates_on):
    # live 2026-10-29: CM Elevate Legacy's district split (style shots) misquoted twice on the composer path
    seen = _composer(monkeypatch, "CM Elevate Legacy disbursement by district in FY 2024-25:")
    rows = [{"district": "EAST KHASI HILLS", "total_lakh": 1531.66}, {"district": "RI BHOI", "total_lakh": 458.37},
            {"district": "NORTH GARO HILLS", "total_lakh": 240.19}]
    out = run(p.compose_response("total disbursement by district", "SELECT 1", rows, schemes=["CM Elevate Legacy"],
                                 style_examples="Example answer: ..."))
    assert len(seen) == 1 and "contain NO figures" in seen[0]
    assert "- **EAST KHASI HILLS** — ₹1,531.66 lakh" in out


def test_one_amount_in_two_units_is_said_once_and_shorthand_in_full(templates_on):
    # live 2026-10-29: "Total exp fell … - FY 2022-23: ₹4,575.40 lakh; total exp ₹45.75 crore"
    rows = [{"financial_year": "2022-23", "total_exp_lakh": 4575.4, "total_exp_cr": 45.75},
            {"financial_year": "2023-24", "total_exp_lakh": 4295.67, "total_exp_cr": 42.96},
            {"financial_year": "2024-25", "total_exp_lakh": 5034.09, "total_exp_cr": 50.34}]
    shape = p._answer_shape("expenditure by year", "SELECT 1", rows)
    body = p._c12s_e9_body(shape, rows, "expenditure by year")
    assert body.startswith("Total expenditure rose from ₹4,575.40 lakh in FY 2022-23")
    assert "crore" not in body and "- FY 2023-24: ₹4,295.67 lakh\n" in body


def test_shaped_fallback_is_the_templated_answer(templates_on):
    shape = p._answer_shape("how has expenditure changed", TREND_SQL, TREND_ROWS)
    out = p._shaped_fallback(shape, TREND_ROWS, ["MGNREGA"], {"district": "RI BHOI"})
    assert out.startswith("Total expenditure over time (MGNREGA, Ri Bhoi district, across all financial years):\n"
                          "Total expenditure rose from ₹6,120.50 lakh in FY 2020-21")


def test_yes_no_question_keeps_the_composer(monkeypatch, templates_on):
    seen = _composer(monkeypatch, "Yes. East Khasi Hills has 38,200 job cards against 25,750.")
    run(p.compose_response("Does EKH have more job cards than WKH?", CMP_SQL, CMP_ROWS, schemes=["MGNREGA"]))
    assert "Answer shape" in seen[0]


def test_rollback_setting_restores_the_composer_written_answer(monkeypatch):
    assert p.settings.ANSWER_TEMPLATES_ENABLED is False                   # tests/conftest.py: the old suites
    seen = _composer(monkeypatch, "Mylliem leads with 412,300 person-days.")
    run(p.compose_response("top 5 blocks by person days", TOP5_SQL, TOP5_ROWS, schemes=["MGNREGA"]))
    assert "Answer shape — A RANKING" in seen[0]


def test_setting_is_on_by_default():
    from app.config import Settings
    assert Settings.model_fields["ANSWER_TEMPLATES_ENABLED"].default is True
