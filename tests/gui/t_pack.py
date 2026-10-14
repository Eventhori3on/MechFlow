import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Make Drawing from Assembly: assembly sheet (BOM table + balloons) and a
# dimensioned sheet per part, all saved as PDFs.
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
    doc.saveAs(OUT + name + "_pack.FCStd")
    return doc, b


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetString("prefAuthor", "Tester")
    S["base"] = part_doc("Base", 400, 300, 20, [(50, 50), (350, 50), (50, 250), (350, 250)])
    S["post"] = part_doc("Post", 80, 80, 300, [])
    from mechflow_gui import assembly
    a = assembly.new_assembly(); S["asm"] = a; a.Label = "Stand"
    a.Document.saveAs(OUT + "Stand_pack.FCStd")
    for key, (doc, b), pl in (("lb", S["base"], App.Placement()),
                              ("lp", S["post"], App.Placement(V(160, 110, 20), App.Rotation()))):
        l = a.newObject("App::Link", doc.Name); l.LinkedObject = b; l.Placement = pl; S[key] = l
    a.Document.saveAs(OUT + "Stand_pack.FCStd")
    a.Document.recompute()
at(setup, 1500)


def pack():
    from mechflow_gui import drawing_pack as dp, bom
    rows = bom.rows(S["asm"])
    pages = dp.make_pack(S["asm"], "A3 (ISO) - Landscape", dp.AUTO)
    S["pages"] = pages
    log("pages", [(p.Document.Name, p.Label, p.Scale) for p in pages], "bom rows", rows)
    assert len(pages) == 3, "assembly + 2 part sheets"
    a = pages[0]
    balloons = sorted(int(v.Text) for v in a.Views if v.TypeId == "TechDraw::DrawViewBalloon")
    tables = [v for v in a.Views if v.TypeId == "TechDraw::DrawViewSymbol"]
    log("balloons", balloons, "tables", len(tables))
    assert balloons == list(range(1, len(rows) + 1)), "a balloon for each BOM item"
    assert tables and "ITEM NO." in tables[0].Symbol and "Base" in tables[0].Symbol
    for b in [v for v in a.Views if v.TypeId == "TechDraw::DrawViewBalloon"]:
        assert all(math.isfinite(float(x)) for x in (b.X, b.Y, b.OriginX, b.OriginY)), b.Text
    base = [p for p in pages if p.Document.Name == "Base"][0]
    dims = [v for v in base.Views if "Dim" in v.TypeId]
    vals = sorted(round(d.getRawValue(), 1) for d in dims)
    log("base dims", [(d.Type, round(d.getRawValue(), 1), d.FormatSpec) for d in dims])
    assert 400.0 in vals and 300.0 in vals, "overall sizes"
    assert any(d.Type == "Diameter" and d.FormatSpec.startswith("4×") for d in dims), "4x hole callout"
    assert 50.0 in vals, "first hole position"
    texts = base.Template.EditableTexts
    log("title block", {k: v for k, v in texts.items() if k in ("title", "sheet_number", "scale")})
    assert texts.get("sheet_number") == "2/3" or texts.get("sheet_number") == "3/3"
at(pack, 1500)


def pdfs():
    from mechflow_gui import drawing_pack as dp
    w = dp.save_all_pdf(S["pages"], OUT + "pack_pdfs")
    log("pdfs", [(os.path.basename(x), os.path.getsize(x)) for x in w])
    assert len(w) == 3 and all(os.path.getsize(x) > 10000 for x in w)
at(pdfs, 2000)
at(lambda: (S["pages"][0].ViewObject.doubleClicked(), None)[1], 500)
at(lambda: shot("pack_assembly"), 2500)
run()
