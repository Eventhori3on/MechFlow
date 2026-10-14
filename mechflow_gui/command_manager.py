# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style tabbed CommandManager for FreeCAD.

Each button wraps an existing FreeCAD command, relabelled with the name a
SOLIDWORKS user expects. Commands that are missing in the running FreeCAD
version are skipped, so the bar never breaks on a version change.
"""

import os

import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

BAR_NAME = "MechFlow_CommandManager"

# (tab, [(label, freecad_command), ...]); None inserts a separator.
# Layout, SOLIDWORKS-style.  Entry kinds:
#   ("Label", "Command")                 big button, text under icon
#   ("stack", [(label, cmd), ...])        column of small buttons, text beside icon
#   ("grid", columns, [(label, cmd), ...]) small icon-only buttons in a grid
#   None                                  separator
TABS = [
    ("Features", [
        ("Extruded\nBoss/Base", "MechFlow_BossExtrude"),
        ("Revolved\nBoss/Base", "MechFlow_Revolve"),
        ("stack", [("Swept Boss/Base", "MechFlow_Sweep"),
                   ("Lofted Boss/Base", "MechFlow_Loft"),
                   ("Helix", "PartDesign_AdditiveHelix")]),
        None,
        ("Extruded\nCut", "MechFlow_CutExtrude"),
        ("Hole\nWizard", "MechFlow_HoleWizard"),
        ("Nozzle", "MechFlow_Nozzle"),
        ("Revolved\nCut", "MechFlow_CutRevolve"),
        ("stack", [("Swept Cut", "MechFlow_CutSweep"),
                   ("Lofted Cut", "MechFlow_CutLoft"),
                   ("Helical Cut", "PartDesign_SubtractiveHelix")]),
        None,
        ("Fillet", "MechFlow_Fillet"),
        ("Linear\nPattern", "MechFlow_LinearPattern"),
        ("stack", [("Chamfer", "MechFlow_Chamfer"),
                   ("Draft", "MechFlow_Draft"),
                   ("Shell", "MechFlow_Shell")]),
        ("stack", [("Circular Pattern", "MechFlow_CircularPattern"),
                   ("Mirror", "MechFlow_Mirror")]),
        None,
        ("stack", [("Plane", "MechFlow_Plane"),
                   ("Axis", "MechFlow_Axis"),
                   ("Point", "PartDesign_Point")]),
        ("Configu-\nrations", "MechFlow_Configurations"),
    ]),
    ("Sketch", [
        ("Sketch", "MechFlow_SketchToggle"),
        ("Smart\nDimension", "Sketcher_Dimension"),
        None,
        ("grid", 4, [("Line", "Sketcher_CreatePolyline"),
                     ("Corner Rectangle", "Sketcher_CreateRectangle"),
                     ("Center Rectangle", "Sketcher_CreateRectangle_Center"),
                     ("Straight Slot", "Sketcher_CreateSlot"),
                     ("Circle", "Sketcher_CreateCircle"),
                     ("Perimeter Circle", "Sketcher_Create3PointCircle"),
                     ("Centerpoint Arc", "Sketcher_CreateArc"),
                     ("3 Point Arc", "Sketcher_Create3PointArc"),
                     ("Polygon", "Sketcher_CreateRegularPolygon"),
                     ("Spline", "Sketcher_CreateBSpline"),
                     ("Ellipse", "Sketcher_CreateEllipseByCenter"),
                     ("Point", "Sketcher_CreatePoint")]),
        ("stack", [("Sketch Fillet", "Sketcher_CreateFillet"),
                   ("Sketch Chamfer", "Sketcher_CreateChamfer"),
                   ("Construction Geometry", "Sketcher_ToggleConstruction")]),
        None,
        ("Trim\nEntities", "Sketcher_Trimming"),
        ("stack", [("Extend Entities", "Sketcher_Extend"),
                   ("Split Entities", "Sketcher_Split")]),
        ("Convert\nEntities", "Sketcher_External"),
        ("stack", [("Offset Entities", "Sketcher_Offset"),
                   ("Intersection Curve", "Sketcher_Intersection")]),
        None,
        ("stack", [("Mirror Entities", "Sketcher_Symmetry"),
                   ("Linear Sketch Pattern", "MechFlow_LinearSketchPattern"),
                   ("Circular Sketch Pattern", "MechFlow_CircularSketchPattern")]),
        ("stack", [("Move Entities", "Sketcher_Translate"),
                   ("Copy Entities", "Sketcher_Copy"),
                   ("Scale Entities", "Sketcher_Scale")]),
        None,
        ("Display/Delete\nRelations", "MechFlow_Relations"),
        ("stack", [("Coincident", "Sketcher_ConstrainCoincidentUnified"),
                   ("Horizontal", "Sketcher_ConstrainHorizontal"),
                   ("Vertical", "Sketcher_ConstrainVertical")]),
        ("stack", [("Tangent", "Sketcher_ConstrainTangent"),
                   ("Equal", "Sketcher_ConstrainEqual"),
                   ("Fix", "Sketcher_ConstrainBlock")]),
        ("Repair\nSketch", "Sketcher_ValidateSketch"),
    ]),
    ("Weldments", [
        ("Sketch", "MechFlow_SketchToggle"),
        ("Structural\nMember", "MechFlow_StructuralMember"),
        ("Trim/\nExtend", "MechFlow_TrimExtend"),
        ("stack", [("End Cap", "MechFlow_EndCap"),
                   ("Gusset", "MechFlow_Gusset")]),
        None,
        ("Cut List", "MechFlow_CutList"),
    ]),
    ("Sheet Metal", [
        ("Base Flange/\nTab", "MechFlow_SM_BaseFlange"),
        ("Convert to\nSheet Metal", "MechFlow_SM_Convert"),
        ("Edge\nFlange", "MechFlow_SM_EdgeFlange"),
        ("stack", [("Sketched Bend", "MechFlow_SM_SketchedBend"),
                   ("Hem", "MechFlow_SM_Hem"),
                   ("Extend Tab", "MechFlow_SM_Extend")]),
        None,
        ("Extruded\nCut", "MechFlow_SM_Cut"),
        ("stack", [("Corner Relief", "MechFlow_SM_CornerRelief"),
                   ("Bend Relief", "MechFlow_SM_Relief"),
                   ("Rip", "MechFlow_SM_Rip")]),
        ("stack", [("Insert Bends", "MechFlow_SM_InsertBends"),
                   ("Forming Tool", "MechFlow_SM_Forming"),
                   ("Sheet Metal Shapes", "MechFlow_SM_Shapes")]),
        None,
        ("Flatten", "MechFlow_SM_Flatten"),
        ("stack", [("Save Flat as DXF", "MechFlow_SM_SaveDXF"),
                   ("Flat Pattern Options", "MechFlow_SM_FlatOptions")]),
    ]),
    ("Evaluate", [
        ("Measure", "Std_Measure"),
        ("Mass\nProperties", "MechFlow_MassProperties"),
        ("Edit\nMaterial", "MechFlow_EditMaterial"),
        ("Section\nView", "MechFlow_SectionView"),
        ("Check\nGeometry", "Part_CheckGeometry"),
        None,
        ("Stress\nCheck", "MechFlow_StressCheck"),
    ]),
    ("Drawing", [
        ("Make\nDrawing", "MechFlow_MakeDrawing"),
        ("Standard\n3 View", "MechFlow_Standard3View"),
        ("stack", [("Model View", "TechDraw_View"),
                   ("Projected View", "TechDraw_ProjectionGroup"),
                   ("Section View", "TechDraw_SectionView")]),
        ("stack", [("Detail View", "TechDraw_DetailView"),
                   ("Break", "TechDraw_BrokenView"),
                   ("Crop View", "TechDraw_ClipGroup")]),
        None,
        ("Smart\nDimension", "TechDraw_Dimension"),
        ("stack", [("Horizontal Dimension", "TechDraw_HorizontalDimension"),
                   ("Vertical Dimension", "TechDraw_VerticalDimension"),
                   ("Ordinate Dimension", "TechDraw_ExtensionCreateHorizCoordDimension")]),
        ("stack", [("Note", "TechDraw_RichTextAnnotation"),
                   ("Balloon", "TechDraw_Balloon"),
                   ("Leader", "TechDraw_LeaderLine")]),
        ("stack", [("Center Mark", "TechDraw_ExtensionCircleCenterLines"),
                   ("Centerline", "TechDraw_FaceCenterLine"),
                   ("Area Hatch/Fill", "TechDraw_Hatch")]),
        ("stack", [("Surface Finish", "TechDraw_SurfaceFinishSymbols"),
                   ("Weld Symbol", "TechDraw_WeldSymbol"),
                   ("Hole/Shaft Fit", "TechDraw_HoleShaftFit")]),
        None,
        ("stack", [("Sheet Format", "MechFlow_SheetFormat"),
                   ("Save as PDF", "MechFlow_SavePDF"),
                   ("Save as DXF", "TechDraw_ExportPageDXF")]),
        ("Save All\nas PDF", "MechFlow_SaveAllPDF"),
        ("Supplier\nPack", "MechFlow_SupplierPack"),
    ]),
    ("Assembly", [
        ("New\nAssembly", "MechFlow_NewAssembly"),
        ("Insert\nComponents", "MechFlow_InsertComponents"),
        ("Mate", "MechFlow_Mate"),
        ("stack", [("Toolbox", "MechFlow_Toolbox"),
                   ("Smart Fasteners", "MechFlow_SmartFasteners"),
                   ("Route Pipe", "MechFlow_RoutePipe")]),
        None,
        ("stack", [("New Part", "Assembly_InsertNewPart"),
                   ("Fix / Float", "Assembly_ToggleGrounded"),
                   ("Rebuild", "Assembly_SolveAssembly")]),
        ("stack", [("Gear Mate", "Assembly_CreateJointGears"),
                   ("Rack Pinion Mate", "Assembly_CreateJointRackPinion"),
                   ("Screw Mate", "Assembly_CreateJointScrew")]),
        None,
        ("stack", [("Exploded View", "MechFlow_ExplodedView"),
                   ("Bill of Materials", "MechFlow_BOM"),
                   ("Interference Detection", "MechFlow_Interference")]),
        ("Make\nDrawing", "MechFlow_MakeDrawing"),
        ("Supplier\nPack", "MechFlow_SupplierPack"),
    ]),
    ("Routing", [
        ("3D\nSketch", "MechFlow_Sketch3D"),
        ("Route\nPipe", "MechFlow_RoutePipe"),
        ("Valves &\nInstruments", "MechFlow_Valves"),
        ("Author\nComponent", "MechFlow_AuthorComponent"),
        ("stack", [("Pipe Specs", "MechFlow_PipeSpecs"),
                   ("Change Pipe Size", "MechFlow_ChangePipeSize")]),
        None,
        ("stack", [("Toolbox", "MechFlow_Toolbox"),
                   ("Nozzle", "MechFlow_Nozzle"),
                   ("Smart Fasteners", "MechFlow_SmartFasteners")]),
        None,
        ("stack", [("Bill of Materials", "MechFlow_BOM"),
                   ("Interference Detection", "MechFlow_Interference")]),
    ]),
]

# Fallbacks for commands renamed between FreeCAD versions.
ALIASES = {
    # FreeCAD 1.1 renamed "External geometry" to "Projection".
    "Sketcher_External": ["Sketcher_Projection", "Sketcher_CompExternal"],
    "PartDesign_NewSketch": ["Sketcher_NewSketch"],
    "Sketcher_ConstrainCoincidentUnified": ["Sketcher_ConstrainCoincident"],
    "Sketcher_Dimension": ["Sketcher_ConstrainDistance"],
    "Std_Measure": ["Std_MeasureDistance"],
    "Sketcher_CreateRegularPolygon": ["Sketcher_CreateHexagon"],
    "Sketcher_ConstrainBlock": ["Sketcher_ConstrainLock"],
    "Sketcher_CreateRectangle_Center": ["Sketcher_CompCreateRectangles"],
    "Sketcher_CreateChamfer": ["Sketcher_CompCreateFillets"],
}

_bar = None


def load_freecad_modules():
    """Import the GUI modules whose commands the bar wraps."""
    for mod in ("PartGui", "SketcherGui", "PartDesignGui", "TechDrawGui", "AssemblyGui"):
        try:
            __import__(mod)
        except ImportError:
            pass
    try:   # TechDraw's Python tools (e.g. Hole/Shaft Fit)
        __import__("TechDrawTools")
    except Exception:
        pass
    _load_assembly_commands()


def _load_assembly_commands():
    """FreeCAD only registers its Assembly commands when the Assembly
    workbench first starts; load the same modules so MechFlow's Assembly tab
    works without visiting that workbench."""
    import sys
    import FreeCAD as App
    path = App.getHomePath() + "Mod/Assembly"
    if path not in sys.path:
        sys.path.append(path)
    try:
        Gui.addIconPath(":/icons")
    except Exception:
        pass
    for mod in ("Assembly_rc", "CommandCreateAssembly", "CommandInsertLink",
                "CommandInsertNewPart", "CommandCreateJoint", "CommandSolveAssembly",
                "CommandCreateView", "CommandCreateBom"):
        try:
            __import__(mod)
        except Exception as e:
            App.Console.PrintLog(f"MechFlow: assembly module {mod} not loaded ({e})\n")


def _resolve(name, available):
    for candidate in [name] + ALIASES.get(name, []):
        if candidate in available:
            return candidate
    return None


def _icon_for(pixmap):
    """Best-effort icon lookup when FreeCAD hasn't created the command's action yet."""
    if not pixmap:
        return QtGui.QIcon()
    if os.path.isfile(pixmap):
        return QtGui.QIcon(pixmap)
    getter = getattr(Gui, "getIcon", None)
    if getter:
        try:
            icon = getter(pixmap)
            if icon and not icon.isNull():
                return icon
        except Exception:
            pass
    for path in (f":/icons/{pixmap}.svg", f":/icons/{pixmap}.png", f":/icons/{pixmap}"):
        icon = QtGui.QIcon(path)
        if icon.availableSizes():
            return icon
    return QtGui.QIcon()


def _make_button(label, cmd_name):
    cmd = Gui.Command.get(cmd_name)
    if cmd is None:
        return None
    actions = cmd.getAction()

    btn = QtWidgets.QToolButton()
    btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
    btn.setIconSize(QtCore.QSize(28, 28))
    btn.setAutoRaise(True)
    btn.setText(label)

    if actions:
        # FreeCAD has already built this command's action: reuse it so the
        # button greys out exactly when FreeCAD's own toolbar would.
        action = actions[0]
        btn.setIcon(action.icon())
        btn.setToolTip(action.toolTip() or label.replace("\n", " "))
        btn.setEnabled(action.isEnabled())
        btn.clicked.connect(action.trigger)
        action.changed.connect(lambda b=btn, a=action: b.setEnabled(a.isEnabled()))
    else:
        # Action not created yet (FreeCAD builds them lazily): run by name.
        info = cmd.getInfo() if hasattr(cmd, "getInfo") else {}
        btn.setIcon(_icon_for(info.get("pixmap", "")))
        btn.setToolTip(info.get("toolTip") or label.replace("\n", " "))
        btn.clicked.connect(lambda checked=False, n=cmd_name: Gui.runCommand(n, 0))
    return btn


def _small_button(label, cmd_name, text_beside=True):
    btn = _make_button(label, cmd_name)
    if btn is None:
        return None
    btn.setIconSize(QtCore.QSize(16, 16))
    if text_beside:
        btn.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
    else:
        btn.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        btn.setToolTip(label)
    return btn


def _separator():
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.VLine)
    line.setStyleSheet("color: #cfcfcf;")
    return line


def _build_tabs():
    available = set(Gui.listCommands())
    tabs = QtWidgets.QTabWidget()
    tabs.setDocumentMode(True)
    tabs.setTabPosition(QtWidgets.QTabWidget.South)

    for title, entries in TABS:
        page = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(page)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(2)
        added = 0
        for entry in entries:
            if entry is None:
                if added:
                    row.addWidget(_separator())
                continue
            kind = entry[0]
            if kind == "stack":
                col = QtWidgets.QVBoxLayout()
                col.setSpacing(0)
                n = 0
                for label, wanted in entry[1]:
                    name = _resolve(wanted, available)
                    b = _small_button(label, name) if name else None
                    if b:
                        col.addWidget(b, 0, QtCore.Qt.AlignLeft)
                        n += 1
                if n:
                    col.addStretch(1)
                    row.addLayout(col)
                    added += 1
            elif kind == "grid":
                cols, items = entry[1], entry[2]
                grid = QtWidgets.QGridLayout()
                grid.setSpacing(0)
                n = 0
                for label, wanted in items:
                    name = _resolve(wanted, available)
                    b = _small_button(label, name, text_beside=False) if name else None
                    if b:
                        grid.addWidget(b, n // cols, n % cols)
                        n += 1
                if n:
                    row.addLayout(grid)
                    added += 1
            else:
                label, wanted = entry
                name = _resolve(wanted, available)
                btn = _make_button(label, name) if name else None
                if btn:
                    btn.setIconSize(QtCore.QSize(26, 26))
                    row.addWidget(btn, 0, QtCore.Qt.AlignTop)
                    added += 1
        row.addStretch(1)
        tabs.addTab(page, title)
    return tabs


def _create_bar():
    mw = Gui.getMainWindow()
    bar = QtWidgets.QToolBar("MechFlow CommandManager", mw)
    bar.setObjectName(BAR_NAME)
    bar.setMovable(False)
    bar.addWidget(_build_tabs())
    mw.addToolBarBreak(QtCore.Qt.TopToolBarArea)
    mw.addToolBar(QtCore.Qt.TopToolBarArea, bar)
    return bar


def select_tab(title):
    """Bring a CommandManager tab (e.g. "Sketch", "Features") to the front."""
    if _bar is None:
        return
    for tabs in _bar.findChildren(QtWidgets.QTabWidget):
        for i in range(tabs.count()):
            if tabs.tabText(i) == title:
                tabs.setCurrentIndex(i)
                return


def rebuild():
    """Rebuild buttons, e.g. after another workbench registered new commands."""
    global _bar
    if _bar is not None:
        _bar.clear()
        _bar.addWidget(_build_tabs())


def show():
    global _bar
    if _bar is None:
        _bar = _create_bar()
    else:
        rebuild()
    _bar.show()


def hide():
    if _bar is not None:
        _bar.hide()


def toggle():
    if _bar is None or not _bar.isVisible():
        show()
    else:
        hide()
