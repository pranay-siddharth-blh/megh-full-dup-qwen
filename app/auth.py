"""
Authorization — compare the caller's role and scope against what a query is
actually asking for, and refuse politely when the query reaches past the role.

Spec 5.7: three checks against a role-to-permissions map plus a per-session
user-scope object —
  1. granularity vs role cap   (state < district < block < village)
  2. geography scope           (which districts/blocks the user may see)
  3. scheme scope              (which schemes the user may query)

The checks are pure Python. Users/tenants/audit live in the `app` schema of
megh_db (see backend/appdb.py); a JSONL mirror of the audit trail is also kept
for offline grep. Admin roles bypass the three query checks but stay
tenant-scoped for what they can *see*.
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app import scheme_registry, sql_ast
from app.config import settings

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]  # repo root

# ── Granularity lattice ─────────────────────────────────────────────────────
# Coarse -> fine. A role's cap is the finest level it may ask for.
GRANULARITY_ORDER = ["state", "district", "block", "village"]


def _finer(a: str, b: str) -> bool:
    """True if a is strictly finer-grained than b."""
    return GRANULARITY_ORDER.index(a) > GRANULARITY_ORDER.index(b)


# ── Role -> permissions ────────────────────────────────────────────────────
# A user record may narrow these (e.g. pin `districts`), never widen them.
# `geographies: "all"` = no geographic restriction.
ROLE_PERMISSIONS: dict[str, dict] = {
    # Platform + tenant administration. is_admin bypasses the three *query*
    # checks (an admin exploring data isn't 5.7's threat model) but stays
    # tenant-scoped for what they can see (conversations, audit, users).
    "super_admin": {
        "granularity_cap": "village", "schemes": list(scheme_registry.NAMES),
        "geographies": "all", "is_admin": True, "cross_tenant": True,
    },
    "tenant_admin": {
        "granularity_cap": "village", "schemes": list(scheme_registry.NAMES),
        "geographies": "all", "is_admin": True,
    },
    "admin": {
        "granularity_cap": "village",
        "schemes": list(scheme_registry.NAMES),
        "geographies": "all",
        "is_admin": True,
    },
    "state_officer": {
        "granularity_cap": "district",
        "schemes": list(scheme_registry.NAMES),
        "geographies": "all",
    },
    "district_officer": {
        "granularity_cap": "block",
        "schemes": list(scheme_registry.NAMES),
        "geographies": {"districts": [], "blocks": []},  # must be pinned per user
    },
    "block_officer": {
        "granularity_cap": "village",
        "schemes": list(scheme_registry.NAMES),
        "geographies": {"districts": [], "blocks": []},
    },
    "analyst": {
        "granularity_cap": "village",
        "schemes": list(scheme_registry.NAMES),
        "geographies": "all",
    },
    # No identity on the request -> this. Statewide aggregates only.
    "public": {
        "granularity_cap": "state",
        "schemes": list(scheme_registry.NAMES),
        "geographies": "all",
    },
}


@dataclass
class UserScope:
    user_id: str
    role: str
    granularity_cap: str
    schemes: list[str]
    geographies: object  # "all" | {"districts": [UPPER...], "blocks": [UPPER...]}
    name: str = ""
    tenant_id: int | None = None
    db_user_id: int | None = None
    username: str = ""

    @property
    def is_admin(self) -> bool:
        return bool(ROLE_PERMISSIONS.get(self.role, {}).get("is_admin"))

    @property
    def cross_tenant(self) -> bool:
        return bool(ROLE_PERMISSIONS.get(self.role, {}).get("cross_tenant"))

    @property
    def geo_restricted(self) -> bool:
        return self.geographies != "all"

    def allowed_districts(self) -> list[str]:
        return [] if self.geographies == "all" else list(self.geographies.get("districts", []))

    def allowed_blocks(self) -> list[str]:
        return [] if self.geographies == "all" else list(self.geographies.get("blocks", []))

    def cache_fingerprint(self) -> str:
        """Stable identity for response-cache bucketing. Two scopes with the same
        fingerprint are guaranteed the same authorization outcome for any given
        question — the auth decision is a pure function of (scope, schemes,
        resolved_entities, sql) — so they may safely share a cached answer.
        tenant_id is deliberately excluded: the curated warehouse the query path
        reads is not tenant-partitioned, so it never changes the answer."""
        if self.geographies == "all":
            geo = "geo=all"
        else:
            geo = ("d=" + ",".join(sorted(self.allowed_districts()))
                   + "|b=" + ",".join(sorted(self.allowed_blocks())))
        return ";".join((
            f"role={self.role}",
            f"gran={self.granularity_cap}",
            f"schemes={','.join(sorted(self.schemes))}",
            geo,
        ))


@dataclass
class AuthDecision:
    allow: bool
    reason: str = ""
    query_granularity: str = "state"
    check: str = ""  # which check denied: "scheme" | "geography" | "granularity"


def _upper_list(values) -> list[str]:
    return [str(v).strip().upper() for v in (values or []) if str(v).strip()]


def anonymous_scope() -> UserScope:
    """AUTH_ENABLED=false dev mode only — real requests always carry a JWT."""
    base = ROLE_PERMISSIONS.get(settings.AUTH_DEFAULT_ROLE, ROLE_PERMISSIONS["analyst"])
    return UserScope(user_id="(anonymous)", role=settings.AUTH_DEFAULT_ROLE,
                     granularity_cap=base["granularity_cap"], schemes=list(base["schemes"]),
                     geographies="all", name="anonymous")


def scope_from_user(rec: dict) -> UserScope:
    """Build the effective scope from an app.users row. The role sets the caps;
    the per-user district/block/scheme lists only narrow them, never widen.

    Fails closed (KI-421, RBAC review 2026-10-26): a role the map does not know
    gets `public` (it used to get the analyst role: all geography, village
    level); a scheme list none of whose names is a real scheme gives NO scheme
    (a typo used to grant all six); the per-user granularity cap can only make
    the role's cap coarser, and an unknown cap is ignored (a bad value used to
    widen the cap, or crash every data question in GRANULARITY_ORDER.index)."""
    role = rec.get("role") or settings.AUTH_DEFAULT_ROLE
    base = ROLE_PERMISSIONS.get(role)
    if base is None:
        logger.warning("scope_from_user: unknown role %r for user %r -> public", role, rec.get("username"))
        role, base = "public", ROLE_PERMISSIONS["public"]

    schemes = list(base["schemes"])
    if rec.get("schemes"):
        allowed = {str(s).strip() for s in rec["schemes"]}
        schemes = [s for s in schemes if s in allowed]
        if not schemes:
            logger.warning("scope_from_user: no known scheme in %r for user %r -> no scheme",
                           rec["schemes"], rec.get("username"))

    cap = base["granularity_cap"]
    user_cap = str(rec.get("granularity_cap") or "").strip().lower()
    if user_cap and user_cap not in GRANULARITY_ORDER:
        logger.warning("scope_from_user: unknown granularity_cap %r for user %r ignored",
                       rec.get("granularity_cap"), rec.get("username"))
    elif user_cap and not _finer(user_cap, cap):
        cap = user_cap

    districts, blocks = _upper_list(rec.get("districts")), _upper_list(rec.get("blocks"))
    if base["geographies"] == "all" and not districts and not blocks:
        geographies: object = "all"
    else:
        geographies = {"districts": districts, "blocks": blocks}

    return UserScope(
        user_id=rec.get("username") or str(rec.get("user_id")),
        username=rec.get("username", ""),
        db_user_id=rec.get("user_id"),
        tenant_id=rec.get("tenant_id"),
        role=role,
        granularity_cap=cap,
        schemes=schemes,
        geographies=geographies,
        name=rec.get("name") or "",
    )


# ── Query inspection (on the parsed tree: app/sql_ast.py) ──────────────────
# Columns, not text: a district name inside a string literal or a comment is
# not a district filter, UPPER(lgd_district) = 'X' is one, and every value of
# an IN list / ANY(ARRAY[...]) / OR branch is checked, not just the first.
_VILLAGE_COLS = ("village_code", "lgd_village_name", "geography_key")


def infer_granularity(resolved_entities: dict, sql: str | None) -> str:
    """The finest level the query touches — from resolved entities first, then
    any column the SQL references (GROUP BY or anywhere else)."""
    e = resolved_entities or {}
    cols = sql_ast.columns(sql) if sql else set()
    if e.get("village_code") or e.get("village") or cols & {"village_code", "lgd_village_name"} \
            or sql_ast.groups_by(sql, *_VILLAGE_COLS):
        return "village"
    if e.get("block") or "lgd_block" in cols:
        return "block"
    if e.get("district") or "lgd_district" in cols:
        return "district"
    return "state"


def _districts_in_sql(sql: str | None) -> list[str]:
    return _upper_list(sql_ast.filter_values(sql, "lgd_district")) if sql else []


def _blocks_in_sql(sql: str | None) -> list[str]:
    return _upper_list(sql_ast.filter_values(sql, "lgd_block")) if sql else []


def authorize(scope: UserScope, *, schemes: list[str], resolved_entities: dict,
              sql: str | None) -> AuthDecision:
    """The three checks, in order of cost. Returns allow/deny + a user-facing reason."""
    gran = infer_granularity(resolved_entities, sql)

    # Admins bypass the query checks (5.7 targets officers reaching past their
    # posting, not administrators). They are still tenant-scoped elsewhere.
    if scope.is_admin:
        return AuthDecision(True, "", gran, "")

    # 1. scheme scope
    over = [s for s in (schemes or []) if s not in scope.schemes]
    if over:
        return AuthDecision(
            False,
            (f"This query relates to {', '.join(over)}. Your account is authorised "
             f"for {', '.join(scope.schemes)} only. Please raise a query within the "
             f"authorised scheme, or request scheme access from your department "
             f"administrator.") if scope.schemes else
            (f"This query relates to {', '.join(over)}. Your account is not yet "
             f"authorised for any scheme. Please request scheme access from your "
             f"department administrator."),
            gran, "scheme",
        )

    # 2. geography scope
    if scope.geo_restricted:
        # A query the parser cannot read cannot be checked for its places, so a
        # restricted user is refused rather than waved through (fail closed).
        if sql and not sql_ast.is_parseable(sql):
            return AuthDecision(
                False,
                "This query could not be checked against your authorised area. "
                "Please rephrase the question, naming your district or block.",
                gran, "geography",
            )
        allowed_d = set(scope.allowed_districts())
        allowed_b = set(scope.allowed_blocks())
        want_d = set()
        if (resolved_entities or {}).get("district"):
            want_d.add(str(resolved_entities["district"]).upper())
        want_d.update(_districts_in_sql(sql))
        want_b = set(_blocks_in_sql(sql))
        if (resolved_entities or {}).get("block"):
            want_b.add(str(resolved_entities["block"]).upper())

        # A block officer whose block was never assigned has no area of their
        # own: the block check below runs only when blocks are listed, so the
        # account saw its whole district (ri-bhoi-bo, DB team review
        # 2026-10-27, KI-429). Fail closed — statewide figures only, as for any
        # restricted account that names no area — until a block is assigned.
        if scope.role == "block_officer" and not allowed_b and (want_d or want_b or _finer(gran, "state")):
            return AuthDecision(
                False,
                "Your block officer account has no block assigned yet, so area-level "
                "data cannot be shown. Please ask your department administrator to "
                "assign your block.",
                gran, "geography",
            )

        stray_d = {d for d in want_d if d not in allowed_d}
        if stray_d:
            return AuthDecision(
                False,
                f"This query relates to {', '.join(sorted(stray_d))}. Your account is "
                f"authorised for "
                f"{', '.join(sorted(allowed_d)) or 'no district at present'}. "
                f"Please restrict the query to your jurisdiction, or request revised "
                f"access from your department administrator.",
                gran, "geography",
            )
        if allowed_b and want_b:
            stray_b = {b for b in want_b if b not in allowed_b}
            if stray_b:
                return AuthDecision(
                    False,
                    f"This query relates to {', '.join(sorted(stray_b))} block. Your "
                    f"account is authorised for "
                    f"{', '.join(sorted(allowed_b)) or 'no block at present'}. "
                    f"Please restrict the query to your jurisdiction, or request "
                    f"revised access from your department administrator.",
                    gran, "geography",
                )
        # Geo-restricted user asking a question with no geography filter at
        # district-or-finer grain would return data outside their area.
        if not want_d and not want_b and _finer(gran, "state"):
            return AuthDecision(
                False,
                f"This query does not specify an area. Your account is authorised "
                f"for {', '.join(sorted(allowed_d)) or 'your assigned jurisdiction'}, "
                f"and a query at this level of detail must name the jurisdiction "
                f"concerned — for example, "
                f"\"... in {sorted(allowed_d)[0] if allowed_d else 'your district'}\".",
                gran, "geography",
            )

    # 3. granularity vs role cap
    if _finer(gran, scope.granularity_cap):
        return AuthDecision(
            False,
            f"This query requires data at {gran} level. Your account is authorised "
            f"up to {scope.granularity_cap} level. Please raise the query at "
            f"{scope.granularity_cap} level, or request revised access from your "
            f"department administrator.",
            gran, "granularity",
        )

    return AuthDecision(True, "", gran, "")


# ── Audit trail (JSONL append) ────────────────────────────────────────────
_audit_path = (_ROOT / settings.AUDIT_FILE) if not Path(settings.AUDIT_FILE).is_absolute() \
    else Path(settings.AUDIT_FILE)
_audit_lock = threading.Lock()


def audit(record: dict) -> None:
    """Append one query record. Best-effort — an audit failure must not fail the
    request."""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **record}
    try:
        with _audit_lock:
            _audit_path.parent.mkdir(parents=True, exist_ok=True)
            with _audit_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:  # noqa: BLE001
        logger.warning("auth.audit: could not write audit record: %s", e)


def read_audit(limit: int = 200, user_id: str | None = None) -> list[dict]:
    try:
        lines = _audit_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if user_id and rec.get("user_id") != user_id:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out
