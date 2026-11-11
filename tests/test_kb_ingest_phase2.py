"""RAG upgrade Phase 2 (2026-10-14): kb_ingest reads data/incoming/<scheme>/,
every format (md / txt / docx / pdf / xlsx), keeps each FAQ question with its
answer, never emits an oversized chunk, and drops the SME docs' internal notes
about the bot's own database."""

import pytest

from app import kb_ingest as K


def test_sources_come_from_incoming_one_folder_per_scheme():
    src = K._sme_sources()
    assert src, "no SME sources found under data/incoming/"
    schemes = {s for _, s in src}
    assert schemes == {"MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate", "CMSS"}
    assert all(f.startswith("incoming/") or f in dict(K._EXTRA_SOURCES) for f, _ in src)
    assert not any("README" in f for f, _ in src)


def test_identical_copies_are_ingested_once():
    # CM_Elevate_Legacy/ holds byte-identical copies of CM_Elevate/'s files.
    files = [f for f, _ in K._sme_sources()]
    assert not any(f.startswith("incoming/CM_Elevate_Legacy/") for f in files)
    names = [f.rsplit("/", 1)[-1] for f in files]
    assert len(names) == len(set(names))


def test_legacy_folder_still_tags_cm_elevate():
    assert K._INCOMING_SCHEMES["CM_Elevate_Legacy"] == "CM Elevate"


def test_no_chunk_is_oversized_and_every_chunk_has_its_label():
    chunks = K._collect_chunks()
    assert chunks
    for c in chunks:
        assert len(c["text"]) <= K._SPLIT_ABOVE + len(c["heading"]) + 60, c["heading"]
        assert c["text"].startswith(f"[{c['heading']}]")


def test_no_internal_database_note_reaches_the_knowledge_base():
    leaks = ("curated data", "curated database", "curated application data",
             "curated application database", "this assistant", "count(*)",
             "unverified in the warehouse", "date column")      # case-insensitive
    for c in K._collect_chunks():
        low = c["text"].lower()
        assert not any(w in low for w in leaks), (c["doc"], c["heading"])


def test_real_sub_scheme_named_warehouse_is_kept():
    text = "\n".join(c["text"] for c in K._collect_chunks() if c["scheme"] == "CM Elevate")
    assert "Warehouse" in text and "Piggery" in text


def test_internal_notes_stripped_but_facts_kept():
    text = ("### How much support?\n"
            "A subsidy of 35% to 75% of project cost. This is policy-level information; the curated "
            "application data this assistant queries does not hold it.\n\n"
            "### How is X different in this assistant's data?\n"
            "X has no date column in the curated database.\n\n"
            "### Where to check?\nThe official portal.\n")
    out = K._strip_internal_notes(text)
    assert "35% to 75%" in out and "official portal" in out
    assert "curated" not in out and "this assistant" not in out and "date column" not in out


def test_faq_section_gives_one_chunk_per_question():
    doc = ("## Eligibility FAQ\n\n"
           "### Who can apply?\nAny adult in a rural household.\n\n"
           "### Is there an age limit?\nApplicants must be 18 or older.\n\n"
           "### Do I need a job card?\nYes, a job card is required to demand work.\n")
    chunks = K._chunk(doc)
    labels = [h for h, _ in chunks]
    assert labels == ["Eligibility FAQ > Who can apply?", "Eligibility FAQ > Is there an age limit?",
                      "Eligibility FAQ > Do I need a job card?"]
    assert "18 or older" in chunks[1][1] and "job card" not in chunks[0][1]


def test_long_section_without_subheadings_is_split_with_overlap():
    paras = [f"Paragraph {i}: " + ("word " * 60).strip() + "." for i in range(12)]
    chunks = K._chunk("## Long rules\n\n" + "\n\n".join(paras))
    assert len(chunks) >= 3
    assert all(len(t) <= K._CHUNK_SIZE + K._OVERLAP + 60 for _, t in chunks)
    assert all(len(t) >= K._MIN_PIECE for _, t in chunks)   # no stub pieces
    # the next piece starts with the tail of the previous one
    assert chunks[1][1].split("\n", 1)[1].startswith("…")
    assert all(h == "Long rules" for h, _ in chunks)


def test_medium_section_stays_whole_so_a_list_keeps_its_intro():
    steps = "\n".join(f"{i}. Step {i}: " + "detail " * 25 for i in range(1, 11))
    doc = "## Process flow\n\nThe application follows these stages:\n" + steps
    assert len(doc) < K._SPLIT_ABOVE
    chunks = K._chunk(doc)
    assert len(chunks) == 1 and "these stages" in chunks[0][1] and "10. Step 10" in chunks[0][1]


def test_shape_turns_plain_lines_into_sections_and_questions():
    md = K._shape(["A. SCHEME OVERVIEW", "What is MGNREGA?", "A rural employment law.",
                   "B. OBJECTIVES", "Why was it introduced?", "To reduce rural poverty."])
    assert "## A. SCHEME OVERVIEW" in md and "### What is MGNREGA?" in md and "## B. OBJECTIVES" in md


def test_word_document_is_read_as_faq_chunks(monkeypatch):
    pytest.importorskip("docx")
    # data/mgnrega/MGNREGA_Scheme_Document.docx is left out of the live KB
    # (measured worse); the reader itself must still handle it.
    monkeypatch.setattr(K, "_EXTRA_SOURCES", [("mgnrega/MGNREGA_Scheme_Document.docx", "MGNREGA")])
    chunks = [c for c in K._collect_chunks() if c["doc"].endswith(".docx")]
    assert len(chunks) >= 20
    assert any(c["heading"].endswith("What is a job card?") for c in chunks)


def test_docx_xlsx_pdf_readers(tmp_path):
    docx = pytest.importorskip("docx")
    openpyxl = pytest.importorskip("openpyxl")
    d = docx.Document()
    d.add_heading("Eligibility", level=2)
    d.add_paragraph("Who can apply?")
    d.add_paragraph("Any adult resident.")
    p = tmp_path / "a.docx"
    d.save(p)
    md = K._read_source(p)
    assert "## Eligibility" in md and "### Who can apply?" in md and "Any adult resident." in md

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Documents"
    ws.append(["Document", "Required"])
    ws.append(["Aadhaar", "Yes"])
    x = tmp_path / "b.xlsx"
    wb.save(x)
    md = K._read_source(x)
    assert "## Documents" in md and "Document: Aadhaar; Required: Yes" in md

    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(width=200, height=200)
    pdf = tmp_path / "c.pdf"
    with open(pdf, "wb") as fh:
        w.write(fh)
    assert K._read_source(pdf) == ""   # no text (a scanned PDF): skipped, not ingested blank
