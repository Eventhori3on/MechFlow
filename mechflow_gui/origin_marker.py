# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style origin marker: small blue X/Y/Z arrows at 0,0,0.

FreeCAD 1.1 doesn't draw its own Origin, so MechFlow adds a display-only
marker to each 3D view while MechFlow is active. It is not a document object:
nothing is saved to the file, and it can't be clicked.

Currently switched off - the Origin eyeball in the tree does this job.
"""

import FreeCAD as App
import FreeCADGui as Gui

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
BLUE = (0.25, 0.50, 0.95)

_markers = {}   # doc name -> (scene graph root, marker separator, scale node, last size)


def enabled():
    # Off: the tree's Origin eyeball already shows FreeCAD's labelled origin,
    # so this extra marker only got in the way.
    return False


def _marker_size(doc):
    """About a tenth of the part, so it stays readable at any part size."""
    box = None
    for o in doc.Objects:
        shape = getattr(o, "Shape", None)
        if shape is None or o.Name.startswith("MechFlow_Pick"):
            continue
        try:
            if shape.isNull() or not shape.Solids:
                continue
            box = shape.BoundBox if box is None else box.united(shape.BoundBox)
        except Exception:
            pass
    if box is None or box.DiagonalLength < 1e-6:
        return 15.0
    return max(5.0, box.DiagonalLength * 0.1)


def _build():
    from pivy import coin
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    scale = coin.SoScale()
    root.addChild(scale)
    colour = coin.SoBaseColor()
    colour.rgb = BLUE
    root.addChild(colour)
    style = coin.SoDrawStyle()
    style.lineWidth = 2
    root.addChild(style)

    coords = coin.SoCoordinate3()
    coords.point.setValues(0, 4, [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
    root.addChild(coords)
    lines = coin.SoIndexedLineSet()
    lines.coordIndex.setValues(0, 9, [0, 1, -1, 0, 2, -1, 0, 3, -1])
    root.addChild(lines)

    # Arrow heads: a cone points along +Y by default.
    for translation, axis, angle in (((1, 0, 0), (0, 0, 1), -1.5708),
                                     ((0, 1, 0), (0, 0, 1), 0.0),
                                     ((0, 0, 1), (1, 0, 0), 1.5708)):
        sep = coin.SoSeparator()
        t = coin.SoTransform()
        t.translation = translation
        t.rotation.setValue(coin.SbVec3f(*axis), angle)
        sep.addChild(t)
        cone = coin.SoCone()
        cone.bottomRadius = 0.06
        cone.height = 0.2
        sep.addChild(cone)
        root.addChild(sep)

    dot = coin.SoSphere()
    dot.radius = 0.04
    root.addChild(dot)
    return root, scale


def _view_root(doc_name):
    from pivy import coin  # noqa: F401  (FreeCAD needs pivy loaded first)
    gdoc = Gui.getDocument(doc_name)
    view = gdoc.ActiveView if gdoc is not None else None
    if view is None or not hasattr(view, "getSceneGraph"):
        return None
    return view.getSceneGraph()


def refresh():
    """Called a few times a second while MechFlow is active."""
    if not enabled():
        clear()
        return
    # Forget documents that have been closed.
    open_docs = App.listDocuments()
    for name in list(_markers):
        if name not in open_docs:
            _markers.pop(name, None)

    doc = App.ActiveDocument
    if doc is None:
        return
    entry = _markers.get(doc.Name)
    if entry is None:
        sg = _view_root(doc.Name)
        if sg is None:
            return
        node, scale = _build()
        sg.addChild(node)
        entry = [sg, node, scale, None]
        _markers[doc.Name] = entry
    size = _marker_size(doc)
    if entry[3] is None or abs(size - entry[3]) > 1e-6:
        entry[2].scaleFactor = (size, size, size)
        entry[3] = size


def clear():
    for name, (sg, node, _scale, _size) in list(_markers.items()):
        try:
            sg.removeChild(node)
        except Exception:
            pass
    _markers.clear()


def toggle():
    p = App.ParamGet(PARAMS)
    p.SetBool("ShowOrigin", not p.GetBool("ShowOrigin", True))
    if enabled():
        refresh()
    else:
        clear()
