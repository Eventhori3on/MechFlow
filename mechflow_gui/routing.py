# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pipe routing (SOLIDWORKS Routing, simplified).

Sketch the pipe's centreline - lines in one sketch or several (for a 3D
run), branches allowed - and Route Pipe fills it in:

- pipe cut to length on every straight,
- an elbow at every bend (EN 10253 2D / 3D / 5D or ASME long radius; other
  angles than 90 / 45 are cut elbows),
- an equal tee where a branch meets a run square on,
- at a route end that starts on a flange face (picked): a gasket, the
  mating weld neck flange and the bolts,
- at the other free ends: plain, a weld neck flange, a blind (weld neck +
  gasket + blind + bolts) or a cap.

The parts are ordinary Toolbox parts (BOM, drawings, interference all see
them). Edit the sketch and the route rebuilds; double-click the route to
change its size or fittings.
"""

import hashlib
import json
import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector
TOL = 0.01
STANDARDS = ["EN", "ASME"]
BENDS = {"EN": ["3D", "2D", "5D"], "ASME": ["LR"]}
ENDS = ["Plain", "Weld neck flange", "Blind flange", "Cap"]


# ------------------------------------------------------------ catalogue

def types_for(std, bend="3D"):
    if std == "ASME":
        return {"pipe": "ASMEB36.10-PIPE", "elbow90": "ASMEB16.9-90LR",
                "elbow45": "ASMEB16.9-45LR", "tee": "ASMEB16.9-TEE",
                "cap": "ASMEB16.9-CAP", "flange": "ASMEB16.5-WN", "blind": "ASMEB16.5-BL"}
    return {"pipe": "EN10220-PIPE", "elbow90": f"EN10253-90-{bend}",
            "elbow45": "EN10253-45-3D" if bend == "3D" else None, "tee": "EN10253-TEE",
            "cap": "EN10253-CAP", "flange": "EN1092-1-11", "blind": "EN1092-1-05"}


def sizes_for(std):
    from mechflow_gui import stdparts
    if std == "ASME":
        return [s for s in stdparts.sizes("ASMEB16.9-90LR")]
    return [s for s in stdparts.sizes("EN10253-90-3D")]


def fitting_dims(std, size, schedule, bend):
    """(od, wall, bend radius, tee C, cap E) in mm."""
    from mechflow_gui import stdparts, stdparts_data as T
    if std == "ASME":
        od, wall = stdparts.asme_pipe(size, schedule)
        A, C, H, E = (x * stdparts.IN if x is not None else None
                      for x in T.B169[stdparts._nps(size)])
        return od, wall, A, C, E
    od, wall, R, C, H, E, _o2, _w2 = stdparts.en_fitting_dims(f"EN10253-90-{bend}", size)
    return od, wall, R, C, E


# ------------------------------------------------------------ geometry

def _rot(z, x_hint=None):
    """Rotation taking local Z to z (and X towards x_hint)."""
    z = V(z).normalize()
    if x_hint is None or abs(V(x_hint).normalize().dot(z)) > 0.999:
        x_hint = V(1, 0, 0) if abs(z.x) < 0.9 else V(0, 1, 0)
    x = V(x_hint) - z * V(x_hint).dot(z)
    x.normalize()
    y = z.cross(x)
    m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
    return App.Placement(m).Rotation


def path_links(o):
    """[(object, [edge names] or None for all)] of a route."""
    out = [(x, None) for x in getattr(o, "PathSketches", [])]
    out += [(x, list(s_)) for x, s_ in o.Path]
    return out


def path_segments(links):
    """[(a, b)] straight segments (in the container's axes) from sketch
    lines. Arcs are refused: bends come from the fittings."""
    segs = []
    for obj, subs in links:
        sh = obj.Shape
        if subs:
            edges = []
            for n in subs:
                try:
                    edges.append((n, sh.getElement(n.lstrip("?"))))
                except Exception:
                    continue
        else:
            edges = [(f"Edge{i + 1}", e) for i, e in enumerate(sh.Edges)]
        for n, e in edges:
            if type(e.Curve).__name__ not in ("Line", "LineSegment"):
                raise ValueError(f"{obj.Label} {n} isn't straight - draw the route with "
                                 "lines; the bends are added for you")
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if (b - a).Length > TOL:
                segs.append((V(a), V(b)))
    if not segs:
        raise ValueError("no lines to route along")
    return segs


class Graph:
    """Route centreline as nodes and straight runs."""

    def __init__(self, segs):
        self.pts = []
        self.adj = {}
        for a, b in segs:
            i, j = self._node(a), self._node(b)
            if i == j:
                continue
            self.adj.setdefault(i, set()).add(j)
            self.adj.setdefault(j, set()).add(i)
        self._merge_straight()
        self._check_tree()

    def _node(self, p):
        for i, q in enumerate(self.pts):
            if (q - p).Length < TOL:
                return i
        self.pts.append(V(p))
        return len(self.pts) - 1

    def dirs(self, i):
        out = []
        for j in self.adj[i]:
            d = self.pts[j] - self.pts[i]
            out.append((j, d.normalize()))
        return out

    def _merge_straight(self):
        changed = True
        while changed:
            changed = False
            for i in list(self.adj):
                if len(self.adj[i]) != 2:
                    continue
                (j, dj), (k, dk) = self.dirs(i)
                if dj.dot(dk) < -1 + 1e-9:          # straight through: one run
                    self.adj[j].discard(i)
                    self.adj[k].discard(i)
                    self.adj[j].add(k)
                    self.adj[k].add(j)
                    del self.adj[i]
                    changed = True
                    break

    def _check_tree(self):
        n_nodes = len(self.adj)
        n_edges = sum(len(v) for v in self.adj.values()) // 2
        if n_edges != n_nodes - 1:
            raise ValueError("the route has a loop or separate pieces - it must be one "
                             "connected run (branches are fine)")

    def edges(self):
        out = []
        for i, js in self.adj.items():
            for j in js:
                if i < j:
                    out.append((i, j))
        return out


def plan(route_like, starts=()):
    """What to build: [{type, size, rating, length, placement, angle, role}]
    plus end info. route_like has Standard, Size, Schedule, Bend, FreeEnds,
    FlangeRating and a path. starts: [(node point, weld-end point, outward
    dir)] for ends that bolt to an existing flange."""
    std = route_like["Standard"]
    size, sched, bend = route_like["Size"], route_like["Schedule"], route_like["Bend"]
    ty = types_for(std, bend)
    od, wall, R, C, E = fitting_dims(std, size, sched, bend)
    rating_pipe = sched if std == "ASME" else ""
    g = Graph(route_like["segments"])
    trim = {}          # (node, neighbour) -> how far the pipe stops short of node
    parts = []
    ends = []
    for i in g.adj:
        ds = g.dirs(i)
        p = g.pts[i]
        if len(ds) == 1:
            j, u = ds[0]                  # u: from the end into the route
            ends.append((i, j, u))
            continue
        if len(ds) == 2:
            (j, a), (k, b) = ds
            bend_deg = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, a.dot(b)))))
            T = R * math.tan(math.radians(bend_deg) / 2)
            trim[(i, j)] = trim[(i, k)] = T
            t90, t45 = ty["elbow90"], ty["elbow45"]
            use = t45 if (t45 and bend_deg <= 45.0 + 1e-6) else t90
            std_ang = 45.0 if use == t45 else 90.0
            angle = 0.0 if abs(bend_deg - std_ang) < 1e-6 else bend_deg
            if bend_deg > 90.0 + 1e-6:
                raise ValueError(f"a bend of {bend_deg:.1f}° is tighter than a 90° "
                                 "elbow - add a straight between two elbows")
            # elbow: inlet on the a side, travelling -a, turning towards b
            inlet = p + a * T
            parts.append({"type": use, "size": size, "rating": rating_pipe, "length": 0.0,
                          "angle": angle, "role": "elbow",
                          "placement": App.Placement(inlet, _rot(-a, b))})
            continue
        if len(ds) == 3:
            pair = None
            for x in range(3):
                for y in range(x + 1, 3):
                    if ds[x][1].dot(ds[y][1]) < -1 + 1e-6:
                        pair = (x, y)
            if pair is None:
                raise ValueError("at a branch two of the lines must be in line (the run)")
            br = [z for z in range(3) if z not in pair][0]
            run_a, run_b, branch = ds[pair[0]], ds[pair[1]], ds[br]
            if abs(branch[1].dot(run_a[1])) > 1e-3:
                raise ValueError("a branch must meet the run square on (equal tee)")
            for j, _d in ds:
                trim[(i, j)] = C
            parts.append({"type": ty["tee"], "size": size, "rating": rating_pipe, "length": 0.0,
                          "angle": 0.0, "role": "tee",
                          "placement": App.Placement(p + run_a[1] * C, _rot(-run_a[1], branch[1]))})
            continue
        raise ValueError("more than three lines meet at one point")
    # ends
    from mechflow_gui import stdparts
    frate = route_like["FlangeRating"] or stdparts.default_rating(ty["flange"])
    fsize = size
    end_info = []
    for i, j, u in ends:
        p = g.pts[i]
        st = None
        for sp, weld, out in starts:
            # an end on a picked flange: the pipe starts at the mating flange's weld end
            if (sp - p).Length < 1.0 or abs((weld - p).cross(u).Length) < 1.0:
                st = (sp, weld)
        if st is not None:
            trim[(i, j)] = (st[1] - p).dot(u)
            end_info.append(("joint", i))
            continue
        mode = route_like["FreeEnds"]
        if mode in ("Weld neck flange", "Blind flange"):
            H = stdparts._length_in_part(ty["flange"], fsize, frate)
            trim[(i, j)] = H
            parts.append({"type": ty["flange"], "size": fsize, "rating": frate, "length": 0.0,
                          "angle": 0.0, "role": "end-flange" if mode == "Weld neck flange"
                          else "end-flange-blind",
                          "placement": App.Placement(p + u * H, _rot(-u))})
        elif mode == "Cap":
            trim[(i, j)] = E
            parts.append({"type": ty["cap"], "size": size, "rating": rating_pipe, "length": 0.0,
                          "angle": 0.0, "role": "cap",
                          "placement": App.Placement(p + u * E, _rot(-u))})
        else:
            trim[(i, j)] = 0.0
        end_info.append((mode, i))
    # pipes
    for i, j in g.edges():
        a, b = g.pts[i], g.pts[j]
        d = b - a
        L = d.Length
        d.normalize()
        ta, tb = trim.get((i, j), 0.0), trim.get((j, i), 0.0)
        ln = L - ta - tb
        if ln < 1.0:
            raise ValueError(f"the straight from {_fmt(a)} to {_fmt(b)} is too short for "
                             f"its fittings ({L:.0f} mm, needs more than {ta + tb:.0f} mm)")
        parts.append({"type": ty["pipe"], "size": size, "rating": rating_pipe,
                      "length": round(ln, 1), "angle": 0.0, "role": "pipe",
                      "placement": App.Placement(a + d * ta, _rot(d))})
    return parts, end_info


def _fmt(p):
    return "(" + ", ".join(f"{x:.0f}" for x in (p.x, p.y, p.z)) + ")"


# ------------------------------------------------------------ the route object

class PipeRoute:
    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkListGlobal", "PathSketches", "Route",
                        "Sketches the pipe follows (all their lines)")
        obj.addProperty("App::PropertyLinkSubListGlobal", "Path", "Route",
                        "Single sketch lines the pipe follows")
        obj.addProperty("App::PropertyLinkSubListGlobal", "StartFlanges", "Route",
                        "Flange faces the route bolts to (gasket, mating flange, bolts)")
        obj.addProperty("App::PropertyEnumeration", "Standard", "Route", "EN or ASME parts")
        obj.Standard = STANDARDS
        obj.addProperty("App::PropertyString", "Size", "Route", "DN.. / NPS ..")
        obj.addProperty("App::PropertyString", "Schedule", "Route", "ASME schedule")
        obj.addProperty("App::PropertyString", "Bend", "Route", "Elbows: 3D / 2D / 5D / LR")
        obj.addProperty("App::PropertyEnumeration", "FreeEnds", "Route",
                        "How the route's other ends finish")
        obj.FreeEnds = ENDS
        obj.addProperty("App::PropertyString", "FlangeRating", "Route", "PN16 / Class 150 ...")
        obj.addProperty("App::PropertyLinkListHidden", "Parts", "Route", "The route's parts")
        obj.addProperty("App::PropertyString", "Built", "Route", "", 4)
        obj.addProperty("App::PropertyString", "Error", "Route", "Why it couldn't be built", 1)
        obj.Proxy = self

    def execute(self, obj):
        # Parts are made outside the recompute (see _Observer); here just
        # notice that the path or settings changed.
        return

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderPipeRoute:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path("Route.svg")

    def claimChildren(self):
        try:
            return list(self.Object.Parts)
        except Exception:
            return []

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.Control.showDialog(RoutePanel(vobj.Object))
        return True

    def onDelete(self, vobj, subs):
        clear_parts(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_route(o):
    return type(getattr(o, "Proxy", None)).__name__ == "PipeRoute"


def _container(o):
    try:
        p = o.getParentGeoFeatureGroup()
    except Exception:
        p = None
    if p is not None:
        return p
    for x in o.InList:
        if x.TypeId == "Assembly::AssemblyObject" or x.isDerivedFrom("App::Part"):
            return x
    return None


def settings(o):
    return {"Standard": o.Standard, "Size": o.Size, "Schedule": o.Schedule,
            "Bend": o.Bend, "FreeEnds": o.FreeEnds, "FlangeRating": o.FlangeRating}


def signature(o):
    """Hash of everything the parts depend on."""
    h = hashlib.sha1()
    h.update(json.dumps(settings(o), sort_keys=True).encode())
    try:
        for a, b in path_segments(path_links(o)):
            h.update(_fmt(a).encode() + _fmt(b).encode())
    except Exception as e:
        h.update(str(e).encode())
    for x, subs in o.StartFlanges:
        for s in subs:
            try:
                import Part
                e = Part.getShape(x, s, needSubElement=True, noElementMap=True)
                h.update(_fmt(e.Curve.Center).encode() + _fmt(V(e.Curve.Axis)).encode())
            except Exception:
                h.update(s.encode())
    return h.hexdigest()


def clear_parts(o):
    """Remove the route's parts - and any left from an unfinished build."""
    doc = o.Document
    names = {p.Name for p in o.Parts}
    names |= {x.Name for x in doc.Objects if getattr(x, "MechFlowRoute", None) == o.Name}
    o.Parts = []
    for n in names:
        try:
            if doc.getObject(n) is not None:
                doc.removeObject(n)
        except Exception:
            pass


def _describe(m):
    try:
        return f"{m.Label} ({m.Document.Name})"
    except Exception:
        return repr(m)


def _tag(objs, route):
    for m in objs:
        if not hasattr(m, "MechFlowRoute"):
            m.addProperty("App::PropertyString", "MechFlowRoute", "Base", "Route it belongs to", 4)
        m.MechFlowRoute = route.Name


def _far_circle(obj, r, from_pt):
    best = None
    for i, e in enumerate(obj.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - r) < 1e-3:
            d = (c.Center - from_pt).Length
            if best is None or d > best[1]:
                best = (f"Edge{i + 1}", d, c.Center)
    return best


_BUILDING = [0]


def build(o):
    """(Re)make the route's parts. Returns the parts (raises on errors)."""
    _BUILDING[0] += 1
    try:
        return _build(o)
    finally:
        _BUILDING[0] -= 1


def _build(o):
    from mechflow_gui import stdparts
    doc = o.Document
    container = _container(o)
    clear_parts(o)
    s = settings(o)
    ty = types_for(o.Standard, o.Bend)
    made = []
    starts = []
    # joints on the picked flanges first: their weld ends are where pipe starts
    for x, subs in o.StartFlanges:
        for sub in subs:
            joint = stdparts.place(container, ty["flange"], x, sub, joint=True)
            _tag(joint, o)
            made += joint
            mate = [m for m in joint if getattr(m, "StdType", "") == ty["flange"]][0]
            info = stdparts.flange_info(mate.StdType, mate.Size, mate.Rating)
            face, n = stdparts._face_frame(mate)
            od = stdparts.outside_diameter(mate.StdType, mate.Size, mate.Rating)
            weld = _far_circle(mate, od / 2, face)
            if weld is None:
                continue
            wp = weld[2]
            if container is not None and hasattr(container, "Placement"):
                pass
            starts.append((face, wp, n))
            if not s["Size"]:
                s["Size"] = mate.Size
    segs = path_segments(path_links(o))
    s["segments"] = segs
    if not s["Size"]:
        s["Size"] = sizes_for(o.Standard)[0]
    parts, ends = plan(s, starts)
    for p in parts:
        part = stdparts.make(container, p["type"], p["size"], p["rating"] or None,
                             p["length"] or 1000.0)
        if p["angle"]:
            stdparts.set_bend_angle(part, p["angle"])
        part.Placement = p["placement"]
        _tag([part], o)
        made.append(part)
        if p["role"] == "end-flange-blind":
            info = stdparts.flange_info(part.StdType, part.Size, part.Rating)
            doc.recompute()
            face, n = stdparts._face_frame(part)
            best = None
            for i, e in enumerate(part.Shape.Edges):
                c = getattr(e, "Curve", None)
                if type(c).__name__ == "Circle" and abs(2 * c.Radius - info["face"]) < 1e-3:
                    dd = (c.Center - face).Length
                    if best is None or dd < best[1]:
                        best = (f"Edge{i + 1}", dd)
            if best:
                bl = stdparts.place(container, ty["blind"], part, best[0], joint=True)
                _tag(bl, o)
                made += bl
    ok, bad = [], []
    for m in made:
        try:
            alive = m.Document is doc and doc.getObject(m.Name) is m
        except Exception:
            alive = False
        (ok if alive else bad).append(m)
    if bad:
        App.Console.PrintWarning(f"MechFlow: {o.Label}: {len(bad)} parts not in this document: "
                                 + ", ".join(_describe(b) for b in bad) + "\n")
    o.Parts = ok
    o.Built = signature(o)
    o.Error = ""
    doc.recompute()
    return made


def make_route(container, path_links, standard="EN", size="", schedule="Sch 40", bend="3D",
               free_ends="Weld neck flange", flange_rating="", starts=(), build_now=True):
    doc = container.Document if container is not None else App.ActiveDocument
    o = doc.addObject("App::FeaturePython", "Route")
    PipeRoute(o)
    if container is not None:
        container.addObject(o)
    if App.GuiUp:
        ViewProviderPipeRoute(o.ViewObject)
    o.PathSketches = [x for x, s_ in path_links if s_ is None]
    o.Path = [(x, tuple(s_)) for x, s_ in path_links if s_]
    if starts:
        o.StartFlanges = [(x, (s,)) for x, s in starts]
    o.Standard = standard
    o.Size = size
    o.Schedule = schedule
    o.Bend = bend
    o.FreeEnds = free_ends
    o.FlangeRating = flange_rating
    n = 1 + sum(1 for x in doc.Objects if is_route(x) and x is not o)
    o.Label = f"Route{n}"
    if build_now:
        build(o)
    return o


# ------------------------------------------------------------ live rebuild

class _Observer:
    def __init__(self):
        self.busy = False

    def slotRecomputedDocument(self, doc):
        if self.busy or _BUILDING[0]:
            return
        routes = [o for o in doc.Objects if is_route(o)]
        if routes:
            QtCore.QTimer.singleShot(0, lambda d=doc: self._check(d))

    def _check(self, doc):
        # a build lets Qt run (the Fasteners workbench does), so this can be
        # called in the middle of one: never start another then
        if self.busy or _BUILDING[0] or Gui.Control.activeDialog():
            return
        self.busy = True
        try:
            for o in [x for x in doc.Objects if is_route(x)]:
                try:
                    if signature(o) != o.Built:
                        build(o)
                except Exception as e:
                    import traceback
                    o.Error = str(e) or type(e).__name__
                    App.Console.PrintWarning(f"MechFlow: {o.Label} not rebuilt ({o.Error})\n"
                                             + traceback.format_exc())
        finally:
            self.busy = False


_obs = None


def install():
    global _obs
    if _obs is None:
        _obs = _Observer()
        App.addDocumentObserver(_obs)


# ------------------------------------------------------------ panel

class RoutePanel:
    def __init__(self, route=None):
        from mechflow_gui import toolbox
        self.route = route
        self.doc = route.Document if route else App.ActiveDocument
        self.container = _container(route) if route else toolbox.active_container()
        self.links = {}
        self.starts = []
        if route is not None:
            for x, subs in path_links(route):
                self.links[x] = subs
            for x, subs in route.StartFlanges:
                for s_ in subs:
                    self.starts.append((x, s_))
        self.doc.openTransaction("Route Pipe")
        self.form = self._build()
        if route is not None:
            self._load()
        else:
            self._take_selection()
        Gui.Selection.clearSelection()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._apply()

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Route Pipe")
        lay = QtWidgets.QVBoxLayout(w)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        f = QtWidgets.QFormLayout()
        self.std = QtWidgets.QComboBox()
        self.std.addItems(STANDARDS)
        f.addRow("Standard", self.std)
        self.size = QtWidgets.QComboBox()
        f.addRow("Size", self.size)
        self.sched = QtWidgets.QComboBox()
        self.sched.addItems(["Sch 10", "Sch 40", "Sch 80"])
        self.sched.setCurrentText("Sch 40")
        f.addRow("Schedule", self.sched)
        self.bend = QtWidgets.QComboBox()
        f.addRow("Elbows", self.bend)
        self.ends = QtWidgets.QComboBox()
        self.ends.addItems(ENDS)
        self.ends.setCurrentText("Weld neck flange")
        f.addRow("Free ends", self.ends)
        self.rating = QtWidgets.QComboBox()
        f.addRow("Flange rating", self.rating)
        lay.addLayout(f)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(110)
        lay.addWidget(QtWidgets.QLabel("<b>Path and start flanges</b>"))
        lay.addWidget(self.list)
        clr = QtWidgets.QPushButton("Clear")
        clr.clicked.connect(self._clear)
        lay.addWidget(clr)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        self.std.currentTextChanged.connect(self._std_changed)
        for c in (self.size, self.sched, self.bend, self.ends, self.rating):
            c.currentTextChanged.connect(self._apply)
        self._std_changed()
        return w

    def _std_changed(self, *_):
        from mechflow_gui import stdparts
        std = self.std.currentText()
        for c, items, default in (
                (self.size, sizes_for(std), "DN80" if std == "EN" else "NPS 3"),
                (self.bend, BENDS[std], BENDS[std][0]),
                (self.rating, stdparts.ratings(types_for(std)["flange"]),
                 stdparts.default_rating(types_for(std)["flange"]))):
            keep = c.currentText()
            c.blockSignals(True)
            c.clear()
            c.addItems(items)
            c.setCurrentText(keep if keep in items else default)
            c.blockSignals(False)
        self.sched.setEnabled(std == "ASME")
        self._apply()

    def _load(self):
        r = self.route
        for c, v in ((self.std, r.Standard),):
            c.setCurrentText(v)
        self._std_changed()
        self.size.setCurrentText(r.Size)
        if r.Schedule:
            self.sched.setCurrentText(r.Schedule)
        self.bend.setCurrentText(r.Bend)
        self.ends.setCurrentText(r.FreeEnds)
        if r.FlangeRating:
            self.rating.setCurrentText(r.FlangeRating)

    def _take_selection(self, sel=None):
        import Part
        changed = False
        for s in (sel if sel is not None else Gui.Selection.getSelectionEx("", 0)):
            obj = s.Object
            for sub in (s.SubElementNames or [""]):
                leaf = sub.rsplit(".", 1)[-1]
                if leaf.startswith("Edge"):
                    try:
                        e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
                    except Exception:
                        continue
                    if type(e.Curve).__name__ == "Circle":
                        key = (obj, sub)
                        if key in self.starts:
                            self.starts.remove(key)
                        else:
                            self.starts.append(key)
                        changed = True
                        continue
                target = obj
                path_sub = leaf
                if "." in sub:
                    try:
                        target = obj.getSubObjectList(sub)[-1]
                    except Exception:
                        pass
                if target.TypeId != "Sketcher::SketchObject" and not target.isDerivedFrom(
                        "Part::Part2DObject") and not target.TypeId.startswith("Part::Part2D"):
                    if not path_sub.startswith("Edge"):
                        continue
                if path_sub.startswith("Edge"):
                    lst = self.links.get(target) or []
                    if path_sub in lst:
                        lst.remove(path_sub)
                    else:
                        lst.append(path_sub)
                    self.links[target] = lst
                elif target in self.links and self.links[target] is None:
                    del self.links[target]            # clicked again: off
                else:
                    self.links[target] = None         # the whole sketch, whatever it becomes
                changed = True
        return changed

    def _poll(self):
        try:
            sel = Gui.Selection.getSelectionEx("", 0)
        except Exception:
            return
        if not sel:
            return
        Gui.Selection.clearSelection()
        if self._take_selection(sel):
            self._apply()

    def _clear(self):
        self.links, self.starts = {}, []
        self._apply()

    def _refresh_list(self):
        self.list.clear()
        for o, subs in self.links.items():
            if subs is None:
                self.list.addItem(f"Path: {o.Label} (all its lines)")
            elif subs:
                self.list.addItem(f"Path: {o.Label} ({len(subs)} line{'s' if len(subs) != 1 else ''})")
        for o, s_ in self.starts:
            self.list.addItem(f"Start on flange: {o.Label} {s_}")

    def _apply(self, *_):
        self._refresh_list()
        links = [(o, s_) for o, s_ in self.links.items() if s_ is None or s_]
        if not links:
            self.msg.setText("<b>Click the route sketch</b> (or its lines). Add more sketches "
                             "for a 3D route. To start on a flange, click its face edge.")
            if self.route is not None:
                clear_parts(self.route)
            return
        std = self.std.currentText()
        try:
            if self.route is None:
                self.route = make_route(
                    self.container, links, std, self.size.currentText(),
                    self.sched.currentText(), self.bend.currentText(),
                    self.ends.currentText(), self.rating.currentText(), self.starts,
                    build_now=False)
                build(self.route)
            else:
                r = self.route
                r.PathSketches = [o for o, s_ in links if s_ is None]
                r.Path = [(o, tuple(s_)) for o, s_ in links if s_]
                r.StartFlanges = [(o, (s_,)) for o, s_ in self.starts]
                r.Standard = std
                r.Size = self.size.currentText()
                r.Schedule = self.sched.currentText() if std == "ASME" else ""
                r.Bend = self.bend.currentText()
                r.FreeEnds = self.ends.currentText()
                r.FlangeRating = self.rating.currentText()
                build(r)
            self.error.hide()
            self._summary()
        except Exception as e:
            self.error.setText(f"<b>Can't route this:</b> {e}")
            self.error.show()
            if self.route is not None:
                self.route.Error = str(e)

    def _summary(self):
        parts = list(self.route.Parts)
        pipes = [p for p in parts if getattr(p, "StdType", "").endswith("-PIPE")]
        elbows = [p for p in parts if "-90" in getattr(p, "StdType", "") or
                  "-45" in getattr(p, "StdType", "") or "LR" in getattr(p, "StdType", "")]
        total = sum(float(p.Length) for p in pipes)
        self.msg.setText(f"<b>{len(pipes)} pipe{'s' if len(pipes) != 1 else ''}</b> "
                         f"({total:,.0f} mm), <b>{len(elbows)} elbow"
                         f"{'s' if len(elbows) != 1 else ''}</b>, {len(parts)} parts in all. "
                         "Click more lines or flanges, or OK.")

    def accept(self):
        self._timer.stop()
        if self.route is None or not self.route.Parts:
            QtWidgets.QMessageBox.information(self.form, "Route Pipe",
                                              "Pick the route's sketch first - or Cancel.")
            self._timer.start()
            return False
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._timer.stop()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def route_pipe():
    if App.ActiveDocument is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Route Pipe",
                                          "Finish the open dialog first.")
        return None
    install()
    p = RoutePanel()
    Gui.Control.showDialog(p)
    return p
