"""
Conversation harness: multi-turn scenarios with expectations, run against the
chatbot either in-process (the router path on the LangGraph pipeline) or through
the HTTP API of a running server (plain and streamed), and checked turn by turn:
route, scope (scheme / place / year carried across asides), figures, leaks,
chips, pauses, and figures against megh_db truth.

    .venv/Scripts/python.exe -m tests.conversation_harness.run --driver http
    .venv/Scripts/python.exe -m tests.conversation_harness.run --driver http --stream --account state-rd
    .venv/Scripts/python.exe -m tests.conversation_harness.run --driver inprocess --only B_out_of_scope,E_hierarchy
    .venv/Scripts/python.exe -m tests.conversation_harness.run --validate      # scenario files only, offline

See README.md in this folder for the scenario format.
"""
