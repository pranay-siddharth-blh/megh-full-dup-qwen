## Purpose

Guarantees that a clarification pause — a scope, year, or entity-ambiguity
question the system must ask before it can safely answer — is never
silently lost, so a user's reply always resumes the question it answers
regardless of which server process or session state happens to handle it.

## ADDED Requirements

### Requirement: Clarification pause resumes across a worker or process boundary
When the system pauses a question to ask the user a scope, year, or
entity-ambiguity clarifying question, it SHALL retain enough context to
merge the user's next reply back into that same paused question, even
when the reply is handled by a different server process than the one
that raised the pause, provided the underlying conversation has not
itself expired or been deleted.

#### Scenario: Reply is handled by a different worker process
- **WHEN** a question is paused with a scope, year, or entity-ambiguity
  clarifying question, and the user's reply is routed to a different
  worker process than the one that raised the pause
- **THEN** the system merges the reply into the original paused question
  rather than treating it as a new, unrelated question

#### Scenario: The worker that raised the pause restarts before the reply
- **WHEN** the server process that raised a clarification pause restarts
  before the user replies
- **THEN** a reply sent afterward, to the same conversation, is still
  merged into the paused question

#### Scenario: In-memory session state has expired but the conversation has not
- **WHEN** the short-lived in-process session record for a conversation
  has expired before the user replies to a clarification pause, but the
  conversation itself still exists
- **THEN** the reply is still merged into the paused question

#### Scenario: Reply handled by the same process, no expiry (baseline preserved)
- **WHEN** a user replies to a clarification pause on the same process
  that raised it, before any session expiry
- **THEN** the reply is merged into the paused question, matching prior
  behavior

### Requirement: A clarification pause is durably recorded when it is raised, not only when the turn later succeeds
The system SHALL durably record a clarification pause's resumption
context at the time the clarifying question is returned to the user, so
that a reply arriving before any other turn on that conversation
completes can still be resumed.

#### Scenario: Reply arrives immediately after the clarifying question, before any other turn
- **WHEN** a clarifying question has just been returned to the user and
  no other turn on that conversation has completed since
- **THEN** the user's reply is still correctly merged into the paused
  question, including on a different worker process

### Requirement: An alternative interrupt-primitive pause/resume component is available, without being the system's default path
The system SHALL provide a separate, explicitly-invoked pause/resume
component that suspends and durably persists in-progress work at the
exact point a clarifying question is needed, resumable by supplying the
user's reply, without requiring every caller of the primary
clarification mechanism to adopt it.

#### Scenario: A pause raised through the alternative component survives being resumed via a separate connection
- **WHEN** the alternative component pauses on a clarifying question,
  and the resume call is made through a connection or process
  independent of the one that raised the pause (sharing only the
  durable store, not in-memory state)
- **THEN** the resume correctly continues from the paused point using
  the durably persisted context, exactly as the primary mechanism's own
  durability guarantee provides

#### Scenario: A second missing piece after a resume pauses again rather than answering incompletely
- **WHEN** a reply resumes an alternative-component pause but the
  question is still missing another required piece
- **THEN** the component pauses again with a new clarifying question,
  rather than proceeding with an incomplete or guessed answer

#### Scenario: A non-resumable refusal is never paused or silently dropped
- **WHEN** the underlying pipeline raises a clarification that is not
  one of the pause-eligible kinds (a terminal refusal, not a missing
  detail)
- **THEN** the alternative component propagates it exactly as raised,
  without pausing or suppressing it

#### Scenario: The alternative component does not change the system's default behavior
- **WHEN** a request is handled through the system's normal request
  path, with the alternative component not enabled
- **THEN** the alternative component plays no part in it — the primary
  clarification-pause mechanism's behavior is unchanged

### Requirement: The alternative component can be enabled as the live request path's pause mechanism without corrupting the primary mechanism's own resume state
The system SHALL provide a configuration switch that, when enabled,
routes the three resumable clarification kinds (scope, year,
entity-ambiguity) through the alternative interrupt-primitive component
for real requests, while guaranteeing this does not set or clear any
state the primary mechanism uses for its own, independent resume
tracking.

#### Scenario: The switch is off by default
- **WHEN** the system is deployed without explicitly enabling the
  switch
- **THEN** every request is handled exactly as it would be with the
  alternative component absent entirely

#### Scenario: A pause raised through the live request path, with the switch on, is later resumed by a second request on the same conversation
- **WHEN** the switch is enabled and a request pauses on a resumable
  clarifying question
- **THEN** a later request on the same conversation supplying the
  reply is recognized as resuming that pause and is merged into the
  original question, without the caller needing to indicate explicitly
  that it is a resume

#### Scenario: Enabling the switch does not corrupt the primary mechanism's own resume tracking
- **WHEN** the switch is enabled and a clarifying question is paused
  through the alternative component
- **THEN** the primary mechanism's own resume-tracking state for that
  conversation is left exactly as it was before the pause — neither set
  nor read by the alternative component's pause/resume handling
