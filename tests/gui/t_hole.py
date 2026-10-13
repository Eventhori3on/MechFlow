import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}; CURH = {}
def setup():
    install_hooks()
    from mechflow_gui import hole_wizard
    orig = hole_wizard.HolePanel.__init__
    def init(self, *a, **k):
        CURH["p"] = self; orig(self, *a, **k)
    hole_wizard.HolePanel.__init__ = init
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    sk = sketch(b, "XY_Plane", rect(0, 0, 80, 40)); p = b.newObject("PartDesign::Pad", "Pad"); p.Profile = sk; p.Length = 12
    doc.recompute(); sk.ViewObject.Visibility = False; S["pad"] = p
at(setup, 1800)
H = lambda: CURH["p"]
top = lambda f: plane_face(f) and normal(f).z > 0.99
def report(tag):
    def f():
        h = H().hole
        log(tag, "| type", H().type.currentText(), "size", H().size.currentText(), "fit", H().fit.currentText(),
            "| ThreadSize", h and h.ThreadSize, "Threaded", h and h.Threaded, "Cut", h and h.HoleCutType, "Fit", h and h.ThreadFit,
            "Diameter", h and round(float(h.Diameter), 2), "| holes", h and len(h.Profile[0].Geometry if isinstance(h.Profile, tuple) else h.Profile.Geometry),
            "valid", h and h.isValid(), "vol", h and round(h.Shape.Volume, 1))
    return f
def open_hw():
    Gui.Selection.clearSelection()
    from mechflow_gui import hole_wizard; hole_wizard.create()
at(open_hw, 800)
def click(x, y):
    def f():
        p = S["pad"] if H().hole is None else H().base
        Gui.Selection.addSelection(S["doc"].Name, p.Name, face_where(p, top), x, y, 12)
    return f
at(click(20, 20), 600); at(click(55, 20), 600)
for kind, size, fit in (("Simple", "M8", "Normal"), ("Simple", "M8", "Close"), ("Simple", "M8", "Loose"),
                        ("Counterbore", "M8", "Normal"), ("Tapped", "M6", "Normal")):
    def setv(k=kind, s=size, ft=fit):
        H().type.setCurrentText(k); H().size.setCurrentText(s); H().fit.setCurrentText(ft)
    at(setv, 800); at(report(f"HW {kind} {size} {fit}"), 50)
at(lambda: H().end.setCurrentText("Blind"), 300)
at(lambda: H().depth.setValue(10), 800); at(report("HW Tapped M6 blind 10"), 50)
at(lambda: (H().accept(), log("  accepted")), 800)
def ed():
    from mechflow_gui import commands
    commands.edit_feature(S["b"].Tip)
at(ed, 900)
at(report("HW edit loaded"), 50)
at(lambda: H().reject(), 600)
run()
