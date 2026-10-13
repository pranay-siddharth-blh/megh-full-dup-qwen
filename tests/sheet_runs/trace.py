"""Run one conversation live and print each turn plus the pipeline's INFO log.
Usage: trace.py "q1" "q2" ...   (run from the repo root)"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Conv  # noqa: E402
from app import main as app_main  # noqa: E402

VERBOSE = os.environ.get("TRACE_LOG") == "1"


async def main():
    async with app_main.lifespan(app_main.app):
        if os.environ.get("REINGEST") == "1":
            from app import kb_ingest
            print("reingest:", await kb_ingest.ingest_kb(force=True))
        if VERBOSE:
            h = logging.StreamHandler(sys.stdout)
            h.setFormatter(logging.Formatter("      log| %(name)s: %(message)s"))
            for n in ("app.pipeline", "app.pipeline_graph", "app.rag"):
                lg = logging.getLogger(n)
                lg.setLevel(logging.INFO)
                lg.addHandler(h)
        c = Conv()
        for q in sys.argv[1:]:
            print(f"\nQ: {q}", flush=True)
            r = await c.ask(q)
            print(f"   [{r['kind']} {r.get('rule') or r.get('route') or ''} schemes={r.get('schemes')}] "
                  f"{(r.get('answer') or '')[:900]}")
            if r.get("rows"):
                print("   rows:", str(r["rows"])[:300])


asyncio.run(main())
