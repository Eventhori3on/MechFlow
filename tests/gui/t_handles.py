import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}; CURX = {}
def setup():
    install_hooks()
    from mechflow_gui import extrude
    orig = extrude.ExtrudePanel.__init__
    def init(self, *a, **k):
        CURX["p"] = self; orig(self, *a, **k)
    extrude.ExtrudePanel.__init__ = init
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    S["sk"] = sketch(b, "XY_Plane", rect(-30, -20, 30, 20)); doc.recompute()
    Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(setup, 1200)
X = lambda: CURX["p"]
def ex():
    Gui.Selection.clearSelection(); sel(S["sk"])
    from mechflow_gui import extrude; extrude.create(cut=False)
at(ex, 900)
def xh(tag):
    def f():
        c = X()._depth_arrow
        log(tag, "arrow", c.arrow is not None, "tip", c.arrow and c.arrow.tip(), "box", c.box and (c.box.isVisible(), c.box.value()), "depth", X().depth1.value(),
            "pad zmax", round(X().feature.Shape.BoundBox.ZMax, 3) if X().feature.isValid() else None)
    return f
at(xh("EXT default"), 100)
at(lambda: Gui.SendMsgToActiveView("ViewFit"), 300)
at(lambda: shot("ext_arrow"), 100)
def drag(v):
    def f():
        c = X()._depth_arrow; c.arrow.dragger.translation.setValue(v / c.arrow.scale, 0, 0)
    return f
at(drag(25), 700); at(xh("EXT dragged 25"), 100)
at(lambda: X().depth1.setValue(15), 700); at(xh("EXT typed 15"), 100)
at(lambda: X().c_box_set if False else X()._depth_arrow.box.setValue(18), 700); at(xh("EXT 3D box 18"), 100)
at(lambda: X().reverse1.setChecked(True), 700); at(xh("EXT reversed"), 100)
at(lambda: X().reverse1.setChecked(False), 500)
at(lambda: X().cond1.setCurrentText("Mid Plane"), 700); at(xh("EXT mid plane"), 100)
at(lambda: X().cond1.setCurrentIndex(0), 500)
at(lambda: (X().accept(), log("  accepted, boxes left:", [w.objectName() for w in Gui.getMainWindow().findChildren(QtWidgets.QDoubleSpinBox) if w.objectName()=="MechFlow_ViewBox" and w.isVisible()])), 700)
# cut extrude from top face
def cut_setup():
    S["sk2"] = sketch(S["b"], "XY_Plane", circle(-20, 0, 3), offset=App.Placement(V(0, 0, 18), App.Rotation()), name="Hole")
    S["doc"].recompute()
at(cut_setup, 400)
def cx():
    Gui.Selection.clearSelection(); sel(S["sk2"])
    from mechflow_gui import extrude; extrude.create(cut=True)
at(cx, 900)
def ch():
    c = X()._depth_arrow
    log("CUT arrow tip", c.arrow and c.arrow.tip(), "depth", X().depth1.value(), "valid", X().feature.isValid())
at(ch, 100)
at(lambda: X().depth1.setValue(18), 700)
at(lambda: (log("CUT through vol", round(X().feature.Shape.Volume, 1), "expect", round(60*40*18 - math.pi*9*18, 1)), X().accept()), 700)
# linear pattern with drag
def lp():
    Gui.Selection.clearSelection(); sel(S["b"].Tip)
    from mechflow_gui import patterns; patterns.linear()
at(lp, 700)
def lp_edge():
    tip = S["b"].Tip
    # front top edge along X (y=-20, z=18)
    for i, e in enumerate(tip.Shape.Edges):
        if type(e.Curve).__name__ in ("Line", "LineSegment") and abs(e.CenterOfMass.y + 20) < 1e-6 and abs(e.CenterOfMass.z - 18) < 1e-6:
            sel(tip, f"Edge{i+1}"); return
at(lp_edge, 800)
def lh(tag):
    def f():
        p = P(); c = p.spacing_arrow
        tip = c.arrow.tip() if c.arrow else None
        inside = None
        if tip is not None and p.feature.isValid():
            inside = p.feature.Shape.isInside(V(tip.x, tip.y, 9), 1e-6, True)
        log(tag, "feats", p.feats.items, "dir", p.dirf.items, "arrow tip", tip, "copy is a hole there:", inside is False, "spacing", p.spacing.value(), "vol", round(p.feature.Shape.Volume, 1) if p.feature.isValid() else None)
    return f
at(lambda: (P().spacing.setValue(12), P().count.setValue(3)), 700)
at(lh("LP edge dir"), 100)
at(lambda: shot("lp_arrow"), 100)
def dragp(v):
    def f():
        c = P().spacing_arrow; c.arrow.dragger.translation.setValue(v / c.arrow.scale, 0, 0)
    return f
at(dragp(17), 800); at(lh("LP dragged 17"), 100)
at(lambda: P().reverse.setChecked(True), 800); at(lh("LP reversed"), 100)
at(lambda: (P().accept(), log("  accepted, boxes left:", len([w for w in Gui.getMainWindow().findChildren(QtWidgets.QDoubleSpinBox) if w.objectName()=="MechFlow_ViewBox" and w.isVisible()]))), 700)
run()
