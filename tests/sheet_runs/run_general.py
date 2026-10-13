"""General sheet (TC-001..TC-024): every case through the live LangGraph
pipeline; data cases checked against megh_db, across districts, blocks and
villages. Writes general_results.json."""
import asyncio
import json
import os
import sys

sys.path.insert(0, ".")
from harness import Conv, fetch, has_value  # noqa: E402
from app import main as app_main  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.environ.get("GEN_OUT", "general_results.json"))
SCHEMES = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"]
RESULTS = {}
SEM = asyncio.Semaphore(3)


def log(*a):
    print(*a, flush=True)


async def conv(tc, label, questions):
    async with SEM:
        c = Conv()
        for q in questions:
            await c.ask(q)
        RESULTS.setdefault(tc, []).append({"label": label, "turns": c.turns})
        last = c.turns[-1]
        log(f"{tc} | {label} | {last['kind']} | {(last.get('answer') or '')[:110]!r}")
        return c.turns


async def data_case(tc, label, question, expected, level=None, name=None):
    """One data question; `expected` is the DB figure (lakh for expenditure)."""
    async with SEM:
        c = Conv()
        rec = await c.ask(question)
        ok = rec["kind"] == "answer" and has_value(rec, expected)
        ents = rec.get("entities") or {}
        level_ok = None
        if level and rec["kind"] == "answer":
            level_ok = {"district": bool(ents.get("district")) and not ents.get("block") and not ents.get("village_code"),
                        "block": bool(ents.get("block")) and not ents.get("village_code"),
                        "village": bool(ents.get("village_code"))}[level]
        RESULTS.setdefault(tc, []).append({"label": label, "turns": c.turns, "expected": expected,
                                           "value_ok": ok, "level": level, "level_ok": level_ok, "name": name})
        log(f"{tc} | {label} | {'OK ' if ok else 'BAD'} exp={expected} | {(rec.get('answer') or '')[:90]!r}")


async def mg_exp(where, params, year=2023):
    r = await fetch(f"SELECT COALESCE(SUM(total_exp),0) AS v FROM curated.v_expenditure WHERE {where}"
                    + (" AND year_key = $%d" % (len(params) + 1) if year is not None else ""),
                    params + ([year] if year is not None else []))
    return float(r[0]["v"])


async def mg_emp(col, where, params, year=2023):
    r = await fetch(f"SELECT COALESCE(SUM({col}),0) AS v FROM curated.v_employment WHERE {where} AND year_key = ${len(params) + 1}",
                    params + [year])
    return float(r[0]["v"])


async def main():
    async with app_main.lifespan(app_main.app):
        tasks = []
        # ── Knowledge / conversation cases ──────────────────────────────────
        tasks.append(conv("TC-001", "schemes available", ["What schemes are available?"]))
        for s in SCHEMES:
            tasks.append(conv("TC-002", s, [f"What is {s}?", "Tell me about this scheme."]))
            tasks.append(conv("TC-003", s, [f"What is {s}?", "Who is eligible for this scheme?"]))
            tasks.append(conv("TC-004", s, [f"What is {s}?", "What benefits will I get under this scheme?"]))
            tasks.append(conv("TC-005", s, [f"What is {s}?", "How can I apply?"]))
            tasks.append(conv("TC-006", s, [f"What is {s}?", "What documents are required?"]))
            tasks.append(conv("TC-009", s, [f"What is {s}?", "Who can get it?"]))
            tasks.append(conv("TC-019", s, [f"What is {s}?", "Eligibility?", "Documents?"]))
        tasks.append(conv("TC-003", "no context", ["Who is eligible for this scheme?"]))
        for a, b in [("Focus Plus", "Focus Legacy"), ("CM Elevate", "CM Elevate Legacy"), ("MGNREGA", "PMAY-G")]:
            tasks.append(conv("TC-007", f"{a} vs {b}", [f"What is {a}?", f"What is {b}?",
                                                        "What is the difference between the two schemes?"]))
        tasks.append(conv("TC-008", "help my family", ["Is there any government scheme that can help my family?"]))
        tasks.append(conv("TC-010", "PMAY-G 4 turns", ["What is PMAY-G?", "Who is eligible?", "What documents are required?",
                                                       "How much assistance is given?"]))
        tasks.append(conv("TC-010", "MGNREGA 4 turns", ["What is MGNREGA?", "Who can apply?", "How many days of work are guaranteed?",
                                                        "How are wages paid?"]))
        tasks.append(conv("TC-011", "how do I get this", ["How do I get this?"]))
        tasks.append(conv("TC-011", "how do I apply for it", ["How do I apply for it?"]))
        for q in ["What is PM-KISAN?", "Tell me about the Jal Jeevan Mission scheme",
                  "How many PM Kisan beneficiaries are there in East Khasi Hills?"]:
            tasks.append(conv("TC-012", q, [q]))
        for q in ["What is the weather in Shillong today?", "Who won the last IPL final?"]:
            tasks.append(conv("TC-013", q, [q]))
        for q in ["What should I invest my money in?", "Should I buy gold or shares this year?"]:
            tasks.append(conv("TC-014", q, [q]))
        for q in ["What is the helpline number for CM Elevate?", "When will the next PMAY-G installment be released?",
                  "Who is the MGNREGA nodal officer in Ri Bhoi?"]:
            tasks.append(conv("TC-015", q, [q]))
        tasks.append(conv("TC-016", "Meghalaya schemes", ["What schemes can I get in Meghalaya?"]))
        tasks.append(conv("TC-018", "Am I eligible", ["Am I eligible for PMAY-G?"]))
        tasks.append(conv("TC-018", "Can I apply", ["Can I apply for PMAY-G?"]))
        tasks.append(conv("TC-018", "Am I eligible (MGNREGA)", ["Am I eligible for MGNREGA?"]))
        tasks.append(conv("TC-018", "Can I apply (MGNREGA)", ["Can I apply for MGNREGA?"]))

        # ── TC-017 misspellings (data answers checked against the DB) ───────
        ekh_pd = await mg_emp("person_days", "lgd_district = $1", ["EAST KHASI HILLS"])
        tasks.append(data_case("TC-017", "manrega persondays east khasi hils 2023-24",
                               "how many manrega persondays in east khasi hils in 2023-24", ekh_pd))
        rb_houses = float((await fetch("SELECT COUNT(*) AS v FROM curated.v_pmay WHERE NOT is_placeholder "
                                       "AND lgd_district = 'RI BHOI' AND year_key = 2022"))[0]["v"])
        tasks.append(data_case("TC-017", "pmay housess sanctiond ri bhoi 2022-23",
                               "pmay housess sanctiond in ri bhoi in 2022-23", rb_houses))
        # user decision 2026-10-12: a bare "CM Elevate applications" count is read as CM Elevate Legacy
        ekh_cme = float((await fetch("SELECT COUNT(*) AS v FROM curated.v_cm_elevate_disbursement "
                                     "WHERE lgd_district = 'EAST KHASI HILLS'"))[0]["v"])
        tasks.append(data_case("TC-017", "cm elevat aplications east khasi hils",
                               "how many cm elevat aplications in east khasi hils", ekh_cme))
        tasks.append(conv("TC-017", "eligibilty for pmay-g", ["who is eligble for pmay-g"]))

        # ── TC-020 ADUGRE in South West Garo Hills, any capitalisation ──────
        adu = await mg_exp("village_code = $1", [273807])
        for variant in ["What was the total expenditure in ADUGRE in South West Garo Hills during 2023-2024 for MGNREGA",
                        "What was the total expenditure in Adugre in South West Garo Hills during 2023-2024 for MGNREGA",
                        "what was the total expenditure in adugre in SOUTH WEST GARO HILLS during 2023-2024 for mgnrega"]:
            tasks.append(data_case("TC-020", variant[34:60], variant, adu, "village", "ADUGRE/SWGH"))
        tasks.append(conv("TC-020", "ADUGRE without district (3 villages)",
                          ["What was the total MGNREGA expenditure in ADUGRE during 2023-2024?"]))

        # ── TC-021 scheme context retention (MGNREGA) ───────────────────────
        tasks.append(conv("TC-021", "MGNREGA then no scheme name",
                          ["Total MGNREGA person-days in East Khasi Hills in 2023-24",
                           "How many households were employed there?",
                           "What about West Garo Hills?",
                           "And the total expenditure?"]))

        # ── TC-022 ABAGRE follow-ups ────────────────────────────────────────
        tasks.append(conv("TC-022", "ABAGRE total then follow-ups",
                          ["What is the total MGNREGA expenditure for the village ABAGRE?",
                           "Show it year-wise", "What was it in 2023-24?"]))

        # ── TC-024 employment questions infer MGNREGA ───────────────────────
        tasks.append(conv("TC-024", "after MGNREGA, employment question",
                          ["Total MGNREGA person-days in Ri Bhoi in 2023-24",
                           "How many people got employment in West Garo Hills in 2024-25?"]))
        tasks.append(conv("TC-024", "fresh employment question",
                          ["How many households got employment in East Garo Hills in 2023-24?"]))
        tasks.append(conv("TC-024", "fresh job cards question", ["How many job cards were issued in Ri Bhoi in 2024-25?"]))

        # ── TC-023 hierarchy: every district, every block, villages, both cases ─
        districts = [r["d"] for r in await fetch(
            "SELECT DISTINCT lgd_district AS d FROM curated.v_expenditure WHERE year_key=2023 ORDER BY 1")]
        for d in districts:
            exp = await mg_exp("lgd_district = $1", [d])
            for name in (d, d.title()):
                tasks.append(data_case("TC-023", f"district {name}",
                                       f"What was the total MGNREGA expenditure in {name} in 2023-24?", exp, "district", d))
        blocks = [r["b"] for r in await fetch(
            "SELECT DISTINCT lgd_block AS b FROM curated.v_expenditure WHERE year_key=2023 AND lgd_block IS NOT NULL ORDER BY 1")]
        for b in blocks:
            exp = await mg_exp("lgd_block = $1", [b])
            for name in (b, b.title()):
                tasks.append(data_case("TC-023", f"block {name}",
                                       f"What was the total MGNREGA expenditure in {name} block in 2023-24?", exp, "block", b))
        villages = await fetch("""
            WITH u AS (SELECT lgd_village_name FROM curated.v_expenditure WHERE year_key=2023
                       GROUP BY lgd_village_name HAVING COUNT(DISTINCT village_code)=1),
                 v AS (SELECT e.lgd_district, e.lgd_village_name, e.village_code, SUM(e.total_exp) AS t,
                              ROW_NUMBER() OVER (PARTITION BY e.lgd_district ORDER BY e.lgd_village_name) AS rn
                       FROM curated.v_expenditure e JOIN u USING (lgd_village_name)
                       WHERE e.year_key=2023 AND e.lgd_village_name ~ '^[A-Z]+$' AND LENGTH(e.lgd_village_name) >= 6
                       GROUP BY 1,2,3 HAVING SUM(e.total_exp) > 0)
            SELECT * FROM v WHERE rn <= 2 ORDER BY 1, 2""")
        for v in villages:
            for name in (v["lgd_village_name"], v["lgd_village_name"].title()):
                tasks.append(data_case("TC-023", f"village {name} ({v['lgd_district']})",
                                       f"What was the total MGNREGA expenditure in {name} village in 2023-24?",
                                       float(v["t"]), "village", v["lgd_village_name"]))

        log(f"running {len(tasks)} conversations")
        await asyncio.gather(*tasks)

        # DB references for the follow-up cases, for the report
        RESULTS["_db"] = {
            "TC-021": {"ekh_pd": await mg_emp("person_days", "lgd_district = $1", ["EAST KHASI HILLS"]),
                       "ekh_hh": await mg_emp("households_employed", "lgd_district = $1", ["EAST KHASI HILLS"]),
                       "wgh_hh": await mg_emp("households_employed", "lgd_district = $1", ["WEST GARO HILLS"]),
                       "wgh_pd": await mg_emp("person_days", "lgd_district = $1", ["WEST GARO HILLS"]),
                       "wgh_exp": await mg_exp("lgd_district = $1", ["WEST GARO HILLS"]),
                       "ekh_exp": await mg_exp("lgd_district = $1", ["EAST KHASI HILLS"])},
            "TC-022": {"abagre_all": await mg_exp("village_code = $1", [273035], None),
                       "abagre_by_year": await fetch("SELECT year_key, SUM(total_exp) AS t FROM curated.v_expenditure "
                                                     "WHERE village_code=273035 GROUP BY 1 ORDER BY 1")},
            "TC-024": {"rb_pd": await mg_emp("person_days", "lgd_district = $1", ["RI BHOI"]),
                       "wgh_persons_2024": await mg_emp("persons_employed", "lgd_district = $1", ["WEST GARO HILLS"], 2024),
                       "wgh_hh_2024": await mg_emp("households_employed", "lgd_district = $1", ["WEST GARO HILLS"], 2024),
                       "egh_hh_2023": await mg_emp("households_employed", "lgd_district = $1", ["EAST GARO HILLS"]),
                       "rb_jobcards_2024": await mg_emp("job_cards_issued_total", "lgd_district = $1", ["RI BHOI"], 2024)},
            "TC-020": {"adugre_swgh_2023": adu},
        }
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(RESULTS, f, indent=1, default=str, ensure_ascii=False)
        log("written", OUT)


asyncio.run(main())
