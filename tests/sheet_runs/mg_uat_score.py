"""Score mg_uat.py / mg_uat_villages.py result files: pass counts per test case (and per tag:
-state / -xdistrict / -xblock / -samename), each failure with its reason.
Usage: mg_uat_score.py <out.json> [<out2.json> ...] [--fails N]"""
import collections
import json
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
nfail = int(next((a.split("=")[1] for a in sys.argv[1:] if a.startswith("--fails=")), "60"))
R = collections.defaultdict(list)
for f in args:
    for k, v in json.load(open(f, encoding="utf-8")).items():
        R[k] += v


def reason(c):
    t = c["turns"][-1]
    if c.get("defects"):
        return "; ".join(c["defects"])
    if t["kind"] != "answer":
        return f"ended in {t['kind']} {t.get('rule') or ''}"
    if c.get("value_ok") and c.get("level_ok") is False:
        return "wrong place level"
    return "wrong value: " + (c.get("note") or "")


tot = ok = 0
fails = []
for tc in sorted(R):
    cs = R[tc]
    good = sum(1 for c in cs if c["ok"])
    tot += len(cs)
    ok += good
    why = collections.Counter(reason(c).split(":")[0] for c in cs if not c["ok"])
    print(f"{tc:22s} {good:5d}/{len(cs):<5d} {dict(why) if why else ''}")
    fails += [(tc, c) for c in cs if not c["ok"]]
print(f"TOTAL {ok}/{tot}  ({100.0 * ok / max(tot, 1):.2f}%)")
for tc, c in fails[:nfail]:
    t = c["turns"][-1]
    print(f"- {tc} | {c['label']} | Q: {c['q']} | {reason(c)} | A: {(t.get('answer') or '')[:260]!r}")
    for line in t.get("repairs") or []:
        print(f"      repair: {line[:300]}")
