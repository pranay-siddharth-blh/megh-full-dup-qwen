## Purpose

Defines the behavior a graph-based orchestration layer must provide when
it replaces the current linear pipeline as the execution substrate for
all 15 Section-5 nodes, across all four schemes this system serves,
without changing what any individual node returns to the user.

## ADDED Requirements

### Requirement: One orchestration graph serves every scheme
The system SHALL execute every question — regardless of which of the four
supported schemes (MGNREGA, PMAY-G, Focus Plus, CM Elevate) it concerns,
including a question that spans more than one scheme — through the same
graph definition. Scheme-specific behavior SHALL be expressed as data the
graph consults (per-scheme rules, thresholds, FK relationships), never as
a separate graph, a scheme-conditional graph topology, or duplicated node
logic per scheme.

#### Scenario: A single-scheme question and a cross-scheme question both complete
- **WHEN** a question resolves to exactly one scheme, and separately a
  question resolves to more than one scheme
- **THEN** both requests execute through the same graph structure and
  each returns a response, with no scheme-specific branch in the graph
  topology itself

### Requirement: Node decomposition covers every Section 5 responsibility
The graph SHALL express scope/scheme classification, query analysis, the
clarification gate, follow-up pause handling, defaults, entity
resolution, authorization, schema retrieval, join discovery, SQL
generation, SQL validation, execution, result findings, chart selection,
and response composition as distinct graph nodes connected by explicit
edges — not as an opaque single node wrapping the whole prior pipeline.

#### Scenario: A request that reaches the response stage passed through every applicable node
- **WHEN** a question does not pause for clarification and is not denied
  by authorization or PII checks
- **THEN** the graph's execution trace includes a distinct step for each
  of the 15 responsibilities that applies to that question, in the order
  the current pipeline already establishes

### Requirement: The response contract is unchanged for callers
For any given question, resolved entities, and authorization scope, the
graph-based execution SHALL produce a response with the same fields,
same field semantics, and same values as the pre-graph pipeline would
have produced for that same input — this is a change to how the response
is computed, not to what it contains.

#### Scenario: A previously-answered question produces an identical response after cutover
- **WHEN** a question that was answered correctly by the pre-graph
  pipeline is re-run against the graph-based pipeline with the same
  inputs
- **THEN** every field of the returned response (route, schemes, resolved
  entities, sql, rows, answer text, findings, chart_type, analysis)
  matches the pre-graph response

### Requirement: A clarification pause is durable across a worker or process boundary for every pause-eligible node
Any node that can pause the graph to ask the user a clarifying question
SHALL persist enough state, via the graph's checkpointer, that the pause
can be correctly resumed by a request handled on a different worker
process or after a process restart — not only by the same in-process
worker that raised it.

#### Scenario: A pause resumes on a different worker than the one that raised it
- **WHEN** a node raises a clarification pause on one worker process, and
  the user's reply is handled by a different worker process
- **THEN** the graph resumes from the correct paused node with the
  correct pending question state, producing the same result as if both
  requests had been handled by the same worker

#### Scenario: A pause resumes after a process restart
- **WHEN** a node raises a clarification pause and the serving process
  restarts before the user replies
- **THEN** a reply after the restart still resumes the correct paused
  node with its pending state intact

### Requirement: SQL repair is attempted at most once per request
When SQL validation fails, the graph SHALL regenerate and re-validate the
query exactly once before returning a failure to the user — matching the
existing one-repair-attempt limit — regardless of how many distinct
validation failure types a candidate query triggers.

#### Scenario: A second validation failure after one repair does not trigger a second repair
- **WHEN** a regenerated query fails validation again after the graph's
  one permitted repair attempt
- **THEN** the graph returns a failure response without generating a
  third SQL candidate

### Requirement: Authorization is re-evaluated on every SQL candidate that reaches execution
The graph SHALL re-run authorization against the specific SQL candidate
about to execute on every attempt, including a repaired candidate that
touches different tables, columns, or scope than the originally generated
query — an authorization pass on the first candidate SHALL NOT be treated
as clearing a later, different candidate.

#### Scenario: A repaired query that would fail authorization is denied, not executed
- **WHEN** SQL repair produces a candidate that touches data outside the
  requester's authorized scope
- **THEN** the graph denies the request at the authorization node without
  executing that candidate and without attempting a further repair

### Requirement: A hard denial short-circuits the graph before execution
When a node determines a request cannot proceed for a non-repairable
reason (authorization denial, a query blocked for referencing
disallowed/PII columns), the graph SHALL end the run at that node and
SHALL NOT reach the execution node for that request.

#### Scenario: A PII-blocked query never reaches execution
- **WHEN** SQL validation finds the candidate query references a
  blocklisted column or exposes a restricted container column
- **THEN** the graph returns a denial response without executing any
  query against the database
