# SPDX-License-Identifier: LGPL-2.1-or-later
"""MechFlow standard parts for the Toolbox: flanges, pipe, butt-weld
fittings and bearings, built parametrically from the tables in
stdparts_data.

Each part is a 'MechFlow standard part' object with Size and Rating
(PN / Class / Schedule) you can change later in the property view. Placed on
a round edge, it stays attached to it (moves with the part) and is sized to
it when inserted: a flange or pipe to the pipe's outside diameter, a blind
flange to the mating flange, a bearing to the shaft or the housing bore.
"""

import math

import FreeCAD as App

from mechflow_gui import stdparts_data as T

IN = T.IN
V = App.Vector

# type id: (category, standard, menu text, description for the BOM)
TYPES = {
    "EN1092-1-11": ("Flanges", "EN", "EN 1092-1 Type 11  Weld neck flange", "Weld neck flange"),
    "EN1092-1-01": ("Flanges", "EN", "EN 1092-1 Type 01  Plate (slip-on) flange", "Plate flange"),
    "EN1092-1-05": ("Flanges", "EN", "EN 1092-1 Type 05  Blind flange", "Blind flange"),
    "ASMEB16.5-WN": ("Flanges", "ASME", "ASME B16.5  Weld neck flange RF", "Weld neck flange RF"),
    "ASMEB16.5-SO": ("Flanges", "ASME", "ASME B16.5  Slip-on flange RF", "Slip-on flange RF"),
    "ASMEB16.5-BL": ("Flanges", "ASME", "ASME B16.5  Blind flange RF", "Blind flange RF"),
    "EN1514-1-IBC": ("Flanges", "EN", "EN 1514-1  Flat gasket (IBC)", "Flat gasket"),
    "ASMEB16.21": ("Flanges", "ASME", "ASME B16.21  Flat ring gasket", "Flat ring gasket"),
    "EN10220-PIPE": ("Pipe", "EN", "EN 10220  Steel pipe (ISO 4200 sizes)", "Steel pipe"),
    "ASMEB36.10-PIPE": ("Pipe", "ASME", "ASME B36.10M  Steel pipe", "Steel pipe"),
    "ASMEB16.9-90LR": ("Pipe Fittings", "ASME", "ASME B16.9  90° long radius elbow", "90 deg LR elbow"),
    "ASMEB16.9-45LR": ("Pipe Fittings", "ASME", "ASME B16.9  45° long radius elbow", "45 deg LR elbow"),
    "ASMEB16.9-TEE": ("Pipe Fittings", "ASME", "ASME B16.9  Equal tee", "Equal tee"),
    "ASMEB16.9-RED": ("Pipe Fittings", "ASME", "ASME B16.9  Concentric reducer", "Concentric reducer"),
    "ASMEB16.9-CAP": ("Pipe Fittings", "ASME", "ASME B16.9  Cap", "Cap"),
    "EN10253-90-3D": ("Pipe Fittings", "EN", "EN 10253-2  90° elbow 3D (R = 1.5 x DN)", "90 deg elbow 3D"),
    "EN10253-90-2D": ("Pipe Fittings", "EN", "EN 10253-2  90° elbow 2D (R = 1.0 x DN)", "90 deg elbow 2D"),
    "EN10253-90-5D": ("Pipe Fittings", "EN", "EN 10253-2  90° bend 5D (R = 2.5 x DN)", "90 deg bend 5D"),
    "EN10253-45-3D": ("Pipe Fittings", "EN", "EN 10253-2  45° elbow 3D", "45 deg elbow 3D"),
    "EN10253-TEE": ("Pipe Fittings", "EN", "EN 10253-2  Equal tee", "Equal tee"),
    "EN10253-RED": ("Pipe Fittings", "EN", "EN 10253-2  Concentric reducer", "Concentric reducer"),
    "EN10253-CAP": ("Pipe Fittings", "EN", "EN 10253-2  Cap", "Cap"),
    "ISO15-60": ("Bearings", "ISO", "ISO 15  Deep groove ball bearing 60xx", "Deep groove ball bearing"),
    "ISO15-62": ("Bearings", "ISO", "ISO 15  Deep groove ball bearing 62xx", "Deep groove ball bearing"),
    "ISO15-63": ("Bearings", "ISO", "ISO 15  Deep groove ball bearing 63xx", "Deep groove ball bearing"),
}
CATEGORIES = ["Flanges", "Pipe", "Pipe Fittings", "Bearings"]
DEFAULT_SIZE = {"EN": "DN50", "ASME": "2", "ISO": None}


def is_std(t):
    return t in TYPES


def standard_of(t):
    return TYPES[t][1]


def catalog(standard=None):
    """[(category, [(type, text)])] like toolbox.catalog."""
    out = []
    for cat in CATEGORIES:
        items = [(t, v[2]) for t, v in TYPES.items()
                 if v[0] == cat and standard in (None, "All", v[1])]
        if items:
            out.append((cat, items))
    return out


# EN sizes with an EN 10253 / ASME B16.9 fitting (DN -> NPS for the lengths)
DN_NPS = {15: "1/2", 20: "3/4", 25: "1", 32: "1-1/4", 40: "1-1/2", 50: "2", 65: "2-1/2",
          80: "3", 100: "4", 125: "5", 150: "6", 200: "8", 250: "10", 300: "12"}


def _dn(size, small=False):
    """'DN80 x DN50' -> 80 (or 50 with small=True); 'DN80' -> 80."""
    parts = [p.strip() for p in size.split(" x ")]
    return int((parts[1] if small and len(parts) > 1 else parts[0])[2:])


def en_fitting_dims(t, size):
    """EN 10253-2 fitting in mm: (od, wall, radius / centre-to-end, tee C,
    reducer H, cap E, small od, small wall). Lengths are the EN 10253-2
    series values (the ASME B16.9 lengths rounded to the mm); the wall is
    the EN 10220 pipe's, so the fitting matches the pipe it's welded to."""
    big = _dn(size)
    od, wall = en_pipe(f"DN{big}")
    A, C, H, E = (round(x * IN) if x is not None else None for x in T.B169[DN_NPS[big]])
    radius = {"3D": A, "2D": round(A / 1.5), "5D": round(A * 5 / 3)}.get(t.split("-")[-1], A)
    od2 = wall2 = None
    if t == "EN10253-RED":
        od2, wall2 = en_pipe(f"DN{_dn(size, small=True)}")
    return od, wall, radius, C, H, E, od2, wall2


def _reductions():
    out = []
    for i, big in enumerate(T.NPS):
        if T.B169[big][2] is None:
            continue
        for small in reversed(T.NPS[max(0, i - 2):i]):      # one size down first
            out.append(f"NPS {big} x {small}")
    return out


def sizes(t):
    if t.startswith("EN1092") or t.startswith("EN1514"):
        return [f"DN{dn}" for dn in T.EN_PN16]
    if t == "EN10220-PIPE":
        return [f"DN{dn}" for dn in T.EN_PN16]
    if t == "ASMEB16.9-RED":
        return _reductions()
    if t == "EN10253-RED":
        dns = list(DN_NPS)
        out = []
        for i, big in enumerate(dns):
            if T.B169[DN_NPS[big]][2] is None:
                continue
            for small in reversed(dns[max(0, i - 2):i]):
                out.append(f"DN{big} x DN{small}")
        return out
    if t.startswith("EN10253"):
        return [f"DN{dn}" for dn in DN_NPS]
    if t.startswith("ASME"):
        return [f"NPS {n}" for n in T.NPS]
    if t.startswith("ISO15-"):
        return list(T.BEARINGS[t[-2:]].keys())
    return []


def ratings(t):
    if t.startswith("EN1092") or t.startswith("EN1514"):
        return list(T.EN_FLANGES.keys())
    if t.startswith("ASMEB16.5") or t == "ASMEB16.21":
        return list(T.ASME_FLANGES.keys())
    if t.startswith("ASMEB36.10") or t.startswith("ASMEB16.9"):
        return list(T.SCHEDULES)
    return []


def default_rating(t):
    r = ratings(t)
    for want in ("PN16", "Class 150", "Sch 40"):
        if want in r:
            return want
    return r[0] if r else ""


def default_size(t):
    s = sizes(t)
    if t.startswith("ISO15-"):
        return s[4] if len(s) > 4 else s[0]
    want = "DN50" if t.startswith("EN") else ("NPS 2 x 1-1/2" if t == "ASMEB16.9-RED" else "NPS 2")
    if t == "EN10253-RED":
        want = "DN50 x DN40"
    return want if want in s else s[0]


def has_length(t):
    return t.endswith("-PIPE")


def nps_label(s):
    return s if s.startswith("NPS") else f"NPS {s}"


def _nps(size, small=False):
    """'NPS 2 x 1-1/2' -> '2' (or '1-1/2' with small=True)."""
    parts = size.replace("NPS", "").strip().split(" x ")
    return parts[1].strip() if small else parts[0].strip()


def designation(t, size, rating, length=None):
    """Standard designation, used as the name and in the BOM."""
    if t.startswith("EN1092"):
        typ = t.split("-")[-1]
        face = "A" if typ == "01" else "B1"
        return f"EN 1092-1/{typ}/{face}/{size}/{rating}"
    if t.startswith("ASMEB16.5"):
        kind = {"WN": "WN", "SO": "SO", "BL": "BL"}[t.split("-")[-1]]
        return f"ASME B16.5 {kind} RF {nps_label(size)} {rating}"
    if t == "EN10220-PIPE":
        od, wall = en_pipe(size)
        return f"Pipe {size} {od:g}x{wall:g} EN 10220 L={length:g}"
    if t == "ASMEB36.10-PIPE":
        return f"Pipe {nps_label(size)} {rating} ASME B36.10M L={length:g}"
    if t.startswith("ASMEB16.9"):
        kind = {"90LR": "Elbow 90 LR", "45LR": "Elbow 45 LR", "TEE": "Tee",
                "RED": "Reducer", "CAP": "Cap"}[t.split("-")[-1]]
        return f"{kind} {nps_label(size)} {rating} ASME B16.9"
    if t.startswith("EN10253"):
        od, wall = en_pipe(f"DN{_dn(size)}")
        kind = t[len("EN10253-"):]
        name = {"90-3D": "Elbow 90 3D", "90-2D": "Elbow 90 2D", "90-5D": "Bend 90 5D",
                "45-3D": "Elbow 45 3D", "TEE": "Tee", "RED": "Reducer", "CAP": "Cap"}[kind]
        if kind == "RED":
            od2, wall2 = en_pipe(f"DN{_dn(size, small=True)}")
            return f"{name} {size} {od:g}x{wall:g}-{od2:g}x{wall2:g} EN 10253-2"
        return f"{name} {size} {od:g}x{wall:g} EN 10253-2"
    if t.startswith("ISO15-"):
        return f"{size} ISO 15"
    if t == "EN1514-1-IBC":
        return f"Gasket EN 1514-1 IBC {size} {rating} 2 mm"
    if t == "ASMEB16.21":
        return f"Gasket ASME B16.21 {nps_label(size)} {rating} 1/8in"
    return f"{t} {size}"


def description(t):
    return TYPES[t][3]


# ---------------------------------------------------------------- dims

def en_flange(size, rating):
    return T.EN_FLANGES.get(rating, T.EN_PN16)[int(size[2:])]


def en_pipe(size):
    r = T.EN_PN16[int(size[2:])]
    return r["A"], r["S"]


def asme_pipe(size, schedule):
    od, s10, s40, s80 = T.ASME_PIPE[_nps(size)]
    wall = {"Sch 10": s10, "Sch 40": s40, "Sch 80": s80}.get(schedule, s40)
    return od * IN, wall * IN


def outside_diameter(t, size, rating):
    """The pipe OD a part connects to (used to size it from an edge)."""
    if t.startswith("EN1092") or t == "EN10220-PIPE" or t.startswith("EN10253"):
        return T.EN_PN16[_dn(size)]["A"]
    if t.startswith("ASME"):
        return T.ASME_PIPE[_nps(size)][0] * IN
    return None


def match_size(t, rating, diameter, tol=0.6):
    """The size whose connection matches a picked circle's diameter."""
    best, err = None, tol
    for s in sizes(t):
        cands = []
        if t.startswith("ISO15-"):
            d, D, _B, _r = T.BEARINGS[t[-2:]][s]
            cands = [d, D]
        elif t in ("EN1092-1-05", "EN1514-1-IBC"):
            f = en_flange(s, rating)
            cands = [f["D"], f["d1"]]
        elif t in ("ASMEB16.5-BL", "ASMEB16.21"):
            f = T.ASME_FLANGES.get(rating, T.ASME_150)[_nps(s)]
            cands = [f["O"] * IN, f["R"] * IN]
        else:
            od = outside_diameter(t, s, rating)
            cands = [od] if od else []
        for c in cands:
            if abs(c - diameter) < err:
                best, err = s, abs(c - diameter)
    return best


# ---------------------------------------------------------------- shapes

def _ring(r_out, r_in, z0, z1):
    import Part
    h = z1 - z0
    s = Part.makeCylinder(r_out, h, V(0, 0, z0))
    if r_in > 0:
        s = s.cut(Part.makeCylinder(r_in, h + 0.02, V(0, 0, z0 - 0.01)))
    return s


def _revolve(points):
    """Solid of revolution of a closed (r, z) polygon about Z."""
    import Part
    pts = [V(r, 0, z) for r, z in points] + [V(points[0][0], 0, points[0][1])]
    face = Part.Face(Part.makePolygon(pts))
    return face.revolve(V(0, 0, 0), V(0, 0, 1), 360)


def _bolt_holes(shape, n, hole_d, bc, z0, z1):
    import Part
    cutters = []
    for i in range(n):
        a = 2 * math.pi * (i + 0.5) / n      # holes straddle the centre lines
        c = V(bc / 2 * math.cos(a), bc / 2 * math.sin(a), z0 - 1)
        cutters.append(Part.makeCylinder(hole_d / 2, z1 - z0 + 2, c))
    if cutters:
        shape = shape.cut(Part.makeCompound(cutters))
    return shape


def _clean(shape):
    try:
        return shape.removeSplitter()
    except Exception:
        return shape


def is_elbow(t):
    return t.endswith("90LR") or t.endswith("45LR") or t.startswith("EN10253-90") or \
        t.startswith("EN10253-45")


def elbow_angle(t):
    return 45.0 if ("45" in t.split("-")[-1] or t.startswith("EN10253-45")) else 90.0


def shape_for(t, size, rating, length=1000.0, angle=0.0):
    """The part in its own axes: the connection at z = 0, the part running
    up +Z (bearings: one side face at z = 0)."""
    import Part
    if t.startswith("EN1092"):
        f = en_flange(size, rating)
        typ = t.split("-")[-1]
        D, K, L, n = f["D"], f["K"], f["L"], f["n"]
        if typ == "11":             # weld neck: weld end at z=0, face up top
            C, H2, H3 = f["C2"], f["H2"], f["H3"]
            ri = f["A"] / 2 - f["S"]
            body = _revolve([(ri, 0), (f["A"] / 2, 0), (f["A"] / 2, H3),
                             (f["N1"] / 2, H2 - C), (D / 2, H2 - C), (D / 2, H2 - f["f1"]),
                             (f["d1"] / 2, H2 - f["f1"]), (f["d1"] / 2, H2), (ri, H2)])
            return _clean(_bolt_holes(body, n, L, K, H2 - C, H2))
        if typ == "01":             # plate: pipe through, face flush at z=0
            C = f["C1"]
            body = _ring(D / 2, f["B1"] / 2, -C, 0)
            return _clean(_bolt_holes(body, n, L, K, -C, 0))
        # 05 blind: raised face down onto the mating flange at z=0
        C = f["C2"]
        body = _revolve([(0, 0), (f["d1"] / 2, 0), (f["d1"] / 2, f["f1"]),
                         (D / 2, f["f1"]), (D / 2, C), (0, C)])
        return _clean(_bolt_holes(body, n, L, K, f["f1"], C))
    if t.startswith("ASMEB16.5"):
        f = T.ASME_FLANGES.get(rating, T.ASME_150)[_nps(size)]
        g = {k: (v * IN if k != "n" else v) for k, v in f.items()}
        rf = T.RF_HEIGHT_ASME
        kind = t.split("-")[-1]
        O, Tt, R, X, n = g["O"], g["T"], g["R"], g["X"], g["n"]
        if kind == "WN":            # weld end at z=0, Y excludes the RF
            Y, ri = g["L2"], g["B2"] / 2
            body = _revolve([(ri, 0), (g["H"] / 2, 0), (X / 2, Y - Tt), (O / 2, Y - Tt),
                             (O / 2, Y), (R / 2, Y), (R / 2, Y + rf), (ri, Y + rf)])
            return _clean(_bolt_holes(body, n, g["hole"], g["BC"], Y - Tt, Y))
        if kind == "SO":            # raised face flush with the pipe end at z=0
            Y, ri = g["L"], g["B"] / 2
            z_face = -rf
            body = _revolve([(ri, z_face - Y), (X / 2, z_face - Y), (X / 2, z_face - Tt),
                             (O / 2, z_face - Tt), (O / 2, z_face), (R / 2, z_face),
                             (R / 2, 0), (ri, 0)])
            return _clean(_bolt_holes(body, n, g["hole"], g["BC"], z_face - Tt, z_face))
        # blind
        body = _revolve([(0, 0), (R / 2, 0), (R / 2, rf), (O / 2, rf), (O / 2, rf + Tt),
                         (0, rf + Tt)])
        return _clean(_bolt_holes(body, n, g["hole"], g["BC"], rf, rf + Tt))
    if t in ("EN1514-1-IBC", "ASMEB16.21"):
        od, i_d, th = gasket_dims(t, size, rating)
        return _ring(od / 2, i_d / 2, 0, th)
    if t == "EN10220-PIPE":
        od, wall = en_pipe(size)
        return _ring(od / 2, od / 2 - wall, 0, length)
    if t == "ASMEB36.10-PIPE":
        od, wall = asme_pipe(size, rating)
        return _ring(od / 2, od / 2 - wall, 0, length)
    if t.startswith("ASMEB16.9"):
        kind = t.split("-")[-1]
        big = _nps(size)
        od, wall = asme_pipe(big, rating)
        A, C, H, E = (x * IN if x is not None else None for x in T.B169[big])
        od2 = wall2 = None
        if kind == "RED":
            od2, wall2 = asme_pipe(_nps(size, small=True), rating)
        kind = {"90LR": "ELB", "45LR": "ELB"}.get(kind, kind)
        ang = angle or (45 if t.endswith("45LR") else 90)
        return _fitting(kind, od, wall, A, ang, C, H, E, od2, wall2)
    if t.startswith("EN10253"):
        od, wall, R, C, H, E, od2, wall2 = en_fitting_dims(t, size)
        kind = t.split("-")[1]
        ang = {"90": 90, "45": 45}.get(kind)
        if ang and angle:
            ang = angle
        return _fitting("ELB" if ang else kind, od, wall, R, ang or 90, C, H, E, od2, wall2)
    if t.startswith("ISO15-"):
        d, D, B, r = T.BEARINGS[t[-2:]][size]
        pm = (d + D) / 4                     # pitch radius
        dw = 0.3 * (D - d)                   # ball diameter
        ch = min(r, 0.25 * B)
        ri_out = pm - 0.32 * dw
        ro_in = pm + 0.32 * dw
        inner = _revolve([(d / 2 + ch, 0), (ri_out, 0), (ri_out, B), (d / 2 + ch, B),
                          (d / 2, B - ch), (d / 2, ch)])
        outer = _revolve([(ro_in, 0), (D / 2 - ch, 0), (D / 2, ch), (D / 2, B - ch),
                          (D / 2 - ch, B), (ro_in, B)])
        groove = Part.makeTorus(pm, dw / 2 * 1.04, V(0, 0, B / 2))
        inner = inner.cut(groove)
        outer = outer.cut(groove)
        z = max(6, int(2 * math.pi * pm / (dw * 1.35)))
        balls = [Part.makeSphere(dw / 2, V(pm * math.cos(2 * math.pi * i / z),
                                           pm * math.sin(2 * math.pi * i / z), B / 2))
                 for i in range(z)]
        return Part.makeCompound([_clean(inner), _clean(outer)] + balls)
    raise ValueError(f"Unknown standard part {t}")


def _fitting(kind, od, wall, A, ang, C, H, E, od2=None, wall2=None):
    """Butt-weld fitting, inlet at z = 0 running up +Z. Elbows turn towards
    +X (bend radius A); a tee's branch points +X."""
    import Part
    if kind == "ELB":
        # sweep about an axis A away from the centre line, starting up +Z
        def bend(r):
            disc = Part.Face(Part.Wire(Part.makeCircle(r)))
            return disc.revolve(V(A, 0, 0), V(0, 1, 0), ang)
        return _clean(bend(od / 2).cut(bend(od / 2 - wall)))
    if kind == "TEE":
        run = Part.makeCylinder(od / 2, 2 * C, V(0, 0, 0))
        br = Part.makeCylinder(od / 2, C, V(0, 0, C), V(1, 0, 0))
        solid = run.fuse(br)
        hole = Part.makeCylinder(od / 2 - wall, 2 * C + 2, V(0, 0, -1)).fuse(
            Part.makeCylinder(od / 2 - wall, C + 1, V(0, 0, C), V(1, 0, 0)))
        return _clean(solid.cut(hole))
    if kind == "RED":
        straight = min(0.12 * H, 0.5 * IN)
        outer = _revolve([(0, 0), (od / 2, 0), (od / 2, straight),
                          (od2 / 2, H - straight), (od2 / 2, H), (0, H)])
        inner = _revolve([(0, -1), (od / 2 - wall, -1), (od / 2 - wall, straight),
                          (od2 / 2 - wall2, H - straight), (od2 / 2 - wall2, H + 1), (0, H + 1)])
        return _clean(outer.cut(inner))
    if kind == "CAP":
        head = od / 4
        straight = max(E - head, 0.1)

        def capsolid(r, extra):
            cyl = Part.makeCylinder(r, straight + extra, V(0, 0, -extra))
            sph = Part.makeSphere(r, V(0, 0, 0))
            m = App.Matrix()
            m.scale(1, 1, (head - (od / 2 - r)) / r)
            ell = sph.transformGeometry(m)
            ell.translate(V(0, 0, straight))
            top = ell.common(Part.makeCylinder(r + 1, r + 1, V(0, 0, straight)))
            return cyl.fuse(top)
        return _clean(capsolid(od / 2, 0).cut(capsolid(od / 2 - wall, 1)))
    raise ValueError(f"Unknown fitting {kind}")


def outlet_direction(t, rating=None):
    """Local direction an elbow's outlet / a tee's branch points (Spin 0),
    or None for parts without one."""
    if t.endswith("90LR") or t.startswith("EN10253-90"):
        return V(1, 0, 0)
    if t.endswith("45LR") or t.startswith("EN10253-45"):
        return V(math.sin(math.radians(45)), 0, math.cos(math.radians(45)))
    if t.endswith("-TEE"):
        return V(1, 0, 0)
    return None


def aim(obj, target):
    """Spin an elbow / tee so its outlet points as near as it can to the
    global direction target (SOLIDWORKS: pick the direction as you place)."""
    if outlet_direction(obj.StdType) is None:
        return False
    target = V(target)
    if target.Length < 1e-9:
        return False
    target.normalize()
    obj.Spin = 0
    obj.recompute()
    rot = obj.Placement.Rotation
    local = rot.inverted().multVec(target)
    if math.hypot(local.x, local.y) < 1e-6:
        return False               # straight along the inlet axis: any spin will do
    obj.Spin = math.degrees(math.atan2(local.y, local.x))
    obj.recompute()
    return True


# ---------------------------------------------------------------- the object

def _edge_frame(obj, sub, bearing=False):
    """(centre, axis out of the material) of a picked circular edge."""
    import Part
    from mechflow_gui import toolbox
    e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
    c, ax = e.Curve.Center, V(e.Curve.Axis).normalize()
    out = toolbox._outward(obj, sub)
    if out is False:
        ax = ax * -1
    if bearing:
        ax = ax * -1                 # a bearing goes onto the shaft / into the bore
    return c, ax


class StdPart:
    """Proxy for a MechFlow standard part."""

    def __init__(self, obj, t, size, rating, length=1000.0, attach=None):
        obj.addProperty("App::PropertyString", "StdType", "Standard part",
                        "Type of standard part", 1)
        obj.addProperty("App::PropertyEnumeration", "Size", "Standard part", "Size")
        obj.addProperty("App::PropertyEnumeration", "Rating", "Standard part",
                        "Pressure rating (PN / Class) or pipe schedule")
        obj.addProperty("App::PropertyLength", "Length", "Standard part", "Pipe length")
        obj.addProperty("App::PropertyLinkSub", "BaseObject", "Placement",
                        "Round edge the part is placed on")
        obj.addProperty("App::PropertyBool", "Invert", "Placement", "Turn the part round")
        obj.addProperty("App::PropertyDistance", "Offset", "Placement",
                        "Move the part along its axis")
        obj.addProperty("App::PropertyAngle", "Spin", "Placement",
                        "Rotate the part about its axis (e.g. to line up bolt holes "
                        "or an elbow's direction)")
        obj.addProperty("App::PropertyInteger", "MechFlowInstance", "Base",
                        "Toolbox instance number (the <n> in the name)", 4)
        obj.StdType = t
        obj.Size = sizes(t)
        obj.Size = size
        r = ratings(t)
        obj.Rating = r if r else ["-"]
        if rating in r:
            obj.Rating = rating
        obj.Length = length
        if not has_length(t):
            obj.setEditorMode("Length", 2)
        if attach:
            obj.BaseObject = attach
        obj.Proxy = self

    def execute(self, obj):
        t = obj.StdType
        rating = obj.Rating if obj.Rating != "-" else ""
        shape = shape_for(t, obj.Size, rating, float(obj.Length),
                          float(getattr(obj, "BendAngle", 0) or 0))
        pl = App.Placement()
        base = obj.BaseObject
        noz = getattr(obj, "NozzleRef", None)
        if noz is not None:
            # on a MechFlow nozzle: follow its pipe end, whatever the edge
            # numbers become when the nozzle is edited
            try:
                if noz.Size != obj.Size and noz.Size in sizes(t):
                    obj.Size = noz.Size            # the nozzle changed size: so does the flange
                body = noz.getParentGeoFeatureGroup()
                gp = body.getGlobalPlacement() if body is not None else App.Placement()
                c = gp.multVec(V(noz.PipeEnd))
                ax = gp.Rotation.multVec(V(noz.Direction)).normalize()
                parent = obj.getParentGeoFeatureGroup()
                if parent is not None:
                    inv = parent.getGlobalPlacement().inverse()
                    c, ax = inv.multVec(c), inv.Rotation.multVec(ax)
                if obj.Invert:
                    ax = ax * -1
                rot = App.Rotation(V(0, 0, 1), ax)
                spin = App.Rotation(V(0, 0, 1), float(obj.Spin))
                pl = App.Placement(c + ax * float(obj.Offset), rot.multiply(spin))
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: {obj.Label}: can't follow its nozzle ({e})\n")
                pl = obj.Placement
            obj.Shape = shape_for(t, obj.Size, rating, float(obj.Length),
                                  float(getattr(obj, "BendAngle", 0) or 0))
            obj.Placement = pl
            n = getattr(obj, "MechFlowInstance", 0)
            name = object_designation(obj)
            want = f"{name}<{n}>" if n else name
            if obj.Label != want:
                obj.Label = want
            return
        if base and base[1]:
            try:
                c, ax = _edge_frame(base[0], base[1][0], t.startswith("ISO15-"))
                if obj.Invert:
                    ax = ax * -1
                rot = App.Rotation(V(0, 0, 1), ax)
                spin = App.Rotation(V(0, 0, 1), float(obj.Spin))
                pl = App.Placement(c + ax * float(obj.Offset), rot.multiply(spin))
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: {obj.Label}: can't find its edge ({e})\n")
                pl = obj.Placement
        else:
            pl = obj.Placement
        obj.Shape = shape
        obj.Placement = pl
        n = getattr(obj, "MechFlowInstance", 0)
        name = object_designation(obj)
        want = f"{name}<{n}>" if n else name
        if obj.Label != want:
            obj.Label = want

    def onChanged(self, obj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderStdPart:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from mechflow_gui import icon_path
        t = getattr(getattr(self, "Object", None), "StdType", "")
        if t.startswith("ISO15-"):
            return icon_path("Bearing.svg")
        if "PIPE" in t or t.startswith("ASMEB16.9") or t.startswith("EN10253"):
            return icon_path("Pipe.svg")
        return icon_path("Flange.svg")

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_std_object(o):
    return type(getattr(o, "Proxy", None)).__name__ == "StdPart"


def object_designation(o):
    rating = o.Rating if o.Rating != "-" else ""
    name = designation(o.StdType, o.Size, rating, float(o.Length))
    a = float(getattr(o, "BendAngle", 0) or 0)
    if a and is_elbow(o.StdType) and abs(a - elbow_angle(o.StdType)) > 1e-6:
        name += f" cut to {a:g}\u00b0"
    return name


def set_bend_angle(o, angle):
    """Cut an elbow to angle (degrees); 0 = its standard angle."""
    if not hasattr(o, "BendAngle"):
        o.addProperty("App::PropertyAngle", "BendAngle", "Standard part",
                      "Elbow cut to this angle (0: the standard 90 / 45)")
    o.BendAngle = angle


def make(container, t, size, rating, length=1000.0, attach=None):
    from mechflow_gui import toolbox
    doc = App.ActiveDocument if container is None else container.Document
    o = doc.addObject("Part::FeaturePython", "StdPart")
    if container is not None:
        container.addObject(o)
    try:
        StdPart(o, t, size, rating, length, attach)
    except Exception:
        doc.removeObject(o.Name)          # don't leave a half-made part behind
        raise
    if App.GuiUp:
        ViewProviderStdPart(o.ViewObject)
        try:
            o.ViewObject.ShapeColor = (0.75, 0.76, 0.78) if not t.startswith("ISO15-") \
                else (0.80, 0.82, 0.85)
        except Exception:
            pass
    name = designation(t, size, rating, length)
    o.MechFlowInstance = int(toolbox.instance_label(doc, name).rsplit("<", 1)[1][:-1])
    doc.recompute()
    return o


# ---------------------------------------------------------------- joints

def is_flange(t):
    return t.startswith("EN1092") or t.startswith("ASMEB16.5")


def is_gasket(t):
    return t in ("EN1514-1-IBC", "ASMEB16.21")


def family(t):
    return "EN" if t.startswith("EN") else "ASME"


def gasket_dims(t, size, rating):
    """(OD, ID, thickness) of a flat inside-bolt-circle gasket: OD to the
    bolts, ID to the pipe (EN 1514-1 IBC / ASME B16.21 sizes)."""
    if t.startswith("EN"):
        f = en_flange(size, rating)
        return f["K"] - f["L"], round(f["A"] + 0.7, 1), 2.0
    f = T.ASME_FLANGES.get(rating, T.ASME_150)[_nps(size)]
    return (f["BC"] - f["hole"] + 0.125) * IN, f["H"] * IN, 0.125 * IN


def flange_info(t, size, rating):
    """Bolting data of a flange: thickness at the bolts (back to joint
    face), bolt circle, hole, number, bolt size, face diameter, OD."""
    if t.startswith("EN"):
        f = en_flange(size, rating)
        typ = t.split("-")[-1]
        th = f["C1"] if typ == "01" else f["C2"]
        return dict(thick=th, K=f["K"], L=f["L"], n=f["n"], bolt=f["bolt"],
                    face=f["d1"] if typ != "01" else f["D"], OD=f["D"])
    f = T.ASME_FLANGES.get(rating, T.ASME_150)[_nps(size)]
    bolt_in = f["hole"] - 0.125
    return dict(thick=(f["T"] + 0.06) * IN, K=f["BC"] * IN, L=f["hole"] * IN, n=f["n"],
                bolt=_inch_name(bolt_in), face=f["R"] * IN, OD=f["O"] * IN)


def _inch_name(x):
    whole = int(x + 1e-6)
    frac = x - whole
    for den in (2, 4, 8, 16):
        num = round(frac * den)
        if abs(num / den - frac) < 1e-3:
            if num == 0:
                return f"{whole}in"
            from math import gcd
            g = gcd(num, den)
            fr = f"{num // g}/{den // g}"
            return f"{whole} {fr}in" if whole else f"{fr}in"
    return f"{x:g}in"


def _inch_value(s):
    s = s.replace("in", "").strip()
    total = 0.0
    for part in s.split():
        if "/" in part:
            a, b = part.split("/")
            total += float(a) / float(b)
        else:
            total += float(part)
    return total


class _Ref:
    """A MechFlow flange reached through a link / Part (e.g. a nozzle flange
    inside an inserted tank): looks like the flange, in assembly axes."""

    def __init__(self, top, prefix, leaf):
        import Part
        self.obj, self.prefix, self.leaf = top, prefix, leaf
        self.StdType, self.Size, self.Rating = leaf.StdType, leaf.Size, leaf.Rating
        self.Placement = top.getSubObject(prefix, retType=3)
        self.Shape = Part.getShape(top, prefix)
        self.Document = leaf.Document
        self.Label = leaf.Label


def _att(base, sub):
    """(object, sub) to attach to for an edge of base (a flange or _Ref)."""
    if isinstance(base, _Ref):
        return base.obj, base.prefix + sub
    return base, sub


def _resolve(obj, sub):
    """The MechFlow standard part a (possibly link-path) sub points into."""
    if obj is None or not sub:
        return None
    if is_std_object(obj):
        return obj
    if "." not in sub:
        return None
    prefix = sub.rsplit(".", 1)[0] + "."
    try:
        leaf = obj.getSubObjectList(sub)[-1]
    except Exception:
        return None
    if leaf is obj or not is_std_object(leaf):
        return None
    return _Ref(obj, prefix, leaf)


def joint_with(obj, sub, t):
    """If the picked edge is the face (raised face or OD) of a MechFlow
    flange, return that flange - the new part bolts to it. Works through
    links too (a flange in an inserted part): then a _Ref is returned."""
    import Part
    if not (is_flange(t) or is_gasket(t)) or obj is None:
        return None
    base = _resolve(obj, sub)
    if base is None:
        return None
    if not is_flange(base.StdType) or family(base.StdType) != family(t):
        return None
    try:
        e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
        d = 2 * e.Curve.Radius
    except Exception:
        return None
    info = flange_info(base.StdType, base.Size, base.Rating)
    if min(abs(d - info["face"]), abs(d - info["OD"])) > 0.6:
        return None
    return base


def _face_frame(base):
    """(point on the joint face, direction out of the face) of a placed
    flange, from its own axes."""
    pl = base.Placement
    t = base.StdType
    rating = base.Rating
    if t.startswith("EN1092"):
        f = en_flange(base.Size, rating)
        typ = t.split("-")[-1]
        z = {"11": f["H2"], "01": 0.0, "05": 0.0}[typ]
        up = -1.0 if typ == "05" else 1.0
    else:
        g = T.ASME_FLANGES.get(rating, T.ASME_150)[_nps(base.Size)]
        kind = t.split("-")[-1]
        z = {"WN": (g["L2"] + 0.06) * IN, "SO": 0.0, "BL": 0.0}[kind]
        up = -1.0 if kind == "BL" else 1.0
    n = pl.Rotation.multVec(V(0, 0, up))
    return pl.multVec(V(0, 0, z)), n


def _length_in_part(t, size, rating):
    """How far the part runs from its own z=0 to its joint face."""
    if t.startswith("EN1092"):
        f = en_flange(size, rating)
        return f["H2"] if t.endswith("-11") else 0.0
    if t.startswith("ASMEB16.5"):
        g = T.ASME_FLANGES.get(rating, T.ASME_150)[_nps(size)]
        return (g["L2"] + 0.06) * IN if t.endswith("-WN") else 0.0
    return 0.0


def _hole_edges(obj, centre, normal, radius, back):
    """Bolt-hole circle edges of a flange, on its back face (the face
    farthest from the joint when back=True)."""
    import Part
    sh = obj.Shape
    holes = {}
    for i, e in enumerate(sh.Edges):
        c = getattr(e, "Curve", None)
        if type(c).__name__ != "Circle" or abs(c.Radius - radius) > 1e-3:
            continue
        d = c.Center - centre
        ax = d.dot(normal)
        radial = d - normal * ax
        key = (round(radial.x, 1), round(radial.y, 1), round(radial.z, 1))
        cur = holes.get(key)
        if cur is None or (ax < cur[1] if back else ax > cur[1]):
            holes[key] = (f"Edge{i + 1}", ax)
    return [v[0] for v in holes.values()]


def bolt_set(container, base, mate, gap):
    """Bolts through two flanges (heads on the base's back), nuts on the
    mate's back. Needs the Fasteners Workbench. Returns the objects."""
    from mechflow_gui import toolbox
    if toolbox.fasteners() is None:
        return []
    info = flange_info(base.StdType, base.Size, base.Rating)
    minfo = flange_info(mate.StdType, mate.Size, mate.Rating)
    face, n = _face_frame(base)
    metric = family(base.StdType) == "EN"
    bolt = info["bolt"]
    if metric:
        d = float(bolt[1:])
        nut_h = 0.8 * d
        pitch = toolbox.METRIC.get(bolt, (d, 0.15 * d))[1]
        btype, ntype = "ISO4014", "ISO4032"
        names = toolbox.diameters(btype)
        bname = bolt if bolt in names else f"({bolt})"
        nname = bname
    else:
        d = _inch_value(bolt) * IN
        nut_h = 0.875 * d
        pitch = d / 8
        btype, ntype = "ASMEB18.2.1.6", "ASMEB18.2.2.4A"
        bname = nname = bolt
    grip = info["thick"] + gap + minfo["thick"]
    need = grip + nut_h + 2 * pitch
    length = _pick(btype, bname, need, metric)
    if length is None and metric:
        btype = "ISO4017"
        length = _pick(btype, bname, need, metric)
    made = []
    for sub in _hole_edges(base, face, n, info["L"] / 2, back=True):
        o, s_ = _att(base, sub)
        made.append(toolbox.make(container, btype, (o, [s_]), bname, length,
                                 invert=toolbox._outward(o, s_) is False))
    mface = face + n * gap
    for sub in _hole_edges(mate, mface, n, minfo["L"] / 2, back=False):
        made.append(toolbox.make(container, ntype, (mate, [sub]), nname,
                                 invert=toolbox._outward(mate, sub) is False))
    return made


def _pick(btype, bname, need, metric):
    from mechflow_gui import toolbox
    opts = toolbox.lengths(btype, bname)
    nums = []
    for o in opts:
        try:
            v = float(o) if metric else _inch_value(o) * IN
        except ValueError:
            continue
        nums.append((v, o))
    nums.sort()
    for v, o in nums:
        if v >= need - 1e-6:
            return o
    return None


def place(container, t, obj, sub, size=None, rating=None, length=1000.0, joint=True):
    """Insert a standard part on a round edge, sized to it unless a size is
    given. On another flange's face it makes a joint: the new flange faces
    it across a gasket, with bolts and nuts (joint=True). Returns the new
    objects."""
    import Part
    base = joint_with(obj, sub, t)
    if base is not None:
        size, rating = base.Size, base.Rating
        return _place_joint(container, t, base, sub, size, rating, joint)
    rating = rating or default_rating(t)
    if size is None and obj is not None:
        try:
            e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
            size = match_size(t, rating, 2 * e.Curve.Radius)
        except Exception:
            size = None
    size = size or default_size(t)
    attach = (obj, [sub]) if obj is not None else None
    return [make(container, t, size, rating, length, attach)]


def _place_joint(container, t, base, sub, size, rating, with_bolts):
    gt = "EN1514-1-IBC" if family(t) == "EN" else "ASMEB16.21"
    gap = gasket_dims(gt, size, rating)[2]
    made = []
    attach = (base.obj if isinstance(base, _Ref) else base, [sub])
    if is_gasket(t):
        g = make(container, t, size, rating, attach=attach)
        _seat_on_face(g, base, 0.0, flip=False)
        return [g]
    if with_bolts:
        g = make(container, gt, size, rating, attach=attach)
        _seat_on_face(g, base, 0.0, flip=False)
        made.append(g)
    else:
        gap = 0.0
    mate = make(container, t, size, rating, attach=attach)
    blind = t.endswith("-05") or t.endswith("-BL")
    # blind flanges already face down onto the joint; others turn round
    _seat_on_face(mate, base, gap + (0 if blind else _length_in_part(t, size, rating)),
                  flip=not blind)
    made.append(mate)
    if with_bolts:
        mate.Document.recompute()
        made += bolt_set(container, base, mate, gap)
    return made


def _seat_on_face(obj, base, dist, flip):
    """Put a part on a flange's joint face (whichever edge was picked):
    Offset along the face normal, turned round if flip."""
    face, n = _face_frame(base)
    c, ax = _edge_frame(obj.BaseObject[0], obj.BaseObject[1][0])
    # the picked edge may sit below the face (an OD edge): measure from it
    shift = (face - c).dot(ax)
    if ax.dot(n) < 0:
        obj.Invert = not obj.Invert
        shift = -shift
        ax = ax * -1
    if flip:
        obj.Invert = not obj.Invert
        obj.Offset = -(shift + dist)
    else:
        obj.Offset = shift + dist
    obj.Document.recompute()
