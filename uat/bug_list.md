# CM Elevate UAT — bugs found and fixed

## B1 Block chip: verifier/repair broke a correct block count
- **Symptom:** Bare block names that are also villages / constituencies (Umling 1130, Samanda 355, Mawkyrwat 162, Mawsynram 72): after the user taps 'block' the answer was wrong (OFF-002, OFF-007, OFF-010, OFF-026 shapes).
- **Root cause:** The block chip resumes the question as '…Umling, the block, not another area type'. The SQL verifier read that UI wording as a demand for a block-level restriction on a correct `lgd_block = 'UMLING'` query, and the repair added `entity_type = 'Block'`; on v_cm_elevate entity_type is the ROW's type (Village / Ward / Unresolved), never the asked level, so the count broke.
- **Fix:** (1) The verifier now sees the question without the level-chip tail (_c01_strip_chip_level), as the level is already in the resolved entities. (2) New deterministic CM Elevate SQL guard _cm_elevate_drop_area_level_entity_type drops any entity_type filter that is not a row type (same rule MGNREGA already had).
- **Files:** app/pipeline/common/c11_sql_verify_repair.py; app/pipeline/schemes/cm_elevate.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes: verifier prompt (all schemes); guard is CM Elevate only

## B2 Same-name villages: 'couldn't build a working query'
- **Symptom:** AMPANGGRE (Rongram / Rongara), NONGSDER (Bhoirymbong / Pynursla): the bot answered 'I understood the question but couldn't build a working query' (OFF-003 shared-name villages).
- **Root cause:** The resolver correctly found 2 same-name villages (J-10 twins, each to be answered). The 30B model put the village name in the district column (`lgd_district = 'NONGSDER'`); the twin guard rejected it and the repair returned the identical SQL three times.
- **Fix:** New deterministic rewrite _pin_missing_twin_codes: a simple query that filters none of the twin codes gets `village_code IN (all)`, the wrong district/block/name literal removed, and GROUP BY village_code, lgd_block, so each village is answered with its block.
- **Files:** app/pipeline/common/c10_sql_generation_and_rewrites.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (all village schemes; only fires on twin villages with no code in the SQL)

## B3 Tura Municipal Board answered 0
- **Symptom:** 'How many CM ELEVATE applicants are there in Tura Municipal Board?' -> 0 (true 105) (OFF-002).
- **Root cause:** v_cm_elevate stores the one board under two spellings, 'TURA MUNICIPAL BOARD' (28) and 'TURA MUNICIPAL BOARD-MUNICIPAL BOARD' (77). _cme_data_block mapped a town to its urban body only when exactly ONE stored spelling existed, so the unstored 'TURA' was kept.
- **Fix:** _cme_data_block now pins a stored spelling when there are several, and the new SQL rewrite _cm_elevate_urban_body_spellings widens `lgd_block = <one spelling>` to every stored spelling of that board.
- **Files:** app/pipeline/schemes/cm_elevate.py; app/pipeline/common/c11_sql_verify_repair.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** No (CM Elevate only)

## B4 Programme names not recognised
- **Symptom:** '… under Agriculture Response Vehicle in <district>', 'status distribution for Warehouse / Cinema Theatre' asked 'which scheme?' (OFF-006/007/008/016/021/023).
- **Root cause:** _CMELEVATE_ONLY_TERMS knew only the long forms ('PRIME agriculture response vehicle', 'warehouse scheme', 'cinema theatre scheme').
- **Fix:** The programme names as officers type them were added (agriculture response vehicle, response vehicle, cinema theatre, agro tourism, warehouse). Which CM Elevate dataset is still settled by the existing dataset choice.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** No

## B5 'Agro Tourism Villa' refused as off-topic
- **Symptom:** 'What is the status distribution for Agro Tourism Villa?' -> 'I don't have information about that' (OFF-016).
- **Root cause:** The edge layer's off-topic bank lists 'tourism' (flights / holidays); the programme name was not in the strong scheme-intent list that exits before it.
- **Fix:** CM Elevate programme names added to edge._SCHEME_STRONG.
- **Files:** app/edge.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (edge layer; only adds specific programme names)

## B6 'pending at level 1' read as a place
- **Symptom:** 'How many CM ELEVATE applications are pending at level 1?' -> 'I couldn't find a place called level' (OFF-018).
- **Root cause:** spelling.unresolved_place takes the words after 'at' as a place name; 'level' was not in its non-place word list.
- **Fix:** 'level', 'levels', 'hold' added to _NOT_A_PLACE.
- **Files:** app/spelling.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (unknown-place check; only stops these words being read as places)

## B7 Ward names asked 'block or constituency?'
- **Symptom:** 'William Nagar (MB) - Ward No.8' asked 'Williamnagar block or assembly constituency?' (OFF-003 wards).
- **Root cause:** The admin-level gate stands down when the text holds a longer name that is one village, but compared with a plain substring: the extractor's 'Williamnagar' is not a substring of 'William Nagar (MB) - Ward No.8'.
- **Fix:** The comparison is on letters and digits only (_c09_alnum).
- **Files:** app/pipeline/common/c09_resolve_entities.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (all schemes; truncated village mentions)

## B8 'across all financial years' on a scheme with no years
- **Symptom:** 'There are 2,624 CM ELEVATE applicants in Ri Bhoi across all financial years' — CM Elevate holds no year or date at all.
- **Root cause:** The question rewrite appends 'across all financial years' for every scheme; the composer repeated it.
- **Fix:** _finish_answer / _framed_fallback drop the phrase and add no period when every scheme in the answer has no time dimension (_SCHEME_DATA_YEARS = []).
- **Files:** app/pipeline/common/c12_answer_numbers.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (answer finishing; only for schemes with no years, i.e. CM Elevate)

## B9 Village-wise lists summarised, not listed
- **Symptom:** 'applicants under Piggery in each village of Umling' -> 'highest 69 in UMSHAKEN, lowest 1 in Amphrilling' with no per-village figures; framed lists in village-code order with codes digit-grouped ('2,77,694'); one village misspelt (OFF-026, H-B>V).
- **Root cause:** _cme_complete_list rebuilds an incomplete list only when the rows have ONE label column and <= 40 rows; village rows carry lgd_village_name + the same lgd_block on every row + village_code, and blocks have up to 107 villages, so the rebuild never fired.
- **Fix:** Code columns and labels that are the same on every row no longer count as labels; up to 200 rows; the rebuilt list is ordered by the figure, highest first.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** CM Elevate (CM Elevate Legacy's list check reads the same helper)

## B10 'Pending' rankings lost under the 'pending is not recorded' rule
- **Symptom:** 'Which CM ELEVATE programs have the highest number of pending applications?' -> only the statewide recorded figures (906 on hold), no ranking (OFF-019; OFF-020 the same for districts).
- **Root cause:** Since the ingestion team's 2026-10-26 ruling a 'pending' question is answered by the fixed workflow query with the recorded figures (on hold, file status): one statewide row, whatever grouping the question asked for.
- **Fix:** _cme_workflow_group: a 'which / each / highest / -wise' question about programmes / districts / blocks groups the recorded figures by that column; the answer lists the on-hold count per group, highest first, still labelled as the data-verification hold.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** No

## B11 Sector breakdown hid applications with no sector
- **Symptom:** 'How many CM ELEVATE applicants are associated with each sector?' -> Poultry 22, Dairy 7, Piggery 7, Goatery 1, silent on the 8,884 (99.6%) with no sector recorded (OFF-011).
- **Root cause:** The model wrote WHERE sector_id IS NOT NULL into the breakdown.
- **Fix:** _cm_elevate_sector_keep_unrecorded drops that filter from an each-sector breakdown (GROUP BY sector, positional too); the answer names the group '(not recorded)'.
- **Files:** app/pipeline/schemes/cm_elevate.py; app/pipeline/common/c11_sql_verify_repair.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** No

## B12 'Garo Hills region' asked which district / answered one district
- **Symptom:** 'How many CM Elevate applicants are there in the Garo Hills region?' paused 'which Garo Hills district?' (East Garo Hills 622 instead of the region's 3,476) (H-REG).
- **Root cause:** detect_region expands a region only on 'all / whole / every ...'; the word 'region' itself did not count.
- **Fix:** 'region' / 'regions' next to the name now means the whole region (its districts; same mapping as v_cm_elevate.region, Khasi includes Ri Bhoi).
- **Files:** app/entity_resolver.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (all schemes; region questions)

## B13 A made-up district answered as a sound-alike village
- **Symptom:** 'How many CM Elevate applicants are there in Gotham district?' -> '0 applicants for Gaoram village' (H-EDGE-invalid).
- **Root cause:** A district mention that is no district is retried as a village; the village resolver matched GAORAM by sound.
- **Fix:** _c09_labelled_other_level: a name the text labels as a district / block / constituency is not retried as a village; the existing unknown-place reply answers ('I couldn't find a district called ...').
- **Files:** app/pipeline/common/c09_resolve_entities.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (all schemes; only names followed by district / block / constituency)

## B14 Block x constituency questions failed
- **Symptom:** 'applicants in Mairang block that fall in the Mairang assembly constituency' -> 'couldn't build a working query'; 'Nongpoh Town Committee block ... Nongpoh constituency' -> 0 (H-BxAC).
- **Root cause:** (a) The verifier called the app's own documented constituency join (v_cm_elevate -> dim_geography on geography_key) 'prohibited' on every repair. (b) The constituency cleared the block slot and the model wrote lgd_block = 'NONGPOH', which the data does not store ('NONGPOH-TOWN COMMITTEE').
- **Fix:** (a) _cme_ac_verifier_complaint_is_false overrules join / entity complaints against the documented query (as Focus Legacy KI-369 and CM Elevate Legacy KI-381 already do). (b) _cm_elevate_urban_body_spellings maps an lgd_block literal the data does not store to the stored block the question names.
- **Files:** app/pipeline/schemes/cm_elevate.py; app/pipeline/common/c11_sql_verify_repair.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** No

## B15 'William Nagar constituency' asked block or constituency
- **Symptom:** 'How many CM Elevate applicants are there in William Nagar constituency?' paused 'Williamnagar block or assembly constituency?' (H-AC, H-ACxSt).
- **Root cause:** The level word was written, but the catalogue spells the name WILLIAMNAGAR, so the explicit-level matchers (exact catalogue name before the level word) missed it.
- **Fix:** _c09_level_after: the level word right after the name, names compared on letters only, settles the collision as if its chip were tapped.
- **Files:** app/pipeline/common/c09_resolve_entities.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (all schemes; collision gate)

## B16 Same-name village with its block named was summed with its twin
- **Symptom:** 'Mawiong village of Rambrai block' -> 17 (Rambrai 9 + Umling 8) (H-EDGE-dupvill).
- **Root cause:** The explicit word 'village' clears the other place slots, so the block named in the text no longer narrowed the two Mawiongs; J-10 then answered both, summed.
- **Fix:** Among same-name candidates, the one whose block the text names is taken.
- **Files:** app/pipeline/common/c09_resolve_entities.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (all village schemes)

## B17 Spelling pre-pass damaged ward names and 'across <district>'
- **Symptom:** 'William Nagar (MB) - Ward No.8' became 'Williamnagar) - Ward No.8' and asked block or constituency (OFF-003 wards); 'Dairy across South West Khasi Hills' became 'Dairy South West Garo Hills Khasi Hills' and paused (OFF-027).
- **Root cause:** app/spelling.py (D-093) rewrote the start of an exact village name to a block alias, and let a fuzzy district reading start on the word 'across'.
- **Fix:** A district / block correction is skipped where an exact longer village name starts; 'across', 'between', 'among', 'over', 'than' end a place span. With B7 (letters-only truncation check) the ward resolves.
- **Files:** app/spelling.py; app/pipeline/common/c09_resolve_entities.py  
- **Commit:** e3d7758 (v1 patch)  
- **Shared code:** Yes (spelling pre-pass, all schemes)

## B18 Comparison dropped a 0 combination
- **Symptom:** Compare Agriculture Response Vehicle and Dairy across East Jaintia Hills and East Khasi Hills: Dairy in East Jaintia Hills (0) not mentioned (C01-027-03).
- **Root cause:** GROUP BY returns no row for a programme x district pair with no applications; nothing stated it.
- **Fix:** _cme_compare_missing_zero: every asked pair without a row is stated as 0.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 3ee1dae  
- **Shared code:** No

## B19 Constituency questions with ac_name in upper case / a stray block
- **Symptom:** 'status distribution in West Shillong constituency' -> 'couldn't find any matching records' (C01-017AC-59).
- **Root cause:** The model wrote ac_name = 'WEST SHILLONG' (stored 'West Shillong') and added lgd_block = 'SHILLONG-MUNICIPAL BOARD' from the town name inside the constituency's.
- **Fix:** _cme_ac_name_case compares ac_name case-blind; _cme_block_inside_constituency drops a block filter named only inside '<AC> constituency'.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 77d05ef  
- **Shared code:** No

## B20 Same-name villages / top-N lists missing figures
- **Symptom:** 'Chandigre' -> highest/lowest only, Demdema's 7 missing; block spelt 'Dadengiri'; 'top 5 villages' -> figures for first and last only (C03, C10).
- **Root cause:** _cme_complete_list did not fire for J-10 twin rows or for 'top / bottom N' questions; village rows carry two varying labels.
- **Fix:** The rebuild also covers twin rows (listed by the data's block) and top/bottom-N lists (labelled by village).
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 3a092ce  
- **Shared code:** No

## B21 Tura MB split into two rows in grouped answers
- **Symptom:** 'Rongram vs Tura Municipal Board' compared 609 with 28 (true 105); West Garo Hills block list showed Tura twice (C09, C15).
- **Root cause:** GROUP BY lgd_block returns one row per stored spelling.
- **Fix:** The urban-body pass maps sibling spellings to one name in SELECT and GROUP BY.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 3a092ce  
- **Shared code:** No

## B22 Month / trend / date-range questions
- **Symptom:** 'Show the monthly totals of CM Elevate applications' -> 'couldn't build a working query'; 'in the last six months' -> the all-time total as if it were six months (C04-MONTHLY, C08).
- **Root cause:** v_cm_elevate has no date column; nothing answered a time ask that names no financial year.
- **Fix:** _cme_notime_query: a fixed answer 'A CM Elevate application carries no date …' with the recorded total for the place.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 3a092ce  
- **Shared code:** No

## B23 Same-name villages: verifier rejected the documented query
- **Symptom:** 'How many CM ELEVATE applicants are there in NONGSHILLIANG?' -> 'couldn't build a working query' (C03).
- **Root cause:** The LLM verifier raised entity / grouping complaints against WHERE village_code IN (<every twin>) on every repair.
- **Fix:** _cme_twin_verifier_complaint_is_false (inside the existing CM Elevate verifier overrule) discards them; measure complaints still stand.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 14ad455  
- **Shared code:** No

## B24 Several villages summed; invented year
- **Symptom:** '2 applicants in Nongshilliang (Mawpat block) and Nongshilliang (Mairang block)'; '16 … in Mawhati … for the year 2024' (C03).
- **Root cause:** A village_code IN-list without GROUP BY returns one combined figure; the composer added a year the applications data cannot hold.
- **Fix:** _cme_villages_per_village groups per village (unless a total is asked); _cme_drop_invented_year removes a year phrase the question never named.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 732a96c  
- **Shared code:** No

## B25 Unknown constituency / village in the wrong block / unnamed programme / block inside a constituency name
- **Symptom:** 'El Dorado constituency' -> '0 … the data records zero' (C14-INV-17); 'MAWBRI village of Mawkyrwat block' -> Mawbri of other blocks (C14); 'Chief Minister's Elevate programme' -> Green Taxi, 1 (C17-09); 'West Shillong constituency' -> 'couldn't build a working query' (C01-017AC-59).
- **Root cause:** No check that a filtered constituency exists; the asked block not compared with the answered villages' blocks; a single programme equality the question never named kept; 'Shillong' inside 'West Shillong constituency' resolved as a block and demanded by the missing-filter guard.
- **Fix:** _cme_unknown_constituency; _cme_village_not_in_named_block / _cme_village_code_not_in_named_block (0 for the village asked); _cm_elevate_unasked_programme_filter covers '='; _cme_block_only_in_constituency drops that block.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 14ec7f9, af54bf9  
- **Shared code:** No

## B26 Repeated GROUP BY key hid zero programmes
- **Symptom:** '… in North Garo Hills under Warehouse and Sericulture & Weaving?' (both 0) -> 'couldn't find any matching records' (C01-009-05).
- **Root cause:** GROUP BY scheme_name, scheme_name made _cme_asked_programmes return nothing, so the KI-182 all-zero answer did not fire.
- **Fix:** _cme_dedupe_group_by in the CM Elevate SQL pass.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** d7b90f5  
- **Shared code:** No

## B27 Verification counts / twin LIMIT (found in the final run)
- **Symptom:** 'completed data verification in Ri Bhoi' -> 2,039 only, non-verified 585 missing (C01-022-06); 'MASSAR' (two villages) -> one village, Pynursla's 5 cut off by LIMIT 1 (C03-ALONE-massar).
- **Root cause:** The model counted only data_verified = 'Valid'; the per-village twin query carried LIMIT 1.
- **Fix:** _cme_verification_split + _cme_verification_figures (verified / not verified / total, each stated, with the rate); _cme_twin_limit drops a LIMIT below the number of villages asked.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 8b8f2f0  
- **Shared code:** No

## B28 Financial-year question on the applications data paused on Legacy (D1)
- **Symptom:** 'How many CM Elevate applicants were there in Adokgre block in FY 2017-18?' -> 'For CM Elevate Legacy, data is available only for 2024-25, 2025-26 … select one' (994 tests: C04-FY, C06).
- **Root cause:** Dataset-choice rule 1 (2026-10-22) pinned any financial-year word to CM Elevate Legacy; D-090 (2026-10-29) says application words mean the applications dataset unless MONEY words are present, and a year is not money.
- **Fix:** _cm_elevate_dataset_choice: a single named year + applicant/application words + no money word stays on the applications data; _cme_notime_query answers with the no-date fact and the recorded total. A breakdown BY year (each year, year-wise) and any money word still go to Legacy.
- **Files:** app/pipeline/schemes/cm_elevate.py  
- **Commit:** 882879d, 1f1ab9c  
- **Shared code:** no

## B29 Ward and village names broken by the spelling pre-pass (N1, N4)
- **Symptom:** 'Ladthalaboh East - Ward No.1' -> East Garo Hills (622, true 6); 'Kenches Trace - Ward No.23' -> 'couldn't find Kenches' / 'Kenches tranche'; 'CENTRE VILLAGE' -> Kentra (5, true 4).
- **Root cause:** _normalise read a district inside a ward name that starts earlier; _domain_word corrected real words (trace, account) to vocabulary words; _village_at corrected a stored one-word name (CENTRE, left out of the index by D-059) by sound; unresolved_place took the start of an exact ward name as an unknown place.
- **Fix:** Exact ward / village names are left whole (look-back + numbered-name skip); 'account' / 'trace' are never typos; entity_resolver.is_stored_village_name guards CENTRE; the unknown-place check skips an exact stored name.
- **Files:** app/spelling.py, app/entity_resolver.py  
- **Commit:** 7f9d8f7  
- **Shared code:** YES — spelling pre-pass of every scheme; full unit suite + 14 scripts pass

## B30 Applicants' bank account / Aadhaar numbers not refused (N3)
- **Symptom:** 'List the CM Elevate applicants' bank account numbers in West Garo Hills.' -> sanctioned amounts per application number from Legacy, no refusal (C11-NAME-5).
- **Root cause:** _pii_listing only knew name / phone / address fields; and the spelling pre-pass had turned 'account' into 'amount' before the guardrail ran.
- **Fix:** _PII_ID_FIELDS (account, aadhaar, ifsc, pan, passport) + number words beside applicant / beneficiary words -> privacy_records refusal; 'account' no longer a typo of 'amount'.
- **Files:** app/guardrails.py, app/spelling.py  
- **Commit:** 4bf022f, 7f9d8f7  
- **Shared code:** YES — guardrail of every scheme ('bank accounts opened under PMJDY' is still answered)

## B31 Four Shillong constituencies answered as statewide
- **Symptom:** 'How many CM Elevate applicants are there in East Shillong constituency?' -> 'couldn't find an assembly constituency called East Shillong … statewide figure' (C12-AC-east_shillong; also North / South / West Shillong).
- **Root cause:** CM Elevate borrows MGNREGA's constituency catalogue, which omits AC 16-19 (urban Shillong, no MGNREGA rows). CM Elevate holds applications in all four.
- **Fix:** assembly_constituency_supplement in cmelevate_entity_resolver.yaml (4 entries) + resolver support for a <dim>_supplement that is ADDED to the borrowed shared catalogue (a first attempt as a full catalogue broke the block/constituency collision checks for every other AC and the William Nagar / Gambegre answers — replaced before the final run).
- **Files:** data/cm_elevate/cmelevate_entity_resolver.yaml, app/entity_resolver.py  
- **Commit:** 176fe54, 2952b14  
- **Shared code:** entity_resolver gains the supplement hook; only CM Elevate uses it

## B32 Invented short village name corrected to a real one
- **Symptom:** 'Asgard village' -> 'Showing results for Askara … 0 applicants for Askapara' instead of 'not found' (C14-INV-14).
- **Root cause:** _village_at accepted a sound-key match two edits away for a 6-letter name.
- **Fix:** A name of up to 6 letters is rewritten only for ONE plain-letter edit; longer names keep the sound-key allowance.
- **Files:** app/spelling.py  
- **Commit:** 67a3ac0  
- **Shared code:** YES — spelling pre-pass; spelling unit tests pass

## Commits on uat-cm-elevate-exhaustive (vs Main)
```
9253603 Spelling pre-pass: an exact village name that ENDS on the corrected word is left whole ("POMLAKRAI RNGI SHYLLONG" lost its last word to the Shillong block; UAT C02-CNT-278328)
2edd11a Spelling: a short typed name (up to 6 letters) is read by sound only when its plain spelling is one edit from the village — in village_matches, so the resolver and the pre-pass agree ("Asgard village" -> not found; UAT C14-INV-14)
67a3ac0 Spelling pre-pass: a short "<name> village" is corrected only for one plain-letter edit ("Asgard village" was read as Askara; UAT C14-INV-14)
2952b14 Entity resolver: a scheme may SUPPLEMENT a borrowed shared catalogue (<dim>_supplement); CM Elevate adds the four Shillong constituencies on top of the borrowed list instead of replacing it (collision checks kept)
176fe54 CM Elevate resolver: the four urban Shillong constituencies (AC 16-19), missing from the borrowed MGNREGA catalogue, so "East Shillong constituency" was answered as statewide
e067362 CM Elevate: a breakdown by financial year (each year, year-wise) stays on Legacy; only a single named year on an applications question gets the no-date reply
e196cba UAT: C12 turn 3 expects the on-hold group (D2), zero-village tests skip same-block twin names (D4), refusal phrases R9 (D3)
4bf022f Guardrails: requests for applicants' bank account / Aadhaar / ID numbers are refused as personal records (UAT N3)
7f9d8f7 Spelling pre-pass: exact ward / village names left whole (Ladthalaboh East - Ward No.1, Kenches Trace - Ward No.23), CENTRE VILLAGE not corrected to Kentra, account/trace not typos (UAT N1, N4)
882879d CM Elevate: an applications question with a financial year and no money word stays on the applications data and gets the no-date reply (D-090 over rule 1; UAT D1)
e0eeea8 UAT: final results, report, patch, bug list, disputes, needs-review, no-impact proof
c206e1f CM Elevate: a district / block literal beside a list of village codes is dropped (C03-ALONE-mawlieh)
8b8f2f0 CM Elevate: a data-verification count returns verified / not verified / total and states each (O1, OFF-022); a per-village query keeps every village asked (O2, LIMIT 1)
d348482 CM Elevate: generic place words (ward, village, municipal board, town committee) no longer count as naming a row, so a ward list missing a figure is rebuilt (C01-026-35)
25462ea CM Elevate: the village-in-the-named-block check fires only on 'in <village> village of <block> block' (regression on 'each village of <block>')
d7b90f5 CM Elevate: a repeated GROUP BY key is dropped, so programmes with no applications are still stated as 0 (C01-009-05)
4f623a2 UAT: disputes D4, needs-review N3
af54bf9 CM Elevate: a village asked in a block where its namesake has no applications is answered 0, even when the SQL picked the namesake of another block
14ec7f9 CM Elevate: unknown constituency said plainly; a village asked in a block that holds none of its applications answered 0; an unnamed single-programme filter dropped; a block named only inside '<name> constituency' is not a block filter
732a96c CM Elevate: several villages in one query answered one row each; a year the question never named is removed from the answer
14ad455 CM Elevate: the verifier's entity complaints against the documented same-name-village query are discarded (C03 'couldn't build a working query')
5e19c1e UAT: chip picks prefer the village chip for village tests; disputes D1-D3; needs-review N1 (ward spelling)
3a092ce CM Elevate: same-name villages and top/bottom-N lists rebuilt with every figure; Tura MB spellings merged in grouped results; month/trend/date asks answered 'no date' with the total
77d05ef CM Elevate: ac_name compared case-blind; a block named only inside the constituency's name is dropped (C01-017AC-59)
3ee1dae CM Elevate: a programme x district comparison states every asked pair with no applications as 0 (C01-027-03)
2da71cb UAT: reduced matrix (4,837) per the 7 AM plan; decisions log of rule changes
88a5724 UAT: exhaustive matrix generator, resumable runner, scheme docs
e3d7758 CM Elevate UAT v1: the CM Elevate fixes from the main folder (B1-B17), CM Elevate hunks only
```
