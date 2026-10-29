# RAG Plan: Status Report (2026-10-24, end of day)

Progress against `new_docs/RAG_Plan_Reference_Notes_2026-10-24_with_fixes.docx`, with each status checked in code, Qdrant or a test run on 2026-10-24.

## 1. Summary

The document lists **29 problems** (Part A: 5, Part B: 5, Part C: 7, Part E: 12).

| Status | Count | Items |
|---|---|---|
| Solved | **2** | C2 (number words); C7 (measured: SQL already stable, no change needed) |
| Partly solved | **12** | A2, A3, A5, B1, C1, C4, C5, E3, E6, E9, E10, E12 |
| Already working before (rule to keep) | **1** | C6 |
| Not started | **14** | A1, A4, B2-B5, C3, E1, E2, E4, E5, E7, E8, E11 |

Most of the day went into **groundwork the plan depends on**: moving the whole project to 1024-dim embeddings safely, fixing what that move exposed, and measuring where accuracy stands.

## 2. Done today (all tested; committed unless marked)

| # | What | Result | Commit |
|---|---|---|---|
| 1 | Qdrant backup | 7 of our collections (about 66 MB) saved outside the repo: `Downloads/qdrant_backup_2026-10-24` | — |
| 2 | 1024-dim embeddings completed (D-067) | KB `megh_scheme_kb_v4`, memory `megh_conversation_memory_1024`, live on :8401 | `9c7c67c` |
| 3 | KI-402: vector-size guard | Wrong-size KB rebuilt at startup; wrong-size memory never written or deleted | `9c7c67c` |
| 4 | KI-403: retention for both memory collections | The old 384 chats are still deleted after 30 days | `9c7c67c` |
| 5 | Memory migration | 12,046 chats re-embedded to 1024; recall 20/20 | `9c7c67c` |
| 6 | KI-408: exact memory search + indexes | 60/60 vs a perfect search (was 58/60); same speed | `9c7c67c` |
| 7 | `.gitignore`: `raw_uc/`, `new_docs/*.csv`, Word lock files | Personal data cannot be committed by accident (E12, part) | `0aa135c` |
| 8 | Docs: KB folder is `data/incoming/<scheme>/` | CLAUDE.md, ARCHITECTURE, AI_PIPELINE, SCHEMES corrected (A3, part) | `dd8b58b` |
| 9 | Data golden set re-run | **54.1% (40/74), 0 wrong answers, 34 asked back** (see section 4) | not committed |
| 10 | Review: golden sets, metadata idea, alternatives | `new_docs/Golden_Test_Set_and_Approach_Review_2026-10-24.md` | not committed |

**Tests after the code changes:** pytest **3,663 passed, 0 failed**; scripts **14/14**; live multi-turn suite **103/107**. The same 4 checks fail on the old 384 settings, so they predate today's changes.

## 3. The 29 problems: item by item

### Part A: Problems found

| # | Problem | Status | Detail |
|---|---|---|---|
| A1 | Metadata never read; build our own collection | Not started | Blocker removed (embedding settled at 1024). Waits on: the ingestion team confirming the `semantic` tables are final, and an expert check |
| A2 | Every layer decides from the wording (needs a query plan) | **Partly** | D-068: a stated scope (all years, statewide, place lists) is now read in any wording, so wordings converge; D-071 (2026-10-26): one measure named in any of its catalogue words reads one fixed query (104 measure/shape pairs). The query plan itself not started |
| A3 | Wikipedia in the KB; wrong folder in the docs | **Partly** | Docs fixed. Wikipedia still in `data/web/`; official documents not received |
| A4 | Routing bugs between knowledge and data | Not started | New example: KI-404 |
| A5 | Unused Qdrant collections | **Partly** | Backup done; nothing deleted (by design) |

### Part B: What RAG can fix

| # | Item | Status |
|---|---|---|
| B1 | Metric / synonym detection | **Partly** (2026-10-26, D-071): the data team's metric catalogue answers a question that names one measure and asks nothing else, in 4 shapes, for the 104 (measure, shape) pairs proven equal live; report `new_docs/Metric_Catalogue_Report_2026-10-26.md`. Meaning-based (vector) synonym matching not done |
| B2 | Scheme from vocabulary | Not started |
| B3 | Data vs knowledge from retrieval scores | Not started |
| B4 | Prompt pruning | Not started |
| B5 | Few-shots chosen by meaning | Not started |

### Part C: Fixed-code rules

| # | Item | Status | Detail |
|---|---|---|---|
| C1 | Years (FY24, last year) | **Partly** | D-068 + KI-414 (2026-10-26): every FY form (FY24, FY 24, FY'24, FY 23-24, 23-24) read the same by all year readers; follow-ups keep the typed year (live 81/81). "last year" and other relative forms not re-checked |
| C2 | Number words ("five highest") | **Solved** | 2026-10-26, KI-412: count words become digits; the SQL LIMIT is the stated count. Five wordings of one ranking give the same 5 blocks |
| C3 | Places | Not started | KI-368 open |
| C4 | Follow-ups carry filters | **Partly** | KI-405 fixed 2026-10-27 (a scheme switch typed during a pause is the paused question for that scheme; live suite 105/107). KI-406 waits on the U5 decision |
| C5 | Units and number checks | **Partly** | KI-417 (2026-10-26): crore / lakh shown at 2 decimals (₹119.74 Cr, a known answer). Rupees vs crore wording per scheme not yet unified |
| C6 | Collision rules | Already working | Kept unchanged |
| C7 | SQL variation (seed) | **Measured: not needed** | 2026-10-26: 10 questions × 5 runs gave identical SQL and results (temperature already 0). Paraphrases 9/10 same result; the 10th is a meaning ambiguity ("sanctions" = houses or amount), item B1 |

### Part E: Layer by layer

| # | Layer | Status | Detail |
|---|---|---|---|
| E1 | Query plan node | Not started | |
| E2 | Guardrail | Not started | |
| E3 | Follow-ups and context | **Partly** | Session-less API calls now get their own conversation (D-070, KI-423, live-verified). Follow-ups editing a plan instead of text, and the U5 year-carry decision, not started |
| E4 | Intent classifier | Not started | |
| E5 | Scheme routing | Not started | |
| E6 | Places and years | **Partly** | Years: every FY form read the same everywhere (D-068, KI-414; live 81/81). Regions: Ri Bhoi in Khasi per the LGD region column (D-069). Places (KI-368) and splitting resolve_entities not started |
| E7 | SQL generation | Not started | |
| E8 | Verifier / repair | Not started | |
| E9 | Composer | **Done 2026-10-29** (D-082) | Money rounding (KI-417); CM Elevate workflow statuses answered in fixed wording (D-069). 2026-10-29: one money formatter (`_c12_money`), figure-to-label check (`_c12_label_misbinds`), ranking / compare / trend / split figures written by code from templates (the 9B writes the opening line only); KI-447/448 fixed. Open: scheme writers' own money formats (KI-449); like-for-like compare by catalogue kind waits on E7; golden set not yet re-run |
| E10 | Cache, memory, orchestration | **Partly** | Semantic-cache scope fix (KI-401); memory search exact (KI-408). Redis and plan-keyed cache not done |
| E11 | UI | Not started | |
| E12 | Security and data | **Partly** | Done: PII files gitignored; generated SQL AND catalog reads run as `megh_readonly` (dev box), pools within the team's caps, `SELECT *` on hidden columns handled (D-069). Open: deploy VMs, `megh_app` (password pending), KI-022 CSV in git history, Qdrant key + firewall, gateway CA file, token in the remote URL |

## 4. Accuracy today (data golden set, `tests/nl2sql_eval`, 74 questions)

| | 2026-10-18 | 2026-10-24 |
|---|---|---|
| Accuracy | 97.3% (72/74) | **54.1% (40/74)** |
| Wrong answers | 2 | **0** |
| Asked back instead of answering | 0 | **34** (19 which year, 12 which area, 3 which CM Elevate dataset) |

- Every answer given was correct (40/40).
- **Cause:** the rules added on 2026-10-22 (D-061, D-064, D-065) make the app ask when a question names no year or place. The set (written 2026-10-15) expects "all years / statewide". **Not caused by the 1024 change:** 5 of the items re-run on 384 asked the same.
- Some look like over-asking even under today's rules: PM-13 ("taking all sanction years together"), MG-11 ("which districts"), CL-03 ("altogether").

Knowledge golden set (`tests/rag_eval`, 188 questions, today on 1024): correct-or-honest **92.0%**, made-up answers 13.9% (17.1% on 384).

### After D-068 (2026-10-24 night)

| | Before | After |
|---|---|---|
| Held-out data set | 54.1% (40/74) | **56.8% (42/74)**: MG-11, PM-13, CL-03 fixed |
| Wrong answers | 0 | 1 (PM-04: flips the same way on the original code, KI-411) |
| "FY24" | FY 2024-25 (wrong) | FY 2023-24, same answer as "FY 23-24" |

## 5. Open issues logged today

| KI | Issue | Status |
|---|---|---|
| KI-404 | "How does MGNREGA job card registration work?" goes to DATA | Open |
| KI-405 | Scheme switch typed during a pause gets merged | Open |
| KI-406 | Follow-up drops the year (tied to U5) | Open: needs a decision |
| KI-407 | Live suite expects the pre-D-064 CM Elevate rule | Open: needs a decision |
| KI-409 | FY24 read as 2024-25 | **Fixed** (D-068) |
| KI-410 | Stated scope asked in unrecognised wordings | **Fixed** (D-068) |
| KI-411 | PM-04 per-year split not caught by the guard | Open |

## 6. Decisions waiting for the user

1. **Ask or assume** when a question names no year or place? Recommended: answer with a stated default (all years / statewide) plus one-tap buttons; keep asking for stock measures and the Focus / CM Elevate collisions. Decides 34 golden-set items.
2. **U5:** does a follow-up keep the previous year? (KI-406)
3. **KI-407:** is the CM Elevate check stale under D-064?
4. **Commit** the review report and the two golden-set result files?

## 7. Needed from others

| From | What | For |
|---|---|---|
| Ingestion team | Are the `semantic` tables final? | A1 (metadata collection) |
| Scheme expert (about 1 hour) | Check metric synonyms; sign off the 188 knowledge answers | A1, B1, golden sets |
| User / scheme owners | Official MGNREGA and PMAY-G documents | A3 |
| Server admin | Qdrant API key + firewall; gateway CA file; `.env` on the deploy servers | E12, deploy |
| Repo owner | Purge the KI-022 bank CSV from the remote history; rotate the token in the remote URL | E12 |

## 8. Current state of the system

- Branch `update/2026-10-24`, 3 commits today (`9c7c67c`, `0aa135c`, `dd8b58b`), **not pushed**.
- App on :8401: health ok, 1024 embeddings, exact memory search.
- Rollback for the embeddings: D-067 (all `.env` lines together); the 384 collections are kept.
