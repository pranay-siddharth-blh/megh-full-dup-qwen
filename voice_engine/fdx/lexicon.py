"""Names the recogniser does not know, snapped to the ones Mitra does (4 Nov 2026, first runs on the real Kyutai STT).

Kyutai STT 1B has no custom vocabulary: "Hunsur" comes back as "Huntser", and the brain then answers for the whole state.
Gemini has the same weakness. Here a word the recogniser CAPITALISED in mid-sentence (it writes proper nouns that way)
that is not already a known name is compared, by a rough phonetic key, with every taluk, district, gram panchayat and
village in the POC copy's gazetteer (read only), and replaced only when one name wins clearly. Two capitalised words in a
row are also tried as one name ("Chikka Ballapura"). Common words are never touched, and a sentence's first word only
when it is not an ordinary word.

  correct(text) -> (fixed_text, [(heard, name), ...])"""
from __future__ import annotations

import difflib
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "stack" / "app" / "data" / "sakala.db"
MIN_RATIO = 0.78          # how alike the keys must be
MARGIN = 0.08             # how far ahead of the next name the winner must be
KIND_RANK = {"taluk": 0, "district": 1, "gp": 2, "village": 3}   # a tie goes to the bigger place
# capitalised words that are never place names (titles, profile words, the start of a sentence)
COMMON = {"i", "case", "cases", "madam", "sir", "mitra", "hey", "hi", "hello", "what", "how", "which", "where", "who",
          "when", "why", "is", "are", "the", "show", "tell", "give", "please", "okay", "ok", "yes", "no", "chief",
          "secretary", "officer", "citizen", "tahsildar", "pdo", "district", "taluk", "karnataka", "india", "english",
          "kannada", "rdpr", "revenue", "food", "gr", "sakala", "ipgrs", "can", "could", "do", "does", "list", "compare"}
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_RULES = [("ph", "f"), ("th", "t"), ("ts", "s"), ("tz", "s"), ("dz", "s"), ("sh", "s"), ("ch", "c"), ("ck", "k"),
          ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("w", "v"), ("z", "s"), ("q", "k"), ("x", "ks"),
          ("ee", "i"), ("ii", "i"), ("oo", "u"), ("uu", "u"), ("aa", "a"), ("y", "i"), ("c", "k")]


def key(s: str) -> str:
    """A rough phonetic key: lower case, letters only, common spelling variants folded, doubled letters collapsed."""
    k = re.sub(r"[^a-z]", "", s.lower())
    for a, b in _RULES:
        k = k.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", k)


@lru_cache(maxsize=1)
def names() -> dict[str, tuple[str, str]]:
    """key -> (name, kind) for every place in the gazetteer; the bigger place wins a shared key."""
    out: dict[str, tuple[str, str]] = {}
    try:
        c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        for kind in ("village", "gp", "taluk", "district"):              # bigger places last, so they win a shared key
            for (n,) in c.execute(f"SELECT DISTINCT {kind} FROM gazetteer WHERE {kind} IS NOT NULL AND {kind} != ''"):
                n = str(n).strip()
                if n:
                    out[key(n)] = (n.title() if n.isupper() else n, kind)
    finally:
        c.close()
    out[key("Karnataka")] = ("Karnataka", "state")   # the whole state ("how is Karnataka doing": the CS's first question)
    return out


_DASH_SLOT = re.compile(r"\bhow(?:'s| is| are| has)\s+(.{3,30}?)\s+(doing|performing|faring|placed|looking)\b", re.I)


def dash_slot(text: str) -> tuple[str, list[tuple[str, str]]]:
    """"How is X doing": X is a place (or the state). "How is carne taca doing?" -> Karnataka (4 Nov, the real STT on the
    atlas listen_sound question). Matched on the key among the state, districts and taluks; one clear winner only."""
    m = _DASH_SLOT.search(text or "")
    if not m or not names():
        return text, []
    x = m.group(1).strip(" ,")
    if key(x) in names() or len(key(x)) < 5:
        return text, []
    table = {k: n for k, (n, kd) in names().items() if kd in ("state", "district", "taluk")}
    kx = key(x)
    scored = sorted(((difflib.SequenceMatcher(None, kx, k).ratio(), n) for k, n in table.items() if k[:1] == kx[:1]), reverse=True)
    if scored and scored[0][0] >= 0.8 and (len(scored) < 2 or scored[0][0] - scored[1][0] >= 0.08):
        return text[:m.start(1)] + scored[0][1] + text[m.end(1):], [(x, scored[0][1])]
    return text, []


def _best(word: str) -> tuple[str, str] | None:
    k = key(word)
    if len(k) < 4:
        return None
    table = names()
    if k in table:
        return table[k]
    scored = []
    for nk, (n, kind) in table.items():
        if abs(len(nk) - len(k)) > 3 or nk[:1] != k[:1]:                # same first sound, similar length
            continue
        r = difflib.SequenceMatcher(None, k, nk).ratio()
        if r >= MIN_RATIO - MARGIN:
            scored.append((r, -KIND_RANK.get(kind, 9), n, kind))
    if not scored:
        return None
    scored.sort(reverse=True)
    top = scored[0]
    if top[0] < MIN_RATIO:
        return None
    if len(scored) > 1 and top[0] - scored[1][0] < MARGIN and scored[1][2] != top[2]:
        return None                                                     # two names too close to call: leave it
    return top[2], top[3]


# case ids as the recogniser writes them: "GR504210", "G R 504210", "G.R. 5 0 4 2 1 0", "gr-504210" -> "GR-504210";
# Sakala application numbers "SK RD855S 260004811" -> "SK-RD855S260004811". The brain matches the canonical form only
# (4 Nov: "status of Case GR504210?" arrived whole and the wrong case was read).
_GR = re.compile(r"\b[Gg]\.?\s*[Rr]\.?\s*-?\s*((?:\d\s*){5}\d)(?!\d)")
_SK = re.compile(r"\b[Ss]\.?\s*[Kk]\.?\s*-?\s*([A-Za-z]{2}\s*\d{3}\s*[A-Za-z])\s*((?:\d\s*){8,9}\d)(?!\d)")


def ids(text: str) -> tuple[str, list[tuple[str, str]]]:
    fixes: list[tuple[str, str]] = []

    def gr(m):
        v = "GR-" + re.sub(r"\s", "", m.group(1))
        if m.group(0) != v:
            fixes.append((m.group(0).strip(), v))
        return v

    def sk(m):
        v = "SK-" + re.sub(r"\s", "", m.group(1)).upper() + re.sub(r"\s", "", m.group(2))
        if m.group(0) != v:
            fixes.append((m.group(0).strip(), v))
        return v
    text = _GR.sub(gr, text)
    text = _SK.sub(sk, text)
    return text, fixes


def skeleton(s: str) -> str:
    """Consonants only (after the key's folding): "my sewer" -> msvr, "Mysuru" -> msr; a recogniser keeps them better
    than vowels when it turns a name into everyday words."""
    return re.sub(r"[aeiou]", "", key(s))


_SLOT = re.compile(r"\b((?:[A-Za-z]+\s+){0,1}[A-Za-z]+)\s+(district|taluk)\b", re.I)


def place_slot(text: str) -> tuple[str, list[tuple[str, str]]]:
    """The words right before "district" / "taluk" are a place: "How is my sewer district doing?" -> Mysuru district.
    Matched among the districts (or taluks) only, on the consonant skeleton, and only when one name wins clearly."""
    fixes: list[tuple[str, str]] = []
    if not names():
        return text, fixes

    def rep(m):
        words, kind = m.group(1), m.group(2).lower()
        table = {k: n for k, (n, kd) in names().items() if kd == kind}
        known_lower = {n.lower() for n in table.values()}
        for cand in (words, words.split()[-1]):                  # two words first ("my sewer"), then the last one
            if cand.lower() in known_lower:
                return m.group(0)                                # already a real name
            sk = skeleton(cand)
            if len(sk) < 2:
                continue
            scored = sorted(((difflib.SequenceMatcher(None, sk, skeleton(n)).ratio(),
                              difflib.SequenceMatcher(None, key(cand), k).ratio(), n) for k, n in table.items()
                             if key(n)[:1] == key(cand)[:1]), reverse=True)
            if scored and scored[0][0] >= 0.8 and scored[0][1] >= 0.5 and (len(scored) < 2 or scored[0][0] - scored[1][0] >= 0.1):
                name = scored[0][2]
                head = m.group(0)[:m.group(0).lower().rfind(cand.lower())]
                fixes.append((cand, name))
                return f"{head}{name} {m.group(2)}"
        return m.group(0)
    return _SLOT.sub(rep, text), fixes


_REPAIR = re.compile(r"[,.;!?]?\s*\b(?:(?:sorry|no|oops|actually|rather|correction|wait)\b[,.\s]*(?:i\s+mean[t]?\b[,.\s]*)?"
                     r"|i\s+mean[t]?\b[,.\s]*)", re.I)


def _places_in(text: str) -> list[tuple[int, int, str]]:
    """(start, end, canonical name) of every known place in a text, one or two words."""
    out = []
    toks = list(_WORD.finditer(text))
    i = 0
    while i < len(toks):
        hit = None
        if i + 1 < len(toks):
            two = toks[i].group(0) + " " + toks[i + 1].group(0)
            if key(two) in names():
                hit = (toks[i].start(), toks[i + 1].end(), names()[key(two)][0])
                i += 1
        if hit is None and key(toks[i].group(0)) in names() and len(key(toks[i].group(0))) >= 4:
            hit = (toks[i].start(), toks[i].end(), names()[key(toks[i].group(0))][0])
        if hit:
            out.append(hit)
        i += 1
    return out


def _prefix_place(tail: str) -> list[tuple[int, int, str]]:
    """The correction cut short: "sorry, I mean Pirya" (the recogniser split Piriyapatna and the turn ended between the
    halves; 4 Nov atlas correction). A fragment of 4+ letters that begins exactly ONE taluk / district counts as it."""
    k = key(tail)
    if len(k) < 4:
        return []
    hits = {n for nk, (n, kd) in names().items() if kd in ("taluk", "district") and nk.startswith(k)}
    return [(0, len(tail), hits.pop())] if len(hits) == 1 else []


def unknown_name(text: str) -> bool:
    """A capitalised word mid-sentence that is neither a known name nor a common word: probably a name the recogniser
    misheard ("And Hunter." for "and Hunsur")."""
    known = {n.lower() for n, _ in names().values()}
    for m in _WORD.finditer(text or ""):
        w = m.group(0)
        if m.start() == 0 or not w[:1].isupper() or len(w) < 4:
            continue
        if w.lower() not in known and w.lower() not in COMMON:
            return True
    return False


_SLOT_WORD = re.compile(r"\b(?:in|at|of|for|about|from|near|on)\s+(?:the\s+)?([a-z][a-z'\-]{4,})\b")
_PLAIN = set("""about above after again against along among around because before behind below beside between beyond
during except inside instead later maybe might other others outside please rather really since still their there these
thing things those though through today together under until where which while would could should without within world
cases complaints problem problems people village villages district districts taluk taluks office officer officers state
water light lights roads drains schools hospital pension ration cards panchayat level levels detail details status total
overdue pending escalated resolved rejected open month months weeks week days hours minutes answer answers number numbers
order dashboard picture chart charts graph donut screen first second third last next whole every school schools
hospital street streets drinking pipe pipes ration pension office road water drain anybody somebody nobody everyone""".split())


def doubtful_words(text: str) -> list[str]:
    """Words that look like a place the recogniser got wrong: a capitalised word mid-sentence that is no known name and
    no common word ("Hunter"), or an unknown word right after in / at / of / for / about ("in periopatnataluk")."""
    known = {n.lower() for n, _ in names().values()}
    out = []
    t = text or ""
    short = len(_WORD.findall(t)) <= 3                # a turn of 1-3 words ("Hunter." for "Hunsur?"): its first word counts too
    for m in _WORD.finditer(t):
        w = m.group(0)
        sentence_start = m.start() == 0 or t[:m.start()].rstrip().endswith((".", "?", "!"))
        if (not sentence_start or short) and w[:1].isupper() and len(w) >= 4 and w.lower() not in known \
                and w.lower() not in COMMON and w.lower() not in _PLAIN:
            out.append(w)
    for m in _SLOT_WORD.finditer(t):
        w = m.group(1)
        # a lowercase word after in / about / near ... is doubtful only if it SOUNDS like a place ("in periopatna"):
        # "about the drinking water", "near the school" made every long complaint wait for a second listen (6 Nov)
        if w.lower() not in known and w.lower() not in COMMON and w.lower() not in _PLAIN and w not in out \
                and _near_name(w) >= 0.75:   # misheard names 0.8+ (periopatna, carne, huncer); school 0.67, water 0.67
            out.append(w)
    # "how is X doing": X is a place or an officer; with no known place in it, its longest word is doubtful
    # ("How is to sealed our periopatina doing?" for "How is Tahsildar Piriyapatna doing?")
    m = _DASH_SLOT.search(text or "")
    if m and not _places_in(m.group(1)):
        ws = [w for w in _WORD.findall(m.group(1)) if w.lower() not in COMMON and w.lower() not in _PLAIN and len(w) >= 5]
        if ws:
            w = max(ws, key=len)
            if w not in out:
                out.append(w)
    return out


def _near_name(word: str) -> float:
    """How much `word` sounds like the closest place name (same first sound, similar length)."""
    k = key(word)
    if len(k) < 4:
        return 0.0
    return max((difflib.SequenceMatcher(None, k, nk).ratio() for nk in names()
                if nk[:1] == k[:1] and abs(len(nk) - len(k)) <= 3), default=0.0)


def candidates(word: str, n: int = 6) -> list[str]:
    """The gazetteer names that sound most like `word` (for priming a second listen), bigger places first on a tie."""
    k = key(word)
    if len(k) < 3 or not names():
        return []
    scored = sorted(((difflib.SequenceMatcher(None, k, nk).ratio(), -KIND_RANK.get(kd, 9), nm)
                     for nk, (nm, kd) in names().items() if abs(len(nk) - len(k)) <= max(4, len(k) // 2)),
                    reverse=True)
    out = []
    for _, _, nm in scored:
        if nm not in out:
            out.append(nm)
        if len(out) >= n:
            break
    return out


def places_in(text: str) -> list[str]:
    """The canonical names of the known places a text names."""
    return [n for _, _, n in _places_in(text or "")]


def prefer_bigger(text: str) -> tuple[str, list[tuple[str, str]]]:
    """A village or gram panchayat whose name is nearly a taluk's, a district's or the state's ("Hunur", a village in
    Raichur, for "Hunsur") becomes that bigger place: what a second listen hears as a small look-alike is far more
    often the taluk people ask about (6 Nov atlas: "Hunter" -> qwen3-asr "Hunur"; the 16 Oct POC bug, the same pair).
    Used on the second listen's words only."""
    kinds = {n: kd for n, kd in names().values()}
    big = {k: n for k, (n, kd) in names().items() if kd in ("taluk", "district", "state")}
    fixes: list[tuple[str, str]] = []
    out, pos = [], 0
    for a, b, n in _places_in(text or ""):
        if kinds.get(n) not in ("village", "gp"):
            continue
        kn = key(n)
        best = max(((difflib.SequenceMatcher(None, kn, k).ratio(), bn) for k, bn in big.items() if k[:1] == kn[:1]),
                   default=(0.0, None))
        if best[1] and best[0] >= 0.85 and best[1] != n:
            out += [text[pos:a], best[1]]
            pos = b
            fixes.append((n, best[1]))
    if not fixes:
        return text, []
    out.append(text[pos:])
    return "".join(out), fixes


def repair(text: str) -> tuple[str, list[tuple[str, str]]]:
    """A self-correction: "how many open cases are there in Hunsur, sorry, I mean Piriyapatna" -> "... in Piriyapatna";
    "status of GR-504210, no, GR-504211" -> "status of GR-504211". Only when what follows the marker is a place or an id
    and the words before it hold one of the same kind; anything else is left to the brain."""
    ms = list(_REPAIR.finditer(text))
    if not ms:
        return text, []
    m = ms[-1]
    head, tail = text[:m.start()], text[m.end():].strip(" ,.?!;")
    if not head.strip() or not tail or len(tail.split()) > 3:
        return text, []
    tid = re.fullmatch(r"((?:GR|SK)-[A-Z0-9]+)", tail, re.I)
    if tid:
        olds = list(re.finditer(r"\b(?:GR|SK)-[A-Z0-9]+\b", head, re.I))
        if olds:
            o = olds[-1]
            return head[:o.start()] + tid.group(1).upper() + head[o.end():].rstrip(" ,;") + "?", [(o.group(0), tid.group(1).upper())]
        return text, []
    new = _places_in(tail) or _prefix_place(tail)
    old = _places_in(head)
    if new and old:
        s, e, was = old[-1]
        return head[:s] + new[-1][2] + head[e:].rstrip(" ,;") + "?", [(was, new[-1][2])]
    return text, []


_FOLLOW = re.compile(r"^\s*(and|an|und|end|what about|how about|and what about|also)\b[\s,]*(.+?)[\s.?!]*$", re.I)


@lru_cache(maxsize=1)
def taluk_district() -> dict[str, str]:
    """taluk (lower case) -> its district, from the gazetteer."""
    out: dict[str, str] = {}
    try:
        c = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
        try:
            for t, d in c.execute("SELECT DISTINCT taluk, district FROM gazetteer WHERE taluk != '' AND district != ''"):
                out[str(t).lower()] = str(d).title() if str(d).isupper() else str(d)
        finally:
            c.close()
    except sqlite3.Error:
        pass
    return out


def followup_place(text: str, scope: dict | None = None) -> tuple[str, list[tuple[str, str]]]:
    """Inside a dashboard's scope, a short follow-up whose place the recogniser turned into everyday words: "An answer."
    for "and Hunsur" (4 Nov, atlas multi_turn on the real STT). Only <= 3 words that open like a follow-up, matched among
    the taluks and districts on the consonant skeleton, one clear winner; the caller applies it only while a scope is
    live. Anything else is left alone."""
    m = _FOLLOW.match(text or "")
    if not m or len(text.split()) > 3 or not names():
        return text, []
    rest = m.group(2)
    if key(rest) in names():
        return text, []                                          # already a place
    sk = skeleton(rest)
    if len(sk) < 3:
        return text, []
    table = {k: n for k, (n, kd) in names().items() if kd in ("taluk", "district")}
    d = str((scope or {}).get("district") or "")
    if d:
        # inside a district's scope only ITS taluks are candidates ("Hunter" inside Mysuru is Hunsur, not Hanur of
        # Chamarajanagar; 4 Nov atlas multi_turn)
        td = taluk_district()
        table = {k: n for k, n in table.items() if td.get(n.lower(), "").lower() == d.lower()}
    scored = sorted(((difflib.SequenceMatcher(None, sk, skeleton(n)).ratio(), n) for n in table.values()), reverse=True)
    if scored and scored[0][0] >= 0.7 and (len(scored) < 2 or scored[0][0] - scored[1][0] >= 0.1):
        return f"and {scored[0][1]}?", [(rest, scored[0][1])]
    return text, []


LEARNED = Path(__file__).resolve().parent / "lexicon_learned.json"
_LEARNED: dict = {"mtime": None, "rx": None, "map": {}}


def learned(text: str) -> tuple[str, list[tuple[str, str]]]:
    """A speaker's own mishearings, learned from their recordings by voicekit/evaluate.py (fdx/lexicon_learned.json:
    {"speakers": {name: {heard phrase: meant name}}}): replaced as whole phrases, before any fuzzy matching. Only phrases
    with at least one word that is not ordinary English are ever learned, so an everyday sentence cannot change. The
    file is re-read when it changes (a running relay picks a new session's learning up)."""
    try:
        mt = LEARNED.stat().st_mtime if LEARNED.exists() else None
    except OSError:
        mt = None
    if mt != _LEARNED["mtime"]:
        mp = {}
        if mt is not None:
            try:
                import json
                for _, var in (json.loads(LEARNED.read_text(encoding="utf-8")).get("speakers") or {}).items():
                    mp.update({k.lower(): v for k, v in (var or {}).items() if k and v})
            except (OSError, ValueError):
                mp = {}
        alts = sorted(mp, key=len, reverse=True)
        _LEARNED.update({"mtime": mt, "map": mp,
                         "rx": re.compile(r"\b(" + "|".join(re.escape(a) for a in alts) + r")\b", re.I) if alts else None})
    rx = _LEARNED["rx"]
    if rx is None or not text:
        return text, []
    fixes: list[tuple[str, str]] = []

    def sub(m):
        name = _LEARNED["map"].get(m.group(0).lower())
        if name:
            fixes.append((m.group(0), name))
            return name
        return m.group(0)
    return rx.sub(sub, text), fixes


def correct(text: str) -> tuple[str, list[tuple[str, str]]]:
    if not text:
        return text, []
    text, learned_fixes = learned(text)
    text, id_fixes = ids(text)
    id_fixes = learned_fixes + id_fixes
    if not names():
        return text, id_fixes
    text, slot_fixes = place_slot(text)
    text, dash_fixes = dash_slot(text)
    id_fixes = id_fixes + slot_fixes + dash_fixes
    toks = list(_WORD.finditer(text))
    fixes: list[tuple[str, str]] = []
    out, pos, i = [], 0, 0
    known = {n.lower() for n, _ in names().values()}
    while i < len(toks):
        m = toks[i]
        w = m.group(0)
        first = m.start() == 0 or text[:m.start()].rstrip().endswith((".", "?", "!"))
        cand = None
        if w[:1].isupper() and w.lower() not in COMMON and w.lower() not in known and not (first and len(w) < 4):
            if i + 1 < len(toks) and toks[i + 1].group(0)[:1].isupper() and text[m.end():toks[i + 1].start()].strip() == "":
                two = w + " " + toks[i + 1].group(0)
                hit = _best(two)
                if hit:
                    cand = (m.start(), toks[i + 1].end(), two, hit[0])
                    i += 1
            if cand is None:
                hit = _best(w)
                if hit:
                    cand = (m.start(), m.end(), w, hit[0])
        if cand is None and i + 1 < len(toks) and text[m.end():toks[i + 1].start()].strip() == "":
            # the recogniser split a name into two ordinary words ("my suru" for Mysuru): joined, an EXACT key match only
            # (no fuzzy guess on two everyday words), and only for names of 5+ letters
            two = w + toks[i + 1].group(0)
            hit = names().get(key(two))
            if hit and len(key(two)) >= 5:
                cand = (m.start(), toks[i + 1].end(), w + " " + toks[i + 1].group(0), hit[0])
                i += 1
        if cand:
            out.append(text[pos:cand[0]])
            out.append(cand[3])
            pos = cand[1]
            fixes.append((cand[2], cand[3]))
        i += 1
    out.append(text[pos:])
    fixed, rep_fixes = repair("".join(out))             # last: the names are canonical by now
    return fixed, id_fixes + fixes + rep_fixes


if __name__ == "__main__":
    import sys
    for s in sys.argv[1:] or ["How many open cases are there in Huntser?", "Which district has the most open cases?",
                              "Show me Piriyapattana and Mysore", "What is the status of Case GR504210?",
                              "How is Shimoga doing?", "Cases in Chikka Ballapur", "status of G R 5 0 4 2 1 0 please",
                              "open gr 504210", "application SK RD855S 260004811", "I have 504210 rupees"]:
        print(s, "->", correct(s))
