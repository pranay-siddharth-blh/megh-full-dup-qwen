"""LOG BANK runner (16 Nov 2026). Not collected by pytest.

Runs tests/accuracy/log_bank_2026_11_16.yaml through the gold runner (run_gold.py: the product's own
conversation layer + graph in-process, as the superadmin, model ON, truth recomputed live from each case's SQL),
then adds the log bank's own checks the gold judge does not know:
  not_route  the turn must not take this route        rw_lacks  the rewritten question must not contain these
  max_s      the turn must answer within N seconds    (latency is reported, it is also a failure KIND here)

    .venv/Scripts/python.exe tests/accuracy/run_log_bank.py --label logbank-1
    .venv/Scripts/python.exe tests/accuracy/run_log_bank.py --only LOG-A1,BLK --label part
    .venv/Scripts/python.exe tests/accuracy/run_log_bank.py --post tests/accuracy/results/<run>.json   # re-judge only
    .venv/Scripts/python.exe tests/accuracy/run_log_bank.py --root "D:/meg one clone/meghoneai" --label gate1
        (the code of another checkout; results land in THIS worktree's tests/accuracy/results)

Writes the gold runner's results JSON and <same>_log.json with the extra checks and the failure KINDS.
"""
from __future__ import annotations

import asyncio
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _take_arg(name: str):
    """Remove `name VALUE` from sys.argv (run_gold parses the rest) and return VALUE."""
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


# --root <checkout>: run the bank against ANOTHER checkout's code (e.g. the merged arch branch at a gate):
# its app/ and its run_gold.py are imported (run_gold chdirs to that root, so its .env is used); the bank
# file stays this one unless the target has its own copy.
ROOT_ARG = _take_arg("--root")
POST_ARG = _take_arg("--post")
TARGET_TESTS = os.path.join(os.path.abspath(ROOT_ARG), "tests", "accuracy") if ROOT_ARG else HERE
sys.path.insert(0, TARGET_TESTS)
import run_gold  # noqa: E402  (chdirs to the target repo root, sets sys.path)
import yaml  # noqa: E402

# results always land in THIS worktree (never dirty the checkout under test)
run_gold.RESULTS = os.path.join(HERE, "results")
_bank_name = "log_bank_2026_11_16.yaml"
run_gold.BANK = os.path.join(TARGET_TESTS, _bank_name) if os.path.exists(os.path.join(TARGET_TESTS, _bank_name))     else os.path.join(HERE, _bank_name)


# the report's groups: one line each (pass / total cases)
KINDS = {
    "one-breath block questions (typed)": ["block-oneshot"],
    "one-breath block questions (voice-shaped)": ["block-voice-shaped"],
    "user's logged questions": ["log-headline", "log-chain", "log-trend", "log-year-outside", "log-month",
                                "log-standalone", "log-money", "log-askback", "log-oneshot", "log-knowledge",
                                "log-meta", "log-dashboard"],
    "vague start -> ask-back -> pick": ["vague"],
    "spoken follow-up chains": ["chain"],
    "voice-shaped chains through the pipeline": ["voice"],
    "block-wise wordings after a breakdown": ["blockwise"],
    "scheme + place, no measure (headline)": ["headline-no-measure"],
    "grouping words (per FY / district wise)": ["grouping-words"],
    "every district drilled (block, top 3, lowest, only, year)": ["district-drill"],
    "one-breath combos (two blocks / years, chart, villages)": ["one-breath-combos"],
    "polite 'Can you / Could you' versions of passing questions": ["polite-can-you"],
}


def post(path: str) -> int:
    with open(run_gold.BANK, encoding="utf-8") as fh:
        bank = {c["id"]: c for c in yaml.safe_load(fh)["cases"]}
    with open(path, encoding="utf-8") as fh:
        res = json.load(fh)
    kinds = collections.Counter()
    examples = collections.defaultdict(list)
    lat = []
    n_ok = 0
    for r in res["results"]:
        case = bank.get(r["id"]) or {"turns": []}
        extra_bad = []
        for i, t in enumerate(r["turns"]):
            spec = case["turns"][i] if i < len(case["turns"]) else {}
            lat.append(t.get("seconds") or 0)
            fails = list(t.get("fails") or [])
            if spec.get("not_route") and t.get("route") == spec["not_route"]:
                fails.append(f"[routing/intent] route {t['route']} (must not be {spec['not_route']})")
            for w in spec.get("rw_lacks") or []:
                if w in (t.get("rewritten") or ""):
                    fails.append(f"[follow-up-glue] rewritten carries {w!r}: {t.get('rewritten')!r}")
                    break
            if spec.get("max_s") and (t.get("seconds") or 0) > spec["max_s"]:
                fails.append(f"[latency] {t.get('seconds')} s > {spec['max_s']} s")
            t["log_fails"] = fails
            tags = []
            for f in fails:
                k = f[1:f.index("]")] if f.startswith("[") and "]" in f else (t.get("primary") or "other")
                if k not in tags:
                    tags.append(k)
            for k in tags:                       # one count per turn per kind
                f = next(x for x in fails if x.startswith(f"[{k}]") or k in ("other",))
                kinds[k] += 1
                if len(examples[k]) < 6:
                    examples[k].append({"id": r["id"], "turn": i + 1, "q": t["q"], "route": t.get("route"),
                                        "rewritten": t.get("rewritten"), "fail": f[:300],
                                        "answer": (t.get("answer") or "")[:300], "s": t.get("seconds")})
            if fails and not any(f.startswith("[latency]") for f in fails[:1]) or \
                    [f for f in fails if not f.startswith("[latency]")]:
                extra_bad.append(i)
        r["log_ok"] = not extra_bad
        n_ok += r["log_ok"]
    lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] if lat else 0  # noqa: E731
    by_cat = collections.Counter()
    by_cat_ok = collections.Counter()
    for r in res["results"]:
        by_cat[r["cat"]] += 1
        by_cat_ok[r["cat"]] += r["log_ok"]
    text = [f"LOG BANK: {n_ok}/{len(res['results'])} cases pass (accuracy; latency reported separately)"
            + (f"  [code: {os.path.abspath(ROOT_ARG)}]" if ROOT_ARG else ""),
            "by category: " + ", ".join(f"{c} {by_cat_ok[c]}/{n}" for c, n in sorted(by_cat.items()))]
    for kind, cats in KINDS.items():
        tot = sum(by_cat[c] for c in cats)
        if tot:
            text.append(f"  KIND {kind:<34} {sum(by_cat_ok[c] for c in cats)}/{tot}")
    text += [
            f"latency per turn: median {p(0.5)} s, p90 {p(0.9)} s, max {lat[-1] if lat else 0} s",
            "failure kinds: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common())]
    out = path.replace(".json", "_log.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": text, "kinds": kinds, "examples": examples, "results": res["results"]}, fh, indent=1,
                  ensure_ascii=False, default=str)
    print("\n".join(text))
    print("written", out)
    return 0


def main() -> int:
    if POST_ARG:
        return post(POST_ARG)
    label = sys.argv[sys.argv.index("--label") + 1] if "--label" in sys.argv else "logbank"
    rc = asyncio.run(run_gold.main())
    runs = sorted(glob.glob(os.path.join(run_gold.RESULTS, f"*_{label}.json")), key=os.path.getmtime)
    if runs:
        post(runs[-1])
    return rc


if __name__ == "__main__":
    sys.exit(main())
