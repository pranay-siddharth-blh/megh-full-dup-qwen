"""Grade a baseline run of the 20 sheet questions (baseline.py's JSON, taken on the
code BEFORE the fixes) with the current grade.py / truth.py, so the workbook's
"before fixes" column states each failure's reason.

Usage (repo root): python tests/sheet_runs/cross/grade_baseline.py <baseline.json> <out.json>"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import cross_run as CR  # noqa: E402
import truth as T  # noqa: E402

D, B = "EAST KHASI HILLS", "MYLLIEM"
TRIO = ["EAST KHASI HILLS", "RI BHOI", "WEST GARO HILLS"]


async def main(src, out):
    base = json.load(open(src, encoding="utf-8"))
    await T.load()
    cases = {c["id"]: c for c in await CR.build(["sheet"])}
    cases["CROSS-16"] = CR.case("CROSS-16", "sheet", "count", ["Focus Plus", "CM Elevate Legacy"], 0,
                                q=base["CROSS-16"]["q"], f={"districts": TRIO})
    cases["CROSS-16"]["group"] = "district"
    alias = {"CROSS-8": f"CROSS-8|{D}", "CROSS-9": f"CROSS-9|{B}", "CROSS-11": f"CROSS-11|{D}", "CROSS-14": f"CROSS-14|{D}"}
    res = {}
    for k, rec in base.items():
        c = cases[alias.get(k, k)]
        if rec["kind"] != "answer":
            bad = [f"ended in {rec['kind']} {rec.get('rule') or ''}: {(rec.get('answer') or '')[:160]}"]
        else:
            E = await CR.expected(c)
            bad = CR.check(c, rec, E)
        res[k] = {"ok": not bad, "bad": bad, "answer": rec.get("answer"), "kind": rec["kind"], "ms": rec.get("ms")}
        print(k, "OK " if not bad else "BAD", "; ".join(bad)[:200])
    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print(sum(r["ok"] for r in res.values()), "/", len(res), "pass")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
