# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS sketch colours and the Under / Fully / Over Defined status.

Colours (while MechFlow is active; your own colours come back when you leave
MechFlow): under-defined geometry blue, fully defined black, over-defined
red, dimensions black. FreeCAD reads these when a sketch opens.

Status: the bottom status bar shows "Editing Sketch1  |  Under Defined" as in
SOLIDWORKS, coloured to match, while a sketch is open.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

VIEW = "User parameter:BaseApp/Preferences/View"
PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"

# RGBA, as FreeCAD stores them.
SW_COLOURS = {
    "EditedEdgeColor": 0x0000FFFF,               # under-defined lines: blue
    "SketchVertexColor": 0x0000FFFF,             # under-defined points: blue
    "FullyConstrainedColor": 0x000000FF,         # fully defined sketch: black
    "FullyConstraintElementColor": 0x000000FF,   # fully defined lines: black
    "InvalidSketchColor": 0xFF0000FF,            # over-defined / broken: red
    "ConstrainedDimColor": 0x202020FF,           # dimensions: black
}

UNDER, FULL, OVER = "Under Defined", "Fully Defined", "Over Defined"
STATUS_COLOUR = {UNDER: "#0000ff", FULL: "#000000", OVER: "#d00000"}

_label = None
_timer = None
_last = None


# ------------------------------------------------------------ colours

def _set_colours(on):
    view, mine = App.ParamGet(VIEW), App.ParamGet(PARAMS)
    if on:
        if not mine.GetBool("SketchColoursSaved", False):
            for k, v in SW_COLOURS.items():
                mine.SetUnsigned("SavedSketch_" + k, view.GetUnsigned(k, v))
            mine.SetBool("SketchColoursSaved", True)
        for k, v in SW_COLOURS.items():
            view.SetUnsigned(k, v)
    elif mine.GetBool("SketchColoursSaved", False):
        for k, v in SW_COLOURS.items():
            view.SetUnsigned(k, mine.GetUnsigned("SavedSketch_" + k, v))
        mine.SetBool("SketchColoursSaved", False)


def restore_after_crash():
    """FreeCAD closed while MechFlow's sketch colours were on: put yours back."""
    try:
        _set_colours(False)
    except Exception:
        pass


# ------------------------------------------------------------ status

def sketch_in_edit():
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return None
    try:
        obj = getattr(gdoc.getInEdit(), "Object", None)
    except Exception:
        return None
    return obj if obj is not None and obj.TypeId == "Sketcher::SketchObject" else None


def state_of(sk):
    """(status, degrees of freedom) of a sketch, as SOLIDWORKS reports it."""
    try:
        if sk.ConflictingConstraints or sk.RedundantConstraints or \
                getattr(sk, "MalformedConstraints", []):
            return OVER, sk.DoF
        if sk.FullyConstrained or sk.DoF == 0:
            return FULL, 0
        return UNDER, sk.DoF
    except Exception:
        return None, None


def _ensure_label():
    global _label
    if _label is not None:
        try:
            _label.isVisible()
            return _label
        except RuntimeError:
            _label = None
    bar = Gui.getMainWindow().statusBar()
    _label = QtWidgets.QLabel()
    _label.setObjectName("MechFlow_SketchStatus")
    bar.addPermanentWidget(_label)
    _label.hide()
    return _label


def _tick():
    global _last
    sk = sketch_in_edit()
    if sk is None:
        if _last is not None and _label is not None:
            _label.hide()
        _last = None
        return
    status, dof = state_of(sk)
    key = (sk.Name, sk.Label, status, dof)
    if key == _last:
        return
    _last = key
    lab = _ensure_label()
    extra = f"  ({dof} DOF)" if status == UNDER and dof else ""
    lab.setText(f"Editing {sk.Label}   |   <b style='color:{STATUS_COLOUR.get(status, '#000')}'>"
                f"{status or ''}</b>{extra}")
    lab.show()


def start():
    global _timer
    try:
        _set_colours(True)
    except Exception as e:
        App.Console.PrintWarning(f"MechFlow: sketch colours not set ({e})\n")
    if _timer is None:
        _timer = QtCore.QTimer()
        _timer.setInterval(250)
        _timer.timeout.connect(lambda: _safe(_tick))
    _timer.start()


def stop():
    global _last
    if _timer is not None:
        _timer.stop()
    if _label is not None:
        try:
            _label.hide()
        except RuntimeError:
            pass
    _last = None
    try:
        _set_colours(False)
    except Exception:
        pass


def _safe(fn):
    try:
        fn()
    except Exception:
        pass
