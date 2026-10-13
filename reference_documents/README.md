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
| `pm_run.py` / `pm_all.py` | the PMAY-G sheet / every PMAY-G village |
| `ce_run.py` / `ce_all.py` | the CM Elevate sheet / every CM Elevate village (`CE_ONLY_CODES` re-runs chosen villages) |
| `write_ce.py` | writes the CM Elevate sheet columns N..Q |
| `cl_run.py` / `cl_all.py` / `write_cl.py` | the CM Elevate Legacy sheet / every CM Elevate Legacy village / its columns G..J |
| `fl_run.py` / `fl_all.py` / `write_fl.py` / `fl_drive.sh` | the Focus Legacy sheet / every Focus Legacy village / its columns G..J / VPN-proof resume loop |
| `fp_run.py` / `fp_all.py` / `write_fp.py` | the Focus + sheet / every Focus Plus village (`FP_ONLY_CODES`; twin villages picked by LGD code) / its columns N..Q |
| `mg_score.py` | scores a results file per test case, with a reason for each failure |
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
