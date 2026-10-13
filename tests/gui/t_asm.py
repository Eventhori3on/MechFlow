import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
def mkparts():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    d1 = App.newDocument("Plate"); b1 = new_body(d1, "Body")
    sk = sketch(b1, "XY_Plane", rect(0, 0, 100, 60)); p = b1.newObject("PartDesign::Pad","Pad"); p.Profile=sk; p.Length=10
    h = b1.newObject("PartDesign::SubtractiveCylinder","Hole"); h.Radius=5; h.Height=10; attach_xy(h, b1, 30, 30)
    d1.recompute(); d1.saveAs(OUT + "Plate.FCStd")
    d2 = App.newDocument("Pin"); b2 = new_body(d2, "Body")
    c = b2.newObject("PartDesign::AdditiveCylinder","Cyl"); c.Radius=5; c.Height=40
    d2.recompute(); d2.saveAs(OUT + "Pin.FCStd")
    S.update(plate=b1, pin=b2)
at(mkparts, 2000)
def newasm():
    from mechflow_gui import assembly
    S["asm"] = assembly.new_assembly()
at(newasm, 1500)
def curtab():
    from mechflow_gui import command_manager as cm
    for t in cm._bar.findChildren(QtWidgets.QTabWidget): return t.tabText(t.currentIndex())
def chk_asm():
    from mechflow_gui import layout
    ie = Gui.ActiveDocument.getInEdit()
    log("tab in assembly:", curtab(), "| ctx now:", layout._current_context(), "stored:", layout._context, "timer:", layout._timer and layout._timer.isActive(), "activeDoc", Gui.ActiveDocument.Document.Name)
    a = S["asm"]
    from mechflow_gui import assembly
    log("assembly", a and a.Label, "doc", App.ActiveDocument.Label, "in edit", a and a.ViewObject.isInEditMode(), "wb", Gui.activeWorkbench().name(),
        "groups", [ (o.Name, o.Label) for o in a.Group ])
at(chk_asm, 300)
def insert():
    # what Insert Components does: links to the parts, first one grounded
    a = S["asm"]; J, U = __import__("mechflow_gui.assembly", fromlist=["x"])._assembly_modules()
    a.Document.saveAs(OUT + "Asm.FCStd")
    l1 = a.newObject("App::Link", "Plate"); l1.LinkedObject = S["plate"]; l1.Label = "Plate<1>"
    l2 = a.newObject("App::Link", "Pin"); l2.LinkedObject = S["pin"]; l2.Label = "Pin<1>"
    l2.Placement = App.Placement(V(150, 80, 20), App.Rotation(V(1, 1, 0), 40))
    g = U.getJointGroup(a).newObject("App::FeaturePython", "GroundedJoint"); J.GroundedJoint(g, l1)
    try: J.ViewProviderGroundedJoint(g.ViewObject)
    except Exception as e: log("vp grounded", e)
    a.Document.recompute(); S.update(l1=l1, l2=l2)
    Gui.SendMsgToActiveView("ViewFit")
at(insert, 800)
def ic():
    from mechflow_gui import assembly
    assembly.insert_components()
at(ic, 1200)
at(lambda: (log("insert components dialog open:", bool(Gui.Control.activeDialog())), Gui.Control.closeDialog()), 600)
def face_of(link, pred):
    sh = link.Shape
    for i, f in enumerate(sh.Faces):
        if pred(f): return f"Face{i+1}"
cyl = lambda f: type(f.Surface).__name__ == "Cylinder"
def mate_open():
    from mechflow_gui import assembly
    S["mp"] = assembly.mate()
at(mate_open, 800)
def pick(link_key, pred):
    def f():
        l = S[link_key]; fn = face_of(l, pred)
        Gui.Selection.addSelection(S["asm"].Document.Name, S["asm"].Name, f"{l.Name}.{fn}")
        log("  picked", l.Label, fn, "selEx:", [(s.ObjectName, s.SubElementNames) for s in Gui.Selection.getSelectionEx("*", 0)])
    return f
at(pick("l1", cyl), 500)
at(pick("l2", cyl), 900)
def mstate(tag):
    def f():
        mp = S["mp"]; l2 = S["l2"]
        ax = l2.Placement.Rotation.multVec(V(0, 0, 1)); base = l2.Placement.Base
        log(tag, "picks", [p[4] for p in mp.picks], "mate", mp.mate, "joint", mp.joint and (mp.joint.JointType, mp.joint.isValid()),
            "pin axis", [round(x, 3) for x in ax], "pin base", [round(x, 3) for x in base], "|", mp.msg.text()[:90])
        shot(tag)
    return f
at(mstate("MATE concentric"), 200)
at(lambda: S["mp"].accept(), 800)
at(lambda: log("joints", [(j.Label, getattr(j, "JointType", "ground")) for j in __import__("mechflow_gui.assembly", fromlist=["x"])._assembly_modules()[1].getJointGroup(S["asm"]).Group],
               "folder", __import__("mechflow_gui.assembly", fromlist=["x"])._assembly_modules()[1].getJointGroup(S["asm"]).Label), 200)
# Coincident: pin bottom flush with plate bottom
botz = lambda f: type(f.Surface).__name__ == "Plane" and f.normalAt(0, 0).z < -0.99
pinbot = lambda f: type(f.Surface).__name__ == "Plane" and abs(f.CenterOfMass.z - min(ff.CenterOfMass.z for ff in S["l2"].Shape.Faces)) < 1e-6
at(mate_open, 800)
at(pick("l1", botz), 500)
def pick_pin_end():
    l = S["l2"]; sh = l.Shape
    ends = [(i, f) for i, f in enumerate(sh.Faces) if type(f.Surface).__name__ == "Plane"]
    i, f = min(ends, key=lambda t: t[1].CenterOfMass.z)
    Gui.Selection.addSelection(S["asm"].Document.Name, S["asm"].Name, f"{l.Name}.Face{i+1}")
at(pick_pin_end, 900)
at(mstate("MATE coincident"), 200)
at(lambda: log("   pin zmin", round(S["l2"].Shape.BoundBox.ZMin, 3), "zmax", round(S["l2"].Shape.BoundBox.ZMax, 3)), 50)
at(lambda: S["mp"]._set_mate("Distance"), 600)
at(lambda: S["mp"].dist.setValue(5), 800)
at(lambda: log("DISTANCE 5: pin zmin", round(S["l2"].Shape.BoundBox.ZMin, 3), "joint", S["mp"].joint.JointType, S["mp"].joint.Distance), 50)
at(lambda: S["mp"]._flip(), 800)
at(lambda: log("FLIPPED: pin zmin", round(S["l2"].Shape.BoundBox.ZMin, 3), "zmax", round(S["l2"].Shape.BoundBox.ZMax, 3)), 50)
at(lambda: S["mp"].reject(), 800)
at(lambda: log("after cancel: pin zmin", round(S["l2"].Shape.BoundBox.ZMin, 3), "joints", len(__import__("mechflow_gui.assembly", fromlist=["x"])._assembly_modules()[1].getJointGroup(S["asm"]).Group)), 200)
def interf():
    from mechflow_gui import assembly
    log("interference (fit pin):", [(a.Label, b.Label, round(v, 2)) for a, b, v in assembly.interferences(S["asm"])])
    S["pin"].Group[0].Radius = 6 if False else S["pin"].Group[0].Radius
    cylf = [o for o in S["pin"].Document.Objects if o.TypeId == "PartDesign::AdditiveCylinder"][0]
    cylf.Radius = 6; S["pin"].Document.recompute(); S["asm"].Document.recompute()
    log("interference (6 mm pin in 5 mm hole):", [(a.Label, b.Label, round(v, 2)) for a, b, v in assembly.interferences(S["asm"])])
at(interf, 800)
run()
