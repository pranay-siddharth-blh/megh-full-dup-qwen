## The decision this document makes

**Recommendation: scope Phase 3 to the "measures/fields that exist but
must not be reported as asked" category — the same risk shape as the
already-shipped `_admin_expenditure_clarification` /
`_women_share_clarification` hardcoded predicates (a column exists, but
answering literally what it says produces a silently wrong figure, not an
error) — 25 nominal conditions across all four schemes, plus a
collision-set correction for `women_share_requested` found while scoping
this phase (see proposal.md).**

## Why this category, not "time" or Focus Plus's "batch duality"

Read `_needs_year_clarification`, `_year_clarification`,
`_needs_tranche_clarification`, and `_tranche_clarification` in
`app/pipeline.py` directly before deciding, the same way Phase 2's
design.md read `resolve_entities` before ruling geography in or out.
Finding: both are generic, already-shipped "which financial year /
tranche?" gates — `_needs_year_clarification` was explicitly re-enabled
for PMAY-G by a 2026-09-09 product decision (its own comment says so), and
`_needs_tranche_clarification` is Focus Plus-only. Several "time" section
conditions in the YAML files (MGNREGA's and PMAY-G's own `missing_time_
period`, `year_outside_available_range`, `vague_recency`, and others) look,
from their authored question text alone, like they ask the same thing
these two hardcoded gates already ask in different words. Whether each one
is a true duplicate, a genuine gap the hardcoded gates miss, or a
narrower/broader variant that needs different wording is real,
condition-by-condition work this document does not do — cross-checking
`_needs_year_clarification`'s exact trigger predicates (`_ALL_YEARS_CUE`,
`_TIME_SERIES_CUE`, `_METRIC_OR_BREAKDOWN_CUE`, the `resolved.get(
"year_key")` check) against each "time" condition's actual phrasing, one
by one, the way Phase 1's task 2.2 did for the four money/bank
collisions.

Focus Plus's "the batch duality" section is excluded for the same reason:
`tranche_comparison_crosses_batches` ("Tranch 4 contains both batches")
sits close enough to `_needs_tranche_clarification`'s own tranche-ambiguity
logic that it needs the same dedicated read before it can be scoped
safely, not because authoring its matcher text would itself be hard.

Wiring either category now, without that cross-check, risks the same kind
of gap this phase found for `women_share_requested` — a condition that
looks unwired in `_MATCHERS` but is actually already handled elsewhere,
except discovered only after a matcher was written and shipped rather than
before. "Measures/fields that exist but must not be reported as asked" has
no such adjacent hardcoded gate to reconcile with — its collision surface
is exactly the 2 known entries (`administrative_expenditure_requested`,
already in `_COLLISION_CONDITIONS`; `women_share_requested`, the gap this
phase fixes) — confirmed by reading every hardcoded predicate list in
`app/pipeline.py` (`_scheme_clarification`, `_scheme_comparison_
clarification`, `_unsupported_scheme_clarification`, `_bank_clarification`,
`_admin_expenditure_clarification`, `_women_share_clarification`,
`_needs_topn_clarification`, `_needs_scope_clarification`, `_region_
clarification`, `_needs_year_clarification`, `_needs_tranche_
clarification`) and confirming none of the other 9 target this category's
subject matter (workflow-stage labels, flat-entitlement columns, applicant
vs. beneficiary terminology, money-unit confirmation).

## Finding: `women_share_requested` is a real, previously-undocumented collision gap

`_women_share_clarification` / `_WOMEN_SHARE_REQUESTED` in
`app/pipeline.py` already handles MGNREGA's `women_share_requested`
condition — verified by both existing test files firing it and asserting
its own exact question text. `ce._COLLISION_CONDITIONS`, however, lists
only 4 names, and `women_share_requested` is not one of them (confirmed by
reading the module's own docstring, which enumerates all 4 by name with
their justification, and by direct membership check against the live
set). This has been a latent gap since Phase 1 — harmless only because no
matcher for that name has existed in `_MATCHERS` until this phase touches
the same YAML section. Fixing it here (adding the name to
`_COLLISION_CONDITIONS`, not writing a matcher for it) is in scope; it is
not a new capability, just closing a gap this phase's own re-verification
surfaced.

## Goals / Non-Goals

**Goals:**
- Wire matchers for the 25 nominal conditions listed in proposal.md across
  all four schemes' "measures/fields that exist but must not be reported
  as asked" sections (or scheme-equivalent header).
- Correct the `women_share_requested` collision-set gap as part of this
  work.
- Reuse the existing `_MATCHERS` / `_load_scheme_rules` /
  `check_clarifications` mechanism exactly as Phases 1-2 left it — no
  registry changes.

**Non-Goals:**
- Not wiring "time" (any scheme) or Focus Plus's "batch duality" — both
  need a dedicated cross-check against the existing year/tranche hardcoded
  gates first (see Why above); a future phase, not this one.
- Not wiring "geography", "identifiers and values", "shape of the
  answer", "data quality", CM Elevate's "WHICH SCHEME" or "THE
  REQUIREMENT WORKBOOK DESCRIBES A DIFFERENT DATASET" sections, or the
  remaining CM Elevate "cannot answer" subsections (identity/personal
  fields, attributes not collected, scope of the data, cross-scheme) —
  each needs its own re-verification pass, not attempted here.
- Not wiring CM Elevate's `gender_breakdown_requested` — its own YAML note
  states it is answerable, not a refusal; same treatment as Phase 1's
  `villages_without_houses_requested`.
- Not extending `resolved`'s shape, `_format_question`, or the matcher
  callable signature.

## Decisions

**Every condition in this phase's scope is scheme-unique** (none of the 25
condition names are shared verbatim across more than one scheme's YAML,
unlike Phases 1-2) — confirmed by checking each name against every other
scheme's `_load_scheme_rules()` output. This means no scheme-agnostic
heuristic or shared-name side effect applies here; each matcher can safely
use that scheme's own specific vocabulary (column names, workflow-stage
labels, tranche amounts) without risking a false-fire on another scheme's
question, the same reasoning Phase 2 used for its scheme-unique
conditions.

**Ordering**: every condition in scope sits in a section that, in its
YAML's own file order, comes after "the source cannot answer this at all"
and before "which measure" / "time" / "geography" for its scheme
(confirmed by direct line-number inspection of all four files) — so
`check_clarifications`'s existing first-match-wins-in-file-order behavior
requires no new reasoning here; these conditions simply take their place
in each scheme's already-correct ordering.

## Risks / Trade-offs

- **[A "measures/fields that exist" matcher fires on a legitimately
  answerable question that happens to share vocabulary]** → Same
  mitigation standard as Phases 1-2: every matcher gets at least one
  negative case in `tests/test_clarification_engine.py` proving the
  scheme's own valid reading of the same column/term does not false-fire,
  found and fixed during authoring/testing if needed, not assumed correct
  on first write.
- **[The excluded "time" / "batch duality" categories remain unwired
  indefinitely if the cross-check is never scheduled]** → No regression
  from today (they don't fire now either); flagged explicitly as
  deliberately deferred work, not silently dropped, same as Phase 2's
  treatment of geography.
- **[Same AUTHORED-PENDING-SME-REVIEW status as Phases 1-2]** → These
  matchers are self-tested, not SME-reviewed for phrasing accuracy before
  this phase's own PR review. Not shippable to production ahead of that
  review.

## Migration Plan

1. Add `women_share_requested` to `ce._COLLISION_CONDITIONS` (one-line
   fix, no matcher written for it).
2. Add ~25 matcher functions and their `_MATCHERS` entries to the existing
   `app/clarification_engine.py` — purely additive, same file, same
   pattern as Phases 1-2.
3. Extend `tests/test_clarification_engine.py` with positive/negative
   cases for the new conditions, plus an explicit assertion that
   `women_share_requested` is now in `_COLLISION_CONDITIONS` and that
   `_women_share_clarification`'s own text still wins (mirrors Phase 1's
   existing collision-zero-regression section).
4. Full regression sweep of all `tests/test_*.py` files, same standard as
   Phases 1-2's task group 4.
5. Rollback: deleting the new `_MATCHERS` entries (and reverting the
   `_COLLISION_CONDITIONS` addition) is safe at any point —
   `check_clarifications` degrades to skipping any condition with no
   entry, exactly as it does today for the untouched ~191 remaining
   conditions.

## Open Questions

1. Approve scoping Phase 3 to the "measures/fields that exist but must not
   be reported as asked" category as described, deferring "time", Focus
   Plus's "batch duality", and every other remaining category to their own
   future proposals?
2. Approve the `women_share_requested` collision-set correction as part of
   this phase rather than a separate change?
3. Who should do the "time" vs. `_needs_year_clarification` / `_needs_
   tranche_clarification` cross-check this document declines to do, and
   when — a dedicated Phase 4 proposal, or folded into whichever phase
   picks up "time" next?
