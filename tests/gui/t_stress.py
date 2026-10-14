import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Stress Check: a cantilever against hand calculation, run from the panel
# with picked faces, and the study saved with the part.
from h import *
import Part
V = App.Vector
S = {}
L, B, F = 1000.0, 50.0, 1000.0
SIGMA = 6 * F * L / (B * B * B)          # 48 MPa at the root
DEFL = F * L ** 3 / (3 * 210000 * B ** 4 / 12)   # 3.05 mm at the tip


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Beam"); S["doc"] = doc
    b = new_body(doc, "Body"); S["b"] = b
    sk = sketch(b, "YZ_Plane", rect(0, 0, B, B))
    pad = b.newObject("PartDesign::Pad", "Pad"); pad.Profile = sk; pad.Length = L
    doc.recompute(); sk.ViewObject.Visibility = False
    from mechflow_gui import material
    material.set_material(b, "Structural steel S275", 7850.0)
    S["root"] = face_where(pad, lambda f: plane_face(f) and abs(f.BoundBox.XMax) < 1e-6 and abs(f.BoundBox.XMin) < 1e-6)
    S["tip"] = face_where(pad, lambda f: plane_face(f) and abs(f.BoundBox.XMin - L) < 1e-6)
    log("beam", b.Shape.BoundBox, S["root"], S["tip"])
    from mechflow_gui import simulation
    S["p"] = simulation.stress_check()
at(setup, 1500)


def picks():
    p = S["p"]; b = S["b"]
    Gui.Selection.addSelection("Beam", b.Tip.Name, S["root"])
at(picks, 600)


def load():
    p = S["p"]
    p.ltype.setCurrentText("Force"); p.lval.setValue(F); p.ldir.setCurrentText("-Z")
    p._mode("load")
    Gui.Selection.addSelection("Beam", S["b"].Tip.Name, S["tip"])
at(load, 800)


def run_():
    p = S["p"]
    log("panel", p.fix_list.text(), [p.load_list.item(i).text() for i in range(p.load_list.count())])
    p.quality.setCurrentText("Coarse")
    p._run()
at(run_, 800)


def wait():
    p = S["p"]
    import time
    t0 = time.time()
    while not (p.solver and p.solver.done) and time.time() - t0 < 600:
        QtWidgets.QApplication.processEvents(); time.sleep(0.2)
    QtWidgets.QApplication.processEvents()
at(wait, 1000)


def check():
    p = S["p"]
    p._check()
    r = __import__("json").loads(p.study.Result)
    log("RESULT", {k: r[k] for k in ("max_stress", "max_disp", "fos", "nodes", "element size", "wall", "solve_s")})
    log("hand", round(SIGMA, 1), "MPa", round(DEFL, 2), "mm")
    assert abs(r["max_disp"] - DEFL) / DEFL < 0.05, "deflection off by more than 5%"
    # the root's peak includes the fixed-edge singularity: check the beam's
    # bending stress half way along instead
    rd = p.rdoc
    res = [o for o in rd.Objects if o.isDerivedFrom("Fem::FemResultObject")][0]
    mesh = res.Mesh.FemMesh
    mid = [v for n, v in zip(res.NodeNumbers, res.vonMises)
           if abs(mesh.getNodeById(n).x - L / 2) < 15 and abs(mesh.getNodeById(n).z - B) < 1e-3]
    s_mid = max(mid)
    log("mid-span top fibre", round(s_mid, 1), "MPa, hand", round(SIGMA / 2, 1))
    assert abs(s_mid - SIGMA / 2) / (SIGMA / 2) < 0.08
    assert 4 < r["fos"] < 7, r["fos"]
    assert "Passes" in p.result.text()
    p.accept()
    pipes = [o for o in rd.Objects if o.isDerivedFrom("Fem::FemPostPipeline")]
    log("pipeline", [(x.Label, x.ViewObject.Field) for x in pipes])
    assert pipes
    S["rdoc"] = rd
at(check, 500)
at(lambda: shot("stress"), 1500)


def reopen():
    d = S["doc"]; d.saveAs(OUT + "beam_t.FCStd"); App.closeDocument(d.Name)
    d = App.openDocument(OUT + "beam_t.FCStd")
    from mechflow_gui import simulation
    st = [o for o in d.Objects if simulation.is_study(o)]
    log("study after reopen", [(o.Label, len(o.Fixed), o.Loads[:80]) for o in st])
    assert st and st[0].Fixed and "Force" in st[0].Loads
    p = simulation.StressPanel(st[0])
    log("reopened panel", p.fix_list.text(), p.load_list.count(), "result shown", "Max von Mises" in p.result.text())
    assert p.load_list.count() == 1
at(reopen, 800)
run()
