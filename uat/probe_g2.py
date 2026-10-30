"""uat/probe_g2.py — print each guardrail-stage call during one live turn (read-only)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_matrix as R  # noqa: E402


async def main():
    drv = R.Driver(); await drv.start()
    from app import pipeline as p
    orig = p._guardrail_check

    async def spy(raw, q, *a, **k):
        out = await orig(raw, q, *a, **k)
        print("GUARD raw=%r q=%r -> %s" % (raw, q, (out or [None])[0] and out[0].get("type")))
        return out
    p._guardrail_check = spy
    orig_e = p._turn_edge_stage

    async def spy_e(t, *a, **k):
        print("EDGE STAGE", t.get("question"))
        return await orig_e(t, *a, **k)
    p._turn_edge_stage = spy_e
    rec, raw = await drv.ask(drv.new_session(), sys.argv[1])
    print(rec["route"], rec["answer"][:120])
asyncio.run(main())
