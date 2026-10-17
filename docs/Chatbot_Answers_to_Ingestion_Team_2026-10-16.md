# Chatbot team: reply to "Database changes the chatbot needs to pick up" (2026-10-16)

**From:** Megh One AI chatbot team · **To:** Megh data ingestion team · **Database:** `megh_db`
**Date:** 16 October 2026 · Replies to `CHATBOT_DB_CHANGES_2026-10-16.md`

We made no change to the database. Every check below was a read-only query, run inside a
`READ ONLY` transaction that was rolled back.

---

## Your three questions

**1. Which role and database does the chatbot connect with? Is `172.18.0.2` the chatbot?**

- Database `megh_db`. Today **every** chatbot connection logs in as **`postgres`**,
  including the one that runs model-written SQL. The read-only pool falls back to the
  app login because `READONLY_DATABASE_URL` is not set.
- **`172.18.0.2` is almost certainly ours:** our Docker image runs 2 workers, each holding a
  minimum of 10 connections, which makes exactly the idle pool of 20 you saw.
- **`10.212.134.4` (28 idle) is a chatbot developer machine** with two app servers running.
  Each server holds about 14 connections.
- We have **cut the pool** in code: minimum 1 per worker (was 10), and idle connections close
  after 120 s. The change takes effect when each server restarts.
- **To switch to `megh_readonly` we need its password.** Please send it through the usual
  secure channel. We will set it in `READONLY_DATABASE_URL` and turn off the superuser
  fallback.

**2. Vector index or prompt?**

Neither. The chatbot does not embed `semantic.v_embedding_documents` and does not load
`semantic.v_prompt_bundles`. At startup it reads the tables those views are built from and
puts a per-scheme block into the SQL prompt:
- `table_catalog`, `column_catalog`, `glossary`, `metric_definitions`, `join_graph`;
- since today, also `semantic.v_join_rules` and `curated.v_data_coverage`.

A change on your side therefore reaches the chatbot at its next restart, with no re-embed.
- **Picked up since today:** `column_catalog.unit`, the `sample_values` lists (shown as
  "VALUES (complete list, use these exact literals)") and `metric_definitions`.
- **A fix of ours:** our reader looked for the wrong column names, so no metric definition
  had reached the prompt until today.

Our vector index holds only our own scheme reference documents.

**3. Does it read the schema directly (`information_schema`)?**

Yes. The SQL prompt lists every column of `curated` and `semantic` from
`information_schema.columns`, fact tables included. Since today that list leaves out:
- every column `megh_readonly` cannot SELECT (we check `has_column_privilege` for that
  role), so `v_cm_elevate.scheme_specific` is no longer shown;
- the three privacy tables (`fact_focus_legacy_disbursement`, `bridge_pg_bank_history`,
  `fact_cm_elevate_disbursement`).

Column notes on `curated.fact_*` tables are no longer put in the prompt either, to match your
documents.

---

## Your seven requests

| # | Request | Status |
|---|---|---|
| 1 | Re-embed | Not needed: we read the catalog tables directly (see Q2). Units, VALUES lists, metric definitions and join rules are now in the prompt. |
| 2 | `megh_readonly` and pool cap | Pool capped in code. Switching roles is **waiting on the password**. Until then, model-written SQL already runs in a `READ ONLY` transaction with a 15 s timeout. |
| 3 | Literals that don't exist | Done. See the list below. |
| 4 | Distinct CM Elevate applications | Done. Every CM Elevate count, "applications" included, is now `COUNT(DISTINCT request_id)`. |
| 5 | One scheme's bundle | Our prompt is already built per scheme (see Q2). |
| 6 | `v_place_names`, `v_data_coverage` | Already covered. Place names: we ask "block or village?" when a name exists at more than one level. Years: read live from each view at startup, so a missing year is answered "no data for that year", never 0. |
| 7 | Reject fan-out joins | Done. A query that row-joins two objects listed in `semantic.v_join_rules` is rejected and sent back to be rewritten as separate aggregates. The same check covers any pair, not just MGNREGA's. |

**What we changed for item 3:**
- **CM Elevate `current_file_status`:** our rules now list exactly `forward`, `resubmit` and
  `sendback to vdv/citizen`, and they carry your API-drift warning.
- **"Approved" / "Rejected":** answered as *not available*. These used to be read from
  `scheme_specific ->> 'file_status'`.
- **"Pending" and "on hold":** both are still answered from `data_verified = 'On Hold'`
  (908). This is a product decision our testers already rely on.
- **`scheme_code = 'FOCUS'`:** no chatbot rule or query used it. Our rules now state that the
  codes are `FOCUS_PLUS` and `FOCUS_LEGACY`.
- **`meta.*`:** the Focus Plus "provisional pending `meta.v_reconciliation_focus_plus`" rule is
  removed. Few-shot examples reading `meta`, `staging` or `raw` are no longer loaded
  (1 Focus Plus, 3 Focus Legacy, 2 CM Elevate).
- **`lgd_block` on `v_district_year_summary`:** our rules already said that view has no block
  column.

---

## What we found in your note

1. **"File status forward = 8,864" counts records, not applications.** As distinct
   `request_id`s, `forward` is **8,837**; `resubmit` is 2 and `sendback to vdv/citizen` is 1,
   which adds up to 8,840. The chatbot will say 8,837. Please correct the expected answer, or
   tell us if you meant records.
2. **Locking `scheme_specific` also removes CM Elevate gender and every per-scheme extra
   field.** We moved sector questions to the new `sector_id` column (identical to the JSON key
   on all 8,867 rows). Gender is now answered *not available*, because `gender_id` was only
   inside `scheme_specific`. If gender is meant to be visible, please add it as a column, the
   way `sector_id` was added.
3. **`megh_readonly` can still SELECT the three privacy tables.** We now refuse them in our SQL
   check, but a column revoke on your side (`account_no`, holder names, applicant names) would
   make that guaranteed.

---

## Expected answers: our status

We have not yet run these live after the change. We will run them once the app restarts on
the new code, and again after the switch to `megh_readonly`.

| Question | Expected | Chatbot now |
|---|---|---|
| CM Elevate applications | 8,840 | `COUNT(DISTINCT request_id)` by rule and by code |
| File status "forward" | 8,864 | 8,837 distinct (see finding 1) |
| On hold | 908 | `data_verified = 'On Hold'` (unchanged) |
| Pending | explain | **908 on hold**, by our product decision (see item 3) |
| Focus+ FY2024-25 disbursements | "no data" | year refused before SQL (unchanged) |
| Job cards 2022–2026 | refuse to sum | latest-year rule (unchanged) |
| Mawlai | block or village? | asks (unchanged) |
