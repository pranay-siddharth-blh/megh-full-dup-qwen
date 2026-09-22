## ADDED Requirements

### Requirement: Few-shot examples are retrieved from a dedicated vector collection, with a safe fallback
The system SHALL retrieve the few-shot question→SQL examples shown to
the SQL-generation model by semantic (embedding) search over a
dedicated pgvector collection, scheme-prefiltered the same way
schema-retrieval is, and SHALL fall back to the pre-existing
token-overlap ranking over the static `*_few_shot.yaml` pool whenever
the vector path returns nothing — never raising, never blocking SQL
generation.

#### Scenario: A non-empty vector match is used directly
- **WHEN** `sql_examples_retrieval.retrieve(question, scheme_ids)`
  returns one or more examples
- **THEN** `prompt_builder._fewshot_block` SHALL render those examples
  in the prompt and SHALL NOT also call the token-overlap fallback

#### Scenario: An empty vector result falls back to token-overlap ranking
- **WHEN** `sql_examples_retrieval.retrieve` returns `[]` — because the
  `megh_sql_examples` table doesn't exist yet, holds no row for the
  active scheme(s), or the embedding call fails
- **THEN** `prompt_builder._fewshot_block` SHALL render examples from
  `annotations.few_shot_examples` exactly as it did before this
  capability existed

#### Scenario: An embedding-service failure never raises
- **WHEN** `llm.call_embedding` raises during
  `sql_examples_retrieval.retrieve`
- **THEN** `retrieve` SHALL return `[]` instead of propagating the
  exception

#### Scenario: A negative (unanswerable) example carries its refusal reason
- **WHEN** a retrieved row has `is_answerable = false`
- **THEN** the rendered example SHALL show the question as
  not-answerable together with its `reason`, and SHALL NOT show a `sql`
  value for it

### Requirement: The example pool starts from the curated use-case sheets and is re-embeddable on demand
The system SHALL populate the vector collection from each scheme's
existing SME-curated `*_few_shot.yaml` file (dropping any example marked
`status: RETIRED_v2.0`), and SHALL expose an admin-only endpoint that
re-embeds that source on request, so a newly-added validated example
becomes retrievable without a code change or redeploy.

#### Scenario: Ingest drops retired examples
- **WHEN** `sql_examples_ingest.ingest_sql_examples` runs for a scheme
  whose `*_few_shot.yaml` contains an example with
  `status: RETIRED_v2.0`
- **THEN** that example SHALL NOT be embedded or upserted into
  `megh_sql_examples`

#### Scenario: An admin can force a re-embed without a redeploy
- **WHEN** an admin calls `POST /api/rag/reingest-sql-examples`
- **THEN** the system SHALL re-read the current `*_few_shot.yaml` files
  and re-embed their contents into `megh_sql_examples`, making any
  newly-added example retrievable immediately

#### Scenario: A non-admin cannot trigger re-ingestion
- **WHEN** `AUTH_ENABLED` is true and the caller is not an admin (A01)
- **THEN** `POST /api/rag/reingest-sql-examples` SHALL respond 403 and
  SHALL NOT re-embed anything
