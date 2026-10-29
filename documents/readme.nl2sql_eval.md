# NL→SQL accuracy set: measuring how often a data question gets the right answer

This document explains the held-out accuracy set in `meghalaya/tests/nl2sql_eval/`: what it measures,
how to run it on every change, how to read the result, and the rules that keep the number honest.
File references are relative to the `meghalaya/` folder.

---

## 1. What it is

74 data questions (12–13 per scheme, all six schemes), each with a **gold SQL** query that gives the
right answer under the project's documented rules. Every run sends each question through the **real
chat pipeline** (the LangGraph graph, the real model gateway, the read-only DB pool) and checks the
pipeline's result against the gold query's result, which is run fresh on the same read-only pool.

| | |
|---|---|
| Questions | `tests/nl2sql_eval/questions.yaml` — 24 easy, 32 medium, 18 hard |
| Runner | `tests/nl2sql_eval/run_eval.py` |
| Result comparison | `tests/nl2sql_eval/compare.py` |
| Hold-out guard | `tests/nl2sql_eval/holdout.py` |
| Run one SQL read-only | `tests/nl2sql_eval/sql_check.py` |
| Saved runs | `tests/nl2sql_eval/results/<date>_<time>_<label>.json` |
| Offline checks (in the normal test suite) | `tests/test_nl2sql_eval_set.py`, `tests/test_nl2sql_eval_compare.py` |

**The questions are held out.** None of them comes from the "fix loop": the few-shot banks and rule
files in `data/`, the scheme test sheets, `reference_documents/` reports, `tests/` and strings in
`app/`. That is what makes the score a measure of accuracy on questions the pipeline was never tuned on.

---

## 2. Running it

From `meghalaya/`, with the VPN up:

```bash
python tests/nl2sql_eval/run_eval.py --label <what-changed>                  # full run, ~5 min
python tests/nl2sql_eval/run_eval.py --label <what-changed> --fail-on-regression
python tests/nl2sql_eval/run_eval.py --scheme "Focus Legacy"                  # one scheme
python tests/nl2sql_eval/run_eval.py --ids MG-06,CE-10                        # a few items
python tests/nl2sql_eval/run_eval.py --check-gold                            # gold SQL + hold-out only, no models
```

- **Read-only database.** The runner uses the read-only pool (`READONLY_DATABASE_URL`, the
  `megh_readonly` role) for both the pipeline's SQL and the gold SQL, with every statement inside a
  `READ ONLY` transaction and passed through the SQLGlot guard (curated / semantic only). Until
  `megh_readonly` is configured in `.env`, add `--allow-superuser`: the run still uses READ ONLY
  transactions and the guard, and the results file records it (`superuser_allowed: true`).
- **No caches.** The runner calls the pipeline directly, so the response and semantic caches (which
  live in the HTTP router) are never used. Each question gets a fresh session.
- **No writes.** LangGraph checkpoints stay in memory; nothing is written to `app.*`.

### On every change

Run it **before and after** any change to the pipeline, prompts, few-shots, rule files, schema
context or model assignment:

1. Make the change.
2. `python tests/nl2sql_eval/run_eval.py --label <short-name> --fail-on-regression`
3. Read the **regressions** line first (items that were correct in the previous run and are not now),
   then the accuracy.
4. Keep the change only when accuracy holds or improves **and** every regression is explained (see
   section 4 on noise).

The normal test suite (`pytest tests`) also runs `tests/test_nl2sql_eval_set.py` offline, so a leaked
question or a gold query that breaks the read-only guard fails CI even when nobody runs the live eval.

---

## 3. How an answer is scored

| Outcome | Meaning |
|---|---|
| `correct` | The pipeline's rows hold the gold answer, or (single-number gold only) the answer text states that number |
| `wrong` | It answered with data, but not the gold answer |
| `clarification` | It stopped to ask a question. The items are written to be unambiguous, so this counts against accuracy |
| `no_sql` | It answered without running SQL (knowledge / out-of-scope route, or "couldn't build a working query") |
| `error` | An exception: gateway, database or timeout |
| `gold_error` | The gold query itself failed: a broken item, left out of the score |

**Accuracy = correct / (items − gold_error).**

The rows match when (`compare.py`):

- the row counts are equal;
- every gold column matches a **different** pipeline column holding the same values. Column names
  never matter. Numbers may differ by rounding (0.5 %, or ±0.05) and by **one unit scale** (rupees ↔
  lakh ↔ crore ↔ thousand, fraction ↔ percent). Text is compared ignoring case and spacing;
- the rows, projected onto those columns, are the same set (the same sequence for `ordered: true`
  items, which are the top-N rankings only).

Extra pipeline columns are fine. A different grain, such as one total against per-district rows, is wrong.

**Fallback for single-number golds.** The item is also correct when the answer text states the number,
for example when the SQL returned a per-year breakdown and the answer gives the total the user asked
for. Indian (`11,61,895`) and western (`1,161,895`) grouping both count. Counts must match exactly. A
year, or a whole number below 10, never counts.

---

## 4. Reading the number: noise

The pipeline runs at temperature 0 but is not fully deterministic. On identical code, two full runs
differed by **2 of 74 items** (MG-08, PM-04), about **±3 points**. So:

- a change of 1–2 items on the headline number is noise, not a result;
- look at **which** items moved. A regression on an item that has been stable across several runs is
  real; one that flips back and forth is not;
- for a decision that matters, run twice and compare both runs.

---

## 5. Baseline (2026-10-15)

Run `2026-10-15_1850_baseline-final` (models: classifier qwen4-deploy, rewrite qwen35-9b, SQL and
verifier qwen-model, composer qwen35-9b; read-only pool with `--allow-superuser`).

**Accuracy 78.4 % (58 / 74).** Two earlier runs on the same code scored 78.4 % and 75.7 %.

| Scheme | Accuracy | | Difficulty | Accuracy |
|---|---|---|---|---|
| CM Elevate Legacy | 91.7 % | | easy | 91.7 % |
| PMAY-G | 84.6 % | | medium | 71.9 % |
| Focus Plus | 83.3 % | | hard | 72.2 % |
| MGNREGA | 76.9 % | | | |
| CM Elevate | 66.7 % | | | |
| Focus Legacy | 66.7 % | | | |

All 16 misses were checked by hand. All are pipeline failures, not test-set flaws (one ambiguous
question, FL-12, was reworded after the first run, and the single-number fallback was added after
PM-04's correct total was marked wrong). They are the same in all three runs.

| Items | What goes wrong |
|---|---|
| MG-06, MG-07, PM-10, FP-06, CE-06, CE-10 | **The question names the count** ("which **three** blocks", "the **5** villages", "Which **3** blocks") **but the pipeline still pauses** to ask "how many results — top 3, top 5…?" (`ranking-count-not-specified`). 8 of the 16 misses come from this one detector |
| MG-09, CE-08 | The same pause fires on plain "**how many** distinct villages…" questions, which are counts, not rankings |
| FL-03 | "payments into Meghalaya Rural Bank accounts" is refused as if it asked for account numbers (`column-not-held`) |
| FL-12 | Sent to the out-of-scope reply ("I can only answer…") instead of the data path |
| FP-11 | Grouped Focus Plus blocks on `lgd_block`; `schema_context.py` says blocks must use `block_name_raw` (Selsella: 4,916 vs 7,691 beneficiaries) |
| FL-10 | Filtered `programme_variant = 'Focus (Addnl)'` as the docs say; the data stores `'FOCUS_ADDNL'`, so 0 % instead of 9.94 %. **The docs are wrong** |
| FL-04 | Added an invented condition (the group paid in all 4 years): 0 villages instead of 173 |
| CE-12 | Grouped by scheme *and* district, so "more in West Garo Hills than in Ri Bhoi" can never compare |
| CL-05 | Did not keep only records that actually received a loan: 1,626 instead of 367 |
| PM-06 | Gave up: "couldn't build a working query" |
| MG-08 *(flaky, 1 of 3 runs)* | Dropped the year range and returned only FY 2025-26 |

**Data and documentation problems found while writing the gold SQL** (worth fixing at the source):

- Focus Legacy `programme_variant` is stored as `'FOCUS'` / `'FOCUS_ADDNL'`; the docs say `'Focus (Addnl)'`.
  Group type codes are `FOCUS_PG` / `LAMP` / `EXISTING_COOPERATIVE`; `schema_context.py` lists the
  `pg_id` prefixes (`PG-FOCUS`, `PG-LAMP`, `PG-EXISTING`) instead.
- Rule files that contradict each other: Focus Plus "beneficiaries" (data YAML: count payments;
  `schema_context.py` rule 6: count distinct people) and Focus Plus `has_geo_conflict` rows (data
  YAML: exclude; rule 9: never filter). MGNREGA money (data YAML defaults to crore; rule 4 says lakh).
  CM Elevate "rejected" (data YAML: `data_verified` Invalid/Wrong; prompt vocabulary:
  `scheme_specific->>'file_status' = 'Rejected'`).
- Stale CM Elevate figures in the rule files and prompts: 8,867 rows live vs 8,543 / 8,436 quoted;
  908 on hold vs ~1,199; 191 invalid vs ~67.
- MGNREGA FY 2024-25 looks anomalous: statewide person-days fall from 27.3 M to 14.7 M and recover to
  23.4 M the next year, with cost per person-day roughly doubling. Real, or a source-feed problem.

---

## 6. Rules that keep the score honest

1. **Never copy an eval question, or a paraphrase, into the fix loop**: few-shots, rule files, prompts,
   tests, sheets or app strings. `holdout.py` refuses to score while any question is leaked, and
   `tests/test_nl2sql_eval_set.py` fails CI. A near-duplicate is "leaked" when it scores ≥ 88 with
   `rapidfuzz.fuzz.ratio` against any sentence of the fix-loop corpus.
2. **Never fix a failure by special-casing its wording.** Fix the general cause (a rule, a detector, a
   prompt section) and check the gain shows on the other items too.
3. **Changing a gold answer is a decision, not a fix.** Change one only when the gold breaks the
   project's own documented rules, or the question honestly has two readings (then reword the
   question). Record why in the item's `note`.
4. **A gold query returns only what the question asks for**, plus the grouping keys a correct answer
   must show. Extra helper columns in the gold would fail correct answers that leave them out.
5. **Adding items:** write the question, write the gold SQL from `app/schema_context.py` and
   `data/<scheme>/*.yaml`, check it with `sql_check.py`, check the question with
   `python -m tests.nl2sql_eval.holdout`, then run `--check-gold`. Keep at least 10 items per scheme.

---

## 7. Known limits

- The gold answers follow the project's documented rules. Where two rule files disagree (for example
  Focus Plus "beneficiaries": the data YAML says count payments, `schema_context.py` says count
  distinct people), the items avoid the conflict or word the question so only one reading fits. The
  conflicts are listed in section 5.
- Data-only. Knowledge (RAG) answers have their own evaluation in `tests/rag_eval/`.
- One-turn questions only. Follow-up resolution is not measured here.
- The answer **text** is checked only for single-number golds; wording, units and caveats in the
  answer are not scored.
