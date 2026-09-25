"""
openspec/changes/multi-tenant-rls-scheme-scaleout — pure-Python checks for
the tenant<->scheme entitlement mechanism: auth.scope_from_user's tenant-
grant intersection, cache_fingerprint's tenant-aware bucketing, and
app.database.db's tenant-context contextvar plumbing.

Runs without a DB (same posture as test_security.py) — the actual RLS
enforcement (deploy/sql/03_tenant_scheme_rls.sql) and app.schemes/
app.tenant_schemes CRUD (app/database/appdb.py) need a live Postgres and are covered
by tasks.md group 3.4 (disposable local Postgres), not here.

Plain script (no pytest in the venv) — `python tests/unit/test_tenant_scheme_entitlements.py`,
exit code 0 = all pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.update(
    ENV="dev",
    AUTH_ENABLED="true",
    DATABASE_URL="postgresql://u:p@127.0.0.1:5/none",
)

from app.core import auth  # noqa: E402
from app.database import db
from app.knowledge import scheme_registry
from app.core.config import settings  # noqa: E402

# scope_from_user()'s default scheme cap is resolved dynamically via
# scheme_registry (2026-09-18 — see auth._role_scheme_cap's docstring).
# The real app always calls this at startup before serving any request;
# this standalone test needs the same call, or the role-cap fallback this
# file tests comes back empty instead of the real 4-scheme registry.
scheme_registry.load_all()

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_USER_REC = {
    "user_id": 1, "tenant_id": 7, "username": "d1", "role": "district_officer",
    "districts": ["EAST KHASI HILLS"], "blocks": [], "schemes": None,
    "granularity_cap": None, "name": "D1",
}

print("1. scope_from_user — flag OFF: tenant_schemes must never affect result")
settings.TENANT_SCHEME_RLS_ENABLED = False
scope_off_no_grants = auth.scope_from_user(_USER_REC, tenant_schemes=None)
scope_off_with_grants = auth.scope_from_user(_USER_REC, tenant_schemes=["MGNREGA"])
check("flag off, tenant_schemes=None -> full role-cap scheme list",
      sorted(scope_off_no_grants.schemes) == sorted(["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]))
check("flag off, tenant_schemes given -> IGNORED, same as tenant_schemes=None",
      sorted(scope_off_with_grants.schemes) == sorted(scope_off_no_grants.schemes),
      f"got {scope_off_with_grants.schemes}")

print("2. scope_from_user — flag ON: tenant grant narrows the role cap")
settings.TENANT_SCHEME_RLS_ENABLED = True
try:
    scope_on_none = auth.scope_from_user(_USER_REC, tenant_schemes=None)
    check("flag on, tenant_schemes=None -> unresolved, falls back to role cap (fail-open by design: "
          "None means \"not resolved\", not \"resolved to zero\" — see app/api/deps.py)",
          sorted(scope_on_none.schemes) == sorted(["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"]))

    scope_on_one = auth.scope_from_user(_USER_REC, tenant_schemes=["MGNREGA"])
    check("flag on, tenant granted only MGNREGA -> effective schemes = {MGNREGA}",
          scope_on_one.schemes == ["MGNREGA"], f"got {scope_on_one.schemes}")

    scope_on_extra = auth.scope_from_user(_USER_REC, tenant_schemes=["MGNREGA", "PMAY-G", "Not-A-Real-Scheme"])
    check("tenant grant never WIDENS past the role cap (bogus/extra scheme id has no effect)",
          sorted(scope_on_extra.schemes) == sorted(["MGNREGA", "PMAY-G"]), f"got {scope_on_extra.schemes}")

    scope_on_zero = auth.scope_from_user(_USER_REC, tenant_schemes=[])
    check("tenant with zero grants -> zero effective schemes (real default-deny, not fallback)",
          scope_on_zero.schemes == [], f"got {scope_on_zero.schemes}")

    rec_pinned = dict(_USER_REC, schemes=["MGNREGA", "PMAY-G"])
    scope_pinned = auth.scope_from_user(rec_pinned, tenant_schemes=["PMAY-G"])
    check("user-level scheme pin AND tenant grant both apply (intersection of three sets)",
          scope_pinned.schemes == ["PMAY-G"], f"got {scope_pinned.schemes}")
finally:
    settings.TENANT_SCHEME_RLS_ENABLED = False

print("3. UserScope.cache_fingerprint — tenant-aware bucketing")
settings.TENANT_SCHEME_RLS_ENABLED = False
fp_off = auth.scope_from_user(_USER_REC).cache_fingerprint()
check("flag off -> tenant_id absent from fingerprint (unchanged historical behavior)",
      "tenant=" not in fp_off, fp_off)

settings.TENANT_SCHEME_RLS_ENABLED = True
try:
    scope_a = auth.scope_from_user(dict(_USER_REC, tenant_id=1), tenant_schemes=["MGNREGA"])
    scope_b = auth.scope_from_user(dict(_USER_REC, tenant_id=2), tenant_schemes=["MGNREGA"])
    check("flag on -> tenant_id present in fingerprint", "tenant=1" in scope_a.cache_fingerprint())
    check("flag on -> two tenants with identical role/schemes/geo get DIFFERENT fingerprints "
          "(prevents cross-tenant cache leakage on tenant-scoped curated data)",
          scope_a.cache_fingerprint() != scope_b.cache_fingerprint())
finally:
    settings.TENANT_SCHEME_RLS_ENABLED = False

print("4. cross-scheme question authorization end-to-end (pure Python, still no DB) — "
      "auth.authorize() is the actual place a query naming multiple schemes gets checked; "
      "this is what \"does a cross-scheme question respect a partial tenant grant\" comes "
      "down to.")
_STATE_OFFICER_REC = dict(_USER_REC, role="state_officer", districts=[], blocks=[])
settings.TENANT_SCHEME_RLS_ENABLED = True
try:
    # A cross-scheme question -- e.g. "compare MGNREGA and PMAY-G spend in
    # East Khasi Hills" -- resolves schemes=["MGNREGA", "PMAY-G"]
    # (app/orchestration/pipeline.py's scheme classification, not re-tested here).
    scope_both = auth.scope_from_user(_STATE_OFFICER_REC, tenant_schemes=["MGNREGA", "PMAY-G"])
    decision_both = auth.authorize(scope_both, schemes=["MGNREGA", "PMAY-G"],
                                   resolved_entities={}, sql=None)
    check("tenant granted BOTH schemes -> cross-scheme question ALLOWED",
          decision_both.allow, decision_both.reason)

    scope_partial = auth.scope_from_user(_STATE_OFFICER_REC, tenant_schemes=["MGNREGA"])
    decision_partial = auth.authorize(scope_partial, schemes=["MGNREGA", "PMAY-G"],
                                      resolved_entities={}, sql=None)
    check("tenant granted only MGNREGA -> cross-scheme question naming PMAY-G too is "
          "DENIED OUTRIGHT (the whole query, not silently partial) before it reaches the DB",
          not decision_partial.allow and decision_partial.check == "scheme",
          f"allow={decision_partial.allow} check={decision_partial.check}")
    check("denial reason names the over-reaching scheme, not a generic message",
          "PMAY-G" in decision_partial.reason, decision_partial.reason)

    scope_single_ok = auth.scope_from_user(_STATE_OFFICER_REC, tenant_schemes=["MGNREGA"])
    decision_single = auth.authorize(scope_single_ok, schemes=["MGNREGA"],
                                     resolved_entities={}, sql=None)
    check("same tenant asking a SINGLE-scheme (MGNREGA-only) question still works fine "
          "(the tenant grant only blocks what it doesn't have, not everything)",
          decision_single.allow, decision_single.reason)
finally:
    settings.TENANT_SCHEME_RLS_ENABLED = False

print("5. app.database.db tenant-context contextvar mechanics (no DB I/O)")
settings.TENANT_SCHEME_RLS_ENABLED = False
tok_off = db.set_tenant_context(42, bypass=False)
check("flag off -> set_tenant_context returns a no-op (None) token", tok_off is None)
db.reset_tenant_context(tok_off)  # must not raise on a None token
check("reset_tenant_context(None) does not raise", True)

settings.TENANT_SCHEME_RLS_ENABLED = True
try:
    check("flag on, before set -> _current_tenant_ctx is None", db._current_tenant_ctx.get() is None)
    tok_on = db.set_tenant_context(42, bypass=True)
    check("flag on -> set_tenant_context returns a real token", tok_on is not None)
    check("context now readable as (42, True)", db._current_tenant_ctx.get() == (42, True))
    db.reset_tenant_context(tok_on)
    check("after reset -> context back to None", db._current_tenant_ctx.get() is None)


    async def _nested_isolation():
        """Concurrent asyncio tasks must never see each other's tenant —
        the whole point of using a contextvar instead of a module global."""
        seen = {}

        async def _one(tenant_id):
            t = db.set_tenant_context(tenant_id, bypass=False)
            await asyncio.sleep(0)  # yield, let the other task interleave
            seen[tenant_id] = db._current_tenant_ctx.get()
            db.reset_tenant_context(t)

        await asyncio.gather(_one(1), _one(2))
        return seen

    seen = asyncio.run(_nested_isolation())
    check("concurrent tasks with different tenant_ids never cross-contaminate",
          seen == {1: (1, False), 2: (2, False)}, str(seen))
finally:
    settings.TENANT_SCHEME_RLS_ENABLED = False

print()
if _fails:
    print(f"FAILED: {len(_fails)} check(s) — {_fails}")
    sys.exit(1)
print("ALL CHECKS PASSED")
