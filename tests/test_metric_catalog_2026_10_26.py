"""The data team's metric catalogue as a fixed query (D-071, RAG plan A, 2026-10-26).

A question that names exactly one catalogue measure and asks nothing else gets
its SQL built from semantic.metric_definitions, so different wordings of the
same question read the same figure. It never guesses: no measure, two
measures, a shared phrase, an extra word, an unsupported filter or shape ->
the model path, exactly as before. Shadow mode and unverified measures only log."""
import asyncio

import pytest

from app import metric_catalog as mc
from app import pipeline as p
from app.config import settings

_COLS = {
    "curated.v_expenditure": {"total_exp", "material_exp", "unskilled_wage_exp", "lgd_district", "lgd_block",
                              "village_code", "year_key", "financial_year_short"},
    "curated.v_employment": {"person_days", "job_cards_issued_total", "lgd_district", "lgd_block",
                             "village_code", "year_key", "financial_year_short"},
    "curated.v_cm_elevate": {"request_id", "lgd_district", "lgd_block", "village_code", "data_verified"},
}


def _metric(key, expr, base, unit, phrases, prefix="mgnrega_", scheme="MGNREGA"):
    return mc.Metric(key=key, scheme=scheme, display_name=key, expression=expr, base_object=base, unit=unit,
                     notes="", alias=mc._alias(key, prefix, unit),
                     phrases=tuple(mc._phrase(x) for x in phrases), columns=frozenset(_COLS[base]))


@pytest.fixture
def catalogue(monkeypatch):
    ms = [
        _metric("mgnrega_total_expenditure", "SUM(total_exp)", "curated.v_expenditure", "lakh rupees",
                ["MGNREGA Total Expenditure", "spend", "expenditure", "money spent", "outlay"]),
        _metric("mgnrega_material_expenditure", "SUM(material_exp)", "curated.v_expenditure", "lakh rupees",
                ["material expenditure", "material cost"]),
        _metric("mgnrega_employment_generated", "SUM(person_days)", "curated.v_employment", "person-days",
                ["person days", "mandays"]),
        _metric("mgnrega_job_card_stock", "SUM(job_cards_issued_total)", "curated.v_employment", "job cards",
                ["job cards"]),
        _metric("cm_elevate_applications", "COUNT(DISTINCT request_id)", "curated.v_cm_elevate", "applications",
                ["applications"], prefix="cm_elevate_", scheme="CM Elevate"),
    ]
    state = {"metrics": {m.key: m for m in ms}, "by_scheme": {}, "loaded": True,
             "no_block_level": frozenset({"CM Elevate"}),
             "single_year": frozenset({"mgnrega_job_card_stock"}),
             "verified": {t: {} for t in mc.QUERY_TYPES}}
    for m in ms:
        state["by_scheme"].setdefault(m.scheme, []).append(m)
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return state


def _er(**resolved):
    display = {}
    if resolved.get("district"):
        display["district"] = str(resolved["district"]).title()
    return {"resolved": resolved, "display": display, "notes": []}


def _verify(state, qtype, key):
    state["verified"][qtype][key] = {"evidence": "test"}


# ── the matcher ─────────────────────────────────────────────────────────────

def test_different_wordings_find_the_same_measure(catalogue):
    for q in ("total expenditure in Ri Bhoi 2023-24", "how much was the outlay", "money spent in Ri Bhoi"):
        assert mc.match(q, "MGNREGA").metric.key == "mgnrega_total_expenditure", q


def test_the_longest_phrase_wins(catalogue):
    assert mc.match("material expenditure in 2023-24", "MGNREGA").metric.key == "mgnrega_material_expenditure"


def test_helper_verbs_the_rephraser_adds_do_not_break_a_phrase(catalogue):
    assert mc.match("How much money was spent in Umsning", "MGNREGA").metric.key == "mgnrega_total_expenditure"
    plan = p._metric_catalog_plan("How much money was spent under MGNREGA in Ri Bhoi in FY 2023-24?",
                                  ["MGNREGA"], _er(district="RI BHOI", year_key=2023))
    assert plan["status"] == "built", plan


def test_a_wording_excluded_by_the_evidence_does_not_answer(catalogue):
    catalogue["verified"]["total"]["mgnrega_total_expenditure"] = {"except_words": ["outlay"]}
    er = _er(district="RI BHOI", year_key=2023)
    assert not p._metric_catalog_plan("Outlay in Ri Bhoi in 2023-24", ["MGNREGA"], er)["verified"]
    assert p._metric_catalog_plan("Expenditure in Ri Bhoi in 2023-24", ["MGNREGA"], er)["verified"]


def test_two_measures_are_never_guessed(catalogue):
    found = mc.match("expenditure and person days in 2023-24", "MGNREGA")
    assert found.metric is None and found.status == "several"


def test_no_measure_named(catalogue):
    assert mc.match("how many houses were built", "MGNREGA").status == "none"


def test_scheme_words_and_a_trailing_total_are_not_a_measure():
    assert mc._phrase("Focus+ total") == ()
    assert mc._phrase("pg disbursement total") == ("pg", "disbursement")
    assert mc._phrase("CM Elevate Disbursement -- total paid out") == ("paid", "out")


def test_aliases_follow_the_sql_prompt_units():
    assert mc._alias("mgnrega_total_expenditure", "mgnrega_", "lakh rupees") == "total_expenditure_lakh"
    assert mc._alias("pmay_amount_released", "pmay_", "rupees") == "amount_released_cr"
    assert mc._alias("pmay_completion_rate", "pmay_", "percent") == "completion_rate_pct"
    assert mc._common_key_prefix(["cm_elevate_disb_a", "cm_elevate_disb_b"]) == "cm_elevate_disb_"


def test_an_expression_that_is_not_one_aggregate_is_refused():
    assert mc._expression_columns("SUM(total_exp)") == {"total_exp"}
    assert mc._expression_columns("(SELECT 1 FROM curated.x)") is None
    assert mc._expression_columns("total_exp") is None


# ── the query ───────────────────────────────────────────────────────────────

def test_the_built_query_binds_every_value(catalogue):
    m = catalogue["metrics"]["mgnrega_total_expenditure"]
    sql, params, shown = mc.build(m, {"district": "Ri Bhoi", "year_key": [2023]})
    assert params == ["Ri Bhoi", 2023] and "Ri Bhoi" not in sql and "$1" in sql and "$2" in sql
    assert "ROUND((SUM(total_exp))::numeric, 2) AS total_expenditure_lakh" in sql
    assert "FROM curated.v_expenditure" in sql and "'RI BHOI'" in shown
    assert mc.is_catalog_sql(sql) and "metric:mgnrega_total_expenditure total" in p._sql_comment_marks(sql)


def test_a_filter_the_view_cannot_take_is_not_built(catalogue):
    m = catalogue["metrics"]["cm_elevate_applications"]
    assert mc.build(m, {"year_key": [2023]}) is None


def test_no_block_level_query_for_a_scheme_whose_blocks_are_elsewhere(catalogue):
    m = catalogue["metrics"]["cm_elevate_applications"]          # listed in the fixture's no_block_level
    assert mc.build(m, {"block": "UMSNING"}) is None and mc.build(m, {}, "block") is None
    assert mc.build(m, {"district": "RI BHOI"}) is not None
    assert "Focus Plus" in mc._load_verified()[2]


def test_ranking_query_orders_and_limits(catalogue):
    m = catalogue["metrics"]["mgnrega_total_expenditure"]
    sql, _, _ = mc.build(m, {"year_key": [2023]}, "district", order="desc", limit=3, qtype="ranking")
    assert "GROUP BY lgd_district ORDER BY total_expenditure_lakh DESC NULLS LAST LIMIT 3" in sql
    assert "lgd_district IS NOT NULL" in sql


# ── the pipeline's decision ─────────────────────────────────────────────────

def test_a_plain_total_is_built(catalogue):
    plan = p._metric_catalog_plan("What is the total expenditure in Ri Bhoi in 2023-24?", ["MGNREGA"],
                                  _er(district="RI BHOI", year_key=2023))
    assert plan["status"] == "built" and plan["qtype"] == "total" and plan["query"][1] == ["RI BHOI", 2023]


def test_the_scheme_name_is_not_an_extra_word(catalogue):
    plan = p._metric_catalog_plan("Total expenditure under MGNREGA in Ri Bhoi in 2023-24", ["MGNREGA"],
                                  _er(district="RI BHOI", year_key=2023))
    assert plan["status"] == "built", plan


def test_an_extra_word_leaves_it_to_the_model(catalogue):
    plan = p._metric_catalog_plan("What is the wage expenditure in Ri Bhoi in 2023-24?", ["MGNREGA"],
                                  _er(district="RI BHOI", year_key=2023))
    assert plan["query"] is None and "wage" in plan["reason"]


def test_an_unsupported_filter_leaves_it_to_the_model(catalogue):
    plan = p._metric_catalog_plan("expenditure in 2023-24", ["MGNREGA"],
                                  _er(year_key=2023, assembly_constituency="X"))
    assert plan["query"] is None


def test_a_per_year_tally_is_not_added_across_years(catalogue):
    plan = p._metric_catalog_plan("job cards in all years", ["MGNREGA"], _er())
    assert plan["query"] is None and "one financial year" in plan["reason"]


def test_no_year_and_no_all_years_cue_is_not_built(catalogue):
    plan = p._metric_catalog_plan("total expenditure in Ri Bhoi", ["MGNREGA"], _er(district="RI BHOI"))
    assert plan["query"] is None


def test_breakdown_ranking_and_compare_shapes(catalogue):
    plan = p._metric_catalog_plan("expenditure by district in 2023-24", ["MGNREGA"], _er(year_key=2023))
    assert plan["qtype"] == "breakdown" and "GROUP BY lgd_district" in plan["query"][0]
    plan = p._metric_catalog_plan("Which district had the highest expenditure in 2023-24?", ["MGNREGA"],
                                  _er(year_key=2023))
    # "which district … highest" reads the winner and the next two (D-092, 2026-10-29)
    assert plan["qtype"] == "ranking" and "DESC NULLS LAST LIMIT 3" in plan["query"][0]
    plan = p._metric_catalog_plan("top 3 districts by expenditure in 2023-24", ["MGNREGA"], _er(year_key=2023))
    assert plan["qtype"] == "ranking" and "DESC NULLS LAST LIMIT 3" in plan["query"][0]
    plan = p._metric_catalog_plan("Top districts for expenditure in 2023-24", ["MGNREGA"], _er(year_key=2023))
    assert plan["query"] is None                       # how many is not said
    plan = p._metric_catalog_plan("compare expenditure in Ri Bhoi and Jaintia Hills in 2023-24", ["MGNREGA"],
                                  _er(district_list=["RI BHOI", "JAINTIA HILLS"], year_key=2023))
    assert plan["qtype"] == "compare" and "= ANY($1::text[])" in plan["query"][0]


def test_shadow_and_unverified_measures_never_answer(catalogue, monkeypatch):
    q, er = "What is the total expenditure in Ri Bhoi in 2023-24?", _er(district="RI BHOI", year_key=2023)
    assert p._metric_catalog_query(q, ["MGNREGA"], er) is None          # built, but not verified
    _verify(catalogue, "total", "mgnrega_total_expenditure")
    assert p._metric_catalog_query(q, ["MGNREGA"], er) is not None      # verified -> answers
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "shadow")
    assert p._metric_catalog_query(q, ["MGNREGA"], er) is None          # shadow: log only
    _verify(catalogue, "breakdown", "mgnrega_total_expenditure")
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    assert p._metric_catalog_query("expenditure by block in 2023-24", ["MGNREGA"], _er(year_key=2023))


def test_off_mode_does_nothing(catalogue, monkeypatch):
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "off")
    assert p._metric_catalog_plan("expenditure in 2023-24", ["MGNREGA"], _er(year_key=2023))["status"] == "off"


def test_it_is_the_last_fixed_query_and_runs_read_only(catalogue, monkeypatch):
    from pathlib import Path
    src = Path(p.__file__).parent.joinpath("common", "c13_compose_and_data_stages.py").read_text(encoding="utf-8")
    chain = src[src.index("_mg_det = _mg_admin or ("):src.index("d.update(mg_admin=_mg_admin")]
    # D-110: the catalogue also takes the edited answer frame of a frame-resolved follow-up
    assert chain.rstrip().endswith('_metric_catalog_query(question, schemes, entity_result, frame=d.get("frame_edit"))')
    seen = {}

    async def ro(sql, params=None):
        seen["ro"] = sql
        return [{"x": 1}]

    async def rw(sql, params=None):
        seen["rw"] = sql
        return [{"x": 1}]

    monkeypatch.setattr(p, "_c16_fetch_rows_readonly", ro)
    monkeypatch.setattr(p, "fetch_rows", rw)
    m = catalogue["metrics"]["mgnrega_total_expenditure"]
    asyncio.run(p._data_deterministic_rows({"mg_det": mc.build(m, {"year_key": [2023]})}))
    asyncio.run(p._data_deterministic_rows({"mg_det": ("/* mg-job-cards */ SELECT 1", [], "x")}))
    assert "metric:" in seen["ro"] and "mg-job-cards" in seen["rw"]


def test_the_verified_file_loads():
    types, single, _ = mc._load_verified()
    assert set(types) == set(mc.QUERY_TYPES) and "mgnrega_job_card_stock" in single
