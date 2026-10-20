# Testing

*Reconciled on 2026-09-26 by running the full suite on the Windows dev box, with the
`10.48.242.4` DB and gateway **unreachable** (VPN off).*

## 1. What the tests are, and what they are not

- Every test is a **regression lock for a past incident**. The tests cover:
  - regex routing;
  - prompt text;
  - YAML catalogues;
  - deterministic helpers;
  - flows with the LLM stubbed out.
- **No test measures NL→SQL accuracy** against the real models and DB. A green suite says nothing
  about whether answers are correct (KNOWN_ISSUES KI-017).
- Correctness is checked by **live QA passes**. Their reports are in `docs/*.xlsx` and
  `docs/*_DB_Issues.md`:
  - Focus Legacy: 28/28, plus the bulk run of 168 + 580; re-tested 2026-09-29: 28/28 on 3 of 3 runs vs DB and raw (`docs/Focus_Legacy_UseCase_Test_Report_2026-09-29.xlsx`, v2 after fixes `…_v2_after_fixes.xlsx`); all blocks / villages / ACs / PGs 32,560/32,560 (`docs/Focus_Legacy_AllBlocks_Villages_ACs_PGs_Test_Report_2026-09-29.xlsx`);
  - CM Elevate Legacy: 36/36 on 2026-09-25; re-tested 2026-09-29: **33/36** vs DB and raw (2 full runs + 3 repeats of the failures;
    `docs/CM_Elevate_Legacy_UseCase_Test_Report_2026-09-29.xlsx` + `_Evidence_2026-09-29/`). TC-13/14/34 failed in the AI layer (KI-166..168);
    **after fixes 36/36** on 2 of 2 fresh runs (`…_2026-09-29_v2_after_fixes.xlsx` + `_Evidence_2026-09-29_after_fixes/`);
    all districts / blocks / villages / constituencies **2,614/2,614** vs DB and raw (KI-169..181;
    `docs/CM_Elevate_Legacy_AllBlocks_AllVillages_Test_Report_2026-09-29.xlsx` + `_Evidence_2026-09-29/`).

## 2. How to run

Always use the repo venv, and run from the repo root (`.env` is read relative to the working
directory):

```bash
# 1) pytest-style suites (46 files as of 2026-10-13). Do NOT run `pytest tests` — see KI-018.
.venv/Scripts/python.exe -m pytest -q $(grep -lE "^\s*(async )?def test_" tests/test_*.py)

# 2) plain-script suites (14 files) — each prints "ALL … PASSED" and exits 0/1
for f in tests/test_ac_full_results.py tests/test_admin_level_collision.py \
         tests/test_block_backstop.py tests/test_block_parent_district.py \
         tests/test_context_manager.py tests/test_cross_scheme_collision.py \
         tests/test_cross_scheme_money.py tests/test_edge_conversational.py \
         tests/test_focusplus_block_columns.py tests/test_history_charts.py \
         tests/test_mgnrega_split_facts.py tests/test_no_data_answer.py \
         tests/test_security.py tests/test_verifier_missing_geo.py; do
  PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "$f" || echo "FAIL $f"; done
```

- Set `PYTHONIOENCODING=utf-8` on Windows, because the scripts print non-ASCII characters.
- **LangGraph is the only orchestrator (D-036): one pytest run covers it.** There is no
  sequential path and no flag to sweep. Tests that need a whole turn use `tests/_graph_turn.py`:
  `graph_turn(question, session=…)` runs `answer_question` (the graph) with an in-process
  checkpointer, and `stub_data_path(monkeypatch, fake)` stubs the DATA path at the `scope_scheme`
  stage. `tests/test_pipeline_graph.py` drives whole conversations through the graph (results, pauses,
  session state and model / DB call counts) and fails if a sequential driver or on/off setting comes
  back. Live: `tests/live_context_validation.py`.
- The script suites are slow when the DB is unreachable. Some entity-resolution paths wait for
  connect timeouts.
- `tests/smoke_restructure.py` is an end-to-end smoke test against a **running server** at
  `http://127.0.0.1:8502` (hardcoded `BASE`, not the default 8400). It was not run.

### Live context validation (needs the VPN)

```bash
.venv/Scripts/python.exe tests/live_context_validation.py            # all scenarios, 3 workers via Postgres
.venv/Scripts/python.exe tests/live_context_validation.py --legacy   # the pre-2026-09-26 rewrite, for A/B
.venv/Scripts/python.exe tests/live_context_validation.py --only A,E --no-db-sync
```

- Exit codes: 0 means all checks passed; 1 means a check failed; 3 means not run (unreachable).
- The report is written to `logs/live_context_validation.json`.
- With DB sync on, it writes temporary `app.conversations` rows under `live-ctx-*` session ids
  and deletes them at the end.
- **Headless browser check** (2026-10-18): `tests/ui_headless/` — `mint_token.py` (a JWT for a seeded user via the
  app's `security` module; the seed passwords are rotated) and `chat_flow.py` (Playwright, system `py -3`): asks,
  types "stop" mid-answer, "continue", "go back to the … one", "what did we discuss?", screenshots at 390 / 820 /
  1440 px, checks the scope banner, overflow and console errors. Run against your own app instance (port 8401).
- **Live context matrix** (2026-10-18): `tests/live_context_matrix.py` runs 7 flows (forward place/year/measure,
  "what is the total …", out of scope, knowledge digression, backward by content, backward by order, topic switch
  and back) for EVERY scheme — 42 conversations on 3 simulated workers; `--only MGNREGA,PMAY-G --flows F1,F5`. A
  dropped connection fails that conversation (retried once) and the run goes on. Report `logs/live_context_matrix.json`.
- Scenarios H..M cover the forward plan (KI-306); N..R (added 2026-10-18, D-050) cover out-of-context in the
  middle, going back to an earlier question by content (+ scope banner) and by order, "what did we discuss?",
  and a reference only the model can place. The harness runs the router's refusal restyle like `_answer` does.

### Bulk live runs: every MGNREGA block and village (2026-09-26)

These runs are the only accuracy checks at scale; see §1 on why green unit tests do not prove
NL→SQL accuracy. The harness lived in the session scratchpad; its method is recorded here and on
the report's Summary sheet.

- **Cases:** FY 2024-25.
  - All 56 blocks × 8 questions: households, person-days, expenditure, women, 100-day %, spend
    + person-days, and two bare-name forms.
  - All 6,425 villages × 2 questions: person-days and total expenditure.
  - Village names are typed exactly as stored.
- **Expected values:** SUM by `village_code` / block from megh_db, read-only. Independently, the
  same sums from the raw CSVs in the repo root.
- **Execution:** `pipeline.answer_question` in-process with the `.venv` Python. When the bot
  pauses, the harness clicks the chip an officer would pick:
  - the option carrying the target village's exact name and block;
  - "village" or "block";
  - MGNREGA.
- **Pass rule:** the answer states the expected figure (lakh/crore display rounding allowed), or
  says there are no records without inventing a number.
- **DB connections: limit the pool.** The default pool is 10–30 connections per process, and
  `megh_db` allows `max_connections` = 100 in total and is shared. During a VPN drop, the server
  keeps the dead connections open until its TCP timeout. On 2026-09-26 that exhausted the server
  ("too many clients already"), and the pipeline turned it into "couldn't build a query" / KB
  fallbacks (KI-025).
  - Run bulk jobs with `DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=10` and concurrency ≤ 10.
  - Pause on outages: check TCP to 10.48.242.4:5432 before each case, and retry a case that
    failed while the host was down.
- **Expect wall-clock time:** about 55 cases/min at concurrency 10.

## 2b. Conversation harness (2026-10-18) — `tests/conversation_harness/`

Multi-turn scenarios in YAML (`scenarios/*.yaml`) with per-turn expectations (route, scope banner components, figures,
leaks, chips, pause rules, `same_scope_as` / `same_numbers_as` an earlier turn, `truth` = a read-only SQL whose value must
be in the answer), run against the chatbot and reported turn by turn. Two drivers: **http** (the running server's
`POST /api/query` or `/api/query/stream`, a JWT minted in-process for any seeded account — caches, rehydration, permissions
and streaming included; authoritative) and **inprocess** (the router path on the graph in this process, for the decision
log). The earlier context suites are in-process only and PASSED while the server failed (a server session holds only its
last turn): always finish with the http driver.

```bash
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver http            # all scenarios, server on :8401
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver http --stream --account state-rd --tags hierarchy
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver inprocess --only C_backward_restore
.venv/Scripts/python.exe -m tests.conversation_harness.run --validate               # offline
```

Exit 0 / 1 (a check failed) / 2 (bad scenario file) / 3 (nothing could run). Reports in `logs/conversation_harness/`.
Offline unit tests: `tests/test_conversation_harness.py`. Scenario set (17): the context-memory review A–E (out of
scope incl. leak, many asides, refusal, denied follow-up; forward; general; backward; hierarchy with roll-up), the
conversation-meta flows (recap / explain / breakdown / correction / pick-a-district / overview / reason), comparisons
with another scheme, and the farmers question. Format and rules: `tests/conversation_harness/README.md`.

## 3. Latest results

| Date | Suite | Result | Notes |
|---|---|---|---|
| 2026-10-19 afternoon (single-year phrase strip KI-326, script stub leak, number-word note) | pytest (documented command), scripts, live HTTP | `tests/test_single_year_phrase_2026_10_19.py` 7 + framing 8 + year-asked 7 = 21 passed; `tests/test_admin_level_collision.py` then `tests/test_pipeline_graph.py` in ONE process 48/48 (was 15 failures; the script now restores its stubs); the script standalone passes. Live on :8401 (restarted 13:21, venv): West Jaintia Hills FY 2022-23 -> 976,990 person-days, Ri Bhoi FY 2021-22 -> 87 houses, scope line present, no all-years phrase. Full documented pytest run: **3,033 passed, 0 failed**, 2 skipped (3 min 57 s, single process) | VPN up |
| 2026-10-19 afternoon (two-dimension charts, KI-325) | headless Chromium (`tests/ui_headless/chart_two_dim.py`, Python 3.14 has Playwright; server :8401) | "compare MGNREGA and PMAY-G expenditure for each financial year" -> line, x = 2017-18 … 2025-26, series PMAY-G / MGNREGA, insight "Latest (2025-26): PMAY-G 0 · MGNREGA 916.06"; "MGNREGA expenditure in East Khasi Hills and West Garo Hills for each financial year" (backend hint `stacked`) -> districts on the axis, years in the legend. Both at 320 / 390 / 1280 / 1440 px, no horizontal overflow. `npm run build` done (web/app). | VPN up |
| 2026-10-19 midday (answer framing + two harness findings) | pytest 3 shards, scripts, conversation harness (http) | pytest **3,013 passed, 1 failed** (`test_ki148_scheme_question_offers_only_constituency_schemes`: the parallel session's c03 `_scheme_clarification` now has 6 options and new wording — theirs), 2 skipped; scripts 14/14. Harness on the final code: forward scenario 2/2 with the DB truth 106,527 (KI-323 fixed: calendar-year date range for a financial year), full set **16/17** — the miss is the MGNREGA year pause not accepting "all of them combined" (KI-324, D-053 area); scenarios aligned to D-053 (year asked after a scheme reply) and to the crore display of MGNREGA money. Harness reports now carry each turn's SQL / rewritten question / resolved entities (`logs/conversation_harness/2026-10-19_1222_final.json`) | VPN dropped twice |
| 2026-10-19 morning (answer framing, D-054, KI-321) | pytest, live HTTP, harness | `tests/test_answer_framing_2026_10_18.py` 8 + the suites pinning fallback text (CM Elevate Legacy, MGNREGA sheet, pipeline graph) pass; full 3-shard pytest: my changes green, the 8 failures in `tests/test_year_asked_without_context_2026_10_19.py` / `test_focus_legacy_usecase_fixes::test_ki148…` belong to the parallel session's in-progress D-053 (year asked on a fresh question). Live formats checked through the API: MGNREGA fallback framed, person-days grouped with a scope line, PMAY-G deterministic facts get the scope line, EKH expenditure (already naming scheme and place) unchanged. Conversation harness re-run after the change: see the row's note below | VPN up |
| 2026-10-18 evening (conversation harness, first run) | `tests/conversation_harness` http driver, pytest | 17 scenarios / 72 turns through the live API: **16/17 scenarios, 71/72 turns**; the one miss, `META_recap_explain_breakdown` turn 5, was KI-315 (verifier false positive) plus a failed turn polluting the next rewrite — both fixed (c11 `_verifier_total_vs_breakdown_is_false`, c14 `_mark_failed_data_turn`); re-run 4/4, then the full set **17/17 scenarios, 72/72 turns** (`_2031_full-run.json`); stream driver 3/3 (`_2021_stream.json`). pytest after the fixes **2,996 passed, 0 failed**, 2 skipped; scripts 14/14; `tests/test_conversation_harness.py` 9, `tests/test_verifier_breakdown_2026_10_18.py` 2 | VPN up |
| 2026-10-18 late afternoon (context memory acceptance through the HTTP API; KI-315, KI-316, KI-318) | pytest 3 shards, scripts, live NL->SQL eval, live HTTP scenarios | pytest **2,951 passed, 0 failed**, 2 skipped (both sessions' changes present; `tests/test_conversation_meta_2026_10_18.py` 73 after the ledger test fix); scripts **14/14**. Eval `2026-10-18_1621_context-memory-2026-10-18-rerun.json` **72/74**: MG-08 = KI-313 (verifier false positive, identical SQL to the passing 13:08 run), FL-12 = a differently generated 30B query with identical inputs, **correct on re-run** (`_fl12-recheck-2`). Three earlier eval runs were wrecked by VPN drops (gold_error / timeouts) and are not evidence. Live, through `POST /api/query` and `/api/query/stream` on the running server (scratchpad `http_probe.py`, JWT minted in-process for `state-rd` and `superadmin`): B out-of-context (data -> cricket -> "What about 2023-24?" = 80,923, also cached and streamed; B5 "raining in Shillong in 2024" leaks nothing; five asides in a row; a harmful refusal; a denied follow-up) ✓; A forward (MGNREGA -> PMAY-G rules -> "How many in 2023-24?" = PMAY-G statewide 106,527) ✓; D general ("How many beneficiaries are there?" -> cross-scheme table -> "Focus Plus" -> total / West Garo Hills) ✓; E hierarchy (EKH 8,996.36 -> by block -> only Mawphlang 1,168.22 -> which villages -> back to the district level 8,996.36 -> statewide 75,961.36 -> 2022-23 88,629.40; PMAY-G Mawphlang 1,378 -> whole district 12,038 -> statewide 71,976) ✓ with both accounts; C backward ("go back to the East Khasi Hills one", "the first question", "what did we discuss?") ✓; meta + out-of-scope mixed ✓ except KI-315 (correction -> sanctioned by block, verifier). KI-320 after the fix: "Total MGNREGA person-days in FY 2023-24" -> "compare with pmay" -> cross-scheme table MGNREGA vs PMAY-G, statewide FY 2023-24 ✓; PMAY-G Ri Bhoi -> "and compared to Focus Plus?" -> table with "no data for FY 2023-24" for Focus Plus -> "what about 2022-23?" (559 vs 419) ✓; MGNREGA West Garo Hills -> "compare with pmay" -> "by block" -> block-wise comparison table ✓. Open: KI-318 ("go back to Mawphlang" after a year change answers the current year) | VPN dropped four times during the session |
| 2026-10-18 afternoon (conversation meta, D-052, KI-310..313) | pytest 3 shards, scripts, live NL->SQL eval, live conversations | pytest **2,935 passed, 0 failed**, 2 skipped (+64 `tests/test_conversation_meta_2026_10_18.py`); scripts **14/14**. Eval `2026-10-18_1429_conversation-meta-2026-10-18.json` 55/59 with 15 gold_error + 3 timeouts during a DB drop; re-run of those 19 ids (`_1433_conversation-meta-recheck.json`) **18/19** — the one wrong, MG-08, is a verifier false positive with SQL identical to the passing 13:08 run (KI-313, not a regression; fails 3/3 since). Live (scratchpad `conv_probe.py`: router path, real models + megh_db): the user's own conversation — houses 2023-24 106,527 -> "why are you not giving me district wise?" -> district-wise with apology -> "okay give me for East Khasi Hills" 17,281 -> "that's wrong, I asked for completed houses" -> EKH completed 12,038 -> "ok and Ri Bhoi?" 6,847 -> explain (9B, grounded) -> "what should I ask next?" -> thanks. Dalu block officer -> overview (8,892.08 lakh, 2,646,057 person-days) -> "compare with last year" asks which year -> FY 2024-25 (2,132.46 lakh, 390,921) -> "why is it so low?" -> reason + chips -> by-block comparison (8 blocks) -> recap. "farmers getting money" -> which Focus. Still open: KI-311 MGNREGA two-year / two-fact shapes, KI-312 Focus Plus overview drops the amount | VPN dropped once mid-run, recovered |
| 2026-10-18 afternoon (pick-a-district, KI-317) | pytest 3 shards, scripts, live NL->SQL eval, live conversation | pytest **2,834 passed, 0 failed**, 2 skipped (+15 `tests/test_pick_district_2026_10_18.py`); scripts **14/14**; eval `2026-10-18_1308_pick-district-2026-10-18.json` **100% (74/74)**, 0 regressions vs 2026-10-16_1902. Live (scratchpad `live_pick.py`, harness `Conv` under the app lifespan): PMAY-G houses 2023-24 -> 106,527; the user's "show me the districts … I will choose one" -> 12 district chips + All of Meghalaya; typed "East Khasi Hills" -> 17,281; completed 2023-24 -> "list the districts, I will pick one" -> "West Garo Hills" -> 13,964; "Which district has the most …" still answered directly (West Garo Hills 19,058) | VPN up |
| 2026-10-18 end of day | pytest 3 shards | **2,971 passed, 0 failed**, 2 skipped — after the comparison rewrite, the cache-hit state fix (KI-319), the sync retry (KI-314) and the idle-ack aside | — |
| 2026-10-18 evening (idle chip in the browser; wording probes V1..V6) | browser (`tests/ui_headless/idle_chip_flow.py`, 60 s idle window), live | Idle chip: appears after the window, tap restores, follow-up answers the restored scope with its banner — after fixing that the acknowledgement was not an aside (first run asked "which scheme?"). Probes: V2 Hinglish, V3 "same for PMAY-G", V5 "the second question", V6 thanks + off-topic all pass; V4 "compare this with the MGNREGA figure" was not built -> `comparison_with_earlier` added; V1 "that number again" passes on 3 workers (rules: no match; the 9B picked q2 = Ri Bhoi; re-run) — its first failure was a DB drop on the Ri Bhoi turn; V4 live passes (single worker; "Compare PMAY-G and MGNREGA in East Khasi Hills in FY 2022-23", both schemes answered) — the 3-worker run was broken by the DB drop on its first two turns. Hardening tests 99 passed with the sync retry; `test_cache_hit_context.py` 3, `test_session_sync_retry.py` 3 | VPN flapping |
| 2026-10-18 late (ledger "pure go back" fix, live) | live O, Q | Q 3/3 (incl. worker sync); O product checks 5/5, its worker-sync check failed on a DB drop (`save-failed`, `unavailable`) — the run before, the same drop made Q's T4 answer from a stale worker (see KI-314) | VPN flapping |
| 2026-10-18 late (headless browser check) | browser (`tests/ui_headless/chat_flow.py`) | Phone / tablet / desktop all correct: banner "ANSWERED FOR MGNREGA · East Khasi Hills · FY 2022-23"; typed "stop" stopped the answer, "continue" answered it (Ri Bhoi, year kept); "go back to the East Khasi Hills one" -> "(from earlier)" banner; history list; scrollWidth == clientWidth at every width; 0 console errors. Found + fixed: a pure "go back" was filed as a new numbered question (topic_memory `_file_ledger`; `test_topic_ledger.py` +2). The "Continue with …" chip after a 4-hour idle was not exercised in the browser (offline tests only) | VPN up |
| 2026-10-18 night (UI failures KI-309, KI-308, live matrix) | pytest 3 shards, live | pytest: **2,870 passed, 1 failed, 2 skipped**; the one failure (`tests/test_scheme_years.py::test_route_stage_answers_years_before_the_knowledge_split`, an `inspect.getsource` pin) was a run artifact — another session saved `c14_turn_stages.py` at 13:29 while the 33-minute shard was running, so the loaded code and the file disagreed; re-run alone afterwards: 26 passed. Effective result **2,871 passed, 0 failed**; final re-run after the CM Elevate-family fix: **2,940 passed, 0 failed**, 2 skipped. (That session also added `c15_conversation_meta.py` and two test files; see HANDOFF.). Live: first matrix run (before the KI-308 / term-gate fixes) 21/23 conversations passed, then the DB connection dropped at #24 (harness now survives it); the 2 failures were F2 "what is the total …" (MGNREGA, Focus Legacy) — fixed. Second full run: **42/42 conversations** (MGNREGA, PMAY-G, Focus Plus 21/21 and Focus Legacy F2..F7 in run 2 — the run then hung on a dead DB connection after a gateway ReadTimeout and was stopped; Focus Legacy F1 14/14 checks and CM Elevate + CM Elevate Legacy 14/14 conversations, 93/93 checks, in run 3 after the CM Elevate-family fix and the applications-only wording). Caveat: the 27 run-2 conversations ran before the CM-family edit (topic_memory / c03 / context_manager), which only changes behaviour when a CM Elevate name is involved. Scenarios F, U1, U2: F 5/6 (KI-308 fixed: 'What about Dalu block?' continues MGNREGA; the one miss is the harness worker-sync check during a DB blip), U1 5/5, U2 5/5 — follow-up resolution 12/12 | VPN flapping |
| 2026-10-18 evening (memory sizes, D-051) | pytest 3 shards | **2,819 passed, 0 failed**, 2 skipped (+3 D-051 tests in `tests/test_stop_continue.py`) | VPN up |
| 2026-10-18 evening (stop -> "continue", D-050) | pytest, live | new `tests/test_stop_continue.py` 35 (+ `test_query_stream.py`); full pytest 3 shards **2,816 passed, 0 failed**, 2 skipped. Live (scratchpad `live_stop_continue.py`, real router + pipeline, writes stubbed): stream stopped after its first frame -> question remembered; "continue" -> MGNREGA East Khasi Hills FY 2022-23 = 3,408,697 person-days, banner shown, stopped question cleared | VPN up |
| 2026-10-18 later (context memory P4..P6, D-050) | pytest 3 shards, scripts, live | pytest **2,779 passed, 0 failed**, 2 skipped; scripts **14/14**; `tests/test_topic_ledger.py` 75. Live `live_context_validation.py`: N, O (incl. banner "(from earlier)"), P, Q, R pass. N first failed because the harness skipped the router's `conversation_replies.restyle` (which marks a refusal an aside) — harness fixed, product unchanged. R first failed: the 9B answered NONE for "that employment figure" — prompt now gives each scheme's meaning, then q1. Full A..R: full A..R on 3 workers 79/83 checks; then H fixed (rehydrated-worker antecedent, see KI-307) and passes; remaining: E T1 (expects a 'which scheme?' pause — outdated by D-045 answer-defaults, not a regression) and F T3 (KI-308 guard/verifier ping-pong, fails with the D-050 features off too) | VPN up |
| 2026-10-18 (topic ledger, D-050, KI-307) | pytest, 9 context files | **560 passed, 0 failed** (baseline before the change 516; +44 `tests/test_topic_ledger.py`). Full 3-shard suite, the 14 scripts and the live suite NOT run; live scenarios N..Q written, not run | VPN down |
| 2026-10-16 evening (ingestion DB changes, D-049) | pytest 3 shards, live NL->SQL eval | pytest **2,667 passed, 0 failed**, 2 skipped (+26 `tests/test_db_changes_2026_10_16.py`). Eval `2026-10-16_1730_db-changes-2026-10-16.json`: **95.9% (71/74)** vs 17:11 run: FP-05 fixed, PM-04 regressed (guard ping-pong from parallel work, see HANDOFF); CE-11 (gender) answered not-available by design — gold since edited by the parallel session. NOTE: the full suite now takes ~50 min serially; run it in shards | VPN up; superuser override |
| 2026-10-08 (conversation layer, live test cases; KI-225, KI-226) | pytest 38 files, scripts, live | pytest **1,935 passed, 0 failed**, 1 skipped (`tests/test_conversation_layer.py` now 78); scripts **14/14**. Live: **36/38** cases (scratchpad `8e45ba45-…/scratchpad/live_cases.py`, automatic checks, through `routers.query._answer`): follow-up 5/5, topic switch 2/2, return 6/6, pronoun 2/2, clarification 3/3, override 2/2, general 6/6, context-aware general 2/2, reset 4/4, expiry 2/2, no-regression 2/4. The 2 failures (NG-03/NG-04, scheme swap refused by the guardrail model) fail identically with the layer off: KI-225. GN-04 failed before the KI-226 fix (also with the layer off) | VPN up |
| 2026-10-08 (conversation layer, D-043; KI-222) | pytest 38 files, scripts, live | pytest **1,926 passed, 0 failed**, 1 skipped (+69 in the new `tests/test_conversation_layer.py`; `tests/test_topic_memory.py` 38); scripts **14/14**. Live (scratchpad `8e45ba45-…/scratchpad/live_conv.py`: 15 multi-turn scenarios through `routers.query._answer`, persistence / audit / sync / cache writes stubbed): spec scenarios 1-6, the §22 multi-topic run, reset, reset with a question, bare return then measure, data topic return keeps WGH + FY ("What about 2022-23?" -> 572). Before the KI-222 fix S1/S2/S7/S10 asked "which scheme?"; after, they continue with the scheme. `live_context_validation.py` NOT re-run | VPN up |
| 2026-10-08 (word-by-word reveal, frontend only) | browser | **28/28** in `ui_format_scroll_test.mjs` (+5: the answer grows word by word, cursor while writing, extras wait for the text, then the whole answer and the extras); streaming **17/17**, banner **20/20**. Waits now include "no `.draft-cursor` left" | VPN not used by the tests |
| 2026-10-13 (Cross Scheme sheet CROSS-1..20 + generated permutations; KI-280..288, D-044) | pytest, scripts, live bulk | pytest **2,258 passed, 0 failed**, 1 skipped (+28 in the new `tests/test_cross_scheme_sheet_fixes.py`); scripts **14/14**; no finished-sheet turn changes route (0 of 5,120 in `Final_Test_Report_2026-10-13.xlsx`). Live: 9th run 0/20 (18 paused, 2 wrong); after the fixes **20/20** and **8,649/8,649 conversations** on the final code: sheet 138 (every district / block filled), all 57 scheme combinations x count / money / both / ranking / coverage, every FY 2017-18..2025-26, district-wise / leader / top district, every district x every combination 684, every block 134, every constituency 120, **every village 6,978**. Harness `tests/sheet_runs/cross/` (`cross_run.py`, `truth.py`, `write_report.py`); report in `reference_documents/Cross Scheme Test Cases.xlsx` | VPN up; DB out of connection slots once (other uvicorn servers running), re-run at concurrency 8 |
| 2026-10-13 (FINAL ROUND, all seven sheets; KI-279) | pytest, scripts, live | pytest **2,230 passed, 0 failed**, 1 skipped; scripts **14/14**; live: every test case of all seven sheets on the final code — **206/206 test cases, 2,946/2,946 conversations** (General 24, MGNREGA 30, PMAY-G 28, CM Elevate 30, Focus + 30, Focus Legacy 28, CM Elevate Legacy 36). One regression found and fixed in the round (KI-279), the affected cases re-run in full. Report: `reference_documents/Final_Test_Report_2026-10-13.xlsx` (`tests/sheet_runs/final_round.sh`, `final_report.py`) | VPN dropped twice; runs resumed |
| 2026-10-12 (CM Elevate Legacy sheet TC-01..TC-36; KI-273..278) | pytest, scripts, live bulk | pytest **2,160 passed, 0 failed**, 1 skipped (`tests/test_cmelevate_legacy_sheet_fixes.py` 14); scripts **14/14**; live: 9th run 25/36, after the fixes sheet **300/300** and **every CM Elevate Legacy village 1,051/1,051**; Focus Legacy TC-28 re-checked 55/55 after the shared gate change | VPN up |
| 2026-10-12 (Focus Legacy sheet TC-01..TC-28; KI-264..272) | pytest, scripts, live bulk | pytest **2,115 passed, 0 failed**, 1 skipped (`tests/test_focuslegacy_sheet_fixes.py` 23); scripts **14/14**; live: 9th run 19/28, after the fixes sheet **231/231** and **every Focus Legacy village 3,384/3,384** on the final code (`tests/sheet_runs/fl_run.py`, `fl_all.py`) | VPN dropped twice; runs resumed (`fl_drive.sh`) |
| 2026-10-11 (Focus + sheet FOCUS-001..030; KI-260..263) | pytest, scripts, live bulk | pytest **2,092 passed, 0 failed**, 1 skipped (`tests/test_focusplus_sheet_fixes.py` 4); scripts **14/14**; live: 9th run 27/30, after the fixes sheet **163/163** and **every Focus Plus village 3,513/3,513** on the final code (`tests/sheet_runs/fp_run.py`, `fp_all.py`). Twin villages (same name and block) are picked by the LGD code on the chip | VPN flapped; runs resumed |
| 2026-10-10 (CM Elevate sheet CM-ELEVATE-OFF-001..030; KI-253..259) | pytest, scripts, live bulk | pytest **2,088 passed, 0 failed**, 1 skipped (`tests/test_cme_sheet_fixes.py` 11); scripts **14/14**; live: 9th run 20/30, after the fixes sheet **529/529** and **every CM Elevate village 2,087/2,087** on the final code (`tests/sheet_runs/ce_run.py`, `ce_all.py`) | VPN up |
| 2026-10-10 (PMAY-G sheet PMAY-OFF-001..028; KI-249..252) | pytest, scripts, live bulk | pytest **2,077 passed, 0 failed**; scripts **14/14**; live: sheet **678/678**, **every PMAY-G village 5,121/5,121** on the final code (`tests/sheet_runs/pm_run.py`, `pm_all.py`) | VPN up |
| 2026-10-10 (full hierarchy: every MGNREGA village; KI-244..248) | pytest, scripts, live bulk | pytest **2,065 passed, 0 failed**; scripts **14/14**. Live: **6,491/6,491 villages** (one question each, 12 sheet shapes, 4 FYs, 3 name casings), MGNREGA sheet **783/783**, General **24/24** (TC-023 182/182), all on the final code. Scripts: `tests/sheet_runs/` | VPN (one drop, resumed) |
| 2026-10-09 (MGNREGA sheet DATA-001..030; KI-236..243) | pytest, scripts, live | pytest **2,034 passed, 0 failed**, 1 skipped (+29 in the new `tests/test_mgnrega_sheet_fixes.py`); scripts **14/14**. Live (LangGraph, real models, megh_db): 783 conversations — first run 13/30 TCs clean; after the fixes **30/30** (every case clean: 24 villages, 8 same-name villages, 55 blocks, 12 districts, 56 constituencies, 4 FYs). Workbook MGNREGA sheet columns Q–T | VPN up |
| 2026-10-09 (General sheet of Test Case Results - 30th Sep 26.xlsx; KI-228..235) | pytest, scripts, live | pytest **1,962 passed, 0 failed**, 1 skipped, plus **42/42** in the new `tests/test_general_sheet_fixes.py`; scripts **14/14**. Live (LangGraph, real models, megh_db): first run 15/24 Pass (262 conversations; TC-023 hierarchy 182/182); after the fixes the 9 failed cases re-run live and the full 262 re-run: **24/24 Pass**. Results in the workbook's General sheet, columns J–M | VPN up |
| 2026-10-07 (answer formatting + smart auto-scroll, frontend only) | browser | **23/23** (headless Chrome, real app on uvicorn): lists (nested; numbered keeps 1, 2, 5), label / bold / `#` headings, table, inline code, "2023-24" at a line start is not a list, HTML stays text, Copy gives clean text; at the bottom the view follows a streamed answer, scrolled up it does not move, the pill ("Answer is being written" → "New answer") takes you to the end, asking jumps down, phone width. Streaming 17/17 and banner 20/20 re-run. pytest not re-run (no backend change) | VPN not used (offline) |
| 2026-10-07 (connection banner, frontend only) | browser | **20/20** (headless Chrome, real app on uvicorn; request interception simulates server refused, the VPN data-service 503, an nginx 502 and browser offline): banner instead of an error, `/health` polled, the waiting question re-asked once on recovery, "Retry now", a busy 503 stays an ordinary error, phone width. Streaming browser test still **17/17**. pytest not re-run (no backend change) | VPN not used (offline) |
| 2026-10-07 (streamed answers, progress steps, Stop, Regenerate; D-039) | pytest 29 files, scripts, browser | pytest **1,648 passed, 0 failed**, 1 skipped (+14 in the new `tests/test_query_stream.py`; `test_context_hardening.py` source pin moved to `_answer`); scripts **14/14**. Browser (headless Chrome, real app + middleware on uvicorn, the turn stubbed): **17/17**: steps in order, draft then final answer, Stop cancels server-side, Retry / Regenerate send `skip_cache`, phone width. Env: Python 3.12 venv (`.venv` is from another machine); `@pytest.mark.asyncio` tests need `pytest-asyncio` installed | VPN not used (offline) |
| 2026-10-06 (six-scheme tester sheet, 206 cases; KI-201..217, D-035) | pytest 28 files flag off and on, scripts, live | pytest **1,496 passed, 0 failed** with the graph off AND on (+45 in the new `tests/test_qa_2026_10_06_fixes.py`; 3 AC tests updated for D-035); scripts **14/14**. Live: all 206 cases of 'Test Case Results - 30th Sep 26.xlsx' through the real `/megh-chat` UI (headless Edge, screenshots), each figure checked against independent SQL: before the fixes 190/206 (7 partial, 9 fail), after **206/206**; reports `reference_documents/Test_Results_2026-10-06.xlsx` and `..._after_fixes.xlsx` | VPN up (DB port flapped once) |
| 2026-10-02 night → 10-03 (all six schemes, all districts / blocks / villages + officer sets; KI-188..198, D-034) | pytest 27 files flag off and on, scripts, live bulk | pytest: pytest **1,453 passed, 0 failed** (27 files) with the graph off AND on; scripts **14/14**; live context suite **43/43 on both paths** (follow-up 29/29). Live bulk **30,280 / 30,280** on the latest run of each question (MGNREGA 6,378; PMAY-G 5,256; PMAY-G officer cases 5,833; Focus Plus 3,651; CM Elevate 2,165; CM Elevate OFF-009/017/018 2,284; CM Elevate Legacy 1,193; Focus Legacy 3,520). 1,667 failed on a first run; each failure was fixed and re-run (8 re-run rounds, the last 29 → 3 → 0 on the final code). Harness: scratchpad `7be462aa-…/scratchpad/bulk` (`bulk.py gen/run/judge`, `pmay_sets.py`, `cme_sets.py`, `make_reports.py` → `docs/<Scheme>_LangGraph_Test_Results.xlsx`). Run with `DB_POOL_MIN_SIZE=2 DB_POOL_MAX_SIZE=12`, concurrency 10, resumable; background jobs stop at 2 h, so run villages in bounded batches | VPN up (drops handled by `_wait_for_vpn`) |
| 2026-10-02, evening (VPN up; KI-182, KI-183, KI-187 fixed; live gates G3/G4) | pytest 27 files flag off and flag on, scripts, live | **1,419 passed, 0 failed in BOTH modes** (the 2 long-standing verifier tests were stale after the CM Elevate Legacy guard extension and were updated); scripts **14/14**. Live: context suite **43/43 on both paths** (42/43 on both before the KI-187 fix; the failure reproduced on the pre-refactor code too); six-scheme sample **36/36 turns identical** sequential vs graph (scratchpad `g4.py`); CM Elevate OFF-009 re-test **49/49 on both paths** vs the DB (`off009.py`; first attempt 42/49 until the LIMIT 1000 case was handled); OFF-017 Piggery SGH correct on both paths (no code change); live node coverage: 21/21 nodes ran, 0 errors (`g4cov.py`). Report artifact: https://claude.ai/artifact/Q2Mb7ynLwebbjcRebHkYmq | VPN up from 19:17 IST after a drop |
| 2026-10-02 (LangGraph orchestrator, D-032) | pytest 27 files (flag off), pytest 27 files (`PIPELINE_GRAPH_ENABLED=true`), scripts | **Baseline before any change: 1,371 passed, 2 failed.** After the verbatim stage split: **1,371 passed, the same 2 failed** (behaviour-neutral). With the graph: flag off **1,398 passed, 2 failed** (+27 in the new `tests/test_pipeline_graph.py`); flag on **1,397 passed, 3 failed** (the same 2, plus `test_default_is_the_sequential_path`, which read the live flag; fixed to read the declared default, now 27/27 in both modes). Scripts **14/14**. Graph-path coverage comes from the 27 new tests only (no existing test calls `answer_question`). The 2 failures are the pre-existing verifier tests owned by the CM Elevate Legacy session (see the 2026-09-29 rows). One source-pin test moved from `_answer_data` to `_data_clarification_stage`. **OFFLINE ONLY**: live context suite and use cases NOT run on either path | VPN down (5432, 443, 6333 unreachable) |
| 2026-09-29, morning (typed reply to any chip pause, KI-181) | pytest 26 files + live | **1,371 passed, 2 failed** (+33 in `test_context_relevance_and_contract.py`, now 177; the same 2 verifier tests owned by the parallel CM Elevate Legacy session, see the row below). Scripts **14/14**; live context suite **43/43** (follow-up 29/29); live replay: measure gap -> "houses sanctioned" (106,527) / "the second one" (410,200 households) / "houses completed in west garo hills" (stays PMAY-G), Focus Plus year-out-of-range -> "2022-23", Sericulture -> "weaving", Garo Hills region -> "west garo hills" (5,489,616) | VPN up |
| 2026-09-29, early morning ("give me for pmay" scheme swap + measure gap, KI-180) | pytest 26 files + live | **1,338 passed, 2 failed** (+26 in `test_context_relevance_and_contract.py`, now 144). The 2 failures (`test_verifier_district_complaint_beside_village_code_is_discarded`, `test_verifier_complaint_on_correct_village_sql_is_discarded`) pin `_verifier_village_code_complaint_is_false` OUTSIDE CM Elevate Legacy; a parallel CM Elevate Legacy session widened that gate while this session ran — not caused by KI-180, left to that session. Scripts **14/14**; live context suite **43/43** (follow-up 29/29); live replay (scratchpad `119975e8-…/scratchpad/live_convo.py`): reported pair, "give me for pmay please", PMAY-G houses -> "give me for mgnrega", money swap (EKH ₹221.26 cr, unchanged), "tell me about pmay" still KNOWLEDGE, chip 106,527 houses | VPN up |
| 2026-09-29, night (Focus Legacy all blocks / villages / ACs / PGs, KI-020 + KI-145..165) | pytest 26 files + live | **1,265 passed**; scripts **14/14**; live context suite **43/43** (follow-up 29/29); use cases **28/28 on 3 of 3 runs** (final code, month names now checked); bulk **32,560/32,560** (56 blocks x3 + 12 district breakdowns, 55 ACs x3, 3,384 villages x2, 11,906 PGs x2, 1,635 older raw spellings) on the latest run of each question, with a final-code regression pass of 5,215 (all block/AC questions, every question that ever failed, 4,300 random) 5,214/5,215 then 5/5 after KI-165. Harness: scratchpad `2ca0226e-…/scratchpad/bulk` (`gen_bulk.py`, `bulk_run.py`, `bulk_judge.py`), `build_bulk_report.py` | VPN up |
| 2026-09-29, later (reported "what is focus" conversation, KI-136 to KI-144; VPN up) | pytest 26 files + live | **1,185 passed** (+22 in `test_context_relevance_and_contract.py`, now 118); scripts **14/14**; live context suite **43/43** (follow-up 29/29, SQL 20/20; turn p50 1.70 s / p95 3.12 s; rewrite p50 162 ms); live battery (scratchpad `live_convo.py`, `battery.sh`, `battery2.sh`): S1 substitution / unrelated / personal, S2 geography-metric-reference, S3 WHK, S4 five thousand (₹46.64 cr + not-a-loan line), S4b not-held, S5 Songsak search + block/village, S6 the reported conversation, S7 knowledge-then-place, S8 digression keeps MGNREGA — all correct, each figure read against its SQL. S8 failed once (KI-144), was fixed and re-run | VPN up |
| 2026-09-29 (context relevance + semantic contract, KI-030/032/034, KI-130 to KI-135) | pytest, 26 files | **1,163 passed** (1,067 + 96 in `test_context_relevance_and_contract.py`); scripts **14/14**. **OFFLINE ONLY**: `10.48.242.4` unreachable (5432 and 443), so `tests/live_context_validation.py` and every live check were NOT run. Reproduced before the fix with the real `_run_pipeline` (model/RAG/DATA stubbed): 4 of the reported turns misrouted | DB and gateway unreachable |
| 2026-09-28 (CM Elevate all districts / blocks / villages, KI-106 to KI-120) | live bulk | **7,364 / 7,364** on the final code (round 1 4,132/4,208); pytest **1,053**; context suite 43/43 | 7,364 questions; DB = raw; run passes one at a time, DB_POOL_MAX_SIZE ≤ 14; VPN dropped once (runner waits) |
| 2026-09-27 (calendar date read as FY, KI-078) | pytest, 24 files | **915 passed** (+18 in `test_calendar_date_filter.py`); scripts **14/14**; live context suite **43/43** (follow-up 29/29, SQL 20/20); live probes 4/4 (2017-11-28 and 28/11/2017 → 504, 2017-18 → 15,513, undated still asks scope) | VPN up |
| 2026-09-27 (MGNREGA women share, KI-077) | pytest, 23 files | **897 passed** (+6 in `test_mgnrega_usecase_fixes.py`, now 84); scripts **14/14**; live context suite **43/43**; live women checks 8/8 (EKH 77.70% FY 2024-25, 74.90% FY 2022-23..2024-25, FY 2025-26 "not recorded") | VPN up |
| 2026-09-27 (CM Elevate use-case fixes, KI-068 to KI-075) | pytest, 23 files | **891 passed** (858 + 33 in `test_cmelevate_usecase_fixes.py`); scripts **14/14**; live context suite **43/43** (follow-up 29/29, SQL 20/20); CM Elevate use cases: **55/55 questions on 2 of 2 fresh live runs (30/30 use cases)**, each figure checked against megh_db and the raw workbook; 11 reworded probe questions: 10 correct, 1 pre-existing intent flake (KI-076) | VPN up for the final runs |
| 2026-09-27 (CM Elevate use-case QA round 1, before the fixes) | live use cases | **23/30 use cases, 47/55 questions**, identical on 2 fresh live runs; each figure checked against megh_db `v_cm_elevate` and the raw `CM_Elevate_AllSchemes_20260927_full.xlsx` (DB = raw exactly). Failures KI-068 to KI-073; KI-074 needs a product decision. pytest and scripts not re-run (no code changed) | VPN flapped; runs were restarted after a drop. Harness in the session scratchpad; the method is on the report's Summary sheet |
| 2026-09-28 (PMAY-G extra information removed, KI-128) | pytest, 25 files | **1,065 passed** (+6 in `test_pmay_usecase_fixes.py`, 2 older ones updated to the trimmed lists); live: 2,129-question random sample of the full scenario set + 21 Sep inputs **2,129/2,129**, use cases **71/71**, follow-ups **18/18** | VPN up |
| 2026-09-28 (PMAY-G 21 Sep tester sheet recheck, KI-125) | pytest, 25 files | **1,055 passed** (incl. 2 new bare-year tests); live: 192/192 (21 Sep inputs: GABIL SONGGITCHAM breakdown + partial, KYNDONGTUBER, LASKEIN count + breakdowns, 12 districts x beneficiaries / financial summary / performance / 7 FYs, 63 dates) and use cases 71/71 (a first attempt lost 38 to a VPN drop and was re-run clean) | VPN flapping |
| 2026-09-28 (PMAY-G full scenario test, KI-099 to KI-105) | pytest, 25 files | **1,005 passed** (`test_pmay_usecase_fixes.py` now 65); scripts **14/14**; live context suite **43/43**; PMAY-G full scenario matrix **17,331/17,331** (first pass 17,297 — 34 failures diagnosed, fixed, re-run 34/34, then the whole matrix re-run; the 571 model-reachable questions re-run again after KI-105): every village × 3 phrasings, every block / district / state × 16 question types, every block / district × every FY, 63 dates, 99 comparisons, 110 model-path questions; follow-up conversations **18/18**; use cases **71/71**; Focus Plus 300/300 and MGNREGA 300/300 villages. Report `docs/PMAY_G_Full_Scenario_Test_Report_2026-09-28.xlsx`. Harness: scratchpad gen_all.py, bulk_run.py, bulk_judge.py, gen_mt.py, run_mt.py, build_all.py | VPN dropped twice (runner paused / 3 re-runs) |
| 2026-09-28 (PMAY-G village named beside its block, KI-098) | pytest, 25 files | **998 passed** (+5 in `test_pmay_usecase_fixes.py`, now 58); live: all 5,120 villages asked with their ", <BLOCK> block, <DISTRICT>" tail **5,120/5,120**; all 224 block questions **224/224**; 500 random bare-name villages **500/500**; 71 use-case questions **71/71**; offline: 0 of 448 block phrasings read as a village | VPN up |
| 2026-09-28 (PMAY-G use-case + all-blocks/all-villages fixes, KI-089 to KI-097) | pytest, 25 files | **993 passed** (+53 in `test_pmay_usecase_fixes.py`; 4 older tests that pinned PMAY-G outside the village gate or the out-of-area check were updated with the reason); scripts **14/14**; live context suite **43/43** (follow-up 29/29, SQL 20/20); PMAY-G use cases **28/28** (71/71 questions on 2 of 2 fresh live runs, identical answers; round 1 was 17/28); all blocks **224/224**; all villages **5,120/5,120** on the final code (round 1 4,393/5,120 → KI-096 fixed); Focus Plus regression 60/60 blocks + 300/300 villages; MGNREGA regression 60/60 blocks + 300/300 villages; 16 model-path probes correct | VPN up |
| 2026-09-28 (KI-025 database-outage handling) | pytest, 24 files | **939 passed** (+3 in `test_focusplus_usecase_fixes.py`); scripts **14/14**; live context suite **43/43**; live outage simulation (megh_db port unreachable) → `DatabaseUnavailableError`, no KB answer, no repairs; live regression 204/204 blocks + 200/200 random villages | VPN up |
| 2026-09-27 night (Focus Plus all blocks / all villages, KI-079 to KI-088) | pytest, 24 files | **936 passed**; scripts **14/14**; live context suite **43/43** (follow-up 29/29); bulk live run on the final code: **204/204 block + 7,026/7,026 village questions** against megh_db and the raw CSV (8 re-run on final code, 3/3); confirmation pass 204/204 + 1,000/1,000 random villages; MGNREGA regression 448/448 blocks + 300/300 villages | VPN flapping, runner paused and resumed |
| 2026-09-27 (Focus Plus use-case fixes, KI-060 to KI-067) | pytest, 22 files | **858 passed** (826 + 32 in `test_focusplus_usecase_fixes.py`); scripts **14/14**; live context suite **43/43** (follow-up 29/29); Focus Plus use cases: **39/39 questions on 2 of 2 fresh live runs (30/30 use cases)**, each figure checked against megh_db and the raw CSV; typed bank-pause flow checked live through three pauses | VPN up (dropped once mid-session, retried) |
| 2026-09-26 night (MGNREGA all blocks / all villages, KI-049 to KI-059) | pytest, 21 files | **826 passed** (748 + 78 in `test_mgnrega_usecase_fixes.py`); scripts **14/14**; live context suite **43/43** (one earlier run was 40/43, with scenario D failing on a DB-sync outage; D alone and the full suite re-run clean); bulk live run on the final code: **448/448 block + 12,850/12,850 village queries** against megh_db and the raw CSVs | VPN flapping, retried |
| 2026-09-26 (MGNREGA use-case fixes, KI-041 to KI-048) | pytest, 21 files | **789 passed** (748 + 41 in `test_mgnrega_usecase_fixes.py`); scripts **14/14**; live context suite **43/43** (follow-up 29/29, SQL 20/20); MGNREGA use cases: **43/43 queries on 2 of 2 fresh live runs (30/30 use cases)**, each figure checked against megh_db and the raw CSVs | VPN up |
| 2026-09-26 (scheme substitution, KI-039) | pytest, 20 files | **748 passed** (657 + 91 in `test_scheme_substitution.py`); scripts **14/14**; live context suite **43/43**; live substitution run: the reported conversation plus 6 scheme pairs and 3 negatives, all correct | VPN up |
| 2026-09-26 (context validation) | live end-to-end, 16 conversations / 53 turns (brief groups A–F, plus clarification, scheme switching, contamination, long answer, 8-turn) | **47 PASS, 1 PASS with a caveat, 5 FAIL**. Findings KI-032 to KI-038; report `docs/Context_Validation_Report_2026-09-26.md` | VPN up, no code changes |
| 2026-09-26 (after live fixes) | pytest, 19 files | **657 passed**, 0 failed (`test_context_hardening.py` now 61) | VPN up |
| 2026-09-26 (after live fixes) | plain scripts, 14 files | **14/14 exit 0** | VPN up |
| 2026-09-26 (context hardening) | pytest, 19 files | **649 passed**, 0 failed (596 + 53 new in `test_context_hardening.py`) | DB unreachable |
| 2026-09-26 (context hardening) | plain scripts, 14 files | **14/14 exit 0** | DB unreachable |
| 2026-09-26 (context hardening) | `tests/live_context_validation.py` (VPN up) | **43/43 checks**, follow-up resolution 29/29, SQL 20/20, turns across 3 workers via real Postgres; repeated twice | live gateway and DB |
| 2026-09-26 (context hardening) | `tests/live_context_validation.py --legacy` | 39/43, follow-up 25/29, SQL 18/18 | live A/B baseline |
| 2026-09-26 (context layer) | pytest, 18 files | **596 passed**, 0 failed (558 + 38 new in `test_context_semantic_state.py`) | DB unreachable |
| 2026-09-26 (context layer) | plain scripts, 14 files | **14/14** | DB unreachable |
| 2026-09-26 | pytest, 17 files | **558 passed**, 0 failed, 1 warning (Pydantic class-based `Config` deprecation) in 24.6 s | DB unreachable |
| 2026-09-26 | plain scripts, 14 files | **14/14 exit 0** | DB unreachable |
| 2026-09-26 | `pytest tests` (whole dir) | **INTERNALERROR** (`SystemExit` from a script at import), 214 s | KI-018 |
| 2026-09-24 | pytest, 16 files | 423 passed (TECHNICAL_BRIEF) | before later additions |

### Live A/B (2026-09-26)

| Metric (live, 2026-09-26, same 8 scenarios, one run each) | Legacy (pre-context work) | New |
|---|---|---|
| Checks passed | 39/43 | **43/43** |
| Follow-up resolution checks | 25/29 | **29/29** |
| SQL executed without the fallback | 18/18 | 20/20 (two more turns reached SQL) |
| Rewrite prompt, approximate tokens, mean / max | 236 / 279 | 217 / 240 |
| Classifier input tokens, gateway mean | 925 | 870 |
| SQL-generation input tokens, gateway mean | 10,196 | 10,280 |
| Rewrite stage p50 / p95 | 141 / 898 ms | 154 / 638 ms |
| SQL generation p50 / p95 | 715 / 1,010 ms | 728 / 998 ms |
| Whole turn p50 / p95 (excluding the DB sync) | 2,155 / 3,297 ms | 2,335 / 3,886 ms |
| DB `sync_in` p50 / p95 | 52 / 105 ms | 52 / 359 ms |
| DB `sync_out` p50 / p95 | 55 / 128 ms | 50 / 153 ms |

- The new run was repeated: two runs gave 43/43 both times.
- Legacy fails scenario A, T3: "How many beneficiaries were there?" was not treated as a
  follow-up, so it got a year pause and lost the Dalu / FY scope. It also fails one structural
  check in D.
- Turn latency is not an apples-to-apples comparison: the new run answered 2 more data turns,
  whose full SQL chains the legacy run never reached.
- The DB sync ran in both modes. The A/B isolates the context logic, and the old per-worker
  behaviour is covered offline.
- TTFT is not observable, because generation is not streamed.
- The SQL prompt measured by the gateway is about 10.2k tokens, including LIVE SCHEMA and the
  catalogue. The offline estimate of 3.0k–6.9k excludes those blocks.

## 4. Test → component map

**The numbers in brackets below are collected pytest cases** (`pytest --collect-only`,
2026-09-26). Many tests are parametrised, so the 21 files hold 382 `def test_` functions but 826
cases. Per file:
- `ac_flow_focus_legacy` 16, `ac_focus_legacy` 18, `asr_transcribe` 54, `cm_elevate_legacy` 83;
- `context_semantic_state` 38, `context_hardening` 61, `scheme_substitution` 91;
- `fewshot_ranking` 20, `focus_legacy_routing` 44, `focus_legacy_usecase_fixes` 42, `mgnrega_usecase_fixes` 84;
- `followup_scheme_scope` 8, `lookup_intent` 19, `pg_abbreviation` 22, `pg_name_lookup` 15;
- `rag_general_scoping` 38, `scheme_pick` 46, `scheme_recommendation` 70;
- `stale_clarification` 31, `year_gap_comparison` 17, `year_gap_tolerance` 15.


| Test file | Style (cases) | Protects | Component(s) |
|---|---|---|---|
| `test_security.py` | script | headers, body/field limits, endpoint gating, login throttle, error hygiene, secret guard | middleware, routers, main |
| `test_pmay_usecase_fixes.py` | pytest (53) | PMAY-G use-case + all-villages fixes (KI-089 to KI-097): facts-path shape detection and answers (exact ₹, differences, stages), model-path guards (year GROUP BY, AVG rates, LIMIT 1), house-status 'sanctioned' phrase, written dates, typo / plural blocks, village narrowing, stated zeros | pipeline `_pmay_*`, entity_resolver `resolve_house_status`, premise_check |
| `test_asr_transcribe.py` | pytest (54) | voice input format/lang/no-speech/prompt-echo | routers/query, llm.call_asr, asr_guard, web |
| `test_context_manager.py` | script | reference substitution, state carry, summary, memory | context_manager, conversation_memory |
| `test_context_relevance_and_contract.py` | pytest (177) | the 2026-09-29 conversation: request-verb scheme swaps ("give me for pmay") and the swap measure-gap pause (KI-180); typed replies to every chip pause (`_resume_option_pause`, `_paused_thread_antecedent`, router `remember_pause`, KI-181); unrelated messages ("who is harshit") and personal money requests do not inherit the scheme; real follow-ups keep a continuation signal; substitution for every registry scheme; bare "which one?" asks; WHK near-miss chips; Focus Plus stated amount (parse, guard, not-held pause, not-a-loan note); `_resolved_scope_missing` rejects K8-shaped SQL and does not over-validate (all years, CM Elevate, village, region, LIKE, apostrophe, date range); village name search (DB stubbed); KI-032 state clears; KI-030 all-years carried and persisted; the three-turn West Garo Hills → Dalu → beneficiaries plan; `pipeline_decision` log has labels, not text | context_policy, edge, entity_resolver, premise_check, pipeline, context_manager, session_store, context_budget |
| `test_scheme_substitution.py` | pytest (91) | "give me same / do the same / now for <scheme>" keeps the previous operation for every registry scheme; the rewrite swaps only the scheme (metric, geography, year, grouped, result-reference shapes); negatives (grouping/time/geography changes, informational, comparison) are untouched; never cached; 7th-scheme agnostic | pipeline `_scheme_substitution` / `is_scheme_substitution` / `_scheme_swap_rewrite`, context_policy, router |
| `test_context_hardening.py` | pytest (61) | cross-worker state A→B→C (KI-028/KI-001) incl. stale-write refusal, DB-down/slow-DB degradation, pending pause across workers; merge actions KEEP/REPLACE/CLEAR/REQUIRE_CLARIFICATION and what they drop from `prior_resolved`; follow-up kinds → layers; provenance sources; field-specific rewrite checks (year, metric, category, village names); 7th-scheme agnosticism; priority-aware SQL budget; per-call usage record | session_sync, session_store, context_policy, context_manager, pipeline, prompt_builder, context_budget, llm, router helpers |
| `live_context_validation.py` | **live script, not pytest** | scenarios A–G against the real gateway and DB, turns rotated across 3 workers through real Postgres; per-turn rewrite/state/SQL/answer/tiers; per-role tokens and p50/p95 latency; `--legacy` A/B | whole pipeline |
| `test_context_semantic_state.py` | pytest (38) | follow-up rewrite evidence tiers (no `answer[:300]`), provenance guard, scheme isolation for all 6 schemes, failed-turn state safety, typed scheme-pause resume, pause replies never cached, `prompt_context` logging, backward compatibility | context_manager, pipeline `rewrite_followup` / `_resume_scheme_pause`, prompt_builder, context_budget, router |
| `test_history_charts.py` | script | reopened chats redraw charts (`response` JSONB) | conversation_store, web |
| `test_stale_clarification.py` | pytest (31) | a new question is not merged into a stale pause; PG names are not geography | `_reply_abandons_scope_pause`, `_drop_producer_group_names` |
| `test_edge_conversational.py` | script | meta/conversational handling | edge |
| `test_lookup_intent.py` | pytest (19) | "is there any X named Y" → DATA | classify_intent, `_DATA_HINTS` |
| `test_followup_scheme_scope.py` | pytest (8) | follow-ups that switch scheme | looks_like_followup, rewrite |
| `test_scheme_pick.py`, `test_scheme_recommendation.py` | pytest (46, 70) | pick/recommend/why/fit, harmful-first ordering | pipeline step f |
| `test_rag_general_scoping.py` | pytest (38) | KB scheme scoping; no lost clarification pause; stale collection | `_run_pipeline` KNOWLEDGE, rag, kb_ingest |
| `test_fewshot_ranking.py` | pytest (20) | breakdown questions retrieve right-shaped exemplars | annotations IDF ranking |
| `test_verifier_missing_geo.py` | script | verifier false "missing geography" suppressed | `_verify_sql` filters |
| `test_cmelevate_usecase_fixes.py` | pytest (33) | CM Elevate use-case fixes KI-068 to KI-075: the Unresolved filter off programme totals; complete programme lists; the multi-programme split and combined total; pending at a level vs a plain pending; zero-count sectors kept; comparison differences; garbled two-label answers rebuilt; the file_status reading of pending; approved/rejected on file_status; the verifier scheme_specific false complaint; PRIME SEED routing | _cm_legacy_keep_unresolved_off_village, _cm_elevate_* SQL guards, _cme_* guarantees, _verifier_scheme_specific_complaint_is_false, _infer_scheme_from_terms |
| `test_focusplus_usecase_fixes.py` | pytest (56) | Focus Plus use-case fixes KI-060 to KI-067: shares (breakdown and recount-verified single count), comparison difference / higher side, complete named lists, rupee formatting, mis-grouped digits, SQL-literal numbers, bank-pause chips + typed resume, Focus Legacy bank KeyError, batch/tranche scope, resumed question remembered on a second pause; all-villages fixes: village narrowing, WHERE pin (place literals, subquery), twin-village LGD chips, district-alias collision, Nan block, BURMA, one-figure misquote, roman numerals | compose_response, _focusplus_answer_guarantees, _bank_clarification, _resume_scheme_pause, _needs_scope_clarification, _run_pipeline, router pause_question |
| `test_mgnrega_usecase_fixes.py` | pytest (84) | MGNREGA use-case fixes KI-041 to KI-048: block chip, SOUTH TURA, scheme vocabulary, integer division, village lists, comparisons, deterministic spend + person-days and admin queries, 100-days faithfulness, top-1 wording, lakh units | resolve_entities, _infer_scheme_from_terms, execute_with_repair, _answer_data, compose_response |
| `test_calendar_date_filter.py` | pytest (18) | KI-078: a calendar date (2017-11-28, 28/11/2017) is not back-filled as an FY, yields no premise figures, and satisfies the scope gate; real FY ranges, premises and the undated scope pause unchanged | _backfill_explicit_year, premise_check.extract_premises, _needs_scope_clarification |
| `test_mgnrega_split_facts.py` | script | employment and expenditure never joined; split-fact hint | execute_with_repair guards |
| `test_no_data_answer.py` | script | empty result → one line; typos don't cause it | compose_response, `_no_data_answer` |
| `test_cross_scheme_money.py` | script | "which scheme paid most" is deterministic across schemes | `_cross_scheme_money_answer` |
| `test_cross_scheme_collision.py`, `test_admin_level_collision.py` | script | block/village/AC level-collision chips per scheme | entity_resolver, gates |
| `test_block_backstop.py`, `test_block_parent_district.py` | script | named blocks survive extraction; a block is scoped to its own district | resolve_entities |
| `test_ac_full_results.py`, `test_ac_focus_legacy.py`, `test_ac_flow_focus_legacy.py` | script / pytest (18, 16) | AC questions return all rows; AC flow end to end for Focus Legacy | entity_resolver, prompt_builder, `_AC_CAPABLE_SCHEMES` |
| `test_focusplus_block_columns.py` | script | Focus Plus blocks use `block_name_raw` | prompt_builder entities block |
| `test_focus_legacy_routing.py` | pytest (44) | Focus Legacy wiring and scoping | scheme registries |
| `test_focus_legacy_usecase_fixes.py` | pytest (122) | the 2026-09-25 QA fixes (group size, list totals, verifier guards, overview retrieval); 2026-09-29 all-levels fixes KI-020, KI-145..165 (breakdowns from rows, month / rupee format, AC scheme routing and drill-down, PG-name parsing / older spellings / edge masking, village phrase, twins, chip pin, DATE_TRUNC cast) | pipeline, edge, entity_resolver (Focus Legacy) |
| `test_pg_name_lookup.py`, `test_pg_abbreviation.py` | pytest (15, 22) | PG name matching and suffix stripping; NULL-row answers; "PG" recognised | schema_context rule 5a, compose_response, edge |
| `test_year_gap_tolerance.py`, `test_year_gap_comparison.py` | pytest (15, 17) | absent year + valid year answered; comparisons substitute | `_apply_year_gap` |
| `test_conversation_layer.py` | pytest (69) | D-043: reset phrasing and clearing (state, turns, pause, topics, paused run), idle expiry (and 0 / unknown age), plain-words return, measure after knowledge (KI-222) incl. inside a return, snapshot carries topics / age, router: reset answered without pipeline or caches, rewritten turns never cached | conversation_layer, topic_memory, session_store, routers/query |
| `test_topic_memory.py` | pytest (38) | topic records per scheme, switch / return / unnamed-return pause, isolation between topics | topic_memory |
| `test_context_ui_fixes_2026_10_18.py` | pytest (37) | KI-308 / KI-309: "what is the total …" after a data answer is a measure follow-up and never a term question; same scheme + measure stays a follow-up; manrega / manraya -> MGNREGA; spoken digit years; verifier may not remove a resolved place filter | c01, c02, c11 |
| `test_cache_hit_context.py` | pytest (3) | KI-319: a cache-served answer updates the structured state, files with its scope, keeps the idle chip, carries the banner (real `router._answer`, pipeline forbidden) | routers/query |
| `test_session_sync_retry.py` | pytest (3) | KI-314: a snapshot load / save that fails once is retried; two failures give up quietly | session_sync |
| `test_stop_continue.py` | pytest (35) | D-050: stop / continue word lists, "continue" runs the stopped question once (never cached), any other message or a 30-min age drops it, snapshot round trip, "stop" with nothing running, a cancelled stream remembers its question | conversation_layer, routers/query, session_store |
| `test_topic_ledger.py` | pytest (77) | D-050 / KI-307: per-topic question ledger (filing, cap, number kept, snapshot), going back by content / order / Hinglish / with a follow-up, ask with chips + chip reply, ordinary questions untouched, off switch, "what did we discuss?", never cached | topic_memory, routers/query |
| `test_query_stream.py` | pytest (14) | D-039: `llm.stream_model` SSE parsing and token events; composer streams only with a live client, falls back to the plain call, never hides `ModelBusyError`; graph nodes emit `step` in order; `/api/query/stream` framing, error status, Stop cancels the turn; `skip_cache` bypasses and refreshes the caches | turn_events, llm, pipeline_graph, routers/query |
| `test_cm_elevate_legacy.py` | pytest (83) | CM Elevate Legacy wiring, pinning, not-held, exact totals | pipeline (CM Legacy), schema_context |

## 5. Coverage by requested category

| Category | Status |
|---|---|
| Unit | Yes, extensively. Most tests call single functions |
| Integration (stubbed LLM, in-process pipeline) | Partial. Several suites drive `answer_question` with stubbed model calls |
| End-to-end (live server) | Only `smoke_restructure.py`, which needs a running server; not part of the routine run |
| SQL correctness vs DB | **None automated.** Guards are tested on SQL strings only |
| Scheme tests | Focus Legacy, CM Elevate Legacy and Focus Plus blocks have suites. PMAY-G has `test_pmay_usecase_fixes.py` (2026-09-28) plus the live use-case and all-blocks / all-villages reports |
| Clarification | Yes (stale pause, collisions, year gap, follow-ups) |
| Composer | Partial. `compose_response` / `_deterministic_answer` are exercised in `test_cm_elevate_legacy.py` and `test_pg_name_lookup.py`, and no-data in `test_no_data_answer.py`. No dedicated faithfulness-guard suite |
| Security | `test_security.py`. **No test that generated SQL cannot read `app.*`** (KI-004), and no prompt-injection test |
| Regression | Every suite is regression-oriented |
| Performance / load | **None.** `docs/INFERENCE_REQUIREMENTS.md` describes a gateway load test (`hey`), run by AIOps |

## 6. Rules for new tests

- Test the **real function**. A test that re-implemented the logic under test once stayed green
  after the production branch was disabled.
- Some tests pin exact source strings (e.g. call sites in `pipeline.py`). Keep those call sites
  verbatim, or update the test deliberately.
- `_SCHEME_DATA_YEARS` is overwritten at startup by `refresh_scheme_years`. Assert against the
  values the module actually holds.
- **Live QA harness:**
  - call `pipeline.answer_question` in-process with the `.venv` Python, from the repo root;
  - click the clarification chip a user would pick;
  - the DB and gateway need the VPN.

  System Python lacks `fastembed`, so KB answers silently degrade under it.
- Test name lookups **after** a place-scoped turn. Single-turn harnesses miss follow-up rewrite
  bugs.
