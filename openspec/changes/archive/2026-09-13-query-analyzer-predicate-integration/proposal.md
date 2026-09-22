## Why

`query-analyzer-consolidation` made node 5.2's structured analysis object
real and live, but explicitly deferred "every downstream rule reads its
output" (the original GT proposal's stated goal for this node) as a
separate, higher-risk change. This change investigates and implements the
safe, valuable slice of that goal.

Investigation (re-verifying rather than assuming, per this project's
convention) found the goal is not uniform across the ~8 hardcoded
`_needs_*_clarification`-style predicates in `app/pipeline.py`:
- 5 of them (`_needs_scheme_clarification`, `_needs_topn_clarification`,
  `_bank_clarification`, `_admin_expenditure_clarification`,
  `_women_share_clarification`) run **before** `classify_scheme`/
  `resolve_entities` — the analyzer needs `schemes`+`entity_result` as
  input, so these cannot consume its output without restructuring the
  entire pipeline order. Structural, not a choice.
- The other 3 (`_needs_scope_clarification`, `_needs_year_clarification`,
  `_needs_tranche_clarification`) run after entity resolution and could
  technically read `analysis` — but their existing logic already derives
  equivalent signals deterministically from the same resolved-entity data.
  Routing them through the LLM-influenced analyzer would trade proven,
  tested, deterministic behavior for less predictable behavior with no
  actual gain — a bad trade, not attempted here.
- The one genuinely **new** capability the analyzer enables is
  `analysis.ambiguous`'s LLM-flagged non-entity ambiguity (an unclear
  metric or comparison basis) — something no existing predicate checks at
  all. This is real, additive value.

A separate, much larger system — `app/clarification_engine.py` (1,334
lines, 100+ regex matchers across all four schemes) — is explicitly marked
"AUTHORED-PENDING-SME-REVIEW" as part of an already-in-flight review
(`backlog-clarification-rule-engine-migration`/`-phase-2`). Per explicit
product decision, this change does not touch it — doing so would risk
colliding with that separate, ongoing review.

Also per explicit product decision: the new `analysis.ambiguous`-driven
capability is wired as a **disclosed note** (surfaced in the answer, same
channel `premise_check`/`defaults_engine` already use), not a new
`ClarificationNeeded` pause. An LLM-judged ambiguity has no production
validation yet, and this codebase's own established design philosophy
(stated explicitly in `clarification_engine.py`'s own module docstring —
"biases toward under-firing... over over-firing on a legitimately
answerable question") argues against introducing a new hard interruption
on an unproven signal.

## What Changes

- `app/query_analyzer.py`: tag each `analysis.ambiguous` entry with its
  provenance (`origin: "entity_note"` for ones already surfaced via
  `entity_result["notes"]`, `origin: "llm"` for the analyzer's own newly
  flagged ones) so a consumer can tell which are genuinely new information
  versus a duplicate of an existing message.
- `app/pipeline.py`'s `_answer_data`: after computing `notes` (same point
  `premise_check`/`defaults_engine` already append to), append one
  disclosed note per `origin: "llm"` ambiguous entry — visible in the
  answer text, never a pause.
- **Explicitly not changed**: the 5 pre-entity-resolution predicates, the 3
  post-entity-resolution predicates' internal logic, `classify_intent`,
  `extract_entity_mentions`, and anything in `app/clarification_engine.py`.

## Capabilities

### New Capabilities
- None as a new spec-level capability — this is additive behavior on the
  existing `query-analyzer` capability's output (an extra disclosed note),
  not a new user-facing capability of its own.

### Modified Capabilities
- `query-analyzer`: `analysis.ambiguous` entries now carry provenance
  (`origin`), and a genuinely new (non-duplicate) ambiguity is now
  disclosed to the user as part of the answer text, not just returned in
  the `analysis` field for the UI badge.

## Impact

- **Modified**: `app/query_analyzer.py`, `app/pipeline.py`.
- **Not modified**: `app/clarification_engine.py` and its ~100 matchers
  (explicit product decision — separate in-flight SME review), the 5
  pre-entity-resolution predicates, the 3 post-entity-resolution
  predicates' own logic.
- **No new model call, no new dependency** — reuses the existing
  `analyze_query` call's already-returned `ambiguous_terms`.
- **Tests**: extend `tests/test_query_analyzer.py` (provenance tagging) and
  `tests/test_query_analyzer_integration.py` (disclosed note reaches the
  final answer, entity-note-origin entries are not duplicated).
