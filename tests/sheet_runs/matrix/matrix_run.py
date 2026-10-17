"""Single-scheme hierarchy matrix (2026-10-14): every scheme x every measure it records x
every level (state, every district, every block, every assembly constituency where the scheme
holds one, every village) x year (none = all years, or a rotating FY) x phrasing, through the
live LangGraph pipeline, each answer checked against megh_db.

Usage (repo root): python tests/sheet_runs/matrix/matrix_run.py [FAMILY ...]
  families: state, district, block, ac, village   (default: state district block ac)
  MX_SCHEMES=MGNREGA,PMAY-G,... limits schemes; MX_OUT (matrix_results.json, resumable);
  MX_CONC (16); MX_ONLY=<file of case ids>."""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, ".")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from harness import Conv, fetch, numbers_in, text_numbers  # noqa: E402
from tests._text_checks import has_phrase, no_near  # noqa: E402
from app import main as app_main  # noqa: E402
import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402


def qualify(condition: str, alias: str, *names: str) -> str:
    """`condition` (a SQL WHERE fragment) with every unqualified column among
    `names` qualified by `alias` — done on the SQLGlot tree, never on the text."""
    wanted = {n.lower() for n in names}
    tree = sqlglot.parse_one(condition, read="postgres")
    for col in tree.find_all(exp.Column):
        if not col.table and col.name.lower() in wanted:
            col.set("table", exp.to_identifier(alias))
    return tree.sql(dialect="postgres")


OUT = os.path.join(HERE, os.environ.get("MX_OUT", "matrix_results.json"))
SEM = asyncio.Semaphore(int(os.environ.get("MX_CONC", "16")))
RESULTS: dict = {}
LOG = open(os.path.join(HERE, "matrix_run.log"), "a", encoding="utf-8")


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n")
    LOG.flush()


# ── measures: (key, words used in questions, view, aggregate, base filter, unit, stock?) ──
# unit: "n" count, "lakh" money in lakh rupees, "rs" money in rupees
M = {
    "MGNREGA": [
        ("pd", ["person-days", "person days generated", "total person-days"], "curated.v_employment", "SUM(person_days)", "TRUE", "n", False),
        ("hh", ["households employed", "households that got employment"], "curated.v_employment", "SUM(households_employed)", "TRUE", "n", False),
        ("pe", ["persons employed", "people who got work"], "curated.v_employment", "SUM(persons_employed)", "TRUE", "n", False),
        ("h100", ["households that completed 100 days of work", "households completing 100 days"], "curated.v_employment", "SUM(households_completed_100_days)", "TRUE", "n", False),
        ("jc", ["job cards issued", "job cards"], "curated.v_employment", "SUM(job_cards_issued_total)", "TRUE", "n", True),
        ("exp", ["total expenditure", "total MGNREGA expenditure", "money spent"], "curated.v_expenditure", "SUM(total_exp)", "TRUE", "lakh", False),
        ("mat", ["material expenditure", "expenditure on materials"], "curated.v_expenditure", "SUM(material_exp)", "TRUE", "lakh", False),
        ("wage", ["unskilled wage expenditure"], "curated.v_expenditure", "SUM(unskilled_wage_exp)", "TRUE", "lakh", False),
    ],
    "PMAY-G": [
        ("hs", ["PMAY-G houses sanctioned", "houses sanctioned under PMAY-G"], "curated.v_pmay", "COUNT(*)", "NOT is_placeholder", "n", False),
        ("hc", ["PMAY-G houses completed", "completed PMAY-G houses"], "curated.v_pmay", "COUNT(*) FILTER (WHERE is_completed)", "NOT is_placeholder", "n", False),
        ("sa", ["PMAY-G sanctioned amount", "amount sanctioned under PMAY-G"], "curated.v_pmay", "SUM(sanctioned_amount)", "NOT is_placeholder", "rs", False),
        ("ar", ["PMAY-G amount released", "money released under PMAY-G"], "curated.v_pmay", "SUM(amount_released)", "NOT is_placeholder", "rs", False),
    ],
    "Focus Plus": [
        ("ben", ["Focus Plus beneficiaries", "beneficiaries under Focus Plus"], "curated.v_focus_plus", "COUNT(DISTINCT beneficiary_key)", "TRUE", "n", False),
        ("amt", ["amount disbursed under Focus Plus", "Focus Plus amount disbursed"], "curated.v_focus_plus", "SUM(amount_disbursed)", "TRUE", "rs", False),
    ],
    "Focus Legacy": [
        ("pg", ["producer groups under Focus Legacy", "Focus Legacy producer groups"], "curated.v_focus_legacy", "COUNT(DISTINCT pg_id)", "TRUE", "n", False),
        ("mem", ["PG members under Focus Legacy", "Focus Legacy producer group members"], "curated.v_focus_legacy", "SUM(no_of_pg_members)", "TRUE", "n", False),
        ("amt", ["amount disbursed under Focus Legacy", "Focus Legacy amount remitted"], "curated.v_focus_legacy", "SUM(amount_disbursed)", "TRUE", "rs", False),
    ],
    "CM Elevate": [
        ("app", ["CM Elevate applicants", "applicants under CM Elevate"], "curated.v_cm_elevate", "COUNT(DISTINCT request_id)", "TRUE", "n", False),
    ],
    "CM Elevate Legacy": [
        ("rec", ["CM Elevate Legacy records", "CM Elevate Legacy applications"], "curated.v_cm_elevate_disbursement", "COUNT(*)", "TRUE", "n", False),
        ("san", ["CM Elevate Legacy sanctioned amount", "amount sanctioned under CM Elevate Legacy"], "curated.v_cm_elevate_disbursement", "SUM(sanctioned_amount)", "TRUE", "rs", False),
        ("dis", ["CM Elevate Legacy total disbursement", "amount disbursed under CM Elevate Legacy"], "curated.v_cm_elevate_disbursement", "SUM(total_disbursement)", "TRUE", "rs", False),
    ],
}
# MGNREGA words that do not themselves name the scheme get it appended in half the questions
NEEDS_NAME = {"MGNREGA": lambda w: "MGNREGA" not in w}
VILL = {"MGNREGA": "village_code IS NOT NULL", "PMAY-G": "village_code IS NOT NULL", "Focus Plus": "village_code > 0",
        "Focus Legacy": "village_code > 0 AND entity_type <> 'Unresolved'",
        "CM Elevate": "village_code IS NOT NULL AND entity_type <> 'Unresolved'",
        "CM Elevate Legacy": "village_code > 0 AND entity_type <> 'Unresolved'"}
AC_HOW = {"MGNREGA": "col", "Focus Legacy": "geo", "CM Elevate Legacy": "geo"}   # others record no constituency
YEARS: dict = {}
FP_RAW: set = set()
TPL = ["How many {w} are there in {p}{y}?", "What is the total {w} in {p}{y}?", "Give me {w} for {p}{y}",
       "{w} in {p}{y}", "Tell me the number of {w} in {p}{y}."]
MONEY_TPL = ["What is the {w} in {p}{y}?", "How much is the {w} in {p}{y}?", "Give me the {w} for {p}{y}",
             "{w} in {p}{y}"]


def fy(y, i):
    return [f" in FY {y}-{str(y + 1)[2:]}", f" for {y}-{str(y + 1)[2:]}", f" during FY{y}-{str(y + 1)[2:]}",
            f" in {y}-{y + 1}"][i % 4]


async def truth(scheme, m, f):
    key, words, view, agg, base, unit, stock = m
    w, prm = [base], []

    def p(v):
        prm.append(v)
        return f"${len(prm)}"
    if f.get("district"):
        w.append(f"UPPER(lgd_district) = {p(f['district'].upper())}")
    if f.get("block"):
        b = f["block"].upper()
        if scheme == "Focus Plus" and b in FP_RAW:
            w.append(f"UPPER(block_name_raw) = {p(b)}")
        else:
            w.append(f"UPPER(lgd_block) = {p(b)}")
    if f.get("village"):
        w.append(VILL[scheme])
        w.append(f"village_code = {p(int(f['village']))}")
    if f.get("ac"):
        if AC_HOW[scheme] == "col":
            w.append(f"UPPER(assembly_constituency_name) = {p(f['ac'].upper())}")
        else:
            w.append(f"geography_key IN (SELECT geography_key FROM curated.dim_geography WHERE UPPER(ac_name) = {p(f['ac'].upper())})")
    if f.get("year"):
        w.append(f"year_key = {p(int(f['year']))}")
    elif stock:
        w.append("year_key = (SELECT MAX(year_key) FROM curated.v_employment)")
    r = await fetch(f"SELECT ({agg})::float8 v FROM {view} WHERE {' AND '.join(w)}", prm)
    return (r[0]["v"] or 0.0), unit


def forms(v, unit):
    if unit == "lakh":
        return [v, v / 100.0, v * 1e5]
    if unit == "rs":
        return [v, v / 1e5, v / 1e7]
    return [v]


def has_figure(rec, v, unit):
    cands = numbers_in(rec.get("rows")) + text_numbers(rec.get("answer"))
    for f in forms(v, unit):
        tol = max(0.0051 if unit != "n" else 0.5, abs(f) * 0.0006)
        if any(abs(c - f) <= tol for c in cands):
            return True
    return False




def zero_txt(ans):
    """The answer says there is nothing / zero (case-insensitive)."""
    return (no_near(ans, ("record", "data", "figure", "house", "applicant", "group", "beneficiar", "payment",
                          "expenditure", "employment", "job card"), 80)
            or has_phrase(ans, "not the same as zero", "none", "0", "zero", "doesn't cover", "does not cover",
                          "no data", "not recorded", "not available", bounded=True)
            or has_phrase(ans, "couldn't find any matching"))


def pick_chip(c, rec):
    rule, labels, qs = rec.get("rule"), rec.get("options") or [], rec.get("option_qs") or []
    if rule != "entity-ambiguous":
        return None, f"NEEDLESS {rule} pause: {(rec.get('answer') or '')[:100]}"
    want = [w.lower() for w in c.get("place") or [] if w]
    if not want:
        return None, f"NEEDLESS place pause: {labels[:4]}"
    cand = [(l, q) for l, q in zip(labels, qs) if want[0] in (l + " " + (q or "")).lower()]
    lv = [(l, q) for l, q in cand if c["level"] in l.lower()]
    cand = lv or cand
    if len(want) > 1:
        bk = [(l, q) for l, q in cand if f"— {want[1]} block" in l.lower()]
        cand = bk or cand
    if c.get("code"):
        cc = [(l, q) for l, q in cand if f"LGD {c['code']}" in l]
        cand = cc or cand
    if not cand:
        return None, f"no chip for {want}: {labels[:5]}"
    return cand[0][1], f"chip -> {cand[0][0]}"


async def run(c):
    async with SEM:
        conv = Conv()
        rec = await conv.ask(c["q"])
        notes, bad = [], []
        for _ in range(3):
            if rec["kind"] != "pause":
                break
            pq, note = pick_chip(c, rec)
            notes.append(note)
            if note.startswith("NEEDLESS") or note.startswith("no chip"):
                bad.append(note)
                break
            if c["level"] != "village":
                bad.append("NEEDLESS place pause: " + note)
            rec = await conv.ask(pq)
        if sum(1 for t in conv.turns if t.get("rule") == "entity-ambiguous") > 1:
            bad.append("repeated which-place pause")
        try:
            v, unit = await truth(c["scheme"], c["m"], c["f"])
        except Exception as e:  # noqa: BLE001
            v, unit, bad = None, None, bad + [f"truth error {e}"]
        if rec["kind"] != "answer":
            bad.append(f"ended in {rec['kind']} {rec.get('rule') or ''}")
        elif v is not None:
            ans = rec.get("answer") or ""
            if has_phrase(ans, "couldn't build a working query", "can't help with that", "outside what I", case=True):
                bad.append("no answer: " + ans[:120])
            elif v == 0:
                if not (zero_txt(ans) or has_figure(rec, 0, unit)):
                    bad.append(f"expected none/0: {ans[:160]}")
            elif not has_figure(rec, v, unit):
                ok_latest = False
                if not c["f"].get("year") and "latest financial year" in ans and YEARS.get(c["scheme"]):
                    lv, _ = await truth(c["scheme"], c["m"], {**c["f"], "year": max(YEARS[c["scheme"]])})
                    ok_latest = has_figure(rec, lv, unit)
                    if ok_latest:
                        notes.append("answered for the latest year, stated")
                if not ok_latest:
                    bad.append(f"expected {v:,.2f} ({unit}): {ans[:200]}")
        RESULTS[c["id"]] = {k: c[k] for k in ("fam", "scheme", "mk", "level", "q", "f")} | {
            "expected": v, "ok": not bad, "bad": bad, "notes": notes,
            "turns": [{k: t.get(k) for k in ("q", "kind", "rule", "answer", "ms")} for t in conv.turns]}
        log(f"{c['id']} | {'OK ' if not bad else 'BAD'} | {c['q'][:110]} | {'; '.join(notes)[:120]} | {'; '.join(bad)[:260]}")


def question(scheme, m, i, place_txt, year_txt):
    key, words, view, agg, base, unit, stock = m
    w = words[i % len(words)]
    if scheme == "MGNREGA" and "MGNREGA" not in w and i % 2:
        w = f"MGNREGA {w}"
    tpl = (MONEY_TPL if unit != "n" else TPL)[i % (len(MONEY_TPL) if unit != "n" else len(TPL))]
    q = tpl.format(w=w, p=place_txt, y=year_txt)
    return q[0].upper() + q[1:]


async def build(fams, schemes):
    C = []
    for scheme in schemes:
        view0 = M[scheme][0][2]
        yrs = sorted(YEARS.get(scheme, []))
        dists = [r["d"] for r in await fetch(f"SELECT DISTINCT lgd_district d FROM {view0} WHERE lgd_district IS NOT NULL ORDER BY 1")]
        blocks = [r["b"] for r in await fetch(f"SELECT DISTINCT lgd_block b FROM {view0} WHERE lgd_block IS NOT NULL ORDER BY 1")]
        if scheme == "Focus Plus":   # its block questions follow the raw names (KI-191)
            blocks = sorted(FP_RAW)
        for mi, m in enumerate(M[scheme]):
            key = m[0]
            if "state" in fams:
                for j, y in enumerate([None] + yrs):
                    i = mi + j
                    pt = ["Meghalaya", "all of Meghalaya", "the state"][i % 3]
                    C.append(dict(id=f"ST|{scheme}|{key}|{y or 'all'}", fam="state", scheme=scheme, m=m, mk=key,
                                  level="state", f={"year": y} if y else {}, place=None,
                                  q=question(scheme, m, i, pt, fy(y, i) if y else ["", " across all financial years", ""][i % 3])))
            if "district" in fams:
                for di, d in enumerate(dists):
                    i = mi + di
                    y = (yrs[i % len(yrs)] if yrs and i % 3 == 0 else None)
                    dn = [d.title(), d.lower(), d.upper()][i % 3]
                    C.append(dict(id=f"DI|{scheme}|{key}|{d}", fam="district", scheme=scheme, m=m, mk=key, level="district",
                                  f={"district": d, **({"year": y} if y else {})}, place=[d],
                                  q=question(scheme, m, i, dn + ["", " district"][i % 2], fy(y, i) if y else "")))
            if "block" in fams:
                for bi, b in enumerate(blocks):
                    i = mi + bi
                    y = (yrs[i % len(yrs)] if yrs and i % 4 == 0 else None)
                    bn = [b.title(), b.lower(), b.upper()][i % 3]
                    C.append(dict(id=f"BL|{scheme}|{key}|{b}", fam="block", scheme=scheme, m=m, mk=key, level="block",
                                  f={"block": b, **({"year": y} if y else {})}, place=[b],
                                  q=question(scheme, m, i, f"{bn} block", fy(y, i) if y else "")))
            if "ac" in fams and scheme in AC_HOW and not (scheme == "MGNREGA" and m[2] == "curated.v_expenditure"):
                acs = [r["a"] for r in await fetch(
                    "SELECT DISTINCT assembly_constituency_name a FROM curated.v_employment WHERE assembly_constituency_name IS NOT NULL ORDER BY 1"
                    if AC_HOW[scheme] == "col" else
                    f"SELECT DISTINCT g.ac_name a FROM {m[2]} v JOIN curated.dim_geography g ON g.geography_key = v.geography_key WHERE g.ac_name IS NOT NULL ORDER BY 1")]
                for ai, a in enumerate(acs):
                    i = mi + ai
                    y = (yrs[i % len(yrs)] if yrs and i % 4 == 1 else None)
                    C.append(dict(id=f"AC|{scheme}|{key}|{a}", fam="ac", scheme=scheme, m=m, mk=key, level="constituency",
                                  f={"ac": a, **({"year": y} if y else {})}, place=[a],
                                  q=question(scheme, m, i, f"{a.title()} {['constituency', 'assembly constituency'][i % 2]}", fy(y, i) if y else "")))
        if "village" in fams:
            vs = await fetch(f"""SELECT v.village_code c, MIN(g.lgd_village_name) n, MIN(g.lgd_block) b
                FROM {view0} v JOIN curated.dim_geography g ON g.village_code = v.village_code
                WHERE {qualify(VILL[scheme], 'v', 'village_code', 'entity_type')}
                AND g.lgd_village_name !~* '^unresolved' GROUP BY 1 ORDER BY 1""")
            for vi, v in enumerate(vs):
                m = M[scheme][vi % len(M[scheme])]
                y = (yrs[vi % len(yrs)] if yrs and vi % 5 == 0 else None)
                vn = [v["n"].upper(), v["n"].title(), v["n"].lower()][vi % 3]
                C.append(dict(id=f"VI|{scheme}|{m[0]}|{v['c']}", fam="village", scheme=scheme, m=m, mk=m[0], level="village",
                              f={"village": v["c"], **({"year": y} if y else {})}, place=[v["n"], v["b"] or ""], code=v["c"],
                              q=question(scheme, m, vi, f"{vn} village", fy(y, vi) if y else "")))
    return C


async def main():
    fams = sys.argv[1:] or ["state", "district", "block", "ac"]
    schemes = [s for s in os.environ.get("MX_SCHEMES", ",".join(M)).split(",") if s]
    async with app_main.lifespan(app_main.app):
        FP_RAW.update(r["b"] for r in await fetch("SELECT DISTINCT UPPER(block_name_raw) b FROM curated.v_focus_plus WHERE block_name_raw IS NOT NULL"))
        for s in M:
            YEARS[s] = [r["y"] for r in await fetch(f"SELECT DISTINCT year_key y FROM {M[s][0][2]} WHERE year_key IS NOT NULL ORDER BY 1")] \
                if s != "CM Elevate" else []
        cases = await build(fams, schemes)
        if os.path.exists(OUT):
            RESULTS.update(json.load(open(OUT, encoding="utf-8")))
        only = set(open(os.environ["MX_ONLY"], encoding="utf-8").read().split("\n")) - {""} if os.environ.get("MX_ONLY") else None
        todo = [c for c in cases if (c["id"] in only if only is not None else c["id"] not in RESULTS)]
        log(f"{fams} {schemes}: {len(cases)} cases, {len(todo)} to run")
        for k in range(0, len(todo), 100):
            await asyncio.gather(*[run(c) for c in todo[k:k + 100]])
            json.dump(RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            done = [RESULTS[c["id"]] for c in cases if c["id"] in RESULTS]
            log(f"checkpoint {min(k + 100, len(todo))}/{len(todo)} — pass {sum(r['ok'] for r in done)}/{len(done)}")
    done = [RESULTS[c["id"]] for c in cases if c["id"] in RESULTS]
    log(f"DONE {fams}: pass {sum(r['ok'] for r in done)}/{len(done)}")


if __name__ == "__main__":
    asyncio.run(main())
