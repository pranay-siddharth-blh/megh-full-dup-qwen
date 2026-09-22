## Context

See `proposal.md` for motivation. Relevant current-state facts that shape this
design (all confirmed by reading the code directly, not assumed):

- `classify_scheme` (`app/pipeline.py:1796`) has exactly one production call
  site (`_answer_data`, `pipeline.py:3369`) and 12 direct call sites in
  `tests/test_scope_scheme_classifier.py` asserting a bare `list[str]` return.
  Its internal decision points are: a named-scheme shortcut
  (`_shortcut_scheme`), fuzzy matching (`_fuzzy_named_schemes`), term inference
  (`_infer_scheme_from_terms`), and a guided-JSON LLM call — in that order.
- `extract_entity_mentions` (`pipeline.py:1869`) is a span-finding LLM call;
  `resolve_entities` (`pipeline.py:2034`) resolves each span to a canonical DB
  value and **raises `ClarificationNeeded` immediately** when a mention is
  genuinely ambiguous between candidates (e.g. `pipeline.py:2093`) — an
  ambiguous entity never survives to be returned in `entity_result`. A mention
  that resolves to nothing in the data is not an error; it is appended to
  `entity_result["notes"]` as plain text (e.g. `pipeline.py:2096`) and the
  query proceeds without it.
- `_answer_data` (`pipeline.py:3349`) runs a fixed sequence: unsupported-scheme
  check → scheme-clarification → topN-clarification → `classify_scheme` →
  `resolve_entities` → clarification-engine (5.3) → region → scope → year →
  tranche clarifications → `generate_sql` → `execute_with_repair` →
  `compose_response` → findings (5.13) → chart_spec (5.14) → return. Any
  clarification raise exits the function via exception; no response dict is
  ever built for a paused turn.
- `web/ai_query.html` already implements a full renderer for `response.scope`
  (NODE 1, `ai_query.html:2216-2241`) and `response.analysis` (NODE 2,
  `ai_query.html:2243-2283`), gated by `SHOW_ROUTE_BADGE = false`
  (`ai_query.html:2214`). Neither key exists in any backend response today.
- `llm.call_classifier(prompt, guided={"guided_json": schema})` is the
  existing idiom for a constrained-JSON model call, already used by
  `classify_scheme`, `extract_entity_mentions`, and `classify_intent`.

## Goals / Non-Goals

**Goals:**
- Make `response.analysis` and `response.scope` real, live, and populated on
  every successful DATA-route answer, matching the exact shape
  `web/ai_query.html` already expects (field names included) — see field
  mapping table below.
- Reuse node 5.6's already-verified entity resolution and the existing topN
  regex machinery for anything deterministic; only use a new model call for
  what is genuinely not already computed anywhere (`query_type`, `metric`,
  `time_scope`, `intent_summary`, non-entity ambiguity).
- Keep `classify_scheme`, `extract_entity_mentions`, `classify_intent`, and
  every `_needs_*_clarification` predicate's externally observable behavior
  byte-for-byte unchanged.

**Non-Goals:**
- Rewiring the ~10 hardcoded clarification predicates to consume this node's
  output ("every downstream rule reads its output" per the original GT
  proposal text) — deferred, see proposal.md's "What Changes".
- Replacing `extract_entity_mentions` or `classify_intent` with the new model
  call. They stay as separate, already-tested functions; the new call adds
  fields they don't produce (query_type, metric, time_scope, intent_summary),
  it does not re-derive fields they already produce correctly.
- Populating `analysis`/`scope` for KNOWLEDGE, EDGE, or denied routes. The
  frontend already guards for their absence (`if (!s) return ''`); adding them
  there would require plumbing scope/entity state through code paths that
  today never compute it, for a badge that (per its own code comment) is
  developer-facing diagnostic detail, not user-critical.
- A live smoke test against the real model gateway — this environment has no
  reachable `DATABASE_URL`/model-gateway credentials (same constraint the
  baseline audit itself documents). Verification here is unit-level: every
  deterministic code path exercised directly, the model-call path exercised
  via mocked responses, matching the precedent set by every other node's test
  suite in this repo (`tests/test_scope_scheme_classifier.py`,
  `tests/test_intent_classifier.py`, etc.).

## Decisions

### 1. `classify_scheme`'s public contract does not change; a new `_classify_scheme_detailed` wrapper sits beside it

**Decision:** Extract `classify_scheme`'s body into
`_classify_scheme_detailed(question) -> tuple[list[str], ScopeMeta]` where
`ScopeMeta` is a small dataclass (`confidence: float`, `source: Literal["llm",
"shortcut", "fallback"]`, `reason: str`). Each of `classify_scheme`'s existing
early-return points gets one extra line setting the matching `ScopeMeta`
before returning. `classify_scheme` itself becomes:
```python
async def classify_scheme(question: str) -> list[str]:
    schemes, _ = await _classify_scheme_detailed(question)
    return schemes
```
`_answer_data` calls `_classify_scheme_detailed` directly instead of
`classify_scheme`, and threads `is_followup` (from `_run_pipeline`'s existing
`is_followup_rewrite` local, passed down as a new `_answer_data` parameter)
into the final `scope` dict.

**Why over alternatives:**
- *Alternative: change `classify_scheme`'s return type.* Rejected — breaks the
  contract 12 existing tests assert and would require touching every call
  site's return-value handling for no behavioral benefit.
- *Alternative: derive scope metadata by re-inspecting `schemes` after the
  fact (e.g. "if len==1 and named, call it a shortcut").* Rejected — this
  would be guessing the mechanism from its output rather than recording the
  mechanism that actually ran, defeating the point of an audit trace, and
  would misclassify e.g. a single scheme that resolved via the LLM path.

### 2. The new analyzer call is additive and placed after clarification gates, not before

**Decision:** `query_analyzer.analyze_query(question, schemes, entity_result)`
is called in `_answer_data` immediately before `generate_sql`, i.e. after
every one of the existing clarification checks has already passed. It is not
consulted by any of them.

**Why:** Placing it earlier and wiring its output into the clarification
predicates is exactly the higher-risk rewrite this change explicitly defers
(see proposal.md). Placing it after the gates means: (a) it never runs on a
question that's about to pause anyway, saving a model call and avoiding
inventing an analysis for an incomplete question; (b) it cannot change which
questions get clarified or how, so the entire existing clarification test
suite needs zero changes; (c) if it fails, the fix is isolated to one new
function with no fan-out into control flow.

### 3. Field-by-field mapping to what the frontend already expects

| `response.analysis` field | Source | New model call? |
|---|---|---|
| `query_type` | Regex fast-path (`_RANKING_CUE`+`_RANK_DIMENSION` → `ranking`; existing comparison detection cues → `comparison`; else LLM) | Fallback only |
| `metric` | New model call | Yes |
| `time_scope` | `entity_result["resolved"]` year/year-range when present, else new model call's `time_scope` | Fallback only |
| `granularity` | Deterministic: village > block > district(s)/district_list/region > state, from `entity_result["resolved"]` | No |
| `limit` | `_EXPLICIT_COUNT` match already used by `_needs_topn_clarification`/`_inject_topn` | No |
| `entities.{districts,blocks,villages,...}` | `entity_result["resolved"]`/`["display"]`, remapped into the frontend's bucket shape | No |
| `ambiguous[].{term,kind,why}` | `entity_result["notes"]` (not-found mentions) + new model call's own flagged ambiguous terms (unclear metric/comparison basis) | Partial |
| `intent_summary` | New model call | Yes |

| `response.scope` field | Source |
|---|---|
| `schemes` | `_classify_scheme_detailed`'s `schemes` |
| `confidence` | `ScopeMeta.confidence` |
| `source` | `ScopeMeta.source` |
| `reason` | `ScopeMeta.reason` |
| `is_followup` | `_run_pipeline`'s `is_followup_rewrite`, threaded through |
| `in_scope` | Always `true` when this object is present (see Non-Goals — `OutOfScope`/edge routes never attach `scope` at all, so the frontend's `in_scope === false` branch is unreachable until a later change wires those routes up; documented as a known limitation, not silently implied) |

**Why one combined model call for `metric`/`intent_summary`/fallback
`query_type`/`time_scope`/partial `ambiguous` rather than several:** Matches
the original GT proposal's own "Approach" for this node (one constrained-JSON
call) and keeps latency/cost to one extra call per question, not four.

### 4. Model-call failure degrades to an omitted field, never an error

**Decision:** `analyze_query` wraps its model call in the same
try/except-and-log pattern already used for `findings`/`chart_spec`/
`defaults_engine` in `_answer_data` (`pipeline.py:3448-3494`) — on failure,
return `None` (or a partial object with only the deterministic fields filled)
rather than raising, and `_answer_data` attaches whatever comes back, possibly
`None`, to `result["analysis"]`.

**Why:** Node 5.2 is explicitly additive per this change's scope — it must
never be able to turn a working answer into a failed request. This mirrors
the exact isolation pattern this codebase already uses for every other
additive node (5.5, 5.13, 5.14).

### 5. Audit trail mirroring

**Decision:** `analysis`/`scope` are added as two new `app.query_audit`
columns (`analysis JSONB`, `scope JSONB`), via the exact same mechanism
`findings`/`chart_type`/`sql`/`result_preview`/`answer` already used:
`app/appdb.py`'s self-managed, idempotent `_DDL` block (`ALTER TABLE
app.query_audit ADD COLUMN IF NOT EXISTS ...`), applied automatically by the
app itself on startup (`db.execute_script(_DDL)`) — not a manual
`deploy/sql/`-style migration requiring a coordinated maintenance window
(that pattern is reserved for the unrelated `megh_app` role cutover, which
needs a superuser and a restart; this is neither). `conversation_store
._persist_turn`'s `INSERT INTO app.query_audit` and `app/routers/query.py
::_mirror_audit`'s JSONL mirror both get the two new fields. Also mirrored
into `conversation_turns.response`'s existing JSON blob (already carries
additive per-turn fields like `clarification` with no migration) so a
reopened conversation thread can redraw the same badge.

**Correction to an earlier draft of this decision:** this document originally
assumed `findings`/`chart_type` lived in a JSON blob and planned to follow
that path. Re-verifying against the actual code (per this project's
established "re-verify claims" discipline) found they are real dedicated
columns added via `app/appdb.py`'s `_DDL`, not a blob — corrected here before
implementation, and the implementation follows the verified mechanism, not
the original assumption.

**Why:** Closes part of the 11.3 audit finding ("no analyser output") with
the same low-risk, already-proven, migration-free mechanism used for every
other field that phase added, rather than inventing a different one.

### 6. Frontend: flip the flag, fix the stale comment

**Decision:** Set `SHOW_ROUTE_BADGE = true` in `web/ai_query.html` and correct
its comment (currently claims the backend already returns these fields).

**Why:** This is the actual "end to end workable" step — without it, the
backend work is real but invisible, exactly the state the proposal is
correcting. This is a visible UI change to end users (a small collapsible
badge above each answer), called out explicitly rather than done silently.

## Risks / Trade-offs

- **[Risk]** The new model call adds latency to every DATA-route answer.
  → **Mitigation**: single combined call (Decision 3), regex fast-path skips
  it entirely for the common ranking/comparison cases (Decision 3), and
  failure degrades gracefully (Decision 4) so a slow/broken model call never
  blocks the answer — worst case it times out under `llm.call_classifier`'s
  existing timeout handling and `analysis` is simply omitted.
- **[Risk]** `_classify_scheme_detailed`'s refactor of `classify_scheme`
  touches a function with 33 existing unit-level checks; a mistake in moving
  logic could silently change a returned scheme list.
  → **Mitigation**: `tests/test_scope_scheme_classifier.py` runs unmodified
  as a regression gate before this is considered done (see proposal.md
  Impact); the refactor is a mechanical extraction (move body, add metadata
  at each existing return point), not a rewrite of any decision logic.
- **[Risk]** `response.scope.in_scope` is always `true` when present, which
  could read as if the field always means "in scope" when really it means
  "this route computes scope at all." → **Mitigation**: documented explicitly
  in Decision 3's table and in the spec as a known limitation; not hidden.
- **[Trade-off]** Deferring the clarification-predicate rewiring means 5.2 is
  not "fully" the proposal's original vision (a node every rule reads from)
  after this change — only a real, live, additive version of it. Judged
  acceptable because the audit's actual finding was "no structured object
  exists," which this closes; the deeper rewiring is a separate, larger,
  separately-reviewable risk.

## Migration Plan

No data migration. Deployment is a normal code + static-asset release:
1. Ship `app/query_analyzer.py` and the `pipeline.py`/`appdb.py`/
   `conversation_store.py` changes together (analysis/scope are additive keys,
   safe to deploy ahead of the frontend flag flip if ever needed).
2. Ship the `web/ai_query.html` flag flip.
3. Rollback is a plain revert of either commit independently — the backend
   change is inert with the flag off, and the flag flip alone is a no-op
   without the backend change (frontend already null-guards both `s` and `a`).

## Open Questions

None — see Non-Goals for deliberately deferred scope, and Decisions for
choices made rather than left open.
