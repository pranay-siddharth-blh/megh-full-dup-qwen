"""Grading of one cross-scheme conversation against truth.py (the 2026-10-30 run).

Since D-062 / D-066 / D-097 the answer is no longer the D-044 fixed table: the
rows are tagged `scheme` (`beneficiaries`, `amount_crore`, `villages`, and
`district` / `block` / `rank` when grouped) and the text is written in code
(`app/cross_figures.py`) — a leader sentence "**X** has the most …", a per-place
winner "**X** is highest in all 12 districts" / "Highest by district: …", a ranked
list "**S** — Top N districts by …: 1. …", and a gap sentence for what a scheme
cannot hold ("has no data for FY …", "records no financial year", "does not
record assembly constituency", "no money recorded").

Pass rule (reference_documents/README.md): the right figure for every scheme
asked, and no other scheme, at the right place, in the rows AND in the text;
"no data" / "not recorded" / "no money" where true — never a false 0; the
ranking, leader and top place right; no needless pause (cross_run.py)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import truth as T  # noqa: E402

ORDER = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CM Elevate Legacy"]
# what a combined count may add (CM Elevate's applications stay out, I-13 / D-097)
_NOT_IN_COMBINED = {"CM Elevate"}


def indian(n):
    neg, s = n < 0, str(int(round(abs(float(n or 0)))))
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts + [tail])
    return ("-" if neg else "") + s


def crore_text(rupees):
    c = rupees / 1e7
    if abs(c) < 1:
        return f"₹{c * 100:,.2f} lakh"
    whole, frac = f"{c:.2f}".split(".")
    return f"₹{indian(float(whole))}.{frac} crore"


def scheme_of(cell):
    c = (cell or "").lower()
    for k, s in (("focus legacy", "Focus Legacy"), ("focus plus", "Focus Plus"), ("cm elevate legacy", "CM Elevate Legacy"),
                 ("cm elevate", "CM Elevate"), ("mgnrega", "MGNREGA"), ("pmay", "PMAY-G")):
        if k in c:
            return s
    return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money_close(got_crore, exp_rupees):
    g = _num(got_crore)
    return g is not None and abs(g - exp_rupees / 1e7) <= 0.0051


def gap_ok(text, s, exp):
    """The sentence a scheme with no figure must get."""
    t = text.lower()
    sl = s.lower()
    if exp == T.NO_MONEY:
        # "CM Elevate records applications only, no money", "- **CM Elevate:** 8,921
        # applications, no money recorded", a table cell "CM Elevate 622 / no money";
        # in a financial-year / constituency question its "records no financial year" /
        # "does not record assembly constituency" is the gap said
        return sl in t and ("no money" in t or f"{sl} records no financial year" in t
                            or f"{sl} does not record assembly constituency" in t)
    if exp == T.NOT_RECORDED:
        return f"{sl} does not record assembly constituency" in t
    if exp == T.NO_YEAR:
        return f"{sl} has no data for" in t or f"{sl} records no financial year" in t
    if not exp:
        return f"{sl} has no records for" in t or f"{sl} has no records matching" in t
    return False


def _zero_ok(text, s, r, col):
    """A true 0: a row with 0 (or no row) and no other figure claimed for it."""
    return (r is None or not _num(r.get(col))) and (r is not None or gap_ok(text, s, 0.0))


def _bold_after(text, marker):
    """The **bold** span that precedes `marker` on the same line: '**X** has the most'."""
    out = []
    k = text.find(marker)
    while k != -1:
        line_start = text.rfind("\n", 0, k) + 1
        seg = text[line_start:k]
        a = seg.rfind("**")
        b = seg.rfind("**", 0, a) if a != -1 else -1
        if b != -1:
            out.append(seg[b + 2:a])
        k = text.find(marker, k + 1)
    return out


def _rank_kind(c):
    return "money" if (c["money"] and not c["count"]) else ("villages" if c["coverage"] and not c["count"] else "count")


def check(c, rec, E):
    """[] when the answer is right, else the list of what is wrong."""
    bad = []
    text = rec.get("answer") or ""
    low = text.lower()
    if c["shape"] == "kb_all":   # a conceptual comparison of every scheme (knowledge path)
        miss = [s for s in ORDER if f"**{s}**" not in text]
        return [f"knowledge comparison misses {miss}"] if miss else []
    rows = [dict(r) for r in (rec.get("rows") or [])]
    if c["f"].get("village") and any("village_code" in r for r in rows):
        # a name shared by 2-3 villages is answered one row each (D-096 / D-097): the
        # asked village's rows are graded
        rows = [r for r in rows if str(r.get("village_code")) == str(c["f"]["village"])]
    by = {}
    for r in rows:
        by.setdefault(r.get("scheme"), []).append(r)
    extra = sorted(s for s in by if s and s not in c["schemes"])
    if extra:
        bad.append(f"schemes not asked shown: {extra}")
    # the header must name the place asked: a village answered from the state, or the
    # wrong village, read as that place's figures (cross-scheme run 2026-10-13)
    head = text.split("\n", 1)[0].lower()
    if c.get("level") == "village" and c.get("place"):
        name = (c["place"][0] or "").lower()
        if name not in head and f"lgd {c.get('code')}" not in head and "village" not in head:
            bad.append(f"header does not name the village: {head[:80]}")
    elif c.get("level") == "constituency" and c.get("place"):
        if (c["place"][0] or "").lower() not in head:
            bad.append(f"header does not name the constituency: {head[:80]}")
    elif c.get("level") == "block" and c.get("place"):
        if "block" not in head:
            bad.append(f"header does not name the block: {head[:80]}")
    if not c["group"]:
        for s in c["schemes"]:
            e = E[s]
            rs = by.get(s, [])
            figures = [k for k in ("count", "money") if c[k] and isinstance(e.get(k), float)]
            if c["coverage"] and isinstance(e.get("reach"), tuple):
                figures.append("reach")
            if not figures:
                # nothing the scheme can give here: every asked measure is a gap
                for k in ("count", "money"):
                    if c[k] and not gap_ok(text, s, e[k]):
                        bad.append(f"{s} {k}: expected gap {e[k]!r}, not said")
                if c["coverage"] and not isinstance(e.get("reach"), tuple) and not gap_ok(text, s, e["reach"]):
                    bad.append(f"{s} coverage: expected gap {e['reach']!r}, not said")
                if rs and any(_num(r.get(k)) for r in rs for k in ("beneficiaries", "amount_crore", "villages")):
                    bad.append(f"{s}: a figure shown where none is held ({rs[0]})")
                continue
            if not rs and not all(e.get(k) in (0.0, None, T.NO_MONEY, T.NO_YEAR, T.NOT_RECORDED)
                                  for k in ("count", "money")):
                bad.append(f"{s}: no row")
                continue
            r = rs[0] if rs else None
            if c["count"]:
                exp = e["count"]
                if isinstance(exp, float) and exp == 0.0:
                    if not _zero_ok(text, s, r, "beneficiaries"):
                        bad.append(f"{s} count: expected 0 / no records, got {r}")
                elif isinstance(exp, float):
                    if r is None or _num(r.get("beneficiaries")) != float(int(round(exp))):
                        bad.append(f"{s} count: row {r and r.get('beneficiaries')} expected {int(round(exp))}")
                    if indian(exp) not in text:
                        bad.append(f"{s} count: {indian(exp)} not in the text")
                elif not gap_ok(text, s, exp):
                    bad.append(f"{s} count: expected gap {exp!r}, not said")
            if c["money"]:
                exp = e["money"]
                if isinstance(exp, float) and exp == 0.0:
                    if not _zero_ok(text, s, r, "amount_crore"):
                        bad.append(f"{s} money: expected 0 / no records, got {r}")
                elif isinstance(exp, float):
                    if r is None or not money_close(r.get("amount_crore"), exp):
                        bad.append(f"{s} money: row {r and r.get('amount_crore')} expected {exp / 1e7:.2f} crore")
                    if crore_text(exp) not in text:
                        bad.append(f"{s} money: {crore_text(exp)} not in the text")
                else:
                    if not gap_ok(text, s, exp):
                        bad.append(f"{s} money: expected gap {exp!r}, not said")
                    if _num(r.get("amount_crore")):
                        bad.append(f"{s} money: a figure shown where none is held")
            if c["coverage"]:
                ex = e["reach"]
                if isinstance(ex, tuple):
                    d, b, vv = (int(x) for x in ex)
                    if _num(r.get("villages")) != float(vv):
                        bad.append(f"{s} villages: row {r.get('villages')} expected {vv}")
                    if f"{indian(vv)} villages" not in text:
                        bad.append(f"{s} villages: '{indian(vv)} villages' not in the text")
                    if not c["f"] and (f"{indian(d)} districts" not in text or f"{indian(b)} blocks" not in text):
                        bad.append(f"{s} reach: '{indian(d)} districts, {indian(b)} blocks' not in the text")
                elif not gap_ok(text, s, ex):
                    bad.append(f"{s} coverage: expected gap {ex!r}, not said")
        if c["rank"] or (c["coverage"] and not c["f"]):
            kind = _rank_kind(c)
            key = {"count": "count", "money": "money", "villages": "reach"}[kind]
            cand = {}
            for s in c["schemes"]:
                v = E[s].get(key)
                if kind == "villages" and isinstance(v, tuple):
                    v = v[2]
                if isinstance(v, float) and v > 0:
                    cand[s] = v
            if len(cand) >= 2:
                best = max(cand.values())
                tops = {s for s, v in cand.items() if v == best}
                marker = {"count": " has the most ", "money": " has the most money", "villages": " has the most villages"}[kind]
                said = _bold_after(text, marker)
                if not said or scheme_of(said[0]) not in tops:
                    bad.append(f"ranking says {said[0] if said else 'nothing'}; top is {sorted(tops)}")
        return bad
    # grouped: one row per scheme and district / block
    grain = c["group"]
    for s in c["schemes"]:
        for kind in ("count", "money"):
            if not c[kind]:
                continue
            ex = E[s][kind]
            rs = {str(r.get(grain) or "").upper(): r for r in by.get(s, [])}
            col = "beneficiaries" if kind == "count" else "amount_crore"
            if not isinstance(ex, dict):
                if not gap_ok(text, s, ex):
                    bad.append(f"{s} {kind}: expected gap {ex!r}, not said")
                if any(_num(r.get(col)) for r in rs.values()):
                    bad.append(f"{s} {kind}: figures shown where none is held")
                continue
            if not rs:
                bad.append(f"{s} {kind}: no rows")
                continue
            for k, v in ex.items():
                if v and k.upper() not in rs:
                    bad.append(f"{s} {kind}: {k} missing")
            for k, r in rs.items():
                v = ex.get(k, ex.get(k.title(), 0.0)) or 0.0
                got = r.get(col)
                ok = (_num(got) == float(int(round(v)))) if kind == "count" else money_close(got, v)
                if not ok:
                    bad.append(f"{s} {kind} {k}: row {got} expected {v}")
                # a winner-per-district answer names the winner and the runner-up with
                # their figures; every scheme's figure is in the table (the rows)
                if kind == "count" and not c["leader"] and not c["topd"] and f"{indian(v)}" not in text:
                    bad.append(f"{s} {kind} {k}: {indian(v)} not in the text")
            if c["f"].get("districts") and grain == "district":
                extra_d = set(rs) - {d.upper() for d in c["f"]["districts"]}
                if extra_d:
                    bad.append(f"districts not asked shown: {sorted(extra_d)[:3]}")
    if c["leader"]:
        # per-district winner: "- K: **W** (…)" lines, and the headline
        want = [s for s in c["schemes"] if isinstance(E[s]["count"], dict)]
        keys = sorted({k for s in want for k in E[s]["count"]})
        per = {}
        for ln in text.splitlines():
            if ln.startswith("- ") and ": **" in ln:
                k, rest = ln[2:].split(": **", 1)
                per[k.strip().upper()] = scheme_of(rest.split("**")[0])
        if not per:
            bad.append("no per-district winner lines")
        for k in keys:
            vals = {s: (E[s]["count"] or {}).get(k, 0.0) for s in want}
            if vals and max(vals.values()) > 0:
                best = max(vals.values())
                tops = {s for s, v in vals.items() if v == best}
                if per.get(k.upper()) not in tops:
                    bad.append(f"leader {k}: {per.get(k.upper())} expected {sorted(tops)}")
        if "is highest in all" not in text and "Highest by district:" not in text:
            bad.append("no winner headline")
    if c["topd"]:
        # one ranked list per scheme, the top district first
        for s in c["schemes"]:
            ex = E[s]["count"]
            if not isinstance(ex, dict) or not ex or max(ex.values()) <= 0:
                continue
            best = max(ex.values())
            tops = {k.upper() for k, v in ex.items() if v == best}
            rs = sorted((r for r in by.get(s, []) if r.get("rank")), key=lambda r: r["rank"])
            got = str(rs[0].get("district") or "").upper() if rs else None
            if got not in tops:
                bad.append(f"top district {s}: {got} expected {sorted(tops)}")
            marker = f"**{s}** — Top "
            k = text.find(marker)
            if k == -1:
                bad.append(f"no ranked list for {s}")
            else:
                first = text[text.find("1. ", k) + 3:].split("\n")[0]
                if not any(first.upper().startswith(t.title().upper()) for t in tops):
                    bad.append(f"ranked list {s} starts with {first[:30]!r}, expected {sorted(tops)}")
    return bad
