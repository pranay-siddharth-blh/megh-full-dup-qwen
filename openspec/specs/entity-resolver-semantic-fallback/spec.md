# entity-resolver-semantic-fallback Specification

## Purpose
Closes the documented gap between `app/entity_resolver.py`'s implemented
scope (stages 1/2/3/6 of the SME-authored 8-stage matching pipeline in
`data/*/*_entity_resolver.yaml`) and stage 7 (embedding fallback) and the
"did-you-mean" half of the `not_found` outcome, both specified in that YAML
but never built. Also adds a best-effort cache in front of the one
resolution path that hits a live database on every call (`resolve_village`).
## Requirements
### Requirement: Embedding fallback for closed-set dimensions
When `resolve_dimension` is called for `district`, `block`, `year`, or
`assembly_constituency` and RapidFuzz (stage 6) does not return a score of
at least 80 against any catalogue value, the system SHALL embed the user
text and the dimension's catalogue values (canonical + aliases) using the
local embedding model and SHALL resolve to the nearest neighbour when its
cosine similarity is at least 0.88 **and** it is the unique top candidate
for that dimension.

#### Scenario: Fuzzy match fails but a close embedding neighbour exists
- **WHEN** a user mention scores below 80 on RapidFuzz against every value
  in a dimension's catalogue, and exactly one catalogue value has cosine
  similarity ≥ 0.88 to the user text
- **THEN** `resolve_dimension` returns `status="resolved"` with that value's
  canonical form and a confidence derived from the embedding similarity

#### Scenario: Embedding neighbour is not unique
- **WHEN** two or more catalogue values in the same dimension tie (or are
  both within acceptance range) at the top embedding similarity
- **THEN** the system SHALL NOT resolve via the embedding stage and SHALL
  continue to `not_found` instead of guessing between them

#### Scenario: Embedding fallback does not apply to house_status or tranche_label
- **WHEN** resolving `house_status` or `tranche_label`
- **THEN** the system SHALL NOT apply the embedding fallback stage,
  regardless of RapidFuzz's outcome, since those dimensions use dedicated
  closed-set token matching with hand-curated deny lists that a generic
  similarity match would bypass

### Requirement: Blocked-pairs guard applies to the embedding stage
The system SHALL NOT resolve a user mention to a catalogue value via the
embedding stage if that (user-text-fold, value) pair — or the value's own
`never_fuzzy_to` list — appears in the scheme's blocked-matches set, using
the same blocked-pairs data RapidFuzz's stage already consults.

#### Scenario: A known confusable pair is not resolved via embedding
- **WHEN** the user text's folded form and a catalogue value's folded form
  are a listed blocked pair (e.g. `LASKEIN` / `THADLASKEIN`)
- **THEN** the embedding stage SHALL NOT resolve the user text to that
  value even if their embedding similarity clears the acceptance threshold

### Requirement: Did-you-mean suggestions on not_found
Whenever `resolve_dimension` returns `status="not_found"`, the system SHALL
populate `Resolved.candidates` with up to 5 suggested catalogue values,
drawn from whichever matching stage progressed furthest (RapidFuzz's own
extracted candidates when it ran; otherwise the embedding stage's nearest
neighbours).

#### Scenario: Not-found result carries suggestions
- **WHEN** a user mention resolves to `not_found` for a dimension whose
  catalogue is non-empty
- **THEN** the response's `candidates` list is non-empty (unless the
  catalogue has fewer than 5 values, in which case it contains all of them)
  and each entry names a real catalogue value

#### Scenario: Genuinely foreign input still yields no false suggestions above threshold
- **WHEN** the user text has no plausible relationship to any catalogue
  value in the dimension (e.g. a place name from outside the state)
- **THEN** `not_found` is still returned (the system SHALL NOT resolve or
  mark `ambiguous` purely to force a suggestion), but `candidates` MAY
  still list the nearest values purely as suggestions, clearly distinct
  from a resolved or ambiguous outcome

### Requirement: Cached village resolution
`resolve_village` SHALL consult a best-effort cache, keyed by the folded
user text plus any district/block scope, before querying
`curated.dim_geography`. A cache hit SHALL return the same `Resolved`
outcome as the equivalent live query would have. Cache unavailability
(unconfigured, unreachable, or erroring) SHALL degrade silently to running
the live query — it SHALL NOT raise or change the resolution outcome.

#### Scenario: Repeated village mention is served from cache
- **WHEN** the same village text and scope have been resolved within the
  cache's TTL window
- **THEN** the second call returns the same outcome without issuing the
  Postgres query that the first call issued

#### Scenario: Cache backend is unavailable
- **WHEN** the cache backend is unconfigured, unreachable, or returns an
  error
- **THEN** `resolve_village` SHALL fall back to querying
  `curated.dim_geography` directly and SHALL return the correct result,
  with no exception surfaced to the caller

