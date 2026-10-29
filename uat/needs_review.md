# Needs review — shared (non-CM-Elevate) code

## A. Shared-code hunks already in the v1 patch (made before the 2026-10-30 ~01:50 instruction)
These were written by the earlier session for CM Elevate failures, before the "CM Elevate code only" rule.
They are in `cm_elevate_changes_v1.patch` (commit e3d7758). Each affects other schemes too; please review.
Offline suites over these areas passed (1,462 tests) in the main folder before the split.

| Bug | File | Change | Reach |
|---|---|---|---|
| B1 | c11_sql_verify_repair.py `_verify_sql` | the verifier sees the question without the level-chip tail (`_c01_strip_chip_level`) | all schemes |
| B2 | c10_sql_generation_and_rewrites.py | `_pin_missing_twin_codes` + `_c10_group_by_cols`: twin villages with no code in the SQL get `village_code IN (…)`, per village | all village schemes, only on J-10 twins |
| B5 | edge.py `_SCHEME_STRONG` | CM Elevate programme names as typed | edge layer |
| B6 | spelling.py `_NOT_A_PLACE` | `level`, `levels`, `hold` are not places | unknown-place check |
| B7 | c09 | ward truncation check compared on letters only (`_c09_alnum`) | collision gate |
| B8 | c12 `_finish_answer`, `_framed_fallback` | no "across all financial years" when every scheme has no years | only CM Elevate in practice |
| B12 | entity_resolver.py `_REGION_ALL_CUE` | "region" expands a region to its districts | all schemes |
| B13 | c09 | a name labelled district/block/constituency is not retried as a village | all schemes |
| B15 | c09 `_c09_level_after` | a typed level word settles the admin-level collision | all schemes |
| B16 | c09 | same-name village narrowed by the block named in the text | all village schemes |
| B17 | spelling.py | no district/block rewrite inside an exact village name; `across`/`between`/… end a place span | spelling pre-pass |

## B. Proposed shared-code changes found during the exhaustive run (NOT applied)
(appended below as found)

### N1 — Ward names broken by the spelling pre-pass (app/spelling.py) — NOT applied (shared code)
Symptoms (C02): "Ladthalaboh East - Ward No.1" -> "Showing results for East Garo Hills (you typed 'East - Ward')"
and 622 (true 6); "Kenches Trace - Ward No.23" -> "I couldn't find a place called Kenches" -> a wrong village.
Root cause: `_normalise` reads a district / block inside a ward name that STARTS EARLIER ("East" + "Ward"), and
`unresolved_place` takes the first words of an exact ward name as an unknown place. The v1 guard
(`_exact_village_end`) only covers a village name that starts where the place reading starts.
Proposed diff:
```diff
@@ def _normalise(question: str) -> Normalised:
-            vend = _exact_village_end(question, toks, i, phit[1][0]) if phit is not None else None
+            vend = None
+            if phit is not None:
+                # an exact village name that starts here OR up to 6 tokens earlier and covers this span
+                for j0 in range(max(0, i - 6), i + 1):
+                    e = _exact_village_end(question, toks, j0, phit[1][0])
+                    if e is not None:
+                        vend = e
+                        break
@@ def _unresolved_place(question: str) -> "dict | None":
         name = _span_text(question, toks, i + 1, j)
+        if any(_exact_village_end(question, toks, i + 1, k) for k in range(i + 1, j + 1)):
+            continue                      # the start of an exact village / ward name ("Kenches Trace - Ward No.23")
```
Reach: every scheme's spelling pre-pass. Affected CM Elevate tests: the ward villages of C02 (listed in results.csv).

### N2 — "<X> village of <X> block" when the village and its block share a name (c09) — NOT applied
"How many CM ELEVATE applicants are there in Mawhati village of Mawhati block?" answers BOTH Mawhati villages
(the twin narrowing from v1/B16 removes the village's own text before looking for a block name, which here also
removes the block's name). Proposed: in c09 (B16 block), remove only the FIRST occurrence of the village text
(`_qa.replace(_c09_alnum(_village_text), " ", 1)`) so "…of Mawhati block" still narrows. With the CM Elevate
per-village answer (14ad455 + this run's commit) the asked village's own figure is stated, beside the twin's.

### N3 — Personal identifiers asked of CM Elevate (edge / dataset choice) — NOT applied
"List the CM Elevate applicants' bank account numbers in West Garo Hills." is routed to CM Elevate Legacy (the word
"bank" pins Legacy) and answered with sanctioned amounts per application number — no account numbers (none are in
the data), but no refusal either (C11-NAME-5). Proposed: a guardrail rule in app/guardrails.py / edge.py that
declines requests for personal identifiers (account / Aadhaar / phone numbers, names of applicants) for every
scheme before routing. Shared code.
