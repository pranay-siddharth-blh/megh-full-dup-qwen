# NL2SQL Comparison Audit Report

## 1. Identity
- **Repo audited:** `C:\Users\Admin\OneDrive\Desktop\MCP\meghoneai\meghalaya` (O).
  - It is a nested git repo. The outer repo `meghoneai` is on branch `Main` at `90c83a1` ("Remove all code", 2026-10-03). There the code is untracked (O).
- **Branch / commit:** `Update/2026-10-13`, HEAD `3ce306515a20258973db263e49a89e25c58cfbca`, last commit 2026-10-13 18:51 +0530 (O).
- **The audit covers the working tree, not HEAD.** It has 927 changed or untracked paths. `app/pipeline.py` is deleted (O).
  - The new `app/pipeline/` package is untracked, and so are `app/sql_guard.py` and `deploy/sql/03_readonly_role.sql` (O). So several key safeguards exist only on disk, not in git.
  - There is also a stale duplicate tree at `meghalaya/meghalaya/{app,data,tests}` (O).
- **Orchestration:** LangGraph `StateGraph` with 22 nodes and a checkpointer (`app/pipeline_graph.py:588-609`). The nodes wrap stage functions in `app/pipeline/` (O).
- **Schemes (from code):** 6. `_ALL_SCHEMES` (`app/pipeline/common/c01_followups.py:637-638`) lists MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate and CM Elevate Legacy (O).

**Models.** All run on a vLLM gateway. Context windows come from `app/config.py:575-578`.

| Role | Model | max_tokens | Context (input budget) | Evidence |
|---|---|---|---|---|
| SQL generation + repair | `qwen-model` (qwen3-coder-30B) | 1024 | 16,384 (15,360) | `config.py:200`, `llm.py:332`, `config.py:577` |
| SQL verifier | `qwen-model` (30B) | 200 | 16,384, but budgeted at 7,992 (stale) | `config.py:236`, `llm.py:444`, `context_budget.py:65` |
| Classifier / router / guardrail | `qwen4-deploy` (Qwen3-4B) | 200 | 8,192 (7,992) | `config.py:185`, `llm.py:289` |
| Follow-up rewrite / rephrase | `qwen35-9b` | 200 / 120 | not recorded | `config.py:194`, `llm.py:296-316` |
| Composer | `qwen35-9b` | 800 | not recorded, so the budget is 0 (unchecked) | `config.py:210-214`, `config.py:579-583` |
| Embeddings (RAG + semantic cache) | local `BAAI/bge-small-en-v1.5` (384-d) | – | – | `config.py:247-248` |
| Reranker | local jina-reranker-v1-turbo on; remote qwen3-reranker off | – | – | `config.py:316`, `config.py:260` |
| ASR | `qwen3-asr` | – | – | `config.py:267` |

## 2. Executive summary
**How it is built.** It is LangGraph over a 22-node chain. Each node is a thin wrapper over a stage function. The stage functions live in ~18.9k lines that `exec()` into one shared namespace. The design is "prompt rule + few-shot + deterministic guard", using hand-written per-scheme schema prose and a sqlglot SQL guard.

**Top 5 problems:**
1. **Authorization is incomplete.** It checks the draft SQL before attempt-0 rewrites, about 6 answer paths skip it, and the district regex misses `UPPER()` and later items in an `IN` list.
2. **The privacy tables are protected by prompt text only.** They are in the LIVE SCHEMA, and the read-only role is granted all of `curated`.
3. **The SQL prompt for two large schemes, or all schemes, exceeds the model window and is still sent.** `finish_reason` is never checked.
4. **Context-dependent questions are cached for the whole scope**, and there is no session ownership check.
5. **Metrics and units have no single source of truth.** Few-shots are labelled "verified" but were never executed, and some contradict the rules.

**Top 3 strengths:** the sqlglot read-only guard with a READ ONLY transaction and a separate role; the typed `ConversationState` with a KEEP/REPLACE/CLEAR merge plan and provenance check; and a held-out, execution-based NL→SQL eval (78.4%).

**Confidence:** medium-high on static findings; runtime behaviour is not verified.

## 3. Size and structure table
| Item | Value | Evidence |
|---|---|---|
| `app/schema_context.py` | 1,613 lines (115,401 bytes) | `wc` (O) |
| `c13_compose_and_data_stages.py` | 1,613 | (O) |
| `data/cm_elevate/prompt_assembler.py` (offline only) | 1,590 | (O) |
| `app/entity_resolver.py` | 1,558 | (O) |
| `c09_resolve_entities.py` | 1,514 | (O) |
| `c11_sql_verify_repair.py` | 1,352 | (O) |
| `data/focus_plus/prompt_assembler.py` | 1,313 | (O) |
| `c14_turn_stages.py` | 1,294 | (O) |
| `schemes/cm_elevate.py` | 1,240 | (O) |
| `schemes/mgnrega.py` | 1,207 | (O) |
| Orchestrator `app/pipeline_graph.py` | 870 | (O) |
| `app/pipeline/` package total (20 exec'd files) | 18,888 lines, 518 `def`s | (O) |
| Test files | 76 `.py` in `tests/`: 72 `test_*.py`, of which 58 pytest-style and 14 plain scripts | (O) |
| Test functions | 1,212 `def test_` (static count) | `grep -c` (O) |
| Docs claim | "27 pytest-style files", "1,453 pytest passed", "14/14 scripts", "30,280/30,280", "43/43" | `CLAUDE.md:158-164` (O); 27 is stale |
| `re.compile(` | 633 in `app/`, 463 in `app/pipeline/` | (O) |
| `re.compile/search/sub/match` in the SQL path | 525 (c10 40, c11 65, c13 42, schemes 378) | (O) |
| SQL rewrites run before execution | ~42 calls in `_scheme_sql_rewrites` | `c11:1045-1090` (O) |
| Deterministic guards in `_execute_one_attempt` | ~25 | `c11:1098-1308` (O) |
| Verifier false-positive filters | ~15 | `c11:942-1013` (O) |
| Clarification gates | ~30 distinct rules | see 3.10 |

## 4. Findings per area

### 3.1 Orchestration
**Graph structure**
- **Nodes:** context, edge, followup, rephrase, route, knowledge, data_context, scope_scheme, entities, clarification_gate, deterministic, sql_generate, authorize, execute_attempt, repair, post_rows, compose, guarantees, assemble, pause_gate, finalize, context_update (`pipeline_graph.py:565-575`) (O).
- **Edges:** linear conditional edges `_CHAIN` (`:578-585`), each going to next / `pause_gate` / `finalize` (`:593-595`) (O).
  - `route` branches to knowledge or data (`:596-598`).
  - `execute_attempt` branches to repair or post_rows (`:599-601`).
  - `repair` goes back to `execute_attempt` (`:602-604`).
  - `pause_gate` goes to `context` (`:606`).
  - `finalize` goes to `context_update`, then END (`:607-608`) (O).
  - The `knowledge` node chains on to `data_context` when it produces no response (`:579`) (O).
- **Not used:** `Send` fan-out and sub-graphs (O, by grep).

**Checkpointer and thread**
- The checkpointer is `AsyncPostgresSaver` in `app.*`, falling back to `InMemorySaver` on Windows or on error (`:657-717`). It uses `JsonPlusSerializer(pickle_fallback=True)` (`:634-638`) (O).
- `thread_id = session.session_id`, or `graph-<uuid>` when there is no session (`:760`) (O).
- The thread is deleted after every completed answer (`:780-798`), so checkpoints effectively store only paused clarification runs. A paused run holds the full state, including rows and SQL (`:74-123`) (O).

**Nodes vs stage functions**
- Nodes hydrate state and call `pipeline._turn_*_stage` / `_data_*_stage` (`:323-430`). Exceptions are the logic inside `node_execute_attempt` (rewrites, re-authorization on repair, budget; `:439-468`) and `node_pause_gate` (`:500-514`) (O).
- The `_observed` wrapper logs one record per node and maps DATA failures to `_data_path_error_result` (`:261-319`) (O).

**Testability**
- Each node exposes `stage_fn` (`:316`), and `tests/_graph_turn.py` drives turns (O).
- Stage functions live in files `exec`'d into one global namespace (`app/pipeline/__init__.py:28-56`). A single file cannot be imported alone, and tests monkeypatch private names (I).

### 3.2 State and follow-ups
**Typed state**
- `ConversationState` dataclass (`session_store.py:38-84`) (O):
  - geography and time: scheme, district, block, village, year, previous_year, year_all
  - measure: metric, tranche, last_dimension
  - comparison_entities, last_intent, `provenance{value, source, confidence, turn}`
- Pending clarification sits on `Session`: `pending_scope_q/rule/options` (`:132-149`) (O).
- Persisted to `app.conversations.context_state` with a rev guard (`conversation_store.py:332-358`) (O).

**Follow-up resolution: a hybrid**
1. A regex gate, `looks_like_followup` (`c01:465-519`) (O).
2. A deterministic `plan_state_merge` with KEEP / REPLACE / CLEAR / REQUIRE_CLARIFICATION per field (`context_policy.py:382-475`). A coarser geography change clears the finer levels (`:423-427`) (O).
3. A 9B model rewrite (`c01:930-1036`) (O).
   - The model sees: an instruction to take filters only from given context; the Known-context block; the PREVIOUS question; PREVIOUS filters; the previous result only for result-references; a "REMOVED … do NOT include" line; then the FOLLOW-UP (`c01:1008-1036`, `context_manager.py:686-742`).
4. A provenance check, `rewrite_violation` (`context_policy.py:571-640`). It rejects re-introduced cleared values and invented values, and falls back to the raw fragment (`c01:961-971`) (O).

**Gaps**
- **No dropped-filter detection** apart from the metric family (`context_policy.py:619-626`). KEEP filters are refilled afterwards from `prior_resolved` (`context_manager.py:266-280`, `c09:1355-1364`) (O).
- A REPLACE is not passed to the check as "cleared" (`c01:1080-1097`) (O).

**Knowledge turn mid-conversation**
- `update_state` returns early for non-data routes (`context_manager.py:377-385`), so scheme, district and year stay as before (O).
- The thread state is reset if the knowledge turn named a different scheme (`c03:171-190`) (O). For the same scheme, the old district and year persist (I).

**Session handling**
- The session id is optional. With none, the user gets a per-day bucket `day-{user}-{date}` or a one-off id (`routers/query.py:159-169`) (O).
- Idle expiry is 1,800 s (`config.py:370`, `conversation_layer.py:612-630`). Eight turns are kept in memory; the snapshot keeps the last turn plus 8 questions (`session_store.py:195-212`) (O).
- **There is no ownership check.** `ensure()` returns any existing session regardless of user (`session_store.py:278-284`), and `load_context_state` selects by `session_id` only (`conversation_store.py:368-370`) (O).

### 3.3 Schema and context
**How the schema gets into the prompt**
- The schema is hand-written prose per scheme, concatenated by scheme list (`schema_context.py:1590-1609`). It is not retrieved per question (O).
- It is augmented, when the DB is reachable at startup, with:
  - a LIVE SCHEMA block of column names only, from `information_schema` (`prompt_builder.py:78-100`);
  - real FKs (`:102-110`);
  - a LIVE CATALOG from the `semantic.*` tables, capped at 30 tables, 24 terms and 20 metrics (`schema_introspect.py:212-296`) (O).
- Embeddings are not used for schema selection (O).

**What is and isn't included**
- Column types: no. PKs: not listed. Join keys and allowed edges: not sent; only the "NEVER join" prohibited edges are (`annotations.py:394-405`) (O).
- Allowed values: hand-written for a few fields only (`schema_context.py:167-188`, `:310-312`) (O).

**Budget handling**
- Over budget, only few-shots (5 → 3 → 1) and catalogue duplicates are compressed. Required sections are sent over budget with a WARNING (`context_budget.py:138-173`) (O).
- `finish_reason` has 0 hits; `llm.py:274` returns `content` blindly (O).

**Cross-scheme questions**
- Comparisons go to a deterministic per-scheme fixed-SQL fan-out (`cross_scheme.py:173-213`, `:572`) (O).
- Questions matching `_OTHER_MEASURE` (`:118-130`, `:181-182`) instead go to one prompt containing every named scheme plus the 25 KB `_CROSS_SCHEME` block (`schema_context.py:1601-1602`) (O).

### 3.4 Metric and unit definitions
**No single source of truth.** Definitions are spread over at least six places (O):
- `SCHEME_METRICS` prose (`schema_context.py:51-127`)
- per-scheme RULES and VOCAB strings
- `cross_scheme.SPECS` (`cross_scheme.py:64-95`)
- `semantic.metric_definitions` (`schema_introspect.py:246-251`)
- `dim_scheme.money_unit` (`schema_context.py:146`)
- the YAML few-shots

The model writes free-form SQL; it never picks a metric id (O).

**Contradictions**
- **C1 (O):** the MGNREGA rule says "do NOT divide by 100 to convert to CRORE" for MGNREGA-only questions (`schema_context.py:265-270`). The few-shot header says "converts lakh to crore" (`data/mgnrega/few_shot.yaml:4`), and 24 lines use `/ 100`.
- **C2 (O):** `cross_scheme.py:53` says money is "in RUPEES" for all specs. The prompt says Focus Plus and Focus Legacy units are UNVERIFIED (`schema_context.py:27,36`).
- **C3 (O):** "Every query MUST end with a LIMIT" (`schema_context.py:222`), but about two-thirds of few-shots have no LIMIT.
- **C4 (O):** "Never query raw, staging or meta" (`schema_context.py:141`), yet few-shots query `meta`/`staging` (`cmelevate_few_shot.yaml:1645,1657`; `focuslegacy_few_shot.yaml:947,955,967`; `focusplus_few_shot.yaml:1103`). These would be rejected by `sql_guard.py:24` (I).

**Known traps**
- **Distinct counts across years:** guarded by a prose rule (`schema_context.py:1250-1262`). The deterministic cross-scheme path, however, sums `persons_employed` across years when no year is resolved (`cross_scheme.py:22,67,448-450`) (O/I).
- **"Men worked":** excluded from the women deterministic path (`mgnrega.py:807-808`). No rule about men exists anywhere, and the issue is open as KI-229 (High; `KNOWN_ISSUES.md:233`) (O).
- **MGNREGA employment × expenditure fan-out:** covered by a prose rule (`schema_context.py:237-252`), a prohibited edge (`foreign_key_augmentation.yaml:95-101`) and the guard `_mgnrega_facts_joined` (`mgnrega.py:1073-1095`). The guard skips any SQL starting with `WITH` (`:1088`) (O).
- **Beneficiaries across all years:** open as KI-035 (High, `KNOWN_ISSUES.md:47`) (O).

### 3.5 SQL generation, repair and verification
**Prompt**
- One user message with no system role (`llm.py:214-219`) (O).
- The dialect is never stated as an instruction (O).
- Few-shots: top 5 per scheme, ranked by IDF-weighted overlap (`annotations.py:302-357`) (O).
- The header says "EXAMPLES (verified SQL…)" (`prompt_builder.py:133`). Four banks say "NOT ONE OF THESE QUERIES HAS BEEN EXECUTED against megh_db" (`cmelevate_few_shot.yaml:43`, `focusplus_few_shot.yaml:33`, `focuslegacy_few_shot.yaml:45`, `cmelevatelegacy_few_shot.yaml:29`). The only test parses one bank with sqlglot; none executes them (`tests/test_cm_elevate_legacy.py:57-64`) (O).

**Few-shot counts** (O)

| Scheme | Examples | Lines with `LIMIT n` | `meta.*` refs |
|---|---|---|---|
| MGNREGA | 68 | 36 | 0 |
| PMAY-G | 66 active | 38 | 0 |
| Focus Plus | 87 | 10 | 1 |
| CM Elevate | 128 SQL + 28 unanswerable | 22 | 1 |
| Focus Legacy | 86 | 24 | 2 |
| CM Elevate Legacy | 114 SQL + 20 unanswerable | 14 | 0 |

`staging.*` refs: 2 in total. Columns absent from the hand-written schema: e.g. `installments_paid` and `sanction_no` in PMAY few-shots (not in `schema_context.py:313-315`), and `tax_exp` (`mgnrega/few_shot.yaml:83`) (O).

**Repair loop**
- `MAX_SQL_REPAIRS = 3`, so 4 attempts (`c11:1019`). `SQL_GENERATION_MAX_RETRIES=1` is dead config (`config.py:205`) (O).
- Fed back: the raw error text and the failed SQL, the full schema including LIVE SCHEMA, and `_missing_column_hint` with real column homes (`c11:11-70`, `c11:1339-1352`, `prompt_builder.py:486-500`) (O).
- Temperature is 0 and output is constrained by a guided regex (O).
- **There is no stop on identical SQL** (O).

**Verifier**
- Runs on the 30B, **after execution** (`c11:1313` → `:1323`) (O).
- **Fails open** on any error or unparseable reply (`c11:936-940`) (O).
- About 15 false-positive filters (`c11:942-1013`) (O).
- A flag raises `ValueError`, which uses up repair budget (`c11:1330-1335`) (O).

**When everything fails**
- A data-shaped question gets an honest "couldn't build a working query" message (`c14:1289-1294`) (O).
- Otherwise there is a **silent KB answer**, labelled `route:"knowledge"`, `intent:"RAG"` (`c14:1279-1282`) (O).

### 3.6 SQL safety and authorization
**Validation** (untracked `app/sql_guard.py`)
- A sqlglot Postgres parser (`sql_guard.py:15-20`) (O).
- Root must be Select / SetOperation / Subquery, single statement (`:39`, `:85`) (O).
- Forbidden nodes include Into, DML, DDL, Command, Set and Lock (`:46-54`) (O).
- 29 forbidden functions, including pg_sleep*, pg_read_file, dblink*, set_config, lo_* and advisory locks (`:58-68`) (O).
- Schema allowlist `curated`, `semantic`; `pg_*` and catalog-qualified names are refused (`:24`, `:94-112`) (O).
- **No table allowlist** inside `curated` (O).

**Database**
- Each query runs in a READ ONLY transaction (`db.py:250`), with `default_transaction_read_only` and `search_path` set (`db.py:91-94,139`) (O).
- Client timeout is 15 s (`db.py:138`). Server `statement_timeout` exists only as a role setting in deploy SQL (`deploy/sql/03_readonly_role.sql:46`) (O).
- Superuser logins are refused on the read-only pool unless `READONLY_DB_ALLOW_SUPERUSER` is set (`db.py:105-119`) (O).

**Roles**
- `megh_readonly` is NOSUPERUSER, granted SELECT on all of `curated` and `semantic` (`03:42,55`), and revoked on `app`, raw and staging (`03:73-77`) (O).
- It can therefore read the privacy tables (O). The production role is UNKNOWN (`docs/ARCHITECTURE.md:352`) (O).
- The eval ran with `"readonly_login": "postgres"`, `"superuser_allowed": true` (`tests/nl2sql_eval/results/2026-10-15_1841_baseline.json:16-17`) (O).

**Authorization**
- `node_authorize` checks the draft SQL, then `execute_attempt` applies about 42 rewrites. Only repairs are re-authorized (`pipeline_graph.py:432-454`) (O).
- Paths that skip `authorize` (O):
  - `_geo_lookup_answer` (`c13:516,817-851`)
  - `_village_name_search_answer` (`c14:913`)
  - `_cross_scheme_money_answer` (`c13:554`)
  - `_focusplus_overall_summary_answer` (`c13:735`)
  - `_focus_legacy_pg_name_answer` (`c13:598`)
  - post-row derived queries (`focus_legacy.py:57,236`; `cm_elevate_legacy.py:288,378,424`)
  - `/api/scheme-stats` (`routers/stats.py:100-107`)
  - admins always (`auth.py:236-239`)
- The MGNREGA deterministic query is authorized on its "shown" text but executed as different text on the **app pool** without sql_guard (`c13:1080,1104-1110`) (O).

**Privacy columns**
- LIVE SCHEMA lists every `curated` column for the scheme, with no visibility filter (`schema_introspect.py:143-156`) (O).
- `bridge_pg_bank_history` and `fact_cm_elevate_disbursement` are explicitly mapped into scheme scopes (`prompt_builder.py:46-52`) (O).
- The only protection is prose: "NEVER QUERY, NEVER JOIN" (`schema_context.py:839-849`) (O).
- Embeddings are built from SME documents, not DB rows (`kb_ingest.py:4-5`) (O/I).

**Credentials** (existence only)
- `app/users.yaml` is git-tracked with 2 `password:` keys (KI-023) (O).
- A hardcoded default seed password exists in `appdb.py` (~:191-194) (O).
- `JWT_SECRET` defaults to a dev string and only logs CRITICAL (`config.py:461,598-608`) (O).
- LLM TLS defaults to `verify=False` (`llm.py:43-81`) (O).
- Per-IP rate limiting exists, in memory per worker (`middleware/rate_limit.py:45-49`) (O).
- KI-022 (Critical, open): a raw file with unmasked bank accounts is committed (`KNOWN_ISSUES.md:35`) (O).

### 3.7 Caching
**Exact cache**
- Key = normalized text + `scope.cache_fingerprint()` (role, granularity, schemes, geo); no user or session (`cache.py:91-98`, `auth.py:128-145`) (O).
- It skips low-confidence answers and clarifications (`cache.py:145`) (O).

**Semantic cache**
- Cosine ≥ 0.93 on bge-small with the same scope key. There is no district, year, scheme or number check (`semantic_cache.py:79-96`, `config.py:105`) (O).

**Cross-user leakage**
- `is_cacheable` excludes regex-detected follow-ups (`routers/query.py:351-374`). "How many in 2023-24?" passes because "how many" is a standalone anchor (`c01:234-237,516-519`) (O).
- Its context-dependent answer is written under the raw text for the whole scope (`query.py:338-341`) (I).
- KB-fallback answers are cacheable (I).

### 3.8 Logging and observability
**Audit trails**
- The JSONL audit and `app.query_audit` store ts, tenant, user, session, question, rewritten_question, route, schemes, granularity, allowed/denied_by, row_count, latency and ip (`appdb.py:127-144`, `query.py:447-465`) (O).
- `app.conversation_turns.response` stores the SQL (`appdb.py:100-125`) (O).

**Not stored in any audit trail** (O)
- errors, attempts or repairs
- verifier verdicts
- tokens
- finish_reason
- retrieved tables or chunks
- few-shot ids
- request_id

Failed requests (5xx) are never audited (`query.py:268-291`) (O).

**App logger**
- Emits `llm_call` (tokens), `prompt_context`, `pipeline_decision` and `pipeline_graph_node/run` (repairs, path), all joined by request_id (`llm.py:174-189`; `context_budget.py:91-116`; `pipeline_graph.py:243-245,792`) (O).
- The existing `logs/*.log` files contain 0 such lines (O).

**Fallback vs real knowledge answer:** indistinguishable in the audit, except for the server log line "data path failed … trying KB fallback" (`c14:58,70`) (O).

**`/metrics`:** no accuracy, repair, verifier or fallback counters (`main.py:199-218`) (O).

### 3.9 Evaluation
**Execution-based held-out eval** (`tests/nl2sql_eval/`)
- 74 questions run against the real graph, gateway and DB, compared to gold SQL (`run_eval.py:1-29`) (O).
- A hold-out guard fuzzy-matches each question against few-shots, sheets and tests (`holdout.py:1-46`) (O).
- Results (all 2026-10-15, dirty tree, superuser) (O):

| Run | Accuracy | Breakdown |
|---|---|---|
| baseline | 78.4% | 58 correct / 9 clarification / 6 wrong / 1 no_sql |
| baseline-2 | 75.7% | – |
| baseline-final | 78.4% | 58 correct / 9 clarification / 5 wrong / 2 no_sql |

- The docs still say no such benchmark exists (`docs/TESTING.md:14-15`, `CLAUDE.md:171`) (O).

**What the doc pass rates mean**
- "1,453 passed" is unit tests with the LLM stubbed (`TESTING.md:10-13`) (O).
- "30,280/30,280" is the score after fixes: 1,667 failed first, then 8 re-run rounds (`TESTING.md:122`) (O).
- Sheets follow the same pattern, e.g. MGNREGA 13/30 → 30/30 and cross-scheme 0/20 → 20/20 (`TESTING.md:108,116`) (O).

**Coverage**
- Prompt injection: only guardrail classifier cases (`tests/test_guardrails.py:50`) (O).
- No `authorize()` scope-bypass test and no cache-isolation test (O).
- Multi-turn: 21 test files plus the live suite (O).

### 3.10 Clarification behaviour
**Gates.** About 30 rules (O):
- scheme / focus / cm-group (`c03:67-98,277-288,477-481`)
- scope and region (`c05:633-689`)
- year (`c06:315-320`)
- tranche (`c06:651-655`)
- top-N (`c05:310-314`)
- entity-ambiguous (14 sites in `c09`)
- measure / column-not-held (`c01:766-770`; `c05:119,213`)

**Log counts** (`logs/query_audit.jsonl`)
- 2,020 of 5,455 turns are `"route": "clarification"` (37%). It was 44% on 2026-10-06 (O).
- After `ANSWER_DEFAULTS_ENABLED` (`config.py:427`, 2026-10-14) it fell to 2/22 and 3/16 (O).
- Many log rows are probably test traffic (I).

### 3.11 Knowledge (RAG) path
**Pipeline settings**
- bge-small embeddings. Chunks of 1,500 characters, split above 2,400 with 200 overlap (`kb_ingest.py:96,307-313`) (O).
- Hybrid BM25 + dense with RRF; 12 candidates, top 8 to the composer (`config.py:317,346-347`) (O).
- Local jina reranker on (O).

**Gates and checks**
- **The score floor is not enforced.** `[…≥0.30] or candidates[:8]` falls back to the unfiltered list (`rag.py:336-337`) (O).
- The effective gate is max score ≥ 0.55 (`rag.py:496`) (O).
- The grounding check drops unsupported sentences but keeps everything if all are flagged or if the check fails (`rag.py:432-445`) (O).

**Eval** (`tests/rag_eval`, 188 questions) (O)
- correct 91.5%, wrong 6.1%
- made-up 16.0% of answers (CM Elevate 23.7%)
- The config comment claims 9.8% (`config.py:341-342`).

### 3.12 Multilingual and voice
- The UI `language` field (en/kha/gar) routes to `translate.to_english` (`query.py:155-158`) (O).
- `TRANSLATE_ENABLED=False` (`config.py:330`, `translate.py:47`), so it is a pass-through: Khasi and Garo text is treated as English. Answers are always English (O).
- ASR falls back to "en" for kha/gar (`llm.py:628-661`) (O).
- `logs/asr_samples/` holds 2,838 saved voice files (O).

### 3.13 Maintainability
**Code shape**
- 18.9k lines are `exec`'d into one namespace (`app/pipeline/__init__.py:53-56`), so static analysis cannot resolve names across files (O).
- 633 `re.compile` calls in `app/` (O).
- 14+ hand-maintained scheme registries (`docs/SCHEMES.md:329-358`). "CM Elevate Legacy" appears literally in 28 files (O).

**Stale docs, comments and config**
1. `CLAUDE.md:110` and `docs/AI_PIPELINE.md:19` say the verifier is the 4B; the code uses the 30B (`config.py:236`).
2. `config.py:578` and `context_budget.py:58-59` budget the rewrite and verifier as the 4B.
3. `CLAUDE.md:158` says 27 pytest files; there are 58.
4. `CLAUDE.md:161` says "graph off AND on", but no switch exists (`pipeline_graph.py:2-4`).
5. `app/pipeline.py` is still referenced (`pipeline_graph.py:13`, `docs/AI_PIPELINE.md:8`, `data/cm_elevate/prompt_assembler.py:22`).
6. KI-005 is still "Open" but fixed (`sql_guard.py:144-173`).
7. `SQL_GENERATION_MAX_RETRIES` is dead config (`config.py:205`).
8. `MULTITENANCY_ENABLED` is dead config (`config.py:456`).
9. `annotations.py:8-17` says the resolver YAMLs are not loaded; they are (`entity_resolver.py:30-35`).
10. `semantic_cache.py:8` says qwen3-embedding; it uses bge-small.

**Known issues** (`docs/KNOWN_ISSUES.md`, 305 rows): 42 open, 258 closed, 5 pending (O). The worst open ones:

| ID | Severity | Issue | Line |
|---|---|---|---|
| KI-022 | Critical | Raw file with unmasked bank accounts committed | 35 |
| KI-200 | High | Qdrant on a public IP over HTTP with no key | 204 |
| KI-004 | High | No table allowlist | 17 |
| KI-023 | High | Plaintext seed passwords | 36 |
| KI-229 | High | "men" answered with total persons | 233 |
| KI-035 | High | Beneficiaries summed across years | 47 |
| KI-033 | High | Rewrite built from a stale summary | 45 |

### 3.14 Reuse of existing assets
- **Entity resolver:** exact → alias → squash → RapidFuzz, with villages looked up via DB trigram, acronyms and `never_fuzzy_to` (`entity_resolver.py:4-35,744-853`). **Keep** (O).
- **sqlglot guard:** **keep** (O).
- **Numeric faithfulness guard:** `c12:62` with strict retry and a row-built fallback. Keep, but it skips integers under 100 and years (`c12:63-64`) (O).
- **Fixed-query library:** mgnrega 5, focus_legacy 2, others 1 or 0 (O); and cross-scheme `SPECS` (O). Keep as certified queries (I).
- **Join graph YAMLs:** loaded, but only prohibited edges reach the prompt (`annotations.py:394-405`) (O).
- **Semantic catalog:** the classification, partitions and defaults YAMLs are **not loaded** (`annotations.py:8-24`). `schema_for_developers.md` covers only MGNREGA and PMAY (O).

## 5. Conversation walk-throughs

**1. "Total MGNREGA expenditure in East Khasi Hills 2023-24" → "And the total amount disbursed?"**
- Turn 1 sets state to MGNREGA / EKH / 2023 / expenditure (`context_manager.py:405-486`) (O).
- Turn 2 (O):
  - The "and" lead makes it a follow-up (`c01:214,494`).
  - The plan is metric REPLACE, the rest KEEP, kind METRIC_CHANGE (`context_policy.py:453-454,503`).
  - The 9B rewrite sees the filters line.
- **Loss point (I):** "disbursed" and "expenditure" are the same money family, so a rewrite that falls back to "expenditure" passes the own-metric check (`context_policy.py:619-626`) and returns the first figure again. A dropped EKH or year is refilled from `prior_resolved` (`c09:1355-1362`).

**2. "Who is eligible for PMAY-G?" → "How many in 2023-24?"**
- Turn 1 is knowledge, so state is not updated (`context_manager.py:377`) (O).
- Turn 2 is not treated as a follow-up (O):
  - "how many" is a standalone anchor (`c01:234-236,516-519`);
  - the scopeless check needs a data predecessor (`c01:307`);
  - the year blocks the measure-after-knowledge rule (`c01:323`).
- The scheme gate, with answer defaults on, goes to `cross_scheme.unnamed_schemes` and answers **all schemes** side by side (`c13:570-578`, `cross_scheme.py:139-142,231-232`) (I/O).
- **The PMAY-G context is lost.** The turn is also cacheable for the whole scope (3.7).

**3. "…in East Khasi Hills" → "for wgh"**
- Two words with no anchor make it a follow-up (`c01:519`) (O).
- The acronym WGH resolves to West Garo Hills (`entity_resolver.py:818-828`; `mgnrega_entity_resolver.yaml:243`), giving district REPLACE with block and village CLEARed (`context_policy.py:414-427`) (O).
- **Loss point (I):** the REPLACEd EKH is not passed as "cleared" (`c01:1080-1097`). If the model keeps EKH and adds WGH, both pass provenance (EKH is in the previous question), and the query runs for two districts.

## 6. Prompt size table
All figures are static SQL-prompt text measured with `wc -c` on `schema_context.py` blocks. LIVE SCHEMA, catalog and entities (DB-dependent) are excluded, so real prompts are larger. Tokens = chars/4 (estimate).

| Scenario | Chars (required) | Est. tokens (+5 few-shots) | Window − max_tokens | Over / under | What the code does |
|---|---|---|---|---|---|
| MGNREGA alone | 11,804 | ~2,951 (~3.5k) | 15,360 | under | sends as is |
| CM Elevate alone (largest single) | 23,657 | ~5,914 (~6.5k) | 15,360 | under | sends as is |
| CM Elevate Legacy alone (+ required common_mistakes 6,898) | 24,013 | ~6,003 (~6.8k) | 15,360 | under | sends as is |
| MGNREGA + PMAY-G (incl. 25,254 `_CROSS_SCHEME`) | 42,336 | ~10,584 (~11.6k) | 15,360 | under | sends as is |
| CM Elevate + Focus Legacy | 65,181 | ~16,295 (~16.9k) | 15,360 | **over, and over the 16,384 window** | few-shots compressed 5→3→1, required parts kept, WARNING logged, sent anyway (`context_budget.py:138-173`); likely a gateway 4xx → repair or KB fallback (I) |
| All 6 schemes | 112,267 | ~28,067 (~31k) | 15,360 | **about 2× the window** | same: sent, with no error handling specific to length |

## 7. Safety walk-through table
| SQL string | Passes validator? | Passes guards? | Authorized? | What would execute |
|---|---|---|---|---|
| `SELECT * INTO tmp FROM curated.x` | No, `exp.Into` is a write operation (`sql_guard.py:44,124-126`) | n/a | n/a | Nothing. The error goes to repair, then the honest message or KB fallback. A READ ONLY transaction is a second layer (`db.py:250`) |
| `SELECT pg_sleep(100)` | No, forbidden function (`sql_guard.py:127-129`) | `NoDataSourceQuery` fires first (`c13:1083`) | n/a | Nothing |
| `SELECT * FROM app.users` | No, `schema_not_allowed` (`sql_guard.py:106-109`) | n/a | n/a | Nothing; the role is also revoked on `app` (`03:73-77`) |
| `… -- limit` trailing comment | Yes. Comments are stripped and `LIMIT 1000` appended after the last real token (`sql_guard.py:135-140,169-170`) | yes | depends on filters | The query with `LIMIT 1000`; the comment does not swallow it (KI-005 is fixed in code) |
| `… WHERE UPPER(lgd_district)='EAST KHASI HILLS'` | Yes | yes (the pipeline's own regex handles `UPPER(`, `c10:31-35`) | Auth regex `lgd_district\s*(=\|like\|in)` misses it (`auth.py:199`). A geo-restricted user is denied as "no area" unless `resolved.district` is set (`auth.py:258,290`), in which case it is allowed on the resolved value (I) | The query as written. Combined with `IN('<allowed>','<other>')` or an `OR`, only the first literal is checked, which is a bypass (I) |

## 8. Scorecard
| # | Dimension | Score | Justification | Evidence |
|---|---|---|---|---|
| 1 | Orchestration structure and testability | 2 | Real graph with conditional edges, pause/resume and per-node logs; but nodes wrap a monolith `exec`'d into one namespace, with no Send or sub-graphs | `pipeline_graph.py:588-609,261-319`; `app/pipeline/__init__.py:53-56` |
| 2 | Typed conversation state | 2 | Typed dataclass with provenance, persisted and versioned; the pending clarification is untyped on Session, and the snapshot keeps 1 full turn | `session_store.py:38-84,132-149,191-212`; `conversation_store.py:332-358` |
| 3 | Follow-up correctness | 2 | KEEP/REPLACE/CLEAR plan plus provenance check; no dropped-filter detection (refill only), REPLACE not treated as cleared, walk-through 2 loses the scheme | `context_policy.py:382-475,571-640`; `c01:1080-1097`; `c09:1355-1364` |
| 4 | Schema retrieval | 1 | Hand-written per-scheme prose plus a full-column LIVE SCHEMA; no per-question table selection, no types or PKs | `schema_context.py:1590-1609`; `prompt_builder.py:78-100` |
| 5 | Context budget and truncation | 1 | Logs and compresses few-shots only; over-window prompts are sent; `finish_reason` never checked; stale verifier and rewrite budgets | `context_budget.py:138-173`; `llm.py:274`; `config.py:575-583` |
| 6 | Cross-scheme handling | 1 | The deterministic fan-out is good, but other measures go to one ~16–28k-token prompt, and fixed specs sum across years | `cross_scheme.py:118-130,173-213,448-450`; `schema_context.py:1601` |
| 7 | Metric and unit definitions | 1 | Six sources; free-form SQL; lakh/crore contradiction; units "UNVERIFIED" vs "RUPEES" | `schema_context.py:51-127,265-270,27`; `few_shot.yaml:4`; `cross_scheme.py:53` |
| 8 | Prompt and few-shot quality | 1 | "Verified" label on never-executed SQL; LIMIT and meta contradictions; no system role or dialect statement; IDF selection is decent | `prompt_builder.py:133`; `cmelevate_few_shot.yaml:43`; `llm.py:214-219`; `annotations.py:302-357` |
| 9 | Repair loop | 2 | Capped at 3, real error plus live columns, temp 0; no identical-SQL stop; the verifier consumes the budget | `c11:1019,1339-1352,11-70,1330-1335` |
| 10 | Verification | 2 | ~25 deterministic guards plus numeric faithfulness; the model verifier fails open, runs post-execution, and needs ~15 FP filters | `c11:1098-1308,936-1013`; `c12:62` |
| 11 | SQL validation | 2 | sqlglot parser, node and function blocklists, schema allowlist, safe LIMIT; no table allowlist; the file is untracked in git | `sql_guard.py:24,39-68,94-173` |
| 12 | Database privileges | 2 | Read-only role, READ ONLY transaction, superuser refused, 15 s client timeout; server timeout only in deploy SQL; privacy tables granted; the eval ran as `postgres`; the production role is unknown | `db.py:91-146,250`; `03_readonly_role.sql:42-77`; `baseline.json:16-17` |
| 13 | Authorization | 1 | Checks the draft before attempt-0 rewrites; ~6 paths skip; regex misses `UPPER()` and later IN items; admins bypass | `pipeline_graph.py:432-454`; `auth.py:199,236-239`; `c13:516,554,598,735` |
| 14 | Privacy of sensitive columns | 1 | Prompt prose only; the privacy tables' columns are in the LIVE SCHEMA; KI-022 raw file committed | `schema_context.py:839-849`; `prompt_builder.py:46-52`; `KNOWN_ISSUES.md:35` |
| 15 | Cache correctness | 1 | Scope-keyed, but context-dependent "How many in 2023-24?" is cacheable; the semantic cache has no entity check; KB fallbacks cached | `query.py:338-374`; `semantic_cache.py:79-96`; `cache.py:145` |
| 16 | Logging and tracing | 2 | request_id-joined token, prompt, decision and node logs; the audit lacks errors, attempts and verdicts; failures not audited; fallback indistinguishable | `llm.py:174-189`; `context_budget.py:91-116`; `appdb.py:127-144`; `c14:1281` |
| 17 | Accuracy evaluation | 2 | A held-out, execution-based 74-question set exists (78.4%); small, a single day, run as superuser; docs deny it exists | `tests/nl2sql_eval/run_eval.py:1-29`; `holdout.py:1-46`; `TESTING.md:14-15` |
| 18 | Clarification behaviour | 1 | ~30 gates; 37% of logged turns were clarifications; defaults added only on 10-14 | `logs/query_audit.jsonl` (grep -c); `config.py:427`; `c13:570-790` |
| 19 | Knowledge (RAG) quality controls | 2 | Hybrid plus reranker plus grounding plus eval; the floor is bypassed; made-up rate 16%; grounding fails open | `rag.py:336-337,432-445,496`; `tests/rag_eval` |
| 20 | Multilingual handling | 1 | Plumbing exists, but translation is disabled, so pass-through; ASR forced to en for kha/gar | `config.py:330`; `translate.py:47`; `llm.py:628-661` |
| 21 | Maintainability | 1 | 18.9k exec'd lines, 633 regexes, 14+ registries, 10+ stale docs, 42 open KIs | `app/pipeline/__init__.py:53-56`; `SCHEMES.md:329-358`; `KNOWN_ISSUES.md` |
| 22 | Reusable assets | 2 | Strong resolver, sql_guard, faithfulness guard and fixed queries; catalog YAMLs largely unloaded; join graph only partly used | `entity_resolver.py:4-35`; `sql_guard.py`; `c12:62`; `annotations.py:8-24,394-405` |

**Total: 33 / 66**

## 9. Top problems ranked
| Rank | Problem | Evidence | Impact |
|---|---|---|---|
| 1 | Authorization skips attempt-0 rewrites and ~6 answer paths; the regex misses `UPPER()` and later IN items | `pipeline_graph.py:432-454`; `auth.py:199`; `c13:516,554,598,735` | High |
| 2 | Privacy tables are readable by the role and listed in LIVE SCHEMA; protected only by prose | `03_readonly_role.sql:55`; `prompt_builder.py:46-52`; `schema_context.py:839` | High |
| 3 | No session ownership check: another user's session id loads and overwrites their context | `session_store.py:278-284`; `conversation_store.py:368-370` | High |
| 4 | Context-dependent questions are cached for the whole scope; the semantic cache ignores entities | `query.py:338-374`; `semantic_cache.py:79-96` | High |
| 5 | Multi-scheme SQL prompts exceed the window and are sent; `finish_reason` is unchecked | `context_budget.py:138-173`; `llm.py:274` | High |
| 6 | Metric and unit rules are fragmented and contradictory; known wrong-number traps are open (KI-229, KI-035) | `schema_context.py:265-270` vs `few_shot.yaml:4`; `KNOWN_ISSUES.md:47,233` | High |
| 7 | Few-shots are labelled "verified" but never executed, and include out-of-allowlist schemas | `prompt_builder.py:133`; `focuslegacy_few_shot.yaml:45,947` | Med |
| 8 | Silent KB fallback is indistinguishable from a real knowledge answer, is cacheable, and failures are not audited | `c14:1279-1282`; `query.py:268-291` | Med |
| 9 | Credential hygiene: tracked seed passwords, default JWT only warns, TLS `verify=False` by default, Critical KI-022 | `config.py:461,598`; `llm.py:76-81`; `KNOWN_ISSUES.md:35-36` | Med |
| 10 | Safety-critical files untracked; monolith `exec` namespace; stale docs | `git status`; `app/pipeline/__init__.py:53-56` | Med |

## 10. Top strengths worth keeping
| Strength | Evidence | Why keep |
|---|---|---|
| sqlglot read-only guard plus READ ONLY transaction plus separate non-superuser pool | `sql_guard.py:15-173`; `db.py:91-146,250` | A principled, parser-based gate that is hard to bypass for writes and side effects |
| Typed `ConversationState` plus `MergePlan` (KEEP/REPLACE/CLEAR) plus provenance check | `session_store.py:38-84`; `context_policy.py:382-640` | The right shape for follow-ups; needs dropped-filter detection added |
| Entity resolver (alias, acronym, fuzzy, DB trigram for villages) | `entity_resolver.py:4-35,744-853` | Domain asset, hard to rebuild |
| Numeric faithfulness guard on composed answers | `c12:62`; `c13:159,189` | Stops invented numbers deterministically |
| Held-out execution eval with leak guard | `tests/nl2sql_eval/holdout.py:1-46` | The only real accuracy measure; grow it |
| Deterministic cross-scheme fan-out and certified fixed queries | `cross_scheme.py:173-213,572`; `mgnrega.py:589,633` | Basis for a metric-id or certified-query layer |

## 11. Not verified
| Item | How to confirm |
|---|---|
| Behaviour when a prompt exceeds 16,384 tokens | Look for a gateway 400 or `HTTPStatusError` followed by "data path failed … trying KB fallback" (`c14:58`), after a `prompt_context … "over_budget": true` line for one request_id; or send a CM Elevate + Focus Legacy "person-days" question |
| SQL truncated at 1,024 tokens | A `llm_call role=sql… completion_tokens=1024` line; this needs `finish_reason` logging, which does not exist |
| Production DB role and `statement_timeout` | `SELECT current_user, rolsuper, current_setting('statement_timeout')` on the read-only pool in prod (not run) |
| Semantic-cache wrong-year hits | The similarity score between "…EGH 2022-23" and "…2023-24" on bge-small, from a `semantic_cache hit` log line |
| Cross-user cache leak for "How many in 2023-24?" | Two users with the same scope in different sessions; check the second request's cache-hit log or `/metrics` cache_hits |
| Walk-through outcomes (1–3) | The `pipeline_decision` stage=followup/plan lines and `pipeline_graph_run path=` for each turn |
| Auth bypass with `IN('<allowed>','<other>')` | An `authorize` decision log for a geo-restricted test user |
| Whether `context_manager` lazy imports of private pipeline names still resolve after the package split | Absence of the silent-skip debug lines at `context_manager.py:185-194,217-228` on a live run |
| Checkpointer backend in production | The startup log "pipeline_graph: compiled, 22 nodes, checkpointer=postgres" |

## 12. Suspicious instructions found
None. All five investigation areas were searched for text aimed at an AI or auditor ("ignore previous", "auditor", "as an AI", "do not report"). The only hits were benign: a guardrail test fixture (`tests/test_guardrails.py:50`), a chatbot reply string (`app/conversation_replies.py:314`), and domain guidance (`data/focus_legacy/focuslegacy_entity_resolver.yaml:920`).

## 13. Read-only confirmation
**What was used**
- Commands: `git branch --show-current`, `git rev-parse HEAD`, `git log`, `git status --short`, `git ls-files`, `ls`, `cat` (CLAUDE.md only), `sed -n`, `head`, `grep` / `grep -c` / `grep -n`, `find … | xargs wc -l`, `wc -c`, `sort`, `awk` (for summing counts), and the Read / Glob / Grep tools.
- Five read-only sub-investigators ran under the same restrictions.

**Main files read**
- `CLAUDE.md`
- `app/pipeline_graph.py`, `app/config.py`, `app/llm.py`, `app/context_budget.py`
- `app/session_store.py`, `app/conversation_store.py`, `app/routers/query.py`, `app/auth.py`, `app/sql_guard.py`, `app/db.py`, `app/rag.py`, `app/cache.py`, `app/semantic_cache.py`
- `app/schema_context.py`, `app/prompt_builder.py`, `app/annotations.py`, `app/cross_scheme.py`, `app/context_policy.py`, `app/context_manager.py`, `app/entity_resolver.py`, `app/translate.py`, `app/appdb.py`, `app/main.py`
- `app/pipeline/__init__.py`, `app/pipeline/common/c01–c14`, `app/pipeline/schemes/*.py`
- `data/*/*.yaml`, `deploy/sql/01*`, `deploy/sql/03_readonly_role.sql`
- `docs/KNOWN_ISSUES.md`, `TESTING.md`, `CURRENT_STATE.md`, `SCHEMES.md`, `AI_PIPELINE.md`, `ARCHITECTURE.md`
- `tests/nl2sql_eval/*`, `tests/rag_eval/*`
- `logs/query_audit.jsonl` and `logs/*.log`: counts only

**Confirmed**
- No file was created, edited, moved or deleted during the audit. This report file was written afterwards, at the user's request.
- No script, test, app code or import was run.
- No network, LLM, Qdrant, Redis or database call was made.
- No git state was changed.
- `.env` contents were not read or printed.
- No personal-data rows were printed.

**One disclosure.** One sub-investigator's read-only `sed` echoed the default seed-password literal from `app/appdb.py` into its own internal tool output. It does not appear in this report or anywhere else, and nothing was changed.
