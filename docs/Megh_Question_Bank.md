# Megh One AI: verified question bank

*Built 2026-11-15 18:02 from megh_db (read-only). 156 questions, 199 turns. Regenerate with `tools/make_question_bank.py`.*

Use this as a guide when you ask the app questions by voice or by typing. Every answer below was read straight from the database with its own query (listed at the end), not taken from the app.

## How good is the app today

- The full test bank of 401 checked questions (553 turns, every answer compared with an independent database query) passed 401 of 401 on 15 Nov 2026, with the AI model on.
- With the AI model switched off entirely, the app still answered 360 of 401 correctly (90%): most questions are answered by fixed, verified queries, and the model is needed mainly for unusual wordings.
- This guide was then run through the app again (model on): it gave the database figures for 155 of 156 questions here. The ones it missed are listed at the end.

## What you can ask

- Figures from eight schemes: MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate (applications), CM Elevate Legacy (disbursements), CMSS and Homestay.
- For the whole state, a district, a block, a village or an assembly constituency; for one financial year, a few, or all of them.
- Totals, breakdowns (by district, block, year, scheme, status, gender…), rankings (top or bottom N), trends, comparisons of places, years or schemes, shares and averages.
- Several schemes at once: the headline of every scheme, money by scheme, one place across every scheme.
- Follow-ups in the same chat: “now by block”, “only Ri Bhoi”, “top 3”, “which is the lowest”, “what about 2023-24”, “and the households instead”.
- How a scheme works (eligibility, rules) is answered from the scheme documents; this guide covers the figures.

## Which years each scheme covers

- **MGNREGA**: 2022-23 to 2025-26, by employment and expenditure.
- **PMAY-G**: 2017-18 to 2023-24, by year a house was sanctioned; 126 records have no year.
- **Focus Plus**: 2022-23 and 2025-26 (only these two years), by payment year.
- **Focus Legacy**: 2021-22 to 2025-26 (no 2023-24), by remittance year.
- **CM Elevate**: no financial year (applications carry no year; 8,938 applications).
- **CM Elevate Legacy**: 2024-25 and 2025-26, by disbursement year; 395 records have no year.
- **CMSS**: 2025-26, by payment year.
- **Homestay**: 2025-26 and 2026-27, by application year.

## Tips for asking

- Name the scheme, the place and the year: “MGNREGA person-days in Ri Bhoi in 2023-24”. Without a year the app adds up every year it holds and says so.
- Short names work: WGH, EKH, “nrega”, “PMAY gramin”, “Focus+”, “23-24”, “FY24”. Casual and spoken wording works too.
- Follow-ups keep what you asked before: after a district breakdown, “now by block”, “only Ri Bhoi”, “top 3”, “and in 2024-25?”, “what about the households instead”.
- For CM Elevate, say “applications” or “Legacy” (the payments). A new chat may ask which one you mean: tap it.
- MGNREGA households and persons are counted once per financial year, so a total over several years counts a household again in each year it worked. Ask for one year when you want a head count.
- PMAY-G “beneficiaries” are the houses sanctioned. Focus Legacy “beneficiaries” are producer-group members.
- Money is shown in ₹ crore or ₹ lakh; MGNREGA money is stored in lakh rupees.

## What is in this guide

| Section | Questions | From the test bank | New | App matched the DB |
|---|---:|---:|---:|---:|
| Every scheme at a glance (cross-scheme) | 15 | 12 | 3 | 14 of 15 |
| MGNREGA | 31 | 28 | 3 | 31 of 31 |
| PMAY-G | 21 | 20 | 1 | 21 of 21 |
| Focus Plus | 11 | 11 | 0 | 11 of 11 |
| Focus Legacy | 11 | 11 | 0 | 11 of 11 |
| CM Elevate (applications) | 10 | 10 | 0 | 10 of 10 |
| CM Elevate Legacy (disbursements) | 12 | 12 | 0 | 12 of 12 |
| CMSS and Homestay | 8 | 2 | 6 | 8 of 8 |
| Conversations: follow-up questions | 25 | 23 | 2 | 25 of 25 |
| Asking for a chart | 3 | 3 | 0 | 3 of 3 |
| What the app declines or asks back | 9 | 8 | 1 | 9 of 9 |
| **All** | **156** | **140** | **16** | **155 of 156** |

Marks under each answer: **test bank ✓** = the same words are in the 401-question test bank and passed there; **new** = added for this guide; **app ✓ / ✗** = what the app answered when this guide was checked (facts only; wording is not judged).

## Every scheme at a glance (cross-scheme)

*Questions that look across the schemes at once: headline figures, money, the same place in every scheme.*

**A1. Give me the headline figure of every scheme**  
MGNREGA 14,94,437 households given work (each financial year counted on its own, 2022-23 to 2025-26); PMAY-G 1,71,107 houses sanctioned; Focus Plus 1,05,813 beneficiaries; Focus Legacy 1,02,021 producer-group members; CMSS 98,751 students paid; Homestay 1,297 applications; CM Elevate 8,938 applications (7,375 of them valid); CM Elevate Legacy 2,820 applicants sanctioned.  
<sub>test bank ✓ · app ✓</sub>

**A2. Compare all eight schemes**  
MGNREGA 14,94,437 households given work (each financial year counted on its own, 2022-23 to 2025-26); PMAY-G 1,71,107 houses sanctioned; Focus Plus 1,05,813 beneficiaries; Focus Legacy 1,02,021 producer-group members; CMSS 98,751 students paid; Homestay 1,297 applications; CM Elevate 8,938 applications (7,375 of them valid); CM Elevate Legacy 2,820 applicants sanctioned. Money: MGNREGA ₹3,628.67 crore spent, PMAY-G ₹2,185.26 crore released, Focus Plus ₹119.74 crore, CM Elevate Legacy ₹82.90 crore, CMSS ₹59.25 crore, Focus Legacy ₹51.01 crore.  
<sub>test bank ✓ · app ✓</sub>

**A3. How much money has each scheme disbursed?**  
MGNREGA ₹3,628.67 crore spent; PMAY-G ₹2,185.26 crore released; Focus Plus ₹119.74 crore; CM Elevate Legacy ₹82.90 crore (subsidy and loan); CMSS ₹59.25 crore; Focus Legacy ₹51.01 crore. CM Elevate and Homestay record applications only, no money.  
<sub>test bank ✓ · app ✓</sub>

**A4. Which scheme has disbursed the most money?**  
MGNREGA, by far: ₹3,628.67 crore spent over 2022-23 to 2025-26. Next is PMAY-G with ₹2,185.26 crore released.  
<sub>test bank ✓ · app ✓</sub>

**A5. Total beneficiaries of each scheme excluding MGNREGA**  
PMAY-G 1,71,107 houses; Focus Plus 1,05,813 beneficiaries; Focus Legacy 1,02,021 members; CMSS 98,751 students paid; Homestay 1,297 applications.  
<sub>test bank ✓ · app ✓</sub>

**A6. In Ri Bhoi, give me each scheme's figures**  
MGNREGA 1,12,602 households given work (all years added); PMAY-G 17,565 houses; Focus Plus 419 beneficiaries; CMSS 8,701 students paid; Homestay 103 applications; Focus Legacy 9,858 members; CM Elevate 2,038 valid applications; CM Elevate Legacy ₹6.95 crore disbursed.  
<sub>test bank ✓ · app ✓</sub>

**A7. In East Khasi Hills, give me each scheme's figures**  
MGNREGA 2,24,663 households given work (all years added); PMAY-G 23,952 houses; Focus Plus 13,608 beneficiaries; CMSS 24,932 students paid; Homestay 341 applications; Focus Legacy 10,841 members; CM Elevate 998 valid applications; CM Elevate Legacy ₹22.60 crore disbursed.  
<sub>new · app ✓</sub>

**A8. Each year, for all schemes, what was disbursed?**  
MGNREGA spent 2022-23 ₹886.29 crore, 2023-24 ₹759.61 crore, 2024-25 ₹1,066.70 crore and 2025-26 ₹916.06 crore. PMAY-G released 2017-18 ₹201.46 crore, 2018-19 ₹45.89 crore, 2019-20 ₹129.03 crore, 2020-21 ₹309.18 crore, 2021-22 ₹37.87 crore, 2022-23 ₹105.37 crore and 2023-24 ₹1,356.45 crore. Focus Plus 2022-23 ₹46.64 crore and 2025-26 ₹73.10 crore. Focus Legacy 2021-22 ₹6.82 crore, 2022-23 ₹14.18 crore, 2024-25 ₹11.50 crore and 2025-26 ₹18.51 crore. CM Elevate Legacy 2024-25 ₹59.82 crore and 2025-26 ₹22.49 crore (plus some payments with no year). CMSS 2025-26 ₹59.25 crore.  
<sub>test bank ✓ · app ✓ · The test bank checks four sample years (MGNREGA and PMAY-G 2023-24, Focus Legacy 2024-25, CMSS 2025-26); the full table is shown here.</sub>

**A9. Which district gets the most money across all the schemes that have money?**  
West Garo Hills. Adding up every scheme that records money, West Garo Hills leads with ₹1,289.39 crore; next East Khasi Hills ₹780.65 crore and South West Garo Hills ₹645.72 crore. It also leads MGNREGA (₹792.42 crore) and PMAY-G (₹425.01 crore) on their own.  
<sub>test bank ✓ · app ✓</sub>

**A10. Which district leads in each scheme?**  
MGNREGA: West Garo Hills (2,61,666 households). PMAY-G: West Garo Hills (33,147 houses). Focus Plus: West Garo Hills (35,039 beneficiaries). Focus Legacy: West Garo Hills (21,867 members). CM Elevate: Ri Bhoi (2,038 valid applications). CM Elevate Legacy: West Garo Hills (493 applicants). CMSS: East Khasi Hills (24,932 students paid). Homestay: East Khasi Hills (341 applications).  
<sub>new · app ✗</sub>

**A11. Compare MGNREGA households employed and PMAY-G houses in Ri Bhoi**  
Ri Bhoi: 1,12,602 MGNREGA households given work (all years added) and 17,565 PMAY-G houses.  
<sub>test bank ✓ · app ✓</sub>

**A12. In Dalu block, how many MGNREGA households and PMAY-G houses are there?**  
Dalu block: 39,927 MGNREGA households given work (all years added) and 3,724 PMAY-G houses.  
<sub>test bank ✓ · app ✓</sub>

**A13. Compare Focus Plus and Focus Legacy amounts in FY 2022-23**  
In 2022-23 Focus Plus disbursed ₹46.64 crore and Focus Legacy ₹14.18 crore.  
<sub>test bank ✓ · app ✓</sub>

**A14. Compare the number of beneficiaries and the total amount for Focus Plus, Focus Legacy and CM Elevate Legacy.**  
Focus Plus: 1,05,813 beneficiaries, ₹119.74 crore. Focus Legacy: 1,02,021 members in 11,906 producer groups, ₹51.01 crore. CM Elevate Legacy: 2,820 applicants, ₹82.90 crore.  
<sub>test bank ✓ · app ✓</sub>

**A15. Compare Focus Plus beneficiaries and CMSS students paid in East Khasi Hills**  
East Khasi Hills: 13,608 Focus Plus beneficiaries and 24,932 CMSS students paid.  
<sub>new · app ✓</sub>

## MGNREGA

*Employment (households, persons, person-days, women, 100 days, job cards) and expenditure, by financial year. Money is stored in lakh rupees.*

**M1. Total MGNREGA person-days statewide in FY 2023-24?**  
2,72,64,054 person-days of employment in 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**M2. Total MGNREGA expenditure across all financial years in Meghalaya?**  
₹3,628.67 crore spent from 2022-23 to 2025-26.  
<sub>test bank ✓ · app ✓</sub>

**M3. How many villages had MGNREGA activity in Meghalaya?**  
6,491 villages appear in MGNREGA's employment or expenditure records.  
<sub>test bank ✓ · app ✓</sub>

**M4. How many households completed 100 days of MGNREGA work in 2025-26?**  
33,397 households completed 100 days in 2025-26.  
<sub>new · app ✓</sub>

**M5. What was the total expenditure in West Garo Hills during 2023-24?**  
MGNREGA spent ₹148.81 crore in West Garo Hills in 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**M6. how many person days did nrega give in west garo hills in 23-24**  
54,89,616 person-days in West Garo Hills in 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**M7. Uh, MGNREGA, total expenditure, East Garo Hills, twenty twenty four twenty five?**  
₹95.18 crore spent in East Garo Hills in 2024-25.  
<sub>test bank ✓ · app ✓</sub>

**M8. What was the total expenditure in Gambegre block during 2022-23?**  
₹14.55 crore spent in Gambegre block in 2022-23.  
<sub>test bank ✓ · app ✓</sub>

**M9. How many households received employment in Nongstoin block during 2025-26?**  
8,323 households in Nongstoin block in 2025-26.  
<sub>test bank ✓ · app ✓</sub>

**M10. How many person-days did Jakrem village get under MGNREGA in 2024-25?**  
57,391 person-days in Jakrem in 2024-25.  
<sub>test bank ✓ · app ✓</sub>

**M11. How many person-days were generated in Mawsynram constituency in 2024-25?**  
1,91,665 person-days in Mawsynram constituency in 2024-25.  
<sub>test bank ✓ · app ✓</sub>

**M12. MGNREGA expenditure by district in 2022-23**  
West Garo Hills leads with ₹150.54 crore; next East Khasi Hills ₹118.69 crore and South West Garo Hills ₹111.58 crore. All twelve: West Garo Hills ₹150.54 crore, East Khasi Hills ₹118.69 crore, South West Garo Hills ₹111.58 crore, North Garo Hills ₹102.61 crore, East Garo Hills ₹82.47 crore, South Garo Hills ₹76.16 crore, South West Khasi Hills ₹60.03 crore, Ri Bhoi ₹45.75 crore, West Jaintia Hills ₹41.71 crore, West Khasi Hills ₹38.66 crore, East Jaintia Hills ₹37.52 crore and Eastern West Khasi Hills ₹20.56 crore.  
<sub>test bank ✓ · app ✓</sub>

**M13. Show MGNREGA person-days by district**  
All years added: West Garo Hills leads with 1,75,39,710; next East Khasi Hills 1,10,54,100 and North Garo Hills 1,07,24,749. All twelve: West Garo Hills 1,75,39,710, East Khasi Hills 1,10,54,100, North Garo Hills 1,07,24,749, South West Garo Hills 1,05,16,665, East Garo Hills 89,48,770, South Garo Hills 88,20,484, South West Khasi Hills 53,17,562, Ri Bhoi 47,61,757, West Jaintia Hills 44,67,950, East Jaintia Hills 35,73,771, West Khasi Hills 30,49,071 and Eastern West Khasi Hills 21,40,592.  
<sub>test bank ✓ · app ✓</sub>

**M14. Which district had the most households completing 100 days in FY 2022-23?**  
East Garo Hills leads with 22,049; next South Garo Hills 9,969 and South West Khasi Hills 7,778.  
<sub>test bank ✓ · app ✓</sub>

**M15. Top 5 districts by MGNREGA person-days in FY 2023-24**  
West Garo Hills 54,89,616, South West Garo Hills 32,82,990, North Garo Hills 30,66,633, East Khasi Hills 30,61,525 and South Garo Hills 28,23,825.  
<sub>test bank ✓ · app ✓</sub>

**M16. Which district had the lowest MGNREGA person-days in 2023-24?**  
Eastern West Khasi Hills, with 6,77,731; then East Jaintia Hills 8,93,276 and West Khasi Hills 8,95,621.  
<sub>test bank ✓ · app ✓</sub>

**M17. Top 3 blocks by MGNREGA expenditure in 2024-25**  
Demdema ₹71.68 crore, Zikzak ₹57.05 crore and Resubelpara ₹47.06 crore.  
<sub>test bank ✓ · app ✓</sub>

**M18. Which block generated the highest person-days during 2023-24?**  
Zikzak leads with 14,40,124; next Tikrikilla 14,23,794 and Resubelpara 12,67,349.  
<sub>test bank ✓ · app ✓</sub>

**M19. Which district had the highest women employment during 2023-24?**  
East Khasi Hills, with 47,345 women given work; next West Garo Hills 44,117 and South West Garo Hills 31,046.  
<sub>test bank ✓ · app ✓</sub>

**M20. MGNREGA households provided employment in each financial year**  
2022-23 4,14,251, 2023-24 4,10,200, 2024-25 3,04,430 and 2025-26 3,65,556.  
<sub>test bank ✓ · app ✓</sub>

**M21. MGNREGA expenditure in Ri Bhoi from 2022-23 to 2024-25, year by year**  
2022-23 ₹45.75 crore, 2023-24 ₹42.96 crore and 2024-25 ₹50.34 crore.  
<sub>test bank ✓ · app ✓</sub>

**M22. In which financial year was MGNREGA expenditure the highest?**  
2024-25, with ₹1,066.70 crore. The other years: 2025-26 ₹916.06 crore, 2022-23 ₹886.29 crore and 2023-24 ₹759.61 crore.  
<sub>test bank ✓ · app ✓</sub>

**M23. Compare MGNREGA expenditure in FY 2022-23 vs FY 2023-24 statewide**  
2022-23: ₹886.29 crore. 2023-24: ₹759.61 crore. Spending fell in 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**M24. Compare MGNREGA person-days in East Khasi Hills and West Garo Hills in 2023-24**  
West Garo Hills 54,89,616 against East Khasi Hills 30,61,525 person-days in 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**M25. Compare MGNREGA expenditure in Ri Bhoi, West Garo Hills and East Khasi Hills in 2024-25**  
2024-25: West Garo Hills ₹257.01 crore, East Khasi Hills ₹110.50 crore, Ri Bhoi ₹50.34 crore.  
<sub>new · app ✓</sub>

**M26. Share of women employed in Ri Bhoi FY 2023-24?**  
55.76%: 29,942 women out of 53,700 persons employed in Ri Bhoi in 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**M27. What is the cost per person-day under MGNREGA in West Jaintia Hills in 2023-24?**  
₹255.16 per person-day in West Jaintia Hills in 2023-24 (expenditure divided by person-days).  
<sub>test bank ✓ · app ✓</sub>

**M28. What share of MGNREGA expenditure went to unskilled wages in 2024-25 statewide?**  
66.13% of the money spent in 2024-25 went to unskilled wages.  
<sub>test bank ✓ · app ✓</sub>

**M29. Compare total expenditure and employment generated in East Khasi Hills during 2025-26.**  
East Khasi Hills, 2025-26: ₹95.77 crore spent and 29,51,690 person-days of employment.  
<sub>test bank ✓ · app ✓</sub>

**M30. Give me the expenditure breakdown for Myriem during 2023-24.**  
Myriem, 2023-24: unskilled wages ₹17.52 lakh, semi-skilled wages ₹4.58 lakh, materials ₹8.77 lakh; total ₹30.87 lakh.  
<sub>test bank ✓ · app ✓</sub>

**M31. What was MGNREGA material expenditure statewide in 2024-25?**  
₹320.46 crore was spent on materials in 2024-25.  
<sub>new · app ✓</sub>

## PMAY-G

*Rural houses: sanctioned, completed, under construction, and the money sanctioned, released and still to be released.*

**P1. How many PMAY-G houses in total, and how many completed?**  
1,71,107 houses sanctioned; 1,29,941 completed, 41,041 still under construction and 125 not started or with no status.  
<sub>test bank ✓ · app ✓</sub>

**P2. How many PMAY-G houses have been sanctioned and completed in Meghalaya, and what is the completion rate?**  
1,71,107 sanctioned, 1,29,941 completed: a completion rate of 75.94%.  
<sub>test bank ✓ · app ✓</sub>

**P3. Total PMAY-G amount released in Meghalaya across all years?**  
₹2,185.26 crore released.  
<sub>test bank ✓ · app ✓</sub>

**P4. Total PMAY-G amount still pending statewide?**  
₹37.49 crore is still to be released, out of ₹2,222.75 crore sanctioned.  
<sub>test bank ✓ · app ✓</sub>

**P5. How many PMAY houses have been completed in West Garo Hills?**  
26,822 houses completed in West Garo Hills.  
<sub>test bank ✓ · app ✓</sub>

**P6. How much PMAY-G money has been released in East Jaintia Hills?**  
₹73.66 crore released in East Jaintia Hills.  
<sub>test bank ✓ · app ✓</sub>

**P7. How many houses are still incomplete in Ri Bhoi?**  
5,509 houses in Ri Bhoi are not completed (5,469 of them under construction).  
<sub>test bank ✓ · app ✓</sub>

**P8. Give me the PMAY financial summary for East Garo Hills.**  
East Garo Hills: ₹219.69 crore sanctioned, ₹216.44 crore released, ₹3.24 crore still to be released.  
<sub>test bank ✓ · app ✓</sub>

**P9. Give me the PMAY financial summary for Amlarem block.**  
Amlarem block: ₹30.89 crore sanctioned, ₹30.00 crore released, ₹89.16 lakh still to be released.  
<sub>test bank ✓ · app ✓</sub>

**P10. How many PMAY beneficiaries are there in GABIL SONGGITCHAM?**  
345 beneficiaries (houses sanctioned) in Gabil Songgitcham.  
<sub>test bank ✓ · app ✓</sub>

**P11. Give me the house status breakdown for GABIL SONGGITCHAM.**  
Completed 179, Roof Cast 91, Plinth 73 and House Sanctioned 2.  
<sub>test bank ✓ · app ✓</sub>

**P12. PMAY-G houses completed by district**  
West Garo Hills leads with 26,822; next East Khasi Hills 18,154 and East Garo Hills 13,784. All twelve: West Garo Hills 26,822, East Khasi Hills 18,154, East Garo Hills 13,784, North Garo Hills 13,183, Ri Bhoi 12,056, South West Garo Hills 10,212, West Jaintia Hills 8,932, West Khasi Hills 7,294, South West Khasi Hills 7,100, South Garo Hills 6,316, Eastern West Khasi Hills 4,465 and East Jaintia Hills 1,623.  
<sub>test bank ✓ · app ✓</sub>

**P13. PMAY-G houses sanctioned in each financial year**  
2017-18 15,513, 2018-19 3,535, 2019-20 9,952, 2020-21 24,215, 2021-22 3,014, 2022-23 8,225 and 2023-24 1,06,527 (126 houses carry no year).  
<sub>test bank ✓ · app ✓</sub>

**P14. Top 5 districts by PMAY-G houses completed**  
West Garo Hills 26,822, East Khasi Hills 18,154, East Garo Hills 13,784, North Garo Hills 13,183 and Ri Bhoi 12,056.  
<sub>test bank ✓ · app ✓</sub>

**P15. Top 3 blocks by PMAY-G houses completed**  
Demdema 5,274, Dambo Rongjeng 5,141 and Songsak 4,850.  
<sub>test bank ✓ · app ✓</sub>

**P16. How many PMAY-G houses in total, and which district has the most?**  
1,71,107 houses; West Garo Hills leads with 33,147; next East Khasi Hills 23,952 and Ri Bhoi 17,565.  
<sub>test bank ✓ · app ✓</sub>

**P17. Compare PMAY-G houses completed in Ri Bhoi and West Jaintia Hills**  
Ri Bhoi 12,056 completed, West Jaintia Hills 8,932.  
<sub>test bank ✓ · app ✓</sub>

**P18. What percentage of PMAY houses are completed in South Garo Hills?**  
53.07% of the houses in South Garo Hills are completed.  
<sub>test bank ✓ · app ✓</sub>

**P19. What percentage of the sanctioned amount has been released in North Garo Hills?**  
98.63% of the sanctioned amount has been released in North Garo Hills.  
<sub>test bank ✓ · app ✓</sub>

**P20. What share of all PMAY-G houses are in West Garo Hills?**  
19.37%: 33,147 of the state's 1,71,107 houses.  
<sub>test bank ✓ · app ✓</sub>

**P21. Which block in West Garo Hills has the most PMAY-G houses completed?**  
Demdema leads with 5,274; next Tikrikilla 4,514 and Selsella 4,457.  
<sub>new · app ✓</sub>

## Focus Plus

*Beneficiaries and the amount disbursed, in tranches.*

**F1. Total amount disbursed under Focus Plus across all years?**  
₹119.74 crore disbursed in 3,85,671 payments.  
<sub>test bank ✓ · app ✓</sub>

**F2. Focus Plus beneficiaries FY 2022-23 and amount paid?**  
93,286 beneficiaries were paid ₹46.64 crore in 2022-23.  
<sub>test bank ✓ · app ✓</sub>

**F3. Focus Plus amount disbursed by financial year**  
2022-23 ₹46.64 crore and 2025-26 ₹73.10 crore. The data holds only these two years.  
<sub>test bank ✓ · app ✓</sub>

**F4. How many Focus+ beneficiaries are there in each district?**  
West Garo Hills leads with 35,039; next South West Garo Hills 15,294 and East Khasi Hills 13,608. All twelve: West Garo Hills 35,039, South West Garo Hills 15,294, East Khasi Hills 13,608, East Garo Hills 11,379, North Garo Hills 11,007, South Garo Hills 8,612, West Khasi Hills 6,754, South West Khasi Hills 1,792, Eastern West Khasi Hills 1,221, Ri Bhoi 419, East Jaintia Hills 404 and West Jaintia Hills 283.  
<sub>test bank ✓ · app ✓ · Focus Plus district figures follow the source file's district names; for West Garo Hills and South West Garo Hills these differ from the LGD map by about 20 beneficiaries (KI-065), so either reading is accepted.</sub>

**F5. Which district received the highest total Focus Plus disbursement?**  
West Garo Hills leads with ₹39.13 crore; next South West Garo Hills ₹16.68 crore and East Khasi Hills ₹15.62 crore.  
<sub>test bank ✓ · app ✓</sub>

**F6. Which district has the fewest Focus Plus beneficiaries?**  
West Jaintia Hills, with 283; then East Jaintia Hills 404 and Ri Bhoi 419.  
<sub>test bank ✓ · app ✓</sub>

**F7. Give me the gender-wise breakdown of Focus+ beneficiaries.**  
Female 10,263 and Male 2,264. Gender is filled in only for these; the other 93,286 beneficiaries have none recorded.  
<sub>test bank ✓ · app ✓</sub>

**F8. What is the average Focus Plus amount disbursed per beneficiary?**  
About ₹11,316.12 per beneficiary.  
<sub>test bank ✓ · app ✓</sub>

**F9. Compare the number of Focus Plus beneficiaries in East Khasi Hills and North Garo Hills.**  
East Khasi Hills 13,608, North Garo Hills 11,007.  
<sub>test bank ✓ · app ✓</sub>

**F10. How many Focus Plus beneficiaries are there in Selsella block?**  
7,691 beneficiaries in Selsella block.  
<sub>test bank ✓ · app ✓</sub>

**F11. How much was disbursed under Focus Plus Tranch 1?**  
₹46.64 crore under Tranche 1. By tranche: Tranch 1 ₹46.64 crore, Tranch 4 - Feb-March ₹26.45 crore, Tranch 2 - August ₹23.32 crore and Tranch 3 - December ₹23.32 crore.  
<sub>test bank ✓ · app ✓</sub>

## Focus Legacy

*Producer groups, their members and the amount remitted to them.*

**L1. Focus Legacy producer groups and total, all years?**  
11,906 producer groups were paid ₹51.01 crore in all (2021-22 ₹6.82 crore, 2022-23 ₹14.18 crore, 2024-25 ₹11.50 crore and 2025-26 ₹18.51 crore).  
<sub>test bank ✓ · app ✓</sub>

**L2. What was the total Focus Legacy amount remitted in FY 2024-25?**  
₹11.50 crore remitted in 2024-25.  
<sub>test bank ✓ · app ✓</sub>

**L3. Focus Legacy amount remitted by financial year**  
2021-22 ₹6.82 crore, 2022-23 ₹14.18 crore, 2024-25 ₹11.50 crore and 2025-26 ₹18.51 crore. There are no Focus Legacy payments for 2023-24.  
<sub>test bank ✓ · app ✓</sub>

**L4. How many Focus Legacy producer groups are mapped to each district?**  
West Garo Hills leads with 2,701; next North Garo Hills 1,173 and West Jaintia Hills 1,130. All twelve: West Garo Hills 2,701, North Garo Hills 1,173, West Jaintia Hills 1,130, Ri Bhoi 955, East Garo Hills 928, West Khasi Hills 926, East Khasi Hills 909, South West Garo Hills 794, Eastern West Khasi Hills 792, East Jaintia Hills 626, South Garo Hills 532 and South West Khasi Hills 440.  
<sub>test bank ✓ · app ✓</sub>

**L5. Which district received the highest Focus Legacy amount?**  
West Garo Hills leads with ₹10.93 crore; next East Khasi Hills ₹5.42 crore and North Garo Hills ₹5.17 crore.  
<sub>test bank ✓ · app ✓</sub>

**L6. Top 3 districts by number of Focus Legacy producer groups**  
West Garo Hills 2,701, North Garo Hills 1,173 and West Jaintia Hills 1,130.  
<sub>test bank ✓ · app ✓</sub>

**L7. Compare the total Focus Legacy remittance between FY 2022-23 and FY 2024-25**  
2022-23: ₹14.18 crore. 2024-25: ₹11.50 crore.  
<sub>test bank ✓ · app ✓</sub>

**L8. Compare the Focus Legacy amounts in Ri Bhoi, West Garo Hills and East Khasi Hills**  
West Garo Hills ₹10.93 crore, East Khasi Hills ₹5.42 crore, Ri Bhoi ₹4.93 crore.  
<sub>test bank ✓ · app ✓</sub>

**L9. What is the average Focus Legacy amount per producer group in East Jaintia Hills?**  
About ₹36,238.02 per producer group.  
<sub>test bank ✓ · app ✓</sub>

**L10. How many Focus Legacy producer groups are mapped to Mawsynram constituency?**  
137 producer groups.  
<sub>test bank ✓ · app ✓</sub>

**L11. How many Focus Legacy producer groups are there in Mawkyrwat block?**  
315 producer groups in Mawkyrwat block.  
<sub>test bank ✓ · app ✓</sub>

## CM Elevate (applications)

*Applications to the CM Elevate schemes. By default the app counts VALID applications and says so; ask for 'all applications' to count every one.*

**E1. How many CM Elevate applications are there in total?**  
7,375 valid applications; 8,938 counting every application (Valid 7,375, On Hold 907, Invalid 490, Wrong 87 and not recorded 79).  
<sub>test bank ✓ · app ✓</sub>

**E2. How many CM ELEVATE applicants are there in each district?**  
Valid applications: Ri Bhoi leads with 2,038; next West Garo Hills 1,625 and East Khasi Hills 998. All twelve: Ri Bhoi 2,038, West Garo Hills 1,625, East Khasi Hills 998, West Khasi Hills 439, East Garo Hills 384, South Garo Hills 368, South West Khasi Hills 350, Eastern West Khasi Hills 289, South West Garo Hills 268, North Garo Hills 261, West Jaintia Hills 231 and East Jaintia Hills 124. (Every application: Ri Bhoi 2,626, West Garo Hills 1,743 and East Khasi Hills 1,131 …)  
<sub>test bank ✓ · app ✓</sub>

**E3. How many applicants are there under each CM ELEVATE program?**  
Valid applications, top five: PRIME Small Enterprise Empowerment and Development (SEED) 3,148, Meghalaya Piggery Development Scheme 2,453, Meghalaya Poultry Farming Scheme 471, PRIME Tourism Vehicle Scheme 363 and PRIME Agriculture Response Vehicle Scheme 354.  
<sub>test bank ✓ · app ✓</sub>

**E4. Which CM Elevate scheme has the most applications?**  
PRIME Small Enterprise Empowerment and Development (SEED): 3,148 valid applications (3,709 in all). Next Meghalaya Piggery Development Scheme with 2,453.  
<sub>test bank ✓ · app ✓</sub>

**E5. How many CM Elevate applications are there in East Khasi Hills?**  
998 valid applications (1,131 in all).  
<sub>test bank ✓ · app ✓</sub>

**E6. How many CM Elevate applications came from Jirang block?**  
539 valid applications from Jirang block (759 in all).  
<sub>test bank ✓ · app ✓</sub>

**E7. How many applicants are there under the Piggery scheme in Ri Bhoi?**  
1,474 valid applications to the Piggery Development Scheme in Ri Bhoi (1,939 in all).  
<sub>test bank ✓ · app ✓</sub>

**E8. How many CM ELEVATE applications are pending?**  
7,348 valid applications are pending (waiting, or sent back to the applicant).  
<sub>test bank ✓ · app ✓</sub>

**E9. How many CM Elevate applications have been rejected?**  
48 valid applications were rejected (62 counting every application).  
<sub>test bank ✓ · app ✓</sub>

**E10. CM Elevate applications by status as a donut chart**  
Valid applications by status: Pending 7,291, Send Back 57 and Rejected 48.  
<sub>test bank ✓ · app ✓</sub>

## CM Elevate Legacy (disbursements)

*Sanctioned applicants and the subsidy and loan paid out.*

**C1. What is the total amount disbursed under CM Elevate Legacy?**  
₹82.90 crore disbursed (subsidy and loan together).  
<sub>test bank ✓ · app ✓</sub>

**C2. How much has been disbursed under CM Elevate Legacy, split into subsidy and loan?**  
₹82.90 crore in all: ₹52.57 crore subsidy and ₹30.33 crore loan.  
<sub>test bank ✓ · app ✓</sub>

**C3. How many records does CM Elevate Legacy have?**  
2,823 records; 2,820 of them have a sanctioned amount (3 were de-sanctioned and paid nothing).  
<sub>test bank ✓ · app ✓</sub>

**C4. What is the total amount disbursed under each CM Elevate Legacy scheme?**  
Top five: Meghalaya Agriculture Warehouse Scheme ₹22.62 crore, Prime Tourism Vehicle Scheme ₹14.31 crore, Prime Agriculture Response Vehicle Scheme ₹14.21 crore, Meghalaya Piggery Development Scheme ₹9.52 crore and Meghalaya Sports & Wellness Scheme ₹5.87 crore.  
<sub>test bank ✓ · app ✓</sub>

**C5. Which 3 CM Elevate Legacy schemes got the most subsidy?**  
Meghalaya Agriculture Warehouse Scheme ₹17.58 crore, Meghalaya Piggery Development Scheme ₹8.47 crore and Prime Tourism Vehicle Scheme ₹6.77 crore.  
<sub>test bank ✓ · app ✓</sub>

**C6. What is the total CM Elevate Legacy disbursement amount for each district?**  
East Khasi Hills leads with ₹22.60 crore; next West Garo Hills ₹14.72 crore and Ri Bhoi ₹6.95 crore; then South West Garo Hills ₹6.12 crore and West Khasi Hills ₹5.74 crore.  
<sub>test bank ✓ · app ✓</sub>

**C7. How many CM Elevate Legacy applications are associated with each loan entity?**  
Bank 1,733 and LIFCOM 689 (401 have no loan entity recorded).  
<sub>test bank ✓ · app ✓</sub>

**C8. What was the total CM Elevate Legacy disbursement in each financial year?**  
2024-25 ₹59.82 crore and 2025-26 ₹22.49 crore; another ₹59.00 lakh was paid on records with no year.  
<sub>test bank ✓ · app ✓</sub>

**C9. How much CM Elevate Legacy subsidy was disbursed in Ri Bhoi?**  
₹4.55 crore of subsidy in Ri Bhoi.  
<sub>test bank ✓ · app ✓</sub>

**C10. How much CM Elevate Legacy loan was disbursed through LIFCOM?**  
₹11.75 crore of loan through LIFCOM.  
<sub>test bank ✓ · app ✓</sub>

**C11. Compare the number of sanctioned CM Elevate Legacy applications across West Garo Hills and East Khasi Hills.**  
West Garo Hills 493, East Khasi Hills 240 sanctioned applicants.  
<sub>test bank ✓ · app ✓ · East Khasi Hills also has 1 de-sanctioned record, which is not counted.</sub>

**C12. CM Elevate Legacy total disbursement in Ri Bhoi in 2025-26**  
₹2.02 crore in Ri Bhoi in 2025-26.  
<sub>test bank ✓ · app ✓</sub>

## CMSS and Homestay

*The two newest schemes: CMSS students paid, and Homestay applications.*

**S1. How many students were paid under CMSS?**  
98,751 students were paid, ₹59.25 crore in all (2025-26).  
<sub>test bank ✓ · app ✓</sub>

**S2. How much has been disbursed under CMSS?**  
₹59.25 crore disbursed (2025-26).  
<sub>new · app ✓</sub>

**S3. How many CMSS applications are there, and how many have been paid?**  
1,04,827 applications, of which 98,751 have been paid.  
<sub>new · app ✓</sub>

**S4. Which district has the most CMSS students paid?**  
East Khasi Hills leads with 24,932; next West Jaintia Hills 12,288 and West Garo Hills 11,966.  
<sub>new · app ✓</sub>

**S5. How many Homestay applications are there?**  
1,297 applications (2025-26 and 2026-27).  
<sub>test bank ✓ · app ✓</sub>

**S6. How many Homestay applications have been approved?**  
80 approved. All applications by status: Pending 1,082, Unknown 133, Approved 80 and Rejected 2.  
<sub>new · app ✓</sub>

**S7. Which district has the most Homestay applications?**  
East Khasi Hills leads with 341; next West Garo Hills 209 and West Khasi Hills 125.  
<sub>new · app ✓</sub>

**S8. How many Homestay applications came in each financial year?**  
2025-26 505 and 2026-27 792.  
<sub>new · app ✓</sub>

## Conversations: follow-up questions

*Two to four turns in one chat. Each later turn only makes sense after the one before it.*

**V1. A conversation**  
1. **“MGNREGA person-days in East Khasi Hills in 2023-24.”** → 30,61,525 person-days.  
2. **“And for Ri Bhoi?”** → 14,81,572 in Ri Bhoi (2023-24).  
3. **“What about the year before?”** → 12,12,513 in Ri Bhoi in 2022-23.  
<sub>test bank ✓ · app ✓</sub>

**V2. A conversation**  
1. **“Tell me about PMAY-G houses by district.”** → West Garo Hills leads with 33,147; next East Khasi Hills 23,952 and Ri Bhoi 17,565 … (all twelve districts).  
2. **“Only the completed ones.”** → Completed: West Garo Hills leads with 26,822; next East Khasi Hills 18,154 and East Garo Hills 13,784 …  
3. **“Top 3 districts.”** → West Garo Hills 26,822, East Khasi Hills 18,154 and East Garo Hills 13,784.  
<sub>test bank ✓ · app ✓</sub>

**V3. A conversation**  
1. **“Total MGNREGA expenditure statewide by financial year”** → 2022-23 ₹886.29 crore, 2023-24 ₹759.61 crore, 2024-25 ₹1,066.70 crore and 2025-26 ₹916.06 crore.  
2. **“break that down by district for 2023-24”** → 2023-24: West Garo Hills leads with ₹148.81 crore; next South West Garo Hills ₹105.97 crore and East Khasi Hills ₹89.96 crore …  
3. **“only West Garo Hills”** → West Garo Hills, 2023-24: ₹148.81 crore.  
<sub>test bank ✓ · app ✓</sub>

**V4. A conversation**  
1. **“How many households got MGNREGA work in West Garo Hills in 2023-24?”** → 72,541 households.  
2. **“and persons?”** → 89,192 persons.  
3. **“and how many of them were women?”** → 44,117 women.  
<sub>test bank ✓ · app ✓</sub>

**V5. A conversation**  
1. **“PMAY-G houses completed in Ri Bhoi”** → 12,056 houses completed.  
2. **“and the sanctioned amount there?”** → ₹227.82 crore sanctioned.  
3. **“what percentage of it has been released?”** → 97.82% has been released.  
<sub>test bank ✓ · app ✓</sub>

**V6. A conversation**  
1. **“Focus Legacy amount by financial year”** → 2021-22 ₹6.82 crore, 2022-23 ₹14.18 crore, 2024-25 ₹11.50 crore and 2025-26 ₹18.51 crore.  
2. **“which year had the most?”** → 2025-26, with ₹18.51 crore.  
<sub>test bank ✓ · app ✓</sub>

**V7. A conversation**  
1. **“Which district had the most PMAY-G houses sanctioned in 2020-21?”** → West Garo Hills, with 5,906 houses.  
2. **“and the least?”** → East Jaintia Hills, with 253 houses.  
<sub>test bank ✓ · app ✓</sub>

**V8. A conversation**  
1. **“MGNREGA person-days in Ri Bhoi in 2023-24”** → 14,81,572 person-days.  
2. **“break that down by block”** → Umling 5,35,875, Bhoirymbong 4,08,820, Jirang 2,92,876, Umsning 2,30,150 and Mawhati 13,851.  
<sub>test bank ✓ · app ✓</sub>

**V9. A conversation**  
1. **“How many Focus Plus beneficiaries are there in East Khasi Hills?”** → 13,608 beneficiaries.  
2. **“And in Ri Bhoi?”** → 419 in Ri Bhoi.  
3. **“and how much was paid there?”** → ₹52.38 lakh paid in Ri Bhoi.  
<sub>test bank ✓ · app ✓</sub>

**V10. A conversation**  
1. **“MGNREGA households employed in Ri Bhoi in 2024-25”** → 21,533 households.  
2. **“and in 2023-24?”** → 33,736 in 2023-24.  
3. **“and in Umling block?”** → 12,099 in Umling block (2023-24).  
<sub>test bank ✓ · app ✓</sub>

**V11. A conversation**  
1. **“Focus Legacy amount by district”** → West Garo Hills leads with ₹10.93 crore; next East Khasi Hills ₹5.42 crore and North Garo Hills ₹5.17 crore …  
2. **“which district had the least?”** → South West Khasi Hills, with ₹1.75 crore.  
<sub>test bank ✓ · app ✓</sub>

**V12. A conversation**  
1. **“Women employed under MGNREGA in East Garo Hills in 2023-24”** → 27,990 women.  
2. **“break that down by block”** → Dambo Rongjeng 11,129, Songsak 8,963 and Samanda 7,898.  
<sub>test bank ✓ · app ✓</sub>

**V13. A conversation**  
1. **“PMAY-G houses by block in East Khasi Hills”** → Mawsynram leads with 4,957; next Pynursla 4,310 and Mawphlang 3,223 … (eleven blocks).  
2. **“which block has the most?”** → Mawsynram, with 4,957 houses.  
<sub>test bank ✓ · app ✓</sub>

**V14. A conversation**  
1. **“Compare MGNREGA households employed in Ri Bhoi and East Khasi Hills in 2023-24”** → Ri Bhoi 33,736, East Khasi Hills 59,114.  
2. **“only Ri Bhoi”** → Ri Bhoi: 33,736.  
<sub>test bank ✓ · app ✓</sub>

**V15. A conversation**  
1. **“How many MGNREGA person-days were generated in West Garo Hills in 2023-24?”** → 54,89,616 person-days.  
2. **“what about the households instead”** → 72,541 households.  
<sub>test bank ✓ · app ✓</sub>

**V16. A conversation**  
1. **“How many PMAY-G houses were sanctioned by district?”** → West Garo Hills leads with 33,147; next East Khasi Hills 23,952 and Ri Bhoi 17,565 …  
2. **“only the incomplete ones”** → Under construction: West Garo Hills leads with 6,322; next East Khasi Hills 5,767 and South Garo Hills 5,574 …  
<sub>test bank ✓ · app ✓</sub>

**V17. A conversation**  
1. **“How many MGNREGA person-days were generated?”** → 9,09,15,181 person-days (all years).  
2. **“break that down by district”** → West Garo Hills leads with 1,75,39,710; next East Khasi Hills 1,10,54,100 and North Garo Hills 1,07,24,749 … (all twelve).  
3. **“now break it down by block”** → Top blocks: Tikrikilla 46,89,766, Zikzak 44,34,677, Resubelpara 41,31,430, Mawkyrwat 37,14,794 and Dambo Rongjeng 34,71,827 …  
4. **“break it down by financial year”** → 2022-23 2,55,96,237, 2023-24 2,72,64,054, 2024-25 1,46,67,872 and 2025-26 2,33,87,018.  
<sub>test bank ✓ · app ✓</sub>

**V18. A conversation**  
1. **“How many PMAY-G houses were completed in East Garo Hills?”** → 13,784 houses completed.  
2. **“break that down by block”** → Dambo Rongjeng 5,141, Songsak 4,850 and Samanda 3,793.  
3. **“break it down by financial year”** → 2017-18 2,380, 2018-19 562, 2019-20 81, 2020-21 4,920, 2021-22 360, 2022-23 545 and 2023-24 4,936.  
<sub>test bank ✓ · app ✓</sub>

**V19. A conversation**  
1. **“What is the total Focus Legacy amount disbursed in West Garo Hills?”** → ₹10.93 crore.  
2. **“break that down by block”** → Demdema leads with ₹2.01 crore; next Rongram ₹1.96 crore and Selsella ₹1.66 crore …  
3. **“break it down by financial year”** → 2021-22 ₹36.30 lakh, 2022-23 ₹2.65 crore, 2024-25 ₹3.30 crore and 2025-26 ₹4.62 crore.  
<sub>test bank ✓ · app ✓</sub>

**V20. A conversation**  
1. **“How many CM Elevate applications are there in Ri Bhoi?”** → 2,038 valid applications (2,626 in all).  
2. **“scheme wise”** → Valid applications: Meghalaya Piggery Development Scheme leads with 1,474; next PRIME Small Enterprise Empowerment and Development (SEED) 203 and Meghalaya Poultry Farming Scheme 184 …  
<sub>test bank ✓ · app ✓</sub>

**V21. A conversation**  
1. **“Compare beneficiaries across all schemes”** → MGNREGA 14,94,437 households given work (each financial year counted on its own, 2022-23 to 2025-26); PMAY-G 1,71,107 houses sanctioned; Focus Plus 1,05,813 beneficiaries; Focus Legacy 1,02,021 producer-group members; CMSS 98,751 students paid; Homestay 1,297 applications; CM Elevate 8,938 applications (7,375 of them valid); CM Elevate Legacy 2,820 applicants sanctioned.  
2. **“break that down by district”** → Each scheme by district. MGNREGA households: West Garo Hills 2,61,666, East Khasi Hills 2,24,663 and South West Garo Hills 1,64,976 …; PMAY-G houses: West Garo Hills 33,147, East Khasi Hills 23,952 and Ri Bhoi 17,565 … (West Garo Hills leads both: 2,61,666 and 33,147).  
<sub>test bank ✓ · app ✓</sub>

**V22. A conversation**  
1. **“How many Homestay applications are there in East Khasi Hills?”** → 341 applications.  
2. **“break that down by block”** → Shella Bholaganj leads with 87; next Pynursla 42 and Mawpat 38 …  
<sub>test bank ✓ · app ✓</sub>

**V23. A conversation**  
1. **“Compare MGNREGA and PMAY-G beneficiaries”** → MGNREGA 14,94,437 households given work (all years added); PMAY-G 1,71,107 houses.  
2. **“only PMAY-G”** → PMAY-G: 1,71,107 houses.  
<sub>test bank ✓ · app ✓</sub>

**V24. A conversation**  
1. **“MGNREGA person-days by district in 2023-24”** → West Garo Hills leads with 54,89,616; next South West Garo Hills 32,82,990 and North Garo Hills 30,66,633 … (all twelve).  
2. **“now by block”** → Top blocks: Zikzak 14,40,124, Tikrikilla 14,23,794, Resubelpara 12,67,349, Dambo Rongjeng 11,30,734 and Bajengdoba 10,53,505 …  
3. **“only Ri Bhoi”** → Ri Bhoi's blocks: Umling 5,35,875, Bhoirymbong 4,08,820, Jirang 2,92,876, Umsning 2,30,150 and Mawhati 13,851.  
4. **“top 3”** → Umling 5,35,875, Bhoirymbong 4,08,820 and Jirang 2,92,876.  
<sub>new · app ✓</sub>

**V25. A conversation**  
1. **“PMAY-G houses completed by district”** → West Garo Hills leads with 26,822; next East Khasi Hills 18,154 and East Garo Hills 13,784 … (all twelve).  
2. **“only East Khasi Hills”** → East Khasi Hills: 18,154.  
3. **“now by block”** → Pynursla leads with 3,802; next Mawsynram 3,773 and Sohiong 2,261 …  
<sub>new · app ✓</sub>

## Asking for a chart

*The same figures, drawn. The numbers are what is checked.*

**K1. Show MGNREGA person-days trend over the years as a line chart**  
A line over four years: 2022-23 2,55,96,237, 2023-24 2,72,64,054, 2024-25 1,46,67,872 and 2025-26 2,33,87,018.  
<sub>test bank ✓ · app ✓</sub>

**K2. A conversation**  
1. **“Top 5 districts by FOCUS+ beneficiaries as a pie chart”** → A pie of West Garo Hills 35,039, South West Garo Hills 15,294, East Khasi Hills 13,608, East Garo Hills 11,379 and North Garo Hills 11,007.  
2. **“now show it as a bar chart”** → The same five districts as bars.  
<sub>test bank ✓ · app ✓</sub>

**K3. A conversation**  
1. **“MGNREGA person-days by district in 2023-24”** → West Garo Hills leads with 54,89,616; next South West Garo Hills 32,82,990 and North Garo Hills 30,66,633 … (all twelve).  
2. **“now show the same as a horizontal bar chart”** → The same twelve districts, redrawn (if a chart kind is not offered, the app says so and draws the nearest one).  
<sub>test bank ✓ · app ✓</sub>

## What the app declines or asks back

*Questions it should NOT answer with a number, or where it should ask which dataset you mean.*

**D1. Focus Legacy amount disbursed in FY 2023-24?**  
It says Focus Legacy has no payments for 2023-24 (never a zero) and names the years it does hold: 2021-22, 2022-23, 2024-25 and 2025-26.  
<sub>test bank ✓ · app ✓</sub>

**D2. Total CM Elevate amount disbursed in East Khasi Hills?**  
CM Elevate (applications) records no money, so it does not give ₹0. If you meant the payments, CM Elevate Legacy disbursed ₹22.60 crore in East Khasi Hills.  
<sub>test bank ✓ · app ✓</sub>

**D3. How many MGNREGA person-days in Gotham district in FY 2023-24?**  
Gotham is not a district of Meghalaya: it says it cannot find the place, never a silent 0.  
<sub>test bank ✓ · app ✓</sub>

**D4. How many PM-KISAN beneficiaries are there in Meghalaya?**  
PM-KISAN is not one of the eight schemes it holds: said plainly, with no figure.  
<sub>test bank ✓ · app ✓</sub>

**D5. What was the administrative expenditure in Gambegre block during 2023-24?**  
Administrative expenditure is never filled in at source, so it says it is not recorded instead of estimating (the column holds ₹0).  
<sub>test bank ✓ · app ✓</sub>

**D6. How many CM Elevate applications were approved?**  
The data has no 'approved' status (only Pending, Send Back and Rejected), so it asks what you mean instead of guessing.  
<sub>test bank ✓ · app ✓</sub>

**D7. A conversation**  
1. **“Beneficiaries under Focus.”** → 'Focus' is two schemes, so it asks: Focus Plus or Focus Legacy?  
2. **“Focus Plus”** → 1,05,813 Focus Plus beneficiaries.  
<sub>test bank ✓ · app ✓</sub>

**D8. A conversation**  
1. **“CM Elevate records in Ri Bhoi.”** → It asks which CM Elevate dataset: applications or the Legacy disbursements.  
2. **“Applications”** → 2,038 valid applications in Ri Bhoi (2,626 in all).  
<sub>test bank ✓ · app ✓</sub>

**D9. How many PMAY-G houses were sanctioned in 2025-26?**  
PMAY-G sanctions in the data run from 2017-18 to 2023-24; it says 2025-26 is not held, never a zero.  
<sub>new · app ✓</sub>

## Differences found

**Checked and explained** (this guide's queries against the test bank and the catalogue):

- PMAY-G houses (P1): 1,71,107 sanctioned = 1,29,941 completed + 41,041 under construction + 125 not started or with no status. The test bank also checks the 125; it is now shown.
- CM Elevate Legacy “sanctioned applicants”: 3 records (Ri Bhoi, East Garo Hills, East Khasi Hills) were de-sanctioned, with no sanctioned amount and nothing paid. Counting records with a sanctioned amount gives 2,820 (East Khasi Hills 240), as the test bank and the app's all-scheme comparison do; the data team's catalogue measure cm_elevate_disb_beneficiaries (COUNT(DISTINCT application_number), named “sanctioned applicants”) gives 2,823 (East Khasi Hills 241). This guide uses 2,820. Worth a word with the data team.
- Focus Plus by district: the source file's district names and the LGD map differ by about 20 beneficiaries for West Garo Hills and South West Garo Hills (KI-065). Both readings are accepted for those two districts.
- MGNREGA households over several years: the app adds the yearly figures (14,94,437 statewide), the same as its welcome card; a household that worked in several years is counted once per year (an open owner decision, CLAUDE.md §0a''').
- CM Elevate applications: 7,375 valid by default; 8,938 counting every application. The app's “compare all eight schemes” answer uses 8,938 while a direct question uses 7,375; both are correct readings, labelled.

- Every figure the 401-question test bank expects for the same questions is also this guide's figure: the two independent sets of queries agree.

**Where the app's answer did not carry the database figures** (checked 2026-11-15_1805, model on):

- **A10 turn 1: “Which district leads in each scheme?”**  
  DB: MGNREGA: West Garo Hills (2,61,666 households). PMAY-G: West Garo Hills (33,147 houses). Focus Plus: West Garo Hills (35,039 beneficiaries). Focus Legacy: West Garo Hills (21,867 members). CM Elevate: Ri Bhoi (2,038 valid applications). CM Elevate Legacy: West Garo Hills (493 applicants). CMSS: East Khasi Hills (24,932 students paid). Homestay: East Khasi Hills (341 applications).  
  App: **All of Meghalaya, all financial years** / - **MGNREGA:** 14,94,437 households given work (counted once per financial year, FY 2022-23 to 2025-26) / - **PMAY-G:** 1,71,107 houses sanctioned / - **Focus Plus:** 1,05,813 beneficiaries / - **Focus Legacy:** 1,02,021 members / - **CM Elevate:** 8,938 applications / - **CM Elevate Legacy:** 2,820 applicants sanctioned / - **CMSS:** 98,751 students paid / - **Homestay:** 1,297 applications / **MGNREGA** has the most beneficiaries (14,94,437). Order: MGNREGA (14,94,437) > PMAY-G (1,71,107) > Focus Plus (1,05,813) > Focus Legacy (1,02,021 members) > CMSS (98,751) > CM Elevate (8,938) > CM Elevate Legacy (2,820) > Homestay (1,297). /  / Note: years in the data — MGNREGA:  
  <sub>[sql-wrong] row WEST GARO HILLS = 261666 missing; [sql-wrong] row WEST GARO HILLS = 33147 missing; [sql-wrong] row West Garo Hills = 35059 missing; [sql-wrong] row WEST GARO HILLS = 21867 missing; [sql-wrong] row RI BHOI = 2626 missing; [sql-wrong] row WEST GARO HILLS = 493 missing; [sql-wrong] row EAST KHASI HILLS = 24932 missing; [sql-wrong] row EAST KHASI HILLS = 341 missing</sub>

## Appendix: the database query behind every answer

Each query is read-only and runs against `megh_db`, schema `curated`. MGNREGA money columns are in lakh rupees; every other money column is in rupees.

**A1**  
- `mg`: `SELECT SUM(households_employed) FROM curated.v_employment`
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay`
- `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`
- `fl`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy`
- `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss`
- `hs`: `SELECT COUNT(*) FROM curated.v_homestay_api`
- `ce`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate`
- `cev`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate`
- `cl`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement`

**A2**  
- `mg`: `SELECT SUM(households_employed) FROM curated.v_employment`
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay`
- `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`
- `fl`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy`
- `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss`
- `hs`: `SELECT COUNT(*) FROM curated.v_homestay_api`
- `ce`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate`
- `cev`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate`
- `cl`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement`
- `mmg`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure`
- `mpm`: `SELECT SUM(amount_released) FROM curated.v_pmay`
- `mfp`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus`
- `mfl`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy`
- `mcl`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement`
- `mcs`: `SELECT SUM(amount_disbursed) FROM curated.v_cmss`

**A3**  
- `mg`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure`
- `pm`: `SELECT SUM(amount_released) FROM curated.v_pmay`
- `fp`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus`
- `fl`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy`
- `cl`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement`
- `cs`: `SELECT SUM(amount_disbursed) FROM curated.v_cmss`

**A4**  
- `mg`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure`
- `pm`: `SELECT SUM(amount_released) FROM curated.v_pmay`

**A5**  
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay`
- `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`
- `fl`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy`
- `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss`
- `hs`: `SELECT COUNT(*) FROM curated.v_homestay_api`

**A6**  
- `mg`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI'`
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`
- `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'RI BHOI'`
- `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss WHERE lgd_district = 'RI BHOI'`
- `hs`: `SELECT COUNT(*) FROM curated.v_homestay_api WHERE lgd_district = 'RI BHOI'`
- `fl`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy WHERE lgd_district = 'RI BHOI'`
- `ce`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'`
- `cl`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'RI BHOI'`

**A7**  
- `mg`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'EAST KHASI HILLS'`
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'EAST KHASI HILLS'`
- `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'EAST KHASI HILLS'`
- `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss WHERE lgd_district = 'EAST KHASI HILLS'`
- `hs`: `SELECT COUNT(*) FROM curated.v_homestay_api WHERE lgd_district = 'EAST KHASI HILLS'`
- `fl`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy WHERE lgd_district = 'EAST KHASI HILLS'`
- `ce`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district = 'EAST KHASI HILLS'`
- `cl`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'EAST KHASI HILLS'`

**A8**  
- `mg23`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE year_key = 2023`
- `pm23`: `SELECT SUM(amount_released) FROM curated.v_pmay WHERE year_key = 2023`
- `fl24`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE year_key = 2024`
- `cs25`: `SELECT SUM(amount_disbursed) FROM curated.v_cmss WHERE year_key = 2025`
- `mg`: `SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `pm`: `SELECT financial_year_short, SUM(amount_released) FROM curated.v_pmay WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `fp`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_plus WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `fl`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `cl`: `SELECT financial_year_short, SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `cs`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_cmss WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**A9**  
- `all`: `SELECT d, SUM(r) FROM (SELECT lgd_district AS d, SUM(total_exp) * 100000 AS r FROM curated.v_expenditure GROUP BY 1 UNION ALL SELECT lgd_district, SUM(amount_released) FROM curated.v_pmay GROUP BY 1 UNION ALL SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_focus_plus GROUP BY 1 UNION ALL SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_focus_legacy GROUP BY 1 UNION ALL SELECT lgd_district, SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement GROUP BY 1 UNION ALL SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_cmss GROUP BY 1) t WHERE d IS NOT NULL GROUP BY 1 ORDER BY 2 DESC`
- `mg`: `SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `pm`: `SELECT lgd_district, SUM(amount_released) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**A10**  
- `mg`: `SELECT lgd_district, SUM(households_employed) FROM curated.v_employment WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `pm`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `fp (a)`: `SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `fp (b)`: `SELECT district_name_raw, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE district_name_raw IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `fl`: `SELECT lgd_district, SUM(no_of_pg_members) FROM curated.v_focus_legacy WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `ce (a)`: `SELECT lgd_district, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `ce (b)`: `SELECT lgd_district, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `cl`: `SELECT lgd_district, COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `cs`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `hs`: `SELECT lgd_district, COUNT(*) FROM curated.v_homestay_api WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**A11**  
- `mg`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI'`
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`

**A12**  
- `mg`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_block = 'DALU'`
- `pm`: `SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_block = 'DALU'`

**A13**  
- `fp`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE year_key = 2022`
- `fl`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE year_key = 2022`

**A14**  
- `fpb`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`
- `fpa`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus`
- `fla`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy`
- `cla`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement`
- `flm`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy`
- `flg`: `SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy`
- `clb`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement`

**A15**  
- `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'EAST KHASI HILLS'`
- `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss WHERE lgd_district = 'EAST KHASI HILLS'`

**M1**  
- `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE year_key = 2023`

**M2**  
- `v`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure`

**M3**  
- `v`: `SELECT COUNT(DISTINCT village_code) FROM (SELECT village_code FROM curated.v_employment UNION SELECT village_code FROM curated.v_expenditure) t`

**M4**  
- `v`: `SELECT SUM(households_completed_100_days) FROM curated.v_employment WHERE year_key = 2025`

**M5**  
- `v`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`

**M6**  
- `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`

**M7**  
- `v`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'EAST GARO HILLS' AND year_key = 2024`

**M8**  
- `v`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_block = 'GAMBEGRE' AND year_key = 2022`

**M9**  
- `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_block = 'NONGSTOIN' AND year_key = 2025`

**M10**  
- `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE UPPER(lgd_village_name) = 'JAKREM' AND year_key = 2024`

**M11**  
- `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE UPPER(ac_name) = 'MAWSYNRAM' AND year_key = 2024`

**M12**  
- `r`: `SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district IS NOT NULL AND year_key = 2022 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M13**  
- `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M14**  
- `r`: `SELECT lgd_district, SUM(households_completed_100_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2022 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M15**  
- `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M16**  
- `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 ASC NULLS LAST, 1`

**M17**  
- `r`: `SELECT lgd_block, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_block IS NOT NULL AND year_key = 2024 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M18**  
- `r`: `SELECT lgd_block, SUM(person_days) FROM curated.v_employment WHERE lgd_block IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M19**  
- `r`: `SELECT lgd_district, SUM(women_employment_provided) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M20**  
- `r`: `SELECT financial_year_short, SUM(households_employed) FROM curated.v_employment WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**M21**  
- `r`: `SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE financial_year_short IS NOT NULL AND lgd_district = 'RI BHOI' AND year_key BETWEEN 2022 AND 2024 GROUP BY 1 ORDER BY 1`

**M22**  
- `r`: `SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**M23**  
- `a`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE year_key = 2022`
- `b`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE year_key = 2023`

**M24**  
- `a`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2023`
- `b`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`

**M25**  
- `a`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'RI BHOI' AND year_key = 2024`
- `b`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2024`
- `c`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2024`

**M26**  
- `p`: `SELECT 100.0 * SUM(women_employment_provided) / SUM(persons_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`
- `w`: `SELECT SUM(women_employment_provided) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`
- `n`: `SELECT SUM(persons_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`

**M27**  
- `v`: `SELECT SUM(total_exp) * 100000 / NULLIF(SUM(person_days), 0) FROM curated.v_district_year_summary WHERE lgd_district = 'WEST JAINTIA HILLS' AND year_key = 2023`

**M28**  
- `v`: `SELECT 100.0 * SUM(unskilled_wage_exp) / NULLIF(SUM(total_exp), 0) FROM curated.v_expenditure WHERE year_key = 2024`

**M29**  
- `e`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2025`
- `p`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2025`

**M30**  
- `u`: `SELECT ROUND(SUM(unskilled_wage_exp), 2) FROM curated.v_expenditure WHERE UPPER(lgd_village_name) = 'MYRIEM' AND year_key = 2023`
- `s`: `SELECT ROUND(SUM(semi_skilled_wage_exp), 2) FROM curated.v_expenditure WHERE UPPER(lgd_village_name) = 'MYRIEM' AND year_key = 2023`
- `m`: `SELECT ROUND(SUM(material_exp), 2) FROM curated.v_expenditure WHERE UPPER(lgd_village_name) = 'MYRIEM' AND year_key = 2023`
- `t`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE UPPER(lgd_village_name) = 'MYRIEM' AND year_key = 2023`

**M31**  
- `v`: `SELECT ROUND(SUM(material_exp), 2) FROM curated.v_expenditure WHERE year_key = 2024`

**P1**  
- `h`: `SELECT COUNT(*) FROM curated.v_pmay`
- `c`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay`
- `i`: `SELECT COUNT(*) FILTER (WHERE is_in_progress) FROM curated.v_pmay`
- `o`: `SELECT COUNT(*) FILTER (WHERE is_completed IS NOT TRUE AND is_in_progress IS NOT TRUE) FROM curated.v_pmay`

**P2**  
- `h`: `SELECT COUNT(*) FROM curated.v_pmay`
- `c`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay`
- `r (a)`: `SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM curated.v_pmay`
- `r (b)`: `SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM curated.v_pmay WHERE sanctioned_amount > 0`

**P3**  
- `v`: `SELECT SUM(amount_released) FROM curated.v_pmay`

**P4**  
- `v`: `SELECT SUM(amount_pending) FROM curated.v_pmay`
- `s`: `SELECT SUM(sanctioned_amount) FROM curated.v_pmay`

**P5**  
- `v`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district = 'WEST GARO HILLS'`

**P6**  
- `v`: `SELECT SUM(amount_released) FROM curated.v_pmay WHERE lgd_district = 'EAST JAINTIA HILLS'`

**P7**  
- `v (a)`: `SELECT COUNT(*) FILTER (WHERE is_completed IS NOT TRUE) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`
- `v (b)`: `SELECT COUNT(*) FILTER (WHERE is_in_progress) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`

**P8**  
- `s`: `SELECT SUM(sanctioned_amount) FROM curated.v_pmay WHERE lgd_district = 'EAST GARO HILLS'`
- `r`: `SELECT SUM(COALESCE(amount_released, 0)) FROM curated.v_pmay WHERE lgd_district = 'EAST GARO HILLS'`
- `p`: `SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM curated.v_pmay WHERE lgd_district = 'EAST GARO HILLS'`

**P9**  
- `s`: `SELECT SUM(sanctioned_amount) FROM curated.v_pmay WHERE lgd_block = 'AMLAREM'`
- `r`: `SELECT SUM(COALESCE(amount_released, 0)) FROM curated.v_pmay WHERE lgd_block = 'AMLAREM'`
- `p`: `SELECT SUM(sanctioned_amount) - SUM(COALESCE(amount_released, 0)) FROM curated.v_pmay WHERE lgd_block = 'AMLAREM'`

**P10**  
- `v`: `SELECT COUNT(*) FROM curated.v_pmay WHERE UPPER(lgd_village_name) = 'GABIL SONGGITCHAM'`

**P11**  
- `r`: `SELECT COALESCE(status_name, 'No status'), COUNT(*) FROM curated.v_pmay WHERE COALESCE(status_name, 'No status') IS NOT NULL AND UPPER(lgd_village_name) = 'GABIL SONGGITCHAM' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**P12**  
- `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**P13**  
- `r`: `SELECT financial_year_short, COUNT(*) FROM curated.v_pmay WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `n`: `SELECT COUNT(*) FROM curated.v_pmay WHERE year_key IS NULL`

**P14**  
- `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**P15**  
- `r`: `SELECT lgd_block, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**P16**  
- `h`: `SELECT COUNT(*) FROM curated.v_pmay`
- `r`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**P17**  
- `a`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`
- `b`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district = 'WEST JAINTIA HILLS'`

**P18**  
- `v (a)`: `SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'SOUTH GARO HILLS'`
- `v (b)`: `SELECT 100.0 * COUNT(*) FILTER (WHERE is_completed) / COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'SOUTH GARO HILLS' AND sanctioned_amount > 0`

**P19**  
- `v`: `SELECT 100.0 * SUM(COALESCE(amount_released, 0)) / SUM(sanctioned_amount) FROM curated.v_pmay WHERE lgd_district = 'NORTH GARO HILLS'`

**P20**  
- `v`: `SELECT 100.0 * COUNT(*) FILTER (WHERE lgd_district = 'WEST GARO HILLS') / COUNT(*) FROM curated.v_pmay`
- `n`: `SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'WEST GARO HILLS'`
- `t`: `SELECT COUNT(*) FROM curated.v_pmay`

**P21**  
- `r`: `SELECT lgd_block, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_block IS NOT NULL AND lgd_district = 'WEST GARO HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**F1**  
- `v`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus`
- `n`: `SELECT COUNT(*) FROM curated.v_focus_plus`

**F2**  
- `b`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE year_key = 2022`
- `a`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE year_key = 2022`

**F3**  
- `r`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_plus WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**F4**  
- `r (a)`: `SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `r (b)`: `SELECT district_name_raw, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE district_name_raw IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**F5**  
- `r (a)`: `SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `r (b)`: `SELECT district_name_raw, SUM(amount_disbursed) FROM curated.v_focus_plus WHERE district_name_raw IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**F6**  
- `r (a)`: `SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 ASC NULLS LAST, 1`
- `r (b)`: `SELECT district_name_raw, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE district_name_raw IS NOT NULL GROUP BY 1 ORDER BY 2 ASC NULLS LAST, 1`

**F7**  
- `r`: `SELECT gender, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE gender IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `n`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE gender IS NULL`

**F8**  
- `v`: `SELECT 1.0 * SUM(amount_disbursed) / COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`

**F9**  
- `a`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'EAST KHASI HILLS'`
- `b`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'NORTH GARO HILLS'`

**F10**  
- `v`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE UPPER(block_name_raw) = 'SELSELLA'`

**F11**  
- `v`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE tranche_label = 'Tranch 1'`
- `t`: `SELECT tranche_label, SUM(amount_disbursed) FROM curated.v_focus_plus WHERE tranche_label IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**L1**  
- `g`: `SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy`
- `a`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy`
- `y`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**L2**  
- `v`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE year_key = 2024`

**L3**  
- `r`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**L4**  
- `r`: `SELECT lgd_district, COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**L5**  
- `r`: `SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**L6**  
- `r`: `SELECT lgd_district, COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**L7**  
- `a`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE year_key = 2022`
- `b`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE year_key = 2024`

**L8**  
- `a`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district = 'RI BHOI'`
- `b`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district = 'WEST GARO HILLS'`
- `c`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district = 'EAST KHASI HILLS'`

**L9**  
- `v`: `SELECT SUM(amount_disbursed)::numeric / COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE lgd_district = 'EAST JAINTIA HILLS'`

**L10**  
- `v`: `SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE UPPER(ac_name) = 'MAWSYNRAM'`

**L11**  
- `v`: `SELECT COUNT(DISTINCT pg_id) FROM curated.v_focus_legacy WHERE lgd_block = 'MAWKYRWAT'`

**E1**  
- `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate`
- `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate`
- `s`: `SELECT COALESCE(data_verified, 'not recorded'), COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE COALESCE(data_verified, 'not recorded') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**E2**  
- `r (a)`: `SELECT lgd_district, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `r (b)`: `SELECT lgd_district, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**E3**  
- `r (a)`: `SELECT scheme_name, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE scheme_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `r (b)`: `SELECT scheme_name, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE scheme_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**E4**  
- `r (a)`: `SELECT scheme_name, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE scheme_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `r (b)`: `SELECT scheme_name, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE scheme_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**E5**  
- `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district = 'EAST KHASI HILLS'`
- `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_district = 'EAST KHASI HILLS'`

**E6**  
- `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_block = 'JIRANG'`
- `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_block = 'JIRANG'`

**E7**  
- `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI' AND scheme_name = 'Meghalaya Piggery Development Scheme'`
- `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI' AND scheme_name = 'Meghalaya Piggery Development Scheme'`

**E8**  
- `v`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid' AND file_status IN ('Pending', 'Send Back')) FROM curated.v_cm_elevate`

**E9**  
- `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE file_status = 'Rejected'`
- `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE file_status = 'Rejected'`

**E10**  
- `r (a)`: `SELECT COALESCE(file_status, '(not recorded)'), COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE COALESCE(file_status, '(not recorded)') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `r (b)`: `SELECT COALESCE(file_status, '(not recorded)'), COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE COALESCE(file_status, '(not recorded)') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**C1**  
- `v`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement`

**C2**  
- `t`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement`
- `s`: `SELECT SUM(total_subsidy_disbursement) FROM curated.v_cm_elevate_disbursement`
- `l`: `SELECT SUM(total_loan_disbursement) FROM curated.v_cm_elevate_disbursement`

**C3**  
- `v`: `SELECT COUNT(*) FROM curated.v_cm_elevate_disbursement`
- `a`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement`
- `d`: `SELECT COUNT(*) FILTER (WHERE sanctioned_amount IS NULL) FROM curated.v_cm_elevate_disbursement`

**C4**  
- `r`: `SELECT scheme_name, SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE scheme_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**C5**  
- `r`: `SELECT scheme_name, SUM(total_subsidy_disbursement) FROM curated.v_cm_elevate_disbursement WHERE scheme_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**C6**  
- `r`: `SELECT lgd_district, SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**C7**  
- `r`: `SELECT loan_entity, COUNT(*) FROM curated.v_cm_elevate_disbursement WHERE loan_entity IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- `n`: `SELECT COUNT(*) FROM curated.v_cm_elevate_disbursement WHERE loan_entity IS NULL`

**C8**  
- `r`: `SELECT financial_year_short, SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- `n`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE year_key IS NULL`

**C9**  
- `v`: `SELECT SUM(total_subsidy_disbursement) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'RI BHOI'`

**C10**  
- `v`: `SELECT SUM(total_loan_disbursement) FROM curated.v_cm_elevate_disbursement WHERE loan_entity = 'LIFCOM'`

**C11**  
- `a`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'WEST GARO HILLS'`
- `b`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'EAST KHASI HILLS'`

**C12**  
- `v`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'RI BHOI' AND year_key = 2025`

**S1**  
- `v`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss`
- `a`: `SELECT SUM(amount_disbursed) FROM curated.v_cmss`

**S2**  
- `v`: `SELECT SUM(amount_disbursed) FROM curated.v_cmss`

**S3**  
- `a`: `SELECT COUNT(*) FROM curated.v_cmss`
- `p`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss`

**S4**  
- `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**S5**  
- `v`: `SELECT COUNT(*) FROM curated.v_homestay_api`

**S6**  
- `v`: `SELECT COUNT(*) FILTER (WHERE file_status = 'Approved') FROM curated.v_homestay_api`
- `s`: `SELECT COALESCE(file_status, 'not recorded'), COUNT(*) FROM curated.v_homestay_api WHERE COALESCE(file_status, 'not recorded') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**S7**  
- `r`: `SELECT lgd_district, COUNT(*) FROM curated.v_homestay_api WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**S8**  
- `r`: `SELECT financial_year_short, COUNT(*) FROM curated.v_homestay_api WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**V1**  
- turn 1, `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2023`
- turn 2, `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`
- turn 3, `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2022`

**V2**  
- turn 1, `r`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 3, `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V3**  
- turn 1, `r`: `SELECT financial_year_short, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- turn 2, `r`: `SELECT lgd_district, ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 3, `v`: `SELECT ROUND(SUM(total_exp), 2) FROM curated.v_expenditure WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`

**V4**  
- turn 1, `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`
- turn 2, `v`: `SELECT SUM(persons_employed) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`
- turn 3, `v`: `SELECT SUM(women_employment_provided) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`

**V5**  
- turn 1, `v`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`
- turn 2, `v`: `SELECT SUM(sanctioned_amount) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`
- turn 3, `v`: `SELECT 100.0 * SUM(COALESCE(amount_released, 0)) / SUM(sanctioned_amount) FROM curated.v_pmay WHERE lgd_district = 'RI BHOI'`

**V6**  
- turn 1, `r`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`
- turn 2, `r`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V7**  
- turn 1, `r`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL AND year_key = 2020 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL AND year_key = 2020 GROUP BY 1 ORDER BY 2 ASC NULLS LAST, 1`

**V8**  
- turn 1, `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`
- turn 2, `r`: `SELECT lgd_block, SUM(person_days) FROM curated.v_employment WHERE lgd_block IS NOT NULL AND lgd_district = 'RI BHOI' AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V9**  
- turn 1, `v`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'EAST KHASI HILLS'`
- turn 2, `v`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district = 'RI BHOI'`
- turn 3, `v`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_plus WHERE lgd_district = 'RI BHOI'`

**V10**  
- turn 1, `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2024`
- turn 2, `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`
- turn 3, `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_block = 'UMLING' AND year_key = 2023`

**V11**  
- turn 1, `r`: `SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_district, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 ASC NULLS LAST, 1`

**V12**  
- turn 1, `v`: `SELECT SUM(women_employment_provided) FROM curated.v_employment WHERE lgd_district = 'EAST GARO HILLS' AND year_key = 2023`
- turn 2, `r`: `SELECT lgd_block, SUM(women_employment_provided) FROM curated.v_employment WHERE lgd_block IS NOT NULL AND lgd_district = 'EAST GARO HILLS' AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V13**  
- turn 1, `r`: `SELECT lgd_block, COUNT(*) FROM curated.v_pmay WHERE lgd_block IS NOT NULL AND lgd_district = 'EAST KHASI HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_block, COUNT(*) FROM curated.v_pmay WHERE lgd_block IS NOT NULL AND lgd_district = 'EAST KHASI HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V14**  
- turn 1, `a`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`
- turn 1, `b`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2023`
- turn 2, `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'RI BHOI' AND year_key = 2023`

**V15**  
- turn 1, `v`: `SELECT SUM(person_days) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`
- turn 2, `v`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023`

**V16**  
- turn 1, `r`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_in_progress) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V17**  
- turn 1, `v`: `SELECT SUM(person_days) FROM curated.v_employment`
- turn 2, `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 3, `r`: `SELECT lgd_block, SUM(person_days) FROM curated.v_employment WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 4, `r`: `SELECT financial_year_short, SUM(person_days) FROM curated.v_employment WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**V18**  
- turn 1, `v`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district = 'EAST GARO HILLS'`
- turn 2, `r`: `SELECT lgd_block, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_block IS NOT NULL AND lgd_district = 'EAST GARO HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 3, `r`: `SELECT financial_year_short, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE financial_year_short IS NOT NULL AND lgd_district = 'EAST GARO HILLS' GROUP BY 1 ORDER BY 1`

**V19**  
- turn 1, `v`: `SELECT SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_district = 'WEST GARO HILLS'`
- turn 2, `r`: `SELECT lgd_block, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE lgd_block IS NOT NULL AND lgd_district = 'WEST GARO HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 3, `r`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL AND lgd_district = 'WEST GARO HILLS' GROUP BY 1 ORDER BY 1`

**V20**  
- turn 1, `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'`
- turn 1, `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'`
- turn 2, `r (a)`: `SELECT scheme_name, COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE scheme_name IS NOT NULL AND lgd_district = 'RI BHOI' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r (b)`: `SELECT scheme_name, COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE scheme_name IS NOT NULL AND lgd_district = 'RI BHOI' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V21**  
- turn 1, `mg`: `SELECT SUM(households_employed) FROM curated.v_employment`
- turn 1, `pm`: `SELECT COUNT(*) FROM curated.v_pmay`
- turn 1, `fp`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`
- turn 1, `fl`: `SELECT SUM(no_of_pg_members) FROM curated.v_focus_legacy`
- turn 1, `cs`: `SELECT COUNT(*) FILTER (WHERE is_disbursed) FROM curated.v_cmss`
- turn 1, `hs`: `SELECT COUNT(*) FROM curated.v_homestay_api`
- turn 1, `ce`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate`
- turn 1, `cev`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate`
- turn 1, `cl`: `SELECT COUNT(sanctioned_amount) FROM curated.v_cm_elevate_disbursement`
- turn 2, `mg`: `SELECT SUM(households_employed) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS'`
- turn 2, `pm`: `SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'WEST GARO HILLS'`
- turn 2, `mgr`: `SELECT lgd_district, SUM(households_employed) FROM curated.v_employment WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `pmr`: `SELECT lgd_district, COUNT(*) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V22**  
- turn 1, `v`: `SELECT COUNT(*) FROM curated.v_homestay_api WHERE lgd_district = 'EAST KHASI HILLS'`
- turn 2, `r`: `SELECT lgd_block, COUNT(*) FROM curated.v_homestay_api WHERE lgd_block IS NOT NULL AND lgd_district = 'EAST KHASI HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V23**  
- turn 1, `mg`: `SELECT SUM(households_employed) FROM curated.v_employment`
- turn 1, `pm`: `SELECT COUNT(*) FROM curated.v_pmay`
- turn 2, `pm`: `SELECT COUNT(*) FROM curated.v_pmay`

**V24**  
- turn 1, `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_block, SUM(person_days) FROM curated.v_employment WHERE lgd_block IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 3, `r`: `SELECT lgd_block, SUM(person_days) FROM curated.v_employment WHERE lgd_block IS NOT NULL AND lgd_district = 'RI BHOI' AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 4, `r`: `SELECT lgd_block, SUM(person_days) FROM curated.v_employment WHERE lgd_block IS NOT NULL AND lgd_district = 'RI BHOI' AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**V25**  
- turn 1, `r`: `SELECT lgd_district, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `v`: `SELECT COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_district = 'EAST KHASI HILLS'`
- turn 3, `r`: `SELECT lgd_block, COUNT(*) FILTER (WHERE is_completed) FROM curated.v_pmay WHERE lgd_block IS NOT NULL AND lgd_district = 'EAST KHASI HILLS' GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**K1**  
- `r`: `SELECT financial_year_short, SUM(person_days) FROM curated.v_employment WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**K2**  
- turn 1, `r (a)`: `SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 1, `r (b)`: `SELECT district_name_raw, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE district_name_raw IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r (a)`: `SELECT lgd_district, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE lgd_district IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r (b)`: `SELECT district_name_raw, COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus WHERE district_name_raw IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**K3**  
- turn 1, `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`
- turn 2, `r`: `SELECT lgd_district, SUM(person_days) FROM curated.v_employment WHERE lgd_district IS NOT NULL AND year_key = 2023 GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**D1**  
- `y`: `SELECT financial_year_short, SUM(amount_disbursed) FROM curated.v_focus_legacy WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

**D2**  
- `cl`: `SELECT SUM(total_disbursement) FROM curated.v_cm_elevate_disbursement WHERE lgd_district = 'EAST KHASI HILLS'`

**D3**  

**D4**  

**D5**  
- `v`: `SELECT SUM(admin_total_exp) FROM curated.v_expenditure WHERE lgd_block = 'GAMBEGRE' AND year_key = 2023`

**D6**  
- `s`: `SELECT COALESCE(file_status, '(not recorded)'), COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE COALESCE(file_status, '(not recorded)') IS NOT NULL GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1`

**D7**  
- turn 2, `v`: `SELECT COUNT(DISTINCT beneficiary_key) FROM curated.v_focus_plus`

**D8**  
- turn 2, `v (a)`: `SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified = 'Valid') FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'`
- turn 2, `v (b)`: `SELECT COUNT(DISTINCT request_id) FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'`

**D9**  
- `y`: `SELECT financial_year_short, COUNT(*) FROM curated.v_pmay WHERE financial_year_short IS NOT NULL GROUP BY 1 ORDER BY 1`

