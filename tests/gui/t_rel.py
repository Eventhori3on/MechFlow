import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"]=doc
    b = new_body(doc, "Body")
    geos = rect(0, 0, 40, 20) + circle(60, 10, 5) + circle(60, 10.5, 3)
    sk = sketch(b, "XY_Plane", geos); doc.recompute(); S["sk"]=sk
    Gui.ActiveDocument.setEdit(sk.Name)
at(setup, 1800)
at(lambda: Gui.SendMsgToActiveView("ViewFit"), 400)
def R():
    from mechflow_gui import relations; return relations._panel
def status():
    from mechflow_gui import sketch_status as ss
    return ss._label.text() if ss._label else None
def buttons():
    p = R(); out=[]
    for i in range(p.add_grid.count()):
        w = p.add_grid.itemAt(i).widget()
        if w: out.append(w.text())
    return out
def click(name):
    def f():
        p = R()
        for i in range(p.add_grid.count()):
            w = p.add_grid.itemAt(i).widget()
            if w and w.text() == name:
                w.click(); return
        log("  !! no button", name, buttons())
    return f
def seltest(tag, subs):
    def f():
        Gui.Selection.clearSelection()
        for s in subs: Gui.Selection.addSelection("T", S["sk"].Name, s)
    def g():
        log(tag, "->", buttons(), "| sel:", R().sel_label.text())
    at(f, 500); at(g, 50)
def cons(tag):
    return lambda: log(tag, [(c.Type, c.First, c.FirstPos, c.Second, c.SecondPos) for c in S["sk"].Constraints], "|", status())
at(lambda: log("panel visible", R() is not None and R().isVisible(), "| status:", status(), "| wb", Gui.activeWorkbench().name()), 300)
seltest("1 line", ["Edge1"])
at(click("Horizontal"), 500); at(cons("after Horizontal"), 50)
seltest("2 points", ["Vertex2", "Vertex3"])
at(click("Coincident"), 500); at(cons("after Coincident"), 50)
seltest("2 lines", ["Edge1", "Edge3"])
at(click("Parallel"), 500)
seltest("line+circle", ["Edge2", "Edge5"])
seltest("2 circles", ["Edge5", "Edge6"])
at(click("Concentric"), 600); at(cons("after Concentric"), 50)
seltest("point+line", ["Vertex1", "Edge2"])
seltest("origin+point", ["RootPoint", "Vertex1"])
at(click("Coincident"), 500)
seltest("3 lines", ["Edge1", "Edge2", "Edge3"])
at(lambda: Gui.Selection.clearSelection(), 500)
at(lambda: (log("all existing:", [R().list.item(i).text() for i in range(R().list.count())]), shot("relations")), 100)
# highlight + delete the Parallel relation
def del_parallel():
    p = R()
    for i in range(p.list.count()):
        if p.list.item(i).text().startswith("Parallel"):
            p.list.setCurrentRow(i); p._highlight(p.list.item(i)); break
at(del_parallel, 500)
at(lambda: log("highlighted sel:", [i.SubElementNames for i in Gui.Selection.getSelectionEx()], "list kept:", R().list.count()), 300)
at(lambda: R()._delete(), 500)
at(cons("after delete Parallel"), 50)
# fully define the rectangle
def fully():
    import Sketcher
    sk = S["sk"]
    for a, b in ((1, 2), (2, 3), (3, 0)):
        pass
    sk.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
    sk.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
    sk.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", 1)); sk.addConstraint(Sketcher.Constraint("Vertical", 3))
    sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 40))
    sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 20))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 4, 3, 60)); sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 4, 3, 10))
    sk.addConstraint(Sketcher.Constraint("Radius", 4, 5)); sk.addConstraint(Sketcher.Constraint("Radius", 5, 3))
at(fully, 600)
at(lambda: (log("DoF", S["sk"].DoF, "| status:", status()), shot("fully")), 500)
def over():
    import Sketcher
    S["sk"].addConstraint(Sketcher.Constraint("DistanceX", 2, 2, 2, 1, 35))
at(over, 600)
at(lambda: log("over | status:", status(), "conflict", S["sk"].ConflictingConstraints), 300)
at(lambda: Gui.ActiveDocument.resetEdit(), 600)
at(lambda: log("after close | panel visible", R().isVisible(), "| status label visible", __import__("mechflow_gui.sketch_status", fromlist=["x"])._label.isVisible()), 100)
run()
