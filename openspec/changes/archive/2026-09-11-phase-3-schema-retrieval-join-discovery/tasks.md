## 0. Confirm the foundation before building on it

- [x] 0.1 Read `app/vectorstore.py` in full. Confirmed: one table per
      collection (`megh_scheme_kb`, `megh_conversation_memory`), no
      `kind` discriminator column exists or is planned — new
      collections get their own tables (see design.md).
- [x] 0.2 Confirmed embedding model/dimension: `EMBEDDING_PROVIDER=local`
      by default, `BAAI/bge-small-en-v1.5` via `app/local_embed.py`,
      384-dim (`local_embed.dim()`). New tables size `vector(dim)` from
      `local_embed.dim()` (or the actual returned vector length), never
      a hardcoded number.
- [x] 0.3 Read `app/kb_ingest.py` and `app/rag.py`. Decision: KB
      documents stay in `megh_scheme_kb` exactly as they are — this
      phase adds two new, separate tables (`megh_schema_metadata`,
      `megh_sql_examples`) rather than migrating KB docs into a shared
      table. Documented in proposal.md/design.md, not left implicit.
- [x] 0.4 Read all four schemes' curated `foreign_key_augmentation.yaml`
      in full. Confirmed: `app/annotations.py:81-91` loads the whole
      file into `_fk_cache[scheme]`, but only
      `prohibited_joins_text()` (`annotations.py:208-219`) reads from
      it at runtime.

      **Correction (found during Phase 3 close-out review):** this task
      originally claimed zero curated positive (non-FK, non-prohibited)
      edges existed in any of the four files, with every edge either
      `declared: true` or `is_prohibited: true`. That is true for
      MGNREGA, PMAY-G, and CM Elevate, but wrong for Focus Plus: its
      file uses a third value, `declared: inferred` ("NOT ONE FOREIGN
      KEY IN THIS FILE IS A VERIFIED CONSTRAINT" per that file's own
      header), and three of those edges
      (`fact_focus_plus_disbursement` -> `dim_geography`/`dim_year`/
      `dim_scheme`) are not prohibited either — genuine curated-only
      positive edges, present since the file's first commit. No live
      behavior was affected: `app/join_graph.py`'s edge loader never
      checked `declared` in the first place, only `is_prohibited`, so
      these three edges were already being loaded and used for
      join-path discovery. Only this task's own accounting and
      `join_graph.py`'s module docstring were wrong; both corrected
      2026-09-11.

## 1. Vector tables + schema-metadata pipeline

- [x] 1.1 Added `megh_schema_metadata` and `megh_sql_examples` table
      support to `app/vectorstore.py`, following the exact
      `recreate_collection`/`upsert`/`search` shape already used for
      `megh_scheme_kb` (`RAG_SCHEMA_METADATA_TABLE` /
      `RAG_SQL_EXAMPLES_TABLE` settings added). Composite index on
      `(scheme_id)` plus an HNSW cosine index on `embedding` for each.
- [x] 1.2 Wrote `scheme_registry.yaml` covering all four existing
      schemes (MGNREGA, PMAY-G, Focus Plus, CM Elevate) plus a `shared`
      entry for the cross-scheme dimensions.
- [x] 1.3 Wrote `app/scheme_registry.py`: `load_all()` at startup
      (wired into `app/main.py`'s lifespan), plus a manual
      admin-triggered `POST /api/rag/reload-scheme-registry` route in
      `app/routers/rag.py` — matching the real precedent
      (`POST /api/rag/reingest`), not an automatic periodic refresh.
- [x] 1.4 Wrote scheme-level, table-level, and column-level (significant
      columns only) descriptions for **CM Elevate**
      (`data/cm_elevate/schema_metadata.yaml`), condensed from
      `schema_context.py`'s existing hand-curated CM Elevate blocks.
- [x] 1.5 Wrote `app/schema_metadata_ingest.py`: embeds
      `data/<scheme>/schema_metadata.yaml` content into
      `megh_schema_metadata` with correct `granularity`, `scheme_id`,
      `ref` tags, via `app.llm.call_embedding`. Added a
      `POST /api/rag/reingest-schema-metadata` admin route.
- [x] 1.6 Ran the indexer against CM Elevate on the live Neon vector DB
      (confirmed reachable; `megh_db`/`DATABASE_URL` is not reachable
      from this dev sandbox, consistent with the retroactive pgvector
      proposal's finding for `smoke_restructure.py`). 9 rows created (1
      scheme + 3 table + 5 column documents); spot-checked `content`
      fields — correct.
- [x] 1.7 Wrote `app/schema_retrieval.py`: given a query string and
      active scheme(s), embeds the question, pre-filters via
      `vectorstore.search_schema_metadata` (`WHERE scheme_id = ANY(...)
      OR shared`), ranks by cosine similarity, returns top-N. Returns
      `[]` (never raises) on an empty index or an embedding failure.
- [x] 1.8 Wrote `tests/test_schema_retrieval.py`: (a) a CM Elevate
      question retrieves CM Elevate's documents; (b) a shared document
      (synthetic, cleaned up after) is retrieved regardless of active
      scheme; (c) a synthetic out-of-scope (MGNREGA) document given the
      identical embedding as the query (the highest possible score) is
      still excluded — proves the SQL `WHERE` pre-filter itself, not a
      rank cutoff, via both a monkeypatched-pool SQL-text assertion and
      a live check; (d) `[]` on empty `scheme_ids` and on a simulated
      embedding failure, no exception raised.
- [x] 1.9 Ran tests: **8/8 PASS** (`python tests/test_schema_retrieval.py`),
      including the live section against the real Neon
      `megh_schema_metadata` table populated in task 1.6.

## 2. Wire schema retrieval into the pipeline

- [x] 2.1 Added `schema_retrieval.retrieve()` as a call inside
      `app/pipeline.py`'s `generate_sql()`, positioned after scheme
      classification/entity resolution and before
      `prompt_builder.build_sql_prompt()` is invoked.
- [x] 2.2 Extended `app/prompt_builder.py` (`_retrieved_schema_block` +
      a new optional `retrieved` parameter on `build_sql_prompt`) to
      append a "RETRIEVED SCHEMA NOTES" block from the retrieved
      candidates, only when non-empty. Confirmed the existing four
      prompt sections are byte-for-byte unchanged (see test below).
- [x] 2.3 Wrote `tests/test_pipeline_schema_retrieval.py`: a CM Elevate
      question (with retrieval mocked to return sample candidates)
      produces a prompt containing the retrieved block; the same
      mechanism run against MGNREGA (mocked to return `[]`, matching
      its real un-indexed state) produces a prompt with no retrieved
      block; `retrieved=[]`/`None` produce a prompt byte-for-byte
      identical to omitting the parameter entirely.
- [x] 2.4 Ran tests: **7/7 PASS** (`python tests/test_pipeline_schema_retrieval.py`).

## 3. FK graph and join discovery

**Design correction found while implementing this group** (see
design.md and specs/join-discovery/spec.md, both updated before these
tasks were implemented): nothing in the current pipeline determines
"which tables does this question need" before the SQL generator runs —
so a join-path lookup cannot gate generation in general without parsing
the generator's *output* SQL, which risks false positives against this
codebase's own sanctioned CTE-then-join pattern and would need a real
SQL parser this codebase doesn't have. The existing PROHIBITED JOINS
mechanism has the identical limitation (a prompt instruction, never
enforced by parsing the returned SQL) — confirmed by reading
`app/annotations.py`. Join discovery matches that same tier for the
common case (additive prompt hint) and hard-gates only in the one
narrow case with a genuine pre-generation signal: when
`schema_retrieval.retrieve()` itself returns 2+ distinct
table-granularity candidates. User confirmed this approach explicitly
before implementation.

- [x] 3.1 Wrote `app/join_graph.py`: an in-memory adjacency-list graph
      (plain `dict`, no new dependency) from
      `schema_introspect.live_fks()` (already loaded, read-only,
      `megh_db`) plus each scheme's curated YAML `edges` sections,
      excluding any edge marked `is_prohibited` AND excluding any node
      tagged `readable_by_read_role: false` (the node-level safety net —
      confirmed one curated YAML's edge into `raw.source_rows` was
      missing the per-edge `is_prohibited` flag its sibling schemes
      have). Wired `join_graph.build()` into `app/main.py`'s startup.
- [x] 3.2 Wrote `find_join_path(tables: list[str])`: BFS shortest-path
      search over the graph between consecutive required tables,
      returns the explicit `ON` clause(s) (from the edge's `on_clause`,
      or synthesized from `live_fks()`'s column pair).
- [x] 3.3 Added the fan-out guard inside `find_join_path`: if two
      endpoints are both tagged `role: fact`/`role: fact_view` and the
      shortest path between them does not pass through a
      `role: dimension` node, returns a `fan_out_guard` result instead
      of a usable path.
- [x] 3.4 Wired the narrow hard-gate into `pipeline.py`'s
      `generate_sql()` (`_join_path_hint` helper): when schema-retrieval
      candidates include 2+ distinct table-granularity refs, calls
      `find_join_path` on the top 2 before invoking the SQL generator;
      on `no_path` or `fan_out_guard`, raises the existing
      `ClarificationNeeded` (`app/pipeline.py:83`) — not a new
      mechanism. Otherwise, folds the result into the prompt as an
      additive "REQUIRED JOIN(S)" hint via `prompt_builder.py`
      (`_required_join_block`), same tier as PROHIBITED JOINS.
- [x] 3.5 Wrote `tests/test_join_graph.py` — (a) a real declared-FK pair
      (`curated.fact_mgnrega_employment`/`curated.dim_geography`) gets
      the graph's exact `on_clause`; (b) the real prohibited
      fact-to-fact edge (MGNREGA employment/expenditure) is never used
      directly, even though a valid dimension-routed path exists; (c) a
      real curated cross-scheme pair (`curated.v_pmay`/
      `curated.fact_mgnrega_employment`) has no usable path — and
      `tests/test_pipeline_join_discovery.py` — (d) `generate_sql`
      raises `ClarificationNeeded` (tagged `join-no-path`/`join-fan-out`)
      for that unsafe pair *before* the SQL generator is ever called;
      (e) a safe real-FK pair proceeds and the hint is folded into the
      prompt; (f) fewer than 2 retrieved table candidates (0 or 1) —
      the actual state of every piloted scheme today — leaves
      generation completely unchanged, no gate, no hint. Join discovery
      never touches `_assert_safe`/`db.py`, so (g) SQL safety validation
      is unaffected by construction, not by a separate check.
- [x] 3.6 Ran tests: **6/6 PASS** (`test_join_graph.py`) + **8/8 PASS**
      (`test_pipeline_join_discovery.py`). Also re-ran the existing
      `test_security.py` and `test_context_manager.py` suites — both
      still fully pass, confirming no regression from the
      `pipeline.py`/`prompt_builder.py` changes. `python -c "import
      app.main"` also confirmed the full app still boots cleanly with
      all new modules wired in.

## 4. Onboarding path

- [x] 4.1 Wrote `docs/scheme-onboarding.md`: registry entry → SME
      descriptions → indexer run → FK candidate review → graph reload,
      per proposal.md.
- [x] 4.2 Proved it: executed the documented flow end-to-end for
      **Focus Plus** (the second scheme, after the CM Elevate pilot) —
      added its `scheme_registry.yaml` entry (done in task 1.2, ahead of
      time, since the registry covers all four schemes up front),
      wrote `data/focus_plus/schema_metadata.yaml`, ran the indexer
      (`ingest_schema_metadata(["CM Elevate", "Focus Plus"], force=True)`
      against the live Neon table — both schemes' rows coexist: 9 CM
      Elevate + 7 Focus Plus = 16 total). Confirmed via this session's
      own edit sequence: zero changes were made to `pipeline.py`,
      `schema_retrieval.py`, or `join_graph.py` after Group 3 completed
      — only a new YAML data file and an indexer run were needed for
      Focus Plus. `join_graph.py` already covered Focus Plus's FK graph
      from the start, since it loads all four schemes'
      `foreign_key_augmentation.yaml` files unconditionally.
- [x] 4.3 Ran the full test suite: all four Phase 3 suites
      (`test_schema_retrieval.py`, `test_pipeline_schema_retrieval.py`,
      `test_join_graph.py`, `test_pipeline_join_discovery.py` — **27/27
      PASS** combined) plus the existing `test_security.py` and
      `test_context_manager.py` (both fully pass, unchanged). The live
      schema-retrieval checks now exercise real two-scheme data (CM
      Elevate + Focus Plus in the same table) and still correctly
      scope — Focus Plus's addition did not regress CM Elevate's
      behavior.

## 5. Exit criteria

- [x] 5.1 Confirmed all task groups' tests pass: 8/8 (group 1) + 9/9
      (group 2) + 6/6 + 8/8 (group 3) = 31/31 new Phase 3 checks, plus
      the pre-existing `test_security.py`/`test_context_manager.py`
      suites fully passing unchanged.
- [x] 5.2 Task 0.3's KB-storage decision (KB docs stay in
      `megh_scheme_kb`; two new dedicated tables added instead of a
      shared/discriminated table) and task 1.1's table-design decision
      (one-table-per-collection, matching the existing pattern) are
      both documented in proposal.md and design.md.
- [x] 5.3 Task 4.2's zero-code-change onboarding proof demonstrated via
      this session's own edit sequence (confirmed above, not assumed):
      no edits to `pipeline.py`/`schema_retrieval.py`/`join_graph.py`
      after Group 3, only `data/focus_plus/schema_metadata.yaml` and an
      indexer run for Focus Plus.
- [x] 5.4 Confirmed via `git status`/`git diff` on `app/db.py` and
      `.env`: both untouched this session — no changes to `DATABASE_URL`
      connection handling, roles, or write paths.
- [x] 5.5 Noted here and in the completion report: full schema-
      description coverage for MGNREGA and PMAY-G (already served in
      depth by `schema_context.py`'s hand-written blocks) is ongoing
      SME-paced work, not a gate for closing this phase — CM Elevate +
      Focus Plus prove the mechanism end to end.
