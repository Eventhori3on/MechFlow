"""Pipe from Scan (GUI): bring a 3D scan in, click a pipe in it, get a
MechFlow route of it - pipe, elbows and flanges in the pipe spec chosen.

Import Scan reads OBJ / STL / PLY meshes and XYZ-type point clouds of any
size: the whole scan is kept for measuring, a lighter copy is shown. Any
mesh or point cloud already in the document works too."""
import math
import os
import tempfile
import time

import numpy as np
import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

from mechflow_gui import scan, scan_match

V = App.Vector
SCAN_FILTER = ("3D scans (*.obj *.stl *.ply *.xyz *.asc *.txt *.pts *.csv);;"
               "Meshes (*.obj *.stl *.ply);;Point clouds (*.xyz *.asc *.txt *.pts *.csv);;"
               "All files (*)")
_SCANS = {}          # (document name, object name) -> scan.Scan
GOOD, CHECK = (0.20, 0.72, 0.32), (0.98, 0.66, 0.15)
BAD = (0.90, 0.25, 0.22)


def cache_dir():
    d = os.environ.get("MF_SCAN_CACHE") or os.path.join(App.getUserAppDataDir(),
                                                        "MechFlow Scan Cache")
    return d


def _colour(o, col):
    """Points objects take ShapeColor, Part shapes' vertices PointColor."""
    vo = o.ViewObject
    for prop in ("PointColor", "ShapeColor"):
        if prop in vo.PropertiesList:
            setattr(vo, prop, col)
            return
    if "ShapeAppearance" in vo.PropertiesList:          # Points in FreeCAD 1.x
        m = App.Material()
        m.DiffuseColor = col
        m.AmbientColor = col
        m.EmissiveColor = tuple(0.35 * c for c in col)
        vo.ShapeAppearance = (m,)


def _mw():
    try:
        return Gui.getMainWindow()
    except Exception:
        return None


class _Progress:
    """A progress dialog that keeps the window alive while a big scan loads."""

    def __init__(self, text, path=None):
        self.d = None
        try:
            small = path is not None and os.path.getsize(path) < 25e6
        except OSError:
            small = False
        if App.GuiUp and not small:                 # quick to read: no dialog
            self.d = QtWidgets.QProgressDialog(text, None, 0, 100, _mw())
            self.d.setWindowTitle("MechFlow")
            self.d.setWindowModality(QtCore.Qt.WindowModal)
            self.d.setMinimumDuration(0)
            self.d.setValue(0)
            self.d.show()
            QtWidgets.QApplication.processEvents()
        self.t = 0.0

    def step(self, frac, text=None):
        if self.d is None:
            return
        now = time.time()
        if text is None and now - self.t < 0.1:
            return
        self.t = now
        if text:
            self.d.setLabelText(text)
        self.d.setValue(int(max(0.0, min(1.0, frac)) * 100))
        QtWidgets.QApplication.processEvents()

    def close(self):
        if self.d is not None:
            self.d.setValue(self.d.maximum())          # done: stops it popping up again
            self.d.reset()
            self.d.close()
            self.d.deleteLater()
            self.d = None


# ------------------------------------------------------------------ scans

def is_scan(o):
    return o is not None and (o.isDerivedFrom("Mesh::Feature") or o.isDerivedFrom("Points::Feature"))


def scans_in(doc):
    return [o for o in (doc.Objects if doc else []) if is_scan(o)]


def _key(o):
    return (o.Document.Name, o.Name)


def show_scan(doc, sc, label, faces=2.0e6):
    """The object that shows a scan: a lighter copy of a mesh, or a thinned
    point cloud."""
    if sc.is_mesh:
        Vd, Fd = scan.light_mesh(sc.V.astype(np.float64), sc.F, faces=faces)
        import Mesh
        tmp = os.path.join(tempfile.gettempdir(), f"mechflow_scan_{os.getpid()}.stl")
        scan.write_stl(tmp, Vd, Fd)
        o = doc.addObject("Mesh::Feature", "Scan")
        o.Mesh = Mesh.Mesh(tmp)
        try:
            os.remove(tmp)
        except OSError:
            pass
    else:
        import Points
        P = sc.V
        if len(P) > 2000000:
            P = P[np.random.default_rng(1).choice(len(P), 2000000, replace=False)]
        pts = Points.Points()
        pts.addPoints([tuple(map(float, q)) for q in P])
        o = doc.addObject("Points::Feature", "Scan")
        o.Points = pts
    o.Label = label
    o.addProperty("App::PropertyFile", "ScanFile", "Scan", "The scan file (measured at full detail)")
    o.ScanFile = sc.source or ""
    if App.GuiUp:
        vo = o.ViewObject
        for prop, val in (("ShapeColor", (0.74, 0.77, 0.81)), ("Lighting", "Two side"),
                          ("PointSize", 2.0), ("Transparency", 45)):
            try:
                setattr(vo, prop, val)
            except Exception:
                pass
    return o


def import_scan(path=None):
    """File > Import Scan: read it, keep it, show a lighter copy."""
    doc = App.ActiveDocument or App.newDocument()
    if path is None:
        path, _f = QtWidgets.QFileDialog.getOpenFileName(_mw(), "Import Scan", "", SCAN_FILTER)
        if not path:
            return None
    pr = _Progress(f"Reading {os.path.basename(path)}...", path)
    try:
        sc = scan.load_scan(path, cache_dir(), lambda f: pr.step(0.8 * f))
        pr.step(0.85, "Making a lighter copy to show...")
        o = show_scan(doc, sc, os.path.splitext(os.path.basename(path))[0])
        _SCANS[_key(o)] = sc
        pr.step(0.95, "Finding the surfaces...")
        sc.cloud()
        doc.recompute()
    finally:
        pr.close()
    if App.GuiUp:
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass
    App.Console.PrintMessage(f"MechFlow: scan {os.path.basename(path)}: {len(sc.V):,} points"
                             + (f", {len(sc.F):,} triangles" if sc.is_mesh else "") + "\n")
    return o


def scan_of(o):
    """The full-detail Scan behind a scan object (read once per session)."""
    k = _key(o)
    if k in _SCANS:
        return _SCANS[k]
    path = getattr(o, "ScanFile", "")
    sc = None
    if path and os.path.exists(path):
        pr = _Progress(f"Reading {os.path.basename(path)}...", path)
        try:
            sc = scan.load_scan(path, cache_dir(), lambda f: pr.step(0.9 * f))
        finally:
            pr.close()
    elif o.isDerivedFrom("Mesh::Feature"):
        tmp = os.path.join(tempfile.gettempdir(), f"mechflow_mesh_{os.getpid()}.stl")
        m = o.Mesh.copy()
        m.Placement = App.Placement()                    # its own coordinates
        m.write(tmp)
        try:
            sc = scan.Scan(soup=scan.read_stl(tmp), source="")
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    elif o.isDerivedFrom("Points::Feature"):
        P = np.array([(q.x, q.y, q.z) for q in o.Points.Points], dtype=np.float64)
        sc = scan.Scan(P, None, None, None, "")
    if sc is None:
        raise ValueError(f"{o.Label} isn't a mesh or a point cloud")
    _SCANS[k] = sc
    return sc


def _local(o, p):
    """A point in the scan's own coordinates."""
    return np.array(tuple(o.Placement.inverse().multVec(V(*map(float, p)))))


def _global(o, p):
    return o.Placement.multVec(V(*map(float, p)))


# ------------------------------------------------------------------ panel

def _specs():
    from mechflow_gui import pipespec
    return pipespec.all_specs()


class ScanPanel:
    """Pipe from Scan: click a pipe, check what was found, OK makes it."""

    def __init__(self, scan_obj=None):
        self.doc = App.ActiveDocument
        self.scan_obj = scan_obj
        self.res = None
        self.plan = None
        self.pick = None
        self.preview = None
        self.extras = []                # fit points, warning markers (removed on close)
        self.raw = None                 # the trace as found, before the corrections
        self.skips = []                 # carry on past these (scan coordinates)
        self.trims = []                 # ends set here (scan coordinates)
        self.modes = {}                 # straight -> 'square' / 'measured'
        self.mode = "trace"             # what the next click on the scan does
        self.ext = [0.0, 0.0]           # ends moved out (+) / in (-) along their straights
        self.grips = [None, None]       # drag handles on the two ends
        self.pipe_len = [None, None]    # cut length of the pipe in each end straight
        self._seen = None
        self._busy = False
        self.form = self._build()
        self._fill_scans()
        Gui.Selection.clearSelection()
        self._picked = None
        self._obs = _PickObserver(self)
        Gui.Selection.addObserver(self._obs)
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._grip_timer = QtCore.QTimer()
        self._grip_timer.setInterval(60)
        self._grip_timer.timeout.connect(self._tick_grips)
        self._grip_settle = QtCore.QTimer()
        self._grip_settle.setSingleShot(True)
        self._grip_settle.setInterval(120)
        self._grip_settle.timeout.connect(lambda: self._replan(light=True))
        self._say()

    # -- layout
    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Pipe from Scan")
        try:
            from mechflow_gui import app_icon
            w.setWindowIcon(app_icon.icon())
        except Exception:
            pass
        lay = QtWidgets.QVBoxLayout(w)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QtWidgets.QHBoxLayout()
        self.scan_box = QtWidgets.QComboBox()
        self.scan_box.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.scan_box.setMinimumContentsLength(10)
        self.scan_box.currentIndexChanged.connect(self._scan_changed)
        row.addWidget(self.scan_box, 1)
        b = QtWidgets.QPushButton("Open...")
        b.setToolTip("Import a scan: OBJ, STL, PLY or an XYZ-type point cloud")
        b.clicked.connect(self._open)
        row.addWidget(b)
        lay.addLayout(row)
        self.found = QtWidgets.QTextBrowser()
        self.found.setOpenLinks(False)
        self.found.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.found.setMinimumHeight(230)
        self.found.setStyleSheet("QTextBrowser { background: transparent; }")
        lay.addWidget(self.found)
        fix = QtWidgets.QGroupBox("Correct it")
        fl = QtWidgets.QVBoxLayout(fix)
        brow = QtWidgets.QHBoxLayout()
        self.b_end = QtWidgets.QPushButton("Set an end...")
        self.b_end.setToolTip("Then click on the pipe in the scan: the line finishes there "
                              "(at whichever end is nearer)")
        self.b_end.setCheckable(True)
        self.b_end.clicked.connect(lambda on: self._set_mode("end" if on else "trace"))
        self.b_carry = QtWidgets.QPushButton("Carry on past...")
        self.b_carry.setToolTip("Then click where the line stopped wrongly (a clamp taken for a "
                                "flange, a gap, something in the way): it follows the pipe on "
                                "past there")
        self.b_carry.setCheckable(True)
        self.b_carry.clicked.connect(lambda on: self._set_mode("carry" if on else "trace"))
        self.b_undo = QtWidgets.QPushButton("Undo corrections")
        self.b_undo.clicked.connect(self._undo_fixes)
        for b_ in (self.b_end, self.b_carry, self.b_undo):
            brow.addWidget(b_)
        fl.addLayout(brow)
        lrow = QtWidgets.QHBoxLayout()
        lrow.addWidget(QtWidgets.QLabel("Pipe at start"))
        self.len_a = QtWidgets.QDoubleSpinBox()
        lrow.addWidget(self.len_a)
        lrow.addWidget(QtWidgets.QLabel("at end"))
        self.len_b = QtWidgets.QDoubleSpinBox()
        lrow.addWidget(self.len_b)
        for k, sp_ in enumerate((self.len_a, self.len_b)):
            sp_.setRange(0.0, 1e6)
            sp_.setDecimals(1)
            sp_.setSuffix(" mm")
            sp_.setKeyboardTracking(False)
            sp_.setToolTip("Cut length of the pipe in the end straight - the pipe itself, not "
                           "the elbow or flange. Type a length, or drag the orange grip on the "
                           "end of the line in the view")
            sp_.valueChanged.connect(lambda v, k=k: self.set_pipe_length(k, v))
            try:
                from mechflow_gui import sketch3d
                sketch3d.keep_enter(sp_)
            except Exception:
                pass
        fl.addLayout(lrow)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Straight", "Length", "Off square", "Make it"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setMinimumHeight(110)
        self.table.setToolTip("Each straight: Auto squares it up when it's within the angle "
                              "below of X, Y or Z; Square forces it; As measured keeps its "
                              "measured direction (the elbows either side are cut to suit)")
        fl.addWidget(self.table)
        frow = QtWidgets.QHBoxLayout()
        self.show_fit = QtWidgets.QCheckBox("Show the scan fit")
        self.show_fit.setToolTip("Colour the scan's points on the pipe by how far they are off "
                                 "the model's surface: green close, amber check, red far")
        self.show_fit.setChecked(True)
        self.show_fit.toggled.connect(self._replan)
        frow.addWidget(self.show_fit)
        frow.addStretch(1)
        self.b_report = QtWidgets.QPushButton("Save report...")
        self.b_report.setToolTip("A CSV of what was measured and how well it fits the scan")
        self.b_report.clicked.connect(self._save_report)
        frow.addWidget(self.b_report)
        fl.addLayout(frow)
        lay.addWidget(fix)
        g = QtWidgets.QGroupBox("Make it as")
        f = QtWidgets.QFormLayout(g)
        self.spec = QtWidgets.QComboBox()
        self.spec.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.spec.setMinimumContentsLength(10)
        self.spec.currentIndexChanged.connect(self._spec_changed)
        f.addRow("Pipe spec", self.spec)
        self.size = QtWidgets.QComboBox()
        f.addRow("Size", self.size)
        self.rating = QtWidgets.QComboBox()
        f.addRow("Flanges", self.rating)
        self.bend = QtWidgets.QComboBox()
        f.addRow("Elbows", self.bend)
        from mechflow_gui import routing
        self.end_a = QtWidgets.QComboBox()
        self.end_a.addItems(routing.ENDS)
        self.end_b = QtWidgets.QComboBox()
        self.end_b.addItems(routing.ENDS)
        f.addRow("Start finishes", self.end_a)
        f.addRow("End finishes", self.end_b)
        sq = QtWidgets.QHBoxLayout()
        self.square = QtWidgets.QCheckBox("Square to X/Y/Z within")
        self.square.setToolTip("Straights within this angle of X, Y or Z are made exactly "
                               "along it (pipework is usually built square)")
        self.square.setChecked(True)
        self.snap = QtWidgets.QDoubleSpinBox()
        self.snap.setRange(0.5, 15.0)
        self.snap.setValue(5.0)
        self.snap.setSuffix(" °")
        try:
            from mechflow_gui import sketch3d
            sketch3d.keep_enter(self.snap)
        except Exception:
            pass
        sq.addWidget(self.square)
        sq.addWidget(self.snap)
        sq.addStretch(1)
        f.addRow(sq)
        for wd in (self.size, self.rating, self.bend, self.end_a, self.end_b):
            wd.currentIndexChanged.connect(self._options_changed)
        self.square.toggled.connect(self._replan)
        self.snap.valueChanged.connect(self._replan)
        lay.addWidget(g)
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d0453a;")
        lay.addWidget(self.error)
        lay.addStretch(1)
        self._fill_specs()
        return w

    def _fill_scans(self, select=None):
        self.scan_box.blockSignals(True)
        self.scan_box.clear()
        objs = scans_in(self.doc)
        for o in objs:
            self.scan_box.addItem(o.Label, o.Name)
        want = select or self.scan_obj
        if want is None and objs:
            want = objs[0]
        if want is not None:
            i = self.scan_box.findData(want.Name)
            if i >= 0:
                self.scan_box.setCurrentIndex(i)
        self.scan_obj = want
        self.scan_box.blockSignals(False)

    def _fill_specs(self, keep=None):
        self.spec.blockSignals(True)
        self.spec.clear()
        for s in _specs():
            self.spec.addItem(s["name"])
        if keep:
            i = self.spec.findText(keep)
            if i >= 0:
                self.spec.setCurrentIndex(i)
        self.spec.blockSignals(False)
        self._spec_changed()

    def current_spec(self):
        from mechflow_gui import pipespec
        return pipespec.get(self.spec.currentText()) or _specs()[0]

    def _spec_changed(self, *_):
        from mechflow_gui import routing, stdparts
        sp = self.current_spec()
        std = sp["standard"]
        ty = routing.types_for(std, sp["bend"])
        for box, items in ((self.size, routing.sizes_for(std)),
                           (self.rating, stdparts.ratings(ty["flange"])),
                           (self.bend, routing.BENDS[std])):
            box.blockSignals(True)
            box.clear()
            box.addItems(items)
            box.blockSignals(False)
        self.rating.setCurrentText(sp["rating"])
        self.bend.setCurrentText(sp["bend"])
        self._replan()

    def _set_found(self, html):
        self.found.setHtml(html)

    # -- messages
    def _say(self, text=None):
        if text is None:
            if self.scan_obj is None:
                text = ("<b>Open a scan</b> (a mesh - OBJ, STL, PLY - or a point cloud), or "
                        "import one into the document first.")
            elif self.res is None:
                text = ("<b>Click the pipe</b> in the scan, on its wall. MechFlow follows it "
                        "both ways - through the elbows - to the flanges or wherever it "
                        "ends.<br>Work a section at a time: one line from flange to flange.")
            elif self.mode == "end":
                text = ("<b>Click the pipe where the line should finish</b> - the nearer end "
                        "moves there.")
            elif self.mode == "carry":
                text = ("<b>Click where the line stopped wrongly</b> - it follows the pipe on "
                        "past there.")
            else:
                text = ("Check what was found and correct it if need be - drag the orange "
                        "grips on the ends of the line, or type the pipe lengths, to set where "
                        "it finishes - pick how to make it, then <b>OK</b>. Click the scan "
                        "again to trace a different pipe.")
        self.msg.setText(text)

    # -- scans
    def _open(self):
        o = import_scan()
        if o is not None:
            self._fill_scans(o)
            self._scan_changed()

    def _scan_changed(self, *_):
        self._dim_scan(False)
        name = self.scan_box.currentData()
        self.scan_obj = self.doc.getObject(name) if name else None
        self.res = None
        self.raw = None
        self._clear_preview()
        self._say()

    # -- picking
    def _stop(self):
        self._timer.stop()
        try:
            Gui.Selection.removeObserver(self._obs)
        except Exception:
            pass

    def _poll(self):
        if self._busy or self.scan_obj is None:
            return
        # a click on the scan (the observer has the point even when a mesh is
        # selected whole, with no picked points in the selection)
        if self._picked is not None:
            name, p = self._picked
            self._picked = None
            if name == self.scan_obj.Name:
                key = (round(p.x, 2), round(p.y, 2), round(p.z, 2))
                if key != self._seen:
                    self._seen = key
                    Gui.Selection.clearSelection()
                    self.clicked(p)
                    return
        try:
            sel = Gui.Selection.getSelectionEx("", 0)
        except Exception:
            return
        for item in sel:
            if item.Object is not self.scan_obj:
                continue
            pts = list(getattr(item, "PickedPoints", []) or [])
            if not pts:
                continue
            p = pts[-1]
            key = (round(p.x, 2), round(p.y, 2), round(p.z, 2))
            if key == self._seen:
                return
            self._seen = key
            Gui.Selection.clearSelection()
            self.clicked(p)
            return

    def clicked(self, p):
        """A click on the scan: trace there, or a correction."""
        if self.mode == "end" and self.res is not None:
            self.set_end_at(p)
        elif self.mode == "carry" and self.res is not None:
            self.carry_on_at(p)
        else:
            self.trace_at(p)

    def _set_mode(self, mode):
        self.mode = mode
        self.b_end.setChecked(mode == "end")
        self.b_carry.setChecked(mode == "carry")
        self._say()

    def set_end_at(self, p):
        """The line finishes at the pipe nearest p (global) - the nearer end."""
        from mechflow_gui import scan_route
        q = _local(self.scan_obj, (p.x, p.y, p.z))
        _r, side, dist = scan_route.trim(self.res, q)
        if dist > 2.5 * self.res["od"]:
            self.error.setText("That's not on the traced pipe - click on it (or close by)")
            return
        self.error.setText("")
        self.trims.append(q)
        self.modes = {}
        self.ext = [0.0, 0.0]
        self.res = _r
        (self.end_a if side == 0 else self.end_b).setCurrentText("Plain")
        self._set_mode("trace")
        self._replan()

    def carry_on_at(self, p):
        """Trace again, carrying on past p (global)."""
        self.skips.append(_local(self.scan_obj, (p.x, p.y, p.z)))
        self._set_mode("trace")
        self._retrace()

    def _undo_fixes(self):
        self.skips, self.trims, self.modes = [], [], {}
        self._set_mode("trace")
        if self.raw is not None:
            self._retrace()

    def trace_at(self, p):
        """Follow the pipe through the clicked point p (global) - a new trace."""
        self.skips, self.trims, self.modes = [], [], {}
        self.pick_local = _local(self.scan_obj, (p.x, p.y, p.z))
        self.pick = p
        self._retrace(new=True)

    def _retrace(self, new=False):
        p = self.pick
        self.ext = [0.0, 0.0]
        self._busy = True
        self.error.setText("")
        self._set_found("Following the pipe...")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            QtWidgets.QApplication.processEvents()
            sc = scan_of(self.scan_obj)
            lines = []
            res = scan.trace_scan(sc, self.pick_local, log=lambda t: lines.append(t),
                                  flanges=scan_match.all_flanges, skip=list(self.skips))
            self.raw = res
            from mechflow_gui import scan_route
            for q in self.trims:
                res = scan_route.trim(res, q)[0]
            self.res = res
            if new:
                self._choose_from_scan()
            else:
                for box, e in ((self.end_a, res["ends"][0]), (self.end_b, res["ends"][1])):
                    if e["kind"] == "flange" and box.currentText() == "Plain":
                        box.blockSignals(True)
                        box.setCurrentText("Weld neck flange")
                        box.blockSignals(False)
            self._replan()
            self._say()
        except Exception as e:
            self.res = None
            self._clear_preview()
            self._set_found("")
            self.error.setText(str(e))
            self._say()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._busy = False

    def _choose_from_scan(self):
        """Set the options from what was measured: a spec of the flanges'
        standard and rating if the current one isn't, the size, elbows."""
        ms = [e.get("match") for e in self.res["ends"] if e.get("match")]
        sp = self.current_spec()
        if ms:
            std, rating = ms[0]["std"], ms[0]["rating"]
            if all(m["std"] == std and m["rating"] == rating for m in ms) and \
                    (sp["standard"] != std or sp["rating"] != rating):
                for s in _specs():
                    if s["standard"] == std and s["rating"] == rating:
                        self.spec.setCurrentText(s["name"])
                        break
        sp = self.current_spec()
        std = sp["standard"]
        size, _od, _d = scan_match.match_pipe(std, self.res["od"])
        for box, val in ((self.size, size),):
            box.blockSignals(True)
            box.setCurrentText(val)
            box.blockSignals(False)
        rating = next((m["rating"] for m in ms if m["std"] == std), sp["rating"])
        self.rating.blockSignals(True)
        self.rating.setCurrentText(rating)
        self.rating.blockSignals(False)
        from mechflow_gui import scan_route, pipespec
        p0 = scan_route.plan(self.res, std)
        # the size at each bend: the straight before it
        bsizes = [p0["sizes"][k]["size"] for k in range(len(p0["bends"]))]
        bend, _m = scan_route.best_bend(std, size, pipespec.schedule_for(sp, size),
                                        [b[1] for b in p0["bends"]], bsizes)
        self.bend.blockSignals(True)
        self.bend.setCurrentText(bend)
        self.bend.blockSignals(False)
        for box, e in ((self.end_a, p0["ends"][0]), (self.end_b, p0["ends"][1])):
            box.blockSignals(True)
            box.setCurrentText(e["mode"])
            box.blockSignals(False)

    def _options_changed(self, *_):
        self._replan()

    # -- plan + preview
    def _replan(self, *_, light=False):
        """Work the line out again from the trace and the options. light:
        only the ends moved (grip / length) - skip the slow fit colours."""
        if self.res is None:
            return
        from mechflow_gui import scan_route, routing, pipespec
        sp = self.current_spec()
        std = sp["standard"]
        try:
            p = scan_route.plan(self.res, std, self.square.isChecked(), self.snap.value(),
                                modes=self.modes)
        except Exception as e:
            self.error.setText(f"Couldn't make a line of it: {e}")
            return
        p["ends"][0]["mode"] = self.end_a.currentText()
        p["ends"][1]["mode"] = self.end_b.currentText()
        self.plan = p
        size = self.size.currentText() or p["size"]
        rating = self.rating.currentText() or sp["rating"]
        bend = self.bend.currentText() or sp["bend"]
        notes = []
        ty = routing.types_for(std, bend)
        Q, n1 = scan_route.end_points(p, rating, ty["flange"])
        Q = scan_route.fit_ends(Q, p, std, size, pipespec.schedule_for(sp, size), bend, rating,
                                ty["flange"], notes)
        base = Q
        Q = scan_route.extend_ends(Q, self.ext)
        self.points = Q
        # the pipe in each end straight: its cut length
        size_b = size
        if any((rr.get("join") or {}).get("kind") == "reducer" for rr in p["runs"]):
            size_b = p["sizes"][-1]["size"]
        modes = (self.end_a.currentText(), self.end_b.currentText())
        tk = scan_route.takeoffs(Q, std, size, size_b, pipespec.schedule_for(sp, size), bend,
                                 rating, modes)
        self.pipe_len = [L - t for L, t in tk]
        for k, box in enumerate((self.len_a, self.len_b)):
            box.blockSignals(True)
            box.setValue(max(0.0, self.pipe_len[k]))
            box.blockSignals(False)
        for k, (L, t) in enumerate(tk):
            if L - t < -0.5:
                notes.append(f"{'start' if k == 0 else 'end'}: the end straight is shorter than "
                             "its fittings - drag the grip out or type a longer pipe")
        self._show_preview(Q, p)
        self._show_grips(base, Q)
        if not light:
            self.warns = scan_route.warnings(self.res, p)
            self._fill_table(p)
            self._show_extras(p, std, size, sched=pipespec.schedule_for(sp, size), bend=bend)
        self._set_found(self._report(p, size, rating, bend, n1 + notes))

    # -- the end grips
    def set_pipe_length(self, k, v):
        """End k (0 start, 1 end): make the pipe in its end straight v mm."""
        if self.res is None or self.pipe_len[k] is None:
            return
        self.ext[k] += float(v) - self.pipe_len[k]
        g = self.grips[k]
        if g is not None:
            g["arrow"].set_value(self.ext[k])
        self._replan(light=True)

    def _remove_grips(self):
        self._grip_timer.stop()
        for g in self.grips:
            if g is not None:
                for h in (g["arrow"], g["box"]):
                    try:
                        h.remove()
                    except Exception:
                        pass
        self.grips = [None, None]

    def _show_grips(self, base, Q):
        """Orange grips on the two ends of the line: drag along the pipe."""
        if not App.GuiUp or len(base) < 2:
            return
        from mechflow_gui import view_handles as vh
        od = self.res["od"] if self.res else 100.0
        for k in (0, 1):
            i, j = (0, 1) if k == 0 else (len(base) - 1, len(base) - 2)
            o = _global(self.scan_obj, base[i])
            dvec = _global(self.scan_obj, base[i]) - _global(self.scan_obj, base[j])
            if dvec.Length < 1e-9:
                continue
            dvec.normalize()
            g = self.grips[k]
            if g is not None and (g["origin"] - o).Length < 0.01 and (g["dir"] - dvec).Length < 1e-6:
                if abs(g["arrow"].last - self.ext[k]) > 1e-6:
                    g["arrow"].set_value(self.ext[k])
                g["box"].set_quiet(max(0.0, self.pipe_len[k]))
                continue
            if g is not None:
                for h in (g["arrow"], g["box"]):
                    h.remove()
            try:
                arrow = vh.Arrow(o, dvec, self.ext[k], max(60.0, 1.1 * od))
                box = vh.ViewBox(" mm", 0.0, 1e6, 1)
                box.setToolTip("Cut length of this pipe (not the elbow or flange)")
                box.set_quiet(max(0.0, self.pipe_len[k]))
                box.valueChanged.connect(lambda v, k=k: self.set_pipe_length(k, v))
                self.grips[k] = {"arrow": arrow, "box": box, "origin": o, "dir": dvec}
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: grips not shown ({e})\n")
                self.grips[k] = None
        if not self._grip_timer.isActive():
            self._grip_timer.start()

    def _tick_grips(self):
        from mechflow_gui import widget_alive
        if not widget_alive(self.form):
            # the panel was closed without OK / Cancel: take the grips, the
            # preview and the colours with it
            self._grip_timer.stop()
            self._grip_settle.stop()
            try:
                self._stop()
                self._clear_preview()
            except Exception:
                pass
            return
        for k, g in enumerate(self.grips):
            if g is None:
                continue
            try:
                d = g["arrow"].moved()
                # (the dragger keeps its position in single precision: reading
                # back a typed length can be a hair out - that's not a drag)
                if d is not None and abs(d - self.ext[k]) > 0.05:
                    self.ext[k] = round(d)                  # whole mm while dragging
                    self._grip_settle.start()
                g["box"].place(g["arrow"].tip(), dy=14)
            except Exception:
                pass

    # -- the straights table
    MODES = [("Auto", None), ("Square", "square"), ("As measured", "measured")]

    def set_mode(self, k, mode):
        """Straight k: None (auto), 'square' or 'measured'."""
        if mode:
            self.modes[k] = mode
        else:
            self.modes.pop(k, None)
        self._replan()

    def _fill_table(self, p):
        good, check = self._limits()
        n = len(p["Q"]) - 1
        self.table.clearContents()
        self.table.setRowCount(0)
        self.table.setRowCount(n)
        for k in range(n):
            L = float(np.linalg.norm(p["Q"][k + 1] - p["Q"][k]))
            mx, _mean, cnt = p["dev"][k]
            it = QtWidgets.QTableWidgetItem(f"{k + 1}")
            c = GOOD if (cnt == 0 or mx <= good) else (CHECK if mx <= check else BAD)
            it.setForeground(QtGui.QBrush(QtGui.QColor(*[int(255 * x) for x in c])))
            it.setToolTip("from the flange face" if cnt == 0 else
                          f"centre line off the scan by up to {mx:.1f} mm")
            self.table.setItem(k, 0, it)
            self.table.setItem(k, 1, QtWidgets.QTableWidgetItem(f"{L:.0f}"))
            off = p["off_axis"][k] if k < len(p["off_axis"]) else 0.0
            self.table.setItem(k, 2, QtWidgets.QTableWidgetItem(f"{off:.1f}°"))
            box = QtWidgets.QComboBox()
            for label, _m in self.MODES:
                box.addItem(label)
            cur = self.modes.get(k)
            box.setCurrentIndex([m for _l, m in self.MODES].index(cur))
            box.currentIndexChanged.connect(
                lambda i, k=k: QtCore.QTimer.singleShot(0, lambda: self.set_mode(k, self.MODES[i][1])))
            self.table.setCellWidget(k, 3, box)
        self.table.resizeColumnsToContents()

    # -- fit colours and warning markers
    def _surface_limits(self):
        od = self.res["od"] if self.res else 100.0
        good = max(3.0, 0.01 * od)
        return good, 3 * good

    def _dim_scan(self, on):
        """Fade the scan right back while the fit colours are shown (they sit
        on its surface), and put it back after."""
        o = self.scan_obj
        if o is None or not App.GuiUp:
            return
        vo = o.ViewObject
        if not hasattr(vo, "Transparency"):
            return
        if on:
            if getattr(self, "_scan_tr", None) is None:
                self._scan_tr = (o.Name, vo.Transparency)
            vo.Transparency = 88
        elif getattr(self, "_scan_tr", None) is not None:
            name, tr = self._scan_tr
            x = self.doc.getObject(name)
            if x is not None:
                x.ViewObject.Transparency = tr
            self._scan_tr = None

    def _clear_extras(self):
        for name in self.extras:
            if self.doc.getObject(name) is not None:
                self.doc.removeObject(name)
        self.extras = []

    def _show_extras(self, p, std, size, sched, bend):
        from mechflow_gui import scan_route, routing
        self._clear_extras()
        if not App.GuiUp:
            return
        pl = self.scan_obj.Placement
        self._dim_scan(self.show_fit.isChecked())
        if self.show_fit.isChecked():
            try:
                R = routing.fitting_dims(std, size, sched, bend)[2]
            except Exception:
                R = None
            radii = [x["od"] / 2 for x in p["sizes"]]
            P, dev = scan_route.fit_points(self.res, p["Q"], radii, R)
            self.fit_stats = (P, dev)
            if len(P) > 300000:
                sel = np.random.default_rng(1).choice(len(P), 300000, replace=False)
                P, dev = P[sel], dev[sel]
            sg, sc = self._surface_limits()
            import Points
            for name, m, col in (("ScanFitGood", np.abs(dev) <= sg, GOOD),
                                 ("ScanFitCheck", (np.abs(dev) > sg) & (np.abs(dev) <= sc), CHECK),
                                 ("ScanFitPoor", np.abs(dev) > sc, BAD)):
                if not m.any():
                    continue
                o = self.doc.addObject("Points::Feature", name)
                pts = Points.Points()
                pts.addPoints([tuple(map(float, q)) for q in P[m]])
                o.Points = pts
                o.Placement = pl
                o.Label = "Scan fit (" + {"ScanFitGood": "close", "ScanFitCheck": "check",
                                          "ScanFitPoor": "far"}[name] + ")"
                _colour(o, col)
                o.ViewObject.PointSize = 4.0
                o.ViewObject.Selectable = False
                self.extras.append(o.Name)
        marks = [q for _t, q in self.warns if q is not None]
        if marks:
            import Part
            o = self.doc.addObject("Part::Feature", "ScanWarnings")
            o.Shape = Part.Compound([Part.Vertex(_global(self.scan_obj, q)) for q in marks])
            o.Label = "Pipe from Scan (look here)"
            o.ViewObject.PointColor = (1.0, 0.45, 0.0)
            o.ViewObject.PointSize = 14.0
            o.ViewObject.Selectable = False
            self.extras.append(o.Name)
        self.doc.recompute()

    def _save_report(self, path=None):
        """Write the fit report as CSV (path, or ask)."""
        from mechflow_gui import scan_route
        if self.plan is None:
            self.error.setText("Trace a pipe first")
            return None
        if path is None:
            path, _f = QtWidgets.QFileDialog.getSaveFileName(
                _mw(), "Save fit report", "Pipe from Scan report.csv", "CSV (*.csv)")
            if not path:
                return None
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(self._report_rows())
        return path

    def _report_rows(self):
        from mechflow_gui import scan_route
        p = dict(self.plan)
        p["Q"] = [np.array(tuple(_global(self.scan_obj, q))) for q in p["Q"]]
        rows = scan_route.report_rows(p, self.size.currentText(), self._limits())
        stats = getattr(self, "fit_stats", None)
        if stats is not None and len(stats[1]):
            d = np.abs(stats[1])
            rows.append(["Scan points on the straights", f"{len(d)}",
                         f"off the model surface: median {np.median(d):.1f} mm, "
                         f"95% within {np.percentile(d, 95):.1f} mm"])
        for t, _q in self.warns:
            rows.append(["Check", t, ""])
        return rows

    def _limits(self):
        od = self.res["od"] if self.res else 100.0
        good = max(5.0, 0.02 * od)
        return good, 3 * good

    def _report(self, p, size, rating, bend, notes):
        good, check = self._limits()
        h = []
        # (what to check is marked by orange dots in the 3D view and listed
        # in the saved report - not repeated here, to keep the summary short)
        od_m = p["od"]
        h.append(f"<b>Pipe:</b> OD {od_m:.1f} measured &rarr; <b>{size}</b> "
                 f"(OD {p['size_od']:.1f}{', ' + format(p['od_diff'], '+.1f') + ' mm' if abs(p['od_diff']) >= 0.5 else ''})")
        straights = len(p["Q"]) - 1
        lengths = [float(np.linalg.norm(p["Q"][k + 1] - p["Q"][k])) for k in range(straights)]
        h.append(f"<b>Line:</b> {straights} straight{'s' if straights != 1 else ''} "
                 f"({', '.join(f'{x:.0f}' for x in lengths)} mm centre to centre)")
        if p["bends"]:
            def _ang(a):
                if a < 1:
                    return "in line"
                if min(abs(a - 90), abs(a - 45)) < 0.25:
                    return f"{a:.0f}°"
                return f"{a:.1f}° (cut)"
            angs = [_ang(a) for a, _r, _j in p["bends"]]
            radii = [r for _a, r, _j in p["bends"] if r]
            rtxt = f", radius about {np.median(radii):.0f} mm" if radii else ""
            h.append(f"<b>Bends:</b> {', '.join(angs)}{rtxt} &rarr; {bend} elbows")
        for k, e in enumerate(p["ends"]):
            name = "Start" if k == 0 else "End"
            m = e.get("match")
            if e["kind"] == "flange" and m:
                txt = (f"flange - looks like {m['std']} {m['size']} {m['rating']} "
                       f"(OD {m['D']:.0f}, {100 * min(1.0, m['fill']):.0f}% of its rim seen)")
            elif e["kind"] == "flange":
                txt = "flange (couldn't tell which - check the rating)"
            elif e["kind"] == "plate":
                txt = "a plate across it (bulkhead / deck / equipment)"
            else:
                txt = "the pipe stops (or the scan does)" + (f" - {e['note']}" if e.get("note") else "")
            h.append(f"<b>{name}:</b> {txt}")
        rows = []
        for k, (mx, mean, n) in enumerate(p["dev"]):
            if n == 0:
                col, word = "#888", "from the flange face"
            else:
                c = GOOD if mx <= good else (CHECK if mx <= check else BAD)
                col = "#%02x%02x%02x" % tuple(int(255 * x) for x in c)
                word = f"off by up to {mx:.1f} mm (mean {mean:.1f})"
            rows.append(f"<span style='color:{col}'>&#9632;</span> straight {k + 1}: {word}")
        h.append(f"<b>Against the scan</b> (pipe centre line; green within {good:.0f} mm, "
                 f"amber within {check:.0f}):<br>" + "<br>".join(rows))
        if notes:
            h.append("<i>" + "<br>".join(notes) + "</i>")
        return "<br>".join(h)

    def _show_preview(self, Q, p):
        import Part
        good, check = self._limits()
        pts = [_global(self.scan_obj, q) for q in Q]
        edges = [Part.LineSegment(pts[k], pts[k + 1]).toShape() for k in range(len(pts) - 1)
                 if (pts[k + 1] - pts[k]).Length > 1e-6]
        if not edges:
            return
        sh = Part.Compound(edges)
        if self.preview is None or self.doc.getObject(self.preview) is None:
            o = self.doc.addObject("Part::Feature", "ScanPipePreview")
            o.Label = "Pipe from Scan (preview)"
            self.preview = o.Name
        o = self.doc.getObject(self.preview)
        o.Shape = sh
        if App.GuiUp:
            vo = o.ViewObject
            vo.LineWidth = 5.0
            vo.PointSize = 8.0
            cols = []
            for k, (mx, _mean, n) in enumerate(p["dev"][:len(edges)]):
                cols.append(GOOD if (n == 0 or mx <= good) else (CHECK if mx <= check else BAD))
            try:
                vo.LineColorArray = [c + (0.0,) for c in cols] if len(cols) == len(edges) else []
            except Exception:
                vo.LineColor = GOOD
            vo.PointColor = (1.0, 0.55, 0.1)
            vo.Selectable = False
        self.doc.recompute()

    def _clear_preview(self):
        if self.preview and self.doc.getObject(self.preview) is not None:
            self.doc.removeObject(self.preview)
        self.preview = None
        self._clear_extras()
        self._dim_scan(False)
        self._remove_grips()

    # -- finishing
    def make(self):
        """Make the 3D sketch and route (also what OK does)."""
        from mechflow_gui import scan_route, routing
        if self.res is None or self.plan is None:
            raise ValueError("click a pipe in the scan first")
        sp = self.current_spec()
        p = self.plan
        # the points in the document's coordinates
        p = dict(p)
        p["Q"] = [np.array(tuple(_global(self.scan_obj, q))) for q in p["Q"]]
        ends = []
        for e in p["ends"]:
            e = dict(e)
            for k in ("joint", "point"):
                if e.get(k) is not None:
                    e[k] = np.array(tuple(_global(self.scan_obj, e[k])))
            ends.append(e)
        p["ends"] = ends
        runs = []
        for rr in p["runs"]:
            rr = dict(rr)
            j = rr.get("join")
            if j and j.get("at") is not None:
                rr["join"] = dict(j, at=np.array(tuple(_global(self.scan_obj, j["at"]))))
            runs.append(rr)
        p["runs"] = runs
        n = 1 + sum(1 for o in self.doc.Objects if o.Label.startswith("Scan line"))
        route, sk, notes = scan_route.make(p, sp, self.size.currentText() or None,
                                           self.rating.currentText() or None,
                                           self.bend.currentText() or None,
                                           label=f"Scan line{n}", ext=tuple(self.ext))
        try:
            if not hasattr(route, "ScanReport"):
                route.addProperty("App::PropertyStringList", "ScanReport", "Scan",
                                  "What Pipe from Scan measured and how well it fits the scan")
            route.ScanReport = [" | ".join(r) for r in self._report_rows()]
        except Exception:
            pass
        return route, sk, notes

    def accept(self):
        self._stop()
        self._grip_settle.stop()
        self._clear_preview()
        if self.res is None:
            Gui.Control.closeDialog()
            return True
        self.doc.openTransaction("Pipe from Scan")
        try:
            route, sk, notes = self.make()
        except Exception as e:
            self.doc.abortTransaction()
            self.error.setText(str(e))
            self._timer.start()
            Gui.Selection.addObserver(self._obs)
            self._replan()
            return False
        self.doc.commitTransaction()
        self.doc.recompute()
        if route.Error:
            App.Console.PrintWarning(f"MechFlow: {route.Label}: {route.Error}\n")
        for t in notes:
            App.Console.PrintMessage(f"MechFlow: Pipe from Scan: {t}\n")
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._stop()
        self._grip_settle.stop()
        self._clear_preview()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


class _PickObserver:
    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, doc, obj, sub, pnt):
        try:
            if pnt is not None and (pnt[0] or pnt[1] or pnt[2]):
                self.panel._picked = (obj, V(*pnt))
        except Exception:
            pass


def pipe_from_scan():
    doc = App.ActiveDocument
    if doc is None:
        doc = App.newDocument()
    sel = [x for x in Gui.Selection.getSelectionEx("", 0) if is_scan(x.Object)]
    panel = ScanPanel(sel[0].Object if sel else None)
    Gui.Control.showDialog(panel)
    # a point already picked on the scan: trace from it straight away
    pts = list(getattr(sel[0], "PickedPoints", []) or []) if sel else []
    if pts:
        panel._seen = (round(pts[-1].x, 2), round(pts[-1].y, 2), round(pts[-1].z, 2))
        panel.trace_at(pts[-1])
    return panel
