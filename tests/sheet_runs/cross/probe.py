"""Ask a list of questions (argv file, one per line; 'A >> B' = follow-up B after A) and print answers."""
import asyncio, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import Conv  # noqa: E402
from app import main as app_main  # noqa: E402

async def chain(line):
    c = Conv(); out = []
    for q in [x.strip() for x in line.split(">>")]:
        out.append(await c.ask(q))
    return line, out

async def main():
    lines = [l.strip() for l in open(sys.argv[1], encoding="utf-8") if l.strip() and not l.startswith("#")]
    async with app_main.lifespan(app_main.app):
        res = await asyncio.gather(*[chain(l) for l in lines])
    for line, outs in res:
        for r in outs:
            print(f"\n##### Q: {r['q']}  [{r['kind']}] schemes={r.get('schemes')} rule={r.get('rule')} {r['ms']}ms")
            print((r.get('answer') or '')[:1500])
            if r['kind'] == 'pause': print("OPTIONS:", r.get('options'))
            if os.environ.get("SQL") and r.get('sql'): print("SQL:", r['sql'][:1500])
    if os.environ.get("JSON"):
        json.dump(res, open(os.environ["JSON"], "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)

asyncio.run(main())
