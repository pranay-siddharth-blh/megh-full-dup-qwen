## Purpose

Extracts the semantic structure of a data question — its query type, requested
metric, named entities, time scope, granularity, ambiguous terms, and a short
intent summary — into one structured object every downstream consumer (UI,
audit log) can read, instead of that information being implicit and scattered.

## ADDED Requirements

### Requirement: Structured analysis on every successful DATA-route answer
For every question that reaches SQL execution on the DATA route, the system
SHALL produce a structured analysis object with the fields: `query_type`,
`metric`, `entities`, `time_scope`, `granularity`, `limit`, `ambiguous`, and
`intent_summary`, and SHALL attach it to the response as `analysis`.

#### Scenario: Successful data answer carries an analysis object
- **WHEN** a question is classified as DATA, passes every clarification gate,
  and returns at least the SQL result rows
- **THEN** the response includes an `analysis` object with a non-empty
  `query_type` and `intent_summary`

#### Scenario: No analysis on non-DATA routes
- **WHEN** a question is routed to KNOWLEDGE, EDGE, or is denied before SQL
  execution
- **THEN** the response does not claim to include a populated `analysis`
  object for that turn

### Requirement: Query type classification
The system SHALL classify every analyzed question into exactly one of:
`aggregation`, `ranking`, `comparison`, `trend`, `lookup`, `distribution`,
`filter_list`.

#### Scenario: Ranking question classified correctly
- **WHEN** the question asks for a ranked list with an explicit count (e.g.
  "top 5 blocks by disbursement")
- **THEN** `analysis.query_type` is `ranking` and `analysis.limit` equals the
  requested count

#### Scenario: Comparison question classified correctly
- **WHEN** the question compares two or more named entities or schemes against
  each other
- **THEN** `analysis.query_type` is `comparison`

### Requirement: Entities reuse resolved pipeline state
`analysis.entities` SHALL be derived from the same entity-resolution result
already computed for the query (district/block/village/year/assembly
constituency resolution), not independently re-extracted or re-resolved.

#### Scenario: Resolved district appears in analysis entities
- **WHEN** the question's entity resolution already resolved a district to its
  canonical name
- **THEN** `analysis.entities` includes that same canonical district name

### Requirement: Ambiguous terms surfaced, not silently dropped
When entity resolution could not find a named mention in the data at all, or
the analyzer itself could not confidently determine the requested metric or
comparison basis, the system SHALL include each such gap in
`analysis.ambiguous` with the term, its kind, and a short reason. (A mention
that is genuinely ambiguous between multiple candidates is asked about
immediately via the existing clarification pause and never reaches this
object — see design.md for why.)

#### Scenario: Not-found entity mention surfaced
- **WHEN** entity resolution could not find a named mention anywhere in the
  data (not ambiguous — simply absent)
- **THEN** `analysis.ambiguous` includes an entry naming that mention and its
  kind

### Requirement: Analysis failure does not break the answer
A failure while producing the analysis object SHALL NOT prevent the question
from being answered; the response SHALL be returned without an `analysis`
field (or with a partial one) rather than failing the whole request.

#### Scenario: Analyzer call fails
- **WHEN** the analyzer's underlying model call raises an error or returns
  unusable output
- **THEN** the user still receives their data answer, with `analysis` omitted
  or null
