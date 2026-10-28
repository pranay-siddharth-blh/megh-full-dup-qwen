"""
The two-scheme comparison card must not read a figure a scheme does not have as 0.

User report 2026-10-22: "MGNREGA vs PMAY-G — households given work: MGNREGA
14,94,437 vs PMAY-G 0". The cross-scheme figures table (app/cross_figures.py,
D-066) gives each scheme its own count column (MGNREGA households_given_work,
PMAY-G houses_sanctioned). frontend/src/chat/analytics.js took its columns from
the first row only, charted households_given_work, and read the PMAY-G row's
missing value as 0. The table and the export dropped PMAY-G's houses_sanctioned
the same way.

Runs the real analytics.js in Node on the real cross_figures._rows output.
Skipped when node is not installed.

User report 2026-10-27: "Compare beneficiaries in mgnrega and PMAY-G" drew the card
on amount (₹ crore) — the only column both rows had — and the table carried money,
villages, sanctioned amounts and completed houses nobody asked for. Every scheme's
count is now in one `beneficiaries` column and the table holds the asked measures
only; the card picks the column of the measure the question names.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import cross_figures as cf

_ANALYTICS = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "chat" / "analytics.js").as_uri()
_NODE = shutil.which("node")


def _rows(measures=("count",)) -> list[dict]:
    p = cf.Plan(schemes=["MGNREGA", "PMAY-G"], by_district=False, districts=None, block=None, year=None,
                measures=list(measures), op="leader")
    figs = {"MGNREGA": {cf.STATE: {"ben": 1494437, "money": 3200.5, "villages": 6500}},
            "PMAY-G": {cf.STATE: {"ben": 180000, "completed": 150000, "money": 1500.2, "sanctioned": 2000.1,
                                  "villages": 5800}}}
    return cf._rows(p, figs, ["MGNREGA", "PMAY-G"])


def _js(expr: str, rows: list[dict]) -> object:
    script = (f"const a = await import({json.dumps(_ANALYTICS)}); const rows = {json.dumps(rows)};"
              f" console.log(JSON.stringify({expr}));")
    out = subprocess.run([_NODE, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_count_question_gets_only_the_count_in_one_shared_column():
    rows = _rows()
    assert rows == [{"scheme": "MGNREGA", "beneficiaries": 1494437},
                    {"scheme": "PMAY-G", "beneficiaries": 180000}]


def test_a_money_question_gets_only_the_money_columns():
    rows = _rows(("money",))
    assert rows == [{"scheme": "MGNREGA", "amount_crore": 3200.5},
                    {"scheme": "PMAY-G", "amount_crore": 1500.2, "sanctioned_crore": 2000.1}]


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_compare_card_compares_beneficiaries_when_asked():
    rows = _rows()
    card = _js("a.buildAnalytics('Compare beneficiaries in mgnrega and PMAY-G.', rows, null)", rows)
    assert card["kind"] == "compare"
    assert card["a"]["value"] > 0 and card["b"]["value"] > 0          # never "PMAY-G 0"
    assert card["a"]["value"] == 1494437 and card["b"]["value"] == 180000
    assert card["measure"] == "beneficiaries"


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_compare_card_follows_the_measure_the_question_names():
    rows = _rows(("count", "money"))
    card = _js("a.buildAnalytics('Compare amount spent in MGNREGA and PMAY-G', rows, null)", rows)
    assert card["a"]["value"] == 3200.5 and card["b"]["value"] == 1500.2
    card = _js("a.buildAnalytics('Compare beneficiaries and amount in MGNREGA and PMAY-G', rows, null)", rows)
    assert card["a"]["value"] == 1494437                               # both named: the first column
    # model-written SQL rows the same way: the asked measure, not the first column
    sql_rows = [{"district": "A", "persondays": 10, "total_exp": 900}, {"district": "B", "persondays": 20, "total_exp": 700}]
    assert _js("a.buildAnalytics('Compare expenditure of A and B', rows, null).a.value", sql_rows) == 900
    assert _js("a.buildAnalytics('Compare A and B', rows, null).a.value", sql_rows) == 10
    assert _js("a.buildAnalytics('Explain A vs B', rows, null).a.value", sql_rows) == 10   # "explain" is not money


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_table_shows_every_schemes_column():
    cols = _js("a.tableColumns(rows)", _rows(("count", "money")))
    assert cols == ["scheme", "beneficiaries", "amount_crore", "sanctioned_crore"]


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_a_sql_null_still_compares():
    # SQL rows keep every key; a NULL measure is unchanged by the fix
    rows = [{"district": "A", "exp": 1}, {"district": "B", "exp": None}]
    assert _js("a.buildAnalytics('A vs B', rows, null).kind", rows) == "compare"
