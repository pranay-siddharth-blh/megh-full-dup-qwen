"""uat/probe_chain.py "<q1>" "<q2>" ... — one chat, every turn printed (read-only driver)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_matrix as R  # noqa: E402


async def main():
    drv = R.Driver(); await drv.start()
    s = drv.new_session()
    for q in sys.argv[1:]:
        rec, raw, turns = await R.one_turn(drv, s, q, ["constituency"])
        print("Q:", q, "| rewritten:", (raw or {}).get("rewritten_question"))
        print("  " + "\n  ".join(turns)[:600])
asyncio.run(main())
