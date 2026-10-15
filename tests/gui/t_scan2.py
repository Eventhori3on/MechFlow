import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# After Pipe from Scan: Remove from Scan takes the modelled pipe out of a
# copy of the scan (the floor and a post beside the pipe stay); a Scan
# Reference View goes on a drawing in the colours chosen and updates; Save
# Part As saves a pipe on its own at its own origin, as FreeCAD and STEP.
from h import *
import Part, shutil
import numpy as np
V = App.Vector
S = {}
D = OUT + "scan2-files/"
shutil.rmtree(D, ignore_errors=True)
os.makedirs(D, exist_ok=True)
os.environ["MF_SCAN_CACHE"] = D + "cache"


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    from mechflow_gui import routing, sketch3d, scan_gui
    routing.install()
    doc = App.newDocument("Scan2")
    S["doc"] = doc
    sk = sketch3d.make(None, "Line")
    ed = sketch3d.Editor(sk)
    pts = [V(0, 0, 0), V(0, 0, 1200), V(1600, 0, 1200), V(1600, 900, 1200)]
    ed.start(pts[0])
    for q in pts[1:]:
        ed.line_to(q)
    ed.save()
    r = routing.make_route(None, [(sk, None)], "EN", "DN150", "", "3D", "Weld neck flange", "PN16")
    doc.recompute()
    assert not r.Error, r.Error
    S["route"] = r
    # a "scan" of it: its outside, a floor, a post close by
    shapes = [p.Shape for p in r.Parts] + [Part.makeBox(3000, 3000, 20, V(-700, -1000, -300)),
                                           Part.makeBox(80, 80, 1300, V(400, 160, -280))]
    Vs, Fs, n = [], [], 0
    for sh in shapes:
        for f in sh.Faces:
            s_ = f.Surface
            if type(s_).__name__ in ("Cylinder", "Toroid") and \
                    getattr(s_, "Radius", getattr(s_, "MinorRadius", 999)) < 80:
                continue                      # bores
            p_, t_ = f.tessellate(0.4)
            if t_:
                Vs.append(np.array([(q.x, q.y, q.z) for q in p_]))
                Fs.append(np.array(t_) + n)
                n += len(p_)
    v, f = np.vstack(Vs), np.vstack(Fs)
    path = D + "scan.obj"
    with open(path, "w") as fh:
        fh.write("".join("v %.3f %.3f %.3f\n" % tuple(q) for q in v))
        fh.write("".join("f %d %d %d\n" % tuple(t + 1) for t in f))
    S["scan"] = scan_gui.import_scan(path)
    log("route parts", len(r.Parts), "scan triangles", len(f))
at(setup, 1500)


def remove():
    from mechflow_gui import scan_extras, scan_gui
    o2 = scan_extras.remove_from_scan(S["scan"], [S["route"]], margin=20.0)
    S["clean"] = o2
    sc = scan_gui.scan_of(o2)
    C = (sc.V[sc.F[:, 0]] + sc.V[sc.F[:, 1]] + sc.V[sc.F[:, 2]]) / 3
    # left: nothing on the pipe's straights (radius 84 round the line)
    def near_pipe(c):
        a, b = np.array([0, 0, 300.0]), np.array([0, 0, 900.0])          # mid riser
        d = c - a
        t = np.clip(d @ (b - a) / ((b - a) @ (b - a)), 0, 1)
        e = c - (a + np.outer(t, b - a))
        return np.abs(np.linalg.norm(e, axis=1) - 84.15) < 10
    on_pipe = int(near_pipe(C).sum())
    floor = int((np.abs(C[:, 2] + 280) < 25).sum())
    post = int(((C[:, 0] > 395) & (C[:, 0] < 485) & (C[:, 1] > 155) & (C[:, 1] < 245)
                & (C[:, 2] > 0) & (C[:, 2] < 900)).sum())
    log("removed", o2.RemovedCount, "left", len(sc.F), "| on the pipe:", on_pipe, "floor:", floor,
        "post:", post, "| original hidden:", not S["scan"].Visibility, "| file:",
        os.path.basename(o2.ScanFile))
    assert o2.RemovedCount > 1000 and on_pipe == 0 and floor > 0 and post > 0
    assert not S["scan"].Visibility and os.path.exists(o2.ScanFile)
    assert list(o2.RemovedFor) == [S["route"]]
at(remove, 600)


def colours_in(path):
    img = QtGui.QImage(path)
    w, h = img.width(), img.height()
    red = green = blue = 0
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            c = img.pixelColor(x, y)
            r_, g_, b_ = c.red(), c.green(), c.blue()
            if r_ > 150 and g_ < 90 and b_ < 90:
                red += 1
            elif g_ > 120 and r_ < 100 and b_ < 100:
                green += 1
            elif b_ > 150 and r_ < 90 and g_ < 120:
                blue += 1
    return w, h, red, green, blue


from PySide6 import QtGui


def ref_view():
    from mechflow_gui import scan_extras, drawings
    doc = S["doc"]
    page = drawings.new_page(doc, "A3 (ISO) - Landscape")
    doc.recompute()
    s = {"scans": [S["clean"].Name], "routes": [S["route"].Name], "view": "Isometric",
         "scan_colour": [0.9, 0.1, 0.1], "scan_opacity": 100, "pipe_colour": [0.1, 0.75, 0.1],
         "others": False}
    img = scan_extras.add_reference_view(page, s)
    S["img"] = img
    w, h, red, green, blue = colours_in(img.ImageFile)
    log("reference view:", img.TypeId, os.path.basename(img.ImageFile), f"{w}x{h}",
        "on the sheet", round(float(img.Width)), "x", round(float(img.Height)), "mm | red (scan)",
        red, "green (pipe)", green, "| title:", img.TitleNote.Text if img.TitleNote else None)
    assert img in page.Views and red > 50 and green > 20
    # sized to fit: about 38 % of the A3 width, inside the frame, top right
    sw, sh = scan_extras._shown_size(img)
    x, y = float(img.X), float(img.Y)
    log("shown at", round(sw), "x", round(sh), "mm, centre", round(x), round(y))
    assert 100 < sw <= 0.38 * 420 + 1 and sh <= 0.45 * 297 + 1
    assert x + sw / 2 <= 410 and y + sh / 2 <= 287 and x - sw / 2 > 150
    S["shown"] = sw
    # the scan's own colour and transparency are back as they were
    assert S["clean"].ViewObject.Transparency == 45
    import json
    s["scan_colour"] = [0.1, 0.2, 0.95]
    img.ScanViewSettings = json.dumps(s)
    scan_extras.update_reference_view(img)
    w, h, red, green, blue = colours_in(img.ImageFile)
    log("updated: red", red, "blue (scan now)", blue, "green", green)
    assert blue > 50 and red < 20
    assert abs(scan_extras._shown_size(img)[0] - S["shown"]) < 1
at(ref_view, 600)


def save_part():
    from mechflow_gui import scan_extras
    pipe = [o for o in S["route"].Parts if getattr(o, "StdType", "").endswith("PIPE")][0]
    name = scan_extras.part_file_name(pipe)
    stp = scan_extras.save_part(pipe, D + name + ".step")
    fc = scan_extras.save_part(pipe, D + name + ".FCStd")
    sh = Part.read(stp)
    d2 = App.openDocument(fc)
    objs = [o for o in d2.Objects if hasattr(o, "Shape") and not o.Shape.isNull()]
    o = objs[0]
    log("saved", name, "| STEP volume", round(sh.Volume), "vs", round(pipe.Shape.Volume),
        "| FCStd:", o.Label, getattr(o, "StdType", "?"), "at origin:",
        o.Placement.isIdentity(), round(o.Shape.Volume))
    assert abs(sh.Volume - pipe.Shape.Volume) < 1 and abs(o.Shape.Volume - pipe.Shape.Volume) < 1
    assert o.Placement.isIdentity() and getattr(o, "StdType", "") == pipe.StdType
    App.closeDocument(d2.Name)
    App.setActiveDocument(S["doc"].Name)
at(save_part, 300)


def finish():
    log("DONE")
    App.closeDocument(S["doc"].Name)
at(finish, 300)
run()
