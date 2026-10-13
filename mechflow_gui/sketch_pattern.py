# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Circular Sketch Pattern.

A small panel in the sketch (like SOLIDWORKS' PropertyManager): the entities
to pattern, the centre (the sketch origin unless you pick a point), the
number of instances, the angle (360 deg with Equal spacing) and Reverse
direction. The copies preview live; OK keeps them, constrained so the
pattern holds: the copies are Equal to the originals and sit on construction
lines from the centre, equal in length and at equal angles.
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


def _kind(sk, g):
    return relations._geo_kind(sk, g)


def _ref_point(sk, g):
    """(pos, point) used to place an instance: centre of a circle/arc,
    start of a line, the point itself."""
    k = _kind(sk, g)
    if k in (relations.CIRCLE, relations.ARC):
        return 3, sk.getPoint(g, 3)
    if k == relations.POINT:
        return 1, sk.getPoint(g, 1)
    return 1, sk.getPoint(g, 1)


class CircularPatternPanel(QtWidgets.QFrame):
    def __init__(self, parent, sk):
        super().__init__(parent)
        self.sk = sk
        self.seeds = []            # geo ids to pattern
        self.centre = ORIGIN       # (geo, pos)
        self.added = []            # preview geo ids
        self.picking_centre = False
        self._last_key = None
        self._build()
        # One undo step for the whole pattern (preview included).
        sk.Document.openTransaction("Circular Sketch Pattern")
        self._take(initial=True)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._update()

    # ---- UI
    def _build(self):
        self.setObjectName("MechFlow_CirPattern")
        self.setStyleSheet(
            "#MechFlow_CirPattern { background: rgba(250,250,250,245);"
            " border: 1px solid #b8b8b8; border-radius: 4px; }"
            "#MechFlow_CirPattern QLabel#title { font-weight: 700; }")
        self.setFixedWidth(250)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(5)
        head = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(QtGui.QIcon(":/icons/sketcher_rotate.svg").pixmap(18, 18)
                       if QtCore.QFile.exists(":/icons/sketcher_rotate.svg") else QtGui.QPixmap())
        head.addWidget(icon)
        t = QtWidgets.QLabel("Circular Pattern")
        t.setObjectName("title")
        head.addWidget(t, 1)
        ok = QtWidgets.QToolButton()
        ok.setText("✔")
        ok.setToolTip("OK")
        ok.setStyleSheet("color: #1a8f1a; font-size: 15px; font-weight: 700;")
        ok.clicked.connect(self.accept)
        cancel = QtWidgets.QToolButton()
        cancel.setText("✖")
        cancel.setToolTip("Cancel")
        cancel.setStyleSheet("color: #c62828; font-size: 15px; font-weight: 700;")
        cancel.clicked.connect(self.reject)
        head.addWidget(ok)
        head.addWidget(cancel)
        lay.addLayout(head)

        lay.addWidget(QtWidgets.QLabel("<b>Parameters</b>"))
        crow = QtWidgets.QHBoxLayout()
        crow.addWidget(QtWidgets.QLabel("Centre"))
        self.centre_lbl = QtWidgets.QLabel("Origin")
        self.centre_lbl.setStyleSheet("background: #e8f0fb; border: 1px solid #9db8e0;"
                                      " padding: 1px 4px;")
        crow.addWidget(self.centre_lbl, 1)
        self.pick_btn = QtWidgets.QPushButton("Pick")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setToolTip("Click a point in the sketch to use as the centre")
        self.pick_btn.toggled.connect(self._pick_toggled)
        crow.addWidget(self.pick_btn)
        lay.addLayout(crow)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0.1, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix(" °")
        self.angle.setValue(360.0)
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(2, 500)
        self.count.setValue(4)
        self.count.setToolTip("Number of instances, including the original")
        self.equal = QtWidgets.QCheckBox("Equal spacing")
        self.equal.setChecked(True)
        self.equal.setToolTip("On: the angle is the total angle, shared out equally.\n"
                              "Off: the angle is between instances.")
        form.addRow("Angle", self.angle)
        form.addRow("Instances", self.count)
        form.addRow("", self.equal)
        form.addRow("", self.reverse)
        lay.addLayout(form)
        for w in (self.angle, self.count):
            w.valueChanged.connect(self._update)
        for w in (self.equal, self.reverse):
            w.toggled.connect(self._update)

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

    # ---- selection
    def _pick_toggled(self, on):
        self.picking_centre = on
        self.msg.setText("Click a point (or a circle/arc for its centre) for the centre."
                         if on else "")

    def _take(self, initial=False):
        items = relations.selected_items(self.sk)
        if not items:
            return
        Gui.Selection.clearSelection()
        mine = set(self.added)
        for kind, g, pos in items:
            if g in mine:
                continue
            if self.picking_centre:
                if kind == "point":
                    self.centre = (g, pos)
                elif g >= 0 and _kind(self.sk, g) in (relations.CIRCLE, relations.ARC):
                    self.centre = (g, 3)
                else:
                    continue
                self.pick_btn.setChecked(False)
                continue
            if kind == "point":
                if initial and g < 0 or (initial and _kind(self.sk, g) != relations.POINT):
                    # a point picked with the entities: the centre
                    self.centre = (g, pos)
                    continue
                if _kind(self.sk, g) == relations.POINT and g not in self.seeds:
                    self.seeds.append(g)
                continue
            if g < 0:
                continue
            if g in self.seeds:
                self.seeds.remove(g)        # click again to remove, like SOLIDWORKS
            else:
                self.seeds.append(g)
        self._refresh_list()
        self._update()

    def _refresh_list(self):
        self.list.clear()
        for g in self.seeds:
            self.list.addItem(relations._geo_name(self.sk, g))
        self.centre_lbl.setText(relations._point_name(self.sk, *self.centre))

    def _clear(self):
        self.seeds = []
        self._refresh_list()
        self._update()

    def _poll(self):
        if sketch_status.sketch_in_edit() is not self.sk:
            self._close(keep=False)
            return
        try:
            self._take()
        except Exception as e:
            App.Console.PrintLog(f"MechFlow circular pattern: {e}\n")

    # ---- geometry
    def step(self):
        n = self.count.value()
        a = self.angle.value()
        if self.equal.isChecked():
            st = a / n if abs(a - 360.0) < 1e-9 else a / max(1, n - 1)
        else:
            st = a
        return -st if self.reverse.isChecked() else st

    def _centre_point(self):
        g, pos = self.centre
        try:
            return self.sk.getPoint(g, pos)
        except Exception:
            return App.Vector(0, 0, 0)

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
        key = (tuple(self.seeds), self.centre, self.count.value(), self.angle.value(),
               self.equal.isChecked(), self.reverse.isChecked())
        if key == self._last_key:
            return
        self._last_key = key
        self._remove_preview()
        self._refresh_list()
        if not self.seeds:
            self.msg.setText("Select the sketch entities to pattern. The centre is the "
                             "origin unless you pick a point.")
            self._redraw()
            return
        c = self._centre_point()
        st = self.step()
        geos, cons = [], []
        for k in range(1, self.count.value()):
            pl = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), st * k), c)
            for g in self.seeds:
                geo = self.sk.Geometry[g].copy()
                geo.transform(pl.toMatrix())
                geos.append(geo)
                cons.append(self.sk.getConstruction(g))
        first = len(self.sk.Geometry)
        for geo, con in zip(geos, cons):
            self.sk.addGeometry(geo, con)
        self.added = list(range(first, len(self.sk.Geometry)))
        self.msg.setText(f"{self.count.value()} instances, {abs(st):g}° apart. "
                         "Click entities to add or remove them.")
        self._redraw()

    def _redraw(self):
        try:
            self.sk.solve()
            self.sk.recompute()
        except Exception:
            pass

    # ---- constraints
    def _constrain(self):
        sk = self.sk
        n = self.count.value()
        m = len(self.seeds)
        if not self.added or m == 0:
            return
        C = Sketcher.Constraint
        cons = []
        inst = lambda k, j: self.added[(k - 1) * m + j]   # k = 1..n-1
        for k in range(1, n):
            for j, g in enumerate(self.seeds):
                if _kind(sk, g) in (relations.CIRCLE, relations.ARC, relations.LINE):
                    cons.append(C("Equal", g, inst(k, j)))
        # Construction lines from the centre to each instance's reference point.
        seed = self.seeds[0]
        pos, _p = _ref_point(sk, seed)
        c = self._centre_point()
        refs = [seed] + [inst(k, 0) for k in range(1, n)]
        lines = []
        for g in refs:
            p = sk.getPoint(g, pos)
            if (p - c).Length < 1e-6:
                return self._add(cons)       # instance on the centre: nothing to place
            lines.append(sk.addGeometry(Part_line(c, p), True))
        cg, cp = self.centre
        st = abs(self.step())
        for i, ln in enumerate(lines):
            cons.append(C("Coincident", ln, 1, cg, cp))
            cons.append(C("Coincident", ln, 2, refs[i], pos))
            if i:
                cons.append(C("Equal", lines[0], ln))
        self._add(cons)
        # Angles one by one, keeping the geometry where it is.
        for i in range(1, len(lines)):
            a, b = lines[i - 1], lines[i]
            if self.reverse.isChecked():
                a, b = b, a
            try:
                idx = sk.addConstraint(C("Angle", a, 1, b, 1, math.radians(st)))
            except Exception:
                continue
            p_before = sk.getPoint(lines[i], 2)
            sk.solve()
            if (sk.getPoint(lines[i], 2) - p_before).Length > 1e-4:
                sk.setDatum(idx, App.Units.Quantity(f"{-st} deg"))
                sk.solve()

    def _add(self, cons):
        if cons:
            self.sk.addConstraint(cons)

    # ---- finish
    def accept(self):
        if not self.added:
            self.msg.setText("Select entities to pattern first.")
            return
        doc = self.sk.Document
        try:
            self._constrain()
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow circular pattern: {e}\n")
        doc.commitTransaction()
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


def Part_line(a, b):
    import Part
    return Part.LineSegment(a, b)


_panel = None


def circular_sketch_pattern():
    global _panel
    sk = sketch_status.sketch_in_edit()
    if sk is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Circular Sketch Pattern",
                                          "Open a sketch first.")
        return None
    if _panel is not None:
        try:
            _panel.reject()
        except Exception:
            pass
    area = relations._mdi()
    relations.suspended = True
    try:
        if relations._panel is not None:
            relations._panel.hide()
    except Exception:
        pass
    _panel = CircularPatternPanel(area, sk)
    _panel.move(10, 56)
    _panel.show()
    _panel.raise_()
    return _panel
