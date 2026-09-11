# Phase 5 — Result Findings & Charts (stub)

## Status
Stub — scope statement only, not yet approved for implementation. Derived
from `docs/baseline-audit.md` §1 (nodes 5.13, 5.14, 5.15).

## Scope (one paragraph)

Build the two pipeline nodes Phase 0 found entirely absent from the
codebase — no partial implementation, no orphaned scaffolding, unlike most
other gaps found in this audit. Node 5.13 (generic result findings): a
registry of pure-Python check functions over the result rows (empty
result, outliers, threshold breaches, ties at the top of a ranking, large
result sets, stale data), each returning a finding or null, with
domain-specific checks loadable from per-scheme YAML — none of this exists
today (`app/annotations.py` is a few-shot/FK loader, not a findings module,
despite the name). Node 5.14 (chart generator): chart-type selection,
Vega-Lite (or equivalent) spec construction, and a rendering decision —
"chart" currently appears in the backend only as a comment and a
keyword-classifier token. Once both exist, wire them into `compose_response`
(`app/pipeline.py:2940`), which is otherwise implemented and already has a
stronger-than-specified numeric-faithfulness guard but currently has
nothing to attach for findings or chart spec.

## Not yet decided

- Charting library choice — the proposal recommends Vega-Lite/Altair, but
  since neither is a current dependency, this is a fresh choice, not a
  continuation of existing code.
- Whether findings and charts ship together or findings first (lower risk,
  text-only) with charts as a separate follow-up.

This stub requires its own approval and design review before work starts.
