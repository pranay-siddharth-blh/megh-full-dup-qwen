## 0. Confirm the foundation before building on it

- [x] 0.1 Re-read `docs/baseline-audit.md`'s §5.5/§5.13/§5.14 findings and
      re-verified each against the current codebase rather than trusting
      the audit summary. Result: §5.5 and §5.14 hold as written; §5.13
      needed a nuance correction — see proposal.md's Why section.
- [x] 0.2 Read `app/followups.py` in full: next-step suggestion chips, a
      fixed deterministic bank keyed on route/scheme/metric/entities. Not
      default-filling, not result-inspection — a different concern,
      confirmed adjacent but not reusable for this phase.
- [x] 0.3 Read `app/premise_check.py` in full: `check_premises(question,
      rows) -> list[str]` (`premise_check.py:221`) — deterministic,
      no-LLM, false-numeric-premise detection against query rows. Confirmed
      as the closest existing precedent for §5.13's "inspect rows, emit a
      note" shape; confirmed it's a different concern (premise correction,
      not general findings) and won't be modified, only patterned after.
- [x] 0.4 Read `app/annotations.py:1-20` and all four
      `*_default_rules.yaml` files: confirmed still unwired
      (`annotations.py:8-13`, unchanged since Phase 0), confirmed real
      SME-authored content exists (40-129 conditions per scheme,
      `condition`/`default_value`/`assumption_text` triples with
      `{placeholder}` interpolation), confirmed the "lives in exactly one
      place" constraint against `*_classification_rules.yaml` stated in
      `mgnrega_default_rules.yaml`'s own header.
- [x] 0.5 Read `pipeline.py`'s `_result_digest()` (`pipeline.py:2868-2931`)
      in full: confirmed it already computes sum/mean/max(+row)/min(+row)
      per numeric column and distinct-value coverage per dimension column,
      from every row — currently formatted straight to text for the
      composer prompt, never exposed as structured data or in the API
      response.
- [x] 0.6 Read the `/api/query` response construction
      (`pipeline.py:3319-3331`): confirmed fields are `route`, `intent`,
      `confidence`, `schemes`, `resolved_entities`, `sql`, `sql_query`,
      `row_count`, `rows`, `data`, `answer` — no `chart` or `findings`
      field exists. Confirmed no frontend/static/client directory exists
      anywhere in this repository (grep across the repo root).
- [x] 0.7 Confirmed no chart-related config flags exist in `app/config.py`
      (`CHART_*`, `FINDING_*` — no matches) and no chart/findings
      references anywhere in `app/routers/`.
- [x] 0.8 Read the existing `backlog-clarification-rule-engine-migration` stub
      in full. Confirmed overlap: it covers §5.3 (rule-engine migration
      decision, untouched by this proposal) and a scope-statement-level
      treatment of §5.5 that already flags the same ask-vs-default tension
      this proposal's collision rule formalizes. Documented the
      relationship in proposal.md's Status section; did not modify or
      delete the old stub — that reconciliation is a human call.

## 1. Defaults engine (§5.5)

- [ ] 1.1 Design and write the per-scheme condition matcher (regex/keyword,
      following `pipeline.py`'s `_DATA_HINTS`/`_AGGREGATE_CUE` and
      `followups.py`'s `_SCHEME_RX` style) mapping question text +
      resolved entities to zero or more `*_default_rules.yaml` condition
      names. Loader parallels `annotations.py`'s existing YAML-cache
      pattern.
- [ ] 1.2 Build the collision set: every condition name already covered by
      an existing `_needs_*_clarification` predicate in `pipeline.py`.
      Enforce in code (not just by convention) that a matched default
      condition is skipped whenever it's in the collision set — zero
      behavior change to the existing clarification gate is the default
      outcome of this task group.
- [ ] 1.3 Wire non-colliding conditions into the pipeline: on match, format
      `assumption_text` (interpolating `{placeholder}`s from resolved
      entities/context) and append to the same `notes` list
      `premise_check.check_premises` already writes into, ahead of
      `compose_response`.
- [ ] 1.4 Write `tests/test_defaults_engine.py`: (a) a question matching a
      non-colliding condition (e.g. a geography default) produces the
      expected `assumption_text` in `notes`; (b) a question matching a
      colliding condition (`missing_top_n`) produces **no** default and
      leaves the existing `_needs_topn_clarification` gate firing exactly
      as before — the explicit zero-regression check; (c) a question
      matching no condition leaves `notes` unchanged; (d) malformed/missing
      `*_default_rules.yaml` for a scheme degrades to no defaults, never
      raises.
- [ ] 1.5 Run the new suite plus `test_security.py`/`test_context_manager.py`
      for regression; record pass counts here.
- [ ] 1.6 **Separate, explicitly-flagged decision point — do not implement
      as part of 1.1-1.5:** enumerate colliding conditions (starting with
      `missing_top_n`) as candidates for flipping from ask to
      silent-default, and get product sign-off per candidate before
      removing it from the collision set. Record the decision (and who
      made it) here before any such flip ships.

## 2. Findings (§5.13)

- [ ] 2.1 Refactor `_result_digest` (`pipeline.py:2868-2931`) into a shared
      structured function (typed sum/mean/max+row/min+row per numeric
      column, distinct values per dimension column) consumed by both the
      existing text-formatting call site (behavior-preserving) and the new
      `app/findings.py`.
- [ ] 2.2 Write `app/findings.py` with detectors: empty result (reuse
      `_no_data_answer`'s trigger condition), extremes (from the shared
      digest), ties (rows sharing the extreme value, within the digest's
      existing tolerance), large-result-set (configurable row-count
      threshold), stale-data (surface each scheme's `dim_year`
      `data_quality_note`/`year_note`, already curated in
      `foreign_key_augmentation.yaml`'s `nodes` section).
- [ ] 2.3 Author `data/cm_elevate/cmelevate_findings_thresholds.yaml`
      (pilot scheme only, per proposal.md's Explicitly Out of Scope) for
      the threshold-breach detector — SME-reviewed values, not invented
      defaults.
- [ ] 2.4 Wire `findings.evaluate(...)` into the data route in
      `pipeline.py`, attach the result as the new `findings` field in the
      response dict (empty list when nothing fires — never omitted, so
      consumers can rely on the key always being present).
- [ ] 2.5 Write `tests/test_findings.py`: (a) empty result produces the
      empty-result finding and nothing else; (b) a result with a clear
      max/min produces an extremes finding matching `_result_digest`'s own
      numbers exactly (cross-checked against the shared digest function
      from 2.1, not re-derived); (c) a tie at the max produces a ties
      finding; (d) a result over the large-result-set threshold produces
      that finding; (e) a CM Elevate question crossing an authored
      threshold produces a threshold-breach finding; (f) a question against
      an un-piloted scheme (no thresholds file) produces no threshold
      findings and does not raise; (g) `findings` is always a list, never
      `None`, even when nothing fires.
- [ ] 2.6 Run the new suite plus `test_security.py`/`test_context_manager.py`
      and the Phase 3 suites (`test_schema_retrieval.py`,
      `test_pipeline_schema_retrieval.py`, `test_join_graph.py`,
      `test_pipeline_join_discovery.py`) for regression; record pass
      counts here.

## 3. Chart spec (§5.14)

- [ ] 3.0 Check with whoever owns the separate frontend repository (or any
      available documentation/code there) for an existing or expected
      chart data contract, before building chart_spec.py's output shape.
      If no answer is available, proceed with the shape as designed in
      proposal.md, but note in the Phase 4 completion report that it's
      unconfirmed against a real consumer.
- [ ] 3.1 Write `app/chart_spec.py`: infer column roles (numeric /
      categorical / temporal) the same way `_result_digest` already
      separates numeric from dimension columns; given the row shape and
      the already-computed `classify_intent` result, select a chart type
      (bar / line / grouped-bar / none) deterministically.
- [ ] 3.2 Emit a minimal declarative JSON spec (plain dict — no
      Vega-Lite/Altair library dependency). Return `None` when the result
      shape doesn't support a chart (single scalar, >2 grouping
      dimensions, no numeric column).
- [ ] 3.3 Wire into the data route in `pipeline.py`, attach as the new
      `chart` field in the response dict (`null` when not applicable —
      always present as a key, per the same "never omitted" rule as
      `findings`).
- [ ] 3.4 Write `tests/test_chart_spec.py`: (a) a single-dimension,
      single-metric result produces a bar spec with the right x/y binding;
      (b) a time-series result (year_key present) produces a line spec;
      (c) a single-scalar result produces `None`; (d) a >2-grouping-dimension
      result produces `None` rather than guessing; (e) the spec is
      JSON-serializable with no additional dependency imported anywhere in
      `app/chart_spec.py` (import-list assertion, not just a smoke test).
- [ ] 3.5 Run the new suite plus the full regression set (Phase 1-3 suites
      + `test_security.py`/`test_context_manager.py`); record pass counts
      here.

## 4. Exit criteria

- [ ] 4.1 All three new suites plus every pre-existing suite (Phase 1
      security/context-manager, Phase 3 schema-retrieval/join-discovery)
      pass together, not just individually.
- [ ] 4.2 Confirm via diff that `_result_digest`'s refactor
      (task 2.1) produced byte-for-byte identical composer-prompt text
      for the existing (pre-Phase-4) call site — the shared-function
      extraction must be behavior-preserving, not just behavior-similar.
- [ ] 4.3 Confirm the collision-set enforcement (task 1.2) by running the
      full pre-Phase-4 clarification test coverage unchanged and diffing
      pass/fail against this phase's pre-implementation baseline — zero
      regressions is the bar, not "mostly the same."
- [ ] 4.4 Record, in this file, the human decision on task 1.6 (which
      colliding conditions if any get flipped to silent-default) before
      this phase is considered closeable — an unresolved decision point
      is an open item, not a rounding error.
- [ ] 4.5 Confirm via `git status`/`git diff` that `app/db.py`, `.env`, and
      the SQL execution/authorization path are untouched this phase.
- [ ] 4.6 Note in the completion report which frontend/API consumers were
      told about the new additive `findings`/`chart` response fields
      (proposal.md's Impact section) — this phase does not require their
      sign-off to ship, but they should not discover the fields by
      surprise.
