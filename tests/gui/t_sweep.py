import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"] = doc
    b = new_body(doc, "Body")
    # profile: circle r=4 on the Front (XZ) plane at the origin; path: line + arc on Top (XY)
    prof = sketch(b, "XZ_Plane", circle(0, 0, 4), name="Profile")
    path = sketch(b, "XY_Plane", [Part.LineSegment(V(0, 0, 0), V(0, 40, 0)),
                                   Part.ArcOfCircle(Part.Circle(V(20, 40, 0), V(0, 0, 1), 20), math.pi/2, math.pi)], name="Path")
    doc.recompute()
    log("path wires closed?", [w.isClosed() for w in path.Shape.Wires], "edges", len(path.Shape.Edges))
    S.update(b=b, prof=prof, path=path)
    Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(setup, 1200)
def sw():
    Gui.Selection.clearSelection(); sel(S["prof"])
    from mechflow_gui import sweeploft; sweeploft.sweep()
at(sw, 700)
at(lambda: sel(S["path"]), 700)
exp = math.pi*16*(40 + math.pi*20/2)
at(lambda: (log("SWEEP prof", P().profile.items, "path", P().path.items), state("SWEEP"), log("  expect", round(exp, 1))), 100)
at(lambda: shot("sweep"), 100)
at(lambda: (P().accept(), log("  accepted")), 700)
def sw_edit():
    from mechflow_gui import commands
    commands.edit_feature(S["doc"].getObject("AdditivePipe"))
at(sw_edit, 800)
at(lambda: log("SWEEP edit loaded", P().profile.items, P().path.items, P().orient.currentText()), 100)
at(lambda: P().reject(), 600)
at(lambda: log("tip", S["b"].Tip.Name), 100)
# cut-sweep: smaller circle r=2 through the same path
def cs_setup():
    S["prof2"] = sketch(S["b"], "XZ_Plane", circle(0, 0, 2), name="Profile2")
    S["path2"] = sketch(S["b"], "XY_Plane", [Part.LineSegment(V(0, 0, 0), V(0, 40, 0))], name="Path2")
    S["doc"].recompute()
at(cs_setup, 500)
def cs():
    Gui.Selection.clearSelection(); sel(S["prof2"]); sel(S["path2"])
    from mechflow_gui import sweeploft; sweeploft.cut_sweep()
at(cs, 900)
at(lambda: (log("CUTSWEEP prof", P().profile.items, "path", P().path.items), state("CUTSWEEP"), log("  expect", round(exp - math.pi*4*40, 1))), 100)
at(lambda: (P().accept(), log("  accepted")), 700)
# ---- Loft: square 20x20 at z=0 (Top) to circle r=8 at z=30
def lsetup():
    doc = S["doc"]; S["b"].ViewObject.Visibility = False
    b = new_body(doc, "Body2"); S["b2"] = b
    S["l1"] = sketch(b, "XY_Plane", rect(60, -10, 80, 10), name="L1")
    S["l2"] = sketch(b, "XY_Plane", circle(70, 0, 8), offset=App.Placement(V(0, 0, 30), App.Rotation()), name="L2")
    S["l3"] = sketch(b, "XY_Plane", rect(64, -6, 76, 6), offset=App.Placement(V(0, 0, 50), App.Rotation()), name="L3")
    doc.recompute()
at(lsetup, 600)
def lo():
    Gui.Selection.clearSelection()
    from mechflow_gui import sweeploft; sweeploft.loft()
at(lo, 700)
at(lambda: sel(S["l1"]), 400); at(lambda: sel(S["l2"]), 400); at(lambda: sel(S["l3"]), 800)
at(lambda: (log("LOFT profiles", P().profiles.items), state("LOFT 3 profiles")), 100)
at(lambda: shot("loft"), 100)
at(lambda: P().ruled.setChecked(True), 700)
at(lambda: state("LOFT ruled"), 100)
at(lambda: (P().accept(), log("  accepted")), 700)
def lo_edit():
    from mechflow_gui import commands
    commands.edit_feature(S["doc"].getObject("AdditiveLoft"))
at(lo_edit, 800)
at(lambda: log("LOFT edit loaded", P().profiles.items, P().ruled.isChecked()), 100)
at(lambda: P().reject(), 600)
# cut loft through
def cl_setup():
    S["c1"] = sketch(S["b2"], "XY_Plane", circle(70, 0, 3), name="C1")
    S["c2"] = sketch(S["b2"], "XY_Plane", circle(70, 0, 2), offset=App.Placement(V(0, 0, 50), App.Rotation()), name="C2")
    S["doc"].recompute()
at(cl_setup, 500)
def cl():
    Gui.Selection.clearSelection(); sel(S["c1"]); sel(S["c2"])
    from mechflow_gui import sweeploft; sweeploft.cut_loft()
at(cl, 900)
at(lambda: (log("CUTLOFT", P().profiles.items), state("CUTLOFT")), 100)
at(lambda: (P().accept(), log("  accepted")), 700)
at(lambda: log("tip2", S["b2"].Tip.Name, round(S["b2"].Tip.Shape.Volume,1)), 100)
run()
