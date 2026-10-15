# SPDX-License-Identifier: LGPL-2.1-or-later
"""The title block: text that fits its box, and an editor for it.

FreeCAD's sheet templates are SVG with "editable" text fields. A long part
name ran straight out of its box into the next one (Created by). MechFlow
keeps the template the drawing was made with and writes the sheet from it
with each field's own settings:

- every field is shrunk to fit its box (the box is found from the lines of
  the template round the field), unless you set a size yourself;
- Title Block (Drawing tab, or right-click the sheet) lists every field: type
  the text, pick the font and size, bold, nudge it right / up, or "Move to
  sheet" - the field becomes a note you can drag anywhere, size and restyle
  (and "Put back in box" returns it).

What was set is kept with the drawing (the template's MechFlowSheet
property), and the sheet is rebuilt whenever the text changes - also when
it's typed straight into the drawing.
"""

import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET

import FreeCAD as App

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

SVG_NS = "http://www.w3.org/2000/svg"
MIN_SIZE = 1.2           # mm - never fit text smaller than this
PAD = 1.0                # mm left clear inside a box


def _mw():
    import FreeCADGui as Gui
    return Gui.getMainWindow()


# ------------------------------------------------------------ svg reading

def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _style(el):
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _num(v, default=0.0):
    if v is None:
        return default
    m = re.match(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)", str(v))
    return float(m.group(1)) if m else default


def _length_mm(v):
    """'420mm' / '297' / '11in' / '1000px' -> mm."""
    s = str(v or "").strip()
    n = _num(s, 0.0)
    for unit, k in (("mm", 1.0), ("cm", 10.0), ("in", 25.4), ("pt", 25.4 / 72),
                    ("pc", 25.4 / 6), ("px", 25.4 / 96)):
        if s.endswith(unit):
            return n * k
    return n                               # unitless: FreeCAD reads it as mm


def _matrix(tr):
    """SVG transform attribute -> (a, b, c, d, e, f)."""
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", tr or ""):
        v = [float(x) for x in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", args)]
        if name == "matrix" and len(v) == 6:
            n = tuple(v)
        elif name == "translate":
            n = (1, 0, 0, 1, v[0] if v else 0, v[1] if len(v) > 1 else 0)
        elif name == "scale":
            sx = v[0] if v else 1
            n = (sx, 0, 0, v[1] if len(v) > 1 else sx, 0, 0)
        elif name == "rotate" and v:
            a = math.radians(v[0])
            r = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
            if len(v) == 3:
                cx, cy = v[1], v[2]
                n = _mul(_mul((1, 0, 0, 1, cx, cy), r), (1, 0, 0, 1, -cx, -cy))
            else:
                n = r
        else:
            continue
        m = _mul(m, n)
    return m


def _mul(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D,
            a * E + c * F + e, b * E + d * F + f)


def _apply(m, x, y):
    return m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]


def _scale_of(m):
    return math.sqrt(abs(m[0] * m[3] - m[1] * m[2])) or 1.0


def _walk(root):
    """(element, absolute matrix, inherited style) for every element."""
    out = []

    def go(el, m, inh):
        st = dict(inh)
        for k in ("font-size", "font-family", "font-weight", "text-anchor", "fill"):
            if el.get(k):
                st[k] = el.get(k)
        st.update({k: v for k, v in _style(el).items()
                   if k in ("font-size", "font-family", "font-weight", "text-anchor", "fill")})
        m2 = _mul(m, _matrix(el.get("transform"))) if el.get("transform") else m
        out.append((el, m2, st))
        for ch in el:
            go(ch, m2, st)
    go(root, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0), {})
    return out


def page_size(root):
    return _length_mm(root.get("width")), _length_mm(root.get("height"))


def _view_matrix(root):
    """User units -> mm (the viewBox mapped onto width x height)."""
    w, h = page_size(root)
    vb = [float(x) for x in re.findall(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?", root.get("viewBox") or "")]
    if len(vb) == 4 and vb[2] and vb[3] and w and h:
        kx, ky = w / vb[2], h / vb[3]
        return (kx, 0.0, 0.0, ky, -vb[0] * kx, -vb[1] * ky)
    return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _path_points(d):
    """Polyline vertices of an SVG path (curves by their end points)."""
    toks = re.findall(r"[MmLlHhVvZzCcSsQqTtAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d or "")
    i, cmd = 0, None
    x = y = sx = sy = 0.0
    polys, cur = [], []
    sizes = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v
    while i < len(toks):
        t = toks[i]
        if re.match(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append((sx, sy))
                    polys.append(cur)
                    cur = []
                x, y = sx, sy
                continue
        if cmd is None:
            i += 1
            continue
        up, rel = cmd.upper(), cmd.islower()
        n = sizes.get(up, 2)
        if i + n > len(toks) or any(re.match(r"[A-Za-z]", q) for q in toks[i:i + n]):
            i += 1
            continue
        vals = [num() for _ in range(n)]
        if up == "M":
            if cur:
                polys.append(cur)
            x, y = (x + vals[0], y + vals[1]) if rel else (vals[0], vals[1])
            sx, sy = x, y
            cur = [(x, y)]
            cmd = "l" if rel else "L"
            continue
        if up == "H":
            x = x + vals[0] if rel else vals[0]
        elif up == "V":
            y = y + vals[0] if rel else vals[0]
        else:
            ex, ey = vals[-2], vals[-1]
            x, y = (x + ex, y + ey) if rel else (ex, ey)
        cur.append((x, y))
    if cur:
        polys.append(cur)
    return polys


def segments(root):
    """Every straight piece of line in the sheet, in mm (SVG y down)."""
    vm = _view_matrix(root)
    segs = []
    for el, m, _st in _walk(root):
        tag = _local(el.tag)
        polys = []
        if tag == "line":
            polys = [[(_num(el.get("x1")), _num(el.get("y1"))), (_num(el.get("x2")), _num(el.get("y2")))]]
        elif tag == "rect":
            x, y = _num(el.get("x")), _num(el.get("y"))
            w, h = _num(el.get("width")), _num(el.get("height"))
            polys = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]]
        elif tag in ("polyline", "polygon"):
            v = [float(q) for q in re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",
                                              el.get("points") or "")]
            pts = list(zip(v[0::2], v[1::2]))
            if tag == "polygon" and pts:
                pts.append(pts[0])
            polys = [pts]
        elif tag == "path":
            polys = _path_points(el.get("d"))
        if not polys:
            continue
        mm = _mul(vm, m)
        for p in polys:
            q = [_apply(mm, a, b) for a, b in p]
            segs += [(q[k], q[k + 1]) for k in range(len(q) - 1)]
    return segs


def fields(svg_text):
    """The editable fields: name, position (mm, y down), size (mm), font..."""
    root = ET.fromstring(svg_text.encode("utf-8") if isinstance(svg_text, str) else svg_text)
    vm = _view_matrix(root)
    out = []
    for el, m, st in _walk(root):
        if _local(el.tag) != "text":
            continue
        name = None
        for k, v in el.attrib.items():
            if k.endswith("}editable") or k == "freecad:editable":
                name = v
        if not name:
            continue
        mm = _mul(vm, m)
        x, y = _num(el.get("x")), _num(el.get("y"))
        sp = next((c for c in el if _local(c.tag) == "tspan"), None)
        if sp is not None and sp.get("x") is not None:
            x, y = _num(sp.get("x")), _num(sp.get("y"), y)
        ax, ay = _apply(mm, x, y)
        k = _scale_of(mm)
        text = "".join(el.itertext()).strip()
        out.append({"name": name, "x": ax, "y": ay, "k": k,
                    "size": _num(st.get("font-size"), 5.0) * k,
                    "family": (st.get("font-family") or "osifont").strip("'\""),
                    "bold": (st.get("font-weight") or "").lower() in ("bold", "700", "800", "900"),
                    "anchor": st.get("text-anchor") or "start", "default": text})
    return out


def box_width(f, segs, others=()):
    """Room for field f across its box: up to the template's lines either
    side of it at its height, or the next field along the same line (some
    title blocks have no line between them). None if there's no box."""
    x, y, size = f["x"], f["y"], f["size"]
    yc = y - 0.35 * size                  # middle of the capitals
    left, right = None, None
    for (x1, y1), (x2, y2) in segs:
        if abs(x1 - x2) > 0.05:
            continue
        lo, hi = min(y1, y2), max(y1, y2)
        if not (lo - 0.2 <= yc <= hi + 0.2) or hi - lo < 0.5 * size:
            continue
        xl = (x1 + x2) / 2
        if xl > x + 0.3 and (right is None or xl < right):
            right = xl
        if xl < x - 0.3 and (left is None or xl > left):
            left = xl
    for o in others:
        if o is f or o["name"] == f["name"] or abs(o["y"] - y) > 0.5 * size:
            continue
        w = o.get("w", 0.0)
        lo = {"start": o["x"], "middle": o["x"] - w / 2}.get(o["anchor"], o["x"] - w) - PAD
        hi = lo + w + 2 * PAD
        if lo > x + 0.3 and (right is None or lo < right):
            right = lo
        if o["x"] < x - 0.3 and (left is None or hi > left):
            left = hi
    a = f["anchor"]
    if a == "middle":
        if left is None or right is None:
            return None
        return 2 * min(x - left, right - x) - 2 * PAD
    if a == "end":
        return None if left is None else x - left - PAD
    return None if right is None else right - x - PAD


_fm_cache = {}


def text_width(text, family, size, bold=False):
    """Width in mm of text at size (mm) in the given font."""
    if not text:
        return 0.0
    app = QtWidgets.QApplication.instance()
    if app is None:
        return 0.55 * size * len(text)
    key = (family, bool(bold))
    fm = _fm_cache.get(key)
    if fm is None:
        font = QtGui.QFont(family)
        font.setPixelSize(100)
        font.setBold(bool(bold))
        fm = QtGui.QFontMetricsF(font)
        _fm_cache[key] = fm
    return fm.horizontalAdvance(text) * size / 100.0


def metrics(family, bold=False):
    """(capitals, ascent, descent) of the font per unit of font size."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        return 0.72, 0.9, 0.25
    font = QtGui.QFont(family)
    font.setPixelSize(100)
    font.setBold(bool(bold))
    fm = QtGui.QFontMetricsF(font)
    return (fm.capHeight() / 100.0 or 0.72), fm.ascent() / 100.0, fm.descent() / 100.0


# ------------------------------------------------------------ svg writing

def _set_style(tag, updates):
    """Merge updates (None removes) into the style attribute of a start tag."""
    m = re.search(r'\sstyle="([^"]*)"', tag)
    st = {}
    if m:
        for part in m.group(1).split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                st[k.strip()] = v.strip()
    for k, v in updates.items():
        if v is None:
            st.pop(k, None)
        else:
            st[k] = v
    new = ";".join(f"{k}:{v}" for k, v in st.items())
    if m:
        return tag[:m.start()] + f' style="{new}"' + tag[m.end():]
    return re.sub(r"\s*(/?>)$", f' style="{new}"\\1', tag)


def _shift_attr(tag, attr, d):
    m = re.search(r'\s' + attr + r'="([^"]*)"', tag)
    if not m or not d:
        return tag
    v = _num(m.group(1)) + d
    return tag[:m.start()] + f' {attr}="{v:.3f}"' + tag[m.end():]


def restyle(svg_text, settings):
    """svg_text with each editable field's start tag set as settings[name]
    says: size (mm), family, bold, dx / dy (mm, right / up)."""
    info = {f["name"]: f for f in fields(svg_text)}

    def fix(m):
        tag = m.group(0)
        nm = re.search(r'\s[\w.-]+:editable="([^"]*)"', tag)
        if not nm:
            return tag
        name = nm.group(1)
        s = settings.get(name)
        f = info.get(name)
        if not s or f is None:
            return tag
        k = f["k"] or 1.0
        up = {}
        if s.get("size"):
            up["font-size"] = f"{s['size'] / k:.3f}px"
        if s.get("family"):
            up["font-family"] = s["family"]
        if s.get("bold") is not None:
            up["font-weight"] = "bold" if s["bold"] else "normal"
        if up:
            tag = _set_style(tag, up)
        tag = _shift_attr(tag, "x", s.get("dx", 0.0) / k)
        tag = _shift_attr(tag, "y", -s.get("dy", 0.0) / k)
        return tag
    out = re.sub(r"<text\b[^>]*>", fix, svg_text)
    # a field's tspan may carry its own x / y (Inkscape writes them): move those too
    def fix_span(m):
        text_tag, span_tag = m.group(1), m.group(2)
        nm = re.search(r'\s[\w.-]+:editable="([^"]*)"', text_tag)
        if not nm:
            return m.group(0)
        s, f = settings.get(nm.group(1)), info.get(nm.group(1))
        if not s or f is None:
            return m.group(0)
        k = f["k"] or 1.0
        span_tag = _shift_attr(span_tag, "x", s.get("dx", 0.0) / k)
        span_tag = _shift_attr(span_tag, "y", -s.get("dy", 0.0) / k)
        span_tag = re.sub(r'\sstyle="[^"]*font-size[^"]*"', lambda q: re.sub(
            r"font-size:[^;\"]*;?", "", q.group(0)), span_tag) if s.get("size") else span_tag
        return text_tag + span_tag
    return re.sub(r"(<text\b[^>]*>)\s*(<tspan\b[^>]*>)", fix_span, out)


# ------------------------------------------------------------ on the template

PROP = "MechFlowSheet"
SRC = "MechFlowSheetSource"
_busy = set()


def settings_of(template):
    try:
        d = json.loads(getattr(template, PROP, "") or "{}")
    except Exception:
        d = {}
    d.setdefault("fit", True)
    d.setdefault("fields", {})
    return d


def _save_settings(template, d):
    if PROP not in template.PropertiesList:
        template.addProperty("App::PropertyString", PROP, "MechFlow",
                             "MechFlow title block settings (fonts, sizes, fit)", 4)
    setattr(template, PROP, json.dumps(d))


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def source_svg(template):
    """The template as it came (before MechFlow's settings)."""
    p = getattr(template, SRC, "") if SRC in template.PropertiesList else ""
    if p and os.path.exists(p):
        return _read(p)
    for p in (getattr(template, "PageResult", ""), template.Template):
        if p and os.path.exists(p):
            return _read(p)
    return ""


def set_source(template, path):
    """Remember path as the template's original (embedded in the document)."""
    if SRC not in template.PropertiesList:
        template.addProperty("App::PropertyFileIncluded", SRC, "MechFlow",
                             "The sheet template as it came, before MechFlow's settings", 4)
    tmp = os.path.join(_folder(), "src_" + os.path.basename(path))
    if os.path.abspath(tmp) != os.path.abspath(path):
        with open(path, "rb") as a, open(tmp, "wb") as b:
            b.write(a.read())
    setattr(template, SRC, tmp)


def _folder():
    d = os.path.join(tempfile.gettempdir(), "MechFlow sheets")
    os.makedirs(d, exist_ok=True)
    return d


def plan(template, svg=None, texts=None):
    """{field: {size, family, bold, dx, dy}} - each field's own settings,
    and fitted sizes where the text is too long for its box."""
    svg = svg if svg is not None else source_svg(template)
    if not svg:
        return {}, []
    d = settings_of(template)
    texts = texts if texts is not None else dict(template.EditableTexts)
    root = ET.fromstring(svg.encode("utf-8"))
    segs = segments(root)
    out = {}
    fl = fields(svg)
    for f in fl:
        s = d["fields"].get(f["name"], {})
        f["w"] = text_width(texts.get(f["name"], ""), s.get("family") or f["family"],
                            s.get("size") or f["size"],
                            s.get("bold") if s.get("bold") is not None else f["bold"])
    for f in fl:
        s = dict(d["fields"].get(f["name"], {}))
        size = s.get("size") or f["size"]
        fam = s.get("family") or f["family"]
        bold = s.get("bold") if s.get("bold") is not None else f["bold"]
        if d["fit"] and s.get("fit", True) and not s.get("detached") and not s.get("size"):
            room = box_width(dict(f, x=f["x"] + s.get("dx", 0.0)), segs, fl)
            w = text_width(texts.get(f["name"], ""), fam, size, bold)
            if room and room > 0 and w > room:
                size = max(MIN_SIZE, size * room / w)
                s["fitted"] = True
        if abs(size - f["size"]) > 1e-3:
            s["size"] = round(size, 3)
        else:
            s.pop("size", None)
        out[f["name"]] = s
    return out, fl


def apply(template, texts=None):
    """Write the sheet from its original with the fields' settings."""
    key = (template.Document.Name, template.Name)
    if key in _busy:
        return False
    svg = source_svg(template)
    if not svg:
        return False
    if SRC not in template.PropertiesList:
        src = template.PageResult if os.path.exists(getattr(template, "PageResult", "")) \
            else template.Template
        if src and os.path.exists(src):
            set_source(template, src)
    if texts is None:
        texts = dict(template.EditableTexts)
    p, _fl = plan(template, svg, texts)
    new = restyle(svg, p)
    d = settings_of(template)
    import hashlib
    h = hashlib.md5((new + json.dumps(texts, sort_keys=True)).encode("utf-8")).hexdigest()
    if d.get("hash") == h and dict(template.EditableTexts) == texts:
        return False
    _busy.add(key)
    try:
        name = re.sub(r"[^A-Za-z0-9_]", "_", f"{template.Document.Name}_{template.Name}")
        path = os.path.join(_folder(), f"{name}_{h[:8]}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(new)
        if os.path.abspath(template.Template) != os.path.abspath(path):
            template.Template = path
        template.EditableTexts = texts
        d["hash"] = h
        _save_settings(template, d)
        template.touch()
    finally:
        _busy.discard(key)
    return True


def change_source(template, path):
    """A new sheet (Sheet Format): keep what was typed and the field settings."""
    texts = dict(template.EditableTexts)
    set_source(template, path)
    template.Template = path
    new = dict(template.EditableTexts)
    for k, v in texts.items():
        if k in new and v:
            new[k] = v
    d = settings_of(template)
    d.pop("hash", None)
    _save_settings(template, d)
    apply(template, new)


# ------------------------------------------------------------ keep fitted

class _Observer:
    def slotChangedObject(self, obj, prop):
        if prop != "EditableTexts" or PROP not in getattr(obj, "PropertiesList", ()):
            return
        if (obj.Document.Name, obj.Name) in _busy:
            return
        doc, name = obj.Document.Name, obj.Name

        def later():
            try:
                t = App.getDocument(doc).getObject(name)
                if t is not None:
                    apply(t)
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: title block not refitted ({e})\n")
        QtCore.QTimer.singleShot(0, later)


_obs = None


def install():
    global _obs
    if _obs is None:
        _obs = _Observer()
        App.addDocumentObserver(_obs)


# ------------------------------------------------------------ fields <-> notes

def _page_of(template):
    for o in template.InList:
        if o.TypeId == "TechDraw::DrawPage":
            return o
    return None


def detach(template, name):
    """Field name off the title block onto the sheet as a note you can move."""
    page = _page_of(template)
    if page is None:
        return None
    p, fl = plan(template)
    f = next((q for q in fl if q["name"] == name), None)
    if f is None:
        return None
    s = p.get(name, {})
    text = dict(template.EditableTexts).get(name, "")
    size = s.get("size") or f["size"]
    fam = s.get("family") or f["family"]
    bold = s.get("bold") if s.get("bold") is not None else f["bold"]
    W, H = float(template.Width), float(template.Height)
    w = text_width(text, fam, size, bold)
    cap, asc, desc = metrics(fam, bold)
    x = f["x"] + s.get("dx", 0.0)
    if f["anchor"] == "start":
        x += w / 2
    elif f["anchor"] == "end":
        x -= w / 2
    doc = template.Document
    note = doc.addObject("TechDraw::DrawViewAnnotation", "TitleText")
    note.Label = f"Title block: {pretty(name)}"
    page.addView(note)
    note.Text = text.split("\n") if text else [""]
    note.Font = fam
    note.TextSize = size * cap          # a note's size is its capitals' height
    note.TextStyle = "Bold" if bold else "Normal"
    note.X = x
    # a note sits centred on its line of text: baseline + half (ascent - descent)
    note.Y = H - (f["y"] - s.get("dy", 0.0)) + size * (asc - desc) / 2
    note.addProperty("App::PropertyString", "MechFlowTitleField", "MechFlow",
                     "The title block field this text came from")
    note.MechFlowTitleField = name
    d = settings_of(template)
    d["fields"].setdefault(name, {})["detached"] = note.Name
    _save_settings(template, d)
    texts = dict(template.EditableTexts)
    texts[name] = ""
    apply(template, texts)
    doc.recompute()
    return note


def put_back(template, name):
    d = settings_of(template)
    fs = d["fields"].get(name, {})
    nn = fs.pop("detached", None)
    doc = template.Document
    note = doc.getObject(nn) if nn else None
    texts = dict(template.EditableTexts)
    if note is not None:
        texts[name] = "\n".join(note.Text)
        page = _page_of(template)
        try:
            if page is not None:
                page.removeView(note)
        except Exception:
            pass
        doc.removeObject(note.Name)
    _save_settings(template, d)
    apply(template, texts)
    doc.recompute()


def pretty(name):
    s = re.sub(r"[_\-]+", " ", name)
    s = re.sub(r"(?<=[a-z])(?=[A-Z0-9])", " ", s)
    return s.strip().capitalize()


# ------------------------------------------------------------ the editor

class TitleBlockDialog(QtWidgets.QDialog):
    """Every title block field: its text, font, size, bold, nudge, fit."""

    COLS = ["Field", "Text", "Font", "Size (mm)", "Bold", "Move → (mm)", "Move ↑ (mm)",
            "Fit to box"]

    def __init__(self, page, parent=None):
        super().__init__(parent or _mw())
        self.page = page
        self.t = page.Template
        self.setWindowTitle("Title Block")
        self.resize(980, 560)
        lay = QtWidgets.QVBoxLayout(self)
        tip = QtWidgets.QLabel(
            "Type in the title block, pick a font and size for any box, or move a box's text a "
            "little. <b>Move to sheet</b> makes a box's text a note you can drag anywhere on the "
            "drawing. Text that's too long for its box is made smaller to fit unless you give "
            "it a size.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        top = QtWidgets.QHBoxLayout()
        self.fit_all = QtWidgets.QCheckBox("Fit text to the boxes")
        self.fit_all.setChecked(settings_of(self.t)["fit"])
        top.addWidget(self.fit_all)
        top.addStretch(1)
        top.addWidget(QtWidgets.QLabel("Font for every box:"))
        self.all_font = QtWidgets.QFontComboBox()
        self.all_font.setCurrentIndex(-1)
        self.all_font.setEditable(True)
        self.all_font.lineEdit().setPlaceholderText("(as the template)")
        top.addWidget(self.all_font)
        b = QtWidgets.QPushButton("Set")
        b.clicked.connect(self._font_all)
        top.addWidget(b)
        lay.addLayout(top)
        self.table = QtWidgets.QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().hide()
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        row = QtWidgets.QHBoxLayout()
        self.detach_btn = QtWidgets.QPushButton("Move to sheet")
        self.detach_btn.setToolTip("The selected box's text becomes a note on the drawing: "
                                   "drag it anywhere, double-click or right-click to restyle it")
        self.detach_btn.clicked.connect(self._detach)
        self.back_btn = QtWidgets.QPushButton("Put back in box")
        self.back_btn.clicked.connect(self._put_back)
        self.reset_btn = QtWidgets.QPushButton("Reset box")
        self.reset_btn.setToolTip("The selected box back to the template's font, size and place")
        self.reset_btn.clicked.connect(self._reset)
        for w in (self.detach_btn, self.back_btn, self.reset_btn):
            row.addWidget(w)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Apply |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self.apply)
        lay.addWidget(bb)
        self._fill()

    # rows ----------------------------------------------------------
    def _fill(self):
        svg = source_svg(self.t)
        self.fl = fields(svg) if svg else []
        d = settings_of(self.t)
        texts = dict(self.t.EditableTexts)
        self.table.setRowCount(0)
        self.rows = []
        seen = set()
        for f in sorted(self.fl, key=lambda q: (round(q["y"] / 3), q["x"])):
            if f["name"] in seen:
                continue
            seen.add(f["name"])
            s = d["fields"].get(f["name"], {})
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QtWidgets.QTableWidgetItem(pretty(f["name"]))
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            it.setToolTip(f["name"])
            self.table.setItem(r, 0, it)
            text = QtWidgets.QLineEdit(texts.get(f["name"], ""))
            font = QtWidgets.QFontComboBox()
            font.setEditable(True)
            font.setCurrentFont(QtGui.QFont(s.get("family") or f["family"]))
            font.setEditText(s.get("family") or f["family"])
            size = QtWidgets.QDoubleSpinBox()
            size.setRange(0.0, 50.0)
            size.setDecimals(1)
            size.setSingleStep(0.5)
            size.setSpecialValueText(f"auto ({f['size']:.1f})")
            size.setValue(float(s.get("size") or 0.0))
            bold = QtWidgets.QCheckBox()
            bold.setChecked(bool(s.get("bold") if s.get("bold") is not None else f["bold"]))
            dx, dy = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
            for sp, v in ((dx, s.get("dx", 0.0)), (dy, s.get("dy", 0.0))):
                sp.setRange(-500, 500)
                sp.setDecimals(1)
                sp.setSingleStep(0.5)
                sp.setValue(float(v))
            fit = QtWidgets.QCheckBox()
            fit.setChecked(bool(s.get("fit", True)))
            det = s.get("detached")
            if det:
                text.setEnabled(False)
                text.setText("(on the sheet as a note)")
            for c, w in enumerate((text, font, size, bold, dx, dy, fit), 1):
                if c in (4, 7):
                    box = QtWidgets.QWidget()
                    bl = QtWidgets.QHBoxLayout(box)
                    bl.setContentsMargins(0, 0, 0, 0)
                    bl.setAlignment(QtCore.Qt.AlignCenter)
                    bl.addWidget(w)
                    self.table.setCellWidget(r, c, box)
                else:
                    self.table.setCellWidget(r, c, w)
                if det and c > 1:
                    w.setEnabled(False)
            self.rows.append({"name": f["name"], "f": f, "text": text, "font": font,
                              "size": size, "bold": bold, "dx": dx, "dy": dy, "fit": fit,
                              "detached": det})
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)

    def _row(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _font_all(self):
        fam = self.all_font.currentText().strip()
        if not fam:
            return
        for r in self.rows:
            r["font"].setEditText(fam)

    def values(self):
        d = settings_of(self.t)
        d["fit"] = self.fit_all.isChecked()
        texts = dict(self.t.EditableTexts)
        for r in self.rows:
            f = r["f"]
            old = d["fields"].get(r["name"], {})
            s = {}
            if old.get("detached"):
                s["detached"] = old["detached"]
            else:
                texts[r["name"]] = r["text"].text()
            fam = r["font"].currentText().strip()
            if fam and fam != f["family"]:
                s["family"] = fam
            if r["size"].value() > 0:
                s["size"] = r["size"].value()
            if r["bold"].isChecked() != f["bold"]:
                s["bold"] = r["bold"].isChecked()
            if r["dx"].value():
                s["dx"] = r["dx"].value()
            if r["dy"].value():
                s["dy"] = r["dy"].value()
            if not r["fit"].isChecked():
                s["fit"] = False
            if s:
                d["fields"][r["name"]] = s
            else:
                d["fields"].pop(r["name"], None)
        return d, texts

    def apply(self):
        d, texts = self.values()
        doc = self.t.Document
        doc.openTransaction("Title Block")
        try:
            d.pop("hash", None)
            _save_settings(self.t, d)
            apply(self.t, texts)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()

    def _ok(self):
        self.apply()
        self.accept()

    def _detach(self):
        r = self._row()
        if r is None or r["detached"]:
            return
        self.apply()
        detach(self.t, r["name"])
        self._fill()

    def _put_back(self):
        r = self._row()
        if r is None or not r["detached"]:
            return
        put_back(self.t, r["name"])
        self._fill()

    def _reset(self):
        r = self._row()
        if r is None or r["detached"]:
            return
        r["font"].setEditText(r["f"]["family"])
        r["size"].setValue(0.0)
        r["bold"].setChecked(r["f"]["bold"])
        r["dx"].setValue(0.0)
        r["dy"].setValue(0.0)
        r["fit"].setChecked(True)


def title_block_command():
    from mechflow_gui import drawings
    page = drawings.active_page()
    if page is None or page.Template is None:
        QtWidgets.QMessageBox.information(_mw(), "Title Block", "Open a drawing first.")
        return
    if not source_svg(page.Template):
        QtWidgets.QMessageBox.information(_mw(), "Title Block",
                                          "This sheet's template couldn't be read.")
        return
    TitleBlockDialog(page).exec()
