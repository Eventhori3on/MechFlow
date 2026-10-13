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
        step("selection highlight check", feature_highlight.restore_after_crash)
        step("quiet tree selection", feature_highlight.install)
        from mechflow_gui import sketch_status
        step("sketch colour check", sketch_status.restore_after_crash)

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
                                     "Separator", "MechFlow_MakeDrawing",
                                     "MechFlow_Standard3View", "MechFlow_SheetFormat",
                                     "MechFlow_SavePDF",
                                     "Separator", "MechFlow_EditMaterial",
                                     "MechFlow_MassProperties",
                                     "MechFlow_ToggleCommandManager",
                                     "MechFlow_ToggleProperties",
                                     "MechFlow_RenameOriginPlanes",
                                     "MechFlow_ToggleToolbars", "MechFlow_ToggleTheme"])

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
            if items:
                self.appendContextMenu("", items + ["Separator"])
        except Exception:
            pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(MechFlowWorkbench())
