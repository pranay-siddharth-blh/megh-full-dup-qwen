"""
Scheme-knowledge base ingest for the RAG path.

Source of truth: the SME-written scheme documents under data/incoming/<scheme>/
(since the RAG upgrade, 2026-10-14; previously data/reference/) — the scheme
references and the general FAQs, in Markdown, text, Word, PDF or Excel. These answer "what is MGNREGA", "who is
eligible for PMAY-G", "what are the scheme components" — questions that are
NOT database questions and must never be answered by generating SQL.

Chunking follows the NeuralAiGovernanceProject rag_service._chunk() pattern:
one chunk per H2 section, split at H3 when a section is too long, each chunk
prefixed with its heading path so the heading travels into the embedding. Two
additions (RAG upgrade Phase 2): every FAQ question ("### ...?") is its own
chunk with its answer, and a piece still over the size limit is cut at
paragraph boundaries with a short overlap, so no chunk is ever oversized.
Word / PDF / Excel files are first turned into the same Markdown shape
(_read_source), so one chunker serves every format.

Idempotent: startup calls ingest_kb(), which skips the work if the Qdrant
collection already holds roughly the expected number of points. POST
/api/rag/reingest forces a full rebuild.
"""
import hashlib
import logging
import uuid
from pathlib import Path

from qdrant_client import models

from app import llm, vectorstore
from app.config import settings
from app.text_match import Hit, Matcher, W

logger = logging.getLogger(__name__)

# app/kb_ingest.py -> repo root -> data/
_DATA_PART = Path(__file__).resolve().parents[1] / "data"

# The SME scheme documents: one folder per scheme under data/incoming/ (the
# user moved them there from data/reference/ on 2026-10-14). Every readable
# file in a folder is a source; the folder decides the scheme tag. These are
# the authoritative tier. CM Elevate Legacy shares CM Elevate's knowledge base
# (see _CANONICAL_SCHEME, rag.kb_scheme): its folder holds the same files, and
# identical files are ingested once (_sme_sources de-duplicates by content).
_INCOMING_DIR = "incoming"
_INCOMING_SCHEMES = {
    "MGNREGA": "MGNREGA",
    "PMAY-G": "PMAY-G",
    "Focus_Plus": "Focus Plus",
    "Focus_Legacy": "Focus Legacy",
    "CM_Elevate": "CM Elevate",
    "CM_Elevate_Legacy": "CM Elevate",
}
# SME documents kept elsewhere under data/ (relative path, scheme). Empty on
# purpose: data/mgnrega/MGNREGA_Scheme_Document.docx was measured on
# 2026-10-14 and left out — its 39 short, generic Q&As crowded the full
# reference out of MGNREGA's top results (right piece found 91% -> 79%,
# correct 88% -> 85%). A document added here is ingested like any other.
_EXTRA_SOURCES: list[tuple[str, str]] = []
_READABLE = {".md", ".txt", ".docx", ".pdf", ".xlsx"}


def _sme_sources() -> list[tuple[str, str]]:
    """(path relative to data/, scheme) for every SME document, each distinct
    file once — a byte-identical copy in a second folder (CM_Elevate_Legacy)
    is skipped, so its chunks are not embedded twice."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    candidates: list[tuple[Path, str]] = []
    base = _DATA_PART / _INCOMING_DIR
    for folder, scheme in _INCOMING_SCHEMES.items():
        d = base / folder
        if d.is_dir():
            candidates += [(p, scheme) for p in sorted(d.iterdir())
                           if p.is_file() and p.suffix.lower() in _READABLE
                           and p.name.lower() != "readme.md"]
    candidates += [(_DATA_PART / f, s) for f, s in _EXTRA_SOURCES]
    for path, scheme in candidates:
        try:
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
        except OSError:
            logger.warning("kb_ingest: source not readable, skipping — %s", path)
            continue
        if digest in seen:
            continue
        seen.add(digest)
        out.append((path.relative_to(_DATA_PART).as_posix(), scheme))
    return out

# Scraped encyclopedic / official background, dropped into data/web/*.md by
# the web-ingest step. Picked up automatically. Tagged source_type="web" so the
# retriever / composer can treat them as context, not as the rule of record —
# the SME docs and the live DB stay authoritative.
_WEB_DIR = "web"

_CHUNK_SIZE = 1500

# Spaces and dots are allowed: the three newest schemes are multi-word
# ("Focus Legacy", "Focus Plus", "CM Elevate"), and the original
# `[A-Za-z0-9-]+` silently refused to match any of them — so an explicitly
# tagged doc fell through to filename-guessing or the unqueryable "GENERAL".
_KB_TAG_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.- ")


class _KbSchemeTag:
    """Finds `<!-- scheme: X -->` (any case, any whitespace around the parts);
    .search(text) returns a Hit whose group(1) is X — letters, digits, '.',
    '-' and spaces, the shortest run that the closing "-->" follows — or None."""

    @staticmethod
    def search(text: str | None) -> Hit | None:
        text = text or ""
        n = len(text)
        k = text.find("<!--")
        while k >= 0:
            p = k + 4
            while p < n and text[p].isspace():
                p += 1
            if text[p:p + 7].lower() == "scheme:":
                q = p + 7
                start = q
                while start < n and text[start].isspace():
                    start += 1
                while True:
                    e = start
                    while e < n and text[e] in _KB_TAG_CHARS:
                        e += 1
                        f = e
                        while f < n and text[f].isspace():
                            f += 1
                        if text.startswith("-->", f):
                            return Hit(text, k, f + 3, [(start, e)])
                    # let the name begin with a space the whitespace run gave up
                    if start > q and text[start - 1] == " ":
                        start -= 1
                    else:
                        break
            k = text.find("<!--", k + 1)
        return None


_SCHEME_TAG = _KbSchemeTag()

# Whatever the tag or the filename produced -> the scheme's canonical spelling,
# which is what every retrieval filter matches on (vectorstore.search uses an
# exact MatchValue). Keyed case-insensitively so "focus legacy", "FOCUS LEGACY"
# and "Focus Legacy" all land on the same tag.
_CANONICAL_SCHEME = {
    "mgnrega": "MGNREGA", "nrega": "MGNREGA",
    "pmay": "PMAY-G", "pmay-g": "PMAY-G", "pmayg": "PMAY-G", "pmay-gramin": "PMAY-G",
    "pmay-u": "PMAY-U", "pmay-urban": "PMAY-U",
    "focus plus": "Focus Plus", "focus+": "Focus Plus", "focusplus": "Focus Plus",
    "focus legacy": "Focus Legacy", "focuslegacy": "Focus Legacy",
    "cm elevate": "CM Elevate", "cmelevate": "CM Elevate", "cm-elevate": "CM Elevate",
    # CM Elevate Legacy is the same CM-ELEVATE programme's sanction and
    # disbursement DATA; its reference material is the programme's, shared with
    # CM Elevate (see rag.kb_scheme). A doc tagged for it lands in that one
    # knowledge base rather than a second, disjoint namespace.
    "cm elevate legacy": "CM Elevate", "cmelevate legacy": "CM Elevate",
    "cmelevatelegacy": "CM Elevate", "cm-elevate legacy": "CM Elevate",
    "cm elevate disbursement": "CM Elevate",
}


def _web_sources() -> list[tuple[str, str]]:
    """(relative_path, scheme) for every data/web/*.md, tagged with the scheme's
    CANONICAL spelling. Scheme comes from a `<!-- scheme: X -->` comment, else
    the filename.

    A file we cannot place is SKIPPED, not ingested under a placeholder label:
    every retrieval path filters on an exact scheme name, so a chunk tagged
    anything else (the old 'GENERAL') can never be returned by a scoped search
    and only wastes an embedding. Skipping it logs a warning naming the file, so
    an untagged doc is a visible problem rather than a silently dead one."""
    web = _DATA_PART / _WEB_DIR
    if not web.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for p in sorted(web.glob("*.md")):
        raw = ""
        try:
            head = p.read_text(encoding="utf-8")[:2000]
            m = _SCHEME_TAG.search(head)
            if m:
                raw = m.group(1).strip()
            else:
                name = p.name.upper()
                # "LEGACY" is tested before the bare "FOCUS": both Focus schemes
                # carry that word, and the qualifier is what tells them apart.
                if "PMAY" in name:
                    raw = "PMAY-G"
                elif "MGNREGA" in name or "NREGA" in name:
                    raw = "MGNREGA"
                # Covers CM Elevate Legacy files too — both CM Elevate datasets
                # share one knowledge base (see _CANONICAL_SCHEME).
                elif "ELEVATE" in name:
                    raw = "CM Elevate"
                elif "LEGACY" in name:
                    raw = "Focus Legacy"
                elif "FOCUS" in name:
                    raw = "Focus Plus"
        except OSError:
            pass

        scheme = _CANONICAL_SCHEME.get(raw.lower().replace("_", " ").strip())
        if not scheme:
            logger.warning(
                "kb_ingest: skipping %s — no scheme could be determined (add a "
                "'<!-- scheme: Focus Legacy -->' comment); an untagged doc is not "
                "retrievable by any scheme-scoped search",
                p.name,
            )
            continue
        out.append((f"{_WEB_DIR}/{p.name}", scheme))
    return out


# ── Readers: every format becomes Markdown-shaped text for _chunk ──────────

# A short line that reads as a section title in a Word / PDF document with no
# heading styles: "A. SCHEME OVERVIEW", "3. Eligibility", "ELIGIBILITY".
_KB_TITLE_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ &/,()'-")


def _kb_is_upper_ascii(ch: str) -> bool:
    return "A" <= ch <= "Z"


def _kb_is_title_line(line: str) -> bool:
    """"A. Overview" / "3) Eligibility" (a capital letter or one or two digits,
    '.' or ')', whitespace, then at most 71 more characters on the line), or a
    capitalised line of 4-61 characters from A-Z, spaces and & / , ( ) ' -."""
    if line.endswith("\n"):
        line = line[:-1]
    n = len(line)
    if n == 0:
        return False
    k = 0
    if _kb_is_upper_ascii(line[0]):
        k = 1
    else:
        while k < n and line[k].isdecimal():
            k += 1
        if k > 2:
            k = 0
    if k and k < n and line[k] in ".)":
        m = k + 1
        while m < n and line[m].isspace():
            m += 1
        rest = line[m + 1:]
        if m > k + 1 and m < n and len(rest) <= 70 and "\n" not in rest:
            return True
    return (_kb_is_upper_ascii(line[0]) and 3 <= n - 1 <= 60
            and all(c in _KB_TITLE_CHARS for c in line[1:]))


def _shape(lines: list[str]) -> str:
    """Plain lines -> Markdown: title lines become "## ", short questions
    (ending in "?") become "### " so each Q&A is one FAQ unit."""
    out = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            out.append(line)
        elif len(line) <= 80 and _kb_is_title_line(line) and not line.endswith((".", ":", ";")):
            out.append(f"\n## {line}")
        elif len(line) <= 200 and line.endswith("?"):
            out.append(f"\n### {line}")
        else:
            out.append(line)
    return "\n".join(out)


def _read_docx(path: Path) -> str:
    import docx  # python-docx

    d = docx.Document(str(path))
    lines: list[str] = []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        style = (p.style.name if p.style is not None else "").lower()
        if style.startswith("title") or style == "heading 1":
            lines.append(f"# {t}")
        elif style == "heading 2":
            lines.append(f"## {t}")
        elif style.startswith("heading"):
            lines.append(f"### {t}")
        elif "list" in style:
            lines.append(f"- {t}")
        else:
            lines.append(t)
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return _shape(lines)


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    text = "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    if len(text.strip()) < 200:
        logger.warning("kb_ingest: %s has almost no text — a scanned PDF? Skipping it "
                       "(a typed copy is needed)", path.name)
        return ""
    return _shape(text.split("\n"))


def _read_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        rows = [[("" if v is None else str(v).strip()) for v in r] for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            continue
        header, body = rows[0], rows[1:]
        parts.append(f"## {ws.title}")
        for r in body:
            pairs = [f"{h or f'Column {i + 1}'}: {v}" for i, (h, v) in enumerate(zip(header, r)) if v]
            if pairs:
                parts.append("- " + "; ".join(pairs))
    wb.close()
    return "\n".join(parts)


def _read_source(path: Path) -> str:
    """The document as Markdown-shaped text, whatever its format."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".xlsx":
        return _read_xlsx(path)
    return path.read_text(encoding="utf-8", errors="replace")


# Internal notes in the SME docs about the bot's OWN database ("the curated
# application data this assistant queries", "COUNT(*)", "no date column") are
# guidance for the SQL path, never for an officer — one was read out verbatim
# as a knowledge answer (RAG eval 2026-10-14, Q163). They are dropped at
# ingest, leaving the documents themselves as the user delivered them: an FAQ
# entry asking about "this assistant's data" goes whole, any other sentence
# that describes the database goes on its own.
def _kb_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


# An FAQ heading ("###...") naming "this assistant's data" — also written
# "this assistant data", "this assistants data", "this assistant' data" — as
# whole words, any case.
_KB_ASSISTANT_DATA = ("this assistant data", "this assistant's data", "this assistants data",
                      "this assistant' data")


def _kb_names_assistant_data(line: str) -> bool:
    low = line.lower()
    if len(low) != len(line):
        low = "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in line)
    for phrase in _KB_ASSISTANT_DATA:
        k = low.find(phrase)
        while k >= 0:
            e = k + len(phrase)
            if (k == 0 or not _kb_is_word_char(low[k - 1])) and (e == len(low) or not _kb_is_word_char(low[e])):
                return True
            k = low.find(phrase, k + 1)
    return False


# A sentence about the bot's own database: any of these phrases, any case,
# even inside a longer word ("curated database", "loaded datasets"). NOT
# "warehouse": CM-ELEVATE has a real "Warehouse" sub-scheme (the FOCUS+
# "unverified in the warehouse" note sits in an FAQ entry that
# _kb_strip_internal_faq drops whole).
_INTERNAL_SENTENCE = ("curated data", "curated application data", "this assistant queries",
                      "this assistant's data", "count(*)", "loaded dataset", "date column", "data column",
                      "aggregate vocabulary", "application data")


def _kb_is_internal_sentence(s: str) -> bool:
    low = s.lower()
    if len(low) != len(s):
        low = "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in s)
    return any(p in low for p in _INTERNAL_SENTENCE)


def _kb_strip_internal_faq(text: str) -> str:
    """Drop every "###" FAQ entry whose heading line names this assistant's
    data: the heading line (which must end in a newline) and everything after
    it up to the next line starting "## " / "### ", or the end of the text."""
    n = len(text)
    out, last, p = [], 0, 0
    while p < n:
        nl = text.find("\n", p)
        if nl < 0:
            break
        if text.startswith("###", p) and _kb_names_assistant_data(text[p:nl]):
            r = nl + 1
            while r < n and not (text.startswith("## ", r) or text.startswith("### ", r)):
                nxt = text.find("\n", r)
                r = n if nxt < 0 else nxt + 1
            out.append(text[last:p])
            last = p = r
            continue
        p = nl + 1
    out.append(text[last:])
    return "".join(out)


def _kb_drop_curated(text: str) -> str:
    """"curated sub-schemes" -> "sub-schemes" (exact case, "curated" a whole word)."""
    key = "curated sub-schemes"
    out, last = [], 0
    k = text.find(key)
    while k >= 0:
        if k == 0 or not _kb_is_word_char(text[k - 1]):
            out.append(text[last:k])
            last = k + len("curated ")
        k = text.find(key, k + 1)
    out.append(text[last:])
    return "".join(out)


def _kb_split_after_punct(text: str) -> list[str]:
    """Split where '.', '!' or '?' is followed by whitespace (the whitespace
    run is dropped; a trailing one leaves an empty last piece)."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] in ".!?" and i + 1 < n and text[i + 1].isspace():
            out.append(text[start:i + 1])
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            start = i = j
            continue
        i += 1
    out.append(text[start:])
    return out


def _strip_internal_notes(text: str) -> str:
    text = _kb_strip_internal_faq(text)
    text = _kb_drop_curated(text)
    out = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#") or not _kb_is_internal_sentence(line):
            out.append(line)
            continue
        kept = [s for s in _kb_split_after_punct(line) if not _kb_is_internal_sentence(s)]
        if kept:
            out.append(" ".join(kept))
    return "\n".join(out)


_OVERLAP = 200      # characters carried into the next piece when a long one is cut
# Only a piece longer than this is cut: up to ~2,400 characters (~550 tokens)
# the embedding model still reads it whole, and cutting a numbered process or a
# sub-scheme list at 1,500 separated "follows these stages:" from the stages
# (RAG eval 2026-10-14, Q176 "the 10 stages of CM Elevate" went wrong).
_SPLIT_ABOVE = 2400
_MIN_PIECE = 400    # never leave a stub: a short intro stays with what follows it


def _kb_split_paragraphs(text: str) -> list[str]:
    """Split at blank lines: a separator runs from a newline to the last
    newline of the whitespace that follows it (it needs two newlines); spaces
    before the first and after the last newline stay with their paragraphs."""
    out, start, i, n = [], 0, 0, len(text)
    while i < n:
        if text[i] != "\n":
            i += 1
            continue
        r = i + 1
        last_nl = i
        while r < n and text[r].isspace():
            if text[r] == "\n":
                last_nl = r
            r += 1
        if last_nl > i:
            out.append(text[start:i])
            start = i = last_nl + 1
        else:
            i = r
    out.append(text[start:])
    return out


def _kb_h3_title(s: str) -> str | None:
    """The title of a "### Title" line at the start of `s`, or None."""
    if not s.startswith("### "):
        return None
    title = s[4:].split("\n", 1)[0]
    return title or None


def _kb_split_before_h3(text: str) -> list[str]:
    """Split at every newline that a "### " line follows (the newline goes)."""
    out, start = [], 0
    k = text.find("\n### ")
    while k >= 0:
        out.append(text[start:k])
        start = k + 1
        k = text.find("\n### ", start)
    out.append(text[start:])
    return out


def _split_long(label: str, body: str) -> list[tuple[str, str]]:
    """Cut an oversized piece at paragraph (then line) boundaries into chunks
    of about _CHUNK_SIZE, each starting with the tail of the previous one, so
    a fact on the boundary is never cut off from its context."""
    if len(body) <= _SPLIT_ABOVE:
        return [(label, body)]
    units = [u for u in _kb_split_paragraphs(body) if u.strip()]
    if len(units) == 1:
        units = [u for u in body.split("\n") if u.strip()]
    pieces: list[str] = []
    cur = ""
    for u in units:
        if len(u) > _CHUNK_SIZE and cur and len(cur) < _MIN_PIECE:
            u, cur = f"{cur}\n\n{u}", ""     # a short intro rides with the long paragraph
        while len(u) > _CHUNK_SIZE:          # one giant paragraph: cut at a space
            cut = u.rfind(" ", 0, _CHUNK_SIZE)
            cut = cut if cut > 0 else _CHUNK_SIZE
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(u[:cut])
            u = u[cut:].strip()
        if cur and len(cur) >= _MIN_PIECE and len(cur) + len(u) + 2 > _CHUNK_SIZE:
            pieces.append(cur)
            tail = cur[-_OVERLAP:]
            tail = tail[tail.find(" ") + 1:] if " " in tail else tail
            cur = f"…{tail}\n\n{u}"
        else:
            cur = f"{cur}\n\n{u}" if cur else u
    if cur.strip():
        if pieces and len(cur) < _MIN_PIECE + _OVERLAP:   # a short last piece joins the one before
            pieces[-1] = f"{pieces[-1]}\n\n{cur.split(chr(10) + chr(10), 1)[-1]}"
        else:
            pieces.append(cur)
    return [(label, p.strip()) for p in pieces if p.strip()]


def _is_faq_block(subs: list[str]) -> bool:
    """Most of the section's ### sub-headings are questions -> an FAQ list."""
    heads = [_kb_h3_title(x.strip()) for x in subs]
    heads = [h.strip() for h in heads if h is not None]
    return len(heads) >= 2 and sum(h.endswith("?") for h in heads) >= 0.6 * len(heads)


def _chunk(content: str) -> list[tuple[str, str]]:
    """Return [(heading_path, text), ...]. H2 sections, split at H3 when large."""
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []
    current_h2 = "(intro)"
    buf: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if buf:
                sections.append((current_h2, "\n".join(buf).strip()))
            current_h2 = line.lstrip("#").strip()
            buf = []
        else:
            buf.append(line)
    if buf:
        sections.append((current_h2, "\n".join(buf).strip()))

    chunks: list[tuple[str, str]] = []
    for heading, text in sections:
        if not text.strip():
            continue
        subs = _kb_split_before_h3(text)
        if heading != "(intro)" and _is_faq_block(subs):
            # An FAQ section: every question with its answer is its own chunk
            # (RAG upgrade Phase 2) — packed together, one question's answer
            # was buried among others and ranked below a broader section.
            for sub in subs:
                sub = sub.strip()
                m = _kb_h3_title(sub)
                if m is None:
                    if len(sub) > 50:
                        chunks.append((heading, f"[{heading}]\n{sub}"))
                    continue
                label = f"{heading} > {m.strip()}"
                chunks.append((label, f"[{label}]\n{sub}"))
            continue
        if len(text) <= _CHUNK_SIZE:
            chunks.append((heading, f"[{heading}]\n{text}"))
            continue
        # Too big — break at H3 boundaries.

        if heading == "(intro)":
            # No real H2 in this doc — the general_faq.md files are flat
            # "### Question?" lists with no H2 at all, so the whole file lands
            # here as one oversized "(intro)" section. Packing several
            # unrelated Q&As into one chunk buried specific answers (e.g.
            # PMAY-G's "what documents are required" answer ended up inside a
            # chunk labeled after a different, unrelated question, and the
            # compose LLM skimmed past it). Each "###" is a self-contained
            # unit here, so give it its own chunk instead of packing.
            for sub in subs:
                sub = sub.strip()
                if not sub:
                    continue
                m = _kb_h3_title(sub)
                label = m.strip() if m is not None else heading
                chunks.append((label, f"[{label}]\n{sub}"))
            continue

        cur_label, cur = heading, ""
        for sub in subs:
            m = _kb_h3_title(sub)
            label = f"{heading} > {m.strip()}" if m is not None else heading
            if len(cur) + len(sub) <= _CHUNK_SIZE:
                cur = f"{cur}\n{sub}" if cur else sub
                cur_label = label
            else:
                if cur.strip():
                    chunks.append((cur_label, f"[{cur_label}]\n{cur.strip()}"))
                cur, cur_label = sub, label
        if cur.strip():
            chunks.append((cur_label, f"[{cur_label}]\n{cur.strip()}"))

    # Anything still over the limit (a long section with no ### inside, a long
    # FAQ answer) is cut with overlap; the "[label]" prefix goes on every piece.
    out: list[tuple[str, str]] = []
    for h, t in chunks:
        body = t[len(f"[{h}]\n"):] if t.startswith(f"[{h}]\n") else t
        for label, piece in _split_long(h, body):
            out.append((label, f"[{label}]\n{piece}"))
    return [(h, t) for h, t in out if len(t.strip()) > 50]


# A PMAY-G-tagged chunk whose OWN heading doesn't say "Urban" can still carry a
# nested subsection that does — e.g. pmay_complete_reference.md's H2 "## 7.
# Application and Registration Process" is short enough to survive as ONE
# chunk (heading "7. Application and Registration Process", no "Urban" in it)
# while its body has both "### 7.1 PMAY-Urban" and "### 7.2 PMAY-Gramin" as
# sub-headings. The heading-only check below can't see that. Strip any such
# Urban sub-heading's block (through the next heading of any level, or end of
# text) out of a PMAY-G chunk's body before it's embedded — the Gramin content
# in the rest of the chunk is unaffected and still answers the question.
_KB_URBAN = Matcher(W("urban"))


def _kb_heading_after(text: str, nl: int) -> bool:
    """Does a heading of two to six '#' and a space/tab follow the newline at `nl`?"""
    h = nl + 1
    while h < len(text) and text[h] == "#":
        h += 1
    return 2 <= h - nl - 1 <= 6 and text[h:h + 1] in (" ", "\t")


def _strip_urban_subsections(text: str) -> str:
    """Replace each "\n##... <line with the word Urban>\n<body>" block with
    "\n": the heading line (two or more '#', after a newline, itself ending in
    a newline) through to the next newline + two-to-six-'#' heading, or the
    end of the text."""
    out, last, n = [], 0, len(text)
    i = text.find("\n##")
    while i >= 0:
        line_end = text.find("\n", i + 1)
        if line_end >= 0 and _KB_URBAN.search(text[i + 1:line_end]):
            r = text.find("\n", line_end + 1)
            while r >= 0 and not _kb_heading_after(text, r):
                r = text.find("\n", r + 1)
            r = n if r < 0 else r
            out.append(text[last:i])
            out.append("\n")
            last = r
            i = text.find("\n##", r)
        else:
            i = text.find("\n##", i + 1)
    out.append(text[last:])
    return "".join(out)


def _collect_chunks() -> list[dict]:
    out: list[dict] = []
    sources = [(f, s, "sme") for f, s in _sme_sources()] + \
              [(f, s, "web") for f, s in _web_sources()]
    for fname, scheme, source_type in sources:
        path = _DATA_PART / fname
        try:
            text = _read_source(path)
        except FileNotFoundError:
            logger.warning("kb_ingest: source not found, skipping — %s", path)
            continue
        except Exception as e:  # noqa: BLE001 — one unreadable file must not stop the ingest
            logger.warning("kb_ingest: could not read %s (%s) — skipping", path.name, e)
            continue
        text = _strip_internal_notes(text)
        for heading, chunk_text in _chunk(text):
            # A PMAY doc can carry both Gramin and Urban sections under one
            # filename-derived "PMAY-G" tag (e.g. data/web/PMAY_Wikipedia.md's
            # "Income Categories (Urban)", "Eligibility Conditions (Urban
            # CLSS)"). Re-tag those sections "PMAY-U" — a scheme this bot
            # doesn't hold — so a PMAY-G-scoped retrieval (vectorstore.search's
            # scheme filter) can never surface Urban content in a PMAY-G answer.
            section_scheme = scheme
            if scheme == "PMAY-G" and _KB_URBAN.search(heading):
                section_scheme = "PMAY-U"
            elif scheme == "PMAY-G":
                chunk_text = _strip_urban_subsections(chunk_text)
            out.append({"scheme": section_scheme, "doc": fname, "heading": heading,
                        "text": chunk_text, "source_type": source_type})
    return out


async def _embed_all(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    batch = settings.EMBED_BATCH_SIZE
    for i in range(0, len(texts), batch):
        vectors.extend(await llm.call_embedding(texts[i : i + batch]))
    return vectors


async def _embedding_dim() -> int | None:
    """Vector size the configured embedding model returns now, or None when the
    model cannot be reached (then the size check is skipped, as before)."""
    try:
        vecs = await llm.call_embedding(["dimension check"])
        return len(vecs[0]) if vecs else None
    except Exception as e:  # noqa: BLE001 — unknown size: keep the other checks
        logger.warning("kb_ingest: could not read the embedding size (%s)", e)
        return None


async def ingest_kb(force: bool = False) -> dict:
    """Build (or rebuild) the Qdrant KB collection. Returns a small status dict."""
    chunks = _collect_chunks()
    if not chunks:
        logger.warning("kb_ingest: no source chunks found under %s", _DATA_PART)
        return {"ingested": 0, "skipped": True, "reason": "no sources"}

    existing = await vectorstore.collection_count()
    want_schemes = {c["scheme"] for c in chunks}
    if not force and existing >= int(len(chunks) * 0.9):
        # The count alone only says the collection is roughly the right SIZE,
        # which is not the same as it holding the right CONTENT. A scheme added
        # to data/ but never ingested answers "not covered" for every question
        # forever, and a count-based check cannot see it whenever the new
        # scheme is under 10% of the corpus (measured: 18 chunks or fewer on top
        # of the existing 170 never trips the threshold). Confirm every scheme
        # the sources produce is actually PRESENT before trusting the skip.
        have_schemes = await vectorstore.distinct_schemes()
        missing = want_schemes - have_schemes
        # The skip checks never looked at the vector SIZE (D-067, 2026-10-24): an
        # EMBEDDING_PROVIDER change without a new QDRANT_COLLECTION left a 384-dim
        # KB that every 1024-dim question fails to search, so each knowledge
        # question answered "not covered" and a restart did not repair it.
        have_dim, want_dim = await vectorstore.collection_dim(), await _embedding_dim()
        if have_dim and want_dim and have_dim != want_dim:
            logger.error("kb_ingest: %s holds %d-dim vectors but the embedding model "
                         "returns %d — rebuilding", settings.QDRANT_COLLECTION, have_dim, want_dim)
        elif settings.RAG_SPARSE_MODEL and not await vectorstore.has_sparse():
            # Built before the keyword vector existed (Phase 3): hybrid search
            # would silently run meaning-only on it, so rebuild with both.
            logger.warning("kb_ingest: %s has no keyword (BM25) vector — rebuilding",
                           settings.QDRANT_COLLECTION)
        elif missing:
            logger.warning(
                "kb_ingest: collection holds %d points but is MISSING %s — "
                "rebuilding (a scheme with no points answers 'not covered' for "
                "every question)",
                existing, ", ".join(sorted(missing)),
            )
        else:
            logger.info("kb_ingest: collection already holds %d points (~%d expected) "
                        "covering %s — skipping",
                        existing, len(chunks), ", ".join(sorted(have_schemes)))
            return {"ingested": 0, "skipped": True, "points": existing}

    n_docs = len(_sme_sources()) + len(_web_sources())
    logger.info("kb_ingest: embedding %d chunks from %d docs", len(chunks), n_docs)
    vectors = await _embed_all([c["text"] for c in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(f"embedding count {len(vectors)} != chunk count {len(chunks)}")

    # The BM25 keyword vector of each piece (Phase 3 hybrid search); None when
    # RAG_SPARSE_MODEL is off or the model cannot load — then meaning only.
    sparse = None
    if settings.RAG_SPARSE_MODEL:
        from app import local_rank
        sparse = await local_rank.sparse_docs([c["text"] for c in chunks])

    await vectorstore.recreate_collection(dim=len(vectors[0]), sparse=sparse is not None)
    points = [
        models.PointStruct(
            id=str(uuid.uuid4()),
            vector=({"": vec, vectorstore.SPARSE_NAME: models.SparseVector(indices=sp[0], values=sp[1])}
                    if sparse is not None else vec),
            payload=chunk)
        for vec, chunk, sp in zip(vectors, chunks, sparse or [None] * len(chunks))
    ]
    for i in range(0, len(points), 128):
        await vectorstore.upsert(points[i : i + 128])

    logger.info("kb_ingest: upserted %d points into %s", len(points), settings.QDRANT_COLLECTION)
    return {"ingested": len(points), "skipped": False}
