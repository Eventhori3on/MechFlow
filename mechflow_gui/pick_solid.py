# SPDX-License-Identifier: LGPL-2.1-or-later
"""Face / feature highlighting while picking where to sketch.

- Which feature created a face of the finished solid (for the tree highlight).
- The faces a feature created (for highlighting it from the tree).
- A display-only Coin overlay to light faces up (FreeCAD's own hover
  highlight is muted while picking so the plane colours show).
- Choosing a feature's best flat face to sketch on (the one facing you).
"""

import FreeCAD as App
import FreeCADGui as Gui

HIGHLIGHT = (0.35, 0.65, 1.0)
TOL = 1e-4

_overlay = None          # (scene graph root, node, key)
_creator_cache = {}      # (doc, body, tip, face index) -> feature name


# ------------------------------------------------------------------ model logic

def body_of(obj):
    for o in getattr(obj, "InList", []):
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def active_body():
    doc = App.ActiveDocument
    if doc is None:
        return None
    try:
        b = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        if b is not None:
            return b
    except Exception:
        pass
    bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
    return bodies[0] if len(bodies) == 1 else None


def _solid_features(body):
    """Solid-making features in history order, up to and including the tip."""
    feats = []
    for o in body.Group:
        if not o.isDerivedFrom("PartDesign::Feature"):
            continue
        shape = getattr(o, "Shape", None)
        try:
            if shape is None or shape.isNull() or not shape.Solids:
                continue
        except Exception:
            continue
        feats.append(o)
        if o == body.Tip:
            break
    return feats


def _global(shape, body):
    """A body-local shape in global coordinates."""
    pl = body.Placement
    if pl.isIdentity():
        return shape
    s = shape.copy()
    s.transformShape(pl.toMatrix())
    return s


def _tip_shape(body):
    return body.Shape            # global, = tip shape with body placement


def _face_probe(face):
    """A point inside the face and its normal there."""
    u0, u1, v0, v1 = face.ParameterRange
    u, v = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    p = face.valueAt(u, v)
    if not face.isInside(p, TOL, True):
        p = face.CenterOfMass
    try:
        n = face.normalAt(*face.Surface.parameter(p))
    except Exception:
        n = face.normalAt(u, v)
    return p, n


def creator_of(body, face_index):
    """The earliest feature whose solid already has this face's surface at
    this spot - i.e. the feature that created the face."""
    tip = body.Tip
    key = (body.Document.Name, body.Name, getattr(tip, "Name", None), face_index)
    if key in _creator_cache:
        return body.Document.getObject(_creator_cache[key]) if _creator_cache[key] else None
    import Part
    result = None
    try:
        face = _tip_shape(body).Faces[face_index]
        p, n = _face_probe(face)
        probe = Part.Vertex(p)
        for feat in _solid_features(body):
            shape = _global(feat.Shape, body)
            for g in shape.Faces:
                try:
                    if probe.distToShape(g)[0] > TOL:
                        continue
                    gn = g.normalAt(*g.Surface.parameter(p))
                    if abs(abs(gn.dot(n)) - 1.0) < 1e-3:
                        result = feat
                        break
                except Exception:
                    continue
            if result is not None:
                break
    except Exception:
        result = None
    _creator_cache[key] = result.Name if result is not None else None
    return result


def faces_of_feature(body, feature):
    """Indices of the finished solid's faces that this feature created."""
    try:
        n = len(_tip_shape(body).Faces)
    except Exception:
        return []
    return [i for i in range(n) if creator_of(body, i) == feature]


def best_face(body, feature):
    """The feature's flat face that faces the viewer most (largest wins ties).
    Returns the face index in the finished solid, or None."""
    try:
        d = Gui.ActiveDocument.ActiveView.getViewDirection()
        view_dir = App.Vector(d[0], d[1], d[2])
    except Exception:
        view_dir = App.Vector(0, 0, -1)
    tip = _tip_shape(body)
    best, best_score = None, None
    for i in faces_of_feature(body, feature):
        f = tip.Faces[i]
        if type(f.Surface).__name__ != "Plane":
            continue
        _p, n = _face_probe(f)
        facing = -n.dot(view_dir)            # 1 = straight at you
        score = (round(facing, 3), f.Area)
        if best_score is None or score > best_score:
            best, best_score = i, score
    return best


def face_under_cursor():
    """(body, face index) for the solid face under the mouse, if any."""
    try:
        view = Gui.ActiveDocument.ActiveView
        info = view.getObjectInfo(view.getCursorPos())
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    comp = info.get("Component") or ""
    if not comp.startswith("Face"):
        return None
    doc = App.ActiveDocument
    obj = doc.getObject(info.get("Object", "")) if doc else None
    if obj is None:
        return None
    body = obj if obj.TypeId == "PartDesign::Body" else body_of(obj)
    if body is None:
        return None
    try:
        return body, int(comp[4:]) - 1
    except ValueError:
        return None


def select_face(body, face_index):
    """Select a face of the finished solid (for PartDesign_NewSketch)."""
    tip = body.Tip
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(tip.Document.Name, tip.Name, f"Face{face_index + 1}")


# ------------------------------------------------------------------ overlay

def _scene():
    try:
        from pivy import coin  # noqa: F401  (FreeCAD needs pivy loaded first)
        return Gui.ActiveDocument.ActiveView.getSceneGraph()
    except Exception:
        return None


def _build(faces):
    from pivy import coin
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    offset = coin.SoPolygonOffset()
    offset.factor = -2.0
    offset.units = -2.0
    root.addChild(offset)
    mat = coin.SoMaterial()
    mat.diffuseColor = HIGHLIGHT
    mat.emissiveColor = tuple(c * 0.6 for c in HIGHLIGHT)
    mat.transparency = 0.35
    root.addChild(mat)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    root.addChild(hints)
    pts, idx = [], []
    for f in faces:
        try:
            p, tris = f.tessellate(0.2)
        except Exception:
            continue
        base = len(pts)
        pts.extend([[v.x, v.y, v.z] for v in p])
        for a, b, c in tris:
            idx.extend([base + a, base + b, base + c, -1])
    if not pts:
        return None
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    root.addChild(coords)
    fs = coin.SoIndexedFaceSet()
    fs.coordIndex.setValues(0, len(idx), idx)
    root.addChild(fs)
    return root


def show(key, body, face_indices):
    """Light up faces of the finished solid (no-op if already showing `key`)."""
    global _overlay
    if _overlay is not None and _overlay[2] == key:
        return
    clear()
    if not face_indices:
        return
    sg = _scene()
    if sg is None:
        return
    tip = _tip_shape(body)
    node = _build([tip.Faces[i] for i in face_indices if i < len(tip.Faces)])
    if node is None:
        return
    sg.addChild(node)
    _overlay = (sg, node, key)


def clear():
    global _overlay
    if _overlay is not None:
        try:
            _overlay[0].removeChild(_overlay[1])
        except Exception:
            pass
        _overlay = None


def reset():
    clear()
    _creator_cache.clear()
