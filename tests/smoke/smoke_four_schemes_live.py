"""
tests/smoke/smoke_four_schemes_live.py — LIVE end-to-end smoke across all four
schemes, run against the real model gateway and the real megh_db.

NOT part of the standalone `tests/test_*.py` sweep (deliberately named
`smoke_*`, like smoke_restructure.py): it needs network reach to the Qwen
gateway and Postgres, so it can only run from inside the office network.
Exits 0 and prints SKIPPED when they are unreachable.

What it checks, per question:
  * a CLARIFICATION LOOP — the same rule asked twice in a row with an
    identical chip question, i.e. an option that cannot change the outcome.
    This is the failure mode reported repeatedly from the live UI
    (tranche-not-specified, no-time-dimension) and the one a mocked test
    cannot see, because it depends on what the real LLM extractor tags.
  * an unhandled exception escaping the pipeline (what surfaced as 502).
  * a DATA answer that came back with rows, and the SQL that produced it.

`python tests/smoke/smoke_four_schemes_live.py`
"""
import asyncio
import logging
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(level=logging.ERROR)

from app.core.config import settings  # noqa: E402

settings.PIPELINE_GRAPH_ENABLED = True  # exercise the LangGraph path

from app.database import db  # noqa: E402
from app.clients import llm
from app.orchestration import pipeline
from app.database import vectorstore
from app.knowledge.annotations import load_all as load_annotations  # noqa: E402
from app.core.auth import UserScope  # noqa: E402
from app.nlu.entity_resolver import load_all as load_entity_resolver  # noqa: E402
from app.conversation.session_store import session_store  # noqa: E402

_MAX_CLARIFY_ROUNDS = 4

_SCOPE = UserScope(user_id="smoke", role="admin", granularity_cap="village",
                   schemes=["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate"],
                   geographies="all", tenant_id=1, db_user_id=1, username="smoke")

# (label, question). Chosen to cover each scheme's own gates: MGNREGA's
# district/year, PMAY-G's year range, Focus Plus's tranche gate, CM Elevate's
# missing time dimension.
_QUESTIONS = [
    ("MGNREGA   ", "Total MGNREGA person-days in 2023-24 for South Garo Hills"),
    ("MGNREGA   ", "MGNREGA expenditure by district for FY 2023-24"),
    ("PMAY-G    ", "PMAY-G houses completed by district for FY 2022-23"),
    ("PMAY-G    ", "How many PMAY-G houses were sanctioned in Ri Bhoi in 2022-23"),
    ("Focus Plus", "How many FOCUS+ payments were made in each batch for West Garo Hills "
                   "for FY 2022-23 across all tranches"),
    ("Focus Plus", "Total Focus Plus disbursement for East Khasi Hills in 2022-23 "
                   "across all tranches"),
    ("CM Elevate", "Top 5 CM Elevate schemes by applications"),
    ("CM Elevate", "How many CM Elevate applications are on hold for all of Meghalaya"),
    ("KNOWLEDGE ", "Who is eligible for PMAY-G?"),
    ("EDGE      ", "hello"),
]

_results: list[tuple[str, str, str]] = []  # (verdict, label, detail)


def _reachable(host: str, port: int) -> bool:
    try:
        s = socket.create_connection((host, port), 8)
        s.close()
        return True
    except Exception:  # noqa: BLE001
        return False


async def _ask(label: str, question: str) -> None:
    """Drive one question, auto-answering clarifications by taking the first
    chip — exactly what a user does — and flag a loop rather than spinning."""
    sess = session_store.ensure(f"smoke-{abs(hash(question))}", _SCOPE.user_id)
    q = question
    seen: list[tuple[str, str]] = []   # (rule, first chip question)
    for _round in range(_MAX_CLARIFY_ROUNDS):
        try:
            r = await pipeline.answer_question(q, session=sess, scope=_SCOPE)
        except pipeline.ClarificationNeeded as e:
            chips = [o.get("question") for o in (e.options or []) if o.get("question")]
            sig = (e.rule or "", chips[0] if chips else "")
            if sig in seen:
                _results.append(("LOOP", label,
                                 f"rule={e.rule!r} repeats with an identical chip "
                                 f"{sig[1]!r} — the option cannot change the outcome"))
                return
            seen.append(sig)
            if not chips:
                _results.append(("CLARIFY", label,
                                 f"rule={e.rule!r} (terminal, no chips) — {e.question[:70]}"))
                return
            q = chips[0]
            continue
        except Exception as e:  # noqa: BLE001
            _results.append(("ERROR", label, f"{type(e).__name__}: {e}"))
            return

        route = r.get("route")
        if route == "data":
            rows = r.get("row_count") or 0
            sql = (r.get("sql") or "").replace("\n", " ")[:90]
            if rows:
                _results.append(("OK", label, f"{rows} rows | {sql}"))
            else:
                _results.append(("NO-ROWS", label, f"answer={str(r.get('answer'))[:80]!r}"))
        else:
            _results.append(("OK", label, f"route={route} | {str(r.get('answer'))[:70]!r}"))
        return
    _results.append(("LOOP", label, f"still clarifying after {_MAX_CLARIFY_ROUNDS} rounds"))


async def main() -> int:
    if not (_reachable("10.48.242.4", 443) and _reachable("10.48.242.4", 5432)):
        print("SKIPPED — model gateway / megh_db not reachable from this host "
              "(needs the office network).")
        return 0

    await llm.init_client()
    await db.init_pool()
    await vectorstore.init_pgvector()
    load_annotations()
    load_entity_resolver()
    await pipeline.refresh_scheme_years()

    for label, question in _QUESTIONS:
        await _ask(label, question)

    await llm.close_client()

    print()
    bad = 0
    for verdict, label, detail in _results:
        if verdict in ("LOOP", "ERROR"):
            bad += 1
        print(f"  {verdict:8} {label}  {detail}")
    print()
    print(f"{len(_results) - bad}/{len(_results)} clean; {bad} LOOP/ERROR")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
