"""MGNREGA sheet UAT round (2026-10-30): DATA-001..DATA-030 through the live LangGraph pipeline,
every expected figure from megh_db, on the CURRENT rules:
- no year in the question -> all financial years combined, answered at once (D-089 "answer with
  defaults"); a year pause is a defect. Job cards are a stock: no year -> the latest year's figure.
  Women employment is not recorded for FY 2025-26: that year must say so; "all years" = 2022-23..2024-25.
- a "which scheme?" pause is a defect (every sheet measure is MGNREGA-only).
- hygiene on every answer: no refusal, no village code printed with digit grouping ("9,04,714").

Coverage (Step 4 of reference_documents/README.md): each sheet shape at its own level for EVERY
district / block / assembly constituency x every FY (rotating year formats) + no year; the village
shapes at every district and block (cross-level); state level; rankings every FY + all years;
24 sample villages x all 12 village shapes x every year option; same-name villages.
Every village (6,491) is mg_uat_villages.py.

Usage (repo root, VPN): .venv/Scripts/python.exe -X utf8 tests/sheet_runs/mg_uat.py <out.json> [part ...]
parts: sheet district block ac rank state cross village dups   (default: all)
MGU_ONLY="DATA-004 DATA-014" limits to test cases. Score: mg_uat_score.py <out.json>"""
import asyncio
import json
import os
import sys

OUTP, PARTS = None, set()
if __name__ == "__main__":
    OUTP = sys.argv[1]
    PARTS = set(sys.argv[2:]) or {"district", "block", "ac", "rank", "state", "cross", "village", "dups"}
    sys.argv = sys.argv[:1]
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Conv, close, fetch, numbers_in, text_numbers  # noqa: E402
from tests._text_checks import first_of, has_phrase, no_near, word_chars_only, zero_lakh  # noqa: E402

SEM = asyncio.Semaphore(int(os.environ.get("MG_CONC", "5")))
ONLY = set(os.environ.get("MGU_ONLY", "").split())
RESULTS: dict = {}
YEARS = [2022, 2023, 2024, 2025]
YOPTS = YEARS + [None]                          # None = no year in the question (all years)
WOMEN_YEARS = [2022, 2023, 2024]                # FY 2025-26 women employment not recorded at source
NOT_REC = ("not recorded", "not been recorded", "not available", "unrecorded", "not captured",
           "isn't recorded", "is not recorded", "wasn't recorded", "no women employment")
EMP_COLS = ["households_employed", "persons_employed", "person_days", "job_cards_issued_total",
            "households_completed_100_days", "women_employment_provided"]
EXP_COLS = ["total_exp", "unskilled_wage_exp", "semi_skilled_wage_exp", "material_exp", "admin_total_exp"]


def log(*a):
    print(*a, flush=True)


def fy(y, style=0):
    a, b = y, y + 1
    return [f"{a}-{str(b)[2:]}", f"{a}-{b}", f"FY {a}-{str(b)[2:]}", f"{str(a)[2:]}-{str(b)[2:]}",
            f"financial year {a}-{str(b)[2:]}"][style % 5]


def fy_label(y):
    return f"FY {y}-{str(y + 1)[2:]}" if y else "all years"


def during(y, style):
    return f" during {fy(y, style)}" if y else ""


def vals(rec):
    return numbers_in(rec.get("rows")) + text_numbers(rec.get("answer"))


def has(rec, expected, rel=0.005, money=False):
    if expected is None:
        return False
    forms = [expected] + ([expected / 100.0, expected * 100000.0] if money else [])
    return any(close(c, f, rel) for c in vals(rec) for f in forms)


def has_name(rec, name):
    blob = (rec.get("answer") or "") + " " + json.dumps(rec.get("rows") or [], default=str)
    return word_chars_only(name).lower() in word_chars_only(blob).lower()


def _indian(n):
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def hygiene(rec):
    """Defects any answer must not have, whatever the figure."""
    a = rec.get("answer") or ""
    out = []
    if a.startswith("Sorry, I can") or "couldn't build a working query" in a:
        out.append("refused / no query")
    for r in rec.get("rows") or []:
        code = r.get("village_code")
        if isinstance(code, int) and code >= 1000:
            if _indian(code) in a or f"{code:,}" in a:
                out.append(f"village code {code} printed with digit grouping")
                break
    return out


# ── the conversation driver ─────────────────────────────────────────────────
async def run_case(tc, label, question, check, *, year=None, place=None, level=None, expected=None, code=None):
    """check(rec) -> (ok, note). A pause is answered as a user tapping the right chip; a year or
    scheme pause is recorded as a defect (both are answered without asking on the current rules)."""
    if ONLY and tc not in ONLY:
        return
    async with SEM:
        c = Conv()
        rec = await c.ask(question)
        notes, defects = [], []
        for _ in range(3):
            if rec["kind"] != "pause":
                break
            rule, labels, qs = rec.get("rule"), rec.get("options") or [], rec.get("option_qs") or []
            pick = None
            if rule == "year-not-specified":
                defects.append("needless year pause")
                if year is None:
                    pick = next((q for l, q in zip(labels, qs) if l.lower().startswith("all ")), None)
                else:
                    pick = next((q for l, q in zip(labels, qs) if l == fy_label(year)), None)
            elif rule in ("scheme-not-specified", "scheme-not-available"):
                defects.append("asked which scheme (MGNREGA-only measure)")
                pick = next((q for l, q in zip(labels, qs) if l.startswith("MGNREGA")), None)
            elif rule == "scope-not-specified" and not place:
                defects.append("asked area (should default to statewide)")
                pick = next((q for l, q in zip(labels, qs) if "meghalaya" in l.lower() or "statewide" in l.lower()), None)
            elif rule == "ranking-count-not-specified":
                pick = next((q for l, q in zip(labels, qs) if l.lower() == "top 5"), None)
            elif rule == "ac-narrow-scope":
                defects.append("whole-or-part constituency pause after 'constituency' was typed")
                pick = next((q for l, q in zip(labels, qs) if l.lower().startswith("the whole")), None)
            elif rule == "village-or-outside-place":
                pick = next((q for l, q in zip(labels, qs) if "village" in l.lower()), None)
            elif rule in ("entity-ambiguous", "scope-not-specified", "region-needs-district") and place:
                want = [w.lower() for w in place if w]
                cand = [(l, q) for l, q in zip(labels, qs) if all(w in (l + " " + (q or "")).lower() for w in want[:1])]
                if level:
                    lv = [(l, q) for l, q in cand if level.replace("ac", "constituency") in l.lower()]
                    cand = lv or cand
                if len(want) > 1:
                    bk = [(l, q) for l, q in cand if f"{want[1]} block" in (l + " " + (q or "")).lower()]
                    cand = bk or cand
                if code is not None:
                    cc = [(l, q) for l, q in cand if f"LGD {code}" in (l + " " + (q or ""))]
                    cand = cc or cand
                pick = cand[0][1] if cand else None
                notes.append(f"asked {rule} -> {cand[0][0] if cand else 'NO MATCHING OPTION'}")
                if not cand:
                    defects.append(f"which-place pause without the right option: {labels[:6]}")
            if not pick:
                notes.append(f"unanswerable pause {rule}: {labels[:6]}")
                break
            rec = await c.ask(pick)
        twins = (rec.get("entities") or {}).get("village_twins") if rec["kind"] == "answer" else None
        if twins and code is not None:
            # J-10 (D-089): a shared name is answered one row per village; this village's own row
            # carries the figure (no row = no record that year)
            mine = [r for r in rec.get("rows") or [] if str(r.get("village_code")) == str(code)]
            # the per-twin answer ("**Dipogre (Baghmara block)**\n…") is judged on its own section:
            # the wages-vs-materials verdict of another twin must not be read as this one's
            ans, label = rec.get("answer") or "", twins.get(str(code)) or ""
            head = ans.find(f"**{label}**") if label else -1
            if head >= 0:
                tail = ans.find("\n**", head + 4)
                ans = ans[head:tail if tail > 0 else None]
            ok, note = check(dict(rec, rows=mine or [{"village_code": code}], answer=ans))
            note += f" [twins {sorted(twins)}]"
        elif rec["kind"] == "answer" or (rec.get("rule") == "year-out-of-range"):
            ok, note = check(rec)
        else:
            ok, note = False, f"ended in {rec['kind']} {rec.get('rule') or ''}"
        ents = rec.get("entities") or {}
        level_ok = None
        if level and rec["kind"] == "answer" and ok:
            level_ok = {"district": bool(ents.get("district")) and not ents.get("block") and not ents.get("village_code"),
                        "block": bool(ents.get("block")) and not ents.get("village_code"),
                        "village": bool(ents.get("village_code") or ents.get("village_code_list")),
                        }.get(level, True)
        hyg = hygiene(rec) if rec["kind"] == "answer" else []
        good = bool(ok) and level_ok is not False and not defects and not hyg
        RESULTS.setdefault(tc, []).append({
            "label": label, "q": question, "turns": c.turns, "expected": expected, "ok": good,
            "value_ok": bool(ok), "level_ok": level_ok, "note": note, "pause_notes": notes,
            "defects": defects + hyg, "code": code})
        log(f"{tc} | {label} | {'OK ' if good else 'BAD'} | {'; '.join(defects + hyg + notes)} | "
            f"{note} | {(rec.get('answer') or '')[:110]!r}")


# ── checks ──────────────────────────────────────────────────────────────────
def zero_ok(chk, expected):
    """A place with no record for the year: 0 stated, or 'no record' said plainly."""
    def wrapped(rec):
        ok, note = chk(rec)
        if ok:
            return ok, note
        zero = (expected == 0) or (isinstance(expected, dict) and not any(v for v in expected.values() if v))
        ans = rec.get("answer") or ""
        if zero and (has_phrase(ans, "0", "zero", bounded=True) or zero_lakh(ans)
                     or no_near(ans, ("record", "data", "employment", "expenditure"), 40)
                     or has_phrase(ans, "not recorded", "nothing recorded", "nothing spent", "nothing was recorded",
                                   "nothing was spent", "couldn?t find any matching records",
                                   "could not find any matching records", "no data")):
            return True, note + " (zero stated)"
        return ok, note
    return wrapped


def value_check(expected, money=False, rel=0.005):
    return zero_ok(lambda rec: (has(rec, expected, rel, money), f"exp={expected}"), expected)


def multi_check(pairs):
    """pairs: [(name, expected, money)] — every nonzero one must be present."""
    def chk(rec):
        miss = [n for n, e, m in pairs if e and not has(rec, e, 0.006, m)]
        return not miss, ("missing " + ", ".join(miss)) if miss else "all present"
    return zero_ok(chk, {n: e for n, e, _ in pairs})


def not_recorded_check(rec):
    return has_phrase(rec.get("answer") or "", *NOT_REC), "expects 'not recorded' (FY 2025-26 women)"


def pct_check(num, den):
    if not den:
        return lambda rec: (has_phrase(rec.get("answer") or "", "cannot be calculated", "can't be calculated",
                                       "divided by is 0", "no households", "no persons", "not recorded", "zero",
                                       "0 households", "no employment", "no record", "0%", "0.00%"), "den=0")
    p = round(100.0 * num / den, 2)
    return lambda rec: (has(rec, p, 0.002) or has(rec, round(p, 1), 0.004), f"pct={p} ({num}/{den})")


def ratio_check(num, den):
    if not den:
        return lambda rec: (True, "den=0, any no-data answer")
    r = round(num / den, 2)
    return lambda rec: (has(rec, r, 0.003) or has(rec, round(r, 1), 0.005), f"avg={r} ({num}/{den})")


def wm_check(e):
    wages, mat, unsk = e["unskilled_wage_exp"] + e["semi_skilled_wage_exp"], e["material_exp"], e["unskilled_wage_exp"]

    def chk(rec):
        ans = (rec.get("answer") or "").lower()
        if not wages and not mat:
            return (zero_lakh(ans) or has_phrase(ans, "no expenditure", "no spending", "zero", "nothing", case=True)), "both 0"
        ok_v = has(rec, mat, 0.006, True) and (has(rec, wages, 0.006, True) or has(rec, unsk, 0.006, True))
        if abs(wages - mat) < 0.006:                     # a tie: "spent the same … 2.02 lakh each" (Umkait)
            return ok_v and has_phrase(ans, "same", "equal", "tie", "tied"), f"tie wages={wages:.2f} mat={mat:.2f}"
        win = "wage" if wages > mat else "material"
        first = first_of(ans, "wage", "material")
        return ok_v and first == win, f"wages={wages:.2f} mat={mat:.2f} winner={win} first={first}"
    return chk


# ── DB truth, pre-aggregated per level / key / year ─────────────────────────
KEYCOL = {"state": ("'MEGHALAYA'", "'MEGHALAYA'"), "district": ("lgd_district", "lgd_district"),
          "block": ("lgd_block", "lgd_block"), "ac": ("assembly_constituency_name", "ac_name"),
          "village": ("village_code", "village_code")}
EMP, EXP = {}, {}         # (level, key, year) -> {col: sum}
VLIST = {}                # (ac, year) -> set(village_code with persons_employed > 0)


async def load_truth(levels=("state", "district", "block", "ac")):
    for lv in levels:
        ke, kx = KEYCOL[lv]
        for r in await fetch(f"SELECT {ke} k, year_key y, " + ", ".join(f"COALESCE(SUM({c}),0)::float8 {c}" for c in EMP_COLS)
                             + f" FROM curated.v_employment GROUP BY 1, 2"):
            EMP[(lv, r["k"], r["y"])] = dict(r)
        for r in await fetch(f"SELECT {kx} k, year_key y, " + ", ".join(f"COALESCE(SUM({c}),0)::float8 {c}" for c in EXP_COLS)
                             + f" FROM curated.v_expenditure GROUP BY 1, 2"):
            EXP[(lv, r["k"], r["y"])] = dict(r)
    for r in await fetch("""SELECT assembly_constituency_name a, year_key y, village_code v FROM curated.v_employment
                            GROUP BY 1, 2, 3 HAVING SUM(persons_employed) > 0"""):
        VLIST.setdefault((r["a"], r["y"]), set()).add(r["v"])


def tot(store, cols, lv, key, years):
    out = {c: 0.0 for c in cols}
    for y in years:
        for c in cols:
            out[c] += (store.get((lv, key, y)) or {}).get(c, 0.0)
    return out


def emp(lv, key, y, years=None):
    return tot(EMP, EMP_COLS, lv, key, years or ([y] if y else YEARS))


def exp(lv, key, y):
    return tot(EXP, EXP_COLS, lv, key, [y] if y else YEARS)


def job_cards(lv, key, y):
    if y:
        return emp(lv, key, y)["job_cards_issued_total"]
    have = [yy for yy in YEARS if (lv, key, yy) in EMP]
    return emp(lv, key, max(have))["job_cards_issued_total"] if have else 0.0


# ── question shapes: tc -> (template, builder(lv, key, y) -> (check, expected)) ──
def b_total(lv, k, y):
    e = exp(lv, k, y)["total_exp"]
    return value_check(e, True), e


def b_emp(col):
    def b(lv, k, y):
        v = emp(lv, k, y)[col]
        return value_check(v), v
    return b


def b_jobcards(lv, k, y):
    v = job_cards(lv, k, y)
    return value_check(v), v


def b_women(lv, k, y):
    if y == 2025:
        return not_recorded_check, None
    v = emp(lv, k, y, None if y else WOMEN_YEARS)["women_employment_provided"]
    return value_check(v), v


def b_exp(col):
    def b(lv, k, y):
        v = exp(lv, k, y)[col]
        return value_check(v, True), v
    return b


def b_breakdown(lv, k, y):
    e = exp(lv, k, y)
    return multi_check([("unskilled", e["unskilled_wage_exp"], True), ("semi-skilled", e["semi_skilled_wage_exp"], True),
                        ("material", e["material_exp"], True), ("total", e["total_exp"], True)]), e


def b_wm(lv, k, y):
    e = exp(lv, k, y)
    return wm_check(e), e


def b_exp_pd(lv, k, y):
    e, m = exp(lv, k, y)["total_exp"], emp(lv, k, y)["person_days"]
    return multi_check([("total_exp", e, True), ("person_days", m, False)]), {"total_exp": e, "person_days": m}


def b_exp_emp(lv, k, y):
    e, m = exp(lv, k, y)["total_exp"], emp(lv, k, y)

    def chk(rec):
        ok_e = (not e) or has(rec, e, 0.006, True)
        ok_m = any(has(rec, m[c]) for c in ("person_days", "households_employed", "persons_employed") if m[c])
        return ok_e and ok_m, f"exp_ok={ok_e} employment_ok={ok_m}"
    return zero_ok(chk, {"total_exp": e, "pd": m["person_days"]}), {"total_exp": e, "person_days": m["person_days"]}


def b_admin(lv, k, y):
    a = exp(lv, k, y)["admin_total_exp"]

    def chk(rec):
        ans = (rec.get("answer") or "").lower()
        return "admin" in ans and (has(rec, a, 0.006, True) or (not a and (zero_lakh(ans) or has_phrase(
            ans, "not populated", "never populated", "not recorded", "zero", "0")))), f"admin={a}"
    return chk, a


def b_women_pct(lv, k, y):
    if y == 2025:
        return not_recorded_check, None
    m = emp(lv, k, y, None if y else WOMEN_YEARS)
    return pct_check(m["women_employment_provided"], m["persons_employed"]), m


def b_100_pct(lv, k, y):
    m = emp(lv, k, y)
    return pct_check(m["households_completed_100_days"], m["households_employed"]), m


def b_avg(lv, k, y):
    m = emp(lv, k, y)
    return ratio_check(m["person_days"], m["households_employed"]), m


def b_ac_villages(lv, k, y):
    vs = VLIST.get((k, y), set()) if y else set().union(*[VLIST.get((k, yy), set()) for yy in YEARS])
    n = len(vs)

    def chk(rec):
        rows = rec.get("rows") or []
        nrows = rec.get("n_rows") or 0
        return nrows == n or has(rec, n), f"villages expected={n} rows={nrows}"
    return zero_ok(chk, n), n


SHAPES = {
    "DATA-001": ("What was the total expenditure in {p}{y}?", b_total),
    "DATA-002": ("What was the total expenditure in {p}{y}?", b_total),
    "DATA-003": ("What was the total expenditure in {p}{y}?", b_total),
    "DATA-004": ("How many persons received employment in {p}{y}?", b_emp("persons_employed")),
    "DATA-005": ("How many households received employment in {p}{y}?", b_emp("households_employed")),
    "DATA-006": ("How many person-days were generated in {p}{y}?", b_emp("person_days")),
    "DATA-007": ("How many job cards were issued in {p}{y}?", b_jobcards),
    "DATA-008": ("How many women were provided employment in {p}{y}?", b_women),
    "DATA-009": ("How many households completed 100 days in {p}{y}?", b_emp("households_completed_100_days")),
    "DATA-010": ("How much was spent on unskilled wages in {p}{y}?", b_exp("unskilled_wage_exp")),
    "DATA-011": ("How much was spent on materials in {p}{y}?", b_exp("material_exp")),
    "DATA-012": ("How much was spent on semi-skilled wages in {p}{y}?", b_exp("semi_skilled_wage_exp")),
    "DATA-013": ("What was the administrative expenditure in {p}{y}?", b_admin),
    "DATA-014": ("Which villages in {p} received employment{y}?", b_ac_villages),
    "DATA-015": ("How many total person-days were generated in {p}{y}?", b_emp("person_days")),
    "DATA-016": ("How many households received employment in {p}{y}?", b_emp("households_employed")),
    "DATA-017": ("How many women received employment in {p}{y}?", b_women),
    "DATA-018": ("How many job cards were issued in {p}{y}?", b_jobcards),
    "DATA-019": ("What percentage of employment persons were women in {p}{y}?", b_women_pct),
    "DATA-020": ("What percentage of employment households completed 100 days in {p}{y}?", b_100_pct),
    "DATA-021": ("What was the average number of person-days per employment household in {p}{y}?", b_avg),
    "DATA-022": ("Give me the expenditure breakdown for {p}{y}.", b_breakdown),
    "DATA-023": ("Was more spent on wages or materials in {p}{y}?", b_wm),
    "DATA-028": ("How much was spent and how many person-days were generated in {p}{y}?", b_exp_pd),
    "DATA-029": ("Compare expenditure and person-days in {p}{y}.", b_exp_pd),
    "DATA-030": ("Compare total expenditure and employment generated in {p}{y}.", b_exp_emp),
}
VILLAGE_TCS = ["DATA-001", "DATA-005", "DATA-006", "DATA-007", "DATA-008", "DATA-009", "DATA-010", "DATA-011",
               "DATA-012", "DATA-022", "DATA-023", "DATA-028"]
DISTRICT_TCS = ["DATA-002", "DATA-015", "DATA-017", "DATA-018", "DATA-019", "DATA-021", "DATA-030"]
BLOCK_TCS = ["DATA-003", "DATA-013", "DATA-016", "DATA-020", "DATA-029"]
AC_TCS = ["DATA-004", "DATA-014"]


DONE: set = set()          # (tc, label) finished with a real answer in an earlier run of the same file


def load_previous(path):
    """Resume: keep every earlier case that did not end in a connection error (the VPN
    dropped mid-run 2026-10-30); those re-run."""
    if not os.path.exists(path):
        return
    prev = json.load(open(path, encoding="utf-8"))
    rerun_failed = os.environ.get("MGU_RERUN_FAILED") == "1"       # the after-fix pass
    for tc, cs in prev.items():
        for c in cs:
            if c["turns"] and c["turns"][-1]["kind"] == "error":
                continue
            if rerun_failed and not c["ok"]:
                continue
            RESULTS.setdefault(tc, []).append(c)
            DONE.add((tc, c["label"]))
    log(f"resumed {sum(len(v) for v in RESULTS.values())} finished cases from {path}")


def case(tc, lv, key, ask, y, style, label, place=None, code=None, tag=""):
    tmpl, build = SHAPES[tc]
    chk, ex = build(lv, key, y)
    q = tmpl.format(p=ask, y=during(y, style))
    full = f"{label} {fy_label(y)} as '{ask}'"
    if (tc + tag, full) in DONE:
        return None
    return run_case(tc + tag, full, q, chk, year=y, place=place,
                    level=None if lv in ("state", "ac") else lv, expected=ex, code=code)


async def main():
    from app import main as app_main
    async with app_main.lifespan(app_main.app):
        await load_truth()
        load_previous(OUTP)
        T = []
        districts = sorted({k for (lv, k, _y) in EMP if lv == "district"})
        blocks = sorted({k for (lv, k, _y) in list(EMP) + list(EXP) if lv == "block" and k})
        acs = sorted({k for (lv, k, _y) in EMP if lv == "ac" and k})
        vnames = {r["n"] for r in await fetch("SELECT DISTINCT UPPER(lgd_village_name) n FROM curated.v_employment")}
        log(f"{len(districts)} districts, {len(blocks)} blocks, {len(acs)} ACs")
        st = 0
        if "district" in PARTS:          # every district x every district shape x every year option
            for i, d in enumerate(districts):
                for tc in DISTRICT_TCS:
                    for y in YOPTS:
                        st += 1
                        ask = [d.title(), d, d.lower()][st % 3]
                        T.append(case(tc, "district", d, ask, y, st, d, place=[d.split()[0]]))
        if "block" in PARTS:             # every block x every block shape x every year option
            for i, b in enumerate(blocks):
                collide = b.upper() in vnames
                for tc in BLOCK_TCS:
                    for y in YOPTS:
                        st += 1
                        ask = (f"{b.title()} block" if st % 2 else b.title()) if collide else [b.title(), b, f"{b.title()} block"][st % 3]
                        T.append(case(tc, "block", b, ask, y, st, b + (" [also a village]" if collide else ""), place=[b]))
        if "ac" in PARTS:                # every constituency x both AC shapes x every year option
            for a in acs:
                for tc in AC_TCS:
                    for y in YOPTS:
                        st += 1
                        T.append(case(tc, "ac", a, f"{a.title()} constituency", y, st, a, place=[a.split()[0]]))
        if "state" in PARTS:             # statewide: every shape that reads a single total, every year option
            for tc in ["DATA-001", "DATA-005", "DATA-006", "DATA-007", "DATA-008", "DATA-009", "DATA-010",
                       "DATA-011", "DATA-012", "DATA-013", "DATA-019", "DATA-020", "DATA-021", "DATA-022",
                       "DATA-023", "DATA-028"]:
                for y in YOPTS:
                    st += 1
                    T.append(case(tc, "state", "MEGHALAYA", ["Meghalaya", "the state", "Meghalaya state"][st % 3],
                                  y, st, "state", tag="-state"))
        if "cross" in PARTS:             # the village shapes asked at every district and every block
            for d in districts:
                for j, tc in enumerate(VILLAGE_TCS):
                    st += 1
                    T.append(case(tc, "district", d, d.title(), YOPTS[st % 5], st, d, place=[d.split()[0]], tag="-xdistrict"))
            for b in blocks:
                ask = f"{b.title()} block"
                for j, tc in enumerate(VILLAGE_TCS):
                    st += 1
                    T.append(case(tc, "block", b, ask, YOPTS[st % 5], st, b, place=[b], tag="-xblock"))
        if "rank" in PARTS:
            T += await rankings()
        if "village" in PARTS or "dups" in PARTS:
            T += await village_sample()
        T = [t for t in T if t is not None]
        log(f"running {len(T)} conversations")
        for k in range(0, len(T), 250):
            await asyncio.gather(*T[k:k + 250])
            json.dump(RESULTS, open(OUTP, "w", encoding="utf-8"), ensure_ascii=False, default=str)
            log(f"checkpoint {min(k + 250, len(T))}/{len(T)}")
    log("written", OUTP)


async def rankings():
    T = []
    for y in YOPTS:
        yrs = [y] if y else YEARS
        wyrs = [y] if y else WOMEN_YEARS
        yc = "year_key = ANY($1::int[])"
        for tc, sql, prm, q in [
            ("DATA-024", f"SELECT lgd_district n, SUM(total_exp)::float8 v FROM curated.v_expenditure WHERE {yc} GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
             yrs, "Which district had the highest expenditure{y}?"),
            ("DATA-025", f"SELECT lgd_block n, SUM(person_days)::float8 v FROM curated.v_employment WHERE {yc} AND lgd_block IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
             yrs, "Which block generated the highest person-days{y}?"),
            ("DATA-026", f"SELECT village_code, MIN(lgd_village_name) n, SUM(person_days)::float8 v FROM curated.v_employment WHERE {yc} GROUP BY 1 ORDER BY 3 DESC LIMIT 1",
             yrs, "Which village generated the highest person-days{y}?"),
            ("DATA-027", f"SELECT lgd_district n, SUM(women_employment_provided)::float8 v FROM curated.v_employment WHERE {yc} GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
             wyrs, "Which district had the highest women employment{y}?"),
        ]:
            for style in (0, 3):
                top = (await fetch(sql, [prm]))[0]
                money = tc == "DATA-024"
                if top["v"] > 0:
                    chk = (lambda r, t=top, m=money: (has_name(r, t["n"]) and has(r, t["v"], 0.006, m), f"exp {t['n']} {t['v']}"))
                else:
                    chk = not_recorded_check
                T.append(run_case(tc, f"{fy_label(y)} style{style}", q.format(y=during(y, style + (y or 0))), chk,
                                  year=y, expected=dict(top)))
    return T


async def village_sample():
    """24 villages (2 per district, unique names, data every year) x the 12 village shapes x every year
    option; plus same-name villages that must ask which one."""
    T = []
    for lv in ("village",):
        ke, kx = KEYCOL[lv]
        for r in await fetch("SELECT village_code k, year_key y, " + ", ".join(f"COALESCE(SUM({c}),0)::float8 {c}" for c in EMP_COLS)
                             + " FROM curated.v_employment GROUP BY 1, 2"):
            EMP[(lv, r["k"], r["y"])] = dict(r)
        for r in await fetch("SELECT village_code k, year_key y, " + ", ".join(f"COALESCE(SUM({c}),0)::float8 {c}" for c in EXP_COLS)
                             + " FROM curated.v_expenditure GROUP BY 1, 2"):
            EXP[(lv, r["k"], r["y"])] = dict(r)
    if "village" in PARTS:
        villages = await fetch("""
            WITH u AS (SELECT UPPER(lgd_village_name) n FROM curated.v_employment
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code)=1),
                 c AS (SELECT e.village_code, MIN(e.lgd_village_name) name, MIN(e.lgd_district) d
                       FROM curated.v_employment e JOIN u ON u.n = UPPER(e.lgd_village_name)
                       WHERE LENGTH(e.lgd_village_name) >= 5
                       GROUP BY 1 HAVING COUNT(DISTINCT e.year_key)=4 AND SUM(e.person_days) > 0),
                 x AS (SELECT c.*, ROW_NUMBER() OVER (PARTITION BY d ORDER BY md5(name || '2026-10-30')) rn FROM c
                       WHERE c.village_code IN (SELECT village_code FROM curated.v_expenditure
                                                GROUP BY 1 HAVING COUNT(DISTINCT year_key)=4))
            SELECT village_code, name, d FROM x WHERE rn <= 2 ORDER BY d, name""")
        st = 0
        for i, v in enumerate(villages):
            for tc in VILLAGE_TCS:
                for y in YOPTS:
                    st += 1
                    nm = [v["name"].upper(), v["name"].title(), v["name"].lower()][st % 3]
                    T.append(case(tc, "village", v["village_code"], nm, y, st, f"{v['name']} ({v['d']})",
                                  place=[v["name"]], code=v["village_code"]))
    if "dups" in PARTS:
        dups = await fetch("""
            WITH n AS (SELECT UPPER(lgd_village_name) n FROM curated.v_employment
                       GROUP BY 1 HAVING COUNT(DISTINCT village_code) BETWEEN 2 AND 4)
            SELECT e.village_code, MIN(e.lgd_village_name) name, MIN(e.lgd_block) b, MIN(e.lgd_district) d
            FROM curated.v_employment e JOIN n ON n.n = UPPER(e.lgd_village_name)
            GROUP BY 1 ORDER BY md5(MIN(e.lgd_village_name)), 1 LIMIT 40""")
        for j, v in enumerate(dups):
            tc = ["DATA-001", "DATA-006", "DATA-005", "DATA-022"][j % 4]
            y = YOPTS[j % 5]
            T.append(case(tc, "village", v["village_code"], v["name"], y, j, f"same-name {v['name']} -> {v['b']}/{v['d']}",
                          place=[v["name"], v["b"]], code=v["village_code"], tag="-samename"))
    return T


if __name__ == "__main__":
    asyncio.run(main())
