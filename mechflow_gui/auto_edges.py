# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dimension straight to model edges, SOLIDWORKS-style.

FreeCAD can only dimension to geometry inside the sketch. So when a sketch is
opened, MechFlow copies in (as reference lines) the edges of the solid's
faces lying in the sketch plane - the edges you normally dimension to. They
sit exactly on the model edges, so Smart Dimension can pick them directly.

When the sketch is closed, the copied edges that no dimension or relation
uses are removed again, so the sketch stays clean.

Setting: Preferences/Mod/MechFlow  AutoModelEdges (default True).
"""

import FreeCAD as App

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
MAX_EDGES = 80          # don't flood a sketch on very complex faces
ANGLE_TOL = 1e-6
DIST_TOL = 1e-4

_session = None          # {"doc", "sketch", "geo_ids"} for the open sketch


def enabled():
    return App.ParamGet(PARAMS).GetBool("AutoModelEdges", True)


def _body_of(obj):
    for o in obj.InList:
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def _previous_solid(sketch):
    """The last solid feature before the sketch in its body - the model as it
    is at this point in the history (avoids circular references)."""
    body = _body_of(sketch)
    if body is None:
        return None
    group = list(body.Group)
    if sketch not in group:
        return None
    for o in reversed(group[:group.index(sketch)]):
        shape = getattr(o, "Shape", None)
        if o.isDerivedFrom("PartDesign::Feature") and shape is not None:
            try:
                if not shape.isNull() and shape.Solids:
                    return o
            except Exception:
                pass
    return None


def _coplanar_edges(feature, sketch):
    """Edge names of the feature's faces that lie in the sketch plane."""
    pl = sketch.Placement
    normal = pl.Rotation.multVec(App.Vector(0, 0, 1))
    origin = pl.Base
    shape = feature.Shape
    wanted = []
    for face in shape.Faces:
        try:
            if type(face.Surface).__name__ != "Plane":
                continue
            n = face.normalAt(0, 0)
            if abs(abs(n.dot(normal)) - 1.0) > ANGLE_TOL:
                continue
            if abs((face.Vertexes[0].Point - origin).dot(normal)) > DIST_TOL:
                continue
        except Exception:
            continue
        for e in face.Edges:
            for i, se in enumerate(shape.Edges):
                if se.isSame(e):
                    name = f"Edge{i + 1}"
                    if name not in wanted:
                        wanted.append(name)
                    break
    return wanted[:MAX_EDGES]


def _external_count(sketch):
    try:
        return len(sketch.ExternalGeo)
    except Exception:
        return None


def enter(sketch):
    """Sketch opened: copy in the coplanar model edges as reference lines."""
    global _session
    _session = None
    if sketch is None or not enabled():
        return
    feature = _previous_solid(sketch)
    if feature is None:
        return
    edges = _coplanar_edges(feature, sketch)
    if not edges:
        return
    before = _external_count(sketch)
    if before is None:
        return
    doc = sketch.Document
    doc.openTransaction("Model edges for dimensioning")
    added = []
    try:
        for name in edges:
            try:
                sketch.addExternal(feature.Name, name)
            except Exception:
                continue   # already referenced, or not projectable
        after = _external_count(sketch) or before
        # ExternalGeo index i  <->  geo id -(i + 1)
        added = [-(i + 1) for i in range(before, after)]
        # Make sure they are reference lines, not part of the outline.
        try:
            from mechflow_gui import convert_ref
            defining = [e for e in convert_ref.defining_externals(sketch)
                        if e[1] in added]
            if defining:
                convert_ref.make_reference(sketch, defining)
        except Exception:
            pass
        sketch.recompute()
    finally:
        doc.commitTransaction()
    _session = {"doc": doc.Name, "sketch": sketch.Name, "geo_ids": added}


def _used_geo_ids(sketch):
    used = set()
    for c in sketch.Constraints:
        for attr in ("First", "Second", "Third"):
            g = getattr(c, attr, -2000)
            if g is not None and g <= -3:
                used.add(g)
    return used


def leave():
    """Sketch closed: remove the copied edges that nothing uses."""
    global _session
    s, _session = _session, None
    if not s or not s["geo_ids"]:
        return
    doc = App.listDocuments().get(s["doc"])
    sketch = doc.getObject(s["sketch"]) if doc else None
    if sketch is None:
        return
    used = _used_geo_ids(sketch)
    count = _external_count(sketch) or 0
    # External index for geo id g is (-g - 3); delete from the highest down so
    # earlier indices stay valid.
    unused = sorted((g for g in s["geo_ids"] if g not in used and -g - 1 < count),
                    reverse=False)   # more negative = higher index first
    if not unused:
        return
    doc.openTransaction("Tidy model edges")
    try:
        for g in unused:
            try:
                sketch.delExternal(-g - 3)
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: couldn't tidy a model edge ({e})\n")
        doc.recompute()
    finally:
        doc.commitTransaction()
