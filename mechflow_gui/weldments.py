# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Weldments: Structural Member and Cut List.

Structural Member: pick sketch lines (from one or more sketches - a frame
drawn on several planes works), a profile (UKB, UKC, PFC, angle, SHS, RHS,
CHS) and a size. Each line becomes a member, cut at the corners:

- End miter: both members cut on the bisecting plane;
- End butt 1 / End butt 2: one member runs through to the outside of the
  other, which stops against it;
- three or more members at a point, or a member ending on the side of
  another: it stops against the one it meets.

The members are one object (like SOLIDWORKS' structural member group); edit
it to change the profile, size, rotation or corner treatment. The Cut List
lists them by profile and length, with the cut angles.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from mechflow_gui import steel_data as D

V = App.Vector
CORNERS = ["End miter", "End butt 1", "End butt 2"]
TOL = 1e-4


# ------------------------------------------------------------ profiles

def _rect(x0, y0, x1, y1):
    import Part
    return Part.Face(Part.makePolygon([V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0),
                                       V(x0, y1, 0), V(x0, y0, 0)]))


def _rounded_rect(w, h, r):
    import Part
    if r <= 1e-6:
        return _rect(-w / 2, -h / 2, w / 2, h / 2)
    core = _rect(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r)
    return Part.Face(core.makeOffset2D(r, 0, False, False, False).Wires[0])


def profile(t, size):
    """(face in the XY plane, centred on its bounding box, [(x, y, r)] edges
    to round along the member: root and toe radii)."""
    row = D.TYPES[t][1][size]
    if t in ("UKB", "UKC"):
        h, b, tw, tf, r = row
        f = _rect(-b / 2, h / 2 - tf, b / 2, h / 2).fuse(_rect(-b / 2, -h / 2, b / 2, -h / 2 + tf))
        f = f.fuse(_rect(-tw / 2, -h / 2 + tf, tw / 2, h / 2 - tf)).removeSplitter()
        y = h / 2 - tf
        return f.Faces[0], [(sx * tw / 2, sy * y, r) for sx in (-1, 1) for sy in (-1, 1)]
    if t == "PFC":
        h, b, tw, tf, r = row
        x0 = -b / 2
        f = _rect(x0, -h / 2, x0 + tw, h / 2).fuse(_rect(x0, h / 2 - tf, b / 2, h / 2))
        f = f.fuse(_rect(x0, -h / 2, b / 2, -h / 2 + tf)).removeSplitter()
        return f.Faces[0], [(x0 + tw, h / 2 - tf, r), (x0 + tw, -h / 2 + tf, r)]
    if t == "EA":
        a, th, r1, r2 = row
        x0 = y0 = -a / 2
        f = _rect(x0, y0, x0 + a, y0 + th).fuse(_rect(x0, y0, x0 + th, y0 + a)).removeSplitter()
        return f.Faces[0], [(x0 + th, y0 + th, r1), (x0 + a, y0 + th, r2), (x0 + th, y0 + a, r2)]
    if t.startswith("SHS") or t.startswith("RHS"):
        h, b, th = row
        ro, ri = D.corner_radii("hot" if t.endswith("-H") else "cold", th)
        outer = _rounded_rect(b, h, ro)
        inner = _rounded_rect(b - 2 * th, h - 2 * th, ri)
        return outer.cut(inner).Faces[0], []
    if t == "CHS":
        d, th = row
        import Part
        outer = Part.Face(Part.Wire(Part.makeCircle(d / 2)))
        inner = Part.Face(Part.Wire(Part.makeCircle(d / 2 - th)))
        return outer.cut(inner).Faces[0], []
    raise ValueError(t)


def designation(t, size):
    name = D.TYPES[t][2]
    if t == "CHS":
        return f"CHS {size}"
    return f"{name} {size}"


def _bar(t, size, length, rotation, mirror):
    """Straight member in its own axes: profile in XY, running up +Z."""
    face, rounds = profile(t, size)
    solid = face.extrude(V(0, 0, length))
    if rounds:
        by_r = {}
        for i, e in enumerate(solid.Edges):
            if type(getattr(e, "Curve", None)).__name__ not in ("Line", "LineSegment"):
                continue
            p, q = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if abs(p.x - q.x) > TOL or abs(p.y - q.y) > TOL:
                continue
            for x, y, r in rounds:
                if abs(p.x - x) < 1e-3 and abs(p.y - y) < 1e-3:
                    by_r.setdefault(r, []).append(e)
        for r, edges in by_r.items():
            try:
                solid = solid.makeFillet(r, edges)
            except Exception:
                pass
    m = App.Matrix()
    if mirror:
        m.scale(-1, 1, 1)
    if mirror:
        solid = solid.transformGeometry(m)
    if rotation:
        solid.rotate(V(0, 0, 0), V(0, 0, 1), rotation)
    return solid


# ------------------------------------------------------------ the frame

class Seg:
    def __init__(self, obj, sub, a, b, normal):
        self.obj, self.sub = obj, sub
        self.a, self.b = a, b
        self.dir = (b - a)
        self.length = self.dir.Length
        self.dir.normalize()
        self.normal = normal       # plane normal of its sketch, or None

    def frame(self):
        """Rotation taking the member's own axes to its place: Z along the
        line, Y ('up', the depth of a beam) in the sketch plane."""
        z = self.dir
        if self.normal is not None and abs(self.normal.dot(z)) < 0.999:
            y = self.normal.cross(z)
        else:
            up = V(0, 0, 1) if abs(z.z) < 0.999 else V(1, 0, 0)
            y = up - z * up.dot(z)
        y.normalize()
        x = y.cross(z)
        x.normalize()
        m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
        return App.Rotation(m)


def segments(links):
    """Seg for every straight line in [(obj, [subs])] (all lines of an
    object listed without subs)."""
    import Part
    out = []
    for obj, subs in links:
        normal = None
        if obj.isDerivedFrom("Part::Part2DObject"):
            normal = obj.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
        subs = [x for x in (subs or []) if x]
        names = subs or [f"Edge{i + 1}" for i in range(len(obj.Shape.Edges))]
        for sub in names:
            try:
                e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
            except Exception:
                continue
            if type(getattr(e, "Curve", None)).__name__ not in ("Line", "LineSegment"):
                continue
            if e.Length < 1e-6:
                continue
            out.append(Seg(obj, sub, e.Vertexes[0].Point, e.Vertexes[-1].Point, normal))
    return out


def _halfspace(p, n, keep_negative, size):
    """A big box on one side of the plane through p with normal n."""
    import Part
    box = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, 0 if not keep_negative else -size))
    # box occupies z in [0, size] (positive side) or [-size, 0]
    rot = App.Rotation(V(0, 0, 1), n)
    box.Placement = App.Placement(p, rot)
    return box


def build(segs, t, size, rotation=0.0, mirror=False, corner=CORNERS[0], trims=None,
          trim_type="Planar"):
    """[(solid, info)] for the members of a frame. trims: [(seg or None,
    solid)] boundaries free member ends are trimmed / extended to."""
    face, _r = profile(t, size)
    bb = face.BoundBox
    big = 4 * max(bb.XLength, bb.YLength) + 10
    span = max(s.length for s in segs) + 4 * big
    # nodes: shared end points
    ends = []
    for i, s in enumerate(segs):
        ends.append((i, 0, s.a))
        ends.append((i, 1, s.b))
    nodes = []
    for e in ends:
        for nd in nodes:
            if (nd[0][2] - e[2]).Length < 1e-3:
                nd.append(e)
                break
        else:
            nodes.append([e])
    ext = {(i, k): 0.0 for i in range(len(segs)) for k in (0, 1)}
    cuts = {i: [] for i in range(len(segs))}      # (kind, data)
    angles = {(i, k): 0.0 for i in range(len(segs)) for k in (0, 1)}

    def raw(i, e0=None, e1=None):
        s = segs[i]
        e0 = ext[(i, 0)] if e0 is None else e0
        e1 = ext[(i, 1)] if e1 is None else e1
        solid = _bar(t, size, s.length + e0 + e1, rotation, mirror)
        solid.Placement = App.Placement(s.a - s.dir * e0, s.frame())
        return solid

    def out_dir(i, k):
        """Direction of member i going out of its end k (into the node)."""
        return segs[i].dir if k == 1 else segs[i].dir * -1

    def extent(i, k, along):
        """How far member i's cross-section reaches along a direction, at end k."""
        sol = raw(i, 0.0, 0.0)
        p = segs[i].b if k == 1 else segs[i].a
        vals = [(v.Point - p).dot(along) for v in sol.Vertexes
                if abs((v.Point - p).dot(segs[i].dir)) < 1e-3]
        return max(vals) if vals else 0.0

    for nd in nodes:
        if len(nd) == 2:
            (i, ki, p), (j, kj, _q) = nd
            u1 = out_dir(i, ki)            # i runs into the node along u1
            u2 = out_dir(j, kj) * -1       # j leaves the node along u2
            if abs(u1.dot(u2)) > 0.9999 and u1.dot(u2) > 0:
                continue                   # straight on: butt, nothing to do
            if corner == CORNERS[0]:
                n = u1 + u2
                n.normalize()
                ext[(i, ki)] = ext[(j, kj)] = big
                cuts[i].append(("keep_neg", p, n))
                cuts[j].append(("keep_pos", p, n))
                ang = math.degrees(math.acos(max(-1.0, min(1.0, abs(n.dot(u1))))))
                angles[(i, ki)] = angles[(j, kj)] = ang
            else:
                run, stop = ((i, ki), (j, kj)) if corner == CORNERS[1] else ((j, kj), (i, ki))
                ru = out_dir(*run)
                ext[run] = max(0.0, extent(stop[0], stop[1], ru))
                ext[stop] = big
                cuts[stop[0]].append(("against", run[0], stop[1]))
        elif len(nd) > 2:
            first = nd[0]
            for other in nd[1:]:
                ru = out_dir(first[0], first[1])
                ext[(first[0], first[1])] = max(ext[(first[0], first[1])],
                                                extent(other[0], other[1], ru))
                ext[(other[0], other[1])] = big
                cuts[other[0]].append(("against", first[0], other[1]))
    # members ending on the side of another
    for nd in nodes:
        if len(nd) != 1:
            continue
        i, k, p = nd[0]
        for j, s in enumerate(segs):
            if j == i:
                continue
            tpar = (p - s.a).dot(s.dir)
            if TOL < tpar < s.length - TOL and ((s.a + s.dir * tpar) - p).Length < 1e-3:
                ext[(i, k)] = big
                cuts[i].append(("against", j, k))
                break
        else:
            # Trim / Extend: a free end reaching another member or body
            hit = _boundary_hit(segs[i], k, trims or [], big) if trims else None
            if hit is not None:
                dist, bseg, bsolid = hit
                ext[(i, k)] = max(0.0, dist) + big
                cuts[i].append(("boundary", (bseg, bsolid), k))
    result = []
    for i, s in enumerate(segs):
        solid = raw(i)
        for kind, a, b in cuts[i]:
            if kind == "keep_neg":
                solid = solid.cut(_halfspace(a, b, False, span))
            elif kind == "keep_pos":
                solid = solid.cut(_halfspace(a, b, True, span))
            elif kind == "boundary":
                bseg, bsolid = a
                if bseg is not None and trim_type == "Planar":
                    solid, ang = _stop_against(solid, s, b, bseg, bsolid, span)
                else:
                    solid, ang = _stop_body(solid, s, b, bsolid), 0.0
                angles[(i, b)] = ang
            else:                           # against member a, at our end b
                solid, ang = _stop_against(solid, s, b, segs[a], raw(a), span)
                angles[(i, b)] = ang
        result.append((solid, dict(seg=s, angle0=angles[(i, 0)], angle1=angles[(i, 1)])))
    return result


def _boundary_hit(s, k, trims, size):
    """(distance along the member past its end, boundary seg, boundary solid)
    for the nearest boundary the free end k of s runs into (or is in)."""
    import Part
    p = s.b if k == 1 else s.a
    u = s.dir if k == 1 else s.dir * -1
    best = None
    for bseg, bsolid in trims:
        if bseg is not None:
            # closest approach of the two lines
            d = bseg.dir
            w0 = p - bseg.a
            b = u.dot(d)
            den = 1 - b * b
            if den < 1e-9:
                continue
            tt = (b * w0.dot(d) - w0.dot(u)) / den
            ss = (w0.dot(d) - b * w0.dot(u)) / den
            gap = ((p + u * tt) - (bseg.a + d * ss)).Length
            if gap > 2 * size or not (-size <= ss <= bseg.length + size):
                continue
            if tt < -size or tt > 1e5:
                continue
            if best is None or tt < best[0]:
                best = (tt, bseg, bsolid)
        else:
            try:
                ray = Part.Edge(Part.LineSegment(p - u * size, p + u * 1e5))
                common = ray.common(bsolid)
            except Exception:
                continue
            pts = [v.Point for v in common.Vertexes]
            if not pts:
                continue
            tt = min((q - p).dot(u) for q in pts)
            if best is None or tt < best[0]:
                best = (tt, None, bsolid)
    return best


def _stop_body(solid, s, k, body):
    """Cut a member to the shape of a body it runs into (coped)."""
    import Part
    try:
        pieces = solid.cut(body).Solids
    except Exception:
        return solid
    if not pieces:
        return solid
    far = s.a if k == 1 else s.b
    return min(pieces, key=lambda x: x.distToShape(Part.Vertex(far))[0])


def _stop_against(solid, s, k, other, other_solid, span):
    """Cut member s square to the face of the other member it meets at its
    end k (the flat face, as a fabricator would cut it)."""
    p = s.b if k == 1 else s.a
    u_in = s.dir if k == 1 else s.dir * -1           # into the joint
    d = other.dir
    w = u_in * -1
    w = w - d * w.dot(d)
    if w.Length < 1e-6:
        return solid, 0.0
    w.normalize()
    angle = math.degrees(math.acos(max(-1.0, min(1.0, abs(w.dot(s.dir))))))
    # the other member's axis point nearest the joint
    axis_pt = other.a + d * (p - other.a).dot(d)
    e = max(((v.Point - axis_pt) - d * (v.Point - axis_pt).dot(d)).dot(w)
            for v in other_solid.Vertexes)
    face_pt = axis_pt + w * e
    cut = solid.cut(_halfspace(face_pt, w, True, span))
    far = s.a if k == 1 else s.b
    pieces = cut.Solids
    if not pieces:
        return solid, 0.0
    import Part
    return min(pieces, key=lambda x: x.distToShape(Part.Vertex(far))[0]), angle


# ------------------------------------------------------------ the object

class StructuralMember:
    def __init__(self, obj, t, size, links):
        obj.addProperty("App::PropertyLinkSubListGlobal", "Path", "Structural member",
                        "Sketch lines the members follow")
        obj.addProperty("App::PropertyEnumeration", "Profile", "Structural member",
                        "Section type")
        obj.addProperty("App::PropertyEnumeration", "Size", "Structural member", "Section size")
        obj.addProperty("App::PropertyAngle", "Rotation", "Structural member",
                        "Rotate the profile about the line")
        obj.addProperty("App::PropertyBool", "Mirror", "Structural member",
                        "Mirror the profile (channels and angles)")
        obj.addProperty("App::PropertyEnumeration", "CornerTreatment", "Structural member",
                        "How members meet at corners")
        _add_trim_props(obj)
        obj.Profile = list(D.TYPES.keys())
        obj.Profile = t
        obj.Size = D.sizes(t)
        obj.Size = size
        obj.CornerTreatment = CORNERS
        obj.Path = links
        obj.Proxy = self
        self._last_profile = t

    def onChanged(self, obj, prop):
        if prop == "Profile" and hasattr(obj, "Size"):
            t = obj.Profile
            if getattr(self, "_last_profile", None) != t:
                self._last_profile = t
                cur = obj.Size
                obj.Size = D.sizes(t)
                obj.Size = cur if cur in D.sizes(t) else D.DEFAULT_SIZE[t]

    def execute(self, obj):
        import Part
        _add_trim_props(obj)
        links = [(o, [x for x in s if x]) for o, s in obj.Path]
        segs = segments(links)
        if not segs:
            obj.Shape = Part.Shape()
            return
        parts = build(segs, obj.Profile, obj.Size, float(obj.Rotation), obj.Mirror,
                      obj.CornerTreatment, trim_boundaries(obj), obj.TrimType)
        obj.Shape = Part.makeCompound([p for p, _i in parts])
        obj.Placement = App.Placement()

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _add_trim_props(obj):
    if not hasattr(obj, "TrimTo"):
        obj.addProperty("App::PropertyLinkList", "TrimTo", "Trim/Extend",
                        "Members or bodies this member's free ends are trimmed / extended to")
        obj.addProperty("App::PropertyEnumeration", "TrimType", "Trim/Extend",
                        "Planar: square to the face met. Body: cut to the body's shape")
        obj.TrimType = ["Planar", "Body"]


def trim_boundaries(obj):
    """[(seg or None, solid)] for an object's Trim/Extend boundaries."""
    out = []
    for b in getattr(obj, "TrimTo", []) or []:
        if b is obj or not hasattr(b, "Shape") or b.Shape.isNull():
            continue
        if is_member(b):
            bsegs = segments([(o, [x for x in s_ if x]) for o, s_ in b.Path])
            sols = b.Shape.Solids
            if len(sols) == len(bsegs):
                out += list(zip(bsegs, sols))
                continue
        for sol in b.Shape.Solids:
            out.append((None, sol))
    return out


class ViewProviderStructuralMember:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path("StructuralMember.svg")

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(MemberPanel(vobj.Object))
        return True

    def unsetEdit(self, vobj, mode=0):
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_member(o):
    return type(getattr(o, "Proxy", None)).__name__ == "StructuralMember"


def _all_lines(obj):
    return [f"Edge{i + 1}" for i, e in enumerate(obj.Shape.Edges)
            if type(getattr(e, "Curve", None)).__name__ in ("Line", "LineSegment")]


def _expand(links):
    """A whole sketch picked: all its lines."""
    out = []
    for o, subs in links:
        subs = [x for x in (subs or []) if x] or _all_lines(o)
        if subs:
            out.append((o, subs))
    return out


def _top(o):
    try:
        return o.getParentGeoFeatureGroup() is None and not any(
            p.TypeId in ("App::Part", "PartDesign::Body") or p.isDerivedFrom("App::Part")
            for p in o.InList if hasattr(p, "Group") and o in p.Group)
    except Exception:
        return False


def into_part(obj, sources=()):
    """Keep a weldment part as one component (SOLIDWORKS: a weldment is one
    part file): put the member / plate in the document's Part container with
    the body and the layout sketches, making the container if needed. Then
    the file goes into an assembly with Insert Components in one go."""
    doc = obj.Document
    if any(p.TypeId == "Assembly::AssemblyObject" for p in doc.Objects):
        return None                # built inside an assembly: leave it where it is
    parts = [p for p in doc.Objects if p.TypeId == "App::Part" and _top(p)]
    part = None
    if len(parts) == 1:
        part = parts[0]
    elif not parts:
        part = doc.addObject("App::Part", "Part")
        for b in doc.Objects:
            if b is not part and b.TypeId == "PartDesign::Body" and _top(b):
                if b.Label == doc.Label:
                    b.Label = "Body"            # the Part takes the part's name
                part.addObject(b)
        part.Label = doc.Label
        for o in doc.Objects:
            if (is_member(o) or type(getattr(o, "Proxy", None)).__name__ in ("EndCap", "Gusset")) \
                    and o is not obj and _top(o):
                part.addObject(o)
                for src in getattr(o, "Path", []) or []:
                    if _top(src[0]) and src[0].TypeId == "Sketcher::SketchObject":
                        part.addObject(src[0])
        # flanges / fasteners already fitted to the part (e.g. on its nozzles)
        for o in doc.Objects:
            if o is not part and _top(o) and (
                    hasattr(o, "StdType") or type(getattr(o, "Proxy", None)).__name__
                    in ("FSScrewObject", "FSWasherObject", "FSNutObject")):
                part.addObject(o)
    else:
        return None                # several Parts: the user has their own layout
    if _top(obj):
        part.addObject(obj)
    for src in sources:
        if src is not None and src.TypeId == "Sketcher::SketchObject" and _top(src):
            part.addObject(src)
    return part


def make(t, size, links, doc=None):
    doc = doc or App.ActiveDocument
    links = _expand(links)
    o = doc.addObject("Part::FeaturePython", "StructuralMember")
    StructuralMember(o, t, size, links)
    if App.GuiUp:
        ViewProviderStructuralMember(o.ViewObject)
        try:
            o.ViewObject.ShapeColor = (0.62, 0.66, 0.72)
        except Exception:
            pass
    o.Label = designation(t, size)
    into_part(o, [lk[0] for lk in links])
    doc.recompute()
    return o


# ------------------------------------------------------------ panel

def _selected_links():
    out = {}
    for s in Gui.Selection.getSelectionEx():
        o = s.Object
        if is_member(o):
            continue
        subs = [n for n in s.SubElementNames if n.startswith("Edge")]
        if not subs and not o.isDerivedFrom("Part::Part2DObject"):
            continue
        if not subs:
            subs = _all_lines(o)
        out.setdefault(o, [])
        for n in subs:
            if n not in out[o]:
                out[o].append(n)
    return out


class MemberPanel:
    def __init__(self, obj=None):
        self.obj = obj
        self.new = obj is None
        self.links = {}
        if obj is not None:
            for o, subs in obj.Path:
                self.links[o] = list(subs)
            self._orig = (obj.Profile, obj.Size, float(obj.Rotation), obj.Mirror,
                          obj.CornerTreatment, [(o, list(s)) for o, s in obj.Path])
        else:
            self.links = _selected_links()
        Gui.Selection.clearSelection()
        self.form = self._build()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        if self.obj is None and self.links:
            self._create()
        self._refresh()

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Structural Member")
        lay = QtWidgets.QVBoxLayout(w)
        sel = QtWidgets.QGroupBox("Selections")
        f = QtWidgets.QFormLayout(sel)
        self.std = QtWidgets.QComboBox()
        self.std.addItem("UK / EN")
        f.addRow("Standard", self.std)
        self.type = QtWidgets.QComboBox()
        for k, v in D.TYPES.items():
            self.type.addItem(v[0], k)
        f.addRow("Type", self.type)
        self.size = QtWidgets.QComboBox()
        self.size.setEditable(True)
        self.size.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        f.addRow("Size", self.size)
        lay.addWidget(sel)
        g = QtWidgets.QGroupBox("Path segments")
        gl = QtWidgets.QVBoxLayout(g)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(110)
        gl.addWidget(self.list)
        clr = QtWidgets.QPushButton("Clear")
        clr.clicked.connect(self._clear)
        gl.addWidget(clr)
        lay.addWidget(g)
        st = QtWidgets.QGroupBox("Settings")
        sf = QtWidgets.QFormLayout(st)
        self.corner = QtWidgets.QComboBox()
        self.corner.addItems(CORNERS)
        sf.addRow("Corner", self.corner)
        self.rot = QtWidgets.QDoubleSpinBox()
        self.rot.setRange(-360, 360)
        self.rot.setSuffix(" °")
        self.rot.setSingleStep(90)
        sf.addRow("Rotation", self.rot)
        self.mirror = QtWidgets.QCheckBox("Mirror profile")
        sf.addRow("", self.mirror)
        lay.addWidget(st)
        self.msg = QtWidgets.QLabel("Click sketch lines (or a whole sketch) for the members. "
                                    "Click a line again to remove it.")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        lay.addWidget(self.msg)
        if self.obj is not None:
            self.type.setCurrentIndex(max(0, self.type.findData(self.obj.Profile)))
        self._fill_sizes()
        if self.obj is not None:
            self.size.setCurrentText(self.obj.Size)
            self.rot.setValue(float(self.obj.Rotation))
            self.mirror.setChecked(self.obj.Mirror)
            self.corner.setCurrentText(self.obj.CornerTreatment)
        self.type.currentIndexChanged.connect(self._type_changed)
        self.size.currentTextChanged.connect(self._apply)
        self.corner.currentTextChanged.connect(self._apply)
        self.rot.valueChanged.connect(self._apply)
        self.mirror.toggled.connect(self._apply)
        return w

    def _fill_sizes(self):
        t = self.type.currentData()
        self.size.blockSignals(True)
        self.size.clear()
        self.size.addItems(D.sizes(t))
        self.size.setCurrentText(D.DEFAULT_SIZE[t])
        self.size.blockSignals(False)

    def _type_changed(self, *_):
        self._fill_sizes()
        self._apply()

    def _links_list(self):
        return [(o, subs) for o, subs in self.links.items()]

    def _create(self):
        doc = App.ActiveDocument
        doc.openTransaction("Structural Member")
        self.obj = make(self.type.currentData(), self.size.currentText(), self._links_list())

    def _apply(self, *_):
        t, size = self.type.currentData(), self.size.currentText()
        if size not in D.sizes(t):
            return
        if self.obj is None:
            if self.links:
                self._create()
            return
        o = self.obj
        if o.Profile != t:
            o.Profile = t
        o.Size = size
        o.Rotation = self.rot.value()
        o.Mirror = self.mirror.isChecked()
        o.CornerTreatment = self.corner.currentText()
        o.Path = self._links_list()
        o.Label = designation(t, size)
        o.Document.recompute()

    def _refresh(self):
        self.list.clear()
        n = 0
        for o, subs in self.links.items():
            for s in (subs or ["(all lines)"]):
                self.list.addItem(f"{o.Label}: {s}")
                n += 1
        if self.obj is not None and self.obj.Shape.Solids:
            self.msg.setText(f"{len(self.obj.Shape.Solids)} members. Click lines to add or "
                             "remove them.")

    def _poll(self):
        try:
            got = _selected_links()
            if not got:
                return
            Gui.Selection.clearSelection()
            for o, subs in got.items():
                if o is self.obj:
                    continue
                cur = self.links.setdefault(o, [])
                if not subs:
                    if not cur:
                        self.links[o] = []
                    continue
                for s in subs:
                    if s in cur:
                        cur.remove(s)
                        if not cur:
                            del self.links[o]
                    else:
                        cur.append(s)
            self._apply()
            self._refresh()
        except Exception as e:
            App.Console.PrintLog(f"MechFlow structural member: {e}\n")

    def _clear(self):
        self.links = {}
        self._apply()
        self._refresh()

    def accept(self):
        self._timer.stop()
        if self.obj is None:
            Gui.Control.closeDialog()
            return True
        if not self.links:
            QtWidgets.QMessageBox.information(self.form, "Structural Member",
                                              "Pick the sketch lines first.")
            self._timer.start()
            return False
        self._apply()
        doc = self.obj.Document
        if self.new:
            doc.commitTransaction()
        for o, _s in self.links.items():
            try:
                o.ViewObject.Visibility = True
            except Exception:
                pass
        Gui.Control.closeDialog()
        if not self.new:
            Gui.ActiveDocument.resetEdit()
        return True

    def reject(self):
        self._timer.stop()
        if self.new and self.obj is not None:
            doc = self.obj.Document
            doc.removeObject(self.obj.Name)
            doc.abortTransaction()
        elif not self.new and self.obj is not None:
            t, size, rot, mir, corner, path = self._orig
            o = self.obj
            o.Profile, o.Size, o.Rotation, o.Mirror = t, size, rot, mir
            o.CornerTreatment, o.Path = corner, path
            o.Document.recompute()
        Gui.Control.closeDialog()
        if not self.new:
            Gui.ActiveDocument.resetEdit()
        return True


def structural_member():
    if App.ActiveDocument is None:
        App.newDocument()
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Structural Member",
                                          "Finish the open dialog first.")
        return None
    p = MemberPanel()
    Gui.Control.showDialog(p)
    return p


# ------------------------------------------------------------ cut list

def cut_items(doc=None):
    """[(description, length, angle1, angle2, qty)] for every member in the
    document, identical ones counted together."""
    doc = doc or App.ActiveDocument
    rows = {}
    order = []
    for o in doc.Objects:
        if not is_member(o) or not o.Shape.Solids:
            continue
        links = [(x, list(s)) for x, s in o.Path]
        segs = segments(links)
        parts = build(segs, o.Profile, o.Size, float(o.Rotation), o.Mirror, o.CornerTreatment,
                      trim_boundaries(o), getattr(o, "TrimType", "Planar"))
        for solid, info in parts:
            s = info["seg"]
            vals = [(v.Point - s.a).dot(s.dir) for v in solid.Vertexes]
            length = round(max(vals) - min(vals), 1)
            a = sorted((round(info["angle0"], 1), round(info["angle1"], 1)))
            key = (designation(o.Profile, o.Size), length, a[0], a[1])
            if key not in rows:
                rows[key] = 0
                order.append(key)
            rows[key] += 1
    from mechflow_gui import weld_extras
    for o in doc.Objects:
        if weld_extras.is_plate(o) and not o.Shape.isNull():
            desc, size = weld_extras.plate_row(o)
            key = (desc, size, 0.0, 0.0)
            if key not in rows:
                rows[key] = 0
                order.append(key)
            rows[key] += 1
    return [k + (rows[k],) for k in order]


def cut_list():
    from mechflow_gui import bom
    doc = App.ActiveDocument
    if doc is None:
        return None
    items = cut_items(doc)
    if not items:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Cut List",
                                          "There are no structural members in this document.")
        return None
    sh = None
    for o in doc.Objects:
        if o.TypeId == "Spreadsheet::Sheet" and getattr(o, "MechFlowCutList", False):
            sh = o
    doc.openTransaction("Cut List")
    if sh is None:
        sh = doc.addObject("Spreadsheet::Sheet", "CutList")
        sh.addProperty("App::PropertyBool", "MechFlowCutList", "Base", "Weldment cut list", 4)
        sh.MechFlowCutList = True
        sh.Label = "Cut List"
    sh.clearAll()
    heads = ["ITEM NO.", "QTY.", "DESCRIPTION", "LENGTH", "ANGLE1", "ANGLE2"]
    for c, h in zip("ABCDEF", heads):
        sh.set(f"{c}1", h)
    sh.setStyle("A1:F1", "bold")
    for i, (desc, length, a1, a2, qty) in enumerate(items, start=2):
        sh.set(f"A{i}", str(i - 1))
        sh.set(f"B{i}", str(qty))
        sh.set(f"C{i}", "'" + desc)
        sh.set(f"D{i}", f"{length:g}" if not isinstance(length, str) else "'" + length)
        sh.set(f"E{i}", f"{a1:g}")
        sh.set(f"F{i}", f"{a2:g}")
    for c, w in zip("ABCDEF", (70, 50, 200, 80, 70, 70)):
        sh.setColumnWidth(c, w)
    doc.recompute()
    doc.commitTransaction()
    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    dlg.setWindowTitle("Cut List")
    v = QtWidgets.QVBoxLayout(dlg)
    tbl = QtWidgets.QTableWidget(len(items), 6)
    tbl.setHorizontalHeaderLabels(heads)
    tbl.verticalHeader().setVisible(False)
    tbl.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    for r, (desc, length, a1, a2, qty) in enumerate(items):
        ln = length if isinstance(length, str) else f"{length:g}"
        for c, val in enumerate((str(r + 1), str(qty), desc, ln, f"{a1:g}", f"{a2:g}")):
            it = QtWidgets.QTableWidgetItem(val)
            if c != 2:
                it.setTextAlignment(QtCore.Qt.AlignCenter)
            tbl.setItem(r, c, it)
    tbl.resizeColumnsToContents()
    v.addWidget(tbl)
    note = QtWidgets.QLabel(f"Saved in the tree as <b>{sh.Label}</b>. Lengths in mm, cut "
                            "angles in degrees from square.")
    note.setWordWrap(True)
    v.addWidget(note)
    b = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
    b.rejected.connect(dlg.reject)
    v.addWidget(b)
    dlg.resize(560, min(480, 140 + 28 * len(items)))
    dlg.show()
    bom._last[:] = [dlg]
    return items
