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

from app import join_graph, llm, sql_join_validator, vectorstore
from app.config import settings

logger = logging.getLogger(__name__)


async def retrieve(question: str, scheme_ids: list[str]) -> list[dict]:
    """Top-N schema-metadata candidates for `question` (§5.8: pull a wider
    SCHEMA_RETRIEVAL_CANDIDATE_K pool, then optionally rerank down to
    SCHEMA_RETRIEVAL_TOP_K). The pre-filter (vectorstore.search_schema_metadata's
    WHERE clause) restricts results to `scheme_ids` or documents tagged shared
    — an out-of-scope scheme's document is excluded before ranking, not merely
    out-ranked. Returns [] — never raises — on an embedding failure or when no
    matching rows exist (including when the table itself doesn't exist yet for
    an un-indexed scheme)."""
    if not scheme_ids:
        return []
    try:
        vecs = await llm.call_embedding(question)
    except Exception as e:  # noqa: BLE001
        logger.warning("schema_retrieval.retrieve: embedding failed — %s", e)
        return []

    try:
        candidates = await vectorstore.search_schema_metadata(
            vecs[0], top_k=settings.SCHEMA_RETRIEVAL_CANDIDATE_K, scheme_ids=scheme_ids)
    except Exception as e:  # noqa: BLE001 — e.g. table not yet created because
        # no scheme has been indexed yet; degrade to no extra context.
        logger.info("schema_retrieval.retrieve: search unavailable — %s", e)
        return []
    if not candidates:
        return []

    top_k = settings.SCHEMA_RETRIEVAL_TOP_K
    # SCHEMA_RETRIEVAL_RERANKER_ENABLED — a dedicated flag, split off from
    # the RAG/KB path's since 2026-09-14 (app/config.py) once the two
    # corpora were found to behave differently. Kept OFF here on real
    # evidence, not just caution: live-tested against 5 real schema-metadata
    # queries across 4 schemes (openspec/changes/schema-retrieval-reranking/
    # proposal.md, "Reranker investigation" addendum), the reranker's top-1
    # disagreed with cosine top-1 in 5/5, including two clear degradations —
    # demoting the exact-match `data_verified` column below a generic
    # scheme-dimension table for a "pending verification" query, and
    # demoting the correct FACT table to dead last behind a low-relevance
    # status-key column for a "houses completed" query. This is a real,
    # repeatable finding for this content type, not an unverified caution —
    # do not flip this on for schema retrieval without re-testing after any
    # reranker/gateway change.
    if not settings.SCHEMA_RETRIEVAL_RERANKER_ENABLED:
        return candidates[:top_k]

    try:
        order = await llm.call_reranker(question, [c["content"] for c in candidates])
    except Exception as e:  # noqa: BLE001
        logger.warning("schema_retrieval.retrieve: reranker failed — %s", e)
        return candidates[:top_k]

    reranked = [candidates[idx] for idx, _score in order[:top_k] if 0 <= idx < len(candidates)]
    return reranked or candidates[:top_k]


def find_tables_outside_retrieved_set(sql: str, retrieved: list[dict]) -> list[str]:
    """§5.11's "tables must belong to the retrieved set" rule (baseline-audit
    finding 11) — every FACT table referenced in `sql` that isn't one of
    `retrieved`'s table-granularity candidates.

    Scoped to fact tables only, never dimensions: a legitimate query can join
    in a dimension (curated.dim_geography, curated.dim_year, ...) that
    schema_retrieval never had reason to surface as a top-K table candidate —
    the join graph already governs those via sql_join_validator, this rule's
    job is only to catch the model picking the wrong FACT table. Returns []
    (a true no-op, not a pass-by-default) whenever `retrieved` names no fact
    table at all — a scheme with no schema-metadata indexed yet (MGNREGA,
    PMAY-G as of Phase 3) has no retrieved set to check membership against,
    same "additive, never gating for an un-indexed scheme" stance
    retrieve() itself already takes."""
    retrieved_facts = {
        r["ref"].lower() for r in retrieved
        if r.get("granularity") == "table" and join_graph.is_fact(r["ref"])
    }
    if not retrieved_facts:
        return []
    referenced = sql_join_validator.referenced_tables(sql)
    return sorted(t for t in referenced if join_graph.is_fact(t) and t not in retrieved_facts)
