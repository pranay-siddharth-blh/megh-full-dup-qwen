One file per scheme: that scheme's village rules, fixed queries, SQL rewrites and answer
checks. Called by the shared steps in `../common/`, which the LangGraph nodes in
`app/pipeline_graph.py` call. Loaded by `app/pipeline/__init__.py` into one namespace;
they are not separate Python modules.
