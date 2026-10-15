import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Pipe from Scan: a "scan" made from a known route (its outside surfaces,
# tessellated, with noise and some clutter) - Import Scan reads it, a click
# on the pipe traces it through the elbows to the flanges, and the route
# made matches the original: same corners (within a few mm), same size,
# same parts, flanges recognised as EN PN16. Then: the scan moved and
# turned (route lands in the right place), a mesh imported by FreeCAD
# itself (no scan file), a point cloud (normals estimated), and a line
# that steps down through a reducer.
from h import *
import Part, shutil
import numpy as np, time
V = App.Vector
S = {}
SCANS = OUT + "scan-files/"
shutil.rmtree(SCANS, ignore_errors=True)
os.makedirs(SCANS, exist_ok=True)
os.environ["MF_SCAN_CACHE"] = SCANS + "cache"
os.environ["MF_PIPE_SPECS"] = OUT + "scan-specs/"
shutil.rmtree(OUT + "scan-specs/", ignore_errors=True)


def inner(f):
    """A bore (its surface faces the pipe's own axis)."""
    s = f.Surface
    k = type(s).__name__
    if k not in ("Cylinder", "Toroid", "Cone"):
        return False
    u0, u1, v0, v1 = f.ParameterRange
    um, vm = (u0 + u1) / 2, (v0 + v1) / 2
    p = f.valueAt(um, vm)
    n = f.normalAt(um, vm)
    C, A = V(s.Center), V(s.Axis)
    q = p - A * (p - C).dot(A)
    if k == "Toroid":
        d = q - C
        d.normalize()
        radial = p - (C + d * s.MajorRadius)
    else:
        radial = q - C
    return n.dot(radial) < 0


def outside_mesh(parts, od, extra=()):
    """Vertices and triangles of the parts' outside surfaces (what a
    scanner sees: no bores) plus extra shapes."""
    Vs, Fs = [], []
    n = 0
    for sh in [p.Shape for p in parts] + list(extra):
        for f in sh.Faces:
            if inner(f):
                continue
            pts, tris = f.tessellate(0.4)
            if not tris:
                continue
            Vs.append(np.array([(q.x, q.y, q.z) for q in pts]))
            Fs.append(np.array(tris) + n)
            n += len(pts)
    return np.vstack(Vs), np.vstack(Fs)


def write_obj(path, v, f, noise=0.25, seed=1):
    rng = np.random.default_rng(seed)
    v = v + rng.normal(0, noise, v.shape)
    with open(path, "w") as fh:
        fh.write("# test scan\n")
        fh.write("".join("v %.4f %.4f %.4f\n" % tuple(q) for q in v))
        fh.write("".join("f %d %d %d\n" % tuple(t + 1) for t in f))


def make_truth(name, pts, size, changes=None):
    from mechflow_gui import sketch3d, routing
    d = App.newDocument(name)
    sk = sketch3d.make(None, "Truth line")
    ed = sketch3d.Editor(sk)
    ed.start(pts[0])
    for q in pts[1:]:
        ed.line_to(q)
    ed.save()
    r = routing.make_route(None, [(sk, None)], "EN", size, "", "3D", "Weld neck flange", "PN16",
                           build_now=False)
    if changes:
        segs = routing.path_segments_keyed(routing.path_links(r))
        for (a, b), sz in changes:
            for s0, s1, key in segs:
                if (s0 - a).Length < 0.1 and (s1 - b).Length < 0.1:
                    routing.set_size_change(r, key, sz)
    routing.build(r)
    d.recompute()
    assert not r.Error, r.Error
    return d, r


def hanger(c, d, r):
    """A pipe hanger: a clamp band round the pipe, two lugs, a rod up."""
    band = Part.makeCylinder(r + 6, 60, c - d * 30, d).cut(Part.makeCylinder(r - 1, 62, c - d * 31, d))
    side = d.cross(V(0, 0, 1))
    side.normalize()
    lugs = [Part.makeBox(16, 16, 40, c + side * (r + 4) - V(8, 8, 20)),
            Part.makeBox(16, 16, 40, c - side * (r + 20) - V(8, 8, 20))]
    rod = Part.makeCylinder(8, 600, c + V(0, 0, r + 4))
    return [band] + lugs + [rod]


def kinds(r):
    k = {}
    for o in r.Parts:
        t = getattr(o, "StdType", "?")
        key = f"{t} {getattr(o, 'Size', '')}"
        k[key] = k.get(key, 0) + 1
    return k


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    from mechflow_gui import routing
    routing.install()
    # a line like one in a ship: off a flange, up, across, down to a flange
    pts = [V(0, 0, 0), V(0, -900, 0), V(0, -900, 1400), V(2200, -900, 1400),
           V(2200, -900, 300), V(2200, 0, 300)]
    d, r = make_truth("ScanTruth", pts, "DN150")
    S["truth_pts"], S["truth_kinds"] = pts, kinds(r)
    log("truth parts", S["truth_kinds"])
    # clutter: a floor, a support post close by, a small pipe running past
    extra = [Part.makeBox(4000, 3000, 20, V(-900, -2200, -420)),
             Part.makeBox(80, 80, 900, V(400, -1020, -400)),
             Part.makeCylinder(30, 2500, V(-300, -500, 900), V(1, 0, 0))]
    extra += hanger(V(700, -900, 1400), V(1, 0, 0), 84.15)      # a pipe hanger on the top run
    v, f = outside_mesh(r.Parts, 168.3, extra)
    S["path"] = SCANS + "line.obj"
    write_obj(S["path"], v, f)
    log("scan", len(v), "points", len(f), "triangles")
    # the same as a point cloud with a big hole along the top run (nothing
    # seen for 800 mm): tracing stops there until told to carry on
    from mechflow_gui import scan as _scan
    P = _scan.load_scan(S["path"]).cloud().P
    hole = (P[:, 0] > 1000) & (P[:, 0] < 1800) & (P[:, 2] > 1250) & (np.abs(P[:, 1] + 900) < 200)
    S["gap"] = SCANS + "gap.xyz"
    np.savetxt(S["gap"], P[~hole], fmt="%.3f")
    App.closeDocument(d.Name)
at(setup, 1500)


def import_it():
    from mechflow_gui import scan_gui
    doc = App.newDocument("ScanTest"); S["doc"] = doc
    o = scan_gui.import_scan(S["path"])
    S["scan"] = o
    log("imported:", o.TypeId, o.Label, "file", os.path.basename(o.ScanFile),
        "shown triangles", o.Mesh.CountFacets)
    assert o.isDerivedFrom("Mesh::Feature") and o.ScanFile == S["path"]
    assert os.path.isdir(SCANS + "cache") and os.listdir(SCANS + "cache"), "scan cached"
at(import_it)


def corners_match(sk, want, tol=4.0, tf=None):
    got = [V(p) for p in sk.Points]
    if tf is not None:
        want = [tf.multVec(p) for p in want]
    worst = 0.0
    for p in want:
        dmin = min((p - q).Length for q in got)
        worst = max(worst, dmin)
    return worst


def trace():
    from mechflow_gui import scan_gui
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(S["doc"].Name, S["scan"].Name)
    p = scan_gui.pipe_from_scan(); S["p"] = p
    assert p.scan_obj is S["scan"]
    # click on the top of the run across (the wall, not the centre)
    p.trace_at(V(1100, -900, 1400 + 84.15))
    assert p.res is not None, p.error.text()
    ends = [(e["kind"], e.get("match") and (e["match"]["std"], e["match"]["rating"]))
            for e in p.res["ends"]]
    log("traced: OD %.1f" % p.res["od"], "ends", ends, "straights", len(p.res["runs"]))
    log("spec", p.spec.currentText(), "size", p.size.currentText(), "flanges",
        p.rating.currentText(), "bend", p.bend.currentText())
    assert abs(p.res["od"] - 168.3) < 2.0
    assert [e[0] for e in ends] == ["flange", "flange"], ends
    assert all(e[1] == ("EN", "PN16") for e in ends), ends
    assert p.size.currentText() == "DN150" and p.rating.currentText() == "PN16"
    assert p.bend.currentText() == "3D"
    assert len(p.res["runs"]) == 5
    pv = S["doc"].getObject(p.preview)
    assert pv is not None and len(pv.Shape.Edges) == 5
    log("found:", p.found.toPlainText()[:400].replace("\n", " | "))
    shot("scan_panel")
at(trace)


def accept():
    p = S["p"]
    before = {o.Name for o in S["doc"].Objects}
    p.accept()
    new = [o for o in S["doc"].Objects if o.Name not in before]
    r = [o for o in new if type(getattr(o, "Proxy", None)).__name__ == "PipeRoute"][0]
    sk = [o for o in new if o.Label.startswith("Scan line")][0]
    S["route"] = r
    worst = corners_match(sk, S["truth_pts"])
    log("route", r.Label, "error:", r.Error or "none", "parts", kinds(r))
    log("corners off the original by up to %.2f mm" % worst)
    assert not r.Error
    assert worst < 4.0, worst
    assert kinds(r) == S["truth_kinds"], (kinds(r), S["truth_kinds"])
    assert S["doc"].getObject("ScanPipePreview") is None, "preview removed"
    shot("scan_route")
at(accept, 600)


def moved():
    """The scan moved and turned: the route lands on it where it is."""
    from mechflow_gui import scan_gui
    o = S["scan"]
    pl = App.Placement(V(5000, 2000, 100), App.Rotation(V(0, 0, 1), 30))
    o.Placement = pl
    S["doc"].recompute()
    p = scan_gui.ScanPanel(o)
    Gui.Control.showDialog(p)
    p.trace_at(pl.multVec(V(1100, -900, 1400 + 84.15)))
    assert p.res is not None, p.error.text()
    route, sk, notes = p.make()
    worst = corners_match(sk, S["truth_pts"], tf=pl)
    log("moved scan: corners off by up to %.2f mm, parts" % worst, len(route.Parts), notes)
    assert worst < 4.0 and not route.Error
    p.reject()
    o.Placement = App.Placement()
at(moved, 600)


def plain_mesh():
    """A mesh FreeCAD imported itself (no scan file behind it)."""
    import Mesh
    from mechflow_gui import scan_gui
    m = S["doc"].addObject("Mesh::Feature", "Plain")
    m.Mesh = Mesh.Mesh(S["path"])
    S["scan"].Visibility = False
    S["doc"].recompute()
    p = scan_gui.ScanPanel(m)
    Gui.Control.showDialog(p)
    t0 = time.time()
    p.trace_at(V(1100, -900, 1400 + 84.15))
    assert p.res is not None, p.error.text()
    route, sk, notes = p.make()
    worst = corners_match(sk, S["truth_pts"])
    log("plain mesh: %.1f s, corners off by up to %.2f mm" % (time.time() - t0, worst))
    assert worst < 4.0 and not route.Error
    p.reject()
at(plain_mesh, 600)


def point_cloud():
    """A point cloud (x y z per line, no normals) - the core on its own."""
    from mechflow_gui import scan, scan_match
    sc0 = scan.load_scan(S["path"])
    pts = sc0.cloud().P                      # points all over the surface, like a laser scan
    rng = np.random.default_rng(3)
    pts = pts + rng.normal(0, 0.3, pts.shape)
    path = SCANS + "line.xyz"
    np.savetxt(path, pts, fmt="%.3f")
    sc = scan.load_scan(path)
    res = scan.trace_scan(sc, np.array([1100, -900, 1400 + 84.15]), log=lambda *a: None,
                          flanges=scan_match.all_flanges)
    Q, _D = scan.solve_line(res["runs"], res["ends"])
    log("point cloud: OD %.1f" % res["od"], "straights", len(res["runs"]), "ends",
        [e["kind"] for e in res["ends"]])
    assert abs(res["od"] - 168.3) < 3.0 and len(res["runs"]) == 5
    for want in S["truth_pts"][1:-1]:
        dmin = min(np.linalg.norm(np.array(tuple(want)) - q) for q in Q)
        assert dmin < 6.0, (want, dmin)
at(point_cloud, 300)


def corrections():
    """Correcting a trace: warnings and fit colours shown, an end set by a
    click, undone, a report saved; a hole in the scan bridged by Carry on
    past."""
    from mechflow_gui import scan_gui
    import csv
    S["scan"].Visibility = True
    p = scan_gui.ScanPanel(S["scan"])
    Gui.Control.showDialog(p)
    p.trace_at(V(400, -900, 1400 + 84.15))
    warns = [t for t, _q in p.warns]
    fit = [S["doc"].getObject(n) for n in p.extras]
    good = S["doc"].getObject("ScanFitGood")
    log("warnings:", warns)
    log("fit objects:", [(o.Label, o.Points.CountPoints) for o in fit if hasattr(o, "Points")])
    near_hanger = [t for t, q in p.warns if q is not None
                   and np.linalg.norm(np.asarray(q) - np.array([700, -900, 1400])) < 200]
    assert near_hanger, p.warns
    assert good is not None and good.Points.CountPoints > 1000
    assert S["doc"].getObject("ScanWarnings") is not None
    assert p.table.rowCount() == 5
    # the end grips: type the pipe length at one end, drag the other
    log("pipe in the end straights:", [round(x, 1) for x in p.pipe_len])
    p.set_pipe_length(1, 500.0)
    g = p.grips[0]["arrow"]
    g.dragger.translation.setValue(150.0 / g.scale, 0, 0)
    p._tick_grips()
    p._replan(light=True)
    log("after typing 500 at the end and dragging the start 150 out:",
        [round(x, 1) for x in p.pipe_len], "ext", p.ext)
    assert abs(p.pipe_len[1] - 500.0) < 0.05 and p.ext[0] == 150
    route, sk, notes = p.make()
    pipes = sorted(round(float(o.Length), 1) for o in route.Parts
                   if getattr(o, "StdType", "").endswith("PIPE"))
    log("route pipes:", pipes, route.Error or "")
    assert not route.Error and any(abs(x - 500.0) < 0.2 for x in pipes)
    assert any(abs(x - round(p.pipe_len[0], 1)) < 0.2 for x in pipes)
    p.ext = [0.0, 0.0]
    p._replan()
    # finish the line on the top run, at x 1500
    p.set_end_at(V(1500, -900, 1400 + 84.15))
    Q = p.plan["Q"]
    log("end set: points", [tuple(round(float(x)) for x in q) for q in Q], "finishes",
        p.end_a.currentText(), "/", p.end_b.currentText())
    assert len(Q) == 4 and np.linalg.norm(Q[-1] - np.array([1500, -900, 1400])) < 5
    assert p.end_b.currentText() == "Plain"
    rep = p._save_report(SCANS + "report.csv")
    rows = list(csv.reader(open(rep, encoding="utf-8")))
    log("report rows:", len(rows), rows[1])
    assert any(r[0].startswith("Straight 1") for r in rows)
    route, sk, notes = p.make()
    log("route from the corrected line:", route.Error or "built", len(route.Parts), "parts;",
        "report on it:", len(route.ScanReport), "lines")
    assert not route.Error and len(route.ScanReport) > 5
    p._undo_fixes()
    assert len(p.plan["Q"]) == 6
    p.reject()
    assert S["doc"].getObject("ScanFitGood") is None, "fit points removed on close"
    # a hole in the scan
    S["scan"].Visibility = False
    o = scan_gui.import_scan(S["gap"])
    p = scan_gui.ScanPanel(o)
    Gui.Control.showDialog(p)
    p.trace_at(V(400, -900, 1400 + 84.15))
    before = [e["kind"] for e in p.res["ends"]]
    n0 = len(p.plan["Q"]) - 1
    p.carry_on_at(V(1050, -900, 1400 + 84.15))
    after = [e["kind"] for e in p.res["ends"]]
    log("hole: ends", before, n0, "straights -> carry on:", after, len(p.plan["Q"]) - 1,
        "straights")
    assert "open" in before and after == ["flange", "flange"] and len(p.plan["Q"]) == 6
    p.reject()
at(corrections, 600)


def reducer_line():
    """DN150 stepping down to DN100 part way across."""
    from mechflow_gui import scan_gui, routing
    pts = [V(0, 0, 0), V(0, 0, 1200), V(1100, 0, 1200), V(2400, 0, 1200), V(2400, 0, 200)]
    d, r = make_truth("ScanTruth2", pts, "DN150", [((pts[2], pts[3]), "DN100")])
    want = kinds(r)
    v, f = outside_mesh(r.Parts, 168.3)
    path = SCANS + "reducer.obj"
    write_obj(path, v, f, seed=2)
    App.closeDocument(d.Name)
    App.setActiveDocument(S["doc"].Name)
    for o in S["doc"].Objects:
        if o.isDerivedFrom("Mesh::Feature"):
            o.Visibility = False
    o = scan_gui.import_scan(path)
    p = scan_gui.ScanPanel(o)
    Gui.Control.showDialog(p)
    p.trace_at(V(500, 0, 1200 + 84.15))
    assert p.res is not None, p.error.text()
    log("reducer line: straights", [(round(2 * x["r"], 1), x["join"] and x["join"]["kind"])
                                     for x in p.res["runs"]])
    route, sk, notes = p.make()
    log("  route", route.Error or "built", "size changes", list(route.SizeChanges),
        "parts", kinds(route))
    log("  original", want)
    # traced from either end: the reducer's point is where it starts in the
    # route's direction - its big end (x 1100) or its small end
    worst = corners_match(sk, pts[:2] + pts[3:])
    red_h = routing.reducer_length("EN", "DN150", "DN100")
    xs = [q.x for q in sk.Points if abs(q.z - 1200) < 5 and 50 < q.x < 2350]
    assert len(xs) == 1 and min(abs(xs[0] - 1100), abs(xs[0] - 1100 - red_h)) < 8.0, (xs, red_h)
    log("  corners off by up to %.2f mm" % worst, [tuple(round(x) for x in q) for q in sk.Points])
    assert not route.Error and kinds(route) == want
    assert worst < 8.0          # the reducer: where its cone starts is a few mm vague
    p.reject()
at(reducer_line, 600)


def cut_elbow():
    """A leg onto a flange that isn't square (an elbow cut to 80°): with
    'Cut to suit the flanges' the route keeps the angle."""
    from mechflow_gui import scan_gui
    import math
    a = math.radians(10)
    pts = [V(0, 0, 0), V(0, 0, 1200), V(1500, 0, 1200),
           V(1500 + 700 * math.sin(a), 0, 1200 - 700 * math.cos(a))]
    d, r = make_truth("ScanTruth3", pts, "DN150")
    v, f = outside_mesh(r.Parts, 168.3)
    path = SCANS + "cut.obj"
    write_obj(path, v, f, seed=4)
    App.closeDocument(d.Name)
    App.setActiveDocument(S["doc"].Name)
    for o in S["doc"].Objects:
        if o.isDerivedFrom("Mesh::Feature"):
            o.Visibility = False
    o = scan_gui.import_scan(path)
    p = scan_gui.ScanPanel(o)
    Gui.Control.showDialog(p)
    p.trace_at(V(700, 0, 1200 + 84.15))
    assert p.res is not None, p.error.text()
    # the legs onto the flanges as measured: the elbows get cut to suit
    p.set_mode(0, "measured")
    p.set_mode(len(p.plan["Q"]) - 2, "measured")
    angs = [round(b[0], 1) for b in p.plan["bends"]]
    route, sk, notes = p.make()
    worst = corners_match(sk, pts)
    elbows = sorted(round(float(getattr(x, "BendAngle", 0) or 90), 1) for x in route.Parts
                    if "90" in getattr(x, "StdType", ""))
    log("cut elbow: bends", angs, "route", route.Error or "built", "corners off by up to %.2f mm"
        % worst, "elbow angles", elbows)
    assert not route.Error and any(abs(x - 80) < 1.5 for x in angs) and worst < 8.0
    p.reject()
at(cut_elbow, 600)


def finish():
    log("DONE")
    App.closeDocument(S["doc"].Name)
at(finish, 300)
run()
