"""
Accuracy gold bank fixes (2026-11-11 / 12; KI-670..KI-686). Every case here was a wrong or missing figure,
or a wrong route, found by the LIVE gold bank `tests/accuracy/run_gold.py` (212 cases, truth recomputed with
independent read-only SQL). Each test calls the REAL pipeline function on the exact words / SQL that failed.

No model or DB (the metric catalogue's match is stubbed where needed).
    python -m pytest tests/test_accuracy_gold_fixes_2026_11_11.py -q
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import entity_resolver  # noqa: E402
from app import pipeline as p  # noqa: E402
from app import sql_ast  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
def _places():
    entity_resolver.load_all()      # the place index the follow-up checks read (YAML, no DB)


def _prev(question, schemes, route="data"):
    return SimpleNamespace(question=question, schemes=list(schemes), route=route)


# ── KI-673: "Focus Plus" is one scheme name, not two asks ────────────────────
def test_focus_plus_is_not_cut_into_two_asks():
    q = "Which district received the highest total Focus Plus disbursement?"
    assert len(p._c17_sub_asks(q)) == 1


def test_a_real_plus_joiner_still_cuts():
    # the joiner itself still works where it is not the scheme's name
    parts = p._c17_sub_asks("How many MGNREGA person-days plus the expenditure in 2023-24?")
    assert len(parts) == 2


# ── KI-674: the rephraser's money wording is a figure question, not the list of years ──
@pytest.mark.parametrize("q", [
    "How much money was remitted under Focus Legacy by financial year?",
    "How much was paid under Focus Legacy by financial year?",
])
def test_money_by_financial_year_is_not_the_years_list(q):
    assert not p._is_years_list_question(q)


def test_the_plain_years_list_is_still_the_list():
    assert p._is_years_list_question("Which financial years does Focus Legacy have?")


# ── KI-675: a village count and another figure are two asks (MGNREGA) ────────
def test_villages_and_person_days_are_two_asks():
    plan = p._c17_ask_plan("How many villages had MGNREGA activity and how many person-days were generated in total?")
    assert plan is not None and len(plan) == 2
    assert "villages" in plan[0].lower() and "MGNREGA" in plan[0]
    assert "person-days" in plan[1]


# ── KI-677: a chart kind the chat cannot draw is named as not available ─────
def test_radar_chart_is_named_not_available_and_not_claimed():
    result = {"answer": "This radar chart displays MGNREGA person-days by district."}
    p._c13_undrawn_chart_note(result, "Show MGNREGA person-days by district as a radar chart?",
                              "Show MGNREGA person-days by district as a radar chart")
    a = result["answer"]
    assert "This chart displays" in a and "This radar chart" not in a
    assert "a radar chart is not available here" in a


def test_a_drawable_chart_gets_no_note():
    result = {"answer": "Here are the figures as a pie chart."}
    p._c13_undrawn_chart_note(result, "MGNREGA person-days by district as a pie chart", "")
    assert "not available" not in result["answer"]


# ── KI-678: a CM Elevate Legacy SANCTIONED count is not the catalogue's application count ──
def test_cml_sanctioned_count_skips_the_application_measure(monkeypatch):
    from app import metric_catalog
    metric = SimpleNamespace(key="cml_sanctioned_applicants", expression="COUNT(DISTINCT application_number)")
    monkeypatch.setattr(metric_catalog, "mode", lambda: "on")
    monkeypatch.setattr(metric_catalog, "match", lambda q, s: SimpleNamespace(status="matched", metric=metric))
    out = p._metric_catalog_plan("How many CM Elevate Legacy applicants were sanctioned in 2024-25?",
                                 ["CM Elevate Legacy"], {"resolved": {}})
    assert out["query"] is None and "COUNT(sanctioned_amount)" in out["reason"]


# ── KI-679: "are done" is completed (PMAY-G) ────────────────────────────────
def test_pmay_are_done_reads_completed():
    assert p._PMAY_M["completed"].search("how many pmay houses are done in east khasi hills")
    assert p._PMAY_M["completed"].search("how many houses got done in Ri Bhoi")


# ── KI-680: sanction_date IS NOT NULL is the registrations exclusion (D-060) ─
def test_sanction_date_not_null_is_dropped_like_not_is_placeholder():
    sql = ("SELECT lgd_district, COUNT(*) AS houses FROM curated.v_pmay WHERE sanction_date IS NOT NULL "
           "GROUP BY lgd_district ORDER BY houses DESC")
    out = p._pmay_count_placeholders(["PMAY-G"], sql)
    assert "sanction_date" not in out and "GROUP BY" in out


def test_other_not_null_filters_are_kept():
    sql = "SELECT COUNT(*) FROM curated.v_pmay WHERE amount_released IS NOT NULL"
    assert p._pmay_count_placeholders(["PMAY-G"], sql) == sql


# ── KI-681 / KI-670: a measure change or an "only …" filter keeps the breakdown ─
def test_measure_change_keeps_the_year_breakdown():
    prev = _prev("What was MGNREGA expenditure in each financial year?", ["MGNREGA"])
    assert p._c14_carried_breakdown("and person-days?", prev) == " by financial year"


def test_measure_change_with_its_own_breakdown_keeps_its_own():
    prev = _prev("What was MGNREGA expenditure in each financial year?", ["MGNREGA"])
    assert p._c14_carried_breakdown("and person-days by district?", prev) == ""


def test_only_filter_keeps_the_district_breakdown():
    prev = _prev("Tell me about PMAY-G houses by district.", ["PMAY-G"])
    out = p._c14_only_filter_keeps_breakdown("Only the completed ones.", "How many PMAY-G houses are completed?", prev)
    assert out.endswith("by district?")


def test_only_filter_with_a_place_is_left_alone():
    prev = _prev("Tell me about PMAY-G houses by district.", ["PMAY-G"])
    rw = "How many PMAY-G houses are completed in Ri Bhoi?"
    assert p._c14_only_filter_keeps_breakdown("Only Ri Bhoi.", rw, prev) == rw


# ── KI-682: a short refinement after a data answer stays a data question ────
def test_short_refinement_after_data_stays_data():
    prev = _prev("Focus Legacy producer groups in West Garo Hills", ["Focus Legacy"])
    assert p._c14_data_refinement("and in East Khasi Hills?", prev)
    assert p._c14_data_refinement("Only the completed ones.", prev)


def test_a_how_does_it_work_question_is_not_a_refinement():
    prev = _prev("Focus Legacy producer groups in West Garo Hills", ["Focus Legacy"])
    assert not p._c14_data_refinement("What is the eligibility for Focus Legacy?", prev)
    assert not p._c14_data_refinement("and in East Khasi Hills?", _prev("x", ["Focus Legacy"], route="knowledge"))


# ── KI-683: "only <scheme>" after a comparison of schemes ───────────────────
def test_only_one_scheme_of_a_comparison():
    prev = _prev("Compare MGNREGA and PMAY-G beneficiaries", ["MGNREGA", "PMAY-G"])
    out = p._c14_one_scheme_of_comparison("only PMAY-G", prev)
    assert out is not None and "PMAY-G" in out and "MGNREGA" not in out and "ompare" not in out
    assert "beneficiaries" in out


def test_only_scheme_not_in_the_comparison_is_not_rewritten():
    prev = _prev("Compare MGNREGA and PMAY-G beneficiaries", ["MGNREGA", "PMAY-G"])
    assert p._c14_one_scheme_of_comparison("only Focus Plus", prev) is None
    assert p._c14_one_scheme_of_comparison("PMAY-G houses in Ri Bhoi", prev) is None


# ── KI-684: a terse scheme + measure + place question asks for a figure ────
def test_terse_figure_question_is_data():
    assert p._c13_terse_figure("PMAY-G completed EKH")
    assert p._c13_terse_figure("MGNREGA person days Ri Bhoi")


def test_terse_question_without_a_place_or_measure_is_not_forced():
    assert not p._c13_terse_figure("PMAY-G eligibility")
    assert not p._c13_terse_figure("PMAY-G completed")


# ── KI-685: a typed reply to the top-N pause ─────────────────────────────────
@pytest.mark.parametrize("reply,n", [("top 3", 3), ("3", 3), ("the top five", 5), ("all of them", 0),
                                     ("show me everything", 0), ("Ri Bhoi", None), ("how many houses", None)])
def test_topn_reply(reply, n):
    assert p._c14_topn_reply(reply) == n


# ── KI-672: "how many schemes" counts scheme_name; the record count makes it a data question ──
def test_cme_scheme_count_column_counts_scheme_name():
    sql = ("SELECT COUNT(DISTINCT request_id) AS applications, COUNT(DISTINCT request_id) AS schemes "
           "FROM curated.v_cm_elevate WHERE data_verified = 'Valid'")
    out = p._cm_elevate_scheme_count_column(["CM Elevate"], sql)
    assert "COUNT(DISTINCT scheme_name) AS schemes" in out and "COUNT(DISTINCT request_id) AS applications" in out


def test_record_count_question_is_not_a_design_count():
    q = "How many CM Elevate applications are there and how many schemes do they cover?"
    assert p._knowledge_form_question(q) is None


# ── KI-671: the default (valid-only) count is called valid ───────────────────
def test_valid_applications_are_called_valid():
    q = "How many CM Elevate applications are there in total?"
    sql = "SELECT COUNT(DISTINCT request_id) AS total FROM curated.v_cm_elevate WHERE data_verified = 'Valid'"
    a = p._cme_valid_wording(q, sql, "There are 7,375 total CM Elevate applications.")
    assert a == "There are 7,375 valid CM Elevate applications."


def test_an_all_applications_count_is_not_called_valid():
    q = "How many CM Elevate applications are there in total?"
    sql = "SELECT COUNT(DISTINCT request_id) AS total FROM curated.v_cm_elevate"
    a = "There are 8,938 CM Elevate applications."
    assert p._cme_valid_wording(q, sql, a) == a


# ── KI-686: a false check-2 complaint about a programme filtered verbatim ──
ISSUE = ("Check 2: The RESOLVED ENTITIES block specifies scheme_name = 'Meghalaya Piggery Development Scheme', but "
         "the SQL uses scheme_name in the WHERE clause. However, the schema shows that "
         "curated.v_cm_elevate_disbursement does not have a scheme_name column.")
PIG_SQL = ("SELECT COUNT(*) AS records FROM curated.v_cm_elevate_disbursement "
           "WHERE scheme_name = 'Meghalaya Piggery Development Scheme'")
PIG = {"cm_scheme": "Meghalaya Piggery Development Scheme"}


def test_programme_check2_is_discarded_when_filtered_verbatim():
    assert p._verifier_programme_filter_is_false(ISSUE, ["CM Elevate Legacy"], PIG, PIG_SQL)


@pytest.mark.parametrize("issue,resolved,sql", [
    (ISSUE, PIG, PIG_SQL.replace("Piggery Development", "Poultry Farming")),         # another programme
    (ISSUE, PIG, PIG_SQL + " OR scheme_name = 'Meghalaya Goat Farming Scheme'"),     # an extra one
    (ISSUE, {}, PIG_SQL),                                                           # nothing resolved
    (ISSUE.replace("Check 2", "Check 3"), PIG, PIG_SQL),                             # another check
])
def test_programme_check2_still_raises_when_it_could_be_right(issue, resolved, sql):
    assert not p._verifier_programme_filter_is_false(issue, ["CM Elevate Legacy"], resolved, sql)


def test_programme_check2_only_for_the_cm_elevate_datasets():
    assert not p._verifier_programme_filter_is_false(ISSUE, ["MGNREGA"], PIG, PIG_SQL)


def test_sql_ast_still_parses_the_cases():
    assert sql_ast.is_parseable(PIG_SQL)


# ── KI-687: a Focus Plus block BREAKDOWN is on block_name_raw ───────────────
FP_BLOCKS = ("SELECT lgd_block, SUM(amount_disbursed) AS amount_raw FROM curated.v_focus_plus "
             "WHERE lgd_district = 'NORTH GARO HILLS' GROUP BY lgd_block ORDER BY amount_raw DESC NULLS LAST LIMIT 100")


def test_focus_plus_block_breakdown_moves_to_block_name_raw():
    out = p._focusplus_block_breakdown_on_raw(["Focus Plus"], FP_BLOCKS)
    assert "GROUP BY UPPER(block_name_raw)" in out and "UPPER(block_name_raw) AS lgd_block" in out
    assert "lgd_district = 'NORTH GARO HILLS'" in out


@pytest.mark.parametrize("sql", [
    "SELECT lgd_block, COUNT(*) FROM curated.v_focus_plus WHERE lgd_block = 'ADOKGRE' GROUP BY lgd_block",
    "SELECT lgd_village_name, lgd_block, COUNT(*) FROM curated.v_focus_plus GROUP BY lgd_village_name, lgd_block",
    "SELECT UPPER(block_name_raw), COUNT(*) FROM curated.v_focus_plus GROUP BY 1",
    "SELECT COUNT(*) FROM curated.v_focus_plus WHERE lgd_block = 'DALU'",
])
def test_focus_plus_block_choices_made_on_purpose_are_kept(sql):
    assert p._focusplus_block_breakdown_on_raw(["Focus Plus"], sql) == sql


def test_block_breakdown_rule_is_focus_plus_only():
    sql = FP_BLOCKS.replace("v_focus_plus", "v_pmay")
    assert p._focusplus_block_breakdown_on_raw(["PMAY-G"], sql) == sql


# ── D-046 / D-047: no regular expressions in the app (one had come back in cm_elevate.py) ──
def test_no_regex_module_anywhere_in_app():
    root = Path(__file__).resolve().parents[1] / "app"
    bad = []
    for f in root.rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if s in ("import re", "import regex") or s.startswith(("import re ", "import re,", "from re import",
                                                                   "import regex ", "from regex import")) \
                    or "re.compile(" in s.replace(" ", ""):
                bad.append(f"{f.relative_to(root)}:{n}")
    assert not bad, bad


@pytest.mark.parametrize("q,n", [("pending at level 2", 2), ("pending in level-1 in Ri Bhoi", 1), ("level2", 2),
                                 ("level 0", 0), ("levels pending", None), ("toplevel 3", None)])
def test_cme_level_number_without_a_regex(q, n):
    assert p._cme_level_number(q) == n


# ── KI-689: CM Elevate "rejected" is the plain file_status column's Rejected (approved is still not recorded) ──
_CME_OPEN = {"curated.v_cm_elevate": [{"column": c} for c in ("request_id", "data_verified", "current_file_status",
                                                              "current_level", "file_status")]}
_CME_LOCKED = {"curated.v_cm_elevate": [{"column": c} for c in ("request_id", "data_verified", "current_file_status")]}


def test_rejected_is_held_by_cm_elevate_once_file_status_is_readable(monkeypatch):
    from app import schema_introspect as si
    monkeypatch.setattr(si, "live_columns", lambda: _CME_OPEN)
    assert p._measures_not_held("How many CM Elevate applications were rejected in Ri Bhoi?", ["CM Elevate"]) == []
    gaps = p._measures_not_held("How many CM Elevate applications were approved?", ["CM Elevate"])
    assert [g[0] for g in gaps] == ["approval or rejection decisions"]
    gap = p._measure_not_held_gap("How many CM Elevate applications were approved?", ["CM Elevate"])
    assert gap is not None and "doesn't record approval decisions" in gap.question


def test_rejected_keeps_the_pause_while_file_status_is_locked(monkeypatch):
    from app import schema_introspect as si
    monkeypatch.setattr(si, "live_columns", lambda: _CME_LOCKED)
    gaps = p._measures_not_held("How many CM Elevate applications were rejected?", ["CM Elevate"])
    assert [g[0] for g in gaps] == ["approval or rejection decisions"]


def test_rejected_count_and_answer(monkeypatch):
    from app import schema_introspect as si
    monkeypatch.setattr(si, "live_columns", lambda: _CME_OPEN)
    q = "How many CM Elevate applications were rejected in Ri Bhoi?"
    sql, params, _ = p._cme_workflow_query(q, {"district": "RI BHOI"})
    assert "FILTER (WHERE file_status = 'Rejected') AS rejected" in sql and params == ["RI BHOI"]
    rows = [{"pending": 2026, "sent_back": 2, "rejected": 17, "forward": 2035, "resubmit": 1, "sendback": 2,
             "applications": 2038}]
    a = p._cme_sector_answer(q, sql, rows, {"district": "Ri Bhoi"})
    assert a.startswith("17 CM Elevate applications in Ri Bhoi have the file status Rejected (of 2,038 valid applications).")


# ── KI-690: an unasked lender filter on a CM Elevate Legacy loan figure ──────
LOAN_SQL = ("SELECT ROUND(SUM(total_loan_disbursement) / 1e7, 2) AS loan_cr FROM curated.v_cm_elevate_disbursement "
            "WHERE lgd_district = 'WEST GARO HILLS' AND loan_entity = 'Bank' AND total_loan_disbursement > 0")


def test_unasked_lender_filter_is_taken_out():
    out = p._cm_legacy_unasked_lender_filter("How much loan was disbursed under CM Elevate Legacy in West Garo Hills?",
                                             ["CM Elevate Legacy"], LOAN_SQL)
    assert "loan_entity" not in out and "lgd_district = 'WEST GARO HILLS'" in out


@pytest.mark.parametrize("q", ["How much bank loan was disbursed under CM Elevate Legacy?",
                               "CM Elevate Legacy loan disbursed through LIFCOM", "CM Elevate Legacy loans by lender"])
def test_a_named_lender_stays(q):
    assert p._cm_legacy_unasked_lender_filter(q, ["CM Elevate Legacy"], LOAN_SQL) == LOAN_SQL


# ── KI-691: "and <other scheme> <measure> there?" after one place's answer ──
def test_other_scheme_there_is_that_place():
    prev = _prev("PMAY-G houses completed in East Garo Hills", ["PMAY-G"])
    assert p._c14_other_scheme_there("and Focus Plus beneficiaries there?", prev) == \
        "Focus Plus beneficiaries in East Garo Hills?"
    assert p._c14_other_scheme_there("what about MGNREGA households employed over there?", prev) == \
        "MGNREGA households employed in East Garo Hills?"


@pytest.mark.parametrize("q", ["how many Focus Plus beneficiaries are there?",      # existential, not a place
                               "and Focus Plus there?",                            # no measure
                               "and PMAY-G houses there?",                         # the same scheme
                               "and Focus Plus beneficiaries in Ri Bhoi?"])        # its own place
def test_other_scheme_there_leaves_the_rest(q):
    prev = _prev("PMAY-G houses completed in East Garo Hills", ["PMAY-G"])
    assert p._c14_other_scheme_there(q, prev) is None


def test_other_scheme_there_never_carries_a_year():
    prev = _prev("PMAY-G houses completed in East Garo Hills in 2023-24", ["PMAY-G"])
    assert p._c14_other_scheme_there("and Focus Plus beneficiaries there?", prev) is None
