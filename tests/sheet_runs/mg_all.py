"""EVERY MGNREGA village (6,491) through the live LangGraph pipeline, one question
each. The question shape rotates over the sheet's 12 village test cases (DATA-001,
005-012, 022, 023, 028) and the FY over all four years; the name's case rotates
UPPER / Title / lower, which is also General TC-023 (case-insensitive entities)
for every village. Shared names must draw a which-village pause offering the
right village (block + district in the chip); the chip is then taken.
Expected values: one grouped query per view and year, from megh_db.

Usage (repo root): mg_all.py [start end]  -> mg_all_results[_start_end].json
Resumable: villages already in the output file are skipped."""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case, value_check, multi_check, has, fy, YEARS  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set()
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("MG_ALL_OUT", "mg_all_results.json"))

EMP_COLS = ["households_employed", "persons_employed", "person_days", "job_cards_issued_total",
            "households_completed_100_days", "women_employment_provided"]
EXP_COLS = ["total_exp", "unskilled_wage_exp", "semi_skilled_wage_exp", "material_exp"]
# (tc, view needed, uses the year in the question)
SHAPES = [("DATA-001", "exp"), ("DATA-005", "emp"), ("DATA-006", "emp"), ("DATA-007", "emp"),
          ("DATA-008", "emp"), ("DATA-009", "emp"), ("DATA-010", "exp"), ("DATA-011", "exp"),
          ("DATA-012", "exp"), ("DATA-022", "exp"), ("DATA-023", "exp"), ("DATA-028", "both")]


def case_name(name, i):
    return [name.upper(), name.title(), name.lower()][i % 3]


async def main():
    start = int(sys.argv[1]) if len(sys.argv) > 2 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else None
    async with app_main.lifespan(app_main.app):
        emp, exp = {}, {}
        for y in YEARS:
            for r in await fetch(f"SELECT village_code, {', '.join(f'COALESCE(SUM({c}),0)::float8 AS {c}' for c in EMP_COLS)} "
                                 "FROM curated.v_employment WHERE village_code IS NOT NULL AND year_key=$1 GROUP BY 1", [y]):
                emp[(r["village_code"], y)] = dict(r)
            for r in await fetch(f"SELECT village_code, {', '.join(f'COALESCE(SUM({c}),0)::float8 AS {c}' for c in EXP_COLS)} "
                                 "FROM curated.v_expenditure WHERE village_code IS NOT NULL AND year_key=$1 GROUP BY 1", [y]):
                exp[(r["village_code"], y)] = dict(r)
        villages = await fetch("""
            SELECT village_code, MIN(lgd_village_name) AS name, MIN(lgd_block) AS block, MIN(lgd_district) AS district
            FROM (SELECT village_code, lgd_village_name, lgd_block, lgd_district FROM curated.v_employment
                  UNION ALL SELECT village_code, lgd_village_name, lgd_block, lgd_district FROM curated.v_expenditure) u
            WHERE village_code IS NOT NULL GROUP BY 1 ORDER BY 1""")
        villages = villages[start:end]
        only_codes = None
        if os.environ.get("MG_ONLY_CODES"):
            only_codes = {int(x) for x in open(os.environ["MG_ONLY_CODES"]).read().split()}
        done = set()
        if os.path.exists(OUT):
            prev = json.load(open(OUT, encoding="utf-8"))
            mg_run.RESULTS.update(prev)
            done = {c["code"] for cs in prev.values() for c in cs if "code" in c}
        mg_run.log(f"{len(villages)} villages ({len(done)} already done)")
        T = []
        for i, v in enumerate(villages):
            code = v["village_code"]
            if code in done or (only_codes is not None and code not in only_codes):
                continue
            in_emp = any((code, y) in emp for y in YEARS)
            in_exp = any((code, y) in exp for y in YEARS)
            shapes = [s for s in SHAPES if (s[1] == "emp" and in_emp) or (s[1] == "exp" and in_exp)
                      or (s[1] == "both" and in_emp and in_exp)]
            tc, view = shapes[(i + start) % len(shapes)]
            y = YEARS[(i + start) % 4]
            if tc == "DATA-008":
                y = YEARS[(i + start) % 3]          # 2025-26 women unrecorded at source
            nm = case_name(v["name"], i + start)
            m = emp.get((code, y), {c: 0.0 for c in EMP_COLS})
            e = exp.get((code, y), {c: 0.0 for c in EXP_COLS})
            st = i + start
            kw = dict(year=y, place=[v["name"], v["block"] or ""], level="village")
            lab = f"{v['name']} [{code}] {v['block']}/{v['district']} FY {y}-{str(y + 1)[2:]} as '{nm}'"
            if tc == "DATA-001":
                q, chk, ex = f"What was the total expenditure in {nm} during {fy(y, st)}?", value_check(e["total_exp"], True), e["total_exp"]
            elif tc == "DATA-005":
                q, chk, ex = f"How many households received employment in {nm}?", value_check(m["households_employed"]), m["households_employed"]
            elif tc == "DATA-006":
                q, chk, ex = f"How many person-days were generated in {nm}?", value_check(m["person_days"]), m["person_days"]
            elif tc == "DATA-007":
                q, chk, ex = f"How many job cards were issued in {nm}?", value_check(m["job_cards_issued_total"]), m["job_cards_issued_total"]
            elif tc == "DATA-008":
                q, chk, ex = f"How many women were provided employment in {nm}?", value_check(m["women_employment_provided"]), m["women_employment_provided"]
            elif tc == "DATA-009":
                q, chk, ex = f"How many households completed 100 days in {nm}?", value_check(m["households_completed_100_days"]), m["households_completed_100_days"]
            elif tc == "DATA-010":
                q, chk, ex = f"How much was spent on unskilled wages in {nm} during {fy(y, st + 1)}?", value_check(e["unskilled_wage_exp"], True), e["unskilled_wage_exp"]
            elif tc == "DATA-011":
                q, chk, ex = f"How much was spent on materials in {nm} during {fy(y, st + 2)}?", value_check(e["material_exp"], True), e["material_exp"]
            elif tc == "DATA-012":
                q, chk, ex = f"How much was spent on semi-skilled wages in {nm}?", value_check(e["semi_skilled_wage_exp"], True), e["semi_skilled_wage_exp"]
            elif tc == "DATA-022":
                q = f"Give me the expenditure breakdown for {nm} during {fy(y, st + 3)}."
                chk = multi_check([("unskilled", e["unskilled_wage_exp"], True), ("semi-skilled", e["semi_skilled_wage_exp"], True),
                                   ("material", e["material_exp"], True), ("total", e["total_exp"], True)])
                ex = dict(e)
            elif tc == "DATA-023":
                wages, mat = e["unskilled_wage_exp"] + e["semi_skilled_wage_exp"], e["material_exp"]

                def chk(rec, wages=wages, mat=mat, unsk=e["unskilled_wage_exp"]):
                    ans = (rec.get("answer") or "").lower()
                    if not wages and not mat:
                        return bool(re.search(r"\b0(?:\.0+)?\s*lakh|no (?:expenditure|spending)|zero", ans)), "both 0"
                    ok_v = has(rec, mat, 0.006, True) and (has(rec, wages, 0.006, True) or has(rec, unsk, 0.006, True))
                    win = "wage" if wages > mat else "material"
                    first = re.search(r"(wage|material)", ans)
                    return ok_v and bool(first) and first.group(1) == win, f"wages={wages:.2f} mat={mat:.2f}"
                q, ex = f"Was more spent on wages or materials in {nm}?", {"wages": wages, "material": mat}
            else:
                q = f"How much was spent and how many person-days were generated in {nm} during {fy(y, st)}?"
                chk = multi_check([("total_exp", e["total_exp"], True), ("person_days", m["person_days"], False)])
                ex = {"total_exp": e["total_exp"], "person_days": m["person_days"]}
            T.append(_case(tc, lab, q, chk, ex, code, kw))
        mg_run.log(f"running {len(T)} conversations")
        # checkpoint the results every 200 cases so a long run can resume
        for k in range(0, len(T), 200):
            await asyncio.gather(*T[k:k + 200])
            json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            mg_run.log(f"checkpoint {min(k + 200, len(T))}/{len(T)}")
    mg_run.log("written", OUT)


async def _case(tc, lab, q, chk, ex, code, kw):
    await run_case(tc, lab, q, _zero_ok(chk, ex), expected=ex, **kw)
    mg_run.RESULTS[tc][-1]["code"] = code


def _zero_ok(chk, expected):
    """A village with no record for the year: 0 stated, or 'no record / not recorded' said plainly."""
    def wrapped(rec):
        ok, note = chk(rec)
        if ok:
            return ok, note
        zero = (expected == 0) or (isinstance(expected, dict) and not any(expected.values()))
        if zero and re.search(r"\b0(?:\.0+)?\b|\bno\b[^.]{0,40}\b(?:record|data|employment|expenditure)|\bzero\b|"
                              r"not recorded|nothing (?:was )?(?:recorded|spent)|(?:couldn.t|could not) find any matching records", rec.get("answer") or "", re.I):
            return True, note + " (zero stated)"
        return ok, note
    return wrapped


asyncio.run(main())
