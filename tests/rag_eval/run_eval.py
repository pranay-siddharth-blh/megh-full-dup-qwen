"""
Scores the RAG (knowledge) path against testset.json — RAG upgrade, Phase 1
(2026-10-14). Run it before and after every RAG change; keep a change only
when the score improves.

For every question it runs exactly what the chat runs for a knowledge turn
(rag.retrieve + rag.answer_from_kb, scoped to the question's scheme) and
measures:

  retrieval   hit@1 / hit@3 / hit@all — is a piece containing the evidence
              quote among the pieces handed to the composer, and how high;
              MRR (1/rank, 0 when missing).
  answer      a judge model compares the answer with the expected answer:
              correct / partial / wrong; "refused" when RAG gave no answer.
  negatives   "not covered" questions: right when RAG refuses or says the
              detail is not published.
  made up     a judge lists sentences of the answer that the retrieved pieces
              do not support; any one makes the answer "made up".

The judge is the gateway's response model at temperature 0, so scores move a
little between runs (about +/-2 points); compare runs, not single answers.

    python tests/rag_eval/run_eval.py --label baseline
    python tests/rag_eval/run_eval.py --label v2 --collection megh_scheme_kb_v2
    python tests/rag_eval/run_eval.py --export-testset      # Excel for SME review
"""
import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TESTSET = HERE / "testset.json"
RESULTS = HERE / "results"
REPORTS = ROOT / "reference_documents"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="run", help="name for this run (e.g. baseline, phase3)")
    ap.add_argument("--collection", help="Qdrant collection to evaluate (default: QDRANT_COLLECTION)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions")
    ap.add_argument("--kind", choices=["doc", "real", "negative"], help="only this kind")
    ap.add_argument("--scheme", help="only this scheme")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--retrieval-only", action="store_true",
                    help="only the search measures (no answers, no judge): fast, for tuning search")
    ap.add_argument("--export-testset", action="store_true",
                    help="write reference_documents/rag_test_set.xlsx for SME review and exit")
    return ap.parse_args()


ARGS = parse_args()
if ARGS.collection:  # before app.config is imported, so settings picks it up
    os.environ["QDRANT_COLLECTION"] = ARGS.collection
sys.path.insert(0, str(ROOT))

from app import llm, rag, vectorstore  # noqa: E402
from app.config import settings  # noqa: E402
from tests._text_checks import has_phrase  # noqa: E402
from tests.rag_eval.build_testset import norm, parse_json  # noqa: E402


# ── judge ───────────────────────────────────────────────────────────────────

async def judge(prompt: str, schema: dict, max_tokens: int = 400) -> dict:
    for attempt in range(3):
        try:
            raw = await llm.call_model(
                base_url=settings.RESPONSE_MODEL_BASE_URL, model=settings.RESPONSE_MODEL,
                api_key=settings.RESPONSE_MODEL_API_KEY, prompt=prompt, temperature=0.0,
                max_tokens=max_tokens, timeout=120, role="rag_eval_judge",
                guided={"guided_json": schema} if settings.GUIDED_DECODING_ENABLED else None)
            return parse_json(raw) or {}
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                return {"error": f"{type(e).__name__}: {str(e)[:100]}"}
            await asyncio.sleep(2 + attempt * 3)
    return {}


VERDICT_SCHEMA = {"type": "object", "properties": {
    "verdict": {"type": "string", "enum": ["correct", "partial", "wrong"]}, "why": {"type": "string"}},
    "required": ["verdict", "why"]}
SUPPORT_SCHEMA = {"type": "object", "properties": {
    "unsupported": {"type": "array", "items": {"type": "string"}}}, "required": ["unsupported"]}
NEG_SCHEMA = {"type": "object", "properties": {
    "says_not_available": {"type": "boolean"}, "why": {"type": "string"}},
    "required": ["says_not_available", "why"]}


async def judge_answer(q: str, expected: str, answer: str) -> dict:
    return await judge(f"""You grade a government-scheme helpdesk chatbot.

Question: "{q}"
Reference answer (correct): "{expected}"
Chatbot answer:
<<<
{answer}
>>>

Grade the chatbot answer against the reference answer:
- "correct": gives the key facts of the reference answer, nothing contradicting it (extra correct detail is fine)
- "partial": some key facts right but an important part missing or vague
- "wrong": misses the point, contradicts the reference, or answers a different question
Reply as JSON: {{"verdict": "correct|partial|wrong", "why": "one short reason"}}""", VERDICT_SCHEMA)


UNITS_SCHEMA = {"type": "object", "properties": {
    "unsupported": {"type": "array", "items": {"type": "integer"}}}, "required": ["unsupported"]}


async def judge_support(answer: str, passages: list[str]) -> tuple[list[str], int]:
    """(unsupported sentences, number of sentences). The answer is cut into
    numbered sentences exactly as the app's sentence check cuts it
    (rag.split_units) and the judge marks the ones the passages do not support.
    Judging numbered sentences instead of listing "claims" in its own words made
    the made-up measure steadier (Phase 5, 2026-10-15: the old list swung by
    +/-6 points between runs of the same answers). The judge's wording is its
    own, not the app check's."""
    units = rag.split_units(answer)
    if not units:
        return [], 0
    ctx = "\n\n---\n\n".join(p[:2500] for p in passages[:8])
    numbered = "\n".join(f"[{i}] {u}" for i, (_, u) in enumerate(units))
    r = await judge(f"""You check a government-scheme chatbot's answer against the passages it was given.

Passages:
<<<
{ctx}
>>>

The chatbot's answer, one numbered sentence per line:
{numbered}

Which sentences contain a SPECIFIC FACT (number, percentage, amount, date, name, document, rule,
eligibility condition or step) that the passages do not state or clearly imply?
Never count: advice on where to confirm, ask or apply (Block office, Gram Panchayat, portal,
helpline); a line that only introduces a list; rewording or summarising what the passages say;
a sentence saying something is not published.
Reply as JSON: {{"unsupported": [sentence numbers]}}""", UNITS_SCHEMA, max_tokens=200)
    idx = sorted({int(i) for i in (r.get("unsupported") or [])
                  if isinstance(i, (int, float)) and 0 <= int(i) < len(units)})
    bad = [units[i][1] for i in idx if not has_phrase(units[i][1], *_ADVICE, bounded=True)]
    return bad, len(units)


def echo_filter(question: str, claims: list[str]) -> list[str]:
    """Drop "claims" that only repeat the officer's own words (a district, an
    amount or the scheme named in the question): repeating the question is not
    inventing a fact."""
    qn = norm(question)
    return [c for c in claims if norm(c) not in qn]


# Safety net for the judge: a "claim" that is only advice on where to confirm
# or ask is never a made-up fact (baseline 2026-10-14 flagged dozens of these).
_ADVICE = ("block office", "gram panchayat", "panchayat office", "portal", "helpline", "confirm", "check with",
           "contact", "visit", "enquire", "inquire", "reach out")      # whole words, any case


async def judge_negative(q: str, answer: str) -> dict:
    return await judge(f"""A helpdesk chatbot was asked a question its documents do not answer.

Question: "{q}"
Chatbot answer:
<<<
{answer}
>>>

Does the chatbot make clear that this specific information is not available / not published (it may
add general guidance or where to ask), instead of giving a specific answer as if it knew?
Reply as JSON: {{"says_not_available": true|false, "why": "one short reason"}}""", NEG_SCHEMA)


# ── one question ────────────────────────────────────────────────────────────

async def run_item(it: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        q, scheme = it["question"], it["scheme"]
        t0 = time.perf_counter()
        chunks = await rag.retrieve(q, scheme=scheme)
        t_ret = time.perf_counter() - t0
        rank = 0
        if it.get("evidence"):
            ev = norm(it["evidence"])
            for i, c in enumerate(chunks, 1):
                if ev in norm(c.get("text", "")):
                    rank = i
                    break
        if ARGS.retrieval_only:
            return {**it, "rank": rank, "n_chunks": len(chunks), "answer": "", "refused": False,
                    "verdict": "-", "why": "", "unsupported": [], "made_up": False, "confidence": "-",
                    "top_score": round(float(chunks[0]["score"]), 3) if chunks else 0.0,
                    "retrieve_s": round(t_ret, 2), "answer_s": 0.0}
        t1 = time.perf_counter()
        kb = await rag.answer_from_kb(q, scheme=scheme)
        t_ans = time.perf_counter() - t1
        answer = (kb or {}).get("answer", "") if kb else ""
        res = {**it, "rank": rank, "n_chunks": len(chunks),
               "top_score": round(float(chunks[0]["score"]), 3) if chunks else 0.0,
               "confidence": (kb or {}).get("confidence", "none"), "answer": answer,
               "refused": kb is None, "retrieve_s": round(t_ret, 2), "answer_s": round(t_ans, 2)}

        if it["kind"] == "negative":
            if kb is None:
                res.update(verdict="correct", why="refused (not covered)")
            else:
                j = await judge_negative(q, answer)
                ok = bool(j.get("says_not_available"))
                res.update(verdict="correct" if ok else "wrong", why=j.get("why", j.get("error", "")))
        elif kb is None:
            res.update(verdict="refused", why="RAG gave no answer")
        else:
            j = await judge_answer(q, it["expected_answer"], answer)
            res.update(verdict=j.get("verdict", "wrong"), why=j.get("why", j.get("error", "")))

        res["unsupported"], res["n_units"] = [], 0
        if kb is not None:
            bad, n_units = await judge_support(answer, [c.get("text", "") for c in chunks])
            res["unsupported"], res["n_units"] = echo_filter(q, bad), n_units
        res["made_up"] = bool(res["unsupported"])
        return res


# ── scoring ─────────────────────────────────────────────────────────────────

def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def score(rows: list[dict]) -> dict:
    pos = [r for r in rows if r["kind"] != "negative"]
    neg = [r for r in rows if r["kind"] == "negative"]
    answered = [r for r in rows if not r["refused"]]
    v = lambda rs, x: sum(1 for r in rs if r["verdict"] == x)  # noqa: E731
    return {
        "questions": len(rows), "answerable": len(pos), "not_covered": len(neg),
        "hit@1": pct(sum(1 for r in pos if r["rank"] == 1), len(pos)),
        "hit@3": pct(sum(1 for r in pos if 1 <= r["rank"] <= 3), len(pos)),
        "hit@all": pct(sum(1 for r in pos if r["rank"] >= 1), len(pos)),
        "mrr": round(sum(1.0 / r["rank"] for r in pos if r["rank"]) / len(pos), 3) if pos else None,
        "correct": pct(v(pos, "correct"), len(pos)),
        "correct+half_partial": pct(v(pos, "correct") + 0.5 * v(pos, "partial"), len(pos)),
        "partial": pct(v(pos, "partial"), len(pos)),
        "wrong": pct(v(pos, "wrong"), len(pos)),
        "refused_wrongly": pct(v(pos, "refused"), len(pos)),
        "not_covered_handled": pct(v(neg, "correct"), len(neg)),
        "made_up": pct(sum(1 for r in answered if r["made_up"]), len(answered)),
        "made_up_sentences": pct(sum(len(r["unsupported"]) for r in answered),
                                 sum(r.get("n_units", 0) for r in answered)),
        "correct_or_honest": pct(v(pos, "correct") + v(neg, "correct"), len(rows)),
        "avg_seconds": round(sum(r["retrieve_s"] + r["answer_s"] for r in rows) / len(rows), 2) if rows else None,
    }


LABELS = [
    ("hit@1", "Right piece ranked 1st (%)"), ("hit@3", "Right piece in top 3 (%)"),
    ("hit@all", "Right piece found at all (%)"), ("mrr", "MRR (0-1)"),
    ("correct", "Correct answers (%)"), ("partial", "Partly correct (%)"), ("wrong", "Wrong (%)"),
    ("refused_wrongly", "Said 'not covered' but it was (%)"),
    ("not_covered_handled", "'Not covered' questions handled honestly (%)"),
    ("made_up", "Answers with a made-up sentence (%)"),
    ("made_up_sentences", "Sentences that are made up (%)"),
    ("correct_or_honest", "OVERALL: correct or honest (%)"), ("avg_seconds", "Avg seconds per question"),
]


def print_summary(label: str, overall: dict, per: dict) -> None:
    print(f"\n=== RAG eval: {label}  ({overall['questions']} questions, collection {settings.QDRANT_COLLECTION})")
    w = max(len(s) for s in per) if per else 8
    print(f"{'':44}{'ALL':>8}" + "".join(f"{s[:w]:>{w + 2}}" for s in per))
    for k, name in LABELS:
        vals = "".join(f"{('-' if per[s][k] is None else per[s][k]):>{w + 2}}" for s in per)
        print(f"{name:44}{('-' if overall[k] is None else overall[k]):>8}{vals}")


# ── Excel ───────────────────────────────────────────────────────────────────

def _sheet(wb, title, header, rows, widths):
    from openpyxl.styles import Alignment, Font, PatternFill
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="5B2C8F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=True)
    ws.freeze_panes = "B2"
    return ws


def write_report(label: str, rows: list[dict], overall: dict, per: dict) -> Path:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    schemes = list(per)
    _sheet(wb, "Summary", ["Measure", "ALL", *schemes],
           [[name, overall[k], *[per[s][k] for s in schemes]] for k, name in LABELS]
           + [[], ["Run", label], ["Collection", settings.QDRANT_COLLECTION],
              ["Date", dt.datetime.now().strftime("%Y-%m-%d %H:%M")], ["Questions", overall["questions"]]],
           [46, 10] + [14] * len(schemes))
    _sheet(wb, "Questions",
           ["ID", "Kind", "Scheme", "Question", "Expected answer", "Bot answer", "Verdict", "Judge reason",
            "Right piece rank (0 = not found)", "Top score", "Confidence", "Made-up claims", "Seconds"],
           [[r["id"], r["kind"], r["scheme"], r["question"], r.get("expected_answer", ""), r["answer"] or "(refused)",
             r["verdict"], r.get("why", ""), r["rank"], r["top_score"], r["confidence"],
             "\n".join(r["unsupported"]), round(r["retrieve_s"] + r["answer_s"], 1)] for r in rows],
           [7, 9, 12, 40, 45, 55, 10, 35, 12, 9, 11, 40, 8])
    path = REPORTS / f"RAG_Eval_{dt.date.today().isoformat()}_{label}.xlsx"
    wb.save(path)
    return path


def export_testset() -> Path:
    from openpyxl import Workbook
    items = json.loads(TESTSET.read_text(encoding="utf-8"))
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, "Test set",
           ["ID", "Kind", "Scheme", "Question", "Expected answer", "Evidence (exact quote from the document)",
            "Document", "Section", "SME check (OK / FIX / DROP)", "SME correction or comment"],
           [[i["id"], i["kind"], i["scheme"], i["question"], i["expected_answer"], i.get("evidence", ""),
             i.get("gold_doc", ""), i.get("gold_heading", ""), "", ""] for i in items],
           [7, 9, 12, 45, 55, 45, 30, 30, 14, 40])
    path = REPORTS / "rag_test_set.xlsx"
    wb.save(path)
    return path


# ── main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    if ARGS.export_testset:
        print("wrote", export_testset())
        return
    items = json.loads(TESTSET.read_text(encoding="utf-8"))
    if ARGS.kind:
        items = [i for i in items if i["kind"] == ARGS.kind]
    if ARGS.scheme:
        items = [i for i in items if i["scheme"] == ARGS.scheme]
    if ARGS.limit:
        items = items[: ARGS.limit]
    await llm.init_client()
    await vectorstore.init_qdrant()
    try:
        sem = asyncio.Semaphore(ARGS.concurrency)
        rows, done = [], 0

        async def one(it):
            nonlocal done
            r = await run_item(it, sem)
            done += 1
            if done % 20 == 0 or done == len(items):
                print(f"  {done}/{len(items)}", flush=True)
            return r

        rows = await asyncio.gather(*(one(it) for it in items))
    finally:
        await vectorstore.close_qdrant()
        await llm.close_client()

    rows.sort(key=lambda r: r["id"])
    by = defaultdict(list)
    for r in rows:
        by[r["scheme"]].append(r)
    per = {s: score(by[s]) for s in sorted(by)}
    overall = score(rows)
    print_summary(ARGS.label, overall, per)
    # Questions a subject expert has checked (sme_review.py import): their
    # score is the trustworthy one — the rest are judged against model-written
    # expected answers.
    checked = [r for r in rows if r.get("reviewed")]
    expert = score(checked) if checked else None
    if expert:
        print(f"\nEXPERT-CHECKED ({len(checked)} of {len(rows)} questions): "
              f"correct {expert['correct']}%, correct or honest {expert['correct_or_honest']}%, "
              f"'not covered' handled {expert['not_covered_handled']}%")
    else:
        print("\n(no expert-checked questions yet — see tests/rag_eval/sme_review.py)")
    if ARGS.retrieval_only:
        print("(retrieval only: answer measures not run)")
        return
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{dt.date.today().isoformat()}_{ARGS.label}.json"
    out.write_text(json.dumps({"label": ARGS.label, "collection": settings.QDRANT_COLLECTION,
                               "overall": overall, "per_scheme": per, "expert_checked": expert, "rows": rows},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nresults:", out)
    print("report: ", write_report(ARGS.label, rows, overall, per))


if __name__ == "__main__":
    asyncio.run(main())
