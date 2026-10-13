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
    sk.addGeometry(Part.Circle(V(20, 20, 0), V(0, 0, 1), 3))                 # 0 seed circle
    sk.addGeometry(Part.LineSegment(V(-40, 0, 0), V(-40 + 30 * math.cos(math.radians(30)), 30 * math.sin(math.radians(30)), 0)))  # 1 direction line
    for c in (C("Diameter", 0, 6), C("DistanceX", -1, 1, 0, 3, 20), C("DistanceY", -1, 1, 0, 3, 20),
              C("Coincident", 1, 1, -1, 1) if False else C("DistanceX", -1, 1, 1, 1, -40), C("PointOnObject", 1, 1, -1),
              C("Distance", 1, 30), C("Angle", 1, math.radians(30))):
        sk.addConstraint(c)
    doc.recompute(); S["sk"] = sk
    Gui.ActiveDocument.setEdit(sk.Name)
C = Sketcher.Constraint
at(setup, 1800)
at(lambda: Gui.SendMsgToActiveView("ViewFit"), 400)
def P():
    from mechflow_gui import sketch_pattern; return sketch_pattern._panel
def state(tag):
    def f():
        sk = S["sk"]
        from mechflow_gui import sketch_status as ss
        circ = sorted((round(g.Center.x, 2), round(g.Center.y, 2), round(g.Radius, 2)) for g in sk.Geometry if type(g).__name__ == "Circle")
        txt = ss._label.text() if ss._label else ""
        log(tag, "| geos", len(sk.Geometry), "cons", len(sk.Constraints), "| circles", circ,
            "|", "Fully" if "Fully" in txt else txt[-40:], "| conflicts", sk.ConflictingConstraints, sk.RedundantConstraints)
    return f
def cmd():
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection("T", "Sketch", "Edge1")
    log("command active:", Gui.Command.get("MechFlow_LinearSketchPattern").isActive())
    Gui.runCommand("MechFlow_LinearSketchPattern", 0)
at(cmd, 600)
at(lambda: log("panel", type(P()).__name__, "seeds", P().seeds, "icon null", P().findChildren(QtWidgets.QLabel)[0].pixmap().isNull()), 400)
at(state("preview default 3 x 10 along X"), 100)
at(lambda: (P().dirs[0].spacing.setValue(15), P().dirs[1].box.setChecked(True), P().dirs[1].spacing.setValue(12), P().dirs[1].count.setValue(2)), 400)
at(state("preview 3x2 grid 15/12"), 100)
at(lambda: shot("lpat_preview"), 100)
at(lambda: P().accept(), 500); at(state("after OK grid"), 300)
def move_seed():
    sk = S["sk"]
    for i, c in enumerate(sk.Constraints):
        if c.Type == "DistanceX" and c.Second == 0: sk.setDatum(i, App.Units.Quantity("25 mm"))
        if c.Type == "Diameter" and c.First == 0: sk.setDatum(i, App.Units.Quantity("8 mm"))
    sk.solve(); sk.recompute()
at(move_seed, 300); at(state("seed moved x=25 dia 8 (grid follows)"), 300)
at(lambda: shot("lpat_done"), 200)
at(lambda: S["doc"].undo(), 400); at(state("after undo"), 300)
# direction from the 30 deg line, reverse, cancel then OK
at(cmd, 500)
def pick_dir():
    P().dirs[0].pick.setChecked(True)
at(pick_dir, 300)
at(lambda: Gui.Selection.addSelection("T", "Sketch", "Edge2"), 400)
at(lambda: log("dir1 angle from line:", P().dirs[0].angle.value(), "seeds", P().seeds), 100)
at(lambda: (P().dirs[0].reverse.setChecked(True), P().dirs[0].count.setValue(2)), 400)
at(state("preview 2 along 30 deg reversed"), 100)
at(lambda: P().reject(), 400); at(state("after cancel"), 300)
at(cmd, 500)
at(lambda: (P().dirs[0].angle.setValue(30), P().dirs[0].count.setValue(3)), 400)
at(lambda: P().accept(), 500); at(state("after OK 3 at 30 deg"), 300)
at(lambda: log("relations back:", __import__("mechflow_gui.relations", fromlist=["x"])._panel.isVisible()), 600)
run()
