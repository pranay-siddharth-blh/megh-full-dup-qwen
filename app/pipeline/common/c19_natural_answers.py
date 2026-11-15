# app/pipeline/common/c19_natural_answers.py — a natural, insight-first answer for the multi-row shapes, and the short
# spoken version the live voice says. Part of the app.pipeline package: executed by app/pipeline/__init__.py into the
# package namespace, after every other file, so it shares every name with them; its functions run at turn time.
#
# Why (user report 2026-11-15, testing by live voice): "The answers are very robotic and quantized. They need to be a
# lot more natural language and high level. It should be like having a normal conversation with another person." The
# E9 templates (c12_answer_shapes) wrote every multi-row answer as a model-written opening line ("This briefing
# outlines the top five …") over a fixed formula ("WEST GARO HILLS is the largest with 33,147; EASTERN WEST KHASI
# HILLS is the smallest with 5,494."), place names in the database's capitals, and the voice read the whole list
# aloud, every number in full.
#
# What this file does (deterministic: no model call, so nothing to verify after the fact and nothing to wait for):
#   * _c19_written: a ranking / comparison / trend / split gets a lead of two or three plain sentences that says what
#     stands out — the leader and its margin over the next, the share of the whole, the gap to the bottom, the shape
#     of a trend (a dip, a peak) — with every figure EXACT (the one formatter, _c12_fmt_value) and the places in
#     Title Case; the full list follows underneath for the screen, as before. Phrasing varies with the question (a
#     stable pick, so the same question reads the same).
#   * _c19_spoken_for_result: the SHORT spoken form (result["spoken"], read by the page's voice instead of the whole
#     answer): the headline and the pattern, the top one or two named, figures rounded the way a person says them
#     ("just over 33,000", "about 1.7 lakh", "nearly ₹890 crore"), always marked as approximate, then "the full list
#     is on your screen". Every number it says is checked against the result (_c19_spoken_numbers_ok): an exact
#     value, a figure computed here from the rows (a total, a share, a gap, a % change), or an honest rounding of one
#     (within 3 %, and only after "about" / "nearly" / "just over" …); on any miss the spoken form falls back to the
#     written answer's own sentences (the old behaviour) — never an unchecked number.
#   * _c19_title_places: the place names a result row holds in capitals are written in Title Case in the answer.
# Off with ANSWER_NATURAL_ENABLED=false (the E9 answer and the page's own spoken form, exactly as before).
import math as _c19_math
import zlib as _c19_zlib

from app.voice import speech_guard as _c19_sg

_C19_PLACE_PARTS = frozenset({"district", "block", "village", "constituency", "panchayat", "gp", "ac"})
_C19_TOL = 0.03                  # an honest spoken rounding: within 3 % of the true value
_C19_SINGLE_TOL = 0.01           # a single figure (the answer itself) is rounded more finely
_C19_QUALIFIERS = ("about", "nearly", "almost", "roughly", "around", "over", "under", "some")
_C19_SPOKEN_MAX = 300            # the page cuts a spoken answer at 320 characters
_C19_TIMES = {2: "twice", 3: "three times", 4: "four times", 5: "five times", 6: "six times", 7: "seven times",
              8: "eight times", 9: "nine times", 10: "ten times"}
_C19_FRACTIONS = ((1 / 2, "half"), (1 / 3, "a third"), (2 / 3, "two-thirds"), (1 / 4, "a quarter"),
                  (3 / 4, "three-quarters"), (1 / 5, "a fifth"), (1 / 6, "a sixth"), (1 / 8, "an eighth"),
                  (1 / 10, "a tenth"), (2 / 5, "two-fifths"))
_C19_COUNT_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
                    10: "ten", 11: "eleven", 12: "twelve"}


_C19_REQUEST_VERBS = frozenset({"show", "give", "tell", "list", "display", "get", "see", "provide", "share", "break",
                                "compare", "rank", "draw", "plot", "pull", "find", "send"})


def _c19_yes_no(shape, question: str) -> bool:
    """A real yes / no question ("Is Ri Bhoi above the average?"), not a polite request ("Could you show me …",
    "Can you give me …"), which the shape reader counts as one by its first word."""
    if shape is None or not shape.yes_no:
        return False
    words = _c12s_words(question or "")
    if len(words) >= 2 and words[0] in ("can", "could", "will", "would") and words[1] in ("you", "u", "i", "we") \
            and any(w in _C19_REQUEST_VERBS for w in words[2:8]):
        return False
    return True


def _c19_on() -> bool:
    return bool(getattr(settings, "ANSWER_NATURAL_ENABLED", False)) and bool(settings.ANSWER_TEMPLATES_ENABLED)


# ── small helpers ────────────────────────────────────────────────────────────

def _c19_pick(question: str, salt: str, n: int) -> int:
    """A stable choice among n wordings: the same question always reads the same; different ones vary."""
    return _c19_zlib.crc32(f"{question or ''}|{salt}".lower().encode("utf-8")) % max(1, n)


def _c19_is_place_col(col: str) -> bool:
    return any(p in _C19_PLACE_PARTS for p in str(col).lower().split("_"))


def _c19_title_rows(rows: list, cols: "list | None" = None) -> list:
    """The rows with every place name held in capitals ("WEST GARO HILLS") in Title Case ("West Garo Hills")."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            out.append(r)
            continue
        nr = dict(r)
        for k, v in r.items():
            if (cols is None or k in cols) and _c19_is_place_col(k) and isinstance(v, str) and v.isupper():
                nr[k] = _place_title(v)
        out.append(nr)
    return out


def _c19_title_places(answer: str, rows: list) -> str:
    """The answer with every place name a row holds in capitals written in Title Case (longest names first, so
    "SOUTH WEST GARO HILLS" is never half-replaced by "WEST GARO HILLS")."""
    if not answer or not rows:
        return answer
    names = set()
    for r in rows[:500]:
        if isinstance(r, dict):
            for k, v in r.items():
                if _c19_is_place_col(k) and isinstance(v, str) and v.isupper() and len(v) >= 3:
                    names.add(v)
    for name in sorted(names, key=len, reverse=True):
        if name in answer:
            answer = answer.replace(name, _place_title(name))
    return answer


def _c19_noun(col: str, schemes: "list | None") -> str:
    """What the measure counts, with the scheme in front when the name does not carry it: "PMAY-G houses
    sanctioned", "Focus Plus beneficiaries" (never "focus plus beneficiaries")."""
    what = _c12s_e9_what(str(col))
    for lead in ("no of ", "num ", "number of ", "count of "):
        if what.startswith(lead):
            what = what[len(lead):]
    scheme = schemes[0] if schemes and len(schemes) == 1 else ""
    if scheme:
        low = scheme.lower()
        if low in what:
            return what.replace(low, scheme)
        return f"{scheme} {what}"
    return what


def _c19_is_money(col: str) -> bool:
    return _c12_money_unit(str(col)) is not None


def _c19_amount(col: str, v, noun: str) -> str:
    """'33,147 PMAY-G houses sanctioned', '₹50.67 crore in MGNREGA total expenditure', 'a wage share of 82.91%'."""
    f = _c12_fmt_value(str(col), v)
    if _c19_is_money(col):
        return f"{f} in {noun}"
    if not _c12s_additive(str(col)):
        return f"{noun} of {f}"
    return f"{f} {noun}"


def _c19_more_word(col: str, low: bool = False) -> str:
    if not _c12s_additive(str(col)):
        return "lowest" if low else "highest"
    if _c19_is_money(col):
        return "least" if low else "most"
    return "fewest" if low else "most"


def _c19_times(r: float) -> "str | None":
    """'more than twice', 'about six times' for a ratio of at least ~1.9; None below that."""
    if r < 1.9:
        return None
    if r < 2.0:
        return "almost twice"
    k = int(round(r))
    if k == 2:
        return "more than twice" if r >= 2.05 else "about twice"
    if k <= 10:
        return f"about {_C19_TIMES[k]}"
    return "more than ten times"


def _c19_fraction(share: float) -> "str | None":
    """'about a fifth' for 0.194; None when no simple fraction is close."""
    best = min(_C19_FRACTIONS, key=lambda f: abs(share - f[0]))
    if abs(share - best[0]) <= 0.08 * best[0]:
        return f"about {best[1]}"
    return None


def _c19_paren(f: str) -> str:
    """' (15,294)' after a name; ', at ₹1,402.93 lakh (≈ ₹14.03 crore)' when the figure has a bracket of its own."""
    return f", at {f}" if "(" in f else f" ({f})"


def _c19_margin(col: str, v1: float, v2: float, second: str) -> str:
    """How far the first is ahead of the second, in words, the second named with its figure."""
    f2 = _c12_fmt_value(str(col), v2)
    if not _c12s_additive(str(col)) or v2 <= 0 or v1 < 0:
        gap = _c12s_e9_gap(str(col), abs(v1 - v2))
        return f"{gap} ahead of {second}{_c19_paren(f2)}"
    r = v1 / v2
    times = _c19_times(r)
    if times:
        return f"{times} the figure for {second}{_c19_paren(f2)}"
    if r >= 1.3:
        return f"well ahead of {second}{_c19_paren(f2)}"
    if r >= 1.08:
        return f"ahead of {second}{_c19_paren(f2)}"
    if v1 == v2:
        return f"level with {second}{_c19_paren(f2)}"
    return f"only just ahead of {second}{_c19_paren(f2)}"


def _c19_scope(schemes, entities) -> "tuple[str, str, bool]":
    """(' in Ri Bhoi district' or '', ' in FY 2023-24' / ' across all financial years' / '', statewide)."""
    _scheme, place, period = _scope_words(schemes, entities)
    statewide = place.startswith("all of")
    where = "" if statewide else f" in {place}"
    timeless = bool(schemes) and all(_SCHEME_DATA_YEARS.get(s) == [] for s in schemes)
    when = "" if timeless else (f" {period}" if period.startswith("across") else f" in {period}")
    return where, when, statewide


def _c19_join(names: list) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _c19_label(r: dict, shape) -> str:
    lab = _c12s_label(r, shape)
    return _c12s_e9_period(r, shape) if shape.kind == "trend" else lab


# ── spoken numbers: rounded the way a person says them, always marked ───────

def _c19_round_sig(v: float, sig: int) -> float:
    if v == 0:
        return 0.0
    e = int(_c19_math.floor(_c19_math.log10(abs(v))))
    step = 10.0 ** (e - sig + 1)
    return round(v / step) * step


def _c19_trim(x: float) -> str:
    """2.0 -> '2', 1.70 -> '1.7', 1070.0 -> '1,070'."""
    if float(x).is_integer():
        return f"{int(x):,}"
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    whole, _, frac = s.partition(".")
    return f"{int(whole):,}" + ("." + frac if frac else "")


def _c19_say_scaled(x: float, money: bool) -> str:
    """A rounded value (in rupees for money) in Indian words: '1.7 lakh', '₹890 crore', '33,000'."""
    sign = "-" if x < 0 else ""
    a = abs(x)
    pre = "₹" if money else ""
    if a >= 1e7:
        return f"{sign}{pre}{_c19_trim(a / 1e7)} crore"
    if a >= 1e5:
        return f"{sign}{pre}{_c19_trim(a / 1e5)} lakh"
    return f"{sign}{pre}{_c19_trim(a)}"


def _c19_qualifier(rounded: float, v: float) -> str:
    if rounded == v:
        return ""
    if v < 0 or abs(rounded - v) <= 0.003 * abs(v):
        return "about "
    return "nearly " if rounded > v else "just over "


def _c19_sig_for(values: list, tol: float) -> int:
    """The coarsest rounding (1-3 significant figures) that keeps every value within tol AND keeps the values
    apart (two different figures never come out as the same spoken number); 0 = say them exactly."""
    vals = [abs(v) for v in values if v]
    for sig in (1, 2, 3):
        rounded = [_c19_round_sig(v, sig) for v in vals]
        if all(abs(r - v) <= tol * v for r, v in zip(rounded, vals)) and len(set(rounded)) == len(set(vals)):
            return sig
    return 0


def _c19_say(col: str, v: float, sig: "int | None" = None, tol: float = _C19_TOL, floor: float = 1000.0) -> str:
    """One figure as spoken: rounded and marked ('just over 33,000') when that helps, else exact."""
    col = str(col)
    v = float(v)
    if _c12_is_pct_col(col):
        r = round(v) if abs(v) >= 10 else round(v, 1)
        if abs(r - v) > 0.5:
            r = round(v, 1)
        return f"{_c19_qualifier(r, v)}{_c19_trim(r)}%"
    unit = _c12_money_unit(col)
    if unit:
        rupees = v * _C12_MONEY_SCALE[unit]
        if abs(rupees) < 1e5:
            return _c12_fmt_value(col, v)
        s = sig if sig is not None else _c19_sig_for([rupees], tol)
        if not s:
            return _c12_fmt_value(col, v)
        r = _c19_round_sig(rupees, s)
        return f"{_c19_qualifier(r, rupees)}{_c19_say_scaled(r, True)}"
    if abs(v) < floor:
        return _c19_trim(round(v, 2)) if not float(v).is_integer() else f"{int(v):,}"
    s = sig if sig is not None else _c19_sig_for([v], tol)
    if not s:
        return _c19_trim(v)
    r = _c19_round_sig(v, s)
    return f"{_c19_qualifier(r, v)}{_c19_say_scaled(r, False)}"


def _c19_say_set(col: str, values: list, tol: float = _C19_TOL) -> list:
    """Several figures said together: one rounding for all of them, so none collapse into another."""
    col = str(col)
    unit = _c12_money_unit(col)
    scaled = [float(v) * (_C12_MONEY_SCALE[unit] if unit else 1.0) for v in values]
    sig = _c19_sig_for(scaled, tol)
    if not sig:
        return [_c12_fmt_value(col, v) if unit or _c12_is_pct_col(col) else _c19_trim(float(v)) for v in values]
    return [_c19_say(col, v, sig=sig, tol=tol) for v in values]


def _c19_spoken_period(p: str) -> str:
    return p[3:] if p.startswith("FY ") else p


# ── the facts a lead needs, computed once from the rows ─────────────────────

def _c19_pairs(shape, rows: list) -> list:
    return [(r, float(v)) for r, v in _c12s_vals(rows, shape.metric)]


def _c19_allowed(shape, rows: list) -> list:
    """Every figure a spoken or written lead may state for these rows: the row values (in the column's unit and in
    rupees), and what this file computes from them — totals, gaps, % changes, shares, ratios."""
    out: list = []
    for r in rows:
        for c in shape.metrics:
            n = _as_number(r.get(c)) if isinstance(r, dict) else None
            if n is None:
                continue
            out += [float(n), abs(float(n))]
            unit = _c12_money_unit(str(c))
            if unit:
                out += [float(n) * _C12_MONEY_SCALE[unit], abs(float(n)) * _C12_MONEY_SCALE[unit]]
    pairs = _c19_pairs(shape, rows)
    vals = [v for _r, v in pairs]
    unit = _c12_money_unit(str(shape.metric))
    scale = _C12_MONEY_SCALE[unit] if unit else 1.0
    if vals:
        total = sum(vals)
        for d in [total] + [abs(v - w) for v in vals[:60] for w in vals[:60]]:
            out += [d, d * scale]
        for v in vals[:60]:
            if total:
                out.append(round(100.0 * v / total, 1))
            for w in vals[:60]:
                if w:
                    out.append(round(100.0 * abs(v - w) / abs(w), 1))
                    out.append(float(round(100.0 * abs(v - w) / abs(w))))
    return out


def _c19_numbers(text: str) -> list:
    """(value alternatives with their half-unit, qualified) for every figure in a text; years, FY halves and counts
    up to 12 left out. The half-unit is half of the last written digit ("1.21 crore": 0.005 crore), so a figure
    written to its own precision is exact."""
    t = text or ""
    low = t.lower()
    fy = [(a, b) for a, b, _y0, _y1 in _c12_fy_spans(t)]
    out = []
    for start, end, v, word, mult in _c19_sg._digit_groups(t):
        if any(a <= start < b for a, b in fy):
            continue
        if word == "" and float(v).is_integer() and (v <= 12 or (1990 <= v <= 2100 and end - start == 4)):
            continue
        raw = ""
        for ch in t[start:end]:
            if not (ch.isdigit() or ch in ",."):
                break
            raw += ch
        decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
        half = 0.5 * 10.0 ** (-decimals)
        before = low[max(0, start - 14):start].replace("₹", " ").replace("(", " ").split()
        qualified = bool(before) and (before[-1] in _C19_QUALIFIERS or before[-1] == "≈"
                                      or (len(before) >= 2 and before[-2] == "just" and before[-1] in ("over", "under")))
        alts = ((v, half),) if mult is None else ((v, half), (v * mult, half * mult))
        out.append((alts, qualified))
    return out


def _c19_spoken_numbers_ok(text: str, allowed: list) -> bool:
    """Every figure in `text` is an allowed value (exact: within half a unit of its last written digit, or 0.1 %), or
    an honest rounding of one (within 3 %, written right after 'about' / 'nearly' / 'just over' / '≈' …)."""
    vals = [a for a in allowed if a is not None]
    for alts, qualified in _c19_numbers(text):
        ok = False
        for x, half in alts:
            for a in vals:
                if a == x or abs(a - x) <= max(half * 1.0001, 0.001 * abs(a)):
                    ok = True
                elif qualified and a and abs(a - x) <= _C19_TOL * abs(a):
                    ok = True
                if ok:
                    break
            if ok:
                break
        if not ok:
            logger.warning("natural answer: the figure %s is not supported by the result", alts[0][0])
            return False
    return True


# ── the written lead ─────────────────────────────────────────────────────────

def _c19_written(shape, rows: list, question: str, schemes, entities) -> "str | None":
    """Lead + list for a ranking / comparison / trend / split, or None (the E9 answer stands)."""
    if shape is None or shape.kind not in ("ranking", "compare", "trend", "breakdown") or not shape.metric \
            or _c19_yes_no(shape, question):
        return None
    rows = _c19_title_rows(rows, shape.labels)
    pairs = _c19_pairs(shape, rows)
    if len(pairs) < 2:
        return None
    shape = _c12s_dataclasses.replace(shape, metrics=[c for c in shape.metrics if c == shape.metric
                                                      or not _c12s_e9_same_amount(shape.metric, c, rows)])
    try:
        lead = {"ranking": _c19_lead_ranking, "compare": _c19_lead_compare, "trend": _c19_lead_trend,
                "breakdown": _c19_lead_breakdown}[shape.kind](shape, pairs, question, schemes, entities)
    except Exception:  # noqa: BLE001 — the E9 answer is always there to fall back on
        logger.warning("natural answer: lead failed — the templated answer stands", exc_info=True)
        return None
    if not lead:
        return None
    body = _c19_list(shape, rows, pairs, question)
    text = lead + ("\n" + body if body else "")
    if not _c19_spoken_numbers_ok(lead, _c19_allowed(shape, rows)):
        return None
    return text


def _c19_list(shape, rows: list, pairs: list, question: str) -> str:
    """The figures underneath the lead, for the screen: the same lines E9 wrote, in Title Case."""
    m, q = str(shape.metric), question or ""
    lines: list = []
    if shape.kind == "ranking":
        for i, (r, v) in enumerate(pairs[:_C12S_LIST_MAX], 1):
            lines.append(f"{i}. **{_c12s_label(r, shape)}** — {_c12_fmt_value(m, v)}")
        if len(pairs) > _C12S_LIST_MAX:
            lines.append(f"…and {len(pairs) - _C12S_LIST_MAX} more in the table.")
        return "\n".join(lines)
    if shape.kind == "compare":
        if len(pairs) > 2:
            lines += [f"- **{_c12s_label(r, shape)}** — {_c12_fmt_value(m, v)}"
                      for r, v in sorted(pairs, key=lambda p: p[1], reverse=True)]
        for col in shape.metrics:
            cp = _c12s_vals(rows, col) if col != shape.metric else []
            if cp and len(lines) < 5:
                lines.append(f"- {_c12s_e9_cap(_c12s_e9_what(str(col)))}: " + "; ".join(
                    f"{_c12s_label(r, shape)} {_c12_fmt_value(str(col), v)}" for r, v in cp))
        return "\n".join(lines)
    if shape.kind == "trend":
        cp = _c19_time_sorted(shape, pairs)
        if len(cp) <= _C12S_LIST_MAX:
            lines += [f"- {_c12s_e9_period(r, shape)}: {_c12_fmt_value(m, v)}{_c12s_e9_extras(shape, r, 2)}"
                      for r, v in cp]
        return "\n".join(lines)
    ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
    additive = _c12s_additive(m) and all(v >= 0 for _r, v in pairs)
    total = _c12s_num(sum(v for _r, v in pairs)) if additive else None
    shares = bool(additive and total and (_C12S_E9_SHARE_ASK.search(q) or "%" in q))
    lines += [f"- **{_c12s_label(r, shape)}** — {_c12_fmt_value(m, v)}"
              f"{f' ({_c12s_pct(v, total)}%)' if shares else ''}{_c12s_e9_extras(shape, r, question=q)}"
              for r, v in ordered[:_C12S_LIST_MAX]]
    if len(pairs) > _C12S_LIST_MAX:
        lines.append(f"…and {len(pairs) - _C12S_LIST_MAX} more in the table.")
    return "\n".join(lines)


def _c19_time_sorted(shape, pairs: list) -> list:
    tcol = next((c for c in shape.labels if _c12s_is_time_col(c)), shape.labels[0] if shape.labels else None)
    return sorted(pairs, key=lambda p: str(p[0].get(tcol))) if tcol else list(pairs)


def _c19_lead_ranking(shape, pairs, question, schemes, entities) -> str:
    m = str(shape.metric)
    noun = _c19_noun(m, schemes)
    where, when, _sw = _c19_scope(schemes, entities)
    one = _c12s_dim_noun(shape, plural=False) if len(shape.labels) == 1 else ""
    (r1, v1), (r2, v2) = pairs[0], pairs[1]
    top, second = _c12s_label(r1, shape), _c12s_label(r2, shape)
    if shape.desc:
        margin = _c19_margin(m, v1, v2, second)
        if _C12S_E9_GAP_ASK.search(question or ""):
            margin += f", a gap of {_c12s_e9_gap(m, abs(v1 - v2))}"
        k = _c19_pick(question, "rank", 3)
        if k == 0 and one:
            s1 = f"{top} is the top {one}{where}, with {_c19_amount(m, v1, noun)}{when} — {margin}."
        elif k == 1:
            s1 = f"{top} comes out on top{where} with {_c19_amount(m, v1, noun)}{when}, {margin}."
        else:
            s1 = f"{top} leads{where} with {_c19_amount(m, v1, noun)}{when} — {margin}."
    else:
        word = _c19_more_word(m, low=True)
        s1 = (f"{top} has the {word} {noun}{where}{when}, at {_c12_fmt_value(m, v1)}, followed by {second} "
              f"{_c19_paren(_c12_fmt_value(m, v2))}.")
        if _C12S_E9_GAP_ASK.search(question or ""):
            s1 = s1[:-1] + f", a gap of {_c12s_e9_gap(m, abs(v1 - v2))}."
    rest = pairs[2:]
    if not rest:
        return s1
    if len(rest) == 1:
        r3, v3 = rest[0]
        return s1 + f" {_c12s_label(r3, shape)} is third, with {_c12_fmt_value(m, v3)}."
    if len(rest) <= 4:
        names = [_c12s_label(r, shape) for r, _v in rest]
        hi, lo = max(v for _r, v in rest), min(v for _r, v in rest)
        close = hi > 0 and (hi - lo) <= 0.25 * hi
        how = "are close behind, between" if close else "follow, from"
        a, b = (_c12_fmt_value(m, lo), _c12_fmt_value(m, hi)) if close else \
            (_c12_fmt_value(m, rest[0][1]), _c12_fmt_value(m, rest[-1][1]))
        joiner = "and" if close else "down to" if shape.desc else "up to"
        return s1 + f" {_c19_join(names)} {how} {a} {joiner} {b}."
    rl, vl = pairs[-1]
    return s1 + f" At the other end of this list, {_c12s_label(rl, shape)} has {_c12_fmt_value(m, vl)}."


def _c19_lead_breakdown(shape, pairs, question, schemes, entities) -> str:
    m = str(shape.metric)
    noun = _c19_noun(m, schemes)
    where, when, statewide = _c19_scope(schemes, entities)
    ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
    (hr, hv), (sr, sv), (lr, lv) = ordered[0], ordered[1], ordered[-1]
    top, second, bottom = (_c12s_label(x, shape) for x in (hr, sr, lr))
    n = len(pairs)
    nouns = _c12s_dim_noun(shape)
    one = _c12s_dim_noun(shape, plural=False)
    place_dim = len(shape.labels) == 1 and _c19_is_place_col(shape.labels[0])
    additive = _c12s_additive(m) and all(v >= 0 for _r, v in pairs)
    if not additive:
        gap = _c12s_e9_gap(m, hv - lv)
        return (f"{_c12s_e9_cap(_c12s_e9_what(m))}{where}{when} is highest in {top}{_c19_paren(_c12_fmt_value(m, hv))} and "
                f"lowest in {bottom}{_c19_paren(_c12_fmt_value(m, lv))}, a spread of {gap}.")
    total = sum(v for _r, v in pairs)
    margin = _c19_margin(m, hv, sv, second)
    k = _c19_pick(question, "split", 2)
    if place_dim:
        s1 = (f"{top} stands out with {_c19_amount(m, hv, noun)}{when}, {margin}." if k == 0 else
              f"{top} has the {_c19_more_word(m)} {noun}{when}: {_c12_fmt_value(m, hv)}, {margin}.")
    else:
        s1 = (f"{top} is the biggest group, with {_c19_amount(m, hv, noun)}{where}{when}, {margin}." if k == 0 else
              f"Most {noun}{where}{when} fall under {top}: {_c12_fmt_value(m, hv)}, {margin}.")
    s2 = ""
    if total > 0 and (place_dim or _C12S_E9_TOTAL_ASK.search(question or "") or _C12S_E9_SHARE_ASK.search(question or "")):
        share = hv / total
        frac = _c19_fraction(share)
        pct = _c12s_pct(hv, total)
        part = f"{frac} ({pct}%)" if frac else f"{pct}%"
        count = _C19_COUNT_WORDS.get(n, str(n))
        if place_dim and statewide and one == "district" and n == 12:
            span = f"Meghalaya's {count} districts"
        elif place_dim:
            span = f"all {count} {nouns}{where}"
        else:
            span = f"all {count} {nouns}"
        s2 = f" That is {part} of the {_c12_fmt_value(m, total)} across {span}."
    ratio = hv / lv if lv > 0 else None
    times = _c19_times(ratio) if ratio and ratio >= 2.95 else None
    s3 = f" {bottom} has the {_c19_more_word(m, low=True)}, at {_c12_fmt_value(m, lv)}"
    if times and place_dim and one:
        s3 += f" — {top} has {times} as {'much' if _c19_is_money(m) else 'many'}"
    s3 += "."
    if n == 2:
        s3 = ""
    return s1 + s2 + s3


def _c19_lead_trend(shape, pairs, question, schemes, entities) -> str:
    m = str(shape.metric)
    cp = _c19_time_sorted(shape, pairs)
    where, _when, _sw = _c19_scope(schemes, entities)
    what = _c19_noun(m, schemes)
    # "The number of PMAY-G houses sanctioned has risen …" (a count is plural; money / a rate reads as itself)
    count_measure = _c12s_additive(m) and not _c19_is_money(m)
    subject = (f"The number of {what}" if count_measure else _c12s_e9_cap(what)) + where
    (r0, v0), (r1, v1) = cp[0], cp[-1]
    p0, p1 = _c12s_e9_period(r0, shape), _c12s_e9_period(r1, shape)
    f0, f1 = _c12_fmt_value(m, v0), _c12_fmt_value(m, v1)
    vals = [v for _r, v in cp]
    pct = _c12s_pct(abs(v1 - v0), abs(v0)) if v0 > 0 and not _c12_is_pct_col(m) else None
    gap = _c12s_e9_gap(m, abs(v1 - v0))
    change = f"{gap}" + (f" ({pct}%)" if pct is not None else "")
    rising = all(b > a for a, b in zip(vals, vals[1:]))
    falling = all(b < a for a, b in zip(vals, vals[1:]))
    step = "month" if _c12s_monthly(shape, [r for r, _v in cp]) else "year"
    if v1 == v0:
        s1 = f"{subject} was the same at both ends, {f0} in {p0} and in {p1}."
    elif rising and len(cp) >= 3:
        s1 = f"{subject} has risen every {step}, from {f0} in {p0} to {f1} in {p1} — up {change}."
    elif falling and len(cp) >= 3:
        s1 = f"{subject} has fallen every {step}, from {f0} in {p0} to {f1} in {p1} — down {change}."
    else:
        up = v1 > v0
        size = (pct if pct is not None else None)
        adj = "" if size is None else ("slightly " if size < 5 else "much " if size >= 30 else "")
        s1 = (f"{subject} ended {adj}{'higher' if up else 'lower'} than it started — {f1} in {p1} against {f0} in "
              f"{p0}, {'up' if up else 'down'} {change}.")
    if rising or falling or len(cp) < 3:
        return s1
    inner = cp[1:-1]
    hi_r, hi_v = max(cp, key=lambda p: p[1])
    lo_r, lo_v = min(cp, key=lambda p: p[1])
    bits = []
    if any(r is lo_r for r, _v in inner) and lo_v < min(v0, v1):
        bits.append(f"dipped to {_c12_fmt_value(m, lo_v)} in {_c12s_e9_period(lo_r, shape)}")
    if any(r is hi_r for r, _v in inner) and hi_v > max(v0, v1):
        bits.append(f"peaked at {_c12_fmt_value(m, hi_v)} in {_c12s_e9_period(hi_r, shape)}")
    if not bits:
        return s1
    if len(bits) == 2 and cp.index((hi_r, hi_v)) < cp.index((lo_r, lo_v)):
        bits.reverse()                                       # said in the order they happened
    return s1 + " It did not move in a straight line: it " + " and then ".join(bits) + "."


def _c19_lead_compare(shape, pairs, question, schemes, entities) -> str:
    m = str(shape.metric)
    what = _c12s_e9_what(m)
    where, when, _sw = _c19_scope(schemes, entities)
    ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
    (hr, hv), (lr, lv) = ordered[0], ordered[-1]
    hi, lo = _c12s_label(hr, shape), _c12s_label(lr, shape)
    periods = bool(shape.labels) and all(_c12s_is_time_col(c) for c in shape.labels)
    if periods:
        hi, lo = _c12s_e9_period(hr, shape), _c12s_e9_period(lr, shape)
    verb = "was" if periods else "is"
    if periods:
        when = ""
    scheme = schemes[0] if schemes and len(schemes) == 1 else ""
    on = f"{scheme} {what}" if scheme and scheme.lower() not in what else what
    fh, fl = _c12_fmt_value(m, hv), _c12_fmt_value(m, lv)
    if hv == lv:
        return f"{_c19_join([_c12s_label(r, shape) for r, _v in pairs])} are level on {on}{where}{when}, at {fh} each."
    gap = _c12s_e9_gap(m, hv - lv)
    pct = _c12s_pct(hv - lv, lv) if lv > 0 and _c12s_additive(m) else None
    if pct is not None and pct < 3:
        s1 = (f"{hi} and {lo} are almost level on {on}{where}{when}: {fh} against {fl}, a difference of only "
              f"{gap} ({pct}%).")
    else:
        lead = "clearly higher" if pct is None or pct >= 15 else "higher"
        s1 = (f"{hi} {verb} {lead} than {lo} on {on}{where}{when}: {fh} against {fl}, a difference of {gap}"
              f"{f' ({pct}% more)' if pct is not None else ''}.")
    if len(pairs) > 2:
        mid = [p for p in ordered[1:-1]]
        s1 += " " + _c19_join([f"{_c12s_label(r, shape)}{_c19_paren(_c12_fmt_value(m, v))}" for r, v in mid]) + \
              (" sits" if len(mid) == 1 else " sit") + " in between."
    return s1


# ── the spoken form ──────────────────────────────────────────────────────────

def _c19_spoken_shape(shape, rows: list, question: str, schemes, entities) -> "str | None":
    """Two or three spoken sentences for a ranking / comparison / trend / split: the headline and the pattern, the
    top one or two named, rounded figures marked as approximate, the rest left to the screen."""
    if shape is None or shape.kind not in ("ranking", "compare", "trend", "breakdown") or not shape.metric:
        return None
    rows = _c19_title_rows(rows, shape.labels)
    pairs = _c19_pairs(shape, rows)
    if len(pairs) < 2:
        return None
    m = str(shape.metric)
    noun = _c19_noun(m, schemes)
    where, when, statewide = _c19_scope(schemes, entities)
    n = len(pairs)
    lab = (lambda r: _c19_spoken_period(_c12s_e9_period(r, shape))) if shape.kind == "trend" else \
        (lambda r: _c12s_label(r, shape))
    money = _c19_is_money(m)
    many = "as much" if money else "as many"
    if shape.kind == "ranking":
        (r1, v1), (r2, v2) = pairs[0], pairs[1]
        s1v, s2v = _c19_say_set(m, [v1, v2])
        if shape.desc:
            r = v1 / v2 if v2 > 0 else None
            times = _c19_times(r) if r and _c12s_additive(m) else None
            rel = (f"{times} {many} as {lab(r2)}, which is second with {s2v}" if times else
                   f"well ahead of {lab(r2)}, second with {s2v}" if r and r >= 1.15 else
                   f"ahead of {lab(r2)}, second with {s2v}" if r and r >= 1.05 else
                   f"with {lab(r2)} close behind at {s2v}")
            # a SHORT first sentence naming the leader (2026-11-15): the relay releases captions a checked sentence at a
            # time and the picture lights a place when its name is captioned (D-115), so a long opening held both back
            s1 = f"{lab(r1)} is out in front{where}. It has {s1v} {_c19_spoken_noun(m, noun)} — {rel}."
        else:
            s1 = (f"{lab(r1)} has the {_c19_more_word(m, low=True)}{where}. It has {s1v} {_c19_spoken_noun(m, noun)}, "
                  f"followed by {lab(r2)} with {s2v}.")
        rest = pairs[2:]
        s2 = ""
        if 1 <= len(rest) <= 3:
            s2 = f" Then come {_c19_join([lab(r) for r, _v in rest])}." if len(rest) > 1 else \
                f" {lab(rest[0][0])} is third."
        tail = " The full ranking is on your screen."
        return _c19_fit([s1, s2, tail])
    if shape.kind == "breakdown":
        ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
        (hr, hv), (lr, lv) = ordered[0], ordered[-1]
        place_dim = len(shape.labels) == 1 and _c19_is_place_col(shape.labels[0])
        additive = _c12s_additive(m) and all(v >= 0 for _r, v in pairs)
        sh, sl = _c19_say_set(m, [hv, lv])
        if not additive:
            s1 = f"{lab(hr)} is highest at {sh}, and {lab(lr)} lowest at {sl}."
            return _c19_fit([s1, f" All {n} are on your screen."])
        total = sum(v for _r, v in pairs)
        frac = _c19_fraction(hv / total) if total > 0 else None
        if place_dim and frac:
            tot = _c19_say(m, total)
            for qual in ("nearly ", "just over ", "about "):
                if tot.startswith(qual):
                    tot = "about " + tot[len(qual):]          # "the state's total of about 1.7 lakh"
            whole = (f"the state's total of {tot}" if statewide and _c19_one_is(shape, "district") and n == 12
                     else f"the total of {tot}")
            s1 = (f"{lab(hr)} has the {_c19_more_word(m)}. That is {sh} {_c19_spoken_noun(m, noun)} — {frac} of "
                  f"{whole}.")
        else:
            s1 = f"{lab(hr)} has the {_c19_more_word(m)}{where}. That is {sh} {_c19_spoken_noun(m, noun)}."
        r = hv / lv if lv > 0 else None
        times = _c19_times(r) if r and r >= 2.95 else None
        s2 = f" {lab(lr)} has the {_c19_more_word(m, low=True)}, {sl}" + \
             (f", so {lab(hr)} has {times} {many}." if times else ".")
        nouns = _c12s_dim_noun(shape)
        tail = f" All {n} {nouns} are on your screen." if len(shape.labels) == 1 else " The full list is on your screen."
        return _c19_fit([s1, s2 if n > 2 else "", tail])
    if shape.kind == "trend":
        cp = _c19_time_sorted(shape, pairs)
        (r0, v0), (r1, v1) = cp[0], cp[-1]
        hi_r, hi_v = max(cp, key=lambda p: p[1])
        lo_r, lo_v = min(cp, key=lambda p: p[1])
        said = dict(zip([id(r) for r, _v in cp], _c19_say_set(m, [v for _r, v in cp])))
        subj = _c12s_e9_cap(_c19_spoken_noun(m, noun, subject=True)) + where
        if v1 == v0:
            s1 = f"{subj} was the same in {lab(r0)} and {lab(r1)}, {said[id(r0)]}."
        else:
            up = v1 > v0
            pct = round(100.0 * abs(v1 - v0) / abs(v0)) if v0 > 0 and not _c12_is_pct_col(m) else None
            how = (f", {'up' if up else 'down'} about {pct}%" if pct else "")
            s1 = (f"{subj} {'went up' if up else 'came down'} from {said[id(r0)]} in {lab(r0)} to {said[id(r1)]} in "
                  f"{lab(r1)}{how}.")
        s2 = ""
        if len(cp) >= 3:
            inner = {id(r) for r, _v in cp[1:-1]}
            if id(lo_r) in inner and lo_v < min(v0, v1) and id(hi_r) in inner and hi_v > max(v0, v1):
                first, second = ((lo_r, "dipped to"), (hi_r, "peaked at")) if cp.index((lo_r, lo_v)) < \
                    cp.index((hi_r, hi_v)) else ((hi_r, "peaked at"), (lo_r, "dipped to"))
                s2 = (f" Along the way it {first[1]} {said[id(first[0])]} in {lab(first[0])}, then {second[1]} "
                      f"{said[id(second[0])]} in {lab(second[0])}.")
            elif id(hi_r) in inner and hi_v > max(v0, v1):
                s2 = f" It peaked in {lab(hi_r)}, at {said[id(hi_r)]}."
            elif id(lo_r) in inner and lo_v < min(v0, v1):
                s2 = f" It dipped in {lab(lo_r)}, to {said[id(lo_r)]}."
        every = " Each month's figure is on your screen." if _c12s_monthly(shape, [r for r, _v in cp]) \
            else " Each year's figure is on your screen."
        return _c19_fit([s1, s2, every])
    # compare
    ordered = sorted(pairs, key=lambda p: p[1], reverse=True)
    (hr, hv), (lr, lv) = ordered[0], ordered[-1]
    sh, sl = _c19_say_set(m, [hv, lv])
    if hv == lv:
        return _c19_fit([f"{_c19_join([lab(r) for r, _v in pairs])} are level, at {sh} each."])
    pct = round(100.0 * (hv - lv) / lv) if lv > 0 and _c12s_additive(m) else None
    r = hv / lv if lv > 0 and _c12s_additive(m) else None
    times = _c19_times(r) if r else None
    rel = f" — {times} {many}" if times else (f" — about {pct}% more" if pct and pct >= 3 else "")
    if pct is not None and pct < 3:
        s1 = f"{lab(hr)} and {lab(lr)} are almost level, at {sh} and {sl}."
    else:
        periods = bool(shape.labels) and all(_c12s_is_time_col(c) for c in shape.labels)
        if periods:
            lab = lambda r: _c19_spoken_period(_c12s_e9_period(r, shape))  # noqa: E731
            s1 = f"{lab(hr)} was higher, with {sh} {_c19_spoken_noun(m, noun)} against {sl} in {lab(lr)}{rel}."
        else:
            s1 = f"{lab(hr)} is ahead, with {sh} {_c19_spoken_noun(m, noun)} against {sl} for {lab(lr)}{rel}."
    return _c19_fit([s1, " The details are on your screen." if len(pairs) > 2 or len(shape.metrics) > 1 else ""])


def _c19_one_is(shape, noun: str) -> bool:
    return len(shape.labels) == 1 and _c12s_dim_noun(shape, plural=False) == noun


def _c19_spoken_noun(m: str, noun: str, subject: bool = False) -> str:
    """The measure as said after a spoken figure: money needs 'in' ('₹890 crore in MGNREGA total expenditure'), a
    subject reads as the noun itself."""
    if subject:
        return noun
    if _c19_is_money(m):
        return f"in {noun}"
    if not _c12s_additive(m):
        return ""
    return noun


def _c19_fit(parts: list) -> str:
    """The sentences joined, dropping the middle ones (never the first or the screen pointer) until it fits."""
    parts = [p for p in parts if p]
    text = "".join(parts).replace("  ", " ").strip()
    while len(text) > _C19_SPOKEN_MAX and len(parts) > 2:
        parts.pop(-2)
        text = "".join(parts).replace("  ", " ").strip()
    return text.replace(" ,", ",").replace(" .", ".")


# ── spoken form from the written text (single figures, cross-scheme answers, lists) ──

def _c19_prose_and_items(answer: str) -> "tuple[list, list]":
    """(prose lines, list items) of a markdown answer, without notes, tables, bold-only headers and brackets."""
    prose, items = [], []
    for raw in (answer or "").split("\n"):
        t = raw.strip()
        if not t or t.startswith("|") or t.lower().startswith("note:") or t.startswith("…"):
            continue
        plain = t.replace("**", "").strip()
        if t.startswith("**") and t.endswith("**") and t.count("**") == 2:
            continue                                         # a header such as "**All of Meghalaya, all years**"
        head = t.split(" ", 1)[0]
        is_item = t.startswith(("- ", "* ", "• ")) or (head[:-1].isdecimal() and head.endswith((".", ")")))
        if is_item:
            items.append(plain.split(" ", 1)[1] if " " in plain else plain)
        else:
            prose.append(plain)
    return prose, items


def _c19_round_text(text: str, rows: list, tol: float, floor: float) -> str:
    """Big figures in a sentence said the way a person says them: '₹22,22,75,30,000 (≈ ₹2,222.75 crore)' ->
    'about ₹2,200 crore', '9,09,15,181' -> 'about 9.1 crore'. Years, percentages and small figures stay exact."""
    s = text
    # the ≈ bracket first: the exact rupees are dropped, the size is kept (and rounded)
    for _ in range(20):
        open_ = s.find("(≈")
        if open_ < 0:
            break
        close = s.find(")", open_)
        if close < 0:
            break
        end = open_
        while end > 0 and s[end - 1] == " ":
            end -= 1
        start = end
        while start > 0 and s[start - 1] not in " (":
            start -= 1
        if s[start:end].lower() in ("lakh", "lakhs", "crore", "crores"):      # "₹4,575.40 lakh (≈ …)": the figure
            start -= 1
            while start > 0 and s[start - 1] == " ":
                start -= 1
            while start > 0 and s[start - 1] not in " (":
                start -= 1
        figure = s[start:end]
        if not any(ch.isdigit() for ch in figure):
            break                                            # a bracket after words: left as it is
        approx = s[open_ + 2:close].strip()
        s = s[:start] + "about " + approx + s[close + 1:]
    out, last = [], 0
    fy = [(a, b) for a, b, _y0, _y1 in _c12_fy_spans(s)]
    for start, end, v, word, mult in _c19_sg._digit_groups(s):
        if any(a <= start < b for a, b in fy) or (word == "" and float(v).is_integer() and 1990 <= v <= 2100):
            continue
        after = s[end:end + 2].lstrip()
        if after.startswith("%"):
            continue
        money = s[max(0, start - 1):start] == "₹"
        value = v * (mult or 1.0)
        if value < floor:
            continue
        sig = _c19_sig_for([value], tol)
        if not sig:
            continue
        r = _c19_round_sig(value, sig)
        q = _c19_qualifier(r, value)
        if not q:
            continue
        b = start - 1 if money else start
        before = s[max(0, b - 8):b].lower().split()
        if before and before[-1] in _C19_QUALIFIERS:
            q = ""
        out.append(s[last:b])
        out.append(q + _c19_say_scaled(r, money))
        last = end
    out.append(s[last:])
    return "".join(out)


def _c19_spoken_from_text(answer: str, rows: list, single: bool) -> "str | None":
    """The answer's own first sentences, big figures rounded and marked, and a pointer to the screen for the rest:
    the spoken form of an answer this file did not shape (a single figure, a cross-scheme answer, a list)."""
    prose, items = _c19_prose_and_items(answer)
    sentences = [x for p in prose for x in _c19_sg.sentences(_c19_drop_brackets(p))]
    if not sentences and not items:
        return None
    intro_at = next((i for i, x in enumerate(sentences[:2]) if x.rstrip().endswith(":")), None)
    take = sentences[:intro_at + 1] if intro_at is not None and items else sentences[:2]
    said = " ".join(take)
    shown_items = 0
    if items and (not take or take[-1].endswith(":")):
        shown_items = min(2, len(items))
        lead_items = [_c19_drop_brackets(i).rstrip(".") for i in items[:shown_items]]
        intro = said.rstrip().rstrip(":").rstrip()
        said = (intro + (": " if intro else "") + "; ".join(lead_items) + ".").strip()
    if not said:
        return None
    said = said.replace(" :", ":").replace(":.", ".").replace("..", ".")
    tol, floor = (_C19_SINGLE_TOL, 1e5) if single else (_C19_TOL, 1e4)
    spoken = _c19_round_text(said, rows, tol, floor)
    spoken = spoken[:1].upper() + spoken[1:]
    if len(items) > shown_items:
        spoken += " The full list is on your screen."
    elif len(sentences) > len(take):
        spoken += " The rest is on your screen."
    return spoken if len(spoken) <= _C19_SPOKEN_MAX + 120 else None


def _c19_drop_brackets(text: str) -> str:
    """Bracketed asides out of a spoken sentence (the ≈ size is kept: _c19_round_text reads it)."""
    out, depth = [], 0
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(" and not text.startswith("(≈", i):
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            i += 1
            continue
        if not depth:
            out.append(ch)
        i += 1
    keep = "".join(out)
    return " ".join(keep.split()).replace(" ,", ",").replace(" .", ".").replace(" ;", ";")


def _c19_text_allowed(answer: str, rows: list) -> list:
    """The figures a spoken form drawn from the written answer may round: every figure the answer holds (it passed
    the answer's own checks) and every row value."""
    out = []
    for alts in _c19_sg.spoken_values(answer or ""):
        out += list(alts)
    for r in rows[:500]:
        if isinstance(r, dict):
            for k, v in r.items():
                n = _as_number(v)
                if n is not None:
                    out.append(float(n))
                    unit = _c12_money_unit(str(k))
                    if unit:
                        out.append(float(n) * _C12_MONEY_SCALE[unit])
    return out


def _c19_spoken_for_result(result: dict) -> "str | None":
    """The short spoken form of a finished DATA answer, or None (the page then reads the answer as before)."""
    if not _c19_on() or not isinstance(result, dict) or result.get("route") != "data":
        return None
    answer = result.get("answer") or ""
    rows = result.get("data") or result.get("rows") or []
    if not answer or not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    sql = result.get("sql") or result.get("sql_query") or ""
    question = result.get("rewritten_question") or result.get("question") or ""
    schemes = result.get("schemes") or []
    display = _display_from_resolved(result.get("resolved_entities") or {})
    spoken = None
    shape = None
    try:
        detail, _totals = _c12s_rollup_split(sql, rows)
        shape = _answer_shape(question, sql, detail)
        if shape is not None and shape.kind in ("ranking", "compare", "trend", "breakdown") \
                and not _c19_yes_no(shape, question):
            spoken = _c19_spoken_shape(shape, detail, question, schemes, display)
            if spoken and not _c19_spoken_numbers_ok(spoken, _c19_allowed(shape, detail)):
                spoken = None
    except Exception:  # noqa: BLE001 — the spoken form is a convenience; the answer stands
        logger.warning("natural answer: spoken form from the rows failed", exc_info=True)
        spoken = None
    if spoken:
        return _c19_with_caveats(spoken, answer, rows, result)
    try:
        single = shape is not None and shape.kind in ("single_value", "profile")
        spoken = _c19_spoken_from_text(answer, rows, single)
        if spoken and not _c19_spoken_numbers_ok(spoken, _c19_text_allowed(answer, rows)):
            return None
        return _c19_with_caveats(spoken, answer, rows, result) if spoken else spoken
    except Exception:  # noqa: BLE001
        logger.warning("natural answer: spoken form from the text failed", exc_info=True)
        return None


# ── caveats the voice must say (2026-11-16, voice audit item 3) ─────────────
# The short spoken form said the headline and left every note on the screen, so a listener never heard that the year
# asked holds no data and another year was answered, that a CM Elevate count is valid applications only, or that a
# scheme of a cross-scheme answer records no money / no data for the period. Those notes change what the figures
# MEAN; each one is said as one short sentence (from the answer's own words, every figure checked like the rest).
# Ordinary context notes ("Focus Plus data covers FY 2022-23 and FY 2025-26") are said only when they fit.
_C19_CAVEAT_ROOM = 318                # the page cuts a spoken answer at 320 characters (voiceSpeech.MAX_SPOKEN)


def _c19_plain_sentence(text: str) -> str:
    """A note sentence as spoken: no 'Note:' opener, no bold, no bracket or dash aside, one full stop."""
    t = (text or "").replace("**", "").strip()
    if t.lower().startswith("note:"):
        t = t[5:].strip()
    t = _c19_drop_brackets(t)
    for dash in (" — ", " – "):
        a = t.find(dash)
        if a >= 0:
            b = t.find(dash, a + len(dash))
            t = (t[:a] + (" " + t[b + len(dash):] if b >= 0 else "")).strip()
    t = " ".join(t.split()).replace(" ,", ",").rstrip(" ,;:.")
    return (t[:1].upper() + t[1:] + ".") if t else ""


def _c19_answer_sentences(answer: str) -> list:
    out = []
    for raw in (answer or "").split("\n"):
        line = raw.strip()
        if line.startswith(("- ", "* ", "• ")):
            line = line[2:]
        out += _c19_sg.sentences(line)
    return out


def _c19_caveats(answer: str, result: dict) -> "list[tuple[int, str]]":
    """(priority, sentence) of every meaning-changing note of the answer, most important first: 0 = a year asked
    that holds no data (said FIRST: the figures are for another year), 1 = a count that is not what it may sound
    like (valid applications only) or a scheme with no money / no data in a cross answer, 2 = the years a scheme's
    data covers (said only when it fits)."""
    out: list = []
    seen: set = set()
    low_answer = (answer or "").lower()

    def add(prio: int, sentence: str) -> None:
        s = _c19_plain_sentence(sentence)
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append((prio, s))

    for s in _c19_answer_sentences(answer):
        low = s.lower()
        if "holds no data" in low:
            add(0, s)
        elif "has no data for" in low:
            add(1, s)
        elif "applications only" in low and "count" in low:
            add(1, s)
        elif "data covers" in low and low.startswith("note"):
            add(2, s)
    # a cross-scheme answer's "- **Homestay**: no money recorded" rows, said as one sentence
    no_money = []
    for raw in (answer or "").split("\n"):
        line = raw.strip().lstrip("-*• ").replace("**", "").strip()
        if line.lower().endswith("no money recorded") and ":" in line:
            name = line.split(":", 1)[0].strip()
            if name and name not in no_money:
                no_money.append(name)
    if no_money:
        verb = "records" if len(no_money) == 1 else "record"
        add(1, f"{_c19_join(no_money)} {verb} no money")
    # a CM Elevate count of valid applications only, when the answer says so in its own words
    if (result.get("schemes") or []) == ["CM Elevate"] and " valid applications" in f" {low_answer}" \
            and not any(p == 1 and "valid" in s.lower() for p, s in out):
        add(1, "These count valid applications only")
    return sorted(out, key=lambda x: x[0])


def _c19_with_caveats(spoken: str, answer: str, rows: list, result: dict) -> str:
    """The spoken form with the answer's meaning-changing notes said in it (each checked against the answer's
    figures; never cut by the page's 320-character limit: middle sentences give way first)."""
    try:
        caveats = _c19_caveats(answer, result)
    except Exception:  # noqa: BLE001 — a caveat we cannot read stays on the screen
        logger.warning("natural answer: caveats failed", exc_info=True)
        return spoken
    if not caveats:
        return spoken
    allowed = _c19_text_allowed(answer, rows)
    said_low = (spoken or "").lower()
    parts = _c19_sg.sentences(spoken)
    if not parts:
        return spoken
    pointer = parts[-1] if "on your screen" in parts[-1].lower() and len(parts) > 1 else ""
    body = parts[:-1] if pointer else list(parts)
    first, rest = [], []
    for prio, c in caveats:
        key = c.lower().rstrip(".")
        if key in said_low or not _c19_spoken_numbers_ok(c, allowed):
            continue
        if prio == 0 and "holds no data" in said_low:
            continue
        if prio == 1 and (("valid" in key and "valid" in said_low) or ("no money" in key and "no money" in said_low)):
            continue
        (first if prio == 0 else rest).append((prio, c))
    if not first and not rest:
        return spoken

    def build(body_parts, extra):
        # a year swap is said FIRST (the figures are for another year); the others after the figures they qualify
        # (never between a headline and its "That is …" sentence), before the screen pointer
        seq = [c for _p, c in first] + body_parts + [c for _p, c in extra] + ([pointer] if pointer else [])
        return " ".join(x.strip() for x in seq if x.strip())

    extra = list(rest)
    text = build(body, extra)
    while len(text) > _C19_CAVEAT_ROOM and len(body) > 1:
        body = body[:-1]                                 # a middle sentence gives way first; the headline stays
        text = build(body, extra)
    while len(text) > _C19_CAVEAT_ROOM and extra and extra[-1][0] == 2:
        extra = extra[:-1]                               # an ordinary context note is said only when it fits
        text = build(body, extra)
    if not pointer and (len(body) < len(parts)):
        text += " The rest is on your screen."
    return text
