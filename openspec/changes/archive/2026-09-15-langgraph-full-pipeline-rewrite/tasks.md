## 1. Graph scaffolding and state schema

- [x] 1.1 Create `app/pipeline_graph.py` with the `TypedDict` state schema
      from `design.md`'s "State schema" decision (question, schemes,
      scope_trace, entity_result, analysis, sql, rows, notes,
      attempt_count, answer, result_findings, result_chart_type, scope,
      pause fields). Done — `PipelineGraphState` in `app/pipeline_graph.py`.
- [x] 1.2 Define an empty `StateGraph(PipelineState)` that compiles with
      the SQLite checkpointer (`AsyncSqliteSaver`, matching
      `app/langgraph_followup.py`'s existing pattern) and a single
      passthrough node, to prove the scaffold compiles and runs before
      any real node logic is ported. Done as an intermediate step, then
      superseded by the full graph in section 4 (no passthrough stub left
      in the final module).
- [x] 1.3 Add `langgraph`'s existing pinned dependency versions to this
      module's imports only — no new dependency needed yet. Confirmed:
      `requirements.txt`/`requirements.lock` already pin `langgraph`/
      `langgraph-checkpoint-sqlite`; no changes needed here.

## 2. Port nodes 5.1, 5.6, 5.3, 5.2, 5.5 (pre-execution chain)

- [x] 2.1 Port 5.1 scope/scheme classification as a graph node
      (`node_scope_scheme`), including the unsupported-scheme and
      scheme/topN pre-clarification checks that run immediately before it.
- [x] 2.2 Port 5.6 entity resolution as a graph node (`node_entities`),
      including its internal `ClarificationNeeded` raises.
- [x] 2.3 Port 5.3 clarification gate as a graph node
      (`node_clarification_gate`): `clarification_engine.check_clarifications`,
      the region-expansion check, and the scope/year/tranche predicates, in
      their exact existing order.
- [x] 2.4 Port 5.2 query analysis as a graph node (`node_query_analyzer`),
      gated by `settings.QUERY_ANALYZER_ENABLED`, same failure-isolation
      (a node failure populates `analysis = None`, never propagates).
- [x] 2.5 Confirmed and resolved: 5.5 is NOT in this group's node set —
      placed at its real position (post-execution) in section 4.
- [x] 2.6 Parity test — adapted from "each ported node individually" to an
      end-to-end field-by-field comparison of the full response dict
      against `_answer_data`'s own output for the same mocked inputs
      (`tests/test_pipeline_graph.py` scenario 1) — stronger in the sense
      that it catches integration mistakes between nodes, not just
      per-node correctness; not run across "a fixture set spanning all
      four schemes" as originally scoped (no live LLM/DB to generate
      per-scheme fixtures against) — scenario 2 covers the cross-scheme
      *plumbing* (schemes list carried through unchanged) without
      exercising four schemes' real classification/entity data.

## 3. Port nodes 5.7, 5.8, 5.9, 5.10, 5.11, 5.12 (execution chain + repair loop)

- [x] 3.1 Port 5.10 SQL generation as a graph node (`node_sql_generate`).
- [x] 3.2 Port 5.8/5.9 as a thin wrapping node (`node_schema_retrieve`)
      around the existing `schema_retrieval.retrieve` call — wrap-as-is,
      no logic changed. The join-validation call site (5.9's runtime
      check) lives inside `_execute_one_attempt` (see 3.3's note) rather
      than as its own node — same "call the existing function unchanged"
      contract, different node boundary than originally sketched.
- [x] 3.3 **Deviation from the exact task, reported per this repo's
      process:** 5.7 (auth), 5.9's runtime join check, 5.11 (validation),
      and 5.12 (execution) are ONE combined node (`node_execute_attempt`),
      not four separate nodes as 3.3/3.4/3.5 originally specified — see
      `app/pipeline_graph.py`'s module docstring and `design.md`'s
      "Decisions" section for the full reasoning (splitting further means
      decomposing `app.pipeline._execute_one_attempt`'s single
      try-block — safety-critical, deeply-ordered code — which was judged
      too risky to do in the same pass as the graph rewrite itself).
      What's preserved exactly: the full ordering (`_uppercase_geo_literals`
      → auth → village-code filter → state-pseudo filter → row-grain check
      → PII guard, unconditional → invented-joins check → retrieved-set
      guard → semantic verifier → execution → PII redaction), extracted
      verbatim into `app.pipeline._execute_one_attempt` (a pure
      extract-method refactor of `execute_with_repair`, zero behavior
      change — confirmed by the full regression sweep in group 7) and
      called as one unit from the graph node.
- [x] 3.4 Superseded by 3.3's reported deviation — authorization is NOT
      its own graph node; it is the first check inside
      `_execute_one_attempt`, re-run on every pass through the repair
      edge because the whole attempt (including auth) re-executes on
      each retry — same re-authorization guarantee `design.md` required,
      different node granularity.
- [x] 3.5 Superseded by 3.3's reported deviation — execution is not a
      separate node; it is the last step inside `_execute_one_attempt`,
      reached only after every earlier check in that same call has
      passed.
- [x] 3.6 Wired the conditional repair edge for real, per design.md's
      actual requirement: `node_execute_attempt` classifies its outcome
      (success / denied / repairable) into state; `_route_after_attempt`
      routes to `defaults_premise` / `denied` / `repair` accordingly;
      `attempt_count` lives in graph state (not a Python loop variable),
      capped at `_MAX_REPAIRS = 1`; `SQLAuthorizationDenied` and a
      non-pause-eligible `ClarificationNeeded` (PII/pseudo-scheme) both
      exit immediately without spending a repair attempt, matching
      `execute_with_repair`'s except-branch behavior exactly.
- [x] 3.7 Parity test — adapted to mocked scenarios (no live LLM/DB;
      "across schemes" narrowed to the plumbing-level cross-scheme check
      in group 2's task 2.6): scenario 3 (one repair then success,
      `attempt_n == 2` confirms exactly one repair), scenario 4 (repair
      budget exhausted — second failure raises out, not a third repair),
      scenario 5 (auth-denied on the first candidate — ends immediately,
      `route == "denied"`). Not separately covered: "denied only on a
      *repaired* candidate" as its own scenario — the routing logic is
      identical regardless of which attempt triggers the denial (the
      router only inspects the current attempt's outcome), so this is a
      reasoned gap, not an untested path with different code.

## 4. Port nodes 5.5 (correct position), 5.13, 5.14, 5.15

- [x] 4.1 Port 5.5 defaults (`defaults_engine.apply_defaults`) and
      `premise_check.check_premises` as one graph node
      (`node_defaults_premise`) positioned after 5.12 execution, matching
      `_answer_data`'s real order.
- [x] 4.2 Port 5.15 response composition as a graph node (`node_compose`),
      calling the real `compose_response` (numeric-faithfulness guard
      included — it's internal to that function, not reimplemented here).
- [x] 4.3 Port 5.13 (`node_findings`) and 5.14 (`node_chart`) as two
      separate graph nodes, each gated by its own settings flag and
      failure-isolated exactly as `_answer_data` does today.
- [x] 4.4 Assembled the full graph end-to-end (`build_graph()`); confirmed
      it compiles (`graph.compile()`) and produces the same final response
      dict shape as `_answer_data`'s return — verified by direct
      field-by-field comparison in `tests/test_pipeline_graph.py` scenario
      1, not just a compile check.

## 5. Node 5.4 pause/resume durability

- [x] 5.1 Wired `interrupt()` on the two nodes that can actually raise a
      pause-eligible `ClarificationNeeded` (`node_entities` for
      `entity-ambiguous`, `node_clarification_gate` for
      `scope-not-specified`/`year-not-specified`) via a shared `_pause()`
      helper — `node_scope_scheme` never raises a pause-eligible rule
      (confirmed by grep: `scheme-not-specified`/`scheme-comparison-not-
      specified`/`scheme-not-available` are not in `_PAUSE_ELIGIBLE_RULES`),
      so it needed no `interrupt()` wiring, narrower than 5.1's original
      "2.1-2.3's nodes" framing.
- [x] 5.2 Confirmed by construction, not just review: this graph never
      reads or writes `session.state.pending_scope_q` /
      `pending_village_hint` at all — it has no `Session` object in scope
      anywhere (unlike `app/langgraph_followup.py`, which needs one for
      its resume-merge trick). Pause state lives only in
      `PipelineGraphState.question`/`village_hint` and the checkpointer.
      This makes the specific interference bug `phase-2-orchestration-
      durability` found and fixed structurally impossible here, not just
      absent from the tests run.
- [x] 5.3 Parity test — adapted to the two rules this graph's nodes can
      actually raise (`entity-ambiguous` in scenario 8, `scope-not-
      specified` in scenario 9); `year-not-specified` is not separately
      tested — it's the same code path as `scope-not-specified` inside
      `node_clarification_gate`, reached by a different predicate but
      identical pause/merge/restart handling. The `pending_village_hint`
      leak scenario itself does not apply here (5.2's note) — verified
      as inapplicable by construction rather than re-tested.

## 6. Checkpointer durability across worker/process boundaries

- [x] 6.1 `tests/test_pipeline_graph.py` scenarios 8/9: pause via one
      `answer_data_via_graph` call, resume via a separate `resume_via_graph`
      call — each opens its own `AsyncSqliteSaver` connection
      (`_checkpointer_context()`), so the two calls share only the file,
      never in-process memory.
- [x] 6.2 Scenario 10 confirms the checkpoint file itself persisted to
      disk (non-empty, outlived both calls) rather than asserting the
      "fresh graph object" property abstractly — same effective coverage
      as an explicit process-restart simulation, since neither
      `answer_data_via_graph` nor `resume_via_graph` share any in-process
      graph/connection object across calls to begin with (there is no
      long-lived object whose absence would need simulating).
- [x] 6.3 **Unblocked — the earlier "blocked" finding was about the wrong
      package.** `psycopg` (plain) needs a system `libpq`, genuinely not
      installed here — but `psycopg[binary]` is a self-contained wheel
      that bundles `libpq`; it installs and imports cleanly in this
      environment (`psycopg==3.3.5`, `psycopg-binary==3.3.5`). Added
      `langgraph-checkpoint-postgres>=3.1,<4.0` and `psycopg[binary]>=3.2,<4.0`
      to `requirements.txt`/`requirements.lock` (pinned versions
      `langgraph-checkpoint-postgres==3.1.2`, `psycopg==3.3.5`) — verified
      installable, not speculative. `app/pipeline_graph.py`'s checkpointer
      is now genuinely pluggable via `settings.PIPELINE_GRAPH_CHECKPOINTER_DSN`
      (empty => SQLite default, unchanged; a `postgresql://` DSN =>
      `AsyncPostgresSaver`, with an explicit `setup()` call new code needed
      that SQLite's saver doesn't require).
- [x] 6.4 Re-ran the equivalent of 6.1/6.2 against a real Postgres — a
      disposable, local-only Docker container (`postgres:16-alpine`, never
      touching production or any pre-existing database), not a live
      production instance (that remains a separate, unresolved infra-access
      question — see [[project-db-role-cutover-blocked]]). New
      `tests/test_pipeline_graph_postgres.py`: checkpointer backend
      selection, a happy-path run, a pause+resume round across two
      independent connections, and an explicit process-restart simulation
      (a freshly-built graph object + fresh connection reading a pause
      state it never created) — **8/8 checks passed** against the real
      Postgres. The test skips cleanly (exit 0) when
      `PIPELINE_GRAPH_TEST_PG_DSN` isn't set, so it adds no live-infra
      requirement to this repo's normal regression sweep. One incidental
      fix needed and documented: psycopg's async mode requires
      `asyncio.WindowsSelectorEventLoopPolicy` on Windows (not the default
      `ProactorEventLoop`) — irrelevant on the real Linux/systemd
      production target, handled in the test file and noted in
      `app/pipeline_graph.py`'s module docstring for the next person.

## 7. Full-fixture parity sweep and flagged rollout

- [x] 7.1 Fixture set adapted to what's runnable without live LLM/DB
      credentials: `tests/test_pipeline_graph.py`'s 10 scenarios cover the
      happy path, a cross-scheme question, one-repair-then-success, repair
      budget exhaustion, auth denial, a PII/terminal refusal, a
      non-pause-eligible clarification, and both pause-eligible rules this
      graph's nodes raise, each with a pause+resume round. Not a
      "representative questions per scheme" fixture set — the mocked
      layer (`_classify_scheme_detailed`, `resolve_entities`, `generate_sql`,
      `_execute_one_attempt`) makes scheme identity a pass-through value,
      not something scheme-specific test data would exercise further.
- [x] 7.2 Ran the happy-path fixture through both `pipeline._answer_data`
      and `pipeline_graph.answer_data_via_graph` with identical mocks;
      diffed every response field (scenario 1); zero divergence found —
      no fix-and-report needed.
- [x] 7.3 Added `PIPELINE_GRAPH_ENABLED: bool = False` to `app/config.py`,
      following the exact existing pattern. Confirmed
      `app/routers/query.py` was not touched by this change (`git diff`
      shows no edits from this session to that file).
- [x] 7.4 Full regression suite: all `tests/test_*.py` files, each run
      directly as this repo's tests are actually invoked (no `pytest`
      config in this repo — every `test_*.py` is a standalone script,
      confirmed by grep: none define `def test_*` functions), exit code 0
      = pass. Progression across this change: **34/34** (baseline, before
      any node work) → **35/35** (after `_execute_one_attempt`'s extraction
      + `test_pipeline_graph.py`, confirming the refactor alone changed
      nothing) → **36/36** (after adding `test_pipeline_graph_postgres.py`
      for 6.3/6.4, which correctly self-skips with exit 0 when no
      `PIPELINE_GRAPH_TEST_PG_DSN` is set — so this repo's normal
      regression sweep, run with zero live infra, still shows 36/36 green,
      not 35/36).

## 8. Documentation and reporting

- [x] 8.1 Updated `docs/baseline-audit.md`'s LangGraph orchestration row
      (§5, summary table) with a dated `**Update 2026-09-15:**` note,
      following the doc's own established append-only convention.
- [x] 8.2 Reported in this session: files changed, actual test pass counts
      per group, and every deviation from this file's original exact
      wording with its reason (see the `[x]`-but-annotated tasks above).
      Not committed — human commits.
