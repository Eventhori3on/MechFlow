# SPDX-License-Identifier: LGPL-2.1-or-later
"""(Disabled for now - FreeCAD 1.1 hides planes via their Origin folder.)

Show hidden planes while hovering over them in the tree, like SOLIDWORKS.

Hovering a plane in the model tree shows it in the 3D view; moving away hides
it again. If you click it, it stays shown while it is selected.

Implementation note: hooking FreeCAD's tree widget from Python (signals or
event filters) crashes Qt on some builds, so this simply polls what is under
the mouse a few times a second while MechFlow is active. No hooks, no crash.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
PLANE_TYPES = ("App::Plane", "PartDesign::Plane")
POLL_MS = 120

active = False      # set by the workbench's Activated / Deactivated
_hovered = None     # plane currently under the mouse in the tree
_temp = []          # planes we made visible
_timer = None
_last_widget = ""   # diagnostics
_last_label = ""


_log_lines = 0
_last_logged = None


DEBUG_LOG = False


def _log(msg):
    """Diagnostics: append to <FreeCAD user dir>/mechflow_debug.log when DEBUG_LOG."""
    global _log_lines
    if not DEBUG_LOG:
        return
    if _log_lines > 400:
        return
    try:
        import os, time
        path = os.path.join(App.getUserAppDataDir(), "mechflow_debug.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + msg + "\n")
        _log_lines += 1
    except Exception:
        pass


def _enabled():
    return active and App.ParamGet(PARAMS).GetBool("HoverShowPlanes", True)


def _tree_item_under_mouse():
    global _last_widget
    pos = QtGui.QCursor.pos()
    w = QtWidgets.QApplication.widgetAt(pos)
    if w is None:
        return None
    tree = w.parentWidget()
    _last_widget = f"{type(w).__name__} in {type(tree).__name__}"
    if not isinstance(tree, QtWidgets.QTreeWidget) or tree.viewport() is not w:
        return None
    return tree.itemAt(w.mapFromGlobal(pos))


def _plane_for_label(label):
    doc = App.ActiveDocument
    if doc is None or not label:
        return None
    try:
        found = doc.getObjectsByLabel(label)
    except Exception:
        found = [o for o in doc.Objects if o.Label == label]
    for o in found:
        if o.TypeId in PLANE_TYPES:
            return o
    return None


def _alive(o):
    try:
        return o.Document is not None and o.ViewObject is not None
    except Exception:
        return False


def _selected(o):
    try:
        return any(s is o for s in Gui.Selection.getSelection())
    except Exception:
        return False


def _tick():
    global _hovered
    if not _enabled():
        return
    global _last_logged
    try:
        item = _tree_item_under_mouse()
        label = item.text(0) if item is not None else None
    except Exception as e:
        label = None
        _log(f"error reading tree: {e!r}")
    global _last_label
    if label:
        _last_label = label
    plane = _plane_for_label(label)
    _hovered = plane
    state = (_last_widget, label, getattr(plane, "Name", None))
    if state != _last_logged:
        _last_logged = state
        vis = None
        try:
            vis = plane.ViewObject.Visibility if plane is not None else None
        except Exception as e:
            vis = repr(e)
        _log(f"widget={_last_widget} | label={label!r} | plane={state[2]} "
             f"type={getattr(plane, 'TypeId', None)} visible_before={vis} "
             f"doc={getattr(App.ActiveDocument, 'Name', None)}")

    if plane is not None and _alive(plane):
        try:
            if not plane.ViewObject.Visibility:
                plane.ViewObject.Visibility = True
                _log(f"showed {plane.Name}: now visible={plane.ViewObject.Visibility}")
                if plane not in _temp:
                    _temp.append(plane)
        except Exception as e:
            _log(f"error showing plane: {e!r}")

    for o in list(_temp):
        if not _alive(o):
            _temp.remove(o)
            continue
        if o is _hovered or _selected(o):
            continue
        try:
            o.ViewObject.Visibility = False
        except Exception:
            pass
        _temp.remove(o)


def start():
    global active, _timer
    active = True
    _log("hover started")
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.setInterval(POLL_MS)
        _timer.timeout.connect(_tick)
    _timer.start()


def stop():
    global active, _hovered
    active = False
    if _timer is not None:
        _timer.stop()
    _hovered = None
    for o in list(_temp):
        try:
            if not _selected(o):
                o.ViewObject.Visibility = False
        except Exception:
            pass
        _temp.remove(o)


def install():
    """Kept for compatibility; polling starts when the workbench activates."""


def refresh():
    """Kept for compatibility."""


def status():
    """Diagnostics: paste  from mechflow_gui import hover; hover.status()  in the console."""
    App.Console.PrintMessage(
        f"MechFlow hover: active={active}, "
        f"setting={App.ParamGet(PARAMS).GetBool('HoverShowPlanes', True)}, "
        f"polling={bool(_timer and _timer.isActive())}, "
        f"hovered={getattr(_hovered, 'Label', None)}, "
        f"under mouse={_last_widget}, last tree label={_last_label!r}\n")


def status_later(seconds=3):
    """Run status() after a delay so the mouse can be over the tree."""
    QtCore.QTimer.singleShot(int(seconds * 1000), status)
