# MGNREGA Test Report (Excel ground truth) — 27 Oct 2026

**Scope:** the 30 use cases in `Test_Case_Results_MGNREGA (1).csv` (DATA-001 … DATA-030), run live through the chatbot
(LangGraph pipeline, real models, live `megh_db`), with every **expected figure taken from the two raw Excels**
(`Updated MNGREGA Expenditure WIth Year.xlsx`, `MGNREGA_Employment.xlsx`), not from the database.
Each case was asked in 3 rotating wordings and 6 year forms ("2024-25", "2024-2025", "FY 2024-25", "24-25", "FY25",
"financial year 2024-25"), across the hierarchy. A pause was answered the way a user taps a chip.
Harness: `tests/sheet_runs/mg_excel_run.py`. All 919 conversations: `new_docs/MGNREGA_Excel_run_conversations_2026-10-27.csv`.

## 1. Summary

| Check | Result |
|---|---|
| Excel vs DB: state, village, constituency figures (all years, all 12 measures) | **Identical** |
| Excel vs DB: block / district | 15 villages sit under another block in the DB (2 under another district) → a few block totals and the South West / West Garo Hills district totals differ. 17 answers matched the DB, not the Excel (scored as data difference) |
| Conversations | **919** (24 villages, 8 same-name villages, 12 districts, 55 blocks, 56 constituencies, 32 rankings, 120 hierarchy-sweep) |
| Right figure, no extra question | **763 / 919 (83.0%)** |
| Right figure after the bot asked "which scheme?" | +100 → **863 / 919 (93.9%)** |
| Real failures | **56** (5 defects, §3) + 4 fixed during the run (KI-431) |

Corrections to the raw score (759): 2 same-name villages with no expenditure record (TLUH, JARAIN) were answered
"no expenditure recorded" — correct; 2 "FY23" questions failed on KI-431 and pass after the fix.

## 2. By hierarchy level and logic

| Level | Result |
|---|---|
| State (9 measures + all years) | 10/10 |
| District | sheet cases 66/72 right figure; sweep 30/30 |
| Block | sheet cases 210/275 (incl. 17 data-difference); sweep 20/20 |
| Village (incl. same-name villages) | 314/320; sweep 30/30 |
| Assembly constituency | employment 100%-right figure; **expenditure 0/10** (KI-432) |
| Rankings (top district / block / village / women, 4 years × 2 wordings) | 32/32 |

Year forms: no failure is caused by the year form after KI-431 (the misses cluster by wording, not by year form).

## 3. Defects found

| KI | Defect | Cases | Example |
|---|---|---|---|
| KI-431 | "FY23" written as `year_key = 2023` → "couldn't build a working query" / KB answer | 4 | **FIXED 2026-10-27** |
| KI-432 | **Constituency expenditure** never answered; one retry gave the **statewide** figure as Amlarem's (106,669.85 lakh; correct 1,239.90) | 10/10 | `v_expenditure` has `ac_name` (title case), not `assembly_constituency_name`; the repair moved to a view with no AC column and dropped the filter |
| KI-433 | "100-day completion **rate** of households in X block" answers the household **count** as the rate | 10/18 | CHOKPOT FY 2025-26: "rate … is 720" (correct 15.33%) |
| KI-434 | Guardrail refuses data questions as "I can't do things on your behalf" | 9 | "Break down the spending in Mawber village for 2022-2023 by component" (8/8); "administrative spend in CHOKPOT block FY 2025-26" |
| KI-435 | "administrative **spend** in X block" → "no usable administrative-expenditure figure in any scheme" (a pause with no options); the sheet's "administrative **expenditure**" answers ₹0.00 lakh with the note | 17/18 | AMLAREM, BATABARI |
| KI-436 | "villages in X AC with MGNREGA employment" counts villages with zero employment | 10/19 | AMPATHI FY 2023-24: 120 (correct 114) |

## 4. For the user to decide: the bot asks "which scheme?"

100 conversations asked which scheme, then gave the right MGNREGA figure. All are wordings without "employment"
or "expenditure": "Total spending in …", "How much was spent in … block", "How many people got work", "households
given work", "women given work", "% of workers were women", "Show spending and employment". "Spending" is also held by
PMAY-G / Focus / CM Elevate, so asking is in line with the current design; "work / workers / given work" are MGNREGA
words only. Decide whether "work" wordings should go straight to MGNREGA.

## 5. Per use case

| TC | Right figure | Note |
|---|---|---|
| DATA-001 | 32/32 | incl. 8 same-name villages (asked which, then right) |
| DATA-002 | 12/12 | 4 asked scheme ("Total spending") |
| DATA-003 | 55/55 | 18 asked scheme ("How much was spent") |
| DATA-004 | 56/56 | 18 asked scheme ("people got work"); 1 KI-431 |
| DATA-005 | 24/24 | 8 asked scheme ("got work") |
| DATA-006 … 010, 012 | 24/24 each | |
| DATA-011 | 24/24 | 1 KI-431 |
| DATA-013 | 37/55 | KI-435 (17), KI-434 (1) |
| DATA-014 | 46/56 | KI-436 (10); 19 asked scheme |
| DATA-015, 018, 021 | 12/12 each | |
| DATA-016 | 55/55 | 19 asked scheme; 6 data difference |
| DATA-017 | 12/12 | 6 asked scheme |
| DATA-019 | 12/12 | 4 asked scheme |
| DATA-020 | 45/55 | KI-433 (10); 4 data difference |
| DATA-022 | 16/24 | KI-434 (8) |
| DATA-023, 028 | 24/24 each | |
| DATA-024 … 027 | 8/8 each | |
| DATA-029 | 55/55 | 7 data difference |
| DATA-030 | 12/12 | 4 asked scheme |
