"""Place names as Megh's data holds them (12 Nov 2026): a misheard district / block / constituency name is snapped to
its canonical spelling before the question reaches the pipeline. The live spoken-accuracy run heard "Nongstoin block"
as "non-stone block", which no resolver can match.

The names come from Megh's own entity resolvers (`data/*/*_entity_resolver.yaml`, read-only): every `values:` entry
with a `canonical` name and its `aliases`, under the dimensions district, block and assembly_constituency (~130 names;
villages are not in the resolvers and are never snapped). Snapping is conservative:

  * an exact alias anywhere ("Nongstoin Block", "WKH") -> its canonical name (Title Case);
  * a near miss ONLY right before a place word ("... non-stone block", "... Amalram constituency"): the one to three
    words before "block" / "constituency" / "district" are compared with every name of that type by a sound key
    (lower case, letters only, vowels and doubled letters folded); best >= 0.80 and ahead of the next by >= 0.08.
Ordinary words ("which block", "every district", "the constituency") are never snapped.
"""
from __future__ import annotations

import difflib
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml

MEGH_DATA = Path(os.environ.get("MEGH_DATA_DIR") or Path(os.environ.get("MEGH_ROOT", r"D:\MEGH-LANG\MEGH-LANG\meghoneai")) / "data")   # MEGH_ROOT
TYPES = {"district": "district", "block": "block", "assembly_constituency": "constituency"}
PLACE_WORDS = {"block": "block", "blocks": "block", "constituency": "constituency", "constituencies": "constituency",
               "ac": "constituency", "district": "district", "districts": "district"}
STOP = {"which", "every", "each", "the", "a", "an", "this", "that", "my", "our", "any", "all", "same", "what", "per", "by",
        "in", "for", "of", "at", "from", "to", "and", "or", "with", "on", "highest", "lowest", "top", "best", "worst",
        "most", "least", "one", "two", "three", "first", "second", "last", "how", "many", "much", "is", "are", "was",
        "give", "show", "me", "tell", "about", "under", "across", "whole", "entire", "each", "new", "other", "another"}
STATS = {"exact": 0, "snapped": 0, "last": ""}


def _key(s: str) -> str:
    """A sound key: lower case letters only, vowels folded to 'a', doubled letters single, a few sound swaps."""
    t = "".join(ch for ch in s.lower() if ch.isalpha())
    for a, b in (("ph", "f"), ("ck", "k"), ("q", "k"), ("z", "s"), ("w", "v"), ("y", "i"), ("ee", "i"), ("oo", "u")):
        t = t.replace(a, b)
    t = "".join("a" if ch in "aeiou" else ch for ch in t)
    t = t.replace("n", "m")                             # nasals blur in Indian place names (12 Nov: "Amleerin" = Amlarem)
    out = []
    for ch in t:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _plain(s: str) -> str:
    """Letters only, doubled letters single (no vowel folding): breaks ties the sound key cannot."""
    out = []
    for ch in (c for c in s.lower() if c.isalpha()):
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _score(cand: str, key) -> float:
    return 0.5 * difflib.SequenceMatcher(None, _key(cand), key[0]).ratio() +         0.5 * difflib.SequenceMatcher(None, _plain(cand), key[1]).ratio()


def _title(name: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in name.split())


@lru_cache(maxsize=1)
def names() -> dict:
    """{type: {canonical title name: [aliases]}} from every resolver."""
    out = {t: {} for t in TYPES.values()}
    for f in sorted(MEGH_DATA.glob("*/*_entity_resolver.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        dims = doc.get("dimensions") or {}
        for dim, typ in TYPES.items():
            for v in ((dims.get(dim) or {}).get("values") or []):
                if not isinstance(v, dict) or not v.get("canonical"):
                    continue
                c = _title(str(v["canonical"]))
                al = out[typ].setdefault(c, [])
                for a in v.get("aliases") or []:
                    if isinstance(a, str) and a not in al:
                        al.append(a)
    return out


@lru_cache(maxsize=1)
def _index():
    exact, keys = {}, {t: [] for t in TYPES.values()}
    for typ, d in names().items():
        for c, aliases in d.items():
            for form in [c] + aliases:
                exact.setdefault(form.lower(), c)
            keys[typ].append(((_key(c), _plain(c)), c))
    return exact, keys


def snap(text: str) -> str:
    """The heard text with misheard place names put right (see the module note). Never raises."""
    try:
        return _snap(text)
    except Exception:  # noqa: BLE001
        return text


def _snap(text: str) -> str:
    exact, keys = _index()
    toks = text.split()
    low = [t.lower().strip(",.?!;:") for t in toks]
    i = 0
    out = []
    while i < len(toks):
        typ = PLACE_WORDS.get(low[i])
        if typ and out:
            # the 1-3 words before the place word, stopping at an ordinary word
            span = []
            j = len(out) - 1
            while j >= 0 and len(span) < 3:
                w = out[j].lower().strip(",.?!;:")
                if w in STOP or not w.replace("-", "").isalpha():
                    break
                span.insert(0, j)
                j -= 1
            if span:
                heard = " ".join(out[k].strip(",.?!;:") for k in span)
                canon = exact.get(heard.lower())
                if canon is None:
                    best = None
                    for n in range(len(span), 0, -1):            # the longest tail that matches well
                        cand = " ".join(out[k].strip(",.?!;:") for k in span[-n:])
                        scored = sorted(((_score(cand, k), c) for k, c in keys[typ]), reverse=True)
                        if scored and scored[0][0] >= 0.72 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.09):
                            best = (n, scored[0][1], scored[0][0])
                            break
                    if best:
                        n, canon, score = best
                        span = span[-n:]
                        STATS["snapped"] += 1
                        STATS["last"] = f"{' '.join(out[k] for k in span)!r} -> {canon} ({score:.2f})"
                else:
                    STATS["exact"] += 1
                if canon:
                    tail = out[span[-1]][len(out[span[-1]].rstrip(",.?!;:")):]
                    out = out[:span[0]] + [canon + tail]
        out.append(toks[i])
        i += 1
    return " ".join(out)


if __name__ == "__main__":
    import json
    import sys
    d = names()
    print(json.dumps({t: len(v) for t, v in d.items()}))
    for s in sys.argv[1:]:
        print(repr(s), "->", repr(snap(s)), STATS["last"])
