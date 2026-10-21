# Current State

**Last updated:** 2026-10-13 (evening), by the Cross Scheme sheet session (KI-280..290, D-044; code changed, uncommitted; LIVE-VERIFIED). Before that: 2026-10-03 (early morning), by the all-schemes all-places QA + fix session (KI-188..199, D-034; code changed, uncommitted; LIVE-VERIFIED). Before that: 2026-10-02, by the LangGraph integration session (D-032; code changed, uncommitted; **offline-verified only**, VPN down). Before that: 2026-09-29 (early morning), by the conversational scheme-swap session (KI-180; code changed, uncommitted). Before that: 2026-09-29 (late night), by the CM Elevate Legacy use-case re-test session (no code changed; KI-166..168 opened). Before that: 2026-09-29 (night), by the Focus Legacy all-levels fix session (KI-020, KI-145..165, D-031; code changed, uncommitted). Before that: 2026-09-29, by the context-relevance / semantic-contract session (code changed, uncommitted; D-030, KI-030/032/034 and KI-130 to KI-135; **offline-verified only**, VPN down). Before that: 2026-09-28 (evening), by the CM Elevate all-blocks / all-villages fix session (code changed in `app/pipeline.py`, tests; uncommitted). Before that: 2026-09-28, by the PMAY-G fix session (code changed, uncommitted; D-029, KI-089 to KI-097). Before that: 2026-09-27 night, by the Focus Plus all-blocks / all-villages session (code changed in `app/pipeline.py`, tests in `tests/test_focusplus_usecase_fixes.py` and `tests/test_mgnrega_usecase_fixes.py`; **uncommitted**). Earlier the same day: the CM Elevate use-case QA **and fix** session (code changed in `app/pipeline.py` and `app/schema_context.py`, plus a new test file; **uncommitted**). Before that, the same day: the Focus Plus use-case QA **and fix** session (code changed in `app/pipeline.py` and `app/routers/query.py`, **uncommitted**, on top of the uncommitted 2026-09-26 MGNREGA and context work).
**Branch / commit:** `main` @ `f38ea1b` (2026-10-02 session start). Uncommitted at session start: `docs/HANDOFF.md`, `docs/KNOWN_ISSUES.md` (KI-182) and untracked QA files; the LangGraph session added the changes listed below on top, all uncommitted.

**Port: 8401 only, everywhere (user rule 2026-10-19). Start from the repo venv.**

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
