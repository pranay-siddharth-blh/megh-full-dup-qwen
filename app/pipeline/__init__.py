"""app.pipeline — the question-answering pipeline (stage functions for the LangGraph graph).

LangGraph is the only driver: app/pipeline_graph.py runs the stage functions defined here as
its graph nodes (D-032, D-036). Behaviour lives in the stages, never in a graph node.

Layout (2026-10-15; until then one 18,700-line pipeline.py):
    common/   the shared steps every scheme goes through (c01_followups ... c14_turn_stages)
    schemes/  one file per scheme: that scheme's village rules, fixed queries, SQL rewrites
              and answer checks (mgnrega, pmay_g, focus_plus, cm_elevate, focus_legacy,
              cm_elevate_legacy)

The files are not separate modules. They are executed here, in _PIPELINE_FILES order, into
this package's namespace, so they share ONE namespace exactly as the single file did:
`from app import pipeline as p`, `p.<name>` and `monkeypatch.setattr(p, ...)` work unchanged.
Function bodies may use a name from any file. Code that runs at load time (constants, matchers,
default arguments, annotations) may only use names from files loaded before it, hence the
order: shared basics, then the schemes, then the shared steps that call them. A new file goes
into _PIPELINE_FILES at the right place.

Original module notes:

The whole NL -> SQL -> answer flow, as stage functions (`_turn_*_stage`,
`_data_*_stage`, `_execute_one_attempt`, ...). The LangGraph orchestrator in
app/pipeline_graph.py is the only driver: it runs these stages as graph nodes
(D-032, D-036). Behaviour lives here, in the stages, never in a graph node.
"""
from pathlib import Path as _PipelinePath

_PIPELINE_FILES = (
    # shared basics: imports, exceptions, follow-ups, rephraser, scheme vocabulary
    "common/c01_followups",
    "common/c02_rephraser",
    "common/c03_scheme_terms",
    # one file per scheme
    "schemes/mgnrega",
    "schemes/pmay_g",
    "schemes/focus_plus",
    "schemes/cm_elevate",
    "schemes/focus_legacy",
    "schemes/cm_elevate_legacy",
    # shared steps, in pipeline order
    "common/c04_scheme_listing",
    "common/c05_clarifications",
    "common/c06_years_tranches",
    "common/c07_mentions",
    "common/c08_villages",
    "common/c09_resolve_entities",
    "common/c10_sql_generation_and_rewrites",
    "common/c11_sql_verify_repair",
    "common/c12_answer_numbers",
    # the answer's shape — ranking / comparison / trend … (user report 2026-10-22)
    "common/c12_answer_shapes",
    "common/c13_compose_and_data_stages",
    "common/c14_turn_stages",
    # talking about the conversation itself (D-052); called by the turn stages at run time
    "common/c15_conversation_meta",
    # the data team's metric catalogue as the last fixed query (D-071); called by c13 at run time
    "common/c16_metric_catalog",
)

for _pipeline_name in _PIPELINE_FILES:
    _pipeline_file = _PipelinePath(__file__).parent / (_pipeline_name + ".py")
    exec(compile(_pipeline_file.read_text(encoding="utf-8"), str(_pipeline_file), "exec"), globals())
del _pipeline_name, _pipeline_file
