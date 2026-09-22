## 1. Scope decision trace (`response.scope`)

- [x] 1.1 In `app/pipeline.py`, extract `classify_scheme`'s body into
      `_classify_scheme_detailed(question) -> tuple[list[str], ScopeMeta]`
      (a small dataclass: `confidence: float`, `source: Literal["llm",
      "shortcut", "fallback"]`, `reason: str`), setting `ScopeMeta` at each of
      the function's existing early-return points (named-scheme shortcut,
      fuzzy match, term inference, LLM call). `classify_scheme` becomes a
      one-line wrapper calling it and returning only `schemes`.
- [x] 1.2 Add an `is_followup: bool = False` parameter to `_answer_data`;
      update its one call site in `_run_pipeline` to pass the existing
      `is_followup_rewrite` local.
- [x] 1.3 In `_answer_data`, call `_classify_scheme_detailed` instead of
      `classify_scheme`, and build the `scope` dict (`schemes`, `confidence`,
      `source`, `reason`, `is_followup`, `in_scope: True`) — attached directly
      to the final response here rather than deferred to group 3, since it's
      the same cohesive unit of work as building it.
- [x] 1.4 Add `tests/test_scope_decision_trace.py` covering: shortcut path
      reports `source="shortcut"`; LLM path reports `source="llm"` with a
      non-empty `reason`; fallback path reports `source="fallback"`;
      `confidence` is always in `[0.0, 1.0]`; `classify_scheme`'s own contract
      (bare `list[str]`) is unchanged. 18/18 passing.
- [x] 1.5 Ran `tests/test_scope_scheme_classifier.py` unmodified — all 24
      existing checks still pass, confirming the refactor in 1.1 changed no
      observable behavior.

## 2. Query analyzer module (`response.analysis`)

- [x] 2.1 Create `app/query_analyzer.py` with a `QueryAnalysis` shape matching
      `web/ai_query.html`'s existing renderer exactly: `query_type`, `metric`,
      `entities` (buckets: `districts`, `regions`, `blocks`, `villages`,
      `banks`, `verticals`, `ids`, `persons`), `time_scope`, `granularity`,
      `limit`, `ambiguous` (list of `{term, kind, why}`), `intent_summary`.
- [x] 2.2 Implement deterministic `query_type` fast-path — local copies of
      `_RANKING_CUE`/`_EXPLICIT_COUNT` (→ `ranking`, with `limit` from the
      matched count) plus new comparison/trend/distribution/filter_list/
      aggregation cue regexes (leaf-module convention: no import back into
      `app/pipeline.py`, matching `app/findings.py`'s documented stance).
- [x] 2.3 Implement the guided-JSON LLM call (schema: `query_type` enum of
      the 7 proposal values as a fallback, `metric`, `time_scope`,
      `intent_summary`, `ambiguous_terms` array of `{term, kind, why}`) using
      the existing `llm.call_classifier(..., guided={"guided_json": ...})`
      idiom — always called (metric/intent_summary have no deterministic
      source), with `query_type`/`time_scope` overridden by the deterministic
      values above when those are confident.
- [x] 2.4 Implement deterministic `entities`/`granularity`/`limit` assembly
      from `entity_result["resolved"]`/`["display"]` — no model call. Maps
      district/block/village/district_list/district_list_region/
      assembly_constituency into the frontend's bucket names; derives
      `granularity` as village > block > district(s)/region > state.
- [x] 2.5 Implement `ambiguous` assembly from `entity_result["notes"]`
      (not-found mentions, parsed via the `'<term>' is not a known <kind>`
      phrasing every such note uses) merged with the LLM call's own
      `ambiguous_terms`.
- [x] 2.6 Wrapped the whole function in try/except, logs and returns `None`
      on any failure or exception — matches the `findings`/`chart_spec`
      isolation pattern in `_answer_data`.
- [x] 2.7 Added `tests/test_query_analyzer.py`: ranking/comparison fast-paths,
      LLM fallback for query_type/time_scope, resolved-year precedence over
      the model's time_scope guess, not-found-note → ambiguous entry,
      model-call exception → `None` (no raise), unusable model output still
      returns a graceful object. 21/21 passing.

## 3. Wire into the live request path

- [x] 3.1 In `_answer_data`, call `query_analyzer.analyze_query(question,
      schemes, entity_result)` immediately before `generate_sql` (gated by
      new `settings.QUERY_ANALYZER_ENABLED`, default `True`), and attach the
      result as `result["analysis"]` in the function's final return dict.
- [x] 3.2 (Superseded by 1.3 — `scope` was attached there as part of the same
      cohesive change rather than deferred.)
- [x] 3.3 Added `tests/test_query_analyzer_integration.py`: a full
      `_answer_data` run (every sub-step monkeypatched at the module-attribute
      level — `_classify_scheme_detailed`, `resolve_entities`, `generate_sql`,
      `execute_with_repair`, `compose_response`, `query_analyzer`) confirming
      `analysis` and `scope` both land in the final response with the right
      shape, `is_followup` threads through correctly, and a query-analyzer
      failure degrades to `analysis: None` without breaking the answer.
      11/11 passing.

## 4. Audit trail

- [x] 4.1 Re-verified design.md's assumption before implementing (per this
      project's "re-verify claims" convention) — `findings`/`chart_type`
      were NOT added to a JSON blob as design.md originally assumed; they are
      dedicated `app.query_audit` columns added via `app/appdb.py`'s
      self-managed, idempotent `_DDL` (`ALTER TABLE ... ADD COLUMN IF NOT
      EXISTS`, applied automatically on app startup — not a manual
      `deploy/sql/` migration requiring a maintenance window, unlike the
      unrelated `megh_app` role cutover). Corrected course to match: added
      `analysis JSONB`/`scope JSONB` to `app.query_audit` via the same `_DDL`
      mechanism (`app/appdb.py`), wired into `conversation_store._persist_turn`'s
      INSERT (columns inserted before `findings/chart_type/answer` rather than
      appended, to avoid shifting the existing test's positional param
      assertions — a real regression caught and fixed during this task), and
      into `app/routers/query.py::_mirror_audit`'s JSONL mirror. Also added to
      `conversation_turns.response`'s existing JSON blob (no migration) so a
      reopened thread can redraw the same badge.
- [x] 4.2 Added `tests/test_query_analyzer_audit_trail.py` (DDL declares the
      two columns; INSERT carries them structurally — by column-name lookup,
      not a brittle fixed index — confirming the reorder didn't break
      findings/chart_type/answer; absent-case binds explicit NULL; JSONL
      mirror carries both in parity). 11/11 passing. Re-ran
      `tests/test_query_audit_trail.py` (17/17) and `tests/test_pii_audit_trail.py`
      /`tests/test_pii_guard.py` unmodified as the regression gate for the
      INSERT reorder — all still pass.

## 5. Frontend

- [x] 5.1 In `web/ai_query.html`, set `SHOW_ROUTE_BADGE = true` and corrected
      the adjacent comment to describe what actually changed.
- [x] 5.2 No live DB/model gateway is reachable in this environment (same
      constraint documented throughout `docs/baseline-audit.md`), so a live
      browser click-through isn't possible here. Instead: extracted
      `buildRouteBadge`/`escapeHTML` verbatim from `web/ai_query.html` into a
      standalone Node harness and fed it mock responses shaped exactly like
      what `app/pipeline.py`/`app/query_analyzer.py` now produce. Confirmed:
      scheme/query-type/confidence/source chips render correctly, the
      expandable reason panel includes intent summary, metric, granularity +
      limit, entity chips, time scope, and ambiguous-term "gap" chips with
      correct tooltips; `in_scope: false` and a missing `scope` key both
      correctly render nothing (no dead badge on KNOWLEDGE/EDGE/out-of-scope
      turns). 12/12 checks passed. A real browser click-through against a
      live deployment is still recommended before this is called fully done
      operationally — flagged here, not silently skipped.

- [x] 6.1 Ran the full `tests/` suite (28 files). 26/28 pass, including every
      file this change touches or could plausibly affect (`test_scope_scheme_
      classifier.py`, `test_intent_classifier.py`, `test_entity_resolver.py`,
      `test_clarification_gate.py`, `test_clarification_engine.py`,
      `test_authorization.py`, `test_pii_guard.py`, `test_pii_audit_trail.py`,
      `test_query_audit_trail.py`, `test_sql_safety.py`, and all four new
      test files). The 2 non-passing files are pre-existing environmental
      gaps unrelated to this change's diff: `smoke_restructure.py` requires a
      live server on localhost (none running in this environment) and
      `test_langgraph_followup.py` requires the optional `langgraph` package
      (not installed here) — neither touches `app/pipeline.py`,
      `app/query_analyzer.py`, `app/conversation_store.py`, `app/appdb.py`,
      `app/config.py`, `app/routers/query.py`, or `web/ai_query.html`, the
      only files this change modified.
- [x] 6.2 Updated `docs/baseline-audit.md` §5.2's row (see below) to reflect
      that a real structured analyzer object now exists, is wired into the
      live DATA path, and is visible end to end via `web/ai_query.html`'s
      previously-dead badge — while explicitly noting the deferred scope
      (the ~10 clarification predicates don't read its output yet) so the
      row isn't overstated.
