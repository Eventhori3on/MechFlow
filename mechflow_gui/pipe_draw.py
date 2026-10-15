# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draw Pipe: the pipe itself while you draw it.

The 3D Sketch's drawing, with the route's real pipe, elbows, tees and
flanges shown as each line goes in (a light preview - the bolts come at
OK), plus:

- start or finish on a nozzle or flange face, a tee's branch end, an open
  pipe end; click part way along a pipe to branch off it (a tee goes in);
- Route to...: click where the pipe has to go and MechFlow offers the
  square ways round (Tab for the next), click again to take one;
- click a straight to get its grips: drag it across (the pipes either side
  stretch) or type its length.
"""

import itertools

import FreeCAD as App

V = App.Vector
PREVIEW = "MechFlowPipePreview"
AX = [V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)]


# ------------------------------------------------------------ what to build

def spec_settings(spec, size):
    """route_like settings (as routing.settings gives) from a pipe spec."""
    return {"Standard": spec["standard"], "Size": size,
            "Schedule": spec["schedule"] if spec["standard"] == "ASME" else "",
            "Bend": spec["bend"], "FreeEnds": spec["free_ends"],
            "FlangeRating": spec["rating"],
            "ScheduleBySize": dict(spec.get("schedule_by_size") or {}),
            "SizeChanges": {}, "Material": spec.get("material", ""), "EndTypes": {}}


def elbow_room(settings, size=None):
    """(outside diameter, how much straight one 90 degree elbow takes)."""
    from mechflow_gui import routing
    size = size or settings["Size"]
    sched = (settings.get("ScheduleBySize") or {}).get(size) or settings.get("Schedule") \
        or "Sch 40"
    od, _w, R, _C, _E = routing.fitting_dims(settings["Standard"], size, sched,
                                             settings["Bend"])
    return od, R


def segments(sketch, ed):
    """[(a, b, key)] of the editor's lines, keyed as the route keys them."""
    out = []
    n = 0
    for (a, b) in ed.lines:
        A, B = ed.pts[a], ed.pts[b]
        if (B - A).Length > 1e-6:
            n += 1
            out.append((V(A), V(B), f"{sketch.Name}:Edge{n}"))
    return out


def plan_for(settings, segs, components=()):
    from mechflow_gui import routing
    s = dict(settings)
    s["segments"] = list(segs)
    s["components"] = list(components)
    return routing.plan(s, ())


# ------------------------------------------------------------ the preview

_shape_cache = {}


def _shape(t, size, rating, length, angle):
    from mechflow_gui import stdparts
    key = (t, size, rating, round(length, 1), round(angle, 3))
    sh = _shape_cache.get(key)
    if sh is None:
        sh = stdparts.shape_for(t, size, rating, length, angle)
        if len(_shape_cache) > 400:
            _shape_cache.clear()
        _shape_cache[key] = sh
    return sh


def preview_shape(parts, placement=None):
    """One compound of the planned parts (no bolts), in global axes."""
    import Part
    from mechflow_gui import inline
    shapes = []
    for p in parts:
        try:
            if p["role"] == "component":
                c = p["obj"]
                sh = c.Shape.copy()
                sh.Placement = inline.placement_for(c, p["centre"], p["dir"], p["od"])
            else:
                sh = _shape(p["type"], p["size"], p["rating"] or "", p["length"] or 1000.0,
                            p.get("angle") or 0.0).copy()
                sh.Placement = p["placement"]
            if placement is not None:
                sh.Placement = placement.multiply(sh.Placement)
            shapes.append(sh)
        except Exception:
            continue
    return Part.makeCompound(shapes) if shapes else None


def show_preview(doc, shape):
    o = doc.getObject(PREVIEW)
    if shape is None:
        if o is not None:
            o.Shape = _empty()
        return o
    if o is None:
        o = doc.addObject("Part::Feature", PREVIEW)
        o.Label = "Pipe (drawing)"
        try:
            vo = o.ViewObject
            vo.ShapeColor = (0.68, 0.70, 0.74)
            vo.LineColor = (0.35, 0.37, 0.40)
            vo.Selectable = False
            vo.ShowInTree = False
        except Exception:
            pass
    o.Shape = shape
    return o


def _empty():
    import Part
    return Part.Shape()


def drop_preview(doc):
    try:
        if doc.getObject(PREVIEW) is not None:
            doc.removeObject(PREVIEW)
    except Exception:
        pass


# ------------------------------------------------------------ Route to...

def _clean(pts):
    out = []
    for p in pts:
        if not out or (p - out[-1]).Length > 0.5:
            out.append(V(p))
    # merge straight runs
    k = 1
    while 0 < k < len(out) - 1:
        d1 = out[k] - out[k - 1]
        d2 = out[k + 1] - out[k]
        if d1.Length > 0 and d2.Length > 0 and \
                abs(d1.normalize().dot(V(d2).normalize()) - 1) < 1e-9:
            out.pop(k)
        else:
            k += 1
    return out


def auto_routes(S, T, ds=None, dt=None, back=None, leg_min=0.0, end_min=0.0):
    """Square routes from S to T: [[S, ..., T]], fewest bends first.
    ds: the way the pipe has to leave S (a nozzle's axis), dt: the way it
    has to leave T going back (so it arrives along -dt); back: the way the
    pipe came into S (it can't turn straight back). Straights between two
    bends at least leg_min, the first and last at least end_min."""
    stub = max(end_min, 1.0)
    A = S + ds * stub if ds is not None else V(S)
    B = T + dt * stub if dt is not None else V(T)
    found = {}
    for perm in itertools.permutations(range(3)):
        pts = [V(S)]
        if ds is not None:
            pts.append(V(A))
        p = V(A)
        for ax in perm:
            q = V(p)
            if ax == 0:
                q.x = B.x
            elif ax == 1:
                q.y = B.y
            else:
                q.z = B.z
            pts.append(q)
            p = q
        if dt is not None:
            pts.append(V(T))
        pts = _clean(pts)
        if len(pts) < 2 or not _valid(pts, ds, dt, back, leg_min, end_min):
            continue
        key = tuple((round(q.x, 1), round(q.y, 1), round(q.z, 1)) for q in pts)
        found[key] = pts
    out = list(found.values())
    out.sort(key=lambda ps: (len(ps), sum((ps[i + 1] - ps[i]).Length
                                          for i in range(len(ps) - 1))))
    return out


def _valid(pts, ds, dt, back, leg_min, end_min):
    dirs = []
    for i in range(len(pts) - 1):
        d = pts[i + 1] - pts[i]
        L = d.Length
        if L < 0.5:
            return False
        dirs.append((V(d).normalize(), L))
    for i in range(len(dirs) - 1):
        if dirs[i][0].dot(dirs[i + 1][0]) < -1 + 1e-9:
            return False                      # straight back on itself
    if back is not None and dirs[0][0].dot(back) < -1 + 1e-9:
        return False
    if ds is not None and dirs[0][0].dot(ds) < 1 - 1e-9:
        return False
    if dt is not None and dirs[-1][0].dot(dt * -1) < 1 - 1e-9:
        return False
    n = len(dirs)
    for i, (_d, L) in enumerate(dirs):
        inner = 0 < i < n - 1
        if n == 1:
            continue
        need = leg_min if inner else end_min
        if L + 1e-6 < need:
            return False
    return True


# ------------------------------------------------------------ geometry helpers

def clashes(pts, obstacles, radius, skip_ends=None):
    """Labels of the obstacles a pipe along pts (global) runs through. The
    first and last bits (where it meets its nozzles) are left out."""
    import Part
    skip = radius * 2 if skip_ends is None else skip_ends
    segs = []
    n = len(pts) - 1
    for i in range(n):
        a, b = V(pts[i]), V(pts[i + 1])
        d = b - a
        L = d.Length
        if L < 1e-6:
            continue
        u = V(d)
        u.normalize()
        if i == 0:
            a = a + u * min(skip, L / 2)
        if i == n - 1:
            b = b - u * min(skip, L / 2)
        if (b - a).Length > 1e-3:
            segs.append(Part.LineSegment(a, b).toShape())
    if not segs:
        return []
    wire = Part.makeCompound(segs)
    hits = []
    for label, sh in obstacles:
        try:
            bb = sh.BoundBox
            bb.enlarge(radius)
            if not bb.intersect(wire.BoundBox):
                continue
            if wire.distToShape(sh)[0] < radius or any(sh.isInside(e.Vertexes[0].Point, 0.01, True)
                                                       for e in segs):
                hits.append(label)
        except Exception:
            continue
    return hits


def ray_segment(p, d, A, B):
    """(distance between the ray p + t d and segment AB, t, point on AB)."""
    u = B - A
    w0 = p - A
    a = d.dot(d)
    b = d.dot(u)
    c = u.dot(u)
    dd = d.dot(w0)
    e = u.dot(w0)
    den = a * c - b * b
    if c < 1e-12:
        s = 0.0
        t = -dd / a
    elif abs(den) < 1e-12:
        s = 0.0
        t = -dd / a
    else:
        t = (b * e - c * dd) / den
        s = (a * e - b * dd) / den
    s = max(0.0, min(1.0, s))
    q = A + u * s
    t = (q - p).dot(d) / a
    r = p + d * t
    return (r - q).Length, t, q


def outward(obj, sub, centre, axis):
    """A round edge's axis pointing out of its part (the way a pipe leaves)."""
    a = V(axis)
    a.normalize()
    try:
        c = obj.Shape.BoundBox.Center
        if (centre - c).dot(a) < 0:
            a = a * -1
    except Exception:
        pass
    return a


# ------------------------------------------------------------ the panel

def _panel_base():
    from mechflow_gui import sketch3d
    return sketch3d.Sketch3DPanel


def make_panel(sketch=None, routes=None):
    """A Draw Pipe panel: a new pipe (sketch None) or a route's sketch."""
    cls = _pipe_panel_class()
    return cls(sketch)


_CLS = []


def _pipe_panel_class():
    if _CLS:
        return _CLS[0]
    import FreeCADGui as Gui
    from mechflow_gui import sketch3d
    from mechflow_gui.sketch3d import AXES, V as _V, to_global, to_local, round_to
    try:
        from PySide6 import QtCore, QtWidgets
    except ImportError:
        from PySide2 import QtCore, QtWidgets

    class PipePanel(sketch3d.Sketch3DPanel):
        """3D Sketch drawing with the real pipe shown as it goes in."""

        def __init__(self, sketch=None):
            self.pipe = True
            self.sel_line = None          # straight with grips
            self.pending = None           # (line, local point): a branch starts here
            self.auto = None              # Route to... state
            self.joins = []               # (other route, global point) ends welded on
            self._grips = []
            self._grip_timer = QtCore.QTimer()
            self._grip_timer.setInterval(60)
            self._grip_timer.timeout.connect(self._grip_tick)
            self._settle = QtCore.QTimer()
            self._settle.setSingleShot(True)
            self._settle.setInterval(350)
            self._settle.timeout.connect(self._grip_settled)
            self._hidden = []
            self.route = None
            super().__init__(sketch)
            rs = self.routes()
            self.route = rs[0] if rs else None
            self._set_mode_ui()
            self._update_preview()

        # -- what's being drawn
        def _set_mode_ui(self):
            new = self.route is None
            for w in (self.spec_l, self.spec, self.size_l, self.size):
                w.setVisible(new)
            if not new:
                self.route_l.setText(
                    f"<b>{self.route.Label}</b> ({getattr(self.route, 'Spec', '') or self.route.Standard}"
                    f", {self.route.Size}) - shown as it will be built; OK rebuilds it.")
            self.route_l.setVisible(not new)

        def _build(self):
            w = super()._build()
            from mechflow_gui import pipespec, routing
            lay = w.layout()
            box = QtWidgets.QGroupBox("Pipe")
            g = QtWidgets.QGridLayout(box)
            self.spec_l = QtWidgets.QLabel("Spec")
            self.spec = QtWidgets.QComboBox()
            self.spec.addItems([x["name"] for x in pipespec.all_specs()])
            from mechflow_gui import drawings  # noqa: F401  (FreeCAD params)
            p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
            last = p.GetString("DrawPipeSpec", "")
            if last and self.spec.findText(last) >= 0:
                self.spec.setCurrentText(last)
            self.size_l = QtWidgets.QLabel("Size")
            self.size = QtWidgets.QComboBox()
            g.addWidget(self.spec_l, 0, 0)
            g.addWidget(self.spec, 0, 1)
            g.addWidget(self.size_l, 1, 0)
            g.addWidget(self.size, 1, 1)
            self.route_l = QtWidgets.QLabel()
            self.route_l.setWordWrap(True)
            g.addWidget(self.route_l, 2, 0, 1, 2)
            row = QtWidgets.QHBoxLayout()
            self.route_to = QtWidgets.QPushButton("Route to... (R)")
            self.route_to.setToolTip("Click where the pipe has to go (a nozzle, flange, pipe "
                                     "or point): it offers the square ways round - Tab for "
                                     "the next, click again to take it")
            self.route_to.clicked.connect(self.start_auto)
            row.addWidget(self.route_to)
            g.addLayout(row, 3, 0, 1, 2)
            self.perr = QtWidgets.QLabel()
            self.perr.setWordWrap(True)
            self.perr.setStyleSheet("color: #b00020;")
            self.perr.hide()
            g.addWidget(self.perr, 4, 0, 1, 2)
            self.sel_box = QtWidgets.QLabel()
            self.sel_box.setWordWrap(True)
            self.sel_box.setStyleSheet("color: #1a5fb4;")
            self.sel_box.hide()
            g.addWidget(self.sel_box, 5, 0, 1, 2)
            lay.insertWidget(1, box)
            self._fill_sizes()
            self.spec.currentTextChanged.connect(self._spec_changed)
            self.size.currentTextChanged.connect(lambda _t: self._update_preview())
            w.setWindowTitle("Draw Pipe")
            return w

        def _fill_sizes(self):
            from mechflow_gui import pipespec, routing
            sp = pipespec.get(self.spec.currentText())
            if sp is None:
                return
            cur = self.size.currentText()
            self.size.blockSignals(True)
            self.size.clear()
            self.size.addItems(routing.sizes_for(sp["standard"]))
            p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
            want = cur or p.GetString("DrawPipeSize", "") or sp.get("start_size") or ""
            if want and self.size.findText(want) >= 0:
                self.size.setCurrentText(want)
            elif self.size.findText("DN100") >= 0:
                self.size.setCurrentText("DN100")
            elif self.size.findText("NPS 4") >= 0:
                self.size.setCurrentText("NPS 4")
            self.size.blockSignals(False)

        def _spec_changed(self, _t):
            self._fill_sizes()
            self._update_preview()

        def settings(self):
            from mechflow_gui import pipespec, routing
            if self.route is not None:
                return routing.settings(self.route)
            sp = pipespec.get(self.spec.currentText()) or pipespec.all_specs()[0]
            s = spec_settings(sp, self.size.currentText())
            s["EndTypes"] = self._join_ends()
            return s

        def _join_ends(self):
            out = {}
            from mechflow_gui import inline
            for (o, _subs), i in zip(self.ed.anchors, self.ed.anchor_pts):
                if i < len(self.ed.pts) and inline.is_component(o):
                    p = self.ed.pts[i]
                    out[",".join(f"{x:g}" for x in (round(p.x, 3), round(p.y, 3),
                                                     round(p.z, 3)))] = \
                        "Weld neck flange" if o.EndType in ("flanged", "wafer") else "Plain"
            for _r, g in self.joins:
                p = to_local(self.sketch, g)
                out[",".join(f"{x:g}" for x in (round(p.x, 3), round(p.y, 3),
                                                 round(p.z, 3)))] = "Plain"
            return out

        def _segments(self):
            from mechflow_gui import routing
            segs = segments(self.sketch, self.ed)
            if self.route is not None:
                others = [(x, s_) for x, s_ in routing.path_links(self.route)
                          if x is not self.sketch]
                if others:
                    segs += routing.path_segments_keyed(others)
            return segs

        def _components(self, s):
            from mechflow_gui import inline, routing, stdparts
            if self.route is None:
                return []
            o = self.route
            ty = routing.types_for(o.Standard, o.Bend)
            frate = o.FlangeRating or stdparts.default_rating(ty["flange"])
            out = []
            for c in inline.components_of(o):
                _f, end = inline.ftf_and_end(c, o.Standard, s["Size"])
                out.append({"obj": c, "position": _V(c.Position), "end": end,
                            "reverse": bool(c.Reverse),
                            "ftf": (lambda size, c=c: inline.ftf_and_end(c, o.Standard, size)),
                            "ports": inline.port_sizes(c, o.Standard, frate)})
            return out

        def od(self):
            try:
                return elbow_room(self.settings())[0]
            except Exception:
                return 100.0

        def bend_room(self):
            try:
                return elbow_room(self.settings())[1]
            except Exception:
                return 150.0

        def _update_preview(self):
            if not hasattr(self, "perr"):
                return
            try:
                s = self.settings()
                if not s["Size"]:
                    from mechflow_gui import routing
                    s["Size"] = routing.sizes_for(s["Standard"])[0]
                segs = self._segments()
                if not segs:
                    show_preview(self.doc, None)
                    self.perr.hide()
                    return
                parts, _ends = plan_for(s, segs, self._components(s))
                c = sketch3d._container(self.sketch)
                pl = c.getGlobalPlacement() if c is not None else None
                show_preview(self.doc, preview_shape(parts, pl))
                self.perr.hide()
            except Exception as e:
                self.perr.setText(f"<b>Can't pipe this yet:</b> {e}")
                self.perr.show()

        # -- the route's own parts are hidden while it's drawn (the preview
        #    shows it as it will be)
        def _fade_routes(self):
            from mechflow_gui import inline
            objs = []
            for r in self.routes():
                objs += list(r.Parts) + inline.components_of(r)
            for o in objs:
                try:
                    if o.ViewObject.Visibility:
                        o.ViewObject.Visibility = False
                        self._hidden.append(o)
                except Exception:
                    pass
            try:
                self._sketch_vis = self.sketch.ViewObject.Visibility
                self.sketch.ViewObject.Visibility = True
            except Exception:
                pass

        def _unfade(self):
            for o in self._hidden:
                try:
                    o.ViewObject.Visibility = True
                except Exception:
                    pass
            self._hidden = []
            try:
                if hasattr(self, "_sketch_vis"):
                    self.sketch.ViewObject.Visibility = self._sketch_vis
                    del self._sketch_vis
            except Exception:
                pass

        def _refresh(self):
            super()._refresh()
            self._update_preview()
            if self.sel_line is not None and self.sel_line < len(self.ed.lines):
                self._show_grips(self.sel_line)

        def _refresh_msg(self):
            super()._refresh_msg()
            if self.auto is not None:
                a = self.auto
                if a.get("T") is None:
                    t = "<b>Route to:</b> click where the pipe has to go."
                else:
                    t = (f"<b>Route to:</b> way {a['i'] + 1} of {len(a['cands'])} - Tab for "
                         "another, click (or Enter) to take it, Esc to stop."
                         + self._clash_text(a["cands"][a["i"]]))
            elif self.pending is not None:
                t = "<b>Branch:</b> click where the branch goes (or Route to...); Esc to stop."
            elif self.ed.current is None and self.ed.lines:
                t = ("Click a pipe to branch off it or to get its grips (drag it across, type "
                     "its length); click a point to carry on from it.")
            else:
                return
            self.msg.setText(t + "<br>" + self.msg.text().split("<br>", 1)[-1])

        # -- where things are
        def _info_at(self, pos):
            """What's under the mouse, looking through the drawing preview."""
            try:
                infos = self.view.getObjectsInfo((int(pos[0]), int(pos[1]))) or []
            except Exception:
                infos = []
            hidden = {o.Name for o in self._hidden}
            for info in infos:
                n = info.get("Object", "")
                if n == PREVIEW or n in hidden:
                    continue
                return info
            return None

        def cur_local(self):
            if self.ed.current is not None:
                return self.ed.pts[self.ed.current]
            if self.pending is not None:
                return self.pending[1]
            return None

        def _ray_point(self, pos):
            view = self.view
            p = _V(view.getPoint(int(pos[0]), int(pos[1])))
            d = _V(view.getViewDirection())
            n = self._normal()
            c = self.cur_local()
            base = to_global(self.sketch, c) if c is not None else _V(0, 0, 0)
            den = d.dot(n)
            if abs(den) < 1e-9:
                return None
            t = (base - p).dot(n) / den
            return p + d * t

        def _candidate(self, pos):
            hit = self._pick(pos)
            if hit is not None:
                g, anchor, idx = hit
                return to_local(self.sketch, g), anchor, idx
            g = self._ray_point(pos)
            if g is None:
                return None
            q = to_local(self.sketch, g)
            c = self.cur_local()
            if c is not None:
                if self.ortho.isChecked():
                    q = sketch3d.snap_axis(c, q, self._normal())
                q = round_to(q, c, self.step.value())
            return q, None, None

        def _px_mm(self, pos):
            try:
                a = _V(self.view.getPoint(int(pos[0]), int(pos[1])))
                b = _V(self.view.getPoint(int(pos[0]) + 10, int(pos[1])))
                return (b - a).Length / 10.0
            except Exception:
                return 1.0

        def line_hit(self, pos):
            """(line, local point) of this sketch's pipe under the mouse."""
            if not self.ed.lines:
                return None
            p = _V(self.view.getPoint(int(pos[0]), int(pos[1])))
            d = _V(self.view.getViewDirection())
            tol = max(self.od() / 2 + 2, 8 * self._px_mm(pos))
            best = None
            for k, (a, b) in enumerate(self.ed.lines):
                A = to_global(self.sketch, self.ed.pts[a])
                B = to_global(self.sketch, self.ed.pts[b])
                if (B - A).Length < 1e-6:
                    continue
                dist, t, q = ray_segment(p, d, A, B)
                if dist <= tol and (best is None or t < best[0]):
                    best = (t, k, q)
            if best is None:
                return None
            return best[1], to_local(self.sketch, best[2])

        def other_route_hit(self, pos):
            """(route, its sketch, line, local point, free end or None) of another
            route's pipe under the mouse."""
            from mechflow_gui import routing
            try:
                info = self._info_at(pos)
            except Exception:
                info = None
            if not info:
                return None
            obj = self.doc.getObject(info.get("Object", ""))
            r = routing.route_of(obj) if obj is not None else None
            if r is None or r in self.routes():
                return None
            sk = routing.route_sketch(r)
            if sk is None or not sketch3d.is_sketch3d(sk):
                return None
            g = _V(info["x"], info["y"], info["z"])
            ed = sketch3d.Editor(sk)
            q = to_local(sk, g)
            best = None
            for k, (a, b) in enumerate(ed.lines):
                A, B = ed.pts[a], ed.pts[b]
                u = B - A
                if u.Length < 1e-6:
                    continue
                t = max(0.0, min(1.0, (q - A).dot(u) / u.dot(u)))
                c = A + u * t
                dd = (q - c).Length
                if best is None or dd < best[0]:
                    best = (dd, k, c)
            if best is None:
                return None
            _dd, k, c = best
            free = None
            for i in ed.lines[k]:
                if ed.is_free_end(i) and (ed.pts[i] - c).Length < max(150.0, self.od() * 2):
                    free = i
            return r, sk, k, c, free

        # -- clicks
        def _on_move(self, cb):
            try:
                ev = cb.getEvent()
                pos = ev.getPosition().getValue()
                if self.auto is not None:
                    self._auto_hover(pos)
                    return
                c = self.cur_local()
                if c is not None and self._pick(pos) is None:
                    lh = self.line_hit(pos)
                    if lh is not None and (self.pending is None or lh[0] != self.pending[0]):
                        j = self._junction(lh[0], c, lh[1])
                        self._rubber([c, j])
                        return
                super()._on_move(cb)
                if self.pending is not None and self.ed.current is None and self.hover:
                    self._rubber([self.pending[1], self.hover[0]])
            except Exception:
                pass

        def _rubber(self, local_pts):
            g = [to_global(self.sketch, q) for q in local_pts]
            self._coords.point.setValues(0, len(g), [(q.x, q.y, q.z) for q in g])
            self._line.numVertices.setValue(len(g))
            self._dot.numPoints.setValue(0)
            if len(g) == 2:
                self._box.set_quiet(round((g[1] - g[0]).Length))
                self._box.place((g[0] + g[1]) * 0.5)

        def _junction(self, k, cur, near):
            """Where a line from cur meets line k square on (else near)."""
            a, b = self.ed.lines[k]
            A, B = self.ed.pts[a], self.ed.pts[b]
            u = B - A
            L = u.Length
            if L < 1e-6:
                return near
            u = _V(u)
            u.normalize()
            t = max(0.0, min(L, (cur - A).dot(u)))
            j = A + u * t
            d = j - cur
            if d.Length > 1e-6:
                dn = _V(d)
                dn.normalize()
                if max(abs(dn.x), abs(dn.y), abs(dn.z)) > 1 - 1e-6:
                    return j
            return near

        def _on_click(self, cb):
            try:
                from pivy import coin
                ev = cb.getEvent()
                if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
                    return
                pos = ev.getPosition().getValue()
                if ev.getState() != coin.SoButtonEvent.DOWN:
                    if getattr(self, "_on_grip_drag", False):
                        self._on_grip_drag = False      # the arrow's own release
                        return
                    cb.setHandled()
                    return
                if self.on_grip(pos):
                    self._on_grip_drag = True           # let the arrow be dragged
                    return
                if self.auto is not None:
                    cb.setHandled()
                    self._auto_click(pos)
                    return
                if self.pipe_click(pos):
                    cb.setHandled()
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow Draw Pipe: {e}\n")

        def pipe_click(self, pos):
            ed = self.ed
            hit = self._pick(pos)
            if hit is None:
                lh = self.line_hit(pos)
                if lh is not None:
                    k, q = lh
                    if ed.current is not None:
                        self.join_line(k, self._junction(k, ed.pts[ed.current], q))
                    else:
                        self.select_line(k, q)
                    return True
                oh = self.other_route_hit(pos)
                if oh is not None:
                    self.other_route_click(*oh)
                    return True
            c = self._candidate(pos)
            if c is None:
                return False
            self.click(*c)
            return True

        def click(self, q, anchor=None, idx=None):
            if self.pending is not None and self.ed.current is None:
                k, p = self.pending
                self.pending = None
                i = self.ed.split_line(k, p)
                self.ed.current = i
            self._hide_grips()
            self.sel_line = None
            super().click(q, anchor, idx)

        def join_line(self, k, p):
            """End the current run on line k at p (a tee goes in)."""
            ed = self.ed
            i = ed.split_line(k, p)
            if ed.current is not None and i != ed.current:
                ed.line_to(ed.pts[i])
            ed.stop()
            self.pending = None
            self._clear_preview()
            self._refresh()

        def select_line(self, k, q=None):
            """Line k gets its grips; a branch can start at q."""
            self.sel_line = k
            if q is not None:
                a, _b = self.ed.lines[k]
                A = self.ed.pts[a]
                d = q - A
                step = self.step.value()
                if step > 0 and d.Length > 0:
                    q = A + d * (round(d.Length / step) * step / d.Length)
                self.pending = (k, q)
            self._show_grips(k)
            self._refresh_msg()

        def branch_from(self, k, p):
            self.select_line(k, p)

        def other_route_click(self, r, sk, k, c, free):
            ed = self.ed
            if ed.current is not None:
                if free is None:
                    self.perr.setText("To join into the middle of that pipe, draw the branch "
                                      "from it: OK this one, then click that pipe.")
                    self.perr.show()
                    return
                g = to_global(sk, sketch3d.Editor(sk).pts[free])
                ed.line_to(to_local(self.sketch, g))
                self.joins.append((r, g))
                ed.stop()
                self._clear_preview()
                self._refresh()
                return
            if ed.lines:
                self.perr.setText(f"That's {r.Label}: OK this pipe first, then click it to "
                                  "carry on or branch from it.")
                self.perr.show()
                return
            self.switch_to(r)
            if free is not None:
                self.ed.current = free
                self._refresh_msg()
            else:
                self.select_line(k, c)

        def switch_to(self, r):
            """Carry on drawing route r (this new, empty sketch is dropped)."""
            from mechflow_gui import routing
            sk = routing.route_sketch(r)
            old = self.sketch
            self._unfade()
            show_preview(self.doc, None)
            try:
                if self.new and not self.ed.lines:
                    self.doc.removeObject(old.Name)
            except Exception:
                pass
            self.sketch = sk
            self.ed = sketch3d.Editor(sk)
            self.ed.current = None
            self.new = False
            self.route = r
            self._fade_routes()
            self._set_mode_ui()
            self._refresh()

        # -- grips on the selected straight
        def _show_grips(self, k):
            from mechflow_gui import view_handles as vh
            self._hide_grips()
            if k is None or k >= len(self.ed.lines):
                return
            a, b = self.ed.lines[k]
            A, B = self.ed.pts[a], self.ed.pts[b]
            mid = to_global(self.sketch, (A + B) * 0.5)
            scale = max(self.od() * 1.6, 80.0)
            self._grip_origin = mid
            self._grip_line = k
            self._grip_applied = {}
            for name in self.ed.drag_axes(k):
                ax = AXES[name]
                try:
                    arr = vh.Arrow(mid, ax, 0.0, scale)
                    self._grips.append(("arrow", name, arr))
                except Exception:
                    pass
                try:
                    arr2 = vh.Arrow(mid, ax * -1, 0.0, scale)
                    self._grips.append(("arrow", "-" + name[1:], arr2))
                except Exception:
                    pass
            box = vh.ViewBox(" mm", 1, 1e6, 0)
            box.set_quiet(round((B - A).Length))
            box.valueChanged.connect(lambda v, k=k: self.set_line_length(k, v))
            box.place(mid, 20, 18)
            box.show()
            self._grips.append(("box", None, box))
            self._grip_timer.start()
            L = (B - A).Length
            n = len([g for g in self._grips if g[0] == "arrow"])
            self.sel_box.setText(f"<b>Straight {k + 1}</b>: {L:,.0f} mm - type its length in "
                                 "the box" + (", drag the arrows to move it across (the pipes "
                                              "either side stretch)" if n else
                                              " (it can't be dragged across: the pipes at "
                                              "its ends don't run that way)") +
                                 ". Click elsewhere to branch from it there.")
            self.sel_box.show()

        def on_grip(self, pos):
            """Is the mouse on one of the grip arrows?"""
            arrows = [g[2] for g in self._grips if g[0] == "arrow" and g[2].root is not None]
            if not arrows:
                return False
            try:
                from pivy import coin
                viewer = self.view.getViewer()
                rm = viewer.getSoRenderManager()
                act = coin.SoRayPickAction(rm.getViewportRegion())
                act.setPoint(coin.SbVec2s(int(pos[0]), int(pos[1])))
                act.setRadius(6)
                act.setPickAll(True)
                act.apply(rm.getSceneGraph())
                for pp in act.getPickedPointList():
                    path = pp.getPath()
                    for a in arrows:
                        if path.containsNode(a.root):
                            return True
            except Exception:
                return False
            return False

        def _hide_grips(self):
            self._grip_timer.stop()
            for kind, _n, g in self._grips:
                try:
                    g.remove()
                except Exception:
                    pass
            self._grips = []
            try:
                self.sel_box.hide()
            except Exception:
                pass

        def _grip_tick(self):
            try:
                for kind, name, g in self._grips:
                    if kind == "box":
                        g.place(self._grip_origin, 20, 18)
                        continue
                    d = g.moved()
                    if d is None:
                        continue
                    if self.pending is not None:
                        self.pending = None
                        self._clear_preview()
                    step = self.step.value() or 1.0
                    want = round(d / step) * step
                    have = self._grip_applied.get(name, 0.0)
                    if abs(want - have) < 1e-6:
                        continue
                    self.ed.move_line(self._grip_line, AXES[name] * (want - have))
                    self._grip_applied[name] = want
                    self._settle.start()
                    self._quick_preview()
            except Exception:
                pass

        def _quick_preview(self):
            if getattr(self, "_qp", None) is None:
                self._qp = QtCore.QTimer()
                self._qp.setSingleShot(True)
                self._qp.setInterval(120)
                self._qp.timeout.connect(self._grip_preview)
            if not self._qp.isActive():
                self._qp.start()

        def _grip_preview(self):
            self.ed.save()
            self._show_labels()
            self._update_preview()

        def _grip_settled(self):
            k = self._grip_line
            self._refresh()
            self.select_line(k)

        def drag_line(self, k, axis_name, dist):
            """Move straight k dist mm along an axis (what dragging its grip does)."""
            if axis_name.lstrip("+-") and ("+" + axis_name[-1]) not in \
                    ["+" + n[-1] for n in self.ed.drag_axes(k)]:
                raise ValueError(f"straight {k + 1} can't move along {axis_name}")
            self.ed.move_line(k, AXES[axis_name if axis_name[0] in "+-" else "+" + axis_name]
                              * dist)
            self._refresh()

        def set_line_length(self, k, v):
            self.pending = None
            self.ed.set_length(k, v)
            self._refresh()
            self.select_line(k)
            QtCore.QTimer.singleShot(0, self._focus_view)

        def _focus_view(self):
            """Keys (Esc, R, Tab) go back to the 3D view, not the panel -
            Esc in the panel would cancel it."""
            try:
                mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
                sub = mdi.activeSubWindow() if mdi is not None else None
                if sub is not None:
                    for gv in sub.findChildren(QtWidgets.QGraphicsView):
                        gv.viewport().setFocus()
                        return
                    sub.widget().setFocus()
            except Exception:
                pass

        # -- Route to...
        def start_auto(self):
            if self.cur_local() is None:
                self.perr.setText("Start the pipe first (click a nozzle, a pipe or a point), "
                                  "then Route to... where it goes.")
                self.perr.show()
                return
            self.auto = {"T": None, "i": 0, "cands": [], "anchor": None, "idx": None,
                         "line": None}
            QtCore.QTimer.singleShot(0, self._focus_view)
            self._hide_grips()
            self._refresh_msg()

        def _target(self, pos):
            """(local point, anchor, sketch point, own line) under the mouse."""
            hit = self._pick(pos)
            if hit is not None:
                g, anchor, idx = hit
                return to_local(self.sketch, g), anchor, idx, None
            lh = self.line_hit(pos)
            if lh is not None:
                return lh[1], None, None, lh[0]
            g = self._ray_point(pos)
            if g is None:
                return None
            q = to_local(self.sketch, g)
            c = self.cur_local()
            if c is not None and self.step.value() > 0:
                st = self.step.value()
                q = c + _V(*(round((q[i] - c[i]) / st) * st for i in range(3)))
            return q, None, None, None

        def _dirs(self, anchor_obj=None, anchor_sub=None, at=None):
            """Way out of a nozzle / flange edge, in the sketch's axes."""
            f = sketch3d.circle_frame(anchor_obj, anchor_sub)
            if f is None:
                return None
            ax = outward(anchor_obj, anchor_sub, f[0], f[1])
            g = f[0]
            return to_local(self.sketch, g + ax) - to_local(self.sketch, g)

        def candidates(self, T, t_anchor=None, t_line=None):
            ed = self.ed
            S = self.cur_local()
            ds = back = None
            i = ed.current
            if i is not None:
                for (o, subs), j in zip(ed.anchors, ed.anchor_pts):
                    if j == i and subs:
                        ds = self._dirs(o, subs[0])
                ls = ed.lines_at(i)
                if len(ls) == 1 and ds is None:
                    a, b = ed.lines[ls[0]]
                    other = b if a == i else a
                    back = ed.pts[i] - ed.pts[other]
                    if back.Length > 1e-6:
                        back.normalize()
                    else:
                        back = None
            elif self.pending is not None:
                k = self.pending[0]
                a, b = ed.lines[k]
                u = ed.pts[b] - ed.pts[a]
                back = None
            dt = None
            if t_anchor is not None:
                dt = self._dirs(*t_anchor)
            R = self.bend_room()
            cands = auto_routes(S, T, ds, dt, back, leg_min=2 * R + 10,
                                end_min=R + (100 if (ds is not None or dt is not None) else 20))
            # ways round that go through something come last
            obst = self._obstacles()
            r = self.od() / 2 + 5
            scored = []
            for n, pts in enumerate(cands):
                hits = clashes([to_global(self.sketch, q) for q in pts], obst, r)
                scored.append((len(hits) > 0, n, pts, hits))
            scored.sort(key=lambda x: (x[0], x[1]))
            self._clash = {id(x[2]): x[3] for x in scored}
            return [x[2] for x in scored]

        def _obstacles(self):
            """Visible solids the pipe shouldn't go through: (label, shape)."""
            from mechflow_gui import routing
            out = []
            mine = set(o.Name for o in self._hidden)
            for o in self.doc.Objects:
                try:
                    if o.Name == PREVIEW or o.Name in mine or o is self.sketch:
                        continue
                    if not o.ViewObject or not o.ViewObject.Visibility:
                        continue
                    if not o.isDerivedFrom("Part::Feature") and o.TypeId != "PartDesign::Body":
                        continue
                    if o.TypeId.startswith("PartDesign::") and o.TypeId != "PartDesign::Body":
                        continue
                    sh = o.Shape
                    if not sh.Solids:
                        continue
                    if any(p.TypeId == "PartDesign::Body" for p in o.InList):
                        continue          # the body stands for its features
                    out.append((o.Label, sh))
                except Exception:
                    continue
            return out

        def _clash_text(self, pts):
            hits = getattr(self, "_clash", {}).get(id(pts))
            return f" <span style='color:#b00020'>Goes through {', '.join(hits)}.</span>" \
                if hits else ""

        def _auto_hover(self, pos):
            a = self.auto
            if a["T"] is None:
                t = self._target(pos)
                if t is None:
                    return
                cands = self.candidates(t[0], t[1], t[3])
                a["preview"] = cands[0] if cands else [self.cur_local(), t[0]]
                self._rubber(a["preview"])
                return

        def _auto_click(self, pos):
            a = self.auto
            if a["T"] is None:
                t = self._target(pos)
                if t is None:
                    return
                self.auto_target(*t)
            else:
                self.auto_accept()

        def auto_target(self, T, anchor=None, idx=None, line=None):
            a = self.auto if self.auto is not None else {}
            self.auto = a
            a.update({"T": T, "anchor": anchor, "idx": idx, "line": line, "i": 0})
            a["cands"] = self.candidates(T, anchor, line)
            if not a["cands"]:
                self.perr.setText("No square way round fits there (too close for the elbows) - "
                                  "draw it by hand, or pick a point further away.")
                self.perr.show()
                self.auto = None
                self._clear_preview()
                self._refresh_msg()
                return []
            self.perr.hide()
            self._rubber(a["cands"][0])
            self._refresh_msg()
            return a["cands"]

        def auto_next(self):
            a = self.auto
            if a and a["cands"]:
                a["i"] = (a["i"] + 1) % len(a["cands"])
                self._rubber(a["cands"][a["i"]])
                self._refresh_msg()

        def auto_accept(self):
            a, self.auto = self.auto, None
            if not a or not a.get("cands"):
                return
            pts = a["cands"][a["i"]]
            ed = self.ed
            if ed.current is None and self.pending is not None:
                k, p = self.pending
                self.pending = None
                ed.current = ed.split_line(k, p)
            # a first leg straight on from the pipe coming in lengthens it
            i = ed.current
            if i is not None and len(pts) > 2 and not ed.is_anchored(i) and \
                    len(ed.lines_at(i)) == 1:
                a_, b_ = ed.lines[ed.lines_at(i)[0]]
                o_ = b_ if a_ == i else a_
                d_in = ed.pts[i] - ed.pts[o_]
                d_out = pts[1] - pts[0]
                if d_in.Length > 1e-6 and d_out.Length > 1e-6 and \
                        abs(_V(d_in).normalize().dot(_V(d_out).normalize()) - 1) < 1e-9:
                    ed.pts[i] = _V(pts[1])
                    pts = pts[1:]
            for q in pts[1:-1]:
                ed.line_to(q)
            last = pts[-1]
            if a.get("line") is not None:
                i = ed.split_line(a["line"], last)
                ed.line_to(ed.pts[i])
                ed.stop()
            elif a.get("idx") is not None:
                ed.line_to(ed.pts[a["idx"]])
                ed.stop()
            elif a.get("anchor") is not None:
                ed.line_to(last, a["anchor"])
                ed.stop()
            else:
                ed.line_to(last)
            self._clear_preview()
            self._refresh()

        def _on_key(self, cb):
            try:
                from pivy import coin
                ev = cb.getEvent()
                if ev.getState() != coin.SoButtonEvent.DOWN:
                    return
                k = ev.getKey()
                if self.auto is not None:
                    if k == coin.SoKeyboardEvent.TAB:
                        self.auto_next()
                        cb.setHandled()
                    elif k in (coin.SoKeyboardEvent.RETURN, coin.SoKeyboardEvent.PAD_ENTER):
                        self.auto_accept()
                        cb.setHandled()
                    elif k == coin.SoKeyboardEvent.ESCAPE:
                        self.auto = None
                        self._clear_preview()
                        self._refresh_msg()
                        cb.setHandled()
                    return
                if k == coin.SoKeyboardEvent.R:
                    self.start_auto()
                    cb.setHandled()
                    return
                if k == coin.SoKeyboardEvent.ESCAPE and (self.pending is not None or
                                                          self.sel_line is not None):
                    self.pending = None
                    self.sel_line = None
                    self._hide_grips()
                    self._clear_preview()
                    self._refresh_msg()
                    cb.setHandled()
                    return
            except Exception:
                pass
            super()._on_key(cb)

        def _stop(self):
            self.pending = None
            super()._stop()

        # -- finish
        def _uninstall(self):
            self._hide_grips()
            self._settle.stop()
            super()._uninstall()

        def accept(self):
            from mechflow_gui import pipespec, routing, stdparts, toolbox
            self._uninstall()
            self.ed.save()
            drop_preview(self.doc)
            if not self.ed.lines:
                if self.new:
                    self.doc.abortTransaction()
                    self.doc.recompute()
                    Gui.Control.closeDialog()
                    return True
            try:
                if self.route is None and self.ed.lines:
                    sp = pipespec.get(self.spec.currentText()) or pipespec.all_specs()[0]
                    ty = routing.types_for(sp["standard"], sp["bend"])
                    starts = []
                    for o, subs in self.ed.anchors:
                        for sub in subs:
                            try:
                                if stdparts.joint_with(o, sub, ty["flange"]) is not None:
                                    starts.append((o, sub))
                            except Exception:
                                pass
                    r = routing.make_route(sketch3d._container(self.sketch),
                                           [(self.sketch, None)], sp["standard"],
                                           self.size.currentText(), sp["schedule"], sp["bend"],
                                           sp["free_ends"], sp["rating"], starts,
                                           build_now=False)
                    pipespec.apply_to_route(r, sp)
                    self.route = r
                    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
                    p.SetString("DrawPipeSpec", sp["name"])
                    p.SetString("DrawPipeSize", self.size.currentText())
                for other, g in self.joins:
                    routing.set_end_type(self.route, to_local(self.sketch, g), "Plain")
                    routing.set_end_type(other, g, "Plain")
                if self.route is not None:
                    routing.build(self.route)
                for other in {o for o, _g in self.joins}:
                    routing.build(other)
                self.doc.commitTransaction()
            except Exception as e:
                self.doc.commitTransaction()
                App.Console.PrintWarning(f"MechFlow Draw Pipe: {e}\n")
                if self.route is not None:
                    self.route.Error = str(e)
            self.doc.recompute()
            Gui.Control.closeDialog()
            return True

        def confirm_discard(self):
            """Esc or Cancel with a new pipe drawn: ask before throwing it away."""
            box = QtWidgets.QMessageBox(Gui.getMainWindow())
            box.setWindowTitle("Draw Pipe")
            box.setText(f"Throw away the pipe you've drawn ({len(self.ed.lines)} lines)?")
            box.setStandardButtons(QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel)
            box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
            return box.exec() == QtWidgets.QMessageBox.Discard

        def reject(self):
            if self.new and self.route is None and self.ed.lines and not self.confirm_discard():
                QtCore.QTimer.singleShot(0, self._focus_view)
                return False
            self._uninstall()
            drop_preview(self.doc)
            self.doc.abortTransaction()
            self.doc.recompute()
            Gui.Control.closeDialog()
            return True

    _CLS.append(PipePanel)
    return PipePanel


def draw_pipe():
    """Draw Pipe command: a new pipe - or the selected route's, to change it."""
    import FreeCADGui as Gui
    try:
        from PySide6 import QtWidgets
    except ImportError:
        from PySide2 import QtWidgets
    if App.ActiveDocument is None:
        App.newDocument()
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Draw Pipe",
                                          "Finish the open dialog first.")
        return None
    from mechflow_gui import routing, sketch3d
    routing.install()
    sk = None
    for o in Gui.Selection.getSelection():
        r = routing.route_of(o)
        if r is not None:
            sk = routing.route_sketch(r)
            break
        if sketch3d.is_sketch3d(o):
            sk = o
            break
    Gui.Selection.clearSelection()
    if sk is not None and not sketch3d.is_sketch3d(sk):
        sk = None
    p = make_panel(sk)
    Gui.Control.showDialog(p)
    return p
