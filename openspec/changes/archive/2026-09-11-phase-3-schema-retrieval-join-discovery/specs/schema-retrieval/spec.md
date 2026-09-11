## Purpose

Supplements the existing classifier-scoped schema context with
semantic, embedding-based retrieval over scheme/table/column-level
descriptions, so fuzzy or ambiguous phrasing that the deterministic
classifier and hand-written schema blocks don't cleanly cover can still
surface the right tables/columns to the SQL generator.

## ADDED Requirements

### Requirement: Retrieval is pre-filtered by active scheme before ranking
Given a question and the classifier's active scheme(s), the system
SHALL restrict candidate schema-metadata documents to those tagged with
an active scheme or tagged `shared`, before similarity ranking is
applied — not merely rank all documents and rely on scores to exclude
out-of-scope ones.

#### Scenario: A pilot-scheme question retrieves only that scheme's tables
- **WHEN** a question classified to a single active scheme is retrieved
  against an index containing schema-metadata documents for that scheme
  and at least one other scheme
- **THEN** every returned candidate SHALL be tagged with the active
  scheme or tagged `shared`, and no document tagged with a different,
  inactive scheme SHALL appear in the results regardless of its
  similarity score

#### Scenario: A shared/cross-scheme dimension is retrieved regardless of active scheme
- **WHEN** a question classified to a single active scheme is retrieved
  against an index containing a document tagged `shared` (e.g. a
  geography or year dimension)
- **THEN** that shared document SHALL be eligible for retrieval
  alongside the active scheme's own documents

#### Scenario: The pre-filter excludes low-score out-of-scope documents, not just low-rank ones
- **WHEN** an out-of-scope scheme's document happens to embed closer to
  the question than some in-scope documents
- **THEN** it SHALL still be excluded by the pre-filter, confirming
  exclusion happens at the `WHERE` clause / pre-filter stage and not by
  a ranking cutoff alone

### Requirement: Retrieval is additive and never blocks SQL generation
The schema-retrieval step SHALL return an empty result (never raise, and
never itself refuse the request) when no schema-metadata documents are
indexed for the active scheme(s), or when the embedding call fails, and
the SQL-generation prompt SHALL be built exactly as it was before this
capability existed whenever retrieval returns empty.

#### Scenario: A scheme with no indexed schema metadata sees no behavior change
- **WHEN** a question is classified to a scheme that has not yet been
  indexed into the schema-metadata store
- **THEN** the SQL-generation prompt SHALL contain the same
  schema-context content it would have contained before this capability
  was added, with no retrieval block inserted

#### Scenario: An embedding-service failure degrades to no extra context, not an error
- **WHEN** the retrieval step's embedding call raises an exception
- **THEN** the pipeline SHALL proceed to SQL generation using the
  existing schema-context sources only, and SHALL NOT surface the
  embedding failure as a user-facing error

### Requirement: Scheme registry is looked up structurally, reloadable without redeploy
The system SHALL maintain a scheme registry (id, display name, aliases,
table list, shared flags) that is loaded at startup and can be reloaded
from its source file without a process restart, via an explicit
admin-triggered action — consistent with the existing manual-reload
precedent already in the codebase (`POST /api/rag/reingest`), not an
automatic periodic refresh.

#### Scenario: Adding a scheme's registry entry requires no code change
- **WHEN** a new scheme's entry is appended to the registry source file
  and a reload is triggered
- **THEN** the active-scheme lookup and shared-table flags for that
  scheme SHALL be available to the retrieval pre-filter without any
  change to pipeline or retrieval module code
