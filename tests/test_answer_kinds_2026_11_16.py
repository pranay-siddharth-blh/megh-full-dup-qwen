"""Answer-quality and routing kinds from the user's live log (app.conversation_turns, 15-16 Nov 2026).

K1  "Give me the figure of MGNREGA for West Garo Hills?" went to the reference documents: a vague measure word
    (figure / numbers / data / details / stats / status) with one scheme and one place is the scheme's headline
    figures for that place (the D-052 overview).
K2  "MGNREGA in 2020." went to the documents too: one scheme and one year and nothing else is the statewide
    overview of that year; a year the data does not hold is said plainly, with the nearest year held.
K4  A month series read "36 in 2021-12-01 against 3,572 in 2021-01-01": months read "December 2021".
K5  "₹91,605.96 lakh (≈ ₹916.06 crore)" is heavy: one crore or more reads "₹916.06 crore".
"""
import pytest

from app import entity_resolver
from app import pipeline as p
from app.pipeline import ClarificationNeeded


@pytest.fixture(scope="module", autouse=True)
def _catalog():
    entity_resolver.load_all()


@pytest.fixture
def natural_on(monkeypatch):
    monkeypatch.setattr(p.settings, "ANSWER_TEMPLATES_ENABLED", True)
    monkeypatch.setattr(p.settings, "ANSWER_NATURAL_ENABLED", True)
    monkeypatch.setattr(p.settings, "ANSWER_MONEY_CRORE_LEAD", True)


# ── K1: a vague measure word with a scheme and a place = the scheme's headline figures there ──

@pytest.mark.parametrize("text, want", [
    ("Give me the figure of MGNREGA for West Garo Hills?",
     "Compare expenditure and person-days in West Garo Hills district"),
    ("Give me the figures of MGNREGA for West Garo Hills", "Compare expenditure and person-days in West Garo Hills district"),
    ("MGNREGA numbers in Ri Bhoi", "Compare expenditure and person-days in Ri Bhoi district"),
    ("Give me MGNREGA data for Ri Bhoi", "Compare expenditure and person-days in Ri Bhoi district"),
    ("Show me the details of Focus Plus in Ri Bhoi",
     "Total Focus Plus amount disbursed and number of beneficiaries in Ri Bhoi district"),
    ("What is the status of PMAY-G in East Khasi Hills?", "PMAY-G house status in East Khasi Hills district"),
    ("PMAY-G figures for Dalu block in 2022-23", "PMAY-G house status in Dalu block in FY 2022-23"),
    ("MGNREGA stats for West Garo Hills in 2023-24",
     "Compare expenditure and person-days in West Garo Hills district in FY 2023-24"),
])
def test_vague_measure_with_scheme_and_place_is_the_overview(text, want):
    q, preface = p._overview_question(text)
    assert q == want and preface.startswith("Here's an overview of")


@pytest.mark.parametrize("text", [
    "Give me MGNREGA person-days data for Ri Bhoi",          # names its measure
    "MGNREGA figure for West Garo Hills and Ri Bhoi",        # two places
    "What is the status of my MGNREGA application?",         # no place: a personal / rules question
    "MGNREGA in 2020 and 2021",                              # two years
    "MGNREGA wage rate in 2020",                             # a measure of its own
])
def test_vague_measure_leaves_real_questions_alone(text):
    assert p._overview_question(text) is None


# ── K2: one scheme and one year, nothing else; a year outside the data said plainly ──

@pytest.mark.parametrize("text, want", [
    ("MGNREGA in 2020.", "Compare expenditure and person-days in Meghalaya in FY 2020-21"),
    ("MGNREGA in 2023-24", "Compare expenditure and person-days in Meghalaya in FY 2023-24"),
    ("PMAY-G in 2015", "PMAY-G house status in Meghalaya in FY 2015-16"),
    ("Give me Focus Plus data for 2022-23",
     "Total Focus Plus amount disbursed and number of beneficiaries in Meghalaya in FY 2022-23"),
])
def test_scheme_and_year_alone_is_the_statewide_overview(text, want):
    q, preface = p._overview_question(text)
    assert q == want and "across Meghalaya" in preface


def test_year_outside_the_data_names_the_years_held_and_the_nearest(monkeypatch):
    monkeypatch.setitem(p._SCHEME_DATA_YEARS, "MGNREGA", ["2022-23", "2023-24", "2024-25", "2025-26"])
    e = p._year_out_of_range_clarification("Compare expenditure and person-days in Meghalaya in FY 2020-21",
                                           "2020-21", ["MGNREGA"])
    assert isinstance(e, ClarificationNeeded)
    assert "data is available only for the financial years 2022-23, 2023-24, 2024-25, 2025-26" in e.question
    assert "The nearest year with data is FY 2022-23." in e.question
    labels = [o["label"] for o in e.options]
    assert labels[0] == "FY 2022-23 (nearest)" and "All available years combined" in labels
    # a year after the data: "no data yet", no "nearest" sentence
    e2 = p._year_out_of_range_clarification("MGNREGA person-days in FY 2030-31", "2030-31", ["MGNREGA"])
    assert "has no data yet" in e2.question and "nearest" not in e2.question


# ── K4: months read as months ──

PMAY_MONTH_ROWS = [{"sanction_month": f"2021-{m:02d}-01", "houses_sanctioned": v} for m, v in
                   zip(range(1, 13), [3572, 9077, 1400, 836, 308, 224, 538, 709, 90, 47, 32, 36])]
PMAY_MONTH_SQL = ("SELECT sanction_month, SUM(houses_sanctioned) AS houses_sanctioned FROM "
                  "curated.v_pmay_monthly_sanctions WHERE sanction_month >= '2021-01-01'::date AND sanction_month < "
                  "'2022-01-01'::date GROUP BY sanction_month ORDER BY sanction_month LIMIT 12")
PMAY_MONTH_Q = "How many PMAY-G houses were sanctioned month by month in 2021?"


def test_month_labels_read_as_months():
    shape = p._answer_shape(PMAY_MONTH_Q, PMAY_MONTH_SQL, PMAY_MONTH_ROWS)
    assert shape.kind == "trend"
    assert p._c12s_label(PMAY_MONTH_ROWS[11], shape) == "December 2021"
    assert p._c12s_e9_period(PMAY_MONTH_ROWS[0], shape) == "January 2021"
    assert p._c12s_date_words("sanction_date", "2024-03-05") == "5 March 2024"
    assert p._c12s_date_words("sanction_month", "2021-02-01 00:00:00") == "February 2021"
    assert p._c12s_date_words("block_name", "DALU") == "DALU"


def test_month_trend_lead_list_and_spoken_say_months(natural_on):
    shape = p._answer_shape(PMAY_MONTH_Q, PMAY_MONTH_SQL, PMAY_MONTH_ROWS)
    text = p._c19_written(shape, PMAY_MONTH_ROWS, PMAY_MONTH_Q, ["PMAY-G"], {})
    assert text is not None and "-01" not in text
    assert "36 in December 2021 against 3,572 in January 2021" in text
    assert "peaked at 9,077 in February 2021" in text
    assert "- November 2021: 32" in text
    spoken = p._c19_spoken_shape(shape, PMAY_MONTH_ROWS, PMAY_MONTH_Q, ["PMAY-G"], {})
    assert "January 2021" in spoken and "Each month's figure is on your screen." in spoken


def test_a_rising_monthly_series_says_every_month(natural_on):
    rows = [{"sanction_month": f"2021-{m:02d}-01", "houses_sanctioned": 100 * m} for m in range(1, 5)]
    shape = p._answer_shape("PMAY-G houses sanctioned month by month in 2021", PMAY_MONTH_SQL, rows)
    lead = p._c19_lead_trend(shape, p._c19_pairs(shape, rows), "q", ["PMAY-G"], {})
    assert "has risen every month" in lead and "April 2021" in lead


# ── K5: one crore or more = the crore figure ──

def test_money_of_a_crore_or_more_reads_in_crore(natural_on):
    assert p._c12_money(91605.96, "lakh") == "₹916.06 crore"
    assert p._c12_money(374931500, "rupees") == "₹37.49 crore"
    assert p._c12_money(-2976.56, "lakh") == "-₹29.77 crore"
    assert p._c12_money(3628.67, "crore") == "₹3,628.67 crore"
    # under a crore: as before
    assert p._c12_money(940000, "rupees") == "₹9,40,000 (≈ ₹9.40 lakh)"
    assert p._c12_money(85.25, "lakh") == "₹85.25 lakh"
    # a composer's own exact copy in brackets is not said twice
    out = p._c12_normalise_figures("₹1,356.45 crore (₹13,56,45,32,500) was spent.", [{"b": 13564532500}],
                                   ["MGNREGA"])
    assert out == "₹1,356.45 crore was spent."


def test_money_switch_off_restores_the_exact_and_size_form(natural_on, monkeypatch):
    monkeypatch.setattr(p.settings, "ANSWER_MONEY_CRORE_LEAD", False)
    assert p._c12_money(91605.96, "lakh") == "₹91,605.96 lakh (≈ ₹916.06 crore)"
    monkeypatch.setattr(p.settings, "ANSWER_MONEY_CRORE_LEAD", True)
    monkeypatch.setattr(p.settings, "ANSWER_NATURAL_ENABLED", False)
    assert p._c12_money(374931500, "rupees") == "₹37,49,31,500 (≈ ₹37.49 crore)"


def test_money_ranking_lead_and_list_in_crore(natural_on):
    rows = [{"lgd_district": "WEST GARO HILLS", "total_expenditure_lakh": 91605.96},
            {"lgd_district": "EAST KHASI HILLS", "total_expenditure_lakh": 45000.5},
            {"lgd_district": "RI BHOI", "total_expenditure_lakh": 800.25}]
    sql = ("SELECT lgd_district, SUM(total_exp) AS total_expenditure_lakh FROM curated.v_expenditure "
           "GROUP BY 1 ORDER BY 2 DESC")
    q = "Which districts spent the most on MGNREGA?"
    shape = p._answer_shape(q, sql, rows)
    text = p._c19_written(shape, rows, q, ["MGNREGA"], {})
    assert "₹916.06 crore" in text and "lakh (≈" not in text
    assert "1. **West Garo Hills** — ₹916.06 crore" in text
    assert "3. **Ri Bhoi** — ₹8.00 crore" in text


# ── polite requests are requests, not capability questions (log bank 2026-11-16) ──

from app import context_policy, edge  # noqa: E402


@pytest.mark.parametrize("text", [
    "Can you give me the headline figure of every scheme?",
    "Can you give me the data of PMAY-G for Meghalaya as of all the districts?",
    "Could you do the same for East Garo Hills?",
    "Can you give me the MGNREGA numbers for West Garo Hills",
    "Okay, and now can you give me the headline just for MGNREGA?",
    "Could you break it down by block?",
])
def test_polite_data_request_is_not_a_capability_question(text):
    out = edge.detect_edge_case(text, has_context=True)
    assert out is None or out.get("type") != "capability"


@pytest.mark.parametrize("text", [
    "Can you answer questions about MGNREGA?", "can you help me?", "What can you do?", "can you answer my questions?",
    "Will you be able to give answers on Meghalaya schemes?",
])
def test_real_capability_questions_stay_capability(text):
    assert (edge.detect_edge_case(text) or {}).get("type") == "capability"


# ── K7: a question about the schemes themselves, or opened with "Okay, now", is not glued to the previous one ──

@pytest.mark.parametrize("text", [
    "Okay, now give me the headline figure of every scheme",
    "Which scheme provided the highest total financial assistance across Meghalaya?",
    "Which scheme has the widest coverage across the districts of Meghalaya?",
    "So which scheme has the most beneficiaries?",
    "Alright, MGNREGA person-days in Ri Bhoi in 2023-24",
])
def test_standalone_questions_are_standalone(text):
    assert context_policy.turn_kind(text).kind == context_policy.TURN_STANDALONE


@pytest.mark.parametrize("text", [
    "and in 2023-24?", "okay what about Ri Bhoi?", "which scheme has the most?", "Now by block",
    "Okay, and now can you give me the headline just for MGNREGA?",
])
def test_follow_ups_stay_follow_ups(text):
    assert context_policy.turn_kind(text).kind == context_policy.TURN_FOLLOWUP


# ── K1 (log bank): a bare scheme + place, a statewide headline ask; never for a breakdown ──

@pytest.mark.parametrize("text, want", [
    ("MGNREGA in East Khasi Hills.", "Compare expenditure and person-days in East Khasi Hills district"),
    ("Show me MGNREGA for Tikrikilla block", "Compare expenditure and person-days in Tikrikilla block"),
    ("MGNREGA headline figures", "Compare expenditure and person-days in Meghalaya"),
    ("can you give me the headline just for MGNREGA?", "Compare expenditure and person-days in Meghalaya"),
])
def test_bare_scheme_place_and_headline_asks(text, want):
    q, _pre = p._overview_question(text)
    assert q == want


@pytest.mark.parametrize("text", [
    "MGNREGA figures for West Garo Hills by block", "Give me MGNREGA data for each district",
    "What is MGNREGA?", "MGNREGA",
])
def test_no_overview_for_a_breakdown_or_a_definition(text):
    assert p._overview_question(text) is None


# ── geography counts from the places master ──

@pytest.mark.parametrize("text, want", [
    ("Can you tell me how many blocks are there in Meghalaya?", ("block", None, None)),
    ("how many districts in Meghalaya", ("district", None, None)),
    ("How many villages are there in West Garo Hills?", ("village", "WEST GARO HILLS", None)),
    ("How many villages in Dalu block?", ("village", None, "DALU")),
])
def test_geography_count_questions(text, want):
    assert p._c15_geography_count(text) == want


@pytest.mark.parametrize("text", [
    "How many blocks have MGNREGA?", "How many villages have PMAY-G houses?", "which district has the most villages",
    "How many person-days in Dalu block?",
])
def test_scheme_coverage_questions_are_not_geography_counts(text):
    assert p._c15_geography_count(text) is None
