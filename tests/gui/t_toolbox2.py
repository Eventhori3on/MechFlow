import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
try:
    import FastenersCmd  # the Toolbox needs the Fasteners Workbench
    HAVE_FASTENERS = True
except ImportError:
    HAVE_FASTENERS = False
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
    sk = sketch(b, "XY_Plane", rect(0, 0, 80, 40)); p = b.newObject("PartDesign::Pad", "Pad"); p.Profile = sk; p.Length = 15
    doc.recompute(); sk.ViewObject.Visibility = False; S["pad"] = p
at(setup, 1800)
H = lambda: CURH["p"]
top = lambda f: plane_face(f) and normal(f).z > 0.99 and f.BoundBox.ZMin > 14.9
def hole(x, kind, size, end=None, depth=None):
    def o():
        Gui.Selection.clearSelection()
        from mechflow_gui import hole_wizard; hole_wizard.create()
    at(o, 800)
    def c():
        base = S["b"].Tip
        Gui.Selection.addSelection("T", base.Name, face_where(base, top), x, 20, 15)
    at(c, 600)
    def setv():
        H().type.setCurrentText(kind); H().size.setCurrentText(size)
        if end: H().end.setCurrentText(end)
        if depth: H().depth.setValue(depth)
    at(setv, 800)
    at(lambda: (H().accept(), log("hole", kind, size, S["b"].Tip.Name, S["b"].Tip.isValid())), 900)
hole(15, "Counterbore", "M8")
hole(40, "Tapped", "M6", "Blind", 10)
hole(65, "Countersink", "M8")
def tb_open():
    from mechflow_gui import toolbox as tb
    S["panel"] = tb.toolbox()
at(tb_open, 800)
def pick():
    b = S["b"]; tip = b.Tip
    # click the top face of the body: all its holes
    Gui.Selection.addSelection("T", b.Name, tip.Name + "." + face_where(tip, top))
    log("selection", [(x.Object.Name, x.Object.Label, x.SubElementNames) for x in Gui.Selection.getSelectionEx("", 0)])
    from mechflow_gui import toolbox as tb
    sels = tb.attachable_selection(None)
    log("attachable", [(o.Name, o.Label, s) for o, s in sels])
    for o, s_ in sels[:1]:
        e = Part.getShape(o, s_[0], needSubElement=True, noElementMap=True)
        log("  edge", e.Curve, "solid edges", len(Part.getShape(o, ".".join(s_[0].split(".")[:-1]), needSubElement=False, noElementMap=True).Edges))
        h = tb.Hole(o, s_[0]); log("  hole", h.ok, h.diameter, h.seat_sub)
at(pick, 600)
def acc():
    pn = S["panel"]
    log("holes:", [pn.hole_list.item(i).text() for i in range(pn.hole_list.count())])
    log("grips", [(h.grip, h.through, h.kind) for h in pn.holes])
    pn.washer.setChecked(True)
    pn.accept()
    for o in S["doc"].Objects:
        if o.TypeId == "Part::FeaturePython":
            bb = o.Shape.BoundBox
            log(f"   {o.Label:24s} z={bb.ZMin:.2f}..{bb.ZMax:.2f} x={bb.Center.x:.1f}")
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(acc, 900)
at(lambda: shot("toolbox_body"), 800)
if not HAVE_FASTENERS:
    Q.clear()
    at(lambda: log("SKIP: the Fasteners Workbench is not installed"), 100)
run()
