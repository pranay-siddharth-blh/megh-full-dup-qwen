# Table & Chart Representation — Code Change Plan — 2026-10-28

**Purpose:** the exact code changes needed to make tables (and their charts' axes) readable for any data
answer, without changing what the backend returns. Follows `new_docs/Table_Rendering_Audit_Report_2026-10-28.md`.
**Status: PLANNED — nothing implemented.** Frontend only; `app/` and the SQL are not touched.

## 1. Files that change

| File | Change size | Why |
|---|---|---|
| `frontend/src/chat/columns.js` (**new**) | ~150 lines | One place that decides each column's meaning (role, name, unit, additive, twins) |
| `frontend/src/chat/analytics.js` | medium | Use the profile: merge twins before choosing the view; pass names/units to charts |
| `frontend/src/chat/components/Charts.jsx` | medium | Formatted cells, readable headers, totals rule, hidden technical columns, axis titles, unit-aware ticks/tooltips |
| `frontend/src/chat/chartTheme.js` | small | Unit-aware compact formatter beside the current `fmtCompact` |
| `frontend/src/chat/components/Messages.jsx` | small | Pass the profile to the tables; trend table choice |
| `frontend/src/styles/chat.css` | small | Right-aligned numeric cells, hidden-column note |
| `tests/test_table_view_2026_10_28.py` (**new**) | ~15 tests | Runs the real JS in node on real row shapes |
| Not changed | — | backend, SQL, answer text, `ChatExport.jsx` (Excel keeps every raw column) |

## 2. Change by change

### C1. New `columns.js` — the column profile
`profileColumns(rows) -> { cols: [{ key, role, label, unit, additive, hidden, twinOf }] }`

- **role**: `period` (year/FY/month/date words or period-shaped values — reuse `isPeriodLabel` and
  `PERIOD_WORDS` from analytics.js/text.js), `measure` (every value a plain number and not a label word —
  reuse `isNumeric` / `isLabelCol`), `technical` (`*_key`, `*_code`, `*_id`, `lgd_code`), else `dimension`.
- **label**: move `humanCol` + `COL_WORDS` (analytics.js:45-49) here and extend it: drop `lgd_` / `_raw` /
  `_name` noise, `year_key` → "Year", `financial_year(_short)` → "Financial year", `total_exp` → "Total
  expenditure". analytics.js re-exports it so current callers keep working.
- **unit** from the column-name suffix — the same rules as the backend's `_unit_suffix`: `_lakh`/`_lakhs` →
  ₹ lakh, `_cr`/`_crore` → ₹ crore, `_rupees`/`amount`/`_amt` → ₹, `_pct`/`percent`/`share`/`rate` → %,
  `ratio`/`per_` → ratio, else count.
- **additive**: false for %, ratio, avg/mean/median/per, and stock measures (`job_cards`, `cumulative`,
  `total_issued`) — mirror of `_c12s_additive` (`c12_answer_shapes.py:39-66`) plus the stock words.
- **twins**: two non-measure columns whose values map **one-to-one** across all rows (every `year_key` has one
  `financial_year` and back): keep the readable one (text over number, FY over key), mark the other
  `hidden`, `twinOf` = kept key. Covers year_key/financial_year, district/district code, scheme/scheme code.
  One-to-one is checked on the data, never guessed from names — a real district × year table is never merged.

### C2. `analytics.js` — choose the view after merging twins
- `buildAnalyticsCore` (:188): compute the profile first; build `numCols` / `lblCols` from the **visible**
  columns only. With the twin hidden, the screenshot rows have one label column → the single-series path
  (line over periods), not `twoDim` (:299-320).
- Period axis labels: use the readable twin's values ("FY 2023-24"), sorted in time order (sort by the hidden
  key when there is one — it is numeric and safe).
- Every descriptor gets `profile` (and charts get `xTitle`, `yTitle`, `unit`) so the components read names and
  units instead of re-deriving them.
- `askedMeasureCol` (KI-437) stays; it now reads profile labels/units too.
- No other branch changes: compare card, cross-summary charts, kpi, view requests keep their rules.

### C3. `Charts.jsx` — tables
- **One cell formatter** `formatCell(value, col)`:
  count → Indian grouping (`27264054` → `2,72,64,054`); ₹ lakh / ₹ crore → 2 decimals with grouping (unit in
  the header, not every cell); ₹ → `₹` + grouping; % → `45.20%`; null / "" / `"None"` → "—"; text unchanged.
  Used in `PivotGrid` (:831), `DynTable` (:793), `BigTable` (:771) and `RecordCard` (:871). Today cells print
  `String(v)` while pivot totals use `toLocaleString` — this removes the mix.
- **Headers**: `colLabel` (:720) → profile label + unit, e.g. "Total expenditure (₹ lakh)", "Person-days".
- **Numeric cells right-aligned**: class `num` on measure `<td>`/`<th>` (+ css).
- **Hidden technical columns**: `DynTable` / `BigTable` render visible columns only; a small note
  "N technical columns hidden — in the Excel download" when any were hidden. Sorting/search unchanged.
- **Totals rule in `PivotGrid`** (:812-838): row/column totals only when the measure is additive AND that
  dimension has 2+ values; grand total only when both totals are shown. Otherwise no Total row/column.
- **Trend table** (one period + one measure, 3+ rows, additive or not): extra column "Change from previous"
  (`+5,33,249` / `-6,91,413`, and % when the previous value is non-zero). Values come from the rows; nothing
  is invented. Shown in `DynTable` when the descriptor says `trend: true`.

### C4. `Charts.jsx` + `chartTheme.js` — chart axes
- **Axis titles**: `VALUE_AXIS` / `CAT_AXIS` (:42-43) get `title: { display: true, text }` from the
  descriptor's `yTitle` ("Person-days", "Expenditure (₹ lakh)") and `xTitle` ("Financial year", "District").
  Set in each config builder that uses them (:191, :201, :238, :247, `twoDimConfig` :634) — via one helper
  `withAxisTitles(options, xTitle, yTitle)` so the builders change by one line each.
- **Unit-aware ticks**: new `fmtAxis(v, unit)` in chartTheme.js beside `fmtCompact` (:243):
  count → `fmtCompact` as today (L / Cr), ₹ → `₹` + compact, ₹ lakh / ₹ crore → the number in its own unit,
  never re-abbreviated (`8,996` on a "(₹ lakh)" axis, not "9K" or "0.1L"), % → `45%`.
  `fmtCompact` stays for every caller that passes no unit, so nothing else moves.
- **Tooltips** (:29-34): the same `formatCell` as the table, plus the unit.
- **Bar value labels** (`barValueLabels` plugin) use `fmtAxis` with the unit.
- `TwoDimChart` (:651) subtitle uses profile labels instead of `replaceAll('_', ' ')`.

### C5. `Messages.jsx`
- Pass `a.profile` to `DynTable` / `PivotTable` / `RecordCard` (:88-181).
- `asked === 'table'` (:62) also builds the profile so "/table" gets the same formatting.

## 3. What the screenshot question will show

| | Before | After |
|---|---|---|
| Table | 3×3 diagonal grid, 6 dashes, raw + formatted numbers, Total column + row + grand total | `Financial year | Person-days | Change from previous` — 3 rows: FY 2023-24 2,72,64,054; FY 2024-25 1,46,67,872 (-1,25,96,182, -46.2%); FY 2025-26 2,33,87,018 (+87,19,146, +59.4%) |
| Chart | 3 bars in 3 legend colours, x-axis "2023", y-axis "2.7Cr" with no title | one line (or bar) series, x-axis "Financial year: FY 2023-24 …", y-axis title "Person-days", ticks "1 Cr, 2 Cr, 3 Cr" |

## 4. How it avoids new problems
- **Presentation only**: rows, answer text, SQL and the Excel export are unchanged.
- **Conservative twin merge**: only exact one-to-one pairs in the data.
- **Defaults keep today's behaviour**: a column with no known unit formats as a count with grouping (today it
  is raw); a chart with no unit keeps `fmtCompact`; every existing descriptor kind is still produced for the
  same rows except the twin case.
- **Tests that must keep passing**: `tests/test_cross_compare_card_2026_10_22.py` (card + "PMAY-G 0"),
  `tests/test_history_charts.py`, `tests/test_ac_full_results.py`, `tests/ui_headless/chart_view_requests.py`,
  and the full pytest + 14 scripts.
- **New tests** (`tests/test_table_view_2026_10_28.py`, real JS in node, real row shapes):
  1. the screenshot rows → one period column, no `twoDim`, no dashes, FY labels in order;
  2. district × year rows (real two-way) → still a pivot;
  3. cell formatting per unit (count, ₹ lakh, ₹ crore, ₹, %, null, "None");
  4. totals: added for person-days, NOT for %, average, job cards;
  5. technical columns hidden in the table, present in `data` (export);
  6. trend change column values;
  7. axis titles + `fmtAxis` per unit; `fmtCompact` unchanged;
  8. cross-scheme rows, compare card, single figure, name-only list, "as a pie chart" → same kinds as today.
- **Order**: C1 + C2 + C3 formatting (fixes the screenshot) → C4 axes → C3 totals / hidden / trend columns;
  each step: tests, `npm run build`, a browser check of 6-8 questions across the schemes.
- **Docs after**: KNOWN_ISSUES (new KI), CURRENT_STATE, HANDOFF, TESTING, ARCHITECTURE (frontend section).
