# pii-denial-audit-trail Specification

## Purpose
Closes a gap where a PII-triggered clarification pause was indistinguishable
from every other clarification reason in the durable audit trail, making it
impossible to query how often or where PII denials occurred.
## Requirements
### Requirement: A clarification's triggering rule is persisted as a queryable field
The system SHALL record which rule triggered a clarification pause as a
queryable field on every durably persisted record of that turn, not only
in application logs or in a nested field of the response body.

#### Scenario: A PII-column-blocked clarification is persisted
- **WHEN** a query is paused for clarification because it referenced a
  blocklisted column or exposed a non-PII-only container column whole
- **THEN** every durable persistence sink for that turn SHALL record the
  triggering rule identifier as a queryable field, without recording the
  specific blocklisted column or field name

#### Scenario: A non-PII clarification is persisted
- **WHEN** a query is paused for clarification for any other reason (for
  example, an unspecified scope or an ambiguous entity)
- **THEN** the same queryable field SHALL record that clarification's own
  triggering rule identifier, using the same mechanism as a PII denial

