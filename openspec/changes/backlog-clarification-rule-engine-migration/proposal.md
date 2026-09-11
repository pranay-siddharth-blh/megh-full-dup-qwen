# Clarification & Defaults Engine (backlog)

## Status
Backlog item — unscheduled, scope statement only, not yet approved for
implementation. Not sequenced as a numbered phase. Derived from
`docs/baseline-audit.md` §1 (nodes 5.3, 5.5).

## Scope (one paragraph)

Decide whether to keep the ~7 hardcoded clarification predicate functions
already working in production (`_needs_scheme_clarification`,
`_needs_topn_clarification`, `_needs_scope_clarification`,
`_needs_year_clarification`, `_needs_tranche_clarification`, and two
scheme-specific ones, all in `app/pipeline.py`), or migrate them to the
YAML-driven generic rule engine the proposal specifies (Section 4.4,
"generic rules over per-use-case logic") — noting that YAML rule files for
this already exist on disk (`data/*/*_classification_rules.yaml`) but were
never wired in (`app/annotations.py:8-13`), so this is a decision about
finishing existing intent, not starting from zero. Separately, build the
"generic defaults" capability (node 5.5) that Phase 0 found entirely
missing: today the system always asks a clarifying question where the
proposal's own examples call for a silent, disclosed default (e.g. ranking
without N should default to top 5, not prompt the user) — decide the
product tradeoff (ask vs. default) per case before implementing, since the
current ask-always behavior may be a deliberate choice, not an oversight.

## Not yet decided

- Whether unifying clarification into a rule engine is worth the
  migration risk given the hardcoded version is already working and
  well-tested in production.
- Which specific cases should move from "always ask" to "default with
  disclosed assumption" — this is a product decision, not just an
  engineering one, and needs business-side input per the proposal's own
  Section 12 SME-dependency framing.

This backlog item requires its own approval and design review before work
starts.
