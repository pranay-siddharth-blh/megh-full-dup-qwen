## Purpose

Given a query's already-fetched rows, column types, and classified
intent, deterministically selects a chart type and emits a minimal
declarative JSON spec — not a rendered image — as an additive `chart`
field in the `/api/query` response, with no new charting-library
dependency.

## ADDED Requirements

### Requirement: Column roles and classified intent deterministically select a chart type
Given `rows`, column types inferred the same way `_result_digest`
already separates numeric from dimension columns (numeric / categorical
/ temporal), and the question's already-computed `classify_intent`
result, the system SHALL deterministically select a chart type (bar /
line / grouped-bar / none) and emit a minimal declarative JSON dict — a
plain dict, not a call into any chart-rendering library.

#### Scenario: A single-dimension, single-metric result produces a bar spec
- **WHEN** a result has exactly one categorical dimension column and one
  numeric metric column
- **THEN** the chart spec SHALL select the bar type with that dimension
  bound to x and that metric bound to y

#### Scenario: A time-series result produces a line spec
- **WHEN** a result includes a `year_key` (or equivalent temporal)
  column alongside a numeric metric column
- **THEN** the chart spec SHALL select the line type with the temporal
  column bound to x and the metric bound to y

### Requirement: A result shape that doesn't support a chart returns null instead of guessing
The system SHALL return `None` (surfaced as `null` in the response) when
the result shape is a single scalar, has more than two grouping
dimensions, or has no numeric column — rather than emitting a
best-guess spec.

#### Scenario: A single-scalar result produces no chart
- **WHEN** a result contains exactly one row and one numeric value with
  no grouping dimension
- **THEN** the chart spec function SHALL return `None`

#### Scenario: A result with more than two grouping dimensions produces no chart
- **WHEN** a result has more than two categorical/grouping dimension
  columns
- **THEN** the chart spec function SHALL return `None` rather than
  selecting a chart type

### Requirement: The chart spec is JSON-serializable with no added dependency
The emitted chart spec SHALL be JSON-serializable using only the
standard library, and `app/chart_spec.py` SHALL import no charting or
visualization library (e.g. no Vega-Lite, Altair, or matplotlib import
anywhere in that module).

#### Scenario: The emitted spec serializes with the standard library and no new dependency is imported
- **WHEN** a chart spec is produced for a supported result shape
- **THEN** it SHALL serialize via the standard library `json` module
  without error, and `app/chart_spec.py`'s import list SHALL contain no
  charting/visualization library

### Requirement: `chart` is always present in the response, `null` when not applicable
The `/api/query` response dict SHALL always include a `chart` key —
a spec dict when a chart type was selected, `null` when the result
shape doesn't support one — never omitted.

#### Scenario: A non-chartable result still returns a present but null chart field
- **WHEN** a query result's shape doesn't support a chart
- **THEN** the response dict's `chart` key SHALL be present with value
  `null`, not omitted
