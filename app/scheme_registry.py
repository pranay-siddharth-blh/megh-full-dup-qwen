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
    Scheme("PMAY-G", "pmay", "PMAY-G", "PMAY-G", "curated.v_pmay", "PMAY-G", False),
    Scheme("Focus Plus", "focus_plus", "Focus_Plus", "Focus Plus", "curated.v_focus_plus", "FOCUS+", False),
    Scheme("CM Elevate", "cm_elevate", "CM_Elevate", "CM Elevate", "curated.v_cm_elevate", "CM-ELEVATE", True),
    Scheme("Focus Legacy", "focus_legacy", "Focus_Legacy", "Focus Legacy", "curated.v_focus_legacy", "FOCUS", True),
    Scheme("CM Elevate Legacy", "cm_elevate_disbursement", "CM_Elevate_Legacy", "CM Elevate",
           "curated.v_cm_elevate_disbursement", "CM-ELEVATE", True),
)

NAMES: tuple[str, ...] = tuple(s.name for s in SCHEMES)
BY_NAME: dict[str, Scheme] = {s.name: s for s in SCHEMES}
SUBJECT_TO_SCHEME: dict[str, str] = {s.subject_area: s.name for s in SCHEMES}
