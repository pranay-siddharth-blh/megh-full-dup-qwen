## ADDED Requirements

### Requirement: Ambiguous-entry provenance
Each entry in `analysis.ambiguous` SHALL carry a provenance marker
distinguishing an entry that duplicates a message already surfaced via
entity resolution from one that is genuinely new information contributed by
the analyzer's own model call.

#### Scenario: Not-found entity mention marked as a duplicate-origin entry
- **WHEN** entity resolution could not find a named mention in the data
- **THEN** the corresponding `analysis.ambiguous` entry is marked as
  originating from entity resolution, not from the analyzer's own model call

#### Scenario: Model-flagged metric ambiguity marked as new-origin entry
- **WHEN** the analyzer's own model call flags a non-entity ambiguity (an
  unclear metric or comparison basis)
- **THEN** the corresponding `analysis.ambiguous` entry is marked as
  originating from that model call

### Requirement: Genuinely new ambiguity is disclosed to the user
When the analyzer flags a non-entity ambiguity that does not duplicate an
entity-resolution message, the system SHALL disclose it to the user as part
of the answer, without pausing to ask a clarifying question.

#### Scenario: New ambiguity appears in the disclosed answer
- **WHEN** a successful DATA-route answer's analysis flags a non-entity
  ambiguity not already covered by an entity-resolution note
- **THEN** the final answer discloses that ambiguity as a note

#### Scenario: Duplicate-origin ambiguity is not disclosed twice
- **WHEN** an `analysis.ambiguous` entry duplicates a message already
  surfaced via entity resolution
- **THEN** the final answer does not disclose that same gap a second time

#### Scenario: A flagged ambiguity never pauses the answer
- **WHEN** the analyzer flags any ambiguity, of any origin
- **THEN** the question is still answered in the same turn — no new
  clarification pause is introduced by this behavior
