"""
Executes every few-shot SQL example the app loads (app/annotations.py: each
scheme's `sql_generation_examples`, retired ones left out), read-only, the way
the chatbot's own SQL runs: the SQLGlot read-only guard (curated / semantic
only), then a READ ONLY transaction on the read-only pool.

The SQL prompt copies these examples' patterns, so an example that does not
even run teaches the model a broken pattern. A few-shot file may call its
examples "validated" in its header only while every one of them runs here
(tests/test_fewshot_headers.py checks the header against the last run).

Outcomes per example:
  ok        ran
  empty     ran, returned no rows (reported, not a failure: a zero can be the answer)
  blocked   refused by the read-only guard (another schema, a write, …) — the
            chatbot could never run it
  error     the database rejected it (a missing column, a type error, …)

    python tests/fewshot_exec/check_fewshots.py --allow-superuser
    python tests/fewshot_exec/check_fewshots.py --scheme "Focus Plus"

Until megh_readonly is configured, --allow-superuser lets the read-only pool
use DATABASE_URL (still guarded, still READ ONLY transactions).
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scheme")
    ap.add_argument("--allow-superuser", action="store_true")
    return ap.parse_args()


ARGS = parse_args()
# Small pools: megh_db is shared (max_connections 100). An env var beats .env.
os.environ.update({"DB_POOL_MIN_SIZE": "1", "DB_POOL_MAX_SIZE": "2",
                   "READONLY_DB_POOL_MIN_SIZE": "1", "READONLY_DB_POOL_MAX_SIZE": "2"})
if ARGS.allow_superuser:
    os.environ["READONLY_DB_ALLOW_SUPERUSER"] = "true"
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from app import annotations, db  # noqa: E402
from app.sql_guard import UnsafeSQLError  # noqa: E402


def few_shot_files() -> dict[str, Path]:
    return {s: annotations._SCHEME_DIRS[s] / annotations._FEW_SHOT_FILE[s] for s in annotations._FEW_SHOT_FILE}


def examples(scheme: str, path: Path) -> list[dict]:
    """Every runnable example in the file, each marked `in_prompt` when the app's
    loader keeps it in the SQL prompt's pool (it drops the ones that read a
    schema the chatbot's role cannot see, or a locked column)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = [e for e in (data.get("sql_generation_examples") or []) if e.get("status") != "RETIRED_v2.0"]
    pooled = {e.get("question") for e in annotations._fit_examples_to_db(scheme, [dict(e) for e in raw])}
    out = []
    for i, e in enumerate(data.get("sql_generation_examples") or []):
        if e.get("status") == "RETIRED_v2.0":
            continue
        for key in ("sql", "caveat_sql"):
            if isinstance(e.get(key), str) and e[key].strip():
                out.append({"index": i, "key": key, "question": e.get("question", ""), "sql": e[key],
                            "in_prompt": e.get("question") in pooled})
    return out


async def run_one(ex: dict) -> dict:
    try:
        rows = await db.run_readonly(ex["sql"])
        return {**ex, "outcome": "ok" if rows else "empty", "rows": len(rows)}
    except UnsafeSQLError as e:
        return {**ex, "outcome": "blocked", "detail": str(e)[:300]}
    except Exception as e:  # noqa: BLE001
        if db.is_connection_error(e):
            raise
        return {**ex, "outcome": "error", "detail": f"{type(e).__name__}: {e}"[:300]}


async def main() -> int:
    files = few_shot_files()
    if ARGS.scheme:
        files = {s: p for s, p in files.items() if s.lower() == ARGS.scheme.lower()}
    await db.init_pool()
    report = {"when": dt.datetime.now().isoformat(timespec="seconds"), "files": {}}
    try:
        for scheme, path in files.items():
            recs = [await run_one(ex) for ex in examples(scheme, path)]      # one at a time: shared DB
            counts = Counter(r["outcome"] for r in recs)
            failing = [r for r in recs if r["outcome"] in ("blocked", "error")]
            report["files"][str(path.relative_to(ROOT)).replace("\\", "/")] = {
                "scheme": scheme, "examples": len(recs), "counts": dict(counts),
                "all_pass": not failing,
                "failing_in_prompt": sum(1 for r in failing if r["in_prompt"]),
                "failing": [{k: r[k] for k in ("index", "key", "question", "outcome", "detail", "in_prompt")}
                            for r in failing]}
            print(f"{scheme:18} {len(recs):4} examples  {dict(counts)}")
            for r in failing:
                print(f"    [{r['index']}{'' if r['key'] == 'sql' else ' caveat'}] {r['outcome']}"
                      f"{' (IN THE PROMPT POOL)' if r['in_prompt'] else ' (kept out of the prompt by the loader)'}: "
                      f"{r['question'][:70]!r}\n        {r['detail'][:200]}")
    finally:
        await db.close_pool()
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "latest.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {out.relative_to(ROOT)}")
    return 0 if all(f["all_pass"] for f in report["files"].values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
