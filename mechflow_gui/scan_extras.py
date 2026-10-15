"""After Pipe from Scan:

Remove from Scan  - a copy of the scan with the pipe that was modelled taken
                    out (everything on the route's parts' surfaces), so the
                    new pipe sits in what's left of the scan.
Scan Reference View - a picture of the scan and the new pipe placed on a
                    drawing sheet (TechDraw can't draw meshes), with the
                    scan's colour and opacity chosen; re-rendered on demand.
Save Part As      - a standard part (a pipe, an elbow...) saved on its own,
                    at its own origin, as FreeCAD or STEP.
"""
import os
import re
import tempfile

import numpy as np
import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

V = App.Vector


def _mw():
    try:
        return Gui.getMainWindow()
    except Exception:
        return None


def _is_route(o):
    return type(getattr(o, "Proxy", None)).__name__ == "PipeRoute"


def route_objects(route):
    """The solids a route made: its parts and the valves / instruments on it."""
    out = [p for p in route.Parts if p is not None and hasattr(p, "Shape")]
    try:
        from mechflow_gui import inline
        out += [c for c in inline.components_of(route) if hasattr(c, "Shape")]
    except Exception:
        pass
    return out


def _surface_points(shapes, step=6.0):
    """Points all over the shapes' surfaces, about step mm apart."""
    pts = []
    for sh in shapes:
        try:
            verts, tris = sh.tessellate(1.0)
        except Exception:
            continue
        if not tris:
            continue
        Vt = np.array([(p.x, p.y, p.z) for p in verts])
        T = np.array(tris)
        a, b, c = Vt[T[:, 0]], Vt[T[:, 1]], Vt[T[:, 2]]
        area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
        k = np.maximum(1, np.ceil(area / (step * step)).astype(int))
        rep = np.repeat(np.arange(len(T)), k)
        rng = np.random.default_rng(3)
        r1 = np.sqrt(rng.random(len(rep)))
        r2 = rng.random(len(rep))
        pts.append(a[rep] * (1 - r1)[:, None] + b[rep] * (r1 * (1 - r2))[:, None] +
                   c[rep] * (r1 * r2)[:, None])
        pts.append(Vt)
    return np.vstack(pts) if pts else np.zeros((0, 3))


# ------------------------------------------------------------ remove from scan

def remove_from_scan(scan_obj, routes, margin=25.0, hide_original=True):
    """A new scan object: scan_obj without the triangles (or points) within
    margin mm of the routes' parts. Returns it."""
    from scipy.spatial import cKDTree
    from mechflow_gui import scan, scan_gui
    doc = scan_obj.Document
    sc = scan_gui.scan_of(scan_obj)
    shapes = []
    for r in routes:
        shapes += [o.Shape for o in route_objects(r)]
    if not shapes:
        raise ValueError("the route has no parts to take out of the scan")
    M = _surface_points(shapes, step=max(4.0, margin / 3))
    # into the scan's own coordinates
    inv = scan_obj.Placement.inverse().toMatrix()
    A = np.array([[inv.A11, inv.A12, inv.A13], [inv.A21, inv.A22, inv.A23],
                  [inv.A31, inv.A32, inv.A33]])
    t = np.array([inv.A14, inv.A24, inv.A34])
    M = M @ A.T + t
    tree = cKDTree(M)
    lo, hi = M.min(0) - margin, M.max(0) + margin
    if sc.is_mesh:
        F = sc.F
        Vv = sc.V
        C = (Vv[F[:, 0]] + Vv[F[:, 1]] + Vv[F[:, 2]]) / np.float32(3)
    else:
        F = None
        C = sc.V
    near_box = np.nonzero(np.all((C >= lo) & (C <= hi), axis=1))[0]
    gone = np.zeros(len(C), bool)
    if len(near_box):
        d, _i = tree.query(C[near_box].astype(np.float64), distance_upper_bound=margin)
        gone[near_box[np.isfinite(d)]] = True
        if F is not None:
            # a triangle with any corner on the parts goes too (big ones)
            for k in range(3):
                Ck = Vv[F[near_box, k]].astype(np.float64)
                dk, _i = tree.query(Ck, distance_upper_bound=margin)
                gone[near_box[np.isfinite(dk)]] = True
    names = ", ".join(r.Label for r in routes)
    label = f"{scan_obj.Label} without {names}"
    if F is not None:
        keep_F = F[~gone]
        used = np.unique(keep_F)
        remap = np.full(len(Vv), -1, np.int64)
        remap[used] = np.arange(len(used))
        new = scan.Scan(Vv[used], remap[keep_F], None, None, "")
    else:
        Nn = None if sc.Nn is None else sc.Nn[~gone]
        new = scan.Scan(sc.V[~gone], None, None, Nn, "")
    # keep the full-detail copy as a file, so it can be traced again later
    path = os.path.join(scan_gui.cache_dir(), re.sub(r"[^A-Za-z0-9._ -]", "_", label)[:120]
                        + (".stl" if new.is_mesh else ".xyz"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if new.is_mesh:
        scan.write_stl(path, new.V.astype(np.float64), new.F)
    else:
        np.savetxt(path, new.V, fmt="%.3f")
    new.source = path
    o = scan_gui.show_scan(doc, new, label)
    o.Placement = scan_obj.Placement
    scan_gui._SCANS[scan_gui._key(o)] = new
    if not hasattr(o, "RemovedFor"):
        o.addProperty("App::PropertyLinkList", "RemovedFor", "Scan",
                      "Routes whose pipe was taken out of this copy of the scan")
    o.RemovedFor = list(routes)
    if hide_original and App.GuiUp:
        scan_obj.Visibility = False
    doc.recompute()
    if not hasattr(o, "RemovedCount"):
        o.addProperty("App::PropertyInteger", "RemovedCount", "Scan",
                      "How many triangles (or points) were taken out", 1)
    o.RemovedCount = int(gone.sum())
    App.Console.PrintMessage(f"MechFlow: {label}: {int(gone.sum()):,} of {len(C):,} "
                             f"{'triangles' if F is not None else 'points'} taken out\n")
    return o


class RemoveDialog(QtWidgets.QDialog):
    def __init__(self, scans, routes, parent=None):
        super().__init__(parent or _mw())
        self.setWindowTitle("Remove from Scan")
        try:
            from mechflow_gui import app_icon
            self.setWindowIcon(app_icon.icon())
        except Exception:
            pass
        lay = QtWidgets.QFormLayout(self)
        info = QtWidgets.QLabel(
            "Makes a copy of the scan without the pipe you modelled (everything on the "
            "route's pipes, fittings, flanges and valves), so the new pipe sits in what's left "
            "of the scan. The original scan is kept (hidden).")
        info.setWordWrap(True)
        lay.addRow(info)
        self.scan = QtWidgets.QComboBox()
        for s in scans:
            self.scan.addItem(s.Label, s.Name)
        lay.addRow("Scan", self.scan)
        self.routes = QtWidgets.QListWidget()
        for r in routes:
            it = QtWidgets.QListWidgetItem(r.Label)
            it.setData(QtCore.Qt.UserRole, r.Name)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked)
            self.routes.addItem(it)
        self.routes.setMaximumHeight(110)
        lay.addRow("Take out", self.routes)
        self.margin = QtWidgets.QDoubleSpinBox()
        self.margin.setRange(1.0, 500.0)
        self.margin.setValue(25.0)
        self.margin.setSuffix(" mm")
        self.margin.setToolTip("Scan within this distance of the parts goes (scan noise, the "
                               "pipe being a little off the model)")
        lay.addRow("Margin", self.margin)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def chosen(self, doc):
        rs = []
        for i in range(self.routes.count()):
            it = self.routes.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                rs.append(doc.getObject(it.data(QtCore.Qt.UserRole)))
        return doc.getObject(self.scan.currentData()), rs, self.margin.value()


def remove_command():
    from mechflow_gui import scan_gui
    doc = App.ActiveDocument
    if doc is None:
        return
    scans = [o for o in scan_gui.scans_in(doc) if o.Visibility] or scan_gui.scans_in(doc)
    routes = [o for o in doc.Objects if _is_route(o)]
    sel = [x for x in Gui.Selection.getSelection() if _is_route(x) or
           any(_is_route(y) for y in getattr(x, "InList", []))]
    if sel:
        picked = set()
        for x in sel:
            picked |= {x.Name} if _is_route(x) else {y.Name for y in x.InList if _is_route(y)}
        routes = [r for r in routes if r.Name in picked] + [r for r in routes if r.Name not in picked]
    if not scans or not routes:
        QtWidgets.QMessageBox.information(_mw(), "Remove from Scan",
                                          "This needs a scan and a route in the document.")
        return
    d = RemoveDialog(scans, routes)
    if d.exec() != QtWidgets.QDialog.Accepted:
        return
    s, rs, margin = d.chosen(doc)
    if not rs:
        return
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        doc.openTransaction("Remove from Scan")
        remove_from_scan(s, rs, margin)
        doc.commitTransaction()
    except Exception as e:
        doc.abortTransaction()
        QtWidgets.QMessageBox.warning(_mw(), "Remove from Scan", str(e))
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()


# ------------------------------------------------------------ reference view

VIEWS = ["Current view", "Isometric", "Front", "Top", "Right", "Left", "Rear", "Bottom"]


def view3d(doc):
    """The 3D view of a document (whatever window is in front)."""
    gd = Gui.getDocument(doc.Name)
    try:
        vs = gd.mdiViewsOfType("Gui::View3DInventor")
        if vs:
            return vs[0]
    except Exception:
        pass
    return gd.ActiveView


def render_scan(doc, settings, path, size=(2400, 1600)):
    """Render the scan(s) and routes to an image with the scan coloured and
    see-through as settings say: {'view', 'scan_colour', 'scan_opacity'
    (0-100), 'pipe_colour' or None, 'scans' [names], 'routes' [names],
    'others': show the rest of the model}. Puts everything back after."""
    view = view3d(doc)
    scans = [doc.getObject(n) for n in settings.get("scans", []) if doc.getObject(n)]
    routes = [doc.getObject(n) for n in settings.get("routes", []) if doc.getObject(n)]
    keep = set(o.Name for o in scans)
    for r in routes:
        keep.add(r.Name)
        keep |= {p.Name for p in route_objects(r)}
    saved = []

    def save(o, prop, val):
        vo = o.ViewObject
        if prop in vo.PropertiesList:
            saved.append((o, prop, getattr(vo, prop)))
            setattr(vo, prop, val)

    cam = None
    try:
        cam = view.getCamera()
    except Exception:
        pass
    try:
        if not settings.get("others", False):
            for o in doc.Objects:
                if not hasattr(o, "ViewObject") or o.ViewObject is None:
                    continue
                if o.Name in keep:
                    continue
                if o.TypeId.startswith("TechDraw") or o.TypeId.startswith("App::Document"):
                    continue
                # groups / parts holding the route stay on
                if any(c.Name in keep for c in getattr(o, "OutListRecursive", [])):
                    continue
                save(o, "Visibility", False)
        def colour(o, col):
            vo = o.ViewObject
            if "ShapeColor" in vo.PropertiesList:
                save(o, "ShapeColor", col)
            if "ShapeAppearance" in vo.PropertiesList:
                m = App.Material()
                m.DiffuseColor = col
                m.AmbientColor = tuple(0.4 * c for c in col)
                save(o, "ShapeAppearance", (m,))

        for s in scans:
            save(s, "Visibility", True)
            col = tuple(settings.get("scan_colour", (0.62, 0.66, 0.72)))
            colour(s, col)
            save(s, "Transparency", int(100 - settings.get("scan_opacity", 100)))
            save(s, "DisplayMode", "Shaded") if "Shaded" in s.ViewObject.listDisplayModes() \
                else None
        pc = settings.get("pipe_colour")
        if pc:
            for r in routes:
                for p in route_objects(r):
                    save(p, "Visibility", True)
                    colour(p, tuple(pc))
        v = settings.get("view", "Isometric")
        if v != "Current view":
            {"Isometric": view.viewIsometric, "Front": view.viewFront, "Top": view.viewTop,
             "Right": view.viewRight, "Left": view.viewLeft, "Rear": view.viewRear,
             "Bottom": view.viewBottom}[v]()
            view.fitAll()
        QtWidgets.QApplication.processEvents()
        view.saveImage(path, int(size[0]), int(size[1]), "White")
    finally:
        for o, prop, val in reversed(saved):
            try:
                setattr(o.ViewObject, prop, val)
            except Exception:
                pass
        if cam is not None:
            try:
                view.setCamera(cam)
            except Exception:
                pass
    return path


def _settings_of(img):
    import json
    try:
        return json.loads(img.ScanViewSettings)
    except Exception:
        return None


def _crop_white(path, pad=40):
    """Trim the plain white border off a rendered picture (keeps a margin)."""
    try:
        from PySide6 import QtGui
    except ImportError:
        from PySide2 import QtGui
    im = QtGui.QImage(path)
    if im.isNull():
        return
    w, h = im.width(), im.height()
    x0, y0, x1, y1 = w, h, -1, -1
    step = 4
    for y in range(0, h, step):
        for x in range(0, w, step):
            c = im.pixel(x, y) & 0xFFFFFF
            if ((c >> 16) & 255) < 245 or ((c >> 8) & 255) < 245 or (c & 255) < 245:
                if x < x0: x0 = x
                if x > x1: x1 = x
                if y < y0: y0 = y
                if y > y1: y1 = y
    if x1 < 0:
        return
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w - 1, x1 + pad), min(h - 1, y1 + pad)
    if x1 - x0 < w - 4 or y1 - y0 < h - 4:
        im.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1).save(path)


# TechDraw shows a picture at 0.1 mm a pixel at scale 1 (its scene works in
# tenths of a millimetre), and Width/Height are a crop box in sheet mm.
_MM_PER_PX = 0.1


def _image_px(img):
    try:
        from PySide6 import QtGui
    except ImportError:
        from PySide2 import QtGui
    im = QtGui.QImage(img.ImageFile)
    return (im.width(), im.height()) if not im.isNull() else (2400, 1600)


def _shown_size(img):
    pw, ph = _image_px(img)
    k = float(img.Scale) * _MM_PER_PX
    return pw * k, ph * k


def _fit_on_sheet(img, page, width=None):
    """Scale the picture to width mm (default 38 % of the sheet, no taller than
    45 %) and put it top right inside the frame."""
    try:
        tw, th = float(page.Template.Width), float(page.Template.Height)
    except Exception:
        tw, th = 420.0, 297.0
    pw, ph = _image_px(img)
    w = width or 0.38 * tw
    w = min(w, 0.45 * th * pw / ph)
    try:
        img.ScaleType = "Custom"
    except Exception:
        pass
    img.Width = pw * _MM_PER_PX
    img.Height = ph * _MM_PER_PX
    img.Scale = w / (pw * _MM_PER_PX)
    sw, sh = _shown_size(img)
    img.X = tw - sw / 2 - 20
    img.Y = th - sh / 2 - 20


def add_reference_view(page, settings, width=None, title="Reference - laser scan"):
    """Render and place a scan reference view on page; returns the image view."""
    import json
    doc = page.Document
    folder = os.path.join(tempfile.gettempdir(), "MechFlow scan views")
    os.makedirs(folder, exist_ok=True)
    n = 1 + sum(1 for o in doc.Objects if hasattr(o, "ScanViewSettings"))
    path = os.path.join(folder, f"{doc.Name}_scan_view_{n}.png")
    render_scan(doc, settings, path)
    _crop_white(path)
    img = doc.addObject("TechDraw::DrawViewImage", "ScanView")
    img.Label = f"Scan view {n}"
    img.addProperty("App::PropertyString", "ScanViewSettings", "Scan",
                    "How this reference view of the scan was rendered (JSON)")
    img.ScanViewSettings = json.dumps(settings)
    img.ImageFile = path
    page.addView(img)
    _fit_on_sheet(img, page, width)
    try:
        cap = doc.addObject("TechDraw::DrawViewAnnotation", "ScanViewTitle")
        cap.Text = [title]
        cap.TextSize = 5.0
        page.addView(cap)
        cap.X = float(img.X)
        cap.Y = float(img.Y) - _shown_size(img)[1] / 2 - 6
        img.addProperty("App::PropertyLink", "TitleNote", "Scan", "The view's title")
        img.TitleNote = cap
    except Exception as e:
        App.Console.PrintWarning(f"MechFlow: scan view title not added ({e})\n")
    doc.recompute()
    return img


def update_reference_view(img):
    """Render a scan reference view again (after the model changed)."""
    s = _settings_of(img)
    if s is None:
        return None
    w = _shown_size(img)[0]
    render_scan(img.Document, s, img.ImageFile)
    _crop_white(img.ImageFile)
    pages = [p for p in img.InList if p.isDerivedFrom("TechDraw::DrawPage")]
    if pages:                                 # same width on the sheet, new crop
        x, y = float(img.X), float(img.Y)
        _fit_on_sheet(img, pages[0], w)
        img.X, img.Y = x, y
    img.ImageFile = img.ImageFile           # touch: reload the picture
    img.touch()
    img.Document.recompute()
    return img


class ReferenceDialog(QtWidgets.QDialog):
    """Scan, routes, view direction, scan colour and opacity, pipe colour."""

    def __init__(self, doc, scans, routes, parent=None, settings=None):
        super().__init__(parent or _mw())
        self.setWindowTitle("Scan Reference View")
        try:
            from mechflow_gui import app_icon
            self.setWindowIcon(app_icon.icon())
        except Exception:
            pass
        s = settings or {}
        lay = QtWidgets.QFormLayout(self)
        info = QtWidgets.QLabel("A picture of the scan with the new pipe in it, placed on the "
                                "drawing as a reference view (drawings can't draw the scan "
                                "itself). Select it and run this again to update it.")
        info.setWordWrap(True)
        lay.addRow(info)
        self.scans = QtWidgets.QListWidget()
        for o in scans:
            it = QtWidgets.QListWidgetItem(o.Label)
            it.setData(QtCore.Qt.UserRole, o.Name)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            on = o.Name in s.get("scans", []) if s else o.Visibility
            it.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
            self.scans.addItem(it)
        self.scans.setMaximumHeight(80)
        lay.addRow("Scan", self.scans)
        self.routes = QtWidgets.QListWidget()
        for o in routes:
            it = QtWidgets.QListWidgetItem(o.Label)
            it.setData(QtCore.Qt.UserRole, o.Name)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            on = o.Name in s.get("routes", []) if s else True
            it.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
            self.routes.addItem(it)
        self.routes.setMaximumHeight(80)
        lay.addRow("Pipework", self.routes)
        self.view = QtWidgets.QComboBox()
        self.view.addItems(VIEWS)
        self.view.setCurrentText(s.get("view", "Isometric"))
        lay.addRow("View", self.view)
        self.scan_colour = tuple(s.get("scan_colour", (0.55, 0.70, 0.92)))
        self.b_scan = QtWidgets.QPushButton()
        self.b_scan.clicked.connect(lambda: self._pick("scan_colour", self.b_scan))
        lay.addRow("Scan colour", self.b_scan)
        self.opacity = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity.setRange(10, 100)
        self.opacity.setValue(int(s.get("scan_opacity", 60)))
        self.op_label = QtWidgets.QLabel()
        self.opacity.valueChanged.connect(lambda v: self.op_label.setText(f"{v}%"))
        self.op_label.setText(f"{self.opacity.value()}%")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.opacity, 1)
        row.addWidget(self.op_label)
        lay.addRow("Scan opacity", row)
        self.hl = QtWidgets.QCheckBox("Colour the new pipe")
        self.hl.setChecked(s.get("pipe_colour") is not None if s else True)
        self.pipe_colour = tuple(s.get("pipe_colour") or (0.95, 0.55, 0.12))
        self.b_pipe = QtWidgets.QPushButton()
        self.b_pipe.clicked.connect(lambda: self._pick("pipe_colour", self.b_pipe))
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(self.hl)
        row2.addWidget(self.b_pipe)
        lay.addRow(row2)
        self.others = QtWidgets.QCheckBox("Show the rest of the model too")
        self.others.setChecked(bool(s.get("others", False)))
        lay.addRow(self.others)
        for b, k in ((self.b_scan, "scan_colour"), (self.b_pipe, "pipe_colour")):
            self._paint(b, getattr(self, k))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def _paint(self, b, col):
        c = QtGui.QColor(*[int(255 * x) for x in col])
        b.setText(c.name())
        b.setStyleSheet(f"background:{c.name()}; color:{'#000' if c.lightness() > 128 else '#fff'};")

    def _pick(self, attr, b):
        c0 = QtGui.QColor(*[int(255 * x) for x in getattr(self, attr)])
        c = QtWidgets.QColorDialog.getColor(c0, self, "Colour")
        if c.isValid():
            setattr(self, attr, (c.redF(), c.greenF(), c.blueF()))
            self._paint(b, getattr(self, attr))

    def settings(self):
        def checked(lst):
            return [lst.item(i).data(QtCore.Qt.UserRole) for i in range(lst.count())
                    if lst.item(i).checkState() == QtCore.Qt.Checked]
        return {"scans": checked(self.scans), "routes": checked(self.routes),
                "view": self.view.currentText(), "scan_colour": list(self.scan_colour),
                "scan_opacity": self.opacity.value(),
                "pipe_colour": list(self.pipe_colour) if self.hl.isChecked() else None,
                "others": self.others.isChecked()}


def reference_command():
    from mechflow_gui import scan_gui, drawings
    doc = App.ActiveDocument
    if doc is None:
        return
    sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "ScanViewSettings")]
    scans = scan_gui.scans_in(doc)
    routes = [o for o in doc.Objects if _is_route(o)]
    if sel:
        img = sel[0]
        d = ReferenceDialog(doc, scans, routes, settings=_settings_of(img))
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        import json
        img.ScanViewSettings = json.dumps(d.settings())
        update_reference_view(img)
        return
    page = drawings.active_page()
    if page is None:
        pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
        page = pages[0] if len(pages) == 1 else None
    if page is None:
        QtWidgets.QMessageBox.information(
            _mw(), "Scan Reference View",
            "Open the drawing sheet to put it on first (Make Drawing makes one).")
        return
    if not scans:
        QtWidgets.QMessageBox.information(_mw(), "Scan Reference View",
                                          "There's no scan in this document.")
        return
    d = ReferenceDialog(doc, scans, routes)
    if d.exec() != QtWidgets.QDialog.Accepted:
        return
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        add_reference_view(page, d.settings())
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()


# ------------------------------------------------------------ save part as

def _safe(name):
    return re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "Part"


def _set_number(o, number, desc=None):
    """Part number (and description) on o - the BOM lists it by its number."""
    if "PartNumber" not in o.PropertiesList:
        o.addProperty("App::PropertyString", "PartNumber", "Part",
                      "Part number (shown in the BOM)")
    o.PartNumber = number or ""
    if desc is not None:
        if "PartDescription" not in o.PropertiesList:
            o.addProperty("App::PropertyString", "PartDescription", "Part",
                          "What the part is")
        o.PartDescription = desc


def save_part(obj, path, number=None, desc=None):
    """Save one part at its own origin: .FCStd (a copy of the part, still a
    standard part) or .step / .stp (its solid). With a part number the saved
    part is called by it (the STEP product too) and carries it for the BOM."""
    import Part
    ext = os.path.splitext(path)[1].lower()
    label = number or obj.Label
    if ext in (".step", ".stp"):
        sh = obj.Shape.copy()
        sh.Placement = App.Placement()
        try:
            tmp = App.newDocument("MechFlowStepOut", hidden=True)
        except TypeError:
            tmp = App.newDocument("MechFlowStepOut")
        try:
            f = tmp.addObject("Part::Feature", "Part")
            f.Shape = sh
            f.Label = label
            tmp.recompute()
            try:
                import Import
                Import.export([f], path)
            except Exception:
                sh.exportStep(path)
        finally:
            App.closeDocument(tmp.Name)
            try:
                App.setActiveDocument(obj.Document.Name)
            except Exception:
                pass
        return path
    src = obj.Document
    name = os.path.splitext(os.path.basename(path))[0]
    new = App.newDocument(re.sub(r"[^A-Za-z0-9_]", "_", name) or "Part")
    try:
        copy = new.copyObject(obj, False)
        copy.Placement = App.Placement()
        copy.Label = label
        new.recompute()
        if copy.Shape.isNull():               # (its maker didn't come across) - the solid
            new.removeObject(copy.Name)
            copy = new.addObject("Part::Feature", "Part")
            sh = obj.Shape.copy()
            sh.Placement = App.Placement()
            copy.Shape = sh
            copy.Label = label
        if number or desc:
            _set_number(copy, number or "", desc)
            if desc:
                copy.Label2 = desc
        new.saveAs(path)
    finally:
        App.closeDocument(new.Name)
        try:
            App.setActiveDocument(src.Name)
        except Exception:
            pass
    return path


def part_file_name(o):
    from mechflow_gui import stdparts
    try:
        if stdparts.is_std_object(o):
            return _safe(stdparts.object_designation(o))
    except Exception:
        pass
    return _safe(o.Label)


def describe(o):
    """What the part is: its standard designation, else its name."""
    from mechflow_gui import stdparts
    try:
        if stdparts.is_std_object(o):
            return stdparts.object_designation(o)
    except Exception:
        pass
    return o.Label


NAMING = ["Part number", "Part number - description", "Description"]
FORMATS = ["FreeCAD part (.FCStd)", "STEP (.step)", "Both"]


class SavePartsDialog(QtWidgets.QDialog):
    """Part numbers, descriptions and file names for the parts to save."""

    def __init__(self, objs, parent=None):
        super().__init__(parent or _mw())
        self.objs = objs
        self.setWindowTitle("Save Part As")
        self.resize(820, 420)
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
        lay = QtWidgets.QVBoxLayout(self)
        num = QtWidgets.QHBoxLayout()
        num.addWidget(QtWidgets.QLabel("Number them:"))
        self.prefix = QtWidgets.QLineEdit(p.GetString("PartNumberPrefix", ""))
        self.prefix.setPlaceholderText("prefix, e.g. WE-")
        self.prefix.setMaximumWidth(140)
        self.start = QtWidgets.QSpinBox()
        self.start.setRange(0, 99999999)
        self.start.setValue(p.GetInt("PartNumberNext", 1001))
        self.step = QtWidgets.QSpinBox()
        self.step.setRange(1, 1000)
        self.step.setValue(1)
        b = QtWidgets.QPushButton("Number")
        b.clicked.connect(self._number)
        for w, t in ((self.prefix, None), (self.start, "from"), (self.step, "step")):
            if t:
                num.addWidget(QtWidgets.QLabel(t))
            num.addWidget(w)
        num.addWidget(b)
        num.addStretch(1)
        lay.addLayout(num)
        self.table = QtWidgets.QTableWidget(len(objs), 4)
        self.table.setHorizontalHeaderLabels(["Part", "Part number", "Description", "File name"])
        self.table.verticalHeader().hide()
        for r, o in enumerate(objs):
            it = QtWidgets.QTableWidgetItem(o.Label)
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(
                getattr(o, "PartNumber", "") or ""))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(
                getattr(o, "PartDescription", "") or describe(o)))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(""))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        form = QtWidgets.QFormLayout()
        self.naming = QtWidgets.QComboBox()
        self.naming.addItems(NAMING)
        self.naming.setCurrentText(p.GetString("PartFileNaming", NAMING[0]))
        form.addRow("File names", self.naming)
        self.fmt = QtWidgets.QComboBox()
        self.fmt.addItems(FORMATS)
        self.fmt.setCurrentText(p.GetString("PartFileFormat", FORMATS[0]))
        form.addRow("Save as", self.fmt)
        frow = QtWidgets.QHBoxLayout()
        doc = objs[0].Document
        start = p.GetString("PartFolder", "") or (os.path.dirname(doc.FileName)
                                                   if doc.FileName else os.path.expanduser("~"))
        self.folder = QtWidgets.QLineEdit(start)
        fb = QtWidgets.QPushButton("Browse...")
        fb.clicked.connect(self._browse)
        frow.addWidget(self.folder, 1)
        frow.addWidget(fb)
        form.addRow("Folder", frow)
        self.keep = QtWidgets.QCheckBox("Put the part numbers on the parts in this model too "
                                        "(the BOM lists them by number)")
        self.keep.setChecked(True)
        form.addRow("", self.keep)
        lay.addLayout(form)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._auto = [True] * len(objs)
        self._filling = False
        self.table.itemChanged.connect(self._changed)
        self.naming.currentTextChanged.connect(lambda _t: self._names())
        self._names()

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Save the parts in",
                                                       self.folder.text())
        if d:
            self.folder.setText(d)

    def _number(self):
        n, st = self.start.value(), self.step.value()
        width = len(str(self.start.value()))
        for r in range(len(self.objs)):
            self.table.item(r, 1).setText(f"{self.prefix.text()}{n:0{width}d}")
            n += st

    def _changed(self, it):
        if self._filling:
            return
        if it.column() == 3:
            self._auto[it.row()] = False
        elif it.column() in (1, 2):
            self._names()

    def _names(self):
        self._filling = True
        try:
            mode = self.naming.currentText()
            used = {}
            for r, o in enumerate(self.objs):
                if not self._auto[r]:
                    continue
                pn = self.table.item(r, 1).text().strip()
                ds = self.table.item(r, 2).text().strip() or describe(o)
                if mode == NAMING[0]:
                    base = pn or ds
                elif mode == NAMING[1]:
                    base = f"{pn} - {ds}" if pn else ds
                else:
                    base = ds
                base = _safe(base)
                used[base] = used.get(base, 0) + 1
                self.table.item(r, 3).setText(base if used[base] == 1 else
                                              f"{base} ({used[base]})")
        finally:
            self._filling = False

    def rows(self):
        out = []
        for r, o in enumerate(self.objs):
            out.append((o, self.table.item(r, 1).text().strip(),
                        self.table.item(r, 2).text().strip(),
                        _safe(self.table.item(r, 3).text().strip() or part_file_name(o))))
        return out

    def _ok(self):
        folder = self.folder.text().strip()
        if not folder or not os.path.isdir(folder):
            QtWidgets.QMessageBox.information(self, "Save Part As", "Pick a folder to save in.")
            return
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
        p.SetString("PartFolder", folder)
        p.SetString("PartFileNaming", self.naming.currentText())
        p.SetString("PartFileFormat", self.fmt.currentText())
        p.SetString("PartNumberPrefix", self.prefix.text())
        nums = [int(m.group(1)) for _o, pn, _d, _f in self.rows()
                for m in [re.search(r"(\d+)$", pn)] if m and pn.startswith(self.prefix.text())]
        if nums:
            p.SetInt("PartNumberNext", max(nums) + self.step.value())
        self.accept()


def save_parts(rows, folder, fmt=FORMATS[0], keep=True):
    """rows: [(object, part number, description, file name)]. Returns paths."""
    exts = {FORMATS[0]: [".FCStd"], FORMATS[1]: [".step"], FORMATS[2]: [".FCStd", ".step"]}[fmt]
    paths = []
    for o, pn, ds, fname in rows:
        for ext in exts:
            paths.append(save_part(o, os.path.join(folder, fname + ext), pn or None,
                                   ds or None))
    if keep:
        doc = rows[0][0].Document if rows else None
        if doc is not None:
            doc.openTransaction("Part numbers")
            for o, pn, ds, _f in rows:
                if pn or "PartNumber" in o.PropertiesList:
                    _set_number(o, pn, ds or None)
            doc.commitTransaction()
    return paths


def save_part_command():
    sel = [o for o in Gui.Selection.getSelection() if hasattr(o, "Shape") and
           not o.Shape.isNull()]
    if not sel:
        QtWidgets.QMessageBox.information(_mw(), "Save Part As",
                                          "Select the part(s) to save - a pipe, an elbow...")
        return None
    dlg = SavePartsDialog(sel)
    if not dlg.exec():
        return None
    paths = save_parts(dlg.rows(), dlg.folder.text().strip(), dlg.fmt.currentText(),
                       dlg.keep.isChecked())
    App.Console.PrintMessage(f"MechFlow: saved {len(paths)} file(s) in "
                             f"{dlg.folder.text().strip()}\n")
    return paths
