# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selecting a feature in the tree doesn't light up the whole part.

In FreeCAD each Part Design feature is the whole solid up to that step, so
selecting one in the tree turns the whole part green. While a feature is
selected from the tree, MechFlow switches the 3D view's selection
highlighting off (the tree row stays selected, so right-click tools still
work). As soon as the mouse goes into the 3D view, highlighting is back on,
so picking faces and edges there works normally.

Uses a selection observer and a light timer - no Qt hooks into FreeCAD.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

VIEW = "User parameter:BaseApp/Preferences/View"
MINE = "User parameter:BaseApp/Preferences/Mod/MechFlow"

active = False
_observer = None
_off = False          # selection highlighting currently switched off by us
_busy = False         # re-selecting, ignore our own selection changes
_timer = None


def restore_after_crash():
    """Earlier MechFlow versions changed a preference; put it back if needed."""
    mine = App.ParamGet(MINE)
    if mine.GetBool("SelectionMuted", False):
        App.ParamGet(VIEW).SetBool("EnableSelection", mine.GetBool("SelectionWas", True))
        mine.SetBool("SelectionMuted", False)


def _selection_node():
    """The 3D view's selection node (SoFCUnifiedSelection)."""
    try:
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        root = view.getViewer().getSoRenderManager().getSceneGraph()
        t = coin.SoType.fromName("SoFCUnifiedSelection")
        if t.isBad():
            return None
        sa = coin.SoSearchAction()
        sa.setType(t)
        sa.setInterest(coin.SoSearchAction.FIRST)
        sa.apply(root)
        path = sa.getPath()
        return path.getTail() if path is not None else None
    except Exception:
        return None


def _set_highlight(on):
    global _off
    node = _selection_node()
    if node is None:
        _off = False
        return False
    try:
        node.getField("selectionMode").set("ON" if on else "OFF")
    except Exception:
        _off = False
        return False
    _off = not on
    return True


def _whole_feature_selected():
    try:
        sel = Gui.Selection.getSelectionEx()
    except Exception:
        return None
    if len(sel) != 1 or sel[0].SubElementNames:
        return None
    o = sel[0].Object
    return o if o.isDerivedFrom("PartDesign::Feature") else None


def _mouse_in_3d_view():
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return False
    pos = mdi.mapFromGlobal(QtGui.QCursor.pos())
    return mdi.rect().contains(pos)


def update():
    global _busy
    if _busy:
        return
    feat = _whole_feature_selected() if active else None
    if feat is None:
        if _off:
            _set_highlight(True)
        return
    if _off:
        return
    if _mouse_in_3d_view():
        return        # selected by clicking in the 3D view: keep FreeCAD's look
    if not _set_highlight(False):
        return
    # Re-select so the existing green highlight is cleared, with highlighting off.
    _busy = True
    try:
        doc = feat.Document.Name
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc, feat.Name)
    except Exception:
        pass
    finally:
        _busy = False
    _ensure_timer()


def _tick():
    """Highlighting back on once the mouse goes into the 3D view."""
    if not _off:
        _timer.stop()
        return
    if _mouse_in_3d_view() or not active:
        _set_highlight(True)
        _timer.stop()


def _ensure_timer():
    global _timer
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.setInterval(120)
        _timer.timeout.connect(_tick)
    _timer.start()


DATUM_TYPES = ("PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
               "App::Plane", "App::Line", "App::Point")


def promote_datums():
    """Clicking a datum plane/axis/point in the view selects a part of it
    called 'Plane' / 'Line' / 'Point' (dark green), which Sketch and the
    feature panels don't accept. Swap it for the whole datum, as SOLIDWORKS
    selects the plane itself."""
    global _busy
    if _busy:
        return
    try:
        from mechflow_gui import sketch_mode
        if sketch_mode.editing_sketch():
            return
    except Exception:
        pass
    try:
        sel = Gui.Selection.getSelectionEx()
    except Exception:
        return
    keep, changed = [], False
    for item in sel:
        obj = item.Object
        subs = list(item.SubElementNames)
        if obj.TypeId == "PartDesign::Body" and not subs:
            # Clicking an already-selected datum makes FreeCAD step up to the
            # whole body: keep the datum under the mouse selected instead.
            d = _datum_under_cursor(obj)
            if d is not None:
                keep.append((d, []))
                changed = True
                continue
        if obj.TypeId in DATUM_TYPES and subs and not any(
                s.split(".")[-1].startswith(("Face", "Edge", "Vertex")) for s in subs):
            subs, changed = [], True
        keep.append((obj, subs))
    if not changed:
        return
    _busy = True
    try:
        Gui.Selection.clearSelection()
        for obj, subs in keep:
            doc = obj.Document.Name
            if subs:
                for sub in subs:
                    Gui.Selection.addSelection(doc, obj.Name, sub)
            else:
                Gui.Selection.addSelection(doc, obj.Name)
    except Exception:
        pass
    finally:
        _busy = False


def _datum_under_cursor(body):
    if not _mouse_in_3d_view():
        return None
    try:
        view = Gui.ActiveDocument.ActiveView
        info = view.getObjectInfo(view.getCursorPos())
        obj = body.Document.getObject(info["Object"]) if isinstance(info, dict) else None
    except Exception:
        return None
    if obj is not None and obj.TypeId in DATUM_TYPES and obj in body.Group:
        return obj
    return None


class _Observer:
    def _later(self, *args):
        if not _busy:
            QtCore.QTimer.singleShot(0, promote_datums)
            QtCore.QTimer.singleShot(0, update)

    addSelection = removeSelection = setSelection = clearSelection = _later


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        Gui.Selection.addObserver(_observer)


def start():
    global active
    active = True


def stop():
    global active
    active = False
    if _off:
        _set_highlight(True)
