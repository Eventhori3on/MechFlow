# SPDX-License-Identifier: LGPL-2.1-or-later
"""Keep converted model edges as reference lines (for dimensioning only).

FreeCAD 1.1 can make projected ("converted") edges *defining* - part of the
sketch's outline - which breaks a cut or boss with "Wire is not closed".
MechFlow switches newly converted edges to reference while you sketch, and
offers a one-click fix in the Boss/Cut panel for older sketches.

To use a converted edge as real geometry (e.g. re-using a slot), select it and
click Construction Geometry to toggle it.

Setting: Preferences/Mod/MechFlow  ConvertAsReference (default True).
"""

import FreeCAD as App

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"
EXT_TYPE = "Sketcher::ExternalGeometryExtension"

_seen = {}   # sketch name -> number of external geometries already handled


def enabled():
    return App.ParamGet(PARAMS).GetBool("ConvertAsReference", True)


def _externals(sketch):
    """[(index, geo_id, defining or None if unknown)] for converted edges.
    ExternalGeo[0] and [1] are the sketch's own H/V axes - skipped."""
    out = []
    try:
        geos = sketch.ExternalGeo
    except Exception:
        return out
    for i, g in enumerate(geos):
        if i < 2:
            continue
        defining = None
        try:
            ext = g.getExtensionOfType(EXT_TYPE)
            defining = bool(ext.testFlag("Defining"))
        except Exception:
            pass
        out.append((i, -(i + 1), defining))
    return out


def defining_externals(sketch):
    return [e for e in _externals(sketch) if e[2]]


def make_reference(sketch, entries=None):
    """Switch converted edges to reference. Returns how many were changed."""
    entries = defining_externals(sketch) if entries is None else entries
    changed = 0
    for _i, geo_id, _d in entries:
        try:
            sketch.toggleConstruction(geo_id)
            changed += 1
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: couldn't change converted edge ({e})\n")
    if changed:
        try:
            sketch.recompute()
        except Exception:
            pass
    return changed


def watch(sketch):
    """Called repeatedly while a sketch is open: newly converted edges that
    came in as defining are switched to reference."""
    if sketch is None or not enabled():
        return
    ext = _externals(sketch)
    seen = _seen.get(sketch.Name)
    if seen is None:
        _seen[sketch.Name] = len(ext)       # don't touch what was already there
        return
    if len(ext) <= seen:
        _seen[sketch.Name] = len(ext)
        return
    new = [e for e in ext[seen:] if e[2]]
    _seen[sketch.Name] = len(ext)
    if not new:
        return
    doc = sketch.Document
    doc.openTransaction("Converted edges as reference")
    try:
        make_reference(sketch, new)
    finally:
        doc.commitTransaction()


def forget(sketch_name=None):
    if sketch_name is None:
        _seen.clear()
    else:
        _seen.pop(sketch_name, None)
