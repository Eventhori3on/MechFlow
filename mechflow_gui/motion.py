# SPDX-License-Identifier: LGPL-2.1-or-later
"""Motion Study (SOLIDWORKS Animation, for FreeCAD).

A Motion Study is a timeline of keyframes kept in the document. A keyframe
sets model values at a time - any numeric parameter ("Lift.Z", a sketch
dimension, "Pad.Length"), or a whole configuration from the Design Table -
and can also hold a camera (position, target, field of view, perspective or
orthographic). Between keyframes values are eased (smooth, linear or hold)
and the camera glides round its target; a key's Turns adds whole orbits on
the way to it.

Play it in the view, scrub the timeline, and export it as an MP4 (needs
ffmpeg - on the PATH or set in the panel) or as numbered PNG frames.

Scripting::

    from mechflow_gui import motion as M
    st = M.create(doc, "Lift sequence")
    M.add_key(st, 0, config="Level 6 (-1290)", camera=M.camera_preset(doc, "iso"))
    M.add_key(st, 2, values={"Lift.TreadExt": 1})
    M.export(doc, st, "C:/out/lift.mp4")
"""

import json
import math
import os
import shutil
import subprocess
import tempfile
import time

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector
EASES = ("smooth", "linear", "hold")
PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/MechFlow"


# ------------------------------------------------------------ the study object

class MotionStudy:
    def __init__(self, obj):
        obj.Proxy = self
        if not hasattr(obj, "MechFlowMotionStudy"):
            obj.addProperty("App::PropertyBool", "MechFlowMotionStudy", "Base", "", 4)
            obj.MechFlowMotionStudy = True
            obj.addProperty("App::PropertyString", "StudyData", "Motion", "Keyframes (JSON)")
            obj.setEditorMode("StudyData", 2)
            obj.addProperty("App::PropertyFloat", "Duration", "Motion", "Length of the study (s)")
            obj.setEditorMode("Duration", 1)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderMotionStudy:
    def __init__(self, vobj):
        vobj.Proxy = self

    def getIcon(self):
        from mechflow_gui import icon_path
        return icon_path("MotionStudy.svg")

    def attach(self, vobj):
        self.Object = vobj.Object

    def doubleClicked(self, vobj):
        show(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_study(o):
    return getattr(o, "MechFlowMotionStudy", False)


def studies(doc):
    return [o for o in doc.Objects if is_study(o)]


def default_data():
    return {"fps": 30, "width": 1920, "height": 1080, "background": "Current",
            "params": [], "keys": []}


def create(doc, name="Motion Study"):
    o = doc.addObject("App::FeaturePython", "MotionStudy")
    MotionStudy(o)
    if App.GuiUp:
        ViewProviderMotionStudy(o.ViewObject)
    o.Label = name
    save(o, default_data())
    return o


def load(study):
    try:
        d = json.loads(study.StudyData or "{}")
    except Exception:
        d = {}
    base = default_data()
    base.update(d)
    return base


def save(study, data):
    data["keys"].sort(key=lambda k: k["t"])
    study.StudyData = json.dumps(data)
    study.Duration = duration(data)


def duration(data):
    return max([k["t"] for k in data["keys"]] or [0.0])


def add_key(study, t, values=None, config=None, camera=None, ease="smooth", turns=0, label=""):
    """Add (or merge into) a keyframe at time t (seconds)."""
    data = load(study)
    k = next((k for k in data["keys"] if abs(k["t"] - t) < 1e-6), None)
    if k is None:
        k = {"t": float(t), "ease": ease, "turns": turns, "label": label}
        data["keys"].append(k)
    else:
        k["ease"], k["turns"] = ease, turns or k.get("turns", 0)
        k["label"] = label or k.get("label", "")
    if values:
        k.setdefault("values", {}).update(values)
        for p in values:
            if p not in data["params"]:
                data["params"].append(p)
    if config:
        k["config"] = config
    if camera:
        k["camera"] = camera
    save(study, data)
    return k


# ------------------------------------------------------------ evaluating

def _ease(u, kind):
    u = max(0.0, min(1.0, u))
    if kind == "linear":
        return u
    if kind == "hold":
        return 1.0 if u >= 1.0 else 0.0
    return 0.5 - 0.5 * math.cos(math.pi * u)


def key_values(doc, key):
    """{param: value} a keyframe sets (its configuration's row, then its own values)."""
    out = {}
    if key.get("config"):
        from mechflow_gui import configurations as C
        sh = C.table(doc)
        if sh is not None:
            for p, v in C.row_values(sh, key["config"]).items():
                if v is not None and v != "":
                    out[p] = v
    out.update(key.get("values", {}))
    return out


def _num(v):
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def values_at(doc, data, t):
    """{param: value} at time t."""
    tracks = {}
    for k in sorted(data["keys"], key=lambda k: k["t"]):
        for p, v in key_values(doc, k).items():
            tracks.setdefault(p, []).append((k["t"], v, k.get("ease", "smooth")))
    out = {}
    for p, pts in tracks.items():
        if t <= pts[0][0]:
            out[p] = pts[0][1]
            continue
        if t >= pts[-1][0]:
            out[p] = pts[-1][1]
            continue
        for (t0, v0, _e0), (t1, v1, e1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                a, b = _num(v0), _num(v1)
                u = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
                if a is None or b is None:
                    out[p] = v1 if u >= 1.0 else v0
                else:
                    out[p] = a + (b - a) * _ease(u, e1)
                break
    return out


def _sph(off):
    d = off.Length
    az = math.degrees(math.atan2(off.y, off.x))
    el = math.degrees(math.asin(max(-1.0, min(1.0, off.z / d)))) if d > 1e-9 else 0.0
    return az, el, d


def _from_sph(az, el, d):
    a, e = math.radians(az), math.radians(el)
    return V(d * math.cos(e) * math.cos(a), d * math.cos(e) * math.sin(a), d * math.sin(e))


def camera_at(data, t):
    cams = [k for k in sorted(data["keys"], key=lambda k: k["t"]) if k.get("camera")]
    if not cams:
        return None
    if t <= cams[0]["t"]:
        return dict(cams[0]["camera"])
    if t >= cams[-1]["t"]:
        return dict(cams[-1]["camera"])
    for A, B in zip(cams, cams[1:]):
        if A["t"] <= t <= B["t"]:
            u = _ease((t - A["t"]) / (B["t"] - A["t"]) if B["t"] > A["t"] else 1.0,
                      B.get("ease", "smooth"))
            ca, cb = A["camera"], B["camera"]
            ta, tb = V(*ca["target"]), V(*cb["target"])
            tgt = ta + (tb - ta) * u
            aa, ea, da = _sph(V(*ca["pos"]) - ta)
            ab, eb, db = _sph(V(*cb["pos"]) - tb)
            dz = (ab - aa + 180.0) % 360.0 - 180.0 + 360.0 * B.get("turns", 0)
            pos = tgt + _from_sph(aa + dz * u, ea + (eb - ea) * u, da + (db - da) * u)
            out = {"pos": tuple(pos), "target": tuple(tgt),
                   "fov": ca.get("fov", 45) + (cb.get("fov", 45) - ca.get("fov", 45)) * u,
                   "type": cb.get("type", "Perspective") if u >= 1.0 else ca.get("type", "Perspective")}
            if "height" in ca or "height" in cb:
                ha, hb = ca.get("height", cb.get("height")), cb.get("height", ca.get("height"))
                out["height"] = ha + (hb - ha) * u
            return out
    return dict(cams[-1]["camera"])


# ------------------------------------------------------------ cameras

def current_camera(view=None):
    view = view or Gui.ActiveDocument.ActiveView
    cam = view.getCameraNode()
    pos = V(*cam.position.getValue().getValue())
    rot = App.Rotation(*cam.orientation.getValue().getValue())
    fd = cam.focalDistance.getValue()
    d = rot.multVec(V(0, 0, -1))
    out = {"pos": tuple(pos), "target": tuple(pos + d * fd), "type": view.getCameraType()}
    if hasattr(cam, "heightAngle"):
        out["fov"] = math.degrees(cam.heightAngle.getValue())
    if hasattr(cam, "height"):
        out["height"] = cam.height.getValue()
        out.setdefault("fov", 45.0)
    return out


def apply_camera(cam, view=None):
    view = view or Gui.ActiveDocument.ActiveView
    want = cam.get("type", "Perspective")
    if view.getCameraType() != want:
        view.setCameraType(want)
    node = view.getCameraNode()
    pos, tgt = V(*cam["pos"]), V(*cam["target"])
    d = tgt - pos
    dist = d.Length or 1.0
    d.normalize()
    up = V(0, 0, 1)
    if abs(d.dot(up)) > 0.999:
        up = V(0, 1, 0)
    zc = d * -1
    xc = up.cross(zc)
    xc.normalize()
    yc = zc.cross(xc)
    m = App.Matrix(xc.x, yc.x, zc.x, 0, xc.y, yc.y, zc.y, 0, xc.z, yc.z, zc.z, 0, 0, 0, 0, 1)
    q = App.Rotation(m).Q
    node.position.setValue(pos.x, pos.y, pos.z)
    node.orientation.setValue(q[0], q[1], q[2], q[3])
    node.focalDistance.setValue(dist)
    if hasattr(node, "heightAngle"):
        node.heightAngle.setValue(math.radians(cam.get("fov", 45.0)))
    if hasattr(node, "height") and "height" in cam:
        node.height.setValue(cam["height"])


def camera_preset(doc, name="iso", fov=40.0, dist_factor=1.6, target=None):
    """A camera looking at the whole model: iso, front, right, top, aft_iso."""
    bb = App.BoundBox()
    for o in doc.Objects:
        # origin planes and axes (every App::Part and Body has them) are infinite
        if o.TypeId in ("App::Origin", "App::Line", "App::Plane", "App::Point"):
            continue
        try:
            if hasattr(o, "Shape") and o.ViewObject.Visibility and o.Shape.BoundBox.isValid() \
                    and o.Shape.BoundBox.DiagonalLength < 1e9:
                bb.add(o.Shape.BoundBox)
        except Exception:
            pass
    c = V(*target) if target else (bb.Center if bb.isValid() else V())
    dirs = {"iso": V(1, -1, 0.8), "aft_iso": V(-1, -1, 0.8), "front": V(0, -1, 0.05),
            "right": V(1, 0, 0.05), "top": V(0.001, -0.001, 1)}
    d = dirs.get(name, V(1, -1, 0.8))
    d.normalize()
    r = (bb.DiagonalLength / 2 if bb.isValid() else 1000) / math.tan(math.radians(fov / 2))
    return {"pos": tuple(c + d * r * dist_factor / 1.6), "target": tuple(c), "fov": fov,
            "type": "Perspective"}


# ------------------------------------------------------------ playing

def apply(doc, data, t, view=None, camera=True):
    from mechflow_gui import configurations as C
    errs = []
    for p, v in values_at(doc, data, t).items():
        e = C.set_value(doc, p, v)
        if e:
            errs.append(e)
    doc.recompute()
    if camera and App.GuiUp:
        cam = camera_at(data, t)
        if cam:
            apply_camera(cam, view)
    return errs


def ffmpeg_path():
    p = App.ParamGet(PARAM_PATH).GetString("FFmpeg", "")
    if p and os.path.isfile(p):
        return p
    w = shutil.which("ffmpeg")
    if w:
        return w
    for cand in (r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                 os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links",
                              "ffmpeg.exe")):
        if cand and os.path.isfile(cand):
            return cand
    return None


def export(doc, study, path, view=None, progress=None, frames_dir=None, first=0, last=None,
           encode=True):
    """Render the study frame by frame and make an MP4 at path (with ffmpeg),
    or leave numbered PNGs. first/last render part of the frames (a long study
    can be split across sessions); frames already in frames_dir are kept.
    Returns (output path, message)."""
    data = load(study)
    view = view or Gui.ActiveDocument.ActiveView
    fps = int(data.get("fps", 30))
    w, h = int(data.get("width", 1920)), int(data.get("height", 1080))
    bg = data.get("background", "Current")
    dur = duration(data)
    n = max(1, int(round(dur * fps)) + 1)
    folder = frames_dir or tempfile.mkdtemp(prefix="mechflow_motion_")
    os.makedirs(folder, exist_ok=True)
    stop = n if last is None else min(n, last + 1)
    for i in range(first, stop):
        f = os.path.join(folder, f"frame_{i:05d}.png")
        if frames_dir and os.path.isfile(f):
            continue
        t = i / fps
        apply(doc, data, t, view)
        Gui.updateGui()
        view.saveImage(f, w, h, bg)
        if progress and not progress(i + 1, n):
            return folder, "Stopped - frames so far are in " + folder
    if not encode or len([x for x in os.listdir(folder) if x.startswith("frame_")]) < n:
        return folder, f"Frames {first}-{stop - 1} of {n} saved in {folder}."
    ff = ffmpeg_path()
    if not ff or not path.lower().endswith((".mp4", ".mov", ".mkv", ".gif")):
        return folder, (f"{n} frames saved in {folder}." +
                        ("" if ff else " Install ffmpeg (or set its path in the panel) to "
                         "make an MP4 directly."))
    if path.lower().endswith(".gif"):
        cmd = [ff, "-y", "-framerate", str(fps), "-i", os.path.join(folder, "frame_%05d.png"),
               "-vf", "fps=15,scale=960:-1:flags=lanczos", path]
    else:
        cmd = [ff, "-y", "-framerate", str(fps), "-i", os.path.join(folder, "frame_%05d.png"),
               "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-movflags", "+faststart", path]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return folder, f"ffmpeg failed ({e}); frames are in {folder}"
    if r.returncode != 0 or not os.path.isfile(path):
        return folder, "ffmpeg failed: " + (r.stderr or "")[-400:]
    if not frames_dir:
        shutil.rmtree(folder, ignore_errors=True)
    return path, f"Saved {path} ({dur:.1f} s, {n} frames, {w}x{h})."


# ------------------------------------------------------------ panel

class MotionPanel:
    """Timeline, keyframes and export, as a task panel."""

    COLS = ("Time (s)", "Ease", "Sets", "Camera", "Turns")

    def __init__(self, doc, study=None):
        self.doc = doc
        self.study = study or (studies(doc)[0] if studies(doc) else create(doc))
        self.t = 0.0
        self.playing = False
        self._busy = False
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._tick)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Motion Study")
        lay = QtWidgets.QVBoxLayout(self.form)
        top = QtWidgets.QHBoxLayout()
        self.combo = QtWidgets.QComboBox()
        self.combo.currentIndexChanged.connect(self._pick_study)
        top.addWidget(self.combo, 1)
        nb = QtWidgets.QPushButton("New")
        nb.clicked.connect(self._new_study)
        top.addWidget(nb)
        lay.addLayout(top)
        # timeline
        tl = QtWidgets.QHBoxLayout()
        self.play_b = QtWidgets.QPushButton("Play")
        self.play_b.clicked.connect(self._play_pause)
        tl.addWidget(self.play_b)
        sb = QtWidgets.QPushButton("Stop")
        sb.clicked.connect(self._stop)
        tl.addWidget(sb)
        self.loop = QtWidgets.QCheckBox("Loop")
        tl.addWidget(self.loop)
        self.tlabel = QtWidgets.QLabel("0.0 s")
        tl.addWidget(self.tlabel)
        lay.addLayout(tl)
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self._scrub)
        lay.addWidget(self.slider)
        # keys
        lay.addWidget(QtWidgets.QLabel("<b>Keyframes</b> - double-click a time to go there"))
        self.table = QtWidgets.QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellChanged.connect(self._cell_changed)
        self.table.cellDoubleClicked.connect(self._goto_row)
        lay.addWidget(self.table, 1)
        g = QtWidgets.QGridLayout()
        for i, (text, fn) in enumerate((("Key from model", self._key_model),
                                        ("Key from configuration...", self._key_config),
                                        ("Camera from view", self._key_camera),
                                        ("Clear camera", self._clear_camera),
                                        ("Update key from model", self._update_key),
                                        ("Delete key", self._delete_key),
                                        ("Parameters...", self._params),
                                        ("Shift keys after...", self._shift))):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        lay.addLayout(g)
        cam = QtWidgets.QHBoxLayout()
        cam.addWidget(QtWidgets.QLabel("Field of view"))
        self.fov = QtWidgets.QDoubleSpinBox()
        self.fov.setRange(5, 120)
        self.fov.setSuffix(" deg")
        self.fov.setValue(45)
        cam.addWidget(self.fov)
        fb = QtWidgets.QPushButton("Set on key")
        fb.clicked.connect(self._set_fov)
        cam.addWidget(fb)
        lay.addLayout(cam)
        # export
        ex = QtWidgets.QGroupBox("Export")
        el = QtWidgets.QGridLayout(ex)
        self.res = QtWidgets.QComboBox()
        self.res.addItems(["1280 x 720", "1920 x 1080", "2560 x 1440", "3840 x 2160", "1080 x 1080"])
        el.addWidget(QtWidgets.QLabel("Size"), 0, 0)
        el.addWidget(self.res, 0, 1)
        self.fps = QtWidgets.QSpinBox()
        self.fps.setRange(10, 60)
        el.addWidget(QtWidgets.QLabel("Frames/s"), 0, 2)
        el.addWidget(self.fps, 0, 3)
        self.bg = QtWidgets.QComboBox()
        self.bg.addItems(["Current", "White", "Black", "Transparent"])
        el.addWidget(QtWidgets.QLabel("Background"), 1, 0)
        el.addWidget(self.bg, 1, 1)
        ffb = QtWidgets.QPushButton("ffmpeg...")
        ffb.clicked.connect(self._set_ffmpeg)
        el.addWidget(ffb, 1, 2)
        xb = QtWidgets.QPushButton("Export video...")
        xb.clicked.connect(self._export)
        el.addWidget(xb, 1, 3)
        lay.addWidget(ex)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        lay.addWidget(self.msg)
        self._fill_combo()
        self._refresh()

    # -- study list
    def _fill_combo(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        for s in studies(self.doc):
            self.combo.addItem(s.Label, s.Name)
        i = self.combo.findData(self.study.Name)
        self.combo.setCurrentIndex(max(0, i))
        self.combo.blockSignals(False)

    def _pick_study(self, i):
        o = self.doc.getObject(self.combo.itemData(i))
        if o:
            self.study = o
            self._refresh()

    def _new_study(self):
        name, ok = QtWidgets.QInputDialog.getText(self.form, "New Motion Study", "Name:",
                                                  text=f"Motion Study {len(studies(self.doc)) + 1}")
        if ok and name.strip():
            self.study = create(self.doc, name.strip())
            self._fill_combo()
            self._refresh()

    # -- table
    def _data(self):
        return load(self.study)

    def _refresh(self):
        d = self._data()
        self.table.blockSignals(True)
        self.table.setRowCount(len(d["keys"]))
        for r, k in enumerate(d["keys"]):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(f"{k['t']:.2f}"))
            cb = QtWidgets.QComboBox()
            cb.addItems(EASES)
            cb.setCurrentText(k.get("ease", "smooth"))
            cb.currentTextChanged.connect(lambda txt, row=r: self._set_field(row, "ease", txt))
            self.table.setCellWidget(r, 1, cb)
            sets = k.get("label") or ""
            if not sets:
                bits = ([f"[{k['config']}]"] if k.get("config") else []) + \
                       [f"{p.split('.')[-1]}={v:g}" if isinstance(v, (int, float)) else f"{p}={v}"
                        for p, v in k.get("values", {}).items()]
                sets = ", ".join(bits)
            it = QtWidgets.QTableWidgetItem(sets)
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            it.setToolTip(json.dumps({x: k[x] for x in ("config", "values") if x in k}, indent=1))
            self.table.setItem(r, 2, it)
            c = k.get("camera")
            ci = QtWidgets.QTableWidgetItem(f"{c.get('type', 'P')[0]} {c.get('fov', 45):.0f} deg"
                                            if c else "")
            ci.setFlags(ci.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 3, ci)
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(str(k.get("turns", 0))))
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)
        dur = duration(d)
        self.slider.blockSignals(True)
        self.slider.setRange(0, int(dur * 100))
        self.slider.setValue(int(self.t * 100))
        self.slider.blockSignals(False)
        self.fps.setValue(int(d.get("fps", 30)))
        self.res.setCurrentText(f"{d.get('width', 1920)} x {d.get('height', 1080)}")
        self.bg.setCurrentText(d.get("background", "Current"))
        self.tlabel.setText(f"{self.t:.1f} / {dur:.1f} s")

    def _row(self):
        r = self.table.currentRow()
        d = self._data()
        return (r, d) if 0 <= r < len(d["keys"]) else (None, d)

    def _set_field(self, row, field, val):
        d = self._data()
        if 0 <= row < len(d["keys"]):
            d["keys"][row][field] = val
            save(self.study, d)

    def _cell_changed(self, r, c):
        d = self._data()
        if not (0 <= r < len(d["keys"])):
            return
        txt = self.table.item(r, c).text()
        try:
            if c == 0:
                d["keys"][r]["t"] = max(0.0, float(txt))
            elif c == 4:
                d["keys"][r]["turns"] = int(float(txt))
        except ValueError:
            pass
        save(self.study, d)
        self._refresh()

    def _goto_row(self, r, c):
        d = self._data()
        if 0 <= r < len(d["keys"]) and c == 0:
            self._go(d["keys"][r]["t"])

    # -- keys
    def _next_time(self):
        return round(self.t if self.t > 0 or not self._data()["keys"]
                     else duration(self._data()) + 2.0, 2)

    def _key_model(self):
        from mechflow_gui import configurations as C
        d = self._data()
        if not d["params"]:
            sh = C.table(self.doc)
            d["params"] = C.columns(sh) if sh else []
            save(self.study, d)
            if not d["params"]:
                self.msg.setText("Pick what to animate first: <b>Parameters...</b>")
                return
        vals = {p: C.value_of(self.doc, p) for p in d["params"]}
        add_key(self.study, self._next_time(), values=vals)
        self._refresh()

    def _key_config(self):
        from mechflow_gui import configurations as C
        sh = C.table(self.doc)
        names = C.configurations(sh) if sh else []
        if not names:
            self.msg.setText("This document has no configurations.")
            return
        n, ok = QtWidgets.QInputDialog.getItem(self.form, "Key from configuration",
                                               "Configuration:", names, 0, False)
        if ok:
            add_key(self.study, self._next_time(), config=n)
            self._refresh()

    def _key_camera(self):
        r, d = self._row()
        cam = current_camera()
        if r is None:
            add_key(self.study, self._next_time(), camera=cam)
        else:
            d["keys"][r]["camera"] = cam
            save(self.study, d)
        self._refresh()

    def _clear_camera(self):
        r, d = self._row()
        if r is not None:
            d["keys"][r].pop("camera", None)
            save(self.study, d)
            self._refresh()

    def _set_fov(self):
        r, d = self._row()
        if r is not None and d["keys"][r].get("camera"):
            d["keys"][r]["camera"]["fov"] = self.fov.value()
            save(self.study, d)
            self._refresh()

    def _update_key(self):
        from mechflow_gui import configurations as C
        r, d = self._row()
        if r is not None:
            d["keys"][r]["values"] = {p: C.value_of(self.doc, p) for p in d["params"]}
            d["keys"][r].pop("config", None)
            save(self.study, d)
            self._refresh()

    def _delete_key(self):
        r, d = self._row()
        if r is not None:
            d["keys"].pop(r)
            save(self.study, d)
            self._refresh()

    def _shift(self):
        r, d = self._row()
        if r is None:
            return
        dt, ok = QtWidgets.QInputDialog.getDouble(self.form, "Shift keys",
                                                  "Seconds to add to this key and later ones:",
                                                  1.0, -600, 600, 2)
        if ok:
            t0 = d["keys"][r]["t"]
            for k in d["keys"]:
                if k["t"] >= t0:
                    k["t"] = max(0.0, k["t"] + dt)
            save(self.study, d)
            self._refresh()

    def _params(self):
        from mechflow_gui import configurations as C
        dlg = QtWidgets.QDialog(self.form)
        dlg.setWindowTitle("Animated parameters")
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel("Tick the values 'Key from model' records."))
        lst = QtWidgets.QListWidget()
        d = self._data()
        have = set(d["params"])
        for key, desc, cur in C.parameters(self.doc):
            if not isinstance(cur, (int, float)) or isinstance(cur, bool):
                continue
            it = QtWidgets.QListWidgetItem(f"{desc} = {cur:g}")
            it.setData(QtCore.Qt.UserRole, key)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if key in have else QtCore.Qt.Unchecked)
            lst.addItem(it)
        v.addWidget(lst)
        b = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        b.accepted.connect(dlg.accept)
        b.rejected.connect(dlg.reject)
        v.addWidget(b)
        dlg.resize(520, 480)
        if dlg.exec():
            d["params"] = [lst.item(i).data(QtCore.Qt.UserRole) for i in range(lst.count())
                           if lst.item(i).checkState() == QtCore.Qt.Checked]
            save(self.study, d)

    # -- playback
    def _go(self, t):
        self.t = max(0.0, min(t, duration(self._data())))
        if self._busy:
            return
        self._busy = True
        try:
            apply(self.doc, self._data(), self.t)
        finally:
            self._busy = False
        self.slider.blockSignals(True)
        self.slider.setValue(int(self.t * 100))
        self.slider.blockSignals(False)
        self.tlabel.setText(f"{self.t:.1f} / {duration(self._data()):.1f} s")

    def _scrub(self, v):
        self._go(v / 100.0)

    def _play_pause(self):
        if self.playing:
            self.playing = False
            self.timer.stop()
            self.play_b.setText("Play")
            return
        if self.t >= duration(self._data()):
            self.t = 0.0
        self.playing = True
        self.play_b.setText("Pause")
        self._clock = time.time() - self.t
        self.timer.start(int(1000 / max(1, self._data().get("fps", 30))))

    def _tick(self):
        dur = duration(self._data())
        t = time.time() - self._clock
        if t > dur:
            if self.loop.isChecked():
                self._clock = time.time()
                t = 0.0
            else:
                self._go(dur)
                self._play_pause()
                return
        self._go(t)

    def _stop(self):
        if self.playing:
            self._play_pause()
        self._go(0.0)

    # -- export
    def _set_ffmpeg(self):
        f, _ = QtWidgets.QFileDialog.getOpenFileName(self.form, "Where is ffmpeg?", "",
                                                     "ffmpeg (ffmpeg*);;All files (*)")
        if f:
            App.ParamGet(PARAM_PATH).SetString("FFmpeg", f)
            self.msg.setText(f"Using {f}")

    def _export(self):
        d = self._data()
        w, h = (int(x) for x in self.res.currentText().split(" x "))
        d.update(width=w, height=h, fps=self.fps.value(), background=self.bg.currentText())
        save(self.study, d)
        ff = ffmpeg_path()
        f, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.form, "Export video", self.study.Label + (".mp4" if ff else ""),
            "MP4 video (*.mp4);;GIF (*.gif);;PNG frames folder (*)")
        if not f:
            return
        frames = None
        if not f.lower().endswith((".mp4", ".gif")):
            frames = f
        prog = QtWidgets.QProgressDialog("Rendering frames...", "Stop", 0, 100, self.form)
        prog.setWindowModality(QtCore.Qt.WindowModal)

        def step(i, n):
            prog.setMaximum(n)
            prog.setValue(i)
            QtWidgets.QApplication.processEvents()
            return not prog.wasCanceled()
        out, msg = export(self.doc, self.study, f, progress=step, frames_dir=frames)
        prog.close()
        self.msg.setText(msg)

    def accept(self):
        self.timer.stop()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close


def show(study=None):
    doc = App.ActiveDocument
    if doc is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Motion Study",
                                          "Finish the open dialog first.")
        return None
    p = MotionPanel(doc, study)
    Gui.Control.showDialog(p)
    return p


def restore(doc):
    """Re-attach proxies after a document is opened (FeaturePython)."""
    for o in doc.Objects:
        if is_study(o):
            if not isinstance(getattr(o, "Proxy", None), MotionStudy):
                MotionStudy(o)
            if App.GuiUp and not isinstance(getattr(o.ViewObject, "Proxy", None),
                                            ViewProviderMotionStudy):
                ViewProviderMotionStudy(o.ViewObject)
