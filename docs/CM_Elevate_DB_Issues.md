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

**Effect:** none on answers. The chatbot and, since 2026-10-29, the dashboard card count
`COUNT(DISTINCT request_id)` (schema rule 8). Any other consumer counting rows over-counts by 27.

**Ask:** de-duplicate on `request_id` (or confirm that the source API returns these requests twice).
