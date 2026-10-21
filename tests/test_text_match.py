"""app/text_match.py — the word-level matcher every English-text check uses (D-047)."""
from app.text_match import (ANY, END, START, Alt, Cap, Gap, Joined, Matcher, NotAfter, NotBefore, Opt, Pred,
                            Seq, W, collapse_ws, fy_spans, is_year, numbers, split_sentences)


def test_words_are_whole_words():
    m = Matcher(Alt(W("cover", "covers", "covered"), "widest"))
    assert m("which scheme has the widest reach") and not m("discover")


def test_prefix_stem_and_sub():
    assert Matcher(W("disburs", prefix=True)).sub("X", "amount disbursed, disbursement") == "amount X, X"


def test_not_before_and_not_after():
    state = Matcher(Seq(Alt("for", "in"), "the", Opt(Alt("whole", "entire")), NotBefore(W("state"), "of")))
    assert state.search("for the entire state please").group() == "for the entire state"
    assert state.search("for the state of Meghalaya") is None
    assert Matcher(NotAfter(W("focus"), Alt("legacy", "old"))).search("old focus or focus plus").start() == 13


def test_gap_joined_and_anchors():
    assert Matcher(Seq("which", Gap(3), W("scheme", "schemes"))).search("which welfare scheme").group() \
        == "which welfare scheme"
    found = [h.group() for h in Matcher(Joined("job", ("card", "cards"))).finditer("job cards, job-card, jobcards")]
    assert found == ["job cards", "job-card", "jobcards"]
    assert Matcher(START, Alt("yes", "ok")).search("  Ok go").group() == "Ok"
    assert Matcher(START, "yes").search("say yes") is None
    assert Matcher("thanks", END).search("ok thanks!") is not None


def test_captures_and_findall():
    yr = Matcher(Seq(Opt("fy"), Cap(Pred(is_year))))
    h = yr.search("data for FY 2023 only")
    assert (h.group(), h.group(1)) == ("FY 2023", "2023")
    assert Matcher(Cap(ANY), "vs", Cap(ANY)).findall("a vs b, c vs d") == [("a", "b"), ("c", "d")]


def test_separator_control():
    assert Matcher(Seq("how", "many", sep="space")).search("how, many") is None
    assert Matcher(Seq("how", "many")).search("how, many") is not None


def test_character_helpers():
    assert collapse_ws("  a \n b ") == "a b"
    assert numbers("1,23,456 and 3.5, 2023.") == ["1,23,456", "3.5", "2023"]
    assert [x[2:] for x in fy_spans("FY 2023-24, 2022/2023 and fy2021-22")] == [(2023, 24), (2022, 23), (2021, 22)]
    assert split_sentences("It is 5. Next one! ok. Then 5 crore.") == ["It is 5.", "Next one! ok.", "Then 5 crore."]
