# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Linear Pattern, Circular Pattern and Mirror."""

from mechflow_gui.panel_base import (FeaturePanel, PickField, has, set_enum,
                                     origin_feature, open_panel)

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

AXES = ["X axis", "Y axis", "Z axis"]
AXIS_ROLE = {"X axis": "X_Axis", "Y axis": "Y_Axis", "Z axis": "Z_Axis"}
PLANES = ["Front Plane", "Top Plane", "Right Plane"]
PLANE_ROLE = {"Front Plane": "XZ_Plane", "Top Plane": "XY_Plane", "Right Plane": "YZ_Plane"}


def _value(q):
    return getattr(q, "Value", q)


def _dir_vector(body, obj, sub):
    """The direction a linear pattern takes from its Direction reference."""
    import FreeCAD as App
    try:
        gpl = body.getGlobalPlacement()
    except Exception:
        gpl = App.Placement()
    v = None
    if sub.startswith("Edge"):
        e = obj.Shape.getElement(sub)
        v = gpl.Rotation.multVec(e.Vertexes[-1].Point - e.Vertexes[0].Point)
    elif sub.startswith("Face"):
        from mechflow_gui import pick_solid
        _p, n = pick_solid._face_probe(obj.Shape.getElement(sub))
        v = gpl.Rotation.multVec(n)
    else:
        rot = obj.getGlobalPlacement().Rotation
        if obj.TypeId == "App::Line":
            v = rot.multVec(App.Vector(1, 0, 0))
        else:                     # datum line, planes: their Z
            v = rot.multVec(App.Vector(0, 0, 1))
    if v is None or v.Length < 1e-9:
        return None
    return v.normalize()


def _feature_centre(body, feat):
    import FreeCAD as App
    try:
        gpl = body.getGlobalPlacement()
    except Exception:
        gpl = App.Placement()
    # Sketch-based features: start at the sketch (usually on the part's
    # surface, where the arrow can be seen and grabbed).
    prof = getattr(feat, "Profile", None)
    prof = prof[0] if isinstance(prof, (tuple, list)) else prof
    if prof is not None and getattr(prof, "MechFlowThinSketch", None) is not None:
        prof = prof.MechFlowThinSketch
    try:
        if prof is not None and not prof.Shape.isNull():
            return gpl.multVec(prof.Shape.BoundBox.Center)
    except Exception:
        pass
    for prop in ("AddSubShape", "Shape"):
        try:
            s = getattr(feat, prop)
            if s is not None and not s.isNull():
                return gpl.multVec(s.BoundBox.Center)
        except Exception:
            pass
    return None


def _role_name(obj, table):
    """'X axis' / 'Front Plane' etc. if obj is one of the body's origin items."""
    for name, role in table.items():
        if obj is not None and obj.TypeId in ("App::Line", "App::Plane") and \
                obj.Name.startswith(role):
            return name
    return None


def _load_ref(field, combo, link, table):
    """Show a saved reference: origin items in the dropdown, others in the box."""
    if not link:
        return
    obj, subs = link[0], list(link[1]) if len(link) > 1 else []
    name = _role_name(obj, table)
    if name and not any(subs):
        combo.setCurrentText(name)
        field.set([])
    else:
        field.set([(obj, (subs or [""])[0])])


class _Patterned(FeaturePanel):
    """Common: 'Features to pattern' field."""

    def _features_field(self):
        return self.add_field(PickField(
            self, "Features to Pattern", ["feature"],
            hint="Click features in the tree, or a face of the feature in the view."))

    def ready(self):
        return bool(self.feats.items) and self._direction() is not None

    def _originals(self):
        return [o for o, _ in self.feats.items]

    def finish(self):
        pass


class LinearPatternPanel(_Patterned):
    TITLE = "Linear Pattern"
    HINT = "Click a straight edge, axis or flat face for the direction."

    def build(self):
        self.dirf = self.add_field(PickField(self, "Direction 1", ["linear", "plane"],
                                             single=True))
        row = QtWidgets.QFormLayout()
        self.axis = self.combo(["Selected edge / face"] + AXES)
        row.addRow("or use", self.axis)
        self.reverse = self.check("Reverse direction")
        row.addRow("", self.reverse)
        self.spacing = self.spin(" mm", 0.001, 1e6, 10.0)
        row.addRow("Spacing", self.spacing)
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(2, 10000)
        self.count.setValue(3)
        self.count.valueChanged.connect(self.changed)
        row.addRow("Instances", self.count)
        self.root.addLayout(row)
        self.feats = self._features_field()
        self.spacing_arrow = self.add_arrow(self.spacing)

    def _direction(self):
        if self.dirf.items:
            return self.dirf.items[0]
        role = AXIS_ROLE.get(self.axis.currentText())
        f = origin_feature(self.body, role) if role else None
        return (f, "") if f is not None else None

    def load(self, f):
        self.feats.set([(o, "") for o in f.Originals])
        _load_ref(self.dirf, self.axis, getattr(f, "Direction", None), AXIS_ROLE)
        self.reverse.setChecked(bool(getattr(f, "Reversed", False)))
        n = int(getattr(f, "Occurrences", 3))
        self.count.setValue(n)
        if has(f, "Offset") and str(getattr(f, "Mode", "")).lower().startswith(("spac", "off")):
            self.spacing.setValue(_value(f.Offset))
        else:
            self.spacing.setValue(_value(f.Length) / max(1, n - 1))

    def make_feature(self):
        return self.body.newObject("PartDesign::LinearPattern", "LinearPattern")

    def update_feature(self, f):
        f.Originals = self._originals()
        obj, sub = self._direction()
        f.Direction = (obj, [sub] if sub else [""])
        f.Reversed = self.reverse.isChecked()
        n = self.count.value()
        f.Occurrences = n
        if has(f, "Mode") and set_enum(f, "Mode", ["Spacing", "Offset"]) and has(f, "Offset"):
            f.Offset = self.spacing.value()
        else:
            f.Length = self.spacing.value() * (n - 1)
        # Drag arrow from the first feature to where its first copy goes.
        try:
            d = _dir_vector(self.body, obj, sub)
            o = _feature_centre(self.body, self._originals()[0])
            if d is None or o is None:
                raise ValueError
            if f.Reversed:
                d = d * -1.0
            self.spacing_arrow.show(o, d, max(1.0, self.size() * 0.05))
        except Exception:
            self.spacing_arrow.hide()

    def error_text(self):
        return ("<b>The pattern can't be built.</b> The copies may run off the part, "
                "or the direction isn't usable - try a different spacing or direction.")


class CircularPatternPanel(_Patterned):
    TITLE = "Circular Pattern"
    HINT = "Click a straight edge, axis or round face for the axis."

    def build(self):
        self.axf = self.add_field(PickField(self, "Axis", ["linear", "axis"], single=True))
        row = QtWidgets.QFormLayout()
        self.axis = self.combo(["Selected edge / face"] + AXES)
        row.addRow("or use", self.axis)
        self.reverse = self.check("Reverse direction")
        row.addRow("", self.reverse)
        self.equal = self.check("Equal spacing (full 360°)", True)
        row.addRow("", self.equal)
        self.angle = self.spin("°", 0.001, 360.0, 360.0)
        row.addRow("Angle", self.angle)
        self.count = QtWidgets.QSpinBox()
        self.count.setRange(2, 10000)
        self.count.setValue(4)
        self.count.valueChanged.connect(self.changed)
        row.addRow("Instances", self.count)
        self.root.addLayout(row)
        self.feats = self._features_field()

    def _direction(self):
        if self.axf.items:
            return self.axf.items[0]
        role = AXIS_ROLE.get(self.axis.currentText())
        f = origin_feature(self.body, role) if role else None
        return (f, "") if f is not None else None

    def load(self, f):
        self.feats.set([(o, "") for o in f.Originals])
        _load_ref(self.axf, self.axis, getattr(f, "Axis", None), AXIS_ROLE)
        self.reverse.setChecked(bool(getattr(f, "Reversed", False)))
        n = int(getattr(f, "Occurrences", 4))
        self.count.setValue(n)
        ang = _value(getattr(f, "Angle", 360.0))
        self.equal.setChecked(abs(ang - 360.0) < 1e-6)
        self.angle.setValue(360.0 if abs(ang - 360.0) < 1e-6 else ang / max(1, n - 1))

    def make_feature(self):
        return self.body.newObject("PartDesign::PolarPattern", "PolarPattern")

    def update_feature(self, f):
        f.Originals = self._originals()
        obj, sub = self._direction()
        f.Axis = (obj, [sub] if sub else [""])
        f.Reversed = self.reverse.isChecked()
        n = self.count.value()
        f.Occurrences = n
        self.angle.setEnabled(not self.equal.isChecked())
        if has(f, "Mode"):
            set_enum(f, "Mode", ["Extent", "Overall angle", "angle"])
        if self.equal.isChecked():
            f.Angle = 360.0
        else:
            # SOLIDWORKS: angle between instances.
            f.Angle = min(360.0, self.angle.value() * (n - 1))

    def error_text(self):
        return ("<b>The pattern can't be built.</b> Copies may overlap or leave the "
                "part, or the axis isn't usable.")


class MirrorPanel(_Patterned):
    TITLE = "Mirror"
    HINT = "Click a flat face or plane to mirror about, then the features to mirror."

    def build(self):
        self.planef = self.add_field(PickField(self, "Mirror Face/Plane", ["plane"],
                                               single=True))
        row = QtWidgets.QFormLayout()
        self.plane = self.combo(["Selected face / plane"] + PLANES)
        row.addRow("or use", self.plane)
        self.root.addLayout(row)
        self.feats = self.add_field(PickField(
            self, "Features to Mirror", ["feature"],
            hint="Click features in the tree, or a face of the feature in the view."))

    def _direction(self):
        if self.planef.items:
            return self.planef.items[0]
        role = PLANE_ROLE.get(self.plane.currentText())
        f = origin_feature(self.body, role) if role else None
        return (f, "") if f is not None else None

    def load(self, f):
        self.feats.set([(o, "") for o in f.Originals])
        _load_ref(self.planef, self.plane, getattr(f, "MirrorPlane", None), PLANE_ROLE)

    def make_feature(self):
        return self.body.newObject("PartDesign::Mirrored", "Mirrored")

    def update_feature(self, f):
        f.Originals = self._originals()
        obj, sub = self._direction()
        f.MirrorPlane = (obj, [sub] if sub else [""])


def linear(feature=None):
    open_panel(LinearPatternPanel, feature)


def circular(feature=None):
    open_panel(CircularPatternPanel, feature)


def mirror(feature=None):
    open_panel(MirrorPanel, feature)
