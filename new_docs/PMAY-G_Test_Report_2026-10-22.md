# PMAY-G Use-Case Test Report — 22 Oct 2026

**Scope:** the 28 use cases in `raw_uc/PMAY-G.xlsx` (PMAY-OFF-001 … 028), run live through the chatbot
(LangGraph pipeline, real models, live `megh_db`). Every bot answer was checked against the database, and the database
was checked row by row against the raw file `raw_uc/PMAY_FullyMapped_with_dates.xlsx`.
No code, data or docs were changed.

## 1. Summary

| Check | Result |
|---|---|
| Raw Excel vs DB: rows | **Match.** 171,107 rows in both, joined 1:1 on the house id (no row missing on either side) |
| Raw Excel vs DB: every field (village / block / district, sanction no., sanction date, sanctioned, released, instalments, house status, allotted to, mapping status) | **100% match.** 0 differences on any field |
| Raw Excel vs DB: totals at state, district (12), block (56), village (5,120), district × year (83), sanction date (1,122), unique sanction numbers per village | **100% match** |
| Bot vs DB: full sweep (every district, every block, 24 villages, comparisons, dates) | **654 / 678 conversations correct (96.5%)** |
| Use cases fully working | **25 of 28** |
| Use cases with a real failure | **3**: PMAY-OFF-019 (0/12), PMAY-OFF-016 (9/12), PMAY-OFF-012 (47/56). All 3 reproduce exactly on re-run |
| Testers' remarks, re-tested (80 extra questions) | **70 / 76** single questions; follow-up chats **1 of 4** fully correct |

**What was broken on 10 / 14 Sep and now works:** "till date" / "so far" / "in total" / "for all financial years"
on village questions (24/24), village names (every village answered at the right level), status categories no longer
repeated (12/12 districts), every district answered for completion % and release % (24/24), year-wise district
questions in every year format (2023-24, FY 2023-24, 2023-2024, 23-24, "financial year 2023-24": 30/30), date-wise
sanctions in 4 date formats (12/12), village / block / district comparisons (58/58).

## 2. Result per use case

Sweep = conversations correct against `megh_db`. The questions name no year, so the bot asks which year; the test
answered the way a user would, by tapping "All financial years combined" (see §4, point 1).

| TC | Use case | 14 Sep (tester) | Today | Notes |
|---|---|---|---|---|
| 001 | Village beneficiary count | Passed | **Pass** 24/24 | "till date" no longer asks the year ✔ |
| 002 | Village sanctioned amount | Passed | **Pass** 24/24 | |
| 003 | Village released amount | Passed | **Pass** 24/24 | typo "sactioned" understood ✔ |
| 004 | Village houses completed | Passed | **Pass** 24/24 | |
| 005 | Village incomplete houses | Passed | **Pass** 24/24 | |
| 006 | Village status breakdown | Passed | **Pass** 24/24 | No category repeated ✔ |
| 007 | Village amount still to release | Passed | **Pass** 24/24 | |
| 008 | Village full release | Passed | **Pass** 24/24 | |
| 009 | Village partial release | Passed | **Pass** 24/24 | |
| 010 | Village nothing released | Passed | **Pass** 24/24 | |
| 011 | Block beneficiary count | Passed | **Pass** 56/56 | Block names also used as village names (e.g. Amlarem) → bot asks "block or village" ✔ |
| 012 | Block financial summary | Passed* | **Fail (9 blocks)** 47/56 | See defect 2. With the word "block" 28/28; bare name 19/28 |
| 013 | Block houses completed | Passed | **Pass** 56/56 | |
| 014 | Block status breakdown | Passed | **Pass** 56/56 | |
| 015 | District beneficiary count | Passed* | **Pass** 12/12 | |
| 016 | District financial summary | Passed | **Fail (3 districts)** 9/12 | See defect 1 |
| 017 | District houses completed | Passed | **Pass** 12/12 | |
| 018 | District status breakdown | Passed | **Pass** 12/12 | |
| 019 | District overall performance | Passed | **Fail** 0/12 | See defect 1. Every district answered with the status breakdown only |
| 020 | Completion % | Passed | **Pass** 12/12 | |
| 021 | Release % | Passed | **Pass** 12/12 | |
| 022 | Village comparison | Passed | **Pass** 24/24 | Both counts plus the right winner |
| 023 | Block comparison | Passed | **Pass** 28/28 | |
| 024 | District comparison | Passed | **Pass** 6/6 | All 4 measures + difference |
| 025 | Year-wise district | Passed | **Pass** 12/12 (+18/18 year formats) | |
| 026 | Unique sanction numbers | Passed | **Pass** 24/24 | |
| 027 | Houses sanctioned on a date | Passed | **Pass** 12/12 | 19-06-2023, 2023-06-19, 19 June 2023, June 19, 2023 |
| 028 | Full release, house not complete | Passed | **Pass** 24/24 | |

\* 012 on 14 Sep: "it is taking financial year data but in excel it is different". 015: "where sanctioned amount is 0
are not considered as beneficiaries" (still the case: the 126 zero-sanction rows are excluded, see §5).

## 3. Defects found (bot)

| # | Severity | Use case | Problem | Reproduces |
|---|---|---|---|---|
| 1 | **High** | 019, 016, also 012 | "Give me the overall PMAY performance of East Garo Hills" / "…financial summary for Ri Bhoi": the bot rewrites it to **"PMAY-G house status in East Garo Hills"**, which is also the text on the year chip. Result: 019 answers only the status breakdown (no sanctioned / released amounts) for all 12 districts; 016 does the same for 3 districts (Eastern West Khasi Hills, South West Garo Hills, South West Khasi Hills). The same rewrite drops "till date" and "across all financial years", so the bot still asks the year (6/6 blocks, 2/2 districts probed) | 2 runs, identical |
| 2 | **High** | 012 | "Give me the PMAY financial summary for Amlarem" (a block, no word "block"): the bot asks the year first, never asks "block or village", and answers for **Amlarem village**, even though the chip it sent said "Amlarem block". Example: Amlarem block sanctioned ₹30.89 crore; the bot gave the village's ₹42.90 lakh. Affected: AMLAREM, DEMDEMA, LASKEIN, MAWKYNREW, MAWSHYNRUT, RAMBRAI, RERAPARA, TIKRIKILLA, ZIKZAK | 2 runs, identical |
| 3 | **High** | Follow-ups | One chat: "How many PMAY beneficiaries are there in Badimbari?" → "How many of those houses are completed?" ✔ → **"What about Rongara block?"** → the bot answers for Badimbari village again (rewrite: "…in Badimbari … in the Rongara block"); the district follow-up and "released there" after it also stay on the village. Moving from a village to its own block or district fails; it worked once (Phlangkynshi Mihngi) | 3 of 4 chats, 2 runs |

**Cause of defect 1 (INFERRED from code, not changed):** `app/pipeline/common/c15_conversation_meta.py`
(`_C15_OVERVIEW`, `_C15_OVERVIEW_TEMPLATES`, `_overview_question`). The words "summary" and "performance" make a
question a "place overview". The PMAY-G overview template is "PMAY-G house status in {place}{year}", and only an explicit
FY is carried over, so "till date" / "all years" is lost. "Financial summary" is not recognised as a measure, so the
template replaces the question. Defect 2 is the same path: the template's "Amlarem block" text is then resolved to the
village.

## 4. Behaviour to note (not counted as failures)

1. **The bot asks the year when a question names none.** All 654 sweep questions without a year got "which financial
   year?" first. This follows the current context rule (new chat → ask scheme, district, year; D-056). The testers
   wrote on 10 Sep that "the bot shouldn't ask financial year question" for PMAY-G. Adding "till date", "so far",
   "in total" or "all years" skips the question (except for defect 1).
2. **"Beneficiaries" = houses.** The bot counts houses (one row per house): 170,981 statewide. The raw file has 368
   repeated registration numbers, so a count of distinct registration numbers would be 170,613. Neither is wrong, but
   the testers should know which one the bot gives.
3. Response time: median 0.95 s, 90th percentile 2.7 s per answer.

## 5. Raw data vs database

| Level | Units compared | Differences |
|---|---|---|
| Rows (raw `id` = DB `source_house_id`) | 171,107 | 0 missing, 0 extra |
| Field by field (13 fields) | 171,107 × 13 | **0** |
| State / district / block / village totals (houses, sanctioned, released, completed) | 1 / 12 / 56 / 5,120 | **0** |
| District × financial year | 83 | **0** |
| Houses per sanction date | 1,122 dates | **0** |
| Unique sanction numbers per village | 5,120 | **0** |
| DB financial year vs sanction date (April–March) | 171,107 | **0** |

**Placeholders:** 126 raw rows have sanctioned amount 0 and no sanction date (73 "Existing site (Old House)", 40
"Proposed Site", 12 blank, 1 "Plinth"). The DB marks exactly these 126 as placeholders and the bot leaves them out.
**Released amount blank:** 336 houses (nothing released yet); raw and DB both treat them as 0.

Statewide figures (raw = DB = bot):

| Measure | Value |
|---|---|
| Houses / beneficiaries | 170,981 |
| Sanctioned | ₹2,222.75 crore |
| Released | ₹2,185.26 crore |
| Completed / Roof Cast / Plinth / House Sanctioned | 129,941 / 25,000 / 13,983 / 2,057 (76.0% completed) |
| Fully / partly / not released | 152,823 / 17,822 / 336 |

| FY | Houses | Sanctioned (₹ crore) | Released (₹ crore) | Completed |
|---|---|---|---|---|
| 2017-18 | 15,513 | 201.67 | 201.46 | 15,456 |
| 2018-19 | 3,535 | 45.96 | 45.89 | 3,524 |
| 2019-20 | 9,952 | 129.38 | 129.03 | 9,702 |
| 2020-21 | 24,215 | 314.80 | 309.18 | 20,664 |
| 2021-22 | 3,014 | 39.18 | 37.87 | 2,371 |
| 2022-23 | 8,225 | 106.93 | 105.37 | 6,248 |
| 2023-24 | 106,527 | 1,384.85 | 1,356.45 | 71,976 |

The raw file holds personal data (beneficiary and parent names); it was only counted and summed, never copied.

## 6. How the test was run

- **Sweep:** the repo's existing harness `tests/sheet_runs/pm_run.py`, unmodified, output kept outside the repo. 678
  conversations: 24 villages (2 per district, names in UPPER and Title case) × the 12 village cases, all 56 blocks × 4
  block cases (named alternately "X block" and "X"), all 12 districts × 7 district cases, plus 025 for every district,
  24 village pairs, 28 block pairs, 6 district pairs and 12 sanction dates. Pauses were answered as a user would tap the chip.
- **Retest:** 012, 016 and 019 run a second time (80 conversations): identical results.
- **Tester remarks:** 76 extra questions (till date / so far / in total / all years, duplicate categories, statewide,
  year formats) and 4 five-step follow-up chats, plus 9 one-off probes.
- **Expected values:** SQL on `curated.v_pmay` (`NOT is_placeholder`, released NULL = 0).
- **Raw vs DB:** pandas on the Excel file vs a full dump of `v_pmay` (personal-name columns dropped on load).

Every conversation (question, bot pauses, chip sent, answer, expected value, SQL, pass/fail), 863 rows:
[PMAY-G_all_conversations_2026-10-22.csv](PMAY-G_all_conversations_2026-10-22.csv) (same folder).

## 7. Update — fixes applied and re-tested (22 Oct 2026, ~00:50)

On instruction ("126 rows sanctioned amount 0 is also considered as beneficiaries and fix all the failed use
cases"), the following was changed. Details: `docs/DECISIONS.md` D-060, `docs/KNOWN_ISSUES.md` KI-127, KI-356..358.

| # | Change | Where |
|---|---|---|
| 1 | **The 126 zero-sanction records are beneficiaries.** Statewide beneficiaries are now **171,107** (was 170,981). The answer says how many have ₹0 sanctioned, e.g. Ri Bhoi "17,565 (including 40 registered with a sanctioned amount of ₹0 and no house sanctioned yet)". They are included in "not completed", "not received any amount", the status breakdown (Existing site(Old House), Proposed Site, no status) and the completion % denominator. They are **not** counted as "received the full sanctioned amount" (₹0 of ₹0 is not a full release). Money, release %, sanction numbers and every year / date figure are unchanged (these records have no year or date). "Houses sanctioned" (cross-scheme comparison, home-page card) still excludes them | fixed PMAY-G answers + a guard on model-written SQL + the prompt rule |
| 2 | **Defect 1 + 2 fixed:** "financial summary" / "overall performance" are no longer rewritten to "PMAY-G house status". They answer their own figures, "till date" / "all years" is honoured, and a bare block name (Amlarem) is asked "block or village?" | `c15_conversation_meta.py`, `pmay_g.py` |
| 3 | **Defect 3 fixed:** a follow-up naming a block or district ("What about Rongara block?", "And South Garo Hills district?") replaces the previous village; also "block?" with a question mark is read as the word "block" | `c01_followups.py` |

### Re-test on the fixed code

| Check | Before | After |
|---|---|---|
| Full sweep, 28 use cases | 654 / 678 | **678 / 678** |
| PMAY-OFF-012 / 016 / 019 | 47/56, 9/12, 0/12 | **56/56, 12/12, 12/12** |
| Tester-remark questions | 70 / 76 | **76 / 76** |
| Follow-up chats (village → block → district → released) | 1 of 4 (11/20 steps) | **4 of 4 (20/20 steps)**, two runs |
| Use cases fully working | 25 of 28 | **28 of 28** |
| Full pytest | — | **3,300 passed, 0 failed** (3 skipped); 14/14 plain scripts |
| Live conversation harness (HTTP, stream, caches off, all scenarios) | — | **102/102 scenarios, 313/313 turns** |

The expected values in this re-test count all rows (the harness `tests/sheet_runs/pm_run.py` was updated to D-060).
Questions 012 / 016 / 019 are now answered directly over all years (the answer names the period) instead of asking the
year first; other questions with no year still ask it (context rule D-056).

Every conversation of the re-test (783 rows):
[PMAY-G_all_conversations_after_fix_2026-10-22.csv](PMAY-G_all_conversations_after_fix_2026-10-22.csv).
