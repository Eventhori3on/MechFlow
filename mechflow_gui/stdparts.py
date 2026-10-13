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
    "EN10220-PIPE": ("Pipe", "EN", "EN 10220  Steel pipe (ISO 4200 sizes)", "Steel pipe"),
    "ASMEB36.10-PIPE": ("Pipe", "ASME", "ASME B36.10M  Steel pipe", "Steel pipe"),
    "ASMEB16.9-90LR": ("Pipe Fittings", "ASME", "ASME B16.9  90° long radius elbow", "90 deg LR elbow"),
    "ASMEB16.9-45LR": ("Pipe Fittings", "ASME", "ASME B16.9  45° long radius elbow", "45 deg LR elbow"),
    "ASMEB16.9-TEE": ("Pipe Fittings", "ASME", "ASME B16.9  Equal tee", "Equal tee"),
    "ASMEB16.9-RED": ("Pipe Fittings", "ASME", "ASME B16.9  Concentric reducer", "Concentric reducer"),
    "ASMEB16.9-CAP": ("Pipe Fittings", "ASME", "ASME B16.9  Cap", "Cap"),
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


def _reductions():
    out = []
    for i, big in enumerate(T.NPS):
        if T.B169[big][2] is None:
            continue
        for small in reversed(T.NPS[max(0, i - 2):i]):      # one size down first
            out.append(f"NPS {big} x {small}")
    return out


def sizes(t):
    if t.startswith("EN1092"):
        return [f"DN{dn}" for dn in T.EN_PN16]
    if t == "EN10220-PIPE":
        return [f"DN{dn}" for dn in T.EN_PN16]
    if t == "ASMEB16.9-RED":
        return _reductions()
    if t.startswith("ASME"):
        return [f"NPS {n}" for n in T.NPS]
    if t.startswith("ISO15-"):
        return list(T.BEARINGS[t[-2:]].keys())
    return []


def ratings(t):
    if t.startswith("EN1092"):
        return list(T.EN_FLANGES.keys())
    if t.startswith("ASMEB16.5"):
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
    if t.startswith("ISO15-"):
        return f"{size} ISO 15"
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
    if t.startswith("EN1092") or t == "EN10220-PIPE":
        return T.EN_PN16[int(size[2:])]["A"]
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
        elif t in ("EN1092-1-05",):
            f = en_flange(s, rating)
            cands = [f["D"], f["d1"]]
        elif t == "ASMEB16.5-BL":
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


def shape_for(t, size, rating, length=1000.0):
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
        if kind in ("90LR", "45LR"):
            ang = 90 if kind == "90LR" else 45
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
            small = _nps(size, small=True)
            od2, wall2 = asme_pipe(small, rating)
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
        shape = shape_for(t, obj.Size, rating, float(obj.Length))
        pl = App.Placement()
        base = obj.BaseObject
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
        name = designation(t, obj.Size, rating, float(obj.Length))
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
        if "PIPE" in t or t.startswith("ASMEB16.9"):
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
    return designation(o.StdType, o.Size, rating, float(o.Length))


def make(container, t, size, rating, length=1000.0, attach=None):
    from mechflow_gui import toolbox
    doc = App.ActiveDocument if container is None else container.Document
    o = doc.addObject("Part::FeaturePython", "StdPart")
    if container is not None:
        container.addObject(o)
    StdPart(o, t, size, rating, length, attach)
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


def place(container, t, obj, sub, size=None, rating=None, length=1000.0):
    """Insert a standard part on a round edge, sized to it unless a size is
    given. Returns the new object."""
    import Part
    rating = rating or default_rating(t)
    if size is None and obj is not None:
        try:
            e = Part.getShape(obj, sub, needSubElement=True, noElementMap=True)
            size = match_size(t, rating, 2 * e.Curve.Radius)
        except Exception:
            size = None
    size = size or default_size(t)
    attach = (obj, [sub]) if obj is not None else None
    return make(container, t, size, rating, length, attach)
