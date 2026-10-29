"""
YAML vs Qdrant SQL examples (SQL_EXAMPLES_SOURCE, D-074): runs the held-out
NL->SQL set twice through run_eval.py — once with the per-scheme YAML few-shot
banks, once with megh_sql_metadata — and compares the two runs item by item:

  correctness   accuracy, and the items only one source gets right
  repairs       SQL answered first try, repairs made, verifier rejections
  latency       mean / median / p90 seconds per question

Both runs score with run_eval.py itself (same gold SQL, same compare.py), so
the only difference is where the worked examples came from. Run-to-run noise
on this set is about +-3 points (2 items): judge the per-item lists, not one
swing.

Before the Qdrant run the eval questions are checked against the collection's
example questions with the same rule as holdout.py: an eval question already
in megh_sql_metadata would be answered from its own worked example, so the run
is refused. Only ids are printed, never the questions.

    python tests/nl2sql_eval/compare_examples_source.py --allow-superuser
    python tests/nl2sql_eval/compare_examples_source.py --scheme MGNREGA
    python tests/nl2sql_eval/compare_examples_source.py --compare results/A.json results/B.json
"""
import argparse
import datetime as dt
import json
import os
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
sys.path.insert(0, str(ROOT))

SOURCES = ("yaml", "qdrant")


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scheme", help="only this scheme")
    ap.add_argument("--ids", help="only these ids, comma-separated")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--allow-superuser", action="store_true", help="passed to run_eval.py")
    ap.add_argument("--compare", nargs=2, metavar=("YAML_RUN", "QDRANT_RUN"),
                    help="compare two saved run_eval results instead of running")
    return ap.parse_args()


def qdrant_leaks() -> list[str]:
    """Ids of eval questions that match an example question in the collection."""
    from qdrant_client import QdrantClient, models
    from rapidfuzz import fuzz

    from app.config import settings
    from tests.nl2sql_eval import holdout

    client = QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY or None, timeout=30)
    texts, offset = [], None
    flt = models.Filter(must=[models.FieldCondition(key="kind", match=models.MatchAny(any=["example", "join"]))])
    while True:
        points, offset = client.scroll(settings.SQL_EXAMPLES_COLLECTION, scroll_filter=flt, limit=256,
                                       offset=offset, with_payload=["question", "example_question"],
                                       with_vectors=False)
        for p in points:
            for key in ("question", "example_question"):
                if (p.payload or {}).get(key):
                    texts.append(holdout.norm(str(p.payload[key])))
        if offset is None:
            break
    client.close()
    leaked = []
    for item in holdout.load_questions():
        q = holdout.norm(item["question"])
        if any(fuzz.ratio(q, t) >= holdout.LEAK_SCORE for t in texts if t):
            leaked.append(item["id"])
    return leaked


def run(source: str, args) -> Path:
    label = f"examples-{source}"
    cmd = [sys.executable, str(HERE / "run_eval.py"), "--label", label,
           "--concurrency", str(args.concurrency), "--timeout", str(args.timeout)]
    for flag in ("scheme", "ids"):
        if getattr(args, flag):
            cmd += [f"--{flag}", getattr(args, flag)]
    if args.allow_superuser:
        cmd.append("--allow-superuser")
    before = set(RESULTS.glob(f"*_{label}.json"))
    print(f"\n=== SQL_EXAMPLES_SOURCE={source} ===", flush=True)
    # An environment variable beats .env, so this run alone uses `source`.
    rc = subprocess.run(cmd, cwd=ROOT, env={**os.environ, "SQL_EXAMPLES_SOURCE": source}).returncode
    new = sorted(set(RESULTS.glob(f"*_{label}.json")) - before)
    if not new:
        raise SystemExit(f"run_eval.py ({source}) saved no result (exit {rc})")
    return new[-1]


def _sql_stats(records: list[dict]) -> dict:
    with_sql = [r for r in records if r.get("sql")]
    secs = sorted(float(r.get("seconds") or 0) for r in records if r["outcome"] != "gold_error")
    p90 = secs[min(len(secs) - 1, int(0.9 * len(secs)))] if secs else None
    return {
        "ran_sql": len(with_sql),
        "first_try": sum(1 for r in with_sql if not r.get("repairs")),
        "repairs": sum(int(r.get("repairs") or 0) for r in records),
        "verifier_rejections": sum(int(r.get("verifier_rejections") or 0) for r in records),
        "seconds_mean": round(statistics.mean(secs), 1) if secs else None,
        "seconds_median": round(statistics.median(secs), 1) if secs else None,
        "seconds_p90": round(p90, 1) if p90 is not None else None,
    }


def compare(yaml_path: Path, qdrant_path: Path) -> dict:
    a = json.loads(yaml_path.read_text(encoding="utf-8"))
    b = json.loads(qdrant_path.read_text(encoding="utf-8"))
    ra = {r["id"]: r for r in a["records"]}
    rb = {r["id"]: r for r in b["records"]}
    ids = sorted(set(ra) & set(rb))
    if not ids:
        raise SystemExit("the two runs share no item ids")
    sub_a, sub_b = [ra[i] for i in ids], [rb[i] for i in ids]
    acc = lambda rs: round(100 * sum(r["outcome"] == "correct" for r in rs)  # noqa: E731
                           / max(1, sum(r["outcome"] != "gold_error" for r in rs)), 1)
    per_scheme = {}
    for s in sorted({r["scheme"] for r in sub_a}):
        per_scheme[s] = {"yaml": acc([r for r in sub_a if r["scheme"] == s]),
                         "qdrant": acc([r for r in sub_b if r["scheme"] == s])}
    return {
        "when": dt.datetime.now().isoformat(timespec="seconds"),
        "runs": {"yaml": yaml_path.name, "qdrant": qdrant_path.name},
        "items": len(ids),
        "accuracy": {"yaml": acc(sub_a), "qdrant": acc(sub_b)},
        "outcomes": {"yaml": dict(Counter(r["outcome"] for r in sub_a)),
                     "qdrant": dict(Counter(r["outcome"] for r in sub_b))},
        "sql": {"yaml": _sql_stats(sub_a), "qdrant": _sql_stats(sub_b)},
        "per_scheme": per_scheme,
        "only_yaml_correct": [i for i in ids if ra[i]["outcome"] == "correct" != rb[i]["outcome"]],
        "only_qdrant_correct": [i for i in ids if rb[i]["outcome"] == "correct" != ra[i]["outcome"]],
        "more_repairs_with_qdrant": [i for i in ids
                                     if int(rb[i].get("repairs") or 0) > int(ra[i].get("repairs") or 0)],
        "fewer_repairs_with_qdrant": [i for i in ids
                                      if int(rb[i].get("repairs") or 0) < int(ra[i].get("repairs") or 0)],
    }


def report(c: dict) -> None:
    print(f"\nYAML vs QDRANT examples — {c['items']} items")
    print(f"  {'':24}{'yaml':>10}{'qdrant':>10}")
    print(f"  {'accuracy %':24}{c['accuracy']['yaml']:>10}{c['accuracy']['qdrant']:>10}")
    for k in ("ran_sql", "first_try", "repairs", "verifier_rejections",
              "seconds_mean", "seconds_median", "seconds_p90"):
        print(f"  {k:24}{c['sql']['yaml'][k]!s:>10}{c['sql']['qdrant'][k]!s:>10}")
    for s, v in c["per_scheme"].items():
        print(f"  {s:24}{v['yaml']!s:>10}{v['qdrant']!s:>10}")
    print(f"  outcomes yaml:   {c['outcomes']['yaml']}")
    print(f"  outcomes qdrant: {c['outcomes']['qdrant']}")
    print(f"  correct only with yaml:   {c['only_yaml_correct']}")
    print(f"  correct only with qdrant: {c['only_qdrant_correct']}")
    print(f"  more repairs with qdrant: {c['more_repairs_with_qdrant']}")
    print(f"  fewer repairs with qdrant: {c['fewer_repairs_with_qdrant']}")


def main() -> int:
    args = parse_args()
    if args.compare:
        paths = [Path(p) if Path(p).is_absolute() else HERE / p for p in args.compare]
    else:
        print("hold-out check against the Qdrant examples ...")
        leaked = qdrant_leaks()
        if leaked:
            print(f"{len(leaked)} eval question(s) are in the Qdrant examples: {leaked} — "
                  "the Qdrant run would score them on their own worked example; refusing.")
            return 2
        paths = [run(s, args) for s in SOURCES]
    c = compare(*paths)
    report(c)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{dt.datetime.now():%Y-%m-%d_%H%M}_examples-compare.json"
    out.write_text(json.dumps(c, indent=1), encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
