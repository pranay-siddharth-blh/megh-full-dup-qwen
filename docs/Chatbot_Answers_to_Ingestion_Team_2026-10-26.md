# Chatbot team's reply to "Database changes the chatbot needs to pick up" (2026-10-26)

**From:** Megh One AI chatbot team · **To:** Megh data ingestion team · **Re:** `CHATBOT_DB_CHANGES_2026-10-26.md`

Thank you for the note. Every item was checked against `megh_db` before we changed anything, as you asked. Below: what we did, the answers to your four questions, and five questions back.

## What we did

| # | Your action | Status on our side |
|---|---|---|
| ⚠ | `v_focus_plus.member_id` removed → use `member_key` | **Done.** The SQL prompt (`app/schema_context.py`) and the Focus Plus rule files now say `member_key`, with the same rules: counted only, never displayed, 12.5K cohort only. We checked that `member_key` covers the same 12,527 people and is empty on all 373,144 rows of the 93K batch. Live: a 12.5K-member question now runs on the first try (12,527); before, it failed with "column member_id does not exist" and needed a repair. |
| — | New `region` column on every scheme view | **Done.** Six of our few-shot examples built their own `CASE … END AS region` and grouped by `region`, which now resolves to your column and fails. Renamed to `region_group`, plus a code safeguard that does the same for any SQL the model writes. All in-prompt examples run again (0 errors). |
| 1 | Reload the documents | **Already covered.** We do not use `v_embedding_documents` or a vector index of it. At startup the app reads `semantic.table_catalog`, `column_catalog` (incl. `unit` and `sample_values`), `glossary`, `metric_definitions`, `join_graph`, `v_join_rules` and `curated.v_data_coverage` live, so your units, `VALUES:` lists and never-join lists reach the SQL prompt. The compact bundles (`v_prompt_bundles_compact`) are on our list for the prompt redesign. |
| 2 | Connect as `megh_readonly`, cap the pool | **Not yet; needs a credential.** `READONLY_DATABASE_URL` is still empty on the dev box (KI-304). Please send the `megh_readonly` password through the agreed secure channel. Our pools are capped per worker in `app/config.py`: `DB_POOL_MAX_SIZE` 30 (app login), `READONLY_DB_POOL_MAX_SIZE` 10 (generated SQL), `PIPELINE_GRAPH_PG_POOL_MAX` 2. With several workers that can still add up; we will size the total against your 100-connection limit when we switch to `megh_readonly`. |
| 3 | Rule literals not in the data | **Checked; no change needed.** No SQL or rule of ours filters on `Pending` / `Send Back` / `Rejected` / `Approved` as `current_file_status`; "on hold" uses `data_verified = 'On Hold'`. "Valid" is used only as a `data_verified` value. We never use `scheme_code = 'FOCUS'` (our prompt states there is no such code). No query uses `lgd_block` on `v_district_year_summary`. The `meta.*` / `staging.*` few-shot examples are already kept out of the prompt by our loader. |
| 4 | Route to tested metrics | **Partly.** `metric_definitions` is read into the prompt; routing questions to the metric SQL directly is planned (our metric catalogue work). |
| 5 | Use the lookups | **Partly.** Years: `v_data_coverage` is read (a year with no data gets "data is available only for …", verified today for Focus Plus FY 2024-25). Place names: our resolver asks when a name is at several levels (Mawlai block vs village); switching it to `v_place_names` is planned. |
| 6 | Reject fan-out joins | **Partly.** `v_join_rules` is in the prompt; a hard reject in our SQL checker is planned. |

### Known answers, as checked today through the chatbot

| Question | Your answer | Chatbot | Note |
|---|---|---|---|
| Focus+ beneficiaries | 105,813 | 105,813 ✅ | |
| Focus+ disbursed | ₹119.74 Cr | 119.73925 crore | Right figure; our answer did not round it (fix on our side) |
| Focus Legacy PGs paid | 11,906 | 11,906 ✅ | |
| CM Elevate applications | 8,840 | asks "applications or sanctions dataset?" | Our rule: a bare "CM Elevate" without money words asks |
| CM Elevate "forward" | 8,864 | 8,837 | See question 1 below |
| CM Elevate on hold | 908 | 903 | See question 1 below |
| MGNREGA person-days FY2024-25 | 14,667,872 | 14,667,872 ✅ | |
| MGNREGA expenditure | ₹3,628.67 Cr | ₹3,628.67 Cr ✅ | |
| MGNREGA job cards FY2025-26 | 520,999 | 520,999 ✅ | |
| PMAY released | ₹2,185.26 Cr | ₹2,185.26 Cr ✅ | |
| Focus+ FY2024-25 | "no data" | "data is available only for 2022-23, 2025-26" ✅ | |
| Focus+ 12.5K members | — | 12,527 ✅ | via `member_key`'s cohort |

CMSS and Home Stay Legacy are not yet in the chatbot (it covers six schemes); we'll add them as a separate piece of work.

## Answers to your questions

1. **Role and database.** The dev box connects to `megh_db` with the main login, not `megh_readonly`, until we get the credential. Our generated SQL runs only inside `READ ONLY` transactions through a guarded runner. Whether `172.18.0.2` (Docker) is the chatbot: the dev box runs without Docker, so it is most likely a deploy VM. **Please let us confirm with our server admin** before we answer for certain.
2. **Documents in the prompt or an index?** In the prompt, built at startup from the catalog **tables** (not from `v_embedding_documents`). No vector index is built from your documents. Our Qdrant index holds only the scheme reference documents and chat memory.
3. **Do we read `information_schema` directly?** Yes, `app/schema_introspect.py` reads column lists. Notes on `curated.fact_*` tables are not put in the prompt (only the views'), so the removed fact documents do not affect us.
4. **`v_focus_legacy_pg_search`?** Yes. Since KI-020, Producer Group names are looked up through it (`app/pipeline/schemes/focus_legacy.py`).

## Questions for you

1. **Records or applications for status counts?** Your note defines CM Elevate "applications" as distinct `request_id` (8,840), but quotes "forward" as 8,864 and "on hold" as 908, which are **record** counts. The distinct-application counts are 8,837 and 903. Which should the chatbot give for a status question?
2. **Region:** your `region` column puts **Ri Bhoi inside Khasi**. Our resolver and examples treat Ri Bhoi as its own group (Garo / Khasi / Jaintia / Ri Bhoi). Which grouping should a "Khasi Hills region" question use? Until you or the scheme owners confirm, we keep our current grouping.
3. **"Pending" CM Elevate applications.** You suggest saying it cannot be read. Today the chatbot answers a plain "pending" with `data_verified = 'On Hold'` (903 applications). Is "on hold" an acceptable reading of "pending", or should we refuse?
4. **CM Elevate `scheme_specific ->> 'member_id'`.** Our CM Elevate rules mention a `member_id` key inside `scheme_specific`. Is that key still present, and is it covered by "no plain member IDs"? We never select it.
5. **Fact table `fact_focus_plus_disbursement`** still has a `member_id` column. We only use the view; please confirm `megh_readonly` cannot read it.

## Changed on our side (for your records)

`app/schema_context.py`, `data/focus_plus/*` (rule files and `prompt_assembler.py`), six few-shot files (`data/mgnrega`, `data/pmay`, `data/focus_plus`, `data/cm_elevate`, `data/cm_elevate_legacy` ×2), and `app/pipeline/common/c11_sql_verify_repair.py` (`_region_alias_not_the_column`). Tests: `tests/test_db_changes_2026_10_26.py`. No database object was changed.

---

## Update after your answers (2026-10-26, evening)

Thank you. All five answers are applied:

| Your answer | Done on our side |
|---|---|
| 1. Applications = distinct `request_id` | Already the rule in our SQL checker; the chatbot gives **8,837** (forward) and **903** (on hold). The four CM Elevate examples that still counted records now count distinct applications. |
| 2. Ri Bhoi is in Khasi | Retired our four-group version in the resolver, rules, prompt and examples; region questions use your `region` column. A Khasi answer adds: "Khasi Hills here includes Ri Bhoi district, as in the official LGD region list." "Ri Bhoi" alone is the district. |
| 3. "Pending" ≠ "on hold" | "Pending", "approved", "rejected" and "sent back" now get: "The CM Elevate data doesn't record a "pending" status. What it does record: 903 applications are on hold at data verification, and by file status 8,837 are forward, 2 resubmit and 1 sendback to vdv/citizen (of 8,840 applications)." "Sent back" adds that the file status is not the department's Send Back decision. |
| 4. `scheme_specific` | The `member_id` pointer is removed from our CM Elevate rules; four in-prompt examples that read `scheme_specific ->> 'sector_id'` now read the plain `sector_id`. |
| 5. `megh_readonly` | **The dev box now runs generated SQL as `megh_readonly`.** Pools: 4 + 4 + 2 per worker (2 workers = 20 in total). `SELECT *` on a table with hidden columns is replaced by the readable columns before it reaches you. All in-prompt examples run as `megh_readonly`. |

Still open: the deploy VMs need the same settings (we'll tell you when they switch), and our server admin is checking `172.18.0.2`. The app's own login (`DATABASE_URL`) is still `postgres` for our app tables and catalog reads; moving it to a least-privilege role (`megh_app`) is next on our side.

---

## Update after your reply (2026-10-26, late)

| Your point | Done |
|---|---|
| Khasi note wording | Now: "Khasi Hills here includes Ri Bhoi district, as in the department's district-to-region list." |
| `sector_id` is mostly empty | Agreed and already so: programme questions use the programme (`scheme_name`), never `sector_id`; a blank `sector_id` is shown as "(not recorded)", never 0; our sector answer says "Sector is recorded only on Poultry, Dairy and Goat Farming applications". |
| Live numbers, not fixed text | The "pending" answer runs a query at question time (e.g. Ri Bhoi: 491 on hold, 2,617 forward). No CM Elevate figure is fixed in any answer text; the `*_default_rules.yaml` / `*_response_template.yaml` files that quote approximate counts are not loaded by the app. |
| Catalog reads and `schema_introspect.py` as `megh_readonly` | **Done.** All catalog reads (`semantic.*`, `curated.v_data_coverage`, `information_schema`, `pg_catalog`) now run as `megh_readonly` in a read-only transaction. Same counts as before (29 tables, 62 metrics, 543 column notes, 46 live tables), and `member_id`, `account_no` and `scheme_specific` no longer appear. |

**Where our app tables live:** in **`megh_db`, schema `app`** (users, chat history, audit, LangGraph checkpoints). The app has created and migrated only this schema (`CREATE … IF NOT EXISTS`) since the project started; it never writes to `raw`, `staging`, `curated` or `semantic`. We understand you want to be told before anything is created there. Please go ahead with a `megh_app` role limited to the `app` schema (plus what `megh_readonly` has), and we will switch `DATABASE_URL` to it. Until then `postgres` is used for the `app` tables and for the app's own fixed, parameter-bound queries on `curated`.

Still open: the deploy VMs' switch and `172.18.0.2` (our server admin is checking).

---

## Reply to your late update (2026-10-26)

**Unused rule files.** All 12 `*_default_rules.yaml` / `*_response_template.yaml` files now open with "NOT LOADED BY THE APP … figures are historical …", and a test (`tests/test_db_changes_2026_10_26.py`) fails if any app code starts reading them. We kept the files (they are the scheme teams' reference) rather than delete them.

**Ready for `megh_app`: your four checks, done on our side before the switch**

| # | Your check | Result |
|---|---|---|
| 1 | Fixed queries on `curated` under `megh_readonly`'s limits | **No problem found.** No app query reads `member_id`, `account_no` or `scheme_specific`, or uses `SELECT *` on a table that hides columns (static scan of every SQL string). Live test: with every fixed `curated` read sent through `megh_readonly`, the startup loads and 9 questions covering every scheme's fixed queries ran with **0 "permission denied"**. |
| 2 | `search_path` | **No dependency.** Every app query names its tables `app.<table>`; the LangGraph checkpointer sets `search_path=app` in its own connection string. |
| 3 | 60 s timeouts | **Fine.** The app already stops a query after 15 s. Schema setup is `CREATE … IF NOT EXISTS` and short. |
| 4 | 20 connections in total | **Please raise it to 30.** The checkpointer shares the app login, so each worker holds up to 4 (app) + 2 (checkpointer) = 6. Dev box: 1 worker = 6. Deploy: 2 VMs × 2 workers = 24. Total 30. |

**Backups of the `app` schema.** Thank you for telling us. We will confirm with the project owner whether chat history may stay in your 14-day backups, and reply separately.

Still open from our side: the deploy VMs' switch and `172.18.0.2`.

---

## Reply to your note on the connection limits (2026-10-26)

Thank you for raising `megh_app` to 30.

**`megh_readonly`: 20 confirmed.** Each worker has one read-only pool of at most 4 connections (`READONLY_DB_POOL_MAX_SIZE=4`), used by the generated SQL and the catalog reads alike: 4 × 5 workers = **20**. We will tell you before adding a worker or a VM, or raising any pool, since both caps are hard.

**`172.18.0.2` — very likely our older build.** The deploy VMs still run the earlier build of the chatbot in Docker (`megh-nlp`, compose project `meghalaya`); 172.18.x.x is Docker's default internal network, and that build's pool keeps 10 idle connections per worker × 2 workers = the 20 idle `postgres` sessions you see. This is our inference; our server admin will confirm (`docker inspect megh-nlp`).

**What that means for the totals.** The new build runs beside the old one until switch-over, so for that period the old build's `postgres` connections come on top of the 30 + 20. At switch-over we will stop the old build: the 20 idle `postgres` sessions go with it, and nothing of ours uses `postgres` on `megh_db` any more. We will tell you the date.

**App-schema backups:** the project owner is deciding; we'll reply separately.
