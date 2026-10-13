"""Re-run the General cases that failed on 2026-10-09 (TC-001, 005, 006, 007,
010, 011, 012, 015, 022) through the live LangGraph pipeline after the fixes.
Writes rerun_results.json; run from the repo root. REINGEST=1 rebuilds the KB."""
import asyncio
import json
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Conv  # noqa: E402
from app import main as app_main  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rerun_results.json")
SCHEMES = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"]
SEM = asyncio.Semaphore(3)
RESULTS: dict = {}


async def conv(tc, label, qs):
    async with SEM:
        c = Conv()
        for q in qs:
            await c.ask(q)
        RESULTS.setdefault(tc, []).append({"label": label, "turns": c.turns})
        print(f"done {tc} {label}", flush=True)


async def main():
    async with app_main.lifespan(app_main.app):
        if os.environ.get("REINGEST") == "1":
            from app import kb_ingest
            print("reingest:", await kb_ingest.ingest_kb(force=True), flush=True)
        only = set(sys.argv[1:])
        T = []

        def add(tc, label, qs):
            if not only or tc in only:
                T.append(conv(tc, label, qs))

        add("TC-001", "schemes available", ["What schemes are available?"])
        add("TC-001", "Meghalaya schemes (TC-016)", ["What schemes can I get in Meghalaya?"])
        add("TC-001", "help my family (TC-008)", ["Is there any government scheme that can help my family?"])
        for s in SCHEMES:
            add("TC-005", s, [f"What is {s}?", "How can I apply?"])
            add("TC-006", s, [f"What is {s}?", "What documents are required?"])
        for a, b in [("Focus Plus", "Focus Legacy"), ("CM Elevate", "CM Elevate Legacy"), ("MGNREGA", "PMAY-G")]:
            add("TC-007", f"{a} vs {b}", [f"What is {a}?", f"What is {b}?",
                                          "What is the difference between the two schemes?"])
        add("TC-010", "PMAY-G 4 turns", ["What is PMAY-G?", "Who is eligible?",
                                         "What documents are required?", "How much assistance is given?"])
        add("TC-010", "MGNREGA 4 turns", ["What is MGNREGA?", "Who can apply?",
                                          "How many days of work are guaranteed?", "How are wages paid?"])
        add("TC-011", "how do I get this", ["How do I get this?"])
        add("TC-011", "how do I apply for it", ["How do I apply for it?"])
        add("TC-012", "PM-KISAN", ["What is PM-KISAN?"])
        add("TC-012", "Jal Jeevan", ["Tell me about the Jal Jeevan Mission scheme"])
        add("TC-012", "PM Kisan data", ["How many PM Kisan beneficiaries are there in East Khasi Hills?"])
        add("TC-015", "CM Elevate helpline", ["What is the helpline number for CM Elevate?"])
        add("TC-015", "PMAY-G instalment", ["When will the next PMAY-G installment be released?"])
        add("TC-015", "MGNREGA nodal officer", ["Who is the MGNREGA nodal officer in Ri Bhoi?"])
        add("TC-022", "pause answered, then follow-ups",
            ["What is the total MGNREGA expenditure for the village ABAGRE?", "All financial years combined",
             "Show it year-wise", "What was it in 2023-24?", "Which year was the highest?"])
        add("TC-022", "pause skipped with year-wise",
            ["What is the total MGNREGA expenditure for the village ABAGRE?", "Show it year-wise",
             "Which year was the highest?"])
        add("TC-022", "all years named",
            ["What is the total MGNREGA expenditure for the village ABAGRE across all years?",
             "Show it year-wise", "Which year was the highest?", "And the lowest?"])
        await asyncio.gather(*T)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=1, default=str)
    print("written", OUT)


asyncio.run(main())
