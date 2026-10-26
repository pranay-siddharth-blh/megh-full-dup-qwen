# Focus Plus Use-Case Test Report — 22 Oct 2026

**Scope:** the 29 use cases in `raw_uc/Focus+ Test Case Observation.xlsx` (FOCUS-001 … 029), run live through the
chatbot (LangGraph pipeline, real models, live `megh_db`), at every level: state, all 12 districts, all 50 blocks,
**every one of the 3,513 villages**, both financial years in four formats, both batches, all four tranches. Every bot
answer was checked against the database, and the database was checked row by row against the raw file
`raw_uc/Focus Plus Master.csv`. **No code, data or docs of the app were changed** (report only).

The raw file holds names, phone numbers and EPIC ids. It was only counted and summed; no row of it appears here or in
the CSV.

## 1. Summary

| Check | Result |
|---|---|
| Raw CSV vs DB: rows | **Match.** 385,671 rows in both, joined 1:1 on the raw `id` (= DB `source_row_id`); none missing on either side |
| Raw CSV vs DB: every field (batch, tranche, FY, amount, gender, occupation, bank, focus status, verification status, member id, pincode, district, block, serial no.) | **100% match.** 0 differences on any field |
| Raw CSV vs DB: village code | Differs on 102,944 rows, all by design of the ingestion (see §5): blank raw codes filled in by name, unmappable rows put under "not yet mapped" |
| Raw CSV vs DB: totals by state, FY, batch, tranche, gender, occupation, status, verification, bank, block, and the FY / tranche / batch cross-tabs | **100% match** |
| Bot vs DB: sheet sweep (sheet questions with "Focus+", every district / block / FY format / batch / tranche) | **161 / 163** |
| Bot vs DB: the sheet's own wording (no scheme name where the sheet has none) | **79 / 85** (2 of the 6 are test-side, see §3) |
| Bot vs DB: every village (3,513) | **3,513 / 3,513** (1 gateway 502 on the first try, correct on re-ask) |
| Follow-up chats (3 chats, 14 turns) | **12 / 14** turns |
| Use cases fully working | **26 of 29** |
| Use cases with a real failure | **3**: FOCUS-002 (each district: wrong district column, 5/5), FOCUS-019 (sheet wording "12.5K batch" refused, 5/5), FOCUS-004 (1 block of 50: Shillong Municipal Board) |

**Testers' 14 Oct failures, re-tested today:** 001 ✔, 006 ✔, 007 ✔, 014 ✔, 019 ✔ with "the" / "Focus+" (✘ in the
sheet's exact wording), 020 ✔, 021 ✔, 022 ✔, 023 ✔. **002 still fails** (see defect 1).

## 2. Result per use case

Sweep = sheet question with "Focus+" in it, over every place / year / batch / tranche. Literal = the sheet's exact
wording. A question with no year draws "which financial year?"; the test tapped "All financial years combined". A
question with no scheme draws "which scheme?"; the test tapped "Focus Plus".

| TC | Use case | 14 Oct (tester) | Sweep | Literal | Today |
|---|---|---|---|---|---|
| 001 | District beneficiary count | Failed | 12/12 | 4/4 | **Pass** |
| 002 | Beneficiaries in each district | Failed | 0/1 | 0/1 | **Fail** — defect 1 |
| 003 | District disbursement | Passed | 12/12 | 4/4 | **Pass** |
| 004 | Block disbursement | Passed | 49/50 | 8/8 | **Fail (1 block)** — defect 3. 13 block names are also village names → bot asks "block or village?" ✔ |
| 005 | FY disbursement | Passed | 8/8 | 4/4 | **Pass** (2022-23, 2022-2023, FY 2022-23, 22-23 and the same for 2025-26) |
| 006 | Batch disbursement | Failed | 2/2 | 4/4 | **Pass** |
| 007 | Tranche disbursement | Failed | 4/4 | 4/4 | **Pass** ("Tranch 1", "Tranche 1", full label) |
| 008 | Gender distribution | Passed | 1/1 | 1/1 | **Pass** |
| 009 | Gender-wise disbursement | Passed | 1/1 | 1/1 | **Pass** |
| 010 | Occupation distribution | Passed | 1/1 | 1/1 | **Pass** |
| 011 | Status distribution | Passed | 1/1 | 1/1 | **Pass** |
| 012 | Verification distribution | Passed | 1/1 | 1/1 | **Pass** |
| 013 | Pending beneficiaries | Passed | 1/1 | 1/1 | **Pass** |
| 014 | Approved beneficiaries | Failed ("not answering") | 1/1 | 1/1 | **Pass** — 714, with the 12.5K-cohort note |
| 015 | Pending Focus status | Passed | 1/1 | 1/1 | **Pass** ("Focus" → asks Focus Plus or Focus Legacy ✔) |
| 016 | Approved verification | Passed | 1/1 | 1/1 | **Pass** |
| 017 | Status-wise disbursement | Passed | 3/3 | 3/3 | **Pass** (Pending, Approved, Rejected) |
| 018 | Tranche status breakdown | Passed | 4/4 | 4/4 | **Pass** — no verification column any more ✔ |
| 019 | Batch status breakdown | Failed | 2/2 | 1/2 | **Fail in sheet wording** — defect 2 |
| 020 | Approved during FY | Failed | 8/8 | 4/4 | **Pass** (see §4 point 2) |
| 021 | Women during FY | Failed | 8/8 | 4/4 | **Pass** (see §4 point 2) |
| 022 | Farmers during FY | Failed | 8/8 | 4/4 | **Pass** (see §4 point 2) |
| 023 | Highest district disbursement | Failed | 1/1 | 1/1 | **Pass** — West Garo Hills ₹39.13 crore |
| 024 | Average per beneficiary | Passed | 1/1 | 1/1 | **Pass** — ₹11,316.08 |
| 025 | District average | Passed | 12/12 | 2/3 | **Pass, 1 slip** — defect 4 (1 in ~20 asks) |
| 026 | District beneficiary comparison | Passed | 6/6 | 3/3 | **Pass** (both counts + difference) |
| 027 | District disbursement comparison | Passed | 6/6 | 3/3 | **Pass** (both totals + the higher one) |
| 028 | Tranche comparison | Passed | 4/4 | 2/2 | **Pass** |
| 029 | Highest bank | Passed | 1/1 | 0/1 * | **Pass** — State Bank of India ₹80.86 crore (5/5 on re-ask) |
| — | Village count / disbursement (001 / 003 asked for a village) | — | 3,513/3,513 | — | **Pass** — 319 shared names drew "which village?" first, then the right village |

\* 029 literal: the bot asked "Focus Plus or Focus Legacy (bank name)?" — correct, since only those two hold a bank;
the test script had no answer for that chip. Re-asked with the chip tapped: 5/5 correct.

## 3. Defects found (bot)

| # | Severity | Use case | Problem | Reproduces |
|---|---|---|---|---|
| 1 | **High** | 002 (also any "by district" split, see chat B) | "How many Focus+ beneficiaries are there in each district?": the model's SQL groups by `district_name_raw` (the raw file's district text) instead of `lgd_district`, which the few-shot example uses and every other answer uses. Result: West Garo Hills **35,059** and South West Garo Hills **15,274**, but "How many … in West Garo Hills?" says **35,039** (SWGH 15,294). Same question, two numbers. Also a 13th row "(no label) — 1". The by-district figures equal the raw file's own district column, so they are not invented, but they disagree with the rest of the bot | 5/5 + 2 more in chats |
| 2 | **High** | 019 | "Give me the status breakdown for 12.5K batch." (the sheet's wording) is **refused**: "I can't do things on your behalf — I can't book, buy … make payments". The guardrail model reads it as a task request and no override recognises "12.5K batch" as Focus Plus data. "…for the 12.5K batch", "…for 93K batch" and "Give me the Focus+ status breakdown for the 12.5K batch" all work | 5/5 |
| 3 | Medium | 004 | "Shillong Municipal Board" (no hyphen): "I couldn't build a working query" 5/5; "SHILLONG-MUNICIPAL BOARD" 1/5. Correct answer ₹85,000. The other 49 blocks are fine | 5/5 (no hyphen) |
| 4 | Medium | 025 | Once in ~20 asks the model wrote `AVG(amount_disbursed)` — the average per **payment** (East Khasi Hills ₹3,107.66) — instead of total ÷ distinct beneficiaries (₹11,475.60). No guard caught it | 1 of 8 in this run; 0 of 10 on re-ask |
| 5 | Medium | follow-up | Chat: "How much Focus+ amount was disbursed in FY 2025-26?" → (area: All of Meghalaya) → **"Break it down by district"** was rewritten "…for all districts in Meghalaya?" and answered the statewide total again (₹73.10 crore), with no split. When the area question was left unanswered, the split came back but grouped by the raw district column (defect 1) | 2 of 2 runs (different failures) |
| 6 | Medium | follow-up | Chat: East Khasi Hills beneficiaries → gender breakdown → **"Compare the number of beneficiaries with Ri Bhoi"** answered Ri Bhoi only (419); East Khasi Hills (13,608) was dropped. ("Compare it with Ri Bhoi" compared the gender split, which is a fair reading: Ri Bhoi has no 12.5K-cohort people, and the bot said so) | 1 of 1 |
| 7 | Low | 020-022 | For FY 2022-23 the figure is right (0) but the explanation is muddled: "the result shows 0 … the only available metric is the number of disbursements". It should say, as the FOCUS-014 answer does, that status / gender / occupation are recorded only for the 12.5K cohort, which was paid in FY 2025-26 | 2/2 formats |

**Cause of defect 1 (INFERRED from code and SQL, not changed):** the per-district few-shot in
`data/focus_plus/focusplus_few_shot.yaml` groups by `lgd_district`, but `district_name_raw` is also in the view and the
model picks it for this shape every time. Following the project pattern (prompt rule → few-shot → deterministic
guard), a guard in `execute_with_repair` that rewrites a Focus Plus `GROUP BY district_name_raw` to `lgd_district`
(SQLGlot, no regex) would make it stable.

**Cause of defect 2 (INFERRED):** the guardrail model's `scope_task` verdict ("give me … 12.5K" read as asking for
money); `c14_turn_stages` overrules scope verdicts for data-shaped questions, but "12.5K batch" without "the" or a
scheme name is not counted as one.

## 4. Behaviour to note (not counted as failures)

1. **The bot asks the year (and for questions without a scheme, the scheme; for statewide questions, the area) first.**
   This follows the current context rule (new chat → scheme, district, year; D-056). 3,513 of 3,513 village questions
   asked the year. Adding "till date", "in total" or a year skips it.
2. **Person fields exist only for the 12.5K cohort.** Gender, occupation, focus status and verification status are
   blank on all 373,144 rows of the 93K cohort, so "how many women / farmers / approved in FY 2022-23" is 0 and in FY
   2025-26 it counts the 12,527 people of the 12.5K cohort only. Testers comparing against the whole sheet will see
   "wrong" numbers; the bot's figures are the correct reading of the data.
3. **"Beneficiaries" = distinct people** (`batch:serial no.`), not rows: 105,813 people, 385,671 payments. A legacy
   member is paid up to four times (one row per tranche). Counting rows in Excel gives 385,671.
4. **District names: the DB uses the LGD district** of the village, the raw file the district text typed at source.
   175 rows differ (144 West Garo Hills → South West Garo Hills, 31 the other way; net 20 people / ₹3.6 lakh). A tester
   who filters the raw `district_name` column gets WGH 35,059 / SWGH 15,274; the bot (and DB) say 35,039 / 15,294. All
   other districts are identical. This may explain the 14 Oct "numbers are not correct" on 001 / 002.
5. Response time: median 2.3 s, 90th percentile 3.9 s per turn (village sweep); 2.7 s / 6.4 s on the sheet questions.

## 5. Raw data vs database

| Level | Units compared | Differences |
|---|---|---|
| Rows (raw `id` = DB `source_row_id`) | 385,671 | 0 missing, 0 extra, 0 duplicates |
| Field by field (15 fields) | 385,671 × 15 | **0** (except village code, below) |
| Person identity (`batch:serial no.` = DB `beneficiary_key`) | 385,671 | **0** |
| State, FY (2), batch (2), tranche (4), gender, occupation (8), focus status, verification status, bank (42) | totals: people, amount, rows | **0** |
| FY × gender / occupation / status, tranche × status, batch × status | 29 cells | **0** |
| District (raw text vs DB raw text) | 12 + blank | **0** |
| District (raw text vs DB LGD district) | 12 | 2 (WGH / SWGH, §4 point 4) |
| Block (raw text) | 50 + "Nan" | **0** |
| Village (raw code vs DB code) | 3,513 DB villages | 3,078 identical; 139 have more rows in the DB; 296 exist only in the DB; 3 raw codes not in the DB |

**Village codes:** the raw file has no village code on 102,923 rows. Ingestion filled 45,280 of them by matching the
village name (all 93K cohort), and put the other 57,649 (57,636 of the 93K cohort, 13 of the 12.5K cohort) under 10
"Unresolved / Not Yet Mapped" codes. 21 rows that had a raw code got a different one (6 to "not yet mapped", 15 to
another LGD code). So for 435 villages the bot's figures are **higher than a sum of the raw rows by their raw code**;
they equal the DB, which is the more complete mapping.

Statewide figures (raw = DB = bot):

| Measure | Value |
|---|---|
| Beneficiaries (people) / payments | 105,813 / 385,671 |
| Amount disbursed | ₹119.74 crore (₹1,197,392,500) |
| FY 2022-23 | 93,286 people, ₹46.64 crore |
| FY 2025-26 | 105,813 people, ₹73.10 crore |
| 93K batch / 12.5K batch | 93,286 people ₹116.61 crore / 12,527 people ₹3.13 crore |
| Tranch 1 / 2 / 3 / 4 | ₹46.64 / ₹23.32 / ₹23.32 / ₹26.45 crore |
| 12.5K focus status | Pending 11,812 · Approved 714 · Rejected 1 |
| 12.5K gender | Female 10,263 · Male 2,264 |
| Highest district / bank | West Garo Hills ₹39.13 crore / State Bank of India ₹80.86 crore |

## 6. How this was run

- `tests/sheet_runs/fp_run.py` (sheet sweep) and `tests/sheet_runs/fp_all.py` (every village), unchanged, in-process
  with the repo venv; VPN up.
- Sheet wording + follow-up chats: scratchpad `fp_literal.py`; reproductions: scratchpad `repro.py` (5 fresh chats per
  question); raw vs DB: scratchpad `raw_vs_db.py`, `village_diff.py`, `level_diff.py` (read-only transaction, counts only).
- Every conversation (3,761 rows): `new_docs/Focus_Plus_all_conversations_2026-10-22.csv`.

## 7. Suggested fixes (not made — awaiting your go-ahead)

1. Defect 1: SQLGlot guard — Focus Plus `district_name_raw` in GROUP BY / SELECT → `lgd_district` (+ regression test).
2. Defect 2: count a Focus Plus batch / tranche term ("12.5K", "93K", "tranche") as data-shaped in the c14 scope
   overrule.
3. Defect 3: block alias "Shillong Municipal Board" (with and without hyphen) in the Focus Plus resolver.
4. Defect 4: guard — a Focus Plus "per beneficiary" question must divide by `COUNT(DISTINCT beneficiary_key)`, not use
   `AVG(amount_disbursed)`.
5. Defects 5, 6: c01 follow-up rewrite — keep "by district" after a statewide answer; keep the previous place in
   "compare … with X".
6. Defect 7: composer note for a person-field question on FY 2022-23.

## 8. Fixes made after the report (22 Oct, on request): FOCUS-019 and FOCUS-004

Tested live with many phrasings each (pauses answered as a chip tap), before and after the fix:

| Case | Phrasings | Before | After |
|---|---|---|---|
| FOCUS-019 batch status breakdown | 18 for 12.5K ("12.5K", "12.5k", "12.5 K", with / without "the", "Focus+", "break down ... by status", "status split", "status wise count", "Can you / Please ..."), 7 for 93K | 18 / 25 | **25 / 25** |
| FOCUS-018 tranche status breakdown (same path) | 3 | 3 / 3 | **3 / 3** |
| FOCUS-004 municipal boards | 16 spellings of the 5 boards ("Shillong Municipal Board", "Shillong-Municipal Board", caps / lower, "Shillong MB", "Tura MB", "William Nagar Municipal Board", "Baghmara MB", ...) x 5 question shapes (with / without the scheme name, beneficiaries, all years, FY 2025-26) | 61 / 80 | **80 / 80** |
| FOCUS-004 ordinary blocks (control) | 4 blocks, 16 questions | 16 / 16 | **16 / 16** |
| FOCUS-004 sheet sweep, every block | 50 | 49 / 50 | **50 / 50** |
| Ward / urban-named villages (regression) | 155 | — | **155 / 155** |

What was wrong and what changed:
- **019:** the guardrail model refused "status breakdown for 12.5K batch" as a task request; "break down ... by status"
  had no word the off-topic filter knows; "12.5 K" was not read as Focus Plus. Now a Focus Plus batch with a status
  breakdown (or named a batch / cohort with a measure) is a data question, the filter knows the batch names, "tranch"
  and "break down", and "12.5 K" / "93 K" mean Focus Plus. Requests to act ("book a payment of 12.5K") are still refused.
- **004:** the SQL model wrote "SHILLONG-MUNICIPAL_BOARD"; a mistyped block is now matched back to the stored block with
  the same letters. "X MB" / "X Municipal Board" / "William Nagar Municipal Board" is now always the municipal board,
  before any "block or village?" or "which constituency?" question (it was the rural Baghmara block, or 0).

Full test suite 3,363 passed / 0 failed; 63 new regression tests. Still open: defects 1 (002), 4 (025), 5, 6, 7.
