"""
Live answer streaming (app/response/answer_stream.py) through the real
composer paths: pipeline.compose_response, rag.answer_from_kb /
answer_from_kb_multi, and the central "replace" in pipeline.answer_question.

Only the model calls themselves are mocked (llm.call_response_composer and
llm.stream_response_composer), so the real prompt building, numeric-
faithfulness guard, strict retry, hedge fallback and answer formatting all
run. The invariant checked throughout: whatever sequence of "token" /
"replace" events the client received, the text it ends up showing equals the
answer the pipeline returns. No DB, no model gateway.
Run: `python tests/unit/test_answer_stream.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

import httpx  # noqa: E402

from app.clients import llm  # noqa: E402
from app.knowledge import rag  # noqa: E402
from app.orchestration import pipeline  # noqa: E402
from app.response import answer_stream  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


_orig_call = llm.call_response_composer
_orig_stream = llm.stream_response_composer


class Recorder:
    """An on_event sink that replays events into what a client would show."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []
        self.shown = ""

    async def __call__(self, kind: str, data: dict) -> None:
        self.events.append((kind, data))
        if kind == "token":
            self.shown += data["t"]
        elif kind == "replace":
            self.shown = data["answer"]

    def kinds(self) -> list[str]:
        return [k for k, _ in self.events]


def mock_models(stream_chunks=None, stream_error=None, call_answers=None):
    """Patch both composer entry points; returns a dict of call counts."""
    calls = {"stream": 0, "call": 0, "prompts": []}
    answers = list(call_answers or [])

    async def fake_stream(prompt):
        calls["stream"] += 1
        for c in stream_chunks or []:
            yield c
        if stream_error is not None:
            raise stream_error

    async def fake_call(prompt):
        calls["call"] += 1
        calls["prompts"].append(prompt)
        return answers.pop(0) if answers else "UNEXPECTED"

    llm.stream_response_composer = fake_stream
    llm.call_response_composer = fake_call
    return calls


def restore():
    llm.stream_response_composer = _orig_stream
    llm.call_response_composer = _orig_call


async def compose(rows, on_event):
    with answer_stream.bind(on_event):
        return await pipeline.compose_response("how many houses?", "SELECT 1", rows)


ONE_ROW = [{"houses_completed": 170981}]

try:
    # ── 1. no sink: exactly the old non-streaming call ──────────────────────
    print("1. NO on_event — UNCHANGED NON-STREAMING PATH")
    calls = mock_models(call_answers=["**170,981** houses were completed."])
    out = asyncio.run(compose(ONE_ROW, None))
    check("call_response_composer used once", calls["call"] == 1, str(calls))
    check("stream_response_composer never used", calls["stream"] == 0, str(calls))
    check("answer carries the figure", "170,981" in out, out)

    # ── 2. faithful streamed answer ─────────────────────────────────────────
    print("2. FAITHFUL ANSWER STREAMS AS TOKENS")
    calls = mock_models(stream_chunks=["**170,981** ", "houses were ", "completed."])
    rec = Recorder()
    out = asyncio.run(compose(ONE_ROW, rec))
    check("three token events, in order",
          [d["t"] for k, d in rec.events if k == "token"] == ["**170,981** ", "houses were ", "completed."],
          str(rec.events))
    check("no non-streaming call when the answer passes every check", calls["call"] == 0, str(calls))
    check("client ends up showing exactly the returned answer", rec.shown == out, f"{rec.shown!r} vs {out!r}")
    check("at most one replace (formatting only)", rec.kinds().count("replace") <= 1, str(rec.kinds()))

    # ── 3. misquoted number -> strict retry (non-streaming) -> replace ────────
    print("3. MISQUOTE -> STRICT RETRY STAYS NON-STREAMING, THEN REPLACE")
    calls = mock_models(stream_chunks=["**17,098** houses."],
                        call_answers=["**170,981** houses were completed."])
    rec = Recorder()
    out = asyncio.run(compose(ONE_ROW, rec))
    check("streamed once, strict retry via call_response_composer",
          calls["stream"] == 1 and calls["call"] == 1, str(calls))
    check("strict retry prompt carries the bad answer", "17,098" in calls["prompts"][0])
    check("final answer is the corrected one", "170,981" in out and "17,098" not in out, out)
    check("a replace event was sent", "replace" in rec.kinds(), str(rec.kinds()))
    check("client ends up showing the corrected answer", rec.shown == out, f"{rec.shown!r} vs {out!r}")

    # ── 4. still wrong after retry -> deterministic fallback -> replace ───────
    print("4. RETRY STILL WRONG -> DETERMINISTIC ANSWER REPLACES THE STREAM")
    calls = mock_models(stream_chunks=["**17,098** houses."], call_answers=["About 99,999 houses."])
    rec = Recorder()
    out = asyncio.run(compose(ONE_ROW, rec))
    # The deterministic sentence uses Indian digit grouping ("1,70,981").
    check("deterministic answer returned",
          "170981" in out.replace(",", "") and "99999" not in out.replace(",", ""), out)
    check("client ends up showing it", rec.shown == out, f"{rec.shown!r} vs {out!r}")

    # ── 5. hedge over a real value -> deterministic fallback -> replace ───────
    print("5. HEDGE OVER A REAL VALUE -> DETERMINISTIC REPLACE")
    calls = mock_models(stream_chunks=["That figure is ", "not available."])
    rec = Recorder()
    out = asyncio.run(compose(ONE_ROW, rec))
    check("hedge discarded for the real figure",
          "170981" in out.replace(",", "") and "not available" not in out, out)
    check("client ends up showing it", rec.shown == out, f"{rec.shown!r} vs {out!r}")

    # ── 6. stream breaks partway -> non-streaming fallback -> replace ─────────
    print("6. STREAM FAILS PARTWAY -> NON-STREAMING FALLBACK")
    calls = mock_models(stream_chunks=["**170,"], stream_error=httpx.ReadError("boom"),
                        call_answers=["**170,981** houses were completed."])
    rec = Recorder()
    out = asyncio.run(compose(ONE_ROW, rec))
    check("fallback call made", calls["call"] == 1, str(calls))
    check("partial token was sent before the failure", rec.events[0] == ("token", {"t": "**170,"}),
          str(rec.events[:2]))
    check("a replace followed the failure", "replace" in rec.kinds(), str(rec.kinds()))
    check("client ends up showing the full answer", rec.shown == out, f"{rec.shown!r} vs {out!r}")

    # ── 7. ModelBusyError is not retried ────────────────────────────────────
    print("7. GATEWAY SATURATED -> ModelBusyError PROPAGATES, NO SECOND QUEUE")
    calls = mock_models(stream_error=llm.ModelBusyError("busy"))
    try:
        asyncio.run(compose(ONE_ROW, Recorder()))
        raised = False
    except llm.ModelBusyError:
        raised = True
    check("ModelBusyError raised", raised)
    check("no non-streaming retry", calls["call"] == 0, str(calls))

    # ── 8. a broken client callback never costs the answer ──────────────────
    print("8. BROKEN on_event CALLBACK IS NON-FATAL")
    calls = mock_models(stream_chunks=["**170,981** houses were completed."])

    def broken(kind, data):
        raise RuntimeError("client went away")
    out = asyncio.run(compose(ONE_ROW, broken))
    check("answer still produced", "170,981" in out, out)

    # ── 9. empty result: no composer, central replace carries the answer ────
    print("9. NO-DATA ANSWER (NO COMPOSER) REACHES THE CLIENT VIA answer_question")
    _orig_run = pipeline._run_pipeline

    async def fake_run(question, session=None, scope=None):
        return {"route": "edge", "answer": "Hello — ask me about MGNREGA."}
    pipeline._run_pipeline = fake_run
    try:
        rec = Recorder()
        res = asyncio.run(pipeline.answer_question("hi", on_event=rec))
        check("exactly one replace with the final answer",
              rec.events == [("replace", {"answer": "Hello — ask me about MGNREGA."})], str(rec.events))
        check("result unchanged", res["answer"] == "Hello — ask me about MGNREGA.")
        res = asyncio.run(pipeline.answer_question("hi"))
        check("without on_event: same result, no binding leaks", res["answer"] == "Hello — ask me about MGNREGA."
              and answer_stream.current() is None)

        # a streamed answer that the turn then prefixes ("Understood as…")
        async def fake_run_streamed(question, session=None, scope=None):
            ans = await pipeline.compose_response("q", "SELECT 1", ONE_ROW)
            return {"route": "data", "answer": "_Understood as: q_\n\n" + ans}
        pipeline._run_pipeline = fake_run_streamed
        mock_models(stream_chunks=["**170,981** houses were completed."])
        rec = Recorder()
        res = asyncio.run(pipeline.answer_question("q", on_event=rec))
        check("a later prefix is delivered by the central replace", rec.shown == res["answer"],
              f"{rec.shown!r} vs {res['answer']!r}")
    finally:
        pipeline._run_pipeline = _orig_run

    # ── 10. RAG: first call streamed, refusal retry non-streaming ──────────
    print("10. RAG COMPOSER STREAMS; REFUSAL RETRY STAYS NON-STREAMING")
    _orig_retrieve = rag.retrieve
    _chunk = {"text": "PMAY-G gives a pucca house to eligible rural households.",
              "doc": "pmayg.md", "heading": "Overview", "score": 0.6}

    async def fake_retrieve(question, scheme=None):
        # MGNREGA has no material, so the multi-scheme answer gets the
        # "I don't have reference material ... for MGNREGA" note appended.
        return [] if scheme == "MGNREGA" else [dict(_chunk)]
    rag.retrieve = fake_retrieve
    try:
        calls = mock_models(stream_chunks=["PMAY-G gives ", "a pucca house."])
        rec = Recorder()

        async def kb(fn, *a, **kw):
            with answer_stream.bind(rec):
                return await fn(*a, **kw)
        res = asyncio.run(kb(rag.answer_from_kb, "what is pmay-g"))
        check("answer_from_kb streamed", calls["stream"] == 1 and calls["call"] == 0, str(calls))
        check("client shows the returned answer", rec.shown == res["answer"], f"{rec.shown!r} vs {res}")

        calls = mock_models(stream_chunks=["That isn't covered in the scheme reference material."],
                            call_answers=["PMAY-G gives a pucca house."])
        rec = Recorder()
        res = asyncio.run(kb(rag.answer_from_kb, "what is pmay-g"))
        check("refusal retried via call_response_composer", calls["call"] == 1, str(calls))
        check("client shows the retried answer", res and rec.shown == res["answer"], f"{rec.shown!r} vs {res}")

        calls = mock_models(stream_chunks=["- **PMAY-G** — a pucca house."])
        rec = Recorder()
        res = asyncio.run(kb(rag.answer_from_kb_multi, "compare", ["PMAY-G", "MGNREGA"]))
        check("answer_from_kb_multi streamed", calls["stream"] == 1, str(calls))
        check("client shows the returned answer incl. the missing-scheme note",
              res and rec.shown == res["answer"] and "MGNREGA" in rec.shown, f"{rec.shown!r} vs {res}")

        calls = mock_models(call_answers=["PMAY-G gives a pucca house."])
        res = asyncio.run(rag.answer_from_kb("what is pmay-g"))
        check("RAG without on_event: non-streaming only", calls["stream"] == 0 and calls["call"] == 1, str(calls))
    finally:
        rag.retrieve = _orig_retrieve

    # ── 11. the binding reaches LangGraph nodes (node_compose's situation) ──
    print("11. BINDING IS VISIBLE INSIDE A LANGGRAPH NODE")
    from typing import TypedDict

    from langgraph.graph import END, StateGraph

    class S(TypedDict, total=False):
        seen: bool

    async def node(state):
        await answer_stream.emit(answer_stream.current(), "token", {"t": "x"})
        return {"seen": answer_stream.current() is not None}

    g = StateGraph(S)
    g.add_node("n", node)
    g.set_entry_point("n")
    g.add_edge("n", END)
    app_graph = g.compile()
    rec = Recorder()

    async def run_graph():
        with answer_stream.bind(rec):
            out = await app_graph.ainvoke({})
            return out, answer_stream.shown_text()
    out, shown = asyncio.run(run_graph())
    check("node sees the on_event binding", out.get("seen") is True, str(out))
    check("node's token reached the sink and the shared 'shown' record",
          rec.shown == "x" and shown == "x", f"{rec.shown!r} / {shown!r}")
finally:
    restore()

if _fails:
    print(f"\n{len(_fails)} FAILED")
    sys.exit(1)
print("\nALL PASS")
