"""
Word-level matching for English text.

Project rule (D-047): text is read word by word. SQL is read on the SQLGlot
tree (app/sql_ast.py); English text — the officer's question, composed
answers, names, verifier complaints — is matched here, on WORDS.

The text is split into word tokens (runs of letters, digits and '_');
everything between two tokens is their separator. Patterns are
small Python objects built from these pieces:

    W("job", "jobs")              one word, any of these (case-insensitive)
    W("disburs", prefix=True)     a word starting with "disburs"
    Pred(fn)                      one word for which fn(raw_word) is true
    ANY                           any one word
    Seq("how", "many")            words in a row ("how many" as one string works too)
    Alt(a, b, ...)                the first alternative that matches
    Opt(x)                        x or nothing
    Rep(x, lo, hi)                x repeated lo..hi times (greedy; lazy=True for fewest)
    Gap(hi) / Gap(lo, hi)         up to hi arbitrary words (fewest first)
    Joined("job", "card")         "job card", "job-card", "job_card" or "jobcard"
    Cap(x, "name")                remember what x matched (Hit.group(1) / ("name"))
    NotBefore(x, y)               x, not followed by y
    NotAfter(x, y)                x, not preceded by y
    Before(x, y) / After(x, y)    positive versions
    START / END                   the first / past the last word

A string argument is a word, or a phrase if it holds spaces; a tuple of
strings is a choice of words. Seq(..., sep="space") requires plain whitespace
between the words (default: any non-word characters, so "how, many" matches
"how many").

    m = Matcher(Seq(Opt("fy"), Cap(Pred(is_year))))
    hit = m.search(text)      # a Hit (start/end/group/span) or None
    m.finditer(text), m.findall(text), m.sub(repl, text), m.match(text), m.fullmatch(text)

Character-level helpers (numbers, whitespace, sentences, years) are at the end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterator, Sequence


# ── tokens ──────────────────────────────────────────────────────────────────

def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    raw: str
    low: str


def tokens(text: str | None) -> list[Token]:
    """Word tokens of `text` (runs of letters/digits/'_') with their positions."""
    text = text or ""
    out: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        if _is_word_char(text[i]):
            j = i + 1
            while j < n and _is_word_char(text[j]):
                j += 1
            raw = text[i:j]
            out.append(Token(i, j, raw, raw.lower()))
            i = j
        else:
            i += 1
    return out


def words(text: str | None) -> list[str]:
    """Lower-cased words of `text`."""
    return [t.low for t in tokens(text)]


class _Ctx:
    __slots__ = ("text", "toks")

    def __init__(self, text: str):
        self.text = text
        self.toks = tokens(text)

    def gap(self, i: int) -> str:
        """The separator text before token i (between token i-1 and token i)."""
        if i <= 0 or i > len(self.toks):
            return ""
        prev_end = self.toks[i - 1].end
        start = self.toks[i].start if i < len(self.toks) else len(self.text)
        return self.text[prev_end:start]


Caps = tuple  # ((key, start_char, end_char), ...)


# ── nodes ───────────────────────────────────────────────────────────────────

class Node:
    def ends(self, ctx: _Ctx, i: int, caps: Caps) -> Iterator[tuple[int, Caps]]:
        raise NotImplementedError


def _node(x) -> Node:
    if isinstance(x, Node):
        return x
    if isinstance(x, str):
        parts = x.split()
        if len(parts) == 1:
            return W(parts[0])
        return Seq(*[W(p) for p in parts])
    if isinstance(x, (tuple, list, set, frozenset)):
        items = list(x)
        if all(isinstance(s, str) and " " not in s.strip() for s in items):
            return W(*items)
        return Alt(*items)
    raise TypeError(f"not a pattern piece: {x!r}")


class W(Node):
    """One word from `options` (case-insensitive unless case=True); prefix=True
    accepts any word starting with an option (the stem, then any word characters)."""

    def __init__(self, *options: str, prefix: bool = False, case: bool = False):
        self.case = case
        self.prefix = prefix
        self.options = tuple(o if case else o.lower() for o in options)
        self._set = frozenset(self.options)

    def test(self, t: Token) -> bool:
        w = t.raw if self.case else t.low
        if self.prefix:
            return any(w.startswith(o) for o in self.options)
        return w in self._set

    def ends(self, ctx, i, caps):
        if i < len(ctx.toks) and self.test(ctx.toks[i]):
            yield i + 1, caps


class Pred(Node):
    """One word for which fn(raw_word) is true."""

    def __init__(self, fn: Callable[[str], bool]):
        self.fn = fn

    def ends(self, ctx, i, caps):
        if i < len(ctx.toks) and self.fn(ctx.toks[i].raw):
            yield i + 1, caps


class _AnyWord(Node):
    def ends(self, ctx, i, caps):
        if i < len(ctx.toks):
            yield i + 1, caps


ANY = _AnyWord()


class Seq(Node):
    """Words / pieces in a row. sep="space": only whitespace may separate them;
    sep="none": nothing may (adjacent tokens can't exist, so this only matters
    with Pred pieces split by punctuation — e.g. '2023' '-' '24' with sep="dash")."""

    def __init__(self, *parts, sep: str = "any"):
        self.parts = [_node(p) for p in parts]
        self.sep = sep

    def _sep_ok(self, ctx, i: int) -> bool:
        if self.sep == "any":
            return True
        g = ctx.gap(i)
        if self.sep == "space":
            return g != "" and g.strip() == ""
        if self.sep == "dash":
            return g.strip() in ("-", "/", "–", "—")
        return True

    def ends(self, ctx, i, caps):
        yield from self._from(ctx, 0, i, caps, i)

    def _from(self, ctx, k, i, caps, start):
        if k == len(self.parts):
            yield i, caps
            return
        for j, c2 in self.parts[k].ends(ctx, i, caps):
            if k + 1 < len(self.parts) and j > i and j < len(ctx.toks) and not self._sep_ok(ctx, j):
                continue
            yield from self._from(ctx, k + 1, j, c2, start)


class Alt(Node):
    def __init__(self, *options):
        self.options = [_node(o) for o in options]

    def ends(self, ctx, i, caps):
        for o in self.options:
            yield from o.ends(ctx, i, caps)


class Opt(Node):
    def __init__(self, x, lazy: bool = False):
        self.x = _node(x)
        self.lazy = lazy

    def ends(self, ctx, i, caps):
        if self.lazy:
            yield i, caps
            yield from self.x.ends(ctx, i, caps)
        else:
            yield from self.x.ends(ctx, i, caps)
            yield i, caps


class Rep(Node):
    def __init__(self, x, lo: int = 0, hi: int | None = None, lazy: bool = False):
        self.x, self.lo, self.hi, self.lazy = _node(x), lo, hi, lazy

    def ends(self, ctx, i, caps):
        yield from self._rep(ctx, i, caps, 0)

    def _rep(self, ctx, i, caps, n):
        can_stop = n >= self.lo
        can_go = self.hi is None or n < self.hi
        if self.lazy and can_stop:
            yield i, caps
        if can_go:
            for j, c2 in self.x.ends(ctx, i, caps):
                if j == i:
                    continue
                yield from self._rep(ctx, j, c2, n + 1)
        if not self.lazy and can_stop:
            yield i, caps


def Gap(lo: int, hi: int | None = None) -> Node:
    """Up to `hi` arbitrary words (Gap(3) = 0..3), fewest first."""
    if hi is None:
        lo, hi = 0, lo
    return Rep(ANY, lo, hi, lazy=True)


class Joined(Node):
    """A compound written as separate words or as one word: Joined("job", "card")
    matches "job card", "job-card", "job_card" and "jobcard". Each part may be a
    string or a tuple of alternatives."""

    def __init__(self, *parts):
        self.parts = [tuple(p) if isinstance(p, (tuple, list)) else (p,) for p in parts]
        combos = [""]
        for alts in self.parts:
            combos = [c + a.lower() for c in combos for a in alts]
        joined = set(combos)
        combos_u = [""]
        for k, alts in enumerate(self.parts):
            combos_u = [c + ("_" if k else "") + a.lower() for c in combos_u for a in alts]
        self.single = frozenset(joined | set(combos_u))
        self.seq = Seq(*[W(*alts) for alts in self.parts])

    def ends(self, ctx, i, caps):
        if i < len(ctx.toks) and ctx.toks[i].low in self.single:
            yield i + 1, caps
        yield from self.seq.ends(ctx, i, caps)


class Cap(Node):
    """Remember the text matched by x. Unnamed captures are numbered 1, 2, …
    in the order they are created inside one Matcher."""

    def __init__(self, x, name: str | None = None):
        self.x = _node(x)
        self.name = name
        self.index: int | None = None

    def ends(self, ctx, i, caps):
        for j, c2 in self.x.ends(ctx, i, caps):
            s = ctx.toks[i].start if i < len(ctx.toks) else len(ctx.text)
            e = ctx.toks[j - 1].end if j > i else s
            yield j, c2 + ((self, s, e),)


class NotBefore(Node):
    """x, provided `ahead` does not match right after it."""

    def __init__(self, x, ahead):
        self.x, self.ahead = _node(x), _node(ahead)

    def ends(self, ctx, i, caps):
        for j, c2 in self.x.ends(ctx, i, caps):
            if next(self.ahead.ends(ctx, j, c2), None) is None:
                yield j, c2


class Before(Node):
    """x, provided `ahead` matches right after it (not consumed)."""

    def __init__(self, x, ahead):
        self.x, self.ahead = _node(x), _node(ahead)

    def ends(self, ctx, i, caps):
        for j, c2 in self.x.ends(ctx, i, caps):
            if next(self.ahead.ends(ctx, j, c2), None) is not None:
                yield j, c2


def _ends_at(node: Node, ctx, i: int) -> bool:
    """Does `node` match some span ending exactly at token index i?"""
    for k in range(i, -1, -1):
        for j, _ in node.ends(ctx, k, ()):
            if j == i:
                return True
    return False


class NotAfter(Node):
    """x, provided `behind` does not match just before it."""

    def __init__(self, x, behind):
        self.x, self.behind = _node(x), _node(behind)

    def ends(self, ctx, i, caps):
        if _ends_at(self.behind, ctx, i):
            return
        yield from self.x.ends(ctx, i, caps)


class After(Node):
    """x, provided `behind` matches just before it."""

    def __init__(self, x, behind):
        self.x, self.behind = _node(x), _node(behind)

    def ends(self, ctx, i, caps):
        if _ends_at(self.behind, ctx, i):
            yield from self.x.ends(ctx, i, caps)


class _Start(Node):
    def ends(self, ctx, i, caps):
        if i == 0:
            yield i, caps


class _End(Node):
    def ends(self, ctx, i, caps):
        if i == len(ctx.toks):
            yield i, caps


START = _Start()
END = _End()


# ── matcher and hits ────────────────────────────────────────────────────────

@dataclass
class Hit:
    """What a Matcher found: the matched span plus captures, read with
    group(), start(), end(), span() and groups()."""
    string: str
    _start: int
    _end: int
    _groups: list = field(default_factory=list)       # [(start, end) | None] by index
    _named: dict = field(default_factory=dict)        # name -> (start, end)

    def _span(self, g=0):
        if g == 0:
            return (self._start, self._end)
        if isinstance(g, str):
            return self._named.get(g)
        return self._groups[g - 1] if 0 < g <= len(self._groups) else None

    def group(self, *gs):
        if not gs:
            gs = (0,)
        vals = []
        for g in gs:
            sp = self._span(g)
            vals.append(self.string[sp[0]:sp[1]] if sp else None)
        return vals[0] if len(vals) == 1 else tuple(vals)

    def __getitem__(self, g):
        return self.group(g)

    def groups(self):
        return tuple(self.string[sp[0]:sp[1]] if sp else None for sp in self._groups)

    def groupdict(self):
        return {k: self.string[s:e] for k, (s, e) in self._named.items()}

    def start(self, g=0):
        sp = self._span(g)
        return sp[0] if sp else -1

    def end(self, g=0):
        sp = self._span(g)
        return sp[1] if sp else -1

    def span(self, g=0):
        return self._span(g) or (-1, -1)

    def __bool__(self):
        return True


def _collect_caps(node, out: list):
    if isinstance(node, Cap):
        out.append(node)
    for attr in ("x", "ahead", "behind", "seq"):
        sub = getattr(node, attr, None)
        if isinstance(sub, Node):
            _collect_caps(sub, out)
    for attr in ("parts", "options"):
        subs = getattr(node, attr, None)
        if isinstance(subs, list):
            for s in subs:
                if isinstance(s, Node):
                    _collect_caps(s, out)


class Matcher:
    """A compiled word pattern. Accepts the same pieces as Seq (several
    arguments are matched in a row)."""

    def __init__(self, *pattern, sep: str = "any"):
        self.node = _node(pattern[0]) if len(pattern) == 1 and sep == "any" else Seq(*pattern, sep=sep)
        self._caps: list[Cap] = []
        _collect_caps(self.node, self._caps)
        unnamed = [c for c in self._caps if c.name is None]
        self._index = {id(c): k + 1 for k, c in enumerate(unnamed)}

    def _hit(self, ctx: _Ctx, i: int, j: int, caps: Caps) -> Hit:
        s = ctx.toks[i].start if i < len(ctx.toks) else len(ctx.text)
        e = ctx.toks[j - 1].end if j > i else s
        groups: list = [None] * len(self._index)
        named: dict = {}
        for cap, cs, ce in caps:
            if cap.name is not None:
                named[cap.name] = (cs, ce)
            elif id(cap) in self._index:
                groups[self._index[id(cap)] - 1] = (cs, ce)
        return Hit(ctx.text, s, e, groups, named)

    def _scan(self, text: str, *, anchored: bool = False, full: bool = False,
              start_tok: int = 0) -> Iterator[tuple[_Ctx, int, int, Caps]]:
        ctx = _Ctx(text or "")
        n = len(ctx.toks)
        i = start_tok
        while i <= n:
            for j, caps in self.node.ends(ctx, i, ()):
                if full and j != n:
                    continue
                yield ctx, i, j, caps
                break
            if anchored:
                return
            i += 1

    def search(self, text: str | None) -> Hit | None:
        for ctx, i, j, caps in self._scan(text or ""):
            return self._hit(ctx, i, j, caps)
        return None

    def match(self, text: str | None) -> Hit | None:
        """A match starting at the first word."""
        for ctx, i, j, caps in self._scan(text or "", anchored=True):
            return self._hit(ctx, i, j, caps)
        return None

    def fullmatch(self, text: str | None) -> Hit | None:
        """A match covering every word of the text."""
        for ctx, i, j, caps in self._scan(text or "", anchored=True, full=True):
            return self._hit(ctx, i, j, caps)
        return None

    def finditer(self, text: str | None) -> Iterator[Hit]:
        """Non-overlapping matches, left to right (empty matches skipped)."""
        ctx = _Ctx(text or "")
        n = len(ctx.toks)
        i = 0
        while i < n:
            found = None
            for j, caps in self.node.ends(ctx, i, ()):
                if j > i:
                    found = (j, caps)
                    break
            if found is None:
                i += 1
                continue
            j, caps = found
            yield self._hit(ctx, i, j, caps)
            i = j

    def findall(self, text: str | None) -> list:
        """Like re.findall: the matched text, or the single capture, or a tuple of captures."""
        out = []
        for h in self.finditer(text):
            if not h._groups:
                out.append(h.group(0))
            elif len(h._groups) == 1:
                out.append(h.group(1) or "")
            else:
                out.append(tuple(g or "" for g in h.groups()))
        return out

    def sub(self, repl: "str | Callable[[Hit], str]", text: str | None, count: int = 0) -> str:
        """Replace every match with `repl` (a plain string — no backreferences —
        or a function of the Hit)."""
        text = text or ""
        out, last, k = [], 0, 0
        for h in self.finditer(text):
            out.append(text[last:h.start()])
            out.append(repl(h) if callable(repl) else repl)
            last = h.end()
            k += 1
            if count and k >= count:
                break
        out.append(text[last:])
        return "".join(out)

    def subn(self, repl, text, count: int = 0) -> tuple[str, int]:
        n = sum(1 for _ in self.finditer(text))
        if count:
            n = min(n, count)
        return self.sub(repl, text, count), n

    def __call__(self, text: str | None) -> bool:
        return self.search(text) is not None


def any_word(*options: str, prefix: bool = False) -> Matcher:
    """Shortcut: a Matcher for one word out of `options`."""
    return Matcher(W(*options, prefix=prefix))


def any_phrase(*phrases) -> Matcher:
    """Shortcut: a Matcher for any of several words / phrases."""
    return Matcher(Alt(*phrases))


# ── character-level helpers ─────────────────────────────────────────────────

def collapse_ws(s: str | None) -> str:
    """Runs of whitespace -> one space, trimmed at both ends."""
    return " ".join((s or "").split())


def is_int(s: str) -> bool:
    return s.isdigit() and s.isascii()


def is_year(s: str, lo: int = 1900, hi: int = 2099) -> bool:
    """A 4-digit year in [lo, hi]."""
    return len(s) == 4 and is_int(s) and lo <= int(s) <= hi


def number_spans(text: str | None, *, decimals: bool = True, commas: bool = True) -> list[tuple[int, int, str]]:
    """Numbers written with digits: '42', '1,23,456', '3.5' -> (start, end, text).
    A digit, then digits and commas, then optionally '.' and more digits
    (trailing commas are not part of a number)."""
    text = text or ""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isdigit() and text[i].isascii():
            j = i + 1
            while j < n and ((text[j].isdigit() and text[j].isascii()) or (commas and text[j] == ",")):
                j += 1
            while j > i and text[j - 1] == ",":
                j -= 1
            if decimals and j + 1 < n and text[j] == "." and text[j + 1].isdigit():
                k = j + 1
                while k < n and text[k].isdigit():
                    k += 1
                j = k
            out.append((i, j, text[i:j]))
            i = j
        else:
            i += 1
    return out


def numbers(text: str | None, **kw) -> list[str]:
    return [s for _, _, s in number_spans(text, **kw)]


def to_number(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (TypeError, ValueError):
        return None


def digit_runs(text: str | None) -> list[str]:
    """Maximal runs of ASCII digits."""
    return numbers(text, decimals=False, commas=False)


def fy_spans(text: str | None) -> list[tuple[int, int, int, int]]:
    """Financial years written '2023-24', '2023-2024', 'FY 2023-24', '2023/24',
    '2023 – 24' -> (start, end, start_year, end_year_last2): an optional 'fy',
    a year 20xx, then '-', '/' or a dash, then two digits or another 20xx."""
    out = []
    toks = tokens(text)
    t = text or ""
    for k, tok in enumerate(toks[:-1]):
        y = tok.raw[2:] if tok.low.startswith("fy") and len(tok.raw) == 6 else tok.raw
        if not (len(y) == 4 and y.startswith("20") and is_int(y)):
            continue
        nxt = toks[k + 1]
        gap = t[tok.end:nxt.start].strip()
        if gap not in ("-", "/", "–", "—"):
            continue
        tail = nxt.raw
        if not ((len(tail) == 2 or (len(tail) == 4 and tail.startswith("20"))) and is_int(tail)):
            continue
        start = tok.start
        if k > 0 and toks[k - 1].low == "fy" and y == tok.raw:
            start = toks[k - 1].start
        elif tok.low.startswith("fy"):
            start = tok.start
        out.append((start, nxt.end, int(y), int(tail[-2:])))
    return out


def split_sentences(text: str | None) -> list[str]:
    """Split after '.', '!' or '?' followed by whitespace and a capital letter,
    digit, quote, '(' , '*' or '₹'; the punctuation stays with its sentence."""
    text = text or ""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] in ".!?":
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j > i + 1 and j < n and (text[j].isupper() or text[j].isdigit() or text[j] in "\"'(*₹"):
                out.append(text[start:i + 1])
                start = j
                i = j
                continue
        i += 1
    out.append(text[start:])
    return [s for s in out if s != ""]


def keep_chars(s: str | None, keep: Callable[[str], bool], repl: str = "") -> str:
    """Replace every character that `keep` rejects with `repl`."""
    return "".join(ch if keep(ch) else repl for ch in (s or ""))


def alnum_only(s: str | None, *, space: bool = False) -> str:
    """Letters and digits only (space=True keeps single spaces between words)."""
    if space:
        return collapse_ws(keep_chars(s, str.isalnum, " "))
    return keep_chars(s, str.isalnum)


def strip_words(text: str, words_: Sequence[str], *, at: str = "end") -> str:
    """Drop any of `words_` (case-insensitive) repeatedly from the start or end of `text`."""
    toks = text.split()
    low = [w.lower() for w in words_]
    if at == "end":
        while toks and toks[-1].lower() in low:
            toks.pop()
    else:
        while toks and toks[0].lower() in low:
            toks.pop(0)
    return " ".join(toks)
