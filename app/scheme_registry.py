"""
The six schemes, in one place (RAG plan E5; user decision 2026-10-27, D-079).

Scheme names were hand-kept in ~124 places across 31 files (mapped 2026-10-27; the
"Adding a scheme" list in docs/SCHEMES.md had grown stale). This module is the one
source of truth for the FACTS about each scheme. Two kinds of code use it:

- pure name lists read it directly (auth roles, the measure-holder set, the query
  plan, the metric catalogue's subject map);
- every other registry keeps its own shape (matchers, fuzzy aliases, the Focus /
  CM Elevate collision rules, prose) and is checked against this module by
  tests/test_scheme_registry_e5_2026_10_27.py, which fails on any drift.

Data only: no app imports, so any module can import it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scheme:
    name: str                 # the canonical name every stage uses
    subject_area: str         # semantic.metric_definitions.subject_area
    kb_folder: str            # data/incoming/<kb_folder>/
    kb_tag: str               # the knowledge-base scheme tag (Legacy shares CM Elevate's docs)
    main_view: str            # the curated view its records are counted on
    doc_label: str            # how the reference documents name it
    records_constituency: bool  # an assembly-constituency figure is answerable


SCHEMES: tuple[Scheme, ...] = (
    Scheme("MGNREGA", "mgnrega", "MGNREGA", "MGNREGA", "curated.v_employment", "MGNREGA", True),
    Scheme("PMAY-G", "pmay", "PMAY-G", "PMAY-G", "curated.v_pmay", "PMAY-G", True),
    Scheme("Focus Plus", "focus_plus", "Focus_Plus", "Focus Plus", "curated.v_focus_plus", "FOCUS+", False),
    Scheme("CM Elevate", "cm_elevate", "CM_Elevate", "CM Elevate", "curated.v_cm_elevate", "CM-ELEVATE", True),
    Scheme("Focus Legacy", "focus_legacy", "Focus_Legacy", "Focus Legacy", "curated.v_focus_legacy", "FOCUS", True),
    Scheme("CM Elevate Legacy", "cm_elevate_disbursement", "CM_Elevate_Legacy", "CM Elevate",
           "curated.v_cm_elevate_disbursement", "CM-ELEVATE", True),
    Scheme("CMSS", "cmss", "CMSS", "CMSS", "curated.v_cmss", "CMSS", True),
    Scheme("Homestay", "homestay_api", "Homestay", "Home Stay", "curated.v_homestay_api", "Homestay", True),
)

NAMES: tuple[str, ...] = tuple(s.name for s in SCHEMES)
BY_NAME: dict[str, Scheme] = {s.name: s for s in SCHEMES}
SUBJECT_TO_SCHEME: dict[str, str] = {s.subject_area: s.name for s in SCHEMES}


# ── Dataset facts: one registry for the chat answers and the dashboard cards ──
# Data-accuracy brief 2026-10-29 (RC5): the cards knew the caveats ("figures
# provisional", the "*" on amounts, "no date/amount data") and the chat answers
# did not. These are the FIXED facts of each dataset, from curated.dim_scheme
# (money_unit, grain_note) and docs/DATA_MODEL.md §3. The years each dataset holds
# are NOT here: they change with every load and are read live from megh_db
# (pipeline _SCHEME_DATA_YEARS, refreshed at startup).
@dataclass(frozen=True)
class DatasetFacts:
    grain: str                    # what one row is
    money_unit: "str | None"      # "rupees" / "lakh"; None = the dataset holds no money
    money_verified: bool          # the department confirmed the unit (dim_scheme.money_unit)
    provisional: bool             # its money figures are provisional (the cards' "*")
    has_dates: bool               # a year / date column exists
    sub_scheme_column: "str | None"   # "which scheme" inside this dataset reads this column
    owned_tables: "tuple[str, ...]"   # curated tables / views only this dataset's questions read
    not_held: str = ""            # what the dataset does not record, said plainly


DATASETS: dict[str, DatasetFacts] = {
    "MGNREGA": DatasetFacts(
        "one source row of the employment / expenditure workbooks (village-year)", "lakh", True, False, True, None,
        ("v_employment", "v_expenditure", "v_district_year_summary", "fact_mgnrega_employment",
         "fact_mgnrega_expenditure")),
    "PMAY-G": DatasetFacts(
        "one sanctioned house", "rupees", True, False, True, None,
        ("v_pmay", "v_pmay_monthly_sanctions", "fact_pmay_house")),
    "Focus Plus": DatasetFacts(
        "one payment (beneficiary x tranche)", "rupees", False, True, True, None,
        ("v_focus_plus", "fact_focus_plus_disbursement")),
    "CM Elevate": DatasetFacts(
        "one application", None, True, False, False, "scheme_name",
        ("v_cm_elevate", "fact_cm_elevate_application", "dim_cm_elevate_scheme"),
        not_held="CM Elevate (applications) records no amounts and no dates; CM Elevate Legacy holds the "
                 "sanctioned and disbursed amounts by financial year"),
    "Focus Legacy": DatasetFacts(
        "one payment to a producer group", "rupees", False, True, True, None,
        ("v_focus_legacy", "dim_producer_group", "dim_pg_entity_type")),
    "CM Elevate Legacy": DatasetFacts(
        "one applicant's sanction and disbursement record", "rupees", False, True, True, "scheme_name",
        ("v_cm_elevate_disbursement", "dim_cm_elevate_disb_scheme")),
    "CMSS": DatasetFacts("one row per student application (paid or not); each student (member_key) appears once. COUNT(*) = applications, COUNT(*) FILTER (WHERE is_disbursed) = students paid, SUM(amount_disbursed) = rupees paid.", "rupees", True, False, True, None, ("v_cmss",), not_held="CMSS records no gender, age, institution, course, student names, payment dates or the reason an application was not paid; only FY 2025-26 is held"),
    "Homestay": DatasetFacts("one row per homestay application (request_id, unique). COUNT(*) = applications; COUNT(DISTINCT member_key) = applicants (17 applicants have more than one application). Statuses are as at the extract (about 1 Nov 2026).", None, True, False, True, None, ("v_homestay_api",), not_held="Homestay (applications) records no money (project cost, subsidy, loan, sanction or disbursement), no operational or completed status, no project dates, no applicant names or contact details, and no reason for a rejection; Homestay Legacy holds the older bank-loan homestays"),
}


# ── What each scheme IS, beside its namesakes (knowledge fix 2026-10-29, KR6) ──
# "Is Focus Plus the same as Focus Legacy?" was answered "Focus Plus pays ₹5,000 to
# registered Producer Group members" — Focus Legacy's unit. Every knowledge answer
# about one of these schemes is told the line below (app/rag.py _naming_note), so a
# namesake's facts are never mixed in. From the reference documents in
# data/incoming/<scheme>/ (FAQ "What is FOCUS+?", "How much financial assistance does
# FOCUS provide?", the CM Elevate Legacy data reference).
KNOWLEDGE_DISTINCTIONS: dict[str, str] = {
    "Focus Plus": "FOCUS+ (Focus Plus) pays Rs 5,000 per HOUSEHOLD by DBT to households that are "
                  "Producer Group members; it is not the original FOCUS scheme (Focus Legacy), which "
                  "gives Rs 5,000 per Producer Group MEMBER as a grant.",
    "Focus Legacy": "FOCUS (Focus Legacy) gives Rs 5,000 per Producer Group MEMBER as a grant, not a loan; "
                    "it is not FOCUS+ (Focus Plus), which pays Rs 5,000 per HOUSEHOLD by DBT.",
    "CM Elevate": "CM-ELEVATE is the programme; CM Elevate Legacy is not a separate scheme but the "
                  "programme's sanction and disbursement records.",
    "CM Elevate Legacy": "CM Elevate Legacy is the CM-ELEVATE programme's sanction and disbursement "
                         "records, not a separate scheme; the programme's rules are CM-ELEVATE's.",
    "PMAY-G": "PMAY-G is the RURAL housing scheme (Gramin); it is not PMAY-Urban.",
    "MGNREGA": "MGNREGA (also NREGA, MGNREGS, the '100 days work' scheme) is the rural employment "
               "guarantee Act.",
    "CMSS": "CMSS (the Chief Minister's Scholarship Scheme) pays a flat Rs 6,000 a year to eligible students; it is a state scholarship, not the CM Elevate enterprise programme.",
    "Homestay": "Homestay (the Chief Minister's Meghalaya Homestay Mission, Tourism Department) supports building a new homestay or upgrading an existing one; this data is its online applications from October 2025, not the older Homestay Legacy bank loans.",
}
