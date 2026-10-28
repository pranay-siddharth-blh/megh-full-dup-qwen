# Table Rendering Audit — 2026-10-28

**Trigger:** user screenshot, "How have MGNREGA person-days changed over the last three years in Meghalaya?" —
the table under the answer was a 3×3 grid with only the diagonal filled, dashes everywhere else, raw numbers
next to formatted ones, and a grand total nobody asked for.
**Scope:** how a DATA answer's rows become the chart and table in the chat UI (frontend only; the rows come
from the backend unchanged). **No code changed.** Labels: VERIFIED = read in code.

## 1. Which components build the table

| Step | File | What it does |
|---|---|---|
| 1. Decide the view | `frontend/src/chat/analytics.js` `buildAnalyticsCore` | Splits columns into numbers and labels, then picks a kind: `compare`, `twoDim`, `multi`, `kpi`, `record`, `table`… |
| 2. Pick the table | `frontend/src/chat/components/Messages.jsx:62-181` | `twoDim` → `PivotTable` (or `DynTable` when there are extra measures); most other kinds → `DynTable`; one row → `RecordCard` |
| 3. Draw the table | `frontend/src/chat/components/Charts.jsx` | `PivotGrid`/`PivotTable` (:807-861), `DynTable` (:781), `BigTable` (expanded view, :733), `RecordCard` (:863) |
| 4. Export | `frontend/src/chat/components/ChatExport.jsx` | Writes the raw rows to Excel |

## 2. What went wrong in the screenshot

The SQL returned three columns per row: `year_key` (2023), `financial_year` ("2023-2024"), `person_days`.

**F1. The same year in two columns is read as two dimensions — the cause of the dashes. VERIFIED.**
`analytics.js:299-320`: two label columns → `twoDim`. Both are periods; `year_key` became the rows and
`financial_year` the columns. Each year matches only its own FY, so only the diagonal has a value and the
other 6 cells are "—". The chart has the same fault: three bars in three legend colours, one per FY, instead
of one series. The backend already knows these two columns are ONE period (`c12_answer_shapes.py:176-179`:
"financial_year and year_key side by side are ONE period"), but the frontend has no such rule.

**F2. Grid cells are not formatted, totals are. VERIFIED.** `Charts.jsx:831` prints a cell as `String(value)`
→ "27264054"; the totals use `toLocaleString('en-IN')` → "2,72,64,054". Same table, two formats.

**F3. A Total row, a Total column and a grand total are always added. VERIFIED.** `Charts.jsx:812-838`.
- Not asked in the question ("how have person-days changed" — the grand total 6,53,18,944 is extra).
- With F1, the Total column just repeats each row's single value.
- They are added for every measure, including ones that must not be added up: percentages, averages, ratios,
  and stock figures such as MGNREGA job cards (a running total — adding years is wrong, see
  `schema_context.py:280-281`).

**F4. Column headers are database names.** `colLabel` (`Charts.jsx:720`) only replaces "_" with a space:
"YEAR KEY", "lgd district", "amount raw". The chart titles use the better `humanCol` (`analytics.js:48`), so
the table and the chart name the same column differently.

**F5. Row count says "3 rows"** — it counts pivot rows, which here are the 3 diagonal years; fine, but with
F1 fixed the right view has no pivot at all.

## 3. The same faults elsewhere (same code, other questions)

- **`DynTable` / `BigTable` never format numbers** (`Charts.jsx:771, 793`): raw 27264054, long decimals
  (119.73925), money without ₹ or unit, no Indian grouping. Every answer with a plain table shows this.
- **Technical columns are shown**: `year_key`, `village_code`, `lgd_*` prefixes, `entity_key`. They are needed
  by the query, not by the reader.
- **Missing values look like data**: `null` → "—", but a `"None"` string is printed as "None" in `DynTable`
  (only `RecordCard` filters it, `Charts.jsx:864`).
- **Any two label columns become a pivot**, even when one is just a longer name of the other (district name +
  district code, scheme name + scheme code) — the same diagonal grid as F1.
- **Numbers are left-aligned like text** — hard to compare by eye (no right-align class for numeric cells).
- **The Excel export takes raw rows** — it does not get F1-F4's problems, but also none of the fixes; it is
  consistent with the database, not with the screen.

## 4. How to make it better (not implemented; ordered by impact ÷ risk)

1. **Merge "twin" columns before choosing the view** (`analytics.js`). Two period columns whose values pair
   one-to-one (each year_key has exactly one financial_year) are one dimension: keep the readable one
   (`financial_year`), hide the other. The same one-to-one test catches name + code twins. For the
   screenshot this gives a 3-row table (FY, person-days) and a single line chart — no dashes.
2. **One number formatter for every table cell** (`Charts.jsx`): Indian grouping for counts, 2 decimals for
   lakh / crore columns with the unit in the header, `%` for `_pct` columns, right-aligned. Use it in
   `PivotGrid`, `DynTable`, `BigTable` and `RecordCard`.
3. **Totals only when they mean something**: add row / column totals only for additive measures (not `%`,
   `avg`, `rate`, `ratio`, `per`, or stock measures like job cards). The backend has a word list for this
   (`_c12s_additive`, `c12_answer_shapes.py:39-66`: share, per, median, …); stock measures such as job cards
   are NOT in it yet (UNKNOWN — NEEDS VERIFICATION) and would need adding. Add totals only when both
   dimensions have 2+ values; no grand total for a single series.
4. **Readable headers**: use `humanCol` in tables too, so "total_exp_lakh" reads "Total expenditure (₹ lakh)".
5. **Hide technical columns** (`*_key`, `*_code`, `*_id`) in the on-screen table when a readable twin exists;
   keep them in the Excel export.
6. **A trend question gets a trend table**: for one period dimension + one measure, show period | value |
   change from previous period — this answers "how have … changed" directly.

Each change needs a node test that runs the real `analytics.js` on the real rows (the pattern of
`tests/test_cross_compare_card_2026_10_22.py`), `npm run build`, and a check of the screenshot question live.
