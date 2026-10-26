# D-068 Technical Report: Stated Scope and "FY24" (2026-10-24)

The code changes that make different wordings of the same question resolve to the same year and scope. Uncommitted on branch `update/2026-10-24` (base `dd8b58b`).

## 1. Problem

| # | Symptom | Root cause (verified in code) |
|---|---|---|
| P1 | "FY24" answered for FY 2024-25 | `c07_mentions._parse_year_key` returned `2000 + yy` for `FY<yy>`; every SME catalogue reads FY<yy> as the year **ending** in 20<yy> (FY23 = 2022-23 in `focusplus_entity_resolver.yaml`, FY25 = 2024-25 in `cmelevatelegacy_entity_resolver.yaml`) |
| P2 | "FY24" still wrong after P1 was fixed | `c02_rephraser._correct_fy_spacing` turns "FY24" into "FY 24"; the LLM extractor (`extract_entity_mentions`) then returns `year = "24"`; `_parse_year_key("24")` is `None`, so `resolve_entities` resolved **no** year and the SQL model read "FY 24" as 2024-25 |
| P3 | "taking all sanction years together", "altogether", "lifetime", "since the start", "for the whole period" asked "which year?" | `_ALL_YEARS_CUE` (c06) matched only contiguous forms ("all [the] [financial] years"); one word between "all" and "years" broke it |
| P4 | "altogether", "whole state", "entire Meghalaya", "for the state" asked "which area?" | `_EXPLICIT_STATEWIDE` (c05) had no such phrases |
| P5 | "Which districts had … above X" asked "which area?" | `_HAS_BREAKDOWN` (c05) caught "which district … highest" (superlative) but not a plain plural list question |

Not a problem, left unchanged: a question that states **no** year and **no** place still asks (user decisions D-053, D-056, D-065).

## 2. Design decisions

1. **Option A (answer with a default) NOT re-applied.** It existed as D-045 / `ANSWER_DEFAULTS_ENABLED` (2026-10-14) and the user reversed it (D-053: "if nothing is there you need to ask"). The fix is in **reading** the scope, not in the policy.
2. **A separate cue for the new all-years phrases (`_STATED_ALL_YEARS_CUE`).** `_ALL_YEARS_CUE` is read in 8 places, including the SQL verifier (`c11_sql_verify_repair.py:1083`), which **skips the mandatory-year check** when it matches. Adding "altogether" there would let "how many … altogether in FY 2024-25" pass a query that sums every year. The new cue is read **only** by the year gate. When the gate does not ask, `c13._data_clarification_stage` (existing code) appends the standard "across all financial years", which every later step already understands.
3. **No combined district + year ask.** It would break D-056 (district, then year, as separate steps, pinned by `tests/test_new_chat_and_scheme_switch_2026_10_21.py`), and an "All of Meghalaya, all years" chip would bring back the D-053 household-years figure.
4. **No regex** (D-046/D-047): every pattern uses `app/text_match.py` (`Matcher`, `Seq`, `Alt`, `W`, `Opt`, `ANY`).
5. **Hold-out respected:** no golden-set question is quoted in code or tests (`tests/nl2sql_eval/holdout.py`; the first test draft tripped it and was rewritten).

## 3. Changes by file

### 3.1 `app/pipeline/common/c07_mentions.py`: `_parse_year_key` (P1)

New inner helper `_fy_short(yy, end)`, used by both `FY` branches (`FY 24` / `FY'24` tokens, and the glued `fy24` token):

```python
def _fy_short(yy: int, end: int) -> int:
    j = _ws_run_end(text, end)
    if j < len(text) and text[j] in "-/":                 # "FY 23-24" / "FY23/24": a range
        j = _ws_run_end(text, j + 1)
        if <next 2 chars are digits, not followed by a digit> and int(...) == (yy + 1) % 100:
            return 2000 + yy                              # range: first year is the start year
    return 2000 + yy - 1                                  # single: FY24 = FY 2023-24
```

| Input | Before | After |
|---|---|---|
| FY24 / FY'24 / FY 24 / fy24 | 2024 | **2023** |
| FY25 | 2025 | **2024** |
| FY 23-24 / FY23-24 / FY23/24 | 2023 | 2023 (unchanged) |
| fy 24-25 / FY 24 - 25 | 2024 | 2024 (unchanged) |
| 2023-24 / 23-24 / FY 2023-24 / 2023 | 2023 | 2023 (unchanged) |

### 3.2 `app/pipeline/common/c09_resolve_entities.py`: `resolve_entities` (P2)

After the existing `year_key = _parse_year_key(raw_year)` fallback:

```python
if year_key is None and str(raw_year).strip().isdecimal() and len(str(raw_year).strip()) <= 2:
    year_key = _parse_year_key(question)
```

Narrow by design: it fires only when the extractor returned a bare 1-2 digit number. Any other unparseable mention keeps the existing "not a recognisable financial year" / out-of-range handling.

### 3.3 `app/pipeline/common/c06_years_tranches.py`: year gate (P3)

New matcher, not merged into `_ALL_YEARS_CUE`:

```python
_STATED_ALL_YEARS_CUE = Matcher(Alt(
    Seq("all", ANY, _C06_YEAR_W),            # "all sanction years", "all reporting years"
    "altogether", "lifetime",
    Seq("since", Opt("the"), W("start", "beginning", "launch")),
    Seq("from", "the", W("start", "beginning")),
    Seq(W("whole", "entire", "full"), W("period", "duration", "timeline")),
))
```

`_needs_year_clarification` now returns False when `_ALL_YEARS_CUE` **or** `_STATED_ALL_YEARS_CUE` **or** `_TIME_SERIES_CUE` matches.

### 3.4 `app/pipeline/common/c05_clarifications.py`: scope gate (P4, P5)

`_EXPLICIT_STATEWIDE` gains:
```python
"altogether", Seq(W("whole", "entire"), W("state", "meghalaya")),
Seq(W("for", "in", "across", "of", "at"), "the", "state"), Seq("state", "as", "a", "whole"),
```
`_HAS_BREAKDOWN` gains (plural place nouns only, so a singular "which district is Dalu in" is unaffected):
```python
Seq(W("which", "what"), W("districts", "blocks", "villages", "panchayats", "gps")),
Seq(W("list", "name"), Opt(W("the", "all")), W("districts", "blocks", "villages", "panchayats", "gps")),
```

Every use was checked. `_EXPLICIT_STATEWIDE` is read only by `_needs_scope_clarification`. `_HAS_BREAKDOWN` is also read by:
- region expansion (`c13:1105`): a "which districts of Garo Hills" list expands to the range's districts, which is correct;
- `c14:2187`: `asked_levels` already handles "which district" before it, so there is no change there.

### 3.5 `app/pipeline/common/c12_answer_numbers.py`
Docstring only: `"fy24" -> "FY 2023-24"`.

### 3.6 Size
5 app files, +49 / -4 lines. No schema, config, prompt, model or API change. No regex.

## 4. Tests

NEW `tests/test_stated_scope_2026_10_24.py`: 35 cases, all calling the real functions.

| Test | Covers |
|---|---|
| `test_financial_year_forms` (16) | `_parse_year_key`: single FY, ranges, 4-digit forms unchanged |
| `test_a_stated_all_years_period_is_not_asked` (6) | `_needs_year_clarification` on the new phrasings |
| `test_the_new_all_years_wordings_stay_out_of_the_verifier_cue` | `_STATED_ALL_YEARS_CUE` matches, `_ALL_YEARS_CUE` does not (verifier safety) |
| `test_a_stated_area_is_not_asked` (8) | `_needs_scope_clarification` on statewide / list phrasings |
| `test_a_question_that_states_nothing_is_still_asked` (3) | D-053 / D-056 unchanged |
| `test_an_extracted_bare_fy_number_is_read_from_the_question` | `resolve_entities` with the extractor stubbed to `"24"` -> `year_key 2023` |

## 5. Results

| Check | Before | After |
|---|---|---|
| pytest (documented command) | 3,663 passed | **3,698 passed, 0 failed**, 3 skipped |
| Plain-script suites | 14/14 | 14/14 |
| Held-out NL->SQL set (`tests/nl2sql_eval`, 74) | 40/74, 0 wrong | **42/74**; MG-11, PM-13, CL-03 fixed; 1 wrong (PM-04, see below) |
| Live, "Total MGNREGA expenditure in East Khasi Hills in FY24 / FY 24 / FY 23-24" | FY24 -> 11,050.42 lakh (FY 2024-25) | **all three -> 8,996.36 lakh (FY 2023-24)** |
| Live, "… in East Khasi Hills altogether" | asked "which year?" | 41,492.84 lakh, all financial years |
| Live context suite (`tests/live_context_validation.py`) | 103/107 | 103/107 (same 4 known failures, KI-405..407) |

**PM-04 (held-out item) is not a regression from this change.** It now splits "counting every financial year" by year instead of giving one total. It did so 4/4 on the new code **and 2/2 on the original code** (changes stashed, then restored). No new phrase matches it. The c11 "one combined figure" guard did not reject the split. Logged as KI-411.

## 6. Risk and rollback

| Risk | Mitigation |
|---|---|
| A new "all years" phrase next to an explicit year ("altogether in FY 2024-25") | The year parser runs first, so the explicit year wins; the new cue is kept out of the verifier's cue (test pins it) |
| `"for the state"` / `"of the state"` read as statewide | Only skips the "which area?" ask; never adds a filter |
| "which districts" reading as a list | Plural nouns only; a singular "which district" is unchanged |
| FY<yy> convention change | Matches every SME catalogue; ranges unchanged; pinned by 16 cases |

**Rollback:** revert the 5 app files and delete the test file. No data, schema or `.env` was touched.

## 7. Documentation updated

- DECISIONS: D-068.
- KNOWN_ISSUES: KI-409 and KI-410 fixed, KI-411 opened.
- AI_PIPELINE §2.4: year gate notes.
- TESTING: results row.
- CURRENT_STATE, HANDOFF, `new_docs/RAG_Plan_Status_Report_2026-10-24.md` (A2 and C1 now partly solved).

## 8. Open

- The other 31 held-out items ask by rule (no year or place stated under D-053/D-056/D-064/D-065). Updating the set's expectations is a user decision.
- KI-411 (PM-04 split not caught by the c11 guard).
- Not committed.
