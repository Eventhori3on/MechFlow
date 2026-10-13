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
    sk = sketch(b, "XY_Plane", rect(-30, -20, 30, 20))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = 10
    hole = b.newObject("PartDesign::SubtractiveCylinder", "Hole"); hole.Radius = 3; hole.Height = 10
    attach_xy(hole, b, -20, 0)
    doc.recompute(); sk.ViewObject.Visibility = False
    S["b"] = b; S["pad"] = pad; S["hole"] = hole
    log("box", round(pad.Shape.Volume, 2), "with hole", round(hole.Shape.Volume, 2), "hole vol", round(math.pi * 90, 2))
    Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(setup, 1200)

# ---- Linear pattern: preselect the hole, then use X axis, spacing 15, 3 instances
def lp_open():
    Gui.Selection.clearSelection(); sel(S["hole"])
    from mechflow_gui import patterns; patterns.linear()
def lp_set():
    p = P(); log("LP feats", p.feats.items, "dir", p.dirf.items)
    p.axis.setCurrentText("X axis"); p.spacing.setValue(15); p.count.setValue(3)
at(lambda: tipwatch(), 10)
at(lp_open, 600); at(lp_set, 800)
at(lambda: (state("LP"), log("  expect", round(24000 - 3 * math.pi * 90, 2)), shot("lp")), 100)
at(lambda: (P().accept(), log("  accepted")), 600)
# edit
def tipwatch():
    b=S["b"]; last=[None]
    def tick():
        t=b.Tip.Name if b.Tip else None
        if t!=last[0]:
            import traceback as tb
            log("   TIP ->", t); last[0]=t
    tm=QtCore.QTimer(); tm.setInterval(20); tm.timeout.connect(tick); tm.start(); S["tm"]=tm
at(tipwatch, 10)
def lp_edit():
    from mechflow_gui import commands
    f = S["doc"].getObject("LinearPattern"); S["lp"] = f
    commands.edit_feature(f)
at(lp_edit, 800)
at(lambda: log("LP edit loaded: feats", P().feats.items, "dir", P().dirf.items, "axis", P().axis.currentText(), "spacing", P().spacing.value(), "n", P().count.value()), 100)
at(lambda: P().spacing.setValue(12), 600); at(lambda: state("LP edited sp12"), 100)
at(lambda: (P().accept(), log("  accepted")), 600)

# ---- Linear pattern by clicking an edge for direction (Y edge of the box)
def lp2():
    Gui.Selection.clearSelection()
    from mechflow_gui import patterns; patterns.linear()
def lp2_pick():
    tip = S["b"].Tip
    e = [f"Edge{i+1}" for i, ed in enumerate(tip.Shape.Edges) if type(ed.Curve).__name__ in ("Line","LineSegment") and abs(ed.Vertexes[0].Point.x - ed.Vertexes[1].Point.x) < 1e-6 and abs(ed.Vertexes[0].Point.z - ed.Vertexes[1].Point.z) < 1e-6 and abs(ed.Vertexes[0].Point.z-10)<1e-6][0]
    sel(tip, e)
def lp2_feat(): sel(S["hole"])
at(lp2, 600); at(lp2_pick, 500); at(lp2_feat, 500)
at(lambda: (log("LP2 dir", P().dirf.items, "feats", P().feats.items), P().spacing.setValue(8), P().count.setValue(2)), 700)
at(lambda: state("LP2 edge dir"), 100)
at(lambda: P().reject(), 600)

# ---- Circular pattern around Z axis, 4 equal
def cp():
    Gui.Selection.clearSelection(); sel(S["hole"])
    from mechflow_gui import patterns; patterns.circular()
at(cp, 600)
at(lambda: (P().axis.setCurrentText("Z axis"), P().count.setValue(4)), 800)
at(lambda: (state("CP"), log("  expect (holes at r=20 around Z, inside 60x40?) ")), 100)
at(lambda: shot("cp"), 100)
at(lambda: P().reject(), 600)

# ---- Mirror about Right plane
def mi():
    Gui.Selection.clearSelection(); sel(S["hole"])
    from mechflow_gui import patterns; patterns.mirror()
at(mi, 600)
at(lambda: P().plane.setCurrentText("Right Plane"), 800)
at(lambda: (state("MIRROR"), log("  expect", round(S["lp"].Shape.Volume - math.pi*90, 2) if False else "tip-1 hole")), 100)
at(lambda: (P().accept(), log("  accepted")), 600)
def mi_edit():
    from mechflow_gui import commands
    f = S["doc"].getObject("Mirrored"); commands.edit_feature(f)
at(mi_edit, 800)
at(lambda: log("MIRROR edit loaded: feats", P().feats.items, "plane", P().planef.items, P().plane.currentText()), 100)
at(lambda: P().reject(), 600)
at(lambda: log("final tip", S["b"].Tip.Name, round(S["b"].Tip.Shape.Volume, 2)), 100)
run()
