"""
Schema-retrieval node (proposal §5.8 / capability `schema-retrieval`) —
semantic retrieval over embedded schema-metadata documents (see
app/schema_metadata_ingest.py), pre-filtered to the active scheme(s).

Supplements, does not replace, the existing classifier + schema_context.py
schema-context path (see design.md's "additive, not gating" decision): an
empty return here means the SQL-generation prompt looks exactly as it did
before this module existed. A scheme with no indexed schema-metadata rows,
or an embedding-service failure, both degrade to [] rather than raising or
blocking SQL generation.
"""
import logging

from app import llm, vectorstore
from app.config import settings

logger = logging.getLogger(__name__)


async def retrieve(question: str, scheme_ids: list[str]) -> list[dict]:
    """Top-N schema-metadata candidates for `question`. The pre-filter
    (vectorstore.search_schema_metadata's WHERE clause) restricts results to
    `scheme_ids` or documents tagged shared — an out-of-scope scheme's
    document is excluded before ranking, not merely out-ranked. Returns []
    — never raises — on an embedding failure or when no matching rows exist
    (including when the table itself doesn't exist yet for an un-indexed
    scheme)."""
    if not scheme_ids:
        return []
    try:
        vecs = await llm.call_embedding(question)
    except Exception as e:  # noqa: BLE001
        logger.warning("schema_retrieval.retrieve: embedding failed — %s", e)
        return []

    try:
        return await vectorstore.search_schema_metadata(
            vecs[0], top_k=settings.SCHEMA_RETRIEVAL_TOP_K, scheme_ids=scheme_ids)
    except Exception as e:  # noqa: BLE001 — e.g. table not yet created because
        # no scheme has been indexed yet; degrade to no extra context.
        logger.info("schema_retrieval.retrieve: search unavailable — %s", e)
        return []
