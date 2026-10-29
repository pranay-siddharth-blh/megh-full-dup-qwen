"""Misspelt / variant scheme and district names (spelling-fix brief 2026-10-29,
megh_chatbot_spelling_fix_prompt.md §4). Offline: the real app/spelling.py, the real
entity-resolver catalogue and the real pipeline matchers; no DB, no model.

The live halves (T1-T10 in one chat, made-up places, context, village typos, misspelt
knowledge questions) are tests/live_chat_spelling.py (needs the VPN).

Before app/spelling.py the live chat scored 13/25: "ribhoy" read as no place (the chat's
East Khasi Hills was answered), "fokus plus" / "fokus+" named no scheme.
"""
import random
import statistics
import time

import pytest

from app import entity_resolver as er
from app import pipeline as p
from app import scheme_registry
from app import spelling as sp
from app import topic_memory as tm

er.load_all()
sp.reload()

DISTRICTS = sp.districts()


def _reads_district(question: str) -> list[str]:
    """The districts the pipeline reads in `question` after the turn's spelling steps
    (the same chain as c14 _turn_context_stage)."""
    text = p._correct_place_spelling(p._correct_scheme_spelling(sp.normalise(question).text))
    return [d.upper() for d in er.scan_districts(text, "MGNREGA")]


def _schemes_named(question: str) -> set:
    text = p._correct_scheme_spelling(sp.normalise(question).text)
    return set(p._exact_schemes(text)) or set(p._fuzzy_named_schemes(text))


# ── B. districts: 5+ variants each ──────────────────────────────────────────
_DIR_SHORT = {"east": "e", "west": "w", "north": "n", "south": "s", "south west": "sw", "eastern west": "ew"}


def _district_variants(canon: str) -> list[str]:
    low = canon.lower()
    if low == "ri bhoi":
        return ["ribhoi", "ri-bhoi", "ribhoy", "ri bhoy", "ri boi", "rbhoi", "Ri Bhoi district", "RIBHOI"]
    words = low.split()
    k = words.index("hills")
    rng = words[k - 1]
    direction = " ".join(words[:k - 1])
    out = [
        low.replace(" ", ""),                                             # no space
        low.replace(" ", "-"),                                            # hyphen
        f"{direction} {rng[:2] + rng[3:]} hills",                         # missing letter
        f"{direction} {rng[:2] + rng[1] + rng[2:]} hills",                # extra letter
        f"{direction} {rng[0] + rng[2] + rng[1] + rng[3:]} hills",        # swapped letters
        f"{direction} {rng} hill",                                        # hill
        f"{direction} {rng} hils",                                        # hils
        f"{direction} {rng}",                                             # "hills" dropped
        f"{_DIR_SHORT[direction]} {rng} hills",                           # direction abbreviated
        f"{rng} hills {direction}",                                       # word order
    ]
    sound = rng.replace("kh", "k").replace("i", "y", 1) if "kh" in rng or "i" in rng else rng + "h"
    out.append(f"{direction} {sound} hills")                               # sound-alike
    return out


_DISTRICT_CASES = [(d, v) for d in DISTRICTS for v in _district_variants(d)]


def test_twelve_districts():
    assert len(DISTRICTS) == 12, DISTRICTS


@pytest.mark.parametrize("canon,typed", _DISTRICT_CASES)
def test_district_variant_reads_as_the_district(canon, typed):
    got = _reads_district(f"mgnrega person days in {typed} 2023-24")
    assert got == [canon.upper()], (typed, got)


@pytest.mark.parametrize("typed,canon", [
    ("ribhoy", "Ri Bhoi"), ("westgaro hills", "West Garo Hills"), ("east kasi hill", "East Khasi Hills"),
    ("east jaintiya hills", "East Jaintia Hills"), ("khasi hills east", "East Khasi Hills"),
    ("sout garo hills", "South Garo Hills"), ("south west khasi hils", "South West Khasi Hills"),
])
def test_correction_is_shown(typed, canon):
    n = sp.normalise(f"houses in {typed} 2023-24")
    assert canon in n.text
    assert n.note() == f"Showing results for **{canon}** (you typed '{typed}')."


# ── C. blocks: 30 random blocks, generated typos ────────────────────────────
def _typos(name: str, rnd: random.Random) -> list[str]:
    w = name.lower()
    i = rnd.randrange(1, len(w) - 1)
    out = [w[:i] + w[i + 1:],                                   # delete
           w[:i] + w[i] + w[i:],                                # insert (double)
           w[:i] + w[i + 1] + w[i] + w[i + 2:],                 # transpose
           w.replace(" ", "")]                                  # space removal
    for a, b in (("y", "i"), ("i", "y"), ("kh", "k"), ("w", "u"), ("ee", "i")):
        if a in w:
            out.append(w.replace(a, b, 1))                      # Khasi sound swap
            break
    return [t for t in dict.fromkeys(out) if t != w and len(t.replace(" ", "")) >= 5]


_BLOCKS = sorted({str(v["canonical"]) for v in er._catalog["MGNREGA"].get("block") or []
                  if len(str(v["canonical"]).replace(" ", "")) >= 6})
_RND = random.Random(20261029)
_BLOCK_CASES = [(b, t) for b in _RND.sample(_BLOCKS, min(30, len(_BLOCKS))) for t in _typos(b, _RND)]


def _block_reading(typed: str, scheme: str = "MGNREGA"):
    """The block the turn's chain reads: app/spelling.py on "in <typed>", then the
    resolver on what it left."""
    text = sp.normalise(f"in {typed}").text[len("in "):]
    r = er.resolve_dimension(text, scheme, "block")
    return r.status, str(r.canonical or "").upper(), [str(c.get("canonical") or c.get("name") or "").upper()
                                                       for c in r.candidates or []]


def test_block_typos_top1_or_offered():
    """>= 95% of generated block typos read as that block (top-1, or in the 'Did you
    mean' list for a name close to another block). Never a silent wrong block."""
    ok, wrong, missed = 0, [], []
    for block, typed in _BLOCK_CASES:
        status, canon, cands = _block_reading(typed)
        if (status == "resolved" and canon == block.upper()) or (status == "ambiguous" and block.upper() in cands):
            ok += 1
        elif status == "resolved":
            wrong.append((typed, block, canon))
        else:
            missed.append((typed, block, status))
    rate = ok / len(_BLOCK_CASES)
    assert not wrong, f"read as ANOTHER block: {wrong}"
    assert rate >= 0.95, f"{ok}/{len(_BLOCK_CASES)} ({rate:.0%}); missed {missed}"


# ── D. schemes: every alias, generated typos, the Focus collision ───────────
_ALIAS_CASES = [(canon, " ".join(words)) for canon, phrases in sp._aliases()["schemes"].items() for words in phrases]


@pytest.mark.parametrize("canon,alias", _ALIAS_CASES)
def test_every_scheme_alias(canon, alias):
    assert _schemes_named(f"how many beneficiaries in {alias} in 2022-23") == {canon}


@pytest.mark.parametrize("typed,canon", [
    ("fokus plus", "Focus Plus"), ("fokus+", "Focus Plus"), ("focus+", "Focus Plus"), ("focas plus", "Focus Plus"),
    ("focuss plus", "Focus Plus"), ("fokus legacy", "Focus Legacy"), ("focus legasy", "Focus Legacy"),
    ("focus lgacy", "Focus Legacy"), ("cm elivate", "CM Elevate"), ("cm elevte", "CM Elevate"),
    ("cm elivate legacy", "CM Elevate Legacy"), ("cm elevate legasy", "CM Elevate Legacy"),
    ("narega", "MGNREGA"), ("mgnerga", "MGNREGA"), ("mnrega", "MGNREGA"), ("manrega", "MGNREGA"),
    ("pmayg", "PMAY-G"), ("pmay-g", "PMAY-G"), ("awas yojana", "PMAY-G"), ("pmay gramin", "PMAY-G"),
])
def test_scheme_typo(typed, canon):
    assert _schemes_named(f"how many beneficiaries under {typed} in 2022-23") == {canon}


@pytest.mark.parametrize("q", ["how many fokus benificiaries", "focus beneficiaries in 2022-23",
                               "focas payments"])
def test_bare_focus_is_never_guessed(q):
    """A bare (or misspelt bare) "focus" names neither Focus scheme: the which-Focus
    rule asks (CLAUDE.md §4)."""
    n = sp.normalise(q)
    assert "Focus Plus" not in n.text and "Focus Legacy" not in n.text
    assert not ({"Focus Plus", "Focus Legacy"} & set(p._exact_schemes(n.text)))


def test_generic_scheme_picker_offers_all_six():
    e = p._scheme_clarification("how many records are there")
    assert [o["label"].split(" (")[0] for o in e.options] == list(scheme_registry.NAMES)


def test_scheme_picker_puts_the_typed_scheme_first():
    e = p._scheme_clarification("how many records for fokis plas")
    assert e.options[0]["label"].startswith("Focus Plus")
    assert len(e.options) == 6


@pytest.mark.parametrize("typed,want", [("who is eligble for awas yojana", "who is eligible for PMAY-G"),
                                        ("awas houses in 2023-24", "PMAY-G houses in 2023-24"),
                                        ("what is old focus skeme", "what is Focus Legacy scheme")])
def test_other_names_are_written_as_the_scheme(typed, want):
    """KI-610: the 4B guardrail refused "awas yojana" as out of scope."""
    assert sp.normalise(typed).text == want


@pytest.mark.parametrize("typed,want", [
    ("how much mony does fokus+ give per houshold", "how much money does Focus Plus give per household"),
    ("job crd how to apply", "job card how to apply"), ("mgnrega expendture", "mgnrega expenditure"),
    ("houses sanctiond", "houses sanctioned"), ("loans and grants", "loans and grants"),
    ("employ more women", "employ more women"),
])
def test_domain_words(typed, want):
    """KI-608: "mony" stayed a typo and the routing read it; another form of a word
    ("loans", "employ") is not a typo."""
    assert sp.normalise(typed).text == want


# ── C. villages: the sound reader in front of the trigram search ────────────
_FAKE_VILLAGES = {"DARONGGRE": ((101, "DADENGGRE", "WEST GARO HILLS"),),
                  "DARANGGITTIM": ((102, "BETASING", "SOUTH WEST GARO HILLS"),),
                  "MAWKAMOIT": ((103, "MYLLIEM", "EAST KHASI HILLS"),),
                  "MAWKAMIT": ((104, "PYNURSLA", "EAST KHASI HILLS"),),
                  "LUMPYLLON": ((105, "UMSNING", "RI BHOI"), (106, "JIRANG", "RI BHOI"))}


@pytest.fixture
def fake_villages(monkeypatch):
    monkeypatch.setattr(sp, "_village_sound_index", lambda: [(sp.sound_key(k), k) for k in _FAKE_VILLAGES])
    monkeypatch.setattr(er, "village_places", lambda name: _FAKE_VILLAGES.get(name, ()))
    monkeypatch.setattr(er, "_village_code_names", {})


@pytest.mark.parametrize("typed,codes", [("darongre", {101}), ("darnoggre", {101}), ("darangigttim", {102}),
                                         ("lumpllon", {105, 106}), ("lumpillon", {105, 106})])
def test_village_typo_read_by_sound(fake_villages, typed, codes):
    assert {r["village_code"] for r in er._sound_village_rows(typed, None, None)} == codes


def test_village_close_race_lists_both(fake_villages):
    """No clear winner: every close name is offered (the pick-list), best first."""
    got = er._sound_village_rows("mawkamoyt", None, None)
    assert {r["village_code"] for r in got} >= {103}
    assert er._sound_village_rows("mawkamit", None, "PYNURSLA")[0]["village_code"] == 104


def test_village_sound_respects_the_district(fake_villages):
    assert er._sound_village_rows("lumpllon", None, "JIRANG") == [
        {"village_code": 106, "lgd_village_name": "LUMPYLLON", "lgd_district": "RI BHOI", "lgd_block": "JIRANG"}]
    assert er._sound_village_rows("darongre", "RI BHOI", None) == []


def test_marked_village_typo_gets_its_real_name(fake_villages, monkeypatch):
    """Live T9 2026-10-29: read by sound in the resolver, but the SQL model still saw the
    typo and filtered the wrong view; the text now carries the clearest village's name."""
    monkeypatch.setattr(er, "is_village_name", lambda n: n.upper() in _FAKE_VILLAGES)
    n = sp.normalise("narega in darongre village 2023-24")
    assert n.text == "MGNREGA in Daronggre village 2023-24"
    assert "**Daronggre** (you typed 'darongre')" in n.note()
    # "mawkamoyt" sounds exactly like MAWKAMOIT (y = i): a clear winner
    assert "Mawkamoit village" in sp.normalise("narega in mawkamoyt village").text
    # a close race ("mawkamot": one edit from MAWKAMOIT and from MAWKAMIT) is left for
    # the resolver's pick-list
    assert "mawkamot village" in sp.normalise("narega in mawkamot village").text
    # an exact village name, and no "village" word: untouched
    assert sp.normalise("persondays in darongre 2023-24").text == "persondays in darongre 2023-24"


def test_unknown_word_is_no_village(fake_villages):
    assert er._sound_village_rows("zorbatown", None, None) == []


@pytest.mark.parametrize("q,want", [
    ("MGNREGA in Mawryngkneng village 2023-24", True),         # live T9: an overview of the village
    ("MGNREGA in Mawryngkneng village", True),
    ("MGNREGA person days in Mawryngkneng village 2023-24", False),   # names its measure
    ("MGNREGA in Mawryngkneng 2023-24", False),                # "village" not written
    ("MGNREGA in East Khasi Hills 2023-24", False),            # districts keep their path
])
def test_bare_village_ask(monkeypatch, q, want):
    monkeypatch.setattr(p, "named_places", lambda text: {"MAWRYNGKNENG": "block"} if "Mawryngkneng" in text
                        else {"EAST KHASI HILLS": "district"})
    assert p._c15_bare_village_ask(q) is want
    if want and "2023" in q:
        assert p._overview_question(q)[0] == "Compare expenditure and person-days in Mawryngkneng village in FY 2023-24"


# ── E. negatives ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("q,typed,level", [
    ("mgnrega person days in zorbatown district 2023-24", "zorbatown", "district"),
    ("mgnrega person days in gotham block 2023-24", "gotham", "block"),
])
def test_made_up_place_is_unresolved(q, typed, level):
    u = sp.unresolved_place(q)
    assert u is not None and u["typed"] == typed and u["level"] == level
    assert len(u["suggestions"]) == 3


@pytest.mark.parametrize("q", ["person days in guwahati 2023-24", "houses in assam", "data in detail",
                               "mgnrega in total for 2023-24", "how many houses in Ri Bhoi",
                               "job cards in mawkyrwat block"])
def test_not_an_unresolved_place(q):
    assert sp.unresolved_place(q) is None


@pytest.mark.parametrize("q", ["we are a self help group, suggest a suitable scheme",
                               "ribbon cutting in total", "focus on west garo hills", "e.g. total wages",
                               "robot count", "the garden scheme", "east side", "west wages", "hills total",
                               "share of women", "persons employed in 2023-24", "south facing houses"])
def test_ordinary_words_are_not_turned_into_places(q):
    n = sp.normalise(q)
    assert not [c for c in n.corrections if c.kind in ("district", "block")], n.corrections


def test_out_of_area_district_stays_out_of_scope():
    assert p._c09_out_of_area_name("Guwahati")
    assert not p._c09_out_of_area_name("Zorbatown")


def test_unknown_place_pause_suggests_closest_first():
    e = p._c13_unknown_place_pause("person days in ribhoyy district 2023-24", "ribhoyy", "district", ["MGNREGA"])
    assert e.rule == "unknown-place"
    assert "couldn't find a district called “ribhoyy”" in e.question
    assert "Did you mean Ri Bhoi" in e.question
    assert e.options[0]["label"].startswith("Ri Bhoi")
    assert e.options[-1]["label"] == "All of Meghalaya"
    assert sum(o["label"].startswith("Ri Bhoi") for o in e.options) == 1


# ── F. context ──────────────────────────────────────────────────────────────
def _topic_mem():
    return {"items": {"MGNREGA": {}, "PMAY-G": {}}, "order": ["MGNREGA", "PMAY-G"]}


@pytest.mark.parametrize("reply,picked", [
    ("MGNREGA", "MGNREGA"), ("pmay-g please", "PMAY-G"),
    ("housholds completed 100 days in east garo hils 2022-23", None),
    ("how many MGNREGA person days in West Garo Hills in 2023-24", None),
])
def test_topic_picker_short_reply_picks_long_question_does_not(reply, picked):
    opts = [{"label": k, "question": f"Go back to {k}: how many beneficiaries"} for k in ("MGNREGA", "PMAY-G")]
    assert tm._pick_reply(reply, opts, _topic_mem()) == picked


def test_chip_question_still_picks():
    opts = [{"label": k, "question": f"Go back to {k}: how many beneficiaries"} for k in ("MGNREGA", "PMAY-G")]
    assert tm._pick_reply("Go back to PMAY-G: how many beneficiaries", opts, _topic_mem()) == "PMAY-G"


def test_unresolved_place_blocks_inherited_place():
    """T4: a place the user named is never filled from the chat (c14
    _same_scheme_context_year)."""
    from types import SimpleNamespace
    state = SimpleNamespace(scheme="MGNREGA", district="EAST KHASI HILLS", block=None, village=None,
                            year=2023, year_all=False, metric=None, provenance={})
    q = "womens share in mgnrega employment in zorbaville 2023-24"
    carried = p._same_scheme_context_year(q, q, state) or {}
    assert "district" not in carried
    q2 = "womens share in mgnrega employment 2023-24"
    assert (p._same_scheme_context_year(q2, q2, state) or {}).get("district") == "EAST KHASI HILLS"


# ── H. speed ────────────────────────────────────────────────────────────────
def test_normalise_and_resolve_p95_under_150ms():
    sp.warm()                    # as app startup does (app/main.py lifespan)
    qs = [f"mgnrega person days in {t} 2023-24" for _c, t in _DISTRICT_CASES[:60]] + [
        "how many fokus plus benificiaries in 2022-23", "how much mony does fokus+ give per houshold",
        "womens share in mgnrega employmnt in ribhoy 2023-24", "person days in zorbatown district"]
    ms = []
    for q in qs:
        t0 = time.perf_counter()
        sp.normalise(q)
        sp.unresolved_place(q)
        ms.append((time.perf_counter() - t0) * 1000)
    p95 = statistics.quantiles(ms, n=20)[-1]
    assert p95 < 150, f"p95 {p95:.1f} ms"
