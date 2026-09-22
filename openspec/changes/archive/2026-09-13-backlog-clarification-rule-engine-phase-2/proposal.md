# Clarification Rule-Engine Coverage — Phase 2 (backlog)

## Status
Proposal — awaiting review and approval before any implementation starts,
same gate `backlog-clarification-rule-engine-migration` (Phase 1) went
through. Not sequenced as a numbered Grant Thornton phase.

**Sequencing tension, flagged rather than skipped past:** Phase 1's own
`design.md` scoped "the remaining ~266 conditions" as belonging to "a
later phase **once the matcher infrastructure and the first [71]
conditions are proven in production**." As of this proposal, Phase 1's
work (`app/clarification_engine.py`, 66 matcher functions,
`tests/test_clarification_engine.py`) is implemented and tested but
**not committed, not deployed, and not yet reviewed by the SME pool**
task 1.2 named as the phrasing-accuracy reviewer. "Proven in production"
has not happened. This proposal exists because it was explicitly
requested, but the approver should treat "is it too early to plan Phase
2" as a real, open question — see Open Questions — not a formality.

## Re-verification (done before drafting this proposal)

Re-counted directly against the live `app/clarification_engine.py` and
the four `*_classification_rules.yaml` files rather than assuming Phase
1's "~266 remaining" figure was still accurate after Phase 1 shipped:

| Scheme | Total conditions in file | Covered by Phase 1 (wired matcher or collision) | Still uncovered |
|---|---|---|---|
| MGNREGA | 48 | 10 | 38 |
| PMAY-G | 90 | 27 | 63 |
| Focus Plus | 88 | 19 | 69 |
| CM Elevate | 115 | 29 | 86 |
| **Total** | **341** | **85** | **256** |

**"Covered by Phase 1" (85) is higher than Phase 1's own nominal 71/70**
because `app/clarification_engine.py`'s `_MATCHERS` dict is keyed by
condition name only, not `(scheme, name)` — a name several schemes'
YAMLs share (e.g. `per_capita_requested`, `other_scheme_requested`,
`age_or_disability_requested`) is covered everywhere it appears once
wired, including scheme/condition instances outside Phase 1's nominal
per-scheme counts. This is documented in `clarification_engine.py`'s own
module docstring and Phase 1's `tasks.md` task 3.1 — re-confirmed here,
not re-derived from scratch.

**256 is a corrected number, not Phase 1's "~266" carried forward
unchecked** — the difference is exactly the 10 extra shared-name
instances Phase 1 covered as a side effect (271 nominal-remaining minus
266-stated wouldn't reconcile either; the honest statement is: this
count was re-run against the current codebase state, not copied from an
older document).

## What is NOT yet accounted for by this table

`app/pipeline.py`'s five scheme-agnostic hardcoded predicates
(`_needs_scheme_clarification`, `_needs_topn_clarification`,
`_needs_scope_clarification`, `_needs_year_clarification`,
`_needs_tranche_clarification`) may already functionally cover some
fraction of the 256 "uncovered" conditions above under a *different*
name than the YAML uses for the same real-world question (e.g. a
`missing_time_period`-shaped YAML condition and `_needs_year_
clarification`'s own regex may already both refuse the same phrasing,
just never cross-referenced). Phase 1's `_COLLISION_CONDITIONS` set only
excludes the 4 conditions already known to collide with
`_admin_expenditure_clarification`/`_bank_clarification` — nothing in
this codebase currently cross-checks the 256 against the OTHER five
hardcoded predicates' regexes. **This proposal does not claim the true
gap is 256** — it claims 256 are not handled by `clarification_engine.py`
specifically, and flags the possible additional overlap as the first
thing any implementation of this phase must re-verify (mirroring how
Phase 1's own task 2.2 found and corrected a 75-vs-71 miscount during
implementation, not before it).

## Category breakdown (re-verified directly, per scheme)

Counted by the YAML files' own section headers — a proxy for "what kind
of question this is," not a proposal-authored taxonomy:

**MGNREGA** (38 remaining): measures that exist but must not be reported
as asked (5), time (7), which measure (9), geography (10), shape of the
answer (8) — 5+7+9+10+8 = 39; one condition's header attribution needs a
by-hand check during implementation (off-by-one against the 38 total,
noted rather than silently rounded).

**PMAY-G** (63 remaining): data quality/v2.0 (5), measures that exist but
must not be reported as asked (9), time (8), which measure (11),
geography (10), identifiers and values (7), shape of the answer (12) —
sums to 62; same one-off note as MGNREGA applies.

**Focus Plus** (69 remaining): what privacy forbids (5), the batch
duality (5), terms that look answerable but mean several things (10),
money (4), time (6), geography (16), status (5), cross-scheme (4), data
quality (2), shape of the answer (13) — sums to 70; same one-off note.

**CM Elevate** (86 remaining): identity and personal fields (4),
attributes not collected (7), scope of the data (8), cross-scheme (3) —
22 of the 86 cleanly categorized this pass. The remaining ~64 sit in CM
Elevate's own "Section 2: THE REQUIREMENT WORKBOOK DESCRIBES A DIFFERENT
DATASET" (`cmelevate_classification_rules.yaml`), whose internal
structure was **not** broken down by sub-header in this proposal —
CM Elevate's file header comment already documents this section exists
because "40 of the 89 use cases in the requirement workbook cannot be
answered" against a differently-shaped legacy dataset assumption, which
suggests these conditions may cluster into a smaller number of *root
causes* (wrong scheme count, wrong column assumptions) rather than 64
independent phrasing problems — worth a dedicated look before wiring
starts, not an argument for skipping this scheme's remaining work.

The small per-scheme reconciliation gaps (39 vs. 38, 62 vs. 63, 70 vs.
69) are recorded here deliberately rather than silently rounded — a
condition sitting exactly on a section-header boundary line was
miscounted by one in at least one scheme, and re-establishing the exact
per-condition list (not just the header-level count) is Phase 2
implementation work, not something to resolve by guessing in a proposal.

## Why (re-grounded from Phase 1's own reasoning)

Phase 1 wired the single highest-severity class — questions the data
genuinely cannot answer at all, where the failure mode is "confidently
wrong or empty answer." The 256 remaining conditions are lower-severity
by Phase 1's own design.md framing (`missing_geography`/`missing_
top_n`-shaped gaps are "acceptable answer, just less refined," not
"wrong answer") but are not zero-risk: every one of them is currently a
silent gap with no clarification and no default, so a legitimately
unanswerable or ambiguous "which measure"/"shape of the answer"/
"geography" question falls straight through to SQL generation exactly
as Phase 1's own `_admin_expenditure_clarification` precedent showed
happens for the "cannot answer" class before it was wired.

## What this proposal does NOT claim

- That 256 (or any other single number derived in this document) is the
  final, exact count — see "What is NOT yet accounted for" above.
- That all 256 should be wired in one pass — same SME-verification
  argument Phase 1 made applies at this scale too, arguably more so
  given CM Elevate's ~64 not-yet-categorized "Section 2" conditions.
- That Phase 2 should start before Phase 1 is committed, reviewed by the
  SME pool, and ideally observed in production — see Status above.

## Capabilities

### Modified Capabilities
- `clarification-rule-matcher`: extends the existing capability
  (`backlog-clarification-rule-engine-migration`'s
  `specs/clarification-rule-matcher/spec.md`) to cover additional
  condition categories beyond Phase 1's "cannot answer at all" class —
  exact category scope to be fixed in this change's own `design.md`,
  matching Phase 1's precedent of a human-approved, explicitly-scoped
  slice rather than "the rest of everything."

### New Capabilities
(none — this is additive coverage under the existing capability, not a
new mechanism)

## Explicitly Out of Scope (this proposal)

- Migrating the existing ~7 hardcoded predicates onto
  `clarification_engine.py` — a separate, previously-deferred item with
  its own low-value/high-risk assessment in Phase 1's `design.md`.
- Cross-checking the 256 (or corrected number) against the five generic
  hardcoded predicates' own regexes to find true double-coverage — named
  above as necessary re-verification work, but not performed in this
  proposal; it belongs to this change's `design.md` or early `tasks.md`
  re-verification group, mirroring Phase 1's own task-group-0 pattern.
- Committing, deploying, or SME-reviewing Phase 1's work — tracked in
  Phase 1's own `tasks.md`, not this change.

## Impact (anticipated, subject to design.md)

- Modified: `app/clarification_engine.py` (more matcher functions added
  to the existing `_MATCHERS` registry — same file, same pattern, no new
  module).
- Modified: `tests/test_clarification_engine.py` (more positive/negative
  cases).
- No changes expected to `app/db.py`, `app/auth.py`, `app/deps.py`,
  `app/appdb.py`, or the registry mechanism itself (`check_clarifications`,
  `_load_scheme_rules`) — this is additive matcher authoring against
  already-approved infrastructure, not an architecture change.

## Open Questions

1. Should this proposal proceed to `design.md`/`tasks.md` now, or wait
   until Phase 1 is committed, SME-reviewed, and observed in production —
   the gating condition Phase 1's own `design.md` stated for "a later
   phase"? (See Status.)
2. Which category should be scoped first, given Phase 1's own precedent
   of picking the highest-severity, most tractable slice rather than
   everything at once? Candidates, roughly ordered by how cleanly they
   parsed in this proposal's category breakdown: "which measure" (9/11
   conditions, MGNREGA/PMAY-G — likely similar shape to Phase 1's
   already-proven pattern) vs. "geography" (10/10/16 conditions across
   three schemes — larger, more schemes involved) vs. CM Elevate's own
   ~64-condition "Section 2" (needs a dedicated categorization pass
   before it can even be scoped).
3. Should the cross-check against the five generic hardcoded predicates
   (naming which of the 256 are already functionally covered under a
   different name) happen as part of THIS proposal's `design.md`, before
   any category is picked — since it could materially shrink the real
   number needing new matchers — or as an early `tasks.md` re-verification
   group, same as Phase 1 corrected its own count mid-implementation?
