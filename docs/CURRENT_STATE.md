# Current State

**Last updated:** 2026-10-30, by the PMAY-G sheet re-test session (D-096, KI-445 fixed, KI-630, KI-631; uncommitted; :8401 restarted from `.venv` 08:55). Also 2026-10-30, by the charts session (D-095, KI-624..629; uncommitted). Also 2026-10-29, by the spelling-brief session (D-093, KI-604..KI-610; uncommitted). Also 2026-10-29, by the E1 stage 2a / E2 parallel session (D-085; uncommitted). Also 2026-10-29, by the E11 UI fixes session (KI-570, D-084; frontend only, uncommitted). Also 2026-10-29, by the re-ranker session (D-083, KI-450; uncommitted). Also 2026-10-29, by the E2 guardrail fail-closed session (D-080, KI-446; uncommitted). Also 2026-10-29, by the E9 answer-formatting session (D-082, KI-447..449; uncommitted). Before that: 2026-10-27 night, by the RAG-plan handover session (D-075, KI-406/407/411/427/441; uncommitted). Before that: 2026-10-27, by the Qdrant two-collections session (D-074; uncommitted). Before that: 2026-10-24 evening, by the 1024-dim completion session (KI-402..407; uncommitted, LIVE on :8401). Before that: 2026-10-24, by the embedding switch session (D-067 gateway qwen3-embedding 1024-dim, KI-401 semantic-cache fix; uncommitted; offline + live RAG eval verified, the :8401 server NOT yet restarted). Before that: 2026-10-22 night, by the cross-scheme UAT D-066 fix session (KI-387..392; uncommitted, LIVE-VERIFIED). Before that: 2026-10-22 evening, by the CM Elevate Legacy sheet re-test + D-064 + KI-379..386 fix session (uncommitted, LIVE-VERIFIED). Before that: 2026-10-22 evening, by the answer-shape + KPI-card session (D-063, KI-377, KI-378; uncommitted, LIVE-VERIFIED). Before that: 2026-10-22 afternoon, by the cross-scheme no-template session (D-062, KI-374; uncommitted, LIVE-VERIFIED). Before that: 2026-10-22 ~13:45, by the context-memory "New Question = New Answer" session (D-061, KI-373; uncommitted, LIVE-VERIFIED). Before that: 2026-10-22 ~13:30, by the Focus Legacy sheet re-test + fix session (KI-369..371 fixed, KI-372 opened; uncommitted, LIVE-VERIFIED). Before that: 2026-10-22 ~12:00, by the ranking follow-up session (KI-366 fixed, KI-367/368 opened; uncommitted, LIVE-VERIFIED). Before that: 2026-10-22, by the Focus Plus FOCUS-019 / FOCUS-004 fix session (KI-360 / KI-361 fixed, code changed, uncommitted, LIVE-VERIFIED; see Latest). Before that: 2026-10-22, by the Focus Plus sheet re-test session (no app code changed; KI-359..365 opened). Before that: 2026-10-22 (~00:50), by the PMAY-G sheet re-test + fix session (D-060, KI-356..358). Before that: 2026-10-13 (evening), by the Cross Scheme sheet session (KI-280..290, D-044; code changed, uncommitted; LIVE-VERIFIED). Before that: 2026-10-03 (early morning), by the all-schemes all-places QA + fix session (KI-188..199, D-034; code changed, uncommitted; LIVE-VERIFIED). Before that: 2026-10-02, by the LangGraph integration session (D-032; code changed, uncommitted; **offline-verified only**, VPN down). Before that: 2026-09-29 (early morning), by the conversational scheme-swap session (KI-180; code changed, uncommitted). Before that: 2026-09-29 (late night), by the CM Elevate Legacy use-case re-test session (no code changed; KI-166..168 opened). Before that: 2026-09-29 (night), by the Focus Legacy all-levels fix session (KI-020, KI-145..165, D-031; code changed, uncommitted). Before that: 2026-09-29, by the context-relevance / semantic-contract session (code changed, uncommitted; D-030, KI-030/032/034 and KI-130 to KI-135; **offline-verified only**, VPN down). Before that: 2026-09-28 (evening), by the CM Elevate all-blocks / all-villages fix session (code changed in `app/pipeline.py`, tests; uncommitted). Before that: 2026-09-28, by the PMAY-G fix session (code changed, uncommitted; D-029, KI-089 to KI-097). Before that: 2026-09-27 night, by the Focus Plus all-blocks / all-villages session (code changed in `app/pipeline.py`, tests in `tests/test_focusplus_usecase_fixes.py` and `tests/test_mgnrega_usecase_fixes.py`; **uncommitted**). Earlier the same day: the CM Elevate use-case QA **and fix** session (code changed in `app/pipeline.py` and `app/schema_context.py`, plus a new test file; **uncommitted**). Before that, the same day: the Focus Plus use-case QA **and fix** session (code changed in `app/pipeline.py` and `app/routers/query.py`, **uncommitted**, on top of the uncommitted 2026-09-26 MGNREGA and context work). Also 2026-10-29 (evening), by the chat UI audit session (branch `fix/chat-ui-audit`, D-088 / D-089, KI-574), and lane A2 (context, PR #20); both merged from Main (PRs #20, #21) into update/2026-10-29.
**Also 2026-10-30:** the Focus + / CM Elevate Legacy sheet re-test (renumbered KI-648..KI-659 on 2026-10-30 to end the clash with the charts / PMAY-G / MGNREGA sessions' KI-624..KI-635), merged from `feature/context-window-hardening`.
**Branch / commit:** `main` @ `f38ea1b` (2026-10-02 session start). Uncommitted at session start: `docs/HANDOFF.md`, `docs/KNOWN_ISSUES.md` (KI-182) and untracked QA files; the LangGraph session added the changes listed below on top, all uncommitted.

**Port: 8401 only, everywhere (user rule 2026-10-19). Start from the repo venv.**
## Latest: CMSS onboarded (2026-11-11), branch `onboard/cmss-2026-11-11`, NOT merged
- Commits: c75e594 (scheme-onboarder apply), 8bba583 (review fixes: `prompt_builder._scheme_of` CMSS, Ri Bhoi in the
  "Khasi Hills" resolver entry, 13 test files updated for a 7th scheme, CS-01..CS-12 held-out items), 3379836 (KI-686).
- VERIFIED offline: 77/79 test files as on base (test_pmay_sheet_rerun already failed before); Focus Plus files 165/165.
- VERIFIED live acceptance (`onboard test`, 86 items, 78.3%): MGNREGA 100, PMAY-G 92.3, Focus Plus 91.7, CM Elevate Legacy 91.7,
  Focus Legacy 83.3, CMSS 66.7 (8/12), CM Elevate 0 (KI-684, pending user decision). FP-11 regression found and fixed (KI-686);
  CL-12 flaky on base too. CMSS misses: KI-687 (one data defect, three pipeline items).
- NOT done: live multi-turn suite (`tests/live_context_validation.py`) on the branch; SME review of `data/cmss/scheme.yaml`
  answers and of the CS gold SQL; `npm run build` output review in the UI.
## Latest: scheme onboarding tool (2026-11-05/06, D-102, KI-683). No app code changed in this repo; docs only.
- New tool outside this repo: `C:\Users\dell\Desktop\MEGH-LANG\scheme-onboarder` (own git repo, README).
  - It learns the schemes and finds every per-scheme registry by itself (186 in 40+ files).
  - It derives a new scheme's entries or drafts them with the project gateway, checking every value, including
    SQL on megh_db.
  - It refuses incomplete plans and applies to a new branch only.
  - It tests with the project's suites (new failures vs the original branch) and `tests/nl2sql_eval`.
  - `docs/SCHEMES.md §Adding a scheme` now starts from it.
- VERIFIED:
  - tool tests 27/27 (incl. an end-to-end onboarding with rollback on a synthetic project);
  - leave-one-out on the 6 schemes;
  - live check, drafting and acceptance (Focus Plus 11/12) on 2026-11-06.
- FOUND: KI-683 (FP-05 Focus Plus blocks of North Garo Hills, 6 rows vs gold 4) — open.
- Later on 2026-11-06:
  - `onboard run` added: the whole flow, stopping only where a person is needed.
  - `init` pre-fills `scheme.yaml`.
  - `apply` rolls back on new test failures and holds entries that would break a fixed unpack, such as
    `routers/stats.py::_cards`.
  - Edits keep each file's line endings (a bug found on a CRLF clone: JS offsets were shifted).
  - The frontend build is verified on a clone.
  - Tool tests: 35/35. Leave-one-out: 89 exact.
- QDRANT (2026-11-06, live, read-only):
  - The tool reads each scheme's points in `megh_sql_metadata` (examples / views / joins) and
    `megh_knowledge`.
  - VERIFIED: the field names match the app's reader (`app/sql_examples.py`, `app/vectorstore.py`).
  - Both collections ALREADY hold three schemes that are not onboarded:
    | Scheme | Examples | Views | Joins | Knowledge pieces |
    |---|---|---|---|---|
    | CMSS | 26 | `curated.v_cmss` | 8 | 44 |
    | Home Stay | 34 | `curated.v_homestay_api` | 8 | 39 |
    | Home Stay Legacy | 30 | `curated.v_homestay_legacy` | 8 | 39 |
  - Trial in a clone: `init --live --name CMSS` filled 8 of 13 manifest fields (main view, grain and owned
    tables from Qdrant) and wrote a 26-example few-shot file from Qdrant. All 26 SQL examples ran read-only
    on megh_db. What the SME still has to supply: the resolver / rules / partitions YAMLs.
  - The app reads `megh_sql_metadata` only with `SQL_EXAMPLES_SOURCE=qdrant`; `.env` says `yaml`.
- BASELINE DONE (2026-11-06, VPN, commit 09ac437): 74 held-out questions, accuracy 81.7%.
  MGNREGA 100%, CM Elevate Legacy 100%, PMAY-G 92.3%, Focus Plus 91.7%, Focus Legacy 83.3%, CM Elevate 0%
  (9 dataset pauses, KI-684). Other misses: KI-683, KI-685. Saved in the tool's
  `reports/acceptance/2026-11-06_1542_09ac437.json`; later onboardings are compared against it.
- Found by the scan, not fixed here (pre-existing drift):
  - edge `_RESPONSES["profanity"]` and `translate.py` name 5 schemes;
  - `config.APP_NAME` names 4.

## Latest: overall Focus Plus summary — wrong "~3%" cohort share, glued scope sentence (2026-11-05, KI-682). Code changed, uncommitted; LIVE-VERIFIED in-process. :8401 NOT restarted.
- "~3% of beneficiaries" was hard-coded (it is 3% of payment records); now computed from the query: 12,527 of 1,05,813
  beneficiaries, ~11.8%. The answer ends with its own scope line, so c12 `_finish_answer` no longer glues one to the last bullet.
- `app/pipeline/schemes/focus_plus.py` only; `tests/test_focusplus_usecase_fixes.py` +1, file 94/94; namespace guard passes.

## Latest: "overall Focus Plus summary" answered from the documents (2026-11-04, KI-681). Code changed, uncommitted; offline-verified only (VPN down). :8401 NOT restarted.
- Cause: no intent cue matched, so the 4B decided; the D-094 prompt line (2026-10-29, "no place, no year, no count ->
  KNOWLEDGE") made it KNOWLEDGE, and the fixed summary query (checked only in the DATA stage) never ran.
- Fix: c13 `_c13_fixed_data_answer_claims` — routing asks the fixed DATA answers' own predicates before the model;
  the B3 score net and the c14 scheme-overview rule (KI-382) leave a claimed question alone. Focus Plus only.
  0 of 173 labelled routing questions change; `tests/test_focusplus_usecase_fixes.py` +27, file 93/93.
- NOT yet live-verified: the classifier was unreachable (no VPN) — see HANDOFF for the live checks.
## Latest: CM Elevate "status" = file_status (2026-11-04, D-101, KI-679, KI-680; KI-624 closed). Code changed, uncommitted; LIVE-VERIFIED in-process. :8401 NOT restarted.
- Ingestion team added a plain `curated.v_cm_elevate.file_status` (Pending / Send Back / Rejected), readable by megh_readonly.
  `cmelevate_pending_rule.yaml` points its file-status step at it; the existing gate `cme_pending_rule.readable()` opens
  when the live schema lists it. Then status questions group by file_status, pending / sent back count from it, approved /
  rejected are answered from it; current_file_status only for a movement question. Closed gate = the old wording.
- LIVE-VERIFIED in-process once the VPN was back: Umshaken Piggery "57 pending" (file_status), "rejected in Ri Bhoi" 17.
- Same day, KI-680: a count beside the pending FILTER went out over every status (Piggery 225 in West Khasi Hills) under a
  "valid only" Note; the FILTER's own 'Valid' had switched the default off. Now 197 valid (+ Note); "all applications" 225, no Note.

## Latest: CM Elevate dataset chip answered from the documents / Piggery filter lost (2026-11-04, KI-677, KI-678). Code changed, uncommitted; LIVE-VERIFIED in-process. :8401 NOT restarted.
- "What is the status of Piggery applications in Umshaken village?" -> D-099 dataset pause -> either chip went to RAG
  ("no village-level status"): `_typed_intent` (used when the rephraser touched the question) copied only part of
  `classify_intent`'s cues. Both now read c13 `_c13_intent_by_cues`.
- Then the CM Elevate chip said 63 (every scheme in the village): the village pin dropped the bracketed WHERE group that
  the valid default creates, `scheme_name` with it. The pin now opens bracketed AND groups. Now 57 (= megh_db).
- Full pytest 5,404 passed / 1 failed (pre-existing BLH8); scripts 14/14.

## Latest: context frames — whole-window context (2026-11-03/04, D-100, KI-671..674). Code changed, uncommitted; LIVE-VERIFIED in-process. :8401 NOT restarted.
- User chat: Focus Plus total -> district-wise -> "compare this with … Focus Legacy" (was statewide) -> "include focus
  plus also" (was the documents) -> "i mean compare focus plus also" (was Focus Plus alone). Now all three give the
  district-wise Focus Plus vs Focus Legacy comparison; the bare "Focus" turn still asks which (CLAUDE.md §4).
- How (`app/context_frames.py`): a frame per answered turn, the whole window in the snapshot (it held only the last
  turn before, KI-674); where the existing path loses context — the `comparison_with_earlier` branch, a give-up of
  `rewrite_followup`, a follow-up no gate caught — one 9B guided-JSON call continues the latest ANSWERED figure
  (asides / pauses skipped) and deterministic checks (existing readers, no word lists) refuse any loss or invented
  name; any skip / failure -> the old path. The precise rules (swaps, figure reference, measure change …) stay first.
- Rollback: `CONTEXT_FRAMES_ENABLED=false`. Tests: NEW `tests/test_context_frames_2026_11_03.py` (24); live harness
  144/159, the 15 failures identical with the frames off (stale expectations, mostly CM Elevate vs D-099).
- :8401 runs on SYSTEM Python (PID 12828 on 11-03), not `.venv`: restart it from `.venv` to serve this and the RAG
  embedding path correctly.

## Latest: fallback list reads grouped (2026-11-03, KI-665). Code changed, uncommitted; offline-verified only.
- The composer's deterministic fallback (`_deterministic_answer`, multi-row) no longer repeats "DISTRICT / BLOCK /" on
  every line: `_c12_grouped_lines` writes the repeated labels once as a bold header, each row under it, the LGD code
  beside the name instead of among the figures. Same rows, same 15-row cap, same values; flat list kept when grouping
  would reorder a row. Composer layer only (`c12_answer_numbers.py`); no frontend change.
- The same fallback now opens with **Key points** computed by code from every row (total, how many districts / blocks,
  where most, highest single row), then **Details** (the list). Only on the compose path's multi-row fallbacks (`sql=`).
- Cross-scheme district-wise summaries of 3+ schemes are now point-wise blocks (Summary, Total, one block per district,
  a point per scheme) instead of one wrapped `|` line per district (KI-666, `app/cross_figures.py` `_district_tables`).
- The chat no longer adds "Note: … amounts are provisional, and the money unit has not been verified by the
  department." to money answers (KI-667, user decision; the absent-year Note and the cards' "*" stay).
- An all-years answer over a scheme with a year gap now notes the years its data covers ("Note: Focus Plus data
  covers FY …", live from `_SCHEME_DATA_YEARS`) instead of naming the missing years (KI-668); a multi-scheme answer lists every scheme's years in one Note.
- **CM Elevate (D-099, KI-669):** a new chat asks "CM Elevate or CM Elevate Legacy?" (no keyword switching); the
  chosen dataset stays for the chat; a question only the other dataset holds asks "switch or stay?".
- **CM Elevate "all statuses" (KI-670):** answered with every application (8,938 live) and its verification split;
  a valid-only figure now says it is valid-only.
- Still open: the frontend bolds the code too; why the composer's own answer was rejected for BLH UAT 8 is unconfirmed (check the server log).
## Latest: context memory — BLH Bot UAT 2026-11-02 (D-098, KI-660..664). Code changed, uncommitted; LIVE-VERIFIED in-process. :8401 NOT restarted (it still serves the old code).
- UAT `BLH Bot UAT 20261102.pdf`: 4 of 10 failed, all on context. Each reproduced live on the old code first (UAT 10
  only in one long chat). Causes and the decision: DECISIONS D-098.
- Fixed, generic (no scheme names, no new word lists): typed replies to a scheme pause ("both", "all of them",
  several names, one name + scope, scope alone; never loses a typed word) — KI-660; a reference cue opens the
  follow-up rewrite (one decision with `turn_kind`) — KI-661; a figure the previous answer stated is referenceable
  (`Turn.subsets` from the SQL tree, deterministic rewrite, `subset_condition`, rows-add-up guard, PMAY-G fixed query
  refuses a stated subset) — KI-662; a vague question runs in the ACTIVE topic (amends D-061 rule 4) — KI-663.
- Live after: UAT 3 both schemes by district; UAT 4 comparison kept, no picker; UAT 8 "these 126" and the explicit
  wording 3/3 each = `is_placeholder`, 126 in 72 villages (DB truth); UAT 10 no picker, PMAY-G. Whole UAT as one chat:
  every turn right.
- Tests: NEW `tests/test_context_memory_uat_2026_11_02.py` (23); 2 tests pinning the old D-061 rule 4 updated
  (`test_new_vs_followup_2026_10_22.py`, `test_test_team_report_2026_10_29.py`); full pytest 5,341 passed / 0 failed
  after the update (first run 5,340 / 1 = that pinned test); scripts 14/14; live context suite 27/27 scenarios, 109
  checks, 0 failed; NEW harness file `tests/conversation_harness/scenarios/blh_uat_2026_11_02.yaml` 4/4 in-process.
- Open: KI-664 ("define completion rate" — documents hold no definition; content, not context); subsets of
  multi-row results; restart :8401 from `.venv`, then run the harness file over HTTP.

## Latest: Focus + / CM Elevate Legacy sheet re-test (2026-10-30, KI-648..KI-655). Code changed, uncommitted; LIVE-VERIFIED in-process (except TC-31, VPN down).
- Workbook `Test Case Results - 30th Sep 26.xlsx`, sheets "Focus +" and "CM Elevate Legacy", run live through the graph
  with megh_db truth (`tests/sheet_runs/fp_run.py`, `cl_run.py`) + 46 new permutations (`tests/sheet_runs/fpcl_perm.py`).
- Baseline: Focus Plus 145/163; Legacy 205/300 (+77 by design: bare "CM-ELEVATE applications" = applications dataset,
  user decision 2026-10-29; +10 infra); permutations 44/46.
- Fixed (each traced live, regression tests in `tests/test_fp_cl_sheet_2026_10_30.py`): "Tranch N" read as a place
  (KI-648, spelling); Focus Plus blocks — verifier "no UPPER()" false positive + un-UPPERed / lgd_block filters (KI-649);
  "across South West Garo Hills" swallowed by a fuzzy reading (KI-650); summary lines dropped the asked total disbursed
  (KI-651); "William Nagar constituency" rewritten to the block (KI-652); "how many people got Focus Plus money" ->
  amount (KI-653, rephraser + verifier); "What is it for the whole state?" -> documents (KI-654, follow-up routing).
- After, full live re-run of every case: Focus Plus **163/163**; CM Elevate Legacy 214/300 Legacy answers right + 86
  applications-dataset answers (by design) verified against `v_cm_elevate` (82 exact, 4 name-mapped); permutations
  **46/46**. With every data question naming "CM Elevate Legacy" (`CL_LEGACY_WORDING=1`): Legacy **300/300**.
  That run found KI-656 (Sericulture split on the applications dataset), fixed, TC-12 13/13 live.
  Open: KI-655 (shared DB connection caps), :8401 restart (refused by the permission classifier).

## Latest: Cross Scheme sheet re-run (2026-10-30, D-097, KI-644..647). Code changed, uncommitted; live run IN PROGRESS (`tests/sheet_runs/cross/cross_drive.sh`, see HANDOFF).
- Task (user 2026-10-30): "100% UAT in cross scheme test cases" — `reference_documents/Cross Scheme Test Cases.xlsx`
  (CROSS-1..20 + the 8,649-conversation generated set: every scheme combination, every FY, every district / block /
  constituency / village), last run 2026-10-13 on the D-044 template.
- Baseline on today's code before the fixes: **2/20** sheet questions (3 gateway timeouts; the model path dropped
  MGNREGA, gave PMAY-G's sanctioned amount, added village counts across schemes, said "24 districts" — KI-644).
- Fixed (D-097): `app/cross_figures.py` answers **all six schemes**, a village, a constituency and a block grain from
  fixed queries (CM Elevate = applications, no money / no FY said; CM Elevate Legacy = applicants sanctioned 2,820 +
  total disbursement); c13 hands the scope gaps to the plan; dataset words ("CM Elevate applicants") are not
  measures; the Tura urban body's two stored block names read as one (KI-647); an exact block name is never respelt
  (`spelling._starts_a_block`, KI-646); "widest coverage across districts" is statewide. Harness re-written
  (`grade.py`, `truth.py`, `cross_drive.sh`).
- Offline: NEW `tests/test_cross_sheet_rerun_2026_10_30.py` (18), `test_cross_figures_2026_10_22.py` +5; pinned tests
  updated on purpose (I-13 "own list", B-7 applications, the model-path parametrize, the per-year split for CM Elevate
  Legacy). Full pytest on the tree before the last three fixes: 5,230 passed, 1 failed (the updated pin).
- Live so far: sheet 138 cases 135/138 before the block / Tura / William Nagar fixes; batch 1 (733 statewide / year /
  district-wise / wording cases) 688/733 before the dataset-word and year-gap fixes; the driver re-runs every failed
  case and then every district, block, constituency and village (VPN dropped at 10:10, driver waits for it).

## Earlier: PMAY-G sheet re-test, 100% at every level (2026-10-30, D-096, KI-445 fixed, KI-630, KI-631). Code changed, uncommitted; LIVE-VERIFIED in-process and over HTTPS; :8401 restarted from `.venv` 08:55 (HTTPS, `certs/dev-*.pem`, log `logs/uvicorn-https.log`).
- Task (user 2026-10-30): every case of the PMAY-G sheet (`reference_documents/Test Case Results - 30th Sep 26.xlsx`, PMAY-OFF-001..028) live through the LangGraph pipeline with the real models and megh_db, every village / block / district / constituency, fix every failure, 100%.
- Fixed: **PMAY-G records the assembly constituency** (D-096; `v_pmay.ac_name` is dim_geography's Title Case name on every row): 'X constituency / assembly constituency / AC' is answered by the fixed PMAY-G query (dim `ac`, `UPPER(ac_name)`, one row named '<X> assembly constituency'); the model path gets a case-insensitive `ac_name` rewrite (`_pmay_ac_name_case`) and a repair when the resolved constituency is not filtered (`_pmay_ac_filter_missing`); capability registered in `scheme_registry`, c08 `_AC_CAPABLE_SCHEMES`, c13 `_CROSS_AC_RECORDED`, `entity_resolver._AC_CONTENTS_SQL`; chips keep the constituency (was: all 56 constituencies a false 0 / 'no matching records' / 'couldn't build a working query', KI-445). **Shared village names** (KI-630): `village_twins` is a fixed-query key; 2-3 same-named villages are answered one row each named with the block, never summed. **Spelling over exact village names** (KI-631): no district / block / scheme-word / domain-word rewrite touches a span that is an exact village name, and the normaliser steps over the whole span (`_starts_a_village`, `_village_span_end`, `_exact_village` over the full stored names): RONGARE ADING, Pyndeng Shallang, Centre Village, Songma Enggok, hawai bhoi.
- Behaviour change to know: a bare block name that is also a constituency (Dalu, Chokpot, Mawlai, ...) under PMAY-G now asks block or constituency (D-059), as under MGNREGA; 5 pinned tests that encoded "PMAY-G has no constituency" were updated on purpose (`test_cross_scheme_llm_2026_10_22`, `test_ac_focus_legacy`, `test_ac_flow_focus_legacy`, `test_bare_place_names_2026_10_21`, `test_mgnrega_usecase_fixes`). D-096 is from the data (every v_pmay row carries ac_name); the ingestion team has not confirmed the mapping's intent.
- Results on the final code: sheet **1,142/1,142** conversations (28 cases; before the fixes 56 constituency conversations failed), **every PMAY-G village 5,121/5,121** (before: 2 wrong + 5 spelling misses), pytest **5,208 passed, 0 failed** (documented command, 8 min 53 s), scripts **14/14**; sheet columns U..X written ("30 Oct Result / Remarks / After Fix / After Fix Remarks", `tests/sheet_runs/write_pm.py`). Held-out NL->SQL eval: see TESTING §3 (label `pmay-sheet-2026-10-30`).
- Next: the user's go-ahead for the next scheme sheet; commit by function (four sessions edit this checkout).

## Latest: charts — the chart asked is the chart given (2026-10-30, D-095, KI-624..629). Code changed, uncommitted; LIVE-VERIFIED in-process; `npm run build` done.
- Task (user 2026-10-30): "if I ask a bar / pie / line chart, give exactly that; 'compare' or 'chart' alone gives the chart; if a question has no chart, generate one".
- Fixed: a comparison (two rows; or one row of figures in one unit with a compare word) shows its tiles AND a chart; a named type is drawn alone whatever the rows, with a one-line caveat when the figures do not add up or a line joins places (was: refused and drawn as bars, D-088 / A-7; unasked defaults unchanged); "pie" on a two-dimension chart is a pie (was a donut); a single figure asked as a chart is drawn as asked, with breakdown chips in the same type; "I want only bar" / "now line" / "line please" are view requests (frontend + c15); "stacked" over several measures stacks them. `viewPlan()` (analytics.js) is the one decision Messages.jsx renders and the tests grade.
- Found by the live suite and fixed (PMAY-G, coordinated with the PMAY-G sheet session): the fixed query dropped the year-gap note (KI-628) and a two-year comparison went to the model path, which summed the years or failed (KI-629); now one row per sanction year.
- Results: requirement cases 13/28 -> 28/28; `npm test` 110/110; live `tests/live_chat_charts.py` 29/29; browser render check clean on Chromium / WebKit / Firefox, phone and desktop. :8401 (another session's server) NOT restarted: it serves the old build until restarted.

## Latest: knowledge answers and routing (2026-10-29, D-094, KI-611..618). Code changed, uncommitted; LIVE-VERIFIED in-process.
- Task: `megh_chatbot_knowledge_fix_prompt.md` (KR1-KR13). Knowledge questions were sent down the data path by single words ("How much does Focus Plus pay?" -> ₹119.74 crore; "What details are recorded when a PMAY-G beneficiary is registered?" -> house counts).
- Fixed: routing by the question's FORM (c14 `_knowledge_form_question`), MIXED rules+figures, multi-part retrieval and related facts, FAQ exact match, Hinglish retrieval, deterministic number / related-fact backstops, citations = pieces used, scheme distinctions (`scheme_registry.KNOWLEDGE_DISTINCTIONS`), FOCUS acronym, one data next-step chip after a knowledge answer. See AI_PIPELINE §4 item 7.
- Measured: live golden suite `tests/live_chat_knowledge.py` 85/108 -> **114/114 (100%)** twice; RAG eval 95.7% -> **98.4%** (final run; negatives 100%, wrong refusals 0). Remaining RAG-eval misses are gold answers that disagree with the KB or lack context (KI-618, SME review); KI-617 is a KB inconsistency for the KB team.
- Not done here: KR7 data-answer template wording (the data-accuracy session's, D-092).

## Latest: spelling brief — misspelt / variant scheme, district, block, village names (2026-10-29, D-093, KI-604..KI-610). Code changed, uncommitted; live-verified in-process; :8401 NOT restarted.
- User: `megh_chatbot_spelling_fix_prompt.md` (T1-T10, "I want to achieve 100%"). Live before: **13/25**.
- NEW `app/spelling.py` + `data/spelling_aliases.yaml` (the alias table, no code change to extend), run first in c14
  `_turn_context_stage`; `raw_question` is now the spelling-normalised text (routing, turn kind, rephrase checks).
  Districts / blocks by alias -> same sound -> few edits (from the resolver catalogue); villages by sound in
  `entity_resolver.resolve_village` before the trigram search (`_sound_village_rows`); a named place that matches
  nothing is never filled from the chat and gets "I couldn't find … Did you mean"; topic picker expires on a full
  question; "Showing results for **X** (you typed 'y')." on corrected answers. AI_PIPELINE §2.9g.
- Live after (`tests/live_chat_spelling.py`): T1-T10 **10/10 in one chat and 10/10 fresh**, negatives 3/3, context 4/4,
  misspelt knowledge **22/22**, village typos **124/124 (was 84/124, 2 wrong)**, 0 wrong places.
  Offline `tests/test_spelling_resolution_2026_10_29.py` **all pass** (12 districts x 9-11 variants 100%; block typos
  >= 95%, 0 wrong; every alias; p95 < 150 ms).
- Final tree: live `--only chat,fresh,neg,ctx` **27/27**; full pytest **4,723 passed, 0 failed**; scripts **14/14**.
  A measure-less "<scheme> in <village> village" now gets the village overview (`_c15_bare_village_ask`; T9).
- Open: :8401 needs a restart to serve this; KI-623 (bare district / block ask -> knowledge, needs a decision);
  KI-600's bare "2023" and the measure-narrowed picker (user rule) unchanged.

## Earlier: data-accuracy brief — D1-D10 and the general rules behind them (2026-10-29, D-092, KI-594..KI-603). Code changed, uncommitted; live-verified in-process; :8401 NOT yet restarted (another session's harness was running on it).
- The user's brief (`megh_chatbot_fix_prompt.md`): ten data questions with known answers, RC1-RC8. Live golden suite
  `tests/live_chat_golden.py` **45/45** (D1-D10, paraphrases, §3 probes, negatives, 13 card figures); before the fixes
  D1-D10 were **3/10**.
- NEW `app/pipeline/common/c17_data_answer_rules.py`: sub-asks, SQL hygiene + invented-answer / other-scheme guards,
  winner + next two for "which … most", money units by dataset, caveat Notes. NEW `scheme_registry.DATASETS` (cards'
  "*" reads it too). Money: "₹37,49,31,500 (≈ ₹37.49 crore)", lakh "₹25,701.49 lakh (≈ ₹257.01 crore)" (KI-449 closed).
  PMAY-G total + completed gives the breakdown that sums (1,29,941 + 41,041 + 125 = 1,71,107). One named
  CM Elevate / Legacy dataset keeps "which scheme" inside itself (D10 no longer fans out to five schemes).
  "E Khasi Hills" / "W Garo Hills" are districts, not regions; year comparisons say "FY 2022-23".
- Open for the user: KI-600 (MGNREGA SME rule asks which FY a bare "2023" is; the brief wants it mapped), KI-601
  (DEMDEMA person_days 0 every year — data), KI-602 (card "Sanction records" 2,823 vs chat "sanctioned" 2,820), KI-603
  (sub-asks run in order, not in parallel).
- Tests: NEW offline `tests/test_data_accuracy_brief_2026_10_29.py` 36/36; pinned money strings in E9 / framing /
  shapes / metric-catalogue tests moved to the D-092 format; graph stub writes Legacy SQL on its own view. Failed files
  of the full run re-run on the settled tree: all pass (the 3 RAG-grounding ones were meghoneai-63's, now fixed by it).
  Scripts 14/14. Live context 105/107 -> scenario D re-run 5/5 after the winner-row fix (T5 = the known applications
  rule). Held-out NL->SQL **68/74 (91.9%), 0 regressions** vs `2026-10-29_1952_knowledge-final2` (`2026-10-29_2003_data-accuracy-brief-2026-10-29.json`).

## Latest: RAG fix report — all 17 issues fixed (2026-10-29, D-089..D-091, KI-574..KI-591). Code changed, uncommitted; :8401 restarted 18:37 (`.venv`, HTTPS, PID 9400), live-verified.
- Source: the tester's `megh_rag_fix_report.md` (7/10, ~75 questions). User decisions (AskUserQuestion): answer with defaults, never ask place/year (D-089); "applications" = CM Elevate applications (D-090).
- Live on :8401, report questions: parity 6/6 with the cards (villages 6,491, CM Elevate 8,921, PMAY-G 1,71,107 / 1,29,941, Focus Plus 3,85,671, Focus Legacy 11,906); starters 8/8 answer; wage rate -> KB; avg wage ₹480.91 (SUM/SUM; FY 2024-25 person-days look short, KI-591, ingestion); hybrid = rules + 419 with sources; "compare both districts" = 12,038 vs 13,964; "why … lower" = reason reply; Hindi answered; schema / PII / SQL-injection refused before SQL; "Shillong Hills district" = not found + chips; CM of Meghalaya answered from the KB, Bihar refused.
- Tests: NEW `tests/test_rag_fix_report_2026_10_29.py` 57/57; frontend lint 0, JS 15/15, `web/app/` rebuilt. Full pytest 4,724 passed / 0 failed; scripts 14/14; live report suite 37/37; harness key scenarios 8/8 after the late fixes.
- Open: KI-591 (data), KI-584 model-path PMAY-G wording, the notified ₹/day wage rate is not in the KB (loading team, D-074). Old tests that pinned the asks / western grouping / the applications ask were updated (TESTING.md).

## Latest: RAG plan C1 / E8 / E3 / E6 closed (2026-10-29 night, this session). Code changed, uncommitted.
- **C1 (KI-592):** relative years ("last year", "this year", "last 3 years", "previous financial year") are
  rewritten to the FY they mean, from the scheme's own years in megh_db. Live 8/8 (was 3/8: three answered for
  all years, one failed). **KI-593:** a FY in the question is no longer read as an assumed figure.
- **E8 / KI-002:** measured on the full held-out run: 41 verifier complaints discarded by the filters, 1 kept
  (still correct), 0 wrong answers from the verifier. Mitigated; repairs bounded by D-088.
- **E3 / E6:** every listed bug fixed (KI-363/364/318, D-070, U5 = D-075; KI-313/368, C1 parser). The two
  restructures — follow-ups editing the query plan (needs QUERY_PLAN_IN_TURN, +0.35 s, same accuracy) and
  splitting `resolve_entities` — **not done by user decision 2026-10-29** (no measured failure).
- RAG plan tally (29 items): all code items done; blocked on others: A1, A3, E10, E12 (admin parts); C5 Indian
  grouping being finished by the parallel session.

## Earlier: open-bug sweep (2026-10-29, this session). Code changed, uncommitted; live-verified in-process.
- User: "fix all open bugs". 64 open -> ~22 left. Fixed / verified: KI-003, 006, 007 (security), 008, 012, 013 (D-088), 024, 026, 027, 036, 037, 290, 311, 318, 355, 359/426, 364, 365, 398, 399 (security), 400, 422, 432, 435, 436; no longer reproduce: KI-031, 313, 322, 352, 353, 354, 362, 363, 367, 372, 396, 416, 433, 434. MG-12 regression from the KI-311 prompt line found and fixed (3/3).
- Tests: this session's files 233/233; full pytest 4,254 passed / 45 failed (2 mine, fixed; 43 = the parallel session's in-progress Issue 6/13 + applications-rule changes, old tests not yet updated); scripts 14/14; live 106/107; golden 71/74 (TESTING.md).
- Left, each needs someone else: data (KI-155, 305, 385, 393 — ingestion team), security actions (KI-022 purge history, 023 rotate passwords, 200 Qdrant firewall), decisions (KI-126, 430 retention, 445, 449 money formats), other teams (KI-424, 438, 440, 450), accepted / process (KI-016, 018, 199), architecture (KI-002 verifier, 009 broad excepts, 014 shared rate limit = Redis, 038). E1 stage 2 already built by the parallel session (D-085, off by default).
## Latest: Chat UI audit fixes (2026-10-29 evening, D-088 / D-089, KI-574). Branch `fix/chat-ui-audit`, one commit per phase; NOT merged, NOT live-verified (VPN off).
- Source: *Megh One AI — Chat UI Audit (question scenarios)* (197 findings in its tables). Per-ID status, files and tests:
  `docs/audit_fix_log.md`. Totals: 189 fixed (the 12 product decisions applied as recommended, D-089), 7 already
  fixed, 1 not reproducible offline (F-9). Several need a live check (KI-574).
- Backend: `cross_figures` reads rank words at a place level (bottom / lowest / best / which district / Hinglish,
  singular and misspelt "district"), ranks one list per scheme unless "combined", returns only the ranked rows, adds
  a per-year mode for stated year spans, a union / overlap of villages, statewide column totals and what each scheme's
  figure is (`measure_notes`). `per_year_plan` keeps place, N, rank and years and asks each scheme only the measures it
  holds; `answer_many` merges into one row shape (financial_year "2023-24", money in ₹ crore). Relative periods
  ("last 3 years", "this year") are read against the years held (c06 `_relative_years`). Descending SQL sorts get
  NULLS LAST. A session held by another user is refused (403, CTX-01).
- One measure-kind rule (D-088, `app/measure_kinds.json` + frontend copy): flow / distinct / stock / rate decides
  every total, share, stack and the backend chart hint; nothing adds across schemes.
- UI: scheme × year rows keep the year; per-scheme rankings are small multiples; dependent labels are details;
  headlines and tiles in the column's unit; % gaps in points; time comparisons from the earlier year; months and
  quarters in FY order; missing years are gaps; chat switch / sign-out stop the running answer; Excel keeps years and
  codes as text; keyboard access to chips and sidebar.
- Verified offline: pytest (new + touched files) green; `frontend` node tests 72/72; `vite build` clean. ESLint not run
  (`@eslint/js` missing from `node_modules`). Full suite: see TESTING 2026-10-29 chat UI audit.
## Latest: structural data rules are checked live and alert when broken (2026-10-29, D-087 claims). Code changed, uncommitted.
- `data_facts.CLAIMS` (17) run after every 10-min refresh: WARNING log, one `ALERT_WEBHOOK_URL` POST, `/metrics` `data_facts.broken_claims`. Live: 17/17 hold.
- NOT yet running in the :8401 server: it is another session's (PID 10296, started 16:20:49, before the change at 16:24:56); stopping it was refused as interfering with that session. Its next restart picks it up.

## Latest: PMAY-G "received no release" answers the count (2026-10-29, KI-573). Code changed, uncommitted.
- `_PMAY_M["none"]` gained "releas": the question had fallen through to the statewide summary. Live: 462 statewide, 68 Ri Bhoi (= megh_db).
- :8401 is now another session's server (PID 52, started 15:53 with `certs/dev-*.pem`, after both of today's code changes); left running.

## Latest: the SQL prompt's data figures are live from megh_db (2026-10-29, D-087, KI-572). Code changed, uncommitted; :8401 restarted.
- NEW `app/data_facts.py`: 87 figures (row / NULL / distinct counts, shares, years held) read by 11 read-only SELECTs at startup and every 10 min; `schema_context` carries `[[name]]` tokens, filled by `build_schema_context` / `available_metrics_text`. `/metrics` shows `data_facts`.
- Live: 87/87 read; 11 figures were stale (CM Elevate 8,948 records / 8,921 applications, Focus Legacy 14,569 payments / 11,906 groups, …).

## Latest: scheme cards read live figures after sign-in (2026-10-29, KI-571). Frontend only, uncommitted; `web/app/` rebuilt.
- The cards asked `/api/scheme-stats` before sign-in (401) and kept the built-in 22 Oct figures for 10 min. Now they read on every sign-in and retry every 30 s while offline. Fallback figures re-synced to 29 Oct.
- :8401 runs from `.venv` over HTTPS (self-signed cert in the session scratchpad, SANs localhost / 127.0.0.1 / 10.90.211.134).
- The prompt's stale CM Elevate counts are fixed by D-087 / KI-572 (live figures). The two `cm_elevate.py` mentions of 8,867 are dated code comments (history), left as written.

## Latest: E11 UI fixes (2026-10-29, KI-570, D-084). Frontend only, uncommitted; `web/app/` rebuilt (a browser reload picks it up, no restart).
- Phones: one welcome card per page below 621 px (the `≤880px` block no longer overrides it); a figure wraps, never "…".
- Missing values: a NULL stays null in charts and compare tiles (Chart.js leaves a gap; a tile shows "—"); chart
  headlines skip gaps. Tables already showed "—" (KI-438).
- Rankings ("top", "highest", "most", …) and non-additive measures (pct, rate, avg) default to a bar; a pct offers
  only bar / line. A pie the officer names still wins.
- Compare card: two schemes are shown side by side with no "X% ahead" (each scheme measures differently); two
  districts on one measure keep the verdict.
- Stream timeout: 75 s of *silence* (every chunk, `: ping` included, restarts it), not 75 s for the whole answer.
- Admin: "Create officer" lists roles least privilege first (default `block_officer`), masked password, inline
  masked password reset (no `prompt()`), **Sign out** (visible on phones too). Chat sign-out also removes the admin
  console's token copy.
- Tooling: `cd frontend && npm run lint && npm test` (ESLint incl. the no-regex rule; `node --test`, 13 tests).
  Two unused constants (`App.jsx` `addMessages`, `Charts.jsx` `ANIM`) and a stale disable comment removed for lint.
- Verified: JS 13/13, lint 0, build clean, related pytest 90/90 + 3 scripts, device probe 16/16 (see TESTING).
  NOT verified in a browser: the welcome cards at phone width and the admin page (token minting was refused).
- Not done here (lane A2 UI-01): pct verdict in points, lower-is-better wording, no cross-scheme Total in pivots,
  " vs " chip labels.

## Latest: qwen3-reranker always on, no switch (2026-10-29, D-083, KI-450 open). LIVE-VERIFIED over HTTP; :8401 restarted (PID 3896).
- User rule: RAG always re-ranks. `qwen3-reranker` (gateway) now runs on **every** knowledge question (`rag._rerank`);
  `RERANKER_ENABLED`, `RAG_LOCAL_RERANKER` and `RAG_RERANK_CHARS` are gone, and a `.env` that sets one fails at startup.
  The local jina re-ranker is removed. `CLAUDE.md` §5 carries the rule; `tests/test_reranker_always_on_2026_10_29.py` guards it.
- The August "inverts relevance" (D-005) was our bare call: `call_reranker` now sends the Qwen3 yes/no format. Probe on
  `megh_knowledge` (137 eval questions): right piece first vector 60.2%, bare 25.6%, formatted 55.6%, **fused 62.4%**;
  top 3 82.7% -> **88.0%**; 0.1 s median. The order is fused with the vector order; `score` stays cosine (re-ranker
  scores are ~0.99 for everything, KI-450, asked AIOps).
- No hidden fallback: the 4B prompt-scoring fallback is removed; a gateway failure keeps vector order for that question
  with a WARNING; an empty / `CHANGE_ME` `RERANKER_API_KEY` logs an ERROR at startup.
- Collections unchanged: `megh_knowledge` (RAG, re-ranked) and `megh_sql_metadata` (SQL examples, not re-ranked).
- RAG eval (188 q): correct-or-honest 91.5% -> **95.7%**, wrong 3.7% -> 0.6%, honest "not covered" 91.7% -> 100%.
  Tests: full pytest 4,174 passed, 2 failed (timing; both pass alone); scripts 14/14; re-ranker files 49/49.
## Latest: E1 stage 2a — query plan built during the turn beside the guardrail call (2026-10-29, D-085). Code changed, uncommitted. Built + LIVE-MEASURED; OFF by default because it made turns slower.
- Live agreement over the shadow log (730 turns, 378 questions since 2026-10-27): intent 98.4%, schemes 95.4%,
  place level 98.5%, years 98.9%, measure 37/37, top N 10/10; plan p50 766 ms. Disagreements listed in D-085.
- `QUERY_PLAN_IN_TURN=true`: a new question's plan starts right before the guardrail model call (c14
  `_guardrail_check`), not awaited, cancelled on a refusal, reused by the end-of-turn shadow (`plan_from: "turn"`).
  `query_plan.turn_plan(session)` = the stage-2b reader (unused).
- Live A/B (VPN, in-process, 6 own questions x on/off): answers identical, plan reused 6/6, but every on-turn slower:
  median 11.8 s -> 14.1 s; the plan 0.8 s -> 1.5-3.0 s (the two 4B calls queue on the gateway, INFERRED). So the
  default is **false** (= stage 1), pinned by a test. E2's "run in parallel" therefore does NOT cut latency today.
- Stage 2b done (same day): the intent stage reads the plan's intent instead of its last-resort classifier call (only
  with the flag on). Only 10% of real questions reach that call (39/383); there the plan matched 36/36. Held-out set
  on vs off: **42/74 both, identical outcomes**, +0.35 s median per question on -> flag stays OFF.
- Merged guardrail + plan call: measured and NOT built (guardrail call median 0.16 s vs plan call 0.80 s: the merge
  would make the safety check ~0.6 s slower on every new question to save a call on ~10%; D-085).
- Tests: NEW `tests/test_query_plan_in_turn_2026_10_29.py` (25 incl. stage 2b). Full pytest after stage 2b **4,243 passed, 0 failed**; scripts 14/14 (VPN up).

## Latest: E2 guardrail — model outage fails closed for abuse only, counted and alerted (2026-10-29, D-080, KI-446 fixed). Code changed, uncommitted. LIVE-VERIFIED in-process; :8401 not running at the time (not started).
- When the guardrail model cannot judge (error, timeout, unreadable reply), `guardrails._outage_verdict`: a message with
  an abuse word (`_ABUSE_SUSPECT`) gets the `unverified` edge reply ("can't check … right now, try again"), marked
  `context_dependent` so it is never cached; plain scheme questions and out-of-scope requests go on.
  `GUARDRAIL_MODEL_FAIL_CLOSED=true` still refuses everything.
- `guardrails.outage_monitor` (per worker): let-through / refused counts, errors by kind, recent count; `/metrics`
  `guardrail`, `/health` `guardrail_model` (visibility only). 3 failures in 300 s (`GUARDRAIL_ALERT_THRESHOLD`,
  `GUARDRAIL_ALERT_WINDOW_SECONDS`) log one ERROR `ALERT guardrail model failing` line per window, and POST it to
  `ALERT_WEBHOOK_URL` when set (blank by default; `.env.example` documents it). Set it on the VMs to reach a person.
- On :8401 (started 12:21 by another session, system Python, HTTPS; has the first round, not the webhook): `/health`
  `guardrail_model: ok`, `/metrics` `guardrail` all 0, `/api/query` ganja -> refused (model, `harmful`), PMAY-G Ri Bhoi
  FY 2023-24 -> 6,847 — VERIFIED. Not restarted (another session's server).
- Not done (by the user's scope): E2's "run the guardrail in parallel with the plan" (waits for E1 stage 2) and
  "word lists for greetings only" (the outage check relies on word lists; unchanged).
- Live (VPN up, in-process, real gateway): model up -> ganja question `harmful` from the model, two scheme questions
  pass, 0 failures counted; classifier pointed at a dead port -> ganja `unverified`, scheme questions pass,
  3 ConnectError counted, exactly 1 ALERT line — VERIFIED.
- Tests: NEW `tests/test_guardrail_outage_2026_10_29.py` (22). Full pytest 4,048 passed, 9 failed — all 9 in files that
  parallel sessions edited during the 27-minute run; those 8 files alone 410/0; guardrail files on the final tree 199/0;
  scripts 14/14.
## Latest: E9 answer formatting (2026-10-29, D-082, KI-447/448 fixed, KI-449 open). Code changed, uncommitted. LIVE-VERIFIED in-process and over HTTP; :8401 restarted from `.venv` 13:28 (plain HTTP).
- **One money formatter** `_c12_money` (c12): ₹, Indian grouping, a lakh / crore column kept in its unit, rupees by
  size, a non-zero amount never ₹0.00 crore. Used by every answer c12 writes (fallbacks, templates). Scheme writers
  keep their own formats (KI-449, open). Count grouping (Indian vs Western) is still the user's open decision.
- **Figure-to-label check** `_c12_label_misbinds` in `compose_response`: a figure beside another row's name, a % as
  lakh, a row's figure written as a "more than" gap (CL-05), a figure under another measure's words → strict retry,
  then the fallback. Stricter only.
- **Templates per shape** (`ANSWER_TEMPLATES_ENABLED=true`, rollback false): ranking / compare / trend / split figures
  are written by code (`_c12s_e9_body`); the 9B writes one figure-free opening line, else code's own. Gap, peak, total
  and share lines only when the question asks. Composer keeps single figures, profiles, two-way tables, lists, yes / no,
  premise corrections. AI_PIPELINE §2.9d.
- **KI-448 fixed:** `_mgnrega_money_units` wrote "24.09 lakh" for an expenditure share % (MG-10); it skips % / share /
  ratio / rate columns.
- Live (VPN up, real models + megh_db, in-process, 12 questions): ranking, trend, two compares, two splits templated
  and correct against their rows; "24.09%" now; PMAY-G / Focus Legacy answered by their own writers (unchanged).
  Held-out golden set 2026-10-29 13:36: 56.8% (42/74), 31 clarifications, 1 wrong (FP-05: the SQL rounded crore to 2 decimals, ₹7,45,000 -> ₹7.00 lakh; qdrant examples, KI-438; not E9).
- Tests: see TESTING.md 2026-10-29 E9 row. Parallel sessions (E2, E7, E12) were editing the same tree; their files are
  not part of E9.

## Latest: E12 security / RBAC — KI-418..421 fixed, gateway CA fails closed (2026-10-29, D-081). Code changed, uncommitted. LIVE-VERIFIED in-process; :8401 NOT restarted.
- RAG-plan handover item E12, done on `update/2026-10-29` before the lanes start; it covers lane A1's SEC-03, the
  `scope_from_user` part of SEC-02 and the CA part of SEC-07, and lane B2's SEC-04 (noted in both HANDOFF lane sections).
- **KI-418:** `routers/admin.py` `_guard_super_admin` — only a cross-tenant super_admin may grant `super_admin` or change /
  reset / deactivate a super_admin; nobody changes their own role.
- **KI-421:** `auth.scope_from_user` fails closed (no real scheme -> no scheme; unknown role -> `public`; the user cap only
  narrows; an unknown cap is ignored); `NewUser` / `UpdateUser` refuse an unknown role / scheme / cap (422).
- **KI-419:** the four fixed answers before the authorize node are authorised: Focus Legacy group names (scheme check +
  in-area groups only), the Focus Plus summary, cross_figures (from the plan, before any query; NOT its SQL, whose places
  are bind parameters and whose village count reads as village level), MGNREGA women-not-recorded. The MGNREGA
  admin-expenditure caveat drops its statewide figure for an area-pinned account.
- **KI-420:** `/api/scheme-stats` returns only the caller's schemes' cards (cache shared); `WelcomeCard.jsx` shows only
  those once the server answers. `web/app/` rebuilt (the build includes other sessions' uncommitted frontend edits).
- **Gateway CA:** a configured CA file that is missing logs CRITICAL and is listed by `insecure_secrets`; with `ENV=prod`
  and the new `BOOT_GUARD_ENFORCE=true` (default false) the model client refuses to start. This dev `.env` has ENV=prod
  (not dev) and the CA file is missing, so the switch stays off here.
- **Qdrant key:** the code already sends `QDRANT_API_KEY` from the one client (`vectorstore.py`) and flags it when empty;
  the key itself and the firewall are an infra request (NOT done, not ours).
- Live (VPN up, in-process via `app.main.lifespan`, real DB + models): 6/6 turns as expected (district officer refused the
  Focus+ summary and the per-district ranking, answered its own district, refused West Garo Hills; state officer answered
  both); cards: PMAY-G-only user 1, state officer 6.
## Latest: audit v3 findings verified and merged into the 4-lane plan (2026-10-28 evening). Report only; no app code changed.
- THE PLAN TO RUN is the 4-lane plan: `new_docs/Lane_Plan_2026-10-28.html` (setup, rules, final integration) and the lane
  reports `new_docs/audit_by_lane_2026-10-28/lane-a1|a2|b1|b2.html` (prompt + audit evidence per task). Its setup commit
  ([SETUP] lane sections) is done. RAG-01..RAG-06 are left out of this round (user decision).
- `new_docs/Project_Audit_and_Work_Plan_2026-10-28.html` (audit v3, 7 packages) is kept as REFERENCE ONLY; do not run
  its Step 0 or packages. Its 19 genuinely new findings were re-checked against the code (real functions, offline):
  17 are in the lanes, SQL-11 is folded into QA-01/CTX-09 (its "58%" had 0 wrong answers, 31 deliberate pauses), and
  CTX-15 is RAG (left out). Its other entries were splits of tasks the lanes already had.
- New High findings (all REPRODUCED offline with the real functions, model stubbed, DB faked):
  SEC-08 a CTE named after a private table passes `sql_guard._assert_schemas` (DB grants UNKNOWN — NEEDS VERIFICATION);
  SEC-09 attempt 0 is authorized before `_scheme_sql_rewrites` (`pipeline_graph.node_execute_attempt` re-checks only
  `if attempt`), cross-scheme bundles authorized once as joined text, `authorize` ignores district_list/block_list/village_code;
  SQL-09 `_mgnrega_drop_geo_beside_village` strips geo filters from every WHERE incl. CTEs (district total becomes state);
  SQL-10 results cut at the 1,000-row cap are reported as complete (CONFIRMED by code);
  CMP-04 the number check skips ints < 100, year-like 1900-2199 and lakh/crore scaling ("33%" passes for 3.39%);
  CMP-06 cross_figures says "more than" / ">" / "Highest" on "lowest" questions.
  Medium: CTX-10..13 (error-path session divergence, summary resurrected after reset, KI-314 load retry dead on DB
  errors, "stop" wipes the topic, Continue offer lost), CMP-05/07/08, REL-05. KIs are opened by the packages from their ranges.
- Tests (this session): pytest 3,932 passed, 0 failed, 3 skipped; scripts 14/14. No live runs (none needed for a report).
- Next: people steps (rotate credentials, ENV=dev on both dev machines), push the setup commits, then the four lane
  sessions A1, A2 (machine 1) and B1, B2 (machine 2) with the prompts in the lane reports.

## Latest: generated SQL switched to megh_chatbot in `.env` (2026-10-28). Config only. LIVE-VERIFIED in-process; the :8401 server (started 11:13, before the change) NOT restarted.
- `.env` `CHATBOT_DATABASE_URL` uncommented (user, 2026-10-28): the D-073 path (`semantic.run_query` as megh_chatbot)
  is now on for the next start. Settings load (user `megh_chatbot`, pool max 4, `SQL_MAX_COST` 1,000,000) — VERIFIED.
  Live (VPN up), in-process through `app.main.lifespan`: startup logs `chatbot pool ready as 'megh_chatbot'`; session
  `current_user` megh_chatbot, `application_name` megh-chatbot-v2:chatbot; run_query rows come back with int/date/bool types.
  One generated-SQL question per scheme, each 1 run_query call, all answered: MGNREGA top-5 blocks EKH 2023-24 (5 rows),
  PMAY-G top-5 blocks WGH 2022-23 (5), CM Elevate district 2025-26 (12), Focus Legacy district 2022-23 (11), CM Elevate
  Legacy district 2024-25 (12); Focus Plus district 2025-26 answered by a fixed query (0 run_query calls, 12 rows) — VERIFIED.
  Seen, not caused by the switch: "CM Elevate applications" answered as CM Elevate Legacy (keyword pin); Focus Legacy
  "beneficiaries per district" answered with amount disbursed + memberships (composer extra content, see the 2026-10-27 audit).
- Still on `postgres`: `DATABASE_URL` (app pool) and the checkpointer (`PIPELINE_GRAPH_CHECKPOINTER_DSN=postgres` reuses it);
  moves to `megh_app` when the team sends the password + the user's go-ahead on `020_megh_app_role.sql`.

## Latest: KI-438 — tables and chart axes show what the rows mean (2026-10-28). Frontend only, uncommitted, `web/app/` rebuilt. Offline-verified; browser check NOT run.
- Twin columns (year_key + financial_year, name + code; one-to-one in the data) shown once — no diagonal grid of dashes.
- Every table: Indian-grouped, right-aligned figures; readable headers; totals only for measures that add up.
- Charts: axis titles, ₹ lakh / ₹ crore / % ticks and tooltips. "Change from previous" column only when the question
  asks how a figure moved. Rows and the Excel download unchanged. New module `frontend/src/chat/columns.js`.
- Tests: NEW `tests/test_table_view_2026_10_28.py` (28 with the card tests); full run in TESTING.md.

## Latest: KI-437 — a cross-scheme comparison shows only what was asked (2026-10-27 evening). Code changed, uncommitted. Offline-verified; live check NOT run (VPN down); :8401 not restarted.
- User screenshot: "Compare beneficiaries in mgnrega and PMAY-G." also gave PMAY-G completed houses, a separate MGNREGA
  sentence, a table with money / villages / sanctioned ₹ crore, and a VS card comparing amount (₹ crore).
- `app/cross_figures.py`: `_rows` has only the asked measures; one `beneficiaries` column for every scheme;
  `Plan.completed` / `Plan.pgs` show PMAY-G completed / FOCUS producer groups only when asked or for a broad ask;
  MGNREGA's household-year note is a clause on its own line. `frontend/src/chat/analytics.js` `askedMeasureCol`: the
  two-way card compares the measure the question names. `web/app/` rebuilt.
- Tests: pytest 3,910 passed / 0 failed (3 skipped; 2 async tests first failed because the fresh venv lacked
  `pytest-asyncio` — installed with `pytest`, then green); scripts 14/14.

## Latest: RAG-plan handover, Tasks 1-10 + 13 + 12 (2026-10-29). Code changed, uncommitted. LIVE-VERIFIED in-process; :8401 NOT restarted.
- **KI-406 fixed (D-075, user's U5 decision):** a standalone question that only repeats the chat's measure on the chat's scheme keeps the chat's year (never the place) — c14 `_same_scheme_context_year` / `_c14_repeats_chat_measure`. **KI-407:** test-only (the app already asks which CM Elevate dataset, D-064). Live context suite **107/107**.
- **KI-427 fixed:** a stated span ("from A to B", "between A and B") resolves to `year_key_list` = every year (c09 `_c09_stated_year_span`), prompt `year_key BETWEEN A AND B`, c11 guard, span end outside the data clamped (c06). **KI-411 fixed:** c11 `_vr_grouped_by_year_only` counts `GROUP BY year_key, financial_year_short`. **KI-441 (new, fixed):** trend answers said "rose" over a fall; `_c12s_fix_trend_direction`.
- pytest **3,951 passed, 0 failed** (2 skipped); scripts 14/14 (after Task 1). Held-out set (flaky VPN, 18/74 network errors): on the 56 clean in both runs 30 -> 31 correct, 0 regressions (PM-04 fixed). Re-run on a stable VPN to measure MG-08.
- **KI-368 fixed (Task 3):** c08 `_explicit_level_in` drops "which / what <level>" (the asked level), so "Which village … in Demdema block" resolves the block; live 2/2.
- **KI-404 fixed (Task 4):** `_PROCESS_QUESTION_CUE` routes "how does <X> work / process for …" to KNOWLEDGE unless it counts or names a year; live 3/3 right. The B3 retrieval-score tie-break is still PLANNED.
- **B4 prompt pruning / KI-442 fixed (Task 5):** every SQL prompt was 15.9k-17.1k tokens (over 15,360) and the examples were cut to 1 on every question; the catalogue now shrinks first (shared tables' column notes the question does not touch). Now 12.7k-14.2k, 5 examples. Held-out set (clean run) **41/74 vs 40/74**: MG-08 and PM-04 fixed, FL-12 one-off (3/3 on re-run). pytest 3,976 / 0. After Task 4: pytest 3,972 / 0, live context 107/107.
- **B1 (Task 6, D-076):** embeddings can't pick a measure safely (measured); unmatched measure wordings are logged with the nearest measure (`logs/metric_meaning_shadow.jsonl`, background) for a person to approve into `data/metric_catalog_synonyms.yaml` (empty today). Review: `tests/metric_meaning/review.py`.
- **B3 (Task 7, D-077):** retrieval scores overturn a DATA verdict only for a no-place / no-year / no-ranking question when the knowledge base is ahead by >= 0.10. Labelled set 67/70 -> 69/70; live 2/2 fixed (KI-444).
- **E1 query plan, stage 1 (Task 8, D-078):** `app/query_plan.py` builds a typed plan per turn in the background and logs it beside the real decisions (`logs/query_plan_shadow.jsonl`); nothing reads it. Live 25-question run: 79/79 field agreement. Later stages (stages reading plan fields) need the user's go-ahead.
- **E5 scheme registry (Task 9, D-079):** `app/scheme_registry.py`; auth roles / `_ALL_SCHEMES` / query plan / catalogue subject map read it; a guard test checks 16 other registries. Found KI-445 (constituency lists disagree; all views now carry ac_name) — open, needs a decision. SCHEMES.md "Adding a scheme" rewritten.
- **E7 (Task 10, D-071 update, 2026-10-29):** the matched measure's own words no longer block the catalogue (`_c16_measure_vocabulary`); verified pairs 104 -> 109 (CM Elevate Legacy beneficiaries total, total disbursed breakdown/ranking/compare, MGNREGA person-days breakdown); KI-425 resolved. On-mode 24/24; held-out 41/74, 0 regressions. **A parallel session is editing this same folder (E9 answer templates, app/rag.py)** — see HANDOFF.
- **B5 (Task 13):** `SQL_EXAMPLES_SOURCE=yaml_meaning` built (reviewed YAML banks ranked by meaning). held-out set 2026-10-29, same code, 0 network errors: yaml **42/74**, first-try SQL 42/43, 1 repair; yaml_meaning 41/74, 41/42, 4 repairs; qdrant (default) 41/74, 37/42, **8 repairs**, 3 verifier rejections; median 11.3 / 10.5 / 8.5 s. Accuracy within noise (only CL-11 differs yaml vs yaml_meaning); meaning ranking changed the examples on 30/37 turns but gave no measurable gain. Results `tests/nl2sql_eval/results/2026-10-29_13{23,33,39}_b5-*.json`. **User chose `yaml` as the default (D-086)**: config + dev `.env` switched; the deploy `.env` must match.
- **B2 (Task 12, KI-481):** five scheme-only words added to the scheme term lists; vocabulary label set 27/32 -> 32/32; live 5/5; pytest 4,236/0; live context 107/107.
- **MGNREGA Excel bugs (2026-10-29):** KI-432 (constituency expenditure) and KI-436 (villages-with-employment count) FIXED, KI-435 (administrative spend) FIXED, KI-433 no longer reproduces (10/10). pytest 4,265/0.
- **E10 (Task 15): BLOCKED** — no Redis server, caches deliberately off, plan-first needs E1 stage 2; see HANDOFF.

## Earlier: everything in both Qdrant collections in use (2026-10-27 evening, D-074 extended). Code + .env changed, uncommitted.
- `SQL_EXAMPLES_SOURCE=qdrant` (default + `.env`): SQL examples (+ `Note:` lines) AND megh_sql_metadata's 12 views / 16
  joins in the SQL prompt (`sql_metadata` section, scoped per scheme). megh_knowledge `doc_title` = citation title.
- Accuracy: held-out NL->SQL set, 74 q, `compare_examples_source.py` 2026-10-27 16:00: **yaml 56.8% (42) vs qdrant 54.1% (40)**; SQL first try 43/43 vs 39/43 (**4 repairs vs 0**, 2 verifier rejections vs 0); median 5.0 s vs 6.0 s; correct only with yaml FP-05, MG-08 (MG-08 is the intermittent KI-427), none only with qdrant; 31 clarifications in BOTH runs (not caused by the switch). Likely cause: the YAML banks hold 70+ examples per scheme, megh_sql_metadata ~20-25 (KI-438). Rollback: `SQL_EXAMPLES_SOURCE=yaml`.
- :8401 not running; not checked over HTTP.

## Earlier: generated SQL runs through `semantic.run_query` as megh_chatbot (2026-10-27 afternoon, D-073). Code changed, uncommitted. LIVE-VERIFIED in-process; :8401 NOT restarted.
- `.env` `CHATBOT_DATABASE_URL` (key renamed from the user's `DATABASE_URL_CHATBOT`, which made settings refuse to load). Third pool, 4/worker.
- Row values restored to asyncpg's types from run_query's `types` (added by the team today); 583/585 recent statements identical, 2 = same rows, no ORDER BY.
- Refusals -> existing errors; class 08 / 53300 retried once; repairs stay 3 (team agreed). `application_name` = `megh-chatbot-v2:<pool>` on every connection.
- Tests: pytest 3,902 / 0, scripts 14/14, eval 43/74 with 0 regressions. Still on `postgres`: the app pool + checkpointer (waiting for the user's go-ahead on 020_megh_app_role.sql, team will cap megh_app at 35); old container 172.18.0.2 (20 postgres sessions) to be stopped by the server admin.

## Earlier: KI-431 — short FY forms ("FY23") reach the SQL model written in full (2026-10-27). Code changed, uncommitted. LIVE-VERIFIED in-process; :8401 not restarted.
- `context_policy.expand_short_fy` (on `short_fy_tokens`) in `generate_sql` / `_repair_sql`; the year guard names a wrong
  year_key (`_vr_year_key_literals`). Found by the MGNREGA Excel sheet run (`tests/sheet_runs/mg_excel_run.py`, expected
  figures from the two raw Excels). Run: 763/919 right figure with no extra question, 863/919 incl. 100 "which scheme?"
  pauses; report `new_docs/MGNREGA_Excel_Test_Report_2026-10-27.md`. New OPEN: KI-432 (HIGH: constituency expenditure
  0/10, once the statewide figure), KI-433 ("completion rate" = count), KI-434 (guardrail refusals), KI-435, KI-436.
- pytest 3,881 passed / 0 failed (3 skipped); scripts 14/14; live 6/6 (FY23, FY 23, FY25, FY 23-24, FY'24, 2022-23).
- Excel vs megh_db: village, constituency and state figures identical; 15 villages sit under another block in megh_db
  (2 under another district), so a few block totals and the SW / W Garo Hills district totals differ (as in the 2026-10-21 report §4).

## Earlier: fixes for the DB team's changes (2026-10-27, D-072). Code changed, uncommitted. LIVE-VERIFIED in-process; :8401 not restarted.
- KI-428 fixed: CMSS / Home Stay glossary terms AND ~40 `v_cmss` / `v_homestay_legacy` column notes no longer go into our six SQL prompts.
- `semantic.check_query` runs before each generated query (row_join -> repair; fail-open; `SQL_DB_PRECHECK`).
- 57014 / 53400 -> `QueryTooHeavyError` (504 "narrower question"); repair loop unchanged.
- SQL guard refuses `pg_*` / `lo_*` / `dblink*` / `txid_*` / `inet_*` functions and `current_setting` / `version` / `current_database`.
- KI-429 fixed: a block_officer with no block gets statewide figures only.
- Tests: pytest 3,863 / 0, scripts 14/14, eval 41/74 with 0 regressions. Still open: KI-430 (retention), megh_app / megh_chatbot (waiting on the team).

## Earlier: DB team changes of 2026-10-27 checked — nothing broken (review only, no code changed).
- Report `new_docs/DB_Changes_Impact_Report_2026-10-27.md`. Live on megh_readonly: name-column locks, 30 s / 1 GB / 20-conn
  limits active; 425 recent generated statements replayed via `run_readonly` with 0 failures, `semantic.check_query` 0 flags
  (max cost 101,270); 6/6 schemes answered end to end. `megh_app` role not created yet; `megh_chatbot` exists, no password.
- New open: KI-428 (CMSS/Home Stay glossary terms in every scheme's prompt), KI-429 (block_officer with no block = whole
  district), KI-430 (audit previews, no retention). Moving generated SQL to `megh_chatbot` + `semantic.run_query` is PLANNED,
  not started (report §5: JSON row types, no `$1` params, error mapping, their 2-repair ask vs our 3).

## Earlier: KI-405 fixed — a scheme switch typed during an area / year pause (2026-10-27). Code changed, uncommitted. LIVE-VERIFIED.
- c14 `_c14_pause_scheme_switch`: "What about MGNREGA?" while "How many PMAY-G beneficiaries…?" waits for its area ->
  "How many MGNREGA beneficiaries are there?" (asked its own area / year), not a merged two-scheme query.
- Live context 105/107 (was 103; left KI-406 / KI-407, user decisions); pytest 3,833 / 0; scripts 14/14; :8401 PID 52752.
- New open: KI-427 (golden MG-08 year range keeps only the last year; intermittent, pre-existing).

## Earlier: D-071 — the data team's metric catalogue answers plain measure questions (2026-10-26 night). Code changed, uncommitted. LIVE-VERIFIED.
- `app/metric_catalog.py` + `app/pipeline/common/c16_metric_catalog.py`: one measure, nothing else asked -> parameter-bound
  query from `semantic.metric_definitions` (total / breakdown / ranking / compare), last in the fixed-query chain, read-only
  pool, only for the 104 (measure, shape) pairs in `data/metric_catalog_verified.yaml`. `METRIC_CATALOG_MODE=on`.
- Live: 183/183 catalogue answers give the same figure; golden 42/74 (0 regressions); live context 103/107; known 13/14.
- pytest 3,829 / 0; scripts 14/14. New open: KI-424 (ambiguous measure words), KI-425, KI-426.
- :8401 restarted from the venv 2026-10-27 11:04 with D-071 loaded (log: 39 metrics, verified 28/25/28/23); live HTTP check OK.

## Earlier: RBAC review (2026-10-26). No app code changed. Report `new_docs/Role_Based_Access_Report_2026-10-26.md`.

## Also 2026-10-27: Qdrant on the data box; only megh_knowledge + megh_sql_metadata, read-only (2026-10-27, D-074). Code + .env changed, uncommitted. Live-checked in-process.
- `QDRANT_URL=http://10.48.242.4:6333` (VPN). RAG reads `megh_knowledge` (207 pieces, another pipeline loads it).
  `QDRANT_KB_READ_ONLY=true`: no startup rebuild, `/api/rag/reingest` skips, writes raise. `RAG_HYBRID_ENABLED=false`.
- Conversation memory OFF (`CONTEXT_SEMANTIC_MEMORY_ENABLED=false`, KI-439). Context still comes from Postgres.
- `SQL_EXAMPLES_SOURCE=yaml|qdrant` (default and `.env`: yaml). qdrant = examples from `megh_sql_metadata`, fetched
  in `_data_sql_stage` (new `app/sql_examples.py`). The eval script is `tests/nl2sql_eval/compare_examples_source.py`; NOT RUN yet.
- `.env` replaced with the user's new file; `DATABASE_URL_CHATBOT` commented out (it stopped startup, KI-437).
- Open: KI-438 (Qdrant examples unvalidated), KI-440 (RAG cut-offs not re-measured on megh_knowledge).
- Tests: see TESTING.md 2026-10-27 row.

- 8 roles (`auth.ROLE_PERMISSIONS`; `public` unreachable), 4 gates (`deps.py`), 3 data checks (`auth.authorize`).
  Built and working: login/JWT, endpoint gates, tenant-scoped admin reads, SQL + repair checks, scope-keyed cache, audit.
- New OPEN issues: KI-418 (HIGH: admin can PATCH self/others to super_admin), KI-419 (4 fixed answers skip `authorize`),
  KI-420 (`/api/scheme-stats` unscoped), KI-421 (fail-open scheme list, unvalidated `granularity_cap`). KI-007 still open.
  No tests for the admin/role endpoints.
## Latest: D-070 — a call without a session id gets its own conversation (KI-423, RAG plan E3), 2026-10-26 night. Code changed, uncommitted. LIVE-VERIFIED.
- `api-<random>` per session-less call (continue by sending the returned id); hidden from the user's history list/search.
- pytest 3,805 / 0; scripts 14/14. :8401 = PID 10012.

## Earlier: connection caps agreed with the ingestion team (2026-10-26 night): megh_app 30, megh_readonly 20, both hard.
- `172.18.0.2` = very likely the old build's Docker container (INFERRED); stop it at switch-over. Docs only; no code change.

## Earlier: megh_app readiness checked; unused rule files marked NOT LOADED (2026-10-26 night).
- Fixed curated reads run clean under megh_readonly's limits (0 permission denied); app SQL is `app.`-qualified; 15 s app
  timeout < 60 s. Connection cap: need 30 (6 per worker x 5 workers), team asked. Chat-history backup policy: user decision.

## Earlier: catalog reads also as megh_readonly; Khasi note wording (2026-10-26 late, team's reply). Code changed, uncommitted. LIVE-VERIFIED.
- `schema_introspect` -> `db.fetch_rows_readonly`: the SQL prompt shows only what megh_readonly can read (same counts).
- The `postgres` login (DATABASE_URL) now serves only the app's own tables (`app.*` in megh_db) and the app's fixed queries.
- pytest 3,799 / 0; scripts 14/14. :8401 = PID 39908.

## Earlier: D-069 extended — megh_readonly in use, Ri Bhoi in Khasi, "pending" not recorded, KI-417 (2026-10-26 evening). Code + rules + .env changed, uncommitted. LIVE-VERIFIED.
- Generated SQL now runs as `megh_readonly` (dev `.env` key fixed, superuser override off, pools 4+4+2 per worker).
  `SELECT *` on a table with hidden columns is expanded to the readable columns (c11).
- Ri Bhoi is in the Khasi region everywhere (resolver, rules, prompt, examples); answers say so in one line.
- CM Elevate "pending / approved / rejected / sent back": "not recorded" + the recorded figures (distinct applications).
- KI-417 fixed (₹119.74 crore). Opened KI-422 (level-2 answer still says "pending").
- pytest 3,799 / 0; scripts 14/14; held-out 42/74 (0 regressions, as megh_readonly); live context 103/107.

## Earlier: D-069 — the ingestion team's 15-24 Oct DB changes picked up (2026-10-26). Code + rules changed, uncommitted. LIVE-VERIFIED.
- `member_id` -> `member_key` (prompt + Focus Plus rules); six region examples -> `region_group` + c11 safeguard;
  KI-415 FIXED (all in-prompt examples run). Reply to the team with answers and 5 questions:
  `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-26.md`. Open: `megh_readonly` credential (KI-304), KI-417 rounding.
- pytest 3,784 / 0; scripts 14/14; known answers 7/12 exact, rest explained. :8401 = PID 29672.

## Earlier: KI-414 — short FY forms read by every year reader; follow-up "give me FY 25" fixed (2026-10-26). Code changed, uncommitted. LIVE-VERIFIED.
- One reader `context_policy.short_fy_tokens` -> `extract_year_keys`, the year-gap guard, the year back-fill; the rewrite
  check keeps the user's own year; edge accepts "FY'25". Live follow-up sweep 81/81 (FY18-26 × 3 forms × 3 schemes).
- Opened KI-415 (broken region few-shot examples; 2 `test_fewshot_headers` failures, not from this change) and KI-416
  (bare year follow-up after a houses question switched to the amount).
- pytest 3,777 passed / 2 failed (KI-415); scripts 14/14. :8401 = PID 7260. Another process also restarts :8401.

## Earlier: ranking count words ("five highest" = top 5) and a shared-namespace guard (2026-10-26). Code changed, uncommitted. LIVE-VERIFIED.
- KI-412 FIXED (RAG plan C2): c02 `_normalize_rank_counts` (count words -> digits in a ranking position) and c11
  `_stated_rank_count_limit` (outer LIMIT = the stated count where safe). Five wordings of one ranking -> the same 5 blocks.
- KI-413 FIXED: a name collision this change caused (shared pipeline namespace) broke spoken years; renamed, and NEW guard
  test fails on any duplicate top-level name. CLAUDE.md §2 notes the rule.
- pytest 3,742 / 0; scripts 14/14; held-out 42/74 (0 regressions); live context 103/107. :8401 = PID 36832.

## Earlier: D-068 — a stated scope is never asked for; "FY24" = FY 2023-24 (2026-10-24 night). Code changed. LIVE-VERIFIED.
- KI-409 FIXED (FY24 read as 2024-25, in the parser AND via the extractor's bare "24"); KI-410 FIXED (stated scope in
  unrecognised wordings was asked). Nothing-stated questions still ask (D-053 / D-056 unchanged; option A NOT re-applied).
- Held-out NL->SQL set: 54.1% (40/74, 0 wrong) earlier today -> **56.8% (42/74)**; the other 31 clarifications follow
  D-053/D-056/D-064/D-065 (the set's expectations predate them: user decision pending). KI-411 opened (PM-04 split).
- pytest 3,698 / 0; scripts 14/14; live context 103/107 (unchanged). :8401 = PID 44700.

## Earlier: docs name the real KB folder `data/incoming/<scheme>/` (2026-10-24, RAG plan A3 doc part). Docs only.
- CLAUDE.md (§1, §5), ARCHITECTURE (tree, §3.9), AI_PIPELINE (KB ingest), SCHEMES (adding a scheme) said `data/reference/`,
  which does not exist since 2026-10-14. Also corrected there: `_SOURCES` -> `_INCOMING_SCHEMES` / `_sme_sources`, the KB
  collection name (`QDRANT_COLLECTION`, v4) and the rebuild conditions (BM25, vector size). History entries left as written.

## Earlier: `.gitignore` now skips `raw_uc/`, `new_docs/*.csv`, `new_docs/~$*` (2026-10-24, RAG plan E12, part)
- The raw use-case sheets (PII) and QA result CSVs can no longer be committed by a careless `git add .`; the files stay on
  disk (13 in `raw_uc/`, 9 CSVs). No tracked file matches the new rules; the `new_docs/` .md/.html/.docx reports stay tracked.
- Still open (E12): KI-022 CSV in the remote history, Qdrant API key, gateway CA file, read-only DB role, token in the remote URL.

## Earlier: the 1024-dim switch is complete and LIVE on :8401 (2026-10-24 evening, D-067 follow-up). Committed `9c7c67c` on `update/2026-10-24`.
- Backup: our 7 `megh_*` Qdrant collections snapshotted to `C:\Users\rohit\Downloads\qdrant_backup_2026-10-24\` (outside
  the repo; holds officers' chats — never commit or share).
- KI-402 FIXED: `kb_ingest` rebuilds a KB of the wrong vector size; memory never writes into / deletes a wrong-size collection.
- KI-403 FIXED: NEW `CONTEXT_MEMORY_PURGE_ALSO` — the 384-dim rollback memory is purged after 30 days too.
- NEW `deploy/migrate_conversation_memory.py`: 12,046 turns re-embedded into `megh_conversation_memory_1024` (recall 20/20).
- :8401 restarted (`.venv`, PID 24368, log `logs/server_8401_2026-10-24.log`); startup size check passed (v4 = 1024).
- pytest 3,661 / 0 (3 skipped), scripts 14/14. Live context 103/107: the 4 failures are identical on 384 → not D-067;
  opened KI-404..407. Stale comments fixed (config.py, rag.py, local_rank.py); AI_PIPELINE's old "top 8 returned anyway" corrected.
- KI-408 FIXED: memory search is exact and the memory collection has payload indexes (tenant_id, user_id, session_id, ts):
  60/60 equal to exact search (was 58/60, 1 usable turn missed), same speed. Live context re-run 103/107 (same 4 known).
  pytest 3,663 / 0. :8401 now PID 17056 (log `logs/server_8401_2026-10-24b.log`).
- NOT done: deploy VMs (`.env` lines + migration script); Qdrant API key + firewall; gateway CA file.

## Earlier: embeddings from the gateway's qwen3-embedding, 1024-dim (2026-10-24, D-067). `.env` + one code fix (KI-401).
- VERIFIED live: gateway `/openai/v1/embeddings` returns 1024-dim vectors for `qwen3-embedding`. The old `.env` URL
  (`…/v1/completions`) gave 404; fixed to `…/openai/v1`.
- `.env`: `EMBEDDING_PROVIDER=gateway`, `QDRANT_COLLECTION=megh_scheme_kb_v4`, `CONTEXT_MEMORY_COLLECTION=megh_conversation_memory_1024`,
  `RAG_MEDIUM_CONFIDENCE=0.35`, `CONTEXT_MEMORY_MIN_SCORE=0.45`. `megh_scheme_kb_v4` BUILT (201 points, 1024-dim, BM25);
  the 384-dim `megh_scheme_kb_v3` / `megh_conversation_memory` untouched (rollback in D-067). `config.py` defaults unchanged.
- RAG eval (188 q): correct-or-honest 92.0 on v4 at 0.35 = 92.0 on v3 today; fewer made-up answers (13.9% vs 17.1%).
- KI-401 FIXED: semantic-cache hits now also need the same rank direction / N / status / measure / category words.
- pytest 3,652 / 0 (3 skipped), scripts 14/14.
- NOT done: the running :8401 server (PID 32172, started with the SYSTEM Python) still has the old settings until restart;
  deploy VMs' `.env`; CA file `certs/enlight-aiops-internal-ca.pem` still missing (TLS verify off, KI-015).

## Latest: NL→SQL feature / benchmark gap report (2026-10-23). No app code changed, no new live runs.
- `new_docs/NL2SQL_LangGraph_Benchmark_Report_2026-10-23.html`: feature checklist (built / partial / missing), LangGraph
  capability check, public benchmarks (Spider, BIRD, Spider 2.0, SParC/CoSQL, Dr.Spider), PROPOSED targets vs latest recorded
  results, 8 ranked gaps + roadmap. Top gaps: rule-based understanding (no `query_analyzer` node), no CI accuracy gate,
  latency under load, no read-only DB role.

## Latest: full system audit (2026-10-23). No app code changed. Report `new_docs/Megh_One_AI_Audit_Report_2026-10-23.html`.
- VERIFIED: 5/5 model roles answer via `app/llm.py`; DB, Qdrant, :8401 up; pytest 3,650 / 0 (3 skipped), scripts 14/14.
- Live ~110 questions over HTTP vs read-only DB truth: every figure given = DB; paraphrases 41/41, repeats 27/27, rankings 9/10,
  follow-up chain 4/4. Found: "FY24" read as FY 2024-25 (no KI yet), "Five highest blocks" asks top-N (number words), Focus+
  money shown in rupees in one wording and crore in another, API calls without session_id share one `day-<user>-<date>` chat.
- Also found: `raw_uc/` (PII CSVs) NOT gitignored; KI-022 CSV still in remote history; gateway CA file missing -> verify=False;
  `state_officer` capped at district (auth.py:64; confirm policy); UI phone cards truncate figures; compare card "% ahead"
  mixes spent vs released. CLAUDE.md stale (verifier model, re-ranker, privacy-table guard, test counts). Not fixed: audit only.

## Latest: KI-397 — cross-scheme comparison card showed "PMAY-G 0" (2026-10-22 night). Frontend only. Code changed, uncommitted. TESTED (node), not checked in a browser.
- User screenshot: "MGNREGA vs PMAY-G — households given work: 14,94,437 vs 0". Cause: the D-066 rows give each scheme its own
  count column; `analytics.js` read columns from the first row only, so PMAY-G (no `households_given_work`) showed 0. The
  table and the Excel export also dropped PMAY-G's `houses_sanctioned`.
- Fix: `analytics.js` charts only columns every row carries + NEW `tableColumns` (union of all rows' keys) used by
  `Charts.jsx` `DynTable` and `ChatExport.jsx`. `npm run build` done. Card now compares amount (₹ crore), held by both.
- Tests: NEW `tests/test_cross_compare_card_2026_10_22.py` 3/3 (2/3 fail on the old code); `test_history_charts.py`,
  `test_ac_full_results.py`, `test_cross_figures_2026_10_22.py` 39/39. Full suite NOT re-run (frontend-only change).

## Latest: D-065 — a pause reply keeps the typed question's kind; a new question with no year is asked (2026-10-22 night). KI-394, KI-395 fixed, KI-396 opened. Code changed, uncommitted. LIVE-VERIFIED (in-process).
- User report: after an all-years CM Elevate Legacy answer, "What is the total disbursement amount for mairang?" ->
  place chips -> whole-or-part chips -> "₹22.49 crore … FY 2025-26 (new question)". "Take previous context or ask
  which year — don't blindly give 2025-26."
- Cause: the typed question names no scheme (VAGUE -> the chat's scope), but the chip text names the scheme and the
  level, was re-classified STANDALONE and got the D-061 latest-FY default. (₹22.49 crore = the statewide FY 2025-26
  total with the Mairang filter dropped: KI-381, being fixed by a parallel session.)
- Fix (D-065): `Session.pending_turn_kind` (snapshot `pending.turn_kind`) set by `routers/query.remember_pause`; c14
  `_turn_context_stage` hands it to a resumed reply (scope merge, typed pick, tapped chip of any length) as
  `turn_context["resumed_turn_kind"]`; `_turn_followup_stage` uses it as the turn kind;
  `_same_scheme_context_year(kind=)`. c13: the D-061 latest-FY default is removed — a standalone question with no year
  gets the year chips. KI-395: a scope resume re-pins the CM Elevate dataset on the merged question.
- Live: the user's chat -> ₹1.14 crore, Mairang constituency, all financial years (= DB). pytest 3,604 passed (2
  parallel-session failures, green alone), scripts 14/14, harness in-process 130/139 -> re-specified + re-run green
  (TESTING). Open: KI-396 (NQ06 Hinglish -> knowledge), META_recap turn 7, **user's call on U5** (below).
- **Conflict for the user:** KI-331 (2026-10-19) said "give me cm elevate disbursement by district" after an all-years
  answer must NOT ask the year again; under D-065 it asks (a new question). Keep asking, or let a same-scheme new
  question keep the chat's year? DOCUMENTATION CONFLICT — NEEDS VERIFICATION (user decision).

## Latest: D-066 — cross-scheme figures of the four main schemes worked out in code (2026-10-22 night). KI-387..392 fixed, KI-393 bot side fixed (data part open). Code changed, uncommitted. LIVE-VERIFIED.
- Sheet `raw_uc/cross_scheme.xlsx` (60 cases T01.1..T20.3). Before (report `new_docs/Cross_Scheme_Test_Report_2026-10-22.md`):
  bot vs raw 20/60, vs DB 17/60. User then gave `Cross_Scheme_Issues_and_Solutions_2026-10-22.md`: "fix these immediately".
- Changed: NEW `app/cross_figures.py` (plan + fixed parameter-bound per-scheme queries + combine step + answer text);
  c01 import; c13 `_cross_exclusions` / `_cross_after_exclusions` / `_cross_figures_question`, `_data_scheme_stage`
  (exclusions first, bare-FOCUS ask in a comparison), `_cross_scheme_scope` (D-066 answer); c14 route (cross figure
  question stays DATA); schemes/focus_plus `_focusplus_district_group_not_null`; c11 `_unasked_having_threshold`
  (+ both in `_scheme_sql_rewrites`). Tests: NEW `tests/test_cross_figures_2026_10_22.py` (39), 1 test in
  `test_cross_scheme_llm_2026_10_22.py` stubs the D-066 answer.
- After (final live run): every figure = megh_db in **59/60** (T13.3 lists low Focus+ districts by villages); = raw files
  **47/60**, the 13 = KI-393 data (MGNREGA Genapara WGH/SWGH, Focus+ village codes) + T13.3. pytest 3,647 / 0, scripts 14/14.
- Not done (ingestion team, `megh_db` not ours): the catalogue items of the issues document (metric defaults,
  'Unresolved' note wording, Focus Legacy members / villages metrics, "coverage" glossary synonym) and KI-393 data.

## Latest: CM Elevate Legacy sheet re-test; D-064 routing + KI-379..386 fixed (2026-10-22 evening). Code changed, uncommitted. LIVE-VERIFIED.
- Sheet `raw_uc/Use_Cases_-_CM_Elevate.xlsx` (its one tab is "CM Elevate Legacy", TC-01..36) vs DB and the raw
  `raw_uc/Cm Elevate to share to BLH (1).csv` (2,823 rows = DB, every field). Report + CSV:
  `new_docs/CM_Elevate_Legacy_Test_Report_2026-10-22.md`, `new_docs/CM_Elevate_Legacy_all_conversations_2026-10-22.csv`.
- **D-064 (user decision):** a bare "CM Elevate" (or a lone sub-scheme): financial words -> CM Elevate Legacy directly
  (thread included); applications-only words -> applications; else the chat's dataset (a DATA answer, not a knowledge
  one); else ask "CM Elevate (applications) or CM Elevate Legacy?". Chip marker "CM Elevate (applications)".
- **Fixed (user: "fix all of these"):** KI-381 constituency questions on Legacy (rewrite to the `dim_geography.ac_name`
  join + missing-filter guard + verifier discard), KI-384 ROLLUP total row read as a category (`_c12s_rollup_split`;
  multi-measure breakdown fallback lists every measure), KI-382 briefing overview -> knowledge, KI-383 "no records"
  sentence, "which / across / each schemes" inside a CM Elevate chat -> its sub-schemes (c04). KI-386 not reproducible.
  KI-385 (MGNREGA `year_note` on Legacy rows) reported to megh-ingestion (`docs/CM_Elevate_Legacy_DB_Issues.md`).
- Live final: sweep **300/300** (was 179), sheet wording **96/108** (32/36 use cases 3/3; the 4 left are "which
  schemes" with no scheme named in a NEW chat = cross-scheme by design), one chat **72/72**; CM Elevate applications sheet
  513/529 (no Legacy answers). pytest **3,608/0**, scripts 14/14. :8401 restarted from the venv onto this code.

## Latest: answers take the question's shape; KPI cards follow the data (2026-10-22 evening). D-063, KI-377, KI-378. Code changed, uncommitted. LIVE-VERIFIED.
- User: "if I ask top 10, top 5 or compare … you need to give different answers" (KI-377). New
  `app/pipeline/common/c12_answer_shapes.py` (in `_PIPELINE_FILES` after c12): the answer's shape (ranking / compare /
  trend / breakdown / cross_tab / list / profile / single_value + yes-no) is read from the SQL tree and the rows;
  `compose_response` gives that shape's instructions + example and code-computed derived figures (gaps, difference and %,
  first-to-last change, peak, shares — whitelisted), sorts a breakdown largest first, and falls back to a shaped answer.
  Single-figure prompt unchanged; temperature still 0. AI_PIPELINE §2.9c.
- Live (12 questions, VPN): top 5 -> numbered ranked list + gap; lowest 3 -> "has the lowest"; compare -> verdict +
  difference + %; Ri Bhoi year-by-year -> first-to-last, peak, per-year list; district split -> total + shares + list.
  Still the old fixed text (phase 2): MGNREGA summary / job cards / combined facts, PMAY-G facts, Focus Legacy
  breakdowns, CM Elevate sectors.
- User: "kpi cards data need to update dynamically … based on the data correctness" (KI-378). `/api/scheme-stats` now
  also returns each card's financial years (`periods`, from the views), counts "(N yr)", shows "—" for a NULL figure;
  the welcome card re-reads on tab focus and every 10 min and says whether the figures are live or the typed fallback.
  All six cards checked against megh_db (= DB). `npm run build` done.
- pytest **3,568 / 0** (3 skipped), scripts 14/14. :8401 restarted from the venv at 15:42 (user request) and checked
  over HTTP: /health ok, /megh-chat serves the new build, /api/scheme-stats returns `periods`, POST /api/query "Top 5
  blocks by MGNREGA person-days in West Garo Hills in 2023-24" -> ranked list + gap. Not committed (user: don't commit).

## Latest: KI-375 / KI-376 fixed (2026-10-22 late afternoon). Code changed, uncommitted. LIVE-VERIFIED.
- KI-375: CM Elevate Legacy `…_cr` columns over undivided rupees are divided by 1e7 (`_cm_legacy_crore_alias_on_rupees`).
- KI-376 (+ Focus Plus unmapped buckets): c11 `_village_rows_by_code` — village rows are one named row per real village
  (code + name + block grouped; a ranking leaves out `entity_type = 'Unresolved'`), every scheme.
- pytest 3,537 / 2 (both green alone; parallel-session edits mid-run), scripts 14/14. :8401 restarted (venv).

 (2026-10-22 afternoon). D-062, KI-374 fixed; KI-375/376 opened. Code changed, uncommitted. LIVE-VERIFIED.
- User report: "top ten highest villages in Mgnrega and pmay" got the same statewide totals card as "compare MGNREGA and
  PMAY-G spending": the D-044 table (`cross_scheme.plan` / `answer`) had no village grain and no top N. User decision:
  no template for cross-scheme questions; answer whatever is asked.
- Now (c13): `_cross_scheme_scope` (no pause, D-044 place handling) -> `_cross_scheme_gaps` (constituency / year / CM
  Elevate money stated, not queried) -> a 9B one-scheme question per scheme (`_cross_scheme_subquestion`, checked) ->
  per-scheme SQL, each with its own prompt, guards, verifier and repairs -> composer -> guards: money in ₹ crore for every
  scheme (read on the SQL tree); a scheme left out -> retry, then sections; full lists; a wrong "highest" corrected;
  no-figure lines. Removed: `cross_scheme.answer` / `plan`, `_cross_scheme_money_answer`, `_CROSS_SCHEME_MONEY_SQL`,
  `unnamed_schemes`.
- pytest 3,530 / 0, scripts 14/14, new `tests/test_cross_scheme_llm_2026_10_22.py` (26). Live: the user's question and
  20/20 sheet questions answered. :8401 restarted from the venv (it was running under the system Python).
- OPEN: KI-375 (CM Elevate Legacy `_cr` alias on a rupee value), KI-376 (PMAY-G village ranking grouped by name only);
  the cross bulk harness needs new truth (DOCUMENTATION CONFLICT in SCHEMES.md). Latency 10-40 s per cross question.

## Latest: New question = new answer (2026-10-22 ~13:45). D-061, KI-373. Code changed, uncommitted. LIVE-VERIFIED.
- User addendum `Context_Memory_New_vs_Followup.pdf`: after "MGNREGA person-days in East Khasi Hills in 2022-23",
  "Which district has the highest beneficiaries in MGNREGA?" was answered inside EKH / FY 2022-23.
- Now `context_policy.turn_kind` decides before any rewrite: STANDALONE (own scheme + own measure, no reference cue)
  inherits nothing — statewide unless named, its year else the scheme's latest FY, banner "(new question)";
  FOLLOWUP (reference cue / fragment) inherits only what it leaves out; VAGUE (measure, no scheme named) uses the one
  open topic or asks with one chip per topic. The level a question asks about and below are never its filter.
  Hinglish "wala" no longer blocks the rephrase (NQ06).
- **Behaviour change vs D-056 §2 / 2026-10-18 / KI-331:** "how many households for PMAY-G" after an MGNREGA West Garo
  Hills FY 2022-23 answer is statewide, latest FY (was: WGH, 2022-23). Idle window left at 8 h (addendum said 30 min).
- Verified: pytest 3,515 / 0 + scripts 14/14; harness new scenarios in-process 32/33 (AU01 needs auth -> http), http
  --stream --skip-cache **33/33, 80/80**; re-specified N3 / C_backward_restore / F3 / CONV / U5 / P13 6/6 live.
  Full http harness: see TESTING. :8401 restarted from the venv ~13:00 onto this code.

## Earlier: Focus Legacy sheet re-tested and fixed (2026-10-22 ~13:30). KI-369, KI-370, KI-371 fixed; KI-372 open. Code changed, uncommitted. LIVE-VERIFIED.
- 28 use cases (`raw_uc/Use_Cases_-_Focus.csv`) vs raw `raw_uc/Focus Legacy to share to BLH.csv`: raw = DB (14,569 rows,
  every field, every level). Before: 25/28 use cases; TC-28 (constituency) 12-15/55 — a REGRESSION from the 17-20 Oct
  commits (13 Oct code 55/55): the 30B verifier rejected the documented `dim_geography` join and the repairs answered the
  district. TC-16 / TC-25 broke on "FOCUS PG" (`pg_entity_type = 'FOCUS_PG'`, learnt from the prompt's value lists).
- Fixed, Focus Legacy only (`schemes/focus_legacy.py` + hooks in c11): verifier overrules (constituency query; "not
  aggregated" when SUMmed), drift guard (resolved constituency must be filtered on `ac_name`), `ac_name` case rewrite,
  FOCUS_PG dropped unless the group type is asked, members-as-groups guard.
- After: sweep **231/231**, sheet wording **84/84**, constituencies **55/55**, TC-16 9/9, TC-25 6/6. pytest 3,416 / 0,
  scripts 14/14. New `tests/test_focus_legacy_sheet_run_2026_10_22.py` (32).
- Every village 3,363 / 3,384 on the fixed code. OPEN: KI-372 (19 of the 21 misses: an unasked `pg_id` — mostly the
  resolver YAML's example id PG-FOCUS-WGH-7089 — / variant / group-type / year filter). :8401 NOT restarted.
- DOCUMENTATION CONFLICT: CLAUDE.md §5 says the 4B is the SQL verifier; `app/config.py` `SQL_VERIFY_MODEL = "qwen-model"`
  (30B) since 2026-10-15. AI_PIPELINE.md corrected; CLAUDE.md left for the user.

## Earlier: ranking follow-ups drop the chat's place at the ranked level (2026-10-22 ~12:00). KI-366. Code changed, uncommitted. LIVE-VERIFIED.
- User chat: after a Demdema block answer, "Which block has highest number of households?" answered Demdema's own 0.
  Now: `context_policy._RANK_OVER_GEO_MATCH` clears the ranked level (district kept, D-056) and
  `c14 _ranking_followup_question` rewrites a ranking that names its measure deterministically. Live: TIKRIKILLA
  58,306 household-years in West Garo Hills (= DB); "top 3 blocks" lists all three (was a sum).
- pytest 3,375 (+ the new file 21/21; known `test_scheme_years` artifact); scripts 14/14; http harness 102/102, 313/313.
- Opened: KI-367 ("most X in which block?" -> knowledge), KI-368 ("which village … in Demdema block" -> village Demdema).
- :8401 restarted ~11:30 from the venv: it serves this code.

## Earlier: FOCUS-019 and FOCUS-004 fixed in every phrasing (2026-10-22). KI-360, KI-361. Code changed, uncommitted. LIVE-VERIFIED.
- FOCUS-019: a Focus Plus batch status breakdown ("12.5K" / "12.5k" / "12.5 K" / "93 K", any word order, "break down
  ... by status", "status split") is never refused (c14 overrule, edge whitelist, Focus Plus terms). Live 25/25 (was 18/25).
- FOCUS-004: the five municipal boards in any spelling ("Shillong Municipal Board", "X MB", "William Nagar Municipal
  Board") answer the board (c09 urban-body step for Focus Plus incl. the constituency slot; mistyped block literal
  snapped in `_focusplus_lgd_only_block`). Live 96/96 (was 75/96); sheet blocks 50/50; ward villages 155/155.
- pytest 3,363 / 0; scripts 14/14. New `tests/test_focusplus_sheet_run_2026_10_22.py`. Still open: KI-359, KI-362..365.
- :8401 was NOT restarted then (it was restarted later, in the KI-366 session).

## Earlier: Focus Plus sheet re-test, every level (2026-10-22). No app code changed. KI-359..365 opened.
- 29 use cases (`raw_uc/Focus+ Test Case Observation.xlsx`): sweep **161/163**, every village **3,513/3,513**, sheet's
  own wording **79/85**, follow-up chats **12/14** turns. 26 of 29 use cases fully pass.
- OPEN: KI-359 ("each district" grouped by `district_name_raw`: WGH 35,059 vs 35,039 elsewhere, 5/5), KI-360 ("status
  breakdown for 12.5K batch" refused, 5/5), KI-361 (Shillong Municipal Board block), KI-362 (rare per-payment average),
  KI-363 / KI-364 (follow-up "by district" / "compare with" lost), KI-365 (FY 2022-23 zero explained badly).
- Raw `raw_uc/Focus Plus Master.csv` = DB row for row (385,671), every field; village codes differ by the ingestion's
  name mapping (45,280 rows filled, 57,649 "not yet mapped"). Report `new_docs/Focus_Plus_Test_Report_2026-10-22.md`.

## Latest (2026-10-23 evening): context-memory audit (report only, no app code). KI-399, KI-400 opened.
- Report `new_docs/Context_Memory_Audit_Report_2026-10-23.html`: verdict pilot-ready on the office network, not
  production-ready; 10 findings, readiness scorecard, production targets, 3-step plan, 4 decisions for the department.
- pytest (documented command) **3,651 passed, 0 failed**, 3 skipped. Harness http --stream --skip-cache full set
  (`logs/conversation_harness/2026-10-23_2231_http.json`): 128/139, 382/420 — 35 error turns in 9 chats (U4..U9, N1..N3)
  are a VPN drop (DB + gateway unreachable at 22:35), 3 logic fails are known (META_recap T7; CMP card removed by D-062,
  stale expectation). Answered turns 382/385.
- NEW High: KI-399 (no session ownership check), KI-400 (one cached answer wipes topic memory). NOT RUN (VPN down):
  re-run of the 9 chats, `tests/live_context_validation.py` (last 18 Oct), the live two-account / cache-then-"go back" probes.

## Latest (2026-10-23): PMAY-G welcome card "Houses sanctioned" = 1,71,107 (D-060 amended). Uncommitted. LIVE-VERIFIED.
- `app/routers/stats.py`: the card query no longer has `WHERE NOT is_placeholder` (the 126 zero-sanction rows count);
  live DB returns 171,107 / 129,941 completed / ₹2,185.26 Cr released. Fallback `frontend/src/chat/constants.js`
  1,71,107; `npm run build` done. `tests/test_scheme_stats.py` 6/6 (+1 regression test). Open: KI-398.

## Earlier: PMAY-G sheet re-test and fixes (2026-10-22, ~00:50). D-060, KI-356..358 (KI-127 decided). Code changed, uncommitted. LIVE-VERIFIED.
- User rule: the 126 zero-sanction PMAY-G registrations are beneficiaries (statewide 171,107; never a "full
  release"; "houses sanctioned" unchanged). Fixed path + model-SQL guard `_pmay_count_placeholders` + prompt rule 1.
- Fixed: "financial summary" / "overall performance" no longer rewritten to "PMAY-G house status" by the c15 overview
  (KI-356; also KI-357, a bare block name answered as the same-name village); a follow-up naming a block / district
  replaces the previous village (KI-358, c01 `_c01_kept_finer_place`).
- VERIFIED: sheet sweep 678/678 (was 654), tester scenarios 76/76, follow-up chats 4/4; pytest 3,300/0; scripts 14/14;
  http harness 102/102, 313/313. Raw Excel = DB row for row. Report `new_docs/PMAY-G_Test_Report_2026-10-22.md`.
- :8401 restarted from the venv at 00:35 onto this code.

## Earlier: MGNREGA re-test, every metric at every level (2026-10-21, night). No app code changed. KI-352..355 opened.
- 30 use cases (783 conversations): **782/783**. New `tests/sheet_runs/mg_matrix.py`: 12 metrics x state / district /
  block / constituency / village x 4 FYs + all years = **270/270**; rankings **35/42**.
- OPEN: KI-352 (ranking by assembly constituency: NULL-constituency rows win, wrong number; "25-26" read as an AC
  name), KI-353 (expenditure by constituency: not in the data; usually "couldn't build a query", once the statewide
  total labelled as the constituency), KI-354 (intermittent MAX-row ranking), KI-355 (admin ranking names no place).
- Report: `new_docs/MGNREGA_Test_Report_2026-10-21.md` §10.

## Earlier: bare village names inside a running chat (2026-10-21, ~22:00). KI-351. Code changed, uncommitted. LIVE-VERIFIED.
- User flow: MGNREGA, West Garo Hills, all years, five questions, then villages named without "village". Recognition
  already worked; the context around it did not. Now: another village typed at a "which <village>?" pause is asked
  for (not the old pause again); a "go back to …" turn remembers the question it ran, so the next bare village keeps
  the measure; the village is shown by NAME everywhere a person sees the state (aside reply, continue chip, topic
  summary, ledger chips, "Back to …") and in the "compare with <scheme>" question; a village answer no longer closes
  with "the figure for <district>"; no stray "shown?" in the place swap.
- VERIFIED: live 13-turn chat (figures = DB); 5 new tests in `tests/test_bare_place_names_2026_10_21.py`; pytest and
  scripts in TESTING.md.

## Earlier: the complete place hierarchy, decided by the database (2026-10-21, ~21:00). D-059 §6, KI-348, KI-349. Code changed, uncommitted.
- User rule (19:50, deadline next day): "block -> block, village -> village, constituency -> constituency; the same
  name at several levels -> ask; the complete hierarchy; no hard-coding." Trigger: "Total sanctioned amount in
  Rasong." after a Chokpot block chip was answered as "Rasong block", null, statewide (KI-348: the chip's level
  tail was carried into the new question).
- Now: a stated level counts only for a name the database holds at it (explicit "not the block" still honoured);
  chip tails never carried; a name at ONE level (for the asking scheme) goes to that level whatever slot the model
  chose; a district named with a finer place settles it; an HQ-alias district never ends the level question; a
  reading the scheme / metric has no data for drops out; the village code is shown by name (banner, state line);
  stray block literals dropped from SQL (Tura). Built and checked with a sweep generated from the database
  (`tests/live_place_hierarchy_sweep.py`: every block, constituency, multi-level name + village sample, MGNREGA and
  PMAY-G). Results: see TESTING.md (final sweep row).

## Earlier: the level of a place comes from the database (2026-10-21, ~18:00). D-059, KI-342..345. Code changed, uncommitted. LIVE-VERIFIED in-process.
- User report: "How many job cards in Mawphlang?" — bare village names not recognised. Diagnosis (live, through the
  graph): on the D-058 code bare villages already resolved, and MAWPHLANG is a block + constituency with no village of
  that name (its block-or-AC question is right). The real faults were in the LEVEL decision: an exact village offered a
  look-alike block under a scheme without its rows (KI-342), typos asked three levels then three villages (KI-343),
  the remembered block / district ignored (KI-344), "centre" read as a village (KI-345).
- How (`settings.PLACE_GAZETTEER`, on): the `entity_resolver` village index also holds each village's code / block /
  district and per-scheme coverage; `match_places` (p95 1.8 ms) feeds the extraction prompt; `collides_across_dimensions`
  exact-village and typo-lead rules; c09 `_c09_gazetteer_settle` (remembered block -> district -> scheme rows; one
  reading left = taken silently) also used by c01 `_place_swap_rewrite`; chips name where each reading lies;
  `resolve_village` narrows to the clearly closest look-alike. The route village-NAME search is unchanged (D-059 §5).
- KI-346 (user's live chat, 18:18): "give me for dalu" after a PMAY-G by-district answer offered village chips. Fixed:
  a "village" mention no village carries that is exactly a block / constituency moves to that slot (c09), and the
  place swap drops a coarser breakdown (c01) -> Dalu block 268 (DB 268).
- KI-347 (user's live PMAY-G chat, 18:33-18:37): place-only follow-ups lost "amount released" (a rejected model
  rewrite sent the bare fragment on), the chat's district was carried onto a village elsewhere (Pakregre), the model
  invented "Dalu village" and "fund utilization", and "its block" to a village pause went to the documents. Fixed in
  c01 (forced place swap on rejection; invented-level and measure-drift rejections), c09 (village's own district),
  c14 (level-only pause reply). Every figure of that chat now equals the DB.
- VERIFIED: `tests/live_bare_place_level.py` 17/17; harness in-process `bare_place` + `user_reported` 33/33; pytest /
  scripts: see TESTING.md. :8401 runs this code. NOT done: full http harness set (stopped: it shares the rate limit
  with the user's browser).

## Earlier: a place named without its level word (2026-10-21, ~17:15). D-058, KI-339, KI-340, KI-341. Code changed, uncommitted. LIVE-VERIFIED in-process.
- User report: after "How much PMAY-G amount was released in East Garo Hills in FY 2023-24?", "in ambare ading" got
  "I don't have information about that"; "in ambare ading village" worked. Now a village, block or constituency
  named bare is a place in a follow-up AND in a new chat (new chat -> the scheme chips), in all six schemes; the
  level question is asked only when the SAME name exists at two levels (Mawlai, Rajabala ask; Wapung, Dalu,
  Mendipathar, Dambo Rongjeng, Sohra answer).
- How: `entity_resolver` village-name index (9,431 names from `dim_geography` + aliases, loaded at startup, lazily
  in c14) -> `place_mentions`; continuation signal, edge whitelist, guardrail overrule; c01 `_place_swap_rewrite`;
  rewrite provenance keeps typed places; `collides_across_dimensions` + c09 `_c09_same_name_village`.
- Also fixed: KI-341 the chat's district was ANDed onto a block in another district (Wapung "no records" -> 9,166);
  KI-339 (DALU / WAPUNG paused on look-alike villages). The ~17:00 http run's P9 / U3 misses (entry below) were
  this work in progress; both fixed after that run (P9's expectation is now "answered as the block").
- VERIFIED: pytest 3,234 / 0; scripts 14/14; harness in-process `bare_place` + `user_reported` 33/33; :8401 restarted
  from the venv 16:53 onto this code, harness http `--stream --tags bare_place` **16/16, 32/32**.

## Latest: context memory acceptance, all paths, caches on and off (2026-10-21, ~17:00). KI-337. Code changed, uncommitted.
- VERIFIED (live :8401, harness http): plain `--skip-cache` **81/81, 266/266**; stream `--skip-cache` **86/86, 281/281**;
  final: stream, caches ON, `--repeat 2`, all scenarios **200/204, 620/624** — the 4 misses are P9 (new
  `bare_place_name.yaml`) and U3 (Dambo Rongjeng block after a Focus Plus village), both inside ANOTHER session's
  in-progress place-only rewrite (c01 `_place_swap_rewrite`, c09; files saved 16:06-16:32 while the run was going).
- `forward_after_statewide.yaml` F1-F5 (user report: statewide one FY -> another district keeps scheme and year) pass
  in every run. KI-337 fixed (c01 `_FOLLOWUP_LEAD` "show me for X"; `is_cacheable` scheme rule).
- pytest **3,212 passed, 0 failed**, 3 skipped; scripts 14/14. Stray :8400 servers stopped (user OK, 2026-10-21).

## Latest: the year asked is the year answered — job cards and the composer (2026-10-21). D-057, KI-336. Code changed, uncommitted. LIVE-VERIFIED.
- From the MGNREGA sheet report (`new_docs/MGNREGA_Test_Report_2026-10-21.md`): job cards were pinned to FY 2025-26
  whatever was asked and answered "across all financial years". Now a job-card question takes the year asked, else
  the chat's year, else the year pause (chip "Every financial year (one figure each)"); all years = one figure per
  year, never summed. One area's job cards are a deterministic query + answer from its rows; the composer is given
  the year the SQL pins (`_entities_with_sql_year`); a village known only by its code is never called "statewide".
- Tests: `tests/test_job_cards_year_2026_10_21.py` (new); pytest **3,199 passed, 0 failed**, 3 skipped; scripts 14/14;
  live job-card checks 11/11; MGNREGA sheet sweep **775/783** (was 755) — DATA-007 24/24 (was 8/24), 0 "statewide" lines
  on local answers (was 74). Still open from the report: DATA-016 households answered as a village count (WAPUNG,
  AMLAREM, MAWRYNGKNENG blocks); "FY24" read as FY 2024-25.
- Same day, KI-338: DATA-016 households answered as a village count / NULL from `entity_type = 'Block'` fixed by
  `_mgnrega_unit_count_not_villages` + `_mgnrega_drop_area_level_entity_type`; DATA-016 53/55 twice. **KI-339 OPEN
  (regression from in-progress entity_resolver work, ~16:00): a bare block name (DALU, WAPUNG, Ri Muliang) pauses with
  village look-alikes only, no block option** — DATA-003 51/55.
- Same day, KI-337: DATA-014 "couldn't build a working query" (repair drifted to `fact_mgnrega_employment`) fixed by
  `_mgnrega_fact_to_view` + `_mgnrega_village_rank_placeholders`; live DATA-014 **56/56 twice**; pytest **3,205 passed, 0 failed**.

## Latest: new chat asks scheme -> district -> year; a chat carries its scope to any scheme (2026-10-21). D-056, KI-335. Code changed, uncommitted. LIVE-VERIFIED (:8401).
- User report (live chat): a new chat asked the scheme, then only the year (the district silently defaulted to all of
  Meghalaya); after "MGNREGA · West Garo Hills · FY 2022-23", "how many households for PMAY-G" re-asked the year and
  dropped the district. Now: NEW chat -> scheme chips -> district chips (+ All of Meghalaya) -> FY chips -> answer;
  inside a chat a new question on ANY one scheme keeps the chat's place and year (year only if that scheme holds it,
  else the FY chips ask with the place kept); the user's own words replace only what they name ("for all of
  Meghalaya", "by district", a district, a year).
- Also fixed on the way: the closing scope sentence called an inherited West Garo Hills figure "statewide"
  (c09 now fills `display`); the year callback read time backwards ("up from 572 in FY 2022-23" for FY 2017-18);
  an answer that inherited a scope or used a default is never written to / served from the shared answer cache for a
  question that would inherit (router `is_cacheable`, `_mark_context_dependent(inherited=)`).
- VERIFIED: `tests/test_new_chat_and_scheme_switch_2026_10_21.py` (25); harness `scenarios/user_reported_2026_10_21.yaml`
  N1-N3 = the user's conversation turn for turn, 12/12 user-reported scenarios live. See TESTING for the full runs.

## Earlier: clarification pills, design #11 "Plain card · Pill chips" (2026-10-21). Frontend only (built), uncommitted. HEADLESS VERIFIED.
- VERIFIED: `Clarify` in `frontend/src/chat/components/Messages.jsx` + the `.clarify-*` block in `chat.css`. Under the
  question: a divider, a "Choose a …" line naming what is asked, a rounded search box, then pills; "+N more" past the
  limit; the "All …" reply (All years / All of Meghalaya) is the outlined pill at the end; the tapped pill fills.
- The kind comes from `clarification.rule` (`RULE_KIND`: scheme-* -> scheme, year-* -> year, scope-not-specified /
  region-needs-district -> district, entity-ambiguous -> place, tranche) or, when absent, from the labels ("FY …" ->
  year, scheme names -> scheme). Scheme: search + short names (the "(rural housing)" note is the tooltip); year: no
  search, all pills, "All financial years combined" shown as "All years"; district: search, 8 + "+4 more".
- The three-card scheme picker (`.scheme-groups` / `.sg-*`, chart-hue dots) is removed. No backend change.
- Headless: `tests/ui_headless/clarify_pills.py` OK at 1280 and 390 px (scheme / year / district, no overflow).

## Latest: context memory per the user's rules (2026-10-19, ~16:30). D-055, KI-330, KI-331, KI-334. Code changed, uncommitted.
- Idle window 8 h (`SESSION_TTL_SECONDS` = `CONTEXT_IDLE_EXPIRY_SECONDS` = 28800), turns 50, ledger 20/topic.
- Inside one chat the scheme is never asked again; only a new chat with no scheme (and no scheme-pinning words) asks (D-055,
  replaces D-045's cross-scheme default for an unnamed scheme). A same-scheme new question keeps the chat's year, and its place
  on "there" / "that district" (KI-331). A pure measure change no longer drags the old measure along (KI-334).
- Acceptance: harness `scenarios/user_reported_2026_10_19.yaml` (9 conversations: the user's own failures and rules),
  `tests/live_context_matrix.py` (42 conversations, all six schemes), `tests/test_context_rules_2026_10_19.py`.

## Latest: chart-type requests and complaints redraw the last answer (2026-10-19, ~16:30). KI-333. Code + frontend changed (built), uncommitted. LIVE + HEADLESS VERIFIED.
- "pie chart" / "But give me only pie chart." / "So I asked about pie chart, right? But why you are giving line chart? Give me a wide frame" after a by-district answer -> the same 12 districts as a pie (an apology for the complaint, `chart_wide` -> taller card). By-district answers no longer default to a line.
- Files: c15 (`_chart_view_request`, `_chart_view_question`, `_attach_preface` sets `chart_wide`), c14 step 0h-view, c13 `_chart_hint`, `app/topic_memory.py` (`resolve_reference` skips view requests), `frontend/src/chat/analytics.js`, `components/Messages.jsx`, `styles/chat.css`.

## Earlier: a scheme swap after a comparison keeps the comparison (2026-10-19, ~15:45). KI-332. Code changed, uncommitted. LIVE-VERIFIED (8401).
- After "Compare PMAY-G and MGNREGA beneficiaries and amount ...": "now give me for cm elevate" -> CM Elevate dataset pause whose chips keep the scope ("Same comparison for CM Elevate applications: beneficiaries and amount in a graph for Meghalaya (statewide), all financial years") -> the comparison card for that scheme alone (8,840 applications, "no money recorded"); Legacy chip -> 2,823 / Rs 82.90 crore; "what about focus plus" -> Focus Plus card for all years (no year re-ask); "give me for mgnrega" narrows to MGNREGA; "and cm elevate legacy too" -> three-scheme comparison.
- Files: `app/pipeline/common/c01_followups.py` (`_comparison_swap`, `_is_same_comparison_question`), `app/cross_scheme.py` (`_SAME_COMPARISON`, one-scheme title, years note), `app/pipeline/common/c13_compose_and_data_stages.py` (CM Elevate pause before a one-scheme card). Test `tests/test_comparison_scheme_swap_2026_10_19.py` (16); swap / follow-up / cross-scheme suites 342 passed.

## Earlier: charts show both dimensions (2026-10-19 afternoon). KI-325. Frontend changed + built, uncommitted. LIVE-VERIFIED.
- A scheme x year / district x year result is drawn with the period on the x-axis and one series per scheme / district
  (`TwoDimChart`: Bar / Stacked / Line / Donut, legend + axes caption); a one-series line says "since …" only over periods.
  Headless check at 320–1440 px. Files: `frontend/src/chat/{analytics.js,chartTheme.js,text.js,components/Charts.jsx,components/Messages.jsx}`, `styles/chat.css`.

## Latest: year asked when nothing carries one (2026-10-19). D-053. Code changed, uncommitted.
- User decision (evening 2026-10-18, screenshot "total benifishjeries for MGNREGA" -> 1,494,437 household-years with no
  question asked): the all-years default of D-045 is for a turn whose conversation already has a year. A metric question
  with no year in its text, entities or `prior_resolved` now pauses with the FY chips again; follow-ups that inherit a
  year, the chip replies, time series, job cards and CM Elevate are unchanged. `c13 _data_clarification_stage`
  (`_ask_year`), `tests/test_year_asked_without_context_2026_10_19.py` (7 tests) and a pause -> reply -> follow-up
  graph test in `tests/test_pipeline_graph.py` (`test_fresh_question_without_a_year_asks_with_answer_defaults_on`).
- KI-330 (user, 15:03): "now give me for cm elevate" after a CM Elevate Legacy answer now switches to the CM Elevate
  applications dataset instead of repeating the Legacy answer; continuing questions keep the thread rule
  (`cm_elevate._cm_switch_to_applications`, c14 pins, c01 swap opening). Coexists with KI-329 (comparison swap).
- KI-331 (found by the KI-330 live probe): a new question on the same scheme as the thread, with no year of its own,
  keeps the thread's year or all-years choice instead of asking the year again (`c14 _same_scheme_context_year`).
- KI-324 (from the parallel session's handoff): a typed "all of them combined" / "all" / "combined" to the year pause now
  resumes as the "All financial years combined" chip (`c05 _is_all_years_reply`, `c14` pause-reply branch). The other half
  of KI-324 did not hold: the pause has five chips (harness report 12:25).
- KI-327 (user screenshot 12:08, Focus Plus Gobekram village WGH -> "now give me for dambo rongjeng block"): the block's
  own district (East Garo Hills) now replaces the inherited one in the resolved entities, the chip and the question text;
  a name that is no village but exactly a block is placed as the block; `c10 _resolved_district_literal` is the SQL
  backstop. `tests/test_block_in_other_district_2026_10_19.py` (7). The user's note on the ideal flow (classifier ->
  state -> entity resolution against canonical metadata -> clarification -> SQL) is what the graph already does; the gap
  was that the resolver's correction never reached the question text or the SQL literal.
  LIVE-VERIFIED 2026-10-19 13:05 through `POST /api/query` as superadmin (state-rd is capped at district level, so the
  village turn is denied for it): Gobekram village WGH FY 2022-23 = 30,000 -> "now give me for dambo rongjeng block" and
  "now give me for dambo rongjeng" both resolve block DAMBO RONGJENG + district EAST GARO HILLS, SQL filters East Garo
  Hills, answer 20,165,000. `_resolved_district_literal` acts only with a resolved block beside the district, so the
  KI-183 deny of a repair that moves the geography is unchanged.
- Also 2026-10-18: composer no longer stays 160px tall after a voice dictation (`frontend/src/chat/App.jsx`, the
  auto-grow effect skips the hidden recording box and re-measures when shown); port moved 8400 -> 8401 in `.env`,
  `app/config.py`, Docker files, Vite proxy, README.
- Full pytest 2026-10-19 11:30: **3,009 passed, 1 failed**, 2 skipped (39 min). The failure,
  `tests/test_focus_legacy_usecase_fixes.py::test_ki148_scheme_question_offers_only_constituency_schemes`, expects 7
  scheme-picker options and `c03 _scheme_clarification` now builds 6 (the seventh chip was dropped earlier; the chat UI
  renders "Compare across schemes" itself). Not from this change; the assertion was updated to 6 on 2026-10-19. Live D-053 probe through `POST /api/query` on :8401:
  fresh no-year question -> FY chips; FY 2023-24 chip -> 410,200; "break that down by district" -> no re-ask; a question
  naming its year -> no pause. Observed: the 9B composer wrote "across all financial years" and "for FY 2023-24" in one
  sentence on a correctly single-year SQL (wording only). **Fixed 2026-10-19 afternoon (KI-326):** `c12 _finish_answer`
  drops the all-years phrase on words when the resolved period is one FY (`_drop_all_years_phrase`);
  `tests/test_single_year_phrase_2026_10_19.py` (7). Servers on :8401 / :8400 restarted from the venv at 13:21 and the
  change live-checked through `POST /api/query` (West Jaintia Hills FY 2022-23 -> 976,990; Ri Bhoi FY 2021-22 -> 87).
- Test isolation (pre-existing, found 2026-10-19 13:20): `tests/test_pipeline_graph.py` is green alone (48) and after
  either new test file, but 15 of its tests fail when `tests/test_admin_level_collision.py` runs BEFORE it in the same
  process (the graph tests then hit a real pool: "'NoneType' object has no attribute 'connect'"); in the full
  alphabetical run the gap between the two files masks it. **Fixed 2026-10-19 afternoon:** the script's module-level
  stubs (`p.resolve_village`, `er.resolve_village`, `p.extract_entity_mentions`, `p.constituency_contents`) are
  restored when its checks end, so nothing leaks into later tests; admin script then graph suite in one process
  = 48/48, the script standalone still passes.
- Pre-existing, not from this change: `tests/test_pipeline_graph.py` 3 failures (the 2026-10-18 answer-framing sentence
  "This figure is for CM Elevate, East Khasi Hills district, across all financial years." is appended; the asserts expect
  the bare sentence; green since). The note that `app/pipeline/schemes/cm_elevate.py` `_cme_digits_for_number_words`
  raises NameError was WRONG (checked 2026-10-19 afternoon): `_NUMBER_WORD_MATCH` / `_NUMBER_TENS` / `_NUMBER_WORDS` are
  defined in `common/c12_answer_numbers.py` (word-level Matcher, no regex) and the pipeline files share one namespace, so
  they resolve at call time ("Five CM ELEVATE applicants" -> "5 ..." verified; pinned in
  `tests/test_single_year_phrase_2026_10_19.py`). The helper's docstring now says where the names live.

## Latest: every data answer reads as a briefing line (2026-10-19 morning). D-054, KI-321, KI-322. Code changed, uncommitted.
- The bare fallback ("1,494,437 household years.") is framed with scheme, plain-words measure, area, period and caveat;
  every DATA answer gets thousands separators and, when it names neither scheme nor area, one closing scope sentence
  (finalize node). Live-verified through the API. KI-322 found on the way: two totals for "households employed".
- NOTE: the parallel session is changing year handling (D-053: a fresh question with no year now ASKS which year); its new
  test file fails 7 tests while in progress — not this session's.

## Latest: conversation harness (2026-10-18, evening). New `tests/conversation_harness/`. Code added, uncommitted.
- Declarative multi-turn scenarios (YAML) + per-turn checks (scope components, figures, leaks, chips, pauses, same scope /
  same numbers as an earlier turn, DB truth), two drivers (live HTTP API — plain / stream / any account — and in-process),
  JSON reports, exit codes. 17 scenarios cover the context-memory review A–E, the conversation-meta flows and comparisons.
  First live run 16/17; the miss exposed KI-315 (verifier false positive on a by-block breakdown) and a failed turn
  polluting the next follow-up's rewrite — both fixed; full set now **17/17 scenarios, 72/72 turns**, stream driver 3/3.
  It validates only; it never guides the chatbot.
- Rule from today: every conversation / context change is accepted with the **http** driver, not an in-process probe.

## Latest: context memory acceptance through the HTTP API (2026-10-18, late afternoon). KI-315, KI-316, KI-318. Code changed, uncommitted. LIVE-VERIFIED.
- Every scenario of `documents/Context_Memory_Forward_Backward_Review_v3.docx` (A forward, B out-of-context + B5 leak, C backward,
  D general, E hierarchy) plus a harmful refusal, a denied follow-up, five asides in a row, the cached path and the SSE stream was run
  through `POST /api/query` / `/api/query/stream` against the running server (scratchpad `http_probe.py`, a JWT minted in-process for
  `state-rd` and `superadmin`). All pass. Fixed on the way (KI-316): a refusal and a denied turn keep the topic; roll-ups
  ("back to the district level", "whole district", "statewide") are deterministic from the topic ledger with the lower levels
  cleared; before, the block figure was labelled as the district / state.
- NOTE for testers: on the server a session is rehydrated every request and holds only its last turn; earlier questions live in
  the topic ledger. An in-process probe (full `session.turns`) can pass where the server fails. Test through the API.
- Also (user screenshot 16:33, KI-320): "compare with pmay" after an MGNREGA figure now gives the MGNREGA-vs-PMAY-G cross-scheme
  table in the same place and year (not PMAY-G alone over all years); "compared to Focus Plus" shows "no data for FY 2023-24";
  "what about 2022-23?" and "by block" continue the comparison. Live-verified through the API.
- Open: KI-318 ("go back to <block>" after a year change), KI-315 (correction -> PMAY-G sanctioned by block, verifier false positive).

## Latest: conversation about the conversation (2026-10-18, afternoon). D-052, KI-310..312. Code changed, uncommitted. LIVE-VERIFIED.
- New `app/pipeline/common/c15_conversation_meta.py`: recap / explain (9B, grounded) / misread (apology) / suggest / reason answered
  from the previous turn (edge stage 0-b); correction / breakdown change the question (follow-up stage 0h) and the answer opens
  with an apology (`_attach_preface`, finalize); place overview -> the scheme's headline question (route stage 1i); "last year"
  with no year in play -> which-year pause (follow-up stage 0i). Also: "thank you, it is very helpful" is thanks; "farmer" is
  domain vocabulary and a farmers question asks which Focus; an opening "okay" no longer hides a follow-up.
- Live (router path, real models + megh_db): houses 2023-24 -> "why are you not giving me district wise?" -> district-wise with
  apology -> "okay give me for East Khasi Hills" 17,281 -> "that's wrong, I asked for completed houses" -> EKH completed 12,038
  -> "ok and Ri Bhoi?" 6,847 -> explain / what next / thanks. Dalu block officer -> overview (8,892.08 lakh, 2,646,057
  person-days) -> "compare with last year" asks which year -> FY 2024-25 -> "why is it so low?" -> reason + chips.
- Open: KI-311 (MGNREGA two-year / two-fact breakdown shapes), KI-312 (Focus Plus overview drops the amount).

## Latest: "show me the districts, I'll choose one" (2026-10-18 afternoon). KI-317. Code changed, uncommitted. LIVE-VERIFIED.
- Right after a DATA answer, a request to see the districts and pick one now pauses with the previous question once per
  district (chips; a typed district merges back) instead of going to the KB. Step 0g of `_turn_followup_stage` (c14);
  helpers `_asks_to_pick_district`, `_pick_district_clarification` (c05).
- Rephrase guard: contractions ("don't") are ordinary words, not lost names (`_is_known_word`, c02).
- pytest 2,834 / 0 failed; scripts 14/14; NL->SQL eval 74/74. Districts only (blocks / villages not offered this way).

## Latest: context memory, all phases of documents/MAIN_Contex.pdf (2026-10-18). Code changed, uncommitted. D-050, KI-307. LIVE-VERIFIED.
Phases: P1 cache safety + P2 forward fixes were built 2026-10-16 (KI-306); P0 + P3..P6 built today.
- **P3 ledger + backward** (`app/topic_memory.py`): each topic keeps its last 6 questions with their scope (in the
  snapshot). "Go back to the East Khasi Hills one", "the first question", "question 3", "the job cards question",
  "MGNREGA ka 2022 wala figure", "you showed X for EKH, what about Ri Bhoi?" restore that question's scope and
  re-run it; several matches -> chips (`ledger-ambiguous`); "what did we discuss?" lists the questions (an aside).
- **P4 constrained model pick** (`topic_memory.resolve_reference`, called from `_turn_context_stage`): a backward cue
  the rules place nowhere -> the 9B (`call_rewriter`, role `reference`) picks a listed ledger id / NONE / ASK; other
  output = ASK. Prompt carries each scheme's meaning (live: "employment" -> MGNREGA person-days).
- **P5**: a new district clears the old block / village (`context_manager.update_state`); restores are re-authorised
  by the graph's authorize node; denied turns are never stored.
- **P6**: `scope_banner` on every DATA answer (`_attach_scope_banner` in node_finalize; "(from earlier)" on a
  restore; UI pill `ScopeBanner`; stored for reopened threads). Idle expiry sets the context aside
  (`Session.expired_ctx`, durable); the first reply carries `continue_offer`; tapping it restores (`ContinueOffer`).
  `npm run build` done.
- Flags: `BACKWARD_RESOLVER_ENABLED`, `CONTEXT_LEDGER_PER_TOPIC` 6, `LLM_REFERENCE_ENABLED`,
  `LLM_REFERENCE_TIMEOUT_SECONDS` 8. Graph still 22 nodes.
- Tests: `tests/test_topic_ledger.py` 75. Full pytest 3 shards **2,779 passed, 0 failed, 2 skipped**; scripts
  **14/14** (incl. test_context_manager.py, failing earlier). Live: N, O, P, Q, R pass (see TESTING.md);
  full A..R run: full A..R on 3 workers 79/83 checks; then H fixed (rehydrated-worker antecedent, see KI-307) and passes; remaining: E T1 (expects a 'which scheme?' pause — outdated by D-045 answer-defaults, not a regression) and F T3 (KI-308 guard/verifier ping-pong, fails with the D-050 features off too).
- **Stop -> "continue"** (user request): a stopped streamed question is remembered (`Session.stopped_ctx`,
  `routers.query._remember_stopped`); "continue" / "resume" / "go on" answers it (`conversation_layer`); "stop"
  typed while an answer runs stops it (UI `stopContinue.js`). Tests `tests/test_stop_continue.py`; live-verified.
- **D-051 (user decision):** 50 turns per session, 20 questions per topic (160 in all), 4-hour idle window (was 8 /
  6 / 30 min). `.env` updated locally; **deploy `.env` files still say 30 min / 8 turns** — change them on deploy.
- **Late 2026-10-18 (user: "it must work 100%"):** the user's own UI thread (app.conversation_turns, 07:18-07:26)
  replayed as live scenarios U1 / U2 — every follow-up had lost the context (KI-309, fixed: "what is the total …"
  is a measure follow-up and never a term question; manraya -> MGNREGA; spoken digit years). KI-308 fixed (verifier
  may not remove a resolved place filter). New `tests/live_context_matrix.py`: 7 flows x 6 schemes = 42 live
  conversations; first run 21/23 before the fixes (DB dropped at #24). **2,870 passed, 1 failed, 2 skipped**; the one failure (`tests/test_scheme_years.py::test_route_stage_answers_years_before_the_knowledge_split`, an `inspect.getsource` pin) was a run artifact — another session saved `c14_turn_stages.py` at 13:29 while the 33-minute shard was running, so the loaded code and the file disagreed; re-run alone afterwards: 26 passed. Effective result **2,871 passed, 0 failed**; final re-run after the CM Elevate-family fix: **2,940 passed, 0 failed**, 2 skipped. (That session also added `c15_conversation_meta.py` and two test files; see HANDOFF.); **42/42 conversations** (MGNREGA, PMAY-G, Focus Plus 21/21 and Focus Legacy F2..F7 in run 2 — the run then hung on a dead DB connection after a gateway ReadTimeout and was stopped; Focus Legacy F1 14/14 checks and CM Elevate + CM Elevate Legacy 14/14 conversations, 93/93 checks, in run 3 after the CM Elevate-family fix and the applications-only wording). Caveat: the 27 run-2 conversations ran before the CM-family edit (topic_memory / c03 / context_manager), which only changes behaviour when a CM Elevate name is involved.
- **Browser check done** (`tests/ui_headless/`): banner, typed stop -> continue, go back, history all correct at
  phone / tablet / desktop, no overflow, no console errors. Fixed on the way: a pure "go back" is no longer filed as
  a new numbered question. Not exercised in a browser: the "Continue with …" chip after 4 h idle (offline tests only).
- **Evening fixes:** KI-314 (snapshot load/save retried once on a DB drop) and KI-319 (a cache-served answer now updates the structured state and carries the banner) — both offline-tested; new `tests/test_session_sync_retry.py`, `tests/test_cache_hit_context.py`; `tests/ui_headless/idle_chip_flow.py` checks the "Continue with …" chip in a browser with a 60 s idle window.
- **"Compare this with the MGNREGA figure you showed"** now works (`conversation_layer.comparison_with_earlier`
  -> the two-scheme comparison for the active scope). Idle chip confirmed in the browser (60 s window) after making
  its acknowledgement an aside. Wording probes V1..V6 in `live_context_validation.py` (see TESTING).
- End of day: full pytest **2,971 passed, 0 failed**, 2 skipped; live probes V1..V6 all pass; 42/42 matrix.
- Not built: WI-9 (Qdrant over archived turns).

## Earlier: following the ingestion team's DB changes of 2026-10-16. Code changed, uncommitted. D-049, KI-304/305.
Source: `CHATBOT_DB_CHANGES_2026-10-16.md`; reply `docs/Chatbot_Answers_to_Ingestion_Team_2026-10-16.md`. **No DB change.**
- `schema_introspect`: prompt now carries column UNIT + exact VALUES lists, the metric definitions (the old reader used
  wrong keys and printed none), `v_join_rules`, `v_data_coverage`; LIVE SCHEMA hides privacy tables and every column
  `megh_readonly` cannot SELECT (`v_cm_elevate.scheme_specific`); fact-table notes dropped.
- Guards: `_prohibited_row_join` (any pair in v_join_rules), `_readonly_denied_column_in`; `sql_guard` refuses the 3
  privacy tables (`private_table`).
- CM Elevate: every count = `COUNT(DISTINCT request_id)` (8,840); sector -> `sector_id` column; gender and
  Approved/Rejected -> measure-not-held ("not available"); "pending" stays On Hold (user decision). Few-shots adapted at
  load (`annotations._fit_examples_to_db`): 13 CM Elevate, 1 Focus Plus, 3 Focus Legacy dropped (meta / locked column).
- Rules: Focus Plus/Focus Legacy money = rupees (catalog UNIT); no `meta.*`; no `scheme_code 'FOCUS'`.
- Pools: `DB_POOL_MIN_SIZE` 10 -> 1 (also local `.env`), `DB_POOL_IDLE_SECONDS=120`.
- **Open (KI-304):** the app still logs in as `postgres` — needs the megh_readonly password from the ingestion team.
- Tests: pytest **2,667 passed, 0 failed**, 2 skipped (3 shards; +26 in `tests/test_db_changes_2026_10_16.py`, 2 stale
  cases updated). NL->SQL eval 95.9% (71/74) — see TESTING.md for PM-04.

## Latest: spoken / FY2022-23 years, audit trace, /metrics accuracy (2026-10-16, late). Uncommitted. KI-289, KI-305.
- Years: "FY2022-23" and spoken years are read (errors.md cases 10-11, both live-verified).
- Audit (JSONL + app.query_audit) now stores SQL, error, few-shot ids, repairs, verifier rejections, outcome,
  request id; the new columns are added by `appdb.ensure_schema` on the next server start.
- /metrics `accuracy`: live SQL outcome / repair counters (per worker) + latest full NL->SQL eval run.
- pytest **2,704 passed, 0 failed**.

## Earlier: one query per scheme (KI-011) + RAG score floor enforced (KI-304) (2026-10-16, evening). Uncommitted.
- Multi-scheme SQL prompts over the 15,360-token budget now fan out to one query per scheme (each with its own
  guards / repairs), rows tagged `scheme`. Live-verified on a CM Elevate + Focus Legacy question.
- `RAG_MIN_SCORE` has no fallback any more. KB v3 eval: 92.1% -> 90.2% correct, made-up 13.4% -> 14.4% (noise);
  the 0.30 floor never binds on KB v3 (all pieces >= 0.548). Results: tests/rag_eval/results/2026-10-16_kbv3_*.

## Earlier: no regex anywhere + business definitions (2026-10-16). Code changed, uncommitted. D-047, D-048.
- **No regex (D-047):** every regex in app/, tests/, data/ and frontend/src replaced — English text by the word
  matcher `app/text_match.py`, SQL by `app/sql_ast.py`, the UI by string methods (`npm run build` done).
  pytest **2,606 passed, 0 failed**; scripts 13/14 (`test_context_manager.py`: the separate memory-retention change).
- **Business definitions (D-048, errors.md cases 1-3, KI-229 / KI-035 / KI-040):** backbone rules (gender; people
  across years; MGNREGA households vs persons), 12 executed few-shots, and the `_mgnrega_people_years_alias`
  rewrite + answer note, and a verifier false-positive filter for those shapes. **LIVE-VERIFIED 2026-10-16: cases
  1-3 all correct** (23,758 men; 105,813; 1,494,437 household-years labelled as such). Held-out accuracy:
  93.2% (16:24) then 100% (18:09, 74/74). Caveat: another session changed code, the DB and reworded FP-12 and
  CE-11 in questions.yaml between those runs; on the 72 unchanged questions the 18:09 run is 72/72.

## Earlier: all SQL handling moved from regex to SQLGlot (2026-10-15, evening). Code changed, uncommitted. D-046, KI-303.
New `app/sql_ast.py` (shared SQLGlot helpers). Converted: `auth.py` (district/block filters read on the tree: UPPER(col),
every IN value, OR branches; unparseable SQL refused for restricted users), c01/c02/c10–c13 and all six
`app/pipeline/schemes/*.py` guards and rewrites, `_extract_sql` (token stream), followups.py, the offline
`data/cm_elevate/prompt_assembler.py` validator and the SQL checks in tests/harnesses. SQL generation/repair send no
`guided_regex`; `SQL_GUIDED_DECODING_ENABLED` is no longer read (kept so an existing .env loads). Fixed on the way:
the MGNREGA employment x expenditure fan-out inside a CTE is now flagged. Remaining regex reads English only
(questions, answers, verifier complaints, DB error text, row key names). Tests: pytest **2,585 passed, 0 failed**
(baseline 2,558); scripts 13/14 — `test_context_manager.py` fails on the separate, uncommitted memory-retention
change in `app/conversation_memory.py` (a `range` condition in the Qdrant filter; not SQL work).
Visible change: a rewrite that fires regenerates the SQL in SQLGlot's layout (`CAST(x AS DECIMAL)`, one line).
LIVE held-out NL->SQL eval (tests/nl2sql_eval, VPN, superuser override as for the baseline): **79.7% (59/74)** vs
78.4% baseline-final — 0 regressions, 1 fixed (CL-05). Results: `tests/nl2sql_eval/results/2026-10-15_2032_sqlglot-only.json`.

## Latest: empty duplicate table under cross-scheme answers removed (2026-10-15). Code changed, uncommitted. KI-302.
The chat UI skips its pivot table and charts for `cross_scheme` results (the answer text already has the tables); the
flag is stored with the turn for reopened threads. `npm run build` done. Tests: `tests/test_cross_scheme_history_flag.py`
(2 passed). Not yet checked in a live browser.

## Latest: pipeline.py split into the app/pipeline/ package (2026-10-15). Code moved, uncommitted. Behaviour-identical.
The 18,698-line `app/pipeline.py` is now `app/pipeline/`: `common/` (14 shared-step files c01..c14) and `schemes/`
(one file per scheme: mgnrega, pmay_g, focus_plus, cm_elevate, focus_legacy, cm_elevate_legacy), executed by
`__init__.py` into one shared namespace; LangGraph (`pipeline_graph.py`, 22 nodes) unchanged. Verified: slices re-join byte for byte,
1,065 names / 504 functions / 362 regexes identical; pytest 2,372 passed, 2 skipped; scripts 14/14. Tests that read
the pipeline source now join the files in `_PIPELINE_FILES` order. Same day: `/api/scheme-stats` (app/routers/stats.py) feeds the
welcome cards live megh_db figures. `sqlglot` (needed by app/sql_guard.py) installed in .mvenv, not yet in requirements.txt.

## Latest: answer-defaults + hierarchy matrix (2026-10-14). Code changed, uncommitted. LIVE-VERIFIED (village run in progress).
User decision (D-045): answer, don't ask — no year = all years combined, no area = all of Meghalaya, no tranche = all
tranches, no scheme = each scheme that records the measure (ANSWER_DEFAULTS_ENABLED, default on). From the user's
2026-10-13 UI session (300 turns in app.conversation_turns) and a new hierarchy matrix (every scheme x every measure
x state / district / block / constituency / village, tests/sheet_runs/matrix/): KI-291..299 fixed, KI-289 closed,
plus job cards as a stock, FY2022-23 spacing, guardrail data-question overrule, relative "that", unasked year
splits, MGNREGA expenditure components, chip pin for every scheme, "<exact name> village" wins over the extractor.
Matrix: state/district/block/AC 2,150/2,150; villages in progress. NOTE: the UI the user tested runs the GitHub
main line (NRLM onboarding, 36b7427), not this branch — merge needed before these fixes show there.

## Latest: Cross Scheme sheet test + fixes (2026-10-13). Code changed, uncommitted. LIVE-VERIFIED.
CROSS-1..CROSS-20: 9th run 0/20 (18 paused, 2 wrong), after the fixes 20/20; 8,649/8,649 conversations (every scheme
combination, level, FY and village). New `app/cross_scheme.py` (D-044): comparisons of 2+ schemes answered
deterministically, each scheme by its single-scheme rule, never summed. KI-280..288 fixed; KI-289 ("FY2022-23" not read
by the shared resolver for single-scheme questions) and KI-290 (low) open.

## Latest: CM Elevate Legacy sheet test + fixes (2026-10-12). Code changed, uncommitted. LIVE-VERIFIED.
TC-01..TC-36: 9th run 25 Pass / 11 Fail, after the fixes 36/36 (300/300 cases; every CM Elevate Legacy village
1,051/1,051). User decision: a bare "CM-ELEVATE" data question defaults to CM Elevate Legacy unless it uses
applications-only words. Other fixes KI-274..278: who-is-it-for questions are knowledge; application breakdowns
ranked descending; Tura Municipal Board stored name corrected in the rules; HQ-town constituency names; village
names kept whole by the rephraser. All seven workbook sheets are done.

## Latest: Focus Legacy sheet test + fixes (2026-10-12). Code changed, uncommitted. LIVE-VERIFIED.
FOCUS TC-01..TC-28: 9th run 19 Pass / 9 Fail, after the fixes 28/28 (231/231 cases; every Focus Legacy village
3,384/3,384). Fixes KI-264..272: "FOCUS" is the scheme, not a variant / group-type filter; overview, list and
date-range requests not refused; duplicates state the repeat payments; constituencies offered for HQ-town names and
"North Tura"; calendar months read correctly; FY comparisons per year; Rs 5,000 per member stated; a village name is
never a producer-group / product filter; unselected GROUP BY dropped; village names masked for the harm checks.

## Latest: Focus + sheet test + fixes (2026-10-11). Code changed, uncommitted. LIVE-VERIFIED.
FOCUS-001..030: 9th run 27 Pass / 3 Fail, after the fixes 30/30 (163/163 cases; every Focus Plus village
3,513/3,513). Fixes KI-260..263: a block tagged as a district read as the block; tranche / batch status breakdowns
count beneficiaries incl. "status not recorded"; "(GARO)" in a village name is not the region; a ward named in full
beats the district-alias question.

## Latest: CM Elevate sheet test + fixes (2026-10-10). Code changed, uncommitted. LIVE-VERIFIED.
CM-ELEVATE-OFF-001..030: 9th run 20 Pass / 10 Fail, after the fixes 30/30 (529/529 cases; every CM Elevate village
2,087/2,087). Fixes KI-253..259: applicants never rephrased to applications; CM Elevate wording routed to the data;
deterministic sector answers; block-also-village asks which; every named district kept; programme x sector totals;
programme word never taken as the village.

## Latest: PMAY-G sheet test + fixes (2026-10-10). Code changed, uncommitted. LIVE-VERIFIED.
- PMAY-OFF-001..028: first run 25/28 TCs clean; after the fixes 28/28 — sheet cases 678/678 and every PMAY-G village
  5,121/5,121 on the final code. KI-249..252 (placeholder registrations in counts, rephrase-driven knowledge routing,
  place names tripping guards, chip questions rephrased).

## Latest: full-hierarchy pass, General + MGNREGA (2026-10-10). Code changed, uncommitted. LIVE-VERIFIED.
- All 6,491 MGNREGA villages 6,491/6,491; MGNREGA sheet 783/783 (30/30 TCs); General 24/24. KI-244..248 fixed
  (look-alike block/AC pause for exact village names, rephraser name suffixes, bracket-tolerant chips, wages-vs-materials
  with no rows, duplicate village rows, a village name read as violence).

## Latest: MGNREGA sheet test + fixes (2026-10-09). Code changed, uncommitted. LIVE-VERIFIED.
- MGNREGA sheet (DATA-001..030) run through the LangGraph pipeline: 783 conversations across all districts, blocks,
  constituencies, 2 villages per district and all years, every figure checked against megh_db. First run 13/30 Pass;
  after the fixes 30/30 (every case clean). KI-236..243: expenditure asked "which scheme?", the guardrail model refused
  village figure questions, the rephraser split two-word villages / dropped "expenditure" / widened to all schemes, the
  constituency whole-or-part pause, HQ-town blocks answered as districts, AVG/SUM ratio, dropped/merged figures in the
  combined and breakdown answers, village lists truncated (LIMIT 100) or miscounted.

## Latest: General sheet test + fixes (2026-10-09). Code changed, uncommitted. LIVE-VERIFIED.
- Ran the General sheet of `reference_documents/Test Case Results - 30th Sep 26.xlsx` (TC-001..024) through the LangGraph
  pipeline with live models and megh_db: 262 conversations, data cases checked against the DB, TC-023 across all 12
  districts, 55 blocks and 24 villages (182/182). First run 15 Pass / 9 Fail; after the fixes all 24 Pass.
- Fixed (KI-228..234): listing said five schemes; Focus Legacy "how to apply" answered with documents; knowledge answers
  named "reference material"; document lists had no required/optional split; "the two schemes" read only the last turn;
  rule questions with "how many / how much" went to DATA; guardrail model SCOPE verdicts refused how-to, unknown-scheme and
  short follow-up questions (also fixes KI-225); "which year was the highest?" paused or kept the previous year;
  "show it year-wise" during the year pause; village top-1 called "top-ranked in Meghalaya".
- KI-235 (cosmetic fallback wording) fixed later the same day.

## Latest: conversation layer (2026-10-08, D-043, KI-222). Code changed, uncommitted. LIVE-VERIFIED.
- New `app/conversation_layer.py`, called once in `routers.query._answer` before the caches. Pipeline,
  graph and DB unchanged. It adds: idle expiry (30 min, `CONTEXT_IDLE_EXPIRY_SECONDS`; the durable snapshot
  used to come back at any age), reset ("start a new topic", "forget the previous question", "let's start
  again"), plain-words returns ("what was the PMAY-G information again?"), and the KI-222 fix: "How many
  beneficiaries are there?" after "Tell me about PMAY-G" now continues with PMAY-G instead of "which scheme?".
- Topic memory (`app/topic_memory.py`, written earlier the same day, kept) is now in the durable snapshot
  (`Session.topics`, `context_at`), and an explicit topic switch is never cached (`is_cacheable`).
- Tests: pytest **1,926 passed, 0 failed**; scripts 14/14; live: 15 multi-turn scenarios through `_answer`.
- Live test cases 36/38 (follow-up, switch, return, pronoun, clarification, override, general, reset, expiry all pass);
  KI-226 fixed in the layer (thanks / hi mid-topic no longer ends the topic). The 2 failures are KI-225: the new guardrail
  model check refuses the scheme swap "give me for pmay" (pre-existing regression, not the layer).
- Open: KI-223 (pre-existing: "What about MGNREGA?" while an area pause waits is merged into the pause),
  KI-224 (semantic memory can still surface pre-reset turns, low).

## Latest: "⋯" menu under answers (2026-10-09, frontend only). Uncommitted. OFFLINE-VERIFIED (browser 9/9).
- A "⋯" button beside ↻ under every answer opens a small menu with when the answer was given ("Today, 11:34 AM",
  "Yesterday, 4:10 PM", "Tue, 6 Oct, 9:05 AM"; replayed answers use the saved `created_at`). No "Branch in new chat"
  (the user did not want it). Files: `format.js` `fullStamp`, `Messages.jsx` `MoreAction`, `App.jsx` (`at` on every
  message), `chat.css` `.msg-menu`. Test: scratchpad `e2e/ui_more_test.mjs`.

## Latest: Qdrant stays on 115.124.102.167:6335 (2026-10-09). No net change.
- A switch to `10.48.242.4:6335` was made and reverted the same day at the user's request: that port did not answer.
  `115.124.102.167:6335` checked 2026-10-09: `megh_scheme_kb` 201 points, `megh_conversation_memory` 765. KI-200 still open.

## Latest: every fresh answer is revealed word by word (2026-10-08, frontend only). Code changed, uncommitted. OFFLINE-VERIFIED.
- Why: on the live app (VPN up, 2026-10-08) the composer DID stream (no `composer stream failed`), but most turns never
  reach it (clarification pauses, edge replies, deterministic row answers), and its answers are short (28–32 tokens in
  0.25–0.9 s), so answers still looked like they arrived all at once.
- Now `frontend/src/chat/reveal.js` (`useReveal`) reveals every fresh answer at ~30 words/s, more words per step on a long
  one (about 2 s at most); the final answer continues from the streamed draft (shared key) and resumes from the first
  changed word when a guard corrected it. Charts / SQL / chips appear after the text. Replays and `prefers-reduced-motion`
  show at once. Browser 28/28 (`e2e/ui_format_scroll_test.mjs`), streaming 17/17, banner 20/20.

## Latest: answer formatting + smart auto-scroll (2026-10-07, frontend only). Code changed, uncommitted. OFFLINE-VERIFIED.
- Answers render a safe Markdown subset (`frontend/src/chat/components/Markdown.jsx`, React elements only, never innerHTML):
  bullet and numbered lists (one nested level; numbered items keep the number written), simple `|` tables (scroll inside
  their box on a phone), `**bold**`, `` `code` ``, `#` headings, and LABEL headings: an all-bold line, or a short
  "Documents required:" line right before a list. The streamed draft uses the same renderer. Copy / Read aloud use
  `plainText` (no `**` / `#`; list markers kept).
- Knowledge answers still arrive WITHOUT `#` headings: `app/rag.py` strips them (`_MD_HEADING`) and both RAG prompts say
  "No Markdown headings". Allowing real headings is a backend change, not done (label lines cover the common cases).
- Smart auto-scroll (`App.jsx`): the chat follows new content only while the officer is at the bottom (within 80 px; a
  ResizeObserver keeps late charts/tables pinned). Scrolled up, nothing moves and a pill shows "Answer is being written" /
  "New answer"; clicking it goes to the end. Sending a question or opening a chat always goes to the bottom.
- Tests: browser 23/23 (scratchpad `e2e/ui_format_scroll_test.mjs`); streaming 17/17 and banner 20/20 still pass.

## Latest: connection banner (2026-10-07, frontend only). Code changed, uncommitted. OFFLINE-VERIFIED.
- When the server can't be reached (network error, nginx 502/503/504 without the app's JSON, the app's "Couldn't reach the
  Megh One data service" 503 = VPN/megh_db, or a stream cut mid-answer) the chat shows "Can't reach the server — retrying…"
  instead of an error under the question. The question shows "Waiting for the connection" and is asked again, once,
  automatically when `GET /health` returns `ok` (polled 3 s → 15 s backoff; at once on the browser's `online` event; a
  "Retry now" button). "Busy" (503) and "took too long" stay ordinary errors. Browser offline shows the banner at once.
- Files: `frontend/src/chat/api.js` (`ConnectionError`, `httpFailure`, `checkHealth`), `App.jsx`, `styles/chat.css`; rebuilt `web/app/`.
- Tests: browser 20/20 (scratchpad `8ef3c696-…/scratchpad/e2e/ui_conn_test.mjs`); streaming browser test still 17/17.
- Limit: an anonymous `/health` says only ok/degraded. If Qdrant alone is down, health stays "degraded" and the banner stays
  up after a drop until an answer succeeds (any successful answer clears it).

## Latest: streamed answers, live progress steps, Stop, Regenerate (2026-10-07, D-039). Code changed, uncommitted. OFFLINE-VERIFIED.
- `POST /api/query/stream` (SSE) runs the same turn as `/api/query` (`routers/query.py` `_answer`): `step` events from
  each graph node (`pipeline_graph._observed` → `app/turn_events.py`), the composer's text as a draft (`llm.stream_model`),
  then `done` with the checked result. Every faithfulness check still runs on the full text; the UI replaces the draft.
- UI: steps ("Understanding your question → … → Writing the answer"), the draft with a cursor, Send → **Stop** (cancels the
  turn on the server), ↻ **Regenerate** on the latest answer and **Try again** after an error or Stop (`skip_cache: true`).
- nginx (`nginx-megh-langgraph.conf`): unbuffered `location = /api/query/stream`. `STREAM_COMPOSER_ENABLED=false` turns the draft off.
- Tests: new `tests/test_query_stream.py` 14/14; pytest **1,648 passed, 0 failed** (1 skipped); scripts **14/14**; browser test
  against the real app + middleware with the turn stubbed **17/17**. NOT yet run against the live gateway (needs the VPN).

## Side-by-side deploy identifiers (2026-10-04)
- This build deploys to `/opt/meghalaya-langgraph` as `megh-langgraph.service` (port 8410) or compose project
  `megh-langgraph` (host 8411). The existing deploy (`/opt/meghalaya`, `megh-nlpservice.service`, port 8300,
  containers `megh-nlp`/`megh-qdrant`/`megh-redis`) is untouched and keeps running. Table: deploy/DEPLOYMENT.md.
- Fixed in passing: the Dockerfile served 8300 while compose mapped 8400. VERIFIED (`docker compose config`).

## Chat route and port (2026-10-04)
- Chat console is **`/megh-chat`** (was `/ai-query`, which now 301-redirects). Service port **8400** (was 8300). Config/routing only — the pipeline, API paths (`/api/*`) and `ai_query.html` itself are unchanged. VERIFIED offline. Details: HANDOFF.md.

## Qdrant server move (2026-10-03, afternoon)
- `QDRANT_URL` now `http://115.124.102.167:6335` (was `10.48.242.4:6333`). Config only. `megh_scheme_kb` rebuilt there (201 points, VERIFIED) and `megh_conversation_memory` created. Open security item KI-200 (no API key on a public IP). Details: HANDOFF.md.

## Project status
- **Stage (INFERRED):** internal UAT with live QA passes per scheme.
- **Production deployment status:** UNKNOWN — NEEDS VERIFICATION. Not recorded in the repo.

## Completed functionality (VERIFIED in code)
- All six schemes wired end to end: MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy
  (added 2026-09-22) and CM Elevate Legacy (added 2026-09-24).
- **NL→SQL chain:**
  - the classifier, entity resolution and clarification gates;
  - 30B SQL generation, 9 deterministic guards and the 4B verifier;
  - up to 3 repairs;
  - the composer, with faithfulness guards.
- RAG over 10 SME docs plus tagged web docs, with scheme-scoped retrieval.
- **Deterministic answers:**
  - geo abbreviations;
  - scheme listing, comparison, recommendation and pick;
  - Focus Legacy PG-name lookups;
  - cross-scheme money ranking.
- Multi-turn context: follow-up rewrite, structured state, a summary, and Qdrant memory.
  Since 2026-09-26 the rewrite gets the previous turn as structured tiers instead of
  `answer[:300]`, with a provenance check on its output (AI_PIPELINE.md §5.1, D-022).
- A typed reply to the "which scheme?" / "which Focus?" pause resumes the paused question
  (§5.2).
- A `prompt_context` log line for every model prompt: tokens per section, budget, and
  request id (§5.3).
- Voice input with no-speech and prompt-echo guards (2026-09-25).
- Auth, multi-tenancy, admin console, history (pin, archive, rename, delete), audit, caches,
  health and metrics.

## Latest: all six schemes, every district / block / village (2026-10-02 night → 10-03). Code changed, uncommitted. LIVE-VERIFIED.
- **Live bulk: 30,280 / 30,280 pass on the final code** (truth computed read-only from `megh_db` per question):
  MGNREGA 6,378 · PMAY-G 5,256 · PMAY-G officer cases 5,833 · Focus Plus 3,651 · CM Elevate 2,165 ·
  CM Elevate OFF-009/017/018 2,284 · CM Elevate Legacy 1,193 · Focus Legacy 3,520. 1,667 questions
  failed on their first run; every one was traced to a cause, fixed and re-run.
- **Fixed (all in `app/pipeline.py`, each with regression tests):** KI-188 village dropped from the SQL
  (non-MGNREGA); KI-189 village written as a CML programme; KI-190 Focus Legacy + CM Elevate Legacy join
  the village gate (D-034); KI-191 Focus Plus LGD-only blocks; KI-192 spelled-out figures → digits;
  KI-193 PMAY-G village comparisons; KI-194 CM Elevate applicants = distinct request_id; KI-195
  "Sports & Wellness"; KI-196 district/block literal beside a village in any UPPER/LOWER/TRIM form;
  KI-197 village named by truncated text → its code; KI-198 doubled bracket in the CML spelling fix.
  KI-182: full OFF-009 1,260/1,260.
- **Reports (docs/):** `All_Schemes_LangGraph_Test_Results_Summary.xlsx` and one
  `<Scheme>_LangGraph_Test_Results.xlsx` per scheme (MGNREGA, PMAY_G, Focus_Plus, CM_Elevate,
  CM_Elevate_Legacy, Focus_Legacy), plus `PMAY_G_Officer_Cases_LangGraph_Test_Results.xlsx` and
  `CM_Elevate_Officer_Sets_LangGraph_Test_Results.xlsx` (all runs on the LangGraph path).
- **Tests:** pytest **1,453 passed, 0 failed** (27 files) with the graph off AND on; scripts **14/14**; live context suite **43/43 on both paths** (follow-up 29/29).
- **Not covered:** one question shape per place (KI-199). Still open: KI-184/185 (Postgres checkpointer
  unverified live), canary G5.

## Latest: live verification + fixes (2026-10-02, evening, VPN up). Code changed, uncommitted. LIVE-VERIFIED.
- **LangGraph live gates passed:** context suite 43/43 on both paths; 36/36 live turns identical across all six schemes; all 21 nodes ran on live traffic with 0 errors. Flag still off by default (next gate: canary, G5).
- **Fixed:** KI-187 (verifier false positive: 'What about Dalu block?' went to the KB; pre-existing, reproduced on the pre-refactor code), KI-182 (CM Elevate OFF-009: a 0-applicant programme left out — live re-test 49/49), KI-183 (repaired SQL now re-authorized, D-033), 2 stale verifier tests.
- **Tests:** pytest 1,419 passed, 0 failed, flag off and on; scripts 14/14.
- **Still open:** KI-184/185 (shared Postgres checkpointer needs approval and a non-production DB); the full 1,260-question OFF-009 set was not re-run (49-question sample was).
- **Report:** https://claude.ai/artifact/Q2Mb7ynLwebbjcRebHkYmq (nodes + per-scheme results).

## Earlier the same day: LangGraph orchestrator (2026-10-02, D-032). Code changed, uncommitted. OFFLINE-VERIFIED ONLY (VPN down).
- **What:** `app/pipeline.py`'s `_run_pipeline`, `_answer_data` and `execute_with_repair` are split,
  verbatim, into stage functions. A new opt-in 21-node LangGraph graph (`app/pipeline_graph.py`)
  runs the same stages, with an explicit SQL repair loop, clarification pauses as `interrupt()`, a
  checkpoint under `thread_id = session_id` (Postgres `app.checkpoint*` since 2026-10-06), and shape-only per-node logs. **Off by
  default** (`PIPELINE_GRAPH_ENABLED=false`, `PIPELINE_GRAPH_CANARY_PERCENT=0`); the router and the
  API are unchanged.
- **Works (VERIFIED offline):**
  - the stage split is behaviour-neutral: 1,371 → 1,371 passed, the same 2 known failures;
  - 27 graph tests: the same conversations on both orchestrators give identical results, pauses,
    session state and model/DB call counts (answer, follow-up, scheme switch, pause → resume,
    "thanks" / new question abandon a pause, digression, repair, repair budget, DB outage,
    denial, edge);
  - pause → checkpoint → resume; correct even with the thread deleted;
  - every intermediate state serializes; no question text in graph logs; TTL sweep;
  - full pytest flag on: 1,397 passed (the only extra failure was a test reading the live flag,
    since fixed). No existing test calls `answer_question`, so this sweep adds no graph coverage;
    the graph evidence is the 27 dedicated tests. Scripts 14/14.
- **Not verified:**
  - live context suite and live use cases on the graph path (KI-186);
  - the Postgres checkpointer (KI-185);
  - cross-VM resume on the Postgres checkpointer, to confirm on the VMs (KI-184).
- **Cost:** +45 to +120 ms per turn of orchestration, measured offline (≈3–7% of a live turn);
  no extra model or DB calls.
- **Found:** repaired SQL is never re-authorized (KI-183, pre-existing, left unchanged on both
  paths).
- **Dependencies:** `langgraph` 1.2.12, `langgraph-checkpoint-postgres` 3.1.2 + `psycopg` 3 (SQLite package removed 2026-10-06) (+ `langchain-core`,
  `langsmith`; `websockets` downgraded 17.1 → 16.1.1 by `langgraph-sdk`). Installed in `.venv`;
  `requirements.txt` / `.lock` updated.

## Latest: typed replies resume every chip pause (2026-09-29, morning, KI-181). Code changed, uncommitted. LIVE-VERIFIED.
- Before: only the area/year/entity/ranking pauses and the which-scheme pauses were remembered. Any other pause with chips
  (measure gap, year out of range, tranche, region, AC part, Sericulture, CM sub-scheme group, stated amount, …) forgot its question,
  so a typed "houses sanctioned" or "2022-23" was read against the last answered turn.
- Now the router remembers every pause with options; a typed reply picks ONE option by its words, an ordinal, or "yes"
  (`_resume_option_pause`), and an unmatched reply stays on the paused scheme (`_paused_thread_antecedent`). AI_PIPELINE §5.2.
- Tests: pytest 1,371 passed + the 2 parallel-session failures; scripts 14/14; live context 43/43.

## Latest: conversational scheme swap — "give me for pmay" (2026-09-29, early morning). Code changed, uncommitted. LIVE-VERIFIED.
- Reported: "Total MGNREGA person-days in 2023-24" then "give me for pmay" returned a PMAY-G scheme description.
- Now a request-verb swap continues the previous DATA question on the new scheme (`_SCHEME_SWAP_FOLLOWUP`, `_SUBSTITUTION_CUE`).
  When the carried measure does not exist in the new scheme (person-days in PMAY-G, houses in MGNREGA), the bot says so and
  offers the new scheme's own measures for the same place/year as chips (`_swap_measure_gap`, rule `swap-measure-unavailable`),
  instead of the old "couldn't build a working query". Questions about a scheme ("tell me about pmay") are unchanged.
- Tests: pytest 1,338 passed + 2 failing tests owned by a parallel CM Elevate Legacy session (see TESTING.md); scripts 14/14; live context 43/43.

## Latest: CM Elevate Legacy fixes + all districts / blocks / villages (2026-09-29, late night). Code changed, uncommitted. LIVE-VERIFIED.
- **Use cases 36/36** on 2 of 2 fresh runs (were 33/36: TC-13 LIMIT 10, TC-14 COUNT(*), TC-34 derived count).
- **All levels 2,614/2,614** vs DB AND raw (12 districts, 59 blocks, 1,051 villages, 55 ACs; 7 question shapes).
  Round 1 found KI-169..181 (twin-village chip loop / ranking, exact small amounts, spelling, ward literal,
  unnamed breakdown figures, Tura MB refused, invented subsidy split, garbled village lists, Garo village,
  "village" kept in the name, verifier false positive after a chip, unselected GROUP BY) — all fixed.
- Design: deterministic SQL guards in `execute_with_repair` + `_cm_legacy_answer_guarantees` after the composer
  (AI_PIPELINE §2.9a). KI-179 (level word dropped from an extracted village name) touches ALL schemes, guarded by
  an exact-name check.
- Tests: pytest 1,309+ (26 files; `test_cm_elevate_legacy.py` 131), scripts 14/14, live context 41/43 then the
  2 failing checks (scenario G, a transient app.conversations save-failed) 5/5 on 2 re-runs.

## Earlier the same night: CM Elevate Legacy use-case re-test — 33/36. No code changed.
- All 36 use cases (`Use_Cases_-_CM_Elevate_legacy.csv`) run live through `pipeline.answer_question`, 2 full runs + 3 repeats of the
  failures; every figure checked against `curated.v_cm_elevate_disbursement` AND the raw file `Cm Elevate legacy to share to BLH (1).csv`.
- **DB = raw** row for row (2,823 = 2,823 on source id; all money, scheme, FY, district, block, AC, lender, desanction fields identical).
- **Fails (AI layer, all reproducible):** TC-14 sanctioned 2,823 vs 2,820 (KI-166, SQL `COUNT(*)`); TC-34 "20 villages with 1 record" vs 24
  (KI-167, composer); TC-13 `LIMIT 10` → "down to 33" vs Motorcaravan 1 (KI-168). TC-01..10 knowledge answers all correct.
- Report `docs/CM_Elevate_Legacy_UseCase_Test_Report_2026-09-29.xlsx` (+ `docs/CM_Elevate_Legacy_UseCase_Evidence_2026-09-29/`, 37 PNGs).

## Latest: reported "what is focus" conversation (2026-09-29, later), uncommitted, LIVE-VERIFIED
- **Report:** after a CM Elevate Legacy turn, "what is focus" was answered with CM Elevate material;
  "give me beneficiaries" paused generically; the user had to retype the whole question.
- **Root causes (KI-136 to KI-144):** a bare "Focus" went to the model rewrite, which read it as a noun;
  the rewrite carried a data turn's year / place into how-it-works questions; the rewrite could swap
  the user's metric; the old scheme's filters fed follow-ups after a knowledge answer on another
  scheme; intent was read from the rewrite, not the typed words; a paused follow-up was remembered as
  a fragment; "all of them combined" kept the last year; a place-only change after knowledge answers
  lost the data thread.
- **Tests:** pytest **1,185**; scripts **14/14**; live context suite **43/43**; live battery S1–S8 all
  correct (it also live-verified the first pass, KI-130 to KI-135).

## Earlier the same day: context relevance + semantic contract (2026-09-29), uncommitted (offline at the time; live-verified later that day)
- **Reported conversation** (after "beneficiaries in focus+ across all financial years"): "who is
  harshit" / "he is my collik remember" answered as Focus Plus; "now give me five thousand loan…"
  became a Focus Plus DATA pause; "…Focus Plus … for a loan of five thousand…" ran SQL without the
  amount; WHK dropped from a comparison. Reproduced offline with the real `_run_pipeline`.
- **Fixed (D-030):** continuation gate `context_policy.continuation_signals` (KI-130); edge
  `personal_request` (KI-131); Focus Plus stated-amount filter + guard + pause (KI-132); WHK
  near-miss chips (KI-133); bare "which one?" asks (KI-134); village name search (KI-135); generic
  `_resolved_scope_missing` SQL guard (KI-034); CLEAR applied to committed state (KI-032);
  all-years carried (KI-030); `pipeline_decision` log lines.
- **Tests:** pytest **1,163** (26 files; +96 in `test_context_relevance_and_contract.py`);
  scripts **14/14**. **Not run:** `tests/live_context_validation.py` and every live check — the
  DB and gateway (`10.48.242.4`) were unreachable. Run them first when the VPN is up.
- "give me same for mgnrega" already worked (KI-039); it is re-tested and unchanged.

## Latest: CM Elevate all blocks / all villages (2026-09-28)
- **CM Elevate all districts / blocks / villages (2026-09-28): 7,364 / 7,364 on the final code** (round 1: 4,132 / 4,208). Every district (12), block (66) and village (2,087 x 3 phrasings) x the use-case question types, each figure checked against megh_db and the raw workbook. Report `docs/CM_Elevate_AllBlocks_AllVillages_Test_Report_2026-09-28.xlsx` (+ `_Evidence_2026-09-28/`).
  - Fixed: KI-074 decided (pending = On Hold only), KI-076 (intent cue), KI-106 to KI-120 (CM Elevate joined the village guards; urban bodies; literal / sector / programme-filter SQL guards; verifier false positives; twin-village chip; number words). All CM Elevate-gated except the literal- and FILTER-aware village WHERE rebuild (KI-108, also Focus Plus). pytest 1,053; context suite 43/43.

## Latest: PMAY-G plain year = calendar year (2026-09-29, KI-125 revised), uncommitted
- "during 2017" → calendar 2017 in the answer, table and SQL; FY reading as a one-line note. Explicit FY unchanged.

## Latest: PMAY-G result table and Sources (2026-09-29, KI-129), uncommitted
- Result table = place + asked figures; Sources no longer shows "TRUE". pytest 1,067; follow-ups 18/18; use cases 71/71.

## Latest: PMAY-G extra information removed (2026-09-28, KI-128), uncommitted
- Summaries = exactly the use-case figures; no side details on single figures; follow-ups answer only what was typed.
- Live 2,129/2,129 sample + use cases 71/71 + follow-ups 18/18; pytest 1,065.

## Latest: PMAY-G 21 Sep tester sheet recheck (2026-09-28), uncommitted
- All tester-named inputs correct vs DB and raw; 192/192 live checks + use cases 71/71.
- Fixed KI-125: a bare year was dropped by the facts path (answered all years). Now FY reading + calendar-year line.
- Open product decisions: KI-126 (one combined village + year question), KI-127 (count zero-sanction placeholder
  records or not — the tester's 14 Sep and 21 Sep remarks conflict).

## Latest: PMAY-G full scenario test (2026-09-28): 17,331 / 17,331, uncommitted
- **Why:** the KI-098 miss showed the earlier village test used one phrasing only. This run covers every place type x 16
  question types, 3 village phrasings, every FY, dates, comparisons, model-path questions and follow-ups.
- **Found and fixed (KI-099 to KI-105):** 'Garo'/'Khasi' inside a village name triggered the hill-range pause; 'Old …'
  villages read as the Old House stage; ', X block' mid-sentence; a village named like its block; two-village comparisons;
  FY printed as a calendar year; model-path amounts in 2-decimal crore.
- **Result:** 17,331/17,331; follow-ups 18/18; use cases 71/71; context 43/43; pytest 1,005; scripts 14/14.
  Report `docs/PMAY_G_Full_Scenario_Test_Report_2026-09-28.xlsx`.

## Village named beside its block (2026-09-28, KI-098, user report), uncommitted
- **Report:** "…still to be released in NONGSOHRAM across all financial years, RI MULIANG block, WEST
  KHASI HILLS" answered with the whole block (₹33,84,000).
- **Fix (PMAY-G only):** `_pmay_village_beside_block`, called at the end of `resolve_entities`.
- **Live:** all 5,120 villages asked with their block + district tail **5,120/5,120** (before the fix, 216 of
  the first 927 such questions answered for the block); block questions unchanged (see TESTING).

## PMAY-G fixes (2026-09-28): 28 / 28 use cases, all blocks and all villages, uncommitted
- **Result:** use cases **28/28** (71/71 questions on 2 of 2 fresh live runs, identical answers; round 1 was 17/28); all blocks **224/224**; all villages **5,120/5,120** on the final code (round 1 4,393/5,120 → KI-096 fixed). Every figure checked against megh_db and the raw CSV (identical row for row).
- **Changed:** `app/pipeline.py` (PMAY-G facts path, model-path guards, village gate, date / typo /
  plural-blocks fixes), `app/entity_resolver.py`, `app/premise_check.py`, `app/schema_context.py`,
  `data/pmay/pmay_few_shot.yaml`, `data/pmay/pmay_entity_resolver.yaml`, tests. D-029; KI-089 to KI-097.
- **Regression:** pytest 993; scripts 14/14; live context 43/43; Focus Plus 60/60 + 300/300;
  MGNREGA 60/60 + 300/300.
- **Reports:** `docs/PMAY_G_UseCase_Test_Report_2026-09-28_v2_after_fixes.xlsx`,
  `docs/PMAY_G_AllBlocks_AllVillages_Test_Report_2026-09-28.xlsx`.

## PMAY-G use-case QA, round 1 (2026-09-28): 17 / 28, before fixes
- **What:** the 28 PMAY-G use cases (`PMAY-G.csv`, PMAY-OFF-001 … 028) as 71 real questions, each
  run twice live, with every figure checked against megh_db and the raw
  `PMAY_FullyMapped_with_dates.csv`. The user said "Focus legacy", but named PMAY-G files, so PMAY-G was tested.
- **Result:** **17 / 28 test cases pass** (49 / 71 questions). The failures are 007, 009, 012,
  016, 018, 022, 023, 024, 025, 027 and 028.
- **DB vs raw:** identical row for row (171,107 rows, 13 fields, 0 mismatches).
- **Root causes (KNOWN_ISSUES KI-089 to KI-095, all fixed the same day — see above):**
  - per-year GROUP BY on summaries and comparisons (row dumps, mislabelled or invented figures);
  - required parts missing (remaining amount, difference, sanctioned amount);
  - a false "House Sanctioned stage" qualifier from the entity resolver;
  - utilisation as an average of ratios;
  - LIMIT 1 on "which has more";
  - a written-date premise misread;
  - village money rounded to 0.0x crore.
- **Report:** `docs/PMAY_G_UseCase_Test_Report_2026-09-28.xlsx` (Summary, Test Results, Question
  Detail, DB vs Raw, Evidence); PNGs in `docs/PMAY_G_UseCase_Evidence_2026-09-28/`.
- **Fixed the same day** — see the section above.

## Latest: database-outage handling and data package (2026-09-28), uncommitted
- **KI-025 fixed (connection loss):** a megh_db outage mid-question now returns 503 "Couldn't
  reach the data service… retry". It no longer answers "not in the reference material" or spends
  SQL repairs. Changed: `app/db.py`, `app/pipeline.py`, `app/routers/query.py`. Slow-query
  timeouts are unchanged (504).
- **KI-065 / KI-084 (data):** not changeable by the chatbot (the DB belongs to the ingestion team,
  CLAUDE.md §6). A row-level package is handed over:
  `docs/Focus_Plus_Data_Corrections_for_Ingestion_2026-09-28.xlsx`. Awaiting their decision.
- **Tests:** pytest 939; scripts 14/14; live context 43/43; outage simulation passed; live
  204/204 blocks + 200/200 villages.

## Latest: Focus Plus all blocks and all villages (2026-09-27 night): 100% on the final code, uncommitted
- **Scope:** every block (51 × 4 questions) and every village or ward in `v_focus_plus`
  (3,513 × 2). Each figure was checked against megh_db and the raw CSV.
- **Result:** blocks **204/204**; villages **7,026/7,026**.
  - Before fixes: blocks 201/204, and villages 62/327 on the first sample.
  - Confirmation pass on the final code: 204/204 and 1,000/1,000.
  - MGNREGA regression: 448/448 and 300/300.
- **Report:** `docs/Focus_Plus_AllBlocks_AllVillages_Test_Report_2026-09-27.xlsx`, with evidence
  images.
- **Fixed (KI-079 to KI-088):**
  - the village guards now cover Focus Plus (`_village_scheme`, D-028);
  - `_focusplus_narrow_village`;
  - `_focusplus_pin_village_where` (place conditions, place literals, `geography_key` subquery);
  - twin-village "(LGD code)" chips;
  - the district-alias collision (BAGHMARA);
  - the "Nan" block;
  - BURMA;
  - the Focus Plus one-figure misquote rule;
  - roman numerals in names.
- **Data side:** DB village totals often exceed the raw file's code-only totals (KI-084, see
  `docs/Focus_Plus_DB_Issues.md`).
- **Tests:** pytest 936 (24 files); scripts 14/14; live context 43/43.

## Latest: CM Elevate use-case fixes (2026-09-27): 30 / 30 after fixes, uncommitted
- **Result:** 55 / 55 questions on 2 of 2 fresh live runs. Each figure was checked against
  megh_db `v_cm_elevate` and the raw `CM_Elevate_AllSchemes_20260927_full.xlsx` (DB = raw
  exactly).
  - Round 1, before the fixes: 23 / 30.
  - Report: `docs/CM_Elevate_UseCase_Test_Report_2026-09-27_v2_after_fixes.xlsx`.
- **Fixed, all CM Elevate-gated (D-027):**
  - KI-068: Unresolved rows dropped from programme totals;
  - KI-069: no per-programme split;
  - KI-070: pending at level 2 gave 0;
  - KI-071: no comparison difference;
  - KI-072: zero sectors vanished;
  - KI-073: garbled two-label prose;
  - KI-075: PRIME SEED paused on "which scheme?".
  - Found while re-testing: a plain "pending" became a level filter; approved/rejected went to
    the wrong column; a verifier false positive on `scheme_specific`.
- **KI-074 interim:** "pending" is still On Hold. A single-figure pending answer also states the
  file-status Pending count. **Product decision still needed.**
- **Tests:** pytest 891 passed (858 + 33 new); scripts 14/14; live context suite 43/43.
- **Open:** KI-076, an intent-classifier flake for a question with no counting word (Low,
  pre-existing).
- The user said "Focus legacy" but named the CM Elevate files, so CM Elevate was tested.

## Latest: Focus Plus use-case fixes (2026-09-27): 30 / 30 after fixes, uncommitted
- **Result:** 39 / 39 questions on 2 of 2 fresh live runs, each figure checked against megh_db
  and the raw CSV. Report: `docs/Focus_Plus_UseCase_Test_Report_2026-09-27_v2_after_fixes.xlsx`.
- **Fixed:**
  - KI-060: shares;
  - KI-061: comparison difference;
  - KI-062: "1,0263", fixed for all schemes;
  - KI-063: bank-pause chips and typed resume;
  - KI-064: rupee format, the "amount raw" fallback (the SQL-literal fix applies to all schemes),
    and no "which area?" for a batch or tranche;
  - KI-066: a typed reply that pauses again kept only the bare reply, all schemes;
  - KI-067: the Focus Legacy bank `KeyError`.
- **Where:** `_focusplus_answer_guarantees` and helpers, `_fix_digit_grouping`,
  `_sql_literal_numbers`, `_bank_clarification`, `_needs_scope_clarification`,
  turn_context `resumed_question`, and router `pause_question`. Rationale is D-026.
- **Tests:** pytest 858 passed (826 + 32 new); scripts 14/14; live context suite 43/43.
- **Still open:** KI-065, data-side (175 Dalu ↔ SWGH rows), with the ingestion team.

## Focus Plus use cases, round 1 (2026-09-27): 19 / 30, before fixes
- **Inputs:** `Focus +_Use_Cases.csv` (FOCUS-001..030) and the raw `Focus Plus Master.csv`.
  - The user wrote "Focus legacy", but both files are Focus Plus, so Focus Plus was tested.
- **Method:** 39 concrete questions, placeholders filled with real values. Each went through the
  live `pipeline.answer_question` twice, clicking the chip a tester would pick. Every figure was
  checked against both megh_db (`v_focus_plus`) and the raw CSV.
- **Result:** **19 PASS / 11 FAIL** test cases (27 / 39 questions). Both runs gave the same
  verdicts.
  - **Failed:** FOCUS-008, 011, 012, 013, 014, 016 (percentages missing, KI-060); 026, 027, 028
    (no difference / higher district, KI-061); 021 (malformed "1,0263", KI-062); 029 (bank
    question lost after the no-chip clarification, KI-063).
  - In 10 of the 11 failures the numbers themselves are correct. The exception is 029, which gave
    no number at all.
- **Report:** `docs/Focus_Plus_UseCase_Test_Report_2026-09-27.xlsx`, with evidence PNGs in
  `docs/Focus_Plus_UseCase_Evidence_2026-09-27/`.
- **DB vs raw:** identical except 175 rows (Dalu ↔ SWGH) in a different district. See KI-065 and
  `docs/Focus_Plus_DB_Issues.md`.
- **Fixed since the testers' 14 Sep comments:**
  - no stray verification column (018, 019);
  - no stray FY column (010);
  - "female during 2025-26" answers (021a);
  - the Focus+ overall summary (030) is complete and correct.

## Calendar date read as FY fix (2026-09-27, KI-078; uncommitted)
- **Report:** "How many PMAY houses were sanctioned on 2017-11-28?" answered 504 (correct) but
  added "not the 11 or 28 figures assumed" and "applies to FY 2017-18".
- **Now:** "504 PMAY houses were sanctioned on 2017-11-28." A date is no longer back-filled as
  an FY, never yields premise figures, and satisfies the scope gate.
- **Checks:** live 4/4 probes; pytest 915; scripts 14/14.

## MGNREGA women share fix (2026-09-27, KI-077; uncommitted)
- **Report:** "What percentage of employment persons were women in ekh?" answered "0.00% … a
  genuine zero".
- **Cause:** the question named no year and the year gate ignored percentage questions, so the
  SQL model took FY 2025-26, whose women column is unrecorded at source.
- **Now:**
  - the bot asks the FY, offering only the years that carry women data;
  - the answer states the years it covers: EKH 77.70% in FY 2024-25, or 74.90% for FY 2022-23
    to 2024-25;
  - FY 2025-26 is answered "not recorded", never 0.
- **Checks:** live 8/8. pytest 897, scripts 14/14, live context 43/43.

## Latest QA: MGNREGA all blocks and all villages (2026-09-26 night): 100% on the final code, uncommitted
- **Scope:** FY 2024-25.
  - All 56 blocks × 8 questions = 448.
  - All 6,425 villages × 2 questions (person-days, total expenditure) = 12,850.
  - Every expected figure comes from megh_db and, independently, from the raw CSVs.
- **Result on the final code: 13,298 / 13,298.** VERIFIED as follows:
  - the full village pass gave 12,846 / 12,850;
  - the 4 misses were 3 short-name villages (fixed afterwards) and one gateway 502;
  - those, plus every case that went through a "village" chip, were re-run on the final code:
    590 / 590 (2 retried after a VPN drop);
  - blocks re-run on the final code: 448 / 448.
- **Report:** `docs/MGNREGA_AllBlocks_AllVillages_Test_Report_2026-09-26.xlsx`, with before/after
  evidence in `docs/MGNREGA_AllBlocks_AllVillages_Evidence_2026-09-26/`.
- **Defects found and fixed:** KI-049 to KI-059, all MGNREGA-only. The worst was a village chosen
  from the bot's own list answered with its whole BLOCK's total (KI-049). Other defects:
  - village-chip loops;
  - bare block names;
  - names with "&", "INCL", "BLOCK", "India" or "Dairy" in them;
  - a stray district filter and an extra village code in the SQL;
  - "null" wording.
- **Data side (the data team's):** 16 villages are in a different block in the DB than in the raw
  file, which affects 68 of the 448 block figures. Village figures are identical. See
  `docs/MGNREGA_DB_Issues.md`.
- **Operational lesson:** bulk runs must cap the DB pool. On 2026-09-26 VPN drops plus a 30-connection
  pool exhausted `megh_db` (max 100, shared), and the result was "too many clients already". See
  TESTING.md, "Bulk live runs".

## MGNREGA use cases (2026-09-26): 30/30 after fixes
- **Round 1 (no code changed):** 16 PASS / 14 FAIL of the 30 use cases in
  `Test_Case_Results_21st_Sep_26_MGNREGA (1).csv`. The testers had 17 / 12 / 1 On-Hold on
  21 Sep.
  - Report: `docs/MGNREGA_UseCase_Test_Report_2026-09-26.xlsx`, with evidence in
    `docs/MGNREGA_UseCase_Evidence_2026-09-26/`.
- **Round 2 (after the fixes, same day): 30/30 PASS.** All 43 concrete queries were correct on
  two fresh full live runs, with every figure checked against megh_db and the raw CSVs. VERIFIED.
  - Report: `docs/MGNREGA_UseCase_Test_Report_2026-09-26_v2_after_fixes.xlsx`, with evidence in
    `docs/MGNREGA_UseCase_Evidence_2026-09-26_after_fixes/`.
- **Fixes:** KI-041 to KI-048, plus three answer-wording and unit fixes. All are in
  `app/pipeline.py` and `app/schema_context.py` (MGNREGA rules 8–10), and **every change is
  gated on MGNREGA**. Design choices are in D-025.
- **Tests:** `tests/test_mgnrega_usecase_fixes.py` (41 at that point; 78 after the all-villages fixes). pytest 789 passed at that point. Scripts 14/14. Live
  context suite 43/43.
- **DB vs raw:** rows and all statewide totals are identical. The one mapping difference is village
  GENAPARA (`docs/MGNREGA_DB_Issues.md`, owned by the data team). No failure was caused by the DB.
- **Known limitation, left on purpose:** the negated-level chip bug (KI-041) still affects the
  other five schemes. The user asked that they not be changed.

## Focus Legacy all blocks / villages / ACs / PGs (2026-09-29, night) — VERIFIED, code changed, uncommitted
- **32,560/32,560** questions correct vs the live DB and the raw file (latest run of each): 56 blocks x3,
  12 district breakdowns, 55 ACs x3, 3,384 villages x2 (list + amount), 11,906 PGs x2 (exists + members),
  1,635 older raw spellings. Final-code regression pass: 5,215 questions (all block/AC, every question that
  ever failed, 4,300 random) 5,214/5,215, the last fixed (KI-165) and re-run.
- Use cases **28/28 on 3 of 3 runs** on the final code; live context suite **43/43**; pytest **1,265**;
  scripts **14/14**.
- Fixed: KI-020 (older PG spellings via `v_focus_legacy_pg_search`), KI-145..165 — breakdowns written from rows
  (D-031), month/rupee formatting, AC-alone no longer pins MGNREGA, AC drill-down per scheme, PG-name parsing
  (punctuation, place words, "_", non-ASCII, "Focus" in a name), edge refusing group/village names holding a
  state or country word, village phrase read from the text, twin villages and LGD chips, village chip pin +
  year chip, verifier false complaint, misspelt block literal, DATE_TRUNC timezone shift.
- Reports: `docs/Focus_Legacy_AllBlocks_Villages_ACs_PGs_Test_Report_2026-09-29.xlsx` (+ `_Evidence_…/`, 70 PNGs,
  before/after per fix), `docs/Focus_Legacy_UseCase_Test_Report_2026-09-29_v2_after_fixes.xlsx` (+ `_Evidence_…_after_fixes/`).
- **Open:** KI-151 (one intermittent "couldn't build a query" under heavy load); KI-155 data team (6 mis-encoded
  names); KI-164 NOT VERIFIED for other schemes (PMAY-G `date_trunc('month', sanction_date)`); the duplicate-village
  chip loop (KI-156) NOT VERIFIED for CM Elevate Legacy; TC-10/16 "beneficiaries" definition needs an SME.

## Focus Legacy use-case re-test (2026-09-29) — VERIFIED, no code changed
- **28/28 PASS** on 3 of 3 full runs (supplementary TC-14b, TC-28blk: 2/2); data answers were
  word-for-word identical across the runs. Each figure was checked against the live DB view
  `curated.v_focus_legacy` AND the raw file `Focus Legacy to share to BLH.csv`, computed independently.
- **DB vs raw:** 14,569 rows joined 1:1 (raw `id` = `source_row_id`); pg_id, members, amount, date, FY,
  district, block, village and constituency identical on every row. PG-name text differs on 1,636
  rows (the DB keeps one current name per pg_id — by design). 88 rows have no block in both sources.
- Remarks, not failures: KI-145 (TC-26 omits 5 no-block PGs), KI-146 (MGNREGA wording in the AC
  chip), KI-147 (unformatted money, "month 4"); TC-10/16 "beneficiaries" = members summed over payments
  (102,021; 91,446 if each PG is counted once — needs an SME definition); one PG records 190 members.
- Report: `docs/Focus_Legacy_UseCase_Test_Report_2026-09-29.xlsx`; proofs:
  `docs/Focus_Legacy_UseCase_Evidence_2026-09-29/` (one PNG per case).

## Earlier QA (from the `docs/` records, 2026-09-25)
- **Focus Legacy:**
  - 28/28 use cases in round 3, VERIFIED from the report's summary sheet;
  - bulk run of 168/168 block and 580/580 PG questions, per session notes. The report computes
    these with formulas that have no cached values, so they are not machine-verified.
- **CM Elevate Legacy:** 36/36 against both the DB and the raw file, VERIFIED from the "FINAL
  RESULT" in report v3. Earlier rounds: 22/36 and 33/36.
- **Ingestion-team fixes:**
  - block NULLs for rows with no village code, in both schemes;
  - CM Elevate Legacy row id 2392 loaded.

  8 of 9 Focus Legacy re-verification checks pass. TC-F1 has an open question (KI-019).

## Partially complete / open
- **PG alternate-spelling lookup:** the DB view `curated.v_focus_legacy_pg_search` exists, but
  the bot does not use it yet (KI-020, PLANNED).
- **No accuracy benchmark** (KI-017).
- **Security hardening gaps:**
  - generated SQL can reach `app.*` and the privacy tables (KI-004);
  - authorization blind spots (KI-007);
  - TLS verification is off unless a CA bundle is present (KI-015).
- ~~Clarification resume is per worker (KI-001)~~ — stale line, corrected 2026-09-29: KI-001 is
  fixed and live-verified (KNOWN_ISSUES; D-023), see the next bullet.
- **KI-028 / KI-001 are fixed and live-verified** (2026-09-26): shared state goes through
  Postgres (D-023). New low-severity findings from the live run: KI-030 (an "all years" choice
  is not carried forward) and KI-031 (the scheme swap keeps old metric words).
- Full list: [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## Documentation audit (2026-09-26)

**Result:**
- All 11 maintained docs were re-checked against the code.
- Every code identifier they cite exists (script check).
- All relative links resolve.
- 24 documentation issues were found. 23 were corrected in the maintained docs. 1 (a stale
  claim in the SME file `data/pmay/README.md`) is recorded in DATA_MODEL.md but the file itself
  was not edited.
- The critical risk KI-022 is documented; it needs a user decision.

**New verified risks added to KNOWN_ISSUES:**
- KI-022: raw PII file pushed. **Critical.**
- KI-023: plaintext seed passwords.
- KI-024: voice recordings saved on the dev box.
- KI-025: LLM repairs spent on infrastructure errors.
- KI-026: no pool acquire timeout.
- KI-027: startup-only year and schema snapshots.
- KI-004 was extended with the prompt-injection path to `app.users`.

## Current development focus
- **INFERRED from the last commits:** per-scheme use-case QA and fixes for the two newest
  schemes.
- **This session:** follow-up context from structured state (D-022), the scheme-pause resume, and
  prompt-context observability.

## Current known failures
- No failing automated tests (see below).
- `pytest tests` over the whole directory fails with INTERNALERROR (KI-018). This is a test
  harness issue, not a product failure.

## Blockers
- None recorded in the repo.
- Live verification needs the office VPN to reach `10.48.242.4`. It was unreachable from this
  machine on 2026-09-26.

## Recent changes (git)

| Commit | Date | Summary |
|---|---|---|
| `7064ab6` | 2026-09-25 | Added Focus Legacy + CM Elevate Legacy data/tests/docs, QA reports, TECHNICAL_BRIEF, ASR fixes, UI |
| `815c37a` | 2026-09-18 | Routing, entity resolution, QA test coverage |
| `5c5a100` | 2026-09-13 | `verify=False` fallback for the gateway; app port bound to localhost |
| `036eafa` | 2026-09-13 | UAT fixes: district acronyms, Focus+ summary, live column notes |
| `7ad882f` | 2026-09-11 | SQL semantic verifier (qwen3-4b) |

Uncommitted code change (2026-09-26): the `scope-not-specified` statewide chip is now
"All of Meghalaya" (area only), not "All of Meghalaya, all years". See HANDOFF.md.

## Context-layer session (2026-09-26, code)

**Changed (uncommitted):**
- `app/context_manager.py`, `app/context_budget.py` (new), `app/pipeline.py`
- `app/prompt_builder.py`, `app/rag.py`, `app/entity_resolver.py`
- `app/session_store.py`, `app/routers/query.py`, `app/middleware/security_headers.py`,
  `app/config.py`
- `tests/test_context_semantic_state.py` (new)

**Behaviour:** see HANDOFF.md and AI_PIPELINE.md §5.1–5.5. The SQL, verifier and composer prompt
texts are byte-identical under budget. No `curated` DB, API-contract, scheme or business-rule
changes.

**Second pass, same day:** `app/session_sync.py`, `app/context_policy.py`,
`app/conversation_store.py`, `app/llm.py`, `tests/test_context_hardening.py` and
`tests/live_context_validation.py`, plus further edits to the pass-1 files. The only DB change is
the existing `app.conversations.context_state` JSONB, which now holds a versioned snapshot. No
DDL.

## Files changed by the documentation sessions (documentation only)

**Created:**
- `CLAUDE.md`
- `docs/PROJECT_CONTEXT.md`
- `docs/AI_PIPELINE.md`
- `docs/SCHEMES.md`
- `docs/CURRENT_STATE.md`
- `docs/KNOWN_ISSUES.md`
- `docs/DECISIONS.md`
- `docs/TESTING.md`
- `docs/HANDOFF.md`

**Rewritten** (the previous versions were stale two-scheme docs):
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`

**Amended by the audit:**
- `CLAUDE.md`: PII-file and seed-password guardrails.
- `docs/{ARCHITECTURE,AI_PIPELINE,DATA_MODEL,SCHEMES,TESTING,DECISIONS,KNOWN_ISSUES,PROJECT_CONTEXT,SECURITY}.md`.
- `deploy/DEPLOYMENT.md`: the verify commands now match the auth on `/health`, `/metrics` and
  `/api/rag/status`.

**Amended (initialisation):**
- `README.md`: scheme list, model table, docs pointer.
- `docs/SECURITY.md`: corrected the DB-role claim.
- `docs/TECHNICAL_BRIEF.md`: marked as a historical snapshot.
- `docs/INFERENCE_REQUIREMENTS.md`: added a status note.

## Scheme substitution (2026-09-26)
- KI-039 is **fixed**: "give me same for <scheme>" is a context-preserving follow-up
  (AI_PIPELINE.md §5.6).
- It is live-verified on the reported conversation and 6 more scheme pairs; the negative cases
  are unchanged.
- New Medium issue KI-040: MGNREGA "beneficiaries" is undefined.

## Live context validation (2026-09-26, no code changes)
- 53 turns, 47 PASS, 1 caveat, 5 FAIL: `docs/Context_Validation_Report_2026-09-26.md`.
- **Open High issues from it:**
  - KI-032: stale block in the committed state;
  - KI-033: stale summary after a knowledge digression;
  - KI-034: SQL ignored mandatory entities and the verifier passed it;
  - KI-035: summing distinct beneficiaries across years.
- **Medium:** KI-031 (raised), KI-036, KI-037.

## Test status (2026-09-27, after the calendar-date fix KI-078, VPN up)
- pytest, 24 pytest-style files: **915 passed**, 0 failed. Plain scripts: **14/14**.

## Test status (2026-09-27, after the Focus Plus fixes, VPN up)
- pytest, 23 pytest-style files: **891 passed**, 0 failed (2026-09-27, after the CM Elevate fixes).
- Plain scripts: **14/14**. Live context suite: **43/43** (follow-up 29/29).
- Focus Plus use cases: 39/39 questions on 2 of 2 fresh live runs (30/30).

## Test status (2026-09-26 night, after the MGNREGA all-villages fixes, VPN up)
- pytest, 21 pytest-style files: **826 passed**, 0 failed.
- Bulk live: 448/448 block and 12,850/12,850 village queries on the final code.
- Plain scripts: **14/14**.
- Live context validation: **43/43 checks** (repeated twice). Legacy A/B: 39/43. Details are in TESTING.md.
- `smoke_restructure.py`: not run (needs a live server on :8502).

## Deployment status
- Deploy artefacts exist:
  - systemd;
  - nginx + ModSecurity;
  - Docker and docker-compose;
  - SQL role and retention scripts.
- Local dev `.env`: DB user `postgres`, `AUTH_ENABLED=true`, `EMBEDDING_PROVIDER=local`, CA
  bundle path set, `REDIS_URL` blank.
- Which environment is live, and with which DB role: UNKNOWN — NEEDS VERIFICATION.

## Next tasks (suggested, in priority order; none started)
0. **Decide what to do about KI-022**, the pushed raw file with unmasked bank accounts, and
   KI-023, the plaintext seed passwords. This is the user's or data owner's call: remove the
   file, possibly rewrite history, review repo access.
1. Wire the PG alias view into `_focus_legacy_pg_name_answer` (KI-020). This is the promised
   follow-up to the ingestion team.
2. ~~Persist the clarification-resume state (KI-001) and the last turn (KI-028)~~ — done
   2026-09-26 (D-023). New item: re-run the live suite on the 2026-09-29 changes (D-030).
3. Least-privilege DB role and table allowlist for generated SQL (KI-004).
4. Request-id propagation and logging of each attempt's SQL (KI-003).
5. A golden-set accuracy benchmark per scheme (KI-017).
6. Fix test collection so `pytest tests` works (KI-018).

## Components that should not be changed casually
- `pipeline.execute_with_repair` guards and `_verify_sql` filters. Each one encodes a live
  incident.
- `compose_response` faithfulness and hedge checks.
- `db.run_readonly` / `_assert_safe`.
- `_SCHEME_NAME_MATCHER`, `_is_ambiguous_focus` and `_pin_cm_elevate_dataset`: the scheme-name
  collision handling.
- `_reply_abandons_scope_pause` and the `pending_scope_q` resume logic.
- `data/<scheme>/*.yaml`: the SME contract. Change it only with an SME-backed reason, and keep
  `schema_context.py` in step.
- `app.*` DDL in `appdb.py`: additive `IF NOT EXISTS` only, because an older build must tolerate
  a newer schema.

## Parallel lanes (2026-10-28), temporary, folded in at final integration

### Lane A1 · Platform & security (KI-450 to KI-479)
- Progress: not started
<!-- end lane A1 -->

### Lane A2 · Conversation & frontend (KI-480 to KI-509)
- Progress: context-memory tasks done on `lane/a2` (2026-10-29; local commits, not pushed). REL-01, UI-01, UI-02 open.
- **What works now (VERIFIED offline with the real functions, and live on 2026-10-29 with the VPN up: live context
  suite 107/107, harness P1 / P2 over HTTP incl. a real cache hit, CTX-07 chats, nl2sql eval 97.7% + 31 expected
  pauses):**
  - Topics survive cache hits, small talk, "stop" and "Continue with …"; "go back to <place>" restores that
    question's scope (CTX-02, KI-400, KI-480).
  - A conversation answers only its owner (403 otherwise); one turn at a time per conversation per worker; a
    failed (503/504/5xx) or stopped turn leaves the session as it found it; the plain /api/query is capped at 110 s;
    the UI mints unguessable session ids (CTX-01, CTX-10, REL-02b). (The UI's silence timer is E11's, on Main.)
  - "Start a new topic" / idle expiry clear the summary on every worker; the KI-314 load retry really retries
    (CTX-11, CTX-12).
  - A typed "stop" keeps the topic; a paused first reply after expiry keeps the Continue chip; cached answers carry
    no `translated_from` (CTX-13, CTX-14).
  - The cache gate is proven on every harness turn (CTX-06). Deleting a chat removes its memory, paused run and
    Session; retention is opt-in (CTX-04a). The decision log holds no question text (CTX-08).
  - "Break it down by district" after a statewide answer and "Compare … with <place>" are rewritten
    deterministically (CTX-07, KI-363, KI-364; the live check found and fixed KI-364's inherited district). KI-416
    was not reproduced live.
  - Eval: deliberate pauses are `expected_pause`, not misses (CTX-09).
- **Tests (rebased on Main 1360c3b):** 4,402 passed, 0 failed, 3 skipped; 14/14 scripts; frontend lint + 13/13.
- **Open, user decisions:** D-A2-CTX-09 sign-off; retention periods; KI-482 (semantic memory almost never used) and
  KI-483 (summary covers 4 questions).
- **Test team report (2026-10-29, 7/10):** Bugs 1-5 and the typo case traced to their causes and fixed (KI-487..492);
  offline-verified, live retest pending (TT1-TT6). Not changed: the D-064 "applications" request (user decision),
  composer wording / units (lane B2), the 8,921 vs 8,948 total (data).
- **Report fixes VERIFIED live (2026-10-29 evening):** all six repros pass over HTTP; the report's "What works" rows
  pass; no new failure in the 94 context scenarios or the live context suite.
- **2026-10-30:** report fixes re-verified live on the merged code (11/11 scenarios); the rulebook D-A2-CTX-09 is
  partly superseded by D-089 / D-090.
<!-- end lane A2 -->

### Lane B1 · NL to SQL, schemes & evaluation (KI-510 to KI-539)
- Progress: not started
<!-- end lane B1 -->

### Lane B2 · Answers & knowledge base (KI-540 to KI-569)
- Progress: not started
<!-- end lane B2 -->
