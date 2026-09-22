## Status

Proposal — not yet approved, no code written. Scopes Grant Thornton §5.5
(generic defaults), §5.13 (generic result findings), and §5.14 (chart
generator) against the current codebase, re-verified fresh rather than
taken from Phase 0's audit summary alone — the same discipline Phase 3
applied, which found the audit's §5.9 framing needed correction on
re-check.

**Relationship to the existing `backlog-clarification-rule-engine-migration`
stub:** that stub (not modified by this proposal) already covers §5.3
(whether to migrate the hardcoded clarification predicates to a YAML rule
engine) and touches §5.5 at a scope-statement level. This proposal
supersedes that stub's §5.5 portion with a concrete, re-verified plan, adds
§5.13 and §5.14 (not covered by the stub at all), and explicitly leaves
§5.3 untouched — the hardcoded predicates stay hardcoded here (see
Explicitly Out of Scope). A human should decide whether to fold the old
stub's §5.5 paragraph into this proposal or retire it; not done here.

## Why

Re-checked each of the three nodes against the running code before
assuming Phase 0's "Missing" verdicts still hold as written:

- **§5.5 (generic defaults) — verdict holds, but not for lack of material.**
  `app/annotations.py:8-13` still documents `*_default_rules.yaml` as
  deliberately unwired ("each rule's `condition` is a named label... needs
  a matcher... before these rules can fire") — unchanged since Phase 0.
  But all four schemes already carry real, SME-authored default-rule
  files: `data/mgnrega/mgnrega_default_rules.yaml` (40 conditions),
  `data/pmay/pmay_default_rules.yaml` (72), `data/focus_plus/focusplus_default_rules.yaml`
  (67), `data/cm_elevate/cmelevate_default_rules.yaml` (129) — each rule a
  `condition` / `default_value` / `assumption_text` triple, with
  `{placeholder}` interpolation, covering time period, geography, measure
  selection, units, and answer shape. `mgnrega_default_rules.yaml`'s own
  header states the load-bearing constraint: *"A condition must live in
  EITHER the clarification file OR this one. The gate runs first, so any
  condition present in both will always ask and never default."* One
  condition, `missing_top_n` (default value `5`), is the exact case the
  Grant Thornton proposal cites and Phase 0 flagged as contradicted today
  — `_needs_topn_clarification` (`pipeline.py:983`) currently **always
  asks** instead. Wiring the defaults engine therefore isn't just an
  additive feature; for any condition that collides with an existing
  hardcoded `_needs_*_clarification` predicate, it is a **behavior
  change** (ask → silent default), which is exactly the "may be a
  deliberate choice, not an oversight" tension the existing stub already
  flags. This proposal does not resolve that tension — see What Changes.

- **§5.13 (generic result findings) — verdict needs a real nuance
  correction.** Phase 0's "no findings registry exists... grepped for
  `finding`, `outlier`, `stale`, `severity`... no matches" is still true
  as a structural claim — there is no registry, no severity tagging, no
  output that reaches the API response. But it is not true that the
  underlying computation is absent: `pipeline.py`'s `_result_digest()`
  (`pipeline.py:2868-2931`) already computes, from **every** row of a
  result (not just the preview shown to the composer): sum, mean, max
  (with the row it occurs at), min (with its row), and full distinct-value
  coverage per dimension column. Today this feeds only the LLM composer's
  prompt, as a numeric-faithfulness whitelist and a "whole-result summary"
  block — never exposed as structured data, never reaches the frontend.
  `_no_data_answer` (`pipeline.py:2949`) already special-cases the
  empty-result case, again text-only. `app/premise_check.py`'s
  `check_premises(question, rows) -> list[str]` (`premise_check.py:221`)
  is a second, narrower precedent: deterministic, no LLM, inspects result
  rows against a claimed premise and returns note strings threaded into
  `compose_response`'s `notes` — a different concern (false-premise
  correction), but the same "inspect rows, emit a note" shape a findings
  check can follow. **A findings engine here is substantially a
  structuring/exposure job on top of `_result_digest`'s existing
  computation, plus new detectors for what it doesn't compute today**
  (threshold breaches, ties, large-result-set, stale-data) — not a
  from-scratch build.

- **§5.14 (chart generator) — verdict confirmed, still fully absent.**
  "chart" appears in `app/` only as a comment (`pipeline.py:3074`, itself
  just describing that the composer's answer should be consistent with
  whatever the frontend renders from raw rows) and a keyword-classifier
  token (`app/edge.py:311`). The `/api/query` response dict
  (`pipeline.py:3319-3331`) carries `rows` (top 20), `data` (top 200), and
  `answer` — no chart field of any kind. ~~This repository has no
  frontend (confirmed: no `frontend/`, `static/`, or `client/` directory
  anywhere) — the UI is a separate, unreviewed codebase.~~ **Corrected
  2026-09-11: this was wrong.** The frontend search matched only literal
  directory names and missed `web/` (`ai_query.html`, `admin.html`,
  `Meghalaya_UnifiedPortal_UI.html`, vendored Chart.js) — a real,
  git-tracked, actively-mounted frontend served by `app/main.py:213-229`
  at `/`, `/ai-query`, and `/admin-ui`. See `docs/baseline-audit.md` §3
  item 10 for the full correction and the methodology gap that produced
  this. Because the frontend is real and already implements chart
  rendering (`ai_query.html`'s `buildAnalytics()`, already reading a
  `response.chart_type` string it doesn't yet receive), this phase builds
  and exposes exactly that string, not a declarative spec/dict — see the
  corrected What Changes item 3 below, which supersedes the "spec" framing
  in this paragraph.

## What Changes

1. **`app/defaults_engine.py`** (new) — deterministic, no LLM, mirrors
   `app/premise_check.py`'s shape (a `check_*`-style pure function over
   already-resolved query state, not a network call):
   - A per-scheme condition matcher (regex/keyword, following the existing
     style of `pipeline.py`'s `_DATA_HINTS`/`_AGGREGATE_CUE` and
     `followups.py`'s `_SCHEME_RX`) mapping question text + resolved
     entities to zero or more `*_default_rules.yaml` condition names.
   - **Collision rule, enforced in code, not just documentation:** before
     applying any matched condition, check it against the set of
     conditions already covered by an existing hardcoded
     `_needs_*_clarification` predicate. If covered, the existing
     predicate's ask-behavior wins and the default is skipped — never
     silently overridden. This makes the YAML's own "lives in exactly one
     place" rule an enforced invariant, not a documentation promise, and
     means this task group ships **zero behavior change** to the existing
     clarification gate by default.
   - A follow-on, separately-approved task (not auto-applied) enumerates
     which specific colliding conditions (starting with `missing_top_n`)
     a product owner wants flipped from ask → silent-default, and removes
     just that condition from the hardcoded predicate's trigger set.
   - Applied defaults produce an `assumption_text` (interpolated) appended
     to the same `notes` channel `premise_check` already writes to, so
     `compose_response` surfaces it exactly like an existing premise
     correction — no new UI contract needed for this part.

2. **`app/findings.py`** (new) — deterministic, no LLM:
   - Refactor `_result_digest`'s per-column computation
     (`pipeline.py:2868-2931`) into a shared, structured function
     (returns typed values, not pre-formatted text) that both the existing
     prompt-building call site and the new findings module call — no
     duplicated statistics logic.
   - Detectors: empty result (reuse `_no_data_answer`'s trigger), extremes
     (from the shared digest — max/min already computed), ties (rows
     sharing the extreme value), large-result-set (row count over a
     configurable threshold), threshold breach (new, SME-authored
     per-scheme thresholds — see task group 2), stale-data (surface
     `dim_year`'s existing `data_quality_note`/`year_note`, already
     curated per scheme in `foreign_key_augmentation.yaml`'s `nodes`
     section but never read for this purpose today).
   - Each finding: `{type, severity, message, column, row_ref}` — additive
     new `findings` list in the `/api/query` response dict alongside
     `rows`/`data`/`answer` (see Impact — this is an API contract change,
     unlike Phase 3).

3. **`app/chart_spec.py`** (new) — deterministic, no LLM. **Corrected
   2026-09-11: this repository has a real, git-tracked, actively-mounted
   frontend (`web/ai_query.html`, served at `/ai-query` by
   `app/main.py:221-224`) that already implements chart rendering and
   already reads a `response.chart_type` string (`ai_query.html:2479`) —
   see `docs/baseline-audit.md` §3 item 10 for the correction and the
   methodology gap that missed it. `chart_spec.py`'s job is to compute the
   value that existing client code already consumes, not to design a new
   contract:**
   - Given `rows` and resolved column types (numeric/categorical/temporal,
     inferred the same way `_result_digest` already separates numeric from
     dimension columns), compute a **`chart_type` string** — one of `bar`,
     `doughnut`, `line`, `grouped_bar`, `stacked`, `kpi_bar` — or `None`.
     **Corrected 2026-09-11 (re-verified before implementation, not just
     at proposal time): does NOT take `classify_intent` as an input.**
     `classify_intent` (`pipeline.py:3135-3165`) is a binary DATA/KNOWLEDGE
     router classifier — by the time `chart_spec.py` runs (scoped to the
     DATA route's successful-result return, same as `findings.evaluate`,
     task 2.4), its value is a constant `"DATA"` and carries zero
     discriminating signal between the six chart types. Selection is
     driven entirely by row count and column-role counts, plus a
     question-text/column-name regex for the time-series case — the same
     inputs `buildAnalytics()` itself already uses client-side with no
     backend intent field at all. This is the exact closed vocabulary
     `web/ai_query.html`'s `buildAnalytics(question, data, hintType)`
     (`ai_query.html:2037-2165`) already branches on. No chart spec dict,
     no axis/binding JSON, no new dependency: this is a plain string (or
     `null`), not a Vega-Lite/Altair library call (both confirmed absent
     from `requirements.txt`/`requirements.lock` in Phase 0's audit and
     still absent).
   - Selection logic mirrors the shapes `buildAnalytics` itself already
     gates on, so a sent hint is never silently wasted (see
     `specs/chart-spec/spec.md` for the full scenario-by-scenario mapping,
     each cited to the exact `ai_query.html` branch it matches):
     `kpi_bar` only for a single-row, multi-numeric-column result;
     `grouped_bar` for one label column with 2+ numeric measure columns;
     `stacked` only when there are 2+ label columns and exactly one
     numeric measure column (the client's `stacked` branch requires
     `lblCols.length >= 2`, `ai_query.html:2126`, and silently falls back
     to its own default heuristic otherwise); `bar`/`doughnut`/`line` for
     the existing simple single-metric-by-category/time shapes.
   - `None` when the result shape doesn't support a chart (single scalar,
     >2 grouping dimensions, no numeric column) — additive new
     **`chart_type`** field in the response dict (a string or `null`, not
     a dict), `null` when not applicable.

## Explicitly Out of Scope

- **§5.3 rule-engine migration.** The hardcoded `_needs_*_clarification`
  predicates stay hardcoded. `*_classification_rules.yaml` stays unwired.
  That decision belongs to the existing `backlog-clarification-rule-engine-migration`
  stub, not this proposal.
- **Flipping any ask → silent-default collision without explicit,
  separate product sign-off.** `missing_top_n` is the flagship example
  Grant Thornton's proposal cites, but this proposal ships the
  collision-detection machinery, not the flip itself.
- **`*_findings_thresholds.yaml` full coverage.** Pilot on one scheme
  first (CM Elevate, matching Phase 3's pilot choice, so the pattern is
  proven against the same scheme reviewers already have context on)
  before asking SMEs to author thresholds for all four.
- **PNG/image chart rendering.** `chart_type` is a plain string, not a
  spec or image. No server-side rendering library (matplotlib, Vega CLI,
  etc.) is added, and no image bytes are generated or returned.
- **Modifying `web/ai_query.html` or any other frontend file.** Corrected
  2026-09-11 (see `docs/baseline-audit.md` §3 item 10): this repository
  does have a frontend, and it already implements full rendering logic
  for all six `chart_type` values in `buildAnalytics()`
  (`ai_query.html:2037-2165`) and already reads `response.chart_type`
  (`ai_query.html:2479`) — today that read is always `undefined` because
  the backend doesn't populate the field yet, which `buildAnalytics`
  already handles gracefully as "no hint." This phase supplies the value
  existing client code already consumes; no frontend change is needed or
  in scope.
- **Manual/visual QA of every `chart_type` value against a live browser
  render.** `tests/test_chart_spec.py` (task 3.4) verifies the selection
  logic and closed-vocabulary/serializability constraints in isolation.
  Exercising the deployed `/ai-query` page end-to-end with real query
  results for all six values is a valuable downstream verification step
  but is not required to close this phase — flagged, not skipped
  silently.
- **Rebuilding or duplicating `app/premise_check.py`.** Findings and
  premise-checking stay separate modules with separate concerns; findings
  reuses its *pattern*, not its code.
- **Any change to `DATABASE_URL`, roles, or the SQL execution path.**
  Findings and charts operate only on `rows` already fetched and already
  authorized by the existing pipeline.

## Known limitation carried forward to Phase 2

Applied defaults need to survive a follow-up turn that corrects them
("no, use last year instead") the same way an existing clarification
answer does. That correction currently rides the same bespoke,
per-worker `Session` state (`ClarificationNeeded` exception +
`Session.pending_scope_q`/`pending_village_hint`, `session_store.py:104-114`)
that Phase 0 confirmed is **lost on worker restart or session-TTL
expiry** (`session_store.py:104,113`; not rehydrated by
`conversation_store.load_context_state`) — the same durability gap
`phase-2-orchestration-durability` (currently a stub, LangGraph-vs-hardened-bespoke
decision not yet made) exists to close. Building the defaults engine now
is still worthwhile — most single-turn "assume X, disclose it" cases need
no cross-turn state at all — but a default whose correction spans a
worker restart mid-conversation will silently lose that correction
context today, exactly like an in-flight clarification does. **Tag: carries
forward to Phase 2**, same pattern as Phase 3's join-discovery hard-gate
limitation (`docs/baseline-audit.md` §3, item 8) — noted as an accepted
gap to revisit once Phase 2's durability decision lands, not a blocker for
starting this phase. Findings (§5.13) and charts (§5.14) have no such
dependency — both are computed once, post-execution, from data already in
hand, with no pause/resume state involved.

## Impact

- New files: `app/defaults_engine.py`, `app/findings.py`,
  `app/chart_spec.py`, and (pilot scope only) a new
  `data/cm_elevate/cmelevate_findings_thresholds.yaml`.
- Modified: `app/pipeline.py` — wires the three new calls into the data
  route, refactors `_result_digest` into a shared structured/text split
  (behavior-preserving for the existing prompt use).
- **API contract change, unlike Phase 3:** the `/api/query` response dict
  gains two new fields: `findings` (list, possibly empty) and
  **`chart_type`** (a string — one of `bar`/`doughnut`/`line`/
  `grouped_bar`/`stacked`/`kpi_bar` — or `null`; not a spec dict). Purely
  additive — no existing field removed, renamed, or reshaped. **Corrected
  2026-09-11:** the original framing here ("whoever owns the separate
  frontend repository needs to know before this ships") assumed no
  frontend existed in this repo. It does — `web/ai_query.html`, git-tracked
  and served at `/ai-query` by `app/main.py` — and it already reads
  `response.chart_type` (`ai_query.html:2479`) in anticipation of exactly
  this field. There is no external party to notify; this phase is what
  starts populating a field the in-repo client is already coded to
  consume. Any consumer doing strict schema validation on the response
  should still be told about the two new keys.
- No change to `DATABASE_URL`, connection roles, pools, or the SQL
  execution/authorization path.
- No new runtime dependency (`chart_type` is a plain string; no
  Vega-Lite/Altair/matplotlib package added).
- Depends on nothing from Phase 2 to *start*; depends on Phase 2's
  durability decision to be *fully correct* for defaults specifically
  (see Known limitation above).
