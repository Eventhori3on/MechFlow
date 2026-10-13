# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared base for MechFlow's SOLIDWORKS-style feature panels.

Gives every panel the same behaviour:
- selection boxes ("pick fields"): click a box to make it active, then click
  faces / edges / features / sketches in the 3D view or tree to fill it;
- live preview, a red message if the feature can't be built (the model stays
  on screen), and OK / Cancel with a single undo step.

Selections are read by polling (no Qt hooks into FreeCAD widgets).
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


def body_of(obj):
    for o in getattr(obj, "InList", []):
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def active_body():
    from mechflow_gui import pick_solid
    b = pick_solid.active_body()
    if b is not None:
        return b
    for item in Gui.Selection.getSelectionEx():
        b = body_of(item.Object) or (item.Object if item.Object.TypeId == "PartDesign::Body" else None)
        if b is not None:
            return b
    return None


def has(obj, prop):
    return prop in getattr(obj, "PropertiesList", [])


def set_enum(obj, prop, names):
    try:
        options = list(obj.getEnumerationsOfProperty(prop) or [])
    except Exception:
        return False
    for n in names:
        if n in options:
            setattr(obj, prop, n)
            return True
    return False


def origin_feature(body, role):
    """X_Axis / Y_Axis / Z_Axis / XY_Plane / XZ_Plane / YZ_Plane of a body."""
    origin = getattr(body, "Origin", None)
    for f in getattr(origin, "OriginFeatures", []) if origin else []:
        if f.Name.startswith(role) or getattr(f, "Role", "") == role:
            return f
    return None


def creator_of_face(obj, sub):
    """The feature that made a clicked face (for picking features in 3D)."""
    from mechflow_gui import pick_solid
    body = body_of(obj) or (obj if obj.TypeId == "PartDesign::Body" else None)
    if body is None or not sub.startswith("Face"):
        return None
    try:
        return pick_solid.creator_of(body, int(sub[4:]) - 1)
    except Exception:
        return None


class PickField:
    """A box listing picked items. kinds: 'face', 'edge', 'vertex', 'feature',
    'sketch', 'plane', 'linear' (straight edge / axis / sketch line)."""

    def __init__(self, panel, title, kinds, single=False, hint=""):
        self.panel = panel
        self.kinds = kinds
        self.single = single
        self.items = []            # (obj, sub) ; sub "" for whole objects
        self.box = QtWidgets.QGroupBox(title)
        lay = QtWidgets.QVBoxLayout(self.box)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(28 if single else 90)
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        lay.addWidget(self.list)
        if not single:
            row = QtWidgets.QHBoxLayout()
            rm = QtWidgets.QPushButton("Remove")
            rm.clicked.connect(self._remove)
            clr = QtWidgets.QPushButton("Clear")
            clr.clicked.connect(self.clear)
            row.addWidget(rm)
            row.addWidget(clr)
            lay.addLayout(row)
        if hint:
            h = QtWidgets.QLabel(hint)
            h.setWordWrap(True)
            h.setStyleSheet("color: gray;")
            lay.addWidget(h)
        self.box.mousePressEvent = lambda e: panel.set_active(self)
        self.list.mousePressEvent = self._list_press

    def _list_press(self, e):
        self.panel.set_active(self)
        QtWidgets.QListWidget.mousePressEvent(self.list, e)

    def set_active(self, on):
        self.box.setStyleSheet("QGroupBox { border: 2px solid #569de5; }" if on else "")

    def label(self, obj, sub):
        return f"{obj.Label}" + (f"  {sub}" if sub else "")

    def refresh(self):
        self.list.clear()
        for obj, sub in self.items:
            self.list.addItem(self.label(obj, sub))

    def _remove(self):
        rows = sorted((self.list.row(i) for i in self.list.selectedItems()), reverse=True)
        for r in rows:
            del self.items[r]
        self.refresh()
        self.panel.changed()

    def clear(self):
        self.items = []
        self.refresh()
        self.panel.changed()

    def set(self, items):
        self.items = list(items)
        self.refresh()

    def accepts(self, obj, sub, shp):
        """Return the (obj, sub) to store for a clicked item, or None."""
        t = obj.TypeId
        if not sub:
            if "sketch" in self.kinds and t == "Sketcher::SketchObject":
                return (obj, "")
            if "plane" in self.kinds and t in ("App::Plane", "PartDesign::Plane"):
                return (obj, "")
            if "linear" in self.kinds and t in ("App::Line", "PartDesign::Line"):
                return (obj, "")
            if "feature" in self.kinds and obj.isDerivedFrom("PartDesign::Feature"):
                return (obj, "")
            return None
        if sub.startswith("Face"):
            if "face" in self.kinds:
                return (obj, sub)
            if "plane" in self.kinds:
                try:
                    if type(shp.Surface).__name__ == "Plane":
                        return (obj, sub)
                except Exception:
                    pass
            if "axis" in self.kinds:
                try:
                    if type(shp.Surface).__name__ in ("Cylinder", "Cone"):
                        return (obj, sub)
                except Exception:
                    pass
            if "feature" in self.kinds:
                f = creator_of_face(obj, sub)
                if f is not None:
                    return (f, "")
            return None
        if sub.startswith("Edge"):
            if "edge" in self.kinds:
                return (obj, sub)
            if "linear" in self.kinds or "axis" in self.kinds:
                try:
                    if type(shp.Curve).__name__ in ("Line", "LineSegment"):
                        return (obj, sub)
                    if "axis" in self.kinds and type(shp.Curve).__name__ == "Circle":
                        return (obj, sub)
                except Exception:
                    pass
            return None
        if sub.startswith("Vertex") and "vertex" in self.kinds:
            return (obj, sub)
        return None

    def add(self, obj, sub, shp):
        if obj is self.panel.feature and sub and shp is not None:
            # Clicked on the live preview: point at the same face/edge/vertex
            # of the solid the feature is built on instead.
            base = self.panel.base
            name = element_on(base.Shape, shp) if base is not None else None
            if not name:
                return False
            obj, sub = base, name
            try:
                shp = base.Shape.getElement(name)
            except Exception:
                return False
        got = self.accepts(obj, sub, shp)
        if got is None or got[0] is self.panel.feature:
            return False
        if self.single:
            self.items = [got]
        elif got not in self.items:
            self.items.append(got)
        else:
            return True
        self.refresh()
        return True


class FeaturePanel:
    """Subclass: set TITLE, build self.fields / widgets in build(), and
    implement make_feature() and update_feature(feature)."""

    TITLE = "Feature"
    HINT = ""

    def __init__(self, body, feature=None):
        self.body = body
        self.doc = body.Document
        self.feature = feature
        self.creating = feature is None
        self.base = getattr(feature, "BaseFeature", None) if feature is not None else body.Tip
        self.failed = False
        self.fields = []
        self.controls = []        # 3D drag arrows (view_handles.ArrowControl)
        self.active = None
        self._loading = False
        self.doc.openTransaction(self.TITLE if self.creating else "Edit " + feature.Label)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(self.TITLE)
        self.root = QtWidgets.QVBoxLayout(self.form)
        self.build()
        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("background: rgba(200, 60, 60, 60); border: 1px solid #c04040;"
                                 " border-radius: 4px; padding: 6px;")
        self.error.hide()
        self.root.addWidget(self.error)
        if self.HINT:
            h = QtWidgets.QLabel(self.HINT)
            h.setWordWrap(True)
            h.setStyleSheet("color: gray;")
            self.root.addWidget(h)
        self.root.addStretch(1)
        if self.fields:
            self.set_active(self.fields[0])
        if feature is not None:
            self._loading = True
            try:
                self.load(feature)
            finally:
                self._loading = False
        self._seed_from_selection()
        self.changed()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    # ---- for subclasses
    def build(self):
        pass

    def load(self, feature):
        pass

    def ready(self):
        """True when enough is picked to build the feature."""
        return True

    def make_feature(self):
        raise NotImplementedError

    def update_feature(self, f):
        raise NotImplementedError

    def error_text(self):
        return f"<b>The {self.TITLE.lower()} can't be built</b> with these settings."

    # ---- helpers for subclasses
    def add_field(self, field):
        self.fields.append(field)
        self.root.addWidget(field.box)
        return field

    def spin(self, suffix, lo, hi, val, dec=2):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSuffix(suffix)
        s.setValue(val)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(self.changed)
        return s

    def check(self, text, on=False):
        c = QtWidgets.QCheckBox(text)
        c.setChecked(on)
        c.toggled.connect(self.changed)
        return c

    def combo(self, items):
        c = QtWidgets.QComboBox()
        c.addItems(items)
        c.currentIndexChanged.connect(self.changed)
        return c

    # ---- picking
    def set_active(self, field):
        self.active = field
        for f in self.fields:
            f.set_active(f is field)

    def _seed_from_selection(self):
        if self.creating and self.fields:
            self._take_selection()

    def _take_selection(self):
        sel = Gui.Selection.getSelectionEx()
        if not sel or self.active is None:
            return False
        took = None
        for item in sel:
            subs = list(item.SubElementNames) or [""]
            shps = list(item.SubObjects) or [None]
            for sub, shp in zip(subs, shps):
                # The highlighted box first; if it can't take this, the first
                # box that can (empty ones first) - like SOLIDWORKS.
                order = [self.active] + \
                    [f for f in self.fields if f is not self.active and not f.items
                     and f.box.isVisibleTo(self.form)] + \
                    [f for f in self.fields if f is not self.active and f.items
                     and f.box.isVisibleTo(self.form)]
                for fld in order:
                    if fld is not None and fld.add(item.Object, sub, shp):
                        took = fld
                        if fld.single and fld is self.active:
                            # Filled: the next pick goes to the next empty box.
                            nxt = next((f for f in self.fields if f is not fld
                                        and not f.items
                                        and f.box.isVisibleTo(self.form)), None)
                            if nxt is not None:
                                self.set_active(nxt)
                        break
        Gui.Selection.clearSelection()
        if took is not None:
            self.after_pick(took)
        return took is not None

    def after_pick(self, field):
        """Move on to the next empty single field, SOLIDWORKS-style."""
        if field.single:
            for f in self.fields:
                if f is not field and not f.items:
                    self.set_active(f)
                    break
        self.changed()

    def _poll(self):
        try:
            if Gui.Selection.getSelectionEx():
                self._take_selection()
        except Exception:
            pass

    # ---- building
    def _base(self):
        return self.base

    def _show(self, obj, on):
        try:
            if obj is not None:
                obj.ViewObject.Visibility = on
        except Exception:
            pass

    def add_arrow(self, spin, factor=1.0):
        """A drag arrow + 3D number box for a spin box (see show_arrow)."""
        from mechflow_gui import view_handles
        ctl = view_handles.ArrowControl(spin, self.changed, factor)
        self.controls.append(ctl)
        return ctl

    def size(self):
        try:
            d = self.body.Shape.BoundBox.DiagonalLength
            return d if d > 1e-6 else 100.0
        except Exception:
            return 100.0

    def _hide_controls(self):
        for c in self.controls:
            c.hide()

    def changed(self, *_):
        if self._loading:
            return
        if not self.ready():
            self._hide_controls()
            if self.feature is not None and not getattr(self, "DATUM", False):
                self._show(self.feature, False)
            self._show(self._base(), True)
            self.error.hide()
            self.failed = True
            return
        if self.feature is None:
            self.feature = self.make_feature()
            # FreeCAD 1.1 doesn't move the Body's Tip onto patterns, shells
            # etc. made this way; without this the new feature sits after the
            # end of the part (looks rolled back) and the next one builds on
            # the wrong solid.
            if not getattr(self, "DATUM", False):
                try:
                    if self.body.Tip is self.base and \
                            self.feature.isDerivedFrom("PartDesign::Feature"):
                        self.body.Tip = self.feature
                except Exception:
                    pass
        try:
            self.update_feature(self.feature)
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: {self.TITLE}: {e}\n")
        try:
            self.doc.recompute()
        except Exception:
            pass
        f = self.feature
        try:
            ok = f.isValid() and not f.Shape.isNull()
        except Exception:
            ok = False
        self.failed = not ok
        datum = getattr(self, "DATUM", False)   # planes/axes don't replace the solid
        if ok:
            self.error.hide()
            if not datum:
                self._show(self._base(), False)
            self._show(f, True)
        else:
            if not datum:
                self._show(f, False)
            self._show(self._base(), True)
            self._hide_controls()
            self.error.setText(self.error_text() + "<br>Your model is unchanged - fix "
                               "this, or press Cancel.")
            self.error.show()

    # ---- task dialog protocol
    def _stop(self):
        try:
            self._timer.stop()
        except Exception:
            pass
        for c in self.controls:
            try:
                c.close()
            except Exception:
                pass

    def accept(self):
        if self.failed or self.feature is None:
            QtWidgets.QMessageBox.information(
                self.form, self.TITLE,
                "Pick what's needed and fix any message in the panel - or press "
                "Cancel to leave the model unchanged.")
            return False
        self._stop()
        self.finish()
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def finish(self):
        """Last tidy-up before OK (e.g. hide used sketches)."""

    def reject(self):
        self._stop()
        self.doc.abortTransaction()
        try:
            if self.body.Tip is not None:
                self.body.Tip.ViewObject.Visibility = True
        except Exception:
            pass
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def open_panel(cls, feature=None):
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), cls.TITLE, "Finish the open dialog first.")
        return
    body = body_of(feature) if feature is not None else active_body()
    if body is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), cls.TITLE, "Open or create a part first.")
        return
    Gui.Control.showDialog(cls(body, feature))


def face_on(shape, face, tol=1e-4):
    """Name of the face of `shape` that a clicked face lies on (by geometry),
    so clicks on the previewed result map back to the original solid."""
    import Part
    from mechflow_gui import pick_solid
    try:
        p, n = pick_solid._face_probe(face)
    except Exception:
        return None
    probe = Part.Vertex(p)
    for i, g in enumerate(shape.Faces):
        try:
            if probe.distToShape(g)[0] > tol:
                continue
            gn = g.normalAt(*g.Surface.parameter(p))
            if abs(abs(gn.dot(n)) - 1.0) < 1e-3:
                return f"Face{i + 1}"
        except Exception:
            continue
    return None


def element_on(shape, elem, tol=1e-4):
    """Name of the face, edge or vertex of `shape` matching `elem` by geometry."""
    try:
        st = elem.ShapeType
    except Exception:
        return None
    if st == "Face":
        return face_on(shape, elem, tol)
    if st == "Vertex":
        for i, v in enumerate(shape.Vertexes):
            if v.Point.distanceToPoint(elem.Point) < tol:
                return f"Vertex{i + 1}"
        return None
    if st == "Edge":
        try:
            a, b = elem.Vertexes[0].Point, elem.Vertexes[-1].Point
            m = elem.valueAt(0.5 * (elem.FirstParameter + elem.LastParameter))
        except Exception:
            return None
        import Part
        for i, e in enumerate(shape.Edges):
            try:
                if abs(e.Length - elem.Length) > tol * 10:
                    continue
                if all(Part.Vertex(p).distToShape(e)[0] < tol for p in (a, b, m)):
                    return f"Edge{i + 1}"
            except Exception:
                continue
    return None


class BaseFaceField(PickField):
    """Faces of the solid the feature is built on (clicks on the preview are
    matched back to it)."""

    def accepts(self, obj, sub, shp):
        if not sub.startswith("Face") or shp is None:
            return None
        base = self.panel.base
        name = face_on(base.Shape, shp)
        if not name and obj is self.panel.feature:
            name = _offset_face_on(base.Shape, shp)
        return (base, name) if name else None


def _offset_face_on(shape, face):
    """A face clicked on a preview that moved it (e.g. a shell wall): the base
    face facing the same way that's nearest to it."""
    import Part
    from mechflow_gui import pick_solid
    try:
        p, n = pick_solid._face_probe(face)
        limit = shape.BoundBox.DiagonalLength * 0.25
    except Exception:
        return None
    best = None
    probe = Part.Vertex(p)
    for i, g in enumerate(shape.Faces):
        try:
            if type(g.Surface).__name__ != type(face.Surface).__name__:
                continue
            gp, gn = pick_solid._face_probe(g)
            if gn.dot(n) < 0.999:
                continue
            d = probe.distToShape(g)[0]
            if d <= limit and (best is None or d < best[0]):
                best = (d, f"Face{i + 1}")
        except Exception:
            continue
    return best[1] if best else None
