# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draw origin planes whose eyeball is on.

FreeCAD 1.1 never draws the planes inside a body's Origin, so the tree's
eyeball appears to do nothing. MechFlow draws each origin plane whose
eyeball is on as a SOLIDWORKS-style plane in the 3D view. Nothing is saved
to the file.

The drawn planes act like real ones: hover turns them orange, a click selects
the origin plane (Ctrl+click adds it), and right-click > Sketch works on them.
Picking is done by MechFlow (a ray through the cursor), so the model in front
of a plane still wins.
"""

import FreeCAD as App
import FreeCADGui as Gui

# origin plane name prefix -> colour
COLOURS = {
    "XY_Plane": (0.30, 0.55, 0.95),   # Top
    "XZ_Plane": (0.35, 0.80, 0.40),   # Front
    "YZ_Plane": (0.95, 0.40, 0.35),   # Right
}

_shown = {}   # (doc, plane name) -> (scene graph root, node, size, state)
_hover = None        # key of the plane under the mouse
_hover_timer = None
_last_pos = None
_callbacks = {}      # id(view) -> (view, callback)

STATE_LOOK = {        # colour, fill transparency
    "normal": (None, 0.92),
    "hover": ((1.0, 0.55, 0.15), 0.80),
    "sel": ((0.10, 0.45, 1.0), 0.72),
}


def _colour(plane):
    for key, rgb in COLOURS.items():
        if plane.Name.startswith(key):
            return rgb
    return (0.6, 0.6, 0.6)


_size_cache = {}       # doc name -> (time, size): measuring every shape is slow on big models


def _size(doc):
    import time
    from mechflow_gui import sketch_start
    hit = _size_cache.get(doc.Name)
    if hit and time.time() - hit[0] < 2.0:
        return hit[1]
    try:
        size = sketch_start._plane_size(doc)
    except Exception:
        size = 100.0
    _size_cache[doc.Name] = (time.time(), size)
    return size


def _build(plane, size):
    from pivy import coin
    h = size / 2.0
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)

    tf = coin.SoTransform()
    pl = plane.getGlobalPlacement() if hasattr(plane, "getGlobalPlacement") else plane.Placement
    tf.translation = (pl.Base.x, pl.Base.y, pl.Base.z)
    q = pl.Rotation.Q
    tf.rotation.setValue(q[0], q[1], q[2], q[3])
    root.addChild(tf)

    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
    root.addChild(hints)

    rgb = _colour(plane)
    mat = coin.SoMaterial()
    mat.diffuseColor = rgb
    mat.emissiveColor = tuple(c * 0.3 for c in rgb)
    mat.transparency = 0.75
    root.addChild(mat)

    pts = [[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]]
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, 4, pts)
    root.addChild(coords)
    face = coin.SoFaceSet()
    face.numVertices.setValue(4)
    root.addChild(face)

    edge_sep = coin.SoSeparator()
    edge_mat = coin.SoMaterial()
    edge_mat.diffuseColor = rgb
    edge_mat.transparency = 0.2
    edge_sep.addChild(edge_mat)
    style = coin.SoDrawStyle()
    style.lineWidth = 1.5
    edge_sep.addChild(style)
    ecoords = coin.SoCoordinate3()
    ecoords.point.setValues(0, 5, pts + [pts[0]])
    edge_sep.addChild(ecoords)
    line = coin.SoLineSet()
    line.numVertices.setValue(5)
    edge_sep.addChild(line)
    root.addChild(edge_sep)
    return root


def _placement(plane):
    try:
        return plane.getGlobalPlacement()
    except Exception:
        return plane.Placement


def _build_sw(plane, size, state="normal"):
    """SOLIDWORKS look: thin blue outline, corner dots and the plane's name."""
    from mechflow_gui import plane_art
    pl = _placement(plane)
    rgb, fill = STATE_LOOK.get(state, STATE_LOOK["normal"])
    return plane_art.build(pl.Rotation, pl.Base, size, plane.Label,
                           rgb or plane_art.SW_BLUE, fill)


def _scene(doc_name):
    from pivy import coin  # noqa: F401  (FreeCAD needs pivy loaded first)
    gdoc = Gui.getDocument(doc_name)
    view = gdoc.ActiveView if gdoc is not None else None
    if view is None or not hasattr(view, "getSceneGraph"):
        return None
    return view.getSceneGraph()


def _remove(key):
    entry = _shown.pop(key, None)
    if entry:
        try:
            entry[0].removeChild(entry[1])
        except Exception:
            pass


def refresh():
    """Called a few times a second while MechFlow is active."""
    open_docs = App.listDocuments()
    for key in list(_shown):
        if key[0] not in open_docs:
            _shown.pop(key, None)

    doc = App.ActiveDocument
    if doc is None:
        return
    if not any(o.TypeId == "PartDesign::Body" for o in doc.Objects):
        for key in [k for k in _shown if k[0] == doc.Name]:
            _remove(key)
        return
    size = _size(doc)
    wanted = set()
    for body in doc.Objects:
        if body.TypeId != "PartDesign::Body":
            continue
        origin = getattr(body, "Origin", None)
        for f in getattr(origin, "OriginFeatures", []) if origin else []:
            if f.TypeId != "App::Plane":
                continue
            try:
                visible = f.ViewObject.Visibility and body.ViewObject.Visibility
            except Exception:
                visible = False
            if visible:
                wanted.add((doc.Name, f.Name))

    selected = _selected_names(doc)
    states = {k: ("sel" if k[1] in selected else "hover" if k == _hover else "normal")
              for k in wanted}

    # Remove planes switched off, resized or with a new look (rebuilt below).
    for key in list(_shown):
        if key[0] == doc.Name and (key not in wanted or abs(_shown[key][2] - size) > 1e-6
                                   or _shown[key][3] != states.get(key)):
            _remove(key)

    for key in wanted:
        if key in _shown:
            continue
        sg = _scene(doc.Name)
        plane = doc.getObject(key[1])
        if sg is None or plane is None:
            continue
        node = _build_sw(plane, size, states[key])
        sg.addChild(node)
        _shown[key] = (sg, node, size, states[key])
    if wanted:
        _start_picking(doc)


def clear():
    global _hover
    for key in list(_shown):
        _remove(key)
    _hover = None
    if _hover_timer is not None:
        _hover_timer.stop()
    for view, cb in list(_callbacks.values()):
        try:
            from pivy import coin
            view.removeEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), cb)
        except Exception:
            pass
    _callbacks.clear()


# ------------------------------------------------------------ picking planes

def _selected_names(doc):
    try:
        return {i.Object.Name for i in Gui.Selection.getSelectionEx(doc.Name)
                if not i.SubElementNames}
    except Exception:
        return set()


def _busy():
    """Times when the drawn planes shouldn't react (sketching, picking a plane
    for a new sketch)."""
    try:
        from mechflow_gui import sketch_mode, sketch_start
        return sketch_mode.editing_sketch() or sketch_start.picking()
    except Exception:
        return False


def _ray(view, pos):
    """(point, direction) of the line of sight through a view position."""
    p = view.getPoint(int(pos[0]), int(pos[1]))
    d = None
    try:
        cam = view.getCameraNode()
        if "Perspective" in cam.getTypeId().getName().getString():
            c = cam.position.getValue()
            d = p - App.Vector(c[0], c[1], c[2])
    except Exception:
        pass
    if d is None or d.Length < 1e-12:
        d = App.Vector(view.getViewDirection())
    return p, d.normalize()


def plane_under(view, pos):
    """The shown origin plane under a view position, or None. A part of the
    model in front of the plane hides it."""
    doc = App.ActiveDocument
    if doc is None or not _shown:
        return None
    try:
        p, d = _ray(view, pos)
    except Exception:
        return None
    best = None
    for key, entry in _shown.items():
        if key[0] != doc.Name:
            continue
        plane = doc.getObject(key[1])
        if plane is None:
            continue
        pl = _placement(plane)
        n = pl.Rotation.multVec(App.Vector(0, 0, 1))
        den = d.dot(n)
        if abs(den) < 1e-9:
            continue
        s = (pl.Base - p).dot(n) / den
        loc = pl.inverse().multVec(p + d * s)
        h = entry[2] / 2.0
        if abs(loc.x) <= h and abs(loc.y) <= h and (best is None or s < best[0]):
            best = (s, plane)
    if best is None:
        return None
    try:
        info = view.getObjectInfo((int(pos[0]), int(pos[1])))
    except Exception:
        info = None
    if isinstance(info, dict) and info.get("Object") and "x" in info:
        if not str(info["Object"]).startswith("MechFlow_"):
            m = App.Vector(info["x"], info["y"], info["z"])
            if (m - p).dot(d) < best[0] - 1e-6:
                return None              # the model is in front
    return best[1]


def _start_picking(doc):
    global _hover_timer
    gdoc = Gui.getDocument(doc.Name)
    view = gdoc.ActiveView if gdoc is not None else None
    if view is not None and id(view) not in _callbacks and hasattr(view, "addEventCallbackPivy"):
        try:
            from pivy import coin
            cb = _make_click(view)
            view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(), cb)
            _callbacks[id(view)] = (view, cb)
        except Exception:
            pass
    if _hover_timer is None:
        try:
            from PySide6 import QtCore
        except ImportError:
            from PySide2 import QtCore
        _hover_timer = QtCore.QTimer()
        _hover_timer.setInterval(80)
        _hover_timer.timeout.connect(_hover_tick)
    if not _hover_timer.isActive():
        _hover_timer.start()


def _hover_tick():
    global _hover, _last_pos
    try:
        if not _shown:
            if _hover_timer is not None:
                _hover_timer.stop()
            return
        doc = App.ActiveDocument
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if doc is None or view is None or _busy():
            new = None
        else:
            pos = tuple(view.getCursorPos())
            if pos == _last_pos:
                return
            _last_pos = pos
            plane = plane_under(view, pos)
            new = (doc.Name, plane.Name) if plane is not None else None
        if new != _hover:
            _hover = new
            refresh()
    except Exception:
        pass


def _make_click(view):
    """Select a drawn plane on a click. Done when the button comes back up
    (FreeCAD clears the selection then), and only if the mouse didn't move
    - a drag is a box-select or a rotate, not a click."""
    from pivy import coin
    down = {"pos": None}

    def on_mouse(event_cb):
        try:
            ev = event_cb.getEvent()
            if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1 or _busy():
                return
            pos = ev.getPosition().getValue()
            if ev.getState() == coin.SoButtonEvent.DOWN:
                down["pos"] = pos
                return
            start, down["pos"] = down["pos"], None
            if start is None or abs(pos[0] - start[0]) + abs(pos[1] - start[1]) > 5:
                return
            plane = plane_under(view, pos)
            if plane is None:
                return
            add = ev.wasCtrlDown()
            try:
                from PySide6 import QtCore
            except ImportError:
                from PySide2 import QtCore
            # After FreeCAD has finished with the click (it clears the selection).
            QtCore.QTimer.singleShot(0, lambda: _select(plane, add))
        except Exception:
            pass
    return on_mouse


def _select(plane, add):
    try:
        if not add:
            Gui.Selection.clearSelection()
        Gui.Selection.addSelection(plane)
        refresh()
    except Exception:
        pass
