"""RAG / knowledge-base management endpoints — pgvector scheme KB."""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core import auth
from app.knowledge import kb_ingest, schema_metadata_ingest, sql_examples_ingest
from app.database import vectorstore
from app.core.config import settings
from app.api.deps import current_scope
from app.knowledge.scheme_registry import load_all as reload_scheme_registry
from app.knowledge.scheme_registry import sync_to_db as sync_scheme_registry_to_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rag", tags=["rag"])


async def _require_user(scope: auth.UserScope = Depends(current_scope)) -> auth.UserScope:
    """A real user when AUTH_ENABLED; anonymous is fine in local dev mode."""
    if settings.AUTH_ENABLED and scope.db_user_id is None:
        raise HTTPException(401, "authentication required")
    return scope


async def _require_admin(scope: auth.UserScope = Depends(_require_user)) -> auth.UserScope:
    """Admin (A01) when AUTH_ENABLED; unguarded in local dev mode."""
    if settings.AUTH_ENABLED and not scope.is_admin:
        raise HTTPException(403, "admin role required")
    return scope


@router.get("/status")
async def status(_: auth.UserScope = Depends(_require_user)):
    count = await vectorstore.collection_count()
    return {
        "collection": settings.RAG_KB_TABLE,
        "points": count if count >= 0 else 0,
        "present": count >= 0,
    }


@router.post("/reingest")
async def reingest(_: auth.UserScope = Depends(_require_admin)):
    """Force a full rebuild of the scheme KB collection from the data/ docs.
    Admin-only (A01) — it is an expensive, embed-heavy operation."""
    try:
        result = await kb_ingest.ingest_kb(force=True)
    except Exception as e:
        logger.exception("KB reingest failed")
        raise HTTPException(502, "reingest failed") from e
    return result


@router.post("/reingest-schema-metadata")
async def reingest_schema_metadata(schemes: list[str] | None = None,
                                   _: auth.UserScope = Depends(_require_admin)):
    """Force a full rebuild of the schema-metadata collection (scheme/table/
    column descriptions used by the schema-retrieval node) from each scheme's
    data/<scheme>/schema_metadata.yaml. Omit `schemes` to rebuild every scheme
    that currently has a source file. Admin-only (A01) — embed-heavy."""
    try:
        result = await schema_metadata_ingest.ingest_schema_metadata(schemes, force=True)
    except Exception as e:
        logger.exception("schema-metadata reingest failed")
        raise HTTPException(502, "reingest failed") from e
    return result


@router.post("/reingest-sql-examples")
async def reingest_sql_examples(schemes: list[str] | None = None,
                                _: auth.UserScope = Depends(_require_admin)):
    """Force a full rebuild of the SQL few-shot example collection (§5.10's
    vector-retrieved examples) from each scheme's data/<scheme>/*_few_shot.yaml.
    Omit `schemes` to rebuild every scheme that currently has a source file —
    this is also how a newly-added validated example in that file becomes
    retrievable, since there is no separate runtime "add one example" API.
    Admin-only (A01) — embed-heavy."""
    try:
        result = await sql_examples_ingest.ingest_sql_examples(schemes, force=True)
    except Exception as e:
        logger.exception("SQL-examples reingest failed")
        raise HTTPException(502, "reingest failed") from e
    return result


@router.post("/reload-scheme-registry")
async def reload_registry(_: auth.UserScope = Depends(_require_admin)):
    """Reload scheme_registry.yaml from disk without a redeploy — the manual-
    trigger precedent this endpoint follows (POST /api/rag/reingest above),
    not an automatic periodic refresh (none exists anywhere in this codebase;
    see design.md)."""
    reload_scheme_registry()
    # openspec/changes/multi-tenant-rls-scheme-scaleout: keeps app.schemes
    # (the DB-backed source of truth curated-data RLS policies read) in
    # sync on every reload — no tenant grants touched (default_tenant_id
    # omitted), so onboarding scheme #N doesn't implicitly grant it to
    # anyone; a separate admin action (POST /admin/tenants/{id}/schemes)
    # grants access.
    await sync_scheme_registry_to_db()
    return {"reloaded": True}
