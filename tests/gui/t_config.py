import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Configurations / Design Table: three tank sizes in one part, a suppressed
# feature, switching, saving and reopening, and an assembly that follows.
from h import *
import Part, Sketcher
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("TankCfg"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    sk = sketch(b, "XY_Plane", [], name="Base")
    pts = [V(0, 0, 0), V(1000, 0, 0), V(1000, 1000, 0), V(0, 1000, 0)]
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", 1))
    sk.addConstraint(Sketcher.Constraint("Vertical", 3))
    sk.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
    # name the size dimensions, like Smart Dimension + Name
    sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 1000))
    sk.renameConstraint(len(sk.Constraints) - 1, "Width")
    sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 1000))
    sk.renameConstraint(len(sk.Constraints) - 1, "Depth")
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = 1000
    doc.recompute(); sk.ViewObject.Visibility = False
    top = face_where(pad, lambda f: plane_face(f) and normal(f).z > 0.99)
    sel(pad, top)
    from mechflow_gui import dressup; dressup.shell()
    p = P(); p.thick.setValue(8); p.accept()
    S["shell"] = b.Tip
    hole = b.newObject("PartDesign::SubtractiveCylinder", "Drain"); hole.Radius = 25; hole.Height = 30
    hole.Placement = App.Placement(V(400, 400, -10), App.Rotation())
    doc.recompute()
    S["drain"] = hole
    log("built", b.Shape.isValid(), b.Shape.BoundBox, "has Suppressed", hasattr(hole, "Suppressed"))
at(setup, 1500)


def table():
    from mechflow_gui import configurations as c
    doc = S["doc"]
    keys = [k for k, d, v in c.parameters(doc)]
    log("parameters offered", keys[:20])
    for k in ("Base.Width", "Base.Depth", "Pad.Length", S["shell"].Name + ".Value"):
        assert k in keys, k
        c.add_parameter(doc, k)
    if f"{S['drain'].Name}.Suppressed" in keys:
        c.add_parameter(doc, f"{S['drain'].Name}.Suppressed")
    c.add_configuration(doc, "6000 l")
    c.add_configuration(doc, "3000 l", {"Base.Width": 1450, "Base.Depth": 1450, "Pad.Length": 1450})
    c.add_configuration(doc, "10000 l", {"Base.Width": 2170, "Base.Depth": 2170, "Pad.Length": 2170,
                                         S["shell"].Name + ".Value": 10,
                                         f"{S['drain'].Name}.Suppressed": True})
    sh = c.table(doc)
    log("configurations", c.configurations(sh), "columns", c.columns(sh), "active", sh.ActiveConfiguration)
    assert c.configurations(sh) == ["6000 l", "3000 l", "10000 l"]
at(table, 800)


def inside_litres():
    bb = S["b"].Shape.BoundBox
    t = S["b"].Shape.Volume
    outer = bb.XLength * bb.YLength * bb.ZLength
    return bb, (outer - t) / 1e6


def switch(name, want):
    def f():
        from mechflow_gui import configurations as c
        errs = c.activate(S["doc"], name)
        bb, litres = inside_litres()
        log(f"{name}: errors {errs}, size {bb.XLength:.0f} x {bb.YLength:.0f} x {bb.ZLength:.0f}, "
            f"~{litres:.0f} l inside, drain suppressed {getattr(S['drain'], 'Suppressed', None)}")
        assert not errs, errs
        assert abs(bb.XLength - want) < 1e-3, bb
    return f


at(switch("3000 l", 1450), 800)
at(switch("10000 l", 2170), 800)
at(switch("6000 l", 1000), 800)


def update():
    from mechflow_gui import configurations as c
    doc = S["doc"]
    c.activate(doc, "3000 l")
    S["doc"].getObject("Pad").Length = 1500
    doc.recompute()
    c.update_from_model(doc)
    vals = c.row_values(c.table(doc), "3000 l")
    log("3000 l row after saving the model", vals)
    assert abs(float(vals["Pad.Length"]) - 1500) < 1e-6
at(update, 800)


def reopen():
    d = S["doc"]; d.saveAs(OUT + "cfg_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "cfg_t.FCStd"); S["doc"] = d; S["b"] = d.getObject("Body")
    S["drain"] = d.getObject("Drain")
    from mechflow_gui import configurations as c
    sh = c.table(d)
    log("reopened: active", sh.ActiveConfiguration, c.configurations(sh))
    errs = c.activate(d, "10000 l")
    assert not errs and abs(S["b"].Shape.BoundBox.XLength - 2170) < 1e-3
at(reopen, 800)


def panel():
    from mechflow_gui import configurations as c
    p = c.show(); S["p"] = p
    items = [p.list.item(i).text() for i in range(p.list.count())]
    log("panel list", items, "params", p.params.count())
    assert any("(active)" in t and t.startswith("10000 l") for t in items)
    p.list.setCurrentRow(1); p._activate()
    log("panel activate:", p.msg.text())
    assert abs(S["b"].Shape.BoundBox.XLength - 1450) < 1e-3
    p.reject()
    Gui.SendMsgToActiveView("ViewFit")
at(panel, 800)
at(lambda: shot("config"), 600)
run()
