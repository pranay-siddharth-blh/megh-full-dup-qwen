"""
SQL generation driven by the QueryFrame (understand.sql_frame()):
app/sql/sql_templates.py, the REQUIRED FILTERS block in app/sql/prompt_builder.py,
generate_sql's template-first path and _verify_sql's deterministic frame check.

Covers: template SQL for each scheme's common value metric (bodies copied from
the SME few-shot files, only WHERE filled from resolved values); templates
declining every non-plain shape; generate_sql skipping the model for a
template and otherwise sending the frame's standalone question + REQUIRED
FILTERS (also in the repair prompt); the frame check catching wrong-scheme
tables / missing breakdown / wrong LIMIT BEFORE the model verifier is called;
no model frame (none, or a fallback frame) => generation exactly as before.
No DB, no gateway.
Run: `python tests/unit/test_sql_frame.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.clients import llm  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402
from app.sql import prompt_builder, schema_retrieval, sql_templates  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


scheme_registry.load_all()


def F(**kw):
    kw.setdefault("rewritten_question", "q")
    kw.setdefault("query_type", "value")
    return u.QueryFrame(**kw)


def ER(**resolved):
    return {"resolved": resolved, "notes": [], "display": {}}


print("\n=== templates: SME few-shot bodies, WHERE from resolved values ===")
cases = [
    ("MGNREGA expenditure, EKH, FY 2025-26", F(metric="total expenditure"), ["MGNREGA"],
     ER(district="EAST KHASI HILLS", year_key=2025),
     "mgnrega.expenditure",
     "SELECT ROUND(SUM(total_exp) / 100, 2) AS total_expenditure_crore FROM curated.v_expenditure "
     "WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2025;"),
    ("MGNREGA person-days statewide, all years", F(metric="person-days"), ["MGNREGA"], ER(),
     "mgnrega.person_days", "SELECT SUM(person_days) AS person_days FROM curated.v_employment;"),
    ("PMAY-G houses completed, WGH, FY 2020-21", F(metric="houses completed"), ["PMAY-G"],
     ER(district="WEST GARO HILLS", year_key=2020), "pmay.houses_completed",
     "SELECT COUNT(*) AS completed_houses FROM curated.v_pmay WHERE NOT is_placeholder AND is_completed "
     "AND lgd_district = 'WEST GARO HILLS' AND financial_year_short = '2020-21';"),
    ("PMAY-G amount released, block", F(metric="amount released"), ["PMAY-G"], ER(block="DALU"),
     "pmay.amount_released",
     "SELECT ROUND(SUM(amount_released) / 10000000.0, 2) AS amount_released_crore FROM curated.v_pmay "
     "WHERE NOT is_placeholder AND lgd_block = 'DALU';"),
    ("Focus Plus beneficiaries, tranche", F(metric="beneficiaries"), ["Focus Plus"],
     ER(tranche_label="Tranch 2 - August"), "focus.beneficiaries",
     "SELECT COUNT(DISTINCT (batch_label, source_sl_no)) AS beneficiaries, COUNT(*) AS payments "
     "FROM curated.v_focus_plus WHERE tranche_label = 'Tranch 2 - August';"),
    ("CM Elevate applications, Ri Bhoi", F(metric="applications"), ["CM Elevate"], ER(district="RI BHOI"),
     "cmelevate.applications",
     "SELECT COUNT(*) AS applications FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI';"),
    ("Garo Hills region (district_list from a region) is a plain IN filter", F(metric="expenditure"), ["MGNREGA"],
     ER(district_list=["EAST GARO HILLS", "WEST GARO HILLS"], district_list_region="Garo Hills"),
     "mgnrega.expenditure",
     "SELECT ROUND(SUM(total_exp) / 100, 2) AS total_expenditure_crore FROM curated.v_expenditure "
     "WHERE lgd_district IN ('EAST GARO HILLS', 'WEST GARO HILLS');"),
]
for name, frame, schemes, er, key, sql in cases:
    got = sql_templates.choose(frame, schemes, er)
    check(name, got == (key, sql), str(got))

print("\n=== templates decline everything that isn't a plain value ===")
declines = [
    ("a ranking", F(metric="expenditure", query_type="ranking", group_by="district"), ["MGNREGA"], ER()),
    ("a breakdown", F(metric="expenditure", group_by="block"), ["MGNREGA"], ER()),
    ("an average", F(metric="average person-days per household"), ["MGNREGA"], ER()),
    ("a share", F(metric="share of expenditure"), ["MGNREGA"], ER()),
    ("two schemes", F(metric="beneficiaries"), ["MGNREGA", "PMAY-G"], ER()),
    ("an unknown metric", F(metric="works completed"), ["MGNREGA"], ER()),
    ("a named district comparison", F(metric="houses completed"), ["PMAY-G"],
     ER(district_list=["EAST KHASI HILLS", "EAST GARO HILLS"])),
    ("a resolved entity it can't filter on", F(metric="houses"), ["PMAY-G"], ER(house_status=["Plinth"])),
    ("a year on CM Elevate (no time dimension)", F(metric="applications"), ["CM Elevate"], ER(year_key=2024)),
    ("a gender subset", F(metric="women applicants"), ["CM Elevate"], ER()),
    ("a subset worded outside the template ('new beneficiaries onboarded')",
     F(metric="new beneficiaries onboarded"), ["Focus Plus"], ER(tranche_label="Tranch 4 - Feb-March")),
    ("a different figure ('approval status')", F(metric="approval status"), ["Focus Plus"], ER()),
]
for name, frame, schemes, er in declines:
    check(f"declines {name}", sql_templates.choose(frame, schemes, er) is None)
check("declines when the gates defaulted a top-N",
      sql_templates.choose(F(metric="expenditure"), ["MGNREGA"], ER(), ["top_n:default:5"]) is None)

print("\n=== generate_sql in frame mode ===")
calls = {"sql_gen": [], "verify": 0}


async def _sql_model(prompt, guided=None):
    calls["sql_gen"].append(prompt)
    return "SELECT lgd_block, SUM(total_exp) FROM curated.v_expenditure GROUP BY lgd_block"


async def _verify_model(prompt, guided=None):
    calls["verify"] += 1
    return '{"ok": true}'


async def _no_retrieval(q, schemes):
    return []

orig = (llm.call_sql_generator, llm.call_sql_verifier, schema_retrieval.retrieve,
        pipeline.sql_examples_retrieval.retrieve if hasattr(pipeline, "sql_examples_retrieval") else None)
llm.call_sql_generator, llm.call_sql_verifier = _sql_model, _verify_model
schema_retrieval.retrieve = _no_retrieval
prompt_builder.sql_examples_retrieval.retrieve = _no_retrieval
flags_before = settings.SQL_VERIFY_ENABLED
settings.SQL_VERIFY_ENABLED = True
try:
    frame = F(rewritten_question="What is the total MGNREGA expenditure in East Khasi Hills?", schemes=["MGNREGA"],
              metric="total expenditure")
    token = u.current_frame.set(frame)
    er = ER(district="EAST KHASI HILLS", year_key=2025)
    er["gate_trace"] = ["year:default:2025"]
    sql = asyncio.run(pipeline.generate_sql("total mgnrega expendture ekh for FY 2025-26", ["MGNREGA"], er))
    check("templated question: SQL from the template", sql.startswith("SELECT ROUND(SUM(total_exp)") and
          "lgd_district = 'EAST KHASI HILLS' AND year_key = 2025" in sql, sql)
    check("... with NO SQL-model call", calls["sql_gen"] == [])
    check("... recorded in the gate trace", "sql:template:mgnrega.expenditure" in er["gate_trace"])
    u.current_frame.reset(token)

    frame = F(rewritten_question="What is the MGNREGA expenditure in East Khasi Hills, block wise?",
              schemes=["MGNREGA"], metric="expenditure", query_type="distribution", group_by="block")
    token = u.current_frame.set(frame)
    er = ER(district="EAST KHASI HILLS", year_key=2025)
    er["gate_trace"] = ["year:default:2025"]
    sql = asyncio.run(pipeline.generate_sql("and block wise?", ["MGNREGA"], er))
    prompt = calls["sql_gen"][-1] if calls["sql_gen"] else ""
    check("non-template question: the model is called", len(calls["sql_gen"]) == 1)
    check("... with the question as asked PLUS the frame's reading as 'understood as'",
          'Question: "and block wise?"' in prompt
          and "understood as: What is the MGNREGA expenditure in East Khasi Hills, block wise?" in prompt)
    check("... and a REQUIRED FILTERS block (scheme, geography, year, group_by, query_type)",
          "REQUIRED FILTERS" in prompt and "lgd_district = 'EAST KHASI HILLS'" in prompt
          and "year_key = 2025" in prompt and "GROUP BY lgd_block" in prompt
          and "query_type (guidance): distribution" in prompt, prompt[prompt.find("REQUIRED"):][:600])
    check("... recorded as sql:llm", "sql:llm" in er["gate_trace"])
    rp = prompt_builder.build_repair_prompt("x", ["MGNREGA"], er, failed_sql="SELECT 1", error="e")
    check("repair prompt carries the same REQUIRED FILTERS (with 'understood as')",
          "REQUIRED FILTERS" in rp and "understood as:" in rp and "block wise" in rp)

    print("\n=== _verify_sql: deterministic frame check before the model ===")
    n_verify = calls["verify"]
    issue = asyncio.run(pipeline._verify_sql(
        "q", ["MGNREGA"], er, "SELECT SUM(total_exp) FROM curated.v_expenditure "
                               "WHERE lgd_district = 'EAST KHASI HILLS' AND year_key = 2025"))
    check("missing GROUP BY for a block-wise question is caught", issue and "breakdown" in issue, str(issue))
    check("... without calling the model verifier", calls["verify"] == n_verify)
    issue = asyncio.run(pipeline._verify_sql(
        "q", ["MGNREGA"], er, "SELECT COUNT(*) FROM curated.v_pmay WHERE lgd_district = 'EAST KHASI HILLS' "
                               "AND financial_year_short = '2025-26' AND year_key = 2025"))
    check("another scheme's tables are caught", issue and "MGNREGA" in issue and "PMAY-G" in issue, str(issue))
    ok_sql = ("SELECT lgd_block, SUM(total_exp) FROM curated.v_expenditure WHERE lgd_district = 'EAST KHASI HILLS' "
              "AND year_key = 2025 GROUP BY lgd_block")
    issue = asyncio.run(pipeline._verify_sql("q", ["MGNREGA"], er, ok_sql))
    check("correct SQL passes the frame check and reaches the model verifier",
          issue is None and calls["verify"] == n_verify + 1, str(issue))
    u.current_frame.reset(token)

    frame = F(schemes=["PMAY-G"], metric="houses completed", query_type="ranking", group_by="district")
    token = u.current_frame.set(frame)
    er = ER()
    er["gate_trace"] = ["top_n:default:5"]
    issue = u.frame_sql_issue(frame, ["PMAY-G"], er,
                              "SELECT lgd_district, COUNT(*) FROM curated.v_pmay GROUP BY lgd_district "
                              "ORDER BY 2 DESC LIMIT 10")
    check("defaulted top-5 ranking with LIMIT 10 is caught", issue and "LIMIT 5" in issue, str(issue))
    issue = u.frame_sql_issue(frame, ["PMAY-G"], er,
                              "SELECT lgd_district, COUNT(*) FROM curated.v_pmay GROUP BY lgd_district "
                              "ORDER BY 2 DESC LIMIT 5")
    check("LIMIT 5 passes", issue is None, str(issue))
    check("no frame -> no frame check", u.frame_sql_issue(None, ["PMAY-G"], er, "SELECT 1") is None)
    u.current_frame.reset(token)

    print("\n=== no model frame (Understand gave none -> fallback frame): generation exactly as before ===")
    q = "total MGNREGA expenditure in EKH for FY 2025-26"
    token = u.current_frame.set(u.fallback_frame(q))
    check("a fallback frame is not a SQL frame", u.sql_frame() is None)
    n = len(calls["sql_gen"])
    er = ER(district="EAST KHASI HILLS", year_key=2025)
    asyncio.run(pipeline.generate_sql(q, ["MGNREGA"], er))
    prompt = calls["sql_gen"][-1]
    check("no model frame: even a templatable question goes to the model", len(calls["sql_gen"]) == n + 1)
    check("no model frame: raw question, no REQUIRED FILTERS",
          "REQUIRED FILTERS" not in prompt and f'Question: "{q}"' in prompt)
    check("no model frame: no gate trace written", "gate_trace" not in er)
    u.current_frame.reset(token)
finally:
    llm.call_sql_generator, llm.call_sql_verifier, schema_retrieval.retrieve = orig[0], orig[1], orig[2]
    settings.SQL_VERIFY_ENABLED = flags_before

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL SQL-FRAME CHECKS PASSED")
