# Run MechFlow's GUI smoke tests inside a running FreeCAD (any OS, e.g.
# Windows, where run_tests.sh's xvfb isn't available). In FreeCAD's Python
# console:
#
#   exec(open(r"<path to MechFlow>/tests/run_in_freecad.py").read())
#
# or, for some tests only:
#
#   MF_ONLY = ["t_stress", "t_pack"]; exec(open(r".../run_in_freecad.py").read())
#
# Each test runs in turn in this session; documents the tests open are
# closed afterwards. Logs, screenshots and summary.txt go to
# "<FreeCAD user data>/MechFlow Test Results".
import os, sys, time, traceback
import FreeCAD as App, FreeCADGui as Gui
from PySide6 import QtCore, QtWidgets


def _mf_suite():
    mod = os.path.join(App.getUserAppDataDir(), "Mod", "MechFlow")
    here = os.path.join(mod, "tests")
    gui = os.path.join(here, "gui")
    out = os.path.join(App.getUserAppDataDir(), "MechFlow Test Results")
    os.makedirs(out, exist_ok=True)
    os.environ["MF_TESTDIR"] = gui
    os.environ["MF_OUT"] = out
    if gui not in sys.path:
        sys.path.insert(0, gui)
    import h
    h.OUT = out.replace("\\", "/").rstrip("/") + "/"
    h.SHOTS = h.OUT + "shots/"
    os.makedirs(h.SHOTS, exist_ok=True)

    tests = globals().get("MF_ONLY") or [
        "t_tabs", "t_pat", "t_dress", "t_sweep", "t_thin", "t_handles", "t_rel", "t_tab",
        "t_draw", "t_asm", "t_splash", "t_hole", "t_toolbox", "t_toolbox2", "t_cpat",
        "t_lpat", "t_stdparts", "t_joint", "t_smart", "t_weld", "t_weld2", "t_sm", "t_mass",
        "t_nozzle", "t_pack", "t_route", "t_config", "t_stress", "t_supplier",
        "t_sketch3d", "t_valves", "t_author", "t_sizes", "t_scan", "t_scan2", "t_sheet", "t_pipedraw",
        "t_stress2", "t_motion"]
    timeout_s = int(globals().get("MF_TIMEOUT", 600))
    real_exit = os._exit
    boxes = {k: getattr(QtWidgets.QMessageBox, k) for k in ("information", "warning", "critical")}
    # the tests change a few preferences (author name, ...): put them back after
    # (only the groups the tests touch: putting back all of FreeCAD's
    # preferences re-applies its style sheet over MechFlow's theme)
    groups = ["Document", "Mod/MechFlow", "Mod/TechDraw/Colors"]
    prefs = []
    for g_ in groups:
        f_ = os.path.join(out, "preferences before tests - " + g_.replace("/", " ") + ".FCParam")
        try:
            App.ParamGet("User parameter:BaseApp/Preferences/" + g_).Export(f_)
            prefs.append((g_, f_))
        except Exception:
            pass
    before = set(App.listDocuments())
    def _windows():
        # dialogs parented to the main window aren't "top-level widgets"
        mw = Gui.getMainWindow()
        out = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isWindow()]
        out += [w for w in mw.findChildren(QtWidgets.QDialog) if w.isWindow()]
        return out
    dialogs = [w for w in _windows() if w.isVisible()]
    st = {"i": 0, "gen": 0, "t0": 0.0, "results": []}
    summary = os.path.join(out, "summary.txt")
    open(summary, "w", encoding="utf-8").write(f"MechFlow tests, FreeCAD {'.'.join(App.Version()[:3])}, "
                             f"{sys.platform}, {time.ctime()}\n")

    def write(line):
        open(summary, "a", encoding="utf-8").write(line + "\n")
        App.Console.PrintMessage("MechFlow test: " + line + "\n")

    def check(t, secs, note=""):
        log = os.path.join(out, t + ".log")
        problems = []
        if not os.path.exists(log):
            problems.append("no log written")
        else:
            text = open(log, encoding="utf-8", errors="replace").read()
            if "\nDONE" not in "\n" + text:
                problems.append("did not finish")
            for key, what in (("Traceback", "traceback(s)"), ("err=True", "panel error(s)"),
                              ("!! ", "unexpected dialog/button(s)")):
                n = text.count(key)
                if n:
                    problems.append(f"{n} {what}")
        if note:
            problems.append(note)
        line = (f"FAIL  {t}: {'; '.join(problems)}" if problems else f"ok    {t}") + f"  ({secs:.0f} s)"
        st["results"].append(not problems)
        write(line)

    def tidy():
        for holder in (h.__dict__, globals()):
            w = holder.get("_wd")
            if w is not None:
                try:
                    w.stop()
                except Exception:
                    pass
        try:
            Gui.Control.closeDialog()
        except Exception:
            pass
        # dialogs a test left open (BOM, cut list...)
        mw = Gui.getMainWindow()
        for w in _windows():
            if w is not mw and w.isVisible() and w not in dialogs:
                try:
                    w.close()
                except Exception:
                    pass
        for name in list(App.listDocuments()):
            if name not in before:
                try:
                    App.closeDocument(name)
                except Exception:
                    pass

    def finish():
        os._exit = real_exit
        for g_, f_ in prefs:
            try:
                App.ParamGet("User parameter:BaseApp/Preferences/" + g_).Import(f_)
            except Exception as e:
                write(f"(preferences {g_} not restored: {e})")
        for k, f in boxes.items():
            setattr(QtWidgets.QMessageBox, k, f)
        n_ok = sum(st["results"])
        write(f"{n_ok} of {len(st['results'])} passed")
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "MechFlow tests",
            f"{n_ok} of {len(st['results'])} tests passed.\n\nDetails: {summary}")

    def next_test(note=""):
        st["gen"] += 1
        gen = st["gen"]
        if st["i"]:
            check(tests[st["i"] - 1], time.time() - st["t0"], note)
        tidy()
        if st["i"] >= len(tests):
            finish()
            return
        t = tests[st["i"]]
        st["i"] += 1
        h.Q.clear()
        h.CUR["p"] = None
        h.LOG = os.path.join(out, t + ".log")
        os.environ["MF_LOG"] = h.LOG
        if os.path.exists(h.LOG):
            os.remove(h.LOG)
        st["t0"] = time.time()

        def timed_out():
            if st["gen"] == gen:
                h.Q.clear()          # the step chain ends at its next step
                next_test(f"timed out after {timeout_s} s")
        QtCore.QTimer.singleShot(timeout_s * 1000, timed_out)
        path = os.path.join(gui, t + ".py")
        try:
            code = compile(open(path, encoding="utf-8").read(), path, "exec")
            exec(code, {"__name__": "__main__", "__file__": path})
        except Exception:
            h.log(traceback.format_exc())
            QtCore.QTimer.singleShot(500, lambda: next_test() if st["gen"] == gen else None)

    def fake_exit(code=0):
        gen = st["gen"]
        QtCore.QTimer.singleShot(800, lambda: next_test() if st["gen"] == gen else None)

    os._exit = fake_exit
    next_test()


_mf_suite()
