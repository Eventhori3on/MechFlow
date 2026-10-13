# SPDX-License-Identifier: LGPL-2.1-or-later
"""MechFlow's own commands."""

import FreeCAD as App
import FreeCADGui as Gui

from mechflow_gui import icon_path

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets


class NewPart:
    """New document with a Body, ready to sketch - like File > New > Part."""

    def GetResources(self):
        return {
            "Pixmap": icon_path("MechFlow.svg"),
            "MenuText": "New Part",
            "ToolTip": "Create a new part document with a body, ready for a first sketch",
        }

    def Activated(self):
        doc = App.newDocument("Part1")
        ensure_body(doc)

    def IsActive(self):
        return True


def ensure_body(doc=None):
    """Return the active Body, creating one if the part has none (SOLIDWORKS has
    no visible 'body' step - the part simply is the solid)."""
    doc = doc or App.ActiveDocument
    if doc is None:
        doc = App.newDocument("Part1")
    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    body = None
    try:
        body = view.getActiveObject("pdbody") if view else None
    except Exception:
        body = None
    if body is None:
        bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if bodies else doc.addObject("PartDesign::Body", "Body")
        try:
            Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        except Exception:
            pass
        doc.recompute()
    return body


class Sketch:
    """Sketch button: works whatever is open - no Body step needed."""

    def GetResources(self):
        return {
            "Pixmap": "Sketcher_NewSketch",
            "MenuText": "Sketch",
            "ToolTip": "Start a new sketch on the selected plane or flat face, or pick one",
        }

    def Activated(self):
        from mechflow_gui import sketch_start
        body = ensure_body()
        sketch_start.start(body)

    def IsActive(self):
        return True


class MassProperties:
    """Volume, mass, surface area and centre of mass of the selected solid."""

    def GetResources(self):
        return {
            "Pixmap": "Part_CheckGeometry",
            "MenuText": "Mass Properties",
            "ToolTip": "Volume, mass, surface area and centre of mass of the selection",
        }

    def Activated(self):
        sel = Gui.Selection.getSelection()
        shape = getattr(sel[0], "Shape", None) if sel else None
        if shape is None or shape.isNull() or not shape.Solids:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), "Mass Properties",
                "Select a body or solid feature first.")
            return

        from mechflow_gui import material
        mat, density = material.get(sel[0])
        if density is None:
            density, ok = QtWidgets.QInputDialog.getDouble(
                Gui.getMainWindow(), "Mass Properties",
                "No material set (use Edit Material to set one).\n"
                "Density (kg/m³) — e.g. steel 7850, aluminium 2700:",
                7850.0, 0.0, 100000.0, 1)
            if not ok:
                return
            mat = "Not set"

        vol_mm3 = shape.Volume
        mass_kg = vol_mm3 * 1e-9 * density
        com = shape.Solids[0].CenterOfMass if len(shape.Solids) == 1 \
            else _combined_com(shape.Solids)

        text = (
            f"Object: {sel[0].Label}\n\n"
            f"Material: {mat}\n"
            f"Density: {density:g} kg/m³\n"
            f"Mass: {mass_kg:.4f} kg\n"
            f"Volume: {vol_mm3:,.2f} mm³\n"
            f"Surface area: {shape.Area:,.2f} mm²\n\n"
            f"Centre of mass (mm):\n"
            f"  X = {com.x:.3f}\n  Y = {com.y:.3f}\n  Z = {com.z:.3f}"
        )
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Mass Properties", text)

    def IsActive(self):
        return App.ActiveDocument is not None


def _combined_com(solids):
    total = sum(s.Volume for s in solids)
    acc = App.Vector()
    for s in solids:
        acc += s.CenterOfMass * (s.Volume / total)
    return acc


class ToggleCommandManager:
    def GetResources(self):
        return {
            "Pixmap": icon_path("MechFlow.svg"),
            "MenuText": "Toggle CommandManager",
            "ToolTip": "Show or hide the MechFlow tabbed CommandManager",
        }

    def Activated(self):
        from mechflow_gui import command_manager
        command_manager.toggle()

    def IsActive(self):
        return True


PLANE_TYPES = ("App::Plane", "PartDesign::Plane")


def selection_is_sketchable():
    """True when exactly one plane or one flat face is selected."""
    sel = Gui.Selection.getSelectionEx()
    if len(sel) != 1:
        return False
    item = sel[0]
    obj = item.Object
    subs = item.SubElementNames
    if not subs:
        return obj.TypeId in PLANE_TYPES
    if len(subs) != 1 or not subs[0].startswith("Face"):
        return False
    try:
        import Part
        face = item.SubObjects[0]
        return isinstance(face.Surface, Part.Plane)
    except Exception:
        return False


class SketchOnSelection:
    """Right-click > Sketch on a plane or flat face, like SOLIDWORKS."""

    def GetResources(self):
        return {
            "Pixmap": "Sketcher_NewSketch",
            "MenuText": "Sketch",
            "ToolTip": "Start a new sketch on the selected plane or flat face",
        }

    def Activated(self):
        Gui.runCommand("PartDesign_NewSketch", 0)

    def IsActive(self):
        return App.ActiveDocument is not None and selection_is_sketchable()


class BossExtrude:
    def GetResources(self):
        return {
            "Pixmap": "PartDesign_Pad",
            "MenuText": "Extruded Boss/Base",
            "ToolTip": "Extrude the selected sketch into a solid (SOLIDWORKS-style dialog)",
        }

    def Activated(self):
        from mechflow_gui import extrude
        extrude.create(cut=False)

    def IsActive(self):
        return App.ActiveDocument is not None


class CutExtrude:
    def GetResources(self):
        return {
            "Pixmap": "PartDesign_Pocket",
            "MenuText": "Extruded Cut",
            "ToolTip": "Cut material using the selected sketch (SOLIDWORKS-style dialog)",
        }

    def Activated(self):
        from mechflow_gui import extrude
        extrude.create(cut=True)

    def IsActive(self):
        return App.ActiveDocument is not None


EDITABLE_TYPES = ("PartDesign::Pad", "PartDesign::Pocket",
                  "PartDesign::Fillet", "PartDesign::Chamfer",
                  "PartDesign::Revolution", "PartDesign::Groove",
                  "PartDesign::Hole",
                  "PartDesign::LinearPattern", "PartDesign::PolarPattern",
                  "PartDesign::Mirrored",
                  "PartDesign::Thickness", "PartDesign::Draft",
                  "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
                  "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft",
                  "PartDesign::Plane", "PartDesign::Line")

# TypeId -> (module, function) for the newer panels.
_PANELS = {
    "PartDesign::LinearPattern": ("patterns", "linear"),
    "PartDesign::PolarPattern": ("patterns", "circular"),
    "PartDesign::Mirrored": ("patterns", "mirror"),
    "PartDesign::Thickness": ("dressup", "shell"),
    "PartDesign::Draft": ("dressup", "draft"),
    "PartDesign::AdditivePipe": ("sweeploft", "sweep"),
    "PartDesign::SubtractivePipe": ("sweeploft", "sweep"),
    "PartDesign::AdditiveLoft": ("sweeploft", "loft"),
    "PartDesign::SubtractiveLoft": ("sweeploft", "loft"),
    "PartDesign::Plane": ("refgeom", "plane"),
    "PartDesign::Line": ("refgeom", "axis"),
}


def _run(module, fn, *args):
    import importlib
    getattr(importlib.import_module("mechflow_gui." + module), fn)(*args)


def edit_feature(feat):
    """Open MechFlow's own panel for a feature."""
    t = feat.TypeId
    if t in _PANELS:
        _run(*_PANELS[t], feat)
    elif t in ("PartDesign::Fillet", "PartDesign::Chamfer"):
        from mechflow_gui import edge_feature
        edge_feature.edit(feat)
    elif t in ("PartDesign::Revolution", "PartDesign::Groove"):
        from mechflow_gui import revolve
        revolve.edit(feat)
    elif t == "PartDesign::Hole":
        from mechflow_gui import hole_wizard
        hole_wizard.edit(feat)
    else:
        from mechflow_gui import extrude
        extrude.edit(feat)


def _simple(menu, tip, pixmap, fn, active=None):
    """Build a small command class."""
    class _Cmd:
        def GetResources(self):
            return {"Pixmap": pixmap, "MenuText": menu, "ToolTip": tip}

        def Activated(self):
            fn()

        def IsActive(self):
            return active() if active else App.ActiveDocument is not None
    return _Cmd()


def _revolve(cut):
    from mechflow_gui import revolve
    revolve.create(cut=cut)


def _hole():
    from mechflow_gui import hole_wizard
    hole_wizard.create()


def selected_feature_any():
    sel = Gui.Selection.getSelectionEx()
    if len(sel) == 1 and not sel[0].SubElementNames:
        o = sel[0].Object
        if o.isDerivedFrom("PartDesign::Feature") or o.TypeId == "Sketcher::SketchObject":
            return o
    return None


def _roll_back():
    from mechflow_gui import rollback
    f = selected_feature_any()
    if f is not None:
        rollback.roll_back_to(f)


def _roll_to_end():
    from mechflow_gui import rollback
    rollback.roll_to_end()


def _context_feature():
    """Feature selected in the tree, or the feature that made a selected face."""
    f = selected_feature_any()
    if f is not None and f.isDerivedFrom("PartDesign::Feature"):
        return f
    sel = Gui.Selection.getSelectionEx()
    if len(sel) == 1 and len(sel[0].SubElementNames) == 1 \
            and sel[0].SubElementNames[0].startswith("Face"):
        try:
            from mechflow_gui import pick_solid
            item = sel[0]
            body = pick_solid.body_of(item.Object) or (
                item.Object if item.Object.TypeId == "PartDesign::Body" else None)
            if body is not None:
                return pick_solid.creator_of(body, int(item.SubElementNames[0][4:]) - 1)
        except Exception:
            pass
    return None


def _suppress(on):
    from mechflow_gui import rollback
    f = _context_feature()
    if f is not None:
        rollback.set_suppressed(f, on)


def can_suppress_selection(on):
    from mechflow_gui import rollback
    f = _context_feature()
    if f is None:
        return False
    if not rollback.can_suppress(f):
        return on      # still offer Suppress, so the user is told why it can't
    return rollback.is_suppressed(f) != on


def is_rolled_back():
    from mechflow_gui import rollback, pick_solid
    b = pick_solid.active_body()
    return b is not None and rollback.rolled_back(b)


class FilletCmd:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Fillet", "MenuText": "Fillet",
                "ToolTip": "Round edges - click edges, or a face for all its edges"}

    def Activated(self):
        from mechflow_gui import edge_feature
        edge_feature.create("fillet")

    def IsActive(self):
        return App.ActiveDocument is not None


class ChamferCmd:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Chamfer", "MenuText": "Chamfer",
                "ToolTip": "Bevel edges - click edges, or a face for all its edges"}

    def Activated(self):
        from mechflow_gui import edge_feature
        edge_feature.create("chamfer")

    def IsActive(self):
        return App.ActiveDocument is not None


def selected_editable_feature():
    """The feature to edit: a selected feature, or the feature that made a
    selected face (right-click a face -> Edit Feature, as in SOLIDWORKS)."""
    sel = Gui.Selection.getSelectionEx()
    if len(sel) != 1:
        return None
    item = sel[0]
    if not item.SubElementNames:
        return item.Object if item.Object.TypeId in EDITABLE_TYPES else None
    subs = item.SubElementNames
    if len(subs) == 1 and subs[0].startswith("Face"):
        try:
            from mechflow_gui import pick_solid
            body = pick_solid.body_of(item.Object) or (
                item.Object if item.Object.TypeId == "PartDesign::Body" else None)
            if body is not None:
                f = pick_solid.creator_of(body, int(subs[0][4:]) - 1)
                if f is not None and f.TypeId in EDITABLE_TYPES:
                    return f
        except Exception:
            pass
    return None


def select_under_cursor():
    """Right-click behaves like SOLIDWORKS: if nothing is selected, select the
    face / edge / vertex under the mouse so the menu can offer the right tools."""
    try:
        if Gui.Selection.getSelectionEx():
            return
        view = Gui.ActiveDocument.ActiveView
        pos = view.getCursorPos()
    except Exception:
        return
    try:                     # one of MechFlow's drawn origin planes?
        from mechflow_gui import datum_display
        plane = datum_display.plane_under(view, pos)
        if plane is not None:
            Gui.Selection.addSelection(plane)
            return
    except Exception:
        pass
    try:
        info = view.getObjectInfo(pos)
    except Exception:
        return
    if not isinstance(info, dict) or not info.get("Object"):
        return
    doc = info.get("Document") or App.ActiveDocument.Name
    obj = info["Object"]
    sub = info.get("SubName") or info.get("Component") or ""
    if obj.startswith("MechFlow_Pick"):
        return
    try:
        Gui.Selection.addSelection(doc, obj, sub)
    except Exception:
        try:
            Gui.Selection.addSelection(doc, obj, info.get("Component") or "")
        except Exception:
            pass


class EditFeature:
    def GetResources(self):
        return {
            "Pixmap": "Std_TransformManip",
            "MenuText": "Edit Feature",
            "ToolTip": "Edit this extrude in the MechFlow dialog",
        }

    def Activated(self):
        feat = selected_editable_feature()
        if feat:
            edit_feature(feat)

    def IsActive(self):
        return selected_editable_feature() is not None


class RenameOriginPlanes:
    """Apply Front/Top/Right plane names to every body in an existing document."""

    def GetResources(self):
        return {
            "Pixmap": icon_path("MechFlow.svg"),
            "MenuText": "Apply MechFlow Names (part, planes)",
            "ToolTip": "Name the body after the part and the origin planes Front/Top/Right in this document",
        }

    def Activated(self):
        from mechflow_gui import naming
        doc = App.ActiveDocument
        for obj in doc.Objects:
            if obj.TypeId == "PartDesign::Body":
                naming._setup_body(doc.Name, obj.Name, new_body=False)
        naming.name_body_after_part(doc)

    def IsActive(self):
        return App.ActiveDocument is not None


class Welcome:
    def GetResources(self):
        return {
            "Pixmap": icon_path("MechFlow.svg"),
            "MenuText": "Welcome",
            "ToolTip": "Show the MechFlow Welcome page",
        }

    def Activated(self):
        from mechflow_gui import welcome
        welcome.show()

    def IsActive(self):
        return True


class ToggleOrigin:
    def GetResources(self):
        return {
            "Pixmap": "Std_AxisCross",
            "MenuText": "Show/Hide Origin",
            "ToolTip": "Show or hide the origin marker in the 3D view",
        }

    def Activated(self):
        from mechflow_gui import origin_marker
        origin_marker.toggle()

    def IsActive(self):
        return True


class ToggleToolbars:
    def GetResources(self):
        return {
            "Pixmap": icon_path("MechFlow.svg"),
            "MenuText": "Show/Hide FreeCAD Toolbars",
            "ToolTip": "Show or hide FreeCAD's own toolbars while in MechFlow",
        }

    def Activated(self):
        from mechflow_gui import view_toolbar
        view_toolbar.toggle_toolbars()

    def IsActive(self):
        return True


class ToggleProperties:
    def GetResources(self):
        return {
            "Pixmap": icon_path("MechFlow.svg"),
            "MenuText": "Show/Hide Property Panel",
            "ToolTip": "Show or hide the property panel under the model tree",
        }

    def Activated(self):
        from mechflow_gui import layout
        layout.toggle_properties()

    def IsActive(self):
        return True


def _sketch_toggle():
    """SOLIDWORKS' Sketch button: starts a sketch, or exits the open one."""
    from mechflow_gui import sketch_mode
    if sketch_mode.editing_sketch():
        Gui.runCommand("Sketcher_LeaveSketch", 0)
    else:
        Gui.runCommand("MechFlow_Sketch", 0)


def _normal_to():
    from mechflow_gui import normal_to
    normal_to.run()


def register():
    # SOLIDWORKS shortcut for Normal To, unless the user has set their own.
    sc = App.ParamGet("User parameter:BaseApp/Preferences/Shortcut")
    if not sc.GetString("MechFlow_NormalTo", ""):
        sc.SetString("MechFlow_NormalTo", "Ctrl+8")
    Gui.addCommand("MechFlow_ToggleProperties", ToggleProperties())
    Gui.addCommand("MechFlow_SketchOnSelection", SketchOnSelection())
    Gui.addCommand("MechFlow_RenameOriginPlanes", RenameOriginPlanes())
    Gui.addCommand("MechFlow_BossExtrude", BossExtrude())
    Gui.addCommand("MechFlow_CutExtrude", CutExtrude())
    Gui.addCommand("MechFlow_EditFeature", EditFeature())
    Gui.addCommand("MechFlow_Fillet", FilletCmd())
    Gui.addCommand("MechFlow_ToggleTheme", _simple(
        "Light / Dark Theme", "Switch between MechFlow's light SOLIDWORKS-style theme "
        "and FreeCAD's own", "Std_DlgParameter",
        lambda: __import__("mechflow_gui.theme", fromlist=["x"]).toggle(), lambda: True))
    Gui.addCommand("MechFlow_SketchToggle", _simple(
        "Sketch", "Start a sketch - or exit the sketch you're in",
        "Sketcher_NewSketch", _sketch_toggle, lambda: True))
    Gui.addCommand("MechFlow_SectionView", _simple(
        "Section View", "Show the part cut through, with the cut faces filled in",
        icon_path("SectionView.svg"), lambda: __import__(
            "mechflow_gui.section", fromlist=["x"]).toggle()))
    Gui.addCommand("MechFlow_NormalTo", _simple(
        "Normal To", "Look straight at the selected face, plane or sketch (Ctrl+8)",
        icon_path("NormalTo.svg"), _normal_to))
    Gui.addCommand("MechFlow_Revolve", _simple(
        "Revolved Boss/Base", "Revolve the selected sketch around an axis",
        "PartDesign_Revolution", lambda: _revolve(False)))
    Gui.addCommand("MechFlow_CutRevolve", _simple(
        "Revolved Cut", "Cut by revolving the selected sketch around an axis",
        "PartDesign_Groove", lambda: _revolve(True)))
    Gui.addCommand("MechFlow_HoleWizard", _simple(
        "Hole Wizard", "Standard holes: pick a face, click to place centres",
        "PartDesign_Hole", _hole))
    Gui.addCommand("MechFlow_RollBack", _simple(
        "Roll Back to Here", "Roll the part back to this feature",
        "PartDesign_MoveTip", _roll_back, lambda: selected_feature_any() is not None))
    Gui.addCommand("MechFlow_Suppress", _simple(
        "Suppress", "Rebuild the part without this feature (like SOLIDWORKS Suppress)",
        "Std_ToggleVisibility", lambda: _suppress(True),
        lambda: can_suppress_selection(True)))
    Gui.addCommand("MechFlow_Unsuppress", _simple(
        "Unsuppress", "Bring a suppressed feature back",
        "Std_ToggleVisibility", lambda: _suppress(False),
        lambda: can_suppress_selection(False)))
    Gui.addCommand("MechFlow_RollToEnd", _simple(
        "Roll to End", "Bring back all features after the rollback point",
        "PartDesign_MoveTip", _roll_to_end, is_rolled_back))
    Gui.addCommand("MechFlow_Chamfer", ChamferCmd())
    for name, menu, tip, pix, fn in (
        ("MakeDrawing", "Make Drawing from Part",
         "Make a drawing of the part: sheet, standard 3 view, isometric and title block",
         "TechDraw_PageDefault", "make_drawing"),
        ("Standard3View", "Standard 3 View",
         "Front, Top and Right views of the selected part on the open drawing",
         "TechDraw_ProjectionGroup", "standard_3_view"),
        ("SheetFormat", "Sheet Format/Size", "Change the drawing's sheet size and format",
         "TechDraw_PageTemplate", "sheet_format"),
        ("SavePDF", "Save as PDF", "Save the open drawing as a PDF",
         "TechDraw_PrintAll", "save_pdf"),
    ):
        Gui.addCommand("MechFlow_" + name, _simple(
            menu, tip, pix, (lambda f=fn: _run("drawings", f))))
    for name, menu, tip, pix, fn in (
        ("NewAssembly", "New Assembly", "Start a new assembly document",
         "Geoassembly", "new_assembly"),
        ("InsertComponents", "Insert Components",
         "Add parts or sub-assemblies to the assembly", "Assembly_InsertLink",
         "insert_components"),
        ("Mate", "Mate", "Mate two parts: pick a face, edge or point on each "
         "(Coincident, Concentric, Distance, ...)", "Assembly_CreateJointDistance", "mate"),
        ("Interference", "Interference Detection", "Find parts that overlap in the assembly",
         "Part_CheckGeometry", "interference_detection"),
    ):
        Gui.addCommand("MechFlow_" + name, _simple(
            menu, tip, pix, (lambda f=fn: _run("assembly", f)), lambda: True))
    Gui.addCommand("MechFlow_InstallSplash", _simple(
        "Use MechFlow Splash Screen", "Show the MechFlow splash screen when FreeCAD starts",
        icon_path("MechFlow.svg"), lambda: _run("splash", "install"), lambda: True))
    Gui.addCommand("MechFlow_RestoreSplash", _simple(
        "Restore FreeCAD Splash Screen", "Go back to FreeCAD's own splash screen",
        "freecad", lambda: _run("splash", "restore"), lambda: True))
    Gui.addCommand("MechFlow_Relations", _simple(
        "Display/Delete Relations", "Show or hide the Relations panel: add relations to "
        "the selected sketch entities, see and delete existing ones",
        "Constraint_PointOnPoint",
        lambda: __import__("mechflow_gui.relations", fromlist=["x"]).toggle(),
        lambda: True))
    for name, menu, tip, pix, mod, fn in (
        ("LinearPattern", "Linear Pattern", "Repeat features along a direction",
         "PartDesign_LinearPattern", "patterns", "linear"),
        ("CircularPattern", "Circular Pattern", "Repeat features around an axis",
         "PartDesign_PolarPattern", "patterns", "circular"),
        ("Mirror", "Mirror", "Mirror features about a face or plane",
         "PartDesign_Mirrored", "patterns", "mirror"),
        ("Shell", "Shell", "Hollow the part, removing the faces you pick",
         "PartDesign_Thickness", "dressup", "shell"),
        ("Draft", "Draft", "Taper faces about a neutral plane",
         "PartDesign_Draft", "dressup", "draft"),
        ("Sweep", "Swept Boss/Base", "Sweep a profile along a path",
         "PartDesign_AdditivePipe", "sweeploft", "sweep"),
        ("CutSweep", "Swept Cut", "Cut by sweeping a profile along a path",
         "PartDesign_SubtractivePipe", "sweeploft", "cut_sweep"),
        ("Loft", "Lofted Boss/Base", "Blend between two or more profiles",
         "PartDesign_AdditiveLoft", "sweeploft", "loft"),
        ("CutLoft", "Lofted Cut", "Cut by blending between profiles",
         "PartDesign_SubtractiveLoft", "sweeploft", "cut_loft"),
        ("Plane", "Plane", "Reference plane: offset, at an angle, mid plane or 3 points",
         "PartDesign_Plane", "refgeom", "plane"),
        ("Axis", "Axis", "Reference axis: centre of a round face, an edge, 2 points "
         "or 2 planes", "PartDesign_Line", "refgeom", "axis"),
        ("EditMaterial", "Edit Material", "Set the part's material (used by Mass "
         "Properties)", icon_path("Material.svg"),
         "material", "edit"),
    ):
        Gui.addCommand("MechFlow_" + name, _simple(
            menu, tip, pix, (lambda m=mod, f=fn: _run(m, f))))
    Gui.addCommand("MechFlow_ToggleToolbars", ToggleToolbars())
    Gui.addCommand("MechFlow_ToggleOrigin", ToggleOrigin())
    Gui.addCommand("MechFlow_Welcome", Welcome())
    Gui.addCommand("MechFlow_NewPart", NewPart())
    Gui.addCommand("MechFlow_Sketch", Sketch())
    Gui.addCommand("MechFlow_MassProperties", MassProperties())
    Gui.addCommand("MechFlow_ToggleCommandManager", ToggleCommandManager())
