# MechFlow - a SOLIDWORKS-style workflow layer for FreeCAD.
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# Note: __file__ is not defined when FreeCAD runs InitGui.py, so paths are
# resolved inside the mechflow package instead.

import FreeCADGui as Gui


class MechFlowWorkbench(Gui.Workbench):
    MenuText = "MechFlow"
    ToolTip = "A familiar, SOLIDWORKS-style workflow for part design"
    Icon = ""

    def __init__(self):
        import mechflow_gui as mechflow
        self.__class__.Icon = mechflow.icon_path("MechFlow.svg")

    def Initialize(self):
        """Runs once, the first time the workbench is opened."""
        import FreeCAD as App
        from mechflow_gui import commands, command_manager

        command_manager.load_freecad_modules()
        commands.register()

        # Each optional feature starts on its own, so one failure can't stop
        # the rest of MechFlow from loading.
        def step(name, fn):
            try:
                fn()
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: {name} failed to start ({e})\n")

        from mechflow_gui import naming, sketch_mode, view_toolbar, welcome, sketch_start
        step("hover highlight check", sketch_start.restore_after_crash)
        step("feature naming", naming.install)
        step("sketch mode", sketch_mode.install)
        step("startup workbench", view_toolbar.set_start_workbench)
        step("welcome page", welcome.show_at_startup)
        from mechflow_gui import shortcut_bar, feature_highlight
        step("S-key shortcut bar", shortcut_bar.install)
        from mechflow_gui import theme
        step("background check", theme.restore_after_crash)
        from mechflow_gui import section
        step("section tidy-up", section.tidy_left_overs)
        step("section save guard", section.install)
        from mechflow_gui import routing
        step("pipe route rebuild", routing.install)
        from mechflow_gui import hole_wizard
        step("Up To Next holes follow the part", hole_wizard.install)
        from mechflow_gui import title_block, sheet_tools
        step("title block fit", title_block.install)
        step("drawing mouse", sheet_tools.install)
        from mechflow_gui import view_align
        step("projected views keep their layout", view_align.install)
        step("selection highlight check", feature_highlight.restore_after_crash)
        step("quiet tree selection", feature_highlight.install)
        from mechflow_gui import sketch_status
        step("sketch colour check", sketch_status.restore_after_crash)
        # After a FreeCAD update the splash branding file is gone: offer to
        # put it back, once FreeCAD has finished starting.
        try:
            from PySide6 import QtCore
        except ImportError:
            from PySide2 import QtCore
        from mechflow_gui import splash
        QtCore.QTimer.singleShot(5000, lambda: step("splash check", splash.check_at_startup))
        # Toolbox fasteners keep their standard names in reopened files.
        from mechflow_gui import toolbox
        QtCore.QTimer.singleShot(3000, lambda: step("toolbox names", toolbox.patch_labels))

        # Own commands live in the CommandManager and the MechFlow menu,
        # not a separate toolbar row.
        # Section View in FreeCAD's View menu, where the old clipping plane was.
        self.appendMenu("&View", ["Separator", "MechFlow_SectionView"])
        self.appendMenu("MechFlow", ["MechFlow_Welcome", "Separator",
                                     "MechFlow_NewPart", "MechFlow_BossExtrude",
                                     "MechFlow_CutExtrude", "MechFlow_Revolve",
                                     "MechFlow_CutRevolve", "MechFlow_HoleWizard",
                                     "MechFlow_Sweep", "MechFlow_CutSweep",
                                     "MechFlow_Loft", "MechFlow_CutLoft",
                                     "MechFlow_Fillet", "MechFlow_Chamfer",
                                     "MechFlow_Shell", "MechFlow_Draft",
                                     "MechFlow_LinearPattern",
                                     "MechFlow_CircularPattern", "MechFlow_Mirror",
                                     "MechFlow_Plane", "MechFlow_Axis",
                                     "Separator",
                                     "MechFlow_EditFeature", "MechFlow_NormalTo",
                                     "MechFlow_SectionView",
                                     "Separator",
                                     "MechFlow_Suppress", "MechFlow_Unsuppress",
                                     "MechFlow_RollBack", "MechFlow_RollToEnd",
                                     "Separator", "MechFlow_NewAssembly",
                                     "MechFlow_InsertComponents", "MechFlow_Mate",
                                     "MechFlow_Toolbox", "MechFlow_SmartFasteners", "MechFlow_BOM",
                                     "Separator", "MechFlow_StructuralMember",
                                     "MechFlow_TrimExtend", "MechFlow_EndCap",
                                     "MechFlow_Gusset", "MechFlow_CutList",
                                     "Separator", "MechFlow_SM_BaseFlange",
                                     "MechFlow_SM_EdgeFlange", "MechFlow_SM_Flatten",
                                     "MechFlow_SM_SaveDXF",
                                     "Separator", "MechFlow_MakeDrawing",
                                     "MechFlow_Standard3View", "MechFlow_SheetFormat",
                                     "MechFlow_TitleBlock", "MechFlow_ClientSheet",
                                     "MechFlow_TextBox", "MechFlow_SavePDF",
                                     "Separator", "MechFlow_EditMaterial",
                                     "MechFlow_MassProperties",
                                     "MechFlow_ToggleCommandManager",
                                     "MechFlow_ToggleProperties",
                                     "MechFlow_RenameOriginPlanes",
                                     "MechFlow_ToggleToolbars", "MechFlow_ToggleTheme",
                                     "Separator", "MechFlow_InstallSplash",
                                     "MechFlow_RestoreSplash"])

    def Activated(self):
        import FreeCAD as App
        from mechflow_gui import command_manager, layout, view_toolbar, hover
        for name, fn in (("theme", lambda: __import__(
                             "mechflow_gui.theme", fromlist=["x"]).apply()),
                         ("CommandManager", command_manager.show),
                         ("layout", layout.apply),
                         ("view toolbar", view_toolbar.show_later),
                         ("S-key bar", lambda: __import__(
                             "mechflow_gui.shortcut_bar", fromlist=["x"]).set_enabled(True)),
                         ("quiet tree selection", lambda: __import__(
                             "mechflow_gui.feature_highlight", fromlist=["x"]).start()),
                         ("sketch status", lambda: __import__(
                             "mechflow_gui.sketch_status", fromlist=["x"]).start()),
                         ("relations panel", lambda: __import__(
                             "mechflow_gui.relations", fromlist=["x"]).start())):
            try:
                fn()
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: {name} failed ({e})\n")

    def Deactivated(self):
        from mechflow_gui import command_manager, layout, view_toolbar, hover
        from mechflow_gui import shortcut_bar, feature_highlight
        for fn in (hover.stop, command_manager.hide, view_toolbar.hide, layout.restore,
                   lambda: shortcut_bar.set_enabled(False), feature_highlight.stop,
                   lambda: __import__("mechflow_gui.theme", fromlist=["x"]).restore(),
                   lambda: __import__("mechflow_gui.relations", fromlist=["x"]).stop(),
                   lambda: __import__("mechflow_gui.sketch_status", fromlist=["x"]).stop()):
            try:
                fn()
            except Exception:
                pass

    def ContextMenu(self, recipient):
        """Right-click menu: what makes sense for the current selection."""
        from mechflow_gui import commands
        import FreeCADGui as G
        try:
            if recipient == "View":
                commands.select_under_cursor()
            items = []
            sel = G.Selection.getSelectionEx()
            subs = [n for i in sel for n in i.SubElementNames]
            if commands.selection_is_sketchable():
                items.append("MechFlow_SketchOnSelection")
            if subs and all(n.startswith(("Edge", "Face")) for n in subs):
                items += ["MechFlow_Fillet", "MechFlow_Chamfer"]
            if len(subs) == 1 and subs[0].startswith("Face"):
                items.append("MechFlow_HoleWizard")
            if commands.selection_is_sketchable():
                items.append("MechFlow_NormalTo")
            if commands.selected_editable_feature():
                items.append("MechFlow_EditFeature")
            if commands.can_suppress_selection(True):
                items.append("MechFlow_Suppress")
            if commands.can_suppress_selection(False):
                items.append("MechFlow_Unsuppress")
            if commands.selected_feature_any():
                items.append("MechFlow_RollBack")
            if commands.is_rolled_back():
                items.append("MechFlow_RollToEnd")
            if any(i.Object.TypeId == "PartDesign::Body" and not i.SubElementNames
                   for i in sel):
                items.append("MechFlow_EditMaterial")
            if any(getattr(i.Object, "RouteLine", "") for i in sel):
                items.append("MechFlow_ChangePipeSize")
            if any(i.Object.isDerivedFrom("Mesh::Feature") or i.Object.isDerivedFrom("Points::Feature")
                   for i in sel):
                items.append("MechFlow_PipeFromScan")
            if any(hasattr(i.Object, "StdType") for i in sel):
                items.append("MechFlow_SavePartAs")
            if any(hasattr(i.Object, "ScanViewSettings") for i in sel):
                items.append("MechFlow_ScanView")
            if any(i.Object.TypeId == "TechDraw::DrawProjGroupItem" and
                   str(i.Object.Type) != "Front" for i in sel):
                items.append("MechFlow_BreakAlignment")
            if any(hasattr(i.Object, "MechFlowAlignment") for i in sel):
                items.append("MechFlow_DefaultAlignment")
            if any(i.Object.TypeId in ("TechDraw::DrawProjGroup", "TechDraw::DrawProjGroupItem")
                   for i in sel):
                items.append("MechFlow_ViewSpacing")
            if any(i.Object.TypeId == "TechDraw::DrawViewAnnotation" for i in sel):
                items.append("MechFlow_TextBox")
            if any(i.Object.TypeId in ("TechDraw::DrawPage", "TechDraw::DrawSVGTemplate")
                   for i in sel):
                items += ["MechFlow_TitleBlock", "MechFlow_ClientSheet"]
            if items:
                self.appendContextMenu("", items + ["Separator"])
        except Exception:
            pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(MechFlowWorkbench())


def _mechflow_app_icon():
    """MechFlow's icon on the FreeCAD window, taskbar and dialogs: set as soon
    as FreeCAD's event loop runs, and again once start-up is done."""
    try:
        try:
            from PySide6 import QtCore
        except ImportError:
            from PySide2 import QtCore
        from mechflow_gui import app_icon
        for ms in (0, 4000):
            QtCore.QTimer.singleShot(ms, app_icon.apply)
        QtCore.QTimer.singleShot(0, app_icon.brand_title)
    except Exception:
        pass


_mechflow_app_icon()
