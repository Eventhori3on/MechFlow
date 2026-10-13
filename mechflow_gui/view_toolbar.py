# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style chrome for MechFlow.

- Quick-access buttons (New, Open, Save, Undo, Redo, Rebuild, workbench picker)
  in the right-hand corner of the menu bar.
- A heads-up view toolbar floating at the top-centre of the 3D view.
- Optionally hides every FreeCAD toolbar while MechFlow is active.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
KEEP_TOOLBARS = {"MechFlow_CommandManager"}

QUICK_ACCESS = ["MechFlow_NewPart", "Std_Open", "Std_Save", None,
                "Std_Undo", "Std_Redo", None, "Std_Refresh"]

ORIENTATION = [
    ("Front", "Std_ViewFront"), ("Back", "Std_ViewRear"),
    ("Left", "Std_ViewLeft"), ("Right", "Std_ViewRight"),
    ("Top", "Std_ViewTop"), ("Bottom", "Std_ViewBottom"),
    None,
    ("Isometric", "Std_ViewIsometric"),
    ("Normal To", "MechFlow_NormalTo"),
]

# Std_DrawStyle is a group command; each style is an index into it.
DISPLAY_STYLE = [
    ("Shaded With Edges", ("Std_DrawStyle", 6)),
    ("Shaded", ("Std_DrawStyle", 5)),
    ("Hidden Lines Removed", ("Std_DrawStyle", 3)),
    ("Wireframe", ("Std_DrawStyle", 2)),
    ("No Shading", ("Std_DrawStyle", 4)),
    ("As Is", ("Std_DrawStyle", 0)),
]

HEADS_UP = [
    ("Zoom to Fit", "Std_ViewFitAll"),
    ("Zoom to Selection", "Std_ViewFitSelection"),
    ("Zoom to Area", "Std_ViewBoxZoom"),
    None,
    ("View Orientation", ORIENTATION),
    ("Normal To (Ctrl+8)", "MechFlow_NormalTo"),
    ("Display Style", DISPLAY_STYLE),
    None,
    ("Section View", "MechFlow_SectionView"),
    ("Hide/Show", "Std_ToggleVisibility"),
]

_quick = None
_overlay = None
_prev_corner = None
_hidden = []


def _params():
    return App.ParamGet(PARAMS)


def _available():
    return set(Gui.listCommands())


def _action(name):
    cmd = Gui.Command.get(name)
    if cmd is None:
        return None
    acts = cmd.getAction()
    return acts[0] if acts else None


def _icon(name):
    act = _action(name)
    if act is not None and not act.icon().isNull():
        return act.icon()
    from mechflow_gui import command_manager
    cmd = Gui.Command.get(name)
    info = cmd.getInfo() if cmd and hasattr(cmd, "getInfo") else {}
    return command_manager._icon_for(info.get("pixmap", ""))


def _run(target):
    name, idx = target if isinstance(target, tuple) else (target, 0)
    return lambda checked=False, n=name, i=idx: Gui.runCommand(n, i)


def _target_icon(target):
    """Icon for a plain command, or for item `idx` of a group command."""
    if not isinstance(target, tuple):
        return _icon(target)
    name, idx = target
    cmd = Gui.Command.get(name)
    acts = cmd.getAction() if cmd else []
    # Group commands return the group action first, then one per item.
    for cand in (idx + 1, idx):
        if 0 <= cand < len(acts) and not acts[cand].icon().isNull():
            return acts[cand].icon()
    return _icon(name)


def _first_available(names, available):
    for n in names:
        if n in available:
            return n
    return None


def _tool_button(label, name, size):
    b = QtWidgets.QToolButton()
    b.setAutoRaise(True)
    b.setIconSize(QtCore.QSize(size, size))
    icon = _icon(name)
    if icon.isNull():
        b.setText(label)
    else:
        b.setIcon(icon)
    b.setToolTip(label)
    b.clicked.connect(_run(name))
    return b


def _dropdown(label, entries, size, available):
    b = QtWidgets.QToolButton()
    b.setAutoRaise(True)
    b.setIconSize(QtCore.QSize(size, size))
    b.setToolTip(label)
    b.setPopupMode(QtWidgets.QToolButton.InstantPopup)
    menu = QtWidgets.QMenu(b)
    first = None
    for e in entries:
        if e is None:
            menu.addSeparator()
            continue
        text, target = e
        name = target[0] if isinstance(target, tuple) else target
        if name not in available:
            continue
        act = menu.addAction(_target_icon(target), text)
        act.triggered.connect(_run(target))
        first = first or target
    if first is None:
        return None
    b.setIcon(_target_icon(first))
    b.setMenu(menu)
    return b


# ------------------------------------------------------------ quick access

def _build_quick():
    available = _available()
    w = QtWidgets.QWidget()
    row = QtWidgets.QHBoxLayout(w)
    row.setContentsMargins(0, 0, 6, 0)
    row.setSpacing(1)
    for name in QUICK_ACCESS:
        if name is None:
            row.addSpacing(8)
            continue
        if name in available:
            cmd = Gui.Command.get(name)
            info = cmd.getInfo() if hasattr(cmd, "getInfo") else {}
            label = (info.get("menuText") or name).replace("&", "")
            row.addWidget(_tool_button(label, name, 18))

    row.addSpacing(10)
    wb = QtWidgets.QComboBox()
    wb.setToolTip("Switch workbench")
    items = []
    for key in Gui.listWorkbenches():
        try:
            items.append((Gui.getWorkbench(key).MenuText, key))
        except Exception:
            pass
    for text, key in sorted(items):
        wb.addItem(text, key)
    i = wb.findData("MechFlowWorkbench")
    if i >= 0:
        wb.setCurrentIndex(i)
    wb.activated.connect(
        lambda idx: Gui.activateWorkbench(wb.itemData(idx)))
    row.addWidget(wb)
    w.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)
    w.adjustSize()
    w.setMinimumWidth(w.sizeHint().width())
    return w


# ------------------------------------------------------------ heads-up bar

_last_size = None
_poll = None


# FreeCAD's overlay buttons that pop up at the right edge of the 3D view.
OVERLAY_BUTTONS = ("toggle right", "toggle overlay", "toggle transparent",
                   "auto show task view", "transparent mode", "auto hide")


def _hide_overlay_buttons():
    for b in Gui.getMainWindow().findChildren(QtWidgets.QToolButton):
        if not b.isVisible():
            continue
        name = " ".join(t for t in (b.toolTip(), b.text(), b.objectName()) if t).lower()
        try:
            act = b.defaultAction()
            if act is not None:
                name += " " + (act.toolTip() or "").lower() + " " + (act.text() or "").lower()
        except Exception:
            pass
        if any(k in name for k in OVERLAY_BUTTONS):
            b.hide()


_btn_timer = None


def _start_button_hider():
    global _btn_timer
    if _btn_timer is None:
        _btn_timer = QtCore.QTimer()
        _btn_timer.setInterval(100)
        _btn_timer.timeout.connect(lambda: _safe(_hide_overlay_buttons))
    _btn_timer.start()


def _stop_button_hider():
    if _btn_timer is not None:
        _btn_timer.stop()


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


def _poll_overlay():
    """Re-centre the heads-up bar when the 3D area changes size (no event filter)."""
    global _last_size
    if _overlay is None:
        return
    try:
        parent = _overlay.parentWidget()
        size = (parent.width(), parent.height()) if parent else None
    except RuntimeError:
        return
    if size != _last_size:
        _last_size = size
        _place_overlay()
        _place_corner()
    # FreeCAD can bring its own toolbars back (e.g. after sketch mode).
    try:
        _hide_freecad_toolbars()
    except Exception:
        pass

    try:
        from mechflow_gui import origin_marker
        origin_marker.refresh()
    except Exception:
        pass
    try:
        from mechflow_gui import datum_display
        datum_display.refresh()
    except Exception:
        pass
    try:
        from mechflow_gui import rollback
        rollback.refresh()
    except Exception:
        pass


def _mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


class _Handle(QtWidgets.QLabel):
    """Grip on the left of the heads-up toolbar: drag to move it,
    double-click to put it back at the top centre."""

    def __init__(self, bar):
        super().__init__("\u22ee\u22ee")
        self._bar = bar
        self._grab = None
        self.setToolTip("Drag to move - double-click to reset")
        self.setStyleSheet("color: rgba(120,120,120,200); padding: 0 3px; font-weight: 700;")
        self.setCursor(QtCore.Qt.SizeAllCursor)

    OPAQUE = ("#MechFlow_HeadsUp { background: rgb(240, 240, 240);"
              " border: 1px solid rgba(120, 120, 120, 120); border-radius: 6px; }")

    def _repaint_behind(self):
        """Repaint the 3D view so no trail is left where the bar was."""
        try:
            self._bar.parentWidget().update()
            for w in self._bar.parentWidget().findChildren(QtWidgets.QWidget):
                if "GL" in type(w).__name__ or "Viewer" in type(w).__name__:
                    w.update()
        except Exception:
            pass
        try:
            Gui.ActiveDocument.ActiveView.redraw()
        except Exception:
            pass

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._grab = QtGui.QCursor.pos() - self._bar.pos()
            self._style = self._bar.styleSheet()
            self._bar.setStyleSheet(self.OPAQUE)     # solid while dragging
        e.accept()

    def mouseMoveEvent(self, e):
        if self._grab is None:
            return
        parent = self._bar.parentWidget()
        p = QtGui.QCursor.pos() - self._grab
        x = min(max(0, p.x()), max(0, parent.width() - self._bar.width()))
        y = min(max(0, p.y()), max(0, parent.height() - self._bar.height()))
        self._bar.move(x, y)
        self._repaint_behind()
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._grab is not None:
            self._grab = None
            self._bar.setStyleSheet(getattr(self, "_style", self._bar.styleSheet()))
            self._repaint_behind()
            parent = self._bar.parentWidget()
            # Remember as a fraction of the view, so it survives resizing.
            w = max(1, parent.width() - self._bar.width())
            h = max(1, parent.height() - self._bar.height())
            _params().SetFloat("HeadsUpX", self._bar.x() / w)
            _params().SetFloat("HeadsUpY", self._bar.y() / h)
        e.accept()

    def mouseDoubleClickEvent(self, e):
        _params().SetFloat("HeadsUpX", -1.0)
        _params().SetFloat("HeadsUpY", -1.0)
        _place_overlay()
        self._repaint_behind()
        e.accept()


def _build_overlay(parent):
    available = _available()
    bar = QtWidgets.QFrame(parent)
    bar.setObjectName("MechFlow_HeadsUp")
    from mechflow_gui import theme
    if theme.enabled():
        # SOLIDWORKS heads-up toolbar: just icons floating over the view.
        bar.setStyleSheet("#MechFlow_HeadsUp { background: transparent; border: none; }")
    else:
        bar.setStyleSheet(
            "#MechFlow_HeadsUp { background: rgba(60, 60, 60, 170);"
            " border: 1px solid rgba(255, 255, 255, 40); border-radius: 6px; }")
    row = QtWidgets.QHBoxLayout(bar)
    row.setContentsMargins(4, 2, 4, 2)
    row.setSpacing(1)
    row.addWidget(_Handle(bar))
    for e in HEADS_UP:
        if e is None:
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.VLine)
            line.setStyleSheet("color: rgba(128,128,128,90);")
            row.addWidget(line)
            continue
        label, target = e
        b = None
        if isinstance(target, list) and target and isinstance(target[0], tuple):
            b = _dropdown(label, target, 20, available)       # menu of choices
        elif isinstance(target, list):
            name = _first_available(target, available)        # fallbacks
            b = _tool_button(label, name, 20) if name else None
        elif target in available:
            b = _tool_button(label, target, 20)
        if b:
            row.addWidget(b)
    bar.adjustSize()
    return bar


# ------------------------------------------------------------ confirmation corner

_corner = None
CORNER_STYLE = """
#MechFlow_Corner QToolButton {
    font-size: 15px; font-weight: 700; min-width: 28px; min-height: 28px;
    max-width: 28px; max-height: 28px; padding: 0px;
    border-radius: 5px; background: rgba(255, 255, 255, 215);
    border: 1px solid rgba(120, 120, 120, 120);
}
#MechFlow_Corner QToolButton#ok { color: #3fbf5f; }
#MechFlow_Corner QToolButton#discard { color: #e05050; }
#MechFlow_Corner QToolButton#ok:hover { background: rgba(63, 191, 95, 90); }
#MechFlow_Corner QToolButton#discard:hover { background: rgba(224, 80, 80, 90); }
"""


def _exit_sketch():
    Gui.runCommand("Sketcher_LeaveSketch", 0)


def _discard_sketch():
    from mechflow_gui import sketch_mode
    sketch_mode.discard_sketch()


def _build_corner(parent):
    w = QtWidgets.QWidget(parent)
    w.setObjectName("MechFlow_Corner")
    w.setStyleSheet(CORNER_STYLE)
    row = QtWidgets.QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    ok = QtWidgets.QToolButton()
    ok.setObjectName("ok")
    ok.setText("\u2713")
    ok.setToolTip("Exit sketch, keeping changes")
    ok.clicked.connect(_exit_sketch)
    row.addWidget(ok)
    no = QtWidgets.QToolButton()
    no.setObjectName("discard")
    no.setText("\u2715")
    no.setToolTip("Exit sketch, discarding changes")
    no.clicked.connect(_discard_sketch)
    row.addWidget(no)
    w.adjustSize()
    return w


def _place_corner():
    if _corner is None:
        return
    try:
        parent = _corner.parentWidget()
    except RuntimeError:
        return
    if parent is None:
        return
    _corner.adjustSize()
    # Sit just left of the navigation cube in the top-right corner.
    x = max(0, parent.width() - _corner.width() - 190)
    _corner.move(x, 12)
    _corner.raise_()


def set_confirmation_corner(visible):
    """Show the SOLIDWORKS-style confirmation corner while a sketch is open."""
    global _corner
    mdi = _mdi()
    if mdi is None:
        return
    if visible:
        if _corner is None:
            _corner = _build_corner(mdi)
        _corner.show()
        _place_corner()
    elif _corner is not None:
        _corner.hide()


def _place_overlay():
    if _overlay is None:
        return
    try:
        parent = _overlay.parentWidget()
    except RuntimeError:
        return
    if parent is None:
        return
    _overlay.adjustSize()
    fx = _params().GetFloat("HeadsUpX", -1.0)
    fy = _params().GetFloat("HeadsUpY", -1.0)
    free_w = max(0, parent.width() - _overlay.width())
    free_h = max(0, parent.height() - _overlay.height())
    if fx < 0 or fy < 0:
        x, y = free_w // 2, 6                     # default: top centre
    else:
        x, y = int(fx * free_w), int(fy * free_h)
    _overlay.move(x, y)
    _overlay.raise_()


# ------------------------------------------------------------ toolbars

def _hide_freecad_toolbars():
    if not _params().GetBool("HideAllToolbars", True):
        return
    for bar in Gui.getMainWindow().findChildren(QtWidgets.QToolBar):
        if bar.objectName() in KEEP_TOOLBARS or not bar.isVisible():
            continue
        if bar.parent() is not Gui.getMainWindow():
            continue
        bar.hide()
        if bar not in _hidden:
            _hidden.append(bar)


def _restore_freecad_toolbars():
    while _hidden:
        bar = _hidden.pop()
        try:
            bar.show()
        except RuntimeError:
            pass


def toggle_toolbars():
    p = _params()
    hide = not p.GetBool("HideAllToolbars", True)
    p.SetBool("HideAllToolbars", hide)
    if hide:
        _hide_freecad_toolbars()
    else:
        _restore_freecad_toolbars()


# ------------------------------------------------------------ lifecycle

def show():
    global _quick, _overlay, _prev_corner
    mw = Gui.getMainWindow()

    if _quick is None:
        _quick = _build_quick()
    mb = mw.menuBar()
    current = mb.cornerWidget(QtCore.Qt.TopRightCorner)
    if current is not _quick:
        _prev_corner = current
        if current is not None:
            current.hide()
        mb.setCornerWidget(_quick, QtCore.Qt.TopRightCorner)
    _quick.show()
    _quick.adjustSize()
    _quick.setFixedSize(_quick.sizeHint())
    mb.updateGeometry()
    mb.adjustSize()

    mdi = _mdi()
    if mdi is not None:
        if _overlay is None:
            _overlay = _build_overlay(mdi)
        _overlay.show()
        _place_overlay()
        global _poll
        if _poll is None:
            _poll = QtCore.QTimer()
            _poll.setInterval(400)
            _poll.timeout.connect(_poll_overlay)
        _poll.start()
        _start_button_hider()

    _hide_freecad_toolbars()
    _hide_old_section_commands()


# FreeCAD's own clipping / section commands - replaced by MechFlow's
# Section View while MechFlow is active (put back when you leave).
OLD_SECTION_COMMANDS = ("Std_ToggleClipPlane", "Std_SectionCut")
_hidden_actions = []


def _hide_old_section_commands():
    for name in OLD_SECTION_COMMANDS:
        cmd = Gui.Command.get(name)
        for act in (cmd.getAction() if cmd else []):
            if act.isVisible():
                act.setVisible(False)
                _hidden_actions.append(act)


def _restore_old_section_commands():
    while _hidden_actions:
        act = _hidden_actions.pop()
        try:
            act.setVisible(True)
        except RuntimeError:
            pass


def show_later():
    """Run show() after FreeCAD has finished laying out its own toolbars."""
    QtCore.QTimer.singleShot(0, show)


def hide():
    mw = Gui.getMainWindow()
    if _quick is not None:
        _quick.hide()
        mb = mw.menuBar()
        if mb.cornerWidget(QtCore.Qt.TopRightCorner) is _quick and _prev_corner is not None:
            mb.setCornerWidget(_prev_corner, QtCore.Qt.TopRightCorner)
            _prev_corner.show()
    if _overlay is not None:
        _overlay.hide()
    if _corner is not None:
        _corner.hide()
    if _poll is not None:
        _poll.stop()
    _stop_button_hider()
    _restore_old_section_commands()
    try:
        from mechflow_gui import origin_marker, datum_display, rollback
        origin_marker.clear()
        datum_display.clear()
        rollback.clear()
    except Exception:
        pass
    _restore_freecad_toolbars()


def set_start_workbench():
    """Make FreeCAD open in MechFlow - once, so a later change by the user sticks."""
    p = _params()
    if p.GetBool("StartupSet", False):
        return
    App.ParamGet("User parameter:BaseApp/Preferences/General").SetString(
        "AutoloadModule", "MechFlowWorkbench")
    p.SetBool("StartupSet", True)
