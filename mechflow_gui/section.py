# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Section View.

- Click Section View, click a flat face, drag the arrow (or type a distance).
- Up to 3 sections: with more than one, the corner where they overlap is cut
  away (a quarter / eighth cut), as in SOLIDWORKS.
- OK keeps the section showing; Cancel undoes the changes made in the panel.
- Click Section View again to edit the section, or remove it.

The section is a temporary display copy: the real part is never changed, the
copy is never saved (it's taken off while saving), and it follows edits to
the part.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

TEMP_PREFIX = "MechFlow_Section"
CAP_COLOUR = (0.62, 0.78, 0.92)
MAX_SECTIONS = 3

_state = None      # the section currently on show (SectionState)
_panel = None      # the open Section View panel
_observer = None


# ======================================================================= model

_CONTAINERS = ("App::Part", "Assembly::AssemblyObject")
_SKIP_TYPES = ("Sketcher::SketchObject", "Assembly::JointGroup", "Assembly::ViewGroup",
               "Assembly::BomGroup", "Assembly::BomObject", "Spreadsheet::Sheet")


def _is_container(o):
    try:
        lo = o.getLinkedObject(True)
    except Exception:
        lo = o
    return lo.TypeId in _CONTAINERS or lo.isDerivedFrom("App::Part")


def _visible(o):
    try:
        return bool(o.ViewObject.Visibility)
    except Exception:
        return False


def _top_level(o):
    """Not inside a body, Part or assembly (those are reached through it)."""
    try:
        if o.getParentGeoFeatureGroup() is not None:
            return False
    except Exception:
        pass
    for parent in o.InList:
        if parent.TypeId in _CONTAINERS or parent.isDerivedFrom("App::Part") or \
                parent.TypeId == "PartDesign::Body" or parent.TypeId.startswith("Assembly::"):
            return False
    return True


def _solids_on_show(doc):
    """What a section cuts: visible bodies and loose solids, and visible
    Parts / assemblies / links (cut through everything inside them)."""
    out = []
    for o in doc.Objects:
        if o.Name.startswith(TEMP_PREFIX) or o.Name.startswith("MechFlow_Pick"):
            continue
        if not _visible(o) or o.TypeId in _SKIP_TYPES:
            continue
        if _is_container(o):
            if _top_level(o):
                out.append(o)
            continue
        if o.TypeId == "PartDesign::Body" or (
                o.isDerivedFrom("Part::Feature") and not o.InList
                and not o.isDerivedFrom("PartDesign::Feature")):
            if o.TypeId == "PartDesign::Body" and not _top_level(o):
                continue
            shape = getattr(o, "Shape", None)
            try:
                if shape is not None and not shape.isNull() and shape.Solids:
                    out.append(o)
            except Exception:
                pass
    return out


def _leaves(o):
    """[(global solid shape, view object for its colour)] for one original:
    itself, or every visible solid inside a Part / assembly / link."""
    import Part
    if not _is_container(o):
        return [(o.Shape, o.ViewObject)]
    out = []

    def walk(path, obj):
        try:
            lo = obj.getLinkedObject(True)
        except Exception:
            lo = obj
        if lo.TypeId in _CONTAINERS or lo.isDerivedFrom("App::Part"):
            for c in getattr(lo, "Group", []):
                if c.TypeId.startswith("App::Origin") or c.TypeId in _SKIP_TYPES:
                    continue
                try:
                    if c.getParentGeoFeatureGroup() not in (lo, None):
                        continue
                except Exception:
                    pass
                if not _visible(c):
                    continue
                walk(path + c.Name + ".", c)
            return
        try:
            sh = Part.getShape(o, path) if path else Part.getShape(o)
        except Exception:
            return
        try:
            if sh.isNull() or not sh.Solids:
                return
        except Exception:
            return
        out.append((sh, getattr(lo, "ViewObject", None) or getattr(obj, "ViewObject", None)))
    walk("", o)
    return out


def _look(vo):
    """Colour key + a way to copy it onto another view object."""
    try:
        app = vo.ShapeAppearance
        m = app[0]
        return (tuple(round(c, 3) for c in m.DiffuseColor[:3]), round(m.Transparency, 2)), app
    except Exception:
        try:
            return (tuple(vo.ShapeColor[:3]), 0), None
        except Exception:
            return ((0.8, 0.8, 0.8), 0), None


def _side(shape, planes):
    """'keep' if wholly outside the cut-away region, 'gone' if wholly
    inside it, else 'cut'. The region is where every plane's box overlaps."""
    bb = shape.BoundBox
    corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax)
               for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]
    all_in = True
    for base, n, _d in planes:
        ds = [(c - base).dot(n) for c in corners]   # > 0: removed side
        if max(ds) <= 1e-6:
            return "keep"
        if min(ds) < -1e-6:
            all_in = False
    return "gone" if all_in else "cut"


def _plane_rotation(n):
    from mechflow_gui import normal_to
    return normal_to._camera_rotation(n)


class SectionState:
    """What's on show: the sections and the temporary cut copies."""

    def __init__(self, doc, originals=None):
        self.doc = doc
        self.originals = originals if originals is not None else _solids_on_show(doc)
        self.sections = []     # dicts: p, n, distance, depth
        self.temps = []
        self.caps = []
        self.busy = False
        self._saving = False

    def bbox(self):
        box = None
        import Part
        for o in self.originals:
            try:
                bb = (Part.getShape(o) if _is_container(o) else o.Shape).BoundBox
                if not bb.isValid():
                    continue
                box = bb if box is None else box.united(bb)
            except Exception:
                pass
        return box

    def snapshot(self):
        return [dict(s) for s in self.sections]

    # ---- display
    def clear(self, show_originals=True):
        for sg, node in self.caps:
            try:
                sg.removeChild(node)
            except Exception:
                pass
        self.caps = []
        for name in self.temps:
            if self.doc.getObject(name) is not None:
                try:
                    self.doc.removeObject(name)
                except Exception:
                    pass
        self.temps = []
        if show_originals:
            for o in self.originals:
                try:
                    o.ViewObject.Visibility = True
                except Exception:
                    pass

    def apply(self):
        """(Re)build the cut copies for the current sections."""
        import Part
        from mechflow_gui import pick_solid
        self.busy = True
        try:
            self.clear(show_originals=False)
            active = [s for s in self.sections if s.get("p") is not None]
            if not active:
                for o in self.originals:
                    try:
                        o.ViewObject.Visibility = True
                    except Exception:
                        pass
                return
            bb = self.bbox()
            size = max(10.0, bb.DiagonalLength * 4.0) if bb else 1000.0
            half = size / 2.0
            remove = None
            planes = []
            for s in active:
                base = s["p"] - s["n"] * s["distance"]
                box = Part.makeBox(size, size, size, App.Vector(-half, -half, 0))
                box.Placement = App.Placement(base, _plane_rotation(s["n"]))
                remove = box if remove is None else remove.common(box)
                planes.append((base, s["n"], s["distance"]))
            groups = {}        # colour -> [appearance, [solids]]
            cap_faces = []
            for o in self.originals:
                for sh, vo in _leaves(o):
                    side = _side(sh, planes)
                    if side == "gone":
                        continue
                    if side == "cut":
                        try:
                            sh = sh.cut(remove)
                        except Exception as e:
                            App.Console.PrintWarning(
                                f"MechFlow: couldn't section part of {o.Label} ({e})\n")
                            continue
                        for face in sh.Faces:
                            try:
                                if type(face.Surface).__name__ != "Plane":
                                    continue
                                fp, fn = pick_solid._face_probe(face)
                                for base, n, dist in planes:
                                    if dist <= 1e-6:
                                        continue
                                    if abs(abs(fn.dot(n)) - 1.0) < 1e-4 and \
                                            abs((fp - base).dot(n)) < 1e-3:
                                        cap_faces.append(face)
                                        break
                            except Exception:
                                continue
                    key, app = _look(vo)
                    g = groups.setdefault(key, [app, [], vo])
                    g[1].extend(sh.Solids)
                try:
                    o.ViewObject.Visibility = False
                except Exception:
                    pass
            for i, (key, (app, solids, vo)) in enumerate(groups.items()):
                if not solids:
                    continue
                t = self.doc.addObject("Part::Feature", f"{TEMP_PREFIX}_{i}")
                t.Shape = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
                t.Label = "Section view"
                self.temps.append(t.Name)
                tv = t.ViewObject
                try:
                    tv.ShowInTree = False
                except Exception:
                    pass
                try:
                    if app is not None:
                        tv.ShapeAppearance = app
                    else:
                        tv.ShapeColor = key[0]
                except Exception:
                    pass
            node = _cap_node(cap_faces) if cap_faces else None
            sg = pick_solid._scene()
            if node is not None and sg is not None:
                sg.addChild(node)
                self.caps.append((sg, node))
            self.doc.recompute()
        finally:
            self.busy = False


def _cap_node(faces):
    from pivy import coin
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)
    off = coin.SoPolygonOffset()
    off.factor = -2.0
    off.units = -2.0
    root.addChild(off)
    mat = coin.SoMaterial()
    mat.diffuseColor = CAP_COLOUR
    mat.emissiveColor = tuple(c * 0.5 for c in CAP_COLOUR)
    root.addChild(mat)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
    root.addChild(hints)
    pts, idx = [], []
    for f in faces:
        try:
            p, tris = f.tessellate(0.1)
        except Exception:
            continue
        b = len(pts)
        pts.extend([[v.x, v.y, v.z] for v in p])
        for a, c, d in tris:
            idx.extend([b + a, b + c, b + d, -1])
    if not pts:
        return None
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(pts), pts)
    root.addChild(coords)
    fs = coin.SoIndexedFaceSet()
    fs.coordIndex.setValues(0, len(idx), idx)
    root.addChild(fs)
    return root


# ======================================================================= panel

class _ViewBox(QtWidgets.QDoubleSpinBox):
    """Distance box floating in the 3D view next to the drag arrow."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("MechFlow_SectionBox")
        self.setDecimals(2)
        self.setSuffix(" mm")
        self.setKeyboardTracking(False)
        self.setFixedWidth(96)
        self.setStyleSheet(
            "#MechFlow_SectionBox { background: rgba(255,255,255,235); color: #000;"
            " border: 1px solid #569de5; border-radius: 3px; padding: 1px 3px; }")


class _ClickBox(QtWidgets.QGroupBox):
    """Section box: click anywhere on it to make it the one you're editing."""

    def __init__(self, title, on_click):
        super().__init__(title)
        self._on_click = on_click
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def mousePressEvent(self, e):
        self._on_click()
        super().mousePressEvent(e)


class _ClickSpin(QtWidgets.QDoubleSpinBox):
    """Distance box that also selects its section when you click into it."""

    def __init__(self, on_focus):
        super().__init__()
        self._on_focus = on_focus

    def focusInEvent(self, e):
        self._on_focus()
        super().focusInEvent(e)


class SectionPanel:
    def __init__(self, state, editing):
        self.state = state
        self.editing = editing
        self.before = state.snapshot()
        if not state.sections:
            state.sections = [self._blank()]
        self.current = 0
        self._bbox = state.bbox()
        self._drag = None          # (scene graph, root, dragger, scale)
        self._preview = None       # (scene graph, root, transform)
        self._last_drag = 0.0
        self.form = self._build_ui()
        self.viewbox = None
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        if mdi is not None:
            self.viewbox = _ViewBox(mdi)
            self.viewbox.valueChanged.connect(self._typed)
            self.viewbox.hide()
        self._settle = QtCore.QTimer()
        self._settle.setSingleShot(True)
        self._settle.setInterval(250)
        self._settle.timeout.connect(self.state.apply)
        self._ticker = QtCore.QTimer()
        self._ticker.setInterval(60)
        self._ticker.timeout.connect(self._tick)
        self._activate(self._first_unpicked())
        Gui.Selection.clearSelection()
        self._ticker.start()

    @staticmethod
    def _blank():
        return {"p": None, "n": None, "distance": 0.0, "depth": 100.0}

    # ---- UI
    def _build_ui(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Section View")
        root = QtWidgets.QVBoxLayout(w)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Sections"))
        self.count = QtWidgets.QComboBox()
        self.count.addItems([str(i) for i in range(1, MAX_SECTIONS + 1)])
        self.count.setCurrentIndex(max(0, len(self.state.sections) - 1))
        self.count.currentIndexChanged.connect(self._count_changed)
        top.addWidget(self.count)
        top.addStretch(1)
        root.addLayout(top)

        self.rows = []
        for i in range(MAX_SECTIONS):
            box = _ClickBox(f"Section {i + 1}", lambda k=i: self._select(k))
            v = QtWidgets.QVBoxLayout(box)
            status = QtWidgets.QLabel()
            status.setWordWrap(True)
            v.addWidget(status)
            h = QtWidgets.QHBoxLayout()
            h.addWidget(QtWidgets.QLabel("Distance"))
            spin = _ClickSpin(lambda k=i: self._select(k))
            spin.setRange(0.0, 1e5)
            spin.setDecimals(2)
            spin.setSuffix(" mm")
            spin.setKeyboardTracking(False)
            spin.valueChanged.connect(lambda val, k=i: self._row_typed(k, val))
            h.addWidget(spin, 1)
            v.addLayout(h)
            root.addWidget(box)
            self.rows.append((box, status, spin))

        self.remove = QtWidgets.QPushButton("Remove Section")
        self.remove.setToolTip("Turn the section view off")
        self.remove.clicked.connect(self._remove_all)
        self.remove.setVisible(self.editing)
        root.addWidget(self.remove)

        note = QtWidgets.QLabel("Click a section's box to work on it, then click a "
                                "flat face and drag the arrow or type a distance. With "
                                "2 or 3 sections the corner where they overlap is cut "
                                "away. Your part isn't changed.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        root.addWidget(note)
        root.addStretch(1)
        return w

    def _refresh_rows(self):
        n = len(self.state.sections)
        for i, (box, status, spin) in enumerate(self.rows):
            box.setVisible(i < n)
            if i >= n:
                continue
            s = self.state.sections[i]
            active = i == self.current
            box.setStyleSheet("QGroupBox { border: 2px solid #569de5; }" if active else "")
            if s["p"] is None:
                status.setText("<b>Click a flat face</b>" if active else "No face yet")
            else:
                status.setText("Face picked" + (" - drag the arrow" if active else ""))
            spin.blockSignals(True)
            spin.setRange(0.0, round(s["depth"], 2))
            spin.setValue(s["distance"])
            spin.setEnabled(s["p"] is not None)
            spin.blockSignals(False)

    def _first_unpicked(self):
        for i, s in enumerate(self.state.sections):
            if s["p"] is None:
                return i
        return 0

    def _count_changed(self, idx):
        want = idx + 1
        secs = self.state.sections
        while len(secs) < want:
            secs.append(self._blank())
        del secs[want:]
        if any(s["p"] is None for s in secs):
            self._activate(self._first_unpicked())
        else:
            self._activate(min(self.current, want - 1))
        self.state.apply()

    def _remove_all(self):
        global _state
        self._finish()
        self.state.sections = []
        self.state.clear()
        _state = None
        Gui.Control.closeDialog()

    # ---- active section + handles
    def _select(self, k):
        if k != self.current:
            self._activate(k)

    def _activate(self, k):
        self.current = max(0, min(k, len(self.state.sections) - 1))
        self._refresh_rows()
        self._make_handles()

    def _remove_handles(self):
        for h in (self._drag, self._preview):
            if h is not None:
                try:
                    h[0].removeChild(h[1])
                except Exception:
                    pass
        self._drag = self._preview = None
        if self.viewbox is not None:
            self.viewbox.hide()

    def _make_handles(self):
        from pivy import coin
        from mechflow_gui import pick_solid, plane_art
        self._remove_handles()
        s = self.state.sections[self.current]
        sg = pick_solid._scene()
        if sg is None or s["p"] is None:
            return
        p, n = s["p"], s["n"]
        size = self._bbox.DiagonalLength if self._bbox else 100.0
        scale = max(1.0, size * 0.06)
        root = coin.SoSeparator()
        tf = coin.SoTransform()
        tf.translation = (p.x, p.y, p.z)
        q = App.Rotation(App.Vector(1, 0, 0), n * -1).Q
        tf.rotation.setValue(q[0], q[1], q[2], q[3])
        root.addChild(tf)
        sc = coin.SoScale()
        sc.scaleFactor = (scale, scale, scale)
        root.addChild(sc)
        dragger = coin.SoTranslate1Dragger()
        dragger.translation.setValue(s["distance"] / scale, 0, 0)
        root.addChild(dragger)
        sg.addChild(root)
        self._drag = (sg, root, dragger, scale)
        self._last_drag = s["distance"]

        proot = coin.SoSeparator()
        ptf = coin.SoTransform()
        proot.addChild(ptf)
        proot.addChild(plane_art.build(_plane_rotation(n), App.Vector(0, 0, 0),
                                       size * 1.1, None, plane_art.SW_ORANGE, 0.8))
        sg.addChild(proot)
        self._preview = (sg, proot, ptf)
        self._move_preview()
        if self.viewbox is not None:
            self.viewbox.blockSignals(True)
            self.viewbox.setRange(0.0, round(s["depth"], 2))
            self.viewbox.setValue(s["distance"])
            self.viewbox.blockSignals(False)

    def _move_preview(self):
        s = self.state.sections[self.current]
        if self._preview is None or s["p"] is None:
            return
        c = s["p"] - s["n"] * s["distance"]
        self._preview[2].translation = (c.x, c.y, c.z)

    def _place_viewbox(self):
        s = self.state.sections[self.current]
        if self.viewbox is None or s["p"] is None or self._drag is None:
            return
        tip = s["p"] - s["n"] * s["distance"]
        try:
            view = Gui.ActiveDocument.ActiveView
            fn = getattr(view, "getPointOnViewport", None) or view.getPointOnScreen
            x, y = fn(tip)
            mdi = self.viewbox.parentWidget()
            sub = mdi.activeSubWindow()
            w = sub.widget() if sub is not None else mdi
            h = view.getSize()[1] if hasattr(view, "getSize") else w.height()
            pt = w.mapTo(mdi, QtCore.QPoint(int(x) + 18, int(h - y) - 12))
            pt.setX(max(0, min(pt.x(), mdi.width() - self.viewbox.width())))
            pt.setY(max(0, min(pt.y(), mdi.height() - self.viewbox.height())))
            self.viewbox.move(pt)
        except Exception:
            self.viewbox.move(12, 40)
        self.viewbox.show()
        self.viewbox.raise_()

    # ---- picking and distance
    def _depth_from(self, p, n):
        b = self._bbox
        if b is None:
            return 100.0
        corners = [App.Vector(x, y, z) for x in (b.XMin, b.XMax)
                   for y in (b.YMin, b.YMax) for z in (b.ZMin, b.ZMax)]
        return max(0.1, max((p - c).dot(n) for c in corners))

    def _take_face(self):
        for item in Gui.Selection.getSelectionEx():
            for sub, shp in zip(item.SubElementNames, item.SubObjects):
                if not sub.startswith("Face"):
                    continue
                try:
                    if type(shp.Surface).__name__ != "Plane":
                        continue
                    from mechflow_gui import pick_solid
                    p, n = pick_solid._face_probe(shp)
                except Exception:
                    continue
                n = App.Vector(n).normalize()
                Gui.Selection.clearSelection()
                s = self.state.sections[self.current]
                s.update(p=p, n=n, distance=0.0, depth=self._depth_from(p, n))
                self._refresh_rows()
                self._make_handles()
                self.state.apply()
                return True
        if Gui.Selection.getSelectionEx():
            Gui.Selection.clearSelection()
        return False

    def _set_distance(self, d, from_drag):
        s = self.state.sections[self.current]
        if s["p"] is None:
            return
        d = max(0.0, min(s["depth"], d))
        s["distance"] = d
        spin = self.rows[self.current][2]
        for box in (spin, self.viewbox):
            if box is not None and abs(box.value() - d) > 1e-6:
                box.blockSignals(True)
                box.setValue(d)
                box.blockSignals(False)
        if not from_drag and self._drag is not None:
            self._drag[2].translation.setValue(d / self._drag[3], 0, 0)
            self._last_drag = d
        self._move_preview()
        self._settle.start()

    def _typed(self, v):
        self._set_distance(float(v), from_drag=False)

    def _row_typed(self, k, v):
        if k != self.current:
            self._activate(k)
        self._set_distance(float(v), from_drag=False)

    def _tick(self):
        if Gui.Selection.getSelectionEx():
            self._take_face()
            return
        if self._drag is None:
            return
        dragger, scale = self._drag[2], self._drag[3]
        try:
            d = dragger.translation.getValue()[0] * scale
        except Exception:
            return
        if abs(d - self._last_drag) > 1e-6:
            depth = self.state.sections[self.current]["depth"]
            clamped = max(0.0, min(depth, d))
            if abs(clamped - d) > 1e-6:
                dragger.translation.setValue(clamped / scale, 0, 0)
            self._last_drag = clamped
            self._set_distance(clamped, from_drag=True)
        self._place_viewbox()

    # ---- closing
    def _finish(self):
        global _panel
        _panel = None
        for t in (self._settle, self._ticker):
            try:
                t.stop()
            except Exception:
                pass
        self._remove_handles()
        if self.viewbox is not None:
            try:
                self.viewbox.deleteLater()
            except Exception:
                pass
            self.viewbox = None

    def accept(self):
        global _state
        self._finish()
        self.state.sections = [s for s in self.state.sections if s["p"] is not None]
        if self.state.sections:
            self.state.apply()
            _state = self.state
            _remember_shape()
        else:
            self.state.clear()
            _state = None
        Gui.Control.closeDialog()
        return True

    def reject(self):
        global _state
        self._finish()
        self.state.sections = self.before
        if self.before:
            self.state.apply()          # back to how it was before editing
            _state = self.state
            _remember_shape()
        else:
            self.state.clear()
            _state = None
        Gui.Control.closeDialog()
        return True


# ======================================================================= saving / edits

_last_shapes = {}


def _shape_key():
    key = []
    for o in _state.originals if _state else []:
        try:
            import Part
            sh = Part.getShape(o) if _is_container(o) else o.Shape
            key.append((o.Name, round(sh.Volume, 6), len(sh.Faces), str(sh.BoundBox)))
        except Exception:
            pass
    return tuple(key)


def _remember_shape():
    if _state is not None:
        _last_shapes[_state.doc.Name] = _shape_key()


def _refresh_after_edit():
    """Rebuild the section if the part's shape changed."""
    if _state is None or _state.busy or _panel is not None:
        return
    key = _shape_key()
    if _last_shapes.get(_state.doc.Name) != key:
        _last_shapes[_state.doc.Name] = key
        _state.apply()


class _DocObserver:
    """Never save the section copy; follow edits to the part."""

    def slotStartSaveDocument(self, doc, filename):
        if _state is not None and _state.doc == doc and _state.temps:
            _state._saving = True
            _state.clear(show_originals=True)

    def slotFinishSaveDocument(self, doc, filename):
        if _state is not None and _state._saving:
            _state._saving = False
            QtCore.QTimer.singleShot(0, _state.apply)

    def slotRecomputedDocument(self, doc):
        if _state is None or _state.doc != doc or _state.busy or _state._saving:
            return
        QtCore.QTimer.singleShot(0, _refresh_after_edit)

    def slotDeletedDocument(self, doc):
        global _state
        if _state is not None and _state.doc == doc:
            _state = None


def install():
    global _observer
    if _observer is None:
        _observer = _DocObserver()
        App.addDocumentObserver(_observer)


# ======================================================================= entry

def toggle():
    """Section View button: new section, or edit the one on show."""
    global _panel
    doc = App.ActiveDocument
    if doc is None or _panel is not None:
        return
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Section View", "Finish the open dialog first.")
        return
    if _state is not None and _state.doc == doc:
        _panel = SectionPanel(_state, editing=True)
    else:
        tidy_left_overs(doc)
        _panel = SectionPanel(SectionState(doc), editing=False)
    Gui.Control.showDialog(_panel)


def tidy_left_overs(doc=None):
    """Remove section copies left behind if FreeCAD closed mid-section."""
    for d in ([doc] if doc else App.listDocuments().values()):
        for o in list(d.Objects):
            if o.Name.startswith(TEMP_PREFIX):
                try:
                    d.removeObject(o.Name)
                except Exception:
                    pass
