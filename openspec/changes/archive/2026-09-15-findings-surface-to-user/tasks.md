## 0. Re-verification (done before writing this proposal)

- [x] 0.1 Re-read `openspec/specs/result-findings/spec.md` — confirmed every
      requirement is backend/API-response scoped, none mention UI or
      composer prose. Confirmed `app/findings.py` + its wiring at
      `pipeline.py:3541-3580` satisfy all 7 requirements as written.
- [x] 0.2 Re-ran `tests/test_findings.py` (`python tests/test_findings.py`) —
      all checks pass ("ALL FINDINGS CHECKS PASSED").
- [x] 0.3 Grepped `web/ai_query.html` for `findings` — zero matches, confirming
      the field is genuinely never rendered, not a stale claim.
- [x] 0.4 Read `compose_response` (`pipeline.py:3167-3317`) and confirmed
      `result_findings` is computed after `compose_response` is called
      (line 3537 vs. 3545), so today's code structurally cannot be routing
      findings into the composed prose even implicitly.

## 1. Frontend renderer (`web/ai_query.html`)

- [x] 1.1 Added `buildFindings(findings)` next to `buildSqlDisclosure`
      (`ai_query.html:2415-2440`): empty/missing `findings` returns `''`;
      otherwise renders each finding's HTML-escaped `message` in a
      `.finding-item`, with a `.finding-info`/`.finding-warning` class
      added only for those two recognized severities — anything else
      (or a missing severity) falls back to the neutral base class rather
      than throwing.
- [x] 1.2 Added the CSS (`ai_query.html`, right after `.sql-copy.copied`):
      `.findings-block`/`.finding-item`/`.finding-info`/`.finding-warning`,
      reusing the existing `--blue`/`--blue-bg`/`--amber`/`--amber-bg`/
      `--hover`/`--line`/`--ink-2` tokens already defined in `:root` — no
      new colors added.
- [x] 1.3 Wired `buildFindings(response.findings)` into `addBotRich`
      (`ai_query.html:2476-2505`): computed alongside `sqlBlock`, inserted
      into the bubble's innerHTML between `analytics.html` and `sqlBlock`
      (after the answer/chart, before the SQL disclosure, matching the
      proposal's placement choice).
- [x] 1.4 **Could not do full live-browser QA against a real `/api/query`
      round-trip** — `docker compose ps` failed ("failed to connect to the
      docker API... dockerDesktopLinuxEngine... cannot find the file
      specified", Docker Desktop not running in this sandbox), same
      unreachable-DB constraint already on record in this project's memory
      for this dev environment. Did not claim browser verification that
      didn't happen.
      **What was actually verified instead:** extracted `escapeHTML` and
      `buildFindings` directly out of the shipped `web/ai_query.html` (not
      a re-typed copy) and ran them under Node against edge cases:
      - empty list / `undefined` / `null` → `''` (no empty block) — PASS
      - one `info` + one `warning` finding → correct
        `finding-info`/`finding-warning` classes, both messages present — PASS
      - an XSS-attempt message (`<img src=x onerror=alert(1)>`, `&`, `"`,
        `'`) → fully HTML-escaped in the output, no raw markup — PASS
      - an unrecognized severity (`"critical"`) and a finding with no
        `severity` key at all → both fall back to the neutral base class,
        no class-name injection, no throw — PASS
      This confirms the rendering logic and escaping are correct but not
      on-screen CSS appearance or the real end-to-end `/api/query` →
      render path — that needed a working local DB/Docker setup this
      sandbox doesn't have.
      **Closed out 2026-09-15: the user verified in a real browser on
      their own machine** (`uvicorn` + `web/ai_query.html` against a live
      DB) and confirmed findings render correctly. No gap remains.

## Regression sweep (run after the group above, record actual results here)

- [x] Ran `python tests/test_findings.py`, `python tests/test_response_composer.py`,
      `python tests/test_chart_spec.py` — all three: **ALL CHECKS PASSED**,
      exit code 0 each. Confirms this change (frontend-only) touched no
      backend behavior; no backend file was edited by this change.
