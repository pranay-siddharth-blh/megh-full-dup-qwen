# query-audit-trail Specification

## Purpose
Defines the compliance-grade audit record persisted for every query so
that an investigation can reconstruct what a user asked, what SQL
actually ran, what came back, and what the user was shown — independent
of and surviving any user-initiated deletion of their own chat history.
## Requirements
### Requirement: Audit record captures the executed SQL
Every completed data-route query SHALL have its final, executed SQL
text (the version actually run against the database, after any repair
regeneration) recorded in the durable compliance audit record, not only
in the separate, user-deletable conversation-history record.

#### Scenario: Query executes successfully on the first attempt
- **WHEN** a data-route query generates SQL, passes validation, and
  executes without a repair cycle
- **THEN** the audit record for that query SHALL include the exact SQL
  text that was executed

#### Scenario: Query executes only after a repair cycle
- **WHEN** the initial generated SQL fails validation or execution and
  a repaired SQL statement is generated, re-authorized, and executed
  instead
- **THEN** the audit record SHALL include the SQL that was actually
  executed (the repaired version), not the original failed attempt

### Requirement: Audit record captures a bounded result preview
The audit record SHALL include a size-bounded preview of the query's
result rows, sufficient to support an investigation without storing an
unbounded copy of query output in the compliance table.

#### Scenario: Query returns rows within the preview bound
- **WHEN** a data-route query returns a result set at or under the
  approved preview size
- **THEN** the audit record's result preview SHALL contain that result
  set (or the same rows already surfaced to the user, whichever is
  smaller)

#### Scenario: Query returns more rows than the preview bound
- **WHEN** a data-route query's result set exceeds the approved preview
  size
- **THEN** the audit record's result preview SHALL contain only the
  first N rows up to that bound, and SHALL NOT silently store the full
  result set

### Requirement: Audit record captures findings and chart type
The audit record SHALL include the result-findings output and the
chart-type hint that were computed for that query and (when present)
returned to the user, so the audit trail reflects what the user was
actually shown, not only what was queried.

#### Scenario: Findings and chart-type selection both run
- **WHEN** a data-route query completes and both findings evaluation
  and chart-type selection produce a non-empty result
- **THEN** the audit record SHALL include both the findings list and
  the selected chart type

#### Scenario: Findings or chart-type selection is disabled or produces nothing
- **WHEN** findings evaluation or chart-type selection is disabled by
  configuration, fails, or produces no result for a given query
- **THEN** the audit record SHALL record that absence explicitly (e.g.
  an empty list or null value), not omit the field or fail the audit
  write

### Requirement: Audit record captures the final response text
The audit record SHALL include the final response text shown to the
user for that query, so the compliance trail reflects the answer given,
not only the data queried to produce it.

#### Scenario: Query completes with an answer
- **WHEN** a query completes and a response answer is returned to the
  user
- **THEN** the audit record SHALL include that same answer text

### Requirement: Audit write failure never blocks the response
Recording the expanded audit fields SHALL remain best-effort: a failure
to write any part of the audit record, including the new fields, SHALL
NOT prevent the query response from reaching the user.

#### Scenario: Audit write fails after a successful query
- **WHEN** a data-route query completes successfully but writing the
  audit record (JSONL file or `app.query_audit` row) raises an error
- **THEN** the user SHALL still receive their answer, and the failure
  SHALL be logged rather than raised to the caller

### Requirement: Audit trail survives user-initiated history deletion
The compliance audit record, including its executed-SQL, result-preview,
findings, chart-type, and final-response-text fields, SHALL remain
intact when a user deletes their own conversation history, since it is
the record an investigation relies on independent of what the user
chooses to keep.

#### Scenario: User deletes a conversation
- **WHEN** a user deletes one of their own conversations
- **THEN** the corresponding audit records in the compliance trail
  SHALL NOT be deleted or modified as a result

