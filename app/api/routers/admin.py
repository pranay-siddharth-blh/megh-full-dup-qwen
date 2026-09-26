"""
Admin API — tenant + user management, login events, officer conversations,
and the query audit trail. All routes require an admin JWT
(admin / tenant_admin / super_admin). tenant_admin sees only their own tenant;
super_admin may pass ?tenant_id= to scope to any tenant (or omit for all).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.database import appdb
from app.core import auth
from app.conversation import conversation_store
from app.sql import fk_miner, join_graph, schema_introspect
from app.api.deps import require_admin, require_super

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _tenant_filter(scope: auth.UserScope, tenant_id: int | None) -> int | None:
    """What tenant_id to filter reads by. tenant_admin is pinned to their own;
    super_admin gets what they ask for (None = all tenants)."""
    if scope.cross_tenant:
        return tenant_id
    return scope.tenant_id


# ── tenants (super_admin) ────────────────────────────────────────────────
class TenantBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)


@router.get("/tenants")
async def list_tenants(scope: auth.UserScope = Depends(require_admin)):
    tenants = await appdb.list_tenants()
    if not scope.cross_tenant:
        tenants = [t for t in tenants if t["tenant_id"] == scope.tenant_id]
    return {"tenants": tenants}


@router.post("/tenants")
async def create_tenant(body: TenantBody, scope: auth.UserScope = Depends(require_super)):
    try:
        return {"tenant": await appdb.create_tenant(body.code, body.name)}
    except Exception as e:  # noqa: BLE001
        logger.warning("create_tenant failed: %s", e)
        raise HTTPException(422, "could not create tenant (code may already exist)") from e


# ── scheme entitlements (openspec/changes/multi-tenant-rls-scheme-scaleout) ─
# The DB-backed replacement for auth.ROLE_PERMISSIONS' hardcoded scheme
# allowlists — which schemes a tenant's users may query, enforced (once
# TENANT_SCHEME_RLS_ENABLED is on) both here at the app layer
# (auth.scope_from_user) and independently at the DB layer via curated-data
# RLS (deploy/sql/03_tenant_scheme_rls.sql). super_admin only: granting a
# tenant access to a scheme is a platform-level administrative act, not
# something a tenant_admin does for their own tenant.
@router.get("/schemes")
async def list_schemes(include_inactive: bool = False,
                       _: auth.UserScope = Depends(require_admin)):
    return {"schemes": await appdb.list_schemes(include_inactive)}


@router.get("/tenants/{tenant_id}/schemes")
async def tenant_schemes(tenant_id: int, scope: auth.UserScope = Depends(require_admin)):
    if not scope.cross_tenant and tenant_id != scope.tenant_id:
        raise HTTPException(403, "tenant belongs to another tenant")
    return {
        "granted": await appdb.list_tenant_schemes(tenant_id),
        "effective": await appdb.tenant_effective_schemes(tenant_id),
    }


@router.post("/tenants/{tenant_id}/schemes/{scheme_id}")
async def grant_tenant_scheme(tenant_id: int, scheme_id: str,
                              scope: auth.UserScope = Depends(require_super)):
    if not await appdb.get_tenant(tenant_id):
        raise HTTPException(404, "no such tenant")
    known = {s["scheme_id"] for s in await appdb.list_schemes(include_inactive=True)}
    if scheme_id not in known:
        raise HTTPException(422, f"unknown scheme_id {scheme_id!r} (not in app.schemes)")
    await appdb.grant_tenant_scheme(tenant_id, scheme_id, granted_by=scope.db_user_id)
    return {"granted": await appdb.list_tenant_schemes(tenant_id)}


@router.delete("/tenants/{tenant_id}/schemes/{scheme_id}")
async def revoke_tenant_scheme(tenant_id: int, scheme_id: str,
                               _: auth.UserScope = Depends(require_super)):
    await appdb.revoke_tenant_scheme(tenant_id, scheme_id)
    return {"granted": await appdb.list_tenant_schemes(tenant_id)}


# ── users ───────────────────────────────────────────────────────────────
class NewUser(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    password: str = Field(min_length=8, max_length=256)
    name: str | None = Field(default=None, max_length=200)
    role: str = Field(min_length=1, max_length=40)
    tenant_id: int | None = None          # super_admin only; else caller's tenant
    districts: list[str] | None = Field(default=None, max_length=64)
    blocks: list[str] | None = Field(default=None, max_length=256)
    schemes: list[str] | None = Field(default=None, max_length=16)
    granularity_cap: str | None = Field(default=None, max_length=40)


class UpdateUser(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=40)
    districts: list[str] | None = Field(default=None, max_length=64)
    blocks: list[str] | None = Field(default=None, max_length=256)
    schemes: list[str] | None = Field(default=None, max_length=16)
    granularity_cap: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


@router.get("/roles")
async def roles(_: auth.UserScope = Depends(require_admin)):
    # auth.ROLE_PERMISSIONS no longer carries a "schemes" key per role (that
    # was the same 4-scheme literal hand-typed 8 times — removed
    # 2026-09-18, see auth._role_scheme_cap's docstring) — resolve each
    # role's effective cap dynamically here instead of dumping the now-
    # sparse dict raw, so this endpoint's response shape is unchanged.
    return {"roles": {
        role: {**perms, "schemes": auth._role_scheme_cap(perms)}
        for role, perms in auth.ROLE_PERMISSIONS.items()
    }}


@router.get("/users")
async def list_users(tenant_id: int | None = None,
                     scope: auth.UserScope = Depends(require_admin)):
    return {"users": await appdb.list_users(_tenant_filter(scope, tenant_id))}


@router.get("/users/{user_id}")
async def get_user(user_id: int, scope: auth.UserScope = Depends(require_admin)):
    rec = await appdb.get_user(user_id)
    if not rec:
        raise HTTPException(404, "no such user")
    if not scope.cross_tenant and rec["tenant_id"] != scope.tenant_id:
        raise HTTPException(403, "user belongs to another tenant")
    return {"user": rec, "effective_scope": auth.scope_from_user(rec).__dict__}


@router.post("/users")
async def create_user(body: NewUser, scope: auth.UserScope = Depends(require_admin)):
    if body.role not in auth.ROLE_PERMISSIONS:
        raise HTTPException(422, f"role must be one of {sorted(auth.ROLE_PERMISSIONS)}")
    if body.role in ("super_admin",) and not scope.cross_tenant:
        raise HTTPException(403, "only super_admin can create super_admin")
    tenant_id = body.tenant_id if scope.cross_tenant and body.tenant_id else scope.tenant_id
    try:
        rec = await appdb.create_user(
            tenant_id=tenant_id, username=body.username, password=body.password,
            name=body.name, role=body.role, districts=body.districts, blocks=body.blocks,
            schemes=body.schemes, granularity_cap=body.granularity_cap,
            created_by=scope.username,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("create_user failed: %s", e)
        raise HTTPException(422, "could not create user (username may already exist)") from e
    return {"user": rec, "effective_scope": auth.scope_from_user(rec).__dict__}


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UpdateUser,
                      scope: auth.UserScope = Depends(require_admin)):
    rec = await appdb.get_user(user_id)
    if not rec:
        raise HTTPException(404, "no such user")
    if not scope.cross_tenant and rec["tenant_id"] != scope.tenant_id:
        raise HTTPException(403, "user belongs to another tenant")
    if body.role and body.role not in auth.ROLE_PERMISSIONS:
        raise HTTPException(422, "bad role")
    updated = await appdb.update_user(user_id, **body.model_dump(exclude_none=True))
    return {"user": updated}


@router.delete("/users/{user_id}")
async def deactivate_user(user_id: int, hard: bool = False,
                          scope: auth.UserScope = Depends(require_admin)):
    """Soft-deactivate by default (is_active = FALSE). Pass ?hard=true to
    permanently delete the row — super_admin only, and never your own account."""
    rec = await appdb.get_user(user_id)
    if not rec:
        raise HTTPException(404, "no such user")
    if not scope.cross_tenant and rec["tenant_id"] != scope.tenant_id:
        raise HTTPException(403, "user belongs to another tenant")
    if scope.db_user_id == user_id:
        raise HTTPException(403, "you cannot delete your own account")
    if hard:
        if not scope.cross_tenant:
            raise HTTPException(403, "only super_admin can permanently delete a user")
        await appdb.purge_user(user_id)
        return {"deleted": user_id}
    await appdb.delete_user(user_id)
    return {"deactivated": user_id}


# ── login events ────────────────────────────────────────────────────────
@router.get("/logins")
async def logins(tenant_id: int | None = None, limit: int = Query(200, ge=1, le=1000),
                 scope: auth.UserScope = Depends(require_admin)):
    return {"events": await appdb.list_login_events(_tenant_filter(scope, tenant_id), limit)}


# ── officer conversations ───────────────────────────────────────────────
@router.get("/conversations")
async def conversations(tenant_id: int | None = None, user_id: int | None = None,
                        limit: int = Query(100, ge=1, le=1000),
                        scope: auth.UserScope = Depends(require_admin)):
    return {"conversations": await conversation_store.admin_list_conversations(
        tenant_id=_tenant_filter(scope, tenant_id), user_id=user_id, limit=limit)}


@router.get("/conversations/{conv_id}")
async def conversation_detail(conv_id: int, scope: auth.UserScope = Depends(require_admin)):
    turns = await conversation_store.get_conversation_turns(conv_id=conv_id, limit=500)
    if turns and not scope.cross_tenant and turns[0]["conv_id"]:
        # tenant check via the first turn's tenant
        t0 = await appdb.db.fetchrow(
            "SELECT tenant_id FROM app.conversation_turns WHERE conv_id = $1 LIMIT 1", [conv_id])
        if t0 and t0["tenant_id"] != scope.tenant_id:
            raise HTTPException(403, "conversation belongs to another tenant")
    return {"conv_id": conv_id, "turns": turns}


# ── audit ──────────────────────────────────────────────────────────────
@router.get("/audit")
async def audit(tenant_id: int | None = None, user_id: int | None = None,
                denied_only: bool = False, limit: int = Query(200, ge=1, le=2000),
                scope: auth.UserScope = Depends(require_admin)):
    recs = await conversation_store.admin_list_audit(
        tenant_id=_tenant_filter(scope, tenant_id), user_id=user_id,
        denied_only=denied_only, limit=limit)
    return {"count": len(recs), "records": recs}


@router.get("/failures")
async def failures(day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                   tenant_id: int | None = None, limit: int = Query(500, ge=1, le=2000),
                   scope: auth.UserScope = Depends(require_admin)):
    """Today's (or `day`'s) failed turns: zero rows, repair used, fallback
    reply, clarification asked more than twice in one conversation — each one
    a candidate eval case (tests/eval/export_failures.py)."""
    from datetime import date
    from app.conversation import failures as _f

    day = day or date.today().isoformat()
    recs = await conversation_store.admin_failures(
        tenant_id=_tenant_filter(scope, tenant_id), day=day, limit=limit)
    counts = {r: sum(1 for x in recs if r in (x.get("reasons") or [])) for r in _f.REASONS}
    return {"day": day, "count": len(recs), "counts": counts, "records": recs}


@router.get("/stats")
async def stats(tenant_id: int | None = None, scope: auth.UserScope = Depends(require_admin)):
    return await conversation_store.tenant_stats(_tenant_filter(scope, tenant_id))


@router.get("/schema")
async def schema(_: auth.UserScope = Depends(require_admin)):
    return schema_introspect.snapshot()


# ── join discovery: query-log FK mining (§5.9, advisory only) ─────────────
@router.get("/fk-mining")
async def fk_mining(scheme: str | None = None,
                    min_occurrences: int = Query(2, ge=1, le=1000),
                    log_limit: int = Query(5000, ge=1, le=50000),
                    _: auth.UserScope = Depends(require_admin)):
    """Mines app.query_audit for JOIN-ON patterns between known tables with
    no declared edge between them (see app/sql/fk_miner.py). Read-only report
    for a human SME to review — never writes to the live join graph or any
    foreign_key_augmentation.yaml."""
    candidates = await fk_miner.mine_implicit_fks(
        log_limit=log_limit, min_occurrences=min_occurrences,
        schemes=[scheme] if scheme else None,
    )
    return {"count": len(candidates), "candidates": [c._asdict() for c in candidates]}


@router.post("/reload-join-graph")
async def reload_join_graph(_: auth.UserScope = Depends(require_admin)):
    """openspec/changes/multi-tenant-rls-scheme-scaleout (scheme-onboarding
    scale-out): rebuilds the in-memory FK graph
    (app/sql/join_graph.py::build(force=True)) from the curated
    foreign_key_augmentation.yaml files + live_fks() without a process
    restart — mirrors the existing POST /api/rag/reload-scheme-registry
    manual-trigger precedent. Before this endpoint existed, onboarding a
    new scheme's join edges required a full service restart
    (`app/main.py`'s lifespan only calls `join_graph.build()` once, at
    startup) — a real operational cost once scheme count grows well past
    4. Admin-only: rebuilding is cheap (in-memory YAML + cached live_fks()
    re-read, no DB round-trip) but the graph is shared, request-serving
    state."""
    join_graph.build(force=True)
    return {"reloaded": True, **join_graph.snapshot()}
