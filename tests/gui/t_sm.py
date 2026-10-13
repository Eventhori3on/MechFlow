import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
OUT = os.environ.get("MF_OUT", "/tmp") + "/"
try:
    import SheetMetalTools
    HAVE = True
except ImportError:
    HAVE = False
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("SM"); S["doc"] = doc
    sk = doc.addObject("Sketcher::SketchObject", "Profile")
    sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(100, 0, 0)))
    sk.addGeometry(Part.LineSegment(V(100, 0, 0), V(100, 60, 0)))
    doc.recompute(); S["sk"] = sk
    log("commands active (nothing selected):", Gui.Command.get("MechFlow_SM_BaseFlange").isActive())
at(setup, 1500)
def base():
    Gui.Selection.addSelection("SM", "Profile")
    log("base flange active with sketch:", Gui.Command.get("MechFlow_SM_BaseFlange").isActive())
    Gui.runCommand("MechFlow_SM_BaseFlange", 0)
at(base, 600)
def base_done():
    dlg = Gui.Control.activeDialog()
    log("task dialog:", dlg)
    Gui.Control.closeDialog()   # accept defaults
    objs = [o for o in S["doc"].Objects if o.TypeId.endswith("FeaturePython")]
    S["base"] = objs[-1]
    b = S["base"]
    log("base:", b.Name, b.Label, "valid", b.Shape.isValid(), "solids", len(b.Shape.Solids), "bbox", b.Shape.BoundBox, "thk", getattr(b, "Thickness", None), "len", getattr(b, "Length", None))
at(base_done, 1000)
def flange():
    b = S["base"]
    # an edge along the far end of the 60 leg (top, at y=60-ish)
    best = None
    for i, e in enumerate(b.Shape.Edges):
        if type(e.Curve).__name__ == "Line" and abs(e.Vertexes[0].Point.y - e.Vertexes[-1].Point.y) < 1e-6 and e.Vertexes[0].Point.y > 55:
            if best is None or e.Vertexes[0].Point.x > best[1]:
                best = (f"Edge{i+1}", e.Vertexes[0].Point.x)
    log("flange edge", best)
    Gui.Selection.clearSelection(); Gui.Selection.addSelection("SM", b.Name, best[0])
    log("edge flange active:", Gui.Command.get("MechFlow_SM_EdgeFlange").isActive())
    Gui.runCommand("MechFlow_SM_EdgeFlange", 0)
at(flange, 600)
def flange_done():
    Gui.Control.closeDialog()
    S["doc"].recompute()
    objs = [o for o in S["doc"].Objects if o.TypeId.endswith("FeaturePython")]
    w = objs[-1]; S["wall"] = w
    log("wall:", w.Name, "valid", w.Shape.isValid(), "vol", round(w.Shape.Volume), "bbox", w.Shape.BoundBox)
at(flange_done, 1000)
def flat():
    from mechflow_gui import sheet_metal as sm
    Gui.Selection.clearSelection()
    f = sm.flatten(); S["flat"] = f
    log("flat:", f and f.Name, f and f.ViewObject.Visibility, "part visible", S["wall"].ViewObject.Visibility,
        "flat bbox", f and f.Shape.BoundBox, "sketches", f and list(f.UnfoldSketches))
    Gui.SendMsgToActiveView("ViewFit")
at(flat, 1500)
at(lambda: shot("sm_flat"), 500)
def dxf():
    from mechflow_gui import sheet_metal as sm
    sm.flatten()   # fold back
    log("after fold back: flat visible", S["flat"].ViewObject.Visibility, "part", S["wall"].ViewObject.Visibility)
    p = sm.save_flat_dxf(OUT + "sm_flat.dxf")
    log("dxf:", p, os.path.exists(OUT + "sm_flat.dxf") and os.path.getsize(OUT + "sm_flat.dxf"))
    log("flat visible after save:", S["flat"].ViewObject.Visibility)
    txt = open(OUT + "sm_flat.dxf").read()
    log("dxf entities:", txt.count("\nLINE"), "lines")
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(dxf, 1200)
at(lambda: shot("sm_folded"), 600)
if not HAVE:
    Q.clear()
    at(lambda: log("SKIP: the SheetMetal Workbench is not installed"), 100)
run()
