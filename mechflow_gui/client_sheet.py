# SPDX-License-Identifier: LGPL-2.1-or-later
"""A client's own border and title block on the drawing.

Client Sheet (Drawing tab, or right-click the sheet) takes the border /
title block a client sent - DXF (AutoCAD), SVG, a picture (PNG / JPG) or a
PDF where FreeCAD can read one - and makes it the drawing's sheet:

- DXF: lines, polylines, arcs, circles, ellipses, splines, text and blocks
  (with their attributes). Block attributes - the title block's fill-in
  boxes in AutoCAD - become boxes you type into; tick any other text to type
  over it too.
- SVG: used as it is (sized in mm); tick the text you want to type over.
- Picture / PDF: the sheet as an image under the drawing; add Text Boxes
  for what you fill in.

Keep it as the size it was drawn, or fit it to a standard sheet. It is kept
in your sheet formats (Make Drawing lists it) unless you say not to.
"""

import base64
import math
import os
import re
from xml.sax.saxutils import escape

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

FC_NS = "https://www.freecad.org/wiki/index.php?title=Svg_Namespace"
SIZES = {
    "A4 Landscape": (297, 210), "A4 Portrait": (210, 297), "A3 Landscape": (420, 297),
    "A3 Portrait": (297, 420), "A2 Landscape": (594, 420), "A1 Landscape": (841, 594),
    "A0 Landscape": (1189, 841), "ANSI A Landscape": (279.4, 215.9),
    "ANSI B Landscape": (431.8, 279.4), "ANSI C Landscape": (558.8, 431.8),
    "ANSI D Landscape": (863.6, 558.8),
}
UNITS = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 8: 0.0254, 9: 0.0254e-3,
         10: 914.4, 13: 1e-3, 14: 100.0}
CAP = 0.72        # a DXF text height is its capitals; SVG sizes the whole font


def _mw():
    return Gui.getMainWindow()


def library_folder():
    d = os.path.join(App.getUserAppDataDir(), "MechFlow Sheet Formats")
    os.makedirs(d, exist_ok=True)
    return d


def library():
    """{name: path} of the sheet formats kept so far."""
    try:
        d = library_folder()
    except Exception:
        return {}
    return {os.path.splitext(f)[0]: os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.lower().endswith(".svg")}


# ------------------------------------------------------------ DXF

def _pairs(path):
    raw = open(path, "rb").read()
    if raw.startswith(b"AutoCAD Binary DXF"):
        raise ValueError("binary DXF - save it from CAD as an ASCII DXF")
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    lines = text.splitlines()
    out = []
    for i in range(0, len(lines) - 1, 2):
        try:
            out.append((int(lines[i].strip()), lines[i + 1].rstrip("\r")))
        except ValueError:
            continue
    return out


def _entities(pairs):
    """[(type, [(code, value)...])] split at code 0."""
    out, cur = [], None
    for c, v in pairs:
        if c == 0:
            cur = (v.strip(), [])
            out.append(cur)
        elif cur is not None:
            cur[1].append((c, v))
    return out


def _g(data, code, default=None, cast=float):
    for c, v in data:
        if c == code:
            try:
                return cast(v)
            except ValueError:
                return default
    return default


def _all(data, code, cast=float):
    out = []
    for c, v in data:
        if c == code:
            try:
                out.append(cast(v))
            except ValueError:
                pass
    return out


def _clean_text(s, mtext=False):
    s = s.replace("%%c", "\u2300").replace("%%C", "\u2300").replace("%%d", "\u00b0") \
        .replace("%%D", "\u00b0").replace("%%p", "\u00b1").replace("%%P", "\u00b1")
    s = re.sub(r"%%[uUoOkK]", "", s)
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    if mtext:
        s = s.replace("\\P", "\n").replace("\\~", " ")
        s = re.sub(r"\\S([^;^/#]*)[\^/#]([^;]*);", r"\1/\2", s)
        s = re.sub(r"\\[fFHhCcTtQqWwAap][^;]*;", "", s)
        s = re.sub(r"\\[LlOoKkNn]", "", s)
        s = s.replace("{", "").replace("}", "").replace("\\\\", "\\")
    return s


def _mat(tx=0.0, ty=0.0, rot=0.0, sx=1.0, sy=1.0):
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    return (c * sx, s * sx, -s * sy, c * sy, tx, ty)


def _mm(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D,
            a * E + c * F + e, b * E + d * F + f)


def _ap(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _arc_pts(cx, cy, r, a1, a2, step=4.0):
    while a2 <= a1:
        a2 += 360.0
    n = max(2, int(math.ceil((a2 - a1) / step)) + 1)
    return [(cx + r * math.cos(math.radians(a1 + (a2 - a1) * k / (n - 1))),
             cy + r * math.sin(math.radians(a1 + (a2 - a1) * k / (n - 1)))) for k in range(n)]


def _bulge_pts(p, q, b):
    if abs(b) < 1e-9:
        return [p, q]
    (x1, y1), (x2, y2) = p, q
    ang = 4 * math.atan(b)
    d = math.hypot(x2 - x1, y2 - y1)
    if d < 1e-12:
        return [p, q]
    r = d / (2 * math.sin(abs(ang) / 2))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    h = math.sqrt(max(0.0, r * r - (d / 2) ** 2))
    ux, uy = (x2 - x1) / d, (y2 - y1) / d
    sgn = 1 if (b > 0) == (abs(ang) < math.pi) else -1
    cx, cy = mx - uy * h * sgn, my + ux * h * sgn
    a1 = math.degrees(math.atan2(y1 - cy, x1 - cx))
    a2 = math.degrees(math.atan2(y2 - cy, x2 - cx))
    pts = _arc_pts(cx, cy, r, a1, a2) if b > 0 else list(reversed(_arc_pts(cx, cy, r, a2, a1)))
    pts[0], pts[-1] = p, q
    return pts


def read_dxf(path):
    """{'lines': [[(x, y)...]], 'texts': [...], 'units': mm per unit}."""
    pairs = _pairs(path)
    units = 1.0
    blocks, ents = {}, []
    section, cur = None, None
    ent = _entities(pairs)
    # header: units
    for k, (t, data) in enumerate(ent):
        if t == "SECTION":
            section = _g(data, 2, "", str).strip()
            continue
        if t == "ENDSEC":
            section = None
            continue
        if section == "HEADER":
            continue
        if section == "BLOCKS":
            if t == "BLOCK":
                cur = {"name": _g(data, 2, "", str).strip(),
                       "base": (_g(data, 10, 0.0), _g(data, 20, 0.0)), "ents": []}
                blocks[cur["name"]] = cur
            elif t == "ENDBLK":
                cur = None
            elif cur is not None:
                cur["ents"].append((t, data))
            continue
        if section == "ENTITIES":
            ents.append((t, data))
    for k in range(len(pairs) - 2):
        if pairs[k] == (9, "$INSUNITS") and pairs[k + 1][0] == 70:
            try:
                units = UNITS.get(int(pairs[k + 1][1]), 1.0)
            except ValueError:
                pass
            break
    # model space first; paper space only if there's nothing else
    model = [e for e in ents if _g(e[1], 67, 0, int) != 1]
    paper = [e for e in ents if _g(e[1], 67, 0, int) == 1]
    use = model if any(t not in ("VIEWPORT",) for t, _d in model) else paper
    out = {"lines": [], "circles": [], "texts": [], "units": units}
    _emit(use, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), blocks, out, 0, top=True)
    return out


def _emit(ents, m, blocks, out, depth, top=False):
    k = 0
    while k < len(ents):
        t, d = ents[k]
        k += 1
        lw = _g(d, 370, None, int)
        if t == "LINE":
            out["lines"].append(([_ap(m, _g(d, 10, 0.0), _g(d, 20, 0.0)),
                                  _ap(m, _g(d, 11, 0.0), _g(d, 21, 0.0))], lw))
        elif t == "LWPOLYLINE":
            pts, bul = [], []
            for c, v in d:
                if c == 10:
                    pts.append([float(v), 0.0])
                    bul.append(0.0)
                elif c == 20 and pts:
                    pts[-1][1] = float(v)
                elif c == 42 and bul:
                    bul[-1] = float(v)
            closed = bool(_g(d, 70, 0, int) & 1)
            out["lines"].append((_poly(pts, bul, closed, m), lw))
        elif t == "POLYLINE":
            pts, bul = [], []
            closed = bool(_g(d, 70, 0, int) & 1)
            while k < len(ents) and ents[k][0] == "VERTEX":
                vd = ents[k][1]
                pts.append([_g(vd, 10, 0.0), _g(vd, 20, 0.0)])
                bul.append(_g(vd, 42, 0.0))
                k += 1
            if k < len(ents) and ents[k][0] == "SEQEND":
                k += 1
            if len(pts) > 1:
                out["lines"].append((_poly(pts, bul, closed, m), lw))
        elif t in ("CIRCLE", "ARC"):
            cx, cy, r = _g(d, 10, 0.0), _g(d, 20, 0.0), _g(d, 40, 0.0)
            a1, a2 = (0.0, 360.0) if t == "CIRCLE" else (_g(d, 50, 0.0), _g(d, 51, 360.0))
            out["lines"].append(([_ap(m, x, y) for x, y in _arc_pts(cx, cy, r, a1, a2)], lw))
        elif t == "ELLIPSE":
            cx, cy = _g(d, 10, 0.0), _g(d, 20, 0.0)
            mx, my = _g(d, 11, 1.0), _g(d, 21, 0.0)
            ratio = _g(d, 40, 1.0)
            p1, p2 = _g(d, 41, 0.0), _g(d, 42, 2 * math.pi)
            while p2 <= p1:
                p2 += 2 * math.pi
            n = max(8, int((p2 - p1) / math.radians(4)))
            pts = []
            for j in range(n + 1):
                a = p1 + (p2 - p1) * j / n
                x = cx + mx * math.cos(a) - my * ratio * math.sin(a)
                y = cy + my * math.cos(a) + mx * ratio * math.sin(a)
                pts.append(_ap(m, x, y))
            out["lines"].append((pts, lw))
        elif t == "SPLINE":
            xs, ys = _all(d, 11), _all(d, 21)
            if len(xs) < 2:
                xs, ys = _all(d, 10), _all(d, 20)
            if len(xs) > 1:
                out["lines"].append(([_ap(m, x, y) for x, y in zip(xs, ys)], lw))
        elif t == "SOLID":
            xs = [_g(d, c, None) for c in (10, 11, 13, 12)]
            ys = [_g(d, c, None) for c in (20, 21, 23, 22)]
            pts = [_ap(m, x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
            if len(pts) >= 3:
                out["lines"].append((pts + [pts[0]], lw))
        elif t in ("TEXT", "ATTRIB") or (t == "ATTDEF" and top):
            _text(d, m, out, attrib=t in ("ATTRIB", "ATTDEF"), definition=t == "ATTDEF")
        elif t == "MTEXT":
            _mtext(d, m, out)
        elif t == "INSERT" and depth < 12:
            name = _g(d, 2, "", str).strip()
            b = blocks.get(name)
            sx, sy = _g(d, 41, 1.0), _g(d, 42, 1.0)
            rot = _g(d, 50, 0.0)
            ins = _mat(_g(d, 10, 0.0), _g(d, 20, 0.0), rot, sx, sy)
            if b is not None and not name.startswith("*D"):
                bm = _mm(_mm(m, ins), _mat(-b["base"][0], -b["base"][1]))
                _emit(b["ents"], bm, blocks, out, depth + 1)
            # attributes follow the insert (in world coordinates)
            while k < len(ents) and ents[k][0] == "ATTRIB":
                _text(ents[k][1], m, out, attrib=True)
                k += 1
            if k < len(ents) and ents[k][0] == "SEQEND":
                k += 1


def _poly(pts, bul, closed, m):
    out = []
    n = len(pts)
    segs = n if closed else n - 1
    for j in range(segs):
        p, q = tuple(pts[j]), tuple(pts[(j + 1) % n])
        seg = _bulge_pts(p, q, bul[j] if j < len(bul) else 0.0)
        out += seg if not out else seg[1:]
    if n == 1:
        out = [tuple(pts[0])]
    return [_ap(m, x, y) for x, y in out]


def _text(d, m, out, attrib=False, definition=False):
    h = _g(d, 40, 2.5)
    s = _g(d, 1, "", str)
    tag = _g(d, 2, "", str).strip() if attrib else ""
    if definition and not s:
        s = ""
    flags = _g(d, 70, 0, int) if attrib else 0
    if attrib and flags & 1:                  # invisible attribute
        return
    hal, val = _g(d, 72, 0, int), _g(d, 74 if attrib else 73, 0, int)
    if hal or val:
        x, y = _g(d, 11, _g(d, 10, 0.0)), _g(d, 21, _g(d, 20, 0.0))
    else:
        x, y = _g(d, 10, 0.0), _g(d, 20, 0.0)
    anchor = {1: "middle", 2: "end", 4: "middle"}.get(hal, "start")
    if hal == 4:
        val = 2
    rot = _g(d, 50, 0.0)
    out["texts"].append(_placed(m, x, y, h, rot, _clean_text(s), anchor,
                                {0: "base", 1: "base", 2: "middle", 3: "top"}.get(val, "base"),
                                tag=tag, editable=attrib))


def _mtext(d, m, out):
    h = _g(d, 40, 2.5)
    s = "".join(v for c, v in d if c == 3) + (_g(d, 1, "", str) or "")
    att = _g(d, 71, 1, int)
    anchor = {1: "start", 2: "middle", 3: "end"}[(att - 1) % 3 + 1]
    val = {0: "top", 1: "middle", 2: "bottom"}[(att - 1) // 3]
    rot = _g(d, 50, 0.0)
    dx, dy = _g(d, 11, None), _g(d, 21, None)
    if dx is not None and dy is not None and rot == 0.0:
        rot = math.degrees(math.atan2(dy, dx))
    out["texts"].append(_placed(m, _g(d, 10, 0.0), _g(d, 20, 0.0), h, rot,
                                _clean_text(s, True), anchor, val))


def _placed(m, x, y, h, rot, text, anchor, valign, tag="", editable=False):
    X, Y = _ap(m, x, y)
    k = math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0
    # direction of the text after the block's own rotation
    ux, uy = _ap((m[0], m[1], m[2], m[3], 0, 0), math.cos(math.radians(rot)),
                 math.sin(math.radians(rot)))
    return {"x": X, "y": Y, "h": h * k, "rot": math.degrees(math.atan2(uy, ux)),
            "text": text, "anchor": anchor, "valign": valign, "tag": tag,
            "editable": editable}


def _bounds(items):
    xs, ys = [], []
    for pts, _lw in items["lines"]:
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    for t in items["texts"]:
        xs.append(t["x"])
        ys.append(t["y"])
    if not xs:
        raise ValueError("nothing drawn in the DXF")
    return min(xs), min(ys), max(xs), max(ys)


def snap_size(w, h, tol=0.03):
    """A standard sheet if (w, h) is within tol of one."""
    for name, (W, H) in SIZES.items():
        if abs(w - W) <= tol * W and abs(h - H) <= tol * H:
            return name
    return None


def _field_name(s, used):
    base = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()[:30] or "field"
    if base[0].isdigit():
        base = "f_" + base
    n, name = 1, base
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


def dxf_svg(items, size=None, font="osifont", editable=None, margin_fit=True):
    """SVG sheet (mm) from read_dxf items. size: (W, H) mm to fit it to, or
    None for as drawn. editable: indexes of texts to type in (attributes by
    default)."""
    u = items["units"]
    x0, y0, x1, y1 = _bounds(items)
    w, h = (x1 - x0) * u, (y1 - y0) * u
    if size is None:
        name = snap_size(w, h)
        W, H = SIZES[name] if name else (math.ceil(w), math.ceil(h))
        k = u
        ox = (W - w) / 2 - x0 * u
        oy = (H - h) / 2 - y0 * u
    else:
        W, H = size
        k = u * min(W / w, H / h) if margin_fit else u
        ox = (W - (x1 - x0) * k) / 2 - x0 * k
        oy = (H - (y1 - y0) * k) / 2 - y0 * k

    def P(x, y):
        return x * k + ox, H - (y * k + oy)
    if editable is None:
        editable = {i for i, t in enumerate(items["texts"]) if t["editable"]}
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:freecad="{FC_NS}" version="1.1" '
           f'width="{W:g}mm" height="{H:g}mm" viewBox="0 0 {W:g} {H:g}">',
           '<title>Client sheet</title>',
           '<g id="client_sheet_lines" style="fill:none;stroke:#000000;stroke-linecap:round;'
           'stroke-linejoin:round">']
    for pts, lw in items["lines"]:
        if len(pts) < 2:
            continue
        q = [P(x, y) for x, y in pts]
        d = "M " + " L ".join(f"{a:.3f},{b:.3f}" for a, b in q)
        sw = max(0.13, (lw or 25) / 100.0) if lw and lw > 0 else 0.25
        out.append(f'<path d="{d}" style="stroke-width:{sw:.2f}"/>')
    out.append("</g>")
    out.append(f'<g id="client_sheet_text" style="font-family:{escape(font)};fill:#000000;'
               f'stroke:none">')
    used = set()
    for i, t in enumerate(items["texts"]):
        X, Y = P(t["x"], t["y"])
        size_ = t["h"] * k / CAP
        lines = t["text"].split("\n")
        cap = t["h"] * k
        nl = len(lines)
        lead = size_ * 1.25
        if t["valign"] == "top":
            Y += cap
        elif t["valign"] == "middle":
            Y += cap / 2 - (nl - 1) * lead / 2
        elif t["valign"] == "bottom":
            Y -= (nl - 1) * lead
        rot = -t["rot"]
        tr = f' transform="rotate({rot:.3f} {X:.3f} {Y:.3f})"' if abs(rot) > 0.01 else ""
        st = f'font-size:{size_:.3f}px;text-anchor:{t["anchor"]}'
        if i in editable:
            name = _field_name(t["tag"] or lines[0] or "field", used)
            out.append(f'<text x="{X:.3f}" y="{Y:.3f}" freecad:editable="{name}" '
                       f'style="{st}"{tr}><tspan>{escape(lines[0])}</tspan></text>')
            lines = lines[1:]
            Y += lead
            if not lines:
                continue
        if not any(lines):
            continue
        # a <text> a line: FreeCAD's SVG drawing doesn't place tspans by x / y
        for j, s_ in enumerate(lines):
            if s_.strip():
                out.append(f'<text x="{X:.3f}" y="{Y + j * lead:.3f}" style="{st}"{tr}>'
                           f'<tspan>{escape(s_)}</tspan></text>')
    out.append("</g></svg>")
    return "\n".join(out)


# ------------------------------------------------------------ SVG

def _root_tag(svg):
    m = re.search(r"<svg\b[^>]*>", svg)
    if not m:
        raise ValueError("not an SVG file")
    return m


def svg_texts(svg):
    """[(index, text, is already editable)] for every <text> in the SVG."""
    out = []
    for i, m in enumerate(re.finditer(r"<text\b([^>]*)>(.*?)</text>", svg, re.S)):
        body = re.sub(r"<[^>]+>", "", m.group(2))
        body = re.sub(r"\s+", " ", body).strip()
        out.append((i, _unescape(body), ":editable=" in m.group(1)))
    return out


def _unescape(s):
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"') \
        .replace("&apos;", "'").replace("&amp;", "&")


def svg_with_fields(svg, chosen):
    """Make the <text> elements at indexes chosen typeable (freecad:editable),
    each with a single tspan."""
    used = set(re.findall(r':editable="([^"]*)"', svg))
    idx = [-1]

    def fix(m):
        idx[0] += 1
        attrs, body = m.group(1), m.group(2)
        if idx[0] not in chosen or ":editable=" in attrs:
            return m.group(0)
        plain = _unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", body)).strip())
        name = _field_name(plain or "field", used)
        span = re.search(r"<tspan\b([^>]*)>", body)
        sp_attrs = span.group(1) if span else ""
        return (f'<text{attrs} freecad:editable="{name}"><tspan{sp_attrs}>{escape(plain)}'
                f'</tspan></text>')
    out = re.sub(r"<text\b([^>]*)>(.*?)</text>", fix, svg, flags=re.S)
    if "xmlns:freecad" not in _root_tag(out).group(0):
        m = _root_tag(out)
        out = out[:m.end() - 1].rstrip("/") + f' xmlns:freecad="{FC_NS}">' + out[m.end():]
    return out


def svg_sheet(svg, size=None):
    """The SVG on a sheet sized in mm: as drawn, or fitted into size (W, H)."""
    from mechflow_gui import title_block
    import xml.etree.ElementTree as ET
    m = _root_tag(svg)
    root = ET.fromstring(svg.encode("utf-8"))
    w, h = title_block.page_size(root)
    vm = title_block._view_matrix(root)
    if not w or not h:
        vb = [float(x) for x in re.findall(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?",
                                           root.get("viewBox") or "")]
        if len(vb) == 4:
            w, h = vb[2] * 25.4 / 96, vb[3] * 25.4 / 96   # px
            vm = (25.4 / 96, 0, 0, 25.4 / 96, -vb[0] * 25.4 / 96, -vb[1] * 25.4 / 96)
        else:
            raise ValueError("the SVG has no size")
    if size is None:
        W, H = w, h
        name = snap_size(w, h)
        if name:
            W, H = SIZES[name]
        fit = (1.0, 0, 0, 1.0, (W - w) / 2, (H - h) / 2)
    else:
        W, H = size
        k = min(W / w, H / h)
        fit = (k, 0, 0, k, (W - w * k) / 2, (H - h * k) / 2)
    t = title_block._mul(fit, vm)
    ns = " ".join(re.findall(r'xmlns(?::[\w.-]+)?="[^"]*"', m.group(0)))
    if 'xmlns="' not in ns:
        ns = 'xmlns="http://www.w3.org/2000/svg" ' + ns
    if "xmlns:freecad" not in ns:
        ns += f' xmlns:freecad="{FC_NS}"'
    inner = svg[m.end():svg.rfind("</svg>")]
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<svg {ns} version="1.1" width="{W:g}mm" height="{H:g}mm" '
            f'viewBox="0 0 {W:g} {H:g}"><g id="client_sheet" transform="matrix('
            + " ".join(f"{v:.6g}" for v in t) + f')">{inner}</g></svg>')


# ------------------------------------------------------------ pictures, PDF

def image_svg(path, size):
    W, H = size
    img = QtGui.QImage(path)
    if img.isNull():
        raise ValueError("the picture couldn't be read")
    k = min(W / img.width(), H / img.height())
    w, h = img.width() * k, img.height() * k
    ba = QtCore.QByteArray()
    buf = QtCore.QBuffer(ba)
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    data = base64.b64encode(bytes(ba)).decode("ascii")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'xmlns:freecad="{FC_NS}" version="1.1" width="{W:g}mm" height="{H:g}mm" '
            f'viewBox="0 0 {W:g} {H:g}"><image x="{(W - w) / 2:.3f}" y="{(H - h) / 2:.3f}" '
            f'width="{w:.3f}" height="{h:.3f}" preserveAspectRatio="none" '
            f'xlink:href="data:image/png;base64,{data}"/></svg>')


def pdf_image(path, dpi=200):
    """First page of a PDF as a picture (if this FreeCAD's Qt can read PDF)."""
    try:
        from PySide6 import QtPdf
    except ImportError:
        raise ValueError("this FreeCAD can't read PDF files - save the sheet as DXF, SVG "
                         "or a picture")
    doc = QtPdf.QPdfDocument(None)
    doc.load(path)
    if doc.pageCount() < 1:
        raise ValueError("the PDF couldn't be read")
    pts = doc.pagePointSize(0)
    size = QtCore.QSize(int(pts.width() / 72 * dpi), int(pts.height() / 72 * dpi))
    img = doc.render(0, size)
    out = os.path.join(library_folder(), "_pdf_page.png")
    img.save(out)
    return out, (pts.width() * 25.4 / 72, pts.height() * 25.4 / 72)


# ------------------------------------------------------------ the dialog

def render_preview(svg, w=360):
    try:
        from PySide6 import QtSvg
    except ImportError:
        from PySide2 import QtSvg
    r = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    ds = r.defaultSize()
    if ds.width() <= 0:
        return None
    h = int(w * ds.height() / ds.width())
    img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
    img.fill(QtGui.QColor("white"))
    p = QtGui.QPainter(img)
    r.render(p)
    p.end()
    return QtGui.QPixmap.fromImage(img)


class ClientSheetDialog(QtWidgets.QDialog):
    def __init__(self, path, page=None, parent=None):
        super().__init__(parent or _mw())
        self.path, self.page = path, page
        self.kind = os.path.splitext(path)[1].lower()
        self.setWindowTitle("Client Sheet")
        self.resize(900, 600)
        self.items = None
        self.src_svg = None
        self.img_path, self.img_size = None, None
        if self.kind == ".dxf":
            self.items = read_dxf(path)
        elif self.kind == ".svg":
            self.src_svg = open(path, encoding="utf-8").read()
        elif self.kind == ".pdf":
            self.img_path, self.img_size = pdf_image(path)
        else:
            self.img_path = path
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        form = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(os.path.splitext(os.path.basename(path))[0])
        form.addRow("Name", self.name)
        self.size = QtWidgets.QComboBox()
        self.size.addItem("As drawn")
        self.size.addItems(list(SIZES))
        if self.img_path and not self.img_size:
            self.size.removeItem(0)
            self.size.setCurrentText("A3 Landscape")
        form.addRow("Sheet size", self.size)
        self.font = QtWidgets.QFontComboBox()
        self.font.setEditable(True)
        self.font.setEditText("osifont")
        if self.items is not None:
            form.addRow("Font for its text", self.font)
        left.addLayout(form)
        self.list = QtWidgets.QListWidget()
        texts = self._texts()
        if texts:
            left.addWidget(QtWidgets.QLabel(
                "Tick the text you want to type over on each drawing (the drawing number, "
                "title, date...):"))
            for i, t, on in texts:
                it = QtWidgets.QListWidgetItem(t or "(empty box)")
                it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
                it.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
                it.setData(QtCore.Qt.UserRole, i)
                self.list.addItem(it)
            left.addWidget(self.list, 1)
        else:
            note = QtWidgets.QLabel("A picture can't be typed into: add Text Boxes on the "
                                    "drawing for what you fill in.")
            note.setWordWrap(True)
            left.addWidget(note)
            left.addStretch(1)
        self.keep = QtWidgets.QCheckBox("Keep it in my sheet formats (Make Drawing lists it)")
        self.keep.setChecked(True)
        left.addWidget(self.keep)
        self.use = QtWidgets.QCheckBox("Use it on this drawing now")
        self.use.setChecked(page is not None)
        self.use.setEnabled(page is not None)
        left.addWidget(self.use)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        left.addWidget(bb)
        lay.addLayout(left, 1)
        self.preview = QtWidgets.QLabel()
        self.preview.setMinimumWidth(420)
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setStyleSheet("background:#888")
        lay.addWidget(self.preview, 1)
        self.size.currentTextChanged.connect(self._update)
        self.font.currentTextChanged.connect(self._update)
        self.list.itemChanged.connect(self._update)
        self._update()

    def _texts(self):
        if self.items is not None:
            return [(i, t["text"].replace("\n", " / "), t["editable"])
                    for i, t in enumerate(self.items["texts"])]
        if self.src_svg is not None:
            return svg_texts(self.src_svg)
        return []

    def _chosen(self):
        out = set()
        for r in range(self.list.count()):
            it = self.list.item(r)
            if it.checkState() == QtCore.Qt.Checked:
                out.add(int(it.data(QtCore.Qt.UserRole)))
        return out

    def svg(self):
        s = self.size.currentText()
        size = SIZES.get(s)
        if self.items is not None:
            return dxf_svg(self.items, size, self.font.currentText().strip() or "osifont",
                           self._chosen())
        if self.src_svg is not None:
            return svg_sheet(svg_with_fields(self.src_svg, self._chosen()), size)
        if size is None:
            size = (round(self.img_size[0], 1), round(self.img_size[1], 1))
        return image_svg(self.img_path, size)

    def _update(self, *_a):
        try:
            pm = render_preview(self.svg(), 420)
            if pm is not None:
                self.preview.setPixmap(pm)
        except Exception as e:
            self.preview.setText(f"Can't show it: {e}")


def save_sheet(svg, name):
    safe = re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "Client sheet"
    path = os.path.join(library_folder(), safe + ".svg")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path


def client_sheet_command(page=None):
    from mechflow_gui import drawings
    if page is None:
        page = drawings.active_page()
    path, _f = QtWidgets.QFileDialog.getOpenFileName(
        _mw(), "Client border and title block", "",
        "Sheets (*.dxf *.svg *.png *.jpg *.jpeg *.bmp *.pdf);;DXF (*.dxf);;SVG (*.svg);;"
        "Pictures (*.png *.jpg *.jpeg *.bmp);;PDF (*.pdf)")
    if not path:
        return None
    if path.lower().endswith(".dwg"):
        QtWidgets.QMessageBox.information(_mw(), "Client Sheet",
                                          "Save the DWG as a DXF in CAD (or ask the client "
                                          "for one) and bring that in.")
        return None
    try:
        dlg = ClientSheetDialog(path, page)
    except Exception as e:
        QtWidgets.QMessageBox.warning(_mw(), "Client Sheet", f"It couldn't be read:\n{e}")
        return None
    if not dlg.exec():
        return None
    return apply_choice(dlg.svg(), dlg.name.text(), page if dlg.use.isChecked() else None,
                        dlg.keep.isChecked())


def apply_choice(svg, name, page=None, keep=True):
    from mechflow_gui import drawings
    if keep:
        path = save_sheet(svg, name)
    else:
        from mechflow_gui import title_block
        path = os.path.join(title_block._folder(), "client_" + (name or "sheet") + ".svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg)
    if page is not None:
        doc = page.Document
        doc.openTransaction("Client Sheet")
        try:
            drawings.set_sheet(page, path)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
    return path
