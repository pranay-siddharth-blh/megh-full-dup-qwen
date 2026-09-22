## Purpose

Closes the gap between the PRD's join-discovery guarantee ("the model
never invents joins") and the pre-generation-only hint the existing
`join_graph.find_join_path` hard-gate provides (narrow: only fires when
schema retrieval already named 2+ required tables). Adds an always-on,
post-generation backstop that parses the SQL the generator actually wrote
and flags a join between two tables the FK graph has no relationship
between.

## ADDED Requirements

### Requirement: A join between two known, unrelated tables is detected and rejected as repairable
The system SHALL parse generated or repaired SQL and, for each `JOIN`
whose own `ON` clause resolves to exactly two tables both known to the
foreign-key graph, reject the query as a repairable error when no edge
connects that pair — regardless of whether schema retrieval named 2 or
more required tables for this query.

#### Scenario: Generated SQL directly joins two tables with no declared relationship
- **WHEN** generated or repaired SQL contains a `JOIN` whose `ON` clause
  connects two tables that are both known to the foreign-key graph but
  have no edge between them
- **THEN** the system SHALL raise a repairable error naming both tables,
  SHALL NOT execute that SQL, and SHALL include a suggested join path
  when the foreign-key graph has one connecting the two tables indirectly

#### Scenario: Generated SQL joins two tables that do have a declared relationship
- **WHEN** generated or repaired SQL contains a `JOIN` whose `ON` clause
  connects two tables with a declared edge between them in the
  foreign-key graph
- **THEN** the system SHALL NOT reject the query on this basis, regardless
  of whether that edge came from a live-introspected foreign key or a
  curated YAML addition

### Requirement: The sanctioned CTE-to-CTE cross-scheme aggregation pattern is never flagged
The system SHALL NOT treat a join between two common-table-expression
(CTE) references as an invented join, since this codebase's sanctioned
pattern for combining data across schemes with no direct table
relationship is to aggregate each side into its own CTE first and join
the CTEs on a shared non-key column.

#### Scenario: A query joins two CTEs, each aggregating a different scheme's fact table
- **WHEN** generated SQL defines two CTEs, each aggregating a different
  base table to a shared grain, and joins those two CTEs together
- **THEN** the system SHALL NOT reject the query on the basis of the two
  underlying base tables (referenced only inside their respective CTEs)
  having no declared relationship

### Requirement: A table absent from every known source is left unvalidated, not treated as invented or as safe
The system SHALL distinguish a table pair where at least one side is
absent from every curated YAML and every live-introspected foreign key
("unknown") from a table pair where both sides are known but have no
edge between them ("known and unrelated"), and SHALL only reject the
latter.

#### Scenario: A join references a table not present in any curated YAML or live foreign-key introspection
- **WHEN** a generated SQL `JOIN`'s `ON` clause resolves to a table that
  is not named in any scheme's foreign-key YAML (as a node or an edge
  endpoint, prohibited or not) and was not returned by live foreign-key
  introspection
- **THEN** the system SHALL NOT reject the join on the basis of that
  unknown table, since it cannot distinguish a genuinely invented
  relationship from a real one the graph has not yet catalogued (for
  example, during a live database outage where introspection returns
  no results)

### Requirement: Unparseable or ambiguous SQL degrades to no detection, never a crash
The system SHALL return no invented-join findings, rather than raising an
exception, when the generated SQL cannot be parsed, or when a `JOIN`'s
`ON` clause cannot be resolved to exactly two known tables (for example, a
composite condition referencing three or more tables, a `USING` clause,
or a `CROSS JOIN` with no `ON` clause at all).

#### Scenario: Generated SQL fails to parse
- **WHEN** the SQL text handed to this check cannot be parsed as valid SQL
- **THEN** the system SHALL treat this check as finding nothing, and SHALL
  defer to whatever other validation already handles malformed SQL

#### Scenario: A JOIN has no ON clause or an ON clause spanning more than two tables
- **WHEN** a `JOIN` in the generated SQL has no `ON` clause (a `CROSS
  JOIN`) or an `ON` clause whose referenced columns resolve to more or
  fewer than exactly two distinct known tables
- **THEN** the system SHALL NOT flag that join, treating it as outside
  this check's scope rather than guessing
