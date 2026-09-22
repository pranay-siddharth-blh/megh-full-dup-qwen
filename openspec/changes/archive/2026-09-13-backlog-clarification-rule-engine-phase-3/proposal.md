## Status
**Implemented, 2026-09-13** — approved and built the same session
("any features pending 5.1, 5.2 and 5.3 complete it here"). 20 of the 25
nominal conditions below actually got wired, not 25 — five more exclusions
were found during authoring (two PMAY-G, two Focus Plus, one CM Elevate),
each for a distinct, recorded reason. See `tasks.md` task 2.2 for the full
trail and `app/clarification_engine.py`'s Phase 3 section comment for the
per-condition detail. The original scope statement below is left intact
per this repo's convention of not rewriting history.

Sequenced after `backlog-clarification-rule-engine-migration` (Phase 1, 66
matchers, "the source cannot answer this at all") and
`backlog-clarification-rule-engine-phase-2` (Phase 2, 27 matchers, "which
measure"/ambiguous vocabulary), both implemented and passing tests but
**not yet committed** — see their own `tasks.md` 4.3 entries.

## Re-verification (done before writing this proposal, not assumed)

Re-ran both phases' test suites directly rather than trusting their
`tasks.md` claims: `python tests/test_clarification_engine.py` and
`python tests/test_clarification_gate.py` both exit 0 — `ALL
CLARIFICATION-ENGINE CHECKS PASSED`, `ALL CLARIFICATION GATE (5.3) CHECKS
PASSED`. `app/clarification_engine.py` and its two test files are
confirmed untracked in git (`git status --short`), consistent with "not
committed" above.

Counted unwired conditions **programmatically**, not from section-header
line counts (which double-count where a scheme nests dash-headers under a
numbered top-level header, e.g. CM Elevate) — loaded every scheme's
`_load_scheme_rules()` output and diffed against `ce._MATCHERS.keys()` and
`ce._COLLISION_CONDITIONS`:

| Scheme | Total conditions | Wired (Phase 1+2) | Collision-covered | Unwired |
|---|---|---|---|---|
| MGNREGA | 48 | 18 | 1 | 29 |
| PMAY-G | 90 | 36 | 2 | 52 |
| Focus Plus | 88 | 29 | 1 | 58 |
| CM Elevate | 115 | 37 | 1 | 77 |
| **Total** | **341** | **120** | **5** | **216** |

## Finding: a real collision-set gap, found during this re-verification

`app/pipeline.py` has a hardcoded `_women_share_clarification` predicate
(gated by `_WOMEN_SHARE_REQUESTED`) that already covers MGNREGA's
`women_share_requested` condition end-to-end — confirmed by
`tests/test_clarification_gate.py` section 5 and
`tests/test_clarification_engine.py` section 5, both of which assert this
predicate fires with its own text. But `women_share_requested` is **not**
in `ce._COLLISION_CONDITIONS` (that set has exactly 4 entries, all
documented in the module's own docstring — `women_share_requested` is not
one of them). This has caused no visible bug yet only because no matcher
for that condition name exists in `_MATCHERS` either — `check_clarifications`
degrades to "no match" for any name absent from `_MATCHERS`, collision set
or not. It becomes load-bearing the moment anyone wires a matcher for
`women_share_requested` under the assumption the collision set is complete.
This proposal's scope (below) authors a matcher for MGNREGA's "measures
that exist but must not be reported as asked" section, which contains
`women_share_requested` — task group 1 fixes the collision-set gap as part
of that work, not as a separate change.

## Finding: the "time" category is not simply 190 unwired conditions waiting for matchers

Before scoping "time" in or out, read `app/pipeline.py`'s existing
hardcoded gates directly (not assumed from name similarity):
`_needs_year_clarification` / `_year_clarification` (a generic "which
financial year?" gate, explicitly re-enabled for PMAY-G by product decision
2026-09-09) and `_needs_tranche_clarification` / `_tranche_clarification`
(Focus Plus-only "which tranche?" gate). Both already ask the same
question several "time" section conditions in the YAML files describe in
different words (MGNREGA's `missing_time_period`, PMAY-G's own copy, and
Focus Plus's tranche-shaped equivalents). Neither hardcoded gate is
cross-checked against the YAML condition names the way
`_admin_expenditure_clarification` / `_bank_clarification` were in Phase
1's task 2.2 — that cross-check has not been done for "time" and is real,
non-trivial work (each of the ~7-8 time conditions per scheme needs to be
read against both hardcoded gates' actual trigger logic, not just their
docstrings). **"Time" is therefore explicitly out of scope for this
proposal** — same treatment Phase 2 gave "geography" for an analogous
reason (see that change's `design.md`, "Why this category, not geography").

For the same reason, Focus Plus's "the batch duality" section (5
conditions: `batch_scope_unclear`, `person_attribute_requested_scheme_wide`,
`paid_unpaid_definition_requested`, `unpaid_backlog_requested`,
`tranche_comparison_crosses_batches`) sits close enough to
`_needs_tranche_clarification`'s existing tranche-ambiguity logic
(`tranche_comparison_crosses_batches` literally describes "Tranch 4
contains both batches") that it needs the same dedicated cross-check before
it can be scoped safely. Excluded from this proposal for that reason, not
because the conditions themselves are hard to author.

## What this proposal actually recommends

Wire the **"measures/fields that exist but must not be reported as asked"**
category (same risk shape, and the same architecture, as Phase 1's
already-shipped `_admin_expenditure_clarification` /
`_women_share_clarification` precedent: a term or column that exists in
the schema but means something different from what a plain reading of the
question assumes, producing a silent wrong answer rather than an error) —
confirmed condition-by-condition to be text-decidable from the question
alone, with no dependency on entity-resolution state, placeholder
interpolation the registry can't fill, or overlap with the year/tranche
gates found above:

| Scheme | Section (YAML's own header) | Conditions in scope |
|---|---|---|
| MGNREGA | "measures that exist but must not be reported as asked" | `women_metric_in_2025_26`, `benefit_to_households_requested`, `job_cards_across_multiple_years` (3; `women_share_requested` and `administrative_expenditure_requested` in this same section are collision-covered, not re-wired) |
| PMAY-G | "measures that exist but must not be reported as asked" | `sanctioned_amount_variation_requested`, `installment_or_release_as_completion_proof`, `house_status_as_occupancy`, `completion_rate_across_mixed_years`, `mapping_status_as_performance`, `fuzzy_village_precision_warning`, `individual_person_tracking_requested`, `parent_name_filter_requested`, `singleton_category_focus` (9) |
| Focus Plus | "money" (the batch-duality section is excluded — see Finding above) | `money_unit_unconfirmed`, `standard_payment_reading_unclear`, `average_payment_requested`, `money_across_schemes_unit_mismatch` (4) |
| CM Elevate | "4. FIELDS THAT EXIST BUT MUST NOT BE READ AS ASKED" | `application_read_as_award`, `beneficiary_term_used`, `forward_status_read_as_approved`, `current_level_read_as_progress`, `data_verified_read_as_funding_decision`, `application_count_offered_as_money_proxy`, `type_raw_grouping_across_schemes`, `current_level_case_variants`, `sendback_wording_variants` (9; `gender_breakdown_requested` in this same section carries its own YAML note "NOT A REFUSAL — this is answerable" and is deliberately excluded, same treatment as Phase 1's `villages_without_houses_requested`) |
| **Total** | | **25 nominal conditions** |

## What this proposal does NOT claim

- Not wiring "time" (any scheme) or Focus Plus's "batch duality" section —
  both need a dedicated cross-check against `_needs_year_clarification` /
  `_needs_tranche_clarification` first (see Finding above); that
  cross-check is a distinct, sizeable piece of work, not a rounding error,
  and belongs in its own future proposal.
- Not wiring "geography", "identifiers and values", "shape of the answer",
  "data quality", CM Elevate's "WHICH SCHEME" or "THE REQUIREMENT WORKBOOK
  DESCRIBES A DIFFERENT DATASET" sections, or the remainder of CM
  Elevate's own "THE SOURCE CANNOT ANSWER THIS AT ALL" subsections
  (identity/personal fields, attributes not collected, scope of the data,
  cross-scheme — left out of Phase 1's narrower original cut). All remain
  unanalyzed; each needs its own re-verification pass before it can be
  scoped, same standard as this document and Phase 2's applied to their
  own categories.
- Not migrating the ~7 pre-existing hardcoded predicates.
- Not changing the matcher registry mechanism, the `(question, resolved)
  -> bool` callable signature, or `_format_question`'s placeholder
  handling.

## Capabilities

### Modified Capabilities
- `clarification-rule-matcher`: additive matcher coverage for the 25
  conditions above, plus the `women_share_requested` collision-set
  correction. No change to the capability's existing behavior for already-
  wired conditions.

## Impact

- Modified: `app/clarification_engine.py` (new matcher functions and
  `_MATCHERS` entries, plus adding `women_share_requested` to
  `_COLLISION_CONDITIONS`), `tests/test_clarification_engine.py` (new
  positive/negative cases).
- No changes expected to `app/db.py`, `app/auth.py`, `app/deps.py`,
  `app/appdb.py`, `app/config.py`, or the `check_clarifications` /
  `_load_scheme_rules` mechanism itself.
