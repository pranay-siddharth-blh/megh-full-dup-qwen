## Why

The user asked to "complete §5.8 end to end," pointing at the original
Grant Thornton proposal text, which specifies: embed table/column
descriptions offline, embed the query at retrieval time, pre-filter by
scheme, pull top-30 candidates, then **cross-encoder rerank to a final
top-8** — with Qdrant, BGE-large/multilingual-E5, and
sentence-transformers named as the tools.

Re-checked against the actual codebase before scoping this (per the
repo's re-verify-before-implementing rule) rather than taking the
original doc's tool list at face value:

- **The scheme pre-filter and top-K retrieval already exist and are
  correctly implemented** — Phase 3 (`app/schema_retrieval.py`,
  archived at `openspec/changes/archive/2026-09-11-phase-3-schema-retrieval-join-discovery/`)
  already does embed → SQL `WHERE scheme_id = ANY(...) OR shared` →
  cosine rank → top-N. `openspec/specs/schema-retrieval/spec.md`
  already documents and tests this.
- **Qdrant, BGE-large, multilingual-E5, and sentence-transformers are
  not available tools for this change.** A firm, direct user
  instruction already replaced Qdrant with Postgres/pgvector (Neon) for
  every vector collection, schema-metadata included (see
  `openspec/changes/archive/2026-09-11-retroactive-qdrant-to-pgvector-migration/proposal.md`,
  which quotes the three chat messages verbatim). Embeddings already
  run through `app.llm.call_embedding`, which is a single switchable
  point (`EMBEDDING_PROVIDER=local` → `fastembed`/bge-small CPU model,
  or `gateway` → the STPI-hosted `qwen3-embedding` deployment named in
  `.env`). There is no BGE-large or multilingual-E5 deployment anywhere
  in `.env`, and no `sentence-transformers` cross-encoder is installed
  (`requirements.txt` has no such dependency). The STPI gateway's own
  reranker (`qwen3-reranker`, `RERANKER_BASE_URL`/`RERANKER_MODEL`/
  `RERANKER_API_KEY` in `.env`) is the cross-encoder-equivalent tool
  actually available, and `app.llm.call_reranker` already wraps it
  (built for the RAG/KB path).
- **The one genuinely missing piece is the two-stage retrieve-wide/
  rerank-narrow shape itself.** `schema_retrieval.retrieve()` today is
  single-stage: pull `SCHEMA_RETRIEVAL_TOP_K` (5) candidates straight
  from pgvector by cosine distance and return them as-is. There is no
  wider candidate pool and no reranking call in this path at all —
  unlike the RAG/KB path (`app/rag.py`), which already has the
  retrieve-then-rerank shape (`RAG_TOP_K` → `llm.call_reranker` →
  `RAG_RERANK_TOP_N`), gated behind `RERANKER_ENABLED`.
- **Important prior finding that bears directly on this change:**
  `app/rag.py`'s own comment (line 96-98) and `RERANKER_ENABLED`'s
  default of `False` record that **the deployed `qwen3-reranker`
  inverts relevance on the KB corpus** — a real, previously-observed
  failure mode, not a hypothetical. This dev sandbox cannot reach the
  gateway (`10.48.242.4`, confirmed unreachable in the retroactive
  pgvector proposal's own verification pass) to test whether the same
  inversion reproduces on schema-metadata content (short structured
  table/column descriptions, a different shape than KB narrative
  chunks). This change cannot resolve that open question from this
  environment — it wires reranking in behind the same opt-in,
  default-off posture, and flags live verification against real
  schema-metadata content as a prerequisite before anyone flips it on
  for this path.

## What Changes

- Widen `schema_retrieval.retrieve()` to a two-stage shape, matching
  the spec's "top-30 candidates, cross-encoder reranks to top-8":
  pull `SCHEMA_RETRIEVAL_CANDIDATE_K` (new setting, default 30)
  candidates from pgvector, then, when `RERANKER_ENABLED` is true,
  rerank via `llm.call_reranker` and keep the top
  `SCHEMA_RETRIEVAL_TOP_K` (default changed 5 → 8, matching the spec's
  "top-8"). When `RERANKER_ENABLED` is false (the default, for the
  reason above), behavior is the same shape as today — cosine order,
  truncated to `SCHEMA_RETRIEVAL_TOP_K` — just drawn from the wider
  30-candidate pool instead of a direct top-5 query, and returning 8
  instead of 5.
- Reuse the existing `RERANKER_ENABLED` flag rather than adding a
  second, schema-specific one: it is the same gateway deployment behind
  both call sites, and splitting the flag now would be speculative
  ahead of any evidence the inversion behavior actually differs by
  corpus. If live verification later shows schema-metadata content
  reranks correctly while KB content still inverts (or vice versa),
  splitting the flag at that point is a small change — not preemptively
  justified today.
- No change to embeddings: `call_embedding` already routes through the
  single `EMBEDDING_PROVIDER` switch; this change does not flip it from
  `local` to `gateway` — that switch also affects the semantic
  near-duplicate cache and the RAG/KB path, a wider blast radius than
  this schema-retrieval-scoped change should decide unilaterally. Left
  exactly as configured today.
- No change to Qdrant, BGE, multilingual-E5, or sentence-transformers —
  none are reintroduced; the pgvector + STPI-gateway foundation from
  the retroactive migration stands.

## Capabilities

### Modified Capabilities
- `schema-retrieval`: adds a reranking stage to the existing scheme-
  prefiltered retrieval requirement (spec delta below).

## Impact

- Affected files: `app/schema_retrieval.py` (two-stage retrieve),
  `app/config.py` (`SCHEMA_RETRIEVAL_CANDIDATE_K` new setting,
  `SCHEMA_RETRIEVAL_TOP_K` default 5 → 8), `tests/test_schema_retrieval.py`
  (new reranker-path checks).
- Behavior change even with the reranker off: `retrieve()` now returns
  up to 8 candidates instead of 5 by default (the spec's stated
  top-8), and reads from a 30-candidate pgvector pool instead of a
  direct top-5 query — slightly more pgvector work per call, still a
  single indexed query. Flagged here since it changes prompt content
  even for schema-retrieval callers with the reranker untouched.
- No change to the scheme pre-filter itself (still the SQL `WHERE`
  clause, unchanged) — this only adds a stage after the pre-filter.
- `RERANKER_ENABLED=true` (when someone flips it) now affects both the
  RAG/KB path and schema retrieval simultaneously, since they share the
  flag — stated explicitly as a joint blast radius, not left implicit.

## Reranker investigation (addendum, same session, follow-up to user request)

The "Why" section above said this dev sandbox couldn't reach the model
gateway to test the reranker. That was true for the compose/response
model at the time it was written, but the gateway itself
(`10.48.242.4`) is in fact reachable from here — confirmed with a
direct `curl`/`ping` and, more usefully, by actually calling
`llm.call_reranker` against real schema-metadata content pulled live
from `megh_schema_metadata`. Re-verifying this before leaving the
open question unresolved, per this repo's standing rule.

**Method:** for 5 real questions across all 4 piloted schemes, called
`schema_retrieval.retrieve()` to get the real cosine-ranked candidate
pool, then called `llm.call_reranker` on that same pool and compared
orderings.

**Result: 0/5 reranked top-1 picks agreed with cosine top-1**, and at
least 2 of the 5 are clear, not merely different, degradations:

- *"which CM Elevate applications are pending verification"* — cosine
  top-1 was `curated.v_cm_elevate.data_verified` (a column literally
  named for verification status, score 0.687); the reranker demoted
  it to #2 behind `curated.dim_cm_elevate_scheme` (a generic scheme
  dimension table, cosine score 0.586).
- *"number of houses completed under PMAY Gramin"* — cosine top-3 was
  `curated.fact_pmay_house` (the actual fact table for houses); the
  reranker pushed it to **dead last** (#8 of 8), promoting
  `curated.v_pmay.status_key` (the lowest-scoring cosine candidate,
  0.491) to #1.
- The other 3 (CM Elevate disbursement, MGNREGA person-days, Focus
  Plus disbursement-by-district) were more mixed — plausible
  arguments exist for some of the reranker's reorderings there — but
  none of the 5 agreed with cosine top-1, and the two above are
  unambiguous quality losses, not just "different judgment."

**Conclusion:** this is real, repeatable evidence — not just
unverified caution — that the deployed `qwen3-reranker` currently
degrades ranking quality on schema-metadata content specifically.
`RERANKER_ENABLED` stays `False` (no code change from this
investigation — the existing default was already correct). The
inline comment in `app/schema_retrieval.py` was updated to cite this
finding directly instead of only gesturing at "needs live
verification," since that verification has now happened.

Sample size caveat: 5 queries is real evidence, not a rigorous
benchmark — enough to keep the flag off with confidence, not enough
to claim a precise failure rate. A larger eval would be needed before
this could inform, say, a decision to try a different reranker model.

