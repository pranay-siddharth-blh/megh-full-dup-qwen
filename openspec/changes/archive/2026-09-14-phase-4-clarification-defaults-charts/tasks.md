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

- [x] 1.1 Design and write the per-scheme condition matcher (regex/keyword,
      following `pipeline.py`'s `_DATA_HINTS`/`_AGGREGATE_CUE` and
      `followups.py`'s `_SCHEME_RX` style) mapping question text +
      resolved entities to zero or more `*_default_rules.yaml` condition
      names. Loader parallels `annotations.py`'s existing YAML-cache
      pattern.
- [x] 1.2 Build the collision set: every condition name already covered by
      an existing `_needs_*_clarification` predicate in `pipeline.py`.
      Enforce in code (not just by convention) that a matched default
      condition is skipped whenever it's in the collision set — zero
      behavior change to the existing clarification gate is the default
      outcome of this task group.
- [x] 1.3 Wire non-colliding conditions into the pipeline: on match, format
      `assumption_text` (interpolating `{placeholder}`s from resolved
      entities/context) and append to the same `notes` list
      `premise_check.check_premises` already writes into, ahead of
      `compose_response`.
- [x] 1.4 Write `tests/test_defaults_engine.py`: (a) a question matching a
      non-colliding condition (e.g. a geography default) produces the
      expected `assumption_text` in `notes`; (b) a question matching a
      colliding condition (`missing_top_n`) produces **no** default and
      leaves the existing `_needs_topn_clarification` gate firing exactly
      as before — the explicit zero-regression check; (c) a question
      matching no condition leaves `notes` unchanged; (d) malformed/missing
      `*_default_rules.yaml` for a scheme degrades to no defaults, never
      raises.
      Implementation note on (a): `missing_geography` was NOT used as the
      non-colliding example — it was placed in the collision set instead
      (see 1.2's implementation), since `_needs_scope_clarification` already
      owns the "geography missing" topic in at least the fully-unscoped
      case, and this module's design deliberately treats the whole topic as
      colliding rather than slicing it into colliding/non-colliding
      sub-cases. `expenditure_unit_unspecified` was used instead — a
      condition with no overlapping hardcoded predicate at all — as the
      demonstrated non-colliding example.
- [x] 1.5 Run the new suite plus `test_security.py`/`test_context_manager.py`
      for regression; record pass counts here.
      **Result (2026-09-11):** `test_defaults_engine.py` 9/9 PASS,
      `test_security.py` 31/31 PASS, `test_context_manager.py` 52/52 PASS.
      Zero failures, all three run standalone (`python tests/test_*.py`,
      exit code 0 each).
- [x] 1.6 **Separate, explicitly-flagged decision point — do not implement
      as part of 1.1-1.5:** enumerate colliding conditions (starting with
      `missing_top_n`) as candidates for flipping from ask to
      silent-default, and get product sign-off per candidate before
      removing it from the collision set. Record the decision (and who
      made it) here before any such flip ships.
      **Decision (2026-09-11, product owner, this session):** all four
      candidate families reviewed against their actual `default_value`/
      `assumption_text` strings — decision is **keep asking, zero flips**,
      across all 12 conditions:
      - Top-N (`missing_top_n`, `singular_superlative_without_n`) — keep asking.
      - Geography (`missing_geography`) — keep asking.
      - Year/time (`missing_time_period`, `relative_year_latest`,
        `relative_year_previous`, `relative_year_earliest`,
        `multi_year_request_without_years`, `trend_without_period`,
        `comparison_without_second_period`, `year_range_partly_outside_data`,
        `job_cards_without_year`) — keep asking.
      - Tranche (`tranche_unspecified`) — keep asking.
      No code change required: `_COLLISION_CONDITIONS`
      (`app/defaults_engine.py:87`) already contains all 12 and ships
      unchanged.

## 2. Findings (§5.13)

- [x] 2.1 Refactor `_result_digest` (`pipeline.py:2868-2931`) into a shared
      structured function (typed sum/mean/max+row/min+row per numeric
      column, distinct values per dimension column) consumed by both the
      existing text-formatting call site (behavior-preserving) and the new
      `app/findings.py`.
- [x] 2.2 Write `app/findings.py` with detectors: empty result (reuse
      `_no_data_answer`'s trigger condition), extremes (from the shared
      digest), ties (rows sharing the extreme value, within the digest's
      existing tolerance), large-result-set (configurable row-count
      threshold), stale-data (surface each scheme's `dim_year`
      `data_quality_note`/`year_note`, already curated in
      `foreign_key_augmentation.yaml`'s `nodes` section).
      Implementation note: `foreign_key_augmentation.yaml`'s `nodes` section
      turned out to hold only PROSE ABOUT `data_quality_note`/`year_note`
      (that the column exists, what it means), not the note text itself —
      the actual note is a live database column value on `curated.dim_year`,
      pre-joined into most scheme views. The stale-data detector therefore
      reads `data_quality_note`/`year_note` directly off the query's own
      returned rows, not from a YAML lookup. This is also the *safer* design:
      `focusplus_foreign_key_augmentation.yaml` line 144 explicitly notes the
      column is scheme-blind ("do not surface MGNREGA's notes on a Focus
      Plus answer") — a note copied in from a separate per-scheme YAML
      lookup could misattribute; reading only what this specific query
      actually returned cannot.
- [ ] 2.3 **Blocked — needs SME input, not implemented.** Author
      `data/cm_elevate/cmelevate_findings_thresholds.yaml` (pilot scheme
      only, per proposal.md's Explicitly Out of Scope) for the
      threshold-breach detector — SME-reviewed values, not invented
      defaults. The detector and its YAML loader are fully implemented and
      tested (task 2.2/2.5) against a temporary test-fixture thresholds
      file; no real file exists for any scheme yet, so today every scheme
      (CM Elevate included) correctly produces zero threshold-breach
      findings — same posture as task 1.6. Needs a product/SME owner before
      this checkbox can close.
      **Decision (2026-09-11, product owner, this session):** explicitly
      deferred — no real thresholds file authored now. Current safe
      posture (zero threshold-breach findings) stays in place until an SME
      provides real numbers. Revisit then; not blocking phase close.
- [x] 2.4 Wire `findings.evaluate(...)` into the data route in
      `pipeline.py`, attach the result as the new `findings` field in the
      response dict (empty list when nothing fires — never omitted, so
      consumers can rely on the key always being present).
      Scoped to the DATA route's successful-result return only (per this
      task's own wording, "the data route") — the pre-existing `_denied()`
      early return and the KB/edge routes are separate response shapes, out
      of scope for this phase, and were not touched.
- [x] 2.5 Write `tests/test_findings.py`: (a) empty result produces the
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
- [x] 2.6 Run the new suite plus `test_security.py`/`test_context_manager.py`
      and the Phase 3 suites (`test_schema_retrieval.py`,
      `test_pipeline_schema_retrieval.py`, `test_join_graph.py`,
      `test_pipeline_join_discovery.py`) for regression; record pass
      counts here.
      **Result (2026-09-11):** `test_defaults_engine.py` 9/9,
      `test_findings.py` 25/25, `test_security.py` 31/31,
      `test_context_manager.py` 52/52, `test_schema_retrieval.py` 8/8,
      `test_pipeline_schema_retrieval.py` 9/9, `test_join_graph.py` 5/5,
      `test_pipeline_join_discovery.py` 8/8. **147/147 checks pass, 0
      failures across all 8 suites**, each run standalone
      (`python tests/test_*.py`, exit code 0).

## 3. Chart spec (§5.14)

- [x] 3.0 **Resolved 2026-09-11, not via an external frontend owner —
      there isn't one.** The original premise (a "separate frontend
      repository" to consult) was wrong: `web/ai_query.html` is real,
      git-tracked, in this repository, and already implements the
      consumer side of this contract. Its `buildAnalytics(question, data,
      hintType)` (`ai_query.html:2037-2165`) already reads
      `response.chart_type` (`ai_query.html:2479`) and already branches on
      a closed six-value vocabulary (`bar`/`doughnut`/`line`/
      `grouped_bar`/`stacked`/`kpi_bar`). The expected contract is not
      unconfirmed — it's read directly from the consumer's own code. See
      `docs/baseline-audit.md` §3 item 10 and the corrected proposal.md /
      specs/chart-spec/spec.md.
- [x] 3.1 Write `app/chart_spec.py`: infer column roles (numeric /
      categorical / temporal) the same way `_result_digest` already
      separates numeric from dimension columns; given only the row/column
      shape (row count, column-role counts) plus a question-text/
      column-name regex for the time-series case, deterministically select
      a `chart_type` string — one of `bar`, `doughnut`, `line`,
      `grouped_bar`, `stacked`, `kpi_bar` — or `None`. **Does NOT take
      `classify_intent` as an input** (re-verified 2026-09-11:
      `classify_intent` is a binary DATA/KNOWLEDGE router classifier,
      constant `"DATA"` by the time this function is reached, contributing
      no signal between the six chart types — see proposal.md's corrected
      §3 item 3 and spec.md's first requirement for the full explanation).
      Match the exact shape gates `buildAnalytics()` itself already
      enforces client-side (see spec.md scenarios): `kpi_bar` only for a
      1-row, 2+-numeric-column result; `stacked` only for 2+ label columns
      with exactly 1 numeric column; `grouped_bar` for 1 label column with
      2+ numeric columns; `line` for a time signal; `doughnut` for a small
      (≤6 row) non-time categorical result; `bar` otherwise.
      **Implementation note (2026-09-11):** column-role inference is a
      local copy, not a call into `findings.compute_result_stats` —
      documented in `chart_spec.py`'s own module docstring, two concrete
      reasons: (1) `compute_result_stats` returns `None` for <2 rows, but
      chart selection needs a working column split for the 1-row
      `kpi_bar` case; (2) `compute_result_stats` classifies numeric-ness
      per *cell*, so a mixed column can land in both its `numeric` and
      `dimensions` buckets — wrong for chart selection, where a column
      belongs on the value axis only if *every* value in it is numeric.
      `_column_roles` classifies per column (all-or-nothing) instead,
      matching the standard `buildAnalytics()` itself applies
      (`ai_query.html:2081-2087`). Reuses `findings._NONSTAT_COL`'s exact
      name-exclusion pattern (year/yr/fy/pincode/rank/serial/_key/_code/
      _id never count as a metric regardless of value shape) rather than
      `buildAnalytics`'s own value-only numeric-string regex, which that
      client code's own comment admits misreads a bare 4-digit year
      column as numeric — the name-aware exclusion avoids feeding that
      known client-side limitation a bad hint in the first place.
- [x] 3.2 Return `None` when the result shape doesn't support a chart
      (single scalar, >2 grouping dimensions, no numeric column) — a
      plain string or `None`, not a dict/spec. No Vega-Lite/Altair/
      matplotlib import anywhere in `app/chart_spec.py`.
- [x] 3.3 Wire into the data route in `pipeline.py`, attach as the new
      `chart_type` field in the response dict (`null` when not
      applicable — always present as a key, per the same "never omitted"
      rule as `findings`). Selection is computed over `rows[:200]` — the
      exact same slice the `data` field carries — not the full unlimited
      `rows`, so the row-count-based gates (1-row `kpi_bar`, ≤6-row
      `doughnut`) always agree with what `buildAnalytics()` actually sees
      client-side (a deliberate choice, not the literal "given `rows`"
      wording — the two only differ when a result exceeds 200 rows).
      Scoped identically to `findings` (task 2.4): the DATA route's
      successful-result return only — `_empty_data_fields()`, `_denied()`,
      and the KB/edge routes were not touched, so `chart_type` is genuinely
      absent (not `null`) on those response shapes, same as `findings`
      there today. Added `CHART_SPEC_ENABLED` config flag (default `True`)
      mirroring `FINDINGS_ENABLED`/`DEFAULTS_ENGINE_ENABLED`'s pattern.
- [x] 3.4 Write `tests/test_chart_spec.py`: (a) a single-dimension,
      single-metric result selects `"bar"`; (b) a time-series result
      (temporal column or year/month/trend in the question) selects
      `"line"`; (c) a single-row, 2+-numeric-column result selects
      `"kpi_bar"`, and a non-1-row result with the same column shape does
      NOT select `"kpi_bar"` (the client silently ignores that hint
      outside the 1-row case — the selector must not emit it there); (d) a
      1-label-column, 2+-numeric-column result selects `"grouped_bar"`;
      (e) a 2-label-column, 1-numeric-column result selects `"stacked"`,
      and a 1-label-column variant of the same data does NOT (falls back
      to bar/doughnut/line instead — matches `buildAnalytics`'s
      `lblCols.length >= 2` gate, `ai_query.html:2126`); (f) a
      small (≤6 row) non-time categorical result selects `"doughnut"`;
      (g) a single-scalar result produces `None`; (h) a
      >2-grouping-dimension result produces `None` rather than guessing;
      (i) a no-numeric-column result produces `None`; (j) every returned
      value is JSON-serializable via the standard library and
      `app/chart_spec.py`'s import list contains no charting/
      visualization library (import-list assertion, not just a smoke
      test).
- [x] 3.5 Run the new suite plus the full regression set (Phase 1-3 suites
      + `test_security.py`/`test_context_manager.py`); record pass counts
      here.
      **Result (2026-09-11):** `test_chart_spec.py` 28/28,
      `test_defaults_engine.py` 9/9, `test_findings.py` 25/25,
      `test_security.py` 31/31, `test_context_manager.py` 52/52,
      `test_schema_retrieval.py` 8/8, `test_pipeline_schema_retrieval.py`
      9/9, `test_join_graph.py` 5/5, `test_pipeline_join_discovery.py`
      8/8. **175/175 checks pass, 0 failures across all 9 suites**, each
      run standalone (`python tests/test_*.py`, exit code 0).

## 4. Exit criteria

- [x] 4.1 All three new suites plus every pre-existing suite (Phase 1
      security/context-manager, Phase 3 schema-retrieval/join-discovery)
      pass together, not just individually.
      **Result (2026-09-11):** ran all 12 files under `tests/` (excluding
      `smoke_restructure.py`) back-to-back in one sweep — every file exits
      0, zero FAILED markers: `test_chart_spec.py`,
      `test_context_manager.py`, `test_defaults_engine.py`,
      `test_findings.py`, `test_join_graph.py`, `test_pii_audit_trail.py`,
      `test_pii_guard.py`, `test_pipeline_join_discovery.py`,
      `test_pipeline_schema_retrieval.py`, `test_schema_retrieval.py`,
      `test_security.py`, `test_sql_join_validator.py`.
- [x] 4.2 Confirm via diff that `_result_digest`'s refactor
      (task 2.1) produced byte-for-byte identical composer-prompt text
      for the existing (pre-Phase-4) call site — the shared-function
      extraction must be behavior-preserving, not just behavior-similar.
      **Result (2026-09-11):** reconstructed the pre-refactor algorithm
      verbatim from `git show 07141af^:app/pipeline.py` (the commit that
      performed the refactor) and diffed its output string-for-string
      against the current `app.pipeline._result_digest` across 9 row
      shapes covering every branch the diff touched: <2 rows, `None`
      cells, a `_NONSTAT_COL`-excluded column (`financial_year`), a tie at
      the max, multi-dimension/multi-numeric, >40 distinct dimension
      values (truncation path), float rounding, and an `_id`/`_code`-style
      excluded column. All 9 byte-identical (`allowed` number set and
      rendered text both). Script not committed (scratchpad, one-off
      verification).
- [x] 4.3 Confirm the collision-set enforcement (task 1.2) by running the
      full pre-Phase-4 clarification test coverage unchanged and diffing
      pass/fail against this phase's pre-implementation baseline — zero
      regressions is the bar, not "mostly the same."
      **Re-verification finding (2026-09-11), cannot be closed as
      worded:** searched `tests/` and full git history for any
      pre-Phase-4 file exercising `_needs_scheme_clarification`,
      `_needs_topn_clarification`, `_needs_scope_clarification`,
      `_needs_year_clarification`, or `_needs_tranche_clarification` —
      none has ever existed in this repo (confirmed via `git log --all
      -- 'tests/*clarif*' 'tests/*pipeline*'`: only Phase 3's schema/join
      files were ever added that way). There is no pre-Phase-4 baseline
      suite to run or diff against. The closest real coverage is this
      phase's own `test_defaults_engine.py` task 1.4(b) — a colliding
      condition (`missing_top_n`) still triggers `_needs_topn_clarification`
      unchanged, no default emitted — which passes (9/9, see 1.5/2.6/3.5).
      **Decision (2026-09-11, product owner, this session):** `1.4(b)`
      accepted as satisfying this exit criterion's intent — no retroactive
      suite required. Closing on that basis.
- [x] 4.4 Record, in this file, the human decision on task 1.6 (which
      colliding conditions if any get flipped to silent-default) before
      this phase is considered closeable — an unresolved decision point
      is an open item, not a rounding error.
      **Resolved (2026-09-11):** see 1.6 above — zero flips, all 12
      conditions keep asking. Decision recorded there.
- [x] 4.5 Confirm via `git status`/`git diff` that `app/db.py`, `.env`, and
      the SQL execution/authorization path are untouched this phase.
      **Result (2026-09-11):** `git diff --stat -- app/db.py app/auth.py
      app/deps.py app/appdb.py` against HEAD (`a14ebf9`) is empty — zero
      diff on all four.
- [x] 4.6 Note in the completion report which frontend/API consumers were
      told about the new additive `findings`/`chart` response fields
      (proposal.md's Impact section) — this phase does not require their
      sign-off to ship, but they should not discover the fields by
      surprise.
      **Result (2026-09-11):** two in-repo consumers of `/api/query`
      exist — `web/ai_query.html` (already reads `response.chart_type`,
      per task 3.0) and `web/Meghalaya_UnifiedPortal_UI.html` (calls
      `/api/query` but does not reference `chart_type` or `findings` at
      all — additive fields are harmless to it either way). Confirmed
      (product owner, this session): both files share the same owner —
      no separate team to notify. Closed.
