# Onboarding a new scheme (schema retrieval + join discovery)

Adding scheme N+1 to the `schema-retrieval` and `join-discovery`
capabilities (see `openspec/changes/phase-3-schema-retrieval-join-discovery/`)
touches only YAML/data files and one indexer run — no pipeline node code
changes. This is an acceptance criterion of that phase (task 4.2), proven
end to end using Focus Plus as the second scheme after the CM Elevate
pilot.

## Steps

1. **Add a `config/scheme_registry.yaml` entry**. One block under
   `schemes:` — `id`, `display_name`, `aliases`, `tables` (the scheme's
   curated/semantic objects), `shared: false`. Reload without a redeploy
   via `POST /api/rag/reload-scheme-registry` (admin-only). Since
   `openspec/changes/multi-tenant-rls-scheme-scaleout`, this same reload
   also upserts the new scheme into `app.schemes` — the DB-backed
   identity table `app.tenant_schemes` grants reference and, once the
   scheme's fact table(s) are added to `curated.table_scheme_map`
   (`deploy/sql/03_tenant_scheme_rls.sql`, a superuser step — see that
   file), the table curated-data RLS policies key off. Registering a
   scheme here does **not** grant any tenant access to it — see step 6.

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
   `app.knowledge.schema_metadata_ingest.ingest_schema_metadata(["<scheme>"],
   force=True)` directly. This embeds the new scheme's
   `schema_metadata.yaml` into `megh_schema_metadata`, tagged with the
   scheme's `scheme_id`.

4. **SME reviews auto-mined FK candidates** for the new scheme's tables
   (informal step today — `app/sql/join_graph.py` reads
   `data/<scheme>/*foreign_key_augmentation.yaml` directly; there is no
   separate mining tool yet, so this step is "write/extend that curated
   YAML file," following the existing four schemes' format: `nodes`
   with a `role` per object — `fact`/`fact_view`/`dimension`/others —
   and `edges` with an explicit `on_clause` per non-prohibited edge,
   `is_prohibited: true` for anything that must never be joined).

5. **Append approved edges to the curated YAML, then reload the join
   graph without a restart**: `POST /admin/reload-join-graph`
   (admin-only) — added by `openspec/changes/multi-tenant-rls-scheme-scaleout`,
   calls `join_graph.build(force=True)` and returns the rebuilt graph's
   node counts. Before this endpoint existed, a new scheme's join edges
   required a full service restart (`join_graph.build()` only ran once,
   at process startup) — tractable at 4 schemes, a real operational cost
   onboarding schemes 5 through 25 one at a time.

6. **Grant tenant access to the new scheme** (only relevant once
   `TENANT_SCHEME_RLS_ENABLED` is on in a given environment — see
   `openspec/changes/multi-tenant-rls-scheme-scaleout`): registering a
   scheme in step 1 does not grant anyone access to it.
   `POST /admin/tenants/{tenant_id}/schemes/{scheme_id}` (super_admin-only)
   grants it explicitly; `GET /admin/schemes` lists what's registered,
   `GET /admin/tenants/{tenant_id}/schemes` shows a tenant's current
   grants. With the flag off (today's default), this step is a no-op —
   every scheme registered in step 1 is visible to every user exactly as
   before this mechanism existed.

## What must NOT change

`app/orchestration/pipeline.py`, `app/sql/schema_retrieval.py`, and `app/sql/join_graph.py` —
zero edits to any of these for scheme N+1. Every scheme-specific fact
lives in `config/scheme_registry.yaml`, `data/<scheme>/schema_metadata.yaml`,
and `data/<scheme>/*foreign_key_augmentation.yaml`.

## Proof (task 4.2, and again at task 6.4)

Focus Plus was onboarded via exactly the steps above, after CM Elevate
(the pilot). No line of `pipeline.py`, `schema_retrieval.py`, or
`join_graph.py` was touched for it — see the "Onboarding path" section of
`tasks.md` for the verification run.

**A stronger, more recent proof (`multi-tenant-rls-scheme-scaleout` task
6.4, 2026-09-18)**: a throwaway 5th scheme (not scheme #2 — the actual
"scales past today's 4" claim) was onboarded end to end against a real
disposable Postgres, in one continuously-running process, zero restarts:
registry entry → `scheme_registry.load_all()` picked it up →
`sync_to_db()` wrote it into `app.schemes` → `POST /admin/reload-join-graph`
(`join_graph.build(force=True)`) ran clean → a `table_scheme_map` insert +
the RLS `ENABLE`/`FORCE`/`CREATE POLICY` statements applied → a tenant
without the new scheme's grant saw 0 rows, a tenant granted it saw the
real rows. The same pass also proved every one of the 8 roles in
`app/core/auth.py::ROLE_PERMISSIONS` picks up a newly-onboarded scheme
automatically (`GET /admin/roles`), after a redundant hand-typed
4-scheme literal in that file (the one hardcoded list step 6 above didn't
already cover) was found and removed — see that task's entry in
`tasks.md` for the full record.
