"""
A year the user DID name but which maps to more than one financial year
("2023" -> FY 2022-23 or FY 2023-24). The resolver catalogue's own rule is to
ask and never default (data/mgnrega/mgnrega_entity_resolver.yaml,
year.ambiguous_input) — but the pause it raised used to carry no options and no
`rule`, which made it a dead end in both directions in the live UI (2026-09-22):

  * no options  -> the clarification bubble rendered with nothing to tap;
  * no rule     -> the pause was not in RESUMABLE_CLARIFICATION_RULES, so a
                   typed answer ("2023-24") was not merged back into the paused
                   question either — it started a brand-new turn that had
                   forgotten the village/block the user had just spent an
                   earlier clarification round pinning down.

Covers the fix end to end at the unit level: the chips themselves, the
resumable rule set every resume mechanism now shares, exact chip recognition
(the FY chips rewrite the MIDDLE of the question, which the old prefix test
mis-read as free text), and the resolved-so-far carry that makes a SECOND
clarification round keep the first round's answer.

No DB, no model gateway — the two resolver calls are stubbed.
Run: `python tests/unit/test_year_ambiguity_clarification.py`, exit code 0 = pass.
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@127.0.0.1:5/none")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault("ENV", "prod")

from app.orchestration import langgraph_followup, pipeline, pipeline_graph  # noqa: E402
from app.nlu.entity_resolver import Resolved  # noqa: E402
from app.conversation.session_store import ConversationState  # noqa: E402

_fails: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _fails.append(name)


# The exact live question from the 2026-09-22 report: a village ambiguity has
# already been answered (the trailing ", <block> block, <district>" is the first
# chip's own text), and the bare "2023" is what pauses the second round.
LIVE_Q = ("What was the total expenditure in Nongthymmai during 2023 for MGNREGA, "
          "RI MULIANG block, WEST KHASI HILLS")


# ── 1. _year_chip_question ──────────────────────────────────────────────────
print("1. YEAR CHIP QUESTION")

chip = pipeline._year_chip_question(LIVE_Q, "2023", 2023)
check("the ambiguous token is replaced, not appended to",
      "during FY 2023-24 for" in chip, chip)
check("no bare '2023' is left behind to re-trip the same pause",
      " 2023 " not in chip, chip)
check("the earlier clarification round's answer is preserved verbatim",
      chip.endswith("RI MULIANG block, WEST KHASI HILLS"), chip)
check("the other chip differs from the first (or the pause would loop)",
      pipeline._year_chip_question(LIVE_Q, "2023", 2022) != chip)
check("an 'FY' already in front of the token is consumed, not doubled",
      pipeline._year_chip_question("Person-days in FY 2023", "2023", 2023)
      == "Person-days in FY 2023-24",
      pipeline._year_chip_question("Person-days in FY 2023", "2023", 2023))
check("a relative token the user actually typed is substituted in place",
      pipeline._year_chip_question("Person-days last year", "last year", 2024)
      == "Person-days FY 2024-25",
      pipeline._year_chip_question("Person-days last year", "last year", 2024))
check("a token the extractor normalised out of the text falls back to appending",
      pipeline._year_chip_question("Person-days for the previous FY", "2023", 2023)
      == "Person-days for the previous FY, FY 2023-24",
      pipeline._year_chip_question("Person-days for the previous FY", "2023", 2023))


# ── 2. _year_ambiguity_clarification ────────────────────────────────────────
print("2. YEAR AMBIGUITY CLARIFICATION")

cands = [{"canonical": "2023-2024"}, {"canonical": "2022-2023"}]
clar = pipeline._year_ambiguity_clarification(
    LIVE_Q, "2023", cands, ["MGNREGA"],
    village_hint="Nongthymmai", resolved_so_far={"block": "RI MULIANG"})

check("it is a ClarificationNeeded", isinstance(clar, pipeline.ClarificationNeeded))
check("it offers one tappable chip per candidate year", len(clar.options) == 2,
      str(clar.options))
check("chips are labelled as financial years",
      [o["label"] for o in clar.options] == ["FY 2022-23", "FY 2023-24"],
      str([o["label"] for o in clar.options]))
check("every chip carries a full, unambiguous standalone question",
      all("FY 20" in o["question"] and o["question"] != LIVE_Q for o in clar.options))
check("every chip pins the year_key it stands for",
      [o["pins"]["year_key"] for o in clar.options] == [2022, 2023],
      str(clar.options))
check("the rule is resumable", clar.rule in pipeline.RESUMABLE_CLARIFICATION_RULES, str(clar.rule))
check("the village the user already disambiguated rides along",
      clar.village_hint == "Nongthymmai")
check("what was already resolved rides along too",
      clar.resolved_so_far == {"block": "RI MULIANG"}, str(clar.resolved_so_far))
check("the question names both candidate years so free text is answerable too",
      "FY 2022-23" in clar.question and "FY 2023-24" in clar.question, clar.question)

# A year the scheme does not hold is never offered as a chip.
narrowed = pipeline._year_ambiguity_clarification(
    "Focus Plus beneficiaries in 2023", "2023",
    [{"canonical": "2022-2023"}, {"canonical": "2023-2024"}], ["Focus Plus"])
check("chips are filtered to the years the scheme actually holds",
      [o["label"] for o in narrowed.options] == ["FY 2022-23"],
      str([o["label"] for o in narrowed.options]))


# ── 3. The resumable-rule set is shared, not hand-copied ────────────────────
print("3. RESUMABLE RULE SET")

check("'year-ambiguous' is resumable",
      "year-ambiguous" in pipeline.RESUMABLE_CLARIFICATION_RULES)
check("the pre-existing pause rules are still resumable",
      {"scope-not-specified", "year-not-specified", "entity-ambiguous"}
      <= pipeline.RESUMABLE_CLARIFICATION_RULES)
check("app/orchestration/langgraph_followup.py reads the same set, not its own copy",
      langgraph_followup._PAUSE_ELIGIBLE_RULES is pipeline.RESUMABLE_CLARIFICATION_RULES)
check("app/orchestration/pipeline_graph.py reads the same set, not its own copy",
      pipeline_graph._PAUSE_ELIGIBLE_RULES is pipeline.RESUMABLE_CLARIFICATION_RULES)


# ── 4. Chip recognition on resume ───────────────────────────────────────────
print("4. CHIP RECOGNITION / MERGE")

fy_chip = clar.options[1]["question"]           # "... during FY 2023-24 for MGNREGA, ..."
check("a chip that rewrites the MIDDLE of the question is still recognised",
      pipeline.matching_chip(fy_chip, clar.options) is clar.options[1])
check("its pins come back with it",
      pipeline.matching_chip(fy_chip, clar.options)["pins"] == {"year_key": 2023})
check("free text is not mistaken for a chip",
      pipeline.matching_chip("2023-24 please", clar.options) is None)
check("a chip reply is passed through whole, never concatenated",
      pipeline.merge_clarification_reply(LIVE_Q, fy_chip, clar.options) == fy_chip,
      pipeline.merge_clarification_reply(LIVE_Q, fy_chip, clar.options))
check("without the options it WOULD have been duplicated (the bug being fixed)",
      pipeline.merge_clarification_reply(LIVE_Q, fy_chip).startswith(LIVE_Q + ","))
check("free text is still merged back into the paused question",
      pipeline.merge_clarification_reply(LIVE_Q, "2023-24", clar.options)
      == LIVE_Q + ", 2023-24")
check("an appending chip still passes through with no options recorded",
      pipeline.merge_clarification_reply("Total expenditure", "Total expenditure for FY 2023-24")
      == "Total expenditure for FY 2023-24")


# ── 5. resolve_entities stamps what it had already pinned ───────────────────
print("5. RESOLVED-SO-FAR CARRY")


async def _resolve_with_ambiguous_year() -> "pipeline.ClarificationNeeded | None":
    async def fake_mentions(question: str) -> dict:
        return {"block": "RI MULIANG", "year": "2023"}

    async def fake_dimension(text: str, scheme: str, dimension: str) -> Resolved:
        if dimension == "block":
            return Resolved("resolved", "block", text, canonical="RI MULIANG",
                            confidence=1.0, display="Ri Muliang")
        return Resolved("ambiguous", "year", text,
                        candidates=[{"canonical": "2022-2023"}, {"canonical": "2023-2024"}])

    real_mentions = pipeline.extract_entity_mentions
    real_dimension = pipeline.resolve_dimension
    pipeline.extract_entity_mentions = fake_mentions
    pipeline.resolve_dimension = fake_dimension
    try:
        await pipeline.resolve_entities(LIVE_Q, ["MGNREGA"])
    except pipeline.ClarificationNeeded as e:
        return e
    finally:
        pipeline.extract_entity_mentions = real_mentions
        pipeline.resolve_dimension = real_dimension
    return None


raised = asyncio.run(_resolve_with_ambiguous_year())
check("an ambiguous year still pauses", raised is not None)
if raised is not None:
    check("the pause now carries chips", len(raised.options) == 2, str(raised.options))
    check("the pause now carries a resumable rule",
          raised.rule in pipeline.RESUMABLE_CLARIFICATION_RULES, str(raised.rule))
    check("the block resolved BEFORE the pause is carried out with it",
          raised.resolved_so_far.get("block") == "RI MULIANG", str(raised.resolved_so_far))


# ── 6. ConversationState carries the pause fields across L1/L2 ──────────────
print("6. PENDING STATE ROUND-TRIP")

st = ConversationState()
st.pending_scope_q = LIVE_Q
st.pending_options = clar.options
st.pending_resolved = {"block": "RI MULIANG"}
back = ConversationState.from_dict(st.to_dict())
check("pending_options survives the L2 round trip",
      [o["label"] for o in back.pending_options] == ["FY 2022-23", "FY 2023-24"],
      str(back.pending_options))
check("pending_resolved survives the L2 round trip",
      back.pending_resolved == {"block": "RI MULIANG"}, str(back.pending_resolved))
check("a fresh state starts with neither",
      ConversationState().pending_options == [] and ConversationState().pending_resolved == {})


print()
if _fails:
    print(f"{len(_fails)} FAILED: " + ", ".join(_fails))
    sys.exit(1)
print("all checks passed")
