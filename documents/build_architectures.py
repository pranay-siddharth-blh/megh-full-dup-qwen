"""Builds documents/architectures.pdf: one architecture per page (diagram on top, explanation below).

Style follows documents/LangGraph_Guide.docx: few boxes, a bold name + one short grey line per box,
light fills with coloured borders, labelled arrows, plenty of white space.

Run from the repo root:  meghalaya/.venv/Scripts/python.exe documents/build_architectures.py
Add an architecture: write page_<name>(c, n) and append it to PAGES.
Facts are taken from the code, config and deploy files (as of AS_OF).
"""
import math
import sys

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, Paragraph, Spacer, Table, TableStyle

OUT = sys.argv[1] if len(sys.argv) > 1 else "documents/architectures.pdf"
AS_OF = "27 October 2026"

pdfmetrics.registerFont(TTFont("UI", r"C:\Windows\Fonts\segoeui.ttf"))
pdfmetrics.registerFont(TTFont("UI-B", r"C:\Windows\Fonts\segoeuib.ttf"))
pdfmetrics.registerFont(TTFont("UI-SB", r"C:\Windows\Fonts\seguisb.ttf"))
pdfmetrics.registerFont(TTFont("UI-I", r"C:\Windows\Fonts\segoeuii.ttf"))
pdfmetrics.registerFontFamily("UI", normal="UI", bold="UI-B", italic="UI-I", boldItalic="UI-B")

W, H = A4
INK = HexColor("#1F1F1F")
GREY = HexColor("#5A5A5A")
SOFT = HexColor("#8A8A8A")
ARROW = HexColor("#4A4A4A")
NAVY = HexColor("#1B2A41")
RULE = HexColor("#DADADA")

# (fill, border) — the LangGraph guide palette
P = {
    "blue":   (HexColor("#E3EEFB"), HexColor("#2D74DA")),
    "green":  (HexColor("#DFF3EA"), HexColor("#1E9E6E")),
    "orange": (HexColor("#FDEBE4"), HexColor("#E8663D")),
    "red":    (HexColor("#F9E1E1"), HexColor("#D9433F")),
    "purple": (HexColor("#E8E6F6"), HexColor("#4B3FB0")),
    "gold":   (HexColor("#FDF3DB"), HexColor("#C8860A")),
    "grey":   (HexColor("#F1F1F0"), HexColor("#8A8A8A")),
    "teal":   (HexColor("#DDF2F2"), HexColor("#178A8A")),
}


# ── primitives ────────────────────────────────────────────────────────────────
def node(c, x, y, w, h, fam, title, sub="", tsize=10.5, ssize=8, fill=None):
    """A rounded box: bold title + one grey line, centred."""
    f, b = P[fam]
    c.setFillColor(fill or f)
    c.setStrokeColor(b)
    c.setLineWidth(1.4)
    c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    cx = x + w / 2
    while tsize > 7 and pdfmetrics.stringWidth(title, "UI-B", tsize) > w - 12:
        tsize -= 0.5
    if sub:
        ty = y + h / 2 + 1.5
        c.setFont("UI-B", tsize); c.setFillColor(INK)
        c.drawCentredString(cx, ty, title)
        c.setFont("UI", ssize); c.setFillColor(GREY)
        c.drawCentredString(cx, ty - ssize - 4, sub)
    else:
        c.setFont("UI-B", tsize); c.setFillColor(INK)
        c.drawCentredString(cx, y + h / 2 - tsize / 3, title)


def pill(c, cx, cy, w, h, text):
    c.setFillColor(INK)
    c.roundRect(cx - w / 2, cy - h / 2, w, h, h / 2, stroke=0, fill=1)
    c.setFillColor(white); c.setFont("UI-B", 9.5)
    c.drawCentredString(cx, cy - 3.3, text)


def zone(c, x, y, w, h, label, fam="grey", bottom=False):
    f, b = P[fam]
    c.setFillColor(HexColor("#FAFAFA"))
    c.setStrokeColor(b); c.setLineWidth(1)
    c.setDash(5, 3)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)
    c.setDash()
    c.setFont("UI-B", 9); c.setFillColor(b)
    c.drawString(x + 10, y + 8 if bottom else y + h - 15, label)


def _head(c, a, b, color):
    ang = math.atan2(b[1] - a[1], b[0] - a[0])
    L, Wd = 7, 3.6
    l = (b[0] - L * math.cos(ang) + Wd * math.sin(ang), b[1] - L * math.sin(ang) - Wd * math.cos(ang))
    r = (b[0] - L * math.cos(ang) - Wd * math.sin(ang), b[1] - L * math.sin(ang) + Wd * math.cos(ang))
    p = c.beginPath(); p.moveTo(*b); p.lineTo(*l); p.lineTo(*r); p.close()
    c.setFillColor(color)
    c.drawPath(p, stroke=0, fill=1)


def arrow(c, pts, color=ARROW, both=False, dashed=False, width=1.3):
    c.setStrokeColor(color); c.setLineWidth(width)
    if dashed:
        c.setDash(4, 3)
    p = c.beginPath(); p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    c.drawPath(p, stroke=1, fill=0)
    c.setDash()
    _head(c, pts[-2], pts[-1], color)
    if both:
        _head(c, pts[1], pts[0], color)


def label(c, x, y, text, color=GREY, size=8, align="left", bold=False):
    font = "UI-SB" if bold else "UI"
    c.setFont(font, size)
    tw = pdfmetrics.stringWidth(text, font, size)
    x0 = {"left": x, "center": x - tw / 2, "right": x - tw}[align]
    c.setFillColor(white)
    c.rect(x0 - 2, y - 2.5, tw + 4, size + 2.5, stroke=0, fill=1)
    c.setFillColor(color)
    c.drawString(x0, y, text)


def badge(c, x, y, n, fam="grey", r=7.5):
    _, b = P[fam]
    c.setFillColor(b); c.setStrokeColor(white); c.setLineWidth(1.2)
    c.circle(x, y, r, stroke=1, fill=1)
    c.setFillColor(white); c.setFont("UI-B", 8)
    c.drawCentredString(x, y - 2.8, str(n))


def header(c, num, title, lead):
    c.setFont("UI-B", 20); c.setFillColor(NAVY)
    c.drawString(40, H - 58, f"{num}.  {title}")
    c.setFont("UI", 10); c.setFillColor(GREY)
    c.drawString(40, H - 76, lead)
    c.setStrokeColor(RULE); c.setLineWidth(0.8)
    c.line(40, H - 88, W - 40, H - 88)


def footer(c, page, source):
    c.setStrokeColor(RULE); c.setLineWidth(0.6)
    c.line(40, 38, W - 40, 38)
    c.setFont("UI", 7); c.setFillColor(SOFT)
    c.drawRightString(W - 40, 26, f"Megh One AI · Architectures · {AS_OF} · page {page}")


# explanation block (below the diagram)
S_H = ParagraphStyle("h", fontName="UI-B", fontSize=11, leading=14, textColor=NAVY, spaceBefore=2, spaceAfter=4)
S_P = ParagraphStyle("p", fontName="UI", fontSize=10, leading=14.5, textColor=INK, spaceAfter=6)
S_C = ParagraphStyle("c", fontName="UI", fontSize=8.2, leading=10.5, textColor=INK)
S_CB = ParagraphStyle("cb", parent=S_C, fontName="UI-B")
S_TH = ParagraphStyle("th", parent=S_C, fontName="UI-B", textColor=white)


def table(rows, widths, head):
    data = [[Paragraph(h, S_TH) for h in head]]
    for r in rows:
        data.append([Paragraph(str(r[0]), S_CB)] + [Paragraph(str(v), S_C) for v in r[1:]])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#F6F7F9")]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def explain(c, flow, top):
    fr = Frame(40, 44, W - 80, top - 44, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    fr.addFromList(flow, c)
    if flow:
        print("  !! explanation overflow:", len(flow), "items did not fit", file=sys.stderr)


def divider(c, y, text="How to read it"):
    c.setStrokeColor(RULE); c.setLineWidth(0.8)
    c.line(40, y, W - 40, y)


# ── cover ─────────────────────────────────────────────────────────────────────
def page_cover(c, n):
    c.setFillColor(NAVY)
    c.rect(0, H - 8, W, 8, stroke=0, fill=1)
    c.setFont("UI-SB", 11); c.setFillColor(P["blue"][1])
    c.drawString(60, H - 230, "MEGH ONE AI  ·  MEGHALAYA CONVERSATIONAL ANALYTICS")
    c.setFont("UI-B", 34); c.setFillColor(NAVY)
    c.drawString(60, H - 275, "Architectures")
    c.setFont("UI", 12.5); c.setFillColor(GREY)
    c.drawString(60, H - 302, "Security, technology, integration and infrastructure")
    c.setStrokeColor(RULE); c.setLineWidth(1)
    c.line(60, H - 330, W - 60, H - 330)
    items = [("1", "Security architecture", "How a question is checked, layer by layer, before it can read data", "red"),
             ("2", "Technology architecture", "Which products the system is built from, and what each one does", "blue"),
             ("3", "Integration architecture", "How the service connects to every system around it", "green"),
             ("4", "Infrastructure architecture", "Where each part runs: servers, network and ports", "purple")]
    y = H - 375
    for num, t, d, fam in items:
        badge(c, 72, y + 4, num, fam, r=10)
        c.setFont("UI-B", 13); c.setFillColor(INK); c.drawString(94, y + 6, t)
        c.setFont("UI", 10); c.setFillColor(GREY); c.drawString(94, y - 9, d)
        y -= 48


# ── 1. security ───────────────────────────────────────────────────────────────
def page_security(c, n):
    header(c, 1, "Security architecture", "A question must pass every layer, top to bottom, before it can read any data.")
    layers = [
        ("grey",   "Network & firewall",  "ESDS vFirewall · VPN-only data host",         "Direct access to the database and the AI models"),
        ("blue",   "Web server (nginx)",  "HTTPS (TLS 1.2/1.3) · WAF · rate limits",     "Eavesdropping, common web attacks, request floods"),
        ("teal",   "App protection",      "Security headers · size and rate limits",     "Oversized requests, clickjacking, leaked error details"),
        ("purple", "Login & roles",       "Hashed passwords · signed token · 8 roles",   "Anyone without an account, or outside their area"),
        ("gold",   "Question guardrails", "Rule check, then a small AI model check",     "Harmful, abusive or manipulative questions"),
        ("red",    "SQL safety",          "One read-only query · allowed tables only",   "Changing data, private tables, system functions"),
        ("orange", "Answer check",        "Every number must come from the result",      "Made-up or wrong figures in the answer"),
    ]
    x, w, h, gap = 70, 220, 42, 16
    top = H - 112
    pill(c, x + w / 2, top - 8, 150, 22, "Officer's question")
    y = top - 30
    arrow(c, [(x + w / 2, top - 19), (x + w / 2, y - 1)])
    label(c, 330, top - 11, "WHAT EACH LAYER STOPS", SOFT, 8, bold=True)
    for i, (fam, t, s, stops) in enumerate(layers):
        y -= h
        node(c, x, y, w, h, fam, t, s)
        badge(c, x + w, y + h, i + 1, fam)
        # what it stops
        c.setStrokeColor(RULE); c.setLineWidth(0.8); c.setDash(2, 2)
        c.line(x + w + 8, y + h / 2, 322, y + h / 2); c.setDash()
        c.setFont("UI", 8.6); c.setFillColor(INK)
        c.drawString(330, y + h / 2 - 3, stops)
        nxt = y - gap
        arrow(c, [(x + w / 2, y), (x + w / 2, nxt + 1)])
        y = nxt
    y -= h
    node(c, x, y, w, h, "green", "Scheme data (megh_db)", "Read through a restricted login only")
    data_y = y
    # audit box on the right, bottom
    node(c, 330, data_y, 225, h, "grey", "Audit log", "Every layer records who, what, allowed or denied", ssize=7.8)
    bottom = data_y - 14

    divider(c, bottom)
    flow = [
        Spacer(1, 10),
        Paragraph("What this shows", S_H),
        Paragraph("This diagram shows how every officer's question is protected before it can reach the scheme data. The question passes seven layers in order: network, web server, app protection, login and roles, guardrails, SQL safety and answer check. Each layer blocks a different risk (shown on the right), and every decision is written to the audit log.", S_P),
    ]
    explain(c, flow, bottom - 2)
    footer(c, n, "docs/SECURITY.md · app/middleware/ · app/auth.py · app/sql_guard.py · deploy/nginx/ · deploy/sql/")


# ── 2. technology ─────────────────────────────────────────────────────────────
def page_technology(c, n):
    header(c, 2, "Technology architecture", "The products the system is built from, layer by layer, and what each one does.")
    rows = [
        ("blue",   "User interface",  [("React 18", "chat + admin screens"), ("Vite 6", "builds the UI"), ("Chart.js 4", "charts in answers")]),
        ("teal",   "Web server",      [("nginx", "HTTPS + proxy"), ("ModSecurity", "web firewall (OWASP)")]),
        ("purple", "Application",     [("Python 3.11", "language"), ("FastAPI", "API + streaming"), ("Uvicorn", "2 workers per server")]),
        ("orange", "AI workflow",     [("LangGraph", "runs the steps"), ("SQLGlot", "checks the SQL"), ("rapidfuzz", "matches place names")]),
        ("red",    "AI models",       [("Qwen3-4B", "routes questions"), ("Qwen3.5-9B", "writes answers"), ("Qwen3-Coder-30B", "writes SQL"), ("Embedding + ASR", "search · voice to text")]),
        ("green",  "Data & search",   [("PostgreSQL 18", "scheme data + app data"), ("Qdrant", "document search"), ("Redis", "optional shared cache")]),
        ("grey",   "Runs on",         [("Ubuntu VMs", "two app servers"), ("systemd", "keeps the app running"), ("vLLM gateway", "GPU model server")]),
    ]
    lx, lw = 40, 100
    cx0, cx1 = 152, W - 40
    rh, gap = 54, 16
    y = H - 112
    for fam, name, chips in rows:
        y -= rh
        f, b = P[fam]
        c.setFillColor(b)
        c.roundRect(lx, y, lw, rh, 6, stroke=0, fill=1)
        c.setFont("UI-B", 10); c.setFillColor(white)
        c.drawCentredString(lx + lw / 2, y + rh / 2 - 3.5, name)
        k = len(chips)
        g = 10
        cw = (cx1 - cx0 - g * (k - 1)) / k
        for i, (t, s) in enumerate(chips):
            node(c, cx0 + i * (cw + g), y, cw, rh, fam, t, s, tsize=10, ssize=7.9)
        y -= gap
    # flow hint
    c.setFont("UI-I", 8); c.setFillColor(SOFT)
    c.drawString(cx0, y + 2, "Top: what the officer sees.  Bottom: what it runs on.")
    bottom = y - 10

    divider(c, bottom)
    flow = [
        Spacer(1, 10),
        Paragraph("What this shows", S_H),
        Paragraph('This diagram shows the products Megh One AI is built from, one layer per row, from the screens the officer sees down to the servers it runs on. Each box names one product and its job: React for the screens, FastAPI and LangGraph for the application and AI workflow, the Qwen models for understanding and answering, and PostgreSQL and Qdrant for the data.', S_P),
    ]
    explain(c, flow, bottom - 2)
    footer(c, n, "requirements.txt · frontend/package.json · app/config.py · docs/DECISIONS.md · deploy/")


# ── 3. integration ────────────────────────────────────────────────────────────
def page_integration(c, n):
    header(c, 3, "Integration architecture", "How the Megh One AI service connects to every system around it.")
    t = H - 112
    # row 1: browser + ops
    node(c, 120, t - 46, 180, 46, "blue", "Officer's browser", "chat and admin screens")
    node(c, 365, t - 46, 175, 46, "grey", "Operations team", "health checks and metrics")
    # row 2: nginx
    ny = t - 140
    node(c, 120, ny, 180, 46, "teal", "nginx", "web server on each app VM")
    arrow(c, [(210, t - 46), (210, ny + 46)], both=True)
    badge(c, 210, ny + 66, 1, "blue")
    label(c, 222, ny + 63, "HTTPS 443 · login token", GREY, 8)
    arrow(c, [(452, t - 46), (452, ny + 23), (300, ny + 23)])
    badge(c, 452, ny + 46, 2, "grey")
    label(c, 464, ny + 43, "HTTPS · metrics key", GREY, 8)
    # row 3: app
    ay = ny - 125
    f, b = P["purple"]
    c.setFillColor(f); c.setStrokeColor(b); c.setLineWidth(1.8)
    c.roundRect(55, ay, W - 110, 58, 8, stroke=1, fill=1)
    c.setFont("UI-B", 13); c.setFillColor(INK)
    c.drawCentredString(W / 2, ay + 33, "Megh One AI service")
    c.setFont("UI", 8.6); c.setFillColor(GREY)
    c.drawCentredString(W / 2, ay + 17, "FastAPI · LangGraph workflow · login, history and admin APIs")
    arrow(c, [(210, ny), (210, ay + 58)])
    badge(c, 210, ny - 27, 3, "teal")
    label(c, 222, ny - 30, "local HTTP :8401", GREY, 8)
    # row 4: external systems
    ey = ay - 140
    bw = 150
    xs = [55, (W - bw) / 2, W - 55 - bw]
    ext = [("red", "AI model gateway", "Qwen models · 10.48.242.4"),
           ("green", "PostgreSQL · megh_db", "scheme data + app data"),
           ("gold", "Qdrant", "scheme document search")]
    texts = [("HTTPS 443", "API key per model"), ("SQL · port 5432", "3 separate logins"), ("HTTP 6333", "search only")]
    for i, ((fam, tt, ss), (l1, l2), x) in enumerate(zip(ext, texts, xs)):
        node(c, x, ey, bw, 50, fam, tt, ss)
        mx = x + bw / 2
        arrow(c, [(mx, ay), (mx, ey + 50)], both=(i < 2))
        badge(c, mx, ay - 30, 4 + i, fam)
        label(c, mx + 12, ay - 28, l1, GREY, 8)
        label(c, mx + 12, ay - 40, l2, SOFT, 7.6)
    # row 5: feeders
    fy = ey - 100
    node(c, xs[1], fy, bw, 46, "grey", "Ingestion team", "loads the scheme data")
    node(c, xs[2], fy, bw, 46, "grey", "Document loader", "loads scheme documents")
    arrow(c, [(xs[1] + bw / 2, fy + 46), (xs[1] + bw / 2, ey)], SOFT, dashed=True)
    arrow(c, [(xs[2] + bw / 2, fy + 46), (xs[2] + bw / 2, ey)], SOFT, dashed=True)
    badge(c, xs[1] + bw / 2, fy + 66, 7, "grey")
    badge(c, xs[2] + bw / 2, fy + 66, 8, "grey")
    # legend
    lx, ly = 60, fy + 30
    c.setStrokeColor(ARROW); c.setLineWidth(1.3); c.line(lx, ly, lx + 26, ly)
    c.setFont("UI", 8); c.setFillColor(GREY); c.drawString(lx + 32, ly - 3, "live call while answering")
    c.setStrokeColor(SOFT); c.setDash(4, 3); c.line(lx, ly - 16, lx + 26, ly - 16); c.setDash()
    c.drawString(lx + 32, ly - 19, "data loaded by another team")
    bottom = fy - 14

    divider(c, bottom)
    flow = [
        Spacer(1, 10),
        Paragraph("What this shows", S_H),
        Paragraph('This diagram shows how the Megh One AI service connects to the systems around it. Officers reach it through nginx; the service then calls the AI models, reads the scheme data from PostgreSQL and searches scheme documents in Qdrant. Solid arrows are live calls during a question; dashed arrows are data loaded by other teams.', S_P),
    ]
    explain(c, flow, bottom - 2)
    footer(c, n, "app/routers/ · app/llm.py · app/db.py · app/vectorstore.py · app/config.py · deploy/nginx/")


# ── 4. infrastructure ─────────────────────────────────────────────────────────
def page_infrastructure(c, n):
    header(c, 4, "Infrastructure architecture", "Where each part runs: the users, two application servers and the data & AI server.")
    t = H - 108
    # users
    zone(c, 40, t - 76, W - 80, 76, "Users", "blue")
    node(c, 55, t - 66, 160, 40, "blue", "Officers", "browser on any device", fill=white)
    node(c, 228, t - 66, 140, 40, "blue", "Administrators", "office network only", fill=white)
    node(c, 400, t - 66, 140, 40, "grey", "Developers", "laptop + Fortinet VPN", fill=white)
    # firewall
    fy = t - 150
    node(c, 165, fy, 265, 36, "teal", "ESDS firewall / load balancer", "only HTTPS 443 is open")
    arrow(c, [(135, t - 66), (135, fy + 18), (165, fy + 18)])
    arrow(c, [(298, t - 66), (298, fy + 36)])
    badge(c, 298, t - 84, 1, "blue")
    # app tier
    zy = fy - 175
    zone(c, 40, zy, W - 80, 140, "Application servers (ESDS cloud)", "purple")
    vms = [55, 305]
    for i, vx in enumerate(vms):
        vw = 235
        c.setFillColor(white); c.setStrokeColor(P["purple"][1]); c.setLineWidth(1.4)
        c.roundRect(vx, zy + 10, vw, 106, 6, stroke=1, fill=1)
        c.setFont("UI-B", 10.5); c.setFillColor(INK)
        c.drawString(vx + 10, zy + 100, f"App server {i + 1}")
        c.setFont("UI", 7.8); c.setFillColor(GREY)
        c.drawRightString(vx + vw - 10, zy + 100, "Ubuntu · Python 3.11")
        node(c, vx + 10, zy + 58, vw - 20, 34, "teal", "nginx  :443", "HTTPS, firewall rules", tsize=9.5, ssize=7.6)
        node(c, vx + 10, zy + 18, vw - 20, 34, "purple", "Megh One AI  :8401", "2 workers · restarts if it stops", tsize=9.5, ssize=7.6)
    arrow(c, [(250, fy), (250, zy + 116)])
    arrow(c, [(345, fy), (345, zy + 116)])
    badge(c, 298, fy - 10, 2, "teal")
    # data & AI server
    dy = zy - 165
    zone(c, 40, dy, W - 80, 130, "Data & AI server  10.48.242.4  (private network)", "green", bottom=True)
    bw = 155
    xs = [55, (W - bw) / 2, W - 55 - bw]
    svc = [("green", "PostgreSQL 18  :5432", "megh_db: scheme + app data"),
           ("red", "AI model gateway  :443", "Qwen models on GPU (vLLM)"),
           ("gold", "Qdrant  :6333", "scheme document search")]
    for (fam, tt, ss), x in zip(svc, xs):
        node(c, x, dy + 50, bw, 46, fam, tt, ss, tsize=9.8)
    c.setFont("UI", 8); c.setFillColor(GREY)
    c.drawCentredString(W / 2, dy + 30, "Database connection limits: megh_app 30 · megh_readonly 25 · megh_chatbot 20 (agreed with the ingestion team)")
    arrow(c, [(172, zy + 10), (172, dy + 96)], both=True)
    arrow(c, [(W / 2, zy + 10), (W / 2, dy + 96)], both=True)
    arrow(c, [(423, zy + 10), (423, dy + 96)], both=True)
    badge(c, 172, zy - 10, 3, "green")
    badge(c, W / 2, zy - 10, 3, "green")
    badge(c, 423, zy - 10, 3, "green")
    # developer VPN path
    arrow(c, [(540, t - 46), (W - 46, t - 46), (W - 46, dy + 73), (W - 55, dy + 73)], SOFT, dashed=True)
    badge(c, W - 46, zy + 70, 4, "grey")
    bottom = dy - 14

    divider(c, bottom)
    flow = [
        Spacer(1, 10),
        Paragraph("What this shows", S_H),
        Paragraph('This diagram shows where each part of the system runs. Users come in through the ESDS firewall to two identical application servers (nginx plus the Megh One AI app), which connect to one private server holding the database, the AI models and the document search. Developers reach that private server over the Fortinet VPN.', S_P),
    ]
    explain(c, flow, bottom - 2)
    footer(c, n, "deploy/DEPLOYMENT.md · deploy/systemd/ · deploy/nginx/ · app/config.py · docs/ARCHITECTURE.md")


PAGES = [page_cover, page_security, page_technology, page_integration, page_infrastructure]

if __name__ == "__main__":
    cv = canvas.Canvas(OUT, pagesize=A4)
    cv.setTitle("Megh One AI — Architectures")
    cv.setSubject("Security, technology, integration and infrastructure architecture")
    for i, fn in enumerate(PAGES):
        fn(cv, i)
        cv.showPage()
    cv.save()
    print("wrote", OUT)
