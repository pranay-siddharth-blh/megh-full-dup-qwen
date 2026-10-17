"""
Run one SQL statement the way the eval runs gold SQL: the SQLGlot read-only
guard (curated / semantic only), then a READ ONLY transaction on the read-only
pool. For writing and checking gold SQL.

    python -m tests.nl2sql_eval.sql_check "SELECT COUNT(*) FROM curated.v_pmay"
    python -m tests.nl2sql_eval.sql_check --file q.sql

Needs READONLY_DATABASE_URL (megh_readonly). Until that role is set up,
--allow-superuser lets the read-only pool use DATABASE_URL — still guarded and
inside READ ONLY transactions, but say so wherever its numbers are reported.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sql", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--allow-superuser", action="store_true")
    ap.add_argument("--max-rows", type=int, default=20)
    args = ap.parse_args()
    if args.allow_superuser:
        os.environ["READONLY_DB_ALLOW_SUPERUSER"] = "true"
    sys.path.insert(0, str(ROOT))
    from app import db  # noqa: E402

    sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.sql

    async def run():
        try:
            rows = await db.run_readonly(sql)
        finally:
            await db.close_pool()
        print(f"{len(rows)} row(s)")
        for r in rows[: args.max_rows]:
            print(json.dumps(r, default=str))

    try:
        asyncio.run(run())
    except Exception as e:  # noqa: BLE001
        print(f"ERROR {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
