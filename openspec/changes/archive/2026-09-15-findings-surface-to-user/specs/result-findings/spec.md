## ADDED Requirements

### Requirement: Findings are rendered to the user in the chat UI
When `/api/query`'s response carries one or more entries in `findings`,
the frontend SHALL render each finding's `message` to the user, styled by
its `severity`, as part of the same chat response — not silently dropped
after being attached to the response.

#### Scenario: A response with findings shows them in the UI
- **WHEN** `/api/query` returns a `findings` list with at least one entry
- **THEN** the chat UI SHALL display each finding's message, visually
  distinguished by severity

#### Scenario: A response with no findings shows no findings block
- **WHEN** `/api/query` returns an empty `findings` list
- **THEN** the chat UI SHALL render no findings block for that response

### Requirement: Findings are rendered as a distinct UI element, not merged into the composed answer
The system SHALL NOT route `findings` into the LLM-composed answer prompt
(`compose_response`). Findings SHALL be rendered as a separate block from
the composed answer text.

#### Scenario: The composed answer prompt is unaffected by findings
- **WHEN** a result triggers one or more findings
- **THEN** the text passed to the response-composer LLM call SHALL be
  unchanged from what it would be with no findings present
