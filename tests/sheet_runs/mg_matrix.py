"""MGNREGA metric x level x year matrix, live (LangGraph, real models, megh_db).
Every one of the 12 metrics at every level (state, district, block, constituency, village),
for each FY and for all years, plus a ranking per metric per level. Expected figures from
the DB views. Reuses tests/sheet_runs/mg_run.run_case (same pause handling).
Usage (repo root): .venv/Scripts/python.exe tests/sheet_runs/mg_matrix.py <out.json>   (needs the VPN)
Score: .venv/Scripts/python.exe tests/sheet_runs/mg_score.py <out.json>"""
import asyncio
import json
import os
import sys

OUTP = sys.argv[1]
sys.argv = sys.argv[:1]
sys.path.insert(0, ".")
sys.path.insert(0, os.path.join(".", "tests", "sheet_runs"))
os.environ.setdefault("MG_CONC", "3")
import mg_run as M  # noqa: E402
from mg_run import run_case, has, has_name, fetch, fy, YEARS  # noqa: E402
from tests._text_checks import has_phrase  # noqa: E402
from app import main as app_main  # noqa: E402

EXP = {  # col: (question phrase, ranking phrase)
    "total_exp": ("What was the total expenditure in {p} {y}?", "total expenditure"),
    "unskilled_wage_exp": ("How much was spent on unskilled wages in {p} {y}?", "unskilled wage expenditure"),
    "semi_skilled_wage_exp": ("How much was spent on semi-skilled wages in {p} {y}?", "semi-skilled wage expenditure"),
    "material_exp": ("What was the material expenditure in {p} {y}?", "material expenditure"),
    "tax_exp": ("How much was the tax expenditure in {p} {y}?", "tax expenditure"),
    "admin_total_exp": ("What was the administrative expenditure in {p} {y}?", "administrative expenditure"),
}
EMP = {
    "households_employed": ("How many households received employment in {p} {y}?", "households employed"),
    "persons_employed": ("How many persons were provided employment in {p} {y}?", "persons employed"),
    "person_days": ("How many person-days were generated in {p} {y}?", "person-days"),
    "households_completed_100_days": ("How many households completed 100 days of work in {p} {y}?",
                                      "households completing 100 days"),
    "job_cards_issued_total": ("How many job cards were issued in {p} {y}?", "job cards issued"),
    "women_employment_provided": ("How many women were provided employment in {p} {y}?", "women employment"),
}
ALL_PHRASES = ["across all financial years", "till date", "in all years combined", "for all years"]
NOT_REC = ("not recorded", "not been recorded", "not available", "unrecorded", "not captured", "no data",
           "zero", "nil", "no women", "0 women")


def year_words(y, i):
    if y == "all":
        return ALL_PHRASES[i % 4]
    return "during " + fy(y, i)


def single_check(exp, money, zero_ok_phrases=False):
    def chk(rec):
        a = rec.get("answer") or ""
        if exp == 0:
            ok = has(rec, 0.0) or has_phrase(a.lower(), *NOT_REC)
            return ok, "exp=0"
        return has(rec, exp, 0.005, money), f"exp={exp}"
    return chk


def all_years_check(total, per_year, money, cumulative=False):
    """all years: the total (summable measures), or every year's figure shown (a breakdown is fine).
    Job cards are a running total: every year's figure, never a sum."""
    def chk(rec):
        each = all(has(rec, v, 0.005, money) for v in per_year.values() if v)
        if cumulative:
            return each, f"per-year={per_year}"
        return has(rec, total, 0.005, money) or each, f"total={total} per-year={per_year}"
    return chk


async def yearly(view, col, where, params):
    rows = await fetch(f"SELECT year_key, COALESCE(SUM({col}),0)::float8 v FROM curated.{view} "
                       f"WHERE {where} GROUP BY 1", params)
    d = {y: 0.0 for y in YEARS}
    d.update({r["year_key"]: r["v"] for r in rows})
    return d


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        districts = [r["d"] for r in await fetch("SELECT DISTINCT lgd_district d FROM curated.v_expenditure ORDER BY 1")]
        blocks = [r["b"] for r in await fetch("SELECT lgd_block b FROM curated.v_employment "
                                              "WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY md5(lgd_block)")]
        acs = [r["a"] for r in await fetch("SELECT assembly_constituency_name a FROM curated.v_employment "
                                           "WHERE assembly_constituency_name IS NOT NULL GROUP BY 1 ORDER BY md5(assembly_constituency_name)")]
        villages = await fetch("""
            WITH u AS (SELECT UPPER(lgd_village_name) n FROM curated.v_employment GROUP BY 1
                       HAVING COUNT(DISTINCT village_code)=1),
                 c AS (SELECT e.village_code, MIN(e.lgd_village_name) name, MIN(e.lgd_district) d
                       FROM curated.v_employment e JOIN u ON u.n = UPPER(e.lgd_village_name)
                       WHERE e.village_code IN (SELECT village_code FROM curated.v_expenditure GROUP BY 1
                                                HAVING COUNT(DISTINCT year_key)=4)
                         AND LENGTH(e.lgd_village_name) >= 5
                       GROUP BY 1 HAVING COUNT(DISTINCT e.year_key)=4 AND SUM(e.person_days) > 0)
            SELECT * FROM c ORDER BY md5(name || 'matrix') LIMIT 40""")
        print(len(districts), len(blocks), len(acs), len(villages), flush=True)
        ydx = YEARS + ["all"]
        n = 0
        for kind, view, metrics in (("exp", "v_expenditure", EXP), ("emp", "v_employment", EMP)):
            levels = ["state", "district", "block", "village"] + (["ac"] if kind == "emp" else [])
            for mi, (col, (q, _rank)) in enumerate(metrics.items()):
                money = kind == "exp"
                for lev in levels:
                    for yi, y in enumerate(ydx):
                        n += 1
                        k = mi * 7 + yi * 3 + n
                        if lev == "state":
                            where, params, pw, place, level = "TRUE", [], "Meghalaya", None, None
                        elif lev == "district":
                            d = districts[k % len(districts)]
                            where, params, place, level = "lgd_district = $1", [d], [d.split()[0]], "district"
                            pw = d.title() if k % 2 else f"{d.title()} district"
                        elif lev == "block":
                            b = blocks[k % len(blocks)]
                            where, params, pw, place, level = "lgd_block = $1", [b], f"{b.title()} block", [b], "block"
                        elif lev == "ac":
                            a = acs[k % len(acs)]
                            where, params, place, level = "assembly_constituency_name = $1", [a], [a.split()[0]], "ac"
                            pw = f"{a.title()} constituency"
                        else:
                            v = villages[k % len(villages)]
                            where, params, place, level = "village_code = $1", [v["village_code"]], [v["name"]], "village"
                            pw = v["name"].upper() if k % 2 else f"{v['name'].title()} village"
                        per = await yearly(view, col, where, params)
                        question = q.format(p=pw, y=year_words(y, k))
                        lab = f"{col} @ {lev} {pw} {('FY ' + fy(y)) if y != 'all' else 'ALL YEARS'}"
                        tc = f"M-{kind}-{col}-{lev}"
                        if y == "all":
                            chk = all_years_check(sum(per.values()), per, money,
                                                  cumulative=col == "job_cards_issued_total")
                            exp, yr = {"total": sum(per.values()), **per}, "all"
                        else:
                            chk, exp, yr = single_check(per[y], money), per[y], y
                        T.append(run_case(tc, lab, question, chk, year=yr, place=place, level=level, expected=exp))
                # one ranking per level per metric
                for li, lev in enumerate([lv for lv in levels if lv != "state"]):
                    y = YEARS[(mi + li) % 4]
                    if col == "women_employment_provided" and y == 2025:
                        y = 2023
                    grp = {"district": "lgd_district", "block": "lgd_block", "ac": "assembly_constituency_name",
                           "village": "village_code"}[lev]
                    nm = "MIN(lgd_village_name)" if lev == "village" else grp
                    top = (await fetch(f"SELECT {nm} n, SUM({col})::float8 v FROM curated.{view} WHERE year_key=$1 "
                                       f"AND {grp} IS NOT NULL GROUP BY {grp} ORDER BY 2 DESC LIMIT 1", [y]))[0]
                    word = {"ac": "assembly constituency"}.get(lev, lev)
                    question = f"Which {word} had the highest {_rank} during {fy(y, mi + li)}?"

                    def rk(rec, t=top, money=money):
                        return has_name(rec, t["n"]) and has(rec, t["v"], 0.006, money), f"top {t['n']} {t['v']}"
                    T.append(run_case(f"R-{kind}-{col}-{lev}", f"rank {col} by {lev} FY {fy(y)}", question, rk,
                                      year=y, expected=dict(top)))
        # expenditure by constituency: not held in the data; the bot must not invent a figure
        for a in acs[:3]:
            T.append(run_case("X-exp-by-ac", f"total_exp @ ac {a}",
                              f"What was the total expenditure in {a.title()} constituency during 2024-25?",
                              lambda r: (True, "informational"), year=2024, place=[a.split()[0]], level="ac"))
        print(f"running {len(T)} conversations", flush=True)
        await asyncio.gather(*T)
    with open(OUTP, "w", encoding="utf-8") as f:
        json.dump(M.RESULTS, f, ensure_ascii=False, indent=1, default=str)
    print("written", OUTP, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
