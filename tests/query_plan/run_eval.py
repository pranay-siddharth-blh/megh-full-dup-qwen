"""E1 stage 1 — build the query plan for a set of questions and compare it with what
the pipeline decided, field by field. Live (VPN: gateway, megh_db, Qdrant).
NOT a pytest suite. Questions that pause for a clarification are skipped.

    .venv/Scripts/python.exe -X utf8 tests/query_plan/run_eval.py tests/query_plan/questions.json [--out FILE]
"""
import argparse
import asyncio
import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
logging.disable(logging.CRITICAL)

from app import main as app_main, pipeline as p, query_plan  # noqa: E402
from app.config import settings  # noqa: E402
from app.session_store import Session  # noqa: E402


async def main(args) -> int:
    settings.QUERY_PLAN_SHADOW = True
    qs = json.load(open(args.questions, encoding="utf-8"))
    recs = []
    async with app_main.lifespan(app_main.app):
        for q in qs:
            s = Session(session_id=f"qp-{time.time_ns()}", user_id="qp-eval", created=time.time(), last_seen=time.time())
            settings.QUERY_PLAN_SHADOW = False          # no background copy inside the turn
            try:
                res = await p.answer_question(q, session=s, scope=None)
            except Exception as e:  # noqa: BLE001 — a pause or an error: nothing to compare
                print(f"skip ({type(e).__name__}) {q}")
                continue
            finally:
                settings.QUERY_PLAN_SHADOW = True
            rec = await query_plan.shadow(res.get("rewritten_question") or q, q, res)
            if rec is None:
                print(f"no plan {q}")
                continue
            recs.append(rec)
            bad = [k for k, v in rec["agree"].items() if not v]
            print(f"{'ok ' if not bad else 'DIFF'} {q[:70]:70} {', '.join(bad)}")
            for k in bad:
                print(f"       {k}: plan={rec['plan'].get(k if k != 'top_n' else 'top_n')!r} "
                      f"actual={rec['actual'].get(k if k != 'top_n' else 'limit')!r}")
    tot, ok = Counter(), Counter()
    for r in recs:
        for k, v in r["agree"].items():
            tot[k] += 1
            ok[k] += bool(v)
    print("\nper-field agreement (plan vs pipeline):")
    for k in tot:
        print(f"  {k:12} {ok[k]}/{tot[k]}")
    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in recs),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("questions")
    ap.add_argument("--out")
    sys.exit(asyncio.run(main(ap.parse_args())))
