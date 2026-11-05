# CM Elevate (applications) — Database Issues

**Date:** 2026-10-29 (found while fixing the RAG fix report, KI-574)
**Dataset:** CM Elevate applications — `curated.v_cm_elevate`
**Owner:** ingestion team (`megh-ingestion`). The app does not change `megh_db`.

## Issue 1: 27 applications are loaded twice

`curated.v_cm_elevate` holds 8,948 rows for 8,921 distinct `request_id`s. The 27 extra rows are exact copies:
same `request_id`, `scheme_name`, `endpoint`, district, `current_level`, `current_file_status` and `onhold`, with
consecutive `cm_elevate_fact_id`s (e.g. `REQ/001/001/10112025/224638` = facts 35178 and 35179; all seen so far are
Meghalaya Piggery Development Scheme, `getApprovedPiggeryList`).

Checks (read-only, 2026-10-29):

| Query | Result |
|---|---|
| `COUNT(*)` | 8,948 |
| `COUNT(DISTINCT request_id)` | 8,921 |
| `COUNT(DISTINCT (request_id, endpoint))`, `COUNT(DISTINCT (request_id, current_file_status, current_level, onhold))` | 8,921 |

**Effect:** none on totals (see the 2026-11-04 resolution below). The chatbot and, since 2026-10-29, the dashboard card count
`COUNT(DISTINCT request_id)` (schema rule 8). Any other consumer counting rows over-counts by 27.

**Ask:** de-duplicate on `request_id` (or confirm that the source API returns these requests twice).

## Issue 2: the chatbot cannot read `file_status` (access needed on `curated.v_cm_elevate`)

**Date:** 2026-11-04 (re-checked while fixing "What is the status of Piggery applications in Umshaken village?";
chatbot known issue KI-624)

**What we need.** The chatbot must answer CM Elevate **status** and **pending** questions from each application's
**file status**. That value exists only as a key inside the JSON column `scheme_specific`
(`scheme_specific ->> 'file_status'`) on `curated.v_cm_elevate`.

**The problem.** The chatbot's database roles cannot read `scheme_specific`:

- `megh_readonly` has column-level SELECT on 28 of the 29 columns of `curated.v_cm_elevate`; `scheme_specific`
  is the one excluded (since about 2026-10-16).
- `semantic.run_query` refuses any query that touches it as well.
- Any query reading `file_status` fails with **`permission denied for view v_cm_elevate`** (re-checked 2026-11-04).
- There is no separate plain `file_status` column on the view.

**Effect on answers.**

- Status questions ("What is the status of Piggery applications in Umshaken village?") cannot use file status. They
  can only use `current_file_status` (forward / resubmit / sendback), which is a different field.
- The agreed **pending** rule (data verified = Valid AND file status = Pending or Send Back,
  `data/cm_elevate/cmelevate_pending_rule.yaml`) cannot run, so pending counts cannot be given.
- Per the source data, file status holds roughly: Pending 8,472, Send Back 90, Rejected 64, Approved 1.

**Ask (either option works; option 1 is preferred).**

1. **Add a plain `file_status` column to `curated.v_cm_elevate`**, taken from `scheme_specific ->> 'file_status'`,
   and grant SELECT on it to `megh_readonly` and `megh_query_runner`. Only the one needed field is exposed, none of
   the rest of the JSON.
2. **Or grant SELECT on the `scheme_specific` column** to the same roles, and allow it through `semantic.run_query`:

   ```sql
   GRANT SELECT (scheme_specific) ON curated.v_cm_elevate TO megh_readonly, megh_query_runner;
   ```

**How to check.** Run as `megh_readonly`; it should return counts, not a permission error:

```sql
-- option 1
SELECT file_status, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate GROUP BY 1;
-- option 2
SELECT scheme_specific ->> 'file_status', COUNT(DISTINCT request_id) FROM curated.v_cm_elevate GROUP BY 1;
```

Nothing else is needed on the data side. Please tell the app team when the check works (and, with option 1, the
column name): the app team then switches status and pending answers to file status.

## Resolution (ingestion team reply, `CHATBOT_DB_CHANGES_2026-11-04.md`, 2026-11-04)

- **Issue 2: done, as option 1.** `curated.v_cm_elevate.file_status` (Pending 8,813 / Send Back 90 / Rejected 62,
  exact spelling; no Approved today), readable by `megh_readonly` and `semantic.run_query`. `scheme_specific`
  stays locked (applicant identifiers). Chatbot side: D-101, KI-624 / KI-679 — status and pending answers read
  `file_status`; `current_file_status` only for a question about the file's last movement.
- **Issue 1: not a double load.** Each of the 27 pairs differs in `file_status` (one Pending, one Rejected; 22
  Piggery, 5 Poultry). Kept as received while the client is asked which is current. Totals stay
  `COUNT(DISTINCT request_id)`; a per-status breakdown adds up to 27 more than the total; 21 of the 27 are Valid,
  so they are inside the pending figure (7,348 on 4 November; 7,327 if Rejected is the current record).
