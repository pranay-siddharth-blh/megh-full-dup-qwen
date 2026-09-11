## Purpose

Structures and exposes the per-column computation `pipeline.py`'s
`_result_digest()` already performs (today text-only, feeding only the
composer prompt) as a typed, additive `findings` field in the `/api/query`
response, and adds detectors for cases the digest doesn't compute today
(large-result-set, threshold breach, stale-data).

## ADDED Requirements

### Requirement: The shared digest refactor is behavior-preserving for the existing composer prompt
The system SHALL refactor `_result_digest`'s per-column computation
(`pipeline.py:2868-2931`) into a shared, structured function (typed
sum/mean/max+row/min+row per numeric column, distinct values per
dimension column) consumed by both the existing prompt-building call site
and the new findings module, without duplicating the statistics logic.
The existing call site's output text SHALL remain byte-for-byte identical
to its pre-refactor output.

#### Scenario: The composer prompt is unchanged after the digest refactor
- **WHEN** the same query result is formatted into the composer prompt
  before and after the `_result_digest` refactor
- **THEN** the produced prompt text SHALL be byte-for-byte identical

### Requirement: An empty result produces exactly the empty-result finding
When a query returns no rows, the system SHALL emit the empty-result
finding (reusing `_no_data_answer`'s existing trigger condition) and no
other finding.

#### Scenario: An empty result produces only the empty-result finding
- **WHEN** a query's result set has zero rows
- **THEN** `findings` SHALL contain the empty-result finding and no
  other finding type

### Requirement: A result with a clear extreme produces an extremes finding matching the shared digest exactly
When a numeric column has a computable max or min, the system SHALL
emit an extremes finding whose values match the shared digest function's
own computed max/min (from task group defaults-engine's sibling
refactor) exactly, not re-derived independently.

#### Scenario: An extremes finding matches the digest's own numbers
- **WHEN** a result has a numeric column with a clear max and min
- **THEN** `findings` SHALL contain an extremes finding whose max/min
  values and row references are identical to those the shared digest
  function computed for that column

### Requirement: Rows sharing the extreme value produce a ties finding
When two or more rows share a column's extreme value (within the
digest's existing tolerance), the system SHALL emit a ties finding.

#### Scenario: A tie at the max value produces a ties finding
- **WHEN** two or more rows share the maximum value of a numeric column
- **THEN** `findings` SHALL contain a ties finding referencing those
  rows

### Requirement: A result over a configurable row-count threshold produces a large-result-set finding
When the result's row count exceeds a configurable threshold, the system
SHALL emit a large-result-set finding.

#### Scenario: A result over the threshold produces the large-result-set finding
- **WHEN** a query's row count exceeds the configured large-result-set
  threshold
- **THEN** `findings` SHALL contain a large-result-set finding

### Requirement: A threshold breach fires only for schemes with an authored thresholds file, and never raises for schemes without one
The system SHALL emit a threshold-breach finding only when the active
scheme has an authored `*_findings_thresholds.yaml` file and a result
value crosses one of its SME-reviewed thresholds. For a scheme with no
such file, the system SHALL NOT emit any threshold-breach finding and
SHALL NOT raise.

#### Scenario: A CM Elevate question crossing an authored threshold produces a threshold-breach finding
- **WHEN** a CM Elevate query result crosses a threshold defined in
  `data/cm_elevate/cmelevate_findings_thresholds.yaml`
- **THEN** `findings` SHALL contain a threshold-breach finding for that
  crossing

#### Scenario: An un-piloted scheme produces no threshold findings and does not raise
- **WHEN** a query against a scheme with no `*_findings_thresholds.yaml`
  file is evaluated
- **THEN** `findings` SHALL contain no threshold-breach finding, and
  evaluation SHALL NOT raise

### Requirement: A stale-data finding surfaces the scheme's existing dim_year data-quality note
When the active scheme's `dim_year` carries an existing
`data_quality_note`/`year_note` in `foreign_key_augmentation.yaml`'s
`nodes` section, the system SHALL surface it as a stale-data finding.

#### Scenario: A scheme with a curated year data-quality note produces a stale-data finding
- **WHEN** a query result's year dimension corresponds to a `dim_year`
  entry carrying a `data_quality_note` or `year_note` in
  `foreign_key_augmentation.yaml`
- **THEN** `findings` SHALL contain a stale-data finding carrying that
  note's content

### Requirement: `findings` is always present as a list, never omitted or null
The `/api/query` response dict SHALL always include a `findings` key
whose value is a list — empty when no detector fires, never omitted and
never `None`.

#### Scenario: A result with no findings still returns an empty list
- **WHEN** a query result triggers no detector
- **THEN** the response dict's `findings` key SHALL be present and SHALL
  be an empty list, not omitted and not `null`
