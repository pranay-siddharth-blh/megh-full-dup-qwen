"""CM Elevate Legacy sheet (TC-01..TC-36) through the live LangGraph pipeline.
Truth from curated.v_cm_elevate_disbursement ONLY (never the fact table) with the project's
rules (schema_context _CMELEVATELEGACY_RULES): applications / records = COUNT(*), sanctioned =
COUNT(sanctioned_amount), not sanctioned = sanctioned_amount IS NULL, disbursed = subsidy +
loan + total (stored totals), FY = financial_year_short (Sericulture rows have none), lender
= COALESCE(loan_entity, '(not recorded)'), constituency via dim_geography.ac_name.
Hierarchy: every scheme, district, block, constituency, both FYs. The sheet says
"CM-ELEVATE": when the bot asks CM Elevate or CM Elevate Legacy, CM Elevate Legacy is chosen.
Usage (repo root): cl_run.py [TC ...] -> cl_results.json (CL_OUT)"""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "CM Elevate Legacy")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case, has_name, vals, close  # noqa: E402
from harness import fetch  # noqa: E402
from tests._text_checks import need_ok  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set(sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("CL_OUT", "cl_results.json"))
T_ = "TC-"
V = "curated.v_cm_elevate_disbursement"
CN = ["CM-ELEVATE", "CM Elevate Legacy", "CM ELEVATE", "cm elevate legacy"]


def num_ok(rec, n):
    return any(close(c, n, 0.0001) for c in vals(rec))


def money_ok(rec, r):
    return any(abs(c - f) <= max(0.006, abs(f) * 0.0006) for c in vals(rec) for f in (r, r / 1e5, r / 1e7))


def checks(*pairs, money=()):
    def chk(rec):
        miss = [f"{l}={e}" for l, e in pairs if not num_ok(rec, e)]
        miss += [f"{l}=Rs{e:,.0f}" for l, e in money if not money_ok(rec, e)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def words(*need):
    """Each need is 'a|b|c' (any of the literals; see _text_checks.need_ok)."""
    def chk(rec):
        a = rec.get("answer") or ""
        miss = [w for w in need if not need_ok(a, w)]
        return (not miss and rec.get("kind") == "answer"), ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def ordered(names_counts, *more_pairs, money=()):
    """every count present AND the names appear in descending-count order (testers' TC-26/36 remark)."""
    base = checks(*[(n, c) for n, c in names_counts], *more_pairs, money=money)

    def chk(rec):
        ok, note = base(rec)
        a = (rec.get("answer") or "").upper()
        pos = [a.find(n.upper()) for n, _ in sorted(names_counts, key=lambda x: -x[1])]
        if ok and all(p >= 0 for p in pos) and pos != sorted(pos):
            return False, "not in descending order"
        return ok, note
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

        # ── knowledge (TC-01..10) ───────────────────────────────────────────
        K = [("01", "What is the CM-ELEVATE programme in Meghalaya?", words(r"entrepreneur|enterprise|business")),
             ("02", "What is the main objective of CM-ELEVATE?", words(r"entrepreneur|enterprise|business|livelihood")),
             ("03", "Who are the intended beneficiaries of CM-ELEVATE?", words(r"entrepreneur|youth|individual|farmer")),
             ("04", "What sectors are covered under the CM-ELEVATE programme?", words(r"piggery|poultry|dairy|tourism|agri")),
             ("05", "What type of financial assistance is provided under CM-ELEVATE?", words(r"subsid", r"loan|credit")),
             ("06", "How does CM-ELEVATE provide access to credit for entrepreneurs?", words(r"loan|credit|bank")),
             ("07", "How does CM-ELEVATE promote entrepreneurship in Meghalaya?", words(r"entrepreneur")),
             ("08", "What is the target number of entrepreneurs under CM-ELEVATE?", words("#")),
             ("09", "Give me a short overview of CM-ELEVATE that I can use for an official briefing.",
              words(r"entrepreneur|enterprise|business", r"subsid|loan")),
             ("10", "How can an entrepreneur apply under the CM-ELEVATE programme?", words(r"apply|application|portal|online"))]
        for k, q, c in K:
            add(run_case(T_ + k, "knowledge", q, c, **kw))

        # ── statewide figures ───────────────────────────────────────────────
        tot = dict((await fetch(f"""SELECT COUNT(*)::float8 n, COUNT(sanctioned_amount)::float8 s,
            COUNT(*) FILTER (WHERE sanctioned_amount IS NULL)::float8 ns, SUM(total_disbursement)::float8 td,
            SUM(total_subsidy_disbursement)::float8 sub, SUM(total_loan_disbursement)::float8 loan FROM {V}"""))[0])
        add(run_case(T_ + "11", "statewide", "How many total applications are recorded under CM-ELEVATE?",
                     checks(("records", tot["n"])), expected=tot["n"], **kw))
        add(run_case(T_ + "14", "statewide", "How many applications have been sanctioned under CM-ELEVATE?",
                     checks(("sanctioned", tot["s"])), expected=tot["s"], **kw))
        pct = round(100 * tot["s"] / tot["n"], 2)
        add(run_case(T_ + "15", "statewide", "What percentage of CM-ELEVATE applications have been sanctioned?",
                     lambda r, p=pct: (any(abs(c - p) <= 0.06 for c in vals(r)), f"pct={p}"), expected=pct, **kw))
        add(run_case(T_ + "16", "statewide", "How many CM-ELEVATE applications have not been sanctioned?",
                     checks(("not sanctioned", tot["ns"])), expected=tot["ns"], **kw))
        add(run_case(T_ + "17", "statewide", "What is the total amount disbursed under CM-ELEVATE?",
                     checks(money=[("total", tot["td"])]),   # "total disbursed" = total_disbursement (rule 5)
                     expected=tot, **kw))

        # ── schemes (TC-12, 13, 18, 19, 25) ─────────────────────────────────
        sch = await fetch(f"SELECT scheme_name s, COUNT(*)::float8 n, COUNT(sanctioned_amount)::float8 k, "
                          f"SUM(total_disbursement)::float8 t FROM {V} GROUP BY 1 ORDER BY 2 DESC")
        for i, r in enumerate(sch):
            add(run_case(T_ + "12", r["s"], f"How many applications are recorded under {r['s']}{' in CM-ELEVATE' if i % 2 else ''}?",
                         checks(("records", r["n"])), expected=r["n"], **kw))
        add(run_case(T_ + "13", "ranking", "Which CM-ELEVATE schemes have the highest number of applications?",
                     lambda r, x=sch[0]: (has_name(r, "Piggery") and num_ok(r, x["n"]), f"{x['s']}={x['n']}"),
                     expected=dict(sch[0]), **kw))
        add(run_case(T_ + "18", "every scheme", "What is the total amount disbursed under each CM-ELEVATE scheme?",
                     checks(money=[(r["s"], r["t"]) for r in sch if r["t"]]), expected={r["s"]: r["t"] for r in sch}, **kw))
        add(run_case(T_ + "19", "every scheme", "How many sanctioned applications are there for each CM-ELEVATE scheme?",
                     checks(*[(r["s"], r["k"]) for r in sch]), expected={r["s"]: r["k"] for r in sch}, **kw))
        for f in ("2024-25", "2025-26"):
            fs = await fetch(f"SELECT scheme_name s, COUNT(*)::float8 n FROM {V} WHERE financial_year_short=$1 GROUP BY 1", [f])
            add(run_case(T_ + "25", f, f"Compare the number of applications across CM-ELEVATE schemes for FY {f}.",
                         checks(*[(r["s"], r["n"]) for r in fs]), expected={r["s"]: r["n"] for r in fs}, **kw))

        # ── lenders (TC-20..22) and years (TC-23, 24) ───────────────────────
        le = await fetch(f"SELECT COALESCE(loan_entity,'(not recorded)') e, COUNT(*)::float8 n, "
                         f"SUM(total_disbursement)::float8 t FROM {V} GROUP BY 1")
        add(run_case(T_ + "20", "statewide", "Which loan entities are associated with CM-ELEVATE applications?",
                     words(r"\bbank\b", r"LIFCOM"), **kw))
        add(run_case(T_ + "21", "statewide", "How many CM-ELEVATE applications are associated with each loan entity?",
                     checks(*[(r["e"], r["n"]) for r in le]), expected={r["e"]: r["n"] for r in le}, **kw))
        add(run_case(T_ + "22", "statewide", "What is the total CM-ELEVATE disbursement made through each loan entity?",
                     checks(money=[(r["e"], r["t"]) for r in le]), expected={r["e"]: r["t"] for r in le}, **kw))
        fy = await fetch(f"SELECT COALESCE(financial_year_short,'(none)') f, COUNT(*)::float8 n, "
                         f"SUM(total_disbursement)::float8 t FROM {V} GROUP BY 1")
        add(run_case(T_ + "23", "statewide", "How many CM-ELEVATE applications are recorded for each financial year?",
                     checks(*[(r["f"], r["n"]) for r in fy]), expected={r["f"]: r["n"] for r in fy}, **kw))
        add(run_case(T_ + "24", "statewide", "What was the total CM-ELEVATE disbursement in each financial year?",
                     checks(money=[(r["f"], r["t"]) for r in fy if r["f"] != "(none)"]),
                     expected={r["f"]: r["t"] for r in fy}, **kw))

        # ── districts (TC-26, 27, 28, 33, 35, 36) ───────────────────────────
        dist = await fetch(f"SELECT lgd_district d, COUNT(*)::float8 n, COUNT(sanctioned_amount)::float8 k, "
                           f"SUM(total_disbursement)::float8 t FROM {V} GROUP BY 1 ORDER BY 2 DESC")
        add(run_case(T_ + "26", "every district", "How many CM-ELEVATE applications are recorded in each district?",
                     ordered([(r["d"], r["n"]) for r in dist]), expected={r["d"]: r["n"] for r in dist}, **kw))
        add(run_case(T_ + "27", "every district", "What is the total CM-ELEVATE disbursement amount for each district?",
                     checks(money=[(r["d"], r["t"]) for r in dist]), expected={r["d"]: r["t"] for r in dist}, **kw))
        add(run_case(T_ + "28", "ranking", "Which districts have the highest number of CM-ELEVATE applications?",
                     checks(*[(r["d"], r["n"]) for r in dist[:5]]), expected={r["d"]: r["n"] for r in dist[:5]}, **kw))
        add(run_case(T_ + "36", "every district", "Give me a district-wise summary of applications, sanctioned cases and "
                     "total disbursement under CM-ELEVATE.",
                     ordered([(r["d"], r["n"]) for r in dist], *[(r["d"] + " sanctioned", r["k"]) for r in dist]),
                     expected={r["d"]: [r["n"], r["k"], r["t"]] for r in dist}, **kw))
        for i, r in enumerate(dist):
            nm = [r["d"], t(r["d"]), r["d"].lower()][i % 3]
            bl = await fetch(f"SELECT lgd_block b, COUNT(*)::float8 n FROM {V} WHERE lgd_district=$1 GROUP BY 1", [r["d"]])
            add(run_case(T_ + "33", r["d"], f"Show me the number of {CN[i % 4]} applications in each block of {nm}.",
                         checks(*[(b["b"], b["n"]) for b in bl]), expected={b["b"]: b["n"] for b in bl}, **kw))
        pairs = [(dist[i], dist[(i + 5) % len(dist)]) for i in range(0, len(dist), 2)]
        for k, (x, y) in enumerate(pairs):
            add(run_case(T_ + "35", f"{x['d']} vs {y['d']}",
                         f"Compare the number of sanctioned {CN[k % 4]} applications across {t(x['d'])} and {t(y['d'])}.",
                         checks((x["d"], x["k"]), (y["d"], y["k"])), expected={x["d"]: x["k"], y["d"]: y["k"]}, **kw))

        # ── blocks (TC-29, 30, 34): every block ─────────────────────────────
        blocks = await fetch(f"SELECT lgd_block b, MIN(lgd_district) d, COUNT(*)::float8 n, "
                             f"SUM(total_disbursement)::float8 t FROM {V} WHERE lgd_block IS NOT NULL GROUP BY 1 ORDER BY 1")
        for i, b in enumerate(blocks):
            nm = [b["b"], t(b["b"])][i % 2] + (" block" if i % 3 else "")
            add(run_case(T_ + "29", f"{b['b']} ({b['d']})", f"How many {CN[i % 4]} applications are recorded in {nm}?",
                         checks(("records", b["n"])), place=[b["b"].split("-")[0]], level="block", expected=b["n"], **kw))
            add(run_case(T_ + "30", f"{b['b']} ({b['d']})", f"What is the total {CN[(i + 1) % 4]} disbursement amount for {nm}?",
                         checks(money=[("total", b["t"])]), place=[b["b"].split("-")[0]], level="block",
                         expected=b["t"], **kw))
        top_blocks = sorted(blocks, key=lambda b: -b["n"])[:12]
        for i, b in enumerate(top_blocks):
            vl = await fetch(f"SELECT lgd_village_name v, village_code c, COUNT(*)::float8 n FROM {V} WHERE lgd_block=$1 "
                             "AND entity_type <> 'Unresolved' GROUP BY 1,2 ORDER BY 3 DESC LIMIT 3", [b["b"]])
            add(run_case(T_ + "34", b["b"], f"Show me the no of {CN[i % 4]} applications mapped to each village in "
                         f"{t(b['b'])} block.",
                         lambda r, vl=vl: (all(has_name(r, x["v"]) and num_ok(r, x["n"]) for x in vl),
                                           "top villages " + ", ".join(f"{x['v']}={x['n']}" for x in vl)),
                         expected={x["v"]: x["n"] for x in vl}, **kw))

        # ── constituencies (TC-31, 32): every AC ────────────────────────────
        acs = await fetch(f"SELECT g.ac_name a, COUNT(*)::float8 n, SUM(v.total_disbursement)::float8 t FROM {V} v "
                          "JOIN curated.dim_geography g ON g.geography_key = v.geography_key WHERE g.ac_name IS NOT NULL "
                          "GROUP BY 1 ORDER BY 1")
        for i, a in enumerate(acs):
            nm = [a["a"], t(a["a"])][i % 2] + [" constituency", ""][i % 2]
            add(run_case(T_ + "31", a["a"], f"How many {CN[i % 4]} applications are mapped to {nm}?",
                         checks(("records", a["n"])), place=[a["a"]], level="constituency", expected=a["n"], **kw))
            add(run_case(T_ + "32", a["a"], f"What is the total {CN[(i + 1) % 4]} disbursement amount for {nm}?",
                         checks(money=[("total", a["t"])]), place=[a["a"]], level="constituency", expected=a["t"], **kw))

        mg_run.log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    mg_run.log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
