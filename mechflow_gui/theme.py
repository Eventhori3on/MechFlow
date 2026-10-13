# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style light theme for MechFlow.

Light grey panels, white tree, blue hover/selection, Segoe UI, and a white to
pale blue-grey gradient behind the model. Applied while MechFlow is active and
fully restored when you switch to another workbench.

Toggle: MechFlow -> Light / Dark Theme (remembered).
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtGui, QtWidgets
except ImportError:
    from PySide2 import QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
VIEW = "User parameter:BaseApp/Preferences/View"

QSS = """
* { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 9pt; color: #1a1a1a; }
QMainWindow, QDialog, QDockWidget, QStackedWidget, QScrollArea { background: #f0f0f0; }
QMainWindow::separator { background: #d6d6d6; width: 4px; height: 4px; }

QMenuBar { background: #f5f5f5; border-bottom: 1px solid #d9d9d9; }
QMenuBar::item { padding: 4px 9px; background: transparent; }
QMenuBar::item:selected { background: #cce4f7; }
QMenu { background: #ffffff; border: 1px solid #c8c8c8; padding: 3px; }
QMenu::item { padding: 4px 22px 4px 24px; }
QMenu::item:selected { background: #cce4f7; }
QMenu::item:disabled { color: #9a9a9a; }
QMenu::separator { height: 1px; background: #e2e2e2; margin: 3px 6px; }

QToolBar { background: #f5f5f5; border: none; spacing: 2px; }
QToolBar#MechFlow_CommandManager {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #fbfbfb, stop:1 #ececec);
    border-bottom: 1px solid #c9c9c9; padding: 1px 2px; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 3px; padding: 2px; }
QToolButton:hover { background: #e5f1fb; border: 1px solid #7eb4ea; }
QToolButton:pressed, QToolButton:checked { background: #cce4f7; border: 1px solid #569de5; }
QToolButton:disabled { color: #a0a0a0; }

QTabWidget::pane { border: none; }
QTabBar::tab { background: #e9e9e9; border: 1px solid #cfcfcf; padding: 3px 10px;
               margin-right: 1px; color: #333333; }
QTabBar::tab:selected { background: #ffffff; color: #000000; font-weight: 600; }
QTabBar::tab:hover:!selected { background: #f4f9fd; }

QDockWidget::title { background: #ececec; padding: 4px; border-bottom: 1px solid #d9d9d9; }
QTreeView, QTreeWidget, QListView, QListWidget, QTableView, QPlainTextEdit, QTextEdit {
    background: #ffffff; alternate-background-color: #f7f7f7; border: 1px solid #d0d0d0;
    selection-background-color: #cce8ff; selection-color: #000000; }
QTreeView::item:hover, QListView::item:hover { background: #e5f3ff; }
QTreeView::item:selected, QListView::item:selected { background: #cce8ff; color: #000000; }
QHeaderView::section { background: #f0f0f0; border: none; border-right: 1px solid #dddddd;
                       border-bottom: 1px solid #dddddd; padding: 3px 6px; }

QGroupBox { background: #ffffff; border: 1px solid #d0d0d0; border-radius: 3px;
            margin-top: 14px; padding: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px;
                   color: #1f4e8c; font-weight: 600; background: transparent; }
QPushButton { background: #fdfdfd; border: 1px solid #adadad; border-radius: 3px; padding: 4px 12px; }
QPushButton:hover { background: #e5f1fb; border-color: #0078d7; }
QPushButton:pressed { background: #cce4f7; }
QPushButton:disabled { color: #a0a0a0; border-color: #d0d0d0; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #ffffff; border: 1px solid #b9b9b9; border-radius: 2px; padding: 2px 4px;
    selection-background-color: #0078d7; selection-color: #ffffff; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #0078d7; }
QComboBox QAbstractItemView { background: #ffffff; selection-background-color: #cce4f7;
                              selection-color: #000000; }
QCheckBox, QRadioButton, QLabel { background: transparent; }
QScrollBar:vertical { background: #f0f0f0; width: 12px; margin: 0; }
QScrollBar:horizontal { background: #f0f0f0; height: 12px; margin: 0; }
QScrollBar::handle { background: #c2c2c2; border-radius: 4px; min-height: 24px; min-width: 24px; margin: 2px; }
QScrollBar::handle:hover { background: #a6a6a6; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QStatusBar { background: #f0f0f0; border-top: 1px solid #d9d9d9; }
QToolTip { background: #ffffe1; color: #000000; border: 1px solid #767676; padding: 3px; }
QMdiArea { background: #ffffff; }
"""

# 3D background gradient: (param name, value as 0xRRGGBBAA)
BACKGROUND = {
    "Simple": False,
    "Gradient": True,
    "BackgroundColor2": 0xFFFFFFFF,     # top: white
    "BackgroundColor3": 0xB9CAD9FF,     # bottom: pale blue-grey
    "UseBackgroundColorMid": False,
}

_applied = False
_saved_qss = None
_saved_palette = None


def enabled():
    return App.ParamGet(PARAMS).GetBool("LightTheme", True)


def _palette():
    p = QtGui.QPalette()
    c = QtGui.QColor
    roles = QtGui.QPalette
    p.setColor(roles.Window, c("#f0f0f0"))
    p.setColor(roles.WindowText, c("#1a1a1a"))
    p.setColor(roles.Base, c("#ffffff"))
    p.setColor(roles.AlternateBase, c("#f7f7f7"))
    p.setColor(roles.Text, c("#1a1a1a"))
    p.setColor(roles.Button, c("#f5f5f5"))
    p.setColor(roles.ButtonText, c("#1a1a1a"))
    p.setColor(roles.Highlight, c("#cce8ff"))
    p.setColor(roles.HighlightedText, c("#000000"))
    p.setColor(roles.ToolTipBase, c("#ffffe1"))
    p.setColor(roles.ToolTipText, c("#000000"))
    p.setColor(roles.Mid, c("#b0b0b0"))
    p.setColor(roles.Light, c("#ffffff"))
    p.setColor(roles.Dark, c("#a0a0a0"))
    p.setColor(roles.PlaceholderText, c("#8a8a8a"))
    for grp in (roles.Disabled,):
        p.setColor(grp, roles.WindowText, c("#9a9a9a"))
        p.setColor(grp, roles.Text, c("#9a9a9a"))
        p.setColor(grp, roles.ButtonText, c("#9a9a9a"))
    return p


def _set_background(on):
    view, mine = App.ParamGet(VIEW), App.ParamGet(PARAMS)
    if on:
        if not mine.GetBool("BackgroundSaved", False):
            for k, v in BACKGROUND.items():
                if isinstance(v, bool):
                    mine.SetBool("Saved_" + k, view.GetBool(k, not v))
                else:
                    mine.SetUnsigned("Saved_" + k, view.GetUnsigned(k, v))
            mine.SetBool("BackgroundSaved", True)
        for k, v in BACKGROUND.items():
            if isinstance(v, bool):
                view.SetBool(k, v)
            else:
                view.SetUnsigned(k, v)
    elif mine.GetBool("BackgroundSaved", False):
        for k, v in BACKGROUND.items():
            if isinstance(v, bool):
                view.SetBool(k, mine.GetBool("Saved_" + k, not v))
            else:
                view.SetUnsigned(k, mine.GetUnsigned("Saved_" + k, v))
        mine.SetBool("BackgroundSaved", False)


def apply():
    global _applied, _saved_qss, _saved_palette
    if not enabled() or _applied:
        return
    app = QtWidgets.QApplication.instance()
    _saved_qss = app.styleSheet()
    _saved_palette = QtGui.QPalette(app.palette())
    app.setPalette(_palette())
    app.setStyleSheet(QSS)
    try:
        _set_background(True)
    except Exception as e:
        App.Console.PrintWarning(f"MechFlow: background not changed ({e})\n")
    _applied = True


def restore():
    global _applied
    if not _applied:
        return
    app = QtWidgets.QApplication.instance()
    if _saved_palette is not None:
        app.setPalette(_saved_palette)
    app.setStyleSheet(_saved_qss or "")
    try:
        _set_background(False)
    except Exception:
        pass
    _applied = False


def restore_after_crash():
    """If FreeCAD closed while the light background was on, put it back."""
    try:
        _set_background(False)
    except Exception:
        pass


def toggle():
    p = App.ParamGet(PARAMS)
    p.SetBool("LightTheme", not enabled())
    if enabled():
        apply()
    else:
        restore()
