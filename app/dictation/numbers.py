"""Spoken numbers to the way an officer types them (dictation, D-111). No regex.

Financial years (ported from the Megh voice shaper's spoken_years, Full Duplex
megh/shaper.py, 12 Nov 2026):
    "two thousand twenty-three twenty-four", "twenty twenty three to twenty twenty
    four", "in twenty three twenty four", "2023 24", "2023 to 2024", "2023 twenty
    four", "2023-2024", "2023/24"                          -> "2023-24"
    "two thousand twenty three", "twenty nineteen"          -> "2023", "2019"
Only consecutive years make a financial year ("2019 to 2022" stays a range).

Amounts and counts (coordinator's style, 15 Nov):
    "five lakh" -> "5 lakh"; "two point five crore" -> "2.5 crore";
    "rupees five lakh" / "five lakh rupees" -> "₹5 lakh"; "ten thousand rupees" -> "₹10,000"
    "top five" -> "top 5"; "one hundred days" -> "100 days"; "twelve percent" -> "12%"
A number word under ten with nothing to measure stays a word ("which one",
"the last three years"): that is how people write it too.
"""
from __future__ import annotations

from app.dictation.words import Chunk, chunk

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
         "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALE_INSIDE = {"hundred": 100, "thousand": 1000}
UNIT_AFTER = {"lakh", "lakhs", "crore", "crores", "percent", "%"}
LEAD_BEFORE = {"top", "bottom"}
YEAR_CUES = {"in", "for", "fy", "year", "during", "of", "from", "since", "between", "till", "until", "and"}
CONNECT = {"to", "-", "and", "till", "until", "through"}
RUPEE = {"rupees", "rupee", "rs", "inr"}


def _is_number_word(w: str) -> bool:
    return w in UNITS or w in TENS


def _digits(s: str) -> bool:
    return bool(s) and s.isdigit() and s.isascii()


def split_hyphenated(chunks: list[Chunk]) -> list[Chunk]:
    """'twenty-three' -> 'twenty' 'three' (number words only; '2023-24' and 'person-days' stay)."""
    out: list[Chunk] = []
    for c in chunks:
        parts = c.core.split("-")
        if len(parts) > 1 and all(p.lower() in UNITS or p.lower() in TENS for p in parts):
            for k, p in enumerate(parts):
                out.append(Chunk(c.lead if k == 0 else "", p, c.trail if k == len(parts) - 1 else ""))
        else:
            out.append(c)
    return out


# ── financial years ─────────────────────────────────────────────────────────

def _two_digit(ws: list[str], k: int) -> "tuple[int, int] | None":
    """10..99 said as words ('twenty three', 'nineteen', 'thirty') or written '24'."""
    if k >= len(ws):
        return None
    w = ws[k]
    if w in TENS:
        if k + 1 < len(ws) and ws[k + 1] in UNITS and 0 < UNITS[ws[k + 1]] < 10:
            return TENS[w] + UNITS[ws[k + 1]], 2
        return TENS[w], 1
    if w in UNITS and UNITS[w] >= 10:
        return UNITS[w], 1
    if len(w) == 2 and _digits(w):
        return int(w), 1
    return None


def _year_at(ws: list[str], k: int) -> "tuple[int, int] | None":
    """A whole year: '2023', 'two thousand (and) twenty three', 'twenty twenty three'."""
    if k >= len(ws):
        return None
    w = ws[k]
    if len(w) == 4 and _digits(w) and 1990 <= int(w) <= 2099:
        return int(w), 1
    if w == "two" and k + 1 < len(ws) and ws[k + 1] == "thousand":
        m = k + 2
        if m < len(ws) and ws[m] == "and":
            m += 1
        t = _two_digit(ws, m)
        if t and not (len(ws[m]) == 2 and _digits(ws[m])):
            return 2000 + t[0], m + t[1] - k
        if m < len(ws) and ws[m] in UNITS and UNITS[ws[m]] < 10:
            return 2000 + UNITS[ws[m]], m + 1 - k
        return None
    if w == "twenty":
        t = _two_digit(ws, k + 1)
        if t and 10 <= t[0] <= 39 and not (len(ws[k + 1]) == 2 and _digits(ws[k + 1])):
            return 2000 + t[0], 1 + t[1]
    return None


def _tail(ws: list[str], k: int, want: int) -> int:
    """Chunks used by the second year of a financial year starting at k (0 = none)."""
    y = _year_at(ws, k)
    if y and y[0] == want:
        return y[1]
    t = _two_digit(ws, k)
    if t and t[0] == want % 100:
        return t[1]
    return 0


def _fy_core(core: str) -> "str | None":
    """'2023-2024', '2023/24', '2023–24' written as one word -> '2023-24' (consecutive only)."""
    for sep in ("-", "/", "–", "—"):
        if sep in core:
            a, _, b = core.partition(sep)
            if len(a) == 4 and _digits(a) and a.startswith("20") and _digits(b) and len(b) in (2, 4):
                if int(b[-2:]) == (int(a[2:]) + 1) % 100 and (len(b) == 2 or b.startswith("20")):
                    return f"{a}-{b[-2:]}"
    return None


def years(chunks: list[Chunk]) -> list[Chunk]:
    chunks = split_hyphenated(chunks)
    out: list[Chunk] = []
    ws = [c.core.lower() for c in chunks]
    i = 0
    while i < len(chunks):
        c = chunks[i]
        fy = _fy_core(c.core)
        if fy and fy != c.core:
            out.append(Chunk(c.lead, fy, c.trail))
            i += 1
            continue
        start = _year_at(ws, i)
        cue = i > 0 and ws[i - 1] in YEAR_CUES
        if start is None:
            t = _two_digit(ws, i)
            if t and 15 <= t[0] <= 39 and not (len(ws[i]) == 2 and _digits(ws[i])):
                # 'twenty three twenty four': a year only as the first half of a consecutive pair
                start = (2000 + t[0], t[1])
                bare = True
            else:
                bare = False
        else:
            bare = False
        if start is not None:
            y, n = start
            k = i + n
            if not chunks[k - 1].ends_sentence():
                m = k + 1 if k < len(ws) and ws[k] in CONNECT else k
                tn = _tail(ws, m, y + 1) if (m == k or not chunks[k].ends_sentence()) else 0
                if tn and (cue or not bare or m == k):
                    last = chunks[m + tn - 1]
                    out.append(Chunk(c.lead, f"{y}-{(y + 1) % 100:02d}", last.trail))
                    i = m + tn
                    continue
            if not bare and n > 1:
                out.append(Chunk(c.lead, str(y), chunks[k - 1].trail))
                i = k
                continue
        out.append(c)
        i += 1
    return out


# ── amounts and counts ──────────────────────────────────────────────────────

def indian(n: int) -> str:
    """1234567 -> '12,34,567'."""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def _run(ws: list[str], i: int) -> "tuple[str, int, int] | None":
    """A run of number words at i -> (written, value, chunks used); None if none."""
    j, total, cur, seen = i, 0, 0, False
    if j < len(ws) and ws[j] == "a" and j + 1 < len(ws) and ws[j + 1] in ("hundred", "thousand", "lakh", "crore"):
        cur, j, seen = 1, j + 1, True
    while j < len(ws):
        w = ws[j]
        if w in UNITS:
            cur += UNITS[w]
        elif w in TENS:
            cur += TENS[w]
        elif w == "hundred" and seen:
            cur = max(cur, 1) * 100
        elif w == "thousand" and seen:
            total += max(cur, 1) * 1000
            cur = 0
        elif w == "and" and seen and j + 1 < len(ws) and _is_number_word(ws[j + 1]) and (total or cur >= 100):
            pass
        else:
            break
        seen = True
        j += 1
    if not seen:
        return None
    value = total + cur
    written = indian(value) if value >= 1000 else str(value)
    if j + 1 < len(ws) and ws[j] == "point" and ws[j + 1] in UNITS and UNITS[ws[j + 1]] < 10:
        k, dec = j + 1, ""
        while k < len(ws) and ws[k] in UNITS and UNITS[ws[k]] < 10:
            dec += str(UNITS[ws[k]])
            k += 1
        return f"{written}.{dec}", value, k - i
    return written, value, j - i


def amounts(chunks: list[Chunk]) -> list[Chunk]:
    ws = [c.key if c.core != "%" else "%" for c in chunks]
    out: list[Chunk] = []
    i = 0
    while i < len(chunks):
        c = chunks[i]
        r = _run(ws, i)
        if r is None or ws[i] == "and":
            out.append(c)
            i += 1
            continue
        written, value, n = r
        # a run never crosses a full stop / question mark inside it
        cut = n
        for k in range(n - 1):
            if chunks[i + k].ends_sentence():
                cut = k + 1
                break
        if cut != n:
            r2 = _run(ws[:i + cut], i)
            if r2 is None:
                out.append(c)
                i += 1
                continue
            written, value, n = r2
        nxt = ws[i + n] if i + n < len(ws) and not chunks[i + n - 1].ends_sentence() else ""
        nxt2 = ws[i + n + 1] if i + n + 1 < len(ws) else ""
        prev = out[-1].key if out and not out[-1].ends_sentence() else ""
        unit = nxt in UNIT_AFTER or (nxt == "per" and nxt2 == "cent")
        if not (value >= 10 or "." in written or unit or prev in LEAD_BEFORE or prev in RUPEE):
            out.extend(chunks[i:i + n])
            i += n
            continue
        last = chunks[i + n - 1]
        out.append(Chunk(c.lead, written, last.trail))
        i += n
    return _percent(out)


def _percent(chunks: list[Chunk]) -> list[Chunk]:
    out: list[Chunk] = []
    i = 0
    while i < len(chunks):
        c = chunks[i]
        if out and _numeric(out[-1].core) and not out[-1].trail:
            if c.key == "percent":
                out[-1] = Chunk(out[-1].lead, out[-1].core + "%", c.trail)
                i += 1
                continue
            if c.key == "per" and i + 1 < len(chunks) and chunks[i + 1].key == "cent" and not c.trail:
                out[-1] = Chunk(out[-1].lead, out[-1].core + "%", chunks[i + 1].trail)
                i += 2
                continue
        out.append(c)
        i += 1
    return out


def _numeric(core: str) -> bool:
    s = core.replace(",", "").replace(".", "", 1)
    return _digits(s)


def rupees(chunks: list[Chunk]) -> list[Chunk]:
    """'rupees 5 lakh' / '5 lakh rupees' / 'Rs 10,000' -> '₹5 lakh' / '₹10,000'."""
    out: list[Chunk] = []
    i = 0
    while i < len(chunks):
        c = chunks[i]
        if c.key in RUPEE and (c.key == "rs" or not c.ends_sentence()) and i + 1 < len(chunks) and _numeric(chunks[i + 1].core):
            n = chunks[i + 1]
            out.append(Chunk(c.lead + n.lead, "₹" + n.core, n.trail))
            i += 2
            continue
        if c.key in ("rupees", "rupee") and out:
            # '5 lakh rupees' / '10,000 rupees'
            k = len(out) - 1
            if out[k].key in UNIT_AFTER - {"percent", "%"} and k > 0:
                k -= 1
            if _numeric(out[k].core) and not out[-1].ends_sentence() and not out[k].core.startswith("₹"):
                out[k] = Chunk(out[k].lead, "₹" + out[k].core, out[k].trail)
                out[-1] = Chunk(out[-1].lead, out[-1].core, out[-1].trail + c.trail)
                i += 1
                continue
        out.append(c)
        i += 1
    return out


def spoken(chunks: list[Chunk]) -> list[Chunk]:
    """Years first (so 'twenty twenty three' is a year, not 2,023), then amounts, then ₹."""
    return rupees(amounts(years(chunks)))


def spoken_text(text: str) -> str:
    from app.dictation.words import join, split
    return join(spoken(split(text)))


__all__ = ["spoken", "spoken_text", "indian", "chunk"]
