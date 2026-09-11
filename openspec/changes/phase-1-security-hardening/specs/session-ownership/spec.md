## Purpose

Ensures a resumed chat session or conversation can only be accessed by the
authenticated user who owns it, preventing cross-user conversation-context
leakage between unrelated requesters.

## ADDED Requirements

### Requirement: Session resumption verifies ownership
The system SHALL verify that a session or conversation identifier supplied
in a request belongs to the authenticated requester before returning or
mutating any state associated with that identifier.

#### Scenario: Requester supplies another user's session identifier
- **WHEN** an authenticated user submits a request carrying a session or
  conversation identifier that is recorded as owned by a different user
- **THEN** the system SHALL reject the request without returning or
  resuming any turn history, conversation state, or pending clarification
  from that identifier, and SHALL NOT bind the other user's session to the
  caller's identity

#### Scenario: Requester supplies their own or a fresh session identifier
- **WHEN** an authenticated user submits a request with a session
  identifier they own, or with no identifier, or with an identifier not
  yet associated with any user
- **THEN** the system SHALL resume or create the session as normal, and
  any newly created session SHALL be associated with the caller's own
  identity

### Requirement: Ownership is derived from a durable record, not request shape
The system SHALL determine session ownership from a database-backed or
otherwise durable record of the session's owner, not from the
identifier's format, a client-supplied header, or any other unauthenticated
claim in the request.

#### Scenario: Predictable or guessable identifier
- **WHEN** a session identifier follows a predictable pattern (for example,
  one derived from a user id and a date)
- **THEN** the system SHALL still enforce ownership by looking up the
  recorded owner, and SHALL NOT treat a pattern match or pre-existing
  identifier as proof of ownership on its own
