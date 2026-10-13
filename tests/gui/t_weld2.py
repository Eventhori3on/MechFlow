import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("W2"); S["doc"] = doc
    sk = doc.addObject("Sketcher::SketchObject", "Frame")
    pts = [(0, 0), (1000, 0), (1000, 600), (0, 600)]
    for i in range(4): sk.addGeometry(Part.LineSegment(V(*pts[i], 0), V(*pts[(i + 1) % 4], 0)))
    sk2 = doc.addObject("Sketcher::SketchObject", "Posts")
    sk2.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
    for x in (0, 1000):
        sk2.addGeometry(Part.LineSegment(V(x, 0, 0), V(x, 800, 0)))
    doc.recompute()
    from mechflow_gui import weldments as w
    S["frame"] = w.make("SHS-H", "50x50x4", [(sk, [])])
    S["posts"] = w.make("SHS-H", "40x40x3", [(sk2, [])])
    for o in (S["frame"], S["posts"]):
        bb = [ (round(s.BoundBox.ZMin,1), round(s.BoundBox.ZMax,1)) for s in o.Shape.Solids]
        log(o.Label, "z ranges", bb)
at(setup, 1500)
def trim():
    from mechflow_gui import weld_extras as we
    Gui.Selection.addSelection("W2", S["posts"].Name)
    p = we.trim_extend(); S["p"] = p
    Gui.Selection.addSelection("W2", S["frame"].Name)
at(trim, 600)
def trim_done():
    p = S["p"]
    log("trim panel:", p.lbl1.text(), "|", p.lbl2.text())
    p.accept()
    log("posts after trim z", [(round(s.BoundBox.ZMin, 1), round(s.BoundBox.ZMax, 1)) for s in S["posts"].Shape.Solids])
at(trim_done, 600)
def face_where(o, pred):
    for i, f in enumerate(o.Shape.Faces):
        if type(f.Surface).__name__ == "Plane" and pred(f): return f"Face{i+1}"
def caps():
    from mechflow_gui import weld_extras as we
    o = S["posts"]
    for f in [face_where(o, lambda f: f.BoundBox.ZMin > 799.9 and f.BoundBox.XMin < 100),
              face_where(o, lambda f: f.BoundBox.ZMin > 799.9 and f.BoundBox.XMin > 900)]:
        Gui.Selection.addSelection("W2", o.Name, f)
    S["p"] = we.end_cap()
at(caps, 600)
def caps_done():
    p = S["p"]; p.accept()
    caps = [o for o in S["doc"].Objects if type(getattr(o, "Proxy", None)).__name__ == "EndCap"]
    for c in caps:
        bb = c.Shape.BoundBox
        log("cap", c.Label, f"x {bb.XMin:.1f}..{bb.XMax:.1f} z {bb.ZMin:.1f}..{bb.ZMax:.1f}", "inset", c.Inset)
at(caps_done, 600)
def gus():
    from mechflow_gui import weld_extras as we
    po, fr = S["posts"], S["frame"]
    f1 = face_where(po, lambda f: abs(f.BoundBox.XMin - 20) < 0.01 and abs(f.BoundBox.XMax - 20) < 0.01 and f.BoundBox.XMax < 100)
    f2 = face_where(fr, lambda f: abs(f.BoundBox.ZMin - 25) < 0.01 and abs(f.BoundBox.ZMax - 25) < 0.01 and f.BoundBox.YMax < 30 and f.BoundBox.XMax > 500)
    log("gusset faces", f1, f2, po.Shape.getElement(f1).BoundBox, fr.Shape.getElement(f2).BoundBox)
    Gui.Selection.addSelection("W2", po.Name, f1); Gui.Selection.addSelection("W2", fr.Name, f2)
    S["p"] = we.gusset()
at(gus, 600)
def gus_done():
    p = S["p"]
    log("gusset msg:", p.msg.text())
    p.accept()
    g = [o for o in S["doc"].Objects if type(getattr(o, "Proxy", None)).__name__ == "Gusset"][0]
    bb = g.Shape.BoundBox
    log("gusset", f"x {bb.XMin:.1f}..{bb.XMax:.1f} y {bb.YMin:.1f}..{bb.YMax:.1f} z {bb.ZMin:.1f}..{bb.ZMax:.1f}", "vol", round(g.Shape.Volume))
    import itertools
    objs = [S["frame"], S["posts"], g] + [o for o in S["doc"].Objects if type(getattr(o, "Proxy", None)).__name__ == "EndCap"]
    for a, b in itertools.combinations(objs, 2):
        v = a.Shape.common(b.Shape).Volume
        if v > 1: log("  overlap", a.Label, b.Label, round(v))
    from mechflow_gui import weldments as w
    log("cut list:", w.cut_items(S["doc"]))
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(gus_done, 700)
at(lambda: shot("weld2"), 800)
OUT = os.environ.get("MF_OUT", "/tmp") + "/"
def reopen():
    d = S["doc"]; d.saveAs(OUT + "weld2.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "weld2.FCStd"); d.recompute()
    log("reopened:", [(o.Label, o.isValid()) for o in d.Objects if hasattr(o, "Proxy")])
at(reopen, 600)
run()
