import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Draw Pipe: spec and size first, start on a nozzle flange, the real pipe
# shows as the lines go in (a too short leg says so), grips on a straight
# (drag it across, type its length), branch part way along a pipe (a tee),
# Route to... with Tab, OK builds the route; a second pipe carries on from
# the first one's open end; selecting the route and Draw Pipe edits it.
from h import *
import Part
V = App.Vector
S = {}
SPEC = "EN carbon steel PN16"


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("PipeDraw"); S["doc"] = doc
    b = new_body(doc, "Body")
    box = b.newObject("PartDesign::AdditiveBox", "Box"); box.Length = 600; box.Width = 600; box.Height = 600
    doc.recompute()
    from mechflow_gui import nozzle, stdparts
    nz = nozzle.make(b, V(600, 300, 300), V(1, 0, 0), "EN 10220", "DN80", "", 150)
    fl = nozzle.add_flange(nz, "EN1092-1-11", "PN16")[0]
    doc.recompute()
    face, n = stdparts._face_frame(fl)
    f = stdparts.flange_info(fl.StdType, fl.Size, fl.Rating)
    best = None
    for i, e in enumerate(fl.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(2 * c.Radius - f["face"]) < 1e-3:
            d = (c.Center - face).Length
            if best is None or d < best[1]:
                best = (f"Edge{i+1}", d)
    S["fl"], S["fl_edge"], S["face"] = fl, best[0], face
    nz2 = nozzle.make(b, V(300, 0, 300), V(0, -1, 0), "EN 10220", "DN80", "", 150)
    S["fl2"] = nozzle.add_flange(nz2, "EN1092-1-11", "PN16")[0]
    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit")
    Gui.ActiveDocument.ActiveView.viewIsometric()
at(setup, 1500)


def preview():
    o = S["doc"].getObject("MechFlowPipePreview")
    return o.Shape if o is not None else None


def start():
    from mechflow_gui import pipe_draw
    Gui.Selection.clearSelection()
    p = pipe_draw.draw_pipe(); S["p"] = p
    log("panel", type(p).__name__, "specs", [p.spec.itemText(i) for i in range(p.spec.count())])
    assert p.route is None and p.spec.isVisibleTo(p.form)
    p.spec.setCurrentText(SPEC)
    p.size.setCurrentText("DN80")
    log("spec", p.spec.currentText(), "size", p.size.currentText(), "sizes", p.size.count())
    assert p.size.currentText() == "DN80"
    view = Gui.ActiveDocument.ActiveView
    edge = S["fl"].Shape.getElement(S["fl_edge"])
    x, y = view.getPointOnViewport(edge.valueAt(edge.FirstParameter))
    cand = None
    for dx in (0, 1, -1, 2, -2):
        for dy in (0, 1, -1, 2, -2):
            c = p._candidate((x + dx, y + dy))
            if c is not None and c[1] is not None:
                cand = c; break
        if cand: break
    assert cand is not None and (cand[0] - S["face"]).Length < 0.5, "snaps to the flange"
    p.click(*cand)
    # by typing: out +X 1000, up +Z 800, along +Y 1200
    for d, L in (("+X", 1000), ("+Z", 800), ("+Y", 1200)):
        p.dir.setCurrentText(d); p.len.setValue(L); p._add_typed()
    sh = preview()
    s = p.settings()
    from mechflow_gui import pipe_draw as pd
    parts, _e = pd.plan_for(s, p._segments(), [])
    kinds = sorted({q["type"] for q in parts})
    log("preview solids", sh and len(sh.Solids), "parts", len(parts), kinds, "error shown", not p.perr.isHidden())
    assert sh is not None and len(sh.Solids) >= 5, "pipe, elbows, flange shown"
    assert sum(1 for q in parts if "90" in q["type"]) == 2, "two elbows"
    assert p.perr.isHidden()
    # a leg too short for its elbows says so straight away
    p.dir.setCurrentText("+Z"); p.len.setValue(40); p._add_typed()
    p.dir.setCurrentText("-X"); p.len.setValue(400); p._add_typed()
    log("short leg ->", p.perr.text()[:120])
    assert not p.perr.isHidden(), "too short warned"
    p._undo(); p._undo()
    assert p.perr.isHidden(), "warning clears"
    # a typed length in the box by the corner, the way the mouse points
    n0 = len(p.ed.lines)
    p._hover_dir = V(1, 0, 0)
    p._box.setValue(700)
    p._typed_length()
    log("typed 700 ->", p.ed.line_info(len(p.ed.lines) - 1)[2:])
    assert len(p.ed.lines) == n0 + 1 and p.ed.line_info(n0)[2:] == (700.0, "+X")
    p._undo()
    Gui.ActiveDocument.ActiveView.viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(start, 1500)
at(lambda: shot("pipedraw_live"), 800)


def grips():
    p = S["p"]
    p._stop()
    # the last straight (+Y, free end): drag it up along Z - the riser stretches
    k = 2
    axes = p.ed.drag_axes(k)
    log("drag axes of straight 3", axes, "of the first (on the flange)", p.ed.drag_axes(0))
    assert "+Z" in axes and p.ed.drag_axes(0) == []
    p.select_line(k)
    log("grips", [(g[0], g[1]) for g in p._grips], "|", p.sel_box.text()[:80])
    assert any(g[0] == "arrow" for g in p._grips) and any(g[0] == "box" for g in p._grips)
    Gui.updateGui()
    view = Gui.ActiveDocument.ActiveView
    arr = [g[2] for g in p._grips if g[0] == "arrow" and g[1] == "+Z"][0]
    on = [p.on_grip(view.getPointOnViewport(arr.origin + arr.dir * arr.scale * f)) for f in (0.3, 0.6, 0.9)]
    off = p.on_grip(view.getPointOnViewport(arr.origin + V(3000, 3000, 0)))
    log("mouse on the grip", on, "away", off)
    assert any(on) and not off, "grip hit test"
    riser = p.ed.line_info(1)[2]
    # drag the +Z arrow 300 (as the dragger would)
    arr = [g[2] for g in p._grips if g[0] == "arrow" and g[1] == "+Z"][0]
    arr.dragger.translation.setValue(300 / arr.scale, 0, 0)
    p._grip_tick()
    log("riser", riser, "->", p.ed.line_info(1)[2])
    assert abs(p.ed.line_info(1)[2] - riser - 300) < 1e-6
    # type its length in the grip box
    box = [g[2] for g in p._grips if g[0] == "box"][0]
    box.setValue(1500)
    log("length typed ->", round(p.ed.line_info(2)[2]))
    assert abs(p.ed.line_info(2)[2] - 1500) < 1e-6
    p._hide_grips(); p.sel_line = None; p.pending = None
at(grips, 1500)


def branch():
    p = S["p"]
    # Move Pipe mode: clicking a straight gives its grips (and doesn't branch)
    view = Gui.ActiveDocument.ActiveView
    from mechflow_gui.sketch3d import to_global
    a, b = p.ed.lines[0]
    x, y = view.getPointOnViewport(to_global(p.sketch, (p.ed.pts[a] + p.ed.pts[b]) * 0.5))
    p.set_move_mode(True)
    p.pipe_click((x, y))
    log("move mode: grips", [(g[0], g[1]) for g in p._grips], "pending", p.pending)
    assert any(g[0] == "box" for g in p._grips) and p.pending is None
    p.set_move_mode(False)
    assert not p._grips
    view = Gui.ActiveDocument.ActiveView
    # click part way along the first straight (on screen): it gets its grips
    # and the next click puts a branch there
    a, b = p.ed.lines[0]
    mid = (p.ed.pts[a] + p.ed.pts[b]) * 0.5
    from mechflow_gui.sketch3d import to_global
    x, y = view.getPointOnViewport(to_global(p.sketch, mid))
    hit = p.line_hit((x, y))
    log("line under the mouse", hit and (hit[0], tuple(round(v) for v in hit[1])))
    assert hit is not None and hit[0] == 0
    p.pipe_click((x, y))
    log("pending branch at", p.pending and tuple(round(v) for v in p.pending[1]))
    assert p.pending is not None and p.pending[0] == 0
    q = p.pending[1] + V(0, -900, 0)
    p.click(q)
    log("lines", len(p.ed.lines), "points", len(p.ed.pts))
    assert len(p.ed.lines) == 5
    parts, _e = __import__("mechflow_gui.pipe_draw", fromlist=["x"]).plan_for(
        p.settings(), p._segments(), [])
    tees = [q for q in parts if "TEE" in q["type"]]
    log("tees in the plan", len(tees))
    assert len(tees) == 1
    # a way round through the tank is spotted (and sorted last)
    from mechflow_gui import pipe_draw as pd
    body = S["doc"].getObject("Body")
    through = pd.clashes([V(-300, 300, 300), V(900, 300, 300)], [("Tank", body.Shape)], 50)
    past = pd.clashes([V(-300, 300, 900), V(900, 300, 900)], [("Tank", body.Shape)], 50)
    log("clash through the tank", through, "above it", past, "obstacles", [l for l, _s in p._obstacles()])
    assert through == ["Tank"] and past == []
    # Route to...: from the branch end to a point down and across
    p.start_auto()
    T = p.cur_local() + V(-1200, -600, -700)
    cands = p.auto_target(T)
    log("route to: ways round", len(cands), [len(c) - 2 for c in cands],
        "clashes", [p._clash.get(id(c)) for c in cands], "|", p.msg.text()[:110])
    assert len(cands) >= 3
    first = [V(x) for x in cands[0]]
    p.auto_next()
    assert p.auto["i"] == 1
    n0 = len(p.ed.lines)
    p.auto_accept()
    log("lines after route to", n0, "->", len(p.ed.lines), "end", tuple(round(v) for v in p.ed.pts[p.ed.current]))
    assert (p.ed.pts[p.ed.current] - T).Length < 1e-6 and len(p.ed.lines) > n0
    assert p.perr.isHidden(), p.perr.text()
at(branch, 1500)
at(lambda: shot("pipedraw_branch"), 800)


def ok():
    p = S["p"]
    p.sketch.Label = "Draw pipe test"
    p.accept()
    from mechflow_gui import routing
    rs = [o for o in S["doc"].Objects if routing.is_route(o)]
    assert len(rs) == 1, "a route"
    r = rs[0]; S["r"] = r
    kinds = {}
    for o in r.Parts:
        k = getattr(o, "StdType", type(getattr(o, "Proxy", None)).__name__)
        kinds[k] = kinds.get(k, 0) + 1
    log("route", r.Label, r.Standard, r.Size, "spec", getattr(r, "Spec", ""), "error", r.Error, kinds)
    assert not r.Error and any("TEE" in k for k in kinds) and r.Size == "DN80"
    assert S["doc"].getObject("MechFlowPipePreview") is None, "preview gone"
    S["nparts"] = len(r.Parts)
at(ok, 1500)
at(lambda: shot("pipedraw_route"), 800)


def carry_on():
    # a new Draw Pipe: click the first route's open end - it carries on drawing that route
    from mechflow_gui import pipe_draw, routing
    from mechflow_gui.sketch3d import Editor, to_global
    r = S["r"]
    sk = routing.route_sketch(r)
    ed = Editor(sk)
    ends = [i for i in range(len(ed.pts)) if ed.is_free_end(i)]
    p = pipe_draw.draw_pipe(); S["p2"] = p
    new_sketch = p.sketch.Name
    k = ed.lines_at(ends[0])[0]
    near = ed.pts[ends[0]] + (ed.pts[[x for x in ed.lines[k] if x != ends[0]][0]] - ed.pts[ends[0]]).normalize() * 60
    p.other_route_click(r, sk, k, near, ends[0])
    log("carry on: route", p.route and p.route.Label, "sketch", p.sketch.Name, "current", p.ed.current,
        "new sketch dropped", S["doc"].getObject(new_sketch) is None,
        "parts hidden", all(not o.ViewObject.Visibility for o in r.Parts))
    assert p.route is r and p.ed.current == ends[0]
    assert S["doc"].getObject(new_sketch) is None
    d = p.ed.pts[ends[0]] - p.ed.pts[[x for x in ed.lines[k] if x != ends[0]][0]]
    d.normalize()
    side = V(0, 0, 1) if abs(d.z) < 0.5 else V(1, 0, 0)
    p.click(p.ed.pts[ends[0]] + d * 600)
    p.click(p.ed.pts[p.ed.current] + side * 700)
    p.accept()
    log("parts", S["nparts"], "->", len(r.Parts), "error", r.Error, "visible", all(o.ViewObject.Visibility for o in r.Parts))
    assert len(r.Parts) > S["nparts"] and not r.Error
    assert all(o.ViewObject.Visibility for o in r.Parts)
at(carry_on, 1500)


def edit_selected():
    from mechflow_gui import pipe_draw
    r = S["r"]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(S["doc"].Name, r.Parts[0].Name)
    p = pipe_draw.draw_pipe()
    log("editing", p.route and p.route.Label, "spec box shown", p.spec.isVisibleTo(p.form),
        "label", p.route_l.text()[:80])
    assert p.route is r and not p.spec.isVisibleTo(p.form)
    assert preview() is not None and len(preview().Solids) > 5
    p.reject()
    assert all(o.ViewObject.Visibility for o in r.Parts)
    assert S["doc"].getObject("MechFlowPipePreview") is None
at(edit_selected, 1500)


def free_flanges(r):
    from mechflow_gui import routing
    faces = []
    for o in S["doc"].Objects:
        f = routing.flange_face(o)
        if f is not None:
            faces.append((o, f[0], f[1]))
    out = []
    for o, c, n in faces:
        if o in r.Parts and not any(x is not o and (c2 - c).Length < 5 for x, c2, _n in faces):
            out.append((o, c, n))
    return out


def screen_on_face(fl):
    """A screen point on a flange's raised face (not its bore)."""
    from mechflow_gui import routing, stdparts
    c, n = routing.flange_face(fl)
    info = stdparts.flange_info(fl.StdType, fl.Size, fl.Rating)
    u = n.cross(V(0, 0, 1)) if abs(n.z) < 0.9 else n.cross(V(1, 0, 0))
    u.normalize()
    return Gui.ActiveDocument.ActiveView.getPointOnViewport(c + u * (info["face"] / 2 - 4))


def flange_to_flange():
    from mechflow_gui import pipe_draw, routing
    r = S["r"]
    ff = free_flanges(r)
    log("free flanges on", r.Label, [(o.Name, tuple(round(v) for v in c)) for o, c, _n in ff])
    assert len(ff) >= 2
    (fa, ca, na), (fb, cb, nb) = ff[0], ff[1]
    Gui.Selection.clearSelection()
    p = pipe_draw.draw_pipe(); S["p3"] = p
    view = Gui.ActiveDocument.ActiveView
    view.viewIsometric(); view.fitAll()
    Gui.updateGui()
    hit = None
    for fl in (fa,):
        x, y = screen_on_face(fl)
        for dx in (0, 2, -2, 4, -4):
            c = p._candidate((x + dx, y + dx))
            if c is not None and (c[0] - ca).Length < 0.5:
                hit = c; break
    log("start on", fa.Label, "->", hit and tuple(round(v, 1) for v in hit[0]), "anchor", hit and hit[1])
    assert hit is not None and hit[1] is None, "snaps to the face; no link to a route's part"
    p.click(*hit)
    assert p.mates and (p.mates[0] - ca).Length < 0.5
    # the other flange: Route to it
    p.flanges[(round(cb.x, 1), round(cb.y, 1), round(cb.z, 1))] = (cb, nb, fb)
    p.start_auto()
    cands = p.auto_target(cb)
    log("flange to flange: ways round", len(cands), [len(c) - 2 for c in cands])
    assert cands
    for pts in cands:
        d0 = pts[1] - pts[0]; d1 = pts[-1] - pts[-2]
        d0.normalize(); d1.normalize()
        assert d0.dot(na) > 1 - 1e-6 and d1.dot(nb) < -1 + 1e-6, "square off both faces"
    p.auto_accept()
    log("mates", len(p.mates), "error", p.perr.isHidden() or p.perr.text())
    assert len(p.mates) == 2 and p.ed.current is None and p.perr.isHidden()
    p.accept()
    r2 = [o for o in S["doc"].Objects if routing.is_route(o) and o is not r][-1]
    kinds = {}
    for o in r2.Parts:
        k = getattr(o, "StdType", type(getattr(o, "Proxy", None)).__name__)
        kinds[k] = kinds.get(k, 0) + 1
    log("flange-to-flange route", r2.Label, "error", r2.Error, kinds)
    assert not r2.Error and kinds.get("EN1514-1-IBC") == 2 and kinds.get("FSScrewObject", 0) >= 8
    # our flanges meet theirs across a 2 mm gasket, face to face
    mine = [routing.flange_face(o) for o in r2.Parts if routing.flange_face(o) is not None]
    for c, n in ((ca, na), (cb, nb)):
        m = min(mine, key=lambda f: (f[0] - c).Length)
        log("  face gap", round((m[0] - c).Length, 2), "normals", round(m[1].dot(n), 3))
        assert abs((m[0] - c).Length - 2.0) < 0.01 and m[1].dot(n) < -0.999
    S["r2"] = r2
at(flange_to_flange, 1500)
at(lambda: shot("pipedraw_flanges"), 800)


def flange_to_pipe():
    # from the second nozzle's flange to the first route's pipe: a tee goes
    # in and the new pipe becomes part of that route
    from mechflow_gui import pipe_draw, routing, sketch3d
    r = S["r"]
    sk = routing.route_sketch(r)
    ed = sketch3d.Editor(sk)
    k = None
    for i, (a, b) in enumerate(ed.lines):
        A, B = ed.pts[a], ed.pts[b]
        d = B - A
        if abs(d.y) < 1e-6 and abs(d.z) < 1e-6 and abs(A.y - 300) < 1e-6 and abs(A.z - 300) < 1e-6 \
                and d.Length >= 400:
            k, P = i, (A + B) * 0.5
            break
    assert k is not None, "a straight along X on the nozzle's line"
    P = V(round(P.x / 10) * 10, P.y, P.z)
    tees0 = sum(1 for o in r.Parts if "TEE" in getattr(o, "StdType", ""))
    p = pipe_draw.draw_pipe(); S["p4"] = p
    c2, n2 = routing.flange_face(S["fl2"])
    # clicking the nozzle's pipe (not the flange) still finds its flange
    view = Gui.ActiveDocument.ActiveView
    sx, sy = view.getPointOnViewport(V(300, -60, 300 + 44.0))
    near = None
    for dx in (0, 1, -1, 2, -2):
        h = p._candidate((sx + dx, sy + dx))
        if h is not None and (h[0] - c2).Length < 0.5:
            near = h; break
    log("click on nozzle 2's pipe ->", near and tuple(round(v, 1) for v in near[0]))
    assert near is not None, "a nozzle's pipe snaps to its flange face"
    x, y = screen_on_face(S["fl2"])
    hit = None
    for dx in (0, 2, -2, 4, -4):
        c = p._candidate((x + dx, y + dx))
        if c is not None and (c[0] - c2).Length < 0.5:
            hit = c; break
    log("start on nozzle 2 ->", hit and (tuple(round(v, 1) for v in hit[0]), hit[1] and hit[1][1]))
    assert hit is not None and hit[1] is not None, "a nozzle's flange is followed (anchored)"
    p.click(*hit)
    p.start_auto()
    cands = p.auto_target(P, None, None, None, (r, sk, k))
    log("to the pipe: ways round", len(cands))
    assert cands
    for pts in cands:
        dl = pts[-1] - pts[-2]
        assert abs(dl.x) < 1e-6, "meets the pipe square on"
    p.auto_accept()
    log("joined", p.merged and p.merged.Label, "route", p.route and p.route.Label, "|", p.sel_box.text()[:90])
    assert p.route is r and p.merged is r
    p.accept()
    tees = sum(1 for o in r.Parts if "TEE" in getattr(o, "StdType", ""))
    bolts_near = [o for o in r.Parts if getattr(o, "StdType", "") == "EN1514-1-IBC"]
    log("tees", tees0, "->", tees, "gaskets", len(bolts_near), "error", r.Error)
    assert tees == tees0 + 1 and not r.Error
    m = [routing.flange_face(o) for o in r.Parts if routing.flange_face(o) is not None]
    near = min(m, key=lambda f: (f[0] - c2).Length)
    log("  nozzle 2 face gap", round((near[0] - c2).Length, 2))
    assert abs((near[0] - c2).Length - 2.0) < 0.01
at(flange_to_pipe, 1500)
at(lambda: shot("pipedraw_tee_join"), 800)


def nested_flange():
    # a flange inside an assembly (turned and moved): the pick finds the
    # flange itself, and the pipe bolts to it
    from mechflow_gui import pipe_draw, routing, stdparts
    doc = S["doc"]
    asm = doc.addObject("App::Part", "Asm")
    asm.Placement = App.Placement(V(-2000, 1500, 0), App.Rotation(V(0, 0, 1), 90))
    fl = stdparts.make(asm, "EN1092-1-11", "DN80", "PN16", 1000.0)
    fl.Placement = App.Placement(V(0, 0, 600), App.Rotation(V(0, 1, 0), 90))
    doc.recompute()
    c, n = routing.flange_face(fl)
    log("nested flange face", tuple(round(v, 1) for v in c), "out", tuple(round(v, 3) for v in n))
    p = pipe_draw.draw_pipe(); S["p5"] = p
    view = Gui.ActiveDocument.ActiveView
    view.viewIsometric(); view.fitAll(); Gui.updateGui()
    x, y = screen_on_face(fl)
    hit = None
    for dx in (0, 2, -2, 4, -4):
        h = p._candidate((x + dx, y + dx))
        if h is not None and (h[0] - c).Length < 0.5:
            hit = h; break
    log("pick through the assembly ->", hit and (tuple(round(v, 1) for v in hit[0]), hit[1] and hit[1][1]))
    assert hit is not None, "finds the flange inside the assembly"
    p.click(*hit)
    p.start_auto()
    cands = p.auto_target(c + n * 1500 + V(0, 0, 800))
    assert cands
    p.auto_accept()
    p.accept()
    r = [o for o in doc.Objects if routing.is_route(o)][-1]
    bolts = [o for o in r.Parts if type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject"]
    mine = [routing.flange_face(o) for o in r.Parts if routing.flange_face(o) is not None]
    m = min(mine, key=lambda f: (f[0] - c).Length)
    log("route", r.Label, "error", r.Error, "bolts+nuts", len(bolts), "face gap", round((m[0] - c).Length, 2))
    assert not r.Error and len(bolts) == 16 and abs((m[0] - c).Length - 2.0) < 0.01
at(nested_flange, 1500)
at(lambda: shot("pipedraw_nested"), 800)


def reopen():
    d = S["doc"]; d.saveAs(OUT + "pipedraw_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "pipedraw_t.FCStd"); d.recompute()
    from mechflow_gui import routing
    r = [o for o in d.Objects if routing.is_route(o)][0]
    log("reopened", r.Label, len(r.Parts), "parts")
    assert r.Parts
at(reopen, 1000)
run()
