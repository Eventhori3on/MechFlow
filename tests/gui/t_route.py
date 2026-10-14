import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Route Pipe: a 3D route with a branch, starting on a nozzle flange, blinds
# on the free ends; rebuilds when the sketch changes.
from h import *
import Part
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Plant"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    box = b.newObject("PartDesign::AdditiveBox", "Box"); box.Length = 600; box.Width = 600; box.Height = 600
    inner = b.newObject("PartDesign::SubtractiveBox", "Inside"); inner.Length = 584; inner.Width = 584; inner.Height = 584
    inner.Placement = App.Placement(V(8, 8, 8), App.Rotation())
    doc.recompute()
    from mechflow_gui import nozzle, stdparts
    nz = nozzle.make(b, V(600, 300, 300), V(1, 0, 0), "EN 10220", "DN80", "", 150)
    fl = nozzle.add_flange(nz, "EN1092-1-11", "PN16")[0]
    doc.recompute()
    face, n = stdparts._face_frame(fl)
    S["face"] = face
    log("flange face", face, n)
    f = stdparts.flange_info(fl.StdType, fl.Size, fl.Rating)
    best = None
    for i, e in enumerate(fl.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(2 * c.Radius - f["face"]) < 1e-3:
            d = (c.Center - face).Length
            if best is None or d < best[1]:
                best = (f"Edge{i+1}", d)
    S["fl"], S["fl_edge"] = fl, best[0]
    fx, fz = face.x, face.z
    # sketch 1 (vertical plane y = 300): out 600, up 400, with a branch down at 300
    sk1 = doc.addObject("Sketcher::SketchObject", "RouteA")
    sk1.Placement = App.Placement(V(0, 300, 0), App.Rotation(V(1, 0, 0), 90))
    sk1.addGeometry(Part.LineSegment(V(fx, fz, 0), V(fx + 300, fz, 0)))
    sk1.addGeometry(Part.LineSegment(V(fx + 300, fz, 0), V(fx + 600, fz, 0)))
    sk1.addGeometry(Part.LineSegment(V(fx + 600, fz, 0), V(fx + 600, fz + 400, 0)))
    sk1.addGeometry(Part.LineSegment(V(fx + 300, fz, 0), V(fx + 300, fz - 250, 0)))
    # sketch 2 (horizontal at the top): along +Y 350
    sk2 = doc.addObject("Sketcher::SketchObject", "RouteB")
    sk2.Placement = App.Placement(V(0, 0, fz + 400), App.Rotation())
    sk2.addGeometry(Part.LineSegment(V(fx + 600, 300, 0), V(fx + 600, 650, 0)))
    doc.recompute()
    S["sk1"], S["sk2"] = sk1, sk2
    log("sketch ends", [(round(v.Point.x), round(v.Point.y), round(v.Point.z)) for v in sk1.Shape.Vertexes][:3])
at(setup, 1500)


def route():
    from mechflow_gui import routing
    routing.install()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection("Plant", "RouteA")
    Gui.Selection.addSelection("Plant", "RouteB")
    Gui.Selection.addSelection("Plant", S["fl"].Name, S["fl_edge"])
    p = routing.route_pipe(); S["p"] = p
    log("first build:", p.msg.text(), "| err", p.error.isVisible() and p.error.text())
    p.ends.setCurrentText("Blind flange")
    log("panel", p.msg.text(), "| err", p.error.isVisible() and p.error.text())
    assert not p.error.isVisible(), p.error.text()
at(route, 1000)


def check():
    p = S["p"]; r = p.route
    parts = list(r.Parts)
    kinds = {}
    for o in parts:
        kinds[o.StdType if hasattr(o, "StdType") else type(o.Proxy).__name__] = kinds.get(
            o.StdType if hasattr(o, "StdType") else type(o.Proxy).__name__, 0) + 1
    log("route parts", kinds)
    for o in parts:
        if hasattr(o, "StdType") and "1092" in o.StdType:
            log("   ", o.Label, [round(x) for x in o.Shape.BoundBox.Center], "base", o.BaseObject[0].Label if o.BaseObject else None)
    pipes = sorted(round(float(o.Length), 1) for o in parts if getattr(o, "StdType", "") == "EN10220-PIPE")
    log("pipe lengths", pipes)
    assert kinds.get("EN10253-90-3D") == 2 and kinds.get("EN10253-TEE") == 1, kinds
    assert len(pipes) == 5, pipes
    assert kinds.get("EN1092-1-05") == 2, "blinds on both free ends"
    # every pipe end meets another part's circle of the pipe OD
    import itertools
    circles = []
    for o in parts:
        for e in o.Shape.Edges:
            c = getattr(e, "Curve", None)
            if type(c).__name__ == "Circle" and abs(c.Radius - 44.45) < 1e-3:
                circles.append((o, c.Center))
    gaps = []
    for o in parts:
        if getattr(o, "StdType", "") != "EN10220-PIPE":
            continue
        z = o.Placement.Rotation.multVec(V(0, 0, 1))
        for end in (o.Placement.Base, o.Placement.Base + z * float(o.Length)):
            if not any((c - end).Length < 0.05 for x, c in circles if x is not o):
                gaps.append((o.Label, end))
    log("gaps", gaps)
    assert not gaps, gaps
    over = []
    solids = [o for o in parts if hasattr(o, "StdType")]
    for a, b in itertools.combinations(solids, 2):
        if a.Shape.BoundBox.intersect(b.Shape.BoundBox):
            v = a.Shape.common(b.Shape).Volume
            if v > 1.0 and not ("ISO" in a.Label or "ISO" in b.Label):
                over.append((a.Label, b.Label, round(v)))
    log("overlaps", over)
    assert not over, over
    inparts = {x.Name for x in r.Parts}
    log("not in route.Parts:", [(o.Name, o.Label, getattr(o, "MechFlowRoute", None)) for o in S["doc"].Objects
                                if hasattr(o, "StdType") and o.Name not in inparts])
    labels = [o.Label for o in S["doc"].Objects if hasattr(o, "StdType")]
    dup = [l for l in labels if l[-3:].isdigit() and ">" in l]
    log("labels with FreeCAD numbering", dup, [(o.Label, o.MechFlowInstance) for o in S["doc"].Objects if hasattr(o, "StdType") and "1092-1/11" in o.Label])
    assert not dup, dup
    p.accept()
    S["r"] = r
    S["before"] = pipes
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(check, 1500)
at(lambda: shot("route"), 800)


def edit_sketch():
    # lengthen the branch: the route rebuilds by itself
    sk1 = S["sk1"]
    g = sk1.Geometry
    a, b = g[3].StartPoint, g[3].EndPoint
    g[3] = Part.LineSegment(a, b + V(0, -150, 0))
    sk1.Geometry = g
    S["doc"].recompute()
at(edit_sketch, 30000)       # the rebuild runs by itself; a slow machine needs the time


def after_edit():
    import time
    r = S["r"]
    from mechflow_gui import routing
    log("rebuild busy", routing._obs.busy)
    pipes = sorted(round(float(o.Length), 1) for o in r.Parts if getattr(o, "StdType", "") == "EN10220-PIPE")
    log("after edit", pipes, "error", r.Error)
    from mechflow_gui import routing
    log("  path", [(o.Label, s_) for o, s_ in r.Path], "starts", [(o.Label, s_) for o, s_ in r.StartFlanges])
    log("  segs", [(routing._fmt(a), routing._fmt(b)) for a, b in routing.path_segments(routing.path_links(r))])
    assert pipes != S["before"] and len(pipes) == 5, "route didn't rebuild"
    from mechflow_gui import bom
    S["doc"].recompute()
at(after_edit, 2000)


def reopen():
    d = S["doc"]; d.saveAs(OUT + "route_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "route_t.FCStd"); d.recompute()
    from mechflow_gui import routing
    rs = [o for o in d.Objects if routing.is_route(o)]
    log("reopened routes", [(o.Label, len(o.Parts)) for o in rs], "invalid", [o.Label for o in d.Objects if not o.isValid()])
    assert rs and len(rs[0].Parts) > 10
at(reopen, 800)
run()
