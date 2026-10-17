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
        "pmay_g": {"sanctioned": 170981, "completed": 129941, "released": 21852598500},
        "focus_plus": {"payments": 385671, "amount": 1197392500, "districts": 12},
        "cm_elevate": {"applications": 8867, "schemes": 15, "districts": 12},
        "focus_legacy": {"groups": 11906, "memberships": 102021, "amount": 510105000},
        "cm_elevate_legacy": {"records": 2823, "schemes": 13, "disbursed": 828978537.75},
    }
    c = stats._cards(rows)
    assert c["pmay_g"][0] == ["1,70,981", "Houses sanctioned"]
    assert c["pmay_g"][2] == ["₹2,185.26 Cr", "Funds released"]
    assert c["mgnrega"] == [["9.09 Cr", "Person-days (4 yr)"], ["₹3,628.67 Cr", "Expenditure (4 yr)"],
                            ["6,491", "Villages with activity"]]
    assert c["focus_plus"][1] == ["₹119.74 Cr*", "Amount disbursed*"]
    assert c["cm_elevate"][0] == ["8,867", "Applications"]
    assert c["focus_legacy"][0] == ["11,906", "Producer Groups"]
    assert c["cm_elevate_legacy"][2] == ["₹82.90 Cr*", "Disbursed (subsidy + loan)*"]
    # same six keys as the cards in frontend/src/chat/constants.js
    assert set(c) == {"mgnrega", "pmay_g", "focus_plus", "cm_elevate", "focus_legacy", "cm_elevate_legacy"}
