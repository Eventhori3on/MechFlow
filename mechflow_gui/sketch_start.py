# SPDX-License-Identifier: LGPL-2.1-or-later
"""Start a sketch the SOLIDWORKS way: no attachment dialog.

With a plane or flat face already selected, the sketch starts on it at once.
Otherwise the three origin planes are shown, a short prompt appears over the
3D view, and the sketch starts as soon as a plane (in the view or the tree) or
a flat face is selected. Esc / Cancel puts everything back.

Polls the selection with a QTimer - no Qt hooks into FreeCAD widgets.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

_timer = None
_prompt = None
_body = None


def _mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


# Temporary display planes: FreeCAD 1.1 doesn't draw its origin planes, so
# MechFlow draws its own while you pick, then removes them.
# (temp object name, origin plane name, rotation axis, angle)
TEMP_PLANES = [
    ("MechFlow_PickFront", "XZ_Plane", (1, 0, 0), 90),
    ("MechFlow_PickTop", "XY_Plane", (0, 0, 1), 0),
    ("MechFlow_PickRight", "YZ_Plane", (0, 1, 0), 90),
]
# Each plane coloured by the axis it faces: Top (Z) blue, Front (Y) green,
# Right (X) red.  Hover keeps the colour, just brighter and more solid.
# SOLIDWORKS look: faint blue planes with blue outlines and names; the one
# under the mouse (in the view or the tree) turns orange.
PLANE_COLOURS = {
    "MechFlow_PickTop": (0.55, 0.72, 0.95),
    "MechFlow_PickFront": (0.55, 0.72, 0.95),
    "MechFlow_PickRight": (0.55, 0.72, 0.95),
}
HOVER_COLOUR = (1.0, 0.55, 0.15)
PLANE_TRANSPARENCY = 88
HOVER_TRANSPARENCY = 55
_art = []      # (scene graph, node) outlines + labels for the pick planes


def _brighter(rgb, amount=0.35):
    return HOVER_COLOUR
_temp_names = []


def _plane_size(doc):
    """Big enough to frame the part, like SOLIDWORKS' default planes."""
    import FreeCAD as App
    box = None
    for o in doc.Objects:
        shape = getattr(o, "Shape", None)
        if shape is None or o.Name.startswith("MechFlow_Pick"):
            continue
        try:
            if shape.isNull() or not shape.Solids:
                continue
            bb = shape.BoundBox
            box = bb if box is None else box.united(bb)
        except Exception:
            pass
    if box is None or box.DiagonalLength < 1e-6:
        return 100.0
    return max(20.0, box.DiagonalLength * 1.2)


def _make_temp_planes(doc):
    import Part
    size = _plane_size(doc)
    half = size / 2.0
    for name, _origin, axis, angle in TEMP_PLANES:
        face = Part.makePlane(size, size, App.Vector(-half, -half, 0))
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = face
        obj.Placement = App.Placement(App.Vector(0, 0, 0),
                                      App.Rotation(App.Vector(*axis), angle))
        label = {"MechFlow_PickFront": "Front Plane", "MechFlow_PickTop": "Top Plane",
                 "MechFlow_PickRight": "Right Plane"}[name]
        obj.Label = f"{label} (pick)"
        vo = obj.ViewObject
        colour = PLANE_COLOURS[name]
        for prop, value in (("ShapeColor", colour), ("LineColor", colour),
                            ("Transparency", PLANE_TRANSPARENCY), ("ShowInTree", False),
                            # Faces only: no outline edges to hover or click.
                            ("DisplayMode", "Shaded")):
            try:
                setattr(vo, prop, value)
            except Exception:
                pass
        _temp_names.append((doc.Name, name))
        try:
            from mechflow_gui import plane_art
            sg = plane_art.scene()
            if sg is not None:
                node = plane_art.build(obj.Placement.Rotation, obj.Placement.Base,
                                       size, label, fill_transparency=1.0)
                sg.addChild(node)
                _art.append((sg, node))
        except Exception:
            pass
    doc.recompute()


def _remove_temp_planes():
    while _art:
        sg, node = _art.pop()
        try:
            sg.removeChild(node)
        except Exception:
            pass
    while _temp_names:
        doc_name, name = _temp_names.pop()
        doc = App.listDocuments().get(doc_name)
        if doc is not None and doc.getObject(name) is not None:
            try:
                doc.removeObject(name)
            except Exception:
                pass


def _origin_plane(origin_name):
    origin = getattr(_body, "Origin", None) if _body is not None else None
    for f in getattr(origin, "OriginFeatures", []) if origin else []:
        if f.Name.startswith(origin_name) or getattr(f, "Role", "") == origin_name:
            return f
    return None


def _picked_temp_plane():
    """The origin plane matching a clicked temporary plane, if any."""
    for item in Gui.Selection.getSelectionEx():
        for name, origin_name, _a, _g in TEMP_PLANES:
            if item.Object.Name != name:
                continue
            subs = item.SubElementNames
            if subs and not any(x.startswith("Face") for x in subs):
                # An edge or corner was clicked: ignore it.
                Gui.Selection.clearSelection()
                return None
            return _origin_plane(origin_name)
    return None


# ------------------------------------------------------------ hover feedback

PLANE_LABELS = {"MechFlow_PickFront": "Front Plane", "MechFlow_PickTop": "Top Plane",
                "MechFlow_PickRight": "Right Plane"}
_callout = None
_hover_name = None
_tree_marks = []     # (tree item, original background brush)


def _hovered_temp_plane():
    """Name of the temporary plane under the cursor in the 3D view, if any.
    Asks the view what is under the cursor right now (FreeCAD's own hover
    highlight can linger after the mouse moves away)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        info = view.getObjectInfo(view.getCursorPos())
    except Exception:
        return None
    name = info.get("Object") if isinstance(info, dict) else None
    return name if name in PLANE_LABELS else None


def _tree_hovered_temp_plane():
    """Temporary plane matching the real plane under the mouse in the tree."""
    try:
        pos = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(pos)
        tree = w.parentWidget() if w is not None else None
        if not isinstance(tree, QtWidgets.QTreeWidget) or tree.viewport() is not w:
            return None
        item = tree.itemAt(w.mapFromGlobal(pos))
        label = item.text(0) if item is not None else None
    except Exception:
        return None
    if not label:
        return None
    for name, origin_name, _a, _g in TEMP_PLANES:
        real = _origin_plane(origin_name)
        if real is not None and real.Label == label:
            return name
    return None


_lit = None          # temp plane currently lit from a tree hover
_lit_saved = None


def _light_temp_plane(name):
    """Make a temporary plane stand out (blue, more solid) - or restore it."""
    global _lit, _lit_saved
    if name == _lit:
        return
    doc = App.ActiveDocument
    if _lit is not None and _lit_saved is not None and doc is not None:
        o = doc.getObject(_lit)
        if o is not None:
            for prop, value in _lit_saved.items():
                try:
                    setattr(o.ViewObject, prop, value)
                except Exception:
                    pass
    _lit, _lit_saved = None, None
    if name is None or doc is None:
        return
    o = doc.getObject(name)
    if o is None:
        return
    vo = o.ViewObject
    saved = {}
    lit = _brighter(PLANE_COLOURS.get(name, (0.5, 0.5, 0.5)))
    for prop, value in (("ShapeColor", lit), ("LineColor", lit),
                        ("Transparency", HOVER_TRANSPARENCY)):
        try:
            saved[prop] = getattr(vo, prop)
            setattr(vo, prop, value)
        except Exception:
            pass
    _lit, _lit_saved = name, saved


def _unmark_tree():
    # Labels only: tree items can be deleted by FreeCAD at any time, and
    # touching a deleted one crashes. Look them up again to clear the mark.
    flags = QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
    labels = list(_tree_marks)
    _tree_marks.clear()
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        for label in labels:
            try:
                for item in tree.findItems(label, flags, 0):
                    item.setData(0, QtCore.Qt.BackgroundRole, None)
            except Exception:
                pass


def _mark_tree(label):
    """Highlight the real plane's row in the model tree."""
    colour = QtGui.QBrush(QtGui.QColor(61, 142, 224, 120))
    flags = QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
    _tree_marks.append(label)
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        try:
            for item in tree.findItems(label, flags, 0):
                item.setBackground(0, colour)
                tree.scrollToItem(item)
        except Exception:
            pass


def _show_callout(text):
    global _callout
    mdi = _mdi()
    if mdi is None:
        return
    if _callout is None:
        _callout = QtWidgets.QLabel(mdi)
        _callout.setObjectName("MechFlow_Callout")
        _callout.setStyleSheet(
            "#MechFlow_Callout { background: rgba(255, 250, 225, 235); color: #222;"
            " border: 1px solid #b08a3c; border-radius: 4px; padding: 3px 8px;"
            " font-size: 12px; font-weight: 600; }")
    _callout.setText(text)
    _callout.adjustSize()
    pos = mdi.mapFromGlobal(QtGui.QCursor.pos())
    _callout.move(pos.x() + 16, pos.y() + 14)
    _callout.show()
    _callout.raise_()


def _hide_callout():
    if _callout is not None:
        _callout.hide()


def _tree_hovered_feature():
    """A solid feature (e.g. Cut-Extrude1) under the mouse in the tree."""
    try:
        pos = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(pos)
        tree = w.parentWidget() if w is not None else None
        if not isinstance(tree, QtWidgets.QTreeWidget) or tree.viewport() is not w:
            return None
        item = tree.itemAt(w.mapFromGlobal(pos))
        label = item.text(0) if item is not None else None
    except Exception:
        return None
    if not label or _body is None:
        return None
    for o in _body.Group:
        if o.Label == label and o.isDerivedFrom("PartDesign::Feature"):
            return o
    return None


def _update_hover():
    """Keep tree and 3D view in step while picking:
    plane or face under the mouse -> highlight it + its tree item;
    plane or feature under the mouse in the tree -> light it up in the view."""
    global _hover_name
    from mechflow_gui import pick_solid

    plane = _hovered_temp_plane()
    face = None if plane else pick_solid.face_under_cursor()

    # What to highlight in the tree.
    if plane:
        key, label = ("plane", plane), PLANE_LABELS[plane]
    elif face:
        creator = pick_solid.creator_of(face[0], face[1])
        key = ("face", face[0].Name, face[1])
        label = creator.Label if creator is not None else None
    else:
        key, label = None, None
    if key != _hover_name:
        _hover_name = key
        _unmark_tree()
        if label:
            _mark_tree(label)

    # Planes: light up from either side, in their own colour.
    _light_temp_plane(plane or _tree_hovered_temp_plane())

    # Solid faces: light up the face under the mouse, or a hovered feature's faces.
    if face:
        pick_solid.show(("face", face[0].Name, face[1]), face[0], [face[1]])
        return
    feat = None if plane else _tree_hovered_feature()
    if feat is not None and _body is not None:
        pick_solid.show(("feature", feat.Name), _body,
                        pick_solid.faces_of_feature(_body, feat))
    else:
        pick_solid.clear()


def _sketch_on_feature(feature):
    """Start a sketch on a feature's best flat face. True if it worked."""
    from mechflow_gui import pick_solid
    body = pick_solid.body_of(feature) or _body
    if body is None:
        return False
    idx = pick_solid.best_face(body, feature)
    if idx is None:
        App.Console.PrintMessage(
            f"MechFlow: {feature.Label} has no flat face to sketch on - "
            "click a flat face in the 3D view instead.\n")
        return False
    pick_solid.select_face(body, idx)
    Gui.runCommand("PartDesign_NewSketch", 0)
    return True


def _selected_feature():
    sel = Gui.Selection.getSelectionEx()
    if len(sel) == 1 and not sel[0].SubElementNames:
        o = sel[0].Object
        if o.isDerivedFrom("PartDesign::Feature") and getattr(o, "Shape", None) is not None:
            try:
                if o.Shape.Solids:
                    return o
            except Exception:
                pass
    return None


def _clear_hover():
    global _hover_name, _lit, _lit_saved
    try:
        from mechflow_gui import pick_solid
        pick_solid.reset()
    except Exception:
        pass
    _hover_name = None
    _unmark_tree()
    _hide_callout()
    _lit, _lit_saved = None, None   # the temp planes are about to be removed


def _build_prompt(parent):
    """Small red cancel X where SOLIDWORKS' confirmation corner sits."""
    w = QtWidgets.QToolButton(parent)
    w.setObjectName("MechFlow_PickCancel")
    w.setText("\u2715")
    w.setToolTip("Cancel sketch (or click Sketch again)")
    w.setStyleSheet(
        "#MechFlow_PickCancel { font-size: 15px; font-weight: 700; color: #e05050;"
        " min-width: 28px; min-height: 28px; max-width: 28px; max-height: 28px;"
        " padding: 0px; border-radius: 5px;"
        " background: rgba(255, 255, 255, 215); border: 1px solid rgba(120,120,120,120); }"
        "#MechFlow_PickCancel:hover { background: rgba(224, 80, 80, 90); }")
    w.clicked.connect(cancel_pick)
    w.adjustSize()
    return w


def _place_prompt():
    if _prompt is None:
        return
    parent = _prompt.parentWidget()
    if parent is None:
        return
    _prompt.adjustSize()
    # Same spot as the green exit-sketch tick: just left of the view cube.
    _prompt.move(max(0, parent.width() - _prompt.width() - 190), 12)
    _prompt.raise_()


VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
_preselect_saved = None


def _quiet_preselection(on):
    """While picking, FreeCAD's yellow hover highlight would paint over the
    plane colours: switch it off, and put the user's setting back after."""
    global _preselect_saved
    p = App.ParamGet(VIEW_PARAMS)
    mine = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
    if on and _preselect_saved is None:
        _preselect_saved = p.GetBool("EnablePreselection", True)
        # Remember it on disk too, in case FreeCAD closes mid-pick.
        mine.SetBool("PreselectionMuted", True)
        mine.SetBool("PreselectionWas", _preselect_saved)
        p.SetBool("EnablePreselection", False)
    elif not on and _preselect_saved is not None:
        p.SetBool("EnablePreselection", _preselect_saved)
        mine.SetBool("PreselectionMuted", False)
        _preselect_saved = None


def restore_after_crash():
    """Called at start-up: undo a hover-highlight mute left by a closed session."""
    mine = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
    if mine.GetBool("PreselectionMuted", False):
        App.ParamGet(VIEW_PARAMS).SetBool(
            "EnablePreselection", mine.GetBool("PreselectionWas", True))
        mine.SetBool("PreselectionMuted", False)


def _finish():
    global _prompt
    if _timer is not None:
        _timer.stop()
    _clear_hover()
    if _prompt is not None:
        _prompt.hide()
    _remove_temp_planes()
    _quiet_preselection(False)


def cancel_pick(*_):
    _finish()


def _poll():
    from mechflow_gui import commands
    # Esc in FreeCAD clears the selection; a closed document ends picking.
    if App.ActiveDocument is None:
        _finish()
        return
    _place_prompt()
    try:
        _update_hover()
    except Exception:
        pass

    # Clicked one of the temporary planes -> sketch on the matching real plane.
    picked = _picked_temp_plane()
    if picked is not None:
        Gui.Selection.clearSelection()
        _finish()
        Gui.Selection.addSelection(picked)
        Gui.runCommand("PartDesign_NewSketch", 0)
        return

    # Clicked a feature (e.g. Cut-Extrude1) in the tree -> its best flat face.
    feat = _selected_feature()
    if feat is not None:
        _finish()
        if not _sketch_on_feature(feat):
            Gui.Selection.clearSelection()
        return

    # Clicked a real plane (e.g. in the tree) or a flat face on the part.
    if commands.selection_is_sketchable():
        keep = [(i.Object, list(i.SubElementNames)) for i in Gui.Selection.getSelectionEx()]
        _finish()
        Gui.Selection.clearSelection()
        for obj, subs in keep:
            try:
                if subs:
                    for sub in subs:
                        Gui.Selection.addSelection(obj, sub)
                else:
                    Gui.Selection.addSelection(obj)
            except Exception:
                pass
        Gui.runCommand("PartDesign_NewSketch", 0)


def picking():
    return _timer is not None and _timer.isActive()


def start(body):
    """Begin a sketch on the current selection, or ask for one."""
    global _timer, _prompt, _body
    from mechflow_gui import commands
    if picking():
        cancel_pick()
        return
    if commands.selection_is_sketchable():
        Gui.runCommand("PartDesign_NewSketch", 0)
        return
    _body = body
    feat = _selected_feature()
    if feat is not None and _sketch_on_feature(feat):
        return

    _finish()  # in case a previous pick was still waiting
    _body = body
    Gui.Selection.clearSelection()
    _quiet_preselection(True)
    try:
        _make_temp_planes(body.Document)
    except Exception as e:
        App.Console.PrintWarning(f"MechFlow: drawing pick planes failed: {e}\n")
    mdi = _mdi()
    if mdi is not None:
        if _prompt is None:
            _prompt = _build_prompt(mdi)
        _prompt.show()
        _place_prompt()
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.setInterval(80)
        _timer.timeout.connect(_poll)
    _timer.start()
