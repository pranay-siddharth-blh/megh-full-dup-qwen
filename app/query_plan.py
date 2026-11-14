"""
E1 (RAG plan) — the query plan, stage 1: SHADOW ONLY (user decision 2026-10-27, D-078).

The plan reads a question ONCE into a typed structure — intent, schemes, measure,
place, years, shape, top N, order — so that later every stage could read the plan
instead of re-reading the words (two wordings, one plan, one answer). Stage 1 only
builds it and logs it beside what the pipeline actually decided; nothing reads it.

- One guided-JSON call to the classifier model (qwen4-deploy, the classification
  role). Its enums come from the scheme list and the metric catalogue's keys, so the
  model can only name a real scheme or measure.
- Deterministic fields are not left to the model: years (every FY form and stated
  spans, the same readers the pipeline uses) and the top-N count (KI-412).
- It runs in the BACKGROUND at the end of the turn (_update_context schedules it),
  after the answer is composed, so it never delays or competes with the officer's
  turn. One JSON line per turn to QUERY_PLAN_FILE; tests/query_plan/compare.py
  reports per-field agreement with the pipeline's decisions.

Stage 2a (2026-10-29, D-085; with RAG plan E2): for a NEW question the plan is built
DURING the turn, started beside the guardrail model call (c14 _guardrail_check,
start_for_turn), so the two classifier calls overlap. Nothing waits for it: the turn
goes on, a guardrail refusal cancels it, and the end-of-turn shadow reuses it instead
of a second call. turn_plan(session) is how a later stage will read it (stage 2b, one
field at a time, each with the user's go-ahead). QUERY_PLAN_IN_TURN, OFF by default:
measured live the two 4B calls queue on the gateway rather than overlap (turn median
11.8 s -> 14.1 s), so it pays only once a stage reads the plan and drops its own call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path

from app import scheme_registry
from app.config import settings

logger = logging.getLogger(__name__)

SCHEMES = scheme_registry.NAMES   # E5, D-079
SHAPES = ("single_value", "breakdown", "ranking", "compare", "trend", "list", "none")
LEVELS = ("state", "district", "block", "village", "assembly_constituency", "none")
GROUPS = ("district", "block", "village", "year", "category", "none")

_lock = threading.Lock()


def _schema(measures: "list[str]") -> dict:
    return {
        "type": "object",
        "properties": {
            "intent": {"enum": ["DATA", "KNOWLEDGE", "OTHER"]},
            "schemes": {"type": "array", "items": {"enum": list(SCHEMES)}},
            "measure": {"enum": [*measures, "other", "none"]},
            "place_level": {"enum": list(LEVELS)},
            "place_name": {"type": "string"},
            "group_by": {"enum": list(GROUPS)},
            "all_years": {"type": "boolean"},
            "shape": {"enum": list(SHAPES)},
            "order": {"enum": ["highest", "lowest", "none"]},
        },
        "required": ["intent", "schemes", "measure", "place_level", "place_name", "group_by", "all_years", "shape",
                     "order"],
    }


def _prompt(question: str, measures: "dict[str, str]") -> str:
    menu = "\n".join(f"  {k}: {v}" for k, v in measures.items())
    return f"""Read this question about Meghalaya government scheme data into a plan.

intent: DATA (a figure, count, list or comparison from the scheme database), KNOWLEDGE (how a
  scheme works: rules, eligibility, process, objectives, and "what is <term>" definitions of
  scheme terms such as SECC, DBT, job card), OTHER (greeting, off-topic).
schemes: every scheme the question is about (none if it names or implies none).
measure: the ONE catalogue measure it asks for, else "other" (a figure not listed) or "none".
place_level / place_name: the AREA the figures are filtered to, as written ("in Ri Bhoi" ->
  district, Ri Bhoi). "state" for all of Meghalaya, "none" if it names no area. Two or more named
  areas compared: their level, names comma-separated. NOT the grouping: "by district" alone is none.
group_by: the level the answer is split or ranked by ("by district", "top 5 blocks" -> block,
  "each year" -> year), else none.
all_years: true only if it explicitly asks across all years.
shape: single_value (one figure), breakdown (split by a level or category), ranking (top /
  highest / which X has most), compare (two or more named sides), trend (over time), list
  (names), none.
order: highest / lowest for a ranking, else none.

Catalogue measures:
{menu}

Return ONLY JSON.
Question: "{question}"
JSON:"""


def _measure_menu() -> "dict[str, str]":
    from app import metric_catalog
    return {k: f"{m.scheme} — {m.display_name}" for k, m in sorted(metric_catalog.metrics().items())}


def normalise(question: str, plan: dict) -> dict:
    """Fill the deterministic fields from the pipeline's own readers: years
    (FY forms, stated spans), the top-N count, and the measure when the
    catalogue's literal match names exactly one (the model's pick otherwise;
    measured 2026-10-27: the 4B chose a wrong measure for 3 of 10)."""
    from app import context_policy, metric_catalog
    from app import pipeline as p
    out = dict(plan)
    schemes = [s for s in (plan.get("schemes") or []) if s in SCHEMES]
    if len(schemes) == 1:
        hit = metric_catalog.match(question, schemes[0])
        if hit.metric is not None:
            out["measure"], out["measure_from"] = hit.metric.key, "catalogue"
        else:
            out["measure_from"] = "model"
    span = p._c09_stated_year_span(question)
    if span is not None:
        out["years"] = list(range(span[0], span[1] + 1))
    else:
        out["years"] = sorted(context_policy.extract_year_keys(question))
    out["top_n"] = p._requested_rank_count(question)
    # The area level from the place index the resolver uses (the DB decides places;
    # the 4B read "by district" / "top 5 blocks" as the area 7 times in 16).
    try:
        from app.entity_resolver import place_mentions
        dims = set(place_mentions(question).values())
    except Exception:  # noqa: BLE001 — no index: keep the model's reading
        dims = None
    if dims is not None:
        level = next((lv for lv in ("village", "block", "assembly_constituency", "district") if lv in dims), None)
        if level:
            out["place_level"], out["place_from"] = level, "index"
        elif out.get("place_level") not in ("state", "none"):
            out["place_level"], out["place_from"] = "none", "index"
    return out


async def extract(question: str) -> "dict | None":
    """The plan for one question, or None (no catalogue / unusable reply)."""
    from app import llm
    from app import pipeline as p
    menu = _measure_menu()
    raw = await llm.call_classifier(_prompt(question, menu), guided={"guided_json": _schema(list(menu))})
    plan = p._extract_json(raw)
    if not isinstance(plan, dict) or plan.get("intent") not in ("DATA", "KNOWLEDGE", "OTHER"):
        return None
    return normalise(question, plan)


def actual(result: dict) -> dict:
    """What the pipeline decided for the turn, in the plan's terms."""
    from app import sql_ast
    sql = result.get("sql") or result.get("sql_query") or ""
    resolved = result.get("resolved_entities") or {}
    years = resolved.get("year_key_list") or ([resolved["year_key"]] if resolved.get("year_key") is not None else [])
    measure = None
    if sql.startswith("/* metric:"):
        measure = sql[len("/* metric:"):].split()[0]
    place_level = next((lv for lv, keys in (("village", ("village_code", "village_code_list")),
                                             ("block", ("block", "block_list")),
                                             ("district", ("district", "district_list")),
                                             ("assembly_constituency", ("assembly_constituency",)))
                        if any(resolved.get(k) for k in keys)), "none")
    try:
        limit = sql_ast.outer_limit(sql) if sql else None
    except Exception:  # noqa: BLE001
        limit = None
    route = result.get("route")
    return {"intent": {"data": "DATA", "knowledge": "KNOWLEDGE"}.get(route, "OTHER"), "route": route,
            "schemes": list(result.get("schemes") or []), "measure": measure, "place_level": place_level,
            "years": sorted(int(y) for y in years if isinstance(y, int)), "limit": limit}


def compare(plan: dict, act: dict) -> dict:
    """Per-field agreement (True / False), only for fields both sides state."""
    out = {"intent": plan.get("intent") == act.get("intent")}
    if act.get("intent") == "DATA" and plan.get("intent") == "DATA":
        out["schemes"] = sorted(plan.get("schemes") or []) == sorted(act.get("schemes") or [])
        if act.get("measure"):
            out["measure"] = plan.get("measure") == act["measure"]
        if act.get("place_level") != "none" or plan.get("place_level") not in ("none", "state"):
            out["place_level"] = plan.get("place_level") == act.get("place_level")
        if act.get("years") or plan.get("years"):
            out["years"] = plan.get("years") == act.get("years")
        if plan.get("top_n"):
            out["top_n"] = plan.get("top_n") == act.get("limit")
    return out


# ── Stage 2a: the plan built during the turn ────────────────────────────────

_TURN_KEY = "query_plan"   # in session.turn_context (in-process, never persisted)


async def _extract_quietly(question: str, box: dict) -> "dict | None":
    try:
        return await extract(question)
    except Exception:  # noqa: BLE001 — the plan must never break a turn
        logger.debug("in-turn query plan failed", exc_info=True)
        return None
    finally:
        box["ms"] = round((time.monotonic() - box["t0"]) * 1000)


def start_for_turn(session, question: str) -> None:
    """Start building this turn's plan in the background (not awaited). Called
    right before the guardrail model call, so the two classifier calls overlap."""
    if (session is None or not settings.QUERY_PLAN_SHADOW or not settings.QUERY_PLAN_IN_TURN
            or not (question or "").strip()):
        return
    ctx = getattr(session, "turn_context", None)
    if not isinstance(ctx, dict) or _TURN_KEY in ctx:
        return
    try:
        box = {"question": question, "t0": time.monotonic()}
        box["task"] = asyncio.get_running_loop().create_task(_extract_quietly(question, box))
        ctx[_TURN_KEY] = box
    except RuntimeError:
        return


def cancel_for_turn(session) -> None:
    """Drop this turn's plan (a guardrail refusal: nothing will read it)."""
    box = (getattr(session, "turn_context", None) or {}).pop(_TURN_KEY, None)
    if box and not box["task"].done():
        box["task"].cancel()


def take_for_turn(session) -> "dict | None":
    """Hand this turn's plan box to the end-of-turn shadow (and forget it)."""
    return (getattr(session, "turn_context", None) or {}).pop(_TURN_KEY, None)


async def turn_plan(session, question: "str | None" = None) -> "dict | None":
    """This turn's plan, waiting for it if still running; None when none was
    started (a follow-up, a pause reply, a greeting, the flag off) or, given
    `question`, when the plan was read from other words. The stage-2b reader
    (first field: intent, c13 _c13_intent_by_rules)."""
    box = (getattr(session, "turn_context", None) or {}).get(_TURN_KEY)
    if not box or (question is not None and box["question"].strip() != (question or "").strip()):
        return None
    try:
        return await asyncio.shield(box["task"])
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        return None


async def shadow(question: str, raw_question: str, result: dict,
                 pending: "dict | None" = None) -> "dict | None":
    """Build the plan for a finished turn (or reuse `pending`, the plan built
    during the turn) and log it beside the actual decision. Best-effort: never
    raises."""
    if not settings.QUERY_PLAN_SHADOW or result.get("route") not in ("data", "knowledge"):
        if pending and not pending["task"].done():
            pending["task"].cancel()
        return None
    try:
        t0 = time.monotonic()
        if pending is not None:
            plan = await pending["task"]
            ms, plan_from = pending.get("ms"), "turn"
        else:
            plan = await extract(question)
            ms, plan_from = round((time.monotonic() - t0) * 1000), "after"
        if plan is None:
            return None
        act = actual(result)
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "question": question,
                  "raw_question": raw_question, "plan": plan, "actual": act, "agree": compare(plan, act),
                  "ms": ms, "plan_from": plan_from}
        if pending is not None:
            record["plan_question"] = pending["question"]
        path = Path(settings.QUERY_PLAN_FILE)
        path = path if path.is_absolute() else Path(__file__).resolve().parent.parent / path
        from app.pii_mask import mask_record          # the officer's words: personal data masked (PII_LOG_MODE)
        with _lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(mask_record(record), ensure_ascii=False, default=str) + "\n")
        return record
    except Exception:  # noqa: BLE001 — shadow only
        logger.debug("query plan shadow failed", exc_info=True)
        return None
