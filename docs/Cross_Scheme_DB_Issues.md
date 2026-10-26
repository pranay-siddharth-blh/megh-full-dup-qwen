# Cross-Scheme UAT — Database Issues for the Data Team

**Date:** 2026-10-22
**For:** megh-ingestion (owners of `megh_db.curated` and `megh_db.semantic`)
**Test:** the 60 cross-scheme UAT cases in `raw_uc/cross_scheme.xlsx` (MGNREGA, PMAY-G, Focus+, FOCUS / Focus Legacy)
**Raw sources compared:** `MGNREGA_Employment.xlsx`, `Updated MNGREGA Expenditure WIth Year.xlsx`,
`PMAY_FullyMapped_with_dates.xlsx`, `Focus Plus Master.csv`, `Focus Legacy to share to BLH.csv` (aggregated only;
no row of a raw file is reproduced here)
**Full reports:** `new_docs/Cross_Scheme_Test_Report_2026-10-22.md`, `new_docs/Cross_Scheme_all_queries_after_fix_2026-10-22.csv`

## Summary

After the chatbot fixes of 22 Oct (D-066), **every figure in 59 of the 60 answers equals the DB**. Against the raw
files, **47 / 60** match. The 12 cases that are right by the DB but wrong by the raw file come from two mapping
differences in the data load (issues 1 and 2). Four more items are gaps in the semantic catalogue (issues 3–6); the
bot now works around them in code, but other tools that read the catalogue will still be misled.

We compared 459 figures (4 schemes × state / 12 districts / 3 blocks / FY 2025-26 × each measure) between the raw
files and the DB: **411 equal, 48 differ**. Every difference is explained below.

| # | Issue | Scheme | Records | UAT cases affected | Type |
|---|---|---|---|---|---|
| 1 | Genapara village placed in a different district / block than the source | MGNREGA | 4 rows, 445 household-years | T07.1, T15.1, T15.2, T17.1, T17.3, T18.1 | Data mapping |
| 2 | Focus+ village codes and districts differ from the source | Focus Plus | 57,649 unmapped rows; 175 rows swap district | T09.1, T09.2, T13.1, T13.2, T20.1, T20.2 | Data mapping |
| 3 | PMAY-G money metrics have no default | PMAY-G | catalogue | T12.1, T12.3, T19.1, T20.3 (before the fix) | Catalogue |
| 4 | Focus Legacy has no members or villages metric | Focus Legacy | catalogue | T01.3, T16.1, T18.3, T19.2 (before the fix) | Catalogue |
| 5 | "Unresolved" rows: the rule does not say they stay in money / member totals | Focus Legacy, Focus Plus (+ others) | 1,101 FL rows, 57,649 FP rows | T20.1 (before the fix) | Catalogue |
| 6 | "coverage" is a synonym of the glossary term "no data versus zero" | shared | catalogue | T09.2 (before the fix) | Catalogue |

What matches the raw files exactly: **PMAY-G** (1,71,107 houses, 1,29,941 completed, 5,121 villages, ₹2,222.75 Cr
sanctioned, ₹2,185.26 Cr released, every district) and **Focus Legacy** (1,02,021 members, 11,906 PGs, 14,569
remittances, ₹51.01 Cr, 3,384 villages, every district and FY). The 126 PMAY-G houses with no sanction date, reported
on 15 Oct, are now counted.

---

## Issue 1 — MGNREGA: Genapara is in West Garo Hills in the DB, South West Garo Hills in the source

**What is wrong.** Village **GENAPARA (LGD 274268)** has 4 rows in `curated.v_employment`, with **445 household-years**
in total:

| Column | Value in the DB |
|---|---|
| `lgd_district` / `lgd_block` | WEST GARO HILLS / DALU |
| `district_name_raw` / `block_name_raw` | SOUTH WEST GARO HILLS / PURAKHASIA |

The source file has it in South West Garo Hills / Purakhasia; the LGD master has it in West Garo Hills / Dalu. These
are the only MGNREGA employment rows whose source district differs from the LGD district.

**Effect.** MGNREGA households, West Garo Hills: **2,61,666** in the DB vs 2,61,221 in the source. South West Garo
Hills: **1,64,976** vs 1,65,421. Villages: 978 vs 977 and 542 vs 543. Any district total or ranking that includes
MGNREGA carries the same 445 difference (e.g. combined beneficiaries, West Garo Hills: 3,51,739 vs 3,51,294). No
conclusion in the UAT changes. Expenditure is not affected.

**Check:**
```sql
SELECT village_code, lgd_village_name, lgd_block, lgd_district, block_name_raw, district_name_raw,
       SUM(households_employed)
FROM curated.v_employment WHERE village_code = 274268 GROUP BY 1,2,3,4,5,6;
```

**Asked of the data team:** confirm which is right for Genapara, the LGD master or the source. If the LGD master is
out of date (Purakhasia is in South West Garo Hills), refresh `shared/data/geography.xlsx` and reload; that fixes
every scheme at once.

---

## Issue 2 — Focus Plus: village codes and districts differ from the source

**2a. Village codes.** The source file carries an LGD village code on about 73% of its rows; the DB also places rows
that gave only a village name. As a result the DB has more distinct villages than the source:

| | Raw file (distinct LGD codes) | DB (`village_code > 0`, not Unresolved) |
|---|---|---|
| Meghalaya | 3,220 | **3,513** (3,456 villages + 57 wards) |
| Mylliem block | 27 | 48 |
| Dadenggiri block | 80 | 130 |

57,649 Focus+ rows (₹18.01 Cr) remain `entity_type = 'Unresolved'` (no village).

In **T09.2** this changes the conclusion. "Widest coverage in Dadenggiri block" comes out as Focus Plus (130 villages)
over MGNREGA (103) by the DB; by the source file it is MGNREGA (Focus+ 80).

**2b. District / block.** 175 rows have a source district that differs from the LGD district:

| Source district (`district_name_raw`) | LGD district (`lgd_district`) | Rows | Distinct beneficiaries |
|---|---|---|---|
| WEST GARO HILLS | SOUTH WEST GARO HILLS | 144 | 51 |
| SOUTH WEST GARO HILLS | WEST GARO HILLS | 31 | 31 |

So by LGD district: West Garo Hills **35,039** (source 35,059), South West Garo Hills **15,294** (source 15,274), with
₹39.13 / 16.68 Cr (source ₹39.16 / 16.64 Cr). 109,192 rows also have a source block name that differs from the LGD
block (38 source names vs 43 LGD blocks). The source uses older, pre-split block names; the LGD master has the newer
blocks (Batabari, Demdema, Adokgre …) and urban wards. Distinct block count: 51 by source name vs 59 by LGD.

**What the chatbot does now.** It groups Focus Plus by the source names (`district_name_raw` / `block_name_raw`), as
the Focus+ catalogue notes say ("lead with the source value"), so its district figures equal the source file. Every
other scheme is grouped by LGD. The two rules differ, so a cross-scheme district table mixes two geographies.

**Asked of the data team:**
1. Decide, with the client, **one geography rule for every scheme**: LGD master by default, or the source value. The
   catalogue notes disagree today: Focus+ / Focus Legacy say "lead with the source value"; MGNREGA / CM Elevate say
   "lead with the LGD master". Tell us the decision and we will change the bot to match.
2. Confirm the LGD master is current. In several villages the source uses a newer block than the master.
3. For the UAT sheet: record the village-count differences as expected (both values), not as failures, unless the
   village codes are reloaded from the source.

---

## Issue 3 — PMAY-G: no default between "released" and "sanctioned"

`semantic.metric_definitions` has `pmay_amount_released` ("Total amount actually disbursed…") and
`pmay_amount_sanctioned` side by side, with nothing saying which one a money question means. The bot gave ₹2,222.75 Cr
(sanctioned) as PMAY-G's "financial assistance" in four UAT answers; the expected figure is ₹2,185.26 Cr (released).

**Asked:** on `pmay_amount_released` add "the default for any money / spending / assistance question"; on
`pmay_amount_sanctioned` add "only when the question says sanctioned".

## Issue 4 — Focus Legacy: no members metric, no villages-covered metric

Focus Legacy has only `focus_legacy_pg_count` and `focus_legacy_total_disbursed`. There is **no members metric**
(`SUM(no_of_pg_members)`, 1,02,021) with "beneficiaries" as a synonym. There is also **no villages-covered metric**
(3,384), although MGNREGA, PMAY-G, Focus+ and CM Elevate each have one. The column `no_of_pg_members` carries no
description. Before the fix the bot counted FOCUS producer groups as its "beneficiaries" (T16.1, T18.3) and dropped
FOCUS from coverage answers.

**Asked:** add `focus_legacy_members` (`SUM(no_of_pg_members)`, synonyms "beneficiaries", "members") and
`focus_legacy_villages_covered` (`COUNT(DISTINCT village_code)`, excluding Unresolved). Add a description on
`v_focus_legacy.no_of_pg_members`.

## Issue 5 — "Unresolved" rows: the rule must say they stay in every total

1,101 Focus Legacy rows (7,905 members, ₹3.95 Cr) and 57,649 Focus Plus rows (₹18.01 Cr) are `entity_type =
'Unresolved'`: real payments with a district / block but no village. In T20.1 the bot dropped them from every column
and showed FOCUS as 94,116 members / ₹47.06 Cr instead of 1,02,021 / ₹51.01 Cr. The catalogue says to exclude them
from village counts, but does not say they must stay in money / member / beneficiary totals.

Also, `focus_plus_villages_covered` and `pmay_villages_covered` have an empty `filters_required`, while
`cm_elevate_villages_covered` says "Must exclude Unresolved placeholder rows".

**Asked:**
- Reword the `entity_type` note and the view descriptions on every affected view to: "Exclude Unresolved rows from
  village counts and village lists ONLY. They are real payments / members and MUST stay in every money, member,
  beneficiary and row total, state and district."
- Give `focus_plus_villages_covered` and `pmay_villages_covered` the same "exclude Unresolved" filter.

## Issue 6 — "coverage" is a synonym of "no data versus zero"

The glossary term **"no data versus zero"** (maps to `curated.v_data_coverage.years_present`) lists "coverage" among
its synonyms. A question like "coverage of NREGA, PMAY-G and Focus+ in Dadenggiri block" (village coverage) can
therefore retrieve the data-years document instead.

**Asked:** replace the plain synonym "coverage" with "data coverage" and "years covered".

---

## After any catalogue change

Run `refresh_catalog()` → seed → `propagate_column_metadata()`, and tell the chatbot team. We re-embed
`semantic.v_embedding_documents` / reload `semantic.v_prompt_bundles` to pick the changes up.

*All figures above were read from the live `megh_db` on 2026-10-22 with read-only queries; nothing was changed in
`curated` or `semantic`.*
