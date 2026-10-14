# Test harness helpers for running MechFlow inside FreeCAD's GUI under Xvfb.
# Each test queues steps with at(fn, wait_ms) and logs results to LOG;
# run_tests.sh runs every test and checks the logs.
import faulthandler, os, tempfile
OUT = os.environ.get("MF_OUT") or os.path.join(tempfile.gettempdir(), "mechflow-tests")
OUT = OUT.rstrip("/") + "/"
os.makedirs(OUT, exist_ok=True)
_fh = open(OUT + "fault.txt", "w")
faulthandler.enable(file=_fh, all_threads=False)
import FreeCAD as App, FreeCADGui as Gui, traceback, math
from PySide6 import QtCore, QtWidgets

LOG = os.environ.get("MF_LOG", OUT + "log.txt")
SHOTS = OUT + "shots/"
os.makedirs(SHOTS, exist_ok=True)
Q = []
CUR = {"p": None}


def log(*a):
    open(LOG, "a", encoding="utf-8").write(" ".join(map(str, a)) + "\n")


def at(f, w=400):
    Q.append((f, w))


def shot(name):
    Gui.getMainWindow().grab().save(SHOTS + name + ".png")


def install_hooks():
    # Never block on message boxes: log them instead.
    def box(kind):
        def f(parent, title, text, *a, **k):
            log(f"  [{kind} box] {title}: {text}")
            return QtWidgets.QMessageBox.Ok
        return f
    for k in ("information", "warning", "critical"):
        setattr(QtWidgets.QMessageBox, k, staticmethod(box(k)))
    from mechflow_gui import panel_base
    orig = panel_base.FeaturePanel.__init__

    def init(self, *a, **k):
        CUR["p"] = self
        orig(self, *a, **k)
    panel_base.FeaturePanel.__init__ = init
    # capture console warnings
    class Obs:
        def __init__(s): pass
    try:
        App.Console.SetStatus("Console", "Wrn", True)
    except Exception:
        pass


def P():
    return CUR["p"]


def sel(obj, sub=""):
    doc = obj.Document.Name
    if sub:
        Gui.Selection.addSelection(doc, obj.Name, sub)
    else:
        Gui.Selection.addSelection(doc, obj.Name)


def face_where(obj, pred):
    for i, f in enumerate(obj.Shape.Faces):
        try:
            if pred(f):
                return f"Face{i + 1}"
        except Exception:
            pass
    return None


def faces_where(obj, pred):
    return [f"Face{i + 1}" for i, f in enumerate(obj.Shape.Faces) if pred(f)]


def plane_face(f):
    return type(f.Surface).__name__ == "Plane"


def normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def new_body(doc, name):
    body = doc.addObject("PartDesign::Body", name)
    Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
    return body


def origin(body, prefix):
    return [f for f in body.Origin.OriginFeatures if f.Name.startswith(prefix)][0]


def sketch(body, plane_prefix, geos, offset=None, name="Sketch"):
    import Part
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = [(origin(body, plane_prefix), "")]
    sk.MapMode = "FlatFace"
    if offset is not None:
        sk.AttachmentOffset = offset
    for g in geos:
        sk.addGeometry(g)
    return sk


def rect(x0, y0, x1, y1):
    import Part
    V = App.Vector
    p = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    return [Part.LineSegment(p[i], p[(i + 1) % 4]) for i in range(4)]


def circle(x, y, r):
    import Part
    return [Part.Circle(App.Vector(x, y, 0), App.Vector(0, 0, 1), r)]


def state(tag, f=None):
    p = P()
    f = f or (p.feature if p else None)
    try:
        vol = round(f.Shape.Volume, 2) if f is not None and not f.Shape.isNull() else None
    except Exception:
        vol = None
    err = p.error.isVisible() if p is not None and hasattr(p, "error") else None
    log(f"{tag}: feat={f and f.Name} valid={f and f.isValid()} vol={vol} err={err}"
        + (f" errtext={p.error.text()[:120]!r}" if err else ""))
    return vol


def attach_xy(feat, body, x, y, z=0):
    feat.AttachmentSupport = [(origin(body, "XY_Plane"), "")]
    feat.MapMode = "FlatFace"
    feat.AttachmentOffset = App.Placement(App.Vector(x, y, z), App.Rotation())


def _watchdog():
    w = QtWidgets.QApplication.activeModalWidget()
    if w is not None:
        log(f"  !! modal open: {w.metaObject().className()} {w.windowTitle()!r}")
        try:
            for lab in w.findChildren(QtWidgets.QLabel):
                if lab.text():
                    log("     ", lab.text()[:200])
        except Exception:
            pass
        w.close()


def run():
    wd = QtCore.QTimer(); wd.setInterval(2000); wd.timeout.connect(_watchdog); wd.start()
    globals()["_wd"] = wd
    def step(i=0):
        if i >= len(Q):
            log("DONE")
            os._exit(0)
        f, w = Q[i]
        try:
            f()
        except Exception:
            log(traceback.format_exc())
        QtCore.QTimer.singleShot(w, lambda: step(i + 1))
    QtCore.QTimer.singleShot(1500, step)
