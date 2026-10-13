"""CM Elevate sheet (CM-ELEVATE-OFF-001..030) through the live LangGraph pipeline.
Truth from curated.v_cm_elevate with the project's rules (schema_context
_CMELEVATE_RULES): applicants = COUNT(DISTINCT request_id); applications = COUNT(*);
"pending"/"on hold" = data_verified 'On Hold'; "pending at level N" = current_level;
status = current_file_status (send-back spellings merged); verified = 'Valid';
withdrawn = is_withdraw; sector = scheme_specific->>'sector_id'; village counts
exclude entity_type 'Unresolved'. Hierarchy: every district, every block,
2 villages per district. Usage (repo root): ce_run.py [TC ...] -> ce_results.json"""
import asyncio
import json
import os
import sys

os.environ.setdefault("SHEET_SCHEME", "CM Elevate")
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mg_run  # noqa: E402
from mg_run import run_case, has_name, vals, close  # noqa: E402
from harness import fetch  # noqa: E402
from app import main as app_main  # noqa: E402

mg_run.ONLY = set(sys.argv[1:])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, os.environ.get("CE_OUT", "ce_results.json"))
T_ = "CM-ELEVATE-OFF-"

SHORT = {
    "PRIME Small Enterprise Empowerment and Development (SEED)": "SEED",
    "Meghalaya Piggery Development Scheme": "Piggery",
    "Meghalaya Poultry Farming Scheme": "Poultry",
    "PRIME Tourism Vehicle Scheme": "Tourism Vehicle",
    "PRIME Agriculture Response Vehicle Scheme": "Agriculture Response Vehicle",
    "Meghalaya Dairy Development Scheme": "Dairy",
    "Meghalaya Any Business Venture Scheme": "Any Business Venture",
    "Meghalaya Goat Farming Scheme": "Goat Farming",
    "Meghalaya Warehouse Scheme": "Warehouse",
    "Meghalaya Sericulture & Weaving Scheme": "Sericulture & Weaving",
    "Chief Minister's Green Taxi Scheme": "Green Taxi",
    "Meghalaya Sports & Wellness Centre Scheme": "Sports & Wellness Centre",
    "Agro Tourism Villa Scheme": "Agro Tourism Villa",
    "Meghalaya Cinema Theatre Scheme": "Cinema Theatre",
    "Meghalaya Motorcaravan Scheme": "Motorcaravan",
}


def pname(full, i):
    """Program name as an officer would type it: full name or the short form, alternately."""
    return full if i % 2 == 0 else f"{SHORT[full]} scheme"


def num_ok(rec, n):
    return any(close(c, n, 0.0001) for c in vals(rec))


def checks(*pairs):
    def chk(rec):
        miss = [f"{l}={e}" for l, e in pairs if not num_ok(rec, e)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


def names_and(*pairs_names):
    """[(name, count)] — every count present and every name mentioned."""
    def chk(rec):
        miss = [f"{n}={c}" for n, c in pairs_names if not num_ok(rec, c)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return chk


async def one(sql, params):
    r = await fetch(sql, params)
    return float(list(dict(r[0]).values())[0] or 0)


STATUS = ("CASE WHEN LOWER(current_file_status) LIKE 'sendback%' THEN 'Sent back' WHEN current_file_status IS NULL "
          "THEN '(not recorded)' ELSE INITCAP(LOWER(current_file_status)) END")


async def status_dist(where, params):
    rows = await fetch(f"SELECT {STATUS} s, COUNT(*)::float8 n FROM curated.v_cm_elevate WHERE {where} GROUP BY 1",
                       params)
    return [(r["s"], r["n"]) for r in rows]


async def main():
    async with app_main.lifespan(app_main.app):
        T = []
        add = T.append
        V = "curated.v_cm_elevate"
        districts = [r["d"] for r in await fetch(f"SELECT DISTINCT lgd_district d FROM {V} ORDER BY 1")]
        blocks = await fetch(f"SELECT lgd_block b, MIN(lgd_district) d FROM {V} WHERE lgd_block IS NOT NULL "
                             "GROUP BY 1 ORDER BY 1")
        progs = [r["s"] for r in await fetch(f"SELECT scheme_name s FROM {V} GROUP BY 1 ORDER BY COUNT(*) DESC")]
        villages = await fetch(f"""
            WITH u AS (SELECT UPPER(lgd_village_name) n FROM {V} WHERE entity_type <> 'Unresolved'
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 c AS (SELECT v.village_code, MIN(v.lgd_village_name) name, MIN(v.lgd_district) d, COUNT(*) k
                       FROM {V} v JOIN u ON u.n = UPPER(v.lgd_village_name)
                       WHERE v.entity_type <> 'Unresolved' AND v.lgd_village_name !~ '[^A-Za-z ]'
                       GROUP BY 1 HAVING COUNT(*) >= 3),
                 x AS (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY d ORDER BY md5(name)) rn FROM c)
            SELECT * FROM x WHERE rn <= 2 ORDER BY d, name""")
        mg_run.log(f"{len(districts)} districts, {len(blocks)} blocks, {len(villages)} villages, {len(progs)} programs")
        kw = dict(mgnrega_only=False, year=None)

        # ── statewide ──────────────────────────────────────────────────────
        per_d = [(d, await one(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE lgd_district=$1", [d]))
                 for d in districts]
        add(run_case(T_ + "004", "every district", "How many CM ELEVATE applicants are there in each district?",
                     names_and(*per_d), expected=dict(per_d), **kw))
        per_p = [(p, await one(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE scheme_name=$1", [p])) for p in progs]
        add(run_case(T_ + "005", "every program", "How many applicants are there under each CM ELEVATE program?",
                     names_and(*per_p), expected=dict(per_p), **kw))
        sec = await fetch(f"SELECT scheme_specific->>'sector_id' s, COUNT(DISTINCT request_id)::float8 n FROM {V} "
                          "WHERE scheme_specific->>'sector_id' IS NOT NULL GROUP BY 1")
        add(run_case(T_ + "011", "every sector", "How many CM ELEVATE applicants are associated with each sector?",
                     names_and(*[(r["s"], r["n"]) for r in sec]), expected={r["s"]: r["n"] for r in sec}, **kw))
        sd = await status_dist("TRUE", [])
        add(run_case(T_ + "015", "statewide", "What is the current application status distribution across CM ELEVATE?",
                     names_and(*sd), expected=dict(sd), **kw))
        for lvl in ("level 0", "level 1", "level 2"):
            n = await one(f"SELECT COUNT(*) FROM {V} WHERE LOWER(current_level)=$1", [lvl.replace(" ", "")])
            add(run_case(T_ + "018", lvl, f"How many CM ELEVATE applications are pending at {lvl}?",
                         checks((lvl, n)), expected=n, **kw))
        n = await one(f"SELECT COUNT(*) FROM {V} WHERE data_verified='On Hold'", [])
        add(run_case(T_ + "018", "on hold", "How many CM ELEVATE applications are pending at the On Hold status?",
                     checks(("on hold", n)), expected=n, **kw))
        top = (await fetch(f"SELECT scheme_name s, COUNT(*)::float8 n FROM {V} WHERE data_verified='On Hold' "
                           "GROUP BY 1 ORDER BY 2 DESC LIMIT 1"))[0]
        add(run_case(T_ + "019", "ranking", "Which CM ELEVATE programs have the highest number of pending applications?",
                     lambda r, t=top: (has_name(r, SHORT[t["s"]]) and num_ok(r, t["n"]), f"{t['s']}={t['n']}"),
                     expected=dict(top), **kw))
        top = (await fetch(f"SELECT lgd_district s, COUNT(*)::float8 n FROM {V} WHERE data_verified='On Hold' "
                           "GROUP BY 1 ORDER BY 2 DESC LIMIT 1"))[0]
        add(run_case(T_ + "020", "ranking", "Which districts have the highest number of pending CM ELEVATE applications?",
                     lambda r, t=top: (has_name(r, t["s"]) and num_ok(r, t["n"]), f"{t['s']}={t['n']}"),
                     expected=dict(top), **kw))
        # 013: program + sector combinations (every recorded combination, plus Piggery scheme / Piggery sector = not recorded)
        combos = await fetch(f"SELECT scheme_name p, scheme_specific->>'sector_id' s, COUNT(DISTINCT request_id)::float8 n FROM {V} "
                             "WHERE scheme_specific->>'sector_id' IS NOT NULL GROUP BY 1,2")
        for i, c in enumerate(combos):
            add(run_case(T_ + "013", f"{SHORT[c['p']]} / {c['s']}",
                         f"How many applicants under {pname(c['p'], i)} belong to {c['s']} sector?",
                         checks(("count", c["n"])), expected=c["n"], **kw))

        # ── every district ─────────────────────────────────────────────────
        for i, d in enumerate(districts):
            nm = d.title() if i % 2 else d
            W = "lgd_district=$1"
            add(run_case(T_ + "001", d, f"How many CM ELEVATE applicants are there in {nm}?",
                         checks(("applicants", per_d[i][1])), place=[d.split()[0]], level="district",
                         expected=per_d[i][1], **kw))
            dp = await fetch(f"SELECT scheme_name p, COUNT(DISTINCT request_id)::float8 n, COUNT(*)::float8 r, "
                             f"COUNT(*) FILTER (WHERE data_verified='On Hold')::float8 oh, "
                             f"COUNT(DISTINCT request_id) FILTER (WHERE data_verified='On Hold')::float8 ohd FROM {V} WHERE {W} "
                             "GROUP BY 1 ORDER BY 2 DESC", [d])
            p0 = dp[i % len(dp)]
            add(run_case(T_ + "006", f"{d} / {SHORT[p0['p']]}", f"How many applicants are there under {pname(p0['p'], i)} in {nm}?",
                         checks(("n", p0["n"])), place=[d.split()[0]], level="district", expected=p0["n"], **kw))
            if len(dp) >= 2:
                a, b = dp[0], dp[1]
                add(run_case(T_ + "009", f"{d} / {SHORT[a['p']]}+{SHORT[b['p']]}",
                             f"How many applicants are there in {nm} under {pname(a['p'], i)} and {pname(b['p'], i + 1)}?",
                             checks(("a", a["n"]), ("b", b["n"]), ("total", a["n"] + b["n"])),
                             place=[d.split()[0]], level="district", expected={"a": a["n"], "b": b["n"]}, **kw))
            sec_d = await fetch(f"SELECT scheme_specific->>'sector_id' s, COUNT(DISTINCT request_id)::float8 n FROM {V} WHERE {W} "
                                "AND scheme_specific->>'sector_id' IS NOT NULL GROUP BY 1 ORDER BY 2 DESC", [d])
            s0 = sec_d[0]["s"] if sec_d else "Poultry"
            n0 = sec_d[0]["n"] if sec_d else 0.0
            add(run_case(T_ + "012", f"{d} / {s0}", f"How many applicants are associated with the {s0} sector in {nm}?",
                         checks(("n", n0)), place=[d.split()[0]], level="district", expected=n0, **kw))
            pd = {r["p"]: r for r in dp}
            dairy = pd.get("Meghalaya Dairy Development Scheme")
            poul = pd.get("Meghalaya Poultry Farming Scheme")
            dsec = await one(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE {W} AND scheme_name='Meghalaya Dairy Development Scheme' "
                             "AND scheme_specific->>'sector_id' ILIKE 'poultry'", [d])
            psec = await one(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE {W} AND scheme_name='Meghalaya Poultry Farming Scheme' "
                             "AND scheme_specific->>'sector_id' ILIKE 'poultry'", [d])
            add(run_case(T_ + "014", d, f"How many applicants under Meghalaya Dairy Development Scheme and Meghalaya "
                                        f"Poultry Farming Scheme are associated with Poultry sector in {nm}?",
                         checks(("dairy", dsec), ("poultry", psec)), place=[d.split()[0]], level="district",
                         expected={"dairy": dsec, "poultry": psec}, **kw))
            sdd = await status_dist(W, [d])
            add(run_case(T_ + "017", d, f"What is the application status distribution in {nm}?", names_and(*sdd),
                         place=[d.split()[0]], level="district", expected=dict(sdd), **kw))
            add(run_case(T_ + "021", f"{d} / {SHORT[p0['p']]}", f"How many applications are pending under {pname(p0['p'], i + 1)} in {nm}?",
                         checks(("oh", p0["oh"])), place=[d.split()[0]], level="district", expected=p0["oh"], **kw))
            ver = await fetch(f"SELECT COUNT(DISTINCT request_id) FILTER (WHERE data_verified='Valid')::float8 v, "
                              f"COUNT(DISTINCT request_id) FILTER (WHERE data_verified IS DISTINCT FROM 'Valid')::float8 nv FROM {V} WHERE {W}", [d])
            add(run_case(T_ + "022", d, f"How many applicants have completed data verification in {nm}?",
                         checks(("verified", ver[0]["v"]), ("not verified", ver[0]["nv"])), place=[d.split()[0]],
                         level="district", expected=dict(ver[0]), **kw))
            add(run_case(T_ + "023", f"{d} / {SHORT[p0['p']]}",
                         f"How many applications are currently on hold under {pname(p0['p'], i)} in {nm}?",
                         checks(("oh", p0["oh"])), place=[d.split()[0]], level="district", expected=p0["oh"], **kw))
            add(run_case(T_ + "024", d, f"How many applications have been withdrawn across CM ELEVATE in {nm}?",
                         checks(("withdrawn", 0.0)), place=[d.split()[0]], level="district", expected=0, **kw))
            top3 = dp[:3]
            ch = []
            for p in top3:
                ch += [(f"{SHORT[p['p']]} applicants", p["n"]), (f"{SHORT[p['p']]} on hold", p["ohd"])]
            add(run_case(T_ + "025", d, f"Give me the applicant count and pendency status for "
                                        f"{', '.join(pname(p['p'], k) for k, p in enumerate(top3[:-1]))} and "
                                        f"{pname(top3[-1]['p'], 2)} in {nm}, broken down by sector.",
                         checks(*ch), place=[d.split()[0]], level="district", expected=dict(ch), **kw))
            ohs = await fetch(f"SELECT COALESCE(scheme_specific->>'sector_id','(not recorded)') s, "
                              f"COUNT(*) FILTER (WHERE data_verified='On Hold')::float8 n FROM {V} WHERE {W} GROUP BY 1", [d])
            add(run_case(T_ + "028", d, f"How many applications are pending in each sector in {nm}?",
                         names_and(*[(r["s"], r["n"]) for r in ohs if r["n"]]), place=[d.split()[0]],
                         level="district", expected={r["s"]: r["n"] for r in ohs}, **kw))
            if len(dp) >= 2:
                sb = await fetch(f"SELECT scheme_name p, COUNT(*) FILTER (WHERE LOWER(current_file_status) LIKE 'sendback%')::float8 n "
                                 f"FROM {V} WHERE {W} AND scheme_name = ANY($2::text[]) GROUP BY 1", [d, [a["p"], b["p"]]])
                sbd = {r["p"]: r["n"] for r in sb}
                add(run_case(T_ + "029", d, f"How many applications under {pname(a['p'], i)} and {pname(b['p'], i + 1)} "
                                            f"are currently sent back in {nm}?",
                             checks(("a", sbd.get(a["p"], 0.0)), ("b", sbd.get(b["p"], 0.0))), place=[d.split()[0]],
                             level="district", expected=sbd, **kw))
        # 016: status per program (every program)
        for i, p in enumerate(progs):
            sp = await status_dist("scheme_name=$1", [p])
            add(run_case(T_ + "016", SHORT[p], f"What is the status distribution for {pname(p, i)}?", names_and(*sp),
                         expected=dict(sp), **kw))
        # 027: two programs across two districts
        for i in range(0, len(districts) - 1, 2):
            d1, d2 = districts[i], districts[i + 1]
            pa, pb = progs[i % 4], progs[(i % 4) + 1]
            cells = await fetch(f"SELECT scheme_name p, lgd_district d, COUNT(DISTINCT request_id)::float8 n FROM {V} "
                                "WHERE scheme_name = ANY($1::text[]) AND lgd_district = ANY($2::text[]) GROUP BY 1,2",
                                [[pa, pb], [d1, d2]])
            got = {(r["p"], r["d"]): r["n"] for r in cells}
            ch = [(f"{SHORT[p]}/{d}", got.get((p, d), 0.0)) for p in (pa, pb) for d in (d1, d2)]
            add(run_case(T_ + "027", f"{SHORT[pa]}+{SHORT[pb]} / {d1}+{d2}",
                         f"Compare applicant counts for {pname(pa, 0)} and {pname(pb, 0)} across {d1.title()} and {d2.title()}.",
                         checks(*ch), expected=dict(ch), **kw))

        # ── every block ────────────────────────────────────────────────────
        for i, b in enumerate(blocks):
            bn = b["b"]
            ask = f"{bn.title()} block" if i % 2 == 0 else bn.title()
            W = "lgd_block=$1"
            n = await one(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE {W}", [bn])
            add(run_case(T_ + "002", f"{bn} as '{ask}'", f"How many CM ELEVATE applicants are there in {ask}?",
                         checks(("n", n)), place=[bn], level="block", expected=n, **kw))
            bp = await fetch(f"SELECT scheme_name p, COUNT(DISTINCT request_id)::float8 n FROM {V} WHERE {W} "
                             "GROUP BY 1 ORDER BY 2 DESC, 1", [bn])
            p0 = bp[0]
            add(run_case(T_ + "007", f"{bn} / {SHORT[p0['p']]}", f"How many applicants are there under {pname(p0['p'], i)} in {ask}?",
                         checks(("n", p0["n"])), place=[bn], level="block", expected=p0["n"], **kw))
            if len(bp) >= 3:
                t3 = bp[:3]
                add(run_case(T_ + "010", f"{bn} / 3 programs",
                             f"How many applicants are there in {ask} under {pname(t3[0]['p'], i)}, {pname(t3[1]['p'], i + 1)} "
                             f"and {pname(t3[2]['p'], i)}?",
                             checks(*[(SHORT[x["p"]], x["n"]) for x in t3], ("total", sum(x["n"] for x in t3))),
                             place=[bn], level="block", expected={x["p"]: x["n"] for x in t3}, **kw))
            nv = await one(f"SELECT COUNT(DISTINCT village_code) FROM {V} WHERE {W} AND scheme_name=$2 "
                           "AND entity_type <> 'Unresolved'", [bn, p0["p"]])

            def vchk(rec, nv=nv):
                n = rec.get("n_rows") or 0
                return n == nv or num_ok(rec, nv), f"villages expected={nv} rows={n}"
            add(run_case(T_ + "026", f"{bn} / {SHORT[p0['p']]}",
                         f"How many applicants are there under {pname(p0['p'], i)} in each village of {bn.title()} block?",
                         vchk, place=[bn], level="block", expected=nv, **kw))

        # ── villages (2 per district) ──────────────────────────────────────
        for i, v in enumerate(villages):
            nm = v["name"].upper() if i % 2 == 0 else v["name"].title()
            W = "village_code=$1 AND entity_type <> 'Unresolved'"
            n = await one(f"SELECT COUNT(DISTINCT request_id) FROM {V} WHERE {W}", [v["village_code"]])
            add(run_case(T_ + "003", f"{v['name']} ({v['d']})", f"How many CM ELEVATE applicants are there in {nm}?",
                         checks(("n", n)), place=[v["name"]], level="village", expected=n, **kw))
            vp = await fetch(f"SELECT scheme_name p, COUNT(DISTINCT request_id)::float8 n FROM {V} WHERE {W} "
                             "GROUP BY 1 ORDER BY 2 DESC, 1", [v["village_code"]])
            p0 = vp[0]
            add(run_case(T_ + "008", f"{v['name']} / {SHORT[p0['p']]}", f"How many applicants are there under {pname(p0['p'], i)} in {nm}?",
                         checks(("n", p0["n"])), place=[v["name"]], level="village", expected=p0["n"], **kw))
            sv = await status_dist(f"{W} AND scheme_name=$2", [v["village_code"], p0["p"]])
            add(run_case(T_ + "030", f"{v['name']} / {SHORT[p0['p']]}",
                         f"What is the status-wise applicant count for {pname(p0['p'], i + 1)} in {nm}?", names_and(*sv),
                         place=[v["name"]], level="village", expected=dict(sv), **kw))

        mg_run.log(f"running {len(T)} conversations")
        await asyncio.gather(*T)
    json.dump(mg_run.RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    mg_run.log("written", OUT)


if __name__ == "__main__":
    asyncio.run(main())
