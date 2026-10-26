# Change Report: Problems, Solutions and Results (2026-10-24 to 2026-10-26)

The current, uncommitted changes on branch `update/2026-10-24`. Each section gives the problem, its root cause, the solution, the files changed and the verified result. The earlier, committed work (1024 embeddings, memory fixes, `.gitignore`, doc folder fix) is summarised at the end.

---

## 1. Financial years ("FY24", "FY 25", "FY'25")

### Problem
| Symptom | Example |
|---|---|
| "FY24" answered for the wrong year | "MGNREGA expenditure, East Khasi Hills, FY24" -> FY 2024-25 (11,050.42 lakh) instead of FY 2023-24 |
| A follow-up kept the previous year | after an FY 2022-23 answer, "give me FY 25" -> FY 2022-23 again (user screenshot) |
| A follow-up year replaced by the old one | "FY20?" rewritten to "… in FY 2022-23 …" |
| A year with no data got a made-up answer | "Focus Legacy … Ri Bhoi … FY 20" -> answered for "FY 2020-21" |
| A bare year message refused | "FY'25" -> "Sorry, I didn't quite catch that" |

### Root cause
1. The year parser read FY<yy> as `2000 + yy` (FY24 -> 2024-25). Every scheme team's own file reads it as the year **ending** in 20<yy> (FY24 = FY 2023-24).
2. The code had **four separate year readers**, and only one knew short forms like "FY 25". When the AI extractor dropped the year (it sometimes returns nothing), the others could not recover it:
   - the "no data for that year" guard did not see "FY 20";
   - the year back-fill only knew "2024-25" style;
   - the follow-up rewrite check (D-024) saw no year in "FY20?", so it allowed the previous year;
   - the first message filter rejected the apostrophe in "FY'25".

**Nothing was hard-coded.** "FY23 works" only because FY23 happened to be extracted in those runs.

### Solution
- **One rule:** FY<yy> = FY (20<yy> − 1)-<yy>; a range "FY 23-24" keeps its first year.
- **One shared short-form reader**, `context_policy.short_fy_tokens` ("FY 25", "FY25", "FY'25", "FY 23-24", "in 23-24"), used by every year check:
  - `extract_year_keys` (about 25 callers: follow-ups, the rewrite check, the cache key …);
  - the "no data for that year" guard;
  - the year back-fill.
- **Rewrite check:** a follow-up rewrite must keep the year the user typed (adding a second year for a comparison is still allowed).
- **First filter** accepts "FY'25".
- **When the extractor returns only digits ("24")**, the year is read from the question itself.
- **Unchanged on purpose:** when the extractor does return a year, it is kept (an existing pinned rule; every failure seen was a dropped year, never a wrong one).

### Files
`app/pipeline/common/c07_mentions.py` (`_parse_year_key`, `_backfill_explicit_year`), `c09_resolve_entities.py`, `c06_years_tranches.py` (`_c06_short_fy_tokens`, `_c06_all_year_tokens`), `app/context_policy.py` (`short_fy_tokens`, `extract_year_keys`, `rewrite_violation`), `app/edge.py`, `c12_answer_numbers.py` (comment).

### Result (live)
| Check | Before | After |
|---|---|---|
| "FY24" / "FY 24" / "FY 23-24", East Khasi Hills | FY24 gave FY 2024-25 | all three: **8,996.36 lakh, FY 2023-24** |
| Follow-up "give me FY 25" after FY 2022-23 | FY 2022-23 | **FY 2024-25, 14,667,872 person-days** |
| Follow-up sweep: FY18–FY26 × "give me FY nn" / "FYnn?" / "FY'nn" × MGNREGA, PMAY-G, Focus Legacy | 52/54 | **81/81** |
| A year with no data (e.g. Focus Legacy FY20) | invented answer | "data is available only for …" |

---

## 2. A scope the officer states is no longer asked again

### Problem
The app asked "which year?" or "which area?" even when the question already said it in a wording it did not know. So two wordings of one question took two paths.

| Question | Before |
|---|---|
| "… in East Khasi Hills **altogether**" | asked "which financial year?" |
| "… **all reporting years taken together**", "**since the start**", "**lifetime**" | asked the year |
| "… in **entire Meghalaya** …", "**for the state**" | asked the area |
| "**Which districts** spent over 20 crore …" | asked the area |

### Root cause
The scope word lists (`_ALL_YEARS_CUE`, `_EXPLICIT_STATEWIDE`, `_HAS_BREAKDOWN`) only knew exact phrasings.

### Solution
- New "all years" phrasings in a **separate list**, `_STATED_ALL_YEARS_CUE`, read only by the "ask the year?" gate. It is kept out of `_ALL_YEARS_CUE`, because the SQL checker drops its compulsory-year check when that list matches, and "altogether in FY 2024-25" must keep that check.
- New statewide phrasings, and plural list questions ("which districts …", "list the blocks …").
- **Option A (answer with a default) was NOT re-applied.** You reversed it before (D-053, D-056, D-065), so a question that states **nothing** still asks.

### Files
`c05_clarifications.py`, `c06_years_tranches.py`.

### Result
| Question | After |
|---|---|
| "… altogether" | **41,492.84 lakh, all years** (live) |
| "since the start", "lifetime", "entire Meghalaya", "which districts …" | answered, not asked |
| "Total MGNREGA expenditure" (nothing stated) | still asks (your rule) |
| Held-out data golden set | 40/74 -> **42/74** (3 fixed) |

---

## 3. Ranking counts written as words ("five highest")

### Problem
"Five highest blocks by person-days" asked "Top 3 / 5 / 10?" although it states five. "Top 5" was answered.

### Root cause
The count check read only digits ("5 highest"), not words.

### Solution
- `_normalize_rank_counts` (c02) turns a count word into digits, **only in a ranking position**: "five highest" -> "5 highest", "top ten" -> "top 10", "which three blocks" -> "which 3 blocks".
- Left alone: "fifth highest", "last five years", "the first one", "which one", "the two schemes".
- `_stated_rank_count_limit` (c11) sets the SQL `LIMIT` to the stated count in code. It never touches "top 5 in each district", "top 5 and bottom 5", rank-with-ties queries or paging.
- The officer's original words are what is saved in chat history.

### Files
`c02_rephraser.py`, `c14_turn_stages.py`, `c11_sql_verify_repair.py`.

### Result (live, West Garo Hills officer)
"Top 5" / "**Five highest**" / "5 highest" / "Which five … most" / "Top five" blocks by person-days, WGH, FY 2023-24 -> **the same 5 blocks, same order** (TIKRIKILLA, RONGRAM, DALU, SELSELLA, DADENGGIRI). "Five highest" no longer asks.

---

## 4. Protection added

| Problem | Solution |
|---|---|
| The pipeline files share one set of names. A new table of mine overwrote the spoken-year table, and "two zero two three" stopped reading as 2023 (caught by tests, fixed) | Renamed it, plus a new guard test, `tests/test_pipeline_namespace_2026_10_26.py`, that fails if any name is defined twice; rule added to CLAUDE.md |
| Golden-set questions must never appear in code or tests | My first test draft quoted two; the hold-out guard caught it and I replaced them with my own wordings |

---

## 5. Measured, no change needed

The same question was asked 5 times, for 10 questions: **identical SQL and result every time** (the models already run at temperature 0). Two wordings of one question: 9 of 10 pairs gave the same result. Adding a seed (C7) was therefore not done.

---

## 6. Overall test results

| Check | Result |
|---|---|
| Unit tests | **3,777 passed**, 2 failed (KI-415 below, not from these changes) |
| Plain-script suites | 14/14 |
| Live multi-turn suite | 103/107 (the same 4 older failures, KI-405 to KI-407) |
| New regression tests | 5 files: `test_stated_scope_2026_10_24.py`, `test_rank_count_words_2026_10_26.py`, `test_short_fy_forms_2026_10_26.py`, `test_pipeline_namespace_2026_10_26.py`, plus `test_embedding_size_guard_2026_10_24.py` (committed) |

No regex was added; text is read with the project's word matcher and SQL is changed through the SQL tree. No database, schema or `.env` change.

---

## 7. Still open (found, not fixed)

| Issue | What |
|---|---|
| KI-415 | Some "compare Garo Hills and Khasi Hills regions" example queries in the scheme files are invalid SQL; the 2 failing tests |
| KI-416 | After a "houses sanctioned" question, "FY20?" once answered the sanctioned **amount**; "sanctioned" alone is ambiguous |
| KI-411 | PM-04 sometimes splits "every financial year" by year instead of one total |
| KI-404 | "How does MGNREGA job card registration work?" goes to the data path |
| KI-405 to KI-407 | Older multi-turn issues (scheme switch during a pause, year carry-over decision, a stale CM Elevate test) |

---

## 8. Earlier work (already committed)

| Commit | What |
|---|---|
| `9c7c67c` | 1024-dim embeddings completed: startup size check (KI-402), 30-day clean-up of both memory collections (KI-403), 12,046 chats migrated, exact memory search with indexes (KI-408) |
| `0aa135c` | `.gitignore`: `raw_uc/`, `new_docs/*.csv`, Word lock files |
| `dd8b58b` | Docs name the real knowledge-base folder `data/incoming/<scheme>/` |

## 9. Rollback

Revert the 10 changed app files and delete the 4 new test files. No data was changed.
