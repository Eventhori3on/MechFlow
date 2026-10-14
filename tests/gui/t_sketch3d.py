import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# 3D Sketch: start on a nozzle flange, lines along X / Z / Y by clicking in
# the view and by typing, edit a length (later lines follow), a branch,
# rename; Route Pipe follows it and bolts on to the flange; editing the
# sketch rebuilds the route; save and reopen.
from h import *
import Part
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Plant3D"); S["doc"] = doc
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
at(setup, 1500)


def draw():
    from mechflow_gui import sketch3d
    p = sketch3d.sketch_3d(); S["p"] = p
    log("panel open", type(p).__name__, "sketch", p.sketch.Label)
    # start: hover the flange's face edge - the pick snaps to its centre
    view = Gui.ActiveDocument.ActiveView
    edge = S["fl"].Shape.getElement(S["fl_edge"])
    on_edge = edge.valueAt(edge.FirstParameter)
    x, y = view.getPointOnViewport(on_edge)
    cand = None
    for dx in (0, 1, -1, 2, -2):
        for dy in (0, 1, -1, 2, -2):
            c = p._candidate((x + dx, y + dy))
            if c is not None and c[1] is not None:
                cand = c; break
        if cand: break
    log("hover flange edge ->", cand and (tuple(round(v, 1) for v in cand[0]), cand[1][1] if cand[1] else None))
    assert cand is not None and (cand[0] - S["face"]).Length < 0.5, "snaps to the flange face centre"
    p.click(*cand)
    view.viewTop()
at(draw, 1500)


def draw2():
    p = S["p"]
    view = Gui.ActiveDocument.ActiveView
    log("view direction", view.getViewDirection())
    # next point by mouse: somewhere out along +X (top view: XY plane), rough
    target = S["face"] + V(397, 23, 0)
    x, y = view.getPointOnViewport(target)
    c = p._candidate((x, y))
    log("mouse at", tuple(round(v) for v in target), "->", tuple(round(v, 1) for v in c[0]),
        "plane", p._plane_name())
    assert abs(c[0].y - S["face"].y) < 1e-6 and abs(c[0].z - S["face"].z) < 1e-6, "snapped along X"
    assert abs((c[0] - S["face"]).Length - 400) < 1e-6, "rounded to 10 mm"
    p.click(*c)
    # then by typing: up 600, along +Y 500
    p.dir.setCurrentText("+Z"); p.len.setValue(600); p._add_typed()
    p.dir.setCurrentText("+Y"); p.len.setValue(500); p._add_typed()
    rows = [p.ed.line_info(k)[2:] for k in range(len(p.ed.lines))]
    log("lines", [(round(L), d) for L, d in rows])
    assert [d for _L, d in rows] == ["+X", "+Z", "+Y"]
    # edit the up line to 800: the last line moves up with it
    end_before = V(p.ed.pts[3])
    p._len_edited(1, 800.0)
    log("after length edit", [round(p.ed.line_info(k)[2]) for k in range(3)], "end moved by",
        tuple(round(v) for v in (p.ed.pts[3] - end_before)))
    assert (p.ed.pts[3] - end_before - V(0, 0, 200)).Length < 1e-6
    # typing a length and pressing Enter applies it and keeps the panel open
    from PySide6 import QtGui, QtCore as QC
    spin = p.table.cellWidget(0, 2)
    spin.lineEdit().setText("450")
    QtWidgets.QApplication.sendEvent(spin, QtGui.QKeyEvent(QC.QEvent.KeyPress, QC.Qt.Key_Return, QC.Qt.NoModifier))
    QtWidgets.QApplication.processEvents()
    log("Enter in a length box: panel open", Gui.Control.activeDialog(), "line 1",
        round(p.ed.line_info(0)[2]))
    assert Gui.Control.activeDialog() and abs(p.ed.line_info(0)[2] - 450) < 1e-6
    p._len_edited(0, 400.0)
    # branch from the corner at the top of the riser: -Y 300
    p._stop()
    p.click(p.ed.pts[1], None, 1)           # click the corner point of the sketch
    p.dir.setCurrentText("-Z"); p.len.setValue(250); p._add_typed()
    log("lines now", len(p.ed.lines), "points", len(p.ed.pts))
    assert len(p.ed.lines) == 4
    p.sketch.Label = "Cooling water line"
    p.accept()
    sk = [o for o in S["doc"].Objects if type(getattr(o, "Proxy", None)).__name__ == "Sketch3D"][0]
    S["sk"] = sk
    log("sketch", sk.Label, "edges", len(sk.Shape.Edges), "anchors", [(o.Label, s) for o, s in sk.Anchors])
    assert len(sk.Shape.Edges) == 4 and sk.Anchors
    Gui.ActiveDocument.ActiveView.viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(draw2, 1500)
at(lambda: shot("sketch3d"), 600)


def route():
    from mechflow_gui import routing
    routing.install()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(S["doc"].Name, S["sk"].Name)
    p = routing.route_pipe(); S["rp"] = p
    log("route panel:", p.msg.text()[:120], "| starts", p.starts, "| error", p.error.isVisible() and p.error.text())
    assert p.route is not None and p.route.Parts, "route built"
    assert p.starts, "starts on the flange it was drawn from"
    p.accept()
    r = p.route; S["r"] = r
    kinds = {}
    for o in r.Parts:
        k = getattr(o, "StdType", type(getattr(o, "Proxy", None)).__name__)
        kinds[k] = kinds.get(k, 0) + 1
    pipes = sorted(round(float(o.Length)) for o in r.Parts if getattr(o, "StdType", "").endswith("PIPE"))
    log("route parts", kinds, "pipes", pipes)
    assert kinds.get("EN10253-TEE") == 1 and kinds.get("EN10253-90-3D") == 1, "a tee and an elbow"
    assert len(pipes) == 4
    S["pipes"] = pipes
at(route, 1500)
at(lambda: shot("sketch3d_route"), 800)


def edit():
    from mechflow_gui import sketch3d
    ed = sketch3d.Editor(S["sk"])
    k = [i for i in range(len(ed.lines)) if ed.line_info(i)[3] == "+Y"][0]
    ed.set_length(k, 700.0)
    ed.save()
    S["doc"].recompute()
at(edit, 500)


def after_edit():
    from mechflow_gui import routing
    # the rebuild runs between events (and lets events run): wait it out
    if routing._obs.busy and S.get("tries", 0) < 120:
        S["tries"] = S.get("tries", 0) + 1
        i = [k for k, (f, w) in enumerate(Q) if f is after_edit][-1]
        Q.insert(i + 1, (after_edit, 1000))
        return
    pipes = sorted(round(float(o.Length)) for o in S["r"].Parts if getattr(o, "StdType", "").endswith("PIPE"))
    from mechflow_gui import routing
    log("pipes after editing the sketch", pipes, "before", S["pipes"], "error", S["r"].Error,
        "waited", S.get("tries", 0), "s")
    assert pipes != S["pipes"] and len(pipes) == 4, "route rebuilt"
at(after_edit, 3000)


def reopen():
    d = S["doc"]; d.saveAs(OUT + "sketch3d_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "sketch3d_t.FCStd"); d.recompute()
    sk = [o for o in d.Objects if o.Label == "Cooling water line"][0]
    log("reopened", sk.Label, type(sk.Proxy).__name__, "edges", len(sk.Shape.Edges), "valid", sk.isValid())
    assert len(sk.Shape.Edges) == 4
at(reopen, 1000)
run()
