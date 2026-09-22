# pii-container-column-protection Specification

## Purpose
Closes a bypass in the completed `urgent-pii-redaction` change: a scheme's
JSONB "container" column (one column holding many fields, only some of
which are PII) could be exposed whole — bypassing the per-key blocklist
scan and the row-level redaction that only strips top-level dict keys, not
keys nested inside a JSON string value.
## Requirements
### Requirement: Whole exposure of a non-PII-only container column is rejected before execution
The system SHALL reject, before execution, any generated SQL that selects
a registered container column in full — bare, aliased, or via a wildcard
select that would include it — for the scheme that column belongs to.

#### Scenario: A query selects the container column bare or aliased
- **WHEN** generated SQL selects a scheme's registered container column
  without a JSON-extraction operator narrowing it to a single key (for
  example `SELECT scheme_specific` or `SELECT scheme_specific AS ss`)
- **THEN** the system SHALL reject the query as a privacy denial before
  execution, without naming the specific field that triggered it in any
  user-facing text

#### Scenario: A query selects all columns via a wildcard that includes the container column
- **WHEN** generated SQL selects `*` (or a table/view alias's `*`) from a
  view that includes a scheme's registered container column
- **THEN** the system SHALL reject the query as a privacy denial before
  execution, the same as a bare selection of that column

### Requirement: A scoped, single-key extraction from the container column is not rejected by this check alone
The system SHALL NOT reject a query solely for extracting one named key
from a registered container column via a JSON-extraction operator,
since a container column may hold legitimate non-PII fields that must
remain queryable.

#### Scenario: A query extracts a single non-blocklisted key from the container column
- **WHEN** generated SQL extracts one specific, non-blocklisted key from a
  scheme's registered container column via a JSON-extraction operator
- **THEN** this requirement SHALL NOT reject the query; the query MAY
  still be rejected by the existing blocklisted-column-name check if the
  extracted key name is itself on the blocklist

### Requirement: A blocklisted key nested inside a JSON-valued column is redacted after execution regardless of pre-execution detection
The system SHALL, after execution and independent of any pre-execution
text-based check, remove any blocklisted key found nested inside a
JSON-object value (whether represented as a string or as a parsed
object) in any returned row, while preserving every other key in that
same value unchanged.

#### Scenario: A returned row contains a JSON string value with both blocklisted and non-blocklisted keys
- **WHEN** a row returned by query execution contains a column whose value
  is a JSON-object string containing one or more blocklisted keys
  alongside one or more non-blocklisted keys
- **THEN** the system SHALL return that value with every blocklisted key
  removed and every non-blocklisted key preserved with its original
  value, re-serialized in the same representation (string stays a
  string) it was received in

#### Scenario: A returned value is not JSON or contains no blocklisted keys
- **WHEN** a row value is not a JSON-object string or dict, or is one but
  contains no blocklisted keys
- **THEN** the system SHALL return that value unchanged

