# SPDX-License-Identifier: LGPL-2.1-or-later
"""MechFlow start-up splash screen.

FreeCAD shows its splash before any addon loads, so the only way to change it
is FreeCAD's own branding file: a small ``branding.xml`` next to the FreeCAD
program (``<FreeCAD>/bin``) naming the splash image by its full path. The
image stays in the MechFlow folder.

On Windows FreeCAD is usually in Program Files, so writing that one file needs
administrator permission: Windows asks once (the usual "allow this app to make
changes" prompt). Reinstalling or updating FreeCAD removes the file; MechFlow
notices and offers to put it back.

FreeCAD writes its own version number on the splash; MechFlow moves it off
the image (the artwork says "Built on FreeCAD" instead).
"""

import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
MARKER = "MechFlow splash screen"
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def image_path():
    # "@2x" tells Qt the image is double resolution: sharp on scaled screens.
    return os.path.join(ADDON_DIR, "Resources", "splash", "MechFlowSplash@2x.png")


def branding_path():
    return os.path.join(App.getHomePath(), "bin", "branding.xml")


def branding_xml():
    img = image_path().replace("\\", "/")
    return ("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            f"<!-- {MARKER}: written by MechFlow. Delete this file (or use MechFlow >\n"
            "     Restore FreeCAD Splash Screen) to get FreeCAD's own splash back. -->\n"
            "<Branding>\n"
            f"    <SplashScreen>{escape(img)}</SplashScreen>\n"
            "    <SplashInfoPosition>4000,4000</SplashInfoPosition>\n"
            "</Branding>\n")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def state():
    """'ours' (current), 'ours-old' (ours but points elsewhere), 'other'
    (someone else's branding), or 'none'."""
    text = _read(branding_path())
    if text is None:
        return "none"
    if MARKER not in text:
        return "other"
    return "ours" if text.strip() == branding_xml().strip() else "ours-old"


# ------------------------------------------------------------ writing

def _write_direct(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _ps_quote(s):
    return s.replace("'", "''")


def _elevated(cmd_line):
    """Run a cmd.exe command with administrator rights (Windows asks)."""
    ps = ("Start-Process -FilePath 'cmd.exe' -ArgumentList '/c " + _ps_quote(cmd_line) +
          "' -Verb RunAs -Wait -WindowStyle Hidden")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", ps], capture_output=True, text=True, creationflags=flags)
    return r.returncode == 0


def _put(text):
    """Write branding.xml; ask Windows for permission if needed."""
    dest = branding_path()
    try:
        _write_direct(dest, text)
        return True, ""
    except PermissionError:
        pass
    except Exception as e:
        return False, str(e)
    if sys.platform != "win32":
        return False, (f"FreeCAD's folder ({os.path.dirname(dest)}) can't be written to "
                       "(on Linux, an AppImage is read-only).")
    tmp = os.path.join(tempfile.gettempdir(), "mechflow_branding.xml")
    _write_direct(tmp, text)
    ok = _elevated(f'copy /Y "{tmp}" "{dest}"')
    if ok and _read(dest) == text:
        return True, ""
    return False, "Windows didn't allow the change (the permission prompt was declined?)."


def _remove():
    dest = branding_path()
    try:
        os.remove(dest)
        return True, ""
    except FileNotFoundError:
        return True, ""
    except PermissionError:
        pass
    except Exception as e:
        return False, str(e)
    if sys.platform != "win32":
        return False, f"{dest} can't be removed (read-only)."
    ok = _elevated(f'del /F /Q "{dest}"')
    return (ok and not os.path.exists(dest)), "Windows didn't allow the change."


# ------------------------------------------------------------ commands

def _mw():
    return Gui.getMainWindow()


def install(quiet=False):
    if not os.path.exists(image_path()):
        QtWidgets.QMessageBox.warning(_mw(), "MechFlow Splash Screen",
                                      "The splash image is missing from the MechFlow folder.")
        return False
    st = state()
    if st == "other":
        QtWidgets.QMessageBox.information(
            _mw(), "MechFlow Splash Screen",
            "FreeCAD already has a branding file from something else:\n"
            f"{branding_path()}\n\nMechFlow won't overwrite it.")
        return False
    if st == "ours":
        App.ParamGet(PARAMS).SetBool("SplashWanted", True)
        if not quiet:
            QtWidgets.QMessageBox.information(
                _mw(), "MechFlow Splash Screen",
                "The MechFlow splash screen is already set up. You'll see it next time "
                "FreeCAD starts.")
        return True
    if not quiet and sys.platform == "win32":
        QtWidgets.QMessageBox.information(
            _mw(), "MechFlow Splash Screen",
            "FreeCAD's splash is set by a small file in FreeCAD's program folder, so "
            "Windows will ask for permission to change it.\n\n"
            "Click Yes on Windows' prompt to continue.")
    ok, why = _put(branding_xml())
    if ok:
        App.ParamGet(PARAMS).SetBool("SplashWanted", True)
        App.ParamGet(PARAMS).SetBool("SplashStopAsking", False)
        QtWidgets.QMessageBox.information(
            _mw(), "MechFlow Splash Screen",
            "Done - you'll see the MechFlow splash screen next time FreeCAD starts.")
        return True
    QtWidgets.QMessageBox.warning(
        _mw(), "MechFlow Splash Screen",
        f"The splash screen couldn't be set.\n\n{why}\n\n"
        "To do it by hand, save this as branding.xml in\n"
        f"{os.path.dirname(branding_path())}:\n\n{branding_xml()}")
    return False


def restore():
    if state() == "other":
        QtWidgets.QMessageBox.information(
            _mw(), "Restore FreeCAD Splash Screen",
            "The branding file there isn't MechFlow's, so MechFlow has left it alone.")
        return False
    ok, why = _remove()
    App.ParamGet(PARAMS).SetBool("SplashWanted", False)
    if ok:
        QtWidgets.QMessageBox.information(
            _mw(), "Restore FreeCAD Splash Screen",
            "FreeCAD's own splash screen will be back next time FreeCAD starts.")
    else:
        QtWidgets.QMessageBox.warning(
            _mw(), "Restore FreeCAD Splash Screen",
            f"Couldn't remove {branding_path()}.\n\n{why}")
    return ok


def check_at_startup():
    """After a FreeCAD update the branding file is gone (or MechFlow moved):
    offer to put the splash back, unless the user said not to."""
    p = App.ParamGet(PARAMS)
    if not p.GetBool("SplashWanted", False) or p.GetBool("SplashStopAsking", False):
        return
    st = state()
    if st in ("ours", "other"):
        return
    box = QtWidgets.QMessageBox(_mw())
    box.setWindowTitle("MechFlow Splash Screen")
    box.setText("FreeCAD has been updated or reinstalled, which removed the MechFlow "
                "splash screen.\n\nPut it back?")
    yes = box.addButton("Put it back", QtWidgets.QMessageBox.AcceptRole)
    box.addButton("Not now", QtWidgets.QMessageBox.RejectRole)
    never = box.addButton("Don't ask again", QtWidgets.QMessageBox.DestructiveRole)
    box.exec()
    if box.clickedButton() is yes:
        install(quiet=True)
    elif box.clickedButton() is never:
        p.SetBool("SplashStopAsking", True)
