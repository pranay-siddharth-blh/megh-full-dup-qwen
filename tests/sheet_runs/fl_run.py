"""FOCUS (Focus Legacy) sheet (TC-01..TC-28) through the live LangGraph pipeline.
Truth from curated.v_focus_legacy ONLY (the privacy tables are never touched) with the
project's rules (schema_context _FOCUSLEGACY_RULES): payments = COUNT(*), producer
groups = COUNT(DISTINCT pg_id), memberships = SUM(no_of_pg_members), amount =
SUM(amount_disbursed) (= memberships x 5000); FY 2023-24 holds no payments; a group
named by the user is matched on its core name (ILIKE). Constituency through
dim_geography.ac_name. Hierarchy: every district, every block, every constituency, every
FY, 2 villages per district. Usage (repo root): fl_run.py [TC ...] -> fl_results.json (FL_OUT)"""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "Focus Legacy")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case, has_name, vals, close  # noqa: E402
from harness import fetch  # noqa: E402
from tests._text_checks import need_ok  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set(sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("FL_OUT", "fl_results.json"))
T_ = "TC-"
V = "curated.v_focus_legacy"
FYS = {"2021-22": 2021, "2022-23": 2022, "2024-25": 2024, "2025-26": 2025}
FN = ["FOCUS", "Focus Legacy", "FOCUS scheme", "focus"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _drop_typed_suffix(nm):
    """'Nongstoin PG' -> 'Nongstoin': a trailing 'producer group' / 'pg'
    (any case) and the whitespace before it come off."""
    low = nm.lower()
    for suffix in ("producer group", "pg"):
        if low.endswith(suffix):
            return nm[:-len(suffix)].rstrip()
    return nm


def _core_name(n):
    """A recorded pg_name without its group-type tail: trailing digits/dashes,
    then 'producer group' / 'p.g.' / 'pg' (any case, any spacing), then the
    whitespace before it. Unchanged when there is no such tail."""
    t = n
    while t and (t[-1] == "-" or t[-1].isdecimal()):
        t = t[:-1]
    t = t.rstrip()
    low = t.lower()
    cut = None
    for form in ("p.g.", "p.g", "pg.", "pg"):
        if low.endswith(form):
            cut = len(t) - len(form)
            break
    if cut is None and low.endswith("group"):
        head = low[:-len("group")]
        if head and head[-1].isspace() and head.rstrip().endswith("producer"):
            cut = len(head.rstrip()) - len("producer")
    if cut is None:
        return n
    return t[:cut].rstrip()


def num_ok(rec, n):
    return any(close(c, n, 0.0001) for c in vals(rec))


def money_ok(rec, r):
    return any(abs(c - f) <= max(0.006, f * 0.0006) for c in vals(rec) for f in (r, r / 1e5, r / 1e7))


def checks(*pairs, money=()):
    def chk(rec):
        miss = [f"{l}={e}" for l, e in pairs if not num_ok(rec, e)]
        miss += [f"{l}=Rs{e:,.0f}" for l, e in money if not money_ok(rec, e)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def words(*need, nums=()):
    """Knowledge answers: every word group ('a|b|c', see need_ok) present, and every number."""
    def chk(rec):
        a = rec.get("answer") or ""
        miss = [w for w in need if not need_ok(a, w)]
        miss += [str(n) for n in nums if not num_ok(rec, n)]
        told = rec.get("kind") == "answer" or rec.get("rule") == "year-out-of-range"   # "no data for <year>"
        return (not miss and told), ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def t(name):
    return " ".join(w.capitalize() if len(w) > 2 else w for w in str(name).split())


async def one(sql, params=()):
    r = await fetch(sql, list(params))
    return float(list(dict(r[0]).values())[0] or 0)


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        add = T.append
        kw = dict(mgnrega_only=False, year="all")
        districts = [r["d"] for r in await fetch(f"SELECT DISTINCT lgd_district d FROM {V} WHERE lgd_district IS NOT NULL ORDER BY 1")]
        tot = dict((await fetch(f"SELECT COUNT(*)::float8 p, COUNT(DISTINCT pg_id)::float8 g, SUM(no_of_pg_members)::float8 m, "
                                f"SUM(amount_disbursed)::float8 a FROM {V}"))[0])
        mg_run.log(f"{len(districts)} districts; totals {tot}")

        # ── knowledge (TC-01..07, 09) ───────────────────────────────────────
        K = [("01", "What is the FOCUS scheme in Meghalaya?", words(r"producer group", r"farm")),
             ("02", "What is the main objective of FOCUS?", words(r"income", r"farm")),
             ("03", "Who can benefit under the FOCUS scheme?", words(r"producer group|PG", "5000|5,000")),
             ("04", "What is the role of Producer Groups under FOCUS?", words(r"producer group|PG")),
             ("05", "What type of financial assistance is provided under FOCUS?", words("5000|5,000", r"grant|assistance")),
             ("06", "What kind of support does FOCUS provide to Producer Groups?", words("5000|5,000")),
             ("07", "How is financial assistance distributed under FOCUS?", words("5000|5,000", r"DBT|bank|account|cheque|transfer")),
             ("09", "Give me a short overview of FOCUS that I can use for an official briefing.", words(r"producer group|PG", "5000|5,000"))]
        for k, q, c in K:
            add(run_case(T_ + k, "knowledge", q, c, **kw))

        # ── statewide figures ───────────────────────────────────────────────
        add(run_case(T_ + "08", "statewide", "How many Producer Groups have been covered under FOCUS?",
                     checks(("groups", tot["g"])), expected=tot["g"], **kw))
        add(run_case(T_ + "10", "statewide", "How many total beneficiaries are available under the FOCUS scheme?",
                     checks(("payments", tot["p"]), ("groups", tot["g"]), ("memberships", tot["m"]), money=[("amt", tot["a"])]),
                     expected=tot, **kw))
        add(run_case(T_ + "11", "statewide", "How many unique Producer Groups are present under FOCUS scheme?",
                     checks(("groups", tot["g"])), expected=tot["g"], **kw))
        rep = await one(f"SELECT COUNT(*) FROM (SELECT pg_id FROM {V} GROUP BY 1 HAVING COUNT(*)>1) x")
        add(run_case(T_ + "12", "statewide", "Are there any duplicate Producer Groups there under FOCUS?",
                     checks(("groups paid more than once", rep), ("extra payments", tot["p"] - tot["g"])),
                     expected={"repeat_groups": rep, "extra_payments": tot["p"] - tot["g"]}, **kw))
        for nm in ("Nongstoin PG", "Shillong Producer Group"):
            n = await one(f"SELECT COUNT(DISTINCT pg_id) FROM {V} WHERE pg_name ILIKE $1",
                          ["%" + _drop_typed_suffix(nm) + "%"])
            if n == 0:
                add(run_case(T_ + "13", nm, f"Is there any Producer Group named {nm} under FOCUS?",
                             words("[no]|not found|could not find|couldn't find|no producer group|none"),
                             expected=0, **kw))
        add(run_case(T_ + "16", "statewide", "What is the total number of FOCUS PG members recorded till now?",
                     checks(("memberships", tot["m"])), expected=tot["m"], **kw))

        # ── named groups (TC-14): a core name matching exactly one pg_id, one per district ──
        cands = await fetch(f"""SELECT pg_id, MAX(pg_name) n, MAX(lgd_district) d, SUM(no_of_pg_members)::float8 m,
                                       MAX(no_of_pg_members)::float8 x
                                FROM {V} GROUP BY pg_id ORDER BY md5(pg_id) LIMIT 400""")
        seen = set()
        for c in cands:
            core = _core_name(c["n"] or "").strip()
            if c["d"] in seen or len(core) < 5 or not all(ch == " " or (ch.isascii() and ch.isalpha()) for ch in core):
                continue
            if await one(f"SELECT COUNT(DISTINCT pg_id) FROM {V} WHERE pg_name ILIKE $1", [f"%{core}%"]) != 1:
                continue
            seen.add(c["d"])
            nm = core + [" PG", " Producer Group", ""][len(seen) % 3]
            # a group paid twice can have two recorded sizes: its current (largest) size or the
            # summed memberships are both correct readings when the answer says which
            add(run_case(T_ + "14", f"{c['pg_id']} ({c['d']})", f"How many members are there in {nm}?",
                         lambda r, c=c: (num_ok(r, c["x"]) or num_ok(r, c["m"]), f"size={c['x']} memberships={c['m']}"),
                         expected={"size": c["x"], "memberships": c["m"]}, **kw))
            if len(seen) >= 12:
                break

        # ── TC-15: top N groups with more than M members ────────────────────
        for n_, m_ in ((5, 20), (10, 25)):
            top = await fetch(f"SELECT pg_id, SUM(no_of_pg_members)::float8 s, MAX(no_of_pg_members)::float8 x FROM {V} "
                              "GROUP BY pg_id HAVING SUM(no_of_pg_members) > $1 ORDER BY 2 DESC, 1 LIMIT 1", [m_])
            add(run_case(T_ + "15", f"top {n_} > {m_}", f"List top {n_} FOCUS PGs which has more than {m_} members.",
                         lambda r, t0=top[0], n_=n_: ((num_ok(r, t0["s"]) or num_ok(r, t0["x"])) and (r.get("n_rows") or 0) >= min(n_, 1),
                                                      f"top={t0['s']}/{t0['x']}"), expected=dict(top[0]), **kw))

        # ── districts (TC-17, 18, 25, 26) ───────────────────────────────────
        per_d = []
        for i, d in enumerate(districts):
            nm = [d, t(d), d.lower()][i % 3]
            m = await one(f"SELECT SUM(no_of_pg_members) FROM {V} WHERE lgd_district=$1", [d])
            a = await one(f"SELECT SUM(amount_disbursed) FROM {V} WHERE lgd_district=$1", [d])
            g = await one(f"SELECT COUNT(DISTINCT pg_id) FROM {V} WHERE lgd_district=$1", [d])
            per_d.append((d, g))
            add(run_case(T_ + "17", d, f"What is the total number of {FN[i % 4]} PG members in {nm}?",
                         checks(("members", m)), place=[d.split()[0]], level="district", expected=m, **kw))
            add(run_case(T_ + "18", d, f"What is the total {FN[i % 4]} amount disbursed for {nm}?",
                         checks(money=[("amt", a)]), place=[d.split()[0]], level="district", expected=a, **kw))
            bl = await fetch(f"SELECT lgd_block b, COUNT(DISTINCT pg_id)::float8 n FROM {V} WHERE lgd_district=$1 "
                             "AND lgd_block IS NOT NULL GROUP BY 1", [d])
            add(run_case(T_ + "26", f"{d} by block", f"How many Producer Groups are mapped to each block for {nm} under FOCUS?",
                         checks(*[(r["b"], r["n"]) for r in bl]), expected={r["b"]: r["n"] for r in bl}, **kw))
        add(run_case(T_ + "25", "every district", "How many FOCUS Producer Groups are mapped to each district?",
                     checks(*per_d), expected=dict(per_d), **kw))
        # every block on its own
        blocks = await fetch(f"SELECT lgd_block b, MIN(lgd_district) d, COUNT(DISTINCT pg_id)::float8 n FROM {V} "
                             "WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY 1")
        for i, b in enumerate(blocks):
            nm = [b["b"], t(b["b"])][i % 2] + " block"
            add(run_case(T_ + "26", f"{b['b']} ({b['d']})", f"How many FOCUS Producer Groups are mapped to {nm}?",
                         checks(("groups", b["n"])), place=[b["b"]], level="block", expected=b["n"], **kw))

        # ── TC-19: groups above an amount ───────────────────────────────────
        for thr in (500000, 750000):
            n = await one(f"SELECT COUNT(*) FROM (SELECT pg_id FROM {V} GROUP BY 1 HAVING SUM(amount_disbursed) > $1) x", [thr])
            add(run_case(T_ + "19", f"> {thr}", f"Which FOCUS Producer Groups received more than ₹{thr:,}?",
                         lambda r, n=n: ((r.get("n_rows") or 0) == n or num_ok(r, n), f"groups={n}"), expected=n, **kw))

        # ── dates and years (TC-20..24) ─────────────────────────────────────
        for (m1, m2, y) in ((4, 6, 2025), (1, 3, 2026), (8, 12, 2021)):
            last = {6: 30, 3: 31, 12: 31}[m2]
            r = dict((await fetch(f"SELECT COUNT(*)::float8 n, COALESCE(SUM(amount_disbursed),0)::float8 a FROM {V} "
                                  f"WHERE date_of_remittance BETWEEN '{y}-{m1:02d}-01' AND '{y}-{m2:02d}-{last}'"))[0])
            add(run_case(T_ + "20", f"{MONTHS[m1-1]}-{MONTHS[m2-1]} {y}",
                         f"Show me all FOCUS remittances made between {MONTHS[m1-1]} and {MONTHS[m2-1]} {y}.",
                         checks(money=[("amt", r["a"])]), expected=r, **kw))
        yrs = await fetch(f"SELECT financial_year_short f, COUNT(*)::float8 n, SUM(amount_disbursed)::float8 a FROM {V} GROUP BY 1")
        ya = {r["f"]: r["a"] for r in yrs}
        add(run_case(T_ + "22", "every FY", "How many records of FOCUS beneficiaries are available for each financial year?",
                     checks(*[(r["f"], r["n"]) for r in yrs]), expected={r["f"]: r["n"] for r in yrs}, **kw))
        for f, y in FYS.items():
            mo = await fetch(f"SELECT EXTRACT(MONTH FROM date_of_remittance)::int m, SUM(amount_disbursed)::float8 a FROM {V} "
                             "WHERE financial_year_short=$1 AND date_of_remittance IS NOT NULL GROUP BY 1", [f])
            add(run_case(T_ + "21", f, f"How much FOCUS amount was remitted during each month for financial year {mg_run.fy(y, 0)}?",
                         checks(money=[(MONTHS[r["m"] - 1], r["a"]) for r in mo]), expected={r["m"]: r["a"] for r in mo}, **kw))
            for s in range(4):
                fy = mg_run.fy(y, s)
                add(run_case(T_ + "23", fy, f"What was the total {FN[s]} amount remitted in {'FY ' if s % 2 else ''}{fy}?",
                             checks(money=[(f, ya[f])]), expected=ya[f], **kw))
        add(run_case(T_ + "23", "2023-24", "What was the total FOCUS amount remitted in FY 2023-24?",
                     words(r"2023-24", "[no]|not|absent|gap|none"), expected=0, **kw))
        for x, y in (("2023-24", "2024-25"), ("2021-22", "2022-23"), ("2022-23", "2025-26"), ("2024-25", "2025-26")):
            mon = [(f, ya[f]) for f in (x, y) if f in ya]
            add(run_case(T_ + "24", f"{x} vs {y}", f"Compare the total FOCUS remittance between FY {x} and FY {y}.",
                         lambda r, mon=mon, x=x: (all(money_ok(r, a) for _, a in mon)
                                                  and (x in ya or need_ok(r.get("answer") or "", "[no]|not|absent|gap|none")),
                                                  " ".join(f"{f}={a:,.0f}" for f, a in mon)),
                         expected=dict(mon), **kw))

        # ── villages (TC-27): 2 per district, groups named ──────────────────
        vills = await fetch(f"""
            WITH u AS (SELECT UPPER(lgd_village_name) n FROM {V} WHERE entity_type <> 'Unresolved'
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 c AS (SELECT v.village_code, MIN(v.lgd_village_name) name, MIN(v.lgd_district) d, COUNT(DISTINCT pg_id) k
                       FROM {V} v JOIN u ON u.n = UPPER(v.lgd_village_name)
                       WHERE v.entity_type <> 'Unresolved' AND TRANSLATE(UPPER(v.lgd_village_name), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ ', '') = ''
                       GROUP BY 1 HAVING COUNT(DISTINCT pg_id) BETWEEN 1 AND 6),
                 x AS (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY d ORDER BY md5(name)) rn FROM c)
            SELECT * FROM x WHERE rn <= 2 ORDER BY d, name""")
        for i, v in enumerate(vills):
            pg = await fetch(f"SELECT pg_id, MAX(pg_name) n FROM {V} WHERE village_code=$1 GROUP BY 1", [v["village_code"]])
            nm = v["name"].upper() if i % 2 == 0 else v["name"].title()
            add(run_case(T_ + "27", f"{v['name']} ({v['d']})", f"Which FOCUS Producer Groups are mapped to {nm} village?",
                         lambda r, pg=pg: (all(has_name(r, p["n"]) or has_name(r, p["pg_id"]) for p in pg),
                                           f"{len(pg)} groups"),
                         place=[v["name"]], level="village", expected=[p["n"] for p in pg], **kw))

        # ── constituencies (TC-28): every AC ────────────────────────────────
        acs = await fetch(f"SELECT g.ac_name a, COUNT(DISTINCT v.pg_id)::float8 n FROM {V} v JOIN curated.dim_geography g "
                          "ON g.geography_key = v.geography_key WHERE g.ac_name IS NOT NULL GROUP BY 1 ORDER BY 1")
        for i, a in enumerate(acs):
            nm = [a["a"], t(a["a"])][i % 2] + [" constituency", ""][i % 2]
            add(run_case(T_ + "28", a["a"], f"How many FOCUS Producer Groups are mapped to {nm}?",
                         checks(("groups", a["n"])), place=[a["a"]], level="constituency", expected=a["n"], **kw))

        mg_run.log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    mg_run.log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
