# Homestay (API feed) Annotation Layer — How the YAMLs Are Built

This folder holds the hand-curated annotation layer for **Homestay**, the application feed of the
**Chief Minister's Meghalaya Homestay Mission (CMMHM)**, formerly the Meghalaya Tourism Homestay
Scheme (Tourism Department, Government of Meghalaya, with DCICs, MIPA and partner banks), for
the Megh One AI NLP-to-SQL bot. The data comes from the **Homestay API** (`HOMESTAY_API`), the
online application system on `invest.meghalaya.gov.in` / `meghalayaone.gov.in`.

Everything here is derived from the inputs in `datasets/Homestay/`. Nothing in this folder is
generated at runtime.

> **Status, 2026-11-06: all 7 YAMLs built (v1.0), 7,670 lines, every file parsing clean.**
> All 168 executable SQL statements are read-only `SELECT`s and ran without error against a
> SQLite emulation of the planned view built from the CSV; every `expected` / `result` value was
> filled by script from those runs. The gate and the defaults share no condition. No SQL reads a
> fact table or a personal column; `member_key` appears only inside `COUNT(DISTINCT …)`.
> **This feed is not in `megh_db` yet.** `SCHEMA_FOR_DEVELOPERS.md` (2026-11-03) has only
> `curated.v_homestay_legacy`. The view name used in this folder, `curated.v_homestay`, is a
> **placeholder** until the loader is built (§7).

It is a sibling of `Annotations/PMAY/README.md` (the structural template) and
`Annotations/CMSS/README.md` (the most recent scheme). What is different about Homestay comes down
to seven things:

1. **One row is one application, not one person or one homestay.** `id` and `request_id` are
   unique (1,298). There are 1,279 distinct `member_id`s, so 19 rows are repeat applications
   by the same person. "Applicants" or "people" means `COUNT(DISTINCT member_id)` (§4.2).
2. **There is no money column.** The feed has no project cost, loan, subsidy, grant or EMI.
   The 70% / 80% subsidy and the ₹10 lakh / ₹2 lakh / ₹80 lakh figures come from the scheme
   reference, not the data. Money questions are refused as data questions and answered only
   as scheme facts (§4.7).
3. **Two schemes, one word.** "Homestay" can mean this feed (applications, FY 2025-26 onward)
   or **Homestay Legacy** (`curated.v_homestay_legacy`, about 909 disbursed loans). An
   unqualified "homestay" question must be routed or asked. Never row-join the two.
4. **Two kinds of application in one table.** `response_type` = *Development of New Homestay*
   (1,274, Component 1) or *Updragation of New Homestay* (24, Component 2; the typo is in the
   source). Each kind fills a different set of columns (§4.3). There are no Boutique
   (Component 3) rows.
5. **Three status columns that mean different things.** `file_status` (Approved / Pending /
   Rejected / Unknown), `current_file_status` (Forward / Approved / Sendback / Resubmit) and
   `current_level` (level1 / Level4). `data_verified` is a separate verification flag. A bare
   "status" must be pinned (§4.4).
6. **Two geographies.** The applicant's home address (`district`, `block`, `village` and the
   LGD-corrected `mapped_*` columns) and the proposed homestay site
   (`district_of_proposed_location`, `block_of_proposed_location` = tourism clusters,
   `village_of_proposed_location`). They differ on 113 new-build rows (145 against the raw,
   unmapped district). The default is the mapped home
   address. The site is used only when the user says "located in" or "proposed in" (§4.5).
7. **The live year is partial.** `financial_year` is derived exactly from `createddate`.
   2025-26 runs from 7 Oct 2025 (the scheme launched that month) and 2026-27 runs only to
   19 Oct 2026. Year comparisons must say that 2026-27 is incomplete.

---

## 1. What is in this folder

| File | Layer | Answers the question | Status |
|---|---|---|---|
| `homestay_schema_partitions.yaml` | **Semantic schema** (*stage2*) | *What columns exist, what do they mean, how are they aggregated?* | **v1.0 built** — 52 expected view columns, 36 few-shot (11 refusals) |
| `homestay_classification_rules.yaml` | **Clarification gate** | *Is the question answerable as asked, or must the bot ask or refuse first?* | **v1.0 built** — 69 rules + 50 worked examples |
| `homestay_default_rules.yaml` | **Defaults** | *What is assumed when the user does not say, and stated back?* | **v1.0 built** — 78 rules + 25 worked examples (executed) |
| `homestay_entity_resolver.yaml` | **Entity resolver** | *The user typed "EKH", "Sohra cluster", "upgradation", "CM Connect": which stored value is that?* | **v1.0 built** — 12 districts, 65 blocks (11 towns), 58 constituencies, 9-name village registry, 37 tourism clusters, 12 status/category vocabularies, 31 worked examples |
| `homestay_few_shot.yaml` | **Worked examples** | *Validated question-to-SQL pairs* | **v1.0 built** — 83 pairs, all with an executed `expected`; covers all 43 answerable use cases |
| `homestay_foreign_key_augmentation.yaml` | **Join graph** | *Which joins are allowed, and which are prohibited* | **v1.0 built** — 22 nodes, 27 edges (4 expected declared, 1 lineage, 5 patterns, 17 prohibited), 13 worked join decisions |
| `homestay_response_template.yaml` | **Response shaping** | *How a number is phrased, and which caveats travel with it* | **v1.0 built** — 8 mandatory caveats, 18 refusals, 31 follow-ups, 17 composer checks, 18 rendered answers |
| `README.md` | This guide | *How the layer is built and what must never change* | written 2026-11-06 |

Pipeline position, the same as for PMAY:

```
user question
   |
   v
[ Node 1 scheme routing ] <-- MASTER/schemes_catalog.yaml
   |  "homestay applications" -> HOMESTAY;  "homestay loans disbursed" -> HOMESTAY_LEGACY;  bare "homestay" -> ask
   v
[ clarification gate ]    <-- homestay_classification_rules.yaml
   |  "how much subsidy was paid", "project start date", "list applicants' phone numbers" -> refuse with an offer
   v
[ defaults ]              <-- homestay_default_rules.yaml
   |  "applications" -> COUNT(*), "status" -> file_status, "district" -> mapped home district
   v
[ entity resolution ]     <-- homestay_entity_resolver.yaml
   |  "EKH" -> 274, "Ri-bhoi" -> Ri Bhoi (276), "upgradation" -> response_type LIKE 'Updragation%'
   v
[ schema linking ]        <-- homestay_schema_partitions.yaml
   v
[ join check ]            <-- homestay_foreign_key_augmentation.yaml
   v
[ SQL generation ] -> SQL guard + SQLGlot validation -> read-only execute   (few-shot from homestay_few_shot.yaml)
   v
[ response ]              <-- homestay_response_template.yaml
```

---

## 2. The source data

| File | What it is | Used for |
|---|---|---|
| `Home Stay API - 2026-11-01.csv` | The application extract, 1,298 rows × 81 columns, missing = the string `NULL` | Every figure in this folder |
| `HomeStay_Use_Cases.xlsx` | Two sheets: **Homestay API** (45 use cases, this folder) and **HomeStay Legacy** (39 use cases, belongs to `Annotations/Homestay_Legacy/`) | Question scope (§6) |
| `meghalaya_homestay_scheme_complete_scheme_reference.md` | Scheme rules: components, subsidy rates, eligibility, workflow, penalties, contacts | Scheme-fact answers, synonyms, caveats |
| `meghalaya_homestay_scheme_general_faq.md` | 25 citizen FAQs | Scheme-fact answers, refusal redirects |

`datasets/Homestay/` is read-only.

### 2.1 The scheme in brief (from the reference and FAQ)

| Item | Value |
|---|---|
| Name | Chief Minister's Meghalaya Homestay Mission (CMMHM), scaled up on World Tourism Day, Sep 2025 |
| Department | Tourism Department; DCIC (Commerce & Industries), MIPA, Meghalaya Rural Bank / SBI; training by IHM Shillong; listing on the M-TIME portal |
| Target | 3,000 homestays and 15,000+ jobs by 2028 |
| Component 1 — New homestay | Cost up to ₹10 lakh; subsidy up to 70% (35% PMEGP + 35% Tourism), cap ₹7 lakh; PwD up to 80%, cap ₹8 lakh; promoter 5% (ST/SC/Women) or 10% (General); 12-month moratorium, 7-year tenure; must use one of the **33 standard designs** |
| Component 2 — Upgradation | ₹50,000 per room, max ₹2 lakh; must have operated 6 months, 50 bed-nights, and be listed on M-TIME |
| Component 3 — Boutique | 10+ rooms, min ₹80 lakh, 90:10 debt-equity, incentive up to ₹15 lakh (₹10 lakh EMI + ₹5 lakh National Games bonus) |
| Eligibility | Indian citizen, Meghalaya domicile, 18+, not a loan defaulter, one unit per family, owned land or a registered lease of 7+ years (15 for boutique), local NOC |
| Workflow | Online application → DCIC + District Tourism Officer scrutiny → site inspection → District Task Force → bank sanction → construction-linked disbursement → subsidy as EMI support → M-TIME onboarding |
| Helplines | MIPA +91 7085741695; citizen service line 1971 |

These are **scheme facts, not data**. None of the amounts above is in the CSV.

---

## 3. CSV to YAML: the derivation pipeline

Run with the project venv (`%USERPROFILE%\.venvs\megh`), reading every column as text with
`keep_default_na=False`.

```
# Step 1 - shape, header, NULL token
#   -> 1,298 x 81; missing = the string 'NULL'; no blank cells               feeds stage2 row count
# Step 2 - per-column census (NULL, distinct, top values, max length)
#   -> the §2.2 column table                                                  feeds stage2 sample_values / exclusions
# Step 3 - key uniqueness: id, request_id, member_id, epic_id, family_id, mobile
#   -> id, request_id unique; member_id 1,279 distinct (19 repeat rows)      feeds the grain + applicants vs applications
# Step 4 - dead / constant columns
#   -> 6 all-one-value columns                                                feeds stage2 exclusions
# Step 5 - response_type split
#   -> 1,274 new-build / 24 upgradation; each fills its own column set        feeds the component rules
# Step 6 - status cross-tabs (file_status x current_file_status x current_level x data_verified)
#   -> §4.4                                                                    feeds the status disambiguation
# Step 7 - time: createddate vs financial_year
#   -> FY derived exactly (1,298/1,298); 7 Oct 2025 to 19 Oct 2026            feeds the partial-year caveat
# Step 8 - code <-> name agreement: raw vs mapped district, block, village, AC
#   -> 14 district rows remapped; block codes are two different series        feeds codes-over-names
# Step 9 - NULL pattern on mapped village / constituency
#   -> the same 64 rows                                                        feeds the Unresolved rule
# Step 10 - data-quality probes: rooms, age vs category, lease years, gender vs category
#   -> §4.6                                                                    feeds the DQ caveats
# Step 11 - totals by district, status, category, year
#   -> the golden answers in §9
```

### 2.2 Column inventory (81 columns, grouped)

| Group | Columns | Notes |
|---|---|---|
| Keys | `id` (1..1298, unique), `request_id` (unique, `REQ/239/157/<D><M><YYYY>/<n>`) | Never parse `request_id`; its date segment duplicates `createddate` |
| Person (**personal data**) | `first_name`, `middle_name`, `last_name`, `date_of_birth`, `mobile_number`, `email_id`, `address`, `pincode`, `epic_id`, `family_id`, `member_id`, `pds_id` | Never shown, listed, embedded or used as a filter value. `member_id` is allowed **only** inside `COUNT(DISTINCT …)` |
| Applicant attributes | `gender_id` (Female 681 / Male 617), `applicant_category` (5 values), `category_remarks` (free text, 1,191 NULL), `application_mode` (Online 1,235 / cmConnectCenter 63) | |
| Applicant geography, raw | `district`, `district_lgd_code`, `block`, `block_lgd_code`, `village`, `village_lgd_code` | Raw block codes are a **different series** (2xxx, 7185) from the mapped LGD block codes |
| Applicant geography, mapped | `mapped_district_lgd_code/name` (12), `mapped_block_lgd_code/name` (65), `mapped_village_lgd_code/name` (64 NULL), `mapped_constituency_name`, `mapped_constituency_name_and_number` (58 ACs, same 64 NULL) | **Use these.** Block codes are the 1960-series, the same as Homestay Legacy and NRLM |
| Proposed site (new-build) | `district_of_proposed_location` (13 values incl. NULL), `block_of_proposed_location` (38 tourism clusters, 46 NULL), `village_of_proposed_location` (542 "Others", 54 NULL), `address_of_proposed_location`, `pincode_of_proposed_location`, `property_estimated_area_insquare_feet` | Cluster names, not LGD blocks. NULL on the 24 upgradation rows |
| Time | `createddate` (M/D/YYYY), `financial_year` (2025-26: 505, 2026-27: 793) | |
| Workflow / status | `file_status`, `current_file_status`, `current_level`, `data_verified`, `onhold` (all FALSE), `is_withdraw` (all FALSE) | §4.4 |
| Scheme component | `response_type` | §4.3 |
| Land | `type_of_land_holding` (Owned 1,005 / Leased 293), `land_lease_year_start`, `land_lease_year_end`, `difference_lease_year`, `is_difference_lease` | Lease years filled on 289 rows |
| New-build facility (1,274 rows) | `homesaty_rooms` (typo in source), `rainwater_harvesting`, `solar_energy`, `waste_management`, `waste_managment_remarks`, `declaration` | NULL on the 24 upgradation rows |
| Upgradation facility (24 rows) | `establishment_name`, `district_of_establishment`, `address_of_establishment`, `pincode_of_establishment`, `mtime_portal_registered`, `have_registred_mtime_portal`, `mtime_portal_id`, `room_booking_6months`, `employees_establishment`, `built_up_area_in_square_feet`, `lounge_area_in_square_feet`, `dining_area_in_square_feet`, `tourism_upgradation_room_details` (JSON), `fund_utilization_home_stay`, `fund_utilization_home_stay_remarks`, `food_detail_establishment`, `eco_friendly_amenities`, `additional_amenities_home_stay`, `is_difference_lease`, `establishment_manager_self` | NULL on every new-build row. `mtime_portal_id` values look like **mobile numbers**: treat as personal data |
| Dead (one value on every row) | `project_start_date`, `project_end_date`, `property_estimated_area_in_square_feet`, `establishment_manager` (all NULL); `onhold`, `is_withdraw` (all FALSE) | Excluded; questions on them are refused |

---

## 4. Verified facts (profiled 2026-11-06, from the CSV)

### 4.1 Size and scope

- 1,298 applications, 81 columns, 12 districts (mapped), 65 blocks (mapped), 58 assembly constituencies.
- Extract date in the file name: 2026-11-01. Latest `createddate`: 19 Oct 2026.

### 4.2 Grain and keys

| Key | Distinct | Duplicates |
|---|---:|---|
| `id`, `request_id` | 1,298 | none, so **one row = one application** |
| `member_id` | 1,279 | 17 values on 36 rows (19 extra rows) |
| `epic_id` (232 NULL) | 1,053 | 13 values on 27 rows |
| `family_id` (12 NULL) | 1,261 | 24 values on 50 rows |
| `mobile_number` | 1,278 | 18 values on 38 rows |
| name + date of birth | — | 36 rows |

All 19 extra rows are repeat applications with status **Unknown**. Each repeating person has one
Pending or Approved application plus one or two Unknown ones. This suggests "Unknown" partly
marks superseded duplicates (to be confirmed with the client, HS-02). The scheme rule "one unit
per family" is therefore breached on paper for 24 `family_id`s. That is a verification
question, not an answer the bot may give about individuals.

### 4.3 Components (`response_type`)

| Stored value | Rows | Component | Columns it fills |
|---|---:|---|---|
| `Development of New Homestay` | 1,274 | 1 — new homestay | rooms, solar, rainwater, waste, declaration, proposed-site columns |
| `Updragation of New Homestay` | 24 | 2 — upgradation of an existing homestay | establishment name/district/address, M-TIME, bookings, area, room JSON, fund utilisation |

- All 24 upgradation applications are `file_status = Pending` (7 in 2025-26, 17 in 2026-27).
- Every upgradation application says it is registered on M-TIME (`TRUE`), as the scheme requires.
  12 report room bookings in the last 6 months; 12 do not.
- The upgradation room counts sit only inside the `tourism_upgradation_room_details` JSON
  (122 rooms across the 24). `homesaty_rooms` is NULL for them.
- **No Boutique (Component 3) applications exist.** Questions about boutique homestays are
  answered as "none recorded in this feed", plus the scheme fact.

### 4.4 Status: three columns, one verification flag

| `file_status` → | Approved | Pending | Rejected | Unknown | Total |
|---|---:|---:|---:|---:|---:|
| `current_file_status` Approved | 80 | | | | 80 |
| Forward | | 1,078 | 2 | 134 | 1,214 |
| Sendback | | 3 | | | 3 |
| Resubmit | | 1 | | | 1 |
| **Total** | **80** | **1,082** | **2** | **134** | **1,298** |

- `current_level`: `level1` 733 (all Pending or Rejected), `Level4` 565 (all 80 Approved,
  351 Pending, all 134 Unknown). The casing is inconsistent, so compare with `lower()`.
  What the levels are (district → state?) is not documented (HS-03).
- **All 80 approvals are in FY 2025-26** (applications created Oct 2025 – Mar 2026). No 2026-27
  application has been approved yet.
- Approval rate = 80 / 1,298 = **6.2%** of all applications (15.8% of 2025-26).
- `data_verified`: Valid 1,145, Invalid 93, On Hold 23, Wrong 5, NULL 32 (all in 2026-27, not
  yet verified). "Invalid" and "Wrong" are kept separate because the use cases ask for each.
  Of the 80 approved, 1 is Invalid and 1 is On Hold (a DQ caveat).
- `onhold` is FALSE on every row. **On hold lives in `data_verified = 'On Hold'`**, the same
  trap as CM Elevate.
- `is_withdraw` is FALSE on every row, so withdrawn = 0 (not "unknown").

Default meaning of a bare "status" = `file_status`. "Forward", "sendback" and "resubmit" resolve
to `current_file_status`. "Verified", "invalid", "on hold" and "wrong" resolve to `data_verified`.

### 4.5 Geography

- **Use the `mapped_*` columns.** `district_lgd_code` and `mapped_district_lgd_code` differ on
  14 rows: 13 *Eastern West Khasi Hills* (740) → *West Khasi Hills* (279), and 1
  *West Garo Hills* → *South West Garo Hills* (663). Raw `district` spells `Ri-bhoi`; mapped
  spells `Ri Bhoi`.
- Raw `block_lgd_code` (57 values) is an older code series. `mapped_block_lgd_code` (65) is the
  LGD 1960-series used by Homestay Legacy and NRLM. Every mapped block code has exactly one
  name. Urban bodies appear as blocks (e.g. *Tura Municipal Board-Municipal Board* 94,
  *Shillong-Municipal Board* 39, *Nongstoin-Town Committee* 41).
- Village: `mapped_village_lgd_code` and `mapped_constituency_*` are NULL on the **same 64
  rows**. Report these as "Unresolved", never drop them. 9 village names carry more than one
  code (Jarain, Lapalang, Lumsohphoh, Mawdiangum, Mawpdang, Nongbah, Nonglang, Nongthymmai,
  Umjarain), so villages are resolved by code.
- **Home address vs proposed site.** `district_of_proposed_location` differs from the home
  district on 145 rows (24 of them are the NULL upgradation rows). `block_of_proposed_location`
  holds **tourism clusters** (Sohra Cluster 113, Nongstoin Cluster 115, Tura (Municipal) 103,
  Wari Chora Cluster 77, Dawki Cluster 36 …), not LGD blocks, and must not be mixed with
  `mapped_block_lgd_name`. For upgradation rows the site is `district_of_establishment`.

### 4.6 Data-quality findings (each becomes a caveat or a gate rule)

| # | Finding | Rows |
|---|---|---:|
| DQ-1 | `homesaty_rooms = 3500` (id 598, Ri-bhoi, Pending). Total rooms 8,613 with it, **5,113 without**. Room sums and averages must exclude it, and say so | 1 |
| DQ-2 | Applicant aged 9 at application (DOB 2016) | 1 |
| DQ-3 | "Youth (18-35 yrs)" applicants aged 36 or more at application | 41 |
| DQ-4 | Male applicants in the "Women" category | 4 |
| DQ-5 | Lease shorter than the 7-year scheme minimum (5 years) | 4 |
| DQ-6 | Leased land with no lease period recorded | 3 |
| DQ-7 | Malformed lease start year (`20`→2046, `10`→2035; plus `1`→`15` counted in DQ-6) | 2 |
| DQ-8 | `end − start ≠ difference_lease_year` (otherwise well-formed) | 1 |
| DQ-9 | Date of birth NULL | 2 |
| DQ-10 | `pds_id` stored in scientific notation (`1.71E+11`), so the value is destroyed | 618 |
| DQ-11 | Approved but `data_verified` Invalid (1) or On Hold (1) | 2 |
| DQ-12 | Repeat applications by the same `member_id` (all status Unknown) | 19 |

Use case 33 ("lease period needs review") = DQ-5 + DQ-6 + DQ-7 + DQ-8 = **10** leased applications, reported as counts.

### 4.7 What the data cannot answer

- **Any money figure**: project cost, loan sanctioned or disbursed, subsidy, grant, EMI
  support, PMEGP share. There is no money column.
- **Project start / end / duration** (use cases 43–44): both columns are NULL on every row.
- Construction progress, operational status, bed-nights, guest footfall, training completion,
  which of the 33 designs was chosen, bank, sanction letter, rejection reason.
- Caste / ST / PwD subsidy rate claimed. `applicant_category = 'Differently Abled'` (7) is the
  only PwD signal and is not a certificate.
- Anything about a named individual.

---

## 5. Personal-data list (never in an answer, export, sample value or embedding)

`first_name`, `middle_name`, `last_name`, `date_of_birth`, `mobile_number`, `email_id`,
`address`, `pincode`, `epic_id`, `family_id`, `member_id`, `pds_id`, `mtime_portal_id`,
`address_of_proposed_location`, `pincode_of_proposed_location`, `address_of_establishment`,
`pincode_of_establishment`, `establishment_manager_self`, and the free-text fields that
can carry names (`waste_managment_remarks` holds a person's name and address on one row;
`category_remarks`; `fund_utilization_home_stay_remarks`).

Allowed uses: age **bands** derived from `date_of_birth`; `COUNT(DISTINCT member_id)`;
**counts** of duplicated identifiers (use case 45) without the values. `establishment_name` is
a business name; it may be shown only for the 24 upgradation homestays and only on request
(open question HS-05).

---

## 6. Question scope: the 45 Homestay API use cases

**A = answer, D = answer with a stated default, C = answer with a caveat, R = refuse with an offer.**

| # | Use case | Scope | Column / rule |
|---|---|---|---|
| 1 | Applications in a FY | A | `financial_year`; 2026-27 partial |
| 2–7 | District / block counts, highest, lowest, comparison, top 10 blocks | A | `mapped_district_*`, `mapped_block_*` |
| 8 | Overall status breakdown | D | `file_status` |
| 9 | Approved | A | `file_status = 'Approved'` → 80 |
| 10 | In Forward status | A | `current_file_status = 'Forward'` → 1,214 |
| 11 | Approval rate | C | 80 / 1,298 of all applications; say that 2026-27 has none approved yet |
| 12–13 | District-wise approved / forward | A | |
| 14–19 | Verification status, Invalid, On Hold, Wrong, by district | A | `data_verified`; NULL = "not yet verified" (32). Use case 17 "identify" = counts by district, never names |
| 20–22 | Application mode, CM Connect, online | A | `application_mode` |
| 23–28 | Applicant category (Youth, Women, FGE, Differently Abled), by district | C | DQ-3, DQ-4 caveats |
| 29–30 | Gender, female by district | A | `gender_id` |
| 31–32 | Owned vs leased, leased by district | A | `type_of_land_holding` |
| 33 | Lease-period review | C | DQ-5..8 as counts |
| 34–37 | Rooms: distribution, total, >10 rooms, district-wise | C | New-build only; exclude DQ-1 outlier; upgradation rooms are in JSON |
| 38–42 | Rainwater, solar, waste, green comparison, both | C | New-build only (1,274); upgradation rows have no value |
| 43–44 | Project timeline / duration | **R** | `project_start_date`, `project_end_date` all NULL; offer application dates (`createddate`) instead |
| 45 | Duplicate EPIC / Family / Member IDs | C | Counts only (13 / 24 / 17 values); never list the IDs |

Plus questions **not in the workbook** that the gate must handle:
- "How much subsidy / loan / money" → R (no money), offer the scheme's rates as a scheme fact.
- "How many homestays are operational / under construction / disbursed" → R here and redirect
  to **Homestay Legacy**, which has loan status.
- Bare "homestay" with no hint → ask: applications (this feed) or disbursed loans (Legacy).
- "Boutique homestays" → answer 0 recorded, plus the Component 3 scheme fact.
- "Upgradation" questions → `response_type`, always restating that only 24 exist.
- Eligibility, documents, how to apply, helpline → scheme-fact answer from the reference or FAQ,
  not SQL.

The **HomeStay Legacy** sheet (39 use cases: operational, under construction, loan not
disbursed, closed, cancelled …) belongs to `Annotations/Homestay_Legacy/`, not here.

---

## 7. Database alignment: not loaded yet

| Item | State |
|---|---|
| Fact table | none. Expected `curated.fact_homestay_application` (name to confirm) |
| View | none. Placeholder **`curated.v_homestay`** |
| Reconciliation | none. Expected `meta.v_reconciliation_homestay` |
| `dim_scheme` row | none. Expected code `HOMESTAY` (vs existing `HOMESTAY_LEGACY`) |
| Money unit | not applicable (no money column) |

Until the view exists, stage2 describes the **expected** view columns: the non-personal CSV
columns, renamed to the house conventions (`district_lgd_code`/`district_name` from the
`mapped_*` pair, `block_lgd_code`, `village_code`, `ac_number`, `ac_name`, `region`, typed
booleans such as `is_approved`, `has_solar`, `has_rainwater_harvesting`, `is_upgradation`). Every
figure is marked `unverified_in_db`. When the loader lands: re-run §11, align column names and
order to the live view, and log the diff in §13.

---

## 8. How each YAML will be built

Same order and shapes as PMAY v2.0, with the CMSS verification method (build a SQLite
emulation of the view from the CSV, execute every SQL, fill few-shot `expected` by script).

1. **`homestay_schema_partitions.yaml`**: expected view columns (§7), semantic rules (§4),
   NL→SQL rules (status pinning, mapped geography, new-build-only facility columns, rooms
   outlier, `COUNT(DISTINCT member_id)` for people), few-shot including refusals.
2. **`homestay_classification_rules.yaml`**: critical refusals first (money, project dates,
   personal data, operational/construction → Legacy, bare "homestay" → ask), then status
   ambiguity, home vs site geography, partial year, cluster vs block.
3. **`homestay_default_rules.yaml`**: applications = `COUNT(*)`; status = `file_status`;
   district = mapped home district; all years unless one is named; facility questions =
   new-build only; rooms exclude the outlier; top N = 5. No overlap with the gate.
4. **`homestay_entity_resolver.yaml`**: 12 districts (raw and mapped spellings, acronyms),
   65 mapped blocks, 38 tourism clusters, 58 ACs, village ambiguity registry (9 names),
   the status, category, mode, response-type, land and waste vocabularies, and blocked pairs.
5. **`homestay_few_shot.yaml`**: one example per answerable use case, `FROM curated.v_homestay`
   only, with `expected` from the CSV.
6. **`homestay_foreign_key_augmentation.yaml`**: dim joins (geography, year, scheme);
   aggregate-then-combine with Homestay Legacy and other schemes by district or block;
   prohibited row joins on `member_id`, `epic_id` or `family_id`.
7. **`homestay_response_template.yaml`**: mandatory caveats (applications ≠ people,
   2026-27 partial, no money in this feed, new-build-only facilities, rooms outlier, "Unresolved"
   villages, not the Legacy loan register) and refusals worded as redirects.

---

## 9. Golden questions (expected answers from the CSV, 2026-11-06)

| Question | Answer |
|---|---|
| Total applications | **1,298** (1,279 distinct applicants) |
| By FY | 2025-26: 505 · 2026-27: 793 (to 19 Oct 2026) |
| By type | New homestay 1,274 · Upgradation 24 · Boutique 0 |
| `file_status` | Pending 1,082 · Unknown 134 · Approved 80 · Rejected 2 |
| `current_file_status` | Forward 1,214 · Approved 80 · Sendback 3 · Resubmit 1 |
| Approval rate | 6.2% (80 / 1,298) |
| `data_verified` | Valid 1,145 · Invalid 93 · On Hold 23 · Wrong 5 · not yet verified 32 |
| Highest district (mapped) | East Khasi Hills 342; then West Garo Hills 209, West Khasi Hills 125 |
| Lowest district (mapped) | South West Garo Hills 17 |
| Top blocks (mapped) | Tura MB 94 · Rongram 91 · Shella Bholaganj 87 · Mawkyrwat 49 · Wapung 47 |
| Approved by district, top | East Khasi Hills 23 · South West Khasi Hills 11 · West Garo Hills 10 |
| Invalid by district, top | West Garo Hills 25 · East Jaintia Hills 14 · Ri Bhoi 11 |
| Gender | Female 681 · Male 617 |
| Female by district, top | East Khasi Hills 154 · West Garo Hills 138 · West Khasi Hills 69 |
| Category | Youth 491 · Women 479 · First Generation Entrepreneur 214 · Other 107 · Differently Abled 7 |
| Mode | Online 1,235 · CM Connect Centre 63 |
| Land | Owned 1,005 · Leased 293 (top leased: East Khasi Hills 90) |
| Rooms (new-build) | 5,113 excluding the 3,500 outlier (8,613 with it); 35 applications over 10 rooms |
| Rooms by district, top | East Khasi Hills 1,325 · West Garo Hills 609 · West Khasi Hills 570 |
| Solar / Rainwater / both | 976 / 937 / 843 of 1,274 new-build |
| Waste management | Composting 579 · Segregation 456 · Recycling 194 · Other 45 |

Full district tables (status × district, FY × district) are re-derived from the CSV by the
profiling script and are not to be copied by hand.

---

## 10. Open questions for the client (HS-xx)

| # | Question |
|---|---|
| HS-01 | When will the feed be loaded to `megh_db`, and under which fact/view names and scheme code? |
| HS-02 | What does `file_status = 'Unknown'` mean? All 19 repeat applications are Unknown. |
| HS-03 | What are `level1` and `Level4` (which office)? Are there levels 2 and 3? |
| HS-04 | Is "Updragation of New Homestay" Component 2 (upgradation of an *existing* homestay)? |
| HS-05 | May `establishment_name` (24 upgradation homestays) be shown? |
| HS-06 | Is "Approved" the DTO/Task Force recommendation or the bank sanction? |
| HS-07 | Will cost, loan, subsidy or construction status ever arrive in this feed? |
| HS-08 | The 3,500-room row (id 598) and the age-9 applicant: data-entry errors to be fixed at source? |
| HS-09 | Which geography does the department report by: applicant home or proposed site / cluster? |

---

## 11. Regeneration checklist (new extract)

1. Drop the new CSV into `datasets/Homestay/`; never overwrite the old one.
2. Re-run the §3 steps; diff the column list (81) and the status vocabularies.
3. Re-check: FY range, the partial year's end date, the outlier, repeat applicants, mapped vs raw.
4. Regenerate resolver catalogues and few-shot `expected`; re-run the §7 checks of
   `Annotations/README.md`.
5. Update §9 and the change log.

---

## 12. House rules

All of `Annotations/README.md` §6 apply. In addition, for Homestay:

1. **No YAML is created or edited without an explicit instruction naming the file and the change.**
2. Never answer a money question from this feed. Scheme rates are scheme facts, labelled as such.
3. Never mix this feed with Homestay Legacy row by row, and never let a bare "homestay" pick one silently.
4. Applications ≠ applicants ≠ homestays. Say which one every figure counts.
5. Facility columns (rooms, solar, rainwater, waste) describe new-build applications only.
6. `block_of_proposed_location` is a tourism cluster, not an LGD block.
7. Never use `onhold` or `is_withdraw`. On hold is `data_verified = 'On Hold'`.

---

## 13. Change log

| Date | Change |
|---|---|
| 2026-11-04 | Folder created with 7 empty YAMLs and an empty README. |
| 2026-11-06 | README written: CSV profiled (1,298 × 81), scheme reference and FAQ read, 45 API use cases scoped, golden answers derived, open questions HS-01..09 listed. No YAML touched. |
| 2026-11-06 | **All 7 YAMLs written (v1.0), in order** schema_partitions → classification_rules → default_rules → entity_resolver → few_shot → foreign_key_augmentation → response_template, on the user's instruction to build them one after another. Built against CMSS v1.0 and PMAY v2.0 shapes, for the placeholder view `curated.v_homestay` (52 columns designed to house conventions: mapped LGD geography, `is_upgradation`, `is_approved`, `age_years`, `upgradation_rooms` from the room JSON, and the flags `is_repeat_applicant`, `is_room_count_outlier`, `has_name_code_conflict`). A SQLite emulation of that view was built from the CSV; all 168 executable SQLs ran clean and every `expected` / `result` was filled by script. Resolver catalogues generated by script and reconciled to 1,298. |
| 2026-11-06 | **Corrections found by the executed checks** and applied to this README and stage2: home vs site district differ on **113** new-build rows (145 was against the raw district); "Youth" applicants over 35 = **41** in completed years (55 counted 35.x); lease-review split = 4 short + 3 no period + 2 malformed start + 1 inconsistent = **10**. |
