# Scheme test sheets — how each sheet is tested and fixed

This folder holds the testers' workbook **`Test Case Results - 30th Sep 26.xlsx`**. It has one sheet
per area: General, MGNREGA, PMAY-G, CM Elevate, Focus +, FOCUS (Focus Legacy) and CM Elevate
Legacy. Sheets are done **one at a time**, and every sheet goes through the steps below. A sheet is
finished only when **every test case passes, at every level of the hierarchy**.

| Sheet | Status | 9th run | After fix | Hierarchy coverage |
|---|---|---|---|---|
| General (TC-001..TC-024) | Done 2026-10-10 | 15 Pass / 9 Fail | 24/24 Pass | entity recognition: all 6,491 MGNREGA villages (UPPER/Title/lower), all 12 districts and 55 blocks (182/182), all 56 constituencies |
| MGNREGA (DATA-001..DATA-030) | Done 2026-10-10 | 13 Pass / 17 Fail | 30/30 Pass | **every village 6,491/6,491**, every block 55/55, every district 12/12, every assembly constituency 56/56, every FY; sheet cases 783/783 |
| PMAY-G (PMAY-OFF-001..028) | Done 2026-10-10 | 25 Pass / 3 Fail | 28/28 Pass | **every village 5,121/5,121**, every block 56/56, every district 12/12, village/block/district pairs, all 7 FYs, sanction dates; sheet cases 678/678 |
| CM Elevate (CM-ELEVATE-OFF-001..030) | Done 2026-10-10 | 20 Pass / 10 Fail | 30/30 Pass | **every village 2,087/2,087**, every block 66/66, every district 12/12, every programme 15/15; sheet cases 529/529 |
| Focus + (FOCUS-001..030) | Done 2026-10-10 | 27 Pass / 3 Fail | 30/30 Pass | **every village 3,513/3,513**, every block 50/50, every district 12/12, both FYs (4 formats), both batches, all 4 tranches; no constituency data in this scheme; sheet cases 163/163 |
| FOCUS (Focus Legacy, TC-01..TC-28) | Done 2026-10-12 | 19 Pass / 9 Fail | 28/28 Pass | **every village 3,384/3,384**, every block 56/56, every district 12/12, every constituency 55/55, all 4 FYs (+ the 2023-24 gap); sheet cases 231/231 |
| CM Elevate Legacy (TC-01..TC-36) | Done 2026-10-12 | 25 Pass / 11 Fail | 36/36 Pass | **every village 1,051/1,051**, every block 59/59, every district 12/12, every constituency 55/55, every scheme 13/13, both FYs; sheet cases 300/300 |

---

## MGNREGA UAT round (2026-10-30) — the sheet on the answer-with-defaults rules

The MGNREGA sheet was run again on the 2026-10-30 code, because the rules it was first passed on (2026-10-10) had
changed since: a question with no year is answered over **all financial years** at once (no year pause, D-089);
job cards with no year give the latest year; FY 2025-26 women employment must be stated "not recorded"; a
"which scheme?" pause on a MGNREGA-only measure is a defect; villages that share a name (J-10) are answered one
row each. Coverage (`tests/sheet_runs/mg_uat.py` + `mg_uat_villages.py`): every district (12), block (56) and
assembly constituency (56) × every shape of its level × every FY (five year formats) **and** no year; the village
shapes at every district and block; statewide; every ranking per FY and all years; 24 sample villages × 12 shapes ×
5 year options; 40 same-name villages; then **every one of the 6,491 villages**. Results and the column writer are
in the scratch run folder's `r_main*.json` / `r_vill*.json`; the sheet gets columns **U..X** ("UAT 30-Oct Result /
Remarks", "After Fix 30-Oct / Remarks") and a tab "MGNREGA UAT 30-Oct" with every after-fix conversation.
Scripts: `mg_uat.py`, `mg_uat_villages.py`, `mg_uat_score.py`, `write_mg_uat.py`, `mg_uat_drive.sh` (first /
after / score / sheet). Backup: `backup/Test Case Results - 30th Sep 26.backup-2026-10-30.xlsx`.

What it found (KI-635..KI-643 in `docs/KNOWN_ISSUES.md`): village codes digit-grouped like counts; a no-year
district ranking sent to the documents by the verifier; same-name villages summed, or their query rejected, or
compared on the wrong totals; a rephrase adding "under the available schemes"; twin codes the SQL never filtered;
village money rounded to crore (1.60 lakh as "0.02 crore"); "RONGARE ADING" rewritten to the Rongara block; a
`HAVING > 0` dropped as an "unasked threshold" so every no-year constituency list failed; a village list written
without GROUP BY (124 rows for 116 villages); an invented year filter on an all-years average. Harness rules learnt:
a twin is judged on its own answer section and its own row; a wages-vs-materials tie is a pass when the answer says
"the same"; a connection error (VPN drop, Postgres connection cap, gateway timeout) is never a bot failure — it
re-runs on resume.

## Final round (2026-10-13)

Every test case of all seven sheets re-run on the final code: **206/206 test cases, 2,946/2,946 conversations**.
One report: `Final_Test_Report_2026-10-13.xlsx` (Summary, one tab per sheet, every conversation). Scripts:
`tests/sheet_runs/final_round.sh` (runs all seven, waits for the VPN) and `final_report.py`.

## Step 1 — Read the sheet

1. Back up the workbook before writing anything to it.
2. List every test case: ID, scenario, test input, expected result, and the testers' earlier remarks
   and status columns. Earlier remarks often name the exact failing village or phrasing, and each one
   becomes a test.
3. For each case, write down what it measures, at which level (village, block, district, assembly
   constituency, state), whether the question carries a year, and whether it names the scheme. Keep
   the testers' own wording: most questions do not name the scheme.

## Step 2 — Work out the truth from the database

- Every expected figure is computed from `megh_db` (`curated.*` views) with **read-only** queries.
  Never take the bot's own answer as the truth.
- Use the same rules the app uses (`docs/DATA_MODEL.md` §5). For example: count villages by
  `village_code`; MGNREGA money is in lakh; `job_cards_issued_total` is a stock (one year, never
  summed); women employment for FY 2025-26 is not recorded at source; PMAY-G excludes placeholders.
- Never query the privacy tables (`CLAUDE.md` §6).

## Step 3 — Run every test case of the sheet (100%)

- Each case runs through the live **LangGraph** pipeline (`pipeline.answer_question`, real models,
  `megh_db`), the way the chat UI calls it.
- When the bot pauses, answer the way a user would: tap the chip for the case's year, place or
  village. Record every pause. A pause the user should not need counts as a defect: "which scheme?"
  for a measure only one scheme has, "whole constituency or part?" after the user typed
  "constituency", or a list of options that leaves out the right one.
- A case passes only when **the right figure** is given, at **the right level** (village, block,
  district or constituency), with **no needless pause** and **no refusal**.

## Step 4 — Test the whole hierarchy, not a sample

Every place the scheme holds data for, **one question per place**. The question shape rotates over
the sheet's cases for that level, and the financial year rotates over all years.

| Level | Coverage |
|---|---|
| Village | **every** village (`village_code`) of the scheme. Name case rotates UPPER / Title / lower. Names shared by several villages must ask "which village?" with the right village offered |
| Block | **every** block. Blocks that are also village names are asked both bare and as "X block" |
| District | **every** district |
| Assembly constituency | **every** constituency, where the scheme holds AC data |
| Year | **every** financial year the scheme holds, in several formats: `2023-24`, `2023-2024`, `FY 2023-24`, `23-24` |
| Rankings and comparisons | every year |

A zero is only correct when the database has zero or no record for that place and year, and the
bot says so plainly.

## Step 5 — Write the 9th-run result into the sheet

Add two columns after the testers' last column:

- **9th Result**: `Pass` or `Fail`.
- **9th Remarks**: what was tested (the numbers covered), what the bot answered, what the database
  says, and **why** it is wrong (the cause in the code), for every failure.

## Step 6 — Fix every failure

Follow `CLAUDE.md`:

- Find the root cause by tracing the turn. Typical causes are the scheme gate, the entity resolver,
  the year gate, the rephraser, the guardrail model, SQL generation and the composer.
- Fix it in a **stage function** in `app/pipeline.py`, never in a graph node.
- For a wrong number, add a **deterministic guard**, not only a prompt rule.
- Add a regression test that calls the real function (`tests/test_<sheet>_sheet_fixes.py`).
- Record the bug as a `KI-` entry in `docs/KNOWN_ISSUES.md`.

## Step 7 — Re-test until everything passes

1. Re-run the failed cases, then **the whole sheet and the whole hierarchy again**, to catch
   regressions.
2. Run the full suites: pytest on the pytest-style files, plus the 14 plain-script suites
   (`docs/TESTING.md`).
3. Repeat Step 6 and Step 7 until every case passes.

## Step 8 — Write the after-fix result

Add two more columns:

- **After Fix**: `Pass` for every case.
- **After Fix Remarks**: what was fixed and the re-test evidence (cases covered, example figures
  against the database). Cases that needed no fix say "No fix needed" with their re-test count.

Then update `docs/CURRENT_STATE.md`, `docs/HANDOFF.md`, `docs/KNOWN_ISSUES.md` and
`docs/TESTING.md`, and tell the user the result before starting the next sheet.

---

## Tools

The scripts live in `tests/sheet_runs/`. They are not collected by pytest. Run them from the repo
root, with the VPN up.

| Script | Purpose |
|---|---|
| `harness.py` | `Conv`: one conversation through `pipeline.answer_question` (records the answer, pause, rows, SQL, entities and chip questions) |
| `run_general.py` | the General sheet, including the TC-023 hierarchy (districts, blocks, villages) |
| `rerun_failed.py` | re-runs the General failures after fixes |
| `mg_run.py` | the MGNREGA sheet: every case, blocks, districts, constituencies, rankings |
| `mg_all.py` | **every MGNREGA village**, one question each (resumable, checkpoints every 200) |
| `pm_run.py` / `pm_all.py` / `pm_drive.sh` / `write_pm.py` | the PMAY-G sheet (every case, every block, district, constituency, district x FY) / every PMAY-G village (resumable, `PM_ONLY_CODES` re-runs chosen villages) / VPN-proof driver (sheet + villages until clean, then pytest + scripts) / its columns U..X |
| `ce_run.py` / `ce_all.py` | the CM Elevate sheet / every CM Elevate village (`CE_ONLY_CODES` re-runs chosen villages) |
| `write_ce.py` | writes the CM Elevate sheet columns N..Q |
| `cl_run.py` / `cl_all.py` / `write_cl.py` | the CM Elevate Legacy sheet / every CM Elevate Legacy village / its columns G..J |
| `fl_run.py` / `fl_all.py` / `write_fl.py` / `fl_drive.sh` | the Focus Legacy sheet / every Focus Legacy village / its columns G..J / VPN-proof resume loop |
| `fp_run.py` / `fp_all.py` / `write_fp.py` | the Focus + sheet / every Focus Plus village (`FP_ONLY_CODES`; twin villages picked by LGD code) / its columns N..Q |
| `mg_score.py` | scores a results file per test case, with a reason for each failure |
| `mg_uat.py` / `mg_uat_villages.py` / `mg_uat_score.py` / `write_mg_uat.py` / `mg_uat_drive.sh` | the 2026-10-30 MGNREGA UAT round on the answer-with-defaults rules: hierarchy + sample villages / every village (both resumable; `MGU_RERUN_FAILED=1` re-runs the failures) / scorer / sheet columns U..X / driver |
| `trace.py` | one conversation with node logs (`TRACE_LOG=1`; `REINGEST=1` rebuilds the KB) |

For a new scheme, copy `mg_run.py` / `mg_all.py`, then change the question shapes and the
truth queries (Step 2).

## Fix log (summary)

- **General (KI-228..235):** six schemes listed; Focus Legacy how-to-apply; no "reference
  material" wording; required/optional documents; "the two schemes" from earlier turns; rule
  questions answered from the reference docs; guardrail no longer refuses how-to / unknown-scheme /
  follow-ups; "which year was the highest?"; "show it year-wise" while the year question is
  pending; fallback wording.
- **MGNREGA (KI-236..243 and later):** "expenditure" means MGNREGA; the guardrail never refuses a
  figure question; the rephraser keeps multi-word villages and spend words, and never widens a
  question to all schemes; no constituency whole-or-part pause when "constituency" is typed;
  HQ-town blocks are not answered as districts; AVG/SUM ratio; deterministic combined and
  breakdown answers; whole village lists with the true count; village names with a
  `(qualifier)` and a punctuation twin. All-villages run (KI-244..248): no look-alike block/AC
  pause for an exact village name, the rephraser keeps name suffixes / brackets / block words,
  bracket-tolerant chips, deterministic wages-vs-materials, DISTINCT village lists, village names
  masked for the guardrails.
- **PMAY-G re-test 2026-10-30 (KI-445 / D-096, KI-630):** every assembly constituency answered (v_pmay.ac_name;
  before: a false 0 / 'no matching records' for all 56); villages sharing a name answered one row each (before:
  summed or 'couldn't build a working query'); chips keep the constituency / village. The all-villages run also
  found five exact village names respelt by the D-093 normaliser (KI-631: RONGARE ADING -> Rongara block, Pyndeng
  Shallang -> 'pending', Centre Village -> Kentra, Songma Enggok -> Songsak, hawai bhoi -> Ri Bhoi): a span that
  is an exact village name is never rewritten. Final code: sheet **1,142/1,142** conversations (28 cases; 56 ACs x 3
  wordings, 12 districts, 56 blocks, 84 district x FY, pairs, dates), **every village 5,121/5,121**. Behaviour
  change: a bare block name that is also a constituency (Dalu, Chokpot, Mawlai, ...) now asks block or constituency
  under PMAY-G, as it does under MGNREGA (D-059). Scripts `pm_run.py` (now every
  AC and every district x every FY), `pm_all.py`, `pm_drive.sh` (VPN-proof driver), `write_pm.py` (columns U..X).
- **PMAY-G (KI-249..252):** placeholder registrations stated beside the beneficiary count (the testers'
  6,125 vs 6,122); summaries of a place always answered from the data; the year chip's "across all
  financial years" never answered with the list of years; place names masked for every guard
  (Chokpot, Wage Kona); chip questions never rephrased; hyphenated name suffixes kept.
- **CM Elevate (KI-253..258):** "applicants" never rephrased to "applications"; CM Elevate wording
  (data verification, sector, status distribution, pendency) goes to the data; deterministic sector
  answers counting distinct applicants; a block that is also a village asks which; every named
  district kept in a comparison; programme x sector answers state each programme's total.
- **Focus + (KI-260..263):** a block tagged as a district is read as the block (Shillong-Municipal Board);
  tranche / batch status breakdowns count beneficiaries with "status not recorded"; a village with "(GARO)" in
  its name is not the Garo Hills region; a ward named in full beats the district-alias question.
- **Focus Legacy (KI-264..272):** "FOCUS" is the scheme, not a variant filter; overview / list / date-range
  requests are not refused; duplicates state the repeat payments; constituencies offered for HQ-town names;
  calendar months read correctly; FY comparisons per year; Rs 5,000 per member stated; a village name is never a
  producer-group filter; village names masked for the harm checks.
- **CM Elevate Legacy (KI-273..277):** user decision — a bare "CM-ELEVATE" data question goes to CM Elevate
  Legacy unless it uses applications-only words; who-is-it-for questions are knowledge; application breakdowns
  ranked descending; the Tura Municipal Board stored name corrected; HQ-town constituency names offered.
- **Rule:** work only on the scheme the user names; finished sheets are not re-run live.

---

## Cross Scheme sheet (`Cross Scheme Test Cases.xlsx`, CROSS-1..CROSS-20) — done 2026-10-13

The same steps as the scheme sheets, applied to questions that compare schemes. Backup of the workbook:
`backup/Cross Scheme Test Cases.backup-2026-10-13.xlsx`. Results: Sheet1 columns D..H (9th Run, After Fix),
tabs `Coverage` and `All conversations`.

| | 9th run | After fix |
|---|---|---|
| Sheet cases | 0 Pass / 20 Fail (18 paused, 2 wrong) | 20/20 Pass |
| Conversations | — | **8,649 / 8,649** |

**How the names are read.** FOCUS = Focus Legacy when Focus+ is also named; a bare CM-ELEVATE = CM Elevate Legacy
(user decision 2026-10-12) unless the applications words are used; "CM Elevate applicants" with money or FY words =
Legacy as well.

**What each scheme's figure is** (the rule its own sheet passed on; never added together): MGNREGA persons employed
/ expenditure; PMAY-G houses sanctioned / amount released; Focus Plus beneficiaries / disbursed; Focus Legacy
producer-group memberships (and groups) / remitted; CM Elevate applications, no money, no FY; CM Elevate Legacy
sanctioned applicants / disbursed.

**Generated cases (our own permutations)**, every one checked cell by cell against `megh_db`:
1. the 20 sheet questions, with `[district]` = every district (CROSS-8/11/14), `[block]` = every block (CROSS-9),
   20 district trios (CROSS-16) — 138;
2. all 57 combinations of the six schemes (15 pairs, 20 triples, 15 fours, 6 fives, all six) x count / money / both,
   statewide — 171; which is higher (count, money) — 114; coverage — 57;
3. every FY 2017-18..2025-26 (incl. a year only some of the schemes hold, and "FY2022-23" without a space) — 171;
4. district-wise, leading scheme per district, top district per scheme, block-wise in every district — 69;
5. every district x every combination — 684; every block (incl. municipal / town committee blocks) — 134;
   every assembly constituency — 120; **every village any scheme holds — 6,978**;
6. wording: vs / & / lowercase / nrega / pmay g / FocusPlus / "all six schemes" / "scheme-wise" — 13.

**Pass rule.** The right figure for every scheme asked (and no other), at the right level, labelled; "no data for
FY …", "not recorded by constituency" or "no money recorded" where true — never a false 0; no needless pause (a year,
area or scheme pause, or the same which-village pause twice, is a fail); rankings, leader and top district right.

**Run it again** (repo root): `python tests/sheet_runs/cross/cross_run.py sheet state rank coverage year dwise words
district block ac village` (resumable; `CROSS_ONLY=<ids file>` re-runs a list; `failed.py` writes the failed ids),
then `python tests/sheet_runs/cross/write_report.py`. If Postgres says "too many clients", lower `CROSS_CONC` and
`DB_POOL_MAX_SIZE`.
