# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Sheet Metal tab, built on the free SheetMetal
Workbench (installed separately through the Addon Manager; MechFlow calls
its commands under SOLIDWORKS names and adds Flatten and Save Flat as DXF).
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

MODULES = ["ExtrudedCutout", "SheetMetalBaseCmd", "SheetMetalBaseShapeCmd", "SheetMetalBend",
           "SheetMetalCmd", "SheetMetalHem", "SheetMetalCornerReliefCmd",
           "SheetMetalExtendCmd", "SheetMetalFoldCmd", "SheetMetalFormingCmd",
           "SheetMetalJunction", "SheetMetalRelief", "SheetMetalUnfoldCmd",
           "SheetMetalUnfolder", "SketchOnSheetMetalCmd", "SheetMetalSketch",
           "SheetMetalFromSolid"]

# MechFlow command: (SOLIDWORKS name, SheetMetal command, tooltip)
COMMANDS = [
    ("SM_BaseFlange", "Base Flange/Tab", "SheetMetal_AddBase",
     "Sheet metal part from a sketch: a closed profile makes a flat tab, an open one a "
     "bent flange. Select the sketch first."),
    ("SM_Convert", "Convert to Sheet Metal", "SheetMetal_FromSolid",
     "Turn a shelled solid into sheet metal: select a fixed face"),
    ("SM_EdgeFlange", "Edge Flange", "SheetMetal_AddWall",
     "Flange on the selected edges of a sheet metal part"),
    ("SM_SketchedBend", "Sketched Bend", "SheetMetal_AddFoldWall",
     "Bend along a sketch line: select the face, then the sketch"),
    ("SM_Hem", "Hem", "SheetMetal_AddHem", "Hem on the selected edges"),
    ("SM_Extend", "Extend Tab", "SheetMetal_Extrude", "Extend a sheet metal face"),
    ("SM_Cut", "Extruded Cut", "SheetMetal_AddCutout",
     "Cut a sketch through the sheet, normal to it"),
    ("SM_CornerRelief", "Corner Relief", "SheetMetal_AddCornerRelief",
     "Relief cuts where bends meet at a corner"),
    ("SM_Relief", "Bend Relief", "SheetMetal_AddRelief", "Relief cuts at the ends of bends"),
    ("SM_Rip", "Rip", "SheetMetal_AddJunction", "Gap along an edge so a box can be unfolded"),
    ("SM_InsertBends", "Insert Bends", "SheetMetal_AddBend",
     "Bends on the sharp edges of a converted part"),
    ("SM_Forming", "Forming Tool", "SheetMetal_Forming", "Stamp a forming tool shape"),
    ("SM_Shapes", "Sheet Metal Shapes", "SheetMetal_BaseShape",
     "Ready-made sheet metal shapes (box, channel, hat ...)"),
    ("SM_FlatOptions", "Flat Pattern Options", "SheetMetal_Unfold",
     "Unfold with options: K-factor, bend lines, sketch export"),
]


def available():
    try:
        import SheetMetalTools  # noqa: F401
        return True
    except Exception:
        return False


def load():
    """Register the SheetMetal commands (normally done by its own
    workbench)."""
    if not available():
        return False
    for m in MODULES:
        try:
            __import__(m)
        except Exception as e:
            App.Console.PrintLog(f"MechFlow sheet metal: {m}: {e}\n")
    return True


def icon_for(cmd):
    try:
        import SheetMetalTools
        path = os.path.join(os.path.dirname(SheetMetalTools.__file__), "Resources", "icons",
                            cmd + ".svg")
        if os.path.exists(path):
            return path
    except Exception:
        pass
    from mechflow_gui import icon_path
    return icon_path("SheetMetal.svg")


def offer_install():
    box = QtWidgets.QMessageBox(Gui.getMainWindow())
    box.setWindowTitle("Sheet Metal")
    box.setText("MechFlow's sheet metal tools use the free <b>SheetMetal Workbench</b>.<br><br>"
                "Install it from the Addon Manager: search for <b>SheetMetal</b>, click "
                "Install, then restart FreeCAD.")
    btn = box.addButton("Open Addon Manager", QtWidgets.QMessageBox.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.exec()
    if box.clickedButton() is btn:
        try:
            Gui.runCommand("Std_AddonMgr", 0)
        except Exception:
            pass


def run(cmd):
    if not load():
        offer_install()
        return
    if cmd not in Gui.listCommands():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Sheet Metal",
                                          f"This SheetMetal version has no {cmd} command.")
        return
    Gui.runCommand(cmd, 0)


def is_active(cmd):
    if not available():
        return App.ActiveDocument is not None
    load()
    c = Gui.Command.get(cmd)
    try:
        return bool(c and c.isActive())
    except Exception:
        return False


# ------------------------------------------------------------ flatten

def _is_sm(o):
    p = type(getattr(o, "Proxy", None)).__module__ if hasattr(o, "Proxy") else ""
    return bool(p) and (p.startswith("SheetMetal") or p in ("ExtrudedCutout",))


def _is_unfold(o):
    return type(getattr(o, "Proxy", None)).__name__ == "SMUnfold"


def sheet_metal_part(doc=None):
    """The last sheet metal feature: selected, the active body's tip, or the
    last one in the document."""
    doc = doc or App.ActiveDocument
    for s in Gui.Selection.getSelection():
        if _is_unfold(s):
            return s.baseObject[0]
        if _is_sm(s):
            return s
        tip = getattr(s, "Tip", None)
        if tip is not None and _is_sm(tip):
            return tip
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        if body is not None and _is_sm(body.Tip):
            return body.Tip
    except Exception:
        pass
    sms = [o for o in doc.Objects if _is_sm(o) and not _is_unfold(o)]
    # the one nothing else builds on
    tops = [o for o in sms if not any(_is_sm(x) and not _is_unfold(x) for x in o.InList)]
    return (tops or sms or [None])[-1]


def unfold_of(part):
    for o in part.Document.Objects:
        if _is_unfold(o) and o.baseObject and o.baseObject[0] is part:
            return o
    return None


def _fixed_face(part):
    """The face to unfold from: the biggest flat face."""
    best, area = None, -1
    for i, f in enumerate(part.Shape.Faces):
        if type(f.Surface).__name__ == "Plane" and f.Area > area:
            best, area = f"Face{i + 1}", f.Area
    return best


def flatten():
    """SOLIDWORKS Flatten: show the flat pattern (again to fold back)."""
    if not load():
        offer_install()
        return None
    part = sheet_metal_part()
    if part is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Flatten",
                                          "There's no sheet metal part to flatten.")
        return None
    flat = unfold_of(part)
    if flat is not None and flat.ViewObject.Visibility:
        flat.ViewObject.Visibility = False      # fold back
        part.ViewObject.Visibility = True
        _show_sketches(flat, False)
        return flat
    if flat is None:
        face = _fixed_face(part)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(part.Document.Name, part.Name, face)
        Gui.runCommand("SheetMetal_UnattendedUnfold", 0)
        Gui.Selection.clearSelection()
        flat = unfold_of(part)
        if flat is None:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Flatten",
                                          "The part couldn't be unfolded.")
            return None
        try:
            flat.GenerateSketch = True
            part.Document.recompute()
        except Exception:
            pass
    flat.ViewObject.Visibility = True
    part.ViewObject.Visibility = False
    _show_sketches(flat, True)              # outline and bend lines, as SOLIDWORKS
    _look_at(flat)
    return flat


def _look_at(flat):
    """Look straight at the flat pattern."""
    try:
        best, area = None, -1
        for f in flat.Shape.Faces:
            if type(f.Surface).__name__ == "Plane" and f.Area > area:
                best, area = f, f.Area
        n = best.normalAt(0, 0)
        view = Gui.ActiveDocument.ActiveView
        ax = max(range(3), key=lambda i: abs(n[i]))
        {0: view.viewRight, 1: view.viewFront, 2: view.viewTop}[ax]()
        view.fitAll()
    except Exception:
        pass


def _show_sketches(flat, on):
    for name in getattr(flat, "UnfoldSketches", []) or []:
        sk = flat.Document.getObject(name)
        if sk is not None:
            try:
                sk.ViewObject.Visibility = on
            except Exception:
                pass


def save_flat_dxf(path=None):
    """Save the flat pattern (outline, holes and bend lines) as a DXF."""
    if not load():
        offer_install()
        return None
    part = sheet_metal_part()
    if part is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Save Flat as DXF",
                                          "There's no sheet metal part.")
        return None
    flat = unfold_of(part)
    made_here = flat is None
    if flat is None:
        flat = flatten()
        if flat is None:
            return None
    try:
        flat.GenerateSketch = True
        flat.Document.recompute()
    except Exception:
        pass
    sketches = [flat.Document.getObject(n) for n in (flat.UnfoldSketches or [])]
    sketches = [s for s in sketches if s is not None]
    if not sketches:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Save Flat as DXF",
                                      "The flat pattern has no outline to save.")
        return None
    if path is None:
        doc = part.Document
        start = os.path.join(os.path.dirname(doc.FileName) if doc.FileName else
                             os.path.expanduser("~"), f"{doc.Label}-{part.Label}-flat.dxf")
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(),
                                                         "Save Flat as DXF", start,
                                                         "DXF (*.dxf)")
        if not path:
            return None
    import importDXF
    importDXF.export(sketches, path)
    if made_here:
        flatten()                         # fold back as it was
    elif not flat.ViewObject.Visibility:
        _show_sketches(flat, False)
    App.Console.PrintMessage(f"MechFlow: flat pattern saved to {path}\n")
    return path
