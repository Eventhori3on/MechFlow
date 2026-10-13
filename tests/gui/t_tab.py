import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("T"); b = new_body(doc, "Body")
    sk = sketch(b, "XY_Plane", rect(0, 0, 40, 20)); doc.recompute(); S["sk"] = sk
    Gui.ActiveDocument.setEdit(sk.Name)
at(setup, 1800)
def check():
    from mechflow_gui import command_manager as cm
    avail = set(Gui.listCommands())
    missing = []
    for tab, entries in cm.TABS:
        if tab != "Sketch": continue
        for e in entries:
            if e is None: continue
            if e[0] == "stack": items = e[1]
            elif e[0] == "grid": items = e[2]
            else: items = [e]
            for label, cmd in items:
                if cm._resolve(cmd, avail) is None: missing.append((label, cmd))
    log("Sketch tab missing:", missing)
    try: cm.select_tab("Sketch")
    except Exception as ex: log("select_tab err", ex)
at(check, 800)
at(lambda: Gui.getMainWindow().grab().copy(0, 0, 1600, 130).save(SHOTS + "sketchtab.png"), 300)
def tog():
    from mechflow_gui import relations
    Gui.runCommand("MechFlow_Relations", 0)
at(tog, 500)
at(lambda: log("after toggle: panel visible", __import__("mechflow_gui.relations", fromlist=["x"])._panel.isVisible()), 400)
at(tog, 500)
at(lambda: log("after 2nd toggle: panel visible", __import__("mechflow_gui.relations", fromlist=["x"])._panel.isVisible()), 400)
run()
