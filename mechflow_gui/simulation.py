# SPDX-License-Identifier: LGPL-2.1-or-later
"""Stress Check (SOLIDWORKS SimulationXpress, for FreeCAD).

Fix some faces, load others - a force, a pressure, the water in a tank,
the part's own weight - and run. MechFlow copies the part into its own
"... Stress Check" document (your part is never changed), meshes it with
gmsh, solves with CalculiX and shows the von Mises stress, the peak stress
and deflection and the factor of safety against the material's yield.

- Weldments are checked as one welded piece (the body, members, plates and
  gussets are fused).
- Water pressure rises with depth: the wetted faces are cut into horizontal
  bands and each band gets the pressure at its depth.
- The mesh is sized from the part's wall thickness and kept to a node
  budget so it solves in a minute or two.

It's a linear static check: like SimulationXpress, peak stresses at sharp
corners and right at fixed edges read high, and a thin panel deflecting more
than half its thickness is stiffer in reality (membrane action).
"""

import json
import math
import os
import subprocess
import threading
import time

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector
G = 9.81
# E (MPa), Poisson's ratio, yield (MPa) for MechFlow's materials
MECH = {
    "Structural steel S275": (210000, 0.30, 275), "Structural steel S355": (210000, 0.30, 355),
    "Plain carbon steel": (200000, 0.29, 220), "AISI 1020 steel": (200000, 0.29, 350),
    "Stainless steel 304": (193000, 0.29, 215), "Stainless steel 316": (193000, 0.30, 205),
    "Cast iron (grey)": (110000, 0.26, 150), "Aluminium 6061-T6": (69000, 0.33, 275),
    "Aluminium 6082-T6": (70000, 0.33, 260), "Brass": (100000, 0.34, 200),
    "Copper": (117000, 0.34, 70), "Titanium Ti-6Al-4V": (114000, 0.34, 880),
    "ABS": (2200, 0.35, 40), "PLA": (3500, 0.36, 50), "Nylon 6/6": (2800, 0.40, 70),
    "Acetal (POM)": (2800, 0.35, 65), "Polycarbonate": (2300, 0.37, 60),
}
QUALITY = {"Coarse": 60000, "Normal": 150000, "Fine": 350000}
LOAD_TYPES = ["Force", "Pressure", "Water pressure"]


# ------------------------------------------------------------ geometry

def _structure(objs):
    """The welded structure: bodies and weldment parts, through Parts and
    links - not bolted-on Toolbox parts (flanges, fasteners), which don't
    act as one piece with it."""
    import Part
    from mechflow_gui import stdparts
    out = []

    def walk(top, path, o):
        lo = o.getLinkedObject(True) if hasattr(o, "getLinkedObject") else o
        if lo.TypeId == "App::Part" or lo.isDerivedFrom("App::Part"):
            for c in lo.Group:
                if c.TypeId.startswith("App::Origin") or c.TypeId == "Sketcher::SketchObject":
                    continue
                try:
                    if c.getParentGeoFeatureGroup() not in (lo, None):
                        continue
                except Exception:
                    pass
                walk(top, path + c.Name + ".", c)
            return
        if stdparts.is_std_object(lo) or type(getattr(lo, "Proxy", None)).__name__ == "FSScrewObject":
            return
        try:
            sh = Part.getShape(top, path) if path else Part.getShape(o)
        except Exception:
            return
        if not sh.isNull() and sh.Solids:
            out.append(sh)
    for o in objs:
        walk(o, "", o)
    return out


def target_shape(objs):
    """One solid (or compound of solids) for the objects, welded together:
    a weldment's body, members, plates and gussets are fused."""
    solids = []
    for sh in _structure(objs):
        solids += [s.copy() for s in sh.Solids]
    if not solids:
        raise ValueError("nothing solid to check")
    if len(solids) == 1:
        return solids[0]
    fused = solids[0].fuse(solids[1:])
    try:
        fused = fused.removeSplitter()
    except Exception:
        pass
    return fused


def simplify(shape, radius=15.0):
    """Leave out small round holes and bosses (bolt holes, small pipe stubs):
    they cost far more mesh than they change the result on a big plate or
    tank. Returns (shape, number of features left out)."""
    small = [f for f in shape.Faces
             if type(f.Surface).__name__ == "Cylinder" and f.Surface.Radius < radius]
    if not small:
        return shape, 0
    try:
        out = shape.defeaturing(small)
        if out.isValid() and out.Solids and abs(out.Volume - shape.Volume) < 0.05 * shape.Volume:
            return out, len(small)
    except Exception:
        pass
    return shape, 0


def wall_thickness(shape, samples=24, thinnest=False):
    main, thin = wall_thicknesses(shape, samples)
    return thin if thinnest else main


def wall_thicknesses(shape, samples=24):
    """Wall thickness, found by looking straight in from the middle of the
    biggest faces: the main plate's or tank wall's thickness (the biggest
    faces' own) and the thinnest wall seen."""
    faces = sorted(shape.Faces, key=lambda f: -f.Area)[:samples]
    reach = shape.BoundBox.DiagonalLength + 10
    found = []
    import Part
    for f in faces:
        try:
            u0, u1, v0, v1 = f.ParameterRange
            u, v = (u0 + u1) / 2, (v0 + v1) / 2
            p = f.valueAt(u, v)
            n = V(f.normalAt(u, v))
            if not f.isInside(p, 1e-6, True):
                p = f.CenterOfMass
            if shape.isInside(p + n * 0.05, 1e-6, True):
                n = n * -1                         # make n point out of the material
            start = p + n * 1e-3
            edge = Part.LineSegment(start, start - n * reach).toShape()
            spans = [e.Length for e in edge.common(shape).Edges]
            spans = [x for x in spans if x > 0.2]
            if spans:
                found.append((f.Area, min(spans)))
        except Exception:
            continue
    if not found:
        bb = shape.BoundBox
        t = min(bb.XLength, bb.YLength, bb.ZLength)
        return t, t
    thin = min(t for _a, t in found)
    # area-weighted median: what most of the part is made of
    found.sort(key=lambda at: at[1])
    half, acc = sum(a for a, _t in found) / 2, 0.0
    for a, t in found:
        acc += a
        if acc >= half:
            return t, thin
    return found[-1][1], thin


def mesh_size(shape, quality="Normal"):
    """Element size for a node budget (2nd order tets): nodes ~ 7.7 A/s^2
    for thin walls, ~ 8 V/s^3 for chunky parts."""
    budget = QUALITY.get(quality, QUALITY["Normal"])
    A, Vol = shape.Area, shape.Volume
    lo, hi = 0.2, shape.BoundBox.DiagonalLength
    for _ in range(60):
        s = (lo + hi) / 2
        n = 7.7 * A / s ** 2 + 8.0 * Vol / s ** 3
        if n > budget:
            lo = s
        else:
            hi = s
    t, t_min = wall_thicknesses(shape)
    s = hi
    # never coarser than a tenth of the part, never finer than a third of the wall
    s = min(s, shape.BoundBox.DiagonalLength / 10)
    s = max(s, t / 3)
    return round(s, 2), t, t_min


def band_planes(z0, z1, bands):
    import Part
    out = []
    for k in range(1, bands):
        z = z0 + (z1 - z0) * k / bands
        out.append(z)
    return out


def slice_for_water(shape, wet_faces, level, bands=12):
    """Cut the shape into horizontal bands over the wetted height, so each
    band's faces can carry the water pressure at their depth."""
    import Part
    from BOPTools import SplitAPI
    zmin = min(f.BoundBox.ZMin for f in wet_faces)
    zmax = min(level, max(f.BoundBox.ZMax for f in wet_faces))
    if zmax - zmin < 1e-3:
        return shape
    bb = shape.BoundBox
    big = bb.DiagonalLength * 2 + 100
    planes = [Part.makePlane(2 * big, 2 * big, V(bb.Center.x - big, bb.Center.y - big, z))
              for z in band_planes(zmin, zmax, bands)]
    if not planes:
        return shape
    return SplitAPI.slice(shape, planes, "CompSolid")


def _edge_concave(shape, f1, f2, e, eps=0.05):
    """True if two faces meet at an inside corner (the liquid's side)."""
    try:
        m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        n1 = V(f1.normalAt(*f1.Surface.parameter(m)))
        n2 = V(f2.normalAt(*f2.Surface.parameter(m)))
        if shape.isInside(m + n1 * 0.05, 1e-6, True):
            n1 = n1 * -1
        if shape.isInside(m + n2 * 0.05, 1e-6, True):
            n2 = n2 * -1
        if abs(n1.dot(n2)) > 0.9999:
            return True                       # smooth (tangent) - keep going
        return shape.isInside(m + (n1 - n2) * eps, 1e-6, True)
    except Exception:
        return False


def wetted_faces(shape, seeds):
    """All the faces a liquid touches, from the face(s) clicked: spread
    across inside corners, stop at the rims of holes and openings."""
    faces = shape.Faces
    edge_faces = {}
    for i, f in enumerate(faces):
        for e in f.Edges:
            edge_faces.setdefault(e.hashCode(), []).append(i)
    edges = {}
    for i, f in enumerate(faces):
        for e in f.Edges:
            edges[e.hashCode()] = e
    start = [i for i, f in enumerate(faces)
             if any(f.isSame(s_) or (f.CenterOfMass - s_.CenterOfMass).Length < 1e-3 for s_ in seeds)]
    seen = set(start)
    todo = list(start)
    while todo:
        i = todo.pop()
        for e in faces[i].Edges:
            for j in edge_faces.get(e.hashCode(), []):
                if j in seen:
                    continue
                if _edge_concave(shape, faces[i], faces[j], edges[e.hashCode()]):
                    seen.add(j)
                    todo.append(j)
    return [faces[i] for i in sorted(seen)]


def _curved(f):
    try:
        return type(f.Surface).__name__ != "Plane" and not f.Surface.isPlanar()
    except Exception:
        return type(f.Surface).__name__ != "Plane"


def _point_on(f):
    """A point on the face itself. A curved face's centre of mass is off
    the surface (a bore's is on its axis), so it can't be used to match it."""
    c = f.CenterOfMass
    try:
        if f.isInside(c, 1e-4, True):
            return c
        u0, u1, v0, v1 = f.ParameterRange
        for a, b in ((0.5, 0.5), (0.25, 0.5), (0.75, 0.5), (0.5, 0.25), (0.5, 0.75)):
            p = f.valueAt(u0 + a * (u1 - u0), v0 + b * (v1 - v0))
            if f.isInside(p, 1e-4, True):
                return p
        pts, _t = f.tessellate(0.5)
        if pts:
            return pts[0]
    except Exception:
        pass
    return c


def match_faces(shape, picked, tol=0.05):
    """Names of shape's faces that lie on one of the picked faces (the
    picked faces may have been cut into bands)."""
    import Part
    out = []
    for i, f in enumerate(shape.Faces):
        try:
            c = _point_on(f)
            u, v = f.Surface.parameter(c)
            n = V(f.normalAt(u, v))
        except Exception:
            continue
        for pf in picked:
            if not pf.BoundBox.isInside(c) and pf.BoundBox.DiagonalLength > 0:
                bb = App.BoundBox(pf.BoundBox)
                bb.enlarge(tol * 10)
                if not bb.isInside(c):
                    continue
            try:
                d = pf.distToShape(Part.Vertex(c))[0]
            except Exception:
                continue
            if d >= tol and type(pf.Surface).__name__ == "Plane":
                # the picked face may have holes that were filled in: on the
                # same plane and inside its outline is good enough
                pl = pf.Surface
                if abs((c - pl.Position).dot(pl.Axis)) < tol:
                    try:
                        outer = Part.Face(pf.OuterWire)
                        d = outer.distToShape(Part.Vertex(c))[0]
                    except Exception:
                        pass
            if d < tol:
                try:
                    uu, vv = pf.Surface.parameter(c)
                    if abs(abs(V(pf.normalAt(uu, vv)).dot(n)) - 1) > 1e-3:
                        continue
                except Exception:
                    pass
                out.append(f"Face{i + 1}")
                break
    return out


# ------------------------------------------------------------ the study

class StressStudy:
    """Stored in the part: what to fix and load, so the check can be re-run
    after design changes. No shape of its own."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLinkList", "Parts", "Study", "What is checked")
        obj.addProperty("App::PropertyLinkSubListGlobal", "Fixed", "Study", "Fixed faces")
        obj.addProperty("App::PropertyString", "Loads", "Study", "Loads (JSON)", 4)
        obj.addProperty("App::PropertyBool", "SelfWeight", "Study", "Include the part's weight")
        obj.addProperty("App::PropertyEnumeration", "Mesh", "Study", "Mesh quality")
        obj.Mesh = list(QUALITY)
        obj.Mesh = "Normal"
        obj.addProperty("App::PropertyString", "Result", "Study", "Last result (JSON)", 4)
        obj.addProperty("App::PropertyBool", "Simplify", "Study", "Leave out small holes")
        obj.Simplify = True
        obj.Proxy = self

    def execute(self, obj):
        return

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderStressStudy:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path("StressCheck.svg")

    def attach(self, vobj):
        self.Object = vobj.Object

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.Control.showDialog(StressPanel(vobj.Object))
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_study(o):
    return type(getattr(o, "Proxy", None)).__name__ == "StressStudy"


def material_of(objs):
    from mechflow_gui import material
    for o in objs:
        name, dens = material.get(o)
        if name is None:
            # a Part container: its body
            for c in getattr(o, "Group", []):
                name, dens = material.get(c)
                if name:
                    break
        if name:
            e = MECH.get(name)
            if e:
                return name, dens, e
            return name, dens, None
    return None, None, None


def _faces_of(links):
    import Part
    out = []
    for obj, subs in links:
        for s in subs:
            try:
                out.append(Part.getShape(obj, s, needSubElement=True, noElementMap=True))
            except Exception:
                pass
    return out


def prepare(study_like):
    """Build the analysis document for a study. Returns (doc, analysis,
    solver, info)."""
    import Part
    import ObjectsFem
    objs = study_like["parts"]
    shape = target_shape(objs)
    left_out = 0
    if study_like.get("simplify", True):
        shape, left_out = simplify(shape)
    loads = study_like["loads"]
    water = [l for l in loads if l["type"] == "Water pressure"]
    for l in water:
        # from the clicked face(s) to every face the liquid touches
        picked = _faces_of(l["faces"])
        seeds = [shape.getElement(n) for n in match_faces(shape, picked)]
        faces = wetted_faces(shape, seeds) if seeds else picked
        l["_wet"] = faces
        if l.get("level") is None:
            l["level"] = max(f.BoundBox.ZMax for f in faces)
    name = objs[0].Document.Label + " - Stress Check"
    for d in list(App.listDocuments().values()):
        if d.Label == name:
            App.closeDocument(d.Name)
    doc = App.newDocument("StressCheck")
    doc.Label = name
    copy = doc.addObject("Part::Feature", "Model")
    copy.Shape = shape
    copy.Label = objs[0].Document.Label
    an = ObjectsFem.makeAnalysis(doc, "StressCheck")
    sol = ObjectsFem.makeSolverCalculiXCcxTools(doc, "CalculiX")
    an.addObject(sol)
    mat_name, density, mech = study_like["material"]
    E, nu, fy = mech
    mat = ObjectsFem.makeMaterialSolid(doc, "Material")
    m = mat.Material
    m.update({"Name": mat_name, "YoungsModulus": f"{E} MPa", "PoissonRatio": str(nu),
              "Density": f"{density or 7850} kg/m^3"})
    mat.Material = m
    an.addObject(mat)
    fixed = match_faces(shape, _faces_of(study_like["fixed"]))
    if not fixed:
        raise ValueError("pick at least one fixed face")
    fx = ObjectsFem.makeConstraintFixed(doc, "Fixed")
    fx.References = [(copy, tuple(fixed))]
    an.addObject(fx)
    used = list(fixed)                  # every face a fixture or load is on
    n_loads = 0
    water = {}
    for k, l in enumerate(loads):
        faces = l.get("_wet") or _faces_of(l["faces"])
        names = match_faces(shape, faces)
        if not names:
            continue
        used += names
        if l["type"] == "Force":
            fo = ObjectsFem.makeConstraintForce(doc, f"Force{k + 1}")
            fo.References = [(copy, tuple(names))]
            fo.Force = App.Units.Quantity(f"{float(l['value'])} N")
            d = l.get("direction", "Normal")
            if d != "Normal":
                axis = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0),
                        "+Z": (0, 0, 1), "-Z": (0, 0, -1)}[d]
                _force_direction(doc, fo, V(*axis), shape)
            an.addObject(fo)
            n_loads += 1
        elif l["type"] == "Pressure":
            pr = ObjectsFem.makeConstraintPressure(doc, f"Pressure{k + 1}")
            pr.References = [(copy, tuple(names))]
            pr.Pressure = App.Units.Quantity(f"{float(l['value'])} kPa")
            pr.Reversed = False
            an.addObject(pr)
            n_loads += 1
        else:
            # water: one pressure on the wetted faces; each element face gets
            # the pressure at its own depth when the solver input is written
            pr = ObjectsFem.makeConstraintPressure(doc, f"Water{k + 1}")
            pr.References = [(copy, tuple(names))]
            pr.Pressure = App.Units.Quantity("1 MPa")
            pr.Reversed = False
            an.addObject(pr)
            water[pr.Name] = (float(l["level"]), float(l.get("density", 1000.0)))
            n_loads += 1
    if study_like.get("self_weight"):
        sw = ObjectsFem.makeConstraintSelfWeight(doc, "OwnWeight")
        an.addObject(sw)
        n_loads += 1
    if not n_loads:
        raise ValueError("add a load: a force, a pressure, water pressure or the part's weight")
    size, t, t_min = mesh_size(shape, study_like.get("quality", "Normal"))
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape = copy
    mesh.CharacteristicLengthMax = size
    # finer round holes and curves, and room for small features (a hole, a
    # chamfer) without the surface mesh folding over
    # (no coarser than half a thin wall, or gmsh can't fill a pipe wall)
    mesh.CharacteristicLengthMin = max(0.3, min(size / 4, t_min / 2, 2.0))
    try:
        mesh.MeshSizeFromCurvature = 12
    except Exception:
        pass
    mesh.ElementOrder = "2nd"
    # straight-sided 2nd order elements: as good in bending, and they can't
    # turn inside out on thin curved features ("nonpositive jacobian"). But
    # their mid-side nodes are off a curved face, so FreeCAD can't find the
    # face's elements and a load or fixture on a bore, a pipe or a round tank
    # wall would be dropped without a word: keep them curved then.
    curved = any(_curved(shape.getElement(n)) for n in set(used))
    try:
        mesh.SecondOrderLinear = not curved
    except Exception:
        pass
    an.addObject(mesh)
    doc.recompute()
    info = {"element size": size, "wall": round(t, 2), "material": mat_name, "yield": fy,
            "water": water, "left out": left_out}
    return doc, an, sol, mesh, info


def _force_direction(doc, fo, axis, shape):
    """Point a force along a global axis (FreeCAD wants an edge or face):
    a small helper line, hidden."""
    import Part
    c = shape.BoundBox.Center
    line = doc.addObject("Part::Feature", "ForceDirection")
    line.Shape = Part.LineSegment(c, c + axis * 100).toShape()
    try:
        line.ViewObject.Visibility = False
    except Exception:
        pass
    fo.Direction = (line, ["Edge1"])
    fo.Reversed = False


def make_mesh(mesh, budget=None):
    """gmsh, falling back to other surface algorithms if the automatic one
    folds the surface mesh (it happens beside small features), and coarser
    once if small features made far more nodes than the budget."""
    from femmesh.gmshtools import GmshTools
    last = None
    for attempt in range(2):
        ok = False
        for alg in ("Automatic", "Delaunay", "Frontal"):
            try:
                mesh.Algorithm2D = alg
            except Exception:
                pass
            err = GmshTools(mesh).create_mesh()
            if not err and mesh.FemMesh.VolumeCount > 0 and _all_volumes(mesh):
                ok = True
                break
            last = err or "no volume elements"
        if not ok:
            raise ValueError(f"the mesh couldn't be made ({last}) - try another mesh quality")
        n = mesh.FemMesh.NodeCount
        if budget is None or n <= 1.6 * budget or attempt:
            return n
        k = math.sqrt(n / budget)
        mesh.CharacteristicLengthMax = float(mesh.CharacteristicLengthMax) * k
        mesh.CharacteristicLengthMin = float(mesh.CharacteristicLengthMin) * k
    return mesh.FemMesh.NodeCount


def _all_volumes(mesh):
    """Every solid got elements (gmsh can leave one empty and carry on)."""
    try:
        shape = mesh.Shape.Shape
        fm = mesh.FemMesh
        for s in shape.Solids:
            c = s.BoundBox.Center
            if not s.isInside(c, 1e-6, True):
                continue
            if not fm.getNodesBySolid(s):
                return False
    except Exception:
        pass
    return True


# CalculiX tetrahedron faces (corner nodes, 1-based)
TET_FACES = {"P1": (1, 2, 3), "P2": (1, 4, 2), "P3": (2, 4, 3), "P4": (3, 4, 1)}


def hydrostatic(inp, water):
    """Give each element face of a water load the pressure at its depth:
    rho g (level - z) at the face centre. water: {constraint: (level, rho)}."""
    nodes, elems = {}, {}
    section = None
    with open(inp, encoding="utf-8", errors="surrogateescape") as f:
        for line in f:
            if line.startswith("*"):
                u = line.upper()
                section = "node" if u.startswith("*NODE") and "PRINT" not in u and "FILE" not in u \
                    else "elem" if u.startswith("*ELEMENT") else None
                continue
            if section == "node":
                p = line.split(",")
                if len(p) >= 4:
                    nodes[int(p[0])] = (float(p[1]), float(p[2]), float(p[3]))
            elif section == "elem":
                p = line.split(",")
                if len(p) >= 5:
                    elems[int(p[0])] = [int(x) for x in p[1:5]]
    out = inp + ".tmp"
    current = None
    with open(inp, encoding="utf-8", errors="surrogateescape") as f, \
            open(out, "w", encoding="utf-8", errors="surrogateescape") as g:
        for line in f:
            if line.startswith("**"):
                text = line[2:].strip()
                # "** Water1" starts a constraint's loads; "** Model.Face7"
                # (a face comment inside it) doesn't change anything
                if text and " " not in text and "." not in text:
                    current = text if text in water else None
                elif " " in text:
                    current = None
                g.write(line)
                continue
            if line.startswith("*"):
                if not line.upper().startswith("*DLOAD"):
                    current = None
                g.write(line)
                continue
            if current:
                p = [x.strip() for x in line.split(",")]
                if len(p) == 3 and p[1] in TET_FACES and p[0].isdigit() and int(p[0]) in elems:
                    corners = elems[int(p[0])]
                    z = sum(nodes[corners[k - 1]][2] for k in TET_FACES[p[1]]) / 3.0
                    level, rho = water[current]
                    depth = level - z
                    if depth > 0:
                        g.write(f"{p[0]},{p[1]},{rho * G * depth * 1e-9:.6e}\n")
                    continue
            g.write(line)
    os.replace(out, inp)


class Solve:
    """CalculiX in a thread (the window stays responsive)."""

    def __init__(self, analysis, solver, water=None):
        from femtools import ccxtools
        self.fea = ccxtools.FemToolsCcx(analysis, solver)
        self.fea.update_objects()
        self.fea.setup_working_dir()
        self.fea.setup_ccx()
        msg = self.fea.check_prerequisites()
        if msg:
            raise ValueError(msg)
        self.fea.purge_results()
        self.fea.write_inp_file()
        self.water = water or {}
        if self.water:
            hydrostatic(self.fea.inp_file_name, self.water)
        self.proc = None
        self.error = None
        self.done = False

    def start(self):
        fea = self.fea
        inp = fea.inp_file_name
        workdir = os.path.dirname(inp)
        job = os.path.splitext(os.path.basename(inp))[0]
        env = dict(os.environ)
        env.setdefault("OMP_NUM_THREADS", str(max(1, (os.cpu_count() or 2))))

        def run():
            try:
                kw = {}
                if os.name == "nt":
                    kw["creationflags"] = 0x08000000      # no console window
                self.proc = subprocess.Popen([fea.ccx_binary, "-i", job], cwd=workdir, env=env,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
                out, _ = self.proc.communicate()
                self.output = out.decode(errors="replace") if out else ""
                if self.proc.returncode != 0 or "*ERROR" in self.output:
                    self.error = _ccx_error(self.output, self.proc.returncode)
            except Exception as e:
                self.error = str(e)
            self.done = True
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def cancel(self):
        try:
            if self.proc is not None:
                self.proc.kill()
        except Exception:
            pass

    def load(self):
        self.fea.load_results()
        an = self.fea.analysis
        res = [o for o in an.Group if o.isDerivedFrom("Fem::FemResultObject")]
        if not res:
            raise ValueError("CalculiX gave no results")
        return res[0]


def _ccx_error(out, code):
    for line in out.splitlines():
        if "*ERROR" in line:
            return line.strip()
    if code and code < 0 or code in (137, -9):
        return "CalculiX stopped - probably out of memory: try the Coarse mesh"
    return f"CalculiX stopped (exit code {code})"


def summarise(result, info):
    vm = list(result.vonMises)
    disp = list(result.DisplacementLengths)
    i = max(range(len(vm)), key=lambda k: vm[k])
    j = max(range(len(disp)), key=lambda k: disp[k])
    nodes = list(result.NodeNumbers)
    mesh = result.Mesh.FemMesh
    at = mesh.getNodeById(nodes[i])
    dat = mesh.getNodeById(nodes[j])
    fy = info["yield"]
    out = {k: v for k, v in info.items() if k != "water"}
    out.update({"max_stress": round(vm[i], 2), "max_stress_at": [round(x, 1) for x in at],
                "max_disp": round(disp[j], 3), "max_disp_at": [round(x, 1) for x in dat],
                "fos": round(fy / vm[i], 2) if vm[i] > 0 else None, "nodes": len(nodes)})
    return out


def show_result(result, doc):
    """Colour the result by von Mises stress, with FreeCAD's scale bar."""
    pipeline = None
    try:
        import ObjectsFem
        pipes = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemPostPipeline")]
        if pipes:
            pipeline = pipes[-1]
        else:
            pipeline = ObjectsFem.makePostVtkResult(doc, [result], "Results")
        pipeline.Label = "Von Mises stress"
        pipeline.recompute()
        if App.GuiUp:
            vo = pipeline.ViewObject
            fields = vo.getEnumerationsOfProperty("Field") or []
            pick = [f for f in fields if "mises" in f.lower()]
            if pick:
                vo.Field = pick[0]
            try:
                vo.DisplayMode = "Surface"
            except Exception:
                pass
            vo.Visibility = True
            try:
                vo.updateColorBars()
            except Exception:
                pass
            for o in doc.Objects:
                # the colour plot on its own: no model, mesh or load arrows
                if (o.Name == "Model" or o.Name.startswith("ForceDirection")
                        or o.isDerivedFrom("Fem::FemMeshObject") or o.isDerivedFrom("Fem::Constraint")):
                    try:
                        o.ViewObject.Visibility = False
                    except Exception:
                        pass
        return pipeline
    except Exception as e:
        App.Console.PrintWarning(f"MechFlow: colour plot not shown ({e})\n")
        try:
            m = result.Mesh
            m.ViewObject.setNodeColorByScalars(list(result.NodeNumbers), list(result.vonMises))
            m.ViewObject.Visibility = True
        except Exception:
            pass
        return None


def run_blocking(study_like, timeout=3600):
    """Whole check without the panel (scripts and tests)."""
    doc, an, sol, mesh, info = prepare(study_like)
    t0 = time.time()
    info["nodes"] = make_mesh(mesh, QUALITY.get(study_like.get("quality", "Normal")))
    info["element size"] = round(float(mesh.CharacteristicLengthMax), 2)
    info["mesh_s"] = round(time.time() - t0, 1)
    t0 = time.time()
    s = Solve(an, sol, info.get("water"))
    s.start()
    while not s.done and time.time() - t0 < timeout:
        time.sleep(0.5)
        if App.GuiUp:
            QtWidgets.QApplication.processEvents()
    if s.error:
        raise ValueError(s.error)
    info["solve_s"] = round(time.time() - t0, 1)
    res = s.load()
    out = summarise(res, info)
    if App.GuiUp:
        show_result(res, doc)
    return doc, out


# ------------------------------------------------------------ panel

def _default_parts(doc):
    parts = [o for o in doc.Objects if o.TypeId == "App::Part" and
             o.getParentGeoFeatureGroup() is None]
    if len(parts) == 1:
        return parts
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body" and
              o.getParentGeoFeatureGroup() is None]
    return bodies[:1]


class StressPanel:
    def __init__(self, study=None):
        self.doc = study.Document if study else App.ActiveDocument
        self.study = study
        self.parts = list(study.Parts) if study else _default_parts(self.doc)
        self.fixed = [(o, list(s)) for o, s in study.Fixed] if study else []
        self.loads = json.loads(study.Loads) if study and study.Loads else []
        self._load_refs()
        self.pick = "fixed"
        self.solver = None
        self.form = self._build()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        Gui.Selection.clearSelection()
        self._refresh()

    def _load_refs(self):
        for l in self.loads:
            refs = []
            for name, subs in l.get("refs", []):
                o = self.doc.getObject(name)
                if o is not None:
                    refs.append((o, list(subs)))
            l["faces"] = refs

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Stress Check")
        lay = QtWidgets.QVBoxLayout(w)
        self.head = QtWidgets.QLabel()
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        mat = QtWidgets.QHBoxLayout()
        mat.addWidget(QtWidgets.QLabel("Material"))
        self.mat = QtWidgets.QComboBox()
        self.mat.addItems(list(MECH))
        mat.addWidget(self.mat, 1)
        lay.addLayout(mat)
        box = QtWidgets.QGroupBox("1. Fixtures")
        bl = QtWidgets.QVBoxLayout(box)
        self.fix_btn = QtWidgets.QPushButton("Pick fixed faces")
        self.fix_btn.setCheckable(True)
        self.fix_btn.setChecked(True)
        self.fix_btn.clicked.connect(lambda: self._mode("fixed"))
        bl.addWidget(self.fix_btn)
        self.fix_list = QtWidgets.QLabel()
        bl.addWidget(self.fix_list)
        lay.addWidget(box)
        box2 = QtWidgets.QGroupBox("2. Loads")
        l2 = QtWidgets.QVBoxLayout(box2)
        row = QtWidgets.QHBoxLayout()
        self.ltype = QtWidgets.QComboBox()
        self.ltype.addItems(LOAD_TYPES)
        self.lval = QtWidgets.QDoubleSpinBox()
        self.lval.setRange(0, 1e9)
        self.lval.setDecimals(2)
        self.lval.setValue(1000)
        self.ldir = QtWidgets.QComboBox()
        self.ldir.addItems(["Normal", "+X", "-X", "+Y", "-Y", "+Z", "-Z"])
        row.addWidget(self.ltype)
        row.addWidget(self.lval)
        row.addWidget(self.ldir)
        l2.addLayout(row)
        self.lhint = QtWidgets.QLabel()
        self.lhint.setWordWrap(True)
        self.lhint.setStyleSheet("color: gray;")
        l2.addWidget(self.lhint)
        self.add_load = QtWidgets.QPushButton("Pick faces for a new load")
        self.add_load.setCheckable(True)
        self.add_load.clicked.connect(lambda: self._mode("load"))
        l2.addWidget(self.add_load)
        self.load_list = QtWidgets.QListWidget()
        self.load_list.setMaximumHeight(90)
        l2.addWidget(self.load_list)
        rm = QtWidgets.QPushButton("Remove load")
        rm.clicked.connect(self._remove_load)
        l2.addWidget(rm)
        self.weight = QtWidgets.QCheckBox("Include the part's own weight")
        l2.addWidget(self.weight)
        lay.addWidget(box2)
        row3 = QtWidgets.QHBoxLayout()
        row3.addWidget(QtWidgets.QLabel("3. Mesh"))
        self.quality = QtWidgets.QComboBox()
        self.quality.addItems(list(QUALITY))
        self.quality.setCurrentText(self.study.Mesh if self.study else "Normal")
        row3.addWidget(self.quality, 1)
        lay.addLayout(row3)
        self.simple = QtWidgets.QCheckBox("Leave out small holes and stubs (much faster on big parts)")
        self.simple.setChecked(bool(getattr(self.study, "Simplify", True)) if self.study else True)
        lay.addWidget(self.simple)
        self.run_btn = QtWidgets.QPushButton("4. Run")
        self.run_btn.clicked.connect(self._run)
        lay.addWidget(self.run_btn)
        self.result = QtWidgets.QLabel()
        self.result.setWordWrap(True)
        self.result.setTextFormat(QtCore.Qt.RichText)
        lay.addWidget(self.result)
        lay.addStretch(1)
        self.ltype.currentTextChanged.connect(self._type_changed)
        self._type_changed()
        name, dens, mech = material_of(self.parts)
        if name in MECH:
            self.mat.setCurrentText(name)
        if self.study:
            self.weight.setChecked(self.study.SelfWeight)
            if self.study.Result:
                self._show(json.loads(self.study.Result))
        return w

    def _type_changed(self, *_):
        t = self.ltype.currentText()
        self.ldir.setVisible(t == "Force")
        self.lval.setSuffix({"Force": " N", "Pressure": " kPa", "Water pressure": " kg/m³"}[t])
        if t == "Water pressure" and self.lval.value() in (1000.0, 0.0) or t == "Water pressure":
            self.lval.setValue(1000)
        self.lhint.setText({
            "Force": "Total force spread over the picked faces.",
            "Pressure": "Pressure on the picked faces (1 bar = 100 kPa).",
            "Water pressure": "Click one inside face the liquid touches (e.g. the tank "
                              "bottom, through Section View): the rest are found for you. The "
                              "value is the liquid's density (water 1000 kg/m³); it's full to the "
                              "top of the wetted faces."}[t])

    def _mode(self, m):
        self.pick = m
        self.fix_btn.setChecked(m == "fixed")
        self.add_load.setChecked(m == "load")
        if m == "load":
            self.loads.append({"type": self.ltype.currentText(), "value": self.lval.value(),
                               "direction": self.ldir.currentText(), "faces": []})
        self._refresh()

    def _poll(self):
        try:
            sel = Gui.Selection.getSelectionEx("", 0)
        except Exception:
            return
        if not sel:
            return
        Gui.Selection.clearSelection()
        for s in sel:
            for sub in s.SubElementNames:
                if not sub.rsplit(".", 1)[-1].startswith("Face"):
                    continue
                key = (s.Object, [sub])
                if self.pick == "fixed":
                    self.fixed.append(key)
                elif self.loads:
                    self.loads[-1]["faces"].append(key)
        self._refresh()

    def _remove_load(self):
        r = self.load_list.currentRow()
        if 0 <= r < len(self.loads):
            del self.loads[r]
            self._refresh()

    def _refresh(self):
        names = ", ".join(p.Label for p in self.parts) or "nothing"
        self.head.setText(f"<b>Stress Check</b> of {names}. Your part isn't changed - the check "
                          "runs on a copy.")
        self.fix_list.setText(f"{sum(len(s) for _o, s in self.fixed)} fixed face(s)")
        self.load_list.clear()
        for l in self.loads:
            unit = {"Force": "N", "Pressure": "kPa", "Water pressure": "kg/m³"}[l["type"]]
            extra = f" {l.get('direction')}" if l["type"] == "Force" else ""
            self.load_list.addItem(f"{l['type']} {l['value']:g} {unit}{extra} on "
                                   f"{len(l['faces'])} face(s)")

    def _spec(self):
        for l in self.loads:
            if self.loads and l is self.loads[-1] and self.pick == "load":
                l.update({"type": self.ltype.currentText(), "value": self.lval.value(),
                          "direction": self.ldir.currentText()})
        loads = [dict(l, density=l["value"]) if l["type"] == "Water pressure" else dict(l)
                 for l in self.loads if l["faces"]]
        name = self.mat.currentText()
        _n, dens, _m = material_of(self.parts)
        return {"parts": self.parts, "fixed": self.fixed, "loads": loads,
                "material": (name, dens or 7850, MECH[name]),
                "self_weight": self.weight.isChecked(), "quality": self.quality.currentText(),
                "simplify": self.simple.isChecked()}

    def _save_study(self, result=None):
        if self.study is None:
            self.study = self.doc.addObject("App::FeaturePython", "StressStudy")
            StressStudy(self.study)
            if App.GuiUp:
                ViewProviderStressStudy(self.study.ViewObject)
            self.study.Label = "Stress Check"
        s = self.study
        s.Parts = self.parts
        s.Fixed = [(o, tuple(sb)) for o, sb in self.fixed]
        s.Loads = json.dumps([{k: v for k, v in l.items() if k != "faces"} |
                              {"refs": [(o.Name, list(sb)) for o, sb in l["faces"]]}
                              for l in self.loads if l["faces"]])
        s.SelfWeight = self.weight.isChecked()
        s.Mesh = self.quality.currentText()
        if not hasattr(s, "Simplify"):
            s.addProperty("App::PropertyBool", "Simplify", "Study", "Leave out small holes")
        s.Simplify = self.simple.isChecked()
        if result is not None:
            s.Result = json.dumps(result)

    def _run(self):
        self.pick = None
        try:
            spec = self._spec()
            self._save_study()
            self.result.setText("Preparing the model (joining the parts, leaving out small holes)...")
            QtWidgets.QApplication.processEvents()
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                self.rdoc, an, sol, mesh, self.info = prepare(spec)
                self.result.setText(f"Meshing ({self.info['element size']} mm elements)...")
                QtWidgets.QApplication.processEvents()
                t0 = time.time()
                self.info["nodes"] = make_mesh(mesh, QUALITY.get(spec.get("quality", "Normal")))
                self.info["element size"] = round(float(mesh.CharacteristicLengthMax), 2)
                self.info["mesh_s"] = round(time.time() - t0, 1)
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self.solver = Solve(an, sol, self.info.get("water"))
            self.solver.start()
            self.t0 = time.time()
            self.run_btn.setText("Cancel")
            self.run_btn.clicked.disconnect()
            self.run_btn.clicked.connect(self._cancel)
            self._wait = QtCore.QTimer()
            self._wait.setInterval(500)
            self._wait.timeout.connect(self._check)
            self._wait.start()
        except Exception as e:
            self.result.setText(f"<span style='color:#b00020'><b>Can't run:</b> {e}</span>")

    def _check(self):
        s = self.solver
        if not s.done:
            self.result.setText(f"Solving {self.info['nodes']:,} nodes... "
                                f"{time.time() - self.t0:.0f} s")
            return
        self._wait.stop()
        self._reset_button()
        if s.error:
            self.result.setText(f"<span style='color:#b00020'><b>The solve failed:</b> "
                                f"{s.error}</span>")
            return
        self.info["solve_s"] = round(time.time() - self.t0, 1)
        res = s.load()
        out = summarise(res, self.info)
        if not out.get("max_disp") and not out.get("max_stress"):
            # nothing moved: the loads never reached the mesh
            self.result.setText("<span style='color:#b00020'><b>No result:</b> the loads didn't "
                                "reach the model. Pick the load faces again and re-run.</span>")
            return
        show_result(res, self.rdoc)
        self._save_study(out)
        self._show(out)
        try:
            Gui.getDocument(self.rdoc.Name).ActiveView.viewIsometric()
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass

    def _cancel(self):
        if self.solver:
            self.solver.cancel()
        self._reset_button()

    def _reset_button(self):
        self.run_btn.setText("4. Run")
        try:
            self.run_btn.clicked.disconnect()
        except Exception:
            pass
        self.run_btn.clicked.connect(self._run)

    def _show(self, r):
        fos = r.get("fos")
        ok = fos is not None and fos >= 1.5
        colour = "#1b7f3b" if ok else ("#b26a00" if fos and fos >= 1 else "#b00020")
        verdict = ("Passes (factor of safety at least 1.5)" if ok else
                   "Marginal: under 1.5" if fos and fos >= 1 else "Yields: over the yield stress")
        wall = r.get("wall")
        note = ""
        if r.get("left out"):
            note += (f"<br><span style='color:gray'>{r['left out']} small hole/stub faces were "
                     f"left out of the check.</span>")
        if wall and r["max_disp"] > 0.5 * wall:
            note += (f"<br><span style='color:gray'>The deflection is more than half the "
                    f"{wall:g} mm wall: real panels are stiffer than this linear check "
                    f"says - but it's a sign they need stiffening.</span>")
        self.result.setText(
            f"<b>Max von Mises stress:</b> {r['max_stress']:,.1f} MPa at {tuple(r['max_stress_at'])}<br>"
            f"<b>Yield ({r['material']}):</b> {r['yield']} MPa<br>"
            f"<b style='color:{colour}'>Factor of safety {fos}: {verdict}</b><br>"
            f"<b>Max deflection:</b> {r['max_disp']:,.2f} mm<br>"
            f"<span style='color:gray'>{r.get('nodes', 0):,} nodes, {r['element size']} mm "
            f"elements; mesh {r.get('mesh_s', '?')} s, solve {r.get('solve_s', '?')} s. "
            f"Peaks at sharp corners and right at fixed edges read high.</span>{note}")

    def accept(self):
        self._timer.stop()
        self._save_study()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._timer.stop()
        if self.solver and not self.solver.done:
            self.solver.cancel()
        Gui.Control.closeDialog()
        return True


def stress_check():
    if App.ActiveDocument is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Stress Check",
                                          "Finish the open dialog first.")
        return None
    studies = [o for o in App.ActiveDocument.Objects if is_study(o)]
    p = StressPanel(studies[0] if studies else None)
    Gui.Control.showDialog(p)
    return p
