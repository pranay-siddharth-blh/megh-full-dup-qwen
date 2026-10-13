"""Re-ask General TC-017's CM Elevate case answering the bot's year question, and store it in final_general.json."""
import asyncio, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Conv, fetch, has_value
from app import main as app_main
P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "final_general.json")

async def main():
    async with app_main.lifespan(app_main.app):
        exp = float((await fetch("SELECT COUNT(*) AS v FROM curated.v_cm_elevate_disbursement "
                                 "WHERE lgd_district = 'EAST KHASI HILLS'"))[0]["v"])
        c = Conv()
        rec = await c.ask("how many cm elevat aplications in east khasi hils")
        if rec["kind"] == "pause" and rec.get("rule") == "year-not-specified":
            pick = next(q for l, q in zip(rec.get("options") or [], rec.get("option_qs") or []) if l.lower().startswith("all"))
            rec = await c.ask(pick)
        ok = rec["kind"] == "answer" and has_value(rec, exp)
        R = json.load(open(P, encoding="utf-8"))
        R["TC-017"] = [x for x in R["TC-017"] if x["label"] != "cm elevat aplications east khasi hils"] + [
            {"label": "cm elevat aplications east khasi hils", "turns": c.turns, "expected": exp, "value_ok": ok,
             "level": None, "level_ok": None, "name": None}]
        json.dump(R, open(P, "w", encoding="utf-8"), indent=1, default=str, ensure_ascii=False)
        print("TC-017 cm case:", ok, exp, (rec.get("answer") or "")[:120])

asyncio.run(main())
