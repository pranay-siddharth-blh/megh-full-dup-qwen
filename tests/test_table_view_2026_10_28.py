"""
Tables and chart axes show what the rows mean (user report 2026-10-28).

"How have MGNREGA person-days changed over the last three years in Meghalaya?"
returned year_key + financial_year + person_days. frontend/src/chat/analytics.js
read the two year columns as two dimensions and drew a 3x3 grid with only the
diagonal filled (six "—" cells); PivotGrid printed raw cells (27264054) beside
formatted totals (2,72,64,054) and always added a Total row, column and grand
total; headers were database names ("YEAR KEY"); the chart had no axis titles.

frontend/src/chat/columns.js now decides once what each column is: twin columns
(one thing written two ways) are shown once, measures are formatted and
right-aligned, totals only for measures that add up, readable headers, axis
titles and units, and "Change from previous" only when the question asks how a
figure moved. The rows and the Excel download are unchanged.

Runs the REAL analytics.js / columns.js / Charts.jsx: the components are bundled
with the frontend's own esbuild and rendered with react-dom/server. Skipped when
node or the frontend's node_modules are missing.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_FRONT = Path(__file__).resolve().parents[1] / "frontend"
_NODE = shutil.which("node")
_ESBUILD = _FRONT / "node_modules" / ".bin" / ("esbuild.cmd" if os.name == "nt" else "esbuild")
pytestmark = pytest.mark.skipif(not _NODE or not _ESBUILD.exists(), reason="node / frontend node_modules missing")

_ENTRY = """
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { DynTable, PivotTable, RecordCard } from '%(src)s/chat/components/Charts.jsx';
import * as analytics from '%(src)s/chat/analytics.js';
import * as columns from '%(src)s/chat/columns.js';
globalThis.T = {
  analytics, columns,
  dyn: (rows, change) => renderToStaticMarkup(createElement(DynTable, { data: rows, change })),
  pivot: (rows, xKey, sKey, vKey) => renderToStaticMarkup(createElement(PivotTable, { data: rows, xKey, sKey, vKey })),
  record: (row) => renderToStaticMarkup(createElement(RecordCard, { row })),
};
"""


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    d = tmp_path_factory.mktemp("tableview")
    entry = d / "entry.jsx"
    entry.write_text(_ENTRY % {"src": (_FRONT / "src").as_posix()}, encoding="utf-8")
    out = d / "bundle.cjs"
    env = dict(os.environ, NODE_PATH=str(_FRONT / "node_modules"))
    r = subprocess.run([str(_ESBUILD), str(entry), "--bundle", "--platform=node", "--format=cjs", "--jsx=automatic",
                        f"--outfile={out}", "--log-level=error"], capture_output=True, text=True, env=env,
                       timeout=120, shell=os.name == "nt")
    assert r.returncode == 0, r.stderr
    return out


def _js(bundle, expr, **data):
    lets = "".join(f"const {k} = {json.dumps(v)};" for k, v in data.items())
    script = f"require({json.dumps(str(bundle))}); const T = globalThis.T; {lets} console.log(JSON.stringify({expr}));"
    r = subprocess.run([_NODE, "-e", script], capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# the user's screenshot rows
SHOT = [{"year_key": 2023, "financial_year": "2023-2024", "person_days": 27264054},
        {"year_key": 2024, "financial_year": "2024-2025", "person_days": 14667872},
        {"year_key": 2025, "financial_year": "2025-2026", "person_days": 23387018}]
Q = "How have MGNREGA person-days changed over the last three years in Meghalaya?"
# a real two-way table: district x year
TWO = [{"lgd_district": d, "financial_year": y, "person_days": n}
       for d, y, n in (("RI BHOI", "2023-24", 10), ("RI BHOI", "2024-25", 20),
                       ("EAST KHASI HILLS", "2023-24", 30), ("EAST KHASI HILLS", "2024-25", 40))]


def test_screenshot_rows_are_one_period_series(bundle):
    a = _js(bundle, "T.analytics.buildAnalytics(q, rows, null)", q=Q, rows=SHOT)
    assert a["kind"] == "multi" and a["change"] is True            # was twoDim (diagonal grid)
    c = a["charts"][0]
    assert c["fullLabels"] == ["2023-2024", "2024-2025", "2025-2026"]
    # chat UI audit 2026-10-29 (D-5 / I-10): the axes also say whether less is better,
    # whether the low end was asked, and the measure's words for the headline
    assert c["axes"] == {"x": "Financial year", "y": "Person days", "unit": None,
                         "lowerBetter": False, "measure": "person days", "low": False}
    assert all("year_key" not in r for r in a["data"])


def test_screenshot_table_has_no_dashes_and_reads_the_change(bundle):
    html = _js(bundle, "T.dyn(rows, true)", rows=SHOT)
    assert "—" not in html and "Year key" not in html and "Total" not in html
    assert "<th>Financial year</th>" in html and '<th class="num">Person days</th>' in html
    assert '<td class="num">2,72,64,054</td>' in html
    assert "−1,25,96,182 (−46.2%)" in html and "+87,19,146 (+59.4%)" in html


def test_no_change_column_unless_asked(bundle):
    assert "Change from previous" not in _js(bundle, "T.dyn(rows, false)", rows=SHOT)
    a = _js(bundle, "T.analytics.buildAnalytics(q, rows, null)",
            q="Show MGNREGA person-days for each financial year", rows=SHOT)
    assert a["change"] is False
    # two measures, or periods out of order: no change column even when asked
    two_m = [dict(r, households=1) for r in SHOT]
    assert _js(bundle, "T.columns.changeColumn(rows)", rows=two_m) is None
    assert _js(bundle, "T.columns.changeColumn(rows)", rows=[SHOT[1], SHOT[0]]) is None


def test_a_real_two_way_table_stays_a_pivot_with_totals(bundle):
    assert _js(bundle, "T.columns.twinColumns(rows)", rows=TWO) == {}
    assert _js(bundle, "T.analytics.buildAnalytics('district wise by year', rows, null).kind", rows=TWO) == "twoDim"
    html = _js(bundle, "T.pivot(rows, 'financial_year', 'lgd_district', 'person_days')", rows=TWO)
    assert html.count(">Total<") == 2 and '<strong>100</strong>' in html      # row + column totals, grand 100


def test_no_totals_for_measures_that_do_not_add_up(bundle):
    for col in ("completion_rate_pct", "avg_wage", "job_cards_issued_total"):
        rows = [dict(lgd_district=r["lgd_district"], financial_year=r["financial_year"], **{col: r["person_days"]})
                for r in TWO]
        html = _js(bundle, f"T.pivot(rows, 'financial_year', 'lgd_district', '{col}')", rows=rows)
        assert ">Total<" not in html, col


def test_only_true_twins_are_merged(bundle):
    # block and district are two names: never merged, even one-to-one
    blocks = [{"lgd_block": b, "lgd_district": d, "n": i}
              for i, (b, d) in enumerate((("A", "D1"), ("B", "D2"), ("C", "D3")))]
    assert _js(bundle, "T.columns.twinColumns(rows)", rows=blocks) == {}
    # a village name and its code are one thing: the code is hidden on screen
    vill = [{"village_code": 274001 + i, "lgd_village_name": f"V{i}", "houses": i} for i in range(3)]
    assert _js(bundle, "T.columns.twinColumns(rows)", rows=vill) == {"village_code": "lgd_village_name"}
    # two villages with the same name keep their codes (not one-to-one)
    same = [{"village_code": 1, "lgd_village_name": "Umsning", "n": 1},
            {"village_code": 2, "lgd_village_name": "Umsning", "n": 2},
            {"village_code": 3, "lgd_village_name": "Nongpoh", "n": 3}]
    assert _js(bundle, "T.columns.twinColumns(rows)", rows=same) == {}
    # the rows themselves are never changed (the Excel download reads them)
    assert _js(bundle, "(T.analytics.buildAnalytics('q', rows, null), rows[0])", rows=SHOT) == SHOT[0]


@pytest.mark.parametrize("v, col, shown", [
    (27264054, "person_days", "2,72,64,054"),
    ("1494437", "households", "14,94,437"),
    (119.73925, "amount_cr", "119.74"),
    (2023, "year_key", "2023"),               # a year is a label: never "2,023"
    (274001, "village_code", "274001"),
    (None, "x", "—"), ("None", "x", "—"), ("", "x", "—"),
    ("RI BHOI", "lgd_district", "Ri Bhoi"),   # C-5 (chat UI audit 2026-10-29): places in Title Case
    ("2023-24", "financial_year", "2023-24"),
    ("0012", "sanction_no", "0012"),          # an identifier in digits is shown as stored
    ("1234567890123", "account_ref", "1234567890123"),
    ("0.5", "share_x", "0.5"),
])
def test_cell_format(bundle, v, col, shown):
    assert _js(bundle, "T.columns.formatCell(v, col)", v=v, col=col) == shown


def test_headers_and_units(bundle):
    assert _js(bundle, "['total_exp_lakh','lgd_district','amount_raw','person_days','completion_rate_pct']"
                       ".map(T.columns.colTitle)") == \
        ["Total expenditure (₹ lakh)", "District", "Amount", "Person days", "Completion rate %"]
    assert _js(bundle, "['total_exp_lakh','loan_cr','valid_pct','person_days'].map(T.columns.unitOf)") == \
        ["lakh", "crore", "pct", None]


def test_record_card_formats_its_figures(bundle):
    html = _js(bundle, "T.record(row)", row={"total_exp_lakh": 8996.3612, "person_days": 2134560, "year_key": 2023})
    assert "8,996.36" in html and "21,34,560" in html and ">2023<" in html


def test_other_views_keep_their_kind(bundle):
    cross = [{"scheme": "MGNREGA", "beneficiaries": 1494437}, {"scheme": "PMAY-G", "beneficiaries": 171107}]
    assert _js(bundle, "T.analytics.buildAnalytics('Compare beneficiaries in mgnrega and PMAY-G', rows, null).kind",
               rows=cross) == "compare"
    one = [{"person_days": 5}]
    assert _js(bundle, "T.analytics.buildAnalytics('q', rows, null).kind", rows=one) == "record"
    names = [{"lgd_block": "A"}, {"lgd_block": "B"}]
    assert _js(bundle, "T.analytics.buildAnalytics('which blocks', rows, null).kind", rows=names) == "table"
    summary = [{"scheme": "MGNREGA", "count": 10, "count_measure": "households", "amount_rupees": 5e9,
                "money_measure": "expenditure"},
               {"scheme": "PMAY-G", "count": 20, "count_measure": "houses", "amount_rupees": 2e9,
                "money_measure": "released"}]
    a = _js(bundle, "T.analytics.buildAnalytics('q', rows, null)", rows=summary)
    # B-5 (audit 2026-10-29, decided): the old cross_scheme summary special case is gone;
    # two schemes are a side-by-side card that never names a scheme "ahead"
    assert a["kind"] == "compare" and a["verdict"] == {"unlike": True, "measure": "count"}
    # a twin pair in two rows reads as a two-way comparison card of the readable labels
    card = _js(bundle, "T.analytics.buildAnalytics('compare', rows, null)", rows=SHOT[:2])
    assert card["kind"] == "compare" and card["title"] == "2023-2024 vs 2024-2025"
