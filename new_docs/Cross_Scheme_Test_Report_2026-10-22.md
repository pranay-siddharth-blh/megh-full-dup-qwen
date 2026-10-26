# Cross-Scheme UAT Test Report — 22 Oct 2026

**Scope:** all 60 test cases (T01.1 … T20.3) in `raw_uc/cross_scheme.xlsx`, tab "UAT Test Report". They cover MGNREGA, PMAY-G,
Focus+ and FOCUS (Focus Legacy); CM-ELEVATE appears only as a scheme to exclude. Each question was asked **in a new chat**,
live through the chatbot (LangGraph pipeline, real models, live `megh_db`). Each answer was checked twice:

1. **vs raw files**: answer keys computed independently from the source files in `raw_uc/`
   (`MGNREGA_Employment.xlsx`, `Updated MNGREGA Expenditure WIth Year.xlsx`, `PMAY_FullyMapped_with_dates.xlsx`,
   `Focus Plus Master.csv`, `Focus Legacy to share to BLH.csv`);
2. **vs DB**: the same figures computed from the `megh_db.curated` views (read-only, by LGD district / block).

**No app code, data or docs of the app were changed for the test** (report only). The raw Focus+ and Focus Legacy files
hold names, phone numbers and bank accounts. They were only counted and summed; no row of either file appears here or in
the CSV.

Files: this report, plus `new_docs/Cross_Scheme_all_queries_2026-10-22.csv`, which has every question, both verdicts,
the figures matched and the bot's full answer.

## 1. Summary

| Check | Result |
|---|---|
| Raw answer key vs the sheet's "Expected result" column | **Match.** Every state, district, block, FY, combined, ranking and average figure in the sheet reproduced exactly |
| Raw files vs DB (459 figures: 4 schemes × state / 12 districts / 3 blocks / FY 2025-26 × each measure) | **411 match, 48 differ.** All differences are in Focus+ (district WGH/SWGH, villages, blocks) and MGNREGA households (WGH/SWGH); see §4 |
| **Bot vs raw files** | **20 / 60 pass, 40 fail (33%)** |
| **Bot vs DB** | **17 / 60 pass, 43 fail (28%)** |
| Pass against both | 15 / 60 |
| Testers' run of 15 Oct (same sheet) | 21 / 60 pass (9 of those were the bot asking a question back, which the sheet accepts as Pass) |
| Clarification questions today | 1 (T13.2, a needless "CM Elevate (applications) or Legacy?"). So the sheet's rule "a follow-up question counts as Pass" changes nothing today |
| Fixed since 15 Oct | 7: T01.3, T03.1, T06.1, T06.2, T06.3, T13.3, T19.3 |
| Passed on 15 Oct, fail today | 8: T08.3, T09.3, T10.3, T12.1, T12.3, T13.2, T19.2, T20.3 (six of these were Pass on 15 Oct only because the bot asked back; today it answers, wrongly) |

**Pass rule.** Every figure the expected answer needs must be in the answer: in the text, or in the table the chat shows
(`data`). Counts must be exact. ₹ amounts must match to the rounding shown (crore, lakh or rupees). The measure must be
the right one (households, not person-years; members, not producer groups; PMAY-G **released**, not sanctioned). And the
answer must give what the question asks: a combined total, a ranking, a per-district winner, an exclusion. For a plain
"compare A and B", side-by-side figures count as the answer, as the testers accepted on 15 Oct (T02.1, T05.2).

**Why the two columns differ.** For Focus+ West Garo Hills / South West Garo Hills the raw district name and the DB's LGD
district give different numbers (35,059 vs 35,039 and 15,274 vs 15,294). The bot sometimes groups by one and sometimes by
the other, so a case can pass against one source and fail against the other (T02.3, T03.x, T06.x, T08.2).

## 2. What is still broken (40 failures, grouped)

| # | Defect | Cases | New KI |
|---|---|---|---|
| 1 | **Cross-scheme results are never computed.** No combined total, no combined district ranking, no per-district winner or second place, no "districts where X > Y". The bot lists each scheme separately and stops | T01.1, T03.3, T04.2, T07.1, T15.1, T15.2, T15.3, T16.2, T18.1, T18.2 | KI-387 |
| 2 | **"Excluding / leaving out" ignored or reversed.** Shows the excluded schemes (T07.2); routes to the CM Elevate documents (T11.2, T13.2); includes CM Elevate Legacy (T12.2) and MGNREGA (T15.3) | T07.2, T11.2, T12.2, T13.2, T15.3 | KI-388 |
| 3 | **MGNREGA dropped or incomplete in district / overall answers**: "No MGNREGA figure could be worked out", or per-year rows with no total. T14.1 was fully right in run 1 and failed in run 2 (unstable) | T13.1, T14.1, T14.2, T14.3, T17.1, T17.2, T20.1, T20.2 | KI-389 |
| 4 | **Per-scheme part returns the wrong grain or leaves the count out**: villages / single house rows instead of a district total (T07.3); money only, counts left out (T08.1, T08.3, T14.3); totals only, no per-district split (T16.2) | T07.3, T08.1, T08.3, T14.3, T16.2 | KI-389 |
| 5 | **Wrong measure or unit**: PMAY-G sanctioned ₹2,222.75 Cr given as the amount (expected ₹2,185.26 Cr released); FOCUS producer groups called beneficiaries; the FOCUS average copied from Focus+ (₹11,316.12, expected ₹5,000); a payment count shown as "₹292,385 lakh crore"; MGNREGA headline in person-years; money compared where beneficiaries were asked | T01.2, T10.3, T12.1, T12.3, T16.1, T18.3, T19.1, T19.2, T20.3 | KI-390 |
| 6 | **FOCUS state totals cut to mapped rows**: 94,116 members / ₹47.06 Cr / 10,998 PGs (correct: 1,02,021 / ₹51.01 Cr / 11,906) | T20.1 | KI-392 |
| 7 | **Block coverage**: Dadenggiri answered from the scheme documents; Songsak drops FOCUS and the village counts; Focus+ Mylliem 49 villages (raw 27, DB 35) | T09.1, T09.2, T09.3 | KI-391 |
| 8 | **Raw vs DB data differences** shown in answers (Focus+ WGH/SWGH; MGNREGA WGH/SWGH; Focus+ village counts) | T02.3, T08.2, T17.2, T17.3 (+ DB column of T03.x, T06.x) | KI-393 (data) |

Cosmetic defects in passing answers: T10.2 prints "₹119.7392500000000000 crore". T13.3 lists an unlabelled "(row)"
record as the lowest district. T03.1 / T06.x show a "(no label) — 1" Focus+ row (the one record with no district).

## 3. Result per test case

Raw / DB: today's verdict against each answer key. 15 Oct: the testers' status in the sheet.

| Test | Question (short) | 15 Oct | Raw | DB | Reason / note |
|---|---|---|---|---|---|
| T01.1 | Total beneficiaries across 4 schemes | Fail | ✘ | ✘ | All four figures right (14,94,437 / 1,71,107 / 1,05,813 / 1,02,021) but the asked total 18,73,378 is not given |
| T01.2 | Scheme-wise beneficiaries, 4 schemes | Fail | ✘ | ✘ | MGNREGA headline is person-years 18,65,234, not households 14,94,437 (households only in the table) |
| T01.3 | Each scheme, FY 2025-26 | Fail | ✔ | ✔ | MGNREGA 3,65,556; PMAY-G no FY 2025-26 data; Focus+ 1,05,813; FOCUS 37,018 members / 8,806 PGs |
| T02.1 | Focus+ or FOCUS more beneficiaries | Pass | ✔ | ✔ | 1,05,813 vs 1,02,021 members (winner not stated in words) |
| T02.2 | Focus+ vs old FOCUS | Pass | ✔ | ✔ | 1,05,813 vs 1,02,021 members / 11,906 PGs |
| T02.3 | Focus+ vs FOCUS, West Garo Hills | Fail | ✘ | ✔ | Focus+ 35,039 (DB LGD) vs raw 35,059; FOCUS 21,867 right |
| T03.1 | Focus+ vs PMAY-G by district | Fail | ✔ | ✘ | All 24 figures = raw (Focus+ by raw district name); DB LGD differs on WGH/SWGH |
| T03.2 | Focus+ vs FOCUS by district | Pass | ✔ | ✘ | All 24 figures = raw; same WGH/SWGH DB difference |
| T03.3 | Districts where Focus+ > PMAY-G | Fail | ✘ | ✘ | Lists PMAY-G only, "Focus Plus has no records"; expected SWGH and WGH |
| T04.1 | Amount disbursed, 3 schemes | Pass | ✔ | ✔ | ₹119.74 / 51.01 / 2,185.26 Cr |
| T04.2 | Money released, 3 schemes combined | Fail | ✘ | ✘ | Combined ₹2,356.01 Cr not given |
| T04.3 | Focus+ and FOCUS, FY 2025-26 | Pass | ✔ | ✔ | ₹73.10 / 18.51 Cr |
| T05.1 | Higher disbursement Focus+ / FOCUS | Pass | ✔ | ✔ | ₹119.74 > 51.01 Cr, winner stated |
| T05.2 | PMAY-G or Focus+ more money | Pass | ✔ | ✔ | ₹2,185.26 vs 119.74 Cr |
| T05.3 | MGNREGA vs PMAY-G spend | Pass | ✔ | ✔ | ₹3,628.67 > 2,185.26 Cr, winner stated |
| T06.1 | Beneficiaries per district, 3 schemes | Fail | ✔ | ✘ | All 36 figures = raw; DB LGD differs on Focus+ WGH/SWGH |
| T06.2 | District-wise counts, 3 schemes | Fail | ✔ | ✘ | Same as T06.1 |
| T06.3 | FOCUS PGs and Focus+ per district | Fail | ✔ | ✘ | All 24 figures = raw; DB LGD differs on Focus+ WGH/SWGH |
| T07.1 | Highest scheme in each district | Fail | ✘ | ✘ | 49-row list, never names the leader; MGNREGA WGH 2,61,666 / SWGH 1,64,976 (DB) vs raw 2,61,221 / 1,65,421 |
| T07.2 | Leaving out MGNREGA & CM-ELEVATE | Fail | ✘ | ✘ | Shows exactly the two excluded schemes |
| T07.3 | Most beneficiaries in Ri-Bhoi | Fail | ✘ | ✘ | MGNREGA as 100 village rows, PMAY-G as single house rows; no totals, no winner |
| T08.1 | Focus+, FOCUS, PMAY-G in East Khasi Hills | Fail | ✘ | ✘ | PMAY-G house count 23,952 not given |
| T08.2 | Same, West Garo Hills | Fail | ✘ | ✔ | Focus+ 35,039 / ₹39.13 Cr (DB) vs raw 35,059 / ₹39.16 Cr |
| T08.3 | Same, Ri Bhoi | Pass | ✘ | ✘ | Money only; Focus+ 419 and PMAY-G 17,565 missing |
| T09.1 | Coverage in Mylliem block | Fail | ✘ | ✘ | Focus+ 49 villages (raw 27, DB 35); MGNREGA 56, PMAY-G 41 right |
| T09.2 | Coverage in Dadenggiri block | Fail | ✘ | ✘ | Answered from scheme documents, no figures |
| T09.3 | Coverage in Songsak block | Pass | ✘ | ✘ | FOCUS left out; no village counts |
| T10.1 | Total expenditure, 4 schemes | Pass | ✔ | ✔ | ₹3,628.67 / 2,185.26 / 119.74 / 51.01 Cr |
| T10.2 | Money per scheme in crore | Pass | ✔ | ✔ | Right; cosmetic "₹119.7392500000000000 crore" |
| T10.3 | MGNREGA vs Focus+, FY 2025-26 | Pass | ✘ | ✘ | "payments of ₹292,385 lakh crore" (a count shown as money); ₹916.06 / 73.10 Cr right |
| T11.1 | Money, West Jaintia Hills | Pass | ✔ | ✔ | ₹173.25 / 159.11 / 0.35 / 4.17 Cr |
| T11.2 | South Garo Hills excluding CM-ELEVATE | Fail | ✘ | ✘ | Routed to CM Elevate documents; no figures |
| T11.3 | Money, East Garo Hills | Pass | ✔ | ✔ | ₹321.79 / 216.44 / 12.62 / 2.75 Cr |
| T12.1 | Highest assistance, 4 schemes | Pass | ✘ | ✘ | PMAY-G ₹2,222.75 Cr sanctioned, not ₹2,185.26 Cr released |
| T12.2 | Leaving out CM-ELEVATE, most money | Fail | ✘ | ✘ | Includes CM Elevate Legacy; no winner stated |
| T12.3 | Most assistance + per beneficiary | Pass | ✘ | ✘ | PMAY-G sanctioned; no PMAY-G / FOCUS per-beneficiary figure |
| T13.1 | Widest coverage across districts | Fail | ✘ | ✘ | "No MGNREGA figure"; no state village totals; no conclusion |
| T13.2 | Excluding CM-ELEVATE, most villages | Pass | ✘ | ✘ | Needless CM Elevate dataset question, then a documents answer |
| T13.3 | Districts with very low Focus+ coverage | Fail | ✔ | ✔ | EJH, WJH, Ri Bhoi, EWKH with right counts (junk "(row)" first) |
| T14.1 | 4 schemes, North Garo Hills | Fail | ✘ | ✘ | "No MGNREGA figure" (run 1: all 8 figures right — unstable) |
| T14.2 | 4 schemes, West Khasi Hills | Fail | ✘ | ✘ | MGNREGA per year only; total 62,655 / ₹131.54 Cr missing |
| T14.3 | 4 schemes, Eastern West Khasi Hills | Fail | ✘ | ✘ | "No MGNREGA figure"; PMAY-G houses 5,494 missing |
| T15.1 | Highest concentration across 4 schemes | Fail | ✘ | ✘ | No combined district ranking (expected WGH 3,51,294 …) |
| T15.2 | Top 3 districts, combined | Fail | ✘ | ✘ | No combined top 3; adds "Focus Legacy 43,055 with no district" |
| T15.3 | Excluding MGNREGA, top districts | Fail | ✘ | ✘ | MGNREGA still included; no ranking |
| T16.1 | Focus+ vs FOCUS, 3 districts | Fail | ✘ | ✘ | FOCUS PGs called beneficiaries; Focus+ WGH 35,039 |
| T16.2 | Focus+ vs PMAY-G, 3 Garo districts | Fail | ✘ | ✘ | Only 3-district totals (44,828 / 30,998, right); no per-district split |
| T16.3 | Focus+ vs FOCUS, WJH / EJH / SWKH | Pass | ✔ | ✔ | All six figures right |
| T17.1 | District summary, 4 schemes | Fail | ✘ | ✘ | MGNREGA per year not per district; Focus+ missing from the text |
| T17.2 | District financial summary | Fail | ✘ | ✘ | MGNREGA per year; Focus+ WGH ₹39.13 / SWGH ₹16.68 Cr (DB) vs raw 39.16 / 16.64 |
| T17.3 | District beneficiary summary | Fail | ✘ | ✘ | MGNREGA WGH/SWGH = DB, Focus+ WGH/SWGH = raw: matches neither source fully |
| T18.1 | Highest scheme per district | Fail | ✘ | ✘ | Never names the highest scheme |
| T18.2 | Second after MGNREGA per district | Fail | ✘ | ✘ | Never names second place |
| T18.3 | Focus+ or FOCUS bigger per district | Fail | ✘ | ✘ | Compares money, says Focus+ bigger everywhere; by members FOCUS is bigger in 6 |
| T19.1 | Count + amount, 3 schemes | Fail | ✘ | ✘ | PMAY-G amount is sanctioned ₹2,222.75 Cr |
| T19.2 | Focus+ vs FOCUS incl. average | Pass | ✘ | ✘ | FOCUS average stated ₹11,316.12 (Focus+'s); correct ₹5,000 |
| T19.3 | Count + amount, Focus+ / FOCUS / MGNREGA | Fail | ✔ | ✔ | All six figures right |
| T20.1 | Overall coverage + money | Fail | ✘ | ✘ | No MGNREGA; FOCUS 94,116 / ₹47.06 Cr (mapped rows only) |
| T20.2 | Rank on coverage, beneficiaries, money | Fail | ✘ | ✘ | No MGNREGA; no ranking |
| T20.3 | Most money per beneficiary | Pass | ✘ | ✘ | PMAY-G ₹1,28,059 (sanctioned basis) vs ₹1,27,713; no FOCUS average |

## 4. Raw files vs DB

| Scheme | Raw vs DB | Detail |
|---|---|---|
| MGNREGA | Match except 2 districts | State 14,94,437 households, ₹3,628.67 Cr, 6,419 villages in both. **445 household-years sit in South West Garo Hills in raw (1,65,421) but in West Garo Hills in the DB (2,61,666 vs raw 2,61,221)**; 1 village moves the same way (543/977 vs 542/978). Expenditure matches everywhere |
| PMAY-G | **Full match** | 1,71,107 houses, 1,29,941 completed, 5,121 villages, ₹2,222.75 Cr sanctioned, ₹2,185.26 Cr released, every district. The 15 Oct issue "126 undated houses left out" is fixed: the bot now shows 1,71,107 |
| Focus+ | Differs | State 1,05,813 / ₹119.74 Cr match. By LGD district: West Garo Hills 35,039 (raw 35,059), South West Garo Hills 15,294 (raw 15,274), with matching ₹ shifts (₹39.13 / 16.68 Cr vs 39.16 / 16.64). Villages 3,513 in the DB vs 3,220 distinct raw LGD codes; blocks 59 vs 51; Mylliem / Dadenggiri block figures differ (raw block name vs LGD block) |
| FOCUS | **Full match** | 1,02,021 members, 11,906 PGs, 14,569 remittances, ₹51.01 Cr, 3,384 villages, every district and FY |

The Focus+ and MGNREGA differences are mapping choices in the ingested data. They belong to the ingestion team
(`megh-ingestion`) and are logged as KI-393; no data was changed.

## 5. How the test was run

- **Runner**: a scratch script drove `pipeline.answer_question` inside the app lifespan (the same entry the API uses),
  6 questions at a time, one new session per question. If the bot asked back, the neutral chip was tapped (all years /
  all of Meghalaya / compare / all of them). The run was done twice. Run 1 kept only the 20-row preview of each table,
  so it was repeated, and **run 2 (full table, as the chat shows it) is graded**. Between the two runs only T14.1
  changed verdict (it passed in run 1).
- **Answer keys**: raw = aggregates of the five source files; DB = the same measures from `curated.v_employment`,
  `v_expenditure`, `v_pmay`, `v_focus_plus`, `v_focus_legacy` by `lgd_district` / `lgd_block` / `year_key`. Definitions
  follow the sheet: MGNREGA beneficiaries = households employed, all FYs added; PMAY-G = every house record, money =
  released; Focus+ = distinct (batch, serial no.); FOCUS = members summed over remittances, PGs distinct.
- **Grading**: the figures each expected answer needs (1 to 96 per case, 623 in all) were checked automatically in the
  answer text and table. Then every answer was read for measure, unit and whether it answers the question.

## 6. After the fix (same day, D-066)

The issues above were fixed on the chatbot side, then the same 60 questions were run again, each in a new chat, and
graded with the same answer keys. Files: `new_docs/Cross_Scheme_all_queries_after_fix_2026-10-22.csv` has every case
before and after, with the full answer.

| Check | Before | After |
|---|---|---|
| Every figure matches **megh_db** | 17 / 60 | **59 / 60** |
| Every figure matches the **raw files** | 20 / 60 | **47 / 60** |
| Answers what was asked (read one by one) | — | **60 / 60** |
| Clarification questions | 1 (needless) | 1 (T09.3 "which Focus?", see below) |

**What changed in the bot:** combined totals, district rankings, the leading and second scheme per district,
"districts where X > Y" and per-beneficiary figures are now worked out in code from fixed per-scheme queries. The
other changes:
- "Excluding / leaving out" is read first.
- MGNREGA is always included.
- PMAY-G money is the amount released.
- FOCUS beneficiaries are its members.
- 'Unresolved' FOCUS rows are left out of village counts only.
- Focus+ is grouped by its source district names.
- Amounts below one crore are shown in lakh; counts use Indian grouping.

A bare "FOCUS" with no Focus+ beside it (T09.3) now asks "which Focus?" instead of being dropped; the test tapped
Focus Legacy, as the sheet means.

**What is left:**
- **T13.3** lists the low Focus+ districts by villages covered (East Jaintia Hills 14, West Jaintia Hills 25, Ri Bhoi
  32, Eastern West Khasi Hills 89), not by beneficiaries. It names the same four districts.
- **12 raw-file differences are data, not the bot (KI-393, ingestion team).** The bot gives the figure megh_db
  holds:
  - MGNREGA Genapara (LGD 274268, 445 household-years) is in West Garo Hills in the DB and South West Garo Hills in
    the raw file. This affects the WGH / SWGH figures in T07.1, T15.1, T15.2, T17.1, T17.3 and T18.1; no conclusion
    changes.
  - Focus+ village codes: 3,513 villages in the DB vs 3,220 raw LGD codes, and Mylliem 48 vs 27, Dadenggiri 130 vs 80.
    This affects T09.1, T09.2, T13.1, T13.2, T20.1 and T20.2. In **T09.2** it changes the conclusion: Focus+ shows
    the most villages in Dadenggiri (130) where the raw file gives MGNREGA (103 vs 80).

**Still to do outside the bot (ingestion team):** the catalogue items of the issues document (PMAY-G money default,
'Unresolved' note wording, Focus Legacy members and villages metrics, the "coverage" glossary synonym) and the two
KI-393 mappings above.
