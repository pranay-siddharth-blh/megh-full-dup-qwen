"""
Shared FastAPI dependencies — request identity and role gates.

  current_scope   -> UserScope for the bearer token (or anonymous in dev mode)
  require_user    -> same, but 401 if there is no valid token
  require_admin   -> require_user + role must be admin/tenant_admin/super_admin
  require_super   -> super_admin only
"""
import logging

from fastapi import Depends, Header, HTTPException

from app.database import appdb
from app.core import auth
from app.database import db
from app.core import security
from app.core.config import settings

logger = logging.getLogger(__name__)


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def current_scope(authorization: str | None = Header(default=None)) -> auth.UserScope:
    """Never raises — returns an anonymous scope when auth is off and no token is
    given. Endpoints that must have a real user depend on require_user instead."""
    token = _bearer(authorization)
    if not token:
        if settings.AUTH_ENABLED:
            # Anonymous is allowed to reach current_scope; require_user is the gate.
            return auth.anonymous_scope()
        return auth.anonymous_scope()
    try:
        claims = security.decode_token(token)
    except security.JWTError as e:
        raise HTTPException(401, f"invalid token: {e}") from e
    rec = await appdb.get_user(int(claims["sub"]))
    if not rec or not rec.get("is_active"):
        raise HTTPException(401, "user not found or inactive")
    # openspec/changes/multi-tenant-rls-scheme-scaleout: resolve the
    # tenant's DB-granted schemes so scope_from_user can intersect them
    # with the role/user-pin ceiling. Skipped entirely when the flag is
    # off (avoids an extra query on every request for a value nothing
    # would use) or when the user record has no tenant_id.
    tenant_schemes = None
    if settings.TENANT_SCHEME_RLS_ENABLED and rec.get("tenant_id") is not None:
        tenant_schemes = await appdb.tenant_effective_schemes(rec["tenant_id"])
    return auth.scope_from_user(rec, tenant_schemes=tenant_schemes)


async def tenant_scoped(scope: auth.UserScope = Depends(current_scope)):
    """openspec/changes/multi-tenant-rls-scheme-scaleout: sets this
    request's RLS tenant context (app.database.db.set_tenant_context) for the
    duration of the request, resetting it afterward — a `yield`
    dependency, so FastAPI runs the reset after the route handler
    returns (including on an exception). `bypass` is only ever true for
    `super_admin` (server-resolved from `scope.role`, never a
    client-suppliable value); `tenant_admin` stays tenant-scoped on
    curated data by design (see proposal.md's "Why" section on the
    previous all-query-checks bypass).

    This is the single point every protected route needs, instead of each
    router file wiring its own explicit set/reset (the original approach
    in app/api/routers/query.py, before this existed — easy to miss a router,
    which is exactly how app.users/conversations/audit endpoints
    (app/api/routers/admin.py, app/api/routers/history.py) ended up unwired long
    enough that Section B of deploy/sql/03_tenant_scheme_rls.sql had to be
    left disabled). `current_scope` itself is deliberately NOT changed to
    do this directly — it's called outside the FastAPI dependency system
    in app/main.py's health check, where a generator/yield function
    can't be `await`ed directly.

    A no-op when TENANT_SCHEME_RLS_ENABLED is off — `set_tenant_context`
    already returns a no-op token in that case, so this adds no behavior
    change to any existing route at the flag's default."""
    token = db.set_tenant_context(scope.tenant_id, bypass=(scope.role == "super_admin"))
    try:
        yield scope
    finally:
        db.reset_tenant_context(token)


async def require_user(scope: auth.UserScope = Depends(tenant_scoped)) -> auth.UserScope:
    if scope.db_user_id is None:
        raise HTTPException(401, "authentication required")
    return scope


async def require_admin(scope: auth.UserScope = Depends(require_user)) -> auth.UserScope:
    if not scope.is_admin:
        raise HTTPException(403, "admin role required")
    return scope


async def require_super(scope: auth.UserScope = Depends(require_user)) -> auth.UserScope:
    if not scope.cross_tenant:
        raise HTTPException(403, "super_admin role required")
    return scope
