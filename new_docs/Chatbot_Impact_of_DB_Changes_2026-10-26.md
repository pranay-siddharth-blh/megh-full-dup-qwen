# Chatbot team: impact of "Database changes the chatbot needs to pick up" (2026-10-26)

**From:** Megh One AI chatbot team · **To:** Megh data ingestion team · **Database:** `megh_db`
**Date:** 26 October 2026 · Replies to `CHATBOT_DB_CHANGES_2026-10-26.md`

We made no change to the database. Every check below was a read-only query in a `READ ONLY`
transaction, or a question put to the real chatbot pipeline (live model gateway, live database).

---

## Summary

| | |
|---|---|
| New chatbot problems caused by the changes | **4** (details in [section 1](#1-new-problems-the-changes-cause-in-the-chatbot)). All four are fixes on our side. |
| Known answers from your note | **9 of 16 match**. 2 differ because of how your note counts. 1 needs a policy decision. 4 fail on our side (see [section 2](#2-your-known-answers-run-through-the-chatbot)). |
| Questions back to you | **6** ([section 4](#4-questions-for-you)) |
| Role the chatbot connects with | Still **`postgres`**. We need the `megh_readonly` password ([section 3](#3-your-four-questions)). |

**Legend:** ✅ = matches · ⚠ = differs, needs a decision · ❌ = wrong, fix on our side.

---

## 1. New problems the changes cause in the chatbot

### 1.1 `v_focus_plus.member_id` removed: two of our examples now fail

- **What breaks.** Our Focus Plus SQL examples still use `member_id` in two places:
  - "Show Focus Plus payments by district";
  - "How many Focus Plus members are registered but not yet paid?"

  Our hand-written schema notes also still tell the model to use `COUNT(DISTINCT member_id)`.
  When the model copies them, the database returns `column "member_id" does not exist`.
- **How we checked.** We ran every SQL example the chatbot loads against the live database:
  2 of 91 Focus Plus examples fail with exactly this error. In live questions, the model
  mostly wrote `member_key` on its own (it sees the live column list), and our repair step
  can recover, but each failure costs a retry.
- **Your side.** Nothing to do. We confirmed `member_key` behaves the same way `member_id`
  did: 12,527 distinct values, all in the 12.5K batch, NULL on every 93K row.
- **Our side.** Replace `member_id` with `member_key` in the examples and the schema notes.

### 1.2 The new `region` column changes the meaning of `GROUP BY region`

- **What breaks.** Our "Garo Hills vs Khasi Hills" examples build a region with
  `CASE … END AS region` and then `GROUP BY region`.
  - Now that every view has a real `region` column, PostgreSQL groups by **the view's
    column**, not by our alias.
  - The query then fails with `column "lgd_district" must appear in the GROUP BY clause`.
- **How we checked.** 4 examples fail this way, one each for MGNREGA, PMAY-G, Focus Plus
  and CM Elevate. All four ran before the change. In a live test the repair step rewrote the
  query and the answer came out right, but only after a failed attempt.
- **Our side.** Fix the four examples. Where your `region` column fits the question, use it.
- **Your side.** See question 3 (Ri Bhoi), and question 6 (new column names).

### 1.3 CMSS and Home Stay Legacy catalog text now goes into every scheme's SQL prompt

- **What breaks.** At startup the chatbot reads `semantic.table_catalog`, `glossary`,
  `metric_definitions` and `column_catalog`. It keeps only the rows for the scheme in the
  question. It recognises six schemes, so it can't place the `cmss` and `homestay_legacy`
  rows, and treats them as shared. They then reach every prompt:
  - 1 table note, 1 glossary term and 5 metrics for `cmss`;
  - 1 table note, 1 glossary term and 8 metrics for `homestay_legacy`;
  - the column notes for `v_cmss`, `v_homestay_legacy` and `v_nrlm`.
- **Measured** (one question per scheme, prompt built exactly as in production; our SQL
  prompt budget is 15,360 tokens):

  | Scheme | SQL prompt today | Without CMSS / Home Stay / NRLM text | Examples left in the prompt today |
  |---|---:|---:|---|
  | Focus Plus | ~21,700 tokens | ~17,800 | 1 (cut from 5) |
  | MGNREGA | ~20,000 | ~16,100 | 1 |
  | PMAY-G | ~18,200 | ~14,500 (fits) | 1 (5 without the new text) |
  | CM Elevate | ~21,700 | ~17,700 | 1 |

  When a prompt is over budget, the SQL examples are the first thing cut. So the new text
  costs every scheme about 4,000 tokens, and costs PMAY-G four of its five examples.
  To be fair: three of the four schemes were already over budget before this change.
- **Our side.** Map `cmss`, `homestay_legacy` and `nrlm` out of the six schemes' prompts.
- **Your side.** See question 5.

### 1.4 The chatbot does not serve CMSS or Home Stay Legacy, and its replies mislead

Now that this data exists, officers may ask about it.

| Question | What the chatbot said | Problem |
|---|---|---|
| "How many CMSS scholarships were paid, and how much?" | "I don't write social media posts, captions, hashtags…" | Wrong refusal. It should say CMSS isn't covered yet. |
| "How much was sanctioned and disbursed in Home Stay Legacy loans?" | "Only CM Elevate Legacy records loans… tap it below" | It points the user to an unrelated scheme. |

- **Our side.** Fix both replies. Whether to add the two schemes is a product decision for us.
- **Your side.** Nothing.

---

## 2. Your known answers, run through the chatbot

Each question was asked as a new chat. Where the chatbot asks "which area?" (its normal
behaviour), we re-asked with "statewide in Meghalaya" in the question.

| # | Question | Your answer | Chatbot answer | |
|---|---|---|---|---|
| 1 | Focus+ beneficiaries in total | 105,813 | 105,813 | ✅ |
| 2 | Focus+ amount disbursed | ₹119.74 Cr | ₹1,197,392,500 (= ₹119.74 Cr) | ✅ (shown in rupees, not crore) |
| 3 | Focus Legacy PGs paid | 11,906 | 11,906 | ✅ |
| 4 | CM Elevate applications | 8,840 | 8,840 | ✅ |
| 5 | CM Elevate file status "forward" | 8,864 | **8,837** | ⚠ see question 1 |
| 6 | CM Elevate on hold | 908 | **903** | ⚠ see question 1 |
| 7 | "Pending" CM Elevate applications | Explain it can't be read | "903 pending" (reads pending as On Hold) | ⚠ see question 2 |
| 8 | MGNREGA person-days FY2024-25 | 14,667,872 | 14,667,872 | ✅ |
| 9 | MGNREGA expenditure, crore | ₹3,628.67 Cr | ₹3,628.67 Cr | ✅ |
| 10 | MGNREGA job cards 2022–2026 | Refuse to sum | **Summed: 2,128,714** | ❌ ours |
| 11 | PMAY amount released, crore | ₹2,185.26 Cr | ₹2,185.26 Cr | ✅ |
| 12 | CMSS paid, and how much | 98,751 / ₹59.25 Cr | Wrong refusal | ❌ ours (1.4) |
| 13 | CMSS rejected | Explain reasons not recorded | Not tested (CMSS not served) | ❌ ours (1.4) |
| 14 | Home Stay Legacy sanctioned / disbursed | ₹118.46 Cr / ₹105.94 Cr | Pointed to CM Elevate Legacy | ❌ ours (1.4) |
| 15 | Focus+ disbursements FY2024-25 | "No data", not 0 | "No data is held for 2024-25" | ✅ |
| 16 | CM Elevate applications in Mawlai | Ask block or village | Asks block, constituency or village; block = 65 | ✅ |

**Row 10** is an old bug of ours (our KI-293, marked fixed on 14 October). It comes back when
the question is worded "from 2022 to 2026". It isn't caused by your changes, and we'll fix it.

---

## 3. Your four questions

**1. Which role and database does the chatbot connect with? Is `172.18.0.2` the chatbot?**
- Database `megh_db`, still as **`postgres`**, for the app's own queries *and* the
  model-written SQL. `READONLY_DATABASE_URL` is still not set, so the read-only pool falls back to the app login.
- What we see right now in `pg_stat_activity`:
  - `172.18.0.2`: 20 idle `postgres` sessions;
  - `10.48.242.2`: 4 idle;
  - our developer machine: 2.
- **`172.18.0.2` is very likely our Docker container** (inferred). On 16 October we lowered
  the pool minimum to 1 per worker, so 20 idle sessions suggests the container hasn't been
  restarted with that code. We'll check on the VM and reply.
- **Pool caps per worker** (in code): app pool max 30, read-only pool max 10, LangGraph store
  max 2. We'll lower the app pool cap when we switch roles.
- **To switch to `megh_readonly` we still need its password.** If you've already sent it,
  please tell us where. Once it's set, the chatbot refuses to run model SQL as a superuser.

**2. Prompt documents or vector index?**

Neither. The chatbot doesn't use `v_embedding_documents`, `v_prompt_bundles` or
`v_prompt_bundles_compact`. At each startup it reads these directly and puts a per-scheme
block into the SQL prompt:
- `table_catalog`, `column_catalog` (incl. `unit` and the `VALUES` lists), `glossary`,
  `metric_definitions` (all 62 load), `join_graph`, `v_join_rules`;
- `curated.v_data_coverage`.

So a restart picks up your changes, with no re-embed. Our vector index holds only scheme
reference documents, not database documents.

**3. Does it read the structure directly (`information_schema`)?**

Yes:
- **Columns:** the prompt lists every `curated` and `semantic` column from
  `information_schema.columns`, minus the three privacy tables and every column `megh_readonly`
  can't SELECT (we check `has_column_privilege` for that role).
- **Foreign keys:** come from `pg_constraint`.
- **Fact tables:** they appear in that column list, but their column notes are left out.

**4. Do we use `curated.v_focus_legacy_pg_search`?**

Yes. Focus Legacy producer-group name lookups search it, so old spellings and aliases match.

---

## 4. Questions for you

1. **"Forward" 8,864 and "on hold" 908 are record counts.** Counted as distinct `request_id`
   (your own rule for "applications") they are **8,837** and **903**, and the chatbot gives
   those. Which should the known-answer list use?
2. **"Pending" CM Elevate applications.** Our product owner decided on 16 October that a
   plain "pending" means `data_verified = 'On Hold'` (903). Your note says the chatbot should
   explain that Pending can't be read. We'd like to agree one rule before changing anything.
   Can we discuss this with you and the product owner?
3. **`region` puts Ri Bhoi under Khasi.** Our older examples treat Ri Bhoi as its own group.
   Is Garo / Khasi / Jaintia, with Ri Bhoi in Khasi, the official grouping we should use?
4. **The `megh_readonly` password**, please, through the usual secure channel.
5. **Could `semantic.column_catalog` carry a `subject_area`**, like `table_catalog` and
   `glossary` do? Then we could scope column notes by scheme exactly, instead of guessing from
   the table name, and new schemes would never leak into other schemes' prompts.
6. **New column names.** Adding `region` silently changed `GROUP BY region` in existing
   queries. When a future note adds columns, could it flag names that are likely to clash
   with common aliases (e.g. `region`, `year`, `total`, `status`)? Listing new columns, as
   this note did, is already a big help.

---

## 5. Status of your six requests

| # | Request | Status |
|---|---|---|
| 1 | Reload the documents | ✅ The catalog is read live at startup. Running servers need a restart to pick up these changes. We'll restart them after the fixes in section 1. |
| 2 | Connect as `megh_readonly`, cap the pool | ❌ Waiting for the password (question 4). |
| 3 | Fix rule literals that don't exist | See the table below. Only `member_id` is open. |
| 4 | Route to tested metrics | Partly: all 62 metrics are in the prompt as guidance. We don't yet run their SQL directly. |
| 5 | Use the lookups | `v_data_coverage`: ✅ used (missing years answer "no data"). `v_place_names`: not used; our own place resolver already asks for Mawlai. Group by LGD code: not yet. |
| 6 | Reject fan-out joins | ✅ Since 16 October our SQL checker rejects any join that `v_join_rules` forbids. |

**Request 3, item by item:**

| Rule literal | Chatbot today |
|---|---|
| CM Elevate `Pending` / `Send Back` | Never filtered on `current_file_status`. Send-back is matched with `LIKE 'sendback%'`. Approved / Rejected get the reply "not available". Pending: see question 2. |
| `Valid` as a status | Used only as a `data_verified` value. "On hold" uses `data_verified = 'On Hold'`; the `onhold` flag isn't used. |
| `scheme_code = 'FOCUS'` | Not used. Our prompt states there is no `FOCUS` code. |
| `meta.*` views | Nothing queries them. They appear only in reference YAML files, and examples that read them are dropped when they load. We'll tidy the YAML text. |
| `lgd_block` in `v_district_year_summary` | Not used. Our prompt states that view has no block column. |
| `v_focus_plus.member_id` | ❌ Still in 2 examples and our schema notes (section 1.1). |

---

## What we'll do next

1. Replace `member_id` with `member_key` (1.1) and fix the four `GROUP BY region` examples (1.2).
2. Keep CMSS / Home Stay Legacy / NRLM text out of the other schemes' prompts (1.3), and fix
   the two misleading replies (1.4).
3. Fix the job-card sum for "from 2022 to 2026" wording (row 10).
4. Switch to `megh_readonly` once we have the password, and restart the servers.
5. Re-run your known answers and send you the results.
