"""
app/clarification_engine.py — generic clarification-rule matcher for
`*_classification_rules.yaml` (node 5.3: "generic clarification gate"),
mirroring app/defaults_engine.py's shape for `*_default_rules.yaml`
(node 5.5).

Phase-1 scope only (backlog-clarification-rule-engine-migration, approved
2026-09-12): wires matchers for the 75 "source cannot answer this at all"
conditions across the four schemes' classification-rule files. The other
~266 conditions in those same files (time, which-measure, geography,
identifiers, shape-of-answer, data-quality categories) are loaded by
`_load_scheme_rules` like everything else, but deliberately have no entry
in `_MATCHERS` yet — see the backlog change's design.md for why this phase
is scoped the way it is, and tasks.md group 5 for what is explicitly
deferred.

Deterministic, no model call — same shape as app/premise_check.py and
app/defaults_engine.py: a pure function over already-resolved query state.
Unlike defaults_engine (which silently fills a detail and discloses it),
this module identifies a question the data genuinely cannot answer and
returns the YAML-authored clarifying question text so the pipeline can
pause and ask, instead of letting SQL generation guess at a column that
doesn't exist.

Collision rule (enforced here in code, not just documented in the YAML
header): a matched condition is applied ONLY when it is not already the
job of an existing hardcoded clarification predicate in app/pipeline.py.
`_COLLISION_CONDITIONS` below is that boundary — found by cross-checking
every condition name in the four "cannot answer" sections against
pipeline.py's existing scheme-agnostic checks (`_admin_expenditure_
clarification`, `_bank_clarification`), not assumed from name similarity:

- `administrative_expenditure_requested` (PMAY-G's "cannot answer" copy of
  the same condition name MGNREGA files under a different section) —
  already handled by `_admin_expenditure_clarification`, whose own comment
  in pipeline.py explicitly names both `mgnrega_classification_rules.yaml`
  and `pmay_classification_rules.yaml`.
- `dbt_or_bank_status_requested` (PMAY-G) and `account_number_or_ifsc_
  requested` (Focus Plus) and `loan_entity_requested` (CM Elevate) — all
  three already handled by `_bank_clarification` (`_BANK_REQUESTED` /
  `_BANK_ACCOUNT_DETAIL_REQUESTED` regexes, which include `\\bdbt\\b`,
  `\\bifsc\\b` / account-number wording, and `\\blifcom\\b` respectively).

This means the real remaining Phase-1 authoring surface is 71 matchers, not
75 — a correction found during infrastructure work, recorded in this
change's tasks.md alongside the rest of task group 2.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

import yaml

logger = logging.getLogger(__name__)

# app/clarification_engine.py -> repo root -> data/
_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"

_CLASSIFICATION_RULES_FILE = {
    "MGNREGA": _DATA_ROOT / "mgnrega" / "mgnrega_classification_rules.yaml",
    "PMAY-G": _DATA_ROOT / "pmay" / "pmay_classification_rules.yaml",
    "Focus Plus": _DATA_ROOT / "focus_plus" / "focusplus_classification_rules.yaml",
    "CM Elevate": _DATA_ROOT / "cm_elevate" / "cmelevate_classification_rules.yaml",
}

# condition name -> {"question": ..., ...}, per scheme, in the YAML file's own
# order (Python dicts preserve insertion order) — needed so first-match-wins
# follows "the YAML's own file order", per every file's own header comment.
_rules_cache: dict[str, dict[str, dict]] = {}
_loaded_schemes: set[str] = set()


def _load_scheme_rules(scheme: str) -> dict[str, dict]:
    """Read `scheme`'s `*_classification_rules.yaml` once, caching the
    result. Any failure (missing file, unreadable, malformed YAML,
    unexpected shape) degrades to "no conditions for this scheme" — this
    module must never raise because a rules file is absent or broken."""
    if scheme in _loaded_schemes:
        return _rules_cache.get(scheme, {})
    _loaded_schemes.add(scheme)
    path = _CLASSIFICATION_RULES_FILE.get(scheme)
    conditions: dict[str, dict] = {}
    if path is not None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for rule in (data or {}).get("clarification_rules", []) or []:
                name = rule.get("condition")
                if name:
                    conditions[name] = rule
        except FileNotFoundError:
            logger.warning("clarification_engine: no classification-rules file for %s at %s",
                            scheme, path)
        except Exception:  # noqa: BLE001 — malformed YAML, wrong shape, etc.
            logger.warning("clarification_engine: failed to load classification-rules file "
                            "for %s at %s", scheme, path, exc_info=True)
    _rules_cache[scheme] = conditions
    return conditions


# ── Collision set — conditions that stay the job of an existing hardcoded ───
# clarification predicate in app/pipeline.py. Never matched/applied by this
# module regardless of what a matcher function below would otherwise say. See
# this module's docstring for how each entry was verified (not assumed).
_COLLISION_CONDITIONS: frozenset[str] = frozenset({
    "administrative_expenditure_requested",
    "dbt_or_bank_status_requested",
    "account_number_or_ifsc_requested",
    "loan_entity_requested",
    # Found during Phase 3 scoping (backlog-clarification-rule-engine-
    # phase-3): MGNREGA's women_share_requested is already handled
    # end-to-end by pipeline.py's own _women_share_clarification /
    # _WOMEN_SHARE_REQUESTED predicate (same file, same section as
    # administrative_expenditure_requested above) but was missing from
    # this set since Phase 1 — harmless until now only because no matcher
    # for the name existed in _MATCHERS either.
    "women_share_requested",
})


# ── Condition matchers ───────────────────────────────────────────────────────
# Each takes (question, resolved) and returns True when that condition
# applies. Authored in tasks.md task group 3 (backlog-clarification-rule-
# engine-migration) for the 71 Phase-1 "cannot answer at all" conditions.
#
# AUTHORED-PENDING-SME-REVIEW: every regex below is a first-pass phrasing
# guess by the implementing session, not yet reviewed for accuracy by the
# SME pool that authored the YAML (task 1.2's assigned reviewer). Per
# design.md's verification-requirement section, these must not be treated
# as production-final until that review happens — tracked in tasks.md.
#
# SHARED CONDITION NAMES: `_MATCHERS` is a single flat dict keyed by
# condition name only, not by (scheme, name) — this is the existing,
# already-approved infrastructure (task group 2), not something introduced
# here. Several condition names are authored identically in more than one
# scheme's YAML (e.g. "per_capita_requested" appears in MGNREGA, PMAY-G,
# Focus Plus AND CM Elevate). Wiring one matcher for such a name
# automatically covers every scheme whose YAML defines it — including
# occurrences outside this phase's nominal per-scheme counts (e.g. CM
# Elevate's own copies of "per_capita_requested", "other_scheme_requested",
# "age_or_disability_requested", "employment_or_wages_requested",
# "personal_contact_details_requested", "below_village_geography_requested",
# "grievance_status_requested" and "other_state_comparison_requested" sit
# in sections this phase's 71-condition scope did NOT count for CM Elevate,
# but they get covered anyway once the shared name is wired). Each such
# extension uses that scheme's OWN authored question text (`rule["question"]`
# is always looked up per-scheme in `check_clarifications`), so this is
# strictly additional coverage of the identical "cannot answer" failure
# mode with SME-authored wording, not a new/invented behavior — flagged
# here, and in tasks.md, as a transparent side effect rather than left
# silent.
#
# DELIBERATELY NOT WIRED: PMAY-G's `villages_without_houses_requested` is
# one of the nominal 26 but is excluded here on purpose — its own YAML entry
# carries a `v2_note` (`pmay_classification_rules.yaml`) stating the
# question this condition used to refuse is now answerable
# (`curated.v_cross_scheme_village_coverage` covers it). Wiring a matcher for
# it would reintroduce exactly the false-fire regression this module's
# design.md warns against — blocking a legitimately answerable question. No
# entry below == it stays a no-op, which is the correct behavior for an
# answerable question. See tasks.md for this exclusion recorded explicitly.

# ---- MGNREGA -----------------------------------------------------------
_FINER_GRANULARITY = re.compile(
    r"\b(month(?:ly)?|per\s+month|quarter(?:ly)?|week(?:ly)?|per\s+week|"
    r"daily|day-?wise|by\s+date)\b", re.IGNORECASE)


def _match_finer_than_fy(question: str, resolved: dict) -> bool:
    return bool(_FINER_GRANULARITY.search(question or ""))


_PENDING_DUES = re.compile(
    r"\b(pending\s+dues?|outstanding\s+(?:dues?|amounts?|payments?)|unpaid|"
    r"arrears?|yet\s+to\s+be\s+paid|due\s+amounts?)\b", re.IGNORECASE)


def _match_pending_dues(question: str, resolved: dict) -> bool:
    return bool(_PENDING_DUES.search(question or ""))


_FUND_AVAILABILITY = re.compile(
    r"\bfunds?\b.{0,15}\bavailab\w+\b|\bavailab\w+\b.{0,15}\bfunds?\b|"
    r"\bfunds?\s+(?:remaining|left)\b|\bopening\s+balance\b|"
    r"\bbalance\s+available\b|\bavailable\s+balance\b|"
    r"\bunspent\s+(?:fund|balance|amount)s?\b", re.IGNORECASE)


def _match_fund_availability(question: str, resolved: dict) -> bool:
    return bool(_FUND_AVAILABILITY.search(question or ""))


_WORKS_ASSETS = re.compile(
    r"\bworks?\b.{0,15}\b(?:completed|created|taken\s+up|undertaken)\b|"
    r"\bassets?\s+created\b|\bnumber\s+of\s+works\b|"
    r"\binfrastructure\s+(?:created|built)\b", re.IGNORECASE)


def _match_works_or_assets(question: str, resolved: dict) -> bool:
    return bool(_WORKS_ASSETS.search(question or ""))


_WAGE_RATE = re.compile(
    r"\b(wage\s+rates?|daily\s+wage(?:\s+rate)?|rate\s+per\s+day|"
    r"per[\s-]?day\s+rate|average\s+wage)\b", re.IGNORECASE)


def _match_wage_rate(question: str, resolved: dict) -> bool:
    return bool(_WAGE_RATE.search(question or ""))


# Shared across MGNREGA / PMAY-G / Focus Plus (and, as a side effect of the
# shared-key registry, CM Elevate too — see the module note above). Excludes
# "per person-day" so MGNREGA's own legitimate person-days metric is never
# mistaken for a per-capita ask.
_PER_CAPITA = re.compile(
    r"\bper[\s-]?capita\b|\bper\s+head\b|\bpopulation[\s-]?normalized\b|"
    r"\bper\s+person\b", re.IGNORECASE)
_PER_PERSON_DAY = re.compile(r"\bper\s+person[\s-]*days?\b", re.IGNORECASE)


def _match_per_capita(question: str, resolved: dict) -> bool:
    q = question or ""
    if _PER_PERSON_DAY.search(q):
        return False
    return bool(_PER_CAPITA.search(q))


_BUDGET_VS_ACTUAL = re.compile(
    r"\b(budget(?:ed)?\s+(?:vs\.?|versus|compared?\s+to|against)\s+actual|"
    r"actual\s+(?:vs\.?|versus)\s+budget(?:ed)?|sanctioned\s+budget|"
    r"planned\s+(?:vs\.?|versus)\s+actual)\b", re.IGNORECASE)


def _match_budget_vs_actual(question: str, resolved: dict) -> bool:
    return bool(_BUDGET_VS_ACTUAL.search(question or ""))


_INDIVIDUAL_PERSON = re.compile(
    r"\b(individual\s+(?:worker|person|beneficiary|job\s*card\s*holder)|"
    r"for\s+(?:this|that|a\s+specific)\s+(?:worker|person)|"
    r"(?:worker|person)(?:'s|’s)\s+(?:person-?days?|wages?|record))\b",
    re.IGNORECASE)


def _match_individual_person(question: str, resolved: dict) -> bool:
    return bool(_INDIVIDUAL_PERSON.search(question or ""))


# Shared across MGNREGA / PMAY-G (and CM Elevate, side effect — see note
# above). Deliberately does NOT try to detect "mentions a different one of
# our four known schemes" — classify_scheme() already resolves multi-scheme
# questions; this only catches an explicitly named unsupported scheme/
# dataset, or a generic "other scheme" phrase, to avoid false-firing on a
# legitimate cross-scheme comparison question our own schemes list covers.
_OTHER_SCHEME_GENERIC = re.compile(
    r"\b(other\s+(?:government\s+)?schemes?|different\s+(?:government\s+)?schemes?|"
    r"another\s+(?:government\s+)?scheme|any\s+other\s+scheme)\b", re.IGNORECASE)
_KNOWN_UNSUPPORTED_SCHEMES = re.compile(
    r"\b(ayushman\s+bharat|pm[\s-]?kisan|ujjwala|swachh\s+bharat|"
    r"jal\s+jeevan\s+mission)\b", re.IGNORECASE)


def _match_other_scheme_requested(question: str, resolved: dict) -> bool:
    q = question or ""
    return bool(_OTHER_SCHEME_GENERIC.search(q) or _KNOWN_UNSUPPORTED_SCHEMES.search(q))


# ---- PMAY-G --------------------------------------------------------------
_PMAY_URBAN = re.compile(
    r"\bpmay[\s-]?u(?:rban)?\b|\burban\s+(?:pmay|housing\s+scheme)\b|"
    r"\bpradhan\s+mantri\s+awas\s+yojana\s+urban\b", re.IGNORECASE)


def _match_pmay_urban(question: str, resolved: dict) -> bool:
    return bool(_PMAY_URBAN.search(question or ""))


# Shared with CM Elevate (side effect — see module note above).
_OTHER_STATE = re.compile(
    r"\b(other\s+states?|across\s+(?:india|states?)|national\s+average|"
    r"compare\s+(?:with\s+)?(?:other\s+)?states?|state[\s-]?wise\s+comparison|"
    r"vs\.?\s+(?:assam|bihar|kerala|karnataka|tripura|manipur|mizoram|"
    r"nagaland|sikkim|arunachal))\b", re.IGNORECASE)


def _match_other_state_comparison(question: str, resolved: dict) -> bool:
    return bool(_OTHER_STATE.search(question or ""))


_CENTRE_STATE_SHARE = re.compile(
    r"\b(?:centre|central)\s*[-\s]?\s*state\s+(?:share|split|ratio|contribution)|"
    r"\bfunding\s+split\b|\bcentre(?:'s|’s)?\s+share\b|"
    r"\bstate(?:'s|’s)?\s+share\b", re.IGNORECASE)


def _match_centre_state_share(question: str, resolved: dict) -> bool:
    return bool(_CENTRE_STATE_SHARE.search(question or ""))


_MATERIAL_LABOUR = re.compile(
    r"\bmaterial\b.{0,20}\blabou?r\b|\blabou?r\b.{0,20}\bmaterial\b|"
    r"\bmaterial[\s-]?labou?r\s+(?:cost\s+)?split\b", re.IGNORECASE)


def _match_material_labour_split(question: str, resolved: dict) -> bool:
    return bool(_MATERIAL_LABOUR.search(question or ""))


# Note: bare "sanctioned" is NOT matched — "houses sanctioned" is a
# legitimate, answerable PMAY-G metric. Only target/allocation/budget words.
_TARGET_ALLOCATION_BUDGET = re.compile(
    r"\b(targets?|allocations?|budget(?:ed)?)\b", re.IGNORECASE)


def _match_budget_or_target(question: str, resolved: dict) -> bool:
    return bool(_TARGET_ALLOCATION_BUDGET.search(question or ""))


# Shared with CM Elevate (side effect — see module note above).
_SATURATION_COVERAGE = re.compile(
    r"\bsaturation\b|\bcoverage\s*(?:rate|percentage|%)?\b|"
    r"\beligible\s+(?:households?|families)\b|\btotal\s+eligible\b|"
    r"\b%\s*covered\b", re.IGNORECASE)


def _match_saturation_or_coverage(question: str, resolved: dict) -> bool:
    return bool(_SATURATION_COVERAGE.search(question or ""))


_INCOME_CASTE_BPL = re.compile(
    r"\bincome\b|\bcaste\b|\bsecc\b|\bbpl\b|\bbelow\s+poverty\s+line\b|"
    r"\b(?:sc|st|obc)\s*(?:category|beneficiar\w+)\b", re.IGNORECASE)


def _match_beneficiary_income_or_caste(question: str, resolved: dict) -> bool:
    return bool(_INCOME_CASTE_BPL.search(question or ""))


_GENDER = re.compile(
    r"\bgenders?\b|\bmales?\b|\bfemales?\b|\bsex[\s-]?wise\b|\btransgender\b",
    re.IGNORECASE)


def _match_gender_column(question: str, resolved: dict) -> bool:
    return bool(_GENDER.search(question or ""))


# Shared with Focus Plus (nominal) and CM Elevate (side effect).
_AGE_DISABILITY = re.compile(
    r"\bages?\b|\bdisab\w+|\bpwd\b|\bdifferently[\s-]?abled\b|"
    r"\bsenior\s+citizens?\b|\belderly\b", re.IGNORECASE)


def _match_age_or_disability(question: str, resolved: dict) -> bool:
    return bool(_AGE_DISABILITY.search(question or ""))


_LAND_OWNERSHIP = re.compile(
    r"\bland\s+(?:ownership|records?|titles?|documents?)\b|"
    r"\bplot\s+(?:ownership|details?)\b|\bpatta\b", re.IGNORECASE)


def _match_land_ownership(question: str, resolved: dict) -> bool:
    return bool(_LAND_OWNERSHIP.search(question or ""))


_HOUSE_SPEC = re.compile(
    r"\bplinth\s+area\b|\bhouse\s+types?\b|\broom\s+counts?\b|"
    r"\bcost\s+estimates?\b|\bsquare\s+f(?:ee|oo)t\b|\bhouse\s+size\b|"
    r"\bnumber\s+of\s+rooms?\b", re.IGNORECASE)


def _match_house_specification(question: str, resolved: dict) -> bool:
    return bool(_HOUSE_SPEC.search(question or ""))


_CONVERGENCE = re.compile(
    r"\btoilets?\b|\blpg\b|\belectricity\s+connections?\b|"
    r"\bwater\s+connections?\b|\bconvergence\b|\bswachh\s+bharat\b|"
    r"\bujjwala\b", re.IGNORECASE)


def _match_convergence_benefits(question: str, resolved: dict) -> bool:
    return bool(_CONVERGENCE.search(question or ""))


_GEOTAG_INSPECTION = re.compile(
    r"\bgeo[\s-]?tag\w*|\binspections?\b|\bsite\s+verifications?\b|"
    r"\bphotographs?\b", re.IGNORECASE)


def _match_geotag_or_inspection(question: str, resolved: dict) -> bool:
    return bool(_GEOTAG_INSPECTION.search(question or ""))


# Shared with CM Elevate (side effect — see module note above).
_GRIEVANCE = re.compile(r"\bgrievances?\b|\bcomplaints?\b|\bappeals?\b", re.IGNORECASE)


def _match_grievance_status(question: str, resolved: dict) -> bool:
    return bool(_GRIEVANCE.search(question or ""))


_CONTRACTOR_AGENCY = re.compile(
    r"\bcontractors?\b|\bimplementing\s+agenc\w+|\bmasons?\b|"
    r"\bagency\s+details?\b", re.IGNORECASE)


def _match_contractor_or_agency(question: str, resolved: dict) -> bool:
    return bool(_CONTRACTOR_AGENCY.search(question or ""))


_WAITLIST_SELECTION = re.compile(
    r"\bwait[\s-]?lists?(?:ed)?\b|\bselection\s+process\b|"
    r"\bpermanent\s+wait\s*list\b", re.IGNORECASE)


def _match_waitlist_or_selection(question: str, resolved: dict) -> bool:
    return bool(_WAITLIST_SELECTION.search(question or ""))


_CANCELLED_REJECTED = re.compile(
    r"\bcancell?ed\b|\brejected\b|\bwithdrawn\b", re.IGNORECASE)


def _match_cancelled_or_rejected_houses(question: str, resolved: dict) -> bool:
    return bool(_CANCELLED_REJECTED.search(question or ""))


_STALLED = re.compile(
    r"\bstalled\b|\bstuck\b|\bnot\s+progress(?:ed|ing)\b|"
    r"\bdelayed\s+houses?\b|\bno\s+progress\b", re.IGNORECASE)


def _match_stalled_houses(question: str, resolved: dict) -> bool:
    return bool(_STALLED.search(question or ""))


_INSTALLMENT_DATES = re.compile(
    r"\bin?stal(?:l)?ment\s+dates?\b|"
    r"\bwhen\s+was\s+(?:the\s+)?(?:in?stal(?:l)?ment|payment)\b|"
    r"\bdates?\s+of\s+(?:in?stal(?:l)?ments?|payments?)\b", re.IGNORECASE)


def _match_installment_dates(question: str, resolved: dict) -> bool:
    return bool(_INSTALLMENT_DATES.search(question or ""))


_COMPLETION_RELEASE_DATE = re.compile(
    r"\bcompletion\s+dates?\b|\bdates?\s+of\s+completion\b|\brelease\s+dates?\b|"
    r"\bwhen\s+(?:was\s+it\s+)?completed\b|\bcompletion\s+time\b", re.IGNORECASE)


def _match_completion_or_release_date(question: str, resolved: dict) -> bool:
    return bool(_COMPLETION_RELEASE_DATE.search(question or ""))


# Shared with CM Elevate (side effect — see module note above).
_EMPLOYMENT_WAGES = re.compile(
    r"\bperson[\s-]?days?\b|\bwages?\b|\bemployment\s+generated\b|"
    r"\bdays?\s+of\s+work\b", re.IGNORECASE)


def _match_employment_or_wages(question: str, resolved: dict) -> bool:
    return bool(_EMPLOYMENT_WAGES.search(question or ""))


# Shared with CM Elevate (side effect — see module note above). Deliberately
# generic PII/contact vocabulary; does not overlap dbt_or_bank_status_
# requested's job (bank TRANSFER STATUS) since that condition name is a
# separate, already-collision-excluded entry.
_PERSONAL_CONTACT = re.compile(
    r"\baadhaar\b|\bmobile\s+numbers?\b|\bphone\s+numbers?\b|"
    r"\bbank\s+accounts?\b|\baddresses?\b|\bepic\b|\bpan\s+(?:numbers?|cards?)\b|"
    r"\bifsc\b", re.IGNORECASE)


def _match_personal_contact_details(question: str, resolved: dict) -> bool:
    return bool(_PERSONAL_CONTACT.search(question or ""))


# Shared with CM Elevate (side effect — see module note above).
_BELOW_VILLAGE_GEO = re.compile(
    r"\bhabitations?\b|\bwards?\b|\bhamlets?\b|\bhousehold\s+locations?\b|"
    r"\bexact\s+locations?\b|\bgps\s+coordinates?\b", re.IGNORECASE)


def _match_below_village_geography(question: str, resolved: dict) -> bool:
    return bool(_BELOW_VILLAGE_GEO.search(question or ""))


# ---- Focus Plus -----------------------------------------------------------
# producer_group_requested was removed 2026-09-23 — producer groups are
# answerable from curated.v_focus_legacy. Any producer-group question (PG /
# LAMPS / "Focus Legacy") skips the Focus Plus rules entirely — see
# check_clarifications. Mirrors pipeline._PRODUCER_GROUP_Q.
_PG_QUESTION = re.compile(
    r"\bproducer[\s-]+groups?\b|\bpgs?\b|\blamps?\b|\bfocus\s+legacy\b", re.IGNORECASE)


_EPIC_ID = re.compile(r"\bepic\b|\bvoter\s*id\b|\bvoter\s+id\s+cards?\b", re.IGNORECASE)


def _match_epic_id(question: str, resolved: dict) -> bool:
    return bool(_EPIC_ID.search(question or ""))


_BENEFICIARY_NAME = re.compile(
    r"\bbeneficiary\s+names?\b|\bnames?\s+of\s+(?:the\s+)?beneficiar\w+|"
    r"\bmember\s+names?\b", re.IGNORECASE)


def _match_beneficiary_name(question: str, resolved: dict) -> bool:
    return bool(_BENEFICIARY_NAME.search(question or ""))


_MOBILE_NUMBER = re.compile(
    r"\bmobile\s+numbers?\b|\bphone\s+numbers?\b|\bcontact\s+numbers?\b",
    re.IGNORECASE)


def _match_mobile_number(question: str, resolved: dict) -> bool:
    return bool(_MOBILE_NUMBER.search(question or ""))


_PAYMENT_DATE = re.compile(
    r"\bpayment\s+dates?\b|\bdates?\s+of\s+payments?\b|"
    r"\bwhen\s+was\s+(?:the\s+)?payment\s+made\b", re.IGNORECASE)


def _match_payment_date(question: str, resolved: dict) -> bool:
    return bool(_PAYMENT_DATE.search(question or ""))


_MONTHLY_QUARTERLY = re.compile(
    r"\bmonth(?:ly|-wise)?\b|\bquarter(?:ly|-wise)?\b", re.IGNORECASE)


def _match_monthly_or_quarterly_analysis(question: str, resolved: dict) -> bool:
    return bool(_MONTHLY_QUARTERLY.search(question or ""))


_FARMER_ID_NIC = re.compile(
    r"\bfarmer\s*ids?\b|\bnic\s+(?:numbers?|fields?)\b|"
    r"\bfarmer\s+identifications?\b", re.IGNORECASE)


def _match_farmer_id_nic(question: str, resolved: dict) -> bool:
    return bool(_FARMER_ID_NIC.search(question or ""))


_ELIGIBLE_COVERAGE = re.compile(
    r"\beligible\s+populations?\b|\bcoverage\s+rates?\b|\b%\s*coverage\b|"
    r"\bhow\s+many\s+(?:are\s+)?eligible\b", re.IGNORECASE)


def _match_eligible_population_or_coverage_rate(question: str, resolved: dict) -> bool:
    return bool(_ELIGIBLE_COVERAGE.search(question or ""))


_CONSTITUENCY_MLA = re.compile(
    r"\bconstituenc\w+\b|\bmlas?\b|\bassembly\s+segments?\b", re.IGNORECASE)


def _match_constituency_or_mla(question: str, resolved: dict) -> bool:
    return bool(_CONSTITUENCY_MLA.search(question or ""))


def _match_budget_target_or_allocation(question: str, resolved: dict) -> bool:
    return bool(_TARGET_ALLOCATION_BUDGET.search(question or ""))


_FORECAST_PROJECTION = re.compile(
    r"\bforecast(?:s|ing)?\b|\bprojections?\b|\bpredict(?:ion)?\b|"
    r"\bestimates?\s+for\s+next\b", re.IGNORECASE)


def _match_forecast_or_projection(question: str, resolved: dict) -> bool:
    return bool(_FORECAST_PROJECTION.search(question or ""))


_OTHER_SCHEME_DATASET = re.compile(
    r"\bginger\s+mission\b|\bother\s+(?:schemes?|datasets?)\b|"
    r"\bdifferent\s+(?:schemes?|datasets?)\b", re.IGNORECASE)


def _match_other_scheme_or_dataset(question: str, resolved: dict) -> bool:
    return bool(_OTHER_SCHEME_DATASET.search(question or ""))


_URBAN_OR_OTHER_STATE = re.compile(
    r"\burban\b|\bother\s+states?\b|\bacross\s+states?\b|"
    r"\bnational\s+average\b", re.IGNORECASE)


def _match_urban_or_other_state(question: str, resolved: dict) -> bool:
    return bool(_URBAN_OR_OTHER_STATE.search(question or ""))


def _match_caste_income_or_bpl(question: str, resolved: dict) -> bool:
    return bool(_INCOME_CASTE_BPL.search(question or ""))


_HOUSEHOLD_FAMILY = re.compile(
    r"\bhouseholds?\b|\bfamil(?:y|ies)\b|\bfamily\s+ids?\b", re.IGNORECASE)


def _match_household_or_family(question: str, resolved: dict) -> bool:
    return bool(_HOUSEHOLD_FAMILY.search(question or ""))


# ---- CM Elevate -------------------------------------------------------------
# any_money_amount_requested / any_time_period_requested are each listed
# FIRST in their sub-section, ahead of more specific money/time conditions
# (disbursement, sanctioned, subsidy, loan / trend, year-comparison, monthly
# breakdown, recency, forecast) — "first rule that fires wins" per the
# YAML's own file order. A naive broad regex here would always win and the
# more specific, better-tailored question texts below it would never
# surface. Both matchers therefore explicitly exclude the more specific
# conditions' own vocabulary, so those get first refusal on their own
# phrasing and this one only catches money/time mentions none of them claim.
_MONEY_GENERIC = re.compile(
    r"\b(?:rs\.?|rupees?|amounts?|money|funding|expenditure|costs?|budgets?)\b",
    re.IGNORECASE)
_MONEY_SPECIFIC_TERMS = re.compile(
    r"\b(disburs\w*|sanction\w*|subsid\w*|loans?)\b", re.IGNORECASE)


def _match_any_money_amount(question: str, resolved: dict) -> bool:
    # Referenced here even though some are defined further down this module
    # — fine, since this function body only runs after the whole module
    # (including those later definitions) has finished loading. Excludes
    # every more specific money condition's own trigger dynamically rather
    # than hand-duplicating their vocabulary, so a new specific condition
    # added later can't silently be shadowed by this catch-all again.
    q = question or ""
    if (_MONEY_SPECIFIC_TERMS.search(q) or _SANCTIONED_DISBURSED_GAP.search(q)
            or _UNIT_COST_SUBSIDY_SHARE.search(q) or _PER_BENEFICIARY_AMOUNT.search(q)):
        return False
    return bool(_MONEY_GENERIC.search(q) or "₹" in q)


_DISBURSEMENT = re.compile(r"\bdisburs\w*\b", re.IGNORECASE)


def _match_disbursement(question: str, resolved: dict) -> bool:
    q = question or ""
    if _SANCTIONED_DISBURSED_GAP.search(q):
        return False
    return bool(_DISBURSEMENT.search(q))


_SANCTIONED_AMOUNT = re.compile(
    r"\bsanctioned\s+amounts?\b|\bamounts?\s+sanctioned\b|"
    r"\bhow\s+much\s+(?:was\s+)?sanctioned\b", re.IGNORECASE)


def _match_sanctioned_amount(question: str, resolved: dict) -> bool:
    return bool(_SANCTIONED_AMOUNT.search(question or ""))


_SUBSIDY = re.compile(r"\bsubsid\w*\b", re.IGNORECASE)


def _match_subsidy(question: str, resolved: dict) -> bool:
    return bool(_SUBSIDY.search(question or ""))


_LOAN_AMOUNT = re.compile(
    r"\bloan\s+amounts?\b|\bloans?\s+(?:disbursed|sanctioned|given|approved)\b|"
    r"\bhow\s+much\s+loan\b", re.IGNORECASE)


def _match_loan(question: str, resolved: dict) -> bool:
    return bool(_LOAN_AMOUNT.search(question or ""))


_SANCTIONED_DISBURSED_GAP = re.compile(
    r"\bsanctioned\s+(?:vs\.?|versus|and)\s+disbursed\b|"
    r"\bgap\s+between\s+sanctioned\s+and\s+disbursed\b|"
    r"\bfunding\s+pipelines?\b|\bpending\s+disbursements?\b", re.IGNORECASE)


def _match_sanctioned_vs_disbursed_gap(question: str, resolved: dict) -> bool:
    return bool(_SANCTIONED_DISBURSED_GAP.search(question or ""))


_UNIT_COST_SUBSIDY_SHARE = re.compile(
    r"\bunit\s+costs?\b|\bsubsidy\s+share\b|\bshare\s+of\s+(?:the\s+)?unit\s+cost\b",
    re.IGNORECASE)


def _match_unit_cost_or_subsidy_share(question: str, resolved: dict) -> bool:
    return bool(_UNIT_COST_SUBSIDY_SHARE.search(question or ""))


_PER_BENEFICIARY_AMOUNT = re.compile(
    r"\bper[\s-]?beneficiary\s+amounts?\b|"
    r"\bamounts?\s+per\s+(?:beneficiary|applicant|person)\b|"
    r"\baverage\s+amount\s+per\b", re.IGNORECASE)


def _match_per_beneficiary_amount(question: str, resolved: dict) -> bool:
    return bool(_PER_BENEFICIARY_AMOUNT.search(question or ""))


_TIME_GENERIC = re.compile(
    r"\bdates?\b|\bwhen\b|\btimelines?\b|\btime\s*periods?\b", re.IGNORECASE)
_TIME_SPECIFIC_TERMS = re.compile(
    r"\b(trend|growth|year[\s-]?(?:on[\s-]?year|wise|comparison)|"
    r"month(?:ly)?|quarter(?:ly)?|recent(?:ly)?|latest|newest|oldest|"
    r"forecast\w*|project(?:ion)?|request\s*id|application\s+number)\b",
    re.IGNORECASE)


def _match_any_time_period(question: str, resolved: dict) -> bool:
    q = question or ""
    if _TIME_SPECIFIC_TERMS.search(q):
        return False
    return bool(_TIME_GENERIC.search(q))


_TREND_GROWTH = re.compile(
    r"\btrends?\b|\bgrowth\b|\bincreasing\s+over\s+time\b|\btrajector\w+\b|"
    r"\bgrowing\b", re.IGNORECASE)


def _match_trend_or_growth(question: str, resolved: dict) -> bool:
    return bool(_TREND_GROWTH.search(question or ""))


_YEAR_COMPARISON = re.compile(
    r"\byear[\s-]?(?:on|over)[\s-]?year\b|\bcompare\s+years?\b|"
    r"\bthis\s+year\s+(?:vs\.?|versus|compared\s+to)\s+last\s+year\b|"
    r"\byear[\s-]?wise\s+comparison\b", re.IGNORECASE)


def _match_year_comparison(question: str, resolved: dict) -> bool:
    return bool(_YEAR_COMPARISON.search(question or ""))


_MONTHLY_BREAKDOWN = re.compile(
    r"\bmonthly\s+break\s*down\b|\bmonth[\s-]?wise\b|\bby\s+month\b|"
    r"\bper\s+month\b", re.IGNORECASE)


def _match_monthly_breakdown(question: str, resolved: dict) -> bool:
    return bool(_MONTHLY_BREAKDOWN.search(question or ""))


_RECENCY_LATEST = re.compile(
    r"\blatest\b|\bmost\s+recent\b|\bnewest\b|\boldest\b|\brecently\b",
    re.IGNORECASE)


def _match_recency_or_latest(question: str, resolved: dict) -> bool:
    return bool(_RECENCY_LATEST.search(question or ""))


_REQUEST_ID_DATE_PARSE = re.compile(
    r"\b(?:date|month|year)\s+from\s+(?:the\s+)?(?:request\s*id|"
    r"application\s+numbers?)\b|\bextract\s+(?:a\s+)?dates?\s+from\b|"
    r"\bparse\s+(?:a\s+)?dates?\s+from\s+(?:request\s*id|application\s+numbers?)\b",
    re.IGNORECASE)


def _match_request_id_date_parse_attempted(question: str, resolved: dict) -> bool:
    return bool(_REQUEST_ID_DATE_PARSE.search(question or ""))


_FORECAST = re.compile(
    r"\bforecast(?:s|ing)?\b|\bpredict(?:ion)?\b|\bproject(?:ion)?\b|"
    r"\bestimates?\s+for\s+(?:next|future)\b", re.IGNORECASE)


def _match_forecast(question: str, resolved: dict) -> bool:
    return bool(_FORECAST.search(question or ""))


_DESANCTIONED = re.compile(r"\bde[\s-]?sanctioned\b", re.IGNORECASE)


def _match_desanctioned(question: str, resolved: dict) -> bool:
    return bool(_DESANCTIONED.search(question or ""))


_REFUSED_REJECTED = re.compile(
    r"\brefus(?:ed|al)\b|\brejected\b|\brejections?\b|\bdenied\b", re.IGNORECASE)


def _match_refused_or_rejected(question: str, resolved: dict) -> bool:
    return bool(_REFUSED_REJECTED.search(question or ""))


_APPROVAL_STATUS = re.compile(r"\bapprov(?:ed|al)\b", re.IGNORECASE)


def _match_approval_status(question: str, resolved: dict) -> bool:
    return bool(_APPROVAL_STATUS.search(question or ""))


_BENEFICIARY_STATUS_OUTCOME = re.compile(
    r"\bdid\b.{0,40}\breceive\b|\bbeneficiary\s+status\b|"
    r"\boutcome\s+for\s+(?:the\s+)?applicant\b|"
    r"\bwhether\s+(?:the\s+)?beneficiary\b", re.IGNORECASE)


def _match_beneficiary_status(question: str, resolved: dict) -> bool:
    return bool(_BENEFICIARY_STATUS_OUTCOME.search(question or ""))


# ── Phase 2 (backlog-clarification-rule-engine-phase-2) ─────────────────────
# "which measure" / ambiguous-vocabulary category: 27 unique matchers for 33
# nominal scheme-condition instances. AUTHORED-PENDING-SME-REVIEW, same
# standing caveat as Phase 1.
#
# DELIBERATELY NOT WIRED (see this change's design.md for the full
# reasoning, found during design/authoring, not before):
# - "vague_qualifier" (all 4 schemes): its authored question text embeds a
#   {value} placeholder meant to echo the user's own ambiguous term back —
#   a matcher's (question, resolved) -> bool signature has no channel to
#   supply that value for interpolation. Wiring it would either show a
#   literal broken "{value}" or require a registry change, both out of
#   scope for additive matcher authoring.
# - "ambiguous_expenditure_component" (MGNREGA), "sanctioned_reading_
#   unclear" (PMAY-G), "amount_reading_unclear" (Focus Plus): each keys on
#   that scheme's single flagship default query term ("expenditure",
#   "sanctioned", "amount"). Firing on every bare mention would demand a
#   clarification on the most common query shape in three of the four
#   schemes — a severe regression, not the "under-fires on a rarer
#   phrasing" trade-off accepted for the shared names below. A correct,
#   narrow version needs a product/SME judgment call about which phrasings
#   still deserve the implicit default reading — not a session's own guess.

# ---- Shared across schemes (registry is name-keyed, not scheme-keyed — ───
# see clarification_engine module docstring for why a single matcher must
# work for every scheme whose YAML defines the name). Deliberately
# conservative: fires only when ranking/trend/count language is present AND
# none of a broad, cross-scheme union of metric/subject nouns is named —
# biases toward under-firing (a less-refined but not wrong answer) over
# over-firing on a legitimately answerable question.
_RANKING_CUE_P2 = re.compile(
    r"\b(top|bottom|highest|lowest|most|least|best|worst|leading|"
    r"rank(?:ed|ing)?|largest|smallest|biggest|maximum|minimum)\b",
    re.IGNORECASE)
_TREND_CUE_P2 = re.compile(
    r"\btrends?\b|\bover\s+time\b|\bgrowth\b|\byear[\s-]?(?:on|over)"
    r"[\s-]?year\b|\bincreasing\b|\bdecreasing\b|\bgrowing\b", re.IGNORECASE)
_ANY_NAMED_METRIC_P2 = re.compile(
    r"\b(expenditure|wages?|costs?|amounts?|disburs\w*|released|sanctioned|"
    r"completed|subsid\w*|loans?|houses?|person-?days?|persons?\s+employed|"
    r"households?\s+employed|applications?|completion\s+rate|percentage|"
    r"percent|shares?|payments?|job\s*cards?)\b", re.IGNORECASE)


def _match_missing_metric_for_ranking(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _RANKING_CUE_P2.search(q):
        return False
    if _ANY_NAMED_METRIC_P2.search(q):
        return False
    # Defers to the more specific CM-Elevate-only biggest_scheme_ambiguous
    # (referenced here even though defined later — fine, this function only
    # runs after the whole module has loaded) — "biggest scheme" already
    # names its own grouping unambiguously and has its own, more precisely
    # worded condition; this shared, cross-scheme matcher should not shadow
    # it. Found via testing, not assumed correct on first write.
    if _BIGGEST_SCHEME.search(q):
        return False
    return True


def _match_missing_metric_for_trend(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _TREND_CUE_P2.search(q):
        return False
    return not _ANY_NAMED_METRIC_P2.search(q)


_COUNT_CUE_P2 = re.compile(
    r"\bhow\s+many\b|\bcount\s+of\b|\bnumber\s+of\b|\btotal\s+count\b",
    re.IGNORECASE)
_SUBJECT_NOUN_P2 = re.compile(
    r"\b(villages?|households?|persons?|people|applicants?|applications?|"
    r"job\s*cards?|schemes?|blocks?|districts?|beneficiar\w+|members?|"
    r"houses?|payments?|farmers?)\b", re.IGNORECASE)


def _match_ambiguous_count_subject(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _COUNT_CUE_P2.search(q):
        return False
    return not _SUBJECT_NOUN_P2.search(q)


_RATE_WORD_P2 = re.compile(r"\b(rate|proportion|shares?)\b", re.IGNORECASE)
_RATE_DISAMBIGUATED_P2 = re.compile(
    r"\b(percentage|percent|%|number\s+of|count\s+of)\b", re.IGNORECASE)


def _match_rate_vs_count_unclear(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _RATE_WORD_P2.search(q):
        return False
    return not _RATE_DISAMBIGUATED_P2.search(q)


# ---- MGNREGA-unique ---------------------------------------------------
_BENEFICIARY_WORD = re.compile(r"\bbeneficiar(?:y|ies)\b", re.IGNORECASE)
_HH_OR_PERSON_QUALIFIER = re.compile(
    r"\bhouseholds?\b|\bpersons?\b|\bpeople\b|\bindividuals?\b", re.IGNORECASE)


def _match_ambiguous_beneficiary(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _BENEFICIARY_WORD.search(q):
        return False
    return not _HH_OR_PERSON_QUALIFIER.search(q)


_EMPLOYMENT_WORD = re.compile(r"\bemployment\b|\bemployed\b", re.IGNORECASE)
_EMPLOYMENT_QUALIFIER = re.compile(
    r"\bpersons?\s+employed\b|\bhouseholds?\s+employed\b|\bperson-?days?\b",
    re.IGNORECASE)


def _match_ambiguous_employment_measure(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _EMPLOYMENT_WORD.search(q):
        return False
    return not _EMPLOYMENT_QUALIFIER.search(q)


_WAGES_WORD = re.compile(r"\bwages?\b", re.IGNORECASE)
_WAGES_QUALIFIER = re.compile(
    r"\bunskilled\b|\bsemi-?skilled\b|\bskilled\b", re.IGNORECASE)


def _match_ambiguous_wages(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _WAGES_WORD.search(q):
        return False
    return not _WAGES_QUALIFIER.search(q)


_HUNDRED_DAYS = re.compile(
    r"\b(?:100|hundred)\s*-?\s*days?\b", re.IGNORECASE)


def _match_ambiguous_hundred_days(question: str, resolved: dict) -> bool:
    return bool(_HUNDRED_DAYS.search(question or ""))


# ---- PMAY-G-unique ------------------------------------------------------
_EFFICIENCY_WORD = re.compile(r"\befficien(?:t|cy)\b", re.IGNORECASE)


def _match_efficiency_term_unclear(question: str, resolved: dict) -> bool:
    return bool(_EFFICIENCY_WORD.search(question or ""))


_PROGRESS_WORD = re.compile(
    r"\bhow\s+much\s+progress\b|\bwhat\s+is\s+the\s+progress\b|"
    r"\bprogress\s+(?:so\s+far|made|status)\b", re.IGNORECASE)


def _match_ambiguous_progress_term(question: str, resolved: dict) -> bool:
    return bool(_PROGRESS_WORD.search(question or ""))


_PENDING_WORD = re.compile(r"\bpending\b", re.IGNORECASE)
_PENDING_QUALIFIER = re.compile(
    r"\bpending\s+houses?\b|\bpending\s+amounts?\b|\bhouses?\s+pending\b|"
    r"\bamounts?\s+pending\b", re.IGNORECASE)


def _match_ambiguous_pending_houses_or_amount(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _PENDING_WORD.search(q):
        return False
    return not _PENDING_QUALIFIER.search(q)


_STATUS_GROUP_AMBIGUOUS = re.compile(
    r"\bnot\s+(?:yet\s+)?completed\b|\bincomplete\b|\bunder\s+construction\b|"
    r"\bin\s+progress\b|\bstill\s+pending\b", re.IGNORECASE)


def _match_ambiguous_status_group(question: str, resolved: dict) -> bool:
    return bool(_STATUS_GROUP_AMBIGUOUS.search(question or ""))


_WOMEN_OWNERSHIP = re.compile(
    r"\bwomen(?:'s|’s)?\s+(?:owned|ownership|allotted|allotment)\b|"
    r"\bhouses?\b.{0,20}\ballotted\s+to\s+women\b", re.IGNORECASE)
_WOMEN_OWNERSHIP_QUALIFIER = re.compile(
    r"\balone\b|\bsolely\b|\bjoint(?:ly)?\b|\bincluding\b", re.IGNORECASE)


def _match_women_ownership_scope_unclear(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _WOMEN_OWNERSHIP.search(q):
        return False
    return not _WOMEN_OWNERSHIP_QUALIFIER.search(q)


# ---- Focus Plus-unique --------------------------------------------------
# Requires an aggregate/count framing ("how many beneficiaries", "number of
# beneficiaries", "beneficiary count") rather than any bare mention of the
# word — a narrower trigger than the MGNREGA-flavored ambiguous_beneficiary
# above, found necessary during testing: a bare mention (e.g. "which ward
# is this beneficiary from?") is a geography question that happens to use
# the word "beneficiary" incidentally, not a request to count/measure
# beneficiaries, and must not shadow below_village_geography_requested or
# any other more specific condition later in this scheme's file order.
_BENEFICIARY_WORD_FP = re.compile(
    r"\b(?:how\s+many|number\s+of|count\s+of|total)\b.{0,20}"
    r"\bbeneficiar(?:y|ies)\b|\bbeneficiar(?:y|ies)\s+count\b", re.IGNORECASE)
_BENEFICIARY_QUALIFIER_FP = re.compile(
    r"\bpayments?\b|\bmembers?\s+with\s+(?:an\s+)?id\b|\blegacy\b|"
    r"\bnewer\s+batch\b", re.IGNORECASE)


def _match_beneficiary_reading_unclear(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _BENEFICIARY_WORD_FP.search(q):
        return False
    return not _BENEFICIARY_QUALIFIER_FP.search(q)


def _match_count_subject_unclear(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _COUNT_CUE_P2.search(q):
        return False
    return not _SUBJECT_NOUN_P2.search(q)


_FARMERS_WORD = re.compile(r"\bfarmers?\b", re.IGNORECASE)
_FARMERS_QUALIFIER = re.compile(
    r"\brecorded\s+occupation\b|\boccupation\s+(?:is|=)\s*farmer\b|"
    r"\beveryone\b|\ball\s+(?:members|beneficiaries)\b", re.IGNORECASE)


def _match_farmers_vs_beneficiaries(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _FARMERS_WORD.search(q):
        return False
    return not _FARMERS_QUALIFIER.search(q)


_PERFORMANCE_GAP_WORD = re.compile(
    r"\bperformance\s+gap\b|\bcoverage\s+gap\b|\bgap\s+in\s+coverage\b|"
    r"\bunderperforming\b|\bwhich\s+(?:villages|districts)\s+(?:have\s+)?a?\s*gap\b",
    re.IGNORECASE)


def _match_performance_or_gap_term_unclear(question: str, resolved: dict) -> bool:
    return bool(_PERFORMANCE_GAP_WORD.search(question or ""))


_ANOMALY_WORD = re.compile(
    r"\banomal\w+|\boutliers?\b|\bunusual(?:ly)?\b", re.IGNORECASE)


def _match_anomaly_or_outlier_definition_unclear(question: str, resolved: dict) -> bool:
    return bool(_ANOMALY_WORD.search(question or ""))


_DUPLICATE_WORD = re.compile(r"\bduplicates?\b|\bduplicated\b", re.IGNORECASE)


def _match_duplicate_definition_unclear(question: str, resolved: dict) -> bool:
    return bool(_DUPLICATE_WORD.search(question or ""))


_CONCENTRATION_THRESHOLD = re.compile(
    r"\bconcentrated\b|\bconcentration\b|\btop\s+(?:one|three|\d+)\s+"
    r"(?:share|percentage)\b", re.IGNORECASE)


def _match_concentration_threshold_missing(question: str, resolved: dict) -> bool:
    return bool(_CONCENTRATION_THRESHOLD.search(question or ""))


_SIGNIFICANCE_COMPARABILITY = re.compile(
    r"\bcompared\s+(?:to|against|with)\s+what\b|\bis\s+this\s+(?:good|high|"
    r"low|significant)\b|\bsignificant(?:ly)?\b", re.IGNORECASE)


def _match_significance_or_comparability_unclear(question: str, resolved: dict) -> bool:
    return bool(_SIGNIFICANCE_COMPARABILITY.search(question or ""))


# ---- CM Elevate-unique ---------------------------------------------------
_BIGGEST_SCHEME = re.compile(
    r"\bbiggest\b.{0,20}\bschemes?\b|\bschemes?\b.{0,20}\bbiggest\b",
    re.IGNORECASE)


def _match_biggest_scheme_ambiguous(question: str, resolved: dict) -> bool:
    return bool(_BIGGEST_SCHEME.search(question or ""))


_SHARE_DENOMINATOR = re.compile(
    r"\bshares?\s+of\b|\bpercentage\s+of\b|\b%\s+of\b", re.IGNORECASE)
# Both `share_denominator_missing` and `ambiguous_average_denominator`
# (below) also exist, correctly, in MGNREGA/PMAY-G/Focus Plus's own "shape
# of the answer" sections (outside this phase's nominal CM-Elevate-only
# design) — same shared-name-registry side effect Phase 1 documented,
# caught here by checking each scheme's own YAML rather than assumed.
# Each scheme's own valid denominator wording differs (MGNREGA: "district
# total, state total"; PMAY-G: "district total, state total"; Focus Plus:
# "district total, batch total, state total"; CM Elevate: "scheme total,
# district total, all applications") — the qualifier below is the union of
# all four so the matcher isn't scheme-blind to a wording only three of the
# four schemes actually use.
_SHARE_DENOMINATOR_QUALIFIER = re.compile(
    r"\bscheme\s+total\b|\bdistrict\s+total\b|\bstate\s+total\b|"
    r"\bbatch\s+total\b|\ball\s+applications?\b|\boverall\s+total\b",
    re.IGNORECASE)


def _match_share_denominator_missing(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _SHARE_DENOMINATOR.search(q):
        return False
    return not _SHARE_DENOMINATOR_QUALIFIER.search(q)


_AVERAGE_WORD = re.compile(r"\baverage\b|\bmean\b|\bper\s+capita\b", re.IGNORECASE)
# Union across all four schemes' valid "per X" denominators (MGNREGA: per
# village/year/household; PMAY-G: per house/village/year; Focus Plus: per
# member/village/block/tranche; CM Elevate: per scheme/district/block/
# village) — see _SHARE_DENOMINATOR_QUALIFIER's comment for why this must
# be a union, not just CM Elevate's own four words.
_AVERAGE_DENOMINATOR_QUALIFIER = re.compile(
    r"\bper\s+(?:scheme|district|block|village|house|year|household|"
    r"member|tranche)\b", re.IGNORECASE)


def _match_ambiguous_average_denominator(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _AVERAGE_WORD.search(q):
        return False
    return not _AVERAGE_DENOMINATOR_QUALIFIER.search(q)


_CONCENTRATION_MEASURE = re.compile(
    r"\bconcentration\b|\bconcentrated\b|\bdominance\b|\bdominant\s+scheme\b",
    re.IGNORECASE)


def _match_concentration_measure_unclear(question: str, resolved: dict) -> bool:
    return bool(_CONCENTRATION_MEASURE.search(question or ""))


_STATUS_SUBJECT_WORD = re.compile(r"\bstatus\b", re.IGNORECASE)
_STATUS_SUBJECT_QUALIFIER = re.compile(
    r"\bverification\s+(?:status|outcome)\b|\bworkflow\s+(?:status|level)\b|"
    r"\bfile\s+status\b|\bdata[\s_]verified\b", re.IGNORECASE)


def _match_ambiguous_status_subject(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _STATUS_SUBJECT_WORD.search(q):
        return False
    return not _STATUS_SUBJECT_QUALIFIER.search(q)


_APPLICANT_TYPE_WORD = re.compile(
    r"\bapplicant\s+types?\b|\bindividual\s+applicants?\b|"
    r"\bregistered\s+(?:bod(?:y|ies)|applicants?)\b|"
    r"\bunregistered\s+(?:bod(?:y|ies)|applicants?)\b", re.IGNORECASE)
_APPLICANT_TYPE_QUALIFIER = re.compile(
    r"\ball\s+three\b|\bindividual\s+only\b|\bcombined\b", re.IGNORECASE)


def _match_applicant_type_scope_unclear(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _APPLICANT_TYPE_WORD.search(q):
        return False
    return not _APPLICANT_TYPE_QUALIFIER.search(q)


# ── Phase 3 (backlog-clarification-rule-engine-phase-3) ─────────────────────
# "Measures/fields that exist but must not be reported as asked" — a column
# is real, but a plain reading of the question assumes a meaning it does not
# support (flat entitlement asked for as if it varies, a workflow-stage
# label asked for as if it were an approval, and scheme-specific
# equivalents). Same risk shape as the already-shipped
# _admin_expenditure_clarification / _women_share_clarification hardcoded
# predicates. AUTHORED-PENDING-SME-REVIEW, same standing caveat as Phases
# 1-2.
#
# Every condition here is scheme-unique (none of these names are shared
# verbatim across more than one scheme's YAML — checked directly, unlike
# Phases 1-2 which had several shared names), so each matcher below may
# safely assume its own scheme's specific vocabulary.
#
# DELIBERATELY NOT WIRED (found during authoring, not before — same
# standard as every prior phase's own exclusions):
# - PMAY-G `fuzzy_village_precision_warning`: its trigger is really "a
#   village-level breakdown was requested", not a specific misreading
#   phrase. "By village" / "village-wise" is one of PMAY-G's single most
#   common, entirely legitimate query shapes — firing on it would repeat
#   the "flagship default term" over-fire regression Phase 2's design.md
#   already identified and excluded for a different condition, not a new
#   risk being accepted here.
# - PMAY-G `singleton_category_focus`: any phrasing that would trigger it
#   ("Self"/"Woman" allotment category) also contains "woman", which
#   Phase 1's already-shipped, earlier-in-file-order `gender_column_
#   requested` matches first — check_clarifications is first-match-wins,
#   so this condition is structurally unreachable without editing already-
#   archived Phase 1 code, out of scope for a purely-additive phase.
# - Focus Plus `standard_payment_reading_unclear` and `average_payment_
#   requested`: both ask about "the payment"/"an average payment" with no
#   tranche named — that phrasing already trips `_needs_tranche_
#   clarification` in app/pipeline.py (its `_METRIC_OR_BREAKDOWN_CUE`
#   includes `payments?`) before this engine would ever see the question
#   with a specific-enough resolved state to add anything. Same "batch
#   duality" adjacency risk this phase's design.md already excluded the
#   whole batch-duality section for — found here to extend to two "money"
#   section conditions too.
# - CM Elevate `application_count_offered_as_money_proxy`: its own YAML
#   note calls it "a backstop for any_money_amount_requested" for when a
#   money intent "survives the earlier gates" — by definition a phrasing
#   any_money_amount_requested's already-broad regex does NOT catch, but
#   authoring a precise trigger for "money intent, unspecified form" without
#   just re-testing the same vocabulary ordering already excludes is not
#   achievable with reasonable confidence via a simple regex.
#
# Effective wired count: 20 of the 25 nominal conditions proposal.md
# scoped (MGNREGA 3, PMAY-G 7, Focus Plus 2, CM Elevate 8) — a correction
# recorded here and in tasks.md, not shipped silently, same as every prior
# phase's own authoring-time corrections.

# ---- MGNREGA -------------------------------------------------------------
_WOMEN_METRIC_2025_26 = re.compile(
    r"\bwomen\b.{0,25}\b(?:employment|employed|work)\b|"
    r"\b(?:employment|employed)\b.{0,25}\bwomen\b", re.IGNORECASE)
_FY_2025_26 = re.compile(
    r"\b2025-26\b|\b2025/26\b|\bfy\s*25-?26\b|\bfy\s*2025-?26\b", re.IGNORECASE)


def _match_women_metric_in_2025_26(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _WOMEN_METRIC_2025_26.search(q):
        return False
    if _FY_2025_26.search(q):
        return True
    return resolved.get("year_key") == "2025-26" or resolved.get("year_key") == 2025


_BENEFIT_TO_HOUSEHOLDS = re.compile(
    r"\bhousehold\s+benefits?\b|\bbenefits?\s+(?:provided|given)\s+to\s+households?\b",
    re.IGNORECASE)


def _match_benefit_to_households(question: str, resolved: dict) -> bool:
    return bool(_BENEFIT_TO_HOUSEHOLDS.search(question or ""))


_JOB_CARDS_WORD = re.compile(r"\bjob\s*cards?\b", re.IGNORECASE)
_MULTI_YEAR_SUM_CUE = re.compile(
    r"\ball[\s-]?(?:the\s+)?(?:financial |fiscal )?years?\b|"
    r"\bacross (?:all )?(?:the )?(?:financial |fiscal )?years?\b|"
    r"\bover (?:the )?years?\b|\bcumulative\b|\bsince inception\b|"
    r"\bto date\b|\btotal\s+over\b|\bcombined\s+(?:across|over)\b|"
    r"\ball[\s-]?time\b", re.IGNORECASE)


def _match_job_cards_across_multiple_years(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _JOB_CARDS_WORD.search(q):
        return False
    return bool(_MULTI_YEAR_SUM_CUE.search(q))


# ---- PMAY-G ---------------------------------------------------------------
_SANCTIONED_VARIATION = re.compile(
    r"\bsanctioned\s+amounts?\b.{0,30}\b(?:vary|varies|varying|differ\w*|"
    r"compar\w*|trend|highest|lowest|which\s+district)\b|"
    r"\b(?:vary|varies|varying|differ\w*|compar\w*|trend)\b.{0,30}"
    r"\bsanctioned\s+amounts?\b", re.IGNORECASE)


def _match_sanctioned_amount_variation(question: str, resolved: dict) -> bool:
    return bool(_SANCTIONED_VARIATION.search(question or ""))


_INSTALLMENT_AS_COMPLETION = re.compile(
    r"\binstal{1,2}ments?\b.{0,40}\bcomplet\w*\b|"
    r"\bcomplet\w*\b.{0,40}\binstal{1,2}ments?\b|"
    r"\ball\s+(?:three|3)\s+instal{1,2}ments?\b", re.IGNORECASE)


def _match_installment_or_release_as_completion_proof(question: str, resolved: dict) -> bool:
    return bool(_INSTALLMENT_AS_COMPLETION.search(question or ""))


_HOUSE_OCCUPANCY = re.compile(
    r"\boccupi(?:ed|ancy)\b|\bhanded\s*over\b|\blived\s+in\b|\bmoved\s+in\b|"
    r"\bpeople\s+living\b|\bliving\s+in\s+(?:the|these|those)\s+houses?\b",
    re.IGNORECASE)


def _match_house_status_as_occupancy(question: str, resolved: dict) -> bool:
    return bool(_HOUSE_OCCUPANCY.search(question or ""))


_COMPLETION_RATE_WORD = re.compile(r"\bcompletion\s+rate\b", re.IGNORECASE)
_PER_YEAR_BREAKDOWN_CUE = re.compile(
    r"\byear[\s-]?(?:wise|by[\s-]?year)\b|\bby\s+(?:financial\s+)?year\b|"
    r"\beach\s+year\b|\bper\s+year\b", re.IGNORECASE)


def _match_completion_rate_across_mixed_years(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _COMPLETION_RATE_WORD.search(q):
        return False
    if _PER_YEAR_BREAKDOWN_CUE.search(q):
        return False
    return not resolved.get("year_key")


_MAPPING_STATUS_PERFORMANCE = re.compile(
    r"\bmapping\s+(?:status|category)\b.{0,40}\b(?:performance|performing|"
    r"score|doing\s+well|progress)\b|"
    r"\b(?:performance|performing|score|doing\s+well|progress)\b.{0,40}"
    r"\bmapping\s+(?:status|category)\b", re.IGNORECASE)


def _match_mapping_status_as_performance(question: str, resolved: dict) -> bool:
    return bool(_MAPPING_STATUS_PERFORMANCE.search(question or ""))


_INDIVIDUAL_PERSON_TRACKING = re.compile(
    r"\btrack\b.{0,20}\b(?:beneficiary|person|individual)\b|"
    r"\bsearch\b.{0,15}\bname\b|\bbeneficiary\s+names?\b|"
    r"\bidentify\s+(?:the\s+)?(?:same\s+)?(?:person|beneficiary)\b|"
    r"\bfind\s+(?:this|the)\s+(?:beneficiary|person)\b", re.IGNORECASE)


def _match_individual_person_tracking(question: str, resolved: dict) -> bool:
    return bool(_INDIVIDUAL_PERSON_TRACKING.search(question or ""))


_PARENT_NAME_FILTER = re.compile(
    r"\b(?:father|mother|parent|guardian)(?:'s|’s)?\s+names?\b", re.IGNORECASE)


def _match_parent_name_filter(question: str, resolved: dict) -> bool:
    return bool(_PARENT_NAME_FILTER.search(question or ""))


# ---- Focus Plus -------------------------------------------------------------
_MONEY_UNIT_QUESTION = re.compile(
    r"\bunit\b.{0,20}\b(?:amount|money|figure|rupees?)\b|"
    r"\bwhat\s+(?:currency|unit)\b|\brupees?\s+or\s+lakhs?\b|"
    r"\bis\s+this\s+in\s+rupees\b|\bcurrency\b", re.IGNORECASE)


def _match_money_unit_unconfirmed(question: str, resolved: dict) -> bool:
    return bool(_MONEY_UNIT_QUESTION.search(question or ""))


_MONEY_WORD_FP = re.compile(
    r"\b(?:money|amounts?|funding|rupees?|rs\.?)\b", re.IGNORECASE)
_SCHEME_NAME_MENTION = re.compile(
    r"\bfocus\s*\+?plus\b|\bmgnrega\b|\bnrega\b|\bpmay(?:-?g)?\b|\bcm\s*elevate\b",
    re.IGNORECASE)


def _match_money_across_schemes_unit_mismatch(question: str, resolved: dict) -> bool:
    q = question or ""
    if not _MONEY_WORD_FP.search(q):
        return False
    return len(set(m.lower() for m in _SCHEME_NAME_MENTION.findall(q))) >= 2


# ---- CM Elevate -------------------------------------------------------------
_APPLICATION_READ_AS_AWARD = re.compile(
    r"\bapplications?\b.{0,40}\breceived\s+(?:the\s+)?(?:scheme|benefit|"
    r"funds?|money|amount)\b|\bapplications?\b.{0,40}\b(?:were|got)\s+"
    r"funded\b|\bsuccessfully\s+funded\b", re.IGNORECASE)


def _match_application_read_as_award(question: str, resolved: dict) -> bool:
    return bool(_APPLICATION_READ_AS_AWARD.search(question or ""))


_BENEFICIARY_WORD_CM = re.compile(r"\bbeneficiar(?:y|ies)\b", re.IGNORECASE)


def _match_beneficiary_term_used(question: str, resolved: dict) -> bool:
    return bool(_BENEFICIARY_WORD_CM.search(question or ""))


_FORWARD_AS_APPROVED = re.compile(
    r"\b(?:forward(?:ed)?|current\s+file\s+status)\b.{0,30}\b(?:approv\w*|"
    r"pipeline)\b|\bapprov\w*\b.{0,30}\bforward(?:ed)?\b", re.IGNORECASE)


def _match_forward_status_read_as_approved(question: str, resolved: dict) -> bool:
    return bool(_FORWARD_AS_APPROVED.search(question or ""))


_LEVEL_AS_PROGRESS = re.compile(
    r"\blevel\s*\d?\b.{0,30}\bprogress\b|\bprogress\b.{0,30}\blevel\s*\d?\b|"
    r"\bhow\s+far\s+along\b.{0,20}\blevel\b", re.IGNORECASE)


def _match_current_level_read_as_progress(question: str, resolved: dict) -> bool:
    return bool(_LEVEL_AS_PROGRESS.search(question or ""))


_VERIFIED_AS_FUNDING = re.compile(
    r"\bverif(?:ied|ication)\b.{0,30}\b(?:fund\w*|approv\w*|reject\w*)\b",
    re.IGNORECASE)


def _match_data_verified_read_as_funding_decision(question: str, resolved: dict) -> bool:
    return bool(_VERIFIED_AS_FUNDING.search(question or ""))


_TYPE_RAW_GROUPING = re.compile(
    r"\b(?:applicant|application)s?\b.{0,20}\btypes?\b", re.IGNORECASE)


def _match_type_raw_grouping_across_schemes(question: str, resolved: dict) -> bool:
    return bool(_TYPE_RAW_GROUPING.search(question or ""))


_LEVEL_CASE_VARIANTS = re.compile(
    r"\blevel\b.{0,15}\b(?:wise|breakdown|group(?:ed|ing)?|distribution)\b|"
    r"\bby\s+level\b|\beach\s+level\b|"
    r"\bhow\s+many\b.{0,20}\bat\s+(?:each\s+)?level\b", re.IGNORECASE)


def _match_current_level_case_variants(question: str, resolved: dict) -> bool:
    return bool(_LEVEL_CASE_VARIANTS.search(question or ""))


_SENDBACK_VARIANTS = re.compile(r"\bsend\s*back\b|\bsent\s*back\b", re.IGNORECASE)


def _match_sendback_wording_variants(question: str, resolved: dict) -> bool:
    return bool(_SENDBACK_VARIANTS.search(question or ""))


_MATCHERS: dict[str, Callable[[str, dict], bool]] = {
    # MGNREGA
    "finer_than_financial_year_requested": _match_finer_than_fy,
    "pending_dues_requested": _match_pending_dues,
    "fund_availability_requested": _match_fund_availability,
    "works_or_assets_requested": _match_works_or_assets,
    "wage_rate_requested": _match_wage_rate,
    "per_capita_requested": _match_per_capita,
    "budget_vs_actual_requested": _match_budget_vs_actual,
    "individual_person_requested": _match_individual_person,
    "other_scheme_requested": _match_other_scheme_requested,
    # PMAY-G
    "pmay_urban_requested": _match_pmay_urban,
    "other_state_comparison_requested": _match_other_state_comparison,
    "centre_state_share_requested": _match_centre_state_share,
    "material_labour_cost_split_requested": _match_material_labour_split,
    "budget_or_target_requested": _match_budget_or_target,
    "saturation_or_coverage_requested": _match_saturation_or_coverage,
    "beneficiary_income_or_caste_requested": _match_beneficiary_income_or_caste,
    "gender_column_requested": _match_gender_column,
    "age_or_disability_requested": _match_age_or_disability,
    "land_ownership_requested": _match_land_ownership,
    "house_specification_requested": _match_house_specification,
    "convergence_benefits_requested": _match_convergence_benefits,
    "geotag_or_inspection_requested": _match_geotag_or_inspection,
    "grievance_status_requested": _match_grievance_status,
    "contractor_or_agency_requested": _match_contractor_or_agency,
    "waitlist_or_selection_requested": _match_waitlist_or_selection,
    "cancelled_or_rejected_houses_requested": _match_cancelled_or_rejected_houses,
    "stalled_houses_requested": _match_stalled_houses,
    "installment_dates_requested": _match_installment_dates,
    "completion_or_release_date_requested": _match_completion_or_release_date,
    "employment_or_wages_requested": _match_employment_or_wages,
    "personal_contact_details_requested": _match_personal_contact_details,
    "below_village_geography_requested": _match_below_village_geography,
    # villages_without_houses_requested: deliberately NOT wired — see note above.
    # Focus Plus
    "epic_id_requested": _match_epic_id,
    "beneficiary_name_requested": _match_beneficiary_name,
    "mobile_number_requested": _match_mobile_number,
    "payment_date_requested": _match_payment_date,
    "monthly_or_quarterly_analysis_requested": _match_monthly_or_quarterly_analysis,
    "farmer_id_nic_requested": _match_farmer_id_nic,
    "eligible_population_or_coverage_rate_requested": _match_eligible_population_or_coverage_rate,
    "constituency_or_mla_requested": _match_constituency_or_mla,
    "budget_target_or_allocation_requested": _match_budget_target_or_allocation,
    "forecast_or_projection_requested": _match_forecast_or_projection,
    "other_scheme_or_dataset_requested": _match_other_scheme_or_dataset,
    "urban_or_other_state_requested": _match_urban_or_other_state,
    "caste_income_or_bpl_requested": _match_caste_income_or_bpl,
    "household_or_family_requested": _match_household_or_family,
    # CM Elevate
    "any_money_amount_requested": _match_any_money_amount,
    "disbursement_requested": _match_disbursement,
    "sanctioned_amount_requested": _match_sanctioned_amount,
    "subsidy_requested": _match_subsidy,
    "loan_requested": _match_loan,
    "sanctioned_vs_disbursed_gap_requested": _match_sanctioned_vs_disbursed_gap,
    "unit_cost_or_subsidy_share_requested": _match_unit_cost_or_subsidy_share,
    "per_beneficiary_amount_requested": _match_per_beneficiary_amount,
    "any_time_period_requested": _match_any_time_period,
    "trend_or_growth_requested": _match_trend_or_growth,
    "year_comparison_requested": _match_year_comparison,
    "monthly_breakdown_requested": _match_monthly_breakdown,
    "recency_or_latest_requested": _match_recency_or_latest,
    "request_id_date_parse_attempted": _match_request_id_date_parse_attempted,
    "forecast_requested": _match_forecast,
    "desanctioned_requested": _match_desanctioned,
    "refused_or_rejected_requested": _match_refused_or_rejected,
    "approval_status_requested": _match_approval_status,
    "beneficiary_status_requested": _match_beneficiary_status,
    # Phase 2 — shared across schemes
    "missing_metric_for_ranking": _match_missing_metric_for_ranking,
    "missing_metric_for_trend": _match_missing_metric_for_trend,
    "ambiguous_count_subject": _match_ambiguous_count_subject,
    "rate_vs_count_unclear": _match_rate_vs_count_unclear,
    # Phase 2 — MGNREGA-unique
    "ambiguous_beneficiary": _match_ambiguous_beneficiary,
    "ambiguous_employment_measure": _match_ambiguous_employment_measure,
    "ambiguous_wages": _match_ambiguous_wages,
    "ambiguous_hundred_days": _match_ambiguous_hundred_days,
    # Phase 2 — PMAY-G-unique
    "efficiency_term_unclear": _match_efficiency_term_unclear,
    "ambiguous_progress_term": _match_ambiguous_progress_term,
    "ambiguous_pending_houses_or_amount": _match_ambiguous_pending_houses_or_amount,
    "ambiguous_status_group": _match_ambiguous_status_group,
    "women_ownership_scope_unclear": _match_women_ownership_scope_unclear,
    # Phase 2 — Focus Plus-unique
    "beneficiary_reading_unclear": _match_beneficiary_reading_unclear,
    "count_subject_unclear": _match_count_subject_unclear,
    "farmers_vs_beneficiaries": _match_farmers_vs_beneficiaries,
    "performance_or_gap_term_unclear": _match_performance_or_gap_term_unclear,
    "anomaly_or_outlier_definition_unclear": _match_anomaly_or_outlier_definition_unclear,
    "duplicate_definition_unclear": _match_duplicate_definition_unclear,
    "concentration_threshold_missing": _match_concentration_threshold_missing,
    "significance_or_comparability_unclear": _match_significance_or_comparability_unclear,
    # Phase 2 — CM Elevate-unique
    "biggest_scheme_ambiguous": _match_biggest_scheme_ambiguous,
    "share_denominator_missing": _match_share_denominator_missing,
    "ambiguous_average_denominator": _match_ambiguous_average_denominator,
    "concentration_measure_unclear": _match_concentration_measure_unclear,
    "ambiguous_status_subject": _match_ambiguous_status_subject,
    "applicant_type_scope_unclear": _match_applicant_type_scope_unclear,
    # Deliberately NOT wired: vague_qualifier (all schemes),
    # ambiguous_expenditure_component (MGNREGA), sanctioned_reading_unclear
    # (PMAY-G), amount_reading_unclear (Focus Plus) — see design.md.
    # Phase 3 — MGNREGA
    "women_metric_in_2025_26": _match_women_metric_in_2025_26,
    "benefit_to_households_requested": _match_benefit_to_households,
    "job_cards_across_multiple_years": _match_job_cards_across_multiple_years,
    # Phase 3 — PMAY-G
    "sanctioned_amount_variation_requested": _match_sanctioned_amount_variation,
    "installment_or_release_as_completion_proof": _match_installment_or_release_as_completion_proof,
    "house_status_as_occupancy": _match_house_status_as_occupancy,
    "completion_rate_across_mixed_years": _match_completion_rate_across_mixed_years,
    "mapping_status_as_performance": _match_mapping_status_as_performance,
    "individual_person_tracking_requested": _match_individual_person_tracking,
    "parent_name_filter_requested": _match_parent_name_filter,
    # Deliberately NOT wired: fuzzy_village_precision_warning,
    # singleton_category_focus — see the Phase 3 section note above.
    # Phase 3 — Focus Plus
    "money_unit_unconfirmed": _match_money_unit_unconfirmed,
    "money_across_schemes_unit_mismatch": _match_money_across_schemes_unit_mismatch,
    # Deliberately NOT wired: standard_payment_reading_unclear,
    # average_payment_requested — see the Phase 3 section note above.
    # Phase 3 — CM Elevate
    "application_read_as_award": _match_application_read_as_award,
    "beneficiary_term_used": _match_beneficiary_term_used,
    "forward_status_read_as_approved": _match_forward_status_read_as_approved,
    "current_level_read_as_progress": _match_current_level_read_as_progress,
    "data_verified_read_as_funding_decision": _match_data_verified_read_as_funding_decision,
    "type_raw_grouping_across_schemes": _match_type_raw_grouping_across_schemes,
    "current_level_case_variants": _match_current_level_case_variants,
    "sendback_wording_variants": _match_sendback_wording_variants,
    # Deliberately NOT wired: application_count_offered_as_money_proxy,
    # gender_breakdown_requested (answerable per its own YAML note) — see
    # the Phase 3 section note above.
}


class _SafePlaceholder(dict):
    """`str.format_map` support that leaves an unresolvable `{placeholder}`
    literal instead of raising — a question template missing its
    interpolation context should still surface (degraded, not absent), and
    must never turn a UI-facing clarification into a 500."""

    def __missing__(self, key):  # noqa: D105
        return "{" + key + "}"


def _format_question(text: str, resolved: dict) -> str:
    try:
        return text.format_map(_SafePlaceholder(resolved or {}))
    except Exception:  # noqa: BLE001 — a stray brace in curated text, etc.
        return text


def check_clarifications(question: str, schemes: list[str], resolved: dict) -> "str | None":
    """First-match-wins clarifying-question text for `question`, checked
    against every scheme in `schemes` in order, and within each scheme in
    that scheme's own `*_classification_rules.yaml` file order. Returns
    `None` when nothing in the currently-wired `_MATCHERS` registry matches
    — including when `_MATCHERS` is empty, a scheme's rules file is
    missing/malformed, or every matched condition collides with an existing
    hardcoded clarification predicate. Never raises."""
    for scheme in schemes or []:
        # Focus Plus's rules describe individual-farmer payments
        # (curated.v_focus_plus: beneficiaries, batches, "count of what").
        # A producer-group question reads curated.v_focus_legacy instead, where
        # none of them apply; its PII columns stay blocked by pii_guard.
        if scheme == "Focus Plus" and _PG_QUESTION.search(question or ""):
            continue
        conditions = _load_scheme_rules(scheme)
        for name, rule in conditions.items():
            if name in _COLLISION_CONDITIONS:
                continue
            matcher = _MATCHERS.get(name)
            if matcher is None:
                continue
            try:
                if not matcher(question, resolved or {}):
                    continue
            except Exception:  # noqa: BLE001 — a matcher must never abort the turn
                logger.warning("clarification_engine: matcher for %s failed", name, exc_info=True)
                continue
            text = _format_question(rule.get("question", ""), resolved or {})
            if text:
                return text
    return None
