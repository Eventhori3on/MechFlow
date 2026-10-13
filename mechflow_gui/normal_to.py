# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Normal To (Ctrl+8).

- In a sketch: look straight at the sketch plane.
- A flat face, plane or sketch selected: look straight at it.
- Run it again while already looking straight at it: flip to the other side.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets


def _target_normal():
    """(normal, centre) in global coordinates for what Normal To should face."""
    from mechflow_gui import sketch_mode
    if sketch_mode.editing_sketch():
        sk = Gui.ActiveDocument.getInEdit().Object
        pl = sk.getGlobalPlacement()
        return pl.Rotation.multVec(App.Vector(0, 0, 1)), pl.Base

    for item in Gui.Selection.getSelectionEx():
        obj = item.Object
        for sub, shp in zip(item.SubElementNames, item.SubObjects):
            if sub.startswith("Face"):
                try:
                    if type(shp.Surface).__name__ != "Plane":
                        continue
                    from mechflow_gui import pick_solid
                    p, n = pick_solid._face_probe(shp)
                    return n, p
                except Exception:
                    continue
        if not item.SubElementNames:
            if obj.TypeId in ("Sketcher::SketchObject", "App::Plane", "PartDesign::Plane"):
                try:
                    pl = obj.getGlobalPlacement()
                except Exception:
                    pl = obj.Placement
                return pl.Rotation.multVec(App.Vector(0, 0, 1)), pl.Base
    return None, None


def _camera_rotation(n):
    """Camera rotation that looks along -n (camera +Z = n), with a sensible 'up'."""
    z = App.Vector(n).normalize()
    up = App.Vector(0, 0, 1)
    if abs(up.dot(z)) > 0.99:
        up = App.Vector(0, 1, 0)
    x = up.cross(z).normalize()
    y = z.cross(x).normalize()
    return App.Rotation(x, y, z, "ZYX")


def run():
    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    if view is None:
        return
    n, _centre = _target_normal()
    if n is None:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Normal To",
            "Select a flat face, a plane or a sketch first (or use it inside a sketch).")
        return
    try:
        cur = view.getCameraOrientation()
        cur_z = cur.multVec(App.Vector(0, 0, 1))
        if cur_z.dot(App.Vector(n).normalize()) > 0.999:
            n = App.Vector(n) * -1          # already facing it: flip, as SOLIDWORKS does
    except Exception:
        pass
    try:
        view.setCameraOrientation(_camera_rotation(n))
    except Exception as e:
        App.Console.PrintWarning(f"MechFlow: Normal To failed ({e})\n")
