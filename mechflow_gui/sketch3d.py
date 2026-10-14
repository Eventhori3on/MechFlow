# SPDX-License-Identifier: LGPL-2.1-or-later
"""3D Sketch (SOLIDWORKS 3D Sketch / Tube and Pipe route sketch).

Lines drawn straight in the 3D view, in X, Y and Z, for a pipe route:

- click to place points; each line runs along X, Y or Z (untick "Along
  X / Y / Z only" for any direction in the drawing plane),
- the drawing plane goes through the last point and faces the screen
  (Auto), or is fixed to XY / YZ / ZX - Tab steps through them,
- hover a flange face or nozzle edge to start or finish on its centre
  (the sketch then follows it if the part moves),
- click a point of the sketch to start a branch from it, Esc to stop the
  current line chain,
- every line is listed with its direction and length: type an exact length
  and the lines after it move along.

It is one item in the tree ("3D Sketch1", rename it as you like). Route
Pipe follows it like any sketch.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

V = App.Vector
TOL = 1e-6
AXES = {"+X": V(1, 0, 0), "-X": V(-1, 0, 0), "+Y": V(0, 1, 0), "-Y": V(0, -1, 0),
        "+Z": V(0, 0, 1), "-Z": V(0, 0, -1)}
PLANES = ["Auto", "XY", "YZ", "ZX"]
NORMALS = {"XY": V(0, 0, 1), "YZ": V(1, 0, 0), "ZX": V(0, 1, 0)}


# ------------------------------------------------------------ the object

class Sketch3D:
    def __init__(self, obj):
        obj.addProperty("App::PropertyVectorList", "Points", "3D Sketch", "Points (in the part's axes)")
        obj.addProperty("App::PropertyIntegerList", "Lines", "3D Sketch",
                        "Lines as pairs of point numbers")
        obj.addProperty("App::PropertyLinkSubListGlobal", "Anchors", "3D Sketch",
                        "Round edges (flange faces, nozzles) points sit on")
        obj.addProperty("App::PropertyIntegerList", "AnchorPoints", "3D Sketch",
                        "Which point each anchor holds")
        obj.Proxy = self
        self.Type = "Sketch3D"

    def execute(self, obj):
        import Part
        pts = list(obj.Points)
        moved = False
        for (o, subs), i in zip(obj.Anchors, obj.AnchorPoints):
            if not subs or i >= len(pts):
                continue
            c = anchor_point(obj, o, subs[0])
            if c is not None and (c - pts[i]).Length > 1e-6:
                pts[i] = c
                moved = True
        if moved:
            obj.Points = pts
        edges = []
        for a, b in pairs(obj):
            if a < len(pts) and b < len(pts) and (pts[a] - pts[b]).Length > TOL:
                edges.append(Part.LineSegment(pts[a], pts[b]).toShape())
        if edges:
            obj.Shape = Part.Compound(edges)
        elif pts:
            obj.Shape = Part.Compound([Part.Vertex(p) for p in pts])
        else:
            obj.Shape = Part.Shape()

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderSketch3D:
    def __init__(self, vobj):
        vobj.Proxy = self
        try:
            vobj.LineColor = (0.86, 0.38, 0.0)
            vobj.PointColor = (0.86, 0.38, 0.0)
            vobj.LineWidth = 2.0
            vobj.PointSize = 6.0
        except Exception:
            pass

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path("Sketch3D.svg")

    def getDisplayModes(self, vobj):
        return ["Wireframe"]

    def getDefaultDisplayMode(self):
        return "Wireframe"

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.Control.showDialog(Sketch3DPanel(vobj.Object))
        return True

    def setEdit(self, vobj, mode=0):
        return False

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_sketch3d(o):
    return type(getattr(o, "Proxy", None)).__name__ == "Sketch3D"


def pairs(obj):
    ln = list(obj.Lines)
    return [(ln[i], ln[i + 1]) for i in range(0, len(ln) - 1, 2)]


def _container(o):
    try:
        p = o.getParentGeoFeatureGroup()
    except Exception:
        p = None
    return p


def to_local(obj_or_container, p):
    """Global point -> the sketch's (container's) axes."""
    c = obj_or_container if (obj_or_container is None or not is_sketch3d(obj_or_container)) \
        else _container(obj_or_container)
    if c is None:
        return V(p)
    try:
        return c.getGlobalPlacement().inverse().multVec(V(p))
    except Exception:
        return V(p)


def to_global(sketch, p):
    c = _container(sketch)
    if c is None:
        return V(p)
    try:
        return c.getGlobalPlacement().multVec(V(p))
    except Exception:
        return V(p)


def circle_frame(obj, sub):
    """(centre, axis) of a round edge, in global axes, through links."""
    import Part
    try:
        e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
        c = e.Curve
        if type(c).__name__ != "Circle":
            return None
        return V(c.Center), V(c.Axis)
    except Exception:
        return None


def anchor_point(sketch, obj, sub):
    f = circle_frame(obj, sub)
    if f is None:
        return None
    return to_local(sketch, f[0])


def make(container=None, label=None):
    doc = container.Document if container is not None else App.ActiveDocument
    o = doc.addObject("Part::FeaturePython", "Sketch3D")
    Sketch3D(o)
    if container is not None:
        container.addObject(o)
    if App.GuiUp:
        ViewProviderSketch3D(o.ViewObject)
    if label is None:
        n = 1 + sum(1 for x in doc.Objects if is_sketch3d(x) and x is not o)
        label = f"3D Sketch{n}"
    o.Label = label
    return o


# ------------------------------------------------------------ editing (no GUI)

class Editor:
    """Points and lines of a 3D sketch, edited as a tree from its first
    point: changing a line's length moves everything beyond it."""

    def __init__(self, sketch):
        self.sketch = sketch
        self.pts = [V(p) for p in sketch.Points]
        self.lines = pairs(sketch)
        self.anchors = [(o, list(s)) for o, s in sketch.Anchors]
        self.anchor_pts = list(sketch.AnchorPoints)
        self.current = len(self.pts) - 1 if self.pts else None

    # -- storing
    def save(self):
        s = self.sketch
        s.Points = self.pts
        flat = []
        for a, b in self.lines:
            flat += [a, b]
        s.Lines = flat
        s.Anchors = [(o, tuple(subs)) for o, subs in self.anchors]
        s.AnchorPoints = self.anchor_pts
        s.Document.recompute()

    # -- building
    def find_point(self, p, tol=0.01):
        for i, q in enumerate(self.pts):
            if (q - p).Length < tol:
                return i
        return None

    def add_point(self, p):
        i = self.find_point(p)
        if i is None:
            self.pts.append(V(p))
            i = len(self.pts) - 1
        return i

    def start(self, p, anchor=None):
        """Begin (or branch) at p."""
        i = self.add_point(p)
        self.current = i
        if anchor is not None:
            self.set_anchor(i, anchor)
        return i

    def line_to(self, p, anchor=None):
        if self.current is None:
            return self.start(p, anchor)
        a = self.current
        b = self.add_point(p)
        if a == b:
            return b
        if (a, b) not in self.lines and (b, a) not in self.lines:
            self.lines.append((a, b))
        self.current = b
        if anchor is not None:
            self.set_anchor(b, anchor)
        return b

    def line_along(self, direction, length):
        if self.current is None:
            self.start(V(0, 0, 0))
        d = V(direction)
        d.normalize()
        return self.line_to(self.pts[self.current] + d * length)

    def set_anchor(self, i, anchor):
        obj, sub = anchor
        for k, j in enumerate(self.anchor_pts):
            if j == i:
                self.anchors[k] = (obj, [sub])
                return
        self.anchors.append((obj, [sub]))
        self.anchor_pts.append(i)

    def stop(self):
        self.current = None

    # -- editing
    def _downstream(self, a, b):
        """Points on b's side of line a-b (b included)."""
        adj = {}
        for x, y in self.lines:
            adj.setdefault(x, set()).add(y)
            adj.setdefault(y, set()).add(x)
        seen = {a, b}
        todo = [b]
        out = [b]
        while todo:
            k = todo.pop()
            for n in adj.get(k, ()):
                if n not in seen:
                    seen.add(n)
                    out.append(n)
                    todo.append(n)
        return out

    def _oriented(self, k):
        """Line k as (from, to): from is the end nearer the first point."""
        a, b = self.lines[k]
        dist = self._depths()
        if dist.get(b, 0) < dist.get(a, 0):
            a, b = b, a
        return a, b

    def _depths(self):
        adj = {}
        for x, y in self.lines:
            adj.setdefault(x, set()).add(y)
            adj.setdefault(y, set()).add(x)
        depth = {}
        for root in range(len(self.pts)):
            if root in depth:
                continue
            depth[root] = 0
            todo = [root]
            while todo:
                k = todo.pop(0)
                for n in adj.get(k, ()):
                    if n not in depth:
                        depth[n] = depth[k] + 1
                        todo.append(n)
        return depth

    def line_info(self, k):
        a, b = self._oriented(k)
        d = self.pts[b] - self.pts[a]
        return a, b, d.Length, direction_name(d)

    def set_length(self, k, length):
        a, b = self._oriented(k)
        d = self.pts[b] - self.pts[a]
        if d.Length < TOL or length <= 0:
            return
        shift = d * (length / d.Length - 1.0)
        for i in self._downstream(a, b):
            self.pts[i] = self.pts[i] + shift

    def set_direction(self, k, name):
        a, b = self._oriented(k)
        d = self.pts[b] - self.pts[a]
        new = AXES[name] * d.Length
        shift = new - d
        for i in self._downstream(a, b):
            self.pts[i] = self.pts[i] + shift

    def delete_line(self, k):
        a, b = self.lines.pop(k)
        self._drop_lonely()

    def _drop_lonely(self):
        used = {i for ab in self.lines for i in ab}
        if not self.lines:
            keep = [0] if self.pts else []
        else:
            keep = sorted(used)
        remap = {old: new for new, old in enumerate(keep)}
        self.pts = [self.pts[i] for i in keep]
        self.lines = [(remap[a], remap[b]) for a, b in self.lines]
        anchors, apts = [], []
        for an, i in zip(self.anchors, self.anchor_pts):
            if i in remap:
                anchors.append(an)
                apts.append(remap[i])
        self.anchors, self.anchor_pts = anchors, apts
        if self.current is not None:
            self.current = remap.get(self.current)

    def undo_last(self):
        if self.lines:
            self.delete_line(len(self.lines) - 1)
            self.current = self.lines[-1][1] if self.lines else (0 if self.pts else None)
        elif self.pts:
            self.pts, self.anchors, self.anchor_pts, self.current = [], [], [], None


def direction_name(d):
    if d.Length < TOL:
        return "-"
    u = V(d)
    u.normalize()
    for name, a in AXES.items():
        if u.dot(a) > 1 - 1e-6:
            return name
    return f"({u.x:.2f}, {u.y:.2f}, {u.z:.2f})"


def snap_axis(cur, q, normal=None):
    """q moved onto the X, Y or Z line through cur nearest to it (in the
    drawing plane when a normal is given)."""
    d = q - cur
    best, comp = None, 0.0
    for a in (V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)):
        if normal is not None and abs(a.dot(normal)) > 0.5:
            continue
        c = d.dot(a)
        if best is None or abs(c) > abs(comp):
            best, comp = a, c
    return cur + best * comp


def round_to(q, cur, step):
    """Length from cur rounded to step (mm)."""
    d = q - cur
    if d.Length < TOL or step <= 0:
        return q
    L = max(step, round(d.Length / step) * step)
    return cur + d * (L / d.Length)


# ------------------------------------------------------------ the panel

class _EnterFilter(QtCore.QObject):
    """Enter in a number box applies the number (and runs on_enter) instead of
    falling through to the task panel's OK button and closing it."""
    def __init__(self, w, on_enter=None):
        super().__init__(w)
        self.on_enter = on_enter

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and ev.key() in (QtCore.Qt.Key_Return,
                                                                 QtCore.Qt.Key_Enter):
            try:
                obj.interpretText()
            except Exception:
                pass
            if self.on_enter:
                QtCore.QTimer.singleShot(0, self.on_enter)
            return True
        return False


def keep_enter(w, on_enter=None):
    """Stop Enter in w closing the task panel (see _EnterFilter)."""
    f = _EnterFilter(w, on_enter)
    w.installEventFilter(f)
    w._mf_enter = f
    return w


class Sketch3DPanel:
    def __init__(self, sketch=None):
        from mechflow_gui import toolbox
        self.new = sketch is None
        self.doc = sketch.Document if sketch else App.ActiveDocument
        self.doc.openTransaction("3D Sketch")
        if sketch is None:
            sketch = make(toolbox.active_container())
            self.doc.recompute()
        self.sketch = sketch
        self.ed = Editor(sketch)
        if self.ed.pts:
            self.ed.current = None           # click a point to carry on from it
        self.plane = "Auto"
        self.hover = None                    # (local point, anchor or None, sketch point index)
        self.form = self._build()
        self._scene = None
        self._cbs = []
        self._labels = []
        self._install()
        self._refresh()

    # -- UI
    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("3D Sketch")
        lay = QtWidgets.QVBoxLayout(w)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Plane"))
        self.planes = QtWidgets.QButtonGroup(w)
        for i, p in enumerate(PLANES):
            b = QtWidgets.QRadioButton(p)
            b.setChecked(p == "Auto")
            self.planes.addButton(b, i)
            row.addWidget(b)
        self.planes.idClicked.connect(lambda i: self._set_plane(PLANES[i]))
        lay.addLayout(row)
        self.ortho = QtWidgets.QCheckBox("Along X / Y / Z only")
        self.ortho.setChecked(True)
        lay.addWidget(self.ortho)
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("Round lengths to"))
        self.step = QtWidgets.QDoubleSpinBox()
        self.step.setRange(0, 1000)
        self.step.setDecimals(0)
        self.step.setValue(10)
        self.step.setSuffix(" mm")
        row2.addWidget(self.step)
        lay.addLayout(row2)
        box = QtWidgets.QGroupBox("Add a line by typing")
        bl = QtWidgets.QHBoxLayout(box)
        self.dir = QtWidgets.QComboBox()
        self.dir.addItems(list(AXES))
        self.dir.setCurrentText("+Z")
        bl.addWidget(self.dir)
        self.len = QtWidgets.QDoubleSpinBox()
        self.len.setRange(1, 1e6)
        self.len.setDecimals(1)
        self.len.setValue(500)
        self.len.setSuffix(" mm")
        keep_enter(self.len, self._add_typed)
        keep_enter(self.step)
        bl.addWidget(self.len, 1)
        add = QtWidgets.QPushButton("Add")
        add.clicked.connect(self._add_typed)
        bl.addWidget(add)
        lay.addWidget(box)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Line", "Direction", "Length (mm)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setMinimumHeight(160)
        lay.addWidget(self.table, 1)
        row3 = QtWidgets.QHBoxLayout()
        undo = QtWidgets.QPushButton("Undo last line")
        undo.clicked.connect(self._undo)
        row3.addWidget(undo)
        dele = QtWidgets.QPushButton("Delete line")
        dele.clicked.connect(self._delete)
        row3.addWidget(dele)
        stop = QtWidgets.QPushButton("End chain (Esc)")
        stop.clicked.connect(self._stop)
        row3.addWidget(stop)
        lay.addLayout(row3)
        self.status = QtWidgets.QLabel()
        self.status.setStyleSheet("color: #555;")
        lay.addWidget(self.status)
        return w

    def _set_plane(self, p):
        self.plane = p
        for b in self.planes.buttons():
            b.setChecked(b.text() == p)
        self._refresh_msg()

    def _refresh_msg(self):
        if self.ed.current is None and not self.ed.pts:
            first = ("<b>Click where the route starts</b> - a flange face or nozzle edge "
                     "(it snaps to the centre), or anywhere in the view.")
        elif self.ed.current is None:
            first = ("<b>Click a point of the sketch</b> to carry on or branch from it, "
                     "or a flange edge to start a new run.")
        else:
            first = "<b>Click to place the next point.</b> Esc ends the chain."
        self.msg.setText(first + f"<br>Drawing plane: <b>{self._plane_name()}</b> "
                         "(Tab to change; Auto faces the screen - turn the view to draw "
                         "up or across).")

    def _plane_name(self):
        if self.plane != "Auto":
            return self.plane
        n = self._normal()
        return {0: "YZ", 1: "ZX", 2: "XY"}[max(range(3), key=lambda i: abs(n[i]))] + " (Auto)"

    def _normal(self):
        if self.plane != "Auto":
            return NORMALS[self.plane]
        try:
            d = Gui.ActiveDocument.ActiveView.getViewDirection()
        except Exception:
            return V(0, 0, 1)
        i = max(range(3), key=lambda k: abs(d[k]))
        return [V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)][i]

    def _refresh(self):
        ed = self.ed
        self.table.blockSignals(True)
        self.table.setRowCount(len(ed.lines))
        for k in range(len(ed.lines)):
            a, b, L, dname = ed.line_info(k)
            it = QtWidgets.QTableWidgetItem(f"{k + 1}")
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(k, 0, it)
            combo = QtWidgets.QComboBox()
            items = list(AXES)
            if dname not in AXES:
                items = [dname] + items
            combo.addItems(items)
            combo.setCurrentText(dname)
            combo.currentTextChanged.connect(lambda t, k=k: self._dir_edited(k, t))
            self.table.setCellWidget(k, 1, combo)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(1, 1e6)
            spin.setDecimals(1)
            spin.setValue(L)
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda v, k=k: self._len_edited(k, v))
            keep_enter(spin)
            self.table.setCellWidget(k, 2, spin)
        self.table.blockSignals(False)
        ed.save()
        self._refresh_msg()
        self._show_labels()
        total = sum(ed.line_info(k)[2] for k in range(len(ed.lines)))
        self.status.setText(f"{len(ed.lines)} line{'s' if len(ed.lines) != 1 else ''}, "
                            f"{total:,.0f} mm")

    def _dir_edited(self, k, t):
        if t in AXES:
            self.ed.set_direction(k, t)
            self._refresh()

    def _len_edited(self, k, v):
        self.ed.set_length(k, v)
        self._refresh()

    def _add_typed(self):
        self.ed.line_along(AXES[self.dir.currentText()], self.len.value())
        self._refresh()

    def _undo(self):
        self.ed.undo_last()
        self._refresh()

    def _delete(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.ed.lines:
            rows = [len(self.ed.lines) - 1]
        for r in rows:
            self.ed.delete_line(r)
        self._refresh()

    def _stop(self):
        self.ed.stop()
        self._clear_preview()
        self._refresh_msg()

    # -- the 3D view
    def _install(self):
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            return
        self.view = view
        self._cbs = [
            (coin.SoLocation2Event.getClassTypeId(),
             view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(), self._on_move)),
            (coin.SoMouseButtonEvent.getClassTypeId(),
             view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), self._on_click)),
            (coin.SoKeyboardEvent.getClassTypeId(),
             view.addEventCallbackPivy(coin.SoKeyboardEvent.getClassTypeId(), self._on_key)),
        ]
        root = coin.SoSeparator()
        from mechflow_gui import view_handles
        view_handles._on_top(root)
        col = coin.SoBaseColor()
        col.rgb = (0.0, 0.45, 0.85)
        root.addChild(col)
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        style.linePattern = 0xF0F0
        style.pointSize = 9
        root.addChild(style)
        self._coords = coin.SoCoordinate3()
        root.addChild(self._coords)
        self._line = coin.SoLineSet()
        self._line.numVertices.setValue(0)
        root.addChild(self._line)
        self._dot = coin.SoPointSet()
        self._dot.numPoints.setValue(0)
        root.addChild(self._dot)
        self._text_root = coin.SoSeparator()
        root.addChild(self._text_root)
        self._scene = view.getSceneGraph()
        self._scene.addChild(root)
        self._root = root
        from mechflow_gui import view_handles as vh
        self._box = vh.ViewBox(" mm", 0, 1e6, 0)

    def _uninstall(self):
        for t, cb in self._cbs:
            try:
                self.view.removeEventCallbackPivy(t, cb)
            except Exception:
                pass
        self._cbs = []
        try:
            if self._scene is not None:
                self._scene.removeChild(self._root)
        except Exception:
            pass
        try:
            self._box.remove()
        except Exception:
            pass

    def _clear_preview(self):
        try:
            self._line.numVertices.setValue(0)
            self._dot.numPoints.setValue(0)
            self._box.hide()
        except Exception:
            pass

    def _show_labels(self):
        """Each line's length at its middle."""
        try:
            from pivy import coin
        except Exception:
            return
        if getattr(self, "_text_root", None) is None:
            return
        self._text_root.removeAllChildren()
        col = coin.SoBaseColor()
        col.rgb = (0.1, 0.1, 0.1)
        self._text_root.addChild(col)
        font = coin.SoFont()
        font.size = 14
        self._text_root.addChild(font)
        for k in range(len(self.ed.lines)):
            a, b, L, _d = self.ed.line_info(k)
            m = to_global(self.sketch, (self.ed.pts[a] + self.ed.pts[b]) * 0.5)
            sep = coin.SoSeparator()
            tr = coin.SoTranslation()
            tr.translation = (m.x, m.y, m.z)
            sep.addChild(tr)
            tx = coin.SoText2()
            tx.string = f"{L:.0f}"
            sep.addChild(tx)
            self._text_root.addChild(sep)

    def _pick(self, pos):
        """What's under the mouse: (global point, anchor, sketch point idx)."""
        try:
            info = self.view.getObjectInfo((int(pos[0]), int(pos[1])))
        except Exception:
            info = None
        if not info:
            return None
        doc = App.getDocument(info["Document"]) if info.get("Document") else self.doc
        obj = doc.getObject(info["Object"]) if doc else None
        sub = info.get("Component", "") or ""
        if obj is None:
            return None
        if obj is self.sketch and sub.startswith("Vertex"):
            try:
                p = obj.Shape.getElement(sub).Point
                gi = self.ed.find_point(V(p), 0.05)
                return to_global(self.sketch, p), None, gi
            except Exception:
                return None
        if obj is self.sketch:
            return None
        full = info.get("SubName") or sub
        for s in (full, sub):
            if not s or "Edge" not in s.rsplit(".", 1)[-1]:
                continue
            f = circle_frame(obj, s)
            if f is not None:
                return f[0], (obj, s), None
        return None

    def _ray_point(self, pos):
        """The mouse on the drawing plane through the current point."""
        view = self.view
        p = V(view.getPoint(int(pos[0]), int(pos[1])))
        d = V(view.getViewDirection())
        n = self._normal()
        base = to_global(self.sketch, self.ed.pts[self.ed.current]) \
            if self.ed.current is not None else V(0, 0, 0)
        den = d.dot(n)
        if abs(den) < 1e-9:
            return None
        t = (base - p).dot(n) / den
        return p + d * t

    def _candidate(self, pos):
        """(local point, anchor, sketch point idx) a click here would add."""
        hit = self._pick(pos)
        if hit is not None:
            g, anchor, idx = hit
            return to_local(self.sketch, g), anchor, idx
        g = self._ray_point(pos)
        if g is None:
            return None
        q = to_local(self.sketch, g)
        if self.ed.current is not None:
            cur = self.ed.pts[self.ed.current]
            n = self._normal()
            if self.ortho.isChecked():
                q = snap_axis(cur, q, n)
            q = round_to(q, cur, self.step.value())
        return q, None, None

    def _on_move(self, cb):
        try:
            ev = cb.getEvent()
            c = self._candidate(ev.getPosition().getValue())
            self.hover = c
            if c is None:
                self._clear_preview()
                return
            q = to_global(self.sketch, c[0])
            if self.ed.current is not None:
                a = to_global(self.sketch, self.ed.pts[self.ed.current])
                self._coords.point.setValues(0, 2, [(a.x, a.y, a.z), (q.x, q.y, q.z)])
                self._line.numVertices.setValue(2)
                self._dot.numPoints.setValue(0)
                L = (c[0] - self.ed.pts[self.ed.current]).Length
                self._box.set_quiet(round(L))
                self._box.place((a + q) * 0.5)
            else:
                self._coords.point.setValues(0, 1, [(q.x, q.y, q.z)])
                self._line.numVertices.setValue(0)
                self._dot.numPoints.setValue(1)
                self._box.hide()
        except Exception:
            pass

    def _on_click(self, cb):
        try:
            from pivy import coin
            ev = cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
                return
            if ev.getState() != coin.SoButtonEvent.DOWN:
                cb.setHandled()
                return
            c = self._candidate(ev.getPosition().getValue())
            if c is None:
                return
            cb.setHandled()
            self.click(*c)
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow 3D Sketch: {e}\n")

    def click(self, q, anchor=None, idx=None):
        """Add the point a click gives (also used by tests)."""
        ed = self.ed
        if ed.current is None:
            if idx is not None:
                ed.current = idx                 # carry on / branch from a sketch point
            else:
                ed.start(q, anchor)
        else:
            if idx is not None:
                q = ed.pts[idx]
            if (q - ed.pts[ed.current]).Length < 0.5:
                return
            ed.line_to(q, anchor)
            if anchor is not None:
                ed.stop()                        # ended on a flange: that run is done
        self._clear_preview()
        self._refresh()

    def _on_key(self, cb):
        try:
            from pivy import coin
            ev = cb.getEvent()
            if ev.getState() != coin.SoButtonEvent.DOWN:
                return
            k = ev.getKey()
            if k == coin.SoKeyboardEvent.TAB:
                i = PLANES.index(self.plane)
                self._set_plane(PLANES[(i + 1) % len(PLANES)])
                cb.setHandled()
            elif k == coin.SoKeyboardEvent.ESCAPE:
                if self.ed.current is not None:
                    self._stop()
                    cb.setHandled()
        except Exception:
            pass

    # -- finish
    def accept(self):
        self._uninstall()
        self.ed.save()
        if not self.ed.lines:
            if self.new:
                self.doc.abortTransaction()
                self.doc.recompute()
                Gui.Control.closeDialog()
                return True
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._uninstall()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def sketch_3d():
    """3D Sketch command: a new one, or edit the selected one."""
    if App.ActiveDocument is None:
        App.newDocument()
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "3D Sketch",
                                          "Finish the open dialog first.")
        return None
    sel = [s for s in Gui.Selection.getSelection() if is_sketch3d(s)]
    Gui.Selection.clearSelection()
    p = Sketch3DPanel(sel[0] if sel else None)
    Gui.Control.showDialog(p)
    return p
