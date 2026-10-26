# Before / After Behaviour Report (2026-10-24 to 2026-10-26)

What each fix changed, shown with examples. Every "after" example below was run on the live system (port 8401, real models, read-only database) unless marked *(function check)*, which means it was run against the real code function directly.

---

## 1. "FY24" now means FY 2023-24 (KI-409, D-068)

**Before:** "FY24" was read as FY 2024-25. In Indian government use, and in every scheme team's own files, FY24 is the year ending March 2024, i.e. FY 2023-24.

| Question | Before | After |
|---|---|---|
| Total MGNREGA expenditure in East Khasi Hills in **FY24** | **11,050.42 lakh, FY 2024-25 (wrong year)** | **8,996.36 lakh, FY 2023-24** |
| … in **FY 24** | year not resolved; the SQL model guessed 2024-25 | 8,996.36 lakh, FY 2023-24 |
| … in **FY 23-24** | 8,996.36 lakh, FY 2023-24 | 8,996.36 lakh, FY 2023-24 (unchanged) |
| PMAY-G houses sanctioned in East Garo Hills in **FY23** | read as FY 2023-24 | read as **FY 2022-23** |

**Result:** three ways of writing the same year give one answer.

## 2. A scope the officer states is never asked again (KI-410, D-068)

**Before:** the app asked "which year?" or "which area?" when the question already said so in a wording it did not recognise. **After:** any wording that states the scope is answered. A question that states **nothing** is still asked, as your rules (D-053 / D-056) require.

| Question | Before | After |
|---|---|---|
| Total MGNREGA expenditure in East Khasi Hills **altogether** | asked "which financial year?" | **41,492.84 lakh, all financial years** |
| PMAY-G houses still incomplete in East Garo Hills, **all reporting years taken together** *(function check)* | asked "which financial year?" | not asked; answered for all years |
| Total MGNREGA expenditure in East Khasi Hills **since the start / lifetime / for the whole period** *(function check)* | asked the year | not asked |
| Total MGNREGA expenditure **in entire Meghalaya** in FY 2023-24 *(function check)* | asked the area | not asked; statewide |
| **Which districts** spent over 20 crore on MGNREGA wages in FY 2023-24? *(function check)* | asked "which area?" | not asked; all districts listed |
| Total MGNREGA expenditure *(nothing stated)* | asked area, then year | **still asks** (unchanged, by your rule) |

**Held-out data set:** the three held-out questions of this kind (MG-11, PM-13, CL-03) went from "asked back" to **correct**. Overall: 40/74 → 42/74.

**Safety detail:** the new "all years" phrases are kept out of the list the SQL checker uses. So a question like "how many … **altogether in FY 2024-25**" still has its year filter enforced.

## 3. Ranking counts written as words (KI-412)

**Before:** a count written as a word ("five highest") made the app ask "top 3, 5 or 10?" even though the officer said five. A count in digits ("top 5") was answered. **After:** the count is read in any form, and the SQL returns exactly that many rows.

Live, logged in as the West Garo Hills officer, "… blocks by person-days in West Garo Hills in FY 2023-24":

| Wording | Before | After |
|---|---|---|
| **Top 5** blocks … | answered | TIKRIKILLA, RONGRAM, DALU, SELSELLA, DADENGGIRI (LIMIT 5) |
| **Five highest** blocks … | **asked "Top 3 / 5 / 10 / all?"** | **the same 5 blocks, same order** (LIMIT 5) |
| **5 highest** blocks … | answered | the same 5 blocks |
| **Which five** blocks had the most … | answered | the same 5 blocks |
| **Top five** blocks … | answered | the same 5 blocks |

**Correctly left as they were** *(function check)*:

| Wording | Behaviour |
|---|---|
| "**fifth** highest block" | one block at rank 5, not a list of 5 |
| "**second** highest district" | one district at rank 2 |
| "spend over the **last five years**" | a time span, not a ranking |
| "show me **the first one**", "**which one** district" | not a count |
| "the **five districts** of Garo Hills" | not a ranking |
| "**top 5 in each district**", "**district-wise top 3**" | per-group ranking; the model handles it as before |
| "**top 5 and bottom 5**" | two lists; the model handles it as before |
| "which blocks had **the most** …" *(no number)* | still asks "Top 3 / 5 / 10?" |

**SQL safety net:** if the model writes LIMIT 10 or 20, or forgets the LIMIT, for "top 5", the code sets LIMIT 5. It never touches window-ranking queries, paging or two-way rankings.

## 4. Repeat and paraphrase consistency (measured, no code change)

| Test | Result |
|---|---|
| The same question, 5 runs, 10 questions | **10/10 identical SQL and result every time** |
| Two wordings of one question, 10 pairs | **9/10 the same result** |
| The one difference | "houses **sanctioned**" was counted; "the most **sanctions**" was read as the **rupee amount**. A meaning ambiguity, for the metric catalogue (B1), not randomness |

**Decision:** adding a seed (C7) was not needed; the models already run at temperature 0.

## 5. Embeddings and chat memory (1024-dim, D-067 completed; KI-402, 403, 408)

| Area | Before | After |
|---|---|---|
| Knowledge base and chat memory | 384-dim local model | **1024-dim qwen3 model**, live |
| Changing the embedding model without a new collection | knowledge answers silently said "not covered", and a restart did not repair it | the app detects the size mismatch at startup and rebuilds the knowledge base; chat memory switches off with a clear error and is never deleted |
| Old chats after the switch | would have been lost to recall, and never deleted after 30 days | **12,046 chats copied** to the new memory (recall 20/20); both memory collections deleted after 30 days |
| Finding an earlier chat | 58/60 matched a perfect search; 1 in 300 useful turns missed | **60/60, 0 missed**, same speed |
| Knowledge answers (188-question set) | 92.0% correct-or-honest, 17.1% with a made-up claim | 92.0% correct-or-honest, **13.9%** with a made-up claim |

## 6. Protection added along the way

| Protection | Why |
|---|---|
| Guard test: no name defined twice across the pipeline files | A new table overwrote the spoken-year table ("two zero two three" stopped reading as 2023); caught, fixed, and now blocked for the future (KI-413) |
| Hold-out guard respected | Golden-set questions are never copied into code or tests, so the score stays honest |
| `.gitignore`: `raw_uc/`, `new_docs/*.csv` | Personal-data files cannot be committed by accident |

## 7. Overall checks after all fixes

| Check | Result |
|---|---|
| Unit tests | **3,742 passed, 0 failed** |
| Plain-script suites | 14/14 |
| Held-out data set | 42/74, 0 regressions from these fixes (the remaining 31 "asked back" follow your ask-when-nothing-stated rule) |
| Live multi-turn suite | 103/107 (the 4 failures predate these changes: KI-405 to KI-407) |

## 8. Known limits (not fixed yet)

- **PM-04 (KI-411):** "counting every financial year" is sometimes split by year instead of one total. It does the same on the original code.
- **"How does MGNREGA job card registration work?" (KI-404)** goes to the data path instead of the knowledge base.
- **"Sanctions" alone** is ambiguous between house count and amount (metric catalogue, B1).
