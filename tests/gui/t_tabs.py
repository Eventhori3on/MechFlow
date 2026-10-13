import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
def go():
    install_hooks(); Gui.activateWorkbench("MechFlowWorkbench")
    from mechflow_gui import command_manager as cm
    avail = set(Gui.listCommands())
    for tab, entries in cm.TABS:
        missing = []
        for e in entries:
            if e is None: continue
            items = e[1] if e[0] == "stack" else (e[2] if e[0] == "grid" else [e])
            for label, cmd in items:
                if cm._resolve(cmd, avail) is None: missing.append((label, cmd))
        log(f"tab {tab}: missing {missing}")
    cm.select_tab("Assembly")
at(go, 2000)
at(lambda: Gui.getMainWindow().grab().copy(0, 0, 1600, 130).save(SHOTS + "asmtab.png"), 300)
run()
