"""uat/probe_g.py — guardrail stage on one question with the catalogue loaded (read-only)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_matrix as R  # noqa: E402


async def main():
    drv = R.Driver(); await drv.start()
    from app import pipeline as c
    from app import edge
    q = sys.argv[1]
    m = await c._mask_village_names(q)
    print("masked:", m, "| harm:", edge.detect_harmful(m))
    print("check:", await c._guardrail_check(q, q, False))
asyncio.run(main())
