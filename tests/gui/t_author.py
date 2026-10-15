import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Author Component: a valve-like part, turned and moved anyhow in its own
# file, and a sensor, made into routing library parts by clicking their
# port edges; then placed on a route like the built-in ones. An equal tee
# authored on its three ends (in any order) sits in the line on its run with
# the branch turning round the pipe; two ends that aren't in line are
# refused; a branch route drawn from the tee's branch end has a plain end
# there. Editing the route's 3D sketch from a selected pipe.
from h import *
import Part, math, shutil
V = App.Vector
S = {}
LIB = OUT + "routing-library/"
shutil.rmtree(LIB, ignore_errors=True)
os.environ["MF_ROUTING_LIBRARY"] = LIB


def author():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    from mechflow_gui import inline
    d = App.newDocument("Strainer")
    shape, L, _e = inline.valve_shape("Check valve", "EN", "DN80", "PN16")
    o = d.addObject("Part::Feature", "Strainer")
    o.Shape = shape
    o.Placement = App.Placement(V(150, -40, 75), App.Rotation(V(1, 1, 0), 37))
    d.recompute()
    from mechflow_gui import stdparts
    od = stdparts.flange_info("EN1092-1-11", "DN80", "PN16")["OD"]
    ax = o.Placement.Rotation.multVec(V(0, 0, 1))
    ends = {}
    for i, e in enumerate(o.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(2 * c.Radius - od) < 1e-3:
            k = (c.Center - o.Placement.Base).dot(ax)
            key = "B" if k > 0 else "A"
            if key not in ends or abs(k) > abs(ends[key][1]):
                ends[key] = (f"Edge{i+1}", k)
    log("port edges", ends)
    p = inline.author_component(); S["ap"] = p
    assert p.add_port(o, ends["A"][0]) and p.add_port(o, ends["B"][0])
    p.name.setText("Y-strainer DN80 PN16")
    p.cat.setCurrentText("Fitting")
    log("panel says", p.msg.text()[-40:], [p.list.item(i).text() for i in range(p.list.count())])
    p.accept()
    # an instrument: a level switch standing on its mounting edge, turned
    s2 = App.newDocument("LevelSwitch")
    body = Part.makeCylinder(15, 40).fuse(Part.makeCylinder(30, 60, V(0, 0, 40)))
    sw = s2.addObject("Part::Feature", "Switch"); sw.Shape = body
    sw.Placement = App.Placement(V(10, 20, 30), App.Rotation(V(0, 1, 0), 90))
    s2.recompute()
    bottom = [f"Edge{i+1}" for i, e in enumerate(sw.Shape.Edges)
              if type(getattr(e, "Curve", None)).__name__ == "Circle" and abs(e.Curve.Radius - 15) < 1e-6
              and (e.Curve.Center - sw.Placement.Base).Length < 1e-6][0]
    p = inline.author_component()
    assert p.add_port(sw, bottom)
    p.name.setText("Level switch")
    p.cat.setCurrentText("Instrument")
    p.accept()
    items = inline.library_items()
    log("library", [(n, i["category"], round(i["ftf"], 1), len(i["ports"])) for n, _p, i in items])
    assert len(items) == 2
    S["lib"] = {n: p_ for n, p_, _i in items}
at(author, 1500)


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Plant"); S["doc"] = doc
    b = new_body(doc, "Body")
    box = b.newObject("PartDesign::AdditiveBox", "Box"); box.Length = 600; box.Width = 600; box.Height = 600
    inner = b.newObject("PartDesign::SubtractiveBox", "Inside"); inner.Length = 584; inner.Width = 584; inner.Height = 584
    inner.Placement = App.Placement(V(8, 8, 8), App.Rotation())
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
    log("flange face", face)
    Gui.SendMsgToActiveView("ViewFit")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    from mechflow_gui import sketch3d, routing
    sk = sketch3d.make(None, "Steam line")
    ed = sketch3d.Editor(sk)
    ed.start(face, (fl, best[0]))
    ed.line_along(V(1, 0, 0), 1400)
    ed.line_along(V(0, 0, 1), 1200)
    ed.line_along(V(0, 1, 0), 1000)
    ed.save()
    routing.install()
    r = routing.make_route(None, [(sk, None)], "EN", "DN80", "", "3D", "Blind flange", "PN16",
                           [(fl, best[0])])
    S["r"], S["sk"] = r, sk
    log("route parts", len(r.Parts), "error", r.Error)
    from mechflow_gui import sketch3d, routing
    sk = sketch3d.make(None, "Line")
    ed = sketch3d.Editor(sk)
    ed.start(face, (fl, best[0]))
    ed.line_along(V(1, 0, 0), 1400)
    ed.line_along(V(0, 0, 1), 1200)
    ed.save()
    routing.install()
    r = routing.make_route(None, [(sk, None)], "EN", "DN80", "", "3D", "Blind flange", "PN16",
                           [(fl, best[0])])
    S["r"] = r
at(setup, 1500)


def place():
    from mechflow_gui import inline
    p = inline.valves_and_instruments(); S["p"] = p
    names = [p.list.item(i).text() for i in range(p.list.count())]
    log("list ends with", names[-2:])
    face = S["face"]
    st = p.place_at(S["r"], face + V(700, 0, 0), library=S["lib"]["Y-strainer DN80 PN16"])
    lv = p.place_at(S["r"], face + V(1400, 0, 700), library=S["lib"]["Level switch"])
    assert not p.error.isVisible(), p.error.text()
    log("placed", st.Label, st.Kind, round(float(st.FaceToFace), 1), st.EndType, "|", lv.Label, lv.EndType)
    pipes = sorted(round(float(o.Length)) for o in S["r"].Parts if getattr(o, "StdType", "").endswith("PIPE"))
    kinds = {}
    for o in S["r"].Parts:
        k = getattr(o, "StdType", type(getattr(o, "Proxy", None)).__name__)
        kinds[k] = kinds.get(k, 0) + 1
    log("pipes", pipes, "parts", kinds)
    assert len(pipes) == 3
    nuts = [o for o in S["r"].Parts if "4032" in o.Label]
    gaskets = [o for o in S["r"].Parts if getattr(o, "StdType", "").startswith("EN1514")]
    log("nuts", len(nuts), "gaskets", len(gaskets), "(nozzle, both strainer ends, blind end)")
    assert len(nuts) == 32 and len(gaskets) == 4
    over = []
    for o in S["r"].Parts:
        if getattr(o, "StdType", "").startswith(("EN10220", "EN1092", "EN1514")):
            v = o.Shape.common(st.Shape).Volume
            if v > 1:
                over.append((o.Label, round(v)))
    log("overlaps", over)
    assert not over
    up = lv.Placement.Rotation.multVec(V(0, 0, 1))
    log("level switch stands out along", tuple(round(x, 3) for x in up), "base",
        tuple(round(x) for x in lv.Placement.Base))
    p.accept()
    Gui.SendMsgToActiveView("ViewFit")
at(place, 1000)
at(lambda: shot("authored"), 800)


def author_tee():
    """An 88.9 x 3.2 equal tee (butt weld), modelled turned anyhow."""
    from mechflow_gui import inline
    d = App.newDocument("Tee")
    R, r = 44.45, 41.25
    run_ = Part.makeCylinder(R, 2 * 76, V(-76, 0, 0), V(1, 0, 0))
    br = Part.makeCylinder(R, 76, V(0, 0, 0), V(0, 1, 0))
    body = run_.fuse(br).cut(Part.makeCylinder(r, 2 * 76, V(-76, 0, 0), V(1, 0, 0))) \
        .cut(Part.makeCylinder(r, 76, V(0, 0, 0), V(0, 1, 0))).removeSplitter()
    o = d.addObject("Part::Feature", "EqualTee")
    o.Shape = body
    o.Placement = App.Placement(V(30, 60, 90), App.Rotation(V(1, 2, 3), 50))
    d.recompute()
    rot = o.Placement.Rotation
    ends = {}
    for i, e in enumerate(o.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ != "Circle" or abs(c.Radius - R) > 1e-6:
            continue
        loc = o.Placement.inverse().multVec(c.Center)
        for key, want in (("A", V(-76, 0, 0)), ("B", V(76, 0, 0)), ("C", V(0, 76, 0))):
            if (loc - want).Length < 1e-6:
                ends[key] = f"Edge{i+1}"
    log("tee ends", ends)
    # two ends that aren't in line (a run end and the branch): refused
    p = inline.author_component()
    assert p.add_port(o, ends["A"]) and p.add_port(o, ends["C"])
    log("run end + branch only:", p.msg.text().rsplit("<br><br>", 1)[-1])
    assert not p.accept() and not p.error.isHidden()
    log("  refused:", p.error.text()[:90])
    # all three, branch picked first
    p._clear()
    assert p.add_port(o, ends["C"]) and p.add_port(o, ends["A"]) and p.add_port(o, ends["B"])
    log("three ends:", p.msg.text().rsplit("<br><br>", 1)[-1])
    p.name.setText("Equal tee DN80")
    p.cat.setCurrentText("Fitting")
    p.end.setCurrentIndex(1)                  # butt weld
    assert p.accept()
    info = [i for n, _p, i in inline.library_items() if n == "Equal tee DN80"][0]
    log("tee ports", [(q["name"], [round(x, 1) for x in q["point"]], [round(x, 2) for x in q["dir"]],
                       q.get("angle")) for q in info["ports"]], "ftf", round(info["ftf"], 1))
    assert len(info["ports"]) == 3 and abs(info["ftf"] - 152) < 0.01
    c = info["ports"][2]
    assert abs(c["point"][1] - 76) < 0.01 and abs(c["dir"][1] - 1) < 1e-6 and abs(c["angle"] - 90) < 0.01
    S["tee_lib"] = [p_ for n, p_, _i in inline.library_items() if n == "Equal tee DN80"][0]
at(author_tee, 1000)


def place_tee():
    from mechflow_gui import inline, routing
    App.setActiveDocument(S["doc"].Name)
    p = inline.valves_and_instruments()
    face = S["face"]
    tee = p.place_at(S["r"], face + V(350, 0, 0), library=S["tee_lib"])
    assert not p.error.isVisible(), p.error.text()
    S["doc"].recompute()
    rot = tee.Placement.Rotation
    run_dir = rot.multVec(V(0, 0, 1))
    branch = rot.multVec(V(0, 1, 0))
    log("tee on the line: run along", tuple(round(x, 3) for x in run_dir), "branch",
        tuple(round(x, 3) for x in branch), "|", p.msg.text()[-120:])
    assert abs(abs(run_dir.x) - 1) < 1e-6 and abs(branch.z - 1) < 1e-6
    tee.Angle = 90
    routing.build(S["r"])
    S["doc"].recompute()
    b2 = tee.Placement.Rotation.multVec(V(0, 1, 0))
    log("turned 90: branch", tuple(round(x, 3) for x in b2))
    assert abs(b2.z) < 1e-6 and abs(abs(b2.y) - 1) < 1e-6
    tee.Angle = 0
    routing.build(S["r"])
    S["doc"].recompute()
    over = [o.Label for o in S["r"].Parts if getattr(o, "StdType", "").endswith("PIPE")
            and o.Shape.common(tee.Shape).Volume > 1]
    log("pipes overlapping the tee", over)
    assert not over
    p.accept()
    S["tee"] = tee
at(place_tee, 1500)


def branch_route():
    """A branch pipe from the tee's branch end: its own route; that end is plain."""
    from mechflow_gui import sketch3d, routing
    tee = S["tee"]
    edge = None
    top = tee.Placement.multVec(V(0, 76, 0))
    for i, e in enumerate(tee.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and (c.Center - top).Length < 1e-3 and c.Radius > 43:
            edge = f"Edge{i+1}"
    sk = sketch3d.make(None, "Branch")
    ed = sketch3d.Editor(sk)
    ed.start(top, (tee, edge))
    ed.line_along(V(0, 0, 1), 500)
    ed.save()
    S["doc"].recompute()
    r2 = routing.make_route(None, [(sk, None)], "EN", "DN80", "", "3D", "Weld neck flange", "PN16")
    S["doc"].recompute()
    ends = routing.component_port_ends(r2)
    near = [o.Label for o in r2.Parts if (o.Shape.BoundBox.Center - top).Length < 60
            and "1092" in getattr(o, "StdType", "")]
    pipes = [round(float(o.Length)) for o in r2.Parts if getattr(o, "StdType", "").endswith("PIPE")]
    log("branch route:", r2.Error or "ok", "| ends from the tee", ends, "| flanges at the tee",
        near, "| pipes", pipes)
    assert not r2.Error and list(ends.values()) == ["Plain"] and not near
    S["r2"] = r2
at(branch_route, 1500)


def edit_route_sketch():
    from mechflow_gui import sketch3d
    pipe = [o for o in S["r"].Parts if getattr(o, "StdType", "").endswith("PIPE")][0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(pipe)
    p = sketch3d.sketch_3d()
    faded = [(o.ViewObject.Transparency, o.ViewObject.Selectable) for o in S["r"].Parts[:3]]
    log("3D Sketch with a pipe selected edits", p.sketch.Label, "| route parts while editing",
        faded, "| sketch shown", p.sketch.ViewObject.Visibility)
    assert p.sketch is S["r"].PathSketches[0] and faded[0] == (80, False)
    p.reject()
    back = [(o.ViewObject.Transparency, o.ViewObject.Selectable) for o in S["r"].Parts[:3]]
    log("after Cancel", back)
    assert back[0][1] is True and back[0][0] != 80
at(edit_route_sketch, 800)
run()
