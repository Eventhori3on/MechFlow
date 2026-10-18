import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Render: finishes picked from material / type / colour, the panel, a Quick
# Render to PNG, and a 3 frame studio animation with a moving and a
# changing part.
from h import *
import Part
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Rend"); S["doc"] = doc
    b = new_body(doc, "Body")
    sk = sketch(b, "XY_Plane", rect(0, 0, 200, 120))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = 40
    doc.recompute(); sk.ViewObject.Visibility = False
    b.ViewObject.ShapeColor = (0.11, 0.30, 0.55)
    from mechflow_gui import material
    material.set_material(b, "Structural steel S275", 7850.0)
    sh = doc.addObject("Part::Feature", "Shaft")
    sh.Shape = Part.makeCylinder(15, 160, V(100, 60, 40))
    st = doc.addObject("Part::Feature", "Stainless")
    st.Shape = Part.makeBox(40, 40, 40, V(-80, 0, 0))
    st.addProperty("App::PropertyString", "MechFlowMaterial", "MechFlow")
    st.MechFlowMaterial = "Stainless steel 316"
    rope = doc.addObject("Part::Cylinder", "Rope"); rope.Radius = 5; rope.Height = 100
    rope.Placement.Base = V(250, 60, 0)
    doc.recompute()
    Gui.ActiveDocument.ActiveView.viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
    from mechflow_gui import render as R
    S["R"] = R
    log("leaves", sorted(o.Name for o in R.leaves(doc)))
    log("finishes", {o.Name: R.finish_name(o) for o in R.leaves(doc)}, "shaft colour", R._color(sh))
    assert R.finish_name(b) == "Paint (gloss)"
    assert R.finish_name(st) == "Stainless (brushed)"
    assert R.finish_name(sh) == "Steel (bare)"
    assert sorted(o.Name for o in R.leaves(doc)) == ["Body", "Rope", "Shaft", "Stainless"]
    R.set_finish([sh], "Chrome")
    assert R.finish_name(sh) == "Chrome"
at(setup, 1500)


def panel():
    R = S["R"]
    p = R.show(); S["p"] = p
    log("panel rows", p.table.rowCount())
    out = OUT + "render_test.png"
    if os.path.exists(out):
        os.remove(out)
    ok, msg = R.quick_render(S["doc"], out, 640, 400, "Studio dark", "Draft")
    log("quick render", ok, msg[-60:])
    assert ok and os.path.isfile(out)
    from PIL import Image, ImageStat
    im = Image.open(out).convert("RGB")
    stat = ImageStat.Stat(im)
    log("image", im.size, "spread", [round(x, 1) for x in stat.stddev])
    assert im.size == (640, 400) and min(stat.stddev) > 5, "the picture has something in it"
    S["p"].accept()
at(panel, 800)


def anim():
    R = S["R"]
    doc = S["doc"]
    sh, rope = doc.getObject("Shaft"), doc.getObject("Rope")
    outs = [OUT + f"anim_{i}.png" for i in range(3)]
    cam = R.camera_from_view()

    def setter(i):
        def f():
            sh.Placement = App.Placement(V(0, 0, 30 * i), App.Rotation())
            rope.Height = 100 + 60 * i
            doc.recompute()
        return f
    ok, msg = R.render_frames(doc, [(setter(i), cam, outs[i]) for i in range(3)],
                              {"width": 320, "height": 200, "supersample": 1,
                               "backdrop": "Studio light", "floor": True, "exposure": 1.2})
    log("anim", ok, msg, [os.path.isfile(f) for f in outs])
    assert ok and all(os.path.isfile(f) for f in outs)
    from PIL import Image, ImageChops
    d = ImageChops.difference(Image.open(outs[0]).convert("RGB"), Image.open(outs[2]).convert("RGB")).getbbox()
    log("frames differ", d)
    assert d is not None
at(anim, 500)


def placed():
    # a part inside a moved App::Part renders where the view shows it, and a
    # see-through part stays see-through
    from mechflow_gui import render as R
    d = App.newDocument("RenderPlaced")
    c = d.addObject("App::Part", "Carriage")
    c.Placement.Base = V(0, 0, 500)
    b = d.addObject("Part::Box", "Plate")
    c.addObject(b)
    b.ViewObject.Transparency = 70
    d.recompute()
    z = R.gshape(b).BoundBox.ZMin
    lk = R.look(b)
    log("in moved part z", z, "finish", R.finish_name(b), "opacity", lk["opacity"])
    assert abs(z - 500) < 1e-6 and lk["opacity"] < 0.5
    App.closeDocument(d.Name)
at(placed, 300)
run()
