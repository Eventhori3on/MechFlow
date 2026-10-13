import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part, Sketcher, math
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); S["doc"] = doc
    b = new_body(doc, "Body")
    sk = b.newObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [(origin(b, "XY_Plane"), "")]; sk.MapMode = "FlatFace"
    sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 50))
    sk.addGeometry(Part.Circle(V(25, -30, 0), V(0, 0, 1), 5))
    sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
    sk.addConstraint(Sketcher.Constraint("Diameter", 0, 100))
    sk.addConstraint(Sketcher.Constraint("Diameter", 1, 10))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 1, 3, 25))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 1, 3, -30))
    doc.recompute(); S["sk"] = sk
    Gui.ActiveDocument.setEdit(sk.Name)
at(setup, 1800)
at(lambda: Gui.SendMsgToActiveView("ViewFit"), 400)
def P():
    from mechflow_gui import sketch_pattern; return sketch_pattern._panel
def state(tag):
    def f():
        sk = S["sk"]
        from mechflow_gui import sketch_status as ss
        circ = [(round(g.Center.x, 2), round(g.Center.y, 2), round(g.Radius, 2)) for g in sk.Geometry if type(g).__name__ == "Circle"]
        log(tag, "| geos", len(sk.Geometry), "cons", len(sk.Constraints), "| circles", circ,
            "| status", ss._label.text() if ss._label else None, "| conflicts", sk.ConflictingConstraints, sk.RedundantConstraints)
    return f
def cmd():
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection("T", "Sketch", "Edge2")
    log("command active:", Gui.Command.get("MechFlow_CircularSketchPattern").isActive())
    Gui.runCommand("MechFlow_CircularSketchPattern", 0)
at(cmd, 600)
at(lambda: log("panel", P() is not None, "visible", P() and P().isVisible(), "seeds", P() and P().seeds, "centre", P() and P().centre_lbl.text()), 500)
at(state("preview 4 x 90"), 100)
at(lambda: shot("cpat_preview"), 100)
at(lambda: P().count.setValue(6), 400); at(state("preview 6"), 100)
at(lambda: P().reject(), 400); at(state("after cancel"), 300)
# again: 6 equal, OK
at(cmd, 500)
at(lambda: P().count.setValue(6), 400)
at(lambda: P().accept(), 500); at(state("after OK 6"), 300)
def move_seed():
    sk = S["sk"]
    for i, c in enumerate(sk.Constraints):
        if c.Type == "DistanceX" and c.Second == 1: sk.setDatum(i, App.Units.Quantity("30 mm"))
        if c.Type == "Diameter" and c.First == 1: sk.setDatum(i, App.Units.Quantity("12 mm"))
    sk.solve(); sk.recompute()
at(move_seed, 300); at(state("seed moved to x=30, dia 12 (pattern follows)"), 300)
at(lambda: shot("cpat_done"), 200)
# Undo
at(lambda: log("undo names", S["doc"].UndoNames[:3]), 100)
at(lambda: S["doc"].undo(), 400); at(state("after 1 undo"), 300)
# 180 deg, not equal spacing, reverse, picked centre (circle 0 centre)
def cmd2():
    Gui.Selection.clearSelection()
    Gui.runCommand("MechFlow_CircularSketchPattern", 0)
at(cmd2, 500)
at(lambda: log("empty panel msg:", P().msg.text()), 200)
at(lambda: Gui.Selection.addSelection("T", "Sketch", "Edge2"), 400)
at(lambda: (P().equal.setChecked(False), P().angle.setValue(45), P().count.setValue(3), P().reverse.setChecked(True)), 400)
at(state("preview 3 x -45"), 100)
at(lambda: P().accept(), 500); at(state("after OK 3 x -45"), 300)
at(lambda: log("relations panel back:", __import__("mechflow_gui.relations", fromlist=["x"])._panel.isVisible()), 600)
run()
