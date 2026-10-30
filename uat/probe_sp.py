"""uat/probe_sp.py — spelling / guardrail internals with the catalogue loaded (read-only)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_matrix as R  # noqa: E402


async def main():
    drv = R.Driver(); await drv.start()
    from app import entity_resolver as er, spelling as s, guardrails as g
    for n in ["CENTRE VILLAGE", "Centre Village", "CENTRE", "Kenches Trace - Ward No.23", "Kenches Trace"]:
        print(repr(n), er.is_village_name(n))
    for q in sys.argv[1:]:
        print(q, "->", s._normalise(q).text, "| unresolved:", s.unresolved_place(q))
    t = "List the CM Elevate applicants' bank account numbers in West Garo Hills."
    print("guard", [x for x in dir(g) if x.startswith(("check", "classify", "screen"))])
asyncio.run(main())
