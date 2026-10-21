"""KI-330 (live 2026-10-19 15:03): "now give me for cm elevate" right after a CM
Elevate Legacy answer repeated the Legacy answer (2,823). The thread rule kept the
bare "CM Elevate" on Legacy; a switch fragment that names CM Elevate after a Legacy
answer means the applications dataset. Continuing questions keep the thread rule."""
import pytest

from app import pipeline as p

LEGACY = "CM Elevate Legacy"


@pytest.mark.parametrize("q", ["now give me for cm elevate", "now give me for CM Elevate", "what about cm elevate",
                               "for cm elevate", "and cm elevate?", "same for CM Elevate"])
def test_switch_fragments_in_a_legacy_thread_go_to_applications(q):
    assert p._cm_switch_to_applications(q, LEGACY)


@pytest.mark.parametrize("q", ["now give me for cm elevate legacy", "give me cm elevate disbursement by district",
                               "how much was sanctioned under cm elevate in ekh"])
def test_legacy_named_or_continuing_questions_keep_the_thread(q):
    assert not p._cm_switch_to_applications(q, LEGACY)


def test_only_a_legacy_thread_counts_as_a_switch():
    assert not p._cm_switch_to_applications("now give me for cm elevate", "CM Elevate")
    assert not p._cm_switch_to_applications("now give me for cm elevate", None)


def test_now_before_the_verb_is_a_scheme_swap():
    for q in ("now give me for mgnrega", "and give me for pmay", "now give me for cm elevate"):
        assert p._SCHEME_SWAP_FOLLOWUP.match(p._c01_strip_opening_fillers(q)), q


def test_the_swapped_question_lands_on_the_applications_dataset():
    prev = "How many CM Elevate Legacy records are there, by scheme in Meghalaya?"
    sw = p._scheme_swap_rewrite(prev, "now give me for cm elevate")
    assert "Legacy" not in sw
    pinned = p._pin_cm_elevate_dataset(sw, "CM Elevate")
    assert "CM Elevate applications" in pinned
    assert p._cm_elevate_dataset_pause(pinned) is None


# ── KI-331: the thread's year carries into a new question about the same scheme ──
from app.session_store import ConversationState  # noqa: E402


def _st(**kw):
    return ConversationState(**kw)


def test_all_years_thread_carries_into_a_same_scheme_question():
    st = _st(scheme=LEGACY, year_all=True)
    assert p._same_scheme_context_year("give me CM Elevate Legacy disbursement by district",
                                       "give me cm elevate disbursement by district", st) == {"year_all": True}


def test_a_single_year_thread_carries_its_year():
    st = _st(scheme="MGNREGA", year=2023)
    assert p._same_scheme_context_year("MGNREGA person-days by block in Dalu", "MGNREGA person-days by block in Dalu",
                                       st) == {"year_key": 2023}


@pytest.mark.parametrize("q", ["MGNREGA person-days in FY 2024-25", "MGNREGA person-days across all financial years",
                               "MGNREGA person-days year-wise", "which year had the most MGNREGA person-days",
                               "PMAY-G houses completed", "compare MGNREGA and PMAY-G spending"])
def test_own_year_other_scheme_or_several_schemes_carry_nothing(q):
    assert p._same_scheme_context_year(q, q, _st(scheme="MGNREGA", year=2023)) is None


def test_no_year_or_a_model_inferred_year_carries_nothing():
    assert p._same_scheme_context_year("MGNREGA person-days", "MGNREGA person-days", _st(scheme="MGNREGA")) is None
    st = _st(scheme="MGNREGA", year=2023)
    st.provenance = {"year": {"source": "model_inference"}}
    assert p._same_scheme_context_year("MGNREGA person-days", "MGNREGA person-days", st) is None
