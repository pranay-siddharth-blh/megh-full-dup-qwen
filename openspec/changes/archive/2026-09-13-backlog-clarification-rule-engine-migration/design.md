# Design — Clarification Rule-Engine Coverage

## The decision this document makes

**Recommendation: build a generic matcher registry (new capability
`clarification-rule-matcher`), and use it to wire in only the 75 "source
cannot answer at all" conditions first. Leave the existing ~7 hardcoded
predicates alone. Defer the remaining ~266 conditions to a later,
separate approval.**

This is a recommendation for human approval, not a decision already made —
consistent with this repo's standing rule that product/rule-design
decisions of this kind need sign-off before implementation starts.

## Why a matcher registry, not more hand-written predicates

`_admin_expenditure_clarification` and `_women_share_clarification`
(`pipeline.py:923,961`) show what hand-porting one condition costs: a
purpose-built regex, a scheme-aware text-selection function, and ~35 lines
each. At that rate, 75 conditions is ~2,600 lines of near-duplicate
boilerplate, and 341 is untenable. `app/defaults_engine.py` already solved
this exact shape of problem for `*_default_rules.yaml` (condition name →
matcher function → templated text), and it's a proven, tested pattern in
this codebase today. Reusing it for `*_classification_rules.yaml` is a
smaller lift than inventing a new mechanism, and keeps the two rule
families symmetric for anyone maintaining both later.

Mechanically: `app/clarification_engine.py` loads each scheme's
`*_classification_rules.yaml` once at startup (same caching pattern as
`_load_scheme_rules` in `defaults_engine.py`), holds a
`condition name -> matcher(question, resolved) -> bool` registry, and on
the first match returns `ClarificationNeeded(question_text)` — mirroring
the YAML's own documented semantic ("First rule that fires wins", per
every one of the four files' header comment). Order in the registry must
follow the YAML's own file order for the ported subset, since the YAML
authors already sequenced "the source cannot answer this" ahead of
"missing detail" deliberately (`mgnrega_classification_rules.yaml:5-6`:
*"requests the source cannot answer are caught before missing detail is
asked for, so the bot never collects details for a question it cannot
answer"*).

## Why NOT migrate the existing ~7 hardcoded predicates

Considered and rejected for this pass:

- They are working, tested (implicitly, via the full regression suite),
  and in production. Migrating them gains zero coverage — the YAML
  conditions they cover (`missing_top_n`, `missing_geography`,
  `missing_time_period` family, `tranche_unspecified`, plus the two
  already-ported "cannot answer" ones) already have enforcement. The only
  thing migration would change is *where* the logic lives, for no user-
  facing benefit and real regression risk (each predicate has accumulated
  scheme-specific tuning — see `_FOCUSPLUS_ONLY_TERMS`'s comment history
  in `pipeline.py` — that a generic matcher would need to reproduce
  exactly or silently regress).
- `app/defaults_engine.py`'s own collision-set pattern (`_COLLISION_CONDITIONS`,
  `defaults_engine.py:87`) already establishes the precedent for this
  codebase: a condition already owned by a hardcoded predicate stays
  owned by it. The same boundary should hold here — a new
  `clarification_engine.py` should refuse to fire on any condition name
  already covered by an existing predicate, exactly like
  `defaults_engine.py` refuses to fire on collision conditions. This
  needs its own exclusion set, seeded from the ~7 already-wired
  condition names (`missing_top_n`, `singular_superlative_without_n`,
  `missing_geography`, the year-family names, `tranche_unspecified`,
  `administrative_expenditure_requested`, `women_share_requested`, and
  their scheme-specific equivalents where names differ) — this needs a
  careful per-scheme cross-check during implementation, since the YAML
  condition names are not always byte-identical to what a hardcoded
  predicate happens to call itself internally.

## Why phase 1 is exactly the "cannot answer at all" class, not a bigger or smaller slice

- **Bigger** (e.g. all 341 at once): rejected — untenable verification
  load in one pass, and the GT proposal's own Section 12 explicitly
  identifies "clarification and default rule design" as SME-dependent,
  not something to bulk-approve without per-condition review of trigger
  phrasing.
- **Smaller** (e.g. just MGNREGA's 9): rejected — the risk (wrong/empty
  answers for unanswerable questions) is identical in every scheme, and
  the fix pattern (registry + matcher) is scheme-agnostic infrastructure
  that costs the same to build for one scheme as for four. Shipping it
  for one scheme only defers identical risk in the other three for no
  engineering-cost reason.
- **This class specifically**: it is the only one of the ~8 category
  headers across all four YAMLs where the failure mode is "confidently
  wrong or empty answer," not "acceptable answer, just less refined than
  it could be." A missed `missing_metric_for_ranking` match means the bot
  asks fewer clarifying questions than the YAML author intended — a
  UX regression. A missed `pending_dues_requested` match means the bot
  may answer a question about money the data doesn't track, using
  whatever column looks closest — a correctness/trust regression. The
  two already-ported conditions (admin expenditure, women share) are
  exactly this class, which is corroborating evidence this is where the
  real production risk already surfaced once.

## Verification requirement before implementation starts

Per the GT proposal's Section 12 framing (SMEs "identify the vague terms
and ambiguous patterns specific to the domain"), each of the 75 matcher
regexes needs a human pass checking realistic phrasings before it ships —
not just before the *YAML* was authored (an SME already wrote the
condition list and question text) but before the *matcher* that decides
when a question text triggers a given condition ships, since a
too-broad matcher risks a false-fire on a legitimately answerable
question (a UX regression opposite to the gap this closes), and a
too-narrow one silently reproduces today's zero-coverage gap for
phrasings it misses. This is new SME-verification work this proposal
creates, not existing work being skipped.

## Open questions for the approver

1. Approve building `clarification_engine.py` infrastructure + the 75-
   condition first phase as scoped above?
2. Who reviews the 75 matcher regexes for phrasing accuracy before they
   ship — same reviewer(s) who authored the original YAML, or a different
   SME pool?
3. Should `CLARIFICATION_ENGINE_ENABLED` (mirroring
   `DEFAULTS_ENGINE_ENABLED`) default to `True` or `False` on first ship,
   given a false-fire here interrupts a query with a clarifying question
   rather than silently degrading — lower blast radius than a wrong
   answer, but still a behavior change on every request.
