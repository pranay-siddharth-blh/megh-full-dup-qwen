# Focus Legacy Use-Case Test Report — 22 Oct 2026

**Scope:** the 28 use cases in `raw_uc/Use_Cases_-_Focus.csv` (TC-01 … TC-28, the "FOCUS" Producer Group scheme =
Focus Legacy), run live through the chatbot (LangGraph pipeline, real models, live `megh_db`). Every bot figure was
checked against the database, and the database was checked row by row against the raw file
`raw_uc/Focus Legacy to share to BLH.csv`. **No code, data or docs of the app were changed** — report and
recommendations only.

The raw file holds bank account numbers and account-holder names (KI-022). Those two columns were never read into
the comparison; only counts and sums appear here and in the CSV.

## 1. Summary

| Check | Result |
|---|---|
| Raw CSV vs DB: rows | **Match.** 14,569 rows in both, joined 1:1 on raw `id` = DB `source_row_id`; 0 missing, 0 extra |
| Raw CSV vs DB: every field (PG id, product, members, amount, remittance date, FY, bank, IFSC, district, block, village code, constituency) | **100% match** — 0 differences |
| Raw CSV vs DB: totals by state, FY, district (12), block (57), constituency (56), village (3,385), bank, month, product | **100% match** |
| Raw CSV vs DB: cosmetic only | Programme label "Focus (Addnl)" stored as `FOCUS_ADDNL` (706 rows); PG names — see §6 |
| Bot vs DB: sheet wording (each question exactly as the sheet words it, 3 fresh chats each) | **81 / 84** — 27 of 28 use cases 3/3; **TC-28 0/3** |
| Bot vs DB: full sweep (every district, block, constituency, FY format, 12 named groups, 24 villages) | **186 / 231** — all 45 failures are TC-28 (43) and the "FOCUS PG" wording (2) |
| Bot vs DB: the whole sheet as ONE chat, in order (twice) | 26 / 28 and 27 / 28 correct (see §4) |
| Use cases fully working | **25 of 28** |
| Use cases with a real failure | **3**: TC-28 (constituency — broken), TC-16 and TC-25 (fail when the user writes "FOCUS PG(s)") |
| Every village (3,384), on the fixed code | **3,363 / 3,384** (99.4%) — 19 of the 21 misses are KI-372, an unasked filter (§7) |

**Most important finding:** TC-28 (Producer Groups by constituency) passed **55 / 55** constituencies on the 12-13 Oct
code and passes only **12-15 / 55** today. The same is true of TC-16 / TC-25 with "FOCUS PG" (9/9 and 6/6 then, 3/9 and
0/3 now). This is a **regression** introduced between 13 Oct (`e59b5ba`) and the 21 Oct commit (`9726b86`), i.e. in the
17-20 Oct changes (`71fef0f` "RAG upgrade, NL->SQL eval set, pipeline package, sqlglot-only SQL handling" and
`e172414`). It is **not** caused by today's uncommitted changes — HEAD fails the same way (§5).

## 2. Result per use case

Sweep = the sheet question with "FOCUS" in it, over every place / year / named group. Literal = the sheet's exact
wording, placeholders filled (East Khasi Hills, West Garo Hills, Ri Bhoi, Lamchaphrang PG, Mawkyrwat, FY 2024-25),
3 fresh chats. A question with no year draws "which financial year?" — the test tapped "All financial years combined".
"FOCUS" alone draws "Focus Plus or Focus Legacy?" — the test tapped Focus Legacy (correct: CLAUDE.md rule, never guess).

| TC | Use case | Sweep | Literal | Verdict | DB figure (all years) |
|---|---|---|---|---|---|
| 01 | What is FOCUS | 1/1 | 3/3 | **Pass** | knowledge (RAG) |
| 02 | Objective | 1/1 | 3/3 | **Pass** | knowledge |
| 03 | Eligibility | 1/1 | 3/3 | **Pass** | knowledge (₹5,000 per member) |
| 04 | Role of Producer Groups | 1/1 | 3/3 | **Pass** | knowledge |
| 05 | Financial assistance | 1/1 | 3/3 | **Pass** | knowledge |
| 06 | Support to PGs | 1/1 | 3/3 | **Pass** | knowledge |
| 07 | Fund distribution | 1/1 | 3/3 | **Pass** | knowledge (DBT to member accounts) |
| 08 | PGs covered | 1/1 | 3/3 | **Pass** | 11,906 groups |
| 09 | Briefing overview | 1/1 | 3/3 | **Pass** | knowledge |
| 10 | Total beneficiaries | 1/1 | 3/3 | **Pass** | 102,021 memberships; 11,906 groups; 14,569 payments; ₹51.01 crore |
| 11 | Unique PGs | 1/1 | 3/3 | **Pass** | 11,906 |
| 12 | Duplicate PGs | 1/1 | 3/3 | **Pass** | no true duplicates (no group paid twice on one date); 2,655 groups paid more than once (2,663 repeat payments) |
| 13 | Search "Nongstoin PG" | 1/1 | 3/3 | **Pass** | no group of that name ("No producer group named …") |
| 14 | Members in a named PG | 12/12 | 3/3 | **Pass** | e.g. Lamchaphrang: size 10 (14 memberships over 2 payments — the bot explains both) |
| 15 | Top N PGs with > M members | 2/2 | 3/3 | **Pass** | only **one** group has > 20 members (Nongprat Lynti, 190); the next largest have 20 — so "top 5" correctly lists 1 |
| 16 | Total PG members | **0/1** | 3/3 | **Fail with "FOCUS PG"** — defect 2 | 102,021 |
| 17 | PG members in a district | 12/12 | 3/3 | **Pass** | East Khasi Hills 10,841 |
| 18 | Amount disbursed for a district | 12/12 | 3/3 | **Pass** | West Garo Hills ₹10.93 crore |
| 19 | PGs above an amount | 2/2 | 3/3 | **Pass** | > ₹5 lakh: 1 group (Nongprat Lynti ₹10.05 lakh) |
| 20 | Remittances in a date range | 3/3 | 3/3 | **Pass** | Apr-Jun 2025: 5,106 payments, ₹9.54 crore |
| 21 | Monthly remittance in an FY | 4/4 | 3/3 | **Pass** | FY 2024-25: all in October 2024, ₹11.50 crore |
| 22 | Records per FY | 1/1 | 3/3 | **Pass** | 2021-22: 965 · 2022-23: 2,139 · 2024-25: 2,653 · 2025-26: 8,812 |
| 23 | Total remitted in an FY | 17/17 | 3/3 | **Pass** (4 FYs × 4 formats + "FY 2023-24 has no data") | FY 2024-25 ₹11.50 crore |
| 24 | Compare two FYs | 4/4 | 3/3 | **Pass** (note §4.3) | 2023-24 has no payments |
| 25 | PGs per district | **0/1** | 3/3 | **Fail with "FOCUS Producer Groups"** — defect 2 | WGH 2,701 … (12 districts) |
| 26 | PGs per block in a district | 68/68 | 3/3 | **Pass** (12 district splits + all 56 blocks alone) | Ri Bhoi: Umsning 380, Umling 251, … (+6 with no block) |
| 27 | PGs mapped to a village | 24/24 | 3/3 | **Pass** (2 villages per district) | Mawkyrwat village: 1 group |
| 28 | PGs mapped to a constituency | **12/55** | **0/3** | **Fail** — defect 1 | Mawkyrwat 311, Amlarem 204, Dalu 203, … |

## 3. Defects found (bot)

| # | Severity | Use case | Problem | Reproduces |
|---|---|---|---|---|
| 1 | **High** | TC-28 | **Constituency questions are broken.** 43 of 55 constituencies fail, in two ways: **(a)** "I understood the question but couldn't build a working query" (29-34 of 55), or **(b) a wrong number**: the SQL filters the constituency's *district* instead of the constituency — Dalu answered **928** (= all of East Garo Hills) for a true **203**; Mawsynram 909 (= East Khasi Hills) for 137; North Tura 2,701 (= West Garo Hills) for 159; Selsella / Ranikor / Mawshynrut 928; or **0** (Umroi, Bajengdoba, Dadenggre, Rajabala, Rangsakona, Gambegre, Umsning, Rongara-Siju, Mahendraganj — true
134-437). In a chat after a district question it answered "288 … Mawkyrwat constituency" = East Khasi Hills FY 2021-22 | 43/55 sweep, 3/3 sheet wording, 2/2 in chat |
| 2 | **High** | TC-16, TC-25 (any question saying "FOCUS PG(s)" / "FOCUS Producer Groups") | The model adds `WHERE pg_entity_type = 'FOCUS_PG'` — it reads the scheme name as the group-type code — and drops the LAMP / EXISTING groups: "FOCUS PG members" **94,766** for a true **102,021**; "FOCUS Producer Groups by district" West Garo Hills **2,240** for **2,701**, North Garo Hills 968 for 1,173, etc. The same question without "FOCUS" (the sheet's wording) is right 3/3 | 3/3 and 3/3 |
| 3 | Medium | TC-16 in a chat | After TC-15 in the same chat, "What is the total number of PG members recorded till now?" was rewritten "How many PG members have been recorded so far?" and answered **"11,906 PG members"** — the SQL counted groups (`COUNT(DISTINCT pg_id)`) and the answer labelled it members. True 102,021. No check caught the label | 1 of 2 chats (fresh chat 3/3 correct) |

### Root causes (VERIFIED by trace and A/B, not changed)

**Defect 1.** Traced live ("How many Focus Producer Groups are mapped to Amlarem / Dalu constituency …"):
1. Entity resolution is right: `assembly_constituency = 'AMLAREM'` (log: "explicit level 'assembly_constituency' — placed 'AMLAREM'").
2. The SQL model writes the documented, correct query —
   `v_focus_legacy f JOIN curated.dim_geography g ON g.geography_key = f.geography_key WHERE g.ac_name = 'AMLAREM'`.
3. The **semantic verifier** (since 15 Oct the 30B coder, run after execution — `prompt_builder` / `c11_sql_verify_repair`)
   then rejects it, each attempt, with one of two false reasons:
   - "**prohibited join path** — v_focus_legacy must not be joined with dim_geography". Wrong: the prohibited rule is
     "never join `fact_focus_legacy_disbursement` (privacy table) — use `v_focus_legacy`"; the
     `geography_key → dim_geography` join is the documented constituency route (`_AC_CAPABLE_SCHEMES`,
     `focuslegacy_foreign_key_augmentation.yaml`, few-shot lines 1021-1041);
   - "the value must be compared with `UPPER(g.ac_name) = UPPER('AMLAREM')`" — partly right: `dim_geography.ac_name` is
     stored **Title Case** ("Amlarem"), so `g.ac_name = 'AMLAREM'` really does return 0 when it slips through.
4. The repair loop "fixes" the false join complaint by **removing the join** — and then filters on the constituency's
   district (wrong number) or fails 4 times ("couldn't build a working query").

On the 13 Oct code the generator wrote `UPPER(g.ac_name) = UPPER('AMLAREM')` and the verifier passed it — 55/55.

**Defect 2.** Since 17 Oct the SQL prompt carries each column's exact **values list** from the semantic catalogue
(`schema_introspect`: "column_catalog incl. unit and the exact VALUES lists"), so the model now knows the code
`FOCUS_PG` and maps "FOCUS PG" onto it. The guard written for exactly this mistake
(`_focus_legacy_scheme_name_not_variant`, `app/pipeline/schemes/focus_legacy.py:1554`, from the 12 Oct all-villages run)
only strips the value `'focus'` (`_fl_equals_focus`, line 1463) — it does not recognise `'FOCUS_PG'`.

**Defect 3.** The follow-up rewrite kept the meaning; the SQL model chose the group count, and neither the
verifier nor the composer checks that a "members" question is answered with `no_of_pg_members`.

## 4. Behaviour to note (not counted as failures)

1. **The bot asks first.** "FOCUS" alone → "Focus Plus or Focus Legacy?" (by design — never guess a bare "Focus").
   A question with no year → "which financial year?" (new-chat context rule). A name that is both a block and a
   constituency (e.g. Mawsynram, Jowai, Songsak) → "the block or the constituency?", then "the whole constituency or the
   block part?" — two questions before the answer; the second is redundant once "constituency" was chosen.
2. **A chat keeps its place.** Asking the sheet in order in one chat, TC-18 ("… for West Garo Hills") sets the place,
   and TC-19-23 ("Which PGs received more than ₹5 lakh?", "remittances April-June 2025", "each month of FY 2024-25",
   "records per FY", "total in FY 2024-25") are answered **for West Garo Hills** and say so. All five figures are correct
   for West Garo Hills (0 groups; ₹4.61 crore; Oct 2024 ₹3.30 crore; 55 / 382 / 825 / 2,231; ₹3.30 crore). This is the
   chat context rule; a tester who expects statewide figures there must say "in Meghalaya" or start a new chat.
3. **TC-24 FY 2023-24 has no payments.** "Compare FY 2023-24 and FY 2024-25" answers "FY 2023-24 holds no data, so
   FY 2022-23 — the nearest year that does — is compared instead". Correct and stated, but the sheet expects the bot to
   say 2023-24 = nil; confirm with the client which they want.
4. **"Members" = memberships paid for, not people.** `SUM(no_of_pg_members)` counts a group's members once per
   payment (102,021); a group paid twice is counted twice. The bot says so in every answer. Lamchaphrang: recorded size
   10, 14 memberships over 2 payments.
5. **TC-12 "duplicates".** The bot reads it as "the same group paid twice on the same date" (none) and also gives the
   2,655 groups paid in more than one tranche. Reasonable; agree the definition with the client.
6. **TC-15.** Only one group in the whole data has more than 20 members (190); 548 groups have exactly 20. "Top 5 with
   more than 20" therefore lists 1 — correct, but a tester may read it as a failure.
7. Response time (sweep, 3 parallel chats): median 3.4 s per turn, 90th percentile 9.0 s; a failing constituency
   question takes a median 12 s (4 verifier rejections before giving up).

## 5. Regression check — the same 70 questions on three code versions

TC-28 (all 55 constituencies), TC-16 ×9 and TC-25 ×6, run on a temporary git worktree of each version (no change to
the working copy):

| Code | TC-28 constituencies | TC-16 "FOCUS PG members" (3 wordings × 3) | TC-25 by district (2 wordings × 3) |
|---|---|---|---|
| 13 Oct, `e59b5ba` | **55 / 55** | **9 / 9** | **6 / 6** |
| 21 Oct, HEAD `9726b86` | 11 / 55 | 4 / 9 | 3 / 6 |
| Working copy (22 Oct, uncommitted) | 15 / 55 | 5 / 9 | 3 / 6 |

On 13 Oct every failing wording passed. The regression is in the committed 17-20 Oct work, not today's edits.

## 6. Raw data vs database

| Level | Units | Differences |
|---|---|---|
| Rows (raw `id` = DB `source_row_id`) | 14,569 | 0 missing, 0 extra, 0 duplicate ids |
| Field by field (12 fields) | 14,569 × 12 | **0** |
| State / FY (4) / district (12) / block (57) / constituency (56) / village (3,385) / bank (14) / month (15) / product (46) — payments, amount, members, distinct groups | 3,590 units | **0** |
| Programme label | 2 | label only: "Focus (Addnl)" → `FOCUS_ADDNL` (706 payments, ₹1.84 crore) |
| PG name | 1,636 payments | The raw file spells 1,634 groups differently on their own payments ("BAK 15 BANANA" / "BAK-15 BANANA PG 40/2020", "MOJURLANG" / "MONJURLANG"); the DB keeps **one** name per `pg_id`. Not an error, but a search by a name spelling that only the raw file has (TC-13 / TC-14) will not find it |

Data facts the tester should know: amount = members × ₹5,000 on **every** row (14,569 / 14,569); **FY 2023-24 has no
payments**; 171 payments have no remittance date (date-range answers TC-20 / 21 exclude them, FY answers include them);
1,101 payments have no village (no constituency) — they count in district and block totals but not in any
constituency or village; 276 payments have no bank name.

Statewide figures (raw = DB = bot):

| Measure | Value |
|---|---|
| Producer Groups / payments / memberships | 11,906 / 14,569 / 102,021 |
| Amount | ₹51.01 crore (₹510,105,000) |
| FY 2021-22 · 2022-23 · 2024-25 · 2025-26 | ₹6.82 · ₹14.18 · ₹11.50 · ₹18.51 crore (965 · 2,139 · 2,653 · 8,812 payments) |
| Highest district | West Garo Hills — 2,701 groups, ₹10.93 crore |
| Banks | Meghalaya Rural Bank ₹29.29 crore · Meghalaya Co-operative Apex Bank ₹16.21 crore · SBI ₹1.57 crore |

## 7. Every village (3,384)

`tests/sheet_runs/fl_all.py` (unchanged): one question per village — alternately "How many Producer Groups are mapped
to <village> village?" (TC-27) and "What is the total amount disbursed for <village>?" (TC-18), the name in UPPER /
Title / lower case. Run on the **fixed** code (a first run had started on the old code and was discarded).

**Result: 3,363 / 3,384 (99.4%)** — TC-27 (group counts) 1,691 / 1,692, TC-18 (amounts) 1,672 / 1,692. On 12 Oct the
full run was 3,384 / 3,384. None of the 21 is a constituency or "FOCUS PG" case. All but two are one new defect,
**KI-372: the model adds a filter nobody asked for** to a single-village money question, and the village then shows no
figure ("the data available doesn't cover …"):

| Invented filter | Villages | Example (true figure) |
|---|---|---|
| `pg_id = 'PG-FOCUS-WKH-7089'` / `'PG-FOCUS-WGH-7089'` — the example id written in `data/focus_legacy/focuslegacy_entity_resolver.yaml` and `focuslegacy_classification_rules.yaml` | 13 | Kyrdem ₹7.75 lakh, Dawa Nengkatok ₹2.65 lakh |
| another invented `pg_id` (`'PG-FOCUS-IEWRYNGHEP'`, `ILIKE 'PG-LAMP-%'`) | 3 | Iewrynghep ₹5.70 lakh, Lamjew ₹45,000 |
| `programme_variant = 'FOCUS_ADDNL'` | 2 | Line Ading ₹4.95 lakh, Garamgre ₹10,000 |
| `pg_entity_type_name = 'LAMPS cooperative'` | 1 | Rajpur (Muslim) ₹20,000 |
| `financial_year_short IN ('2021-22','2022-23')` for "across all financial years" | 1 | Santogre ₹40,000 |
| other | 2 | "Mawkohmit & Mawkynsah" read as TWO villages (277073 + 277074): 11 groups for 6; Nongthymmai — a year pause the test script could not answer (test-side) |

Root cause (INFERRED, same family as KI-370): since 17 Oct the SQL prompt carries the catalogue's values and the
resolver YAML's example id, and the 30B copies one into the WHERE clause. The verifier did not catch any of them.

Suggested fix (not made — outside the requested fixes): a Focus Legacy guard in `_execute_one_attempt` — a `pg_id`,
`programme_variant`, group-type or year filter the question does not ask for (no PG id / variant / type / year word in
the question, no resolved year) goes back to repair; plus a check that a village name containing "&" resolves to the
one village of that full name.

## 8. Suggested fixes (NOT made — awaiting your go-ahead)

Following the project pattern (prompt rule → few-shot → **deterministic guard**):

1. **Defect 1 — verifier false "prohibited join"** (`c11_sql_verify_repair.py`, `execute_with_repair`): when the only
   join is `<scheme view> JOIN curated.dim_geography ON geography_key` for an `_AC_CAPABLE_SCHEMES` scheme and the
   resolved entity is a constituency, overrule a verifier "prohibited join" flag (SQLGlot check of the join, no regex).
   Also say it in the verifier prompt / prohibited-joins text: "v_focus_legacy → dim_geography on geography_key is the
   allowed constituency route; the prohibited table is fact_focus_legacy_disbursement".
2. **Defect 1 — case of `ac_name`**: a SQLGlot rewrite, like `_uppercase_geo_literals`, turning
   `g.ac_name = 'X'` / `IN (…)` into `UPPER(g.ac_name) = UPPER('X')` (dim_geography stores Title Case).
3. **Defect 1 — place drift guard**: if the resolved entity is an assembly constituency and the final SQL has no
   `ac_name` filter but filters `lgd_district` / `lgd_block`, send it back to repair (never answer the district's figure
   as the constituency's). This would have turned all the wrong numbers into a retry.
4. **Defect 2**: `_fl_equals_focus` (`focus_legacy.py:1463`) — also treat `'FOCUS_PG'` (and `'PG-FOCUS'`), any case, as
   the scheme name, and drop it when it is the **only** WHERE condition too, unless the question asks about group type
   (`_FL_GROUP_TYPE_ASKED`). Regression test on the real function with the two SQLs above.
5. **Defect 3**: guard — a Focus Legacy question about "members" whose SQL returns only `COUNT(DISTINCT pg_id)` (no
   `no_of_pg_members`) goes to repair.
6. **Process**: TC-28 regressed silently. Add the 55-constituency check (`ac_ab.py`-style, or `fl_run.py TC-28`) to the
   live checks run after any change to the verifier, the prompt catalogue or SQL rewrites; and check CM Elevate Legacy
   and CM Elevate constituency questions, which use the same join and verifier (INFERRED risk, not tested here).
7. Test note: confirm with the client the TC-12 definition of "duplicate" and the TC-24 behaviour for FY 2023-24.

## 9. How this was run

- Live, in-process, with the repo venv and the VPN; LangGraph pipeline; pauses answered as a chip tap.
- `tests/sheet_runs/fl_run.py` (sweep, unchanged); scratchpad `literal.py` (sheet wording × 3, plus the whole sheet as
  one chat × 2); `ac_ab.py` (A/B on three code versions via temporary git worktrees); `fl_raw_vs_db.py` (raw vs DB,
  read-only, counts and sums only); `tests/sheet_runs/trace.py` for the root-cause traces.
- Every conversation, with the bot's answer, SQL and the DB figure: `new_docs/Focus_Legacy_all_conversations_2026-10-22.csv`.

## 10. Fixes made after the report (22 Oct, on request: "fix all these, don't change any other")

Focus Legacy only — every new check returns early for any other scheme. Code: `app/pipeline/schemes/focus_legacy.py`
(the logic) and three call sites in `app/pipeline/common/c11_sql_verify_repair.py`. Tests:
`tests/test_focus_legacy_sheet_run_2026_10_22.py` (32, real functions). Issues: KI-369, KI-370, KI-371.

| Defect | What changed |
|---|---|
| 1 — TC-28 constituency (KI-369) | (a) the verifier's "prohibited join" / "resolved entity" / "use UPPER()" complaint is discarded when the SQL is the documented constituency query (only `v_focus_legacy` + `dim_geography`, joined on `geography_key`, `ac_name` = the resolved constituency); a measure or grain complaint still stands. (b) A resolved constituency the SQL does not filter on `ac_name` is sent back to repair — never answered with the district's figure. (c) `ac_name = 'X'` is rewritten `UPPER(ac_name) = 'X'` (dim_geography stores Title Case) |
| 2 — "FOCUS PG" (KI-370) | `pg_entity_type = 'FOCUS_PG'` (or its display name) is dropped, also when it is the only condition, unless the question asks about group type / LAMPS / existing / newly formed / cooperatives |
| 3 — members as groups (KI-371) | A "members" question whose SQL only counts groups goes back to repair. Found while re-testing: the verifier also rejected the correct `SUM(no_of_pg_members)` as "not aggregated" on every attempt in 5 of 9 asks — that complaint is discarded when the SQL SUMs exactly that column |

Live, on the fixed code (same scripts as §9):

| Check | Before | After |
|---|---|---|
| TC-28, all 55 constituencies | 12-15 / 55 | **55 / 55** |
| TC-16 "PG members", 3 wordings × 3 | 4-5 / 9 | **9 / 9** |
| TC-25 "PGs per district", 2 wordings × 3 | 3 / 6 | **6 / 6** |
| Full sweep, all 28 use cases | 186 / 231 | **231 / 231** |
| Sheet wording × 3 | 81 / 84 | **84 / 84** |
| One chat, sheet order (× 2) | TC-16 wrong in 1, TC-28 wrong in both | TC-16 and TC-28 right in both; TC-19-23 answered for the carried district (correct figures, §4.2) |
| pytest (documented command) / 14 scripts | — | **3,416 passed, 0 failed** / **14 / 14** |

**Use cases fully working now: 28 of 28.**

New finding, not fixed (outside the requested fixes): **KI-372** — on village questions the model sometimes adds a
filter nobody asked for, taken from the catalogue's value lists: `financial_year_short IN ('2021-22','2022-23')` for
"across all financial years" (Santogre: no figure instead of ₹40,000) or `programme_variant = 'FOCUS_ADDNL'` (Line
Ading: no figure instead of ₹4.95 lakh). Same family as KI-370. The every-village result is in §7.

Also found: `CLAUDE.md` §5 says the 4B model is the SQL verifier; the code (`app/config.py`
`SQL_VERIFY_MODEL = "qwen-model"`) uses the 30B since 15 Oct. `docs/AI_PIPELINE.md` corrected; `CLAUDE.md` left for you.
