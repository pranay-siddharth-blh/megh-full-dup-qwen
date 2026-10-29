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
