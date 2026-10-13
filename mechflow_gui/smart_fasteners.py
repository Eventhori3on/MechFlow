# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Smart Fasteners.

Finds the round holes in an assembly (or a part) that a standard screw fits
- ISO 273 clearance holes and tapped holes - including holes that line up
through several parts, and fills them all at once:

- a stack of clearance holes into a tapped part gets a screw long enough to
  engage the thread (up to 1.5 x d, no deeper than the tapped hole);
- a stack of clearance holes right through gets a bolt, washer and nut;
- counterbores take socket head cap screws, countersinks countersunk
  screws, plain holes hex head screws - changeable per group;
- holes that already have a fastener are left alone.

Uses the Toolbox (and so the Fasteners Workbench) to make the fasteners.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from mechflow_gui import toolbox

V = App.Vector
TYPES = [("ISO4762", "Socket head cap screw (ISO 4762)"),
         ("ISO4017", "Hex head screw (ISO 4017)"),
         ("ISO4014", "Hex head bolt (ISO 4014)"),
         ("ISO10642", "Countersunk socket screw (ISO 10642)"),
         ("ISO7380-1", "Button head socket screw (ISO 7380)")]


# ------------------------------------------------------------ finding holes

def _is_hardware(o):
    from mechflow_gui import stdparts
    name = type(getattr(o, "Proxy", None)).__name__
    return name in ("FSScrewObject",) or stdparts.is_std_object(o)


def components(container=None, doc=None):
    """[(object, shape in container coordinates)] to look for holes in."""
    if container is not None and container.isDerivedFrom("Assembly::AssemblyObject"):
        from mechflow_gui import assembly
        return [(o, s) for o, s in assembly.components(container) if not _is_hardware(o)]
    doc = doc or App.ActiveDocument
    out = []
    for o in doc.Objects:
        if o.getParentGeoFeatureGroup() is not None or _is_hardware(o):
            continue
        if o.isDerivedFrom("Assembly::AssemblyObject") or o.TypeId.startswith("App::Origin"):
            continue
        try:
            if not o.Visibility:
                continue
            sh = o.Shape
        except Exception:
            continue
        if sh is None or sh.isNull() or not sh.Solids:
            continue
        out.append((o, sh))
    return out


def _canon(axis):
    a = V(axis).normalize()
    for c in (a.z, a.y, a.x):
        if abs(c) > 1e-6:
            return a if c > 0 else a * -1
    return a


class Segment:
    def __init__(self, obj, shape, r, lo, hi):
        self.obj, self.shape, self.r, self.lo, self.hi = obj, shape, r, lo, hi


def hole_segments(obj, shape):
    """Concave (hole) cylinders of a shape, keyed by axis line."""
    out = {}
    for f in shape.Faces:
        surf = f.Surface
        if type(surf).__name__ != "Cylinder":
            continue
        u0, u1, v0, v1 = f.ParameterRange
        try:
            p = f.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
            n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        except Exception:
            continue
        a = _canon(surf.Axis)
        c = surf.Center
        radial = (p - c) - a * (p - c).dot(a)
        if n.dot(radial) >= 0:            # outside of a boss, not a hole
            continue
        r = surf.Radius
        if not (0.8 <= r <= 20):
            continue
        p0 = c - a * c.dot(a)
        ts = [(v.Point - p0).dot(a) for v in f.Vertexes] or [0.0]
        key = (round(a.x, 4), round(a.y, 4), round(a.z, 4),
               round(p0.x, 1), round(p0.y, 1), round(p0.z, 1))
        out.setdefault(key, (a, p0, []))[2].append(Segment(obj, shape, r, min(ts), max(ts)))
    return out


class Entry:
    """One hole in one part along a line: the hole proper (smallest radius)
    plus any counterbore."""

    def __init__(self, segs):
        self.obj, self.shape = segs[0].obj, segs[0].shape
        self.rp = min(s.r for s in segs)
        self.rmax = max(s.r for s in segs)
        self.lo = min(s.lo for s in segs)
        self.hi = max(s.hi for s in segs)
        proper = [s for s in segs if abs(s.r - self.rp) < 1e-4]
        self.plo = min(s.lo for s in proper)
        self.phi = max(s.hi for s in proper)
        self.size, self.kind = toolbox.size_for(2 * self.rp)


def _merge(segs):
    segs = sorted(segs, key=lambda s: s.lo)
    groups, cur = [], []
    for s in segs:
        if cur and s.lo > max(x.hi for x in cur) + 0.01:
            groups.append(cur)
            cur = []
        cur.append(s)
    if cur:
        groups.append(cur)
    return [Entry(g) for g in groups]


class Stack:
    """Holes lining up through one or more parts."""

    def __init__(self, axis, p0, entries, solids=()):
        self.axis, self.p0, self.entries = axis, p0, entries
        self.solids = list(solids) or [e.shape for e in entries]
        self.reason = None
        self.ok = self._work_out()

    def point(self, t):
        return self.p0 + self.axis * t

    def _work_out(self):
        es = self.entries
        kinds = [e.kind for e in es]
        if any(k not in ("clearance", "tapped") for k in kinds):
            self.reason = "not a standard clearance or tapped hole"
            return False
        tapped = [i for i, e in enumerate(es) if e.kind == "tapped"]
        sizes = {e.size for e in es}
        if len(sizes) != 1:
            self.reason = "holes of different sizes line up"
            return False
        self.size = sizes.pop()
        if len(tapped) > 1 or (tapped and tapped[0] not in (0, len(es) - 1)):
            self.reason = "tapped hole in the middle of the stack"
            return False
        if len(es) == 1:
            open_lo, open_hi = self._open(es[0], es[0].plo, -1), self._open(es[0], es[0].phi, 1)
        else:
            open_lo = open_hi = True
        if len(es) == 1 and open_lo != open_hi:
            self.head_hi = open_hi          # a blind hole: in from its open end
        elif tapped:
            self.head_hi = tapped[0] == 0
        else:
            hi_cb = es[-1].rmax > es[-1].rp + 1e-3 and es[-1].hi > es[-1].phi + 1e-3
            lo_cb = es[0].rmax > es[0].rp + 1e-3 and es[0].lo < es[0].plo - 1e-3
            if hi_cb != lo_cb:
                self.head_hi = hi_cb
            else:
                self.head_hi = self.axis.z >= 0
        self.tapped = es[tapped[0]] if tapped else None
        self.head = es[-1] if self.head_hi else es[0]
        self.far = es[0] if self.head_hi else es[-1]
        return True

    def _open(self, entry, t, sign):
        """True if the hole opens out (no material in any part) past t."""
        for k in (0.05, 0.65 * entry.rp + 0.3):
            p = self.point(t + sign * k)
            for sh in self.solids:
                try:
                    if sh.BoundBox.isInside(p) and sh.isInside(p, 1e-6, True):
                        return False
                except Exception:
                    pass
        return True

    # ---- for the Toolbox
    def _circle(self, entry, t, r):
        for i, e in enumerate(entry.shape.Edges):
            c = getattr(e, "Curve", None)
            if type(c).__name__ != "Circle" or abs(c.Radius - r) > 1e-3:
                continue
            d = c.Center - self.p0
            along = d.dot(self.axis)
            if abs(along - t) < 1e-3 and (d - self.axis * along).Length < 1e-3:
                return f"Edge{i + 1}"
        return None

    def hole(self):
        """A toolbox.Hole for the head part, with lengths for the stack."""
        h_end = self.head.hi if self.head_hi else self.head.lo
        # the outermost circle at the head end (counterbore / countersink top)
        best = None
        for i, e in enumerate(self.head.shape.Edges):
            c = getattr(e, "Curve", None)
            if type(c).__name__ != "Circle":
                continue
            d = c.Center - self.p0
            along = d.dot(self.axis)
            if (d - self.axis * along).Length > 1e-3 or abs(abs(V(c.Axis).dot(self.axis)) - 1) > 1e-6:
                continue
            if abs(along - h_end) < 0.6 * c.Radius + 1e-3:
                if best is None or c.Radius > best[1]:
                    best = (f"Edge{i + 1}", c.Radius)
        if best is None:
            return None
        h = toolbox.Hole(self.head.obj, best[0])
        if not h.ok:
            return None
        import Part
        seat = Part.getShape(h.obj, h.seat_sub, needSubElement=True, noElementMap=True)
        ts = (seat.Curve.Center - self.p0).dot(self.axis)
        dist = (lambda t: ts - t) if self.head_hi else (lambda t: t - ts)
        single_grip, single_cs = h.grip, h.cs_grip
        extra = (single_cs - single_grip) if (single_cs is not None and single_grip) else None
        h.size, h.kind = self.size, "clearance"
        if self.tapped is not None:
            near = self.tapped.phi if self.head_hi else self.tapped.plo
            h.tapped_after = dist(near)
            h.tapped_depth = self.tapped.phi - self.tapped.plo
            h.grip = h.tapped_after
            h.through = False
            h.exit_sub = None
        else:
            far_t = self.far.plo if self.head_hi else self.far.phi
            h.grip = dist(far_t)
            h.through = self._open(self.far, far_t, -1 if self.head_hi else 1)
            h.exit_obj = self.far.obj
            h.exit_sub = self._circle(self.far, far_t, self.far.rp) if h.through else None
        if extra is not None:
            h.cs_grip = h.grip + extra
        h.depth = h.grip
        return h

    def default_type(self, h):
        if h is not None and h.cs_sub is not None and h.seat_sub != h.cs_sub:
            import Part
            try:
                cs = Part.getShape(h.obj, h.cs_sub, needSubElement=True, noElementMap=True)
                # a cone between the countersink edge and the hole: countersunk
                cc, cr = cs.Curve.Center, cs.Curve.Radius
                for f in h.obj.Shape.Faces:
                    if type(f.Surface).__name__ != "Cone":
                        continue
                    for e in f.Edges:
                        c = getattr(e, "Curve", None)
                        if type(c).__name__ == "Circle" and abs(c.Radius - cr) < 1e-4 \
                                and (c.Center - cc).Length < 1e-4:
                            return "ISO10642"
            except Exception:
                pass
            return "ISO4762"            # counterbore
        if self.tapped is not None and len(self.entries) == 1:
            return "ISO4762"            # straight into a tapped hole: short lengths
        return "ISO4017"

    def describe(self):
        n = len(self.entries)
        if self.tapped is not None:
            what = "into a tapped hole" if n > 1 else "tapped hole"
        else:
            what = "through" if n > 1 else "clearance hole"
        parts = f"{n} parts" if n > 1 else self.entries[0].obj.Label
        return f"{self.size} {what} ({parts})"


def _filled(stack, fasteners):
    lo = min(e.lo for e in stack.entries) - 50
    hi = max(e.hi for e in stack.entries) + 50
    for f in fasteners:
        b = f.Placement.Base
        d = b - stack.p0
        along = d.dot(stack.axis)
        if (d - stack.axis * along).Length < 0.2 and lo <= along <= hi:
            return True
    return False


def find_stacks(container=None, only=None):
    """All hole stacks to fill. only: objects to limit the search to."""
    lines = {}
    comps = components(container)
    solids = [sh for _o, sh in comps]
    for obj, shape in comps:
        for key, (a, p0, segs) in hole_segments(obj, shape).items():
            lines.setdefault(key, (a, p0, []))[2].append(segs)
    doc = container.Document if container is not None else App.ActiveDocument
    fasteners = [o for o in doc.Objects
                 if type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject"]
    stacks = []
    for key, (a, p0, per_obj) in lines.items():
        entries = []
        for segs in per_obj:
            entries += _merge(segs)
        entries.sort(key=lambda e: e.lo)
        chain = []
        for e in entries:
            if chain and e.lo > chain[-1].hi + 0.5:
                stacks.append(Stack(a, p0, chain, solids))
                chain = []
            chain.append(e)
        if chain:
            stacks.append(Stack(a, p0, chain, solids))
    out = []
    for s in stacks:
        if only and not any(e.obj in only for e in s.entries):
            continue
        if _filled(s, fasteners):
            continue
        out.append(s)
    return out


# ------------------------------------------------------------ the panel

class Group:
    def __init__(self, key, ftype):
        self.key, self.ftype, self.stacks = key, ftype, []


class SmartFastenersPanel:
    def __init__(self):
        from mechflow_gui import assembly
        self.container = toolbox.active_container()
        if self.container is None:
            a = assembly.active_assembly()
            self.container = a
        sel = [s.Object for s in Gui.Selection.getSelectionEx()]
        self.only = sel or None
        self.stacks = find_stacks(self.container, self.only)
        self.groups = self._group()
        self.form = self._build()

    def _group(self):
        groups = {}
        for s in self.stacks:
            if not s.ok:
                continue
            s.h = s.hole()
            if s.h is None:
                s.ok, s.reason = False, "couldn't find the hole's edge"
                continue
            if s.tapped is None and not s.h.through:
                s.ok, s.reason = False, "blind clearance hole (no thread to screw into)"
                continue
            ftype = s.default_type(s.h)
            grip = round(getattr(s.h, "tapped_after", None) or s.h.grip or 0, 1)
            key = (s.size, ftype, s.tapped is not None, s.h.through, grip, len(s.entries))
            groups.setdefault(key, Group(key, ftype)).stacks.append(s)
        return list(groups.values())

    def _build(self):
        w = QtWidgets.QWidget()
        w.setWindowTitle("Smart Fasteners")
        lay = QtWidgets.QVBoxLayout(w)
        scope = ("selected parts" if self.only else
                 ("the assembly" if self.container is not None else "the document"))
        n = sum(len(g.stacks) for g in self.groups)
        skipped = [s for s in self.stacks if not s.ok]
        head = QtWidgets.QLabel(f"<b>{n} hole{'s' if n != 1 else ''}</b> to fill in {scope}"
                                + (f", {len(skipped)} skipped" if skipped else "") + ".")
        head.setWordWrap(True)
        lay.addWidget(head)
        box = QtWidgets.QWidget()
        bl = QtWidgets.QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        self.combos, self.lengths, self.labels = [], [], []
        for r, g in enumerate(self.groups):
            s0 = g.stacks[0]
            fr = QtWidgets.QFrame()
            fr.setFrameShape(QtWidgets.QFrame.StyledPanel)
            fl = QtWidgets.QVBoxLayout(fr)
            fl.setContentsMargins(6, 4, 6, 4)
            fl.setSpacing(3)
            lbl = QtWidgets.QLabel(f"<b>{len(g.stacks)} x</b> {s0.describe()}")
            lbl.setWordWrap(True)
            fl.addWidget(lbl)
            row = QtWidgets.QHBoxLayout()
            cb = QtWidgets.QComboBox()
            for t, text in TYPES:
                if toolbox.diameters(t) and s0.size in toolbox.diameters(t):
                    cb.addItem(text, t)
            cb.setCurrentIndex(max(0, cb.findData(g.ftype)))
            cb.currentIndexChanged.connect(lambda _i, row=r: self._type_changed(row))
            row.addWidget(cb, 1)
            fl.addLayout(row)
            ln = QtWidgets.QLabel()
            ln.setStyleSheet("color: #1d5fb8;")
            fl.addWidget(ln)
            bl.addWidget(fr)
            self.combos.append(cb)
            self.lengths.append(ln)
            self.labels.append(lbl)
        bl.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(box)
        scroll.setMinimumHeight(min(360, 70 * max(1, len(self.groups)) + 10))
        lay.addWidget(scroll, 1)
        for r in range(len(self.groups)):
            self._type_changed(r)
        form = QtWidgets.QFormLayout()
        self.washer = QtWidgets.QCheckBox("Washer under the head")
        self.washer.toggled.connect(lambda *_: [self._type_changed(r)
                                                for r in range(len(self.groups))])
        form.addRow("", self.washer)
        self.ends = QtWidgets.QComboBox()
        self.ends.addItems([toolbox.ENDS[1], toolbox.ENDS[2]])
        self.ends.setToolTip("What bolts through holes end in")
        self.washer.setChecked(False)
        self.ends.currentIndexChanged.connect(lambda *_: [self._type_changed(r)
                                                          for r in range(len(self.groups))])
        form.addRow("Through holes", self.ends)
        lay.addLayout(form)
        if skipped:
            why = {}
            for s in skipped:
                why[s.reason] = why.get(s.reason, 0) + 1
            note = QtWidgets.QLabel("Skipped: " + "; ".join(f"{n} {r}" for r, n in why.items()))
            note.setWordWrap(True)
            note.setStyleSheet("color: gray;")
            lay.addWidget(note)
        msg = QtWidgets.QLabel("Select parts first to fill only their holes. Holes that "
                               "already have a fastener are left alone.")
        msg.setWordWrap(True)
        msg.setStyleSheet("color: gray;")
        lay.addWidget(msg)
        return w

    def _ends(self):
        return self.ends.currentText() if hasattr(self, "ends") else toolbox.ENDS[1]

    def _type_changed(self, row):
        g = self.groups[row]
        g.ftype = self.combos[row].currentData()
        s0 = g.stacks[0]
        offset = 0.0
        if getattr(self, "washer", None) is not None and self.washer.isChecked() \
                and g.ftype not in toolbox.COUNTERSUNK:
            offset = 0.16 * toolbox.METRIC.get(s0.size, (8.0,))[0]
        ln = toolbox.auto_length(g.ftype, s0.h, s0.size, self._ends(), offset)
        extra = ""
        if s0.tapped is None and s0.h.through and self._ends() == toolbox.ENDS[1]:
            extra = " + washer, nut"
        self.lengths[row].setText(f"\u2192 {s0.size}x{ln}{extra}" if ln else "no standard length fits")

    def accept(self):
        doc = (self.container.Document if self.container is not None else App.ActiveDocument)
        doc.openTransaction("Smart Fasteners")
        made = []
        try:
            for g in self.groups:
                for s in g.stacks:
                    made += toolbox.place(self.container, g.ftype, s.h, s.size, None,
                                          self.washer.isChecked(), self._ends())
            doc.commitTransaction()
        except Exception as e:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self.form, "Smart Fasteners",
                                          f"The fasteners couldn't be inserted:\n{e}")
            return False
        doc.recompute()
        self.made = made
        App.Console.PrintMessage(f"MechFlow Smart Fasteners: inserted {len(made)} parts\n")
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def smart_fasteners():
    if toolbox.fasteners() is None:
        toolbox.offer_install()
        return None
    if App.ActiveDocument is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Smart Fasteners",
                                          "Finish the open dialog first.")
        return None
    toolbox.patch_labels()
    panel = SmartFastenersPanel()
    if not panel.groups:
        skipped = [s for s in panel.stacks if not s.ok]
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Smart Fasteners",
            "No empty clearance or tapped holes found." +
            (f" ({len(skipped)} holes skipped: not standard sizes.)" if skipped else ""))
        return None
    Gui.Control.showDialog(panel)
    return panel
