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
