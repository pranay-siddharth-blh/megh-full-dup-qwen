# Post-Generation Join Validation (SQLGlot)

## Status
Proposal — closes a gap between the PRD and the current implementation,
identified during a review of `app/join_graph.py` against
`GrantThornton_Solution_Proposal_1 (1).pdf` §5.9/§5.11, re-verified against
the live repo below (including hands-on prototyping with `sqlglot` against
this codebase's own real query shapes — not just reasoning about the PRD
text).

## Why

The PRD's join-discovery component (§5.9) says: "Return explicit ON clauses
the SQL generator must use, so the model cannot invent its own joins."
§5.11's SQL validator goes further: SQLGlot parses generated SQL to an AST
and enforces, among other rules, "joins must exist in the FK graph."

The current implementation (`app/join_graph.py` + `app/pipeline.py
::execute_with_repair`) does not do this. Its own design doc
(`openspec/changes/archive/2026-09-11-phase-3-schema-retrieval-join-discovery
/design.md`, "Join discovery gates SQL generation only where it has a
genuine pre-generation signal") is explicit about why: nothing in the
pipeline determines which tables a question needs *before* the generator
runs, so `find_join_path()` can only hard-gate in the narrow case where
`schema_retrieval` already named 2+ required tables — otherwise the graph's
output is folded into the prompt as a "REQUIRED JOIN(S)" hint, same
enforcement tier as the existing PROHIBITED JOINS text. In every other case
(the common one — most schemes have exactly one fact table each), a model
that ignores the hint and joins two unrelated tables is never caught. The
design doc calls the alternative "parsing the generator's *output* SQL" but
rejects it for lack of "a real SQL parser this codebase doesn't have," and
flags a specific risk: this codebase's own sanctioned cross-scheme pattern
("aggregate each side into a CTE, then join the CTEs" —
`app/schema_context.py` line 378, "aggregate v_focus_plus to village_code in
a CTE and FULL JOIN the aggregate") would look like an invented join to a
naive checker, since Focus Plus's fact has no FK-graph edge to a PMAY/MGNREGA
fact at all (that pairing is explicitly `is_prohibited: true` in
`focusplus_foreign_key_augmentation.yaml` for exactly this reason).

**This proposal closes that gap using `sqlglot`, scoped narrowly enough to
avoid the false positive the design doc predicted** — verified empirically,
not just argued:

- `sqlglot.parse_one()` correctly distinguishes a real, schema-qualified
  table reference (`curated.dim_geography`, `.db == "curated"`) from a bare
  CTE-name reference (`fp`, `.db == ""`) with zero extra bookkeeping — a CTE
  alias parses as an `exp.Table` with an empty `db`, so "only validate a
  join when both sides are schema-qualified" is sufficient to skip every
  CTE-to-CTE join without an explicit CTE-name allowlist.
- **The join's own `ON` clause — not FROM-clause position — decides which
  two tables a `JOIN` actually connects.** Prototyped against a real
  chained-dimension query (`fact_mgnrega_employment JOIN dim_geography g ON
  ... JOIN dim_geography_alias a ON a.geography_key = g.geography_key`):
  the second `JOIN`'s `ON` clause names `a` and `g`, not the fact table.
  Resolving table identity from the columns actually referenced inside each
  `ON` clause (via that `SELECT` scope's alias map) is the only correct way
  to determine a join's real endpoints; anchoring to "whatever is in the
  `FROM` clause" would misattribute chained/snowflake joins and produce
  false positives or false negatives depending on join order.
- Verified against 4 representative real shapes (see task 0.2): a valid
  star + chained-dimension join, the sanctioned CTE-to-CTE cross-scheme
  pattern, a real prohibited direct join (`v_focus_plus` to
  `fact_pmay_house`, no CTE), and a fully-qualified unaliased join. All four
  behaved correctly: the CTE pattern was silently skipped, the direct
  prohibited join was flagged, the other two passed clean.

**A second risk found during verification, not in the original ask:**
`join_graph._graph` only contains a node once it has at least one
*non-prohibited* edge — `curated.v_focus_plus` has six declared edges in its
YAML and every one is `is_prohibited: true`, so it never becomes a `_graph`
key at all today. A validator that only checks "is this pair in `_graph`"
can't distinguish "these two tables were reviewed by an SME and found to
have no relationship" (what we want to catch) from "this table was never
catalogued at all" (a live-only FK the YAML doesn't know about, or a future
scheme with no YAML yet) — and the latter is a real, live failure mode
today: `app/db.py`'s own docstring notes the DB host "flaps," and
`join_graph.build()`'s only source of live-only edges
(`schema_introspect.live_fks()`) is best-effort and empty whenever that
happens (as it is in this very session). Treating "not in `_graph`" as
"invented" would make a transient DB hiccup at startup newly capable of
rejecting a *previously working* query that only ever depended on a
live-only FK — a resilience regression this codebase doesn't have today
(right now a missing live edge only weakens a prompt hint, never blocks
execution). The fix: track a broader "known to the graph" set — every table
named in *any* YAML `nodes:` entry or `edges:` entry (prohibited or not)
plus every `live_fks()` participant — separately from "has a live edge."
The validator only flags a pair when **both** sides are known and **no**
edge connects them; an unknown table on either side is left unvalidated,
not waved through as safe and not rejected as invented.

## What Changes

- **`app/join_graph.py`**: `build()` additionally populates a
  `_known_nodes: set[str]` from every `nodes:`/`edges:` entry in all four
  YAMLs (regardless of `is_prohibited`) plus every `live_fks()` participant.
  New public helpers: `has_edge(a, b) -> bool` and `is_known(table) -> bool`.
  No change to existing behavior of `find_join_path()` or the pre-generation
  hint path.
- **New `app/sql_join_validator.py`**: `find_invented_joins(sql) ->
  list[tuple[str, str]]`. Parses `sql` with `sqlglot` (dialect `postgres`);
  for each `SELECT` scope, for each `JOIN`, resolves the real table pair
  referenced by that join's own `ON` clause (via that scope's alias map);
  flags the pair only when both are `join_graph.is_known()` and
  `join_graph.has_edge()` says no. Silently returns `[]` on a parse failure
  (defers to whatever other check already handles malformed SQL) or when a
  join's `ON` clause can't be cleanly resolved to exactly two known tables
  (e.g. a multi-column composite condition mixing three-plus table
  references, a `USING` join, a `CROSS JOIN`) — conservative by design, per
  the same "additive signal only where it has genuine confidence" tier
  `join_graph.py`'s own docstring commits to for its existing checks.
- **`app/pipeline.py::execute_with_repair`**: one new call, alongside the
  existing free (non-model) structural checks, before the paid
  `_verify_sql` call. A non-empty result raises `ValueError` — a
  *repairable* error, same tier as `_village_name_filter_instead_of_code`
  etc., not `ClarificationNeeded` — naming the two tables and, when
  `join_graph.find_join_path()` can find a real route between them, the
  correct path to use instead.
- **`requirements.txt`/`requirements.lock`**: add `sqlglot` (new
  dependency; `>=30.18,<31.0` / pinned `==30.18.0`).

## Explicitly Out of Scope

- **Does not replace `annotations.prohibited_joins_text()`.** That
  mechanism encodes *why* a specific pairing is unsafe even when a technical
  path might exist (grain mismatch, unit mismatch) — a business judgment,
  not a graph-connectivity fact. This validator only asks "does any declared
  relationship connect these two tables at all," which is a strict subset:
  every currently-prohibited pair in the YAMLs already has zero non-
  prohibited edges, so this validator happens to also catch them if the
  model bypasses the prompt instruction directly (a welcome overlap, not the
  design goal), but the prompt-level mechanism remains the source of truth
  for *why*.
- **No column-level ON-clause correctness check** (e.g. "the graph's
  canonical `on_clause` uses `geography_key`, but the generated SQL joined
  on `village_code` instead" — right tables, arguably wrong or just
  different columns). Scoped to catching a join between two tables with *no
  declared relationship at all* — the concrete "invents its own joins" risk
  the PRD names. A stricter column-match check is a plausible fast-follow,
  not attempted here.
- **No change to the pre-generation hint tier** (`find_join_path()`'s
  narrow 2+-required-tables hard gate, or the additive prompt hint
  otherwise) — this is a new, independent, always-on post-generation check,
  additive to what exists.

## Impact

- Files: `app/join_graph.py` (extended), `app/sql_join_validator.py` (new),
  `app/pipeline.py` (one new call site in `execute_with_repair`),
  `requirements.txt`/`requirements.lock` (new dependency), `tests/` (new
  `test_sql_join_validator.py`; existing join/pipeline test fixtures
  audited for false-positive risk from the new gate, per task 3).
- `app/db.py`, `.env`, connection/role handling: untouched.
- Rollback: the new call site in `execute_with_repair` is one line to
  remove; `app/join_graph.py`'s additions are additive (new functions, no
  changed signatures); `app/sql_join_validator.py` is a new, independent
  file.
