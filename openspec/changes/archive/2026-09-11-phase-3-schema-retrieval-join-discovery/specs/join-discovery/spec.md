## Purpose

Computes explicit join paths from declared foreign keys and curated join
edges over a graph built at startup, so the SQL generator is shown a
validated join instead of being left to invent one — and, in the
specific case where the schema-retrieval capability itself has already
identified two or more required tables for the active scheme(s), gates
SQL generation entirely rather than proceeding on an unsafe combination.

## ADDED Requirements

### Requirement: Join paths are computed only from declared or curated edges
Given a set of tables, the system SHALL compute a join path using only
edges that are either real foreign-key constraints (read from
`information_schema`/`pg_constraint`) or edges explicitly present in the
curated join-graph YAML, and SHALL NOT emit any `ON` clause invented by
an LLM.

#### Scenario: A query needing two related tables gets the graph's join, not a guessed one
- **WHEN** two tables connected by exactly one declared foreign key are
  looked up
- **THEN** the join-path function SHALL return that foreign key's exact
  `ON` clause, and the SQL-generation prompt SHALL include it as a
  required-join hint alongside the existing REAL FOREIGN KEYS block

#### Scenario: An edge marked prohibited is never used to build a path
- **WHEN** the only structural connection between two tables is an edge
  marked `is_prohibited` in the curated YAML
- **THEN** the join-path function SHALL NOT include that edge in any
  returned path, even if it is the shortest structural connection
  available

#### Scenario: A node marked unreadable by the read-only role is excluded from the graph
- **WHEN** a curated YAML node is tagged `readable_by_read_role: false`
  (the `raw` schema, outside `megh_readonly`'s boundary)
- **THEN** that node SHALL be excluded from the graph entirely,
  regardless of whether the specific edge into it is separately marked
  `is_prohibited` — node-level exclusion is the safety net, confirmed
  necessary because one curated YAML's edge into `raw.source_rows` was
  found missing that per-edge flag

### Requirement: A fan-out guard flags unsafe fact-to-fact paths
When a computed join path connects two tables both marked as fact
tables in the curated metadata, the system SHALL check whether the path
routes through at least one shared dimension table, and SHALL flag the
result rather than returning a usable join when it does not.

#### Scenario: Two fact tables with no shared-dimension path trigger the guard
- **WHEN** the shortest path between two fact-tagged tables does not
  pass through any dimension-tagged table
- **THEN** the join-path function SHALL return a fan-out-guard signal
  instead of a usable `ON` clause

### Requirement: SQL generation is gated only when schema retrieval itself supplied the required tables
When `schema-retrieval` (see that capability's spec) returns two or more
distinct table-granularity candidates for the active scheme(s), the
system SHALL compute the join path between those specific tables before
invoking SQL generation, and SHALL route to the existing
clarification/refusal mechanism instead of proceeding when that path is
absent or trips the fan-out guard. Outside this case (fewer than two
retrieved table candidates — the common case, since every scheme
piloted so far has exactly one fact table and this condition can only
arise across schemes) join-path results are folded into the prompt as
an additive hint only, at the same enforcement tier as the existing
PROHIBITED JOINS mechanism (a prompt instruction, not a runtime parse of
the generator's output SQL — verified this is the existing mechanism's
actual guarantee level too, not a lesser one introduced by this
capability).

#### Scenario: Retrieval-identified tables with no approved path trigger clarification before generation
- **WHEN** `schema_retrieval.retrieve()` returns two distinct
  table-granularity candidates for the active scheme, and no path
  exists between them in the join graph
- **THEN** the system SHALL raise the existing clarification/refusal
  signal before the SQL generator is invoked, and no SQL referencing an
  invented join between those tables SHALL be generated

#### Scenario: Retrieval-identified fact tables with no shared dimension trigger clarification before generation
- **WHEN** `schema_retrieval.retrieve()` returns two distinct
  table-granularity candidates that are both fact-tagged, and the
  fan-out guard trips between them
- **THEN** the system SHALL raise the existing clarification/refusal
  signal before the SQL generator is invoked

#### Scenario: Fewer than two retrieved table candidates is not gated
- **WHEN** `schema_retrieval.retrieve()` returns zero or one
  table-granularity candidate (including every scheme with no schema-
  metadata indexed yet)
- **THEN** the system SHALL NOT gate SQL generation on join-path
  results, and SHALL proceed exactly as it would without this capability

#### Scenario: A valid joined query still passes existing SQL safety validation unchanged
- **WHEN** a generated query uses a join path this capability
  identified for two related tables
- **THEN** that query SHALL pass the existing SQL safety validation
  (`_assert_safe` or equivalent) exactly as a query without a computed
  join path would, with no change required to that validation
