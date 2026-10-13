# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style PropertyManager for sketch entities.

While a sketch is open, selecting a line / arc / circle / point brings a
"PropertyManager" tab to the front of the left pane showing the entity, its
Existing Relations (with delete) and Add Relations buttons. Clearing the
selection brings the tree back.

Driven by the MechFlow layout timer (polling) - no Qt hooks into FreeCAD.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

# FreeCAD constraint type -> SOLIDWORKS relation name.  Dimensions are left out:
# SOLIDWORKS lists them separately from relations.
RELATIONS = {
    "Coincident": "Coincident",
    "PointOnObject": "Coincident (on edge)",
    "Horizontal": "Horizontal",
    "Vertical": "Vertical",
    "Parallel": "Parallel",
    "Perpendicular": "Perpendicular",
    "Tangent": "Tangent",
    "Equal": "Equal",
    "Symmetric": "Symmetric",
    "Block": "Fix",
    "Lock": "Fix",
}
DIMENSIONS = {
    "Distance": "Distance", "DistanceX": "Horizontal distance",
    "DistanceY": "Vertical distance", "Radius": "Radius",
    "Diameter": "Diameter", "Angle": "Angle",
}

ADD_RELATIONS = [
    ("Horizontal", "Sketcher_ConstrainHorizontal"),
    ("Vertical", "Sketcher_ConstrainVertical"),
    ("Coincident", "Sketcher_ConstrainCoincidentUnified"),
    ("Coincident", "Sketcher_ConstrainCoincident"),
    ("Tangent", "Sketcher_ConstrainTangent"),
    ("Parallel", "Sketcher_ConstrainParallel"),
    ("Perpendicular", "Sketcher_ConstrainPerpendicular"),
    ("Equal", "Sketcher_ConstrainEqual"),
    ("Symmetric", "Sketcher_ConstrainSymmetric"),
    ("Fix", "Sketcher_ConstrainBlock"),
]

GEOMETRY_NAMES = {
    "LineSegment": "Line", "Circle": "Circle", "ArcOfCircle": "Arc",
    "Ellipse": "Ellipse", "ArcOfEllipse": "Elliptical arc", "Point": "Point",
    "BSplineCurve": "Spline",
}
POS_NAMES = {1: "start point", 2: "end point", 3: "centre"}

_dock = None
_last_key = None


# ----------------------------------------------------------------- model logic

def selected_entities(sketch):
    """[(kind, geo_id, pos)] for the current selection inside `sketch`.
    kind is 'edge' or 'vertex'; pos is None for edges."""
    out = []
    for item in Gui.Selection.getSelectionEx():
        if item.Object is not sketch:
            continue
        for sub in item.SubElementNames:
            if sub.startswith("Edge"):
                try:
                    out.append(("edge", int(sub[4:]) - 1, None))
                except ValueError:
                    pass
            elif sub.startswith("Vertex"):
                try:
                    geo, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
                    out.append(("vertex", geo, pos))
                except Exception:
                    pass
    return out


def relations_for(sketch, entities):
    """[(index, label, is_dimension)] of constraints touching the entities."""
    found = []
    for i, c in enumerate(sketch.Constraints):
        refs = [(getattr(c, "First", -2000), getattr(c, "FirstPos", 0)),
                (getattr(c, "Second", -2000), getattr(c, "SecondPos", 0)),
                (getattr(c, "Third", -2000), getattr(c, "ThirdPos", 0))]
        hit = False
        for kind, geo, pos in entities:
            for g, p in refs:
                if g != geo:
                    continue
                if kind == "edge" or p == pos or (c.Type in ("Block", "Lock")):
                    hit = True
        if not hit:
            continue
        if c.Type in RELATIONS:
            found.append((i, RELATIONS[c.Type], False))
        elif c.Type in DIMENSIONS:
            val = getattr(c, "Value", None)
            v = getattr(val, "Value", val)
            unit = "°" if c.Type == "Angle" else " mm"
            if c.Type == "Angle" and isinstance(v, (int, float)):
                import math
                v = math.degrees(v)
            text = f"{DIMENSIONS[c.Type]} = {v:.2f}{unit}" if isinstance(v, (int, float)) \
                else DIMENSIONS[c.Type]
            found.append((i, text, True))
    return found


def describe(sketch, entities):
    if not entities:
        return "", ""
    if len(entities) > 1:
        return f"{len(entities)} entities selected", ""
    kind, geo, pos = entities[0]
    try:
        g = sketch.Geometry[geo]
    except Exception:
        return "Entity", ""
    name = GEOMETRY_NAMES.get(type(g).__name__, type(g).__name__)
    detail = ""
    if kind == "vertex":
        return f"{name} {POS_NAMES.get(pos, 'point')}", ""
    try:
        if name == "Line":
            detail = f"Length: {g.length():.2f} mm"
        elif name in ("Circle", "Arc"):
            detail = f"Radius: {g.Radius:.2f} mm"
    except Exception:
        pass
    try:
        if sketch.getConstruction(geo):
            name = "Construction " + name.lower()
    except Exception:
        pass
    return name, detail


# ----------------------------------------------------------------- UI

def _find_dock(*names):
    for d in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget):
        if d.objectName() in names or d.windowTitle() in names:
            return d
    return None


def _ensure_dock():
    global _dock
    if _dock is not None:
        return _dock
    mw = Gui.getMainWindow()
    _dock = QtWidgets.QDockWidget("PropertyManager", mw)
    _dock.setObjectName("MechFlow_PropertyManager")
    _dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
    model = _find_dock("Model", "Tree view")
    area = mw.dockWidgetArea(model) if model else QtCore.Qt.LeftDockWidgetArea
    mw.addDockWidget(area, _dock)
    if model:
        mw.tabifyDockWidget(model, _dock)
    _dock.hide()
    return _dock


def _run(cmd):
    return lambda checked=False: Gui.runCommand(cmd, 0)


def _delete_relation(sketch, index):
    def go(checked=False):
        doc = sketch.Document
        doc.openTransaction("Delete relation")
        try:
            sketch.delConstraint(index)
            sketch.solve()
        finally:
            doc.commitTransaction()
        global _last_key
        _last_key = None  # force refresh
    return go


def _build_panel(sketch, entities):
    w = QtWidgets.QWidget()
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(8, 8, 8, 8)

    title, detail = describe(sketch, entities)
    head = QtWidgets.QLabel(f"<b>{title}</b>")
    lay.addWidget(head)
    if detail:
        lay.addWidget(QtWidgets.QLabel(detail))

    # Existing relations
    box = QtWidgets.QGroupBox("Existing Relations")
    bl = QtWidgets.QVBoxLayout(box)
    rels = relations_for(sketch, entities)
    if not rels:
        none = QtWidgets.QLabel("None - this entity is free to move.")
        none.setStyleSheet("color: gray;")
        bl.addWidget(none)
    for index, label, is_dim in rels:
        row = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel(label)
        if is_dim:
            lbl.setStyleSheet("color: gray;")
        row.addWidget(lbl, 1)
        rm = QtWidgets.QToolButton()
        rm.setText("✕")
        rm.setToolTip("Delete this relation")
        rm.setAutoRaise(True)
        rm.clicked.connect(_delete_relation(sketch, index))
        row.addWidget(rm)
        bl.addLayout(row)
    lay.addWidget(box)

    # Add relations
    available = set(Gui.listCommands())
    add = QtWidgets.QGroupBox("Add Relations")
    grid = QtWidgets.QGridLayout(add)
    seen = set()
    n = 0
    for label, cmd in ADD_RELATIONS:
        if label in seen or cmd not in available:
            continue
        seen.add(label)
        b = QtWidgets.QPushButton(label)
        b.setToolTip(f"Add a {label.lower()} relation to the selection")
        b.clicked.connect(_run(cmd))
        grid.addWidget(b, n // 2, n % 2)
        n += 1
    lay.addWidget(add)

    hint = QtWidgets.QLabel("Select more entities (Ctrl+click) to relate them.")
    hint.setWordWrap(True)
    hint.setStyleSheet("color: gray;")
    lay.addWidget(hint)
    lay.addStretch(1)
    return w


# ----------------------------------------------------------------- polling

def update(sketch):
    """Called a few times a second while a sketch is being edited."""
    global _last_key
    entities = selected_entities(sketch) if sketch is not None else []
    key = (getattr(sketch, "Name", None), tuple(entities),
           len(sketch.Constraints) if sketch is not None else 0)
    if key == _last_key:
        return
    _last_key = key
    dock = _ensure_dock()
    if entities:
        old = dock.widget()
        dock.setWidget(_build_panel(sketch, entities))
        if old is not None:
            old.deleteLater()
        dock.show()
        dock.raise_()
    else:
        dock.hide()
        model = _find_dock("Model", "Tree view")
        if model:
            model.raise_()


def stop():
    global _last_key
    _last_key = None
    if _dock is not None:
        _dock.hide()
