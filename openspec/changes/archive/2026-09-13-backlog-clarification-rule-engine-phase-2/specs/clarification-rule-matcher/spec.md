## ADDED Requirements

### Requirement: A question using ambiguous ranking, trend, or count vocabulary without a named measure is intercepted before SQL generation
The system SHALL detect, via a matcher registered for a given scheme's
`*_classification_rules.yaml` "which measure" (or scheme-equivalent)
condition, when a question asks to rank, trend, or count something
without naming which measure or subject that ranking, trend, or count
applies to, and SHALL raise a clarification (using that condition's
authored question text) before SQL generation runs for that question.

#### Scenario: A ranking or trend question names no measure
- **WHEN** a resolved question uses ranking or trend language (e.g. "top
  villages", "trend over time") for an active scheme, and names no
  specific measure that scheme's own registered conditions recognize
- **THEN** the system SHALL raise `ClarificationNeeded` with that
  condition's authored question text from the YAML, and SHALL NOT
  proceed to SQL generation for the original question

#### Scenario: A ranking or trend question already names a measure
- **WHEN** a resolved question uses ranking or trend language and also
  names a specific measure
- **THEN** no "which measure" clarification SHALL fire for that
  question, and the system SHALL proceed exactly as it does today

### Requirement: A condition whose authored question text cannot be correctly rendered by this engine is never wired
The system SHALL NOT register a matcher for a classification-rules
condition whose authored question text requires information the
matcher/registry mechanism cannot supply (for example, echoing back the
user's own ambiguous term via a placeholder no matcher can populate),
rather than firing that condition with a broken or generic rendering of
its question text.

#### Scenario: A condition's question text depends on information no matcher can supply
- **WHEN** a classification-rules condition's authored question text
  requires a value the matcher/registry mechanism has no way to compute
  or pass through
- **THEN** the system SHALL leave that condition unwired (no entry
  registered for it), SHALL NOT fire a clarification with a broken or
  literal placeholder for it, and SHALL proceed exactly as if that
  condition did not exist
