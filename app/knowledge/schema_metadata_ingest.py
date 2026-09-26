"""
Schema-metadata indexer for the schema-retrieval node (see openspec/changes/
phase-3-schema-retrieval-join-discovery). Embeds scheme/table/column-level
descriptions from each scheme's data/<scheme>/schema_metadata.yaml into the
megh_schema_metadata pgvector table.

Only a scheme that has a schema_metadata.yaml file contributes rows — this is
the pilot mechanism (CM Elevate, then Focus Plus for the onboarding proof),
not full coverage of all four schemes. A scheme with no file yet is silently
skipped, exactly as app/sql/schema_retrieval.py's retrieve() returns [] for a
scheme with no indexed rows (additive, never gating — see design.md).

Shape mirrors app/knowledge/kb_ingest.py's ingest_kb(): idempotent (skips a full
re-embed if the table already holds roughly the expected row count), force=True
always rebuilds.
"""
import logging
import uuid
from pathlib import Path

import yaml

from app.clients import llm
from app.database import vectorstore
from app.knowledge.scheme_registry import shared_scheme_ids

logger = logging.getLogger(__name__)

# app/knowledge/schema_metadata_ingest.py -> repo root -> data/
_DATA_PART = Path(__file__).resolve().parents[2] / "data"

_SCHEME_DIRS = {
    "MGNREGA": _DATA_PART / "mgnrega",
    "PMAY-G": _DATA_PART / "pmay",
    "Focus Plus": _DATA_PART / "focus_plus",
    "CM Elevate": _DATA_PART / "cm_elevate",
}
_METADATA_FILE = "schema_metadata.yaml"

# Every scheme this ingester knows how to look for a file under. Onboarding a
# scheme beyond these four means adding one entry here (see
# docs/scheme-onboarding.md) — nothing else in this module changes.
ALL_SCHEMES = list(_SCHEME_DIRS)


def _load_scheme_file(scheme: str) -> dict | None:
    path = _SCHEME_DIRS[scheme] / _METADATA_FILE
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _collect_points(schemes: list[str]) -> list[dict]:
    """[{scheme_id, granularity, ref, shared, content, metadata}, ...] for
    every scheme in `schemes` that has a schema_metadata.yaml today."""
    out: list[dict] = []
    shared_ids = set(shared_scheme_ids())
    for scheme in schemes:
        data = _load_scheme_file(scheme)
        if not data:
            logger.info("schema_metadata_ingest: no %s for %s — skipping",
                       _METADATA_FILE, scheme)
            continue
        shared = scheme in shared_ids

        s = data.get("scheme") or {}
        if s.get("content"):
            out.append({"scheme_id": scheme, "granularity": "scheme", "ref": scheme,
                       "shared": shared, "content": s["content"].strip(), "metadata": None})

        for t in data.get("tables", []) or []:
            if t.get("content") and t.get("ref"):
                out.append({"scheme_id": scheme, "granularity": "table", "ref": t["ref"],
                           "shared": shared, "content": t["content"].strip(), "metadata": None})

        for c in data.get("columns", []) or []:
            if c.get("content") and c.get("ref"):
                out.append({"scheme_id": scheme, "granularity": "column", "ref": c["ref"],
                           "shared": shared, "content": c["content"].strip(), "metadata": None})
    return out


async def ingest_schema_metadata(schemes: list[str] | None = None, force: bool = False) -> dict:
    """Embed and upsert schema_metadata.yaml content for `schemes` (default:
    every scheme this module knows about) into megh_schema_metadata."""
    schemes = schemes if schemes is not None else ALL_SCHEMES
    points_data = _collect_points(schemes)
    if not points_data:
        logger.warning("schema_metadata_ingest: no sources found for %s", schemes)
        return {"ingested": 0, "skipped": True, "reason": "no sources"}

    existing = await vectorstore.schema_metadata_count()
    if not force and existing >= int(len(points_data) * 0.9):
        logger.info("schema_metadata_ingest: table already holds %d rows (~%d expected) — skipping",
                    existing, len(points_data))
        return {"ingested": 0, "skipped": True, "points": existing}

    logger.info("schema_metadata_ingest: embedding %d documents from %s", len(points_data), schemes)
    vectors = await llm.call_embedding([p["content"] for p in points_data])
    if len(vectors) != len(points_data):
        raise RuntimeError(f"embedding count {len(vectors)} != doc count {len(points_data)}")

    await vectorstore.recreate_schema_metadata_table(dim=len(vectors[0]))
    points = [
        {"id": str(uuid.uuid4()), "vector": vec, "payload": p}
        for vec, p in zip(vectors, points_data)
    ]
    for i in range(0, len(points), 128):
        await vectorstore.upsert_schema_metadata(points[i:i + 128])

    logger.info("schema_metadata_ingest: upserted %d rows", len(points))
    return {"ingested": len(points), "skipped": False}
