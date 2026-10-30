"""uat/probe_sql.py "<q>" ... — like probe.py, printing every SQL attempt and the guard's complaint."""
import asyncio, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import run_matrix as R  # noqa: E402


async def main():
    drv = R.Driver(); await drv.start()
    from app import pipeline as p
    orig = p._execute_one_attempt

    async def spy(question, schemes, entity_result, sql):
        res = {k: v for k, v in (entity_result.get("resolved") or {}).items() if "village" in k or k in ("block", "district")}
        print("  ATTEMPT:", sql.replace("\n", " ")[:300], "| resolved:", res)
        try:
            return await orig(question, schemes, entity_result, sql)
        except Exception as e:
            print("  REJECT:", str(e)[:250]); raise
    p._execute_one_attempt = spy
    for q in sys.argv[1:]:
        rec, raw, turns = await R.one_turn(drv, drv.new_session(), q, ["village"])
        print("Q:", q); print("  " + " | ".join(turns)[:600])
asyncio.run(main())
