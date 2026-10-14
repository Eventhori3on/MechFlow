import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Tools added after the bunker-tank test: Nozzle, Hole Wizard Up To Next,
# EN 10253 fittings with Outlet points, base plates, weldment part grouping.
from h import *
import Part
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Vessel"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    # a closed cylindrical vessel, R 300, 8 wall, 1000 long, axis Z
    cyl = b.newObject("PartDesign::AdditiveCylinder", "Shell"); cyl.Radius = 300; cyl.Height = 1000
    hol = b.newObject("PartDesign::SubtractiveCylinder", "Inside"); hol.Radius = 292; hol.Height = 984
    hol.Placement = App.Placement(V(0, 0, 8), App.Rotation())
    doc.recompute()
    assert b.Shape.isValid() and len(b.Shape.Shells) == 2, "vessel isn't a closed shell"
    from mechflow_gui import nozzle
    S["p"] = nozzle.create()
at(setup, 1500)


def pick_side():
    # click the curved side at x = -300, z = 400 (the nozzle points -X)
    b = S["b"]
    side = face_where(b.Tip, lambda f: type(f.Surface).__name__ == "Cylinder" and f.Surface.Radius > 299)
    Gui.Selection.addSelection("Vessel", b.Tip.Name, side, -300, 0, 400)
at(pick_side, 800)


def check_side():
    p = S["p"]; f = p.feature
    assert f is not None, "no nozzle made from the click"
    log("nozzle", f.Label, "valid", f.isValid(), "dir", f.Direction, "end", f.PipeEnd, "err", p.error.isVisible())
    assert f.isValid() and not p.error.isVisible()
    end = V(f.PipeEnd)
    assert abs(end.x + 450) < 1e-3 and abs(end.z - 400) < 1e-3, end
    sh = S["b"].Shape
    # bore open into the vessel, the far wall untouched
    assert not sh.isInside(V(-296, 0, 400), 1e-6, True), "wall not bored"
    assert sh.isInside(V(296, 0, 400), 1e-6, True), "far wall bored"
    assert sh.isInside(V(-400, 0, 400 + 44.45 - 1.5), 1e-6, True), "no pipe wall"
    p.standout.setValue(200)
    log("standout 200 end", f.PipeEnd)
    assert abs(V(f.PipeEnd).x + 500) < 1e-3
    p.accept()
    fl = [o for o in S["doc"].Objects if getattr(o, "StdType", "") == "EN1092-1-11"]
    log("flange", [o.Label for o in fl])
    assert len(fl) == 1, "no weld neck flange on the nozzle"
    bb = fl[0].Shape.BoundBox
    assert abs(bb.XMax + 500) < 1e-3, f"flange not on the pipe end {bb}"
    S["flange"] = fl[0]
    # edit the nozzle: the flange follows (standout, then size)
    f.Standout = 260
    S["doc"].recompute()
    bb = fl[0].Shape.BoundBox
    log("after standout 260: flange x max", round(bb.XMax, 2), "nozzle ref", getattr(fl[0], "NozzleRef", None) and fl[0].NozzleRef.Label)
    assert abs(bb.XMax + 560) < 1e-3, bb
    f.Size = "DN100"
    S["doc"].recompute()
    log("after DN100:", fl[0].Label)
    assert fl[0].Size == "DN100" and abs(fl[0].Shape.BoundBox.XMax + 560) < 1e-3
    f.Size = "DN80"; f.Standout = 200
    S["doc"].recompute()
at(check_side, 1200)


def top_nozzle():
    from mechflow_gui import nozzle
    o = nozzle.make(S["b"], V(150, 0, 1000), V(0, 0, 1), "ASME B36.10M", "NPS 2", "Sch 40", 100)
    log("top nozzle", o.Label, o.isValid(), o.PipeEnd)
    assert o.isValid() and abs(V(o.PipeEnd).z - 1100) < 1e-3
    assert not S["b"].Shape.isInside(V(150, 0, 996), 1e-6, True), "top not bored"
    assert S["b"].Shape.isInside(V(150, 0, 4), 1e-6, True), "bottom bored"
    S["doc"].recompute()
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(top_nozzle, 800)
at(lambda: shot("nozzle"), 600)


def fittings():
    from mechflow_gui import stdparts
    _b, sub = __import__("mechflow_gui.nozzle", fromlist=["x"]).end_edge(
        [o for o in S["b"].Group if o.Label.startswith("Nozzle NPS")][0])
    # EN 10253 elbow on the flange-free top nozzle? use a pipe then an elbow
    pipe = stdparts.place(None, "EN10220-PIPE", S["flange"], None, "DN80", None, 300) if False else None
    out = []
    for t in ("EN10253-90-3D", "EN10253-90-5D", "EN10253-45-3D", "EN10253-TEE", "EN10253-RED", "EN10253-CAP"):
        sz = stdparts.default_size(t)
        sh = stdparts.shape_for(t, sz, "")
        out.append((stdparts.designation(t, sz, ""), sh.isValid(), round(sh.Volume)))
        assert sh.isValid() and sh.Volume > 0, t
    log("EN 10253:", out)
    d = stdparts.designation("EN10253-90-3D", "DN80", "")
    assert "88.9x3.2" in d, d
    # elbow on the top nozzle's end, outlet aimed +Y
    noz = [o for o in S["b"].Group if o.Label.startswith("Nozzle NPS")][0]
    body, sub = __import__("mechflow_gui.nozzle", fromlist=["x"]).end_edge(noz)
    el = stdparts.place(None, "ASMEB16.9-90LR", body, sub, "NPS 2", "Sch 40")[0]
    ok = stdparts.aim(el, V(0, 1, 0))
    S["doc"].recompute()
    bb = el.Shape.BoundBox
    log("elbow aimed +Y:", ok, "spin", float(el.Spin), "bb y", round(bb.YMin), round(bb.YMax), "x", round(bb.XMin), round(bb.XMax))
    assert ok and bb.YMax > 70 and bb.YMin > -40, "elbow not turned towards +Y"
at(fittings, 800)


def hollow_box():
    doc = App.newDocument("Box"); S["box"] = doc
    b = new_body(doc, "Body"); S["bb"] = b
    sk = sketch(b, "XY_Plane", rect(-200, -200, 200, 200))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = 400
    doc.recompute(); sk.ViewObject.Visibility = False
    top = face_where(pad, lambda f: plane_face(f) and normal(f).z > 0.99)
    sel(pad, top)
    from mechflow_gui import dressup; dressup.shell()
    p = P(); p.thick.setValue(8); p.accept()
    # lid
    sk2 = sketch(b, "XY_Plane", rect(-200, -200, 200, 200), offset=App.Placement(V(0, 0, 400), App.Rotation()), name="Lid")
    pad2 = b.newObject("PartDesign::Pad", "LidPad"); pad2.Profile = sk2; pad2.Length = 8
    doc.recompute(); sk2.ViewObject.Visibility = False
    from mechflow_gui import hole_wizard
    orig = hole_wizard.HolePanel.__init__

    def init(self, *a, **k):
        S["hp"] = self
        orig(self, *a, **k)
    hole_wizard.HolePanel.__init__ = init
    Gui.Selection.clearSelection()
    hole_wizard.create()
at(hollow_box, 1000)


def click(x):
    def f():
        p = S["hp"]
        base = S["bb"].Tip if p.hole is None else p.base
        top = face_where(base, lambda f: plane_face(f) and normal(f).z > 0.99)
        Gui.Selection.addSelection("Box", base.Name, top, x, 0, 408)
    return f
for i, x in enumerate((-100, 0, 100)):
    at(click(x), 800 if not i else 300)


def holes_set():
    p = S["hp"]
    ends = [p.end.itemText(i) for i in range(p.end.count())]
    log("end conditions", ends)
    assert "Up To Next" in ends
    p.size.setCurrentText("M12"); p.end.setCurrentText("Up To Next")
at(holes_set, 1500)


def holes_ok():
    p = S["hp"]; h = p.hole
    log("up to next depth", float(h.Depth), "valid", h.isValid(), "drill", h.DrillPoint)
    sh = S["bb"].Shape
    gp = p.sketch.getGlobalPlacement()
    log("centres", [gp.multVec(g.Center) for g in p.sketch.Geometry if type(g).__name__ == "Circle"],
        "vol base", round(h.BaseFeature.Shape.Volume), "vol hole", round(h.Shape.Volume), "tip", S["bb"].Tip.Name,
        "inside hole shape", h.Shape.isInside(V(0, 0, 404), 1e-6, True), "bb", sh.BoundBox)
    assert h.isValid() and 8 < float(h.Depth) < 10, float(h.Depth)
    assert not sh.isInside(V(0, 0, 404), 1e-6, True), "lid not drilled"
    assert sh.isInside(V(0, 0, 4), 1e-6, True), "bottom drilled too"
    p.accept()
    S["box"].recompute()
    assert S["bb"].Tip.MechFlowUpToNext
    S["hole"] = S["bb"].Tip
    from mechflow_gui import hole_wizard
    hole_wizard.install()
    S["box"].getObject("LidPad").Length = 12        # a thicker lid
    S["box"].recompute()
at(holes_ok, 1500)


def lid_thicker():
    h = S["hole"]
    log("lid 12 mm: Up To Next depth", float(h.Depth))
    assert abs(float(h.Depth) - 12.5) < 0.01, float(h.Depth)
    assert not S["bb"].Shape.isInside(V(0, 0, 404), 1e-6, True) and not S["bb"].Shape.isInside(V(0, 0, 398), 1e-6, True)
at(lid_thicker, 1500)


def weldment():
    # legs + base plates: everything ends up in one Part with the body
    doc = S["box"]
    lay = doc.addObject("Sketcher::SketchObject", "Legs")
    lay.Placement = App.Placement(V(0, -150, 0), App.Rotation(V(1, 0, 0), 90))
    for x in (-150, 150):
        lay.addGeometry(Part.LineSegment(V(x, 0, 0), V(x, -300, 0)))
    doc.recompute()
    from mechflow_gui import weldments as w, weld_extras as we
    m = w.make("SHS-H", "100x100x6.3", [(lay, [])])
    ends = [f"Face{i+1}" for i, f in enumerate(m.Shape.Faces)
            if plane_face(f) and abs(f.BoundBox.ZMax + 300) < 1e-3 and abs(f.BoundBox.ZMin + 300) < 1e-3]
    caps = [we.make_end_cap((m, [e]), 15, None, True, (200, 200, 22, 30)) for e in ends]
    doc.recompute()
    parts = [o for o in doc.Objects if o.TypeId == "App::Part"]
    log("parts", [(p.Label, sorted(c.Label for c in p.Group)) for p in parts])
    assert len(parts) == 1 and parts[0].Label == "Box", parts[0].Label
    grp = parts[0].Group
    for o in [S["bb"], m, lay] + caps:
        assert o in grp, f"{o.Label} not in the part"
    bb = caps[0].Shape.BoundBox
    log("base plate", round(bb.XLength), round(bb.YLength), round(bb.ZLength), "faces", len(caps[0].Shape.Faces), caps[0].Label)
    assert abs(bb.XLength - 200) < 1e-3 and abs(bb.YLength - 200) < 1e-3 and abs(bb.ZLength - 15) < 1e-3
    assert len([f for f in caps[0].Shape.Faces if type(f.Surface).__name__ == "Cylinder"]) == 4, "anchor holes"
    log("cut list", w.cut_items(doc))
    assert any(r[0].startswith("Base plate PL15") for r in w.cut_items(doc))
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(weldment, 800)
at(lambda: shot("nozzle_box"), 600)


def reopen():
    for d in (S["doc"], S["box"]):
        d.saveAs(OUT + d.Name + "_t.FCStd")
        n = d.Name
        App.closeDocument(n)
        d2 = App.openDocument(OUT + n + "_t.FCStd"); d2.recompute()
        bad = [o.Label for o in d2.Objects if not o.isValid()]
        log("reopened", n, "invalid:", bad)
        assert not bad
at(reopen, 800)


def dished_head():
    # a nozzle and flange on a vessel's ellipsoidal head: some of its edges
    # have no usable Curve ("undefined curve type") - that used to crash
    import Part
    from mechflow_gui import nozzle
    d = App.newDocument("Dished")
    b = d.addObject("PartDesign::Body", "Body")
    cyl = b.newObject("PartDesign::AdditiveCylinder", "Shell"); cyl.Radius = 400; cyl.Height = 800
    e = b.newObject("PartDesign::AdditiveEllipsoid", "Head")
    e.Radius1 = 200; e.Radius2 = 400; e.Radius3 = 400
    e.Placement = App.Placement(App.Vector(0, 0, 800), App.Rotation())
    t = b.newObject("PartDesign::Thickness", "Hollow")
    t.Base = (cyl, ["Face3"]); t.Value = 8; t.Reversed = True
    d.recompute()
    log("hollow body valid", b.Shape.isValid(), "solids", len(b.Shape.Solids))
    n = nozzle.make(b, App.Vector(200, 0, 900), App.Vector(0, 0, 1), "EN 10220", "DN50", "", 120)
    d.recompute()
    fl = nozzle.add_flange(n, "EN1092-1-11", "PN16")[0]
    d.recompute()
    log("nozzle on the head:", n.isValid(), "| flange", fl.Label, fl.isValid())
    assert n.isValid() and fl.isValid()
at(dished_head, 800)
run()
