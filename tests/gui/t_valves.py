import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Valves and Instruments: ball, gate and butterfly valves and a pressure
# gauge on a route's pipes - the pipe splits round them with gaskets,
# flanges and bolts; turned round the pipe with the ring handle and the
# angle box; slid along with the arrow; too near a bend is refused; BOM.
from h import *
import Part, math
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Valves"); S["doc"] = doc
    b = new_body(doc, "Body")
    box = b.newObject("PartDesign::AdditiveBox", "Box"); box.Length = 600; box.Width = 600; box.Height = 600
    inner = b.newObject("PartDesign::SubtractiveBox", "Inside"); inner.Length = 584; inner.Width = 584; inner.Height = 584
    inner.Placement = App.Placement(V(8, 8, 8), App.Rotation())
    doc.recompute()
    from mechflow_gui import nozzle, stdparts
    nz = nozzle.make(b, V(600, 300, 300), V(1, 0, 0), "EN 10220", "DN80", "", 150)
    fl = nozzle.add_flange(nz, "EN1092-1-11", "PN16")[0]
    doc.recompute()
    face, n = stdparts._face_frame(fl)
    f = stdparts.flange_info(fl.StdType, fl.Size, fl.Rating)
    best = None
    for i, e in enumerate(fl.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(2 * c.Radius - f["face"]) < 1e-3:
            d = (c.Center - face).Length
            if best is None or d < best[1]:
                best = (f"Edge{i+1}", d)
    S["fl"], S["fl_edge"], S["face"] = fl, best[0], face
    log("flange face", face)
    Gui.SendMsgToActiveView("ViewFit")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    from mechflow_gui import sketch3d, routing
    sk = sketch3d.make(None, "Steam line")
    ed = sketch3d.Editor(sk)
    ed.start(face, (fl, best[0]))
    ed.line_along(V(1, 0, 0), 1400)
    ed.line_along(V(0, 0, 1), 1200)
    ed.line_along(V(0, 1, 0), 1000)
    ed.save()
    routing.install()
    r = routing.make_route(None, [(sk, None)], "EN", "DN80", "", "3D", "Blind flange", "PN16",
                           [(fl, best[0])])
    S["r"], S["sk"] = r, sk
    log("route parts", len(r.Parts), "error", r.Error)
at(setup, 1500)


def place():
    from mechflow_gui import inline
    p = inline.valves_and_instruments(); S["p"] = p
    face = S["face"]
    p.list.setCurrentRow(inline.KINDS.index("Ball valve"))
    S["ball"] = p.place_at(S["r"], face + V(700, 0, 0))
    log("ball valve", S["ball"].Label, "ftf", S["ball"].FaceToFace, "end", S["ball"].EndType,
        "error", p.error.isVisible() and p.error.text())
    p.list.setCurrentRow(inline.KINDS.index("Gate valve"))
    S["gate"] = p.place_at(S["r"], face + V(1400, 0, 600))
    p.list.setCurrentRow(inline.KINDS.index("Butterfly valve"))
    S["bfv"] = p.place_at(S["r"], face + V(1400, 350, 1200))
    p.list.setCurrentRow(inline.KINDS.index("Pressure gauge"))
    S["pg"] = p.place_at(S["r"], face + V(1400, 750, 1200))
    assert not p.error.isVisible(), p.error.text()
    r = S["r"]
    kinds = {}
    for o in r.Parts:
        k = getattr(o, "StdType", type(getattr(o, "Proxy", None)).__name__)
        kinds[k] = kinds.get(k, 0) + 1
    pipes = sorted(round(float(o.Length)) for o in r.Parts if getattr(o, "StdType", "").endswith("PIPE"))
    log("route parts", kinds, "pipes", pipes)
    assert len(pipes) == 3 + 3, "three valves split three runs"
    assert kinds.get("EN1514-1-IBC", 0) >= 6 + 1
    # pipe ends meet the flanges: total = runs - fittings - valves
    for c in (S["ball"], S["gate"], S["bfv"]):
        log("  ", c.Label, "at", tuple(round(x) for x in c.Placement.Base),
            "stem", tuple(round(x, 3) for x in c.Placement.Rotation.multVec(V(0, 1, 0))))
    st = S["ball"].Placement.Rotation.multVec(V(0, 1, 0))
    assert (st - V(0, 0, 1)).Length < 1e-6, "stem up on a horizontal pipe"
    up = S["pg"].Placement.Rotation.multVec(V(0, 0, 1))
    log("gauge stands out along", tuple(round(x, 3) for x in up), "at", tuple(round(x) for x in S["pg"].Placement.Base))
    assert (up - V(0, 0, 1)).Length < 1e-6
    # overlaps between the valve and its neighbours (other than bolts/nuts)
    over = []
    for o in r.Parts:
        if getattr(o, "StdType", "").startswith(("EN10220", "EN1092", "EN1514")):
            v = o.Shape.common(S["ball"].Shape).Volume
            if v > 1:
                over.append((o.Label, round(v)))
    log("ball valve overlaps", over)
    dup = [o.Label for o in S["doc"].Objects if o.Label[-3:].isdigit() and ">" in o.Label]
    log("labels FreeCAD renumbered", dup[:8], len(dup))
    from mechflow_gui import routing
    vp = S["r"].ViewObject.Proxy
    claimed = vp.claimChildren()
    log("route claims", len(claimed), "parts", len(S["r"].Parts))
    assert not over
at(place, 1500)
at(lambda: (Gui.SendMsgToActiveView("ViewFit"), shot("valves")), 800)


def turn():
    p = S["p"]
    p._select(S["ball"])
    # drag the ring 90 degrees (as the mouse would)
    from pivy import coin
    p.disc.dragger.rotation.setValue(coin.SbVec3f(0, 0, 1), math.radians(91))
    p._follow_handles()
    log("after dragging the ring: angle box", p.angle.value(), "callout", p.dbox.value())
    assert abs(p.angle.value() - 90) < 1e-6
    p._rebuild()
    st = S["ball"].Placement.Rotation.multVec(V(0, 1, 0))
    log("stem now", tuple(round(x, 3) for x in st))
    assert (st - V(0, -1, 0)).Length < 1e-6
    # type in the 3D box: 30 degrees
    p.dbox.setValue(-30.0)
    p._rebuild()
    log("typed -30:", float(S["ball"].Angle))
    assert abs(float(S["ball"].Angle) + 30) < 1e-6
    # slide along: 900 from the start of the run
    p.along.setValue(900.0)
    p._rebuild()
    x = S["ball"].Placement.Base.x - S["face"].x
    log("slid to", round(x), "from the flange")
    assert abs(x - 900) < 1e-6
    # too near the elbow: refused with a message
    p.along.setValue(1350.0)
    p._rebuild()
    log("too near:", p.error.isVisible(), p.error.text()[:100])
    assert p.error.isVisible()
    x = S["ball"].Placement.Base.x - S["face"].x
    pipes = [o for o in S["r"].Parts if getattr(o, "StdType", "").endswith("PIPE")]
    log("  it stayed at", round(x), "and the route is whole:", len(pipes), "pipes")
    assert abs(x - 900) < 1e-6 and len(pipes) == 6
    p.along.setValue(700.0)
    p._rebuild()
    # drag the slide arrow back 100 mm (as the mouse would)
    p._follow_handles()
    a = p.arrow
    a.dragger.translation.setValue(-100.0 / a.scale, 0, 0)
    p._follow_handles()
    log("after dragging the arrow: along", p.along.value(), "callout", p.abox.value(),
        "shown", p.abox.isVisible())
    assert abs(p.along.value() - 600) < 1e-6 and p.abox.isVisible()
    p.along.setValue(700.0)
    p._rebuild()
    assert not p.error.isVisible()
    p.accept()
    dup = [o.Label for o in S["doc"].Objects if o.Label[-3:].isdigit() and ">" in o.Label]
    from mechflow_gui import routing
    owned = {x.Name for x in S["r"].Parts}
    loose = [o.Label for o in S["doc"].Objects if getattr(o, "MechFlowRoute", None) and o.Name not in owned]
    log("after turning and sliding: renumbered labels", dup[:5], len(dup), "| parts not in the route", loose[:5], len(loose))
    assert not dup and not loose
at(turn, 800)
at(lambda: shot("valves_turned"), 800)


def bom():
    from mechflow_gui import bom
    doc = S["doc"]
    names = [o.Label for o in doc.Objects if type(getattr(o, "Proxy", None)).__name__ == "InlineComponent"]
    log("components", names)
    assert any(n.startswith("Ball valve DN80 PN16") for n in names)
    d = doc; d.saveAs(OUT + "valves_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "valves_t.FCStd"); d.recompute()
    cs = [o for o in d.Objects if type(getattr(o, "Proxy", None)).__name__ == "InlineComponent"]
    log("reopened", [(c.Label, round(float(c.Angle))) for c in cs], [c.isValid() for c in cs])
    assert len(cs) == 4 and all(c.isValid() for c in cs)
at(bom, 800)
run()
