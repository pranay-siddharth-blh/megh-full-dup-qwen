## Why

The user asked to "complete §5.10 SQL generation end to end," pointing at
the original Grant Thornton proposal text, which specifies: a single LLM
call assembling a schema section, a join section, "a handful of few-shot
examples retrieved from the same vector store as schema retrieval (but in
a separate question→SQL collection)," the analysed query, and resolved
entities — with the example pool "start[ing] from the use-case sheets and
grow[ing] over time as new validated queries are added." Tools named:
Qwen 2.5 Coder 32B via vLLM (alternatives DeepSeek Coder V2 / Llama 3.3
70B / SQLCoder), Jinja2 for prompt templating, and "Outlines with a SQL
grammar can be added for guaranteed-parseable output."

Re-checked against the actual codebase before scoping this (per the
repo's re-verify-before-implementing rule), following the same "tool
list vs. architecture" split the `schema-retrieval-reranking` change used
for §5.8:

- **The single-LLM-call architecture, schema section, join section,
  resolved-entities section, and analysed-query threading all already
  exist and are correctly implemented.** `pipeline.generate_sql()`
  (`app/pipeline.py:2507-2542`) calls `schema_retrieval.retrieve()`
  (§5.8), resolves a join hint via `join_graph` (§5.9), builds one prompt
  via `prompt_builder.build_sql_prompt()`, and makes one call to
  `llm.call_sql_generator`. `docs/baseline-audit.md` §5.10 already
  records this as "Implemented, with a weaker input than specified,"
  scoped narrowly to the §5.9 join-path gap — that gap is out of this
  change's scope (it's §5.9/join-discovery's, already tracked there).
- **Model, alternatives, Jinja2, and Outlines are tool-list items, not
  the architecture, and are deliberately not chased here** — same
  reasoning the `schema-retrieval-reranking` proposal applied to
  Qdrant/BGE/sentence-transformers:
  - The deployed model is `qwen3-coder-30b-fp8` (`SQL_GENERATION_MODEL`,
    `app/config.py:174`), not literally Qwen 2.5 Coder 32B — a pre-existing,
    already-documented divergence (baseline-audit.md's own "model swap"
    note), and the model name is a fixed gateway deployment on
    `10.48.242.4` — an infra choice, not something this repo's code can
    change (same class of gap as the DB-role cutover: not implementable
    client-side).
  - `app/prompt_builder.py` assembles the structured prompt via plain
    Python string composition, not Jinja2. It already produces exactly
    the sectioned structure the spec describes (schema / join / few-shot
    / entities / question). Porting a working, whitespace-sensitive LLM
    prompt to a template engine for its own sake is pure tooling churn
    with real regression risk (prompt formatting differences are exactly
    the kind of thing that silently changes generation quality) and no
    functional gap it closes — not done.
  - Guided decoding already exists (`app/config.py:114-123`,
    `SQL_GUIDED_DECODING_ENABLED`, `_SQL_SHAPE_REGEX` in
    `app/pipeline.py:332`), and its own comment already documents the
    Outlines-grammar tradeoff explicitly: "Deliberately looser than a
    full SQL grammar — it enforces shape, not join correctness." The
    spec itself phrases full-grammar decoding as optional ("can be
    added"), and the practical guarantee it would provide
    (guaranteed-parseable output) is already achieved at a different
    layer — a real sqlglot-AST safety check
    (`app/db.py::_assert_safe`, re-verified 2026-09-14, see
    `[[project-db-role-cutover-blocked]]` memory) plus the existing
    repair-loop in `pipeline.py:2923`. Not reintroducing Outlines.
- **The one genuinely missing piece is the few-shot retrieval mechanism
  itself.** The spec's architecture is semantic vector retrieval from a
  dedicated collection. What actually runs today
  (`app/prompt_builder.py:101-116`'s `_fewshot_block`, backed by
  `app/annotations.py:178`'s `few_shot_examples()`) is a **different**
  mechanism entirely: every scheme's `*_few_shot.yaml` is loaded once at
  startup into an in-process list, and ranked per-question by a
  hand-built token-overlap + synonym-table heuristic
  (`_fewshot_score`/`_FEWSHOT_SYNONYMS`, `app/annotations.py:94-176`) —
  no embeddings, no vector store, not the "same vector store as schema
  retrieval" the spec calls for.
  Confirms this is genuinely unwired, not just differently named: `grep
  -rn "search_sql_examples\|upsert_sql_examples\|recreate_sql_examples_table"
  app/ tests/` returns **zero call sites** outside their own definitions
  in `app/vectorstore.py:252-349`. The `megh_sql_examples` pgvector
  table, its config entry (`RAG_SQL_EXAMPLES_TABLE`, `app/config.py:321`,
  filed under a "Vector store — schema metadata / SQL examples (Phase 3)"
  comment block), and its upsert/search functions were scaffolded during
  Phase 3 alongside the schema-metadata collection but never connected to
  anything — dormant since it was written, exactly the shape of gap this
  change closes.
- **"Grows over time as new validated queries are added" has no
  mechanism today.** `app/routers/rag.py` has `/reingest` (KB) and
  `/reingest-schema-metadata`, but no SQL-examples equivalent — there is
  no way, today, to get a `*_few_shot.yaml` addition (or any validated
  query) into `megh_sql_examples` at all, since nothing ever populates
  that table in the first place.
- **Re-verification caveat, flagged transparently rather than silently
  worked around:** the spec's wording implies the starting pool is
  already "validated." `data/cm_elevate/cmelevate_few_shot.yaml`'s own
  header (lines 38-40) states plainly: "NOT ONE OF THESE QUERIES HAS BEEN
  EXECUTED against megh_db... unverified against the data." The four
  `*_few_shot.yaml` files are real, SME-authored use-case-sheet artifacts
  (matching "starts from the use-case sheets"), but at least the CM
  Elevate file is execution-unverified, not the fully-validated pool the
  spec's language suggests. This change indexes that pool into the
  vector store as-is — it does not and cannot fix the underlying
  data-quality gap (running ~360 queries against production and grading
  them is SME/human work, out of scope here, same "human-gated tasks
  stay unchecked" posture as other blocked items in this repo).

## What Changes

- New `app/sql_examples_ingest.py`: embeds each scheme's
  `*_few_shot.yaml` `sql_generation_examples` (dropping
  `status: RETIRED_v2.0`, exactly as `app/annotations.py` already does at
  runtime) into `megh_sql_examples` — `is_answerable=false` + `reason`
  for `status: UNANSWERABLE` negative examples, `sql` text otherwise.
  Mirrors `app/schema_metadata_ingest.py`'s shape: its own copy of the
  scheme→file map (so it runs standalone, matching that module's own
  precedent of not importing `app/annotations.py`'s), idempotent
  row-count skip unless `force=True`.
- New `app/sql_examples_retrieval.py`: `retrieve(question, scheme_ids)` —
  embed the question, then `vectorstore.search_sql_examples` filtered to
  `scheme_ids`, mirroring `app/schema_retrieval.py`'s
  never-raises-degrades-to-`[]` contract (embedding failure, or the table
  not existing yet because no scheme has been ingested, both degrade to
  `[]`, not an exception). No reranking stage — the spec doesn't call for
  one here, unlike §5.8's explicit "top-30 then rerank to top-8."
- `app/vectorstore.py`: add `sql_examples_count()`, mirroring
  `schema_metadata_count()`, for the ingest module's idempotent-skip
  check.
- `app/config.py`: add `SQL_EXAMPLES_TOP_K: int = 5` next to the existing
  `RAG_SQL_EXAMPLES_TABLE` setting (same default as the current
  `few_shot_examples(..., top_k=5)` call). No enable/disable flag —
  `schema_retrieval.retrieve()` has none either; both degrade safely by
  design, so a flag would add a knob with no real decision behind it.
- `app/prompt_builder.py`: `_fewshot_block` becomes `async`, tries
  `sql_examples_retrieval.retrieve()` first. A non-empty result is used
  directly (adapted to the block's existing two rendering branches — a
  worked example vs. an `is_answerable=false` negative example). An empty
  result (table not yet seeded for this scheme, or an embedding failure)
  falls back unchanged to today's `annotations.few_shot_examples()`
  token-overlap path — additive/never-gating, the same stance every
  other retrieval node in this pipeline already takes.
  `build_sql_prompt` becomes `async def` (its only caller,
  `pipeline.generate_sql`, is already `async`).
- `app/pipeline.py`: `await` the now-`async` `build_sql_prompt` call
  in `generate_sql`. `build_repair_prompt` is untouched — it doesn't call
  `_fewshot_block` today and this change doesn't add one there.
- `app/routers/rag.py`: new `POST /api/rag/reingest-sql-examples`,
  mirroring `/reingest-schema-metadata` exactly (same admin-only auth,
  same `schemes` filter + `force` semantics). This is the "grows over
  time" mechanism in practice: add a validated example to the relevant
  `*_few_shot.yaml` (the existing SME-reviewed artifact), then call this
  endpoint to re-embed — one place SMEs edit, not two.

## Capabilities

### Added Capabilities
- `sql-generation`: first spec for §5.10 — the vector-backed few-shot
  retrieval requirement (delta below). The single-LLM-call architecture,
  schema/join/entity sections, and guided-decoding shape constraint are
  pre-existing and not restated here as new requirements (out of this
  change's scope; see the join-path gate for follow-up if §5.9 changes).

## Impact

- Affected files: `app/sql_examples_ingest.py` (new),
  `app/sql_examples_retrieval.py` (new), `app/vectorstore.py`
  (`sql_examples_count`), `app/config.py` (`SQL_EXAMPLES_TOP_K`),
  `app/prompt_builder.py` (`_fewshot_block` + `build_sql_prompt` async),
  `app/pipeline.py` (`await` the call site), `app/routers/rag.py` (new
  endpoint), `tests/test_pipeline_schema_retrieval.py` (updated for the
  async signature), `tests/test_sql_examples_retrieval.py` (new).
- **No behavior change until an admin runs the new endpoint.** Until
  `POST /api/rag/reingest-sql-examples` is called at least once,
  `megh_sql_examples` doesn't exist, `sql_examples_retrieval.retrieve()`
  degrades to `[]` on every call, and every SQL-generation prompt is
  byte-for-byte identical to today's token-overlap-YAML path — same
  rollout posture as the schema-metadata pilot.
- After it's run for a scheme: that scheme's few-shot examples in the
  prompt come from semantic (embedding cosine) ranking instead of
  token-overlap ranking. One documented behavior nuance: today's
  token-overlap path returns up to `top_k` examples **per scheme**
  (looped), so a cross-scheme question could see up to 10; the vector
  path returns up to `SQL_EXAMPLES_TOP_K` **total** across the given
  `scheme_ids` in one query (a single `WHERE scheme_id = ANY(...)`
  filter + `LIMIT`) — fewer examples for a multi-scheme question, by
  design (the spec calls for "a handful," not a per-scheme multiple).
- New expensive/embed-heavy admin action, admin-only (A01), same posture
  as the two existing `/api/rag/reingest*` endpoints.
- Does not touch `SQL_GENERATION_MODEL`, guided decoding, Jinja2, or
  Outlines — explicitly out of scope, reasoning above.
- `recreate_sql_examples_table` (pre-existing) still drops and rebuilds
  the whole table on `force=True`, so calling the new endpoint with a
  `schemes` subset and `force=True` loses previously-ingested rows for
  schemes not in that subset — an existing limitation inherited
  unchanged from `app/schema_metadata_ingest.py`'s identical pattern,
  not introduced by this change. Flagged here, not silently carried.
