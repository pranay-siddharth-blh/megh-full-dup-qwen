"""B1 review list — officers' wordings that named no catalogue measure, with the
nearest measure by meaning, from the app's shadow log (METRIC_MEANING_FILE,
default logs/metric_meaning_shadow.jsonl). For a PERSON to approve: an approved
wording goes into data/metric_catalog_synonyms.yaml (see its header). Nothing
here changes an answer. NOT a pytest suite; no VPN needed.

    .venv/Scripts/python.exe -X utf8 tests/metric_meaning/review.py [--file PATH] [--min-count N]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", default=str(ROOT / "logs" / "metric_meaning_shadow.jsonl"))
    ap.add_argument("--min-count", type=int, default=1, help="only wordings seen at least N times")
    args = ap.parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"no shadow log yet at {path}")
        return 0
    groups: dict = defaultdict(lambda: {"n": 0, "nearest": defaultdict(int), "score": 0.0, "margin": 0.0})
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        g = groups[(r["scheme"], r["wording"].lower())]
        g["n"] += 1
        g["nearest"][r["nearest"]] += 1
        g["score"] += r.get("score", 0.0)
        g["margin"] += r.get("margin", 0.0)
    rows = sorted(((k, g) for k, g in groups.items() if g["n"] >= args.min_count), key=lambda kv: -kv[1]["n"])
    print(f"{'seen':>4}  {'scheme':17} {'officer wording':36} {'nearest measure':40} score  margin")
    for (scheme, wording), g in rows:
        nearest = max(g["nearest"], key=g["nearest"].get)
        print(f"{g['n']:>4}  {scheme:17} {wording[:36]:36} {nearest[:40]:40} {g['score'] / g['n']:.3f}  "
              f"{g['margin'] / g['n']:.3f}")
    print(f"\n{len(rows)} wording(s). A high score is NOT approval: check the meaning by hand "
          "(data/metric_catalog_synonyms.yaml).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
