# SPDX-License-Identifier: LGPL-2.1-or-later
"""Window layout tweaks applied while the MechFlow workbench is active.

- Hides FreeCAD toolbars that duplicate the CommandManager (restored on leaving).
- Tabs the Tasks panel behind the Model tree, PropertyManager style: it comes
  to the front when a feature dialog opens and hands back to the tree when it
  closes.
"""

import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

# FreeCAD toolbar object names to hide in MechFlow.
HIDE_TOOLBARS = {"Structure", "Macro", "Help"}

_hidden = []
_timer = None
_task_was_open = False


def _main():
    return Gui.getMainWindow()


def _find_dock(*names):
    for dock in _main().findChildren(QtWidgets.QDockWidget):
        if dock.objectName() in names or dock.windowTitle() in names:
            return dock
    return None


def _hide_toolbars():
    for bar in _main().findChildren(QtWidgets.QToolBar):
        if bar.objectName() in HIDE_TOOLBARS and bar.isVisible():
            bar.hide()
            _hidden.append(bar)


def _restore_toolbars():
    while _hidden:
        bar = _hidden.pop()
        try:
            bar.show()
        except RuntimeError:  # toolbar was deleted by FreeCAD
            pass


def _dock_tasks():
    model = _find_dock("Model", "Tree view")
    tasks = _find_dock("Tasks", "Task view")
    if not model or not tasks or model is tasks:
        return None, None
    mw = _main()
    if mw.dockWidgetArea(tasks) != mw.dockWidgetArea(model) or tasks.isFloating():
        tasks.setFloating(False)
        mw.addDockWidget(mw.dockWidgetArea(model), tasks)
    mw.tabifyDockWidget(model, tasks)
    model.raise_()
    return model, tasks


_sketch_was_open = False
_tasks_hidden_for_sketch = False
_reported = set()


def _report(where, err):
    """Show each distinct background error once in the Report view."""
    key = (where, str(err))
    if key in _reported:
        return
    _reported.add(key)
    try:
        import FreeCAD as App
        App.Console.PrintWarning(f"MechFlow ({where}): {err}\n")
    except Exception:
        pass


def _watch_sketch():
    """While a sketch is open: Sketch tab, tree in front, no Tasks tab,
    confirmation corner, PropertyManager. Re-applied every tick, because
    FreeCAD re-shows its Tasks panel on its own."""
    global _sketch_was_open, _tasks_hidden_for_sketch
    from mechflow_gui import command_manager, sketch_mode, sketch_props, view_toolbar
    now = sketch_mode.editing_sketch()

    if now != _sketch_was_open:
        _sketch_was_open = now
        try:
            command_manager.select_tab("Sketch" if now else "Features")
        except Exception as e:
            _report("sketch tab", e)
        from mechflow_gui import auto_edges
        if now:
            try:
                sketch_mode.note_sketch_opened(Gui.ActiveDocument.getInEdit().Object)
            except Exception as e:
                _report("sketch undo point", e)
            try:
                auto_edges.enter(Gui.ActiveDocument.getInEdit().Object)
            except Exception as e:
                _report("model edges", e)
        else:
            sketch_mode._session = False
            try:
                auto_edges.leave()
            except Exception as e:
                _report("tidy model edges", e)

    tasks = _find_dock("Tasks", "Task view")
    model = _find_dock("Model", "Tree view")
    if now:
        try:
            if tasks is not None and tasks.isVisible():
                tasks.hide()
                _tasks_hidden_for_sketch = True
                if model is not None:
                    model.raise_()
        except Exception as e:
            _report("hide Tasks", e)
        try:
            view_toolbar.set_confirmation_corner(True)
        except Exception as e:
            _report("confirmation corner", e)
        try:
            sketch_props.update(Gui.ActiveDocument.getInEdit().Object)
        except Exception as e:
            _report("PropertyManager", e)
        try:
            from mechflow_gui import convert_ref
            convert_ref.watch(Gui.ActiveDocument.getInEdit().Object)
        except Exception as e:
            _report("Convert Entities", e)
    else:
        if _tasks_hidden_for_sketch:
            _tasks_hidden_for_sketch = False
            try:
                if tasks is not None:
                    tasks.show()
                    if model is not None:
                        model.raise_()
            except Exception as e:
                _report("restore Tasks", e)
        try:
            view_toolbar.set_confirmation_corner(False)
            sketch_props.stop()
            from mechflow_gui import convert_ref
            convert_ref.forget()
        except Exception as e:
            _report("leave sketch", e)


_context = None


def _current_context():
    """'Drawing' (a sheet in front), 'Assembly' (an assembly open for
    editing) or 'Features'."""
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi is not None else None
    try:
        if sub is not None and sub.widget().metaObject().className().endswith("MDIViewPage"):
            return "Drawing"
    except RuntimeError:
        pass
    try:
        import FreeCAD as App
        doc = App.ActiveDocument
        for o in (doc.Objects if doc is not None else []):
            if o.isDerivedFrom("Assembly::AssemblyObject") and o.ViewObject.isInEditMode():
                return "Assembly"
    except Exception:
        pass
    return "Features"


def _watch_drawing():
    """Bring the matching CommandManager tab to the front, as SOLIDWORKS does
    for parts, assemblies and drawings."""
    global _context
    now = _current_context()
    if now != _context:
        first = _context is None
        _context = now
        if first and now == "Features":
            return
        from mechflow_gui import command_manager
        try:
            command_manager.select_tab(now)
        except Exception as e:
            _report("context tab", e)


def _watch_tasks():
    """Raise Tasks while a feature dialog is open, back to the tree after."""
    global _task_was_open
    try:
        _watch_drawing()
    except Exception as e:
        _report("drawing mode", e)
    try:
        _watch_sketch()
    except Exception as e:
        _report("sketch mode", e)
    try:
        from mechflow_gui import sketch_mode
        if sketch_mode.editing_sketch():
            return  # handled above
        open_now = bool(Gui.Control.activeDialog())
    except Exception:
        return
    if open_now == _task_was_open:
        return
    _task_was_open = open_now
    model = _find_dock("Model", "Tree view")
    tasks = _find_dock("Tasks", "Task view")
    if open_now and tasks:
        tasks.show()
        tasks.raise_()
    elif model:
        model.raise_()


PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
PROPERTY_SHARE = 0.18          # fraction of the Model pane given to properties
_saved_sizes = None


def _params():
    import FreeCAD as App
    return App.ParamGet(PARAMS)


def _property_splitter():
    """The splitter inside the Model pane that holds tree (top) + properties (bottom)."""
    model = _find_dock("Model", "Tree view")
    if not model:
        return None
    for sp in model.findChildren(QtWidgets.QSplitter):
        if sp.orientation() != QtCore.Qt.Vertical or sp.count() < 2:
            continue
        top = sp.widget(0)
        if isinstance(top, QtWidgets.QTreeWidget) or top.findChildren(QtWidgets.QTreeWidget):
            return sp
    return None


def _tidy_properties():
    global _saved_sizes
    sp = _property_splitter()
    if not sp:
        return
    if _saved_sizes is None:
        _saved_sizes = sp.sizes()
    props = sp.widget(sp.count() - 1)
    hidden = _params().GetBool("HidePropertyPanel", False)
    props.setVisible(not hidden)
    if not hidden:
        total = sum(sp.sizes()) or sp.height()
        bottom = int(total * PROPERTY_SHARE)
        sizes = [0] * sp.count()
        sizes[0] = total - bottom
        sizes[-1] = bottom
        sp.setSizes(sizes)


def _restore_properties():
    global _saved_sizes
    sp = _property_splitter()
    if not sp or _saved_sizes is None:
        return
    sp.widget(sp.count() - 1).setVisible(True)
    sp.setSizes(_saved_sizes)
    _saved_sizes = None


def toggle_properties():
    p = _params()
    p.SetBool("HidePropertyPanel", not p.GetBool("HidePropertyPanel", False))
    _tidy_properties()


def apply():
    global _timer, _sketch_was_open, _context
    _sketch_was_open = False  # re-check: the CommandManager was just rebuilt
    _context = None
    # Run after FreeCAD has finished setting up the workbench's toolbars.
    def _later():
        _hide_toolbars()
        _dock_tasks()
        # If FreeCAD was closed mid-sketch, its Tasks tab may have been saved
        # hidden: bring it back.
        try:
            from mechflow_gui import sketch_mode
            tasks = _find_dock("Tasks", "Task view")
            if tasks is not None and not tasks.isVisible() and not sketch_mode.editing_sketch():
                tasks.show()
                model = _find_dock("Model", "Tree view")
                if model is not None:
                    model.raise_()
        except Exception:
            pass
        _tidy_properties()
    QtCore.QTimer.singleShot(0, _later)

    if _timer is None:
        _timer = QtCore.QTimer(_main())
        _timer.setInterval(250)
        _timer.timeout.connect(_watch_tasks)
    _timer.start()


def restore():
    global _tasks_hidden_for_sketch
    if _timer is not None:
        _timer.stop()
    if _tasks_hidden_for_sketch:
        _tasks_hidden_for_sketch = False
        tasks = _find_dock("Tasks", "Task view")
        if tasks is not None:
            tasks.show()
    try:
        from mechflow_gui import sketch_props
        sketch_props.stop()
    except Exception:
        pass
    _restore_toolbars()
    _restore_properties()
