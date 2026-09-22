## 1. Storage + config scaffolding

- [x] 1.1 Added `vectorstore.sql_examples_count()`, mirroring
      `schema_metadata_count()` (row count, or -1 on `UndefinedTableError`).
- [x] 1.2 Added `SQL_EXAMPLES_TOP_K: int = 5` to `app/config.py`, next to
      `RAG_SQL_EXAMPLES_TABLE`. No dedicated enable flag — matches
      `schema_retrieval.retrieve()`'s own precedent of no on/off knob,
      documented inline.

## 2. Ingest module

- [x] 2.1 New `app/sql_examples_ingest.py`: own scheme→file map, loads
      each `*_few_shot.yaml`'s `sql_generation_examples`, drops
      `status: RETIRED_v2.0`, maps `status: UNANSWERABLE` to
      `is_answerable=false` + `reason`, everything else to `sql` text.
      `ingest_sql_examples(schemes=None, force=False)` embeds via
      `llm.call_embedding`, idempotent-skips unless `force=True`, calls
      `vectorstore.recreate_sql_examples_table` + `upsert_sql_examples`
      in batches of 128.
- [x] 2.2 Pure-logic test coverage for the real `_load_scheme_file` +
      `_collect_points` against a temp-file fixture (not a monkeypatched
      stub) — RETIRED dropped, UNANSWERABLE mapped correctly with its
      reason whitespace-collapsed, a normal example keeps its `sql` text,
      an example with no question or no sql-or-reason is skipped.

## 3. Retrieval + prompt wiring

- [x] 3.1 New `app/sql_examples_retrieval.py`: `retrieve(question,
      scheme_ids)` — embed, then `vectorstore.search_sql_examples`
      filtered to `scheme_ids`, `top_k=SQL_EXAMPLES_TOP_K`. Degrades to
      `[]` (never raises) on empty `scheme_ids`, embedding failure, or
      search failure (table not yet created).
- [x] 3.2 `app/prompt_builder.py`: `_fewshot_block` is now `async`, tries
      `sql_examples_retrieval.retrieve` first, falls back to
      `annotations.few_shot_examples` when empty. `build_sql_prompt` is
      now `async def`.
- [x] 3.3 `app/pipeline.py`: `await`s the `build_sql_prompt` call in
      `generate_sql`.
- [x] 3.4 Updated `tests/test_pipeline_schema_retrieval.py` for the now-
      async `build_sql_prompt` (wrapped sections 1-2 in `asyncio.run`),
      and monkeypatched `sql_examples_retrieval.retrieve` to return `[]`
      for the suite's existing calls — preserves this file's declared
      "no model gateway" stance and its byte-for-byte-unchanged
      assertions exactly as before this change.

## 4. Admin re-ingest endpoint

- [x] 4.1 `app/routers/rag.py`: `POST /api/rag/reingest-sql-examples`,
      mirroring `/reingest-schema-metadata` (admin-only, `schemes`
      filter, `force=True`).

## 5. New test suite + regression sweep

- [x] 5.1 New `tests/test_sql_examples_retrieval.py`, mirroring
      `tests/test_schema_retrieval.py`'s shape: (a) `retrieve()` degrades
      safely; (b) `search_sql_examples`'s scheme pre-filter is in the SQL
      itself; (c) `_fewshot_block` uses vector results when non-empty and
      falls back to token-overlap when empty; (d) `sql_examples_ingest`
      real-file-fixture checks from 2.2; (e) best-effort live section
      against real Neon (SKIP, not FAIL, if unreachable/unseeded).
- [x] 5.2 Ran `python tests/test_sql_examples_retrieval.py` — **16/16
      PASS** (live section correctly SKIPped: Neon itself is reachable —
      confirms prior sessions' finding — but `megh_sql_examples` doesn't
      exist yet, since nobody has called the new endpoint against
      production; expected pre-rollout state, not a failure).
- [x] 5.3 Ran the repo's standing regression baseline —
      **114/114 PASS, 0 FAIL** across
      `test_security.py` (31), `test_context_manager.py` (58),
      `test_schema_retrieval.py` (12), `test_join_graph.py` (5),
      `test_pipeline_join_discovery.py` (8) — plus
      `test_pipeline_schema_retrieval.py` (9/9, counted separately in
      group 3 above since it's the file this change edited directly).
      The `DBUnavailableError`/gateway-down tracebacks in the output are
      these suites' own deliberate failure-path simulations, not
      regressions.

## 6. Exit criteria

- [x] 6.1 All suites from 5.2-5.3 pass, exact counts as above (9 + 16 +
      114 = 139 checks, 0 failures).
- [x] 6.2 `git status --porcelain` confirms exactly the files listed in
      proposal.md's Impact section changed — `app/config.py`,
      `app/pipeline.py`, `app/prompt_builder.py`, `app/routers/rag.py`,
      `app/vectorstore.py` (modified, each via a scoped `Edit` — see
      note below on pre-existing mixed diffs), plus the new
      `app/sql_examples_ingest.py`, `app/sql_examples_retrieval.py`,
      `tests/test_sql_examples_retrieval.py`, and this
      `openspec/changes/sql-generation-vector-fewshot/` directory.
      Per CLAUDE.md's "mixed-concern files" note, `app/config.py` and
      `app/pipeline.py` already carried pre-existing, unrelated
      uncommitted work before this session — this change's own edits
      inside them are additive and scoped (confirmed via the `Edit` tool's
      exact old/new-string matches, not a broad rewrite), but a
      `git diff` of either file will show more than just this change.
- [x] 6.3 No `.env`/`.env.example` change — confirmed no new required
      config; the one new setting has a default and the new endpoint
      reuses existing admin auth.
