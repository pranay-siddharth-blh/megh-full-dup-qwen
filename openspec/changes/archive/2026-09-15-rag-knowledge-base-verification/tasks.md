## 1. Live verification (done in proposal.md's "Why", recorded here for traceability)

- [x] 1.1 Confirmed `megh_scheme_kb` row count (170) matches
      `kb_ingest._collect_chunks()`'s expected count from current
      `data/` sources exactly, per-scheme.
- [x] 1.2 Confirmed scheme-scoped retrieval returns on-topic, well-
      scored top hits for all four schemes against real Neon data.
- [x] 1.3 Confirmed the PMAY-G/PMAY-U separation holds live (zero
      `PMAY-U` chunks in a PMAY-G-scoped retrieval of an
      Urban-flavored question).
- [x] 1.4 Confirmed the high/medium confidence-tier thresholds fire as
      designed against real scores (MGNREGA/PMAY-G high; Focus
      Plus/CM Elevate medium).
- [x] 1.5 Confirmed `RERANKER_ENABLED=False`/`EMBEDDING_PROVIDER=local`
      live match `app/config.py`'s defaults.
- [x] 1.6 Confirmed the medium-confidence compose path and
      `answer_from_kb_multi` cannot be live-tested from this sandbox
      (gateway `10.48.242.4` unreachable) — same known environmental
      limit as every prior session, not a new finding.

## 2. Add durable test coverage

- [x] 2.1 Wrote `tests/test_rag.py`, offline section: `kb_ingest._chunk()`
      splits a synthetic multi-H2 doc correctly, splits an oversized H2
      at H3 boundaries, and handles a flat `### Question?` FAQ doc (no
      H2 at all) as one chunk per `###`. (Test bodies had to be padded
      well past the module's own 50-char floor — and, for the H3-split
      and flat-FAQ cases, past `_CHUNK_SIZE`=1500 — or `_chunk()`
      legitimately drops/merges them; this isn't a bug, just a fixture
      sizing detail found while writing the test.)
- [x] 2.2 Same file, offline section: `kb_ingest._collect_chunks()`
      re-tags an Urban-flavored PMAY-G subsection as `PMAY-U` when it
      splits into its own chunk (bodies padded past `_CHUNK_SIZE` so
      `_chunk()` actually splits at the H3 boundary — the real-world
      case kb_ingest.py's own comment describes; a short combined
      section instead exercises the separate `_strip_urban_subsections`
      merge-and-strip path, not this one). Used a `tempfile` scratch
      dir + monkeypatched `kb_ingest._DATA_PART`/`_SOURCES` rather than
      patching `pathlib.Path.read_text` globally.
- [x] 2.3 Same file, monkeypatched section: `rag.retrieve()` returns
      `[]` (never raises) when `llm.call_embedding` raises.
- [x] 2.4 Same file, monkeypatched section: `answer_from_kb()`'s three
      branches — top score >= `RAG_HIGH_CONFIDENCE` returns the chunk
      verbatim with no composer call (asserted the mock's call count is
      0); top score in the medium band calls the (mocked) composer and
      returns its cleaned output; top score below `RAG_MEDIUM_CONFIDENCE`
      returns `None`.
- [x] 2.5 Same file, live section (SKIP-safe, same pattern as
      `test_schema_retrieval.py`'s section 3): re-asserted, as a
      durable re-runnable suite, the live findings from Group 1 against
      the real Neon `megh_scheme_kb` table.
- [x] 2.6 Ran `python tests/test_rag.py` — **18/18 PASS**, including
      all 6 live checks (pgvector was reachable this session; the
      live section's one gateway-dependent scenario — medium-confidence
      compose — was intentionally not asserted live, given 1.6's
      confirmed unreachability, so nothing there needed a SKIP path in
      practice this run).

## 3. Exit criteria

- [x] 3.1 `tests/test_rag.py` passes — **18/18**, count as above.
- [x] 3.2 Confirmed via `git diff --stat`/`git status`: this change
      added only `tests/test_rag.py` and
      `openspec/changes/rag-knowledge-base-verification/` — no file
      under `app/` was touched.

## 4. Reranker investigation (follow-up, same session, user-requested)

- [x] 4.1 Found the model gateway (`10.48.242.4`) is actually
      reachable from this dev sandbox — re-tested `app/rag.py`'s own
      claim that "the deployed qwen3-reranker inverts relevance on
      this KB" with 3 controlled synthetic ground-truth cases plus 4
      real per-scheme KB queries. Result: 3/4 real-query top-1 picks
      agreed with cosine order, and the synthetic cases never promoted
      an irrelevant doc above a relevant one — this sample does not
      reproduce a clear inversion (full data in proposal.md's
      "Reranker investigation" addendum).
- [x] 4.2 Updated the inline comment in `app/rag.py` (the
      `RERANKER_ENABLED` branch) to record both the original claim and
      this session's counter-evidence, rather than silently
      overwriting or silently ignoring it.
- [x] 4.3 Deliberately left `RERANKER_ENABLED=False` unchanged — a
      4-query sample is evidence worth recording, not a basis for
      flipping a flag that changes live answer behavior; that call is
      flagged for the human who owns this tradeoff.
- [x] 4.4 Re-ran `tests/test_rag.py` after the comment-only edit —
      still 18/18 PASS, no regression.

## 5. Targeted re-test of the original documented failure (follow-up, user-requested "implement it completely")

- [x] 5.1 Group 4's "3/4 agree with cosine" result used 4 *varied* real
      queries, not a re-test of the *specific* case the original
      2026-08-29 comment named ("what documents are required" ranking
      below "where to find info"). Re-ran that exact query pattern per
      scheme before treating the earlier finding as settled, per this
      repo's re-verify rule. Result: does **not** reproduce for
      PMAY-G, MGNREGA, or Focus Plus (reranked top-1 is the correct
      "documents required" chunk in all three, and cosine top-1 already
      was too — reranking didn't need to fix anything there) but
      **does** reproduce, close to verbatim, for CM Elevate: cosine
      top-1 for that scheme was `(intro)` (the documents-required
      chunk sat at cosine rank #6 of 8), and reranking promoted "14.
      Where to Find Authoritative, Current Information" to #1 instead
      of surfacing the actual `7.1 Required Documents` content.
- [x] 5.2 Corrected the picture from this proposal's earlier addendum:
      the evidence is corpus-*and-scheme* inconsistent, not a clean
      "doesn't reproduce" result — enabling the reranker would trade a
      confirmed-safe outcome on 3 schemes for a confirmed, reproduced
      regression on the 4th.

## 6. Split the shared reranker flag (follow-up, same "implement it completely" request)

- [x] 6.1 `app/config.py`'s `RERANKER_ENABLED` was replaced with two
      independent flags (implemented in the sibling
      `schema-retrieval-reranking` change, task group 5, since
      `app/config.py` is shared): `RAG_RERANKER_ENABLED` and
      `SCHEMA_RETRIEVAL_RERANKER_ENABLED`, both defaulting `False`.
- [x] 6.2 `app/rag.py` now reads `RAG_RERANKER_ENABLED`; its inline
      comment was rewritten to cite both the first (4-query) and
      second (targeted, per-scheme) investigations from group 5 above,
      rather than only the first.
- [x] 6.3 Added reranker-path test coverage to `tests/test_rag.py`
      (new section 5, "RERANKER PATH (RAG_RERANKER_ENABLED)"),
      matching `test_schema_retrieval.py`'s pattern: disabled ->
      cosine order truncated to `RAG_RERANK_TOP_N`; enabled (mocked
      reranker) -> output follows the mocked reranked order. A
      reranker-failure-degrades check was not duplicated here since
      `rag.py`'s reranked branch has no separate try/except around
      `llm.call_reranker` the way `schema_retrieval.py` does — noted
      as a real asymmetry between the two modules, not fixed by this
      task group (out of scope for a flag-split change; flagged for
      whoever next touches `rag.py`'s reranker branch).
- [x] 6.4 Deliberately left `RAG_RERANKER_ENABLED=False` — group 5's
      corrected finding (reproduced regression on CM Elevate) argues
      against enabling it, not for it.
- [x] 6.5 Ran `python tests/test_rag.py` — **20/20 PASS** (18 previous
      + 2 new reranker-path checks).
