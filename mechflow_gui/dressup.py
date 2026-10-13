# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Shell and Draft."""

from mechflow_gui.panel_base import (FeaturePanel, PickField, BaseFaceField, has,
                                     set_enum, open_panel, face_on)

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets


def _value(q):
    return getattr(q, "Value", q)


class ShellPanel(FeaturePanel):
    TITLE = "Shell"
    HINT = "Click the faces to remove (the open side). The rest becomes the wall."

    def build(self):
        row = QtWidgets.QFormLayout()
        self.thick = self.spin(" mm", 0.01, 1e5, 1.0)
        row.addRow("Thickness", self.thick)
        self.outward = self.check("Shell outward")
        row.addRow("", self.outward)
        self.root.addLayout(row)
        self.faces = self.add_field(BaseFaceField(self, "Faces to Remove", ["face"]))

    def ready(self):
        return bool(self.faces.items)

    def load(self, f):
        base = f.Base[0] if f.Base else self.base
        self.faces.set([(base, s) for s in (f.Base[1] if f.Base else [])])
        self.thick.setValue(_value(f.Value))
        # FreeCAD: Reversed = False grows the wall outward.
        self.outward.setChecked(not bool(getattr(f, "Reversed", True)))

    def make_feature(self):
        return self.body.newObject("PartDesign::Thickness", "Thickness")

    def update_feature(self, f):
        f.Base = (self.base, [s for _, s in self.faces.items])
        f.Value = self.thick.value()
        if has(f, "Reversed"):
            # FreeCAD: Reversed = True hollows inward (SOLIDWORKS' default).
            f.Reversed = not self.outward.isChecked()
        if has(f, "Join"):
            set_enum(f, "Join", ["Intersection", "Arc"])

    def error_text(self):
        return ("<b>The shell can't be built.</b> The wall may be too thick for a "
                "thin part or a small fillet - try a thinner wall.")


class DraftPanel(FeaturePanel):
    TITLE = "Draft"
    HINT = "Click the neutral plane (the face that keeps its size), then the faces to draft."

    def build(self):
        row = QtWidgets.QFormLayout()
        self.angle = self.spin("°", 0.01, 89.0, 1.0)
        row.addRow("Draft angle", self.angle)
        self.reverse = self.check("Reverse direction")
        row.addRow("", self.reverse)
        self.root.addLayout(row)
        self.neutral = self.add_field(PickField(self, "Neutral Plane", ["plane"],
                                                single=True))
        self.faces = self.add_field(BaseFaceField(self, "Faces to Draft", ["face"]))

    def ready(self):
        return bool(self.faces.items) and bool(self.neutral.items)

    def load(self, f):
        base = f.Base[0] if f.Base else self.base
        self.faces.set([(base, s) for s in (f.Base[1] if f.Base else [])])
        n = getattr(f, "NeutralPlane", None)
        if n:
            self.neutral.set([(n[0], (list(n[1]) or [""])[0])])
        self.angle.setValue(_value(f.Angle))
        self.reverse.setChecked(bool(getattr(f, "Reversed", False)))

    def make_feature(self):
        return self.body.newObject("PartDesign::Draft", "Draft")

    def update_feature(self, f):
        f.Base = (self.base, [s for _, s in self.faces.items])
        obj, sub = self.neutral.items[0]
        if obj is not self.base and obj.isDerivedFrom("PartDesign::Feature") and sub:
            # A face clicked on the preview: refer to the original solid.
            name = face_on(self.base.Shape, obj.Shape.getElement(sub))
            if name:
                obj, sub = self.base, name
        f.NeutralPlane = (obj, [sub] if sub else [""])
        f.Angle = self.angle.value()
        f.Reversed = self.reverse.isChecked()

    def error_text(self):
        return ("<b>The draft can't be built.</b> Check the neutral plane is flat and "
                "the faces to draft touch it, or try a smaller angle.")


def shell(feature=None):
    open_panel(ShellPanel, feature)


def draft(feature=None):
    open_panel(DraftPanel, feature)
