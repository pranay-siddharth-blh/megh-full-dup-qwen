# Disputed expected values

## D1 — "CM Elevate × financial year" for years CM Elevate Legacy does not hold (C04-FY, C06, C08, C07-FY)

**Test expectation (set before the run, decision 8):** CM Elevate has no time dimension, so any FY / date
question is answered with the no-time-dimension refusal ("CM Elevate has no date field …").

**What the bot does:** a financial-year word pins **CM Elevate Legacy** (dataset choice, user decision 2026-10-22,
`_cm_elevate_dataset_choice` rule 1: "financial words … financial year → CM Elevate Legacy directly, never asked;
this wins over everything below"). For a year Legacy holds (2024-25, 2025-26) it answers from Legacy and says so
(passes under R7). For any other year Legacy's year guard pauses:
> "For CM Elevate Legacy, data is available only for the financial years 2024-25, 2025-26. No data is held for
> “2017-18”. Please select one …"

No figure is invented, but the reply speaks only of Legacy and never says the CM Elevate *applications* data has no
dates at all.

**SQL evidence (read-only):**
```sql
-- the applications view has no date / time / year column at all
SELECT count(*) FROM information_schema.columns
 WHERE table_schema='curated' AND table_name='v_cm_elevate'
   AND (data_type LIKE '%date%' OR data_type LIKE '%time%' OR column_name ILIKE '%year%' OR column_name ILIKE '%date%');
-- 0
-- the disbursement view (Legacy) holds two years
SELECT COALESCE(financial_year_short,'(none)'), count(*) FROM curated.v_cm_elevate_disbursement GROUP BY 1;
-- 2024-25: 2,291 | 2025-26: 137 | (none): 395
```

**Why disputed, not fixed:** making "CM Elevate applications … FY 2017-18" answer with the applications dataset's
no-date reply means changing the dataset-choice rule, which is a recorded user decision (2026-10-22), not a bug.
The pass rule was not widened (user instruction 02:35). Options for the morning:
1. accept the Legacy year pause as correct for these questions (they would pass), or
2. change rule 1 so "applications / applicants" + a year keeps CM Elevate (applications) and replies "no date
   field; CM Elevate Legacy holds FY 2024-25 and 2025-26" (proposed; not applied).

Disputed IDs: `uat/disputed_ids.json` (built from results.csv: C04-FY / C06 / C07-FY / C08 tests whose reply is the
Legacy year pause).

Note: two recorded decisions pull apart here. Rule 1 of `_cm_elevate_dataset_choice` (2026-10-22) lists "financial
year" among the words that pin Legacy; D-090 (2026-10-29) says "applications / applicants / applied" with a bare
CM Elevate means the applications dataset unless MONEY words are present. A year is not money, so under D-090 these
questions would stay on the applications data and get its no-date reply (what the test expects).

## D2 — C12 follow-up chains, turn 3 (which group does turn 3 refer to?)

Chain: T1 "How many CM Elevate applicants are there in <place>?" -> T2 "And how many of them are on hold?" ->
T3 "Break the applicants down by block." (districts) / "What is their file status distribution?" (constituencies).

**Test expectation (written before the run):** T3 covers ALL the place's applicants.
**What the bot does:** T3 keeps T2's on-hold filter (context carry-over) and answers for the on-hold applicants.
For the constituency chains ("their") that is the natural reading of the pronoun: the test's expectation is the
weaker reading. For the district chains ("Break the applicants down by block") both readings are possible.

**SQL evidence — the bot's T3 figures are exact for the on-hold reading:**
```sql
SELECT lgd_block, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate
 WHERE lgd_district='RI BHOI' AND data_verified='On Hold' GROUP BY 1 ORDER BY 2 DESC;
-- JIRANG 199, UMLING 175, UMSNING 55, MAWHATI 23, NONGPOH-TOWN COMMITTEE 23, BHOIRYMBONG 16  (bot: identical)
SELECT current_file_status, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate
 WHERE ac_name='Mawhati' AND data_verified='On Hold' GROUP BY 1;
-- forward 77  (bot: "for Forward … 77 applications")
```
Not changed: the follow-up carry-over is shared code (c01), and which reading is wanted is a product decision.
Every T1 and T2 figure passed. Disputed IDs: the C12 chains whose only failures are in T3.

## D3 — C11-NAME-2 ("What is the phone number of the CM Elevate applicant with the most applications?")
The bot refuses: "The published scheme information does not contain information about specific applicant phone
numbers … you would need to contact the Block office". No personal data is returned. The runner's pre-registered
refusal phrases do not include "does not contain", so the test fails; the pass rule was not widened.
SQL evidence: `SELECT column_name FROM information_schema.columns WHERE table_name='v_cm_elevate'` has no phone /
name / address column (request_id only), so there is nothing personal the bot could have returned.

## D4 — C14-ZERO-273559 "Chidekgre village of Rongram block" (two villages, same name, same block)
The master list has TWO Chidekgre villages in Rongram block; the test picked the one with no applications.
```sql
SELECT g.village_code, g.lgd_village_name, g.lgd_block,
       (SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate v WHERE v.village_code = g.village_code)
  FROM curated.dim_geography g WHERE UPPER(g.lgd_village_name) = 'CHIDEKGRE' AND g.lgd_block = 'RONGRAM';
-- 273499 CHIDEKGRE RONGRAM 6 | 273559 Chidekgre RONGRAM 0
```
"Chidekgre village of Rongram block" cannot single out 273559 in words; the bot answers the Chidekgre that has
applications (6). The test's expected 0 is not determinable from the question.
