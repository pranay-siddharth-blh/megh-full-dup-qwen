# CM Elevate sheet — summary

Workbook: `reference_documents/Test Case Results - 30th Sep 26.xlsx` (read only; never modified).
Sheets (7): `General`, `MGNREGA`, `PMAY-G`, `CM Elevate`, `Focus +`, `FOCUS Legacy`, `CM Elevate Legacy`.
The sheet under test is named exactly **`CM Elevate`** (casing as written). `CM Elevate Legacy` is a different
dataset (sanctions / disbursements, `v_cm_elevate_disbursement`) and is out of scope.

## Columns
| Column | Meaning |
|---|---|
| TC ID | CM-ELEVATE-OFF-001 … 030 |
| Test Scenario | what the case covers |
| Test Input / Action | a question TEMPLATE with slots: [district], [block], [village], [program], [sector], [status], [level/status] |
| Expected Result | a rule in words ("Return the total number of applicants …"), never a number |
| Actual Result / Status / Remarks | first round |
| Comment / Status on 14 Sep, 22nd Sep, 30th Sep | later rounds |
| 9th Result / 9th Remarks | run of 2026-10-09/10 |
| After Fix / After Fix Remarks | latest round (2026-10-10) |

## Cases: 30, every one with an expected result; no duplicate IDs
| Round | Pass | Fail | Not run |
|---|---|---|---|
| Status (first round) | 9 | 21 | 0 |
| 14 Sep | 1 | 29 | 0 |
| 22 Sep | 11 | 19 | 0 |
| 30 Sep | 24 | 6 | 0 |
| 9th run | 20 | 10 | 0 |
| After Fix (2026-10-10) | 30 | 0 | 0 |

## The 30 templates
| TC | Scenario | Slots |
|---|---|---|
| 001 | district applicant count | district |
| 002 | block applicant count | block |
| 003 | village applicant count | village |
| 004 | district-wise distribution | — |
| 005 | programme-wise distribution | — |
| 006 | programme × district | program, district |
| 007 | programme × block | program, block |
| 008 | programme × village | program, village |
| 009 | 2 programmes in a district + combined | district, program ×2 |
| 010 | 3 programmes in a block + combined | block, program ×3 |
| 011 | sector-wise distribution | — |
| 012 | sector × district | sector, district |
| 013 | programme × sector | program, sector |
| 014 | 2 programmes × sector × district + combined | |
| 015 | overall status distribution | — |
| 016 | status distribution for a programme | program |
| 017 | status distribution in a district | district |
| 018 | pending at a level | level |
| 019 | programmes ranked by pending | — |
| 020 | districts ranked by pending | — |
| 021 | pending × programme × district | |
| 022 | data verification in a district (verified, non-verified, rate) | district |
| 023 | on hold × programme × district | |
| 024 | withdrawn × programme / all × district | |
| 025 | 3 programmes × district by sector: applicants + pendency | |
| 026 | village-wise counts for a programme in a block | program, block |
| 027 | 2 programmes × 2 districts comparison | |
| 028 | pending by sector in a district | district |
| 029 | 2 programmes × status × district + combined | |
| 030 | status-wise counts for a programme in a village | program, village |

Because the expected results are rules, every expected figure in this UAT is computed independently by SQL on
the live DB (see scheme_map.md for the definitions) and stored in test_matrix.csv beside each question.
