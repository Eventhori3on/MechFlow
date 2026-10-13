# SPDX-License-Identifier: LGPL-2.1-or-later
"""Nozzle: a pipe stub on a tank or vessel wall, flat or curved.

Click the face where it goes, pick the pipe size and how far it stands
out, and MechFlow adds the stub (shaped to meet a curved shell all round)
and bores through the wall it sits on - only that wall. The pipe end is a
true circle, so the Toolbox (or the Flange option here) can put a weld neck
flange straight on it.

The nozzle is a feature in the part's history (a PartDesign Python
feature), so it moves with the part and can be edited by double-clicking.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector
STANDARDS = {"EN 10220": "EN10220-PIPE", "ASME B36.10M": "ASMEB36.10-PIPE"}
FLANGES = {
    "EN 10220": [("None", None), ("Weld neck (EN 1092-1 Type 11)", "EN1092-1-11"),
                 ("Plate (EN 1092-1 Type 01)", "EN1092-1-01")],
    "ASME B36.10M": [("None", None), ("Weld neck RF (ASME B16.5)", "ASMEB16.5-WN"),
                     ("Slip-on RF (ASME B16.5)", "ASMEB16.5-SO")],
}
DIRECTIONS = [("Square to the face", None), ("+X", (1, 0, 0)), ("-X", (-1, 0, 0)),
              ("+Y", (0, 1, 0)), ("-Y", (0, -1, 0)), ("+Z", (0, 0, 1)), ("-Z", (0, 0, -1))]


# ------------------------------------------------------------ geometry

def pipe_dims(standard, size, schedule):
    from mechflow_gui import stdparts
    if standard == "ASME B36.10M":
        return stdparts.asme_pipe(size, schedule or "Sch 40")
    return stdparts.en_pipe(size)


def _spans(shape, start, d, reach):
    """[(t0, t1)] where the line start + t*d runs through shape's material."""
    import Part
    edge = Part.LineSegment(start, start + d * reach).toShape()
    out = []
    for e in edge.common(shape).Edges:
        t0 = (e.Vertexes[0].Point - start).dot(d)
        t1 = (e.Vertexes[-1].Point - start).dot(d)
        out.append((min(t0, t1), max(t0, t1)))
    return sorted(out)


def surface_point(shape, p, d):
    """Where the nozzle's axis (through p, along d) comes out of the wall
    nearest p: the outside face the nozzle stands on."""
    reach = shape.BoundBox.DiagonalLength * 2 + 100
    far = p + d * reach
    spans = _spans(shape, far, -d, 2 * reach)
    if not spans:
        return None
    # each span's first point (coming in from outside) is an outside face
    best = min(spans, key=lambda s: abs(((far - d * s[0]) - p).dot(d)))
    return far - d * best[0]


def nozzle_shape(base, p, d, od, wall, standout):
    """base with a pipe stub on the wall at p, its end standout from the
    face along d, and the bore through that wall only."""
    import Part
    d = V(d).normalize()
    s = surface_point(base, p, d)
    if s is None:
        raise ValueError("the nozzle's axis doesn't meet the part")
    reach = base.BoundBox.DiagonalLength * 2 + 100
    end = s + d * standout
    # the stub: the pipe's outside, from deep in the part out to its end,
    # less everything that's already part - keep the bit at the end
    rod = Part.makeCylinder(od / 2, reach + standout, end - d * (reach + standout), d)
    outside = rod.cut(base)
    probe = end - d * min(1.0, standout / 2)
    stub = [so for so in outside.Solids if so.isInside(probe, 1e-6, True)]
    if not stub:
        raise ValueError("the pipe doesn't stand out of the part - more standout?")
    solid = base.fuse(stub[0])
    # the bore: from the pipe end in, through the stub and the first wall
    from mechflow_gui import hole_wizard
    ri = od / 2 - wall
    depth = hole_wizard.first_wall_depth(solid, [end], -d, ri, overshoot=0.5)
    if depth is None:
        raise ValueError("there's no inside to bore into (a solid part?)")
    bore = Part.makeCylinder(ri, depth + 1.0, end + d * 1.0, -d)
    result = solid.cut(bore)
    try:
        result = result.removeSplitter()
    except Exception:
        pass
    return result, end


class NozzleFeature:
    """PartDesign Python feature proxy for a nozzle."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyVector", "Position", "Nozzle",
                        "A point on the nozzle's axis, near the wall (in the part's axes)")
        obj.addProperty("App::PropertyVector", "Direction", "Nozzle",
                        "Which way the nozzle points out of the wall")
        obj.addProperty("App::PropertyEnumeration", "Standard", "Nozzle", "Pipe standard")
        obj.Standard = list(STANDARDS)
        obj.addProperty("App::PropertyString", "Size", "Nozzle", "Pipe size (DN.. / NPS ..)")
        obj.addProperty("App::PropertyString", "Schedule", "Nozzle", "ASME schedule")
        obj.addProperty("App::PropertyLength", "Standout", "Nozzle",
                        "From the outside of the wall to the pipe end, along the axis")
        obj.addProperty("App::PropertyVector", "PipeEnd", "Nozzle",
                        "Centre of the pipe end (worked out)", 1)
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature else None
        if base is None or base.isNull():
            raise ValueError("A nozzle needs a part to go on")
        od, wall = pipe_dims(obj.Standard, obj.Size, obj.Schedule)
        shape, end = nozzle_shape(base, V(obj.Position), V(obj.Direction), od, wall,
                                  float(obj.Standout))
        obj.Shape = shape
        if (V(obj.PipeEnd) - end).Length > 1e-9:
            obj.PipeEnd = end

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderNozzle:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path("Nozzle.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(NozzlePanel(feature=vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        return None

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def label_for(obj):
    """'Nozzle DN80 x 150<1>' (the <n> stops FreeCAD renumbering the 150)."""
    from mechflow_gui import toolbox
    base = f"Nozzle {obj.Size} x {float(obj.Standout):g}"
    if obj.Label.startswith(base + "<"):
        return obj.Label
    return toolbox.instance_label(obj.Document, base)


def make(body, position, direction, standard="EN 10220", size="DN80", schedule="",
         standout=150.0):
    """Add a nozzle to body (position / direction in the body's axes)."""
    o = body.newObject("PartDesign::FeaturePython", "Nozzle")
    NozzleFeature(o)
    o.Position = position
    o.Direction = direction
    o.Standard = standard
    o.Size = size
    o.Schedule = schedule
    o.Standout = standout
    if App.GuiUp:
        ViewProviderNozzle(o.ViewObject)
        try:
            prev = o.BaseFeature
            if prev is not None:
                o.ViewObject.ShapeAppearance = prev.ViewObject.ShapeAppearance
                prev.ViewObject.Visibility = False
        except Exception:
            pass
    o.Label = label_for(o)
    body.Document.recompute()
    return o


def end_edge(feature):
    """Name of the pipe end's outside circle on the body (for a flange)."""
    body = feature.getParentGeoFeatureGroup()
    od, _w = pipe_dims(feature.Standard, feature.Size, feature.Schedule)
    end = V(feature.PipeEnd)
    shape = feature.Shape
    best = None
    for i, e in enumerate(shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - od / 2) < 1e-3 and \
                (c.Center - end).Length < 1e-3:
            best = f"Edge{i + 1}"
    return body, best


def add_flange(feature, ftype, rating=None, container=None):
    """Put a flange on the nozzle's end (Toolbox placement on its circle)."""
    from mechflow_gui import stdparts
    body, sub = end_edge(feature)
    if sub is None:
        raise ValueError("couldn't find the nozzle's pipe end")
    size = feature.Size
    if ftype.startswith("ASME"):
        size = stdparts.nps_label(size).replace("NPS ", "")
        size = f"NPS {size}" if f"NPS {size}" in stdparts.sizes(ftype) else size
    rating = rating or stdparts.default_rating(ftype)
    if container is None:
        # with the part: in its Part container if it has one
        try:
            part = body.getParentGeoFeatureGroup()
        except Exception:
            part = None
        if part is not None and part.TypeId == "App::Part":
            container = part
    return stdparts.place(container, ftype, body, sub, size, rating, joint=False)


# ------------------------------------------------------------ panel

def _body_of(obj):
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Body":
        return obj
    try:
        b = obj.getParentGeoFeatureGroup()
        if b is not None and b.TypeId == "PartDesign::Body":
            return b
    except Exception:
        pass
    return None


class NozzlePanel:
    def __init__(self, feature=None):
        self.feature = feature
        self.editing = feature is not None
        self.body = _body_of(feature) if feature else None
        self.face_normal = None
        self._loading = True
        self.doc = (feature.Document if feature else App.ActiveDocument)
        self.doc.openTransaction("Nozzle")
        self.form = self._build()
        if feature is not None:
            self._load()
        self._loading = False
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        Gui.Selection.clearSelection()
        self._update_status()

    # ---- UI
    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Nozzle")
        lay = QtWidgets.QVBoxLayout(w)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        f = QtWidgets.QFormLayout()
        self.std = QtWidgets.QComboBox()
        self.std.addItems(list(STANDARDS))
        f.addRow("Pipe", self.std)
        self.size = QtWidgets.QComboBox()
        f.addRow("Size", self.size)
        self.sched = QtWidgets.QComboBox()
        self.sched.addItems(["Sch 10", "Sch 40", "Sch 80"])
        self.sched.setCurrentText("Sch 40")
        f.addRow("Schedule", self.sched)
        self.standout = QtWidgets.QDoubleSpinBox()
        self.standout.setRange(1, 100000)
        self.standout.setValue(150)
        self.standout.setSuffix(" mm")
        self.standout.setKeyboardTracking(False)
        self.standout.setToolTip("From the outside of the wall to the pipe end")
        f.addRow("Standout", self.standout)
        self.dir = QtWidgets.QComboBox()
        for text, vec in DIRECTIONS:
            self.dir.addItem(text, vec)
        f.addRow("Points", self.dir)
        self.flip = QtWidgets.QCheckBox("Reverse")
        f.addRow("", self.flip)
        lay.addLayout(f)
        pos = QtWidgets.QGroupBox("Position (where the axis meets the wall)")
        pf = QtWidgets.QFormLayout(pos)
        self.xyz = []
        for ax in "XYZ":
            sb = QtWidgets.QDoubleSpinBox()
            sb.setRange(-1e6, 1e6)
            sb.setDecimals(2)
            sb.setSuffix(" mm")
            sb.setKeyboardTracking(False)
            sb.valueChanged.connect(self._changed)
            pf.addRow(ax, sb)
            self.xyz.append(sb)
        lay.addWidget(pos)
        fl = QtWidgets.QGroupBox("Flange on the end")
        ff = QtWidgets.QFormLayout(fl)
        self.flange = QtWidgets.QComboBox()
        ff.addRow("Flange", self.flange)
        self.rating = QtWidgets.QComboBox()
        ff.addRow("Rating", self.rating)
        self.flange_box = fl
        lay.addWidget(fl)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        self.std.currentTextChanged.connect(self._std_changed)
        for wdg in (self.size, self.sched, self.dir):
            wdg.currentTextChanged.connect(self._changed)
        self.flip.toggled.connect(self._changed)
        self.standout.valueChanged.connect(self._changed)
        self.flange.currentIndexChanged.connect(self._flange_changed)
        self._std_changed()
        if self.editing:
            fl.hide()
        return w

    def _std_changed(self, *_):
        from mechflow_gui import stdparts
        std = self.std.currentText()
        t = STANDARDS[std]
        keep = self.size.currentText()
        self.size.blockSignals(True)
        self.size.clear()
        self.size.addItems(stdparts.sizes(t))
        default = "DN80" if std == "EN 10220" else "NPS 3"
        self.size.setCurrentText(keep if self.size.findText(keep) >= 0 else default)
        self.size.blockSignals(False)
        self.sched.setEnabled(std != "EN 10220")
        self.flange.blockSignals(True)
        self.flange.clear()
        for text, ft in FLANGES[std]:
            self.flange.addItem(text, ft)
        self.flange.setCurrentIndex(1)
        self.flange.blockSignals(False)
        self._flange_changed()
        self._changed()

    def _flange_changed(self, *_):
        from mechflow_gui import stdparts
        ft = self.flange.currentData()
        self.rating.clear()
        if ft:
            self.rating.addItems(stdparts.ratings(ft))
            self.rating.setCurrentText(stdparts.default_rating(ft))
        self.rating.setEnabled(bool(ft))

    def _load(self):
        o = self.feature
        self.std.setCurrentText(o.Standard)
        self._std_changed()
        self.size.setCurrentText(o.Size)
        if o.Schedule:
            self.sched.setCurrentText(o.Schedule)
        self.standout.setValue(float(o.Standout))
        gp = self.body.getGlobalPlacement()
        p = gp.multVec(V(o.Position))
        for sb, v in zip(self.xyz, (p.x, p.y, p.z)):
            sb.setValue(v)
        d = gp.Rotation.multVec(V(o.Direction))
        self.face_normal = d
        for i in range(self.dir.count()):
            vec = self.dir.itemData(i)
            if vec is not None:
                if (V(*vec) - d).Length < 1e-6:
                    self.dir.setCurrentIndex(i)
                elif (V(*vec) + d).Length < 1e-6:
                    self.dir.setCurrentIndex(i)
                    self.flip.setChecked(True)

    def _update_status(self):
        if self.feature is None:
            self.status.setText("<b>Click the face</b> where the nozzle goes - a flat wall or "
                                "a curved shell. Then set the size and standout, or type an "
                                "exact position.")
        else:
            self.status.setText(f"<b>{self.feature.Label}</b> on {self.body.Label}. Click "
                                "another spot on the face to move it.")

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
        pts = list(getattr(item, "PickedPoints", []) or [])
        obj = item.Object
        face = item.SubObjects[0] if item.SubObjects else None
        Gui.Selection.clearSelection()
        if not subs or not subs[0].startswith("Face") or not pts or face is None:
            return
        body = _body_of(obj)
        if body is None:
            self.status.setText("Click a face of a part body (PartDesign).")
            return
        if self.body is not None and body is not self.body:
            self.status.setText("Click a face of the same part.")
            return
        self.body = body
        p = V(pts[0])
        try:
            u, v = face.Surface.parameter(p)
            n = V(face.normalAt(u, v)).normalize()
            if face.Orientation == "Reversed":
                pass  # normalAt already follows the face's orientation
            if body.Shape.isInside(p + n * 0.5, 1e-6, True):
                n = n * -1
        except Exception:
            n = V(0, 0, 1)
        self.face_normal = n
        self._loading = True
        for sb, val in zip(self.xyz, (p.x, p.y, p.z)):
            sb.setValue(val)
        self._loading = False
        self._changed()

    def _direction(self):
        vec = self.dir.currentData()
        d = V(*vec) if vec is not None else (V(self.face_normal) if self.face_normal else None)
        if d is None:
            return None
        return d * -1 if self.flip.isChecked() else d

    def _changed(self, *_):
        if self._loading or self.body is None:
            return
        d = self._direction()
        if d is None:
            return
        gp = self.body.getGlobalPlacement()
        inv = gp.inverse()
        p_local = inv.multVec(V(*[sb.value() for sb in self.xyz]))
        d_local = inv.Rotation.multVec(d)
        std = self.std.currentText()
        sched = self.sched.currentText() if std != "EN 10220" else ""
        try:
            if self.feature is None:
                self.feature = make(self.body, p_local, d_local, std, self.size.currentText(),
                                    sched, self.standout.value())
            else:
                o = self.feature
                o.Position, o.Direction = p_local, d_local
                o.Standard = std
                o.Size, o.Schedule = self.size.currentText(), sched
                o.Standout = self.standout.value()
                o.Label = label_for(o)
                self.doc.recompute()
        except Exception as e:
            self._show_error(str(e))
            return
        ok = self.feature.isValid() and not self.feature.Shape.isNull()
        if ok:
            self.error.hide()
            try:
                self.feature.ViewObject.Visibility = True
            except Exception:
                pass
        else:
            self._show_error("")
        self._update_status()

    def _show_error(self, why):
        self.error.setText("<b>The nozzle can't be made here</b>" +
                           (f": {why}" if why else "") +
                           ". Check the position, direction and standout.")
        self.error.show()

    # ---- task dialog
    def _stop(self):
        try:
            self._timer.stop()
        except Exception:
            pass

    def accept(self):
        if self.feature is None or not self.feature.isValid():
            QtWidgets.QMessageBox.information(
                self.form, "Nozzle",
                "Click a face to place the nozzle, and fix any error shown - or press "
                "Cancel to leave the part unchanged.")
            return False
        self._stop()
        self.made_flanges = []
        ft = self.flange.currentData() if not self.editing else None
        if ft:
            try:
                self.made_flanges = add_flange(self.feature, ft, self.rating.currentText())
            except Exception as e:
                QtWidgets.QMessageBox.warning(self.form, "Nozzle",
                                              f"The nozzle is in, but the flange couldn't be "
                                              f"added:\n{e}")
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception:
            pass
        return True

    def reject(self):
        self._stop()
        base = getattr(self.feature, "BaseFeature", None) if not self.editing else None
        self.doc.abortTransaction()
        try:
            if base is not None:
                base.ViewObject.Visibility = True
        except Exception:
            pass
        self.doc.recompute()
        Gui.Control.closeDialog()
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception:
            pass
        return True


def create():
    if App.ActiveDocument is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Nozzle",
                                          "Finish the open dialog first.")
        return None
    panel = NozzlePanel()
    # a face picked before clicking Nozzle starts it there
    Gui.Control.showDialog(panel)
    return panel
