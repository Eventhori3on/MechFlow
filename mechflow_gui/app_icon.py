# SPDX-License-Identifier: LGPL-2.1-or-later
"""MechFlow's icon on FreeCAD's window, taskbar button, task panels and
dialogs (they all fall back to the application icon)."""

import os

try:
    from PySide6 import QtGui, QtWidgets
except ImportError:
    from PySide2 import QtGui, QtWidgets

ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZES = (16, 24, 32, 48, 64, 128, 256)


def icon():
    ic = QtGui.QIcon()
    folder = os.path.join(ADDON_DIR, "Resources", "icons", "app")
    for n in SIZES:
        p = os.path.join(folder, f"MechFlow-{n}.png")
        if os.path.exists(p):
            ic.addFile(p)
    if ic.isNull():
        ic = QtGui.QIcon(os.path.join(ADDON_DIR, "Resources", "icons", "MechFlow.svg"))
    return ic


def apply():
    ic = icon()
    if ic.isNull():
        return
    QtWidgets.QApplication.setWindowIcon(ic)
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        if mw is not None:
            mw.setWindowIcon(ic)
    except Exception:
        pass


def version():
    """MechFlow's version, from package.xml."""
    import re
    try:
        with open(os.path.join(ADDON_DIR, "package.xml"), encoding="utf-8") as f:
            m = re.search(r"<version>\s*([^<\s]+)\s*</version>", f.read())
        return m.group(1) if m else ""
    except Exception:
        return ""


def branded_title(title, fc_version, mf_version):
    """'Part1 - FreeCAD 1.1.4' -> 'Part1 - MechFlow 0.27.1 · FreeCAD 1.1.4'."""
    old = f"FreeCAD {fc_version}".strip()
    if not mf_version or "MechFlow " in title or old not in title:
        return title
    return title.replace(old, f"MechFlow {mf_version} · {old}", 1)


_title_hooked = []


def brand_title():
    """Keep MechFlow's version in the main window's title (FreeCAD resets the
    title whenever the active document changes)."""
    import FreeCADGui as Gui
    import FreeCAD as App
    mw = Gui.getMainWindow()
    if mw is None or _title_hooked:
        return
    fc = ".".join(App.Version()[:3])
    mf = version()
    busy = []

    def fix(t):
        if busy:
            return
        new = branded_title(t, fc, mf)
        if new != t:
            busy.append(1)
            try:
                mw.setWindowTitle(new)
            finally:
                busy.clear()

    mw.windowTitleChanged.connect(fix)
    _title_hooked.append(fix)
    fix(mw.windowTitle())
