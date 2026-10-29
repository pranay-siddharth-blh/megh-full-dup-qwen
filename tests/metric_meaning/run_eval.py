"""B1 (RAG plan) — can embeddings pick a catalogue measure for a wording the
literal matcher misses? Live measurement tool (VPN: megh_db + the embedding
gateway). NOT a pytest suite.

labels.json: [scheme, officer wording, expected metric_key or null]. null rows are
measures the catalogue does NOT hold ("administrative expenditure", "wage rate",
"women workers"): a safe matcher must leave them unmatched.

Measured 2026-10-27 (qwen3-embedding, 1024-dim): the null rows score as high as
the true paraphrases (e.g. "administrative expenditure" -> total expenditure
0.873 / margin 0.119; "wage rate" -> wage share 0.902 / 0.154, while "funds
utilised" -> total expenditure is 0.745 / 0.018), so no cosine threshold
separates them. Re-run after the catalogue or the embedding model changes.

    .venv/Scripts/python.exe -X utf8 tests/metric_meaning/run_eval.py tests/metric_meaning/labels.json
"""
import asyncio, json, logging, sys, math
sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)
from app import db, schema_introspect as si, metric_catalog as mc, llm
def cos(a, b): return sum(x*y for x, y in zip(a, b)) / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(y*y for y in b)))
async def main():
    await db.init_pool(); await llm.init_client(); await si.load(); await mc.load()
    labels = json.load(open(sys.argv[1], encoding="utf-8"))
    for fmt in ("{s}: {p}", "{p}"):
        ph = [(m.scheme, m.key, " ".join(p)) for m in mc.metrics().values() for p in m.phrases] + \
             [(m.scheme, m.key, m.display_name) for m in mc.metrics().values()]
        pv = await llm.call_embedding([fmt.format(s=s, p=p) for s, _k, p in ph])
        qv = await llm.call_embedding([fmt.format(s=s, p=w) for s, w, _e in labels])
        print("== format", fmt)
        for (s, w, exp), v in zip(labels, qv):
            best = {}
            for (ps, k, p), u in zip(ph, pv):
                if ps != s: continue
                c = cos(v, u)
                if c > best.get(k, (-1, ""))[0]: best[k] = (c, p)
            r = sorted(best.items(), key=lambda kv: -kv[1][0])
            (k1, (c1, p1)), (k2, (c2, _)) = r[0], r[1]
            ok = "OK " if k1 == exp else ("NEG" if exp is None else "BAD")
            print(f"  {ok} {c1:.3f} margin {c1-c2:.3f}  {s:17} {w:32} -> {k1} ('{p1}')  expected {exp}")
    await llm.close_client(); await db.close_pool()
asyncio.run(main())
