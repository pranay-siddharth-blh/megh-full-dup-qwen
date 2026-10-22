# CM Elevate Legacy Use-Case Test Report — 22 Oct 2026

**Scope:** the 36 use cases in `raw_uc/Use_Cases_-_CM_Elevate.xlsx`. The workbook's only sheet is titled **"CM Elevate
Legacy"**, and its questions (sanctioned, disbursed, loan entity, financial year) are about the sanctions-and-disbursements
dataset, which is the same data as the raw file `raw_uc/Cm Elevate to share to BLH (1).csv`. Every question was run live
through the chatbot (LangGraph pipeline, real models, live `megh_db`). Every bot figure was checked against the database,
and the database was checked row by row against the raw file. §1–§8 are the original test (no code changed). **§0 is the
fix the user then asked for (D-064) and the full re-run on the fixed code.**

The raw file holds applicant names. The three name columns were never read. Only counts and sums appear here and in the
CSV.

## FINAL RESULT — every fix applied (2026-10-22 evening, user: "fix all of these")

| Check (live, final code) | First run today | Final |
|---|---|---|
| Full sweep, 300 cases (13 schemes, 12 districts, 59 blocks, 55 constituencies × 2 measures, 2 FYs, 4 name spellings) | 179 / 300 | **300 / 300** |
| Sheet's exact wording, 3 fresh chats each | 72 / 108 | **96 / 108 — 32 of 36 use cases 3/3** |
| Whole sheet asked in ONE chat (× 2) | 30 / 72 | **72 / 72** |
| Constituency questions (TC-31 / TC-32) | 25 / 55, 39 / 55 | **55 / 55, 55 / 55** |
| Raw file vs DB | — | equal on every amount, scheme, FY, lender, district, constituency (§6) |
| pytest (documented command) / 14 scripts | — | **3,608 passed, 0 failed** / **14 / 14** |

**What was fixed:**

| Issue | Fix |
|---|---|
| D-064 / KI-379 / KI-380 — wrong dataset | A bare "CM Elevate" with financial words goes to CM Elevate Legacy; otherwise the bot asks "CM Elevate (applications) or CM Elevate Legacy?" (§0 below) |
| KI-381 — constituency questions (wrong / missing numbers) | The resolved constituency, written by the model as a district / block filter, is rewritten to the documented `dim_geography.ac_name` join; a query without the constituency is sent back (never the state's figure); the verifier's false "prohibited join" is discarded |
| KI-384 — TC-36 "ALL DISTRICTS" counted as a 13th district | The query's ROLLUP total row is treated as the total, not a category; a multi-measure summary now lists every measure per district (records, sanctioned, ₹ sanctioned / subsidy / loan / disbursed) |
| KI-382 — TC-09 briefing overview | An overview / briefing request with no place or figure word is a knowledge question (3/3), retrieved with the scheme-overview phrasing: credit-linked programme, 35–75% subsidy, 15 sectors |
| KI-383 — "the data doesn't cover … null" | A place / year with no records: "No CM Elevate Legacy records are held for <place> in <FY>, so there is no sanctioned or disbursed amount to report." |
| One chat: "which schemes / each scheme / across schemes" | Inside a CM Elevate (Legacy) chat they mean its own sub-schemes (TC-13 / 18 / 19 / 25) |
| KI-386 — ward village | Not reproducible on the current code (3 / 3 correct) |
| KI-385 — MGNREGA notes in the Legacy view's `year_note` | A database issue — sent to the ingestion team (`docs/CM_Elevate_Legacy_DB_Issues.md`, Issue 3) |

**Not changed, on purpose:** TC-13 / 18 / 19 / 25 asked in a **new** chat with no scheme named ("Which schemes have the
highest number of applications?") are answered across all government schemes — the same words are the Cross-Scheme
sheet's questions (D-062). Named ("…CM-ELEVATE schemes…") or inside a CM Elevate chat they answer from CM Elevate
Legacy (sweep 5/5, one-chat 4/4). If the sheet should be read as CM-ELEVATE-only, its questions should say so.

**Conversation harness, http on the restarted :8401 (`--skip-cache`, full set):** full set **136/139 scenarios, 410/420 turns** (`logs/conversation_harness/2026-10-22_1906_d064-http.json`); E_hierarchy_drill_and_rollup = 7 transport errors, **passes on re-run** (`_d064-http-rerun.json`); the 2 left are not CM Elevate: META_recap_explain_breakdown (PMAY-G block ranking without its 375 total, D-063 answer shapes) and CMP_compare_with_scheme (the removed D-062 comparison card). Every CM Elevate scenario passes (AC04 / AC04b / AC04c, P5, AF11, AB03, U4); E_denied_block_keeps_topic and AU01 pass over http.

## 0. After the fix — D-064, user decision 2026-10-22 (re-run on the fixed code)

**Rule now** (any question naming a bare "CM Elevate" / "CM-ELEVATE", or only a CM Elevate sub-scheme such as Piggery):

| The question has… | The bot… |
|---|---|
| a **financial** word (sanctioned, disbursed, amount, crore / lakh, subsidy, loan, lender, LIFCOM, a specific FY, expenditure) | answers from **CM Elevate Legacy directly**, no question (also inside an applications chat) |
| only "applications" / "applicants" / "how many …" / "by district" | **asks "CM Elevate (applications) or CM Elevate Legacy?"** and answers from the one tapped |
| a word only the applications dataset holds (on hold, status, pending at level N, data verified, gender, sector) | answers from CM Elevate (applications) — Legacy cannot answer these |
| nothing new, inside a chat already on one dataset (a data answer, not a "what is CM-ELEVATE?" answer) | stays on that dataset |

**Code:** `app/pipeline/schemes/cm_elevate.py` (`_cm_elevate_dataset_choice`, `_names_cm_elevate`, `_cme_name_dataset`,
`_cm_thread_scheme`, chip marker "CM Elevate (applications)"); `c13` (the dataset question reads the words before the
rephrase model); `c04` / `c14` ("each scheme" follows the dataset of the last answer, then the money rule). Docs: D-064,
KI-379 / KI-380 fixed, KI-381..386 opened.

**Re-run on the fixed code (live, VPN):**

| Check | Before the fix | After the fix |
|---|---|---|
| Full sweep, 300 cases (dataset question answered "Legacy") | 179 | **258** — the 42 left are the constituency defect KI-381 (40) and the "ALL DISTRICTS" row KI-384 (1); 1 is a checker artifact (TC-26, correct figures) |
| Sheet's exact wording × 3 fresh chats | 72 / 108 | **85 / 108** (88 counting TC-26) — the rest: "which schemes" wording (TC-13/18/19/25, 12), KI-381 (TC-31, 3), KI-384 (TC-36, 3), KI-382 briefing routed to data (TC-09, 2) |
| Wrong "sanctioned" figures from the applications data (TC-15 80.63%, TC-16 8,840, TC-35 1,733, in-chat "8,840 sanctioned") | every run | **none** — all go to Legacy: 99.89%, 3, 493, 2,820 |
| Plain "applications" questions answered 8,840 from the applications data unasked (TC-11, 12, 26, 28, 29, 31, 33) | every run | **asked** every time; Legacy tap → the right Legacy figure (TC-11 2,823, TC-12 1,353, TC-29 59/59, TC-33 12/12) |
| Whole sheet in one chat (× 2) | TC-11 8,840 unasked; TC-18 "doesn't record rupee amounts" | TC-11 **asks**; TC-18 answered from Legacy. Answers after TC-14 are for FY 2025-26 by D-061 (correct for that year) |
| CM Elevate APPLICATIONS sheet (`ce_run.py`, 529, regression check) | — | **513 / 529**; 0 answered from Legacy, 0 stuck; 187 now ask first ("applicants") and answer from applications after the tap. The 16 misses are the script's record-vs-distinct-application expectations and the OFF-022 verified / not-verified split, not the dataset rule |
| Every village (before the fix, both datasets named) | — | TC-30 disbursement **525 / 525**; TC-29 applications named Legacy **525 / 526** (KI-386 ward) |
| pytest (documented command) / 14 scripts | — | **3,581 passed, 0 failed** / **14 / 14** |
| Conversation harness, full set (in-process, `--skip-cache`) | — | **131 / 137** scenarios; all 7 CM Elevate scenarios pass after one scenario fix; the other misses are known (auth-only in-process ×2, D-062 card ×2) or from D-063 (PMAY-G block ranking without its total). The http run was not done (:8401 is a parallel session's server) |

**Still failing — not covered by this fix (each needs your go-ahead):**
- **KI-381 (High, wrong numbers): constituency questions on Legacy (TC-31/32).** 30-40 of 110 constituency questions fail
  per run: "no data" / "couldn't build a query", and in a chat **the statewide figure was given as Mahendraganj's** (137
  applications, ₹22.49 crore — true 0 in FY 2025-26). The same fix as Focus Legacy KI-369 applies.
- **KI-384 (Medium):** TC-36 district summary counts the SQL's "ALL DISTRICTS" grand-total row as a 13th district. Passed
  3/3 at 12:49 today; it appeared with the parallel answer-shape work (D-063).
- **KI-382 (Medium):** TC-09 "overview for an official briefing" is sometimes routed to data (then asks the dataset and
  gives Legacy figures) and sometimes describes the database.
- Sheet wording TC-13/18/19/25 ("Which schemes…", no CM-ELEVATE): the bot compares all government schemes.

## 1. Summary

| Check | Result |
|---|---|
| Raw CSV vs DB: rows | **Match.** 2,823 rows in both, joined 1:1 (raw `id` = DB `source_row_id`, same `application_number`); 0 missing, 0 extra |
| Raw CSV vs DB: 29 fields (scheme, sanctioned, bank sanctioned, 3 subsidy + 3 loan tranches with dates, totals, lender, desanctioned, refused, FY, loan status, district, block, village, constituency) | **Match.** Every amount, scheme, FY, lender, district and constituency is identical. 3 cosmetic differences, all correct cleansing (§6) |
| Raw CSV vs DB: totals by state, scheme (13), FY (3), lender (3), district (12), constituency (56), scheme × FY, district × scheme, district × FY | **100% match** |
| Bot, **sheet's exact wording**, 3 fresh chats each | **72 / 108**: **24 of 36 use cases 3/3**, 12 use cases 0/3 |
| Bot, same questions naming **"CM Elevate Legacy"** (the 10 failing data questions) | **20 / 20** |
| Bot, full sweep (13 schemes, 12 districts, 59 blocks, 55 constituencies, 2 FYs, 4 spellings of the name) | **186 / 300** (179 + 7 that stopped at the "which dataset?" question and are right once Legacy is tapped) |
| Bot, whole sheet as ONE chat (× 2) | 30 / 72 against all-years statewide figures. Most of the gap is by design (§4): inside a chat the bot answers new questions for the latest FY (D-061, today) |

**Bottom line.** When the bot reaches the Legacy data, its figures are right: every Legacy answer in this run matched the DB
except the constituency defect (D2). The failures come from **three causes**:

1. **Routing, by design (needs your decision).** Since 19-20 Oct, a bare "CM-ELEVATE" with the word "applications" and no
   money words is answered from the **CM Elevate applications** dataset (8,840 applications), not Legacy (2,823 records).
   Most sheet questions are worded that way. This reverses the 12 Oct user decision (KI-273). 7 use cases fail on this
   alone. Naming "CM Elevate Legacy" fixes every one (20/20).
2. **Two real defects** (D1, D2 below). These give **wrong numbers** or dead ends whichever routing rule you choose.
3. **Sheet wording.** "Which schemes…" / "each scheme" without "CM-ELEVATE" is read, in a fresh chat, as all government
   schemes (MGNREGA, PMAY-G, Focus…), not the CM-ELEVATE sub-schemes (TC-13, 18, 19, 25).

## 2. Result per use case

**Sheet** = the sheet's own wording, placeholders filled (Piggery scheme, FY 2024-25, Umling block, Mahendraganj
constituency, Ri Bhoi, West Garo Hills vs East Khasi Hills), 3 fresh chats. **Sweep** = `tests/sheet_runs/cl_run.py`
(unchanged) over every place / scheme / FY, with the name written 4 ways ("CM-ELEVATE", "CM ELEVATE", "CM Elevate Legacy",
"cm elevate legacy"). A pause was answered as a user tapping the chip: scheme / dataset → CM Elevate Legacy, year → all
financial years, area → all of Meghalaya, ranking → top 5.

| TC | Use case | Sheet | Sweep | Verdict | Why it fails / DB figure |
|---|---|---|---|---|---|
| 01-08, 10 | Programme, objective, beneficiaries, sectors, assistance, credit, entrepreneurship, target, how to apply | 27/27 | 9/9 | **Pass** | knowledge (RAG) |
| 09 | Overview for a briefing | **0/3** | 0/1 | **Fail: defect D3** | Describes the *dataset* ("processed through a unified API… contains no monetary data"), never the subsidy / loan / credit link; in a chat it gives application statistics instead |
| 11 | Total applications | **0/3** | 0/1 | **Fail: routing** | Says **8,840** (applications dataset); Legacy has **2,823** |
| 12 | Applications by scheme (Piggery) | **0/3** | 1/13 | **Fail: routing** | Piggery **3,064** (applications dataset); Legacy **1,353** |
| 13 | Schemes with most applications | **0/3** | 0/1 | **Fail: wording / routing** | Sheet wording → table of all government schemes; "CM-ELEVATE schemes" → applications dataset. Legacy: Piggery 1,353 |
| 14 | Sanctioned applications | 3/3 | 1/1* | **Pass** (bot asks "applications or Legacy?" first) | 2,820 |
| 15 | Sanction rate | 3/3 | **0/1** | **Pass in sheet wording; Fail: defect D1** when written "CM-ELEVATE applications…" | Bot: **80.63%** from the applications dataset (it calls data-verified applications "sanctioned"); true **99.89%** |
| 16 | Not sanctioned | 3/3 | **0/1** | **Pass in sheet wording; Fail: defect D1** | Bot: **8,840 not sanctioned**; true **3** |
| 17 | Total disbursed | 3/3 | 1/1* | **Pass** (asks first) | ₹82.90 crore |
| 18 | Disbursed by scheme | **0/3** | 1/1* | **Fail in sheet wording** (all government schemes); Pass as "each CM-ELEVATE scheme" | Agriculture Warehouse ₹22.62 cr, Tourism Vehicle ₹14.31 cr, Agri Response Vehicle ₹14.21 cr … |
| 19 | Sanctioned by scheme | **0/3** | 1/1* | Same as 18 | Piggery 1,353 · Poultry 454 · … · Any Business Venture 30 |
| 20 | Loan entities | **0/3** | **0/1** | **Fail: defect D1** | Wrong dataset first: "CM Elevate doesn't record loans — only CM Elevate Legacy does", with a "Loans under CM Elevate Legacy" chip (an extra tap; the first report said no chip — the test driver missed it). True: Bank, LIFCOM. **Fixed (§0)**: now answered from Legacy directly |
| 21 | Applications per loan entity | 3/3 | **0/1** | **Pass in sheet wording; Fail: D1** with "CM-ELEVATE applications" (same dead end) | Bank 1,733 · LIFCOM 689 · not recorded 401 |
| 22 | Disbursement per loan entity | 3/3 | 1/1 | **Pass** | Bank ₹43.72 cr · LIFCOM ₹38.58 cr · not recorded ₹0.60 cr |
| 23 | Applications per FY | 3/3 | **0/1** | **Pass in sheet wording; Fail: D1** with "CM-ELEVATE applications" ("couldn't build a working query") | 2024-25: 2,291 · 2025-26: 137 · no FY: 395 |
| 24 | Disbursement per FY | 3/3 | 1/1 | **Pass** (asks which scheme first) | 2024-25 ₹59.82 cr · 2025-26 ₹22.49 cr |
| 25 | Schemes compared for FY 2024-25 | **0/3** | 2/2* | Same as 18 | 2,291 records in FY 2024-25 |
| 26 | Applications per district | **0/3** | 0/1 | **Fail: routing** | Bot gives the applications dataset (Ri Bhoi 2,617 …). Legacy: West Garo Hills 493, Ri Bhoi 486, South West Garo Hills 461 … |
| 27 | Disbursement per district | 3/3 | 1/1 | **Pass** | East Khasi Hills ₹22.60 cr highest |
| 28 | Districts with most applications | **0/3** | 0/1 | **Fail: routing** | Same as 26 |
| 29 | Applications in a block | 3/3 | 29/59 | **Pass** in sheet wording and when Legacy is named (29/29); bare "CM-ELEVATE applications" → routing (0/30) | Umling 224 |
| 30 | Disbursement in a block | 3/3 | **59/59** | **Pass** | Umling ₹1.80 cr |
| 31 | Applications in a constituency | **0/3** | 25/55 | **Fail: routing** in sheet wording (Mahendraganj 86 vs **174**); named Legacy 25/27, the 2 misses are **D2** | |
| 32 | Disbursement in a constituency | 3/3 | **39/55** (re-run **32/55**) | **Fail: defect D2** (30-40% of constituencies) | Mahendraganj ₹1.22 cr. One chat answered **₹22.49 crore** for Mahendraganj: that is the *statewide* FY 2025-26 figure (true 0 that year) |
| 33 | Blocks of a district | **0/3** | 6/12 | **Fail: routing** in sheet wording; named Legacy 6/6 | Ri Bhoi: Umling 224, Umsning 106, Bhoirymbong 96, Jirang 59, Mawhati 1 |
| 34 | Villages of a block | 3/3 | 6/12 | **Pass** in sheet wording and named (6/6); bare → routing | |
| 35 | Sanctioned, two districts | 3/3 | 2/6 | **Pass in sheet wording**; "sanctioned CM-ELEVATE applications" → **D1** (counts all applications and calls them "sanctioned": West Garo Hills "1,733 sanctioned", true 493); 1 Legacy answer gave one combined figure, not each district | WGH 493 · EKH 240 |
| 36 | District-wise summary | 3/3 | 1/1* | **Pass** (asks first) | |

\* the bot asked "CM Elevate (applications) or CM Elevate Legacy?". The sweep's script cannot answer that question; on
re-run, tapping Legacy, all 7 were correct (source 2 in the CSV).

**Use cases passing in the sheet's own wording: 24 of 36.** Failing: 09, 11, 12, 13, 18, 19, 20, 25, 26, 28, 31, 33. Of
these, 6 are routing (11, 12, 26, 28, 31, 33), 4 are "schemes" wording (13, 18, 19, 25) and 2 are defects (09, 20). With
"CM Elevate Legacy" named, all 10 data cases among them pass (20/20).

## 3. Defects found (bot)

| # | Severity | Use cases | Problem | Reproduces |
|---|---|---|---|---|
| **D1** | **High: wrong numbers** | 15, 16, 20, 21, 23, 35 (and 14 inside a chat) | **"CM-ELEVATE applications" + a sanction / loan / FY word goes to the applications dataset without asking**, although only Legacy holds sanctions, loans and FYs. Results: **(a) wrong figures labelled as sanctions**: "80.63% sanctioned" (true 99.89%), "8,840 not sanctioned" (true 3), "West Garo Hills 1,733 sanctioned" (true 493); in a chat after an applications answer, "How many applications have been sanctioned under CM-ELEVATE?" → **"8,840 applications have been sanctioned"** (true 2,820); **(b) detours**: "only CM Elevate Legacy records loans" + a Legacy chip (TC-20, 21), "total amount disbursed" in that chat → "CM Elevate doesn't record rupee amounts"; "couldn't build a working query" (TC-23) | 3/3, every run |
| **D2** | **High: wrong / missing numbers** | 31, 32 | **Constituency questions on Legacy.** The SQL model filters `lgd_district = '<constituency>'` instead of `dim_geography.ac_name` → null → "the data available does not cover…" (Jirang, Mawkyrwat, Mawthadraishan, Nartiang, Raliang, Selsella, Sohing, Umroi, Rongara-Siju, Raksamgre) or "couldn't build a working query" (Amlarem, Mawsynram, Pynursla, Rongjeng, Shella, South Tura, William Nagar). In one chat the filter was dropped and the **statewide** FY 2025-26 total (₹22.49 cr) was given as Mahendraganj's. Several also get an extra "whole or part of the constituency?" question after "constituency" was already chosen | TC-32: 16/55 and 23/55 fail on two runs |
| D3 | Medium | 09 | The briefing overview describes the database ("unified API", "contains no monetary data"), not the programme (35-75% capital subsidy, credit-linked bank / LIFCOM loan, 15 sectors). "No monetary data" is wrong for Legacy | 3/3 |
| D4 | Low | 32 (in chat) | A place / year with **0 records** is answered "the data available doesn't cover… the result is null" instead of "no records (₹0)" | 2/2 |
| D5 | Low | 35 | One Legacy answer gave the two districts' combined sanctioned count (234) instead of each district | 1/3 |

### Root causes (VERIFIED in code and by live trace; nothing changed)

**D1.** `app/pipeline/schemes/cm_elevate.py`, `_cm_elevate_dataset_choice` (line 284) checks
`_CMELEVATE_APPLICATIONS_ONLY` **first**. That matcher contains `_cme_join("elevate", ("applications", "application"))`
(line ~211), which was added so the dataset chip's own text ("CM Elevate applications …") pins the applications dataset. It
also matches a user's ordinary "CM-ELEVATE applications", so the Legacy-only words that follow ("sanctioned
applications", loan entity, FY) are never consulted, and no question is asked. The code's own comment at line ~175 says
"the applications dataset has no sanction at all". The SQL model then invents a meaning (sanctioned = `data_verified =
'Valid'`). Separately, the thread rule (`thread_scheme == "CM Elevate"` → "applications", line ~300) keeps an applications
chat on applications even when the new question uses Legacy-only words. Verified:
`_cm_elevate_dataset_choice("What percentage of CM-ELEVATE applications have been sanctioned?")` → `"applications"`
although `_CMELEVATELEGACY_ONLY_TERMS` matches it. The "measure not held" pause (`c01_followups.py`) knows that only Legacy
holds the measure but offers only applications measures as chips.

**D2.** The same family as Focus Legacy KI-369 (fixed **for Focus Legacy only** earlier today). The documented route is
`v_cm_elevate_disbursement JOIN curated.dim_geography ON geography_key WHERE UPPER(ac_name) = …`. The generator sometimes
filters the constituency name as a district instead, and nothing catches a resolved constituency that the final SQL does
not filter on `ac_name`. Today's Focus Legacy report (§8.6) predicted this risk for CM Elevate Legacy.

## 4. Decisions you need to make (not defects)

1. **Which dataset does a bare "CM-ELEVATE" + "applications" mean?** **DOCUMENTATION CONFLICT — NEEDS VERIFICATION**:
   - code (commit `e172414`, 20 Oct; comment "user decision 2026-10-19, replacing the 2026-10-12 default to Legacy"):
     application words → applications dataset; money words → ask;
   - `docs/SCHEMES.md` §"CM Elevate vs CM Elevate Legacy": money words → **Legacy without asking**; neither → CM Elevate;
   - `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, KI-273: the 12 Oct rule, "a bare CM-ELEVATE data question defaults to
     CM Elevate Legacy unless it uses applications-only words" (the example given is this sheet's TC-26);
   - `docs/DECISIONS.md`: no entry for the 19 Oct rule.

   This sheet passed 36/36 (300/300 sweep, 1,051 villages) on 12 Oct under the old rule. Either the sheet names "CM
   Elevate Legacy" (20/20 today), or the rule goes back to the 12 Oct default for this sheet's wording.

   **USER DECISION (2026-10-22, after this report): "Always ask".** A bare "CM-ELEVATE" data question always asks "CM
   Elevate (applications) or CM Elevate Legacy?", never a guess. This also covers "CM-ELEVATE applications" with no other
   words. Fixes: not yet ("no fixes yet"). When they are made, this decision replaces both the 12 Oct (KI-273) and the
   19 Oct rules and must be recorded in DECISIONS.md, SCHEMES.md, CURRENT_STATE.md and HANDOFF.md. Under it, TC-11, 12,
   26, 28, 31 and 33 would ask first and then answer from Legacy, and D1 disappears for bare-name questions.
2. **"Which schemes / each scheme" with no programme named** (TC-13, 18, 19, 25): in a fresh chat the bot answers across
   all government schemes. That is a fair reading of the words. If the client means CM-ELEVATE sub-schemes, the sheet should
   say "CM-ELEVATE schemes" (then the bot asks applications-or-Legacy and answers correctly).
3. **Inside one chat, a new question uses the latest FY (D-061, user addendum today, still uncommitted).** Asking the
   sheet in order in one chat, TC-14 onwards were answered **for FY 2025-26** ("137 sanctioned", "₹22.49 crore"), not all
   years. The answers say so, and every FY 2025-26 figure checked is correct (137 · ₹22.49 cr · per-scheme ₹12.50 / 8.40 /
   1.59 cr · Umling 5 records, ₹0.32 cr, 4 villages · EKH 38 / WGH 18). A tester expecting statewide all-years totals must
   say "across all financial years" or start a new chat. Also by D-061: once the chat has touched both CM Elevate datasets,
   an unnamed question asks "Which topic is this about — CM Elevate Legacy or CM Elevate?".

## 5. Behaviour to note

- **The bot asks before it answers** in a new chat: "which scheme?" (no scheme named), "applications or Legacy?",
  "which area?", "which financial year?", "top how many?". A sheet question often takes 1-3 taps. This is by design
  (D-053 / D-056).
- **Name collisions:** Umling (block and village), Mahendraganj / Jirang (constituency and block) draw a "which one?" chip
  question. That's correct, but it's an extra tap.
- **Response time:** median 5.6 s per turn, 90th percentile 12.7 s (834 turns; other sessions were running live tests on
  the same gateway at the time).
- **Test-tool note (not a bot defect):** my first literal run tapped "Focus Legacy" for "which scheme?" on TC-24, 27, 30
  and 32. Those 12 conversations were re-run with the right tap (3/3 each) and the bad ones are not in the CSV. The first
  one-chat run did not answer the new `topic-ambiguous` question and was likewise re-run.
- **Other scheme, seen in passing:** the cross-scheme table gave Focus Plus "applications" as 12,527 in one run and
  385,671 in another (different SQL filter). Not part of this sheet; worth a look in the cross-scheme suite.

## 6. Raw data vs database

| Level | Units | Differences |
|---|---|---|
| Rows | 2,823 | 0 missing, 0 extra; `id` = `source_row_id` and same `application_number` on every row |
| 29 fields | 2,823 × 29 | **3 kinds, all correct cleansing:** (1) 4 first-subsidy dates in the raw file have impossible years (**1014 / 1015**); the DB stores them blank (amounts identical). (2) Block "TURA MUNICIPAL BOARD-MUNICIPAL BOARD" (2 rows, ₹5.82 lakh) is stored "TURA MUNICIPAL BOARD". (3) 404 rows have no village in the raw file; the DB files them under "Unresolved / Not Yet Mapped (block known)" (46 block-level codes). They count in district, block and constituency totals but in no village |
| State / scheme / FY / lender / district / constituency / scheme×FY / district×scheme / district×FY: rows, sanctioned count, total, subsidy, loan disbursed | 263 units | **0** |
| Block (60) / village (1,098) | | Only the two label / unresolved items above |

**Data issue for the ingestion team (not the bot):** `v_cm_elevate_disbursement.year_note` carries **MGNREGA** caveats on
CM Elevate Legacy rows ("EMPLOYMENT FIGURES FOR THIS YEAR APPEAR TO BE A PARTIAL EXTRACT. Person-days fell 46.2%…" on all
2,291 FY 2024-25 rows; "women_employment_provided is zero…" on the 137 FY 2025-26 rows). The note belongs to MGNREGA's
year dimension. It did not show up in any answer here, but anything that surfaces `year_note` for this scheme would mislead.
Suggest a `docs/*_DB_Issues.md` note to `megh-ingestion`.

Statewide figures (raw = DB; bot correct whenever it reached Legacy):

| Measure | Value |
|---|---|
| Records / sanctioned / not sanctioned | 2,823 / 2,820 / 3 (sanction rate 99.89%) |
| Total disbursed (subsidy + loan) | ₹82.90 crore (subsidy ₹52.57 cr, loan ₹30.33 cr) |
| By FY | 2024-25: 2,291 records, ₹59.82 cr · 2025-26: 137, ₹22.49 cr · no FY (Sericulture): 395, ₹0.59 cr |
| By lender | Bank 1,733 (₹43.72 cr) · LIFCOM 689 (₹38.58 cr) · not recorded 401 (₹0.60 cr) |
| Most records | Piggery 1,353; West Garo Hills 493 |
| Most money | Agriculture Warehouse ₹22.62 cr; East Khasi Hills ₹22.60 cr |

## 7. Suggested fixes (NOT made — awaiting your go-ahead)

Following the project pattern (prompt rule → few-shot → **deterministic guard**):

1. **D1:** in `_cm_elevate_dataset_choice`, let Legacy-only terms (`_CMELEVATELEGACY_ONLY_TERMS`: sanctioned
   applications, loan entity, lender, LIFCOM, desanction) win over the "Elevate applications" phrase unless the text is the
   chip's own exact wording "CM Elevate applications". Do the same in the thread branch. The result would then be Legacy
   (or "ask"), never applications, for these questions. Add a guard: SQL on `v_cm_elevate` for a question with a
   sanction / loan / disbursement word goes back to repair or to the dataset pause. Make the measure-not-held pause offer a
   "CM Elevate Legacy" chip when Legacy holds the measure.
2. **D2:** reuse the Focus Legacy KI-369 guards for CM Elevate Legacy: a resolved constituency whose final SQL has no
   `ac_name` filter (or filters the name as `lgd_district`) goes back to repair, and the verifier's false "prohibited join"
   is discarded for the documented `geography_key` join. Then re-run TC-31/32 over all 55 constituencies.
3. **D3:** an overview / briefing question routes to knowledge, or the composer gets a briefing style: what the scheme is,
   subsidy %, loan, sectors, then headline figures.
4. **D4:** a 0-row / NULL sum answers "no records (₹0)" (deterministic, like `_cm_legacy_small_money_notes`).
5. **Decision 1** first: whichever rule you choose, record it in DECISIONS.md and align SCHEMES.md, CURRENT_STATE.md and
   HANDOFF.md.

## 8. How this was run

- Live, in-process, with the repo venv and the VPN; LangGraph pipeline; pauses answered as a chip tap.
- Code tested: HEAD `9726b86` plus the uncommitted working copy. Another session was editing the app during the run (code
  fingerprint changed between 12:49 and 13:17). Each run loads the code once at start, so each run is internally consistent.
  The sweep and literal runs used the 12:49 code; the one-chat re-run and the named-Legacy run used the 13:17 code.
- `tests/sheet_runs/cl_run.py` (sweep, unchanged). Scratch scripts (not in the repo): `cl_raw_vs_db.py` / `cl_raw_detail.py`
  (raw vs DB, read-only, counts and sums only, name columns never loaded), `cl_literal.py` (sheet wording; fresh / one-chat /
  named-Legacy modes), `cl_rerun_tap_legacy.py` (sweep re-run answering the dataset pause), `repro_chat.py` (root-cause
  replays).
- Not run: every CM Elevate Legacy village (`cl_all.py`, 1,051 villages). The sheet has no per-village use case beyond
  TC-34, which passed; on 12 Oct it was 1,051/1,051.
- Every conversation, with the question, pauses, the bot's answer, its SQL and the DB figure:
  `new_docs/CM_Elevate_Legacy_all_conversations_2026-10-22.csv` (562 rows; column `source` = which run).
