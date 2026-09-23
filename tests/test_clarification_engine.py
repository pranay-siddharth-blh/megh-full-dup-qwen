"""
Clarification rule-matcher engine (app/clarification_engine.py, node 5.3
Phase 1 — backlog-clarification-rule-engine-migration) — pure-logic checks
against the real curated `*_classification_rules.yaml` files. No DB, no
model gateway — same stance as test_defaults_engine.py:
`python tests/test_clarification_engine.py`, exit code 0 = all pass.

Covers tasks.md task 3.2's acceptance scenarios:
(a) per scheme, at least one positive match per wired condition (question
    text -> expected condition fires, with the scheme's own authored
    question text returned);
(b) at least one negative case per scheme — a legitimately answerable
    question that must NOT trigger any clarification;
(c) explicit zero-regression check: a question matching an existing
    hardcoded predicate's topic (administrative expenditure, women's
    share, DBT/bank status) still gets that predicate's exact question
    text, not this engine's — collision handling is not silently bypassed;
(d) documents (with assertions, not just prose) the shared-condition-name
    side effect described in clarification_engine.py's module docstring:
    wiring one matcher for a name multiple schemes' YAMLs share extends
    coverage to every scheme that defines it, including occurrences
    outside this phase's nominal per-scheme counts;
(e) the deliberate non-wiring of PMAY-G's `villages_without_houses_
    requested` (now answerable per its own YAML v2_note) never fires.

AUTHORED-PENDING-SME-REVIEW: matcher phrasing has not yet been reviewed by
the SME pool named in tasks.md task 1.2. These tests check the matchers do
what THIS implementation intends, not that the intent itself is the
correct product call for every real-world phrasing — that is exactly what
the pending SME review is for.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app import clarification_engine as ce  # noqa: E402
from app.pipeline import (  # noqa: E402
    _admin_expenditure_clarification,
    _bank_clarification,
    _women_share_clarification,
)

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def fires(scheme: str, question: str) -> "str | None":
    return ce.check_clarifications(question, [scheme], {})


# Phase 2 (backlog-clarification-rule-engine-phase-2) unique matcher names —
# defined here, before section 1, so section 1's Phase-1-only coverage check
# can exclude them (they get their own coverage check in section 7).
_PHASE2_NAMES = {
    "missing_metric_for_ranking", "missing_metric_for_trend", "ambiguous_count_subject",
    "rate_vs_count_unclear", "ambiguous_beneficiary", "ambiguous_employment_measure",
    "ambiguous_wages", "ambiguous_hundred_days", "efficiency_term_unclear",
    "ambiguous_progress_term", "ambiguous_pending_houses_or_amount", "ambiguous_status_group",
    "women_ownership_scope_unclear", "beneficiary_reading_unclear", "count_subject_unclear",
    "farmers_vs_beneficiaries", "performance_or_gap_term_unclear",
    "anomaly_or_outlier_definition_unclear", "duplicate_definition_unclear",
    "concentration_threshold_missing", "significance_or_comparability_unclear",
    "biggest_scheme_ambiguous", "share_denominator_missing", "ambiguous_average_denominator",
    "concentration_measure_unclear", "ambiguous_status_subject", "applicant_type_scope_unclear",
}

# Phase 3 (backlog-clarification-rule-engine-phase-3) unique matcher names —
# same reason: excluded from section 1's Phase-1-only coverage check (they
# get their own coverage check in section 10).
_PHASE3_NAMES = {
    "women_metric_in_2025_26", "benefit_to_households_requested",
    "job_cards_across_multiple_years", "sanctioned_amount_variation_requested",
    "installment_or_release_as_completion_proof", "house_status_as_occupancy",
    "completion_rate_across_mixed_years", "mapping_status_as_performance",
    "individual_person_tracking_requested", "parent_name_filter_requested",
    "money_unit_unconfirmed", "money_across_schemes_unit_mismatch",
    "application_read_as_award", "beneficiary_term_used",
    "forward_status_read_as_approved", "current_level_read_as_progress",
    "data_verified_read_as_funding_decision", "type_raw_grouping_across_schemes",
    "current_level_case_variants", "sendback_wording_variants",
}


# ── 1. Positive matches — one per unique wired condition, fired through a ──
# scheme whose YAML actually authors that condition, asserting BOTH that a
# clarification fires AND that it is that scheme's own YAML question text
# (proves check_clarifications is reading text from the right per-scheme
# rule dict, not a matcher-owned string).
print("1. POSITIVE MATCHES (one per wired condition)")

_POSITIVE_CASES = [
    # scheme, condition, question, substring expected in that scheme's own question text
    ("MGNREGA", "finer_than_financial_year_requested", "What was the monthly MGNREGA expenditure?", "financial year only"),
    ("MGNREGA", "pending_dues_requested", "What are the pending dues for MGNREGA workers?", "Pending dues"),
    ("MGNREGA", "fund_availability_requested", "How much fund is available for MGNREGA right now?", "Fund releases"),
    ("MGNREGA", "works_or_assets_requested", "How many works were completed under MGNREGA?", "Works and assets"),
    ("MGNREGA", "wage_rate_requested", "What is the MGNREGA wage rate in West Garo Hills?", "wage rate"),
    ("MGNREGA", "per_capita_requested", "What is the per capita MGNREGA expenditure?", "Population figures"),
    ("MGNREGA", "budget_vs_actual_requested", "How does actual expenditure compare to the sanctioned budget?", "sanctioned budget"),
    ("MGNREGA", "individual_person_requested", "How many person-days did this individual worker complete?", "village level"),
    ("MGNREGA", "other_scheme_requested", "Can you show me data from another government scheme?", "MGNREGA is loaded"),

    ("PMAY-G", "pmay_urban_requested", "What about PMAY urban housing data?", "PMAY-Gramin only"),
    ("PMAY-G", "other_state_comparison_requested", "How does Meghalaya compare with other states?", "other states cannot be compared"),
    ("PMAY-G", "centre_state_share_requested", "What is the centre state share split for PMAY houses?", "funding split"),
    ("PMAY-G", "material_labour_cost_split_requested", "What is the material and labour cost split for PMAY houses?", "material or labour breakdown"),
    ("PMAY-G", "budget_or_target_requested", "What is the target for houses this year?", "Targets, allocations"),
    ("PMAY-G", "saturation_or_coverage_requested", "What is the saturation coverage of PMAY in Ri Bhoi?", "coverage or saturation"),
    ("PMAY-G", "beneficiary_income_or_caste_requested", "What is the caste breakdown of PMAY beneficiaries?", "Income, caste"),
    ("PMAY-G", "gender_column_requested", "Show me the gender breakdown of PMAY beneficiaries", "no gender column"),
    ("PMAY-G", "age_or_disability_requested", "How many PMAY beneficiaries have a disability?", "Age, disability"),
    ("PMAY-G", "land_ownership_requested", "What is the land ownership status of PMAY beneficiaries?", "Land ownership"),
    ("PMAY-G", "house_specification_requested", "What is the plinth area of the sanctioned houses?", "Plinth area"),
    ("PMAY-G", "convergence_benefits_requested", "Did the beneficiaries also get a toilet under convergence?", "Toilet, LPG"),
    ("PMAY-G", "geotag_or_inspection_requested", "Were the houses geotagged during inspection?", "Geotagged photographs"),
    ("PMAY-G", "grievance_status_requested", "How many grievances were filed against PMAY?", "Grievances, appeals"),
    ("PMAY-G", "contractor_or_agency_requested", "Which contractor built these houses?", "Implementing agency"),
    ("PMAY-G", "waitlist_or_selection_requested", "What is the current PMAY waitlist?", "permanent waitlist"),
    ("PMAY-G", "cancelled_or_rejected_houses_requested", "How many PMAY houses were cancelled?", "Cancelled, rejected"),
    ("PMAY-G", "stalled_houses_requested", "How many PMAY houses are stalled?", "stalled house cannot be identified"),
    ("PMAY-G", "installment_dates_requested", "What are the installment dates for this house?", "Individual installment dates"),
    ("PMAY-G", "completion_or_release_date_requested", "What is the completion date of the house?", "no completion date"),
    ("PMAY-G", "employment_or_wages_requested", "How many person-days of employment did PMAY beneficiaries get?", "separate source"),
    ("PMAY-G", "personal_contact_details_requested", "What is the Aadhaar number of the beneficiary?", "Aadhaar, mobile numbers"),
    ("PMAY-G", "below_village_geography_requested", "Which habitation is this house located in?", "village only"),
    ("PMAY-G", "other_scheme_requested", "Is there data for another scheme here?", "PMAY-G only"),

    ("Focus Plus", "epic_id_requested", "What is the EPIC number of this beneficiary?", "EPIC / voter ID"),
    ("Focus Plus", "beneficiary_name_requested", "What is the beneficiary name for this payment?", "Beneficiary names"),
    ("Focus Plus", "mobile_number_requested", "What is the mobile number of this farmer?", "Mobile numbers"),
    ("Focus Plus", "payment_date_requested", "What is the payment date for this disbursement?", "no payment date"),
    ("Focus Plus", "monthly_or_quarterly_analysis_requested", "Show me a monthly breakdown of Focus Plus payments", "monthly or quarterly view"),
    ("Focus Plus", "farmer_id_nic_requested", "What is the Farmer ID for this beneficiary?", "Farmer ID"),
    ("Focus Plus", "eligible_population_or_coverage_rate_requested", "What is the coverage rate of Focus Plus?", "Coverage as a percentage"),
    ("Focus Plus", "per_capita_requested", "What is the per capita Focus Plus payment amount?", "Population figures"),
    ("Focus Plus", "constituency_or_mla_requested", "Which MLA constituency does this village fall under?", "Assembly constituency"),
    ("Focus Plus", "budget_target_or_allocation_requested", "What is the budget allocation for Focus Plus this year?", "Targets, allocations"),
    ("Focus Plus", "forecast_or_projection_requested", "Can you forecast next year's Focus Plus payments?", "projection would rest"),
    ("Focus Plus", "other_scheme_or_dataset_requested", "What about the Ginger Mission data?", "Ginger Mission"),
    ("Focus Plus", "urban_or_other_state_requested", "How does this compare with urban areas in other states?", "Meghalaya only"),
    ("Focus Plus", "caste_income_or_bpl_requested", "What is the caste of Focus Plus beneficiaries?", "Income, caste"),
    ("Focus Plus", "age_or_disability_requested", "How many Focus Plus beneficiaries have a disability?", "Age and disability"),
    ("Focus Plus", "household_or_family_requested", "How many households are covered under Focus Plus?", "individual members, not households"),
    ("Focus Plus", "below_village_geography_requested", "Which ward is this beneficiary from?", "village or ward only"),

    ("CM Elevate", "any_money_amount_requested", "What is the total funding under CM Elevate?", "no sanctioned, subsidy, loan or disbursed amount"),
    ("CM Elevate", "disbursement_requested", "How much was disbursed under CM Elevate?", "No disbursement figures"),
    ("CM Elevate", "sanctioned_amount_requested", "What sanctioned amount did this applicant get?", "no sanctioned amount"),
    ("CM Elevate", "subsidy_requested", "What is the subsidy amount for this application?", "Subsidy amounts"),
    ("CM Elevate", "loan_requested", "How much loan amount was given under CM Elevate?", "Loan amounts"),
    ("CM Elevate", "sanctioned_vs_disbursed_gap_requested", "What is the gap between sanctioned and disbursed amounts?", "Neither a sanctioned nor a disbursed"),
    ("CM Elevate", "unit_cost_or_subsidy_share_requested", "What is the unit cost for this CM Elevate scheme?", "Unit costs"),
    ("CM Elevate", "per_beneficiary_amount_requested", "What is the average amount per beneficiary?", "no amount to divide"),
    ("CM Elevate", "any_time_period_requested", "What is the timeline for these applications?", "no date"),
    ("CM Elevate", "trend_or_growth_requested", "What is the trend in CM Elevate applications over time?", "A trend needs a date"),
    ("CM Elevate", "year_comparison_requested", "How do this year's applications compare year on year?", "cannot be split by year"),
    ("CM Elevate", "monthly_breakdown_requested", "Show me a monthly breakdown of applications", "no month on a CM Elevate application"),
    ("CM Elevate", "recency_or_latest_requested", "What are the latest CM Elevate applications received?", "carry none"),
    ("CM Elevate", "request_id_date_parse_attempted", "Can you extract the date from the request id?", "not reliable enough"),
    ("CM Elevate", "forecast_requested", "Can you forecast next year's CM Elevate applications?", "Forecasting is out of scope"),
    ("CM Elevate", "desanctioned_requested", "How many CM Elevate applications were desanctioned?", "no desanctioned field"),
    ("CM Elevate", "refused_or_rejected_requested", "How many CM Elevate applications were rejected?", "no refusal or rejection field"),
    ("CM Elevate", "approval_status_requested", "Was this CM Elevate application approved?", "does not record an approval decision"),
    ("CM Elevate", "beneficiary_status_requested", "Did the CM Elevate beneficiary actually receive anything?", "not recorded"),
]

for scheme, condition, question, expect_substr in _POSITIVE_CASES:
    text = fires(scheme, question)
    check(f"{scheme}/{condition}: fires", text is not None, question)
    if text is not None:
        check(f"{scheme}/{condition}: returns that scheme's own question text",
              expect_substr.lower() in text.lower(), text)

_all_wired = set(ce._MATCHERS.keys()) - _PHASE2_NAMES - _PHASE3_NAMES
_covered = {c for _, c, _, _ in _POSITIVE_CASES}
check("every Phase 1 wired matcher has at least one positive case above",
      _all_wired <= _covered, sorted(_all_wired - _covered))


# ── 2. Shared-condition-name side effect (documented in the module) ────────
# Several names are wired once but authored in more than one scheme's YAML;
# firing for a scheme outside this phase's nominal per-scheme count is an
# intentional, documented consequence of the existing global-name registry,
# not a bug — assert it explicitly rather than leaving it as prose only.
print("2. SHARED CONDITION NAMES EXTEND TO SCHEMES OUTSIDE THE NOMINAL COUNT")

_SIDE_EFFECT_CASES = [
    ("CM Elevate", "What is the per capita CM Elevate application count?", "Population figures"),
    ("CM Elevate", "Can I see data for another scheme instead of CM Elevate?", "CM Elevate only"),
    ("CM Elevate", "How many CM Elevate beneficiaries have a disability?", "Age and disability"),
    ("CM Elevate", "How many person-days of wages did CM Elevate applicants get?", "separate source"),
    ("CM Elevate", "What is the Aadhaar number of this CM Elevate applicant?", "Aadhaar, EPIC"),
    ("CM Elevate", "Which habitation is this CM Elevate applicant from?", "village only"),
    ("CM Elevate", "How many grievances were filed against CM Elevate?", "Grievances, appeals"),
    ("CM Elevate", "How does Meghalaya compare with other states on CM Elevate?", "other states cannot be compared"),
    ("CM Elevate", "What is the saturation coverage of CM Elevate?", "coverage or saturation"),
]
for scheme, question, expect_substr in _SIDE_EFFECT_CASES:
    text = fires(scheme, question)
    check(f"{scheme}: shared-name matcher fires ({question!r})", text is not None, question)
    if text is not None:
        check(f"{scheme}: uses CM Elevate's own question text, not another scheme's",
              expect_substr.lower() in text.lower(), text)


# ── 3. Deliberately unwired: PMAY-G's now-answerable villages_without_houses ─
print("3. DELIBERATELY UNWIRED CONDITION NEVER FIRES")
check("villages_without_houses_requested has no matcher entry",
      "villages_without_houses_requested" not in ce._MATCHERS)
check("a question phrased for it does not raise a clarification",
      fires("PMAY-G", "Which villages have no PMAY houses at all?") is None
      or "villages_without_houses" not in str(fires("PMAY-G", "Which villages have no PMAY houses at all?")))


# ── 4. Negative cases — one legitimately answerable question per scheme ────
# must not trigger ANY clarification from this engine.
print("4. NEGATIVE CASES (legitimately answerable, per scheme)")

_NEGATIVE_CASES = [
    ("MGNREGA", "What was the total MGNREGA expenditure in West Garo Hills for FY 2023-24?"),
    ("PMAY-G", "How many PMAY-G houses were sanctioned in Ri Bhoi district?"),
    ("Focus Plus", "How many Focus Plus payments were made in East Khasi Hills?"),
    ("CM Elevate", "How many CM Elevate applications were received for the Piggery scheme?"),
    # Producer groups are answerable since 2026-09-23 (curated.v_focus_legacy) —
    # the old producer_group_requested refusal was removed, and no other Focus
    # Plus farmer-payment rule ("count of what?") may fire on a PG question.
    ("Focus Plus", "Which producer group does this farmer belong to?"),
    ("Focus Plus", "How many members are there in Sakania PG?"),
    ("Focus Plus", "how many producer groups are there in West Garo Hills"),
]
for scheme, question in _NEGATIVE_CASES:
    text = fires(scheme, question)
    check(f"{scheme}: legitimate question fires no clarification", text is None, text)


# ── 5. Collision zero-regression — an existing hardcoded predicate's exact ──
# text still wins; this engine never shadows it, because check_clarifications
# is never even reached for a collision condition (skipped via
# _COLLISION_CONDITIONS), and pipeline.py checks the hardcoded predicates in
# their own, separate, earlier code path.
print("5. COLLISION ZERO-REGRESSION (existing hardcoded predicates unaffected)")

_admin_exc = _admin_expenditure_clarification("What was the administrative expenditure for MGNREGA?")
check("administrative_expenditure_requested: hardcoded predicate still fires with its own text",
      "Administrative expenditure" in _admin_exc.question, _admin_exc.question)
check("administrative_expenditure_requested is in this module's collision set",
      "administrative_expenditure_requested" in ce._COLLISION_CONDITIONS)
check("administrative_expenditure_requested is skipped by check_clarifications even though "
      "PMAY-G's own YAML copy of it is loaded",
      "administrative_expenditure_requested" in ce._load_scheme_rules("PMAY-G"))

_women_exc = _women_share_clarification("What is the women's share of MGNREGA employment?")
check("women_share_requested: hardcoded predicate still fires with its own text",
      "share can't be computed" in _women_exc.question, _women_exc.question)

_bank_exc = _bank_clarification("What is the DBT bank transfer status for this PMAY beneficiary?")
check("dbt_or_bank_status_requested: hardcoded predicate still fires", _bank_exc is not None)
check("dbt_or_bank_status_requested is in this module's collision set",
      "dbt_or_bank_status_requested" in ce._COLLISION_CONDITIONS)
check("account_number_or_ifsc_requested is in this module's collision set",
      "account_number_or_ifsc_requested" in ce._COLLISION_CONDITIONS)
check("loan_entity_requested is in this module's collision set",
      "loan_entity_requested" in ce._COLLISION_CONDITIONS)

# The engine itself must never return text for a collision condition, even
# if a matcher for that name existed (none do today, but this proves the
# collision check runs regardless of _MATCHERS content).
check("check_clarifications never fires for a collision-listed condition name",
      all(name not in ce._COLLISION_CONDITIONS
          for scheme in ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]
          for name, matcher in ce._MATCHERS.items()
          if ce._load_scheme_rules(scheme).get(name) and matcher("administrative expenditure", {})
          and name in ce._COLLISION_CONDITIONS))


# ── 6. Malformed / missing rules file degrades safely (mirrors defaults_ ───
# engine's equivalent check) — never raises, never fires.
print("6. MISSING/UNKNOWN SCHEME DEGRADES SAFELY")
check("unknown scheme name returns None, does not raise",
      fires("NoSuchScheme", "What is the pending dues amount?") is None)
check("empty schemes list returns None",
      ce.check_clarifications("What is the pending dues amount?", [], {}) is None)


# ── 7. Phase 2 — "which measure" category positive matches ─────────────────
# backlog-clarification-rule-engine-phase-2: one positive case per unique
# Phase 2 matcher, through a scheme whose YAML actually authors it.
print("7. PHASE 2 POSITIVE MATCHES (\"which measure\" category)")

_PHASE2_POSITIVE_CASES = [
    # Shared across schemes
    ("MGNREGA", "missing_metric_for_ranking", "What are the top 5 villages in MGNREGA?", "Top by what"),
    ("MGNREGA", "missing_metric_for_trend", "What is the trend for MGNREGA over time?", "trend show"),
    ("MGNREGA", "ambiguous_count_subject", "How many are there for MGNREGA this year?", "A count of what"),
    # Was "What is the completion rate for PMAY-G?" — found during Phase 3
    # authoring (backlog-clarification-rule-engine-phase-3) that this exact
    # phrase now also matches the newer, earlier-in-file-order
    # completion_rate_across_mixed_years condition, which correctly wins
    # per first-match-wins file order (SME-authored, not a bug). Swapped to
    # a different bare "rate" noun so this case still tests rate_vs_count_
    # unclear's own actual behavior (a bare "rate" word with no percentage/
    # count qualifier) without touching that unrelated condition's trigger.
    ("PMAY-G", "rate_vs_count_unclear", "What is the PMAY-G success rate?", "completion rate as a percentage"),
    # MGNREGA-unique
    ("MGNREGA", "ambiguous_beneficiary", "How many beneficiaries did MGNREGA cover?", "households or persons"),
    ("MGNREGA", "ambiguous_employment_measure", "What was the total employment under MGNREGA?", "Which measure of employment"),
    ("MGNREGA", "ambiguous_wages", "What were the wages paid under MGNREGA?", "Unskilled wages or semi-skilled"),
    ("MGNREGA", "ambiguous_hundred_days", "How many households completed 100 days under MGNREGA?", "100 days of work"),
    # PMAY-G-unique
    ("PMAY-G", "efficiency_term_unclear", "How efficient is PMAY-G in Ri Bhoi?", "counts as efficient"),
    ("PMAY-G", "ambiguous_progress_term", "What is the progress of PMAY-G houses?", "construction stage"),
    ("PMAY-G", "ambiguous_pending_houses_or_amount", "How much is pending for PMAY-G?", "Pending houses, or pending amount"),
    ("PMAY-G", "ambiguous_status_group", "How many PMAY-G houses are not yet completed?", "under construction"),
    ("PMAY-G", "women_ownership_scope_unclear", "How many houses are allotted to women?", "joint husband-and-wife"),
    # Focus Plus-unique
    ("Focus Plus", "beneficiary_reading_unclear", "How many Focus Plus beneficiaries are there?", "three different numbers"),
    ("Focus Plus", "count_subject_unclear", "How many are there in Focus Plus this year?", "payments, members"),
    ("Focus Plus", "farmers_vs_beneficiaries", "How many farmers are covered by Focus Plus?", "recorded occupation is Farmer"),
    ("Focus Plus", "performance_or_gap_term_unclear", "Which villages have a coverage gap in Focus Plus?", "no coverage percentage"),
    ("Focus Plus", "anomaly_or_outlier_definition_unclear", "Are there any anomalies in Focus Plus payments?", "outlier"),
    ("Focus Plus", "duplicate_definition_unclear", "How many duplicate members are in Focus Plus?", "count as a duplicate"),
    ("Focus Plus", "concentration_threshold_missing", "Which villages are concentrated in Focus Plus payments?", "top one, the top three"),
    ("Focus Plus", "significance_or_comparability_unclear", "Is this Focus Plus number significant?", "Compared against what"),
    # CM Elevate-unique
    ("CM Elevate", "biggest_scheme_ambiguous", "Which is the biggest scheme in CM Elevate?", "most applications"),
    ("CM Elevate", "share_denominator_missing", "What percentage of CM Elevate applications is this?", "scheme total, the district total"),
    ("CM Elevate", "ambiguous_average_denominator", "What is the average CM Elevate application count?", "per scheme, per district"),
    ("CM Elevate", "concentration_measure_unclear", "How concentrated are CM Elevate applications?", "largest scheme"),
    ("CM Elevate", "ambiguous_status_subject", "What is the status of this CM Elevate application?", "verification outcome"),
    ("CM Elevate", "applicant_type_scope_unclear", "How many individual applicants applied to CM Elevate?", "registered bodies"),
]

for scheme, condition, question, expect_substr in _PHASE2_POSITIVE_CASES:
    text = fires(scheme, question)
    check(f"{scheme}/{condition}: fires", text is not None, question)
    if text is not None:
        check(f"{scheme}/{condition}: returns that scheme's own question text",
              expect_substr.lower() in text.lower(), text)

_phase2_covered = {c for _, c, _, _ in _PHASE2_POSITIVE_CASES}
check("every Phase 2 matcher has at least one positive case above",
      _PHASE2_NAMES <= _phase2_covered, sorted(_PHASE2_NAMES - _phase2_covered))
check("Phase 2 added exactly 27 unique matchers to the registry",
      len(_PHASE2_NAMES) == 27, len(_PHASE2_NAMES))
check("registry contains at least Phase 1 (66) + Phase 2 (27) = 93 matchers "
      "(exact total re-asserted in section 10, once Phase 3 is also accounted for)",
      len(ce._MATCHERS) >= 93, len(ce._MATCHERS))


# ── 8. Phase 2 shared-name side effects found during design/authoring ──────
# `share_denominator_missing` and `ambiguous_average_denominator` also exist
# in MGNREGA/PMAY-G/Focus Plus's own "shape of the answer" sections (outside
# this phase's original CM-Elevate-only design) — each scheme's own valid
# "per X" / "X total" phrasing must be recognized as already-disambiguated,
# not just CM Elevate's four words (see clarification_engine.py comments).
print("8. PHASE 2 SHARED-NAME SIDE EFFECTS (denominator conditions, 4 schemes)")

_PHASE2_SIDE_EFFECT_POSITIVE = [
    ("MGNREGA", "What is the average MGNREGA figure?", "per village, per year, or per household"),
    ("PMAY-G", "What is the average PMAY-G figure?", "per house, per village, or per year"),
    ("Focus Plus", "What is the average Focus Plus figure?", "per member, per village, per block, or per tranche"),
    ("MGNREGA", "What share of the total is this MGNREGA figure?", "district total, or the state total"),
    ("Focus Plus", "What share of the total is this Focus Plus figure?", "district total, the batch total"),
]
for scheme, question, expect_substr in _PHASE2_SIDE_EFFECT_POSITIVE:
    text = fires(scheme, question)
    check(f"{scheme}: denominator matcher fires ({question!r})", text is not None, question)
    if text is not None:
        check(f"{scheme}: uses its own scheme-specific denominator wording",
              expect_substr.lower() in text.lower(), text)

# The fix this section exists to prove: a scheme's OWN valid, already-
# disambiguated denominator phrasing must NOT still trigger the matcher.
_PHASE2_DENOMINATOR_NEGATIVE = [
    ("MGNREGA", "What is the average MGNREGA figure per household?"),
    ("MGNREGA", "What share of the state total is this MGNREGA figure?"),
    ("PMAY-G", "What is the average PMAY-G figure per house?"),
    ("Focus Plus", "What is the average Focus Plus figure per tranche?"),
    ("Focus Plus", "What share of the batch total is this Focus Plus figure?"),
]
for scheme, question in _PHASE2_DENOMINATOR_NEGATIVE:
    text = fires(scheme, question)
    check(f"{scheme}: already-qualified denominator phrasing does not false-fire ({question!r})",
          text is None, text)


# ── 9. Phase 2 deliberate exclusions never fire ─────────────────────────────
# vague_qualifier (placeholder the registry can't fill) and the three
# flagship-default-term conditions (ambiguous_expenditure_component,
# sanctioned_reading_unclear, amount_reading_unclear) — see design.md.
print("9. PHASE 2 DELIBERATE EXCLUSIONS NEVER FIRE")

for name in ("vague_qualifier", "ambiguous_expenditure_component",
             "sanctioned_reading_unclear", "amount_reading_unclear"):
    check(f"{name} has no matcher entry", name not in ce._MATCHERS)

check("a bare MGNREGA expenditure question still answers without a clarification "
      "(the flagship-default-term regression this exclusion prevents)",
      fires("MGNREGA", "What was the total MGNREGA expenditure in West Garo Hills?") is None)
check("a bare PMAY-G 'houses sanctioned' question still answers without a clarification",
      fires("PMAY-G", "How many PMAY-G houses were sanctioned in Ri Bhoi district?") is None)
check("a bare Focus Plus 'amount disbursed' question still answers without a clarification",
      fires("Focus Plus", "What is the total amount disbursed under Focus Plus?") is None)


def fires_r(scheme: str, question: str, resolved: dict) -> "str | None":
    return ce.check_clarifications(question, [scheme], resolved)


# ── 10. Phase 3 positive matches — "measures/fields exist but must not be ──
# reported as asked" category (backlog-clarification-rule-engine-phase-3).
# One positive case per wired condition; every condition here is
# scheme-unique (no shared-name side effects to test, unlike Phases 1-2).
print("10. PHASE 3 POSITIVE MATCHES (\"measures/fields exist but must not be reported as asked\")")

_PHASE3_POSITIVE_CASES = [
    # scheme, condition, question, resolved, expected substring
    ("MGNREGA", "women_metric_in_2025_26",
     "How many women were employed under MGNREGA in FY 2025-26?", {}, "zero on every row in 2025-26"),
    ("MGNREGA", "benefit_to_households_requested",
     "What is the household benefit provided under MGNREGA?", {}, "household benefit column is unverified"),
    ("MGNREGA", "job_cards_across_multiple_years",
     "What is the total job cards issued across all financial years?", {}, "running total"),
    ("PMAY-G", "sanctioned_amount_variation_requested",
     "How does the sanctioned amount vary by district?", {}, "flat per-house entitlement"),
    ("PMAY-G", "installment_or_release_as_completion_proof",
     "Are houses with all three installments considered complete?", {}, "not proof of completion"),
    ("PMAY-G", "house_status_as_occupancy",
     "How many PMAY houses are occupied?", {}, "construction stage"),
    ("PMAY-G", "completion_rate_across_mixed_years",
     "What is the overall completion rate for PMAY-G?", {}, "mixes older houses"),
    ("PMAY-G", "mapping_status_as_performance",
     "How is the mapping status performance for PMAY?", {}, "how confidently a house was matched"),
    ("PMAY-G", "individual_person_tracking_requested",
     "Can you track this beneficiary across records?", {}, "beneficiary names are not held"),
    ("PMAY-G", "parent_name_filter_requested",
     "Filter houses by father's name", {}, "parent names are not held"),
    ("Focus Plus", "money_unit_unconfirmed",
     "What currency is this Focus Plus amount reported in?", {}, "unit for Focus Plus amounts is not confirmed"),
    ("Focus Plus", "money_across_schemes_unit_mismatch",
     "Compare the funding amount between Focus Plus and MGNREGA", {}, "different units"),
    ("CM Elevate", "application_read_as_award",
     "How many applications received the scheme funds?", {}, "not approvals or payments"),
    ("CM Elevate", "beneficiary_term_used",
     "How many beneficiaries are there in CM Elevate?", {}, "means one application"),
    ("CM Elevate", "forward_status_read_as_approved",
     "How many applications are forwarded and approved?", {}, "does not record an approval decision"),
    ("CM Elevate", "current_level_read_as_progress",
     "What level shows the most progress for CM Elevate?", {}, "stage label"),
    ("CM Elevate", "data_verified_read_as_funding_decision",
     "How many applications were verified and funded?", {}, "own data was found valid"),
    ("CM Elevate", "type_raw_grouping_across_schemes",
     "Break down CM Elevate applications by applicant type", {}, "spelled differently by each scheme"),
    ("CM Elevate", "current_level_case_variants",
     "Show me applications by level", {}, "inconsistent capitalisation"),
    ("CM Elevate", "sendback_wording_variants",
     "How many applications were sent back?", {}, "two different wordings"),
]

for scheme, condition, question, resolved, expect_substr in _PHASE3_POSITIVE_CASES:
    text = fires_r(scheme, question, resolved)
    check(f"{scheme}/{condition}: fires", text is not None, question)
    if text is not None:
        check(f"{scheme}/{condition}: returns that scheme's own question text",
              expect_substr.lower() in text.lower(), text)

_phase3_covered = {c for _, c, _, _, _ in _PHASE3_POSITIVE_CASES}
_phase3_wired = {
    "women_metric_in_2025_26", "benefit_to_households_requested",
    "job_cards_across_multiple_years", "sanctioned_amount_variation_requested",
    "installment_or_release_as_completion_proof", "house_status_as_occupancy",
    "completion_rate_across_mixed_years", "mapping_status_as_performance",
    "individual_person_tracking_requested", "parent_name_filter_requested",
    "money_unit_unconfirmed", "money_across_schemes_unit_mismatch",
    "application_read_as_award", "beneficiary_term_used",
    "forward_status_read_as_approved", "current_level_read_as_progress",
    "data_verified_read_as_funding_decision", "type_raw_grouping_across_schemes",
    "current_level_case_variants", "sendback_wording_variants",
}
check("every Phase 3 wired matcher has at least one positive case above",
      _phase3_wired <= _phase3_covered, sorted(_phase3_wired - _phase3_covered))
check("Phase 3 added exactly 20 unique matchers to the registry",
      len(_phase3_wired) == 20, len(_phase3_wired))
# 112, not 113: Phase 1's producer_group_requested was unwired 2026-09-23
# (producer groups are answerable from curated.v_focus_legacy).
check("total registry size is Phase 1 (66 - 1 removed) + Phase 2 (27) + Phase 3 (20) = 112",
      len(ce._MATCHERS) == 112, len(ce._MATCHERS))


# ── 11. Phase 3 negative cases — resolved-state-sensitive conditions must ───
# not false-fire once the relevant state IS resolved, and legitimate
# readings of the same column/term must not trigger any Phase 3 condition.
print("11. PHASE 3 NEGATIVE CASES (resolved-state sensitivity + legitimate readings)")

check("women_metric_in_2025_26 does not fire once a different year is resolved",
      fires_r("MGNREGA", "How many women were employed under MGNREGA?",
              {"year_key": "2023-24"}) != ce._load_scheme_rules("MGNREGA")["women_metric_in_2025_26"]["question"])
check("completion_rate_across_mixed_years does not fire once a year is resolved",
      "mixes older houses" not in (fires_r("PMAY-G", "What is the completion rate for PMAY-G in FY 2023-24?",
                                            {"year_key": "2023-24"}) or ""))
check("completion_rate_across_mixed_years does not fire on an explicit year-by-year breakdown request",
      "mixes older houses" not in (fires_r("PMAY-G", "What is the completion rate by year for PMAY-G?", {}) or ""))
check("job_cards_across_multiple_years does not fire on a single-year question",
      fires("MGNREGA", "How many job cards were issued in FY 2023-24?") is None)
check("sanctioned_amount_variation_requested does not fire on a plain sanctioned-amount question",
      fires("PMAY-G", "What is the sanctioned amount for houses in Ri Bhoi district?") is None)
check("money_unit_unconfirmed does not fire on a plain Focus Plus money question",
      fires("Focus Plus", "What is the total amount disbursed under Focus Plus?") is None)
check("application_read_as_award does not fire on a plain 'applications received' (submitted) question",
      fires("CM Elevate", "How many applications were received for the Piggery scheme?") is None)


# ── 12. Phase 3 collision-set correction — women_share_requested ────────────
print("12. PHASE 3 COLLISION-SET CORRECTION (women_share_requested)")

check("women_share_requested is now in the collision set (found during Phase 3 scoping)",
      "women_share_requested" in ce._COLLISION_CONDITIONS)
check("women_share_requested has no matcher entry (stays the hardcoded predicate's job)",
      "women_share_requested" not in ce._MATCHERS)
_women_exc2 = _women_share_clarification("what percentage of MGNREGA workers were women?")
check("_women_share_clarification still fires with its own text after the collision-set fix",
      "share can't be computed" in _women_exc2.question, _women_exc2.question)


# ── 13. Phase 3 deliberate exclusions never fire ────────────────────────────
# Found during authoring (not before): each excluded for a distinct,
# recorded reason — see clarification_engine.py's Phase 3 section comment.
print("13. PHASE 3 DELIBERATE EXCLUSIONS NEVER FIRE")

for name in ("fuzzy_village_precision_warning", "singleton_category_focus",
             "standard_payment_reading_unclear", "average_payment_requested",
             "application_count_offered_as_money_proxy"):
    check(f"{name} has no matcher entry", name not in ce._MATCHERS)

check("gender_breakdown_requested (answerable per its own YAML note) has no matcher entry",
      "gender_breakdown_requested" not in ce._MATCHERS)


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL CLARIFICATION-ENGINE CHECKS PASSED")
