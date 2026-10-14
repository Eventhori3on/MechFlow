import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Pipe specs and size changes: a route off a DN200 nozzle following a spec
# (material on the parts and in the BOM), a size change part way along a
# straight (reducer in the run) and one after an elbow, a big step (two
# reducers), Change Pipe Size from a selected pipe, a library part with
# DN100 / DN80 ends changing the size after it, editing the spec moves the
# route with it; every pipe end meets a part of its own size.
from h import *
import Part, shutil, json
V = App.Vector
S = {}
LIB = OUT + "sizes-library/"
SPECS = OUT + "sizes-specs/"
for d in (LIB, SPECS):
    shutil.rmtree(d, ignore_errors=True)
os.environ["MF_ROUTING_LIBRARY"] = LIB
os.environ["MF_PIPE_SPECS"] = SPECS


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Sizes"); S["doc"] = doc
    b = new_body(doc, "Tank")
    box = b.newObject("PartDesign::AdditiveBox", "Box"); box.Length = 1000; box.Width = 1000; box.Height = 1000
    inner = b.newObject("PartDesign::SubtractiveBox", "Inside"); inner.Length = 980; inner.Width = 980; inner.Height = 980
    inner.Placement = App.Placement(V(10, 10, 10), App.Rotation())
    doc.recompute()
    from mechflow_gui import nozzle, stdparts
    nz = nozzle.make(b, V(1000, 500, 400), V(1, 0, 0), "EN 10220", "DN200", "", 200)
    fl = nozzle.add_flange(nz, "EN1092-1-11", "PN16")[0]
    doc.recompute()
    face, n = stdparts._face_frame(fl)
    f = stdparts.flange_info(fl.StdType, fl.Size, fl.Rating)
    best = None
    for i, e in enumerate(fl.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(2 * c.Radius - f["face"]) < 1e-3:
            dd = (c.Center - face).Length
            if best is None or dd < best[1]:
                best = (f"Edge{i+1}", dd)
    S["fl"], S["edge"], S["face"] = fl, best[0], face
    from mechflow_gui import sketch3d
    sk = sketch3d.make(None, "Line 101")
    ed = sketch3d.Editor(sk)
    ed.start(face, (fl, best[0]))
    ed.line_along(V(1, 0, 0), 1400)          # Edge1
    ed.line_along(V(1, 0, 0), 1600)          # Edge2: straight on (same run)
    ed.line_along(V(0, 0, 1), 1500)          # Edge3: up
    ed.line_along(V(0, 1, 0), 2400)          # Edge4: across
    ed.save()
    doc.recompute()
    S["sk"] = sk
    log("flange", fl.Size, "sketch edges", len(sk.Shape.Edges))
at(setup, 1500)


from mechflow_gui import edge_curve as _ec


def kinds(r):
    k = {}
    for o in r.Parts:
        t = getattr(o, "StdType", type(getattr(o, "Proxy", None)).__name__)
        sz = getattr(o, "Size", "")
        key = f"{t} {sz}" if t.endswith(("PIPE", "RED")) or "90" in t else t
        k[key] = k.get(key, 0) + 1
    return k


def joints_ok(r):
    """Every pipe end sits on another part's circle of the same radius."""
    circles = []
    for o in r.Parts:
        for e in o.Shape.Edges:
            c = _ec(e)
            if type(c).__name__ == "Circle":
                circles.append((o.Name, V(c.Center), round(c.Radius, 2)))
    bad = []
    for o in r.Parts:
        if not getattr(o, "StdType", "").endswith("PIPE"):
            continue
        rad = None
        ends = []
        for e in o.Shape.Edges:
            c = _ec(e)
            if type(c).__name__ == "Circle":
                if rad is None or c.Radius > rad:
                    rad = c.Radius
        for e in o.Shape.Edges:
            c = _ec(e)
            if type(c).__name__ == "Circle" and abs(c.Radius - rad) < 1e-6:
                ends.append(V(c.Center))
        for p in ends:
            if not any(n != o.Name and abs(rr - round(rad, 2)) < 0.02 and (cc - p).Length < 0.05
                       for n, cc, rr in circles):
                bad.append((o.Label, tuple(round(x) for x in p)))
    return bad


def route():
    from mechflow_gui import routing, pipespec
    routing.install()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(S["doc"].Name, S["sk"].Name)
    p = routing.route_pipe(); S["p"] = p
    log("specs offered", [p.spec.itemText(i) for i in range(p.spec.count())][:4])
    log("size at the start from the flange:", p.size.currentText())
    assert p.size.currentText() == "DN200"
    p.spec.setCurrentText("EN carbon steel PN16")
    r = p.route; S["r"] = r
    log("spec", r.Spec, "material", r.Material, "| err", p.error.isVisible() and p.error.text())
    assert r.Spec == "EN carbon steel PN16" and r.Material == "Carbon steel P235GH"
    assert not p.error.isVisible(), p.error.text()
    k = kinds(r)
    log("one size:", k)
    assert all("DN200" in x for x in k if "PIPE" in x)
    # size change on the second line (straight on from the first): reducer in the run
    key2 = f"{S['sk'].Name}:Edge2"
    routing.set_size_change(r, key2, "DN150")
    p._apply()
    k = kinds(r)
    log("DN150 from line 2:", k, "| err", p.error.isVisible() and p.error.text())
    assert k.get("EN10253-RED DN200 x DN150") == 1
    assert k.get("EN10253-90-3D DN150") == 2, "both elbows after the change are DN150"
    red = [o for o in r.Parts if getattr(o, "StdType", "").endswith("RED")][0]
    log("reducer starts at x", round(red.Placement.Base.x - S["face"].x), "(line 2 starts at 1400)")
    assert abs(red.Placement.Base.x - S["face"].x - 1400) < 1e-6
    bad = joints_ok(r)
    log("open pipe ends", bad)
    assert not bad
    log("changes list", [p.changes.item(i).text() for i in range(p.changes.count())])
    assert p.changes.count() == 1
    p.accept()
at(route, 1500)


def right_click():
    from mechflow_gui import routing
    r = S["r"]
    # the pipe after the first elbow (going up): select it, Change Pipe Size -> DN80
    up = [o for o in r.Parts if getattr(o, "StdType", "").endswith("PIPE") and
          o.Placement.Rotation.multVec(V(0, 0, 1)).z > 0.99][0]
    log("selected", up.Label, "line", up.RouteLine)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(S["doc"].Name, up.Name)
    hit = routing.selected_route_pipe()
    assert hit and hit[0] is r
    d = routing.ChangeSizeDialog(r, hit[1])
    d.combo.setCurrentText("DN80")
    ok = d.apply()
    k = kinds(r)
    log("DN80 up the riser:", ok, k)
    assert ok
    reds = sorted(x for x in k if "RED" in x)
    log("reducers", reds)
    # DN150 -> DN80 is more than one standard reducer: two in a row, after the elbow
    assert sum(k[x] for x in reds) == 3, reds
    assert k.get("EN10253-90-3D DN80") == 1 and k.get("EN10253-90-3D DN150") == 1
    bad = joints_ok(r)
    log("open pipe ends", bad)
    assert not bad
    flanges = [o for o in r.Parts if getattr(o, "StdType", "") == "EN1092-1-11"]
    log("free end flange", [f.Size for f in flanges])
    assert any(f.Size == "DN80" for f in flanges)
    # back off: remove the DN80 change
    routing.set_size_change(r, hit[1], None)
    routing.build(r)
    log("after removing it:", sorted(x for x in kinds(r) if "RED" in x))
at(right_click, 1000)


def two_size_part():
    # a reducing control valve with DN100 and DN80 flanged ends
    from mechflow_gui import inline, stdparts, routing
    d = App.newDocument("RedValve")
    def flange(x, size, sign):
        info = stdparts.flange_info("EN1092-1-11", size, "PN16")
        f = Part.makeCylinder(info["OD"] / 2, 20, V(x, 0, 0), V(sign, 0, 0))
        return f
    body = Part.makeCylinder(80, 260, V(-130, 0, 0), V(1, 0, 0)).fuse(Part.makeSphere(110))
    shape = body.fuse(flange(-130, "DN100", -1)).fuse(flange(130, "DN80", 1))
    shape = shape.fuse(Part.makeCylinder(25, 220, V(0, 0, 100)))
    o = d.addObject("Part::Feature", "RedValve"); o.Shape = shape
    d.recompute()
    edges = {}
    from mechflow_gui import edge_curve
    for i, e in enumerate(o.Shape.Edges):
        c = edge_curve(e)
        if type(c).__name__ == "Circle" and abs(c.Center.x) > 140:
            edges.setdefault(round(c.Center.x), []).append((c.Radius, f"Edge{i+1}"))
    a = max(edges[-150])[1]                      # DN100 end, outer circle
    b = max(edges[150])[1]                       # DN80 end
    p = inline.author_component()
    assert p.add_port(o, a) and p.add_port(o, b)
    p.name.setText("Reducing control valve DN100 x DN80")
    p.accept()
    items = {n: path for n, path, _i in inline.library_items()}
    info = json.load(open(items["Reducing control valve DN100 x DN80"]))
    log("ports", [(q["name"], q.get("dia")) for q in info["ports"]])
    S["redvalve"] = items["Reducing control valve DN100 x DN80"]
    App.setActiveDocument(S["doc"].Name)
    r = S["r"]
    # make the run DN100 from line 2 on, then put the valve on the top run (line 4)
    routing.set_size_change(r, f"{S['sk'].Name}:Edge2", "DN100")
    routing.build(r)
    pv = inline.valves_and_instruments(); S["pv"] = pv
    face = S["face"]
    top = face + V(3000, 1200, 1500)
    c = pv.place_at(r, top, library=S["redvalve"])
    log("placed", c.Label, "| err", pv.error.isVisible() and pv.error.text())
    assert pv.error.isHidden(), pv.error.text()
    sizes = inline.port_sizes(c, "EN", "PN16")
    log("port sizes", sizes)
    assert sizes == ("DN100", "DN80")
    k = kinds(r)
    log("with the valve:", k)
    after = [o for o in r.Parts if getattr(o, "StdType", "") == "EN10220-PIPE" and o.Size == "DN80"]
    assert after, "pipe after the valve is DN80"
    comp_fl = sorted(o.Size for o in r.Parts if getattr(o, "StdType", "") == "EN1092-1-11")
    log("flanges", comp_fl)
    assert "DN80" in comp_fl and "DN100" in comp_fl
    bolts = [o for o in r.Parts if "4014" in o.Label or "4017" in o.Label]
    log("bolts", len(bolts), "(DN200 start 12, valve ends 8 + 8)")
    assert len(bolts) == 28
    bad = joints_ok(r)
    log("open pipe ends", bad)
    assert not bad
    # turned round, it would take DN80 in on a DN100 pipe: refused, stays as it was
    pv._select(c)
    pv.reverse.setChecked(True)
    pv._rebuild()
    log("reversed:", not pv.error.isHidden(), pv.error.text()[:140])
    assert not pv.error.isHidden() and not c.Reverse
    pv.accept()
    # a panel closed without OK / Cancel leaves no handles behind
    from mechflow_gui import view_handles
    pv2 = inline.valves_and_instruments()
    pv2._select(c)
    Gui.Control.closeDialog()
    S["pv2"] = pv2
at(two_size_part, 1000)


def no_leftovers():
    from PySide6 import QtWidgets as QW
    boxes = [w for w in Gui.getMainWindow().findChildren(QW.QDoubleSpinBox)
             if w.objectName() == "MechFlow_ViewBox" and w.isVisible()]
    log("number boxes left in the view:", len(boxes), "| handles", S["pv2"].disc, S["pv2"].arrow)
    assert not boxes and S["pv2"].disc is None
at(no_leftovers, 1500)


def spec_edit():
    from mechflow_gui import pipespec, routing
    r = S["r"]
    # my own spec from the built-in one, PN40 and stainless; the route follows it
    sp = dict(pipespec.get("EN carbon steel PN16"))
    sp.update(name="Glenn CS PN40", rating="PN40", material="Stainless steel 1.4404 (316L)", user=True)
    pipespec.save(sp)
    pipespec.apply_to_route(r, pipespec.get("Glenn CS PN40"))
    routing.build(r)
    sp["material"] = "Duplex 1.4462"
    pipespec.save(sp)
    n = pipespec.update_routes("Glenn CS PN40")
    fl = [o for o in r.Parts if getattr(o, "StdType", "") == "EN1092-1-11"]
    mats = {getattr(o, "MechFlowMaterial", "") for o in r.Parts
            if hasattr(o, "StdType") and not o.StdType.startswith("EN1514")}
    log("routes updated", n, "| ratings", sorted({o.Rating for o in fl}), "| materials", mats)
    # (the flange mating the nozzle's PN16 flange stays PN16)
    assert n == 1 and "PN40" in {o.Rating for o in fl} and mats == {"Duplex 1.4462"}
    from mechflow_gui import bom
    from mechflow_gui import stdparts
    pipe = [o for o in r.Parts if getattr(o, "StdType", "") == "EN10220-PIPE"][0]
    row = bom._std_row(pipe)
    log("BOM row", row)
    assert "Duplex 1.4462" in row[1]
    # the editor opens and lists both
    dlg = pipespec.SpecDialog(select="Glenn CS PN40")
    names = [dlg.list.item(i).text() for i in range(dlg.list.count())]
    log("editor lists", names[:3], "... editable:", dlg.b_save.isEnabled())
    assert any(x.startswith("Glenn CS PN40") for x in names) and dlg.b_save.isEnabled()
    dlg.close()
at(spec_edit, 800)
at(lambda: (Gui.SendMsgToActiveView("ViewFit"), shot("sizes")), 800)


def reopen():
    d = S["doc"]; d.saveAs(OUT + "sizes_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "sizes_t.FCStd"); d.recompute()
    from mechflow_gui import routing
    r = [o for o in d.Objects if routing.is_route(o)][0]
    log("reopened", r.Label, r.Spec, routing.size_changes(r), "parts", len(r.Parts),
        "invalid", [o.Label for o in d.Objects if not o.isValid()])
    assert not [o for o in d.Objects if not o.isValid()]
    # opening the route's panel again keeps its size, material and spec
    before = (r.Size, r.Material, r.Spec, sorted(routing.size_changes(r).items()), len(r.Parts))
    p = routing.RoutePanel(r)
    Gui.Control.showDialog(p)
    after = (r.Size, r.Material, r.Spec, sorted(routing.size_changes(r).items()), len(r.Parts))
    log("panel reopened:", p.size.currentText(), p.material.currentText(), p.spec.currentText(),
        "| route before", before, "after", after)
    assert before == after and p.size.currentText() == r.Size and p.spec.currentText() == r.Spec
    p.reject()
at(reopen, 800)
run()
