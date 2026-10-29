# Handoff

*For the next Claude session or account. Keep this short and overwrite it at the end of every
significant session.*

**2026-10-27 evening (run only, no code change): app running over HTTPS on :8401.** The repo had no root `.venv`
(only the old gitignored `meghalaya/.venv`); a new `.venv` was built from `requirements.txt` (Python 3.12) plus
`cryptography`. A self-signed dev cert (SAN localhost, DESKTOP-L9GCSDL, 127.0.0.1, 192.168.1.25, 10.212.134.3; 825 days)
is in `certs/dev-cert.pem` + `dev-key.pem` (gitignored). Start:
`.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8401 --ssl-certfile certs/dev-cert.pem --ssl-keyfile certs/dev-key.pem`.
Plain `http://` on :8401 no longer answers. Verified live: `/health` ok, HSTS + CSP headers, `/api/query` answered over HTTPS.
The `app/users.yaml` seed passwords do NOT match the DB users (login 401/422). This is a dev setup; production TLS stays at nginx (`deploy/nginx/`).
This run includes the uncommitted D-072/D-073/KI-431 changes listed below.

**2026-10-27 night (code): RAG-plan handover, Tasks 1-9 — uncommitted, :8401 NOT restarted.** The user gave the colleague's handover (`RAG_Plan_Progress_and_Handover_2026-10-27.docx`, Downloads) and asked for the remaining items one at a time, in its §8 order. User decisions today: no year/place named -> keep asking; U5 -> keep the previous year **only when the measure repeats** (D-075); KI-407 -> keep asking (D-064). Done: KI-406 (c14), KI-407 (test), KI-427 (c06 / c09 / c11 / prompt_builder), KI-411 (c11), KI-441 (c12 / c13). Live context 107/107. Task 3 done too: **KI-368** (c08 `_explicit_level_in`). Held-out set ran on a flaky VPN (18 network errors): 56 clean items 30 -> 31, 0 regressions; re-run on a stable VPN. :8401 was started by another process 16:48 (system Python + SSL) — ask the user before restarting. Task 4 done: **KI-404** (deterministic process cue; B3 score tie-break still PLANNED). Task 5 done: **B4 / KI-442** (catalogue shrinks first; examples 1 -> 5; held-out 41/74 vs 40/74). Task 6 done: **B1 / D-076** (meaning shadow log + approved synonyms; never answers). Task 7 done: **B3 / D-077** (score safety net, 69/70). Task 8 done: **E1 stage 1 / D-078** (query plan in shadow, 79/79). Task 9 done: **E5 / D-079** (registry + drift guard; KI-445 found). **Next (Task 10): E7** SQL built from the catalogue. The user wants a report after EVERY task (done list, next, remaining count) and waits to say go. Python: the repo root has no `.venv`; `meghalaya/.venv/Scripts/python.exe` works.

**2026-10-27 afternoon (code, D-073): generated SQL through `semantic.run_query` on megh_chatbot, uncommitted, :8401 NOT restarted.** Files: `app/db.py` (chatbot pool, `_run_via_run_query`, type restore, `application_name`), `app/config.py` (`CHATBOT_DATABASE_URL`, `CHATBOT_DB_POOL_*`, `SQL_MAX_COST`, `DB_APPLICATION_NAME`), `app/pipeline_graph.py` (checkpointer application_name), `tests/conftest.py` (tests keep the read-only path), `tests/test_readonly_pool.py` (pinned server_settings now include application_name), NEW `tests/test_run_query_path_2026_10_27.py`, `.env.example`, `.env` (key rename only). Rollback: blank `CHATBOT_DATABASE_URL`. Next: user's go-ahead for `020_megh_app_role.sql` (cap 35) -> set `DATABASE_URL` to megh_app; the admin stops the old 172.18.0.2 container; restart :8401.

**2026-10-27 (code): KI-431 fixed** — the SQL model wrote "FY23" as `year_key = 2023` -> "couldn't build a working query".
`context_policy.expand_short_fy` gives the SQL + repair prompts the full form; the guard names a wrong year. pytest 3,881/0,
scripts 14/14, live 6/6. :8401 not restarted. New harness `tests/sheet_runs/mg_excel_run.py <expect.json> <out.json>`: MGNREGA
DATA-001..030 + a 5-level hierarchy sweep, expected figures from the raw Excels (expect.json is built with the system
python + pandas from `raw_uc/`; the venv has no pandas). Run 763/919 (863 incl. "which scheme?" pauses), report
`new_docs/MGNREGA_Excel_Test_Report_2026-10-27.md`. Next (user's go-ahead): KI-432 first (wrong number), then KI-433..436;
user decision: should "work / workers" wordings go straight to MGNREGA instead of asking the scheme?

**2026-10-27 (code, D-072): fixes for the DB team's changes, uncommitted, :8401 NOT restarted (restart to take effect).** Files: `app/schema_introspect.py` (KI-428 scope-out maps), `app/db.py` (`QueryTooHeavyError`, `precheck_readonly`), `app/config.py` (`SQL_DB_PRECHECK`), `app/pipeline/common/c01_followups.py` (import), `c11_sql_verify_repair.py` (pre-check before `run_readonly`), `app/sql_guard.py` (system functions), `app/auth.py` (KI-429), NEW `tests/test_db_changes_2026_10_27.py`. Deliberately NOT done: making timeouts / 42501 final or cutting repairs to 2 (a timeout was repaired into an answer 2026-10-18; asked the team). Waiting on the team's reply to the message in report §7 / chat; KI-430 retention needs the user.

**2026-10-27 (review only): DB team's changes checked.** Report `new_docs/DB_Changes_Impact_Report_2026-10-27.md`.
No breakage. Waiting on the user: go-ahead for the KI-428 fix (2-line scope-out map), KI-429 (assign block or fail closed),
KI-430 retention period, `020_megh_app_role.sql` go-ahead, and whether/when to move to `megh_chatbot` + `run_query`
(report §5; repair 3 -> 2 would need a DECISIONS entry). The draft reply to the DB team is report §7.

**2026-10-27 (code): KI-405 fixed.** One new branch in the c14 scope-pause step (`_c14_pause_scheme_switch`, before the
merge): a pure "What about <other scheme>?" / "same for <other scheme>" reply re-asks the paused question for that scheme.
Live suite 105/107; the 2 left are KI-406 (needs the user's U5 year-carry decision) and KI-407 (bare CM Elevate count:
ask, or default to Legacy? — user decision). New KI-427 (MG-08 year range). :8401 restarted (PID 52752).

**2026-10-26 night (code): D-071 metric catalogue, Parts 1-3 done.** `app/metric_catalog.py` (load / match / build),
`app/pipeline/common/c16_metric_catalog.py` (decision; last in the c13 fixed-query chain), `data/metric_catalog_verified.yaml`
(the evidence gate: total 28, breakdown 25, ranking 28, compare 23; `single_year`; `no_block_level`; `except_words`),
`METRIC_CATALOG_MODE=on` (config default). A measure not in the file is shadow-logged only. To add or re-check a measure:
`.venv/Scripts/python.exe -X utf8 tests/metric_catalog_eval.py --out <file> [--metrics k1,k2] [--mode on]` (VPN), then edit
the file with the evidence. Report: `new_docs/Metric_Catalogue_Report_2026-10-26.md`. :8401 was restarted from the venv on
2026-10-27 11:04 with the catalogue loaded (the old PID 32108 was the venv launcher's child, not a foreign process). Open: KI-424 (ask the owners what "sanctions" /
"coverage" / "remittances" mean), KI-425, KI-426.

**2026-10-27 evening (code + .env): every kind in megh_knowledge and megh_sql_metadata is now used (user's instruction).**
`SQL_EXAMPLES_SOURCE=qdrant` by default: examples + view / join notes from megh_sql_metadata. Measured slightly worse than
YAML (54.1% vs 56.8%, 4 repairs vs 0; KI-438), kept on by the user's instruction. Next: show the user that result, then either
more / validated examples in megh_sql_metadata (loading team) or `SQL_EXAMPLES_SOURCE=yaml`. Start :8401 and check over HTTP.

**2026-10-27 (code + .env): D-074 — Qdrant is `10.48.242.4:6333`; the project uses ONLY `megh_knowledge` (RAG) and
`megh_sql_metadata` (SQL examples), both read-only to the app.** The user's new `.env` is in place, with the Qdrant
block rewritten and `DATABASE_URL_CHATBOT` commented out (KI-437). Memory is off (KI-439). `SQL_EXAMPLES_SOURCE=yaml` stays
until `python tests/nl2sql_eval/compare_examples_source.py` has been run and shows no regressions (KI-438, VPN, ~2 x 74
questions). Next: run that comparison; run `tests/rag_eval/run_eval.py` against megh_knowledge (KI-440); the live context
suite (memory off). KB doc changes now go to the team that loads megh_knowledge. Deploy `.env` must match `.env.example`.

**2026-10-26 (review only): role-based access.** Report `new_docs/Role_Based_Access_Report_2026-10-26.md`; no code
changed. Opened KI-418 (HIGH, `PATCH /admin/users` escalation to super_admin), KI-419 (cross_figures, Focus Plus summary,
Focus Legacy PG-name, MGNREGA women-unrecorded answers run before `authorize`), KI-420, KI-421. Fix order in report §8.

**2026-10-26 night (code): D-070 / KI-423** — session-less API calls get their own `api-<random>` conversation
(`routers/query._session_id`, cached per request); `conversation_store` hides `api-` threads from the user's list/search.
API scripts that relied on the day bucket to answer a clarification must now send back the returned `session_id`.

**2026-10-26 night (team agreed caps): megh_app cap 30, megh_readonly 20 (both HARD; tell the team before adding a worker,
VM or pool).** `172.18.0.2` is very likely the OLD build's Docker container (`megh-nlp`; 2 workers x min pool 10 = the 20 idle
`postgres` sessions) — INFERRED, server admin to confirm; stop the old build at switch-over. Waiting: megh_app password,
the user's backup decision. Reply section added to `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-26.md`.

**2026-10-26 night: megh_app readiness.** The team is preparing `megh_app` (owns `app`, reads like megh_readonly, 60 s
timeouts, 20-connection cap). Done: unused default-rule / template files marked NOT LOADED (+ guard test); readiness checks
1-3 pass; check 4 needs the cap raised to 30 (asked). When the password arrives: set `DATABASE_URL` to megh_app, restart,
run the full suite + live checks. **User decision pending:** may chat history stay in the team's 14-day `megh_db` backups?

**2026-10-26 late (code): the team's reply to our evening update applied** — catalog reads as megh_readonly
(`db.fetch_rows_readonly`), Khasi wording. **For the user to tell the team:** our app tables live in megh_db, schema `app`
(created by `appdb.ensure_schema` since the start) — they asked to be told, and want a `megh_app` role there; plus the deploy
VMs and `172.18.0.2`. The app's own fixed curated queries still run as `postgres` (DATABASE_URL).

**2026-10-26 evening (code + rules + .env): D-069 extended after the team's answers** (`ANSWERS_TO_CHATBOT_TEAM_2026-10-26.md`,
pasted by the user). megh_readonly live on the dev box; Ri Bhoi in Khasi; CM Elevate workflow statuses answered "not
recorded" (`_cme_workflow_query`); KI-417 rounding; `_star_without_hidden_columns`. Still for the user: tell the team which
of their 6 actions are done (reply doc updated), confirm `172.18.0.2` with the server admin, apply the same `.env` lines on
the deploy VMs. Another session is editing KNOWN_ISSUES in parallel (KI-418..421 are theirs) — check numbers before adding.

**2026-10-26 (code + rules): D-069, the ingestion team's DB changes.** Note `CHATBOT_DB_CHANGES_2026-10-26.md` (pasted by the
user). Done: `member_key`, region alias (`region_group` + c11 `_region_alias_not_the_column`), few-shot check 0 errors.
Waiting on the team (5 questions in `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-26.md`: records vs applications,
Ri Bhoi region, "pending", CM Elevate scheme_specific member_id, fact table access) and on the `megh_readonly` password.
CMSS / Home Stay Legacy are new in megh_db and not in the chatbot.

**2026-10-26 (code): KI-414 short FY forms everywhere.** `app/context_policy.py` (`short_fy_tokens`, `extract_year_keys`,
`rewrite_violation` keeps the user's own year), c06 (`_c06_short_fy_tokens` delegates, `_c06_all_year_tokens` used by
`_years_in_question` / `_out_of_range_year_in`), c07 `_backfill_explicit_year`, `app/edge.py` ("FY'25"). Tests
`tests/test_short_fy_forms_2026_10_26.py`. Live 81/81. Open: KI-415 (fix the region few-shot SQL), KI-416 (measure drift on
a bare year follow-up). Another process restarts :8401 too — check `netstat` before assuming whose server answers.

**2026-10-26 (code): ranking count words, KI-412 / KI-413.** c02 `_normalize_rank_counts` (wired at c14 next to
`_correct_fy_spacing`), c11 `_stated_rank_count_limit` (end of `_scheme_sql_rewrites`), NEW tests
`test_rank_count_words_2026_10_26.py` and the namespace guard `test_pipeline_namespace_2026_10_26.py`. Option 2 of the
ranking design (option 3, a structured RankingSpec + SQL compiler, waits for the metric catalogue). Uncommitted together
with D-068; the user will commit.

**2026-10-24 night (code): D-068.** A stated scope is never asked for (c05 / c06 cues; `_STATED_ALL_YEARS_CUE` kept
out of `_ALL_YEARS_CUE` for the verifier's sake) and "FY24" = FY 2023-24 (c07 parser + c09 bare-digit fallback).
Option A (answer with a default) was NOT re-applied: D-053/D-056/D-065 are the user's own reversals of it. Held-out set
42/74 (0 wrong except PM-04, which flips on the original code too, KI-411). Open for the user: update the held-out set's
expectations to D-053/D-056/D-064/D-065 (31 items ask by rule), KI-411, U5, KI-407.

**2026-10-24 late: branch `update/2026-10-24`, commit `9c7c67c` (everything below, not pushed).** Then `.gitignore`
gained `raw_uc/`, `new_docs/*.csv`, `new_docs/~$*` (PII + QA CSVs + Word lock files; uncommitted). Status of the user's
29-item RAG plan: `new_docs/RAG_Plan_Status_Report_2026-10-24.md`. Then (docs only) every current-guidance mention
of `data/reference/` corrected to `data/incoming/<scheme>/` (CLAUDE.md, ARCHITECTURE, AI_PIPELINE, SCHEMES). The user wants one instruction at a time, no day plans.

**2026-10-24 evening (code): the 1024-dim switch is finished and live on :8401.** Qdrant backup in
`C:\Users\rohit\Downloads\qdrant_backup_2026-10-24\` (outside the repo). Code: `app/vectorstore.py` (`vector_size`,
`collection_dim`), `app/kb_ingest.py` (size check -> rebuild, KI-402), `app/conversation_memory.py` (size refusal, purge of
`CONTEXT_MEMORY_PURGE_ALSO`, KI-403), `app/config.py` (new setting + comments), comments in `rag.py` / `local_rank.py`; NEW
`deploy/migrate_conversation_memory.py` (ran: 12,046 turns) and `tests/test_embedding_size_guard_2026_10_24.py`. Docs: D-067,
KNOWN_ISSUES KI-402..407, TESTING, AI_PIPELINE, ARCHITECTURE, DEPLOYMENT, `.env.example`. Tests: pytest 3,661/0, scripts 14/14,
live context 103/107 (same 4 fail on 384: KI-405 scheme switch in a pause, KI-406 year dropped / U5, KI-407 stale F-T5 check).
Then KI-408: memory search exact + payload indexes (`conversation_memory.create_payload_indexes`; added live to
`megh_conversation_memory_1024`), 60/60 vs exact, pytest 3,663/0, live context 103/107 again, :8401 = PID 17056.
Nothing committed. **Next:** the user's RAG plan (`new_docs/RAG_Plan_Reference_Notes_2026-10-24_with_fixes.docx`), Step 0
onward; the Step 4 metadata collection is built at 1024 with qwen3-embedding.

**2026-10-24 (config + one code fix): embeddings switched to the gateway's `qwen3-embedding` (1024-dim), D-067.**
`.env` changed (provider `gateway`, URL `…/openai/v1`, collections `megh_scheme_kb_v4` + `megh_conversation_memory_1024`,
`RAG_MEDIUM_CONFIDENCE=0.35`, `CONTEXT_MEMORY_MIN_SCORE=0.45`; a pre-change copy was kept outside the repo). `megh_scheme_kb_v4`
is built. Code: `app/semantic_cache.py` (KI-401, contrast words in the cache scope) + its test in `tests/test_forward_plan_wi.py`.
Docs: DECISIONS D-067 (D-004 superseded), AI_PIPELINE, ARCHITECTURE, KNOWN_ISSUES KI-401, TESTING, CLAUDE.md §5,
`.env.example`, `deploy/DEPLOYMENT.md`. **Next:** restart :8401 from `.venv` (the running one is system Python, old settings),
ask 2-3 knowledge questions and one follow-up, check `megh_conversation_memory_1024` gets created; then copy the same `.env`
lines to the deploy VMs. Rollback = D-067. Nothing committed.

**2026-10-23 evening (report, no app code): context-memory audit** — `new_docs/Context_Memory_Audit_Report_2026-10-23.html`
(also published as a private claude.ai artifact). New KI-399 (session not bound to its owner) and KI-400 (cached answer
wipes topic memory), both High, both confirmed by calling the real functions. VPN dropped mid-harness: when it is back,
re-run `--only` U4,U5,U6,U7,U8,U9,N1,N2,N3 (http --stream --skip-cache) and `tests/live_context_validation.py`; also run
the harness once WITHOUT `--skip-cache` (KI-400 only shows with caches on). Next fixes in the report's Step 1.

**2026-10-23 (code): PMAY-G card "Houses sanctioned" now 1,71,107** (user: include the 126 zero-sanction rows). Changed
`app/routers/stats.py` (`_SQL["pmay_g"]` counts every row), `frontend/src/chat/constants.js` fallback, `tests/test_scheme_stats.py`;
frontend rebuilt. The card cache is 10 min (`STATS_TTL_SECONDS`): restart :8401 to see it at once. Open KI-398 (prompt
cross-scheme examples text). Nothing committed.

**2026-10-23 (report only, no code):** `new_docs/NL2SQL_LangGraph_Benchmark_Report_2026-10-23.html` ranks the NL→SQL gaps.
Suggested next step from it: re-run `tests/nl2sql_eval` on today's code (last full run 18 Oct, before D-060..066).

**PORT RULE (user, 2026-10-19): the app runs on 8401 ONLY — dev box, docs, harness, probes. Never 8400 or any other port.
Start it from the repo venv: `.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8401` (two servers started
with the SYSTEM Python — no fastembed, RAG degrades silently — were found running on 8400 and 8401 at 13:05 and replaced).**

**Latest (2026-10-23): full audit, no code changed.** Report `new_docs/Megh_One_AI_Audit_Report_2026-10-23.html` (findings,
priorities). First actions it recommends: gitignore `raw_uc/` + `new_docs/*.csv`; FY24 / number-word parsing; phone KPI
cards + compare-card verdict; CA bundle; read-only DB role; refresh CLAUDE.md. Awaiting the user's choice of what to fix.

**Latest (2026-10-22 night, KI-397): comparison card "MGNREGA 14,94,437 vs PMAY-G 0".** Frontend only: `analytics.js`
(charts use columns every row carries; NEW `tableColumns`), `Charts.jsx` `DynTable`, `ChatExport.jsx`; `npm run build`.
NEW `tests/test_cross_compare_card_2026_10_22.py` (node). Nothing committed. NOT CHECKED in a browser: reload /megh-chat
and ask "MGNREGA vs PMAY-G households" — expect the card on amount (₹ crore) and both count columns in the table.

**Latest (2026-10-22 night, D-065 / KI-394 / KI-395): a pause reply keeps the typed question's kind; a new
question with no year asks the year.** User's Mairang chat ("…for mairang?" -> chips -> "FY 2025-26 (new question)").
Changed: `app/session_store.py` (`pending_turn_kind` + snapshot), `app/routers/query.py` (`remember_pause`), c14
(`_turn_context_stage`: carry the kind, tapped-chip match, re-pin CM Elevate after a scope resume; `_turn_followup_stage`
`_tk`; `_same_scheme_context_year(kind=)`), c13 (latest-FY default removed -> year chips). Tests: +6 in
`tests/test_new_vs_followup_2026_10_22.py`, 1 re-specified there and 1 in `test_pipeline_graph.py`; harness
`new_vs_followup_2026_10_22.yaml` (NQ01/07/08/09/11/12 + 2 new NQ_D065_*), AC04c, F3, U5, N3 re-specified. Results in
TESTING. Nothing committed. NOT RUN: http harness (restart :8401 from the venv when the parallel session is done) and
the live context suite. ASK THE USER: U5 / KI-331 conflict (CURRENT_STATE). Open: KI-396, META_recap turn 7.

**Latest (2026-10-22 night, D-066 / KI-387..392): cross-scheme figures worked out in code.** User gave
`Cross_Scheme_Issues_and_Solutions_2026-10-22.md`: "fix these immediately". NEW `app/cross_figures.py` answers
beneficiaries / money / village coverage of MGNREGA, PMAY-G, Focus Plus, Focus Legacy (state, district(s), block, per
district, one FY) from fixed queries with the combine step in Python; c13 exclusions first + bare-FOCUS ask; c14 keeps
these DATA; Focus+ ranked district breakdown drops the no-district row; c11 drops an unasked HAVING threshold.
UAT 60: 20/60 -> 59/60 = megh_db, 47/60 = raw (rest = KI-393 data). pytest 3,647/0, scripts 14/14. Reports:
`new_docs/Cross_Scheme_Test_Report_2026-10-22.md` (§6 after the fix), `new_docs/Cross_Scheme_Issues_2026-10-22.md`.
Nothing committed. NOT RUN: http harness, live context suite (restart :8401 from the venv first). Ingestion items of
the issues document are theirs (megh-ingestion). The D-062 model path still answers village / block lists.

**Latest (2026-10-22 evening, D-063 / KI-377 / KI-378): answer shapes + live KPI cards.** User: "if I ask top 10, top 5
or compare … different answers" and "kpi cards … update dynamically … based on the data correctness". Changed: NEW
`app/pipeline/common/c12_answer_shapes.py` (+ `_PIPELINE_FILES`), c13 `compose_response` (shape block, derived figures,
breakdown order, `_shaped_fallback` before `_framed_fallback`), `app/routers/stats.py` (`_YEARS_SQL`, `_period`, "(N yr)",
"—"), `frontend/src/chat/constants.js` (`period` / `periodLead` / `metaTail`, `STATS_SYNCED`), `api.js`, `WelcomeCard.jsx`
(refresh + status line), `chat.css`; `npm run build`. Tests: NEW `tests/test_answer_shapes_2026_10_22.py` (26), 3 new in
`tests/test_scheme_stats.py`. pytest 3,568/0, scripts 14/14, live 12 shape questions + card figures = DB (scratchpad
`live_shapes.py`, `kpi_live.py`). :8401 restarted from the venv at 15:42 and checked over HTTP (health, new UI build, `periods`, a top-5 answer).
A parallel session then extended `c12_answer_shapes.py` (18:12: `_c12s_rollup_split` for ROLLUP total rows, KI-384;
every measure per item in a breakdown fallback, CM Elevate Legacy TC-36) and restarted :8401 (18:39, venv); re-checked
18:40: shape + stats tests 31/31, HTTP health / UI / `periods` / top-5 answer OK.
NOT done: live context suite / http harness, commit (user: don't commit yet).
Next (phase 2, ask the user first): route the fixed per-scheme answers (PMAY-G facts, MGNREGA summary / job cards /
combined facts, Focus Legacy breakdowns, CM Elevate sectors) through the shaped composer, keeping their text as fallback.

**Latest (2026-10-22 evening, D-064 / KI-379..386): CM Elevate Legacy sheet — all fixed, live 300/300.**
User decision D-064: a bare "CM Elevate" with financial words -> CM Elevate Legacy directly; otherwise ask
"CM Elevate (applications) or CM Elevate Legacy?". Then "fix all of these": KI-381 (Legacy constituency: rewrite
`_cm_legacy_ac_as_place_filter`, guard `_cm_legacy_ac_filter_missing`, verifier discard — c11), KI-384
(`c12_answer_shapes._c12s_rollup_split` + c13 `compose_response`; multi-measure breakdown fallback), KI-382 (c14 route:
scheme overview -> KNOWLEDGE, `_scheme_overview` skips the figure-summary flip; CM Elevate overview retrieval), KI-383
(`_cml_no_records_sentence`), c04 `_each_scheme_in_cm_thread` ("which / across / by schemes", Legacy vocabulary).
Files: `schemes/cm_elevate.py`, `schemes/cm_elevate_legacy.py`, c04, c11, c12_answer_shapes, c13, c14. Tests: NEW
`tests/test_cm_elevate_legacy_sheet_run_2026_10_22.py` (19) + D-064 updates (TESTING). pytest 3,608/0, scripts 14/14;
live: sweep 300/300, sheet wording 96/108 (rest = cross-scheme reading of "which schemes" in a new chat, by design),
one chat 72/72. :8401 restarted from the venv. HTTP harness full set **136/139 scenarios, 410/420 turns** (`logs/conversation_harness/2026-10-22_1906_d064-http.json`); E_hierarchy_drill_and_rollup = 7 transport errors, **passes on re-run** (`_d064-http-rerun.json`); the 2 left are not CM Elevate: META_recap_explain_breakdown (PMAY-G block ranking without its 375 total, D-063 answer shapes) and CMP_compare_with_scheme (the removed D-062 comparison card). Every CM Elevate scenario passes (AC04 / AC04b / AC04c, P5, AF11, AB03, U4); E_denied_block_keeps_topic and AU01 pass over http. Nothing committed. A parallel session (D-065) edited
c14 / cm_elevate_legacy / scenarios during this session — both sets of changes are in the working copy.

**Latest (2026-10-22 late afternoon, KI-375 / KI-376 fixed):** `schemes/cm_elevate_legacy._cm_legacy_crore_alias_on_rupees`
and c11 `_village_rows_by_code` (both in `_scheme_sql_rewrites`); tests `tests/test_sql_rewrites_ki375_376_2026_10_22.py`.
NOTE: a parallel session is editing `app/pipeline/__init__.py` / new `c12_answer_shapes.py` — two pytest failures seen
mid-run were green alone. :8401 restarted. Nothing committed. Still open from D-062: rewrite
`tests/sheet_runs/cross/truth.py`; a comparison line when 5-6 schemes fall back to sections.

: cross-scheme questions are answered by the model, one query per
scheme, with no fixed template.** User: "top ten highest villages in Mgnrega and pmay" got the statewide totals card;
"no template … whatever the user asks". Changed: `app/cross_scheme.py` (only detection and the place helpers remain);
c13 (`_cross_scheme_scope`, `_cross_scheme_gaps`, `_cross_scheme_subquestion` + `_cross_subquestion_violation`,
`_cross_scheme_base_question`, per-scheme always for cross, `_cross_scheme_rows_in_crore`, `_cross_schemes_left_out`
/ `_cross_scheme_sections`, `_cross_scheme_leader`, `_cross_scheme_complete_lists`, `_cross_scheme_no_figure_lines`;
`_literal_sql` removed); c06 (money-ranking template removed); `prompt_builder.build_cross_subquestion_prompt`.
pytest 3,530/0, scripts 14/14, live 20/20 sheet questions + the user's question (TESTING). :8401 restarted from the venv.
Nothing committed. Next: KI-375, KI-376; rewrite `tests/sheet_runs/cross/truth.py` for the per-scheme answers;
consider a short comparison line when 5-6 schemes fall back to per-scheme sections.

**Latest (2026-10-22 ~13:45, D-061 / KI-373): "New Question = New Answer" context rule.** User gave
`Context_Memory_New_vs_Followup.pdf` and asked for every scenario, not only follow-ups. Changed: `context_policy`
(`turn_kind`, `asked_levels`, `TurnKind`), c01 (`is_scopeless_followup` same-scheme branch removed; Hinglish
`wala/wali/wale` in `_HINGLISH_GLOSS`), c14 (`_turn_followup_stage` classifies first, standalone never rewritten,
`_vague_topic_clarification`, `_same_scheme_context_year` returns None for standalone, `_c14_kept_place_fields`
asked-level guard, banner "(new question)"), c13 (latest-FY default for a standalone question in a chat with scope),
`pipeline_graph._data` (`turn_kind`), harness checks (`new_question`, `place_not`, `year_not`). Tests: NEW
`tests/test_new_vs_followup_2026_10_22.py` (90), scenarios `new_vs_followup_2026_10_22.yaml` (33); superseded
expectations updated (D-056 file, KI-331 tests, 10-18 same-scheme test, ranking file, N3, C_backward_restore, F3).
pytest 3,515/0, scripts 14/14, http new scenarios 33/33. :8401 restarted ~13:00 (venv). Full http harness: TESTING.
Nothing committed. Open choices for the user: idle window 30 min vs the current 8 h; latest-FY default vs asking.

**Earlier (2026-10-22 ~13:30, KI-369 / 370 / 371 FIXED): Focus Legacy sheet re-tested and its three failures fixed.**
User: test `raw_uc/Use_Cases_-_Focus.csv` against DB + raw `raw_uc/Focus Legacy to share to BLH.csv`, then "fix all
these, don't change any other". Changed (Focus Legacy only): `schemes/focus_legacy.py` — `_fl_equals_focus` /
`_focus_legacy_scheme_name_not_variant` (FOCUS_PG), new `_focus_legacy_ac_name_case`, `_focus_legacy_ac_filter_missing`,
`_focus_legacy_ac_verifier_complaint_is_false`, `_focus_legacy_aggregate_complaint_is_false`,
`_focus_legacy_members_counted_as_groups`; c11 — hooks in `_scheme_sql_rewrites`, `_execute_one_attempt`, `_verify_sql`.
Live: sweep `fl_run.py` 231/231 (was 186/231), sheet wording 84/84, 55/55 constituencies (was 12-15; the 13 Oct code had
55/55 — it was a regression from the 17-20 Oct commits). pytest 3,416/0 on the final code (see
TESTING), scripts 14/14. Every village `fl_all.py` on the fixed code **3,363/3,384**: 19 misses are KI-372
(the 30B adds an unasked filter — 13 x `pg_id = 'PG-FOCUS-WKH/WGH-7089'`, the example id in the Focus Legacy resolver
YAML), 1 "Mawkohmit & Mawkynsah" read as two villages, 1 test-side pause. Report + CSV in
`new_docs/Focus_Legacy_*_2026-10-22.*`. NOT done: http harness, :8401 restart, commit. Next: KI-372 (guard on an unasked
pg_id / variant / type / year filter — awaiting the user's go-ahead), KI-359, KI-362.

**Earlier (2026-10-22 ~12:00, KI-366 FIXED): a follow-up that ranks a place level no longer keeps the chat's place at
that level.** User chat: Demdema block answer -> "Which block has highest number of households?" answered Demdema's 0.
Changed: `context_policy._RANK_OVER_GEO_MATCH` (+ CLEAR in `plan_state_merge`), c14 `_ranking_followup_question`
(deterministic rewrite branch after the KI-334 measure-change one). Live (scratchpad `perm_demdema.py`): Tikrikilla
58,306 / person-days 4,689,766 / top 3 listed, = DB. pytest 3,375 + new file 21/21, scripts 14/14, http harness
102/102 & 313/313. :8401 restarted ~11:30 (venv). Nothing committed. Next: KI-367, KI-368, then KI-359, KI-362.

**Earlier (2026-10-22, KI-360 / KI-361 FIXED): FOCUS-019 and FOCUS-004 pass in every phrasing.** User: "fix focus 019
and focus 004 ... should pass for different permutations and combinations". Changed: c14 `_overrules_scope_verdict` +
`_C14_COHORT_WORD`; edge `_DOMAIN_WORDS` (batch labels, "tranch", "break down" ...); focus_plus `_FP_12_5_SPACE_K` /
`_FP_93_SPACE_K` in `_FOCUSPLUS_ONLY_TERMS`, block-literal snap in `_focusplus_lgd_only_block`; c09 early urban-body
step for Focus Plus + constituency slot; cm_elevate `_cm_elevate_block_from_mention` reads Focus Plus raw blocks.
Live permutations (scratchpad `fp_perm.py`) 019 25/25, 004 96/96; sheet `fp_run.py` 161/163 (misses = open KI-359,
KI-362); ward villages 155/155; CM Elevate boards 5/5. pytest 3,363/0, scripts 14/14. NOT run: http harness. :8401
NOT restarted (serves old code). Nothing committed. Next: KI-359 (`district_name_raw` guard), KI-362.

**Earlier (2026-10-22, KI-359..365): Focus Plus sheet re-tested at every level. No app code changed (report only;
fix after the user confirms).** `raw_uc/Focus+ Test Case Observation.xlsx` vs `raw_uc/Focus Plus Master.csv` (raw = DB,
385,671 rows, every field; village codes differ only by the ingestion's name mapping). Sweep `fp_run.py` 161/163, every
village `fp_all.py` 3,513/3,513, sheet wording + chats (scratchpad `fp_literal.py`) 79/85 and 12/14 turns. To fix once
confirmed: KI-359 (SQLGlot guard `district_name_raw` -> `lgd_district` for Focus Plus), KI-360 (c14 overrule: "12.5K
batch" is data), KI-361 (Shillong Municipal Board), KI-362 (per-beneficiary average guard), KI-363/364 (c01 follow-ups),
KI-365 (composer note). Report `new_docs/Focus_Plus_Test_Report_2026-10-22.md`, CSV
`new_docs/Focus_Plus_all_conversations_2026-10-22.csv`. pytest / harness not run (no code changed). Nothing committed.

**Earlier (2026-10-22 ~00:50, D-060, KI-356..358): PMAY-G sheet re-tested and fixed.** User asked to test
`raw_uc/PMAY-G.xlsx` against `raw_uc/PMAY_FullyMapped_with_dates.xlsx` (raw = DB, 171,107 rows, every field), then:
"126 rows sanctioned amount 0 is also considered as beneficiaries and fix all the failed use cases". Done: D-060
(pmay_g.py fixed path, `_pmay_count_placeholders` model-SQL guard, schema_context rule 1 + cross-scheme beneficiary
example, c11 village-ranking guard skips v_pmay, `_pmay_attach_placeholders` removed), KI-356/357 (c15 overview skips
PMAY-G financial summary / performance), KI-358 (c01 `_c01_kept_finer_place` + `district=True` swap; level word read
without "?"). Sweep 678/678, extras 76/76, follow-ups 4/4, pytest 3,300/0, scripts 14/14, http harness 102/102 &
313/313. `tests/sheet_runs/pm_run.py` / `pm_all.py` expected values follow D-060 (pm_all NOT re-run). :8401 restarted
00:35 (venv). Report `new_docs/PMAY-G_Test_Report_2026-10-22.md` §7. Nothing committed.

**Earlier (2026-10-21 night, KI-352..355): MGNREGA re-tested on the final code, every metric at every level.** No app
code changed (user rule: no code change before they confirm). Use-case sweep 782/783; new matrix
`tests/sheet_runs/mg_matrix.py` direct figures 270/270, rankings 35/42. To fix once the user confirms: KI-352 (AC
ranking: add `assembly_constituency_name IS NOT NULL` deterministically; "25-26" read as an AC name), KI-353
(expenditure by constituency: decide the wanted answer), KI-354, KI-355. Report `new_docs/MGNREGA_Test_Report_2026-10-21.md`
§10, CSV `new_docs/MGNREGA_all_metrics_all_levels_2026-10-21.csv`. Nothing committed.

**Earlier (2026-10-21 ~22:00, KI-351): bare village names inside a running chat (a parallel session).** User flow:
MGNREGA, West Garo Hills, all years, five questions, then villages without "village". Bare names already resolved;
fixed four context faults (details KI-351): another village typed at a "which <village>?" pause (c14
`_c14_pause_place_switch`); "go back to …" recorded as the typed words (c14 `restored_question` ->
`_mark_context_dependent`); the village CODE shown to people / sent in "compare with" (`topic_memory.place_words`);
"figure for <district>" on a village answer (c12 `_display_from_resolved`) + "…, shown?" (c01). Live 13-turn chat
(scratchpad `repro_wgh_bare_village.py`) all correct, figures = DB. pytest / scripts: see TESTING.md. NOTE: :8401 was
restarted by the other session at 21:33, BEFORE the c12 / c01 parts of this fix — restart it again to serve them.
Not run: http harness. Nothing committed.

**Earlier (2026-10-21 ~21:00, D-059 §6, KI-348/349): complete place hierarchy by the database — user deadline next day.**
User rule: one level -> that level; same name at several levels -> ask; no hard-coding. Changed: c09 (stated level
vs database, single-level move with `_c09_scheme_levels`, district named with a finer place, AC-suppressed one
reading, extractor-empty backstop, HQ-alias move scheme-aware), entity_resolver (`_level_index` + `_match_forms`,
cache-key bug fixed, alias-only district, `village_code_name` / `village_code_place`, long constituencies first),
c01 (`_c01_strip_chip_level`, every copy of the old place, no district for a same-name place), c07 hint (coarse to
fine, constituency only when signalled), c10 `_stray_block_literal`, c14 banner + measure-change place,
context_manager (village name in state; village sets its own block / district), mgnrega re-read. NEW live sweep
`tests/live_place_hierarchy_sweep.py` (in-process; needs the VPN). `resolve_village` real name beats another
village's alias (Nongspung B); 345 alias collisions reported to ingestion in
`docs/PlaceHierarchy_DB_Issues_2026-10-21.md`. FINAL: pytest 3,273/0, scripts 14/14, sweep 272/272, live chats
17/17. Then KI-350 (MGNREGA "sanctioned amount" -> column-not-held pause + expenditure chip; a scheme reply to
that pause continues the paused question). http harness full set (stream) **102/102, 313/313**. :8401 restarted
21:33 onto the final code. Nothing committed.

**Earlier (2026-10-21 ~18:00, D-059, KI-342..345): the level of a place comes from the database (`PLACE_GAZETTEER`, on).**
User report "How many job cards in Mawphlang?". Mawphlang is a block + constituency (no such village), so that pause
is correct; bare villages already worked on the D-058 code. Fixed the level decision: entity_resolver
(`village_places`, `village_scheme_data`, `village_fuzzy`, `match_places`, cached `_level_index` / `_ac_forms`,
exact-village + typo-lead rules in `collides_across_dimensions`, `resolve_village` look-alike narrowing, CENTRE etc. in
`_VILLAGE_SOLO_DENY`), c09 `_c09_gazetteer_settle` (+ silent pick through the chip question), c01 `_place_swap_rewrite`
(same rule), c07 `_c07_places_hint` (extraction prompt) and `_c07_chip_where` (chip parents), config `PLACE_GAZETTEER`.
Tests: `tests/test_bare_place_names_2026_10_21.py` 37; NEW live `tests/live_bare_place_level.py` 14/14. Harness
in-process bare_place + user_reported 33/33. Then the user's live chat found KI-346 ("give me for dalu" after a PMAY-G
by-district answer -> village chips DALUAGRE / DALUGAON): fixed (c09 village->block guard, c01
`_c01_drop_coarser_breakdown`), answer 268 = DB. Then KI-347 (user's PMAY-G chat 18:33-18:37: measure lost after a
rejected rewrite, Pakregre labelled West Garo Hills, invented "Dalu village" / "fund utilization", "its block" to a
village pause -> documents): fixed in c01 (`_place_swap_rewrite(force=True)` on rejection, `_c01_invented_level`,
`_c01_place_only_drift`), c09 (`village_code_place`: the village's own district), c14 (`_c14_level_only_reply`,
`_c14_restate_level`). Test file 42, live 17/17. :8401 restarted from the venv at 18:06, after KI-346, after KI-347.
The http `--stream` full harness run was STOPPED part-way at 18:18: it shares the server's 30 req/60 s rate limit with
the user's browser, which caused the user's "Rate limit exceeded" error. Run it only when nobody is using :8401. Route
village-name search left as is on purpose (D-059 §5). Nothing committed.

**Earlier (2026-10-21 ~17:15, D-058, KI-339/340/341): places named without "village" / "block" / "constituency".**
User report: "in ambare ading" after a PMAY-G East Garo Hills answer was declined as off-topic. Fixed in
entity_resolver (village-name index, `place_mentions`, `place_only`, `place_levels`, `is_village_name`), context_policy
(continuation "place" at any level; `rewrite_violation` keeps typed places), edge (step 6), c01 (`_place_swap_rewrite`,
`_restore_typed_village`), c09 (same-name level rule; the chat's district not carried onto another district's block,
the block's own district named instead), c14 (index lazy-load, `_names_place_only`), main.py (startup load). Tests
`tests/test_bare_place_names_2026_10_21.py` (22), harness `scenarios/bare_place_name.yaml` (P1-P16). pytest 3,234/0,
scripts 14/14, harness in-process 33/33 (bare_place + user_reported); :8401 restarted from the venv 16:53 (user
request; the old server ran pre-fix code), http `--stream --tags bare_place` 16/16. NEXT: full http set, caches on (`--stream --repeat 2`). P9 / U3 in the ~17:00 http run below were fixed
after it. BEHAVIOUR CHANGE to review: a bare "Sohra" / "Mendipathar" / "Wapung" no longer asks "constituency/block or
village?" when no village has that exact name (D-058). The MGNREGA-sweep session (KI-338) should re-run DATA-003 /
DATA-016: block names now answer directly. Nothing committed.

**Latest (2026-10-21 ~17:00, KI-337): context memory re-accepted end to end, caches ON.** Full harness, stream, caches on,
twice: 200/204 — remaining P9 + U3 belong to the parallel session's unfinished place-only rewrite (c01
`_place_swap_rewrite`, c09, `bare_place_name.yaml`): FOR THAT SESSION, U3 ("now give me for dambo rongjeng block" after a
Focus Plus Gobekram village answer) passed all day before your edit and now answers null in Dambo Rongjeng without
East Garo Hills. KI-337 fixed: "show me for X" is a follow-up (c01 `_FOLLOWUP_LEAD`), and `is_cacheable` never shares a
scheme-less question from a chat with a scheme. Harness acceptance should always include a caches-ON pass
(`--stream --repeat 2`, no `--skip-cache`). :8401 restarted from the venv ~16:15; :8400 servers stopped. Nothing committed.

**Latest (2026-10-21 afternoon, D-057, KI-336): the year asked is the year answered.** MGNREGA sheet tested end to end
(report + every conversation in `new_docs/` — the user's folder for reports). Fixed: job cards follow the year asked /
chat year / year pause, all years = one row per year (`_mgnrega_job_cards_query` + `_mgnrega_job_cards_answer`, c13
deterministic + post_rows via the `/* mg-job-cards */` mark — no graph change); composer and closing line take the
SQL's year (`_entities_with_sql_year`); code-only places never "statewide" (c12 `_finish_data_result`). Few-shot +
schema rule 3 no longer teach `year_key = 2025`. pytest 3,199/0, scripts 14/14, sweep 775/783. Then KI-337 (DATA-014
repair drift to the fact table) fixed: `_mgnrega_fact_to_view`, `_mgnrega_village_rank_placeholders`; DATA-014 live
56/56 twice; pytest 3,205/0. Then KI-338 (DATA-016: households as a village count; `entity_type = 'Block'` -> NULL)
fixed: `_mgnrega_unit_count_not_villages`, `_mgnrega_drop_area_level_entity_type`, schema rule 4a, one few-shot.
**FOR THE D-056 / entity_resolver SESSION — KI-339: since ~16:00 a bare block name pauses with village look-alikes
only (DALU -> DALUPARA/DALUAGRE/DALUGAON, no "The DALU C&RD block"); also c01_followups.py held 2 raw NUL bytes at
16:00:46 (line 1196, the "\x00" marker) — the whole package failed to import until it was re-saved at 16:02.** Still
open from the report: "FY24" read as FY 2024-25. THIS SESSION AND THE D-056 SESSION BOTH EDITED c13 TODAY — review both before committing. Nothing
committed. User rule: no code changes before they confirm.

**WARNING (2026-10-18): two sessions edited this tree in parallel.** The other one added `c15_conversation_meta.py`, KI-310..313 and a SECOND `KI-309` row (KNOWN_ISSUES, the later one; this session's KI-309 is the UI-context one) — renumber theirs when reconciling. This session's stale-worker finding is KI-314.

**Latest (2026-10-21, D-056, KI-335): context memory — the user's rule, restated firmly: "new chat -> ask scheme, then
district, then year if nothing is in context; inside a chat carry everything forward and update only what the user
names."** Code: c13 `_chat_has_data_scope` + district pause in `_data_clarification_stage`; c14 `_same_scheme_context_year`
(now any one scheme, place always, re-read in the target scheme's catalogue); c09 fallback guard + display; c15 callback
direction; router `is_cacheable`; `pipeline_graph` (`chat_has_scope`, `inherited`). Tests
`tests/test_new_chat_and_scheme_switch_2026_10_21.py`; harness `scenarios/user_reported_2026_10_21.yaml` (N1-N3, the
user's own chat). After ANY context change run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m
tests.conversation_harness.run --driver http --skip-cache` (the env var is needed: the printer crashes on "₹" otherwise).
NOTE: `.venv` is Python 3.11.9 and had NO pytest — installed `pytest pytest-asyncio` 2026-10-21. Stray servers on :8400
(PIDs 30884 / 10524, from an earlier session, one on the SYSTEM Python) were left running — the port rule says stop them.
Nothing committed.

**Earlier (2026-10-21): clarification chips restyled to the user's design #11 "Plain card · Pill chips"** (scheme / financial
year / district each get their own "Choose a …" line; search for scheme and district; "+N more"; "All …" outlined). Frontend
only, `npm run build` done. Headless `tests/ui_headless/clarify_pills.py` OK. NOTE: Python 3.14 (the Playwright Python) is no
longer installed — the run used a scratch venv with `pip install playwright` and `channel="msedge"`. Nothing committed.

**Latest (2026-10-19 ~17:40, D-055): conversational layer from `documents/Megh_One_AI_Conversational_Memory_Approach.pdf`** —
"go back to the first one" (was a KB answer), "I'm Ravi" (name kept for the chat), coverage ("which years / which districts
can I see"), greeting back / "You're welcome" on mixed messages, rule-computed callback "That's down from X in FY …", one
steer-back per run of asides, thanks chips, first greeting introduces once, scheme list with one chip per scheme, shorter
D-054 scope sentence. Harness `scenarios/conversational_approach.yaml` (tag `conversational`); unit tests
`tests/test_conversational_approach_2026_10_19.py`. NOT done: kha / grt / hi templates, voice, lakh/crore display of counts,
tone rubric. Pre-existing failures seen (not this change): `test_followup_stage_runs_the_correction_in_the_previous_scope`,
`test_stop_continue::test_the_decided_defaults` (pins 4 h; the user set 8 h). Nothing committed.

**Latest (2026-10-19 ~16:30, KI-333): chart-type requests** — c15 `_chart_view_question` (c14 step 0h-view) redraws the previous data question as the type asked ("why ... giving X" = the wrong type), `chart_wide` for "wide frame"; topic memory no longer reads "I asked about pie chart" as a back-reference; UI: no line chart for by-district rows. `npm run build` done. Headless: `py -3.14 tests/ui_headless/chart_view_requests.py`. WARNING: 8401 keeps being restarted from the SYSTEM Python by the parallel session (16:09, 16:26, 16:28) — it ran my code, but it should use the venv. Nothing committed.

**Earlier (2026-10-19 ~15:45, KI-332): scheme swap after a cross-scheme comparison** — "now give me for cm elevate" after "Compare PMAY-G and MGNREGA ..." no longer becomes "Compare CM Elevate and CM Elevate": c01 `_comparison_swap` writes "Same comparison for X: <measures + scope>", answered by `cross_scheme.detect` as the one-scheme card; "and X too" adds X. Live-verified on 8401 (5 conversations incl. both CM Elevate chips). NOTE for the KI-330 owner: your graph test `test_cm_elevate_after_a_legacy_answer_switches_dataset` failed once mid-edit at 15:10 and passes now. Nothing committed.

**Earlier (2026-10-19 afternoon, KI-325): two-dimension charts** — scheme x year / district x year drawn with the period on one axis
and one series per scheme / district (`TwoDimChart`); insight "since" only over periods. `npm run build` done. Headless check
`tests/ui_headless/chart_two_dim.py` (run with `py -3.14`, the only Python here with Playwright). PORT 8401 ONLY.

**Earlier (2026-10-19 morning, D-054, KI-321, KI-322): answer framing** — `_framed_fallback` / `_finish_answer` /
`_finish_data_result` (c12; finalize node). c12's tail (`_unit_suffix` … `_entity_names_block`) was accidentally cut and
restored from HEAD at 11:20 — if the parallel session had edited that region on 2026-10-18, re-check it. Also KI-323 fixed (c11 `_calendar_year_range_issue`: a financial-year question answered for the calendar year — the harness `truth`
check caught 110,890 vs 106,527). FOR THE D-053 OWNER: KI-324 — your MGNREGA year pause offers "all of them combined" in words but
has no chip for it and does not accept it typed (re-asks); Focus Plus / CM Elevate Legacy pauses do have the chip. Also
`test_ki148…` fails against your 6-option `_scheme_clarification`. Harness scenarios were aligned to D-053 and to crore money.
NEXT: KI-322 (households employed: two totals); KI-324; keep D-053 and D-054 consistent in the composer prompt.

**Earlier (2026-10-18 evening): conversation harness `tests/conversation_harness/`** — YAML scenarios + checks + http / in-process
drivers + reports (README in the folder; TESTING.md §2b). First live run 16/17 found KI-315 (now fixed: c11 `_verifier_total_vs_breakdown_is_false`) and a failed-turn rewrite bug
(fixed: c14 `_mark_failed_data_turn`); full set now 17/17, 72/72 turns. Use it (http driver) to accept any context /
conversation change. NEXT: a scenario for KI-318 once fixed; wire a nightly run; restart the deployed servers.

**Earlier (2026-10-18 late afternoon, KI-315, KI-316, KI-318): context memory ACCEPTED through the HTTP API.** Forward, out-of-context (incl.
refusals, denials, place/year leak, cached and streamed), backward, general, hierarchy (drill-down AND roll-up) all pass on the
running server with both a district-level and an unrestricted account (CURRENT_STATE "Latest"). Fixes: refusal / denial are asides;
deterministic roll-up from the topic ledger with a CLEAR plan (c15 `_rollup_question`, c14 step 0h'). ALWAYS test conversation
changes through the API (sessions hold one turn on the server). Also KI-320: "compare with pmay" -> cross-scheme comparison in the same scope (c15 `_compare_with_scheme_question`, c14 step 0h'').
NEXT: KI-318, KI-315; restart the deployed servers. Nothing committed.

**Earlier (2026-10-18 afternoon, D-052, KI-310..312): the chatbot talks about the conversation** — `c15_conversation_meta.py`
(recap / explain / misread / suggest / reason; correction / breakdown with an apology; place overview; "last year" with no
year -> which-year pause), thanks / farmer / opening-filler fixes. Live-verified on the user's own conversation (see
CURRENT_STATE). NEXT: (1) restart the deployed servers (code only); (2) KI-311 — MGNREGA two-year and two-fact-by-block
shapes answer one year or fail; (3) KI-312 — Focus Plus overview drops the amount; (4) KI-313 — eval MG-08 verifier false positive on a year range
(c11 discard rule); (5) try the chips in the browser at phone width. Nothing committed.

**Earlier (2026-10-18 afternoon, KI-317): "show me the districts, I'll choose one" after a data answer now offers district chips**
(c14 step 0g, c05 `_asks_to_pick_district` / `_pick_district_clarification`) and the rephrase guard accepts contractions (c02
`_is_known_word`). pytest 2,834 / 0; scripts 14/14; eval 74/74; live-verified. NEXT: try it in the browser (chips at phone width);
decide whether the same "pick one" should offer blocks within a district. Nothing committed.

**Earlier (2026-10-18, D-050, KI-307): context memory — every phase of `documents/MAIN_Contex.pdf` built
and LIVE-VERIFIED.** Backward memory (question ledger, by order / content / 9B pick), "what did we discuss?",
place-level clearing, scope banner, "Continue with …?" after idle expiry. Code: `app/topic_memory.py`,
`app/conversation_layer.py`, `app/context_manager.py`, `app/session_store.py`, c14 (`_attach_scope_banner`,
`resolve_reference` call), `pipeline_graph.node_finalize`, `routers/query.py`, `conversation_store.py`, frontend
`Messages.jsx` + `chat.css` (built). Tests `tests/test_topic_ledger.py`; live scenarios N..R. Also stop -> "continue" (`tests/test_stop_continue.py`,
`frontend/src/chat/stopContinue.js`, `Session.stopped_ctx`). D-051: 50 turns / 20 per topic / 4 h idle — set
`SESSION_TTL_SECONDS=14400`, `SESSION_MAX_TURNS=50` in every deploy `.env` (they override the code). Late evening: KI-308 + KI-309 fixed, `tests/live_context_matrix.py` (7 flows x 6 schemes): **42/42 live
conversations pass** (see TESTING for the three runs and the DB-flap caveat); scenarios F, U1, U2 pass; full pytest
2,940 / 0 failed. NEXT: (0) after any context change, run `tests/live_context_matrix.py` and
`tests/live_context_validation.py --only F,U1,U2` with the VPN up; (1) browser check DONE via `tests/ui_headless/` (banner, stop/continue, go back, history at 3 widths) — only the
idle-expiry "Continue with …" chip is still unseen in a browser; (2) WI-9 / mid-sentence comparison if
wanted; (3) the AI_PIPELINE model-roster DOCUMENTATION CONFLICT (classifier / verifier rows vs the 2026-10-15
role map). Nothing committed.

**Earlier (2026-10-16, evening, D-049):** chatbot side of the ingestion team's DB changes — see CURRENT_STATE "Latest"
and `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-16.md`. NEXT: (1) get the megh_readonly password, set
`READONLY_DATABASE_URL`, `READONLY_DB_ALLOW_SUPERUSER=false`, restart every server (KI-304); (2) restart the Docker
deploy so the smaller pool takes effect; (3) live-check the note's "known answers" (CM Elevate 8,840; on hold 908;
approved -> not available; Mawlai asks). **WARNING: another session edited this tree in parallel (17:10-17:35:
mgnrega.py, c11, questions.yaml, test_general_sql_rewrites_2026_10_16.py).** Eval PM-04 ("Counting every financial
year ... Roof Cast") now loops between `_breakdown_missing_issue` (wants per-year) and the "ONE combined figure"
guard (c11 ~L1835) and falls to the KB — correct at 17:11, not caused by D-049; for that session to resolve.

**Latest (2026-10-16, D-047 / D-048):** the codebase has NO regex at all (text: `app/text_match.py`; SQL:
`app/sql_ast.py`). Business definitions for gender / people across years / households vs persons are in
`app/schema_context.py`, the MGNREGA and Focus Plus few-shots (executed), and `_mgnrega_people_years_alias`.
SME to confirm "MGNREGA beneficiaries = households". pytest 2,606 / 0 failed.

**Also 2026-10-15 (D-046, KI-303): no regex on SQL anywhere.** All SQL reading/rewriting uses SQLGlot via
`app/sql_ast.py` (auth, every pipeline guard/rewrite, `_extract_sql`, offline validator, test harnesses). Never add a
regex that touches SQL. pytest 2,585 passed / 0 failed. Open: `tests/test_context_manager.py` (script) fails on the
separate memory-retention change in `app/conversation_memory.py`; the stale nested copy `meghalaya/meghalaya/` still
holds the old regex code (not run by anything).

**Also 2026-10-15 (KI-302):** cross-scheme answers no longer show an empty second table ("—" / 0) under the
answer: `Messages.jsx` skips analytics when `response.cross_scheme` is set, and `conversation_store` stores the flag.
UI rebuilt. Next: check one district-wise cross-scheme question in the browser.

**Latest (2026-10-15): `app/pipeline.py` no longer exists.** It is the `app/pipeline/` package: `common/` (shared steps
c01..c14) + `schemes/` (one file per scheme), one namespace via `__init__.py`. Edit the file that holds the function;
a `pipeline.py` recreated next to the package is silently ignored. Behaviour-identical (pytest 2,372 pass, 14/14 scripts).

**Latest (2026-10-14): answer, don't ask (D-045) + hierarchy matrix. Code changed, uncommitted.**
- ANSWER_DEFAULTS_ENABLED (config.py) replaces the scope / year / tranche / scheme pauses with the chip text; real
  ambiguity still asks. Tests `tests/test_answer_defaults_2026_10_14.py`; graph pause tests turn the flag off.
- Matrix harness `tests/sheet_runs/matrix/matrix_run.py [state district block ac village]` (resumable; truth from
  megh_db). state/district/block/AC 2,150/2,150. Village family (21,632) run as a detached process
  (Start-Process; background shells die with the session) — resume with the same command.
- NEXT: finish villages + re-run their failures; re-run the six finished sheets (tests/sheet_runs/*_run.py) since
  the defaults change every scheme; decide with the user which line (this branch vs GitHub main with NRLM) to merge.
- `.venv` is Python 3.12 (rebuilt 2026-10-13); pytest / pytest-asyncio / openpyxl installed.

**Earlier (2026-10-13, evening): Cross Scheme sheet + generated cross-scheme permutations. Code changed, uncommitted. LIVE-VERIFIED.**
- `reference_documents/Cross Scheme Test Cases.xlsx` (backup in `reference_documents/backup/`): Sheet1 D..H = 9th Run (0/20) and
  After Fix (20/20); tabs `Coverage` and `All conversations` (8,649/8,649). Process in `reference_documents/README.md`.
- New `app/cross_scheme.py` (D-044) + hooks in `_data_scheme_stage` / `_data_entity_stage` / `_data_clarification_stage`;
  graph DATA keys `cross`, `pre_rephrase_question`. KI-280..288 fixed. Tests `tests/test_cross_scheme_sheet_fixes.py` (28).
  pytest 2,258 passed; scripts 14/14. Re-run: `tests/sheet_runs/cross/cross_run.py <families>`, then `write_report.py`.
- OPEN: KI-289 "FY2022-23" (no space) not read for single-scheme questions — needs a decision (shared resolver; the finished
  sheets would need a re-run). KI-290 low.
- Env: `.venv` rebuilt on Python 3.12 (the old one pointed at another machine); pytest, pytest-asyncio, openpyxl installed.

**Earlier (2026-10-13): FINAL ROUND — all seven sheets 206/206 test cases, 2,946/2,946 conversations. LIVE-VERIFIED.**
- Report: `reference_documents/Final_Test_Report_2026-10-13.xlsx`. Workbook tabs FOCUS Legacy (renamed by the user from
  FOCUS) and CM Elevate Legacy now carry their 9th / After Fix columns.
- Regression found and fixed in the round: KI-279 (CM Elevate "Mairang"/"Nongstoin" block reading). pytest 2,230 passed;
  scripts 14/14. Code uncommitted.

**Earlier (2026-10-12, evening): CM Elevate Legacy sheet test + fixes (KI-273..278). Code changed, uncommitted. LIVE-VERIFIED.**
- USER DECISION: a bare "CM-ELEVATE" data question defaults to CM Elevate Legacy unless it uses applications-only words
  (applicants, pending, status, sector, sent back, level, on hold, verification …). None of the 529 CM Elevate sheet
  questions change dataset. Test sample questions updated accordingly.
- Workbook "CM Elevate Legacy" sheet G/H (9th: 25 Pass / 11 Fail) and I/J (After Fix 36/36) — written only when the
  workbook is not open in Excel (it was locked; FOCUS G..J likewise pending: `write_fl.py`, `write_cl.py`).
- Live on the final code: sheet 300/300 (13 schemes, 12 districts, 59 blocks, 55 constituencies, both FYs) and EVERY
  CM Elevate Legacy village 1,051/1,051. New tests `tests/test_cmelevate_legacy_sheet_fixes.py`.
- ALL SEVEN SHEETS DONE: General, MGNREGA, PMAY-G, CM Elevate, Focus +, FOCUS (Focus Legacy), CM Elevate Legacy.

**Earlier (2026-10-12): Focus Legacy ("FOCUS" tab) sheet test + fixes (KI-264..272). Code changed, uncommitted. LIVE-VERIFIED.**
- Workbook FOCUS sheet: G/H "9th Result/Remarks" (19 Pass / 9 Fail, judged on the bot), I/J "After Fix" (28/28 Pass).
  Live on the final code: sheet cases 231/231 (every district, block 56, constituency 55, all FYs + the 2023-24 gap)
  and EVERY Focus Legacy village 3,384/3,384 (`tests/sheet_runs/fl_run.py`, `fl_all.py`, `fl_drive.sh`, `write_fl.py`).
  New tests `tests/test_focuslegacy_sheet_fixes.py`.
- Finished sheets: General, MGNREGA, PMAY-G, CM Elevate, Focus +, FOCUS (Focus Legacy). NEXT: CM Elevate Legacy when
  the user names it.

**Earlier (2026-10-11): Focus + sheet test + fixes (KI-260..263). Code changed, uncommitted. LIVE-VERIFIED.**
- Workbook Focus + sheet: N/O "9th Result/Remarks" (27 Pass / 3 Fail), P/Q "After Fix" (30/30 Pass). Live on the final
  code: sheet cases 163/163 (every district 12, block 50, both FYs x 4 formats, batches, tranches, district pairs)
  and EVERY Focus Plus village 3,513/3,513 (`tests/sheet_runs/fp_run.py`, `fp_all.py`, `write_fp.py`; the VPN
  flapped, `fp_drive.sh`-style resume). New tests `tests/test_focusplus_sheet_fixes.py`.
- Finished sheets: General, MGNREGA, PMAY-G, CM Elevate, Focus +. NEXT: the user names FOCUS or CM Elevate Legacy.

**Earlier (2026-10-10, evening): CM Elevate sheet test + fixes (KI-253..259). Code changed, uncommitted. LIVE-VERIFIED.**
- Workbook CM Elevate sheet: N/O "9th Result/Remarks" (20 Pass / 10 Fail), P/Q "After Fix" (30/30 Pass). Live on the
  final code: sheet cases 529/529 (every block 66, district 12, programme 15) and EVERY CM Elevate village
  2,087/2,087 (`tests/sheet_runs/ce_run.py`, `ce_all.py`, `write_ce.py`). New tests `tests/test_cme_sheet_fixes.py`.
- The user's rule: test only the scheme they name; General, MGNREGA, PMAY-G and CM Elevate are finished.
- NEXT: the user names the next sheet (Focus +, FOCUS, CM Elevate Legacy).

**Earlier (2026-10-10, later): PMAY-G sheet test + fixes (KI-249..252). Code changed, uncommitted. LIVE-VERIFIED.**
- Workbook PMAY-G sheet: Q/R "9th Result/Remarks" (25 Pass / 3 Fail), S/T "After Fix" (28/28 Pass). Live: sheet cases
  678/678 (every block, district, pairs, all FYs, dates) and EVERY PMAY-G village 5,121/5,121 on the final code
  (`tests/sheet_runs/pm_run.py`, `pm_all.py`). New tests `tests/test_pmay_sheet_fixes.py`.
- The user's rule: test only the scheme they name; General and MGNREGA are finished and are not re-run live.
- NEXT: the user names the next sheet (CM Elevate, Focus +, FOCUS, CM Elevate Legacy).

**Earlier (2026-10-10): full-hierarchy pass for General + MGNREGA (KI-244..248). Code changed, uncommitted. LIVE-VERIFIED.**
- Every MGNREGA village (6,491) through the pipeline, one sheet question each (`tests/sheet_runs/mg_all.py`, resumable;
  stopped once by a VPN drop at 2,200 and resumed): 6,491/6,491 pass on the final code. Sheet cases re-run 783/783
  (all blocks, districts, constituencies, FYs); General re-run 24/24 (TC-023 182/182). Workbook After Fix remarks
  carry the hierarchy evidence. Process documented in `reference_documents/README.md`; scripts in `tests/sheet_runs/`.
- NEXT: the user names the next sheet (PMAY-G, CM Elevate, Focus +, FOCUS, CM Elevate Legacy) — same process,
  including EVERY village / block / district / constituency of that scheme.

**Earlier (2026-10-09, latest): MGNREGA sheet test + fixes (KI-236..243). Code changed, uncommitted. LIVE-VERIFIED.**
- Workbook MGNREGA sheet (DATA-001..030): Q "9th Result", R "9th Remarks" (13 Pass / 17 Fail), S "After Fix",
  T "After Fix Remarks" (30/30 Pass). Next: the user names the next sheet (PMAY-G, CM Elevate, Focus +, FOCUS, CM Elevate Legacy).
- Method (scratchpad `gentest/mg_run.py`, `mg_score.py`): 783 live conversations — 24 villages (2 per district, all 4 FYs,
  4 year formats), 8 same-name villages, all 55 blocks (blocks that are also villages asked bare and as "X block"),
  all 12 districts, all 56 constituencies, rankings for every FY; every expected figure from megh_db.
- Fixes in `app/pipeline.py`: `_MGNREGA_EXPENDITURE_WORD` (expenditure = MGNREGA), `_is_data_shaped` (guardrail scope
  overrule), `_unknown_word_runs` + spend-word + all-schemes checks in `_rephrase_violation`, `_place_words` no longer caches
  an empty set, `_USER_NAMED_CONSTITUENCY` (no AC drill-down when typed), HQ-town district alias -> block/AC test in the
  admin-level gate, `_MGNREGA_MIXED_AGG_RATIO_RE`, deterministic `_mgnrega_combined_facts_answer` and
  `_mgnrega_breakdown_query/_answer`, `_mgnrega_village_list_no_limit`, `_states_wrong_list_count`, fallbacks get all rows,
  `_data_path_kb_fallback` skips the KB for figure questions, a rephrased question is routed by `_typed_intent(raw)`.
- Tests: new `tests/test_mgnrega_sheet_fixes.py` (29); updated `test_mgnrega_usecase_fixes.py` (expenditure now pins
  MGNREGA), `test_query_rephraser.py`. pytest 2,034 passed, 0 failed; scripts 14/14.

**Earlier (2026-10-09, later): General sheet test + fixes (KI-228..235; KI-225 fixed). Code changed, uncommitted. LIVE-VERIFIED.**
- Workbook `reference_documents/Test Case Results - 30th Sep 26.xlsx`, General sheet: columns J "9th Result", K "9th Remarks"
  (15 Pass / 9 Fail), then L "After Fix", M "After Fix Remarks" (all 24 Pass after the fixes). Other sheets untouched.
  The user will name the next sheet (MGNREGA, PMAY-G, CM Elevate, Focus +, FOCUS, CM Elevate Legacy), one at a time, same method.
- Files: `app/pipeline.py` (`_scheme_listing_lines`, `_recent_compared_schemes`, `_is_entitlement_question`,
  `_overrules_scope_verdict`, `_WHICH_YEAR_CUE`, `_is_yearwise_reply`, `_WHERE_SCOPED_RE`, `_mgnrega_top_one_wording`,
  `_knowledge_not_covered_answer`), `app/rag.py` (`_hide_internal_sources`, `_LIST_QUESTION`, `_DOCS_RULE`), `app/guardrails.py`
  (two SAFE prompt lines), `app/edge.py` (money_advice names six), `data/reference/FOCUS_LEGACY_FAQ.md` (§8a; KB re-ingested,
  202 points), tests `test_general_sheet_fixes.py` (new, 42), `test_cm_elevate_legacy.py`, `test_scheme_recommendation.py`.
- Harness (scratchpad `0505c350-…/scratchpad/gentest/`): `harness.py`, `run_general.py` (262 conversations incl. 182
  hierarchy cases), `rerun_failed.py`, `trace.py "q1" "q2"` (TRACE_LOG=1 for node logs, REINGEST=1 to rebuild the KB).
- Tests: pytest 1,962 + 42 new passed, 0 failed; scripts 14/14.

**Earlier (2026-10-08, later): conversation layer (D-043, KI-222). Code changed, uncommitted. LIVE-VERIFIED.**
- The user asked for the conversational-feature spec WITHOUT changing existing code; they approved small additive edits
  to `routers/query.py`, `session_store.py`, `config.py` and docs only, and asked to keep the earlier topic-memory work.
  **`pipeline.py` was not edited in this session** (its one uncommitted hunk for topic memory predates it).
- Files: new `app/conversation_layer.py`, `tests/test_conversation_layer.py` (69); `app/routers/query.py` (`prepare_turn`
  call; `question` replaces `req.question` for answer_question / pause_question / build_turn; `is_cacheable` rejects
  `topic_memory.is_topic_command`); `app/session_store.py` (`topics`, `context_at` + snapshot keys); `app/config.py`
  (`CONVERSATION_LAYER_ENABLED`, `CONTEXT_IDLE_EXPIRY_SECONDS`); `app/topic_memory.py` docstring only.
- Live harness: scratchpad `8e45ba45-…/scratchpad/live_conv.py [S1 S7 …]` (env `%TEMP%\megh-sv`, run from repo root,
  `DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=6`); writes nothing.
- Live test cases: scratchpad `live_cases.py [FU TS RT …]` -> 36/38. KI-226 fixed in the layer. **KI-225 (High, open):** the
  guardrail MODEL check (commit `856044a`) refuses "give me for pmay" after MGNREGA data; ask the user before touching `guardrails.py`.
- NEXT: re-run `tests/live_context_validation.py` (not run this session; it does not go through `_answer`, so it does not
  exercise the layer); decide KI-223 (needs a `pipeline.py` change, ask the user); optionally move the KI-222 fix into the
  pipeline's follow-up branch; restart the server; commit when the user asks.

**Latest (2026-10-09): Qdrant stays `http://115.124.102.167:6335`.** A switch to `10.48.242.4:6335` was reverted the same
day (that port did not answer). No net config change.

**Earlier (2026-10-08): word-by-word reveal of every fresh answer. Frontend only, uncommitted.** See CURRENT_STATE.md.
- New `frontend/src/chat/reveal.js`; `Messages.jsx` (`TypingMessage` / `BotMessage` take `streamKey`, `animate`);
  `App.jsx` marks fresh answers `animate: true, streamKey: typingId`. The app was running on :8400 (pid 5768, venv
  `%TEMP%\megh-sv`, started from `meghalaya/`); the new build is served from disk, no restart needed.
- `app/config.py` has ~10 more uncommitted lines that are NOT from this work (someone else's); left as they are.

**Earlier (2026-10-07, latest): answer formatting (headings, lists, tables) + smart auto-scroll. Frontend only, uncommitted. OFFLINE-VERIFIED (browser 23/23).**
- New `frontend/src/chat/components/Markdown.jsx` (`parseBlocks`, `Markdown`, `plainText`); `Messages.jsx` uses it for answers
  and the draft; `App.jsx` `followRef` / `newBelow` / `onChatScroll` / ResizeObserver; `styles/chat.css` `.md-*`, `.new-below`.
- Open choice for the user: let knowledge answers carry real `#` headings (remove the strip in `app/rag.py` and the
  "No Markdown headings" prompt lines). Not done: backend + prompt change; needs a live check of answer quality.
- Browser suites (scratchpad `e2e/`, stub server `ui_server.py` on :8498): `ui_format_scroll_test.mjs` 23,
  `ui_stream_test.mjs` 17, `ui_conn_test.mjs` 20. Give the stub server ~2 s after stopping before restarting it.

**Earlier (2026-10-07, later): connection banner. Frontend only, uncommitted. OFFLINE-VERIFIED (browser 20/20).**
- `api.js`: `ConnectionError` for unreachable server / nginx 5xx without the app's JSON / the data-service 503 / a stream cut
  mid-answer; `checkHealth()`. `App.jsx`: `conn` state, `/health` poller, the waiting question re-asked once on recovery
  (only if it is still the latest message). Details: CURRENT_STATE.md. Test: scratchpad `e2e/ui_conn_test.mjs` (routes simulate
  each drop; needs `e2e/ui_server.py` on :8498).
- NEXT (with the VPN): drop the VPN mid-question in the real UI and confirm the banner and the automatic re-ask.

**Latest (2026-10-07): streamed answers, live progress steps, Stop, Regenerate / Retry (D-039). Code changed, uncommitted. OFFLINE-VERIFIED.**
- Files: new `app/turn_events.py`, `tests/test_query_stream.py`; `app/routers/query.py` (body of `query()` moved verbatim into
  `_answer()`, new `query_stream`, `QueryRequest.skip_cache`); `app/llm.py` (`stream_model`, `call_response_composer`);
  `app/pipeline_graph.py` (`_observed` emits `step`); `app/config.py` (`STREAM_COMPOSER_ENABLED`, `STREAM_PING_SECONDS`);
  `frontend/src/chat/api.js`, `App.jsx`, `components/Messages.jsx`, `styles/chat.css` (+ rebuilt `web/app/`);
  `deploy/nginx/nginx-megh-langgraph.conf`; `tests/test_context_hardening.py` (one source pin follows the body to `_answer`);
  docs CLAUDE.md §1, DECISIONS D-039, ARCHITECTURE, AI_PIPELINE §3.3, TESTING, DEPLOYMENT.
- Untouched: the uncommitted history-timestamp edits already in `App.jsx` / `format.js` (`stampTime`) from an earlier session.
- Tests: pytest 1,648 passed, 0 failed; scripts 14/14; new 14/14; browser 17/17 (scratchpad `8ef3c696-…/scratchpad/e2e`:
  `ui_server.py` = real app with the turn stubbed on :8498, `ui_stream_test.mjs`, `stream_e2e.py` = SSE timing check).
- ENVIRONMENT: the repo `.venv` was created on another machine (`C:\Users\dell\…\Python311`) and does not run on this box.
  Tests ran in `%TEMP%\megh-sv` (Python 3.12 + requirements.lock + pytest + pytest-asyncio). Install into a SHORT path:
  onnxruntime's file names exceed Windows' 260-char limit under the scratchpad.
- NEXT: with the VPN up, ask a few real questions in `/megh-chat` and watch the draft and steps; confirm the vLLM gateway
  accepts `stream: true` + `stream_options` (if not, the composer falls back to the plain call; look for
  `composer stream failed` in the log). Deploy: the new nginx location + `nginx -t` + reload. Commit when the user asks.

**Earlier (2026-10-06): six-scheme tester sheet ('Test Case Results - 30th Sep 26.xlsx', 206 cases) run live; all 16 Fail/Partial cases fixed. Code changed, uncommitted.**
- Before the fixes: 190/206 correct (82 pass, 108 after a clarification), 7 partial, 9 fail (TC-015's helpline number turned out to be fabricated). Report: `reference_documents/Test_Results_2026-10-06.xlsx`
  (+ `Test_Screenshots_2026-10-06/`). After: `reference_documents/Test_Results_2026-10-06_after_fixes.xlsx` (+ `..._after_fixes/`).
- Fixes KI-201..KI-217 (KNOWN_ISSUES; KI-214 = a FABRICATED helpline number in the first run, now blocked) and D-035 (CM Elevate answers constituency questions). Files: `app/pipeline.py`,
  `app/prompt_builder.py`, `app/schema_context.py`, `app/rag.py` (one retry on a dropped Qdrant connection),
  `data/reference/pmay_gramin_general_faq.md`, tests `tests/test_qa_2026_10_06_fixes.py` (new) and the two `test_ac_*focus_legacy.py`.
- **Deploy note:** the PMAY-G FAQ changed — re-ingest the shared `megh_scheme_kb` collection (admin `POST /api/rag/reingest`).
  It was verified on a temporary collection `megh_scheme_kb_qa20261006` on the same Qdrant server (safe to delete).
- Tests: pytest 28 files **1,496 passed, 0 failed** with the graph off AND on; scripts 14/14.
- Live after the fixes: **206/206** (91 pass, 115 pass after a clarification, 0 partial, 0 fail).

**Latest (2026-10-04, later): deploy identifiers renamed so this build cannot overwrite the existing deploy.**
- An earlier build is already deployed from a directory of the same name. Every identifier Docker/systemd/nginx keys on was
  changed here; the old `deploy/systemd/megh-nlpservice.service` and `deploy/nginx/nginx-nlpservice.conf` were REVERTED to
  their committed state so the running deploy keeps its port 8300 and `/opt/meghalaya`.
- New names: compose project `megh-langgraph` (`name:` key — this also prefixes the volumes), image `megh-langgraph:latest`,
  containers `megh-langgraph-nlp` / `-qdrant` / `-redis`, host ports 8411 (app), 6343 (Qdrant), 6389 (Redis);
  new unit `deploy/systemd/megh-langgraph.service` (port **8410**, `WorkingDirectory=/opt/meghalaya-langgraph`);
  new vhost `deploy/nginx/nginx-megh-langgraph.conf` (upstream 8410, rate-limit zones renamed `*_lg` — nginx refuses two
  enabled vhosts that declare the same zone name).
- **Dockerfile bug found and fixed:** it still had `EXPOSE 8300`, a 8300 healthcheck and `--port 8300` in CMD while compose
  mapped to 8400 — the container would have published nothing reachable. Now 8400 throughout; `WORKDIR` is
  `/opt/meghalaya-langgraph` and the compose log mount follows it.
- Deploy to `/opt/meghalaya-langgraph`, never `/opt/meghalaya`. Full table + commands: DEPLOYMENT.md "Side-by-side".
- `docker compose config` validates. Tests: 36 passed (`test_pipeline_graph`, `test_ac_full_results`, `test_history_charts`).
  Docker Desktop is not running on this dev box, so nothing was built or started here.

**Latest (2026-10-04): chat route renamed and service port changed. Config + routing only; no pipeline change.**
- `/ai-query` → **`/megh-chat`** (`app/main.py`: new `megh_chat()` serves `web/ai_query.html`; `/ai-query` now returns a 301 to it, so bookmarks keep working). The file name `ai_query.html` is unchanged.
- Port **8300 → 8400**: `app/config.py` default, `.env`, `.env.example`, `deploy/systemd/megh-nlpservice.service`, all 9 nginx `proxy_pass` lines, `docker-compose.yml` (host 8401→container 8400), README, DEPLOYMENT, ARCHITECTURE, TESTING, CLAUDE.md §9.
- In-page links updated: `web/admin.html` (2), `web/Meghalaya_UnifiedPortal_UI.html` (3). `web/ai_query.html` `_prefixCandidates()` regex now also matches `megh-chat` — without this the UI would derive the wrong API prefix when served from a sub-path.
- Verified offline (VPN down) with `starlette.testclient`: `/megh-chat` 200 (serves the chat page), `/ai-query` 301 → `/megh-chat`, `/admin-ui` 200, `/` 200, unknown path 404, `settings.PORT == 8400`. Tests: 90 passed (`test_ac_full_results`, `test_asr_transcribe`, `test_history_charts`, `test_pipeline_graph`).
- **Deploy note:** the VMs need the new `.env` PORT, the new nginx conf and the new systemd unit, then `systemctl daemon-reload` + `nginx -t` + reload. Not done from here.

**Latest (2026-10-03, afternoon): Qdrant moved to a new server. Config only, no code change. KB INGESTED and verified.**
- `.env` `QDRANT_URL` changed `http://10.48.242.4:6333` → `http://115.124.102.167:6335` (collection names unchanged: `megh_scheme_kb`, `megh_conversation_memory`). `.env.example`, `deploy/DEPLOYMENT.md`, `CLAUDE.md` §9 updated.
- New server checked read-only: Qdrant 1.18.3 (client 1.19.0, compatible); reachable without the VPN; **no API key** (KI-200); holds six `Metadata_*` collections (1024-dim schema metadata, not ours, not used: our KB is 384-dim bge-small) — never touch them.
- **Done (2026-10-03):** `ingest_kb` built `megh_scheme_kb` on the new server: 201 points from 12 docs, 384-dim, five scheme tags (CM Elevate Legacy maps to CM Elevate by design). `megh_conversation_memory` created (384-dim, empty). Retrieval checked per scheme (top cosine 0.77–0.85). The `Metadata_*` collections are unchanged (e.g. Metadata_MGNREGA 360, Metadata_CMElevate 917 points).
- **Still open:** the user sets `QDRANT_API_KEY` (KI-200); the two VMs' `.env` need the same `QDRANT_URL`; a full KNOWLEDGE answer end to end needs the VPN (the composer model is on 10.48.242.4).
- **The old Qdrant (10.48.242.4:6333) is retired for this app:** no code, config default or doc points to it. `app/config.py` default `QDRANT_URL` is now `http://115.124.102.167:6335`.

**Latest (2026-10-03, early morning): all six schemes × every place, all failures fixed. Code changed, uncommitted. LIVE-VERIFIED.**
- Result: 30,280 / 30,280 live bulk questions pass (see SCHEMES.md "All-places QA"); reports in `docs/*_LangGraph_Test_Results*.xlsx`.
- Code: `app/pipeline.py` only — `_VILLAGE_NARROW_SCHEMES` (5 schemes), `_focus_legacy_village_names`, `_cm_legacy_village_names`,
  `_village_filter_missing`, `_pin_missing_village_code` → `_village_name_cond_to_code` / `_drop_geo_beside_pinned_village` /
  `_PINNED_GEO_COND`, `_GEO_BESIDE_VILLAGE_RE` (UPPER/LOWER/TRIM), `_cm_unasked_programme_beside_village` (non-programme literal),
  `_focusplus_lgd_only_block`, `_FPL_BLOCKS`, `_cm_elevate_applicants_distinct`, `_NUMBER_TENS`, `_cml_fix_place_spelling`,
  `_YEAR_AFTER_CHIP_TAIL_MATCH`, `_mgnrega_village_not_out_of_area` (BURMA; both Legacy schemes for MANIPUR), `_pmay_two_villages`.
- Tests changed with reasons (CML is now a village scheme): `test_focusplus_usecase_fixes.py`, `test_mgnrega_usecase_fixes.py`,
  `test_focus_legacy_usecase_fixes.py`; new tests in those and `test_cm_elevate_legacy.py`, `test_cmelevate_usecase_fixes.py`, `test_pmay_usecase_fixes.py`.
- Tests: pytest **1,453 passed, 0 failed** (27 files) with the graph off AND on; scripts **14/14**; live context suite **43/43 on both paths** (follow-up 29/29).
- Harness: scratchpad `7be462aa-…/scratchpad/bulk` (`bulk.py gen|run|judge [--only-failed f --out f]`, `pmay_sets.py`, `cme_sets.py`,
  `make_reports.py <docs dir>` with system Python + openpyxl). Background jobs die at 2 h: run villages in batches (resumable).
- Next: canary (G5); decide KI-184/185; broaden QA beyond one shape per place (KI-199); commit when the user asks.

**Latest (2026-10-02, evening): live verification + fixes. Code changed, uncommitted. LIVE-VERIFIED.**
- Live: context suite 43/43 both paths; G4 36/36 identical; OFF-009 re-test 49/49 both paths; 21/21 nodes ran live.
- Fixed: KI-187 (`_verifier_unlisted_geo_is_false`), KI-182 (`_cme_asked_programmes`, `_cme_all_zero_answer`, `_cme_multi_scheme_total`), KI-183 (`_repaired_sql_denial`, `RepairedSQLDenied`, `execute_with_repair(scope=)`, graph `node_execute_attempt`; D-033); stale tests in `test_focus_legacy_usecase_fixes.py` / `test_mgnrega_usecase_fixes.py`.
- Tests: pytest 1,419 passed, 0 failed, flag off and on; scripts 14/14.
- Harnesses (session scratchpad `7be462aa-…/scratchpad`): `live_q.py` (ad-hoc live questions), `g4.py` (six-scheme old-vs-graph), `off009.py [graph]` (OFF-009 vs DB), `g4cov.py` (live node coverage), `live_q_orig.py` (runs the pre-refactor `pipeline_orig.py` for A/B). Set `DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=6`.
- GOTCHA: writing Python through a bash heredoc turned `\\b` into a literal backspace (0x08) in regexes — silently matching nothing. Use the Edit tool or a script file; check with `chr(8) in source`.
- Next: canary (G5); decide KI-184/185; optionally re-run the full OFF-009 1,260 set; commit when the user asks.

**Earlier (2026-10-02): LangGraph orchestrator (D-032). Code changed, uncommitted. OFFLINE-VERIFIED ONLY (VPN down all session).**
- Read first: `docs/LANGGRAPH_ARCHITECTURE.md`, `docs/LANGGRAPH_PAUSE_RESUME.md`, `docs/LANGGRAPH_MIGRATION.md` (rollout gates G1–G8).
- Files:
  - `app/pipeline.py`: the verbatim stage split (`_turn_*_stage`, `_data_*_stage`, `_scheme_sql_rewrites`,
    `_execute_one_attempt`, `_repair_sql`, `_data_path_error_result`, `_update_context`, `MAX_SQL_REPAIRS`,
    `_pipeline_graph_selected` in `answer_question`);
  - new `app/pipeline_graph.py`;
  - `app/config.py` (8 `PIPELINE_GRAPH_*` / `LANGGRAPH_*` flags);
  - `app/main.py` (pause sweep + checkpointer close + `/health` component, only when the graph is in use);
  - `requirements.txt`, `requirements.lock`;
  - new `tests/test_pipeline_graph.py` (27);
  - `tests/test_mgnrega_usecase_fixes.py` (one source pin moved to `_data_clarification_stage`).
- The split was done with a splice script (scratchpad `7be462aa-…/scratchpad/splice.py`, from `pipeline_orig.py`),
  so every moved body is byte-for-byte the original. Live-in variables per boundary were checked with `ast` (`live.py`, `undef.py`).
- Tests:
  - baseline 1,371 passed / 2 failed; after the split, the same;
  - flag off 1,398 / 2; flag on 1,397 / 3 (one test fixed since). NOTE: no existing test calls
    `answer_question`, so only `test_pipeline_graph.py` exercises the graph;
  - `test_pipeline_graph.py` 27/27 in both modes; scripts 14/14.
  The 2 failures are the pre-existing verifier tests.
- NEXT (in order):
  1. With the VPN up: `PIPELINE_GRAPH_ENABLED=true .venv/Scripts/python.exe tests/live_context_validation.py` (expect 43/43),
     plus a per-scheme use-case sample flag on vs off (G3, G4).
  2. Decide KI-183 (re-authorize repaired SQL).
  3. Canary 10% on one VM (G5).
  4. Commit when the user asks.
- Gotchas:
  - LangGraph reads a node's *unwrapped* signature: never set `__wrapped__` on `_observed` nodes (it stops
    passing `runtime`). The wrapped function is exposed as `.stage_fn`.
  - `from tests.test_pipeline_graph import *` skips the `_loaded` fixture (underscore), and the resolver
    catalogue is then empty: import it explicitly.

**Latest (2026-10-01): CM Elevate OFF-009 all pairs — TEST ONLY, no code changed.** 1,260 questions (12 districts x 105 programme pairs): PASS 552, PASS-with-remark 141 (both 0 → 'no matching records'), FAIL 567 (one programme 0 → omitted, KI-182). Bot SQL data correct 1,260/1,260; raw = DB. Report docs/CM_Elevate_OFF009_AllPairs_2026-09-30.xlsx. On 2026-09-30 the gateway was down (timeouts) and its TLS cert failed verification; both fine on 2026-10-01.

**Latest (2026-09-29, morning): typed replies resume every chip pause (KI-181). Code changed, uncommitted. LIVE-VERIFIED.**
- Files: `app/routers/query.py` (`remember_pause` generic branch, uses `SCOPE_MERGE_RULES`), `app/pipeline.py` (`SCOPE_MERGE_RULES`,
  `_resume_option_pause`, `_option_tokens`, `_paused_thread_antecedent`, step 0a'' in `_run_pipeline`, `_paused_state` thread override,
  measure-gap pause remembered as its first offer), `tests/test_context_relevance_and_contract.py` (+33, now 177).
- Tests: pytest 1,371 passed, 2 failed (same parallel-session verifier tests as below); scripts 14/14; live context 43/43.
- Open: an unmatched reply with its own measure + place but no year keeps the paused scheme, not the paused year (FY pause follows).
- Next: restart :8300; commit when the user asks.

**Latest (2026-09-29, early morning): "give me for pmay" — conversational scheme swap (KI-180). Code changed, uncommitted. LIVE-VERIFIED.**
- Files: `app/pipeline.py` (`_SCHEME_SWAP_FOLLOWUP` request-verb opening, `_SUBSTITUTION_CUE`, new `_SCHEME_OWN_MEASURES`,
  `_SCHEME_HEADLINE_OFFERS`, `_swap_scope_phrase`, `_swap_measure_gap`, one call after the follow-up rewrite in `_run_pipeline`),
  `tests/test_context_relevance_and_contract.py` (+26, now 144).
- Tests: pytest 1,338 passed, 2 failed — both pin `_verifier_village_code_complaint_is_false` and were broken by a PARALLEL
  CM Elevate Legacy session editing `pipeline.py` at the same time (it added `["CM Elevate Legacy"]` to that gate); not KI-180.
  Scripts 14/14; live context 43/43; live replay via scratchpad `119975e8-…/scratchpad/live_convo.py`.
- Open: a bare "for focus" -> which-Focus chip -> Focus Plus with an MGNREGA-only measure still reaches the generator (not gated).
  (The pause is now remembered — KI-181, entry above.)
- Next: restart :8300; commit when the user asks.

**Latest (2026-09-29, late night): CM Elevate Legacy KI-166..181 fixed — use cases 36/36, all levels 2,614/2,614. Code changed, uncommitted. LIVE-VERIFIED.**
- Files: `app/pipeline.py` (CM Elevate Legacy SQL guards `_cm_legacy_sanctioned_count`, `_cm_legacy_unrequested_limit`,
  `_cm_legacy_unselected_group_by`; `_cm_legacy_answer_guarantees` and its `_cml_*` helpers; chip pin / twin ranking /
  urban blocks / verifier filter / Garo gate extended to CM Elevate Legacy; KI-179 level word in the explicit-village
  step, all schemes), `tests/test_cm_elevate_legacy.py` (+48 tests, 131).
- Reports: `docs/CM_Elevate_Legacy_UseCase_Test_Report_2026-09-29_v2_after_fixes.xlsx`,
  `docs/CM_Elevate_Legacy_AllBlocks_AllVillages_Test_Report_2026-09-29.xlsx` (+ evidence folders).
- Harness: scratchpad `d746a809-…/scratchpad/bulk` — `gen_bulk.py` (truth from DB AND raw, system python),
  `bulk_run.py` (.venv; set BOTH `DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=6` — a max below the default min 10 kills the
  pool), `bulk_judge.py`, `build_bulk.py`, `issues.json`; `trace_sql.py` logs failing SQL.
- Tests: pytest 1,309 (26 files), scripts 14/14, live context 41/43 + scenario G 5/5 twice (transient save-failed).
- Next: RESTART :8300; commit when the user asks; KI-003 (failing SQL not logged) made the KI-181 hunt slow.

**Earlier (2026-09-29, late night): CM Elevate Legacy use-case re-test — 33/36. No code changed.**
- The user said "Focus legacy" but named the CM Elevate Legacy files, so CM Elevate Legacy was tested (36 cases, 2 full runs + 3 repeats).
- DB = raw row for row (2,823). Failures, all AI layer and reproducible: KI-166 (TC-14 sanctioned = COUNT(*) → 2,823 vs 2,820, 5/5),
  KI-167 (TC-34 composer "20 villages with 1 record" vs 24, 5/5), KI-168 (TC-13 LIMIT 10 → "down to 33", 4/5).
- Report `docs/CM_Elevate_Legacy_UseCase_Test_Report_2026-09-29.xlsx` (+ `_Evidence_2026-09-29/`).
- Harness: scratchpad `d746a809-…/scratchpad` — `run_bot.py OUT [TC…]` (.venv), `ground_truth.py` and `recon.py` (system python; the raw
  file is aggregated only — reading its rows is blocked as PII), `judge.py`, `verdicts.py`, `fails.py`, `build.py`.
- Next: fix KI-166..168 with deterministic guards + regression tests (user has not asked yet), then re-run the 36.

**Latest (2026-09-29, night): Focus Legacy all blocks / villages / ACs / PGs — 32,560/32,560. Code changed, uncommitted. LIVE-VERIFIED.**
- Files: `app/pipeline.py`, `app/entity_resolver.py` (`constituency_contents(ac, scheme)`), `app/edge.py`
  (`_mask_group_name`), `tests/test_focus_legacy_usecase_fixes.py` (122), 3 older tests updated with reasons
  (`test_admin_level_collision.py` fake signature, `test_mgnrega_usecase_fixes.py` verifier scope,
  `test_ac_flow_focus_legacy.py` docstring).
- Tests: pytest 1,265; scripts 14/14; live context 43/43; use cases 28/28 x3 (final code).
- Reports: `docs/Focus_Legacy_AllBlocks_Villages_ACs_PGs_Test_Report_2026-09-29.xlsx`,
  `docs/Focus_Legacy_UseCase_Test_Report_2026-09-29_v2_after_fixes.xlsx` (+ evidence folders).
- Harness: scratchpad `2ca0226e-…/scratchpad/bulk` — `gen_bulk.py` (truth from DB AND raw), `bulk_run.py`
  (concurrent, resumable, clicks chips), `bulk_judge.py`; run shards in parallel with `DB_POOL_MAX_SIZE=5`.
- Next: CM Elevate Legacy duplicate-village chips (KI-156) and PMAY-G DATE_TRUNC (KI-164) — both NOT VERIFIED;
  KI-151 under load; RESTART the :8300 server to pick the changes up; commit when the user asks.

**Latest (2026-09-29, evening): Focus Legacy use-case re-test — 28/28 on 3 of 3 runs. No code changed.**
- Checked against the live DB (`curated.v_focus_legacy`, never the privacy table) and the raw file;
  DB = raw row for row. Report `docs/Focus_Legacy_UseCase_Test_Report_2026-09-29.xlsx` (+ `_Evidence_2026-09-29/`).
- New cosmetic issues KI-145..147 (open). Harness: scratchpad `2ca0226e-…/scratchpad`
  (`bot_run.py`, `judge.py`, `expected.py`, `recon.py`, `verdicts.py`, `build.py`; Excel COM for recalc).

**Latest (2026-09-29, later): the reported "what is focus" conversation — KI-136 to KI-144. Code changed, uncommitted. LIVE-VERIFIED (VPN up).**
- Fixes: `_names_bare_focus_scheme` (no model rewrite for a bare scheme "Focus"); `_drop_inherited_time` /
  `_drop_inherited_place` (KNOWLEDGE path); `rewrite_violation` keeps the follow-up's own metric;
  `_followup_thread_state` + `_data_thread_antecedent` (which thread a follow-up continues — never a
  state wipe, see D-030 amendment); `_measure_after_knowledge` + `_typed_intent`;
  `turn_context["standalone_question"]` read by `routers.query.pause_question`;
  `ConversationState.last_dimension` + "all of them" CLEAR + `_all_years_rewrite`; Focus Plus
  amount answer guarantee; `build_followup_context(state=...)`.
- Tests: pytest 1,185; scripts 14/14; live context suite 43/43 (final code); live battery S1–S8 correct.
  Harness: scratchpad `5a4188f1-…/scratchpad/live_convo.py` (real lifespan, router pause helpers;
  "@chip:<label>" clicks a chip), `battery.sh`, `battery2.sh`.
- Open: KI-040 (MGNREGA "beneficiaries" = SUM(persons_employed) across years, person-years — needs an
  SME definition); after 2+ edge turns a bare "how many beneficiaries?" asks "which scheme?" (safe, by
  choice); bulk false-positive rate of `_resolved_scope_missing` not measured.
- Next: commit when the user asks; a Focus Plus / MGNREGA block-village bulk sample to measure the guard.

**Earlier (2026-09-29): context relevance + semantic contract (D-030). Offline at the time; live-verified by the later session.**
- The VPN was down all session (`10.48.242.4` answered neither 5432 nor 443), so **nothing was
  live-verified**. FIRST NEXT STEP when it is up: `tests/live_context_validation.py` (43 checks),
  then the reported conversation live (see KNOWN_ISSUES KI-130 to KI-135), then a Focus Plus and a
  MGNREGA block/village regression sample to measure `_resolved_scope_missing` false positives.
- Changed: `app/context_policy.py` (`continuation_signals`, `is_bare_reference`),
  `app/pipeline.py` (step 0-c gate, `reference-ambiguous`, step 1g `_village_name_search_answer`,
  `_acronym_near_miss_clarification`, Focus Plus `_focusplus_stated_amount*`,
  `_resolved_scope_missing` guard, `inject_year_scope` call, decision logs), `app/edge.py`
  (`personal_request`, `has_domain_vocabulary`), `app/entity_resolver.py`
  (`acronym_near_misses`), `app/premise_check.py` (`stated_amount_filters`, number words),
  `app/context_manager.py` (`inject_year_scope`, KI-032 clears, `year_all`),
  `app/session_store.py` (`year_all`), `app/context_budget.py` (`log_decision`); new
  `tests/test_context_relevance_and_contract.py` (96).
- Tests: pytest 1,163 (26 files); scripts 14/14. Offline harness:
  scratchpad `5a4188f1-…/scratchpad/repro_routing.py` (real `_run_pipeline`, model/RAG/DATA stubbed).
- Not fixed, still open: KI-035, KI-040 (MGNREGA "beneficiaries" is undefined, which is what
  "same for mgnrega" will answer with), KI-036/037 (Songsak-style block/village level memory; tests
  5–7 of the request rely on the existing level gates and were not live-checked).

**Latest (2026-09-29, later): PMAY-G plain year = calendar year.** "during 2017" now answers calendar 2017 (EKH 1,419 houses; table + SQL agree) with FY 2017-18 (1,548) as a one-line note; explicit FY unchanged. pytest 1,266; use cases 71/71; follow-ups 18/18. Restart :8300.

**Latest (2026-09-29): KI-129 — PMAY-G result table / Sources.** The table under an answer now holds only the place and the asked figures (`_pmay_display_rows`); "Sources: TRUE" gone (SQL + UI). Live: follow-ups 18/18, use cases 71/71; pytest 1,067. Restart :8300.

**Latest (2026-09-28, night): PMAY-G extra information removed (KI-128).** Summaries list only the use-case figures; single figures carry no side details; rewritten follow-ups answer only the figure the user typed (`_PMAY_TYPED_TURN`). Live: 2,129-question sample 2,129/2,129, use cases 71/71, follow-ups 18/18; pytest 1,065. Restart :8300.

**Latest (2026-09-28, late): PMAY-G tester sheet (Test Case Results - 21st Sep 26 - PMAY-G) re-tested.** Every input the tester named is now correct vs DB/raw (GABIL SONGGITCHAM partial 83; no KYNDONGTUBER mix-up; one row per status; LASKEIN 5,232). Live: 192/192 (21 Sep inputs, all districts x ben/summary/performance/each FY, 63 dates) + use cases 71/71. Fixed KI-125 (bare year "sanctioned in 2023" was dropped → now FY 2023-24 + calendar-2023 line). Open decisions: KI-126 (two taps for a shared village name) and KI-127 (placeholder rows in beneficiary counts: tester's 5,251 vs 5,232).

**Latest (2026-09-28, later): CM Elevate status = current_file_status (KI-123, user decision).** Prompt rule 13 + vocabulary, 2 few-shots, guard `_cm_elevate_status_is_file_status`. Pending / verification / on hold unchanged. Tester questions 36/36; pytest 1,062.

**Previous (2026-09-28, late): CM Elevate tester sheet (Test Case Results - 21st Sep 26) re-tested.** 36 tester-phrased questions all correct vs DB/raw after two fixes (KI-121 verifier grain false positive, KI-122 sector wording); pytest 1,055. Open decisions: KI-123 (testers want current_file_status for status/pending) and KI-124 (applicants = distinct request_id vs raw row count).

**Latest (2026-09-28, evening): CM Elevate — remaining issues + all districts / blocks / villages. Code changed, uncommitted.**
- Final pass **7,364 / 7,364** (7,364 questions = 12 districts, 66 blocks, 2,087 villages x 3 phrasings x the use-case types); round 1 4,132/4,208. Report `docs/CM_Elevate_AllBlocks_AllVillages_Test_Report_2026-09-28.xlsx`.
- KI-074 DECIDED by the product owner: pending = verification On Hold only (interim line removed). KI-076 fixed (`_APPLICANT_PLACE_CUE`).
- KI-106..120: CM Elevate in `_village_scheme` / `_VILLAGE_NARROW_SCHEMES` (village catalogue `_cm_elevate_village_names`); urban bodies mapped to stored `lgd_block` (`_cm_elevate_blocks_to_data`, `_cm_elevate_block_from_mention`, urban step at the top of `resolve_entities`); SQL guards `_cm_elevate_fix_literals`, `_cm_elevate_sector_all_programmes`, `_cm_elevate_unasked_programme_filter`; `_focusplus_pin_village_where` literal/FILTER-aware (`_top_level_where_span`); chip pin keeps the scheme's twin; verifier filters; number words → digits before the checks.
- Three older tests that pinned CM Elevate OUTSIDE the village gate were updated (reason in each).
- Tests: pytest 1,053; context suite 43/43. Harness: scratchpad `63ff2b45-…/scratchpad/bulk` (gen_bulk, bulk_run, bulk_judge, make_extra, build_bulk). RESTART the :8300 server.

**Latest (2026-09-28, late night): PMAY-G full scenario test — 17,331/17,331. Code changed, uncommitted.**
- 34 first-pass failures → KI-099 to KI-104 fixed; the final pass found KI-105 (model-path crore rounding), fixed and the
  571 model-reachable questions re-run 571/571. Follow-ups 18/18, use cases 71/71, context 43/43, pytest 1,005.
- Report `docs/PMAY_G_Full_Scenario_Test_Report_2026-09-28.xlsx` (+ `_Evidence_2026-09-28/`). RESTART the :8300 server.

**Previous (2026-09-28, night): KI-098 — PMAY-G village named beside its block. Code changed, uncommitted.**
- User report: "…in NONGSOHRAM across all financial years, RI MULIANG block, WEST KHASI HILLS" answered for
  the whole block. Fix: `_pmay_village_beside_block` at the end of `resolve_entities` (PMAY-G only; reads
  an explicit ", X block, DISTRICT" tail from the text; one mention written "X block" stays the block).
- Live: 5,120/5,120 villages with the tail, 224/224 blocks, 500/500 bare villages, 71/71 use cases;
  pytest 998. The running server on :8300 must be RESTARTED to pick the change up.

**Previous (2026-09-28, evening): PMAY-G fixes + all blocks / all villages. Code changed, uncommitted.**
- **Result:** use cases **28/28** (71/71 questions on 2 of 2 fresh live runs, identical answers; round 1 was 17/28); all blocks **224/224**; all villages **5,120/5,120** on the final code (round 1 4,393/5,120 → KI-096 fixed).
- **Design (D-029):** `_pmay_facts_query` / `_pmay_facts_answer` answer the fixed PMAY-G shapes
  deterministically; the model path keeps the rest with `_pmay_sql_issue`,
  `_pmay_comparison_limit`, `_pmay_rupee_format`. PMAY-G is now in `_village_scheme`
  (`_pmay_village_names`). Resolver: "sanctioned" stage phrases match in order only.
- **Tests:** `tests/test_pmay_usecase_fixes.py` (53); pytest 993; scripts 14/14; live context 43/43;
  Focus Plus regression 60/60 + 300/300; MGNREGA 60/60 + 300/300. Four older tests that pinned
  PMAY-G outside the village gate / out-of-area check were updated, with the reason in each.
- **Reports:** `docs/PMAY_G_UseCase_Test_Report_2026-09-28_v2_after_fixes.xlsx` (+ `_Evidence_…_after_fixes/`),
  `docs/PMAY_G_AllBlocks_AllVillages_Test_Report_2026-09-28.xlsx` (+ `_Evidence_2026-09-28/`).
- **Next step:** commit when the user asks. Keep the FY pause (product decision). The harness is in
  scratchpad `9d9b9d7b-…` (gen_bulk, bulk_run, bulk_judge, build_bulk, run_bot, judge, verdicts_after,
  build_xlsx ROUND=2).

**Previous session (2026-09-28, later): PMAY-G use-case QA. No code changed.**
- **Result:** **17 / 28 test cases** (49 / 71 questions; two live runs; a question passes only if
  both pass). The user said "Focus legacy" but named PMAY-G files (`PMAY-G.csv` = use cases,
  `PMAY_FullyMapped_with_dates.csv` = raw), so PMAY-G was tested.
- **DB = raw** row for row (171,107 rows).
- **Report:** `docs/PMAY_G_UseCase_Test_Report_2026-09-28.xlsx`, evidence
  `docs/PMAY_G_UseCase_Evidence_2026-09-28/` (73 PNGs; 016a and 022b also have `_runB`).
- **Issues found:** KI-089 to KI-095 (all fixed later the same day — see the session above). The biggest was KI-089
  (per-year GROUP BY for "financial summary" and comparisons), then KI-091 (false "House
  Sanctioned stage").
- **Not a failure:** the FY pause on no-year PMAY-G questions is a 2026-09-09 product decision.
- **Next step:** fix KI-089 to KI-095 (PMAY-G only, prompt + few-shot + deterministic guard), add
  `tests/test_pmay_usecase_fixes.py`, re-run the 71 questions.
- **Harness:** session scratchpad `9d9b9d7b-…/scratchpad` holds `cases.py`, `frames.py`,
  `recon.py`, `expected.py`, `run_bot.py`, `judge.py` (money within stated rounding and 1%),
  `verdicts.py`, `render.py` and `build_xlsx.py`. The runner and renderer use the `.venv` python;
  pandas and openpyxl steps use the system python. Raw names are dropped at load.

**Previous session (2026-09-28): KI-025 fixed; data package for KI-065 / KI-084. Code changed, uncommitted.**
- **KI-025:**
  - `db.DatabaseUnavailableError` and `db.is_connection_error()` (connection-class errors; not
    TimeoutError);
  - `execute_with_repair` raises it before any repair;
  - `_run_pipeline` re-raises it, with no KB fallback;
  - the router returns 503.
  - Tests: 3 in `tests/test_focusplus_usecase_fixes.py`. Live-verified with a real unreachable
    DB port.
- **KI-065 / KI-084:** data-side, so the chatbot must not change megh_db. The ingestion team has
  the row-level package `docs/Focus_Plus_Data_Corrections_for_Ingestion_2026-09-28.xlsx`
  (README, rows, per-village summary, read-only verification SQL). Next: their decision. No
  chatbot change is needed after they fix it.
- **Tests:** pytest 939; scripts 14/14; live context 43/43.

**Previous session (2026-09-27 night): Focus Plus all blocks and all villages. Code changed, uncommitted.**
- **Result on the final code:** blocks **204/204**; villages **7,026/7,026**.
  - Confirmation pass: 204/204 and 1,000/1,000 random villages.
  - MGNREGA regression: 448/448 and 300/300.
  - Report: `docs/Focus_Plus_AllBlocks_AllVillages_Test_Report_2026-09-27.xlsx`.
- **Fixes (all in `app/pipeline.py`; KNOWN_ISSUES KI-079 to KI-088; D-028):**
  - The MGNREGA village guards (KI-049 to KI-059) are gated on `_village_scheme(schemes)`, which
    returns MGNREGA exactly as before, or Focus Plus when it is the only scheme.
  - Focus Plus adds `_focusplus_village_names`, `_focusplus_narrow_village`,
    `_focusplus_pin_village_where` and `_focusplus_alias_district_collision`.
  - The twin-village chip tag is `_village_code_tag`.
  - Also: the "Nan" block, BURMA, and the one-figure misquote rule in `compose_response`.
- **Tests:** `tests/test_focusplus_usecase_fixes.py` (53). Two MGNREGA tests that pinned
  MGNREGA-only gates were updated, with the reason in the test.
- **Another session edited the same files in parallel** (CM Elevate, calendar dates: KI-068 to
  KI-078, D-027). Numbering was coordinated by reading the docs first.
- **Next step:** commit when the user asks. Remaining data-side items for the ingestion team are
  KI-065 and KI-084. The bulk harness (`gen_fp_bulk.py`, `fp_bulk_run.py`, `fp_bulk_judge.py`,
  `build_fp_bulk.py`) is in the session scratchpad; the method is on the report's Summary sheet.

**Earlier (2026-09-27): calendar date read as a financial year (KI-078). Code changed, uncommitted.**
- **The user's screenshot:** "How many PMAY houses were sanctioned on 2017-11-28?" gave 504
  (correct, checked in megh_db), but the answer said "not the 11 or 28 figures assumed" and
  "applies to FY 2017-18".
- **Fixed (only this; nothing else changed):**
  - `app/pipeline.py`: `_EXPLICIT_FY_RANGE_MATCH` no longer matches the head of a date;
    `_needs_scope_clarification` accepts a full date as the time pin (`_CALENDAR_DATE_MATCH`).
  - `app/premise_check.py`: `extract_premises` blanks dates (`_DATE_RE`).
- **Tests:** new `tests/test_calendar_date_filter.py` (18); pytest 915 (24 files); scripts 14/14;
  live context suite **43/43** (follow-up 29/29, SQL 20/20); live probes 4/4.
- **Next:** commit when the user asks.

**Earlier session (2026-09-27): MGNREGA women-share fix (KI-077). Code changed, uncommitted.**
- **The user's screenshot:** "What percentage of employment persons were women in ekh?" came back
  as 0.00%, with no year named.
- **Fixed in `app/pipeline.py`, MGNREGA only:**
  - the year gate now covers percentage, share and women questions, and women chips offer only
    the years that carry women data;
  - a deterministic women query uses the recorded years and says which;
  - FY 2025-26 is answered "not recorded";
  - generator SQL over all years is restricted to the recorded years.
- **Details:** KNOWN_ISSUES KI-077 and AI_PIPELINE.
- **Tests:** 897 pytest, 14/14 scripts, live context 43/43, 8/8 live women checks.
- **Next:** commit when the user asks.

**Earlier session (2026-09-27, later): CM Elevate use-case QA, then fixes. Code changed, uncommitted.**
- **Result:**
  - Round 1: 23 / 30 test cases (47 / 55 questions).
  - After fixes: **30 / 30** (55 / 55) on 2 of 2 fresh live runs, with identical answers.
  - Every figure was checked against megh_db and the raw workbook, which are identical (8,627
    rows).
  - The user said "Focus legacy" but named CM Elevate files, so CM Elevate was tested.
- **Reports:**
  - round 1: `docs/CM_Elevate_UseCase_Test_Report_2026-09-27.xlsx`;
  - after fixes: `docs/CM_Elevate_UseCase_Test_Report_2026-09-27_v2_after_fixes.xlsx`, with
    evidence in `..._Evidence_2026-09-27_after_fixes/`. It keeps the round-1 status as a column.
- **Files:**
  - `app/pipeline.py`:
    - `_UNRESOLVED_PLACEHOLDER_SCHEMES` now includes CM Elevate;
    - `_CMELEVATE_ONLY_TERMS` now includes PRIME SEED;
    - five `_cm_elevate_*` SQL rewrites run in `execute_with_repair`;
    - the `_cme_*` guarantees run through `_cm_elevate_answer_guarantees` after the composer;
    - new verifier filter `_verifier_scheme_specific_complaint_is_false`.
  - `app/schema_context.py`: the CM Elevate vocabulary now covers pending at a level, status by
    sector, approved/rejected on `file_status`, and the `file_status` key.
  - `tests/test_cmelevate_usecase_fixes.py` (33 tests).
  - Docs: AI_PIPELINE §2.8 and §2.9, D-027, KNOWN_ISSUES KI-068 to KI-076, TESTING, SCHEMES,
    CURRENT_STATE, and the CLAUDE.md baseline.
- **Tests:** pytest 891 passed; scripts 14/14; live context suite 43/43. 11 reworded probes gave
  10 correct and 1 intent flake (KI-076, pre-existing).
- **Scope:** every change is gated on `schemes == ["CM Elevate"]`. The only shared-code
  touches are the Unresolved-scheme tuple and the CM Elevate term regex. No YAML was edited.
- **Next step:**
  - Commit when the user asks.
  - **Ask the product owner which "pending" is wanted (KI-074)**: verification On Hold (953)
    or file status Pending (8,472). If they choose file status, change the vocabulary line and
    drop `_cme_pending_file_status`.
  - Consider KI-076.
- **Harness:**
  - the scratchpad `63ff2b45-…/scratchpad` holds cases, expected, judge, run_bot, render,
    build_xlsx (`ROUND=2`), verdicts and `verdicts_after`, plus the `probe/` folder;
  - run passes sequentially with `DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=6`;
  - read every answer, because the judge misses grouped lists and top-3 answers.

**Latest session (2026-09-27, continued): Focus Plus fixes. Code changed, uncommitted.**
- **Result: 30 / 30** (39 / 39 questions) on 2 of 2 fresh live runs after fixing KI-060 to
  KI-064, plus two bugs found along the way:
  - KI-066: in all schemes, a typed reply that resumed a pause and then paused again was
    remembered as the bare reply;
  - KI-067: a Focus Legacy bank question raised `KeyError`.
- **Report:** `docs/Focus_Plus_UseCase_Test_Report_2026-09-27_v2_after_fixes.xlsx`, with
  evidence in `docs/Focus_Plus_UseCase_Evidence_2026-09-27_after_fixes/`. It keeps the round-1
  status as a column.
- **Files:**
  - `app/pipeline.py`: `_focusplus_answer_guarantees` and its `_fp_*` helpers,
    `_fix_digit_grouping`, `_sql_literal_numbers`, `_bank_clarification` (chips and a Focus
    Legacy entry), `SCHEME_PAUSE_RULES`, `_needs_scope_clarification`, and turn_context
    `resumed_question`;
  - `app/routers/query.py`: `pause_question`;
  - `tests/test_focusplus_usecase_fixes.py` (32 tests);
  - docs: AI_PIPELINE §2.9 / §5.2, D-026, KNOWN_ISSUES, TESTING, SCHEMES, CURRENT_STATE and
    CLAUDE.md baselines.
- **Tests:** pytest 858 passed; scripts 14/14; live context suite 43/43.
- **Scope:** the answer guarantees are gated on Focus Plus. The digit-grouping fix, the
  SQL-literal numbers and `pause_question` apply to every scheme (D-026 explains why).
- **Next step:** commit when the user asks. Consider extending `_fp_comparison` and the
  shares to other schemes if their QA shows the same gaps. KI-065 is waiting on the data team.

**Earlier the same day: Focus Plus use-case QA, round 1. No code changed.**
- **Result: 19 / 30 test cases pass** (27 / 39 questions). Two live runs agreed on every verdict.
  Every figure was checked against megh_db and the raw `Focus Plus Master.csv`.
  - The user said "Focus legacy" but named the Focus Plus files, so Focus Plus was tested.
- **Report:** `docs/Focus_Plus_UseCase_Test_Report_2026-09-27.xlsx`:
  - sheets Summary, Test Results, Question Detail, DB vs Raw and Evidence;
  - the Evidence sheet embeds `docs/Focus_Plus_UseCase_Evidence_2026-09-27/*.png`.
- **New open issues:**
  - KI-060: no percentages;
  - KI-061: no difference or "which is higher";
  - KI-062: the composer printed "1,0263";
  - KI-063: the no-chip "which bank" clarification loses the question;
  - KI-064: wording;
  - KI-065: a data-side district difference. The data-team note is `docs/Focus_Plus_DB_Issues.md`.
- **Next step (done later the same day):** fix KI-060 to KI-064 and re-run the 39 questions. The harness scripts (cases, judge, run_bot, render, build_xlsx) are
  in the session scratchpad, not the repo, and the method is on the report's Summary sheet.
- **Harness lessons:**
  - A question that pauses for "which area?" needs the "All of Meghalaya" chip, not the first
    district.
  - Set `PYTHONIOENCODING=utf-8`, or the "₹" in an answer crashes the runner's print.
  - Fetching the whole `v_focus_plus` view needs `timeout=500`.

**Previous session (2026-09-26, into the night): MGNREGA all-blocks and all-villages test, then fixes.
Code changed, uncommitted.**
- **Result on the final code: 13,298 / 13,298.**
  - All 56 blocks × 8 questions and all 6,425 villages × 2 questions (FY 2024-25);
  - each figure matched against megh_db and the raw CSVs.
  - Report: `docs/MGNREGA_AllBlocks_AllVillages_Test_Report_2026-09-26.xlsx`, with before/after
    evidence images.
- **Fixed:** KI-049 to KI-059 (the table and causes are in KNOWN_ISSUES), all in `app/pipeline.py`
  and all gated on MGNREGA. The ones to know:
  - the village-chip resume is pinned from the chip text (`_mgnrega_village_chip_pin`);
  - `_mgnrega_longest_village_in` does a whole-name lookup over every MGNREGA village;
  - SQL rewrites around a resolved `village_code`: `_mgnrega_pin_village_code` and
    `_mgnrega_drop_geo_beside_village`;
  - `_mgnrega_empty_answer` handles no-record and zero-base answers.
- **Tests:** `tests/test_mgnrega_usecase_fixes.py` now has 78 tests. Final suite numbers are in
  TESTING.md.
- **Bulk-run lesson (read before running one):** cap the DB pool (`DB_POOL_MAX_SIZE=10`).
  Tonight's VPN drops plus the default pool of 30 exhausted `megh_db` ("too many clients").
  The harness pauses on outages and retries. The method is in TESTING.md, "Bulk live runs".
- **Open:**
  - 16 village-to-block mapping differences between the DB and raw (the data team's; in
    `MGNREGA_DB_Issues.md`);
  - the KI-041 chip bug still exists in the other five schemes (awaiting the user's go-ahead);
  - generic "total expenditure" questions still ask "which scheme?", by design.
- **Next step:** commit when the user asks. Consider running the same all-villages harness for
  other years, and for the other schemes if the user wants the gated fixes extended.

**Earlier the same day: MGNREGA use-case QA, then fixes (30 / 30).**
- **Round 1:** 16 / 30. Report: `docs/MGNREGA_UseCase_Test_Report_2026-09-26.xlsx`.
- **Fixes:** KI-041 to KI-048, plus wording and unit fixes, all gated on MGNREGA (the user asked
  that other schemes not change). Rationale is in D-025, and the fix map is in KNOWN_ISSUES under
  "KI-041 to KI-048".
- **Round 2:** 30 / 30. Evidence: 43 of 43 queries on two fresh full live runs, checked against
  megh_db and the raw CSVs. Report: `docs/MGNREGA_UseCase_Test_Report_2026-09-26_v2_after_fixes.xlsx`.
- **Files changed:**
  - `app/pipeline.py`;
  - `app/schema_context.py` (MGNREGA rules 8–10);
  - new `tests/test_mgnrega_usecase_fixes.py` (41 tests);
  - docs: AI_PIPELINE, KNOWN_ISSUES, DECISIONS (D-025), CURRENT_STATE, TESTING and
    `MGNREGA_DB_Issues.md`.
- **Tests:** pytest 789 passed (baseline 748). Scripts 14/14. Live context suite 43/43.
- **Open items:**
  - GENAPARA's geography differs between the DB and raw (the data team's, in
    `docs/MGNREGA_DB_Issues.md`);
  - the KI-041 chip bug in the other schemes (awaiting the user's go-ahead);
  - generic "total expenditure" questions still ask "which scheme?". That is by design, since
    PMAY-G and Focus Plus also hold money.
- **Next step:** commit when the user asks. If other schemes are to get the KI-041 fix, remove
  the `"MGNREGA" in schemes` condition in `_explicit_level_in`, then re-run their QA sets.
- The harness scripts lived in the session scratchpad and are **not** in the repo. The method is
  on each report's Summary sheet.

**Previous session:** 2026-09-26. The context-hardening session, then a live validation with the
VPN up. Code changed, **uncommitted** (the user asked for no commit). Also uncommitted from
earlier the same day: context pass 1 (D-022) and the "All of Meghalaya" scope chip.

**LIVE-VERIFIED 2026-09-26** (`tests/live_context_validation.py`, real gateway and DB, turns
rotated across 3 worker stores through real Postgres):
- **43/43 checks**, follow-up resolution 29/29, SQL 20/20, repeated twice.
- Legacy A/B (`--legacy`): 39/43. Figures are in TESTING.md, "Live A/B".
- DB sync cost: about 50 ms p50 each way; `sync_in` p95 359 ms.

**The first live run found, and this session fixed:**
1. **Scenario design:** Focus Plus holds only FY 2022-23 and FY 2025-26, so the scenarios now use
   FY 2025-26. Scenario B2 (MGNREGA) checks the SQL-level year change. Scenario F step 5 no
   longer carries an FY, which D-009 pins to CM Elevate Legacy.
2. **Real bug:** "Show it by district." was rewritten "…in West Garo Hills". The fix is a
   `REMOVED by the follow-up` prompt line plus the `cleared:<field>` check
   (`_cleared_filters`, `context_policy.rewrite_violation`).
3. **Real bug:** "How many beneficiaries were there?" was not treated as a follow-up. The fix is
   `pipeline.is_scopeless_followup`, used in `_run_pipeline` and in the router's `is_cacheable`.

**New open issues (Low):**
- KI-030: an "all years" choice is not carried into the next follow-up.
- KI-031: the scheme swap keeps the old metric words.

**TESTS:** pytest, 19 files: **657 passed**. Scripts: **14/14**. Live: 43/43.

**LATEST: scheme substitution fixed (KI-039), uncommitted.** "give me same for <scheme>"
used to be answered from the reference docs. It is now a follow-up that swaps only the scheme:
`pipeline._scheme_substitution` / `is_scheme_substitution`, plan kind `SCHEME_SUBSTITUTION`,
AI_PIPELINE.md §5.6.
- Tests: `tests/test_scheme_substitution.py` (91).
- Live results: `logs/live_scheme_substitution_2026-09-26.json`.
- New Medium issue KI-040: MGNREGA "beneficiaries" is undefined.

**Before that (same day): live end-to-end validation, no code changed.** The report is
`docs/Context_Validation_Report_2026-09-26.md`: 53 turns, 47 PASS, 1 caveat, 5 FAIL. New issues KI-032 to KI-038.

**NEXT EXACT STEP (supersedes the list below):**
1. KI-032: apply the plan's CLEAR to `session.state` in `update_state`.
2. KI-034: a deterministic "resolved entity missing from SQL" guard.
3. KI-033: use the last DATA turn as the antecedent after a digression.
4. KI-035: never sum per-year distinct counts as a total.
5. Then re-run `tests/live_context_validation.py` and the validation groups.

**Previous next steps:**
1. KI-030: add a `year_all_combined` flag, mirroring `tranche_all_combined`.
2. KI-031.
3. Then the KI-022 / KI-023 user decision, which is still pending.

Re-run `tests/live_context_validation.py` (VPN) after any routing, rewrite or state change.

**DO NOT CHANGE (without reading the incident comment and the tests):**
- the `execute_with_repair` guards and `_verify_sql` filters;
- the `compose_response` faithfulness checks;
- `db._assert_safe` / `run_readonly`;
- the scheme-collision handling;
- the pending-pause resume (steps 0a / 0a');
- `data/<scheme>/*.yaml`;
- `megh_db.curated`.

Do not reintroduce raw previous-answer text into the rewrite prompt (D-022). Do not move
conversation state back into process memory (D-023).

**Never print or copy rows from `Focus Legacy to share to BLH.csv`.**
