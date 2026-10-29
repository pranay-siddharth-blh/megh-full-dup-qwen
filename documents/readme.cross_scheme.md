# Cross-scheme questions — how Megh One AI answers them

Written 2026-10-13 after the Cross Scheme Test Cases sheet (CROSS-1..CROSS-20) and 8,649 generated test
conversations, all passing on the final code.

## What a cross-scheme question is
Any question that compares two or more of the six schemes (MGNREGA, PMAY-G, Focus Plus, Focus Legacy (FOCUS),
CM Elevate (applications), CM Elevate Legacy (CM-ELEVATE)), or asks "which scheme / each scheme / all schemes"
about a figure. For example: "Compare Focus+, FOCUS and CM-ELEVATE in East Khasi Hills", "Which scheme has the
highest beneficiary count in each district?", "District-wise summary comparing MGNREGA, PMAY-G, Focus+, FOCUS
and CM-ELEVATE".

## The problem (before)
The question went to the AI SQL generator with every named scheme at once. Of the testers' 20 questions, 18
stopped to ask something unnecessary (a nine-year "which financial year?" list, "which area?", "which scheme?"),
and the other 2 were wrong ("(no label)" rows; one total that added different kinds of money together).

## The solution (after)
`meghalaya/app/cross_scheme.py` answers these questions without the AI writing SQL:
1. **Detect** the schemes (FOCUS beside Focus+ = Focus Legacy; bare CM-ELEVATE = CM Elevate Legacy) and what is
   asked: counts, money, both, coverage, a ranking, district-wise / block-wise, the leading scheme per district,
   the top district per scheme.
2. **Resolve the place and year** (state, district, block, village, constituency; any FY). No year = each
   scheme's whole data; no place = all of Meghalaya. No unnecessary pauses.
3. **Run one fixed query per scheme**, using exactly the rule that scheme's own answers use.
4. **Build the answer table** from the rows: what each figure counts, each scheme's years, "no data for FY …",
   "not recorded by constituency", "no money recorded" — never a false zero, never a sum across schemes.

## Edge cases handled
- Urban blocks ("Baghmara-Municipal Board") are no longer mistaken for the rural block of the same name.
- The four Shillong constituencies are recognised (they have no MGNREGA data).
- Two villages with one name in one block, both holding data, are offered separately with their LGD codes.
- A tapped village chip is pinned exactly (no repeated question, no wrong village).
- The AI rephraser can no longer change what the question asks for.

## Open items
- "FY2022-23" written without a space is not understood in single-scheme questions (works in cross-scheme
  ones). Fixing it touches the shared resolver, and the finished scheme sheets would need re-running.
- "Give me a summary comparing …" with no figure word may get a scheme description instead of data.

## Where things are
Code `meghalaya/app/cross_scheme.py`; tests `meghalaya/tests/test_cross_scheme_sheet_fixes.py`; live harness
`meghalaya/tests/sheet_runs/cross/`; results `meghalaya/reference_documents/Cross Scheme Test Cases.xlsx`;
process `meghalaya/reference_documents/README.md`; design decision D-044 in `meghalaya/docs/DECISIONS.md`.
