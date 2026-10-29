# NL2SQL Re-Audit Report

## 1. Identity and scope

**Team audited.** Team B, the LangGraph version. The code runs on a LangGraph `StateGraph`; there is no custom-pipeline driver (`app/pipeline_graph.py:574-612`) (O).

**Repository**
- Path: `C:\Users\Admin\OneDrive\Desktop\MCP\meghoneai\meghalaya`. It is a nested git repo (O).
- The outer repo `meghoneai` is on `Main` at `90c83a1` ("Remove all code"). There, all of the code is untracked (O).

**Branch and commit**
- Branch: `update/2026-10-13` (O).
- HEAD: `3ce306515a20258973db263e49a89e25c58cfbca`. Last commit: 2026-10-13 18:51 +0530, "Cross-scheme answers, conversation replies, keyboard shortcuts, test reports" (O).

**Previous audit**
- Commit `3ce3065`, the same as HEAD now.
- Saved as `documents/error one.md`, at 2026-10-15 19:11 IST. Score **33 / 66** (O).
- That audit also covered the **working tree**, not HEAD (`error one.md:7`).
- **Consequence: no commit has been made since the previous audit.** Every change audited here is uncommitted or untracked. "Changed since the last audit" therefore means files whose modification time is after 2026-10-15 19:11. There are about 200 such files under `app/`, `tests/`, `data/`, `docs/`, `deploy/` and `frontend/src/` (O, `find -newermt`).

**Working tree at audit time** (`git status --short`)

| State | Count |
|---|---|
| Modified | 117 |
| Deleted | 835 |
| Untracked | 67 (more appeared during the audit) |

- 793 of the deleted paths are evidence and report files under `docs/*Evidence*` and `docs/*.xlsx`.
- Also deleted: 18 files under `data/reference/`, and `app/pipeline.py`, which was 18,346 lines at HEAD (O).

**Safety files untracked at the previous audit, all still untracked (O)**
- `app/pipeline/` (the whole 21-file pipeline package)
- `app/sql_guard.py`
- `deploy/sql/03_readonly_role.sql`

**Newly untracked**
- Code: `app/sql_ast.py`, `app/text_match.py`, `app/turn_trace.py`, `app/translate.py`, `app/local_rank.py`, `app/routers/stats.py`, `app/routers/feedback.py`
- Tests: `tests/nl2sql_eval/`, `tests/fewshot_exec/`, and 31 `tests/test_*.py` files
- Data: `data/incoming/`
- Stale or stray: the duplicate tree `meghalaya/meghalaya/`, `frontend/undefined/`, and an empty `constants.js` (O)

**The tree was being edited during the audit (O).** Examples:
- `app/turn_trace.py` changed at 18:41 and again at 18:45.
- `app/main.py` changed at 18:44.
- Three new NL2SQL result files appeared between 18:42 and 18:44.

This report reflects the tree as read between about 18:30 and 19:00 IST on 2026-10-16.

**Task board.** `task-board-B-langgraph.md` was **not provided** and is not anywhere in the workspace. A search for "task-board", "Week 0" and "task board" found nothing except the previous report. Section 4 is therefore provisional; see the note there.

## 2. Executive summary

1. **No commits.** HEAD is unchanged. All work, including the SQL guard, the AST helper, the read-only role script, the pipeline package and the eval, is uncommitted, and the key safety files are untracked. A deploy from git would ship none of it (O).
2. **Real progress:**
   - Authorization now reads parsed SQL with sqlglot, so the `UPPER()` and second-`IN` holes are closed and tested.
   - Three private tables are refused in code, and the LIVE SCHEMA hides them.
   - Over-budget multi-scheme prompts now split into one query per scheme.
   - All 567 few-shots have been executed once.
   - Context-dependent answers are no longer written to the cache, and the semantic cache now matches scheme, place and year.
   - The audit log gained SQL, error, few-shot ids, repairs and outcome, and `/metrics` gained accuracy counters.
   - The RAG score floor is enforced.
   - `re.compile` count in `app/` went from 633 to 0.
3. **Still not done:**
   - The first attempt runs rewritten SQL without re-authorization.
   - About 6 answer paths still skip authorization.
   - There is no session ownership check.
   - `finish_reason` is still never read.
   - There is no stop when the repair returns identical SQL.
   - The lakh/crore contradiction is unchanged.
   - The result digest still sums `COUNT(DISTINCT)` columns.
   - Translation is still off.
   - The grounding check still fails open.
4. **New risks:**
   - **CTE-scope bypass.** A CTE name inside a subquery disables the private-table and `pg_*` checks (`sql_guard.py:109,119,124`).
   - **Geography check is a denylist.** It only looks for named stray districts, so `<>`, `NOT IN` and `OR TRUE` pass.
   - **Regexes were ported, not removed.** They became a custom backtracking matcher with about 510 patterns (`text_match.py`).
   - **Eval questions were edited.** Two of the three were reworded or replaced after they failed.
5. **Eval figures:**
   - Accuracy went from 78.4% to 100% at 18:11–18:15, then **97.3%** at 18:42, with CE-11 and CL-12 regressing.
   - **Every run logged in as `postgres`.** Four files record `superuser_allowed: false`, which is wrong.
6. **Score: 33 → 39 / 66 (+6).** Six dimensions rose by 1. Each rise is capped at +1 because the change is uncommitted or untracked.
7. **Confidence:** medium-high on the static findings. Runtime behaviour is not verified.

## 3. What changed

Counts are against HEAD `3ce3065`. Because the previous audit read the working tree, changes made after it are identified by file modification time.

**Diff size against HEAD (O)**

| Scope | Lines added | Lines removed |
|---|---|---|
| Whole working tree (`git diff --stat`) | 8,331 | 474,827 |
| Tracked `app/` | 5,808 | 19,776 |

- The whole-tree removal count is mostly deleted evidence files plus `data/reference/pmay_metadata.json` (451,691 lines).
- Most of the `app/` removal is `app/pipeline.py`.
- The untracked `app/pipeline/` is now **26,281 lines** in 21 files. It was 18,888 at the previous audit and 18,346 as the HEAD monolith (O).

**Changes by area** (files changed after 2026-10-15 19:11)

| Area | What changed (main files) |
|---|---|
| Safety (SQL) | `app/sql_guard.py` (16:50): `PRIVATE_TABLES` denylist and `private_table` rule (`:26-32,122-128`). `app/sql_ast.py` (new, 19:37 on 10-15): sqlglot helpers. `app/db.py` (16:46): read-only pool, superuser refusal |
| Authorization | `app/auth.py` (10-15 19:37): regex replaced by `sql_ast.filter_values`; fail-closed when SQL cannot be parsed (`auth.py:220-225,252-260`) |
| Prompt and context | `app/schema_context.py` (16:57, +15.6k / −12.8k chars), `app/prompt_builder.py` (12:53), `app/annotations.py` (16:59), `app/schema_introspect.py` (16:50: private tables and locked columns filtered). Per-scheme split in `c13:1441-1542` |
| Metrics and definitions | MGNREGA rules 6a, 11 and 12 (`schema_context.py:308-343`); units marked "RUPEES … confirmed" (`:27,36`); `tests/test_business_definitions.py` |
| Follow-ups | `app/context_policy.py` (12:53): `cleared:<fld>` violations at `:768-773`. `app/context_manager.py` (18:20): `_switch_topic_on_knowledge` at `:374-396`. `c01` (18:21), `c02` (18:40), `app/conversation_layer.py` (13:05) |
| Cache | `app/semantic_cache.py` (18:22): `scope_signature` (`:37-49,92-104`). `routers/query.py` (18:22): no write when `context_dependent` (`:351`) |
| Logging | `app/turn_trace.py` (new, 18:41/18:45). `app/appdb.py` audit columns (`:150-156`). `app/main.py` `/metrics` accuracy block (`:206-230`). `app/routers/feedback.py` (new) |
| Eval | `tests/nl2sql_eval/{questions.yaml,run_eval.py,holdout.py,compare.py}`: 14 new result files on 10-16. `tests/fewshot_exec/` (new). 2 new RAG eval results |
| Data and SQL | Few-shot YAMLs (MGNREGA +99 lines; Focus Plus, CM Elevate and Focus Legacy at 18:15). `data/reference/` deleted and moved to `data/incoming/`. `deploy/sql/01_create_megh_app_role.sql` modified |
| Docs | `CLAUDE.md`, `docs/{AI_PIPELINE,CURRENT_STATE,DATA_MODEL,DECISIONS,HANDOFF,KNOWN_ISSUES,SCHEMES,TESTING}.md`, `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-16.md` (new) |
| Tests | 46 tracked test files modified (+742 / −234); 31 untracked test files |
| Frontend | About 20 `frontend/src/chat/*` files and a rebuilt `web/app/assets/*` (not in scope) |

**Files added** (untracked): listed in section 1.

**Files deleted:** `app/pipeline.py`, `data/reference/*` (18 files), and 793 `docs/` evidence and report files.

**Top 10 changed files by lines**

| # | File | Change | Note |
|---|---|---|---|
| 1 | `data/reference/pmay_metadata.json` | −451,691 | deleted |
| 2 | `app/pipeline.py` | −18,346 | deleted; replaced by untracked `app/pipeline/` (26,281 lines) |
| 3 | `docs/Context_Validation_Report_2026-09-26.md` | −1,022 | deleted |
| 4 | `app/edge.py` | +989 / −293 | |
| 5 | `app/guardrails.py` | +637 / −156 | |
| 6 | `app/rag.py` | +632 / −55 | |
| 7 | `app/kb_ingest.py` | +530 / −40 | |
| 8 | `app/premise_check.py` | +435 / −55 | |
| 9 | `data/cm_elevate/prompt_assembler.py` | +329 / −108 | |
| 10 | `app/cross_scheme.py` | +308 / −70 | |

Source: `git diff --numstat HEAD` (O).

**Schemes in code:** 6, unchanged. MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate and CM Elevate Legacy, listed in `_ALL_SCHEMES` at `app/pipeline/common/c01_followups.py:1133-1134` (O). None was added or removed.

**Size, regex and test counts**

| Metric | Previous (B) | Now | Evidence |
|---|---|---|---|
| `app/pipeline/` lines | 18,888 | 26,281 | `wc -l` (O) |
| `app/pipeline_graph.py` lines | 870 | 878 | (O) |
| `re.compile(` in `app/` | 633 | **0** | `grep -c` (O) |
| `import re` in `app/` | many | 0 | (O) |
| `text_match` patterns (`Matcher(`) | – | about 510 | `app/text_match.py`, used by 25 files (O) |
| `tests/test_*.py` files | 72 | 87 | (O) |
| Files with `def test_` | 58 | 73 | (O) |
| `def test_` functions | 1,212 | 1,341 | (O; 1,329 at 18:44, so it grew during the audit) |

## 4. Board item status table

**The board was not provided.** The audit brief says to ask for the board file and meanwhile do the other sections. This file is the delivered report, so the table below is **provisional**.
- It reconstructs the board from the previous audit's top problems (`error one.md:456-468`), its scorecard gaps, and the regression cases in brief 3.6.
- IDs are prefixed **R-** (reconstructed) and do not match the board's own IDs.
- Re-map them when `task-board-B-langgraph.md` is attached.

| ID | Task (reconstructed) | Status | Change evidence | Test evidence | What is missing |
|---|---|---|---|---|---|
| R-01 | Commit and track the safety files (`sql_guard`, `03_readonly_role.sql`, `app/pipeline/`) | NOT DONE | `git status`: all `??`; HEAD unchanged | – | Commit everything; remove `meghalaya/meghalaya/` |
| R-02 | Authorize the **executed** SQL (after rewrites) | PARTIAL | Repairs are re-checked at `pipeline_graph.py:455-460` and `c13:1517` | `tests/test_sql_ast.py:62-91` (AST only) | Attempt 0 runs `_scheme_sql_rewrites` output unchecked (`pipeline_graph.py:454,462`; `c13:1516-1521`). Rewrites can swap or drop the district (`c10:642-666`; `mgnrega.py:1720-1729`) |
| R-03 | Parse-based authorization (`UPPER()`, IN lists) | DONE (scope as stated) | `auth.py:220-225` uses `sql_ast.filter_values` (`sql_ast.py:30-32,325-343`) | `tests/test_sql_ast.py:67-70` | `<>`, `NOT IN`, `OR TRUE`, subqueries and other columns are not covered (section 8) |
| R-04 | Close the answer paths that skip authorization | NOT DONE | `_geo_lookup_answer` (`c13:1112-1140`), `_village_name_search_answer` (`c13:597-640`), `_cross_scheme_money_answer` (`c06:561-569`), `_focusplus_overall_summary_answer` (`focus_plus.py:146`), `_focus_legacy_pg_name_answer` (`focus_legacy.py:968-1011`), `/api/scheme-stats` (`stats.py:92-119`) | none | Every path listed |
| R-05 | Run deterministic queries through `sql_guard` on the read-only pool | NOT DONE | Authorized on the shown text, executed as different text on the app pool (`c13:1330-1337,1573-1579`) | none | Route through `run_readonly`; authorize the executed text |
| R-06 | Privacy tables unreadable | PARTIAL | Code denylist (`sql_guard.py:30-32,123-128`); LIVE SCHEMA filtered (`schema_introspect.py:240-251,273`) | `tests/test_db_changes_2026_10_16.py:75-104` | DB grant still covers them (`03_readonly_role.sql:55`); CTE bypass; no column denylist |
| R-07 | Read-only role in use; superuser refused | PARTIAL | `db.py:106-125` refuses superuser by default (`config.py:164`); separate pool (`db.py:128-148`) | `tests/test_readonly_pool.py:85-154` | `.env` has no `READONLY_DATABASE_URL` and has `READONLY_DB_ALLOW_SUPERUSER=True`; still logs in as `postgres` (KI-304, `KNOWN_ISSUES.md:313`) |
| R-08 | Server-side `statement_timeout` | PARTIAL | Only in deploy SQL (`03:46`, `01:50`); client timeout 15 s (`db.py:140`) | none | Not set in `server_settings` (`db.py:92-95`); no evidence the scripts were run |
| R-09 | Session ownership check | NOT DONE | `session_store.py:279-297` (`:288` only fills an empty `user_id`); `conversation_store.py:382` | none | Owner check on ensure, load and save |
| R-10 | No caching of context-dependent answers | DONE (writes only) | `routers/query.py:351`; `_mark_context_dependent` at `c14:35-43`, `pipeline_graph.py:530` | `tests/test_forward_plan_wi.py:65-79` (flag only) | No router-level test that `put` is skipped; reads still decided by `is_cacheable` alone |
| R-11 | Semantic-cache entity check | PARTIAL | `semantic_cache.py:37-49,92-104` (scheme, place, year) | `tests/test_forward_plan_wi.py:83-104` | Measure, number and tranche not compared; threshold still 0.93 (`config.py:105`) |
| R-12 | Mark KB-fallback answers and do not cache them | PARTIAL | `turn_trace.outcome` gives `failed` (`turn_trace.py:104-112`) | `tests/test_audit_trace_and_years.py:39-88` (untracked) | `route` is still "knowledge" (`c14:1578-1581`); still cacheable when confidence is not "low" |
| R-13 | Check `finish_reason` | NOT DONE | `grep -rn finish_reason app/` gives 0; `llm.py:273` | none | Log it and handle "length" |
| R-14 | Context budget for multi-scheme prompts | DONE | `c13:1441,1463-1542`; graph wiring at `pipeline_graph.py:448-451` | `tests/test_per_scheme_sql.py` (untracked) | Single-scheme overflow is still sent (`context_budget.py:138-173`); verifier budget stale (`config.py:593,597`) |
| R-15 | Single source of truth for metrics and units | NOT DONE | Definitions still in `schema_context.py:51-129,308-343`, `cross_scheme.SPECS` (`:64-95`) and the YAMLs | `tests/test_business_definitions.py` | Merge into one registry; `cross_scheme` contradicts the rules (section 7) |
| R-16 | Fix the lakh/crore contradiction | NOT DONE | Rule `schema_context.py:289-294` vs `data/mgnrega/few_shot.yaml:4-5`; 24 `/ 100` lines (same as HEAD) | none | Align the rule and the few-shots |
| R-17 | KI-229 "men worked" | PARTIAL | Rule 6a (`schema_context.py:308-324`) plus few-shots | `tests/test_business_definitions.py:66,79,83` | No deterministic guard; `_MG_DEFINITION_COMPLAINT` (`mgnrega.py:605-608`) may discard real verifier complaints |
| R-18 | KI-035 beneficiaries across years | PARTIAL | Focus Plus `COUNT(DISTINCT beneficiary_key)` (`cross_scheme.py:73`) | `tests/test_business_definitions.py:14,49,54` | MGNREGA cross-scheme still `SUM(persons_employed)` with no year filter (`cross_scheme.py:67,654-656`) |
| R-19 | Stop the digest summing `COUNT(DISTINCT)` | NOT DONE | `_result_digest` (`c12:329-389`), labelled "authoritative" (`c13:98-113`) | none | Skip non-additive columns |
| R-20 | Execute few-shots and label them honestly | PARTIAL | `tests/fewshot_exec/check_fewshots.py`; `results/latest.json` (18:13): 567 run, 6 blocked, all out of prompt | `tests/test_fewshot_headers.py` (skips in CI: `:22-24`) | `prompt_builder.py:133` still says "verified SQL"; "NOT ONE … EXECUTED" lines remain (`pmay:26`, `focusplus:39`, `cmelevate:49`, `focuslegacy:51`, `cmelevatelegacy_prompt:32`); three banks edited after the run; checker not in CI; values not checked |
| R-21 | Stop the repair loop on identical SQL | NOT DONE | `pipeline_graph.py:476-481`, `c11:1976-1990` | none | Compare against the previous SQL |
| R-22 | Verifier after execution, fail-closed | PARTIAL | Runs after execution (`c11:1943,1953`) | `tests/test_verifier_after_execution.py` | Still fails open (`c11:1404-1411`); about 16 false-positive filters |
| R-23 | Audit-log fields (errors, attempts, verdicts, request_id) | PARTIAL | `appdb.py:150-156`; `query.py:459-479`; `turn_trace.py` | `tests/test_audit_trace_and_years.py` (untracked) | 5xx not audited (`query.py:273-296`); no `finish_reason` or tokens; live log has 0 `"outcome"` lines |
| R-24 | Accuracy counters in `/metrics` | DONE | `main.py:220-229`; `turn_trace.py:161-174` | `tests/test_audit_trace_and_years.py` | No fallback counter; per-worker only |
| R-25 | Eval run as the read-only role | NOT DONE | All 18 result files have `readonly_login: "postgres"` | – | Configure `megh_readonly`; record the effective superuser setting (`run_eval.py:286`) |
| R-26 | Fix docs that deny the eval exists | NOT DONE | `CLAUDE.md:175`; `docs/TESTING.md:14-15` | – | Update the docs |
| R-27 | Follow-ups: dropped-filter detection; REPLACE treated as cleared | PARTIAL | Cleared fields are checked (`context_policy.py:768-773`); entity refill (`c09:1384-1393`) | `test_forward_plan_wi.py:29-53` | REPLACE is not passed as cleared (`c01:1613-1631`); no "for wgh" test |
| R-28 | Knowledge → data switch | DONE | `context_manager.py:374-396`; `conversation_layer.py:787-791` | `tests/test_forward_plan_wi.py:29-35`; `test_conversation_layer.py:272-279` | A KB-fallback result also takes this branch (I) |
| R-29 | RAG score floor enforced | DONE | `rag.py:528-545,788-790` | `tests/test_rag_score_floor.py:29-42` | Floor never binds on KB v3 (`KNOWN_ISSUES.md:312`) |
| R-30 | Grounding check fails closed | NOT DONE | `rag.py:744-746,755-757` | `tests/test_rag_grounding.py:56,65` lock in fail-open | – |
| R-31 | Multilingual: enable translation | NOT DONE | `TRANSLATE_ENABLED=False` (`config.py:341`); ASR maps kha/gar to en (`llm.py:648-651`) | – | – |
| R-32 | Credential hygiene (`users.yaml`, seed password, JWT, TLS, KI-022) | NOT DONE | `app/users.yaml` tracked (`:21,27`); seed default (`appdb.py:228`); JWT only warns (`main.py:62-67`); `verify=False` (`llm.py:42-80`); KI-022 file still in history (`7064ab6`) | – | All |
| R-33 | Table allowlist (KI-004) | PARTIAL | Denylist of 3 tables only (`sql_guard.py:30-32`) | `tests/test_db_changes_2026_10_16.py:97` | No allowlist |
| R-34 | Regression cases in tests or eval | PARTIAL | See section 9 | – | "admin recurring" and "for wgh" are absent |
| R-35 | Staging tests (prod role, timeout, over-window, cache leak) | NOT DONE | No saved outputs (section 10) | – | All |

**Status counts (provisional, 35 rows):** DONE 6 · PARTIAL 16 · NOT DONE 13 · REGRESSED 0 · UNVERIFIABLE 0.

Four items have a related regression or new risk, covered in sections 5 and 8:
- R-03: the geography check is a denylist.
- R-06: the CTE bypass.
- R-20: `latest.json` is stale.
- R-25: the superuser field is misleading.

## 5. Regressions

| # | What got worse | Evidence | Severity |
|---|---|---|---|
| 1 | **Eval regressed after the 100% runs.** 100% at 18:11 and 18:15, then 97.3% at 18:42. CE-11 is wrong ("row count: gold 8, got 14") in two rechecks at 18:43 and 18:44, both with `holdout_checked: null`. The docs still report 100% | `tests/nl2sql_eval/results/2026-10-16_1842_after-followup-fixes.json`, `_1843_…`, `_1844_…` (O) | Med |
| 2 | **Eval items were edited after they failed.** FP-12 was reworded (10-16) and CE-11 was replaced (10-16); FL-12 was reworded (10-15). The scores are not like-for-like with the 78.4% baseline | `questions.yaml:527-544,690-706,837-853` (O) | Med |
| 3 | **Eval metadata is misleading.** Four runs record `superuser_allowed: false` but logged in as `postgres`, because `.env` sets `READONLY_DB_ALLOW_SUPERUSER=True` and the field records only the CLI flag | `run_eval.py:286`; `.env:159` (name only) (O) | Med |
| 4 | **Tests loosened.** One assertion now accepts either path; a state assertion was relaxed; one CM Elevate expectation was reversed (that last one is a spec change, per rule 8) | `tests/test_conversation_layer.py:328`; `tests/test_topic_memory.py:214`; `tests/test_cmelevate_usecase_fixes.py:651` (O) | Low |
| 5 | **Tests can skip silently.** `python-docx`, `pypdf` and `openpyxl` were added to `requirements.txt` but not to `requirements.lock`, so in a lock-built environment their `importorskip` tests skip. `test_fewshot_headers.py` skips in CI because `latest.json` is untracked | `requirements.txt`; `requirements.lock`; `tests/test_kb_ingest_phase2.py:104-135`; `tests/test_fewshot_headers.py:22-24` (O/I) | Low |
| 6 | **More prompt text, nothing trimmed.** `schema_context.py` is net +2.8k chars; MGNREGA few-shots +4.5k chars; `_CROSS_SCHEME` grew from 25,254 to 25,388 | `git diff` (O) | Low |
| 7 | **The verifier now runs after execution.** Generated SQL reaches the database before the semantic check, which can mean up to 4 executions and 4 30B verifier calls per turn (more on the per-scheme path) | `c11:1943,1953`; `pipeline_graph.py:461-481` (O/I) | Low |
| 8 | **Answer defaults on.** `ANSWER_DEFAULTS_ENABLED=True` answers missing area, year or tranche for "all" instead of asking. Clarifications fell, but the answers it gives are wider | `config.py:438` (O) | Low |

**Config changes, old → new** (`git diff HEAD -- app/config.py .env.example`) (O)

| Setting | Old | New |
|---|---|---|
| `SQL_VERIFY_MODEL` | `qwen4-deploy` | `qwen-model` (`:245`) |
| `QDRANT_COLLECTION` | `megh_scheme_kb` | `megh_scheme_kb_v3` (`:309`) |
| `DB_POOL_MIN_SIZE` | 10 | 1 (`:147`) |
| `.env.example` `DATABASE_URL` user | `megh_readonly` | `megh_app` |

New settings:
- **Pools:** `DB_POOL_IDLE_SECONDS=120`.
- **Read-only DB:** `READONLY_DATABASE_URL=""`, which falls back to the app login with a CRITICAL log line (`db.py:130-133`); `READONLY_DB_POOL_MIN/MAX=1/10`; `READONLY_DB_ALLOW_SUPERUSER=False`.
- **Rewrite model:** `REWRITE_MODEL=qwen35-9b`, `REWRITE_TIMEOUT_SECONDS=30`.
- **RAG:**
  - `RAG_SPARSE_MODEL=Qdrant/bm25`, `RAG_HYBRID_ENABLED=True`, `RAG_LOCAL_RERANKER=""` (off).
  - `RAG_CANDIDATES=12`, `RAG_RERANK_CHARS=800`, `RAG_MULTI_QUERY=0`.
  - `RAG_GROUNDING_CHECK=True`.
- **Translation:** `TRANSLATE_ENABLED=False`, `TRANSLATE_TIMEOUT_SECONDS=10`.
- **Answers and memory:** `ANSWER_DEFAULTS_ENABLED=True`, `CONTEXT_MEMORY_RETENTION_DAYS=30`.

Also changed: `insecure_secrets()` now flags an empty `QDRANT_API_KEY` (`:626-627`).

Unchanged: `SEMANTIC_CACHE_THRESHOLD=0.93`, `MAX_SQL_REPAIRS=3`, `SQL_EXECUTION_TIMEOUT_MS=15000`, the JWT default, and dead `SQL_GENERATION_MAX_RETRIES=1` (`:214`).

**No guard was deleted outright:**
- `db.py`: the regex `_FORBIDDEN`/`_assert_safe` was replaced by sqlglot, which is stronger.
- `auth.py`: the regex was replaced by the AST, and it now fails closed.
- `guardrails.py` and `edge.py`: regex rules were ported to `text_match`. A one-for-one parity check was not done.
- `schema_context.py`: CM Elevate rule 9a and the `?`/`->>` rule were removed because the `scheme_specific` column is now locked from the role (a data change).
- No `skip` or `xfail` was added in tracked tests, and no test function was deleted without a replacement.

## 6. Re-measured numbers

Character counts are of `schema_context.py` constants (`sed -n` | `wc -c`). Tokens = chars / 4 (an estimate). The figures leave out LIVE SCHEMA, catalog and entities, so real prompts are larger. Budget = 16,384 − 1,024 = **15,360** (`config.py:591-598`; `llm.py:332`).

**Prompt sizes**

| Scenario | Previous (est. tokens) | Now (chars) | Now (est. tokens) | Vs 15,360 | What the code does now |
|---|---|---|---|---|---|
| Largest single block: Focus Plus (17,122) + base (about 7,450) + 5 shots | – | about 26.8k | about 6.7k | under | sent as is |
| Largest required single: CM Elevate Legacy + common_mistakes 6,898 | about 6.8k | about 28.7k | about 7.2k | under | sent as is |
| CM Elevate + Focus Legacy | about 16.9k | about 69.5k | about 17.4k | **over** | few-shots compressed, then **split into one query per scheme** (`c13:1441,1463-1499`) |
| Two largest blocks: Focus Plus + Focus Legacy | – | about 71.6k | about 17.9k | **over** | per-scheme split |
| All six schemes | about 31k | about 129.9k | about 32.5k | **about 2× over** | per-scheme split |
| A single scheme over budget | – | – | – | – | few-shots cut 5 → 3 → 1, then **sent anyway** with a WARNING (`context_budget.py:138-173`) |

**Per-scheme block sizes (tables + rules + vocab)**

| Block | Chars |
|---|---|
| Focus Plus | 17,122 |
| Focus Legacy | 16,128 |
| CM Elevate | 14,593 |
| CM Elevate Legacy | 11,493 |
| MGNREGA | 9,417 |
| PMAY-G | 5,426 |
| `_CROSS_SCHEME` | 25,388 (previous 25,254) |

**`finish_reason`:** 0 hits in `app/` (O). `llm.py:273` returns `content` whatever the finish reason. A "length" stop has these effects (I):
- truncated SQL goes into the repair loop;
- truncated verifier JSON passes, because the verifier fails open;
- a truncated composer answer is shown to the user.

**Few-shots** (O). "No LIMIT" counts every SQL without a LIMIT; many of these are single-row aggregates that do not need one.

| Bank | Examples | SQL | SQL with no LIMIT | `meta.` / `staging.` | Exec result (`latest.json`, 18:13) |
|---|---|---|---|---|---|
| MGNREGA | 76 | 75 | 32 | 0 / 0 | 74 ok, 1 empty |
| PMAY-G | 74 (9 retired) | 66 | 36 | 0 / 0 | 64 ok, 2 empty |
| Focus Plus | 91 | 91 | 77 | 4 / 0 | 88 ok, 2 empty, 1 blocked (not in prompt) |
| CM Elevate | 155 (29 unanswerable) | 128 | 107 | 3 / 3 | 126 ok, 2 blocked (not in prompt) |
| Focus Legacy | 86 | 86 | 62 | 6 / 3 | 80 ok, 3 empty, 3 blocked (not in prompt) |
| CM Elevate Legacy (loaded bank) | 132 | 114 (121 with caveat SQL) | 103 | 0 / 0 | 120 ok, 1 empty |

- The loader drops examples that read `meta`, `staging` or `raw` (`annotations.py:100,133-153`) (O).
- The checker records **no DB login**. The CM Elevate `scheme_specific` examples ran "ok", which suggests `--allow-superuser` was used (I).
- Three banks were modified at 18:15, after the 18:13 run, so the result may be stale (O).
- The checker checks only that each query runs, not its values (`check_fewshots.py:1-20`).
- CI does not run the checker. `bitbucket-pipelines.yml` runs only `tests/test_*.py` (O).

**Test and regex counts:** see section 3.

## 7. Previously found problems: status

| # | Group | Status | Evidence |
|---|---|---|---|
| 1a | KI-035 beneficiaries across years | **Changed (partial)** | Focus Plus definition plus few-shot (`cross_scheme.py:73`; `focusplus_few_shot.yaml:1114-1118`). MGNREGA cross-scheme still `SUM(persons_employed)` with no year filter, plus a footnote (`cross_scheme.py:67,654-656,972-973`). KI marked "Definition added" (`KNOWN_ISSUES.md:47`) |
| 1b | KI-229 "men worked" | **Changed (partial)** | Rule 6a (`schema_context.py:308-324`) and tests (`test_business_definitions.py:66-83`). No deterministic guard (`mgnrega.py:593` is a shape check only). The ID is duplicated (`KNOWN_ISSUES.md:233,237`) |
| 1c | KI-040 households vs persons | **Changed, contradictory** | Rule 11: beneficiaries = `households_employed` (`schema_context.py:326-333`). `cross_scheme` reports beneficiaries as `SUM(persons_employed)` (`cross_scheme.py:67,~834`) |
| 1d | Lakh vs crore | **Still present** | `schema_context.py:289-294` vs `data/mgnrega/few_shot.yaml:4-5`; 24 `/ 100` lines |
| 1e | Digest sums `COUNT(DISTINCT)` | **Still present** | `c12:329-389`, labelled "authoritative" (`c13:98-113`). Example (I): the per-year Focus Plus distinct counts would be summed to 199,099, the KI-035 wrong figure |
| 2 | SQL safety | **Changed (stronger, with a new hole)** | Parser-based (`sql_guard.py:15-20,80-96`). `INTO` → `write_operation` (`:59,140-142`); `pg_sleep` → `forbidden_function` (`:68`); `app.users` → `schema_not_allowed` (`:115-118`); `-- limit` comment dropped and LIMIT appended (`:151-156,185-186`, fixed). `UPPER(lgd_district)` is unwrapped by the AST (`sql_ast.py:30-32`). `IN('<allowed>','<other>')` → denied (`sql_ast.py:334-336`; `auth.py:271-281`; test `test_sql_ast.py:67-70`). **New:** the CTE-scope bypass (`sql_guard.py:109,119,124`) |
| 3 | Database role | **Changed (code); still present (runtime)** | Superuser refused by default (`db.py:106-125`); READ ONLY transaction (`db.py:252`); separate pool. Server `statement_timeout` only in deploy SQL (`03:46`). Locally there is no `READONLY_DATABASE_URL` and the superuser override is on, so it logs in as `postgres` (KI-304) |
| 4 | Authorization | **Changed (partial)** | AST-based. Still checks the draft on attempt 0 (`pipeline_graph.py:454-462`; `c13:1516-1521`). Paths that still skip: geo lookup, village search, cross-scheme money, Focus Plus summary, Focus Legacy PG name, `/api/scheme-stats`, and deterministic queries executed on the app pool (`c13:1330-1337,1573-1579`). Admin bypass (`auth.py:235-236`) |
| 5 | Sessions and cache | **Sessions still present; cache changed** | No ownership check (`session_store.py:279-297`; `conversation_store.py:382,360-370`). The id is optional and defaults to `day-{user}-{date}` (`query.py:162-172`). Exact cache: text + scope (`cache.py:89-96`). Semantic cache: + scheme/place/year signature (`semantic_cache.py:37-49`). Context-dependent answers are no longer written (`query.py:351`). KB fallback can still be cached (I, `c14:1578-1581`) |
| 6 | Follow-ups | **Changed (partial)** | Cleared fields are checked (`context_policy.py:768-773`). REPLACE is still not treated as cleared (`c01:1613-1631`). No dropped-filter detection, only the refill from `prior_resolved` (`c09:1384-1393`). Knowledge → data switch fixed (`context_manager.py:374-396`) |
| 7 | Repair loop | **Still present** | Cap 3 (`c11:1491`). No identical-SQL stop. The hint is the missing-column or window-function hint (`c11:281-351`). The verifier is the 30B and fails open (`c11:1404-1411`), runs after execution, and its flags use up repair budget |
| 8 | Logging | **Changed (better)** | Audit: + `sql_text`, `error`, `few_shot_ids`, `repairs`, `verifier_rejections`, `outcome`, `request_id` (`appdb.py:150-156`). `/metrics` accuracy block (`main.py:220-229`). Still no `finish_reason`, tokens or cache-hit flag in the audit; 5xx not audited (`query.py:273-296`) |
| 9 | Credentials in git | **Still present** | `app/users.yaml` tracked with `password` keys (`:21,27`); hard-coded seed default (`appdb.py:228`); JWT default only warns (`config.py:472`; `main.py:62-67`); TLS `verify=False` default (`llm.py:42-80`); KI-022 CSV removed from the tree but still in history (`7064ab6`). Values not printed |
| 10 | Multilingual | **Still present** | `TRANSLATE_ENABLED=False` (`config.py:341`); UI `language` field (`query.py:53-56,158-161`); ASR maps kha/gar to en (`llm.py:648-651`) |
| 11 | RAG | **Changed (partial)** | Floor enforced (`rag.py:528-545`), but it never binds on KB v3. Grounding still fails open (`rag.py:744-757`). Reranker OFF (`config.py:269,327`). FAQ chunks are one Q&A each (`kb_ingest.py:554,584-593`). Made-up rate 14.4% (latest) |

## 8. New risks introduced

| # | Risk | Evidence | Severity |
|---|---|---|---|
| 1 | **CTE-scope bypass of the private-table and `pg_*` checks.** CTE names are collected over the whole tree, so `SELECT * FROM fact_focus_legacy_disbursement, (WITH fact_focus_legacy_disbursement AS (SELECT 1) SELECT * FROM fact_focus_legacy_disbursement) s` skips the check for the outer, real table. The DB grant does not stop it | `sql_guard.py:109,119,124`; `sql_ast.py:127-130`; `03_readonly_role.sql:55` (O code, I effect; not executed) | High |
| 2 | **Geography check is a denylist of named districts.** `lgd_district <> 'X'`, `NOT … IN`, `… OR TRUE`, `IN (SELECT …)`, and filters on other columns (`village_code`, `ac_name`, `block_name_raw`) all pass for a restricted user | `auth.py:263-305`; `sql_ast.py:298-343` (I from code) | High |
| 3 | **Rewrites after authorization change geography.** The district-list swap and the district-filter drop beside a `village_code` both run after the check on attempt 0 | `c10:642-666`; `mgnrega.py:1720-1729`; `pipeline_graph.py:454-462` (O/I) | High |
| 4 | **`/api/scheme-stats` is a new unscoped path.** Statewide totals for all six schemes, fixed SQL on the app pool, cached process-wide for 600 s. CM Elevate uses `COUNT(*)`, against rule 8's `COUNT(DISTINCT request_id)` | `routers/stats.py:24-49,92-119` (O) | Med |
| 5 | **Regexes ported to a custom backtracking engine.** About 510 `Matcher` patterns; generator backtracking (`text_match.py:187-194,227-238`); re-tokenizes on every call; no timeout. Meets the "no regex" rule in letter only | `app/text_match.py` (O/I) | Med |
| 6 | **Read-only URL falls back silently.** A blank `READONLY_DATABASE_URL` falls back to the app login with only a log line | `db.py:130-133` (O) | Med |
| 7 | **Personal data on disk.** `logs/asr_samples/` holds 3,214 voice files plus transcripts and is still growing. `frontend/undefined/*.xlsx` (possible chat exports) are untracked and not ignored. `app.answer_feedback` and `query_audit` (now with `sql_text`/`error`) have no retention | `.gitignore:14`; `config.py:295-297`; `appdb.py:150-162` (O) | Med |
| 8 | **Production code reads `tests/`.** `turn_trace.latest_eval()` globs `tests/nl2sql_eval/results` on every `/metrics` call | `turn_trace.py:138-158` (O) | Low |
| 9 | **Runtime model download.** `local_rank.py` downloads HuggingFace weights on first use and runs CPU inference on the event loop | `local_rank.py:18,46-53` (O) | Low |
| 10 | **Translation (off) would bypass guardrails.** When on, the translated text replaces the question before guardrails, and only `</message>` is stripped | `translate.py:56,70-75`; `query.py:158-161` (O/I) | Low |
| 11 | **Duplicate KB chunks.** `data/incoming/CM_Elevate*` hold byte-identical reference and FAQ files | `cmp` (O) | Low |
| 12 | **Lock drift.** `requirements.lock` is missing python-docx, pypdf and openpyxl | `requirements.txt` vs `requirements.lock` (O) | Low |
| 13 | **Stale and stray files.** `meghalaya/meghalaya/` duplicate tree (with its own `.git` and `.env`); `frontend/undefined/`; empty `constants.js` | (O) | Low |

## 9. Evaluation status

**Held-out, execution-based eval:** `tests/nl2sql_eval/` (untracked).
- 74 questions in 6 schemes: MGNREGA 13, PMAY-G 13, and 12 each for the other four.
- Difficulty: 24 easy, 32 medium, 18 hard (`questions.yaml`) (O).
- Accuracy = correct / (items − gold_error). Clarification and no-SQL outcomes count as failures (`run_eval.py:12-27,231-234`).
- The comparison ignores column names and allows 0.5% relative tolerance, unit scales and a "stated in answer" fallback (`compare.py:29-31,137-203`). That fallback fired once each in 1815 and 1842.

**Result files** (all: commit `3ce3065`, `dirty: true`, `readonly_login: "postgres"`, sql = verifier = `qwen-model`) (O)

| File | Accuracy | Correct / clarification / wrong / no SQL |
|---|---|---|
| 2026-10-15_1841_baseline | 78.4 | 58 / 9 / 6 / 1 |
| 2026-10-15_1845_baseline-2 | 75.7 | 56 / 9 / 7 / 2 |
| 2026-10-15_1850_baseline-final | 78.4 | 58 / 9 / 5 / 2 |
| 2026-10-15_2032_sqlglot-only | 79.7 | 59 / 9 / 4 / 2 |
| 2026-10-16_1248_business-definitions | 77.0 | 57 / 9 / 6 / 2 |
| 2026-10-16_1624_defs-guard-run1 | 93.2 | 69 / 0 / 1 / 4 |
| 2026-10-16_1631_fixes-1-to-4 | 94.6 | 70 / 0 / 1 / 3 |
| 2026-10-16_1711_all-fixes-run1 | 95.9 | 71 / 1 / 2 / 0 |
| 2026-10-16_1730_db-changes | 95.9 | 71 / 1 / 1 / 1 |
| 2026-10-16_1756_all-fixes-run2 | 95.9 | 70 / 0 / 2 / 1 (73 scored) |
| 2026-10-16_1757_recheck-pm04 (2 items) | 50.0 | 1 / 0 / 0 / 1 |
| 2026-10-16_1804_all-fixes-run3 | 98.6 | 73 / 0 / 1 / 0 |
| 2026-10-16_1809_defs-guard-run2 | 100.0 | 74 / 0 / 0 / 0 |
| 2026-10-16_1811_final-run4 | 100.0 | 74 |
| 2026-10-16_1815_final-run5 | 100.0 | 74 |
| **2026-10-16_1842_after-followup-fixes (latest full)** | **97.3** | 72 / 0 / 2 / 0 |
| 2026-10-16_1843 / 1844 recheck CE-11, CL-12 (2 items) | 50.0 | CE-11 wrong; `holdout_checked: null` |

**Superuser.**
- **Every run logged in as `postgres`.** Four files record `superuser_allowed: false`, but that field records only the CLI flag (`run_eval.py:286`), and `.env` sets the override on (O).
- **None of these results was produced under the read-only role.**

**Why the jump from 77% to 93%.** All 9 earlier clarifications became correct. Eight of them had been `ranking-count-not-specified`, now handled by number-word top-N parsing at `c05_clarifications.py:306-319`. That is a general app fix, not a scorer change (O/I).

**Hold-out integrity**
- The guard fuzzy-matches each whole question (rapidfuzz ratio ≥ 88) against sentences from YAML, CSV, XLSX and the strings and comments in `tests/` and `app/` (`holdout.py:40,110-171`).
- It does not scan `docs/*.md`, `data/**/*.md`, `CLAUDE.md`, JSON or gold SQL, and it misses short fragments (O/I).
- **Fragment leak:** the FP-12 fragment "12.5K registration batch payments" appears verbatim in `tests/test_general_sql_rewrites_2026_10_16.py:175` and `app/pipeline/common/c09_resolve_entities.py:20`. The test file's docstring claims "never the eval items' wording" (`:1-3`) (O).
- **Questions edited:** FL-12 was reworded (10-15), FP-12 was reworded (10-16) and CE-11 was replaced (10-16). Two of these were failing before the edit (`questions.yaml:527-544,690-706,837-853`). `CURRENT_STATE.md:35-37` discloses this and claims 72/72 on the unchanged items (O).
- No full held-out question was found in any few-shot file, based on a 15-phrase spot check (O).

**Regression cases** (O)

| Case | Present? | Where |
|---|---|---|
| admin recurring | **absent** | Not in tests or eval; only `mgnrega_schema_partitions.yaml:160,173` |
| MAWLAI | present | `tests/test_ac_full_results.py:40,72`; `tests/test_admin_level_collision.py:45` |
| "for wgh" | **absent as a follow-up** | WGH resolver cases only (`test_conversation_layer.py:30,121`; `test_admin_level_collision.py:229`) |
| 12.5K batch | present | `questions.yaml:409,476,531`; `test_focusplus_usecase_fixes.py:58-71` |
| PMAY-G follow-up | present | `test_forward_plan_wi.py:29-53`; `test_conversation_layer.py:121,272-279` |
| men worked | present | `test_business_definitions.py:66-83` |
| beneficiaries across years | present | `test_business_definitions.py:14,49,54` |
| MGNREGA employment with expenditure | present | `test_db_changes_2026_10_16.py:67-71` |
| cross-scheme | present | `test_cross_scheme_*.py` (4 files) |

**Docs.** They still say no benchmark exists (`CLAUDE.md:175`; `docs/TESTING.md:14-15`), although `TESTING.md:105` itself logs an eval run (O).

**RAG eval** (`tests/rag_eval/results/`, 14 summary files, no git or settings metadata)

| Run | Correct | Wrong | Made-up |
|---|---|---|---|
| Latest: kbv3_after_floor (10-16 18:33) | 90.2% | 3.7% | 14.4% |
| Previous audit: phase5_final | 91.5% | 6.1% | 16.0% |

The judge is the same 9B model that composes the answer and runs the grounding check (`tests/rag_eval/run_eval.py:20,72-78`) (O).

## 10. Staging tests

The board's staging-test list was not available, so these are the staging checks named in the previous audit (`error one.md:480-491`) and the brief.

| Test | Saved evidence? |
|---|---|
| Production DB role / `rolsuper` / `statement_timeout` on the read-only pool | **Not run.** KI-304 (`KNOWN_ISSUES.md:313`) and `CURRENT_STATE.md:18` say it still logs in as `postgres` |
| Over-window prompt behaviour (gateway 400 → fallback) | **Not run.** No log evidence; the per-scheme split now avoids the multi-scheme case |
| SQL truncated at 1,024 tokens | **Not run.** `finish_reason` is not logged |
| Semantic-cache wrong-year hit | **Not run** |
| Cross-user cache leak | **Not run** |
| Auth bypass with `IN` / `UPPER` for a geo-restricted user (live) | **Not run.** Unit tests only (`test_sql_ast.py:62-91`) |
| Checkpointer backend in production | **Not run.** No startup log line saved |
| Load / performance | **Not run.** `TESTING.md:255` says "None" |
| Smoke after the restructure | **Not run.** `TESTING.md:55,248` says `smoke_restructure.py` was not run |
| Pen test | No evidence |

## 11. Claims vs code

| # | Claim | Code / fact |
|---|---|---|
| 1 | `CLAUDE.md:110` (and `AI_PIPELINE.md:19,577`, `README.md:216,422,967`): the verifier is `qwen4-deploy` | `config.py:245` `SQL_VERIFY_MODEL="qwen-model"` (30B) |
| 2 | `CLAUDE.md:113`, `data/incoming/README.md:70-72`: jina reranker "on" | `config.py:327` `RAG_LOCAL_RERANKER=""` (off); `config.py:269` `RERANKER_ENABLED=False` |
| 3 | `CLAUDE.md:175`, `TESTING.md:14-15`: no NL→SQL benchmark exists | `tests/nl2sql_eval/` with 18 result files |
| 4 | `CLAUDE.md:162-166`: "27 pytest-style files … 1,453 passed". `TESTING.md:34`: 46 files. `CURRENT_STATE.md`: 2,667 passed | 73 pytest-style files, 1,341 `def test_` (static count; pass counts not verifiable) |
| 5 | `CLAUDE.md:166-167`, `CURRENT_STATE.md:262`, `HANDOFF.md:200,242`: results "with the graph off AND on" | No switch or sequential driver (`CLAUDE.md:45-47`; `pipeline_graph.py`) |
| 6 | `CLAUDE.md:146`: "only the prompt protects" the privacy tables | `sql_guard.py:30-32,123-128` refuses them in code (but see the CTE bypass) |
| 7 | `CLAUDE.md:13,128`: KB docs live in `data/reference/` | Deleted; `kb_ingest.py:5,40` reads `data/incoming/` |
| 8 | `config.py:350-354`: grounding brings made-up answers to 9.8% | That figure was measured with the reranker, which is now off; latest is 14.4% (`kbv3_after_floor`) |
| 9 | `tests/test_general_sql_rewrites_2026_10_16.py:1-3`: "never the eval items' wording" | `:175` uses FP-12's "12.5K registration batch payments" |
| 10 | Eval results `superuser_allowed: false` (1248, 1624, 1809, 2032) | Logged in as `postgres`; the flag records only the CLI argument (`run_eval.py:286`) |

Other stale items:
- `AI_PIPELINE.md:8` names the deleted `app/pipeline.py` as the source of truth.
- `prompt_builder.py:133` labels the few-shots "verified SQL" while five banks still say "NOT ONE … EXECUTED".
- `KNOWN_ISSUES.md` has duplicate IDs: KI-228, KI-229, KI-230, KI-231 and KI-304.
- `CURRENT_STATE.md:3` says "Last updated 2026-10-13" but has 10-16 entries.
- The docs do not mention the 18:42 regression to 97.3%.

## 12. Scorecard

**Scoring rule.** Every change sits in the uncommitted or untracked working tree. Under the brief's rule, each score rises by **at most 1**, and each raised justification says so.

| # | Dimension | Before B | Now | Change | Justification | Evidence |
|---|---|---|---|---|---|---|
| 1 | Orchestration structure and testability | 2 | 2 | 0 | Same 22-node graph; still one exec'd namespace (now 26k lines); a per-scheme branch was added inside a node | `pipeline_graph.py:448-451,574-612`; `app/pipeline/__init__.py:55-57` |
| 2 | Typed conversation state | 2 | 2 | 0 | Typed dataclass unchanged; pending clarification still loose fields; `turn_context`/`topics` untyped | `session_store.py:38-84,132-149,207-212` |
| 3 | Follow-up correctness | 2 | 2 | 0 | Cleared-field check and knowledge → data switch added; REPLACE still not treated as cleared; no dropped-filter detection; no "for wgh" test | `context_policy.py:768-773`; `c01:1613-1631`; `context_manager.py:374-396` |
| 4 | Schema retrieval | 1 | 1 | 0 | Still scheme-scoped, not per question; column names only (no types or PKs); private tables now filtered | `prompt_builder.py:76-110`; `schema_introspect.py:240-273` |
| 5 | Context budget and truncation | 1 | 2 | +1 | Over-budget multi-scheme prompts split into per-scheme queries, with a test. Single-scheme overflow still sent; `finish_reason` 0 hits. Untracked, so capped at +1 | `c13:1441,1463-1542`; `tests/test_per_scheme_sql.py`; `llm.py:273` |
| 6 | Cross-scheme handling | 1 | 2 | +1 | Large combined prompts gone (per-scheme split); deterministic fan-out kept. MGNREGA SPECS still sum across years; `combined_total_crore` contradiction. Uncommitted, capped | `c13:1441`; `cross_scheme.py:67,654-656`; `schema_context.py:1414-1419` |
| 7 | Metric and unit definitions | 1 | 1 | 0 | Definitions added, but still 3+ sources; lakh/crore unchanged; `cross_scheme` contradicts rule 11; digest sums distinct counts | `schema_context.py:289-294,326-333`; `few_shot.yaml:4-5`; `c12:329-389` |
| 8 | Prompt and few-shot quality | 1 | 2 | +1 | All 567 few-shots executed once; unreadable-schema examples dropped from the prompt. "Verified" header still there; the run is stale (bank edits after it) and probably as superuser; not in CI. Untracked, capped | `tests/fewshot_exec/results/latest.json`; `annotations.py:100,133-153`; `prompt_builder.py:133` |
| 9 | Repair loop | 2 | 2 | 0 | Unchanged: cap 3, error and column hints; no identical-SQL stop; verifier flags use up the budget | `c11:1491,281-351`; `pipeline_graph.py:461-481` |
| 10 | Verification | 2 | 2 | 0 | Verifier now after execution (tested) but still fails open; about 16 false-positive filters | `c11:1404-1487,1943-1972`; `tests/test_verifier_after_execution.py` |
| 11 | SQL validation | 2 | 2 | 0 | Private-table denylist and comment-safe LIMIT added (tested), but a new CTE-scope bypass; no table allowlist; still untracked | `sql_guard.py:30-32,109-128,151-189`; `tests/test_sql_guard.py` |
| 12 | Database privileges | 2 | 2 | 0 | Code refuses superuser and has a read-only pool (tested); in practice still `postgres`, override on, privacy tables granted, server timeout only in deploy SQL | `db.py:106-148,252`; `03_readonly_role.sql:46,55`; KI-304 |
| 13 | Authorization | 1 | 1 | 0 | AST-based (UPPER and IN fixed, tested), but attempt-0 rewrites unchecked, about 6 paths skip, denylist logic passes `<>`/`OR TRUE`, admin bypass | `auth.py:220-305`; `pipeline_graph.py:454-462`; `c13:1112,1330-1337,1573-1579`; `stats.py:92-119` |
| 14 | Privacy of sensitive columns | 1 | 2 | +1 | LIVE SCHEMA filtered and 3 private tables refused in code (tested). The DB grant still covers them, the CTE bypass exists, there is no column denylist, and the KI-022 file is in history. Untracked, capped | `schema_introspect.py:240-273`; `sql_guard.py:30-32`; `tests/test_db_changes_2026_10_16.py:75-104` |
| 15 | Cache correctness | 1 | 2 | +1 | Context-dependent answers no longer written; semantic cache matches scheme, place and year (tested). Measure and number not compared; KB fallback cacheable; router write path untested. Capped | `query.py:351`; `semantic_cache.py:37-104`; `tests/test_forward_plan_wi.py:65-104` |
| 16 | Logging and tracing | 2 | 2 | 0 | Audit and `/metrics` much richer (an improvement), but 5xx not audited, no `finish_reason`, the live log shows none of the new fields, and `turn_trace` is untracked. Not yet at 3 | `appdb.py:150-156`; `turn_trace.py`; `main.py:220-229`; `query.py:273-296` |
| 17 | Accuracy evaluation | 2 | 2 | 0 | More runs and a compare tool, but every run is as `postgres` with a misleading flag, failing items were reworded, a fragment leaked, the latest run regressed to 97.3%, and the docs deny the eval exists | `results/*.json`; `run_eval.py:286`; `questions.yaml:527-853`; `CLAUDE.md:175` |
| 18 | Clarification behaviour | 1 | 2 | +1 | Number-word top-N and answer defaults: eval clarifications 9 → 0; logs 3/26 on 10-15 and 0/5 on 10-16. About 51 `ClarificationNeeded` sites remain. Uncommitted, capped | `c05_clarifications.py:306-319`; `config.py:438`; `logs/query_audit.jsonl` (counts) |
| 19 | RAG quality controls | 2 | 2 | 0 | Floor enforced (tested) but never binds; grounding fails open; made-up 14.4%; reranker off; self-judging eval | `rag.py:528-545,744-757`; `tests/rag_eval/results/2026-10-16_kbv3_after_floor.json` |
| 20 | Multilingual handling | 1 | 1 | 0 | Unchanged: translation off, ASR maps kha/gar to en | `config.py:341`; `llm.py:648-651` |
| 21 | Maintainability | 1 | 1 | 0 | Regex count is 0, but about 510 patterns moved into a custom matcher; 26k exec'd lines; nothing committed; duplicate tree; 10+ stale docs; duplicate KI IDs | `text_match.py`; `app/pipeline/__init__.py:55-57`; `git status` |
| 22 | Reusable assets | 2 | 2 | 0 | Resolver, `sql_guard` and the faithfulness guard kept; new `sql_ast` is reusable; join graph still only prohibited edges; catalog YAMLs partly unused | `sql_ast.py`; `annotations.py:465-476`; `schema_introspect.py:133,474` |
| | **Total (out of 66)** | **33** | **39** | **+6** | | |

## 13. Top 10 remaining problems

| Rank | Problem | Evidence | Impact | Board item |
|---|---|---|---|---|
| 1 | Nothing committed; safety-critical code (`sql_guard`, `sql_ast`, `app/pipeline/`, `03_readonly_role.sql`) untracked; the tree changed during the audit | `git status`; HEAD `3ce3065` | High | R-01 |
| 2 | Authorization: attempt-0 rewrites unchecked; about 6 paths skip; the denylist passes `<>`, `NOT IN`, `OR TRUE` and other columns | `pipeline_graph.py:454-462`; `c13:1516-1521`; `auth.py:263-305`; section 7 #4 | High | R-02, R-03, R-04, R-05 |
| 3 | CTE-scope bypass of the private-table and `pg_*` checks, and the DB grant still covers the privacy tables | `sql_guard.py:109,119,124`; `03_readonly_role.sql:55` | High | R-06, R-33 |
| 4 | App and eval still run as `postgres` with the superuser override on | `.env:159` (name); KI-304; `results/*.json` | High | R-07, R-25 |
| 5 | No session ownership check (read and write) | `session_store.py:279-297`; `conversation_store.py:360-382` | High | R-09 |
| 6 | Wrong-number traps: digest sums distinct counts; lakh/crore; MGNREGA beneficiaries contradiction; no men-worked guard | `c12:329-389`; `schema_context.py:289-294,326-333`; `cross_scheme.py:67` | High | R-15–R-19 |
| 7 | `finish_reason` never checked; single-scheme overflow still sent | `llm.py:273`; `context_budget.py:138-173` | Med | R-13, R-14 |
| 8 | Eval integrity: failing items reworded, a fragment leaked into tests and code, latest run regressed, results not as the read-only role | `questions.yaml:527-853`; `test_general_sql_rewrites_2026_10_16.py:175`; `results/…_1842…` | Med | R-25, R-26 |
| 9 | Credentials: tracked `users.yaml` passwords, seed default, JWT default only warns, TLS `verify=False`, KI-022 in history; voice recordings on disk | `users.yaml:21,27`; `appdb.py:228`; `main.py:62-67`; `llm.py:42-80`; `logs/asr_samples/` | Med | R-32 |
| 10 | Grounding fails open; KB fallback cacheable and labelled "knowledge"; repair has no identical-SQL stop | `rag.py:744-757`; `c14:1578-1581`; `c11:1976-1990` | Med | R-12, R-21, R-30 |

## 14. Recommended next steps

None of these was applied.

1. **Commit the working tree** on a branch: `app/pipeline/`, `sql_guard.py`, `sql_ast.py`, `deploy/sql/03_readonly_role.sql`, `tests/nl2sql_eval/`. Delete `meghalaya/meghalaya/` and `frontend/undefined/`, and add the ASR sample directory to a retention policy.
   - **Test:** CI runs on the committed tree; `git status` is clean.
2. **Authorize the SQL that actually runs.** In `pipeline_graph.py:455`, drop the `if attempt:` condition so `_repaired_sql_denial` runs on every attempt. Make the same change in `c13:1517`.
   - **Test:** a rewrite that swaps `district_list` for a restricted user is denied.
3. **Make the geography check positive, not a denylist** (`auth.py:263-305`). Require every geography predicate to be an AND-ed equality or IN over allowed values. Refuse `<>`, `NOT`, `OR` across geography, and subqueries for geography-restricted users. Also check `village_code`, `ac_name` and `block_name_raw`.
   - **Test:** add cases in `tests/test_sql_ast.py`.
4. **Fix the CTE scope** in `sql_guard.py:109`. Resolve each `exp.Table` against the CTEs visible in its own scope (sqlglot `optimizer.scope`), and add `REVOKE SELECT` on the three private tables in `03_readonly_role.sql`.
   - **Test:** a nested-CTE case in `tests/test_sql_guard.py`.
5. **Close the authorization-skipping paths:**
   - `c13:1112-1140`, `c13:597-640`, `c06:561-569`, `focus_plus.py:146`, `focus_legacy.py:968-1011` and `stats.py:92-119`: scope each one.
   - `c13:1330-1337,1573-1579`: authorize the executed text and run it through `run_readonly`.
   - **Test:** one restricted-user test per path.
6. **Add a session ownership check** in `session_store.ensure` (`:279-297`) and in `conversation_store` load/save (`:360-382`). Refuse when the session's `user_id` differs from the caller's.
   - **Test:** a second user cannot read or append to the session.
7. **Configure `megh_readonly`.** Set `READONLY_DATABASE_URL`, turn off `READONLY_DB_ALLOW_SUPERUSER`, and refuse to start when it is blank in prod (`db.py:130-133`). Record the effective superuser setting in `run_eval.py:286`, then re-run the eval.
   - **Test:** the result shows `readonly_login: megh_readonly`.
8. **Handle `finish_reason`** in `llm.py:273`: log it and treat "length" as an error for SQL and verifier calls.
   - **Test:** a stubbed "length" response.
9. **Fix the wrong-number traps:**
   - `c12:329-389`: skip sums for distinct-count, percentage and constant columns.
   - Align `few_shot.yaml:4-5` with `schema_context.py:289-294`.
   - `cross_scheme.py:67`: use `households_employed` and require a year.
   - **Test:** extend `test_business_definitions.py`.
10. **Few-shots:**
    - Change `prompt_builder.py:133` to "example SQL".
    - Remove the "NOT ONE … EXECUTED" lines once a run passes.
    - Run `check_fewshots.py` as the read-only role, in CI or pre-merge, and check values, not just execution.
11. **Repair loop:** in `c11:1976-1990`, stop when the new SQL normalizes to the same text as the previous attempt.
    - **Test:** a stubbed repeat.
12. **Docs:** fix the 10 mismatches in section 11, de-duplicate the KI IDs, and report the 97.3% run and the reworded items.

## 15. Not verified

| Item | What would confirm it |
|---|---|
| The CTE-scope bypass reaches the private table | A `sql_guard.assert_readonly` call on the nested-CTE query in a scratch test, then the same query on the read-only pool in staging |
| Geography denylist bypass (`<>`, `OR TRUE`) | An `authorize` decision log for a geo-restricted test user on those SQL shapes |
| Attempt-0 rewrite changes the district after authorization | A `pipeline_graph_node node=execute_attempt` log line showing the SQL differing from the authorized draft for a restricted user |
| Production role and `statement_timeout` | `SELECT current_user, rolsuper, current_setting('statement_timeout')` on the read-only pool in prod |
| Truncation at 1,024 tokens | An `llm_call role=sql completion_tokens=1024` line (needs `finish_reason` logging) |
| Single-scheme overflow behaviour | A `prompt_context … over_budget=true` line, then a gateway 4xx or the fallback, for one request_id |
| Semantic-cache measure confusion | A `semantic_cache hit` log line for "houses sanctioned" vs "houses completed" with the same place and year |
| The new audit fields are populated | A `query_audit.jsonl` line with `"outcome"` after a server restart; currently 0 such lines |
| Few-shot results under the read-only role | Re-running `check_fewshots.py` without `--allow-superuser` once `megh_readonly` exists |
| Whether the 100% runs are reproducible | A fresh full eval on a committed tree; the latest is 97.3% |
| Checkpointer backend | The startup log line "pipeline_graph: compiled, 22 nodes, checkpointer=postgres" |
| `text_match` worst-case cost | A timing of the guardrail matchers on long adversarial input in a staging benchmark |

## 16. Suspicious instructions found

None. `*.md`, `*.py`, `*.yaml`, `*.json`, `*.txt`, `*.js` and `*.jsx` were searched for text aimed at an AI or auditor ("ignore previous", "as an AI", "do not report", "auditor", "note to the AI"). The only hits are benign:
- a chatbot reply string (`app/conversation_replies.py:379`);
- a domain rule (`data/focus_legacy/focuslegacy_entity_resolver.yaml:920`);
- a prompt-injection test input (`tests/test_guardrails.py:50`);
- references to "audit 2026-10-15" as the reason for a fix (`rag.py:531`; `KNOWN_ISSUES.md:312`).

## 17. Read-only confirmation

**Commands used**
- **git:** `branch --show-current`, `rev-parse HEAD`, `rev-parse --show-toplevel`, `log` (with `-1`, `--oneline`, `--all --name-status`), `status --short`, `diff --stat`, `diff --numstat`, `diff HEAD -- <files>`, `show HEAD:<file>`, `ls-files`, `branch -a --contains`, `merge-base --is-ancestor`, `remote -v`, `check-ignore`.
- **shell:** `ls`, `find … -newermt` (listing only), `cat`, `sed -n`, `head`, `grep`/`grep -c`/`grep -n`, `wc -l`, `wc -c`, `sort`, `uniq`, `cut`, `awk` (summing counts), `cmp -s`, `md5sum` (over grep output), `du`, `date`.
- **tools:** Read, Grep and Glob.

**Main files read**
- **Baseline:** `documents/error one.md`.
- **Docs:** `CLAUDE.md`; `docs/{KNOWN_ISSUES,TESTING,CURRENT_STATE,HANDOFF,AI_PIPELINE}.md` (parts); `data/incoming/README.md` (grep).
- **Pipeline and graph:** `app/pipeline_graph.py`; `app/pipeline/__init__.py`; `app/pipeline/common/c01,c03,c05,c06,c09,c10,c11,c12,c13,c14` (ranges); `app/pipeline/schemes/*.py` (ranges).
- **Safety and DB:** `app/sql_guard.py`, `app/sql_ast.py`, `app/db.py`, `app/auth.py`.
- **Prompt and schema:** `app/schema_context.py`, `app/prompt_builder.py`, `app/context_budget.py`, `app/annotations.py`, `app/schema_introspect.py`, `app/cross_scheme.py`.
- **State and cache:** `app/session_store.py`, `app/conversation_store.py`, `app/routers/query.py`, `app/cache.py`, `app/semantic_cache.py`, `app/context_policy.py`, `app/context_manager.py`, `app/conversation_layer.py`.
- **Logging and new modules:** `app/turn_trace.py`, `app/appdb.py`, `app/main.py`, `app/routers/stats.py`, `app/routers/feedback.py`, `app/local_rank.py`, `app/text_match.py`, `app/translate.py`.
- **Model and RAG:** `app/llm.py`, `app/rag.py`, `app/kb_ingest.py`, `app/config.py`.
- **Data and deploy:** `data/*/*few_shot*.yaml`; `deploy/sql/01_create_megh_app_role.sql`, `deploy/sql/03_readonly_role.sql` (password lines redacted); `bitbucket-pipelines.yml`; `requirements.txt`, `requirements.lock`.
- **Eval and tests:** `tests/nl2sql_eval/*` and all 18 result files; `tests/rag_eval/run_eval.py` and result summaries; `tests/fewshot_exec/check_fewshots.py`, `results/latest.json`; selected `tests/test_*.py`.
- **Logs:** `logs/query_audit.jsonl` (counts only).
- **Secrets:** `.env` (flag names and non-secret flag lines only; no secret values).

**Confirmed**
- No repo file, code, data, setting or git state was changed.
- No test, eval runner, app code or app import was run, and no network, LLM, Qdrant, Redis or database call was made.
- No secret value or personal-data row appears in this report.

**Disclosures**
1. **The report file.** The brief says the report goes in chat, not on disk. At the user's explicit request, this report was written to `meghoneai/documents/RAM report.md`. That file is outside the audited `meghalaya/` repo, and it is the only file created.
2. **An interpreter was started.** One read-only sub-investigator ran a compound shell command that began with a no-op `python -c "pass"`. It ran no repo code and changed nothing, but starting an interpreter is outside the brief's allowed commands.
3. **A secret appeared in internal output.** One sub-investigator's grep echoed the default seed-password literal from `app/appdb.py:244` into its own internal tool output. It appears nowhere in this report.
