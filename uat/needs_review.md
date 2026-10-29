# Needs review — shared (non-CM-Elevate) code

## A. Shared-code hunks already in the v1 patch (made before the 2026-10-30 ~01:50 instruction)
These were written by the earlier session for CM Elevate failures, before the "CM Elevate code only" rule.
They are in `cm_elevate_changes_v1.patch` (commit e3d7758). Each affects other schemes too; please review.
Offline suites over these areas passed (1,462 tests) in the main folder before the split.

| Bug | File | Change | Reach |
|---|---|---|---|
| B1 | c11_sql_verify_repair.py `_verify_sql` | the verifier sees the question without the level-chip tail (`_c01_strip_chip_level`) | all schemes |
| B2 | c10_sql_generation_and_rewrites.py | `_pin_missing_twin_codes` + `_c10_group_by_cols`: twin villages with no code in the SQL get `village_code IN (…)`, per village | all village schemes, only on J-10 twins |
| B5 | edge.py `_SCHEME_STRONG` | CM Elevate programme names as typed | edge layer |
| B6 | spelling.py `_NOT_A_PLACE` | `level`, `levels`, `hold` are not places | unknown-place check |
| B7 | c09 | ward truncation check compared on letters only (`_c09_alnum`) | collision gate |
| B8 | c12 `_finish_answer`, `_framed_fallback` | no "across all financial years" when every scheme has no years | only CM Elevate in practice |
| B12 | entity_resolver.py `_REGION_ALL_CUE` | "region" expands a region to its districts | all schemes |
| B13 | c09 | a name labelled district/block/constituency is not retried as a village | all schemes |
| B15 | c09 `_c09_level_after` | a typed level word settles the admin-level collision | all schemes |
| B16 | c09 | same-name village narrowed by the block named in the text | all village schemes |
| B17 | spelling.py | no district/block rewrite inside an exact village name; `across`/`between`/… end a place span | spelling pre-pass |

## B. Proposed shared-code changes found during the exhaustive run (NOT applied)
(appended below as found)
