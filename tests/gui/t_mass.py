import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Mass Properties of a weldment part / assembly, and a scaled drawing
# (found building a 6000 l bunker tank: views of a 1:20 drawing were 2 m off
# the sheet, and Mass Properties only weighed the first selected object).
from h import *
import Part
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Frame"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    sk = sketch(b, "XY_Plane", rect(0, 0, 1000, 1000))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = 10
    doc.recompute(); sk.ViewObject.Visibility = False
    from mechflow_gui import material, weldments as w
    material.set_material(b, "Structural steel S275", 7850.0)
    lay = doc.addObject("Sketcher::SketchObject", "Legs")
    lay.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
    lay.addGeometry(Part.LineSegment(V(50, 0, 0), V(50, -1500, 0)))
    doc.recompute()
    m = w.make("SHS-H", "100x100x6.3", [(lay, [])]); S["m"] = m
    lay.ViewObject.Visibility = False
    doc.recompute()
    part = doc.addObject("App::Part", "Part"); part.addObject(b); part.addObject(m); S["part"] = part
    doc.recompute()
at(setup, 1500)


def mass():
    from mechflow_gui import material, commands
    plate = 1000 * 1000 * 10 * 1e-9 * 7850
    for tag, objs in (("body", [S["b"]]), ("body+member", [S["b"], S["m"]]), ("part", [S["part"]])):
        items = material.mass_items(objs)
        assert all(d for _l, _s, _m, d in items), f"{tag}: a solid has no density {items}"
        kg = commands.mass_summary(items)[0]
        log("mass", tag, len(items), "solids", round(kg, 2), "kg")
        if tag == "body":
            assert abs(kg - plate) < 0.01, kg
        else:
            assert kg > plate + 20, f"{tag}: the member wasn't weighed ({kg})"
            S.setdefault("kg", kg)
            assert abs(kg - S["kg"]) < 1e-6, "Part total differs from body+member"
at(mass, 600)


def drawing():
    from mechflow_gui import drawings
    drawings.SheetDialog.exec = lambda self: (self.list.setCurrentItem(
        self.list.findItems("A4 (ISO) - Landscape", drawings._match())[0]), True)[1]
    Gui.Selection.clearSelection(); sel(S["b"]); Gui.Selection.addSelection(S["m"])
    S["page"] = drawings.make_drawing()
at(drawing, 800)


def check_views():
    from mechflow_gui import drawings
    p = S["page"]
    drawings.wait_for_views(p, 30)
    st = drawings._view_state(p)
    log("scale", p.Scale, "views", st)
    assert p.Scale < 0.2, p.Scale
    for name, n, x, y in st:
        assert n > 0, f"{name} has no lines"
        assert abs(x) < 300 and abs(y) < 300, f"{name} is off the sheet ({x}, {y})"
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (OUT + "t_mass.pdf", "PDF"))
    Gui.Selection.clearSelection(); sel(p)
    drawings.save_pdf()
    log("pdf", os.path.getsize(OUT + "t_mass.pdf"))
at(check_views, 3000)
at(lambda: shot("mass_drawing"), 500)
run()
