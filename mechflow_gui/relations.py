# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style sketch relations panel, shown while a sketch is open.

Add Relations: select sketch entities and the panel offers only the
relations that make sense for them (Horizontal, Coincident, Tangent, ...),
named as in SOLIDWORKS. One click adds it.

Existing Relations (Display/Delete Relations): the relations on the selected
entities - or all of them when nothing is selected. Click one to highlight it,
Delete removes it.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from mechflow_gui import sketch_status

# ------------------------------------------------------------ selection model

LINE, ARC, CIRCLE, POINT, OTHER = "line", "arc", "circle", "point", "other"


def _geo_kind(sk, g):
    try:
        geo = sk.Geometry[g] if g >= 0 else sk.ExternalGeo[-g - 1]
    except Exception:
        return LINE if g in (-1, -2) else OTHER
    t = type(geo).__name__
    if t in ("LineSegment", "Line"):
        return LINE
    if t == "Circle":
        return CIRCLE
    if t == "ArcOfCircle":
        return ARC
    if t == "Point":
        return POINT
    return OTHER


def _geo_name(sk, g):
    if g == -1:
        return "X axis"
    if g == -2:
        return "Y axis"
    k = _geo_kind(sk, g)
    word = {LINE: "Line", ARC: "Arc", CIRCLE: "Circle", POINT: "Point"}.get(k, "Curve")
    return f"{word}{g + 1}" if g >= 0 else f"Model edge {-g - 2}"


def _point_name(sk, g, pos):
    if g == -1 and pos == 1:
        return "Origin"
    if _geo_kind(sk, g) == POINT:
        return _geo_name(sk, g)
    which = {1: "start", 2: "end", 3: "centre"}.get(pos, "point")
    return f"{_geo_name(sk, g)} {which}"


def selected_items(sk):
    """[(kind, geo, pos)] for the sketch entities selected: kind 'edge' or
    'point' (pos: 1 start, 2 end, 3 centre)."""
    out = []
    for item in Gui.Selection.getSelectionEx():
        if item.Object is not sk:
            continue
        for sub in item.SubElementNames:
            sub = sub.split(".")[-1]
            try:
                if sub.startswith("Edge"):
                    g = int(sub[4:]) - 1
                    if _geo_kind(sk, g) == POINT:
                        out.append(("point", g, 1))
                    else:
                        out.append(("edge", g, 0))
                elif sub.startswith("ExternalEdge"):
                    out.append(("edge", -int(sub[12:]) - 2, 0))
                elif sub.startswith("Vertex"):
                    g, pos = sk.getGeoVertexIndex(int(sub[6:]) - 1)
                    out.append(("point", g, pos))
                elif sub == "RootPoint":
                    out.append(("point", -1, 1))
                elif sub == "H_Axis":
                    out.append(("edge", -1, 0))
                elif sub == "V_Axis":
                    out.append(("edge", -2, 0))
            except Exception:
                pass
    return out


def selected_constraints(sk):
    out = []
    for item in Gui.Selection.getSelectionEx():
        if item.Object is not sk:
            continue
        for sub in item.SubElementNames:
            sub = sub.split(".")[-1]
            if sub.startswith("Constraint"):
                try:
                    out.append(int(sub[10:]) - 1)
                except ValueError:
                    pass
    return out


# ------------------------------------------------------------ which relations

def options(sk, items):
    """[(SOLIDWORKS name, pixmap, [Sketcher.Constraint args, ...])] for the
    selected items."""
    edges = [(g) for k, g, p in items if k == "edge"]
    pts = [(g, p) for k, g, p in items if k == "point"]
    kinds = [_geo_kind(sk, g) for g in edges]
    lines = [g for g, k in zip(edges, kinds) if k == LINE]
    rounds = [g for g, k in zip(edges, kinds) if k in (ARC, CIRCLE)]
    opts = []

    def add(name, pix, *cons):
        opts.append((name, pix, list(cons)))

    n = len(items)
    # one entity
    if n == 1 and len(lines) == 1:
        add("Horizontal", "Constraint_Horizontal", ("Horizontal", lines[0]))
        add("Vertical", "Constraint_Vertical", ("Vertical", lines[0]))
    if n == 1 and edges and edges[0] >= 0:
        add("Fix", "Constraint_Block", ("Block", edges[0]))
    if n == 1 and pts and pts[0][0] >= 0:
        add("Fix", "Constraint_Lock", ("__fix_point__", pts[0][0], pts[0][1]))
    # two lines
    if n == 2 and len(lines) == 2:
        a, b = lines
        add("Parallel", "Constraint_Parallel", ("Parallel", a, b))
        add("Perpendicular", "Constraint_Perpendicular", ("Perpendicular", a, b))
        add("Collinear", "Constraint_Tangent", ("Tangent", a, b))
        if a >= 0 and b >= 0:
            add("Equal", "Constraint_EqualLength", ("Equal", a, b))
            add("Horizontal", "Constraint_Horizontal", ("Horizontal", a), ("Horizontal", b))
            add("Vertical", "Constraint_Vertical", ("Vertical", a), ("Vertical", b))
    # line + arc/circle, or two arcs/circles
    if n == 2 and len(lines) == 1 and len(rounds) == 1:
        add("Tangent", "Constraint_Tangent", ("Tangent", lines[0], rounds[0]))
    if n == 2 and len(rounds) == 2:
        a, b = rounds
        add("Concentric", "Constraint_Concentric", ("Coincident", a, 3, b, 3))
        add("Tangent", "Constraint_Tangent", ("Tangent", a, b))
        add("Equal", "Constraint_EqualLength", ("Equal", a, b))
    # two points
    if n == 2 and len(pts) == 2:
        (g1, p1), (g2, p2) = pts
        add("Coincident", "Constraint_PointOnPoint", ("Coincident", g1, p1, g2, p2))
        add("Horizontal", "Constraint_Horizontal", ("Horizontal", g1, p1, g2, p2))
        add("Vertical", "Constraint_Vertical", ("Vertical", g1, p1, g2, p2))
    # point + curve
    if n == 2 and len(pts) == 1 and len(edges) == 1:
        (gp, pp), ge = pts[0], edges[0]
        if kinds[0] in (ARC, CIRCLE) and pp == 3:
            add("Concentric", "Constraint_Concentric", ("Coincident", gp, pp, ge, 3))
        add("Coincident", "Constraint_PointOnObject", ("PointOnObject", gp, pp, ge))
        if kinds[0] == LINE and ge >= 0:
            add("Midpoint", "Constraint_Symmetric", ("Symmetric", ge, 1, ge, 2, gp, pp))
    # two points + a line: symmetric about it
    if n == 3 and len(pts) == 2 and len(lines) == 1:
        (g1, p1), (g2, p2) = pts
        add("Symmetric", "Constraint_Symmetric", ("Symmetric", g1, p1, g2, p2, lines[0]))
    # several lines at once
    if n >= 3 and len(lines) == n:
        add("Horizontal", "Constraint_Horizontal", *[("Horizontal", g) for g in lines])
        add("Vertical", "Constraint_Vertical", *[("Vertical", g) for g in lines])
        if all(g >= 0 for g in lines):
            add("Equal", "Constraint_EqualLength",
                *[("Equal", lines[0], g) for g in lines[1:]])
        add("Parallel", "Constraint_Parallel",
            *[("Parallel", lines[0], g) for g in lines[1:]])
    return opts


def apply(sk, name, cons):
    """Add one SOLIDWORKS relation (one or more FreeCAD constraints)."""
    import Sketcher
    doc = sk.Document
    doc.openTransaction(f"Add {name}")
    try:
        for c in cons:
            if c[0] == "__fix_point__":
                g, pos = c[1], c[2]
                p = sk.getPoint(g, pos)
                sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, g, pos, p.x))
                sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, g, pos, p.y))
            else:
                sk.addConstraint(Sketcher.Constraint(*c))
        doc.commitTransaction()
    except Exception as e:
        doc.abortTransaction()
        App.Console.PrintWarning(f"MechFlow: couldn't add {name} ({e})\n")
        return False
    try:
        sk.solve()
        sk.recompute()
    except Exception:
        pass
    return True


# ------------------------------------------------------------ existing relations

TYPE_NAMES = {
    "Coincident": "Coincident", "Horizontal": "Horizontal", "Vertical": "Vertical",
    "Parallel": "Parallel", "Perpendicular": "Perpendicular", "Tangent": "Tangent",
    "Equal": "Equal", "PointOnObject": "Coincident", "Symmetric": "Symmetric",
    "Block": "Fix", "Distance": "Distance", "DistanceX": "Horizontal distance",
    "DistanceY": "Vertical distance", "Radius": "Radius", "Diameter": "Diameter",
    "Angle": "Angle", "Weight": "Weight", "SnellsLaw": "Refraction",
    "InternalAlignment": "Internal", "Lock": "Fix",
}
DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")


def describe(sk, i):
    c = sk.Constraints[i]
    t = c.Type
    name = TYPE_NAMES.get(t, t)
    # SOLIDWORKS names a few special cases differently.
    if t == "Coincident" and c.FirstPos == 3 and c.SecondPos == 3:
        name = "Concentric"
    if t == "Tangent" and _geo_kind(sk, c.First) == LINE and _geo_kind(sk, c.Second) == LINE \
            and c.FirstPos == 0 and c.SecondPos == 0:
        name = "Collinear"
    if t == "Symmetric" and c.First == c.Second and c.First >= 0:
        name = "Midpoint"
    refs = []
    for g, pos in ((c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)):
        if g is None or g == -2000:          # -2000: slot not used
            continue
        r = _point_name(sk, g, pos) if pos else _geo_name(sk, g)
        if r not in refs:                    # e.g. the line in Midpoint appears twice
            refs.append(r)
    if t in DIMENSIONS:
        try:
            import math
            v = c.Value
            name += f" {math.degrees(v):g}°" if t == "Angle" else f" {v:g} mm"
        except Exception:
            pass
    uniq = refs
    return name, ", ".join(uniq)


def involves(c, geos):
    return any(g in geos for g in (c.First, c.Second, c.Third))


# ------------------------------------------------------------ the panel

class RelationsPanel(QtWidgets.QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("MechFlow_Relations")
        self.setStyleSheet(
            "#MechFlow_Relations { background: rgba(250,250,250,240);"
            " border: 1px solid #b8b8b8; border-radius: 4px; }"
            "#MechFlow_Relations QLabel#title { font-weight: 700; }"
            "#MechFlow_Relations QToolButton { text-align: left; padding: 2px 6px; }")
        self.setFixedWidth(230)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)

        head = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel("Relations")
        t.setObjectName("title")
        head.addWidget(t)
        head.addStretch(1)
        self.fold = QtWidgets.QToolButton()
        self.fold.setText("▴")
        self.fold.setAutoRaise(True)
        self.fold.clicked.connect(self._toggle_fold)
        head.addWidget(self.fold)
        lay.addLayout(head)

        self.body = QtWidgets.QWidget()
        b = QtWidgets.QVBoxLayout(self.body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(4)
        self.sel_label = QtWidgets.QLabel()
        self.sel_label.setWordWrap(True)
        self.sel_label.setStyleSheet("color: #444;")
        b.addWidget(self.sel_label)
        self.add_title = QtWidgets.QLabel("<b>Add Relations</b>")
        b.addWidget(self.add_title)
        self.add_box = QtWidgets.QWidget()
        self.add_grid = QtWidgets.QGridLayout(self.add_box)
        self.add_grid.setContentsMargins(0, 0, 0, 0)
        self.add_grid.setSpacing(2)
        b.addWidget(self.add_box)
        self.exist_title = QtWidgets.QLabel("<b>Existing Relations</b>")
        b.addWidget(self.exist_title)
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumHeight(90)
        self.list.setMaximumHeight(200)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.itemClicked.connect(self._highlight)
        b.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.del_btn = QtWidgets.QPushButton("Delete")
        self.del_btn.clicked.connect(self._delete)
        self.del_all = QtWidgets.QPushButton("Delete All")
        self.del_all.setToolTip("Delete every relation in the list (not dimensions)")
        self.del_all.clicked.connect(self._delete_all)
        row.addWidget(self.del_btn)
        row.addWidget(self.del_all)
        b.addLayout(row)
        lay.addWidget(self.body)
        self._indices = []
        self._folded = App.ParamGet(sketch_status.PARAMS).GetBool("RelationsFolded", False)
        self.body.setVisible(not self._folded)
        self.fold.setText("▾" if self._folded else "▴")

    def _toggle_fold(self):
        self._folded = not self._folded
        App.ParamGet(sketch_status.PARAMS).SetBool("RelationsFolded", self._folded)
        self.body.setVisible(not self._folded)
        self.fold.setText("▾" if self._folded else "▴")
        self.adjustSize()

    # ---- contents
    def refresh(self, sk):
        self.sk = sk
        items = selected_items(sk)
        if items:
            names = []
            for k, g, p in items:
                names.append(_point_name(sk, g, p) if k == "point" else _geo_name(sk, g))
            self.sel_label.setText("Selected: " + ", ".join(names))
        else:
            self.sel_label.setText("Select sketch entities to add relations.")
        # Add Relations buttons
        while self.add_grid.count():
            w = self.add_grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        opts = options(sk, items) if items else []
        self.add_title.setVisible(bool(opts))
        self.add_box.setVisible(bool(opts))
        for i, (name, pix, cons) in enumerate(opts):
            btn = QtWidgets.QToolButton()
            btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            try:
                btn.setIcon(Gui.getIcon(pix))
            except Exception:
                pass
            btn.setText(name)
            btn.setAutoRaise(True)
            btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, n=name, c=cons: self._add(n, c))
            self.add_grid.addWidget(btn, i // 2, i % 2)
        # Existing relations
        geos = {g for k, g, p in items}
        self.list.clear()
        self._indices = []
        for i, c in enumerate(sk.Constraints):
            if geos and not involves(c, geos):
                continue
            name, refs = describe(sk, i)
            it = QtWidgets.QListWidgetItem(f"{name}  ({refs})" if refs else name)
            if not getattr(c, "Driving", True) or not getattr(c, "IsActive", True):
                it.setForeground(QtGui.QBrush(QtGui.QColor(140, 140, 140)))
            self.list.addItem(it)
            self._indices.append(i)
        self.exist_title.setText("<b>Existing Relations</b>" +
                                 (" (selected)" if geos else ""))
        self.del_all.setEnabled(bool(self._indices))
        self.adjustSize()

    def _add(self, name, cons):
        if apply(self.sk, name, cons):
            Gui.Selection.clearSelection()
            _force_refresh()

    def _highlight(self, item):
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        Gui.Selection.clearSelection()
        for r in rows:
            try:
                Gui.Selection.addSelection(self.sk.Document.Name, self.sk.Name,
                                           f"Constraint{self._indices[r] + 1}")
            except Exception:
                pass
        global _hold
        _hold = True      # keep this list while a relation is highlighted

    def _delete(self):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True)
        if not rows:
            return
        self._remove([self._indices[r] for r in rows])

    def _delete_all(self):
        idx = [i for i in self._indices if self.sk.Constraints[i].Type not in DIMENSIONS]
        self._remove(idx)

    def _remove(self, idx):
        global _hold
        sk = self.sk
        doc = sk.Document
        doc.openTransaction("Delete relations")
        try:
            for i in sorted(set(idx), reverse=True):
                sk.delConstraint(i)
            doc.commitTransaction()
        except Exception as e:
            doc.abortTransaction()
            App.Console.PrintWarning(f"MechFlow: couldn't delete ({e})\n")
        try:
            sk.solve()
            sk.recompute()
        except Exception:
            pass
        _hold = False
        Gui.Selection.clearSelection()
        _force_refresh()


_panel = None
_timer = None
_last = None
_hold = False
suspended = False       # another sketch panel (e.g. Circular Pattern) is open


def _mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


def _force_refresh():
    global _last
    _last = None


def _place():
    area = _panel.parentWidget()
    if area is not None:
        _panel.move(10, 56)
        _panel.raise_()


def hidden():
    return App.ParamGet(sketch_status.PARAMS).GetBool("RelationsHidden", False)


def toggle():
    """Display/Delete Relations: show or hide the panel (remembered)."""
    p = App.ParamGet(sketch_status.PARAMS)
    p.SetBool("RelationsHidden", not hidden())
    if not hidden():
        p.SetBool("RelationsFolded", False)
        if _panel is not None:
            _panel._folded = False
            _panel.body.setVisible(True)
            _panel.fold.setText("\u25B4")
    _force_refresh()
    _safe(_tick)


def _tick():
    global _panel, _last, _hold
    if suspended:
        return
    sk = sketch_status.sketch_in_edit()
    if sk is not None and hidden():
        if _panel is not None:
            _panel.hide()
        return
    if sk is None:
        if _panel is not None:
            _panel.hide()
        _last = None
        _hold = False
        return
    if _panel is None:
        area = _mdi()
        if area is None:
            return
        _panel = RelationsPanel(area)
    cons_sel = selected_constraints(sk)
    if cons_sel and _hold:
        _panel.show()
        _place()
        return
    if not cons_sel:
        _hold = False
    sel = tuple(selected_items(sk))
    key = (sk.Name, sel, len(sk.Constraints), len(sk.Geometry),
           tuple((c.Type, c.First, c.Second, c.Third) for c in sk.Constraints))
    if key != _last:
        _last = key
        _panel.refresh(sk)
    _panel.show()
    _place()


def start():
    global _timer
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.setInterval(200)
        _timer.timeout.connect(lambda: _safe(_tick))
    _timer.start()


def stop():
    global _last
    if _timer is not None:
        _timer.stop()
    if _panel is not None:
        try:
            _panel.hide()
        except RuntimeError:
            pass
    _last = None


def _safe(fn):
    try:
        fn()
    except Exception as e:
        App.Console.PrintLog(f"MechFlow relations: {e}\n")
