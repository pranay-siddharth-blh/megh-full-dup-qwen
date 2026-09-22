## ADDED Requirements

### Requirement: Implicit FKs can be mined from historical query logs for SME review
The system SHALL provide a read-only tool that scans allowed queries
recorded in `app.query_audit`, extracts JOIN-ON column equalities
between two tables the join graph already knows about (curated YAML or
live foreign keys) but has no edge between, and surfaces them as
candidates for a human SME to review — and SHALL NOT write any mined
candidate into the live join graph or into a `foreign_key_augmentation.yaml`
file automatically.

#### Scenario: A recurring unknown-edge join across logged queries is surfaced
- **WHEN** two known tables with no declared edge between them are
  joined on the same pair of columns in at least `min_occurrences`
  logged, allowed queries
- **THEN** the mining function SHALL return a candidate naming both
  tables, both columns, the occurrence count, and a sample SQL string

#### Scenario: A pair already covered by a declared or curated edge is not surfaced
- **WHEN** the join graph already has a non-prohibited edge between the
  two tables a logged query joins on
- **THEN** that pair SHALL NOT appear in the mined candidates, regardless
  of how many logged queries use it

#### Scenario: An unresolvable or unqualified join is skipped, not guessed at
- **WHEN** a logged query's JOIN-ON clause references a bare/CTE-aliased
  table, a composite condition that isn't a simple column-to-column
  equality, or a table absent from every curated YAML and from live FKs
- **THEN** that join SHALL be skipped and SHALL NOT produce a candidate

#### Scenario: A mined candidate never becomes a usable join path on its own
- **WHEN** a candidate is returned by the mining function
- **THEN** `join_graph.find_join_path()` SHALL continue to return
  `"no_path"` (or route through a different edge) for that table pair
  until a human adds the edge to the relevant scheme's curated YAML by
  hand
