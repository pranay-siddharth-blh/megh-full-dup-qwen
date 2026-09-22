## 1. Provenance tagging

- [x] 1.1 In `app/query_analyzer.py::_ambiguous_from_notes`, tag each
      produced entry with `origin: "entity_note"`.
- [x] 1.2 In `analyze_query`'s LLM-`ambiguous_terms` merge loop, tag each
      appended entry with `origin: "llm"`.
- [x] 1.3 Extend `tests/test_query_analyzer.py` to assert `origin` on both
      kinds of entry.

## 2. Disclosed-note wiring

- [x] 2.1 In `app/pipeline.py::_answer_data`, after the `defaults_engine`
      block (same `notes` list, before `compose_response`), append one
      disclosure string per `origin: "llm"` entry in
      `analysis["ambiguous"]`.
- [x] 2.2 Confirm `origin: "entity_note"` entries are never disclosed a
      second time by this new loop (they're already in `notes` via
      `entity_result["notes"]`).
- [x] 2.3 Extend `tests/test_query_analyzer_integration.py` with an
      end-to-end check: a mocked `query_analyzer.analyze_query` returning an
      `origin: "llm"` ambiguous entry results in that note appearing in the
      final `answer`/`notes`-derived output; an `origin: "entity_note"` entry
      does not produce a second, duplicate note.

## 3. Regression sweep

- [x] 3.1 Re-ran the full `tests/` suite (29 files, one more than
      `query-analyzer-consolidation`'s sweep — `tests/test_clarification_
      engine.py` unaffected). 27/29 pass; the same 2 pre-existing,
      unrelated environmental gaps as the prior change
      (`smoke_restructure.py` needs a live server, `test_langgraph_
      followup.py` needs the optional `langgraph` package) — neither
      touches `app/query_analyzer.py` or `app/pipeline.py`.
- [x] 3.2 Updated `docs/baseline-audit.md` §5.2 with a dated note covering
      this change: what's now live, what's structurally out of reach, and
      what's deliberately unattempted, and why.
