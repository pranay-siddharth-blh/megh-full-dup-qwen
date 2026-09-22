## ADDED Requirements

### Requirement: Retrieval widens to a candidate pool before an optional reranking stage
The system SHALL pull a wider candidate pool from the scheme-prefiltered
pgvector query than the number of results ultimately returned, and,
when reranking is enabled, SHALL rerank that pool with the configured
cross-encoder-equivalent model before truncating to the final returned
count — not rerank an already-narrow top-N.

#### Scenario: The candidate pool is wider than the returned count
- **WHEN** `schema_retrieval.retrieve()` is called
- **THEN** the underlying `vectorstore.search_schema_metadata` call
  SHALL request `SCHEMA_RETRIEVAL_CANDIDATE_K` rows (default 30), not
  `SCHEMA_RETRIEVAL_TOP_K`

#### Scenario: Reranking disabled returns the widened pool's cosine order, truncated
- **WHEN** `RERANKER_ENABLED` is false
- **THEN** `retrieve()` SHALL return the first `SCHEMA_RETRIEVAL_TOP_K`
  candidates from the pgvector cosine order, unchanged from today's
  ranking behavior other than being drawn from the wider pool

#### Scenario: Reranking enabled reorders the pool before truncating
- **WHEN** `RERANKER_ENABLED` is true
- **THEN** `retrieve()` SHALL call the configured reranker with the
  question and the full candidate pool's content, and SHALL return the
  top `SCHEMA_RETRIEVAL_TOP_K` candidates in the reranker's order

#### Scenario: A reranker failure degrades to the pre-rerank cosine order, not an error
- **WHEN** the reranker call raises an exception
- **THEN** `retrieve()` SHALL return the first `SCHEMA_RETRIEVAL_TOP_K`
  candidates from the pre-rerank cosine order instead of raising or
  returning an empty result
