# defaults-engine Specification

## Purpose

Applies the existing, SME-authored `*_default_rules.yaml` files (currently
unwired) so that questions matching a defined condition receive a silent,
disclosed default instead of the system always asking a clarifying
question — while guaranteeing zero behavior change to any condition an
existing hardcoded `_needs_*_clarification` predicate already handles.

## Requirements

### Requirement: Question text and resolved entities are matched to default-rule conditions
Given a question and its resolved entities, the system SHALL match them
against the active scheme's `*_default_rules.yaml` conditions using a
per-scheme regex/keyword matcher, returning zero or more matched
condition names.

#### Scenario: A question matching a non-colliding condition resolves that condition
- **WHEN** a question's text and resolved entities match a condition
  defined in the active scheme's `*_default_rules.yaml` (e.g. a missing
  geography scope) and that condition is not covered by any existing
  `_needs_*_clarification` predicate
- **THEN** the matcher SHALL return that condition name

#### Scenario: A question matching no condition returns no defaults
- **WHEN** a question's text and resolved entities match none of the
  active scheme's `*_default_rules.yaml` conditions
- **THEN** the matcher SHALL return no condition names, and `notes`
  SHALL remain unchanged from what it would be without this capability

### Requirement: A matched condition already covered by a hardcoded clarification predicate is never defaulted
Before applying any matched condition, the system SHALL check it against
the set of conditions already covered by an existing hardcoded
`_needs_*_clarification` predicate in `app/orchestration/pipeline.py`. If the condition
is in that collision set, the existing predicate's ask-behavior SHALL win
and the default SHALL be skipped — the collision SHALL be enforced in
code, not left as a documentation-only convention.

#### Scenario: A colliding condition produces no default and leaves the existing clarification gate unchanged
- **WHEN** a question matches the `missing_top_n` condition, which
  collides with the existing `_needs_topn_clarification` predicate
  (`pipeline.py:983`)
- **THEN** the defaults engine SHALL NOT apply a default or append any
  `assumption_text`, and `_needs_topn_clarification` SHALL fire exactly
  as it did before this capability existed

### Requirement: A non-colliding matched condition produces a disclosed assumption
When a matched condition is not in the collision set, the system SHALL
format that condition's `assumption_text` (interpolating `{placeholder}`s
from the resolved entities/context) and append it to the same `notes`
list `app/nlu/premise_check.py`'s `check_premises` already writes into, ahead
of `compose_response`.

#### Scenario: A non-colliding default appends its assumption text to notes
- **WHEN** a question matches a non-colliding condition (e.g. a missing
  geography scope) in the active scheme's `*_default_rules.yaml`
- **THEN** `notes` SHALL contain that condition's `assumption_text`,
  interpolated with the resolved entities/context, before
  `compose_response` is called

### Requirement: A malformed or missing default-rules file degrades to no defaults, never raises
The system SHALL NOT raise when a scheme's `*_default_rules.yaml` is
missing or malformed; it SHALL instead behave as if no condition matched
for that scheme.

#### Scenario: A scheme with a missing or malformed default-rules file produces no defaults without error
- **WHEN** the active scheme's `*_default_rules.yaml` is missing from
  disk or fails to parse
- **THEN** the defaults engine SHALL return no matched conditions for
  that scheme, append nothing to `notes`, and SHALL NOT raise an
  exception
