# RAG Plan: Status Report (2026-10-24)

Progress against `new_docs/RAG_Plan_Reference_Notes_2026-10-24_with_fixes.docx`, with each status checked in code, Qdrant or a test run on 2026-10-24.

## Summary

The document lists **29 problems** (Part A: 5, Part B: 5, Part C: 7, Part E: 12).

| Status | Count |
|---|---|
| Solved | **0** |
| Partly solved | **2** (A5, E10) |
| Already working before (rule to keep) | **1** (C6) |
| Not started | **26** |

Today's work went into a groundwork task that the plan depends on: **moving the whole project to 1024-dim embeddings safely.** It finished that move and fixed 4 problems found along the way. The document's problems themselves are still open.

## Part A: Problems we found

| # | Problem | Status | Notes |
|---|---|---|---|
| A1 | Metadata collections never read; build our own metadata collection | Not started | The blocker is gone: the embedding model is settled (1024, qwen3). Collection `megh_metric_catalog_v1` not built yet |
| A2 | Every layer decides from the wording (needs a query plan) | Not started | |
| A3 | Wikipedia pages in the KB; CLAUDE.md names the wrong folder | Not started | `data/web/*_Wikipedia.md` still there; CLAUDE.md still says `data/reference/` (lines 13, 129); official documents not received |
| A4 | Routing bugs between knowledge and data | Not started | New example logged: KI-404 ("How does MGNREGA job card registration work?" goes to DATA) |
| A5 | Clean up unused Qdrant collections | **Partly** | Snapshots of all 7 of our collections taken (`Downloads/qdrant_backup_2026-10-24`). Nothing deleted, by design |

## Part B: What RAG can fix

| # | Item | Status |
|---|---|---|
| B1 | Metric and synonym detection | Not started |
| B2 | Scheme from vocabulary | Not started |
| B3 | Data vs knowledge from retrieval scores | Not started |
| B4 | Prompt pruning | Not started |
| B5 | Few-shot examples chosen by meaning | Not started |

## Part C: Fixed-code rules

| # | Item | Status | Notes |
|---|---|---|---|
| C1 | Years ("FY24", "last year") | Not started | `c12_answer_numbers.py:800` still maps "fy24" to FY 2024-25 |
| C2 | Number words ("five highest") | Not started | |
| C3 | Place names and hierarchy | Not started | KI-368 (Demdema block read as a village) open |
| C4 | Follow-ups carry filters | Not started | Two more found today: KI-405 (scheme switch during a pause), KI-406 (year dropped) |
| C5 | Units and number checks | Not started | |
| C6 | Collision rules (Focus, CM Elevate D-064) | Already working | Kept unchanged |
| C7 | Random SQL variation (seed, temperature) | Not started | `app/llm.py` sends no seed |

## Part E: Fixes layer by layer

| # | Layer | Status | Notes |
|---|---|---|---|
| E1 | Query plan node | Not started | |
| E2 | Edge layer and guardrail | Not started | |
| E3 | Follow-ups and context | Not started | Session-less API calls still share `day-<user>-<date>` (`routers/query.py:154`); U5 decision pending |
| E4 | Intent classifier | Not started | |
| E5 | Scheme routing | Not started | |
| E6 | Entities: places and years | Not started | |
| E7 | SQL generation (catalogue, compiler, seed) | Not started | |
| E8 | Verifier and repair loop | Not started | |
| E9 | Composer | Not started | |
| E10 | Cache, memory and orchestration | **Partly** | Semantic cache now also matches rank direction, N, status and measure (KI-401, fixed today by the D-067 session). Memory search improved (KI-408). Redis and plan-keyed cache not done |
| E11 | UI | Not started | |
| E12 | Security and data | Not started | `raw_uc/` still not gitignored; Qdrant has no API key; gateway CA file missing; token in the git remote; bank CSV in history |

## Done today (groundwork, not in the document's list)

| Item | Result |
|---|---|
| Embeddings moved to 1024 (D-067 completed) | KB `megh_scheme_kb_v4` and memory `megh_conversation_memory_1024` live on :8401 |
| Qdrant backup | 7 collections, about 66 MB, outside the repo |
| KI-402 | Startup vector-size check: wrong-size KB rebuilt; wrong-size memory never written to or deleted |
| KI-403 | 30-day purge covers both memory collections |
| Memory migration | 12,046 chats re-embedded to 1024; recall 20/20 |
| KI-408 | Memory search exact plus payload indexes: 60/60 vs 58/60; 0 turns missed |
| New issues logged | KI-404, KI-405, KI-406, KI-407 |
| Tests | pytest 3,663 passed, 0 failed; scripts 14/14; live context 103/107 (4 failures identical on 384, so they predate the change) |

## Needed from the user or others

- Commit the current work (nothing is committed).
- Decision U5: should a follow-up keep the previous year (KI-406)?
- Decision KI-407: is the CM Elevate test check stale under D-064?
- The ingestion team: are the `semantic` tables final (needed for A1)?
- Official MGNREGA and PMAY-G documents (needed for A3).
- Server admin: Qdrant API key and firewall, gateway CA file, `.env` on the deploy servers.
