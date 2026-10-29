# Jira backlog for Megh One AI

**Current file (2026-10-22): `documents/jira/jira_backlog_v2.csv` / `.json`**, built by `jira/build_backlog_v2.py`
from the v1 CSV plus the 2026-10-19 changes. Pushed with `jira/push_to_jira.py` (Jira Cloud REST API v3).

| Epic | Scope | Stories | Tasks | Done | Open |
|---|---|---|---|---|---|
| E1 LangGraph orchestration | D-032, D-033, D-036, D-037, c15 in the graph, finalize framing, test isolation | 3 | 13 | 14 | 2 |
| E2 Context memory | MAIN_Contex.pdf P1..P6, D-050..D-055, KI-306..KI-334 | 29 | 7 | 30 | 6 |
| E3 Chat UI | D-038, D-039, D-042, KI-302, KI-325, KI-333, design rules, responsive, scheme cards, picker | 13 | 4 | 13 | 4 |

Hierarchy: Epic > Story (officer-visible behaviour) and Epic > Task (engineering, QA, DevOps). v2 corrects E2-07 to the
8-hour idle window and marks KI-324 (E2-23) done.

## Push with the API script

```
set JIRA_URL=https://<site>.atlassian.net
set JIRA_EMAIL=<atlassian account email>
set JIRA_API_TOKEN=<token from id.atlassian.com>
set JIRA_PROJECT=<project key>
python documents/jira/push_to_jira.py --check     # sign in, list issue types and fields
python documents/jira/push_to_jira.py --dry-run   # list what would be created
python documents/jira/push_to_jira.py             # create epics, then children, then set statuses
```

Created keys are saved in `jira/jira_push_state.json`; a re-run skips them, so new rows can be added and pushed
alone. Components missing in the project are skipped; Story falls back to Task if the project has no Story type;
company-managed projects get Epic Name / Epic Link automatically. Never commit the token.

## v1 notes (kept for the CSV importer route)


Source of truth for what goes into Jira for the two tracks the user asked for on 2026-10-19:

| Epic | Scope | Tasks | Done | Open |
|---|---|---|---|---|
| E1 LangGraph orchestration for the Megh One AI pipeline | D-032, D-036, D-037, pipeline package, graph tests | 12 | 10 | 2 |
| E2 Context memory: forward and backward conversation memory | MAIN_Contex.pdf P1..P6, WI-1..WI-9, D-050, D-051, D-052, D-053, D-054, KI-306..KI-325 | 25 | 19 | 6 |

The file is `documents/jira/jira_backlog_langgraph_context_memory.csv`.

## Columns

`Issue Type, Issue ID, Parent ID, Summary, Description, Status, Priority, Labels, Components, Story Points`

- `Issue ID` / `Parent ID` are import-time ids only. Jira's CSV importer uses them to link each Task to its Epic
  (map `Issue ID` to "Issue Id" and `Parent ID` to "Parent Id" in the field-mapping step).
- `Labels` are `;`-separated; set the importer's multi-value delimiter to `;`.
- `Status` values are `Done`, `In Progress`, `To Do`. Map them to the project's workflow in the importer.
- `Components` are `Backend`, `Frontend`, `QA`, `Docs`, `DevOps`. Create them in the project first or clear the column.

## Two ways to push

1. **Claude with the Atlassian connector.** Authorize "claude.ai Atlassian" in claude.ai connector settings, then ask
   Claude in an interactive session to create the issues from this CSV in the named Jira project. Claude cannot run the
   OAuth flow in a non-interactive session.
2. **Jira CSV import.** Jira settings > System > External System Import > CSV, pick the file, choose the project, map the
   columns as above.

## Where the content comes from

Every task description cites the decision (`docs/DECISIONS.md`), known issue (`docs/KNOWN_ISSUES.md`) or handoff note
(`docs/HANDOFF.md`) it was taken from, so the Jira ticket and the repo docs say the same thing. Update this CSV when a
new D- or KI- entry lands in either track, then re-import or ask Claude to sync the new rows only.
