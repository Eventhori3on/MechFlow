import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Supplier Pack: drawings (incl. exploded view), STEP, DXF flats, BOM and
# a zip from one call; Exploded View toggles the 3D model.
from h import *
import Part
V = App.Vector
S = {}


def part_doc(name, w, d, h, holes):
    doc = App.newDocument(name)
    b = new_body(doc, "Body")
    sk = sketch(b, "XY_Plane", rect(0, 0, w, d))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = h
    doc.recompute(); sk.ViewObject.Visibility = False
    if holes:
        hs = sketch(b, "XY_Plane", [circle(x, y, 6) for x, y in holes], name="Holes")
        pk = b.newObject("PartDesign::Pocket", "Holes"); pk.Profile = hs; pk.Type = "ThroughAll"
        pk.Reversed = True
        doc.recompute(); hs.ViewObject.Visibility = False
    from mechflow_gui import material
    material.set_material(b, "Structural steel S275", 7850.0)
    doc.recompute()
    doc.saveAs(OUT + name + "_sup.FCStd")
    return doc, b


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetString("prefAuthor", "Tester")
    S["base"] = part_doc("Base", 400, 300, 20, [(50, 50), (350, 50), (50, 250), (350, 250)])
    S["post"] = part_doc("Post", 80, 80, 300, [])
    from mechflow_gui import assembly
    a = assembly.new_assembly(); S["asm"] = a; a.Label = "Stand"
    a.Document.saveAs(OUT + "Stand_sup.FCStd")
    for key, (doc, b), pl in (("lb", S["base"], App.Placement()),
                              ("lp", S["post"], App.Placement(V(160, 110, 20), App.Rotation()))):
        l = a.newObject("App::Link", doc.Name); l.LinkedObject = b; l.Placement = pl; S[key] = l
    a.Document.saveAs(OUT + "Stand_sup.FCStd")
    a.Document.recompute()
at(setup, 1500)


def pack():
    import zipfile
    from mechflow_gui import supplier_pack as sp
    folder = OUT + "Stand - Supplier Pack"
    import shutil
    shutil.rmtree(folder, ignore_errors=True)
    done = sp.make(S["asm"], folder, sheet="A3 (ISO) - Landscape")
    S["done"] = done
    log("pdf", done.get("pdf"))
    log("step", done.get("step"))
    log("dxf", done.get("dxf"))
    log("lists", done.get("lists"), "zip", os.path.basename(done.get("zip", "")))
    assert len(done["pdf"]) == 4, "assembly, exploded, 2 parts"
    assert any("Exploded" in p for p in done["pdf"])
    assert len(done["step"]) == 3
    assert [d[1:3] for d in done["dxf"]] == [(20.0, 1)], "the base plate only (the post is a block)"
    dxf = open(os.path.join(folder, "DXF", done["dxf"][0][0])).read()
    assert dxf.count("CIRCLE") == 4 and dxf.count("LINE") == 4, "outline and 4 holes"
    assert done["dxf"][0][3] == "400 x 300"
    z = zipfile.ZipFile(done["zip"]).namelist()
    log("zip entries", len(z))
    assert any(n.endswith("BOM.csv") for n in z) and any(n.endswith(".dxf") for n in z)
    ex = done["pages"][1]
    balloons = [v for v in ex.Views if v.TypeId == "TechDraw::DrawViewBalloon"]
    assert len(balloons) == 2
    g = S["asm"].Document.getObject("ExplodedView")
    moved = [round(Part.getShape(l).BoundBox.ZMin) for l in g.Group]
    log("exploded moves", moved)
    assert sorted(moved)[0] == 0 and sorted(moved)[1] > 20 + 50, "base stays, post lifts off"
    from mechflow_gui import drawing_pack as dp
    va = [v for v in done["pages"][0].Views if v.TypeId == "TechDraw::DrawViewPart"][0]
    ve = [v for v in ex.Views if v.TypeId == "TechDraw::DrawViewPart"][0]
    ha = dp._view_extent(va); he = dp._view_extent(ve)
    log("view heights", round(ha[3] - ha[2]), round(he[3] - he[2]))
    assert he[3] - he[2] > ha[3] - ha[2] + 40, "the exploded view is taller"
at(pack, 1500)


def show_exploded():
    from mechflow_gui import drawings
    drawings._open(S["done"]["pages"][1])
at(show_exploded, 500)


def still_mechflow():
    wb = Gui.activeWorkbench().name()
    log("workbench after opening the sheet", wb)
    assert wb == "MechFlowWorkbench", wb
at(still_mechflow, 800)
at(lambda: shot("supplier_exploded_sheet"), 2500)


def toggle3d():
    from mechflow_gui import exploded
    Gui.setActiveDocument(S["asm"].Document.Name)
    mw = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    for w in mw.subWindowList():
        if w.windowTitle().startswith("Stand_sup"):
            mw.setActiveSubWindow(w)
    on = exploded.toggle(S["asm"])
    log("exploded on", on, "asm visible", S["asm"].ViewObject.Visibility)
    d = S["asm"].Document
    log("vis", [(o.Name, o.ViewObject.Visibility, o.Visibility) for o in d.getObject("ExplodedView").Group],
        "asm", S["asm"].ViewObject.Visibility, [(c.Name, c.ViewObject.Visibility) for c in S["asm"].Group[:4]])
    log("group", [o.Name for o in d.getObject("ExplodedView").Group],
        "links", [(o.Name, [p.Name for p in o.InList]) for o in d.Objects if o.Name.startswith("Exploded0") or o.Name == "Exploded"])
    assert on is True and not S["asm"].ViewObject.Visibility
at(toggle3d, 800)
at(lambda: shot("supplier_exploded_3d"), 1500)


def again():
    # a second pack reuses the sheets (no duplicates) and the exploded view
    # still has its parts after Exploded View remade them
    from mechflow_gui import supplier_pack as sp
    from mechflow_gui import drawing_pack as dp
    done = sp.make(S["asm"], OUT + "Stand - Supplier Pack", step=False, dxf=False, zip_it=False,
                   sheet="A3 (ISO) - Landscape")
    labels = sorted(p.Label for d in App.listDocuments().values() for p in d.Objects
                    if p.TypeId == "TechDraw::DrawPage")
    log("pages after second pack", labels)
    assert len(labels) == len(set(labels)) == 4, labels
    ex = [p for p in done["pages"] if "Exploded" in p.Label][0]
    v = [x for x in ex.Views if x.TypeId == "TechDraw::DrawViewPart"][0]
    log("exploded view sources", len(v.Source))
    assert len(v.Source) == 2
at(again, 1000)


def back():
    from mechflow_gui import exploded
    off = exploded.toggle(S["asm"])
    log("exploded off", off, "asm visible", S["asm"].ViewObject.Visibility)
    assert off is False and S["asm"].ViewObject.Visibility
at(back, 800)
run()
