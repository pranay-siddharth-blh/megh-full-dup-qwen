## Status

Proposal — not yet approved, no code written. Scopes the remaining gap in
Grant Thornton §5.13 (generic result findings): findings are computed and
attached to the `/api/query` response, but never reach an end user. Re-verified
fresh against the running code (not taken from `docs/baseline-audit.md` at
face value) before writing this.

## Why

The user asked for §5.13 "done end to end." Re-checking the current code
against the canonical `openspec/specs/result-findings/spec.md`, every one
of that spec's 7 requirements is implemented and passing
(`tests/test_findings.py`, re-run this session: all checks pass). That
spec's own scope, however, stops at "an additive `findings` field in the
`/api/query` response" — it says nothing about a human ever seeing that
field's contents. Re-verified two places that would surface it and found
neither does:

- `app/pipeline.py:3537` (`compose_response(...)`) runs **before**
  `result_findings` is computed at line 3545-3550, so findings can't reach
  the composed answer prompt even if a future change wanted them to. The
  composer's prose today never references findings.
- `web/ai_query.html` — grepped for `findings`: zero matches. The frontend
  reads `response.data` and `response.chart_type` (`buildAnalytics`,
  line 2480) but never `response.findings`. It's rendered nowhere.

This matches `docs/baseline-audit.md`'s own §5.15 note (line 49): *"findings/
chart_type now attached to the response... not yet routed into the composed
answer's own prose"* — already known, not a new discovery, just not yet
turned into a proposal until now.

**Design choice — render as a separate UI element, do not route into the
LLM composer prompt.** `compose_response` (`pipeline.py:3167-3317`) carries
substantial, hard-won guardrails around what the LLM is allowed to say
(`_answer_numbers_faithful`, a strict-retry path, a deterministic fallback)
specifically because free-text LLM prose over numeric data is failure-prone.
Findings are already fully-formed, human-readable strings
(`findings.py`'s `_finding()` messages) — piping them through another LLM
call to get paraphrased back into prose adds a new faithfulness-risk surface
for no benefit. The established precedent in this codebase for an additive,
structured field is `chart_type`: attached to the response, rendered by the
frontend as its own UI element, never merged into the answer text. This
proposal follows that same precedent for `findings` — a distinct block in
the chat bubble, styled by `severity`, positioned after the answer/chart and
before the SQL disclosure (mirrors `buildSqlDisclosure`'s placement pattern
at `ai_query.html:2494`).

## What Changes

- **No backend change.** `findings.evaluate(...)`, its wiring in
  `pipeline.py`, and the `findings` field on the response are already
  correct and tested — confirmed by re-running `tests/test_findings.py`
  this session (all checks pass). Nothing here is re-implemented.
- **`web/ai_query.html`**: add a `buildFindings(findings)` renderer
  (modeled on `buildSqlDisclosure`, `ai_query.html:2415-2425`) that turns
  `response.findings` (a list of `{type, severity, message, column,
  row_ref}` dicts) into a small block of severity-styled lines using the
  existing CSS tokens already defined in `:root`
  (`--amber`/`--amber-bg` for `warning`, `--blue`/`--blue-bg` for `info` —
  no new color tokens needed, `ai_query.html:16-27`). Wire it into
  `addBotRich` (`ai_query.html:2476-2503`) alongside `analytics.html` and
  `sqlBlock`. An empty `findings` list renders nothing (no empty box).
- **No new severities beyond what `findings.py` already emits**
  (`info`, `warning`) — the renderer maps only those two; an unrecognized
  future severity value falls back to a neutral/default style rather than
  breaking.
- **Manual QA**, per this project's own standing instruction to verify UI
  changes in a real browser: start the dev server, ask a question that
  exercises each finding type (empty result, a tie, a large result set —
  threshold-breach is not exercisable today since no scheme has an
  authored thresholds file, see Explicitly Out of Scope) and confirm the
  block renders, is styled by severity, and an ordinary no-findings answer
  shows no empty block.

## Explicitly Out of Scope

- **Routing findings into `compose_response`'s LLM prose.** Rejected above
  — the separate-UI-element design is the lower-risk, precedent-following
  choice. Revisit only if product explicitly wants findings woven into the
  natural-language answer itself.
- **Authoring real `*_findings_thresholds.yaml` files for any scheme.**
  Still SME-gated, still blocked, unrelated to this proposal — see
  `findings.py`'s module docstring and the prior phase-4 proposal's task
  2.3. Nothing here depends on it; the threshold-breach finding type is
  handled by the same generic renderer as every other finding type, it
  simply won't fire in practice until that YAML exists.
- **Any other pipeline node.** This proposal touches only the
  frontend-rendering gap in §5.13/§5.15's boundary; it does not re-open
  §5.14 (chart spec, already wired) or any other node.

## Impact

- Affected files: `web/ai_query.html` only (one new render function, one
  wiring call, a handful of CSS rules reusing existing tokens).
- No API contract change — `findings` is already on the response; this
  only makes an already-shipped field visible.
- No database, migration, or backend behavior change.
- Reversible: a pure frontend addition behind no feature flag; removing
  the render call reverts to today's behavior exactly.
