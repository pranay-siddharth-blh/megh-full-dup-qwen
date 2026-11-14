"""The Secretary's voice desk: one read-only board of every onboarded scheme, by district and by year (D-105).

Like `/api/scheme-stats` (routers/stats.py), and next to it, NOT part of the pipeline: fixed, parameter-free SELECTs on
the curated views, with the same counting rules the chat uses (stats.py's comments), cached for BOARD_TTL_SECONDS so
opening the voice desk never adds load to the shared database, and filtered to the schemes the caller may query.
The brain and the NL-to-SQL are not touched; a spoken question is still answered by the pipeline (relay.py).

Each scheme keeps its own unit: nothing here is ever added across schemes (a person-day, a house and a rupee are not
the same thing). Money is in rupees (MGNREGA's total_exp is stored in lakh and converted here, as the card does)."""
import asyncio
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app import auth, cross_registry
from app.db import fetch_rows
from app.routers.stats import _require_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/voice", tags=["voice"])

BOARD_TTL_SECONDS = 600

# (scheme, view, [(measure key, SQL aggregate, label, unit, what it counts)])
# unit: 'count' (a number of things), 'rupees', 'person-days'
_MEASURES = (
    ("MGNREGA", "curated.v_employment", (
        ("person_days", "SUM(person_days)", "Person-days", "person-days", "days of work generated"),
        ("households", "SUM(households_employed)", "Households employed", "count", "households given work, summed over years"),
    )),
    ("MGNREGA", "curated.v_expenditure", (
        ("expenditure", "SUM(total_exp) * 100000", "Expenditure", "rupees", "total spent (wages, material, admin)"),
    )),
    ("PMAY-G", "curated.v_pmay", (
        ("sanctioned", "COUNT(*)", "Houses sanctioned", "count", "houses sanctioned"),
        ("completed", "COUNT(*) FILTER (WHERE is_completed)", "Houses completed", "count", "houses completed"),
        ("released", "SUM(COALESCE(amount_released, 0))", "Funds released", "rupees", "money released to beneficiaries"),
    )),
    ("Focus Plus", "curated.v_focus_plus", (
        ("payments", "COUNT(*)", "Disbursements", "count", "payments made to beneficiaries"),
        ("amount", "SUM(amount_disbursed)", "Amount disbursed", "rupees", "money paid out (provisional)"),
    )),
    ("CM Elevate", "curated.v_cm_elevate", (
        ("applications", "COUNT(DISTINCT request_id)", "Applications", "count", "applications received (no amounts held)"),
    )),
    ("Focus Legacy", "curated.v_focus_legacy", (
        ("groups", "COUNT(DISTINCT pg_id)", "Producer groups", "count", "producer groups paid"),
        ("amount", "SUM(amount_disbursed)", "Amount remitted", "rupees", "money remitted to groups (provisional)"),
    )),
    ("CM Elevate Legacy", "curated.v_cm_elevate_disbursement", (
        ("disbursed", "SUM(total_disbursement)", "Disbursed", "rupees", "subsidy + loan disbursed (provisional)"),
        ("records", "COUNT(*)", "Sanction records", "count", "sanction records"),
    )),
    # 2026-11-14: the two schemes onboarded on 11-12 Nov, with the welcome cards' own counting rules
    # (routers/stats.py _SQL "cmss" / "homestay"): a CMSS row is one student application, paid or not;
    # a Homestay row is one application and the scheme records no money
    ("CMSS", "curated.v_cmss", (
        ("students_paid", "COUNT(*) FILTER (WHERE is_disbursed)", "Students paid", "count", "scholarship applications that were paid"),
        ("applications", "COUNT(*)", "Applications", "count", "scholarship applications received"),
        ("amount", "SUM(amount_disbursed)", "Amount disbursed", "rupees", "scholarship money paid out"),
    )),
    ("Homestay", "curated.v_homestay_api", (
        ("applications", "COUNT(*)", "Applications", "count", "homestay applications received (no amounts held)"),
        ("approved", "COUNT(*) FILTER (WHERE file_status = 'Approved')", "Approved", "count", "applications approved"),
    )),
)

# a view with no date column has no year series: the views of the schemes declared `years: false` in
# data/cross_scheme.yaml (CM Elevate), not a hand-kept list (2026-11-14)
_NO_YEAR = frozenset(q.view for e in cross_registry.ENTRIES if not e.years for q in e.queries)

_cache: dict = {"at": 0.0, "body": None}
_lock = asyncio.Lock()


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


async def _compute() -> dict:
    schemes: dict = {}
    districts: set = set()
    regions: dict = {}
    for scheme, view, measures in _MEASURES:    # one view at a time: the shared DB is short of connections
        aggs = ", ".join(f"{sql} AS {key}" for key, sql, *_ in measures)
        by_d = await fetch_rows(f"SELECT lgd_district AS d, MIN(region) AS r, {aggs} FROM {view} "
                                "WHERE lgd_district IS NOT NULL GROUP BY lgd_district")
        by_y = [] if view in _NO_YEAR else await fetch_rows(
            f"SELECT financial_year_short AS fy, {aggs} FROM {view} WHERE financial_year_short IS NOT NULL "
            "GROUP BY financial_year_short")
        tot = (await fetch_rows(f"SELECT {aggs} FROM {view}"))[0]
        entry = schemes.setdefault(scheme, {"name": scheme, "measures": []})
        for key, _sql, label, unit, counts in measures:
            entry["measures"].append({
                "key": key, "label": label, "unit": unit, "counts": counts, "total": _num(tot[key]),
                "by_district": {str(r["d"]): _num(r[key]) for r in by_d if r[key] is not None},
                "by_year": {str(r["fy"]).strip(): _num(r[key]) for r in by_y if r[key] is not None},
            })
        for r in by_d:
            districts.add(str(r["d"]))
            if r["r"]:
                regions[str(r["d"])] = str(r["r"])
    return {"schemes": list(schemes.values()), "districts": sorted(districts), "regions": regions,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}


async def _board() -> dict:
    if _cache["body"] and time.monotonic() - _cache["at"] < BOARD_TTL_SECONDS:
        return _cache["body"]
    async with _lock:
        if _cache["body"] and time.monotonic() - _cache["at"] < BOARD_TTL_SECONDS:
            return _cache["body"]
        try:
            body = await _compute()
        except Exception:  # noqa: BLE001
            logger.warning("voice board: refresh failed", exc_info=True)
            if _cache["body"]:
                return _cache["body"]
            raise HTTPException(503, "board figures unavailable")
        _cache.update(at=time.monotonic(), body=body)
        return body


def _for_scope(body: dict, scope: auth.UserScope) -> dict:
    allowed = set(scope.schemes)
    keep = [s for s in body["schemes"] if s["name"] in allowed]
    return body if len(keep) == len(body["schemes"]) else {**body, "schemes": keep}


@router.get("/board")
async def board(scope: auth.UserScope = Depends(_require_user)):
    """The voice desk's figures for the caller's schemes: per scheme, its measures in their own units, statewide, by
    district and by financial year. Cached for BOARD_TTL_SECONDS; a failed refresh keeps the last good board."""
    return _for_scope(await _board(), scope)
