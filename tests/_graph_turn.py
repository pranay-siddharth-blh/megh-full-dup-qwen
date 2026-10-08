"""Test helpers: drive a turn through the LangGraph orchestrator, the only one
(D-036). There is no sequential driver to call directly any more.

    from _graph_turn import graph_turn, stub_data_path

    stub_data_path(monkeypatch, fake_answer_data)   # optional: stub the DATA path
    result = asyncio.run(graph_turn("What about Dalu block?", session=s))

`graph_turn` runs pipeline.answer_question (the graph) with an in-process
checkpointer, so nothing needs Postgres. A pause raises ClarificationNeeded as
it does for the router; the reply resumes from the Session's pending pause.
"""
from app import pipeline as p
from app import pipeline_graph as pg
from app.config import settings


def data_stage_from(answer_data):
    """A scope_scheme stage that hands the whole DATA path to `answer_data`
    (question, scope=, skip_scope_clarify=, prior_resolved=, village_hint=):
    for tests that stub everything after the turn stages. A result ends the
    DATA path there; a raise is mapped by the graph exactly like a real stage."""
    async def stage(d, scope=None):
        return await answer_data(d["question"], scope=scope,
                                 skip_scope_clarify=d["skip_scope_clarify"],
                                 prior_resolved=d["prior_resolved"],
                                 village_hint=d["village_hint"])
    return stage


def stub_data_path(monkeypatch, answer_data) -> None:
    monkeypatch.setattr(p, "_data_scheme_stage", data_stage_from(answer_data))


async def graph_turn(question, session=None, scope=None):
    """One turn on the graph, with an in-process checkpointer."""
    saved = settings.PIPELINE_GRAPH_CHECKPOINTER_DSN
    settings.PIPELINE_GRAPH_CHECKPOINTER_DSN = "memory"
    try:
        return await p.answer_question(question, session=session, scope=scope)
    finally:
        await pg.close()
        settings.PIPELINE_GRAPH_CHECKPOINTER_DSN = saved
