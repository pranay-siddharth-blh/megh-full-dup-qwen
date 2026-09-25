"""Build tests/eval/cases.yaml — the evaluation set run_eval.py scores.

Three sources, one file:
  1. kpi_workbook   data/reference/*_KPI_Use_Cases.xlsx (all 4 schemes):
                    use cases, descriptive commands, Q+A drilldowns (expected
                    answer + scored figures) and ambiguous inputs (expected
                    clarification). Follow-up sheet rows are attached to the
                    use cases they link to as `expect.followup_policy`.
  2. audit_log      100 real questions sampled from logs/query_audit.jsonl
                    (singles + multi-turn conversations), marked
                    needs_expected_answer for a human to fill in.
  3. messy_variant  tests/eval/messy_variants.yaml — typos, Hinglish, no
                    scheme name, word order — inheriting the original case's
                    expected figures.

Re-running is safe: audit_log cases already in cases.yaml are human-owned
(you fill in their expected answers) and are carried over untouched; only
workbook + messy cases are regenerated. Pass --resample-audit to redraw them.

    python tests/eval/build_cases.py [--resample-audit]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

import openpyxl
import yaml

ROOT = Path(__file__).resolve().parents[2]
EVAL = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
from scoring import expected_figures, parse_figures  # noqa: E402

CASES_FILE = EVAL / "cases.yaml"
AUDIT_FILE = ROOT / "logs" / "query_audit.jsonl"

WORKBOOKS = {  # scheme -> (file, id prefix)
    "MGNREGA": ("data/reference/mgnrega_kpi_use_cases.xlsx", "mgnrega"),
    "PMAY-G": ("data/reference/pmay_kpi_use_cases.xlsx", "pmay"),
    "Focus Plus": ("data/reference/Focus_Plus_KPI_Use_Cases.xlsx", "focus"),
    "CM Elevate": ("data/reference/CM_Elevate_KPI_Use_Cases.xlsx", "cmelevate"),
}
MESSY_KEYS = {"mgnrega": "MGNREGA", "pmay": "PMAY-G", "focus_plus": "Focus Plus",
              "cm_elevate": "CM Elevate"}

# Ambiguous inputs that are only meaningful mid-conversation ("This year",
# "The livestock scheme"): played as turn 2 after the linked use case.
CONTEXTUAL_AMBIGUOUS = {
    ("MGNREGA", "AM-02"), ("Focus Plus", "AM-02"), ("CM Elevate", "AM-04"),
    ("PMAY-G", "AM-05"),
}

N_AUDIT_QUESTIONS = 100
AUDIT_SEED = 20260925
# Harness / scripted traffic in the audit log — not real phrasing.
_SYNTHETIC_USER = re.compile(r"(tester|^rc-officer-|^qa-)", re.IGNORECASE)
_PII_LIKE = re.compile(r"(\d{10,}|[\w.+-]+@[\w-]+\.\w+|\b[A-Z]{2}-\d{2}-\d{3}-\d{3})")


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _links(cell) -> list[str]:
    return re.findall(r"\b([A-Z]{1,2}\d?-\d{2})\b", str(cell or ""))


def _sheet_rows(ws) -> list[dict]:
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 3:
        return []
    hdr = [_clean(h) for h in rows[1]]
    out = []
    for r in rows[2:]:
        d = dict(zip(hdr, r))
        if d.get("UC ID"):
            out.append({k: v for k, v in d.items() if k})
    return out


# Where the auto-picked headline figure is wrong (the workbook sentence leads
# with a label-ish number), the figure(s) to score on instead — or None to
# leave the case unscored because its answer is an explanation, not a figure.
FIGURE_OVERRIDES = {
    "mgnrega-K1-06": "71%",            # statewide wage share; "60%" is the floor
    "focus-F1-10": None,               # explains why bank-wise is unreliable
    "focus-F2-05": "10,263 Female 82%",
    "focus-F2-08": "8,533 68%",
    "cmelevate-C1-04": "14 10",        # Sericulture (14), Green Taxi (10)
    "cmelevate-C2-02": "74%",          # Piggery 74% female
}


_DERIVED = re.compile(r"(average|avg|share|%|proportion|fraction|ratio|concentrated|"
                      r"per|what part|how much of)", re.IGNORECASE)


def _figs(answer: str, case_id: str = "", question: str = "") -> list[dict]:
    if case_id in FIGURE_OVERRIDES:
        if FIGURE_OVERRIDES[case_id] is None:
            return []
        figs = parse_figures(FIGURE_OVERRIDES[case_id], skip_labels=False)
    else:
        figs = expected_figures(answer)
        # "A ÷ B = ~C": for a derived-quantity question (average / share /
        # per-unit) the answer is C, so figures after the last '=' / '≈' lead
        # (K1-05 "₹945.71 Cr ÷ 4,629 villages = ~₹20.4 Lakh per village").
        # Not for a ranking question whose answer merely ends with a remark
        # ("… East Garo Hills ₹83.22 Cr. Top 5 = 68% of state spend.").
        cut = max(answer.rfind("="), answer.rfind("≈"))
        if cut > 0 and _DERIVED.search(question):
            tail = expected_figures(answer[cut + 1:])
            if tail:
                figs = tail + [f for f in figs if f["text"] not in {t["text"] for t in tail}]
    return [{"text": f["text"], "value": f["value"], "unit": f["unit"],
             "pct": f["pct"], "decimals": f["decimals"]} for f in figs]


def workbook_cases() -> list[dict]:
    cases = []
    for scheme, (rel, prefix) in WORKBOOKS.items():
        wb = openpyxl.load_workbook(ROOT / rel, read_only=True, data_only=True)
        sheets = {ws.title: _sheet_rows(ws) for ws in wb.worksheets}
        by_id: dict[str, dict] = {}

        def add(uc, sheet, query, answer, kind="answer", extra=None):
            cid = f"{prefix}-{uc}"
            figs = _figs(_clean(answer), cid, _clean(query)) if kind == "answer" else []
            case = {
                "id": cid, "source": "kpi_workbook", "scheme": scheme,
                "sheet": sheet, "turns": [_clean(query)],
                "expect": {"kind": kind, "answer": _clean(answer), "figures": figs},
            }
            if kind == "answer" and not figs and cid in FIGURE_OVERRIDES:
                case["expect"]["unscored_reason"] = "expected answer is an explanation, not a figure"
            elif kind == "answer" and not figs:
                case["expect"]["unscored_reason"] = \
                    "expected answer describes a method, not a figure"
            if extra:
                case["expect"].update(extra)
            by_id[uc] = case
            cases.append(case)

        use_sheet = next(t for t in sheets if t.endswith("KPI Use Cases"))
        for d in sheets[use_sheet]:
            add(d["UC ID"], use_sheet, d.get("Query (Input)"), d.get("Expected Answer"))
        for d in sheets.get("Descriptive Commands", []):
            add(d["UC ID"], "Descriptive Commands", d.get("Command (Input)"), d.get("Expected Answer"))
        for d in sheets.get("Q+A Drilldown", []):
            add(d["UC ID"], "Q+A Drilldown", d.get("Descriptive Command"), d.get("Suggested Answer"))

        # Follow-up sheet: a policy on the linked use cases, not an input.
        for d in sheets.get("Follow-up", []):
            policy = {"id": d["UC ID"], "trigger": _clean(d.get("Trigger")),
                      "ask": _clean(d.get("Follow-up Question / Action")).strip("'"),
                      "notes": _clean(d.get("Notes"))}
            for uc in _links(d.get("Linked UC")):
                if uc in by_id:
                    by_id[uc]["expect"].setdefault("followup_policy", []).append(policy)

        for d in sheets.get("Ambiguous Cases", []):
            query = _clean(d.get("Ambiguous Input")).strip("'\" ")
            notes = _clean(d.get("Notes"))
            extra = {"clarification": _clean(d.get("Resolution / Clarifying Question")),
                     "accept_default": notes.lower().startswith("default"),
                     "default": notes if notes.lower().startswith("default") else None}
            add(d["UC ID"], "Ambiguous Cases", query, "", kind="clarify", extra=extra)
            if (scheme, d["UC ID"]) in CONTEXTUAL_AMBIGUOUS:
                linked = [u for u in _links(d.get("Linked UC")) if u in by_id]
                if linked:
                    by_id[d["UC ID"]]["turns"] = [by_id[linked[0]]["turns"][0], query]
                    by_id[d["UC ID"]]["expect"]["scored_turn"] = 1
    return cases


def messy_cases(workbook: list[dict]) -> list[dict]:
    spec = yaml.safe_load((EVAL / "messy_variants.yaml").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in workbook}
    out = []
    for key, scheme in MESSY_KEYS.items():
        for i, v in enumerate(spec.get(key) or [], 1):
            src = by_id.get(v["of"])
            if src is None:
                raise SystemExit(f"messy_variants.yaml: unknown case {v['of']!r}")
            out.append({
                "id": f"messy-{src['id']}-{i:02d}", "source": "messy_variant",
                "scheme": scheme, "variant_of": src["id"], "style": v.get("style", []),
                "turns": [v["say"]],
                "expect": {k: val for k, val in src["expect"].items()
                           if k in ("kind", "answer", "figures", "unscored_reason")},
            })
    return out


def flow_cases() -> list[dict]:
    """tests/eval/flows.yaml — scripted multi-turn flows with chip clicks."""
    spec = yaml.safe_load((EVAL / "flows.yaml").read_text(encoding="utf-8")) or {}
    return [{"id": f["id"], "source": "flow", "scheme": f.get("scheme"), "turns": f["turns"],
             "expect": f["expect"]} for f in spec.get("flows") or []]


def _conversations(rows: list[dict]) -> list[list[dict]]:
    """Split each session's turns into conversations at gaps > 20 min."""
    by_sess = collections.defaultdict(list)
    for r in rows:
        by_sess[r["session_id"]].append(r)
    convs = []
    for turns in by_sess.values():
        turns.sort(key=lambda r: r["ts"])
        cur = [turns[0]]
        for prev, r in zip(turns, turns[1:]):
            gap = (dt.datetime.fromisoformat(r["ts"]) - dt.datetime.fromisoformat(prev["ts"]))
            if gap > dt.timedelta(minutes=20):
                convs.append(cur)
                cur = []
            cur.append(r)
        convs.append(cur)
    return convs


_HINGLISH = re.compile(r"\b(kitna|kitne|kitni|hai|hain|ka|ki|ke|mein|me|mai|batao|dikhao|"
                       r"kya|kaun|kahan|kaise|wala|wale|sabse|paisa|ghar)\b", re.IGNORECASE)


def _vocab() -> set[str]:
    words: set[str] = set()
    for p in list((ROOT / "data").rglob("*.md")) + list((ROOT / "data").rglob("*.yaml")):
        words.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", p.read_text(encoding="utf-8", errors="ignore")))
    return words


def _norm(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()


def _style(q: str, vocab: set[str]) -> str:
    toks = re.findall(r"[A-Za-z]+", q)
    if _HINGLISH.search(q):
        return "hinglish"
    if any(len(t) >= 4 and t.lower() not in vocab for t in toks):
        return "misspelled_or_unknown"
    if len(q.split()) <= 4:
        return "fragment"
    if len(q.split()) >= 16:
        return "long"
    return "plain"


def audit_cases() -> list[dict]:
    rows = []
    for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("ip") in (None, "testclient") or _SYNTHETIC_USER.search(r.get("username") or ""):
            continue
        q = _clean(r.get("question"))
        if not q or _PII_LIKE.search(q):
            continue
        r["question"] = q
        rows.append(r)

    rng = random.Random(AUDIT_SEED)
    vocab = _vocab()
    convs = _conversations(rows)
    seen: set[str] = set()

    # Multi-turn: conversations where the bot paused for a clarification (or a
    # follow-up was asked) and the user kept going — 2 to 4 turns each.
    multi = [c for c in convs if 2 <= len(c) <= 4
             and any(t["route"] == "clarification" for t in c[:-1])]
    rng.shuffle(multi)
    picked: list[list[dict]] = []
    n_q = 0
    for c in multi:
        key = " | ".join(_norm(t["question"]) for t in c)
        if key in seen or n_q + len(c) > 32:
            continue
        seen.add(key)
        seen.update(_norm(t["question"]) for t in c)
        picked.append(c)
        n_q += len(c)

    # Singles: conversation openers only (a mid-conversation reply like "all
    # of Meghalaya, all years" means nothing on its own), stratified by style.
    buckets = collections.defaultdict(list)
    for c in convs:
        q = c[0]["question"]
        if _norm(q) in seen:
            continue
        seen.add(_norm(q))
        buckets[_style(q, vocab)].append(c[0])
    for b in buckets.values():
        rng.shuffle(b)
    singles = []
    order = ["misspelled_or_unknown", "hinglish", "fragment", "long", "plain"]
    while n_q + len(singles) < N_AUDIT_QUESTIONS and any(buckets[k] for k in order):
        for k in order:
            if buckets[k] and n_q + len(singles) < N_AUDIT_QUESTIONS:
                singles.append((k, buckets[k].pop()))

    out = []
    for i, c in enumerate(picked, 1):
        out.append({
            "id": f"audit-conv-{i:02d}", "source": "audit_log", "scheme": None,
            "turns": [t["question"] for t in c],
            "logged": [{"route": t["route"], "rule": t.get("deny_check"),
                        "rows": t.get("row_count")} for t in c],
            "needs_expected_answer": True,
            "expect": {"kind": "answer", "answer": None, "figures": []},
        })
    for i, (style, t) in enumerate(singles, 1):
        out.append({
            "id": f"audit-{i:03d}", "source": "audit_log", "scheme": None, "style": [style],
            "turns": [t["question"]],
            "logged": [{"route": t["route"], "rule": t.get("deny_check"), "rows": t.get("row_count")}],
            "needs_expected_answer": True,
            "expect": {"kind": "answer", "answer": None, "figures": []},
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resample-audit", action="store_true")
    args = ap.parse_args()

    workbook = workbook_cases()
    messy = messy_cases(workbook)
    existing_audit = []
    if CASES_FILE.exists() and not args.resample_audit:
        old = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8")) or {}
        existing_audit = [c for c in old.get("cases", []) if c.get("source") == "audit_log"]
    audit = existing_audit or audit_cases()

    cases = workbook + messy + flow_cases() + audit
    ids = [c["id"] for c in cases]
    dup = [i for i, n in collections.Counter(ids).items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate case ids: {dup}")

    header = (
        "# GENERATED by tests/eval/build_cases.py — see its docstring.\n"
        "# Workbook + messy cases are regenerated on every build; audit_log cases\n"
        "# are human-owned: fill in expect.answer / expect.figures (or set\n"
        "# expect.kind: clarify) and flip needs_expected_answer to false.\n"
        "# expect.figures[0] is the headline figure a case passes or fails on.\n"
    )
    doc = {"version": 1, "built": dt.date.today().isoformat(), "cases": cases}
    CASES_FILE.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
                          encoding="utf-8")
    c = collections.Counter(x["source"] for x in cases)
    nq = sum(len(x["turns"]) for x in audit)
    print(f"wrote {CASES_FILE.relative_to(ROOT)}: {len(cases)} cases {dict(c)}; "
          f"audit questions={nq}; scored workbook cases="
          f"{sum(1 for x in workbook if x['expect'].get('figures') or x['expect']['kind'] == 'clarify')}")


if __name__ == "__main__":
    main()
