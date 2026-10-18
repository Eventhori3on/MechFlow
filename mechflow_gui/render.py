# SPDX-License-Identifier: LGPL-2.1-or-later
"""Render: photo-style pictures of the model, like SOLIDWORKS' render tools.

* Quick Render - one click, a few seconds: MechFlow's own studio renderer
  (render_vtk.py, run with FreeCAD's Python, which ships VTK). Studio
  lighting, soft ground shadow, metal / paint / rubber / glass finishes
  picked from each part's material and colour.
* Motion Study videos can use the same studio look (motion.export).

Each part's finish is automatic (from its MechFlow material, its standard-
part type or its colour) unless picked in the Render panel; the choice is
kept on the part (MechFlowRenderFinish).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

V = App.Vector
PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
PROP = "MechFlowRenderFinish"
AUTO = "Automatic"
HERE = os.path.dirname(os.path.abspath(__file__))

# finish: base colour (None = the part's own colour), metallic, roughness,
# clear coat, opacity
FINISHES = {
    "Paint (gloss)":       dict(rgb=None, metal=0.0, rough=0.35, coat=0.35),
    "Paint (satin)":       dict(rgb=None, metal=0.0, rough=0.55, coat=0.1),
    "Powder coat":         dict(rgb=None, metal=0.0, rough=0.5, coat=0.2),
    "Plastic":             dict(rgb=None, metal=0.0, rough=0.4, coat=0.25),
    "Steel (bare)":        dict(rgb=(0.56, 0.57, 0.58), metal=1.0, rough=0.38),
    "Steel (machined)":    dict(rgb=(0.80, 0.81, 0.83), metal=1.0, rough=0.22),
    "Stainless (brushed)": dict(rgb=(0.78, 0.78, 0.80), metal=1.0, rough=0.30),
    "Galvanised":          dict(rgb=(0.70, 0.72, 0.74), metal=0.9, rough=0.50),
    "Aluminium":           dict(rgb=(0.91, 0.92, 0.93), metal=1.0, rough=0.30),
    "Cast iron":           dict(rgb=(0.28, 0.29, 0.31), metal=0.2, rough=0.65),
    "Chrome":              dict(rgb=(0.90, 0.90, 0.92), metal=1.0, rough=0.05),
    "Brass":               dict(rgb=(0.88, 0.70, 0.38), metal=1.0, rough=0.25),
    "Copper":              dict(rgb=(0.93, 0.60, 0.47), metal=1.0, rough=0.30),
    "Zinc plated":         dict(rgb=(0.78, 0.79, 0.76), metal=1.0, rough=0.30),
    "Black oxide":         dict(rgb=(0.12, 0.12, 0.13), metal=0.6, rough=0.45),
    "Rubber":              dict(rgb=(0.05, 0.05, 0.05), metal=0.0, rough=0.85),
    "Glass":               dict(rgb=(0.85, 0.92, 0.95), metal=0.0, rough=0.05, opacity=0.25),
    "See-through":         dict(rgb=None, metal=0.0, rough=0.4),
    "Timber":              dict(rgb=(0.60, 0.42, 0.26), metal=0.0, rough=0.70),
}
BACKDROPS = ("Studio dark", "Studio light", "White")
SIZES = ("Current view", "1280 x 720", "1920 x 1080", "2560 x 1440", "3840 x 2160")
QUALITY = {"Draft": 1, "Good": 2, "Best": 3}
_DEFAULT_GREYS = ((0.8, 0.8, 0.8), (0.62, 0.66, 0.72), (0.75, 0.76, 0.78), (0.80, 0.82, 0.85),
                  (0.678, 0.710, 0.741))


def _default_greys():
    """The colours a part has when nobody chose one (FreeCAD's default and MechFlow's)."""
    out = list(_DEFAULT_GREYS)
    try:
        u = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("DefaultShapeColor", 0)
        if u:
            out.append((((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0))
    except Exception:
        pass
    return out


# ------------------------------------------------------------ finishes

def _color(o):
    """The colour the part shows in the 3D view (0..1 RGB)."""
    for x in (o, _linked(o)):
        vo = getattr(x, "ViewObject", None)
        try:
            c = vo.ShapeColor
            return tuple(float(v) for v in c[:3])
        except Exception:
            pass
    return (0.8, 0.8, 0.8)


def _linked(o):
    try:
        return o.getLinkedObject(True) if o.TypeId == "App::Link" else o
    except Exception:
        return o


def _material_name(o):
    """MechFlow material of the part, or of the body / part it belongs to."""
    seen = [o, _linked(o)]
    for x in list(seen):
        try:
            p = x.getParentGeoFeatureGroup()
            if p is not None:
                seen.append(p)
        except Exception:
            pass
    for x in seen:
        n = getattr(x, "MechFlowMaterial", "")
        if n:
            return n.lower()
    return ""


def auto_finish(o):
    """The finish MechFlow picks for a part on its own."""
    x = _linked(o)
    t = (getattr(x, "StdType", "") or "").upper()
    if t.startswith("ISO15"):
        return "Steel (machined)"
    if t.startswith(("EN1514", "ASMEB16.21")):
        return "Rubber"
    if t.startswith(("EN1092", "ASMEB16.5", "EN10220", "EN10253", "ASMEB16.9", "ASMEB36")):
        return "Steel (bare)"
    tn = type(getattr(x, "Proxy", None)).__name__
    if tn == "FSScrewObject" or (x.Label[:4] in ("ISO ", "DIN ") and "×" not in x.Label):
        return "Zinc plated"
    try:
        if int(getattr(x.ViewObject, "Transparency", 0) or 0) >= 50:
            return "See-through"           # context drawn see-through: keep it that way
    except Exception:
        pass
    m = _material_name(o)
    for key, fin in (("stainless", "Stainless (brushed)"), ("alumin", "Aluminium"),
                     ("cast iron", "Cast iron"), ("gjl", "Cast iron"), ("gjs", "Cast iron"),
                     ("brass", "Brass"), ("bronze", "Brass"), ("copper", "Copper"),
                     ("rubber", "Rubber"), ("epdm", "Rubber"), ("neoprene", "Rubber"),
                     ("glass", "Glass"), ("acrylic", "Glass"), ("polycarbonate", "Glass"),
                     ("timber", "Timber"), ("wood", "Timber"), ("oak", "Timber"),
                     ("nylon", "Plastic"), ("pvc", "Plastic"), ("hdpe", "Plastic"),
                     ("polyprop", "Plastic"), ("plastic", "Plastic"), ("galvan", "Galvanised")):
        if key in m:
            return fin
    c = _color(o)
    if any(sum(abs(a - b) for a, b in zip(c, g)) < 0.06 for g in _default_greys()):
        return "Steel (bare)"          # left at the default colour: bare metal reads best
    return "Paint (gloss)"


def finish_name(o):
    x = _linked(o)
    for y in (o, x):
        n = getattr(y, PROP, "")
        if n in FINISHES:
            return n
    return auto_finish(o)


def set_finish(objs, name):
    """Give the parts a finish (AUTO goes back to the automatic choice)."""
    for o in objs:
        if PROP not in o.PropertiesList:
            o.addProperty("App::PropertyString", PROP, "MechFlow", "Render finish (blank: automatic)")
        setattr(o, PROP, "" if name == AUTO else name)


def _transparency(o):
    for x in (o, _linked(o)):
        try:
            return max(0, min(100, int(x.ViewObject.Transparency or 0)))
        except Exception:
            pass
    return 0


def look(o):
    """Renderer settings for a part: rgb, metal, rough, coat, opacity. A part
    the view shows see-through stays see-through, as much as the view shows."""
    f = dict(FINISHES[finish_name(o)])
    rgb = f.pop("rgb") or _color(o)
    opacity = f.get("opacity", 1.0)
    t = _transparency(o)
    if t:
        # a little firmer than the raw figure: the view's black edges and
        # flat shading make faint panels read better than PBR glass does
        opacity = min(opacity, max(0.1, 1.0 - t / 100.0) ** 0.8)
    return dict(rgb=list(rgb), metal=f.get("metal", 0.0), rough=f.get("rough", 0.5),
                coat=f.get("coat", 0.0), opacity=round(opacity, 3))


def gshape(o):
    """The part's shape where the 3D view draws it: with the placements of
    the App::Parts it sits in (Part.getShape alone leaves those out)."""
    import Part
    s = Part.getShape(o)
    try:
        gp = o.getGlobalPlacement()
        if not gp.isSame(o.Placement, 1e-9):
            s = s.copy()
            s.Placement = gp.multiply(o.Placement.inverse()).multiply(s.Placement)
    except Exception:
        pass
    return s


# ------------------------------------------------------------ what to draw

_SKIP = ("App::Origin", "App::Line", "App::Plane", "App::Point", "App::Part",
         "App::DocumentObjectGroup", "App::DocumentObjectGroupPython", "Spreadsheet::Sheet",
         "App::MaterialObjectPython", "App::MaterialObject")


def _shown(o):
    vo = getattr(o, "ViewObject", None)
    if vo is None or not vo.Visibility:
        return False
    for p in o.InList:
        if p.TypeId in ("App::Part", "App::DocumentObjectGroup") and o in getattr(p, "Group", []):
            if not p.ViewObject.Visibility:
                return False
            if not _shown_parent(p):
                return False
    return True


def _shown_parent(p):
    for q in p.InList:
        if q.TypeId in ("App::Part", "App::DocumentObjectGroup") and p in getattr(q, "Group", []):
            if not q.ViewObject.Visibility or not _shown_parent(q):
                return False
    return True


def leaves(doc):
    """The visible solids of the document, one per part (bodies, part
    features, MechFlow features, links)."""
    import Part
    out = []
    for o in doc.Objects:
        t = o.TypeId
        if t in _SKIP or t.startswith(("Sketcher::", "TechDraw::", "Fem::", "Mesh::", "Points::")):
            continue
        if o.isDerivedFrom("Part::Part2DObject"):
            continue
        try:
            p = o.getParentGeoFeatureGroup()
            if p is not None and p.TypeId == "PartDesign::Body":
                continue                       # a body's features: the body is drawn
        except Exception:
            pass
        if hasattr(o, "Group") and t not in ("App::Link", "PartDesign::Body"):
            continue                           # containers: their children are drawn
        if t != "App::Link" and not hasattr(o, "Shape"):
            continue
        if not _shown(o):
            continue
        try:
            s = gshape(o)
        except Exception:
            continue
        if s.isNull() or not s.Faces:
            continue
        out.append(o)
    return out


# ------------------------------------------------------------ scene

def _sig(s):
    try:
        return (round(s.Area, 1), round(s.Volume, 1) if s.Solids else 0.0)
    except Exception:
        return (0.0, 0.0)


def _mat16(p):
    m = p.toMatrix()
    return [m.A11, m.A12, m.A13, m.A14, m.A21, m.A22, m.A23, m.A24,
            m.A31, m.A32, m.A33, m.A34, 0.0, 0.0, 0.0, 1.0]


class Stopped(Exception):
    pass


class Scene:
    """The visible parts, meshed once; for animations, each frame gives each
    part's move (or a new mesh when its shape changed)."""

    def __init__(self, doc, folder, tick=None):
        """tick(i, n) -> False stops the meshing (raises Stopped)."""
        self.doc, self.dir = doc, folder
        os.makedirs(folder, exist_ok=True)
        self.objs = leaves(doc)
        bb = App.BoundBox()
        for o in self.objs:
            bb.add(gshape(o).BoundBox)
        self.bb = bb
        self.tol = max(0.02, bb.DiagonalLength / 4000.0) if bb.isValid() else 0.5
        self.base = {}                         # id -> (placement, signature, bbox centre)
        self.items = []
        for i, o in enumerate(self.objs):
            if tick and not tick(i, len(self.objs)):
                raise Stopped()
            s = gshape(o)
            path = self._mesh(i, s, 0)
            self.base[i] = (s.Placement, _sig(s), s.BoundBox.Center)
            d = look(o)
            d.update(id=i, mesh=path, label=o.Label)
            self.items.append(d)

    def _mesh(self, i, s, n):
        import MeshPart
        tol = min(self.tol, max(0.01, s.BoundBox.DiagonalLength / 150.0))
        m = MeshPart.meshFromShape(Shape=s, LinearDeflection=tol, AngularDeflection=0.35,
                                   Relative=False)
        path = os.path.join(self.dir, f"o{i}_{n}.obj")
        m.write(path)
        return path

    def frame(self, n):
        """Moves and new meshes for the model as it is now (frame n). Each
        part is drawn from the mesh made at its reference placement; a part
        whose shape changed (a rope getting longer) is meshed again."""
        import Part
        xf, meshes = {}, {}
        for i, o in enumerate(self.objs):
            try:
                s = gshape(o)
            except Exception:
                continue
            p0, sig0, c0 = self.base[i]
            delta = s.Placement.multiply(p0.inverse())
            if _sig(s) != sig0 or (delta.multVec(c0) - s.BoundBox.Center).Length > max(0.5, 2 * self.tol):
                meshes[str(i)] = self._mesh(i, s, n)
                self.base[i] = (s.Placement, _sig(s), s.BoundBox.Center)
                delta = App.Placement()
            xf[str(i)] = _mat16(delta)
        return xf, meshes


def camera_from_view(view=None):
    """The 3D view's camera, for the renderer."""
    view = view or Gui.ActiveDocument.ActiveView
    cam = view.getCameraNode()
    pos = V(*cam.position.getValue().getValue())
    rot = App.Rotation(*cam.orientation.getValue().getValue())
    fd = cam.focalDistance.getValue()
    d = rot.multVec(V(0, 0, -1))
    up = rot.multVec(V(0, 1, 0))
    tgt = pos + d * fd
    out = {"target": tuple(tgt), "up": tuple(up)}
    if view.getCameraType() == "Orthographic":
        out.update(projection="Orthographic", height=float(cam.height.getValue()),
                   pos=tuple(tgt - d * max(fd, 1.0) * 3))
    else:
        import math
        out.update(projection="Perspective", fov=math.degrees(cam.heightAngle.getValue()),
                   pos=tuple(pos))
    return out


def camera_from_motion(c):
    """A Motion Study camera ({pos, target, fov, type}) for the renderer."""
    pos, tgt = V(*c["pos"]), V(*c["target"])
    d = tgt - pos
    up = (0, 0, 1)
    if d.Length > 1e-9 and abs(d.normalize().z) > 0.999:
        up = (0, 1, 0)
    out = {"pos": tuple(pos), "target": tuple(tgt), "up": up, "fov": float(c.get("fov", 45.0))}
    if c.get("type") == "Orthographic":
        out.update(projection="Orthographic", height=float(c.get("height", 1000.0)))
    else:
        out["projection"] = "Perspective"
    return out


def python_exe():
    """FreeCAD's own Python (it ships VTK)."""
    home = App.getHomePath()
    for c in (os.path.join(home, "bin", "python.exe"), os.path.join(home, "bin", "python"),
              os.path.join(home, "bin", "python3")):
        if os.path.isfile(c):
            return c
    return shutil.which("python3") or shutil.which("python")


def run_job(job, folder, progress=None):
    """Run the studio renderer on a job. progress(i, n) -> False stops it.
    Returns (ok, message)."""
    path = os.path.join(folder, "job.json")
    json.dump(job, open(path, "w"))
    exe = python_exe()
    if not exe:
        return False, "FreeCAD's Python wasn't found, so the renderer can't run."
    env = dict(os.environ)
    env.pop("PYTHONHOME", None) if sys.platform.startswith("win") else None
    errf = open(os.path.join(folder, "render_errors.txt"), "w")    # VTK can be chatty: never a pipe
    try:
        p = subprocess.Popen([exe, os.path.join(HERE, "render_vtk.py"), path],
                             stdout=subprocess.PIPE, stderr=errf, text=True,
                             cwd=os.path.dirname(exe), env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        errf.close()
        return False, f"The renderer couldn't start ({e})."
    n = len(job["frames"])
    import threading
    lines = []

    def reader():
        for ln in p.stdout:
            lines.append(ln)
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    done = 0
    while p.poll() is None:
        while lines:
            ln = lines.pop(0)
            if ln.startswith("FRAME"):
                done = int(ln.split()[1])
        if progress and not progress(done, n):
            p.kill()
            return False, "Stopped."
        QtWidgets.QApplication.processEvents()
        time.sleep(0.05)
    th.join(1)
    errf.close()
    if p.returncode != 0:
        err = [x for x in open(errf.name).read().strip().splitlines() if x.strip()]
        return False, "The renderer stopped: " + (err[-1] if err else f"exit {p.returncode}")
    return True, "Done."


def size_for(choice, view=None):
    if choice == "Current view":
        try:
            w, h = (view or Gui.ActiveDocument.ActiveView).getSize()
            return 1920, max(2, int(round(1920 * h / max(1, w) / 2)) * 2)
        except Exception:
            return 1920, 1080
    w, h = (int(x) for x in choice.split(" x "))
    return w, h


def quick_render(doc, out, width=1920, height=1080, backdrop="Studio dark", quality="Good",
                 floor=True, exposure=1.2, camera=None, progress=None, meshing=None):
    """Render the model as the 3D view shows it into out (PNG). meshing(i, n)
    and progress(i, n) report the two stages; either returning False stops."""
    folder = tempfile.mkdtemp(prefix="mechflow_render_")
    camera = camera or camera_from_view()
    try:
        try:
            sc = Scene(doc, folder, meshing)
        except Stopped:
            return False, "Stopped."
        if not sc.items:
            return False, "Nothing to render: show some parts first."
        job = {"objects": sc.items,
               "frames": [{"out": out, "camera": camera}],
               "settings": {"width": width, "height": height, "supersample": QUALITY.get(quality, 2),
                            "backdrop": backdrop, "floor": floor, "bake": True,
                            "exposure": exposure}}
        ok, msg = run_job(job, folder, progress)
        return ok and os.path.isfile(out), (f"Saved {out}" if ok else msg)
    finally:
        if not os.environ.get("MECHFLOW_RENDER_KEEP"):
            shutil.rmtree(folder, ignore_errors=True)


def render_frames(doc, frames, settings, progress=None, folder=None):
    """For Motion Study: frames is a list of (apply(), camera, out path).
    Each apply() sets the model for that frame. Returns (ok, message)."""
    folder = folder or tempfile.mkdtemp(prefix="mechflow_motion_scene_")
    sc = None
    fr = []
    n = len(frames)
    for k, (setup, cam, out) in enumerate(frames):
        setup()
        if sc is None:
            sc = Scene(doc, folder)
            xf, meshes = {}, {}
        else:
            xf, meshes = sc.frame(k)
        fr.append({"out": out, "camera": cam, "xf": xf, "mesh": meshes})
        if progress and not progress(k + 1, 2 * n):
            return False, "Stopped."
    if sc is None or not sc.items:
        return False, "Nothing to render."
    s = dict(settings)
    s.update(bake=False)
    ok, msg = run_job({"objects": sc.items, "frames": fr, "settings": s}, folder,
                      (lambda i, m: progress(n + i, 2 * n)) if progress else None)
    shutil.rmtree(folder, ignore_errors=True)
    return ok, msg


# ------------------------------------------------------------ panel

class RenderPanel:
    """Render task panel: look, size, appearances, Render."""

    def __init__(self, doc):
        self.doc = doc
        self.p = App.ParamGet(PARAMS)
        self.last = None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Render")
        lay = QtWidgets.QVBoxLayout(self.form)
        head = QtWidgets.QLabel("<b>Render</b> - a studio picture of the model as the view shows "
                                "it. Set the view, pick the look, then Render.")
        head.setWordWrap(True)
        lay.addWidget(head)
        g = QtWidgets.QGroupBox("Look")
        gl = QtWidgets.QGridLayout(g)
        self.backdrop = QtWidgets.QComboBox()
        self.backdrop.addItems(BACKDROPS)
        self.backdrop.setCurrentText(self.p.GetString("RenderBackdrop", "Studio dark"))
        gl.addWidget(QtWidgets.QLabel("Backdrop"), 0, 0)
        gl.addWidget(self.backdrop, 0, 1)
        self.floor = QtWidgets.QCheckBox("Floor and shadow")
        self.floor.setChecked(self.p.GetBool("RenderFloor", True))
        gl.addWidget(self.floor, 0, 2)
        self.exposure = QtWidgets.QDoubleSpinBox()
        self.exposure.setRange(0.4, 3.0)
        self.exposure.setSingleStep(0.1)
        self.exposure.setValue(self.p.GetFloat("RenderExposure", 1.2))
        gl.addWidget(QtWidgets.QLabel("Brightness"), 1, 0)
        gl.addWidget(self.exposure, 1, 1)
        lay.addWidget(g)
        g2 = QtWidgets.QGroupBox("Image")
        g2l = QtWidgets.QGridLayout(g2)
        self.size = QtWidgets.QComboBox()
        self.size.addItems(SIZES)
        self.size.setCurrentText(self.p.GetString("RenderSize", "Current view"))
        g2l.addWidget(QtWidgets.QLabel("Size"), 0, 0)
        g2l.addWidget(self.size, 0, 1)
        self.quality = QtWidgets.QComboBox()
        self.quality.addItems(list(QUALITY))
        self.quality.setCurrentText(self.p.GetString("RenderQuality", "Good"))
        g2l.addWidget(QtWidgets.QLabel("Quality"), 1, 0)
        g2l.addWidget(self.quality, 1, 1)
        lay.addWidget(g2)
        g3 = QtWidgets.QGroupBox("Appearances")
        g3l = QtWidgets.QVBoxLayout(g3)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Parts", "Finish"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        self.table.setColumnWidth(1, 160)
        self.table.setTextElideMode(QtCore.Qt.ElideRight)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(180)
        g3l.addWidget(self.table)
        lay.addWidget(g3)
        row = QtWidgets.QHBoxLayout()
        self.go = QtWidgets.QPushButton("Render")
        self.go.setDefault(True)
        self.go.clicked.connect(self._render)
        row.addWidget(self.go)
        self.save_btn = QtWidgets.QPushButton("Save image...")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)
        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumHeight(160)
        lay.addWidget(self.preview)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        lay.addWidget(self.msg)
        self._fill_table()

    def _groups(self):
        groups = {}
        for o in leaves(self.doc):
            auto = getattr(o, PROP, "") not in FINISHES and getattr(_linked(o), PROP, "") not in FINISHES
            key = (finish_name(o), auto, tuple(round(c, 2) for c in _color(o)))
            groups.setdefault(key, []).append(o)
        return groups

    def _fill_table(self):
        self.groups = list(self._groups().items())
        self.table.setRowCount(len(self.groups))
        for r, ((fin, auto, rgb), objs) in enumerate(self.groups):
            name = objs[0].Label + (f"  (+{len(objs) - 1})" if len(objs) > 1 else "")
            it = QtWidgets.QTableWidgetItem(name)
            pm = QtGui.QPixmap(14, 14)
            pm.fill(QtGui.QColor.fromRgbF(*rgb))
            it.setIcon(QtGui.QIcon(pm))
            it.setToolTip("\n".join(o.Label for o in objs[:30]))
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            cb = QtWidgets.QComboBox()
            cb.addItem(f"{AUTO} ({auto_finish(objs[0])})", AUTO)
            for f in FINISHES:
                cb.addItem(f, f)
            cb.setCurrentIndex(0 if auto else cb.findData(fin))
            cb.currentIndexChanged.connect(lambda _i, row=r, box=cb: self._set(row, box))
            self.table.setCellWidget(r, 1, cb)

    def _set(self, row, box):
        objs = self.groups[row][1]
        self.doc.openTransaction("Render finish")
        set_finish(objs, box.currentData())
        self.doc.commitTransaction()

    def _remember(self):
        self.p.SetString("RenderBackdrop", self.backdrop.currentText())
        self.p.SetBool("RenderFloor", self.floor.isChecked())
        self.p.SetFloat("RenderExposure", self.exposure.value())
        self.p.SetString("RenderSize", self.size.currentText())
        self.p.SetString("RenderQuality", self.quality.currentText())

    def _render(self):
        self._remember()
        w, h = size_for(self.size.currentText())
        out = os.path.join(tempfile.gettempdir(), f"MechFlow render {int(time.time())}.png")
        self.msg.setText("Rendering...")
        self.go.setEnabled(False)
        dlg = QtWidgets.QProgressDialog("Preparing the parts...", "Cancel", 0, 100, Gui.getMainWindow())
        dlg.setWindowTitle("MechFlow Render")
        dlg.setWindowModality(QtCore.Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)
        dlg.show()
        QtWidgets.QApplication.processEvents()

        def meshing(i, n):
            dlg.setLabelText(f"Preparing the parts... {i} of {n}")
            dlg.setValue(int(60 * i / max(1, n)))
            QtWidgets.QApplication.processEvents()
            return not dlg.wasCanceled()

        t1 = [None]

        def rendering(i, n):
            t1[0] = t1[0] or time.time()
            dlg.setLabelText(f"Rendering {w} x {h}... {time.time() - t1[0]:.0f} s")
            dlg.setValue(60 + int(40 * i / max(1, n)))
            return not dlg.wasCanceled()
        t0 = time.time()
        try:
            ok, msg = quick_render(self.doc, out, w, h, self.backdrop.currentText(),
                                   self.quality.currentText(), self.floor.isChecked(),
                                   self.exposure.value(), progress=rendering, meshing=meshing)
        finally:
            dlg.close()
            dlg.deleteLater()
            self.go.setEnabled(True)
        if ok:
            self.last = out
            pm = QtGui.QPixmap(out)
            self.preview.setPixmap(pm.scaledToWidth(max(200, self.form.width() - 30),
                                                    QtCore.Qt.SmoothTransformation))
            self.save_btn.setEnabled(True)
            self.msg.setText(f"Rendered {w} x {h} in {time.time() - t0:.0f} s. Save it, or change "
                             "the view or finishes and render again.")
            show_image(out)
        else:
            self.msg.setText(msg)

    def _save(self):
        if not self.last:
            return
        base = (self.doc.FileName and os.path.splitext(self.doc.FileName)[0]) or self.doc.Label
        f, _ = QtWidgets.QFileDialog.getSaveFileName(self.form, "Save render", base + " render.png",
                                                     "PNG image (*.png);;JPEG image (*.jpg)")
        if f:
            if f.lower().endswith((".jpg", ".jpeg")):
                QtGui.QImage(self.last).save(f, "JPG", 95)
            else:
                shutil.copyfile(self.last, f)
            self.msg.setText(f"Saved {f}")

    def accept(self):
        self._remember()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        return self.accept()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close


def show_image(path):
    """The render in a window of its own, at a size that fits the screen."""
    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    dlg.setWindowTitle(os.path.basename(path))
    lay = QtWidgets.QVBoxLayout(dlg)
    lab = QtWidgets.QLabel()
    pm = QtGui.QPixmap(path)
    scr = QtWidgets.QApplication.primaryScreen().availableGeometry()
    lab.setPixmap(pm.scaled(int(scr.width() * 0.7), int(scr.height() * 0.7), QtCore.Qt.KeepAspectRatio,
                            QtCore.Qt.SmoothTransformation))
    lay.addWidget(lab)
    dlg.setModal(False)
    dlg.show()
    _WINDOWS.append(dlg)
    return dlg


_WINDOWS = []


def show():
    doc = App.ActiveDocument
    if doc is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Render", "Finish the open dialog first.")
        return None
    p = RenderPanel(doc)
    Gui.Control.showDialog(p)
    return p
