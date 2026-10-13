import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part, Sketcher
V = App.Vector
S = {}
def poly(sk, pts, closed=True):
    n = len(pts)
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        sk.addGeometry(Part.LineSegment(V(*pts[i], 0), V(*pts[(i + 1) % n], 0)))
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("W"); S["doc"] = doc
    sk = doc.addObject("Sketcher::SketchObject", "Frame")
    poly(sk, [(0, 0), (1000, 0), (1000, 600), (0, 600)])
    sk.addGeometry(Part.LineSegment(V(500, 0, 0), V(500, 600, 0)))     # middle post
    sk2 = doc.addObject("Sketcher::SketchObject", "Portal")
    sk2.Placement = App.Placement(V(0, 2000, 0), App.Rotation(V(1, 0, 0), 90))   # on an XZ plane
    poly(sk2, [(0, 0), (0, 2000), (1500, 2600), (3000, 2000), (3000, 0)], closed=False)
    doc.recompute(); S.update(sk=sk, sk2=sk2)
at(setup, 1500)
def P(): return S["panel"]
def open_sm():
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection("W", "Frame")
    from mechflow_gui import weldments as w
    S["panel"] = w.structural_member()
    p = P(); p.type.setCurrentIndex(p.type.findData("SHS-H")); p.size.setCurrentText("50x50x4")
at(open_sm, 600)
def rep(tag):
    def f():
        from mechflow_gui import weldments as w
        o = P().obj
        log(tag, "| obj", o.Label, "| solids", len(o.Shape.Solids), "valid", o.Shape.isValid(), "| corner", o.CornerTreatment)
        log("   cut list:", w.cut_items(S["doc"]))
    return f
at(rep("SHS miter"), 500)
at(lambda: shot("weld_preview"), 200)
at(lambda: P().corner.setCurrentText("End butt 1"), 500); at(rep("SHS butt1"), 100)
at(lambda: P().accept(), 500)
def portal():
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection("W", "Portal")
    from mechflow_gui import weldments as w
    S["panel"] = w.structural_member()
    p = P(); p.type.setCurrentIndex(p.type.findData("UKB")); p.size.setCurrentText("203x133x25")
    p.corner.setCurrentText("End butt 2")
at(portal, 600)
def portal_rep():
    o = P().obj
    for s in o.Shape.Solids:
        bb = s.BoundBox
        log(f"   portal solid x {bb.XMin:.1f}..{bb.XMax:.1f} y {bb.YMin:.1f}..{bb.YMax:.1f} z {bb.ZMin:.1f}..{bb.ZMax:.1f} vol {s.Volume:,.0f}")
    P().accept()
    from mechflow_gui import weldments as w
    log("cut list all:", w.cut_items(S["doc"]))
at(portal_rep, 600)
def edit():
    o = [x for x in S["doc"].Objects if x.Label.startswith("SHS")][0]
    Gui.ActiveDocument.setEdit(o.Name)
    p = Gui.Control.activeDialog() and None
at(edit, 600)
def in_edit():
    from mechflow_gui import weldments as w
    dlg = Gui.Control.activeDialog()
    log("edit dialog open:", dlg)
at(in_edit, 400)
at(lambda: (Gui.Control.closeDialog(), Gui.ActiveDocument.resetEdit()), 400)
def cl():
    from mechflow_gui import weldments as w
    w.cut_list()
    sh = [o for o in S["doc"].Objects if o.TypeId == "Spreadsheet::Sheet"][0]
    log("sheet:", [[sh.getContents(f"{c}{r}") for c in "ABCDEF"] for r in range(1, 6)])
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(cl, 500)
at(lambda: shot("weld_result"), 800)
run()
