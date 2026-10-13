# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style S-key shortcut bar.

Press S over the 3D view (or anywhere in MechFlow) and a small grid of the
commands you need right now pops up at the mouse: sketch tools while you're
in a sketch, feature tools otherwise. Click one, or press Esc to close.

Uses a QShortcut on the main window - no event filters on FreeCAD widgets.
The key can be changed: Preferences/Mod/MechFlow  ShortcutBarKey (default "S").
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"

SKETCH_TOOLS = [
    ("Line", "Sketcher_CreatePolyline"), ("Rectangle", "Sketcher_CreateRectangle"),
    ("Circle", "Sketcher_CreateCircle"), ("Arc", "Sketcher_CreateArc"),
    ("Slot", "Sketcher_CreateSlot"), ("Smart Dimension", "Sketcher_Dimension"),
    ("Trim", "Sketcher_Trimming"), ("Convert Entities", "Sketcher_External"),
    ("Construction", "Sketcher_ToggleConstruction"), ("Normal To", "MechFlow_NormalTo"),
    ("Exit Sketch", "Sketcher_LeaveSketch"),
]
PART_TOOLS = [
    ("Sketch", "MechFlow_Sketch"), ("Extruded Boss", "MechFlow_BossExtrude"),
    ("Extruded Cut", "MechFlow_CutExtrude"), ("Revolve", "MechFlow_Revolve"),
    ("Hole Wizard", "MechFlow_HoleWizard"), ("Fillet", "MechFlow_Fillet"),
    ("Chamfer", "MechFlow_Chamfer"), ("Shell", "MechFlow_Shell"),
    ("Linear Pattern", "MechFlow_LinearPattern"), ("Mirror", "MechFlow_Mirror"),
    ("Plane", "MechFlow_Plane"), ("Measure", "Std_Measure"),
    ("Zoom to Fit", "Std_ViewFitAll"), ("Normal To", "MechFlow_NormalTo"),
]

_shortcut = None
_popup = None


def _editing_sketch():
    try:
        from mechflow_gui import sketch_mode
        return sketch_mode.editing_sketch()
    except Exception:
        return False


def _resolve(name, available):
    from mechflow_gui import command_manager
    return command_manager._resolve(name, available)


def _build(tools):
    from mechflow_gui import command_manager
    available = set(Gui.listCommands())
    w = QtWidgets.QFrame(Gui.getMainWindow(), QtCore.Qt.Popup)
    w.setObjectName("MechFlow_SBar")
    w.setStyleSheet(
        "#MechFlow_SBar { background: palette(window); border: 1px solid palette(mid);"
        " border-radius: 6px; }")
    grid = QtWidgets.QGridLayout(w)
    grid.setContentsMargins(4, 4, 4, 4)
    grid.setSpacing(2)
    n = 0
    for label, wanted in tools:
        name = _resolve(wanted, available)
        if not name:
            continue
        b = command_manager._make_button(label, name)
        if b is None:
            continue
        b.setIconSize(QtCore.QSize(22, 22))
        b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        b.setToolTip(label)
        b.clicked.connect(w.close)
        grid.addWidget(b, n // 5, n % 5)
        n += 1
    return w if n else None


def show():
    global _popup
    if _popup is not None:
        try:
            _popup.close()
        except RuntimeError:
            pass
    _popup = _build(SKETCH_TOOLS if _editing_sketch() else PART_TOOLS)
    if _popup is None:
        return
    _popup.adjustSize()
    pos = QtGui.QCursor.pos() - QtCore.QPoint(_popup.width() // 2, _popup.height() // 2)
    _popup.move(pos)
    _popup.show()


def install():
    global _shortcut
    if _shortcut is not None:
        return
    key = App.ParamGet(PARAMS).GetString("ShortcutBarKey", "S")
    if not key:
        return
    _shortcut = QtGui.QShortcut(QtGui.QKeySequence(key), Gui.getMainWindow()) \
        if hasattr(QtGui, "QShortcut") else \
        QtWidgets.QShortcut(QtGui.QKeySequence(key), Gui.getMainWindow())
    # Window shortcut: text boxes (console, number fields) still get a typed "s".
    _shortcut.setContext(QtCore.Qt.WindowShortcut)
    _shortcut.activated.connect(show)
    _shortcut.activatedAmbiguously.connect(show)
    _shortcut.setEnabled(False)


def set_enabled(on):
    """Only active while MechFlow is the current workbench."""
    if _shortcut is not None:
        _shortcut.setEnabled(on)
