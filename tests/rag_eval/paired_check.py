"""
Paired test of the sentence check (RAG upgrade Phase 5, 2026-10-15).

The composer's answers vary between runs even at temperature 0 (only 71 of
188 were identical across two runs of the same settings), so comparing a run
with the check against a run without it mixes the check's effect with that
variation. Here the SAME answers are judged before and after the check: take a
finished run's answers, re-retrieve their passages, apply rag.ground_answer,
and judge both versions with the same judge.

    python tests/rag_eval/paired_check.py --from p5_D0_rerank8
"""
import argparse
import asyncio
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:]]
ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="src", required=True, help="label of a finished run_eval run (no check)")
ap.add_argument("--concurrency", type=int, default=3)
args = ap.parse_args()
sys.argv = [sys.argv[0]]
sys.path.insert(0, str(ROOT))

from app import llm, rag, vectorstore  # noqa: E402
from tests.rag_eval import run_eval as E  # noqa: E402


async def one(r: dict, sem: asyncio.Semaphore) -> dict | None:
    if not r["answer"] or r["kind"] == "negative":
        return None
    async with sem:
        chunks = await rag.retrieve(r["question"], scheme=r["scheme"])
        passages = [c.get("text", "") for c in chunks]
        after = await rag.ground_answer(r["answer"], passages)
        out = {"id": r["id"], "before": r["answer"], "after": after, "changed": after != r["answer"]}
        for tag, ans in (("before", r["answer"]), ("after", after)):
            bad, n = await E.judge_support(ans, passages)
            bad = E.echo_filter(r["question"], bad)
            v = await E.judge_answer(r["question"], r["expected_answer"], ans)
            out[tag + "_bad"], out[tag + "_units"], out[tag + "_verdict"] = len(bad), n, v.get("verdict", "wrong")
        return out


async def main():
    src = sorted(glob.glob(str(ROOT / f"tests/rag_eval/results/*_{args.src}.json")))[-1]
    rows = json.loads(Path(src).read_text(encoding="utf-8"))["rows"]
    await llm.init_client()
    await vectorstore.init_qdrant()
    try:
        sem = asyncio.Semaphore(args.concurrency)
        res = [x for x in await asyncio.gather(*(one(r, sem) for r in rows)) if x]
    finally:
        await vectorstore.close_qdrant()
        await llm.close_client()
    n = len(res)
    pc = lambda k: round(100 * k / n, 1)  # noqa: E731
    for tag in ("before", "after"):
        made = sum(1 for x in res if x[tag + "_bad"])
        sent = sum(x[tag + "_bad"] for x in res) / max(1, sum(x[tag + "_units"] for x in res))
        ok = sum(1 for x in res if x[tag + "_verdict"] == "correct")
        print(f"{tag:6}  answers with a made-up sentence {pc(made):5}%   made-up sentences {round(100 * sent, 1):4}%"
              f"   correct {pc(ok):5}%   ({n} answers)")
    print("answers the check changed:", sum(1 for x in res if x["changed"]))
    lost = [x for x in res if x["before_verdict"] == "correct" and x["after_verdict"] != "correct"]
    print("correct before, not after:", len(lost), [x["id"] for x in lost])
    out = ROOT / "tests/rag_eval/results" / f"paired_check_{args.src}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("details:", out)


asyncio.run(main())
