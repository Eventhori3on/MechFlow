# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Edit Material.

The material is stored on the body (MechFlowMaterial / MechFlowDensity), so it
is saved with the part and Mass Properties uses it without asking.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

# name: density kg/m^3
MATERIALS = {
    "Plain carbon steel": 7800.0,
    "AISI 1020 steel": 7900.0,
    "Stainless steel 304": 8000.0,
    "Stainless steel 316": 8000.0,
    "Cast iron (grey)": 7200.0,
    "Aluminium 6061-T6": 2700.0,
    "Aluminium 6082-T6": 2700.0,
    "Brass": 8500.0,
    "Copper": 8900.0,
    "Titanium Ti-6Al-4V": 4430.0,
    "ABS": 1050.0,
    "PLA": 1240.0,
    "Nylon 6/6": 1140.0,
    "Acetal (POM)": 1410.0,
    "Polycarbonate": 1200.0,
}

GROUP = "MechFlow"


def _body_for_selection():
    sel = Gui.Selection.getSelection()
    for o in sel:
        if o.TypeId == "PartDesign::Body":
            return o
        try:
            b = o.getParentGeoFeatureGroup()
            if b is not None and b.TypeId == "PartDesign::Body":
                return b
        except Exception:
            pass
    try:
        b = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        if b is not None:
            return b
    except Exception:
        pass
    doc = App.ActiveDocument
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"] if doc else []
    return bodies[0] if len(bodies) == 1 else None


def get(obj):
    """(material name, density kg/m^3) for an object, or (None, None)."""
    body = obj
    if obj is not None and obj.TypeId != "PartDesign::Body":
        try:
            body = obj.getParentGeoFeatureGroup() or obj
        except Exception:
            body = obj
    for o in (body, obj):
        if o is not None and hasattr(o, "MechFlowDensity") and o.MechFlowDensity > 0:
            return getattr(o, "MechFlowMaterial", "") or "Custom", float(o.MechFlowDensity)
    return None, None


def set_material(body, name, density):
    if not hasattr(body, "MechFlowMaterial"):
        body.addProperty("App::PropertyString", "MechFlowMaterial", GROUP, "Material")
    if not hasattr(body, "MechFlowDensity"):
        body.addProperty("App::PropertyFloat", "MechFlowDensity", GROUP,
                         "Density in kg/m^3")
    body.MechFlowMaterial = name
    body.MechFlowDensity = float(density)


class MaterialDialog(QtWidgets.QDialog):
    def __init__(self, body, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Material")
        self.body = body
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(f"Material for <b>{body.Label}</b>:"))
        self.list = QtWidgets.QListWidget()
        for n in list(MATERIALS) + ["Custom..."]:
            self.list.addItem(n)
        lay.addWidget(self.list)
        form = QtWidgets.QFormLayout()
        self.dens = QtWidgets.QDoubleSpinBox()
        self.dens.setRange(1.0, 50000.0)
        self.dens.setDecimals(1)
        self.dens.setSuffix(" kg/m³")
        form.addRow("Density", self.dens)
        self.name = QtWidgets.QLineEdit()
        form.addRow("Name", self.name)
        lay.addLayout(form)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.currentTextChanged.connect(self._picked)
        cur, d = get(body)
        items = self.list.findItems(cur or "Plain carbon steel", QtCore.Qt.MatchExactly)
        if items:
            self.list.setCurrentItem(items[0])
        else:
            self.list.setCurrentRow(self.list.count() - 1)
        if cur:
            self.name.setText(cur)
            self.dens.setValue(d)

    def _picked(self, text):
        custom = text == "Custom..."
        self.name.setEnabled(custom)
        if not custom:
            self.name.setText(text)
            self.dens.setValue(MATERIALS[text])
        else:
            self.name.setText("")
            self.name.setFocus()

    def result_material(self):
        return (self.name.text().strip() or "Custom"), self.dens.value()


def edit():
    body = _body_for_selection()
    if body is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Material",
                                          "Select the part (body) first.")
        return
    dlg = MaterialDialog(body, Gui.getMainWindow())
    if dlg.exec():
        name, d = dlg.result_material()
        doc = body.Document
        doc.openTransaction("Edit Material")
        set_material(body, name, d)
        doc.commitTransaction()
        App.Console.PrintMessage(f"MechFlow: {body.Label} material = {name} ({d:g} kg/m³)\n")
