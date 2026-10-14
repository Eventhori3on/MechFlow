import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import os
from mechflow_gui import splash as _sp
B = _sp.branding_path()
def setup():
    install_hooks()
    def auto(self):
        log("  [question box]", self.text().replace("\n", " ")[:90], "->", self.buttons()[0].text())
        self.buttons()[0].click(); return 0
    QtWidgets.QMessageBox.exec = auto
    Gui.activateWorkbench("MechFlowWorkbench")
at(setup, 1500)


def app_icon():
    # MechFlow's icon on the window and as the fallback for panels/dialogs
    ic = QtWidgets.QApplication.windowIcon()
    sizes = sorted(sz.width() for sz in ic.availableSizes())
    mw = Gui.getMainWindow().windowIcon()
    panel = QtWidgets.QWidget().windowIcon()
    img = mw.pixmap(32, 32).toImage()
    c = img.pixelColor(16, 6)                    # top face of the block: light blue
    log("app icon sizes", sizes, "| window icon top colour", c.name(), "| panel falls back to it",
        panel.cacheKey() == ic.cacheKey())
    assert 256 in sizes and c.blue() > 200 and c.red() < 140
    from mechflow_gui import app_icon
    d = App.newDocument("TitleCheck")
    QtWidgets.QApplication.processEvents()
    t = Gui.getMainWindow().windowTitle()
    log("window title", repr(t))
    assert f"MechFlow {app_icon.version()} \u00b7 FreeCAD " in t and "TitleCheck" in t
    App.closeDocument(d.Name)
at(app_icon, 300)
def s(): from mechflow_gui import splash; return splash
at(lambda: log("state before:", s().state(), "| branding path:", s().branding_path()), 100)
at(lambda: Gui.runCommand("MechFlow_InstallSplash", 0), 500)
at(lambda: log("state after install:", s().state(), "| file has image path:", s().image_path().replace("\\", "/") in open(B).read(), "| wanted:", App.ParamGet(s().PARAMS).GetBool("SplashWanted")), 100)


def writable():
    # FreeCAD installed under Program Files (Windows) can't be changed
    # without admin rights: the rest needs a writable install
    probe = os.path.join(os.path.dirname(B), "mechflow_write_test.tmp")
    try:
        open(probe, "w").close()
        os.remove(probe)
        return True
    except OSError:
        return False
if not writable():
    at(lambda: log("FreeCAD's folder is read-only here: the reinstall/foreign-file steps are skipped"), 100)
else:
    at(lambda: (os.remove(B), log("simulated FreeCAD reinstall: file removed, state:", s().state())), 100)
    at(lambda: s().check_at_startup(), 500)
    at(lambda: log("state after startup check:", s().state()), 100)
    at(lambda: Gui.runCommand("MechFlow_RestoreSplash", 0), 500)
    at(lambda: log("state after restore:", s().state(), "| wanted:", App.ParamGet(s().PARAMS).GetBool("SplashWanted")), 100)
    def foreign():
        open(B, "w").write("<?xml version='1.0'?><Branding><WindowTitle>Other</WindowTitle></Branding>")
        Gui.runCommand("MechFlow_InstallSplash", 0)
    at(foreign, 500)
    at(lambda: (log("foreign branding kept:", "Other" in open(B).read(), "| state:", s().state()), os.remove(B)), 100)
    at(lambda: Gui.runCommand("MechFlow_InstallSplash", 0), 500)
    at(lambda: log("final state:", s().state()), 100)
run()
