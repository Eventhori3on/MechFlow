# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Fillet / Chamfer PropertyManager.

Click edges to add them, click a face to add all of its edges, or select them
before starting. Live preview, item list with Remove/Clear, and the same
error handling as Boss/Cut-Extrude. Drives FreeCAD's PartDesign Fillet /
Chamfer, so the geometry is FreeCAD's.

Clicks on the previewed (already filleted) solid are matched back to the
original edges by geometry, so you can keep adding while seeing the result.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

TOL = 1e-4
KINDS = {
    "fillet": {"type": "PartDesign::Fillet", "name": "Fillet", "title": "Fillet",
               "prop": "Radius", "label": "Radius", "default": 2.0},
    "chamfer": {"type": "PartDesign::Chamfer", "name": "Chamfer", "title": "Chamfer",
                "prop": "Size", "label": "Distance", "default": 1.0},
}


def _body_of(obj):
    for o in getattr(obj, "InList", []):
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def _active_body():
    from mechflow_gui import pick_solid
    return pick_solid.active_body()


# ------------------------------------------------------------ geometry matching

def _edge_name(shape, edge):
    """Name of the edge in `shape` that `edge` lies on (by geometry)."""
    import Part
    try:
        p0, p1 = edge.FirstParameter, edge.LastParameter
        probes = [edge.valueAt((p0 + p1) / 2.0)]
        if not edge.isClosed():
            probes += [edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
    except Exception:
        return None
    for i, b in enumerate(shape.Edges):
        try:
            if all(Part.Vertex(p).distToShape(b)[0] < TOL for p in probes):
                return f"Edge{i + 1}"
        except Exception:
            continue
    return None


def _face_edge_names(shape, face):
    """Edge names (in `shape`) of the face of `shape` that `face` lies on."""
    import Part
    from mechflow_gui import pick_solid
    try:
        p, n = pick_solid._face_probe(face)
    except Exception:
        return []
    probe = Part.Vertex(p)
    for g in shape.Faces:
        try:
            if probe.distToShape(g)[0] > TOL:
                continue
            gn = g.normalAt(*g.Surface.parameter(p))
            if abs(abs(gn.dot(n)) - 1.0) > 1e-3:
                continue
        except Exception:
            continue
        names = []
        for e in g.Edges:
            for i, b in enumerate(shape.Edges):
                if b.isSame(e):
                    names.append(f"Edge{i + 1}")
                    break
        return names
    return []


def _names_from_selection(base_shape, skip=()):
    """Edges (on the base solid) for whatever is selected now."""
    names = []
    for item in Gui.Selection.getSelectionEx():
        if item.Object.Name in skip:
            continue
        for sub, shp in zip(item.SubElementNames, item.SubObjects):
            if sub.startswith("Edge"):
                n = _edge_name(base_shape, shp)
                if n:
                    names.append(n)
            elif sub.startswith("Face"):
                names.extend(_face_edge_names(base_shape, shp))
    out = []
    for n in names:
        if n not in out:
            out.append(n)
    return out


# ------------------------------------------------------------ panel

class EdgeFeaturePanel:
    def __init__(self, kind, body, base, feature=None, initial=()):
        self.kind = KINDS[kind]
        self.body = body
        self.base = base
        self.feature = feature
        self.creating = feature is None
        self.doc = body.Document
        self.failed = False
        self._base_shown = False
        self.items = list(feature.Base[1]) if feature is not None and feature.Base else []
        for n in initial:
            if n not in self.items:
                self.items.append(n)
        self.form = self._build_ui()
        if feature is not None:
            self.size.setValue(getattr(feature, self.kind["prop"]).Value
                               if hasattr(getattr(feature, self.kind["prop"]), "Value")
                               else float(getattr(feature, self.kind["prop"])))
        self._refresh_list()
        self._apply()
        Gui.Selection.clearSelection()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ---- UI
    def _build_ui(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle(self.kind["title"])
        root = QtWidgets.QVBoxLayout(w)

        box = QtWidgets.QGroupBox(f"{self.kind['title']} Parameters")
        form = QtWidgets.QFormLayout(box)
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setRange(0.01, 1e5)
        self.size.setDecimals(2)
        self.size.setSuffix(" mm")
        self.size.setValue(self.kind["default"])
        self.size.setKeyboardTracking(False)
        self.size.valueChanged.connect(self._apply)
        form.addRow(self.kind["label"], self.size)
        root.addWidget(box)

        items = QtWidgets.QGroupBox("Items to " + self.kind["title"].lower())
        il = QtWidgets.QVBoxLayout(items)
        self.list = QtWidgets.QListWidget()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setMinimumHeight(110)
        il.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        rm = QtWidgets.QPushButton("Remove")
        rm.clicked.connect(self._remove)
        clr = QtWidgets.QPushButton("Clear")
        clr.clicked.connect(self._clear)
        row.addWidget(rm)
        row.addWidget(clr)
        il.addLayout(row)
        root.addWidget(items)

        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            "background: rgba(200, 60, 60, 60); border: 1px solid #c04040;"
            " border-radius: 4px; padding: 6px;")
        self.error.hide()
        root.addWidget(self.error)

        hint = QtWidgets.QLabel(
            "Click edges to add them. Click a face to add all of its edges.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        root.addWidget(hint)
        root.addStretch(1)
        return w

    def _refresh_list(self):
        self.list.clear()
        for n in self.items:
            self.list.addItem(n)

    def _remove(self):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True)
        for r in rows:
            del self.items[r]
        self._refresh_list()
        self._apply()

    def _clear(self):
        self.items = []
        self._refresh_list()
        self._apply()

    # ---- picking
    def _poll(self):
        try:
            sel = Gui.Selection.getSelectionEx()
        except Exception:
            return
        if not sel:
            return
        new = _names_from_selection(self.base.Shape)
        Gui.Selection.clearSelection()
        added = [n for n in new if n not in self.items]
        if added:
            self.items.extend(added)
            self._refresh_list()
            self._apply()

    # ---- feature
    def _ensure_feature(self):
        if self.feature is None:
            self.feature = self.body.newObject(self.kind["type"], self.kind["name"])
        return self.feature

    def _apply(self, *_):
        if not self.items:
            # Nothing to fillet yet: show the solid as it is.
            self.error.hide()
            self.failed = self.feature is not None
            if self.feature is not None:
                try:
                    self.feature.ViewObject.Visibility = False
                except Exception:
                    pass
            self._show_base(True)
            return
        f = self._ensure_feature()
        f.Base = (self.base, list(self.items))
        setattr(f, self.kind["prop"], self.size.value())
        try:
            self.doc.recompute()
        except Exception:
            pass
        self._check()

    def _show_base(self, on):
        try:
            self.base.ViewObject.Visibility = on
            self._base_shown = on
        except Exception:
            pass

    def _check(self):
        f = self.feature
        try:
            ok = f.isValid() and not f.Shape.isNull()
        except Exception:
            ok = False
        self.failed = not ok
        if ok:
            self.error.hide()
            self._show_base(False)
            try:
                f.ViewObject.Visibility = True
            except Exception:
                pass
            return
        try:
            f.ViewObject.Visibility = False
        except Exception:
            pass
        self._show_base(True)
        word = self.kind["label"].lower()
        self.error.setText(
            f"<b>The {self.kind['title'].lower()} can't be built.</b> The {word} may be "
            "too large for one of the edges, or two edges meet awkwardly. Try a "
            f"smaller {word} or remove an edge.<br>Your model is unchanged.")
        self.error.show()

    # ---- task dialog protocol
    def _stop(self):
        try:
            self._timer.stop()
        except Exception:
            pass

    def accept(self):
        if not self.items or self.failed:
            QtWidgets.QMessageBox.information(
                self.form, self.kind["title"],
                "Add at least one edge, and fix any error shown in the panel - "
                "or press Cancel to leave the model unchanged.")
            return False
        self._stop()
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._stop()
        self.doc.abortTransaction()
        try:
            tip = self.body.Tip
            if tip is not None:
                tip.ViewObject.Visibility = True
        except Exception:
            pass
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


# ------------------------------------------------------------ entry points

def create(kind):
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), KINDS[kind]["title"], "Finish the open dialog first.")
        return
    body = _active_body()
    if body is None:
        sel = Gui.Selection.getSelection()
        body = _body_of(sel[0]) if sel else None
    if body is None or body.Tip is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), KINDS[kind]["title"],
            "There's no solid to " + KINDS[kind]["title"].lower() + " yet.")
        return
    base = body.Tip
    initial = _names_from_selection(base.Shape)
    body.Document.openTransaction(KINDS[kind]["title"])
    Gui.Control.showDialog(EdgeFeaturePanel(kind, body, base, initial=initial))


def edit(feature):
    if Gui.Control.activeDialog():
        return
    kind = "fillet" if feature.TypeId == "PartDesign::Fillet" else "chamfer"
    body = _body_of(feature)
    base = feature.Base[0] if feature.Base else getattr(feature, "BaseFeature", None)
    if body is None or base is None:
        return
    feature.Document.openTransaction("Edit " + feature.Label)
    Gui.Control.showDialog(EdgeFeaturePanel(kind, body, base, feature=feature))
