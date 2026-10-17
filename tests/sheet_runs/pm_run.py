"""PMAY-G sheet (PMAY-OFF-001..028) through the live LangGraph pipeline; every
expected figure from curated.v_pmay (NOT is_placeholder, COALESCE(amount_released,0)).
Hierarchy: 2 villages per district (24) for the village cases, EVERY block, EVERY
district, village / block / district pairs, top sanction dates. A year pause is
answered "All financial years combined" (the sheet's questions name no year).

Usage (repo root): pm_run.py [PMAY-OFF-001 ...]  -> pm_results.json (PM_OUT)"""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "PMAY-G")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case, has_name, vals, close, YEARS  # noqa: E402,F401
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set(sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("PM_OUT", "pm_results.json"))
PM_YEARS = [2017, 2018, 2019, 2020, 2021, 2022, 2023]
STAGES = ["Completed", "Roof Cast", "Plinth", "House Sanctioned"]

AGG = """COUNT(*)::float8 AS houses,
 COALESCE(SUM(sanctioned_amount),0)::float8 AS sanctioned,
 COALESCE(SUM(COALESCE(amount_released,0)),0)::float8 AS released,
 COUNT(*) FILTER (WHERE is_completed)::float8 AS completed,
 COUNT(*) FILTER (WHERE NOT COALESCE(is_completed,false))::float8 AS incomplete,
 COUNT(*) FILTER (WHERE COALESCE(amount_released,0) >= sanctioned_amount)::float8 AS full_r,
 COUNT(*) FILTER (WHERE COALESCE(amount_released,0) > 0 AND COALESCE(amount_released,0) < sanctioned_amount)::float8 AS part_r,
 COUNT(*) FILTER (WHERE COALESCE(amount_released,0) = 0)::float8 AS none_r,
 COUNT(*) FILTER (WHERE COALESCE(amount_released,0) >= sanctioned_amount AND NOT COALESCE(is_completed,false))::float8 AS fnd,
 COUNT(DISTINCT sanction_no)::float8 AS sanc_nos,
 COALESCE(SUM(COALESCE(amount_released,0)) FILTER (WHERE sanctioned_amount > 0),0)::float8 AS rel_pos,
 COALESCE(SUM(sanctioned_amount) FILTER (WHERE sanctioned_amount > 0),0)::float8 AS sanc_pos,
 """ + ",\n ".join(f"COUNT(*) FILTER (WHERE status_name = '{s}')::float8 AS \"st_{s}\"" for s in STAGES)


async def agg(where, params):
    r = await fetch(f"SELECT {AGG} FROM curated.v_pmay WHERE NOT is_placeholder AND {where}", params)
    return dict(r[0])


def money_ok(rec, rupees):
    """The ₹ figure, exact, or in lakh / crore (2 dp)."""
    if rupees is None:
        return False
    for c in vals(rec):
        if close(c, rupees, 0.0005) or close(c, rupees / 1e5, 0.006) or close(c, rupees / 1e7, 0.006):
            return True
    return False


def num_ok(rec, n):
    return any(close(c, n, 0.0001) for c in vals(rec))


def checks(*pairs):
    """pairs: (label, expected, kind) kind in num|money|pct; zero expected numbers must appear as 0."""
    def chk(rec):
        miss = []
        for label, e, kind in pairs:
            ok = (money_ok(rec, e) if kind == "money" else
                  any(close(c, round(e, 2), 0.0005) for c in vals(rec)) if kind == "pct" else num_ok(rec, e))
            if not ok:
                miss.append(f"{label}={e}")
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def shape(tc, a):
    """The question's expected figures from an aggregate row."""
    st = [(s, a[f"st_{s}"], "num") for s in STAGES if a[f"st_{s}"]]
    return {
        "PMAY-OFF-001": [("beneficiaries", a["houses"], "num")],
        "PMAY-OFF-002": [("sanctioned", a["sanctioned"], "money")],
        "PMAY-OFF-003": [("released", a["released"], "money")],
        "PMAY-OFF-004": [("completed", a["completed"], "num")],
        "PMAY-OFF-005": [("incomplete", a["incomplete"], "num")],
        "PMAY-OFF-006": st,
        "PMAY-OFF-007": [("remaining", a["sanctioned"] - a["released"], "money")],
        "PMAY-OFF-008": [("full", a["full_r"], "num")],
        "PMAY-OFF-009": [("part", a["part_r"], "num")],
        "PMAY-OFF-010": [("none", a["none_r"], "num")],
        "PMAY-OFF-026": [("sanction_nos", a["sanc_nos"], "num")],
        "PMAY-OFF-028": [("full_not_done", a["fnd"], "num")],
        "PMAY-OFF-011": [("beneficiaries", a["houses"], "num")],
        "PMAY-OFF-012": [("sanctioned", a["sanctioned"], "money"), ("released", a["released"], "money"),
                         ("remaining", a["sanctioned"] - a["released"], "money")],
        "PMAY-OFF-013": [("completed", a["completed"], "num")],
        "PMAY-OFF-014": st,
        "PMAY-OFF-015": [("beneficiaries", a["houses"], "num")],
        "PMAY-OFF-016": [("sanctioned", a["sanctioned"], "money"), ("released", a["released"], "money"),
                         ("remaining", a["sanctioned"] - a["released"], "money")],
        "PMAY-OFF-017": [("completed", a["completed"], "num")],
        "PMAY-OFF-018": st,
        "PMAY-OFF-019": [("beneficiaries", a["houses"], "num"), ("sanctioned", a["sanctioned"], "money"),
                         ("released", a["released"], "money"), ("completed", a["completed"], "num")],
        "PMAY-OFF-020": [("completion_pct", 100 * a["completed"] / a["houses"] if a["houses"] else 0, "pct")],
        "PMAY-OFF-021": [("release_pct", 100 * a["rel_pos"] / a["sanc_pos"] if a["sanc_pos"] else 0, "pct")],
    }[tc]


Q = {
    "PMAY-OFF-001": "How many PMAY beneficiaries are there in {p}?",
    "PMAY-OFF-002": "What is the total amount sanctioned in {p}?",
    "PMAY-OFF-003": "How much sactioned amount has been released in {p}?",
    "PMAY-OFF-004": "How many PMAY houses have been completed in {p}?",
    "PMAY-OFF-005": "How many houses are still incomplete in {p}?",
    "PMAY-OFF-006": "Give me the house status breakdown for {p}.",
    "PMAY-OFF-007": "How much sanctioned amount is still to be released in {p}?",
    "PMAY-OFF-008": "How many beneficiaries in {p} have received their full sanctioned amount?",
    "PMAY-OFF-009": "How many beneficiaries in {p} have received only part of their sanctioned amount?",
    "PMAY-OFF-010": "How many beneficiaries in {p} have not received any amount?",
    "PMAY-OFF-026": "How many unique sanction numbers are there in {p}?",
    "PMAY-OFF-028": "How many beneficiaries in {p} have received the full sanctioned amount but their house is still not completed?",
    "PMAY-OFF-011": "How many PMAY beneficiaries are there in {p}?",
    "PMAY-OFF-012": "Give me the PMAY financial summary for {p}.",
    "PMAY-OFF-013": "How many houses have been completed in {p}?",
    "PMAY-OFF-014": "Give me the house status breakdown for {p}.",
    "PMAY-OFF-015": "How many PMAY beneficiaries are there in {p}?",
    "PMAY-OFF-016": "Give me the PMAY financial summary for {p}.",
    "PMAY-OFF-017": "How many PMAY houses have been completed in {p}?",
    "PMAY-OFF-018": "Give me the house status breakdown for {p}.",
    "PMAY-OFF-019": "Give me the overall PMAY performance of {p}.",
    "PMAY-OFF-020": "What percentage of PMAY houses are completed in {p}?",
    "PMAY-OFF-021": "What percentage of the sanctioned amount has been released in {p}?",
}
VILLAGE_TCS = ["PMAY-OFF-001", "PMAY-OFF-002", "PMAY-OFF-003", "PMAY-OFF-004", "PMAY-OFF-005", "PMAY-OFF-006",
               "PMAY-OFF-007", "PMAY-OFF-008", "PMAY-OFF-009", "PMAY-OFF-010", "PMAY-OFF-026", "PMAY-OFF-028"]
BLOCK_TCS = ["PMAY-OFF-011", "PMAY-OFF-012", "PMAY-OFF-013", "PMAY-OFF-014"]
DISTRICT_TCS = ["PMAY-OFF-015", "PMAY-OFF-016", "PMAY-OFF-017", "PMAY-OFF-018", "PMAY-OFF-019",
                "PMAY-OFF-020", "PMAY-OFF-021"]


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        villages = await fetch("""
            WITH u AS (SELECT UPPER(lgd_village_name) n FROM curated.v_pmay WHERE NOT is_placeholder
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 c AS (SELECT p.village_code, MIN(p.lgd_village_name) name, MIN(p.lgd_block) b, MIN(p.lgd_district) d,
                              COUNT(*) h
                       FROM curated.v_pmay p JOIN u ON u.n = UPPER(p.lgd_village_name)
                       WHERE NOT p.is_placeholder AND p.village_code IS NOT NULL AND p.lgd_village_name !~ '[^A-Za-z ]'
                       GROUP BY 1 HAVING COUNT(*) >= 5),
                 x AS (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY d ORDER BY md5(name)) rn FROM c)
            SELECT village_code, name, b, d FROM x WHERE rn <= 2 ORDER BY d, name""")
        blocks = await fetch("SELECT lgd_block b, MIN(lgd_district) d FROM curated.v_pmay WHERE NOT is_placeholder "
                             "AND lgd_block IS NOT NULL GROUP BY 1 ORDER BY 1")
        districts = [r["d"] for r in await fetch("SELECT DISTINCT lgd_district d FROM curated.v_pmay "
                                                 "WHERE NOT is_placeholder ORDER BY 1")]
        mg_run.log(f"{len(villages)} villages, {len(blocks)} blocks, {len(districts)} districts")

        for i, v in enumerate(villages):
            a = await agg("village_code = $1", [v["village_code"]])
            nm = v["name"].upper() if i % 2 == 0 else v["name"].title()
            for tc in VILLAGE_TCS:
                T.append(run_case(tc, f"{v['name']} ({v['b']}/{v['d']})", Q[tc].format(p=nm),
                                  checks(*shape(tc, a)), year="all", place=[v["name"]], level="village",
                                  expected={k: a[k] for k in ("houses", "sanctioned", "released", "completed")},
                                  mgnrega_only=False))
        for i, b in enumerate(blocks):
            a = await agg("lgd_block = $1", [b["b"]])
            nm = (f"{b['b'].title()} block" if i % 2 == 0 else b["b"].title())
            for tc in BLOCK_TCS:
                T.append(run_case(tc, f"{b['b']} as '{nm}'", Q[tc].format(p=nm), checks(*shape(tc, a)),
                                  year="all", place=[b["b"]], level="block",
                                  expected={k: a[k] for k in ("houses", "sanctioned", "released", "completed")},
                                  mgnrega_only=False))
        for i, d in enumerate(districts):
            a = await agg("lgd_district = $1", [d])
            nm = d.title() if i % 2 else d
            for tc in DISTRICT_TCS:
                T.append(run_case(tc, d, Q[tc].format(p=nm), checks(*shape(tc, a)), year="all",
                                  place=[d.split()[0]], level="district",
                                  expected={k: a[k] for k in ("houses", "sanctioned", "released", "completed")},
                                  mgnrega_only=False))
            # 025: houses sanctioned + amounts in a district during a year (every district, rotating FY)
            y = PM_YEARS[i % len(PM_YEARS)]
            ay = await agg("lgd_district = $1 AND year_key = $2", [d, y])
            T.append(run_case("PMAY-OFF-025", f"{d} FY {y}-{str(y + 1)[2:]}",
                              f"How many houses were sanctioned and how much was released in {nm} during "
                              f"{y}-{str(y + 1)[2:]}?",
                              checks(("houses", ay["houses"], "num"), ("sanctioned", ay["sanctioned"], "money"),
                                     ("released", ay["released"], "money")),
                              year=y, place=[d.split()[0]], level="district", expected=dict(ay), mgnrega_only=False))

        # 022: village pairs inside one block (which has more completed houses)
        pairs = await fetch("""
            WITH c AS (SELECT village_code, MIN(lgd_village_name) n, MIN(lgd_block) b,
                              COUNT(*) FILTER (WHERE is_completed) comp
                       FROM curated.v_pmay WHERE NOT is_placeholder AND lgd_village_name !~ '[^A-Za-z ]'
                       GROUP BY 1),
                 u AS (SELECT UPPER(lgd_village_name) n FROM curated.v_pmay GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 x AS (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY b ORDER BY md5(c.n)) rn FROM c
                       JOIN u ON u.n = UPPER(c.n) WHERE comp > 0)
            SELECT a.n n1, a.comp c1, z.n n2, z.comp c2 FROM x a JOIN x z ON a.b = z.b AND a.rn = 1 AND z.rn = 2
            WHERE a.comp <> z.comp ORDER BY md5(a.b) LIMIT 24""")
        for p in pairs:
            win = p["n1"] if p["c1"] > p["c2"] else p["n2"]

            def chk22(rec, p=p, win=win):
                ok = num_ok(rec, p["c1"]) and num_ok(rec, p["c2"])
                ans = (rec.get("answer") or "")
                return ok and has_name(rec, win), f"{p['n1']}={p['c1']} {p['n2']}={p['c2']} winner={win}"
            T.append(run_case("PMAY-OFF-022", f"{p['n1']} vs {p['n2']}",
                              f"Which has more completed houses: {p['n1']} or {p['n2']}?", chk22, year="all",
                              place=[p["n1"]], level=None, expected=dict(p), mgnrega_only=False))
        # 023: block pairs (sanctioned amounts)
        for i in range(0, len(blocks) - 1, 2):
            b1, b2 = blocks[i]["b"], blocks[i + 1]["b"]
            a1 = await agg("lgd_block = $1", [b1])
            a2 = await agg("lgd_block = $1", [b2])
            T.append(run_case("PMAY-OFF-023", f"{b1} vs {b2}",
                              f"Compare the sanctioned amounts of {b1.title()} block and {b2.title()} block.",
                              checks(("s1", a1["sanctioned"], "money"), ("s2", a2["sanctioned"], "money")),
                              year="all", place=[b1], level=None, expected={"s1": a1["sanctioned"], "s2": a2["sanctioned"]},
                              mgnrega_only=False))
        # 024: district pairs (performance)
        for i in range(0, len(districts) - 1, 2):
            d1, d2 = districts[i], districts[i + 1]
            a1 = await agg("lgd_district = $1", [d1])
            a2 = await agg("lgd_district = $1", [d2])
            T.append(run_case("PMAY-OFF-024", f"{d1} vs {d2}",
                              f"Compare PMAY performance between {d1.title()} and {d2.title()}.",
                              checks(("h1", a1["houses"], "num"), ("h2", a2["houses"], "num"),
                                     ("s1", a1["sanctioned"], "money"), ("s2", a2["sanctioned"], "money"),
                                     ("r1", a1["released"], "money"), ("r2", a2["released"], "money"),
                                     ("c1", a1["completed"], "num"), ("c2", a2["completed"], "num")),
                              year="all", place=[d1.split()[0]], level=None, expected={}, mgnrega_only=False))
        # 027: dates — the 8 busiest sanction dates and 4 others
        dates = await fetch("""(SELECT sanction_date d, COUNT(*) n FROM curated.v_pmay WHERE NOT is_placeholder
                                AND sanction_date IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8)
                               UNION ALL
                               (SELECT sanction_date, COUNT(*) FROM curated.v_pmay WHERE NOT is_placeholder
                                AND sanction_date IS NOT NULL GROUP BY 1 HAVING COUNT(*) BETWEEN 5 AND 50
                                ORDER BY md5(sanction_date::text) LIMIT 4)""")
        fmts = ["{d:%d-%m-%Y}", "{d:%Y-%m-%d}", "{d.day} {d:%B %Y}", "{d:%B} {d.day}, {d:%Y}"]
        for i, r in enumerate(dates):
            ds = fmts[i % 4].format(d=r["d"])
            T.append(run_case("PMAY-OFF-027", f"{r['d']} as '{ds}'", f"How many PMAY houses were sanctioned on {ds}?",
                              checks(("houses", float(r["n"]), "num")), year="all", expected=float(r["n"]),
                              mgnrega_only=False))

        mg_run.log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    mg_run.log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
