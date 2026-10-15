# SPDX-License-Identifier: LGPL-2.1-or-later
"""Projected views that stay lined up but can be dragged apart, like
SOLIDWORKS:

- MechFlow's drawings lay the views out once and then let go (FreeCAD's
  automatic spacing locked them in place): drag the top view up or down, the
  side view left or right - each slides along its line from the front view,
  so they stay aligned. Drag the front view to move them all.
- View Spacing: the gap between the views, all at once.
- Break Alignment (right-click a projected view): it becomes a view of its
  own you can put anywhere. Default Alignment puts it back in line.
"""

import json
import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

PROP = "MechFlowAlignment"
VERTICAL = ("Top", "Bottom")
HORIZONTAL = ("Left", "Right", "Rear")


def _mw():
    return Gui.getMainWindow()


def _page_of(v):
    for p in v.InList:
        if p.TypeId == "TechDraw::DrawPage":
            return p
        if p.TypeId == "TechDraw::DrawProjGroup":
            return _page_of(p)
    return None


def _group_of(item):
    for p in item.InList:
        if p.TypeId == "TechDraw::DrawProjGroup":
            return p
    return None


# ------------------------------------------------------------ free layout

def free_layout(group, bb, scale, projection, gap=15.0):
    """Place the group's views from the part's size (the gap between their
    outlines) and switch FreeCAD's automatic spacing off, so each view can
    be dragged along its line from the front view."""
    sx, sy, sz = bb.XLength * scale, bb.YLength * scale, bb.ZLength * scale
    first = str(projection).startswith("First")
    pos = {
        "Front": (0.0, 0.0),
        "Top": (0.0, (-1 if first else 1) * (sz / 2 + gap + sy / 2)),
        "Bottom": (0.0, (1 if first else -1) * (sz / 2 + gap + sy / 2)),
        "Right": ((-1 if first else 1) * (sx / 2 + gap + sy / 2), 0.0),
        "Left": ((1 if first else -1) * (sx / 2 + gap + sy / 2), 0.0),
    }
    items = list(getattr(group, "Views", []))
    if any(str(v.Type) not in pos for v in items):
        return False                       # a view we can't place: leave it to FreeCAD
    group.AutoDistribute = False
    for v in items:
        v.X, v.Y = pos[str(v.Type)]
    try:
        group.spacingX = gap
        group.spacingY = gap
    except Exception:
        pass
    return True


class _ScaleObserver:
    """A group whose views were let go keeps its layout when its scale
    changes: each view's distance from the front view is scaled, the gap
    between them kept."""

    def __init__(self):
        self.old = {}

    def slotBeforeChangeObject(self, obj, prop):
        if prop == "Scale" and getattr(obj, "TypeId", "") == "TechDraw::DrawProjGroup":
            self.old[(obj.Document.Name, obj.Name)] = float(obj.Scale)

    def slotChangedObject(self, obj, prop):
        # (FreeCAD tells of the group's new scale through its views)
        if prop != "Scale":
            return
        t = getattr(obj, "TypeId", "")
        g = obj if t == "TechDraw::DrawProjGroup" else \
            _group_of(obj) if t == "TechDraw::DrawProjGroupItem" else None
        if g is None:
            return
        old = self.old.pop((g.Document.Name, g.Name), None)
        if not old or g.AutoDistribute:
            return
        new = float(g.Scale)
        if new <= 0 or abs(new - old) < 1e-12:
            return
        rescale(g, new / old)


def rescale(group, k):
    try:
        gx = float(getattr(group.spacingX, "Value", group.spacingX))
        gy = float(getattr(group.spacingY, "Value", group.spacingY))
    except Exception:
        gx = gy = 15.0
    for v in group.Views:
        x, y = float(v.X), float(v.Y)
        if abs(x) > 1e-9:
            v.X = math.copysign(max(0.0, abs(x) - gx) * k + gx, x)
        if abs(y) > 1e-9:
            v.Y = math.copysign(max(0.0, abs(y) - gy) * k + gy, y)


_obs = None


def install():
    global _obs
    if _obs is None:
        _obs = _ScaleObserver()
        App.addDocumentObserver(_obs)


def set_spacing(group, gap):
    """The gap between the views (mm on the sheet), all at once: FreeCAD
    spaces them from their real outlines, then lets go again."""
    doc = group.Document
    group.spacingX = gap
    group.spacingY = gap
    group.AutoDistribute = True
    doc.recompute()
    QtWidgets.QApplication.processEvents()
    for v in list(group.Views) + [group]:
        v.touch()
    doc.recompute()
    group.AutoDistribute = False
    doc.recompute()


class SpacingDialog(QtWidgets.QDialog):
    def __init__(self, group, parent=None):
        super().__init__(parent or _mw())
        self.g = group
        self.setWindowTitle("View Spacing")
        lay = QtWidgets.QFormLayout(self)
        self.gap = QtWidgets.QDoubleSpinBox()
        self.gap.setRange(0.0, 500.0)
        self.gap.setDecimals(1)
        self.gap.setSuffix(" mm")
        self.gap.setValue(float(getattr(group.spacingX, "Value", group.spacingX)))
        lay.addRow("Gap between the views", self.gap)
        note = QtWidgets.QLabel("Or drag a view on the drawing: the top view moves up and "
                                "down, the side view left and right, so they stay in line.")
        note.setWordWrap(True)
        lay.addRow(note)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.gap.valueChanged.connect(lambda v: set_spacing(self.g, v))


def spacing_command(group=None):
    if group is None:
        for o in Gui.Selection.getSelection():
            if o.TypeId == "TechDraw::DrawProjGroup":
                group = o
            elif o.TypeId == "TechDraw::DrawProjGroupItem":
                group = _group_of(o)
            if group is not None:
                break
    if group is None:
        QtWidgets.QMessageBox.information(_mw(), "View Spacing",
                                          "Select a projected view on the drawing first.")
        return
    doc = group.Document
    doc.openTransaction("View Spacing")
    if SpacingDialog(group).exec():
        doc.commitTransaction()
    else:
        doc.abortTransaction()
        doc.recompute()


# ------------------------------------------------------------ break / default

SKIP = {"Label", "Label2", "X", "Y", "Type", "LockPosition", "ScaleType", "Scale",
        "ExpressionEngine", "Visibility", "Source", "XSource", "Views", PROP,
        "Proxy", "Rotation", "Direction", "XDirection", "RotationVector"}


def _copy_props(src, dst, only=None):
    for p in src.PropertiesList:
        if p in SKIP or p not in dst.PropertiesList or (only and p not in only):
            continue
        try:
            if "ReadOnly" in dst.getPropertyStatus(p) or "Output" in dst.getPropertyStatus(p):
                continue
        except Exception:
            pass
        try:
            setattr(dst, p, getattr(src, p))
        except Exception:
            pass
    try:
        for p in src.ViewObject.PropertiesList:
            if p in ("Visibility",) or p not in dst.ViewObject.PropertiesList:
                continue
            try:
                setattr(dst.ViewObject, p, getattr(src.ViewObject, p))
            except Exception:
                pass
    except Exception:
        pass


def _swap(v, old, new):
    if v is old:
        return new, True
    if isinstance(v, tuple) and v and v[0] is old:
        return (new,) + tuple(v[1:]), True
    if isinstance(v, list):
        out, ch = [], False
        for x in v:
            y, c = _swap(x, old, new)
            out.append(y)
            ch = ch or c
        return out, ch
    return v, False


def relink(old, new, skip=()):
    """Everything that points at old (dimensions, balloons, hatches,
    centre lines, section and detail views...) points at new."""
    n = 0
    for o in list(old.InList):
        if o is new or o in skip:
            continue
        for p in o.PropertiesList:
            try:
                t = o.getTypeIdOfProperty(p)
            except Exception:
                continue
            if "PropertyLink" not in t or p in ("Views", "Source", "XSource"):
                continue
            try:
                v, ch = _swap(getattr(o, p), old, new)
                if ch:
                    setattr(o, p, v)
                    n += 1
            except Exception:
                pass
    return n


def break_alignment(item):
    """A projected view off its group: a view of its own, where it was."""
    g = _group_of(item)
    page = _page_of(item)
    if g is None or page is None or str(item.Type) == "Front":
        return None
    doc = item.Document
    doc.openTransaction("Break Alignment")
    try:
        typ, label = str(item.Type), item.Label
        new = doc.addObject("TechDraw::DrawViewPart", "View")
        page.addView(new)
        new.Source = list(item.Source)
        try:
            new.XSource = list(item.XSource)
        except Exception:
            pass
        new.Direction = item.Direction
        try:
            new.XDirection = item.XDirection
        except Exception:
            pass
        new.ScaleType = "Custom"
        new.Scale = float(g.Scale)
        _copy_props(item, new)
        new.addProperty("App::PropertyString", PROP, "MechFlow",
                        "Which projected view this was (Default Alignment puts it back)")
        setattr(new, PROP, json.dumps({"group": g.Name, "type": typ}))
        new.X = float(g.X) + float(item.X)
        new.Y = float(g.Y) + float(item.Y)
        relink(item, new, skip=(g, page))
        Gui.Selection.clearSelection()     # (TechDraw trips over a deleted selected view)
        g.removeProjection(typ)
        new.Label = label
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    return new


def default_alignment(view):
    """A view that was broken off its group back in line with the front."""
    try:
        info = json.loads(getattr(view, PROP))
    except Exception:
        return None
    doc = view.Document
    g = doc.getObject(info.get("group", ""))
    typ = info.get("type", "")
    if g is None:
        QtWidgets.QMessageBox.information(_mw(), "Default Alignment",
                                          "The views it lined up with have gone.")
        return None
    if any(str(v.Type) == typ for v in g.Views):
        QtWidgets.QMessageBox.information(_mw(), "Default Alignment",
                                          f"The group already has a {typ} view.")
        return None
    page = _page_of(view)
    doc.openTransaction("Default Alignment")
    try:
        label = view.Label
        item = g.addProjection(typ)
        _copy_props(view, item, only=None)
        if typ in VERTICAL:
            item.X, item.Y = 0.0, float(view.Y) - float(g.Y)
        else:
            item.X, item.Y = float(view.X) - float(g.X), 0.0
        relink(view, item, skip=(page,))
        Gui.Selection.clearSelection()
        if page is not None:
            page.removeView(view)
        doc.removeObject(view.Name)
        item.Label = label
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    doc.recompute()
    return item


def break_command():
    items = [o for o in Gui.Selection.getSelection()
             if o.TypeId == "TechDraw::DrawProjGroupItem" and str(o.Type) != "Front"]
    if not items:
        QtWidgets.QMessageBox.information(
            _mw(), "Break Alignment",
            "Select a projected view (top, side...) on the drawing first - "
            "the front view carries the others.")
        return
    for it in items:
        break_alignment(it)


def default_command():
    views = [o for o in Gui.Selection.getSelection() if hasattr(o, PROP)]
    if not views:
        QtWidgets.QMessageBox.information(_mw(), "Default Alignment",
                                          "Select a view that had its alignment broken.")
        return
    for v in views:
        default_alignment(v)
