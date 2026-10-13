# SPDX-License-Identifier: LGPL-2.1-or-later
"""MechFlow Welcome dialog, like SOLIDWORKS' Welcome.

Shown as its own window: FreeCAD's document area only accepts FreeCAD's own
document views, and putting anything else there crashes Qt.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from mechflow_gui import icon_path

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
RECENT = "User parameter:BaseApp/Preferences/RecentFiles"
MAX_RECENT = 10

_sub = None   # the open Welcome dialog

STYLE = """
#MechFlow_Welcome { background: palette(window); }
#MechFlow_Welcome QLabel#title { font-size: 28px; font-weight: 600; }
#MechFlow_Welcome QLabel#subtitle { color: palette(mid); font-size: 13px; }
#MechFlow_Welcome QLabel#section { font-size: 15px; font-weight: 600; margin-top: 18px; }
#MechFlow_Welcome QPushButton#big {
    font-size: 14px; padding: 14px 22px; min-width: 150px;
    border: 1px solid palette(mid); border-radius: 6px; text-align: left;
}
#MechFlow_Welcome QPushButton#big:hover { border-color: #3d8ee0; background: rgba(61,142,224,30); }
#MechFlow_Welcome QPushButton#recent {
    text-align: left; padding: 7px 10px; border: none; border-radius: 4px;
}
#MechFlow_Welcome QPushButton#recent:hover { background: rgba(61,142,224,30); }
"""


def _params():
    return App.ParamGet(PARAMS)


def _recent_files():
    p = App.ParamGet(RECENT)
    files = []
    for i in range(MAX_RECENT):
        path = p.GetString(f"MRU{i}", "")
        if path and os.path.isfile(path):
            files.append(path)
    return files


START_PARAMS = "User parameter:BaseApp/Preferences/Mod/Start"


def _quiet_freecad_start():
    """Ask FreeCAD not to show its own Start page at launch (its own setting)."""
    try:
        App.ParamGet(START_PARAMS).SetBool("ShowOnStartup", False)
    except Exception:
        pass


def _run_and_close(fn):
    def go(*_):
        fn()
        close()
    return go


def _open_file(path):
    try:
        App.openDocument(path)
    except Exception as e:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Open", str(e))


def _build():
    w = QtWidgets.QWidget()
    w.setObjectName("MechFlow_Welcome")
    w.setWindowTitle("Welcome")
    w.setStyleSheet(STYLE)

    outer = QtWidgets.QHBoxLayout(w)
    outer.addStretch(1)
    col_w = QtWidgets.QWidget()
    col_w.setMaximumWidth(720)
    col = QtWidgets.QVBoxLayout(col_w)
    col.setContentsMargins(24, 48, 24, 24)
    outer.addWidget(col_w, 3)
    outer.addStretch(1)

    # Header
    head = QtWidgets.QHBoxLayout()
    logo = QtWidgets.QLabel()
    logo.setPixmap(QtGui.QIcon(icon_path("MechFlow.svg")).pixmap(64, 64))
    head.addWidget(logo)
    titles = QtWidgets.QVBoxLayout()
    t = QtWidgets.QLabel("MechFlow")
    t.setObjectName("title")
    s = QtWidgets.QLabel("A familiar part-design workflow, built on FreeCAD")
    s.setObjectName("subtitle")
    titles.addWidget(t)
    titles.addWidget(s)
    head.addLayout(titles)
    head.addStretch(1)
    col.addLayout(head)
    col.addSpacing(24)

    # Actions
    actions = QtWidgets.QHBoxLayout()
    for text, icon, fn in (
        ("New Part", icon_path("MechFlow.svg"),
         lambda: Gui.runCommand("MechFlow_NewPart", 0)),
        ("Open…", None, lambda: Gui.runCommand("Std_Open", 0)),
    ):
        b = QtWidgets.QPushButton(text)
        b.setObjectName("big")
        b.setCursor(QtCore.Qt.PointingHandCursor)
        if icon:
            b.setIcon(QtGui.QIcon(icon))
            b.setIconSize(QtCore.QSize(28, 28))
        else:
            b.setIcon(w.style().standardIcon(QtWidgets.QStyle.SP_DirOpenIcon))
            b.setIconSize(QtCore.QSize(28, 28))
        b.clicked.connect(_run_and_close(fn))
        actions.addWidget(b)
    actions.addStretch(1)
    col.addLayout(actions)

    # Recent
    sec = QtWidgets.QLabel("Recent documents")
    sec.setObjectName("section")
    col.addWidget(sec)
    files = _recent_files()
    if not files:
        none = QtWidgets.QLabel("Nothing yet - your recent parts will appear here.")
        none.setObjectName("subtitle")
        col.addWidget(none)
    file_icon = w.style().standardIcon(QtWidgets.QStyle.SP_FileIcon)
    for path in files:
        name = os.path.basename(path)
        folder = os.path.dirname(path)
        b = QtWidgets.QPushButton(f"{name}    —    {folder}")
        b.setObjectName("recent")
        b.setIcon(file_icon)
        b.setToolTip(path)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.clicked.connect(_run_and_close(lambda p=path: _open_file(p)))
        col.addWidget(b)

    col.addStretch(1)

    # Footer
    foot = QtWidgets.QHBoxLayout()
    show = QtWidgets.QCheckBox("Show this page at startup")
    show.setChecked(_params().GetBool("ShowWelcome", True))
    show.toggled.connect(lambda v: _params().SetBool("ShowWelcome", v))
    foot.addWidget(show)
    foot.addStretch(1)
    col.addLayout(foot)
    return w


def show():
    """Open (or bring forward) the Welcome dialog."""
    global _sub
    if _sub is not None:
        try:
            _sub.show()
            _sub.raise_()
            _sub.activateWindow()
            return
        except RuntimeError:
            _sub = None
    mw = Gui.getMainWindow()
    dlg = QtWidgets.QDialog(mw)
    dlg.setWindowTitle("Welcome - MechFlow")
    dlg.setWindowIcon(QtGui.QIcon(icon_path("MechFlow.svg")))
    lay = QtWidgets.QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(_build())
    dlg.resize(760, 540)
    dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    dlg.finished.connect(_forget)
    _sub = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def _forget(*_):
    global _sub
    _sub = None


def close():
    global _sub
    if _sub is not None:
        try:
            _sub.close()
        except RuntimeError:
            pass
        _sub = None


def show_at_startup():
    """Called once when MechFlow first loads."""
    if not _params().GetBool("ShowWelcome", True):
        return
    _quiet_freecad_start()
    if App.listDocuments():
        return  # FreeCAD was started with a file: go straight to it
    QtCore.QTimer.singleShot(400, show)
