"""
SQL few-shot example indexer (proposal §5.10 / capability `sql-generation`)
— embeds each scheme's already-curated question/SQL pairs from
data/<scheme>/*_few_shot.yaml ("the use-case sheets" the spec's example
pool starts from) into the megh_sql_examples pgvector table, so
app/sql/sql_examples_retrieval.py can pull the on-topic subset semantically
instead of app/knowledge/annotations.py's token-overlap fallback.

Mirrors app/knowledge/schema_metadata_ingest.py's shape (own source-file map,
idempotent row-count skip, force=True always rebuilds) and deliberately
defines its own copy of the scheme->file mapping rather than importing
app/knowledge/annotations.py's — same precedent schema_metadata_ingest.py already
set for a different source file — so ingest can run standalone without
depending on load_annotations() having run first.

status: RETIRED_v2.0 examples are dropped, the same filter
app/knowledge/annotations.py applies at runtime load — a retired example must not
resurface via vector search just because token-overlap ranking no longer
sees it. status: UNANSWERABLE (negative) examples embed with
is_answerable=False and their `reason`, sql=None — matching
app/database/vectorstore.py's megh_sql_examples schema, which already has both
columns for exactly this shape.

Growing the pool ("new validated queries are added" per the spec) today
means: add the example to the scheme's *_few_shot.yaml (the existing
SME-reviewed artifact), then POST /api/rag/reingest-sql-examples to
re-embed. There is no separate runtime "add one example" API — reusing
the existing file-review workflow keeps one place SMEs edit, not two.
"""
import logging
import uuid
from pathlib import Path

import yaml

from app.clients import llm
from app.database import vectorstore

logger = logging.getLogger(__name__)

# app/knowledge/sql_examples_ingest.py -> repo root -> data/
_DATA_PART = Path(__file__).resolve().parents[2] / "data"

_SCHEME_DIRS = {
    "MGNREGA": _DATA_PART / "mgnrega",
    "PMAY-G": _DATA_PART / "pmay",
    "Focus Plus": _DATA_PART / "focus_plus",
    "CM Elevate": _DATA_PART / "cm_elevate",
}
_FEW_SHOT_FILE = {
    "MGNREGA": "few_shot.yaml",
    "PMAY-G": "pmay_few_shot.yaml",
    "Focus Plus": "focusplus_few_shot.yaml",
    "CM Elevate": "cmelevate_few_shot.yaml",
}

ALL_SCHEMES = list(_SCHEME_DIRS)


def _load_scheme_file(scheme: str) -> list[dict]:
    path = _SCHEME_DIRS[scheme] / _FEW_SHOT_FILE[scheme]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    examples = (data or {}).get("sql_generation_examples", []) or []
    return [e for e in examples if e.get("status") != "RETIRED_v2.0"]


def _collect_points(schemes: list[str]) -> list[dict]:
    """[{scheme_id, question, sql, is_answerable, reason, content}, ...]
    for every scheme in `schemes` that has a *_few_shot.yaml today. Only
    the question text is embedded (`content`) — the SQL/reason are payload,
    not part of the similarity search."""
    out: list[dict] = []
    for scheme in schemes:
        for ex in _load_scheme_file(scheme):
            question = (ex.get("question") or "").strip()
            if not question:
                continue
            is_unanswerable = ex.get("status") == "UNANSWERABLE"
            if is_unanswerable:
                sql = None
                reason = " ".join((ex.get("reason") or "").split())
            else:
                sql = (ex.get("sql") or "").strip()
                reason = None
                if not sql:
                    continue  # neither a worked example nor a negative one — nothing to index
            out.append({
                "scheme_id": scheme,
                "question": question,
                "sql": sql,
                "is_answerable": not is_unanswerable,
                "reason": reason,
                "content": question,
            })
    return out


async def ingest_sql_examples(schemes: list[str] | None = None, force: bool = False) -> dict:
    """Embed and upsert *_few_shot.yaml content for `schemes` (default:
    every scheme this module knows about) into megh_sql_examples."""
    schemes = schemes if schemes is not None else ALL_SCHEMES
    points_data = _collect_points(schemes)
    if not points_data:
        logger.warning("sql_examples_ingest: no sources found for %s", schemes)
        return {"ingested": 0, "skipped": True, "reason": "no sources"}

    existing = await vectorstore.sql_examples_count()
    if not force and existing >= int(len(points_data) * 0.9):
        logger.info("sql_examples_ingest: table already holds %d rows (~%d expected) — skipping",
                    existing, len(points_data))
        return {"ingested": 0, "skipped": True, "points": existing}

    logger.info("sql_examples_ingest: embedding %d examples from %s", len(points_data), schemes)
    vectors = await llm.call_embedding([p["content"] for p in points_data])
    if len(vectors) != len(points_data):
        raise RuntimeError(f"embedding count {len(vectors)} != example count {len(points_data)}")

    await vectorstore.recreate_sql_examples_table(dim=len(vectors[0]))
    points = [
        {"id": str(uuid.uuid4()), "vector": vec, "payload": p}
        for vec, p in zip(vectors, points_data)
    ]
    for i in range(0, len(points), 128):
        await vectorstore.upsert_sql_examples(points[i:i + 128])

    logger.info("sql_examples_ingest: upserted %d rows", len(points))
    return {"ingested": len(points), "skipped": False}
