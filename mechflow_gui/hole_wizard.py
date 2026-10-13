# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Hole Wizard.

1. Click the flat face for the holes (or have it selected before starting).
2. Click on that face to place hole centres - as many as you like.
3. Choose type (Simple / Counterbore / Countersink / Tapped), ISO metric size,
   fit and end condition. The preview updates as you go.

Behind the scenes MechFlow makes a positions sketch on the face and drives
FreeCAD's PartDesign Hole with it. To dimension the positions exactly later,
edit that sketch.
"""

import FreeCAD as App
import FreeCADGui as Gui

from mechflow_gui.extrude import _has, _set_enum, _body_of

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

TYPES = ["Simple", "Counterbore", "Countersink", "Tapped"]
SIZES = ["M3", "M4", "M5", "M6", "M8", "M10", "M12", "M16", "M20"]
# FreeCAD 1.1 calls the ISO 273 clearance fits Fine / Medium / Coarse.
FITS = {"Normal": ["Medium", "Standard", "Normal"], "Close": ["Fine", "Close"],
        "Loose": ["Coarse", "Wide", "Loose"]}
CUTS = {
    "Simple": ["None"],
    "Counterbore": ["ISO 4762", "Counterbore"],
    "Countersink": ["ISO 10642", "Countersink"],
    "Tapped": ["None"],
}
MARKER_RADIUS = 0.5      # positions are circles; the hole uses their centres


def _sketch_on_face(body, obj, face):
    sk = body.newObject("Sketcher::SketchObject", "Sketch")
    prop = "AttachmentSupport" if _has(sk, "AttachmentSupport") else "Support"
    setattr(sk, prop, [(obj, face)])
    sk.MapMode = "FlatFace"
    sk.Document.recompute()
    try:
        sk.ViewObject.Visibility = False
    except Exception:
        pass
    return sk


def set_thread_size(hole, size):
    """FreeCAD 1.1 names sizes with the pitch ("M8x1.25"); older versions
    used "M8". Pick the coarse-pitch entry for a size like "M8"."""
    try:
        options = list(hole.getEnumerationsOfProperty("ThreadSize") or [])
    except Exception:
        return False
    for name in options:
        if name == size or name.split("x")[0] == size:
            hole.ThreadSize = name
            return True
    return False


def size_of(hole):
    """'M8' from a hole's ThreadSize ('M8x1.25' or 'M8')."""
    return str(getattr(hole, "ThreadSize", "")).split("x")[0]


def _circles(sketch):
    return [g for g in sketch.Geometry if type(g).__name__ == "Circle"]


def first_wall_depth(shape, points, direction, radius, overshoot=0.5):
    """Up To Next: how deep to drill from each point along direction to come
    out of the first wall (and no further), checked round the hole's edge
    too so a curved inside face is cleared everywhere. None if a hole never
    comes out (a solid block - use Blind or Through All)."""
    import math
    import Part
    d = App.Vector(direction).normalize()
    bb = shape.BoundBox
    reach = bb.DiagonalLength * 2 + 10
    # two directions square to the drill axis
    a = App.Vector(1, 0, 0) if abs(d.x) < 0.9 else App.Vector(0, 1, 0)
    u = d.cross(a).normalize()
    v = d.cross(u).normalize()
    deepest = 0.0
    for p in points:
        for k in range(9):
            q = App.Vector(p)
            if k:
                ang = (k - 1) * math.pi / 4
                q = q + (u * math.cos(ang) + v * math.sin(ang)) * (radius * 0.98)
            start = q - d * 1e-3
            edge = Part.LineSegment(start, start + d * reach).toShape()
            try:
                inside = edge.common(shape)
            except Exception:
                return None
            spans = []
            for e in inside.Edges:
                t0 = (e.Vertexes[0].Point - start).dot(d)
                t1 = (e.Vertexes[-1].Point - start).dot(d)
                spans.append((min(t0, t1), max(t0, t1)))
            spans.sort()
            # the material the drill meets first, starting at the face
            first = None
            for t0, t1 in spans:
                if t0 < 1.0:
                    first = t1 if first is None else max(first, t1)
            if first is None:
                continue               # this sample misses the part (edge of a face)
            if first > reach * 0.49:
                return None
            deepest = max(deepest, first)
    return deepest + overshoot if deepest > 0 else None


class HolePanel:
    def __init__(self, body, sketch=None, hole=None):
        self.body = body
        self.doc = body.Document
        self.sketch = sketch
        self.hole = hole
        self.creating = hole is None
        self.base = hole.BaseFeature if hole is not None else body.Tip
        self.failed = False
        self._loading = False
        self.form = self._build_ui()
        if hole is not None:
            self._load()
        self._update_status()
        self._apply()
        Gui.Selection.clearSelection()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ---- UI
    def _combo(self, items):
        c = QtWidgets.QComboBox()
        c.addItems(items)
        c.currentIndexChanged.connect(self._changed)
        return c

    def _build_ui(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Hole Wizard")
        root = QtWidgets.QVBoxLayout(w)

        spec = QtWidgets.QGroupBox("Hole Specification")
        f = QtWidgets.QFormLayout(spec)
        self.type = self._combo(TYPES)
        f.addRow("Type", self.type)
        self.standard = QtWidgets.QLabel("ISO metric")
        f.addRow("Standard", self.standard)
        self.size = self._combo(SIZES)
        self.size.setCurrentText("M6")
        f.addRow("Size", self.size)
        self.fit = self._combo(list(FITS))
        f.addRow("Fit", self.fit)
        root.addWidget(spec)

        end = QtWidgets.QGroupBox("End Condition")
        e = QtWidgets.QFormLayout(end)
        self.end = self._combo(["Blind", "Up To Next", "Through All"])
        e.addRow("", self.end)
        self.depth = QtWidgets.QDoubleSpinBox()
        self.depth.setRange(0.1, 1e5)
        self.depth.setSuffix(" mm")
        self.depth.setValue(10.0)
        self.depth.setKeyboardTracking(False)
        self.depth.valueChanged.connect(self._changed)
        e.addRow("Depth", self.depth)
        root.addWidget(end)

        pos = QtWidgets.QGroupBox("Positions")
        p = QtWidgets.QVBoxLayout(pos)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        p.addWidget(self.status)
        row = QtWidgets.QHBoxLayout()
        undo = QtWidgets.QPushButton("Remove last")
        undo.clicked.connect(self._remove_last)
        clr = QtWidgets.QPushButton("Clear")
        clr.clicked.connect(self._clear)
        row.addWidget(undo)
        row.addWidget(clr)
        p.addLayout(row)
        root.addWidget(pos)

        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            "background: rgba(200, 60, 60, 60); border: 1px solid #c04040;"
            " border-radius: 4px; padding: 6px;")
        self.error.hide()
        root.addWidget(self.error)
        root.addStretch(1)
        return w

    def _update_status(self):
        if self.sketch is None:
            self.status.setText("<b>Click the flat face</b> you want the holes on.")
            return
        n = len(_circles(self.sketch))
        if n == 0:
            self.status.setText("<b>Click on the face</b> to place hole centres.")
        else:
            self.status.setText(f"<b>{n} hole{'s' if n != 1 else ''}.</b> "
                                "Click on the face to add more.")

    def _changed(self, *_):
        if self._loading:
            return
        self.fit.setEnabled(self.type.currentText() != "Tapped")
        self.depth.setEnabled(self.end.currentText() == "Blind")
        self._apply()

    # ---- load an existing hole
    def _load(self):
        h = self.hole
        self._loading = True
        try:
            cut = str(getattr(h, "HoleCutType", "None"))
            if getattr(h, "Threaded", False):
                self.type.setCurrentText("Tapped")
            elif "4762" in cut or "bore" in cut.lower():
                self.type.setCurrentText("Counterbore")
            elif "10642" in cut or "sink" in cut.lower():
                self.type.setCurrentText("Countersink")
            size = size_of(h) or "M6"
            if size in SIZES:
                self.size.setCurrentText(size)
            fit = str(getattr(h, "ThreadFit", "Standard"))
            for k, names in FITS.items():
                if fit in names:
                    self.fit.setCurrentText(k)
            if str(getattr(h, "DepthType", "Dimension")) == "ThroughAll":
                self.end.setCurrentText("Through All")
            elif getattr(h, "MechFlowUpToNext", False):
                self.end.setCurrentText("Up To Next")
            d = getattr(h, "Depth", 10.0)
            self.depth.setValue(getattr(d, "Value", d))
        finally:
            self._loading = False
        self.fit.setEnabled(self.type.currentText() != "Tapped")
        self.depth.setEnabled(self.end.currentText() == "Blind")

    # ---- picking
    def _poll(self):
        try:
            sel = Gui.Selection.getSelectionEx()
        except Exception:
            return
        if not sel:
            return
        item = sel[0]
        subs = item.SubElementNames
        picked = list(getattr(item, "PickedPoints", []) or [])
        Gui.Selection.clearSelection()
        if not subs or not subs[0].startswith("Face"):
            return
        if self.sketch is None:
            try:
                face = item.SubObjects[0]
                if type(face.Surface).__name__ != "Plane":
                    self.status.setText("That face isn't flat - pick a flat face.")
                    return
            except Exception:
                return
            self.sketch = _sketch_on_face(self.body, item.Object, subs[0])
            if picked:
                self._add_point(picked[0])     # first click also places a hole
            self._update_status()
            self._apply()
            return
        if picked:
            self._add_point(picked[0])

    def _add_point(self, p):
        import Part
        gp = self.sketch.getGlobalPlacement()
        local = gp.inverse().multVec(App.Vector(p.x, p.y, p.z))
        if abs(local.z) > 1e-3:
            self.status.setText("Click on the same face as the other holes.")
            return
        self.sketch.addGeometry(
            Part.Circle(App.Vector(local.x, local.y, 0), App.Vector(0, 0, 1), MARKER_RADIUS))
        self._update_status()
        self._apply()

    def _remove_last(self):
        if self.sketch is None:
            return
        geos = self.sketch.Geometry
        for i in range(len(geos) - 1, -1, -1):
            if type(geos[i]).__name__ == "Circle":
                self.sketch.delGeometry(i)
                break
        self._update_status()
        self._apply()

    def _clear(self):
        if self.sketch is None:
            return
        geos = self.sketch.Geometry
        for i in range(len(geos) - 1, -1, -1):
            if type(geos[i]).__name__ == "Circle":
                self.sketch.delGeometry(i)
        self._update_status()
        self._apply()

    # ---- feature
    def _apply(self, *_):
        if self.sketch is None or not _circles(self.sketch):
            if self.hole is not None:
                try:
                    self.hole.ViewObject.Visibility = False
                except Exception:
                    pass
            self._show_base(True)
            self.error.hide()
            self.failed = self.hole is not None
            return
        if self.hole is None:
            self.hole = self.body.newObject("PartDesign::Hole", "Hole")
            self.hole.Profile = self.sketch
        h = self.hole
        kind = self.type.currentText()
        try:
            _set_enum(h, "ThreadType", ["ISOMetricProfile"])
            if not set_thread_size(h, self.size.currentText()):
                App.Console.PrintWarning(
                    f"MechFlow: thread size {self.size.currentText()} not available\n")
            if _has(h, "Threaded"):
                h.Threaded = kind == "Tapped"
            if _has(h, "ModelThread"):
                h.ModelThread = False
            if kind != "Tapped":
                _set_enum(h, "ThreadFit", FITS[self.fit.currentText()])
            _set_enum(h, "HoleCutType", CUTS[kind])
            if not _has(h, "MechFlowUpToNext"):
                h.addProperty("App::PropertyBool", "MechFlowUpToNext", "MechFlow",
                              "Drilled through the first wall only (Up To Next)")
            h.MechFlowUpToNext = self.end.currentText() == "Up To Next"
            if self.end.currentText() == "Through All":
                _set_enum(h, "DepthType", ["ThroughAll"])
            elif self.end.currentText() == "Up To Next":
                _set_enum(h, "DepthType", ["Dimension"])
                depth = self._up_to_next()
                if depth is None:
                    raise ValueError("no wall to drill through")
                _set_enum(h, "DrillPoint", ["Flat"])
                h.Depth = depth
                self.depth.blockSignals(True)
                self.depth.setValue(depth)
                self.depth.blockSignals(False)
            else:
                _set_enum(h, "DepthType", ["Dimension"])
                h.Depth = self.depth.value()
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: hole setting not applied ({e})\n")
        try:
            self.doc.recompute()
        except Exception:
            pass
        self._check()

    def _up_to_next(self):
        base = self.hole.BaseFeature if self.hole is not None else self.base
        if base is None:
            return None
        gp = self.sketch.getGlobalPlacement()
        pts = [gp.multVec(g.Center) for g in _circles(self.sketch)]
        n = gp.Rotation.multVec(App.Vector(0, 0, 1))
        try:
            r = float(self.size.currentText().lstrip("M")) * 0.55     # clearance
        except Exception:
            r = 6.0
        try:
            r = max(r, float(self.hole.Diameter) / 2)
        except Exception:
            pass
        shape = base.Shape
        # the drill goes into the material, away from the face's outside
        probe = pts[0] - n * 0.05
        direction = -n if shape.isInside(probe, 1e-6, True) else n
        return first_wall_depth(shape, pts, direction, r)

    def _show_base(self, on):
        try:
            if self.base is not None:
                self.base.ViewObject.Visibility = on
        except Exception:
            pass

    def _check(self):
        h = self.hole
        try:
            ok = h.isValid() and not h.Shape.isNull()
        except Exception:
            ok = False
        self.failed = not ok
        if ok:
            self.error.hide()
            self._show_base(False)
            h.ViewObject.Visibility = True
            return
        h.ViewObject.Visibility = False
        self._show_base(True)
        self.error.setText(
            "<b>The hole can't be built</b> with these settings - for example a "
            "counterbore too big for the face. Try another size or type.<br>"
            "Your model is unchanged.")
        self.error.show()

    # ---- task dialog protocol
    def _stop(self):
        try:
            self._timer.stop()
        except Exception:
            pass

    def accept(self):
        if self.hole is None or self.failed or not _circles(self.sketch):
            QtWidgets.QMessageBox.information(
                self.form, "Hole Wizard",
                "Place at least one hole, and fix any error shown in the panel - "
                "or press Cancel to leave the model unchanged.")
            return False
        self._stop()
        try:
            self.sketch.ViewObject.Visibility = False
        except Exception:
            pass
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._stop()
        self.doc.abortTransaction()
        try:
            if self.body.Tip is not None:
                self.body.Tip.ViewObject.Visibility = True
        except Exception:
            pass
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def create():
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Hole Wizard", "Finish the open dialog first.")
        return
    from mechflow_gui import pick_solid
    sel = Gui.Selection.getSelectionEx()
    body = None
    face = None
    if sel:
        body = _body_of(sel[0].Object)
        subs = sel[0].SubElementNames
        if subs and subs[0].startswith("Face"):
            try:
                if type(sel[0].SubObjects[0].Surface).__name__ == "Plane":
                    face = (sel[0].Object, subs[0])
            except Exception:
                pass
    body = body or pick_solid.active_body()
    if body is None or body.Tip is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Hole Wizard", "There's no solid to put holes in yet.")
        return
    body.Document.openTransaction("Hole Wizard")
    sketch = _sketch_on_face(body, face[0], face[1]) if face else None
    Gui.Control.showDialog(HolePanel(body, sketch=sketch))


def edit(hole):
    if Gui.Control.activeDialog():
        return
    body = _body_of(hole)
    profile = getattr(hole, "Profile", None)
    sketch = profile[0] if isinstance(profile, tuple) else profile
    if body is None:
        return
    hole.Document.openTransaction("Edit " + hole.Label)
    Gui.Control.showDialog(HolePanel(body, sketch=sketch, hole=hole))
