import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
V = App.Vector
S = {}


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    d = App.newDocument("MotionTest"); S["d"] = d
    b = d.addObject("Part::Box", "Box"); b.Length = 10
    d.recompute()
    from mechflow_gui import configurations as C
    C.add_parameter(d, "Box.Length")
    C.add_configuration(d, "Short", {"Box.Length": 10})
    C.add_configuration(d, "Long", {"Box.Length": 50})
    Gui.ActiveDocument.ActiveView.viewIsometric(); Gui.SendMsgToActiveView("ViewFit")
at(setup, 1500)


def keys():
    from mechflow_gui import motion as M
    d = S["d"]
    st = M.create(d, "Grow"); S["st"] = st
    M.add_key(st, 0, config="Short", camera=M.camera_preset(d, "iso", fov=40))
    M.add_key(st, 1.0, values={"Box.Height": 30}, ease="linear")
    M.add_key(st, 2.0, config="Long", camera=M.camera_preset(d, "aft_iso", fov=20), turns=1)
    data = M.load(st)
    log("keys", len(data["keys"]), "duration", st.Duration)
    v = M.values_at(d, data, 1.0)
    log("length at 1.0", round(v["Box.Length"], 2), "height at 1.0", v.get("Box.Height"))
    v = M.values_at(d, data, 0.5)
    log("height at 0.5 (linear)", round(v["Box.Height"], 2))
    c0, c1, cm = M.camera_at(data, 0), M.camera_at(data, 2), M.camera_at(data, 1)
    log("fov 0/1/2", round(c0["fov"], 1), round(cm["fov"], 1), round(c1["fov"], 1))
    M.apply(d, data, 2.0)
    log("box length after apply 2.0", d.Box.Length.Value)
    cam = M.current_camera()
    log("camera fov applied", round(cam.get("fov", 0), 1))
    # an App::Part's origin axes are infinite: presets must ignore them
    d.addObject("App::Part", "Container"); d.recompute()
    pre = M.camera_preset(d, "iso")
    log("preset with App::Part finite", max(abs(x) for x in pre["pos"]) < 1e6)
    d.removeObject("Container"); d.recompute()
at(keys, 500)


def panel():
    from mechflow_gui import motion as M
    p = M.show(S["st"]); S["p"] = p
    log("panel rows", p.table.rowCount())
    p._go(1.5)
    log("scrub 1.5 length", round(S["d"].Box.Length.Value, 2))
    p._play_pause()
at(panel, 500)


def stop():
    p = S["p"]
    log("played to", round(p.t, 2), "playing", p.playing)
    p._stop()
    log("stopped at", p.t)
at(stop, 1200)


def export():
    from mechflow_gui import motion as M
    d, st = S["d"], S["st"]
    data = M.load(st); data.update(width=320, height=180, fps=10); M.save(st, data)
    out, msg = M.export(d, st, OUT + "motion_test.mp4")
    log("export", os.path.basename(out), os.path.isfile(OUT + "motion_test.mp4"), msg[:60])
    out2, msg2 = M.export(d, st, OUT + "frames_only", frames_dir=OUT + "motion_frames")
    log("frames", len([f for f in os.listdir(OUT + "motion_frames") if f.endswith(".png")]))
    S["p"].accept()
    d.saveAs(OUT + "motion_test.FCStd")
    App.closeDocument(d.Name)
    d2 = App.openDocument(OUT + "motion_test.FCStd")
    sts = M.studies(d2)
    log("reopened studies", len(sts), "keys", len(M.load(sts[0])["keys"]),
        "proxy", type(sts[0].Proxy).__name__)
at(export, 800)
run()
