"""Cross-scheme test run: the testers' 20 cases (every [district] / [block] they name
filled with every district / block) plus generated permutations — every combination
of 2..6 schemes, at state, district, block, village and constituency level, every
financial year, every question shape — through the live LangGraph pipeline, checked
cell by cell against truth.py.

Usage (repo root):  python tests/sheet_runs/cross/cross_run.py [FAMILY ...]
  families: sheet, state, year, district, dwise, rank, coverage, block, ac, village, words
  CROSS_OUT=<file> (default cross_results.json, resumable), CROSS_CONC (16),
  CROSS_ONLY=<file of case ids> re-runs just those cases, CROSS_LIMIT=n caps each family."""
import asyncio
import itertools
import json
import os
import sys
import time

sys.path.insert(0, ".")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from harness import Conv, fetch  # noqa: E402
from tests._text_checks import number_runs  # noqa: E402
import truth as T  # noqa: E402
from app import main as app_main  # noqa: E402
from app import pipeline as PL  # noqa: E402

OUT = os.path.join(HERE, os.environ.get("CROSS_OUT", "cross_results.json"))
SEM = asyncio.Semaphore(int(os.environ.get("CROSS_CONC", "16")))
LIMIT = int(os.environ.get("CROSS_LIMIT", "0"))
ORDER = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CM Elevate Legacy"]
COMBOS = [c for k in range(2, 7) for c in itertools.combinations(ORDER, k)]       # 57
RESULTS: dict = {}
LOG = open(os.path.join(HERE, "cross_run.log"), "a", encoding="utf-8")


def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.write(s + "\n")
    LOG.flush()


def fy(y, style=0):
    return [f"FY {y}-{str(y + 1)[2:]}", f"{y}-{str(y + 1)[2:]}", f"FY{y}-{str(y + 1)[2:]}", f"{y}-{y + 1}"][style % 4]


# ── naming ────────────────────────────────────────────────────────────────────

def name(s, combo, i):
    if s == "MGNREGA":
        return ["MGNREGA", "mgnrega", "NREGA", "MNREGA"][i % 4]
    if s == "PMAY-G":
        return ["PMAY-G", "pmay-g", "PMAY", "PMAY G"][i % 4]
    if s == "Focus Plus":
        return ["Focus+", "Focus Plus", "focus plus", "FocusPlus"][i % 4]
    if s == "Focus Legacy":
        forms = ["FOCUS", "Focus Legacy", "focus legacy", "Legacy Focus"] if "Focus Plus" in combo \
            else ["Focus Legacy", "focus legacy", "Legacy Focus", "FOCUS Legacy"]
        return forms[i % 4]
    if s == "CM Elevate":
        return ["CM Elevate applicants", "cm elevate applicants"][i % 2]
    if s == "CM Elevate Legacy":
        forms = ["CM-ELEVATE", "CM Elevate Legacy", "cm elevate legacy", "CM Elevate"] if "CM Elevate" not in combo \
            else ["CM Elevate Legacy", "cm elevate legacy", "CM-ELEVATE Legacy", "Legacy CM Elevate"]
        return forms[i % 4]


def joined(combo, i, sep_or=False):
    ns = [name(s, combo, i) for s in combo]
    if sep_or:
        return ", ".join(ns[:-1]) + " or " + ns[-1]
    if len(ns) == 2:
        return ["{} and {}", "{} vs {}", "{} & {}", "{} and {}"][i % 4].format(*ns)
    return ", ".join(ns[:-1]) + [" and ", ", and ", " & ", " and "][i % 4] + ns[-1]


# ── shapes: (template, count, money, coverage, rank, group, leader, topd) ──────
SHAPES = {
    "count": ["How many beneficiaries are there under {S}{P}{Y}?",
              "Compare the number of beneficiaries in {S}{P}{Y}.",
              "What is the beneficiary count across {S}{P}{Y}?",
              "Show the beneficiary/application count for {S}{P}{Y}."],
    "money": ["How much total amount has been disbursed under {S}{P}{Y}?",
              "Compare the total expenditure or disbursement under {S}{P}{Y}.",
              "How much money was spent or released under {S}{P}{Y}?"],
    "both": ["Compare {S} performance{P}{Y}.",
             "Compare the beneficiary count and total amount for {S}{P}{Y}.",
             "Give me a performance summary comparing {S}{P}{Y}."],
    "coverage": ["Compare the coverage of {S}{P}{Y}."],
    "rank_count": ["Which scheme has more beneficiaries{P}{Y}: {O}?"],
    "rank_money": ["Which scheme has a higher total financial disbursement{P}{Y}: {O}?"],
    "dw_count": ["Give me a district-wise comparison of beneficiaries under {S}{Y}.",
                 "Compare the number of beneficiaries in each district for {S}{Y}."],
    "dw_money": ["Compare the amount disbursed in each district under {S}{Y}."],
    "dw_both": ["Give me a district-wise summary comparing {S}{Y}."],
    "lead": ["For each district, identify which scheme among {S} has the highest beneficiary count{Y}.",
             "Which of {S} has the most beneficiaries in each district{Y}?"],
    "topd": ["Which districts have the highest number of beneficiaries under {S}{Y}?"],
    "bw_both": ["Compare {S} block-wise{P}{Y}."],
    "kb_all": ["{S}"],
}
FLAGS = {  # count, money, coverage, rank, group, leader, topd
    "count": (1, 0, 0, 0, None, 0, 0), "money": (0, 1, 0, 0, None, 0, 0), "both": (1, 1, 0, 0, None, 0, 0),
    "coverage": (1, 0, 1, 0, None, 0, 0), "rank_count": (1, 0, 0, 1, None, 0, 0),
    "rank_money": (0, 1, 0, 1, None, 0, 0), "dw_count": (1, 0, 0, 0, "district", 0, 0),
    "dw_money": (0, 1, 0, 0, "district", 0, 0), "dw_both": (1, 1, 0, 0, "district", 0, 0),
    "lead": (1, 0, 0, 0, "district", 1, 0), "topd": (1, 0, 0, 0, "district", 0, 1),
    "bw_both": (1, 1, 0, 0, "block", 0, 0),
    "kb_all": (0, 0, 0, 0, None, 0, 0),
}


def case(cid, fam, shape, combo, i, *, P="", Y="", f=None, level=None, place=None, code=None, q=None):
    tpl = SHAPES[shape][i % len(SHAPES[shape])]
    q = q or tpl.format(S=joined(combo, i), O=joined(combo, i, sep_or=True), P=P, Y=Y)
    c, m, cov, rk, grp, lead, topd = FLAGS[shape]
    combo = list(combo)
    # the product rule (user decision 2026-10-12, _pin_cm_elevate_dataset): a CM Elevate
    # named with money / FY words is the sanction-and-disbursement data (CM Elevate Legacy)
    if "CM Elevate" in combo and "CM Elevate Legacy" not in combo and PL._pin_cm_elevate_dataset(q) != q:
        combo = [("CM Elevate Legacy" if x == "CM Elevate" else x) for x in combo]
    return dict(id=cid, fam=fam, shape=shape, q=q, schemes=combo, f=f or {}, count=c, money=m,
                coverage=cov, rank=rk, group=grp, leader=lead, topd=topd, level=level, place=place, code=code)


# ── answer parsing ────────────────────────────────────────────────────────────

def scheme_of(cell):
    c = cell.lower()
    for k, s in (("focus legacy", "Focus Legacy"), ("focus plus", "Focus Plus"), ("cm elevate legacy", "CM Elevate Legacy"),
                 ("cm elevate", "CM Elevate"), ("mgnrega", "MGNREGA"), ("pmay", "PMAY-G")):
        if k in c:
            return s
    return None


def tables(text):
    out, cur, heading = [], None, None
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.startswith("|"):
            cells = [x.strip() for x in s.strip("|").split("|")]
            if cur is None:
                cur = dict(heading=heading, header=cells, rows=[])
                out.append(cur)
            elif set(s) <= set("|-: "):
                continue
            else:
                cur["rows"].append(cells)
        else:
            cur = None
            if len(s) >= 5 and s.startswith("**") and s.endswith("**"):   # a **bold** line
                heading = s[2:-2]
    return out


def money_val(cell, div=None):
    if div is not None:
        runs = number_runs(cell, signed=True, commas_first=True)
        return float(runs[0][2].replace(",", "")) * div if runs else None
    found = _rupees(cell)
    if not found:
        return None
    num, unit = found
    return float(num.replace(",", "")) * {"crore": 1e7, "lakh": 1e5, None: 1}[unit]


def _rupees(cell):
    """The first '₹ <digits/commas>[.<digits>] [crore|lakh]' in the cell ->
    (number text, 'crore' | 'lakh' | None), or None."""
    k = cell.find("₹")
    while k != -1:
        i = k + 1
        while i < len(cell) and cell[i].isspace():
            i += 1
        runs = number_runs(cell[i:], commas_first=True)
        if runs and runs[0][0] == 0:
            num = runs[0][2]
            j = i + len(num)
            while j < len(cell) and cell[j].isspace():
                j += 1
            unit = next((u for u in ("crore", "lakh") if cell.startswith(u, j)), None)
            return num, unit
        k = cell.find("₹", k + 1)
    return None


def _after_bold(text, label):
    """Every position just past '**<label>:**' and the whitespace after it,
    with the start of that whitespace: [(ws_start, ws_end), ...]."""
    marker = f"**{label}:**"
    out = []
    k = text.find(marker)
    while k != -1:
        a = b = k + len(marker)
        while b < len(text) and text[b].isspace():
            b += 1
        out.append((a, b))
        k = text.find(marker, k + 1)
    return out


def _bold_value(text, label, stop="\n"):
    """The run after '**<label>:**' (and its whitespace) up to the first char
    in `stop` (old regex: **label:**\\s*([^stop]+)). When nothing follows the
    whitespace on that line, the regex backed into the whitespace: the last
    non-newline whitespace char before it is the value."""
    for a, b in _after_bold(text, label):
        for start in range(b, a - 1, -1):
            if start < b and text[start] == "\n":
                continue
            end = start
            while end < len(text) and text[end] not in stop and text[end] != "\n":
                end += 1
            if end > start:
                return text[start:end]
    return None


def _bold_lead(text, label):
    """The shortest run (no newline) after '**<label>:**' and its whitespace
    that is followed by ' at ' or ' with ' (old regex: **label:**\\s*([^\\n]+?)(?: at | with ))."""
    for a, b in _after_bold(text, label):
        for start in range(b, a - 1, -1):
            if start < b and text[start] == "\n":
                continue
            line_end = text.find("\n", start)
            line_end = len(text) if line_end == -1 else line_end
            hits = [k for k in (text.find(" at ", start + 1), text.find(" with ", start + 1))
                    if k != -1 and k <= line_end]
            if hits:
                return text[start:min(hits)]
    return None


def _first_bold(text):
    """The text of the first **bold** span on one line (old regex \\*\\*(.+?)\\*\\*)."""
    i = text.find("**")
    while i != -1:
        j = text.find("**", i + 3)
        if j != -1 and "\n" not in text[i + 2:j]:
            return text[i + 2:j]
        if j == -1:
            return None
        i = text.find("**", i + 1)
    return None


def money_ok(got, exp, unit):
    return got is not None and abs(got - exp) <= max(unit * 0.0051, abs(exp) * 0.0005)


def first_int(cell):
    runs = number_runs(cell)
    if not runs:
        return None
    digits = runs[0][2].split(".")[0]          # \d[\d,]* stops before any decimal part
    return int(digits.replace(",", ""))


def unit_of(v):
    return 1e7 if abs(v) >= 1e7 else (1e5 if abs(v) >= 1e5 else 1)


def check_single(c, exp, cell, kind):
    """One scheme's cell in the one-row-per-scheme table."""
    if exp == T.NO_MONEY:
        return "no money recorded" in cell.lower()
    if exp == T.NOT_RECORDED:
        return "not recorded" in cell.lower()
    if exp == T.NO_YEAR:
        return cell.strip() in ("—", "-") or "no data" in cell.lower() or "not recorded by financial year" in cell.lower()
    if not exp:
        return "no records" in cell.lower()
    if kind == "count":
        return first_int(cell) == int(round(exp))
    return money_ok(money_val(cell), exp, unit_of(exp))


async def expected(c):
    E = {}
    for s in c["schemes"]:
        E[s] = {}
        for kind in ("count", "money"):
            if c[kind]:
                E[s][kind] = await T.truth(s, kind, c["f"], c["group"])
        if c["coverage"]:
            E[s]["reach"] = await T.reach(s, c["f"]) if not (c["f"].get("year") and (
                not T.S[s]["year"] or int(c["f"]["year"]) not in T.YEARS.get(s, set()))) else T.NO_YEAR
    return E


def check(c, rec, E):
    """[] when the answer is right, else the list of what is wrong."""
    bad = []
    text = rec.get("answer") or ""
    if c["shape"] == "kb_all":   # a conceptual comparison of every scheme (knowledge path)
        miss = [s for s in ORDER if f"**{s}**" not in text]
        return [f"knowledge comparison misses {miss}"] if miss else []
    tbs = tables(text)
    if not c["group"]:
        tb = next((t for t in tbs if t["header"] and t["header"][0].lower() == "scheme"), None)
        if not tb:
            return ["no per-scheme table"]
        hdr = [h.lower() for h in tb["header"]]
        rows = {scheme_of(r[0]): r for r in tb["rows"]}
        if set(rows) != set(c["schemes"]):
            bad.append(f"schemes shown {sorted(k for k in rows if k)} != asked {sorted(c['schemes'])}")
        for s in c["schemes"]:
            r = rows.get(s)
            if not r:
                continue
            for kind, col in (("count", "beneficiaries / applications"), ("money", "amount")):
                if not c[kind]:
                    continue
                if col not in hdr:
                    bad.append(f"no {kind} column")
                    continue
                cell = r[hdr.index(col)]
                if not check_single(c, E[s][kind], cell, kind):
                    bad.append(f"{s} {kind}: '{cell}' expected {E[s][kind]}")
            if c["coverage"]:
                ex = E[s]["reach"]
                if "districts" not in hdr:
                    bad.append("no coverage columns")
                elif isinstance(ex, tuple):
                    got = tuple(first_int(r[hdr.index(k)]) for k in ("districts", "blocks", "villages"))
                    if got != tuple(int(x) for x in ex):
                        bad.append(f"{s} reach {got} expected {ex}")
        if c["rank"]:
            kind = "money" if c["money"] else "count"
            cand = {s: E[s][kind] for s in c["schemes"] if isinstance(E[s].get(kind), float) and E[s][kind]}
            if cand:
                top = max(cand, key=cand.get)
                lab = "Highest amount" if kind == "money" else "Highest count"
                said = _bold_lead(text, lab)
                if said is None or scheme_of(said) != top:
                    bad.append(f"ranking says {said if said is not None else 'nothing'}; top is {top}")
        if c["coverage"] and not c["f"]:
            cand = {s: E[s]["reach"] for s in c["schemes"] if isinstance(E[s]["reach"], tuple)}
            top_v = max((v[0], v[2]) for v in cand.values())
            tops = {s for s, v in cand.items() if (v[0], v[2]) == top_v}
            said = _bold_value(text, "Widest coverage", stop="\n—")
            if said is None or scheme_of(said) not in tops:
                bad.append(f"widest says {said if said is not None else 'nothing'}; expected {tops}")
        return bad
    # grouped (district / block matrices)
    unit = c["group"]
    for kind in ("count", "money"):
        if not c[kind]:
            continue
        tb = next((t for t in tbs if t["header"] and t["header"][0].lower() == unit
                   and ((t["heading"] or "").lower().startswith("amount") == (kind == "money"))), None)
        if not tb:
            bad.append(f"no {unit} {kind} table")
            continue
        div = None
        if kind == "money":
            h = (tb["heading"] or "").lower()
            div = 1e7 if "crore" in h else (1e5 if "lakh" in h else 1.0)
        cols = {scheme_of(h): i for i, h in enumerate(tb["header"]) if i and scheme_of(h)}
        want = [s for s in c["schemes"] if not (kind == "money" and E[s][kind] == T.NO_MONEY)]
        if set(cols) != set(want):
            bad.append(f"{kind} columns {sorted(cols)} != {sorted(want)}")
        rowkeys = {r[0].upper(): r for r in tb["rows"]}
        for s in want:
            ex = E[s][kind]
            if s not in cols:
                continue
            if not isinstance(ex, dict):
                if not all(r[cols[s]] in ("—", "-") for r in tb["rows"]):
                    bad.append(f"{s} {kind} should be '—' ({ex})")
                continue
            for k, v in ex.items():
                if v and k.upper() not in rowkeys:
                    bad.append(f"{s} {kind}: {k} missing")
            for k, r in rowkeys.items():
                v = ex.get(k, ex.get(k.title(), 0.0)) or 0.0
                cell = r[cols[s]]
                ok = first_int(cell) == int(round(v)) if kind == "count" else money_ok(money_val(cell, div), v, div)
                if not ok:
                    bad.append(f"{s} {kind} {k}: '{cell}' expected {v}")
            if c["f"].get("districts") and c["group"] == "district":
                extra = set(rowkeys) - {d.upper() for d in c["f"]["districts"]}
                if extra:
                    bad.append(f"districts not asked shown: {sorted(extra)[:3]}")
        if c["leader"] and kind == "count":
            if "leading scheme" not in [h.lower() for h in tb["header"]]:
                bad.append("no leading-scheme column")
            else:
                li = [h.lower() for h in tb["header"]].index("leading scheme")
                for k, r in rowkeys.items():
                    vals = {s: (E[s]["count"] or {}).get(k, 0.0) for s in want if isinstance(E[s]["count"], dict)}
                    if vals and max(vals.values()) > 0:
                        best = max(vals.values())
                        if scheme_of(r[li]) not in {s for s, v in vals.items() if v == best}:
                            bad.append(f"leader {k}: {r[li]}")
    if c["topd"]:
        line = _bold_value(text, "Highest district per scheme")
        if line is None:
            bad.append("no highest-district line")
        else:
            seg = {scheme_of(x.split(":")[0]): x for x in line.split(";")}
            for s in c["schemes"]:
                ex = E[s]["count"]
                if isinstance(ex, dict) and ex and max(ex.values()) > 0:
                    best = max(ex.values())
                    tops = {k.upper() for k, v in ex.items() if v == best}
                    got = _first_bold(seg.get(s, ""))
                    if got is None or got.upper() not in tops:
                        bad.append(f"top district {s}: {got if got is not None else 'missing'} expected {tops}")
    return bad


# ── running ───────────────────────────────────────────────────────────────────

def pick_chip(c, rec):
    rule, labels, qs = rec.get("rule"), rec.get("options") or [], rec.get("option_qs") or []
    if rule == "entity-ambiguous" and c.get("place"):
        want = [w.lower() for w in c["place"] if w]
        cand = [(l, q) for l, q in zip(labels, qs) if want[0] in (l + " " + (q or "")).lower()]
        if c.get("level"):
            lv = [(l, q) for l, q in cand if c["level"] in l.lower()]
            cand = lv or cand
        if len(want) > 1:
            # "— MAIRANG block", not the substring of "MAIRANG-TOWN COMMITTEE" or "Rongramgre"
            bk = [(l, q) for l, q in cand if f"— {want[1]} block" in l.lower()]
            cand = bk or cand
        if c.get("code") is not None:
            cc = [(l, q) for l, q in cand if f"LGD {c['code']}" in (l + " " + (q or ""))]
            cand = cc or cand
        return (cand[0][1], f"asked {rule} -> {cand[0][0]}") if cand else (None, f"no chip for {want}: {labels[:5]}")
    if rule == "year-not-specified":
        y = c["f"].get("year")
        lab = f"FY {y}-{str(y + 1)[2:]}" if y else "all "
        p = next((q for l, q in zip(labels, qs) if l.lower().startswith(lab.lower())), None)
        return p, "NEEDLESS year pause"
    if rule == "scope-not-specified":
        p = next((q for l, q in zip(labels, qs) if "all of meghalaya" in l.lower()), None)
        return p, "NEEDLESS area pause"
    if rule in ("scheme-not-specified",):
        p = next((q for l, q in zip(labels, qs) if l.lower().startswith("compare")), None)
        return p, "NEEDLESS scheme pause"
    return None, f"unanswerable pause {rule}: {labels[:5]}"


async def run(c):
    async with SEM:
        conv = Conv()
        rec = await conv.ask(c["q"])
        notes, needless = [], False
        for _ in range(3):
            if rec["kind"] != "pause":
                break
            p, note = pick_chip(c, rec)
            notes.append(note)
            needless |= note.startswith("NEEDLESS") or note.startswith("unanswerable") or note.startswith("no chip")
            # a place pause on a non-village level, or on a village we named with its block, is needless
            if rec.get("rule") == "entity-ambiguous" and c.get("level") != "village":
                needless = True
                notes[-1] = "NEEDLESS " + notes[-1]
            if not p:
                break
            rec = await conv.ask(p)
        try:
            E = await expected(c)
        except Exception as e:  # noqa: BLE001
            E, bad = None, [f"truth error {e}"]
        if E is not None:
            bad = check(c, rec, E) if rec["kind"] == "answer" else [f"ended in {rec['kind']} {rec.get('rule') or ''}: {(rec.get('answer') or '')[:120]}"]
            if bad and rec["kind"] == "answer" and c["f"].get("village"):
                # a same-name twin in the same block: when the village asked about holds no
                # record of the asked schemes, the twin that does is the one the name can mean
                held = any(isinstance(v, float) and v for e in E.values() for v in e.values())
                if not held:
                    for tw in await fetch("""SELECT g2.village_code c FROM curated.dim_geography g1
                            JOIN curated.dim_geography g2 ON UPPER(g2.lgd_village_name) = UPPER(g1.lgd_village_name)
                            AND g2.lgd_block IS NOT DISTINCT FROM g1.lgd_block AND g2.lgd_district IS NOT DISTINCT FROM g1.lgd_district
                            WHERE g1.village_code = $1 AND g2.village_code <> $1""", [c["f"]["village"]]):
                        c2 = {**c, "f": {**c["f"], "village": tw["c"]}}
                        if not check(c2, rec, await expected(c2)):
                            notes.append(f"answered for same-name twin LGD {tw['c']} (the asked code holds no record of these schemes)")
                            bad = []
                            break
        if sum(1 for t in conv.turns if t.get("rule") == "entity-ambiguous") > 1:
            needless = True        # a chip must settle the place; asking again is a loop
            notes.append("NEEDLESS repeated which-place pause")
        if needless:
            bad = ["needless pause"] + bad
        RESULTS[c["id"]] = {**{k: c[k] for k in ("fam", "shape", "q", "schemes", "level")}, "f": c["f"],
                            "ok": not bad, "bad": bad, "notes": notes,
                            "turns": [{k: t.get(k) for k in ("q", "kind", "rule", "answer", "options", "ms", "schemes")} for t in conv.turns]}
        log(f"{c['id']} | {'OK ' if not bad else 'BAD'} | {c['q'][:110]} | {'; '.join(notes)} | {'; '.join(bad)[:300]}")


# ── case families ─────────────────────────────────────────────────────────────

SHEET_D = ["CROSS-8", "CROSS-11", "CROSS-14"]


async def build(fams):
    dists = [r["d"] for r in await fetch("SELECT DISTINCT lgd_district d FROM curated.dim_geography WHERE lgd_district IS NOT NULL ORDER BY 1")]
    blocks = await fetch("""SELECT b, MIN(d) d FROM (
        SELECT lgd_block b, lgd_district d FROM curated.v_employment UNION ALL SELECT lgd_block, lgd_district FROM curated.v_pmay
        UNION ALL SELECT lgd_block, lgd_district FROM curated.v_focus_plus UNION ALL SELECT lgd_block, lgd_district FROM curated.v_focus_legacy
        UNION ALL SELECT lgd_block, lgd_district FROM curated.v_cm_elevate UNION ALL SELECT lgd_block, lgd_district FROM curated.v_cm_elevate_disbursement) u
        WHERE b IS NOT NULL GROUP BY 1 ORDER BY 1""")
    acs = [r["a"] for r in await fetch("SELECT DISTINCT ac_name a FROM curated.dim_geography WHERE ac_name IS NOT NULL ORDER BY 1")]
    C = []
    tc = lambda s: s.title() if s else s  # noqa: E731
    if "sheet" in fams:
        base = {
            "CROSS-1": ("count", ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy"], "What is the beneficiary count across MGNREGA, PMAY-G, Focus+, and FOCUS?"),
            "CROSS-2": ("count", ["Focus Plus", "Focus Legacy"], "Compare the number of beneficiaries in Focus+ and FOCUS."),
            "CROSS-3": ("dw_count", ["Focus Plus", "CM Elevate Legacy"], "Compare the performance of Focus+ and CM-ELEVATE across districts based on beneficiary/application counts."),
            "CROSS-4": ("money", ["Focus Plus", "Focus Legacy", "CM Elevate Legacy"], "How much total amount has been disbursed under Focus+, FOCUS, and CM-ELEVATE?"),
            "CROSS-5": ("rank_money", ["Focus Plus", "CM Elevate Legacy"], "Which scheme has a higher total financial disbursement: Focus+ or CM-ELEVATE?"),
            "CROSS-6": ("dw_count", ["Focus Plus", "Focus Legacy", "CM Elevate Legacy"], "Compare the number of beneficiaries/applications in each district for Focus+, FOCUS, and CM-ELEVATE."),
            "CROSS-7": ("lead", ORDER, "Which scheme has the highest beneficiary or application count in each district?"),
            "CROSS-10": ("money", ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate Legacy"], "Compare the total expenditure or disbursement under MGNREGA, PMAY-G, Focus+, and CM-ELEVATE."),
            "CROSS-12": ("rank_money", ORDER, "Which scheme provided the highest total financial assistance across Meghalaya?"),
            "CROSS-13": ("coverage", ORDER, "Which scheme has the widest coverage across districts of Meghalaya?"),
            "CROSS-15": ("topd", ORDER, "Which districts have the highest concentration of beneficiaries or applications across the schemes?"),
            "CROSS-17": ("dw_both", ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate Legacy"], "Give me a district-wise summary comparing MGNREGA, PMAY-G, Focus+, FOCUS, and CM-ELEVATE."),
            "CROSS-18": ("lead", ORDER, "For each district, identify which scheme has the highest beneficiary/application count."),
            "CROSS-19": ("both", ["Focus Plus", "Focus Legacy", "CM Elevate Legacy"], "Compare the beneficiary/application count and total financial amount for Focus+, FOCUS, and CM-ELEVATE."),
            "CROSS-20": ("both", ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate Legacy"], "Give me an overall performance comparison of MGNREGA, PMAY-G, Focus+, FOCUS, and CM-ELEVATE based on coverage and financial performance."),
        }
        for k, (shape, combo, q) in base.items():
            cc = case(k, "sheet", shape, combo, 0, q=q)
            if k == "CROSS-20":
                cc.update(coverage=1)
            C.append(cc)
        for i, d in enumerate(dists):
            C.append(case(f"CROSS-8|{d}", "sheet", "both", ["Focus Plus", "Focus Legacy", "CM Elevate Legacy"], 0,
                          q=f"Compare Focus+, FOCUS, and CM-ELEVATE performance in {tc(d)}.", f={"districts": [d]}))
            C.append(case(f"CROSS-11|{d}", "sheet", "money", ORDER, 0,
                          q=f"How much financial assistance or expenditure was recorded under each scheme in {tc(d)}?",
                          f={"districts": [d]}))
            C.append(case(f"CROSS-14|{d}", "sheet", "both", ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate Legacy"], 0,
                          q=f"What is the performance of MGNREGA, PMAY-G, Focus+, and CM-ELEVATE in {tc(d)}?",
                          f={"districts": [d]}))
        for b in blocks:
            C.append(case(f"CROSS-9|{b['b']}", "sheet", "coverage", ["MGNREGA", "PMAY-G", "CM Elevate Legacy"], 0,
                          q=f"Compare the coverage of MGNREGA, PMAY-G, and CM-ELEVATE in {tc(b['b'])} block.",
                          f={"block": b["b"]}, level="block", place=[b["b"]]))
        for i, trio in enumerate(itertools.combinations(dists, 3)):
            if i % 11:
                continue
            C.append(case(f"CROSS-16|{'/'.join(trio)}", "sheet", "count", ["Focus Plus", "CM Elevate Legacy"], 0,
                          q=f"Compare Focus+ and CM-ELEVATE beneficiary/application counts across {tc(trio[0])}, {tc(trio[1])}, and {tc(trio[2])}.",
                          f={"districts": list(trio)}))
            C[-1]["group"] = "district"
    if "state" in fams:   # every combination x count / money / both, statewide
        for i, combo in enumerate(COMBOS):
            for j, shape in enumerate(("count", "money", "both")):
                P = ["", " in Meghalaya", " across Meghalaya", ""][(i + j) % 4]
                C.append(case(f"ST-{shape}-{i:02d}", "state", shape, combo, i + j, P=P))
    if "rank" in fams:    # every combination: which is higher (count, money)
        for i, combo in enumerate(COMBOS):
            C.append(case(f"RK-c-{i:02d}", "rank", "rank_count", combo, i))
            C.append(case(f"RK-m-{i:02d}", "rank", "rank_money", combo, i))
    if "coverage" in fams:
        for i, combo in enumerate(COMBOS):
            C.append(case(f"CV-{i:02d}", "coverage", "coverage", combo, i))
    if "year" in fams:    # every FY x every combination (shape rotates), statewide
        for y in range(2017, 2026):
            for i, combo in enumerate(COMBOS):
                if (i + y) % 3:
                    continue
                shape = ("count", "money", "both", "dw_count")[(i + y) % 4]
                C.append(case(f"YR-{y}-{i:02d}", "year", shape, combo, i, Y=" in " + fy(y, i), f={"year": y}))
    if "district" in fams:   # every district x every combination
        for di, d in enumerate(dists):
            for i, combo in enumerate(COMBOS):
                shape = ("count", "money", "both", "rank_money", "rank_count", "coverage")[(i + di) % 6]
                dn = [d.title(), d.lower(), d.upper()][(i + di) % 3]
                y = (2024, None, None, 2022, None)[(i + di) % 5]
                C.append(case(f"DI-{di:02d}-{i:02d}", "district", shape, combo, i + di, P=f" in {dn}",
                              Y=(" in " + fy(y, i)) if y else "", f={"districts": [d], **({"year": y} if y else {})},
                              level="district", place=[d]))
    if "dwise" in fams:      # every combination, district-wise / leader / top districts
        for i, combo in enumerate(COMBOS):
            shape = ("dw_count", "dw_money", "dw_both", "lead", "topd")[i % 5]
            C.append(case(f"DW-{i:02d}", "dwise", shape, combo, i))
        for di, d in enumerate(dists):
            combo = COMBOS[(di * 7) % len(COMBOS)]
            C.append(case(f"BW-{di:02d}", "dwise", "bw_both", combo, di, P=f" in {d.title()}", f={"districts": [d]}))
    if "block" in fams:      # every block, two combinations each
        for bi, b in enumerate(blocks):
            for j in range(2):
                combo = COMBOS[(bi * 5 + j * 23) % len(COMBOS)]
                shape = ("count", "money", "both", "coverage")[(bi + j) % 4]
                bn = [b["b"].title(), b["b"].lower(), b["b"].upper()][(bi + j) % 3]
                C.append(case(f"BL-{bi:03d}-{j}", "block", shape, combo, bi + j, P=f" in {bn} block",
                              f={"block": b["b"]}, level="block", place=[b["b"]]))
    if "ac" in fams:         # every assembly constituency
        for ai, a in enumerate(acs):
            for j in range(2):
                combo = COMBOS[(ai * 3 + j * 29) % len(COMBOS)]
                shape = ("count", "money", "both")[(ai + j) % 3]
                C.append(case(f"AC-{ai:02d}-{j}", "ac", shape, combo, ai + j, P=f" in {a} constituency",
                              f={"ac": a}, level="constituency", place=[a]))
    if "village" in fams:    # every village any scheme holds, one question each
        vills = await fetch("""SELECT g.village_code c, MIN(g.lgd_village_name) n, MIN(g.lgd_block) b, MIN(g.lgd_district) d
            FROM curated.dim_geography g WHERE g.village_code IN (
              SELECT village_code FROM curated.v_employment UNION SELECT village_code FROM curated.v_pmay
              UNION SELECT village_code FROM curated.v_focus_plus WHERE village_code > 0
              UNION SELECT village_code FROM curated.v_focus_legacy UNION SELECT village_code FROM curated.v_cm_elevate
              UNION SELECT village_code FROM curated.v_cm_elevate_disbursement)
            AND g.lgd_village_name IS NOT NULL AND g.village_code > 0
            AND g.lgd_village_name !~* '^unresolved' GROUP BY 1 ORDER BY 1""")
        for vi, v in enumerate(vills):
            combo = COMBOS[(vi * 13) % len(COMBOS)]
            shape = ("count", "money", "both")[vi % 3]
            vn = [v["n"].upper(), v["n"].title(), v["n"].lower()][vi % 3]
            C.append(case(f"VI-{v['c']}", "village", shape, combo, vi, P=f" in {vn} village",
                          f={"village": v["c"]}, level="village", place=[v["n"], v["b"] or ""], code=v["c"]))
    if "words" in fams:      # phrasing variants on a fixed pair / triple
        W = ["mgnrega vs pmay-g beneficiaries", "Compare nrega and pmay beneficiaries",
             "focus plus vs focus legacy: who has more beneficiaries?", "Which is bigger, Focus+ or FOCUS, by amount disbursed?",
             "beneficiaries of MGNREGA, PMAY-G and Focus Plus side by side", "Compare MGNREGA with PMAY-G in terms of money",
             "MGNREGA & PMAY-G expenditure comparison", "show pmay-g and cm elevate legacy numbers",
             "How do Focus Plus and CM Elevate Legacy compare?", "Compare all six schemes", "Compare all schemes by amount",
             "Give me a scheme-wise comparison of beneficiaries", "Compare the schemes district-wise"]
        shapes = ["count", "count", "rank_count", "rank_money", "count", "money", "money", "both", "both", "both",
                  "money", "count", "dw_both"]
        shapes[9] = "kb_all"
        combos = [("MGNREGA", "PMAY-G"), ("MGNREGA", "PMAY-G"), ("Focus Plus", "Focus Legacy"), ("Focus Plus", "Focus Legacy"),
                  ("MGNREGA", "PMAY-G", "Focus Plus"), ("MGNREGA", "PMAY-G"), ("MGNREGA", "PMAY-G"),
                  ("PMAY-G", "CM Elevate Legacy"), ("Focus Plus", "CM Elevate Legacy"), tuple(ORDER), tuple(ORDER),
                  tuple(ORDER), tuple(ORDER)]
        for i, (q, sh, cb) in enumerate(zip(W, shapes, combos)):
            C.append(case(f"WD-{i:02d}", "words", sh, cb, 0, q=q))
    if LIMIT:
        by: dict = {}
        for c in C:
            by.setdefault(c["fam"], []).append(c)
        C = [c for v in by.values() for c in v[:LIMIT]]
    return C


async def main():
    fams = sys.argv[1:] or ["sheet"]
    async with app_main.lifespan(app_main.app):
        await T.load()
        cases = await build(fams)
        if os.path.exists(OUT):
            RESULTS.update(json.load(open(OUT, encoding="utf-8")))
        only = None
        if os.environ.get("CROSS_ONLY"):
            only = set(open(os.environ["CROSS_ONLY"], encoding="utf-8").read().split("\n")) - {""}
        todo = [c for c in cases if (c["id"] in only if only is not None else c["id"] not in RESULTS)]
        log(f"families {fams}: {len(cases)} cases, {len(todo)} to run")
        for k in range(0, len(todo), 100):
            await asyncio.gather(*[run(c) for c in todo[k:k + 100]])
            json.dump(RESULTS, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            done = [RESULTS[c["id"]] for c in cases if c["id"] in RESULTS]
            log(f"checkpoint {min(k + 100, len(todo))}/{len(todo)} — pass {sum(r['ok'] for r in done)}/{len(done)}")
    done = [RESULTS[c["id"]] for c in cases if c["id"] in RESULTS]
    log(f"DONE {fams}: pass {sum(r['ok'] for r in done)}/{len(done)}")


if __name__ == "__main__":
    asyncio.run(main())
