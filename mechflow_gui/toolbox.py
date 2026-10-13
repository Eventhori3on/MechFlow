# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Toolbox: standard fasteners, placed in holes.

Built on the free Fasteners Workbench (installed separately through the
Addon Manager; MechFlow only calls it). Pick a fastener (ISO, DIN, EN, ASME
...), click the hole edges - or a face, for all its holes - and MechFlow:

- sizes each fastener to its hole: clearance holes (ISO 273 fine / medium /
  coarse) and tapped holes (tapping drill) are recognised, so an M8 screw
  goes in a 9 mm hole and in a 6.8 mm tapped hole;
- seats it: on the counterbore floor, on top of a plain hole, or in the
  countersink for countersunk screws;
- picks a standard length from the hole depth and what the screw ends in
  (a tapped part, a washer and nut, or flush);
- optionally adds a washer under the head, and a washer + nut on the far side;
- names it by its standard ("ISO 4762 M8x25") for the Bill of Materials.

Each fastener stays attached to its hole edge, so it moves with the part.
"""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"

# Metric sizes: nominal d, pitch, tapping drill, ISO 273 clearance fine/medium/coarse
METRIC = {
    "M2": (2.0, 0.4, 1.6, 2.2, 2.4, 2.6),
    "M2.5": (2.5, 0.45, 2.05, 2.7, 2.9, 3.1),
    "M3": (3.0, 0.5, 2.5, 3.2, 3.4, 3.6),
    "M4": (4.0, 0.7, 3.3, 4.3, 4.5, 4.8),
    "M5": (5.0, 0.8, 4.2, 5.3, 5.5, 5.8),
    "M6": (6.0, 1.0, 5.0, 6.4, 6.6, 7.0),
    "M8": (8.0, 1.25, 6.8, 8.4, 9.0, 10.0),
    "M10": (10.0, 1.5, 8.5, 10.5, 11.0, 12.0),
    "M12": (12.0, 1.75, 10.2, 13.0, 13.5, 14.5),
    "M14": (14.0, 2.0, 12.0, 15.0, 15.5, 16.5),
    "M16": (16.0, 2.0, 14.0, 17.0, 17.5, 18.5),
    "M20": (20.0, 2.5, 17.5, 21.0, 22.0, 24.0),
    "M24": (24.0, 3.0, 21.0, 25.0, 26.0, 28.0),
    "M30": (30.0, 3.5, 26.5, 31.0, 33.0, 35.0),
}
TOL = 0.06    # mm, matching hole diameters to the tables

# Fasteners Workbench groups -> SOLIDWORKS Toolbox categories
CATEGORY_GROUPS = [
    ("Bolts and Screws", ["Hex head", "Hexagon socket", "Hexalobular socket", "Slotted",
                          "H cross", "Misc head", "Thumb screws"]),
    ("Set Screws", ["Grub/Set screws"]),
    ("Nuts", ["Nut"]),
    ("Washers", ["Washer"]),
    ("Pins", ["Pins"]),
    ("Threaded Rods", ["ThreadedRod"]),
    ("Inserts", ["Inserts"]),
    ("Retaining Rings", ["Retaining Rings"]),
    ("T-Slot", ["T-Slot Fasteners"]),
    ("Other", ["Nails", "EJOT PT WN14xx Screws for plastic", "Ground screws"]),
]
STANDARDS = ["ISO", "DIN", "EN", "ASME", "SAE", "GOST", "Other"]
COUNTERSUNK = ("ISO10642", "ISO2009", "ISO2010", "ISO7046", "ISO7047", "ISO14581",
               "ISO14582", "ISO14584", "DIN7997", "ASMEB18.3.2", "ASMEB18.6.3.1A",
               "ASMEB18.6.3.4A", "ASMEB18.6.1.2", "ASMEB18.6.1.4")
NUT, WASHER = "ISO4032", "ISO7089"
ENDS = ["Tapped part (1.5 x d)", "Washer and nut", "Flush with the hole"]


# ------------------------------------------------------------ the workbench

def fasteners():
    """(FastenersCmd, ScrewMaker instance) or None if not installed."""
    try:
        import FastenersCmd
        return FastenersCmd
    except Exception:
        return None


def offer_install():
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setWindowTitle("Toolbox")
    box.setText("The Toolbox uses the free <b>Fasteners Workbench</b> for its standard "
                "parts (ISO, DIN, ASME screws, nuts, washers, pins...).<br><br>"
                "Install it from the Addon Manager: search for <b>Fasteners</b>, "
                "click Install, then restart FreeCAD.")
    open_btn = box.addButton("Open Addon Manager", QtWidgets.QMessageBox.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.exec()
    if box.clickedButton() is open_btn:
        try:
            Gui.runCommand("Std_AddonMgr", 0)
        except Exception:
            pass


def standard_of(ftype):
    for s in STANDARDS[:-1]:
        if ftype.upper().startswith(s):
            return s
    return "Other"


def pretty(ftype):
    """'ISO4762' -> 'ISO 4762', 'ASMEB18.3.1A' -> 'ASME B18.3.1A'."""
    from mechflow_gui import stdparts
    if stdparts.is_std(ftype):
        return ""
    for s in ("ASME", "ISO", "DIN", "EN", "SAE", "GOST"):
        if ftype.startswith(s):
            return f"{s} {ftype[len(s):]}"
    return ftype


def catalog(standard=None):
    """[(category, [(type, description)])]: fasteners from the Fasteners
    Workbench (when installed), then MechFlow's flanges, pipe, fittings and
    bearings."""
    from mechflow_gui import stdparts
    FC = fasteners()
    if FC is None:
        return stdparts.catalog(standard)
    table = FC.FSScrewCommandTable
    out = []
    for cat, groups in CATEGORY_GROUPS:
        items = []
        for t, row in table.items():
            if row[1] in groups and (standard in (None, "All") or standard_of(t) == standard):
                items.append((t, row[0]))
        items.sort(key=lambda i: i[0])
        if items:
            out.append((cat, items))
    return out + stdparts.catalog(standard)


def icon(ftype):
    from mechflow_gui import stdparts, icon_path
    if stdparts.is_std(ftype):
        cat = stdparts.TYPES[ftype][0]
        return QtGui.QIcon(icon_path({"Flanges": "Flange.svg", "Bearings": "Bearing.svg"}.get(
            cat, "Pipe.svg")))
    FC = fasteners()
    if FC is None:
        return QtGui.QIcon()
    path = os.path.join(os.path.dirname(FC.__file__), "Icons", ftype + ".svg")
    return QtGui.QIcon(path) if os.path.exists(path) else QtGui.QIcon()


def diameters(ftype):
    FC = fasteners()
    try:
        return list(FC.screwMaker.GetAllDiams(ftype))
    except Exception:
        return []


def lengths(ftype, diam):
    FC = fasteners()
    try:
        return [l for l in FC.screwMaker.GetAllLengths(ftype, diam, False)]
    except Exception:
        return []


def _len_num(s):
    try:
        return float(str(s).replace("in", "").replace("mm", ""))
    except ValueError:
        return None


# ------------------------------------------------------------ reading a hole

class Hole:
    """What MechFlow worked out about a picked hole edge."""

    def __init__(self, obj, sub):
        import Part
        self.obj, self.sub = obj, sub
        self.ok = False
        self.size = None          # "M8"
        self.kind = "unknown"     # clearance / tapped / nominal / unknown
        self.seat_sub = sub       # edge for a screw head
        self.cs_sub = None        # countersink top edge (countersunk screws)
        self.exit_sub = None      # edge at the far end (nut side)
        self.grip = None          # length of the hole proper (through holes)
        self.depth = None         # length of the hole proper (any hole)
        self.cs_grip = None       # countersink top to the far end
        self.through = False
        self.diameter = None
        try:
            edge = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
            prefix = ".".join(sub.split(".")[:-1])
            solid = Part.getShape(obj, prefix + "." if prefix else "", needSubElement=False,
                                  noElementMap=True)
        except Exception:
            return
        if not hasattr(edge, "Curve") or type(edge.Curve).__name__ != "Circle":
            return
        c, ax = edge.Curve.Center, App.Vector(edge.Curve.Axis).normalize()
        coax = []
        for i, e in enumerate(solid.Edges):
            if type(e.Curve).__name__ != "Circle" or e.Curve.Radius < 0.5:
                continue
            a2 = App.Vector(e.Curve.Axis).normalize()
            if abs(abs(a2.dot(ax)) - 1) > 1e-6:
                continue
            d = e.Curve.Center - c
            off = d - ax * d.dot(ax)
            if off.Length > 1e-4:
                continue
            coax.append((("." if prefix else "").join([prefix, f"Edge{i + 1}"]) if prefix
                         else f"Edge{i + 1}", e.Curve.Radius, d.dot(ax)))
        if not coax:
            return
        rp = min(r for _n, r, _t in coax)                     # the hole proper
        self.diameter = 2 * rp
        self.size, self.kind = size_for(2 * rp)
        proper = [x for x in coax if abs(x[1] - rp) < 1e-4]
        t_click = 0.0
        entry = min(proper, key=lambda x: abs(x[2] - t_click))
        exitp = max(proper, key=lambda x: abs(x[2] - entry[2]))
        self.seat_sub = entry[0]
        if exitp is not entry:
            self.exit_sub = exitp[0]
            self.grip = abs(exitp[2] - entry[2])
            self.depth = self.grip
        # Countersink: the largest circle on the click side of the hole proper.
        side = [x for x in coax if x[1] > rp + 1e-4 and (x[2] - entry[2]) * (t_click - entry[2]) >= 0]
        if side:
            cs = max(side, key=lambda x: x[1])
            self.cs_sub = cs[0]
            if exitp is not entry:
                self.cs_grip = abs(exitp[2] - cs[2])
        # Through hole: past the far end, along the axis, is outside the part.
        if self.exit_sub is not None:
            out_dir = 1.0 if exitp[2] > entry[2] else -1.0
            # Just past the end, and past where a drill point would reach.
            try:
                self.through = not any(
                    solid.isInside(c + ax * (exitp[2] + out_dir * k), 1e-6, True)
                    for k in (0.05, 0.65 * rp + 0.3))
            except Exception:
                self.through = True
        if not self.through:
            self.exit_sub = None
        self.ok = True

    def describe(self):
        if not self.ok:
            return "not a round hole"
        what = {"clearance": "clearance", "tapped": "tapped", "nominal": "thread size"}.get(
            self.kind, "unrecognised")
        size = f" for {self.size}" if self.size else ""
        return f"Ø{self.diameter:.2f} {what}{size}" + ("" if self.through else ", blind")


def size_for(d):
    """('M8', 'clearance') for a hole diameter, from the ISO tables."""
    for name, (nom, _p, tap, fine, med, coarse) in METRIC.items():
        if abs(d - tap) < TOL:
            return name, "tapped"
    for name, (nom, _p, tap, fine, med, coarse) in METRIC.items():
        if min(abs(d - fine), abs(d - med), abs(d - coarse)) < TOL:
            return name, "clearance"
    for name, (nom, *_r) in METRIC.items():
        if abs(d - nom) < TOL:
            return name, "nominal"
    # Not a standard hole: the largest size that fits.
    fits = [n for n, v in METRIC.items() if v[0] < d]
    return (fits[-1], "unknown") if fits else (None, "unknown")


# ------------------------------------------------------------ making fasteners

def designation(obj):
    """'ISO 4762 M8x25' (screws) or 'ISO 4032 M8' (nuts, washers)."""
    t = pretty(obj.Type)
    d = str(getattr(obj, "Diameter", ""))
    ln = str(getattr(obj, "Length", "")) if hasattr(obj, "Length") else ""
    if ln and ln not in ("Custom", "Auto"):
        return f"{t} {d}x{ln}"
    return f"{t} {d}"


def instance_label(doc, name):
    """'ISO 4762 M8x25<1>', '<2>', ... like SOLIDWORKS instances (and so
    FreeCAD doesn't renumber the size, e.g. 'M8' -> 'M001')."""
    used = {o.Label for o in doc.Objects}
    n = 1
    while f"{name}<{n}>" in used:
        n += 1
    return f"{name}<{n}>"


_patched = []


def patch_labels():
    """Keep the standard name ('ISO 4762 M8x25<1>') on Toolbox fasteners.

    The Fasteners Workbench renames a fastener on every recompute
    ('M8x25-Screw'); for the ones MechFlow inserted, put the standard name
    back afterwards, so it follows size changes and reopened files."""
    if _patched:
        return
    FC = fasteners()
    if FC is None:
        return
    cls = FC.FSScrewObject
    orig = cls.execute

    def execute(self, fp, *a, **k):
        r = orig(self, fp, *a, **k)
        try:
            n = getattr(fp, "MechFlowInstance", 0)
            if n:
                want = f"{designation(fp)}<{n}>"
                if fp.Label != want:
                    fp.Label = want
        except Exception:
            pass
        return r
    cls.execute = execute
    _patched.append(orig)


def make(container, ftype, attach, diam, length=None, offset=0.0, invert=False):
    FC = fasteners()
    doc = App.ActiveDocument if container is None else container.Document
    a = doc.addObject("Part::FeaturePython", "Fastener")
    if container is not None:
        container.addObject(a)
    FC.FSScrewObject(a, ftype, attach)
    try:
        FC.FSViewProviderTree(a.ViewObject)
    except Exception:
        pass
    if diam and diam in a.getEnumerationsOfProperty("Diameter"):
        a.Diameter = diam
    if offset and hasattr(a, "Offset"):
        a.Offset = offset
    if invert and hasattr(a, "Invert"):
        a.Invert = True
    # The length list depends on the diameter: let the fastener update first.
    doc.recompute()
    if length and hasattr(a, "Length"):
        try:
            opts = a.getEnumerationsOfProperty("Length")
        except Exception:
            opts = None
        if opts and str(length) in opts:
            a.Length = str(length)
        elif opts is None:
            try:
                a.Length = float(length)
            except Exception:
                pass
    name = instance_label(doc, designation(a))
    a.addProperty("App::PropertyInteger", "MechFlowInstance", "Base",
                  "Toolbox instance number (the <n> in the name)", 4)
    a.MechFlowInstance = int(name.rsplit("<", 1)[1][:-1])
    patch_labels()
    doc.recompute()
    a.Label = name
    return a


def _thickness(obj, axis):
    """Size of a fastener along an axis (e.g. a washer's thickness)."""
    try:
        ts = [v.Point.dot(axis) for v in obj.Shape.Vertexes]
        return max(ts) - min(ts)
    except Exception:
        return 0.0


def pick_length(ftype, diam, target, at_most=False):
    """Shortest standard length >= target (or the longest <= target)."""
    opts = lengths(ftype, diam)
    nums = [(n, s) for s in opts for n in [_len_num(s)] if n is not None]
    if not nums:
        return None
    nums.sort()
    if at_most:
        fit = [s for n, s in nums if n <= target + 1e-6]
        return fit[-1] if fit else nums[0][1]
    for n, s in nums:
        if n >= target - 1e-6:
            return s
    return nums[-1][1]


def _outward(obj, sub):
    """True if the edge's own axis points out of the material at that edge
    (Fasteners puts a head on that side). None if it can't tell."""
    import Part
    try:
        e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
        prefix = ".".join(sub.split(".")[:-1])
        solid = Part.getShape(obj, prefix + "." if prefix else "", needSubElement=False,
                              noElementMap=True)
        c, ax, r = e.Curve.Center, App.Vector(e.Curve.Axis).normalize(), e.Curve.Radius
        radial = ax.cross(App.Vector(1, 0, 0))
        if radial.Length < 1e-6:
            radial = ax.cross(App.Vector(0, 1, 0))
        radial.normalize()
        # Just outside the circle (a hole edge), then just inside (a pipe or
        # shaft end, where the material is inside the circle).
        for dr in (0.3, 0.1, 1.0, -0.3, -0.1, -min(1.0, 0.5 * r)):
            p = c + radial * (r + dr)
            up = solid.isInside(p + ax * 0.05, 1e-7, False)
            down = solid.isInside(p - ax * 0.05, 1e-7, False)
            if up != down:
                return down
    except Exception:
        pass
    return None


def auto_length(ftype, hole, diam, ends=ENDS[0], offset=0.0):
    """Standard screw length for a hole (see place)."""
    nom, pitch = METRIC.get(diam, (8.0, 1.25))[:2]
    grip = hole.grip if hole.grip is not None else 0.0
    at_most = False
    tapped_after = getattr(hole, "tapped_after", None)
    if tapped_after is not None:
        # Through clearance parts into a tapped part (Smart Fasteners):
        # engage up to 1.5 x d, no deeper than the tapped hole.
        depth = getattr(hole, "tapped_depth", None) or 1.5 * nom
        target, at_most = tapped_after + offset + min(1.5 * nom, depth - pitch), True
    elif hole.kind == "tapped" and not hole.through:
        # Straight into a blind tapped hole: as long as the hole allows.
        target = min(1.5 * nom, hole.depth - pitch) if hole.depth else 1.5 * nom
        at_most = bool(hole.depth)
    elif not hole.through and hole.grip:
        # A blind hole: no longer than the hole.
        target, at_most = hole.grip + offset, True
    elif ends == ENDS[1] and hole.through:
        target = grip + offset + 0.16 * nom + 0.8 * nom + 2 * pitch
    elif ends == ENDS[2]:
        target = grip + offset
    else:
        target = grip + offset + 1.5 * nom
    if ftype in COUNTERSUNK:
        # Countersunk lengths include the head: measure from the top.
        g2 = hole.cs_grip if hole.cs_grip is not None else grip
        target = max(target - grip + g2, 1.5 * nom)
    return pick_length(ftype, diam, target, at_most)


def place(container, ftype, hole, diam=None, length=None, washer_under_head=False,
          ends=ENDS[0]):
    """Insert a fastener (with washers / nut) in one hole. Returns the objects."""
    import Part
    made = []
    diam = diam or hole.size or "M8"
    nom, pitch = METRIC.get(diam, (8.0, 1.25))[:2]
    try:
        axis = App.Vector(Part.getShape(hole.obj, hole.seat_sub, needSubElement=True,
                                        noElementMap=True).Curve.Axis).normalize()
    except Exception:
        axis = App.Vector(0, 0, 1)
    seat = hole.cs_sub if (ftype in COUNTERSUNK and hole.cs_sub) else hole.seat_sub
    offset = 0.0
    inv = _outward(hole.obj, seat) is False
    if washer_under_head and ftype not in COUNTERSUNK:
        w = make(container, WASHER, (hole.obj, [seat]), diam, invert=inv)
        offset = _thickness(w, axis)
        made.append(w)
    is_screw = hasattr_length(ftype)
    if is_screw and length is None:
        length = auto_length(ftype, hole, diam, ends, offset)
    s = make(container, ftype, (hole.obj, [seat]), diam, length, offset, inv)
    made.append(s)
    if ends == ENDS[1] and hole.through and hole.exit_sub and is_screw:
        xobj = getattr(hole, "exit_obj", None) or hole.obj
        inv2 = _outward(xobj, hole.exit_sub) is False
        w2 = make(container, WASHER, (xobj, [hole.exit_sub]), diam, invert=inv2)
        made.append(w2)
        made.append(make(container, NUT, (xobj, [hole.exit_sub]), diam,
                         offset=_thickness(w2, axis), invert=inv2))
    return made


def hasattr_length(ftype):
    FC = fasteners()
    try:
        return "Length" in FC.FSGetParams(ftype) or "LengthCustom" in FC.FSGetParams(ftype)
    except Exception:
        return False


def active_container():
    for ctx in ("assembly", "part"):
        try:
            c = Gui.ActiveDocument.ActiveView.getActiveObject(ctx)
            if c is not None:
                return c
        except Exception:
            pass
    try:
        from mechflow_gui import assembly
        a = assembly.active_assembly()
        if a is not None and a.ViewObject.isInEditMode():
            return a
    except Exception:
        pass
    return None


def attachable_selection(container=None):
    """[(obj, [sub])] for each hole edge selected - or each hole in a selected
    face - with obj inside the container (an assembly: the component link)."""
    import Part
    doc = App.ActiveDocument

    def edge_name(shape, edge):
        for i, e in enumerate(shape.Edges):
            if e.isSame(edge):
                return f"Edge{i + 1}"
        return None
    out, seen = [], []

    def dup(e):
        for c, r in seen:
            if (c - e.Curve.Center).Length < 1e-6 and abs(r - e.Curve.Radius) < 1e-6:
                return True
        seen.append((e.Curve.Center, e.Curve.Radius))
        return False

    for so in Gui.Selection.getSelectionEx("", 0):
        for raw in so.SubElementNames:
            sub = raw
            if ";" in sub:      # drop the element map: 'Plate.;#42:3;:H..,E.Edge15'
                parts = sub.split(";")
                sub = parts[0] + parts[-1].split(".")[-1]
            path = [so.Object.Name] + sub.split(".")
            if container is not None and container.Name in path:
                path = path[path.index(container.Name) + 1:]
            if len(path) < 2:
                continue
            obj = so.Object.Document.getObject(path[0]) or doc.getObject(path[0])
            sub = ".".join(path[1:])
            try:
                shape = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
            except Exception:
                continue
            if hasattr(shape, "Curve"):
                if type(shape.Curve).__name__ == "Circle" and not dup(shape):
                    out.append((obj, [sub]))
            elif isinstance(shape, Part.Face):
                pre = ".".join(sub.split(".")[:-1])
                whole = Part.getShape(obj, pre + "." if pre else "",
                                      needSubElement=False, noElementMap=True)
                outer = shape.OuterWire.Edges
                for e in shape.Edges:
                    if type(e.Curve).__name__ != "Circle" or any(o.isSame(e) for o in outer):
                        continue
                    name = edge_name(whole, e)
                    if name is None or dup(e):
                        continue
                    out.append((obj, [".".join(sub.split(".")[:-1] + [name])]))
    return out


# ------------------------------------------------------------ the panel

class ToolboxPanel:
    def __init__(self):
        self.FC = fasteners()
        self.container = active_container()
        self.holes = []          # Hole objects
        self.form = self._build()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._take()

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Toolbox")
        root = QtWidgets.QVBoxLayout(w)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Standard"))
        self.std = QtWidgets.QComboBox()
        self.std.addItems(["All"] + STANDARDS)
        self.std.setCurrentText(App.ParamGet(PARAMS).GetString("ToolboxStandard", "ISO"))
        self.std.currentTextChanged.connect(self._fill_tree)
        top.addWidget(self.std, 1)
        root.addLayout(top)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search (e.g. 4762, socket, nut)")
        self.search.textChanged.connect(self._fill_tree)
        root.addWidget(self.search)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QtCore.QSize(28, 28))
        self.tree.setMinimumHeight(220)
        self.tree.currentItemChanged.connect(self._type_changed)
        root.addWidget(self.tree, 1)

        form = QtWidgets.QFormLayout()
        self.form_layout = form
        self.size = QtWidgets.QComboBox()
        self.size.currentTextChanged.connect(self._size_changed)
        form.addRow("Size", self.size)
        self.rating = QtWidgets.QComboBox()
        self.rating.setToolTip("Pressure rating (PN / Class) or pipe schedule")
        self.rating.currentTextChanged.connect(lambda *_: self._refresh_holes())
        form.addRow("Rating", self.rating)
        self.length = QtWidgets.QComboBox()
        form.addRow("Length", self.length)
        self.pipe_length = QtWidgets.QDoubleSpinBox()
        self.pipe_length.setRange(1.0, 100000.0)
        self.pipe_length.setDecimals(1)
        self.pipe_length.setSuffix(" mm")
        self.pipe_length.setValue(1000.0)
        form.addRow("Pipe length", self.pipe_length)
        self.ends = QtWidgets.QComboBox()
        self.ends.addItems(ENDS)
        form.addRow("Ends in", self.ends)
        self.washer = QtWidgets.QCheckBox("Washer under the head")
        form.addRow("", self.washer)
        self.joint = QtWidgets.QCheckBox("Gasket, bolts and nuts")
        self.joint.setChecked(True)
        self.joint.setToolTip("On another flange's face: add a gasket between them and bolt "
                              "them together (bolts need the Fasteners Workbench)")
        form.addRow("Joint", self.joint)
        root.addLayout(form)

        hb = QtWidgets.QGroupBox("Holes")
        self.hole_box = hb
        hv = QtWidgets.QVBoxLayout(hb)
        self.hole_list = QtWidgets.QListWidget()
        self.hole_list.setMaximumHeight(90)
        hv.addWidget(self.hole_list)
        clr = QtWidgets.QPushButton("Clear")
        clr.clicked.connect(self._clear)
        hv.addWidget(clr)
        root.addWidget(hb)
        self.msg = QtWidgets.QLabel("Pick a fastener, then click hole edges in the view - "
                                    "or a face, for all its holes. OK inserts them.")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        root.addWidget(self.msg)
        if fasteners() is None:
            note = QtWidgets.QLabel("Screws, nuts, washers and pins come from the free "
                                    "<b>Fasteners Workbench</b>, which isn't installed.")
            note.setWordWrap(True)
            root.addWidget(note)
            get = QtWidgets.QPushButton("Get the Fasteners Workbench...")
            get.clicked.connect(offer_install)
            root.addWidget(get)
        self._fill_tree()
        return w

    # ---- catalogue
    def _fill_tree(self, *_):
        App.ParamGet(PARAMS).SetString("ToolboxStandard", self.std.currentText())
        want = self.search.text().strip().lower()
        cur = self.current_type()
        self.tree.blockSignals(True)
        self.tree.clear()
        select = None
        for cat, items in catalog(self.std.currentText()):
            rows = [(t, d) for t, d in items
                    if not want or want in t.lower() or want in d.lower()
                    or want in pretty(t).lower()]
            if not rows:
                continue
            top = QtWidgets.QTreeWidgetItem([cat])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.tree.addTopLevelItem(top)
            for t, d in rows:
                it = QtWidgets.QTreeWidgetItem([f"{pretty(t)}  {d}".strip()])
                it.setData(0, QtCore.Qt.UserRole, t)
                it.setIcon(0, icon(t))
                it.setToolTip(0, f"{pretty(t)} - {d}")
                top.addChild(it)
                if t == (cur or "ISO4762"):
                    select = it
                elif select is None and cur is None and fasteners() is None:
                    select = it
            first = self.tree.topLevelItemCount() == 1
            top.setExpanded(bool(want) or cat == "Bolts and Screws"
                            or (first and fasteners() is None))
        self.tree.blockSignals(False)
        if select is not None:
            self.tree.setCurrentItem(select)
        self._type_changed()

    def current_type(self):
        it = self.tree.currentItem() if hasattr(self, "tree") else None
        return it.data(0, QtCore.Qt.UserRole) if it is not None else None

    def is_std(self, t=None):
        from mechflow_gui import stdparts
        t = t or self.current_type()
        return bool(t) and stdparts.is_std(t)

    def _row(self, widget, on):
        try:
            self.form_layout.setRowVisible(widget, on)
        except Exception:
            widget.setVisible(on)
            lbl = self.form_layout.labelForField(widget)
            if lbl is not None:
                lbl.setVisible(on)

    def _type_changed(self, *_):
        from mechflow_gui import stdparts
        t = self.current_type()
        std = self.is_std(t)
        self.size.blockSignals(True)
        self.size.clear()
        if t:
            self.size.addItem("Auto (from edge)" if std else "Auto (from hole)")
            self.size.addItems(stdparts.sizes(t) if std else diameters(t))
        self.size.blockSignals(False)
        self.rating.clear()
        if std:
            self.rating.addItems(stdparts.ratings(t))
            self.rating.setCurrentText(stdparts.default_rating(t))
        self._row(self.rating, std and self.rating.count() > 0)
        self._row(self.pipe_length, std and stdparts.has_length(t))
        self._row(self.joint, std and stdparts.is_flange(t))
        for w in (self.length, self.ends, self.washer):
            self._row(w, not std)
        self.hole_box.setTitle("Edges" if std else "Holes")
        screw = bool(t) and not std and hasattr_length(t)
        self.ends.setEnabled(screw)
        self.washer.setEnabled(screw and t not in COUNTERSUNK)
        self._size_changed()
        self._refresh_holes()
        if std:
            cat = stdparts.TYPES[t][0]
            hint = {"Flanges": "Click a pipe end (its outside edge), or a flange's face edge to "
                               "bolt another flange (or a blind) to it.",
                    "Pipe": "Click the end of a flange or fitting to carry on from it.",
                    "Pipe Fittings": "Click a pipe end to fit it there.",
                    "Bearings": "Click a shaft end or a housing bore edge."}[cat]
            self.msg.setText(hint + " It is sized to the edge. With nothing picked, OK "
                             "puts one at the origin.")
        elif t:
            self.msg.setText("Click hole edges in the view - or a face, for all its holes. "
                             "OK inserts the fasteners.")

    def _size_changed(self, *_):
        t = self.current_type()
        self.length.clear()
        if self.is_std(t):
            self.length.setEnabled(False)
            return
        if not t or not hasattr_length(t):
            self.length.setEnabled(False)
            return
        self.length.setEnabled(True)
        self.length.addItem("Auto (from hole)")
        d = self.size.currentText()
        if d and not d.startswith("Auto"):
            self.length.addItems(lengths(t, d))

    # ---- holes
    def _poll(self):
        try:
            self._take()
        except Exception as e:
            App.Console.PrintLog(f"MechFlow toolbox: {e}\n")

    def _take(self):
        if not Gui.Selection.getSelectionEx():
            return
        sels = attachable_selection(self.container)
        Gui.Selection.clearSelection()
        std = self.is_std()
        known = {(h.obj.Name, h.sub if std else h.seat_sub) for h in self.holes}
        for s in sels:
            if s is None:
                continue
            h = Hole(s[0], s[1][0])
            key = (h.obj.Name, h.sub if std else h.seat_sub)
            if not h.ok or key in known:
                continue
            known.add(key)
            self.holes.append(h)
        self._refresh_holes()
        n = len(self.holes)
        what = ("edge" if std else "hole") + ("s" if n != 1 else "")
        self.msg.setText(f"{n} {what} picked. OK inserts "
                         + ("the parts." if std else "the fasteners."))

    def _refresh_holes(self):
        from mechflow_gui import stdparts
        import Part
        self.hole_list.clear()
        t = self.current_type()
        for h in self.holes:
            if self.is_std(t):
                try:
                    e = Part.getShape(h.obj, h.sub, needSubElement=True, noElementMap=True)
                    d = 2 * e.Curve.Radius
                    base = stdparts.joint_with(h.obj, h.sub, t)
                    if base is not None:
                        self.hole_list.addItem(
                            f"{base.Label}: face \u2192 joint, {base.Size} {base.Rating}")
                        continue
                    size = stdparts.match_size(t, self.rating.currentText()
                                               or stdparts.default_rating(t), d)
                    text = f"Ø{d:.2f} edge" + (f" → {size}" if size else
                                                    " (no matching size)")
                except Exception:
                    text = "edge"
            else:
                text = h.describe()
            self.hole_list.addItem(f"{h.obj.Label}: {text}")

    def _clear(self):
        self.holes = []
        self.hole_list.clear()

    # ---- task dialog
    def accept(self):
        t = self.current_type()
        if not t:
            QtWidgets.QMessageBox.information(self.form, "Toolbox", "Pick a part first.")
            return False
        if self.is_std(t):
            return self._accept_std(t)
        self._timer.stop()
        doc = (self.container.Document if self.container is not None else App.ActiveDocument)
        doc.openTransaction("Toolbox")
        size = None if self.size.currentText().startswith("Auto") else self.size.currentText()
        length = None if self.length.currentText().startswith("Auto") else self.length.currentText()
        made = []
        try:
            if self.holes:
                for h in self.holes:
                    made += place(self.container, t, h, size, length,
                                  self.washer.isChecked() and self.washer.isEnabled(),
                                  self.ends.currentText())
            else:
                made.append(make(self.container, t, None, size or "M8",
                                 length or (lengths(t, size or "M8") or [None])[0]))
            doc.commitTransaction()
        except Exception as e:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self.form, "Toolbox",
                                          f"The fasteners couldn't be inserted:\n{e}")
            return False
        doc.recompute()
        App.Console.PrintMessage(
            "MechFlow Toolbox: inserted " + ", ".join(o.Label for o in made) + "\n")
        Gui.Control.closeDialog()
        return True

    def _accept_std(self, t):
        from mechflow_gui import stdparts
        self._timer.stop()
        doc = (self.container.Document if self.container is not None else App.ActiveDocument)
        size = None if self.size.currentText().startswith("Auto") else self.size.currentText()
        rating = self.rating.currentText() or None
        length = self.pipe_length.value()
        made = []
        doc.openTransaction("Toolbox")
        try:
            if self.holes:
                for h in self.holes:
                    made += stdparts.place(self.container, t, h.obj, h.sub, size, rating,
                                           length, joint=self.joint.isChecked())
            else:
                made += stdparts.place(self.container, t, None, None, size, rating, length)
            doc.commitTransaction()
        except Exception as e:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self.form, "Toolbox",
                                          f"The part couldn't be inserted:\n{e}")
            return False
        doc.recompute()
        App.Console.PrintMessage(
            "MechFlow Toolbox: inserted " + ", ".join(o.Label for o in made) + "\n")
        self.made = made
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._timer.stop()
        Gui.Control.closeDialog()
        return True


def toolbox():
    if App.ActiveDocument is None:
        App.newDocument()
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Toolbox",
                                          "Finish the open dialog first.")
        return None
    panel = ToolboxPanel()
    Gui.Control.showDialog(panel)
    return panel
