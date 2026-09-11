## Why

Phase 0's baseline audit flagged two pipeline nodes as missing outright:
§5.8 (schema retrieval) and §5.9 (join discovery). Before scoping the
work, this proposal was checked against the actual running code (not
re-derived from the audit's summary alone), because both gaps turned out
to be narrower than the audit's framing suggested:

- **§5.8 is not a total absence of schema scoping.** `app/schema_introspect.py`
  already reads live `information_schema` columns/FKs from `megh_db` at
  startup; `app/schema_context.py` is a ~900-line hand-curated,
  per-scheme prompt backbone (tables, hazard rules, business vocabulary),
  selected deterministically by the classifier's scheme output
  (`app/prompt_builder.py`). There is genuinely no *semantic/fuzzy*
  retrieval layer — nothing embeds the question and ranks candidate
  tables/columns by similarity — but there are also only **4 schemes**
  in this codebase today (MGNREGA, PMAY-G, Focus Plus, CM Elevate), not
  the 25 an earlier scope reference implied. At 4 schemes, deterministic
  classification into a hand-tuned block does not hit the "stuffing
  schema into a prompt" failure mode §2.2 warns about. The real gap is
  narrower: fuzzy phrasing or column-level pivots that the classifier
  and the hand-written blocks don't cleanly cover, and headroom for
  scheme count to grow well past 4.
- **§5.9 is not "the generator is free to invent joins."** Real FK
  constraints already reach the SQL generator today —
  `prompt_builder._live_schema_block()` emits a "REAL FOREIGN KEYS"
  section sourced from `pg_constraint`, and `annotations.prohibited_joins_text()`
  already surfaces every curated prohibition. What's missing is runtime
  *path computation* (shortest path across a table set, not just a flat
  per-table FK list) and a fan-out guard on fact-to-fact paths. Checking
  all four schemes' curated `foreign_key_augmentation.yaml` files found
  **zero** curated positive (non-FK) edges (`declared: false` and not
  `is_prohibited`) — every edge is either a real FK or a deliberate
  prohibition — so there is no dead curated data to "unlock," only a
  graph-search step to add on top of data that already loads.

This phase builds both nodes, scoped to what the code actually needs
rather than the audit summary's framing, and confirms the vector-store
foundation (Postgres/pgvector on Neon, per the retroactive migration
proposal) by extending it with two new dedicated tables.

## What Changes

- Add a scheme registry (`scheme_registry.yaml`): id, display name,
  aliases, table list, `shared` flags — looked up directly for
  structural facts, loaded at startup like `entity_resolver.py`/
  `annotations.py`'s YAML caches, with a manual admin-triggered reload
  endpoint matching the real precedent already in the codebase
  (`POST /api/rag/reingest`), not an automatic periodic refresh — no
  such mechanism exists anywhere today, confirmed by reading both
  `entity_resolver.py` and `annotations.py` in full.
- Add two new dedicated pgvector tables, following the existing
  one-table-per-collection pattern (`megh_scheme_kb`,
  `megh_conversation_memory`) rather than introducing a `kind`-discriminated
  table: `megh_schema_metadata` (scheme/table/column-granularity
  descriptions, scheme-scoped) and `megh_sql_examples` (a handful of seed
  examples, for testing generation end-to-end — full example-pool growth
  is ongoing SME work, out of scope here).
- Add a schema-retrieval function: embed the question, pre-filter by
  scheme_id (+ shared), rank by cosine similarity, return top-N — wired
  into `app/pipeline.py` as a **supplement** to the existing
  classifier + `schema_context.py` path, not a replacement. Existing
  scheme-scoped context keeps flowing exactly as it does today.
- Add an in-memory FK graph built at startup from `information_schema`
  (read-only, `megh_db`) plus the curated YAML's edges (all of which are
  either real FKs or prohibitions today), searched with a plain in-house
  BFS shortest-path (no new dependency — each scheme's graph has under
  10 nodes, and there is no curated data volume that would justify
  NetworkX). Includes a fan-out guard (flag rather than silently emit a
  fact-to-fact path that doesn't route through a shared dimension) and a
  no-path fallback into the existing clarification-gate mechanism in
  `app/pipeline.py`.
- Pilot the schema-metadata pipeline on **CM Elevate** (smallest table
  count) and prove the onboarding path with **Focus Plus** as the second
  scheme — not a 25-scheme rollout. Full description coverage for
  MGNREGA and PMAY-G (already covered in depth by `schema_context.py`'s
  hand-written blocks) is not required to close this phase.
- Document the onboarding flow (`docs/scheme-onboarding.md`): registry
  entry → SME descriptions → indexer run → FK candidate review → graph
  reload, with zero pipeline-node code changes required per new scheme.

## Capabilities

### New Capabilities
- `schema-retrieval`: scheme-scoped semantic retrieval over embedded
  schema-metadata documents (scheme/table/column granularity), used to
  supplement the existing classifier-scoped schema context with
  fuzzy-matched candidates; includes the scheme registry lookup that
  both this and join-discovery depend on.
- `join-discovery`: runtime join-path computation over an in-memory FK
  graph (declared FKs + curated YAML edges), producing explicit `ON`
  clauses for the SQL generator, with a fan-out guard and a
  clarification fallback when no approved path exists.

### Modified Capabilities
(none — no existing `openspec/specs/` capability has a behavior change;
Phase 1's specs are unaffected)

## Impact

- New dependency: none beyond what's already landed (pgvector via the
  retroactive migration). NetworkX is explicitly NOT added — see
  design.md.
- Affected files: `app/vectorstore.py` (extend with two new tables),
  new `app/schema_retrieval.py`, new `app/join_graph.py`, new
  `scheme_registry.yaml`, `app/pipeline.py` (wire in both new node
  calls), existing curated `*_foreign_key_augmentation.yaml` files
  (positive edges now consumed by the graph, not just the deny-list via
  `app/annotations.py`), new `docs/scheme-onboarding.md`.
- No changes to `DATABASE_URL` connection handling, roles, pools, or
  writes — this phase only reads `megh_db`'s catalog and executes
  already-validated SQL exactly as before.
- No API contract changes — this phase improves what SQL gets
  generated, not the response shape.
