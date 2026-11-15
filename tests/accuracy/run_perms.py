"""Permutation bank: scheme x district x follow-up, by VOICE and TYPED (2026-11-16, before the main demo).

Not collected by pytest (not named test_*.py). Needs megh_db (VPN); the model gateway for the model-on run.

Every chain is one conversation of 2-5 turns over the 8 schemes and the 12 districts ("<scheme> <measure> by district"
-> "break down <district> by block" / "break that down by block" / "<district> block-wise" / "can you break <district>
by the blocks for the same" -> "which block has the most" / "top 3" / "the lowest" -> "show this as a bar chart" / "as a
pie" / "on the map" / "as a table"; "only <block>", "what about <year>", "and for <other district>", "the <measure>
instead"; a fresh chat "breakdown by blocks of <district>" -> the scheme pause -> the scheme). Each chain runs twice:

  typed  the words straight to the chat pipeline (in-process, as the superadmin, like run_gold.py); a chart switch
         must be the chat's own local redraw (frontend analytics.js viewOnlyRequest), never a server question;
  voice  each turn through the sovereign engine's question shaper (D:/Full Duplex Architecture/megh/shaper.py
         `shape()`) with the engine's turn memory kept as the adapter keeps it (asked -> answered with the pipeline's
         own reading `asked_as` and answer frame; a clarification's options; a redraw = a note), then the shaped
         question to the same pipeline; a chart switch must come out as one of the page's canonical sentences
         (voiceViews.js canonicalView).

Truth: independent SQL from the verified catalogue definitions (semantic.metric_definitions), built in this file
(blocks OF THAT district, the measure, the year scope, the ranking / top N), recomputed live; each answer is judged
with run_gold.judge_turn (text or table, Indian grouping, lakh / crore renderings).

    .venv/Scripts/python.exe tests/accuracy/run_perms.py --build              # (re)write perms_bank.yaml from megh_db
    .venv/Scripts/python.exe tests/accuracy/run_perms.py --label perms-1      # both paths, model on
    .venv/Scripts/python.exe tests/accuracy/run_perms.py --paths typed --only K1,K3 --schemes MGNREGA
    .venv/Scripts/python.exe tests/accuracy/run_perms.py --nomodel --label perms-nm1   # every model = the 503 stub

Writes tests/accuracy/results/<stamp>_<label>.json and prints the matrix (chain kind x scheme: voice, typed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "perms_bank.yaml")
RESULTS = os.path.join(HERE, "results")
FDX = os.environ.get("FDX_ROOT", r"D:\Full Duplex Architecture")
STUB = "http://127.0.0.1:8409/v1"
MODEL_URL_KEYS = ["CLASSIFIER_BASE_URL", "SQL_GENERATION_BASE_URL", "RESPONSE_MODEL_BASE_URL", "REWRITE_BASE_URL",
                  "SQL_VERIFY_BASE_URL", "RERANKER_BASE_URL", "ASR_BASE_URL"]

# ── the measures (semantic.metric_definitions, verified catalogue) ─────────────────────────────────────────────────
# (scheme, the words said) -> view, expression, base filter, block column, unit (run_gold units)
MEASURES = {
    ("MGNREGA", "person-days"): ("curated.v_employment", "SUM(person_days)", "TRUE", "lgd_block", "count"),
    ("MGNREGA", "expenditure"): ("curated.v_expenditure", "ROUND(SUM(total_exp), 2)", "TRUE", "lgd_block", "lakh"),
    # D-060 (2026-10-22): the 126 zero-sanction registrations are houses sanctioned: no is_placeholder filter
    ("PMAY-G", "houses completed"): ("curated.v_pmay", "COUNT(*)", "is_completed", "lgd_block", "count"),
    ("PMAY-G", "houses sanctioned"): ("curated.v_pmay", "COUNT(*)", "TRUE", "lgd_block", "count"),
    ("PMAY-G", "amount released"): ("curated.v_pmay", "SUM(amount_released)", "TRUE", "lgd_block", "rupees"),
    ("Focus Plus", "beneficiaries"): ("curated.v_focus_plus", "COUNT(DISTINCT beneficiary_key)", "TRUE", "UPPER(block_name_raw)", "count"),
    ("Focus Plus", "amount disbursed"): ("curated.v_focus_plus", "SUM(amount_disbursed)", "TRUE", "UPPER(block_name_raw)", "rupees"),
    ("Focus Legacy", "amount disbursed"): ("curated.v_focus_legacy", "SUM(amount_disbursed)", "TRUE", "lgd_block", "rupees"),
    ("Focus Legacy", "producer groups"): ("curated.v_focus_legacy", "COUNT(DISTINCT pg_id)", "TRUE", "lgd_block", "count"),
    ("CM Elevate", "applications"): ("curated.v_cm_elevate", "COUNT(DISTINCT request_id)", "data_verified = 'Valid'", "lgd_block", "count"),
    ("CM Elevate Legacy", "total disbursed"): ("curated.v_cm_elevate_disbursement", "SUM(total_disbursement)", "TRUE", "lgd_block", "rupees"),
    ("CM Elevate Legacy", "sanctioned amount"): ("curated.v_cm_elevate_disbursement", "SUM(sanctioned_amount)", "TRUE", "lgd_block", "rupees"),
    ("CMSS", "students paid"): ("curated.v_cmss", "COUNT(*)", "is_disbursed", "lgd_block", "count"),
    ("CMSS", "amount disbursed"): ("curated.v_cmss", "SUM(amount_disbursed)", "TRUE", "lgd_block", "rupees"),
    ("CMSS", "applications"): ("curated.v_cmss", "COUNT(*)", "TRUE", "lgd_block", "count"),
    ("Homestay", "applications"): ("curated.v_homestay_api", "COUNT(*)", "TRUE", "lgd_block", "count"),
    ("Homestay", "approved applications"): ("curated.v_homestay_api", "COUNT(*)", "file_status = 'Approved'", "lgd_block", "count"),
}
# per scheme: main measure, second measure (a "... instead" switch), a year with data, the headline measure (c16)
SCHEMES = {
    "MGNREGA": ("person-days", "expenditure", 2023, "person-days"),
    "PMAY-G": ("houses completed", "amount released", 2022, "houses sanctioned"),
    "Focus Plus": ("beneficiaries", "amount disbursed", 2025, "beneficiaries"),
    "Focus Legacy": ("amount disbursed", "producer groups", 2024, "producer groups"),
    "CM Elevate": ("applications", None, None, "applications"),
    "CM Elevate Legacy": ("total disbursed", "sanctioned amount", 2024, None),
    "CMSS": ("students paid", "amount disbursed", None, "applications"),
    "Homestay": ("applications", "approved applications", 2025, "applications"),
}
DISTRICTS = ["EAST KHASI HILLS", "WEST GARO HILLS", "RI BHOI", "NORTH GARO HILLS", "WEST JAINTIA HILLS",
             "SOUTH WEST GARO HILLS", "EAST GARO HILLS", "WEST KHASI HILLS", "SOUTH GARO HILLS", "EAST JAINTIA HILLS",
             "SOUTH WEST KHASI HILLS", "EASTERN WEST KHASI HILLS"]


def title(s: str) -> str:
    return " ".join(w.capitalize() for w in str(s).lower().split())


def fy(y: int) -> str:
    return f"{y}-{(y + 1) % 100:02d}"


def truth_sql(scheme, measure, group, district=None, year=None, block=None, order="DESC") -> str:
    view, expr, base, bcol, _u = MEASURES[(scheme, measure)]
    col = bcol if group == "block" else "lgd_district"
    where = [base, f"{col} IS NOT NULL"]
    if district:
        where.append(f"lgd_district = '{district}'")
    if year is not None:
        where.append(f"year_key = {int(year)}")
    if block:
        where.append(f"{bcol} = '{block}'")
    return (f"SELECT {col}, {expr} FROM {view} WHERE {' AND '.join(where)} GROUP BY 1 "
            f"ORDER BY 2 {order} NULLS LAST, 1")


def figure_sql(scheme, measure, district=None, year=None, block=None) -> str:
    view, expr, base, bcol, _u = MEASURES[(scheme, measure)]
    where = [base]
    if district:
        where.append(f"lgd_district = '{district}'")
    if year is not None:
        where.append(f"year_key = {int(year)}")
    if block:
        where.append(f"{bcol} = '{block}'")
    return f"SELECT {expr} FROM {view} WHERE {' AND '.join(where)}"


def rows_turn(q, scheme, measure, group, district=None, year=None, block=None, take="all", order="DESC", place=None):
    unit = MEASURES[(scheme, measure)][4]
    if block or (group == "district" and district):
        # one place: its one figure (the answer may say the figure before the place's name)
        return {"q": q, "pause": False, "place": place or title(block or district),
                "figures": [{"sql": figure_sql(scheme, measure, district, year, block), "unit": unit}]}
    return {"q": q, "pause": False, "place": place or (title(district) if district else None),
            "rows": [{"sql": truth_sql(scheme, measure, group, district, year, block, order), "unit": unit, "take": take}]}


def view_turn(q, view):
    return {"q": q, "view": view}


def nav_turn(q, nav="go back to the dashboard"):
    return {"q": q, "nav": nav}


# one-shot fully specified questions (the user's live logs, 16 Nov): scheme + measure + year + district + block
ONESHOT = [("MGNREGA", "person-days", 2024), ("PMAY-G", "houses completed", 2022), ("Focus Legacy", "amount disbursed", 2024),
           ("CM Elevate Legacy", "total disbursed", 2024), ("CMSS", "students paid", 2025), ("Homestay", "applications", 2025),
           ("Focus Plus", "beneficiaries", 2025)]
SPOKEN_FY = {2022: "twenty twenty-two twenty-three", 2023: "twenty twenty-three twenty-four",
             2024: "twenty twenty-four twenty-five", 2025: "twenty twenty-five twenty-six"}
AMBIGUOUS_BLOCKS = [("Mawlai", "EAST KHASI HILLS"), ("Nongstoin", "WEST KHASI HILLS"), ("Resubelpara", "NORTH GARO HILLS"),
                    ("Chokpot", "SOUTH GARO HILLS")]


def oneshot_chains(yblocks: dict) -> list[dict]:
    """K12: MGNREGA expenditure 2023-24 for EVERY block; K13: every block again for a rotating other scheme (its own
    year with data). The voice says the year aloud ("twenty twenty-three twenty-four" / "23-24") and the block plainly."""
    out = []
    exp = yblocks.get(("MGNREGA", "expenditure", 2023), [])
    for i, (d, b) in enumerate(exp):
        q = f"MGNREGA expenditure for the financial year 2023-24 in {title(d)}, {title(b)} block"
        vq = [f"MGNREGA expenditure for the financial year {SPOKEN_FY[2023]} in {title(d)}, {title(b)} block",
              f"MGNREGA expenditure for 23-24 in {title(d)} {title(b)} block",
              f"{title(b)} block of {title(d)}, MGNREGA expenditure in 2023-24"][i % 3]
        t = rows_turn(q, "MGNREGA", "expenditure", "block", d, 2023, b)
        t["voice_q"] = vq
        out.append({"id": f"K12-{b.replace(' ', '')[:16]}", "kind": "K12", "scheme": "MGNREGA", "district": d, "turns": [t]})
    for i, (d, b) in enumerate(exp):
        for j in range(len(ONESHOT)):
            S, M, Y = ONESHOT[(i + j) % len(ONESHOT)]
            have = {x[1].upper(): x for x in yblocks.get((S, M, Y), []) if x[0] == d}
            if b.upper() in have:
                bb = have[b.upper()][1]
                q = f"{S} {M} in {fy(Y)} in {title(d)}, {title(bb)} block"
                t = rows_turn(q, S, M, "block", d, Y, bb)
                t["voice_q"] = (f"{S} {M} in {SPOKEN_FY[Y]} in {title(d)}, {title(bb)} block" if i % 2 == 0
                                else f"{S} {M} for {fy(Y)[2:]} in {title(bb)} block, {title(d)}")
                out.append({"id": f"K13-{S.replace(' ', '')}-{bb.replace(' ', '')[:14]}", "kind": "K13", "scheme": S,
                            "district": d, "turns": [t]})
                break
    return out


def vague_chains(blocks: dict) -> list[dict]:
    """Questions that must ask back, then answer exactly after the pick (the user's live logs)."""
    out = []
    for i, (S, (m1, _m2, _y, head)) in enumerate(SCHEMES.items()):
        if not head:
            continue
        ds = [d for d in DISTRICTS[i:] + DISTRICTS[:i] if len(blocks.get(f"{S}|{head}|{d}", [])) >= 2]
        if not ds:
            continue
        d = ds[0]
        # K14: a scheme and a place but no measure: the scheme's headline measure, block by block
        out.append({"id": f"K14-{S.replace(' ', '')}", "kind": "K14", "scheme": S, "district": d,
                    "turns": [rows_turn(f"{S} in {title(d)} block-wise", S, head, "block", d)]})
    # K15: "Focus" alone: which Focus (Plus or Legacy), then the pick
    out.append({"id": "K15-FocusPlus", "kind": "K15", "scheme": "Focus Plus", "district": "",
                "turns": [{"q": "Focus beneficiaries by district", "pause": True},
                          dict(rows_turn("Focus Plus", "Focus Plus", "beneficiaries", "district", place="-"), pick="Focus Plus")]})
    out.append({"id": "K15-FocusLegacy", "kind": "K15", "scheme": "Focus Legacy", "district": "WEST GARO HILLS",
                "turns": [{"q": "Focus amount disbursed in West Garo Hills by block", "pause": True},
                          dict(rows_turn("Focus Legacy", "Focus Legacy", "amount disbursed", "block", "WEST GARO HILLS"),
                               pick="Focus Legacy")]})
    # K16: the CM Elevate dataset question (D-099), then the pick
    out.append({"id": "K16-CMElevate", "kind": "K16", "scheme": "CM Elevate", "district": "RI BHOI",
                "turns": [{"q": "CM Elevate applications in Ri Bhoi by block", "pause": True},
                          dict(rows_turn("CM Elevate", "CM Elevate", "applications", "block", "RI BHOI"), pick="CM Elevate")]})
    # K17: a place at two levels (block and constituency): which one, then the block
    for name, d in AMBIGUOUS_BLOCKS:
        out.append({"id": f"K17-{name}", "kind": "K17", "scheme": "MGNREGA", "district": d,
                    "turns": [{"q": f"MGNREGA person-days in {name}", "pause": True},
                              dict(rows_turn("the block", "MGNREGA", "person-days", "block", d, block=name.upper()),
                                   pick="block")]})
    return out


def logged_chains() -> list[dict]:
    """K18 / K19: the wordings of the user's live logs (16 Nov)."""
    out = []
    for S, M, Y, d in [("MGNREGA", "person-days", 2023, "RI BHOI"), ("PMAY-G", "houses completed", 2022, "WEST GARO HILLS"),
                       ("Focus Legacy", "amount disbursed", 2024, "EAST KHASI HILLS")]:
        out.append({"id": f"K18-{S.replace(' ', '')}", "kind": "K18", "scheme": S, "district": d, "turns": [
            {"q": f"{S} {M} in {fy(Y)}", "pause": False, "place": "-",
             "figures": [{"sql": figure_sql(S, M, year=Y), "unit": MEASURES[(S, M)][4]}]},
            rows_turn("break it down by the district", S, M, "district", year=Y, place="-"),
            rows_turn(f"what about {title(d)}?", S, M, "district", d, year=Y),
            nav_turn("go back to the dashboard")]})
    for S, M in [("MGNREGA", "expenditure"), ("MGNREGA", "person-days"), ("PMAY-G", "amount released"),
                 ("Focus Legacy", "amount disbursed")]:
        view, expr, base, _b, unit = MEASURES[(S, M)]
        # "per financial year across all districts" = the state's figure per year (all districts together; the lead,
        # from the user's log, 16 Nov); "for every financial year" the same
        sql = (f"SELECT financial_year_short, {expr} FROM {view} WHERE {base} AND year_key IS NOT NULL "
               f"GROUP BY 1 ORDER BY 1")
        t = {"q": f"Could you please show me the {S} {M} per financial year across all districts", "pause": False,
             "place": "-", "rows": [{"sql": sql, "unit": unit, "take": "all"}]}
        out.append({"id": f"K18y-{S.replace(' ', '')}-{M.split()[0]}", "kind": "K18", "scheme": S, "district": "", "turns": [t]})
        t = {"q": f"I want you to show me the {S} {M} for every financial year.", "pause": False,
             "place": "-", "rows": [{"sql": sql, "unit": unit, "take": "all"}]}
        out.append({"id": f"K18e-{S.replace(' ', '')}-{M.split()[0]}", "kind": "K18", "scheme": S, "district": "", "turns": [t]})
    # K19: the same, as the ears heard it (engine log): "Meghalaya expenditure" for "MGNREGA expenditure", "per
    # financial" with "year" lost
    view, expr, base, _b, unit = MEASURES[("MGNREGA", "expenditure")]
    sql = f"SELECT financial_year_short, {expr} FROM {view} WHERE {base} AND year_key IS NOT NULL GROUP BY 1 ORDER BY 1"
    out.append({"id": "K19-asr", "kind": "K19", "scheme": "MGNREGA", "district": "", "turns": [
        rows_turn("MGNREGA person-days by district", "MGNREGA", "person-days", "district", place="-"),
        {"q": "Could you please show me the MGNREGA expenditure per financial year across all districts",
         "voice_q": "Could you please show me the Meghalaya expenditure per financial across all districts",
         "pause": False, "place": "-", "rows": [{"sql": sql, "unit": unit, "take": "all"}]}]})
    return out


# ── the bank ──────────────────────────────────────────────────────────────────────────────────────────────────────
NAMED_BLOCK = ["break down {d} by block", "can you break {d} by the blocks for the same",
               "okay, now could you break down {d} by the blocks please", "{d} block-wise",
               "can you break down {d} by the blocks", "break down {d} by the block for the same"]


def chains_for(scheme: str, idx: int, blocks: dict) -> list[dict]:
    """The chains of one scheme. `blocks[(measure, district)]` = its blocks with data (UPPER), so a district is only
    used where it has at least two blocks with data; districts rotate by scheme so all 12 appear per scheme."""
    m1, m2, year, head = SCHEMES[scheme]
    ok = [d for d in DISTRICTS[idx:] + DISTRICTS[:idx] if len(blocks.get((m1, d), [])) >= 2]
    if not ok:
        return []
    D = [ok[i % len(ok)] for i in range(12)]
    S = scheme
    out = []

    def add(kind, turns, d):
        out.append({"id": f"{kind}-{S.replace(' ', '')}-{d.replace(' ', '')[:10]}", "kind": kind, "scheme": S,
                    "district": d, "turns": turns})

    q1 = f"{S} {m1} by district"
    d = D[0]
    add("K1", [rows_turn(q1, S, m1, "district", place="-"),
               rows_turn(NAMED_BLOCK[idx % len(NAMED_BLOCK)].format(d=title(d)), S, m1, "block", d),
               rows_turn("which block has the most", S, m1, "block", d, take=1),
               view_turn("show this as a bar chart", "bar")], d)
    d = D[1]
    add("K2", [rows_turn(f"{S} {m1} in {title(d)}", S, m1, "district", d),
               rows_turn("break that down by block", S, m1, "block", d),
               rows_turn("top 3", S, m1, "block", d, take=3),
               view_turn("as a pie", "pie")], d)
    d = D[2]
    add("K3", [rows_turn(f"{S} {m1} in {title(d)}", S, m1, "district", d),
               rows_turn("break it down by block", S, m1, "block", d),
               rows_turn("which block has the lowest", S, m1, "block", d, take=1, order="ASC"),
               view_turn("as a table", "table")], d)
    d = D[3]
    b = blocks[(m1, d)][0]
    add("K4", [rows_turn(f"{S} {m1} in {title(d)} by block", S, m1, "block", d),
               rows_turn(f"only {title(b)}", S, m1, "block", d, block=b, place=title(b)),
               view_turn("show it on the map", "map")], d)
    if year is not None:
        d = D[4]
        add("K5", [rows_turn(q1, S, m1, "district", place="-"),
                   rows_turn(f"what about {fy(year)}", S, m1, "district", year=year, place="-"),
                   rows_turn(f"break down {title(d)} by block", S, m1, "block", d, year=year)], d)
    d, d2 = D[5], D[6]
    add("K6", [rows_turn(f"can you break {title(d)} by the blocks for {S} {m1}", S, m1, "block", d),
               rows_turn(f"and for {title(d2)}", S, m1, "block", d2),
               view_turn("show it as a bar chart please", "bar")], d)
    if m2 and len(blocks.get((m2, D[7]), [])) >= 2:
        d = D[7]
        add("K7", [rows_turn(q1, S, m1, "district", place="-"),
                   rows_turn(f"{title(d)} block-wise", S, m1, "block", d),
                   rows_turn(f"the {m2} instead", S, m2, "block", d)], d)
    if head and len(blocks.get((head, D[8]), [])) >= 2:
        d = D[8]
        add("K8", [{"q": f"breakdown by blocks of {title(d)}", "pause": True},
                   rows_turn(S, S, head, "block", d)], d)
    d = D[9]
    add("K9", [rows_turn(f"okay so um {S} {m1} by district please", S, m1, "district", place="-"),
               rows_turn(f"okay, now could you break down {title(d)} by the blocks for the same", S, m1, "block", d),
               rows_turn("um which block is having the lowest", S, m1, "block", d, take=1, order="ASC"),
               view_turn("in a line graph", "line")], d)
    d = D[10]
    add("K10", [rows_turn(q1, S, m1, "district", place="-"),
                rows_turn(f"show me {title(d)} block-wise", S, m1, "block", d),
                rows_turn("top 3", S, m1, "block", d, take=3),
                view_turn("on the map", "map")], d)
    d = D[11]
    add("K11", [rows_turn(f"{S} {m1} by block in {title(d)}", S, m1, "block", d),
                rows_turn("which block has the most", S, m1, "block", d, take=1),
                view_turn("give me this as a pie chart", "pie")], d)
    return out


async def build() -> int:
    import yaml
    from app import db
    blocks = {}
    for (scheme, measure) in MEASURES:
        for d in DISTRICTS:
            rows = await db.fetch_rows_readonly(truth_sql(scheme, measure, "block", d))
            blocks[f"{scheme}|{measure}|{d}"] = [list(r.values())[0] for r in rows if list(r.values())[1] not in (None, 0)]
    yblocks = {}
    for S, M, Y in ONESHOT + [("MGNREGA", "expenditure", 2023)]:
        view, expr, base, bcol, _u = MEASURES[(S, M)]
        rows = await db.fetch_rows_readonly(
            f"SELECT lgd_district, {bcol}, {expr} FROM {view} WHERE {base} AND year_key = {Y} AND {bcol} IS NOT NULL "
            f"AND lgd_district IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2")
        yblocks[(S, M, Y)] = [(list(r.values())[0], list(r.values())[1]) for r in rows
                              if list(r.values())[2] not in (None, 0)]
    cases = []
    for i, scheme in enumerate(SCHEMES):
        per = {(m, d): blocks.get(f"{scheme}|{m}|{d}", []) for (s, m) in MEASURES if s == scheme for d in DISTRICTS}
        cases += chains_for(scheme, i, per)
    cases += oneshot_chains(yblocks) + vague_chains(blocks) + logged_chains()
    with open(BANK, "w", encoding="utf-8") as fh:
        yaml.safe_dump({"built": time.strftime("%Y-%m-%d %H:%M"), "chains": cases}, fh, sort_keys=False,
                       allow_unicode=True, width=120)
    print(f"{len(cases)} chains, {sum(len(c['turns']) for c in cases)} turns -> {BANK}")
    return 0


# ── the engine's shaper (voice path) ─────────────────────────────────────────────────────────────────────────────
def load_shaper(nomodel: bool):
    sys.path.insert(0, os.path.join(FDX, "megh"))
    os.environ.setdefault("MEGH_DOMAIN_PACK", os.path.join(FDX, "megh", "domain", "clone_pack", "megh_pack.json"))
    if nomodel:
        os.environ["FDX_LLM_URL"] = STUB
    else:
        for f in (os.path.join(FDX, "gateway_models.env"), os.path.join(FDX, "run", "models.env")):
            try:
                for row in open(f, encoding="utf-8").read().splitlines():
                    k, _, v = row.partition("=")
                    k = k.strip()
                    if k in ("FDX_LLM_URL", "FDX_LLM_MODEL", "FDX_LLM_KEY", "FDX_LLM_INSECURE") and v.strip() \
                            and not os.environ.get(k):
                        os.environ[k] = v.strip().strip('"')
            except OSError:
                pass
    import shaper  # noqa: E402
    return shaper


FRAME_KEYS = ["schemes", "qtype", "group", "order", "limit", "all_years", "measure_text", "split"]
FILTER_KEYS = ["district", "block", "assembly_constituency", "year_key", "district_list", "block_list", "year_key_list"]


def asked_of(raw: dict, question: str) -> tuple[str, dict | None]:
    """voiceSpeech.askedOf: what the page sends the engine with a spoken answer."""
    asked = (raw.get("rewritten_question") or raw.get("translated_question") or question or "").strip()[:400]
    f = raw.get("answer_frame")
    frame = None
    if isinstance(f, dict):
        frame = {k: f[k] for k in FRAME_KEYS if f.get(k) not in (None, "")}
        src = f.get("filters") if isinstance(f.get("filters"), dict) else {}
        filt = {k: src[k] for k in FILTER_KEYS if src.get(k) not in (None, "")}
        if filt:
            frame["filters"] = filt
        frame = frame or None
    return asked, frame


# ── running ───
_SPY = {"on": False}


def conversation_class(rg):
    """run_gold's superadmin conversation; the ask-back's options as the UI gets them (label + the question a tap
    sends) are kept on the conversation's own session, so a TYPED pick is a chip tap (concurrent chains never mix)."""
    from app.routers import query as router
    if not _SPY["on"]:
        keep = router.remember_pause

        def spy(session, q, e):
            try:
                session._perms_options = [o for o in (getattr(e, "options", None) or []) if isinstance(o, dict)]
            except Exception:  # noqa: BLE001
                pass
            return keep(session, q, e)
        router.remember_pause = spy
        _SPY["on"] = True

    class PermsConversation(rg.SuperadminConversation):
        @property
        def last_options(self) -> list:
            return list(getattr(self.session, "_perms_options", None) or [])
    return PermsConversation


# ────────────────────────────────────────────────────────────────────────────────────────────────────
async def run_chain(chain, path, d, scope, sem, shaper, views, rg):
    import copy
    chain = copy.deepcopy(chain)                  # the voice and typed runs of one chain never share truth values
    async with sem:
        conv = conversation_class(rg)(d.store, scope)
        mem = shaper.Memory() if path == "voice" else None
        out, last_data = [], False

        async def ask(q):
            t0 = time.perf_counter()
            try:
                return await asyncio.wait_for(conv._ask(q, t0), rg.TURN_TIMEOUT)
            except asyncio.TimeoutError:
                return rg.TurnRecord(say=q, route="error", answer="timeout", ms=0)

        def remember(said, sent, rec):
            if mem is None:
                return
            mem.asked(sent, said)
            if rec.route == "pause":
                # the options as the engine reads them from the spoken ask-back (natural.options_of: names, no notes)
                opts = [str(o).split(" (")[0].strip() for o in (rec.chips or [])]
                speak = (rec.answer or "") + (" The options are " + ", ".join(opts[:-1]) + " or " + opts[-1] + "."
                                              if len(opts) > 1 else "")
                mem.answered(speak, "clarification", opts)
            else:
                raw = rec.raw or {}
                asked, frame = asked_of(raw, sent)
                speak = raw.get("spoken") or rec.answer or ""
                mem.answered(speak, rec.route or "answer", [], asked_as=asked, frame=frame)

        last_chips: list = []
        for i, turn in enumerate(chain["turns"]):
            said = (turn.get("voice_q") or turn["q"]) if path == "voice" else turn["q"]
            if turn.get("pick"):
                # the reply to the ask-back: typed = the chip that names it (as a tap), voice = said
                if path == "typed":
                    tap = next((o for o in conv.last_options if turn["pick"].lower() in str(o.get("label")).lower()), None)
                    said = (tap.get("question") or tap.get("label")) if tap else turn["pick"]
                else:
                    said = turn["pick"] if turn["pick"] != "block" else "the block one"
            entry = {"q": said}
            sent, how = said, "typed"
            if path == "voice":
                sh = await shaper.shape(said, mem)
                if sh["action"] != "send":
                    entry.update(ok=False, fails=[f"[voice] held ({sh['how']})"], sent=None, how=sh["how"])
                    out.append(entry)
                    break
                sent, how = sh["question"], sh["how"]
            entry.update(sent=sent, how=how)
            if "nav" in turn:
                if path == "voice":
                    ok = how == "nav" and sent == turn["nav"]
                    entry.update(ok=ok, fails=[] if ok else [f"[nav] voice: {sent!r} ({how})"])
                    if mem is not None:
                        mem.asked(sent, said)
                        mem.answered("Here's the dashboard, sir.", "note", [])
                else:
                    rec = await ask(sent)
                    raw = rec.raw or {}
                    ok = raw.get("edge_type") == "ui_command" or rec.route == "ui_command"
                    entry.update(ok=ok, route=rec.route, answer=(rec.answer or "")[:300],
                                 fails=[] if ok else [f"[nav] typed: route {rec.route} edge {raw.get('edge_type')}"])
                out.append(entry)
                if not entry["ok"]:
                    break
                continue
            if "view" in turn:
                got = (views.get(sent) or {}).get("voice" if path == "voice" else "typed")
                want = turn["view"]
                if path == "typed" and want == "map":
                    # the map exists only on the voice stage; typed, it is a server question (graded as n/a)
                    entry.update(ok=True, na=True, local=got)
                elif got == want or (want == "pie" and got in ("pie", "doughnut")):
                    entry.update(ok=True, local=got)
                    if mem is not None:
                        mem.asked(sent, said)
                        mem.answered(f"Here it is as {want}.", "note", [])
                else:
                    entry.update(ok=False, local=got, fails=[f"[view] {path}: {sent!r} -> {got} (want {want})"])
                out.append(entry)
                if not entry["ok"]:
                    break
                continue
            for k in ("rows", "figures"):
                for r in turn.get(k) or []:
                    r.pop("live", None)
            await rg.live_truth(turn)
            rec = await ask(sent)
            remember(said, sent, rec)
            if rec.route == "pause":
                last_chips = list(rec.chips or [])
            # D-099: a new chat asks which CM Elevate dataset; the officer taps / says the one the chain is about
            if rec.route == "pause" and rec.pause_rule == "cm-elevate-dataset" and turn.get("pause") is False:
                pick = "CM Elevate Legacy" if chain["scheme"] == "CM Elevate Legacy" else "CM Elevate"
                psent = pick
                if path == "voice":
                    psh = await shaper.shape(pick, mem)
                    psent = psh["question"]
                rec = await ask(psent)
                remember(pick, psent, rec)
                entry["dataset_pick"] = psent
            v = rg.judge_turn(turn, rec, i)
            raw = rec.raw or {}
            entry.update(ok=v["ok"], fails=v.get("fails", []), route=rec.route, answer=(rec.answer or "")[:600],
                         chips=list(rec.chips or [])[:10],
                         rewritten=raw.get("rewritten_question"), sql=(raw.get("sql_query") or raw.get("sql") or "")[:600],
                         truth=[(r.get("live") or [])[:6] for r in turn.get("rows") or []]
                         + [f.get("live") for f in turn.get("figures") or []])
            out.append(entry)
            last_data = bool(raw.get("data")) or last_data
            if not v["ok"]:
                break
        ok = len(out) == len(chain["turns"]) and all(t.get("ok") for t in out)
        res = {"id": chain["id"], "kind": chain["kind"], "scheme": chain["scheme"], "path": path, "ok": ok, "turns": out}
        bad = [f"t{i + 1} {t['q']!r} sent {t.get('sent')!r} ({t.get('how')}): " + "; ".join(t.get("fails") or [])
               for i, t in enumerate(out) if not t.get("ok")]
        print(f"{'PASS' if ok else 'FAIL'} {path:<5} {chain['id']:<34}" + ("" if ok else "  " + " || ".join(bad)[:500]),
              flush=True)
        return res


def view_map(sentences) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(sorted(set(sentences)), fh)
        tmp = fh.name
    try:
        out = subprocess.run(["node", os.path.join(HERE, "perms_views.mjs"), tmp], capture_output=True, text=True,
                             encoding="utf-8", timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return json.loads(out.stdout or "{}")
    finally:
        os.unlink(tmp)


def matrix(results) -> str:
    kinds = sorted({r["kind"] for r in results}, key=lambda k: int(k[1:]))
    kinds = [k for k in kinds if k not in ("K12", "K13")]
    schemes = list(SCHEMES)
    cell = {}
    for r in results:
        cell.setdefault((r["kind"], r["scheme"]), {})[r["path"]] = r["ok"]
    lines = ["kind  " + " | ".join(f"{s[:12]:<12}" for s in schemes)]
    for k in kinds:
        row = []
        for s in schemes:
            c = cell.get((k, s))
            if not c:
                row.append(f"{'-':<12}")
                continue
            v = "V" + ("ok" if c.get("voice") else "X" if "voice" in c else "-")
            t = "T" + ("ok" if c.get("typed") else "X" if "typed" in c else "-")
            row.append(f"{v + ' ' + t:<12}")
        lines.append(f"{k:<5} " + " | ".join(row))
    for k in ("K12", "K13"):
        for p in ("voice", "typed"):
            rs = [r for r in results if r["kind"] == k and r["path"] == p]
            if rs:
                lines.append(f"{k} one-shot (every block) {p}: {sum(r['ok'] for r in rs)}/{len(rs)}")
    for p in ("voice", "typed"):
        rs = [r for r in results if r["path"] == p]
        if rs:
            lines.append(f"{p}: {sum(r['ok'] for r in rs)}/{len(rs)} chains")
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--label", default="perms")
    ap.add_argument("--paths", default="voice,typed")
    ap.add_argument("--only", help="comma list of chain kinds (K1..K11) or chain ids")
    ap.add_argument("--schemes", help="comma list of schemes")
    ap.add_argument("--failed", help="a results JSON: re-run only its failed (chain, path)")
    ap.add_argument("--nomodel", action="store_true", help="every model endpoint = the 503 stub on 127.0.0.1:8409")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    if args.nomodel:
        for k in MODEL_URL_KEYS:
            os.environ[k] = STUB
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    sys.path.insert(0, HERE)
    if args.build:
        return await build()
    import yaml
    import run_gold as rg  # noqa: E402
    shaper = load_shaper(args.nomodel)
    with open(BANK, encoding="utf-8") as fh:
        chains = yaml.safe_load(fh)["chains"]
    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
        chains = [c for c in chains if c["kind"] in keys or c["id"] in keys]
    if args.schemes:
        keep = [s.strip() for s in args.schemes.split(",")]
        chains = [c for c in chains if c["scheme"] in keep]
    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    jobs = [(c, p) for c in chains for p in paths]
    if args.failed:
        prev = json.load(open(args.failed, encoding="utf-8"))
        bad = {(r["id"], r["path"]) for r in prev["results"] if not r["ok"]}
        jobs = [(c, p) for c, p in jobs if (c["id"], p) in bad]
    # every sentence the page may have to read as a view: the said words and the shaper's canonical sentences
    views = view_map([t["q"] for c in chains for t in c["turns"]]
                     + ["show it as a bar chart", "show it as a line chart", "show it as a pie chart", "show it as a table",
                        "show it on the map", "show it as a ranking", "show it as horizontal bars"])
    print(f"{len(jobs)} chain runs ({', '.join(paths)}), model {'DOWN' if args.nomodel else 'on'}", flush=True)
    t0 = time.perf_counter()
    async with rg.InProcessDriver() as d:
        scope = await rg.superadmin_scope()
        sem = asyncio.Semaphore(max(1, min(args.concurrency, 6)))
        results = await asyncio.gather(*(run_chain(c, p, d, scope, sem, shaper, views, rg) for c, p in jobs))
    text = matrix(results)
    print("\n" + text)
    os.makedirs(RESULTS, exist_ok=True)
    path = os.path.join(RESULTS, f"{time.strftime('%Y-%m-%d_%H%M')}_{args.label}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"label": args.label, "seconds": round(time.perf_counter() - t0), "nomodel": args.nomodel,
                   "matrix": text, "results": results}, fh, ensure_ascii=False, indent=1, default=str)
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed in {time.perf_counter() - t0:.0f} s -> {path}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
