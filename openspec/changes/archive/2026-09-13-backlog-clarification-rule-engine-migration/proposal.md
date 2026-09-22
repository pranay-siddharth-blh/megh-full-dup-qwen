# Clarification Rule-Engine Coverage (backlog)

## Status
Proposal — awaiting review and approval before any implementation starts.
Re-scoped 2026-09-11 after re-verifying this item's original framing against
the current codebase; the original scope statement is stale in two ways
(see Corrections below). Not sequenced as a numbered phase.

## Corrections to the original scope statement

This item originally bundled two concerns under one backlog entry. Re-
verification found:

1. **Node 5.5 ("generic defaults") is no longer in scope here — it shipped.**
   `app/defaults_engine.py` (Phase 4) implements it in full: a YAML-driven
   matcher registry over `*_default_rules.yaml`, wired into the pipeline,
   with an explicit collision set so it never overlaps a hardcoded
   clarification predicate. The "ask vs. default" product decision this
   item flagged as unresolved was made on 2026-09-11: all 12 candidate
   conditions stay "ask" (zero flips), recorded in
   `phase-4-clarification-defaults-charts/tasks.md` task 1.6. Nothing
   further to do here on defaults.

2. **The real 5.3 gap is coverage, not architecture.** The original framing
   — "keep ~7 hardcoded predicates, or migrate them to YAML" — undersells
   the problem. The ~7 hardcoded predicates are not a smaller version of
   the same thing the YAML describes; they are a small subset of it.
   Counted directly against the YAML files:

   | Scheme | `*_classification_rules.yaml` conditions | Wired into `app/pipeline.py` |
   |---|---|---|
   | MGNREGA | 48 | 2 (`administrative_expenditure_requested`, `women_share_requested`) — plus the 5 generic cross-scheme predicates (scheme/top-N/scope/year/tranche) |
   | PMAY-G | 90 | 0 scheme-specific |
   | Focus Plus | 88 | 0 scheme-specific |
   | CM Elevate | 115 | 0 scheme-specific |
   | **Total** | **341** | **~7** |

   This is a ~2% wiring rate, not a "hardcoded vs. YAML-driven" style
   preference between two roughly-equivalent implementations.

## Why (re-grounded, with severity)

The highest-risk slice of the unwired 341 is a specific category present
in every scheme's YAML under headers like *"the source cannot answer this
at all"* (MGNREGA, PMAY-G), *"what privacy forbids"* (Focus Plus), or
*"money/time/outcome fields that do not exist"* (CM Elevate) — questions
asking for a fact the underlying data genuinely does not hold (pending
dues, fund availability, a wage rate, per-capita figures, budget-vs-actual,
individual-level records, and scheme-specific equivalents). Counted
directly:

| Scheme | "Cannot answer at all" conditions | Wired |
|---|---|---|
| MGNREGA | 9 | 0 |
| PMAY-G | 28 | 2 |
| Focus Plus | 18 | 1 |
| CM Elevate | 20 | 1 |
| **Total** | **75** | **4** |

**Correction (found during tasks.md 2.2, 2026-09-12):** "wired" above
means covered end-to-end by an existing scheme-agnostic hardcoded
predicate, not the two conditions this proposal already named
(`administrative_expenditure_requested`, `women_share_requested`) — those
two are filed under a different YAML section ("measures that exist but
must not be reported as asked"), not this "cannot answer at all" one.
Within this class specifically: PMAY-G's own copy of
`administrative_expenditure_requested` (same condition name, different
section) and `dbt_or_bank_status_requested`; Focus Plus's
`account_number_or_ifsc_requested`; and CM Elevate's `loan_entity_
requested` are already caught by `_admin_expenditure_clarification` /
`_bank_clarification`. Net effect: 4 conditions already covered, 71 — not
75 — genuinely unwired (MGNREGA 9, PMAY-G 26, Focus Plus 17, CM Elevate
19). See `app/clarification_engine.py`'s module docstring and this
file's tasks.md task 2.2 for the full per-condition verification trail.

This is not a hypothetical risk. `app/pipeline.py`'s own comment on
`_admin_expenditure_clarification` (`pipeline.py:891-900`) states exactly
what happens without a guard: *"the question reached SQL generation, which
has no such column to read and either errors or returns a wrong/empty
figure instead of explaining the exclusion."* That predicate and
`_women_share_clarification` are the two conditions from this same "cannot
answer" risk class that got manually ported into `pipeline.py` after
someone hit the gap in practice. The other 73 conditions in this category
— across all four schemes — have the identical failure mode and no guard
at all today. Confirmed there is no other safety net: `app/premise_check.py`
only checks numeric premises against rows a query already returned, so a
query for data that doesn't exist never reaches it.

## What this proposal does NOT claim

Wiring in all 341 conditions in one pass is not being proposed — each
condition's regex/keyword trigger needs to be checked against how users
actually phrase the question (the same SME-verification dependency the GT
proposal itself names in Section 12 for "clarification and default rule
design"), and 341 is too much to verify in one pass without risking
false-fire regressions on working queries. See `design.md` for the phased
recommendation this proposal is actually asking approval for.

## Capabilities

### New Capabilities
- `clarification-rule-matcher`: a generic condition-name → matcher-function
  registry loaded from `*_classification_rules.yaml`, mirroring
  `app/defaults_engine.py`'s existing pattern for `*_default_rules.yaml` —
  see `design.md` for why this precedent is reused rather than a new
  design.

### Modified Capabilities
(none yet — this proposal does not modify the existing ~7 hardcoded
predicates; see design.md's migration-risk discussion for why)

## Explicitly Out of Scope (this proposal)

- The remaining ~266 conditions outside the "cannot answer at all" class
  (time, which-measure, geography, identifiers, shape-of-answer,
  data-quality categories) — flagged as a later phase once the matcher
  infrastructure and the first 75 conditions are proven in production.
- Migrating or touching the existing ~7 hardcoded predicates — they work,
  are tested, and migrating them is a pure-risk / low-reward move with no
  coverage gain (see design.md).
- Any change to `app/defaults_engine.py` or the 1.6 decision.

## Impact

- New file: `app/clarification_engine.py` (mirrors `app/defaults_engine.py`
  structure).
- Modified: `app/pipeline.py` (one new call site in the same place
  `defaults_engine.apply_defaults` / `premise_check.check_premises` are
  called from), `app/config.py` (one new enabled flag, matching
  `DEFAULTS_ENGINE_ENABLED`/`FINDINGS_ENABLED` naming).
- No changes expected to `app/db.py`, `app/auth.py`, `app/deps.py`,
  `app/appdb.py`.
