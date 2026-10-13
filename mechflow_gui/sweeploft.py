# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Swept and Lofted Boss/Base and Cut."""

from mechflow_gui.panel_base import (FeaturePanel, PickField, has, set_enum, open_panel)

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

ORIENT = {"Follow path": ["Standard"], "Keep normal constant": ["Fixed"],
          "Twist free (Frenet)": ["Frenet"]}


def _link_obj(v):
    return v[0] if isinstance(v, (tuple, list)) else v


class SweepPanel(FeaturePanel):
    CUT = False
    TITLE = "Sweep"
    HINT = ("Click the profile sketch, then the path (a sketch or model edges). "
            "The profile should sit at one end of the path.")

    def build(self):
        self.profile = self.add_field(PickField(self, "Profile", ["sketch"], single=True))
        self.path = self.add_field(PickField(self, "Path", ["sketch", "edge"]))
        row = QtWidgets.QFormLayout()
        self.orient = self.combo(list(ORIENT))
        row.addRow("Profile orientation", self.orient)
        self.root.addLayout(row)

    def ready(self):
        return bool(self.profile.items) and bool(self.path.items)

    def load(self, f):
        p = _link_obj(f.Profile)
        if p is not None:
            self.profile.set([(p, "")])
        sp = getattr(f, "Spine", None)
        if sp:
            obj, subs = sp[0], list(sp[1]) or [""]
            self.path.set([(obj, s) for s in subs])
        mode = str(getattr(f, "Mode", "Standard"))
        for k, v in ORIENT.items():
            if mode in v:
                self.orient.setCurrentText(k)

    def make_feature(self):
        t = "PartDesign::SubtractivePipe" if self.CUT else "PartDesign::AdditivePipe"
        f = self.body.newObject(t, "SubtractivePipe" if self.CUT else "AdditivePipe")
        f.Profile = self.profile.items[0][0]
        return f

    def update_feature(self, f):
        f.Profile = self.profile.items[0][0]
        obj = self.path.items[0][0]
        subs = [s for o, s in self.path.items if o is obj and s]
        f.Spine = (obj, subs)
        set_enum(f, "Mode", ORIENT[self.orient.currentText()])

    def finish(self):
        for fld in (self.profile, self.path):
            for o, s in fld.items:
                if o.TypeId == "Sketcher::SketchObject":
                    self._show(o, False)

    def error_text(self):
        return ("<b>The sweep can't be built.</b> Usually the profile isn't at the "
                "start of the path, the path has sharp corners for this profile size, "
                "or the profile isn't a closed outline.")


class CutSweepPanel(SweepPanel):
    CUT = True
    TITLE = "Cut-Sweep"


class LoftPanel(FeaturePanel):
    CUT = False
    TITLE = "Loft"
    HINT = "Click the profile sketches in order, from one end of the loft to the other."

    def build(self):
        self.profiles = self.add_field(PickField(self, "Profiles (in order)", ["sketch"]))
        row = QtWidgets.QFormLayout()
        self.ruled = self.check("Straight (ruled) sides")
        row.addRow("", self.ruled)
        self.closed = self.check("Close loft (back to the first profile)")
        row.addRow("", self.closed)
        self.root.addLayout(row)

    def ready(self):
        return len(self.profiles.items) >= 2

    def load(self, f):
        items = []
        p = _link_obj(f.Profile)
        if p is not None:
            items.append((p, ""))
        for sec in getattr(f, "Sections", []) or []:
            items.append((_link_obj(sec), ""))
        self.profiles.set(items)
        self.ruled.setChecked(bool(getattr(f, "Ruled", False)))
        self.closed.setChecked(bool(getattr(f, "Closed", False)))

    def make_feature(self):
        t = "PartDesign::SubtractiveLoft" if self.CUT else "PartDesign::AdditiveLoft"
        f = self.body.newObject(t, "SubtractiveLoft" if self.CUT else "AdditiveLoft")
        f.Profile = self.profiles.items[0][0]
        return f

    def update_feature(self, f):
        objs = [o for o, _ in self.profiles.items]
        f.Profile = objs[0]
        try:
            f.Sections = [(o, [""]) for o in objs[1:]]
        except Exception:
            f.Sections = objs[1:]
        f.Ruled = self.ruled.isChecked()
        f.Closed = self.closed.isChecked()

    def finish(self):
        for o, _ in self.profiles.items:
            self._show(o, False)

    def error_text(self):
        return ("<b>The loft can't be built.</b> Check every profile is a closed "
                "outline on its own plane, and they're picked in order.")


class CutLoftPanel(LoftPanel):
    CUT = True
    TITLE = "Cut-Loft"


def sweep(feature=None):
    cut = feature is not None and feature.TypeId == "PartDesign::SubtractivePipe"
    open_panel(CutSweepPanel if cut else SweepPanel, feature)


def cut_sweep():
    open_panel(CutSweepPanel)


def loft(feature=None):
    cut = feature is not None and feature.TypeId == "PartDesign::SubtractiveLoft"
    open_panel(CutLoftPanel if cut else LoftPanel, feature)


def cut_loft():
    open_panel(CutLoftPanel)
