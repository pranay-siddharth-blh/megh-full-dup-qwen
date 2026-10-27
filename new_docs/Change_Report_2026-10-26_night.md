# Change Report: 2026-10-26 night (D-070, D-071)

This report covers the **uncommitted** changes on branch `update/2026-10-24` made after commit `cc0d1f1`. The changes up to `cc0d1f1` are described in `new_docs/Change_Report_2026-10-26.md`.

There are two changes:

1. **D-070:** an API call that sends no session id now gets a conversation of its own.
2. **D-071:** the data team's metric catalogue answers plain one-measure questions.

All test figures below come from the runs recorded in `docs/TESTING.md` and `docs/DECISIONS.md`. They were not re-run for this report.

---

## 1. D-070: a call without a session id gets its own conversation (KI-423)

### Problem
Every API call from one user on one day that carried no `session_id` shared a single conversation, `day-<user>-<date>`. Each unrelated question was therefore treated as a follow-up of the previous one and inherited its scheme, place and year.

Example: "MGNREGA person-days FY 2024-25 for all of Meghalaya", followed by an unrelated call "and in Ri Bhoi?". The second call was silently answered as an MGNREGA follow-up.

### Solution
| File | Change |
|---|---|
| `app/routers/query.py` (`_session_id`) | A logged-in call without a session id gets `api-<random>` instead of the per-day bucket. The id is computed once per request and cached on `request.state`. Without the cache, the stream's stop handler would have got a different id. |
| `app/conversation_store.py` | `list_my_conversations` and `search_my_conversations` skip `api-` threads, so scripts do not flood the user's chat history. The threads are still saved, so admin views and the audit keep them. |
| `tests/test_session_less_calls_2026_10_26.py` (new) | 5 regression tests. |

To continue an API conversation, for example to answer a clarification, the caller sends back the `session_id` returned in the response.

### Result (live)
- **Without an id:** "and in Ri Bhoi?" now starts a new conversation and asks "Which scheme?". There is no leaked context.
- **With the returned id:** 928,817 (MGNREGA, Ri Bhoi, FY 2024-25).
- **History list:** no `api-` chat appears in it.

**Impact:** a **real fix**. Wrong-context answers on session-less API calls are gone. The chat UI already sends a session id, so it behaves exactly as before.

**Side effect:** an API script that answered a clarification without sending the id back must now send it.

---

## 2. D-071: the metric catalogue answers plain measure questions (RAG plan B1 / A2)

### Problem
The SQL model wrote its own SQL for every wording. "Spend", "outlay" and "money spent" could therefore read different figures, and a wording could be misread. The ingestion team's table `semantic.metric_definitions` already defines 62 named measures, each with its SQL expression, view, unit and synonyms.

### Solution
| File | Change |
|---|---|
| `app/metric_catalog.py` (new, 375 lines) | At startup, loads the 39 measures that belong to our six schemes. Finds the **one** measure a question names. Builds a parameter-bound query on the SQLGlot tree, with no regex. |
| `app/pipeline/common/c16_metric_catalog.py` (new, 225 lines) | Decides whether a question qualifies. Every word in it must be the measure, the scheme, a resolved place, a year or plain question grammar. Allowed filters are district, block, village and year. Four shapes are supported: total, breakdown, ranking (top/bottom N) and compare. |
| `app/pipeline/common/c13_compose_and_data_stages.py` | `_metric_catalog_query` is added as the **last** fixed query in the chain, so every existing fixed query keeps priority. Catalogue SQL runs on the **read-only** pool (`fetch_rows_readonly`). |
| `app/pipeline/__init__.py` | `c16_metric_catalog` added to `_PIPELINE_FILES`. |
| `app/main.py` | Loads the catalogue at startup. |
| `app/config.py` | New `METRIC_CATALOG_MODE` setting: `off` / `shadow` / `on`. The default is `on`. |
| `data/metric_catalog_verified.yaml` (new) | The evidence gate. A (measure, shape) pair answers through the catalogue only if it is listed here. 104 pairs are listed: total 28, breakdown 25, ranking 28, compare 23. Any other pair is only logged, and the model path answers as before. |
| `tests/test_metric_catalog_2026_10_26.py` (new, 24 tests), `tests/metric_catalog_eval.py` (new live harness) | Tests. |

### Result (live, 312 questions)
- **Shadow run:** 207 questions built a catalogue query. For 105 of the 111 (measure, shape) pairs, the catalogue figure matched the current answer on every question. The 6 that disagreed were left out (see KI-424..426).
- **On run:** the catalogue answered 183 of the 312 questions. **All 183 gave the same figure** as before, and every total stated it.
- **Golden NL→SQL set:** **42/74**, the same as before, with **0 regressions**.
- **Live context suite:** 103/107 (unchanged).
- **Known answers:** 13/14. The 14th is the intended D-064 "which CM Elevate" question.

### Impact: an improvement, but in consistency rather than in the accuracy score
- **What is better:**
  - For about 59% of the eval questions (183 of 312), the answer no longer depends on the 30B SQL model. A fixed, parameter-bound query from the data team's own definition answers instead. Different wordings of the same question now read the same figure every time.
  - There is no SQL-model call, verifier or repair loop for these questions, so they are faster and cannot hallucinate SQL.
  - The run found three real inconsistencies that were not known before (KI-424..426).
- **What is unchanged:** the golden-set score stays at 42/74. The catalogue was deliberately limited to cases where it gives the **same** figure as today, so it cannot raise or lower correctness on these questions. Every other question takes the model path exactly as before.
- **Rollback:** set `METRIC_CATALOG_MODE=off` and restart.

---

## 3. Documentation updated
`CLAUDE.md` (file list; reranker status corrected to **off**), `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, `docs/DECISIONS.md` (D-070, D-071), `docs/KNOWN_ISSUES.md` (KI-423 fixed; KI-424, 425, 426 opened), `docs/TESTING.md`, `docs/AI_PIPELINE.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `new_docs/RAG_Plan_Status_Report_2026-10-24.md` (B1, C5, E3, E6 and E9 now partly solved).

## 4. Tests
- **pytest** (the documented 27-file command): **3,829 passed, 0 failed**, 3 skipped. That is 29 more than the 3,800 before these two changes.
- **Plain-script suites:** 14/14.

## 5. Open items
| Item | What |
|---|---|
| KI-424 | Ambiguous measure words. On PMAY-G, "sanctions" and "coverage" are read differently by the model and by the catalogue; on Focus Legacy, "remittances" and "payments made" are. Confirm the meanings with the scheme owners. |
| KI-425 | CM Elevate Legacy applicants sanctioned: 2,288 on the model path vs 2,291 in the catalogue. The difference is 3 records with no amount. |
| KI-426 | Focus Plus payments by district: the model path groups on `district_name_raw`, not `lgd_district`, so district totals differ. A question for the data owners. |
| Server | The :8401 server (PID 32108, system Python) started before these changes. Restart it from `.venv` to load the catalogue. |
| Docs | `new_docs/Metric_Catalogue_Report_2026-10-26.md` is referenced in `config.py`, `HANDOFF.md` and the verified YAML, but **the file does not exist**. DOCUMENTATION CONFLICT — NEEDS VERIFICATION. |
| Git | Nothing is committed yet. 16 files are modified, and 8 new files are untracked: 2 code modules, the verified YAML, the eval harness, 2 test files and 2 eval result JSONs. |
