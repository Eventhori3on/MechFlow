import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Stress Check with a load on a curved face (a bore): the load must reach the
# mesh. Straight-sided 2nd order elements used to drop it without a word.
from h import *
import Part
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Lug"); S["doc"] = doc
    shp = Part.makeBox(300, 40, 80).cut(Part.makeCylinder(15, 40, V(250, 0, 40), V(0, 1, 0)))
    base = doc.addObject("Part::Feature", "LugShape"); base.Shape = shp
    b = doc.addObject("PartDesign::Body", "Body"); b.BaseFeature = base
    doc.recompute(); base.ViewObject.Visibility = False
    from mechflow_gui import material, simulation
    material.set_material(b, "Structural steel S275", 7850.0)
    root = [f"Face{i+1}" for i, f in enumerate(b.Shape.Faces)
            if f.BoundBox.XLength < 1e-6 and f.BoundBox.XMax < 1e-6]
    bore = [f"Face{i+1}" for i, f in enumerate(b.Shape.Faces) if type(f.Surface).__name__ == "Cylinder"]
    log("root", root, "bore", bore)
    p = simulation.stress_check(); S["p"] = p
    p.fixed = [(b, root)]
    p.loads = [{"type": "Force", "value": 5000.0, "direction": "-Z", "faces": [(b, bore)]}]
    p._refresh()
    p.quality.setCurrentText("Coarse")
    p._run()
at(setup, 1500)


def wait():
    import time, json
    p = S["p"]; t0 = time.time()
    while p.solver and not p.solver.done and time.time() - t0 < 600:
        QtWidgets.QApplication.processEvents(); time.sleep(0.2)
    QtWidgets.QApplication.processEvents(); time.sleep(1.0); QtWidgets.QApplication.processEvents()
    r = json.loads(p.study.Result or "{}")
    log("RESULT", {k: r.get(k) for k in ("max_stress", "max_disp", "fos")})
    # cantilever 250 long to the load, 40 x 80 section: ~ F L^3 / 3EI at the hole
    I = 40 * 80 ** 3 / 12
    hand = 5000 * 250 ** 3 / (3 * 210000 * I)
    log("hand deflection at the hole", round(hand, 3))
    assert r.get("max_disp", 0) > 0.7 * hand, "the bore load didn't reach the mesh"
    p.accept()
at(wait, 1000)
run()
