# CM Elevate — scheme map (live DB, 2026-10-30)

## Data
| Object | Use |
|---|---|
| `curated.v_cm_elevate` | the dataset: 8,948 rows, **8,921 applications** (`COUNT(DISTINCT request_id)`; 27 duplicate rows) |
| `curated.dim_cm_elevate_scheme` | the 15 programmes |
| `curated.dim_geography` | village master list (7,436 village codes) and the constituency join (`geography_key`, `ac_name`) |
| `curated.fact_cm_elevate_application` | never queried by the app |

## Code
- `app/pipeline/schemes/cm_elevate.py` — the scheme file (terms, dataset pin vs CM Elevate Legacy, fixed sector /
  workflow queries, SQL rewrites, answer guarantees)
- `data/cm_elevate/*.yaml` — classification, defaults, resolver catalogue, few-shots, response template, schema notes
- `app/scheme_registry.py` (facts), `app/entity_resolver.py` (catalogues, regions, villages)
- shared steps `app/pipeline/common/c01…c17`, `app/edge.py`, `app/spelling.py`

## Hierarchy (as stored)
| Level | Count | Note |
|---|---|---|
| Region | 3 | `region`: Garo (5 districts), Khasi (5, incl. Ri Bhoi), Jaintia (2) |
| District | 12 | `lgd_district` |
| Block | 67 stored (66 places) | urban bodies are blocks ("SHILLONG-MUNICIPAL BOARD"); Tura MB is stored under TWO spellings |
| Village / Ward | 2,170 codes with data | `village_code`, `entity_type` Village / Ward / Unresolved (53 applications unresolved) |
| Assembly constituency | 60 | `ac_name` (also via `dim_geography`); 4 span two districts; 35 blocks split across ACs; 115 block×AC pairs |
| Parliamentary constituency, Gram Panchayat | — | not in the data |

## Dimensions
| Dimension | Column | Values |
|---|---|---|
| Programme | `scheme_name` | 15 |
| File status ("status") | `current_file_status` | forward 8,915 / resubmit 3 / sendback to vdv/citizen 3 |
| Data verification | `data_verified` | Valid 7,371 / On Hold 906 / Invalid 494 / Wrong 87 / NULL 63 |
| Workflow level | `current_level` | level0 3 / level1 8,607 / level2 310 / level4 1 |
| Applicant category | `applicant_category` | individual / registered / unregistered |
| Application mode | `application_mode` | online / cmconnectcenter |
| Sector | `sector_id` | Poultry 22, Dairy 7, Piggery 7, Goatery 1, NULL 8,884 |
| Withdrawn / on-hold flags | `is_withdraw`, `onhold` | always FALSE |
| Financial year, month, date | — | **none: CM Elevate has no time dimension** (`_SCHEME_DATA_YEARS["CM Elevate"] = []`) |
| Money / amount types, sanction stage | — | **none** (money and sanctions are CM Elevate Legacy) |
| Named beneficiaries | — | **none exposed** (no names; `request_id` only) |

## Definitions used for expected values (code and team decisions)
- applications = applicants = `COUNT(DISTINCT request_id)` (D-049, D-090)
- "status" = `current_file_status` (KI-123)
- "on hold" = `data_verified = 'On Hold'`; "verified" = `'Valid'`
- "pending": the data records no pending status (ingestion team 2026-10-26, KI-422); the bot says so and gives the
  recorded figures — on hold at data verification; "pending at level N" = applications currently at level N (KI-070)
- village counts exclude `entity_type = 'Unresolved'`
- sector = `sector_id`; "(not recorded)" for NULL
