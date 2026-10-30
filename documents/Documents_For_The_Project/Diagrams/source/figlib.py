"""Tiny HTML diagram kit: absolute boxes + one SVG overlay for arrows; rendered by headless Edge."""
import html as _h
import os
import subprocess

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
VER = "v2.0 · 29-Oct-2026"

FAM = {  # fill, border, title colour
    "blue":   ("#EEF4FF", "#2D6BDA", "#0F172A"),
    "teal":   ("#ECFDF9", "#0F8C80", "#0F172A"),
    "green":  ("#EEFBF3", "#178A4C", "#0F172A"),
    "purple": ("#F5F3FF", "#7C3AED", "#0F172A"),
    "orange": ("#FFF6EE", "#C2410C", "#0F172A"),
    "gold":   ("#FEF9E7", "#B7791F", "#0F172A"),
    "grey":   ("#F3F5F8", "#475569", "#0F172A"),
    "red":    ("#FEF1F1", "#D02E2E", "#0F172A"),
    "pink":   ("#FDF0F6", "#BE185D", "#0F172A"),
    "white":  ("#FFFFFF", "#6366F1", "#0F172A"),
}

CSS = """
*{box-sizing:border-box} body{margin:0;background:#fff;font-family:'Segoe UI',Arial,sans-serif;color:#0F172A}
#c{position:relative;overflow:hidden;background:#fff}
.ttl{position:absolute;left:0;right:0;text-align:center;font-weight:700}
.sub{position:absolute;left:0;right:0;text-align:center;color:#475569}
.b{position:absolute;border-radius:9px;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:4px 8px;line-height:1.25}
.b .t{font-weight:650} .b .s{color:#475569;margin-top:3px}
.mono .t{font-family:Consolas,'Cascadia Mono',monospace;font-weight:700}
.tag{position:absolute;background:#fff;border:1px solid #CBD5E1;border-radius:6px;padding:1px 7px;font-size:11.5px;white-space:nowrap;transform:translate(-50%,-50%)}
.sec{position:absolute;font-size:12.5px;font-weight:700;letter-spacing:1.6px;color:#64748B;text-transform:uppercase}
.grp{position:absolute;border:1.5px solid #CBD5E1;border-radius:12px;background:#F8FAFC}
.foot{position:absolute;font-size:11.5px;color:#94A3B8}
.leg{position:absolute;border:1.5px solid #CBD5E1;border-radius:10px;display:flex;align-items:center;gap:22px;padding:0 20px;font-size:13px;color:#334155}
.sw{display:inline-block;width:20px;height:16px;border-radius:4px;border:2px solid;vertical-align:-3px;margin-right:7px}
.txt{position:absolute;font-size:13px;color:#334155;line-height:1.45}
.ent{position:absolute;border-radius:9px;border:2px solid;background:#fff;overflow:hidden}
.ent .h{color:#fff;font-weight:700;text-align:center;padding:6px 4px;font-size:14px}
.ent .r{padding:1px 11px;font-size:12.3px;color:#334155;white-space:nowrap}
.ent .pk{font-weight:700;color:#0F172A} .ent .fk{font-style:italic;color:#1E3A8A} .ent .nw{color:#B45309;font-weight:600}
"""


class Fig:
    def __init__(self, w, h, title, sub="", banner=False, dark=False):
        self.w, self.h, self.parts, self.svg, self.bg = w, h, [], [], []
        self.markers = {}
        self.dark = dark
        if banner:
            self.parts.append(f'<div style="position:absolute;left:0;top:0;width:{w}px;height:78px;background:#13294B"></div>')
            self.parts.append(f'<div class="ttl" style="top:10px;font-size:27px;color:#fff">{_h.escape(title)}</div>')
            self.parts.append(f'<div class="sub" style="top:48px;font-size:14.5px;color:#C7D7F0">{_h.escape(sub)}</div>')
        else:
            col = "#F8FAFC" if dark else "#0F172A"
            self.parts.append(f'<div class="ttl" style="top:12px;font-size:27px;color:{col}">{_h.escape(title)}</div>')
            self.parts.append(f'<div class="sub" style="top:50px;font-size:14.5px;color:{"#CBD5E1" if dark else "#475569"}">{_h.escape(sub)}</div>')

    # ---- primitives -------------------------------------------------------
    def raw(self, s):
        self.parts.append(s)

    def box(self, x, y, w, h, fam, t, s="", mono=False, dashed=False, ts=15, ss=12.3, fill=None, tcol=None, bw=2):
        f, b, tc = FAM[fam]
        style = "dashed" if dashed else "solid"
        cls = "b mono" if mono else "b"
        sub = f'<div class="s" style="font-size:{ss}px">{s}</div>' if s else ""
        self.parts.append(
            f'<div class="{cls}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;background:{fill or f};'
            f'border:{bw}px {style} {b}"><div class="t" style="font-size:{ts}px;color:{tcol or tc}">{t}</div>{sub}</div>')
        return (x, y, w, h)

    def pill(self, x, y, w, h, t, bg="#111827"):
        self.parts.append(f'<div class="b" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;background:{bg};'
                          f'border-radius:{h/2}px;color:#fff;font-weight:700;font-size:15px">{t}</div>')

    def tag(self, x, y, t, col="#334155", border="#CBD5E1", bg="#fff"):
        self.parts.append(f'<div class="tag" style="left:{x}px;top:{y}px;color:{col};border-color:{border};background:{bg}">{t}</div>')

    def sec(self, x, y, t, col="#64748B"):
        self.parts.append(f'<div class="sec" style="left:{x}px;top:{y}px;color:{col}">{t}</div>')

    def grp(self, x, y, w, h, label="", col="#64748B", bg="#F8FAFC", border="#CBD5E1"):
        self.bg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{bg}" stroke="{border}" stroke-width="1.5"/>')
        if label:
            self.sec(x + 18, y + 12, label, col)

    def text(self, x, y, w, t, size=13, col="#334155", align="left", weight=400):
        self.parts.append(f'<div class="txt" style="left:{x}px;top:{y}px;width:{w}px;font-size:{size}px;color:{col};text-align:{align};font-weight:{weight}">{t}</div>')

    def ent(self, x, y, w, name, col, rows):
        body = []
        for r in rows:
            k, t = (r if isinstance(r, tuple) else ("", r))
            if k == "pk":
                body.append(f'<div class="r pk">PK&nbsp; <u>{t}</u></div>')
            elif k == "fk":
                body.append(f'<div class="r fk">FK {t}</div>')
            elif k == "new":
                body.append(f'<div class="r nw">{t} &nbsp;★</div>')
            else:
                body.append(f'<div class="r">{t}</div>')
        h = 34 + 20.5 * len(rows) + 10
        self.parts.append(f'<div class="ent" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;border-color:{col}">'
                          f'<div class="h" style="background:{col}">{name}</div><div style="padding-top:5px">{"".join(body)}</div></div>')
        return (x, y, w, h)

    def _marker(self, col):
        if col not in self.markers:
            mid = f"m{len(self.markers)}"
            self.markers[col] = mid
            self.svg.insert(0, f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7.5" markerHeight="7.5" '
                               f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
        return self.markers[col]

    def arrow(self, pts, col="#334155", dash=False, w=2, head=True, both=False, label=None, lpos=None, lcol=None):
        mid = self._marker(col)
        d = " ".join(f"{x},{y}" for x, y in pts)
        da = ' stroke-dasharray="7 5"' if dash else ""
        me = f' marker-end="url(#{mid})"' if head else ""
        ms = f' marker-start="url(#{mid})"' if both else ""
        self.svg.append(f'<polyline points="{d}" fill="none" stroke="{col}" stroke-width="{w}"{da}{me}{ms} stroke-linejoin="round"/>')
        if label:
            if lpos is None:
                (x1, y1), (x2, y2) = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
                lpos = ((x1 + x2) / 2, (y1 + y2) / 2)
            self.tag(lpos[0], lpos[1], label, lcol or col, "#CBD5E1")

    def line(self, x1, y1, x2, y2, col="#94A3B8", dash="4 4", w=1.5):
        self.svg.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="{w}" stroke-dasharray="{dash}"/>')

    def rect(self, x, y, w, h, fill, rx=4, stroke="none"):
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}"/>')

    def legend(self, y, items, foot, h=46, x=30, w=None):
        w = w or self.w - 2 * x
        cells = []
        for kind, a, t in items:
            if kind == "sw":
                f, b, _ = FAM[a]
                cells.append(f'<span><span class="sw" style="background:{f};border-color:{b}"></span>{t}</span>')
            elif kind == "ln":
                col, dash = a
                da = 'stroke-dasharray="6 4"' if dash else ""
                cells.append(f'<span><svg width="44" height="12" style="vertical-align:-1px;margin-right:6px"><line x1="0" y1="6" x2="34" y2="6" stroke="{col}" stroke-width="2" {da}/><path d="M34,1 L44,6 L34,11 z" fill="{col}"/></svg>{t}</span>')
            else:
                cells.append(f"<span>{t}</span>")
        bg = "#111827" if self.dark else "#fff"
        col = "#E2E8F0" if self.dark else "#334155"
        self.parts.append(f'<div class="leg" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px;background:{bg};color:{col};border-color:{"#334155" if self.dark else "#CBD5E1"}">{"".join(cells)}'
                          f'<span style="margin-left:auto;font-size:11.5px;color:#94A3B8">Megh One AI · {foot} · {VER}</span></div>')

    def html(self):
        bg = "#0B1220" if self.dark else "#fff"
        svg = (f'<svg width="{self.w}" height="{self.h}" style="position:absolute;left:0;top:0;pointer-events:none">'
               f'<defs>{"".join(s for s in self.svg if s.startswith("<marker"))}</defs>{"".join(self.bg)}'
               f'{"".join(s for s in self.svg if not s.startswith("<marker"))}</svg>')
        return (f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body style="background:{bg}">'
                f'<div id="c" style="width:{self.w}px;height:{self.h}px;background:{bg}">{svg}{"".join(self.parts)}</div></body></html>')

    def render(self, out_png, work):
        os.makedirs(work, exist_ok=True)
        hp = os.path.join(work, os.path.basename(out_png).replace(".png", ".html"))
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(self.html())
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                        f"--window-size={self.w},{self.h}", f"--screenshot={out_png}", "file:///" + hp.replace("\\", "/")],
                       check=True, capture_output=True)
        return out_png


def seq(title, sub, parts, steps, foot="LLD · Sequence Diagram", W=1530):
    """parts: [(name, sub, colour)]; steps: (kind, ...) with kinds call/ret/self/div/note."""
    n = len(parts)
    left, right = 40, 40
    col = (W - left - right) / n
    xs = [left + col * i + col / 2 for i in range(n)]
    y = 175
    rows = []
    for st in steps:
        k = st[0]
        if k == "div":
            y += 14
            rows.append((k, y, st)); y += 34
        elif k == "self":
            rows.append((k, y, st)); y += 52
        elif k == "note":
            rows.append((k, y, st)); y += 46
        else:
            rows.append((k, y, st)); y += 44
    H = y + 90
    f = Fig(W, H, title, sub)
    span = {}
    for k, yy, st in rows:
        idx = [st[1]] if k in ("self",) else ([st[1], st[2]] if k in ("call", "ret") else [])
        for i in idx:
            a, b = span.get(i, (yy, yy))
            span[i] = (min(a, yy - 14), max(b, yy + 22))
    for i, (name, s, c) in enumerate(parts):
        f.line(xs[i], 141, xs[i], H - 70, "#94A3B8", "5 5", 1.4)
        if i in span and i != 0:
            a, b = span[i]
            f.rect(xs[i] - 6, a, 12, b - a, "#E2E8F0", 3)
        f.raw(f'<div class="b" style="left:{xs[i]-85}px;top:92px;width:170px;height:48px;background:{c};border-radius:7px;color:#fff">'
              f'<div class="t" style="font-size:14px;color:#fff">{name}</div><div style="font-size:11.5px;color:#E5E7EB">{s}</div></div>')
    for k, yy, st in rows:
        if k in ("call", "ret"):
            a, b, lab = st[1], st[2], st[3]
            x1, x2 = xs[a], xs[b]
            off = 8 if x2 > x1 else -8
            if k == "call":
                f.arrow([(x1 + off, yy + 14), (x2 - off, yy + 14)], "#2563EB", False, 1.8)
                f.raw(f'<div class="txt" style="left:{min(x1,x2)}px;width:{abs(x2-x1)}px;top:{yy-8}px;text-align:center;font-size:12.6px;color:#0F172A">{lab}</div>')
            else:
                f.arrow([(x1 - off * 0 , yy + 14), (x2 + off, yy + 14)], "#64748B", True, 1.6)
                f.raw(f'<div class="txt" style="left:{min(x1,x2)}px;width:{abs(x2-x1)}px;top:{yy-8}px;text-align:center;font-size:12.4px;color:#475569;font-style:italic">{lab}</div>')
        elif k == "self":
            a, lab = st[1], st[2]
            x = xs[a] + 8
            f.arrow([(x, yy + 6), (x + 36, yy + 6), (x + 36, yy + 30), (x + 2, yy + 30)], "#7C3AED", False, 1.8)
            f.raw(f'<div class="txt" style="left:{x+44}px;top:{yy+7}px;font-size:12.6px;color:#0F172A;white-space:nowrap">{lab}</div>')
        elif k == "div":
            f.line(14, yy, W - 14, yy, "#CBD5E1", "2 4", 1.4)
            f.tag(W / 2, yy, f"<b>{st[1]}</b>", "#334155", "#CBD5E1", "#F1F5F9")
        elif k == "note":
            a, b, lab = st[1], st[2], st[3]
            x1, x2 = min(xs[a], xs[b]) - 60, max(xs[a], xs[b]) + 60
            f.raw(f'<div class="b" style="left:{x1}px;top:{yy}px;width:{x2-x1}px;height:34px;background:#FEF9C3;border:1px solid #EAB308;border-radius:6px;font-size:12.5px;color:#713F12">{lab}</div>')
    f.raw(f'<div class="txt" style="left:40px;top:{H-44}px;font-size:12.5px;color:#475569"><b style="color:#0F172A">Legend:</b>&nbsp;&nbsp; solid arrow = call / request · dashed arrow = return / response · purple loop = work inside the same component · yellow = note</div>')
    f.raw(f'<div class="foot" style="right:40px;top:{H-42}px">Megh One AI · {foot} · {VER}</div>')
    return f
