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
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import cross_figures as cf

_ANALYTICS = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "chat" / "analytics.js").as_uri()
_NODE = shutil.which("node")


def _rows() -> list[dict]:
    p = cf.Plan(schemes=["MGNREGA", "PMAY-G"], by_district=False, districts=None, block=None, year=None,
                measures=["count"], op="leader")
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


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_compare_card_uses_a_figure_both_schemes_have():
    rows = _rows()
    assert "households_given_work" in rows[0] and "households_given_work" not in rows[1]
    card = _js("a.buildAnalytics('MGNREGA vs PMAY-G households', rows, null)", rows)
    assert card["kind"] == "compare"
    assert card["a"]["value"] > 0 and card["b"]["value"] > 0          # never "PMAY-G 0"
    assert card["a"]["value"] == 3200.5 and card["b"]["value"] == 1500.2


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_table_shows_every_schemes_count_column():
    cols = _js("a.tableColumns(rows)", _rows())
    assert "households_given_work" in cols and "houses_sanctioned" in cols and "sanctioned_crore" in cols


@pytest.mark.skipif(not _NODE, reason="node not installed")
def test_a_sql_null_still_compares():
    # SQL rows keep every key; a NULL measure is unchanged by the fix
    rows = [{"district": "A", "exp": 1}, {"district": "B", "exp": None}]
    assert _js("a.buildAnalytics('A vs B', rows, null).kind", rows) == "compare"
