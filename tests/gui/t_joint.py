import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
try:
    import FastenersCmd
    HAVE_FASTENERS = True
except ImportError:
    HAVE_FASTENERS = False
import Part
V = App.Vector
S = {}
def circle_edge(obj, r, z):
    for i, e in enumerate(obj.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - r) < 1e-3 and abs(c.Center.z - z) < 1e-3:
            return f"Edge{i+1}"
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("J"); S["doc"] = doc
    for name, x, od in (("PipeEN", 0, 60.3), ("PipeAS", 400, 60.33)):
        p = doc.addObject("Part::Feature", name)
        p.Shape = Part.makeCylinder(od / 2, 300, V(x, 0, 0)).cut(Part.makeCylinder(od / 2 - 3, 302, V(x, 0, -1)))
        S[name] = p
    doc.recompute()
at(setup, 1500)
def P(): return S["panel"]
def open_tb(t):
    def f():
        from mechflow_gui import toolbox as tb
        S["panel"] = tb.toolbox(); p = P(); p.std.setCurrentText("All")
        def find(item):
            for i in range(item.childCount()):
                c = item.child(i)
                if c.data(0, QtCore.Qt.UserRole) == t: return c
                r = find(c)
                if r: return r
        p.tree.setCurrentItem(find(p.tree.invisibleRootItem()))
        log("open", t, "joint row", p.joint.isVisibleTo(p.form))
    return f
def pick(key, r, z, xoff=0):
    def f():
        o = S[key] if isinstance(key, str) else key()
        for i, e in enumerate(o.Shape.Edges):
            c = getattr(e, "Curve", None)
            if type(c).__name__ == "Circle" and abs(c.Radius - r) < 1e-3 and abs(c.Center.z - z) < 1e-3 and abs(c.Center.y) < 1e-3 and abs(c.Center.x - xoff) < 1e-3:
                Gui.Selection.addSelection("J", o.Name, f"Edge{i+1}"); return
        log("  !! no edge", r, z)
    return f
def acc(tag):
    def f():
        p = P()
        log("  edges:", [p.hole_list.item(i).text() for i in range(p.hole_list.count())])
        p.accept()
        for o in p.made:
            bb = o.Shape.BoundBox
            log(f"  {tag}: {o.Label:42s} z {bb.ZMin:7.2f}..{bb.ZMax:7.2f}  x {bb.Center.x:6.1f} y {bb.Center.y:6.1f}")
        S[tag] = p.made
    return f
# EN: WN on pipe, then WN on its raised face -> joint
at(open_tb("EN1092-1-11"), 700); at(pick("PipeEN", 30.15, 300), 500); at(acc("en_wn"), 600)
at(open_tb("EN1092-1-11"), 700); at(pick(lambda: S["en_wn"][0], 51, 345), 500); at(acc("en_joint"), 1500)
# ASME: SO on pipe, blind on it via the OD edge
at(open_tb("ASMEB16.5-SO"), 700); at(pick("PipeAS", 30.165, 300, 400), 500); at(acc("as_so"), 600)
def od_edge():
    o = S["as_so"][0]; bb = o.Shape.BoundBox
    for i, e in enumerate(o.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - 76.2) < 1e-2 and c.Center.z > bb.ZMax - 3:
            Gui.Selection.addSelection("J", o.Name, f"Edge{i+1}"); log("  OD edge at z", round(c.Center.z, 2)); return
at(open_tb("ASMEB16.5-BL"), 700); at(od_edge, 500); at(acc("as_blind"), 1500)
def check():
    import itertools
    objs = [o for o in S["doc"].Objects if hasattr(o, "Shape") and o.Shape.Solids and o.Name not in ("PipeEN", "PipeAS")]
    clashes = []
    for a, b in itertools.combinations(objs, 2):
        if a.Shape.BoundBox.intersect(b.Shape.BoundBox):
            v = a.Shape.common(b.Shape).Volume
            if v > 1.0: clashes.append((a.Label, b.Label, round(v, 1)))
    log("clashes (bolt/hole contact expected none):", clashes[:10], len(clashes))
    Gui.SendMsgToActiveView("ViewFit"); Gui.activeDocument().activeView().viewIsometric()
at(check, 800)
at(lambda: shot("joint"), 800)
if not HAVE_FASTENERS:
    Q.clear()
    at(lambda: log("SKIP: the Fasteners Workbench is not installed"), 100)
run()
