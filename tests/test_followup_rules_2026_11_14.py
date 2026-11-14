"""Follow-ups that resolve by rule, so they work when every model call fails (2026-11-14, second round).

A no-model run of the gold bank (tests/accuracy/results/2026-11-14_1442_nomodel-9.json) failed 27 follow-up turns after
a passing first turn. The rules below rewrite the follow-up into the previous question changed in one way; they run in
the ctx07 loop of c14 (before any model rewrite) and in rewrite_followup's model-failed path (c01).

  _c01_measure_swap_question    "and the loan?", "and the amount?", "and how much was paid there?", "and person-days?",
                                "only the completed ones", "only rejected": the previous question with its measure
                                replaced by the one catalogue measure of that scheme the message names (metric_catalog)
  _c01_regroup_year_question    "break that down by district for 2023-24"
  _c01_one_place_of_comparison  "only Ri Bhoi" after a comparison of Ri Bhoi and East Khasi Hills
  _c01_year_only_question       "how many in 2022-23?" (the year swap, now ahead of the model)
  _comparison_swap              "Same for CM Elevate Legacy." after "Compare ... in Focus Plus and Focus Legacy." lost
                                its dangling "in"
  metric_catalog_synonyms.yaml  PMAY-G "beneficiaries" (COUNT(*), one row per beneficiary); CM Elevate Legacy "subsidy"

The catalogue is the live one's phrases (semantic.metric_definitions as read on 2026-11-14) plus the approved synonyms
file, installed in memory: no database, no model.
    .venv/Scripts/python.exe -m pytest tests/test_followup_rules_2026_11_14.py -q
"""
import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import annotations, context_frames, entity_resolver, llm  # noqa: E402
from app import metric_catalog as mc  # noqa: E402
from app import pipeline as p  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers.query import build_turn  # noqa: E402
from app.session_store import Session, Turn  # noqa: E402
from _graph_turn import graph_turn, stub_data_path  # noqa: E402


# (key, scheme, unit, catalogue phrases as semantic.metric_definitions held them on 2026-11-14, stemmed)
_CATALOGUE = [
    ('cm_elevate_applications', 'CM Elevate', 'applications', 'applicant | application'),
    ('cm_elevate_applications_by_district', 'CM Elevate', 'applications', 'application by district'),
    ('cm_elevate_applications_on_hold', 'CM Elevate', 'applications', 'application on hold | held application | on hold'),
    ('cm_elevate_applications_pending', 'CM Elevate', 'applications', 'application pending | not yet decided | pending application | under process'),
    ('cm_elevate_applications_rejected', 'CM Elevate', 'applications', 'application rejected | rejected application'),
    ('cm_elevate_applications_sent_back', 'CM Elevate', 'applications', 'application sent back | returned application | send back | sent back application'),
    ('cm_elevate_applications_valid', 'CM Elevate', 'applications', 'application verified valid | approved verification | valid application | verified application'),
    ('cm_elevate_villages_covered', 'CM Elevate', 'villages', 'coverage | village | village covered'),
    ('cm_elevate_disb_beneficiaries', 'CM Elevate Legacy', 'applicants', 'applicant sanctioned | beneficiarie | sanctioned applicant'),
    ('cm_elevate_disb_loan_disbursed', 'CM Elevate Legacy', 'rupees', 'loan disbursed | loan paid | loan released'),
    ('cm_elevate_disb_paid_beneficiaries', 'CM Elevate Legacy', 'applicants', 'applicant paid | applicant who received money | beneficiarie paid | paid beneficiarie'),
    ('cm_elevate_disb_subsidy_disbursed', 'CM Elevate Legacy', 'rupees', 'subsidy disbursed | subsidy paid | subsidy released'),
    ('cm_elevate_disb_total_disbursed', 'CM Elevate Legacy', 'rupees', 'amount | amount disbursed | disbursed | money disbursed | paid out | payout'),
    ('cm_elevate_disb_total_sanctioned', 'CM Elevate Legacy', 'rupees', 'sanctioned | sanctioned amount'),
    ('cmss_amount_disbursed', 'CMSS', 'rupees', 'amount paid | cmss amount disbursed | money disbursed | scholarship amount'),
    ('cmss_applications', 'CMSS', 'applications', 'applicant | cmss application | scholarship application | student applied'),
    ('cmss_students_paid', 'CMSS', 'students', 'beneficiarie | cmss student paid | scholarship paid | student paid'),
    ('focus_legacy_members_paid_for', 'Focus Legacy', 'member-payments', 'farmer covered | member | member covered | member paid | member paid for | pg member'),
    ('focus_legacy_payments', 'Focus Legacy', 'payments', 'grant paid | payment | payment made | remittance'),
    ('focus_legacy_pg_count', 'Focus Legacy', 'Producer Groups', 'distinct producer group paid | number of pgs | pg | pgs | pgs paid | producer group | producer group count | producer group paid'),
    ('focus_legacy_total_disbursed', 'Focus Legacy', 'rupees', 'amount | amount remitted | disbursed | money | paid out | pay out | payout | pg disbursement | remitted'),
    ('focus_plus_amount_disbursed', 'Focus Plus', 'rupees', 'amount disbursed | disbursed | money | money disbursed | paid out'),
    ('focus_plus_beneficiaries', 'Focus Plus', 'beneficiaries', 'beneficiarie | people covered'),
    ('focus_plus_payments', 'Focus Plus', 'payments', 'disbursement | disbursement made | number of payment | payment made | tranche paid | tranche payment'),
    ('focus_plus_villages_covered', 'Focus Plus', 'villages', 'coverage | village | village covered'),
    ('focus_plus_women_beneficiaries', 'Focus Plus', 'beneficiaries', 'female beneficiarie | women | women beneficiarie'),
    ('mgnrega_cost_per_person_day', 'MGNREGA', 'rupees per person-day', 'cost per person day | unit cost'),
    ('mgnrega_employment_generated', 'MGNREGA', 'person-days', 'employment generated | employment provided | manday | person day | personday | work generated'),
    ('mgnrega_households_100_days', 'MGNREGA', 'households', '100 day completed | full 100 day | household completing 100 day | household with 100 day'),
    ('mgnrega_households_employed', 'MGNREGA', 'households', 'familie given work | household employed | household got work | household provided employment | household received employment'),
    ('mgnrega_job_card_stock', 'MGNREGA', 'job cards', 'job card | job card stock | registered household'),
    ('mgnrega_material_expenditure', 'MGNREGA', 'lakh rupees', 'material cost | material expenditure | spending on material'),
    ('mgnrega_persons_employed', 'MGNREGA', 'persons', 'people given work | person employed | worker'),
    ('mgnrega_total_expenditure', 'MGNREGA', 'lakh rupees', 'expenditure | money spent | outlay | spend'),
    ('mgnrega_villages_covered', 'MGNREGA', 'villages', 'coverage | village | village covered'),
    ('mgnrega_wage_share_compliance', 'MGNREGA', 'percent', '60 40 ratio | wage material ratio | wage share | wage share compliance'),
    ('pmay_amount_pending', 'PMAY-G', 'rupees', 'amount still to be released | amount yet to be released | balance due | fund pending | pending amount'),
    ('pmay_amount_released', 'PMAY-G', 'rupees', 'amount disbursed | amount released | released amount'),
    ('pmay_amount_sanctioned', 'PMAY-G', 'rupees', 'amount sanctioned | sanctioned amount | subsidy sanctioned'),
    ('pmay_completion_rate', 'PMAY-G', 'percent', 'completion rate | house completed'),
    ('pmay_houses_completed', 'PMAY-G', 'houses', 'completed house | house built | house completed'),
    ('pmay_houses_in_progress', 'PMAY-G', 'houses', 'house in progress | house under construction | incomplete house'),
    ('pmay_houses_sanctioned', 'PMAY-G', 'houses', 'house | house sanctioned | sanction'),
    ('pmay_villages_covered', 'PMAY-G', 'villages', 'coverage | village | village covered'),
]


@pytest.fixture(scope="module", autouse=True)
def _loaded():
    entity_resolver.load_all()
    annotations.load_all()


@pytest.fixture
def catalogue(monkeypatch):
    approved = mc._load_approved_synonyms()               # the real file, with this round's additions
    metrics = {}
    for key, scheme, unit, phrases in _CATALOGUE:
        ps = {tuple(x.split()) for x in phrases.split(" | ")} | {mc._phrase(w) for w in approved.get(key, [])}
        metrics[key] = mc.Metric(key=key, scheme=scheme, display_name=key, expression="COUNT(*)",
                                 base_object="v", unit=unit, notes="", alias=key,
                                 phrases=tuple(sorted(x for x in ps if x)), columns=frozenset())
    state = {"metrics": metrics, "by_scheme": {}, "loaded": True, "no_block_level": frozenset(),
             "single_year": frozenset(), "verified": {t: {} for t in mc.QUERY_TYPES}}
    for m in metrics.values():
        state["by_scheme"].setdefault(m.scheme, []).append(m)
    monkeypatch.setattr(mc, "_state", state)
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "on")
    return state


def _prev(question, schemes, resolved=None, route="data"):
    return Turn(question=question, raw_question=question, route=route, schemes=list(schemes),
                resolved_entities=dict(resolved or {}), answer="x")


CML_SUB_BY_D = _prev("CM Elevate Legacy subsidy disbursed by district", ["CM Elevate Legacy"])
CML_SUB_WGH = _prev("CM Elevate Legacy subsidy disbursed in West Garo Hills", ["CM Elevate Legacy"],
                    {"district": "WEST GARO HILLS"})
FP_BEN_BY_D = _prev("Focus Plus beneficiaries by district", ["Focus Plus"])
FP_BEN_RB = _prev("How many Focus Plus beneficiaries are there in Ri Bhoi?", ["Focus Plus"], {"district": "RI BHOI"})
FL_PG_WGH = _prev("Focus Legacy producer groups in West Garo Hills", ["Focus Legacy"], {"district": "WEST GARO HILLS"})
FL_AMT_BY_D = _prev("Focus Legacy amount by district", ["Focus Legacy"])
MG_EXP_GAMB = _prev("MGNREGA expenditure in Gambegre block in 2022-23", ["MGNREGA"],
                    {"district": "WEST GARO HILLS", "block": "GAMBEGRE", "year_key": 2022})
MG_PD_STATE = _prev("Total MGNREGA person-days statewide in FY 2023-24", ["MGNREGA"], {"year_key": 2023})
MG_EXP_YEARS = _prev("What was MGNREGA expenditure in each financial year?", ["MGNREGA"])
PM_HOUSES_BY_D = _prev("Tell me about PMAY-G houses by district.", ["PMAY-G"])
PM_SANC_BY_FY = _prev("PMAY-G houses sanctioned in each financial year", ["PMAY-G"])
PM_REL_BY_D = _prev("PMAY-G amount released by district", ["PMAY-G"])
CME_APPS_BY_D = _prev("CM Elevate applications by district", ["CM Elevate"])
CROSS = _prev("Compare MGNREGA and PMAY-G beneficiaries", ["MGNREGA", "PMAY-G"])


# ── another measure of the same question ─────────────────────────────────────

@pytest.mark.parametrize("msg,prev,want", [
    ("and the loan?", CML_SUB_BY_D, "CM Elevate Legacy loan disbursed by district"),
    ("and the loan?", CML_SUB_WGH, "CM Elevate Legacy loan disbursed in West Garo Hills"),
    ("and the amount?", FP_BEN_BY_D, "Focus Plus amount disbursed by district"),
    ("and the amount disbursed there?", _prev("Focus Plus beneficiaries in Ri Bhoi", ["Focus Plus"],
                                              {"district": "RI BHOI"}), "Focus Plus amount disbursed in Ri Bhoi"),
    ("and the amount?", FL_PG_WGH, "Focus Legacy amount in West Garo Hills"),
    # a count asked again as money: "How many ... are there" -> "How much ..."
    ("and how much was paid there?", FP_BEN_RB, "How much Focus Plus paid out in Ri Bhoi"),
    ("and person-days?", MG_EXP_GAMB, "MGNREGA person days in Gambegre block in 2022-23"),
    ("and person-days?", MG_EXP_YEARS, "What was MGNREGA person days in each financial year"),
    ("same for person-days", MG_EXP_GAMB, "MGNREGA person days in Gambegre block in 2022-23"),
    ("what about the money instead", MG_PD_STATE, "Total MGNREGA money spent statewide in FY 2023-24"),
    ("how much money was spent on that", MG_PD_STATE, "Total MGNREGA money spent statewide in FY 2023-24"),
    ("and households?", MG_PD_STATE, "Total MGNREGA households statewide in FY 2023-24"),
    ("and the subsidy?", _prev("CM Elevate Legacy loan disbursed in Ri Bhoi", ["CM Elevate Legacy"],
                               {"district": "RI BHOI"}), "CM Elevate Legacy subsidy in Ri Bhoi"),
    # a chart asked with the previous question stays
    ("and the loan?", _prev("CM Elevate Legacy subsidy disbursed by district as a bar chart", ["CM Elevate Legacy"]),
     "CM Elevate Legacy loan disbursed by district as a bar chart"),
])
def test_another_measure_of_the_same_question(catalogue, msg, prev, want):
    assert p._c01_measure_swap_question(msg, prev) == want


@pytest.mark.parametrize("msg,prev,want", [
    ("Only the completed ones.", PM_HOUSES_BY_D, "Tell me about PMAY-G houses completed by district"),
    ("only the completed ones", PM_SANC_BY_FY, "PMAY-G houses completed in each financial year"),
    ("just the completed houses", PM_SANC_BY_FY, "PMAY-G completed houses in each financial year"),
    ("only rejected", CME_APPS_BY_D, "CM Elevate applications rejected by district"),
    ("only the pending ones", CME_APPS_BY_D, "CM Elevate applications pending by district"),
])
def test_a_status_filter_is_the_measure_of_that_status(catalogue, msg, prev, want):
    assert p._c01_measure_swap_question(msg, prev) == want


@pytest.mark.parametrize("msg,prev", [
    # NEW questions: they name their own scheme (and measure) -> never rewritten
    ("How many PMAY-G houses were completed in Ri Bhoi?", PM_HOUSES_BY_D),
    ("MGNREGA person-days in 2023-24", MG_EXP_GAMB),
    ("Focus Plus amount disbursed", FP_BEN_BY_D),
    ("and Focus Legacy amount?", FP_BEN_BY_D),
    ("What is the total CM Elevate Legacy loan disbursed?", CML_SUB_BY_D),
    # what a measure IS / how it works
    ("what is person days?", MG_EXP_GAMB),
    ("how is the loan disbursed?", CML_SUB_BY_D),
    ("explain the subsidy", _prev("CM Elevate Legacy loan disbursed in Ri Bhoi", ["CM Elevate Legacy"])),
    # a word that names more than one measure of the scheme: not guessed
    ("and the amount?", _prev("PMAY-G houses in Ri Bhoi", ["PMAY-G"], {"district": "RI BHOI"})),
    # a filter that does not keep the previous measure's noun
    ("only the completed ones", PM_REL_BY_D),
    # the same measure again: nothing to change
    ("and the amount?", FL_AMT_BY_D),
    # more than a measure: a year, a grouping, a ranking, a place, a value
    ("and the amount in 2023-24?", FP_BEN_BY_D),
    ("and the amount by block", FP_BEN_BY_D),
    ("which district has the most amount?", FP_BEN_BY_D),
    ("and the amount in Ri Bhoi?", FP_BEN_BY_D),
    ("just the ones above 1000", PM_HOUSES_BY_D),
    ("compare the amount", FP_BEN_BY_D),
    # a measure the scheme does not hold (the measure-not-held pause's)
    ("and person-days?", PM_HOUSES_BY_D),
    # words that are no measure
    ("thanks", FP_BEN_BY_D), ("ok", FP_BEN_BY_D), ("why?", FP_BEN_BY_D),
])
def test_what_the_measure_rule_leaves_alone(catalogue, msg, prev):
    assert p._c01_measure_swap_question(msg, prev) is None


def test_the_measure_rule_needs_one_scheme_a_data_answer_and_the_catalogue(catalogue, monkeypatch):
    assert p._c01_measure_swap_question("and the amount?", CROSS) is None
    knowledge = _prev("What is Focus Plus?", ["Focus Plus"], route="knowledge")
    assert p._c01_measure_swap_question("and the amount?", knowledge) is None
    monkeypatch.setattr(settings, "METRIC_CATALOG_MODE", "off")
    assert p._c01_measure_swap_question("and the amount?", FP_BEN_BY_D) is None


def test_the_rewrite_reads_as_the_new_measure(catalogue):
    out = p._c01_measure_swap_question("and the loan?", CML_SUB_BY_D)
    assert mc.match(out, "CM Elevate Legacy").metric.key == "cm_elevate_disb_loan_disbursed"
    out = p._c01_measure_swap_question("only the completed ones", PM_SANC_BY_FY)
    assert mc.match(out, "PMAY-G").metric.key == "pmay_houses_completed"


# ── the approved synonyms of this round ──────────────────────────────────────

def test_pmay_beneficiaries_are_houses_sanctioned(catalogue):
    assert mc.match("PMAY-G beneficiaries?", "PMAY-G").metric.key == "pmay_houses_sanctioned"
    assert mc.match("How many PMAY beneficiaries are there in West Garo Hills?", "PMAY-G").metric.key == \
        "pmay_houses_sanctioned"


def test_cm_elevate_legacy_subsidy_is_the_subsidy_disbursed(catalogue):
    assert mc.match("CM Elevate Legacy subsidy in South Garo Hills?", "CM Elevate Legacy").metric.key == \
        "cm_elevate_disb_subsidy_disbursed"
    assert mc.match("How much CM Elevate Legacy subsidy was disbursed in Ri Bhoi?", "CM Elevate Legacy").metric.key \
        == "cm_elevate_disb_subsidy_disbursed"
    assert mc.match("CM Elevate Legacy subsidy sanctioned", "CM Elevate Legacy").metric is None    # two measures


# ── a regroup and a year in one message ──────────────────────────────────────

MG_EXP_BY_FY = _prev("Total MGNREGA expenditure statewide by financial year", ["MGNREGA"])
IN_WGH = _prev("MGNREGA expenditure in West Garo Hills", ["MGNREGA"], {"district": "WEST GARO HILLS"})
IN_2022 = _prev("How many MGNREGA person-days were generated in 2022-23?", ["MGNREGA"], {"year_key": 2022})


@pytest.mark.parametrize("msg,prev,want", [
    ("break that down by district for 2023-24", MG_EXP_BY_FY,
     "Total MGNREGA expenditure statewide by district in FY 2023-24"),
    ("block wise for FY 2024-25", IN_WGH, "MGNREGA expenditure in West Garo Hills by block in FY 2024-25"),
    # the previous question's own year is replaced, where it stands
    ("break it down by district in 2023-24", IN_2022,
     "How many MGNREGA person-days were generated in FY 2023-24 by district"),
])
def test_a_regroup_with_a_year(msg, prev, want):
    assert p._c01_regroup_year_question(msg, prev) == want


@pytest.mark.parametrize("msg,prev", [
    ("break it down by financial year for 2023-24", IN_WGH),       # a year grouping with a year
    ("by district for 2022-23 and 2023-24", MG_EXP_BY_FY),         # two years
    ("break that down by district", MG_EXP_BY_FY),                 # no year: the plain regroup's
    ("by district for PMAY-G in 2023-24", MG_EXP_BY_FY),           # a scheme of its own
    ("by district for 2023-24", CROSS.__class__(question="What is PMAY-G?", raw_question="What is PMAY-G?",
                                                route="knowledge", schemes=["PMAY-G"])),
])
def test_what_the_regroup_year_rule_leaves_alone(msg, prev):
    assert p._c01_regroup_year_question(msg, prev) is None


# ── one year, ahead of the model ─────────────────────────────────────────────

def test_how_many_in_a_year_is_the_previous_question_for_that_year():
    prev = _prev("PMAY-G houses sanctioned in South West Khasi Hills", ["PMAY-G"], {"district": "SOUTH WEST KHASI HILLS"})
    assert p._c01_year_only_question("how many in 2022-23?", prev) == \
        "PMAY-G houses sanctioned in South West Khasi Hills in FY 2022-23"
    assert p._c01_year_only_question("and the year before?", IN_2022) == \
        "How many MGNREGA person-days were generated in FY 2021-22"


@pytest.mark.parametrize("msg,prev", [
    ("and in 2023-24?", MG_EXP_YEARS),                              # one year of a per-year list: not a swap
    ("compare with last year", IN_2022),
    ("and person-days in 2023-24?", MG_EXP_GAMB),                   # a measure too
    ("in 2023-24", _prev("What is PMAY-G?", ["PMAY-G"], route="knowledge")),
])
def test_what_the_year_rule_leaves_alone(msg, prev):
    assert p._c01_year_only_question(msg, prev) is None


# ── one place of a comparison of places ─────────────────────────────────────

CMP_2 = _prev("Compare MGNREGA households employed in Ri Bhoi and East Khasi Hills in 2023-24", ["MGNREGA"],
              {"district_list": ["RI BHOI", "EAST KHASI HILLS"], "year_key": 2023})
CMP_BLOCKS = _prev("Compare PMAY-G houses in Dalu and Tikrikilla blocks", ["PMAY-G"],
                   {"block_list": ["DALU", "TIKRIKILLA"]})


@pytest.mark.parametrize("msg,prev,want", [
    ("only Ri Bhoi", CMP_2, "MGNREGA households employed in Ri Bhoi in 2023-24"),
    ("just East Khasi Hills", CMP_2, "MGNREGA households employed in East Khasi Hills in 2023-24"),
    ("only Dalu", CMP_BLOCKS, "PMAY-G houses in Dalu"),
])
def test_one_place_of_a_comparison(msg, prev, want):
    assert p._c01_one_place_of_comparison(msg, prev) == want


@pytest.mark.parametrize("msg,prev", [
    ("only West Garo Hills", CMP_2),                                # not one of the places compared
    ("Ri Bhoi", CMP_2),                                             # no "only": a pause reply or a swap
    ("only Ri Bhoi", _prev("PMAY-G houses completed by district", ["PMAY-G"])),   # the grouped rule's
    ("only Ri Bhoi", _prev("MGNREGA expenditure in Ri Bhoi", ["MGNREGA"], {"district": "RI BHOI"})),
])
def test_what_the_one_place_rule_leaves_alone(msg, prev):
    assert p._c01_one_place_of_comparison(msg, prev) is None


# ── the comparison swap's dangling preposition ───────────────────────────────

def test_a_comparison_that_ends_with_its_list_leaves_no_dangling_preposition():
    out = p._scheme_swap_rewrite("Compare the number of beneficiaries in Focus Plus and Focus Legacy.",
                                 "Same for CM Elevate Legacy.")
    assert out == "Same comparison for CM Elevate Legacy: the number of beneficiaries."
    # a list in the middle: the scope after it stays, the list's own preposition is not doubled
    out = p._scheme_swap_rewrite("Compare beneficiaries in MGNREGA and PMAY-G in Ri Bhoi", "same for Focus Plus")
    assert out == "Same comparison for Focus Plus: beneficiaries in Ri Bhoi"     # was "beneficiaries in in Ri Bhoi"
    out = p._scheme_swap_rewrite("Compare MGNREGA and PMAY-G beneficiaries in Ri Bhoi", "same for Focus Plus")
    assert out == "Same comparison for Focus Plus: beneficiaries in Ri Bhoi"


# ── context_frames.check accepts every rewrite ───────────────────────────────

def _base(prev):
    """The frame context_frames keeps for a turn (its "by" = the place levels the question asks)."""
    from app import context_policy
    return {"id": 1, "q": prev.question, "route": "data", "schemes": list(prev.schemes),
            "by": list(context_policy.asked_levels(prev.question)), "place": {}, "years": []}


@pytest.mark.parametrize("msg,prev", [
    ("and the loan?", CML_SUB_BY_D),
    ("and the amount?", FL_PG_WGH),
    ("only the completed ones", PM_SANC_BY_FY),
    ("and person-days?", MG_EXP_GAMB),
    ("and how much was paid there?", FP_BEN_RB),
])
def test_the_frames_check_accepts_a_measure_swap(catalogue, msg, prev):
    out = p._c01_measure_swap_question(msg, prev)
    base = _base(prev)
    assert context_frames.check(out, msg, base) is None, out


def test_the_frames_check_accepts_the_other_rewrites():
    base = _base(CMP_2)
    assert context_frames.check(p._c01_one_place_of_comparison("only Ri Bhoi", CMP_2), "only Ri Bhoi", base) is None
    base = _base(MG_EXP_BY_FY)
    msg = "break that down by district for 2023-24"
    assert context_frames.check(p._c01_regroup_year_question(msg, MG_EXP_BY_FY), msg, base) is None


# ── through the graph, the model unreachable ─────────────────────────────────

@pytest.fixture
def chat(monkeypatch, catalogue):
    for flag in ("CONTEXT_LAYER_ENABLED", "CONTEXT_STATE_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    seen, resolved = [], {}

    async def data(question, scope=None, **kw):
        seen.append(question)
        return {"route": "data", "intent": "DATA", "schemes": [resolved["scheme"]], "sql": "SELECT 1",
                "resolved_entities": dict(resolved["entities"]), "rows": [{"n": 1}], "data": [{"n": 1}],
                "row_count": 1, "answer": "answer."}
    stub_data_path(monkeypatch, data)

    async def no_model(*a, **k):
        raise RuntimeError("no model offline")
    monkeypatch.setattr(llm, "call_rewriter", no_model)
    s = Session(session_id=f"rules-{time.time()}", user_id="u", created=time.time(), last_seen=time.time())

    def ask(q, scheme, entities=None):
        resolved.update(scheme=scheme, entities=entities or {})
        n = len(seen)
        out = asyncio.run(graph_turn(q, session=s))
        s.turns.append(build_turn(q, out))
        return seen[-1] if len(seen) > n else None
    return ask


def test_a_measure_change_and_a_filter_through_the_graph(chat):
    chat("CM Elevate Legacy subsidy disbursed by district", "CM Elevate Legacy")
    assert chat("and the loan?", "CM Elevate Legacy") == "CM Elevate Legacy loan disbursed by district"
    chat("PMAY-G houses sanctioned in each financial year", "PMAY-G")
    assert chat("only the completed ones", "PMAY-G") == "PMAY-G houses completed in each financial year"


def test_one_place_of_a_comparison_through_the_graph(chat):
    chat("Compare MGNREGA households employed in Ri Bhoi and East Khasi Hills in 2023-24", "MGNREGA",
         {"district_list": ["RI BHOI", "EAST KHASI HILLS"], "year_key": 2023})
    assert chat("only Ri Bhoi", "MGNREGA", {"district": "RI BHOI", "year_key": 2023}) == \
        "MGNREGA households employed in Ri Bhoi in 2023-24"


def test_a_regroup_with_a_year_and_a_year_alone_through_the_graph(chat):
    chat("Total MGNREGA expenditure statewide by financial year", "MGNREGA")
    assert chat("break that down by district for 2023-24", "MGNREGA", {"year_key": 2023}) == \
        "Total MGNREGA expenditure statewide by district in FY 2023-24"
    chat("PMAY-G houses sanctioned in South West Khasi Hills", "PMAY-G", {"district": "SOUTH WEST KHASI HILLS"})
    assert chat("how many in 2022-23?", "PMAY-G", {"district": "SOUTH WEST KHASI HILLS", "year_key": 2022}) == \
        "PMAY-G houses sanctioned in South West Khasi Hills in FY 2022-23"


# ── the voice shaper's canonical wordings (the voice screen sends exactly these) ──

CANON_PM_RB = _prev("How many PMAY-G houses were sanctioned in Ri Bhoi?", ["PMAY-G"], {"district": "RI BHOI"})
CANON_FL_WGH = _prev("Focus Legacy amount disbursed in West Garo Hills", ["Focus Legacy"],
                     {"district": "WEST GARO HILLS"})


@pytest.mark.parametrize("msg,prev,want", [
    ("what about the amount released instead", CANON_PM_RB, "How much PMAY-G amount released in Ri Bhoi"),
    ("what about the households instead", MG_PD_STATE, "Total MGNREGA households statewide in FY 2023-24"),
    ("what about the members instead", CANON_FL_WGH, "Focus Legacy members in West Garo Hills"),
    ("only the completed ones", PM_HOUSES_BY_D, "Tell me about PMAY-G houses completed by district"),
    ("only the incomplete ones", PM_HOUSES_BY_D, "Tell me about PMAY-G incomplete houses by district"),
])
def test_canonical_measure_and_value_wordings(catalogue, msg, prev, want):
    assert p._c01_measure_swap_question(msg, prev) == want


def test_canonical_only_a_scheme_of_a_comparison():
    out = p._c14_one_scheme_of_comparison("only PMAY-G", CROSS)
    assert out == "PMAY-G beneficiaries?"


@pytest.mark.parametrize("msg,want", [
    ("what about Ri Bhoi?", "How many PMAY-G houses were sanctioned in Ri Bhoi in FY 2023-24?"),
    ("what about Mawphlang block?", "How many PMAY-G houses were sanctioned in Mawphlang block, East Khasi Hills "
                                    "in FY 2023-24?"),
])
def test_canonical_place_wordings_when_the_model_is_down(msg, want):
    prev = _prev("How many PMAY-G houses were sanctioned in West Garo Hills in FY 2023-24?", ["PMAY-G"],
                 {"district": "WEST GARO HILLS", "year_key": 2023})
    # D-056: a district swap is the model rewrite's while it answers; when its call fails, the deterministic swap
    assert p._place_swap_rewrite(prev, msg, force=True, district=True) == want


@pytest.mark.parametrize("msg,want", [
    ("what about 2022-23?", "How many MGNREGA person-days were generated in FY 2022-23"),
    ("what about the year before?", "How many MGNREGA person-days were generated in FY 2021-22"),
    ("what about the year after?", "How many MGNREGA person-days were generated in FY 2023-24"),
])
def test_canonical_year_wordings(msg, want):
    assert p._c01_year_only_question(msg, IN_2022) == want


PM_BY_BLOCK = _prev("PMAY-G houses by block in East Khasi Hills", ["PMAY-G"], {"district": "EAST KHASI HILLS"})


@pytest.mark.parametrize("msg,prev,want", [
    ("which is the lowest", FL_AMT_BY_D, "Which district has the lowest: Focus Legacy amount"),
    ("top 3", FL_AMT_BY_D, "Top 3 districts: Focus Legacy amount"),
    ("bottom 2 blocks", PM_BY_BLOCK, "Bottom 2 blocks: PMAY-G houses in East Khasi Hills"),
])
def test_canonical_rank_wordings(msg, prev, want):
    assert p._c01_rank_question(msg, prev) == want


@pytest.mark.parametrize("msg,prev,want", [
    ("only Ri Bhoi", _prev("PMAY-G houses completed by district", ["PMAY-G"]), "PMAY-G houses completed in Ri Bhoi"),
    ("only Mawphlang block", _prev("MGNREGA expenditure by block in 2024-25", ["MGNREGA"], {"year_key": 2024}),
     "MGNREGA expenditure in 2024-25 in Mawphlang block"),
])
def test_canonical_only_place_wordings(msg, prev, want):
    assert p._c01_only_place_question(msg, prev) == want
