## Why

Asked to check the RAG feature's knowledge base — distinct from
§5.8 schema retrieval (`schema-retrieval-reranking/`, this session's
other change) — end to end, the way §5.8 just was.

Re-verified against the actual codebase and live infra before scoping
anything, per this repo's standing rule:

- **The two "knowledge base" concepts in this codebase are genuinely
  different features**, not two names for one thing —
  `docs/baseline-audit.md`'s own (stale, pre-Phase-3) §5.8 entry
  already says this: the RAG path
  (`app/rag.py`/`app/kb_ingest.py`/`megh_scheme_kb`) indexes
  **narrative FAQ/reference Markdown** (`data/reference/*.md`,
  `data/web/*.md`) answering "what is MGNREGA" / "who is eligible for
  PMAY-G" — general scheme knowledge, never SQL. Schema retrieval
  (`app/schema_retrieval.py`/`megh_schema_metadata`) indexes
  table/column **descriptions** for the SQL generator. Separate
  tables, separate ingest pipelines, separate confidence models,
  correctly never conflated in the code.
- **The RAG/KB feature itself is fully built and, as far as this
  environment can verify, working correctly** — not a gap in
  implementation. Live-checked against the real Neon `megh_scheme_kb`
  table this session (`llm.init_client()` + `vectorstore.init_pgvector()`
  both reachable from this dev sandbox):
  - Row count is **170**, exactly matching `kb_ingest._collect_chunks()`'s
    expected count from the current `data/reference/*.md` +
    `data/web/*.md` sources (69 MGNREGA / 40 PMAY-G / 29 Focus Plus /
    32 CM Elevate) — the live table is not stale against the checked-in
    source docs.
  - Scheme-scoped retrieval returns clearly on-topic, correctly-scored
    top hits for a direct factual question in **all four schemes**
    (e.g. "how many days of employment does MGNREGA guarantee" scored
    0.912 top-1 against the exact matching FAQ entry).
  - The PMAY-G/PMAY-U split (`kb_ingest.py`'s `_strip_urban_subsections`
    / re-tagging) works live, not just in theory: a PMAY-G-scoped query
    deliberately phrased around "PMAY urban" returned **zero**
    `PMAY-U`-tagged chunks — all 8 results were legitimately PMAY-G.
  - The confidence tiers fire as designed: both MGNREGA and PMAY-G's
    top-1 scores (0.912, 0.855) cleared `RAG_HIGH_CONFIDENCE` (0.84)
    and returned the verbatim-chunk path with no LLM call; Focus Plus
    (0.787) and CM Elevate (0.801) landed in the medium band as
    expected.
  - `RERANKER_ENABLED=False` and `EMBEDDING_PROVIDER=local` are
    confirmed live, matching `app/config.py`'s defaults — no drift
    between configured and running behavior.
  - **Could not verify from this sandbox:** the medium-confidence
    compose path and `answer_from_kb_multi` both need the model
    gateway (`10.48.242.4`) for `call_response_composer`, which is
    unreachable from this dev environment — consistent with every
    prior session's finding for gateway-dependent calls (see the
    retroactive pgvector migration proposal, Phase 3's task 1.6). Not
    a new gap; this environment simply cannot reach that host.
  - **Could not re-verify:** `app/rag.py`'s own comment that the
    deployed `qwen3-reranker` "inverts relevance on this KB" — that
    finding needs the same unreachable gateway to test. Left exactly
    as configured (`RERANKER_ENABLED=False`); not touched, not
    second-guessed without evidence either way.
- **The one real, concrete gap found: this feature has zero automated
  test coverage.** A full repo search
  (`grep -rl "kb_ingest\|answer_from_kb" tests/`) returns nothing —
  no `tests/test_rag.py`, no chunking test, nothing. Every sibling
  retrieval feature in this codebase has a dedicated suite
  (`test_schema_retrieval.py`, `test_entity_resolver*.py`,
  `test_query_analyzer*.py`); this one does not, despite being a live,
  user-facing answer path (`app/routers/query.py`'s edge/RAG routing)
  that this session just hand-verified works today. Nothing here
  regresses silently only because no one has run it against a change
  yet.

## What Changes

- Add `tests/test_rag.py`, mirroring `test_schema_retrieval.py`'s
  layered structure (pure-logic checks, monkeypatched-dependency
  checks, a best-effort live section that SKIPs rather than FAILs when
  the gateway/pgvector aren't reachable):
  - Offline: `kb_ingest._chunk()`'s H2/H3 splitting and the
    `general_faq.md` flat-Q&A special case; the PMAY-G→PMAY-U
    re-tagging and urban-subsection stripping in
    `kb_ingest._collect_chunks()`.
  - Monkeypatched: `rag.retrieve()` degrades to `[]` on an embedding
    failure, never raises; `answer_from_kb()`'s confidence-tier
    branching (high → verbatim chunk, medium → compose call, below
    floor → `None`) with `llm.call_embedding`/`call_response_composer`
    mocked so the tier logic is tested without live network calls.
  - Live (SKIP-safe): the four live checks this proposal's "Why"
    section already ran by hand — row count matches expected,
    scheme-scoped retrieval returns on-topic results, PMAY-G excludes
    PMAY-U content, and the confidence-tier thresholds actually fire
    on today's real data — captured as a durable, re-runnable suite
    instead of a one-off scratch script.
- No behavior change to `app/rag.py` or `app/kb_ingest.py` — this
  proposal's own live verification found the feature working as
  designed; the gap is coverage, not correctness.
- Add `openspec/specs/rag-knowledge-base/spec.md`, documenting the
  already-live behavior as a formal capability (this feature predates
  this repo's openspec adoption and was never captured as one) —
  retroactive, same spirit as schema-retrieval's spec.

## Capabilities

### New Capabilities
- `rag-knowledge-base`: scheme-scoped narrative-knowledge retrieval
  over `data/reference/*.md` + `data/web/*.md`, with confidence-tiered
  response composition — documented retroactively from already-live,
  already-verified behavior, not new functionality.

## Impact

- Affected files: new `tests/test_rag.py`, new
  `openspec/specs/rag-knowledge-base/spec.md`. No production code
  changed.
- Does not touch `RERANKER_ENABLED`, `EMBEDDING_PROVIDER`, or any
  `.env` value — see the "Reranker investigation" addendum below,
  which re-tests the one open question this proposal originally
  deferred and still leaves the flag unchanged.

## Reranker investigation (addendum, same session, follow-up to user request)

This proposal's live-verification pass above said the model gateway
was unreachable from this dev sandbox — true at the time for the
response-composer call, but the gateway itself (`10.48.242.4`) is in
fact reachable, confirmed directly (`curl`/`ping`) and by actually
exercising `llm.call_reranker`. Re-investigated the specific claim in
`app/rag.py`'s own comment — "the deployed qwen3-reranker inverts
relevance on this KB" — since this repo's rule is to re-verify a
factual claim before building on it, and this one had never actually
been re-tested, only carried forward.

**Method 1 — controlled synthetic ground truth** (3 query/document
sets, each with one exact-match doc, one loosely-related doc, and two
clearly unrelated docs): the reranker correctly ranked the two
relevant docs above the two irrelevant ones in all 3 cases (never
promoted an unrelated doc into the top 2). It did swap the *exact
match* below the *loosely related* doc in 1 of 3 cases (a PMAY-G
subsidy-amount question), so it isn't flawless — but "swaps which of
two relevant docs is first" is a materially different, much milder
failure mode than "inverts relevance," which would mean irrelevant
content outranking relevant content.

**Method 2 — real KB content**, one query per scheme, comparing the
reranker's order against the real cosine order from
`rag.retrieve()`: **3 of 4 reranked top-1 picks agreed with cosine
top-1.** The one disagreement (Focus Plus: "What is Focus Plus?")
promoted "What is the objective of FOCUS+?" above "What is FOCUS+?"
— arguably still a reasonable answer to the question, not an
unrelated result surfacing at the top.

**Conclusion: this investigation does not reproduce a clear
"inversion" on KB content.** The original claim may have been true
at the time it was written (a different gateway deployment, a
different corpus state, or a genuinely worse sample) — nothing here
proves it was wrong when written, only that it doesn't hold up
against today's data. `app/rag.py`'s comment was updated to record
both the original claim and this session's counter-evidence rather
than silently overwriting it.

**`RERANKER_ENABLED` was deliberately left `False` regardless** — 4
queries is suggestive, not a basis for flipping a flag that changes
live answer behavior for real users. That call belongs to whoever
owns this tradeoff, informed by this evidence, not decided
unilaterally from a 4-query sample. Recommended next step if this is
worth pursuing further: a larger, more systematic eval (a held-out
set of real user-style questions per scheme with human-judged
relevance) before turning this on in production — and note the two
corpora do NOT behave the same way (see
`schema-retrieval-reranking/proposal.md`'s addendum: schema-metadata
content showed a real, repeatable degradation, 0/5 in that
investigation), so this KB finding should not be read as clearing the
reranker in general, only for this corpus.

