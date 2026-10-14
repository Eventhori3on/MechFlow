# SPDX-License-Identifier: LGPL-2.1-or-later
"""Workshop drawings: what SOLIDWORKS gives you from Make Drawing from
Assembly, plus a sheet for each part.

- Assembly sheet: an isometric view, the Bill of Materials as a table above
  the title block, and a numbered balloon on each BOM item.
- Part sheets: front / top / side and an isometric, overall dimensions, a
  diameter callout and a position for each size of hole, and - for
  weldments - the cut list as a table.
- Save All Drawings as PDF writes every sheet into one folder.

Tables are drawn as SVG at true size (mm), so they print exactly.
"""

import math
import os
from xml.sax.saxutils import escape

import FreeCAD as App
from mechflow_gui import edge_curve, curve_name  # noqa: F401
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector
ISO_DIR, ISO_X = V(1, -1, 1), V(1, 1, 0)
ROW_H, FONT = 6.0, 2.5            # table row height and text height (mm)


# ------------------------------------------------------------ tables

def text_width(s, font=FONT):
    return len(s) * font * 0.6


def svg_table(headers, rows, min_widths=None, font=FONT, row_h=ROW_H):
    """(svg, width, height) of a ruled table, header on top, sized to fit."""
    n = len(headers)
    widths = []
    for c in range(n):
        w = max([text_width(headers[c], font)] + [text_width(str(r[c]), font) for r in rows])
        w = max(w + 3.0, (min_widths or [0] * n)[c])
        widths.append(round(w, 1))
    W = sum(widths)
    H = row_h * (len(rows) + 1)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" '
           f'viewBox="0 0 {W} {H}">',
           f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff" stroke="#000000" '
           f'stroke-width="0.5"/>',
           f'<rect x="0" y="0" width="{W}" height="{row_h}" fill="#e8e8e8" stroke="#000000" '
           f'stroke-width="0.5"/>']
    for i in range(1, len(rows) + 1):
        y = row_h * i
        out.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="#000000" '
                   f'stroke-width="{0.5 if i == 1 else 0.25}"/>')
    x = 0.0
    for w in widths[:-1]:
        x += w
        out.append(f'<line x1="{x:.2f}" y1="0" x2="{x:.2f}" y2="{H}" stroke="#000000" '
                   f'stroke-width="0.25"/>')
    base = row_h / 2 + font * 0.35

    def cell(text, x0, w, y, bold=False, centre=False):
        anchor = "middle" if centre else "start"
        tx = x0 + w / 2 if centre else x0 + 1.5
        weight = ' font-weight="bold"' if bold else ""
        return (f'<text x="{tx:.2f}" y="{y:.2f}" font-family="osifont, sans-serif" '
                f'font-size="{font}" text-anchor="{anchor}"{weight}>{escape(str(text))}</text>')
    x = 0.0
    for c, w in enumerate(widths):
        out.append(cell(headers[c], x, w, base, bold=True, centre=True))
        x += w
    for i, r in enumerate(rows, start=1):
        x = 0.0
        for c, w in enumerate(widths):
            centre = len(str(r[c])) <= 6
            out.append(cell(r[c], x, w, row_h * i + base, centre=centre))
            x += w
    out.append("</svg>")
    return "\n".join(out), W, H


def place_table(page, name, svg, w, h, right, bottom):
    """A table on the page with its bottom-right corner at (right, bottom)."""
    doc = page.Document
    sym = doc.addObject("TechDraw::DrawViewSymbol", name)
    sym.Symbol = svg
    page.addView(sym)
    sym.X = right - w / 2
    sym.Y = bottom + h / 2
    sym.Label = name
    return sym


# ------------------------------------------------------------ views

_CACHE = None          # shapes by object while a sheet is being made


def shape_once(o):
    """Part.getShape(o), remembered while a sheet is made (an assembly's
    hundreds of components are looked at several times)."""
    import Part
    key = (o.Document.Name, o.Name)
    if _CACHE is not None and key in _CACHE:
        return _CACHE[key]
    try:
        s = Part.getShape(o)
    except Exception:
        s = getattr(o, "Shape", None)
    if _CACHE is not None:
        _CACHE[key] = s
    return s


def _shape_of(objs):
    import Part
    shapes = []
    for o in objs:
        s = shape_once(o)
        if s is not None and not s.isNull():
            shapes.append(s)
    if not shapes:
        return None
    return shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)


def projected_box(direction, xdir, bb):
    """Width and height of a bounding box seen along direction."""
    d = V(direction).normalize()
    x = V(xdir) - d * V(xdir).dot(d)
    x.normalize()
    y = d.cross(x)
    xs, ys = [], []
    for px in (bb.XMin, bb.XMax):
        for py in (bb.YMin, bb.YMax):
            for pz in (bb.ZMin, bb.ZMax):
                p = V(px, py, pz)
                xs.append(p.dot(x))
                ys.append(p.dot(y))
    return max(xs) - min(xs), max(ys) - min(ys)


def projected_extent(direction, xdir, shape):
    """Width and height of the shape itself seen along direction (tighter
    than its bounding box when parts are spread out, as when exploded)."""
    d = V(direction).normalize()
    x = V(xdir) - d * V(xdir).dot(d)
    x.normalize()
    y = d.cross(x)
    pts = []
    for sol in (shape.Solids or [shape]):
        bb = sol.BoundBox
        for px in (bb.XMin, bb.XMax):
            for py in (bb.YMin, bb.YMax):
                for pz in (bb.ZMin, bb.ZMax):
                    pts.append(V(px, py, pz))
    xs = [p.dot(x) for p in pts]
    ys = [p.dot(y) for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys)


def _fit_scale(w, h, avail_w, avail_h):
    from mechflow_gui import drawings
    fit = min(avail_w / max(w, 1e-6), avail_h / max(h, 1e-6))
    for s in drawings.SCALES:
        if s <= fit:
            return s
    return drawings.SCALES[-1]


class ViewMap:
    """3D points to a view's own unscaled 2D coordinates, lined up with the
    view's actual lines (TechDraw centres the drawing its own way)."""

    def __init__(self, view, shape):
        self.view = view
        xs, ys = [], []
        pts = [v.Point for v in shape.Vertexes]
        step = max(1, len(pts) // 4000)
        for p in pts[::step]:
            q = view.projectPoint(p)
            xs.append(q.x)
            ys.append(q.y)
        ext = _view_extent(view)
        if xs and ext:
            self.dx = (min(xs) + max(xs)) / 2 - (ext[0] + ext[1]) / 2
            self.dy = (min(ys) + max(ys)) / 2 - (ext[2] + ext[3]) / 2
        else:
            c = view.projectPoint(shape.BoundBox.Center)
            self.dx, self.dy = c.x, c.y

    def __call__(self, p):
        q = self.view.projectPoint(V(p))
        return V(q.x - self.dx, q.y - self.dy, 0)


def _edges(view):
    """The view's lines in its own unscaled (model mm) coordinates."""
    out = []
    i = 0
    while i < 50000:
        try:
            e = view.getEdgeByIndex(i)
        except Exception:
            break
        if e is None:
            break
        out.append((i, e))
        i += 1
    return out


def _view_extent(view):
    """(xmin, xmax, ymin, ymax) of a view's lines, unscaled view units."""
    xs, ys = [], []
    big = 1e7
    for _i, e in _edges(view):
        try:
            bb = e.BoundBox
        except Exception:
            continue
        vals = (bb.XMin, bb.XMax, bb.YMin, bb.YMax)
        if any(not math.isfinite(v) or abs(v) > big for v in vals):
            continue
        xs += [bb.XMin, bb.XMax]
        ys += [bb.YMin, bb.YMax]
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def wait(page, timeout=60):
    from mechflow_gui import drawings
    drawings.wait_for_views(page, timeout)


# ------------------------------------------------------------ balloons

def _front_point(shape, direction):
    """A point on the shape nearest the viewer (likely to be visible)."""
    d = V(direction).normalize()
    best = None
    for v in shape.Vertexes:
        k = v.Point.dot(d)
        if best is None or k > best[0]:
            best = (k, v.Point)
    if best is None:
        return shape.BoundBox.Center
    # pull it a little towards the middle so the arrow lands on the part
    c = shape.BoundBox.Center
    return best[1] + (c - best[1]) * 0.15


def add_balloons(page, view, items, shape, scale):
    """items: [(number text, 3D point)]. Balloons round the view, leaders
    to the points, spaced so they don't overlap."""
    ext = _view_extent(view)
    if ext is None:
        return []
    xmin, xmax, ymin, ymax = ext
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    hx, hy = (xmax - xmin) / 2, (ymax - ymin) / 2
    gap = 14.0 / scale                      # balloons sit 14 mm outside the view
    ax, ay = hx + gap, hy + gap
    to2d = ViewMap(view, shape)
    pts = []
    for text, p in items:
        o = to2d(p)
        ang = math.atan2((o.y - cy) / max(ay, 1e-6), (o.x - cx) / max(ax, 1e-6))
        pts.append([ang, text, o])
    pts.sort(key=lambda t: t[0])
    # keep them apart: at least ~11 mm along the ellipse (by arc length,
    # so they don't bunch at the ends of a long ellipse)
    if pts:
        N = 1440
        angs = [2 * math.pi * i / N for i in range(N + 1)]
        cum = [0.0]
        for i in range(1, N + 1):
            x0, y0 = ax * math.cos(angs[i - 1]), ay * math.sin(angs[i - 1])
            x1, y1 = ax * math.cos(angs[i]), ay * math.sin(angs[i])
            cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
        total = cum[-1]

        def to_s(a):
            a %= 2 * math.pi
            i = min(N - 1, int(a / (2 * math.pi) * N))
            f = (a - angs[i]) / (angs[i + 1] - angs[i])
            return cum[i] + f * (cum[i + 1] - cum[i])

        def to_a(sv):
            sv %= total
            lo, hi = 0, N
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if cum[mid] <= sv:
                    lo = mid
                else:
                    hi = mid
            f = (sv - cum[lo]) / max(cum[lo + 1] - cum[lo], 1e-12)
            return angs[lo] + f * (angs[lo + 1] - angs[lo])
        step = min(17.0 / scale, total / len(pts))
        want = sorted(to_s(t[0]) for t in pts)
        order = sorted(range(len(pts)), key=lambda i: to_s(pts[i][0]))
        got = list(want)
        for i in range(1, len(got)):
            got[i] = max(got[i], got[i - 1] + step)
        over = got[-1] - (got[0] + total - step)
        if over > 0:
            got = [g - over * i / max(1, len(got) - 1) for i, g in enumerate(got)]
            for i in range(1, len(got)):
                got[i] = max(got[i], got[i - 1] + step)
        shift = sum(w - g for w, g in zip(want, got)) / len(got)
        for j, i in enumerate(order):
            pts[i][0] = to_a(got[j] + shift)
    made = []
    doc = page.Document
    for ang, text, o in pts:
        b = doc.addObject("TechDraw::DrawViewBalloon", "Balloon")
        b.SourceView = view
        b.OriginX, b.OriginY = o.x, o.y
        b.X = cx + ax * math.cos(ang)
        b.Y = cy + ay * math.sin(ang)
        b.Text = str(text)
        try:
            b.BubbleShape = "Circular"
        except Exception:
            pass
        page.addView(b)
        made.append(b)
    return made


# ------------------------------------------------------------ dimensions

def _circles(view):
    """[(index, centre, radius)] of the view's full circles."""
    out = []
    for i, e in _edges(view):
        c = edge_curve(e)
        if type(c).__name__ == "Circle" and abs(e.LastParameter - e.FirstParameter) > 6.2:
            out.append((i, V(c.Center), c.Radius))
    return out


def add_dimensions(page, view, scale, overall=True, holes=True, max_hole_sizes=4,
                   overall_dirs=(0, 1)):
    """Overall width / height and, for each hole size, a diameter callout
    (n x) and the first hole's position from the left and bottom."""
    import TechDraw
    made = []
    ext = _view_extent(view)
    if ext is None:
        return made
    _activate(view.Document)
    xmin, xmax, ymin, ymax = ext
    off = 10.0 / scale
    k = view_scale(view)             # dimension positions are on the sheet (scaled)
    if overall:
        for direction, pos in ((0, (0.5 * (xmin + xmax), ymin - off)),
                               (1, (xmin - off, 0.5 * (ymin + ymax)))):
            if direction not in overall_dirs:
                continue
            try:
                d = TechDraw.makeExtentDim(view, [], direction)
                d.X, d.Y = pos[0] * k, pos[1] * k
                made.append(d)
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: overall dimension skipped ({e})\n")
    if not holes:
        return made
    sizes = {}
    for i, c, r in _circles(view):
        if r < 0.5 or 2 * r > 0.8 * min(xmax - xmin, ymax - ymin):
            continue
        sizes.setdefault(round(r, 2), []).append((i, c))
    tier = 2
    for r, lst in sorted(sizes.items(), key=lambda kv: -len(kv[1]))[:max_hole_sizes]:
        lst.sort(key=lambda t: (round(t[1].y, 1), t[1].x))
        i, c = lst[0]
        dx0, dy0 = _datums(view, c, xmin, ymin)
        doc = page.Document
        try:
            d = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
            d.Type = "Diameter"
            d.References2D = [(view, f"Edge{i}")]
            n = len(lst)
            d.FormatSpec = (f"{n}× ⌀%.1f" if n > 1 else "⌀%.1f")
            page.addView(d)
            d.X, d.Y = (c.x - r) * k - 14.0, (c.y + r) * k + 8.0
            made.append(d)
            # where the first hole is: from the left and the bottom
            for kind, p0, p1, pos in (
                    ("DistanceX", V(dx0, c.y, 0), V(c.x, c.y, 0),
                     ((dx0 + c.x) / 2, ymin - off * tier)),
                    ("DistanceY", V(c.x, dy0, 0), V(c.x, c.y, 0),
                     (xmin - off * tier, (dy0 + c.y) / 2))):
                if abs((p1 - p0).Length) < 1e-3:
                    continue
                dd = _distance_dim(view, kind, p0, p1, k)
                if dd is not None:
                    dd.X, dd.Y = pos[0] * k, pos[1] * k
                    made.append(dd)
            tier += 1
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: hole dimension skipped ({e})\n")
    return _drop_invalid(made)


def _datums(view, c, xmin, ymin):
    """Edges to measure a hole from: the longest vertical line left of it and
    the longest horizontal line below it (the part's side and bottom, not a
    nozzle flange sticking out)."""
    vert, horiz = [], []
    for _i, e in _edges(view):
        if curve_name(e) not in ("Line", "LineSegment"):
            continue
        p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if abs(p0.x - p1.x) < 1e-6 and p0.x <= c.x + 1e-6:
            vert.append((abs(p1.y - p0.y), -abs(c.x - p0.x), p0.x))
        if abs(p0.y - p1.y) < 1e-6 and p0.y <= c.y + 1e-6:
            horiz.append((abs(p1.x - p0.x), -abs(c.y - p0.y), p0.y))
    dx = max(vert)[2] if vert else xmin
    dy = max(horiz)[2] if horiz else ymin
    return dx, dy


def view_scale(view):
    """A view's real scale: a projection-group view's own Scale can be
    stale - the group's is the one used."""
    for p in getattr(view, "InList", []):
        if p.TypeId == "TechDraw::DrawProjGroup":
            return float(p.Scale)
    return float(view.Scale)


def _distance_dim(view, kind, p0, p1, k):
    """makeDistanceDim takes points on the sheet (model x scale)."""
    import TechDraw
    return TechDraw.makeDistanceDim(view, kind, p0 * k, p1 * k)


def _drop_invalid(dims):
    """Remove dimensions TechDraw couldn't measure (they draw as stray lines)."""
    if not dims:
        return dims
    doc = dims[0].Document
    doc.recompute()
    keep = []
    for d in dims:
        try:
            ok = d.isValid() and abs(d.getRawValue()) > 1e-6
        except Exception:
            ok = False
        if ok:
            keep.append(d)
        else:
            try:
                doc.removeObject(d.Name)
            except Exception:
                pass
    return keep


# ------------------------------------------------------------ sheets

def _layout(template):
    from mechflow_gui import drawings
    W, H, left, margin, tb_w, tb_h = drawings._sheet_area(template)
    return W, H, left, margin, tb_w, tb_h


FASTENER_LIMIT = 40     # more than this and the view leaves them out by default


def _is_fastener(o):
    return type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject"


def view_sources(asm, fasteners=None):
    """The assembly's components to draw. Bolts, nuts and washers are left
    out of big assemblies: FreeCAD's drawing view slows down with the square
    of its line count (the bunker tank's 240 fasteners took a 2-minute view
    down to 8 seconds). They stay in the BOM and get their balloons."""
    comps, fast = [], []
    for o in asm.Group:
        if o.TypeId.startswith("Assembly::") or o.TypeId in ("Spreadsheet::Sheet",):
            continue
        if type(getattr(o, "Proxy", None)).__name__ in ("Joint", "GroundedJoint"):
            continue
        try:
            sh = shape_once(o)
            if sh is None or sh.isNull() or not sh.Solids:
                continue
        except Exception:
            continue
        (fast if _is_fastener(o) else comps).append(o)
    if fasteners is None:
        fasteners = len(fast) <= FASTENER_LIMIT
    return comps + (fast if fasteners else []), len(fast), fasteners


def assembly_sheet(asm, sheet, sheet_no=1, sheets=1, fasteners=None, exploded=False):
    """Isometric of the assembly, BOM table and balloons. Returns the page.
    exploded=True draws the exploded view (see exploded.py) instead."""
    global _CACHE
    _CACHE = {}
    try:
        return _assembly_sheet(asm, sheet, sheet_no, sheets, fasteners, exploded)
    finally:
        _CACHE = None


def _assembly_sheet(asm, sheet, sheet_no, sheets, fasteners, exploded):
    from mechflow_gui import bom, drawings
    doc = asm.Document
    page = drawings.new_page(doc, sheet)
    page.Label = f"{asm.Label} - {'Exploded View' if exploded else 'Assembly'}"
    t = page.Template
    W, H, left, margin, tb_w, tb_h = _layout(t)
    data, objs = bom.rows_with_objects(asm)
    headers = ["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY."]
    table_rows = [(str(i), n, d, str(q)) for i, (n, d, q) in enumerate(data, start=1)]
    svg, tw, th = svg_table(headers, table_rows, [14, 40, 30, 11])
    bottom = margin + tb_h + 6
    if bottom + th > H - margin:          # too tall above the title block: beside it
        bottom = margin
    place_table(page, "BOM table", svg, tw, th, W - margin, bottom)
    # the view, in the space left of the table
    sources, n_fast, shown = view_sources(asm, fasteners)
    move = {}
    if exploded:
        from mechflow_gui import exploded as ex
        links, move = ex.exploded_links(asm, sources)
        sources = links
    shape = _shape_of(sources)
    if shape is None:
        doc.removeObject(page.Name)
        raise ValueError("the assembly has no parts to draw")
    pw, ph = projected_extent(ISO_DIR, ISO_X, shape)
    area_w = W - left - margin - tw - 40
    area_h = H - 2 * margin - 30
    # room for the balloons round it: about 20 mm each side
    scale = _fit_scale(pw, ph, area_w - 45, area_h - 45)
    v = doc.addObject("TechDraw::DrawViewPart", "AssemblyView")
    page.addView(v)
    v.Label = "Exploded isometric" if exploded else "Isometric"
    v.Source = sources
    v.Direction, v.XDirection = ISO_DIR, ISO_X
    if n_fast and not shown:
        # a note in the corner (a caption under the view runs into balloons)
        note = doc.addObject("TechDraw::DrawViewAnnotation", "Note")
        note.Text = ["Bolts, nuts and washers not shown (see BOM)"]
        note.TextSize = 3.5
        page.addView(note)
        note.X = left + 55
        note.Y = margin + 8
    v.ScaleType = "Custom"
    v.Scale = scale
    v.X = left + area_w / 2 + 10
    v.Y = margin + 15 + area_h / 2
    page.Scale = scale
    drawings.fill_title_block(t, [asm], scale, sheet_no, sheets)
    _fill(t, {"title": asm.Label, "DrawingTitle1": asm.Label,
              "part_material": "", "Weight": _total_weight([asm])})
    doc.recompute()
    wait(page)
    # balloons, numbered as the BOM
    items = []
    if exploded:
        from mechflow_gui import exploded as ex
        move = ex.follow(asm, move)       # hidden bolts go with what they hold
    for i, (name, _d, _q) in enumerate(data, start=1):
        best = None
        for o in objs.get(name, []):
            try:
                sh = _shape_of([o])
            except Exception:
                sh = None
            if sh is None:
                continue
            if exploded:
                sh = sh.copy()
                sh.translate(move.get(o, V()))
            p = _front_point(sh, ISO_DIR)
            k = p.dot(V(ISO_DIR).normalize())
            if best is None or k > best[0]:
                best = (k, p)
        if best is not None:
            items.append((str(i), best[1]))
    add_balloons(page, v, items, shape, scale)
    doc.recompute()
    return page


def _fill(template, values):
    texts = dict(template.EditableTexts)
    for k, val in values.items():
        if k in texts:
            texts[k] = val
    template.EditableTexts = texts


def _total_weight(objs):
    try:
        from mechflow_gui import material, commands
        items = material.mass_items(objs)
        if not items or any(d is None for *_x, d in items):
            return ""
        kg = commands.mass_summary(items)[0]
        return f"{kg:,.1f} kg"
    except Exception:
        return ""


AUTO = "Auto (A3, bigger if it helps)"
AUTO_SHEETS = ["A3 (ISO) - Landscape", "A2 (ISO) - Landscape", "A1 (ISO) - Landscape"]


def auto_sheet(objs, sizes=AUTO_SHEETS):
    """The smallest sheet that doesn't leave the part tiny: go up a size
    only while that gives a bigger scale and the views fill under 45%."""
    from mechflow_gui import drawings
    import FreeCAD
    best = sizes[0]
    prev_scale = None
    for sz in sizes:
        t = _probe_template(sz)
        s_ = drawings.pick_scale(objs, t, True)
        if prev_scale is not None and s_ <= prev_scale:
            break
        best, prev_scale = sz, s_
        if drawings.sheet_fill(objs, t, s_) >= 0.45:
            break
    return best


class _T:
    def __init__(self, w, h):
        self.Width, self.Height = w, h


def _probe_template(sheet):
    sizes = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594),
             "A0": (1189, 841)}
    k = sheet.split()[0]
    w, h = sizes.get(k, (420, 297))
    return _T(w, h)


def part_sheet(objs, sheet, sheet_no=1, sheets=1, dims=True, title=None):
    """Standard views of a part, overall and hole dimensions, and its
    weldment cut list. Returns the page."""
    from mechflow_gui import drawings
    doc = objs[0].Document
    if sheet == AUTO:
        sheet = auto_sheet(objs)
    page = drawings.new_page(doc, sheet)
    t = page.Template
    W, H, left, margin, tb_w, tb_h = _layout(t)
    g, iso, scale = drawings.add_standard_views(page, objs, drawings._projection(), True)
    page.Label = f"{title or drawings._title_of(objs)} - Part"
    drawings.fill_title_block(t, objs, scale, sheet_no, sheets)
    vals = {"Weight": _total_weight(objs)}
    if title:
        vals.update({"title": title, "DrawingTitle1": title})
    _fill(t, vals)
    doc.recompute()
    wait(page)
    decorate_part_page(page, g, scale, dims)
    return page


def _activate(doc):
    """TechDraw's dimension helpers work in the active document."""
    try:
        if App.ActiveDocument is not doc:
            App.setActiveDocument(doc.Name)
        if Gui.ActiveDocument is None or Gui.ActiveDocument.Document is not doc:
            Gui.setActiveDocument(doc.Name)
    except Exception:
        pass


def _span(view):
    ext = _view_extent(view)
    return 0.0 if ext is None else min(ext[1] - ext[0], ext[3] - ext[2])


def decorate_part_page(page, group, scale, dims=True):
    """Dimensions on the front and side views, and the weldment cut list
    table, on a part's standard-view page."""
    import TechDraw
    doc = page.Document
    W, H, left, margin, tb_w, tb_h = _layout(page.Template)
    if dims and group is not None:
        views = list(getattr(group, "Views", []))
        front = [x for x in views if x.Label == "Front"]
        side = [x for x in views if x.Label in ("Right", "Left")]
        holes_on = max(views, key=lambda x: len([c for c in _circles(x) if c[2] < 0.25 *
                                                  max(1.0, _span(x))]), default=None)
        if front:
            add_dimensions(page, front[0], scale, holes=holes_on is front[0])
        if holes_on is not None and front and holes_on is not front[0]:
            # the top view adds the depth; front already has width and height
            add_dimensions(page, holes_on, scale,
                           overall_dirs=(1,) if holes_on.Label == "Top" else ())
        if side:
            ext = _view_extent(side[0])
            if ext is not None:
                try:            # depth: the width of the side view
                    _activate(side[0].Document)
                    d = TechDraw.makeExtentDim(side[0], [], 0)
                    k = view_scale(side[0])
                    d.X, d.Y = 0.5 * (ext[0] + ext[1]) * k, ext[2] * k - 10.0
                    _drop_invalid([d])
                except Exception as e:
                    App.Console.PrintWarning(f"MechFlow: depth dimension skipped ({e})\n")
    try:
        from mechflow_gui import weldments
        cl = weldments.cut_items(doc)
    except Exception:
        cl = []
    if cl:
        rows = []
        for i, (desc, length, a1, a2, qty) in enumerate(cl, start=1):
            ln = length if isinstance(length, str) else f"{length:g}"
            rows.append((str(i), str(qty), desc, ln, f"{a1:g}", f"{a2:g}"))
        svg, tw, th = svg_table(["ITEM NO.", "QTY.", "DESCRIPTION", "LENGTH", "ANGLE1", "ANGLE2"],
                                rows, [14, 10, 34, 18, 14, 14])
        place_table(page, "Cut list table", svg, tw, th, W - margin, margin + tb_h + 6)
    doc.recompute()


def part_targets(asm):
    """The distinct parts in an assembly to draw: [(objects, title)] - one
    per part file / Part (not Toolbox hardware)."""
    from mechflow_gui import stdparts
    seen, out = set(), []
    for o in asm.Group:
        lo = o
        try:
            lo = o.getLinkedObject(True)
        except Exception:
            pass
        if lo is None or lo is asm:
            continue
        if stdparts.is_std_object(lo) or type(getattr(lo, "Proxy", None)).__name__ == "FSScrewObject":
            continue
        if lo.TypeId not in ("App::Part", "PartDesign::Body") and not (
                lo.isDerivedFrom("Part::Feature") and lo.Shape.Solids):
            continue
        key = (lo.Document.Name, lo.Name)
        if key in seen:
            continue
        seen.add(key)
        title = lo.Document.Label if lo.Document is not asm.Document else lo.Label
        out.append(([lo], title))
    return out


def load_parts(asm):
    """FreeCAD opens an assembly's part files only partly; a drawing in a
    partly loaded file can't be recomputed or saved. Load them fully."""
    done = []
    try:
        deps = asm.Document.getDependentDocuments()
    except Exception:
        deps = list(App.listDocuments().values())
    for d in deps:
        if getattr(d, "Partial", False):
            try:
                d.restore()
                done.append(d.Label)
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: couldn't fully load {d.Label} ({e})\n")
    if done:
        asm.Document.recompute()
    return done


def make_pack(asm, sheet, part_sheet_size=None, with_parts=True, fasteners=None):
    """Assembly sheet plus one sheet per part. Returns the pages."""
    if with_parts:
        load_parts(asm)
    targets = part_targets(asm) if with_parts else []
    total = 1 + len(targets)
    pages = [assembly_sheet(asm, sheet, 1, total, fasteners)]
    for n, (objs, title) in enumerate(targets, start=2):
        try:
            pages.append(part_sheet(objs, part_sheet_size or sheet, n, total, title=title))
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: no drawing for {title} ({e})\n")
    return pages


def save_all_pdf(pages, folder):
    """Every page as a PDF in folder ('01 - BunkerTank - Assembly.pdf')."""
    import TechDrawGui
    from mechflow_gui import drawings
    os.makedirs(folder, exist_ok=True)
    written = []
    cols = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors")
    had = cols.GetUnsigned("PageColor", 0)
    cols.SetUnsigned("PageColor", 0xFFFFFFFF)
    try:
        for i, p in enumerate(pages, start=1):
            drawings.wait_for_views(p)
            safe = "".join(ch for ch in p.Label if ch not in '<>:"/\\|?*').strip()
            path = os.path.join(folder, f"{i:02d} - {safe}.pdf")
            try:
                p.ViewObject.show()
            except Exception:
                pass
            TechDrawGui.exportPageAsPdf(p, path)
            written.append(path)
    finally:
        if had:
            cols.SetUnsigned("PageColor", had)
        else:
            cols.RemUnsigned("PageColor")
    return written


# ------------------------------------------------------------ commands

class PackDialog(QtWidgets.QDialog):
    def __init__(self, asm):
        super().__init__(Gui.getMainWindow())
        from mechflow_gui import drawings
        self.setWindowTitle("Make Drawing from Assembly")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(f"Drawings of <b>{asm.Label}</b>"))
        f = QtWidgets.QFormLayout()
        self.sheet = QtWidgets.QComboBox()
        self.sheet.addItems(list(drawings.SHEETS))
        self.sheet.setCurrentText("A2 (ISO) - Landscape")
        f.addRow("Assembly sheet", self.sheet)
        self.psheet = QtWidgets.QComboBox()
        self.psheet.addItems([AUTO] + list(drawings.SHEETS))
        self.psheet.setCurrentText(AUTO)
        f.addRow("Part sheets", self.psheet)
        lay.addLayout(f)
        self.parts = QtWidgets.QCheckBox("Also a sheet for each part (dimensioned)")
        self.parts.setChecked(True)
        lay.addWidget(self.parts)
        _src, n_fast, shown = view_sources(asm)
        self.fast = QtWidgets.QCheckBox(f"Show the {n_fast} bolts, nuts and washers in the view")
        self.fast.setChecked(shown)
        self.fast.setToolTip("Hundreds of fasteners make FreeCAD's drawing view very slow; "
                             "they're always in the BOM")
        self.fast.setVisible(n_fast > 0)
        lay.addWidget(self.fast)
        b = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                       QtWidgets.QDialogButtonBox.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)


_last_pack = []


def make_drawing_from_assembly(asm=None):
    from mechflow_gui import assembly, drawings
    asm = asm or assembly.active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Make Drawing from Assembly",
                                          "Open an assembly first.")
        return None
    dlg = PackDialog(asm)
    if not dlg.exec():
        return None
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        asm.Document.openTransaction("Make Drawing from Assembly")
        pages = make_pack(asm, dlg.sheet.currentText(), dlg.psheet.currentText(),
                          dlg.parts.isChecked(), dlg.fast.isChecked())
        asm.Document.commitTransaction()
    except Exception as e:
        asm.Document.abortTransaction()
        QtWidgets.QApplication.restoreOverrideCursor()
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Make Drawing from Assembly",
                                      f"The drawings couldn't be made: {e}")
        return None
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    _last_pack[:] = pages
    drawings._open(pages[0])
    return pages


def all_pages():
    pages = []
    for d in App.listDocuments().values():
        pages += [o for o in d.Objects if o.TypeId == "TechDraw::DrawPage"]
    return pages


def save_all_drawings():
    pages = [p for p in _last_pack if _alive(p)] or all_pages()
    if not pages:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Save All Drawings as PDF",
                                          "There are no drawings open.")
        return None
    doc = pages[0].Document
    start = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
    folder = QtWidgets.QFileDialog.getExistingDirectory(
        Gui.getMainWindow(), "Save All Drawings as PDF - choose a folder", start)
    if not folder:
        return None
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        written = save_all_pdf(pages, folder)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    QtWidgets.QMessageBox.information(
        Gui.getMainWindow(), "Save All Drawings as PDF",
        f"{len(written)} PDF{'s' if len(written) != 1 else ''} saved in\n{folder}")
    return written


def _alive(o):
    try:
        return o.Document is not None and o.Name is not None
    except Exception:
        return False
