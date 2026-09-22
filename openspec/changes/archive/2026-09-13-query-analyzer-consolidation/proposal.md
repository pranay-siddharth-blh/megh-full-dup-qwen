## Why

`docs/baseline-audit.md` §5.2 classifies the proposal's "Query analyzer" node as
**partially implemented — architecturally split**: no single structured object
(query type, metric, entities, time scope, granularity, ambiguous terms, intent
summary) exists anywhere. Its responsibilities are spread across
`extract_entity_mentions`, `classify_intent`, and ~10 standalone
`_needs_*_clarification` predicates, and this row was explicitly re-verified as
"unverified in depth" in the audit's summary table.

Concretely, `web/ai_query.html` already ships a finished frontend for this node
— CSS block "NODE 2 — Query Analyzer chips" (`ai_query.html:667`), a renderer
that reads `response.analysis.{query_type,metric,granularity,limit,entities,
time_scope,ambiguous}` (`ai_query.html:2243-2283`), and a sibling NODE 1 renderer
that reads `response.scope.{schemes,confidence,source,is_followup,reason,
in_scope}` (`ai_query.html:2216-2241`). The backend returns neither key today
(confirmed: zero occurrences of `"analysis"` or `"scope"` as response keys in
`app/pipeline.py`), so the badge is permanently dead code — hidden today only by
`const SHOW_ROUTE_BADGE = false` (`ai_query.html:2214`), whose own comment
("The backend still returns `scope` and `analysis`") is incorrect as of this
reading. This is the "end to end workable" gap: a real backend node exists to
build, a real frontend consumer already waits for it, and nothing connects them.

## What Changes

- Add `app/query_analyzer.py`: a new, additive analysis step that runs once per
  successful DATA-route question (after entity resolution, before SQL
  generation) and produces the structured object the frontend already expects:
  `query_type` (aggregation/ranking/comparison/trend/lookup/distribution/
  filter_list), `metric`, `time_scope`, `intent_summary`, and non-entity
  `ambiguous` terms via one constrained-JSON LLM call (matching the proposal's
  own "Approach" for this node and this codebase's existing `guided_json`
  idiom), with a regex fast-path for the unambiguous cases (ranking/topN,
  comparison) reusing the already-tested `_RANKING_CUE`/`_RANK_DIMENSION`/
  `_EXPLICIT_COUNT` patterns — same "keyword fast-path first, LLM otherwise"
  style `classify_intent` already uses.
- `entities`, `granularity`, and `limit` in that object are assembled
  **deterministically from the existing, already-verified pipeline state**
  (`entity_result["resolved"]`/`["display"]` from node 5.6, and the existing
  topN extraction) — not re-derived by the LLM — so node 5.6's proven
  three-way resolved/ambiguous/not_found behavior is reused, not duplicated
  or risked.
- Add a small, additive `_classify_scheme_detailed()` wrapper in
  `app/pipeline.py` around the existing `classify_scheme()` decision points
  (named-scheme shortcut / fuzzy match / LLM call / term inference) that
  captures `confidence`, `source`, and a human-readable `reason` without
  changing `classify_scheme()`'s own signature or behavior — its 12 existing
  call sites in `tests/test_scope_scheme_classifier.py` and its one production
  call site are unaffected.
- Wire both into the live request path: `_answer_data` attaches
  `result["scope"]` and `result["analysis"]` to every successful DATA-route
  response. Also mirrored into the audit trail (`app/appdb.py` /
  `conversation_store.py`, already extended once in
  `phase-2-audit-trail-enrichment`) — closing part of the 11.3 audit gap that
  explicitly lists "no analyser output" as missing.
- Flip `SHOW_ROUTE_BADGE` to `true` in `web/ai_query.html` now that the data it
  renders is real, and correct its stale comment.
- **Explicitly out of scope, deferred to a follow-on change** (same
  incremental discipline already used for 5.4/5.9 in this codebase): rewiring
  the ~10 hardcoded `_needs_*_clarification` predicates to *read* this node's
  output ("every downstream rule reads its output" per the original proposal
  text) and replacing `extract_entity_mentions`/`classify_intent` outright.
  Both are proven, heavily-tested, delicately-tuned functions (33 and
  keyword-fast-pathed checks respectively) with dozens of hand-fixed edge
  cases documented inline; collapsing them into this new object in the same
  change would be a high-regression-risk rewrite disproportionate to the
  audit's actual finding, which is that no structured object exists yet — not
  that the current split logic is wrong. This change makes the object real,
  live, and visible end to end; a later change can migrate individual
  predicates onto it one at a time once it has run in production.

## Capabilities

### New Capabilities
- `query-analyzer`: for every DATA-route question that reaches SQL generation,
  the system produces a structured analysis (query type, metric, entities,
  time scope, granularity, limit, ambiguous terms, intent summary) and returns
  it as `response.analysis`.
- `scope-decision-trace`: for every DATA-route question, the system records how
  the scope/scheme decision was reached (source, confidence, human-readable
  reason, follow-up flag) and returns it as `response.scope`.

### Modified Capabilities
- None. `classify_scheme`, `extract_entity_mentions`, `classify_intent`, and
  all `_needs_*_clarification` predicates keep their current external
  behavior unchanged; this change only adds new, additive outputs alongside
  them.

## Impact

- **New file**: `app/query_analyzer.py`.
- **Modified**: `app/pipeline.py` (`_classify_scheme_detailed` wrapper,
  `_answer_data` wiring), `app/appdb.py` / `app/conversation_store.py` (audit
  mirror of the two new fields), `web/ai_query.html` (flip
  `SHOW_ROUTE_BADGE`, fix its stale comment).
- **New dependency**: none — reuses the existing `llm.call_classifier(...,
  guided={"guided_json": ...})` mechanism already used by `classify_scheme`/
  `classify_intent`/`extract_entity_mentions`.
- **Tests**: new `tests/test_query_analyzer.py`; `tests/
  test_scope_scheme_classifier.py` must keep passing unchanged (regression
  guard on `classify_scheme`'s public contract).
- **No schema/API breaking change**: `response.analysis`/`response.scope` are
  new, additive, optional keys; nothing existing is removed or renamed.
