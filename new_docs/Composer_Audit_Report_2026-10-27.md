# Composer Layer Audit — 2026-10-27

**Question asked:** why do data answers carry extra, unrequested information, and why is the composer's
wording often poor?
**Scope:** the data-answer path after the SQL runs: `compose_response`
(`app/pipeline/common/c13_compose_and_data_stages.py:33`), the answer-shape module
(`c12_answer_shapes.py`), the fallbacks and finishing pass (`c12_answer_numbers.py`), the per-scheme
answer writers and guarantees, and the SQL prompt rules that decide which columns reach the composer.
**Method:** code reading (all claims cite file:line) plus the 43 answered questions of the latest saved
NL→SQL eval run (`tests/nl2sql_eval/results/2026-10-27_1337_run-query-types-appname-2026-10-27.json`).
No code was changed. **Not done:** live questions (the office VPN was down); the eval file stores answers
cut at 400 characters, so long answers were judged on their first 400 characters only.

Labels: **VERIFIED** = read in code or in a saved answer. **INFERRED** = reasoned from evidence.

---

## 1. Summary

The extra information is mostly **by design, not by model mistake**. Five layers each add figures on
their own, and none of them knows what the user actually asked for:

1. The **SQL prompt and few-shots** tell the model to return companion columns (counts beside money,
   three-way "disbursed", four Focus Legacy measures) — and nothing says "return only what was asked".
2. The **composer is forced to state every column** it receives (`dropped_metric` retry, "profile" rule).
3. The **answer-shape rules make extra lines mandatory**: every ranking ends with a "#1 is N ahead" line,
   every breakdown opens with a total and % shares, every trend adds % change, peak and lowest.
4. **Code appends sentences** after the composer (scope tails, caveats, notes, guarantees).
5. **Per-scheme writers and fallbacks** print fixed bundles of measures.

Separately, the composer makes **real errors the guards do not catch**, because the faithfulness check
only verifies that each number *exists* in the data — not that it is attached to the right claim, unit
or sentence. And there is **no test that grades answer text**: the eval scores the SQL rows, so all the
answers below were scored "correct".

Of the 43 answers checked: **15 clean**, **20 with unrequested content**, **8 with a wrong or misleading
statement** (§3).

## 2. Root causes

### RC-1 No "answer only what was asked" rule anywhere — VERIFIED
- The SQL prompt (`prompt_builder.build_sql_prompt`, `app/prompt_builder.py:459-483`) has no rule to select
  only the asked measures. The one narrow exception is "pending" (`schema_context.py:308`).
- The composer prompt (c13:78-110, 165-194) never says "do not add figures the question did not ask for".
  It says the opposite: "Put the supporting figures in a separate, plainly listed second sentence" (c13:94).

### RC-2 The SQL is told to return companion columns — VERIFIED
`app/schema_context.py`:
- :902 Focus Legacy — "EVERY money SELECT must carry SUM(no_of_pg_members) beside it"
- :1115-1116 CM Elevate Legacy — "A bare 'disbursed' … returns subsidy_cr, loan_cr and total_disbursed_cr
  side by side, with sanctioned_cr beside them"
- :1169 — "record count beside any money ranking"; :1172 — sanction rate "with records and sanctioned_records"
- :713 CM Elevate — "always show the count alongside any percentage"
- :316-327 MGNREGA men — "returns all three columns so the answer can show its working"
- :543 Focus Plus — payments and beneficiaries "both, labelled, when the question is ambiguous"

Few-shot examples teach it too — share of examples whose SQL selects 2+ measures (upper bound, not
filtered to one-measure questions): CM Elevate Legacy (loaded v2 bank) **64%**, Focus Legacy **48%**,
Focus Plus **41%**, CM Elevate 25%, PMAY-G 24%, MGNREGA 13%. Examples: "What is the total amount
disbursed under Focus Legacy?" → amount, memberships, payments; "What is the total amount sanctioned?"
(CM Elevate Legacy) → sanctioned_cr, records.

Code rewrites add measures: `_focus_legacy_beneficiary_four_measures` (`schemes/focus_legacy.py:731-754`)
replaces the SELECT of any Focus Legacy beneficiary total with payments, producer groups, memberships and
amount; `_pmay_sql_issue` (`schemes/pmay_g.py:1235-1243`) demands houses, sanctioned, released, remaining.

### RC-3 The composer must state every column it is given — VERIFIED
- `dropped_metric` (c13:229-230): a one-row result with 2+ metrics whose answer skips one → strict retry
  "State EVERY value in the result" (c13:251), then the deterministic fallback.
- "profile" shape rule: "report EVERY figure in the row" (`c12_answer_shapes.py:361-363`).
- So RC-2's companion columns **always** reach the user. This guard was added for a real bug (a
  cross-scheme answer dropping PMAY-G), but it cannot tell an asked figure from a companion one.

### RC-4 The answer shapes make extra lines mandatory — VERIFIED
`_SHAPE_GUIDE` (`c12_answer_shapes.py:359-409`) and `_shape_facts` (:244-352):

| Shape | Always required, whatever the question |
|---|---|
| ranking | open with "#1 leads with…", close with "how far #1 leads #2" |
| breakdown | open with the total and item count, then largest and smallest **with % share** |
| trend | first→last change **and % change**, then **peak and lowest** |
| compare | the difference **and %**, up to 3 measures |
| profile | every figure in the row |

The shape is chosen from the SQL (ORDER BY / LIMIT) and a few words, so a **filter** question ("districts
with cost above ₹400", "blocks with over 1,000 houses") becomes a "ranking" with "leads" and "ahead"
lines (MG-11, PM-13).

### RC-5 The shape measures the first numeric column, not the asked one — VERIFIED
`_answer_shape` uses `metrics[0]` for trend, compare and breakdown (c12_answer_shapes.py:192-195). CE-11
asked for each scheme's **online share %**; the SQL returned total, online, percentage, so the answer
ranked schemes by **total applications**. Same bug class as the VS card fixed today (KI-437).

### RC-6 Code appends sentences after the composer — VERIFIED
- `_finish_answer` (`c12_answer_numbers.py:626-666`, runs twice: c13:312 and the finalize node): a
  one-row answer that does not literally name the scheme AND place gets a tail sentence. Bugs:
  - `' for ' + period` with period "across all financial years" → **"This is the PMAY-G figure for across
    all financial years."** (PM-01, CL-03, CL-09)
  - The scheme check is literal: "CM Elevate sub-scheme" does not contain "CM Elevate Legacy", so a tail
    is added to an answer that already said it (CL-03, CL-09).
  - It repeats a period the sentence already gave (PM-01 says "across all financial years" twice).
- Guarantees stage (c13 ~2630-2711) and scheme guarantees add caveat/notes lines: Focus Plus "not a loan…",
  MGNREGA women "not recorded at source…", Focus Legacy membership note (`focus_legacy.py:691`), latest-year
  line, region note, MGNREGA complete-list line (`mgnrega.py:1795`), CM Elevate "Differences: …"
  (`cm_elevate.py:1960`), and others. Many exist for correctness; none checks whether it is relevant.
- Finalize node adds "That's up from X in FY …" when the same figure was asked earlier
  (`c15_conversation_meta.py:1135`).

### RC-7 Fallbacks and fixed writers print bundles — VERIFIED
- `_framed_fallback` (`c12_answer_numbers.py:522`) prints **every numeric column** (one row) or every metric
  of up to 15 rows, plus metric caveats. It is used whenever the composer fails a check twice.
- PMAY-G `_pmay_metrics` (`pmay_g.py:609-668`) maps "performance" / a comparison with no measure to four
  measures and "released" alone to released + sanctioned; comparisons always get a Difference block (:1172).
- MGNREGA breakdown always lists all 5 expenditure components plus total (`mgnrega.py:1157`).

### RC-8 The faithfulness check cannot see wrong claims — VERIFIED
`_answer_numbers_faithful` (c13:226) checks that each number in the answer appears somewhere in the data.
It does not check which claim a number is attached to, the unit, or contradictions between sentences.
Derived figures (gaps, %, shares) are added to the allowed set (`_c12s_allow`), which widens it further.

### RC-9 A small model with a long, conflicting prompt — INFERRED
The composer is `qwen35-9b` (`app/config.py:206`). Its prompt carries ~2,600 characters of general rules
(c13:78-110) plus the shape rule and example, entity block, summary, derived figures, notes and up to 40
rows. Several rules pull against brevity ("supporting figures in a second sentence", "say what the figure
counts, for which scheme, area and period"). Wording errors in §3 (garbled MG-12, contradictory CL-09) are
typical of a small model following many rules at once.

## 3. Evidence — the 43 answered eval questions

**Wrong or misleading statements (8):**

| ID | Question (short) | What the answer says | Problem | Cause |
|---|---|---|---|---|
| CL-05 | loans per lender, FY 2024-25 | "Bank disbursed **11.10 crore more** loans than LIFCOM … Bank 11.10, LIFCOM 9.79" | gap is 1.31 crore | RC-8: 11.10 exists in data, so the check passes |
| CL-09 | records with nothing disbursed | "**One record** … has had nothing disbursed. The data shows **172 records**" | contradicts itself | RC-8, RC-9 |
| MG-10 | wage compliance % per block | "1. MAWHATI — **82.91 lakh**" | a percentage written as lakh | no unit check (RC-8); unit source INFERRED (model) |
| CE-11 | online share % per scheme | "Top 8 schemes **by total applications**" | wrong measure | RC-5 |
| CE-10 | lowest % valid (CM Elevate) | "…across all financial years" | CM Elevate records no financial year | period wording not scheme-aware |
| PM-06 | name the top 5 villages | names only the highest and lowest; "The data shows a clear ranking … with no other villages included" | the 5 names missing; filler sentence | RC-9 |
| FL-08 | payments **and** producer groups per year | lists payments only | asked measure dropped | trend shape takes `metrics[:2]` but composer listed one; multi-row answers have no coverage check |
| MG-12 | % change in person-days | "the recorded total is -48.84 percentage change" | garbled; should say "fell 48.84%" | RC-9 |

**Unrequested content (20; an answer can show several patterns, and some of the 8 above also do), main patterns:**
- Ranking gap line not asked: MG-05, MG-06, MG-10, MG-11, PM-05, PM-08, PM-10, PM-11, PM-13, CE-10 (RC-4).
- Filter questions answered as a ranking ("leads", "ahead"): MG-11, PM-13 (RC-4).
- Totals and % shares not asked: FP-05, CE-07, CE-09, CL-08, CL-11 (RC-4 breakdown); a total across the
  five listed villages: MG-07.
- % change, peak and lowest not asked: MG-08, CL-07 (RC-4 trend / compare).
- Companion columns stated: FL-12 (total and LAMPS payments beside the asked share) (RC-2, RC-3).
- Same figures twice: CE-05 (sentence, then a list of the same two numbers).
- Duplicate / ungrammatical scope tail: PM-01, CL-03, CL-09 (RC-6).
- Inconsistent number formats in one answer: PM-10 "₹39,41,96,000" vs gap "15,124,000"; FP-05
  "₹118,447,500.00" (Western grouping, paise) while other answers use Indian grouping.

**Clean (15):** MG-01, MG-02, MG-03, MG-04, MG-09, MG-13, PM-02, PM-03, PM-04, PM-07, PM-09, FL-04, FL-10, CE-01
(single figures) and PM-12 (a two-district comparison from the PMAY-G code writer). Single figures work; the
problems are in multi-row shapes.

## 4. Why the tests did not catch this — VERIFIED
- The NL→SQL eval scores the **rows** (`detail: "same rows"`), not the answer text: all 43 above are "correct".
- Unit tests pin the composer's *guards* (misquote, dropped metric, hedging), not relevance or wording.
- The shape examples and guards were each added for a real failure (comments cite the dates), so each
  rule is locally right; nothing checks the combined result against the question.

## 5. Recommendations (not implemented; ordered by impact ÷ risk)

1. **One "asked measures" reader, used by every layer.** A deterministic function that reads which
   measures the question names (count / money / % / villages …), the way `cross_figures.plan` already does
   for cross-scheme questions (KI-437). Use it to (a) pass only asked columns to the composer, (b) limit
   `dropped_metric` and the "profile" rule to asked columns, (c) choose the shape's measure (fixes RC-5),
   (d) trim the table. Companion columns can stay in the SQL where they protect correctness (Focus Legacy
   memberships) but are not stated unless asked.
2. **Make shape extras conditional.** Gap line only for "how far / difference / compare"; totals and % shares
   only for "share / percent / total / split"; peak / lowest / % change only for "trend / change / growth /
   peak". A threshold question ("above / over / more than N", "at least") → list shape, never ranking.
3. **Let code write verdict sentences.** For compare / ranking gaps, write the "X is N more than Y" sentence
   in code from `_shape_facts` (as `cross_figures` does) instead of asking the model to word it. Removes
   the CL-05 class of error.
4. **Fix `_finish_answer`'s tail:** no "for across", recognise the scheme's short forms ("CM Elevate
   sub-scheme" for Legacy), never repeat a period already stated, no "financial years" for CM Elevate.
5. **Add answer-text checks to the eval:** flag an answer that names a measure the question did not ask,
   a unit that does not match the column (`_pct` → never "lakh"), two different counts for the same thing,
   or a missing asked measure. Without this, composer quality stays invisible.
6. **Review the companion-column rules and few-shots with the SMEs** (RC-2 list). Keep the ones the data
   needs; label the rest "only when asked". Edit few-shots whose question asks one measure.
7. **One number format:** Indian grouping and ₹ crore / lakh rules applied by code to every answer, including
   gaps and fallbacks.
8. **Model (needs a DECISIONS entry):** after 1-3, the composer's job is mostly wording a short, pre-computed
   answer; re-measure then. Moving the composer role to a larger model is an option but is a bigger change
   and should be decided on measured results, not before the structural fixes.

Each fix needs a regression test that calls the real function, a live check with the VPN, and the docs
update listed in CLAUDE.md §8.
