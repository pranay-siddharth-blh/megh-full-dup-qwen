## 1. Query-log FK miner

- [x] 1.1 Added `app/fk_miner.py`: `_extract_equalities(sql)` parses one
      SQL string with SQLGlot (`dialect="postgres"`, matching
      `app/db.py`/`app/sql_join_validator.py`'s existing convention),
      resolves per-SELECT-scope schema-qualified table aliases the same
      conservative way `sql_join_validator._alias_map` does, and yields
      `(table_a, col_a, table_b, col_b)` for every JOIN-ON equality
      between two distinct, resolved tables.
- [x] 1.2 `mine_implicit_fks(log_limit=5000, min_occurrences=2,
      schemes=None)`: reads `sql` from `app.query_audit` (`allowed = TRUE`,
      `sql IS NOT NULL`, optional `schemes && $n` filter, most recent
      `log_limit` rows) via `app.db.fetch_rows`, runs `_extract_equalities`
      over each row, drops any pair where `join_graph.is_known()` is
      False for either side or `join_graph.has_edge()` is already True,
      aggregates occurrence counts (canonicalized pair ordering so A-B
      and B-A merge), and returns `MinedFKCandidate` tuples
      (`from_table`, `from_column`, `to_table`, `to_column`,
      `occurrences`, `sample_sql`) with count >= `min_occurrences`,
      sorted by occurrence count descending.
- [x] 1.3 Best-effort like `join_graph.build()`: an `app.query_audit`
      read failure logs a warning and returns `[]`, never raises.
- [x] 1.4 Added `GET /admin/fk-mining` to `app/routers/admin.py`
      (`require_admin`, matching the existing GET-report style of
      `/admin/schema` and `/admin/audit`), with optional `scheme`,
      `min_occurrences`, `log_limit` query params, returning the
      candidate list as JSON (`{"count": ..., "candidates": [...]}`).

## 2. Tests

- [x] 2.1 New `tests/test_fk_miner.py` (standalone script, this repo's
      convention — no pytest): monkeypatches `db.fetch_rows` to return a
      fixed list of `{"sql": ...}` rows (no real DB dependency), against
      `join_graph`'s real state built from the actual curated YAMLs
      (`join_graph.build(force=True)`, same pattern as
      `tests/test_join_graph.py` — no need to fake `is_known`/`has_edge`
      since real known/unrelated/declared-edge table pairs already exist
      in the curated data). Covers: (a) a pair joined 3x with no declared
      edge (`curated.v_pmay` / `curated.fact_mgnrega_employment`) is
      surfaced with `occurrences == 3`; (b) a pair already `has_edge()`
      (`curated.fact_mgnrega_employment` / `curated.dim_geography`, a
      real declared FK) is never surfaced even joined 5x; (c) a second
      known-but-unrelated pair (`curated.v_cm_elevate` /
      `curated.v_focus_plus`) joined once is dropped at the default
      `min_occurrences=2` but surfaced at `min_occurrences=1`; (d) a
      CTE-to-CTE join contributes nothing; (e) a table unknown to
      `join_graph` (`curated.made_up_table_xyz`) is skipped, not guessed
      at; (f) a malformed SQL string is skipped without raising.
- [x] 2.2 Ran `python tests/test_fk_miner.py` — **8/8 PASS**.
- [x] 2.3 Re-ran `tests/test_join_graph.py` (3/3 PASS) and
      `tests/test_pipeline_join_discovery.py` (8/8 PASS) — unchanged, no
      regression (this change touches neither module — confirmed via
      `git diff --stat`, see 3.2).

## 3. Exit criteria

- [x] 3.1 All tests in group 2 pass.
- [x] 3.2 `git diff --stat -- app/routers/admin.py` shows exactly the
      import line + the one new route (18 insertions/1 deletion) —
      isolated from the pre-existing uncommitted diffs already sitting
      in `app/join_graph.py`/`app/pipeline.py`/`app/sql_join_validator.py`
      (untouched by this task group; see CLAUDE.md's mixed-concern-files
      note — those predate this session). `app/fk_miner.py` and
      `tests/test_fk_miner.py` are new, untracked files.
- [x] 3.3 No `foreign_key_augmentation.yaml` file and no line in
      `app/join_graph.py` changed by this task group — mining stays
      advisory-only, per proposal.md.
