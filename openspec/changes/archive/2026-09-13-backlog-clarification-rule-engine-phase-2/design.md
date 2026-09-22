## The decision this document makes

**Recommendation: scope Phase 2 to the "which measure" / ambiguous-
vocabulary category, present in all four schemes' YAMLs under headers
`which measure` (MGNREGA, PMAY-G), `terms that look answerable but mean
several things` (Focus Plus), and a literal `6. WHICH MEASURE` (CM
Elevate) — 40 nominal conditions, 31 unique matcher functions after
shared-name savings, minus four deliberate exclusions found during
design (`vague_qualifier` across all 4 schemes, plus
`ambiguous_expenditure_component`/`sanctioned_reading_unclear`/
`amount_reading_unclear` — see below), for an effective 33 nominal / 27
unique.**

Proceeding now per the user's explicit instruction ("build it please",
2026-09-13) rather than waiting for the sequencing condition
`proposal.md`'s Status section named (Phase 1 committed/SME-reviewed/
observed in production) — flagged there, not re-litigated here, and not
silently dropped: the approver should know this was a judgment call to
proceed, not a resolved question.

## Why this category, not geography or CM Elevate's "Section 2"

Re-read the actual condition list (not just section-header counts) in
every "geography" section before ruling it out: `ambiguous_village_
needs_district`, `ambiguous_geography_level`, `unmatched_geography_
name`, `district_split_boundary`, and most of that category's ~50
conditions need **entity-resolution state** (which district(s) a named
village actually matched, whether a term is simultaneously a valid
block/constituency/village name) that is not decidable from question
text alone — `resolve_entities`'s current return shape was not verified
to expose the specific ambiguous-match data these conditions need, and
wiring them properly would mean extending what `entity_result["resolved"]`
carries, which is a bigger change than "add matcher functions" (this
proposal's stated Impact). CM Elevate's own uncharacterized "Section 2"
(~64 conditions, workbook-mismatch class) needs its own dedicated
categorization pass before it can be scoped at all (`proposal.md`
already flagged this).

"Which measure" is the one remaining category confirmed, condition by
condition, to be decidable from question text alone (ranking/trend
language without a named metric, a generic term used without its
qualifying variant, an ambiguous count subject) — the same shape Phase 1
already proved works with this registry.

## Finding: `vague_qualifier` cannot be correctly wired without a registry change

Every scheme's `vague_qualifier` question text embeds a `{value}`
placeholder: *"What should '{value}' be measured by..."* — meant to
echo back the specific ambiguous term the user typed. `_format_question`
(`app/clarification_engine.py`) only fills placeholders from the
`resolved` dict already passed in; a matcher's signature is
`(question, resolved) -> bool` — it cannot contribute the specific
matched substring back for interpolation. Shipping this condition today
would either show a literal, broken `'{value}'` to the user (the
existing `_SafePlaceholder` fallback) or require detecting a fixed
"vague term" independent of what the user actually typed, which is not
what the YAML's own text promises. Extending the matcher contract to
return more than a bool (or writing back into `resolved`) is a registry
change — explicitly out of scope per this change's own `proposal.md`
Impact section ("No changes... to the registry mechanism itself").

**Decision: skip `vague_qualifier` in this phase, across all four
schemes, same treatment as Phase 1's `villages_without_houses_
requested`.** No entry in `_MATCHERS` for it; recorded here and in
`tasks.md`, not silently dropped. Revisiting it is a separate, small
follow-up proposal (extend the matcher contract) if a future phase wants
it — not a reason to block the other matchers in this phase.

## Finding: three more conditions each key on that scheme's single flagship default term

Found while drafting the actual matcher regexes (not before) —
`ambiguous_expenditure_component` (MGNREGA), `sanctioned_reading_
unclear` (PMAY-G), and `amount_reading_unclear` (Focus Plus) each ask
the user to disambiguate a term — "expenditure", "sanctioned", "amount"
— that this codebase already treats as each scheme's single most common,
implicitly-defaulted query shape. Direct evidence, not a guess:
Phase 1's own `app/clarification_engine.py` comment on
`_TARGET_ALLOCATION_BUDGET` states outright *"bare 'sanctioned' is NOT
matched — 'houses sanctioned' is a legitimate, answerable PMAY-G
metric"* — i.e. this session already made and recorded the opposite
judgment call for the same word once before. "Total MGNREGA expenditure"
and "total Focus Plus amount disbursed" are the equivalent flagship
defaults for their schemes (the former is literally this test suite's
own canonical example of a legitimately-answerable negative case in
`tests/test_clarification_engine.py`).

Wiring these three as authored — fire on any bare mention of the term —
would mean every ordinary "what was the MGNREGA expenditure in West
Garo Hills" question newly demands a clarification it never asked for
before, breaking the single most common query shape in three of the
four schemes. This is a materially different, more severe risk than the
"under-fires on a rarer ambiguous phrasing" trade-off the Risks section
below accepts for the four shared names — it is an over-fire on the
*most common* phrasing, not a rare one.

**Decision: skip all three, same treatment as `vague_qualifier`.**
Unlike `vague_qualifier`, these are not a registry limitation — a
correct version is plausible in principle (fire only when the term
appears WITHOUT the scheme's implicit default reading, e.g. "expenditure
breakdown by category" vs. bare "expenditure") but authoring that
correctly needs the same kind of product/SME judgment call Phase 1's
task 1.1-1.3 required human sign-off for, not a session's own regex
guess about which phrasings the default reading should still cover.
Flagged as an Open Question below for the approver, not resolved here.

## Goals / Non-Goals

**Goals:**
- Wire matchers for the 27 unique, text-decidable, non-flagship-term
  conditions in the "which measure" category across all four schemes
  (33 nominal instances after the four exclusions above).
- Reuse the existing `_MATCHERS` registry exactly as Phase 1 left it —
  no changes to `check_clarifications`, `_load_scheme_rules`, or
  `_COLLISION_CONDITIONS`'s existing four entries.
- Document every shared-name side effect and every conservative
  (scheme-agnostic) heuristic explicitly, same standard as Phase 1.

**Non-Goals:**
- Not wiring `vague_qualifier`, `ambiguous_expenditure_component`,
  `sanctioned_reading_unclear`, or `amount_reading_unclear` — see
  Findings above.
- Not touching the "geography" category or CM Elevate's "Section 2" —
  both need further analysis this change does not perform (see Why
  above); a future Phase 3 proposal, not this one.
- Not extending `resolved`'s shape, `_format_question`, or the matcher
  callable signature.
- Not migrating the ~7 hardcoded predicates, and not touching
  `_needs_topn_clarification`/`_needs_scope_clarification`/etc.
  directly — confirmed by reading them that none of the 30 conditions
  here collide with what they already check (topn asks "how many",
  these ask "ranked/trended by WHAT metric" — a different, later
  question in the same turn, not a duplicate one).

## Decisions

**Two scheme-agnostic heuristics for the four remaining shared names**
(`missing_metric_for_ranking`, `missing_metric_for_trend`,
`ambiguous_count_subject`, `rate_vs_count_unclear` — the fifth shared
name, `vague_qualifier`, is excluded above). Since a matcher does not
know which scheme invoked it, and each scheme's own metric vocabulary
differs (MGNREGA: expenditure/wages/person-days; PMAY-G: houses/amount
released; CM Elevate: application count only), a single hardcoded
per-scheme metric list cannot work correctly for a shared entry. Instead:
a broad, cross-scheme union of plausible metric/count nouns
(`_ANY_NAMED_METRIC` / `_SUBJECT_NOUN`) stands in for "the question
already names a specific measure," and the condition only fires when
ranking/trend/count language is present AND none of that broad union
matches. This deliberately biases toward under-firing (missing an
ambiguity Phase 1's design.md would call acceptable to miss — a slightly
less-refined but not wrong answer) rather than over-firing on a
legitimately answerable question. Documented as an approximation in the
module, same as Phase 1 documented its own conservative choices.

**All 26 scheme-unique conditions get scheme-flavored, specific regexes**
— since `check_clarifications` only ever consults a matcher for a scheme
whose own YAML defines that exact condition name, a unique name's
matcher can safely assume that scheme's own vocabulary (e.g. PMAY-G's
`sanctioned_reading_unclear` can reference "sanctioned" freely — no other
scheme's YAML defines that condition name, so it is never evaluated
against another scheme's question).

**Ordering**: `check_clarifications` already short-circuits per scheme in
YAML file order; CM Elevate's own `missing_metric_for_ranking` note
("If the user names a money measure, fall through to
any_money_amount_requested") already works correctly with zero code
changes, since Section 1 (money) precedes Section 6 (which measure) in
that file — re-verified, not assumed.

## Risks / Trade-offs

- **[Broad shared-name heuristics under-fire on ambiguous ranking/trend
  questions]** → Accepted per Phase 1's own severity framing: this
  category's failure mode is "less-refined answer," not "wrong answer."
  Tightening per-scheme precision would require a registry change
  (scheme-aware matcher keys) — out of scope here, noted as a possible
  follow-up.
- **[`vague_qualifier` gap persists]** → No user-facing regression (it
  does not fire today either); flagged as a known, deliberate gap rather
  than silently absent.
- **[Same AUTHORED-PENDING-SME-REVIEW status as Phase 1]** → These
  matchers are self-tested, not SME-reviewed for phrasing accuracy.
  Explicitly not shippable to production ahead of that review, same
  standing caveat as Phase 1's `tasks.md`.

## Migration Plan

1. Add ~30 matcher functions and their `_MATCHERS` entries to the
   existing `app/clarification_engine.py` — purely additive, same file,
   same pattern as Phase 1.
2. Extend `tests/test_clarification_engine.py` with positive/negative
   cases for the new conditions, the collision/no-regression checks
   already in place needing no change (Phase 2 introduces no new
   collisions).
3. Rollback: deleting the new `_MATCHERS` entries is safe at any point —
   `check_clarifications` degrades to skipping any condition with no
   entry, exactly as it does today for the untouched ~220 remaining
   conditions.

## Open Questions

1. Approve scoping Phase 2 to the "which measure" category as described,
   deferring "geography" and CM Elevate's "Section 2" to their own future
   proposals?
2. Approve skipping `vague_qualifier` in this phase rather than extending
   the matcher/registry contract to support it?
3. Is the broad, scheme-agnostic heuristic acceptable for the four
   shared names, or should a future change make `_MATCHERS` scheme-aware
   (a registry change, bigger than this proposal's stated scope) to
   sharpen them?
4. Approve skipping `ambiguous_expenditure_component`, `sanctioned_
   reading_unclear`, and `amount_reading_unclear` in this phase given
   the flagship-default-term regression risk, OR provide the product
   judgment call these need (e.g. a specific "already-qualified"
   phrasing list per scheme that's narrow enough to fire only on a
   genuine breakdown request, never on the bare default) so they can be
   wired precisely instead of skipped?
