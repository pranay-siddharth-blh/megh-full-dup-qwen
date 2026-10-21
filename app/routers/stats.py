"""Live figures for the scheme overview cards (welcome screen).

The cards used to carry hand-typed numbers in frontend/src/chat/constants.js, which
went stale whenever the data was refreshed: PMAY-G said 1,71,107 houses sanctioned
while the chatbot, reading megh_db, said 1,70,981 (2026-10-15). Each figure is now
computed from the curated views with the same counting rules the chatbot uses, and
cached for STATS_TTL_SECONDS so a page load never adds load to the shared database.
The frontend keeps its typed numbers only as a fallback when this endpoint fails."""
import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app import auth
from app.config import settings
from app.db import fetch_rows
from app.deps import current_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["stats"])

STATS_TTL_SECONDS = 600

# One fixed, read-only statement per card. Labels match the cards; the rules are the
# chatbot's (schema_context): PMAY-G excludes placeholder rows, Focus Legacy counts
# groups on pg_id, CM Elevate applications are rows, MGNREGA villages are those with
# an employment or an expenditure record.
_SQL = {
    "mgnrega": """SELECT (SELECT SUM(person_days) FROM curated.v_employment) AS person_days,
                         (SELECT SUM(total_exp) FROM curated.v_expenditure) AS exp_lakh,
                         (SELECT COUNT(*) FROM (SELECT village_code FROM curated.v_employment
                                                UNION SELECT village_code FROM curated.v_expenditure) v
                          WHERE village_code IS NOT NULL) AS villages""",
    "pmay_g": """SELECT COUNT(*) AS sanctioned, COUNT(*) FILTER (WHERE is_completed) AS completed,
                        SUM(COALESCE(amount_released, 0)) AS released
                 FROM curated.v_pmay WHERE NOT is_placeholder""",
    "focus_plus": """SELECT COUNT(*) AS payments, SUM(amount_disbursed) AS amount,
                            COUNT(DISTINCT lgd_district) AS districts FROM curated.v_focus_plus""",
    "cm_elevate": """SELECT COUNT(*) AS applications, COUNT(DISTINCT scheme_name) AS schemes,
                            COUNT(DISTINCT lgd_district) AS districts FROM curated.v_cm_elevate""",
    "focus_legacy": """SELECT COUNT(DISTINCT pg_id) AS groups, SUM(no_of_pg_members) AS memberships,
                              SUM(amount_disbursed) AS amount FROM curated.v_focus_legacy""",
    "cm_elevate_legacy": """SELECT COUNT(*) AS records, COUNT(DISTINCT scheme_name) AS schemes,
                                   SUM(total_disbursement) AS disbursed FROM curated.v_cm_elevate_disbursement""",
}

_cache: dict = {"at": 0.0, "body": None}
_lock = asyncio.Lock()


def _indian(n) -> str:
    """12345678 -> '1,23,45,678'."""
    s = str(int(round(float(n or 0))))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def _crore(rupees, star: bool = False) -> str:
    return f"₹{float(rupees or 0) / 1e7:,.2f} Cr" + ("*" if star else "")


def _cards(r: dict) -> dict:
    m, p, f, c, fl, cl = (r[k] for k in ("mgnrega", "pmay_g", "focus_plus", "cm_elevate", "focus_legacy",
                                         "cm_elevate_legacy"))
    return {
        "mgnrega": [[f"{float(m['person_days'] or 0) / 1e7:.2f} Cr", "Person-days (4 yr)"],
                    # total_exp is in lakh: / 100 -> crore
                    [f"₹{float(m['exp_lakh'] or 0) / 100:,.2f} Cr", "Expenditure (4 yr)"],
                    [_indian(m["villages"]), "Villages with activity"]],
        "pmay_g": [[_indian(p["sanctioned"]), "Houses sanctioned"], [_indian(p["completed"]), "Houses completed"],
                   [_crore(p["released"]), "Funds released"]],
        "focus_plus": [[_indian(f["payments"]), "Disbursements"], [_crore(f["amount"], True), "Amount disbursed*"],
                       [_indian(f["districts"]), "Districts covered"]],
        "cm_elevate": [[_indian(c["applications"]), "Applications"], [_indian(c["schemes"]), "Schemes"],
                       [_indian(c["districts"]), "Districts covered"]],
        "focus_legacy": [[_indian(fl["groups"]), "Producer Groups"], [_indian(fl["memberships"]), "Memberships paid"],
                         [_crore(fl["amount"], True), "Amount remitted*"]],
        "cm_elevate_legacy": [[_indian(cl["records"]), "Sanction records"], [_indian(cl["schemes"]), "Schemes"],
                              [_crore(cl["disbursed"], True), "Disbursed (subsidy + loan)*"]],
    }


async def _compute() -> dict:
    rows = {}
    for key, sql in _SQL.items():   # one at a time: the shared DB is short of connections
        rows[key] = (await fetch_rows(sql))[0]
    return {"cards": _cards(rows), "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}


async def _require_user(scope: auth.UserScope = Depends(current_scope)) -> auth.UserScope:
    if settings.AUTH_ENABLED and scope.db_user_id is None:
        raise HTTPException(401, "authentication required")
    return scope


@router.get("/scheme-stats")
async def scheme_stats(_: auth.UserScope = Depends(_require_user)):
    """Card figures for all six schemes, cached for STATS_TTL_SECONDS. A failed refresh
    keeps serving the last good figures; with none yet, 503 (the UI keeps its own)."""
    if _cache["body"] and time.monotonic() - _cache["at"] < STATS_TTL_SECONDS:
        return _cache["body"]
    async with _lock:
        if _cache["body"] and time.monotonic() - _cache["at"] < STATS_TTL_SECONDS:
            return _cache["body"]
        try:
            body = await _compute()
        except Exception:  # noqa: BLE001
            logger.warning("scheme-stats: refresh failed", exc_info=True)
            if _cache["body"]:
                return _cache["body"]
            raise HTTPException(503, "scheme figures unavailable")
        _cache.update(at=time.monotonic(), body=body)
        return body
