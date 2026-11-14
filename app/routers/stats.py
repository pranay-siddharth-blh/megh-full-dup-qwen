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

from app import auth, cross_registry, scheme_registry
from app.config import settings
from app.db import fetch_rows
from app.deps import current_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["stats"])

STATS_TTL_SECONDS = 600

# One fixed, read-only statement per card. Labels match the cards; the rules are the
# chatbot's (schema_context): PMAY-G counts every row (the 126 zero-sanction registrations
# are houses sanctioned too, D-060 as widened by the user 2026-10-23: the card said 1,70,981
# while the rule and the chatbot say 1,71,107; they add 0 completed and Rs 0), Focus Legacy counts
# groups on pg_id, CM Elevate applications are distinct request_ids, MGNREGA villages are
# those with an employment or an expenditure record (the chat reads villages the same way:
# _mgnrega_villages_active_query).
# CM Elevate (RAG fix report 2026-10-29, Issue 1): the card said 8,948 (rows) while the chat
# said 8,921 — 27 request_ids have two identical rows (an ingestion duplicate, schema rule 8),
# so the card now counts COUNT(DISTINCT request_id), the chat's and the prompt's rule.
# The LEAD figure of each card (its first stat) is the scheme's `headline` in data/cross_scheme.yaml
# (app/cross_registry.py, 2026-11-14): the same SQL answers "the headline figures across all schemes", so the card
# and the chat cannot disagree on it. _lead() writes it into the card's statement; the rest stays here.
def _lead(card: str) -> str:
    h = cross_registry.headline_for_card(card)
    return f"{h.expr} AS {h.figure}"


_MG = cross_registry.headline_for_card("mgnrega")
_SQL = {
    "mgnrega": f"""SELECT (SELECT {_MG.expr} FROM {_MG.view}) AS {_MG.figure},
                         (SELECT SUM(total_exp) FROM curated.v_expenditure) AS exp_lakh,
                         (SELECT COUNT(*) FROM (SELECT village_code FROM curated.v_employment
                                                UNION SELECT village_code FROM curated.v_expenditure) v
                          WHERE village_code IS NOT NULL) AS villages""",
    "pmay_g": f"""SELECT {_lead("pmay_g")}, COUNT(*) FILTER (WHERE is_completed) AS completed,
                        SUM(COALESCE(amount_released, 0)) AS released
                 FROM curated.v_pmay""",
    "focus_plus": f"""SELECT {_lead("focus_plus")}, SUM(amount_disbursed) AS amount,
                            COUNT(DISTINCT lgd_district) AS districts FROM curated.v_focus_plus""",
    "cm_elevate": f"""SELECT {_lead("cm_elevate")}, COUNT(DISTINCT scheme_name) AS schemes,
                            COUNT(DISTINCT lgd_district) AS districts FROM curated.v_cm_elevate""",
    "focus_legacy": f"""SELECT {_lead("focus_legacy")}, SUM(no_of_pg_members) AS memberships,
                              SUM(amount_disbursed) AS amount FROM curated.v_focus_legacy""",
    "cm_elevate_legacy": f"""SELECT {_lead("cm_elevate_legacy")}, COUNT(DISTINCT scheme_name) AS schemes,
                                   SUM(total_disbursement) AS disbursed FROM curated.v_cm_elevate_disbursement""",
    "cmss": f"""SELECT {_lead("cmss")}, COUNT(*) FILTER (WHERE is_disbursed) AS students_paid, SUM(amount_disbursed) AS amount_disbursed FROM curated.v_cmss""",
    "homestay": f"""SELECT {_lead("homestay")}, COUNT(DISTINCT member_key) AS applicants, COUNT(*) FILTER (WHERE file_status = 'Approved') AS approved FROM curated.v_homestay_api""",
}

# The financial years each card covers, read from the same views. The cards' period text
# ("FY 2022-23 to 2025-26", "no FY 2023-24") and "(4 yr)" were typed into constants.js and
# would go stale on the next data load (user 2026-10-22: "kpi cards … need to update
# dynamically … based on the data"). CM Elevate has no date column: no period.
_YEARS_SQL = {
    "mgnrega": """SELECT financial_year_short AS fy FROM curated.v_employment
                  UNION SELECT financial_year_short FROM curated.v_expenditure""",
    "pmay_g": "SELECT DISTINCT financial_year_short AS fy FROM curated.v_pmay WHERE NOT is_placeholder",
    "focus_plus": "SELECT DISTINCT financial_year_short AS fy FROM curated.v_focus_plus",
    "focus_legacy": "SELECT DISTINCT financial_year_short AS fy FROM curated.v_focus_legacy",
    "cm_elevate_legacy": "SELECT DISTINCT financial_year_short AS fy FROM curated.v_cm_elevate_disbursement",
    "cmss": "SELECT DISTINCT financial_year_short AS fy FROM curated.v_cmss",
    "homestay": "SELECT DISTINCT financial_year_short AS fy FROM curated.v_homestay_api",
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


_NO_FIGURE = "—"


def _has(v) -> bool:
    """A figure the view actually returned. SUM over no rows is NULL: shown as "—", never as a
    "0" / "₹0.00 Cr" that reads as a real measurement."""
    return v is not None


def _period(years) -> str:
    """'FY 2022-23 to 2025-26', 'FY 2022-23 & 2025-26', 'FY 2021-22 to 2025-26, no FY 2023-24'
    from a list of '2022-23' labels; '' when there are none."""
    fys = sorted({str(y) for y in (years or []) if y and len(str(y)) >= 4 and str(y)[:4].isdecimal()})
    if not fys:
        return ""
    if len(fys) == 1:
        return f"FY {fys[0]}"
    if len(fys) == 2 and int(fys[1][:4]) - int(fys[0][:4]) > 1:
        return f"FY {fys[0]} & {fys[1]}"
    first, last = int(fys[0][:4]), int(fys[-1][:4])
    held = {int(y[:4]) for y in fys}
    gaps = [f"FY {y}-{(y + 1) % 100:02d}" for y in range(first, last) if y not in held]
    return f"FY {fys[0]} to {fys[-1]}" + (f", no {', '.join(gaps)}" if gaps else "")


def _cards(r: dict, years: "dict | None" = None) -> dict:
    m, p, f, c, fl, cl, cs, hs = (r[k] for k in ("mgnrega", "pmay_g", "focus_plus", "cm_elevate", "focus_legacy",
                                                 "cm_elevate_legacy", "cmss", "homestay"))
    # "(4 yr)" is the number of financial years the MGNREGA views hold, counted
    n_mg = len((years or {}).get("mgnrega") or [])
    span = f" ({n_mg} yr)" if n_mg else ""

    def ind(v):
        return _indian(v) if _has(v) else _NO_FIGURE

    def cr(v, star=False):
        return _crore(v, star) if _has(v) else _NO_FIGURE

    # the "*" (figures provisional) comes from the one dataset registry the chat
    # answers read too (scheme_registry.DATASETS, data-accuracy brief 2026-10-29)
    def prov(name):
        return scheme_registry.DATASETS[name].provisional

    # the lead stat's label is the headline's (data/cross_scheme.yaml), like its SQL
    def lead(card):
        return cross_registry.headline_for_card(card).label

    return {
        "mgnrega": [[f"{float(m['person_days']) / 1e7:.2f} Cr" if _has(m["person_days"]) else _NO_FIGURE,
                     f"{lead('mgnrega')}{span}"],
                    # total_exp is in lakh: / 100 -> crore
                    [f"₹{float(m['exp_lakh']) / 100:,.2f} Cr" if _has(m["exp_lakh"]) else _NO_FIGURE,
                     f"Expenditure{span}"],
                    [ind(m["villages"]), "Villages with activity"]],
        "pmay_g": [[ind(p["sanctioned"]), lead("pmay_g")], [ind(p["completed"]), "Houses completed"],
                   [cr(p["released"]), "Funds released"]],
        "focus_plus": [[ind(f["payments"]), lead("focus_plus")], [cr(f["amount"], prov("Focus Plus")), "Amount disbursed*"],
                       [ind(f["districts"]), "Districts covered"]],
        "cm_elevate": [[ind(c["applications"]), lead("cm_elevate")], [ind(c["schemes"]), "Schemes"],
                       [ind(c["districts"]), "Districts covered"]],
        "focus_legacy": [[ind(fl["groups"]), lead("focus_legacy")], [ind(fl["memberships"]), "Memberships paid"],
                         [cr(fl["amount"], prov("Focus Legacy")), "Amount remitted*"]],
        "cm_elevate_legacy": [[ind(cl["records"]), lead("cm_elevate_legacy")], [ind(cl["schemes"]), "Schemes"],
                              [cr(cl["disbursed"], prov("CM Elevate Legacy")), "Disbursed (subsidy + loan)*"]],
        # CMSS: applications (paid or not), students paid, rupees paid — a flat Rs 6,000 per paid student
        "cmss": [[ind(cs["applications"]), lead("cmss")], [ind(cs["students_paid"]), "Students paid"],
                 [cr(cs["amount_disbursed"], prov("CMSS")), "Amount disbursed"]],
        # Homestay: applications, distinct applicants, approved — the feed records no money
        "homestay": [[ind(hs["applications"]), lead("homestay")], [ind(hs["applicants"]), "Applicants"],
                     [ind(hs["approved"]), "Approved"]],
    }


async def _compute() -> dict:
    rows, years = {}, {}
    for key, sql in _SQL.items():   # one at a time: the shared DB is short of connections
        rows[key] = (await fetch_rows(sql))[0]
    for key, sql in _YEARS_SQL.items():
        years[key] = sorted(str(r["fy"]) for r in await fetch_rows(sql) if r["fy"])
    return {"cards": _cards(rows, years), "periods": {k: _period(v) for k, v in years.items()},
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# Card key ("pmay_g") -> scheme name ("PMAY-G"): the frontend's SCHEME_CARDS keys.
_CARD_SCHEME = {s.name.lower().replace(" ", "_").replace("-", "_"): s.name
                for s in scheme_registry.SCHEMES}


def _for_scope(body: dict, scope: auth.UserScope) -> dict:
    """Only the cards of the schemes the caller may query (KI-420, RBAC review
    2026-10-26: every logged-in user got all six). The figures are statewide totals,
    which every role may see, so the scheme list is the only filter; the cache stays
    shared and is never changed here."""
    allowed = set(scope.schemes)
    keep = [k for k in body["cards"] if _CARD_SCHEME.get(k) in allowed]
    if len(keep) == len(body["cards"]):
        return body
    return {**body, "cards": {k: body["cards"][k] for k in keep},
            "periods": {k: v for k, v in body["periods"].items() if k in keep}}


async def _require_user(scope: auth.UserScope = Depends(current_scope)) -> auth.UserScope:
    if settings.AUTH_ENABLED and scope.db_user_id is None:
        raise HTTPException(401, "authentication required")
    return scope


@router.get("/scheme-stats")
async def scheme_stats(scope: auth.UserScope = Depends(_require_user)):
    """Card figures for the caller's schemes, cached (all six) for STATS_TTL_SECONDS. A
    failed refresh keeps serving the last good figures; with none yet, 503 (the UI keeps
    its own)."""
    return _for_scope(await _all_cards(), scope)


async def _all_cards() -> dict:
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
