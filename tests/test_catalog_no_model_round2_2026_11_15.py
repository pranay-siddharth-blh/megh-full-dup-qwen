"""No-model coverage, round 2 (15 Nov 2026, D-109 additions): shapes and wordings the catalogue now reads by rule.

Each was a no-model gold-bank failure whose truth is the measure's own figure (equal row by row to the bank's
independent truth SQL on megh_db; the bank case is named in each test). Offline: the catalogue is faked, no model,
no database.
    .venv/Scripts/python.exe -m pytest tests/test_catalog_no_model_round2_2026_11_15.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import answer_frame as af  # noqa: E402
from app import metric_catalog as mc  # noqa: E402
from app import pipeline as p  # noqa: E402
from app import spelling  # noqa: E402
from app.config import settings  # noqa: E402

_COLS = {
    "curated.v_expenditure": {"total_exp", "lgd_district", "lgd_block", "village_code", "year_key",
                              "financial_year_short"},
    "curated.v_employment": {"person_days", "households_employed", "households_completed_100_days", "lgd_district",
                             "lgd_block", "village_code", "year_key", "financial_year_short"},
    "curated.bridge_geography_source": {"geography_key", "lgd_district", "lgd_block", "village_code"},
    "curated.v_cm_elevate_disbursement": {"total_subsidy_disbursement", "total_disbursement", "scheme_name",
                                          "lgd_district", "lgd_block", "village_code", "year_key",
                                          "financial_year_short"},
    "curated.v_focus_plus": {"beneficiary_key", "block_name_raw", "lgd_block", "lgd_district", "village_code",
                             "year_key"},
    "curated.v_focus_legacy": {"amount_disbursed", "lgd_district", "lgd_block", "village_code", "year_key",
                               "financial_year_short"},
}


def _metric(key, scheme, prefix, expr, base, unit, phrases):
    return mc.Metric(key=key, scheme=scheme, display_name=key, expression=expr, base_object=base, unit=unit,
                     notes="", alias=mc._alias(key, prefix, unit),
                     phrases=tuple(mc._phrase(x) for x in phrases), columns=frozenset(_COLS[base]))


@pytest.fixture
def catalogue(monkeypatch):
    ms = [
        _metric("mgnrega_total_expenditure", "MGNREGA", "mgnrega_", "SUM(total_exp)", "curated.v_expenditure",
                "lakh rupees", ["expenditure", "spend"]),
        _metric("mgnrega_employment_generated", "MGNREGA", "mgnrega_", "SUM(person_days)", "curated.v_employment",
                "person-days", ["person days", "persondays", "employment generated"]),
        _metric("mgnrega_households_employed", "MGNREGA", "mgnrega_", "SUM(households_employed)",
                "curated.v_employment", "households", ["households", "households employed"]),
        _metric("mgnrega_households_100_days", "MGNREGA", "mgnrega_", "SUM(households_completed_100_days)",
                "curated.v_employment", "households", ["households completed 100 days",
                                                       "households that completed 100 days"]),
        _metric("mgnrega_villages_covered", "MGNREGA", "mgnrega_", "COUNT(DISTINCT geography_key)",
                "curated.bridge_geography_source", "villages", ["village", "villages covered"]),
        _metric("cm_elevate_disb_subsidy_disbursed", "CM Elevate Legacy", "cm_elevate_disb_",
                "SUM(total_subsidy_disbursement)", "curated.v_cm_elevate_disbursement", "rupees",
                ["subsidy", "subsidy disbursed"]),
        _metric("cm_elevate_disb_total_disbursed", "CM Elevate Legacy", "cm_elevate_disb_", "SUM(total_disbursement)",
                "curated.v_cm_elevate_disbursement", "rupees", ["amount disbursed", "total disbursed"]),
        _metric("focus_plus_beneficiaries", "Focus Plus", "focus_plus_", "COUNT(DISTINCT beneficiary_key)",
                "curated.v_focus_plus", "beneficiaries", ["beneficiaries"]),
        _metric("focus_legacy_total_disbursed", "Focus Legacy", "focus_legacy_", "SUM(amount_disbursed)",
                "curated.v_focus_legacy", "rupees", ["amount", "amount remitted"]),
    ]
    state = {"metrics": {m.key: m for m in ms}, "by_scheme": {}, "loaded": True,
             "no_block_level": frozenset({"Focus Plus"}),
             "source_blocks": {"curated.v_focus_plus": frozenset({"SELSELLA", "TIKRIKILLA"})},
             "single_year": frozenset({"mgnrega_households_employed", "mgnrega_households_100_days"}),
             "verified": {t: {} for t in mc.QUERY_TYPES}}
    for m in ms:
        state["by_scheme"].setdefault(m.scheme, []).append(m)
        for t in mc.QUERY_TYPES:
            state["verified"][t][m.key] = {"evidence": "test"}
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return state


def _er(**resolved):
    display = {"district": str(resolved["district"]).title()} if resolved.get("district") else {}
    return {"resolved": resolved, "display": display, "notes": []}


def _plan(q, scheme, village=None, **resolved):
    er = _er(**resolved)
    if village:
        er["display"]["village"] = village
    return p._metric_catalog_plan(q, [scheme], er)


# ── rankings BY year and BY sub-scheme ───────────────────────────────────────

def test_which_financial_year_ranks_every_year(catalogue):
    """W3-YR-01: every year, largest first (three of four years read as a trend with a year missing)."""
    plan = _plan("In which financial year was MGNREGA expenditure the highest?", "MGNREGA")
    assert plan["status"] == "built" and plan["verified"] and plan["qtype"] == "ranking", plan
    sql = plan["query"][0]
    assert "GROUP BY year_key ORDER BY (SUM(total_exp)) DESC NULLS LAST" in sql and "LIMIT" not in sql


def test_which_year_among_two_named_years(catalogue):
    """FU-24 t2 (rendered by the frame): the ranking stays inside the two years."""
    plan = _plan("Which financial year has the highest: MGNREGA expenditure in FY 2022-23 and FY 2023-24", "MGNREGA",
                 year_key_list=[2022, 2023])
    assert plan["status"] == "built" and plan["qtype"] == "ranking", plan
    assert plan["query"][1] == [[2022, 2023]] and "year_key = ANY($1::int[])" in plan["query"][0]


def test_the_all_years_scope_is_not_a_ranking_of_years(catalogue):
    plan = _plan("Which district had the highest MGNREGA expenditure across all financial years", "MGNREGA")
    assert plan["qtype"] == "ranking" and "GROUP BY lgd_district" in plan["query"][0]


def test_which_n_schemes_ranks_the_sub_schemes(catalogue):
    """W2-RK-04: "Which 3 CM Elevate Legacy schemes got the most subsidy?" (got = grammar)."""
    plan = _plan("Which 3 CM Elevate Legacy schemes got the most subsidy across all financial years?",
                 "CM Elevate Legacy")
    assert plan["status"] == "built" and plan["qtype"] == "ranking", plan
    sql = plan["query"][0]
    assert "GROUP BY scheme_name" in sql and sql.endswith("LIMIT 3")
    # ranked on the raw rupees: two schemes both read Rs 6.77 crore once rounded
    assert "ORDER BY (SUM(total_subsidy_disbursement)) DESC" in sql


def test_which_schemes_without_a_count_declines(catalogue):
    plan = _plan("Which CM Elevate Legacy schemes got the most subsidy?", "CM Elevate Legacy")
    assert plan["query"] is None


def test_received_is_grammar(catalogue):
    """CV-FL-02: "Which district received the highest Focus Legacy amount?"."""
    plan = _plan("Which district received the highest Focus Legacy amount across all financial years?",
                 "Focus Legacy")
    assert plan["status"] == "built" and plan["qtype"] == "ranking", plan


# ── per-year shapes ──────────────────────────────────────────────────────────

def test_trend_over_the_years_is_the_figure_per_year(catalogue):
    """CH-02."""
    plan = _plan("Show MGNREGA person-days trend over the years as a line chart", "MGNREGA")
    assert plan["status"] == "built" and plan["qtype"] == "breakdown", plan
    assert "GROUP BY year_key ORDER BY year_key" in plan["query"][0]


def test_two_years_joined_by_and_are_compared(catalogue):
    """FU-24 t1: "MGNREGA expenditure in 2022-23 and 2023-24 statewide"."""
    plan = _plan("MGNREGA expenditure in 2022-23 and 2023-24 statewide", "MGNREGA", year_key_list=[2022, 2023])
    assert plan["status"] == "built" and plan["qtype"] == "compare", plan


def test_a_year_range_year_by_year(catalogue):
    """G-S6: "... from 2022-23 to 2024-25, year by year"."""
    plan = _plan("MGNREGA expenditure in Ri Bhoi from 2022-23 to 2024-25, year by year", "MGNREGA",
                 district="RI BHOI", year_key_list=[2022, 2023, 2024])
    assert plan["status"] == "built" and plan["qtype"] == "compare", plan


@pytest.mark.parametrize("q", [
    "Show MGNREGA expenditure by financial year as bar chart, pie chart and line chart",    # CH-13
    "Show MGNREGA expenditure by financial year as a radar chart",                          # CH-16 (c13 notes it)
])
def test_chart_words_are_not_more_to_compute(catalogue, q):
    plan = _plan(q, "MGNREGA")
    assert plan["status"] == "built" and plan["qtype"] == "breakdown", plan


def test_and_before_a_figure_still_declines(catalogue):
    plan = _plan("Show MGNREGA expenditure by financial year as bar chart and wages", "MGNREGA")
    assert plan["query"] is None


def test_each_scheme_name_scheme_is_a_breakdown_by_scheme(catalogue):
    """SH-X018: "the total amount disbursed under each CM Elevate Legacy scheme"."""
    plan = _plan("What is the total amount disbursed under each CM Elevate Legacy scheme across all financial years?",
                 "CM Elevate Legacy")
    assert plan["status"] == "built" and plan["qtype"] == "breakdown", plan
    assert "GROUP BY scheme_name" in plan["query"][0]


# ── places ───────────────────────────────────────────────────────────────────

def test_village_word_names_the_pinned_village(catalogue):
    """CV-MG-11 / W3-VL-01: with ONE village pinned, "village" is not the villages-covered count."""
    plan = _plan("Person-days in UMRNONG village in 2022-23 under MGNREGA", "MGNREGA", village="Umrnong", village_code=270001,
                 year_key=2022)
    assert plan["status"] == "built" and plan["metric"] == "mgnrega_employment_generated", plan
    plan = _plan("Person-days and villages in 2022-23 under MGNREGA", "MGNREGA", year_key=2022)
    assert plan["status"] == "several"                     # no village pinned: both measures, as before


def test_block_list_districts_is_not_a_filter(catalogue):
    """W3-MP-02: the resolver's note of each block's district pins no other rows."""
    plan = _plan("Compare MGNREGA person-days in Zikzak and Betasing blocks in 2024-25", "MGNREGA",
                 block_list=["BETASING", "ZIKZAK"], year_key=2024,
                 block_list_districts={"BETASING": "SOUTH WEST GARO HILLS", "ZIKZAK": "SOUTH WEST GARO HILLS"})
    assert plan["status"] == "built" and plan["qtype"] == "compare", plan


def test_focus_plus_block_reads_the_source_block_column(catalogue):
    """CV-FP-01 / W2-BLK-08: truth COUNT(DISTINCT beneficiary_key) WHERE UPPER(block_name_raw) = 'SELSELLA'."""
    m = catalogue["metrics"]["focus_plus_beneficiaries"]
    sql, params, shown = mc.build(m, {"block": "Selsella"})
    assert "UPPER(block_name_raw) = UPPER($1)" in sql and params == ["SELSELLA"] and "lgd_block" not in sql
    assert "UPPER(block_name_raw) = 'SELSELLA'" in shown
    assert mc.build(m, {"block": "SIJU"}) is None            # a block the source column never names
    # 2026-11-15 (KI-728, the drill-down behind a ranking): a grouping by block reads the same source column, as the
    # model path's block breakdowns do (KI-718); it was declined before
    _sql, _params, grouped = mc.build(m, {}, "block")
    assert "UPPER(block_name_raw) AS block" in grouped and "lgd_block" not in grouped


# ── ratios, wordings, spelling ───────────────────────────────────────────────

def test_a_count_per_a_count(catalogue):
    """UAT-M08: truth 1.0 * SUM(person_days) / SUM(households_employed)."""
    plan = _plan("What was the average number of person-days per employment household in South West Khasi Hills "
                 "during 2024-25?", "MGNREGA", district="SOUTH WEST KHASI HILLS", year_key=2024)
    assert plan["status"] == "built" and plan["qtype"] == "ratio", plan
    sql = plan["query"][0]
    assert "ROUND((" in sql and "SUM(person_days)" in sql and "SUM(households_employed)" in sql
    assert sql.split("NULLIF(")[0].count("SUM(person_days)") == 1     # person-days above the line
    assert "person_days_per_employment_household" in sql


def test_mgnrega_work_is_the_scheme(catalogue):
    """G-P3: "households that completed 100 days of MGNREGA work"."""
    plan = _plan("Which district had the highest number of households that completed 100 days of MGNREGA work in "
                 "2022-23?", "MGNREGA", year_key=2022)
    assert plan["status"] == "built" and plan["metric"] == "mgnrega_households_100_days", plan


@pytest.mark.parametrize("typed,want", [
    ("expenditur", "expenditure"),       # W2-PF-MGX-misspelt: a long word missing only its final "e"
    ("expenditures", None),              # another form: left as typed
])
def test_final_e_typo(typed, want):
    assert spelling._domain_word(typed) == want


@pytest.mark.parametrize("q,want", [
    ("mgnrega persondays 2023 24", "mgnrega persondays 2023-24"),       # PF-MG-misspelt
    ("mgnrega persondays 2023 2024", "mgnrega persondays 2023-24"),
    ("mgnrega persondays 2023 25", "mgnrega persondays 2023 25"),       # not consecutive: left as typed
    ("2023 24 villages", "2023-24 villages"),
])
def test_spaced_financial_year(q, want):
    toks = spelling.tokens(q)
    i = next(i for i, t in enumerate(toks) if t.raw.startswith("20"))
    got = spelling._spaced_fy(q, toks, i)
    out = q[:toks[i].start] + got + q[toks[i + 1].end:] if got else q
    assert out == want


# ── the answer frame: "which year …?" after an answer by year ────────────────

def _frame(group, qtype, filters=None):
    return af.AnswerFrame(schemes=["MGNREGA"], measure_text="MGNREGA expenditure", qtype=qtype, group=group,
                          filters=dict(filters or {}), all_years=not filters, source="catalogue",
                          metric_key="mgnrega_total_expenditure")


@pytest.mark.parametrize("msg,order", [("which year had the most?", "desc"), ("which year was higher?", "desc"),
                                       ("and which year was the lowest?", None), ("which year was lower?", "asc")])
def test_year_rank_follow_up(msg, order):
    out = p._c18_edit_rank_year(msg, _frame("year", "compare", {"year_key_list": [2022, 2023]}))
    if order is None:
        assert out is None                                  # "and" is not one of the words: the older rules
        return
    kind, new = out
    assert kind == "rank" and new.qtype == "ranking" and new.group == "year" and new.order == order
    assert new.limit is None and new.filters == {"year_key_list": [2022, 2023]}
    assert p._c18_render(new) == ("Which financial year has the " + ("highest" if order == "desc" else "lowest")
                                  + ": MGNREGA expenditure in FY 2022-23 and FY 2023-24")


def test_year_rank_follow_up_needs_an_answer_by_year():
    assert p._c18_edit_rank_year("which year had the most?", _frame("district", "breakdown")) is None
    assert p._c18_edit_rank_year("which district had the most?", _frame("year", "breakdown")) is None


def test_except_words_hold_a_display_name_noise_word(monkeypatch):
    """SH-F023: 'disbursement' is noise in the data team's display names; read as an excluded wording it was an empty
    phrase and excluded nothing, so 'which district received the highest total Focus Plus disbursement' was answered
    as the payments COUNT (its truth is the amount)."""
    state = {"verified": {t: {} for t in mc.QUERY_TYPES}}
    state["verified"]["ranking"]["focus_plus_payments"] = {"evidence": "t", "except_words": ["disbursement"]}
    monkeypatch.setattr(mc, "_state", state)
    assert mc.verified("ranking", "focus_plus_payments", frozenset({("disbursement",)})) is None
    assert mc.verified("ranking", "focus_plus_payments", frozenset({("payment", "made")})) is not None
