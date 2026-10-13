import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
def circle_edge(obj, r, z, x=0):
    for i, e in enumerate(obj.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - r) < 1e-3 and abs(c.Center.z - z) < 1e-3 and abs(c.Center.x - x) < 1e-3:
            return f"Edge{i+1}"
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("P"); S["doc"] = doc
    pipe = doc.addObject("Part::Feature", "Pipe")
    pipe.Shape = Part.makeCylinder(30.15, 300).cut(Part.makeCylinder(27.25, 302, V(0, 0, -1)))
    shaft = doc.addObject("Part::Feature", "Shaft"); shaft.Shape = Part.makeCylinder(10, 80, V(200, 0, 0))
    house = doc.addObject("Part::Feature", "Housing")
    house.Shape = Part.makeBox(100, 100, 30, V(350, -50, 0)).cut(Part.makeCylinder(23.5, 32, V(400, 0, -1)))
    doc.recompute(); S.update(pipe=pipe, shaft=shaft, house=house)
at(setup, 1500)
def P():
    return S["panel"]
def open_tb(t):
    def f():
        from mechflow_gui import toolbox as tb
        S["panel"] = tb.toolbox()
        p = P()
        p.std.setCurrentText("All")
        def find(item):
            for i in range(item.childCount()):
                c = item.child(i)
                if c.data(0, QtCore.Qt.UserRole) == t: return c
                r = find(c)
                if r: return r
        it = find(p.tree.invisibleRootItem())
        p.tree.setCurrentItem(it)
        log("open", t, "| type", p.current_type(), "| sizes", p.size.count(), "| rating", [p.rating.itemText(i) for i in range(p.rating.count())],
            "| rating row", p.rating.isVisible(), "length row", p.length.isVisible(), "pipe len", p.pipe_length.isVisible(), "| box", p.hole_box.title())
    return f
def pick(objkey, r, z, x=0):
    def f():
        o = S[objkey]; sub = circle_edge(o, r, z, x)
        Gui.Selection.addSelection("P", o.Name, sub)
    return f
def acc(tag):
    def f():
        p = P()
        log("  edges:", [p.hole_list.item(i).text() for i in range(p.hole_list.count())], "| msg", p.msg.text()[:60])
        p.accept()
        for o in p.made:
            bb = o.Shape.BoundBox
            log(f"  {tag}: {o.Label} | size {o.Size} rating {o.Rating} | valid {o.Shape.isValid()} | x {bb.XMin:.1f}..{bb.XMax:.1f} z {bb.ZMin:.1f}..{bb.ZMax:.1f} | centre ({bb.Center.x:.1f},{bb.Center.y:.1f})")
            S[tag] = o
    return f
# weld neck flange on the pipe top
at(open_tb("EN1092-1-11"), 700); at(pick("pipe", 30.15, 300), 500); at(acc("wn"), 600)
# blind on the flange raised face
def pick_rf():
    o = S["wn"]; sub = circle_edge(o, 51, 345)
    log("  rf edge", sub); Gui.Selection.addSelection("P", o.Name, sub)
at(open_tb("EN1092-1-05"), 700); at(pick_rf, 500); at(acc("blind"), 600)
# ASME 90 LR elbow at the pipe bottom
at(open_tb("ASMEB16.9-90LR"), 700); at(pick("pipe", 30.15, 0), 500); at(acc("elbow"), 600)
# bearing on the shaft end and in the housing bore
at(open_tb("ISO15-62"), 700); at(pick("shaft", 10, 80, 200), 400); at(pick("house", 23.5, 30, 400), 500); at(acc("brg"), 600)
# ASME slip-on on the pipe top (other standard, auto from 60.3 OD)
at(open_tb("ASMEB16.5-SO"), 700); at(pick("pipe", 30.15, 300), 500); at(acc("so"), 600)
# pipe with nothing picked, 250 long
def pipe_nothing():
    p = P(); p.pipe_length.setValue(250); p.size.setCurrentText("DN80")
at(open_tb("EN10220-PIPE"), 700); at(pipe_nothing, 300); at(acc("pipe2"), 600)
# change size afterwards, move the pipe -> parts follow
def change():
    o = S["wn"]; o.Rating = "PN40"; S["doc"].recompute()
    log("after PN40:", o.Label, round(o.Shape.BoundBox.ZMax, 1))
    S["pipe"].Placement = App.Placement(V(0, 0, 50), App.Rotation())
    S["doc"].recompute()
    log("after moving the pipe up 50: wn z", round(S["wn"].Shape.BoundBox.ZMin, 1), "elbow zmax", round(S["elbow"].Shape.BoundBox.ZMax, 1))
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(change, 500)
at(lambda: shot("stdparts"), 800)
def bomcheck():
    from mechflow_gui import bom
    log("BOM rows:", [bom._std_row(S[k]) for k in ("wn", "elbow", "brg", "pipe2")])
    from mechflow_gui import toolbox as tb
    log("fasteners installed:", tb.fasteners() is not None)
at(bomcheck, 200)
def tree_shot():
    from mechflow_gui import toolbox as tb
    S["panel"] = tb.toolbox(); p = P(); p.std.setCurrentText("All")
    p.std.setCurrentText("EN")
    for i in range(p.tree.topLevelItemCount()):
        it = p.tree.topLevelItem(i); it.setExpanded(it.text(0) in ("Flanges",))
        log("category", it.text(0), it.childCount())
        if it.text(0) == "Flanges":
            p.tree.setCurrentItem(it.child(0)); p.tree.scrollToItem(it.child(0))
    Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Combo View")
    log("rows visible to panel:", p.rating.isVisibleTo(p.form), p.length.isVisibleTo(p.form), p.washer.isVisibleTo(p.form), p.size.currentText(), p.size.count())
at(tree_shot, 600)
at(lambda: shot("stdparts_panel"), 400)
at(lambda: P().reject(), 300)
OUT = os.environ.get("MF_OUT", "/tmp") + "/"
def reopen():
    d = S["doc"]; d.saveAs(OUT + "stdparts.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "stdparts.FCStd")
    o = [x for x in d.Objects if x.Label.startswith("EN 1092-1/11")][0]
    o.Size = "DN100"; d.recompute()
    log("reopened:", o.Label, type(o.Proxy).__name__, "valid", o.Shape.isValid(), "OD", round(o.Shape.BoundBox.XLength, 1))
at(reopen, 600)
def showcase():
    from mechflow_gui import stdparts as sp
    d = App.newDocument("Show")
    items = [("EN1092-1-11", "DN100", "PN16", 0), ("EN1092-1-01", "DN100", "PN16", 300), ("EN1092-1-05", "DN100", "PN16", 600),
             ("ASMEB16.9-90LR", "NPS 4", "Sch 40", 900), ("ASMEB16.9-TEE", "NPS 4", "Sch 40", 1200),
             ("ASMEB16.9-RED", "NPS 4 x 3", "Sch 40", 1450), ("ISO15-62", "6212", "", 1650)]
    for t, s_, r, x in items:
        o = sp.make(None, t, s_, r, 300)
        o.Placement = App.Placement(V(x, 0, 0), App.Rotation()); d.recompute()
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(showcase, 800)
at(lambda: shot("stdparts_showcase"), 800)
run()
