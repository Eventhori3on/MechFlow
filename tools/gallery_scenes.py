# Builds the README gallery models with MechFlow's own tools and writes each
# one's triangles, grouped by finish, for tools/gallery_render.py. Run it like
# a GUI test:
#   MF_TESTDIR=tests/gui MF_OUT=/tmp/gallery G_SCENES=housing,weldment \
#     xvfb-run -a -s "-screen 0 1920x1080x24" freecad tools/gallery_scenes.py
# then for each scene folder:
#   xvfb-run -a <freecad>/usr/bin/python tools/gallery_render.py /tmp/gallery/<scene> <scene>.png 1600 1000
# The routing picture is the splash skid (tools/splash_scene.py writes its
# scene folder) rendered with gallery_render.py and this camera.json:
#   {"az": -24, "el": 20, "dist": 1.5, "fov": 32, "exposure": 1.25, "focus": [2350, 1000, 1900]}
# Finally python3 tools/gallery_cards.py <renders dir> docs/gallery frames
# them (the renders dir holds <scene>.png and the gallery/ scene folders).
import os, sys, json, math
sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
ROOT = OUT + "gallery/"
WANT = set(os.environ.get("G_SCENES", "housing,weldment,toolbox,exploded,stress,sketch,drawing").split(","))


# ------------------------------------------------------------ export

def tess(shape, tol):
    """Triangles with exact surface normals; each triangle is wound to agree
    with its face's outward normal (FreeCAD gives reversed faces' triangles
    the other way round)."""
    verts, norms, tris = [], [], []
    for f in shape.Faces:
        try:
            pts, fs = f.tessellate(tol)
        except Exception:
            continue
        if not fs:
            continue
        base = len(verts)
        planar = type(f.Surface).__name__ == "Plane"
        if planar:
            try:
                n0 = f.normalAt(*f.Surface.parameter(pts[0]))
            except Exception:
                n0 = None
        for p in pts:
            n = n0 if planar else None
            if n is None:
                try:
                    n = f.normalAt(*f.Surface.parameter(p))
                except Exception:
                    n = V(0, 0, 1)
            verts.append((p.x, p.y, p.z)); norms.append((n.x, n.y, n.z))
        for a, b, c in fs:
            pa, pb, pc = pts[a], pts[b], pts[c]
            tn = (pb - pa).cross(pc - pa)
            na = V(*norms[base + a]) + V(*norms[base + b]) + V(*norms[base + c])
            if tn.dot(na) < 0:
                b, c = c, b
            tris.append((a + base, b + base, c + base))
    return verts, norms, tris


def export(name, items, camera, tol=None):
    """items: [(shape, finish)] with finish a name or f(face) -> name."""
    dest = ROOT + name + "/"
    os.makedirs(dest, exist_ok=True)
    for f in os.listdir(dest):
        if f.endswith(".obj"):
            os.remove(dest + f)
    bb = App.BoundBox()
    for s, _f in items:
        bb.add(s.BoundBox)
    tol = tol or max(0.05, bb.DiagonalLength / 4000)
    groups = {}
    for shape, fin in items:
        faces = shape.Faces
        if callable(fin):
            by = {}
            for f in faces:
                by.setdefault(fin(f), []).append(f)
            parts = [(Part.Compound(fs), k) for k, fs in by.items()]
        else:
            parts = [(shape, fin)]
        for s, k in parts:
            v, nn, t = tess(s, tol)
            g = groups.setdefault(k, {"v": [], "n": [], "t": []})
            off = len(g["v"])
            g["v"] += v
            g["n"] += nn
            g["t"] += [(a + off, b + off, c + off) for a, b, c in t]
    for k, g in groups.items():
        with open(dest + k + ".obj", "w") as fh:
            for v in g["v"]:
                fh.write("v %.4f %.4f %.4f\n" % v)
            for n in g["n"]:
                fh.write("vn %.4f %.4f %.4f\n" % n)
            for t in g["t"]:
                a, b, c = t[0] + 1, t[1] + 1, t[2] + 1
                fh.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")
    json.dump(camera, open(dest + "camera.json", "w"))
    log("exported", name, {k: len(g["t"]) for k, g in groups.items()}, "bbox", bb)


def solid_of(o):
    s = o.Shape.copy()
    try:
        s.Placement = o.getGlobalPlacement()
    except Exception:
        pass
    return s


# ------------------------------------------------------------ housing (part modelling)

def housing_shape():
    """A plummer-block bearing housing: base with slotted, counterbored
    holding-down holes, a pedestal and bore boss, ribs, a machined bearing
    seat, an end-cover bolt circle and a grease boss."""
    base = Part.makeBox(300, 120, 26, V(-150, -60, 0))
    base = base.makeFillet(14, [e for e in base.Edges if abs(e.BoundBox.ZLength - 26) < 1e-6])
    zc = 150.0
    boss = Part.makeCylinder(82, 120, V(0, -60, zc), V(0, 1, 0))
    ped = Part.makeBox(170, 120, zc, V(-85, -60, 0))
    body = base.fuse(ped).fuse(boss)
    for sx in (-1, 1):                                     # ribs between base and pedestal
        rib = Part.Face(Part.makePolygon([V(sx * 85, -9, 26), V(sx * 128, -9, 26), V(sx * 85, -9, 110),
                                          V(sx * 85, -9, 26)])).extrude(V(0, 18, 0))
        body = body.fuse(rib)
    body = body.fuse(Part.makeCylinder(16, 20, V(0, 0, zc + 70)))           # grease boss
    body = body.removeSplitter()
    try:
        es = [e for e in body.Edges if e.BoundBox.ZMin > 25 and e.BoundBox.ZMax < zc - 20
              and abs(e.BoundBox.XLength) < 1e-6 and e.BoundBox.YLength > 100]
        body = body.makeFillet(10, es)
    except Exception as ex:
        log("pedestal fillet", ex)
    # bore with bearing seats, bolt circle for the end covers
    body = body.cut(Part.makeCylinder(48, 130, V(0, -65, zc), V(0, 1, 0)))
    for y0 in (-61, 36):                                   # seats for 6212 bearings (110 OD)
        body = body.cut(Part.makeCylinder(55, 25, V(0, y0, zc), V(0, 1, 0)))
    for k in range(6):
        a = math.radians(30 + 60 * k)
        x, z = 70 * math.cos(a), zc + 70 * math.sin(a)
        if z < 40:
            continue
        for y, d in ((-61, 1), (61, -1)):
            body = body.cut(Part.makeCylinder(4.2, 16, V(x, y, z), V(0, d, 0)))
    for sx in (-1, 1):                                     # slotted holding-down holes, counterbored
        x = sx * 118
        slot = Part.makeBox(24, 18, 40, V(x - 12, -9, -5)).fuse(Part.makeCylinder(9, 40, V(x - 12, 0, -5))) \
            .fuse(Part.makeCylinder(9, 40, V(x + 12, 0, -5)))
        cb = Part.makeBox(24, 30, 10, V(x - 12, -15, 18)).fuse(Part.makeCylinder(15, 10, V(x - 12, 0, 18))) \
            .fuse(Part.makeCylinder(15, 10, V(x + 12, 0, 18)))
        body = body.cut(slot).cut(cb)
    body = body.cut(Part.makeCylinder(4, 40, V(0, 0, zc + 60)))
    body = body.removeSplitter()
    return body, zc


def machined(zc):
    def f(face):
        s = type(face.Surface).__name__
        bb = face.BoundBox
        if s == "Cylinder":
            r = face.Surface.Radius
            if r < 56 and abs(face.Surface.Axis.y) > 0.99:
                return "machined"                          # bore, seats, tapped holes
            if r < 20:
                return "machined"
        if s == "Plane":
            n = face.Surface.Axis
            if abs(n.y) > 0.99 and abs(abs(bb.YMin) - 60) < 1e-3:
                return "machined"                          # faced bore ends
            if abs(n.z) > 0.99 and bb.ZMax < 1e-3:
                return "machined"                          # machined underside
            if abs(n.z) > 0.99 and abs(bb.ZMin - zc - 90) < 1e-3:
                return "machined"
        return "frame"
    return f


def housing():
    body, zc = housing_shape()
    S["housing"] = body
    log("housing valid", body.isValid(), round(body.Volume))
    # shaft and bearing so the part reads as a housing
    export("housing", [(body, machined(zc))],
           {"az": -38, "el": 24, "dist": 2.1, "fov": 28, "exposure": 1.25,
            "focus": [0, 0, 95], "shift": [0.0, 0.05]})
if "housing" in WANT:
    at(lambda: (install_hooks(), Gui.activateWorkbench("MechFlowWorkbench"), housing()), 1500)


# ------------------------------------------------------------ weldment

def line(sk, a, b):
    sk.addGeometry(Part.LineSegment(V(*a), V(*b)))


def face_near(o, normal, point, tol=3.0):
    """Name of o's planar face with this normal that contains point."""
    best = None
    for i, f in enumerate(o.Shape.Faces):
        try:                                # members' faces can be B-splines after transformGeometry
            u, v = f.Surface.parameter(point)
            n = f.normalAt(u, v)
        except Exception:
            continue
        if abs(n.dot(normal)) < 0.99:
            continue
        d = f.distToShape(Part.Vertex(point))[0]
        if d < tol and (best is None or d < best[1]):
            best = (f"Face{i+1}", d)
    return best[0] if best else None


def weldment():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Stand"); S["wd"] = doc
    from mechflow_gui import weldments as w, weld_extras as we
    X, Y = 2400.0, 1400.0
    hb = 157.6                                            # UKC 152x152x30 depth
    base = doc.addObject("Sketcher::SketchObject", "Base")
    base.Placement = App.Placement(V(0, 0, hb / 2), App.Rotation())
    for a, b in (((0, 0, 0), (X, 0, 0)), ((X, 0, 0), (X, Y, 0)), ((X, Y, 0), (0, Y, 0)), ((0, Y, 0), (0, 0, 0)),
                 ((800, 0, 0), (800, Y, 0)), ((1600, 0, 0), (1600, Y, 0))):
        line(base, a, b)
    ztop = 1500.0
    doc.recompute()
    bm = w.make("UKC", "152x152x30", [(base, [])], doc)
    bm.Rotation = 90; doc.recompute()
    log("base z", bm.Shape.BoundBox.ZMin, bm.Shape.BoundBox.ZMax)
    # posts: one 3D-ish sketch per side (XZ planes)
    post_objs = []
    for y in (0.0, Y):
        sk = doc.addObject("Sketcher::SketchObject", f"Side{int(y)}")
        sk.Placement = App.Placement(V(0, y, 0), App.Rotation(V(1, 0, 0), 90))
        for x in (0.0, X):
            line(sk, (x, hb, 0), (x, ztop, 0))
        doc.recompute()
        post_objs.append(sk)
    pm = w.make("SHS-H", "120x120x8", [(sk, []) for sk in post_objs], doc)
    top = doc.addObject("Sketcher::SketchObject", "Top")
    top.Placement = App.Placement(V(0, 0, ztop + 75), App.Rotation())
    for a, b in (((0, 0, 0), (X, 0, 0)), ((X, 0, 0), (X, Y, 0)), ((X, Y, 0), (0, Y, 0)), ((0, Y, 0), (0, 0, 0)),
                 ((1200, 0, 0), (1200, Y, 0))):
        line(top, a, b)
    doc.recompute()
    tm = w.make("RHS-H", "150x100x6.3", [(top, [])], doc)
    try:
        tm.Rotation = 90; doc.recompute()
    except Exception as ex:
        log("rot", ex)
    # knee braces on the long sides
    braces = []
    for y in (0.0, Y):
        sk = doc.addObject("Sketcher::SketchObject", f"Brace{int(y)}")
        sk.Placement = App.Placement(V(0, y, 0), App.Rotation(V(1, 0, 0), 90))
        line(sk, (60, ztop - 450, 0), (510, ztop, 0))
        line(sk, (X - 60, ztop - 450, 0), (X - 510, ztop, 0))
        doc.recompute(); braces.append(sk)
    br = w.make("EA", "70x70x7", [(sk, []) for sk in braces], doc)
    doc.recompute()
    S.update(bm=bm, pm=pm, tm=tm, br=br)
    for o in (bm, pm, tm, br):
        log("member", o.Label, len(o.Shape.Solids), o.Shape.BoundBox)
    # gussets between each corner post and the base beam
    n = 0
    for (x, y, sx, sy) in ((0, 0, 1, 1), (X, 0, -1, 1), (X, Y, -1, -1), (0, Y, 1, -1)):
        fa = face_near(pm, V(sx, 0, 0), V(x + sx * 60, y, hb + 60))
        fb = face_near(bm, V(0, 0, 1), V(x + sx * 120, y, hb))
        if fa and fb:
            try:
                we.make_gusset((pm, [fa]), (bm, [fb]), 110, 110, 10, 12); n += 1
            except Exception as ex:
                log("gusset", ex)
        log("gusset faces", fa, fb)
    log("gussets", n)
    doc.recompute()
    Gui.ActiveDocument.ActiveView.viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
    shot("g_weldment")
if "weldment" in WANT:
    at(weldment, 1500)


def weldment_export():
    doc = S["wd"]
    items = []
    for o in doc.Objects:
        tn = type(getattr(o, "Proxy", None)).__name__
        if tn in ("StructuralMember",):
            items.append((solid_of(o), "frame"))
        elif tn in ("Gusset", "EndCap"):
            items.append((solid_of(o), "yellow"))
    # a chequer-plate deck over half the top, so the frame still shows
    items.append((Part.makeBox(1200, 1400 + 100, 6, V(-50, -50, 1500 + 150)), "deck"))
    export("weldment", items, {"az": -36, "el": 22, "dist": 1.75, "fov": 30, "exposure": 1.25,
                               "shift": [0.0, 0.03]})
if "weldment" in WANT:
    at(weldment_export, 800)

# ------------------------------------------------------------ toolbox

def round_edge(o, radius, near, tol=1.0):
    """Name of o's circular edge of this radius whose centre is nearest `near`."""
    best = None
    for i, e in enumerate(o.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - radius) < tol:
            d = (c.Center - near).Length
            if best is None or d < best[1]:
                best = (f"Edge{i+1}", d, c.Center)
    return best


def finish_std(o):
    t = getattr(o, "StdType", "") or ""
    tn = type(getattr(o, "Proxy", None)).__name__
    if t.startswith("ISO15"):
        return "machined"
    if t.endswith("PIPE") or "10253" in t or "B16.9" in t:
        return "pipe"
    if t.startswith("EN1514") or t.startswith("ASMEB16.21"):
        return "gasket"
    if t.startswith("EN1092") or t.startswith("ASMEB16.5"):
        return "steel"
    if tn == "FSScrewObject" or "ISO" in o.Label or "DIN" in o.Label:
        return "bolt"
    return None


def toolbox_scene():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Spool"); S["td"] = doc
    from mechflow_gui import stdparts as sp
    pipe = sp.make(None, "EN10220-PIPE", "DN100", sp.default_rating("EN10220-PIPE"), length=520)
    doc.recompute()
    r = pipe.Shape.BoundBox.XLength / 2
    top = round_edge(pipe, r, V(0, 0, 520)); bot = round_edge(pipe, r, V(0, 0, 0))
    log("pipe", pipe.Label, pipe.Shape.BoundBox, top, bot)
    wn = sp.place(None, "EN1092-1-11", pipe, top[0])[0]; doc.recompute()
    info = sp.flange_info(wn.StdType, wn.Size, wn.Rating)
    face, n = sp._face_frame(wn)
    rf = round_edge(wn, info["face"] / 2, face)
    joint = sp.place(None, "EN1092-1-11", wn, rf[0]); doc.recompute()
    log("joint", [o.Label for o in joint])
    el = sp.place(None, "EN10253-90-3D", pipe, bot[0])[0]; doc.recompute()
    # the elbow's free end: the pipe-sized circle furthest from the pipe
    far = None
    for i, e in enumerate(el.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - r) < 0.5:
            d = c.Center.Length
            if far is None or d > far[1]:
                far = (f"Edge{i+1}", d, c.Center)
    log("elbow end", far)
    p2 = sp.place(None, "EN10220-PIPE", el, far[0], length=320)[0]; doc.recompute()
    p2end = None
    for i, e in enumerate(p2.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(c.Radius - r) < 0.5:
            d = (c.Center - far[2]).Length
            if p2end is None or d > p2end[1]:
                p2end = (f"Edge{i+1}", d, c.Center)
    wn2 = sp.place(None, "EN1092-1-11", p2, p2end[0])[0]; doc.recompute()
    face2, n2 = sp._face_frame(wn2)
    rf2 = round_edge(wn2, info["face"] / 2, face2)
    blind = sp.place(None, "EN1092-1-05", wn2, rf2[0]); doc.recompute()
    log("blind joint", [o.Label for o in blind])
    # loose catalogue parts on the floor beside the spool
    zf = min(o.Shape.BoundBox.ZMin for o in doc.Objects if hasattr(o, "Shape") and o.Shape.Solids)
    def lay(t, size, at, rot=App.Rotation(), rating=None):
        o = sp.make(None, t, size, rating if rating is not None else sp.default_rating(t))
        doc.recompute()
        o.Placement = App.Placement(V(), rot)
        doc.recompute()
        try:
            bb = o.Shape.optimalBoundingBox()
        except Exception:
            bb = o.Shape.BoundBox
        o.Placement = App.Placement(V(at[0] - bb.Center.x, at[1] - bb.Center.y, zf - bb.ZMin), rot)
        doc.recompute()
        return o
    from mechflow_gui import stdparts as _sp
    for args in (("ISO15-62", "6212", (-740, -560)), ("ISO15-62", "6208", (-300, -720)),
                 ("EN10253-TEE", "DN80", (-680, -170), App.Rotation(V(1, 0, 0), 90)),
                 ("EN1092-1-11", "DN150", (-430, -390), App.Rotation(), "PN16"),
                 ("EN10253-RED", _sp.sizes("EN10253-RED")[min(3, len(_sp.sizes("EN10253-RED")) - 1)],
                  (-930, -330), App.Rotation(V(0, 1, 0), 90))):
        try:
            S.setdefault("loose", []).append(lay(*args))
        except Exception as ex:
            log("lay", args[0], ex)
    Gui.ActiveDocument.ActiveView.viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
    shot("g_toolbox")
if "toolbox" in WANT:
    at(toolbox_scene, 1500)


def toolbox_export():
    doc = S["td"]
    items = []
    loose = S.get("loose", [])
    # the spool lies on its side, both legs on the floor, among the loose parts
    rot = App.Placement(V(), App.Rotation(V(1, 0, 0), 90))

    def placed(o):
        sh = solid_of(o)
        if o not in loose:
            sh.Placement = rot.multiply(sh.Placement)
        return sh
    shapes = {o: placed(o) for o in doc.Objects
              if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids}
    def zmin(sh):                         # tight: B-spline bounding boxes are loose
        try:
            return sh.optimalBoundingBox().ZMin
        except Exception:
            return sh.BoundBox.ZMin
    zs = min(zmin(sh) for o, sh in shapes.items() if o not in loose)
    for o, sh in shapes.items():
        f = finish_std(o)
        if f is None:
            log("skip", o.Label, o.TypeId)
            continue
        if o in loose:
            sh.translate(V(0, 0, zs - zmin(sh)))
        items.append((sh, f))
    export("toolbox", items, {"az": -24, "el": 33, "dist": 1.4, "fov": 30, "exposure": 1.3,
                              "shift": [0.0, -0.02]})


if "toolbox" in WANT:
    at(toolbox_export, 800)


# ------------------------------------------------------------ exploded assembly

def exploded_scene():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Pedestal"); S["ed"] = doc
    body, zc = housing_shape()
    hs = doc.addObject("Part::Feature", "Housing"); hs.Shape = body
    shaft = Part.makeCylinder(30, 420, V(0, -210, zc), V(0, 1, 0))
    shaft = shaft.cut(Part.makeBox(60, 10, 8, V(-30, -205, zc + 22)))      # keyway
    sh = doc.addObject("Part::Feature", "Shaft"); sh.Shape = shaft
    doc.recompute()
    from mechflow_gui import stdparts as sp
    parts = {"housing": hs, "shaft": sh}
    brgs = []
    for y in (-60 + 22, 60 - 22):                         # bearings seated against the shoulders
        b = sp.make(None, "ISO15-62", "6212", "")
        b.Placement = App.Placement(V(0, y - 11, zc), App.Rotation(V(0, 0, 1), V(0, 1, 0)))
        brgs.append(b)
    doc.recompute()
    covers = []
    for sgn in (-1, 1):
        c = Part.makeCylinder(92, 12, V(0, 0, 0)).fuse(Part.makeCylinder(54.5, 3, V(0, 0, -3)))
        c = c.cut(Part.makeCylinder(32 if sgn < 0 else 0.01, 30, V(0, 0, -5)))
        for k in range(6):
            a = math.radians(30 + 60 * k)
            c = c.cut(Part.makeCylinder(4.5, 30, V(70 * math.cos(a), 70 * math.sin(a), -5)))
        c = c.removeSplitter()
        try:
            c = c.makeFillet(2, [e for e in c.Edges if type(e.Curve).__name__ == "Circle"
                                 and abs(e.Curve.Radius - 92) < 1e-3 and e.Curve.Center.z > 1])
        except Exception:
            pass
        # local Z is the shaft axis pointing outward
        c.Placement = App.Placement(V(0, sgn * 60, zc), App.Rotation(V(0, 0, 1), V(0, sgn, 0)))
        o = doc.addObject("Part::Feature", "Cover"); o.Shape = c; covers.append((o, sgn))
        for k in range(6):
            a = math.radians(30 + 60 * k)
            sc = Part.makeCylinder(6.5, 8, V(0, 0, 12)).fuse(Part.makeCylinder(4, 28, V(0, 0, -16)))
            sc = sc.cut(Part.makeCylinder(3, 5, V(0, 0, 15.01)))          # hex socket (round)
            sc.Placement = App.Placement(V(0, sgn * 60, zc), App.Rotation(V(0, 0, 1), V(0, sgn, 0))).multiply(
                App.Placement(V(70 * math.cos(a), 70 * math.sin(a), 0), App.Rotation()))
            so = doc.addObject("Part::Feature", "Screw"); so.Shape = sc
    doc.recompute()
    from mechflow_gui import exploded
    # Exploded View's own spacing for the main parts; the shaft stays through
    # the housing and each cover's screws come off after their cover
    main = [hs] + brgs + [c for c, _s in covers]
    mv = exploded.explode_offsets(main)
    for o in main[1:]:
        mv[o] = mv[o] * 1.9                              # a wider spread reads better at gallery size
    mv[sh] = V()
    for o in doc.Objects:
        if o.Name.startswith("Screw"):
            sgn = 1 if o.Shape.BoundBox.Center.y > 0 else -1
            cov = [c for c, sg in covers if sg == sgn][0]
            mv[o] = mv[cov] + V(0, sgn * 110, 0)
    S["explode"] = mv
    log("explode", {o.Label: (round(v.x), round(v.y), round(v.z)) for o, v in mv.items()})
if "exploded" in WANT:
    at(exploded_scene, 1500)


def exploded_export():
    doc = S["ed"]; mv = S["explode"]
    items = []
    for o, v in mv.items():
        s = solid_of(o); s.translate(v)
        if o.Name.startswith("Housing"):
            body, zc = housing_shape()
            items.append((s, machined(zc)))
            continue
        f = "machined" if o.Name.startswith(("Shaft", "StdPart")) else \
            "black" if o.Name.startswith("Screw") else "frame"
        items.append((s, f))
    export("exploded", items, {"az": -62, "el": 20, "dist": 1.55, "fov": 30, "exposure": 1.25,
                               "shift": [0.0, 0.04]})
if "exploded" in WANT:
    at(exploded_export, 800)


# ------------------------------------------------------------ stress check

def stress_scene():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("HousingFEA"); S["sd"] = doc
    body, zc = housing_shape()
    # leave the small holes out of the mesh, as Stress Check does by default
    base = doc.addObject("Part::Feature", "HousingShape"); base.Shape = body
    base.ViewObject.Visibility = False
    b = doc.addObject("PartDesign::Body", "Housing"); b.BaseFeature = base
    doc.recompute()
    from mechflow_gui import material, simulation
    material.set_material(b, "Structural steel S275", 7850.0)
    fixed, seats = [], []
    for i, f in enumerate(b.Shape.Faces):
        bb = f.BoundBox
        if bb.ZLength < 1e-6 and bb.ZMax < 1e-6:
            fixed.append(f"Face{i+1}")
        if os.environ.get("G_LOADTEST") and bb.ZLength < 1e-6 and abs(bb.ZMin - zc - 90) < 1e-3:
            seats.append(f"Face{i+1}")
        if not os.environ.get("G_LOADTEST") and type(f.Surface).__name__ == "Cylinder" and abs(f.Surface.Radius - 55) < 1e-3:
            seats.append(f"Face{i+1}")
    log("fixed", fixed, "seats", seats)
    p = simulation.stress_check(); S["sp"] = p
    p.fixed = [(b, fixed)]
    p.loads = [{"type": "Force", "value": 60000.0, "direction": "-Z", "faces": [(b, [f]) for f in seats]}]
    p.pick = "fixed"
    p._refresh()
    log("panel", p.fix_list.text(), [p.load_list.item(i).text() for i in range(p.load_list.count())])
    p.quality.setCurrentText("Coarse")
    p.simple.setChecked(False)
    p._run()
if "stress" in WANT:
    at(stress_scene, 1500)


def stress_wait():
    import time
    p = S["sp"]; t0 = time.time()
    while p.solver and not p.solver.done and time.time() - t0 < 1200:
        QtWidgets.QApplication.processEvents(); time.sleep(0.2)
    QtWidgets.QApplication.processEvents()
    p._check()
    r = json.loads(p.study.Result)
    log("stress result", {k: r.get(k) for k in ("max_stress", "max_disp", "fos", "nodes")}, p.result.text()[:200])
    rd = p.rdoc
    res = [o for o in rd.Objects if o.isDerivedFrom("Fem::FemResultObject")][0]
    fm = res.Mesh.FemMesh
    import numpy as np
    vm = dict(zip(res.NodeNumbers, res.vonMises))
    smax = max(res.vonMises)
    lim = 0.6 * smax                                  # SimulationXpress-style: saturate the peak
    # the mesh's outer surface: tetrahedron faces that belong to one element only
    count = {}
    for ele in fm.Volumes:
        n = fm.getElementNodes(ele)[:4]
        for a_, b_, c_, d_ in ((0, 1, 2, 3), (0, 1, 3, 2), (0, 2, 3, 1), (1, 2, 3, 0)):
            k = tuple(sorted((n[a_], n[b_], n[c_])))
            if k in count:
                count[k] = None
            else:
                count[k] = (n[a_], n[b_], n[c_], n[d_])
    verts, tris, vals, index = [], [], [], {}
    for k, f in count.items():
        if f is None:
            continue
        a_, b_, c_, d_ = f
        pa, pb, pc, pd = (fm.getNodeById(x) for x in (a_, b_, c_, d_))
        if (pb - pa).cross(pc - pa).dot(pd - pa) > 0:     # wind outward, away from the inside node
            b_, c_ = c_, b_
        ids = []
        for nid in (a_, b_, c_):
            if nid not in index:
                q = fm.getNodeById(nid)
                index[nid] = len(verts); verts.append((q.x, q.y, q.z)); vals.append(vm.get(nid, 0.0))
            ids.append(index[nid])
        tris.append(tuple(ids))
    vals = np.clip(np.array(vals) / lim, 0, 1)
    # blue -> cyan -> green -> yellow -> red
    stops = np.array([[0.10, 0.20, 0.85], [0.05, 0.75, 0.95], [0.20, 0.85, 0.30], [0.98, 0.85, 0.10],
                      [0.92, 0.12, 0.08]])
    x = vals * (len(stops) - 1); i0 = np.clip(np.floor(x).astype(int), 0, len(stops) - 2); u = (x - i0)[:, None]
    rgb = stops[i0] * (1 - u) + stops[i0 + 1] * u
    dest = ROOT + "stress/"
    os.makedirs(dest, exist_ok=True)
    with open(dest + "fea.obj", "w") as fh:
        for v in verts:
            fh.write("v %.4f %.4f %.4f\n" % tuple(v))
        for t in tris:
            fh.write("f %d %d %d\n" % (t[0] + 1, t[1] + 1, t[2] + 1))
    np.save(dest + "fea_rgb.npy", rgb)
    json.dump({"az": -38, "el": 24, "dist": 2.1, "fov": 28, "exposure": 1.15, "coat": 0.15,
               "focus": [0, 0, 95], "shift": [0.0, 0.05], "smax": smax, "lim": lim},
              open(dest + "camera.json", "w"))
    log("stress export", len(tris), "tris, max", round(smax, 1), "MPa")
    try:
        p.accept()
    except Exception:
        pass
if "stress" in WANT:
    at(stress_wait, 2000)


# ------------------------------------------------------------ sketch

def sketch_scene():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    import Sketcher
    pv = App.ParamGet("User parameter:BaseApp/Preferences/View")
    S["font"] = pv.GetInt("EditSketcherFontSize", 17)
    pv.SetInt("EditSketcherFontSize", 22)
    doc = App.newDocument("Profile"); S["kd"] = doc
    b = new_body(doc, "Body")
    sk = b.newObject("Sketcher::SketchObject", "EndProfile")
    sk.AttachmentSupport = [([f for f in b.Origin.OriginFeatures if f.Role == "XZ_Plane"][0], "")]
    sk.MapMode = "FlatFace"
    L = lambda a, c: sk.addGeometry(Part.LineSegment(V(*a, 0), V(*c, 0)))
    l0 = L((-150, 0), (150, 0)); l1 = L((150, 0), (150, 26)); l2 = L((150, 26), (85, 26))
    l3 = L((85, 26), (85, 150))
    arc = sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 150, 0), V(0, 0, 1), 85), 0, math.pi))
    l4 = L((-85, 150), (-85, 26)); l5 = L((-85, 26), (-150, 26)); l6 = L((-150, 26), (-150, 0))
    bore = sk.addGeometry(Part.Circle(V(0, 150, 0), V(0, 0, 1), 48))
    cs = []
    C = lambda *a: cs.append(Sketcher.Constraint(*a))
    C("Coincident", l0, 2, l1, 1); C("Coincident", l1, 2, l2, 1); C("Coincident", l2, 2, l3, 1)
    C("Tangent", l3, 2, arc, 1); C("Tangent", arc, 2, l4, 1)
    C("Coincident", l4, 2, l5, 1); C("Coincident", l5, 2, l6, 1); C("Coincident", l6, 2, l0, 1)
    C("Horizontal", l2); C("Horizontal", l5); C("Vertical", l1); C("Vertical", l3); C("Vertical", l4); C("Vertical", l6)
    C("Symmetric", l0, 1, l0, 2, -2)
    C("PointOnObject", l0, 1, -1)
    C("Symmetric", l2, 2, l5, 1, -2)
    C("DistanceX", l0, 1, l0, 2, 300.0)
    C("DistanceY", l1, 1, l1, 2, 26.0)
    C("Radius", arc, 85.0)
    C("DistanceY", -1, 1, arc, 3, 150.0)
    C("Coincident", bore, 3, arc, 3)
    C("Diameter", bore, 96.0)
    # the end-cover bolt circle: six holes on a construction PCD, mirrored
    # about the centre line, the first pair set out at 30 deg
    pcd = sk.addGeometry(Part.Circle(V(0, 150, 0), V(0, 0, 1), 70), True)
    holes = []
    for k in range(6):
        a = math.radians(30 + 60 * k)
        holes.append(sk.addGeometry(Part.Circle(V(70 * math.cos(a), 150 + 70 * math.sin(a), 0), V(0, 0, 1), 4.2)))
    rays = []
    for k in (0, 5):
        a = math.radians(30 + 60 * k)
        rays.append(sk.addGeometry(Part.LineSegment(V(0, 150, 0), V(70 * math.cos(a), 150 + 70 * math.sin(a), 0)), True))
    C("Coincident", pcd, 3, arc, 3)
    C("Diameter", pcd, 140.0)
    for k in (0, 1, 4, 5):
        C("PointOnObject", holes[k], 3, pcd)
    C("Symmetric", holes[0], 3, holes[2], 3, -2)
    C("Symmetric", holes[5], 3, holes[3], 3, -2)
    C("PointOnObject", holes[1], 3, -2)
    C("PointOnObject", holes[4], 3, -2)
    for r, h, ang in ((rays[0], holes[0], 30), (rays[1], holes[5], -30)):
        C("Coincident", r, 1, arc, 3)
        C("Coincident", r, 2, h, 3)
        C("Angle", r, math.radians(ang))
    for k in range(1, 6):
        C("Equal", holes[0], holes[k])
    C("Diameter", holes[0], 8.4)
    sk.addConstraint(cs)
    # dimension text clear of the geometry
    n0 = 17                              # the profile's dimensions start here
    for idx, dist, pos in ((n0, -40.0, None), (n0 + 1, -70.0, None), (n0 + 2, 30.0, 2.6),
                           (n0 + 3, 95.0, None), (n0 + 5, None, 0.2), (n0 + 7, 60.0, -2.75),
                           (len(cs) - 1, 60.0, 1.15), (len(cs) - 7, 36.0, None), (len(cs) - 10, 36.0, None)):
        try:
            if dist is not None:
                sk.setLabelDistance(idx, dist)
            if pos is not None:
                sk.setLabelPosition(idx, pos)
        except Exception as ex:
            log("label", idx, ex)
    # the bolt circle's equal / on-circle / symmetric markers are still in
    # force but kept off screen, so the dimensions can be read
    for i, c in enumerate(sk.Constraints):
        if i >= n0 + 6 and c.Type in ("Equal", "PointOnObject", "Symmetric", "Coincident"):
            try:
                sk.setVirtualSpace(i, True)
            except Exception as ex:
                log("virtual", ex); break
    doc.recompute()
    log("sketch dof", sk.solve(), getattr(sk, "FullyConstrained", None), "malformed", sk.MalformedConstraints,
        "redundant", sk.RedundantConstraints, "conflict", sk.ConflictingConstraints)
    S["sk"] = sk
    log("editing workbench", repr(getattr(sk.ViewObject, "EditingWorkbench", None)))
    try:
        sk.ViewObject.EditingWorkbench = ""          # stay in MechFlow while editing
    except Exception:
        pass
    Gui.ActiveDocument.setEdit(sk.Name)
if "sketch" in WANT:
    at(sketch_scene, 1500)


def sketch_shot():
    sk = S["sk"]
    log("sketch fully constrained", getattr(sk, "FullyConstrained", None))
    v = Gui.ActiveDocument.ActiveView
    v.viewFront()
    Gui.SendMsgToActiveView("ViewFit")
    try:
        cam = v.getCameraNode(); cam.height.setValue(cam.height.getValue() * 1.0)
    except Exception:
        pass
    Gui.Selection.clearSelection()
    dest = ROOT + "sketch/"; os.makedirs(dest, exist_ok=True)
    v.saveImage(dest + "view.png", 1240, 760, "#f7f9fc")
    dims = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
    nd = sum(1 for c in sk.Constraints if c.Type in dims)
    from mechflow_gui import sketch_status
    status = sketch_status.FULL if getattr(sk, "FullyConstrained", False) else sketch_status.UNDER
    json.dump({"name": sk.Label, "status": status, "dof": 0 if sk.FullyConstrained else None,
               "dims": nd, "relations": len(sk.Constraints) - nd, "plane": "Front Plane"},
              open(dest + "info.json", "w"))
    App.ParamGet("User parameter:BaseApp/Preferences/View").SetInt("EditSketcherFontSize", S["font"])
    log("sketch view saved")
if "sketch" in WANT:
    at(sketch_shot, 1500)
    at(lambda: (Gui.ActiveDocument.resetEdit(), App.closeDocument(S["kd"].Name)), 800)


# ------------------------------------------------------------ drawing

def drawing_scene():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("BearingHousing"); S["dd"] = doc
    body, zc = housing_shape()
    S["zc"] = zc
    base = doc.addObject("Part::Feature", "HousingShape"); base.Shape = body
    b = doc.addObject("PartDesign::Body", "Bearing_Housing"); b.BaseFeature = base
    b.Label = "Bearing Housing"
    doc.recompute(); base.ViewObject.Visibility = False
    S["db"] = b
    from mechflow_gui import material, drawings
    material.set_material(b, "Cast iron EN-GJL-250", 7200.0)
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetString("prefAuthor", "MechFlow")
    S["dlg_sheet"] = "A2 (ISO) - Landscape"

    def fake_exec(self):
        items = self.list.findItems(S["dlg_sheet"], drawings._match()); self.list.setCurrentItem(items[0])
        return True
    drawings.SheetDialog.exec = fake_exec
    Gui.Selection.clearSelection(); Gui.Selection.addSelection(doc.Name, b.Name)
    S["page"] = drawings.make_drawing()
if "drawing" in WANT:
    at(drawing_scene, 1500)


def _hlines(view):
    """y of the view's horizontal edges, with their x span (model units)."""
    out = []
    for e in view.getVisibleEdges():
        p, q = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if abs(p.y - q.y) < 1e-6 and abs(p.x - q.x) > 1e-6:
            out.append((round(p.y, 3), min(p.x, q.x), max(p.x, q.x)))
    return out


def drawing_more():
    """Section A-A through the bore, a detail of the bearing seat, centre
    marks, notes and a surface finish note: a full engineering sheet."""
    import TechDraw
    from mechflow_gui import sheet_tools, drawing_pack as dp
    doc, page, b, zc = S["dd"], S["page"], S["db"], S["zc"]
    g = [v for v in page.Views if v.TypeId == "TechDraw::DrawProjGroup"][0]
    views = {v.Label: v for v in g.Views}
    front = views["Front"]
    log("views", {k: (round(float(v.X)), round(float(v.Y))) for k, v in views.items()}, "group", g.X, g.Y,
        "front dir", front.Direction, front.XDirection)
    iso = [v for v in page.Views if v.Label == "Isometric"]
    if iso:
        iso[0].Scale = 0.4
        iso[0].X, iso[0].Y = 492, 300
    # the projection group moves left to make room for the section and detail
    g.X, g.Y = 215, 272
    top = views.get("Top")
    if top is not None:
        top.Y = float(top.Y) - 18          # more room between the front and top views
    sec = doc.addObject("TechDraw::DrawViewSection", "SectionA")
    page.addView(sec)
    sec.BaseView = front
    sec.Source = front.Source
    sec.ScaleType = "Custom"; sec.Scale = 0.5
    sec.SectionSymbol = "A"
    sec.SectionOrigin = V(0, 0, zc)
    sec.SectionNormal = V(-1, 0, 0)
    sec.Direction = V(-1, 0, 0)
    sec.XDirection = V(0, -1, 0)
    try:
        sec.SectionDirection = "Left"
    except Exception as ex:
        log("secdir", ex)
    sec.X, sec.Y = 352, 283
    for v in (front, sec):
        try:
            v.ArcCenterMarks = True
        except Exception:
            pass
    doc.recompute()
    S["sec"] = sec
if "drawing" in WANT:
    at(drawing_more, 6000)


def drawing_detail():
    import TechDraw
    from mechflow_gui import sheet_tools, drawing_pack as dp
    doc, page, sec, zc = S["dd"], S["page"], S["sec"], S["zc"]
    k = 0.5
    made = []
    ext = dp._view_extent(sec)
    if ext:
        try:
            d = TechDraw.makeExtentDim(sec, [], 0)
            d.X, d.Y = 0.5 * (ext[0] + ext[1]) * k, ext[2] * k - 12
            made.append(d)
        except Exception as ex:
            log("extent", ex)
    dp._drop_invalid(made)
    # detail C: a slotted, counterbored holding-down hole, from the top view
    g = [v for v in page.Views if v.TypeId == "TechDraw::DrawProjGroup"][0]
    top = [v for v in g.Views if v.Label == "Top"][0]
    det = doc.addObject("TechDraw::DrawViewDetail", "DetailC")
    page.addView(det)
    det.BaseView = top
    det.Source = top.Source
    det.Direction = top.Direction
    det.XDirection = top.XDirection
    det.AnchorPoint = V(114.0, 0.0, 0)
    det.Radius = 30.0
    det.Reference = "C"
    det.ScaleType = "Custom"; det.Scale = 1.0
    det.X, det.Y = 352, 120
    doc.recompute()
    S["det"] = det
    try:
        dd = TechDraw.makeExtentDim(det, [], 0)
        e2 = dp._view_extent(det)
        if e2:
            dd.X, dd.Y = 0.5 * (e2[0] + e2[1]), e2[2] - 10
        dp._drop_invalid([dd])
    except Exception as ex:
        log("detail dim", ex)
    # notes and the general finish
    # view captions
    for x, y, txt in ((352, 186, "SECTION A-A"), (352, 78, "DETAIL C   SCALE 1:1"),
                      (492, 222, "ISOMETRIC   SCALE 1:2.5")):
        c = sheet_tools.add_text_box(page, x, y, txt)
        c.TextSize = 5.0
    notes = sheet_tools.add_text_box(page, 480, 170, "NOTES:")
    notes.Text = ["NOTES:",
                  "1. MATERIAL: CAST IRON EN-GJL-250.",
                  "2. BEARING SEATS \u00d8110 H7, Ra 1.6.",
                  "3. FACED ENDS AND BASE Ra 3.2.",
                  "4. REMOVE ALL SHARP EDGES 0.5 x 45\u00b0.",
                  "5. GENERAL TOLERANCES ISO 2768-m.",
                  "6. PAINT RAL 5005 EXCEPT MACHINED FACES."]
    notes.TextSize = 5.0
    try:
        notes.Font = "osifont"
    except Exception:
        pass
    doc.recompute()
    log("detail", det.isValid(), "anchor", det.AnchorPoint, "notes", notes.Label)
if "drawing" in WANT:
    at(drawing_detail, 6000)


def drawing_pdf():
    import TechDrawGui
    p = S["page"]
    S["dd"].recompute()
    dest = ROOT + "drawing/"; os.makedirs(dest, exist_ok=True)
    TechDrawGui.exportPageAsPdf(p, dest + "drawing.pdf")
    kinds = [v.TypeId for v in p.Views]
    nviews = sum(1 for v in p.Views if v.TypeId in ("TechDraw::DrawViewPart", "TechDraw::DrawViewSection",
                                                    "TechDraw::DrawViewDetail"))
    for g in p.Views:
        if g.TypeId == "TechDraw::DrawProjGroup":
            nviews += len(g.Views)
    json.dump({"title": "Bearing Housing", "sheet": "A2", "scale": "1:2", "views": nviews,
               "dims": kinds.count("TechDraw::DrawViewDimension")}, open(dest + "info.json", "w"))
    log("drawing pdf", os.path.getsize(dest + "drawing.pdf"), "views", [v.Label for v in p.Views][:12])
if "drawing" in WANT:
    at(drawing_pdf, 8000)

run()
