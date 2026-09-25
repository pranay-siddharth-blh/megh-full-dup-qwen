# chart-spec Specification

## Purpose

Given a query's already-fetched rows, column types, and classified
intent, deterministically computes a `chart_type` string and exposes it
as an additive `chart_type` field in the `/api/query` response — no new
charting-library dependency.

**Corrected 2026-09-11:** this repository has a real, git-tracked,
actively-mounted frontend, `web/ai_query.html` (served at `/ai-query` by
`app/main.py:221-224`; see `docs/baseline-audit.md` §3 item 10 for the
correction to the earlier "no frontend exists" finding and the
methodology gap that produced it). Its `buildAnalytics(question, data,
hintType)` function (`ai_query.html:2037-2165`) already reads
`response.chart_type` (`ai_query.html:2479`) and already implements full
client-side rendering for a closed, six-value vocabulary. This spec does
not design a new contract — it specifies the value `app/response/chart_spec.py`
must compute to drive rendering logic that already exists and is already
wired to consume it. Every requirement and scenario below cites the
exact `ai_query.html` branch it matches, so `buildAnalytics()` is the
behavioral source of truth throughout.

## Requirements

### Requirement: Column roles and row shape deterministically select a chart_type string
Given `rows` and column types inferred the same way `_result_digest`
already separates numeric from dimension columns (numeric / categorical /
temporal), the system SHALL deterministically select one `chart_type`
value from the closed set `{bar, doughnut, line, grouped_bar, stacked,
kpi_bar}`, or `None` — not a rendered spec, dict, or image. **Corrected
2026-09-11 (re-verified before implementation):** this does NOT take
`classify_intent` as an input. `classify_intent` (`pipeline.py:3135-3165`)
is a binary DATA/KNOWLEDGE router classifier; by the time this function
runs (only reached on the DATA route's successful-result return), its
value is a constant `"DATA"` and contributes no signal for distinguishing
among the six chart types. Selection instead uses only row count,
column-role counts, and — for the time-series case — a question-text/
column-name regex, matching what the client itself already relies on
with no backend intent field (see the time-series scenario below). This
is the exact vocabulary `web/ai_query.html`'s `buildAnalytics()` already
branches on
via the `hintType` parameter it receives as `response.chart_type`
(`ai_query.html:2479`).

#### Scenario: A single-dimension, single-metric result selects bar
- **WHEN** a result has exactly one categorical dimension column and one
  numeric metric column, and is not a single-row or time-series shape
- **THEN** chart_type SHALL be `"bar"` — matching `buildAnalytics`'s bar
  rendering (`ai_query.html:1960-1963`, reached via the default-chart
  path at `ai_query.html:2137-2164`) for a one-category-column,
  one-metric result

#### Scenario: A time-series result selects line
- **WHEN** a result includes a `year_key` (or equivalent temporal) column
  alongside a numeric metric column
- **THEN** chart_type SHALL be `"line"` — matching `buildAnalytics`'s own
  `isTime` fallback (`ai_query.html:2104,2112-2113`), which today infers
  a time axis only from column-name or question-text patterns
  (`month|period|year|date|trend`) when no hint is sent at all; sending
  `"line"` explicitly makes the same choice deterministic instead of
  leaving it to the client's text-sniffing heuristic

#### Scenario: A single-row result with 2+ comparable numeric columns selects kpi_bar
- **WHEN** a result has exactly one row and two or more numeric columns
  representing comparable parts of a whole (e.g. paid vs. pending counts)
- **THEN** chart_type SHALL be `"kpi_bar"` — the only value
  `buildAnalytics` honors specifically for a one-row result
  (`ai_query.html:2040`); it renders a bar/donut toggle over the row's
  columns and drops a derived total column from the chart (not the
  record card below it) when that total equals the sum of the other
  columns (`ai_query.html:2044-2060`)
- **Constraint:** `chart_spec.py` SHALL NOT return `"kpi_bar"` for a
  result whose row count is not exactly 1. The client only applies this
  hint when `data.length === 1` (`ai_query.html:2040`); sent for any
  other row count, the hint is silently ignored — `buildAnalytics` falls
  straight through to its own bar/doughnut/line heuristic
  (`ai_query.html:2112-2113`) as if no hint had been sent. This is a
  confirmed no-op, not a crash or a misrender, but it means the hint is
  simply wasted if the backend's row-count assumption is wrong — the
  selection logic must get the row count right, not just the shape.

#### Scenario: One category column with 2+ numeric measure columns selects grouped_bar
- **WHEN** a result has exactly one categorical/label column and two or
  more numeric measure columns
- **THEN** chart_type SHALL be `"grouped_bar"` — `buildAnalytics` renders
  every numeric column as its own dataset, grouped per category value,
  with no additional shape gate on this branch
  (`ai_query.html:2115-2124`, `groupedBar()` at `ai_query.html:1978-1983`)

#### Scenario: Two category columns with exactly one numeric measure column selects stacked
- **WHEN** a result has exactly two categorical/label columns (an x-axis
  category and a sub-group category) and exactly one numeric measure
  column
- **THEN** chart_type SHALL be `"stacked"` — `buildAnalytics` pivots the
  two label columns into x-axis categories and stacked segments
  (`pivotStackedBar()`, `ai_query.html:1991-1997`) rendered via
  `stackedBar()` (`ai_query.html:1984-1990`)
- **Constraint:** `chart_spec.py` SHALL NOT return `"stacked"` unless the
  result has at least two distinct categorical/label columns. The
  client's stacked branch requires `lblCols.length >= 2`
  (`ai_query.html:2126`); with fewer than two, the hint is silently
  ignored and `buildAnalytics` falls through to its default
  per-numeric-column rendering (`ai_query.html:2137-2164`) instead — the
  same silent-no-op pattern as an unmatched `kpi_bar` hint above.

#### Scenario: A small categorical result with no time signal selects doughnut
- **WHEN** a result has one categorical dimension column, one numeric
  metric column, 6 or fewer rows, and no time-series signal
- **THEN** chart_type SHALL be `"doughnut"` — matching `buildAnalytics`'s
  own `isFew` fallback (`ai_query.html:2111,2113`) for small, non-time
  result sets

### Requirement: A result shape that doesn't support a chart returns None instead of guessing
The system SHALL return `None` (surfaced as `null` in the response's
`chart_type` field) when the result shape is a single scalar (one row,
no grouping dimension, one numeric value), has more than two
grouping/categorical dimension columns, or has no numeric column —
rather than emitting a best-guess value. This matches how
`buildAnalytics` itself degrades for shapes it can't chart: a
single-row result without a `kpi_bar` hint renders as a plain record
card, not a chart (`ai_query.html:2076-2078`), and a result with no
numeric column renders as a plain table (`ai_query.html:2100`) — in
neither case does the client error or fabricate a chart.

#### Scenario: A single-scalar result produces no chart
- **WHEN** a result contains exactly one row and one numeric value with
  no grouping dimension
- **THEN** chart_type SHALL be `None`

#### Scenario: A result with more than two grouping dimensions produces no chart
- **WHEN** a result has more than two categorical/grouping dimension
  columns
- **THEN** chart_type SHALL be `None` rather than selecting a chart type

#### Scenario: A result with no numeric column produces no chart
- **WHEN** a result has no column that qualifies as numeric under the
  shared column-role inference
- **THEN** chart_type SHALL be `None` — matching `buildAnalytics`'s own
  fallback to a plain table when `numCols` is empty (`ai_query.html:2100`)

### Requirement: chart_type is a closed-vocabulary string or None, with no charting-library dependency
The emitted `chart_type` SHALL be one of the six literal strings `bar`,
`doughnut`, `line`, `grouped_bar`, `stacked`, `kpi_bar`, or the value
`None` — never any other string. `app/response/chart_spec.py` SHALL import no
charting or visualization library (e.g. no Vega-Lite, Altair, or
matplotlib import anywhere in that module). An unrecognized string is not
defined behavior for this module to produce: `buildAnalytics` does not
error on one, but silently treats it exactly like no hint at all — it
falls through the `hintType === 'bar' || 'doughnut' || 'line'` check
(`ai_query.html:2112`) to its own isTime/isFew default — so any value
outside the closed set is effectively equivalent to returning `None`,
just less honest about it.

#### Scenario: The emitted value matches the closed vocabulary and serializes cleanly
- **WHEN** a chart_type is produced for any supported result shape
- **THEN** it SHALL be one of the six defined string literals, SHALL
  serialize via the standard library `json` module without error, and
  `app/response/chart_spec.py`'s import list SHALL contain no
  charting/visualization library

### Requirement: `chart_type` is always present in the response, `null` when not applicable
The `/api/query` response dict SHALL always include a `chart_type` key —
one of the six string values when a chart type was selected, `null` when
the result shape doesn't support one — never omitted. This is the exact
field name and null convention `web/ai_query.html` already reads
(`response.chart_type`, `ai_query.html:2479`): before this phase ships,
the key is simply absent from the response and that read evaluates to
`undefined`, which `buildAnalytics` already handles gracefully as "no
hint" (`ai_query.html:2112`) — so populating the key for the first time
is backward-compatible with the client's current behavior by
construction.

#### Scenario: A non-chartable result still returns a present but null chart_type field
- **WHEN** a query result's shape doesn't support a chart
- **THEN** the response dict's `chart_type` key SHALL be present with
  value `null`, not omitted
