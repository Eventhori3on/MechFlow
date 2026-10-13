import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
CURX = {}
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
    S["open"] = sketch(b, "XY_Plane", [Part.LineSegment(V(0, 0, 0), V(40, 0, 0)), Part.LineSegment(V(40, 0, 0), V(40, 30, 0))], name="Open")
    doc.recompute()
    Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(setup, 1200)
X = lambda: CURX["p"]
def xstate(tag):
    p = X(); f = p.feature
    try: vol = round(f.Shape.Volume, 1)
    except Exception: vol = None
    log(f"{tag}: valid={f.isValid()} vol={vol} thin={p.thin.isChecked()} side={p.thin_side.currentText()} t={p.thin_t.value()} err={p.error.isVisible()} {p.error.text()[:150]!r}")
def ex():
    Gui.Selection.clearSelection(); sel(S["open"])
    from mechflow_gui import extrude; extrude.create(cut=False)
at(ex, 900)
at(lambda: xstate("THIN open sketch default"), 100)
at(lambda: X().thin_t.setValue(2), 800)
at(lambda: (xstate("THIN open t=2"), log("  expect ~", 70*2*10)), 100)
at(lambda: shot("thin_open"), 100)
at(lambda: (X().accept(), log("  accepted")), 700)
at(lambda: log("tree", [(o.Name, o.TypeId, [p.Name for p in o.InList]) for o in S["doc"].Objects if o.TypeId in ("Part::Offset2D","PartDesign::SubShapeBinder")], "tip", S["b"].Tip.Name, "body group", [o.Name for o in S["b"].Group]), 100)
def ed():
    from mechflow_gui import commands
    commands.edit_feature(S["doc"].getObject("Pad"))
at(ed, 900)
at(lambda: xstate("THIN edit loaded"), 100)
at(lambda: X().depth1.setValue(25), 800)
at(lambda: xstate("THIN edit depth 25"), 100)
at(lambda: (X().accept(), log("  accepted")), 700)
# closed rectangle, thin outside / inside / mid
def cl_setup():
    S["b"].ViewObject.Visibility = False
    b = new_body(S["doc"], "Body2"); S["b2"] = b
    S["rect"] = sketch(b, "XY_Plane", rect(100, 0, 140, 20), name="Rect")
    S["doc"].recompute()
at(cl_setup, 500)
def ex2():
    Gui.Selection.clearSelection(); sel(S["rect"])
    from mechflow_gui import extrude; extrude.create(cut=False)
at(ex2, 900)
at(lambda: xstate("RECT plain (thin off expected)"), 100)
at(lambda: (X().thin.setChecked(True), X().thin_t.setValue(2)), 800)
at(lambda: (xstate("RECT thin outside"), log("  expect", 2560)), 100)
at(lambda: X().thin_side.setCurrentText("Inside"), 800)
at(lambda: (xstate("RECT thin inside"), log("  expect", 2240)), 100)
at(lambda: X().thin_side.setCurrentText("Mid-plane"), 800)
at(lambda: (xstate("RECT thin mid"), log("  expect", 2400)), 100)
at(lambda: X().thin.setChecked(False), 800)
at(lambda: (xstate("RECT thin off again"), log("  expect", 8000), log("  leftovers", [o.Name for o in S["doc"].Objects if o.TypeId in ("Part::Offset2D","PartDesign::SubShapeBinder")])), 100)
at(lambda: (X().thin.setChecked(True), X().thin_side.setCurrentText("Mid-plane")), 800)
at(lambda: (X().accept(), log("  accepted")), 700)
def ed2():
    from mechflow_gui import commands
    commands.edit_feature(S["b2"].Tip)
at(ed2, 900)
at(lambda: xstate("RECT edit loaded (mid t=2)"), 100)
at(lambda: X().thin_side.setCurrentText("Inside"), 800)
at(lambda: (xstate("RECT edit -> inside"), log("  leftovers", [o.Name for o in S["doc"].Objects if o.TypeId in ("Part::Offset2D","PartDesign::SubShapeBinder")])), 100)
at(lambda: (X().accept(), log("  accepted")), 700)
# material + mass properties
def mat():
    from mechflow_gui import material
    material.set_material(S["b2"], "Aluminium 6061-T6", 2700.0)
    log("material get", material.get(S["b2"]), material.get(S["b2"].Tip))
    Gui.Selection.clearSelection(); sel(S["b2"])
    Gui.runCommand("MechFlow_MassProperties", 0)
at(mat, 800)
def matdlg():
    from mechflow_gui import material
    d = material.MaterialDialog(S["b2"], Gui.getMainWindow())
    log("dialog shows", d.list.currentItem().text() if d.list.currentItem() else None, d.dens.value(), d.name.text())
    d.list.setCurrentRow(list(material.MATERIALS).index("ABS"))
    log("pick ABS ->", d.result_material())
    d.list.setCurrentRow(d.list.count() - 1); d.name.setText("My resin"); d.dens.setValue(1150)
    log("custom ->", d.result_material())
at(matdlg, 500)
run()
