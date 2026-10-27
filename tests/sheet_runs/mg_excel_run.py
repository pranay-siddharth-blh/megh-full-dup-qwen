"""MGNREGA sheet (DATA-001..030) live, with the EXPECTED figures taken from the two raw Excels
(`raw_uc/Updated MNGREGA Expenditure WIth Year.xlsx`, `raw_uc/MGNREGA_Employment.xlsx`), not from
megh_db. Each case is asked in rotating wordings and year forms ("2024-25", "2024-2025", "FY 2024-25",
"24-25", "FY25", "financial year 2024-25"), across the hierarchy: the sheet's own level for each TC,
plus a cross-level sweep (state / district / block / constituency / village x 9 measures).
A figure that matches the DB but not the Excel is scored DATA-DIFF (a place assigned to another
block/district in megh_db), not a bot failure.

Expectations: built by the system python from the Excels (pandas):  <scratch>/mg_excel_expect.json
Usage (repo root, VPN): .venv/Scripts/python.exe -X utf8 tests/sheet_runs/mg_excel_run.py <expect.json> <out.json>"""
import asyncio
import json
import os
import sys

EXPECT, OUTP = sys.argv[1], sys.argv[2]
sys.argv = sys.argv[:1]
sys.path.insert(0, ".")
sys.path.insert(0, os.path.join(".", "tests", "sheet_runs"))
os.environ.setdefault("MG_CONC", "4")
import mg_run as M  # noqa: E402
from mg_run import run_case, has, has_name, fetch, fy_label  # noqa: E402
from tests._text_checks import first_of, has_phrase  # noqa: E402
from app import main as app_main  # noqa: E402

M.ONLY = set(os.environ.get("MGX_ONLY", "").split())   # e.g. MGX_ONLY="DATA-004 HIER-state"
X = json.load(open(EXPECT, encoding="utf-8"))
YEARS = [2022, 2023, 2024, 2025]
NOT_REC = ("not recorded", "not been recorded", "not available", "unrecorded", "not captured", "no data", "zero")
EXP_COLS = {"total_exp", "unskilled_wage_exp", "semi_skilled_wage_exp", "material_exp", "tax_exp", "admin_total_exp"}
# DB column per level for the live cross-check
DBCOL = {"district": "lgd_district", "block": "lgd_block", "village": "village_code"}


def yform(y, i):
    a, b = y, y + 1
    return [f"{a}-{str(b)[2:]}", f"{a}-{b}", f"FY {a}-{str(b)[2:]}", f"{str(a)[2:]}-{str(b)[2:]}",
            f"FY{str(b)[2:]}", f"financial year {a}-{str(b)[2:]}"][i % 6]


def xl(view, level, name, year, col):
    try:
        return X[view][level][name][str(year)][col]
    except KeyError:
        return 0.0


async def dbv(view, level, name, year, col):
    if level == "state":
        where, params = "TRUE", []
    elif level == "ac":
        where, params = (("assembly_constituency_name" if view == "v_employment" else "ac_name") + " = $1"), [name]
    else:
        where, params = f"UPPER({DBCOL[level]}::text) = $1", [name.upper()]
    q = f"SELECT COALESCE(SUM({col}),0)::float8 v FROM curated.{view} WHERE {where}"
    if year != "all":
        q += f" AND year_key = ${len(params) + 1}"
        params = params + [year]
    return (await fetch(q, params))[0]["v"]


async def both(level, name, year, col):
    view = "v_expenditure" if col in EXP_COLS else "v_employment"
    key = "exp" if col in EXP_COLS else "emp"
    return xl(key, level, name, year, col), await dbv(view, level, name, year, col)


def vcheck(exp_xl, exp_db, money=False, rel=0.005):
    def chk(rec):
        if has(rec, exp_xl, rel, money):
            return True, f"excel={exp_xl} (db={exp_db})"
        if exp_db is not None and abs((exp_db or 0) - (exp_xl or 0)) > 0.011 and has(rec, exp_db, rel, money):
            return True, f"DATA-DIFF matches db={exp_db}, excel={exp_xl}"
        return False, f"excel={exp_xl} db={exp_db}"
    return chk


def mcheck(pairs):
    """pairs: [(name, excel, db, money)] — every nonzero one must be present (Excel or DB figure)."""
    def chk(rec):
        miss, diff = [], []
        for n, ex, eb, money in pairs:
            if not ex and not eb:
                continue
            if has(rec, ex, 0.006, money):
                continue
            if has(rec, eb, 0.006, money):
                diff.append(n)
                continue
            miss.append(f"{n}={ex}")
        if miss:
            return False, "missing " + ", ".join(miss)
        return True, ("DATA-DIFF " + ",".join(diff)) if diff else "all present"
    return chk


def pct_check(num, den, num_db, den_db):
    p = round(100.0 * num / den, 2) if den else None
    pd_ = round(100.0 * num_db / den_db, 2) if den_db else None

    def chk(rec):
        if p is None:
            a = rec.get("answer") or ""
            return has_phrase(a, "cannot be calculated", "divided by is 0", "no households", "not recorded"), "den=0"
        if has(rec, p, 0.002):
            return True, f"excel%={p}"
        if pd_ is not None and pd_ != p and has(rec, pd_, 0.002):
            return True, f"DATA-DIFF db%={pd_} excel%={p}"
        return False, f"excel%={p} db%={pd_}"
    return chk, p


# ── sheet wordings, rotated per case ("different logics") ───────────────────
T = {
    "DATA-001": ["What was the total expenditure in {p} during {y}?", "How much MGNREGA money was spent in {p} village in {y}?",
                 "Total expenditure of {p} for {y}"],
    "DATA-005": ["How many households received employment in {p}?", "Number of households that got work in {p} village in {y}",
                 "households employed in {p} {y}"],
    "DATA-006": ["How many person-days were generated in {p}?", "Total person days in {p} village during {y}",
                 "What is the persondays figure for {p} in {y}?"],
    "DATA-007": ["How many job cards were issued in {p}?", "Job cards issued in {p} village in {y}?",
                 "How many job cards does {p} have in {y}?"],
    "DATA-008": ["How many women were provided employment in {p}?", "Women employment in {p} village during {y}",
                 "how many women got MGNREGA work in {p} in {y}"],
    "DATA-009": ["How many households completed 100 days in {p}?", "How many families finished 100 days of work in {p} in {y}?",
                 "100 days completed households in {p} village {y}"],
    "DATA-010": ["How much was spent on unskilled wages in {p} during {y}?", "Unskilled wage expenditure for {p} village in {y}",
                 "unskilled wages paid in {p} {y}?"],
    "DATA-011": ["How much was spent on materials in {p} during {y}?", "Material expenditure in {p} village for {y}",
                 "What did {p} spend on material in {y}?"],
    "DATA-012": ["How much was spent on semi-skilled wages in {p}?", "Semi-skilled wage spend in {p} in {y}",
                 "semi skilled wage expenditure of {p} village during {y}"],
    "DATA-022": ["Give me the expenditure breakdown for {p} during {y}.", "Break down the spending in {p} village for {y} by component",
                 "Show all expenditure heads for {p} in {y}"],
    "DATA-023": ["Was more spent on wages or materials in {p}?", "In {p} during {y}, did wages or material cost more?",
                 "Wages vs material expenditure in {p} village {y}"],
    "DATA-028": ["How much was spent and how many person-days were generated in {p} during {y}?",
                 "Expenditure and person-days for {p} village in {y}", "Total expenditure and total person days in {p} for {y}"],
    "DATA-002": ["What was the total expenditure in {p} during {y}?", "Total spending in {p} district in {y}",
                 "How much was spent under MGNREGA in {p} district for {y}?"],
    "DATA-015": ["How many total person-days were generated in {p} during {y}?", "person days generated in {p} district {y}",
                 "Total persondays of {p} in {y}"],
    "DATA-017": ["How many women received employment in {p} during {y}?", "Women employed in {p} district for {y}",
                 "number of women given work in {p} in {y}"],
    "DATA-018": ["How many job cards were issued in {p} during {y}?", "job cards in {p} district {y}",
                 "Total job cards issued in {p} for {y}"],
    "DATA-019": ["What percentage of employment persons were women in {p}?", "Women share of persons employed in {p} district in {y}",
                 "What % of workers were women in {p} during {y}?"],
    "DATA-021": ["What was the average number of person-days per employment household in {p}?",
                 "Average person days per household in {p} district for {y}", "person-days per household in {p} in {y}"],
    "DATA-030": ["Compare total expenditure and employment generated in {p} during {y}.",
                 "Expenditure versus person-days in {p} district for {y}", "Show spending and employment for {p} in {y}"],
    "DATA-003": ["What was the total expenditure in {p} during {y}?", "Total expenditure in {p} block for {y}",
                 "How much was spent in {p} block during {y}?"],
    "DATA-013": ["What was the administrative expenditure in {p} during {y}?", "Admin expenditure of {p} block in {y}",
                 "administrative spend in {p} block {y}"],
    "DATA-016": ["How many households received employment in {p} during {y}?", "households employed in {p} block in {y}",
                 "Number of households given work in {p} block during {y}"],
    "DATA-020": ["What percentage of employment households completed 100 days in {p}?",
                 "100-day completion rate of households in {p} block for {y}", "What % of households finished 100 days in {p} block in {y}?"],
    "DATA-029": ["Compare expenditure and person-days in {p} during {y}.", "Expenditure vs person days for {p} block in {y}",
                 "Show total spending and persondays in {p} block for {y}"],
    "DATA-004": ["How many persons received employment in {p} constituency during {y}?",
                 "Persons employed in {p} assembly constituency in {y}", "How many people got work in {p} AC for {y}?"],
    "DATA-014": ["Which villages in {p} constituency received employment during {y}?",
                 "List the villages of {p} assembly constituency that got employment in {y}",
                 "villages in {p} AC with MGNREGA employment {y}"],
}


def q(tc, i, p, y):
    t = T[tc][i % len(T[tc])]
    return t.format(p=p, y=y)


async def main():
    async with app_main.lifespan(app_main.app):
        C = []
        add = C.append
        vill_names = {n for n in X["names"]}

        # ── villages: 13 TCs x 24 villages ────────────────────────────────────
        for i, v in enumerate(X["villages"]):
            code, d = v["code"], v["district"]
            name = [v["name"].upper(), v["name"].title(), v["name"].lower()][i % 3]
            y = YEARS[i % 4]
            yw = YEARS[i % 3]
            lab = f"{v['name']} ({v['block']}, {d}) {fy_label(y)}"
            kw = dict(year=y, place=[v["name"]], level="village")

            async def B(col, yy=y):
                return await both("village", code, yy, col)
            for k, (tc, col, money) in enumerate([("DATA-001", "total_exp", True), ("DATA-005", "households_employed", False),
                                                  ("DATA-006", "person_days", False), ("DATA-007", "job_cards_issued_total", False),
                                                  ("DATA-009", "households_completed_100_days", False),
                                                  ("DATA-010", "unskilled_wage_exp", True), ("DATA-011", "material_exp", True),
                                                  ("DATA-012", "semi_skilled_wage_exp", True)]):
                ex, eb = await B(col)
                add(run_case(tc, lab, q(tc, i + k, name, yform(y, i + k)), vcheck(ex, eb, money), expected=ex, **kw))
            ex, eb = await B("women_employment_provided", yw)
            add(run_case("DATA-008", f"{v['name']} ({d}) {fy_label(yw)}", q("DATA-008", i, name, yform(yw, i)),
                         vcheck(ex, eb), expected=ex, year=yw, place=[v["name"]], level="village"))
            parts = [(c, *(await B(c)), True) for c in ("unskilled_wage_exp", "semi_skilled_wage_exp", "material_exp", "total_exp")]
            add(run_case("DATA-022", lab, q("DATA-022", i, name, yform(y, i + 3)), mcheck(parts),
                         expected={p[0]: p[1] for p in parts}, **kw))
            un, se, ma = parts[0][1], parts[1][1], parts[2][1]
            wages, winner = un + se, ("wage" if un + se > ma else "material")

            def wm(rec, wages=wages, ma=ma, un=un, winner=winner):
                if not wages and not ma:
                    return True, "both zero"
                ok = has(rec, ma, 0.006, True) and (has(rec, wages, 0.006, True) or has(rec, un, 0.006, True))
                first = first_of((rec.get("answer") or "").lower(), "wage", "material")
                return ok and first == winner, f"wages={wages:.2f} material={ma:.2f} winner={winner} first={first}"
            add(run_case("DATA-023", lab, q("DATA-023", i, name, yform(y, i + 4)), wm,
                         expected={"wages": wages, "material": ma}, **kw))
            add(run_case("DATA-028", lab, q("DATA-028", i, name, yform(y, i + 5)),
                         mcheck([("total_exp", *(await B("total_exp")), True), ("person_days", *(await B("person_days")), False)]),
                         expected="both", **kw))

        # same-name villages (2+ codes, different districts): the bot must ask; the right chip -> right figure
        dup = [(n, c) for n, c in X["names"].items() if 2 <= len(c) <= 3 and n.replace(" ", "").isalpha()
               and len({X["village_meta"][k]["district"] for k in c}) >= 2]
        dup.sort(key=lambda t: (len(t[0]) * 7919 + sum(map(ord, t[0]))) % 997)
        for n, codes in dup[:8]:
            code = codes[0]
            meta = X["village_meta"][code]
            ex, eb = await both("village", code, 2024, "total_exp")
            add(run_case("DATA-001", f"same-name {n} -> {meta['block']} ({meta['district']}) FY 2024-25",
                         f"What was the total expenditure in {n.title()} during 24-25?", vcheck(ex, eb, True),
                         year=2024, place=[n, meta["block"]], level="village", expected=ex))

        # ── districts: 7 TCs x 12 ─────────────────────────────────────────────
        for i, d in enumerate(sorted(X["exp"]["district"])):
            y, yw = YEARS[i % 4], YEARS[i % 3]
            name = d.title() if i % 2 else d
            kw = dict(year=y, place=[d.split()[0]], level="district")
            kww = dict(year=yw, place=[d.split()[0]], level="district")
            lab, labw = f"{d} {fy_label(y)}", f"{d} {fy_label(yw)}"
            for k, (tc, col, money) in enumerate([("DATA-002", "total_exp", True), ("DATA-015", "person_days", False),
                                                  ("DATA-018", "job_cards_issued_total", False)]):
                ex, eb = await both("district", d, y, col)
                add(run_case(tc, lab, q(tc, i + k, name, yform(y, i + k)), vcheck(ex, eb, money), expected=ex, **kw))
            ex, eb = await both("district", d, yw, "women_employment_provided")
            add(run_case("DATA-017", labw, q("DATA-017", i, name, yform(yw, i + 3)), vcheck(ex, eb), expected=ex, **kww))
            (w, wd), (p, pdb) = await both("district", d, yw, "women_employment_provided"), await both("district", d, yw, "persons_employed")
            chk, pv = pct_check(w, p, wd, pdb)
            add(run_case("DATA-019", labw, q("DATA-019", i, name, yform(yw, i + 4)), chk, expected=pv, **kww))
            (pdx, pdd), (hx, hd) = await both("district", d, yw, "person_days"), await both("district", d, yw, "households_employed")
            avg, avg_db = (round(pdx / hx, 2) if hx else None), (round(pdd / hd, 2) if hd else None)
            add(run_case("DATA-021", labw, q("DATA-021", i, name, yform(yw, i + 5)), vcheck(avg, avg_db, rel=0.002),
                         expected=avg, **kww))
            te = await both("district", d, y, "total_exp")
            emps = [await both("district", d, y, c) for c in ("person_days", "households_employed", "persons_employed")]

            def ce(rec, te=te, emps=emps):
                ok_e = has(rec, te[0], 0.006, True) or has(rec, te[1], 0.006, True)
                ok_m = any(has(rec, a) or has(rec, b) for a, b in emps)
                return ok_e and ok_m, f"exp_ok={ok_e} employment_ok={ok_m}"
            add(run_case("DATA-030", lab, q("DATA-030", i, name, yform(y, i + 2)), ce, expected=te[0], **kw))

        # ── blocks: 5 TCs x 55 ────────────────────────────────────────────────
        for i, b in enumerate(sorted(X["exp"]["block"])):
            y = YEARS[i % 4]
            collide = b in vill_names
            if collide:
                ask = f"{b.title()} block" if i % 2 == 0 else b.title()
            else:
                ask = b if i % 2 else b.title()
            kw = dict(year=y, place=[b], level="block")
            lab = f"{b}{' [also a village]' if collide else ''} as '{ask}' {fy_label(y)}"

            def qb(tc, k):
                t = T[tc][(i + k) % 3]
                # a wording that already says "block" keeps the bare name
                p = ask.replace(" block", "") if " block" in t and ask.endswith(" block") else ask
                return t.format(p=p, y=yform(y, i + k))
            ex, eb = await both("block", b, y, "total_exp")
            add(run_case("DATA-003", lab, qb("DATA-003", 0), vcheck(ex, eb, True), expected=ex, **kw))
            ax, ad = await both("block", b, y, "admin_total_exp")

            def admin(rec, ax=ax, ad=ad):
                a = (rec.get("answer") or "").lower()
                return "admin" in a and (has(rec, ax, 0.006, True) or has(rec, ad, 0.006, True)), f"admin excel={ax} db={ad}"
            add(run_case("DATA-013", lab, qb("DATA-013", 1), admin, expected=ax, **kw))
            ex, eb = await both("block", b, y, "households_employed")
            add(run_case("DATA-016", lab, qb("DATA-016", 2), vcheck(ex, eb), expected=ex, **kw))
            (h1, h1d), (hh, hhd) = await both("block", b, y, "households_completed_100_days"), await both("block", b, y, "households_employed")
            chk, pv = pct_check(h1, hh, h1d, hhd)
            add(run_case("DATA-020", lab, qb("DATA-020", 3), chk, expected=pv, **kw))
            add(run_case("DATA-029", lab, qb("DATA-029", 4),
                         mcheck([("total_exp", *(await both("block", b, y, "total_exp")), True),
                                 ("person_days", *(await both("block", b, y, "person_days")), False)]), expected="both", **kw))

        # ── assembly constituencies: 2 TCs x 56 ──────────────────────────────
        for i, a in enumerate(sorted(X["emp"]["ac"])):
            y = YEARS[i % 4]
            kw = dict(year=y, place=[a.split()[0]], level="ac")
            ex, eb = await both("ac", a, y, "persons_employed")
            add(run_case("DATA-004", f"{a} {fy_label(y)}", q("DATA-004", i, a.title(), yform(y, i)), vcheck(ex, eb),
                         expected=ex, **kw))
            nv = (await fetch("""SELECT COUNT(DISTINCT village_code) n FROM curated.v_employment
                                 WHERE assembly_constituency_name=$1 AND year_key=$2 AND persons_employed > 0""", [a, y]))[0]["n"]

            def vil(rec, nv=nv):
                n = rec.get("n_rows") or 0
                return n == nv or has(rec, nv), f"villages expected={nv} rows={n}"
            add(run_case("DATA-014", f"{a} {fy_label(y)}", q("DATA-014", i + 1, a.title(), yform(y, i + 1)), vil,
                         expected=nv, **kw))

        # ── rankings: 4 TCs x 4 years, 2 wordings each ───────────────────────
        def top(view, level, col, y):
            items = [(n, v.get(str(y), {}).get(col, 0)) for n, v in X[view][level].items()]
            return max(items, key=lambda t: t[1])
        RANK = [("DATA-024", "exp", "district", "total_exp", True,
                 ["Which district had the highest expenditure during {y}?", "Top district by MGNREGA spending in {y}"]),
                ("DATA-025", "emp", "block", "person_days", False,
                 ["Which block generated the highest person-days during {y}?", "Which block had the most persondays in {y}?"]),
                ("DATA-026", "emp", "village", "person_days", False,
                 ["Which village generated the highest person-days during {y}?", "Village with maximum person days in {y}"]),
                ("DATA-027", "emp", "district", "women_employment_provided", False,
                 ["Which district had the highest women employment during {y}?", "Top district for women employment in {y}"])]
        for tc, view, level, col, money, tpls in RANK:
            for k, y in enumerate(YEARS):
                for j, t in enumerate(tpls):
                    n, v = top(view, level, col, y)
                    label_n = X["village_meta"].get(n, {}).get("name", n) if level == "village" else n
                    if v > 0:
                        def chk(r, n=label_n, v=v, money=money):
                            return has_name(r, n) and has(r, v, 0.006, money), f"exp {n} {v}"
                    else:   # 2025-26 women: not recorded at source
                        def chk(r):
                            return has_phrase(r.get("answer") or "", *NOT_REC), "expects 'not recorded'"
                    add(run_case(tc, f"{fy_label(y)} w{j}", t.format(y=yform(y, k + j)), chk, year=y,
                                 expected={"name": label_n, "value": v}))

        # ── hierarchy sweep: 9 measures x every level (state + 3 samples per level) ──
        MEAS = [("total_exp", True, "What was the total MGNREGA expenditure in {p} in {y}?"),
                ("unskilled_wage_exp", True, "How much was spent on unskilled wages in {p} in {y}?"),
                ("material_exp", True, "What was the material expenditure in {p} in {y}?"),
                ("person_days", False, "How many person-days were generated in {p} in {y}?"),
                ("households_employed", False, "How many households got MGNREGA employment in {p} in {y}?"),
                ("persons_employed", False, "How many persons were employed under MGNREGA in {p} in {y}?"),
                ("households_completed_100_days", False, "How many households completed 100 days of work in {p} in {y}?"),
                ("job_cards_issued_total", False, "How many MGNREGA job cards were issued in {p} in {y}?"),
                ("women_employment_provided", False, "How many women got MGNREGA employment in {p} in {y}?")]
        ds = sorted(X["exp"]["district"])[::4]
        bs = [b for b in sorted(X["exp"]["block"]) if b not in vill_names][::18]
        acs = sorted(X["emp"]["ac"])[::19]
        vs = X["villages"][1::8]
        SAMPLES = ([("state", "MEGHALAYA", "Meghalaya", None)]
                   + [("district", d, f"{d.title()} district", d.split()[0]) for d in ds]
                   + [("block", b, f"{b.title()} block", b) for b in bs]
                   + [("ac", a, f"{a.title()} constituency", a.split()[0]) for a in acs]
                   + [("village", v["code"], f"{v['name']} village", v["name"]) for v in vs])
        for si, (level, key, phrase, place) in enumerate(SAMPLES):
            for mi, (col, money, tpl) in enumerate(MEAS):
                y = YEARS[(si + mi) % (3 if col == "women_employment_provided" else 4)]
                if level == "ac" and col in EXP_COLS:
                    ex, eb = (await dbv("v_expenditure", "ac", key, y, col),) * 2   # Excel has no AC for expenditure
                else:
                    ex, eb = await both(level, key, y, col)
                add(run_case("HIER-" + level, f"{phrase} | {col} | {fy_label(y)}", tpl.format(p=phrase, y=yform(y, si + mi)),
                             vcheck(ex, eb, money), expected=ex, year=y,
                             place=[place] if place else None, level=None if level in ("state", "ac") else level))
            # all years combined, one measure per sample
            col, money, tpl = MEAS[si % len(MEAS)]
            if col == "job_cards_issued_total":   # cumulative per year (KI-293): an all-years sum is not asked
                col, money, tpl = MEAS[0]
            if level == "ac" and col in EXP_COLS:
                ex = eb = await dbv("v_expenditure", "ac", key, "all", col)
            else:
                ex, eb = await both(level, key, "all", col)
            add(run_case("HIER-" + level, f"{phrase} | {col} | all years", tpl.format(p=phrase, y="all years combined"),
                         vcheck(ex, eb, money), expected=ex, year="all",
                         place=[place] if place else None, level=None if level in ("state", "ac") else level))

        M.log(f"running {len(C)} conversations")
        await asyncio.gather(*C)
    with open(OUTP, "w", encoding="utf-8") as f:
        json.dump(M.RESULTS, f, ensure_ascii=False, indent=1, default=str)
    M.log("written", OUTP)


if __name__ == "__main__":
    asyncio.run(main())
