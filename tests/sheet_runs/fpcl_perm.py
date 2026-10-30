"""Focus Plus + CM Elevate Legacy permutations (2026-10-30): paraphrases, word order, aliases,
misspellings, district / block / FY / batch / tranche / sub-scheme combinations, invalid /
ambiguous / conflicting inputs, and multi-turn conversations (breakdown follow-up, metric
switch, year change, scheme switch both ways, clarification resume, unrelated question, stale
context). Every expected figure is read from megh_db with the rules fp_run.py / cl_run.py use:
Focus Plus beneficiaries = COUNT(DISTINCT beneficiary_key), amount = SUM(amount_disbursed);
CM Elevate Legacy applications = COUNT(*), sanctioned = COUNT(sanctioned_amount), disbursed =
SUM(total_disbursement) on curated.v_cm_elevate_disbursement.

A turn is (question, check) where check is a function(rec) -> (ok, note), or ("pause", rule)
when a clarification is the right answer. Other pauses are answered like a user tapping the
matching chip (scheme / place / year / all-of-Meghalaya).
Usage (repo root): fpcl_perm.py [ID ...] -> fpcl_perm.json (PERM_OUT)"""
import asyncio
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Conv, fetch  # noqa: E402
from mg_run import close, has_name, vals  # noqa: E402
from app import main as app_main  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("PERM_OUT", os.path.join(HERE, "fpcl_perm.json"))
SEM = asyncio.Semaphore(int(os.environ.get("MG_CONC", "4")))
ONLY = set(sys.argv[1:])
FP, CL = "curated.v_focus_plus", "curated.v_cm_elevate_disbursement"
BEN, AMT = "COUNT(DISTINCT beneficiary_key)", "SUM(amount_disbursed)"
RESULTS = []


def num(n):
    return lambda r: (any(close(c, n, 0.0001) for c in vals(r)), f"want {n:,.0f}")


def money(a):
    return lambda r: (any(abs(c - f) <= max(0.006, abs(f) * 0.0006) for c in vals(r) for f in (a, a / 1e5, a / 1e7)),
                      f"want Rs {a:,.0f}")


def avg(v):
    return lambda r: (any(abs(c - v) <= 0.6 for c in vals(r)), f"want avg {v:,.2f}")


def all_of(*cs):
    def chk(r):
        res = [c(r) for c in cs]
        return all(ok for ok, _ in res), "; ".join(n for _, n in res)
    return chk


def none_of(*cs):
    """the figure must NOT appear (stale-context leak check)."""
    def chk(r):
        res = [c(r) for c in cs]
        return not any(ok for ok, _ in res), "must not show: " + "; ".join(n for _, n in res)
    return chk


def says(*phrases):
    def chk(r):
        a = (r.get("answer") or "").lower()
        hit = [p for p in phrases if p.lower() in a]
        return bool(hit), f"any of {phrases}"
    return chk


def named(pairs):
    return lambda r: (all(has_name(r, n) and any(close(c, v, 0.0001) for c in vals(r)) for n, v in pairs),
                      "every " + ", ".join(f"{n}={v:,.0f}" for n, v in pairs[:6]) + ("…" if len(pairs) > 6 else ""))


def scheme_is(name):
    return lambda r: (name in (r.get("schemes") or []), f"scheme {name} (got {r.get('schemes')})")


def kind(k):
    return lambda r: (r.get("kind") == k, f"kind {k}")


async def one(sql, params=()):
    r = await fetch(sql, list(params))
    return float(list(dict(r[0]).values())[0] or 0)


def _pick(rec, want):
    labels, qs = rec.get("options") or [], rec.get("option_qs") or []
    rule = rec.get("rule")
    for l, q in zip(labels, qs):
        low = (l or "").lower()
        if rule in ("focus-scheme-ambiguous", "scheme-not-specified", "scheme-not-available",
                    "cm-elevate-dataset") or "scheme" in (rule or "") or "dataset" in (rule or ""):
            if want.get("scheme") and low.startswith(want["scheme"].lower()):
                return q
        elif rule == "year-not-specified":
            if low.startswith("all "):
                return q
        elif want.get("place") and want["place"].lower() in (low + " " + (q or "").lower()):
            return q
        elif rule == "scope-not-specified" and ("all of meghalaya" in low or "statewide" in low):
            return q
    return None


async def scenario(sid, group, turns, want=None):
    if ONLY and sid not in ONLY:
        return
    want = want or {}
    async with SEM:
        c = Conv()
        out = []
        for q, chk in turns:
            rec = await c.ask(q)
            notes = []
            if isinstance(chk, tuple) and chk[0] == "pause":
                ok = rec["kind"] == "pause" and (chk[1] is None or rec.get("rule") == chk[1])
                out.append({"q": q, "ok": ok, "note": f"want pause {chk[1]}, got {rec['kind']} {rec.get('rule')}",
                            "rec": rec})
                continue
            for _ in range(3):
                if rec["kind"] != "pause":
                    break
                pick = _pick(rec, want)
                notes.append(f"pause {rec.get('rule')} -> {pick}")
                if not pick:
                    break
                rec = await c.ask(pick)
            ok, note = chk(rec) if rec["kind"] != "error" else (False, "error: " + str(rec.get("answer"))[:80])
            if rec["kind"] == "pause":
                note = f"ended in pause {rec.get('rule')}: " + note
            out.append({"q": q, "ok": bool(ok), "note": note, "pauses": notes, "rec": rec})
        RESULTS.append({"id": sid, "group": group, "ok": all(t["ok"] for t in out), "turns": out})
        mark = "PASS" if all(t["ok"] for t in out) else "FAIL"
        print(f"{mark} {sid} " + " | ".join(f"{'ok' if t['ok'] else 'X'}:{t['note'][:70]}" for t in out), flush=True)


async def main():
    async with app_main.lifespan(app_main.app):
        S = []
        add = S.append
        FPW, CLW = {"scheme": "Focus Plus"}, {"scheme": "CM Elevate Legacy"}

        # ── truth ───────────────────────────────────────────────────────────
        fpd = {r["d"]: (float(r["b"]), float(r["a"])) for r in await fetch(
            f"SELECT lgd_district d, {BEN} b, {AMT} a FROM {FP} GROUP BY 1")}
        fp_tot_b, fp_tot_a = await one(f"SELECT {BEN} FROM {FP}"), await one(f"SELECT {AMT} FROM {FP}")
        fp_d_fy = {(r["d"], r["f"]): float(r["a"]) for r in await fetch(
            f"SELECT lgd_district d, financial_year f, {AMT} a FROM {FP} GROUP BY 1,2")}
        fp_fy = {r["f"]: (float(r["b"]), float(r["a"])) for r in await fetch(
            f"SELECT financial_year f, {BEN} b, {AMT} a FROM {FP} GROUP BY 1")}
        fp_d_batch = {(r["d"], r["k"]): float(r["a"]) for r in await fetch(
            f"SELECT lgd_district d, batch_label k, {AMT} a FROM {FP} GROUP BY 1,2")}
        fp_fem = {r["d"]: float(r["b"]) for r in await fetch(
            f"SELECT lgd_district d, {BEN} b FROM {FP} WHERE gender='Female' GROUP BY 1")}
        fp_d_tr = {(r["d"], r["t"]): float(r["a"]) for r in await fetch(
            f"SELECT lgd_district d, tranche_label t, {AMT} a FROM {FP} GROUP BY 1,2")}
        cld = {r["d"]: (float(r["n"]), float(r["k"]), float(r["t"] or 0)) for r in await fetch(
            f"SELECT lgd_district d, COUNT(*) n, COUNT(sanctioned_amount) k, SUM(total_disbursement) t FROM {CL} GROUP BY 1")}
        cl_tot = dict((await fetch(f"SELECT COUNT(*)::float8 n, COUNT(sanctioned_amount)::float8 k, "
                                   f"SUM(total_disbursement)::float8 t, SUM(total_subsidy_disbursement)::float8 s, "
                                   f"SUM(total_loan_disbursement)::float8 l FROM {CL}"))[0])
        cl_fy = {r["f"]: (float(r["n"]), float(r["t"] or 0)) for r in await fetch(
            f"SELECT financial_year_short f, COUNT(*) n, SUM(total_disbursement) t FROM {CL} "
            "WHERE financial_year_short IS NOT NULL GROUP BY 1")}
        cl_sch_fy = [(r["s"], float(r["n"])) for r in await fetch(
            f"SELECT scheme_name s, COUNT(*) n FROM {CL} WHERE financial_year_short='2025-26' GROUP BY 1")]
        cl_pig_d = {r["d"]: float(r["n"]) for r in await fetch(
            f"SELECT lgd_district d, COUNT(*) n FROM {CL} WHERE scheme_name ILIKE '%Piggery%' GROUP BY 1")}
        cl_poul_fy = await one(f"SELECT COUNT(*) FROM {CL} WHERE scheme_name ILIKE '%Poultry%' AND financial_year_short='2024-25'")
        cl_loan_d = {r["d"]: float(r["l"] or 0) for r in await fetch(
            f"SELECT lgd_district d, SUM(total_loan_disbursement) l FROM {CL} GROUP BY 1")}
        cl_blk = {}
        for r in await fetch(f"SELECT lgd_district d, lgd_block b, SUM(total_disbursement) t FROM {CL} "
                             "WHERE lgd_block IS NOT NULL GROUP BY 1,2"):
            cl_blk.setdefault(r["d"], []).append((r["b"], float(r["t"] or 0)))
        EKH, RB, WGH, WJH, EGH = "EAST KHASI HILLS", "RI BHOI", "WEST GARO HILLS", "WEST JAINTIA HILLS", "EAST GARO HILLS"

        # ── Focus Plus: single turn ─────────────────────────────────────────
        add(scenario("FP-P01", "paraphrase", [("focus plus beneficiaries in east khasi hills", num(fpd[EKH][0]))]))
        add(scenario("FP-P02", "word order", [("In Ri Bhoi, how many people got Focus Plus money?", num(fpd[RB][0]))]))
        add(scenario("FP-P03", "abbreviation", [("No. of FOCUS+ beneficiaries in E Khasi Hills", num(fpd[EKH][0]))]))
        add(scenario("FP-P04", "alias", [("How many households are covered under focusplus in West Garo Hills?",
                                          num(fpd[WGH][0]))]))
        add(scenario("FP-P05", "district+FY", [("Total Focus Plus disbursement in West Garo Hills in FY 2025-26",
                                                money(fp_d_fy[(WGH, "2025-2026")]))]))
        add(scenario("FP-P06", "district+FY reorder", [("In 2022-23, how much was paid under Focus+ in Ri Bhoi?",
                                                        money(fp_d_fy[(RB, "2022-2023")]))]))
        add(scenario("FP-P07", "batch+district", [("Focus Plus amount disbursed for the 12.5K batch in East Khasi Hills",
                                                   money(fp_d_batch.get((EKH, "12.5K"), 0.0)))]))
        fem_d = max(fp_fem, key=fp_fem.get)       # gender is recorded on the 12.5K cohort only
        add(scenario("FP-P08", "gender+district", [(f"How many female Focus+ beneficiaries are in {fem_d.title()}?",
                                                    num(fp_fem[fem_d]))]))
        add(scenario("FP-P09", "tranche+district", [("How much Focus Plus money was disbursed in Tranche 2 in East Garo Hills?",
                                                     money(fp_d_tr.get((EGH, "Tranch 2 - August"), 0.0)))]))
        add(scenario("FP-P10", "misspelling", [("focus pls beneficiares in east khasi hils", num(fpd[EKH][0]))]))
        add(scenario("FP-P11", "FY-only beneficiaries", [("How many Focus Plus beneficiaries were paid in FY 2022-23?",
                                                          num(fp_fy["2022-2023"][0]))]))
        add(scenario("FP-P12", "FY average", [("Average Focus Plus payment per beneficiary in 2025-26",
                                               avg(fp_fy["2025-2026"][1] / fp_fy["2025-2026"][0]))]))
        add(scenario("FP-P13", "statewide terse", [("total focus+ beneficiaries", num(fp_tot_b))]))
        add(scenario("FP-P14", "statewide money", [("Focus Plus: total amount released so far?", money(fp_tot_a))]))
        add(scenario("FP-N01", "invalid year", [("Focus Plus disbursement in 2019-20",
                                                 says("no ", "not ", "only", "2022-23", "2025-26"))]))
        add(scenario("FP-N02", "outside Meghalaya", [("How many Focus Plus beneficiaries are in Guwahati?",
                                                      none_of(num(fp_tot_b)))]))
        add(scenario("FP-N03", "ambiguous bare Focus", [("How many Focus beneficiaries are in Ri Bhoi?",
                                                         ("pause", "focus-scheme-ambiguous"))]))
        add(scenario("FP-N04", "unknown district", [("Focus Plus beneficiaries in Khasi Garo district",
                                                     none_of(num(fp_tot_b)))]))

        # ── CM Elevate Legacy: single turn ──────────────────────────────────
        add(scenario("CL-P01", "terse", [("cm elevate legacy applications in ri bhoi", num(cld[RB][0]))]))
        add(scenario("CL-P02", "word order", [("In West Garo Hills, how many CM Elevate Legacy applications were sanctioned?",
                                               num(cld[WGH][1]))]))
        add(scenario("CL-P03", "sub-scheme+district", [("Piggery applications in East Khasi Hills under CM Elevate Legacy",
                                                        num(cl_pig_d.get(EKH, 0.0)))]))
        add(scenario("CL-P04", "FY money", [("CM Elevate Legacy disbursement in FY 2025-26", money(cl_fy["2025-26"][1]))]))
        add(scenario("CL-P05", "sub-scheme+FY", [("How many poultry applications under CM Elevate Legacy in 2024-25?",
                                                  num(cl_poul_fy))]))
        add(scenario("CL-P06", "subsidy", [("How much subsidy was disbursed under CM Elevate Legacy?", money(cl_tot["s"]))]))
        add(scenario("CL-P07", "loan+district", [("How much loan was disbursed under CM Elevate Legacy in East Garo Hills?",
                                                  money(cl_loan_d.get(EGH, 0.0)))]))
        add(scenario("CL-P08", "misspelling", [("cm elevat legacy aplications in east khasi hills", num(cld[EKH][0]))]))
        add(scenario("CL-P09", "alias", [("elevate legacy sanctioned cases statewide", num(cl_tot["k"]))]))
        add(scenario("CL-P10", "sanction money word", [("How much has been disbursed under CM Elevate in Ri Bhoi?",
                                                         money(cld[RB][2]))]))
        add(scenario("CL-N01", "invalid year", [("CM Elevate Legacy applications in 2021-22",
                                                 says("no ", "not ", "only", "2024-25", "2025-26"))]))
        add(scenario("CL-N02", "outside Meghalaya", [("CM Elevate Legacy applications in Kolkata",
                                                      none_of(num(cl_tot["n"])))]))

        # ── multi-turn ──────────────────────────────────────────────────────
        add(scenario("MT-01", "breakdown follow-up", [
            ("How many Focus Plus beneficiaries are there?", num(fp_tot_b)),
            ("Give me the district-wise breakdown", named([(d, v[0]) for d, v in fpd.items() if d])),
        ], FPW))
        add(scenario("MT-02", "metric switch", [
            ("How many Focus Plus beneficiaries are there in Ri Bhoi?", num(fpd[RB][0])),
            ("And how much was disbursed there?", money(fpd[RB][1])),
        ], FPW))
        add(scenario("MT-03", "year change", [
            ("Focus Plus disbursement in East Khasi Hills in FY 2022-23", money(fp_d_fy[(EKH, "2022-2023")])),
            ("What about 2025-26?", money(fp_d_fy[(EKH, "2025-2026")])),
        ], FPW))
        add(scenario("MT-04", "scheme switch FP->CL", [
            ("How much Focus Plus money was disbursed in West Garo Hills?", money(fpd[WGH][1])),
            ("Same for CM Elevate Legacy", money(cld[WGH][2])),
        ], CLW))
        add(scenario("MT-05", "clarification resume", [
            ("How many Focus beneficiaries are in Ri Bhoi?", ("pause", "focus-scheme-ambiguous")),
            ("Focus Plus", num(fpd[RB][0])),
        ], FPW))
        add(scenario("MT-06", "unrelated then new", [
            ("Focus Plus beneficiaries in East Khasi Hills", num(fpd[EKH][0])),
            ("What is the weather today?", kind("answer")),
            ("How many CM Elevate Legacy applications are there in the whole state?", num(cl_tot["n"])),
        ], CLW))
        add(scenario("MT-07", "place change", [
            ("Focus Plus beneficiaries in East Khasi Hills", num(fpd[EKH][0])),
            ("What about West Jaintia Hills?", num(fpd[WJH][0])),
        ], FPW))
        add(scenario("MT-08", "stale place after switch", [
            ("Focus Plus beneficiaries in East Khasi Hills", num(fpd[EKH][0])),
            ("How many CM Elevate Legacy applications are there in all of Meghalaya?",
             all_of(num(cl_tot["n"]), none_of(num(cld[EKH][0])))),
        ], CLW))
        add(scenario("MT-09", "subset follow-up", [
            ("How many CM Elevate Legacy applications are there in East Khasi Hills?", num(cld[EKH][0])),
            ("How many of those were sanctioned?", num(cld[EKH][1])),
        ], CLW))
        add(scenario("MT-10", "scheme switch CL->FP", [
            ("CM Elevate Legacy applications in Ri Bhoi", num(cld[RB][0])),
            ("Now show Focus Plus beneficiaries there", num(fpd[RB][0])),
        ], FPW))
        add(scenario("MT-11", "add year filter", [
            ("CM Elevate Legacy applications for each scheme", kind("answer")),
            ("Only for FY 2025-26", named(cl_sch_fy)),
        ], CLW))
        add(scenario("MT-12", "block breakdown follow-up", [
            ("CM Elevate Legacy disbursement in East Garo Hills", money(cld[EGH][2])),
            ("Break it down by block", lambda r: (all(any(abs(c - f) <= max(0.006, abs(f) * 0.0006) for c in vals(r)
                                                           for f in (t, t / 1e5, t / 1e7)) for _b, t in cl_blk[EGH] if t),
                                                  "every block total of " + EGH)),
        ], CLW))
        add(scenario("MT-13", "place change CL", [
            ("CM Elevate Legacy applications in East Khasi Hills", num(cld[EKH][0])),
            ("and in West Garo Hills?", num(cld[WGH][0])),
        ], CLW))
        add(scenario("MT-14", "switch back keeps new scheme", [
            ("Focus Plus beneficiaries in Ri Bhoi", num(fpd[RB][0])),
            ("CM Elevate Legacy applications in Ri Bhoi", num(cld[RB][0])),
            ("What about West Garo Hills?", num(cld[WGH][0])),
        ], CLW))
        add(scenario("MT-15", "year change CL", [
            ("CM Elevate Legacy disbursement in FY 2024-25", money(cl_fy["2024-25"][1])),
            ("and 2025-26?", money(cl_fy["2025-26"][1])),
        ], CLW))
        add(scenario("MT-16", "drop filter", [
            ("Focus Plus disbursement in East Khasi Hills", money(fpd[EKH][1])),
            ("What is it for the whole state?", money(fp_tot_a)),
        ], FPW))

        print(f"running {len(S)} scenarios", flush=True)
        await asyncio.gather(*S)

    def clean(o):
        r = dict(o)
        r["turns"] = [{**t, "rec": {k: t["rec"].get(k) for k in ("kind", "answer", "rule", "options", "sql",
                                                                  "schemes", "entities", "rewritten", "rows")}}
                      for t in o["turns"]]
        return r
    json.dump([clean(x) for x in sorted(RESULTS, key=lambda x: x["id"])], open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    n_ok = sum(x["ok"] for x in RESULTS)
    print(f"DONE {n_ok}/{len(RESULTS)} passed -> {OUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
