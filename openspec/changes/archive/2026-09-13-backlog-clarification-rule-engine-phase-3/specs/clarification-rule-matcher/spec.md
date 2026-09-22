## ADDED Requirements

### Requirement: A question that reads an existing column against a meaning it does not support is intercepted before SQL generation
The system SHALL detect, via a matcher registered for a given scheme's
`*_classification_rules.yaml` "measures/fields that exist but must not be
reported as asked" (or scheme-equivalent) condition, when a question asks
for a column or term the schema does hold, but under a reading that column
does not actually support (a flat entitlement asked for as if it varies, a
workflow-stage label asked for as if it were an approval, a payment record
asked for as if it were proof of completion, and scheme-specific
equivalents), and SHALL raise a clarification (using that condition's
authored question text) before SQL generation runs for that question,
rather than returning a technically-valid but semantically wrong figure.

#### Scenario: A question asks an existing column to answer something it cannot support
- **WHEN** a resolved question, for an active scheme, uses phrasing that
  matches a registered "exists but must not be read as asked" condition
  for that scheme
- **THEN** the system SHALL raise `ClarificationNeeded` with that
  condition's authored question text from the YAML, and SHALL NOT proceed
  to SQL generation for the original question

#### Scenario: A question about the same column does not trigger the misreading
- **WHEN** a resolved question names the same column or term but does not
  use the misreading phrasing a registered condition targets (e.g. asks
  for the column's recorded value directly rather than the meaning the
  condition warns against)
- **THEN** no clarification SHALL fire for that question, and the system
  SHALL proceed exactly as it does today

### Requirement: A condition already covered by an existing hardcoded predicate is never re-wired, and the collision set is kept accurate as new sections are wired
The system SHALL NOT register a matcher for a classification-rules
condition name already handled end-to-end by an existing hardcoded
predicate in `app/pipeline.py`. Before wiring any new section, the
condition names in that section SHALL be cross-checked against every
existing hardcoded predicate's actual trigger logic (not name similarity
alone), and any condition found to be already covered SHALL be added to
`_COLLISION_CONDITIONS` at the same time a matcher would otherwise have
been written for it.

#### Scenario: A newly-wired section contains a condition an existing hardcoded predicate already covers
- **WHEN** a condition name in a section being wired is confirmed, by
  reading the hardcoded predicate's own logic, to already be handled by it
- **THEN** the system SHALL add that condition name to
  `_COLLISION_CONDITIONS`, SHALL NOT register a matcher for it in
  `_MATCHERS`, and `check_clarifications` SHALL continue to never fire for
  it regardless of `_MATCHERS` content

#### Scenario: A condition is authored but the data now makes it fully answerable
- **WHEN** a classification-rules condition's own YAML entry states (via a
  note such as a `v2_note` or an explicit "NOT A REFUSAL" annotation) that
  the question it used to refuse is now answerable
- **THEN** the system SHALL leave that condition unwired, exactly as
  Phase 1 already does for PMAY-G's `villages_without_houses_requested`
