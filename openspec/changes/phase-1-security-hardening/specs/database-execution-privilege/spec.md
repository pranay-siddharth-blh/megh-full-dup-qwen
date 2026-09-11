## Purpose

Ensures the application's runtime database connection used to execute
generated queries cannot perform write or schema-altering operations,
independent of and in addition to any application-level SQL validation.

## ADDED Requirements

### Requirement: Runtime query execution uses a read-only database role
The runtime database connection used to execute generated or repaired SQL
SHALL use a database role holding only read (SELECT) privileges on the
schemas that generated SQL queries, so that a defect or bypass in
application-level SQL validation cannot by itself result in a write to
operational data.

#### Scenario: Application-level validation is bypassed or defective
- **WHEN** a generated or repaired SQL statement that should have been
  rejected by application-level validation reaches the database
  connection
- **THEN** the database role's own privileges SHALL prevent any write,
  DDL, or privilege-escalating operation from succeeding, regardless of
  the application-level validator's outcome

#### Scenario: Production role is confirmed, not assumed
- **WHEN** this requirement is evaluated against the running production
  environment
- **THEN** the actual database role the runtime connection uses SHALL be
  confirmed by inspecting the live configuration or an active connection
  — not inferred from the existence of a role-provisioning script — and
  any gap between the intended read-only role and the role actually in
  use SHALL be treated as a defect blocking this requirement from being
  considered met
