"""A measure the chosen scheme does not record (reported 2026-10-06).

"Give me person days in Mawlwai for Focus Plus across all financial years" was
answered "Mawlai block recorded 12 person days for Focus Plus": the SQL model
wrote COUNT(*) AS person_days on curated.v_focus_plus, 12 PAYMENTS renamed to
the measure asked for. Two guards now cover every scheme:
  * _measure_not_held_gap (scope_scheme, before any SQL) pauses and says so;
  * _sql_measure_label_issue (execute_attempt) rejects a mislabelled column.
"""
import asyncio
import inspect

import pytest

from app import pipeline as p

MAWLWAI = ("Give me person days in Mawlwai for Focus Plus across all financial years, "
           "the block, not the village")


# ── 1. The pause, before SQL ───────────────────────────────────────────────

def test_reported_mawlwai_question_pauses_instead_of_answering_payments():
    gap = p._measure_not_held_gap(MAWLWAI, ["Focus Plus"])
    assert gap is not None and gap.rule == "measure-not-held"
    assert "Focus Plus doesn't record person-days" in gap.question
    assert "only MGNREGA does" in gap.question
    labels = [o["label"] for o in gap.options]
    assert labels[0] == "Person-days under MGNREGA"
    assert "Disbursements" in labels and "Amount disbursed" in labels
    # the offers keep the place and the year range the user asked about
    assert "MGNREGA" in gap.options[0]["question"] and "Focus Plus" not in gap.options[0]["question"]
    assert all("Mawlwai" in o["question"] for o in gap.options)
    assert all("across all financial years" in o["question"] for o in gap.options[1:])


@pytest.mark.parametrize("question,schemes,measure,owner", [
    ("How many houses were sanctioned under CM Elevate in East Khasi Hills?", ["CM Elevate"],
     "houses", "PMAY-G"),
    ("How many houses under Focus Plus?", ["Focus Plus"], "houses", "PMAY-G"),
    ("Total subsidy disbursed under MGNREGA in 2023-24", ["MGNREGA"], "subsidy", "CM Elevate Legacy"),
    ("Loans given under PMAY-G in Ri Bhoi", ["PMAY-G"], "loans", "CM Elevate Legacy"),
    ("How many job cards under PMAY-G in West Garo Hills?", ["PMAY-G"], "job cards", "MGNREGA"),
    ("Wage expenditure under Focus Legacy in Ri Bhoi", ["Focus Legacy"], "wage expenditure", "MGNREGA"),
    ("Person days under CM Elevate Legacy", ["CM Elevate Legacy"], "person-days", "MGNREGA"),
    ("Households employed under Focus Plus in 2025-26", ["Focus Plus"], "employment", "MGNREGA"),
    ("How many producer groups under Focus Plus?", ["Focus Plus"], "producer groups", "Focus Legacy"),
    ("Material expenditure under PMAY-G", ["PMAY-G"], "material expenditure", "MGNREGA"),
])
def test_every_scheme_pauses_on_a_measure_only_another_scheme_records(question, schemes, measure, owner):
    gap = p._measure_not_held_gap(question, schemes)
    assert gap is not None and gap.rule == "measure-not-held"
    assert f"{schemes[0]} doesn't record {measure}" in gap.question
    assert f"only {owner} does" in gap.question
    assert gap.options[0]["label"].endswith(f"under {owner}")


@pytest.mark.parametrize("question,schemes,measure", [
    ("Total amount disbursed under CM Elevate", ["CM Elevate"], "rupee amounts"),
    ("How much money was spent under CM Elevate in Shillong?", ["CM Elevate"], "rupee amounts"),
    ("How many women got Focus Legacy payments?", ["Focus Legacy"], "gender"),
    ("Female applicants under CM Elevate Legacy", ["CM Elevate Legacy"], "gender"),
    ("How many applications under MGNREGA?", ["MGNREGA"], "applications"),
])
def test_measures_held_by_several_schemes_still_pause_where_none_holds_them(question, schemes, measure):
    gap = p._measure_not_held_gap(question, schemes)
    assert gap is not None and f"doesn't record {measure}" in gap.question


@pytest.mark.parametrize("question,schemes", [
    ("Total MGNREGA person-days in 2023-24", ["MGNREGA"]),
    ("How many households completed 100 days of work under MGNREGA?", ["MGNREGA"]),
    ("How many PMAY-G houses completed in East Khasi Hills?", ["PMAY-G"]),
    ("How much PMAY-G amount was released in 2022-23?", ["PMAY-G"]),
    ("How many PMAY-G houses were allotted to women?", ["PMAY-G"]),
    ("How much was disbursed under Focus Plus in Mawlai?", ["Focus Plus"]),
    ("How many Focus Plus payments in Mawlai block?", ["Focus Plus"]),
    ("Focus Plus payments by gender", ["Focus Plus"]),
    ("How many CM Elevate applications from women?", ["CM Elevate"]),
    ("How many producer groups were paid under Focus Legacy?", ["Focus Legacy"]),
    ("Total sanctioned amount under CM Elevate Legacy for the Warehouse scheme", ["CM Elevate Legacy"]),
    ("Subsidy and loan disbursed under CM Elevate Legacy", ["CM Elevate Legacy"]),
    ("Compare MGNREGA person-days and PMAY-G houses in East Khasi Hills", ["MGNREGA", "PMAY-G"]),
    ("Payments in the last 100 days under Focus Plus", ["Focus Plus"]),
])
def test_a_measure_the_scheme_records_is_never_paused(question, schemes):
    assert p._measure_not_held_gap(question, schemes) is None


def test_owner_offer_names_only_the_owner_scheme():
    # "CM Elevate" + "sanctioned" is re-pointed to CM Elevate Legacy; the PMAY-G
    # offer must not keep the typed "CM Elevate" beside PMAY-G
    gap = p._measure_not_held_gap("How many houses were sanctioned under CM Elevate in East Khasi Hills?",
                                  ["CM Elevate Legacy"])
    q = gap.options[0]["question"]
    assert q == "How many houses were sanctioned under PMAY-G in East Khasi Hills?"


@pytest.mark.parametrize("question,scope", [
    (MAWLWAI, " in Mawlwai block across all financial years"),   # "the block, not the village"
    ("Person days in Mawlai block for Focus Plus", " in Mawlai block"),
    ("Person days in Umsning village under Focus Plus", " in Umsning village"),
    ("Person days in Nongpoh, not the village, under Focus Plus", " in Nongpoh"),
    ("Job cards under PMAY-G in West Garo Hills in 2023-24", " in West Garo Hills in FY 2023-24"),
])
def test_offers_keep_the_level_the_user_already_settled(question, scope):
    # an offer that drops "block" re-asks "block or village?" after the tap
    assert p._measure_gap_scope(question) == scope


def test_focus_plus_stated_amount_keeps_its_own_reply():
    # "loans of ₹5,000" has the reviewed amount-not-held reply (two real sizes)
    assert p._measure_not_held_gap("How many Focus Plus loans of 5000?", ["Focus Plus"]) is None


def test_cm_elevate_offers_carry_no_year():
    gap = p._measure_not_held_gap("How many houses under CM Elevate in Ri Bhoi in 2023-24?",
                                  ["CM Elevate"])
    own = [o for o in gap.options if "CM Elevate" in o["question"]]
    assert own and all("2023" not in o["question"] for o in own)
    assert all("Ri Bhoi" in o["question"] for o in own)


def test_place_name_with_measure_words_is_masked():
    # scan_text is the question with the village name masked (the stage passes
    # _mask_scheme_words_in_village_name's output), so a place is never a measure
    q = "Total Focus Plus amount disbursed in Houses Village"
    assert p._measure_not_held_gap(q, ["Focus Plus"],
                                   scan_text="Total Focus Plus amount disbursed in ") is None


def test_scheme_stage_runs_the_gate_after_classification():
    src = inspect.getsource(p._data_scheme_stage)
    assert "_measure_not_held_gap(question, schemes, scan_text=_scheme_q)" in src
    assert src.index("classify_scheme(") < src.index("_measure_not_held_gap(")


# ── 2. The SQL label guard ──────────────────────────────────────────────────

def test_reported_sql_is_rejected_for_repair():
    sql = ("SELECT COUNT(*) AS person_days FROM curated.v_focus_plus "
           "WHERE lgd_block = 'MAWLAI' LIMIT 1")
    issue = p._sql_measure_label_issue(["Focus Plus"], sql)
    assert issue and "'person_days'" in issue and "Focus Plus records no person-days" in issue


@pytest.mark.parametrize("schemes,sql", [
    (["Focus Plus"], "SELECT COUNT(*) AS payments, SUM(amount_disbursed) AS amount_disbursed "
                     "FROM curated.v_focus_plus"),
    (["MGNREGA"], "SELECT SUM(person_days) AS person_days FROM curated.v_employment"),
    (["PMAY-G"], "SELECT COUNT(*) AS houses_sanctioned FROM curated.v_pmay"),
    (["CM Elevate Legacy"], "SELECT COUNT(*) AS warehouse_records, CAST(x AS numeric) "
                            "FROM curated.v_cm_elevate_disbursement"),
    (["CM Elevate"], "WITH t AS (SELECT * FROM curated.v_cm_elevate) "
                     "SELECT COUNT(*) AS applications FROM t"),
])
def test_honestly_named_columns_pass(schemes, sql):
    assert p._sql_measure_label_issue(schemes, sql) is None


@pytest.mark.parametrize("schemes,sql", [
    (["CM Elevate"], "SELECT COUNT(*) AS total_amount FROM curated.v_cm_elevate"),
    (["PMAY-G"], "SELECT SUM(amount_released) AS wages FROM curated.v_pmay"),
    (["Focus Legacy"], "SELECT COUNT(*) AS houses FROM curated.v_focus_legacy"),
])
def test_mislabelled_columns_are_rejected_on_every_scheme(schemes, sql):
    assert p._sql_measure_label_issue(schemes, sql) is not None


def test_label_guard_runs_before_the_database():
    async def run():
        with pytest.raises(ValueError, match="claims person-days"):
            await p._execute_one_attempt(
                MAWLWAI, ["Focus Plus"], {"resolved": {"block": "MAWLAI"}, "unresolved": []},
                "SELECT COUNT(*) AS person_days FROM curated.v_focus_plus WHERE lgd_block = 'MAWLAI'")
    asyncio.run(run())
