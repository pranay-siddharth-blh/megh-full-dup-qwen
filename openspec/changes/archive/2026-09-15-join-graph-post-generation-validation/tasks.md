## 0. Foundation — verify before implementing (done, recorded here)

- [x] 0.1 Confirmed `sqlglot` is not currently a dependency (not in
      `requirements.txt`/`.lock`, not importable) and installs cleanly
      (30.18.0) — the environment has internet access for this.
- [x] 0.2 Prototyped the exact `find_invented_joins` approach against 4 real
      shapes before writing production code: (a) a valid star + chained
      dimension join (`fact_mgnrega_employment JOIN dim_geography JOIN
      dim_geography_alias`) — no false positive, and confirmed the second
      `JOIN`'s `ON` clause names `dim_geography`/`dim_geography_alias`, not
      the fact table, proving FROM-anchored attribution would be wrong;
      (b) the sanctioned CTE-to-CTE cross-scheme pattern from
      `schema_context.py` line 378 — correctly skipped, zero false
      positives, confirming a CTE reference parses as `exp.Table` with
      `db == ""` and needs no separate CTE-name tracking; (c) a real,
      currently-`is_prohibited` direct join (`v_focus_plus` to
      `fact_pmay_house`, no CTE) — correctly flagged; (d) a fully-qualified,
      unaliased join — correctly resolved, no false positive.
- [x] 0.3 Found and diagnosed the "known vs. has-edge" gap (see proposal.md
      Why): `curated.v_focus_plus` never becomes a `_graph` key at all today
      (all 6 of its declared edges are `is_prohibited: true`), which means a
      naive "not in `_graph`" check can't distinguish a reviewed-and-found-
      unrelated pair from a never-catalogued one — and the latter is a real
      live risk given `live_fks()` is best-effort and already empty this
      session. Resolved by tracking a separate `_known_nodes` set.

## 1. `app/join_graph.py` — known-nodes tracking + public helpers

- [x] 1.1 `build()` now populates `_known_nodes` from every `nodes:` entry
      (regardless of `readable_by_read_role`) and every `edges:` entry's
      `from_table`/`to_table` (regardless of `is_prohibited`) across all
      four YAMLs, plus every `schema_introspect.live_fks()` participant.
- [x] 1.2 Added `has_edge(a: str, b: str) -> bool` (calls `build()`, checks
      `_graph`) and `is_known(table: str) -> bool` (calls `build()`, checks
      `_known_nodes`). `snapshot()` also now reports `known_nodes` count.
- [x] 1.3 Deviation from spec wording: the is_known/has_edge distinction
      test landed in the new `tests/test_sql_join_validator.py` (section 1)
      instead of `tests/test_join_graph.py` — it's the foundation this new
      module depends on, so keeping it alongside the module's own tests
      reads better than splitting it into the older file. Confirmed:
      `is_known("curated.v_focus_plus") == True`,
      `has_edge("curated.v_focus_plus", "curated.fact_pmay_house") ==
      False`, `is_known("curated.totally_made_up_table_xyz") == False`,
      and a real declared FK pair has an edge — 4/4 pass.

## 2. `app/sql_join_validator.py` — the validator itself

- [x] 2.1 New module: `find_invented_joins(sql: str) -> list[tuple[str,
      str]]` — parses with `sqlglot` (dialect `postgres`, swallows parse
      errors as `[]`); per `SELECT` scope, builds an alias map from that
      scope's schema-qualified `exp.Table` nodes only; per `JOIN`, collects
      the real tables referenced by columns inside its `ON` clause; flags
      the pair only when exactly 2 distinct known tables resolve and
      `join_graph.has_edge()` says no.
- [x] 2.2 `tests/test_sql_join_validator.py` section 2: all 7 shapes as real
      assertions — valid chained dimension join (no false positive), the
      sanctioned CTE-to-CTE pattern (not flagged), the real prohibited
      direct join (flagged, exact pair confirmed), fully-qualified
      unaliased join (no false positive), a wholly unknown table (not
      flagged), a `CROSS JOIN` with no `ON` (not flagged), unparseable SQL
      (`[]`, no crash) — 7/7 pass.

## 3. Wire into `app/pipeline.py` + regression-audit existing fixtures

- [x] 3.1 One new call in `execute_with_repair` (`app/pipeline.py`,
      immediately before `_verify_sql`), alongside the existing free
      structural checks. A non-empty result raises `ValueError` naming the
      two tables, plus `join_graph.find_join_path()`'s suggested route
      (built from `.joins`, each hop's real `ON` clause — not `.tables`,
      which only echoes the two input table names with no intermediate
      hops; caught by hand-tracing a real 2-hop example before trusting it)
      when one exists. `except SQLAuthorizationDenied`/`except
      ClarificationNeeded` still `raise` unchanged; this falls into the
      existing generic repair-retry clause, same tier as the other
      structural checks.
- [x] 3.2 Audited every `initial_sql` fixture in `tests/test_pii_guard.py`
      (13 fixtures) and `tests/test_pipeline_join_discovery.py` (0 — that
      file never calls `execute_with_repair` at all, only `generate_sql()`)
      — confirmed: zero contain a `JOIN` at all, all single-table `SELECT`s.
      No fixture changes needed; confirmed by inspection, not assumed.
- [x] 3.3 `tests/test_sql_join_validator.py` section 3: an invented-join
      `initial_sql` triggers exactly one repair call and the repaired SQL
      (no invented join) is what executes and returns; a real declared-FK
      join executes on the first attempt with zero repairs — 3/3 pass.
      (Caught a bug in my own first draft of this test here: my hand-written
      "corrected" retry SQL for the first case still joined `v_focus_plus`
      directly to `dim_geography` — itself invented, since v_focus_plus has
      *no* legitimate join partner in this graph at all — so the validator
      correctly rejected my own fixture. Fixed the fixture, not the code.)

## 4. Dependency + regression + report

- [x] 4.1 Added `sqlglot>=30.18,<31.0` to `requirements.txt` and
      `sqlglot==30.18.0` to `requirements.lock` (alphabetical position,
      between `redis`/`requests` and `starlette`).
- [x] 4.2 Full regression sweep — all 12 files in `tests/` (excluding
      `smoke_restructure.py`, a manual/dev script): every file exits 0,
      zero `FAILED` markers. See conversation report for the full run.
- [x] 4.3 `git diff --stat` confirms `app/db.py`, `app/auth.py`,
      `app/deps.py`, `app/appdb.py` have zero diff. Touched set exactly
      matches proposal.md's Impact section: `app/join_graph.py` (modified),
      `app/sql_join_validator.py` (new), `app/pipeline.py` (modified,
      one call site + import), `requirements.txt`/`requirements.lock`
      (modified), `tests/test_sql_join_validator.py` (new).
- [x] 4.4 Reported back below — STOPPING here, no commit made. Awaiting
      confirmation.

## 5. Post-review fixes (2026-09-12, after keep-or-revert approval)

- [x] 5.1 Wrote the missing `specs/join-invention-detection/spec.md` delta
      (4 ADDED Requirements, 9 scenarios) — the change previously had no
      `specs/` directory at all. `openspec validate
      join-graph-post-generation-validation --strict` now passes (was
      failing: "Change must have at least one delta").
- [x] 5.2 Re-verification found the join validator ran *before* the §11.4
      PII checks in `execute_with_repair`, even though PII is an
      unconditional, non-repairable denial and the join check is a
      repairable one — a query violating both would waste the single
      repair attempt (and, if it also reached that far, the paid semantic
      verifier) on the join before being denied for PII anyway. Reordered:
      PII checks (`pii_guard.find_blocked_columns`/`find_container_exposure`,
      now `pipeline.py:2743-2768`) now run before the join validator
      (`pipeline.py:2769-2798`) and the paid verifier
      (`pipeline.py:2799-2808`). No data-exposure difference either way —
      nothing executes until every check passes regardless of order — this
      is a repair-budget/cost fix, not a security fix. Full regression
      sweep re-run after the change: all 12 `tests/` files exit 0.
- [x] 5.3 `docs/baseline-audit.md` §3 item 8 updated (append, original
      finding untouched) to record this backstop and its scope limit —
      still no pre-generation hard gate for the common single-required-
      table case, still carries forward to Phase 2 as originally stated.
