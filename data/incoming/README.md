# RAG upgrade: scheme documents and work log

This folder holds the scheme documents the chatbot's knowledge answers (RAG)
are built from. This file also records the RAG upgrade: what was decided, what
is done, and what comes next. Keep it up to date as the work moves on.

---

## 1. Where the documents go

| Folder | Scheme | Files now |
|---|---|---|
| `MGNREGA/` | MGNREGA | `mgnrega_complete_reference.md`, `mgnrega_general_faq.md` |
| `PMAY-G/` | PMAY-Gramin | `pmay_gramin_complete_reference.md`, `pmay_gramin_general_faq.md` |
| `Focus_Plus/` | FOCUS+ | `focusplus_complete_reference.md`, `focusplus_general_faq.md` |
| `Focus_Legacy/` | FOCUS (Legacy) | `FOCUS_legacy_Complete_Reference.md`, `FOCUS_LEGACY_FAQ.md` |
| `CM_Elevate/` | CM-ELEVATE | `CM_Elevate_Complete_Reference.md`, `cmelevate_general_faq.md` |
| `CM_Elevate_Legacy/` | CM-ELEVATE Legacy | same two files as `CM_Elevate/` (identical copies) |

**Accepted formats:**
- PDF, but only real text; scanned photos of paper can't be read.
- Word (.docx)
- Excel (.xlsx)
- Markdown (.md)
- Plain text (.txt)

**What to add:** guidelines, circulars, FAQs, application forms, eligibility rules, and helpline or office contacts.

**Don't** put documents in the lowercase scheme folders (`data/mgnrega/`, `data/pmay/` and so on). Those hold the SQL pipeline's rules, not RAG material.

---

## 2. What happened to `data/reference/` (2026-10-14)

- **Moved:** the user moved the reference documents from `data/reference/` into these folders, one set per scheme. `data/reference/` no longer exists.
- **No new content:** all 12 files are word-for-word the same as before.
- **Duplicates resolved:**
  - **CM Elevate:** the user kept `CM_Elevate_Complete_Reference.md`. It's the same as the old `cmelevate_complete_reference.md` minus §15, an internal note about the curated database that was never meant for officers. The old `cmelevate_complete_reference.md` was not moved.
  - **Focus Plus:** `FOCUS_Plus_Complete_Reference (1).md` was identical to `focusplus_complete_reference.md` and was not moved.
- **CM Elevate Legacy** shares one knowledge base with CM Elevate (`rag.kb_scheme`), so its copy is loaded once, not twice.
- **Not moved, and only reachable in the zip:** the KPI use-case spreadsheets (`*_kpi_use_cases.xlsx`) and `pmay_metadata.json`. No running code reads them; only a docstring in `app/schema_context.py` mentions them. Every original is still in `meghoneai/meghalaya.zip` (dated 2026-10-05) if needed.
- **Still pointing at the old folder:**
  - `app/kb_ingest.py` `_SOURCES` → updated in Phase 2.
  - `tests/test_general_sheet_fixes.py` (reads `data/reference/FOCUS_LEGACY_FAQ.md`) → updated in Phase 2.

  The live knowledge collection in Qdrant is unaffected: it was built before the move and is only rebuilt by a reingest.
- **Also not yet used by RAG:** `data/mgnrega/MGNREGA_Scheme_Document.docx` (Word). It is included from Phase 2 unless a newer version is put in `MGNREGA/`.

---

## 3. The RAG upgrade

**Goal:** about 95% correct answers and about 0% made-up answers. Every reply is either correct or an honest "not covered". Everything stays inside the existing chat; there is no separate RAG page.

### Approved by the user (2026-10-14)
- **Code:** change `rag.py`, `kb_ingest.py`, `vectorstore.py`, `config.py`, the knowledge part of `pipeline.py`, and the chat screen.
- **Qdrant:** build a NEW collection, `megh_scheme_kb_v2`, switched on by one setting. The old `megh_scheme_kb` stays for rollback.
- **Past chats:** read past chat questions (`app.conversation_turns`), read-only, to build realistic tests.
- **Feedback table:** add `app.answer_feedback` for 👍/👎, in the app schema only, never scheme data.
- **Rules for every phase:**
  - Nothing is committed or pushed without the user's OK.
  - `megh_db` scheme data and the `Metadata_*` Qdrant collections are never touched.

### The 7 phases

| # | Phase | What | Status |
|---|---|---|---|
| 1 | Measure | 190-question test set + scoring script + today's baseline score | **Done** (2026-10-14); SME review of the test set pending |
| 2 | Clean documents | Read from these folders; PDF/Word/Excel; FAQ question+answer kept together; overlap | **Done** (2026-10-14); app switched to `megh_scheme_kb_v2` |
| 3 | Better search | Keyword (BM25) + meaning search merged (RRF) + local reranker | **Done** (2026-10-15); app on `megh_scheme_kb_v3` with hybrid search; local jina-turbo re-ranker **on** (2026-10-15, user's decision) |
| 4 | Better questions | Rewrite vague questions, 2–3 wordings, Khasi/Garo → English | **Done** (2026-10-15); extra wordings built (on in Phase 5 with the re-sorter); Khasi/Garo built but OFF (English only, user's decision) |
| 5 | No made-up answers | Best 4 pieces only + a check that every sentence is supported | **Done** (2026-10-15): sentence check ON; best-4 measured and rejected (8 pieces kept); re-sorter ON (user's decision) |
| 6 | Sources & feedback | "Source: …" under answers, 👍/👎 in the chat, feedback in the admin dashboard | **Done** (2026-10-15) |
| 7 | Security & housekeeping | Qdrant API key, 30-day chat-memory cleanup, KI-224 fix, drop `megh_scheme_kb_qa20261006` | **Done** (2026-10-15) except the Qdrant key itself, which the infra team sets |

After every phase:
- Re-run the test set and compare the score; keep a change only if the score improves.
- Run the whole test suite.
- Update the docs.

### Phase 1: how the measuring works

Files are in `tests/rag_eval/`.

**`build_testset.py`** writes `testset.json`. It has three kinds of question:
- **doc:** written by the model from one document section, in an officer's words (6 styles), with the expected answer and an **exact evidence quote** from the section.
- **real:** genuine knowledge questions officers asked in the chat, each labelled with the section that answers it.
- **negative:** realistic questions the documents do **not** answer, checked against the scheme's whole text. The right reply is "not covered".

A search **finds the right piece** when a returned piece contains the evidence quote. The test set therefore stays valid when Phase 2+ re-cut or move the documents.

**`run_eval.py`** runs each question exactly as the chat does (`rag.retrieve` + `rag.answer_from_kb`), and a judge model grades it. It reports:
- **Search:** right piece 1st / in top 3 / found at all, and MRR.
- **Answers:** correct / partial / wrong / wrongly refused.
- **Honesty:** "not covered" questions handled honestly.
- **Made-up:** answers with a claim the pieces don't support.
- **Overall:** "correct or honest" %.
- **Speed:** average seconds per question.

Outputs:
- `tests/rag_eval/results/<date>_<label>.json`
- `reference_documents/RAG_Eval_<date>_<label>.xlsx`

**`run_eval.py --export-testset`** writes `reference_documents/rag_test_set.xlsx` for a subject expert to check (OK / FIX / DROP, plus a comment).

```
python tests/rag_eval/build_testset.py                         # build / rebuild the test set
python tests/rag_eval/run_eval.py --label baseline             # score today's RAG
python tests/rag_eval/run_eval.py --label v2 --collection megh_scheme_kb_v2
python tests/rag_eval/run_eval.py --export-testset             # Excel for SME review
```

### Still needed from the user
- **Subject expert review:** check `reference_documents/rag_test_set.xlsx`, about 2–3 hours.
- **New official documents:** any newer ones (PDF/Word/Excel) for these folders.
- **Live server RAM/CPU:** the reranker needs about 1–2 GB extra.
- **Khasi and Garo samples:** about 20 real questions in each, with their English meaning.
- **Qdrant API key:** from the infra team. Put it in `.env` as `QDRANT_API_KEY=...`; never paste it in chat.

### Phase 1 result: baseline (2026-10-14, collection `megh_scheme_kb`)

190 questions in total:
- 139 written from the documents
- 27 real officer questions
- 24 the documents can't answer

Full report: `reference_documents/RAG_Eval_2026-10-14_baseline.xlsx`

| Measure | ALL | CM Elevate | Focus Legacy | Focus Plus | MGNREGA | PMAY-G |
|---|---|---|---|---|---|---|
| Right piece ranked 1st | 43.4% | 35.3% | 33.3% | 36.1% | 45.5% | 63.9% |
| Right piece in top 3 | 68.7% | 64.7% | 70.4% | 63.9% | 72.7% | 72.2% |
| Right piece found at all | 89.2% | 79.4% | 100% | 86.1% | 93.9% | 88.9% |
| Correct answers | 94.0% | 91.2% | 100% | 97.2% | 87.9% | 94.4% |
| Wrong answers | 4.2% | 2.9% | 0% | 2.8% | 9.1% | 5.6% |
| "Not covered" handled honestly | 100% | 100% | 100% | 100% | 100% | 100% |
| Answers with a made-up claim | 19.5% | 25.6% | 19.4% | 31.7% | 10.5% | 9.8% |
| **Overall: correct or honest** | **94.7%** | 92.3% | 100% | 97.6% | 89.5% | 95.1% |
| Seconds per question | 2.4 | | | | | |

**By kind of question:**
- **From the documents:** 132 of 139 correct.
- **Real officer questions:** 24 of 27 correct. This is the more honest number, about 89%.
- **Not covered:** 24 of 24 handled honestly.

**What it shows:**
- **Search is the weakest step.** The right piece is ranked first in only 43% of questions and is missing entirely in 11%. The AI still answers well because it reads 8 pieces, but that is also where made-up details creep in. Phase 3 is the fix.
- **Made-up details in about 20% of answers.** Some are judge noise, but real examples exist:
  - a CM Elevate document list including an income certificate the documents don't mention;
  - the PMAY-G start date given as June 2015;
  - MGNREGA "up to 100 days" instead of "at least 100 days".

  Phase 5's grounding check targets these.
- **An internal note leaked to officers (Q163).** CM Elevate's §15, about "the curated database this assistant queries", is still in the live knowledge base. The new `CM_Elevate_Complete_Reference.md` doesn't have it, so Phase 2's rebuild removes it.
- **The scores are optimistic.** Questions written from the documents are easier than real ones; the real-question score is the one to watch. The subject-expert review of `rag_test_set.xlsx` will firm this up.
- **About the judge:** the judge is a model, so scores move about ±2 points between runs. It no longer counts "confirm at the Block office" advice, or words from the question itself, as made up.

### Phase 2 result: clean documents (2026-10-14, collection `megh_scheme_kb_v2`)

**What changed in `app/kb_ingest.py`:**
- **Sources:** every file in `data/incoming/<scheme>/`. A byte-identical copy (the `CM_Elevate_Legacy/` files) is loaded once.
- **Readers:** Word (.docx), PDF (.pdf) and Excel (.xlsx) are read as well as Markdown and text. A scanned PDF with no text is skipped with a warning. New requirements: `python-docx`, `pypdf`, `openpyxl`.
- **FAQ sections:** each question with its answer is one piece.
- **Long sections:** only a section over 2,400 characters is cut, with a 200-character overlap and no stub pieces under 400 characters. Cutting at 1,500 split "follows these stages:" from the 10 stages (Q176), so the limit was raised.
- **Internal notes stripped while loading:**
  - The documents' notes about the bot's own database ("the curated data this assistant queries", `COUNT(*)`, "no date column", FAQ entries about "this assistant's data") are removed. One was read out to an officer (Q163).
  - The documents themselves are not changed by this.
  - The real "Warehouse" sub-scheme is kept; my first filter removed it by mistake.
- **`data/mgnrega/MGNREGA_Scheme_Document.docx` is measured and left out:** its 39 short generic Q&As pushed MGNREGA's right piece out of the results (found 91% → 79%). The Word reader stays for new documents.

**Two fixes restored into these files.** The copies placed here were the 2026-10-05 versions and had lost two fixes from the General sheet testing. Both were recovered word-for-word from the live knowledge base:
- `PMAY-G/pmay_gramin_general_faq.md`: "What documents are typically required", with "Required for every beneficiary" and "Required where applicable" (TC-006).
- `Focus_Legacy/FOCUS_LEGACY_FAQ.md`: "8a. How do I apply for FOCUS?", the 4 steps (TC-005).

**Test set:** Q093 and Q152 were removed, because they tested the internal notes. Q163 now expects the public fact (CFC notified 11 March 2024). 188 questions now.

**Score (same 188 questions):**

| Measure | Baseline (`megh_scheme_kb`) | Phase 2 (`megh_scheme_kb_v2`) |
|---|---|---|
| Right piece ranked 1st | 42.7% | 42.7% |
| Right piece found at all | 89.0% | 89.0% |
| Correct answers | 93.9% | 93.3% (one question; within judge noise) |
| "Not covered" handled honestly | 100% | 100% |
| Made-up claim | 19.7% | 20.2% (the judge swings ±6 points between runs; not reliable yet) |
| Overall: correct or honest | 94.7% | 94.1% |
| Seconds per question | 2.4 | 1.4 |

**What this means:**
- **No accuracy gain:** Phase 2 is about clean, safe content. The internal notes are gone, the fixes are kept, all formats are supported, and there are no oversized pieces.
- **Search is unchanged:** that's Phase 3's job.
- **The made-up measure needs a steadier judge:** Phase 5.

**Switched over:**
- **Setting:** `QDRANT_COLLECTION=megh_scheme_kb_v2` in `.env` and in `app/config.py`.
- **Server:** the app on :8400 was restarted on it.
- **Rollback:** set `QDRANT_COLLECTION=megh_scheme_kb`.

**On the deployed server:**
- **Copy `data/incoming/`** there.
- **Install the requirements.**
- **Set the same setting.** On first start the app builds `megh_scheme_kb_v2` from `data/incoming/` by itself.

**Tests:**
- **New:** `tests/test_kb_ingest_phase2.py`, 13 tests.
- **Updated:** paths in `tests/test_general_sheet_fixes.py` and `tests/test_rag_general_scoping.py`.
- **Full suite:** 2,287 passed, 0 failed, 1 skipped (`docs/TESTING.md` command).

### Phase 3 result: better search (2026-10-15, collection `megh_scheme_kb_v3`)

**What was built:**
- **`app/local_rank.py`:** BM25 keyword vectors (`Qdrant/bm25`, ~10 MB) and a local cross-encoder re-sorter. Both run on the server's CPU through fastembed, with no internet after the first download. A model that can't load is skipped and the search falls back to meaning only.
- **`app/vectorstore.py`:** collections store a keyword vector beside the meaning vector. Search runs both and Qdrant merges the two lists by rank (RRF). The score kept on each piece is still the meaning similarity, so the confidence levels ("show directly" ≥ 0.84, "not covered" < 0.55) are unchanged.
- **`app/rag.py`:**
  - Wider candidate pool.
  - Optional re-sort.
  - "Enough to answer" is judged on the strongest piece kept.
  - "Show the piece directly" still needs the first piece itself to be a near-exact match.
- **`app/kb_ingest.py`:** stores the keyword vector for every piece. A collection that lacks it is rebuilt.
- **New settings:** `RAG_SPARSE_MODEL`, `RAG_HYBRID_ENABLED`, `RAG_LOCAL_RERANKER`, `RAG_CANDIDATES` (12), `RAG_RERANK_CHARS` (800).
- **`run_eval.py --retrieval-only`:** search measures only, about 1 minute per setup.

**Search setups compared (188 questions, search only):**

| Setup | Right piece 1st | In top 3 | Found at all | Time / question* |
|---|---|---|---|---|
| Meaning only (before) | 42.7% | 68.3% | 89.0% | 0.4 s |
| Meaning + keyword | 47.6% | 73.2% | 92.7% | 0.4 s |
| + MiniLM-L6 re-sorter (20 pieces, full text) | 56.7% | 79.3% | 90.9% | 32 s* |
| + MiniLM-L12 | 57.3% | 81.7% | 93.3% | 37 s* |
| + jina-turbo (20, full) | 57.9% | 79.9% | 93.3% | 16 s* |
| + jina-turbo (12 pieces × 800 chars) | 55.5% | 78.0% | 90.9% | **1.2 s** |
| + MiniLM-L6 (12 × 800) | 55.5% | 79.3% | 90.9% | 1.4 s |
| + bge-reranker-base (1 GB) | stopped: too slow (> 30 min for the run) | | | |

*Measured 3 questions at a time on one CPU. One question alone: jina-turbo takes 4.0 s on 20 full pieces and 0.85 s on 12 × 800 characters.

**Full scoring with answers:**

| | Before (v2) | Hybrid + jina-turbo | **Hybrid only (chosen)** |
|---|---|---|---|
| Right piece 1st | 42.7% | 55.5% | 46.3% |
| Right piece found at all | 89.0% | 90.9% | **91.5%** |
| Correct answers | 93.3% | 90.9% | 92.1% |
| "Not covered" handled honestly | 100% | 95.8% | **100%** |
| Overall: correct or honest | 94.1% | 91.5% | 93.1% |
| Seconds per question | 1.8 | 4.8 | 2.1 |

**Decision:**
- **The app uses hybrid search (meaning + keyword) with the re-sorter off.** Answers are the same as before within the judge's normal variation, about ±2 questions, and the right piece is found more often.
- **The re-sorter doesn't help answers yet.** It puts the right piece first far more often, but the answer writer still reads 8 pieces, so the order hardly matters. Choosing 8 of 12 sometimes dropped the right piece (Q020, Q091).
- **It will be switched on in Phase 5,** when the answer writer gets only the best 4 pieces and the order decides what it sees.

**Switched over:**
- **Setting:** `QDRANT_COLLECTION=megh_scheme_kb_v3` in `.env` and in `app/config.py`.
- **Server:** the app on :8400 was restarted on it.
- **Rollback:** `megh_scheme_kb_v2`, or the original `megh_scheme_kb`.

**On the deployed server:** set the same setting. The first start builds v3 with keyword vectors and downloads `Qdrant/bm25` (~10 MB) once.

**Tests:**
- **New:** `tests/test_rag_hybrid_rerank.py`, 8 tests.
- **Updated:** two older test stand-ins now accept the keyword argument.
- **Full suite:** 2,340 passed, 0 failed.

### Phase 4 result: better questions (2026-10-15)

**1. Search with extra wordings** (`rag._alt_queries`, `rag._fuse`, setting `RAG_MULTI_QUERY`):
- **How it works:** the fast model writes 2 other wordings of the question in the words the documents use, every wording is searched, and the lists are merged by rank.
- **Failures:** a timeout or bad reply searches with the question alone.
- **Scope:** the "which scheme holds this term?" helper never uses it.

Measured in search-only mode, 188 questions (and the 27 real officer questions):

| Setup | Right piece 1st | In top 3 | Found at all |
|---|---|---|---|
| Hybrid, question only (current app) | 47.6% | 74.4% | 92.1% |
| Hybrid + 2 extra wordings | 39.0% | 72.0% | 89.6% |
| Hybrid + 3 extra wordings | 38.4% | 70.1% | 89.6% |
| Re-sorter, question only | 55.5% | 78.0% | 90.9% |
| **Re-sorter + 2 extra wordings** | 55.5% | **80.5%** | **92.1%** |
| Real questions: re-sorter, question only | 48.1% | 55.6% | 77.8% |
| **Real questions: re-sorter + 2 extra wordings** | 48.1% | **74.1%** | **88.9%** |

**Decision:**
- **On their own, extra wordings hurt:** they pull in generic pieces such as "documents required".
- **With the re-sorter they help,** most on real officer questions: found 77.8% → 88.9%.
- **So they switch on together with the re-sorter in Phase 5.** Until then `RAG_MULTI_QUERY=0`, so the app behaves as after Phase 3.

**2. Khasi / Garo → English** (`app/translate.py`, setting `TRANSLATE_ENABLED`):
- **Before:** the chat's KHA / GAR buttons always sent `language`, but the backend ignored it. `QueryRequest` now carries it.
- **Built:** with KHA or GAR selected, the question is translated to English by the response model before anything else runs. The original wording goes back on the result as `translated_from`.
- **Hints:** the prompt lists a few common Khasi question words. The fast model read "katno" (how many) as a name, so the larger response model is used.
- **Checked on hand-made samples:** all translated correctly in 0.1–0.3 s.
- **OFF:** the user wants English only for now. Turn it on with `TRANSLATE_ENABLED=True`; it then needs about 20 real Khasi and 20 real Garo questions to test properly.

**Tests:**
- **New:** `tests/test_rag_phase4_questions.py`, 21 tests.
- **Updated:** one older stand-in accepts the `expand` argument.
- **Full suite:** 2,361 passed, 0 failed.

**App:** restarted with no change in behaviour: extra wordings off, translation off, hybrid search as in Phase 3.

### Phase 5 result: fewer made-up details (2026-10-15)

**What was built:**
- **Sentence check** (`rag.ground_answer`, setting `RAG_GROUNDING_CHECK`, ON):
  - After the composer writes, the answer is cut into sentences (`rag.split_units`; a bullet line is one unit). The response model marks the ones the passages don't support, and they're dropped.
  - Advice ("confirm at the Block office") and a list's intro line always count as supported. An intro left with nothing under it is dropped too.
  - If every sentence is flagged, the answer is kept. That's the check misreading the passages: it turned a correct "56 C&RD Blocks statewide" (Q132) into "not covered".
  - A failure of the check keeps the answer.
- **Steadier judge** (`run_eval.judge_support`): it marks numbered sentences instead of listing "claims" in its own words, and reports "answers with a made-up sentence" and "% of sentences made up".
- **`tests/rag_eval/paired_check.py`:** judges the same answers before and after the check.
- **Re-sorter ON** (`RAG_LOCAL_RERANKER = jina-turbo`): the user's decision, made in `app/config.py` on 2026-10-15.

**Setups measured (188 questions, full answers):**

| Setup | Right piece 1st | Found | Correct | "Not covered" honest | Answers with made-up sentence | Made-up sentences | s / question |
|---|---|---|---|---|---|---|---|
| A. hybrid, 8 pieces, no check | 47.6% | 91.5% | 93.3% | 100% | 17.6% | 5.5% | 2.4 |
| B. re-sorter + 2 extra wordings, best 4 | 55.5% | 84.8% | 90.2% | 100% | 19.3% | 5.6% | 6.5 |
| C. B + sentence check | 56.1% | 84.8% | 89.0% | 95.8% | 10.6% | 4.6% | 9.0 |
| D0. re-sorter, 8 pieces, no check | 55.5% | 90.9% | 90.9% | 100% | 16.5% | 4.5% | 5.2 |
| D1. D0 + sentence check | 55.5% | 90.9% | 89.6% | 95.8% | 9.8% | 2.9% | 6.4 |
| **Final: D1 + "keep if all flagged"** | 55.5% | 91.5% | 91.5% | 95.8% | 16.0% | 5.4% | 8.0 |

**Why the rows don't line up, and the paired test:**
- **Answers vary between runs:** only 71 of 188 answers were word-for-word the same across two runs of identical settings, even at temperature 0. So the made-up figures swing by about ±6 points between runs (D1 9.8% vs Final 16.0%).
- **The fair test:** judge the same 164 answers (from D0) before and after the check:

| Same 164 answers | Before the check | After the check |
|---|---|---|
| Answers with a made-up sentence | 10.4% | **7.9%** |
| Made-up sentences | 2.7% | **2.0%** |
| Correct | 90.9% | **92.1%** |
| Correct answers lost to the check | — | **0** |

**Decisions:**
- **Sentence check ON:** it cuts made-up sentences by about a quarter and loses no correct answer.
- **Best 4 pieces REJECTED:** the right piece is missing from the 4 more often (found 91% → 85%), and answers got worse and slower.
- **Extra wordings stay OFF:** they only helped with best-4.
- **Re-sorter ON** as the user chose.

  Measured honestly, it didn't improve answers (A 93.3% vs D0 90.9% correct, about 4 questions, near the judge's noise) and adds about 3 s per question.

**Final app setup:** `megh_scheme_kb_v3`, hybrid (meaning + BM25) search, 8 pieces to the composer, sentence check ON, extra wordings OFF, Khasi/Garo translation OFF. The jina-turbo re-sorter was later switched OFF too (see the log).

**Honest overall:**
- **Search is clearly better than at the start:** right piece first 42.7% → 55.5%, found 89.0% → 91.5%.
- **Made-up details are down by about a quarter.**
- **Answer correctness is flat, about 91–94% depending on the run.** The remaining wrong answers are mostly the composer misreading a piece it was given, which more search work won't fix.
- **"About 0% made up" isn't reached;** about 2% of sentences still carry an unsupported detail.

**Also seen on 2026-10-15** (not part of the RAG work):
- Someone reorganised `app/pipeline.py` into the `app/pipeline/` package and added `app/sql_guard.py` (needs `sqlglot`). The KI-300 fixes were carried over.
- Data questions now stop with "read-only pool logged in as 'postgres' … set READONLY_DATABASE_URL". That's the new read-only-database rule, which needs a read-only login in `.env`.
- Full suite: 2,450 passed, 0 failed.

### Phase 6 result: sources and feedback (2026-10-15)

**Sources under knowledge answers:**
- **`rag.citations`:** turns the best-ranked pieces into readable sources, at most 2 per answer and one per scheme for a multi-scheme answer. Examples: "PMAY-G FAQ › What documents are typically required for PMAY-Gramin?", "PMAY-G Reference › Eligibility Criteria › …", "MGNREGA background (Wikipedia) › Overview".
- **The response:** knowledge answers carry `citations`.
- **The chat** (`Messages.jsx` `Citations`): shows "Source: …" / "Sources: …" under the answer. Data answers keep their own "Sources:" line, the tables used.

**👍 / 👎 on every answer:**
- **Buttons:** two thumbs beside copy, read aloud and regenerate (not on refusals or pauses).
  - A click saves the vote.
  - The same thumb again takes it back.
  - The other thumb changes it.
  - A chosen thumb stays visible.
  - A failed save says "Couldn't save" and un-highlights the thumb.
- **"What was wrong?" (optional), after 👎:**
  - Quick reasons: Wrong / Incomplete / Not what I asked / Out of date.
  - A free note, then Send or Skip.
- **Storage:** table `app.answer_feedback` (created at startup by `appdb.ensure_schema`). One row per officer per answer (`UNIQUE (user_id, message_key)`) holding the question, answer, route, schemes, citations, rating and comment.
- **API** (`app/routers/feedback.py`):
  - `POST /api/feedback`: logged-in officers only (401 otherwise). Rating 1 / -1 / 0 (0 removes the vote).
  - `GET /admin/feedback`: admins only. Newest first, with 👍/👎 totals and `?rating=-1` for 👎 only. A tenant admin sees only their own tenant.

**Admin dashboard:** new "Answer feedback" page under Activity. It shows the 👍/👎 totals and a 👎-only switch, and a table of time, officer, vote, question, answer, source and note.

**Checked:**
- **Live database round trip:** save 👍 → change to 👎 with a note → admin list shows it → take it back → row gone. The test row was removed.
- **Browser tests at desktop 1300, tablet 820 and phone 390:** 63/63 (sources shown, every vote action, the note box fits every screen, failure handling, the admin page, no sideways scroll, no page errors).
- **Earlier UI suites still pass:** responsive 15/15, alignment 27, composer 39, chat download 39, shortcuts 46.
- **Tests:**
  - New: `tests/test_rag_phase6_feedback.py`, 14 tests.
  - Full suite: 2,560 passed, 0 failed.

**How a 👎 turns into a fix:** read it in Answer feedback, check the answer against the documents, fix the document (or log a known issue), and add the question to `tests/rag_eval/testset.json` so it stays fixed.

### Phase 7 result: security and housekeeping (2026-10-15)

| Task | Result |
|---|---|
| Chat memory older than 30 days | Never returned to a search, and deleted at startup and then once a day (`conversation_memory.purge_old_turns` / `purge_loop`, setting `CONTEXT_MEMORY_RETENTION_DAYS=30`, 0 = keep all). At the time: 1,559 turns, none older than 30 days (memory started 2026-10-04), so the first deletions come around 2026-11-03 |
| KI-224: old turns coming back after "new topic" / reset / idle expiry | **Fixed.** Clearing the context records `Session.memory_since` (kept in the durable snapshot); memory search returns only turns after it |
| Leftover test collection `megh_scheme_kb_qa20261006` | **Deleted** (201 test pieces). The `Metadata_*` collections, which are not ours, were not touched |
| Qdrant password (KI-200) | **Code side done:** `QDRANT_API_KEY` is already sent to Qdrant, and startup logs a CRITICAL "insecure configuration … QDRANT_API_KEY (empty)" until it is set. **Still needed from the infra team:** turn on an API key on the Qdrant server (115.124.102.167:6335), put the same value in `.env` as `QDRANT_API_KEY=…` on every server (never in chat), and close the port to the public internet with a firewall |

**Still in Qdrant, the user's call:** `megh_scheme_kb` (original) and `megh_scheme_kb_v2` (Phase 2) are rollback copies. Delete them once `megh_scheme_kb_v3` is accepted.

**Tests:**
- **New:** `tests/test_rag_phase7_housekeeping.py`, 9 tests.
- **Full suite:** 2,581 passed, 0 failed.
- **App restarted:** the warning and the cleanup both ran at startup.

---

## Subject-expert review of the test set (set up 2026-10-15)

Until an expert checks it, "correct" is judged against expected answers the model wrote from the documents. With the review, the scores become trustworthy.

| Step | What |
|---|---|
| 1. Send | `reference_documents/RAG_Test_Set_SME_Review.xlsx` to a scheme expert. The "How to review" sheet explains everything. On "Review", each row has the question, expected answer, exact quote, document, section, and the chatbot's latest answer, plus a **Decision** dropdown (OK / FIX / DROP), a **Correct answer** box for FIX, and a Comment box. About 1 minute per row (188 rows ≈ 2–3 hours); a partial review is fine |
| 2. Read it back | `python tests/rag_eval/sme_review.py import <filled file> --reviewer "Name"`. OK confirms, FIX replaces the expected answer with the expert's, DROP removes the question, and blank leaves it. The old test set is kept as `testset.before_review_<date>.json`. Bad rows (a FIX with no answer, an unknown decision) are listed and skipped |
| 3. Score | `python tests/rag_eval/run_eval.py --label after_review` now also prints **EXPERT-CHECKED (n of 188): correct …%**, the number to trust |
| Again | `python tests/rag_eval/sme_review.py export` writes a fresh workbook; reviewed rows show who checked them and when |

The older `reference_documents/rag_test_set.xlsx` (190 rows, before Q093/Q152 were dropped) is superseded by this workbook.
Tests: `tests/test_rag_sme_review.py` (3 tests, run on a copy of the test set).

## 5. The whole upgrade at a glance (2026-10-14 → 2026-10-15)

| Measure | Before (Phase 1) | After Phase 7 |
|---|---|---|
| Right piece ranked 1st | 42.7% | **55.5%** |
| Right piece found | 89.0% | **91.5%** |
| Correct answers (188-question test) | ~92–94% | ~91–94% (unchanged; answers vary run to run) |
| Made-up details | — | **cut by about a quarter** (same 164 answers before/after the check: answers with a made-up sentence 10.4% → 7.9%, sentences 2.7% → 2.0%) |
| "Not covered" questions handled honestly | 100% | 96–100% |
| Sources shown to the officer | No | **Yes** |
| Officer feedback | No | **👍/👎 + note, admin page** |
| Document formats | Markdown | **Markdown, text, Word, PDF, Excel** |
| Internal database notes reaching officers | Yes (Q163) | **No** |
| Chat memory kept | Forever | **30 days** |

**Built but switched off:**
- **Khasi/Garo translation:** English only, the user's decision.
- **Search with extra wordings:** it helped only with best-4, which was rejected.

**Open:**
- **Qdrant API key:** the infra team.
- **KI-301:** "its" after a scheme-term question is misread by the rephraser.
- **Subject-expert review** of `reference_documents/rag_test_set.xlsx`.
- **`READONLY_DATABASE_URL`:** the new read-only database rule, which isn't RAG work, stops data questions locally until it is set.
- **Nothing committed yet.**

---

## 4. Log

| Date | What |
|---|---|
| 2026-10-14 | Upgrade plan approved; documents moved here from `data/reference/`; Phase 1 started (`tests/rag_eval/`) |
| 2026-10-15 | Subject-expert review set up: `RAG_Test_Set_SME_Review.xlsx` (instructions, OK/FIX/DROP dropdown, chatbot's latest answer), `sme_review.py import`, expert-checked score in `run_eval.py` |
| 2026-10-15 | Re-sorter switched OFF (user's decision after the Phase 5 numbers): it cost ~3 s per answer without improving answers (correct 93.3% without vs 90.9% with). Back on by setting `RAG_LOCAL_RERANKER=jinaai/jina-reranker-v1-turbo-en` |
| 2026-10-15 | Phase 7 done: 30-day chat-memory retention (search filter + daily delete), KI-224 fixed, test collection `megh_scheme_kb_qa20261006` deleted, CRITICAL startup warning while `QDRANT_API_KEY` is empty; the key itself is waiting on the infra team |
| 2026-10-15 | Phase 6 done: "Source: …" under knowledge answers; 👍/👎 with an optional "what was wrong?" note, saved in `app.answer_feedback`; admin "Answer feedback" page; 63/63 browser checks, 2,560 tests pass |
| 2026-10-15 | Phase 5 done: sentence check ON (paired test: made-up answers 10.4% -> 7.9%, sentences 2.7% -> 2.0%, 0 correct answers lost); best-4 rejected; re-sorter ON (user); final 91.5% correct, 92.0% correct-or-honest |
| 2026-10-15 | Phase 4 done: extra-wordings search built and measured (helps only with the re-sorter; both on in Phase 5); Khasi/Garo translation built, OFF (English only); `language` now reaches the backend |
| 2026-10-15 | Phase 3 done: hybrid search (meaning + BM25 keyword, RRF) on `megh_scheme_kb_v3`; right piece found 89.0% -> 91.5%, first 42.7% -> 46.3%; answers unchanged within noise (93.1%); jina-turbo re-sorter built (first 55.5%), off until Phase 5 |
| 2026-10-15 | KI-300 fixed: what-is questions about scheme terms (Gram Panchayat, SECC, DBT, Gram Sabha…) answered from the scheme whose documents hold the term; re-score unchanged (94.1% correct-or-honest, 0% wrongly refused); KI-301 ("its" after a term question) logged open |
| 2026-10-14 | Phase 2 done: ingest from `incoming/`, docx/pdf/xlsx, FAQ pieces, internal notes stripped, 2 lost fixes restored, Word FAQ measured and left out; app on `megh_scheme_kb_v2` (score = baseline, 94.1%) |
| 2026-10-14 | Phase 1 done: 190-question test set, `run_eval.py`, baseline 94.7% correct-or-honest, 43% right piece first, ~20% answers with a made-up detail; `rag_test_set.xlsx` sent for SME review |
