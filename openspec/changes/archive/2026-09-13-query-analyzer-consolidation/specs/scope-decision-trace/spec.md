## Purpose

Records how the scope/scheme classifier reached its decision for a question —
which mechanism decided, how confident it was, and why — so the decision is
auditable and explainable instead of only its final scheme list being visible.

## ADDED Requirements

### Requirement: Scope decision trace on every DATA-route answer
For every question that reaches scheme classification on the DATA route, the
system SHALL record a decision trace with `schemes`, `confidence` (0.0-1.0),
`source` (one of `llm`, `shortcut`, `fallback`), `reason` (a short
human-readable explanation), and `is_followup` (boolean), and SHALL attach it
to the response as `scope`.

#### Scenario: Named-scheme shortcut recorded
- **WHEN** the question names a scheme outright and is resolved via the
  deterministic shortcut path, without a model call
- **THEN** `scope.source` is `shortcut` and `scope.confidence` is at least as
  high as the LLM path's typical confidence

#### Scenario: Model-classified scheme recorded
- **WHEN** the question's scheme is decided by the classifier model call
- **THEN** `scope.source` is `llm` and `scope.reason` names the classification
  outcome in plain language

#### Scenario: Follow-up turn flagged
- **WHEN** the question is a rewritten follow-up building on a prior turn
- **THEN** `scope.is_followup` is `true`

### Requirement: No change to existing scheme-classification behavior
Recording the decision trace SHALL NOT alter which scheme(s) are returned for
any question, nor any other externally observable behavior of scheme
classification.

#### Scenario: Existing scheme classification test suite still passes
- **WHEN** the existing scheme-classification test suite is run after this
  capability is added
- **THEN** every test's asserted scheme list is unchanged from before this
  capability existed
