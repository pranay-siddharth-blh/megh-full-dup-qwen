## 1. Two-stage retrieve + optional rerank

- [x] 1.1 Added `SCHEMA_RETRIEVAL_CANDIDATE_K: int = 30` to
      `app/config.py`; changed `SCHEMA_RETRIEVAL_TOP_K` default from 5
      to 8.
- [x] 1.2 Rewrote `schema_retrieval.retrieve()`: queries
      `vectorstore.search_schema_metadata` with
      `top_k=SCHEMA_RETRIEVAL_CANDIDATE_K`. When `RERANKER_ENABLED` is
      false, returns the first `SCHEMA_RETRIEVAL_TOP_K` of that
      (unchanged cosine order). When true, calls `llm.call_reranker`
      with the question and each candidate's `content`, and returns
      the top `SCHEMA_RETRIEVAL_TOP_K` in reranked order — wrapped so a
      reranker exception degrades to the pre-rerank cosine order
      (never raises, matching this module's existing "additive, never
      gating" stance for the embedding-failure and empty-index cases).
- [x] 1.3 Extended `tests/test_schema_retrieval.py` (new section
      "2b. TWO-STAGE RETRIEVE/RERANK"): (a) the pgvector query is
      called with `top_k=SCHEMA_RETRIEVAL_CANDIDATE_K` (30), not
      `TOP_K`, via the monkeypatched-pool technique already used by the
      pre-filter test, driven through `retrieve()` itself rather than
      calling `vectorstore.search_schema_metadata` directly; (b) with
      `RERANKER_ENABLED=False` (default), a 30-candidate mocked pool is
      truncated to 8 in cosine order; (c) with `RERANKER_ENABLED=True`
      and a mocked `llm.call_reranker` that deliberately reverses
      order, `retrieve()`'s output follows the mocked reranked order,
      not cosine order; (d) a mocked `llm.call_reranker` that raises
      degrades to the pre-rerank cosine order, truncated to 8, not an
      exception.
- [x] 1.4 Ran `python tests/test_schema_retrieval.py` — **12/12 PASS**
      (4 pre-existing group-1/2 checks + 4 new group-2b checks + 4 live
      checks against the real Neon `megh_schema_metadata` table, all
      passing — Neon is reachable from this dev sandbox, consistent
      with prior sessions' findings). Re-ran
      `tests/test_pipeline_schema_retrieval.py` — **9/9 PASS**, no
      regression (it only exercises the shape of `retrieve()`'s return
      value, which is unchanged: same dict keys, just up to 8 items
      instead of 5, sourced from a wider pool).

## 2. Exit criteria

- [x] 2.1 Both suites from 1.4 pass — 12/12 and 9/9, counts as above.
- [x] 2.2 Confirmed via `git diff --stat`: only `app/config.py`,
      `app/schema_retrieval.py`, and `tests/test_schema_retrieval.py`
      were touched by this change. (The repo's working tree carries a
      large amount of pre-existing, unrelated uncommitted work spanning
      many other files/phases — confirmed those diffs predate this
      session and were left untouched, per the repo's own
      mixed-concern-files convention.) `app/pipeline.py`,
      `app/prompt_builder.py`, `app/vectorstore.py`, and the scheme
      pre-filter SQL are untouched by this change specifically.
- [x] 2.3 Left `RERANKER_ENABLED` at its existing default (`False`) in
      `.env`/`.env.example` — not changed by this task group, per the
      reasoning in proposal.md.

## 4. Reranker investigation (follow-up, same session, user-requested)

- [x] 4.1 Found the model gateway (`10.48.242.4`) is actually
      reachable from this dev sandbox (contradicting the assumption in
      group 2) — live-tested `llm.call_reranker` against 5 real
      schema-metadata queries across all 4 piloted schemes, comparing
      reranked order to cosine order. **0/5 agreed on top-1**,
      including 2 clear degradations (see proposal.md's "Reranker
      investigation" addendum for the full data). Confirms — with
      real evidence now, not just caution — that `RERANKER_ENABLED`
      should stay `False` for schema retrieval.
- [x] 4.2 Updated the inline comment in `app/schema_retrieval.py`
      (the `RERANKER_ENABLED` branch) to cite this finding directly.
      No behavior change — `RERANKER_ENABLED` untouched.
- [x] 4.3 Re-ran `tests/test_schema_retrieval.py` after the
      comment-only edit — still 12/12 PASS, no regression.

## 5. Split the shared reranker flag (follow-up, user-requested "implement it completely")

- [x] 5.1 Replaced the single `RERANKER_ENABLED` in `app/config.py` with
      two independent flags: `RAG_RERANKER_ENABLED` (default `False`)
      and `SCHEMA_RETRIEVAL_RERANKER_ENABLED` (default `False`) — the
      "not preemptively justified today" caveat in this proposal's
      original "What Changes" section is now resolved: the two
      investigations found the corpora genuinely behave differently, so
      a shared flag could not represent that. `RERANKER_MODEL`/
      `RERANKER_BASE_URL`/`RERANKER_API_KEY`/`RERANKER_TIMEOUT_SECONDS`
      stay shared — same gateway deployment, only the on/off decision
      differs per corpus.
- [x] 5.2 `app/schema_retrieval.py` now reads
      `SCHEMA_RETRIEVAL_RERANKER_ENABLED`; `app/rag.py` now reads
      `RAG_RERANKER_ENABLED` (that file's own task group is in the
      sibling `rag-knowledge-base-verification` change).
- [x] 5.3 Updated `tests/test_schema_retrieval.py`'s three rerank-path
      checks (disabled/enabled/failure) to set
      `SCHEMA_RETRIEVAL_RERANKER_ENABLED` instead of the removed shared
      flag.
- [x] 5.4 Deliberately did NOT flip `SCHEMA_RETRIEVAL_RERANKER_ENABLED`
      to `True` — group 4's evidence (0/5 agreement, two clear
      degradations) still stands and wasn't revisited by this task
      group; the split makes independent control possible, it doesn't
      by itself change the decision for this corpus.
- [x] 5.5 Ran `python tests/test_schema_retrieval.py` — **12/12 PASS**
      after the rename.
