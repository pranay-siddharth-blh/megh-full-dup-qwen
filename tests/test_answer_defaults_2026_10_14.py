"""
User session 2026-10-13 and the hierarchy matrix run 2026-10-14: answer, don't ask
(ANSWER_DEFAULTS_ENABLED), and the wrong answers the session and the matrix found.
Every test calls the real function.
"""
from app import cross_scheme as cs
from app import guardrails as g
from app import pipeline as p
from app.config import settings


def test_answer_defaults_on_by_default():
    assert settings.ANSWER_DEFAULTS_ENABLED is True


# ── years ────────────────────────────────────────────────────────────────────

def test_fy_without_a_space_is_spaced_before_routing():
    assert p._correct_fy_spacing("PMAY-G houses in FY2022-23") == "PMAY-G houses in FY 2022-23"
    assert p._parse_year_key(p._correct_fy_spacing("released during FY2019-20")) == 2019
    assert p._correct_fy_spacing("FYI the data") == "FYI the data"


def test_the_state_is_meghalaya():
    assert p._correct_fy_spacing("Give me persons employed for the state") == \
        "Give me persons employed for Meghalaya"
    assert p._correct_fy_spacing("the state of Assam") == "the state of Assam"


def test_all_available_financial_years_is_all_years():
    for q in ("Across all available financial years combined, how many PMAY-G records in Nengkram?",
              "CM Elevate Legacy applications in Umling block across all schemes and financial years",
              "total sanctioned amount across all available records"):
        assert p._ALL_YEARS_CUE.search(q), q


def test_an_unasked_year_split_is_detected():
    sql = ("SELECT COALESCE(financial_year_short, '(no financial year)') AS fy, SUM(sanctioned_amount) "
           "FROM curated.v_cm_elevate_disbursement WHERE lgd_block = 'GASUAPARA' "
           "GROUP BY financial_year_short ORDER BY financial_year_short")
    assert p._vr_grouped_by_year_only(sql)
    assert not p._YEAR_SPLIT_ASKED.search("sanctioned amount for Gasuapara block across all financial years")
    assert p._YEAR_SPLIT_ASKED.search("sanctioned amount year-wise for Gasuapara")
    assert not p._vr_grouped_by_year_only(sql.replace("GROUP BY financial_year_short",
                                                            "GROUP BY financial_year_short, lgd_district"))


# ── job cards are a stock ────────────────────────────────────────────────────

def test_job_cards_sum_is_pinned_to_the_latest_year():
    out = p._mgnrega_job_cards_latest_year(
        ["MGNREGA"], "SELECT SUM(job_cards_issued_total) FROM curated.v_employment WHERE lgd_district = 'X'")
    assert p._JOB_CARD_PIN in out and "lgd_district = 'X'" in out
    out = p._mgnrega_job_cards_latest_year(["MGNREGA"], "SELECT SUM(job_cards_issued_total) FROM curated.v_employment")
    assert out.endswith(p._JOB_CARD_PIN)
    kept = "SELECT SUM(job_cards_issued_total) FROM curated.v_employment WHERE year_key = 2023"
    assert p._mgnrega_job_cards_latest_year(["MGNREGA"], kept) == kept


# ── follow-up and edge false hits ───────────────────────────────────────────

def test_relative_that_is_not_a_reference_to_an_earlier_answer():
    q = "Households that completed 100 days of work in RI BHOI"
    assert p._CONTEXTLESS_REF.search(q)
    assert not p._CONTEXTLESS_REF.search(p._RELATIVE_THAT.sub(" ", q))
    assert p._CONTEXTLESS_REF.search(p._RELATIVE_THAT.sub(" ", "what about that?"))


def test_terse_and_plain_data_questions_overrule_an_out_of_scope_verdict():
    for q in ("how many applicants are recorded under meghalaya poultry farming scheme in west garo hills?",
              "show me all remittances made between april and june 2025.",
              "cm elevate applicants in laskein block",
              "mgnrega people who got work in ampathi assembly constituency",
              "what is the village code of abokgre?"):
        assert g._DATA_QUESTION.search(q), q
    assert not g._DATA_QUESTION.search("write an instagram post")


# ── scheme pause -> each scheme that records it ─────────────────────────────

def test_unnamed_scheme_questions_go_to_the_schemes_that_record_them():
    assert cs.unnamed_schemes("How many applications are recorded in Tikrikilla block?") == \
        ["CM Elevate", "CM Elevate Legacy"]
    assert cs.unnamed_schemes("For FY 2022-23, how many beneficiary records are there in Dambo Rongjeng block?") == cs.ORDER
    assert "CM Elevate" not in cs.unnamed_schemes("total amount disbursed in Ri Bhoi")
    assert cs.unnamed_schemes("Give me total block count.") == cs.ORDER
    assert cs.plan("Give me total block count.", cs.ORDER, {}).coverage
    assert cs.unnamed_schemes("How many schemes are onboarded?") is None


def test_how_many_schemes_is_the_listing():
    assert p._SCHEME_LISTING_CUE.search("How many schemes are onboarded?")
    assert not p._SCHEME_LISTING_CUE.search("How many schemes are there under CM Elevate?")


def test_remittance_is_focus_legacy_vocabulary():
    assert p._FOCUSLEGACY_ONLY_TERMS.search("Show me all remittances made between April and June 2025")


def test_geo_lookup_questions_are_recognised():
    for q in ("What is the village code of Abokgre?", "Which block is Umshaken village in?",
              "What is the block name of Aberam village?", "LGD code for Mawsawa"):
        assert p._GEO_LOOKUP_MATCH.search(q), q
    assert not p._GEO_LOOKUP_MATCH.search("How many person-days in Abokgre village?")


def test_mgnrega_expenditure_component_must_be_read():
    import asyncio
    import pytest
    sql = "SELECT ROUND(SUM(total_exp), 2) AS total_expenditure_lakh FROM curated.v_expenditure WHERE village_code = 272818"
    comps = {col for cue, col in p._MGNREGA_EXP_COMPONENTS
             if cue.search("MGNREGA unskilled wage expenditure in BOWABARI village")}
    assert comps == {"unskilled_wage_exp"}
    assert not {col for cue, col in p._MGNREGA_EXP_COMPONENTS
                if cue.search("MGNREGA semi-skilled wage expenditure")} - {"semi_skilled_wage_exp"}
    assert "unskilled_wage_exp" not in sql   # the guard in _execute_one_attempt sends this back


def test_chip_tail_with_a_year_is_still_a_chip():
    assert p._CHIP_TAIL_PARSE_MATCH.search(
        "How many persons employed are there in Apalgre village during FY 2024-25, SELSELLA block, WEST GARO HILLS")


def test_component_amount_question_is_not_answered_with_a_share():
    assert not p._SHARE_ASKED.search("MGNREGA unskilled wage expenditure in Mawdet village")
    assert p._SHARE_ASKED.search("unskilled wage share in Mawdet")


# --- a resolved village the SQL only NAMES (hierarchy matrix 2026-10-14, "mot village") ---

def test_village_code_in_select_is_not_a_filter():
    from app import pipeline as p
    er = {"resolved": {"village_code": 278836}}
    sql = ("SELECT COUNT(DISTINCT village_code) AS households_employed_villages\n"
           "FROM curated.v_employment\nWHERE households_employed > 0\nLIMIT 1000")
    assert p._village_filter_missing(["MGNREGA"], er, sql) == 278836
    assert p._mgnrega_village_filter_missing(["MGNREGA"], er, sql) == 278836
    for ok in ("SELECT SUM(x) FROM curated.v_employment WHERE village_code = 278836",
               "SELECT SUM(x) FROM curated.v_employment e WHERE e.village_code IN (278836)",
               "SELECT SUM(x) FROM curated.v_employment WHERE UPPER(lgd_village_name) = 'MOT'",
               "SELECT SUM(x) FROM a JOIN b ON a.village_code = b.village_code WHERE b.lgd_village_name ILIKE 'MOT'"):
        assert p._village_filter_missing(["MGNREGA"], er, ok) is None, ok


def test_counting_villages_for_one_village_is_rejected():
    from app import pipeline as p
    er = {"resolved": {"village_code": 278836}}
    sql = "SELECT COUNT(DISTINCT village_code) FROM curated.v_employment WHERE village_code = 278836"
    q = "What is the total MGNREGA households that got employment in mot village?"
    assert p._village_count_for_one_village(q, er, sql) == 278836
    assert p._village_count_for_one_village("How many villages in mot village block got work?", er, sql) is None
    assert p._village_count_for_one_village(q, er, sql.replace("COUNT(DISTINCT village_code)", "SUM(households_employed)")) is None
    assert p._village_count_for_one_village(q, {"resolved": {}}, sql) is None
