# Builds the splash-screen showcase model (a small process skid) with
# MechFlow's own tools - nozzles, Toolbox flanges, a 3D Sketch, Route Pipe,
# valves - then writes its triangles, grouped by finish, for
# tools/splash_render.py.  Run it like a GUI test:
#   MF_TESTDIR=tests/gui MF_OUT=/tmp/splash xvfb-run freecad tools/splash_scene.py
# then (FreeCAD's Python has VTK):
#   MF_MODE=height xvfb-run <freecad>/usr/bin/python tools/splash_render.py /tmp/splash/scene height.npy
#   python3 tools/splash_floor.py height.npy floor.png
#   MF_FLOOR=floor.png MF_SHIFT_X=-0.47 MF_SHIFT_Y=0.06 MF_DIST=11900 MF_AZ=-45 MF_EL=21 \
#     MF_EXPOSURE=1.35 xvfb-run <freecad>/usr/bin/python tools/splash_render.py /tmp/splash/scene art.png 2720 1600
#   (shrink art.png to 1360 x 800 -> Resources/splash/SplashArt.jpg)
#   python3 tools/make_splash.py <version>
import os, sys, json
sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
DEST = OUT + "scene/"
os.makedirs(DEST, exist_ok=True)


def part(doc, name, shape, finish):
    o = doc.addObject("Part::Feature", name)
    o.Shape = shape
    o.addProperty("App::PropertyString", "Finish")
    o.Finish = finish
    return o


def ibeam(p0, p1, h=203.0, b=133.0, tw=6.4, tf=9.6):
    """UB-ish I-beam from p0 to p1 (web vertical)."""
    d = p1 - p0
    L = d.Length
    pts = [V(-b / 2, 0, 0), V(b / 2, 0, 0), V(b / 2, 0, tf), V(tw / 2, 0, tf), V(tw / 2, 0, h - tf),
           V(b / 2, 0, h - tf), V(b / 2, 0, h), V(-b / 2, 0, h), V(-b / 2, 0, h - tf),
           V(-tw / 2, 0, h - tf), V(-tw / 2, 0, tf), V(-b / 2, 0, tf), V(-b / 2, 0, 0)]
    f = Part.Face(Part.makePolygon(pts))
    s = f.extrude(V(0, L, 0))
    rot = App.Rotation(V(0, 1, 0), d)
    s.Placement = App.Placement(p0, rot)
    return s


def flange_disc(centre, axis, od, t, pcd, nb, hole):
    """A plain flange with its bolt holes (for the bought-in equipment)."""
    f = Part.makeCylinder(od / 2, t)
    for i in range(nb):
        a = 2 * math.pi * (i + 0.5) / nb
        f = f.cut(Part.makeCylinder(hole / 2, t, V(pcd / 2 * math.cos(a), pcd / 2 * math.sin(a), 0)))
    f.Placement = App.Placement(centre, App.Rotation(V(0, 0, 1), axis))
    return f


def build():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Skid"); S["doc"] = doc
    # --- skid base: perimeter and cross beams, 4200 x 2000
    beams = []
    X, Y = 4200.0, 2000.0
    for y in (0.0, Y):
        beams.append(ibeam(V(0, y, 0), V(X, y, 0)))
    for x in (66.0, 1300.0, 2400.0, 3300.0, X - 66):
        beams.append(ibeam(V(x, 66, 0), V(x, Y - 66, 0)))
    # support steel: under the vessel's legs and the exchanger's saddles
    for y in (1000 - 368.0, 1000 + 368.0):
        beams.append(ibeam(V(66, y, 0), V(1300, y, 0)))
    beams.append(ibeam(V(1300, 1650, 0), V(3300, 1650, 0)))
    for i, b in enumerate(beams):
        part(doc, f"Beam{i}", b, "frame")
    # lifting lugs at the corners
    for x in (300.0, X - 300):
        for y in (-7.0, Y + 7):
            lug = Part.makeBox(120, 20, 140, V(x - 60, y - 10, 203))
            lug = lug.cut(Part.makeCylinder(25, 20, V(x, y - 10, 203 + 85), V(0, 1, 0)))
            part(doc, "Lug", lug, "frame")
    # chequer-plate deck under the pump
    deck = Part.makeBox(1650, 1800, 6, V(2420, 100, 203))
    part(doc, "Deck", deck, "deck")

    # --- vertical vessel (PartDesign body, so MechFlow nozzles go on it)
    def vessel_solid(r, h, z0, depth, cx=900.0, cy=1000.0):
        """Shell radius r, straight from z0 up h, 2:1 heads depth deep."""
        z1 = z0 + h
        e0 = Part.Ellipse(V(cx + r, cy, z0), V(cx, cy, z0 - depth), V(cx, cy, z0)).toShape(0, math.pi / 2)
        e1 = Part.Ellipse(V(cx + r, cy, z1), V(cx, cy, z1 + depth), V(cx, cy, z1)).toShape(0, math.pi / 2)
        l0 = Part.LineSegment(V(cx + r, cy, z0), V(cx + r, cy, z1)).toShape()
        l1 = Part.LineSegment(V(cx, cy, z1 + depth), V(cx, cy, z0 - depth)).toShape()
        w = Part.Wire(Part.__sortEdges__([e0, l0, e1, l1]))
        return Part.Face(w).revolve(V(cx, cy, 0), V(0, 0, 1), 360)
    shellsh = vessel_solid(600, 1800, 1000, 300).cut(vessel_solid(588, 1800, 1000, 288)).Solids[0]
    vs = part(doc, "VesselShell", shellsh, "paint")
    vs.ViewObject.Visibility = False
    b = doc.addObject("PartDesign::Body", "Vessel")
    b.BaseFeature = vs
    doc.recompute()
    from mechflow_gui import nozzle, stdparts
    n1 = nozzle.make(b, V(1500, 1000, 1250), V(1, 0, 0), "EN 10220", "DN100", "", 200)
    n2 = nozzle.make(b, V(900, 1000, 3000), V(0, 0, 1), "EN 10220", "DN80", "", 150)
    n3 = nozzle.make(b, V(900, 400, 2100), V(0, -1, 0), "EN 10220", "DN450", "", 180)
    n4 = nozzle.make(b, V(1325, 1425, 2400), V(0.7071, 0.7071, 0), "EN 10220", "DN50", "", 150)
    doc.recompute()
    fl1 = nozzle.add_flange(n1, "EN1092-1-11", "PN16")[0]
    fl2 = nozzle.add_flange(n2, "EN1092-1-11", "PN16")[0]
    fl3 = nozzle.add_flange(n3, "EN1092-1-11", "PN16")[0]
    nozzle.add_flange(n4, "EN1092-1-11", "PN16")
    doc.recompute()
    # the manway gets a blind cover with a gasket and studs
    face3, n3d = stdparts._face_frame(fl3)
    info = stdparts.flange_info(fl3.StdType, fl3.Size, fl3.Rating)
    od = float(info.get("D", info.get("OD", 670)))
    pcd = float(info.get("K", info.get("PCD", 620)))
    nb = int(info.get("n", info.get("bolts", 20)))
    part(doc, "ManwayGasket", flange_disc(face3, n3d, float(info.get("face", 550)), 3, 0, 0, 0), "gasket")
    cover = flange_disc(face3 + n3d * 3, n3d, od, 40, pcd, 0, 0)
    part(doc, "ManwayCover", cover, "steel")
    part(doc, "ManwayHandle", Part.makeTorus(70, 12, face3 + n3d * 60, n3d).common(
        Part.makeBox(400, 400, 400, face3 + n3d * 43 - V(200, 200, 200))), "steel")
    for i in range(nb):
        a = 2 * math.pi * (i + 0.5) / nb
        u = n3d.cross(V(0, 0, 1)); u.normalize() if u.Length > 1e-6 else None
        w = n3d.cross(u)
        c = face3 + (u * math.cos(a) + w * math.sin(a)) * (pcd / 2)
        part(doc, "Stud", Part.makeCylinder(12, 130, c - n3d * 60, n3d), "bolt")
        part(doc, "Nut", Part.makeCylinder(20, 22, c + n3d * 43, n3d), "bolt")
    S["fl1"], S["fl2"] = fl1, fl2
    # legs: four pipe legs with base plates
    for a in (45, 135, 225, 315):
        r = math.radians(a)
        cx, cy = 900 + 520 * math.cos(r), 1000 + 520 * math.sin(r)
        leg = Part.makeCylinder(84, 1000 - 203 + 120, V(cx, cy, 203)).cut(Part.makeCylinder(76, 1000, V(cx, cy, 203)))
        part(doc, "Leg", leg, "paint")
        part(doc, "LegPlate", Part.makeBox(260, 260, 16, V(cx - 130, cy - 130, 203)), "paint")
        for dx in (-95, 95):                              # hold-down bolts into the beam flange
            part(doc, "HoldDown", Part.makeCylinder(10, 40, V(cx + dx, cy, 203)).fuse(
                Part.makeCylinder(17, 14, V(cx + dx, cy, 219))), "bolt")

    # --- pump P-101 on the deck: baseplate, casing, coupling guard, motor
    pz = 650.0                                           # shaft centre height
    part(doc, "PumpBase", Part.makeBox(1450, 560, 90, V(2560, 720, 209)), "frame")
    vol = Part.makeCylinder(260, 170, V(2880, 1000, pz), V(1, 0, 0))
    vol = vol.fuse(Part.makeCylinder(150, 160, V(2720, 1000, pz), V(1, 0, 0)))          # suction neck
    vol = vol.fuse(Part.makeCylinder(57, 170, V(2600, 1000, pz), V(1, 0, 0)))
    vol = vol.fuse(Part.makeBox(150, 140, 230, V(2890, 930, pz + 150)))               # discharge neck
    vol = vol.fuse(Part.makeCylinder(46, 120, V(2965, 1000, pz + 370), V(0, 0, 1)))
    vol = vol.fuse(Part.makeBox(140, 440, 380, V(2900, 780, 299)))                    # foot
    vol = vol.fuse(Part.makeCylinder(120, 260, V(3050, 1000, pz), V(1, 0, 0)))        # bearing housing
    try:
        vol = vol.removeSplitter()
    except Exception:
        pass
    part(doc, "PumpCasing", vol, "pump")
    sfl = flange_disc(V(2580, 1000, pz), V(-1, 0, 0), 220, 20, 180, 8, 18)
    part(doc, "PumpSuctionFlange", sfl, "pump")
    dfl = flange_disc(V(2965, 1000, pz + 490), V(0, 0, 1), 200, 20, 160, 8, 18)
    part(doc, "PumpDischargeFlange", dfl, "pump")
    guard = Part.makeBox(360, 240, 300, V(3310, 880, pz - 160))
    try:
        guard = guard.makeFillet(30, guard.Edges)
    except Exception:
        pass
    part(doc, "CouplingGuard", guard, "accent")
    motor = Part.makeCylinder(210, 640, V(3670, 1000, pz), V(1, 0, 0))
    for i in range(24):                                   # cooling fins
        a = 2 * math.pi * i / 24
        fin = Part.makeBox(560, 8, 30, V(0, -4, 200))
        fin.rotate(V(0, 0, 0), V(1, 0, 0), math.degrees(a))
        fin.translate(V(3710, 1000, pz))
        motor = motor.fuse(fin)
    motor = motor.fuse(Part.makeCylinder(200, 120, V(4310, 1000, pz), V(1, 0, 0)))   # fan cowl
    motor = motor.fuse(Part.makeBox(180, 180, 150, V(3880, 1000 - 90, pz + 210)))     # terminal box
    motor = motor.fuse(Part.makeBox(560, 400, 260 - 205 + pz - 210 - 299 + 100, V(3700, 800, 299)))
    try:
        motor = motor.removeSplitter()
    except Exception:
        pass
    part(doc, "Motor", motor, "motor")
    S["pump_suction"] = V(2580, 1000, pz)
    S["pump_discharge"] = V(2965, 1000, pz + 510)

    # --- heat exchanger E-101 along the back
    ex_z, ex_y = 1250.0, 1650.0
    shell = Part.makeCylinder(230, 1900, V(1700, ex_y, ex_z), V(1, 0, 0))
    for x, d in ((1600.0, -1), (3600.0, 1)):
        ch = Part.makeCylinder(240, 100, V(x, ex_y, ex_z), V(1, 0, 0))
        ch = ch.fuse(Part.makeSphere(240, V(x + 50 + d * 50, ex_y, ex_z)).common(
            Part.makeBox(240, 600, 600, V(x + (100 if d > 0 else -240), ex_y - 300, ex_z - 300))))
        shell = shell.fuse(ch)
    part(doc, "Exchanger", shell, "paint")
    for x in (1700.0, 3500.0):
        part(doc, "ExFlange", flange_disc(V(x - 40, ex_y, ex_z), V(1, 0, 0), 560, 40, 500, 20, 26), "steel")
        for i in range(20):
            a = 2 * math.pi * (i + 0.5) / 20
            p = V(x - 75, ex_y + 250 * math.cos(a), ex_z + 250 * math.sin(a))
            part(doc, "ExBolt", Part.makeCylinder(11, 110, p, V(1, 0, 0)), "bolt")
    for x in (1950.0, 3250.0):                            # saddles
        sad = Part.makeBox(120, 420, ex_z - 203 - 16, V(x - 60, ex_y - 210, 219))
        sad = sad.fuse(Part.makeBox(260, 460, 16, V(x - 130, ex_y - 230, 203)))      # base plate
        sad = sad.cut(Part.makeCylinder(232, 200, V(x - 100, ex_y, ex_z), V(1, 0, 0)))
        part(doc, "Saddle", sad, "paint")
    for x in (2050.0, 3150.0):                            # shell nozzles, flanged
        part(doc, "ExNozzle", Part.makeCylinder(45, 220, V(x, ex_y, ex_z + 200)), "steel")
        part(doc, "ExNozFl", flange_disc(V(x, ex_y, ex_z + 400), V(0, 0, 1), 200, 20, 160, 8, 18), "steel")
    doc.recompute()
    Gui.SendMsgToActiveView("ViewFit"); Gui.ActiveDocument.ActiveView.viewIsometric()
at(build, 1500)


def flange_face_edge(fl):
    from mechflow_gui import stdparts
    face, n = stdparts._face_frame(fl)
    f = stdparts.flange_info(fl.StdType, fl.Size, fl.Rating)
    best = None
    for i, e in enumerate(fl.Shape.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ == "Circle" and abs(2 * c.Radius - f["face"]) < 1e-3:
            d = (c.Center - face).Length
            if best is None or d < best[1]:
                best = (f"Edge{i+1}", d)
    return face, best[0]


def pipes():
    from mechflow_gui import sketch3d, routing
    routing.install()
    # suction: vessel N1 -> along X -> down -> pump suction
    face, edge = flange_face_edge(S["fl1"])
    log("N1 face", face)
    ps = S["pump_suction"]
    sk = sketch3d.make(None, "Suction line")
    ed = sketch3d.Editor(sk)
    ed.start(face, (S["fl1"], edge))
    ed.line_along(V(1, 0, 0), 2220 - face.x)
    ed.line_along(V(0, 0, -1), face.z - ps.z)
    ed.line_along(V(1, 0, 0), ps.x - 2220 - 3)
    ed.save()
    r1 = routing.make_route(None, [(sk, None)], "EN", "DN100", "", "3D", "Weld neck flange", "PN16",
                            [(S["fl1"], edge)])
    S["r1"] = r1
    # discharge: vessel top N2 -> up -> over -> down to the pump
    face2, edge2 = flange_face_edge(S["fl2"])
    pd = S["pump_discharge"]
    sk2 = sketch3d.make(None, "Discharge line")
    ed = sketch3d.Editor(sk2)
    ed.start(face2, (S["fl2"], edge2))
    ed.line_along(V(0, 0, 1), 3700 - face2.z)
    ed.line_along(V(1, 0, 0), pd.x - face2.x)
    ed.line_along(V(0, 0, -1), 3700 - pd.z - 3)
    ed.save()
    r2 = routing.make_route(None, [(sk2, None)], "EN", "DN80", "", "3D", "Weld neck flange", "PN16",
                            [(S["fl2"], edge2)])
    S["r2"] = r2
    log("routes", len(r1.Parts), r1.Error, "|", len(r2.Parts), r2.Error)
at(pipes, 2000)


def valves():
    from mechflow_gui import inline
    p = inline.valves_and_instruments(); S["p"] = p
    face, _e = flange_face_edge(S["fl1"])
    def put(route, pt, kind, ang):
        p.angle.setValue(ang)
        c = p.place_at(route, pt, kind=kind)
        ok = c.isValid() if c else False
        log(kind, "placed" if ok else "REFUSED", p.error.isVisible() and p.error.text()[:120])
        return c
    put(S["r1"], V(face.x + 2220 - face.x - 0, 1000, (face.z + S["pump_suction"].z) / 2), "Butterfly valve", 0)
    pd = S["pump_discharge"]
    face2, _e2 = flange_face_edge(S["fl2"])
    put(S["r2"], V((face2.x + pd.x) / 2, 1000, 3700), "Gate valve", 0)
    put(S["r2"], V(pd.x, 1000, pd.z + 1250), "Check valve", 0)
    put(S["r2"], V(pd.x, 1000, pd.z + 2000), "Ball valve", 90)
    put(S["r2"], V(pd.x, 1000, pd.z + 420), "Pressure gauge", -90)
    p.accept()
    Gui.SendMsgToActiveView("ViewFit")
at(valves, 1500)
at(lambda: shot("skid"), 1500)


def finish_of(o):
    f = getattr(o, "Finish", "")
    if f:
        return f
    t = getattr(o, "StdType", "") or ""
    k = getattr(o, "Kind", "") or ""
    tn = type(getattr(o, "Proxy", None)).__name__
    if k:
        return "gauge" if "gauge" in k.lower() or "sensor" in k.lower() else "valve"
    if t.endswith("PIPE") or "10253" in t:
        return "pipe"
    if t.startswith("EN1514"):
        return "gasket"
    if t.startswith("EN1092") or t.startswith("ASMEB16.5"):
        return "steel"
    if tn == "FSScrewObject" or "ISO" in o.Label or "4014" in o.Label or "4032" in o.Label:
        return "bolt"
    if o.TypeId.startswith("PartDesign::Body"):
        return "paint"
    return None


def export():
    doc = S["doc"]
    groups = {}
    seen = 0
    for o in doc.Objects:
        if not hasattr(o, "Shape") or o.Shape.isNull() or not o.Shape.Faces:
            continue
        if o.TypeId.startswith("PartDesign::") and not o.TypeId.endswith("Body"):
            continue                                      # body features: the body has them
        if o.TypeId == "Sketcher::SketchObject" or "Sketch3D" in type(getattr(o, "Proxy", None)).__name__:
            continue
        vo = getattr(o, "ViewObject", None)
        if vo is not None and not vo.Visibility:
            continue
        fin = finish_of(o)
        if fin is None:
            log("skip", o.Label, o.TypeId)
            continue
        try:
            sh = o.Shape.copy()
            gpl = o.getGlobalPlacement()
            sh.Placement = gpl
        except Exception:
            sh = o.Shape
        verts, tris = [], []
        for f in sh.Faces:
            try:
                pts, fs = f.tessellate(0.25)
            except Exception:
                continue
            base = len(verts)
            verts += [(p.x, p.y, p.z) for p in pts]
            tris += [(a + base, b + base, c + base) for a, b, c in fs]
        if not tris:
            continue
        g = groups.setdefault(fin, {"v": [], "t": []})
        off = len(g["v"])
        g["v"] += verts
        g["t"] += [(a + off, b + off, c + off) for a, b, c in tris]
        seen += 1
    for fin, g in groups.items():
        with open(DEST + fin + ".obj", "w") as fh:
            for v in g["v"]:
                fh.write("v %.3f %.3f %.3f\n" % v)
            for t in g["t"]:
                fh.write("f %d %d %d\n" % (t[0] + 1, t[1] + 1, t[2] + 1))
    log("exported", seen, "objects:", {k: len(v["t"]) for k, v in groups.items()})
    doc.saveAs(OUT + "skid.FCStd")
at(export, 500)
run()
