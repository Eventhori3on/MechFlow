import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"] = doc
    b = new_body(doc, "Body")
    sk = sketch(b, "XY_Plane", rect(-30, -20, 30, 20))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = 20
    doc.recompute(); sk.ViewObject.Visibility = False
    S["b"] = b; S["pad"] = pad
    Gui.activeDocument().activeView().viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(setup, 1200)
top = lambda f: plane_face(f) and normal(f).z > 0.99
bottom = lambda f: plane_face(f) and normal(f).z < -0.99
side = lambda f: plane_face(f) and abs(normal(f).z) < 1e-6
# ---- Shell: click top face first (preselected), thickness 2
def sh():
    Gui.Selection.clearSelection(); sel(S["pad"], face_where(S["pad"], top))
    from mechflow_gui import dressup; dressup.shell()
at(sh, 700)
at(lambda: (log("SHELL faces", P().faces.items), P().thick.setValue(2)), 800)
exp_shell = 60*40*20 - 56*36*18
at(lambda: (state("SHELL"), log("  expect", exp_shell)), 100)
at(lambda: shot("shell"), 100)
# click on the preview's face (bottom) to add a second removed face
def sh2():
    f = P().feature; sel(f, face_where(f, bottom))
at(sh2, 800)
at(lambda: (log("SHELL faces after click on preview", P().faces.items), state("SHELL 2 faces")), 100)
at(lambda: (P().accept(), log("  accepted")), 700)
def sh_edit():
    from mechflow_gui import commands
    commands.edit_feature(S["doc"].getObject("Thickness"))
at(sh_edit, 800)
at(lambda: log("SHELL edit loaded", P().faces.items, P().thick.value(), P().outward.isChecked()), 100)
at(lambda: P().reject(), 600)
at(lambda: log("tip", S["b"].Tip.Name), 100)
# ---- Draft on a fresh body
def setup2():
    doc = S["doc"]; b = new_body(doc, "Body2")
    sk = sketch(b, "XY_Plane", rect(50, -20, 110, 20), name="Sk2")
    pad = b.newObject("PartDesign::Pad", "Pad2"); pad.Profile = sk; pad.Length = 20
    doc.recompute(); sk.ViewObject.Visibility = False
    S["b2"] = b; S["pad2"] = pad
    S["b"].ViewObject.Visibility = False
at(setup2, 600)
def dr():
    Gui.Selection.clearSelection()
    from mechflow_gui import dressup; dressup.draft()
at(dr, 700)
def dr_pick():
    p = S["pad2"]
    sel(p, face_where(p, bottom))
at(dr_pick, 500)
def dr_faces():
    p = S["pad2"]
    for fn in faces_where(p, side):
        sel(p, fn)
at(dr_faces, 600)
at(lambda: (log("DRAFT neutral", P().neutral.items, "faces", P().faces.items), P().angle.setValue(5)), 800)
at(lambda: state("DRAFT 5deg"), 100)
at(lambda: shot("draft"), 100)
at(lambda: P().reverse.setChecked(True), 700)
at(lambda: state("DRAFT reversed"), 100)
at(lambda: (P().accept(), log("  accepted")), 700)
def dr_edit():
    from mechflow_gui import commands
    commands.edit_feature(S["doc"].getObject("Draft"))
at(dr_edit, 800)
at(lambda: log("DRAFT edit loaded", P().neutral.items, len(P().faces.items), P().angle.value(), P().reverse.isChecked()), 100)
at(lambda: P().reject(), 600)
at(lambda: log("tip2", S["b2"].Tip.Name, "vol", round(S["b2"].Tip.Shape.Volume,1), "box", 60*40*20), 100)
run()
