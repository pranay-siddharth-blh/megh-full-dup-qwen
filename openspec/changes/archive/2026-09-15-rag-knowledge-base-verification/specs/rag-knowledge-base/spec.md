## Purpose

Answers general scheme-knowledge questions ("what is X", "who is
eligible for Y") from SME-written narrative reference docs and
supplementary scraped background, never by generating SQL — a
distinct retrieval path from `schema-retrieval` (table/column
descriptions for the SQL generator), documented retroactively here
since it predates this repo's openspec adoption.

## ADDED Requirements

### Requirement: Retrieval is scheme-scoped when a scheme is given
Given a question and an optional active scheme, the system SHALL
restrict candidate knowledge-base chunks to that scheme when one is
given, and SHALL search the whole knowledge base when none is given.

#### Scenario: A scheme-scoped question returns that scheme's own chunks
- **WHEN** `retrieve(question, scheme="PMAY-G")` is called
- **THEN** every returned chunk SHALL be tagged with scheme `PMAY-G`

### Requirement: PMAY-Gramin and PMAY-Urban content are never conflated
Given PMAY source documents contain both Gramin (rural, in scope) and
Urban (out of scope) content under a shared filename-derived scheme
tag, the system SHALL separate Urban-flavored subsections into a
distinct `PMAY-U` tag at ingest time, so a `PMAY-G`-scoped retrieval
never surfaces Urban content.

#### Scenario: A PMAY-G-scoped query about an Urban-adjacent topic excludes Urban chunks
- **WHEN** a question phrased around PMAY Urban content is retrieved
  with `scheme="PMAY-G"`
- **THEN** no returned chunk SHALL be tagged `PMAY-U`

### Requirement: Response confidence is tiered by top-chunk score
Given a retrieved chunk set, the system SHALL branch on the top
chunk's score: at or above `RAG_HIGH_CONFIDENCE`, return that chunk
verbatim with no composition call; at or above `RAG_MEDIUM_CONFIDENCE`
but below high, compose an answer from the kept chunks via the
response-composer model; below `RAG_MEDIUM_CONFIDENCE`, return no
answer.

#### Scenario: A high-scoring top chunk returns verbatim, no LLM call
- **WHEN** `answer_from_kb()`'s top retrieved chunk scores at or above
  `RAG_HIGH_CONFIDENCE`
- **THEN** the returned answer SHALL be that chunk's own text (heading
  stripped), and no response-composer call SHALL be made

#### Scenario: A below-floor top score returns no answer
- **WHEN** every retrieved chunk (or an empty retrieval) scores below
  `RAG_MEDIUM_CONFIDENCE`
- **THEN** `answer_from_kb()` SHALL return `None`, signaling the
  pipeline to fall back to its standard "not in the reference
  material" message

### Requirement: Retrieval and answer composition are additive and never raise
The knowledge-base path SHALL return `[]`/`None` (never raise) when
the embedding call fails, when retrieval is empty, or when the
composer call fails after its retry — the pipeline SHALL proceed to
its standard fallback instead of surfacing an internal error.

#### Scenario: An embedding-service failure degrades to no answer, not an error
- **WHEN** `retrieve()`'s embedding call raises an exception
- **THEN** `retrieve()` SHALL return `[]` rather than raising
