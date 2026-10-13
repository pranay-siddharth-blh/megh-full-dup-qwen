"""MGNREGA sheet (DATA-001..DATA-030) through the live LangGraph pipeline, every
expected figure computed from megh_db. Hierarchy: 2 villages per district (24),
every block (55), every district (12), every assembly constituency, every year.
The question wording is the sheet's own (no scheme name). A pause is answered the
way the UI does (chip question): year -> the case's FY, which-place -> the case's
place, which-scheme -> MGNREGA (recorded as a defect for MGNREGA-only measures).

Usage (repo root): mg_run.py [DATA-001 ...]   -> mg_results.json"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Conv, close, fetch, numbers_in, text_numbers  # noqa: E402
from app import main as app_main  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("MG_OUT", "mg_results.json"))
SEM = asyncio.Semaphore(int(os.environ.get("MG_CONC", "4")))
RESULTS: dict = {}
YEARS = [2022, 2023, 2024, 2025]
ONLY = set(sys.argv[1:])


def log(*a):
    print(*a, flush=True)


def fy(y, style=0):
    a, b = y, y + 1
    return [f"{a}-{str(b)[2:]}", f"{a}-{b}", f"FY {a}-{str(b)[2:]}", f"{str(a)[2:]}-{str(b)[2:]}"][style % 4]


def fy_label(y):
    return f"FY {y}-{str(y + 1)[2:]}"


def vals(rec):
    return numbers_in(rec.get("rows")) + text_numbers(rec.get("answer"))


def has(rec, expected, rel=0.005, money=False):
    if expected is None:
        return False
    forms = [expected] + ([expected / 100.0, expected * 100000.0] if money else [])
    return any(close(c, f, rel) for c in vals(rec) for f in forms)


def has_name(rec, name):
    blob = (rec.get("answer") or "") + " " + json.dumps(rec.get("rows") or [], default=str)
    return re.sub(r"\W", "", name).lower() in re.sub(r"\W", "", blob).lower()


# ── the conversation driver ─────────────────────────────────────────────────
async def run_case(tc, label, question, check, *, year=None, place=None, level=None, expected=None,
                   mgnrega_only=True, code=None):
    """check(rec) -> (ok, note). Pauses are answered as a user tapping the right chip."""
    if ONLY and tc not in ONLY:
        return
    async with SEM:
        c = Conv()
        rec = await c.ask(question)
        notes = []
        for _ in range(3):
            if rec["kind"] != "pause":
                break
            rule, labels, qs = rec.get("rule"), rec.get("options") or [], rec.get("option_qs") or []
            pick = None
            if rule == "year-not-specified" and year == "all":
                pick = next((q for l, q in zip(labels, qs) if l.lower().startswith("all ")), None)
                notes.append("asked year -> all years")
            elif rule == "year-not-specified" and year is not None:
                pick = next((q for l, q in zip(labels, qs) if l == fy_label(year)), None)
                notes.append(f"asked year -> {fy_label(year)}")
            elif rule == "focus-scheme-ambiguous":
                want_s = os.environ.get("SHEET_SCHEME", "Focus Plus")
                pick = next((q for l, q in zip(labels, qs) if l.startswith(want_s)), None)
                notes.append(f"asked Focus Legacy or Plus -> {want_s}")
            elif rule in ("scheme-not-specified", "scheme-not-available") :
                want_s = os.environ.get("SHEET_SCHEME", "MGNREGA")
                pick = next((q for l, q in zip(labels, qs) if l.startswith(want_s)), None)
                notes.append("ASKED WHICH SCHEME" + (" (defect: MGNREGA-only measure)" if mgnrega_only else ""))
            elif rule == "scope-not-specified" and not place:
                pick = next((q for l, q in zip(labels, qs) if "all of meghalaya" in l.lower()
                             or "statewide" in l.lower()), None)
                notes.append("asked area -> All of Meghalaya")
            elif rule == "ranking-count-not-specified":
                pick = next((q for l, q in zip(labels, qs) if l.lower() == "top 5"), None)
                notes.append("asked how many -> Top 5")
            elif rule == "village-or-outside-place":
                # e.g. "Manipur" / "Burma": a village AND a place outside Meghalaya — a fair question
                pick = next((q for l, q in zip(labels, qs) if "village" in l.lower()), None)
                notes.append("asked village-or-outside-place -> village")
            elif rule == "ac-narrow-scope":
                pick = next((q for l, q in zip(labels, qs) if l.lower().startswith("the whole")), None)
                notes.append("EXTRA PAUSE whole-or-part constituency (defect)")
            elif rule in ("entity-ambiguous", "scope-not-specified", "region-needs-district") and place:
                want = [w.lower() for w in place]
                cand = [(l, q) for l, q in zip(labels, qs) if all(w in (l + " " + (q or "")).lower() for w in want)]
                if level:
                    lv = [(l, q) for l, q in cand if level in l.lower()]
                    cand = lv or cand
                if len(want) > 1 and want[1]:
                    # a village named like its block ("MAWHATI — MAWHATI block" vs "MAWHATI — RANIKOR block")
                    bk = [(l, q) for l, q in cand if f"{want[1]} block" in (l + " " + (q or "")).lower()]
                    cand = bk or cand
                if code is not None:
                    # twin villages (same name, same block) are told apart by the LGD code on the chip
                    cc = [(l, q) for l, q in cand if f"LGD {code}" in (l + " " + (q or ""))]
                    cand = cc or cand
                if not cand and level:
                    # a level chip names only the place ("The Baghmara village")
                    nm = want[0]
                    cand = [(l, q) for l, q in zip(labels, qs)
                            if nm in l.lower() and level in l.lower()]
                pick = cand[0][1] if cand else None
                notes.append(f"asked {rule} -> {cand[0][0] if cand else 'NO MATCHING OPTION'}")
            if not pick:
                notes.append(f"unanswerable pause {rule}: {labels[:6]}")
                break
            rec = await c.ask(pick)
        if rec["kind"] == "answer" or (expected == 0 and rec.get("rule") == "year-out-of-range"):
            # a year the scheme holds no data for: "no data is held for <year>" IS the answer
            ok, note = check(rec)
        else:
            ok, note = False, f"ended in {rec['kind']} {rec.get('rule') or ''}"
        ents = rec.get("entities") or {}
        level_ok = None
        if level and rec["kind"] == "answer":
            level_ok = {"district": bool(ents.get("district")) and not ents.get("block") and not ents.get("village_code"),
                        "block": bool(ents.get("block")) and not ents.get("village_code"),
                        "village": bool(ents.get("village_code") or ents.get("village_code_list")),
                        "ac": True}.get(level)
        scheme_defect = any("defect" in n for n in notes)
        RESULTS.setdefault(tc, []).append({
            "label": label, "turns": c.turns, "expected": expected, "ok": bool(ok) and level_ok is not False,
            "value_ok": bool(ok), "level_ok": level_ok, "note": note, "pause_notes": notes,
            "scheme_defect": scheme_defect})
        log(f"{tc} | {label} | {'OK ' if ok and level_ok is not False else 'BAD'} | {'; '.join(notes)} | "
            f"{note} | {(rec.get('answer') or '')[:100]!r}")


def value_check(expected, money=False, rel=0.005):
    def chk(rec):
        return has(rec, expected, rel, money), f"exp={expected}"
    return chk


def multi_check(pairs):
    """pairs: [(name, expected, money)] — every nonzero one must be present."""
    def chk(rec):
        miss = [n for n, e, m in pairs if e and not has(rec, e, 0.006, m)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


# ── DB expectations ────────────────────────────────────────────────────────
async def agg(view, cols, where, params, year):
    sel = ", ".join(f"COALESCE(SUM({c}),0)::float8 AS {c}" for c in cols)
    q = f"SELECT {sel} FROM curated.{view} WHERE {where}"
    if year is not None:
        q += f" AND year_key = ${len(params) + 1}"
        params = params + [year]
    r = await fetch(q, params)
    return r[0]


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        add = T.append
        districts = [r["d"] for r in await fetch("SELECT DISTINCT lgd_district d FROM curated.v_expenditure ORDER BY 1")]
        blocks = await fetch("""SELECT lgd_block b, MIN(lgd_district) d FROM curated.v_expenditure
                                WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY 1""")
        village_names = {r["n"] for r in await fetch(
            "SELECT DISTINCT UPPER(lgd_village_name) n FROM curated.v_employment")}
        # 2 villages per district, name unique statewide, present in both views every year
        villages = await fetch("""
            WITH u AS (SELECT UPPER(lgd_village_name) n FROM curated.v_employment
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 ue AS (SELECT UPPER(lgd_village_name) n FROM curated.v_expenditure
                        GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 c AS (SELECT e.village_code, MIN(e.lgd_village_name) name, MIN(e.lgd_district) d
                       FROM curated.v_employment e
                       JOIN u ON u.n = UPPER(e.lgd_village_name) JOIN ue ON ue.n = u.n
                       WHERE e.village_code IS NOT NULL AND LENGTH(e.lgd_village_name) >= 5
                         AND e.lgd_village_name !~ '[^A-Za-z ]'
                       GROUP BY 1 HAVING COUNT(DISTINCT e.year_key)=4 AND SUM(e.person_days) > 0),
                 x AS (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY d ORDER BY md5(name)) rn FROM c
                       WHERE c.village_code IN (SELECT village_code FROM curated.v_expenditure
                                                GROUP BY 1 HAVING COUNT(DISTINCT year_key)=4))
            SELECT village_code, name, d FROM x WHERE rn <= 2 ORDER BY d, name""")
        acs = [r["a"] for r in await fetch("""SELECT DISTINCT assembly_constituency_name a FROM curated.v_employment
                                              WHERE assembly_constituency_name IS NOT NULL ORDER BY 1""")]
        log(f"{len(districts)} districts, {len(blocks)} blocks, {len(villages)} villages, {len(acs)} ACs")

        # ── village cases ───────────────────────────────────────────────────
        for i, v in enumerate(villages):
            code, d = v["village_code"], v["d"]
            name = v["name"].upper() if i % 2 == 0 else v["name"].title()
            y = YEARS[i % 4]
            yw = YEARS[i % 3]                         # women: 2025-26 is unrecorded at source
            st = i
            W, P = "village_code = $1", [code]
            e = await agg("v_expenditure", ["total_exp", "unskilled_wage_exp", "semi_skilled_wage_exp",
                                            "material_exp"], W, P, y)
            m = await agg("v_employment", ["households_employed", "person_days", "job_cards_issued_total",
                                           "households_completed_100_days", "women_employment_provided"], W, P, y)
            mw = await agg("v_employment", ["women_employment_provided"], W, P, yw)
            kw = dict(year=y, place=[v["name"]], level="village")
            lab = f"{name} ({d}) {fy_label(y)}"
            add(run_case("DATA-001", lab, f"What was the total expenditure in {name} during {fy(y, st)}?",
                         value_check(e["total_exp"], True), expected=e["total_exp"], **kw))
            add(run_case("DATA-005", lab, f"How many households received employment in {name}?",
                         value_check(m["households_employed"]), expected=m["households_employed"], **kw))
            add(run_case("DATA-006", lab, f"How many person-days were generated in {name}?",
                         value_check(m["person_days"]), expected=m["person_days"], **kw))
            add(run_case("DATA-007", lab, f"How many job cards were issued in {name}?",
                         value_check(m["job_cards_issued_total"]), expected=m["job_cards_issued_total"], **kw))
            add(run_case("DATA-008", f"{name} ({d}) {fy_label(yw)}", f"How many women were provided employment in {name}?",
                         value_check(mw["women_employment_provided"]), expected=mw["women_employment_provided"],
                         year=yw, place=[v["name"]], level="village"))
            add(run_case("DATA-009", lab, f"How many households completed 100 days in {name}?",
                         value_check(m["households_completed_100_days"]),
                         expected=m["households_completed_100_days"], **kw))
            add(run_case("DATA-010", lab, f"How much was spent on unskilled wages in {name} during {fy(y, st + 1)}?",
                         value_check(e["unskilled_wage_exp"], True), expected=e["unskilled_wage_exp"], **kw))
            add(run_case("DATA-011", lab, f"How much was spent on materials in {name} during {fy(y, st + 2)}?",
                         value_check(e["material_exp"], True), expected=e["material_exp"], **kw))
            add(run_case("DATA-012", lab, f"How much was spent on semi-skilled wages in {name}?",
                         value_check(e["semi_skilled_wage_exp"], True), expected=e["semi_skilled_wage_exp"], **kw))
            add(run_case("DATA-022", lab, f"Give me the expenditure breakdown for {name} during {fy(y, st + 3)}.",
                         multi_check([("unskilled", e["unskilled_wage_exp"], True),
                                      ("semi-skilled", e["semi_skilled_wage_exp"], True),
                                      ("material", e["material_exp"], True), ("total", e["total_exp"], True)]),
                         expected=dict(e), **kw))
            wages = e["unskilled_wage_exp"] + e["semi_skilled_wage_exp"]
            winner = "wage" if wages > e["material_exp"] else "material"

            def wm_check(rec, wages=wages, mat=e["material_exp"], winner=winner, e_unsk=e["unskilled_wage_exp"]):
                ans = (rec.get("answer") or "").lower()
                vals_ok = has(rec, mat, 0.006, True) and (has(rec, wages, 0.006, True)
                                                          or has(rec, e_unsk, 0.006, True))
                first = re.search(r"(wage|material)", ans)
                right = bool(first) and first.group(1) == winner
                return vals_ok and right, f"wages={wages:.2f} material={mat:.2f} winner={winner} first_named={first.group(1) if first else None}"
            add(run_case("DATA-023", lab, f"Was more spent on wages or materials in {name}?", wm_check,
                         expected={"wages": wages, "material": e["material_exp"]}, **kw))
            add(run_case("DATA-028", lab, f"How much was spent and how many person-days were generated in {name} "
                                          f"during {fy(y, st)}?",
                         multi_check([("total_exp", e["total_exp"], True), ("person_days", m["person_days"], False)]),
                         expected={"total_exp": e["total_exp"], "person_days": m["person_days"]}, **kw))

        # same-name villages: the bot must ask which one; the right option must give the right figure
        dups = await fetch("""
            WITH n AS (SELECT UPPER(lgd_village_name) n FROM curated.v_expenditure WHERE year_key=2024
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code) BETWEEN 2 AND 3 AND COUNT(DISTINCT lgd_district) >= 2)
            SELECT e.village_code, MIN(e.lgd_village_name) name, MIN(e.lgd_block) b, MIN(e.lgd_district) d,
                   SUM(e.total_exp)::float8 t
            FROM curated.v_expenditure e JOIN n ON n.n = UPPER(e.lgd_village_name)
            WHERE e.year_key=2024 AND e.lgd_village_name !~ '[^A-Za-z ]' GROUP BY 1 ORDER BY md5(MIN(e.lgd_village_name)) LIMIT 8""")
        for v in dups:
            add(run_case("DATA-001", f"same-name {v['name']} -> {v['b']} ({v['d']}) FY 2024-25",
                         f"What was the total expenditure in {v['name']} during 2024-25?",
                         value_check(v["t"], True), year=2024, place=[v["name"], v["b"]], level="village",
                         expected=v["t"]))

        # ── district cases ──────────────────────────────────────────────────
        for i, d in enumerate(districts):
            y, yw, name = YEARS[i % 4], YEARS[i % 3], (d.title() if i % 2 else d)
            W, P = "lgd_district = $1", [d]
            e = await agg("v_expenditure", ["total_exp"], W, P, y)
            m = await agg("v_employment", ["person_days", "job_cards_issued_total", "households_employed",
                                           "persons_employed"], W, P, y)
            mw = await agg("v_employment", ["women_employment_provided", "persons_employed", "person_days",
                                            "households_employed"], W, P, yw)
            kw = dict(year=y, place=[d.split()[0]], level="district")
            lab = f"{d} {fy_label(y)}"
            add(run_case("DATA-002", lab, f"What was the total expenditure in {name} during {fy(y, i)}?",
                         value_check(e["total_exp"], True), expected=e["total_exp"], **kw))
            add(run_case("DATA-015", lab, f"How many total person-days were generated in {name} during {fy(y, i + 1)}?",
                         value_check(m["person_days"]), expected=m["person_days"], **kw))
            add(run_case("DATA-017", f"{d} {fy_label(yw)}", f"How many women received employment in {name} during {fy(yw, i + 2)}?",
                         value_check(mw["women_employment_provided"]), expected=mw["women_employment_provided"],
                         year=yw, place=[d.split()[0]], level="district"))
            add(run_case("DATA-018", lab, f"How many job cards were issued in {name} during {fy(y, i + 3)}?",
                         value_check(m["job_cards_issued_total"]), expected=m["job_cards_issued_total"], **kw))
            pct = 100.0 * mw["women_employment_provided"] / mw["persons_employed"] if mw["persons_employed"] else None
            add(run_case("DATA-019", f"{d} {fy_label(yw)}", f"What percentage of employment persons were women in {name}?",
                         value_check(round(pct, 2) if pct is not None else None, rel=0.002), expected=pct,
                         year=yw, place=[d.split()[0]], level="district"))
            avg = mw["person_days"] / mw["households_employed"] if mw["households_employed"] else None
            add(run_case("DATA-021", f"{d} {fy_label(yw)}",
                         f"What was the average number of person-days per employment household in {name}?",
                         value_check(round(avg, 2) if avg else None, rel=0.002), expected=avg,
                         year=yw, place=[d.split()[0]], level="district"))

            def emp_check(rec, e=e, m=m):
                ok_e = has(rec, e["total_exp"], 0.006, True)
                ok_m = any(has(rec, m[k]) for k in ("person_days", "households_employed", "persons_employed"))
                return ok_e and ok_m, f"exp_ok={ok_e} employment_ok={ok_m}"
            add(run_case("DATA-030", lab, f"Compare total expenditure and employment generated in {name} during {fy(y, i)}.",
                         emp_check, expected={"total_exp": e["total_exp"], **dict(m)}, **kw))

        # ── block cases ─────────────────────────────────────────────────────
        for i, b in enumerate(blocks):
            bn, d = b["b"], b["d"]
            y = YEARS[i % 4]
            collide = bn.upper() in village_names
            # a block that is also a village name is asked as "<X> block" (and, every other time, bare —
            # then the bot must ask which one and the block option must be offered)
            if collide:
                ask = f"{bn.title()} block" if i % 2 == 0 else bn.title()
            else:
                ask = bn if i % 2 else bn.title()
            W, P = "lgd_block = $1", [bn]
            e = await agg("v_expenditure", ["total_exp", "admin_total_exp"], W, P, y)
            m = await agg("v_employment", ["households_employed", "person_days", "households_completed_100_days"], W, P, y)
            kw = dict(year=y, place=[bn], level="block")
            lab = f"{bn}{' [also a village]' if collide else ''} as '{ask}' {fy_label(y)}"
            add(run_case("DATA-003", lab, f"What was the total expenditure in {ask} during {fy(y, i)}?",
                         value_check(e["total_exp"], True), expected=e["total_exp"], **kw))

            def admin_check(rec, a=e["admin_total_exp"]):
                ans = (rec.get("answer") or "").lower()
                return ("admin" in ans) and has(rec, a, 0.006, True), f"admin={a}"
            add(run_case("DATA-013", lab, f"What was the administrative expenditure in {ask} during {fy(y, i + 1)}?",
                         admin_check, expected=e["admin_total_exp"], **kw))
            add(run_case("DATA-016", lab, f"How many households received employment in {ask} during {fy(y, i + 2)}?",
                         value_check(m["households_employed"]), expected=m["households_employed"], **kw))
            pct = 100.0 * m["households_completed_100_days"] / m["households_employed"] if m["households_employed"] else None
            add(run_case("DATA-020", lab, f"What percentage of employment households completed 100 days in {ask}?",
                         value_check(round(pct, 2) if pct is not None else None, rel=0.002), expected=pct, **kw))
            add(run_case("DATA-029", lab, f"Compare expenditure and person-days in {ask} during {fy(y, i + 3)}.",
                         multi_check([("total_exp", e["total_exp"], True), ("person_days", m["person_days"], False)]),
                         expected={"total_exp": e["total_exp"], "person_days": m["person_days"]}, **kw))

        # ── assembly constituency cases ─────────────────────────────────────
        for i, a in enumerate(acs):
            y = YEARS[i % 4]
            m = await agg("v_employment", ["persons_employed"], "assembly_constituency_name = $1", [a], y)
            nv = (await fetch("""SELECT COUNT(DISTINCT village_code) n FROM curated.v_employment
                                 WHERE assembly_constituency_name=$1 AND year_key=$2 AND persons_employed > 0""",
                              [a, y]))[0]["n"]
            kw = dict(year=y, place=[a.split()[0]], level="ac")
            add(run_case("DATA-004", f"{a} {fy_label(y)}",
                         f"How many persons received employment in {a.title()} constituency during {fy(y, i)}?",
                         value_check(m["persons_employed"]), expected=m["persons_employed"], **kw))

            def vil_check(rec, nv=nv):
                n = rec.get("n_rows") or 0
                return n == nv or has(rec, nv), f"villages expected={nv} rows={n}"
            add(run_case("DATA-014", f"{a} {fy_label(y)}",
                         f"Which villages in {a.title()} constituency received employment during {fy(y, i + 1)}?",
                         vil_check, expected=nv, **kw))

        # ── rankings, every year ────────────────────────────────────────────
        for y in YEARS:
            top = (await fetch("""SELECT lgd_district n, SUM(total_exp)::float8 v FROM curated.v_expenditure
                                  WHERE year_key=$1 GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", [y]))[0]
            add(run_case("DATA-024", fy_label(y), f"Which district had the highest expenditure during {fy(y, y)}?",
                         lambda r, t=top: (has_name(r, t["n"]) and has(r, t["v"], 0.006, True), f"exp {t['n']} {t['v']}"),
                         year=y, expected=dict(top)))
            top = (await fetch("""SELECT lgd_block n, SUM(person_days)::float8 v FROM curated.v_employment
                                  WHERE year_key=$1 AND lgd_block IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", [y]))[0]
            add(run_case("DATA-025", fy_label(y), f"Which block generated the highest person-days during {fy(y, y + 1)}?",
                         lambda r, t=top: (has_name(r, t["n"]) and has(r, t["v"]), f"exp {t['n']} {t['v']}"),
                         year=y, expected=dict(top)))
            top = (await fetch("""SELECT village_code, MIN(lgd_village_name) n, SUM(person_days)::float8 v
                                  FROM curated.v_employment WHERE year_key=$1 AND village_code IS NOT NULL
                                  GROUP BY 1 ORDER BY 3 DESC LIMIT 1""", [y]))[0]
            add(run_case("DATA-026", fy_label(y), f"Which village generated the highest person-days during {fy(y, y + 2)}?",
                         lambda r, t=top: (has_name(r, t["n"]) and has(r, t["v"]), f"exp {t['n']} {t['v']}"),
                         year=y, expected=dict(top)))
            top = (await fetch("""SELECT lgd_district n, SUM(women_employment_provided)::float8 v FROM curated.v_employment
                                  WHERE year_key=$1 GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", [y]))[0]
            if top["v"] > 0:
                chk = (lambda r, t=top: (has_name(r, t["n"]) and has(r, t["v"]), f"exp {t['n']} {t['v']}"))
            else:   # 2025-26: women employment not recorded at source — must say so, not name a district
                chk = (lambda r: (bool(re.search(r"not (?:been )?recorded|not available|unrecorded|not captured|zero",
                                                 r.get("answer") or "", re.I)), "expects 'not recorded'"))
            add(run_case("DATA-027", fy_label(y), f"Which district had the highest women employment during {fy(y, y + 3)}?",
                         chk, year=y, expected=dict(top)))

        log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1, default=str)
    log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
