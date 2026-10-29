"""B3 (RAG plan) — can retrieval scores tell a data question from a knowledge one?
Live measurement tool (VPN: gateway, megh_db, Qdrant). NOT a pytest suite.

For each labelled question: today's classify_intent (cues + 4B model), the top
megh_knowledge score (knowledge passages) and the top megh_sql_metadata `example`
score (worked data questions), both cosine on the same qwen3 embedding.

    .venv/Scripts/python.exe -X utf8 tests/intent_scores/run_eval.py tests/intent_scores/labels.json
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
logging.disable(logging.CRITICAL)

from qdrant_client import models  # noqa: E402

from app import db, llm, pipeline as p, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402


async def _top_example(vec):
    flt = models.Filter(must=[models.FieldCondition(key="kind", match=models.MatchValue(value="example"))])
    r = await vectorstore.get_client().query_points(collection_name=settings.SQL_EXAMPLES_COLLECTION, query=vec,
                                                    query_filter=flt, limit=1, with_payload=False)
    return r.points[0].score if r.points else 0.0


async def main(path: str) -> int:
    await db.init_pool(); await llm.init_client(); await vectorstore.init_qdrant()
    rows = json.load(open(path, encoding="utf-8"))
    vecs = await llm.call_embedding([q for _l, q in rows])
    out = []
    for (label, q), v in zip(rows, vecs):
        kb = await vectorstore.search(v, 1)
        kb_s = kb[0]["score"] if kb else 0.0
        ex_s = await _top_example(v)
        try:
            now = await p.classify_intent(q)
        except Exception as e:  # noqa: BLE001
            now = f"ERR {type(e).__name__}"
        out.append({"label": label, "q": q, "now": now, "kb": round(kb_s, 3), "ex": round(ex_s, 3),
                    "diff": round(ex_s - kb_s, 3)})
        print(f"{label:9} now={now:9} {'ok ' if now == label else 'BAD'} kb={kb_s:.3f} ex={ex_s:.3f} "
              f"ex-kb={ex_s - kb_s:+.3f}  {q}")
    wrong = [r for r in out if r["now"] != r["label"]]
    print(f"\ntoday's classify_intent: {len(out) - len(wrong)}/{len(out)} right")
    for name, key in (("ex-kb", "diff"),):
        best = None
        for t in sorted({r[key] for r in out}):
            acc = sum((r[key] >= t) == (r["label"] == "DATA") for r in out)
            if best is None or acc > best[1]:
                best = (t, acc)
        print(f"score rule '{name} >= t -> DATA': best t={best[0]:+.3f} gives {best[1]}/{len(out)}")
    await vectorstore.close_qdrant(); await llm.close_client(); await db.close_pool()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1])))
