# Metric Catalogue: What Was Implemented and What We Got (2026-10-26)

Decision **D-071**. RAG plan item **B1** (metric / synonym detection), towards **A2** (same meaning, same answer).
Code is uncommitted, on branch `update/2026-10-24`.

## 1. The problem

The model wrote new SQL for every wording of a question. "Spend", "outlay" and "money spent" could read different
figures, and some wordings were misread or not answered at all.

The ingestion team already maintains **`semantic.metric_definitions`**. It holds 62 named measures, each with:
- its SQL expression;
- the view it is read from;
- its unit;
- the words officers use for it.

39 of them belong to our six schemes. The chatbot never used them to build queries.

## 2. The solution

When a question names **exactly one** catalogue measure and asks **nothing else**, the query is built from the catalogue
instead of being written by the model. The same measure, place and year then always read the same figure.

| Part | What it does | Status |
|---|---|---|
| **1. Load and match (shadow)** | Loads the 39 measures at startup. Finds the one measure a question names, and logs what it would do. | Done, live |
| **2. Single totals** | One figure for the state, a district, a block or a village, for one year | Done, live (28 measures) |
| **3. Breakdowns, rankings, comparisons** | Per district, block or year; top or bottom N districts or blocks; named places or years side by side | Done, live (25 / 28 / 23 measures) |

### How a question is handled

1. **Match.** The measure's words are looked up in the question. Plurals don't matter, and the "was" / "were" that the
   rephraser adds is skipped. The longest phrase wins.
   - Two measures named → model path.
   - A phrase that two measures share → model path.
2. **Nothing else asked.** Every other word must be the scheme name, a resolved place, a year, or plain question grammar
   ("what", "how many", "total" …).
   - "**Wage** expenditure" has the extra word "wage", so it goes to the model path as before.
3. **Filters.** Only district, block, village and year filters are allowed. A constituency, region, status, gender,
   programme and so on → model path.
4. **Shape.** The question's shape must be one of: total; breakdown by district, block or year; ranking with one
   direction and a stated count ("which district" = 1); compare. Anything else → model path.
5. **Years.** Four measures are per-year tallies, which the catalogue's own notes say must never be added across years:
   - job cards;
   - households employed;
   - persons employed;
   - 100-day households.

   These are only built for exactly one year, or per year. A question with no year still gets the usual "which year?"
   question.
6. **The evidence gate.** The catalogue query answers **only** for a (measure, shape) pair listed in
   `data/metric_catalog_verified.yaml`, and a pair is listed only after a live check showed the same figure as today's
   answer. Everything else is logged as "shadow" and answered exactly as before.

### Safety

- **Priority.** It is the **last** fixed query, so every existing fixed query keeps priority (PMAY-G facts, MGNREGA job
  cards, CM Elevate sectors, and so on).
- **Parameters.** Every value is a bound parameter. The query runs on the **read-only** database login (`megh_readonly`).
- **Checks.** Answers still go through the composer and all its number checks. `authorize` still checks the SQL.
- **Focus Plus blocks.** There is never a block-level catalogue query for Focus Plus. Its blocks are on `block_name_raw`,
  because `lgd_block` is empty on 15% of its rows (an existing rule).
- **Switch.** `METRIC_CATALOG_MODE` takes `off`, `shadow` or `on` (default `on`). Setting `off` restores the exact old
  behaviour, with no other change.

## 3. What we got (live, 2026-10-26)

### Part 1: shadow run

312 questions were asked: 8 per measure for 39 measures, at the state, a district, a block, a breakdown, a ranking and
a comparison. The model answered them as it does today.

- **207** questions built a catalogue query.
- The rest were already handled by existing fixed queries, were asked a clarification, or the catalogue declined them.
- **105 of 111** (measure, shape) pairs gave the **same figure** as today on every question.

The other 6 pairs are explained in section 5.

### Parts 2 and 3: turned on

| Shape | Measures verified |
|---|---|
| Total | 28 |
| Breakdown | 25 |
| Ranking | 28 |
| Compare | 23 |

The same 312 questions were re-run with the catalogue answering:

- the catalogue answered **183**;
- **183 / 183** returned the catalogue figure;
- every total stated that figure in its answer;
- the other 129 were answered as before.

### Did anything else break?

| Check | Before | After |
|---|---|---|
| pytest (documented command) | 3,805 passed / 0 failed | **3,829 / 0** (+24 new tests) |
| 14 plain-script suites | 14 / 14 | **14 / 14** |
| Golden set (74 held-out questions) | 42 / 74 | **42 / 74, 0 regressions** (2 VPN timeouts, re-run correct) |
| Live context suite | 103 / 107 | **103 / 107** (same 4 older failures) |
| Known answers from the data team | 13 / 14 | **13 / 14** (the 14th is the CM Elevate "which dataset?" question, asked by rule D-064) |

## 4. Examples

| Question | Before | After |
|---|---|---|
| "What is the spend under MGNREGA in Ri Bhoi district in FY 2023-24?" | 4,295.67 lakh | 4,295.67 lakh: same figure, now from the catalogue query every time |
| "What is the expenditure under MGNREGA in Ri Bhoi …?" (another wording) | 4,295.67 lakh | 4,295.67 lakh, same query as above |
| "What is the houses sanctioned under PMAY-G in Ri Bhoi district in FY 2022-23?" | "I understood the question but couldn't build a working query …" | **559 houses were sanctioned** |
| "Compare beneficiaries **paid** under CM Elevate Legacy in Ri Bhoi and West Garo Hills in FY 2024-25" | 214 vs 414: these are *sanctioned* beneficiaries, the wrong measure | **211 vs 396 paid**, the measure that was asked |
| "Wage expenditure in Ri Bhoi in FY 2023-24" | model path | model path, unchanged ("wage" is not part of the measure) |

The catalogue query is visible in the answer's SQL, for example:

```
/* metric:mgnrega_total_expenditure total */ SELECT ROUND((SUM(total_exp))::numeric, 2) AS total_expenditure_lakh
FROM curated.v_expenditure WHERE UPPER(lgd_district) = UPPER($1) AND year_key = $2
```

## 5. What was found and left on the old path

These cases are not answered by the catalogue. They are logged as known issues.

| Found | Why it stays on the old path | Issue |
|---|---|---|
| PMAY-G "**sanctions**" is read by the model as the sanctioned *amount*; the catalogue says the house count | Ambiguous word; excluded by wording (`except_words`) | KI-424 |
| PMAY-G "**coverage**" is read as the houses / amount summary; the catalogue says villages covered | Same | KI-424 |
| Focus Legacy "**remittances**" and "**payments made**" (ranking) are read as the amount disbursed; the catalogue says payment count | Same | KI-424 |
| CM Elevate Legacy applicants sanctioned, statewide: 2,288 (model adds "amount not null") vs 2,291 (catalogue) | 3 records differ; not verified | KI-425 |
| Focus Plus payments by district: the model groups by `district_name_raw`, the catalogue by `lgd_district`; different totals | Which column is right is a question for the owners | KI-426 |
| Focus Plus women beneficiaries | FY 2022-23 holds no gender data, so "0 = 0" proves nothing | not verified |
| MGNREGA villages covered | Its view (`bridge_geography_source`) has no place or year columns | never built |

**Not used from the catalogue:**
- **The free-text `filters_required` notes.** What they demand was reviewed by hand into the verified file.
- **PMAY "Filter WHERE NOT is_placeholder".** It is not applied: today's answers count every house (D-060), and the
  figures matched.
- **CMSS, Home Stay Legacy and NRLM.** These are not schemes in the chatbot.

## 6. Files

**New:**
- `app/metric_catalog.py`: load, match, build.
- `app/pipeline/common/c16_metric_catalog.py`: the decision.
- `data/metric_catalog_verified.yaml`: the evidence gate.
- `tests/test_metric_catalog_2026_10_26.py`: 24 tests.
- `tests/metric_catalog_eval.py`: the live measurement.

**Changed (small):**
- `app/config.py` (`METRIC_CATALOG_MODE`);
- `app/main.py` (load at startup);
- `app/pipeline/__init__.py` (file list);
- `c13_compose_and_data_stages.py`: one entry added to the end of the fixed-query chain, and catalogue queries run on the
  read-only pool.

**Docs updated:**
- DECISIONS (D-071), AI_PIPELINE §2.4b, ARCHITECTURE, DATA_MODEL, TESTING, KNOWN_ISSUES (KI-424..426), CURRENT_STATE,
  HANDOFF, CLAUDE.md;
- the RAG plan status report (B1 → partly; now 2 solved, 11 partly, 1 already working, 15 not started).

## 7. To do next

1. **Restart :8401 from the venv.** The running server (PID 32108, system Python, not started by this session) predates
   this change, so the chat UI does not use the catalogue yet.
2. **Ask the scheme owners about KI-424.** What do "sanctions", "coverage" and "remittances" mean? Then either ask the
   officer or fix the wording.
3. **Ask the ingestion team about KI-425 and KI-426.**
4. **Add a measure or shape later.** Run `tests/metric_catalog_eval.py --metrics <keys>` (VPN), then add the pair to the
   verified file with its evidence.
5. **Not done here:** matching by meaning (vector search over the synonyms). Right now a wording must contain the
   catalogue's own words.
