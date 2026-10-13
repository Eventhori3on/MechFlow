import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
try:
    import FastenersCmd  # the Toolbox needs the Fasteners Workbench
    HAVE_FASTENERS = True
except ImportError:
    HAVE_FASTENERS = False
import Part
V = App.Vector
S = {}
def plate():
    b = Part.makeBox(80, 40, 10)
    cut = []
    cut.append(Part.makeCylinder(4.5, 12, V(10, 20, -1)))                 # A plain 9 through
    cut.append(Part.makeCylinder(4.5, 12, V(28, 20, -1)))                 # B counterbore M8
    cut.append(Part.makeCylinder(7.0, 9, V(28, 20, 1.5)))
    cut.append(Part.makeCylinder(2.5, 8, V(46, 20, 3)))                   # C tapped M6, 7 deep
    cut.append(Part.makeCylinder(4.5, 12, V(66, 20, -1)))                 # D countersink
    cut.append(Part.makeCone(4.5, 9.0, 4.5, V(66, 20, 5.5)))
    for c in cut:
        b = b.cut(c)
    return b.removeSplitter()
def top_circle(obj, x, r, z=10):
    for i, e in enumerate(obj.Shape.Edges):
        if type(e.Curve).__name__ == "Circle" and abs(e.Curve.Radius - r) < 1e-4 \
           and abs(e.Curve.Center.x - x) < 1e-4 and abs(e.Curve.Center.z - z) < 1e-4:
            return f"Edge{i + 1}"
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"] = doc
    p = doc.addObject("Part::Feature", "Plate"); p.Shape = plate(); S["p"] = p
    doc.recompute()
    log("fasteners installed:", bool(__import__("mechflow_gui.toolbox", fromlist=["x"]).fasteners()))
at(setup, 1500)
def desc(objs):
    for o in objs:
        bb = o.Shape.BoundBox
        log(f"   {o.Label:22s} Diameter={o.Diameter} z={bb.ZMin:.2f}..{bb.ZMax:.2f} x={bb.Center.x:.1f}"
            f" Invert={getattr(o,'Invert',None)} Offset={getattr(o,'Offset',None)}")
def direct():
    from mechflow_gui import toolbox as tb
    p = S["p"]
    for tag, x, r, z, ftype, kw in (("A plain 9", 10, 4.5, 10, "ISO4762", {}),
                                    ("A bottom edge", 10, 4.5, 0, "ISO4762", {}),
                                    ("B cbore top", 28, 7.0, 10, "ISO4762", {}),
                                    ("C tapped", 46, 2.5, 10, "ISO4762", {}),
                                    ("D csink", 66, 9.0, 10, "ISO10642", {}),
                                    ("A washer+nut", 10, 4.5, 10, "ISO4017", {"washer_under_head": True, "ends": tb.ENDS[1]}),
                                    ("A flush", 10, 4.5, 10, "ISO4762", {"ends": tb.ENDS[2]})):
        sub = top_circle(p, x, r, z)
        h = tb.Hole(p, sub)
        log(tag, sub, "->", h.describe(), "size", h.size, h.kind, "grip", h.grip, "seat", h.seat_sub, "cs", h.cs_sub, "exit", h.exit_sub,
            "out(seat)", tb._outward(p, h.seat_sub))
        made = tb.place(None, ftype, h, **kw)
        desc(made)
        for o in made:
            S["doc"].removeObject(o.Name)
at(direct, 500)
# GUI flow: open the panel, click the top face, accept
def open_panel():
    from mechflow_gui import toolbox as tb
    S["panel"] = tb.toolbox()
    log("panel open", S["panel"] is not None, "type", S["panel"].current_type(),
        "tree top", S["panel"].tree.topLevelItemCount())
at(open_panel, 800)
def click_face():
    p = S["p"]
    Gui.Selection.addSelection("T", "Plate", face_where(p, lambda f: plane_face(f) and normal(f).z > 0.99 and f.BoundBox.ZMin > 9.9))
at(click_face, 600)
def show_holes():
    pn = S["panel"]
    log("holes:", [pn.hole_list.item(i).text() for i in range(pn.hole_list.count())])
    pn.search.setText("4762"); log("search 4762 ->", pn.current_type(), pn.tree.topLevelItemCount())
    shot("toolbox_panel")
at(show_holes, 400)
def acc():
    S["panel"].accept()
    fs = [o for o in S["doc"].Objects if o.TypeId == "Part::FeaturePython"]
    log("after accept", len(fs)); desc(fs)
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(acc, 900)
at(lambda: shot("toolbox_result"), 500)

OUT = os.environ.get("MF_OUT", "/tmp") + "/"
def asm_setup():
    Gui.Control.closeDialog()
    d1 = App.newDocument("TPlate"); b1 = new_body(d1, "Body")
    sk = sketch(b1, "XY_Plane", rect(0, 0, 60, 40)); p = b1.newObject("PartDesign::Pad","Pad"); p.Profile=sk; p.Length=10
    h = b1.newObject("PartDesign::SubtractiveCylinder","Hole"); h.Radius=4.5; h.Height=10; attach_xy(h, b1, 20, 20)
    h2 = b1.newObject("PartDesign::SubtractiveCylinder","Hole2"); h2.Radius=4.5; h2.Height=10; attach_xy(h2, b1, 40, 20)
    d1.recompute(); d1.saveAs(OUT + "TPlate.FCStd")
    from mechflow_gui import assembly
    a = assembly.new_assembly(); S["asm"] = a
    a.Document.saveAs(OUT + "TAsm.FCStd")
    l1 = a.newObject("App::Link", "Plate"); l1.LinkedObject = b1; l1.Label = "Plate<1>"
    l1.Placement = App.Placement(V(100, 0, 0), App.Rotation())
    a.Document.recompute(); S["l1"] = l1
    log("asm in edit", a.ViewObject.isInEditMode(), "container", __import__("mechflow_gui.toolbox", fromlist=["x"]).active_container())
at(asm_setup, 2500)
def asm_open():
    from mechflow_gui import toolbox as tb
    S["panel"] = tb.toolbox()
at(asm_open, 800)
def asm_click():
    l1, a = S["l1"], S["asm"]
    sh = l1.LinkedObject.Shape
    for i, e in enumerate(sh.Edges):
        c = e.Curve
        if type(c).__name__ == "Circle" and abs(c.Radius - 4.5) < 1e-4 and abs(c.Center.z - 10) < 1e-4:
            Gui.Selection.addSelection(a.Document.Name, a.Name, f"{l1.Name}.Edge{i+1}")
            log("  picked", c.Center, f"{l1.Name}.Edge{i+1}", "sel now", [x.SubElementNames for x in Gui.Selection.getSelectionEx("", 0)])
    import FastenerBase
    from mechflow_gui import toolbox as tb
    sels = tb.attachable_selection(a)
    log("  attachable", [(s[0].Name, s[1]) for s in sels if s])
    from mechflow_gui import toolbox as tb
    for s_ in sels:
        h = tb.Hole(s_[0], s_[1][0]); log("  hole", h.ok, h.seat_sub, h.describe())
at(asm_click, 600)
def asm_acc():
    pn = S["panel"]
    import FastenerBase
    log("asm holes:", [pn.hole_list.item(i).text() for i in range(pn.hole_list.count())])
    pn.accept()
    a = S["asm"]
    fs = [o for o in a.Group if o.TypeId == "Part::FeaturePython"]
    log("in assembly:", [o.Label for o in fs]); desc(fs)
    S["fs"] = fs
    S["l1"].Placement = App.Placement(V(100, 50, 5), App.Rotation())
    a.Document.recompute()
    log("after moving the plate by (0,50,5):"); desc(fs)
    log("y centre", [round(o.Shape.BoundBox.Center.y, 2) for o in fs])
    fs[0].Length = "25"; a.Document.recompute()
    log("after changing length:", [o.Label for o in fs])
    # A second plate (another instance) and a washer + nut set
    l2 = a.newObject("App::Link", "Plate"); l2.LinkedObject = S["l1"].LinkedObject; l2.Label = "Plate<2>"
    l2.Placement = App.Placement(V(100, 0, 40), App.Rotation()); a.Document.recompute()
    from mechflow_gui import bom
    data = bom.bill_of_materials()
    log("MechFlow BOM:", data)
    sh = [o for o in a.Document.Objects if o.TypeId == "Spreadsheet::Sheet"][0]
    log("sheet", sh.Label, [[sh.getContents(f"{c}{r}") for c in "ABCD"] for r in range(1, 5)])
    # running it again updates the same sheet
    bom.bill_of_materials()
    log("sheets after second run", len([o for o in a.Document.Objects if o.TypeId == "Spreadsheet::Sheet"]))
    from mechflow_gui import command_manager as cm
    log("commands", [c in Gui.listCommands() for c in ("MechFlow_Toolbox", "MechFlow_BOM")])
at(asm_acc, 900)
def later():
    from mechflow_gui import bom
    bom._last[0].grab().save(SHOTS + "bom_dialog.png")
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(later, 800)
at(lambda: shot("asm_result"), 600)
if not HAVE_FASTENERS:
    Q.clear()
    at(lambda: log("SKIP: the Fasteners Workbench is not installed"), 100)
run()
