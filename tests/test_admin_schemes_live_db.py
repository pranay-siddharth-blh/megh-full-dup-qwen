"""
tests/test_admin_schemes_live_db.py — openspec/changes/multi-tenant-rls-
scheme-scaleout task 1.5: an actual DB-backed test of
app.scheme_registry.sync_to_db() and the /admin/schemes,
/admin/tenants/{id}/schemes endpoints against a REAL Postgres — the one
thing tests/test_tenant_scheme_entitlements.py's pure-Python coverage
(scope intersection, cache fingerprint, contextvar mechanics) couldn't
reach, since it never touches a database at all.

Requires: `ADMIN_SCHEMES_TEST_PG_DSN` pointing at a reachable, disposable
Postgres you don't mind app.* tables landing in — never a shared or
production instance. Skips cleanly (exit 0) when unset, same convention as
tests/test_pipeline_graph_postgres.py. This test calls
app.appdb.ensure_schema()/app.scheme_registry.sync_to_db() directly (the
same calls app/main.py's real startup makes) rather than relying on
Starlette TestClient's lifespan handling.

Uses httpx.AsyncClient(transport=ASGITransport(app)) rather than
starlette.testclient.TestClient, and runs everything — bootstrap AND every
HTTP call — inside ONE asyncio.run(), not several: asyncpg connections/
pools are bound to the event loop that created them, and TestClient's
synchronous wrapper drives the ASGI app in its own internal loop per call,
so mixing db.init_pool() from a bare asyncio.run() with later
TestClient.get()/post() calls breaks with "another operation is in
progress" / InterfaceError — confirmed by hitting it directly while
writing this test, not a hypothetical.

Run: `ADMIN_SCHEMES_TEST_PG_DSN=postgresql://... python
tests/test_admin_schemes_live_db.py`, exit code 0 = pass (or skip).
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_PG_DSN = os.environ.get("ADMIN_SCHEMES_TEST_PG_DSN", "")

if not _PG_DSN:
    print("SKIPPED — ADMIN_SCHEMES_TEST_PG_DSN not set; no live Postgres to test against.")
    sys.exit(0)

os.environ["DATABASE_URL"] = _PG_DSN
os.environ["JWT_SECRET"] = "test-secret-at-least-32-characters-long"
os.environ["ENV"] = "prod"
os.environ["AUTH_ENABLED"] = "true"

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app import appdb, db, scheme_registry  # noqa: E402
from app.auth import UserScope  # noqa: E402
from app.deps import require_admin, require_super  # noqa: E402
from app.main import app  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_SUPER = UserScope(user_id="live-admin", role="super_admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"],
                   geographies="all", tenant_id=1, db_user_id=1)


async def main():
    await db.init_pool()
    scheme_registry.load_all()
    await appdb.ensure_schema()
    default_tid = await appdb.get_default_tenant_id()
    await scheme_registry.sync_to_db(default_tenant_id=default_tid)
    check("bootstrap ran against the real DB (default tenant resolved)",
          default_tid is not None, default_tid)

    app.dependency_overrides[require_admin] = lambda: _SUPER
    app.dependency_overrides[require_super] = lambda: _SUPER
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        print("1. GET /admin/schemes — the real registry, synced to the real DB")
        r = await client.get("/admin/schemes")
        check("200 OK", r.status_code == 200, r.text[:300])
        body = r.json()
        scheme_ids = {s["scheme_id"] for s in body.get("schemes", [])}
        check("all 4 real schemes present, synced from scheme_registry.yaml",
              {"MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"} <= scheme_ids, scheme_ids)

        print("2. POST/GET/DELETE /admin/tenants/{id}/schemes/{scheme_id} — real grant/revoke round trip")
        new_tenant = await appdb.create_tenant("live-test-tenant", "Live DB test tenant")
        tid = new_tenant["tenant_id"]

        r_before = await client.get(f"/admin/tenants/{tid}/schemes")
        check("200 OK (pre-grant)", r_before.status_code == 200, r_before.text[:300])
        check("fresh tenant starts with zero granted schemes",
              r_before.json().get("granted") == [], r_before.json())

        r_grant = await client.post(f"/admin/tenants/{tid}/schemes/MGNREGA")
        check("200 OK (grant)", r_grant.status_code == 200, r_grant.text[:300])
        check("MGNREGA now shows as granted", r_grant.json().get("granted") == ["MGNREGA"], r_grant.json())

        r_after_grant = await client.get(f"/admin/tenants/{tid}/schemes")
        check("effective schemes include MGNREGA + the shared scheme",
              "MGNREGA" in r_after_grant.json().get("effective", []), r_after_grant.json())

        r_bad = await client.post(f"/admin/tenants/{tid}/schemes/NOT-A-REAL-SCHEME")
        check("422 for an unknown scheme_id — real DB-backed validation, not just app-level",
              r_bad.status_code == 422, r_bad.text[:300])

        r_revoke = await client.delete(f"/admin/tenants/{tid}/schemes/MGNREGA")
        check("200 OK (revoke)", r_revoke.status_code == 200, r_revoke.text[:300])
        check("MGNREGA no longer granted after revoke",
              r_revoke.json().get("granted") == [], r_revoke.json())

        print("3. Second sync_to_db() call is idempotent — no duplicate rows, no error")
        await scheme_registry.sync_to_db()
        r_idempotent = await client.get("/admin/schemes")
        check("re-running sync_to_db() doesn't duplicate scheme rows",
              len([s for s in r_idempotent.json()["schemes"] if s["scheme_id"] == "MGNREGA"]) == 1,
              r_idempotent.json())

    app.dependency_overrides.pop(require_admin, None)
    app.dependency_overrides.pop(require_super, None)
    await db.close_pool()


asyncio.run(main())

print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL ADMIN SCHEMES LIVE-DB (task 1.5) CHECKS PASSED")
