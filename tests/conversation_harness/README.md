# Conversation harness

Multi-turn conversations, declared in YAML, run against the chatbot and checked
turn by turn. It validates; it never guides or changes how the chatbot answers.

Why it exists (2026-10-18): the sheet runs check single questions, and the earlier
context suites hard-code their scenarios in Python and run **in-process** — which
passed while the real server failed, because the server rehydrates a session on
every request (it holds only the last turn, earlier questions live in the topic
ledger) and serves answers from caches. This harness drives the **HTTP API of a
running server** (plain or streamed, any seeded account), and the same scenarios
in-process when you want the pipeline's own decision log.

## Run

```bash
# from the repo root, VPN up, server running on :8401 (the project's only port)
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver http
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver http --stream
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver http --account state-rd --only E_denied_block_keeps_topic
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver http --skip-cache --repeat 3 --only CMP_compare_with_scheme
.venv/Scripts/python.exe -m tests.conversation_harness.run --driver inprocess --tags hierarchy
.venv/Scripts/python.exe -m tests.conversation_harness.run --validate      # offline: scenario files only
.venv/Scripts/python.exe -m tests.conversation_harness.run --list
```

Exit codes: 0 all passed · 1 a check failed · 2 a scenario file is invalid · 3 nothing
could run (server, DB or gateway unreachable). Reports: `logs/conversation_harness/
<timestamp>_<label>.json` — every turn's answer, banner, chips, DB truth and failures.

Login: the HTTP driver mints a JWT for the seeded user in-process with the `.env`
secret (`drivers.mint_token`); the seed passwords in `app/users.yaml` are not the
live ones. The account's permissions apply (a district-level account is denied block
questions — scenario `E_denied_block_keeps_topic` relies on that).

## Scenario format

```yaml
- name: B_out_of_scope                 # unique; used by --only
  doc: "Review B: ..."                 # what it proves
  tags: [out_of_scope, context]        # used by --tags
  account: superadmin                  # seeded username for the HTTP driver
  skip: "reason"                       # optional: listed, not run
  turns:
    - say: "How many MGNREGA job cards in West Garo Hills in 2024-25?"
      expect: {route: data, scheme: MGNREGA, place: West Garo Hills, year: FY 2024-25, numbers_any: [64939]}
    - say: "Who won the cricket match yesterday?"
      expect: {route: edge}
    - say: "What about 2023-24?"
      expect: {route: data, same_scope_as: 1, except: [year], year: FY 2023-24,
               truth: {sql: "SELECT SUM(job_cards_issued_total) FROM curated.v_employment WHERE lgd_district = 'WEST GARO HILLS' AND year_key = 2023"}}
```

Expectation keys (every key present must hold):

| key | meaning |
|---|---|
| `route` | `data` / `knowledge` / `edge` / `pause` / `denied` / `error` |
| `edge_type`, `pause_rule` | the edge reply kind / the clarification rule |
| `scheme`, `place`, `year` | scope-banner components; `place: all` = All of Meghalaya; `year: none` = no year |
| `banner` | the whole banner, exactly (a "(from earlier)" suffix is ignored) |
| `from_earlier` | the banner must say "(from earlier)" (a ledger restore) |
| `numbers_any` / `numbers_all` | numbers that must appear in the answer (commas ignored) |
| `answer_contains` / `answer_not_contains` | phrases (case-insensitive); the latter is the leak check |
| `chips_contain`, `chips_min` | follow-up / option chips |
| `same_scope_as: N`, `except: [year]` | banner components equal to turn N's, except the listed ones |
| `same_numbers_as: N` | every number of turn N's answer reappears (recap, restore) |
| `truth: {sql, within}` | the first numeric cell of this read-only query must be in the answer |

Rules: SQL in `truth` is run read-only through `db.run_readonly` (single SELECT,
auto-LIMIT); never write. Figures in the files are facts observed live on the date in
the file header — when the data changes, re-observe and update them (the `truth`
checks flag the drift). No regex anywhere (project rule): numbers via
`app.text_match.numbers`, text via string methods.

## Adding a scenario

1. Reproduce the conversation in the browser or with the HTTP driver.
2. Write the turns with the *minimal* expectations that would have caught the bug
   (scope components and a figure, a leak phrase, a pause rule).
3. `--validate`, then run it with `--driver http`; add a `truth` query where a
   single SELECT states the figure.
4. Record the run in `docs/TESTING.md`.

Offline unit tests of the checks and of every scenario file: `tests/test_conversation_harness.py`.
