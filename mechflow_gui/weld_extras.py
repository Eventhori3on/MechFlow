# SPDX-License-Identifier: LGPL-2.1-or-later
"""Weldment extras, as in SOLIDWORKS: Trim/Extend, End Cap and Gusset."""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from mechflow_gui import weldments as W

V = App.Vector


def _face(obj, sub):
    import Part
    return Part.getShape(obj, sub, needSubElement=True, noElementMap=True)


def _planar(f):
    return type(getattr(f, "Surface", None)).__name__ == "Plane"


def _normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


class _ViewProvider:
    ICON = ""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path(self.ICON)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderEndCap(_ViewProvider):
    ICON = "EndCap.svg"


class ViewProviderGusset(_ViewProvider):
    ICON = "Gusset.svg"


# ------------------------------------------------------------ End cap

class EndCap:
    def __init__(self, obj, base, thickness, inset, outward=True):
        obj.addProperty("App::PropertyLinkSub", "Base", "End cap", "End face of a member")
        obj.addProperty("App::PropertyLength", "Thickness", "End cap", "Plate thickness")
        obj.addProperty("App::PropertyLength", "Inset", "End cap",
                        "How far the plate's edge is in from the member's outside")
        obj.addProperty("App::PropertyEnumeration", "Direction", "End cap",
                        "Outward: on the end. Inward: inside the end, flush")
        obj.Direction = ["Outward", "Inward"]
        obj.Base = base
        obj.Thickness = thickness
        obj.Inset = inset
        obj.Direction = "Outward" if outward else "Inward"
        obj.Proxy = self

    def execute(self, obj):
        import Part
        b = obj.Base
        f = _face(b[0], b[1][0])
        n = _normal(f)
        t = float(obj.Thickness)
        inset = float(obj.Inset)
        if obj.Direction == "Outward":
            plate = Part.Face(f.OuterWire)
            if inset > 1e-6:
                plate = Part.Face(plate.makeOffset2D(-inset, 0).Wires[0])
            obj.Shape = plate.extrude(n * t)
        else:
            inner = [w for w in f.Wires if not w.isSame(f.OuterWire)]
            if not inner:
                inner = [f.OuterWire]
            plate = Part.Face(inner[0])
            if inset > 1e-6:
                plate = Part.Face(plate.makeOffset2D(-inset, 0).Wires[0])
            obj.Shape = plate.extrude(n * -t)
        obj.Placement = App.Placement()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def wall_of(face):
    """Wall thickness of a hollow end face (0 if solid)."""
    if len(face.Wires) < 2:
        return 0.0
    ob = face.OuterWire.BoundBox
    ib = [w for w in face.Wires if not w.isSame(face.OuterWire)][0].BoundBox
    return max(0.0, (ob.DiagonalLength - ib.DiagonalLength) / (2 * math.sqrt(2)))


def make_end_cap(base, thickness=5.0, inset=None, outward=True):
    doc = base[0].Document
    f = _face(base[0], base[1][0])
    if inset is None:
        inset = round(0.5 * wall_of(f), 2)
    o = doc.addObject("Part::FeaturePython", "EndCap")
    EndCap(o, base, thickness, inset, outward)
    if App.GuiUp:
        ViewProviderEndCap(o.ViewObject)
        o.ViewObject.ShapeColor = (0.62, 0.66, 0.72)
    from mechflow_gui import toolbox
    o.Label = toolbox.instance_label(doc, f"End cap PL{thickness:g}")
    doc.recompute()
    return o


# ------------------------------------------------------------ Gusset

class Gusset:
    def __init__(self, obj, a, b, d1, d2, thickness, relief):
        obj.addProperty("App::PropertyLinkSub", "Face1", "Gusset", "First face")
        obj.addProperty("App::PropertyLinkSub", "Face2", "Gusset", "Second face")
        obj.addProperty("App::PropertyLength", "D1", "Gusset", "Leg along the first face")
        obj.addProperty("App::PropertyLength", "D2", "Gusset", "Leg along the second face")
        obj.addProperty("App::PropertyLength", "Thickness", "Gusset", "Plate thickness")
        obj.addProperty("App::PropertyLength", "Relief", "Gusset",
                        "Corner chamfer for the weld")
        obj.Face1, obj.Face2 = a, b
        obj.D1, obj.D2, obj.Thickness, obj.Relief = d1, d2, thickness, relief
        obj.Proxy = self

    def execute(self, obj):
        obj.Shape = gusset_shape(_face(obj.Face1[0], obj.Face1[1][0]),
                                 _face(obj.Face2[0], obj.Face2[1][0]),
                                 float(obj.D1), float(obj.D2), float(obj.Thickness),
                                 float(obj.Relief))
        obj.Placement = App.Placement()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def gusset_shape(f1, f2, d1, d2, thickness, relief=0.0):
    import Part
    n1, n2 = _normal(f1), _normal(f2)
    L = n1.cross(n2)
    if L.Length < 1e-6:
        raise ValueError("the faces are parallel")
    L.normalize()
    p1, p2 = f1.Vertexes[0].Point, f2.Vertexes[0].Point
    # a point on both planes: solve n1.x = n1.p1, n2.x = n2.p2, L.x = 0
    m = App.Matrix(n1.x, n1.y, n1.z, 0, n2.x, n2.y, n2.z, 0, L.x, L.y, L.z, 0, 0, 0, 0, 1)
    rhs = V(n1.dot(p1), n2.dot(p2), 0)
    c0 = m.inverse().multVec(rhs)
    # the stretch of the line both faces cover: the gusset goes in its middle
    r1 = [(v.Point - c0).dot(L) for v in f1.Vertexes]
    r2 = [(v.Point - c0).dot(L) for v in f2.Vertexes]
    lo, hi = max(min(r1), min(r2)), min(max(r1), max(r2))
    mid = (lo + hi) / 2 if hi > lo else (sum(r1) / len(r1))
    c = c0 + L * mid

    def along(f, n):
        g = f.CenterOfMass - c
        g = g - L * g.dot(L) - n * g.dot(n)
        g.normalize()
        return g
    a, b = along(f1, n1), along(f2, n2)
    if relief > 1e-6:
        pts = [c + a * relief, c + a * d1, c + b * d2, c + b * relief]
    else:
        pts = [c, c + a * d1, c + b * d2]
    pts = [q - L * (thickness / 2) for q in pts]
    face = Part.Face(Part.makePolygon(pts + [pts[0]]))
    return face.extrude(L * thickness)


def make_gusset(a, b, d1=100.0, d2=100.0, thickness=10.0, relief=10.0):
    doc = a[0].Document
    o = doc.addObject("Part::FeaturePython", "Gusset")
    Gusset(o, a, b, d1, d2, thickness, relief)
    if App.GuiUp:
        ViewProviderGusset(o.ViewObject)
        o.ViewObject.ShapeColor = (0.62, 0.66, 0.72)
    from mechflow_gui import toolbox
    o.Label = toolbox.instance_label(doc, f"Gusset PL{thickness:g}")
    doc.recompute()
    return o


def is_plate(o):
    return type(getattr(o, "Proxy", None)).__name__ in ("EndCap", "Gusset")


def plate_row(o):
    """(description, size) for the cut list."""
    t = float(o.Thickness)
    bb = o.Shape.BoundBox
    dims = sorted([bb.XLength, bb.YLength, bb.ZLength])
    if type(o.Proxy).__name__ == "Gusset":
        return f"Gusset PL{t:g}", f"{float(o.D1):g} x {float(o.D2):g}"
    return f"End cap PL{t:g}", f"{dims[2]:.0f} x {dims[1]:.0f}"


# ------------------------------------------------------------ panels

class _Panel:
    TITLE = ""

    def __init__(self):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(self.TITLE)
        self.lay = QtWidgets.QVBoxLayout(self.form)
        self.picks = []
        self._build()
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        self.lay.addWidget(self.msg)
        App.ActiveDocument.openTransaction(self.TITLE)
        self._take(Gui.Selection.getSelectionEx())
        Gui.Selection.clearSelection()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._update()

    def _poll(self):
        sel = Gui.Selection.getSelectionEx()
        if not sel:
            return
        Gui.Selection.clearSelection()
        try:
            self._take(sel)
            self._update()
        except Exception as e:
            App.Console.PrintLog(f"MechFlow {self.TITLE}: {e}\n")

    def _finish(self, ok):
        self._timer.stop()
        doc = App.ActiveDocument
        if ok:
            doc.commitTransaction()
        else:
            self._remove()
            doc.abortTransaction()
        doc.recompute()
        Gui.Control.closeDialog()
        return True

    def accept(self):
        return self._finish(True)

    def reject(self):
        return self._finish(False)


class EndCapPanel(_Panel):
    TITLE = "End Cap"

    def _build(self):
        self.made = []
        f = QtWidgets.QFormLayout()
        self.thick = QtWidgets.QDoubleSpinBox()
        self.thick.setRange(0.5, 100)
        self.thick.setValue(5)
        self.thick.setSuffix(" mm")
        f.addRow("Thickness", self.thick)
        self.inset = QtWidgets.QDoubleSpinBox()
        self.inset.setRange(-1, 100)
        self.inset.setSpecialValueText("Auto (half the wall)")
        self.inset.setValue(-1)
        self.inset.setSuffix(" mm")
        f.addRow("Inset", self.inset)
        self.dir = QtWidgets.QComboBox()
        self.dir.addItems(["Outward", "Inward"])
        f.addRow("Direction", self.dir)
        self.lay.addLayout(f)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(90)
        self.lay.addWidget(QtWidgets.QLabel("<b>End faces</b>"))
        self.lay.addWidget(self.list)
        for w in (self.thick, self.inset):
            w.valueChanged.connect(self._update)
        self.dir.currentTextChanged.connect(self._update)

    def _take(self, sel):
        for s in sel:
            for sub in s.SubElementNames:
                if not sub.startswith("Face"):
                    continue
                f = _face(s.Object, sub)
                if not _planar(f):
                    continue
                key = (s.Object, sub)
                if key in self.picks:
                    self.picks.remove(key)
                else:
                    self.picks.append(key)

    def _remove(self):
        for o in self.made:
            try:
                o.Document.removeObject(o.Name)
            except Exception:
                pass
        self.made = []

    def _update(self, *_):
        self._remove()
        self.list.clear()
        for obj, sub in self.picks:
            inset = None if self.inset.value() < 0 else self.inset.value()
            o = make_end_cap((obj, [sub]), self.thick.value(), inset,
                             self.dir.currentText() == "Outward")
            self.made.append(o)
            self.list.addItem(f"{obj.Label}: {sub}")
        self.msg.setText("Click the end faces of tubes or members to cap them."
                         if not self.picks else f"{len(self.picks)} end cap(s).")


class GussetPanel(_Panel):
    TITLE = "Gusset"

    def _build(self):
        self.made = None
        f = QtWidgets.QFormLayout()
        self.d1 = QtWidgets.QDoubleSpinBox()
        self.d2 = QtWidgets.QDoubleSpinBox()
        self.t = QtWidgets.QDoubleSpinBox()
        self.rel = QtWidgets.QDoubleSpinBox()
        for w, v, lab in ((self.d1, 100, "Leg 1 (d1)"), (self.d2, 100, "Leg 2 (d2)"),
                          (self.t, 10, "Thickness"), (self.rel, 10, "Corner relief")):
            w.setRange(0, 2000)
            w.setValue(v)
            w.setSuffix(" mm")
            f.addRow(lab, w)
            w.valueChanged.connect(self._update)
        self.lay.addLayout(f)
        self.faces = QtWidgets.QLabel()
        self.lay.addWidget(self.faces)

    def _take(self, sel):
        for s in sel:
            for sub in s.SubElementNames:
                if sub.startswith("Face") and _planar(_face(s.Object, sub)):
                    self.picks.append((s.Object, sub))
        self.picks = self.picks[-2:]

    def _remove(self):
        if self.made is not None:
            try:
                self.made.Document.removeObject(self.made.Name)
            except Exception:
                pass
            self.made = None

    def _update(self, *_):
        self._remove()
        self.faces.setText("Faces: " + ", ".join(f"{o.Label} {s}" for o, s in self.picks))
        if len(self.picks) < 2:
            self.msg.setText("Click the two faces the gusset joins (e.g. a column's side "
                             "and a beam's underside).")
            return
        try:
            a, b = self.picks
            self.made = make_gusset((a[0], [a[1]]), (b[0], [b[1]]), self.d1.value(),
                                    self.d2.value(), self.t.value(), self.rel.value())
            self.msg.setText("Gusset in the middle of where the faces meet.")
        except Exception as e:
            self.msg.setText(f"Can't make a gusset there: {e}")


class TrimPanel(_Panel):
    TITLE = "Trim/Extend"

    def _build(self):
        self.member = None
        self.bounds = []
        self.lbl1 = QtWidgets.QLabel()
        self.lbl2 = QtWidgets.QLabel()
        self.lbl1.setWordWrap(True)
        self.lbl2.setWordWrap(True)
        self.lay.addWidget(QtWidgets.QLabel("<b>Bodies to be trimmed</b>"))
        self.lay.addWidget(self.lbl1)
        self.lay.addWidget(QtWidgets.QLabel("<b>Trimming boundary</b>"))
        self.lay.addWidget(self.lbl2)
        self.type = QtWidgets.QComboBox()
        self.type.addItems(["Planar", "Body"])
        self.type.setToolTip("Planar: cut square to the face met. Body: cut to the shape")
        f = QtWidgets.QFormLayout()
        f.addRow("Cut", self.type)
        self.lay.addLayout(f)
        self.type.currentTextChanged.connect(self._update)

    def _take(self, sel):
        for s in sel:
            o = s.Object
            if self.member is None and W.is_member(o):
                self.member = o
                self._orig = (list(getattr(o, "TrimTo", []) or []),
                              getattr(o, "TrimType", "Planar"))
                self.bounds = list(self._orig[0])
                self.type.setCurrentText(self._orig[1])
                continue
            if o is self.member or not hasattr(o, "Shape"):
                continue
            if o in self.bounds:
                self.bounds.remove(o)
            else:
                self.bounds.append(o)

    def _remove(self):
        if self.member is not None:
            self.member.TrimTo, self.member.TrimType = self._orig

    def _update(self, *_):
        self.lbl1.setText(self.member.Label if self.member else "Click the structural member "
                          "whose ends to trim / extend.")
        self.lbl2.setText(", ".join(b.Label for b in self.bounds) if self.bounds
                          else "Then click the members or bodies to trim / extend them to.")
        if self.member is not None:
            W._add_trim_props(self.member)
            self.member.TrimTo = self.bounds
            self.member.TrimType = self.type.currentText()
            self.member.Document.recompute()
            self.msg.setText("Free ends that reach a boundary are trimmed or extended to it.")


def _open(cls):
    if App.ActiveDocument is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), cls.TITLE,
                                          "Finish the open dialog first.")
        return None
    p = cls()
    Gui.Control.showDialog(p)
    return p


def end_cap():
    return _open(EndCapPanel)


def gusset():
    return _open(GussetPanel)


def trim_extend():
    return _open(TrimPanel)
