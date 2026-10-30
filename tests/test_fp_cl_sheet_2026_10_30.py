"""Focus + / CM Elevate Legacy sheet re-test 2026-10-30 (Test Case Results - 30th Sep 26.xlsx).
Regression tests for the defects found live; each calls the real function. No DB, no model.

- FOCUS-007 / 018 / 028: "under Tranch 1" (the stored tranche_label spelling), rephrased to
  "in Tranch 1", was a place "Tranch" that matched nothing -> unknown-place pause.
- FOCUS-004: `block_name_raw = 'MAWKYNREW'` (no UPPER) matched nothing (stored "Mawkynrew").
- TC-35: "applications across South West Garo Hills and …" -> the spelling layer read
  "across South West" as South West Garo Hills -> "which district is 'garo hills'?".
- TC-31: "William Nagar constituency" was rewritten to the block "Williamnagar" -> block or AC?
- TC-36: a district summary of applications, sanctioned cases and total disbursement listed
  three other measures in SQL order and dropped the total disbursed the question asked for.
"""
import asyncio

from app import entity_resolver as er
from app import pipeline as p
from app import spelling as sp

er.load_all()
sp.reload()


# ── FOCUS-007 / 018 / 028 ─────────────────────────────────────────────────────

def test_tranch_is_not_an_unknown_place():
    for q in ("How much amount was disbursed under Focus Plus in Tranch 1?",
              "Give me the Focus Plus status breakdown in Tranch 4 - Feb-March.",
              "Compare Focus Plus disbursements in Tranch 1 and Tranch 2."):
        assert sp.unresolved_place(q) is None, q


def test_unknown_place_still_said():
    assert sp.unresolved_place("Focus Plus beneficiaries in zorbatown")["typed"] == "zorbatown"


def test_known_word_reads_the_few_shot_term_map():
    assert sp._known_word("Tranch")
    assert not sp._known_word("Mawkynrew")        # a place stays a place


# ── FOCUS-004 ─────────────────────────────────────────────────────────────────

def _guard(sql, monkeypatch):
    async def raw():
        return {"MAWKYNREW", "MYLLIEM", "SHILLONG-MUNICIPAL BOARD"}
    monkeypatch.setattr(p, "_focusplus_raw_block_names", raw)
    return asyncio.run(p._focusplus_lgd_only_block(["Focus Plus"], sql))


def test_known_block_without_upper_is_compared_in_upper_case(monkeypatch):
    base = "SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE "
    for where in ("block_name_raw = 'MAWKYNREW'", "block_name_raw = 'Mawkynrew'"):
        out = _guard(base + where, monkeypatch)
        assert "UPPER(block_name_raw) = 'MAWKYNREW'" in out, out


def test_correct_block_filters_unchanged(monkeypatch):
    base = "SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE "
    for where in ("UPPER(block_name_raw) = 'MYLLIEM'", "block_name_raw ILIKE 'mylliem'"):
        assert _guard(base + where, monkeypatch) == base + where
    # KI-361 snap-back still works
    out = _guard(base + "UPPER(block_name_raw) = 'SHILLONG-MUNICIPAL_BOARD'", monkeypatch)
    assert "'SHILLONG-MUNICIPAL BOARD'" in out


# ── TC-35 ─────────────────────────────────────────────────────────────────────

def test_ordinary_word_is_not_part_of_a_place():
    q = ("Compare the number of sanctioned CM Elevate Legacy applications across South West Garo Hills "
         "and West Jaintia Hills.")
    assert sp.normalise(q).text == q


def test_typo_after_an_ordinary_word_still_corrected():
    assert sp.normalise("applications among south west khasi hils").text == \
        "applications among South West Khasi Hills"
    assert sp.normalise("compare between west garo hils and ri bhoi").text.startswith(
        "compare between West Garo Hills")


# ── TC-31 ─────────────────────────────────────────────────────────────────────

def test_constituency_spelling_is_not_rewritten_to_a_block():
    q = "How many CM Elevate Legacy applications are mapped to William Nagar constituency?"
    assert sp.normalise(q).text == q
    # the block reading is unchanged when the user says "block"
    assert sp.normalise("applications in William Nagar block").text == "applications in Williamnagar block"


# ── TC-36 ─────────────────────────────────────────────────────────────────────

_TC36_SQL = ("SELECT COALESCE(lgd_district, 'ALL DISTRICTS') AS lgd_district, COUNT(*) AS records, "
             "COUNT(sanctioned_amount) AS sanctioned_records, ROUND(SUM(sanctioned_amount) / 1e7, 2) AS sanctioned_cr, "
             "ROUND(SUM(total_subsidy_disbursement) / 1e7, 2) AS subsidy_cr, "
             "ROUND(SUM(total_loan_disbursement) / 1e7, 2) AS loan_cr, "
             "ROUND(SUM(total_disbursement) / 1e7, 2) AS total_disbursed_cr "
             "FROM curated.v_cm_elevate_disbursement GROUP BY lgd_district ORDER BY records DESC")
_TC36_ROWS = [
    {"lgd_district": "WEST GARO HILLS", "records": 493, "sanctioned_records": 493, "sanctioned_cr": 25.20,
     "subsidy_cr": 9.88, "loan_cr": 11.02, "total_disbursed_cr": 20.90},
    {"lgd_district": "RI BHOI", "records": 486, "sanctioned_records": 485, "sanctioned_cr": 16.33,
     "subsidy_cr": 4.55, "loan_cr": 6.01, "total_disbursed_cr": 10.56},
    {"lgd_district": "EAST JAINTIA HILLS", "records": 35, "sanctioned_records": 35, "sanctioned_cr": 4.13,
     "subsidy_cr": 1.55, "loan_cr": 1.77, "total_disbursed_cr": 3.32},
]


def test_summary_lists_the_measures_the_question_asks_for():
    q = ("Give me a district-wise summary of applications, sanctioned cases and total disbursement "
         "under CM Elevate Legacy.")
    shape = p._answer_shape(q, _TC36_SQL, _TC36_ROWS)
    line = p._c12s_e9_extras(shape, _TC36_ROWS[0], question=q)
    assert "20.90" in line, line                     # total disbursed, asked for
    assert "sanctioned" in line.lower()


def test_extras_keep_sql_order_when_nothing_is_named():
    shape = p._answer_shape("district-wise summary", _TC36_SQL, _TC36_ROWS)
    assert p._c12s_e9_extras(shape, _TC36_ROWS[0], question="district-wise summary") == \
        p._c12s_e9_extras(shape, _TC36_ROWS[0])


# ── FP-P02 (permutation run) ──────────────────────────────────────────────────

def test_rephrase_may_not_turn_a_count_into_an_amount():
    o = "In Ri Bhoi, how many people got Focus Plus money?"
    assert p._rephrase_violation(o, "How much money was given under Focus Plus in Ri Bhoi?") == "measure"
    # a "how much" question rephrased as "how much" is not touched by this rule
    assert p._rephrase_violation("how much focus plus money was given in ri bhoi",
                                 "How much money was given under Focus Plus in Ri Bhoi?") is None


# ── MT-16 (permutation run) ───────────────────────────────────────────────────

def test_rescoping_follow_up_is_not_a_definition_question():
    for q in ("What is it for the whole state?", "What is it for Ri Bhoi?", "What is it in 2022-23?"):
        assert p._typed_intent(q) is None, q          # the rewrite is classified instead
    for q in ("What is it?", "What is Focus Plus?", "What is the eligibility for Focus Plus in Ri Bhoi?"):
        assert p._typed_intent(q) == "KNOWLEDGE", q


def test_verifier_money_sum_on_a_count_question_is_discarded():
    issue = ("Check 2: … the question asks for 'how many people got Focus Plus money across all financial years', "
             "which implies a monetary aggregation (e.g., SUM of amount_disbursed), not a count of beneficiaries.")
    count_sql = ("SELECT COUNT(DISTINCT beneficiary_key) AS beneficiaries FROM curated.v_focus_plus "
                 "WHERE lgd_district = 'RI BHOI'")
    q = "In Ri Bhoi, how many people got Focus Plus money across all financial years"
    assert p._verifier_wants_amount_for_count(issue, q, count_sql)
    # a "how much" question, or SQL that already sums, keeps the complaint
    assert not p._verifier_wants_amount_for_count(issue, "how much Focus Plus money did Ri Bhoi get", count_sql)
    assert not p._verifier_wants_amount_for_count(
        issue, q, "SELECT COUNT(*), SUM(amount_disbursed) FROM curated.v_focus_plus")
    # a complaint that is not about money keeps going to repair
    assert not p._verifier_wants_amount_for_count("check 4: it sums a column unrelated to the question", q, count_sql)


def test_block_filtered_on_lgd_block_moves_to_block_name_raw(monkeypatch):
    base = "SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE "
    for where in ("lgd_block = 'MAWKYNREW'", "UPPER(lgd_block) = 'MAWKYNREW'"):
        out = _guard(base + where, monkeypatch)
        assert "UPPER(block_name_raw) = 'MAWKYNREW'" in out and "lgd_block" not in out, out
    # a village question keeps lgd_block (village rows are mapped by LGD)
    v = base + "lgd_block = 'MAWKYNREW' AND village_code = 123"
    assert _guard(v, monkeypatch) == v
    # an LGD-only block (no raw rows) is left on lgd_block
    lgd_only = base + "lgd_block = 'MAWLAI'"
    assert _guard(lgd_only, monkeypatch) == lgd_only


def test_verifier_case_form_complaint_on_a_filtered_block_is_cosmetic():
    issue = ("Check 2 violation: The RESOLVED ENTITY 'block_name_raw' = 'MAWKYNREW' is not present in the WHERE "
             "clause. The SQL filters on UPPER(block_name_raw) = 'MAWKYNREW', but the resolved entity value should "
             "be used verbatim as 'MAWKYNREW' without the UPPER() wrapper.")
    sql = "SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = 'MAWKYNREW'"
    assert p._verifier_complaint_is_cosmetic(issue, {"block": "MAWKYNREW"}, sql)
    # the block really missing: the complaint stands
    assert not p._verifier_complaint_is_cosmetic(issue, {"block": "MAWKYNREW"},
                                                 "SELECT SUM(amount_disbursed) FROM curated.v_focus_plus")


def test_shaped_fallback_lines_follow_the_question(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ANSWER_TEMPLATES_ENABLED", True)
    q = ("Give me a district-wise summary of applications, sanctioned cases and total disbursement "
         "under CM Elevate Legacy.")
    shape = p._answer_shape(q, _TC36_SQL, _TC36_ROWS)
    out = p._shaped_fallback(shape, _TC36_ROWS, ["CM Elevate Legacy"], {}, q)
    assert "20.90" in out, out                           # WEST GARO HILLS total disbursed


# ── TC-12 (full after-fix run): Sericulture spinning / weaving on the applications dataset ──

def test_sericulture_split_question_is_told_there_is_no_split():
    sql = ("SELECT COUNT(DISTINCT request_id) AS applications FROM curated.v_cm_elevate "
           "WHERE scheme_name = 'Meghalaya Sericulture & Weaving Scheme'")
    ans = "The Meghalaya Sericulture & Weaving Scheme recorded 14 applications for spinning."
    for q in ("How many applications are recorded under Meghalaya Sericulture & Weaving Scheme (spinning)?",
              "How many applications are recorded under Meghalaya Sericulture & Weaving Scheme(weaving) in CM-ELEVATE?"):
        out = p._cme_sericulture_split_note(q, sql, ans)
        assert out.startswith("Note: CM Elevate (applications) holds Sericulture as one scheme"), out
        assert "for spinning" not in out and "recorded 14 applications." in out, out
    # the plain scheme name (its own "Weaving") is not a split question
    q = "How many applications are recorded under Meghalaya Sericulture & Weaving Scheme?"
    assert p._cme_sericulture_split_note(q, sql, ans) == ans


# ── all-constituencies run (Focus Plus): KI-657 / KI-658 / KI-659 ─────────────

def test_constituency_name_with_level_word_is_not_split():
    q = "How many focus plus beneficiaries are there in Rambrai jyrngam constituency?"
    assert sp.normalise(q).text == q                     # never "Rambrai Jirang constituency"
    assert sp.normalise("applications in mawsinram constituency").text == "applications in Mawsynram constituency"


def test_focus_plus_ac_name_compared_in_upper_case():
    for where in ("ac_name = 'EAST SHILLONG'", "ac_name = 'East Shillong'"):
        out = p._focusplus_ac_name_case(["Focus Plus"],
                                        f"SELECT COUNT(*) FROM curated.v_focus_plus WHERE {where}")
        assert "UPPER(ac_name) = 'EAST SHILLONG'" in out, out
    other = "SELECT 1 FROM curated.v_expenditure WHERE ac_name = 'Amlarem'"
    assert p._focusplus_ac_name_case(["MGNREGA"], other) == other


def test_focus_plus_reads_a_constituency_only_when_named():
    assert p._ac_dimension_available("Focus Plus beneficiaries in East Shillong constituency", ["Focus Plus"])
    assert not p._ac_dimension_available("Focus Plus amount disbursed in Mawsynram", ["Focus Plus"])


def test_focus_plus_constituency_prompt_names_ac_name():
    from app import prompt_builder as pb
    text = pb._entities_block({"resolved": {"assembly_constituency": "EAST SHILLONG"}, "notes": []},
                              schemes=["Focus Plus"])
    assert "UPPER(ac_name) = UPPER('EAST SHILLONG')" in text
    assert "assembly_constituency_name" not in text


def test_geography_only_constituencies_resolve(monkeypatch):
    async def rows(_sql, *_a, **_k):
        return [{"a": "East Shillong"}, {"a": "Nongkrem"}]
    monkeypatch.setattr(er, "fetch_rows", rows)
    try:
        assert asyncio.run(er.load_geography_constituencies()) == 1       # Nongkrem is MGNREGA's already
        r = er.resolve_dimension("East Shillong", "Focus Plus", "assembly_constituency")
        assert r.status == "resolved" and r.canonical == "EAST SHILLONG"
    finally:
        er._catalog.pop(er._GEOGRAPHY_ONLY, None)
