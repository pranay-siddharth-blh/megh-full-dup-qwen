## Context

`app/vectorstore.py` (post-pgvector migration) holds two dedicated
tables today, each with its own columns/index, no `kind` discriminator:
`megh_scheme_kb` (`RAG_KB_TABLE`) for narrative FAQ/reference docs, and
`megh_conversation_memory` (`CONTEXT_MEMORY_TABLE`) for semantic
conversation history. Embeddings are `local_embed.py`'s fastembed
`BAAI/bge-small-en-v1.5`, 384-dim, when `EMBEDDING_PROVIDER=local`
(the default); `llm.call_embedding()` is the single entry point
regardless of provider, so new code embeds through that, not through
`local_embed` directly, and sizes new tables from `local_embed.dim()`
(or `len(vectors[0])`, matching `kb_ingest.ingest_kb`'s pattern) rather
than a hardcoded 384.

`app/prompt_builder.py` already composes the SQL-generation prompt from
four sources in order: `schema_context.py` (hand-written backbone),
`schema_introspect.live_columns()`/`live_fks()` (live catalog), 
`schema_introspect.catalog_block()` (SME `semantic.*` descriptions), and
`annotations.py` (few-shot examples + prohibited joins + resolved
entities). This phase adds a fifth and sixth source — schema-retrieval
candidates and an explicit join-path block — without touching the
existing four; see proposal.md for why the existing four are not being
replaced.

Every scheme's curated `foreign_key_augmentation.yaml` already has a
`nodes` section (role, grain, `aggregate_before_reporting` flags) and an
`edges` section with an explicit `on_clause` per edge (`null` for
prohibited ones) and a `join_graph` adjacency list. All edges today are
either `declared: true` (real FK) or `is_prohibited: true` — confirmed
by scanning all four files. `app/annotations.py:81-91` loads this file
per scheme into `_fk_cache[scheme]` already; only
`prohibited_joins_text()` (`annotations.py:208-219`) reads from it at
runtime.

## Goals / Non-Goals

**Goals:**
- Add scheme-scoped semantic retrieval as a supplement to, not a
  replacement for, the existing classifier + `schema_context.py` path.
- Add runtime join-path computation (BFS shortest path) over declared
  FKs + curated YAML edges, with an explicit fan-out guard and
  clarification fallback.
- Keep the two new vector tables consistent with the existing
  one-table-per-collection pattern.
- Prove the "onboarding a new scheme needs zero pipeline-code changes"
  claim with a real second scheme (Focus Plus), not just document it.

**Non-Goals:**
- Replacing or deprecating `schema_context.py`'s hand-written blocks —
  they encode judgment (hazard rules, business vocabulary) that cannot
  be introspected or embedded away, and stay the primary source for the
  4 schemes that already have them.
- Adding NetworkX or any other new runtime dependency — every scheme's
  graph is small enough (under 10 nodes today) that a plain BFS over a
  `dict[str, list[str]]` adjacency list is proportionate. Revisit only
  if a future scheme's graph is measured to actually need weighted or
  more complex path search.
- Full schema-metadata description coverage for MGNREGA/PMAY-G (already
  covered by `schema_context.py`) or for schemes beyond the four that
  exist — SME-paced, ongoing, not gated on this phase.
- Any change to `DATABASE_URL`, connection roles, or pools.

## Decisions

**One table per collection, not a `kind`-discriminated table.**
`megh_schema_metadata(id uuid pk, scheme_id text, granularity text,
ref text, shared boolean, content text, embedding vector(dim), metadata
jsonb, updated_at timestamptz)` and `megh_sql_examples(id uuid pk,
scheme_id text, question text, sql text, is_answerable boolean, reason
text, content text, embedding vector(dim), updated_at timestamptz)` —
two new tables in `app/vectorstore.py`, mirroring `recreate_collection`/
`upsert`/`search`'s existing shape for `megh_scheme_kb`. Alternative
considered: a single `rag_documents` table with a `kind` column
spanning all three collections. Rejected — inconsistent with the two
collections that already exist as dedicated tables (the retroactive
pgvector proposal chose one-table-per-collection deliberately, mirroring
Qdrant's separate-collections model), and the KB table's payload shape
(`doc`, `heading`, `source_type`) doesn't share a natural row shape with
schema-metadata's (`granularity`, `ref`) or SQL-example's
(`question`/`sql`) — a shared table would need nullable columns for
fields only some rows use.

**In-house BFS shortest path, no NetworkX.** `app/join_graph.py` builds
a `dict[str, list[tuple[str, str]]]` adjacency list (node -> [(neighbor,
edge_key)]) at startup from `schema_introspect.live_fks()` (already
loaded) plus each scheme's curated YAML `edges`/`join_graph` sections
(all either real FKs, already covered by `live_fks()`, or explicit
prohibitions — prohibited edges are excluded from the graph entirely,
not just penalized). Plain BFS finds the shortest path between two
required tables; each edge carries its `on_clause` (or is synthesized
from `live_fks()`'s `from_column`/`to_column` when the edge came from
there). Alternative considered: NetworkX, as the original scope
sketch assumed. Rejected for now — every scheme's graph today has under
10 nodes and under 20 edges; NetworkX's weighted/multigraph machinery
buys nothing at this size and is a dependency to justify, install, and
maintain for no measured benefit. If a future scheme's graph is
materially larger or needs weighted paths, revisit then.

**Join discovery gates SQL generation only where it has a genuine
pre-generation signal to gate on; otherwise it is an additive prompt
hint, the same enforcement tier as the existing PROHIBITED JOINS
block.** Implementing this surfaced a real constraint: nothing in the
current pipeline determines "which tables does this question need"
before the SQL generator runs — table selection is something the
generator itself decides while writing SQL, not a prior pipeline step.
That means a hard "no invented joins" gate would require parsing the
generator's *output* SQL to find which tables it actually joined —
which risks false positives on this codebase's own sanctioned pattern
of aggregating each side into a CTE first and joining the CTEs (every
cross-scheme worked example in `schema_context.py` does exactly this),
and would need a real SQL parser this codebase doesn't have. Checked:
the existing PROHIBITED JOINS mechanism has the identical limitation
already — it is a strongly-worded prompt instruction
(`annotations.prohibited_joins_text()`), never enforced by parsing the
SQL that comes back. Join discovery matches that same, already-accepted
tier for the common case, and only hard-gates in one narrow, honest
case: when `schema_retrieval.retrieve()` itself returns 2+ distinct
table-granularity candidates for the active scheme(s) — a real,
already-computed, pre-generation signal, not an invented one — and
`join_graph.find_join_path()` says those specific tables have no valid
path or trip the fan-out guard, `pipeline.generate_sql()` raises
`ClarificationNeeded` before ever calling the SQL generator. When fewer
than 2 such candidates exist (the common case today, since both CM
Elevate and Focus Plus have exactly one fact table each — the guard
cannot even arise within either scheme alone, only across schemes) or
the path is valid, the result is folded into the prompt as an additive
"REQUIRED JOIN(S)" hint alongside the existing REAL FOREIGN KEYS and
PROHIBITED JOINS blocks — never silently dropped, never a false claim
of a stronger guarantee than the codebase's existing mechanism already
provides.

**Fan-out guard.** After BFS finds a path between two tables both
tagged `role: fact` in the YAML `nodes` section, check whether the path
passes through at least one node tagged `role: dimension`. If not (a
direct or dimension-free fact-to-fact path), the join-path function
returns a guard flag instead of the path, and the pipeline treats this
the same as a no-path result (clarification), never a silent join. This
catches exactly the case `foreign_key_augmentation.yaml`'s own comment
warns about ("no shared grain... a row-level join inflates totals").

**Scheme registry reload is a manual admin-triggered endpoint, not a
periodic background refresh.** Checked both existing YAML-cache loaders
this design was originally said to mirror (`entity_resolver.load_all()`,
`annotations.load_all()`) — neither has any refresh mechanism at all,
periodic or otherwise; both load once at startup. The actual precedent
for "reload without a redeploy" in this codebase is
`app/routers/rag.py`'s `POST /api/rag/reingest`, which calls
`kb_ingest.ingest_kb(force=True)` on an admin-only route. The scheme
registry loader follows that same shape: `load_all()` at startup, plus
a `POST /api/rag/reload-scheme-registry`-style admin route that calls
it again. No new automatic-refresh mechanism is introduced.

**Schema retrieval is additive, not gating.** `app/schema_retrieval.py`'s
`retrieve(question, scheme_ids)` returns top-N schema-metadata
candidates or an empty list (e.g., before the pilot scheme's index is
built, or on an embedding-service failure) — `app/prompt_builder.py`
appends a "RETRIEVED SCHEMA NOTES" block only when non-empty, so schemes
without indexed metadata (MGNREGA, PMAY-G initially) see zero change in
prompt behavior. This keeps the phase's blast radius limited to the two
piloted schemes until more are indexed.

## Risks / Trade-offs

- [Two more startup-time reads/pools against `megh_db` and the vector
  DB] → both are read-only and best-effort exactly like
  `schema_introspect.load()` already is (never blocks startup, logs and
  falls back on failure) — `join_graph`'s startup build follows the same
  try/except-and-log pattern.
- [Fan-out guard could produce false positives if a scheme's `nodes`
  section is missing `role` tags] → treat a missing/unknown `role` as
  "not a fact" conservatively for the guard's purposes (i.e., don't
  block), but log a warning so a curation gap is visible rather than
  silently under-guarding; verified against all four schemes' YAML
  `nodes` sections having `role` on every fact entry today.
- [Retrieval quality on a 384-dim local embedding model for short schema
  descriptions] → mitigated by keeping retrieval additive (see Decisions)
  rather than gating SQL generation on it; a bad ranking degrades to "no
  extra context," not a wrong query.
- [Onboarding proof (Focus Plus) could reveal a pipeline-code dependency
  the design didn't anticipate] → task 4.2 is the explicit acceptance
  test for this; if it fails, that's a real design gap to fix before
  closing the phase, not a result to paper over.

## Migration Plan

1. Create the two new tables (idempotent `CREATE TABLE IF NOT EXISTS`
   equivalent — actually `DROP`+`CREATE` on rebuild, matching
   `recreate_collection`'s existing pattern, gated behind an explicit
   ingest/rebuild call, never run implicitly).
2. Index CM Elevate's schema metadata; verify retrieval end-to-end.
3. Wire retrieval + join-path into `pipeline.py` behind the "additive,
   empty-list-safe" behavior above — no behavior change for MGNREGA/
   PMAY-G/Focus Plus until their metadata is indexed too.
4. Index Focus Plus as the onboarding proof; confirm zero pipeline code
   changes were needed.
5. Rollback: both new tables and the two new modules are additive; if
   retrieval or join-path output ever looks worse than the pre-phase
   baseline for a piloted scheme, the pipeline wiring is a single call
   site in `pipeline.py` to revert (feature-flag not needed — the
   additive/empty-safe design means simply not indexing a scheme keeps
   it on old behavior).
