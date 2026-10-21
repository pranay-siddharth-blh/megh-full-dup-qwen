"""Score an mg_run results file per TC. A case passes when it ends in an answer
with the DB figure at the right level and needed no 'which scheme?' pause.
Checker corrections: a 0-vs-0 wages/materials tie with both zeros stated, and a
percentage whose denominator is 0 answered 'cannot be calculated'."""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root, for tests._text_checks
from tests._text_checks import zero_lakh  # noqa: E402

R = json.load(open(sys.argv[1], encoding="utf-8"))


def verdict(tc, c):
    t = c["turns"][-1]
    a = t.get("answer") or ""
    if t["kind"] == "answer" and not c["ok"]:
        exp = c.get("expected")
        if tc == "DATA-023" and isinstance(exp, dict) and not exp.get("wages") and not exp.get("material") \
                and zero_lakh(a):
            return "ok"
        if exp is None and ("cannot be calculated" in a or "divided by is 0" in a):
            return "ok"
    if c["ok"] and not c["scheme_defect"]:
        return "ok"
    if a.startswith("Sorry, I can"):
        return "guardrail refused a data question"
    if c["scheme_defect"] and c["ok"]:
        return "asked 'which scheme?' (right figure after picking MGNREGA)"
    if any("unanswerable" in n or "NO MATCHING" in n for n in c["pause_notes"]):
        return "pause the user cannot answer / wrong options"
    if t["kind"] != "answer":
        return f"ended in {t['kind']} {t.get('rule')}"
    if c.get("level_ok") is False:
        return "wrong place level"
    return "wrong value"


out = {}
for tc in sorted(R):
    cnt = collections.Counter()
    ex = collections.defaultdict(list)
    for c in R[tc]:
        v = verdict(tc, c)
        cnt[v] += 1
        if v != "ok" and len(ex[v]) < 3:
            ex[v].append(f"{c['label']}: {(c['turns'][-1].get('answer') or '')[:140]}")
    out[tc] = {"n": sum(cnt.values()), "ok": cnt["ok"], "fails": {k: v for k, v in cnt.items() if k != "ok"},
               "examples": ex}
    print(tc, f"{cnt['ok']}/{sum(cnt.values())}", {k: v for k, v in cnt.items() if k != "ok"})
json.dump(out, open(sys.argv[1].replace(".json", "_score.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
