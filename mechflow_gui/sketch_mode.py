# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keep the user in MechFlow while editing a sketch.

FreeCAD's Sketcher jumps to the Sketcher workbench whenever a sketch is opened
for editing. If that jump comes from MechFlow, switch straight back; the
CommandManager then shows its Sketch tab (see layout._watch_tasks), and
leaving the sketch returns to the Features tab - as in SOLIDWORKS.

Turn off with:
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow").SetBool("StayInMechFlow", False)
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
MECHFLOW = "MechFlowWorkbench"
SKETCHER = "SketcherWorkbench"

PART_DESIGN = "PartDesignWorkbench"
TECHDRAW = "TechDrawWorkbench"
ASSEMBLY = "AssemblyWorkbench"

_previous = None
_installed = False
_session = False   # a sketch was opened from MechFlow and hasn't been closed yet


def editing_sketch():
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return False
    try:
        vp = gdoc.getInEdit()
    except Exception:
        return False
    obj = getattr(vp, "Object", None)
    return obj is not None and obj.TypeId == "Sketcher::SketchObject"


def _on_workbench(name):
    global _previous, _session
    came_from = _previous
    _previous = name
    if not App.ParamGet(PARAMS).GetBool("StayInMechFlow", True):
        return

    # Sketch opened from MechFlow -> FreeCAD jumped to Sketcher: go back.
    if name == SKETCHER and came_from == MECHFLOW:
        QtCore.QTimer.singleShot(0, _back_to_mechflow)
        return

    # Sketch closed -> FreeCAD restored Part Design or Sketcher instead of
    # MechFlow: go back, once, then forget the session.
    if _session and name in (SKETCHER, PART_DESIGN):
        QtCore.QTimer.singleShot(0, _after_sketch_closed)
        return

    # Opening a drawing (or an assembly) from MechFlow jumps to TechDraw (or
    # Assembly): MechFlow's Drawing and Assembly tabs have those tools.
    if name in (TECHDRAW, ASSEMBLY) and came_from == MECHFLOW:
        QtCore.QTimer.singleShot(0, lambda: Gui.activateWorkbench(MECHFLOW))
        return

    # Double-clicking a Part Design feature from MechFlow jumps to Part Design.
    if name == PART_DESIGN and came_from == MECHFLOW:
        QtCore.QTimer.singleShot(0, _after_feature_edit)


def _in_edit_object():
    gdoc = Gui.ActiveDocument
    if gdoc is None:
        return None
    try:
        vp = gdoc.getInEdit()
    except Exception:
        return None
    return getattr(vp, "Object", None)


def _after_feature_edit():
    obj = _in_edit_object()
    if obj is None:
        return  # user picked Part Design themselves: leave them there
    from mechflow_gui import commands
    if obj.TypeId in commands.EDITABLE_TYPES:
        # Swap FreeCAD's Pad/Pocket dialog for MechFlow's.
        try:
            Gui.Control.closeDialog()
        except Exception:
            pass
        try:
            Gui.ActiveDocument.resetEdit()
        except Exception:
            pass
        Gui.activateWorkbench(MECHFLOW)
        QtCore.QTimer.singleShot(0, lambda o=obj: commands.edit_feature(o))
    else:
        # Other features: keep FreeCAD's dialog, but stay in MechFlow.
        Gui.activateWorkbench(MECHFLOW)


def _back_to_mechflow():
    global _session
    if editing_sketch():
        _session = True
        Gui.activateWorkbench(MECHFLOW)


def _after_sketch_closed():
    global _session
    if editing_sketch():
        # Still in the sketch (e.g. Sketcher re-asserted itself): stay in MechFlow.
        Gui.activateWorkbench(MECHFLOW)
        return
    _session = False
    Gui.activateWorkbench(MECHFLOW)


def install():
    global _installed, _previous
    if _installed:
        return
    mw = Gui.getMainWindow()
    sig = getattr(mw, "workbenchActivated", None)
    if sig is None:
        return
    sig.connect(_on_workbench)
    _previous = MECHFLOW
    _installed = True


# ------------------------------------------------------------ discard (X)

_baseline = None   # {"doc", "sketch", "undo", "new"} recorded when a sketch opens


def note_sketch_opened(sketch):
    """Remember the undo position when a sketch opens, so X can roll back."""
    global _baseline
    doc = sketch.Document
    try:
        undo = doc.UndoCount
    except Exception:
        undo = None
    new = (len(sketch.Geometry) == 0 and len(sketch.Constraints) == 0)
    _baseline = {"doc": doc.Name, "sketch": sketch.Name, "undo": undo, "new": new}


def discard_sketch():
    """Leave the sketch and undo everything done since it opened.
    A brand-new empty sketch is removed altogether, as in SOLIDWORKS."""
    global _baseline
    b, _baseline = _baseline, None
    gdoc = Gui.ActiveDocument
    try:
        gdoc.resetEdit()
    except Exception:
        pass
    if not b:
        return
    doc = App.listDocuments().get(b["doc"])
    if doc is None:
        return
    try:
        from mechflow_gui import auto_edges
        auto_edges._session = None     # undo removes those edges too
    except Exception:
        pass
    if b["undo"] is not None:
        guard = 0
        while doc.UndoCount > b["undo"] and guard < 500:
            doc.undo()
            guard += 1
    if b["new"]:
        sk = doc.getObject(b["sketch"])
        if sk is not None and len(sk.Geometry) == 0:
            doc.openTransaction("Discard sketch")
            try:
                doc.removeObject(sk.Name)
            finally:
                doc.commitTransaction()
    doc.recompute()
