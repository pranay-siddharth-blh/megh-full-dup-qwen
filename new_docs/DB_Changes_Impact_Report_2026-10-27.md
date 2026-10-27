# DB Changes Impact Report: 2026-10-27

The DB team's note "Database Changes and Next Actions for the Chatbot Team" (Thulasi Ram, 2026-10-27) lists six changes.
This report checks each one against our code and the live database.

**Bottom line: none of the six changes breaks the chatbot today.** Every recent generated query still runs, all six
schemes answer end to end, and the audit log has no new permission, timeout or disk-cap errors. I found four things to
act on. Only one is caused by today's changes, and it is minor (T1 below). Nothing in the code was changed.

---

## 1. How the chatbot connects today (dev box, VERIFIED live)

| Pool | Login | Used for | Today's changes apply? |
|---|---|---|---|
| Read-only pool (`READONLY_DATABASE_URL`) | `megh_readonly` | every model-generated query, plus the startup catalogue reads | **Yes**: column locks and all role limits |
| App pool (`DATABASE_URL`) + LangGraph checkpointer | `postgres` (superuser) | `app.*` tables, our fixed hand-written queries | No: a superuser bypasses every protection |

- `megh_app` does **not exist yet** on the server: `020_megh_app_role.sql` is still waiting for our go-ahead.
- `megh_chatbot` **exists** (connection limit 20, the same settings as `megh_readonly`) but has no password yet.
- The deployed VMs and the `172.18.0.2` container (very likely the old build, see HANDOFF) were **not** checked. I
  cannot see their `.env` files. **UNKNOWN — NEEDS VERIFICATION.**

Live settings on `megh_readonly` (VERIFIED): `statement_timeout=30s`, `idle_in_transaction_session_timeout=60s`,
`temp_file_limit=1GB`, `default_transaction_read_only=on`, connection limit 20, and no execute right on `pg_sleep`,
`pg_cancel_backend` or `pg_terminate_backend`.

## 2. Change by change

| # | DB change | Effect on us | Trouble? |
|---|---|---|---|
| 1 | Name columns locked (`first_name`, `middle_name`, `last_name` on `fact_cm_elevate_disbursement`; `name_on_the_account` on `fact_focus_legacy_disbursement`) | Active for `megh_readonly`: all four return "permission denied" (checked). We never query those two tables: `sql_guard.PRIVATE_TABLES` refuses them before execution, and no app code reads those columns. A `SELECT *` on a table with hidden columns is already expanded to the readable columns (`_star_without_hidden_columns`, c11). | **No** |
| 2 | Role limits (1 GB temp disk, 20 connections, no `pg_sleep` / cancel / terminate) | The 30 s server timeout is longer than our own 15 s query timeout, so ours fires first. Our SQL guard already refuses `pg_sleep` and the cancel/terminate functions. The slowest replayed query took 5.2 s, and none hit the disk cap. The 20-connection limit equals our agreed plan exactly (4 per worker × 5 workers), so there is **no headroom** (T4). | **No** (watch T4) |
| 3 | `semantic.check_query()` | New and optional; we don't call it yet. I ran it on every replayed query: **0 row-join flags, 0 errors**. Highest estimated cost: 101,270. | No |
| 4 | `semantic.run_query()` + the `megh_chatbot` login | New. Not used yet. Moving to it is a real piece of work (§4). | Not today |
| 5 | `semantic.scheme_relationships` + 7 glossary terms | We read `semantic.glossary` at startup into the SQL prompt (`schema_introspect`). We don't embed `v_embedding_documents`, so **no re-embed is needed**. But two of the new terms are about schemes we don't serve (CMSS, Home Stay), and they reach **all six** schemes' SQL prompts after the next restart (T1). The rules for our own pairs match what we already do: CM Elevate and CM Elevate Legacy are never added together; Focus+ and Focus Legacy are never added as beneficiaries plus groups. | **Yes, minor (T1)** |
| 6 | `semantic.resolve_name()` | New and optional. Our place resolution still uses our own lists and is unaffected. Tried live: "Mawkyrwat" returns 4 exact matches (constituency, block, GP, village) marked `ask_user`, which is the same kind of level question our D-059 logic asks. It could replace in-memory lists later, but that is not needed now. | No |

The 2026-10-26 `member_id` → `member_key` switch is also clean. `member_id` is no longer visible to `megh_readonly`, no
generated SQL has used it since 2026-10-24, and the few-shot files mention it only in notes and column aliases.

## 3. Tests run (all read-only, VPN, repo venv)

| Check | Result |
|---|---|
| Role settings, column privileges, function rights read from the catalogue as `megh_readonly` | As in §1–2 |
| **Replay of the 400 most recent distinct generated SQL texts** (`app.query_audit`, since 2026-10-20) through our real `db.run_readonly` as `megh_readonly`, plus `semantic.check_query` | **425 single statements ran, 0 failures**: 366 ran as they were; 31 audit rows held several statements joined by `;`, which split into 68 parts (59 ran, 9 were our own `$1`-parameter fixed queries, which can't be replayed without their values); 3 more were parameter queries. check_query: 0 `row_join`, 0 `error`. The only flags were 31 `rejected`, which were the joined audit rows, not real queries. Max estimated cost 101,270 (limit 1,000,000). Slowest 5.2 s. |
| Audit errors 2026-10-24 → 27 (685 turns) | 0 permission denied, 0 temp-file, 0 statement timeout, 0 connection-limit |
| **Live end to end**, app startup (`lifespan`) then `pipeline.answer_question`, one question per scheme | 6/6 answered with figures: MGNREGA 3,061,525 person days (EKH 2023-24); PMAY-G 13,964 completed (WGH 2023-24); Focus Plus ₹0.31 cr (Ri Bhoi 2025-26); CM Elevate 202 applications (EKH 2024-25); Focus Legacy ₹18.40 lakh (WJH 2024-25); CM Elevate Legacy ₹3.81 cr (EGH 2024-25). Catalogue loaded: 50 glossary terms, 62 metrics, 20 join rules. |

The probe scripts are in the session scratchpad, not the repo. No pytest run was needed because no code changed.

## 4. Things to act on

**T1: CMSS and Home Stay glossary terms go into every scheme's SQL prompt (Low; caused by change 5).**
`schema_introspect._matches_scheme` treats any `subject_area` it doesn't recognise as shared by all schemes. Only
`nrlm` is explicitly scoped out. The new terms "combining CMSS with Focus+" (`cmss`) and "combining Home Stay Legacy with
the new Home Stay feed" (`homestay_legacy`) are therefore shown to all six schemes, pointing at `curated.v_cmss` and
`curated.v_homestay_legacy`. The older CMSS and Home Stay term in each area already leaked the same way. No term is
pushed out of the 24-term cap, and no generated SQL has ever touched those views (0 of 59,997 audit rows). So this is
prompt noise and a small risk of a wrong table, not a wrong number today. It takes effect at the next restart, because
the catalogue is read at startup.
**Fix (awaiting your go-ahead):** add `cmss`, `homestay_legacy` (and `homestay`) to the scoped-out entries in
`_SUBJECT_TO_SCHEME`, next to `nrlm`, with a regression test.

**T2: The block officer with no block sees the whole district (Medium, security; existing, raised by the DB team, action 8).**
`app.users`: `ri-bhoi-bo`, role `block_officer`, districts `[RI BHOI]`, blocks `[]`, active. In `auth.authorize` the
block check runs only `if allowed_b and want_b`, so an empty block list skips it and this officer can query every block
in Ri Bhoi. It fails open. Either assign the block (an admin task, no code), or make a `block_officer` with no block
fail closed. Your decision.

**T3: Old result previews in the audit log, kept forever (Medium, privacy; DB team action 4).**
`app.query_audit` has 59,997 rows going back to 2026-08-29, with no retention. 26,717 of them carry a `result_preview`
(jsonb), all written from 2026-09-18 to 2026-10-01. **No code in this repo writes that column today**, so they came
from an older build. What's needed: a decision on the retention period, then clearing the old previews and adding a
purge. Both are writes to `app.*`, so I did not do them.

**T4: No connection headroom on `megh_readonly` (Low, operational).**
Its cap is 20, which is exactly our plan (4 per worker × 1 dev + 4 VM workers). Any extra dev box, worker or script
that uses `megh_readonly` gets "too many connections" refused. Tell the team before adding one (already in
DEPLOYMENT.md).

## 5. The team's main ask: moving generated SQL to `megh_chatbot` + `run_query`

They want every AI query to run as `megh_chatbot` through `semantic.run_query`. That makes their checks impossible to
skip. It is **not** a switch of the connection string. What it touches:

1. **Results come back as JSON.** Numbers become JSON numbers rather than `Decimal`/`int`, and dates become strings.
   `compose_response`'s numeric-faithfulness checks and the formatting code read the row types, so they need checking
   and probably a conversion layer. This is the biggest risk.
2. **No parameters.** `run_query(text, …)` takes plain SQL only. Our fixed queries use `$1` binding, so they stay on
   `megh_readonly`, which the team allows for "fixed, hand-written queries". The startup catalogue reads
   (`schema_introspect`) and the `_check_readonly_login` check also stay on `megh_readonly`, because `megh_chatbot` can't
   read tables. So we keep three logins.
3. **Error handling.** `run_query` returns `{"ok": false, "reason": …}` instead of raising. Their mapping table (refuse
   on `row_join`/`rejected`, ask the user to narrow on `too_expensive`/57014/53400, repair on classes 22/42 except
   42501, "restricted" on 42501, retry once on 08/53300) has to be wired into `execute_with_repair`. Today
   `is_connection_error` and the repair loop work from asyncpg exceptions.
4. **Repair attempts: they ask for at most 2; we do up to 3.** This changes a documented design, so it needs your
   decision and a DECISIONS entry.
5. **Limits match:** 1,000 rows = our `SQL_MAX_RESULT_ROWS`. A cost cap of 1,000,000 is about 10× our highest
   (101,270).
6. Blocked until the team shares the `megh_chatbot` password.

Rough size: a few days, plus a live re-run of the context suite and the scheme bulk checks, because answer composition
depends on the row types.

## 6. Their action list against where we stand

| # | Their action | Status |
|---|---|---|
| 1 | Stop connecting as `postgres` | Generated SQL: done on dev (`megh_readonly`). App pool + checkpointer: still `postgres`, waiting for `megh_app` (needs our go-ahead on 020, then its password). VMs / `172.18.0.2`: unknown. `megh_chatbot`: §5. |
| 2 | Pool ≤ 20 per login | Planned: `megh_readonly` 4/worker = 20 total; `megh_app` 4 + 2 checkpointer = 6/worker = 30 total (cap 30 agreed 2026-10-26). |
| 3 | Handle `run_query` results | Not done (§5). |
| 4 | Audit previews + retention | Not done (T3). The current code no longer stores previews. |
| 5 | Function allow-list | Partly done: SQLGlot guard (D-046) refuses `COPY`, `SET`/`RESET` (`exp.Set`, `exp.Command`), `set_config` and side-effect functions, but through a **block-list** of functions, not an allow-list. Catalogue *tables* (`pg_catalog.*`) are refused. System-information *functions* still pass (checked: `current_setting()`, `version()`, `inet_server_addr()`). They are read-only and leak little, but an allow-list would close them. |
| 6 | Repair ≤ 2 attempts via `run_query` | We do up to 3. Needs a decision (§5.4). |
| 7 | No fact-to-fact join paths | Already guarded: `semantic.v_join_rules` fan-out check in c11, and the team found 0 row joins in 21,973 of our statements (I found 0 in 425). |
| 8 | Block officer with no block | T2. |

## 7. Draft answers to "What we need back from you"

Facts are filled in. Items marked **[you decide]** are yours.

- **Switch date** from `postgres`: generated SQL is already on `megh_readonly`; `megh_app`: **[you decide]**;
  `megh_chatbot`/`run_query`: **[you decide]** (a few days of work, §5).
- **Go-ahead for `020_megh_app_role.sql`:** **[you decide]**. Our side is ready (D-069 readiness check, 2026-10-26).
- **Pool size per login:** `megh_app` 6 per worker (30 total), `megh_readonly` 4 per worker (20 total), 5 workers.
- **Defaults (1,000 rows, cost 1,000,000):** they suit us. Our row cap is 1,000, and our highest recent cost is 101,270.
- **Audit retention period:** **[you decide]**.
- **Result / error handling in place:** not yet (comes with the `run_query` move).
- **`SELECT *` on `fact_cm_elevate_disbursement` / `fact_focus_legacy_disbursement`:** no. Generated SQL is refused on
  both tables by `sql_guard`, and no app query reads them.

## 8. Not caused by the DB changes

In the smoke test, "How many CM Elevate applications were received in East Khasi Hills in 2024-25?" was answered from
**CM Elevate Legacy** (202). This is the open KI-407 question (a bare CM Elevate count: ask, or default to Legacy?),
which is waiting for your decision.

## 9. Fixes applied (2026-10-27, after the review), D-072

| Item | Fix | Status |
|---|---|---|
| T1 / KI-428 | CMSS and Home Stay glossary terms scoped out. The same leak also carried ~40 `v_cmss` / `v_homestay_legacy` column notes (from the 2026-10-26 load) into every scheme's prompt; those are scoped out too. | Fixed |
| T2 / KI-429 | A `block_officer` with no block now gets statewide figures only, plus "no block assigned yet, ask your administrator". | Fixed |
| Action 3 (partly) | Codes 57014 / 53400 now end in the existing 504 "try a narrower question", not "couldn't build a working query". The repair loop is unchanged (see D-072). | Fixed |
| Action 3 / 7 | `semantic.check_query` runs before each generated query; `row_join` goes to repair. Fail-open; 160–370 ms live. | Added |
| Action 5 (partly) | The guard refuses `pg_*`, `lo_*`, `dblink*`, `txid_*`, `inet_*` functions and `current_setting`, `version`, `current_database`. | Fixed |
| T3 / KI-430, actions 1, 2, 4, 6 | Waiting on the data team's reply or your decision. | Open |

Tests: NEW `tests/test_db_changes_2026_10_27.py` (36); pytest 3,863 passed / 0 failed; scripts 14/14; live NL→SQL eval 41/74
with 0 regressions vs this morning; live smoke 6/6 with the same figures. The running server on :8401 needs a restart to
pick these up.

## 10. After the team's replies (2026-10-27 afternoon), D-073

| Item | Done |
|---|---|
| AI-generated SQL runs as `megh_chatbot` through `semantic.run_query` (action 1) | Yes. Third pool, 4 per worker. Our SQLGlot guard still runs first. Fixed queries and catalogue reads stay on `megh_readonly`. Rollback: blank `CHATBOT_DATABASE_URL`. |
| Exact values and types | Each value is restored from run_query's `types` to the type asyncpg returned before. 585 recent real statements compared, old path vs new: 583 identical, and 2 have the same rows in another order (those queries have no ORDER BY). |
| run_query results handled (action 3) | `row_join`: repair with the reason. `rejected`: refused. `too_expensive` / 57014 / 53400: "try a narrower question". Class 08 / 53300: retried once after 1 s. Query mistakes: repair. |
| Repair loop (action 6) | Stays at 3 attempts, each through run_query (the team agreed). |
| application_name | Every session is named `megh-chatbot-v2:app`, `:readonly`, `:chatbot` or `:checkpointer`. Verified in pg_stat_activity. |
| Glossary filter | `cmss`, `nrlm`, `homestay_legacy` are excluded explicitly (KI-428, done earlier today). |
| `megh_app` (020 script, cap 35) | **Waiting for your go-ahead.** The app pool and checkpointer still log in as `postgres`. |
| Old build at `172.18.0.2` (20 `postgres` sessions, no name) | **The server admin should stop that container**, then confirm the 20 sessions disappear. |
| Audit retention (action 4) | **Waiting for your decision** (KI-430). |

Tests: pytest 3,902 passed, 0 failed; scripts 14/14; live NL→SQL eval 43/74 with 0 regressions; live smoke 6/6 with the same figures.

## 10. After the team's replies (2026-10-27 afternoon), D-073

| Item | Done |
|---|---|
| AI-generated SQL runs as `megh_chatbot` through `semantic.run_query` (action 1) | Yes. Third pool, 4 per worker. Our SQLGlot guard still runs first. Fixed queries and catalogue reads stay on `megh_readonly`. Rollback: blank `CHATBOT_DATABASE_URL`. |
| Exact values and types | Each value is restored from run_query's `types` to the type asyncpg returned before. 585 recent real statements compared, old path vs new: 583 identical, and 2 have the same rows in another order (those queries have no ORDER BY). |
| run_query results handled (action 3) | `row_join`: repair with the reason. `rejected`: refused. `too_expensive` / 57014 / 53400: "try a narrower question". Class 08 / 53300: retried once after 1 s. Query mistakes: repair. |
| Repair loop (action 6) | Stays at 3 attempts, each through run_query (the team agreed). |
| application_name | Every session is named `megh-chatbot-v2:app`, `:readonly`, `:chatbot` or `:checkpointer`. Verified in pg_stat_activity. |
| Glossary filter | `cmss`, `nrlm`, `homestay_legacy` are excluded explicitly (KI-428, done earlier today). |
| `megh_app` (020 script, cap 35) | **Waiting for your go-ahead.** The app pool and checkpointer still log in as `postgres`. |
| Old build at `172.18.0.2` (20 `postgres` sessions, no name) | **The server admin should stop that container**, then confirm the 20 sessions disappear. |
| Audit retention (action 4) | **Waiting for your decision** (KI-430). |

Tests: pytest 3,902 passed, 0 failed; scripts 14/14; live NL→SQL eval 43/74 with 0 regressions; live smoke 6/6 with the same figures.
