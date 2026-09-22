## Why

The user asked to "implement §5.9 end to end," pointing at the original
Grant Thornton proposal text for join discovery: NetworkX for the graph,
SQLAlchemy to introspect `information_schema`, and "SQLGlot to
optionally mine implicit FKs from existing query logs."

Re-verified against the actual codebase before scoping this (per the
repo's re-verify-before-implementing rule), then confirmed scope
directly with the user rather than guessing:

- **Graph build, shortest-path join discovery, the fan-out guard, and
  pipeline gating are already implemented, tested, and committed** —
  `app/join_graph.py`, wired into `app/pipeline.py`, archived at
  `openspec/changes/archive/2026-09-11-phase-3-schema-retrieval-join-discovery/`,
  documented at `openspec/specs/join-discovery/spec.md`. Both
  `tests/test_join_graph.py` and `tests/test_pipeline_join_discovery.py`
  pass today (re-ran them this session).
- **Two named tools were deliberately swapped for ones already in the
  codebase, per `design.md`:** NetworkX -> a plain BFS over a
  `dict[str, dict[str, str]]` adjacency list (every scheme's graph is
  under ~20 nodes — NetworkX's weighted/multigraph machinery buys
  nothing at this size), and SQLAlchemy -> the existing `asyncpg` pool
  in `app/db.py` (already the app's only DB access layer; introducing a
  second one just for introspection queries would be a redundant
  dependency). User confirmed keeping BFS (not revisiting the NetworkX
  swap) when asked directly.
- **The one genuinely unbuilt piece is the query-log FK-mining leg** —
  the proposal calls it optional, and today the implicit-FK role is
  covered entirely by each scheme's SME-reviewed
  `foreign_key_augmentation.yaml` (see `app/join_graph.py`'s module
  docstring: Focus Plus's `declared: inferred` edges are exactly this,
  authored by hand from column-naming convention, not mined). This
  change adds the mining tool itself, confirmed in scope by the user.
- **Query logs already exist to mine from**: `app.query_audit.sql`
  (phase-2 audit-trail enrichment) durably records every executed,
  allowed query's SQL text — real historical evidence, not a
  hypothetical log source that would need building first.
- **`app/sql_join_validator.py` already does almost the exact
  extraction this needs**, just for a different purpose: its
  `find_invented_joins()` parses one query's SQL with SQLGlot,
  resolves per-SELECT-scope schema-qualified table aliases, and flags
  JOIN-ON pairs that are `is_known()` on both sides but have no
  `has_edge()` between them — i.e. exactly the "known tables, joined in
  real SQL, no declared relationship" signal an implicit-FK miner needs,
  just discarding the join columns (it only needs table identity to
  flag a single query) and never aggregating across queries. The new
  miner mirrors this same conservative resolution (schema-qualified only,
  skip CTE-to-CTE and USING/CROSS/natural joins, skip anything an
  alias doesn't resolve cleanly) but keeps the join *columns* and
  aggregates occurrence counts across many historical queries instead of
  flagging one query in isolation.

## What Changes

- Add `app/fk_miner.py`: `mine_implicit_fks(log_limit=5000,
  min_occurrences=2, schemes=None)` — reads recent `allowed = TRUE` rows
  from `app.query_audit`, extracts every JOIN-ON column-equality that
  resolves to two schema-qualified tables `join_graph` already knows
  about (curated YAML or `live_fks()`) but has no edge between, and
  returns candidates seen at least `min_occurrences` times, most
  frequent first, each carrying a sample SQL string for review context.
- Add `GET /admin/fk-mining` (admin-only, matches `admin.py`'s existing
  GET-report pattern like `/admin/schema` and `/admin/audit`) —
  runs the miner on demand and returns the candidate list as JSON.
  Read-only; no request body, no state mutation.
- **This tool never writes to the live join graph or to any
  `foreign_key_augmentation.yaml` file.** Every candidate is a report
  for a human SME to review and, if they agree, add to the relevant
  scheme's curated YAML by hand — the same "reviewed by a SME" gate
  `app/join_graph.py`'s own module docstring already requires for any
  implicit (non-FK-constraint) edge, and the same reasoning
  `join-discovery`'s spec gives for why join paths come only from
  declared-or-curated edges, never an invented one. Auto-merging a
  query-log pattern straight into the graph would reintroduce exactly
  the risk this capability exists to prevent.

## Capabilities

### Modified Capabilities
- `join-discovery`: adds the query-log mining tool as an offline/
  admin-triggered advisory report feeding the existing SME-curation
  process (spec delta below) — no change to how the live graph is built
  or how join paths are computed/gated.

## Impact

- Affected files: `app/fk_miner.py` (new), `app/routers/admin.py`
  (`GET /admin/fk-mining`), `tests/test_fk_miner.py` (new).
- No change to `app/join_graph.py`, `app/pipeline.py`,
  `app/sql_join_validator.py`, or any `foreign_key_augmentation.yaml` —
  this is a new, additive, read-only reporting tool alongside them, not
  a change to the live join-discovery path.
- No new dependency: `sqlglot` is already in `requirements.txt` (used by
  `app/db.py` and `app/sql_join_validator.py`).
- Reads `app.query_audit` (existing table) — adds query load, bounded by
  `log_limit` (default 5000 rows), triggered only when an admin calls
  the new endpoint, never on a hot path.
