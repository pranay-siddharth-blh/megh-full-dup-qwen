# Megh One AI: errors and problems found

**Date:** 2026-10-15
**Code checked:** `meghalaya/app/` (all paths below are relative to `meghalaya/`)
**How it was checked:** the source code, docs, tests and logs were read. Nothing was executed and no
database queries were run, so every item here comes from reading, not from running the bot.
**Inferences** (things concluded but not seen directly) are marked *(inference)*.

**Contents**
1. [Summary](#1-summary)
2. [Wrong or failing answers (concrete cases)](#2-wrong-or-failing-answers-concrete-cases)
3. [Root causes, ranked](#3-root-causes-ranked)
4. [Context memory problems](#4-context-memory-problems)
5. [SQL safety and security problems](#5-sql-safety-and-security-problems)
6. [Prompt, schema and example problems](#6-prompt-schema-and-example-problems)
7. [Knowledge (RAG) answer problems](#7-knowledge-rag-answer-problems)
8. [Multilingual and voice gaps](#8-multilingual-and-voice-gaps)
9. [Testing and logging gaps](#9-testing-and-logging-gaps)
10. [Recommended fixes, in order](#10-recommended-fixes-in-order)
11. [Not verified](#11-not-verified)
12. [Reference: how the bot is built](#12-reference-how-the-bot-is-built)

---

## 1. Summary

The bot is a Python / FastAPI app orchestrated by LangGraph. It turns questions about six Meghalaya
schemes into PostgreSQL. All models are self-hosted Qwen models behind one OpenAI-compatible gateway:

- `qwen3-coder-30b` writes the SQL;
- `Qwen3-4B` classifies, rewrites follow-ups and verifies the SQL;
- `qwen35-9b` writes the answer.

**The most important problems:**

| # | Problem | Why it matters |
|---|---|---|
| 1 | **Wrong numbers from missing business definitions** ("men worked" summed all persons; per-year beneficiaries summed into an all-years total) | The answer looks correct but the number is wrong. Nothing fails, so nobody notices |
| 2 | **Follow-up and context bugs** (topic switch, KI-033, KI-223, KI-301) | The bot answers for the wrong scheme, district or year |
| 3 | **No automated SQL accuracy measure** | The test sheets are re-runs of the same questions after fixes. First-pass accuracy was about **70%** (144/206) |
| 4 | **Generated SQL runs as the `postgres` superuser**, protected by one regex check | The most serious security risk |

---

## 2. Wrong or failing answers (concrete cases)

| # | Question | What happened | Cause | Status | Evidence |
|---|---|---|---|---|---|
| 1 | "How many men worked under MGNREGA in Ri Bhoi in 2023-24?" | SQL used `SUM(persons_employed) AS men_employed` → **53,700**; correct is **23,758** | Missing business definition (no men column rule) | **Open, High** | `docs/KNOWN_ISSUES.md:233` |
| 2 | "Show beneficiaries for Focus Plus" (all years) | Per-year distinct counts were summed → **199,099**; the unique count is **105,813** | Missing aggregation rule | **Open, High** | `docs/KNOWN_ISSUES.md:47, 738-744` |
| 3 | "How many beneficiaries in MGNREGA, all years" | One phrasing used `SUM(households_employed)` (1,494,437), another used `persons_employed` | Missing definition + no example | **Open, Medium** | `docs/KNOWN_ISSUES.md:52, 782-790` |
| 4 | Question about Shallang block | Correct SQL, but the verifier wrongly complained about "Meghalaya" and used up all repair attempts | Verifier false positive | KI-002 **Open (mitigated)** | `logs/uvicorn_verifier_geo.err:60-65` |
| 5 | "give me block wise only in ekh for MGNREGA across all financial years" | `column "lgd_block" does not exist`, twice, then fell back to the knowledge base | Wrong column for that view | Fixed later *(inference)* | `logs/run_dev.err:1082-1086` |
| 6 | MGNREGA money question for one village | SQL converted lakh to crore for a single village | Unit rule | Guarded (fixed) | `logs/uvicorn_verifier_geo.err:85` |
| 7 | Knowledge turn, then a data follow-up | The rewrite took "West Garo Hills, Dalu, FY 2025-26" from a stale summary; scope was lost | Follow-up / history | **KI-033 Open, High** | `docs/KNOWN_ISSUES.md:722-730` |
| 8 | "How many PMAY-G beneficiaries…?" then "What about MGNREGA?" while a pause was waiting | Merged into the paused question, giving a two-scheme pause | Follow-up / history | **KI-223 Open** | `docs/KNOWN_ISSUES.md:227` |
| 9 | "What is Gram Panchayat?" then "what is its role in PMAY-G?" | Rephrased into "role of a government data assistant in PMAY-G" | Follow-up / history | **KI-301 Open** | `docs/KNOWN_ISSUES.md:309` |
| 10 | "How many houses were sanctioned under PMAY-G in FY2022-23?" | "FY2022-23" (no space) not understood; the bot asked for area / time | Year parsing | **KI-289 Open** | `docs/KNOWN_ISSUES.md:297` |
| 11 | "Which are the top ten blocks in West Garo Hills by disbursement amount for Focus Plus per financial year twenty twenty five to twenty six?" | No scheme detected, 0 rows, 15.8 s | Spoken-number year not parsed *(inference)* | Open | `logs/query_audit.jsonl` (2026-10-15) |
| 12 | Any question that needs all 6 schemes | Prompt is about **32k tokens** against a **16k** model limit | Context overflow | **KI-011 Open** | `docs/KNOWN_ISSUES.md:452-462` |
| 13 | "Which village in CM Elevate covers all fifteen schemes?" | Rewritten to CM Elevate **Legacy** | Wrong scheme substitution | Open | `logs/query_audit.jsonl` (2026-10-13) |
| 14 | Under load | Intermittent "couldn't build a working query" | Unknown | **KI-151 Open** | `docs/KNOWN_ISSUES.md:155` |

**From the audit log** (`logs/query_audit.jsonl`, 5,455 rows):
- about **37%** of turns are clarification questions (2,020);
- **1,186** rows returned 0 rows.

The audit log does not record the SQL or the error, so the cause of each zero-row answer cannot be
seen there.

---

## 3. Root causes, ranked

| Rank | Root cause | Evidence | Impact |
|---|---|---|---|
| 1 | Missing aggregation and business definitions (gender, distinct-across-years, households vs persons) | Cases 1-3 | **High**: silent wrong numbers |
| 2 | Follow-up and history handling | Cases 7-9; topic-switch bug; about 40 KI entries | **High** |
| 3 | No accuracy benchmark; fixes are validated only on the same questions | KI-017, KI-199 | **High**: problems are not detected |
| 4 | Filter values and year parsing (FY formats, number words) | Cases 10-11; about 70 entity-related KI entries | Medium |
| 5 | Unexecuted few-shot examples presented to the model as "verified" | `app/prompt_builder.py:133` vs the yaml headers | Medium |
| 6 | Verifier false positives using up the repair budget | Case 4; KI-002 | Medium |
| 7 | All-scheme prompt larger than the context window | Case 12; KI-011 | Medium |
| 8 | Dialect not stated; no column types or primary keys in the live schema | Section 6 | Low |
| 9 | Low knowledge (RAG) precision: no reranker, score floor not enforced, about 19% made-up answers | Section 7 | Medium (knowledge answers) |

**Known-issue categories** (about 300 KI entries in `docs/KNOWN_ISSUES.md`; grouping is approximate):

| Category | Approx. count | Still open |
|---|---|---|
| Entity resolution / filter values (villages, blocks, AC collisions, spellings, years) | ~70 | KI-036, KI-037, KI-289 |
| Follow-up / context / pause resume | ~40 | KI-031, KI-033, KI-038, KI-223, KI-224, KI-301 |
| Answer faithfulness and formatting (lakh/crore, sums, labels) | ~35 | — |
| SQL guards for wrong aggregation or definitions | ~35 | KI-035, KI-040, KI-229, KI-124 |
| Routing / intent / guardrail / scheme detection | ~30 | KI-290 |
| Infra / security / process | ~25 | KI-003, KI-004 (High), KI-005..010, KI-012..014, KI-017, KI-022 (Critical), KI-023, KI-200 |
| Verifier false positives | ~10 | KI-002 |
| Data-side (external) | 4 | KI-019, KI-065, KI-084, KI-155 |
| Prompt size | 1 | KI-011 |

**Doc problems in `docs/KNOWN_ISSUES.md`:**
- IDs KI-228..231 are used twice.
- The KI-089..095 header says "open", but the rows say Fixed.
- KI-031 says Low in its detail section and Medium in the table.

---

## 4. Context memory problems

### 4.1 Topic switch through a knowledge question (open)

| Turn | User says | Expected | Actual |
|---|---|---|---|
| 1 | "How many MGNREGA person-days in East Khasi Hills in 2022-23?" | MGNREGA, EKH, 2022-23 | Correct |
| 2 | "Who is eligible for PMAY-G?" | PMAY-G rules | Correct |
| 3 | "How many in 2023-24?" | **PMAY-G**, statewide, 2023-24 | Answered for **MGNREGA, EKH** |

**Causes:**
- `update_state()` returns early for any non-DATA turn, so the knowledge turn never changes the
  stored scheme (`app/context_manager.py:377`).
- "How many in 2023-24?" is not treated as a follow-up:
  - "how many" counts as a standalone question;
  - `is_scopeless_followup` needs a DATA turn before it;
  - `_measure_after_knowledge` rejects any question that names a year (`app/pipeline.py:324`).

### 4.2 Other context gaps

| # | Gap | Example | Evidence |
|---|---|---|---|
| C1 | A standalone DATA turn keeps the old `metric`, comparison and tranche | Old metric leaks into a new topic | `app/context_manager.py:481-491` |
| C2 | "this year" / "last year" / "both" are substituted on **every** question, not only follow-ups | A standalone "this year" gets the session's old year | `app/pipeline.py:17988` |
| C3 | Caches decide on the raw text before the pipeline runs; a rewritten, context-dependent answer is cached under its raw text | Another user can get this user's year or scheme | `app/routers/query.py:188, 325` |
| C4 | Semantic cache accepts a 0.93 similarity hit with no scheme / place / year check | "…2023-24" can be served the "…2024-25" answer | `app/semantic_cache.py:66-98` |
| C5 | Only the **last** turn per topic can be restored | Two MGNREGA questions: the earlier one is lost | `app/topic_memory.py` `checkpoint()` |
| C6 | Going back works only by scheme name, only at the start of the message | "go back to the East Khasi Hills question" fails | `topic_memory.parse_switch`, `_SWITCH_LEAD` |
| C7 | Recall needs the word "again" / "remind me" / "recap" | "What was the MGNREGA figure?" is a new question | `app/conversation_layer.py:130` |
| C8 | The Qdrant older-turns search runs only while the session has fewer than 2 turns | It is almost never used | `app/context_manager.py:830` |
| C9 | Everything (state, turns, topics) is cleared after 30 idle minutes | "Go back to MGNREGA" after lunch fails | `app/config.py:320` |
| C10 | A worker switch can drop all topics ("reset-stale") | Topics lost with no error | `app/topic_memory.py:299` |
| C11 | Only 8 turns are kept per session | Long conversations lose early turns | `app/config.py:309` |
| C12 | "What was the figure?" with several topics in memory is silently read against the current topic | Should ask which topic | `app/conversation_layer.py` (no rule) |

**Note:** LangGraph checkpoints are **not** conversation memory here. They store a paused run only
(e.g. "Which year?" waiting for a reply) and are deleted when the run finishes
(`app/pipeline_graph.py:16-25`). Conversation memory lives in the Session state and topic memory.

---

## 5. SQL safety and security problems

| # | Problem | Evidence | Severity |
|---|---|---|---|
| S1 | **The app connects to the database as the `postgres` superuser.** The least-privilege role exists only as an unapplied script | `.env` DATABASE_URL user (checked by pattern, value not printed); `deploy/sql/01_create_megh_app_role.sql:5-8` | **Critical** |
| S2 | No SQL parser. The only guard is a regex: one statement, must start with SELECT/WITH, blocks 11 write keywords | `app/db.py:20-26, 115-123` | High |
| S3 | Not blocked: `SELECT … INTO`, `pg_read_file`, `pg_ls_dir`, `lo_import`, `dblink`, `pg_sleep`, `set_config`, `pg_terminate_backend`, `FOR UPDATE` *(inference from the regex)* | `app/db.py:23-26` | High |
| S4 | No allowed-table list. Generated SQL can read `app.users` (password hashes), `app.query_audit`, `pg_catalog` | `app/db.py` (no check); KI-004 | High |
| S5 | No `READ ONLY` transaction; no server-side `statement_timeout` (only a 15 s client timeout) | `app/db.py:80, 173-174` | Medium |
| S6 | The LIMIT is skipped if the text "limit" appears anywhere (e.g. a column named `credit_limit`); a model-written `LIMIT 1000000` is kept | `app/db.py:169-171` | Low |
| S7 | Even the planned `megh_app` role can write to `app.*`, and generated SQL shares the same connection pool | `deploy/sql/01_create_megh_app_role.sql:54-65, 79-92` | Medium |
| S8 | The user-scope check is regex-based. `UPPER(lgd_district)=`, `ILIKE`, `<>`, `NOT IN`, `= ANY(...)`, joins and subqueries are not detected *(inference)*. No Postgres row-level security | `app/auth.py:199-220, 231-312` | High |
| S9 | `_focus_legacy_pg_name_answer` returns district / block / member data with no `authorize` call *(inference)* | `app/pipeline.py:3754, 16376` | Medium |
| S10 | On attempt 0, the ~40 deterministic SQL rewrites run **after** `authorize` and are not re-checked *(inference: low risk)* | `app/pipeline_graph.py:432-449` | Low |
| S11 | The LLM verifier and the guardrail model let everything through when they fail | `app/pipeline.py:14244-14246`; `app/config.py:553` | Medium |
| S12 | The user's text is put into every prompt verbatim, with no delimiting | `app/prompt_builder.py:498` | Medium |
| S13 | Model gateway TLS falls back to `verify=False` if no CA bundle is set (a bundle is set in `.env` today) | `app/llm.py:43-81` | Low |
| S14 | DB connection has no `sslmode` | `.env` (checked by count) | Low |
| S15 | `app/users.yaml` is tracked in git and holds seed passwords (default "changeme123" per its header) | `app/users.yaml:21, 27`; KI-022 | **Critical** if real |
| S16 | `JWT_SECRET` falls back to `"change-me-dev-secret"`; a weak secret only logs a warning | `app/config.py:443, 576-591` | Low (set in `.env`) |
| S17 | Rate limiting is per worker (in-memory); `TRUSTED_PROXIES` trusts all private IP ranges by default | `app/middleware/rate_limit.py:18-23`; `app/config.py:70` | Low |

---

## 6. Prompt, schema and example problems

**Prompt**
- The SQL dialect is never stated. "PostgreSQL" appears only once, incidentally
  (`app/schema_context.py:201`).
- There is no system prompt; everything is one user message (`app/llm.py:214-219`).
- `top_p` and stop sequences are never set, so gateway defaults apply.
- `SQL_GENERATION_MAX_RETRIES` is defined but never used (`app/config.py:186`).
- The context window of `qwen35-9b` (composer) is not recorded, and the composer prompt is not
  budget-checked (`app/config.py:566`).
- Token counting is characters ÷ 4, with no tokenizer (`app/context_budget.py:48-50`).
- Repair and verify prompts are never compressed when they are too long. An over-budget SQL prompt is
  sent anyway, with a warning (`app/context_budget.py:138-173`).

**Schema**
- The live schema block shows column names only: **no data types and no primary keys**
  (`app/prompt_builder.py:100`; `app/schema_introspect.py:177` reads foreign keys only).
- Tables the code does not recognise default to "shared" and are shown to every scheme
  (`app/prompt_builder.py:55-75`).
- The catalogue's `join_graph` is loaded but never put in the prompt (`app/schema_introspect.py:305`).
- `dim_scheme.grain_note` is used in a Focus Plus example but missing from the hand-written column
  list (`app/schema_context.py:146`).
- `data/schema/schema_for_developers.md` is stale: it says 204 columns / 16 objects from when only
  2 schemes were loaded.

**Few-shot examples**
- The prompt calls them **"verified SQL"** (`app/prompt_builder.py:133`), but 5 of the 6 files say
  **"NOT ONE OF THESE QUERIES HAS BEEN EXECUTED against megh_db"**:
  - `pmay_few_shot.yaml:26`
  - `focusplus_few_shot.yaml:33`
  - `cmelevate_few_shot.yaml:43`
  - `focuslegacy_few_shot.yaml:45`
  - `cmelevatelegacy_prompt_few_shots.yaml:32`, which is a "calibrated mock"
- PMAY's retired examples are meant to stay as negative examples but are dropped by the loader
  (`app/annotations.py:104`).
- MGNREGA job-card examples hard-code `year_key = 2025` (`data/mgnrega/few_shot.yaml:323-327`).
- Several examples have no `LIMIT`, although the rules require one.

**Other**
- `requirements.txt` still says LangGraph is "off unless PIPELINE_GRAPH_ENABLED". That flag was
  removed; LangGraph is always on.
- A nested copy of the repo exists at `meghalaya/meghalaya/app/`. It was not checked and may confuse
  searches.

---

## 7. Knowledge (RAG) answer problems

| # | Problem | Evidence |
|---|---|---|
| R1 | If every chunk scores below the 0.30 minimum, the top 8 are **sent anyway**, so the floor never filters | `app/rag.py:336-337` |
| R2 | The reranker is off: `qwen3-reranker` "inverts relevance" | `app/config.py:244` |
| R3 | Multi-query and the grounding check are off | `app/config.py:322, 326` |
| R4 | Eval (188 questions): Hit@3 68-80%, **made-up answers about 18-20%** | `tests/rag_eval/results/*.json` |
| R5 | The latest eval used KB `megh_scheme_kb_v2`, but production uses `megh_scheme_kb_v3` | `termfix.json`; `logs/server_8400.log` |
| R6 | The embedding model `bge-small-en-v1.5` is English-only | `app/config.py:232` |

---

## 8. Multilingual and voice gaps

- **Khasi / Garo:** the English translation step exists but is **off** (`TRANSLATE_ENABLED=False`,
  `app/config.py:312-315`).
- **Hindi / Hinglish:** handled only by the rephraser, and only when a question looks messy
  (`app/prompt_builder.py:684-718`).
- **Bengali:** passed through untouched (`app/edge.py:1020-1023`).
- **Voice:** the ASR allows `hi` but not Khasi, Garo or Bengali; those fall back to English
  (`app/llm.py:617-631`).
- **Answers:** always in English.
- **Coverage:** no tests and no known-issue entries cover multilingual questions.

---

## 9. Testing and logging gaps

**Testing**

| Item | Result |
|---|---|
| Unit tests | pytest 2,258 passed / 1 skipped; 14/14 script suites (`docs/TESTING.md:108`) |
| Scheme test sheets | 206 cases: **144/206 (~70%) first run**, 206/206 after fixes |
| Cross-scheme sheet | **0/20** first run → 20/20 after fixes |
| Live context validation | 43/43 (not always re-run after changes: `docs/TESTING.md:106`) |
| **NL→SQL accuracy vs the real model and DB** | **None** (KI-017 Open, High; `docs/TESTING.md:14-15, 248`) |
| Prompt-injection test / test that SQL cannot read `app.*` | **None** (`docs/TESTING.md:252`) |

- The sheet results are re-runs of the same questions after fixes, so they overstate real accuracy.
  KI-199 says only one question shape per place is covered.
- Running `pytest tests` on the whole folder crashes (KI-018).

**Logging**
- The audit log (`logs/query_audit.jsonl`, `app.query_audit`) has **no SQL, no error, no token
  counts and no retrieved tables** (KI-003).
- The failed SQL is not logged during repair; only the error text is.
- The few-shot examples used for each turn are not logged.
- `/metrics` has no accuracy or repair counters (KI-009).
- Most pipeline log lines carry no request id.
- The SQL **is** stored in `app.conversation_turns` (DB only).

---

## 10. Recommended fixes, in order

| # | Fix | Solves |
|---|---|---|
| 1 | Run generated SQL through a **SELECT-only role** with its own connection pool, `SET TRANSACTION READ ONLY`, a server `statement_timeout`, and only `curated` / `semantic` allowed | S1, S4, S5, S7 |
| 2 | **Parse SQL with sqlglot** before running it: allowed tables, function blocklist, real LIMIT check, scope check on the parsed tree | S2, S3, S6, S8 |
| 3 | Add the missing **business definitions** (gender, distinct across years, households vs persons) to the rules, with executed examples | Cases 1-3 |
| 4 | Build an **NL→SQL accuracy set** of held-out questions with expected results; run it against the real model and a read-only DB on every change | Root cause 3 |
| 5 | **Execute every few-shot example** (read-only); remove the word "verified" until they all pass | Section 6 |
| 6 | Fix the **context bugs**: knowledge-turn topic switch, year-aware measure follow-up, field reset, substitution only on follow-ups, cache context flag, semantic-cache entity check; then the per-topic ledger and backward resolver | Section 4 |
| 7 | Make the year parser accept "FY2022-23" and spoken numbers | Cases 10-11 |
| 8 | Log the **generated SQL, the error and the few-shot ids** in the audit log; add accuracy and repair counters to `/metrics` | Section 9 |
| 9 | State "PostgreSQL" in the prompt; add column types and primary keys to the live schema | Section 6 |
| 10 | For all-scheme questions, generate one query per scheme or trim the schema text | Case 12 |
| 11 | Enforce the RAG score floor; re-run the RAG eval on KB v3 | Section 7 |
| 12 | Add a scope check to `_focus_legacy_pg_name_answer`; re-authorize the rewritten SQL on attempt 0 | S9, S10 |
| 13 | Remove seed passwords from `app/users.yaml` and rotate them | S15 |

---

## 11. Not verified

These need execution or database access and were **not** checked:
- the real prompt sizes in tokens, and the gateway's real context limits;
- whether the `megh_app` role exists in the database;
- the content and language of the `semantic.*` catalogue;
- the `.xlsx` test sheets (pass rates are taken from `reference_documents/README.md` and
  `docs/TESTING.md`);
- the SQL behind the zero-row audit rows (it is in `app.conversation_turns`);
- whether the scope-check bypasses in S8 actually work;
- the nested copy at `meghalaya/meghalaya/app/`.

---

## 12. Reference: how the bot is built

**Flow of one question**
1. **Router** (`app/routers/query.py`): rate limit, JWT, restore the session.
2. **Conversation layer** (`app/conversation_layer.py`): idle expiry, reset, small talk, recall.
3. **Caches:** exact match, then semantic.
4. **LangGraph graph** (`app/pipeline_graph.py:588`), each node calling a stage in `app/pipeline.py`:
   - context → edge → followup → rephrase → route;
   - **KNOWLEDGE:** RAG (Qdrant hybrid search) → composer;
   - **DATA:** scheme → entities (LLM finds the words, `app/entity_resolver.py` matches exact DB
     values) → clarification → fixed SQL templates or LLM SQL (`app/prompt_builder.py:459`) →
     authorize (`app/auth.py:231`) → execute (`app/db.py`), with up to 3 repairs → compose →
     number checks → finalize → update context.
5. **After the graph:** save the turn, write the caches, sync the session.

**Models** (all temperature 0)

| Role | Model | max_tokens | Timeout |
|---|---|---|---|
| SQL generation and repair | `qwen-model` (qwen3-coder-30b-fp8), 16k context | 1024 | 30 s |
| Classifier, follow-up rewrite, verifier, guardrail, summary | `qwen4-deploy` (Qwen3-4B), 8k context | 40-200 | 6-30 s |
| Answer composer | `qwen35-9b` (context window not recorded) | 800 | 20 s |
| Embeddings | `BAAI/bge-small-en-v1.5` (local) | – | – |
| Voice | `qwen3-asr` | – | 60 s |

**Few-shot examples per scheme** (top 5 picked per question by word overlap)

| Scheme | Examples |
|---|---|
| MGNREGA | 68 |
| PMAY-G | 65 active |
| Focus Plus | 87 |
| CM Elevate | 155 |
| Focus Legacy | 86 |
| CM Elevate Legacy | ~132 |
