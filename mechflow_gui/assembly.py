# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style assemblies on FreeCAD 1.1's Assembly.

- New Assembly: a new assembly document, ready for Insert Components.
- Mate: click two faces / edges / points on different components; MechFlow
  suggests the mate (two flat faces -> Coincident, two round faces ->
  Concentric, round + flat -> Tangent) and the parts move as you choose.
  Standard mates: Coincident, Parallel, Perpendicular, Tangent, Concentric,
  Lock, Distance, Angle; mechanical: Hinge, Slider. Aligned / Anti-Aligned
  flips the part. Mates appear in the tree's Mates folder with SOLIDWORKS
  names (Coincident1, Concentric1, ...).

Each mate is one of FreeCAD's assembly joints underneath:
  Coincident, Tangent -> Distance 0   Concentric -> Cylindrical
  Distance -> Distance               Angle -> Angle
  Parallel / Perpendicular -> same   Lock -> Fixed
  Hinge -> Revolute                  Slider -> Slider
"""

import FreeCAD as App
from mechflow_gui import edge_curve, curve_name  # noqa: F401
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

# SOLIDWORKS mate: (FreeCAD joint type, value property or None, icon)
MATES = {
    "Coincident": ("Distance", None, "Assembly_CreateJointDistance"),
    "Parallel": ("Parallel", None, "Assembly_CreateJointParallel"),
    "Perpendicular": ("Perpendicular", None, "Assembly_CreateJointPerpendicular"),
    "Tangent": ("Distance", None, "Assembly_CreateJointDistance"),
    "Concentric": ("Cylindrical", None, "Assembly_CreateJointCylindrical"),
    "Lock": ("Fixed", None, "Assembly_CreateJointFixed"),
    "Distance": ("Distance", "Distance", "Assembly_CreateJointDistance"),
    "Angle": ("Angle", "Angle", "Assembly_CreateJointAngle"),
    "Hinge": ("Revolute", None, "Assembly_CreateJointRevolute"),
    "Slider": ("Slider", None, "Assembly_CreateJointSlider"),
}
STANDARD = ["Coincident", "Parallel", "Perpendicular", "Tangent", "Concentric",
            "Lock", "Distance", "Angle"]
MECHANICAL = ["Hinge", "Slider"]


def _assembly_modules():
    import sys
    path = App.getHomePath() + "Mod/Assembly"
    if path not in sys.path:
        sys.path.append(path)
    import JointObject
    import UtilsAssembly
    return JointObject, UtilsAssembly


def active_assembly():
    try:
        _J, U = _assembly_modules()
        a = U.activeAssembly()
        if a is not None:
            return a
    except Exception:
        pass
    doc = App.ActiveDocument
    if doc is None:
        return None
    found = [o for o in doc.Objects if o.isDerivedFrom("Assembly::AssemblyObject")]
    return found[0] if len(found) == 1 else None


def ensure_active(asm):
    """FreeCAD's assembly tools work on the assembly open for editing."""
    try:
        if not asm.ViewObject.isInEditMode():
            Gui.ActiveDocument.setEdit(asm.Name)
    except Exception:
        pass


def _name_mates_folder(asm):
    try:
        _J, U = _assembly_modules()
        jg = U.getJointGroup(asm)
        if jg.Label in ("Joints", "Joints001"):
            jg.Label = "Mates"
    except Exception:
        pass


# ------------------------------------------------------------ New Assembly

def new_assembly():
    n = 1 + sum(1 for d in App.listDocuments().values()
                if d.Label.startswith("Assembly"))
    doc = App.newDocument(f"Assembly{n}")
    doc.Label = f"Assembly{n}"
    Gui.runCommand("Assembly_CreateAssembly", 0)
    asm = active_assembly()
    if asm is not None:
        asm.Label = f"Assembly{n}"
        _name_mates_folder(asm)
    return asm


def insert_components():
    asm = active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Insert Components",
            "Make or open an assembly first (New Assembly).")
        return
    ensure_active(asm)
    Gui.runCommand("Assembly_InsertLink", 0)


# ------------------------------------------------------------ selection

def _kind(shape):
    try:
        st = shape.ShapeType
    except Exception:
        return "other"
    if st == "Face":
        t = type(shape.Surface).__name__
        return "plane" if t == "Plane" else ("round" if t in ("Cylinder", "Cone") else "face")
    if st == "Edge":
        t = curve_name(shape)
        return "line" if t in ("Line", "LineSegment") else ("round" if t == "Circle" else "edge")
    if st == "Vertex":
        return "point"
    return "other"


def suggest(kinds):
    """SOLIDWORKS' default mate for two selected entities."""
    a, b = kinds
    if a == "round" and b == "round":
        return "Concentric"
    if {a, b} == {"round", "plane"}:
        return "Tangent"
    return "Coincident"


class MatePanel:
    def __init__(self, asm):
        self.asm = asm
        self.doc = asm.Document
        self.J, self.U = _assembly_modules()
        self.refs = []        # FreeCAD joint references [component, [sub, sub]]
        self.picks = []       # (doc name, root object name, full sub, kind, label)
        self.joint = None
        self.mate = None
        self.doc.openTransaction("Mate")
        self.form = self._build()
        self._timer = QtCore.QTimer()
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        self._take_selection()

    # ---- UI
    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Mate")
        root = QtWidgets.QVBoxLayout(w)
        box = QtWidgets.QGroupBox("Mate Selections")
        v = QtWidgets.QVBoxLayout(box)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(52)
        v.addWidget(self.list)
        clr = QtWidgets.QPushButton("Clear Selections")
        clr.clicked.connect(self._clear)
        v.addWidget(clr)
        root.addWidget(box)

        self.buttons = {}
        self.group = QtWidgets.QButtonGroup(w)
        self.group.setExclusive(True)
        for title, names in (("Standard Mates", STANDARD), ("Mechanical Mates", MECHANICAL)):
            g = QtWidgets.QGroupBox(title)
            grid = QtWidgets.QGridLayout(g)
            for i, name in enumerate(names):
                b = QtWidgets.QToolButton()
                b.setText(name)
                b.setCheckable(True)
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
                b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
                try:
                    b.setIcon(Gui.getIcon(MATES[name][2]))
                except Exception:
                    pass
                b.clicked.connect(lambda _=False, n=name: self._set_mate(n))
                self.group.addButton(b)
                self.buttons[name] = b
                grid.addWidget(b, i // 2, i % 2)
            root.addWidget(g)

        form = QtWidgets.QFormLayout()
        self.dist = QtWidgets.QDoubleSpinBox()
        self.dist.setRange(-1e5, 1e5)
        self.dist.setDecimals(2)
        self.dist.setSuffix(" mm")
        self.dist.setValue(10.0)
        self.dist.setKeyboardTracking(False)
        self.dist.valueChanged.connect(self._value_changed)
        form.addRow("Distance", self.dist)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setValue(30.0)
        self.angle.setKeyboardTracking(False)
        self.angle.valueChanged.connect(self._value_changed)
        form.addRow("Angle", self.angle)
        root.addLayout(form)

        al = QtWidgets.QHBoxLayout()
        al.addWidget(QtWidgets.QLabel("Mate alignment"))
        self.flip_btn = QtWidgets.QPushButton("Aligned / Anti-Aligned")
        self.flip_btn.setToolTip("Flip the part to the other side")
        self.flip_btn.clicked.connect(self._flip)
        al.addWidget(self.flip_btn)
        root.addLayout(al)

        self.msg = QtWidgets.QLabel("Click a face, edge or point on one part, then on another.")
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        root.addWidget(self.msg)
        root.addStretch(1)
        self._refresh_ui()
        return w

    def _refresh_ui(self):
        self.list.clear()
        for p in self.picks:
            self.list.addItem(p[4])
        ready = len(self.refs) == 2
        for b in self.buttons.values():
            b.setEnabled(ready)
        self.dist.setEnabled(self.mate == "Distance")
        self.angle.setEnabled(self.mate == "Angle")
        self.flip_btn.setEnabled(self.joint is not None)
        if self.mate and self.mate in self.buttons:
            self.buttons[self.mate].setChecked(True)

    # ---- picking
    def _poll(self):
        try:
            self._take_selection()
        except Exception as e:
            App.Console.PrintLog(f"MechFlow mate: {e}\n")

    def _take_selection(self):
        sel = Gui.Selection.getSelectionEx("*", 0)
        known = {(p[0], p[1], p[2]) for p in self.picks}
        new = []
        for s in sel:
            for sub in s.SubElementNames:
                key = (s.DocumentName, s.ObjectName, sub)
                if key not in known and sub and not sub.endswith("."):
                    new.append((s, sub))
        if not new:
            return
        changed = False
        for s, sub in new:
            try:
                comp, rel = self.U.getComponentReference(self.asm, s.Object, sub)
            except Exception:
                comp, rel = None, ""
            if comp is None:
                continue
            if any(r[0] == comp for r in self.refs):
                self.msg.setText("Pick the second entity on a different part.")
                continue
            if len(self.refs) >= 2:
                break
            try:
                shape = s.Object.getSubObject(sub)
            except Exception:
                shape = None
            kind = _kind(shape)
            elt = sub.split(".")[-1]
            self.refs.append([comp, [rel, rel]])
            self.picks.append((s.DocumentName, s.ObjectName, sub, kind, f"{elt}@{comp.Label}"))
            changed = True
        # Keep both picks highlighted.
        Gui.Selection.clearSelection()
        for p in self.picks:
            try:
                Gui.Selection.addSelection(p[0], p[1], p[2])
            except Exception:
                pass
        if changed:
            if len(self.refs) == 2 and self.joint is None:
                self._set_mate(suggest([p[3] for p in self.picks]))
            else:
                self._refresh_ui()

    def _clear(self):
        if self.joint is not None:
            self._remove_joint()
        self.refs, self.picks, self.mate = [], [], None
        Gui.Selection.clearSelection()
        self.group.setExclusive(False)
        for b in self.buttons.values():
            b.setChecked(False)
        self.group.setExclusive(True)
        self.msg.setText("Click a face, edge or point on one part, then on another.")
        self._refresh_ui()

    # ---- the joint
    def _remove_joint(self):
        try:
            if hasattr(self.asm, "undoSolve"):
                self.asm.undoSolve()
        except Exception:
            pass
        try:
            self.doc.removeObject(self.joint.Name)
        except Exception:
            pass
        self.joint = None

    def _set_mate(self, name):
        if len(self.refs) != 2:
            return
        self.mate = name
        jtype, _prop, _icon = MATES[name]
        jg = self.U.getJointGroup(self.asm)
        if self.joint is None:
            self.joint = jg.newObject("App::FeaturePython", "Mate")
            self.J.Joint(self.joint, self.J.JointTypes.index(jtype))
            try:
                self.J.ViewProviderJoint(self.joint.ViewObject)
            except Exception:
                pass
        elif self.joint.JointType != jtype:
            self.joint.JointType = jtype
        self._apply_values()
        self._ground_hardware()
        try:
            self.joint.Proxy.setJointConnectors(self.joint, self.refs)
            self.msg.setText(f"{name}: the part moves to suit. Choose another mate, flip it, "
                             "or OK.")
        except Exception as e:
            self.msg.setText(f"<b>That mate doesn't fit these selections</b> ({e}).")
        self.doc.recompute()
        self._refresh_ui()

    def _apply_values(self):
        j = self.joint
        if j is None:
            return
        if self.mate == "Distance":
            j.Distance = self.dist.value()
        elif self.mate in ("Coincident", "Tangent") and hasattr(j, "Distance"):
            j.Distance = 0.0
        if self.mate == "Angle" and hasattr(j, "Angle"):
            j.Angle = self.angle.value()

    def _value_changed(self, *_):
        if self.joint is None:
            return
        self._apply_values()
        try:
            self.J.solveIfAllowed(self.asm)
        except Exception:
            pass
        self.doc.recompute()

    def _flip(self):
        """Aligned / Anti-Aligned: turn the moving part 180 degrees about the
        mate's own X axis, then let the solver settle it. (FreeCAD's own flip
        only moves a part that has no other mates yet.)"""
        if self.joint is None:
            return
        j = self.joint
        grounded = self._grounded()
        p1, p2 = self.refs[0][0], self.refs[1][0]
        if p2 not in grounded:
            moving, jcs = p2, j.Placement2
        elif p1 not in grounded:
            moving, jcs = p1, j.Placement1
        else:
            self.msg.setText("Both parts are fixed - float one to flip the mate.")
            return
        try:
            g = moving.Placement.multiply(jcs)              # mate frame in assembly
            axis = g.Rotation.multVec(App.Vector(1, 0, 0))
            turn = App.Placement(g.Base, App.Rotation(axis, 180)).multiply(
                App.Placement(g.Base * -1, App.Rotation()))
            moving.Placement = turn.multiply(moving.Placement)
            self.J.solveIfAllowed(self.asm)
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: flip failed ({e})\n")
        self.doc.recompute()

    def _ground_hardware(self):
        """Toolbox parts (flanges, pipe, fasteners) are held by the edge they
        were placed on; in a mate it's the other part that must move, so
        fix them in place."""
        grounded = self._grounded()
        for comp, _sub in self.refs:
            proxy = type(getattr(comp, "Proxy", None)).__name__
            if proxy not in ("StdPart", "FSScrewObject") or comp in grounded:
                continue
            g = self.U.getJointGroup(self.asm).newObject("App::FeaturePython", "GroundedJoint")
            self.J.GroundedJoint(g, comp)
            try:
                self.J.ViewProviderGroundedJoint(g.ViewObject)
            except Exception:
                pass
            g.Label = f"Fixed ({comp.Label})"
            self._auto_ground = getattr(self, "_auto_ground", []) + [g]

    def _grounded(self):
        out = set()
        try:
            for o in self.U.getJointGroup(self.asm).Group:
                g = getattr(o, "ObjectToGround", None)
                if g is not None:
                    out.add(g)
        except Exception:
            pass
        return out

    # ---- task dialog
    def _stop(self):
        self._timer.stop()
        Gui.Selection.clearSelection()

    def accept(self):
        if self.joint is None:
            QtWidgets.QMessageBox.information(
                self.form, "Mate", "Pick two entities on different parts first - or Cancel.")
            return False
        self._stop()
        n = 1 + sum(1 for o in self.U.getJointGroup(self.asm).Group
                    if o is not self.joint and o.Label.startswith(self.mate))
        self.joint.Label = f"{self.mate}{n}"
        # SOLIDWORKS doesn't draw mates in the view: hide the joint markers
        for j in [self.joint] + list(getattr(self, "_auto_ground", [])):
            try:
                j.ViewObject.Visibility = False
            except Exception:
                pass
        _name_mates_folder(self.asm)
        self.doc.commitTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._stop()
        if self.joint is not None:
            self._remove_joint()
        self.doc.abortTransaction()
        self.doc.recompute()
        Gui.Control.closeDialog()
        return True


def mate():
    asm = active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Mate", "Open an assembly first (New Assembly).")
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Mate",
                                          "Finish the open dialog first.")
        return None
    ensure_active(asm)
    panel = MatePanel(asm)
    Gui.Control.showDialog(panel)
    return panel


# ------------------------------------------------------------ interference

def components(asm):
    """The parts in an assembly, each with its shape in assembly position."""
    out = []
    for o in asm.Group:
        if o.TypeId in ("Assembly::JointGroup", "Assembly::ViewGroup", "Assembly::BomGroup") \
                or o.isDerivedFrom("Assembly::JointGroup"):
            continue
        try:
            shape = o.Shape
        except Exception:
            continue
        if shape is None or shape.isNull() or not shape.Solids:
            continue
        out.append((o, shape))
    return out


def _is_fastener(o):
    return type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject"


_CACHE = {}          # (key A, key B) -> overlap volume, per session


def _deep_overlap(b1, b2, eps=0.05):
    """Boxes that really overlap - not just touching (a nut on a flange face,
    a pipe butted to an elbow): those can't interfere."""
    return (min(b1.XMax, b2.XMax) - max(b1.XMin, b2.XMin) > eps and
            min(b1.YMax, b2.YMax) - max(b1.YMin, b2.YMin) > eps and
            min(b1.ZMax, b2.ZMax) - max(b1.ZMin, b2.ZMin) > eps)


def _key(o, shape):
    """Changes when the part's shape or position does."""
    bb = shape.BoundBox
    return (o.Document.Name, o.Name, round(shape.Volume, 3),
            tuple(round(x, 3) for x in (bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax)))


def _near(shape, box):
    """The solids of shape whose boxes overlap box (a part's other solids
    are far away: no need to intersect them)."""
    sols = [x for x in shape.Solids if _deep_overlap(x.BoundBox, box)]
    if not sols:
        return None
    import Part
    return sols[0] if len(sols) == 1 else Part.makeCompound(sols)


def interferences(asm, tol=1.0, fastener_pairs=False, progress=None):
    """[(part A, part B, overlap volume mm^3)] for parts that overlap by more
    than tol. A bolt through its own nut and washer always 'overlaps' (the
    thread is modelled at full size), so pairs of fasteners are left out
    unless fastener_pairs. Results are remembered, so checking again after
    an edit only re-tests the parts that moved or changed. progress(i, n)
    can return False to stop."""
    comps = components(asm)
    keys = [_key(o, sh) for o, sh in comps]
    boxes = [sh.BoundBox for o, sh in comps]
    todo = []
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            a, b = comps[i][0], comps[j][0]
            if not fastener_pairs and _is_fastener(a) and _is_fastener(b):
                continue
            if not _deep_overlap(boxes[i], boxes[j]):
                continue
            todo.append((i, j))
    found = []
    for n, (i, j) in enumerate(todo):
        if progress is not None and n % 10 == 0 and progress(n, len(todo)) is False:
            break
        (a, sa), (b, sb) = comps[i], comps[j]
        ck = (keys[i], keys[j])
        v = _CACHE.get(ck)
        if v is None:
            try:
                pa, pb = _near(sa, boxes[j]), _near(sb, boxes[i])
                v = 0.0 if pa is None or pb is None else pa.common(pb).Volume
            except Exception:
                v = 0.0
            _CACHE[ck] = v
        if v > tol:
            found.append((a, b, v))
    if progress is not None:
        progress(len(todo), len(todo))
    return found


def interference_detection():
    asm = active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Interference Detection",
                                          "Open an assembly first.")
        return None
    dlg = QtWidgets.QProgressDialog("Checking for overlapping parts...", "Cancel", 0, 100,
                                    Gui.getMainWindow())
    dlg.setWindowTitle("Interference Detection")
    dlg.setMinimumDuration(400)
    stopped = []

    def progress(i, n):
        dlg.setMaximum(max(1, n))
        dlg.setValue(i)
        QtWidgets.QApplication.processEvents()
        if dlg.wasCanceled():
            stopped.append(True)
            return False
        return True
    found = interferences(asm, progress=progress)
    dlg.close()
    if stopped:
        return None
    Gui.Selection.clearSelection()
    if not found:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Interference Detection",
                                          "No interferences: no parts overlap.")
        return found
    lines = []
    for a, b, v in found:
        lines.append(f"{a.Label}  /  {b.Label}:  {v:,.2f} mm\u00b3")
        for o in (a, b):
            try:
                Gui.Selection.addSelection(o)
            except Exception:
                pass
    QtWidgets.QMessageBox.warning(
        Gui.getMainWindow(), "Interference Detection",
        f"{len(found)} interference{'s' if len(found) != 1 else ''} found "
        "(the parts are highlighted):\n\n" + "\n".join(lines))
    return found
