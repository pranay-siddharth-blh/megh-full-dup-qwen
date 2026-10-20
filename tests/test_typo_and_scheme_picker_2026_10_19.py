"""User report 2026-10-19, a new chat: "gender wise breakup the applicxations"
got "I don't have information about that; I only know Meghalaya's scheme data",
while the same question spelt right got the "which scheme?" picker.
  * the edge whitelist gate now accepts a close misspelling of a scheme word;
  * the DATA-path scheme picker offers only the schemes that record what the
    question asks for ("you should be showing only for that")."""
import pytest

from app import edge
from app import pipeline as p


@pytest.mark.parametrize("q", [
    "gender wise breakup the applicxations",
    "how many benificiaries in tura",
    "expenditre by year",
    "housholds employed",
])
def test_misspelt_scheme_word_is_not_off_topic(q):
    assert edge.detect_edge_case(q) is None


@pytest.mark.parametrize("q", [
    "what is the capital of france",
    "recommend a good movie",
    "what is the distinct meaning of love",
    "tell me about german history",
])
def test_everyday_words_near_scheme_words_stay_off_topic(q):
    hit = edge.detect_edge_case(q)
    assert hit is not None and hit["type"] in ("off_topic", "silly")


def _picked(q):
    c = p._scheme_clarification(q, by_measure=True)
    return c.question, [o["label"].split(" (")[0] for o in c.options]


def test_gender_and_applications_offer_only_the_scheme_holding_both():
    for q in ("gender wise breakup the applicxations", "gender wise breakup the applications"):
        head, schemes = _picked(q)
        assert schemes == ["Focus Plus"]
        assert head.startswith("Only Focus Plus records")


def test_one_measure_offers_its_holders():
    head, schemes = _picked("district wise applications")
    assert schemes == ["Focus Plus", "CM Elevate", "CM Elevate Legacy"]
    assert "Which one" in head
    # CM Elevate records no money
    assert "CM Elevate" not in _picked("total amount disbursed in 2024")[1]


def test_measures_no_scheme_holds_together_offer_each_holder():
    head, schemes = _picked("person days and applications by district")
    assert schemes == ["MGNREGA", "Focus Plus", "CM Elevate", "CM Elevate Legacy"]
    assert head.startswith("No single scheme")


def test_no_measure_named_keeps_all_six():
    assert len(_picked("Show beneficiaries")[1]) == 6
    # the KNOWLEDGE path never narrows: "how do I apply?" holds for every scheme
    assert len(p._scheme_clarification("district wise applications").options) == 6


# ── MGNREGA: a short per-area breakdown names every area (harness 2026-10-19) ──
_WGH_ROWS = [{"lgd_block": b, "person_days": n} for b, n in (
    ("TIKRIKILLA", 773491), ("SELSELLA", 470583), ("RONGRAM", 465415), ("DALU", 390921),
    ("DADENGGIRI", 355539), ("GAMBEGRE", 298138), ("BATABARI", 54330), ("DEMDEMA", 0))]


def test_mgnrega_breakdown_missing_blocks_gets_the_full_list():
    short = ("West Garo Hills generated 2,808,417 person-days across FY 2024-25. "
             "The highest count was 773,491 at TIKRIKILLA, while DEMDEMA recorded 0 person-days.")
    out = p._mgnrega_complete_list(short, _WGH_ROWS)
    assert out.startswith(short)
    assert "Dalu 390,921" in out and "Batabari 54,330" in out and "by block:" in out


def test_mgnrega_breakdown_already_complete_is_unchanged():
    full = " ".join(f"{r['lgd_block']} ({r['person_days']:,})" for r in _WGH_ROWS)
    assert p._mgnrega_complete_list(full, _WGH_ROWS) == full


def test_mgnrega_money_breakdown_is_left_to_the_lakh_wording():
    rows = [{"lgd_block": r["lgd_block"], "total_expenditure_lakh": 1.5} for r in _WGH_ROWS]
    assert p._mgnrega_complete_list("Tikrikilla spent most.", rows) == "Tikrikilla spent most."


def test_composer_gets_no_mean_unless_an_average_is_asked():
    rows = [{"gender": "Female", "n": 10263}, {"gender": "Male", "n": 2264}]
    text, allowed = p._result_digest(rows, with_mean=False)
    assert "mean=" not in text and "6263.5" not in allowed
    assert "mean=6,263.50" in p._result_digest(rows)[0]
    assert not p._ASKS_AVERAGE.search("gender wise breakup the applications")
    assert p._ASKS_AVERAGE.search("average beneficiaries per district")
