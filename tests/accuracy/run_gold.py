"""LIVE accuracy gold bank runner (2026-11-11). Not collected by pytest (not named test_*.py).

Runs every case of tests/accuracy/gold_bank.yaml through the product's own conversation layer and
LangGraph graph IN-PROCESS (tests/conversation_harness InProcessDriver, as tests/live_chat_golden.py
does; a fresh conversation per case), as the `superadmin` user (the user's rule: every scheme, every
level). Each turn's truth is RECOMPUTED LIVE from the case's own read-only SQL (the app's read-only
pool, READ ONLY transaction), so a data reload never makes the bank stale; the value recorded when the
bank was built is reported beside it when the two differ ("drift").

What is checked on each turn (only the keys the turn carries):
  figures   every expected figure is in the ANSWER TEXT in a faithful rendering of its unit:
            count  = the exact integer (Indian grouping; a count written as money is a format failure);
            lakh   = ₹X lakh (2 dp), or ₹X/100 crore (2 dp), or the exact rupees;
            rupees = the exact rupees, or ₹ crore / lakh at 2 dp;  pct = 2 dp or 1 dp, with %;
            dec    = 2 dp or 1 dp (to the rupee when >= 100).
            `any`: one of two documented readings, each with its own word (e.g. 'valid').
  rows      a breakdown / ranking: each expected row's label and value, in the text (the value after its
            own label, before the next label) or in the answer's table (`data`); take=N = the first N rows.
  schemes   the answer's schemes, exactly (as a set).   pause / route   answered vs a clarification.
  chart     the chart the answer tells the UI to draw (`chart_type`); 'unsupported:<kind>' = the answer
            must say the kind is not available and never claim it; 'horizontal_bar' likewise unless drawn;
            'multi' = one chart drawn and no claim of several.
  has / any_of / lacks   caveats and leaks (case-insensitive for any_of).
  strict    no number in the text that the truth does not support (years, list markers and the
            question's own numbers aside).

Failure taxonomy (first that applies is the primary tag): timeout/error, clarification, routing/intent,
refused-wrongly, follow-up-context, entity-resolution, year, sql-wrong, composer-misstated, unit/format,
chart. The tag is a first reading; every failure is then root-caused by hand.

    .venv/Scripts/python.exe tests/accuracy/run_gold.py                       # all, 4 at a time
    .venv/Scripts/python.exe tests/accuracy/run_gold.py --only G-D,UAT-P01,chain
    .venv/Scripts/python.exe tests/accuracy/run_gold.py --failed tests/accuracy/results/<run>.json
    .venv/Scripts/python.exe tests/accuracy/run_gold.py --label after-fix1 --concurrency 3

Writes tests/accuracy/results/<stamp>_<label>.json and prints a summary by category and by tag.
Needs the office VPN (megh_db + model gateway). Exit code 0 = every case passed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)                      # .env is read relative to the working directory
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import yaml  # noqa: E402

from app.text_match import fy_spans, number_spans, to_number  # noqa: E402
from conversation_harness.drivers import InProcessDriver, _InProcessConversation, _from_result  # noqa: E402
from conversation_harness.checks import TurnRecord  # noqa: E402

BANK = os.path.join(ROOT, "tests", "accuracy", "gold_bank.yaml")
RESULTS = os.path.join(ROOT, "tests", "accuracy", "results")
TURN_TIMEOUT = 300.0
DISTRICTS = ["EASTERN WEST KHASI HILLS", "EAST GARO HILLS", "EAST JAINTIA HILLS", "EAST KHASI HILLS",
             "NORTH GARO HILLS", "RI BHOI", "SOUTH GARO HILLS", "SOUTH WEST GARO HILLS", "SOUTH WEST KHASI HILLS",
             "WEST GARO HILLS", "WEST JAINTIA HILLS", "WEST KHASI HILLS"]
TAG_ORDER = ["timeout/error", "clarification", "routing/intent", "refused-wrongly", "follow-up-context",
             "entity-resolution", "year", "sql-wrong", "composer-misstated", "unit/format", "chart"]
REFUSAL_WORDS = ("not available", "isn't available", "is not available", "not recorded", "cannot", "can't",
                 "don't have", "do not have", "not held", "unable", "no data", "not part of")


# ── the conversation, as the superadmin ─────────────────────────────────────────────────────────

class SuperadminConversation(_InProcessConversation):
    """The harness conversation (snapshot round-trip per turn), asked with the superadmin's own scope as
    the router passes it (`session.scope = scope`; pipeline.answer_question(scope=...))."""

    def __init__(self, store, scope):
        super().__init__(store, False)
        self.scope = scope

    async def _ask(self, say: str, t0: float) -> TurnRecord:
        from app import conversation_layer, conversation_replies, pipeline
        from app.routers import query as router
        self.session.turn_context = {}
        self.session.scope = self.scope
        try:
            layer = await conversation_layer.prepare_turn(self.session, say)
            if layer.response is not None:
                result = layer.response
            elif layer.multi:
                result = await conversation_layer.answer_many(
                    layer.multi, lambda x: pipeline.answer_question(x, session=self.session, scope=self.scope))
            else:
                result = await pipeline.answer_question(layer.question, session=self.session, scope=self.scope)
            styled = conversation_replies.restyle(self.session, say, result)
            if styled is not None:
                result = styled
            self.session.turns.append(router.build_turn(say, result))
            return _from_result(say, result, round((time.perf_counter() - t0) * 1000))
        except pipeline.ClarificationNeeded as e:
            router.remember_pause(self.session, router.pause_question(self.session, say), e)
            return TurnRecord(say=say, route="pause", answer=e.question, pause_rule=e.rule,
                              chips=[o.get("label") if isinstance(o, dict) else str(o) for o in (e.options or [])],
                              ms=round((time.perf_counter() - t0) * 1000))
        except Exception as e:  # noqa: BLE001 — recorded as a failed turn
            return TurnRecord(say=say, route="error", answer=f"{type(e).__name__}: {e}",
                              ms=round((time.perf_counter() - t0) * 1000))


async def superadmin_scope():
    from app import appdb, auth
    rec = await appdb.get_user_by_username("superadmin")
    if not rec:
        raise SystemExit("no superadmin user in app.users")
    scope = auth.scope_from_user(rec)
    if not scope.is_admin:
        raise SystemExit("the superadmin scope is not an admin scope")
    return scope


# ── truth ───────────────────────────────────────────────────────────────────────────────────────

def _conv(v):
    if isinstance(v, Decimal):
        return float(v) if v != v.to_integral_value() else int(v)
    return v


async def truth_value(sql: str):
    from app import db
    rows = await db.fetch_rows_readonly(sql)
    return _conv(list(rows[0].values())[0]) if rows else None


async def truth_rows(sql: str):
    from app import db
    rows = await db.fetch_rows_readonly(sql)
    return [[_conv(x) for x in r.values()] for r in rows]


async def live_truth(turn: dict) -> None:
    """Recompute every figure / rows of the turn in place: `live` beside the recorded `value`."""
    async def fig(f):
        if "any" in f:
            for g in f["any"]:
                await fig(g)
            return
        f["live"] = await truth_value(f["sql"])
    for f in turn.get("figures") or []:
        await fig(f)
    for r in _flat_rows(turn):
        r["live"] = await truth_rows(r["sql"])


# ── reading numbers out of an answer (no regex: app.text_match + string methods) ───────────────

def _is_indian(raw: str) -> bool:
    whole = raw.split(".")[0]
    if "," not in whole:
        return len(whole) <= 3
    parts = whole.split(",")
    return len(parts[-1]) == 3 and all(len(p) == 2 for p in parts[1:-1]) and 1 <= len(parts[0]) <= 2


def scan(text: str) -> list[dict]:
    """Every number in the text with what surrounds it: its unit word after it (lakh / crore / %),
    a rupee sign before it, whether it is (part of) a year."""
    text = text or ""
    low = text.lower()
    fy_cover = [(s, e) for s, e, _, _ in fy_spans(text)]
    out = []
    for s, e, raw in number_spans(text):
        val = to_number(raw)
        if val is None:
            continue
        after = low[e:e + 14].lstrip("  ")
        unit = None
        if after.startswith(("lakh", "lac")):
            unit = "lakh"
        elif after.startswith("crore") or after.startswith(("cr ", "cr.", "cr)", "cr,")) or after == "cr":
            unit = "crore"
        elif after.startswith(("%", "per cent", "percent")):
            unit = "pct"
        before = low[max(0, s - 6):s].rstrip("  ")
        rupee = before.endswith(("₹", "rs.", "rs", "inr", "rupees"))
        in_fy = any(a <= s < b for a, b in fy_cover)
        is_year = in_fy or (len(raw) == 4 and raw.isdigit() and 2015 <= val <= 2035)
        line_start = low.rfind("\n", 0, s) + 1
        marker = low[line_start:s].strip() in ("", "-", "*", "•") and low[e:e + 1] == "." and val < 50 \
            and "." not in raw
        out.append({"s": s, "e": e, "raw": raw, "val": val, "unit": unit, "rupee": rupee, "year": is_year,
                    "marker": marker})
    return out


def _near(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol + 1e-9


def renderings(value, unit: str) -> list[tuple]:
    """(value, unit word or None, tolerance) a faithful answer may write for this figure."""
    if value is None:
        return []
    v = float(value)
    if unit == "count":
        return [(v, None, 0.5)]
    if unit == "lakh":
        return [(v, "lakh", 0.0101), (v / 100.0, "crore", 0.0101), (v * 1e5, None, 1.0)]
    if unit == "rupees":
        return [(v, None, 1.0), (v / 1e7, "crore", 0.0101), (v / 1e5, "lakh", 0.0101)]
    if unit == "crore":
        return [(v, "crore", 0.0101), (v * 100, "lakh", 1.01), (v * 1e7, None, 100.0)]
    if unit == "pct":
        return [(v, "pct", 0.0051), (round(v, 1), "pct", 0.0001)]
    if unit == "dec":
        tol = 0.5 if abs(v) >= 100 else 0.0051
        return [(v, None, tol), (round(v, 1), None, 0.0001)]
    return [(v, None, 0.0)]


def find_figure(nums: list[dict], value, unit: str) -> tuple[bool, list[str]]:
    """(found, format problems). Found = a number in a faithful rendering; format problems are
    recorded for a figure that is there numerically but written wrong (unit, money, grouping)."""
    probs = []
    if value is None:
        return False, ["truth is NULL"]
    for v, u, tol in renderings(value, unit):
        for n in nums:
            if n["year"] and unit != "count":
                continue
            if not _near(n["val"], v, tol):
                continue
            if unit == "count":
                if n["year"] and not (2015 <= float(value) <= 2035):
                    continue
                if n["rupee"] or n["unit"] in ("lakh", "crore"):
                    probs.append(f"count {n['raw']} written as money/unit ({'₹' if n['rupee'] else ''}{n['unit'] or ''})")
                    continue
                if float(value) >= 1000 and not _is_indian(n["raw"]):
                    probs.append(f"{n['raw']} not in Indian grouping")
                    continue
                return True, []
            if unit == "pct":
                if n["unit"] != "pct":
                    probs.append(f"{n['raw']} without %")
                    continue
                return True, []
            if unit == "dec":
                if n["unit"] == "pct":
                    continue
                return True, []
            # money
            if u is None:
                if n["unit"] in ("lakh", "crore"):
                    continue
                if float(v) >= 1000 and not _is_indian(n["raw"]):
                    probs.append(f"{n['raw']} not in Indian grouping")
                    continue
                if n["raw"].endswith(".00"):
                    probs.append(f"{n['raw']} carries a '.00' tail")
                    continue
                return True, []
            if n["unit"] == u:
                return True, []
            probs.append(f"{n['raw']} matches the {u} figure but is written {n['unit'] or 'without a unit'}")
    return False, probs


def figure_in_table(data: list, value, unit: str) -> bool:
    if value is None or not data:
        return False
    for row in data:
        if not isinstance(row, dict):
            continue
        for col, cell in row.items():
            x = _num(cell)
            if x is None:
                continue
            for v, u, tol in renderings(value, unit):
                if u == "pct" or not _near(x, v, tol):
                    continue
                c = str(col).lower()
                if u == "crore" and "crore" not in c and "cr" not in c.split("_"):
                    continue
                if u == "lakh" and "lakh" not in c and unit != "lakh":
                    continue
                return True
    return False


def _num(cell):
    if isinstance(cell, bool) or cell is None:
        return None
    if isinstance(cell, (int, float, Decimal)):
        return float(cell)
    s = str(cell).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def norm(s) -> str:
    s = str(s if s is not None else "").lower()
    s = "".join(ch if (ch.isalnum() or ch in "&()") else " " for ch in s)
    return " ".join(s.split())


def _fy_label(v) -> str | None:
    s = str(v).strip()
    if len(s) == 4 and s.isdigit():
        return f"{s}-{(int(s) + 1) % 100:02d}"
    return None


def label_spans(text_norm: str, labels: list[str]) -> dict:
    """label -> [(start, end)] in the normalised text, an occurrence inside a longer label's dropped."""
    occ = []
    for lab in set(labels):
        if not lab:
            continue
        i = 0
        while True:
            j = text_norm.find(lab, i)
            if j < 0:
                break
            end = j + len(lab)
            ok_l = j == 0 or text_norm[j - 1] == " "
            ok_r = end == len(text_norm) or text_norm[end] == " "
            if ok_l and ok_r:
                occ.append((j, end, lab))
            i = j + 1
    occ.sort(key=lambda o: (-(o[1] - o[0]), o[0]))
    kept = []
    for o in occ:
        if any(k[0] <= o[0] and o[1] <= k[1] and (k[1] - k[0]) > (o[1] - o[0]) for k in kept):
            continue
        kept.append(o)
    out: dict = {}
    for s, e, lab in kept:
        out.setdefault(lab, []).append((s, e))
    for k in out:
        out[k].sort()
    return out


def check_rows(text: str, data: list, spec: dict, rows: list) -> list[str]:
    take = spec.get("take", "all")
    want = rows if take == "all" else rows[: int(take)]
    want = [r for r in want if r and r[0] is not None]
    tn = norm(text)
    labels = [norm(r[0]) for r in rows if r and r[0] is not None] + [norm(d) for d in DISTRICTS]
    spans = label_spans(tn, labels)
    starts = sorted(s for v in spans.values() for s, _ in v)
    fails = []
    for r in want:
        lab, value = norm(r[0]), r[-1]
        if value is None:
            continue
        ok = False
        for s, e in spans.get(lab, []):
            nxt = next((x for x in starts if x > s), len(tn))
            # the window (this label's end to the next label) is read back in the original text
            ok = _value_in_norm_window(text, tn, e, min(nxt, e + 220), value, spec.get("unit", "count"))
            if ok:
                break
        if not ok and data:
            ok = _row_in_table(data, lab, value, spec.get("unit", "count"))
        if not ok:
            fails.append(f"row {r[0]!s} = {value} missing")
    return fails


def _value_in_norm_window(text: str, tn: str, a: int, b: int, value, unit: str) -> bool:
    """The normalised text keeps the original's length only up to collapsed spaces, so the window is
    found again in the original by the label's own words: we map normalised offsets to original ones."""
    mapping = _norm_map(text)
    oa = mapping[a] if a < len(mapping) else len(text)
    ob = mapping[b] if b < len(mapping) else len(text)
    found, _ = find_figure(scan(text[oa:ob]), value, unit)
    return found


_MAP_CACHE: dict = {}


def _norm_map(text: str) -> list[int]:
    """For each index of norm(text), the index of the original character it came from."""
    if text in _MAP_CACHE:
        return _MAP_CACHE[text]
    chars = []
    for i, ch in enumerate(str(text).lower()):
        c = ch if (ch.isalnum() or ch in "&()") else " "
        chars.append((c, i))
    out_idx, prev_space, started = [], False, False
    for c, i in chars:
        if c == " ":
            if not started or prev_space:
                continue
            prev_space = True
            out_idx.append(i)
        else:
            started = True
            prev_space = False
            out_idx.append(i)
    _MAP_CACHE[text] = out_idx
    return out_idx


def _row_in_table(data: list, lab: str, value, unit: str) -> bool:
    for row in data:
        if not isinstance(row, dict):
            continue
        cells = list(row.values())
        if not any(isinstance(c, (str, int)) and (norm(c) == lab or norm(_fy_label(c) or "") == lab) for c in cells):
            continue
        if figure_in_table([{k: v for k, v in row.items()}], value, unit):
            return True
    return False


# ── judging one turn ───────────────────────────────────────────────────────────────────────────

def _fig_truth(f):
    return f.get("live", f.get("value"))


def judge_turn(turn: dict, rec, idx: int) -> dict:
    raw = rec.raw or {}
    text = rec.answer or ""
    data = raw.get("data") or []
    sql = (raw.get("sql_query") or raw.get("sql") or "")
    nums = scan(text)
    fails: list[tuple[str, str]] = []

    def fail(tag, msg):
        fails.append((tag, msg))

    pause = turn.get("pause", False)
    if rec.route == "error":
        fail("timeout/error", text[:200])
        return _verdict(fails)
    if pause is False and rec.route == "pause":
        fail("clarification", f"paused ({rec.pause_rule}): {text[:160]}")
        return _verdict(fails)
    if pause is True and rec.route != "pause":
        fail("clarification", f"expected a clarification, got {rec.route}")
        return _verdict(fails)
    if pause is True:
        return _verdict(fails)
    want_route = turn.get("route")
    if want_route and rec.route != want_route:
        refused = any(w in text.lower() for w in REFUSAL_WORDS)
        fail("refused-wrongly" if refused else "routing/intent", f"route {rec.route} != {want_route}")
    if turn.get("figures") or turn.get("rows"):
        if rec.route not in ("data",) and not want_route:
            refused = any(w in text.lower() for w in REFUSAL_WORDS)
            fail("refused-wrongly" if refused or rec.route == "denied" else "routing/intent",
                 f"route {rec.route}: {text[:160]}")
    if turn.get("schemes") is not None and rec.route != "pause":
        got = sorted((raw.get("schemes") or []))
        if got != sorted(turn["schemes"]):
            fail("routing/intent", f"schemes {got} != {sorted(turn['schemes'])}")

    def miss_tag():
        q = (rec.say or "").lower()
        if idx > 0:
            pl, yr = turn.get("place"), turn.get("year")
            if (pl and pl.lower() not in q and pl not in sql.upper()) or \
                    (yr is not None and str(yr) not in q and str(yr) not in sql):
                return "follow-up-context"
        if turn.get("place") and turn["place"] not in sql.upper() and sql:
            return "entity-resolution"
        if turn.get("year") is not None and sql and str(turn["year"]) not in sql:
            return "year"
        return None

    supported = []
    for f in turn.get("figures") or []:
        alts = f["any"] if "any" in f else [f]
        ok_any, probs_all, in_data, unworded = False, [], False, []
        for g in alts:
            val = _fig_truth(g)
            ok, probs = find_figure(nums, val, g["unit"])
            if raw.get("local_view") and not ok:
                ok, probs = figure_in_table(data, val, g["unit"]), []
            if ok and g.get("word") and g["word"].lower() not in text.lower():
                ok = False
                unworded.append(f"{g.get('label') or val} is stated but not called '{g['word']}'")
            supported += [r[0] for r in renderings(val, g["unit"])] if val is not None else []
            if ok:
                ok_any = True
                break
            probs_all += probs
            if figure_in_table(data, val, g["unit"]):
                in_data = True
        if ok_any:
            continue
        label = f.get("label") or "/".join(str(g.get("label") or g["unit"]) for g in alts)
        shown = " | ".join(f"{_fig_truth(g)}" for g in alts)
        tag = miss_tag()
        if unworded and not tag:
            fail("composer-misstated", f"{label} = {shown}: {'; '.join(unworded)}")
        elif probs_all and not tag:
            fail("unit/format", f"{label} = {shown}: {'; '.join(probs_all[:2])}")
        elif in_data and not tag:
            fail("composer-misstated", f"{label} = {shown}: in the result rows, not said")
        else:
            fail(tag or "sql-wrong", f"{label} = {shown} missing" + (f" ({'; '.join(probs_all[:1])})" if probs_all else ""))

    for spec_or_any in turn.get("rows") or []:
        specs = spec_or_any["any"] if "any" in spec_or_any else [spec_or_any]
        rf, spec, rows = None, specs[0], []
        for spec in specs:
            rows = spec.get("live", spec.get("value")) or []
            for v in rows:
                supported += [r[0] for r in renderings(v[-1], spec.get("unit", "count"))] if v[-1] is not None else []
            rf = check_rows(text, data, spec, rows)
            if not rf and spec.get("word") and spec["word"].lower() not in text.lower():
                rf = [f"the rows are right but the answer does not call them '{spec['word']}'"]
            if not rf:
                break
        if rf:
            tag = miss_tag() or "sql-wrong"
            if tag == "sql-wrong":
                take = spec.get("take", "all")
                want = rows if take == "all" else rows[: int(take)]
                if all(_row_in_table(data, norm(r[0]), r[-1], spec.get("unit", "count")) for r in want if r[0]):
                    tag = "composer-misstated"
            fail(tag, "; ".join(rf[:4]) + (f" (+{len(rf) - 4} more)" if len(rf) > 4 else ""))

    low = text.lower()
    for s in turn.get("has") or []:
        if s.lower() not in low:
            fail("composer-misstated", f"missing {s!r}")
    for alts in turn.get("any_of") or []:
        if not any(a.lower() in low for a in alts):
            fail("composer-misstated", f"none of {alts!r}")
    for s in turn.get("lacks") or []:
        if s in text:
            money_count = s.startswith(("Rs", "₹")) or "lakh" in s
            fail("unit/format" if money_count else "composer-misstated", f"must not say {s!r}")

    chart = turn.get("chart") or ""
    if chart.startswith("unsupported:"):
        # what is DRAWN is graded on the UI's own viewPlan after the run (grade_charts); here: the words
        kind = chart.split(":", 1)[1]
        said = kind in low and any(w in low for w in ("not available", "not supported", "isn't", "is not",
                                                      "cannot", "can't", "instead", "not offered"))
        if not said:
            fail("chart", f"{kind} chart asked: the answer does not say it is not available")

    if turn.get("strict") and not raw.get("local_view"):
        q_nums = {n["val"] for n in scan(rec.say or "")}
        extra = []
        for n in nums:
            if n["year"] or n["marker"] or n["val"] in q_nums or n["val"] == 0:
                continue
            if n["val"] <= 12 and n["unit"] is None and not n["rupee"] and "." not in n["raw"]:
                continue
            if any(_near(n["val"], s, max(0.0101, abs(s) * 1e-9)) for s in supported):
                continue
            extra.append(n["raw"])
        if extra:
            fail("composer-misstated", f"figures the truth does not support: {extra[:5]}")
    return _verdict(fails)


def _verdict(fails):
    tags = [t for t, _ in fails]
    primary = next((t for t in TAG_ORDER if t in tags), None)
    return {"ok": not fails, "primary": primary, "fails": [f"[{t}] {m}" for t, m in fails]}


# ── running ────────────────────────────────────────────────────────────────────────────────────

async def run_case(case: dict, d, scope, sem) -> dict:
    async with sem:
        t_case = time.perf_counter()
        conv = SuperadminConversation(d.store, scope)
        out_turns = []
        drift = []
        last_raw = None
        for i, turn in enumerate(case["turns"]):
            try:
                await live_truth(turn)
            except Exception as e:  # noqa: BLE001
                out_turns.append({"q": turn["q"], "ok": False, "primary": "timeout/error",
                                  "fails": [f"[timeout/error] truth SQL failed: {type(e).__name__}: {e}"]})
                break
            for f in _flat_figs(turn):
                if f.get("value") is not None and f.get("live") is not None and abs(float(f["value"]) - float(f["live"])) > 1e-6:
                    drift.append(f"t{i + 1} {f.get('label') or f['unit']}: recorded {f['value']} live {f['live']}")
            t0 = time.perf_counter()
            view = VIEW_ONLY.get(turn["q"])
            if view and last_raw is not None:
                # App.jsx redraws a view-only message ("pie chart", "give me donut") from the last answer's rows
                # and never sends it to the server: so does the bank (the server's conversation never sees it)
                rec = TurnRecord(say=turn["q"], route="data", answer=f"Here is the same data as {view}.", ms=0,
                                 raw={**last_raw, "local_view": view, "rewritten_question": None})
            else:
                try:
                    rec = await asyncio.wait_for(conv.ask(turn["q"]), TURN_TIMEOUT)
                except asyncio.TimeoutError:
                    rec = TurnRecord(say=turn["q"], route="error", answer=f"timeout after {TURN_TIMEOUT:.0f}s",
                                     ms=round((time.perf_counter() - t0) * 1000))
            v = judge_turn(turn, rec, i)
            raw = rec.raw or {}
            if raw.get("data") and not raw.get("local_view"):
                last_raw = {"data": raw.get("data"), "schemes": raw.get("schemes"), "chart_type": raw.get("chart_type"),
                            "sql_query": raw.get("sql_query") or raw.get("sql")}
            out_turns.append({
                "q": turn["q"], **v, "local_view": raw.get("local_view"), "route": rec.route, "pause_rule": rec.pause_rule, "seconds": round(rec.ms / 1000, 1),
                "answer": rec.answer, "schemes": raw.get("schemes"), "chart_type": raw.get("chart_type"),
                "rewritten": raw.get("rewritten_question"), "sql": raw.get("sql_query") or raw.get("sql"),
                "data": (raw.get("data") or [])[:300], "data_full": raw.get("data") or [], "chips": rec.chips,
                "truth": [{"label": f.get("label"), "unit": f["unit"], "live": f.get("live")} for f in _flat_figs(turn)]
                + [{"rows": r.get("live", []), "unit": r.get("unit"), "take": r.get("take")} for r in _flat_rows(turn)],
            })
        ok = all(t.get("ok") for t in out_turns) and len(out_turns) == len(case["turns"])
        prim = next((t.get("primary") for t in out_turns if not t.get("ok")), None)
        res = {"id": case["id"], "cat": case["cat"], "shape": case["shape"], "src": case.get("src"), "ok": ok,
               "primary": prim, "drift": drift, "seconds": round(time.perf_counter() - t_case, 1), "turns": out_turns}
        bad = [f"t{i + 1}: " + "; ".join(t["fails"]) for i, t in enumerate(out_turns) if not t.get("ok")]
        print(f"{'PASS' if ok else 'FAIL'} {case['id']:<16} {case['cat']:<18} {res['seconds']:>6}s"
              + ("" if ok else "  " + " || ".join(bad)[:600]), flush=True)
        return res


VIEW_ONLY: dict = {}


def view_only_map(questions: list) -> dict:
    """{question: view} for the messages the chat UI redraws itself (App.jsx viewOnlyRequest), read with the
    frontend's own function (tests/accuracy/chart_view.mjs --view-only)."""
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(sorted(set(questions)), fh)
        tmp = fh.name
    try:
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "accuracy", "chart_view.mjs"), "--view-only", tmp],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        return {k: v for k, v in json.loads(out.stdout or "{}").items() if v}
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: view-only map unavailable ({e}); every turn goes to the server", flush=True)
        return {}
    finally:
        os.unlink(tmp)


def grade_charts(results: list, cases: list) -> None:
    """The chart each `chart` turn DRAWS, graded with the chat UI's own viewPlan (tests/accuracy/chart_view.mjs
    over frontend/src/chat/analytics.js, read only): a named type must be the chart drawn (alone);
    'horizontal_bar' = hbar; 'multi' = a chart is drawn; 'unsupported:<kind>' = something is drawn (the words
    were checked in judge_turn)."""
    import subprocess
    import tempfile
    by_id = {c["id"]: c for c in cases}
    items, where = [], {}
    for r in results:
        last = None
        for i, t in enumerate(r["turns"]):
            want = (by_id[r["id"]]["turns"][i] if i < len(by_id[r["id"]]["turns"]) else {}).get("chart")
            resp = {"route": t.get("route"), "data": t.get("data_full") or t.get("data") or [],
                    "chart_type": t.get("chart_type"), "answer": t.get("answer"), "rewritten_question": t.get("rewritten")}
            if want:
                key = f"{r['id']}#{i}"
                items.append({"key": key, "q": t["q"], "r": resp, "last": last})
                where[key] = (r, i, want)
            if resp["data"]:
                last = {"q": t["q"], "r": resp}
    if not items:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(items, fh, default=str)
        tmp = fh.name
    try:
        out = subprocess.run(["node", os.path.join(ROOT, "tests", "accuracy", "chart_view.mjs"), tmp],
                             capture_output=True, text=True, encoding="utf-8", timeout=120)
        plans = json.loads(out.stdout or "{}")
    except Exception as e:  # noqa: BLE001
        plans = {k: {"error": f"node failed: {e}"} for k in where}
    finally:
        os.unlink(tmp)
    for key, (r, i, want) in where.items():
        t = r["turns"][i]
        plan = plans.get(key)
        t["drawn"] = plan
        charts = (plan or {}).get("charts") or []
        initials = [c.get("initial") for c in charts]
        msg = None
        if plan is None or (plan or {}).get("error") or not charts:
            msg = f"nothing drawn ({(plan or {}).get('mode') or (plan or {}).get('error') or 'no rows'})"
        elif want in ("pie", "doughnut", "line", "stacked", "bar"):
            if any(x != want for x in initials) or any(len(c.get("types") or []) != 1 for c in charts):
                msg = f"drawn {initials} {[c.get('types') for c in charts]} for {want}"
        elif want == "horizontal_bar":
            if any(x != "hbar" for x in initials):
                msg = f"drawn {initials} for a horizontal bar chart"
        elif want == "grouped_bar":
            if plan.get("mode") not in ("grouped", "twoDim") or any(x != "bar" for x in initials):
                msg = f"drawn {plan.get('mode')} {initials} for a grouped bar chart"
        if msg:
            t["fails"].append(f"[chart] {msg}")
            t["ok"] = False
            if t.get("primary") is None:
                t["primary"] = "chart"
    for r in results:
        r["ok"] = all(t.get("ok") for t in r["turns"]) and r["ok"]
        r["primary"] = next((t.get("primary") for t in r["turns"] if not t.get("ok")), None)


def _flat_rows(turn):
    out = []
    for r in turn.get("rows") or []:
        out += r["any"] if "any" in r else [r]
    return out


def _flat_figs(turn):
    out = []
    for f in turn.get("figures") or []:
        out += f["any"] if "any" in f else [f]
    return out


def summary(results: list) -> str:
    lines = []
    cats: dict = {}
    for r in results:
        c = cats.setdefault(r["cat"], [0, 0, 0, 0])
        c[0] += r["ok"]
        c[1] += 1
        c[2] += sum(1 for t in r["turns"] if t.get("ok"))
        c[3] += len(r["turns"])
    lines.append(f"{'category':<20}{'cases':>12}{'turns':>12}")
    for k in sorted(cats):
        a, b, c2, d2 = cats[k]
        lines.append(f"{k:<20}{f'{a}/{b}':>12}{f'{c2}/{d2}':>12}")
    a = sum(r["ok"] for r in results)
    tt = sum(len(r["turns"]) for r in results)
    tp = sum(1 for r in results for t in r["turns"] if t.get("ok"))
    lines.append(f"{'TOTAL':<20}{f'{a}/{len(results)}':>12}{f'{tp}/{tt}':>12}   "
                 f"({100.0 * a / max(1, len(results)):.1f}% cases)")
    tags: dict = {}
    for r in results:
        for t in r["turns"]:
            if not t.get("ok") and t.get("primary"):
                tags.setdefault(t["primary"], []).append(r["id"])
    lines.append("\nfailure taxonomy (primary tag per failing turn):")
    for t in TAG_ORDER:
        if t in tags:
            lines.append(f"  {t:<20}{len(tags[t]):>4}  {', '.join(sorted(set(tags[t])))[:300]}")
    drift = [(r["id"], r["drift"]) for r in results if r.get("drift")]
    if drift:
        lines.append("\ntruth drift since the bank was recorded (data reloaded?):")
        for cid, dd in drift:
            lines.append(f"  {cid}: {'; '.join(dd)}")
    return "\n".join(lines)


def regrade(path: str, bank: dict) -> int:
    """Judge a saved run again with the current checks and the truth it recorded (no model call, no DB):
    for changes to the judge itself."""
    with open(path, encoding="utf-8") as fh:
        prev = json.load(fh)
    by_id = {c["id"]: c for c in bank["cases"]}
    VIEW_ONLY.update(view_only_map([t["q"] for r in prev["results"] for t in r["turns"]]))
    results = []
    for r in prev["results"]:
        case = by_id.get(r["id"])
        if not case:
            continue
        last = None
        for i, t in enumerate(r["turns"]):
            if i >= len(case["turns"]) or "route" not in t:
                continue
            view = VIEW_ONLY.get(t["q"])
            if view and last is not None and not t.get("local_view"):
                # a run made before the bank emulated the UI's local redraw: judged as the UI shows it
                t.update({"route": "data", "answer": f"Here is the same data as {view}.", "local_view": view,
                          "data": last["data"], "schemes": last["schemes"], "chart_type": last["chart_type"],
                          "sql": last["sql"], "rewritten": None, "pause_rule": None})
            elif t.get("data") and not t.get("local_view"):
                last = {"data": t["data"], "schemes": t.get("schemes"), "chart_type": t.get("chart_type"),
                        "sql": t.get("sql")}
            turn = case["turns"][i]
            figs, rows = _flat_figs(turn), _flat_rows(turn)
            fl = [x for x in t.get("truth", []) if "rows" not in x]
            rl = [x for x in t.get("truth", []) if "rows" in x]
            for f, x in zip(figs, fl):
                f["live"] = x.get("live")
            for spec, x in zip(rows, rl):
                spec["live"] = x.get("rows")
            rec = TurnRecord(say=t["q"], route=t["route"], answer=t.get("answer") or "", pause_rule=t.get("pause_rule"),
                             chips=t.get("chips") or [], ms=int((t.get("seconds") or 0) * 1000),
                             raw={"schemes": t.get("schemes"), "chart_type": t.get("chart_type"), "sql_query": t.get("sql"),
                                  "data": t.get("data"), "rewritten_question": t.get("rewritten"),
                                  "local_view": t.get("local_view")})
            t.update(judge_turn(turn, rec, i))
        r["ok"] = all(t.get("ok") for t in r["turns"]) and len(r["turns"]) == len(case["turns"])
        r["primary"] = next((t.get("primary") for t in r["turns"] if not t.get("ok")), None)
        results.append(r)
    grade_charts(results, [by_id[r["id"]] for r in results])
    for r in results:
        if not r["ok"]:
            bad = [f"t{i + 1}: " + "; ".join(t["fails"]) for i, t in enumerate(r["turns"]) if not t.get("ok")]
            print(f"FAIL {r['id']:<16} {r['cat']:<18} " + " || ".join(bad)[:500])
    text = summary(results)
    out = path.replace(".json", "_regraded.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({**prev, "summary": text, "results": results, "regraded_from": os.path.basename(path)}, fh,
                  indent=1, ensure_ascii=False, default=str)
    print("\n" + text + f"\n\nwritten {os.path.relpath(out, ROOT)}")
    return 0 if all(r["ok"] for r in results) else 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of ids, id prefixes or categories")
    ap.add_argument("--failed", help="a results JSON: re-run only the cases that failed there")
    ap.add_argument("--regrade", help="a results JSON: judge it again with the current checks (no model call)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()
    with open(BANK, encoding="utf-8") as fh:
        bank = yaml.safe_load(fh)
    if args.regrade:
        return regrade(args.regrade, bank)
    cases = bank["cases"]
    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
        cases = [c for c in cases if any(c["id"] == k or c["id"].startswith(k) or c["cat"] == k for k in keys)]
    if args.failed:
        with open(args.failed, encoding="utf-8") as fh:
            prev = json.load(fh)
        bad = {r["id"] for r in prev["results"] if not r["ok"]}
        cases = [c for c in cases if c["id"] in bad]
    print(f"{len(cases)} cases, {sum(len(c['turns']) for c in cases)} turns, concurrency {args.concurrency}", flush=True)
    VIEW_ONLY.update(view_only_map([t["q"] for c in cases for t in c["turns"]]))
    t0 = time.perf_counter()
    async with InProcessDriver() as d:
        scope = await superadmin_scope()
        sem = asyncio.Semaphore(max(1, min(args.concurrency, 4)))
        results = await asyncio.gather(*(run_case(c, d, scope, sem) for c in cases))
    grade_charts(results, cases)
    for r in results:
        for t in r["turns"]:
            t.pop("data_full", None)
        if not r["ok"] and any(t.get("primary") == "chart" for t in r["turns"]):
            print(f"FAIL {r['id']:<16} (chart) " + " || ".join("; ".join(t["fails"]) for t in r["turns"]
                                                             if not t.get("ok"))[:400], flush=True)
    os.makedirs(RESULTS, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H%M")
    path = os.path.join(RESULTS, f"{stamp}_{args.label}.json")
    text = summary(results)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"label": args.label, "when": stamp, "seconds": round(time.perf_counter() - t0),
                   "bank_recorded": bank.get("truth_recorded"), "summary": text, "results": results}, fh,
                  indent=1, ensure_ascii=False, default=str)
    print("\n" + text)
    print(f"\n{round(time.perf_counter() - t0)} s; written {os.path.relpath(path, ROOT)}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
