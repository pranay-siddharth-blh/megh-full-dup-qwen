"""
Fixes for the 15 Fail / Partial cases of the six-scheme test run of 2026-10-06
('Test Case Results - 30th Sep 26.xlsx', report reference_documents/
Test_Results_2026-10-06.xlsx). Every test calls the real function.
"""
import asyncio

import pytest

from app import pipeline as p
from app.session_store import Turn


# ── MGNREGA DATA-014: verifier read GROUP BY lgd_village_name as a filter ──────
_DATA014_ISSUE = ("semantic verifier flagged this query: Check 2: The RESOLVED ENTITIES block explicitly "
                  "states 'CONSTITUENCY ONLY: filter on assembly_constituency_name and NOTHING ELSE for "
                  "geography. Do NOT add lgd_block, lgd_district or village_code conditions'. However, the "
                  "SQL includes a GROUP BY clause on 'lgd_village_name' and 'village_code'")
_DATA014_SQL = ("SELECT lgd_village_name, village_code, SUM(persons_employed) AS persons_employed "
                "FROM curated.v_employment WHERE UPPER(assembly_constituency_name) = UPPER('TIKRIKILA') "
                "GROUP BY lgd_village_name, village_code HAVING SUM(persons_employed) > 0")


def test_groupby_complaint_on_a_village_list_is_discarded():
    assert p._verifier_groupby_complaint_is_false(
        _DATA014_ISSUE, "Which villages in Tikrikila assembly constituency received employment?",
        _DATA014_SQL) is True


def test_groupby_complaint_stands_when_the_question_is_not_a_list():
    assert p._verifier_groupby_complaint_is_false(
        _DATA014_ISSUE, "How many persons received employment in Tikrikila constituency?",
        _DATA014_SQL) is False


def test_groupby_complaint_stands_when_the_where_clause_filters_the_column():
    sql = _DATA014_SQL.replace("WHERE ", "WHERE village_code = 273237 AND ")
    assert p._verifier_groupby_complaint_is_false(
        _DATA014_ISSUE, "Which villages in Tikrikila assembly constituency received employment?", sql) is False


# ── MGNREGA DATA-021: AVG of a per-row ratio -> ratio of the sums ──────────────
def test_avg_of_ratio_becomes_ratio_of_sums():
    sql = ("SELECT ROUND(AVG(person_days::numeric / NULLIF(households_employed, 0)), 2) AS a "
           "FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' LIMIT 1")
    out = p._mgnrega_avg_of_ratio(["MGNREGA"], sql)
    assert "AVG(" not in out
    assert "SUM(person_days)::numeric / NULLIF(SUM(households_employed), 0)" in out


def test_avg_of_ratio_runs_inside_the_scheme_rewrites():
    sql = "SELECT AVG(person_days / households_employed) FROM curated.v_employment"
    out = asyncio.run(p._scheme_sql_rewrites("average person-days per household", ["MGNREGA"],
                                             {"resolved": {}}, sql))
    assert "AVG(" not in out and "SUM(person_days)" in out


def test_avg_of_a_single_measure_is_untouched():
    sql = "SELECT AVG(person_days) FROM curated.v_employment"
    assert p._mgnrega_avg_of_ratio(["MGNREGA"], sql) == sql
    assert p._mgnrega_avg_of_ratio(["PMAY-G"], "SELECT AVG(person_days / households_employed)") \
        == "SELECT AVG(person_days / households_employed)"


# ── General TC-024: "got employment" is MGNREGA vocabulary ──────────────────────
@pytest.mark.parametrize("q", ["How many households got employment in Dalu block in 2023-24?",
                               "How many people get employment in Dalu?"])
def test_got_employment_pins_mgnrega(q):
    assert p._shortcut_scheme(q) == ["MGNREGA"]


# ── CM Elevate Legacy TC-19: "sanctioned applications ... each scheme" ──────────
def test_sanctioned_applications_by_scheme_is_cm_elevate_legacy():
    assert p._shortcut_scheme("How many sanctioned applications are there for each scheme?") \
        == ["CM Elevate Legacy"]


def test_each_scheme_without_scheme_vocabulary_stays_cross_scheme():
    assert p._shortcut_scheme("What is the total amount disbursed under each scheme?") == list(p.SCHEME_CATALOG)


# ── General TC-007: "the two schemes" after naming two ──────────────────────────
class _Sess:
    def __init__(self, turn):
        self.last_turn = turn


def test_two_schemes_reuses_the_previous_turn():
    sess = _Sess(Turn(question="Tell me about MGNREGA and PMAY-G",
                      raw_question="Tell me about MGNREGA and PMAY-G", route="knowledge"))
    prev = p._previous_turn_schemes(sess)
    assert prev == ["MGNREGA", "PMAY-G"]
    out = p._scheme_comparison_answer("What is the difference between the two schemes?", prev)
    assert out and "MGNREGA" in out["answer"] and "PMAY-G" in out["answer"]


def test_two_schemes_with_no_history_still_asks():
    with pytest.raises(p.ClarificationNeeded):
        p._scheme_comparison_answer("What is the difference between the two schemes?", [])


# ── General TC-016: "What schemes can I get in Meghalaya?" lists them ───────────
def test_schemes_i_can_get_lists_the_schemes():
    out = p._scheme_recommendation_answer("What schemes can I get in Meghalaya?", None)
    if out is None:   # not read as a recommendation request at all: the listing path answers it
        out = p._scheme_listing_answer("What schemes can I get in Meghalaya?")
    assert out and "MGNREGA" in out["answer"] and "PMAY-G" in out["answer"]


# ── General TC-017: "West Garo Hils" ───────────────────────────────────────────
def test_hills_typo_is_corrected():
    assert p._correct_place_spelling("expenditure in West Garo Hils in 2023-24") \
        == "expenditure in West Garo Hills in 2023-24"
    assert p._correct_place_spelling("East Khasi Hill") == "East Khasi Hills"
    assert p._correct_place_spelling("West Garo Hills") == "West Garo Hills"


# ── General TC-020: keep only villages that hold MGNREGA data ───────────────────
def test_mgnrega_village_without_data_is_dropped(monkeypatch):
    async def fake_fetch(sql, params):
        return [{"village_code": 273807}]
    monkeypatch.setattr(p, "fetch_rows", fake_fetch)
    cands = [{"village_code": 1300001, "name": "Adugre", "block": "RERAPARA", "district": "SOUTH WEST GARO HILLS"},
             {"village_code": 273807, "name": "ADUGRE", "block": "BETASING", "district": "SOUTH WEST GARO HILLS"}]
    out = asyncio.run(p._mgnrega_villages_with_data(cands))
    assert [c["village_code"] for c in out] == [273807]


def test_mgnrega_village_filter_keeps_all_when_lookup_fails(monkeypatch):
    async def boom(sql, params):
        raise RuntimeError("db down")
    monkeypatch.setattr(p, "fetch_rows", boom)
    cands = [{"village_code": 1, "name": "A"}, {"village_code": 2, "name": "A"}]
    assert asyncio.run(p._mgnrega_villages_with_data(cands)) == cands


# ── General TC-022: a back-reference after a year pause ─────────────────────────
@pytest.mark.parametrize("q,hit", [("How much of that was spent on materials?", True),
                                   ("2023-24", False), ("all years combined", False)])
def test_backref_followup_regex(q, hit):
    assert bool(p._BACKREF_FOLLOWUP_RE.search(q)) is hit


# ── CM Elevate Legacy TC-31: CM Elevate can answer a constituency ──────────────
def test_cm_elevate_offers_constituency():
    assert "CM Elevate" in p._AC_CAPABLE_SCHEMES
    assert p._ac_dimension_available("How many CM-ELEVATE applications are mapped to Umsning?",
                                     ["CM Elevate"]) is True


def test_cm_elevate_constituency_join_columns_are_qualified():
    sql = ("SELECT COUNT(DISTINCT v.request_id) FROM curated.v_cm_elevate v JOIN curated.dim_geography g "
           "ON g.geography_key = v.geography_key WHERE UPPER(g.ac_name) = UPPER('Umsning') "
           "AND lgd_district = 'RI BHOI'")
    assert "v.lgd_district" in p._cm_legacy_qualify_shared_geo_cols(["CM Elevate"], sql)


def test_cm_elevate_constituency_prompt_line():
    from app.prompt_builder import _entities_block
    block = _entities_block({"resolved": {"assembly_constituency": "UMSNING"},
                             "display": {"assembly_constituency": "Umsning"}},
                            "How many CM-ELEVATE applications are mapped to Umsning?", ["CM Elevate"])
    assert "curated.v_cm_elevate v JOIN curated.dim_geography g" in block


# ── FOCUS TC-10 / TC-16 / TC-17: Focus Legacy beneficiaries and members ────────
def test_beneficiary_total_must_carry_four_measures():
    msg = p._focus_legacy_beneficiary_measures_missing(
        "How many total beneficiaries are available under the Focus Legacy scheme?", ["Focus Legacy"],
        "SELECT SUM(no_of_pg_members) AS beneficiaries FROM curated.v_focus_legacy")
    assert msg and "COUNT(DISTINCT pg_id)" in msg


def test_beneficiary_total_with_four_measures_passes():
    sql = ("SELECT COUNT(*) AS payments, COUNT(DISTINCT pg_id) AS producer_groups, "
           "SUM(no_of_pg_members) AS memberships, SUM(amount_disbursed) AS amount_disbursed "
           "FROM curated.v_focus_legacy")
    assert p._focus_legacy_beneficiary_measures_missing("total beneficiaries", ["Focus Legacy"], sql) is None


def test_beneficiary_breakdown_keeps_its_shape():
    sql = "SELECT financial_year_short, COUNT(*) FROM curated.v_focus_legacy GROUP BY 1"
    assert p._focus_legacy_beneficiary_measures_missing(
        "How many records of beneficiaries are available for each financial year?", ["Focus Legacy"], sql) is None


def test_member_total_says_memberships_paid_for():
    out = p._focus_legacy_answer_guarantees(
        "The total number of PG members recorded is 102,021.",
        "SELECT SUM(no_of_pg_members) AS memberships FROM curated.v_focus_legacy", [{"memberships": 102021}])
    assert "memberships paid for, not as distinct people" in out


def test_group_size_answer_gets_no_membership_note():
    out = p._focus_legacy_answer_guarantees(
        "Green Hills Women Group has 12 members.",
        "SELECT MAX(no_of_pg_members) AS group_size FROM curated.v_focus_legacy", [{"group_size": 12}])
    assert "memberships paid for" not in out


# ── CM Elevate Legacy TC-18: "each scheme" inside a CM Elevate conversation ─────
def test_each_scheme_after_a_cm_elevate_legacy_turn_means_its_sub_schemes():
    sess = _Sess(Turn(question="Tell me about CM Elevate Legacy",
                      raw_question="Tell me about CM Elevate Legacy", route="knowledge"))
    out = p._each_scheme_in_cm_thread("What is the total amount disbursed under each scheme?", sess)
    assert "CM Elevate Legacy" in out
    assert p._shortcut_scheme(out) == ["CM Elevate Legacy"]


def test_each_scheme_with_no_cm_conversation_is_unchanged():
    q = "What is the total amount disbursed under each scheme?"
    assert p._each_scheme_in_cm_thread(q, None) == q
    sess = _Sess(Turn(question="Tell me about MGNREGA", raw_question="Tell me about MGNREGA", route="knowledge"))
    assert p._each_scheme_in_cm_thread(q, sess) == q


# ── HTTP 502 on a dropped Qdrant keep-alive connection: one retry ──────────────
def test_rag_retrieve_retries_a_dropped_qdrant_connection(monkeypatch):
    from app import rag, llm, vectorstore
    calls = {"n": 0}

    async def fake_embed(q):
        return [[0.1] * 4]

    async def flaky_search(vec, top_k, scheme=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Server disconnected without sending a response.")
        return [{"text": "chunk", "score": 0.9}]

    monkeypatch.setattr(llm, "call_embedding", fake_embed)
    monkeypatch.setattr(vectorstore, "search", flaky_search)
    out = asyncio.run(rag.retrieve("Who is eligible for PMAY-G?"))
    assert calls["n"] == 2 and out and out[0]["text"] == "chunk"


# ── General TC-015: a phone number typed into the SQL ──────────────────────────
def test_helpline_question_is_knowledge():
    assert asyncio.run(p.classify_intent(
        "What is the toll-free helpline number for MGNREGA complaints in Meghalaya?")) == "KNOWLEDGE"


def test_a_query_with_no_table_never_runs():
    async def fake_generate(question, schemes, entity_result):
        return "SELECT '1800-103-4000' AS helpline_number LIMIT 1"
    d = p._new_data_turn("helpline number")
    d.update(schemes=["MGNREGA"], entity_result={"resolved": {}}, mg_det=None)
    orig = p.generate_sql
    p.generate_sql = fake_generate
    try:
        with pytest.raises(p.NoDataSourceQuery):
            asyncio.run(p._data_sql_stage(d))
    finally:
        p.generate_sql = orig


def test_a_normal_query_passes_the_table_check():
    assert p._SQL_READS_A_TABLE.search("SELECT SUM(total_exp) FROM curated.v_expenditure")


# ── MGNREGA DATA-014: a latest-year filter must be stated ──────────────────────
_LATEST_SQL = ("SELECT lgd_village_name, SUM(persons_employed) FROM curated.v_employment WHERE "
               "year_key = (SELECT MAX(year_key) FROM curated.v_employment) GROUP BY 1")


def test_latest_year_filter_is_stated(monkeypatch):
    async def fake_fetch(sql, params):
        assert sql == "SELECT MAX(year_key) AS y FROM curated.v_employment"
        return [{"y": 2025}]
    monkeypatch.setattr(p, "fetch_rows", fake_fetch)
    out = asyncio.run(p._latest_year_guarantee("45 villages received employment.", _LATEST_SQL))
    assert out.endswith("This is for FY 2025-26, the latest financial year in the data.")


def test_latest_year_note_not_added_when_the_answer_names_the_year(monkeypatch):
    async def boom(sql, params):
        raise AssertionError("no lookup expected")
    monkeypatch.setattr(p, "fetch_rows", boom)
    a = "45 villages received employment in FY 2025-26."
    assert asyncio.run(p._latest_year_guarantee(a, _LATEST_SQL)) == a


def test_group_count_named_beneficiaries_is_sent_back():
    sql = ("SELECT COUNT(*) AS payments, COUNT(DISTINCT pg_id) AS beneficiaries, "
           "SUM(no_of_pg_members) AS memberships, SUM(amount_disbursed) AS amount_disbursed "
           "FROM curated.v_focus_legacy")
    msg = p._focus_legacy_beneficiary_measures_missing("total beneficiaries", ["Focus Legacy"], sql)
    assert msg and "producer groups" in msg


@pytest.mark.parametrize("q,hit", [
    ("What is the toll-free helpline number for MGNREGA complaints in Meghalaya?", True),
    ("Where do I file a grievance under PMAY-G?", True),
    ("How many job cards were issued in Dalu?", False),
])
def test_contact_cue(q, hit):
    assert bool(p._CONTACT_INFO_CUE.search(q)) is hit


# ── CM-ELEVATE-OFF-024: "<programme> or across CM ELEVATE" needs both scopes ────
_OFF024_Q = "How many applications have been withdrawn under the Piggery Development Scheme or across CM ELEVATE in Ri Bhoi?"


def test_programme_or_all_with_a_tautology_is_sent_back():
    sql = ("SELECT COUNT(*) FILTER (WHERE is_withdraw) AS withdrawn_applications, COUNT(*) AS total_applications "
           "FROM curated.v_cm_elevate WHERE (scheme_name = 'Meghalaya Piggery Development Scheme' OR scheme_name IN "
           "(SELECT scheme_name FROM curated.dim_cm_elevate_scheme)) AND lgd_district = 'RI BHOI'")
    assert p._cme_programme_or_all_scopes_missing(_OFF024_Q, ["CM Elevate"], sql)


def test_programme_or_all_with_two_rows_passes():
    sql = ("SELECT 'Piggery' AS scope, COUNT(*) FILTER (WHERE is_withdraw) FROM curated.v_cm_elevate WHERE "
           "scheme_name = 'Meghalaya Piggery Development Scheme' AND lgd_district = 'RI BHOI' UNION ALL SELECT "
           "'All', COUNT(*) FILTER (WHERE is_withdraw) FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'")
    assert p._cme_programme_or_all_scopes_missing(_OFF024_Q, ["CM Elevate"], sql) is None


def test_single_scope_question_is_untouched():
    assert p._cme_programme_or_all_scopes_missing(
        "How many applications have been withdrawn under the Piggery Development Scheme in Ri Bhoi?",
        ["CM Elevate"], "SELECT COUNT(*) FROM curated.v_cm_elevate") is None


def test_beneficiary_total_is_built_with_four_measures_on_the_model_filters():
    sql = ("SELECT SUM(no_of_pg_members) AS beneficiaries FROM curated.v_focus_legacy f "
           "WHERE f.lgd_district = 'WEST GARO HILLS' LIMIT 1")
    out = p._focus_legacy_beneficiary_four_measures("How many total beneficiaries are there?", ["Focus Legacy"], sql)
    assert out.startswith(p._FL_FOUR_SELECT)
    assert "WHERE f.lgd_district = 'WEST GARO HILLS'" in out and "LIMIT" not in out
    assert p._focus_legacy_beneficiary_measures_missing("total beneficiaries", ["Focus Legacy"], out) is None


def test_beneficiary_breakdown_is_not_rebuilt():
    sql = "SELECT financial_year_short, COUNT(*) FROM curated.v_focus_legacy GROUP BY 1"
    assert p._focus_legacy_beneficiary_four_measures("beneficiaries each year", ["Focus Legacy"], sql) == sql


def test_cm_elevate_constituency_drilldown_reads_its_own_data():
    from app import entity_resolver as er
    assert "v_cm_elevate v JOIN curated.dim_geography" in er._AC_CONTENTS_SQL["CM Elevate"]
    assert er.AC_CONTENTS_SOURCE["CM Elevate"] == "CM Elevate applications data"
    c = p._ac_drilldown_clarification("How many CM-ELEVATE applications are mapped to Umsning?", "UMSNING",
                                      {"districts": ["RI BHOI"], "blocks": ["UMSNING", "UMLING"], "villages": 39},
                                      "CM Elevate")
    assert "CM Elevate applications data" in c.question and "MGNREGA" not in c.question
