"""uat/probe.py "<question>" ["<question>" ...] — ask through the runner's read-only driver, print answer + SQL."""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_matrix as R  # noqa: E402


async def main():
    drv = R.Driver()
    await drv.start()
    for q in sys.argv[1:]:
        rec, raw, turns = await R.one_turn(drv, drv.new_session(), q, ["village", "block", "district", "constituency"])
        print("Q:", q)
        print("  " + "\n  ".join(turns)[:1500])
        print("  SQL:", ((raw or {}).get("sql_query") or "")[:400].replace("\n", " "))


asyncio.run(main())
