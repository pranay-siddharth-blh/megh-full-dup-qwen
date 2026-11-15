# CLAUDE.md — Megh One AI (Meghalaya Conversational Analytics Chatbot)

Read this first, every session. It is short on purpose; details live in `docs/`.
Last reconciled with the code: **3 Nov 2026**; §0a''' added **14 Nov 2026 (evening)** (Bitbucket merge + architecture round); §0a'' added **12 Nov 2026 (night)** (the live voice and its Secretary view D-103..D-105, test counts, the
gateway outage of 2–3 Nov). **Voice layer updated 10–11 Nov 2026 (§0); `docs/` not yet reconciled with it.**

## 0. Current state of the live voice (10–11 Nov 2026) — read before touching anything voice

### 0c. 16 Nov 2026 (early) — permutation bank, branch `wt/perms-2026-11-16` (before the main demo)
- New permanent bank `tests/accuracy/run_perms.py` + `perms_bank.yaml` (+ `perms_views.mjs`): 8 schemes x all 12
  districts x follow-up chains (by district -> a district's blocks in 6 wordings -> most / top 3 / lowest -> bar / pie /
  table / line / map; "only <block>", year swap, "and for <district>", "the <measure> instead", no-scheme "breakdown by
  blocks of X" -> pick), one-shot scheme+measure+year+district+block for EVERY block (55) twice, vague questions that
  must ask back (no measure, "Focus", CM Elevate dataset, a block that is also a constituency), the user's logged
  wordings. Each chain runs TYPED (raw words; a chart switch = `viewOnlyRequest`) and VOICE (the engine's
  `megh/shaper.py shape()` with the adapter's memory; a chart switch = `canonicalView`); truth = own SQL from the
  catalogue definitions (D-060: PMAY-G counts include the 126 placeholders). `--build` rewrites the YAML from megh_db.
- Pipeline fixes (general, no regex): c01 rank reader takes spoken fillers ("um which block is having the lowest");
  c01 measure swap reads a previous measure split by helper words ("How much money WAS disbursed" -> "the producer
  groups instead"); c18 "only <name>" after a by-block answer reads a block that is also a constituency / village at
  the block level (no ask-back); metric_catalog `_value_sql` money below a crore exact to the rupee (2 places of a
  crore had said Rs 6,30,000 as "Rs 6,00,000"); c16 `_c16_year_series`: "per / every / each financial year" (and
  "per financial" with year lost) = the year grouping, "across all districts" beside it = the whole state.
- Engine (Full Duplex `megh/shaper.py`, backups `ops/backups_original/2026-11-16/shaper_*perms*`): a district + a lower
  level ("the blocks of X", "drill down into X", "by blockwise") = its breakdown, never "what about X block?"; a rank
  word keeps the question as said; "per financial" -> "per financial year"; "Meghalaya <MGNREGA-only measure>" ->
  MGNREGA; bare "map please"; "show me the show me ..." restarts collapsed; "the headline just for MGNREGA" passes as
  said; a view command is never held; leading "Okay, now" stripped; a multi-sentence ramble with no content held.

### 0b. 15 Nov 2026 (night) — the user's live-test round, ALL MERGED on `arch/step1-2026-11-14` (read first)
- From the user's live test (log + `app.conversation_turns` read first, standing rule): four builds merged —
  98a434f drill-down follow-ups (KI-728; D-110 (b) REVISED and **confirmed by the user**: "by block" after a ranking =
  the blocks INSIDE those districts; "by year" = each district side by side; gold BD-01..12, bank 413), a09911e
  natural written + spoken answers and screen commands (D-114, KI-729; the two 0a'''''' notes below), 4e93f3e voice
  stage captions + picture timing (D-115, KI-730), e49f900 question bank (`docs/Megh_Question_Bank.pdf` +
  `tools/make_question_bank.py`; 156 DB-verified client-style questions), 72fc810 "which district leads in each
  scheme" (the bank's one miss: "leads" was not a rank word; a singular district ranking = one leader per scheme).
- Results on the combined code: **model-on bank merged-4 = 413/413**, no-model nomodel-20 = 372/413 (0 newly
  failing), pytest 7,065 passed 0 failed, scripts 14/14, frontend 232/232. Server 8401 restarted on 72fc810.
- After the merge (abd83bf, 298bbf4): the leader-per-scheme reading narrowed to a HIGH singular district ranking
  said per scheme (each / every / per; 3 old reading tests had failed); the spoken ranking / breakdown open with a
  SHORT sentence naming the leader (the picture lit the first place 1.5 s after its name: captions come a checked
  sentence at a time); `voice_explain_*` throwaway sessions never show in the history list / search (4 had been
  left); the voice tests now expect the spoken form (D-114). FINAL: pytest 7,076 passed 0 failed, scripts 14/14,
  voice UI 153/153 (captions 20, stage 33, views 37, voice 23, visual 40). Server 8401 runs abd83bf.
- Owner items open: D-114 extras (share + multiple in the lead; spoken rounding from 1 lakh; explained to the user,
  no answer yet); the guard could release captions at ':' / ';' (faster first caption, a D-108 decision); CM Elevate
  Legacy 2,820 vs 2,823 (3 de-sanctioned records; data team).

### 0a''''''. 15 Nov 2026 (night) — Natural answers + screen commands (D-114, KI-729), worktree branch `wt/natural-2026-11-15`
- User (live voice): answers "robotic and quantized"; "take me back to the dashboard" answered "I can't apply, book, pay…".
- **Written:** a ranking / comparison / trend / split opens with an insight-first lead written by CODE (no model call;
  `app/pipeline/common/c19_natural_answers.py`): leader + margin, share of the whole, bottom + multiple, a trend's
  dip / peak; exact figures, places in Title Case, the same list underneath. Every lead figure checked against the
  rows; a miss -> the E9 answer. Places in Title Case on every data answer (`_c19_title_places`).
- **Spoken:** `result["spoken"]` (2-3 sentences, rounded figures marked "about / nearly / just over", "… on your
  screen"), every number checked (exact, or within 3 % after a qualifier); the page reads it (`voiceSpeech.spokenForm`);
  `speech_guard` accepts a marked rounding within 3 %, still blocks inventions.
- **Screen commands:** `app/ui_commands.py` (closed vocabulary, no regex) + `voiceViews.canonicalNav` (same list): any
  wording of "back to the dashboard / go home / close the chart / the chart again"; the chat answers a typed one itself
  (`edge_type` ui_command), the guardrail model's out-of-scope verdict is overruled for app commands, the voice
  instruction canonicalises navigation. Off switch: `ANSWER_NATURAL_ENABLED=false`.
### 0a'''''''. 15 Nov 2026 (night) — voice stage captions + picture timing (D-115, KI-730), branch `wt/voiceui-2026-11-15`
- The user's live test (real Gemini Live): captions at the top of the stage missing / flickering, lines bobbing, the
  picture late and out of step. Root cause: since 14 Nov the relay sends captions a checked sentence at a time
  (VOICE_BLOCK_UNSOURCED) and the page held each piece until the end of Gemini's audio burst; the picture's items are
  revealed from the captions. NOT the D-112 / D-113 merges (the pre-merge build measures the same). Fix, page only:
  `frontend/src/chat/voice/captionPacer.js` (words shown as the playing audio reaches them), words fade in place,
  stable wrapping. Test: `tests/voice/ui_voice_captions.py` (fake Live `!!burst`). Details: DECISIONS D-115.

### 0a'''''. 15 Nov 2026 (evening) — EVERYTHING MERGED on `arch/step1-2026-11-14` (read first; the two 0a'''' notes below say "not merged yet": they are)
- Merged in order: answer frame (D-110), streaming (D-112), dictation (D-111), orb + AI-mode panel (D-113), the
  independent review's fixes (2d27ef9), more deterministic answers (`wt/nomodel2`, cad3ae6), Focus Legacy list units
  (79331c9: "₹10.93 crore total disbursed", not "… total disbursed cr"), follow-up after an aside (9e9a80f: the
  durable-frames fallback no longer assumes the newest frame is the aside's).
- Results on the merged code: **model-on gold bank merged-3 = 401/401 (100%)**; no-model bank nomodel-19 = 360/401,
  0 newly failing; full suite 6,876 passed, 0 failed, scripts 14/14 (cad3ae6). Worktrees at `D:\megwt\<name>`.
- Not done: a live microphone test by a person (dictation, orb); the voice bank (needs qwen3-tts, which returns 404).
  MEGH-LANG is still the pre-merge copy; switch it over only when the user says so.

### 0a''''. 15 Nov 2026 — Dictation (D-111, worktree branch `wt/dictate-2026-11-15`)
- **The composer mic now DICTATES** (types the officer's words at the caret, the box stays visible); the live voice is
  opened by the voice orb (another workstream; `live.open()` is unchanged, the orb calls `micLock.stopDictation()`).
- Server `app/dictation/` (`/ws/dictate`: router, session, segmenter, ears, clean, numbers, words) + `app/asr_gate.py`
  (speech never takes the LLM's `_slot()`; `/api/query/transcribe` moved too) + `data/dictation_hearing.yaml` (read
  by dictation only). Page: `useDictation.js`, `dictation/{machine,insert,micLock}.js`, `components/DictationBar.jsx`;
  `useVoice.js` stays as the fallback (no socket).
- Tests: `tests/test_dictation_ws_2026_11_15.py`, `tests/test_dictation_clean_2026_11_15.py`,
  `frontend/tests/dictation.test.js`; accuracy runner `tests/accuracy/dictation_bank.py` (240 spoken clips, real
  qwen3-asr; `--rescore` re-scores a recorded run offline). Results in docs/TESTING.md §3; limits KI-725, KI-726.
### 0a''''. 15 Nov 2026 — the answer frame (D-110), worktree branch `wt/frame-2026-11-15` (not merged yet)
- Follow-ups ("by block", "only Ri Bhoi", "which is the lowest", "top 3", "what about 2023-24", "and the households
  instead") are read as ONE edit of the last data answer's frame (`app/answer_frame.py`, pipeline `c18`), rendered as
  one canonical question, inheriting exactly the frame's filters. Details: docs/CONTEXT_AND_LANGGRAPH.md §3a, DECISIONS
  D-110, KNOWN_ISSUES KI-727 (what it leaves to the older rules). Offline green; nothing run with the model ON yet.

### 0a'''. 14 Nov 2026 — THIS checkout is where work continues: Bitbucket merge + architecture round (read first)
- **What this folder is:** `D:\meg one clone\meghoneai` = the team's Bitbucket Main (`blh2026/meghoneai`, 5c1deb1, 13 Nov:
  CMSS + Homestay = 8 schemes, D-099..D-102) merged with our voice / accuracy work. **We only pull; push is disabled on
  every remote.** Branch **`arch/step1-2026-11-14`**. `D:\meg one clone\main_pristine` = the team's untouched Main (to
  tell their failures from ours). `D:\MEGH-LANG\MEGH-LANG\meghoneai` = the OLD pre-merge copy (branch
  `local/fullduplex-voice-2026-11-14`), still runnable, not developed any more. Our ids were renumbered (KI-660..692 ->
  KI-691..723, D-098..102 -> D-103..106; `docs/ID_RENUMBER_2026-11-14.md`). New today: D-107, D-108, D-109 (DECISIONS.md).
- **Run things:** Python = `D:\MEGH-LANG\MEGH-LANG\meghoneai\.venv`; `frontend/node_modules` is a junction to
  MEGH-LANG's; `npm test / lint / build` only from a path without spaces (`subst M: "D:\meg one clone"`, then
  `M:\meghoneai\frontend`). Full test run = pytest over the real test files + the 14 script-style `tests/test_*.py` run
  on their own (bare `pytest tests` dies on them, KI-018; docs/TESTING.md). `.env`, `certs/voice.env`,
  `gateway_models.env` are git-ignored copies. Everything runs as `superadmin` (`MEGH_VOICE_USER=superadmin`).
- **Built 14 Nov (the GPU crashed ~11:50; done offline, five Opus agents in worktrees `D:\megwt\<name>`, all merged):**
  - Follow-ups by rule (c01 + the ctx07 loop in c14): regroup ("break that down by block"), regroup + year, rank ("which
    is lowest", "top 3", rank after rank), only one place ("only Ri Bhoi"), one place of a comparison, measure swap
    ("what about the households instead"), value filter ("only the completed ones"), year-only / year / place swap;
    also on the model-failed path. Tests `test_regroup_followups_2026_11_14.py`, `test_followup_rules_2026_11_14.py`.
  - Cross-scheme = data (D-107): `data/cross_scheme.yaml` + `app/cross_registry.py` build every cross table; headline =
    the welcome card's figure; parallel fan-out; grain in `semantic_cache.scope_signature`; "compare all eight schemes".
  - Guardrails (D-108): `app/pii_mask.py` (`PII_LOG_MODE`), unsourced spoken numbers blocked (`VOICE_BLOCK_UNSOURCED`),
    `VOICE_MAX_SESSION_MINUTES` 60 / `VOICE_HELLO_PER_MINUTE` 60, AI-voice disclosure + "AI-generated voice" label.
  - No-model coverage (D-109): spelling vocabulary + `not_typos`; catalogue: approved synonyms keep their words, place
    aliases (WGH), fewest / greatest, constituency filter via `cross_registry`, two-or-three-measure totals in one
    query, the CM Elevate valid-only default (`_c16_cme_default`); answers read "person-days of employment", "₹X crore
    disbursed". RAG: every knowledge path grounded and scheme-scoped, `rag.check_kb_coverage()` at start-up.
  - UI: voice stage smoothness (style recalc ~5x less, no layout while charts are up), AI label at every width.
- **Measured:** pytest **6,343 passed + the 4 known failures** (3 `test_accuracy_gold_fixes` CM Elevate rejected vs the
  team's D-101; BLH8 `test_cacheable_shapes`, fails on pristine Main too); scripts 14/14; frontend 180/180, lint clean.
  **No-model gold bank** (every model endpoint 503, megh_db real; a pass = rules + DB alone): 154/394 -> **308/401
  (76.8%, nomodel-14)**, never a newly failing case. Results in `tests/accuracy/results/*_nomodel-*.json`.
- **NOT verified yet (needs the model + megh_db):** the gold bank with the model ON (`tests/accuracy/run_gold.py --label
  merged-1`), the probe matrix, the voice bank (needs TTS), a live mic test. **Check first:** nomodel-15 (run while
  megh_db was failing) answered "CM Elevate applications WGH" -> pause -> typed "CM Elevate" STATEWIDE (7,375, not
  1,625): the resumed question was just "CM Elevate (applications)". The resume functions are right offline;
  reproduce with the DB up before trusting the CM Elevate pause path.
- **Owner / team decisions open:** synonyms PMAY-G "beneficiaries" = houses sanctioned, CM Elevate Legacy "subsidy" =
  subsidy disbursed, MGNREGA "households" = households employed; MGNREGA households across all years (bank sums years,
  catalogue refuses: single_year); retention 0 days, `GUARDRAIL_MODEL_FAIL_CLOSED` / `BOOT_GUARD_ENFORCE` off, seeded
  password `changeme123`; the onboarding tool still writes `cross_figures` overrides into `scheme.yaml`.
- Cross-project handoff (voice engine, ports, backups, history): `D:\Full Duplex Architecture\CLAUDE.md` §0.

### 0a''. 12 Nov 2026 (night) — FINAL: fix round done, the user's live test PASSED, everything STOPPED
- **Stopped:** no server running (8401 app, the sovereign voice 8144 / engine 8170 in `D:\Full Duplex Architecture`,
  every test copy). Nothing deployed. The full cross-project handoff is `D:\Full Duplex Architecture\CLAUDE.md` §0.
- **Live test (user, real mic, 18:41-18:56): "near perfect, no real issues"** — dashboards by voice, pie / bar / map /
  line by voice, comparisons, back to the dashboard, answers 2-5 s.
- **Changed in THIS repo on 12 Nov (after the accuracy round):** KI-723 FIXED (`app/pipeline/common/c02_rephraser.py`:
  `_REPHRASE_STATUS_WORDS` / `_stages`, a rephrase may not add a stage the user never said; test
  `tests/test_ki692_rephrase_stage_2026_11_12.py`, 6). Frontend, rebuilt into `web/app`: a comparison of > 8 items keeps
  its ranking (`voice/vizPlan.js` autoView); the voice menu opens above the stage (glass, the stage dims behind it); the
  footer's conversation feed and the dock chips replaced by a **scheme strip** (six schemes in `chartTheme.SCHEME_HUES`,
  a tap asks the scheme's dashboard question from `voice/meghVoicePack.js` `dashboards`, generated by the Full Duplex
  `megh/domain/build_pack.py` + `export_page_pack.py`); captions get a space where two spoken lines meet
  (`useLiveVoice.js`). Backups: `D:\Full Duplex Architecture\ops\backups_megh\2026-11-12_fixround\`,
  `...6-11-12_ui_strip\`. Docs: KNOWN_ISSUES KI-723 Fixed; TESTING row "2026-11-12 (fix round …)".
- **Tests (superadmin):** pytest 5,427 passed / 0 failed; gold bank 336/337 at load, SH-X027 passes alone -> 337/337;
  frontend 158/158; visual 40/40 + scheme bank 18/18; voice bank (real pipeline, sovereign engine) 81/82 (A1 "headline
  figure of every scheme" = pipeline variance: by-year once, correct the next time; open).
- **`gateway_models.env`** (repo root, git-ignored, identical copy in Full Duplex): every model URL / key / model name,
  incl. the Kyutai gateway key. The app still reads `.env`; this file is for lookup / copying only. Never commit it.
- **Open (nothing started; the user said do nothing until he says so):** P0 guardrails before deployment — retention ON
  (CONVERSATION_RETENTION_DAYS / QUERY_AUDIT_RETENTION_DAYS are 0), PII redaction in the audit JSONL (raw question + IP),
  block (not just log) unsourced spoken numbers in `app/voice/speech_guard.py`, AI-voice disclosure (IT Rules 2026),
  BOOT_GUARD_ENFORCE, KI-022 / 023 / 016 / 024, guardrail-model outage policy (fails open by default); P1 / P2 list in
  the Full Duplex CLAUDE.md. Make the A1 cross-scheme headline deterministic. KI-699 = user decision. Assistant name:
  brainstorm only.

### 0a'. 12 Nov 2026 (afternoon) — accuracy round RESUMED and finished (supersedes the "stopped mid-edit" bullet below)
- Every half-done edit of the previous agent was verified and KEPT (diffs vs `ops\backups_megh\2026-11-12_accuracy\`; the two
  follow-up rewriters were complete). One test pinned the old YAML (`scheme_specific ->> 'file_status'`) and was updated to the
  plain `file_status` column the DB team exposed (VERIFIED readable). New fixes KI-717..KI-722; a regex in `cm_elevate.py`
  removed (KI-719). Docs: D-106, KNOWN_ISSUES KI-701..691, AI_PIPELINE §2.9i, TESTING "Accuracy gold bank".
- Gold bank (superadmin, live truth): 182/212 → **315/315 cases (bank widened)**; pytest 5,421 passed / 0 failed; scripts 14/14;
  live golden 44/45 (CARD-cme-apps, KI-699, failing since 2026-10-30); held-out 64/74 (was 62/74 at the start of the session, 68/74 on 2026-10-30 before D-B1-CME-01; 0 regressions caused by this round). Nothing restarted, nothing committed. Backups of this session's first edits:
  `D:\Full Duplex Architecture\ops\backups_megh\2026-11-12_accuracy_b\`.

### 0a. 12 Nov 2026 — quality / accuracy / scalability round (STOPPED mid-way for a laptop shutdown; resume from here)

**User decisions (12 Nov):** pipeline fixes ARE approved where the DATA is wrong (the brain is no longer frozen for
accuracy fixes); read-only DB access for independent truth SQL; every run as `superadmin` (only); voice recordings,
new TTS models and gateway deployment come last.

- **Accuracy (agent stopped MID-EDIT):** `tests/accuracy/` — `gold_bank.yaml` (212 cases from the three PDFs, the Test
  Case Results sheet, the goldens, the voice bank, paraphrase families, follow-up chains), `build_bank.py`,
  `run_gold.py` (in-process, as superadmin, truth recomputed live with independent read-only SQL), `results/`.
  Baseline (regraded) **182/212 cases = 85.8% (219/251 turns)**: CM Elevate 1/15, chains 19/26, charts 12/15, PMAY
  36/39, Focus Plus 19/20, MGNREGA 53/54, CM Elevate Legacy 16/17, cross 8/8, Focus Legacy 17/17. Failure tags:
  sql-wrong 13, composer-misstated 12, routing/intent 6, clarification 1. **Pipeline files it edited (originals in
  `D:\Full Duplex Architecture\ops\backups_megh\2026-11-12_accuracy\`):** `app/conversation_layer.py`,
  `app/pipeline/common/c06_years_tranches.py`, `c11_sql_verify_repair.py`, `c13_compose_and_data_stages.py`,
  `c14_turn_stages.py`, `c16_metric_catalog.py`, `c17_data_answer_rules.py`, `app/pipeline/schemes/cm_elevate.py`,
  `cm_elevate_legacy.py`, `focus_legacy.py`, `mgnrega.py`, `pmay_g.py`, `data/cm_elevate/cmelevate_pending_rule.yaml`.
  It was adding two deterministic follow-up rewriters ("only <scheme>" after a comparison; "only the X ones" keeping
  the breakdown) when stopped. All these files COMPILE; they are NOT yet verified: re-run `tests/accuracy/run_gold.py`
  and the pytest suite (§7) before trusting them, and complete their §8 documentation (DECISIONS / KNOWN_ISSUES /
  AI_PIPELINE / TESTING), which may be partial. Latest result file: `results/2026-11-11_1148_fix2.json`.
- **Voice toggle (backend part done, live after a restart):** `app/voice/relay.py` reads `hello.voice` (one of
  `SOVEREIGN_VOICES` a..e) and, ONLY when `VOICE_LIVE_URL` is set (the sovereign engine), puts it in the setup's
  voiceName; Gemini never gets a page-chosen name. Voice relay unit tests 38/38 after the change.
- **Frontend (edited, ESLint clean, `node --test` 158/158, NOT yet built into `web/app/`):** voice layer —
  `voice/voices.js` (new: the voice list, a/b/c Indian women, d Indian man "coming soon"), `useLiveVoice.js` (hello
  carries the voice; `setVoice` re-opens the session in the new voice, which says one line), `VoiceStage.jsx`
  (`VoicePicker` in the header), `styles/voice-stage.css` (picker styles), `voice/vizPlan.js` (scheme / district /
  spoken-form lists now come from the generated `voice/meghVoicePack.js`, written by `D:\Full Duplex
  Architecture\megh\domain\export_page_pack.py` from this repo's registries). Chat charts (from the 30 Oct chart
  PDF): `components/Charts.jsx` (monotone line curves: no overshoot above the real peak; new `hbar` horizontal bars,
  largest first), `analytics.js` ("horizontal" understood; several chart types named -> one card per type, up to 3;
  place labels title-cased on grouped / per-scheme / joined charts), `columns.js` (`colTitle`: no "short"/"key", a year
  column reads "Financial year", no doubled "(₹) (₹ lakh)"). Originals: `D:\Full Duplex
  Architecture\ops\backups_megh\2026-11-12_charts\` and `2026-11-11b\`.
- **Engine side (outside this repo):** question shaper + domain pack + place-name snapping from this repo's
  `data/*/*_entity_resolver.yaml` (read-only) + hearing fixes; see `D:\Full Duplex Architecture\CLAUDE.md` §0.
- **State at the stop:** nothing running (app 8401, engine 8170, voice 8144 all stopped). Nothing committed.


- **The live voice now runs on a SOVEREIGN engine, not Gemini.** The engine lives in a separate project,
  `D:\Full Duplex Architecture` (its `megh/adapter.py`, stack service `megh`, `ws://127.0.0.1:8170`). It speaks the
  same Gemini Live message subset this app's relay already uses, so **no backend file changed**: the app is started
  with the process env `VOICE_LIVE_URL=ws://127.0.0.1:8170` (no key is sent to it; `VOICE_ENGINE` stays `gemini`).
  Ears: Kyutai STT 1B (timing) + `qwen3-asr` (words); mouth: `qwen3-tts` with a designed Indian female voice (full
  clone, one seed, one request per answer); all on the team gateway, nothing leaves the network (closes KI-691 in
  practice; a D-101 entry is still to be written).
- **Brain frozen (user rule).** Nothing under `app/` was changed. The voice work is the engine (outside this repo) and
  the voice-layer frontend only.
- **What the engine adds in front of `ask_megh`** (`megh/shaper.py`, rules first, the on-prem LLM only for
  follow-ups): unfinished turns ("Okay. Um.", "I also want you to.") are held; fillers, false starts ("leave this",
  "do one thing"), politeness wrappers and spoken years ("twenty three twenty four" -> 2023-24) are cleaned; "every
  financial year" -> "by financial year" (user decision: one row per year); clarification replies -> the option's own
  words (ordinals, "I meant X"; two schemes to "which scheme?" -> a comparison of both, user decision); a long
  follow-up this pipeline's word lists miss (>12 words, a long pointing breakdown / chart request, one scheme of a
  comparison) -> one standalone question by `qwen4-deploy`, guarded (schemes / districts / years only from the words
  or the conversation). Complete questions and cross-scheme questions are never rewritten. Chart switches and
  navigation become fixed sentences the page acts on (below).
- **What the engine says** (`megh/natural.py`): a DATA answer with figures is re-said as warm spoken English by
  `qwen4-deploy` behind a deterministic guard (every figure, unit, rupee sign, name, caveat and the screen mention
  kept; every figure beside its own district / scheme / year label; one retry, else the checked answer itself).
  Refusals, access messages, notes, knowledge passages, row dumps and answers cut mid-row are read **as written**.
  `speech_guard` still checks every spoken number (voice bank V3 82/82). This deviates from "read word for word"
  (§5) for data answers only and needs a DECISIONS entry (D-101) before production.
- **Voice-layer frontend changed (10–11 Nov; backups in `D:\Full Duplex Architecture\ops\backups_megh\2026-11-10\`,
  `2026-11-11\`, `2026-11-11b\`, each with the previous `web/app` build as `web_app_before\`):**
  `VoiceStage.jsx`, `voice/vizPlan.js`, `voice/StageCards.jsx`, `voice/stageCanvas.js`, `voice/voiceViews.js` (new),
  `useLiveVoice.js`, `voiceSpeech.js`, `styles/voice-stage.css`, `tests/voiceViews.test.js` (new),
  `tests/voice/ui_voice_views.py` (new). Captions = what the voice says, word by word; per-item spotlight as each item
  is named; seven instant chart switches from the engine's fixed sentences (`show it as a bar|line|pie chart`, `as a
  table`, `on the map`, `as a ranking`, `as horizontal bars`; the closest allowed view + a spoken reason when the data
  can't hold it); navigation (`go back to the dashboard`, `bring the chart back`: done on the stage, never a pipeline
  question); best picture from the question's words when the data supports it; a single figure gets an "explains the
  figure" breakdown (a background query in a throwaway session, drawn only if its parts add up within 0.5%); a
  question arriving mid-answer is queued (newest wins); the "(Drawn here ...)" note is never spoken. No regex
  (D-046/047), ESLint clean.
- **Tests (all as `MEGH_VOICE_USER=superadmin`, the user's rule; `state-rd` is district-only and fails block
  questions):** `voice_bank.py --real` **82/82** on the final engine + page, every category green;
  `ui_voice_stage.py --real` 32/32; `ui_voice.py --real` 16/16; `ui_voice_views.py --real` 32/32 (+ nav 7/7);
  `node --test` 158/158. One live session per officer: a test run as superadmin and a person testing as superadmin
  replace each other.
- **Known gaps (pipeline side, brain frozen):** a district breakdown of the cross-scheme "villages in both" answer is
  ignored by the pipeline even when the follow-up is understood; "every financial year" is ambiguous in the pipeline
  itself (KI-411) — the voice layer asks it as "by financial year".
- **Open (not done):** DECISIONS D-101 (sovereign engine + natural re-saying), KNOWN_ISSUES (KI-691 closed by the
  swap), AI_PIPELINE §3.3a, ARCHITECTURE, TESTING, HANDOFF / CURRENT_STATE. None of the voice work is committed
  (branch `feature/context-window-hardening`).

## 1. What this is

One FastAPI service (`app/`) that answers Meghalaya government officers' natural-language
questions about **six scheme datasets**: MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy
and CM Elevate Legacy.

- **Data questions** → NL→SQL against PostgreSQL `megh_db` (schema `curated`), then an
  LLM-composed answer.
- **"How does the scheme work"** questions → RAG over Qdrant (`megh_knowledge`, read-only to the app).
- **Greetings / off-topic / abuse** → the edge layer and the guardrails, with no data step.
- **Typed or spoken.** Officers type, dictate (the mic types the words, `qwen3-asr`), or talk to the
  **live voice** (full duplex, D-103 / D-104 / D-105): the mic opens the Secretary's voice view — a desk of every
  scheme's figures, then a picture for every answer — the officer speaks and is answered aloud ("Good evening,
  Secretary sir" on opening), and can talk over the answer at any time. The voice never answers by itself: every
  spoken question goes down the same path as a typed one (§2).

All pipeline inference is remote, on a self-hosted vLLM gateway (`10.48.242.4`); the live voice used Gemini
Live (§5, KI-691) and since 10 Nov runs on the sovereign engine on the same gateway (§0). The UI is a **React** app in `frontend/` (Vite; D-038), built into `web/app/` and served by
the same app at `/megh-chat` and `/admin-ui`. Answers stream over SSE (`POST /api/query/stream`, D-039): the
streamed text is a draft, and every faithfulness check still runs on the full answer. **No WebSocket, except
the live voice `/ws/voice`** (D-103). After any change in `frontend/src`, run `npm run build` in `frontend/`
(the app serves the build, not the source).

## 2. Architecture in one breath

`POST /api/query[/stream]` → JWT auth → conversation layer → cache (exact, then semantic) →
`pipeline.answer_question` → spelling + context → guardrails + edge → follow-up rewrite → intent
(DATA/KNOWLEDGE) →
- **DATA:** scheme gate → `classify_scheme` → `resolve_entities` → clarification gates →
  fixed queries where they exist (metric catalogue, scheme facts, cross-scheme figures) or `generate_sql` →
  `auth.authorize` → `execute_with_repair` (AST guards + LLM verifier + up to 3 repairs) →
  `compose_response` (numeric-faithfulness checks).
- **KNOWLEDGE:** `rag.answer_from_kb` (embeddings + `qwen3-reranker`, always on).

The orchestration lives in the **[app/pipeline/](app/pipeline/) package** (one 18,700-line `pipeline.py`
until 2026-10-15):
- [app/pipeline/common/](app/pipeline/common/) — the shared steps every scheme goes through,
  `c01_followups.py` … `c16_metric_catalog.py` (the data team's metric catalogue as a fixed query, D-071),
  `c17_data_answer_rules.py` (sub-asks, SQL hygiene, runners-up, money units, dataset caveats; D-092);
- [app/pipeline/schemes/](app/pipeline/schemes/) — **one file per scheme** (`mgnrega.py`, `pmay_g.py`,
  `focus_plus.py`, `cm_elevate.py`, `focus_legacy.py`, `cm_elevate_legacy.py`): that scheme's village
  rules, fixed queries, SQL rewrites and answer checks. A scheme-only fix goes in its scheme file.

`app/pipeline/__init__.py` executes the files in `_PIPELINE_FILES` order into ONE shared namespace, so
`from app import pipeline as p`, `p.<name>` and `monkeypatch.setattr(p, …)` work as before. Function bodies may
use names from any file; load-time code (constants, regexes, defaults) only names from files loaded before it.
Every top-level name must be unique across the files: a second definition silently replaces the first for every caller
(KI-413; `tests/test_pipeline_namespace_2026_10_26.py` fails on a duplicate).
**Edit the file that holds the function** (there is no `app/pipeline.py` any more — recreating it would be
shadowed by the package and silently ignored). It is written as
**stage functions** (`_turn_*_stage`, `_data_*_stage`, `_execute_one_attempt`, …). **LangGraph is the only
orchestrator** ([app/pipeline_graph.py](app/pipeline_graph.py), 22 nodes, D-032, D-036, D-037): there is no
sequential driver, no on/off switch and no canary, and none may be added back. **Change behaviour in a stage,
never in a graph node.** Tests drive turns through the graph with `tests/_graph_turn.py`.

**The live voice in one breath (D-103, D-104)** — it sits outside the pipeline and changes nothing in it:
mic → `useLiveVoice.js` (AudioWorklet, 16 kHz PCM) → `/ws/voice` ([app/voice/relay.py](app/voice/relay.py), JWT in the
first message) → Gemini Live, which has ONE function, `ask_megh` → the relay hands the call to the **page** → the page
sends the words through the chat's own `sendQuery` → `POST /api/query/stream` (the full pipeline above, history, audit)
→ the checked answer → `voiceSpeech.spokenForm` (deterministic spoken text) → back to Gemini, read word for word →
24 kHz audio to the page. The page shows it on the voice stage (`components/VoiceStage.jsx`): Mitra's orb and
choreography (copied from the Sakala Mitra POC, read-only, in Megh's palette); the Secretary's desk
(`voice/SecretaryDesk.jsx`, figures from `GET /api/voice/board` = [app/voice/board.py](app/voice/board.py), fixed
read-only SQL beside the pipeline, D-105); every answer drawn as Mitra's canvas cards planned from its own rows
(`voice/vizPlan.js` → `voice/StageCards.jsx` → `voice/stageCanvas.js`; the district map `voice/meghMap.js`), each
item revealed as the voice is heard naming it; an answer with no picture → the chat's own answer card.
One spoken question = one `ask_megh` call, one pipeline answer, one picture: the relay merges the model's reworded
re-calls within a turn and holds a call it makes on its own after the answer was read.

Full map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/AI_PIPELINE.md](docs/AI_PIPELINE.md) (§3.3a for the
voice), [docs/LANGGRAPH_ARCHITECTURE.md](docs/LANGGRAPH_ARCHITECTURE.md).

## 3. Documentation map

| Doc | Read it when |
|---|---|
| [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) | Onboarding: what, why, capabilities, constraints |
| [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) | **Every session.** What works, what's broken, what's next |
| [docs/HANDOFF.md](docs/HANDOFF.md) | **Every session.** Where the last session stopped |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, API (incl. `/ws/voice`), auth, deploy, infrastructure |
| [docs/AI_PIPELINE.md](docs/AI_PIPELINE.md) | Any change to routing, prompts, SQL gen/repair, composer, RAG, the voice (§3.3a) |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Any change touching SQL, tables, joins, units, years |
| [docs/SCHEMES.md](docs/SCHEMES.md) | Any scheme-specific change, or adding a scheme |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Before fixing a bug (it may already be tracked) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | **Before proposing any architectural replacement** (voice: D-103, D-104, D-105) |
| [docs/TESTING.md](docs/TESTING.md) | Before and after changing code |
| [docs/SECURITY.md](docs/SECURITY.md) | OWASP control map, deploy security checklist, the live voice's controls |
| [docs/LANGGRAPH_ARCHITECTURE.md](docs/LANGGRAPH_ARCHITECTURE.md) | The LangGraph orchestrator: nodes, state, checkpointing, logs, adding a node |
| [docs/CONTEXT_AND_LANGGRAPH.md](docs/CONTEXT_AND_LANGGRAPH.md) | How the context window runs inside the graph |
| [docs/LANGGRAPH_PAUSE_RESUME.md](docs/LANGGRAPH_PAUSE_RESUME.md) | Clarification pauses as `interrupt()`; resume; the two stores |
| [docs/LANGGRAPH_MIGRATION.md](docs/LANGGRAPH_MIGRATION.md) | Flags, rollout gates, rollback, measured overhead |
| [deploy/DEPLOYMENT.md](deploy/DEPLOYMENT.md) | Deploying to the VMs |
| `data/<scheme>/README.md` | The SME contract for one scheme's YAMLs (authoritative for that scheme) |

Historical and reference documents: `docs/TECHNICAL_BRIEF.md` (a 2026-09-24 analysis snapshot
whose line numbers are stale), `docs/*_DB_Issues.md`, `docs/*Fix_Verification*.md` (QA records)
`docs/INFERENCE_REQUIREMENTS.md` (the AIOps handoff), `docs/MEGHALAYA_LANGGRAPH_ARCHITECTURE.md`
(the 2026-10-02 pre-implementation analysis for the LangGraph work) and
`docs/Context_Validation_Report_2026-09-26.md` (the live end-to-end context validation).

## 4. Development principles

- **Evidence order:** source code > DB schema > tests > config > docs > git history > chat memory.
  If a doc disagrees with the code, the code wins, and you fix the doc.
- **Don't break working behaviour.** No drive-by refactors, API changes, schema changes or
  "cleaner" rewrites. Make small, targeted, tested changes. This is a live project, worked on by several
  sessions at once: re-read a file before editing it, and commit by function, not by file.
- **Almost every regex, gate and guard in the pipeline (`app/pipeline/`) exists because of a real reported
  failure.** The comment above it usually says which one. Read that comment before changing or
  removing it.
- **Scheme facts live in `app/scheme_registry.py`** (D-079); the other registries (listed in
  [docs/SCHEMES.md §Adding a scheme](docs/SCHEMES.md#adding-a-scheme)) keep their own shape and are
  checked against it by `tests/test_scheme_registry_e5_2026_10_27.py`. Changing one scheme's name or
  pattern means running that guard and fixing every registry it names.
- **Two name collisions must never be guessed:**
  - A bare "Focus" → ask *which* Focus (Focus Plus or Focus Legacy).
  - A bare "CM Elevate" → pinned by keywords (`_pin_cm_elevate_dataset`).

  See [docs/SCHEMES.md](docs/SCHEMES.md).
- **Match the surrounding code.** Comments explain *why*, often citing the incident and date.
  Keep that style.

## 5. AI / LLM rules

- **Never trust a prose rule alone** for a wrong-number bug. The project's pattern is:
  1. a prompt rule;
  2. a few-shot example;
  3. a **deterministic guard** in `execute_with_repair` or `compose_response`.

  Prose rules have repeatedly failed under sampling.
- **Model roles are fixed** (VERIFIED in [app/config.py](app/config.py) and `.env`, 2 Nov 2026):
  - `qwen-model` (Qwen3-Coder-30B) = SQL generation, SQL repair and the SQL verifier (`SQL_GENERATION_MODEL`,
    `SQL_VERIFY_MODEL`);
  - `qwen4-deploy` (Qwen3-4B) = classifier: intent, scheme, entities (`CLASSIFIER_MODEL`);
  - `qwen35-9b` (Qwen3.5-9B) = the follow-up rewrite, the rephraser and the conversation summary (`REWRITE_MODEL`),
    the composer (`RESPONSE_MODEL`) and translation (`app/translate.py`);
  - `qwen3-asr` = dictation (`/api/query/transcribe`);
  - embeddings = gateway `qwen3-embedding`, 1024-dim (D-067, `.env`; rollback `EMBEDDING_PROVIDER=local` +
    `megh_scheme_kb_v3`). A different embedding model needs NEW Qdrant collections and re-tuned cut-offs;
  - **re-ranker = gateway `qwen3-reranker`, ALWAYS ON, on every knowledge question** (D-083, user rule
    2026-10-29). There is no on/off setting and none may be added back; the local jina re-ranker was removed.
    If it misbehaves, fix it (call format, deployment, fusion) — never disable it.
    `tests/test_reranker_always_on_2026_10_29.py` guards this;
  - **the live voice = Gemini Live** (`gemini-3.8-live`, `VOICE_LIVE_MODEL`, D-103): ears and mouth only, never a
    pipeline role. Its settings are NOT in `app/config.py` (below). **Since 10 Nov it is the sovereign engine
    (`VOICE_LIVE_URL=ws://127.0.0.1:8170`, §0): Kyutai + qwen3-asr ears, qwen3-tts mouth, qwen4-deploy for the
    question shaper and the natural re-saying, all on the gateway.**

  Do not move roles without a DECISIONS entry.
- The composer must never state a number that isn't in the result. The faithfulness checks in
  `compose_response` enforce this. Don't weaken them.
- **The live voice never decides a fact** (D-103). Rules that hold it there:
  - Gemini has one function, `ask_megh`, and the **page** answers it through `sendQuery`; never run the pipeline
    from the relay, and never let the model answer a scheme or data question itself.
  - The question sent is the call's own argument (the model is told to pass the officer's words exactly); the live
    transcript is only the fallback — measured: it lags the call and mishears years.
  - The spoken text is built deterministically by `frontend/src/chat/voiceSpeech.js` (`spokenForm`), never by the
    model; it is read word for word. Behind that prose rule, the guards: `app/voice/speech_guard.py` checks every
    number the voice said against the answers it was given; a number from its own memory makes the page run the
    question through the pipeline; a wrong number makes the page re-read the checked answer ("To be exact: …"); a
    model that says and calls nothing for 7 s after the officer finished gets the question answered by the page;
    the same words never go to the pipeline twice within 2 minutes.
  - The voice stage never answers: it draws the answer the chat got. Either the picture planner's cards
    (`voice/vizPlan.js`, from the answer's own rows only) or, when the planner has no picture, the chat's own message
    components (`BotMessage`, `TypingMessage`, `TextMessage`). On that fallback card the speech-synced reveal reaches
    a chart through `canvas.__chart` and **replaces** its data arrays, never mutates them (they are the answer's own,
    shared with the chat).
  - Mute switches only the microphone track off: the session, the answer and typed input go on (D-104).
  - One spoken question = one pipeline call, one answer, one picture (D-105): the relay answers the model's
    reworded re-calls in a turn from the first call and holds a call it makes on its own after the answer was read;
    the page's harness re-asks only when the voice said nothing or said an unsourced figure; years are never
    deviations; after an answer was read, model speech with nothing new from the officer and no page read is not
    forwarded (no answer is ever heard twice). Keep these when touching `relay.on_tool_call` / `_from_gemini`, the
    hook's `turn_complete` or `speech_guard`. Idle closes the session after `VOICE_IDLE_SECONDS` (120 s) of quiet.
  - The picture planner (`voice/vizPlan.js`) only draws cells of the answer: never a total across schemes (each
    keeps its unit and "what this counts" note), a year a scheme does not hold is a gap, never a zero. The desk's
    figures come from `app/voice/board.py` (fixed read-only SQL, the counting rules of `/api/scheme-stats`).
  - The greeting is "Good <morning|afternoon|evening>, Secretary sir" (user, 2026-11-02): no "Chief", no "Madam".
  - **English only, whatever is spoken to it** (user, 2026-11-03): `speechConfig.languageCode` en-IN, the instruction
    forbids any other language, and the relay drops any speech whose transcript holds a non-Latin script
    (`relay.not_english`, checked before the audio goes out) and has the voice say "Sorry, I can only speak English."
  - The voice says the gist: the spoken form is cut at ~320 characters at a sentence end (~20–25 s; 560 took 45–65 s),
    the rest stays on screen; an exact rupee figure with its "(≈ … crore)" is said once, as the approximation.
    It is read once per opening of the stage through the relay's read path, and is the desk's heading.
  - Timing, measured on the real voice: Gemini's transcript arrives far ahead of its audio (an answer's whole text in
    under 5 s, its audio 25–30 s), so captions are held until the audio chunk they came with is playing. Cards land
    when the voice starts reading (2.5 s at most). The reveal follows the known script (`spokenForm`): items the
    script names wait for their name, the rest come 1.2 s after the last named one; a script naming nothing → all
    3 s after the voice starts; the end of the turn → the rest. Do not drive the reveal from transcript arrival.
  - The view must open seamlessly (user, 2026-11-02): the board is fetched ahead (`api.fetchVoiceBoard`, cached
    10 min, warmed by `useLiveVoice`), the desk enters once per column, nothing on the desk animates on its own, no
    animation loops on cards (a scan line sweeps once, the insight chip breathes twice), and the orb's glow ends
    inside its canvas (a radius past the edge drew a square). `tests/voice/ui_voice_visual.py` guards all of this.
- **Few-shot examples are per scheme, ranked by IDF** (`annotations.few_shot_examples`). The
  CM Elevate Legacy bank is `cmelevatelegacy_prompt_few_shots.yaml` (v2), not the v1 file.
  **`SQL_EXAMPLES_SOURCE=yaml` is the default again since 2026-10-29 (D-086, user decision after the B5 measurement:
  qdrant needed 8 repairs vs 1).** `qdrant` takes them from `megh_sql_metadata` (unvalidated, KI-438) plus its view /
  join notes (D-074); `yaml_meaning` ranks the YAML banks by meaning (B5). Measure with the held-out set before switching.
- **Follow-up context is structured, not sliced** (D-022). The rewrite gets the previous turn's
  filters, and gets its result rows only when the follow-up points into them. Its output is
  provenance-checked field by field (D-024). Do not put raw previous-answer text back into a
  prompt.
- **Conversation state lives in Postgres** (`app.conversations.context_state`, versioned;
  `session_sync`, D-023). The in-process `SessionStore` is a per-worker cache. Anything the next
  turn needs must be in `Session.to_snapshot()`.
- **The KB is `megh_knowledge`, loaded by another pipeline and read-only to the app (D-074,
  `QDRANT_KB_READ_ONLY=true`)**: editing `data/incoming/<scheme>/` or `POST /api/rag/reingest` no longer
  changes RAG answers (KI-440); KB doc changes go to the loading team. With `QDRANT_KB_READ_ONLY=false`
  (an app-owned collection) the old flow applies: re-ingest after editing `data/incoming/<scheme>/`.
- **Languages.** Answers are in English. Khasi / Garo typed questions are translated only when
  `TRANSLATE_ENABLED` (off, the user's choice); a Devanagari (Hindi) question is always translated (D-091). Speech —
  dictation and the live voice — is English only (KI-693); the UI says so when KHA / GAR is chosen.

## 6. SQL safety and database protection

- LLM SQL runs **only** through `db.run_readonly()`. It enforces a single statement, a
  `SELECT`/`WITH` lead, no write/DDL keywords, and an auto-`LIMIT 1000`. Never bypass it. Never
  run model text through `fetch_rows` or `execute`.
- The app's own SQL is **always parameter-bound**.
- **No regex anywhere, ever (D-046, D-047).** Code that reads, checks or changes SQL works on the SQLGlot tree,
  through `app/sql_ast.py` (inspection, filters incl. `UPPER(col)` / every `IN` value, rewrites via `transform`).
  English text uses the word matcher `app/text_match.py` or string methods; the frontend uses string methods
  (ESLint enforces it in `frontend/`; `tests/test_voice_relay_2026_11_02.py` checks `app/voice/`).
  Never write `import re`, a compiled pattern, a JS regex literal or `new RegExp`.
- **Privacy tables must never be queried:**
  - `curated.fact_focus_legacy_disbursement` and `curated.bridge_pg_bank_history` (unmasked
    account numbers);
  - `curated.fact_cm_elevate_disbursement` (applicant names).

  Only the prompt protects them today; see KNOWN_ISSUES KI-004.
- **`Focus Legacy to share to BLH.csv`** (repo root) contains **unmasked bank account numbers and
  holder names** (KI-022). Never print, quote, copy or upload its rows. Count or aggregate them
  only. Never commit new raw source files.
- `app/users.yaml` holds plaintext seed passwords (KI-023). Never repeat them. Tests that need a login mint a token
  for a seeded user with `security.issue_token` (see `tests/conversation_harness/drivers.py` `mint_token`).
- **Do not modify database data or schema.** `megh_db.curated` belongs to the ingestion team
  (`megh-ingestion`). Report data defects to them as a `docs/*_DB_Issues.md` note.
- The app **creates and migrates only the `app.*` schema** (`appdb.ensure_schema`, idempotent
  `IF NOT EXISTS`).
- For ad-hoc investigation against the live DB: use read-only queries only, ideally inside a
  `READ ONLY` transaction that you roll back.

## 7. Testing rules

- Use the repo venv: `.venv/Scripts/python.exe` (Windows). System Python lacks `fastembed` and the app's
  packages, and RAG answers silently degrade under it.
- Run pytest on the **pytest-style files only** (174 of the 188 `tests/test_*.py` on 3 Nov 2026; the documented command
  greps them), then the **14 plain-script suites** (`python tests/test_X.py`), then the frontend
  (`cd frontend && npm run lint && npm test`). The exact commands are in [docs/TESTING.md](docs/TESTING.md).
  Do **not** run bare `pytest tests`: it crashes with INTERNALERROR (KNOWN_ISSUES KI-018).
- **Baseline (2 Nov 2026 night, after the Secretary view D-105):** pytest **5,342 passed, 0 failed, 3 skipped** (about 4–9 min);
  scripts **14/14**; frontend **144/144** (incl. `voicePlan.test.js`, `stageCanvas.test.js`), lint clean. Live checks: `tests/live_context_validation.py`,
  `tests/live_chat_golden.py`, `tests/live_chat_knowledge.py`, `tests/live_chat_charts.py` and the sheet runs under
  `tests/sheet_runs/` (all need the VPN); re-run the context suite after any routing, rewrite or state change.
- **The live voice** (TESTING.md "Live voice"):
  - offline, in the pytest run: `tests/test_voice_relay_2026_11_02.py` (the relay alone against the fake Gemini Live
    `tests/voice/fake_live.py`; no DB, no gateway);
  - browser, real pipeline (VPN): start `python tests/voice/fake_live.py 8499`, start the app with
    `VOICE_LIVE_URL=ws://127.0.0.1:8499`, then `python tests/voice/ui_voice.py`, `tests/voice/ui_voice_stage.py` (the
    Secretary view) and `tests/voice/ui_voice_visual.py [--only N,M]` (visual regression: the opening in one entrance,
    no orb square, then 36 questions — one call, one answer, each card entering once, drawn, revealed, on screen,
    never overlapping; screenshots in `%TEMP%/megh_visual_shots`). Headless Edge over CDP, `tests/voice/cdp.py`;
    `?voicetest=1` exposes `window.__meghVoice`, `window.__stageCards()`, `window.__stagePlan` and
    `window.__revealLog`; and the voice question bank `tests/voice/voice_bank.py [--real] [--failed]` (82 turns,
    every drawn figure checked against the answer's own cells; loop with `--failed` until green);
  - the real voice (app started without `VOICE_LIVE_URL`; costs live-audio credits): add `--real` to both, plus
    `tests/voice/ui_voice_mic.py` (the browser's microphone path with a spoken WAV) and
    `tests/voice/live_audio_probe.py` (five spoken turns in one conversation);
  - one live session per officer: run the browser suites one at a time, never two at once.
  - Last results (2–3 Nov 2026): fake voice: stage 33/33, voice 23/23, visual opening 4/4 (the 36 questions wait
    for the gateway, below); real Gemini: stage 31/32 (the miss: a test timing, fixed and green on the fake; the
    speech-synced reveal passes on the real voice); relay 25/25 in pytest. A real run can fail for outside reasons:
    the shared Gemini quota (1011 "Resource exhausted", KI-695) or the VPN / gateway dropping — read the server log
    (`voice: session ended by an error …`, `WinError 121`, gateway 503 / ReadTimeout) before suspecting the code.
- Every bug fix gets a regression test that calls the **real function**, never a
  re-implementation of it.
- Some tests pin exact source strings in the pipeline (they read the pipeline files joined in
  `_PIPELINE_FILES` order) or in the UI (`tests/test_asr_transcribe.py` reads `App.jsx`, `useVoice.js`). If one fails
  after a change, read it before "fixing" it.
- **Green tests do not prove NL→SQL accuracy.** Behaviour changes need a live check: call `pipeline.answer_question`
  in-process with the `.venv` Python, from the repo root so `.env` loads, and the held-out set
  (`tests/nl2sql_eval/run_eval.py`). The DB and gateway require the office VPN.

## 8. DOCUMENTATION MAINTENANCE IS PART OF EVERY DEVELOPMENT TASK.

This rule is permanent and mandatory.

**Before work:**
1. Read this file.
2. Read `docs/CURRENT_STATE.md`, and `docs/HANDOFF.md` if you are continuing work.
3. Read the docs relevant to the task (see the map in §3).
4. Check `git status` and recent commits.
5. Inspect the actual source code, and understand existing behaviour before changing it.

**During work**, keep track of:
- architectural changes;
- behaviour changes;
- files changed;
- tests run and their results;
- newly discovered issues;
- significant decisions.

**After work:**
1. Run the relevant tests.
2. **Always review and update `docs/CURRENT_STATE.md` and `docs/HANDOFF.md`.**
3. Update the other docs that the change affects:

| If you changed… | Update |
|---|---|
| Routing, prompts, SQL gen/verify/repair, composer, RAG, models, timeouts | AI_PIPELINE.md (+ TESTING.md, KNOWN_ISSUES.md) |
| DB objects used, joins, units, years, SQL execution | DATA_MODEL.md (+ AI_PIPELINE.md if query behaviour changed) |
| Anything scheme-specific, or added a scheme | SCHEMES.md (+ AI_PIPELINE.md if pipeline behaviour changed) |
| Components, API, auth, deploy, infra | ARCHITECTURE.md, PROJECT_CONTEXT.md, DECISIONS.md |
| The live voice (relay, stage, spoken form, its guards or settings), the Secretary view (planner, cards, desk, `/api/voice/board`) | AI_PIPELINE.md §3.3a, DECISIONS.md, SECURITY.md, TESTING.md (+ ARCHITECTURE.md for an endpoint) |
| A significant technical choice | DECISIONS.md |
| Test strategy or suites | TESTING.md |
| A bug found, fixed or re-scoped | KNOWN_ISSUES.md |

4. Run a consistency check: look for stale scheme counts, model roles, file names, test counts
   and issue statuses. Mark anything you cannot resolve as
   `DOCUMENTATION CONFLICT — NEEDS VERIFICATION`.
5. Finish with a summary covering: WHAT CHANGED · FILES CHANGED · TESTS RUN · TEST RESULTS ·
   DOCUMENTATION UPDATED · KNOWN ISSUES · REMAINING WORK · NEXT STEP.

**Never finish a significant task with stale documentation.** Do not assume earlier conversation
context exists: the repository must carry everything a new session, or a different Claude
account, needs. Don't create new top-level Markdown files for project knowledge. Extend the docs
above instead.

**Labels used in docs:**
- **VERIFIED:** read in code, config or a test run.
- **INFERRED:** reasoned from evidence, not directly confirmed.
- **UNKNOWN — NEEDS VERIFICATION:** could not be confirmed.
- **PLANNED:** not implemented.

## 9. Environment quick facts

- Windows dev box. Run from the repo root, because `.env` is read relative to the working
  directory.
- Start the app: `.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8401` — **port 8401 only,
  for the whole project (user rule 2026-10-19); never 8400 or any other port** — then open
  `/megh-chat` (chat), `/admin-ui` and `/health`. `/` redirects to `/megh-chat`. Over HTTPS (needed for the microphone
  from another machine; `localhost` works over HTTP): add `--ssl-certfile certs/dev-cert.pem --ssl-keyfile
  certs/dev-key.pem` when those files exist.
- **The venv.** If `.venv` points at a Python that is not on this machine (it was built elsewhere), rebuild it:
  `python -m venv .venv`, `.venv/Scripts/python.exe -m pip install -r requirements.lock`, plus the test tools
  `pytest==9.1.1 pytest-asyncio==1.4.1`. On 2 Nov 2026 the old one was kept as `.venv.dell-broken/` (untracked).
- UI work: Node (installed 2 Nov 2026 with `winget install OpenJS.NodeJS.LTS`); `cd frontend && npm install && npm run dev`
  (hot reload on :5173, API proxied to :8401; the dev proxy does not forward `/ws/voice`, so test the voice on the
  built app); `npm run build` writes `web/app/`, which is what the app serves.
- **Live voice settings live outside `.env`** (`.env` refuses unknown keys: a voice key there stops the app starting):
  the process environment, then `certs/voice.env` (git-ignored): `GEMINI_API_KEY`, `VOICE_ENGINE` (`gemini` | `off`),
  `VOICE_LIVE_MODEL`, `VOICE_NAME`, optional `VOICE_LIVE_URL` (a test server), `VOICE_IDLE_SECONDS` (default 120),
  `VOICE_MAX_SESSIONS`, `VOICE_TOOL_TIMEOUT` ([app/voice/settings.py](app/voice/settings.py)). The key there today is
  the Sakala Mitra POC's, so both share one Live quota (KI-695); the officer's audio and the spoken text go to Google
  (KI-691, needs sign-off before production). Behind nginx the voice needs `location = /ws/voice` (present in
  `deploy/nginx/nginx-megh-langgraph.conf`, missing in `nginx-nlpservice.conf`, KI-694).
- `megh_db` and the model gateway are on `10.48.242.4`, which needs the Fortinet VPN.
  The DB connection sometimes times out briefly, so retry. The live voice also needs outbound internet (Google).
  To tell a gateway outage from a code fault: ping 10.48.242.4, then time a one-line chat completion to each model
  through `app.config.settings` (never print the keys). On 2–3 Nov 2026 the gateway went 503 → model ReadTimeouts →
  host unreachable from the VPN; AI ops (Rahul): servers down for a platform update, about an hour.
- Qdrant is `http://10.48.242.4:6333` (data box, needs the VPN) since 2026-10-27 (D-074). The project uses
  **only two collections, both READ-ONLY to the app**: `megh_knowledge` (RAG, `QDRANT_COLLECTION`,
  `QDRANT_KB_READ_ONLY=true`) and `megh_sql_metadata` (SQL examples + view / join notes, used only with
  `SQL_EXAMPLES_SOURCE=qdrant`; the default is `yaml` since 2026-10-29, D-086). Conversation memory is off (it needs
  its own collection). Never create, write or delete any collection there (`Metadata_*`, `sql_examples`,
  `megh_scheme_kb`, ... are not ours).
- `.env` and `certs/` are gitignored and hold real secrets. Never print or commit them.
- Startup logs two CRITICAL lines on this box (`QDRANT_API_KEY` empty; `AI_MODEL_CA_BUNDLE_PATH` names a missing file,
  so gateway TLS is not verified). They are known and do not stop the app (BOOT_GUARD_ENFORCE is off).
- **State at 12 Nov 2026 (supersedes the bullets below):** everything STOPPED for a laptop shutdown, mid-way through the 12 Nov round (§0a: accuracy agent stopped mid-edit in the pipeline; frontend edits not built). Restart order: engine side first (`D:\Full Duplex Architecture\CLAUDE.md` §0), then this app with `VOICE_LIVE_URL=ws://127.0.0.1:8170`, output to a log file.
- **State at 11 Nov 2026 (supersedes the bullets below):** the app runs on 8401 with the process env
  `VOICE_LIVE_URL=ws://127.0.0.1:8170` (the sovereign engine; started from `D:\Full Duplex Architecture` with
  `run\stack.py start poc voice` and, with the Kyutai gateway key in the env, `run\stack.py start megh`). Stopped at
  the end of 11 Nov for shutdown (the app, the engine and the voice): start them again in that order. See §0 for what changed and the test results.
- **State at 16:25, 3 Nov 2026 (supersedes the next bullet):** the app runs on 8401 on the REAL voice with every fix in
  (no fake voice, no test job: stopped so the user can check it; one live session per officer, so a test run and a person
  on the same account end each other's session). Verified on the real voice: the 82-turn bank's conversations except
  the re-checks below, the client PDFs' RAG 20/20 (voice + picture) and UAT 20/20 on voice (as `state-rd`, district-level
  only, so village / block questions were refused). Not yet run on the real voice after the last fixes: the 9 re-checks
  (A6 passed; B4 B5 B6 B17 F2 F3 F5 F6), the PDF chart tests, the UAT as superadmin. Next: `MEGH_VOICE_USER=superadmin
  python tests/voice/voice_bank.py --real --only B4,B5,B6,B17,F2,F3,F5,F6`, then `voice_bank_pdf.py --real --group
  pdf_chart`, then `--group pdf_uat`, one after another.
- **Earlier state (3 Nov 2026):** everything of this project is stopped (no app on 8401, no fake voice, no test
  job), at the user's request. After the AI-ops platform update the gateway lists `qwen-model`, `qwen35-9b`,
  `qwen3-asr`, `qwen3-embedding`, `qwen3-reranker`, `qwen3-tts`, but **`qwen4-deploy` (the classifier) returns 404**:
  intent and scheme classification have no fallback for a model error, so questions fail until it is redeployed (or
  the user decides to move the classifier role, a model-role change needing a DECISIONS entry). Then: start the app
  with the fake voice and run `tests/voice/ui_voice_visual.py`, then on the real voice speak the cross-scheme bank. The live voice work (D-103, D-104, D-105) is in the working tree, uncommitted, on branch
  `feature/context-window-hardening`; `web/app/` is rebuilt with it. The work state is in `docs/CURRENT_STATE.md`
  and `docs/HANDOFF.md`.
