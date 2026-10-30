"""uat/probe_ac.py — which constituencies resolve for CM Elevate (read-only)."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
import run_matrix as R  # noqa: E402
import live_cme_uat as U  # noqa: E402


async def main():
    drv = R.Driver(); await drv.start()
    from app import entity_resolver as er
    acs = [r[0] for r in U.DB().rows("SELECT DISTINCT ac_name FROM curated.v_cm_elevate WHERE ac_name IS NOT NULL ORDER BY 1")]
    print("acs", len(acs))
    bad = []
    for a in acs:
        r = er.resolve_dimension(f"{a} constituency", "CM Elevate", "assembly_constituency")
        if r.status != "resolved":
            bad.append((a, r))
    print("unresolved:", len(bad))
    for a, r in bad:
        print("  ", a, "->", r)
asyncio.run(main())


async def more():
    drv = R.Driver(); await drv.start()
    from app import entity_resolver as er
    cat = er._catalog.get("CM Elevate", {}).get("assembly_constituency") or []
    print("catalog ACs:", len(cat), [x for x in cat if "SHILL" in str(x).upper()])
    print(er.resolve_dimension("East Shillong", "CM Elevate", "assembly_constituency"))
asyncio.run(more())
