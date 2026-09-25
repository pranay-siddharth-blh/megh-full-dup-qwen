"""
Understand node (app/nlu/understand.py) + its SHADOW wiring in
app/orchestration/pipeline.py::_run_pipeline.

Covers: vocabulary grounding read from the pipeline's own regexes / registry /
rule files, prompt contents (schemes, aliases, few-shots, last turns, state,
pending clarification), the context snapshot being taken before the pipeline
consumes the pending pause, the guided-JSON call contract (qwen4-deploy via
the verifier's credentials, temperature 0), field-by-field coercion, the
deterministic guard flags, never-raise behaviour, and that shadow mode changes
nothing the pipeline returns — including on a clarification pause, a slow
frame, and a cancelled request. The model is mocked; no DB, no gateway.
Run: `python tests/unit/test_understand.py`, exit code 0 = pass.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

import re  # noqa: E402

from app.api.routers import query as query_router  # noqa: E402
from app.clients import llm  # noqa: E402
from app.conversation.session_store import ConversationState, Session, Turn, session_store  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.knowledge import scheme_registry  # noqa: E402
from app.nlu import understand as u  # noqa: E402
from app.orchestration import pipeline  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


scheme_registry.load_all()

GOOD_FRAME = {
    "rewritten_question": "What is the total MGNREGA expenditure in westgaro hils?",
    "intent": "DATA", "is_followup": False, "answers_pending": False,
    "schemes": ["MGNREGA"], "metric": "total expenditure",
    "geo_mentions": [{"text": "westgaro hils", "level": None}],
    "year_text": None, "tranche": None, "query_type": "value",
    "group_by": None, "top_n": None, "unclear": None,
}


def _session(pending: str | None = None) -> Session:
    s = Session(session_id="t-understand", user_id="u", created=0.0, last_seen=0.0)
    s.turns = [Turn(question=f"q{i}", raw_question=f"raw {i}", route="data", schemes=["PMAY-G"],
                    resolved_entities={"district": "EAST KHASI HILLS"} if i == 4 else {})
               for i in range(5)]
    s.state = ConversationState(scheme="PMAY-G", district="EAST KHASI HILLS")
    if pending:
        s.state.pending_scope_q = pending
        s.state.pending_options = [{"label": "FY 2023-24", "question": pending + " for FY 2023-24"},
                                   {"label": "All financial years combined", "question": pending + " all years"}]
    return s


print("\n=== vocabulary grounding ===")
terms = u.regex_terms(re.compile(r"\b(person[\s-]?days?|job cards?|households?\s+(?:were\s+)?employed|x(?:y|z)w)\b"))
check("regex_terms turns an alternation into readable phrases",
      terms[:3] == ["person day", "job card", "household employed"], str(terms))
grounding = u.scheme_grounding()
for scheme, word in (("MGNREGA", "person day"), ("PMAY-G", "house"), ("Focus Plus", "tranch"),
                     ("CM Elevate", "piggery")):
    check(f"{scheme}: scheme-only vocabulary from pipeline regex ('{word}')", word in grounding)
check("registry aliases included (nrega, awas, focus+)",
      all(a in grounding for a in ("nrega", "awas", "focus+")))
check("classification-rule topics included", "missing time period" in grounding)

print("\n=== context snapshot + prompt ===")
sess = _session(pending="How many households got employment under MGNREGA")
ctx = u.snapshot_context(sess)
check("only the last UNDERSTAND_HISTORY_TURNS turns", len(ctx["recent_turns"]) == settings.UNDERSTAND_HISTORY_TURNS)
check("turn entities carried", ctx["recent_turns"][-1].get("entities") == {"district": "EAST KHASI HILLS"})
check("state carried", ctx["state"].get("scheme") == "PMAY-G")
check("pending question + option labels captured",
      ctx["pending"] == {"question": "How many households got employment under MGNREGA",
                         "options": ["FY 2023-24", "All financial years combined"]})
check("no session => empty context", u.snapshot_context(None) == {})
prompt = u.build_prompt("all of meghalaya, all years", ctx)
check("prompt carries the message", '"all of meghalaya, all years"' in prompt)
check("prompt carries the pending clarification", "How many households got employment under MGNREGA" in prompt
      and "All financial years combined" in prompt)
check("prompt carries recent turns + state", "raw 4" in prompt and "EAST KHASI HILLS" in prompt)
import yaml as _y  # noqa: E402
_n_examples = len(_y.safe_load(u._FEW_SHOT_FILE.read_text(encoding="utf-8"))["examples"])
check("prompt carries every few-shot example (at least 12)",
      _n_examples >= 12 and prompt.count("\nJSON: {") == _n_examples,
      f"{prompt.count(chr(10) + 'JSON: {')} in prompt vs {_n_examples} in file")
check("prompt forbids guessing", "NEVER guess" in prompt and "Never fill a missing detail with a default" in prompt)
import yaml  # noqa: E402
_bad = []
for _ex in yaml.safe_load(u._FEW_SHOT_FILE.read_text(encoding="utf-8"))["examples"]:
    try:
        u.QueryFrame.model_validate(_ex["frame"])
    except Exception as _e:  # noqa: BLE001
        _bad.append(f"{_ex['from']}: {_e}")
check("every few-shot frame validates against QueryFrame", not _bad, "; ".join(_bad))

print("\n=== model call contract ===")
calls = []


async def _fake_model(**kw):
    calls.append(kw)
    return json.dumps(GOOD_FRAME)

orig_call = llm.call_model
llm.call_model = _fake_model
out = asyncio.run(u.build_frame("westgaro hils mgnrega spending", {}))
llm.call_model = orig_call
kw = calls[0]
check("uses settings.UNDERSTAND_MODEL (qwen4-deploy)", kw["model"] == "qwen4-deploy" == settings.UNDERSTAND_MODEL)
check("uses the verifier's credentials by default",
      kw["base_url"] == settings.SQL_VERIFY_BASE_URL and kw["api_key"] == settings.SQL_VERIFY_API_KEY)
check("temperature 0", kw["temperature"] == 0.0)
check("guided_json schema sent", (kw["guided"] or {}).get("guided_json") is u.FRAME_JSON_SCHEMA
      or not settings.GUIDED_DECODING_ENABLED)
check("frame parsed", out["frame"] and out["frame"]["schemes"] == ["MGNREGA"]
      and out["frame"]["geo_mentions"][0]["text"] == "westgaro hils", json.dumps(out))
check("clean frame has no guard flags", out["meta"]["flags"] == [], str(out["meta"]["flags"]))
check("latency recorded", isinstance(out["meta"].get("latency_ms"), int))


async def _garbage(**_kw):
    return "I think the user wants something"


async def _boom(**_kw):
    raise RuntimeError("gateway down")

for name, fn, want in (("no JSON in output", _garbage, "no JSON"), ("model call raises", _boom, "gateway down")):
    llm.call_model = fn
    res = asyncio.run(u.build_frame("x", {}))
    llm.call_model = orig_call
    check(f"{name}: frame None, error recorded, no raise",
          res["frame"] is None and want in res["meta"].get("error", ""), json.dumps(res))

print("\n=== coercion + guards ===")
flags: list[str] = []
f = u._coerce({**GOOD_FRAME, "schemes": ["MGNREGA", "PMAY-U"], "query_type": "sum",
               "geo_mentions": [{"text": "wgh", "level": "district"}, {"text": "x", "level": "planet"}]}, flags)
check("invalid scheme dropped, valid kept", f.schemes == ["MGNREGA"])
check("invalid query_type dropped", f.query_type is None)
check("bad geo level coerced to None, text kept", [(g.text, g.level) for g in f.geo_mentions]
      == [("wgh", "district"), ("x", None)])
check("each coercion flagged", any("PMAY-U" in x for x in flags) and any("query_type" in x for x in flags))

g = u.guard_flags(u.QueryFrame(**{**GOOD_FRAME, "geo_mentions": [{"text": "West Garo Hills", "level": None}]}),
                  "westgaro hils mgnrega spending", {})
check("geo not copied as typed is flagged", any("geo not as typed" in x for x in g), str(g))
g = u.guard_flags(u.QueryFrame(**{**GOOD_FRAME, "schemes": ["PMAY-G"], "geo_mentions": []}),
                  "total expenditure", {})
check("scheme with no text/context evidence is flagged", any("without text/context evidence" in x for x in g), str(g))
g = u.guard_flags(u.QueryFrame(**{**GOOD_FRAME, "geo_mentions": []}), "total manrega expenditure", {})
check("misspelled scheme name counts as evidence (no flag)", not g, str(g))
g = u.guard_flags(u.QueryFrame(**{**GOOD_FRAME, "schemes": ["PMAY-G"], "geo_mentions": []}), "and block wise?",
                  {"recent_turns": [{"user": "houses in ekh", "schemes": ["PMAY-G"]}]})
check("scheme certain from the conversation counts as evidence", not g, str(g))
g = u.guard_flags(u.QueryFrame(**{**GOOD_FRAME, "answers_pending": True, "geo_mentions": []}),
                  "mgnrega", {})
check("answers_pending with nothing pending is flagged", any("nothing pending" in x for x in g), str(g))

print("\n=== shadow wiring in _run_pipeline ===")
RESULT = {"route": "data", "answer": "42", "schemes": ["MGNREGA"]}
seen_ctx = []


async def _body(question, session=None, scope=None, frame_followup=None, frame_intent=None):
    if session is not None and session.state.pending_scope_q:
        session.state.pending_scope_q = None          # the real body consumes the pause first
    await asyncio.sleep(0.01)
    return dict(RESULT)


async def _frame(message, ctx):
    seen_ctx.append(ctx)
    return {"frame": GOOD_FRAME, "meta": {"flags": []}}

def _llm_part(d):
    return {k: v for k, v in d.items() if k in u.LLM_FIELDS}


async def _normalise_passthrough(f, message):
    return f                                    # normalise_frame has its own test file

orig_body, orig_build, orig_norm = pipeline._run_pipeline_body, u.build_frame, u.normalise_frame
pipeline._run_pipeline_body = _body
u.build_frame = _frame
u.normalise_frame = _normalise_passthrough
orig_flag, orig_to = settings.UNDERSTAND_SHADOW, settings.UNDERSTAND_TIMEOUT_SECONDS
try:
    settings.UNDERSTAND_SHADOW = False
    s = _session()
    r = asyncio.run(pipeline._run_pipeline("q", session=s))
    check("flag off: no Understand call", not seen_ctx)
    check("flag off: result unchanged", r == RESULT)
    check("flag off: no frame on session", s.understand_frame is None)

    settings.UNDERSTAND_SHADOW = True
    s = _session(pending="How many households got employment under MGNREGA")
    r = asyncio.run(pipeline._run_pipeline("all years", session=s))
    check("flag on: result identical to the pipeline's own", r == RESULT)
    check("flag on: frame stored on session, tagged with its message",
          s.understand_frame and _llm_part(s.understand_frame["frame"]) == GOOD_FRAME
          and s.understand_frame["question"] == "all years")
    check("flag on: context snapshot taken BEFORE the body consumed the pause",
          (seen_ctx[-1].get("pending") or {}).get("question") == "How many households got employment under MGNREGA")

    async def _pause(question, session=None, scope=None, frame_followup=None, frame_intent=None):
        raise pipeline.ClarificationNeeded("Which year?", rule="year-not-specified")
    pipeline._run_pipeline_body = _pause
    s = _session()
    try:
        asyncio.run(pipeline._run_pipeline("mgnrega spend", session=s))
        check("clarification pause still propagates", False, "no exception")
    except pipeline.ClarificationNeeded as e:
        check("clarification pause still propagates unchanged", e.rule == "year-not-specified")
    check("frame recorded for a paused turn too",
          s.understand_frame and _llm_part(s.understand_frame["frame"]) == GOOD_FRAME)

    async def _slow(message, ctx):
        await asyncio.sleep(30)
    pipeline._run_pipeline_body = _body
    u.build_frame = _slow
    settings.UNDERSTAND_TIMEOUT_SECONDS = 0.05
    s = _session()
    r = asyncio.run(pipeline._run_pipeline("q", session=s))
    check("slow frame: answer still returned unchanged", r == RESULT)
    check("slow frame: recorded as an error, not a frame",
          s.understand_frame["frame"] is None and "shadow wait" in s.understand_frame["meta"]["error"])

    async def _cancel_run():
        t = asyncio.create_task(pipeline._run_pipeline("q", session=_session()))
        await asyncio.sleep(0.001)
        t.cancel()
        try:
            await asyncio.wait_for(t, 2)
            return "finished"
        except asyncio.CancelledError:
            return "cancelled"
    check("cancelled request is not held up waiting for the frame", asyncio.run(_cancel_run()) == "cancelled")
finally:
    pipeline._run_pipeline_body, u.build_frame, u.normalise_frame = orig_body, orig_build, orig_norm
    settings.UNDERSTAND_SHADOW, settings.UNDERSTAND_TIMEOUT_SECONDS = orig_flag, orig_to

print("\n=== audit helper ===")
sess = session_store.ensure("t-audit-frame", "u")
sess.understand_frame = {"frame": GOOD_FRAME, "meta": {}, "question": "hello"}
check("audit logs the frame for its own message",
      query_router._shadow_frame_for("t-audit-frame", "hello") is sess.understand_frame)
check("audit ignores a frame from another message (cache-hit turn)",
      query_router._shadow_frame_for("t-audit-frame", "different") is None)

print()
if _fails:
    print(f"FAILED {len(_fails)}: {_fails}")
    sys.exit(1)
print("ALL UNDERSTAND CHECKS PASSED")
