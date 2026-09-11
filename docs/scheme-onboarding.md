# Onboarding a new scheme (schema retrieval + join discovery)

Adding scheme N+1 to the `schema-retrieval` and `join-discovery`
capabilities (see `openspec/changes/phase-3-schema-retrieval-join-discovery/`)
touches only YAML/data files and one indexer run — no pipeline node code
changes. This is an acceptance criterion of that phase (task 4.2), proven
end to end using Focus Plus as the second scheme after the CM Elevate
pilot.

## Steps

1. **Add a `scheme_registry.yaml` entry** (repo root). One block under
   `schemes:` — `id`, `display_name`, `aliases`, `tables` (the scheme's
   curated/semantic objects), `shared: false`. Reload without a redeploy
   via `POST /api/rag/reload-scheme-registry` (admin-only).

2. **SME (or, for a pilot, whoever knows the schema) writes descriptions**
   in `data/<scheme>/schema_metadata.yaml`, three sections:
   - `scheme:` — one `content` block: what the scheme does, who it
     serves, common phrasings.
   - `tables:` — one entry per significant table/view (`ref` +
     `content`): what it represents, fact vs. dimension, how to query it.
   - `columns:` — one entry per significant column (`ref` as
     `<table>.<column>` + `content`): synonyms, gotchas, exact stored
     values.
   These are genuinely new prose, not derived automatically — the real
   bottleneck this phase's proposal.md calls out. Reusing the scheme's
   existing hand-curated `schema_context.py` blocks as source material
   (condensed into embeddable prose) is the fastest honest path, as done
   for both CM Elevate and Focus Plus.

3. **Run the indexer**: `POST /api/rag/reingest-schema-metadata` with
   `{"schemes": ["<scheme>"]}` in the body (admin-only), or call
   `app.schema_metadata_ingest.ingest_schema_metadata(["<scheme>"],
   force=True)` directly. This embeds the new scheme's
   `schema_metadata.yaml` into `megh_schema_metadata`, tagged with the
   scheme's `scheme_id`.

4. **SME reviews auto-mined FK candidates** for the new scheme's tables
   (informal step today — `app/join_graph.py` reads
   `data/<scheme>/*foreign_key_augmentation.yaml` directly; there is no
   separate mining tool yet, so this step is "write/extend that curated
   YAML file," following the existing four schemes' format: `nodes`
   with a `role` per object — `fact`/`fact_view`/`dimension`/others —
   and `edges` with an explicit `on_clause` per non-prohibited edge,
   `is_prohibited: true` for anything that must never be joined).

5. **Append approved edges to the curated YAML**. No separate "graph
   reload" endpoint exists yet for `join_graph.py` specifically — it
   rebuilds at process startup (`join_graph.build()` in
   `app/main.py`'s lifespan). A code change to add a manual reload
   route for it, mirroring the KB/schema-metadata reingest pattern, is
   a reasonable small follow-up but was not required to prove the
   zero-pipeline-code-change claim (a restart picks up new YAML content
   today, same as `annotations.py`'s few-shot/FK cache).

## What must NOT change

`app/pipeline.py`, `app/schema_retrieval.py`, and `app/join_graph.py` —
zero edits to any of these for scheme N+1. Every scheme-specific fact
lives in `scheme_registry.yaml`, `data/<scheme>/schema_metadata.yaml`,
and `data/<scheme>/*foreign_key_augmentation.yaml`.

## Proof (task 4.2)

Focus Plus was onboarded via exactly the steps above, after CM Elevate
(the pilot). No line of `pipeline.py`, `schema_retrieval.py`, or
`join_graph.py` was touched for it — see the "Onboarding path" section of
`tasks.md` for the verification run.
