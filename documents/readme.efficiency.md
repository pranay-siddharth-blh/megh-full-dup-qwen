# Efficiency and latency: where the Meghalaya NL Assistant is slow, and why

This document finds where response time goes in the `meghalaya` project and which parts cause the
slow answers. It uses **real measured data** from the project's own logs, plus a reading of the code.

Companion document: [README.md](README.md) explains how the LangGraph pipeline works node by node.
File references are relative to the `meghalaya/` folder.

---

## 1. Summary

**A normal data question takes about 1.7 seconds, but 1 in 20 takes 6 seconds or more, and some take
40–52 seconds.** The time is lost in these places, in order of impact:

| # | Problem | Where it happens | Measured impact |
|---|---|---|---|
| 1 | **SQL repair loop.** A rejected query is rewritten by the model, re-verified and re-run, up to 4 times | `execute_attempt` ↔ `repair` (`pipeline.execute_with_repair`) | Each repair adds about 0.9–1.7 s. The cause of most slow tail requests |
| 2 | **Very large SQL prompt.** About 12,500 input tokens per SQL call, re-sent in full on every repair | `sql_generate`, `repair` (`prompt_builder.build_sql_prompt`) | 450 ms p50 and 905 ms p95 per call. The largest single model cost |
| 3 | **SQL verifier on the critical path.** One extra model call (about 4,000 tokens) before every query runs, and its false alarms *trigger* repairs | `execute_attempt` (`pipeline._verify_sql`) | 400 ms p50 per attempt, plus the repairs it causes |
| 4 | **Every model call waits for the previous one.** Nothing runs in parallel | All nodes | 4–6 model calls in a row = 1.5–2.2 s of a data turn |
| 5 | **Non-model work: 350–700 ms per data turn.** Database lookups over the VPN, session sync, deterministic rewrites | `entities`, `execute_attempt`, router | 25–33 % of a data turn |
| 6 | **No streaming.** The user sees nothing until the whole answer is finished | `compose`, router | The full 1.7 s+ feels like waiting |
| 7 | **Follow-up questions cost an extra model call** and larger prompts | `followup` | +280 ms at p50 (1,937 vs 1,656 ms) |
| 8 | **LangGraph orchestration overhead** (only once it is turned on) | `pipeline_graph.py` | +44 to +121 ms per turn |
| 9 | **Timeouts are larger than the request budget.** Four 30 s SQL calls can exceed the 60 s limit | `config.py` | Explains the 40–52 s outliers and the 504 errors |

**What is *not* the problem:** the model queue (wait time ≈ 1 ms), the database pool, and the
LangGraph framework itself (3–7 % of a turn).

---

## 2. Where the numbers come from

| Source | What it contains | Caveat |
|---|---|---|
| `logs/query_audit.jsonl` | **3,814 real requests**, 2026-08-29 → 2026-10-04, with route, scheme and end-to-end `latency_ms` | Collected on dev and test runs, not production traffic. Includes cache hits |
| `logs/live_context_validation.json` | Live suite run on 2026-10-03: **27 turns** with every model call timed (role, latency, queue time, tokens) | Small sample, but exact per-call detail |
| `logs/live_context_validation_legacy.json` | The same suite on 2026-09-26: **31 turns** | Before some prompt changes |
| `logs/uvicorn*.log` | "SQL failed (attempt n/4), repairing: …" warnings | Dev runs; shows *why* repairs happen |
| `meghalaya/docs/LANGGRAPH_MIGRATION.md` §4 | LangGraph overhead with model and DB stubbed | Offline benchmark |

All model calls currently run **sequentially on the old driver**, because LangGraph is not switched on
in `.env` (see README §0). LangGraph runs the same calls in the same order, so every finding below
applies to both paths. Section 4.8 covers the overhead that LangGraph alone adds.

---

## 3. Measured latency

### 3.1 All requests (3,814)

| p50 | p90 | p95 | p99 | max |
|---|---|---|---|---|
| **1.0 s** | 3.2 s | 4.7 s | 9.1 s | **52.3 s** |

Distribution:

| < 1 s | 1–2 s | 2–3 s | 3–5 s | 5–10 s | 10–20 s | 20–60 s |
|---|---|---|---|---|---|---|
| 1,881 (49 %) | 1,083 (28 %) | 431 (11 %) | 251 (7 %) | 134 (3.5 %) | 23 | 11 |

### 3.2 By route: the DATA path is where the time goes

| Route | Requests | p50 | p90 | p95 | max |
|---|---|---|---|---|---|
| **data** | 1,701 | **1,703 ms** | 4,328 ms | **6,078 ms** | 52,282 ms |
| knowledge (RAG) | 556 | 1,468 ms | 3,516 ms | 5,000 ms | 14,625 ms |
| clarification | 1,342 | 250 ms | 750 ms | 1,141 ms | 24,859 ms |
| denied | 27 | 687 ms | 862 ms | 878 ms | 881 ms |
| edge (small talk) | 188 | 32 ms | 750 ms | 1,016 ms | 1,812 ms |

### 3.3 DATA path by scheme: CM Elevate has the worst tail

| Scheme | Requests | p50 | p95 |
|---|---|---|---|
| MGNREGA | 519 | 1,453 ms | 6,391 ms |
| PMAY-G | 380 | 1,312 ms | 5,110 ms |
| Focus Plus | 299 | 1,828 ms | 3,906 ms |
| **CM Elevate** | 151 | 1,954 ms | **13,719 ms** |
| MGNREGA + PMAY-G | 124 | 2,032 ms | 6,484 ms |
| Focus Legacy | 104 | 2,000 ms | 4,390 ms |
| CM Elevate Legacy | 24 | 2,719 ms | 4,313 ms |
| (no scheme recorded) | 78 | **4,515 ms** | 11,594 ms |

### 3.4 The slowest requests

| Latency | Scheme | Question |
|---|---|---|
| **52.3 s** | CM Elevate | What is the gender split of CM Elevate applicants in Eastern West Khasi Hills? |
| 50.8 s | CM Elevate | Break that down by block within Eastern West Khasi Hills. |
| 44.3 s | CM Elevate | Show the verification status breakdown for CM Elevate in Eastern West Khasi Hills |
| 41.5 s | CM Elevate | How many CM Elevate applications are on hold for Eastern West Khasi Hills |
| 41.3 s | CM Elevate | How many individual schemes does CM-ELEVATE cover for South Garo Hills |
| 36.0 s | Focus Plus | no distict |
| 32.0 s | CM Elevate | Show the verification status breakdown for CM Elevate in South Garo Hills? |
| 24.9 s | (clarification) | Which bank processed the highest total disbursement in focus plus |

7 of the 8 slowest are CM Elevate questions at district level. The per-call logs for these requests
were not kept, so the exact cause is not proven. The pattern (30–50 s, close to the 60 s cap) matches
a query that is **repaired three times**, with slow SQL calls each time (§4.1, §4.9).

### 3.5 Anatomy of one data turn (live suite, 2026-10-03)

Model time is **67 %** of all turn time (75 % in the 2026-09-26 run). The rest is database work,
session sync and Python.

| Model role | Model | Calls / data turn | Input tokens (mean) | p50 | p95 |
|---|---|---|---|---|---|
| classifier (intent, scheme, entities, rewrite) | `qwen4-deploy` | 1–2 | 863 | 142 ms | 359 ms |
| **SQL generation / repair** | `qwen-model` | 1–2 | **12,458** | **451 ms** | **905 ms** |
| **SQL verifier** | `qwen4-deploy` | 1 | **4,068** | **402 ms** | 814 ms |
| composer | `qwen35-9b` | 1 | 780 | 311 ms | 689 ms |

Data turn: **p50 2.27 s**, of which model time ≈ 1.50 s and non-model time ≈ 0.62 s.
Model calls per turn: 4 (fresh question), 5 (follow-up), 6 (follow-up with one repair).

A typical data turn on a time line (p50 values, every step waits for the one before):

```
sync_in  cache   classifier  entities+DB   SQL generation   verifier   DB query  composer  summary* sync_out
 67 ms   ~20ms    ~140 ms     ~200 ms ▲      ~450 ms          ~400 ms    ~100 ms  ~310 ms   (0/140)  68 ms
|──|──|─────|───────|─────────────────────|────────────────|─────|────────────|──|──|
                                          └─ if rejected: + repair (450) + verifier (400) + DB, up to 3×
* the conversation summary is refreshed every 4th turn, before the answer is returned
```

The most expensive slice is **SQL generation + verifier ≈ 850 ms, about 40 % of a data turn**, and it
repeats on every repair.

---

## 4. Where exactly the problems are

### 4.1 Problem 1: the SQL repair loop (the biggest tail cost)

**Where:** `pipeline.execute_with_repair` ([app/pipeline.py:12150](../meghalaya/app/pipeline.py#L12150)),
`_execute_one_attempt` (line 12220), `_repair_sql` (line 12383). In LangGraph: `execute_attempt` →
`repair` → `execute_attempt`.

**What happens:** if a regex guard, the verifier, or Postgres rejects the query, the full prompt plus
the error goes back to the SQL model, and the new query runs the whole check sequence again. With
`MAX_SQL_REPAIRS = 3` there can be up to **4 SQL calls, 4 verifier calls and 4 DB executions** in one
request.

**Evidence (dev logs):**

| Attempt that failed | Count |
|---|---|
| 1st attempt failed → 1st repair | 94 |
| 2nd attempt failed → 2nd repair | 44 |
| 3rd attempt failed → 3rd repair | 33 |

About half of the queries that need one repair need another, and a third reach the last attempt.
Once a query fails, it tends to keep failing.

Most common reasons:

| Reason | Count | Kind |
|---|---|---|
| `column "admin_recurring_exp" does not exist` | 24 | Model invents a column |
| MGNREGA money converted to crore for a single village | 12 | Guard |
| `column "lgd_block" does not exist` | 11 | Model uses a column the view lacks |
| **Verifier**: resolved entities vs SQL filter mismatch ("Check 2") | 40+ | **Verifier** |
| **Verifier**: prohibited join ("Check 1") | 8+ | Verifier |
| Direct JOIN of `v_employment` to `v_expenditure` | 5 | Guard |
| Village filtered by name or at the wrong level instead of `village_code` | 11 | Guard |

**Why it is slow:** each repair costs about **450 ms (SQL) + 400 ms (verifier) + DB time + rewrites,
roughly 0.9–1.7 s**, and more when the model is under load (SQL p95 is 905 ms). Three repairs add
3–5 s at normal speed.

**Possible direction:** catch invented columns before execution (check the SQL's columns against the
known schema in code, with no model call); add the recurring mistakes to the generation prompt so the
first attempt is right.

### 4.2 Problem 2: the SQL prompt is very large (about 12,500 tokens)

**Where:** `prompt_builder.build_sql_prompt` ([app/prompt_builder.py:446](../meghalaya/app/prompt_builder.py#L446))
and `build_repair_prompt` (line 473).

**What happens:** every SQL call sends the schema backbone, the live schema, the catalog, prohibited
joins, few-shot examples, common mistakes, resolved entities and the question. The live suite measured
a mean of **12,458 input tokens** against 1,165 output tokens in total across 25 calls. The model
spends most of its time *reading* the prompt (prefill), not writing SQL.

The **repair prompt re-sends the whole schema** plus the failed SQL and the error, so every repair
pays the full 12,500 tokens again.

**Why it matters:** the SQL call is the single most expensive call (451 ms p50, 905 ms p95), and it
runs once or more on every data question that is not a fixed-shape query.

**Note on prompt caching:** the prompt puts the static schema first, which suits a prefix cache. The
few-shot block is ranked per question, though, so everything after it differs between requests.
Whether the model gateway (`10.48.242.4`) has prefix caching turned on is not recorded in the repo.

**Possible direction:** send only the views and columns the resolved scheme needs; confirm prefix
caching on the gateway and keep everything question-specific at the end of the prompt.

### 4.3 Problem 3: the SQL verifier is on the critical path, and causes repairs

**Where:** `pipeline._verify_sql` ([app/pipeline.py:12032](../meghalaya/app/pipeline.py#L12032)),
called inside `_execute_one_attempt` at line 12363, **before** the query runs.

**What happens:** a second model (`qwen4-deploy`) reads a 4,068-token prompt and judges whether the
SQL answers the question. Every attempt pays this, including a correct first query.

**Two costs:**

1. **Direct:** 402 ms p50 (814 ms p95) on every data question and on every repair.
2. **Indirect:** the verifier itself rejects queries. At least 40 repairs in the logs began with
   "semantic verifier flagged this query: Check 2…". Some of those flags are false; the code already
   carries a filter for one known false-alarm pattern (`_VERIFIER_FALSE_EMPTY_ENTITIES`). A false flag
   costs a full repair, about 1 s.

**Possible direction:** run the verifier *in parallel* with the DB query and discard the rows only if
it objects; or skip it for simple query shapes that the regex guards already cover.

### 4.4 Problem 4: every step waits for the previous one

**Where:** the whole pipeline. Each stage `await`s its model call before the next stage starts. The
LangGraph graph is a straight chain, with no parallel branches.

Pairs that do not depend on each other but still run one after the other:

| Step A | Step B | Why they are independent |
|---|---|---|
| `classify_scheme` ([pipeline.py:5515](../meghalaya/app/pipeline.py#L5515)) | `extract_entity_mentions` ([pipeline.py:5784](../meghalaya/app/pipeline.py#L5784)) | Mention extraction takes only the question, not the schemes |
| `_verify_sql` | `db.run_readonly` (the query) | The query is read-only; rows can be discarded if the verifier objects |
| `compose` | `finalize` follow-up suggestions | Suggestions use the rows and SQL, not the composed text |
| `sync_out` (68 ms, awaited) | returning the response | The write must finish before the *next* request, not before this response |

`classify_scheme` and `classify_intent` often skip the model through keyword shortcuts, which is why
the live data shows only 1–2 classifier calls per turn. When the shortcut misses, the calls add up.

**Possible direction:** `asyncio.gather` for independent calls, or parallel branches in the LangGraph
graph (a "fan-out" from one node to two).

### 4.5 Problem 5: non-model time is 350–700 ms per data turn

Measured: turn time minus model time = **504 ms p50 and 1,623 ms p95** per turn (2026-10-03 run);
**615 ms p50** for data turns.

**Where it goes:**

| Item | Where | Cost |
|---|---|---|
| `session_sync.sync_in`, read session from Postgres | router, before the pipeline ([session_sync.py:59](../meghalaya/app/session_sync.py#L59)) | 67 ms p50, 137 ms p95 |
| `session_sync.sync_out`, write session, **awaited** | router, after the pipeline (line 84) | 68 ms p50, 185 ms p95 |
| Entity resolution DB lookups (district, block, village, year, CM Elevate block names) | `entities` node, `resolve_entities` | Several queries per turn over the VPN |
| Async rewrites that read the DB **on every attempt** (`_cm_elevate_fix_literals`, `_focusplus_lgd_only_block`) | `_scheme_sql_rewrites`, run before each attempt | Repeated on each repair |
| The SQL query itself (15 s timeout, `LIMIT 1000`) | `execute_attempt` | Varies by query |
| Semantic cache lookup (embeds the question) | router, before the pipeline | On every cacheable miss |

The database (`10.48.242.4`) is reached over a VPN, so every round trip carries network latency. Each
small lookup is cheap, but there are many, and they run one after another.

**Note:** database time is **not logged separately** today. The `llm_call` records time the model,
but there is no equivalent `db_call` record, so the 615 ms cannot yet be split exactly.

### 4.6 Problem 6: no streaming, so the user waits for everything

**Where:** `app/llm.py` makes every model call without streaming (the comment at line 164 notes this),
and the router returns one JSON response at the end.

**Effect:** time-to-first-word equals the full turn time (1.7 s p50, 6 s p95). The composer alone
takes 311 ms p50, but even after it starts writing, nothing reaches the screen until the turn
finishes, including `context_update` and `sync_out`.

This does not change total latency, but it is the largest change to how slow the app *feels*.

### 4.7 Problem 7: follow-up questions cost more

| Data questions | Count | p50 | p95 |
|---|---|---|---|
| Fresh questions | 1,387 | 1,656 ms | 6,078 ms |
| Follow-ups (rewritten) | 314 | **1,937 ms** | **6,828 ms** |

**Where:** the `followup` node calls `rewrite_followup` (one more classifier call, 161 ms p50 and
510 ms p95 in the live suite). The rewritten question also carries more context into the SQL prompt
(27,900 total input tokens per follow-up turn, against 20,450 for a fresh one).

Follow-ups also **never use the cache** (`is_cacheable` in `routers/query.py` excludes them, correctly,
because their meaning depends on the conversation).

### 4.8 Problem 8: LangGraph overhead (once the flag is on)

**Where:** [app/pipeline_graph.py](../meghalaya/app/pipeline_graph.py).

| Turn type | Added by LangGraph |
|---|---|
| Data answer | +73 ms |
| Follow-up | +121 ms |
| Clarification pause | +44 ms |
| Pause reply (resume) | +80 ms |
| First request per worker (compile + open SQLite) | 161 ms, once |

That is 3–7 % of a live turn, so it is **not** a main bottleneck. The small inefficiencies inside it:

1. **About 50 ms of per-step machinery**, ≈ 2.9 ms × ~18 node steps (task scheduling, callbacks,
   channel updates).
2. **The checkpoint is written, then deleted, on every answered turn.** With
   `PIPELINE_GRAPH_DURABILITY=exit`, LangGraph writes the final state at the end of the run, and
   `_drop_thread` ([pipeline_graph.py:719](../meghalaya/app/pipeline_graph.py#L719)) deletes it straight
   away. Only paused threads need to be stored, so two SQLite writes per answered turn achieve
   nothing.
3. **`aget_state` is read twice per request**: once to check for a pause, once after the run.
4. **State is rebuilt in every node.** `_hydrate_turn` / `_dehydrate_turn` convert dicts back to
   `Turn`, `ConversationState` and `MergePlan` objects in each of the six turn nodes. This is the main
   reason a follow-up costs +121 ms against +73 ms for a fresh question.
5. **One `json.dumps` log record per node**, about 20 per request (cheap, but on the hot path).

### 4.9 Problem 9: the timeouts allow requests longer than the 60 s budget

**Where:** [app/config.py](../meghalaya/app/config.py).

| Call | Timeout | Worst case per request |
|---|---|---|
| SQL generation / repair | 30 s | × 4 attempts = **120 s** |
| SQL verifier | 15 s | × 4 attempts = 60 s |
| Classifier | 30 s | × 2–4 calls |
| Composer | 20 s | × 2 (with the faithfulness retry) |
| SQL execution | 15 s | × 4 attempts |
| **Whole request** | **60 s** (`REQUEST_TIMEOUT_SECONDS`) | |

The sum of the individual timeouts is far above 60 s. A slow model plus a repair loop runs until the
60 s cap, and the user gets a **504 after waiting a full minute**. The 40–52 s requests in §3.4 are
this case: they finished just under the cap.

Nothing checks how much of the 60 s is left before starting another repair.

**Possible direction:** pass a deadline down the pipeline and skip further repairs (falling back to a
clear "could not build a query" answer) when there is not enough time left.

### 4.10 Knowledge (RAG) questions: 1.5 s p50, 5 s p95

**Where:** the `knowledge` node → `rag.answer_from_kb` ([app/rag.py:169](../meghalaya/app/rag.py#L169)).

Three steps run one after another: embed the question (`call_embedding`, or the local
`bge-small` model on CPU), search Qdrant for 12 chunks (`115.124.102.167:6335`, a remote host), rerank
with `qwen3-reranker`, then compose with `qwen35-9b` (and retry once if the answer is a whole
refusal). Questions naming several schemes run `answer_from_kb_multi`, which repeats this per scheme.

---

## 5. What is not the problem

| Suspect | Evidence | Verdict |
|---|---|---|
| Model gateway queue | `queue_ms` ≈ 0–1 ms on every call in the live suite | Not a bottleneck at current load. Watch it under real concurrency (24 slots per worker) |
| DB connection pool | 10–30 connections per worker, no pool waits reported | Fine |
| LangGraph | +44 to +121 ms, 3–7 % of a turn | Small (see §4.8) |
| Composer output length | 770 output tokens across 20 calls (≈ 38 per answer) | Short answers; the composer is fast (311 ms) |
| Clarification questions | 250 ms p50 | Fast, because they are asked **before** any SQL work |
| Edge replies | 32 ms p50 | Fast |

---

## 6. Where the time goes: a data question, ranked

Based on the live suite (p50 values for a fresh data question with no repair):

| Rank | Step | Time | Share of ≈ 2.2 s |
|---|---|---|---|
| 1 | SQL generation (`qwen-model`, 12.5 k tokens) | ~450 ms | ~20 % |
| 2 | SQL verifier (`qwen4-deploy`, 4 k tokens) | ~400 ms | ~18 % |
| 3 | Database lookups + query + rewrites + Python | ~500–600 ms | ~25 % |
| 4 | Composer (`qwen35-9b`) | ~310 ms | ~14 % |
| 5 | Classifier calls (intent / scheme / entities) | ~140–300 ms | ~10 % |
| 6 | Session sync in + out | ~135 ms | ~6 % |
| 7 | LangGraph overhead (when on) | ~73 ms | ~3 % |

**For each repair, add ranks 1 + 2 + part of 3 again: about +1 s.** That repeat cost is what turns a
2 s answer into a 6 s, 15 s or 50 s answer.

---

## 7. Data still missing

To pin the remaining causes down exactly, these measurements are needed:

1. **Database time per request.** Add a `db_call` log record (query kind, ms, rows), like `llm_call`.
2. **Per-node timing in production.** Turn LangGraph on for a canary
   (`PIPELINE_GRAPH_CANARY_PERCENT=10`); the `pipeline_graph_node` records then give `ms` for every
   node, and `pipeline_graph_run` gives `repairs` per request.
3. **Repair rate in production.** How many real requests need 1, 2 or 3 repairs (`repairs` in
   `pipeline_graph_run`).
4. **The CM Elevate 40–52 s requests.** Re-run those questions with logging on to confirm whether
   they are repair loops, slow model calls, or slow SQL.
5. **Gateway prefix caching.** Confirm with whoever runs `10.48.242.4` whether vLLM prefix caching is
   enabled for `qwen-model`.
6. **Real production traffic.** The audit log here comes from development and testing. Measure the
   same figures on the VMs.
