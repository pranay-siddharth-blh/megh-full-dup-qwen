"""Answer key for the cross-scheme runs: each scheme's figure straight from megh_db
(read-only), by the rule its own single-scheme sheet passed on and the measures
D-066 fixed (docs/SCHEMES.md "Cross-scheme questions"). Written independently of
app/cross_figures.py — never read the bot's own SQL as truth.

Rules (2026-10-30 re-run, D-097):
  MGNREGA            beneficiaries = households given work, every FY added
                     (household-years); money = SUM(total_exp) lakh -> rupees;
                     constituency: assembly_constituency_name (employment), ac_name
                     (expenditure).
  PMAY-G             houses = every record (the 126 undated houses count, KI-393);
                     money = amount RELEASED; constituency ac_name (D-096).
  Focus Plus         distinct beneficiaries; money = amount_disbursed; by its SOURCE
                     district / block name (district_name_raw / block_name_raw, KI-393),
                     the LGD block when the source never uses the name; no constituency.
  Focus Legacy       members = SUM(no_of_pg_members); money = amount_disbursed;
                     'Unresolved' rows out of the village count only; constituency ac_name.
  CM Elevate         applications = COUNT(DISTINCT request_id); no money, no FY,
                     no constituency.
  CM Elevate Legacy  applicants sanctioned = records with sanctioned_amount > 0
                     (2,820, KI-166); money = total_disbursement; constituency ac_name.

f = {"districts": [..], "block": str, "village": int, "ac": str, "year": int}
truth(scheme, "count"|"money", f, group=None|"district"|"block") ->
    float (or {key: float} when grouped), or NOT_RECORDED / NO_MONEY / NO_YEAR."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import fetch  # noqa: E402

NOT_RECORDED, NO_MONEY, NO_YEAR = "not recorded", "no money", "no year"

S = {
    "MGNREGA": dict(cv="curated.v_employment", c="SUM(households_employed)",
                    mv="curated.v_expenditure", m="SUM(total_exp) * 100000",
                    base="TRUE", vill="village_code IS NOT NULL",
                    ac_c="UPPER(assembly_constituency_name)", ac_m="UPPER(ac_name)", year=True),
    "PMAY-G": dict(cv="curated.v_pmay", c="COUNT(*)", mv="curated.v_pmay", m="SUM(amount_released)",
                   base="TRUE", vill="village_code IS NOT NULL", ac_c="UPPER(ac_name)", ac_m="UPPER(ac_name)",
                   year=True),
    "Focus Plus": dict(cv="curated.v_focus_plus", c="COUNT(DISTINCT beneficiary_key)",
                       mv="curated.v_focus_plus", m="SUM(amount_disbursed)",
                       base="TRUE", vill="village_code > 0", ac_c=None, ac_m=None, year=True, raw=True),
    "Focus Legacy": dict(cv="curated.v_focus_legacy", c="SUM(no_of_pg_members)",
                         mv="curated.v_focus_legacy", m="SUM(amount_disbursed)", base="TRUE",
                         vill="village_code > 0 AND entity_type <> 'Unresolved'", ac_c="UPPER(ac_name)",
                         ac_m="UPPER(ac_name)", year=True),
    "CM Elevate": dict(cv="curated.v_cm_elevate", c="COUNT(DISTINCT request_id)", mv=None, m=None,
                       base="TRUE", vill="village_code IS NOT NULL AND entity_type <> 'Unresolved'",
                       ac_c=None, ac_m=None, year=False),
    "CM Elevate Legacy": dict(cv="curated.v_cm_elevate_disbursement", c="COUNT(*) FILTER (WHERE sanctioned_amount > 0)",
                              mv="curated.v_cm_elevate_disbursement", m="SUM(total_disbursement)", base="TRUE",
                              vill="village_code > 0 AND entity_type <> 'Unresolved'", ac_c="UPPER(ac_name)",
                              ac_m="UPPER(ac_name)", year=True),
}
_CACHE: dict = {}
FP_RAW: set = set()
YEARS: dict = {}


async def load():
    FP_RAW.update(r["b"] for r in await fetch(
        "SELECT DISTINCT UPPER(block_name_raw) b FROM curated.v_focus_plus WHERE block_name_raw IS NOT NULL"))
    for s, v in S.items():
        if v["year"]:
            YEARS[s] = {r["y"] for r in await fetch(f"SELECT DISTINCT year_key y FROM {v['cv']} WHERE year_key IS NOT NULL")}


def _dcol(s):
    return "UPPER(district_name_raw)" if S[s].get("raw") else "UPPER(lgd_district)"


def _bcol(s, b=None):
    if S[s].get("raw") and (b is None or b in FP_RAW):
        return "UPPER(block_name_raw)"
    return "UPPER(lgd_block)"


def _where(s, kind, f, params):
    v = S[s]
    w = [v["base"]]

    def p(x):
        params.append(x)
        return f"${len(params)}"
    if f.get("districts"):
        w.append(f"{_dcol(s)} = ANY({p([d.upper() for d in f['districts']])}::text[])")
    if f.get("block"):
        b = f["block"].upper()
        # TURA MUNICIPAL BOARD (CM Elevate Legacy) = TURA MUNICIPAL BOARD-MUNICIPAL BOARD (others)
        base = b.replace("-MUNICIPAL BOARD", "") if b.startswith("TURA MUNICIPAL BOARD") else b
        names = [base, base + "-MUNICIPAL BOARD"] if base == "TURA MUNICIPAL BOARD" else [b]
        w.append(f"{_bcol(s, b)} = ANY({p(names)}::text[])")
    if f.get("village"):
        w.append(v["vill"])
        w.append(f"village_code = {p(int(f['village']))}")
    if f.get("ac"):
        how = v["ac_c"] if kind == "count" else v["ac_m"]
        if not how:
            return None
        w.append(f"{how} = {p(f['ac'].upper())}")
    if f.get("year") and v["year"]:
        w.append(f"year_key = {p(int(f['year']))}")
    return " AND ".join(w)


async def truth(s, kind, f, group=None):
    v = S[s]
    if kind == "money" and not v["mv"]:
        return NO_MONEY
    if f.get("year") and not v["year"]:
        return NO_YEAR
    if f.get("year") and int(f["year"]) not in YEARS.get(s, set()):
        return NO_YEAR
    key = (s, kind, tuple(sorted((k, tuple(x) if isinstance(x, list) else x) for k, x in f.items() if x)), group)
    if key in _CACHE:
        return _CACHE[key]
    params: list = []
    w = _where(s, kind, f, params)
    if w is None:
        out = NOT_RECORDED
    else:
        view, expr = (v["cv"], v["c"]) if kind == "count" else (v["mv"], v["m"])
        if group:
            col = _dcol(s) if group == "district" else _bcol(s)
            rows = await fetch(f"SELECT {col} k, ({expr})::float8 n FROM {view} WHERE {w} AND {col} IS NOT NULL GROUP BY 1",
                               params)
            out = {r["k"]: r["n"] or 0.0 for r in rows}
        else:
            rows = await fetch(f"SELECT ({expr})::float8 n FROM {view} WHERE {w}", params)
            out = rows[0]["n"] or 0.0
    _CACHE[key] = out
    return out


async def reach(s, f):
    """(districts, blocks, villages) a scheme has records in, within f."""
    v = S[s]
    params: list = []
    w = _where(s, "count", f, params)
    if w is None:
        return None
    key = (s, "reach", tuple(sorted((k, tuple(x) if isinstance(x, list) else x) for k, x in f.items() if x)))
    if key in _CACHE:
        return _CACHE[key]
    r = (await fetch(f"SELECT COUNT(DISTINCT {_dcol(s)})::float8 d, COUNT(DISTINCT {_bcol(s)})::float8 b, "
                     f"COUNT(DISTINCT village_code) FILTER (WHERE {v['vill']})::float8 vv FROM {v['cv']} WHERE {w}",
                     params))[0]
    _CACHE[key] = (r["d"], r["b"], r["vv"])
    return _CACHE[key]
