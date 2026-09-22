# Retroactive — Qdrant → Postgres/pgvector (Neon) Migration

## Status
**Retroactive, open questions now answered from primary evidence.** Written
up after the fact by a review pass in a follow-up session, then answered in
this session by the same agent that did the implementation, against direct
evidence (the original chat instructions, live queries against the Neon
instance, and a from-scratch `.venv` rebuild + test run) rather than
recollection. Not yet reviewed/approved by a human. Treat this document as
the rollback spec if rejected, not just a record.

## Why (now sourced, not inferred)

No infra-cost, ops-simplicity, or Neon-feature rationale was recorded or
should be assumed. The literal trigger was three consecutive user messages
in the implementing session, quoted in full because the exact wording
matters for how firm this commitment is:

1. *"...for vectordatabase use thei sposogtress pg vector not the things."*
   (typo-laden for: use this Postgres/pgvector instead of Qdrant)
2. *"use this for scheme partinoing storage please"* — sent as an
   interrupt before the first request was even acted on.
3. *"and for rag also schmee meta data store and hte rag you can use this
   instead of the quadrant please"* — i.e. also use it for the RAG /
   scheme-metadata store, replacing Qdrant.

No business or technical justification was given beyond "use this
database instead of Qdrant" — the connection string had already been
pasted into `.env`'s `QDRANT_URL` field (a type mismatch: Qdrant expects
an `http://` collection endpoint, not a Postgres DSN) before the
implementing session started, which is itself weak evidence this was a
user-driven substitution decision made outside the coding session, not
one the agent proposed or justified.

**Conclusion for Phase 3 planning:** treat this as a direct, explicit user
architectural decision — not a discovered technical constraint and not
a documented cost/ops tradeoff. It should be honored as a firm constraint
(don't silently reintroduce Qdrant), but Phase 3 should not read any
deeper strategic intent into it than "run the vector store on the
Postgres the user already has, not a second service." If a deeper reason
exists (cost ceiling on the data-box VM, a Neon commitment already made
elsewhere, etc.), only the user can supply it — still genuinely open,
and the one item in this document that cannot be closed from repo/session
evidence alone.

## What Changed (confirmed accurate against the diff)

- `.env`: `QDRANT_URL`/`QDRANT_COLLECTION` → `VECTOR_DB_URL` (Neon
  connection string) + `RAG_KB_TABLE`. `DATABASE_URL` (the `megh_db`
  curated, scheme-partitioned operational data) is untouched and remains
  a separate connection/concern.
- `app/vectorstore.py`: rewritten from an `AsyncQdrantClient` wrapper to
  an `asyncpg` pool against `VECTOR_DB_URL`, auto-enabling
  `CREATE EXTENSION vector`. Public API preserved
  (`collection_count`/`recreate_collection`/`upsert`/`search`). HNSW
  cosine indexes; vectors passed as pgvector text literals (`vec_literal`)
  cast with `::vector` in SQL — no `pgvector` Python package dependency
  needed.
- `app/conversation_memory.py`: semantic "relevant older turns" store
  rewritten from Qdrant collections/filters to a Postgres table
  (`CONTEXT_MEMORY_TABLE`) with `tenant_id`/`user_id`/`session_id` columns
  and a cosine-similarity query, scoped with plain SQL `WHERE`.
- `app/kb_ingest.py`, `app/main.py`, `app/routers/rag.py`, `app/rag.py`,
  `app/context_manager.py`, `app/local_embed.py`: renamed/updated to
  match.
- `requirements.txt` / `.lock`: `qdrant-client` dropped.
- `docker-compose.yml`: local Qdrant service/volume removed.
- `README.md`, `deploy/DEPLOYMENT.md`, `.env.example`, tests: references
  updated.

## Open Questions — resolved this session

- [x] **Reason for the change.** Answered above from the actual chat
      transcript — direct user instruction, no deeper rationale recorded
      or inferable. The "get a sentence in writing from whoever requested
      it" ask is satisfied by the quotes above; a *deeper* strategic
      reason (if one exists) is still only answerable by the user.

- [x] **Was the live-Neon verification run against production-adjacent
      data?** No. Re-queried the instance directly this session (not
      relying on the prior session's report):
      - `SELECT datname FROM pg_database` → `postgres`, `neondb` — Neon's
        own default pair for a freshly created project, not custom names.
      - Schemas in `neondb` → only `public`.
      - `SELECT rolname FROM pg_roles` → `cloud_admin`, `neondb_owner`,
        `neon_service`, `neon_superuser` — Neon's own default roles only,
        no application-created role.
      - `pg_database_size('neondb')` → **7728 kB**, i.e. baseline-empty.
      - Extensions present: `plpgsql`, `vector` (0.8.6) — nothing else.
      This is a fresh, effectively empty Neon project, not a database
      carrying other production data. The verification (create test
      table → insert → search → drop) was safe by this evidence, though
      the *original* implementing session did not check pre-existing
      state before acting — it only confirmed the instance was empty
      *afterward*. That ordering gap is noted, not defended: **going
      forward, check-before-write is the correct order** for any live
      action against infra not fully under this session's control, even
      when the outcome turns out fine. Logged here per the standing
      practice Phase 1 is establishing; no separate `docs/SECURITY.md`
      entry was added because this document *is* that log entry for this
      action — if the project wants a single consolidated audit file
      instead of per-change logs, that's a Phase 1 process decision, not
      one this document should make unilaterally.

- [x] **Collection design.** Confirmed by re-reading the implementation:
      **one table per collection**, not one shared table with a
      discriminator column. `RAG_KB_TABLE` (default `megh_scheme_kb`) and
      `CONTEXT_MEMORY_TABLE` (default `megh_conversation_memory`) are two
      independent tables, each with its own `vector(dim)` column, its own
      HNSW index, and its own scoping columns (`scheme` on the KB table;
      `tenant_id`/`user_id`/`session_id` on the memory table). This
      mirrors Qdrant's separate-named-collections model 1:1 rather than
      introducing a `kind` discriminator.

      **Implication for Phase 3, stated explicitly since it wasn't
      before:** the two collections Phase 3 still needs — `schema_metadata`
      and `sql_examples` — are not yet represented as tables. Under the
      pattern already in place, the natural extension is two more
      dedicated tables (e.g. `RAG_SCHEMA_METADATA_TABLE`,
      `RAG_SQL_EXAMPLES_TABLE`) added to `app/vectorstore.py` alongside
      the existing two, each following the same
      create/upsert/search shape. This is **a recommendation, not a
      decision made here** — Phase 3 owns whether one-table-per-collection
      still holds at four collections, or whether the three-granularity
      requirement (scheme-level/table-level/column-level docs, each
      scoped by `scheme_id`) is better served by a single generalized
      table with `kind` + `scheme_id` + `table_name` + `column_name`
      columns so retrieval can filter across granularities in one query
      instead of unioning four tables. Both are workable on the current
      `asyncpg`-direct-SQL foundation; neither requires touching
      `VECTOR_DB_URL` or the extension setup again.

- [x] **Index strategy at scale — investigated, not deliberately tuned.**
      `CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)` in
      `app/vectorstore.py` carries **no explicit `m` / `ef_construction`**
      — pgvector's library defaults apply (`m=16`, `ef_construction=64`),
      and query-time `hnsw.ef_search` was never set either (pgvector
      default `40`). This was not a deliberate scale decision; it should
      be named as a default, not a choice.

      Measured against the actual current corpus, not an assumed one:
      the eight SME reference/FAQ docs `kb_ingest.py` ingests total
      **~115 KB** of source Markdown, plus **~16 KB** across the two
      `data/web/*.md` scraped docs — at `_CHUNK_SIZE = 1500` chars,
      that's on the order of **one to a few hundred rows** in
      `megh_scheme_kb` today. HNSW defaults are documented as performing
      well from thousands up to low-millions of vectors; a few hundred
      rows is nowhere near where `m`/`ef_construction` tuning would
      matter for either recall or build time.
      Phase 3's projected scale (hundreds of tables × 25 schemes worth of
      schema-metadata documents, each table/column probably one row) is
      plausibly **thousands to tens of thousands** of rows — still
      comfortably inside HNSW's default-parameter comfort zone. Continuous
      conversation-memory growth is the one dimension with no natural
      ceiling; if it becomes the actual bottleneck, `ef_search` is a
      query-time knob (no reindex) and is the first thing to tune, well
      before `m`/`ef_construction` would need revisiting.
      **Net: the defaults are not provably wrong at either today's or
      Phase 3's projected scale, but they were not chosen — they were
      inherited. Revisit only if/when `EXPLAIN ANALYZE` on the real
      corpus says otherwise; don't pre-tune on a guess.**

- [x] **`.venv` rebuild — done this session, not just flagged.**
      The checked-in `.venv` was confirmed broken (`pyvenv.cfg` pointed
      at `C:\Users\rohit\AppData\Local\Programs\Python\Python311`, a path
      that doesn't exist on this machine — it was copied from another
      machine, not created here). Rebuilt from scratch:
      `python -m venv .venv` (local Python 3.11.9) →
      `pip install -r requirements.lock` → clean install, `qdrant-client`
      confirmed absent (`pip freeze | grep qdrant` → no match).
      Re-ran the two standalone suites inside the rebuilt venv:
      - `tests/test_security.py` — **all checks passed**, no changes
        needed.
      - `tests/test_context_manager.py` — **found and fixed a real
        regression**: the test's semantic-memory isolation check (§9)
        still monkeypatched `conversation_memory.vectorstore.get_client`
        and asserted against Qdrant `Filter`/`FieldCondition` objects —
        both removed by this migration. This is exactly the class of
        break the open question anticipated. Fixed by rewriting that one
        block to fake `vectorstore.get_pool()` (an `asyncpg`-shaped fake
        `.fetch()`) and `conversation_memory._ensure_table`, then
        asserting tenant/user/session scoping against the actual bound
        SQL parameters (`$2`/`$3`/`$4`) instead of a Qdrant filter shape.
        All 40+ checks across both suites pass after the fix.
      - `tests/smoke_restructure.py` was **not** run — it drives a live
        HTTP server on `:8502` against the real model gateway
        (`10.48.242.4`, unreachable from this environment) and `megh_db`.
        It is an integration smoke test, not part of the standalone
        suite the deploy checklist names (`deploy/DEPLOYMENT.md`'s
        go-live checklist only requires `test_security.py`). Running it
        for real needs the actual deployment target and is out of scope
        for a dev-machine verification pass.
      - Also did a plain `import app.main` smoke check (11 routes
        registered, no import-time errors) to confirm the app boots with
        the new vectorstore wiring end to end, independent of the two
        test files.

## Explicitly Out of Scope (for this retroactive proposal)

- Building out the actual `schema_metadata` / `sql_examples` collections
  and the scheme-registry onboarding flow — that's Phase 3's job, and it
  should be scoped as its own change *once* the collection-design
  question above has a definite answer (one-table-per-collection vs. a
  generalized discriminator table), not folded into this one.
- Any change to `DATABASE_URL` / `megh_db` — explicitly untouched, and
  confirmed untouched again by re-reading the current `.env` this
  session.
- Actually exercising the rollback path (see below) — investigated only
  to the point of confirming it's mechanically plausible, not run.

## Impact

- Dependency removed: `qdrant-client` (confirmed gone from the rebuilt
  `.venv` and from `requirements.lock`). Dependency added: reliance on
  the target Postgres instance supporting `pgvector`, **and** on the
  connecting role having privilege to `CREATE EXTENSION` (Neon's default
  owner role has this; a locked-down self-hosted role may not — now
  stated explicitly in `deploy/DEPLOYMENT.md`'s prerequisites section,
  not left implicit in the connection-string change alone).
- Operational simplification: one fewer service
  (`docker-compose.yml`'s Qdrant entry removed). Real benefit given the
  "why" evidence above — the user wanted one fewer thing to run, not a
  cost/performance-driven migration.
- Rollback: the public API in `vectorstore.py` was preserved
  (`collection_count`/`recreate_collection`/`upsert`/`search`), so
  re-pointing to Qdrant would mean reverting `vectorstore.py`,
  `conversation_memory.py`'s storage internals, and the `requirements.txt`
  line, then restoring `QDRANT_URL`/`QDRANT_COLLECTION` in `.env`. This
  remains **mechanically plausible but unexercised** — it was not run
  this session either (out of scope, see above). Do not treat rollback as
  a tested, known-good path until it has actually been run once, even in
  dev.

## Recommendation

The two open questions with a real, sourced answer now (Neon
production-data risk, collection design, index-strategy honesty, `.venv`
rebuild + passing tests including one real fix) are closed. The one item
that cannot be closed from repo or session evidence — whether there is a
*deeper* strategic reason for this migration beyond the user's direct
instruction — should be put to the user directly before Phase 3 is scoped
against "collection design," since Phase 3's schema-metadata table count
and the one-table-vs-discriminator decision are cheap to change now and
expensive to change once table-level and column-level documents exist in
production.
