# CMSS Annotation Layer — How the YAMLs Are Built

This folder holds the hand-curated annotation layer for **CMSS**, the **Chief Minister's
Scholarship Scheme** (Education Department, Government of Meghalaya; implemented by the
Directorate of Higher and Technical Education, DHTE), for the Megh One AI NLP-to-SQL bot.
Everything here is derived from the inputs in `datasets/CMSS/` and the live database structure
in `SCHEMA_FOR_DEVELOPERS.md`. Nothing in this folder is generated at runtime. These files are
the reviewed, SME-owned contract that the retrieval and SQL-generation stages read.

> **Status, 2026-11-04: all 7 YAMLs built (v1.0), 7,157 lines, every file parsing clean.**
> All 176 SQL statements are read-only `SELECT`s. The gate and the defaults share no condition.
> Every figure was computed from the CSV, and every SQL that reads only `v_cmss` was executed
> against an emulation built from it. What remains is verification against the live database,
> not authoring (§10), plus one cross-folder job: the `MASTER/schemes_catalog.yaml` entry.

It is a sibling of `Annotations/PMAY/README.md` (the structural template) and
`Annotations/NRLM/README.md` (the model for a newly onboarded scheme). Read those for the general
method. This one records what is different about CMSS, which comes down to six things:

1. **One row is one student application, paid or not.** `COUNT(*)` counts applications.
   Students paid is `COUNT(*) FILTER (WHERE is_disbursed)`. Every `member_id` appears once, so in
   this file applications = students (§4.2).
2. **The money is a flat ₹6,000.** Every paid application holds exactly ₹6,000, so an amount
   question is a paid-count question multiplied by 6,000. Averages, maxima and minima are all ₹6,000.
3. **Unpaid has no reason, status or date.** 6,076 applications are unpaid, and nothing says
   whether they were rejected, defective, pending or not yet processed (CM-02, CM-22).
4. **One financial year only.** Every row is 2025-26. Trends and year comparisons are not
   possible yet, and the academic year is not the financial year (CM-21).
5. **Gender and institution type were removed from the file.** Thirteen of the 41 use cases
   ask for them and must be refused (CM-03, CM-04, CM-05, CM-15; §6).
6. **Towns are reported as blocks.** 11 municipal boards and town committees sit in the block
   column (CM-08), and urban wards sit in the village column (CM-13). The geography is the
   **student's home address**, not the institution (CM-20).

---

## 1. What is in this folder

| File | Layer | Answers the question | Status |
|---|---|---|---|
| `cmss_schema_partitions.yaml` | **Semantic schema** (*stage2*) | *What columns exist, what do they mean, how are they aggregated?* | **v1.0 built** — 19 view columns, 40 few-shot (14 refusals) |
| `cmss_classification_rules.yaml` | **Clarification gate** | *Is the question answerable as asked, or must the bot ask or refuse first?* | **v1.0 built** — 68 rules + 45 worked examples |
| `cmss_default_rules.yaml` | **Defaults** | *What is assumed when the user does not say, and stated back?* | **v1.0 built** — 65 rules + 25 worked examples |
| `cmss_entity_resolver.yaml` | **Entity resolver** | *The user typed "EKH", "Tura", "Shillong MB", "unpaid": which stored value is that?* | **v1.0 built** — 12 districts, 67 blocks (11 towns), 60 constituencies, 231-name village registry, 31 worked examples |
| `cmss_few_shot.yaml` | **Worked examples** | *Validated question-to-SQL pairs* | **v1.0 built** — 95 pairs, 93 with an executed `expected` |
| `cmss_foreign_key_augmentation.yaml` | **Join graph** | *Which joins are allowed, and which are prohibited* | **v1.0 built** — 25 nodes, 28 edges (4 declared, 19 prohibited, 4 patterns), 14 worked join decisions |
| `cmss_response_template.yaml` | **Response shaping** | *How a number is phrased, and which caveats travel with it* | **v1.0 built** — 77 templates (16 refusals), 31 follow-ups, 16 composer checks, 20 rendered answers |
| `README.md` | This guide | *How the layer is built and what must never change* | written 2026-11-04 |

Pipeline position, the same as for PMAY:

```
user question
   |
   v
[ clarification gate ] <-- cmss_classification_rules.yaml
   |  "male and female students", "by institution type", "why was I not paid" -> refuse with an offer
   v
[ defaults ]           <-- cmss_default_rules.yaml
   |  "beneficiaries" -> paid students, no year -> 2025-26, top N -> 5
   v
[ entity resolution ]  <-- cmss_entity_resolver.yaml
   |  "EKH" -> district_lgd_code 274, "Tura" -> ask (MB or AC), "unpaid" -> NOT is_disbursed
   v
[ schema linking ]     <-- cmss_schema_partitions.yaml
   |  "scholarship amount" -> amount_disbursed, "students paid" -> is_disbursed
   v
[ join check ]         <-- cmss_foreign_key_augmentation.yaml
   v
[ SQL generation ] -> SQL guard + SQLGlot validation -> read-only execute   (few-shot from cmss_few_shot.yaml)
   v
[ response ]           <-- cmss_response_template.yaml
```

**Rule of thumb, unchanged:** if a fact is about a *column* it belongs in stage2. If it is about
a *value* it belongs in the resolver.

---

## 2. The source data

All inputs are in `datasets/CMSS/`, which is **read-only**.

| File | What it is | Use to this layer |
|---|---|---|
| `CMSS - 2026-10-23.csv` | The data: the 23 Oct 2026 delivery, 104,827 rows × 12 columns | Every figure in this folder |
| `CMSS_Use_Cases.xlsx` | 41 use cases with example bot questions | Question scope (§6) and few-shot coverage |
| `CMSS Dataset Answers.xlsx` | The client's answers to issues CM-01 to CM-23, raised on an earlier 104,909-row file | The authority for every "removed", "not held" and "how to report" rule |
| `cmss_meghalaya_complete_scheme_reference (1).md` | Scheme reference: policy, eligibility, ₹6,000 rate, dates, institutions, documents | Grounds policy questions and the response caveats |
| `cmss_meghalaya_general_faq (1).md` | 25-question FAQ | Knowledge-base answers; not SQL |

### 2.1 `CMSS - 2026-10-23.csv`

- **104,827 rows × 12 columns**, comma-separated, one header row, CRLF line endings, no blank rows.
- Missing values are the literal string `NULL`, never blank. No column has leading or trailing
  whitespace.
- Profiled 2026-11-04 with pandas, every column read as text with `keep_default_na=False`.

| # | Column | Blank / NULL | Distinct | What it holds |
|---|---|---|---|---|
| 1 | `id` | 0 | 104,827 | Source application id, 1 to 104,909 (82 ids absent: the earlier file had 104,909 rows). Unique. In the DB: `source_application_id`, stable across deliveries. |
| 2 | `member_id` | 0 | 104,827 | Meghalaya One citizen id, 6 characters, pattern `A9A9AA`. **Unique on every row.** Personal data: hashed to `member_key` at ingest (CM-23). |
| 3 | `amount_disbursed` | **6,076 `NULL`** | 2 | `6000` on 98,751 rows, `NULL` on 6,076. No other value, and no zeros. |
| 4 | `financial_year` | 0 | **1** | `2025-26` on every row. |
| 5 | `mapped_district_lgd_code` | 0 | 12 | LGD district code. **Authoritative.** |
| 6 | `mapped_district_lgd_name` | 0 | 12 | District name. 19 rows contradict the code (§4.5). |
| 7 | `mapped_block_lgd_code` | 0 | 67 | LGD block code: 56 rural C&RD blocks + 11 municipal boards / town committees. **Authoritative.** |
| 8 | `mapped_block_lgd_name` | 0 | 67 | Block name. The same 19 rows contradict the code. Town names carry a suffix, e.g. `Tura Municipal Board-Municipal Board`, `Nongstoin-Town Committee`. |
| 9 | `mapped_village_lgd_code` | **1,218 `NULL`** | 5,902 | LGD village or urban ward code. Range 951 to 1,299,540. |
| 10 | `mapped_village_lgd_name` | **1,218 `NULL`** | 5,592 | Village or ward name. `NULL` on the same rows as the code. |
| 11 | `mapped_constituency_name` | **1,218 `NULL`** | 60 | Assembly constituency, mixed case (`Mawkyrwat`). |
| 12 | `mapped_constituency_name_and_number` | **1,218 `NULL`** | 60 | Number + upper-case name (`36 MAWKYRWAT`). |

**What the earlier file had and this one does not** (client answers): student names (CM-16,
CM-17), gender (CM-15), institution type and location (CM-03, CM-04, CM-05), `draft_requestid`
(CM-14), and the internal constituency code series (CM-06).

---

## 3. CSV to YAML: the derivation pipeline

The steps run on 2026-11-04, in order, and what each one feeds:

```
# Step 1 - shape, header, NULL token check
#   -> 104,827 x 12; missing = the string 'NULL'                         feeds stage2 row counts
# Step 2 - per-column census (NULL, distinct, top values, max length, whitespace)
#   -> the §2.1 table                                                    feeds stage2 sample_values
# Step 3 - key uniqueness: id, member_id
#   -> both unique; one application per student in 2025-26             feeds the grain + is_repeat_member_in_year
# Step 4 - money census
#   -> {6000: 98,751, NULL: 6,076}; total Rs 59,25,06,000                feeds the flat-rate rules
# Step 5 - financial_year census
#   -> one value, 2025-26                                               feeds the one-year refusals
# Step 6 - code <-> name agreement for district, block, village, constituency
#   -> 19 rows (657/2000 named Eastern West Khasi Hills / Mairang)      feeds codes-over-names
# Step 7 - NULL pattern on village and constituency
#   -> all four NULL on the same 1,218 rows, all paid                    feeds the Unresolved rule
# Step 8 - towns and wards
#   -> 11 urban block codes (10,173 rows); 120 ward codes (8,541 rows)   feeds the resolver town catalogue
# Step 9 - village-name ambiguity and cross-level name collisions
#   -> 231 names with >1 code; 27 block=village, 26 block=AC names        feeds the ambiguity registry
# Step 10 - totals by district / block / constituency (by LGD code)
#   -> the golden answers in §9
```

---

## 4. Verified facts (profiled 2026-11-04, from the CSV)

### 4.1 The money is a flat ₹6,000 — the headline finding

| | |
|---|---|
| Paid applications | **98,751** (94.20%), each exactly ₹6,000 |
| Unpaid applications | **6,076** (5.80%), `amount_disbursed` = `NULL` |
| Total disbursed | **₹59,25,06,000 = ₹59.25 crore** |
| Zeros | none. "Zero disbursement" in the use cases means the 6,076 `NULL`s. |

Consequences:
- **Amount = paid students × ₹6,000** for every slice. The DB constraint
  `ck_cmss_disbursed` (`is_disbursed = (amount_disbursed IS NOT NULL)`) guarantees the two
  columns agree.
- **Average per paid student is ₹6,000 everywhere.** It never varies by district, block or
  village, so "average assistance by district" is answered once, with that explanation, not as a
  table of identical numbers. Average per *application* (₹5,652.23 statewide) varies only with
  the paid share and must be labelled as such.
- **Highest or lowest disbursement per beneficiary** has no answer: all are equal. Use cases 21
  and 22 are answered with that fact, never with a list of students.
- "More than ₹5,000" = every paid student (98,751).
- The scheme reference projected about 80,000 students and ₹48 crore a year. The file's
  98,751 paid students and ₹59.25 crore are above both. This is a reportable fact, not an error.

### 4.2 Grain and keys

| Candidate | Unique? | Use |
|---|---|---|
| `id` | **Yes**, 104,827 | Source application id. In the DB: `source_application_id` (fact only, not in the view). |
| `member_id` | **Yes**, 104,827 | The student. Hashed to `member_key` (64 hex characters) in the DB and **never shown**. |

In 2025-26 one student has exactly one application (the client confirmed "each member_id appears
only once", CM-17), so **applications = distinct students = 104,827**. When a second year lands,
`COUNT(DISTINCT member_key)` will differ from `COUNT(*)`. The fact flag `is_repeat_member_in_year`
(false on every row) is not exposed in the view.

`member_id` is the common Meghalaya One citizen id (CM-18). The DB hashes it with the same key as
Focus+'s `member_key`, so a CMSS student and a Focus+ member can be matched. **This link is
prohibited in this layer** until a deliberate decision is recorded (§7).

### 4.3 Unpaid applications

- 6,076 unpaid, with **no** reason, status, rejection flag, defect flag or date (CM-02, CM-22).
- **Never call them "rejected".** The scheme reference describes defect notices and a
  compliance deadline, so an unpaid application may be defective, pending, rejected or
  cancelled. Say "not paid (no amount recorded)".
- Every one of the 1,218 rows without a village is **paid**. All 6,076 unpaid rows have a village.
- Unpaid share by block ranges from 3.0% (Mawhati) to 14.4% (Rongara). By district from 4.8%
  (South West Khasi Hills) to 10.4% (East Garo Hills).

### 4.4 Time

- One value, `2025-26`, on all rows. In the DB this is `financial_year_short = '2025-26'` /
  `financial_year = '2025-2026'`, joined through `dim_year`.
- **Academic year ≠ financial year** (CM-21). The scheme runs on academic sessions (2025-26 cycle:
  applications 1 Sep to 31 Oct 2025; 2026-27 cycle: 7 Oct to 6 Nov 2026, verification to
  4 Dec 2026). The data carries only the financial year, and the bot answers by financial year.
- There is no application, payment or verification date. "This month", "last quarter" and "when
  was it paid" are refused.
- **No 2026-27 data.** A question about 2026-27 gets "not held yet", never 0.
- Trend, growth and year-on-year comparison are refused until a second year is loaded. The
  client says new years will be added, so these refusals carry an "until more years are loaded"
  wording.

### 4.5 Geography

- **12 districts, 67 block codes (56 rural + 11 towns), 5,902 village/ward codes, 60
  constituencies (numbers 1–60, all present).** All Meghalaya. The geography is the **student's
  home address** (CM-20).
- **Codes are authoritative, names are not.** 19 rows carry district code 657 (East Jaintia Hills)
  and block code 2000 (Saipung) with the names *Eastern West Khasi Hills / Mairang*. Grouped by
  code, East Jaintia Hills has 5,812 applications and Saipung 1,474. Grouped by source name, they
  have 5,793 and 1,455. The DB flags these `has_name_code_conflict` and trusts the codes.
- **The DB also flags 16 more rows** (South West Garo Hills / Betasing names on Demdema villages,
  per the fact-table comment). The CSV's block code and name agree on those rows, so the conflict
  is only visible against the LGD village roster. Which block they report under in `v_cmss` must be
  checked in the DB (§10).
- **Towns as blocks (CM-08).** 11 urban local bodies sit in the block column, with **10,173
  applications** (9,524 paid):

  | Block code | Source name | District | Applications | Paid |
  |---|---|---|---:|---:|
  | 249814 | Shillong-Municipal Board | East Khasi Hills | 2,495 | 2,321 |
  | 249810 | Nongstoin-Town Committee | West Khasi Hills | 1,727 | 1,620 |
  | 249820 | Jowai-Municipal Board | West Jaintia Hills | 1,521 | 1,441 |
  | 249811 | Mairang-Town Committee | Eastern West Khasi Hills | 1,061 | 1,002 |
  | 249806 | Tura Municipal Board-Municipal Board | West Garo Hills | 1,015 | 950 |
  | 249807 | Resubelpara-Municipal Board | North Garo Hills | 665 | 642 |
  | 249808 | William Nagar-Municipal Board | East Garo Hills | 636 | 569 |
  | 249812 | Nongpoh-Town Committee | Ri Bhoi | 593 | 542 |
  | 249809 | Baghmara-Municipal Board | South Garo Hills | 349 | 333 |
  | 282009 | Mawkyrwat-Town Committee | South West Khasi Hills | 61 | 57 |
  | 279714 | Khliehriat-Town Committee | East Jaintia Hills | 50 | 47 |

  Five towns share a name with a rural block (Nongstoin, Mairang, Resubelpara, Baghmara,
  Mawkyrwat), and Jowai, Nongpoh, Khliehriat and William Nagar share a name with a constituency.
  "Nongstoin block" is ambiguous between the rural block (1980) and the town committee (249810),
  so the resolver asks.
- **Wards (CM-13).** 120 ward codes on 8,541 rows take the place of a village in urban areas.
  62 of those rows sit in rural blocks.
- **1,218 rows (1.16%) have no village and no constituency.** All are paid. West Garo Hills 848
  (825 in Rongram, 19 in Tura MB, 4 in Tikrikilla), East Khasi Hills 359 (all Shella Bholaganj),
  East Garo Hills 8, West Jaintia Hills 3. In the DB they point at their block's `Unresolved`
  placeholder (`entity_type = 'Unresolved'`). **Count them in district and block totals; exclude
  them from village and constituency figures.** A constituency total therefore sums to 103,609,
  not 104,827.
- **Village names are not unique.** 231 names map to more than one code (up to 8: *Umsaw*). 154
  resolve by district, 72 more by block, and 5 need the village code (*Chokdenggre*, *Dewsaw*,
  *Konchikol Apal*, *Old Kalapara*, *Umsaw*).
- **Cross-level name collisions:** 27 names are both a block and a village, 26 are both a block
  and a constituency, and 25 are both a village and a constituency. *Mawlai* is all three. *Tura*
  is not a block at all: it is Tura Municipal Board, or North/South Tura constituency.
- **The view's geography columns come from the roster** (`dim_geography`): `lgd_district` and
  `lgd_block` are stored **upper case**, and `ac_number` / `ac_name` are the roster's
  constituency, not the source's two constituency columns. **Filter on `district_lgd_code`,
  `block_lgd_code` and `ac_number`.** Codes avoid every casing and spelling trap, and
  `dim_geography.lgd_block_code` notes that the Tura placeholder is "spelled differently".

### 4.6 Constituencies

The two source constituency columns agree on every row. Spellings that differ between them:
`Sohing` / `23 SOHIONG`, `Ampathi` / `53 AMPATI`, `Tikrikila` / `45 TIKRIKILLA`. Truncated in the
numbered form: `Sutnga-saipung` / `5 SUTNGA`, `Rambrai jyrngam` / `33 RAMBRAI`, `William Nagar` /
`43 WILLIAM`, `Rongara-siju` / `58 RONGARA`. All are resolver aliases. 12 constituencies span two
districts (e.g. Sutnga-Saipung, Mawthadraishan, Dalu), so a constituency answer never implies a
single district.

### 4.7 Region

`v_cmss.region` comes from the LGD master by district: **Garo** (East, North, South, South West
and West Garo Hills: 33,483 applications), **Khasi** (East, West, South West and Eastern West
Khasi Hills: 43,438), **Jaintia** (East and West Jaintia Hills: 18,677). **Ri Bhoi's region value
(9,229 applications) is not confirmed.** The DB says the values are Garo / Khasi / Jaintia, so
Ri Bhoi is most likely recorded as Khasi. Check before quoting a regional total (§10).

---

## 5. The client issue list, answered (`CMSS Dataset Answers.xlsx`)

| ID | Question raised | Client answer | Effect on this layer |
|---|---|---|---|
| CM-01 | Every application, approved only, or paid only? | "Check whether amount is disbursed or not." | The file holds all applications. "Beneficiary" = paid; applications reported alongside. |
| CM-02 | 6,158 unpaid with no institution: rejected, pending, drafts? | Same as CM-01. | Unpaid = no amount recorded, reason unknown. Never "rejected". Now 6,076. |
| CM-03, 04, 05 | Institution type and location | "Institution type is no longer in the file." | All institution questions refused. |
| CM-06 | Internal constituency code series | Removed from the new dataset. | Constituency by name and ECI number only. |
| CM-08 | Municipal boards / town committees under blocks | "Consider them as blocks." | Towns are block values (§4.5). |
| CM-09 | Blank Purakhasia block code | Purakhasia = 7418, now filled. | Verified: 593 rows, code 7418. |
| CM-10 | Different block code series | The new file uses LGD block codes. | Verified: e.g. Mawkynrew = 1991. |
| CM-12 | Village codes 1 and 951 | "Check on the basis of district, block and village name." | Code 951 no longer appears as a bare village. The lowest codes are urban wards (2363+). |
| CM-13 | Wards in the village column | Yes; the ward replaces the village; home address. | Wards count as villages in "villages covered". |
| CM-14 | `draft_requestid` | No longer in the file. | — |
| CM-15 | Gender values | "Gender is no longer in the file." | All gender questions refused. |
| CM-16, 17 | Names, duplicate names | Names removed; each member_id appears once. | No name lookup. Applications = students. |
| CM-18 | Is member_id the common citizen id? | Yes, the Meghalaya One member id. | Cross-scheme link possible but prohibited (§7). |
| CM-19 | Village codes not in the LGD roster | New LGD dataset provided. | The DB's roster is the 3 Sep 2026 LGD master. |
| CM-20 | Home or institution address? | The student's home address. | Every geography answer says "students from …". |
| CM-21 | Academic vs financial year | Not equal; answer by financial_year; more years later. | Time rules in §4.4. |
| CM-22 | Payment date, status, failed transfers | "No. Currently we don't have these data." | Refused. |
| CM-23 | Masking of names and member_id | Names gone; mask member_id. | `member_key` only; never displayed. |

---

## 6. Question scope: the 41 use cases

| Verdict | Use cases | How |
|---|---|---|
| **Answer** (20) | 1, 2, 5, 6, 14, 15, 16, 17, 18, 19, 20, 23, 24, 25, 26, 32, 33, 36, 38, 39 | Counts and amounts by state, district, block, village, constituency and year. 20, 25 and 26 answer "₹6,000 per paid student, everywhere". 32 and 33 answer with the single year and say a trend needs more years. |
| **Answer in aggregate, with a caveat** (8) | 3, 4, 21, 22, 34, 35, 37, 41 | 3, 4, 35: no student list (no names; the id is masked), so offer counts by village. 21, 22: every paid student got ₹6,000. 34: only 2025-26 is held. 37, 41: report every available dimension and state that gender and institution type are not held. |
| **Refuse, with an offer** (13) | 7, 8, 9, 10, 11, 12, 13, 27, 28, 29, 30, 31, 40 | Gender and institution type were removed from the data (CM-03/04/05/15). Offer the same breakdown by district, block or constituency. |

Also refused, beyond the workbook: reasons for non-payment, payment dates and status, academic
year or course level, institution name or location, marks, income, caste or tribe (the scheme
has no income or community criterion, so none is recorded), individual students, and any
row-level link to another scheme.

Policy questions (eligibility, documents, how to apply, deadlines, helpline) are not SQL. They are
answered from the scheme documents in the knowledge base.

---

## 7. Database alignment: CMSS is in `megh_db`

`SCHEMA_FOR_DEVELOPERS.md` (live extract, 2026-11-03 13:12 UTC) contains:

| Object | Role |
|---|---|
| `curated.fact_cmss_application` | The fact, ~104,827 rows, unique on `source_application_id`. 4 declared FKs (`dim_geography`, `dim_scheme`, `dim_year`, `raw.source_rows`). |
| **`curated.v_cmss`** | **The query surface the YAMLs target.** 19 columns: fact + `dim_geography` + `dim_year`. |
| `meta.v_reconciliation_cmss` | `raw_rows = curated_rows + quarantined`. Expected on the 23 Oct file: 104,827 = 104,827 + 0. |
| `curated.v_place_names` | Name → level lookup (village / block / AC / district). Use it before filtering on a bare name. |
| `curated.v_data_coverage` | Years present per scheme. For CMSS: 2025-26 only. |
| `semantic.scheme_relationships` | Pairwise combine rules. The CMSS ↔ Focus+ / Homestay rows are not printed in the schema doc. |

CSV column → view column:

| CSV | `v_cmss` | Note |
|---|---|---|
| `id` | not exposed (`source_application_id` on the fact) | lineage |
| `member_id` | `member_key` | HMAC-SHA256, 64 hex. `COUNT(DISTINCT)` only. |
| `amount_disbursed` | `amount_disbursed` (numeric, NULL when unpaid) + `is_disbursed` (boolean, NOT NULL) | |
| `financial_year` | `year_key`, `financial_year` (`2025-2026`), `financial_year_short` (`2025-26`) | |
| district code / name | `district_lgd_code` / `lgd_district` (roster, **UPPER CASE**) | raw name on the fact only |
| block code / name | `block_lgd_code` / `lgd_block` (roster, **UPPER CASE**) | raw name on the fact only |
| village code / name | `village_code` / `lgd_village_name`; `entity_type` (`Village` / `Ward` / `Unresolved`) | Unresolved placeholder on the 1,218 |
| constituency (both columns) | `ac_number`, `ac_name` (from the **roster**) | raw strings on the fact only |
| (derived) | `has_name_code_conflict` (35 rows), `region`, `geography_key`, `cmss_fact_id` | |

Not in the view: `source_application_id`, the raw name columns, `is_repeat_member_in_year`,
`raw_id`, `batch_id`.

---

## 8. How each YAML was built (2026-11-04, step by step)

Every file follows the shape of its PMAY sibling (`Annotations/PMAY/pmay_*.yaml`, v2.0): the same
top-level keys, field names and `# ---- section ----` dividers, so the pipeline loads CMSS exactly
as it loads PMAY. The content is driven by §4–§7. A v1.0 file carries no `v2_note`. The build
notes are appended here as each file lands.

### Step 1 - `cmss_schema_partitions.yaml` (stage2)

Built from `SCHEMA_FOR_DEVELOPERS.md` (2026-11-03) for structure and from the CSV profile for values.

- The `database` block points at `curated.v_cmss`. `volumes_verified: false` because there is no
  read credential for `megh_db` on this machine.
- **19 column documents** for `v_cmss`, in the view's declared order, each with `source_column`,
  `meaning`, `type`, `category`, `nlp_sql_priority`, `sql_operations`, `synonyms`,
  `sample_values` (none on `member_key`, by design) and `business_rules`.
- `fact_cmss_application` documented for lineage: 4 declared FKs, 3 CHECK constraints, the 13
  columns not in the view, `member_id` under `dropped_at_ingest`, and a new
  `removed_from_source_by_department` list (names, gender, institution type, `draft_requestid`,
  internal constituency codes).
- The three shared dimensions (`dim_scheme`, `dim_year`, `dim_geography`) plus the two lookup
  views (`v_place_names`, `v_data_coverage`).
- `semantic_rules` carries the CMSS-specific rules: `geography_meaning` (home address),
  `towns_as_blocks_rule`, `unresolved_rule`, `academic_year_rule`, `beneficiary_term` (=
  paid), `flat_rate_rule`, `payment_status_rule` and `not_held_dimensions`.
- `nlp_sql_rules.mandatory_predicate` is **none**, as in NRLM. Two new keys,
  `geography_filter_behavior` (filter on codes) and `list_behavior` (no student lists), have no
  PMAY counterpart.
- 40 few-shot examples: 26 answerable and 14 refusals with `sql: null`.
- Checks: parses with `yaml.safe_load`; all 26 SQL statements parse under SQLGlot as read-only
  `SELECT`s against real `v_cmss` columns; `member_key` appears only inside
  `COUNT(DISTINCT …)`. Every query was **executed against a SQLite emulation of `v_cmss` built
  from the CSV**, and every figure quoted in the file reproduced. Two errors were caught and
  fixed: the per-application average (₹5,652.23, first written 5,652.21) and the number of
  two-district constituencies (11, first written 12).

### Step 2 - `cmss_classification_rules.yaml` (the gate)

68 conditions in PMAY's `condition` + `question` shape (14 carry a `note`), in eight sections
ordered as in PMAY: what the source cannot answer first, then people and identity, payment
status, time, measure, geography, answer shape and cross-scheme.

- **Not held (20 rules):** gender, gender lists, institution type, institution name or
  location, course or class level, marks, Fresh vs Renewal, application status or reason,
  verification or defect status, payment date, bank or DBT details, caste/tribe/income, age,
  budget/target, coverage rate, cancellation or refund, other scholarships (NSP Post-Matric
  ST, pre-matric, PMSS), other schemes, and policy questions routed to the knowledge base.
  Every one ends in an offer of what *can* be answered.
- **New sections with no PMAY counterpart:** *people and identity* (student lists, member-id
  lookup, name lookup, highest/lowest student, cross-scheme person match) and *payment
  status* ("rejected" and "pending" are not recorded states).
- **Time (7 rules):** a year that is not loaded, the current 2026-27 cycle, year comparison,
  trend or growth, academic year, calendar year, month/quarter/date. The "year not loaded"
  rule never lets the bot answer 0.
- **Geography (17 rules), driven by the data:** home vs institution location (CM-20), town and
  rural block sharing a name (5 names), Tura is not a block, Shillong scope (Shillong MB =
  the four Shillong constituencies, 2,495), multi-level names, village names needing a
  district, block or code, Eastern West vs West Khasi Hills, the 19 Tangnub name/code rows,
  constituencies spanning two districts (11), the constituency total of 103,609, Ri Bhoi's
  unconfirmed region, and rural-only vs with-towns.
- **All 13 refused use cases** (7–13, 27–31, 40) are caught by `gender_requested`,
  `gender_list_requested` or `institution_type_requested`. Use cases 37 and 41 are caught by
  `report_with_unavailable_dimensions`, which offers the report without the missing fields.
- **45 `worked_examples`** (NRLM's v1.1 addition) show what a user types, which rule fires and
  what the bot asks, with figures computed from the CSV.
- The header names the conditions reserved for `cmss_default_rules.yaml` (beneficiaries =
  paid, no year, top N, ranking metric, bare amount, average, zero disbursement, unit, towns
  in block lists, Unresolved handling), so the two files stay disjoint.
- Checks: parses with `yaml.safe_load`; no duplicate conditions; every question ends in "?";
  every worked example fires a condition that exists.

### Step 3 - `cmss_default_rules.yaml`

65 defaults in PMAY's shape: `condition` + `default_value` + `assumption_text`, with
`sql_effect` on 14 and a `note` where the reason matters. Seven sections, as in PMAY:
population, time, geography, measure, table, units, answer shape, plus nulls.

- **Population comes first.** Counts include paid and unpaid applications.
  **"Beneficiary" = a paid student** (`beneficiary_term`, critical), with the application total
  always stated beside it. "Students" unqualified shows both numbers. Unresolved rows count in
  totals but not in village or constituency figures. Name/code conflicts count by code. Towns
  are blocks and wards are villages.
- **Time:** everything lands on 2025-26 (missing period, latest, current-as-data-year, all
  years, per-year breakdown with the one-row note). Any other year is left to the gate.
- **Geography:** the student's home address, filtered by LGD code. Regions expand to their
  districts (Khasi with or without Ri Bhoi stays in the gate). Towns with no rural namesake
  (Jowai, Nongpoh, William Nagar, Khliehriat) resolve straight to the town. Constituency
  spellings resolve to the ECI number.
- **Measure, where the flat rate drives four defaults:** average = ₹6,000 per paid student plus
  ₹5,652.23 per application; average by area = the flat-rate statement plus the per-application
  figure (never a column of identical 6,000s); amount thresholds = a flat-rate comparison;
  ranking metric = students paid (amount gives the same order).
- **Units:** crore for the State and districts, lakh below one crore, rupees for a village.
- **Shape:** top 5, show ties, district as the default report level, a fixed report column set,
  and a count per village as the accepted replacement for a student list.
- The header names everything reserved for the gate.
- **25 `worked_examples`** in NRLM's shape (`user`, `fires`, `assumptions_shown`, `sql`,
  `result`).
- Checks: parses with `yaml.safe_load`; no duplicate conditions; **gate ∩ defaults = ∅
  (68 ∩ 65)**; all 23 worked-example SQL statements parse as read-only `SELECT`s and were
  executed against the CSV emulation of `v_cmss`. Every `result` reproduced.

### Step 4 - `cmss_entity_resolver.yaml`

About 2,580 lines, with the same top-level shape and 8-stage matching pipeline as PMAY and
NRLM. The hand-written parts are normalisation, blocked pairs, the output contract, overloaded
terms, collisions, absent dimensions, worked examples and maintenance. **The catalogues were
generated by a pandas script that groups the CSV by LGD code**, so every count matches what
the database filters on:

| Catalogue | Size | Carries |
|---|---|---|
| district | 12 | code, acronym, region, applications, paid, amount, blocks, towns, villages, unresolved, aliases |
| block | 67 = 56 rural + 6 municipal boards + 5 town committees | code, `kind`, district, applications, paid, villages, `also_a`, aliases; towns carry the source spelling |
| constituency | 60 (all ECI numbers) | number, numbered form, districts (and the split where a seat spans two), applications, paid, every spelling |
| village ambiguity registry | 231 names | 154 resolve by district, 72 by block, **5 by code** (two copies in one block) |
| financial_year / payment_status / entity_type / region | 1 / 2 / 3 / 3 | counts and aliases |

Differences from PMAY and NRLM:
- **Every `sql_predicate` is a code.** No name literal reaches the SQL.
- **Towns are a block `kind`.** There are blocked pairs for each town and its same-name rural
  block, and a `same_area_pairs` list: Mawlai block = Mawlai constituency (3,161), and
  Shillong MB = constituencies 16-19 (2,495).
- **No default-to-block on a colliding name** (NRLM defaults to block). CMSS returns
  ambiguous and the gate asks, because the town readings make a silent default wrong too
  often. The exception is the four towns with no rural namesake.
- **Two output shapes from siblings:** `not_available` (from CM Elevate) for gender,
  institution, course, status, dates and any year other than 2025-26, and `refused` (from
  Focus+) for a member-id-shaped span (`^[A-Z][0-9][A-Z][0-9][A-Z]{2}$`).
- An `absent_dimensions` section lists the trigger words for 11 absent dimensions, each with a
  reason and an offer.

Checks: parses with `yaml.safe_load`. District and block catalogues each sum to 104,827
applications / 98,751 paid; constituencies to 103,609 / 97,533. No alias points at two
values within a dimension. Every blocked pair names a catalogue value. All 23 worked-example
SQL statements parse as read-only `SELECT`s and **return their `expected` value against the
CSV emulation**. The alias cross-check found four block/constituency collisions the name
comparison had missed (Rambrai, Rongara, Sohiong, Tikrikilla, whose constituency spelling in
the source differs). They were added as `block_constituency_collisions_via_alias`.

### Step 5 - `cmss_few_shot.yaml`

95 question-to-SQL pairs in PMAY's `sql_generation_examples` format (`question` + `sql` +
`tables`, optional `note`), plus NRLM's `expected`. There are 11 sections: applications and
beneficiaries, districts, blocks and towns, constituencies, villages and wards, money, time,
region and urban/rural, reports (use cases 36-41), data quality, and cross-scheme. Every
answerable use case (1, 2, 5, 6, 14-20, 23-26, 32, 33, 36, 38, 39) and every caveat case
answered in aggregate (3, 4, 35, 37, 41) has at least one pair. As in PMAY and NRLM, refusals
live in stage2, not here.

- The header lists the house rules every pair obeys: `FROM curated.v_cmss` only, codes in
  every `WHERE`, `GROUP BY` code + name, `member_key` only in `COUNT(DISTINCT)`,
  `entity_type <> 'Unresolved'` only on village and constituency questions, and units stated.
- **Every `expected` was produced by a script that executed the pair's SQL against the SQLite
  emulation of `v_cmss`**. No value was typed by hand. Scalars and single rows are stored
  as-is; multi-row results as a row count with the first, second and last rows. The two
  cross-scheme pairs (NRLM, PMAY: aggregate each side, then combine) carry
  `expected: null`, because the other scheme's data is not in this folder.
- Example 92 records both counts for name/code conflicts: 19 from the CSV, 35 per the DB
  comment.
- Checks: parses with `yaml.safe_load`; all 95 SQL statements parse under SQLGlot as
  read-only `SELECT`s; no pair queries the fact table; `member_key` appears only inside
  `COUNT(DISTINCT)`.
- **The executed results caught one error in an earlier file.** West Jaintia Hills'
  per-application average is ₹5,730.90 (₹7,37,28,000 ÷ 12,865), not ₹5,730.82 as first written
  in a `cmss_default_rules.yaml` worked example. It was corrected there.

### Step 6 - `cmss_foreign_key_augmentation.yaml`

25 nodes and 28 edges in PMAY's `nodes` / `edges` / `join_graph` shape, plus NRLM's
`worked_examples`:

- **4 declared FKs** of `fact_cmss_application` (`dim_geography`, `dim_year`, `dim_scheme`, all
  NOT NULL; `raw.source_rows`, untraversable by `megh_readonly`), plus the view-to-fact
  lineage edge.
- **4 sanctioned patterns:** aggregate-then-combine on `village_code`, `district_lgd_code` and
  `block_lgd_code` (block is the only level at which CMSS can meet Home Stay Legacy, which has
  no village), and **`distinct_people_across_schemes`** (see below).
- **19 prohibited edges:** row-level joins to every other scheme (PMAY, NRLM, MGNREGA
  employment and expenditure, Focus+ by village, Focus Legacy, CM Elevate, CM Elevate
  Disbursement, Home Stay Legacy by block); both cross-scheme views (they exclude CMSS);
  `dim_geography` on the block or district code (fan-out over every roster village);
  `v_place_names` on a name; `dim_geography_alias`; equating constituency with block;
  `raw.source_rows`; a `member_key` self-join; and, **marked critical, `member_key` to
  Focus+** through the views and through the facts.

**The `member_key` decision, which is new to this layer.** CMSS's `member_key` is the same HMAC
as Focus+'s (its 12.5K cohort only), so "which CMSS students also got Focus+" is one join away.
That join identifies people the department asked to mask (CM-23), so it is prohibited.
`v_homestay_legacy` carries no person key, so CM-18's Homestay overlap cannot be linked at all.
The database defines one person-level rule for schemes that share people
(`semantic.v_scheme_relationship_terms`, `shared_people`): *"count people across both as
DISTINCT member_key over both, never add the two counts"*. That is recorded as a
**conditional** pattern, a `UNION` then `COUNT(DISTINCT member_key)` returning one number,
**disabled until the CMSS / FOCUS_PLUS row of `semantic.scheme_relationships` is read and says
`shared_people`**. An intersection count ("how many are in both") stays refused in every case.

Checks: parses with `yaml.safe_load`. Every node appears in `join_graph` (as a key or an
aggregate partner), every edge endpoint is a declared node, every prohibited edge has a
`use_instead` and no `on_clause`. The 4 worked examples that read only `v_cmss` return their
`expected` value against the CSV emulation. The other 3 read the fact, `dim_scheme` or
`v_focus_plus`, which the emulation does not hold. The SQL checker flags exactly the two
deliberate exceptions: the lineage example reads the fact for `district_name_raw`, and the
conditional `UNION` selects `member_key` inside a subquery whose only output is
`COUNT(DISTINCT)`.

### Step 7 - `cmss_response_template.yaml`

530 lines in PMAY's `formatting` / `templates` / `follow_up_rules` shape. It adds CM Elevate's
refusal templates (`text` / `offer` / `never`) and `composer_checks`, Focus Legacy's in-file
`maintenance` block, and NRLM's `rendered_examples`.

- **The seven mandatory caveats** are listed in the header: beneficiary = paid; flat ₹6,000;
  not paid ≠ rejected; one year; home address; gender and institution not held; village and
  constituency figures exclude the 1,218 unmapped applications. **Each has a template that states
  it and a composer check that fails a draft without it.** A further rule covers identity: no
  student is ever named or listed.
- **Formatting (24 keys):** Indian grouping, ₹, crore for the State and districts, lakh below
  one crore, rupees for a village and for the per-student rate, `date_format: null` (no date
  exists), `unpaid_display: "not paid"`, canonical town names (never the source's doubled
  suffix), and `person_identifiers: never_rendered`.
- **77 templates.** 61 are text: result shapes, situations and the lines that travel with an
  answer. 16 are refusals, each with an offer and, where a wrong move is tempting, a `never`
  line (gender, institution, course, status/reason, payment date, year not loaded, second
  year, academic year, student list, student lookup, highest-paid student, cross-scheme
  person match, caste/income, budget, other scholarships, partial report).
- **31 follow-up rules.** They lead with the measure (paid vs applied vs not paid) and with
  geography type (towns vs rural, a constituency vs its namesake block), since there is no
  time axis to move along.
- **16 composer checks.** Among them: no 'rejected' / 'pending' / 'defective' for the unpaid,
  no gender or institution figure even in a chart label, no year but 2025-26, no
  'studying in', no person identifier, no table of identical ₹6,000s, and no PMAY
  'placeholder' wording.
- **20 rendered answers** built from the CSV figures, including all three refusal families and
  the Shillong, Khasi Hills (Ri Bhoi) and 'studying in Shillong colleges' cases.
- Checks: parses with `yaml.safe_load`. Every refusal has `text` and `offer`; no follow-up
  condition repeats; every rendered example cites templates that exist. **The composer checks
  were run as a script against the 20 rendered answers.** They caught one real violation in a
  first draft: the not-paid example speculated "they may be defective, still in process or
  not approved". It was rewritten to state only that no reason is recorded. The one remaining
  hit is the deliberate "no data for 2024-25" wording.

### Checks run on all seven

- Every file parses with `yaml.safe_load` (7,157 lines in total).
- All 176 SQL statements across the seven files parse under SQLGlot as read-only `SELECT`s.
- No condition is in both the gate (68) and the defaults (65), and none repeats within either.
- Every figure was computed from the CSV. Every SQL that reads only `v_cmss` was executed
  against the SQLite emulation and reproduced its stated value. Four errors were caught and
  fixed along the way: the per-application average (₹5,652.23), the number of two-district
  constituencies (11), West Jaintia Hills' per-application average (₹5,730.90), and four
  block/constituency name collisions missing from the resolver.
- **No query has been run against `megh_db`.** §10 lists what must be checked there.

---

## 9. Golden questions (expected answers from the CSV, 2026-11-04)

| # | Question | Expected |
|---|---|---|
| 1 | How many CMSS beneficiaries are there? | **98,751 students paid** (of 104,827 applications) |
| 2 | How many applications? | **104,827** |
| 3 | Total amount disbursed? | **₹59.25 crore** (₹59,25,06,000) |
| 4 | How many applications were not paid? | **6,076** (5.80%) |
| 5 | Average amount per beneficiary? | **₹6,000** (flat rate; ₹5,652.23 per application) |
| 6 | Which district has the most beneficiaries? | **East Khasi Hills, 24,932 paid** (26,326 applications) |
| 7 | Amount disbursed in West Jaintia Hills? | **₹7.37 crore** (12,288 paid) |
| 8 | Which block has the most beneficiaries? | **Laskein, 4,303 paid** (then Thadlaskein 3,888) |
| 9 | Beneficiaries in Mawkyrwat constituency? | **3,341 paid** (3,521 applications) |
| 10 | How many students from Shillong Municipal Board? | **2,321 paid** (2,495 applications) |
| 11 | How many villages have a CMSS applicant? | **5,902** village/ward codes (5,782 villages + 120 wards); 1,218 applications unmapped |
| 12 | Male vs female beneficiaries? | **Refuse**: gender is not in the data (CM-15) |
| 13 | Beneficiaries by institution type? | **Refuse**: institution type is not in the data (CM-03) |
| 14 | Compare 2025-26 with 2024-25 | **Refuse / not held**: only 2025-26 is loaded |
| 15 | Why were 6,076 not paid? | **Refuse**: no reason or status is recorded (CM-02, CM-22) |

District totals, grouped by **LGD code** (as `v_cmss.district_lgd_code` does):

| District | LGD | Applications | Paid | Unpaid | Paid % | Amount (₹ Cr) | Blocks | Villages | No village |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| East Khasi Hills | 274 | 26,326 | 24,932 | 1,394 | 94.7 | 14.9592 | 12 | 900 | 359 |
| West Jaintia Hills | 275 | 12,865 | 12,288 | 577 | 95.5 | 7.3728 | 5 | 290 | 3 |
| West Garo Hills | 278 | 12,744 | 11,966 | 778 | 93.9 | 7.1796 | 9 | 950 | 848 |
| Ri Bhoi | 276 | 9,229 | 8,701 | 528 | 94.3 | 5.2206 | 6 | 578 | 0 |
| West Khasi Hills | 279 | 7,358 | 6,968 | 390 | 94.7 | 4.1808 | 6 | 511 | 0 |
| East Jaintia Hills | 657 | 5,812 | 5,517 | 295 | 94.9 | 3.3102 | 4 | 176 | 0 |
| South West Garo Hills | 663 | 5,800 | 5,442 | 358 | 93.8 | 3.2652 | 4 | 508 | 0 |
| East Garo Hills | 273 | 5,082 | 4,554 | 528 | 89.6 | 2.7324 | 4 | 432 | 8 |
| South Garo Hills | 277 | 4,985 | 4,520 | 465 | 90.7 | 2.7120 | 6 | 589 | 0 |
| Eastern West Khasi Hills | 740 | 4,967 | 4,724 | 243 | 95.1 | 2.8344 | 3 | 208 | 0 |
| North Garo Hills | 656 | 4,872 | 4,584 | 288 | 94.1 | 2.7504 | 5 | 475 | 0 |
| South West Khasi Hills | 658 | 4,787 | 4,555 | 232 | 95.2 | 2.7330 | 3 | 285 | 0 |
| **Total** | | **104,827** | **98,751** | **6,076** | **94.2** | **59.2506** | **67** | **5,902** | **1,218** |

Grouping by source district **name** instead would move 19 applications from East Jaintia Hills to
Eastern West Khasi Hills (§4.5). Every golden figure for the DB uses the code-based numbers above.
The 16 DB-flagged Betasing/Demdema rows may move between South West Garo Hills and West Garo
Hills in `v_cmss`. Check this before publishing those two districts (§10).

---

## 10. Open verification tasks (need the live DB)

1. `meta.v_reconciliation_cmss`: expect 104,827 = 104,827 + 0.
2. `curated.dim_scheme` row `CMSS`: read `money_unit` (expect rupees), `grain_note`,
   `time_semantics`, `data_as_of`.
3. **The 35 `has_name_code_conflict` rows.** Check whether `block_lgd_code` agrees with
   `lgd_block` on them, especially the 16 Betasing/Demdema rows.
4. `region` for Ri Bhoi (district 276).
5. The stored `lgd_block` spelling of the 11 towns (the Tura placeholder is "spelled
   differently"), and `ac_name` spellings, for display only, since filters use codes.
6. `semantic.scheme_relationships` rows for CMSS (with Focus+ and Homestay, which share
   member ids).
7. `meta.v_access_matrix`: `megh_readonly` can read `v_cmss`, and `member_key` is not exposed to
   the chatbot role in plain answers.

---

## 11. Regeneration checklist

Run whenever a new extract arrives. The client says new financial years will be added.

- [ ] Re-run the §3 steps. Diff every count against §4 and §9 and explain every change.
- [ ] **A second financial year arrives:** lift the trend, comparison and growth refusals in the
      gate. Re-check `member_id` uniqueness per year and across years, since
      `COUNT(DISTINCT member_key)` and `COUNT(*)` will now differ. Re-check
      `is_repeat_member_in_year`.
- [ ] **The amount stops being flat** (the guidelines allow differential rates by course):
      remove every "₹6,000 everywhere" rule and the average/maximum refusals.
- [ ] **Gender, institution type, status or payment date reappear:** remove the matching
      refusals and add columns to stage2.
- [ ] Re-run code ↔ name agreement, the town list, the ward count and the village ambiguity
      registry.
- [ ] New district / block / village / constituency values: **append** to the resolver. Never
      delete one.
- [ ] Bump versions, update `generated_on` and row counts, validate every YAML with
      `yaml.safe_load`, and re-run §9.

---

## 12. House rules

- `datasets/CMSS/` is a **read-only input**. Never write to it.
- **Applications, paid students and amount are three answers.** Name which one every number is.
  "Beneficiaries" means paid students.
- **₹6,000 is the whole story of the money.** Never present an average, maximum or minimum as if
  it varied.
- **Unpaid is not rejected.** No reason is recorded.
- **One year only.** Never invent a trend, and never answer 0 for a year that is not loaded.
- **Gender and institution type are not held.** Refuse, then offer geography.
- **`member_key` never reaches an answer.** No student-level list, ever.
- **Codes over names.** Filter on `district_lgd_code`, `block_lgd_code`, `ac_number`,
  `village_code`. Exclude `Unresolved` from village and constituency figures only.
- **Never row-join CMSS to another scheme's fact**, including Focus+ through `member_key`.
- **No YAML in this folder is created or edited without an explicit instruction naming the file
  and the change.** (Instruction received 2026-11-04: build all seven, in order.)

---

## 13. Change log

| Date | Change |
|---|---|
| 2026-11-03 | Folders `datasets/CMSS/` and `Annotations/CMSS/` created. Seven empty YAML stubs with the `cmss_` prefix. README started from the 2026-11-03 schema extract. |
| 2026-11-04 | All five inputs read: the 23 Oct CSV (104,827 × 12, profiled in full), the 41-case use-case workbook, the CM-01…CM-23 client answers, the scheme reference and the FAQ. README rewritten: source data, profiling steps, verified facts, client answers, question scope (20 answer / 8 caveat / 13 refuse), DB alignment, golden questions by LGD code, open verification tasks. Headline: **flat ₹6,000, one year, no gender or institution, towns as blocks.** |
| 2026-11-04 | `cmss_schema_partitions.yaml` **v1.0 written**: 19 view columns, fact lineage, 3 dimensions, 2 lookup views, semantic and NL→SQL rules, 40 few-shot examples (14 refusals). All SQL validated and executed against a CSV emulation of `v_cmss`. See §8 step 1. |
| 2026-11-04 | `cmss_classification_rules.yaml` **v1.0 written**: 68 rules in 8 sections plus 45 worked examples. All 13 refused use cases are caught. See §8 step 2. |
| 2026-11-04 | `cmss_default_rules.yaml` **v1.0 written**: 65 rules plus 25 worked examples. No overlap with the gate. Every worked example executed against the CSV emulation. See §8 step 3. |
| 2026-11-04 | `cmss_entity_resolver.yaml` **v1.0 written**: generated catalogues (12 districts, 67 blocks including 11 towns, 60 constituencies, 231-name village registry), 11 absent dimensions, 31 worked examples. Catalogue totals reconcile; every worked example returns its expected value. See §8 step 4. |
| 2026-11-04 | `cmss_few_shot.yaml` **v1.0 written**: 95 pairs in 11 sections; 93 `expected` values produced by executing the SQL against the CSV emulation, 2 cross-scheme pairs left null. One correction to `cmss_default_rules.yaml`: West Jaintia Hills' per-application average is ₹5,730.90, not 5,730.82. See §8 step 5. |
| 2026-11-04 | `cmss_foreign_key_augmentation.yaml` **v1.0 written**: 25 nodes, 28 edges (4 declared FKs, 19 prohibited including the critical `member_key` link to Focus+, 4 sanctioned patterns), 14 worked join decisions. The distinct-people UNION pattern is recorded as conditional, pending `semantic.scheme_relationships`. See §8 step 6. |
| 2026-11-04 | `cmss_response_template.yaml` **v1.0 written**: 24 formatting keys, 77 templates (16 refusals), 31 follow-ups, 16 composer checks, 20 rendered answers. The composer checks, run against the rendered answers, caught one speculative 'defective' wording, which was rewritten. **All seven YAMLs are built: 7,157 lines, 176 SQL statements, every file parsing clean.** See §8 step 7. |
