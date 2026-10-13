# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Revolved Boss/Base and Revolved Cut PropertyManager.

Drives FreeCAD's PartDesign Revolution (boss) and Groove (cut). Property names
differ a little between FreeCAD versions, so options are only shown when the
feature has them.
"""

import FreeCAD as App
import FreeCADGui as Gui

from mechflow_gui.extrude import _has, _set_enum, _body_of, _value, _selected_sketch

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

# (label, how to build the ReferenceAxis link)
AXES = [
    ("Sketch vertical axis", ("sketch", "V_Axis")),
    ("Sketch horizontal axis", ("sketch", "H_Axis")),
    ("X axis", ("origin", "X_Axis")),
    ("Y axis", ("origin", "Y_Axis")),
    ("Z axis", ("origin", "Z_Axis")),
]
SELECTED = "Selected line / edge"


class RevolvePanel:
    def __init__(self, feature, sketch, cut, creating):
        self.feature = feature
        self.sketch = sketch
        self.cut = cut
        self.creating = creating
        self.doc = feature.Document
        self.body = _body_of(feature)
        self.picked_axis = None
        self.failed = False
        self._loading = False
        self.form = self._build_ui()
        self._load()
        self._apply()

    # ---- UI
    def _build_ui(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Cut-Revolve" if self.cut else "Revolve")
        root = QtWidgets.QVBoxLayout(w)

        ax = QtWidgets.QGroupBox("Axis of Revolution")
        al = QtWidgets.QVBoxLayout(ax)
        self.axis = QtWidgets.QComboBox()
        for label, _ in AXES:
            self.axis.addItem(label)
        self.axis.addItem(SELECTED)
        self.axis.currentIndexChanged.connect(self._apply)
        al.addWidget(self.axis)
        self.pick_btn = QtWidgets.QPushButton("Use selected line / edge")
        self.pick_btn.setToolTip("Select a sketch line or a model edge, then click this.")
        self.pick_btn.clicked.connect(self._pick_axis)
        al.addWidget(self.pick_btn)
        root.addWidget(ax)

        d1 = QtWidgets.QGroupBox("Direction 1")
        f1 = QtWidgets.QFormLayout(d1)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(0.01, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setValue(360.0)
        self.angle.setKeyboardTracking(False)
        self.angle.valueChanged.connect(self._apply)
        f1.addRow("Angle", self.angle)
        self.reverse = QtWidgets.QCheckBox("Reverse direction")
        self.reverse.toggled.connect(self._apply)
        f1.addRow("", self.reverse)
        self.midplane = QtWidgets.QCheckBox("Mid plane (half each way)")
        self.midplane.toggled.connect(self._apply)
        f1.addRow("", self.midplane)
        root.addWidget(d1)

        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            "background: rgba(200, 60, 60, 60); border: 1px solid #c04040;"
            " border-radius: 4px; padding: 6px;")
        self.error.hide()
        root.addWidget(self.error)
        root.addStretch(1)
        return w

    def _pick_axis(self):
        for item in Gui.Selection.getSelectionEx():
            for sub in item.SubElementNames:
                if sub.startswith("Edge"):
                    self.picked_axis = (item.Object, [sub])
                    self._loading = True
                    self.axis.setCurrentText(SELECTED)
                    self._loading = False
                    self._apply()
                    return
        QtWidgets.QMessageBox.information(
            self.form, "Axis", "Select a sketch line or a model edge first.")

    # ---- feature <-> UI
    def _load(self):
        f = self.feature
        self._loading = True
        try:
            self.angle.setValue(_value(getattr(f, "Angle", 360.0)) or 360.0)
            self.reverse.setChecked(bool(getattr(f, "Reversed", False)))
            self.midplane.setChecked(bool(getattr(f, "Midplane", False)))
            self.midplane.setVisible(_has(f, "Midplane"))
            ref = getattr(f, "ReferenceAxis", None)
            if ref:
                obj, subs = ref[0], list(ref[1]) if len(ref) > 1 else []
                sub = subs[0] if subs else ""
                matched = False
                for i, (_label, (src, name)) in enumerate(AXES):
                    if (src == "sketch" and obj == self.sketch and sub == name) or \
                            (src == "origin" and obj.Name.startswith(name)):
                        self.axis.setCurrentIndex(i)
                        matched = True
                        break
                if not matched:
                    self.picked_axis = (obj, subs)
                    self.axis.setCurrentText(SELECTED)
        finally:
            self._loading = False

    def _axis_link(self):
        text = self.axis.currentText()
        if text == SELECTED:
            return self.picked_axis
        for label, (src, name) in AXES:
            if label != text:
                continue
            if src == "sketch":
                return (self.sketch, [name])
            origin = getattr(self.body, "Origin", None)
            for o in getattr(origin, "OriginFeatures", []) if origin else []:
                if o.Name.startswith(name) or getattr(o, "Role", "") == name:
                    return (o, [""])
        return None

    def _apply(self, *_):
        if self._loading:
            return
        f = self.feature
        link = self._axis_link()
        if link is not None:
            try:
                f.ReferenceAxis = link
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: couldn't set revolve axis ({e})\n")
        if _has(f, "Type"):
            _set_enum(f, "Type", ["Angle", "Dimension"])
        f.Angle = self.angle.value()
        if _has(f, "Reversed"):
            f.Reversed = self.reverse.isChecked()
        if _has(f, "Midplane"):
            f.Midplane = self.midplane.isChecked()
        try:
            self.doc.recompute()
        except Exception:
            pass
        self._check()

    def _check(self):
        f = self.feature
        try:
            ok = f.isValid() and not f.Shape.isNull()
        except Exception:
            ok = False
        self.failed = not ok
        base = getattr(f, "BaseFeature", None)
        if ok:
            self.error.hide()
            if base is not None and getattr(self, "_base_shown", False):
                base.ViewObject.Visibility = False
                self._base_shown = False
            return
        if base is not None:
            try:
                base.ViewObject.Visibility = True
                self._base_shown = True
            except Exception:
                pass
        self.error.setText(
            "<b>The revolve can't be built.</b> The usual causes: the axis crosses "
            "the sketch outline, the outline isn't closed, or nothing is selected "
            "as the axis.<br>Your model is unchanged - fix this, or press Cancel.")
        self.error.show()

    # ---- task dialog protocol
    def accept(self):
        self._apply()
        if self.failed:
            QtWidgets.QMessageBox.warning(
                self.form, self.form.windowTitle(),
                "This feature can't be built yet - see the message in the panel.")
            return False
        if self.sketch is not None:
            self.sketch.ViewObject.Visibility = False
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        if self.creating and self.sketch is not None:
            self.sketch.ViewObject.Visibility = True
        self.doc.abortTransaction()
        try:
            if self.body is not None and self.body.Tip is not None:
                self.body.Tip.ViewObject.Visibility = True
        except Exception:
            pass
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def create(cut=False):
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Revolve", "Finish the open dialog first.")
        return
    sketch = _selected_sketch()
    if sketch is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Cut-Revolve" if cut else "Revolve",
            "Select the sketch to revolve first (it should include the profile, "
            "and ideally a centreline to revolve around).")
        return
    body = _body_of(sketch)
    if body is None:
        QtWidgets.QMessageBox.warning(
            Gui.getMainWindow(), "Revolve", "That sketch is not inside a Body.")
        return
    doc = sketch.Document
    doc.openTransaction("Cut-Revolve" if cut else "Revolve")
    feat = body.newObject("PartDesign::Groove" if cut else "PartDesign::Revolution",
                          "Groove" if cut else "Revolution")
    feat.Profile = sketch
    try:
        feat.ReferenceAxis = (sketch, ["V_Axis"])
    except Exception:
        pass
    sketch.ViewObject.Visibility = False
    Gui.Control.showDialog(RevolvePanel(feat, sketch, cut, creating=True))


def edit(feature):
    if Gui.Control.activeDialog():
        return
    cut = feature.TypeId == "PartDesign::Groove"
    feature.Document.openTransaction("Edit " + feature.Label)
    profile = getattr(feature, "Profile", None)
    sketch = profile[0] if isinstance(profile, tuple) else profile
    Gui.Control.showDialog(RevolvePanel(feature, sketch, cut, creating=False))
