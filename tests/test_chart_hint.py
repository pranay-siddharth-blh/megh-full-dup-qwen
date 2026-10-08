"""chart_type on DATA results (pipeline._chart_hint, D-042): the chat UI had
grouped / stacked / KPI charts that never appeared because no backend code
sent the hint, and "show it as a pie chart" changed nothing."""
from decimal import Decimal

import pytest

from app import pipeline

BY_DISTRICT = [{"district_name": "Ri Bhoi", "total_exp": Decimal("120.5")},
               {"district_name": "West Garo Hills", "total_exp": Decimal("98.0")}]


@pytest.mark.parametrize("q,hint", [
    ("MGNREGA expenditure by district as a pie chart", "pie"),
    ("show it in a donut chart", "doughnut"),
    ("houses completed by district, stacked by year", "stacked"),
    ("person-days and households side by side by district", "grouped_bar"),
    ("MGNREGA expenditure line chart", "line"),
    ("PMAY-G houses over the years", "line"),
    ("give me a bar chart of applications by block", "bar"),
    ("bar graph of houses", "bar"),
])
def test_an_asked_for_chart_wins(q, hint):
    assert pipeline._chart_hint(q, q, BY_DISTRICT) == hint


def test_the_typed_text_counts_when_the_rewrite_dropped_the_chart_words():
    assert pipeline._chart_hint("MGNREGA expenditure by district", "show that as a pie chart",
                                BY_DISTRICT) == "pie"


def test_plain_rows_get_no_hint_so_the_ui_decides():
    assert pipeline._chart_hint("MGNREGA expenditure by district", "", BY_DISTRICT) is None


def test_one_row_of_several_figures_is_a_kpi_bar():
    rows = [{"unskilled_wage_exp": Decimal("10.2"), "material_exp": 4, "semi_skilled_wage_exp": "1,200"}]
    assert pipeline._chart_hint("wages vs material", "", rows) == "kpi_bar"


def test_one_row_with_one_figure_gets_no_chart():
    assert pipeline._chart_hint("total houses", "", [{"total_houses": 512}]) is None


def test_two_labels_and_one_additive_measure_are_stacked():
    rows = [{"district_name": d, "year_key": y, "houses_completed": n}
            for d in ("Ri Bhoi", "Tura") for y, n in ((2023, 10), (2024, 12))]
    # year_key is numeric but a label, not a measure
    assert pipeline._chart_hint("houses completed by district and year", "", rows) == "stacked"


def test_a_rate_is_never_stacked():
    rows = [{"district_name": d, "year_key": y, "completion_pct": 50.0}
            for d in ("Ri Bhoi", "Tura") for y in (2023, 2024)]
    assert pipeline._chart_hint("completion % by district and year", "", rows) is None


def test_too_many_series_are_not_stacked():
    rows = [{"district_name": "Ri Bhoi", "block_name": f"B{i}", "houses": i} for i in range(12)]
    assert pipeline._chart_hint("houses by district and block", "", rows) is None


def test_the_hint_is_attached_to_data_results_only():
    data = {"route": "data", "data": BY_DISTRICT}
    pipeline._attach_chart_hint(data, "expenditure as a pie chart", "")
    assert data["chart_type"] == "pie"
    knowledge = {"route": "knowledge", "data": []}
    pipeline._attach_chart_hint(knowledge, "explain as a pie chart", "")
    assert "chart_type" not in knowledge


def test_a_broken_row_never_breaks_the_answer():
    result = {"route": "data", "data": [object()]}
    pipeline._attach_chart_hint(result, "anything", "")
    assert "chart_type" not in result
