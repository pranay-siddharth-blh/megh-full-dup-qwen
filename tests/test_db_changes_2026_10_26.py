"""Ingestion team's database changes of 15-24 Oct (note CHATBOT_DB_CHANGES_2026-10-26.md).

- v_focus_plus.member_id was removed; member_key holds the same person (masked), on the
  12.5K cohort only. The SQL prompt and the Focus Plus rules said member_id, so a live
  12.5K-member question failed first ("column member_id does not exist") and was repaired
  to another column.
- Every scheme view gained a `region` column. A query that builds its own
  `CASE … END AS region` and says `GROUP BY region` now groups by the view's column and
  fails; six few-shot examples taught that shape."""
from pathlib import Path

import pytest

from app import pipeline as p
from app import schema_context


def test_the_sql_prompt_names_member_key_not_the_removed_member_id():
    text = Path(schema_context.__file__).read_text(encoding="utf-8")
    assert "member_key" in text
    assert "member_id" not in text


def test_the_focus_plus_rules_name_member_key_for_the_view():
    root = Path("data/focus_plus")
    for name in ("focusplus_few_shot.yaml", "focusplus_schema_partitions.yaml", "focusplus_entity_resolver.yaml"):
        text = (root / name).read_text(encoding="utf-8")
        assert "COUNT(DISTINCT member_id)" not in text, name
    assert "COUNT(DISTINCT member_key)" in (root / "focusplus_few_shot.yaml").read_text(encoding="utf-8")


_BAD = ("SELECT CASE WHEN lgd_district IN ('EAST GARO HILLS', 'WEST GARO HILLS') THEN 'Garo Hills' "
        "ELSE 'Other' END AS region, SUM(total_exp) AS t FROM curated.v_expenditure "
        "GROUP BY region ORDER BY region")


def test_a_computed_region_no_longer_collides_with_the_views_region_column():
    out = p._region_alias_not_the_column(_BAD)
    assert "AS region_group" in out and "GROUP BY region_group" in out and "ORDER BY region_group" in out
    assert " region," not in out.replace("region_group", "")


def test_the_views_own_region_column_is_left_alone():
    for sql in ("SELECT region, SUM(total_exp) FROM curated.v_expenditure GROUP BY region",
                "SELECT region AS region, SUM(total_exp) FROM curated.v_expenditure GROUP BY region"):
        assert p._region_alias_not_the_column(sql) == sql


def test_no_few_shot_example_still_groups_by_a_computed_region():
    for f in Path("data").rglob("*few_shot*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "END AS region," not in text.replace("AS region_group,", ""), f


# ── Ingestion answers (ANSWERS_TO_CHATBOT_TEAM_2026-10-26.md) ─────────────────────
from decimal import Decimal  # noqa: E402

from app import entity_resolver as er  # noqa: E402


def test_khasi_hills_includes_ri_bhoi_for_every_scheme():
    """Answer 2: the LGD master puts Ri Bhoi in the Khasi region."""
    er.load_all()
    for s in ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CM Elevate Legacy", "CMSS", "Homestay"):
        r = er.detect_region("total in all of Khasi Hills", s)
        assert r is not None and "Ri Bhoi" in r["districts"] and len(r["districts"]) == 5, s
    assert er.detect_region("total in Ri Bhoi", "MGNREGA") is None          # the district, not a region


def test_the_prompt_names_the_region_column_and_ri_bhoi_in_khasi():
    text = Path(schema_context.__file__).read_text(encoding="utf-8")
    assert "Ri Bhoi is its own group" not in text and "and RI BHOI" in text


@pytest.mark.parametrize("q", [
    "How many CM Elevate applications are pending?",
    "pending applications in Ri Bhoi",
    "How many applications were sent back?",
    "How many CM Elevate applications were rejected?",
])
def test_a_workflow_status_gets_the_recorded_figures_not_on_hold(q):
    """Answer 3 (2026-10-26) as amended by the user on 2026-10-30: the recorded workflow figures
    are offered; data_verified is never read for pending / on hold."""
    sql, params, _shown = p._cme_workflow_query(q, {"district": "RI BHOI"} if "Ri Bhoi" in q else {})
    assert "cme-sector-workflow" in sql and "COUNT(DISTINCT request_id)" in sql
    assert "'On Hold'" not in sql and "current_file_status = 'forward'" in sql


@pytest.mark.parametrize("q", [
    "applications pending verification",
    "How many applications are forwarded?",
    "How many applications were resubmitted?",
])
def test_a_recorded_field_keeps_its_own_path(q):
    assert p._cme_workflow_query(q, {}) is None


def test_on_hold_and_levels_take_the_pending_path():
    """User 2026-10-30: on hold is the pending rule (never data_verified); a level filters it."""
    sql, params, _ = p._cme_workflow_query("How many CM Elevate applications are on hold?", {})
    assert "cme-sector-workflow" in sql and "'On Hold'" not in sql
    sql, params, _ = p._cme_workflow_query("How many applications are pending at level 2?", {})
    assert "LOWER(current_level) = $1" in sql and params == ["level2"]


def test_the_workflow_answer_says_not_recorded_and_labels_the_figures():
    rows = [{"forward": 8837, "resubmit": 2, "sendback": 1, "applications": 8840}]
    a = p._cme_sector_answer("How many CM Elevate applications are pending?",
                             "/* cme-sector-workflow */ SELECT 1", rows, {})
    assert a.startswith("Pending means:") and "pending count is not available" in a
    assert "8,840 valid applications" in a and "8,837 forward" in a and "on hold" not in a.lower().replace("on-hold", "")
    b = p._cme_sector_answer("How many CM Elevate applications are on hold?",
                             "/* cme-sector-workflow */ SELECT 1", rows, {})
    assert "on-hold count is not available" in b and "data verification" not in b


def test_money_in_crore_and_lakh_is_rounded_for_display_only():
    rows = [{"total_disbursed_crore": Decimal("119.73925"), "exp_lakh": 8996.3612, "beneficiaries": 105813,
             "share_pct": 12.34567, "amount_raw": 1197392500.0}]
    shown = p._money_rounded_for_display(rows)[0]
    assert shown["total_disbursed_crore"] == 119.74 and shown["exp_lakh"] == 8996.36
    assert shown["beneficiaries"] == 105813 and shown["share_pct"] == 12.34567 and shown["amount_raw"] == 1197392500.0
    assert rows[0]["total_disbursed_crore"] == Decimal("119.73925")                 # the rows are not changed
    assert p._answer_numbers_faithful("It was 119.74 crore.", p._data_numbers(rows))


def test_select_star_is_left_alone_when_no_column_is_hidden(monkeypatch):
    from app import schema_introspect as si
    monkeypatch.setitem(si._cache, "denied", set())
    sql = "SELECT * FROM curated.v_cm_elevate LIMIT 1"
    assert p._star_without_hidden_columns(sql) == sql


def test_select_star_on_a_table_with_hidden_columns_lists_the_readable_ones(monkeypatch):
    from app import schema_introspect as si
    monkeypatch.setitem(si._cache, "denied", {("curated", "v_cm_elevate", "scheme_specific")})
    monkeypatch.setitem(si._cache, "live_columns", {"curated.v_cm_elevate": [
        {"column": "request_id"}, {"column": "lgd_district"}]})
    out = p._star_without_hidden_columns("SELECT * FROM curated.v_cm_elevate WHERE lgd_district = 'RI BHOI'")
    assert "*" not in out and "request_id" in out and "lgd_district" in out and "scheme_specific" not in out


def test_a_khasi_region_answer_states_it_includes_ri_bhoi():
    """Live 2026-10-26: "Total MGNREGA expenditure in all of Khasi Hills" -> 234.8 crore (Ri Bhoi
    included, correctly) but the sentence never said so; the data team asked for one line."""
    import asyncio
    d = {"question": "Total MGNREGA expenditure in all of Khasi Hills in FY 2023-24", "schemes": ["PMAY-G"],
         "entity_result": {"resolved": {"district_list_region": "Khasi Hills"},
                           "display": {"district": "Khasi Hills (includes Ri Bhoi)"}},
         "sql": "SELECT 1", "rows": [{"x_crore": 234.8}], "answer": "It was 234.8 crore.",
         "fp_amount": None, "mg_women": None, "fl_total": None, "fl_unplaced": None, "fl_breakdown": None}
    asyncio.run(p._data_guarantees_stage(d))
    assert "Khasi Hills here includes Ri Bhoi district" in d["answer"]


def test_no_app_code_reads_the_unloaded_default_rule_or_template_files():
    """Ingestion team, 2026-10-26: the *_default_rules.yaml / *_response_template.yaml files quote
    old counts; they are marked NOT LOADED, and no app code may start reading them unnoticed.
    Only string literals count (a comment that names them is fine)."""
    import ast
    for f in Path("app").rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                low = node.value.lower()
                assert "default_rules" not in low and "response_template" not in low, (str(f), node.value[:80])
    for f in list(Path("data").glob("*/*default_rules*.yaml")) + list(Path("data").glob("*/*response_template*.yaml")):
        assert f.read_text(encoding="utf-8").startswith("# NOT LOADED BY THE APP"), f
