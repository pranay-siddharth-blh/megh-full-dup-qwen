"""
SQL few-shot retrieval node (proposal §5.10 / capability `sql-generation`)
— semantic retrieval over the megh_sql_examples pgvector collection
populated by app/knowledge/sql_examples_ingest.py, mirroring app/sql/schema_retrieval.py's
shape for the schema-metadata collection (same embed -> pgvector
scheme-filtered-search pattern, same "never raises, degrades to []"
contract).

app/sql/prompt_builder.py's _fewshot_block() tries this first and falls back to
app/knowledge/annotations.py's token-overlap ranking over the static YAML pool when
this returns [] — table not yet seeded for the active scheme(s), or an
embedding-service failure, same additive-never-gating stance
app/sql/schema_retrieval.py documents for its own collection. No reranking
stage: unlike §5.8, the spec doesn't call for one here ("a handful of
few-shot examples"), so a single cosine top-K is the whole shape.
"""
import logging

from app.clients import llm
from app.database import vectorstore
from app.core.config import settings

logger = logging.getLogger(__name__)


async def retrieve(question: str, scheme_ids: list[str]) -> list[dict]:
    """Up to SQL_EXAMPLES_TOP_K examples, pre-filtered to scheme_ids
    (a single scheme_id = ANY(...) query — best cosine match first across
    all given schemes together, not per-scheme). Each item:
    {score, scheme_id, question, sql, is_answerable, reason}. Returns []
    (never raises) when scheme_ids is empty, the embedding call fails, or
    the search fails (e.g. megh_sql_examples doesn't exist yet because no
    scheme has been ingested)."""
    if not scheme_ids:
        return []
    try:
        vecs = await llm.call_embedding(question)
    except Exception as e:  # noqa: BLE001
        logger.warning("sql_examples_retrieval.retrieve: embedding failed — %s", e)
        return []

    try:
        return await vectorstore.search_sql_examples(
            vecs[0], top_k=settings.SQL_EXAMPLES_TOP_K, scheme_ids=scheme_ids)
    except Exception as e:  # noqa: BLE001 — e.g. table not yet created because
        # no scheme has been ingested yet; degrade to no vector examples.
        logger.info("sql_examples_retrieval.retrieve: search unavailable — %s", e)
        return []
