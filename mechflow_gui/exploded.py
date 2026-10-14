# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exploded view, like SOLIDWORKS' auto-explode.

The biggest component stays put. Every other one moves straight out from it
along the axis it sits on (a nozzle's gasket, flanges and pipe slide out
along the nozzle, a door comes off its side), and parts in the same line
are spaced apart so each one can be seen.

The exploded copies are links (live geometry, moved positions) in an
"Exploded View" group beside the assembly; the assembly itself, its mates
and its BOM are not touched. Exploded View on the Assembly tab shows or
hides them; the supplier pack draws them.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtWidgets
except ImportError:
    from PySide2 import QtWidgets

V = App.Vector
GROUP = "ExplodedView"


def _shape(o):
    from mechflow_gui import drawing_pack
    try:
        s = drawing_pack.shape_once(o)
        return None if s is None or s.isNull() or not s.Solids else s
    except Exception:
        return None


def _bulk(s):
    try:
        return s.Volume
    except Exception:
        bb = s.BoundBox
        return bb.XLength * bb.YLength * bb.ZLength


def explode_offsets(comps, gap=None):
    """{component: move vector}. comps: the assembly's components."""
    shapes = {o: _shape(o) for o in comps}
    comps = [o for o in comps if shapes[o] is not None]
    if len(comps) < 2:
        return {o: V() for o in comps}
    base = max(comps, key=lambda o: _bulk(shapes[o]))
    B = shapes[base].BoundBox
    c0 = B.Center
    half = [max(B.XLength / 2, 1.0), max(B.YLength / 2, 1.0), max(B.ZLength / 2, 1.0)]
    if gap is None:
        gap = max(40.0, min(400.0, 0.25 * B.DiagonalLength))
    sides = {}
    for o in comps:
        if o is base:
            continue
        c = shapes[o].BoundBox.Center
        rel = [(c[i] - c0[i]) / half[i] for i in range(3)]
        ax = max(range(3), key=lambda i: abs(rel[i]))
        sign = 1 if rel[ax] >= 0 else -1
        sides.setdefault((ax, sign), []).append(o)
    out = {base: V()}
    for (ax, sign), objs in sides.items():
        others = [i for i in range(3) if i != ax]

        def box2(o):
            bb = shapes[o].BoundBox
            lo = (bb.XMin, bb.YMin, bb.ZMin)
            hi = (bb.XMax, bb.YMax, bb.ZMax)
            return [(lo[i], hi[i]) for i in others]

        # parts whose outlines overlap, seen along the axis, are in one line
        parent = {o: o for o in objs}

        def find(o):
            while parent[o] is not o:
                parent[o] = parent[parent[o]]
                o = parent[o]
            return o
        boxes = {o: box2(o) for o in objs}
        for i, a in enumerate(objs):
            for b in objs[i + 1:]:
                if all(boxes[a][k][0] <= boxes[b][k][1] + 1e-6 and
                       boxes[b][k][0] <= boxes[a][k][1] + 1e-6 for k in range(2)):
                    parent[find(a)] = find(b)
        lines = {}
        for o in objs:
            lines.setdefault(find(o), []).append(o)
        for line in lines.values():
            def inner(o):
                bb = shapes[o].BoundBox
                lo = (bb.XMin, bb.YMin, bb.ZMin)[ax]
                hi = (bb.XMax, bb.YMax, bb.ZMax)[ax]
                return lo if sign > 0 else -hi
            line.sort(key=inner)
            # each part opens a gap after the one before it, in proportion to
            # its own size across the line (a gasket a little, a vessel more)
            at = 0.0
            for k, o in enumerate(line):
                bb = shapes[o].BoundBox
                dims = (bb.XLength, bb.YLength, bb.ZLength)
                across = max(dims[i] for i in others)
                g = max(25.0, min(gap, max(0.4 * across, 0.25 * dims[ax])))
                if k == 0:
                    g = max(g, 0.5 * gap)
                at += g
                d = [0.0, 0.0, 0.0]
                d[ax] = sign * at
                out[o] = V(*d)
    return out


def follow(asm, move):
    """Moves for the assembly's other components (bolts left out of the
    view): each goes with the smallest drawn part it sits in or next to."""
    drawn = [(o, _shape(o)) for o in move]
    drawn = [(o, s.BoundBox) for o, s in drawn if s is not None]
    out = dict(move)
    for o in asm.Group:
        if o in out:
            continue
        s = _shape(o)
        if s is None:
            continue
        c = s.BoundBox.Center
        best = None
        for d, bb in drawn:
            big = App.BoundBox(bb)
            big.enlarge(max(5.0, 0.6 * s.BoundBox.DiagonalLength))
            if big.isInside(c):
                vol = bb.XLength * bb.YLength * bb.ZLength
                if best is None or vol < best[0]:
                    best = (vol, d)
        out[o] = out[best[1]] if best else V()
    return out


def _group(doc, make=True):
    g = doc.getObject(GROUP)
    if g is None and make:
        g = doc.addObject("App::DocumentObjectGroup", GROUP)
        g.Label = "Exploded View"
    return g


def _final(o):
    """(the object at the end of o's links, its placement in the assembly)."""
    try:
        lo, mat = o.getLinkedObject(True, App.Matrix(), True)
        if lo is not None and lo is not o:
            return lo, App.Placement(mat)
    except Exception:
        pass
    return o, o.Placement


def exploded_links(asm, comps, gap=None, with_rest=False):
    """Links to the components at their exploded positions, in the
    'Exploded View' group (made again each time). with_rest: the other
    components too (bolts), moved with what they hold. Returns (links, moves)."""
    doc = asm.Document
    g = _group(doc)
    # drawing views of the old links are pointed at the new ones afterwards
    views = {}
    for o in g.Group:
        for v in o.InList:
            if v.TypeId == "TechDraw::DrawViewPart":
                views[v.Name] = [getattr(x, "MechFlowOf", "") for x in v.Source]
    for v in views:
        try:
            doc.getObject(v).Source = []
        except Exception:
            pass
    for o in list(g.Group):
        try:
            doc.removeObject(o.Name)
        except Exception:
            pass
    moves = explode_offsets(comps, gap)
    todo = list(comps)
    if with_rest:
        moves = follow(asm, moves)
        todo += [o for o in moves if o not in comps]
    links = []
    for o in todo:
        if o not in moves:
            continue
        ln = doc.addObject("App::Link", "Exploded")
        # link straight to the part itself (a link to a link shows at the
        # inner link's place in the 3D view, whatever its own placement)
        target, where = _final(o)
        ln.setLink(target)
        ln.Label = f"{o.Label} (exploded)"
        ln.addProperty("App::PropertyString", "MechFlowOf", "MechFlow", "The component this shows", 4)
        ln.MechFlowOf = o.Name
        try:
            ln.LinkTransform = False
        except Exception:
            pass
        ln.Placement = App.Placement(moves[o], App.Rotation()).multiply(where)
        g.addObject(ln)
        links.append(ln)
    by = {ln.MechFlowOf: ln for ln in links}
    for name, was in views.items():
        v = doc.getObject(name)
        if v is not None:
            v.Source = [by[n] for n in was if n in by]
    doc.recompute()
    if App.GuiUp:
        on = _shown(asm)
        for ln in links:
            try:
                ln.ViewObject.Visibility = on
            except Exception:
                pass
    return links, moves


def _shown(asm):
    g = _group(asm.Document, False)
    return g is not None and getattr(g, "MechFlowShown", False)


def toggle(asm=None):
    """Exploded View: show the assembly exploded, or put it back."""
    from mechflow_gui import assembly, drawing_pack
    asm = asm or assembly.active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Exploded View",
                                          "Open an assembly first.")
        return None
    doc = asm.Document
    g = _group(doc)
    if not hasattr(g, "MechFlowShown"):
        g.addProperty("App::PropertyBool", "MechFlowShown", "MechFlow", "", 4)
    if not hasattr(g, "MechFlowHidden"):
        g.addProperty("App::PropertyStringList", "MechFlowHidden", "MechFlow", "", 4)
    if g.MechFlowShown:
        g.MechFlowShown = False
        for o in g.Group:
            o.ViewObject.Visibility = False
        for name in g.MechFlowHidden:
            o = doc.getObject(name)
            if o is not None:
                o.ViewObject.Visibility = True
        g.MechFlowHidden = []
        asm.ViewObject.Visibility = True
        return False
    comps, _n, _shown_fast = drawing_pack.view_sources(asm, fasteners=False)
    g.MechFlowShown = True
    links, _m = exploded_links(asm, comps, with_rest=True)
    # hide the assembly's parts themselves (hiding an assembly doesn't
    # always hide what's in it), remembering which to show again
    hidden = []
    for o in asm.Group:
        try:
            if o.ViewObject.Visibility and o.isDerivedFrom("App::DocumentObject") and \
                    not o.TypeId.startswith("Assembly::"):
                o.ViewObject.Visibility = False
                hidden.append(o.Name)
        except Exception:
            pass
    g.MechFlowHidden = hidden
    asm.ViewObject.Visibility = False
    g.ViewObject.Visibility = True
    for ln in links:
        ln.ViewObject.Visibility = True
    try:
        v = Gui.getDocument(doc.Name).ActiveView
        v.viewIsometric()
        v.fitAll()
    except Exception:
        pass
    return True
