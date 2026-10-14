# SPDX-License-Identifier: LGPL-2.1-or-later
"""Valves and instruments on a pipe route (SOLIDWORKS Routing's inline
components).

Pick a valve or instrument, click a route's pipe where it goes, and:

- an inline component (valve) splits the pipe: flanged ones get a gasket,
  a weld neck flange and bolts each side (a wafer butterfly valve is
  clamped between two flanges on long bolts); butt-weld ones are welded
  straight to the pipe,
- an instrument (pressure gauge, temperature sensor) sits on the pipe wall,
- the rotate handle turns it round the pipe (the stem, handwheel or dial
  where you want it), with the angle shown and editable in the view; the
  arrow slides it along the pipe, with the distance shown,
- it sizes itself to the route and moves with it when the route changes.

Built-in parts are representative: face-to-face lengths follow EN 558
basic series 1 / ASME B16.10 class 150 (butterfly: EN 558 series 20 /
API 609 category A) and the flanges EN 1092-1 / ASME B16.5 - check
against the valve maker's data. Your own parts go in the library with
Author Component.
"""

import json
import math
import os

import FreeCAD as App
from mechflow_gui import edge_curve, curve_name  # noqa: F401
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector

INLINE = ["Ball valve", "Gate valve", "Globe valve", "Check valve", "Butterfly valve"]
BRANCH = ["Pressure gauge", "Temperature sensor"]
KINDS = INLINE + BRANCH + ["Library part"]

# face to face (mm): EN 558 basic series 1 by DN / ASME B16.10 class 150 by NPS
FTF_EN = {"DN15": 130, "DN20": 150, "DN25": 160, "DN32": 180, "DN40": 200, "DN50": 230,
          "DN65": 290, "DN80": 310, "DN100": 350, "DN125": 400, "DN150": 480, "DN200": 600,
          "DN250": 730, "DN300": 850, "DN350": 980, "DN400": 1100}
FTF_ASME = {"1/2": 108, "3/4": 117, "1": 127, "1 1/4": 140, "1 1/2": 165, "2": 178,
            "2 1/2": 191, "3": 203, "4": 229, "5": 254, "6": 267, "8": 292, "10": 330,
            "12": 356, "14": 381, "16": 406}
# wafer butterfly: EN 558 series 20 / API 609 cat A
WAFER_EN = {"DN40": 33, "DN50": 43, "DN65": 46, "DN80": 46, "DN100": 52, "DN125": 56,
            "DN150": 56, "DN200": 60, "DN250": 68, "DN300": 78, "DN350": 78, "DN400": 102}
WAFER_ASME = {"1 1/2": 33, "2": 43, "2 1/2": 46, "3": 46, "4": 52, "5": 56, "6": 56, "8": 60,
              "10": 68, "12": 78, "14": 78, "16": 102}


def _nps_key(size):
    s = size.replace("NPS", "").replace('"', "").strip()
    return s


def face_to_face(kind, standard, size):
    if kind == "Butterfly valve":
        t = WAFER_EN if standard == "EN" else WAFER_ASME
    else:
        t = FTF_EN if standard == "EN" else FTF_ASME
    key = size if standard == "EN" else _nps_key(size)
    if key in t:
        return float(t[key])
    # outside the table: scale from the nearest pipe size
    from mechflow_gui import routing
    od = routing.fitting_dims(standard, size, "Sch 40", "3D" if standard == "EN" else "LR")[0]
    return round((0.6 if kind == "Butterfly valve" else 3.2) * od + 40, 0)


# ------------------------------------------------------------ shapes (own axes)
# Inline: pipe axis = Z, centre at the origin, ports at z = -L/2 and +L/2,
# stem / handwheel up +Y. Branch: mounting face on the pipe wall at the
# origin, standing out along +Z, pipe running along Y.

def _cyl(r, z0, z1, axis="z", at=V(0, 0, 0)):
    import Part
    d = {"x": V(1, 0, 0), "y": V(0, 1, 0), "z": V(0, 0, 1)}[axis]
    return Part.makeCylinder(r, z1 - z0, at + d * z0, d)


def _flange_end(f, z_face, inward):
    """A flanged valve end: disc with bolt holes, joint face at z_face, the
    flange running inward (+1: towards +z) by its thickness."""
    import Part
    th = f["thick"]
    z0, z1 = (z_face, z_face + th) if inward > 0 else (z_face - th, z_face)
    disc = Part.makeCylinder(f["OD"] / 2, z1 - z0, V(0, 0, z0), V(0, 0, 1))
    holes = []
    for i in range(f["n"]):
        a = 2 * math.pi * (i + 0.5) / f["n"]
        c = V(f["K"] / 2 * math.cos(a), f["K"] / 2 * math.sin(a), z0 - 1)
        holes.append(Part.makeCylinder(f["L"] / 2, z1 - z0 + 2, c, V(0, 0, 1)))
    for h in holes:
        disc = disc.cut(h)
    return disc


def valve_shape(kind, standard, size, rating):
    """(shape, face-to-face length, end type)."""
    import Part
    from mechflow_gui import routing, stdparts
    ty = routing.types_for(standard)
    od, wall = routing.fitting_dims(standard, size, "Sch 40", "3D" if standard == "EN" else "LR")[:2]
    L = face_to_face(kind, standard, size)
    f = stdparts.flange_info(ty["flange"], size, rating or stdparts.default_rating(ty["flange"]))
    D = f["OD"]
    bore = od / 2 - wall
    if kind == "Butterfly valve":
        r_body = (f["K"] - f["L"]) / 2 - 2
        body = _cyl(r_body, -L / 2, L / 2)
        neck = _cyl(0.12 * D, 0, r_body + 0.45 * D, "y")
        box = Part.makeBox(0.5 * D, 0.25 * D, 0.5 * D,
                           V(-0.25 * D, r_body + 0.45 * D, -0.25 * D))
        lever = Part.makeBox(0.08 * D, 0.06 * D, 1.6 * D,
                             V(-0.04 * D, r_body + 0.7 * D, -0.25 * D))
        shape = body.fuse([neck, box, lever])
        shape = shape.cut(_cyl(bore, -L, L))
        disc = _cyl(bore - 1.0, -0.06 * D, 0.06 * D, "z")
        return Part.makeCompound([shape.removeSplitter(), disc]), L, "wafer"
    ends = [_flange_end(f, -L / 2, +1), _flange_end(f, L / 2, -1)]
    th = f["thick"]
    inner = L / 2 - th
    if kind == "Ball valve":
        body = _cyl(0.42 * D, -inner, inner).fuse(Part.makeSphere(0.55 * D))
        stem = _cyl(0.07 * D, 0, 0.85 * D, "y")
        lever = Part.makeBox(0.1 * D, 0.06 * D, 1.9 * D, V(-0.05 * D, 0.85 * D, -0.25 * D))
        parts = [body, stem, lever]
    elif kind == "Gate valve":
        body = _cyl(0.4 * D, -inner, inner).fuse(_cyl(0.48 * D, -0.25 * D, 0.25 * D, "y"))
        bonnet = _cyl(0.22 * D, 0, 1.5 * D, "y")
        yoke = _cyl(0.05 * D, 1.5 * D, 2.1 * D, "y")
        wheel = Part.makeTorus(0.5 * D, 0.035 * D, V(0, 2.1 * D, 0), V(0, 1, 0))
        spokes = Part.makeBox(1.0 * D, 0.04 * D, 0.06 * D, V(-0.5 * D, 2.08 * D, -0.03 * D))
        parts = [body, bonnet, yoke, wheel, spokes]
    elif kind == "Globe valve":
        body = _cyl(0.4 * D, -inner, inner).fuse(Part.makeSphere(0.6 * D))
        bonnet = _cyl(0.2 * D, 0, 1.3 * D, "y")
        stem = _cyl(0.04 * D, 1.3 * D, 1.75 * D, "y")
        wheel = Part.makeTorus(0.4 * D, 0.035 * D, V(0, 1.75 * D, 0), V(0, 1, 0))
        parts = [body, bonnet, stem, wheel]
    elif kind == "Check valve":
        body = _cyl(0.42 * D, -inner, inner).fuse(Part.makeSphere(0.55 * D))
        cover = _cyl(0.38 * D, 0, 0.75 * D, "y")
        lid = _cyl(0.45 * D, 0.7 * D, 0.82 * D, "y")
        arrow = Part.makeCone(0.12 * D, 0, 0.25 * D, V(0, 0.82 * D, 0.1 * D), V(0, 0, 1))
        shaft = _cyl(0.04 * D, -0.25 * D, 0.1 * D, "z", V(0, 0.86 * D, 0))
        parts = [body, cover, lid, arrow, shaft]
    else:
        raise ValueError(f"unknown valve {kind}")
    shape = ends[0].fuse(ends[1:] + parts)
    shape = shape.cut(_cyl(bore, -L, L))
    try:
        shape = shape.removeSplitter()
    except Exception:
        pass
    return shape, L, "flanged"


def instrument_shape(kind):
    import Part
    if kind == "Pressure gauge":
        boss = _cyl(14, -6, 30)
        stem = _cyl(7, 30, 95)
        dial = Part.makeCylinder(50, 28, V(0, -14, 145), V(0, 1, 0))
        rim = Part.makeTorus(50, 3, V(0, 14, 145), V(0, 1, 0))
        glass = Part.makeCylinder(46, 1, V(0, 14, 145), V(0, 1, 0))
        needle = Part.makeBox(3, 2, 38, V(-1.5, 15, 140))
        return Part.makeCompound([boss.fuse([stem, dial, rim]), glass, needle])
    if kind == "Temperature sensor":
        boss = _cyl(16, -6, 30)
        neck = _cyl(8, 30, 120)
        head = _cyl(38, 120, 190)
        cap = _cyl(30, 190, 198)
        gland = _cyl(9, 0, 40, "y", V(0, 38, 160))
        return boss.fuse([neck, head, cap, gland])
    raise ValueError(f"unknown instrument {kind}")


# ------------------------------------------------------------ the object

class InlineComponent:
    def __init__(self, obj, kind):
        obj.addProperty("App::PropertyLink", "Route", "Route component", "The route it is on")
        obj.addProperty("App::PropertyEnumeration", "Kind", "Route component", "What it is")
        obj.Kind = KINDS
        obj.Kind = kind
        obj.addProperty("App::PropertyVector", "Position", "Route component",
                        "Where on the route (the route snaps it onto its pipe)")
        obj.addProperty("App::PropertyAngle", "Angle", "Route component",
                        "Turned round the pipe (0: stem / dial straight up)")
        obj.addProperty("App::PropertyBool", "Reverse", "Route component",
                        "Flow the other way (check valves)")
        obj.addProperty("App::PropertyString", "Standard", "Route component", "EN / ASME", 1)
        obj.addProperty("App::PropertyString", "Size", "Route component", "Follows the route", 1)
        obj.addProperty("App::PropertyString", "Rating", "Route component", "Follows the route", 1)
        obj.addProperty("App::PropertyLength", "FaceToFace", "Route component",
                        "Length along the pipe", 1)
        obj.addProperty("App::PropertyString", "EndType", "Route component",
                        "flanged / wafer / weld / branch", 1)
        obj.addProperty("App::PropertyString", "Library", "Route component",
                        "Library part file (Library part)", 1)
        obj.addProperty("App::PropertyString", "LibraryName", "Route component", "", 1)
        obj.addProperty("Part::PropertyPartShape", "LibraryShape", "Route component", "", 4)
        obj.addProperty("App::PropertyString", "Ports", "Route component", "", 4)
        obj.addProperty("App::PropertyInteger", "MechFlowInstance", "Base", "", 4)
        obj.Proxy = self

    def execute(self, obj):
        try:
            shape, L, end = component_shape(obj)
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: {obj.Label}: {e}\n")
            return
        pl = obj.Placement
        obj.Shape = shape
        obj.Placement = pl
        if abs(float(obj.FaceToFace) - L) > 1e-6:
            obj.FaceToFace = L
        if obj.EndType != end:
            obj.EndType = end
        n = obj.MechFlowInstance
        want = f"{designation(obj)}<{n}>" if n else designation(obj)
        if obj.Label != want and not getattr(obj, "_renamed", False):
            obj.Label = want

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderInlineComponent:
    def __init__(self, vobj):
        vobj.Proxy = self
        try:
            vobj.ShapeColor = (0.80, 0.18, 0.15) if vobj.Object.Kind in INLINE else (0.25, 0.45, 0.75)
        except Exception:
            pass

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        k = getattr(self.Object, "Kind", "")
        return icon_path("Instrument.svg" if k in BRANCH else "Valve.svg")

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.Control.showDialog(InlinePanel(edit=vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_component(o):
    return type(getattr(o, "Proxy", None)).__name__ == "InlineComponent"


def is_branch(o):
    if o.Kind == "Library part":
        try:
            return len(json.loads(o.Ports or "[]")) == 1
        except Exception:
            return False
    return o.Kind in BRANCH


def designation(o):
    if o.Kind == "Library part":
        base = o.LibraryName or "Component"
        return f"{base} {o.Size}".strip() if o.Size and o.Size not in base else base
    if o.Kind in BRANCH:
        return o.Kind
    rating = f" {o.Rating}" if o.Rating else ""
    return f"{o.Kind} {o.Size}{rating}".strip()


def component_shape(o):
    """(shape in the component's own axes, face-to-face, end type)."""
    if o.Kind == "Library part":
        sh = o.LibraryShape
        ports = json.loads(o.Ports or "[]")
        if len(ports) == 2:
            L = abs(ports[1]["point"][2] - ports[0]["point"][2])
            return sh.copy(), L, ports[0].get("end", "flanged")
        return sh.copy(), 0.0, "branch"
    if o.Kind in BRANCH:
        return instrument_shape(o.Kind), 0.0, "branch"
    if not o.Size:
        raise ValueError("not on a route yet")
    return valve_shape(o.Kind, o.Standard or "EN", o.Size, o.Rating)


def ftf_and_end(comp, standard, size):
    """(face-to-face, end type) without building the shape."""
    if comp.Kind == "Library part":
        ports = json.loads(comp.Ports or "[]")
        if len(ports) == 2:
            return abs(ports[1]["point"][2] - ports[0]["point"][2]), ports[0].get("end", "flanged")
        return 0.0, "branch"
    if comp.Kind in BRANCH:
        return 0.0, "branch"
    return face_to_face(comp.Kind, standard, size), (
        "wafer" if comp.Kind == "Butterfly valve" else "flanged")


def nominal_size(standard, rating, dia, end="flanged"):
    """The pipe size a port edge of this diameter belongs to: a flange's
    outside or raised-face diameter (flanged ends; the route's rating
    first, then the others - a part keeps the flanges it was modelled
    with) or the pipe's outside diameter (weld ends). None if nothing
    matches closely."""
    from mechflow_gui import routing, stdparts
    ty = routing.types_for(standard)
    ratings = [rating] + [r for r in stdparts.ratings(ty["flange"]) if r != rating]
    best = None
    for size in routing.sizes_for(standard):
        cands = []
        if end in ("flanged", "wafer"):
            for k, rt in enumerate(ratings):
                try:
                    info = stdparts.flange_info(ty["flange"], size, rt)
                except Exception:
                    continue
                cands += [(info["OD"], 0, k), (info["face"], 1, k)]
        try:
            cands.append((routing.fitting_dims(standard, size, "Sch 40",
                                               routing.BENDS[standard][0])[0],
                          0 if end not in ("flanged", "wafer") else 2, 0))
        except Exception:
            pass
        for d_, pref, k in cands:
            rel = abs(d_ - dia) / max(d_, 1e-6)
            key = (rel > 0.005, pref, k > 0, rel)
            if best is None or key < best[0]:
                best = (key, size)
    if best is None or best[0][3] > 0.04:
        return None
    return best[1]


def port_sizes(comp, standard, rating):
    """(port A size, port B size) of a library part with two ports whose
    diameters match standard sizes - so the route can check the pipe it
    sits in and change size after it - else None (it follows the pipe)."""
    if getattr(comp, "Kind", "") != "Library part":
        return None
    try:
        ports = json.loads(comp.Ports or "[]")
    except Exception:
        return None
    if len(ports) != 2 or not all(p.get("dia") for p in ports):
        return None
    sizes = [nominal_size(standard, rating, float(p["dia"]), p.get("end", "flanged")) for p in ports]
    if None in sizes:
        return None
    return sizes[0], sizes[1]


class PortFlange:
    """A component's flanged end, seen as a flange for bolting (bolt holes
    found on the component itself)."""

    def __init__(self, comp, flange_t, size, rating):
        self.obj, self.prefix = comp, ""
        self.StdType, self.Size, self.Rating = flange_t, size, rating
        self.Placement = comp.Placement
        self.Shape = comp.Shape
        self.Document = comp.Document
        self.Label = comp.Label


def components_of(route):
    return [o for o in route.Document.Objects if is_component(o) and o.Route is route]


def make(container, kind, route=None, position=None, angle=0.0, library=None):
    from mechflow_gui import toolbox
    doc = route.Document if route is not None else (
        container.Document if container is not None else App.ActiveDocument)
    o = doc.addObject("Part::FeaturePython", "Component")
    InlineComponent(o, kind if kind in KINDS else "Library part")
    if container is not None:
        container.addObject(o)
    if library is not None:
        load_library_item(o, library)
    if route is not None:
        o.Route = route
        o.Standard, o.Size, o.Rating = route.Standard, route.Size, route.FlangeRating
    if position is not None:
        o.Position = position
    o.Angle = angle
    if App.GuiUp:
        ViewProviderInlineComponent(o.ViewObject)
    o.MechFlowInstance = int(toolbox.instance_label(doc, designation(o)).rsplit("<", 1)[1][:-1])
    return o


# ------------------------------------------------------------ on the route

def placement_for(comp, centre, d, od):
    """Where a component goes for a run direction d (unit) through centre."""
    from mechflow_gui import routing
    up0 = V(0, 0, 1) - d * d.z
    if up0.Length < 1e-6:                  # vertical pipe: angle 0 faces +X
        up0 = V(1, 0, 0) - d * d.x
    up0.normalize()
    up = App.Rotation(d, float(comp.Angle)).multVec(up0)
    if is_branch(comp):
        # stands out of the wall along `up`, its own Y along the pipe
        rot = routing._rot(up, up.cross(d) * -1)
        return App.Placement(centre + up * (od / 2), rot)
    z = d * (-1 if comp.Reverse else 1)
    rot = routing._rot(z, up.cross(z))
    return App.Placement(centre, rot)


def joint_length(comp, flange_t, size, rating, gasket_t):
    """How much of the run the component and its joints take each side of
    its centre: (half length incl. joints, gasket thickness, flange length)."""
    from mechflow_gui import stdparts
    L = float(comp.FaceToFace)
    if comp.EndType in ("flanged", "wafer"):
        g = stdparts.gasket_dims(gasket_t, size, rating)[2]
        H = stdparts._length_in_part(flange_t, size, rating)
        return L / 2 + g + H, g, H
    return L / 2, 0.0, 0.0


# ------------------------------------------------------------ library

def library_dir():
    d = os.environ.get("MF_ROUTING_LIBRARY") or \
        os.path.join(App.getUserAppDataDir(), "MechFlow Routing Library")
    os.makedirs(d, exist_ok=True)
    return d


def library_items():
    """[(name, path, info)] of authored components."""
    out = []
    d = library_dir()
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith(".json"):
            try:
                info = json.load(open(os.path.join(d, fn), encoding="utf-8"))
                out.append((info["name"], os.path.join(d, fn), info))
            except Exception:
                continue
    return out


def load_library_item(o, path):
    import Part
    info = json.load(open(path, encoding="utf-8"))
    sh = Part.Shape()
    sh.importBrep(os.path.join(os.path.dirname(path), info["brep"]))
    o.Kind = "Library part"
    o.LibraryShape = sh
    o.Ports = json.dumps(info["ports"])
    o.Library = path
    o.LibraryName = info["name"]


# ------------------------------------------------------------ panel

class InlinePanel:
    """Pick a component, click a route pipe to put it there; turn and slide
    it with the handles (or the boxes)."""

    def __init__(self, edit=None):
        self.comp = edit
        self.doc = edit.Document if edit else App.ActiveDocument
        self.doc.openTransaction("Valves and Instruments")
        self.form = self._build()
        self.disc = self.dbox = None
        self.arrow = None
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._settle = QtCore.QTimer()
        self._settle.setSingleShot(True)
        self._settle.setInterval(200)
        self._settle.timeout.connect(self._rebuild)
        self._good = None
        if edit is not None:
            self._load(edit)
            self._good = (V(edit.Position), float(edit.Angle), edit.Reverse)
        Gui.Selection.clearSelection()
        self._timer.start()
        self._show_handles()

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Valves and Instruments")
        lay = QtWidgets.QVBoxLayout(w)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(170)
        for k in INLINE + BRANCH:
            self.list.addItem(k)
        for name, path, info in library_items():
            it = QtWidgets.QListWidgetItem(f"{name}  (library)")
            it.setData(QtCore.Qt.UserRole, path)
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        lay.addWidget(self.list)
        self.swap = QtWidgets.QPushButton("Change the selected one to this")
        self.swap.clicked.connect(self._kind_changed)
        self.swap.setEnabled(False)
        lay.addWidget(self.swap)
        f = QtWidgets.QFormLayout()
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setDecimals(1)
        self.angle.setSingleStep(15)
        self.angle.setSuffix(" °")
        self.angle.setWrapping(True)
        self.angle.valueChanged.connect(self._changed)
        from .sketch3d import keep_enter
        keep_enter(self.angle)
        f.addRow("Turn round the pipe", self.angle)
        self.along = QtWidgets.QDoubleSpinBox()
        self.along.setRange(0, 1e6)
        self.along.setDecimals(1)
        self.along.setSuffix(" mm")
        self.along.setKeyboardTracking(False)
        self.along.valueChanged.connect(self._along_changed)
        keep_enter(self.along)
        f.addRow("From the start of the pipe", self.along)
        self.reverse = QtWidgets.QCheckBox("Flow the other way")
        self.reverse.toggled.connect(self._changed)
        f.addRow("", self.reverse)
        lay.addLayout(f)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        self._refresh_msg()
        return w

    def _refresh_msg(self):
        if hasattr(self, "swap"):
            self.swap.setEnabled(self.comp is not None)
        if self.comp is None:
            self.msg.setText("<b>Pick a valve or instrument, then click a route's pipe</b> "
                             "where it goes. It sizes itself to the pipe.")
        else:
            self.msg.setText(f"<b>{self.comp.Label}</b>: drag the ring to turn it round the "
                             "pipe and the arrow to slide it along (or type below). Click "
                             "another pipe to add another.")

    def _load(self, c):
        self.angle.blockSignals(True)
        self.angle.setValue(float(c.Angle))
        self.angle.blockSignals(False)
        self.reverse.blockSignals(True)
        self.reverse.setChecked(c.Reverse)
        self.reverse.blockSignals(False)
        self._sync_along()
        self._refresh_msg()

    def _choice(self):
        it = self.list.currentItem()
        if it is None:
            return INLINE[0], None
        path = it.data(QtCore.Qt.UserRole)
        return (it.text(), None) if not path else ("Library part", path)

    def _kind_changed(self, *_):
        if self.comp is None:
            return
        kind, path = self._choice()
        if kind == "Library part":
            load_library_item(self.comp, path)
        else:
            self.comp.Kind = kind
        from mechflow_gui import toolbox
        self.comp.MechFlowInstance = 0
        self.comp.MechFlowInstance = int(toolbox.instance_label(
            self.comp.Document, designation(self.comp)).rsplit("<", 1)[1][:-1])
        self._rebuild()
        self._refresh_msg()

    # -- placing
    def _tick(self):
        from mechflow_gui import widget_alive
        if not widget_alive(self.form):
            # the panel went without OK / Cancel (its document closed...):
            # don't leave the handles and number boxes behind
            self._timer.stop()
            self._settle.stop()
            self._hide_handles()
            return
        try:
            sel = Gui.Selection.getSelectionEx("", 0)
        except Exception:
            sel = []
        if sel:
            Gui.Selection.clearSelection()
            for s in sel:
                if self._clicked(s):
                    break
        self._follow_handles()

    def _clicked(self, s):
        """A click on a route part: put a new component there."""
        from mechflow_gui import routing
        obj = s.Object
        target = obj
        for sub in (s.SubElementNames or [""]):
            if "." in sub:
                try:
                    target = obj.getSubObjectList(sub)[-1]
                except Exception:
                    pass
        rname = getattr(target, "MechFlowRoute", None)
        route = target.Document.getObject(rname) if rname else None
        if route is None or not routing.is_route(route):
            if is_component(target):
                self._select(target)
                return True
            self.error.setText("Click a pipe of a route (made with Route Pipe).")
            self.error.show()
            return False
        pts = s.PickedPoints
        if not pts:
            return False
        gp = V(pts[0])
        c = routing._container(route)
        local = c.getGlobalPlacement().inverse().multVec(gp) if c is not None else gp
        kind, path = self._choice()
        comp = make(c, kind, route, local, self.angle.value(), library=path)
        comp.Reverse = self.reverse.isChecked()
        self.comp = comp
        self._good = None
        self._rebuild()
        self._refresh_msg()
        self._show_handles()
        return True

    def place_at(self, route, point, kind=None, library=None):
        """Add a component at a point (container axes) - also for tests."""
        from mechflow_gui import routing
        c = routing._container(route)
        k = kind or self._choice()[0]
        comp = make(c, k, route, point, self.angle.value(), library=library)
        self.comp = comp
        self._good = None
        self._rebuild()
        self._refresh_msg()
        self._show_handles()
        return comp

    def _select(self, comp):
        self.comp = comp
        self._good = (V(comp.Position), float(comp.Angle), comp.Reverse)
        self._load(comp)
        self._show_handles()

    def _changed(self, *_):
        if self.comp is None:
            return
        self.comp.Angle = self.angle.value()
        self.comp.Reverse = self.reverse.isChecked()
        self._settle.start()

    def _along_changed(self, v):
        if self.comp is None:
            return
        run = run_of(self.comp)
        if run is None:
            return
        a, d, L = run
        self.comp.Position = a + d * max(0.0, min(L, v))
        self._settle.start()

    def _sync_along(self):
        run = run_of(self.comp) if self.comp is not None else None
        if run is None:
            return
        a, d, L = run
        s = (V(self.comp.Position) - a).dot(d)
        self.along.blockSignals(True)
        self.along.setRange(0, L)
        self.along.setValue(s)
        self.along.blockSignals(False)

    def _rebuild(self):
        from mechflow_gui import routing
        if self.comp is None or self.comp.Route is None:
            return
        c = self.comp
        try:
            if c.Document.getObject(c.Name) is not c:
                return
        except Exception:
            return
        if routing._BUILDING[0]:
            self._settle.start()            # a build is running: try again after it
            return
        try:
            routing.build(c.Route)
            self.error.hide()
            self._good = (V(c.Position), float(c.Angle), c.Reverse)
        except Exception as e:
            self.error.setText(f"<b>Can't place it there:</b> {e}")
            self.error.show()
            good = getattr(self, "_good", None)
            if good is not None and good[0] is not None:
                # put it back where it fitted, so the route stays whole
                c.Position, c.Angle, c.Reverse = good
                try:
                    routing.build(c.Route)
                except Exception as e2:
                    App.Console.PrintWarning(f"MechFlow: {c.Route.Label} not rebuilt ({e2})\n")
            elif good is None:
                # a new one that doesn't fit anywhere here: take it off again
                r = c.Route
                c.Document.removeObject(c.Name)
                self.comp = None
                try:
                    routing.build(r)
                except Exception:
                    pass
                self._refresh_msg()
                self._hide_handles()
                return
        self._sync_along()
        self._show_handles()

    # -- handles
    def _show_handles(self):
        from mechflow_gui import view_handles as vh
        self._hide_handles()
        c = self.comp
        if c is None or c.Route is None:
            return
        run = run_of(c)
        if run is None:
            return
        a, d, L = run
        cont = c.getParentGeoFeatureGroup()
        gpl = cont.getGlobalPlacement() if cont is not None else App.Placement()
        centre = gpl.multVec(V(c.Position))
        dg = gpl.Rotation.multVec(d)
        size = max(80.0, float(c.FaceToFace) or 150.0)
        try:
            self.disc = vh.Disc(centre, dg, float(c.Angle), size * 0.9)
            self.dbox = vh.ViewBox(" °", -180, 180, 1)
            self.dbox.set_quiet(float(c.Angle))
            self.dbox.valueChanged.connect(lambda v: self.angle.setValue(v))
            # the arrow sits beside the part, on the camera's side (kept there
            # as the view turns): on the centreline it'd be inside the body, and
            # a click there picks the valve or the pipe instead of the arrow
            self._arrow_frame = (centre, dg, 0.6 * size)
            self.arrow = vh.Arrow(self._arrow_place(), dg, 0.0, size * 0.6)
            self.abox = vh.ViewBox(" mm", 0, 1e6, 1)
            self.abox.set_quiet(self.along.value())
            self.abox.valueChanged.connect(lambda v: self.along.setValue(v))
            self._arrow_base = self.along.value()
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: handles not shown ({e})\n")

    def _arrow_place(self):
        """Where the slide arrow goes: beside the pipe, towards the camera."""
        centre, dg, off = self._arrow_frame
        try:
            t = V(Gui.ActiveDocument.ActiveView.getViewDirection()) * -1.0
        except Exception:
            t = V(0, 0, 1)
        t = t - dg * t.dot(dg)
        if t.Length < 0.2:                    # looking along the pipe
            t = dg.cross(V(0, 0, 1))
            if t.Length < 1e-6:
                t = dg.cross(V(1, 0, 0))
        return centre + t.normalize() * off

    def _hide_handles(self):
        for h in ("disc", "dbox", "arrow", "abox"):
            x = getattr(self, h, None)
            if x is not None:
                try:
                    x.remove()
                except Exception:
                    pass
            setattr(self, h, None)

    def _follow_handles(self):
        try:
            if self.disc is not None:
                a = self.disc.moved()
                if a is not None:
                    a = round(a / 5.0) * 5.0               # 5 degree steps when dragged
                    self.angle.setValue(a)
                    self.dbox.set_quiet(a)
                self.dbox.place(self.disc.label_point())
            if self.arrow is not None:
                self.arrow.move_origin(self._arrow_place())
                d = self.arrow.moved()
                if d is not None:
                    self.along.setValue(self._arrow_base + round(d / 5.0) * 5.0)
                self.abox.set_quiet(self.along.value())
                self.abox.place(self.arrow.tip(), dy=14)
        except Exception as e:
            if not getattr(self, "_follow_warned", False):
                self._follow_warned = True
                App.Console.PrintWarning(f"MechFlow: handles: {e}\n")

    # -- finish
    def accept(self):
        self._timer.stop()
        self._settle.stop()
        self._hide_handles()
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._timer.stop()
        self._settle.stop()
        self._hide_handles()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def run_of(comp):
    """(start point, direction, length) of the straight run comp is on
    (container axes), in flow order (from the route's start)."""
    from mechflow_gui import routing
    r = comp.Route
    if r is None:
        return None
    try:
        roots = []
        import Part
        for x, subs in r.StartFlanges:
            for sub in subs:
                try:
                    e = Part.getShape(x, sub, needSubElement=True, noElementMap=True)
                    roots.append(V(e.Curve.Center))
                except Exception:
                    pass
        fl = routing.Flow(routing.path_segments_keyed(routing.path_links(r)), roots)
    except Exception:
        return None
    p = V(comp.Position)
    best = None
    for run in fl.runs:
        a, d, L = run["a"], run["d"], run["L"]
        s = max(0.0, min(L, (p - a).dot(d)))
        dist = (a + d * s - p).Length
        if best is None or dist < best[0]:
            best = (dist, a, d, L)
    return None if best is None else best[1:]


def valves_and_instruments():
    if App.ActiveDocument is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Valves and Instruments",
                                          "Finish the open dialog first.")
        return None
    from mechflow_gui import routing
    routing.install()
    sel = [s for s in Gui.Selection.getSelection() if is_component(s)]
    p = InlinePanel(edit=sel[0] if sel else None)
    Gui.Control.showDialog(p)
    return p


# ------------------------------------------------------------ Author Component

def normalise(shape, ports):
    """Shape and ports in a library item's own axes, from picked port
    frames [(centre, axis)] in the model: two ports - pipe axis Z through
    both, centre at the origin, up (+Y) towards the model's +Z; one port -
    mounting face at the origin, standing out along +Z."""
    if len(ports) == 2:
        (c1, _a1), (c2, _a2) = ports
        d = c2 - c1
        L = d.Length
        if L < 1e-6:
            raise ValueError("the two ports are in the same place")
        d.normalize()
        up = V(0, 0, 1) - d * d.z
        if up.Length < 1e-6:
            up = V(1, 0, 0) - d * d.x
        up.normalize()
        x = up.cross(d)
        m = (c1 + c2) * 0.5
        frame = App.Placement(m, App.Rotation(x, up, d, "ZYX"))
        local = shape.copy()
        local.transformShape(frame.inverse().toMatrix())
        return local, [{"name": "A", "point": [0, 0, -L / 2], "dir": [0, 0, -1]},
                       {"name": "B", "point": [0, 0, L / 2], "dir": [0, 0, 1]}]
    if len(ports) == 1:
        c, a = ports[0]
        a = V(a)
        a.normalize()
        # the part stands out on the side away from the pipe
        if (shape.BoundBox.Center - c).dot(a) < 0:
            a = a * -1
        y = V(0, 1, 0) - a * a.y
        if y.Length < 1e-6:
            y = V(1, 0, 0) - a * a.x
        y.normalize()
        x = y.cross(a)
        frame = App.Placement(c, App.Rotation(x, y, a, "ZYX"))
        local = shape.copy()
        local.transformShape(frame.inverse().toMatrix())
        return local, [{"name": "A", "point": [0, 0, 0], "dir": [0, 0, -1]}]
    raise ValueError("pick one port (an instrument) or two (an inline part)")


def save_library_item(name, shape, ports, end="flanged", category="Valve", port_dia=None):
    """Write a library item (BREP + JSON). Returns the JSON path."""
    import re
    d = library_dir()
    safe = re.sub(r'[<>:"/\\|?*]+', "-", name).strip(" .") or "Component"
    local, pts = normalise(shape, ports)
    dias = port_dia if isinstance(port_dia, (list, tuple)) else [port_dia] * len(pts)
    for p, dia in zip(pts, dias):
        p["end"] = end if len(pts) == 2 else "branch"
        if dia:
            p["dia"] = round(dia, 2)
    brep = safe + ".brep"
    local.exportBrep(os.path.join(d, brep))
    info = {"name": name, "category": category, "ports": pts, "brep": brep,
            "ftf": abs(pts[1]["point"][2] - pts[0]["point"][2]) if len(pts) == 2 else 0.0}
    path = os.path.join(d, safe + ".json")
    json.dump(info, open(path, "w", encoding="utf-8"), indent=1)
    return path


class AuthorPanel:
    """Author Component: turn a part into a routing library item by
    clicking its port edges."""

    def __init__(self):
        self.doc = App.ActiveDocument
        self.ports = []                 # [(obj, sub, centre, axis, diameter)]
        self.form = self._build()
        Gui.Selection.clearSelection()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._refresh()

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Author Component")
        lay = QtWidgets.QVBoxLayout(w)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(80)
        lay.addWidget(self.list)
        clr = QtWidgets.QPushButton("Clear ports")
        clr.clicked.connect(self._clear)
        lay.addWidget(clr)
        f = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit(self.doc.Label if self.doc else "Component")
        f.addRow("Name", self.name)
        self.cat = QtWidgets.QComboBox()
        self.cat.addItems(["Valve", "Instrument", "Fitting", "Other"])
        f.addRow("Kind", self.cat)
        self.end = QtWidgets.QComboBox()
        self.end.addItems(["Flanged (gasket, flange and bolts each side)",
                           "Butt weld (pipe welded straight on)"])
        f.addRow("Ends", self.end)
        lay.addLayout(f)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        return w

    def _refresh(self):
        n = len(self.ports)
        self.msg.setText(
            "<b>Click the port edges</b> of the part: for a valve or other inline part the "
            "two round edges where the pipe joins (flange faces or pipe ends), for an "
            "instrument the one round edge it mounts on. Then name it and press OK to put it "
            f"in the routing library.<br><br>Ports picked: <b>{n}</b>")
        self.list.clear()
        for k, (o, s, c, a, dia) in enumerate(self.ports):
            self.list.addItem(f"Port {'AB'[k] if k < 2 else k + 1}: {o.Label} {s.rsplit('.', 1)[-1]} "
                              f"(Ø{dia:.1f})")
        self.end.setEnabled(n != 1)

    def _clear(self):
        self.ports = []
        self._refresh()

    def _poll(self):
        try:
            sel = Gui.Selection.getSelectionEx("", 0)
        except Exception:
            return
        if not sel:
            return
        Gui.Selection.clearSelection()
        for s in sel:
            for sub in s.SubElementNames:
                self.add_port(s.Object, sub)

    def add_port(self, obj, sub):
        import Part
        try:
            e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
        except Exception:
            return False
        if curve_name(e) != "Circle":
            self.error.setText("Pick round edges (a flange face or pipe end).")
            self.error.show()
            return False
        if len(self.ports) >= 2:
            self.error.setText("Two ports at most - Clear ports to start again.")
            self.error.show()
            return False
        self.error.hide()
        self.ports.append((obj, sub, V(e.Curve.Center), V(e.Curve.Axis), 2 * e.Curve.Radius))
        self._refresh()
        return True

    def _shape(self):
        """The part the ports are on (its whole visible solid)."""
        import Part
        tops = []
        for o, s, *_r in self.ports:
            top = o
            if "." in s:
                try:
                    top = o.getSubObjectList(s)[0]
                except Exception:
                    pass
            if top not in tops:
                tops.append(top)
        shapes = [Part.getShape(t) for t in tops]
        return shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)

    def save(self):
        if not self.ports:
            raise ValueError("pick the port edges first")
        ports = [(c, a) for _o, _s, c, a, _d in self.ports]
        end = "weld" if self.end.currentIndex() == 1 else "flanged"
        return save_library_item(self.name.text().strip() or "Component", self._shape(), ports,
                                 end, self.cat.currentText(), [p[4] for p in self.ports])

    def accept(self):
        try:
            path = self.save()
        except Exception as e:
            self.error.setText(f"<b>Not saved:</b> {e}")
            self.error.show()
            return False
        name = self.name.text().strip() or "Component"
        self._timer.stop()
        Gui.Control.closeDialog()
        App.Console.PrintMessage(f"MechFlow: {name} added to the routing library "
                                 f"({path})\n")
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Author Component",
            f"{name} is in the routing library.\n\nPlace it with Valves and "
            "Instruments: it's at the bottom of the list.")
        return True

    def reject(self):
        self._timer.stop()
        Gui.Control.closeDialog()
        return True


def author_component():
    if App.ActiveDocument is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Author Component",
                                          "Open the part (valve, instrument...) first.")
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Author Component",
                                          "Finish the open dialog first.")
        return None
    p = AuthorPanel()
    Gui.Control.showDialog(p)
    return p
