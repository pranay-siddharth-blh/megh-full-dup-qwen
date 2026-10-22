# Cross-Scheme Issues — 22 Oct 2026

These issues come from the live re-test of the 60 cross-scheme UAT cases in `raw_uc/cross_scheme.xlsx`. Each question
was asked in a new chat and checked against the raw source files and against `megh_db`.

**Result: 20 / 60 pass against the raw files and 17 / 60 against the DB** (the testers recorded 21 / 60 on 15 Oct).
The full per-case report is in `new_docs/Cross_Scheme_Test_Report_2026-10-22.md`, and every question with the bot's full
answer is in `new_docs/Cross_Scheme_all_queries_2026-10-22.csv`.

| # | Issue | Severity | Cases | KI | Status (22 Oct, night) |
|---|---|---|---|---|---|
| 1 | Combined cross-scheme results are never worked out | High | 10 | KI-387 | Fixed |
| 2 | "Excluding / leaving out" is ignored or reversed | High | 5 | KI-388 | Fixed |
| 3 | MGNREGA (and other per-scheme parts) missing or incomplete | High | 13 | KI-389 | Fixed |
| 4 | Wrong measure or unit | High | 9 | KI-390 | Fixed |
| 5 | FOCUS state totals cut to mapped rows | High | 1 | KI-392 | Fixed |
| 6 | Block coverage questions | Medium | 3 | KI-391 | Fixed (village counts: see 7) |
| 7 | Raw files vs DB mapping differences (data) | Medium | 4 + DB column of 6 | KI-393 | Bot side fixed; data open (ingestion) |

Some cases have more than one issue, so the case counts add up to more than 40.

**Update, 22 Oct night:** issues 1–6 are fixed on the chatbot side (D-066). On a re-run of all 60 questions, every figure matches megh_db in 59/60 cases and the raw files in 47/60. The 12 remaining raw-file differences are issue 7 (data), and T13.3 lists the low districts by villages, not beneficiaries. Details: `new_docs/Cross_Scheme_Test_Report_2026-10-22.md` §6 and `new_docs/Cross_Scheme_all_queries_after_fix_2026-10-22.csv`.

---

## 1. Combined cross-scheme results are never worked out — High (KI-387)

When a question needs a figure built from several schemes, the bot lists each scheme separately and stops. It gives no
combined total, no combined district ranking, no per-district winner or second place, and no answer to a condition such
as "districts where X > Y".

| Case | Question | Expected | Bot today |
|---|---|---|---|
| T01.1 | What is the total beneficiary count across MGNREGA, PMAY-G, Focus+ and FOCUS? | Combined 18,73,378 | All four figures right; no total |
| T04.2 | What is the total money released under Focus Plus, FOCUS and PMAY Gramin combined? | ₹2,356.01 Cr | Three amounts; no total |
| T03.3 | In which districts does Focus+ have more beneficiaries than PMAY-G? | South West Garo Hills, West Garo Hills | PMAY-G list only; "Focus Plus has no records" |
| T07.1 | Which scheme has the highest beneficiary count in each district? | MGNREGA in all 12 | 49-row list; leader never named |
| T18.1 | For each district, which scheme has the highest beneficiary count? | MGNREGA in all 12 | Per-scheme lists; leader never named |
| T18.2 | Which of PMAY-G, Focus+ and FOCUS comes second after MGNREGA in each district? | PMAY-G 8, FOCUS 2, Focus+ 2 | Second place never named |
| T15.1 | Which districts have the highest concentration of beneficiaries across the 4 schemes? | WGH 3,51,294; EKH 2,73,064; SWGH 1,99,200 … | Per-scheme lists; no combined ranking |
| T15.2 | Top 3 districts by total beneficiaries across the 4 schemes? | WGH, EKH, SWGH | No combined top 3; adds "Focus Legacy 43,055 with no district" |
| T15.3 | Excluding MGNREGA, which districts have the most beneficiaries? | WGH 90,073; EKH 48,401; NGH 37,382 | No ranking (also issue 2) |
| T16.2 | Focus+ vs PMAY-G beneficiaries in East, North and South Garo Hills? | Per-district figures + totals | Only the 3-district totals (44,828 / 30,998, both correct) |

**Expected behaviour:** when the question asks for a total, ranking, winner or condition across schemes, compute it in
code from the per-scheme rows, so the composer does not do the arithmetic. The composer then states it. The raw figures
are already in the per-scheme results.

## 2. "Excluding / leaving out" is ignored or reversed — High (KI-388)

| Case | Question | What happened |
|---|---|---|
| T07.2 | Leaving out MGNREGA and CM-ELEVATE, which scheme has the most beneficiaries in each district? | Showed **only** MGNREGA and CM Elevate, the two excluded schemes |
| T11.2 | What is the scheme-wise spending in South Garo Hills, excluding CM-ELEVATE? | Routed to the CM Elevate documents; no figures |
| T13.2 | Excluding CM-ELEVATE, which scheme reaches the most villages? | Asked "CM Elevate (applications) or Legacy?", then answered from the documents |
| T12.2 | Leaving out CM-ELEVATE, which scheme has spent the most money? | Included CM Elevate Legacy (₹82.90 Cr); no winner stated |
| T15.3 | Excluding MGNREGA, which districts have the most beneficiaries…? | MGNREGA still included |

**Expected behaviour:** a scheme named after "excluding / leaving out / except / other than / without" is removed from
the scheme set. It must not trigger scheme detection, the CM Elevate dataset question or routing to the documents. When
CM-ELEVATE is excluded, CM Elevate Legacy is excluded too. The remaining schemes are then the default four (MGNREGA,
PMAY-G, Focus+, FOCUS) minus the excluded ones.

## 3. MGNREGA (and other per-scheme parts) missing or incomplete — High (KI-389)

**3a. "No MGNREGA figure could be worked out"** in district and overall answers:

| Case | Question | Expected MGNREGA |
|---|---|---|
| T13.1 | Which scheme has the widest coverage across districts? | 6,419 villages |
| T14.1 | Performance of MGNREGA, PMAY-G, Focus+ and FOCUS in North Garo Hills | 1,36,418 households, ₹404.65 Cr |
| T14.3 | … in Eastern West Khasi Hills | 50,391 households, ₹81.86 Cr |
| T20.1 | Overall comparison on coverage and money | 14,94,437 households, 6,419 villages, ₹3,628.67 Cr |
| T20.2 | Rank the 4 schemes on coverage, beneficiaries, money | Same as T20.1 |

T14.1 was fully correct in the first run and failed in the second, so the SQL for this part is not consistent between
runs.

**3b. MGNREGA given per year with no total:** T14.2 (West Khasi Hills, expected 62,655 / ₹131.54 Cr), T17.1 and T17.2
(district summaries). The year rows are also labelled "lakh crore".

**3c. Wrong grain or count left out** for the other schemes:

| Case | Problem |
|---|---|
| T07.3 (Ri Bhoi) | MGNREGA shown as 100 village rows and PMAY-G as single-house rows; no district totals (expected 1,12,602 / 17,565) and no winner |
| T08.1 (East Khasi Hills) | PMAY-G house count 23,952 left out |
| T08.3 (Ri Bhoi) | Money only; Focus+ 419 and PMAY-G 17,565 left out |
| T14.3 | PMAY-G houses 5,494 left out |

## 4. Wrong measure or unit — High (KI-390)

| Case | Problem | Correct |
|---|---|---|
| T12.1, T12.3, T19.1 | PMAY-G amount given as ₹2,222.75 Cr **sanctioned** | ₹2,185.26 Cr **released** (as in every other answer) |
| T20.3 | PMAY-G per beneficiary ₹1,28,059 (sanctioned basis); no FOCUS average; no winner | ₹1,27,713 released; FOCUS ₹5,000 |
| T19.2 | FOCUS average stated as ₹11,316.12 (Focus+'s figure copied) | ₹5,000 |
| T12.3 | No per-beneficiary figure for PMAY-G or FOCUS; Focus+ printed "₹11,316.119002391011" | ₹1,27,713 / ₹11,316 / ₹5,000 |
| T16.1 | FOCUS producer groups (2,701 / 955 / 909) called "beneficiaries" | Members 21,867 / 9,858 / 10,841 |
| T18.3 | "Which is bigger, Focus+ or FOCUS" answered with money, "Focus+ bigger everywhere" | By beneficiaries / members, FOCUS is bigger in 6 districts |
| T10.3 | "Focus Plus shows payments of ₹292,385 lakh crore" | 2,92,385 is a payment count, not money |
| T01.2 | MGNREGA headline in person-years (18,65,234) | Households 14,94,437 |
| T10.2 (passes, cosmetic) | "₹119.7392500000000000 crore" | ₹119.74 crore |

**Expected behaviour:** PMAY-G money is always `amount_released` unless the question says "sanctioned". FOCUS
"beneficiaries" are members (`no_of_pg_members`), with PGs alongside. Per the project's rule for wrong-number bugs, each
of these needs a deterministic guard in `compose_response`, not only a prompt rule.

## 5. FOCUS state totals cut to mapped rows — High (KI-392)

T20.1 ("overall performance comparison … coverage and financial performance") showed FOCUS as **94,116 members /
₹47.06 Cr / 10,998 PGs / 13,468 payments**. Those are only the village-mapped rows. The correct state totals are
**1,02,021 / ₹51.01 Cr / 11,906 / 14,569**. The village filter for the coverage column was applied to the money and
count columns too. The village count (3,384) should be filtered; the totals should not.

## 6. Block coverage questions — Medium (KI-391)

| Case | Question | Problem | Expected |
|---|---|---|---|
| T09.2 | What is the coverage of NREGA, PMAY-G and Focus+ in Dadenggiri block? | Answered from the scheme documents, no figures | MGNREGA 103, PMAY-G 97, Focus+ 80 villages |
| T09.3 | Compare coverage of MGNREGA, PMAY-G and FOCUS in Songsak block | FOCUS left out; no village counts | 155 / 135 / 118 villages |
| T09.1 | Compare coverage … in Mylliem block | Focus+ "49 villages" | Raw 27 distinct LGD codes (DB 35); MGNREGA 56 and PMAY-G 41 correct |

"Coverage of" in Dadenggiri is read as a knowledge question. In a data question, "coverage" should mean villages
covered.

## 7. Raw files vs DB mapping differences — Medium, data (KI-393)

48 of the 459 checked figures differ between the raw files and the DB:

| Scheme | Raw file | DB (LGD mapping) |
|---|---|---|
| Focus+ West Garo Hills | 35,059 beneficiaries, ₹39.16 Cr | 35,039, ₹39.13 Cr |
| Focus+ South West Garo Hills | 15,274, ₹16.64 Cr | 15,294, ₹16.68 Cr |
| Focus+ villages (state) | 3,220 distinct LGD codes | 3,513 |
| Focus+ blocks | 51 | 59 |
| MGNREGA households, West Garo Hills | 2,61,221 | 2,61,666 |
| MGNREGA households, South West Garo Hills | 1,65,421 | 1,64,976 |

PMAY-G and FOCUS match the raw files exactly.

**Bot side:** the bot groups Focus+ sometimes by `district_name_raw` (raw figure) and sometimes by `lgd_district` (DB
figure). The same question can therefore return either number (T02.3, T08.2, T16.1, T17.2 and T17.3 show the DB figure;
T03.x and T06.x show the raw figure). Pick one grouping column for Focus+ districts and use it everywhere.

**Data side:** the mapping differences belong to the ingestion team (`megh-ingestion`). Report them there; do not
change `megh_db.curated`.

---

## Cases that pass today (20 against the raw files)

T01.3, T02.1, T02.2, T03.1, T03.2, T04.1, T04.3, T05.1, T05.2, T05.3, T06.1, T06.2, T06.3, T10.1, T10.2, T11.1, T11.3,
T13.3, T16.3, T19.3.

Five of these pass against the raw files but not the DB (T03.1, T03.2, T06.1–T06.3), because of issue 7. T02.3 and
T08.2 are the reverse.

**Passed on 15 Oct, fail today:** T08.3, T09.3, T10.3, T12.1, T12.3, T13.2, T19.2, T20.3. On 15 Oct, six of these
"passed" only because the bot asked a question back. Today the bot answers them, wrongly.

## Reference figures (raw files, all years)

| Scheme | Beneficiaries | Money | Villages |
|---|---|---|---|
| MGNREGA | 14,94,437 households (FY 2022-23 to 2025-26 added) | ₹3,628.67 Cr expenditure | 6,419 |
| PMAY-G | 1,71,107 houses (1,29,941 completed) | ₹2,185.26 Cr released (₹2,222.75 Cr sanctioned) | 5,121 |
| Focus+ | 1,05,813 | ₹119.74 Cr | 3,220 |
| FOCUS | 1,02,021 members in 11,906 PGs | ₹51.01 Cr | 3,384 |
