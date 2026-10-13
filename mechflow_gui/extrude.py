# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Boss-Extrude / Cut-Extrude PropertyManager.

Drives FreeCAD's own PartDesign Pad (boss) and Pocket (cut) features, so the
geometry is FreeCAD's - only the dialog is MechFlow's. FreeCAD 1.0 and 1.1 use
different property names for some options, so everything is looked up from
the feature itself rather than assumed.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

BLIND = "Blind"
THROUGH_ALL = "Through All"
UP_TO_NEXT = "Up To Next"
UP_TO_SURFACE = "Up To Surface"
MID_PLANE = "Mid Plane"

# End condition -> FreeCAD "Type" names to try, in order.
TYPE_NAMES = {
    BLIND: ["Length", "Dimension"],
    THROUGH_ALL: ["ThroughAll", "UpToLast"],
    UP_TO_NEXT: ["UpToFirst"],
    UP_TO_SURFACE: ["UpToFace"],
    MID_PLANE: ["Length", "Dimension"],
}

DIR2_CONDITIONS = [BLIND, THROUGH_ALL, UP_TO_NEXT, UP_TO_SURFACE]


# ---------------------------------------------------------------- helpers

def _enums(obj, prop):
    try:
        return list(obj.getEnumerationsOfProperty(prop) or [])
    except Exception:
        return []


def _set_enum(obj, prop, candidates):
    options = _enums(obj, prop)
    for name in candidates:
        if name in options:
            setattr(obj, prop, name)
            return True
    return False


def _side_option(obj, kind):
    """FreeCAD 1.1+ SideType option for 'one', 'two' or 'symmetric'."""
    keys = {"one": ("one",), "two": ("two",), "symmetric": ("symmetric", "mid")}[kind]
    for opt in _enums(obj, "SideType"):
        if any(k in opt.lower() for k in keys):
            return opt
    return None


def _has(obj, prop):
    return prop in obj.PropertiesList


def _body_of(obj):
    for o in obj.InList:
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def _value(q):
    return getattr(q, "Value", q)


def _available_conditions(obj):
    types = _enums(obj, "Type")
    conds = [c for c in (BLIND, THROUGH_ALL, UP_TO_NEXT, UP_TO_SURFACE)
             if any(t in types for t in TYPE_NAMES[c])]
    if _side_option(obj, "symmetric") or _has(obj, "Midplane"):
        conds.append(MID_PLANE)
    return conds


def _condition_of(obj, prop="Type"):
    t = getattr(obj, prop, "")
    for cond in (BLIND, THROUGH_ALL, UP_TO_NEXT, UP_TO_SURFACE):
        if t in TYPE_NAMES[cond]:
            return cond
    return BLIND


# ---------------------------------------------------------------- panel

class ExtrudePanel:
    def __init__(self, feature, sketch, cut, creating):
        self.feature = feature
        self.sketch = sketch
        self.cut = cut
        self.creating = creating
        self.doc = feature.Document
        self.face = None
        self.face2 = None
        self._loading = False
        self.form = self._build_ui()
        from mechflow_gui import view_handles
        self._depth_arrow = view_handles.ArrowControl(self.depth1, self._apply)
        self._load()
        self._apply()

    # ---- UI
    def _spin(self, suffix, lo, hi, val, dec=2):
        s = QtWidgets.QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSuffix(suffix)
        s.setValue(val)
        s.setKeyboardTracking(False)
        s.valueChanged.connect(self._apply)
        return s

    def _build_ui(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Cut-Extrude" if self.cut else "Boss-Extrude")
        root = QtWidgets.QVBoxLayout(w)

        # Direction 1
        g1 = QtWidgets.QGroupBox("Direction 1")
        f1 = QtWidgets.QFormLayout(g1)
        self.cond1 = QtWidgets.QComboBox()
        self.cond1.addItems(_available_conditions(self.feature))
        self.cond1.currentIndexChanged.connect(self._on_condition)
        self.reverse1 = QtWidgets.QCheckBox("Reverse direction")
        self.reverse1.toggled.connect(self._apply)
        self.depth1 = self._spin(" mm", 0.0, 1e6, 10.0)
        self.face_btn1 = QtWidgets.QPushButton("Use selected face")
        self.face_btn1.clicked.connect(lambda: self._pick_face(1))
        self.face_lbl1 = QtWidgets.QLabel("No face selected")
        self.draft1 = QtWidgets.QCheckBox("Draft")
        self.draft1.toggled.connect(self._apply)
        self.draft_angle1 = self._spin("°", 0.0, 89.0, 1.0)
        self.draft_out1 = QtWidgets.QCheckBox("Draft outward")
        self.draft_out1.toggled.connect(self._apply)

        f1.addRow("End condition", self.cond1)
        f1.addRow("", self.reverse1)
        f1.addRow("Depth", self.depth1)
        f1.addRow(self.face_btn1, self.face_lbl1)
        f1.addRow(self.draft1, self.draft_angle1)
        f1.addRow("", self.draft_out1)
        self._form1 = f1
        root.addWidget(g1)

        # Direction 2
        self.g2 = QtWidgets.QGroupBox("Direction 2")
        self.g2.setCheckable(True)
        self.g2.setChecked(False)
        self.g2.toggled.connect(self._on_condition)
        f2 = QtWidgets.QFormLayout(self.g2)
        self.cond2 = QtWidgets.QComboBox()
        self.dir2_full = _has(self.feature, "Type2")
        self.cond2.addItems(DIR2_CONDITIONS if self.dir2_full else [BLIND])
        self.cond2.currentIndexChanged.connect(self._on_condition)
        self.depth2 = self._spin(" mm", 0.0, 1e6, 10.0)
        self.face_btn2 = QtWidgets.QPushButton("Use selected face")
        self.face_btn2.clicked.connect(lambda: self._pick_face(2))
        self.face_lbl2 = QtWidgets.QLabel("No face selected")
        self.draft2 = QtWidgets.QCheckBox("Draft")
        self.draft2.toggled.connect(self._apply)
        self.draft_angle2 = self._spin("°", 0.0, 89.0, 1.0)
        f2.addRow("End condition", self.cond2)
        f2.addRow("Depth", self.depth2)
        f2.addRow(self.face_btn2, self.face_lbl2)
        f2.addRow(self.draft2, self.draft_angle2)
        self._form2 = f2
        root.addWidget(self.g2)

        # Thin Feature (SOLIDWORKS): a wall of given thickness along the outline.
        self.thin = QtWidgets.QGroupBox("Thin Feature")
        self.thin.setCheckable(True)
        self.thin.setChecked(False)
        self.thin.toggled.connect(self._apply)
        ft = QtWidgets.QFormLayout(self.thin)
        self.thin_side = QtWidgets.QComboBox()
        self.thin_side.addItems(["Outside", "Inside", "Mid-plane"])
        self.thin_side.currentIndexChanged.connect(self._apply)
        ft.addRow("Wall", self.thin_side)
        self.thin_t = self._spin(" mm", 0.01, 1e5, 1.0)
        ft.addRow("Thickness", self.thin_t)
        root.addWidget(self.thin)

        self.error = QtWidgets.QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            "background: rgba(200, 60, 60, 60); border: 1px solid #c04040;"
            " border-radius: 4px; padding: 6px;")
        self.error.hide()
        root.addWidget(self.error)
        self.fix_btn = QtWidgets.QPushButton("Make converted lines reference")
        self.fix_btn.setToolTip(
            "Converted model edges are being used as part of the outline. "
            "Make them reference lines (for dimensioning only) and try again.")
        self.fix_btn.clicked.connect(self._fix_converted)
        self.fix_btn.hide()
        root.addWidget(self.fix_btn)

        hint = QtWidgets.QLabel(
            "Tip: for Up To Surface, click a face in the 3D view, then "
            "'Use selected face'.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        root.addWidget(hint)
        root.addStretch(1)
        return w

    def _set_row_visible(self, form, field, visible):
        field.setVisible(visible)
        label = form.labelForField(field)
        if label:
            label.setVisible(visible)

    def _refresh_visibility(self):
        c1 = self.cond1.currentText()
        mid = c1 == MID_PLANE
        self._set_row_visible(self._form1, self.depth1, c1 in (BLIND, MID_PLANE))
        self.face_btn1.setVisible(c1 == UP_TO_SURFACE)
        self.face_lbl1.setVisible(c1 == UP_TO_SURFACE)
        self.reverse1.setVisible(not mid)
        self.draft_out1.setEnabled(self.draft1.isChecked())
        self.draft_angle1.setEnabled(self.draft1.isChecked())
        has_taper = _has(self.feature, "TaperAngle")
        self.draft1.setVisible(has_taper)
        self.draft_angle1.setVisible(has_taper)
        self.draft_out1.setVisible(has_taper)

        self.g2.setEnabled(not mid)
        c2 = self.cond2.currentText()
        self._set_row_visible(self._form2, self.depth2, c2 == BLIND)
        self.face_btn2.setVisible(c2 == UP_TO_SURFACE)
        self.face_lbl2.setVisible(c2 == UP_TO_SURFACE)
        has_taper2 = _has(self.feature, "TaperAngle2")
        self.draft2.setVisible(has_taper2)
        self.draft_angle2.setVisible(has_taper2)
        self.draft_angle2.setEnabled(self.draft2.isChecked())

    def _on_condition(self, *_):
        self._refresh_visibility()
        self._apply()

    def _pick_face(self, which):
        for item in Gui.Selection.getSelectionEx():
            for sub in item.SubElementNames:
                if sub.startswith("Face"):
                    link = (item.Object, [sub])
                    if which == 1:
                        self.face = link
                        self.face_lbl1.setText(f"{item.Object.Label}.{sub}")
                    else:
                        self.face2 = link
                        self.face_lbl2.setText(f"{item.Object.Label}.{sub}")
                    self._apply()
                    return
        QtWidgets.QMessageBox.information(
            self.form, "Up To Surface", "Click a face in the 3D view first.")

    # ---- feature <-> UI
    def _load(self):
        f = self.feature
        self._loading = True
        try:
            binder, inner = self._thin_parts()
            if binder is not None:
                self.thin.setChecked(True)
                legacy = None
                try:
                    legacy = binder.Support[0][0]
                except Exception:
                    pass
                if legacy is not None and legacy.TypeId == "Part::Offset2D":
                    v = float(getattr(legacy.Value, "Value", legacy.Value))
                    if str(legacy.Mode) == "Pipe":
                        self.thin_side.setCurrentText("Mid-plane")
                        self.thin_t.setValue(abs(v) * 2)
                    else:
                        self.thin_side.setCurrentText("Outside" if v >= 0 else "Inside")
                        self.thin_t.setValue(abs(v))
                else:
                    v = float(binder.Offset)
                    if inner is not None:
                        self.thin_side.setCurrentText("Mid-plane")
                        self.thin_t.setValue(abs(v))
                    elif self._sketch_is_open():
                        self.thin_side.setCurrentText("Mid-plane")
                        self.thin_t.setValue(abs(v) * 2)
                    else:
                        self.thin_side.setCurrentText("Outside" if v >= 0 else "Inside")
                        self.thin_t.setValue(abs(v))
            elif self.creating and self._sketch_is_open():
                # An open outline can only be a thin feature, as in SOLIDWORKS.
                self.thin.setChecked(True)
            cond = _condition_of(f)
            symmetric = _side_option(f, "symmetric")
            if (_has(f, "SideType") and symmetric and f.SideType == symmetric) or \
                    getattr(f, "Midplane", False):
                cond = MID_PLANE
            two = _side_option(f, "two")
            dir2 = (_has(f, "SideType") and two and f.SideType == two) or \
                getattr(f, "Type", "") == "TwoLengths"
            if dir2 and cond not in (MID_PLANE,) and getattr(f, "Type", "") == "TwoLengths":
                cond = BLIND

            idx = self.cond1.findText(cond)
            self.cond1.setCurrentIndex(max(idx, 0))
            self.reverse1.setChecked(bool(getattr(f, "Reversed", False)))
            length = _value(getattr(f, "Length", 10.0))
            self.depth1.setValue(length if length > 0 else 10.0)
            taper = _value(getattr(f, "TaperAngle", 0.0))
            self.draft1.setChecked(abs(taper) > 1e-9)
            self.draft_angle1.setValue(abs(taper) or 1.0)
            self.draft_out1.setChecked(taper < 0)
            face = getattr(f, "UpToFace", None)
            if face:
                self.face = (face[0], list(face[1]))
                self.face_lbl1.setText(f"{face[0].Label}.{','.join(face[1])}")

            self.g2.setChecked(bool(dir2))
            if self.dir2_full:
                idx2 = self.cond2.findText(_condition_of(f, "Type2"))
                self.cond2.setCurrentIndex(max(idx2, 0))
            length2 = _value(getattr(f, "Length2", 10.0))
            self.depth2.setValue(length2 if length2 > 0 else 10.0)
            taper2 = _value(getattr(f, "TaperAngle2", 0.0))
            self.draft2.setChecked(abs(taper2) > 1e-9)
            self.draft_angle2.setValue(abs(taper2) or 1.0)
            face2 = getattr(f, "UpToFace2", None)
            if face2:
                self.face2 = (face2[0], list(face2[1]))
                self.face_lbl2.setText(f"{face2[0].Label}.{','.join(face2[1])}")
        finally:
            self._loading = False
        self._refresh_visibility()
        try:
            self._sync_thin_ui()
        except Exception:
            pass

    # ---- Thin Feature
    def _sketch_is_open(self):
        try:
            wires = self.sketch.Shape.Wires
            return bool(wires) and not all(w.isClosed() for w in wires)
        except Exception:
            return False

    def _thin_parts(self):
        """(profile binder, inner binder or None) of a MechFlow thin feature."""
        prof = _link_obj(getattr(self.feature, "Profile", None))
        if prof is not None and _has(prof, "MechFlowThinSketch"):
            return prof, getattr(prof, "MechFlowThinInner", None)
        return None, None

    def _remove(self, *objs):
        for o in objs:
            try:
                if o is not None:
                    self.doc.removeObject(o.Name)
            except Exception:
                pass

    def _new_binder(self, name, before):
        body = _body_of(self.feature)
        b = body.newObject("PartDesign::SubShapeBinder", name)
        b.ViewObject.Visibility = False
        try:   # keep it ahead of the feature in the tree
            body.removeObject(b)
            body.insertObject(b, before, False)
        except Exception:
            pass
        return b

    @staticmethod
    def _offset(binder, value, fill):
        binder.Offset = value
        binder.OffsetFill = fill
        if _has(binder, "OffsetOpenResult"):
            binder.OffsetOpenResult = False
        _set_enum(binder, "OffsetJoinType", ["Intersection", "Arcs"])

    def _apply_thin(self):
        """Thin Feature: the profile becomes a wall of the given thickness,
        made with shape-binder offsets inside the Body (nothing left behind
        when thin is switched off)."""
        f = self.feature
        binder, inner = self._thin_parts()
        if not self.thin.isChecked():
            if binder is not None:
                f.Profile = self.sketch
                self._remove(binder, inner)
            return
        if binder is None:
            binder = self._new_binder("ThinProfile", f)
            binder.addProperty("App::PropertyLink", "MechFlowThinSketch", "MechFlow")
            binder.addProperty("App::PropertyLink", "MechFlowThinInner", "MechFlow")
            binder.MechFlowThinSketch = self.sketch
            f.Profile = binder
        else:
            # Made by an older MechFlow (Part Offset2D outside the Body): tidy up.
            try:
                old = binder.Support[0][0]
                if old is not None and old.TypeId == "Part::Offset2D":
                    binder.Support = [(self.sketch, "")]
                    self._remove(old)
            except Exception:
                pass
            if not _has(binder, "MechFlowThinInner"):
                binder.addProperty("App::PropertyLink", "MechFlowThinInner", "MechFlow")
        t = self.thin_t.value()
        side = self.thin_side.currentText()
        if self._sketch_is_open():
            side = "Mid-plane"           # an open outline is centred on its lines
        if side == "Mid-plane" and not self._sketch_is_open():
            if inner is None:
                inner = self._new_binder("ThinInner", binder)
                binder.MechFlowThinInner = inner
            inner.Support = [(self.sketch, "")]
            self._offset(inner, -t / 2.0, False)
            binder.Support = [(inner, "")]
            self._offset(binder, t, True)
        else:
            binder.Support = [(self.sketch, "")]
            if inner is not None:
                binder.MechFlowThinInner = None
                self._remove(inner)
            if self._sketch_is_open():
                self._offset(binder, t / 2.0, True)
            else:
                self._offset(binder, t if side == "Outside" else -t, True)
        self._sync_thin_ui()

    def _sync_thin_ui(self):
        """Open outlines can only be centred: show that in the Wall box."""
        open_ = self._sketch_is_open()
        if open_ and self.thin_side.currentText() != "Mid-plane":
            self.thin_side.blockSignals(True)
            self.thin_side.setCurrentText("Mid-plane")
            self.thin_side.blockSignals(False)
        self.thin_side.setEnabled(not open_)

    def _apply(self, *_):
        if self._loading:
            return
        try:
            self._apply_thin()
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: thin feature not applied ({e})\n")
        f = self.feature
        c1 = self.cond1.currentText()
        dir2 = self.g2.isChecked() and c1 != MID_PLANE
        new_side = _has(f, "SideType")

        # Sides: FreeCAD 1.1+ uses SideType, 1.0 uses Midplane / TwoLengths.
        if new_side:
            kind = "symmetric" if c1 == MID_PLANE else ("two" if dir2 else "one")
            opt = _side_option(f, kind)
            if opt:
                f.SideType = opt
        elif _has(f, "Midplane"):
            f.Midplane = c1 == MID_PLANE

        if dir2 and not new_side and not self.dir2_full:
            _set_enum(f, "Type", ["TwoLengths"])
        else:
            _set_enum(f, "Type", TYPE_NAMES[c1])

        if c1 in (BLIND, MID_PLANE):
            f.Length = self.depth1.value()
        if _has(f, "Reversed"):
            f.Reversed = self.reverse1.isChecked() and c1 != MID_PLANE
        if c1 == UP_TO_SURFACE and self.face and _has(f, "UpToFace"):
            f.UpToFace = self.face
        if _has(f, "TaperAngle"):
            a = self.draft_angle1.value() if self.draft1.isChecked() else 0.0
            f.TaperAngle = -a if self.draft_out1.isChecked() else a

        if dir2:
            if self.dir2_full:
                _set_enum(f, "Type2", TYPE_NAMES[self.cond2.currentText()])
            if _has(f, "Length2"):
                f.Length2 = self.depth2.value()
            if (self.cond2.currentText() == UP_TO_SURFACE and self.face2
                    and _has(f, "UpToFace2")):
                f.UpToFace2 = self.face2
            if _has(f, "TaperAngle2"):
                f.TaperAngle2 = self.draft_angle2.value() if self.draft2.isChecked() else 0.0

        try:
            self.doc.recompute()
        except Exception:
            pass
        self._check_result()
        self._update_handle()

    # ---- drag arrow + depth box in the 3D view (like SOLIDWORKS)
    def _update_handle(self):
        ctl = getattr(self, "_depth_arrow", None)
        if ctl is None:
            return
        c1 = self.cond1.currentText()
        if self.sketch is None or c1 not in (BLIND, MID_PLANE):
            ctl.hide()
            return
        try:
            body = _body_of(self.feature)
            gpl = body.getGlobalPlacement() if body is not None else App.Placement()
            bb = self.sketch.Shape.BoundBox
            centre = gpl.multVec(bb.Center)
            n = self.sketch.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            d = n * (-1.0 if self.cut else 1.0)       # a cut goes into the part
            if c1 != MID_PLANE and self.reverse1.isChecked():
                d = d * -1.0
            size = bb.DiagonalLength
            try:
                size = max(size, body.Shape.BoundBox.DiagonalLength)
            except Exception:
                pass
            ctl.show(centre, d, max(1.0, size * 0.06),
                     factor=2.0 if c1 == MID_PLANE else 1.0)
        except Exception:
            ctl.hide()

    def _close_handle(self):
        ctl = getattr(self, "_depth_arrow", None)
        if ctl is not None:
            ctl.close()

    # ---- error handling
    def _base(self):
        """The solid this feature builds on (shown if this feature fails)."""
        return getattr(self.feature, "BaseFeature", None)

    def _open_ends(self):
        """Number of loose ends in the sketch's profile (0 = closed)."""
        try:
            shape = self.sketch.Shape
            counts = {}
            for e in shape.Edges:
                if e.isClosed():
                    continue
                for v in (e.Vertexes[0], e.Vertexes[-1]):
                    key = (round(v.X, 4), round(v.Y, 4), round(v.Z, 4))
                    counts[key] = counts.get(key, 0) + 1
            return sum(1 for c in counts.values() if c == 1)
        except Exception:
            return None

    def _check_result(self):
        f = self.feature
        try:
            ok = f.isValid() and not f.Shape.isNull()
        except Exception:
            ok = False
        self.failed = not ok
        base = self._base()
        if ok:
            self.error.hide()
            self.fix_btn.hide()
            if getattr(self, "_base_shown", False) and base is not None:
                try:
                    base.ViewObject.Visibility = False   # new result replaces it
                except Exception:
                    pass
                self._base_shown = False
            return
        # Keep the previous solid visible instead of an empty view.
        if base is not None:
            try:
                base.ViewObject.Visibility = True
                self._base_shown = True
            except Exception:
                pass
        try:
            status = " ".join(f.getStatusString().split()) if hasattr(f, "getStatusString") else ""
        except Exception:
            status = ""
        ends = self._open_ends() if self.sketch is not None else None
        converted = []
        try:
            from mechflow_gui import convert_ref
            converted = convert_ref.defining_externals(self.sketch) if self.sketch else []
        except Exception:
            converted = []
        self.fix_btn.setVisible(bool(converted))
        if converted:
            msg = (f"<b>The outline includes {len(converted)} converted model "
                   f"edge{'s' if len(converted) != 1 else ''}</b>, so it isn't closed. "
                   "If you only converted them to dimension to, click the button below.")
        elif ends:
            msg = (f"<b>The sketch isn't a closed outline</b> - it has {ends} loose "
                   f"end{'s' if ends != 1 else ''}. Edit the sketch and make sure every "
                   "line meets the next one. Converted model edges must be construction "
                   "(reference) lines, not part of the outline.")
        elif "not closed" in status.lower():
            msg = ("<b>The sketch isn't a closed outline.</b> Edit the sketch and make "
                   "sure every line meets the next one.")
        elif status:
            msg = f"<b>This feature can't be built:</b> {status}"
        else:
            msg = "<b>This feature can't be built</b> with these settings."
        self.error.setText(msg + "<br>Your model is unchanged - fix this, or press Cancel.")
        self.error.show()

    def _fix_converted(self):
        from mechflow_gui import convert_ref
        if self.sketch is None:
            return
        changed = convert_ref.make_reference(self.sketch)
        if not changed:
            QtWidgets.QMessageBox.information(
                self.form, self.form.windowTitle(),
                "MechFlow couldn't change those lines automatically.\n\n"
                "Edit the sketch, select the converted lines and click "
                "Construction Geometry, then try again.")
            return
        self._apply()

    # ---- task dialog protocol
    def accept(self):
        self._apply()
        if getattr(self, "failed", False):
            QtWidgets.QMessageBox.warning(
                self.form, self.form.windowTitle(),
                "This feature can't be built yet - see the message in the panel.\n\n"
                "Fix the sketch, or press Cancel to leave the model unchanged.")
            return False
        self._close_handle()
        if self.sketch is not None:
            self.sketch.ViewObject.Visibility = False
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._close_handle()
        if self.creating and self.sketch is not None:
            self.sketch.ViewObject.Visibility = True
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


# ---------------------------------------------------------------- entry points

def _link_obj(v):
    return v[0] if isinstance(v, (tuple, list)) else v


def _sketch_of(feature):
    prof = _link_obj(getattr(feature, "Profile", None))
    if prof is not None and _has(prof, "MechFlowThinSketch"):
        return prof.MechFlowThinSketch
    return prof


def _selected_sketch():
    # Clicking Extrude while still inside a sketch: close it and use it.
    gdoc = Gui.ActiveDocument
    if gdoc is not None:
        try:
            vp = gdoc.getInEdit()
        except Exception:
            vp = None
        obj = getattr(vp, "Object", None)
        if obj is not None and obj.TypeId == "Sketcher::SketchObject":
            gdoc.resetEdit()
            return obj
    for o in Gui.Selection.getSelection():
        if o.TypeId == "Sketcher::SketchObject":
            return o
    return None


def create(cut=False):
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Extrude", "Finish the open dialog first.")
        return
    sketch = _selected_sketch()
    if sketch is None:
        from mechflow_gui import commands
        if commands.selection_is_sketchable():
            # Plane or face selected: start a sketch on it, like SOLIDWORKS.
            Gui.runCommand("PartDesign_NewSketch", 0)
            return
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Cut-Extrude" if cut else "Boss-Extrude",
            "Select a sketch (or a plane / flat face to sketch on) first.")
        return
    body = _body_of(sketch)
    if body is None:
        QtWidgets.QMessageBox.warning(
            Gui.getMainWindow(), "Extrude", "That sketch is not inside a Body.")
        return

    doc = sketch.Document
    doc.openTransaction("Cut-Extrude" if cut else "Boss-Extrude")
    feat = body.newObject("PartDesign::Pocket" if cut else "PartDesign::Pad",
                          "Pocket" if cut else "Pad")
    feat.Profile = sketch
    if not cut:
        feat.Length = 10.0
    sketch.ViewObject.Visibility = False
    Gui.Control.showDialog(ExtrudePanel(feat, sketch, cut, creating=True))


def edit(feature):
    if Gui.Control.activeDialog():
        return
    cut = feature.TypeId == "PartDesign::Pocket"
    feature.Document.openTransaction("Edit " + feature.Label)
    sketch = _sketch_of(feature)
    Gui.Control.showDialog(ExtrudePanel(feature, sketch, cut, creating=False))
