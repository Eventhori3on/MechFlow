# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style reference Plane and Axis.

Plane - choose the type from the dropdown (like SOLIDWORKS), then click its
references: Offset distance (drag arrow), At angle (drag disc), Mid plane,
Parallel through point, Through 3 points, Normal to curve, Tangent to surface.
Axis:
  round face / circular edge -> its centre axis
  straight edge              -> along the edge
  two points                 -> through both
  two planes / faces         -> where they meet
"""

import FreeCAD as App
from mechflow_gui import edge_curve, curve_name  # noqa: F401
import FreeCADGui as Gui

from mechflow_gui.panel_base import FeaturePanel, PickField, has, set_enum, open_panel

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


def _shape_of(obj, sub):
    try:
        return obj.Shape.getElement(sub) if sub else obj.Shape
    except Exception:
        return None


def _kind(obj, sub):
    if not sub:
        if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
            return "plane"
        if obj.TypeId in ("App::Line", "PartDesign::Line"):
            return "line"
        if obj.TypeId in ("App::Point", "PartDesign::Point"):
            return "point"
        return "other"
    shp = _shape_of(obj, sub)
    if sub.startswith("Face"):
        try:
            t = type(shp.Surface).__name__
        except Exception:
            t = ""
        return "plane" if t == "Plane" else ("round" if t in ("Cylinder", "Cone") else "face")
    if sub.startswith("Edge"):
        try:
            t = curve_name(shp)
        except Exception:
            t = ""
        return "line" if t in ("Line", "LineSegment") else ("round" if t == "Circle" else "edge")
    if sub.startswith("Vertex"):
        return "point"
    return "other"


def _set_support(f, refs):
    prop = "AttachmentSupport" if has(f, "AttachmentSupport") else "Support"
    setattr(f, prop, [(o, s) for o, s in refs])


def _attached_placement(f):
    f.Document.recompute()
    return App.Placement(f.Placement)


# ---------------------------------------------------------------- Plane types
# name: (icon key, [(field title, kinds, optional)], handle)
PLANE_TYPES = [
    ("Offset distance", "offset",
     [("Face / Plane", ["plane"], False)], "arrow"),
    ("At angle", "angle",
     [("Face / Plane", ["plane"], False),
      ("Hinge edge (optional)", ["linear"], True)], "disc"),
    ("Mid plane", "mid",
     [("First face / plane", ["plane"], False),
      ("Second face / plane", ["plane"], False)], None),
    ("Parallel through point", "point",
     [("Face / Plane", ["plane"], False),
      ("Point", ["vertex"], False)], None),
    ("Through 3 points", "three",
     [("Point 1", ["vertex"], False), ("Point 2", ["vertex"], False),
      ("Point 3", ["vertex"], False)], None),
    ("Normal to curve", "normal",
     [("Edge / curve", ["edge"], False),
      ("Point on the curve (optional)", ["vertex"], True)], None),
    ("Tangent to surface", "tangent",
     [("Round face", ["face"], False),
      ("Point on the face", ["vertex"], False)], None),
]
TYPE_NAMES = [t[0] for t in PLANE_TYPES]
MODES = TYPE_NAMES          # (older name, kept for saved planes)


def _type_icon(key):
    """Little SOLIDWORKS-style picture of each plane type."""
    try:
        from PySide6 import QtGui
    except ImportError:
        from PySide2 import QtGui
    pm = QtGui.QPixmap(32, 32)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    grey = QtGui.QColor(150, 150, 150, 170)
    blue = QtGui.QColor(70, 140, 220, 200)

    def plane(dy=0, colour=grey, pts=None):
        poly = QtGui.QPolygonF([QtCore.QPointF(x, y + dy) for x, y in
                                (pts or [(3, 24), (19, 24), (29, 16), (13, 16)])])
        p.setPen(QtGui.QPen(colour.darker(150), 1))
        p.setBrush(colour)
        p.drawPolygon(poly)

    def dot(x, y):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(30, 30, 30))
        p.drawEllipse(QtCore.QPointF(x, y), 2.2, 2.2)

    if key == "offset":
        plane()
        plane(-12, blue)
        p.setPen(QtGui.QPen(QtGui.QColor(200, 60, 40), 1.6))
        p.drawLine(16, 19, 16, 9)
        p.drawLine(16, 9, 13, 12)
        p.drawLine(16, 9, 19, 12)
    elif key == "angle":
        plane()
        plane(0, blue, [(3, 24), (19, 24), (25, 6), (9, 6)])
        p.setPen(QtGui.QPen(QtGui.QColor(200, 60, 40), 2))
        p.drawLine(3, 24, 19, 24)
    elif key == "mid":
        plane(4)
        plane(-14)
        plane(-5, blue)
    elif key == "point":
        plane(4)
        plane(-10, blue)
        dot(16, 10)
    elif key == "three":
        plane(-4, blue)
        dot(8, 19)
        dot(19, 19)
        dot(21, 13)
    elif key == "normal":
        path = QtGui.QPainterPath(QtCore.QPointF(2, 28))
        path.cubicTo(10, 26, 16, 18, 30, 16)
        p.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30), 1.6))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(path)
        plane(0, blue, [(10, 30), (18, 26), (18, 6), (10, 10)])
        dot(14, 20)
    elif key == "tangent":
        p.setPen(QtGui.QPen(grey.darker(150), 1))
        p.setBrush(grey)
        p.drawEllipse(QtCore.QPointF(12, 18), 9, 9)
        plane(0, blue, [(21, 30), (25, 27), (25, 4), (21, 7)])
        dot(21, 18)
    p.end()
    return QtGui.QIcon(pm)


def _store(f, name, typ, value):
    if not hasattr(f, name):
        try:
            f.addProperty(typ, name, "MechFlow", "")
            f.setEditorMode(name, 2)         # hidden: MechFlow keeps it in step
        except Exception:
            return
    try:
        setattr(f, name, value)
    except Exception:
        pass


class PlanePanel(FeaturePanel):
    TITLE = "Plane"
    DATUM = True
    HINT = ("Choose the plane type, then click its references in the view or the "
            "tree. Drag the arrow or disc in the view, or type in the box beside it.")

    def build(self):
        row = QtWidgets.QFormLayout()
        self.ptype = QtWidgets.QComboBox()
        self.ptype.setIconSize(QtCore.QSize(28, 28))
        for name, key, _f, _h in PLANE_TYPES:
            self.ptype.addItem(_type_icon(key), name)
        self.ptype.setMinimumHeight(34)
        self.ptype.currentIndexChanged.connect(self._type_changed)
        row.addRow("Plane type", self.ptype)
        self.root.addLayout(row)
        # Up to three reference boxes; titles and what they take follow the type.
        self.refs_f = [self.add_field(PickField(self, "Reference", ["plane"], single=True))
                       for _ in range(3)]
        row = QtWidgets.QFormLayout()
        self.offset = self.spin(" mm", -1e6, 1e6, 10.0)
        self.offset_lbl = QtWidgets.QLabel("Offset")
        row.addRow(self.offset_lbl, self.offset)
        self.angle = self.spin("°", -360.0, 360.0, 45.0)
        self.angle_lbl = QtWidgets.QLabel("Angle")
        row.addRow(self.angle_lbl, self.angle)
        self.root.addLayout(row)
        # 3D view handles and callouts
        self._key = None
        self._geo = None
        self._arrow = self._disc = None
        self._dbox = self._abox = None
        self._settle = QtCore.QTimer()
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
        self._settle.timeout.connect(self.changed)
        self._ticker = QtCore.QTimer()
        self._ticker.setInterval(60)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()
        self._apply_type(keep=False)

    # ---- plane type
    def _tdef(self):
        return PLANE_TYPES[max(0, self.ptype.currentIndex())]

    def _apply_type(self, keep=True):
        name, key, fields, handle = self._tdef()
        for i, fld in enumerate(self.refs_f):
            if i < len(fields):
                title, kinds, optional = fields[i]
                fld.box.setTitle(title)
                fld.kinds = kinds
                fld.optional = optional
                fld.box.setVisible(True)
                if keep:   # drop what this type can't use
                    ok = []
                    for o, s in fld.items:
                        shp = _shape_of(o, s) if s else None
                        if fld.accepts(o, s, shp):
                            ok.append((o, s))
                    fld.set(ok)
                else:
                    fld.set([])
            else:
                fld.box.setVisible(False)
                fld.set([])
                fld.optional = True
        self.offset.setVisible(handle == "arrow")
        self.offset_lbl.setVisible(handle == "arrow")
        self.angle.setVisible(handle == "disc")
        self.angle_lbl.setVisible(handle == "disc")
        nxt = next((f for f in self._visible() if not f.items), None)
        self.set_active(nxt or self.refs_f[0])

    def _type_changed(self, _i):
        if self._loading:
            return
        self._apply_type(keep=True)
        self.changed()

    def _visible(self):
        n = len(self._tdef()[2])
        return self.refs_f[:n]

    def _take_selection(self):
        """Selected items fill the boxes in turn (e.g. three points at once)."""
        sel = Gui.Selection.getSelectionEx()
        if not sel or self.active is None:
            return False
        took = False
        for item in sel:
            subs = list(item.SubElementNames) or [""]
            shps = list(item.SubObjects) or [None]
            for sub, shp in zip(subs, shps):
                fld = self.active
                if fld.add(item.Object, sub, shp):
                    took = True
                    nxt = next((f for f in self._visible() if not f.items), None)
                    if nxt is not None:
                        self.set_active(nxt)
        Gui.Selection.clearSelection()
        if took:
            self.changed()
        return took

    def after_pick(self, field):
        for f in self._visible():
            if f is not field and not f.items:
                self.set_active(f)
                break
        self.changed()

    def ready(self):
        return all(f.items for f in self._visible() if not getattr(f, "optional", False))

    def _ref(self, i):
        f = self.refs_f[i]
        return f.items[0] if f.items else None

    # ---- geometry helpers
    def _centre(self, ref):
        """World point the new plane is centred on: the face's centre, or the
        part's centre for a datum/origin plane."""
        obj, sub = ref
        if sub:
            shp = _shape_of(obj, sub)
            try:
                return shp.CenterOfMass
            except Exception:
                pass
        try:
            return self.body.Shape.BoundBox.Center
        except Exception:
            return App.Vector()

    def _size(self):
        try:
            d = self.body.Shape.BoundBox.DiagonalLength
            return d if d > 1e-6 else 100.0
        except Exception:
            return 100.0

    def _attach_flat(self, f, ref):
        """Attach flat on a face/plane with no offset; return its placement."""
        _set_support(f, [ref])
        set_enum(f, "MapMode", ["FlatFace"])
        f.AttachmentOffset = App.Placement()
        bp = _attached_placement(f)
        if not f.isValid():
            set_enum(f, "MapMode", ["ObjectXY"])
            bp = _attached_placement(f)
        return bp

    # ---- build the plane
    def make_feature(self):
        return self.body.newObject("PartDesign::Plane", "DatumPlane")

    def update_feature(self, f):
        name, key, _fields, _h = self._tdef()
        r1, r2, r3 = self._ref(0), self._ref(1), self._ref(2)
        self._geo = None

        if key == "three":
            _set_support(f, [r1, r2, r3])
            set_enum(f, "MapMode", ["ThreePointsPlane"])
            f.AttachmentOffset = App.Placement()
        elif key == "normal":
            _set_support(f, [r1] + ([r2] if r2 else []))
            set_enum(f, "MapMode", ["NormalToEdge"])
            f.AttachmentOffset = App.Placement()
        elif key == "tangent":
            _set_support(f, [r1, r2])
            set_enum(f, "MapMode", ["TangentPlane"])
            f.AttachmentOffset = App.Placement()
        else:
            bp = self._attach_flat(f, r1)
            inv = bp.inverse()
            c = inv.multVec(self._centre(r1))
            c.z = 0.0
            normal = bp.Rotation.multVec(App.Vector(0, 0, 1))
            if key == "offset":
                d = self.offset.value()
                f.AttachmentOffset = App.Placement(App.Vector(c.x, c.y, d), App.Rotation())
                self._geo = ("offset", bp.multVec(c), normal, d)
            elif key == "point":
                d = inv.multVec(_shape_of(*r2).Point).z
                f.AttachmentOffset = App.Placement(App.Vector(c.x, c.y, d), App.Rotation())
            elif key == "mid":
                other = _shape_of(*r2)
                if other is None or not hasattr(other, "Faces") or not other.Faces:
                    p2 = r2[0].Placement.Base      # a datum / origin plane
                else:
                    try:
                        from mechflow_gui import pick_solid
                        p2, _n = pick_solid._face_probe(other.Faces[0])
                    except Exception:
                        p2 = self._centre(r2)
                d = inv.multVec(p2).z / 2.0
                f.AttachmentOffset = App.Placement(App.Vector(c.x, c.y, d), App.Rotation())
            elif key == "angle":
                if r2 is not None:
                    e = _shape_of(*r2)
                    a = inv.multVec(e.Vertexes[0].Point)
                    b = inv.multVec(e.Vertexes[-1].Point)
                    u = b - a
                    m = (a + b) * 0.5
                else:
                    # No edge: hinge on the plane's own horizontal line
                    # through the centre.
                    a = m = App.Vector(c.x, c.y, 0)
                    u = App.Vector(1, 0, 0)
                ang = self.angle.value()
                # Rotate about the hinge; keep the plane's centre on the hinge.
                f.AttachmentOffset = (App.Placement(a, App.Rotation(u, ang))
                                      .multiply(App.Placement(a * -1, App.Rotation()))
                                      .multiply(App.Placement(m, App.Rotation())))
                self._geo = ("angle", bp.multVec(m), bp.Rotation.multVec(u), ang)

        _store(f, "MechFlowPlaneMode", "App::PropertyString", name)
        _store(f, "MechFlowPlaneOffset", "App::PropertyFloat", self.offset.value())
        _store(f, "MechFlowPlaneAngle", "App::PropertyFloat", self.angle.value())
        for i in range(3):
            r = self._ref(i)
            _store(f, f"MechFlowRef{i + 1}", "App::PropertyLinkSubGlobal",
                   (r[0], [r[1]] if r[1] else []) if r else None)
        self._sync_handles()

    # ---- 3D handles
    def _sync_handles(self):
        from mechflow_gui import view_handles as vh
        geo = self._geo
        key = None
        if geo is not None:
            key = (geo[0], tuple(round(x, 6) for x in geo[1]),
                   tuple(round(x, 6) for x in geo[2]))
        if key == self._key:
            if geo is not None:          # value typed: move the handle to it
                h = self._arrow or self._disc
                if h is not None and abs(h.last - geo[3]) > 1e-6:
                    h.set_value(geo[3])
                box = self._dbox or self._abox
                if box is not None:
                    box.set_quiet(geo[3])
            return
        self._clear_handles()
        self._key = key
        if geo is None:
            return
        scale = max(1.0, self._size() * 0.06)
        if geo[0] == "offset":
            self._arrow = vh.Arrow(geo[1], geo[2], geo[3], scale)
            self._dbox = vh.ViewBox(" mm", -1e6, 1e6)
            self._dbox.set_quiet(geo[3])
            self._dbox.valueChanged.connect(self.offset.setValue)
        else:
            self._disc = vh.Disc(geo[1], geo[2], geo[3], scale * 1.2)
            self._abox = vh.ViewBox("°", -360.0, 360.0)
            self._abox.set_quiet(geo[3])
            self._abox.valueChanged.connect(self.angle.setValue)

    def _clear_handles(self):
        for h in (self._arrow, self._disc, self._dbox, self._abox):
            if h is not None:
                h.remove()
        self._arrow = self._disc = self._dbox = self._abox = None
        self._key = None

    def changed(self, *a):
        super().changed(*a)
        if not self.ready() or self.failed:
            self._geo = None
            if self._key is not None:
                self._clear_handles()

    def _tick(self):
        try:
            if self._arrow is not None:
                d = self._arrow.moved()
                if d is not None:
                    self._quiet(self.offset, d)
                    self._dbox.set_quiet(d)
                    self._settle.start()
                self._dbox.place(self._arrow.tip())
            if self._disc is not None:
                a = self._disc.moved()
                if a is not None:
                    a = round(a, 1)
                    self._quiet(self.angle, a)
                    self._abox.set_quiet(a)
                    self._settle.start()
                self._abox.place(self._disc.label_point())
        except Exception:
            pass

    @staticmethod
    def _quiet(spin, v):
        spin.blockSignals(True)
        spin.setValue(v)
        spin.blockSignals(False)

    def _stop(self):
        for t in (self._ticker, self._settle):
            try:
                t.stop()
            except Exception:
                pass
        self._clear_handles()
        super()._stop()

    def load(self, f):
        mode = getattr(f, "MechFlowPlaneMode", "")
        if mode not in TYPE_NAMES:
            mm = str(f.MapMode)
            mode = {"ThreePointsPlane": "Through 3 points",
                    "NormalToEdge": "Normal to curve",
                    "TangentPlane": "Tangent to surface"}.get(mm, "Offset distance")
        self.ptype.setCurrentIndex(TYPE_NAMES.index(mode))
        self._apply_type(keep=False)
        refs = []
        for i in range(3):
            v = getattr(f, f"MechFlowRef{i + 1}", None)
            if v:
                obj, subs = v[0], list(v[1]) if len(v) > 1 else []
                refs.append((obj, subs[0] if subs else ""))
        if not refs:                     # a plane MechFlow didn't make
            prop = "AttachmentSupport" if has(f, "AttachmentSupport") else "Support"
            for obj, subs in getattr(f, prop, []) or []:
                for sub in (subs if isinstance(subs, (list, tuple)) else [subs]) or [""]:
                    refs.append((obj, sub))
        for fld, r in zip(self._visible(), refs):
            fld.set([r])
        if hasattr(f, "MechFlowPlaneOffset"):
            self.offset.setValue(f.MechFlowPlaneOffset)
        else:
            self.offset.setValue(f.AttachmentOffset.Base.z)
        if hasattr(f, "MechFlowPlaneAngle"):
            self.angle.setValue(f.MechFlowPlaneAngle)
        nxt = next((x for x in self._visible() if not x.items), None)
        self.set_active(nxt or self._visible()[0])

    def error_text(self):
        return ("<b>The plane can't be made</b> from these references - check they "
                "suit the plane type (e.g. the two faces for a mid plane are parallel).")


class AxisPanel(FeaturePanel):
    TITLE = "Axis"
    DATUM = True
    HINT = ("Pick a round face or circular edge (centre axis), a straight edge, "
            "two points, or two planes / faces (where they meet).")

    def build(self):
        self.refs = self.add_field(PickField(self, "References",
                                             ["plane", "linear", "axis", "vertex", "face"]))
        row = QtWidgets.QFormLayout()
        self.kind = QtWidgets.QLabel("-")
        row.addRow("Axis type", self.kind)
        self.root.addLayout(row)

    def ready(self):
        return bool(self.refs.items)

    def make_feature(self):
        return self.body.newObject("PartDesign::Line", "DatumLine")

    def update_feature(self, f):
        kinds = [_kind(o, s) for o, s in self.refs.items]
        items = self.refs.items
        f.AttachmentOffset = App.Placement()
        if "round" in kinds:
            r = items[kinds.index("round")]
            _set_support(f, [r])
            set_enum(f, "MapMode", ["AxisOfCurvature"])
            self.kind.setText("Centre axis")
        elif kinds.count("point") >= 2:
            pts = [r for r, k in zip(items, kinds) if k == "point"][:2]
            _set_support(f, pts)
            set_enum(f, "MapMode", ["TwoPointLine"])
            self.kind.setText("Through two points")
        elif kinds.count("plane") >= 2:
            pls = [r for r, k in zip(items, kinds) if k == "plane"][:2]
            _set_support(f, pls)
            set_enum(f, "MapMode", ["IntersectionLine"])
            self.kind.setText("Where two planes meet")
        elif "line" in kinds:
            obj, sub = items[kinds.index("line")]
            edge = _shape_of(obj, sub)
            names = []
            for v in (edge.Vertexes[0], edge.Vertexes[-1]):
                for i, sv in enumerate(obj.Shape.Vertexes):
                    if sv.isSame(v):
                        names.append(f"Vertex{i + 1}")
                        break
            if len(names) == 2:
                _set_support(f, [(obj, n) for n in names])
                set_enum(f, "MapMode", ["TwoPointLine"])
            else:
                _set_support(f, [(obj, sub)])
                set_enum(f, "MapMode", ["ObjectX", "TangentU", "Tangent"])
            self.kind.setText("Along the edge")
        else:
            self.kind.setText("Pick a round face, an edge, two points or two planes")

    def load(self, f):
        prop = "AttachmentSupport" if has(f, "AttachmentSupport") else "Support"
        items = []
        for obj, subs in getattr(f, prop, []) or []:
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]) or [""]:
                items.append((obj, sub))
        self.refs.set(items)

    def error_text(self):
        return "<b>The axis can't be made</b> from these references."


def plane(feature=None):
    open_panel(PlanePanel, feature)


def axis(feature=None):
    open_panel(AxisPanel, feature)
