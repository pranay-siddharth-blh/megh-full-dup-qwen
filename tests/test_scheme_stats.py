"""/api/scheme-stats: the scheme cards' live figures (2026-10-15 — the PMAY-G card said 1,71,107
houses sanctioned while megh_db held 1,70,981)."""
from app.routers import stats


def test_indian_grouping():
    assert stats._indian(170981) == "1,70,981"
    assert stats._indian(385671) == "3,85,671"
    assert stats._indian(8867) == "8,867"
    assert stats._indian(12) == "12"
    assert stats._indian(None) == "0"


def test_card_figures_from_rows():
    rows = {
        "mgnrega": {"person_days": 90915181, "exp_lakh": 362866.57, "villages": 6491},
        "pmay_g": {"sanctioned": 171107, "completed": 129941, "released": 21852598500},
        "focus_plus": {"payments": 385671, "amount": 1197392500, "districts": 12},
        "cm_elevate": {"applications": 8867, "schemes": 15, "districts": 12},
        "focus_legacy": {"groups": 11906, "memberships": 102021, "amount": 510105000},
        "cm_elevate_legacy": {"records": 2823, "schemes": 13, "disbursed": 828978537.75},
        "cmss": {"applications": 104827, "students_paid": 98751, "amount_disbursed": 592506000},
        "homestay": {"applications": 1297, "applicants": 1278, "approved": 80},
    }
    years = {"mgnrega": ["2022-23", "2023-24", "2024-25", "2025-26"]}
    c = stats._cards(rows, years)
    assert c["pmay_g"][0] == ["1,71,107", "Houses sanctioned"]
    assert c["pmay_g"][2] == ["₹2,185.26 Cr", "Funds released"]
    assert c["mgnrega"] == [["9.09 Cr", "Person-days (4 yr)"], ["₹3,628.67 Cr", "Expenditure (4 yr)"],
                            ["6,491", "Villages with activity"]]
    assert c["focus_plus"][1] == ["₹119.74 Cr*", "Amount disbursed*"]
    assert c["cm_elevate"][0] == ["8,867", "Applications"]
    assert c["focus_legacy"][0] == ["11,906", "Producer Groups"]
    assert c["cm_elevate_legacy"][2] == ["₹82.90 Cr*", "Disbursed (subsidy + loan)*"]
    # CMSS (2026-11-11): money verified, not provisional — no "*"
    assert c["cmss"] == [["1,04,827", "Applications"], ["98,751", "Students paid"], ["₹59.25 Cr", "Amount disbursed"]]
    # same six keys as the cards in frontend/src/chat/constants.js
    # Homestay (2026-11-12): counts only — the application feed records no money (live v_homestay_api)
    assert c["homestay"] == [["1,297", "Applications"], ["1,278", "Applicants"], ["80", "Approved"]]
    assert set(c) == {"mgnrega", "pmay_g", "focus_plus", "cm_elevate", "focus_legacy", "cm_elevate_legacy", "cmss", "homestay"}


# ── 2026-10-22: the cards follow the data (user: "kpi cards … need to update dynamically … based on the
# data"). The period text and "(N yr)" come from the views; a figure the view did not return is "—".
def test_period_text_from_the_years_held():
    assert stats._period(["2022-23", "2023-24", "2024-25", "2025-26"]) == "FY 2022-23 to 2025-26"
    assert stats._period(["2022-23", "2025-26"]) == "FY 2022-23 & 2025-26"                  # Focus Plus
    assert stats._period(["2021-22", "2022-23", "2024-25", "2025-26"]) == \
        "FY 2021-22 to 2025-26, no FY 2023-24"                                              # Focus Legacy
    assert stats._period(["2024-25", "2025-26"]) == "FY 2024-25 to 2025-26"
    assert stats._period(["2023-24"]) == "FY 2023-24"
    assert stats._period([]) == "" and stats._period([None]) == ""


def test_year_count_follows_the_data():
    rows = {**{k: dict.fromkeys(("sanctioned", "completed", "released", "payments", "amount", "districts",
                                 "applications", "schemes", "groups", "memberships", "records", "disbursed"), 1)
               for k in ("pmay_g", "focus_plus", "cm_elevate", "focus_legacy", "cm_elevate_legacy")},
            "mgnrega": {"person_days": 1, "exp_lakh": 1, "villages": 1},
            "cmss": {"applications": 1, "students_paid": 1, "amount_disbursed": 1},
            "homestay": {"applications": 1, "applicants": 1, "approved": 1}}
    c = stats._cards(rows, {"mgnrega": ["2022-23", "2023-24", "2024-25", "2025-26", "2026-27"]})
    assert c["mgnrega"][0][1] == "Person-days (5 yr)" and c["mgnrega"][1][1] == "Expenditure (5 yr)"


def test_a_missing_figure_is_a_dash_not_zero():
    rows = {"mgnrega": {"person_days": None, "exp_lakh": None, "villages": 0},
            "pmay_g": {"sanctioned": 0, "completed": 0, "released": None},
            "focus_plus": {"payments": 0, "amount": None, "districts": 0},
            "cm_elevate": {"applications": 0, "schemes": 0, "districts": 0},
            "focus_legacy": {"groups": 0, "memberships": None, "amount": None},
            "cm_elevate_legacy": {"records": 0, "schemes": 0, "disbursed": None},
            "cmss": {"applications": 0, "students_paid": 0, "amount_disbursed": None},
            "homestay": {"applications": None, "applicants": 0, "approved": 0}}
    c = stats._cards(rows, {})
    assert c["mgnrega"][0] == ["—", "Person-days"] and c["mgnrega"][2] == ["0", "Villages with activity"]
    assert c["pmay_g"][2] == ["—", "Funds released"] and c["focus_legacy"][1] == ["—", "Memberships paid"]
    assert c["homestay"][0] == ["—", "Applications"] and c["homestay"][2] == ["0", "Approved"]


def test_pmay_card_counts_zero_sanction_registrations():
    # user 2026-10-23: the card said 1,70,981; the 126 zero-sanction rows are houses
    # sanctioned too (D-060), so the card's count must not drop them.
    from app import sql_ast
    assert not sql_ast.references_column(stats._SQL["pmay_g"], "is_placeholder")
