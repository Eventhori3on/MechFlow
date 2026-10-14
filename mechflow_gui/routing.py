# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pipe routing (SOLIDWORKS Routing, simplified).

Draw the pipe's centreline - a 3D Sketch (sketch3d.py), or lines in one
sketch or several - branches allowed - and Route Pipe fills it in:

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
from mechflow_gui import edge_curve, curve_name  # noqa: F401
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


def path_segments_keyed(links):
    """[(a, b, key)] straight segments (in the container's axes) from sketch
    lines; key ('Object:EdgeN') names the line, for size changes. Arcs are
    refused: bends come from the fittings."""
    segs = []
    for obj, subs in links:
        sh = obj.Shape
        if subs:
            edges = []
            for n in subs:
                try:
                    edges.append((n.lstrip("?"), sh.getElement(n.lstrip("?"))))
                except Exception:
                    continue
        else:
            edges = [(f"Edge{i + 1}", e) for i, e in enumerate(sh.Edges)]
        for n, e in edges:
            if curve_name(e) not in ("Line", "LineSegment"):
                raise ValueError(f"{obj.Label} {n} isn't straight - draw the route with "
                                 "lines; the bends are added for you")
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if (b - a).Length > TOL:
                segs.append((V(a), V(b), f"{obj.Name}:{n}"))
    if not segs:
        raise ValueError("no lines to route along")
    return segs


def path_segments(links):
    return [(a, b) for a, b, _k in path_segments_keyed(links)]


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


class Flow:
    """The route as straight runs in flow order: from the start (a picked
    flange, else where the path was first drawn) out to every free end.
    Each run: start node, end node, direction, length and the sketch lines
    it's made of [(key, from, to)] (distances along the run)."""

    def __init__(self, segs, root_points=()):
        self.pts = []
        adj = {}
        keyof = {}
        for a, b, k in segs:
            i, j = self._node(a), self._node(b)
            if i == j:
                continue
            adj.setdefault(i, set()).add(j)
            adj.setdefault(j, set()).add(i)
            keyof[(i, j)] = keyof[(j, i)] = k
        n_edges = sum(len(v) for v in adj.values()) // 2
        if n_edges != len(adj) - 1:
            raise ValueError("the route has a loop or separate pieces - it must be one "
                             "connected run (branches are fine)")
        ends = [i for i in adj if len(adj[i]) == 1]
        root = None
        for rp in root_points:
            for i in ends:
                if (self.pts[i] - rp).Length < 1.0:
                    root = i
            if root is not None:
                break
        if root is None:
            # a start flange in line with an end (the sketch stops short of it)
            for rp in root_points:
                for i in ends:
                    j = next(iter(adj[i]))
                    u = self.pts[j] - self.pts[i]
                    u.normalize()
                    if ((rp - self.pts[i]).cross(u)).Length < 1.0:
                        root = i
                if root is not None:
                    break
        if root is None and segs:
            first = self._node(segs[0][0])
            root = first if first in ends else (ends[0] if ends else first)
        self.root = root
        self.runs = []
        # walk out from the root; straight-through nodes join runs
        stack = [(root, j) for j in sorted(adj[root])]
        while stack:
            u, v = stack.pop(0)
            d = self.pts[v] - self.pts[u]
            d.normalize()
            pieces = []
            prev, cur = u, v
            s0 = 0.0
            while True:
                L = (self.pts[cur] - self.pts[prev]).Length
                pieces.append((keyof[(prev, cur)], s0, s0 + L))
                s0 += L
                nxt = [w for w in adj[cur] if w != prev]
                if len(nxt) == 1:
                    e = self.pts[nxt[0]] - self.pts[cur]
                    e.normalize()
                    if e.dot(d) > 1 - 1e-9:          # straight on: same run
                        prev, cur = cur, nxt[0]
                        continue
                break
            self.runs.append({"start": u, "end": cur, "a": V(self.pts[u]), "d": V(d),
                              "L": s0, "pieces": pieces})
            for w in sorted(adj[cur]):
                if w != prev:
                    stack.append((cur, w))
        self.node_runs = {}
        for k, r in enumerate(self.runs):
            self.node_runs.setdefault(r["start"], {"in": None, "out": []})["out"].append(k)
            self.node_runs.setdefault(r["end"], {"in": None, "out": []})["in"] = k

    def _node(self, p):
        for i, q in enumerate(self.pts):
            if (q - p).Length < TOL:
                return i
        self.pts.append(V(p))
        return len(self.pts) - 1


def _size_key(std, size):
    """Sort key: pipe OD."""
    try:
        return fitting_dims(std, size, "Sch 40", "3D" if std == "EN" else "LR")[0]
    except Exception:
        return 0.0


def reducer_type(std):
    return "ASMEB16.9-RED" if std == "ASME" else "EN10253-RED"


def _red_name(std, big, small):
    if std == "ASME":
        return f"{big} x {small.replace('NPS ', '')}"
    return f"{big} x {small}"


def reducer_steps(std, s1, s2):
    """[(from, to)] concentric reducers taking s1 to s2 (several when the
    step is bigger than one standard reducer covers)."""
    from mechflow_gui import stdparts
    if s1 == s2:
        return []
    avail = set(stdparts.sizes(reducer_type(std)))
    sizes = sorted(sizes_for(std), key=lambda z: _size_key(std, z))
    down = _size_key(std, s1) > _size_key(std, s2)
    big, small = (s1, s2) if down else (s2, s1)
    steps = []
    cur = big
    guard = 0
    while cur != small and guard < 20:
        guard += 1
        # the biggest step down from cur a standard reducer makes, not past small
        cands = [z for z in sizes if _size_key(std, small) <= _size_key(std, z) < _size_key(std, cur)
                 and _red_name(std, cur, z) in avail]
        if not cands:
            raise ValueError(f"no standard reducer from {cur} towards {small}")
        nxt = min(cands, key=lambda z: _size_key(std, z))
        steps.append((cur, nxt))
        cur = nxt
    if not down:
        steps = [(b, a) for a, b in reversed(steps)]
    return steps


def reducer_length(std, big, small):
    from mechflow_gui import stdparts, stdparts_data as T
    if std == "ASME":
        return T.B169[stdparts._nps(big)][2] * stdparts.IN
    return stdparts.en_fitting_dims("EN10253-RED", _red_name(std, big, small))[4]


def plan(route_like, starts=()):
    """What to build: [{type, size, rating, length, placement, angle, role}]
    plus end info. route_like has Standard, Size (the size at the start),
    Schedule, Bend, FreeEnds, FlangeRating, segments [(a, b, key)], and
    optionally SizeChanges {line key: size}, ScheduleBySize, components.
    starts: [(face point, weld-end point, outward dir, flange size)] for
    ends that bolt to an existing flange.

    Sizes follow the flow: a run starts at its start node's size; a size
    change on a line (SizeChanges) puts in reducers where that line starts
    and carries on downstream; a component with different end sizes changes
    the size after it. Each fitting takes the size arriving at it."""
    from mechflow_gui import stdparts
    std = route_like["Standard"]
    bend = route_like["Bend"]
    by_size = route_like.get("ScheduleBySize") or {}

    def sched(size):
        return by_size.get(size) or route_like["Schedule"] or "Sch 40"

    dims_cache = {}

    def dims(size):
        if size not in dims_cache:
            dims_cache[size] = fitting_dims(std, size, sched(size), bend)
        return dims_cache[size]

    def rpipe(size):
        return sched(size) if std == "ASME" else ""

    ty = types_for(std, bend)
    frate = route_like["FlangeRating"] or stdparts.default_rating(ty["flange"])
    gt = "EN1514-1-IBC" if std == "EN" else "ASMEB16.21"
    segs = route_like["segments"]
    if segs and len(segs[0]) == 2:
        segs = [(a, b, f"seg{i}") for i, (a, b) in enumerate(segs)]
    fl = Flow(segs, [sp[0] for sp in starts] + [sp[1] for sp in starts])
    explicit = route_like.get("SizeChanges") or {}
    comps = route_like.get("components", [])
    runs = fl.runs

    # components onto runs (nearest)
    for r in runs:
        r["comps"] = []
    for c in comps:
        best = None
        for k, r in enumerate(runs):
            s_ = max(0.0, min(r["L"], (V(c["position"]) - r["a"]).dot(r["d"])))
            dist = (r["a"] + r["d"] * s_ - V(c["position"])).Length
            if best is None or dist < best[0]:
                best = (dist, k, s_)
        if best is not None:
            runs[best[1]]["comps"].append((best[2], c))

    # the start
    root_start = None
    for sp in starts:
        p = fl.pts[fl.root]
        if (sp[0] - p).Length < 1.0 or (sp[1] - p).Length < 1.0 or \
                abs((sp[1] - p).cross(runs[fl.node_runs[fl.root]["out"][0]]["d"]).Length) < 1.0:
            root_start = sp
    start_size = route_like["Size"]
    root_size = (root_start[3] if root_start is not None and len(root_start) > 3 and root_start[3]
                 else start_size) or sizes_for(std)[0]

    # pass 1: sizes - each run's events and its end size
    node_size = {fl.root: root_size}
    for r in runs:                       # runs come in flow order
        cur = node_size[r["start"]]
        ev = []                          # (s, kind, data)
        if r["start"] == fl.root and start_size and start_size != cur:
            ev.append((0.0, "size", start_size))
        for key, s0, _s1 in r["pieces"]:
            if key in explicit and explicit[key]:
                ev.append((s0, "size", explicit[key]))
        for s_, c in r["comps"]:
            ev.append((s_, "comp", c))
        ev.sort(key=lambda t: (t[0], 0 if t[1] == "size" else 1))
        events = []
        for s_, kind, data in ev:
            if kind == "size":
                if data != cur:
                    events.append((s_, "size", (cur, data)))
                    cur = data
            else:
                ports = data.get("ports")
                in_s, out_s = cur, cur
                if ports:
                    a_s, b_s = ports
                    in_s, out_s = (b_s, a_s) if data.get("reverse") else (a_s, b_s)
                    if in_s != cur:
                        raise ValueError(f"{data['obj'].Label} takes {in_s} in, but the pipe "
                                         f"there is {cur} - change the pipe size before it "
                                         "or turn the part round (Flow the other way)")
                events.append((s_, "comp", (data, in_s, out_s)))
                cur = out_s
        r["events"] = events
        r["start_size"] = node_size[r["start"]]
        r["end_size"] = cur
        node_size[r["end"]] = cur

    parts = []
    trim_start = {}                      # run index -> pipe starts this far in
    trim_end = {}                        # run index -> pipe stops this far short
    red_after = {}                       # run index -> reducers right after the start fitting

    def add_reducers(k, start_off, s_from, s_to):
        """Reducers on run k from start_off on; returns their total length."""
        r = runs[k]
        off = start_off
        for x, y in reducer_steps(std, s_from, s_to):
            down = _size_key(std, x) > _size_key(std, y)
            big, small = (x, y) if down else (y, x)
            H = reducer_length(std, big, small)
            name = _red_name(std, big, small)
            if down:
                pl = App.Placement(r["a"] + r["d"] * off, _rot(r["d"]))
            else:
                pl = App.Placement(r["a"] + r["d"] * (off + H), _rot(r["d"] * -1))
            parts.append({"type": reducer_type(std), "size": name, "rating": rpipe(big),
                          "length": 0.0, "angle": 0.0, "role": "reducer", "placement": pl})
            off += H
        return off - start_off

    # fittings at the nodes
    for i, nr in fl.node_runs.items():
        p = fl.pts[i]
        size = node_size[i]
        od, wall, R, C, E = dims(size)
        dirs = []                        # (run index, direction from the node, is_out)
        if nr["in"] is not None:
            dirs.append((nr["in"], runs[nr["in"]]["d"] * -1, False))
        for k in nr["out"]:
            dirs.append((k, runs[k]["d"], True))
        if len(dirs) == 1:
            continue                     # an end: below
        if len(dirs) == 2:
            (ka, a, _oa), (kb, b, _ob) = dirs
            if a.dot(b) < -1 + 1e-9:     # straight through (only where a run was split)
                trim_end[ka] = trim_start[kb] = 0.0
                continue
            bend_deg = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, a.dot(b)))))
            if bend_deg > 90.0 + 1e-6:
                raise ValueError(f"a bend of {bend_deg:.1f}° is tighter than a 90° "
                                 "elbow - add a straight between two elbows")
            T = R * math.tan(math.radians(bend_deg) / 2)
            trim_end[ka] = T
            trim_start[kb] = T
            t90, t45 = ty["elbow90"], ty["elbow45"]
            use = t45 if (t45 and bend_deg <= 45.0 + 1e-6) else t90
            std_ang = 45.0 if use == t45 else 90.0
            angle = 0.0 if abs(bend_deg - std_ang) < 1e-6 else bend_deg
            inlet = p + a * T
            parts.append({"type": use, "size": size, "rating": rpipe(size), "length": 0.0,
                          "angle": angle, "role": "elbow",
                          "placement": App.Placement(inlet, _rot(-a, b))})
            continue
        if len(dirs) == 3:
            pair = None
            for x in range(3):
                for y in range(x + 1, 3):
                    if dirs[x][1].dot(dirs[y][1]) < -1 + 1e-6:
                        pair = (x, y)
            if pair is None:
                raise ValueError("at a branch two of the lines must be in line (the run)")
            br = [z for z in range(3) if z not in pair][0]
            run_a, branch = dirs[pair[0]], dirs[br]
            if abs(branch[1].dot(run_a[1])) > 1e-3:
                raise ValueError("a branch must meet the run square on (equal tee)")
            for k, _d, is_out in dirs:
                if is_out:
                    trim_start[k] = C
                else:
                    trim_end[k] = C
            parts.append({"type": ty["tee"], "size": size, "rating": rpipe(size), "length": 0.0,
                          "angle": 0.0, "role": "tee",
                          "placement": App.Placement(p + run_a[1] * C, _rot(-run_a[1], branch[1]))})
            continue
        raise ValueError("more than three lines meet at one point")

    # ends
    end_info = []
    for i, nr in fl.node_runs.items():
        if (1 if nr["in"] is not None else 0) + len(nr["out"]) != 1:
            continue
        p = fl.pts[i]
        if nr["in"] is not None:
            k, u, at_start = nr["in"], runs[nr["in"]]["d"] * -1, False
        else:
            k, u, at_start = nr["out"][0], runs[nr["out"][0]]["d"], True
        size = node_size[i]
        if at_start and root_start is not None and i == fl.root:
            weld = root_start[1]
            (trim_start if at_start else trim_end)[k] = (weld - p).dot(u)
            end_info.append(("joint", i))
            continue
        od, wall, R, C, E = dims(size)
        mode = route_like["FreeEnds"]
        tset = trim_start if at_start else trim_end
        if mode in ("Weld neck flange", "Blind flange"):
            H = stdparts._length_in_part(ty["flange"], size, frate)
            tset[k] = H
            parts.append({"type": ty["flange"], "size": size, "rating": frate, "length": 0.0,
                          "angle": 0.0, "role": "end-flange" if mode == "Weld neck flange"
                          else "end-flange-blind",
                          "placement": App.Placement(p + u * H, _rot(-u))})
        elif mode == "Cap":
            tset[k] = E
            parts.append({"type": ty["cap"], "size": size, "rating": rpipe(size), "length": 0.0,
                          "angle": 0.0, "role": "cap",
                          "placement": App.Placement(p + u * E, _rot(-u))})
        else:
            tset[k] = 0.0
        end_info.append((mode, i))

    # pipes, reducers and components along each run
    for k, r in enumerate(runs):
        a, d, L = r["a"], r["d"], r["L"]
        ta, tb = trim_start.get(k, 0.0), trim_end.get(k, 0.0)
        pos = ta
        cur = r["start_size"]
        label_here = None

        def key_at(s_):
            for key, s0, s1 in r["pieces"]:
                if s0 - 1e-6 <= s_ <= s1 + 1e-6:
                    return key
            return r["pieces"][-1][0]

        def pipe(s0, s1, size, who):
            ln = s1 - s0
            if ln < 1.0:
                if who is None:
                    raise ValueError(f"the straight from {_fmt(a)} to {_fmt(a + d * L)} is "
                                     f"too short for its fittings ({L:.0f} mm, needs more "
                                     f"than {L - ln + 1:.0f} mm)")
                raise ValueError(f"no room for {who} there ({ln:.0f} mm of pipe left) - "
                                 "slide it along the pipe or move it to a longer straight")
            parts.append({"type": ty["pipe"], "size": size, "rating": rpipe(size),
                          "length": round(ln, 1), "angle": 0.0, "role": "pipe",
                          "key": key_at(s0 + min(0.5, ln / 2)),
                          "placement": App.Placement(a + d * s0, _rot(d))})

        for s_, kind, data in r["events"]:
            if kind == "size":
                s1_, s2_ = data
                at = max(s_, pos)
                if at - pos >= 1.0:
                    pipe(pos, at, cur, label_here)
                elif at - pos > 1e-6:
                    pipe(pos, at, cur, label_here)        # raises: too short
                length = add_reducers(k, at, s1_, s2_)
                pos = at + length
                cur = s2_
                label_here = None
                continue
            c, in_s, out_s = data
            obj = c["obj"]
            centre = a + d * s_
            parts.append({"role": "component", "obj": obj, "centre": centre, "dir": d,
                          "od": dims(in_s)[0], "size": in_s, "size_out": out_s,
                          "length": 0.0, "angle": 0.0, "type": None})
            if c["end"] == "branch":
                if s_ < ta + 20 or s_ > L - tb - 20:
                    raise ValueError(f"{obj.Label} is on a fitting - slide it along the pipe")
                continue
            ftf, _end = c["ftf"](in_s) if callable(c["ftf"]) else (c["ftf"], c["end"])
            half = ftf / 2
            reach = {}
            for side, sgn, sz in (("A", -1, in_s), ("B", 1, out_s)):
                g_ = H = 0.0
                if c["end"] in ("flanged", "wafer"):
                    g_ = stdparts.gasket_dims(gt, sz, frate)[2]
                    H = stdparts._length_in_part(ty["flange"], sz, frate)
                    port = centre + d * (sgn * half)
                    gpos = port + d * (sgn * g_)            # gasket's far face
                    parts.append({"type": gt, "size": sz, "rating": frate, "length": 0.0,
                                  "angle": 0.0, "role": "comp-gasket", "comp": obj, "side": side,
                                  "placement": App.Placement(port if sgn > 0 else gpos, _rot(d))})
                    parts.append({"type": ty["flange"], "size": sz, "rating": frate,
                                  "length": 0.0, "angle": 0.0, "role": "comp-flange",
                                  "comp": obj, "side": side, "gap": g_,
                                  "placement": App.Placement(gpos + d * (sgn * H), _rot(d * -sgn))})
                reach[side] = half + g_ + H
            if s_ - reach["A"] - pos < 1.0:
                pipe(pos, s_ - reach["A"], cur, obj.Label)
            else:
                pipe(pos, s_ - reach["A"], cur, label_here)
            pos = s_ + reach["B"]
            cur = out_s
            label_here = obj.Label
        pipe(pos, L - tb, cur, label_here)
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
        ensure_props(obj)
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
            from mechflow_gui import inline
            return inline.components_of(self.Object) + list(self.Object.Parts)
        except Exception:
            return []

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.Control.showDialog(RoutePanel(vobj.Object))
        return True

    def onDelete(self, vobj, subs):
        clear_parts(vobj.Object)
        try:
            from mechflow_gui import inline
            for c in inline.components_of(vobj.Object):
                c.Document.removeObject(c.Name)
        except Exception:
            pass
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def ensure_props(o):
    """Properties added since routes were first made (older files get them
    when opened or rebuilt)."""
    if not hasattr(o, "Spec"):
        o.addProperty("App::PropertyString", "Spec", "Route", "Pipe spec the route follows")
    if not hasattr(o, "Material"):
        o.addProperty("App::PropertyString", "Material", "Route", "Pipe and fittings material")
    if not hasattr(o, "ScheduleBySize"):
        o.addProperty("App::PropertyString", "ScheduleBySize", "Route",
                      "ASME schedule for particular sizes (JSON)", 4)
    if not hasattr(o, "SizeChanges"):
        o.addProperty("App::PropertyStringList", "SizeChanges", "Route",
                      "Size changes: 'line=size' - from that line on, downstream")


def size_changes(o):
    """{line key: size} of a route."""
    out = {}
    for t in getattr(o, "SizeChanges", []) or []:
        if "=" in t:
            k, v = t.rsplit("=", 1)
            if v.strip():
                out[k.strip()] = v.strip()
    return out


def set_size_change(o, key, size):
    """Size from line key on (None: follow the size before it)."""
    ensure_props(o)
    ch = size_changes(o)
    if size:
        ch[key] = size
    else:
        ch.pop(key, None)
    o.SizeChanges = [f"{k}={v}" for k, v in sorted(ch.items())]


def describe_key(o, key):
    """'3D Sketch1 line 3' for a line key."""
    try:
        name, edge = key.split(":", 1)
        obj = o.Document.getObject(name)
        n = int(edge.replace("Edge", ""))
        return f"{obj.Label if obj else name} line {n}"
    except Exception:
        return key


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
    ensure_props(o)
    try:
        by = json.loads(o.ScheduleBySize or "{}")
    except Exception:
        by = {}
    return {"Standard": o.Standard, "Size": o.Size, "Schedule": o.Schedule,
            "Bend": o.Bend, "FreeEnds": o.FreeEnds, "FlangeRating": o.FlangeRating,
            "ScheduleBySize": by, "SizeChanges": size_changes(o), "Material": o.Material}


def signature(o):
    """Hash of everything the parts depend on."""
    h = hashlib.sha1()
    h.update(json.dumps(settings(o), sort_keys=True).encode())
    try:
        for a, b in path_segments(path_links(o)):
            h.update(_fmt(a).encode() + _fmt(b).encode())
    except Exception as e:
        h.update(str(e).encode())
    try:
        from mechflow_gui import inline
        for c in inline.components_of(o):
            h.update(json.dumps([c.Name, c.Kind, _fmt(V(c.Position)), round(float(c.Angle), 3),
                                 bool(c.Reverse), c.Library, c.Ports]).encode())
    except Exception:
        pass
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
        c = edge_curve(e)
        if type(c).__name__ == "Circle" and abs(c.Radius - r) < 1e-3:
            d = (c.Center - from_pt).Length
            if best is None or d > best[1]:
                best = (f"Edge{i + 1}", d, c.Center)
    return best


_BUILDING = [0]


_AGAIN = set()


def build(o):
    """(Re)make the route's parts. Returns the parts (raises on errors).
    A build asked for while one is running (a build lets Qt run, so a
    panel or the live rebuild can ask) is done straight after it instead."""
    if _BUILDING[0]:
        _AGAIN.add(o.Name)
        return list(o.Parts)
    _BUILDING[0] += 1
    # parts are made in the active document: make it the route's own
    prev = App.ActiveDocument
    if prev is not o.Document:
        App.setActiveDocument(o.Document.Name)
    try:
        made = _build(o)
        for _i in range(3):
            if o.Name not in _AGAIN:
                break
            _AGAIN.discard(o.Name)
            made = _build(o)
        return made
    finally:
        _AGAIN.discard(o.Name)
        _BUILDING[0] -= 1
        if prev is not None and prev is not o.Document:
            try:
                App.setActiveDocument(prev.Name)
            except Exception:
                pass


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
            starts.append((face, wp, n, mate.Size))
    segs = path_segments_keyed(path_links(o))
    s["segments"] = segs
    if not s["Size"] and not starts:
        s["Size"] = sizes_for(o.Standard)[0]
    frate = o.FlangeRating or stdparts.default_rating(ty["flange"])
    from mechflow_gui import inline
    comps = inline.components_of(o)
    s["components"] = []
    for c in comps:
        _ftf0, end = inline.ftf_and_end(c, o.Standard, s["Size"] or (starts[0][3] if starts else ""))
        s["components"].append({
            "obj": c, "position": V(c.Position), "end": end, "reverse": bool(c.Reverse),
            "ftf": (lambda size, c=c: inline.ftf_and_end(c, o.Standard, size)),
            "ports": inline.port_sizes(c, o.Standard, frate)})
    parts, ends = plan(s, starts)
    comp_parts = {}
    for p in parts:
        if p["role"] == "component":
            c = p["obj"]
            c.Standard, c.Size, c.Rating = o.Standard, p["size"], frate
            c.Position = p["centre"]
            c.Placement = inline.placement_for(c, p["centre"], p["dir"], p["od"])
            c.recompute()
            continue
        part = stdparts.make(container, p["type"], p["size"], p["rating"] or None,
                             p["length"] or 1000.0)
        if p.get("key"):
            if not hasattr(part, "RouteLine"):
                part.addProperty("App::PropertyString", "RouteLine", "Route",
                                 "The route line this pipe is on (for Change Size)", 4)
            part.RouteLine = p["key"]
        if p["role"] in ("comp-gasket", "comp-flange"):
            comp_parts.setdefault(p["comp"].Name, {})[p["role"] + p["side"]] = part
            comp_parts[p["comp"].Name]["size" + p["side"]] = p["size"]
            if "gap" in p:
                comp_parts[p["comp"].Name]["gap" + p["side"]] = p["gap"]
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
                c = edge_curve(e)
                if type(c).__name__ == "Circle" and abs(2 * c.Radius - info["face"]) < 1e-3:
                    dd = (c.Center - face).Length
                    if best is None or dd < best[1]:
                        best = (f"Edge{i + 1}", dd)
            if best:
                bl = stdparts.place(container, ty["blind"], part, best[0], joint=True)
                _tag(bl, o)
                made += bl
    # bolts through the components' flanged ends
    if comp_parts:
        doc.recompute()
        for c in comps:
            cp = comp_parts.get(c.Name)
            if not cp:
                continue
            try:
                if c.EndType == "wafer":
                    b = stdparts.bolt_set(container, cp["comp-flangeA"], cp["comp-flangeB"],
                                          2 * cp["gapA"] + float(c.FaceToFace))
                else:
                    b = []
                    for side in "AB":
                        b += stdparts.bolt_set(container, cp["comp-flange" + side],
                                               inline.PortFlange(c, ty["flange"], cp["size" + side],
                                                                 frate),
                                               cp["gap" + side])
                _tag(b, o)
                made += b
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: {c.Label}: bolts not added ({e})\n")
    if o.Material:                       # the spec's material on the steel parts
        from mechflow_gui import material as _mat, pipespec
        for m in made:
            t = getattr(m, "StdType", "")
            if t and not stdparts.is_gasket(t):
                try:
                    _mat.set_material(m, o.Material, pipespec.density(o.Material))
                except Exception:
                    pass
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
        self._loading = True                 # no rebuilds while the fields fill in
        self.form = self._build()
        if route is not None:
            self._load()
        else:
            self._take_selection()
        self._loading = False
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
        srow = QtWidgets.QHBoxLayout()
        self.spec = QtWidgets.QComboBox()
        self._fill_specs()
        srow.addWidget(self.spec, 1)
        eb = QtWidgets.QPushButton("Specs...")
        eb.setToolTip("Look at, make and change pipe specs")
        eb.clicked.connect(self._edit_specs)
        srow.addWidget(eb)
        f.addRow("Pipe spec", srow)
        self.std = QtWidgets.QComboBox()
        self.std.addItems(STANDARDS)
        f.addRow("Standard", self.std)
        self.material = QtWidgets.QComboBox()
        self.material.setEditable(True)
        from mechflow_gui import pipespec
        self.material.addItems([""] + list(pipespec.MATERIALS))
        f.addRow("Material", self.material)
        self.size = QtWidgets.QComboBox()
        self.size.setToolTip("The size where the route starts. Right-click a pipe "
                             "(Change Pipe Size) to change size further on.")
        f.addRow("Size at the start", self.size)
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
        lay.addWidget(QtWidgets.QLabel("<b>Size changes</b> (right-click a pipe: Change Pipe Size)"))
        self.changes = QtWidgets.QListWidget()
        self.changes.setMaximumHeight(80)
        lay.addWidget(self.changes)
        rm = QtWidgets.QPushButton("Remove size change")
        rm.clicked.connect(self._remove_change)
        lay.addWidget(rm)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.error.hide()
        lay.addWidget(self.error)
        lay.addStretch(1)
        self._from_spec = False
        self.std.currentTextChanged.connect(self._std_changed)
        self.std.currentTextChanged.connect(self._off_spec)
        for c in (self.size, self.sched, self.bend, self.ends, self.rating, self.material):
            c.currentTextChanged.connect(self._apply)
        for c in (self.sched, self.bend, self.ends, self.rating, self.material):
            c.currentTextChanged.connect(self._off_spec)
        self.spec.currentTextChanged.connect(self._spec_chosen)
        self._std_changed()
        return w

    # -- specs
    def _fill_specs(self, keep=None):
        from mechflow_gui import pipespec
        self.spec.blockSignals(True)
        self.spec.clear()
        self.spec.addItem("(none)")
        names = [x["name"] for x in pipespec.all_specs()]
        if keep and keep != "(none)" and keep not in names:
            names.append(keep)               # a spec from another PC: keep its name
        self.spec.addItems(names)
        if keep:
            self.spec.setCurrentText(keep)
        self.spec.blockSignals(False)

    def _off_spec(self, *_):
        """A field changed by hand: the route no longer follows a spec
        (except the size at the start, which isn't part of one)."""
        if self._from_spec:
            return
        if self.spec.currentText() != "(none)":
            self.spec.blockSignals(True)
            self.spec.setCurrentText("(none)")
            self.spec.blockSignals(False)

    def _spec_chosen(self, name):
        from mechflow_gui import pipespec
        sp = pipespec.get(name)
        if sp is None:
            self._apply()
            return
        self._from_spec = True
        try:
            for c in (self.std, self.size, self.sched, self.bend, self.ends, self.rating,
                      self.material):
                c.blockSignals(True)
            self.std.setCurrentText(sp["standard"])
            for c in (self.std, ):
                c.blockSignals(False)
            self._std_changed(apply=False)
            for c in (self.size, self.sched, self.bend, self.ends, self.rating, self.material):
                c.blockSignals(True)
            if sp["start_size"] and not self.starts:
                self.size.setCurrentText(sp["start_size"])
            if sp["schedule"]:
                self.sched.setCurrentText(sp["schedule"])
            self.bend.setCurrentText(sp["bend"])
            self.ends.setCurrentText(sp["free_ends"])
            self.rating.setCurrentText(sp["rating"])
            self.material.setCurrentText(sp["material"])
        finally:
            for c in (self.std, self.size, self.sched, self.bend, self.ends, self.rating,
                      self.material):
                c.blockSignals(False)
            self._from_spec = False
        self._apply()

    def _edit_specs(self):
        from mechflow_gui import pipespec
        cur = self.spec.currentText()
        self._timer.stop()
        try:
            pipespec.edit_specs(select=cur if cur != "(none)" else None)
        finally:
            self._timer.start()
        self._fill_specs(keep=cur)
        if cur != "(none)" and pipespec.get(cur) is not None:
            self._spec_chosen(cur)

    # -- size changes
    def _refresh_changes(self):
        self.changes.clear()
        if self.route is None:
            return
        for k, v in sorted(size_changes(self.route).items()):
            it = QtWidgets.QListWidgetItem(f"{describe_key(self.route, k)} on: {v}")
            it.setData(QtCore.Qt.UserRole, k)
            self.changes.addItem(it)

    def _remove_change(self):
        it = self.changes.currentItem()
        if it is None or self.route is None:
            return
        set_size_change(self.route, it.data(QtCore.Qt.UserRole), None)
        self._apply()

    def _std_changed(self, *_, apply=True):
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
        if apply:
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
        ensure_props(r)
        self.material.setCurrentText(r.Material)
        self._fill_specs(keep=r.Spec or "(none)")

    def _take_selection(self, sel=None):
        import Part
        changed = False
        for s in (sel if sel is not None else Gui.Selection.getSelectionEx("", 0)):
            obj = s.Object
            for sub in (s.SubElementNames or [""]):
                leaf = sub.rsplit(".", 1)[-1]
                sk = obj
                if "." in sub:
                    try:
                        sk = obj.getSubObjectList(sub)[-1]
                    except Exception:
                        sk = obj
                from mechflow_gui import sketch3d
                if sketch3d.is_sketch3d(sk):
                    # a 3D sketch is always the whole route, and where it
                    # starts on a flange the pipe bolts on there
                    if sk in self.links and self.links[sk] is None:
                        del self.links[sk]
                    else:
                        self.links[sk] = None
                        self._add_anchor_starts(sk)
                    changed = True
                    continue
                if leaf.startswith("Edge"):
                    try:
                        e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
                    except Exception:
                        continue
                    if curve_name(e) == "Circle":
                        key = (obj, sub)
                        if key in self.starts:
                            self.starts.remove(key)
                        else:
                            self.starts.append(key)
                            self._size_from_flange(obj)
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

    def _size_from_flange(self, obj):
        """Starting on a flange: the route starts at the flange's size."""
        if len(self.starts) != 1:
            return
        sz = getattr(obj, "Size", "")
        if sz and self.size.findText(sz) >= 0:
            self.size.blockSignals(True)
            self.size.setCurrentText(sz)
            self.size.blockSignals(False)

    def _add_anchor_starts(self, sk):
        from mechflow_gui import stdparts
        flange = types_for(self.std.currentText())["flange"]
        for o, subs in sk.Anchors:
            for sub in subs:
                if (o, sub) in self.starts:
                    continue
                try:
                    if stdparts.joint_with(o, sub, flange) is not None:
                        self.starts.append((o, sub))
                        self._size_from_flange(o)
                except Exception:
                    pass

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
        if getattr(self, "_loading", False):
            return
        self._refresh_list()
        links = [(o, s_) for o, s_ in self.links.items() if s_ is None or s_]
        if not links:
            self.msg.setText("<b>Click the route's 3D Sketch</b> (or a sketch, or its lines; "
                             "several sketches make a 3D route too). To start on a flange, "
                             "click its face edge.")
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
                self._set_spec_fields(self.route)
                build(self.route)
            else:
                r = self.route
                self._set_spec_fields(r)
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
            self._refresh_changes()
        except Exception as e:
            self.error.setText(f"<b>Can't route this:</b> {e}")
            self.error.show()
            if self.route is not None:
                self.route.Error = str(e)

    def _set_spec_fields(self, r):
        from mechflow_gui import pipespec
        ensure_props(r)
        name = self.spec.currentText()
        sp = pipespec.get(name)
        r.Spec = "" if name == "(none)" else name
        r.Material = self.material.currentText().strip()
        if sp is not None:
            r.ScheduleBySize = json.dumps(sp.get("schedule_by_size") or {}, sort_keys=True)
        elif not r.Spec:
            r.ScheduleBySize = "{}"

    def _summary(self):
        parts = list(self.route.Parts)
        pipes = [p for p in parts if getattr(p, "StdType", "").endswith("-PIPE")]
        elbows = [p for p in parts if "-90" in getattr(p, "StdType", "") or
                  "-45" in getattr(p, "StdType", "") or "LR" in getattr(p, "StdType", "")]
        total = sum(float(p.Length) for p in pipes)
        reds = [p for p in parts if getattr(p, "StdType", "").endswith("-RED")]
        sizes = sorted({p.Size for p in pipes}, key=lambda z: -_size_key(self.route.Standard, z))
        extra = (f", <b>{len(reds)} reducer{'s' if len(reds) != 1 else ''}</b> "
                 f"({' / '.join(sizes)})") if reds else ""
        self.msg.setText(f"<b>{len(pipes)} pipe{'s' if len(pipes) != 1 else ''}</b> "
                         f"({total:,.0f} mm), <b>{len(elbows)} elbow"
                         f"{'s' if len(elbows) != 1 else ''}</b>{extra}, {len(parts)} parts in all. "
                         "Click more lines or flanges, or OK.")

    def accept(self):
        self._timer.stop()
        if self.route is None or not self.route.Parts:
            if self.links and not self.error.isHidden():
                text = ("This path can't be piped yet - see the red message. Change the "
                        "sketch (or the size), or Cancel.")
            else:
                text = "Pick the route's sketch first - or Cancel."
            QtWidgets.QMessageBox.information(self.form, "Route Pipe", text)
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


# ------------------------------------------------------------ change pipe size

def selected_route_pipe():
    """(route, line key, pipe) for a selected route pipe, else None."""
    try:
        sel = Gui.Selection.getSelection()
    except Exception:
        return None
    for o in sel:
        key = getattr(o, "RouteLine", "")
        rname = getattr(o, "MechFlowRoute", "")
        if key and rname:
            r = o.Document.getObject(rname)
            if r is not None and is_route(r):
                return r, key, o
    return None


class ChangeSizeDialog(QtWidgets.QDialog):
    def __init__(self, route, key, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Change Pipe Size")
        self.setMinimumWidth(480)
        self.route, self.key = route, key
        lay = QtWidgets.QVBoxLayout(self)
        cur = size_changes(route).get(key)
        lab = QtWidgets.QLabel(
            f"Size from <b>{describe_key(route, key)}</b> of <b>{route.Label}</b> on: the pipe "
            "carries on at this size downstream until the next size change, and reducers "
            "go in where it changes.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.combo = QtWidgets.QComboBox()
        self.combo.addItem("Same as the pipe before it (no change here)")
        self.combo.addItems(sizes_for(route.Standard))
        if cur:
            self.combo.setCurrentText(cur)
        lay.addWidget(self.combo)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020;")
        self.error.hide()
        lay.addWidget(self.error)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def chosen(self):
        return None if self.combo.currentIndex() == 0 else self.combo.currentText()

    def apply(self):
        r = self.route
        old = list(getattr(r, "SizeChanges", []) or [])
        doc = r.Document
        doc.openTransaction("Change Pipe Size")
        try:
            set_size_change(r, self.key, self.chosen())
            build(r)
        except Exception as e:
            r.SizeChanges = old
            try:
                build(r)
            except Exception:
                pass
            doc.abortTransaction()
            self.error.setText(f"<b>Can't do that:</b> {e}")
            self.error.show()
            self.adjustSize()
            return False
        doc.commitTransaction()
        self.accept()
        return True


def change_pipe_size():
    hit = selected_route_pipe()
    if hit is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Change Pipe Size",
                                          "Select a pipe of a route first (right-click it).")
        return None
    r, key, _pipe = hit
    install()
    d = ChangeSizeDialog(r, key)
    d.exec()
    return d
