import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
try:
    import FastenersCmd
    HAVE_FASTENERS = True
except ImportError:
    HAVE_FASTENERS = False
import Part
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("SF"); S["doc"] = doc
    A = Part.makeBox(120, 40, 10, V(0, 0, 15))
    for x in (15, 40, 65, 90, 110):
        A = A.cut(Part.makeCylinder(4.5, 12, V(x, 20, 14)))
    A = A.cut(Part.makeCylinder(7, 9, V(40, 20, 25 - 8.5)))
    A = A.cut(Part.makeCone(4.5, 9, 4.5, V(90, 20, 20.5)))
    B = Part.makeBox(120, 40, 15)
    B = B.cut(Part.makeCylinder(3.4, 13, V(15, 20, 3)))      # tapped M8 blind 12
    B = B.cut(Part.makeCylinder(3.4, 17, V(40, 20, -1)))     # tapped M8 through
    B = B.cut(Part.makeCylinder(4.5, 17, V(65, 20, -1)))     # clearance through
    B = B.cut(Part.makeCylinder(3.4, 13, V(90, 20, 3)))      # tapped blind under the countersink
    C = Part.makeBox(30, 30, 12, V(200, 0, 0)).cut(Part.makeCylinder(2.5, 9, V(215, 15, -1)))  # M6 tapped from below
    for n, sh in (("Top", A), ("Base", B), ("Block", C)):
        o = doc.addObject("Part::Feature", n); o.Shape = sh.removeSplitter()
    doc.recompute()
at(setup, 1500)
def run_sf():
    Gui.Selection.clearSelection()
    from mechflow_gui import smart_fasteners as sf
    p = sf.smart_fasteners(); S["p"] = p
    for r in range(len(p.groups)):
        log("row:", p.labels[r].text(), "|", p.combos[r].currentText(), "|", p.lengths[r].text())
    log("skipped:", [(s.describe() if s.ok else s.reason) for s in p.stacks if not s.ok])
at(run_sf, 800)
at(lambda: shot("smart_panel"), 300)
def acc():
    p = S["p"]; p.accept()
    for o in p.made:
        bb = o.Shape.BoundBox
        log(f"  {o.Label:24s} x {bb.Center.x:6.1f}  z {bb.ZMin:6.2f}..{bb.ZMax:6.2f}")
at(acc, 800)
def again():
    from mechflow_gui import smart_fasteners as sf
    st = sf.find_stacks(None)
    log("second run finds:", len(st))
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(again, 500)
at(lambda: shot("smart_result"), 700)
OUT = os.environ.get("MF_OUT", "/tmp") + "/"
def asm():
    src = S["doc"]
    for o in list(src.Objects):
        if type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject": src.removeObject(o.Name)
    src.saveAs(OUT + "SFparts.FCStd")
    from mechflow_gui import assembly
    a = assembly.new_assembly(); S["asm"] = a
    a.Document.saveAs(OUT + "SFasm.FCStd")
    for n in ("Top", "Base"):
        l = a.newObject("App::Link", n); l.LinkedObject = src.getObject(n); l.Label = n + "<1>"
        l.Placement = App.Placement(V(0, 100, 0), App.Rotation())
    a.Document.recompute()
    from mechflow_gui import smart_fasteners as sf
    p = sf.smart_fasteners(); S["p"] = p
    log("assembly container:", p.container and p.container.Label, "rows", len(p.groups))
    p.accept()
    fs = [o for o in a.Group if type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject"]
    log("in assembly:", len(fs), sorted(o.Label for o in fs))
    log("y of fasteners", sorted({round(o.Shape.BoundBox.Center.y, 1) for o in fs}))
at(asm, 800)
if not HAVE_FASTENERS:
    Q.clear()
    at(lambda: log("SKIP: the Fasteners Workbench is not installed"), 100)
run()
