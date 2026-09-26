"""
Pipeline architecture doc §5.7 ("Authorization check") — app/core/auth.py's three
checks (scheme scope, geography scope, granularity vs. role cap) against
UserScope/ROLE_PERMISSIONS, plus infer_granularity() and scope_from_user().
Pure Python, no DB, no model gateway — auth.py self-documents as "Spec 5.7"
(auth.py:5). audit()/read_audit() (file-backed) are out of scope here; they
already have dedicated coverage in test_query_audit_trail.py and
test_pii_audit_trail.py.
Run: `python tests/unit/test_authorization.py`, exit code 0 = pass.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.knowledge import scheme_registry  # noqa: E402
from app.core.auth import UserScope, authorize, infer_granularity, scope_from_user  # noqa: E402

# scope_from_user()'s default scheme cap is now resolved dynamically via
# scheme_registry (2026-09-18 — see auth._role_scheme_cap's docstring for
# why it's no longer a hardcoded literal in ROLE_PERMISSIONS). The real app
# always calls this at startup before serving any request
# (app/main.py::lifespan); this standalone test needs the same call for the
# same reason, or every role's default scheme cap comes back empty.
scheme_registry.load_all()

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


def _scope(role: str, **overrides) -> UserScope:
    base = dict(user_id="u1", role=role, granularity_cap="village",
                schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"], geographies="all")
    base.update(overrides)
    return UserScope(**base)


# ── 1. infer_granularity — finest level the query actually touches ─────────
print("1. INFER_GRANULARITY")

check("a resolved village entity infers village grain",
      infer_granularity({"village_code": 12345}, None) == "village")
check("SQL grouping by lgd_block infers block grain",
      infer_granularity({}, "SELECT lgd_block, SUM(x) FROM t GROUP BY lgd_block") == "block")
check("a resolved district entity infers district grain",
      infer_granularity({"district": "EAST GARO HILLS"}, None) == "district")
check("no entity and no place-shaped SQL infers state (coarsest) grain",
      infer_granularity({}, "SELECT SUM(x) FROM t") == "state")


# ── 2. authorize — scheme scope ─────────────────────────────────────────────
print("2. AUTHORIZE — SCHEME SCOPE")

scope = _scope("analyst", schemes=["MGNREGA"])
d = authorize(scope, schemes=["PMAY-G"], resolved_entities={}, sql=None)
check("a scheme outside the user's authorised list is denied",
      d.allow is False and d.check == "scheme", detail=str(d))

d = authorize(scope, schemes=["MGNREGA"], resolved_entities={}, sql=None)
check("a scheme within the user's authorised list is allowed",
      d.allow is True, detail=str(d))


# ── 3. authorize — geography scope ──────────────────────────────────────────
print("3. AUTHORIZE — GEOGRAPHY SCOPE")

scope = _scope("district_officer", granularity_cap="block",
               geographies={"districts": ["WEST GARO HILLS"], "blocks": []})

d = authorize(scope, schemes=["MGNREGA"], resolved_entities={"district": "East Garo Hills"}, sql=None)
check("a district outside the user's pinned geography is denied",
      d.allow is False and d.check == "geography", detail=str(d))

d = authorize(scope, schemes=["MGNREGA"], resolved_entities={"district": "West Garo Hills"}, sql=None)
check("the user's own pinned district is allowed",
      d.allow is True, detail=str(d))

d = authorize(scope, schemes=["MGNREGA"],
             resolved_entities={}, sql="SELECT lgd_block, SUM(x) FROM t GROUP BY lgd_block")
check("a geo-restricted user querying finer-than-state with no named area is denied",
      d.allow is False and d.check == "geography", detail=str(d))


# ── 4. authorize — granularity vs. role cap ─────────────────────────────────
print("4. AUTHORIZE — GRANULARITY CAP")

scope = _scope("state_officer", granularity_cap="district", geographies="all")
d = authorize(scope, schemes=["MGNREGA"], resolved_entities={"village_code": 1}, sql=None)
check("a query finer than the role's granularity cap is denied",
      d.allow is False and d.check == "granularity", detail=str(d))

d = authorize(scope, schemes=["MGNREGA"], resolved_entities={"district": "East Garo Hills"}, sql=None)
check("a query at or within the role's granularity cap is allowed",
      d.allow is True, detail=str(d))


# ── 5. authorize — admins bypass the three query checks ────────────────────
print("5. AUTHORIZE — ADMIN BYPASS")

scope = _scope("super_admin", granularity_cap="village", geographies="all")
d = authorize(scope, schemes=["MGNREGA", "PMAY-G"], resolved_entities={"village_code": 1}, sql=None)
check("super_admin bypasses scheme/geography/granularity checks entirely",
      d.allow is True and d.check == "", detail=str(d))


# ── 6. scope_from_user — role sets caps, per-user record only narrows them ──
print("6. SCOPE_FROM_USER")

s = scope_from_user({"username": "u2", "role": "district_officer",
                     "districts": ["West Garo Hills"], "blocks": []})
check("a per-user role builds the expected granularity cap from ROLE_PERMISSIONS",
      s.granularity_cap == "block", detail=str(s))
check("a per-user district pin narrows the scope away from 'all'",
      s.geographies != "all" and "WEST GARO HILLS" in s.allowed_districts(), detail=str(s))

s = scope_from_user({"username": "u3", "role": "analyst", "schemes": ["MGNREGA"]})
check("a per-user scheme list narrows the role's default scheme set",
      s.schemes == ["MGNREGA"], detail=str(s))

s = scope_from_user({"username": "u4", "role": "analyst"})
check("no per-user narrowing leaves the role's full default scheme set",
      set(s.schemes) == {"MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"}, detail=str(s))


print()
if _fails:
    print(f"FAILED ({len(_fails)}): " + ", ".join(_fails))
    sys.exit(1)
print("ALL AUTHORIZATION (5.7) CHECKS PASSED")
