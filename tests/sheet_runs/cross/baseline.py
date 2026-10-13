"""Baseline: the 20 Cross Scheme sheet questions verbatim through the live pipeline."""
import asyncio, json, os, sys
sys.path.insert(0, "."); sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import Conv  # noqa: E402
from app import main as app_main  # noqa: E402

D, B = "East Khasi Hills", "Mylliem"
Q = {
 "CROSS-1": "What is the beneficiary count across MGNREGA, PMAY-G, Focus+, and FOCUS?",
 "CROSS-2": "Compare the number of beneficiaries in Focus+ and FOCUS.",
 "CROSS-3": "Compare the performance of Focus+ and CM-ELEVATE across districts based on beneficiary/application counts.",
 "CROSS-4": "How much total amount has been disbursed under Focus+, FOCUS, and CM-ELEVATE?",
 "CROSS-5": "Which scheme has a higher total financial disbursement: Focus+ or CM-ELEVATE?",
 "CROSS-6": "Compare the number of beneficiaries/applications in each district for Focus+, FOCUS, and CM-ELEVATE.",
 "CROSS-7": "Which scheme has the highest beneficiary or application count in each district?",
 "CROSS-8": f"Compare Focus+, FOCUS, and CM-ELEVATE performance in {D}.",
 "CROSS-9": f"Compare the coverage of MGNREGA, PMAY-G, and CM-ELEVATE in {B}.",
 "CROSS-10": "Compare the total expenditure or disbursement under MGNREGA, PMAY-G, Focus+, and CM-ELEVATE.",
 "CROSS-11": f"How much financial assistance or expenditure was recorded under each scheme in {D}?",
 "CROSS-12": "Which scheme provided the highest total financial assistance across Meghalaya?",
 "CROSS-13": "Which scheme has the widest coverage across districts of Meghalaya?",
 "CROSS-14": f"What is the performance of MGNREGA, PMAY-G, Focus+, and CM-ELEVATE in {D}?",
 "CROSS-15": "Which districts have the highest concentration of beneficiaries or applications across the schemes?",
 "CROSS-16": "Compare Focus+ and CM-ELEVATE beneficiary/application counts across West Garo Hills, Ri Bhoi, and East Khasi Hills.",
 "CROSS-17": "Give me a district-wise summary comparing MGNREGA, PMAY-G, Focus+, FOCUS, and CM-ELEVATE.",
 "CROSS-18": "For each district, identify which scheme has the highest beneficiary/application count.",
 "CROSS-19": "Compare the beneficiary/application count and total financial amount for Focus+, FOCUS, and CM-ELEVATE.",
 "CROSS-20": "Give me an overall performance comparison of MGNREGA, PMAY-G, Focus+, FOCUS, and CM-ELEVATE based on coverage and financial performance.",
}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("OUT", "baseline.json"))

async def one(k, q):
    c = Conv(); r = await c.ask(q); return k, r

async def main():
    async with app_main.lifespan(app_main.app):
        res = await asyncio.gather(*[one(k, q) for k, q in Q.items()])
    json.dump(dict(res), open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)

asyncio.run(main())
