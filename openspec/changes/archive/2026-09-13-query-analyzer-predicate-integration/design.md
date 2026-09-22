## Context

See `proposal.md` for the full investigation and motivation. The key facts
that shape this design:

- `app/pipeline.py`'s `_answer_data` (see `query-analyzer-consolidation`'s
  design.md for the full call sequence) computes `notes` — a list of
  disclosure strings surfaced verbatim in the composed answer — from
  `entity_result["notes"]`, then `premise_check`, then `defaults_engine`, in
  that order, immediately before `compose_response`.
- `app/query_analyzer.py`'s `analyze_query` already computes
  `analysis["ambiguous"]` from two sources: `entity_result["notes"]`
  (not-found mentions) via `_ambiguous_from_notes`, and the analyzer's own
  guided-JSON model call's `ambiguous_terms`. Both were merged into one flat
  list with no way to tell them apart.
- The not-found-mention half of that list is **already disclosed** — it
  came from `entity_result["notes"]`, which is already the first thing
  folded into `notes` above. Re-disclosing it via a second mechanism would
  show the user the same gap twice, worded slightly differently each time.

## Goals / Non-Goals

**Goals:**
- Make the analyzer's own newly-flagged (non-duplicate) ambiguities visible
  to the user, closing the "no downstream consumer of `analysis.ambiguous`"
  gap for at least one real case.
- Do this with zero new pause/interruption risk — an LLM-judged ambiguity is
  disclosed, never gates the answer.

**Non-Goals:**
- Touching any of the 8 hardcoded `_needs_*_clarification`-style predicates'
  own logic (see proposal.md for why 5 structurally can't consume `analysis`
  and 3 would only be made worse by it).
- Touching `app/clarification_engine.py` or its ~100 matchers — explicit
  product decision to avoid the separate, in-flight SME review on those
  files.
- A confidence threshold or product-tunable sensitivity for when an
  ambiguity is "worth" disclosing — the analyzer's prompt already caps
  `ambiguous_terms` at 2 entries and instructs the model to return an empty
  array when nothing is ambiguous; no additional filtering layer is added
  here. If this proves too noisy or too quiet in practice, tuning the prompt
  is a follow-on, not part of this change.

## Decisions

### 1. Provenance via an `origin` field, not a separate list

**Decision:** Add `origin: "entity_note"` (set in `_ambiguous_from_notes`) or
`origin: "llm"` (set where the model's own `ambiguous_terms` are appended)
to each entry in `analysis["ambiguous"]`, rather than returning two separate
lists.

**Why over alternatives:**
- *Alternative: two separate fields (`analysis.ambiguous` for entity notes,
  `analysis.ambiguous_new` for LLM-flagged ones).* Rejected — changes the
  shape `web/ai_query.html`'s existing renderer already consumes
  (`a.ambiguous.map(...)`) for no benefit; the renderer already ignores
  unknown keys on each entry, so `origin` is invisible to it and free.
- *Alternative: filter entity-note entries out of `analysis.ambiguous`
  entirely.* Rejected — the UI's "Gaps" chip display is a legitimate,
  separate consumer that benefits from seeing both kinds together (it's
  informational, not a disclosure-dedup problem); only the *disclosed note*
  path needs to distinguish them.

### 2. Disclosed note, not a new predicate or `ClarificationNeeded`

**Decision:** In `_answer_data`, after `defaults_engine`'s block (same
`notes` list, same point in the sequence), append one note per
`origin: "llm"` entry in `analysis["ambiguous"]`.

**Why:** This was an explicit product decision (see proposal.md) made
precisely because the alternative — a new hard pause — would introduce a
production-untested LLM signal as an interruption trigger, cutting against
this codebase's own stated bias toward under-firing on clarifications.
Disclosure carries none of that risk: worst case, an unhelpful or slightly
over-eager note appears in the answer text, which is easy to observe and
tune (or disable outright via a settings flag, matching every other
additive node in this codebase) without it ever having blocked anyone from
getting an answer.

### 3. No new settings flag

**Decision:** This behavior is gated by the existing
`settings.QUERY_ANALYZER_ENABLED` (if that's off, `analysis` is `None` and
the new note loop is a no-op) — no separate flag is added.

**Why:** The note-disclosure logic has no independent failure mode or cost
of its own (it's a few string-formatting lines over already-computed data,
not a new model call) — a dedicated flag would be a knob with nothing
distinct to turn off. If it needs a kill switch later without disabling the
whole analyzer, adding one then is a small, low-risk follow-up.

## Risks / Trade-offs

- **[Risk]** The LLM's `ambiguous_terms` judgment could be noisy (flagging
  things that aren't really ambiguous) or could word a note oddly.
  → **Mitigation**: this is a disclosed note, not a pause — worst case is a
  mildly unhelpful sentence in the answer, not a broken or blocked request.
  Observable in the audit trail (`app.query_audit.analysis`) for later
  tuning.
- **[Risk]** A future change to `_ambiguous_from_notes`'s regex or the
  model's `ambiguous_terms` schema could silently stop setting `origin`,
  making every entry look like a duplicate (or like new) by default.
  → **Mitigation**: covered by this change's test additions — the
  provenance value is asserted directly, not inferred.

## Migration Plan

No data migration. Two small, isolated code changes
(`app/query_analyzer.py`, `app/pipeline.py`), inert whenever
`QUERY_ANALYZER_ENABLED` is off or `analysis` comes back `None`. Rollback is
a plain revert.
