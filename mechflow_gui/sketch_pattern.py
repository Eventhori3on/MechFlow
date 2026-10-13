# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Linear and Circular Sketch Patterns.

Both open the same kind of panel in the sketch (like SOLIDWORKS'
PropertyManager), at the top left of the view:

- Linear: Direction 1 (angle, spacing, instances, reverse) and an optional
  Direction 2 for a grid. A direction can be taken from a sketch line.
- Circular: centre (the origin unless you pick a point), angle, instances,
  equal spacing, reverse.

Entities to Pattern: whatever was selected, plus anything you click while
the panel is open (click again to remove). The copies preview live; OK keeps
them, constrained so the pattern holds when the original changes: copies are
Equal to the originals and placed by construction lines (equal length and
angle). One undo removes the whole pattern.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

import Sketcher

from mechflow_gui import relations, sketch_status

ORIGIN = (-1, 1)
C = Sketcher.Constraint


def _kind(sk, g):
    return relations._geo_kind(sk, g)


def _ref_pos(sk, g):
    """Which point of an entity places its instance: a circle/arc centre,
    otherwise the start point."""
    return 3 if _kind(sk, g) in (relations.CIRCLE, relations.ARC) else 1


def _icon(name):
    for path in (f":/icons/{name}.svg", f":/icons/{name.lower()}.svg",
                 f":/icons/geometry/{name}.svg", f":/icons/tools/{name}.svg"):
        if QtCore.QFile.exists(path):
            return QtGui.QIcon(path)
    try:
        return QtGui.QIcon(Gui.getIcon(name))
    except Exception:
        return QtGui.QIcon()


def _line(a, b):
    import Part
    return Part.LineSegment(a, b)


def _spin(lo, hi, val, suffix="", decimals=2):
    w = QtWidgets.QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(decimals)
    w.setSuffix(suffix)
    w.setValue(val)
    w.setKeyboardTracking(False)
    return w


def _count(val):
    w = QtWidgets.QSpinBox()
    w.setRange(1, 500)
    w.setValue(val)
    w.setKeyboardTracking(False)
    w.setToolTip("Number of instances, including the original")
    return w


class PatternPanel(QtWidgets.QFrame):
    """Shared panel: title with OK/Cancel, parameters (subclass), Entities to
    Pattern, live preview, one undo step."""

    TITLE = "Pattern"
    ICON = ""
    UNDO = "Sketch Pattern"

    def __init__(self, parent, sk):
        super().__init__(parent)
        self.sk = sk
        self.seeds = []
        self.added = []
        self.picking = None          # callback taking (kind, g, pos) -> bool
        self._last_key = None
        self._build()
        sk.Document.openTransaction(self.UNDO)
        self._take(initial=True)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._update()

    # ---- UI
    def _build(self):
        self.setObjectName("MechFlow_SkPattern")
        self.setStyleSheet(
            "#MechFlow_SkPattern { background: rgba(250,250,250,245);"
            " border: 1px solid #b8b8b8; border-radius: 4px; }"
            "#MechFlow_SkPattern QLabel#title { font-weight: 700; }"
            "#MechFlow_SkPattern QLabel.field { background: #e8f0fb;"
            " border: 1px solid #9db8e0; padding: 1px 4px; }")
        self.setFixedWidth(260)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(5)
        head = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(_icon(self.ICON).pixmap(18, 18))
        head.addWidget(icon)
        t = QtWidgets.QLabel(self.TITLE)
        t.setObjectName("title")
        head.addWidget(t, 1)
        for text, tip, colour, fn in (("✔", "OK", "#1a8f1a", self.accept),
                                      ("✖", "Cancel", "#c62828", self.reject)):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setStyleSheet(f"color: {colour}; font-size: 15px; font-weight: 700;")
            b.clicked.connect(fn)
            head.addWidget(b)
        lay.addLayout(head)
        self._build_params(lay)
        lay.addWidget(QtWidgets.QLabel("<b>Entities to Pattern</b>"))
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(90)
        lay.addWidget(self.list)
        clr = QtWidgets.QPushButton("Clear")
        clr.clicked.connect(self._clear)
        lay.addWidget(clr)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: #666;")
        lay.addWidget(self.msg)

    def _build_params(self, lay):
        pass

    def _field(self, text):
        lbl = QtWidgets.QLabel(text)
        lbl.setProperty("class", "field")
        lbl.setStyleSheet("background: #e8f0fb; border: 1px solid #9db8e0; padding: 1px 4px;")
        return lbl

    def _watch(self, *widgets):
        for w in widgets:
            if isinstance(w, QtWidgets.QAbstractButton):
                w.toggled.connect(self._update)
            else:
                w.valueChanged.connect(self._update)

    # ---- selection
    def _take(self, initial=False):
        items = relations.selected_items(self.sk)
        if not items:
            return
        Gui.Selection.clearSelection()
        mine = set(self.added)
        for kind, g, pos in items:
            if g in mine:
                continue
            if self.picking is not None:
                if self.picking(kind, g, pos):
                    self.picking = None
                continue
            if self._take_extra(kind, g, pos, initial):
                continue
            if g < 0:
                continue
            if kind == "point" and _kind(self.sk, g) != relations.POINT:
                continue
            if g in self.seeds:
                self.seeds.remove(g)        # click again to remove, like SOLIDWORKS
            else:
                self.seeds.append(g)
        self._refresh()
        self._update()

    def _take_extra(self, kind, g, pos, initial):
        return False

    def _refresh(self):
        self.list.clear()
        for g in self.seeds:
            self.list.addItem(relations._geo_name(self.sk, g))

    def _clear(self):
        self.seeds = []
        self._refresh()
        self._update()

    def _poll(self):
        if sketch_status.sketch_in_edit() is not self.sk:
            self._close(keep=False)
            return
        try:
            self._take()
        except Exception as e:
            App.Console.PrintLog(f"MechFlow sketch pattern: {e}\n")

    # ---- geometry
    def placements(self):
        """[(instance key, Placement)] for every copy (not the original)."""
        return []

    def _key(self):
        return ()

    def _remove_preview(self):
        if self.added:
            try:
                self.sk.delGeometries(sorted(self.added))
            except Exception:
                for g in sorted(self.added, reverse=True):
                    try:
                        self.sk.delGeometry(g)
                    except Exception:
                        pass
            self.added = []

    def _update(self, *_):
        key = (tuple(self.seeds),) + self._key()
        if key == self._last_key:
            return
        self._last_key = key
        self._remove_preview()
        self._refresh()
        if not self.seeds:
            self.msg.setText("Select the sketch entities to pattern.")
            self._redraw()
            return
        self.instances = self.placements()
        first = len(self.sk.Geometry)
        for _k, pl in self.instances:
            for g in self.seeds:
                geo = self.sk.Geometry[g].copy()
                geo.transform(pl.toMatrix())
                self.sk.addGeometry(geo, self.sk.getConstruction(g))
        self.added = list(range(first, len(self.sk.Geometry)))
        self.msg.setText(self._summary() + " Click entities to add or remove them.")
        self._redraw()

    def _summary(self):
        return ""

    def _redraw(self):
        try:
            self.sk.solve()
            self.sk.recompute()
        except Exception:
            pass

    def copy_of(self, i, j):
        """Geo id of seed j in instance i (index into self.instances)."""
        return self.added[i * len(self.seeds) + j]

    def _equal_constraints(self):
        cons = []
        for i in range(len(self.instances)):
            for j, g in enumerate(self.seeds):
                if _kind(self.sk, g) in (relations.CIRCLE, relations.ARC, relations.LINE):
                    cons.append(C("Equal", g, self.copy_of(i, j)))
        return cons

    def _constrain(self):
        pass

    # ---- finish
    def accept(self):
        if not self.added:
            self.msg.setText("Select entities to pattern first.")
            return
        try:
            self._constrain()
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow sketch pattern: {e}\n")
        self.sk.Document.commitTransaction()
        self.added = []
        self._redraw()
        self._close(keep=True)

    def reject(self):
        self._close(keep=False)

    def _close(self, keep):
        global _panel
        self._timer.stop()
        if not keep:
            try:
                self._remove_preview()
                self._redraw()
                self.sk.Document.abortTransaction()
            except Exception:
                pass
        relations.suspended = False
        _panel = None
        self.hide()
        self.deleteLater()


# ------------------------------------------------------------ circular

class CircularPatternPanel(PatternPanel):
    TITLE = "Circular Pattern"
    ICON = "Sketcher_Rotate"
    UNDO = "Circular Sketch Pattern"

    def __init__(self, parent, sk):
        self.centre = ORIGIN
        super().__init__(parent, sk)

    def _build_params(self, lay):
        lay.addWidget(QtWidgets.QLabel("<b>Parameters</b>"))
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(QtWidgets.QLabel("Centre"))
        self.centre_lbl = self._field("Origin")
        crow.addWidget(self.centre_lbl, 1)
        self.pick_btn = QtWidgets.QPushButton("Pick")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setToolTip("Click a point (or a circle/arc for its centre) for the centre")
        self.pick_btn.toggled.connect(self._pick_toggled)
        crow.addWidget(self.pick_btn)
        lay.addLayout(crow)
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.angle = _spin(0.1, 360.0, 360.0, " °")
        self.count = _count(4)
        self.count.setMinimum(2)
        self.equal = QtWidgets.QCheckBox("Equal spacing")
        self.equal.setChecked(True)
        self.equal.setToolTip("On: the angle is the total angle, shared out equally.\n"
                              "Off: the angle is between instances.")
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        form.addRow("Angle", self.angle)
        form.addRow("Instances", self.count)
        form.addRow("", self.equal)
        form.addRow("", self.reverse)
        lay.addLayout(form)
        self._watch(self.angle, self.count, self.equal, self.reverse)

    def _pick_toggled(self, on):
        self.picking = self._pick_centre if on else None
        if on:
            self.msg.setText("Click a point, or a circle/arc for its centre.")

    def _pick_centre(self, kind, g, pos):
        if kind == "point":
            self.centre = (g, pos)
        elif g >= 0 and _kind(self.sk, g) in (relations.CIRCLE, relations.ARC):
            self.centre = (g, 3)
        else:
            return False
        self.pick_btn.setChecked(False)
        return True

    def _take_extra(self, kind, g, pos, initial):
        # A point picked together with the entities is the centre.
        if initial and kind == "point" and (g < 0 or _kind(self.sk, g) != relations.POINT):
            self.centre = (g, pos)
            return True
        return False

    def _refresh(self):
        super()._refresh()
        self.centre_lbl.setText(relations._point_name(self.sk, *self.centre))

    def step(self):
        n, a = self.count.value(), self.angle.value()
        if self.equal.isChecked():
            st = a / n if abs(a - 360.0) < 1e-9 else a / max(1, n - 1)
        else:
            st = a
        return -st if self.reverse.isChecked() else st

    def _centre_point(self):
        try:
            return self.sk.getPoint(*self.centre)
        except Exception:
            return App.Vector(0, 0, 0)

    def _key(self):
        return (self.centre, self.count.value(), self.angle.value(),
                self.equal.isChecked(), self.reverse.isChecked())

    def placements(self):
        c, st = self._centre_point(), self.step()
        return [(k, App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), st * k), c))
                for k in range(1, self.count.value())]

    def _summary(self):
        return f"{self.count.value()} instances, {abs(self.step()):g}° apart."

    def _constrain(self):
        sk = self.sk
        cons = self._equal_constraints()
        seed = self.seeds[0]
        pos = _ref_pos(sk, seed)
        c = self._centre_point()
        refs = [seed] + [self.copy_of(i, 0) for i in range(len(self.instances))]
        if any((sk.getPoint(g, pos) - c).Length < 1e-6 for g in refs):
            if cons:
                sk.addConstraint(cons)      # on the centre: nothing to place
            return
        lines = [sk.addGeometry(_line(c, sk.getPoint(g, pos)), True) for g in refs]
        cg, cp = self.centre
        for i, ln in enumerate(lines):
            cons.append(C("Coincident", ln, 1, cg, cp))
            cons.append(C("Coincident", ln, 2, refs[i], pos))
            if i:
                cons.append(C("Equal", lines[0], ln))
        sk.addConstraint(cons)
        st = abs(self.step())
        for i in range(1, len(lines)):
            a, b = lines[i - 1], lines[i]
            if self.reverse.isChecked():
                a, b = b, a
            _add_keeping(sk, C("Angle", a, 1, b, 1, math.radians(st)), lines[i], st, "deg")


def _add_keeping(sk, con, moved_line, value, unit):
    """Add a constraint; if the solver flipped the geometry to satisfy it,
    use the opposite sign instead."""
    before = sk.getPoint(moved_line, 2)
    idx = sk.addConstraint(con)
    sk.solve()
    if (sk.getPoint(moved_line, 2) - before).Length > 1e-4:
        sk.setDatum(idx, App.Units.Quantity(f"{-value} {unit}"))
        sk.solve()
    return idx


# ------------------------------------------------------------ linear

class _Direction:
    def __init__(self, panel, title, angle, checkable):
        self.panel = panel
        self.box = QtWidgets.QGroupBox(title)
        self.box.setCheckable(checkable)
        if checkable:
            self.box.setChecked(False)
        f = QtWidgets.QFormLayout(self.box)
        f.setContentsMargins(6, 4, 6, 4)
        row = QtWidgets.QHBoxLayout()
        self.angle = _spin(-360.0, 360.0, angle, " °")
        self.angle.setToolTip("Direction, measured from the sketch X axis")
        row.addWidget(self.angle, 1)
        self.pick = QtWidgets.QPushButton("Pick")
        self.pick.setCheckable(True)
        self.pick.setToolTip("Click a sketch line or model edge to take its direction")
        self.pick.toggled.connect(self._pick_toggled)
        row.addWidget(self.pick)
        f.addRow("Angle", row)
        self.spacing = _spin(0.001, 100000.0, 10.0, " mm", 3)
        f.addRow("Spacing", self.spacing)
        self.count = _count(2 if not checkable else 2)
        f.addRow("Instances", self.count)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        f.addRow("", self.reverse)
        panel._watch(self.angle, self.spacing, self.count, self.reverse)
        if checkable:
            self.box.toggled.connect(panel._update)

    def on(self):
        return not self.box.isCheckable() or self.box.isChecked()

    def n(self):
        return self.count.value() if self.on() else 1

    def vector(self):
        a = math.radians(self.angle.value() + (180.0 if self.reverse.isChecked() else 0.0))
        return App.Vector(math.cos(a), math.sin(a), 0) * self.spacing.value()

    def key(self):
        return (self.on(), self.angle.value(), self.spacing.value(), self.count.value(),
                self.reverse.isChecked())

    def _pick_toggled(self, on):
        if on:
            for d in self.panel.dirs:
                if d is not self:
                    d.pick.setChecked(False)
            self.panel.picking = self._pick_line
            self.panel.msg.setText("Click a line or model edge for the direction.")
        elif self.panel.picking == self._pick_line:
            self.panel.picking = None

    def _pick_line(self, kind, g, pos):
        if kind != "edge":
            return False
        if g == -1:
            ang = 0.0
        elif g == -2:
            ang = 90.0
        else:
            try:
                geo = self.panel.sk.Geometry[g] if g >= 0 else self.panel.sk.ExternalGeo[-g - 1]
                d = geo.EndPoint - geo.StartPoint
            except Exception:
                return False
            ang = math.degrees(math.atan2(d.y, d.x))
        self.angle.setValue(round(ang, 4))
        self.pick.setChecked(False)
        return True


class LinearPatternPanel(PatternPanel):
    TITLE = "Linear Pattern"
    ICON = "Sketcher_RectangularArray"
    UNDO = "Linear Sketch Pattern"

    def _build_params(self, lay):
        self.dirs = [_Direction(self, "Direction 1", 0.0, False),
                     _Direction(self, "Direction 2", 90.0, True)]
        self.dirs[0].count.setValue(3)
        self.dirs[0].count.setMinimum(2)
        for d in self.dirs:
            lay.addWidget(d.box)

    def _key(self):
        return tuple(d.key() for d in self.dirs)

    def placements(self):
        v1, v2 = self.dirs[0].vector(), self.dirs[1].vector()
        out = []
        for j in range(self.dirs[1].n()):
            for i in range(self.dirs[0].n()):
                if i == 0 and j == 0:
                    continue
                out.append(((i, j), App.Placement(v1 * i + v2 * j, App.Rotation())))
        return out

    def _summary(self):
        n1, n2 = self.dirs[0].n(), self.dirs[1].n()
        return f"{n1 * n2} instances ({n1} x {n2})." if n2 > 1 else f"{n1} instances."

    def _constrain(self):
        sk = self.sk
        cons = self._equal_constraints()
        seed = self.seeds[0]
        pos = _ref_pos(sk, seed)
        index = {k: i for i, (k, _pl) in enumerate(self.instances)}

        def ref(k):
            return seed if k == (0, 0) else self.copy_of(index[k], 0)

        # A construction line to each instance from its neighbour: along
        # Direction 1 in each row, along Direction 2 down the first column.
        first = {1: None, 2: None}
        made = []
        for k, _pl in self.instances:
            i, j = k
            prev, d = ((i - 1, j), 1) if i > 0 else ((i, j - 1), 2)
            a, b = sk.getPoint(ref(prev), pos), sk.getPoint(ref(k), pos)
            ln = sk.addGeometry(_line(a, b), True)
            cons.append(C("Coincident", ln, 1, ref(prev), pos))
            cons.append(C("Coincident", ln, 2, ref(k), pos))
            if first[d] is None:
                first[d] = ln
                made.append((ln, d))
            else:
                cons.append(C("Equal", first[d], ln))
                cons.append(C("Parallel", first[d], ln))
        sk.addConstraint(cons)
        for ln, d in made:
            dr = self.dirs[d - 1]
            sk.addConstraint(C("Distance", ln, dr.spacing.value()))
            ang = (dr.angle.value() + (180.0 if dr.reverse.isChecked() else 0.0)) % 360.0
            if abs(ang) < 1e-9 or abs(ang - 180.0) < 1e-9:
                sk.addConstraint(C("Horizontal", ln))
            elif abs(ang - 90.0) < 1e-9 or abs(ang - 270.0) < 1e-9:
                sk.addConstraint(C("Vertical", ln))
            else:
                # Angle from the sketch X axis, as the line runs.
                a = ang - 360.0 if ang > 180.0 else ang
                _add_keeping(sk, C("Angle", ln, math.radians(a)), ln, a, "deg")
            sk.solve()


# ------------------------------------------------------------ commands

_panel = None


def _open(cls, title):
    global _panel
    sk = sketch_status.sketch_in_edit()
    if sk is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), title, "Open a sketch first.")
        return None
    if _panel is not None:
        try:
            _panel.reject()
        except Exception:
            pass
    relations.suspended = True
    try:
        if relations._panel is not None:
            relations._panel.hide()
    except Exception:
        pass
    _panel = cls(relations._mdi(), sk)
    _panel.move(10, 56)
    _panel.show()
    _panel.raise_()
    return _panel


def circular_sketch_pattern():
    return _open(CircularPatternPanel, "Circular Sketch Pattern")


def linear_sketch_pattern():
    return _open(LinearPatternPanel, "Linear Sketch Pattern")
