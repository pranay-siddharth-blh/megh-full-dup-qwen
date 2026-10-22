# MGNREGA Use-Case Test Report — 21 Oct 2026

**Scope:** the 30 use cases in `Test_Case_Results_MGNREGA (1).csv` (DATA-001 … DATA-030), run live through the chatbot
(LangGraph pipeline, real models, live `megh_db`). Every bot answer was checked against the database, and the database
was checked against the two raw files (`MGNREGA_Employment.xlsx`, `Updated MNGREGA Expenditure WIth Year.xlsx`).
No code, data or docs were changed.

## 1. Summary

| Check | Result |
|---|---|
| Raw Excel vs DB: row counts | **Match**: 18,818 expenditure rows, 26,375 employment rows |
| Raw Excel vs DB: figures at state, village and constituency level | **100% match** (every year, every measure) |
| Raw Excel vs DB: figures at block and district level | **Mostly match.** 16 villages sit under a different block in the DB (known issue, see §4) |
| Bot vs DB: full sweep (every district, block, constituency, year, plus 48 villages) | **755 / 783 conversations correct (96.4%)** |
| Bot vs DB: the testers' own reported problems, re-tested | **29 / 32 pass.** 2 of the 3 "fails" are by design (the bot asks for the year) |
| Use cases fully working | **23 of 30** |
| Use cases with correct figures but a wording / year-reading defect | **5**: DATA-007, DATA-022, DATA-023, DATA-028 (wrong scope line), DATA-027 ("FY24") |
| Use cases with a real failure | **2**: DATA-014 (2 constituencies), DATA-016 (WAPUNG block, wrong number) |

Since the testers' 10 Sep round (16 Failed), every issue they reported now works: village names, same-name villages,
block-vs-village names, GAMBEGRE constituency, years typed as "25-26", "till date", administrative expenditure,
0.2 L values, and "all years combined".

## 2. Result per use case

Sweep = conversations correct against megh_db. Retests are 3 repeated runs of each failure.

| TC | Use case | 10 Sep (tester) | Today | Notes |
|---|---|---|---|---|
| DATA-001 | Village + year expenditure | Failed | **Pass** 32/32 | Same-name villages (AKINPARA, AMONGGRE) → bot asks which; with the district named it gives the **village** figure (not the district); "25-26" understood |
| DATA-002 | District + year expenditure | Passed | **Pass** 12/12 | |
| DATA-003 | Block + year expenditure | Failed | **Pass** 54/55 | Block that is also a village (RAMBRAI, UMSNING) → bot asks which. 1 one-off miss (BAJENGDOBA said "no data"; passed 3/3 on retest) |
| DATA-004 | Constituency + year persons | Failed | **Pass** 56/56 | GAMBEGRE + "constituency" = 13,195 ✔; bare "Gambegre" asks constituency / block / village. Minor: picking the constituency chip triggers a 2nd question (whole or part) |
| DATA-005 | Village households | Failed | **Pass** 24/24 | "till date" = all years ✔; 18TH MILE UMDOH = 317 under both spellings ✔ |
| DATA-006 | Village person-days | Failed | **Pass** 24/24 | "till date" ✔ |
| DATA-007 | Village job cards | Passed | **Wording defect** | Figure is the FY 2025-26 job-card total (by design: job cards are cumulative, KI-293) and matches the DB, but **all 24 answers say "across all financial years"** |
| DATA-008 | Village women | Failed | **Pass** 24/24 | |
| DATA-009 | Village 100-day households | Failed | **Pass** 24/24 | |
| DATA-010 | Village unskilled wages | Failed | **Pass** 24/24 | "till date" ✔; no longer refused as out of scope |
| DATA-011 | Village materials | Passed | **Pass** 24/24 | |
| DATA-012 | Village semi-skilled wages | Failed | **Pass** 24/24 | "for all financial years" ✔ |
| DATA-013 | Block admin expenditure | Failed | **Pass** 55/55 | AMLAREM (tester's exact wording) no longer refused; answers ₹0.00 lakh and explains that the column is empty at source |
| DATA-014 | Villages in a constituency | Passed | **Fail (2 ACs)** 53/56 | **MAWKYNREW and SUTNGA-SAIPUNG (FY 2025-26) fail 3/3**: "couldn't build a working query". PYNURSLA miss was one-off (3/3 on retest) |
| DATA-015 | District person-days | Passed | **Pass** 12/12 | |
| DATA-016 | Block households | Passed* | **Fail (1 block)** 53/55 | **WAPUNG FY 2023-24 answers "46 households"; correct is 9,166** (46 is the number of villages), 3/3. Saipung miss was one-off. "All years combined" gives one total ✔ |
| DATA-017 | District women | Failed | **Pass** 12/12 | "23-24" ✔ |
| DATA-018 | District job cards | Passed | **Pass** 12/12 | |
| DATA-019 | % women, district | Failed | **Pass** 12/12 | With no year the bot asks (by design, D-053); the "all years with women data" chip → 48.63% ✔ |
| DATA-020 | % 100-day, block | Failed | **Pass** 55/55 | |
| DATA-021 | Person-days per household | Passed | **Pass** 12/12 | |
| DATA-022 | Expenditure breakdown, village | Failed | **Pass + wording** 24/24 | 0.20 L now shown (not 0) ✔. Answers end "This is the statewide figure for all of Meghalaya" on a village answer |
| DATA-023 | Wages vs materials | Passed | **Pass + wording** 24/24 | Same "statewide" line |
| DATA-024 | Top district, expenditure | Failed | **Pass** 4/4 | With no year the bot asks (by design); the "all years" chip → West Garo Hills 792.42 crore ✔ |
| DATA-025 | Top block, person-days | Failed | **Pass** 4/4 | "24-25" ✔ |
| DATA-026 | Top village, person-days | Passed | **Pass** 4/4 | |
| DATA-027 | Top district, women | Failed | **Pass, 1 defect** 4/4 | "2023-2024", "FY 2023-24" ✔. **"FY24" is read as FY 2024-25** (the Indian convention is FY 2023-24), while "FY 2024" makes the bot ask |
| DATA-028 | Expenditure + person-days, village | Failed | **Pass + wording** 24/24 | "24-25" ✔; same "statewide" line |
| DATA-029 | Block expenditure + person-days | Passed | **Pass** 55/55 | |
| DATA-030 | District expenditure + employment | Passed | **Pass** 12/12 | |

\* The tester's DATA-016 "Passed" on 10 Sep was marked "not a blocker".

## 3. Defects found (bot)

| # | Severity | Use case | Problem | Reproduces |
|---|---|---|---|---|
| 1 | **High** | DATA-016 | "How many households received employment in WAPUNG during 23-24?" (block chip) → **"46 households"**. The SQL counted villages; the answer calls them households. Correct: 9,166. The number-faithfulness check did not catch the relabelling. | 3/3 |
| 2 | **High** | DATA-014 | Village lists for **MAWKYNREW** and **SUTNGA-SAIPUNG** constituencies (FY 2025-26) → "couldn't build a working query". The first SQL is rejected by the placeholder-row guard; every repair then uses a non-existent column `f.lgd_village_name`. | 3/3 |
| 3 | Medium | DATA-007 | Job-card answers say "**across all financial years**" but the figure is FY 2025-26 only. The number is right by design (KI-293); the label is wrong. | 24/24 |
| 4 | Medium | DATA-027 (any) | "**FY24**" is silently read as FY 2024-25; government usage is FY 2023-24. "FY 2024" asks for clarification. | 1/1 |
| 5 | Low | DATA-022/023/028, some DATA-008 | Village answers end with "**This is the statewide figure for all of Meghalaya.**" The number is the village's; the scope sentence is wrong. | 74 answers |
| 6 | Low | DATA-003/014/016 | One-off SQL slips (~1 in 4 for these few places): BAJENGDOBA filtered on `entity_type='Block'` → "no data"; Saipung counted villages. All passed on retest. | intermittent |
| 7 | Low | DATA-004 | After choosing the GAMBEGRE constituency chip, a second question asks "whole constituency or one part?" The answer is correct once "whole" is chosen. | 1/1 |

## 4. Raw data vs database

| Level | Expenditure | Employment |
|---|---|---|
| State, per year | Match (4/4) | Match (4/4) |
| District, per year | Match (48/48) | 8 of 48 differ: **West Garo Hills / South West Garo Hills** (GENAPARA) |
| Block, per year | 22 of 220 differ in total expenditure | 26 of 224 differ in households |
| Village, per year | Match (18,637/18,637) | Match (24,306/24,306) |
| Assembly constituency, per year | — | Match (222/222) |

**Why blocks and districts differ:** the DB places 16 villages (4 expenditure, 12 employment) under the current LGD
block, while the raw file uses the "shifted-village" block. Affected blocks: CHOKPOT, SIJU, NONGSTOIN, RAMBRAI,
UMSNING, MAWHATI, BATABARI, SELSELLA, PURAKHASIA, DALU, ZIKZAK, SHALLANG, MAWSHYNRUT. One village (GENAPARA, 274268) also
moves district. This is already reported to the ingestion team (`docs/MGNREGA_DB_Issues.md`, Issue 1 / 1b) and is
still open. **Impact:** for these blocks and the two districts, the bot's figure matches the DB but not a pivot of the
raw Excel file.

Statewide yearly totals (identical in raw and DB):

| FY | Total expenditure (lakh) | Person-days |
|---|---|---|
| 2022-23 | 88,629.40 | 25,596,237 |
| 2023-24 | 75,961.36 | 27,264,054 |
| 2024-25 | 1,06,669.85 | 14,667,872 |
| 2025-26 | 91,605.96 | 23,387,018 |

**Source-data limitations (not bot defects):**
- Administrative expenditure is empty at source: only 1 of 18,818 rows is non-zero (₹0.90 lakh, DEMDEMA). The bot says so.
- Women employment is not recorded for FY 2025-26 (0 in the raw file). The bot says so and leaves the year out of percentages.
- Some villages have two rows for the same year (e.g. UMDOHKHA 2023-24: 42 + 122). Raw and DB both sum them.
- Village names vary in the raw file (e.g. "18TH MILE UMDOH" vs LGD "UMDOH 18TH MILE"). The bot understands both.

## 5. How the test was run

- Full sweep: the repo's existing harness `tests/sheet_runs/mg_run.py`, unmodified, with output sent outside the repo.
  783 conversations: every district (12), every block (55), every assembly constituency (56), 48 villages (2 per district,
  plus 8 same-name villages) and all four FYs, with year formats varied (2023-24, 2023-2024, FY 2023-24, 23-24).
  When the bot asked a question, it was answered the way a user would tap the chip.
- Tester scenarios: 32 questions built from the remarks in the CSV, plus 5 follow-ups and 3× retests of every failure.
- Expected values: computed by SQL directly on `curated.v_expenditure` / `curated.v_employment`.
- Raw vs DB: pandas aggregation of both Excel files, compared with a full dump of the two DB views.

Detailed results (every conversation, question, bot answer, expected value, SQL):
[MGNREGA_all_conversations_2026-10-21.csv](MGNREGA_all_conversations_2026-10-21.csv) (same folder).

## 6. Update — after the job-card year fix (21 Oct 2026, afternoon)

Fix: D-057 / KI-336 (`docs/DECISIONS.md`, `docs/KNOWN_ISSUES.md`). The year asked is the year answered:
- job cards take the year asked, else the previous turn's year, else the bot asks; all years = one figure per year
  (job cards are a running total, so years are never added);
- the composer and the closing line state the year the SQL actually read;
- a village answer is no longer labelled "the statewide figure for all of Meghalaya".

Re-run of the same full sweep on the fixed code:

| Check | Before | After |
|---|---|---|
| All conversations correct | 755 / 783 | **775 / 783** |
| DATA-007 job cards | 8 / 24 (all said "across all financial years") | **24 / 24** |
| Local answers labelled "statewide" | 74 | **0** |
| Full pytest suite | — | 3,199 passed, 0 failed |
| Live job-card checks (year pause, chips, context year, all years, ranking) | — | 11 / 11 |

Still open (not changed by this fix): defect #1 DATA-016 households answered as a village count (WAPUNG, AMLAREM,
MAWRYNGKNENG blocks); defect #2 DATA-014 intermittent "couldn't build a working query" (moves between constituencies
on re-run, e.g. MAWKYNREW now passes 2/2, MAWRYNGKNENG fails 2/2); defect #4 "FY24" read as FY 2024-25.

## 7. Update — DATA-014 fixed (21 Oct 2026, late afternoon)

Defect #2 ("couldn't build a working query" for village lists in some constituencies) is fixed — KI-337.
Cause: the first query was right apart from the "Unresolved" placeholder filter; when the bot asked the model to add
it, the model switched to the raw table `fact_mgnrega_employment`, which has no village columns, and repeated that
mistake on every retry. Now the filter is added in code (no retry needed), and any MGNREGA query that reads the raw
table for village / block / district columns is pointed back to its view.

| Check | Before | After |
|---|---|---|
| DATA-014, all 56 constituencies | 51–53 / 56 (different failures each run) | **56 / 56, two runs in a row** |
| Full pytest suite | 3,199 passed | **3,205 passed, 0 failed** |

Still open: defect #1 DATA-016 households answered as a village count; defect #4 "FY24" read as FY 2024-25.

## 8. Update — DATA-016 fixed (21 Oct 2026, ~16:00)

Defect #1 (households answered wrongly for some blocks) is fixed — KI-338. Two causes, both now corrected in code:
1. For "How many households received employment in <block>?" the SQL model sometimes counted the **villages** that
   had employment (AMLAREM: 79) instead of adding up households (6,917). The query is now rewritten to the household
   (or person) total whenever the question asks for households / persons and not villages.
2. After choosing the block option, the model sometimes added `entity_type = 'Block'`. In the MGNREGA data every row
   is a village record, so that filter matched nothing and the bot said "the data doesn't cover it". That filter is
   now removed automatically (this also fixes the one-off BAJENGDOBA "no data" in DATA-003).

| Check | Before | After |
|---|---|---|
| DATA-016, all 55 blocks | 52–53 / 55 (wrong numbers / "no data") | **53 / 55, two runs** — every previously wrong block now correct |
| DATA-004 / DATA-014 (unaffected check) | 56 / 56 | 56 / 56 |
| Full pytest suite | 3,205 passed | 3,209 passed, 0 failed |

**New issue found while testing (KI-339, not caused by these fixes):** since about 16:00, a bare block name such as
"DALU", "WAPUNG" or "Ri Muliang" makes the bot ask "which village?" offering only look-alike villages, with no option
for the block itself. It comes from in-progress changes to the place-name resolver by a parallel session. It accounts
for the 2 remaining DATA-016 misses and 4 DATA-003 misses (DATA-003 51/55 in this run).

Still open: "FY24" read as FY 2024-25.

## 9. Final status (21 Oct 2026, evening — full re-run on the current code)

**770 of 783 conversations correct; 13 failing.** All 13 have one cause — KI-339: a bare block name is read as a
look-alike village (or the bot offers only look-alike villages), from the parallel session's in-progress resolver
changes. No failure remains from the defects found this morning.

| Block asked | Use cases failing |
|---|---|
| WAPUNG | DATA-003, DATA-013, DATA-016, DATA-029 |
| RI MULIANG | DATA-013, DATA-016, DATA-020 |
| JIRANG | DATA-003, DATA-013 |
| MAWSYNRAM | DATA-003, DATA-013 |
| DALU | DATA-003 |
| THADLASKEIN | DATA-029 |

Use cases 100% correct: 25 of 30. Tester-reported scenarios: 29 of 32 — two are by design (with no year the bot asks
which year, and the "all years" chip then gives the right figure: DATA-019, DATA-024) and one is open ("FY24" read as
FY 2024-25).

| Run | Correct | Failing |
|---|---|---|
| Morning (before fixes) | 755 / 783 | 28 |
| Evening (after fixes) | **770 / 783** | **13** (all KI-339) |

## 10. Re-test on the final code — every metric at every level (21 Oct 2026, night)

Run after the place-hierarchy fixes (D-058 / D-059, KI-339..351). No app code changed in this round.
Detailed results (1,113 conversations: question, pauses, answer, expected value, SQL):
[MGNREGA_all_metrics_all_levels_2026-10-21.csv](MGNREGA_all_metrics_all_levels_2026-10-21.csv).

### 10.1 Summary

| Check | Result |
|---|---|
| The 30 use cases (same 783-conversation sweep as §5) | **782 / 783** (was 770 / 783). The 13 block-name failures (KI-339) are gone |
| Every metric × every level × every year (new matrix, below) | **270 / 270** |
| Rankings: every metric × district / block / village / constituency | **35 / 42**: 4 constituency rankings, 3 admin rankings |
| Raw Excel vs DB, all 12 metrics, every level, every year | Same as §4: exact at state, constituency and village level; block / district differences = the 16 shifted villages (ingestion issue, still open) |

### 10.2 Metric × level × year (direct figures)

Each cell = 4 FYs (year written as 2023-24 / 2023-2024 / FY 2023-24 / 23-24) + all years ("till date",
"across all financial years", …). Places rotate, so 12 districts, 56 blocks, 56 constituencies and 40 villages are
covered. Expected value = SQL on `curated.v_expenditure` / `curated.v_employment`.

| Metric | State | District | Block | Constituency | Village |
|---|---|---|---|---|---|
| Total expenditure | 5/5 | 5/5 | 5/5 | not in data | 5/5 |
| Unskilled wages | 5/5 | 5/5 | 5/5 | not in data | 5/5 |
| Semi-skilled wages | 5/5 | 5/5 | 5/5 | not in data | 5/5 |
| Material | 5/5 | 5/5 | 5/5 | not in data | 5/5 |
| Tax | 5/5 | 5/5 | 5/5 | not in data | 5/5 |
| Administrative | 5/5 | 5/5 | 5/5 | not in data | 5/5 |
| Households employed | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Persons employed | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Person-days | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Households completed 100 days | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Job cards (running total: all years = one figure per year) | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |
| Women employment (FY 2025-26 not recorded at source) | 5/5 | 5/5 | 5/5 | 5/5 | 5/5 |

"Persons employed" with no scheme named makes the bot ask which scheme (CM Elevate also counts persons); after
MGNREGA is chosen the figure is right 25/25. This follows the new-chat rule (scheme → district → year) and is not
counted as a defect.

### 10.3 Defects found (each re-tested 3×)

| # | Severity | Question | What happens | Reproduces |
|---|---|---|---|---|
| A | **High** | "Which assembly constituency had the highest persons employed / women employment during 2022-23?" | 1,240 employment rows have no constituency (360 in FY 2022-23). The SQL groups by constituency without excluding them, so the blank group "wins": persons → "No assembly constituency had persons employed … 28,823"; women → "**15,657 … statewide**" (the real statewide figure is 3,09,225; the right answer is SONGSAK 27,291 / 13,651). KI-352 | 3/3 each |
| A2 | High | "Which assembly constituency had the highest households employed during **25-26**?" | "25-26" is read as a constituency name ("not a known assembly constituency"), or MAHENDRAGANJ is named but labelled "all of Meghalaya (statewide)". Right answer: MAHENDRAGANJ 13,681. Person-days, job-card and 100-day rankings by constituency work. KI-352 | 3/3 |
| B | **High** | "What was the total expenditure in Kharkutta constituency during 2024-25?" | Expenditure data has no constituency. Answer is "couldn't build a working query" (8 of 9 runs). **Once it gave ₹1,066.70 crore, the statewide total, labelled as Kharkutta.** It should say expenditure isn't recorded by constituency (and offer the district / block). KI-353 | 1/9 wrong number, 8/9 unhelpful |
| C | Medium | DATA-027 "Which district had the highest women employment during 2022-2023?" | Once in 4 + 3 runs: SQL took the single largest village row (`MAX`, no `GROUP BY`), answered "the recorded total is 1,034 person-days … statewide". Right: East Khasi Hills 50,844. KI-354 | 1/7 |
| D | Low | "Which district had the highest administrative expenditure during 2023-24?" | Gives the statewide total (₹0.90 lakh) with the "empty at source" note, but doesn't name the place (West Garo Hills, DEMDEMA, the only non-zero row). Block / village in other years: all zero, so no real ranking exists. KI-355 | 3/3 |

Not re-tested in this round: "FY24" read as FY 2024-25 (§1 defect #4, still open).

### 10.4 How to re-run

```
.venv/Scripts/python.exe tests/sheet_runs/mg_run.py       # the 30 use cases (MG_OUT=<file> to write elsewhere)
.venv/Scripts/python.exe tests/sheet_runs/mg_matrix.py <out.json>   # metric x level x year + rankings
.venv/Scripts/python.exe tests/sheet_runs/mg_score.py <results.json>
```
Both need the VPN and run in-process (no server; the :8401 rate limit is not involved). About 45 minutes together at
concurrency 4 + 3.
