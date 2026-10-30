# Open failures on the frozen final code (d348482) — not disputed, not shared-code

## O1 — C01-022-06 (OFF-022, Ri Bhoi): non-verified count left out (model variance)
Final run answer: "2,039 applicants have completed data verification in Ri Bhoi." — the sheet asks for verified AND
non-verified counts (and the rate). The same question passed in 4 earlier runs on the same code path with
"2,039 … 585 have not been verified … 77.7%". The composer sometimes drops the second figure.
Proposed CM Elevate fix (not applied, code frozen for the final run): in `_cm_elevate_answer_guarantees`, for a
"completed data verification" question, append "Not verified: <total - valid>; verified rate <x>%" when the
non-verified figure is not stated (the query already returns it, or one extra COUNT on the same filter).

## O2 — C03-ALONE-massar: per-village twin query ended `LIMIT 1`
SQL (logged): `SELECT village_code, <block>, COUNT(DISTINCT request_id), lgd_village_name FROM curated.v_cm_elevate
WHERE village_code IN (276939, 278914) GROUP BY … LIMIT 1` -> one row (Mawthadraishan 1); Pynursla's 5 cut off.
Read-only check: the same SQL without LIMIT returns both rows (276939 → 1, 278914 → 5).
Proposed CM Elevate fix (not applied, code frozen): in the CM Elevate SQL pass, a query filtering N village codes
and grouped by village_code drops a LIMIT below N (as `sql_ast.widen_village_filter` already does for the J-10
rewrite it makes).
