# Golden Test Sets, the "RAG Metadata" Idea and Alternatives: Review (2026-10-24)

Three questions answered:

1. Are the golden test sets a good approach for this project?
2. Can RAG metadata be used to generate answers?
3. What are the alternatives?

No code was changed for this review.

---

## 1. Verdict on the golden test sets: good, keep them, but they have gaps

### What is good (keep)

| Strength | Why it matters |
|---|---|
| **Scored on the result, not the SQL text** (`nl2sql_eval/compare.py`) | Two different SQL queries can both be right. The set checks the number the officer sees. Public text-to-SQL benchmarks such as Spider and BIRD use the same method. |
| **The gold SQL runs fresh on the DB every time** | A data reload never makes the expected answers stale |
| **Hold-out guard** (`holdout.py`) | Nobody can "fix" a failure by pasting the question into a prompt, so the score stays honest |
| **Every scheme, with easy / medium / hard mixed** | One scheme cannot hide another's failures |
| **The knowledge set includes "not covered" questions** (24 of 188) | Measures honesty, not just correctness. This is how the made-up-answer rate fell to 13.9%. |
| **Real gateway, real DB, real graph** | Measures what officers actually get, not a mock |

### What is weak (fix)

| Gap | Effect | Fix |
|---|---|---|
| **One wording per question** | Cannot see the main problem in the RAG plan (A2): paraphrases giving different answers | Add a paraphrase / consistency set |
| **Small: 74 data questions** | One question = 1.35%; a single flip moves the score visibly | Grow it with questions generated from the DB (see section 3, option C) |
| **Not run since 2026-10-18** | Today's accuracy is unknown after D-060..066 | Re-run now, then nightly |
| **Run by hand, not automatic** | A regression can ship unseen | Nightly run with a fail-on-regression flag (the runner already supports it) |
| **Knowledge set never checked by an expert** | Its 188 expected answers are a model-written draft | One SME review pass |
| **Knowledge answers judged by a model** | Scores move about ±2 points between runs | Compare on repeated runs; the expert-checked subset is the trustworthy one |
| **No follow-up chains or routing score in the golden sets** | Context and data-vs-knowledge routing are only in pass/fail suites | Add a "right route" column and a few chains to the new set |

**Conclusion:** the approach is the right one, and the scoring is industry standard. The problems are **coverage and use** (small, one wording, not automated), not the method. Do not replace it. Extend it.

---

## 2. The idea "use RAG metadata to generate answers": partly right

It depends on what the metadata is used for.

### Where it is WRONG: producing the numbers

The metadata (metric definitions, aliases, formulas, sample values, place names) **describes** the data; it **does not hold** the figures. If the answer's number came from metadata text:

- it would be a **made-up or stale number** (sample values and examples are not today's totals);
- it would break the project's core rule: *the composer must never state a number that is not in the SQL result* (CLAUDE.md §5);
- there is no way to check it against the database.

**So no: numbers must always come from SQL on `megh_db`.**

### Where it is RIGHT: four good uses

| Use | How it helps | RAG plan item |
|---|---|---|
| **A. Understanding the question** | "HH employed", "households", "beneficiaries" → the right metric for that scheme, by meaning, not word rules | A1, B1, B2 |
| **B. Building the query** | The metric's catalogue entry (view, column, unit, year column) lets **code** build the SQL for common question shapes, with no free-form model SQL | E7 (metric catalogue + SQL compiler) |
| **C. Explaining the answer** | Add the definition and unit next to the figure: "59,114 households (a household counted once per year it worked)" | E9 |
| **D. Generating TEST questions** | Metric aliases × places × years × shapes → thousands of test questions, each with a gold SQL built from the catalogue | Golden set growth |

**Use D fits the golden-set question best.** It turns the metadata into a large, always-fresh test set: for example 35 metrics × 12 districts × 4 years × 5 wordings, all with known answers computed from the DB.

**Rule of thumb:** metadata **decides what to ask the database and how to describe the answer**; the database **supplies the number**.

---

## 3. Alternatives

### For testing

| Option | What it is | Verdict |
|---|---|---|
| **A. Keep the golden sets (current)** | Fixed questions with gold answers, scored | ✅ Keep: the base |
| **B. Paraphrase / consistency set** | Same question in 3-5 wordings; all must agree | ✅ Add: the only way to measure A2 |
| **C. Questions generated from the DB / metadata** | Templates × catalogue × places × years, gold SQL from the catalogue (like the existing place-hierarchy sweep, 30,280 cases) | ✅ Add: large and never stale |
| **D. Invariant ("metamorphic") checks** | Rules that must always hold: district totals add up to the state total; top 5 ⊂ top 10; changing the year changes the SQL year; "FY24" = "2023-24" | ✅ Add: catches errors without needing gold answers |
| **E. Production feedback loop** | Officers' 👍/👎 and real failed questions, reviewed weekly; each confirmed failure becomes a test | ✅ Add later: finds what no one thought to test |
| **F. Nightly automatic run** | All sets run every night; a drop blocks the merge | ✅ Add: makes the sets actually protect the project |
| **G. Model-as-judge only** | A model grades every answer, no gold | ❌ Not for numbers (too noisy); fine for knowledge prose |
| **H. Manual QA sheets only** | People test by hand (the `raw_uc` sheets) | ⚠️ Keep as acceptance tests, not as the regression net |

### For answering data questions (the bigger architectural choice)

| Approach | How it works | Accuracy | Effort | Verdict |
|---|---|---|---|---|
| **1. Current: model writes SQL + guards** | 30B writes free SQL; verifier, repair and composer checks | Good but varies with wording | Already built | Keep as the **fallback** for unusual questions |
| **2. Metric catalogue + SQL compiler ("semantic layer")** | Question → structured plan → code builds SQL from the catalogue | **Exact and repeatable** for common shapes (likely 70-80% of questions) | Medium | ✅ **Recommended** (RAG plan E1 + E7). This is where the metadata is most useful. |
| **3. Pre-computed KPI tables** | The ingestion team builds summary tables (scheme × place × year × metric); the app reads them | Exact, very fast | Needs the ingestion team | ⚠️ Good complement for the top KPIs; depends on another team |
| **4. "Facts as text" in RAG** | Pre-written number sentences embedded and retrieved | Goes stale; cannot combine filters; wrong numbers when retrieval misses | Low | ❌ Not recommended: this is the risky version of "metadata generates answers" |
| **5. External semantic-layer product** (Cube, dbt metrics, etc.) | A third-party metrics server between the app and the DB | Exact | High (new infrastructure, licensing, ops) | ❌ Not now; approach 2 gives the same benefit inside the app |

**Recommendation:** approach 2 for common questions, approach 1 as the fallback, the metadata feeding both understanding and test generation.

---

## 4. Recommended order (each step measured with the golden sets)

1. Re-run the data golden set now: today's baseline.
2. Add the paraphrase / consistency set (option B), with a "right route" column.
3. Add invariant checks (option D): cheap, no gold answers needed.
4. Build our metadata collection and catalogue (`megh_metric_catalog_v1`). Use it first to **generate tests** (option C), then to **understand questions** (RAG plan B1-B3).
5. Metric catalogue + SQL compiler (approach 2), switched on shape by shape, each shape kept only if the golden sets hold or improve.
6. Nightly automatic run (option F), and later the officer feedback loop (option E).
7. One expert review of the knowledge set.

## 5. One-line answers

- **Golden test sets: good or bad?** Good, and correctly designed. Too small, one wording only, and not run automatically. Extend them; don't replace them.
- **RAG metadata to generate answers?** Not for the numbers (they must come from the DB). Yes for understanding the question, building the SQL, explaining the answer, and generating test questions.
- **Better alternative?** A metric catalogue + SQL compiler (semantic layer), built from that metadata, with today's model-written SQL as the fallback.
