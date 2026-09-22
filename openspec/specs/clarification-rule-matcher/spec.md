# clarification-rule-matcher Specification

## Purpose

Closes the gap between the clarification rules SME-authored in
`*_classification_rules.yaml` (341 conditions across four schemes) and
what the runtime pipeline actually enforces (~7, via hand-written
predicates in `app/pipeline.py`). Scoped to the 75 conditions in the
highest-risk "source cannot answer this at all" category first — the
class already proven, in production, to produce a wrong or empty answer
rather than a clarifying question when unguarded.

## Requirements

### Requirement: A question matching an unanswerable-data condition is intercepted before SQL generation
The system SHALL detect, via a matcher registered for a given scheme's
`*_classification_rules.yaml` "cannot answer at all" condition, when a
question asks for a fact the underlying data does not hold, and SHALL
raise a clarification (using that condition's authored question text)
before SQL generation runs for that question.

#### Scenario: A question asks for a fact absent from the scheme's data
- **WHEN** a resolved question matches a registered "cannot answer at all"
  condition for the active scheme (e.g. a pending-dues, fund-availability,
  wage-rate, or per-capita question against MGNREGA)
- **THEN** the system SHALL raise `ClarificationNeeded` with that
  condition's authored question text from the YAML, and SHALL NOT proceed
  to SQL generation for the original question

#### Scenario: A question does not match any registered condition
- **WHEN** no registered matcher fires for a resolved question
- **THEN** the system SHALL proceed exactly as it does today — this
  requirement adds no new blocking behavior for questions outside the
  75-condition scope of this phase

### Requirement: A condition already owned by an existing hardcoded predicate is never matched by this engine
The system SHALL NOT fire a clarification from this engine for any
condition name already covered by an existing hardcoded
`_needs_*_clarification` predicate or the existing
`_admin_expenditure_clarification` / `_women_share_clarification`
predicates, regardless of what this engine's own matcher would otherwise
detect for that condition.

#### Scenario: A question matches both an existing predicate's topic and a YAML condition this engine could also detect
- **WHEN** a question would trigger both an existing hardcoded predicate
  and a condition this engine has a matcher for
- **THEN** the existing hardcoded predicate's question text SHALL be what
  the user sees, and this engine SHALL NOT also fire or produce a second,
  conflicting clarification

### Requirement: A malformed or missing classification-rules file degrades to no clarification from this engine, never a crash
The system SHALL tolerate a missing, unreadable, or malformed
`*_classification_rules.yaml` for any scheme by producing zero matches
from this engine for that scheme, and SHALL NOT raise an unhandled
exception or block the pipeline.

#### Scenario: A scheme's classification-rules file is absent or malformed
- **WHEN** `*_classification_rules.yaml` for the active scheme cannot be
  loaded or parsed
- **THEN** this engine SHALL contribute no clarification for that scheme,
  and the pipeline SHALL continue exactly as if this engine were disabled
  for that request

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
