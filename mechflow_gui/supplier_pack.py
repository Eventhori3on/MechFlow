# SPDX-License-Identifier: LGPL-2.1-or-later
"""Supplier Pack: everything a fabricator needs from one button.

    <assembly> - Supplier Pack/
        Drawings/   assembly sheet, exploded view, a dimensioned sheet per part (PDF)
        STEP/       the assembly and each part
        DXF/        flat profiles for plasma / laser cutting: every flat plate,
                    the panels of plate-built parts (a tank's walls) and
                    sheet metal flat patterns, named with thickness and quantity
        BOM.csv     the bill of materials (plus Cut list.csv for weldments)
        Contents.txt
    and the lot zipped, ready to send.
"""

import csv
import datetime
import math
import os
import re
import zipfile

import FreeCAD as App
from mechflow_gui import edge_curve, curve_name  # noqa: F401
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

V = App.Vector


def _safe(name):
    return re.sub(r'[<>:"/\\|?*]+', "-", str(name)).strip(" .") or "part"


# ------------------------------------------------------------ DXF

def _arc_angles(e):
    """(centre, r, start, end) in degrees, counter-clockwise about +Z."""
    c = e.Curve
    p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
    a0 = math.degrees(math.atan2(p0.y - c.Center.y, p0.x - c.Center.x))
    a1 = math.degrees(math.atan2(p1.y - c.Center.y, p1.x - c.Center.x))
    # which way does the edge run? look at its middle
    m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
    am = math.degrees(math.atan2(m.y - c.Center.y, m.x - c.Center.x))

    def ccw_between(a, b, x):            # is x on the ccw sweep a -> b?
        return (x - a) % 360 < (b - a) % 360
    if not ccw_between(a0, a1, am):
        a0, a1 = a1, a0
    return c.Center, c.Radius, a0 % 360, a1 % 360


def dxf_text(edges, layer="0"):
    """A plain R12 DXF of flat edges (in the XY plane): lines, arcs and
    circles, anything else as short lines. Millimetres."""
    out = ["0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009",
           "9", "$INSUNITS", "70", "4", "0", "ENDSEC",
           "0", "SECTION", "2", "ENTITIES"]

    def line(a, b):
        out.extend(["0", "LINE", "8", layer, "10", f"{a.x:.4f}", "20", f"{a.y:.4f}", "30", "0",
                    "11", f"{b.x:.4f}", "21", f"{b.y:.4f}", "31", "0"])
    for e in edges:
        kind = curve_name(e)
        if kind in ("Line", "LineSegment"):
            line(e.Vertexes[0].Point, e.Vertexes[-1].Point)
        elif kind == "Circle" and e.isClosed():
            c = e.Curve.Center
            out.extend(["0", "CIRCLE", "8", layer, "10", f"{c.x:.4f}", "20", f"{c.y:.4f}",
                        "30", "0", "40", f"{e.Curve.Radius:.4f}"])
        elif kind == "Circle":
            c, r, a0, a1 = _arc_angles(e)
            out.extend(["0", "ARC", "8", layer, "10", f"{c.x:.4f}", "20", f"{c.y:.4f}",
                        "30", "0", "40", f"{r:.4f}", "50", f"{a0:.4f}", "51", f"{a1:.4f}"])
        else:
            pts = e.discretize(Deflection=0.02)
            for a, b in zip(pts, pts[1:]):
                line(a, b)
    out.extend(["0", "ENDSEC", "0", "EOF"])
    return "\n".join(out) + "\n"


def flat_edges(face):
    """The face's edges laid flat in XY (outline at the origin)."""
    pl = face.Surface
    n = V(pl.Axis)
    u0, u1, v0, v1 = face.ParameterRange
    if face.Orientation == "Reversed":
        n = n * -1
    # x along the longest straight edge, so the profile sits square
    xdir = None
    for e in sorted(face.OuterWire.Edges, key=lambda e: -e.Length):
        if curve_name(e) in ("Line", "LineSegment"):
            xdir = e.Vertexes[-1].Point - e.Vertexes[0].Point
            break
    rot = App.Rotation(xdir or V(1, 0, 0), n.cross(xdir or V(1, 0, 0)), n, "ZXY") if xdir \
        else App.Rotation(V(0, 0, 1), n)
    f = face.copy()
    f.transformShape(App.Placement(V(), rot).inverse().toMatrix())
    bb = f.BoundBox
    f.translate(V(-bb.XMin, -bb.YMin, -bb.ZMin))
    return f.Edges, f.BoundBox


# ------------------------------------------------------------ finding plates

def _leaves(top):
    """(label, shape, object) for each solid-bearing part inside top
    (through Parts and links), leaving out structural members (cut list),
    bought-in parts and fasteners."""
    import Part
    from mechflow_gui import stdparts
    out = []

    def walk(path, o):
        lo = o.getLinkedObject(True) if hasattr(o, "getLinkedObject") else o
        if lo.TypeId == "App::Part" or lo.isDerivedFrom("App::Part"):
            for c in lo.Group:
                if c.TypeId.startswith("App::Origin") or c.isDerivedFrom("Part::Part2DObject"):
                    continue
                try:
                    if c.getParentGeoFeatureGroup() not in (lo, None):
                        continue
                except Exception:
                    pass
                walk(path + c.Name + ".", c)
            return
        kind = type(getattr(lo, "Proxy", None)).__name__
        if stdparts.is_std_object(lo) or kind in ("FSScrewObject", "StructuralMember", "PipeRoute"):
            return
        try:
            if lo.isDerivedFrom("App::DocumentObjectGroup"):
                return
        except Exception:
            pass
        try:
            sh = Part.getShape(top, path) if path else Part.getShape(o)
        except Exception:
            return
        if not sh.isNull() and sh.Solids:
            out.append((lo.Label, sh, lo))
    walk("", top)
    return out


def _inside_point(face, n=9):
    """A point well inside the face (away from its edges and holes)."""
    import Part
    u0, u1, v0, v1 = face.ParameterRange
    mid = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    margin = 0.05 * math.sqrt(face.Area)
    try:
        if face.isInside(mid, 1e-6, True) and \
                min(e.distToShape(Part.Vertex(mid))[0] for e in face.Edges) > margin:
            return mid
    except Exception:
        pass
    best = None
    for i in range(1, n):
        for j in range(1, n):
            u = u0 + (u1 - u0) * i / n
            v = v0 + (v1 - v0) * j / n
            p = face.valueAt(u, v)
            if not face.isInside(p, 1e-6, True):
                continue
            try:
                d = min(e.distToShape(Part.Vertex(p))[0] for e in face.Edges)
            except Exception:
                d = 0.0
            if best is None or d > best[0]:
                best = (d, p)
    return best[1] if best else None


def _thickness_at(shape, face):
    """(thickness, opposite face index) straight in from the face's middle."""
    import Part
    try:
        p = _inside_point(face)
        if p is None:
            return None, None
        n = V(face.normalAt(*face.Surface.parameter(p)))
        if shape.isInside(p + n * 0.05, 1e-6, True):
            n = n * -1
        reach = shape.BoundBox.DiagonalLength + 10
        seg = Part.LineSegment(p + n * 1e-3, p - n * reach).toShape()
        hit = seg.common(shape)
        if not hit.Edges:
            return None, None
        e = min(hit.Edges, key=lambda e: (e.Vertexes[0].Point - p).Length)
        far = e.Vertexes[0].Point if (e.Vertexes[0].Point - p).Length > (e.Vertexes[-1].Point - p).Length \
            else e.Vertexes[-1].Point
        t = e.Length
        opp = None
        axis = V(face.Surface.Axis)
        for j, g in enumerate(shape.Faces):
            if type(g.Surface).__name__ != "Plane":
                continue
            if abs(abs(V(g.Surface.Axis).dot(axis)) - 1) > 1e-4:
                continue
            try:
                if g.distToShape(Part.Vertex(far))[0] < 1e-3:
                    opp = j
                    break
            except Exception:
                continue
        return t, opp
    except Exception:
        return None, None


def plates_in(shape, min_area=1500.0):
    """Flat plates in a solid: [(face, thickness)]. A flat plate gives one;
    a box built of plate (a tank) gives one per wall - each wall's bigger
    face, i.e. the outside of the box. Thick lumps and round parts give none."""
    out = []
    used = set()
    faces = shape.Faces
    planar = [(i, f) for i, f in enumerate(faces) if type(f.Surface).__name__ == "Plane"]
    if not planar:
        return out
    biggest = max(f.Area for _i, f in planar)
    for i, f in sorted(planar, key=lambda t: -t[1].Area):
        if i in used or f.Area < max(min_area, 0.02 * biggest):
            continue
        t, j = _thickness_at(shape, f)
        if t is None or j is None:
            continue
        g = faces[j]
        size = math.sqrt(f.Area)
        if t > 0.25 * size or t < 0.3:          # a lump, not a plate
            continue
        if abs(abs(V(g.Surface.Axis).dot(V(f.Surface.Axis))) - 1) > 1e-4:
            continue                            # not a parallel-sided plate here
        used.update((i, j))
        # the side with the bigger outline (the outside of a box; holes and
        # things welded on don't count)
        def outline(x):
            try:
                import Part
                return Part.Face(x.OuterWire).Area
            except Exception:
                return x.Area
        big, small = (f, g) if outline(f) >= outline(g) else (g, f)
        out.append((_plate_profile(big, small), round(t, 1)))
    return out


def _plate_profile(a, b):
    """The plate's cut profile from its two sides: the plate is wherever
    either side has material (something welded onto one side - a door frame
    on the outside, a fitting inside - hides only that side), so the holes
    are the real through holes. Drawn on side a's plane."""
    try:
        n = V(a.Surface.Axis)
        d = (b.Surface.Position - a.Surface.Position).dot(n)
        bb = b.copy()
        bb.translate(n * -d)
        u = a.fuse(bb).removeSplitter()
        faces = [x for x in u.Faces if type(x.Surface).__name__ == "Plane"]
        if faces:
            best = max(faces, key=lambda x: x.Area)
            if best.Area >= a.Area - 1e-6:
                return best
    except Exception:
        pass
    return a


def _side(face, solid=None):
    """'top', 'front'... for a panel: which side of the part it is on."""
    try:
        n = V(face.Surface.Axis)
        ax = max(range(3), key=lambda i: abs(n[i]))
        c = solid.BoundBox.Center if solid is not None else V()
        d = face.BoundBox.Center[ax] - c[ax]
    except Exception:
        return "flat"
    return {(0, 1): "right", (0, -1): "left", (1, 1): "back", (1, -1): "front",
            (2, 1): "top", (2, -1): "bottom"}[(ax, 1 if d > 0 else -1)]


def _points(edges):
    """Every edge's middle (and a circle's centre), for comparing profiles."""
    pts = []
    for e in edges:
        m = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
        pts.append((m.x, m.y))
        if curve_name(e) == "Circle":
            pts.append((e.Curve.Center.x, e.Curve.Center.y))
    return pts


def _signature(face, t):
    edges, bb = flat_edges(face)
    W, H = bb.XLength, bb.YLength
    pts = _points(edges)

    def key(ps):
        return tuple(sorted((round(x * 2) / 2, round(y * 2) / 2) for x, y in ps))
    # the same cut part, turned over or round, is the same profile
    variants = {key(pts), key([(W - x, y) for x, y in pts]), key([(x, H - y) for x, y in pts]),
                key([(W - x, H - y) for x, y in pts])}
    return (round(t, 1), round(W * 2) / 2, round(H * 2) / 2, len(edges), variants)


def _same(a, b):
    return a[:4] == b[:4] and bool(a[4] & b[4])


def write_flats(targets, folder):
    """DXF flats for the parts' plates. targets: [([objects], title)].
    Returns [(file, thickness, qty, size text, part)]."""
    os.makedirs(folder, exist_ok=True)
    from mechflow_gui import bom
    found = []                      # [signature, face, t, qty, part, name, sides]
    for objs, title in targets:
        for top in objs:
            for label, sh, lo in _leaves(top):
                for s in sh.Solids:
                    plates = plates_in(s)
                    whole = len(plates) == 1 and abs(plates[0][0].Area * plates[0][1] - s.Volume) \
                        < 0.03 * s.Volume
                    for k, (face, t) in enumerate(plates):
                        sig = _signature(face, t)
                        side = None if whole else _side(face, s)
                        same = [f for f in found if _same(f[0], sig)]
                        if same:
                            same[0][3] += 1
                            if side and side not in same[0][6]:
                                same[0][6].append(side)
                            continue
                        name = bom._strip_instance(label)
                        if name in ("Body", title):
                            name = title
                        found.append([sig, face, t, 1, title, name, [side] if side else []])
    written = []
    used = set()
    for _sig, face, t, qty, title, name, sides in found:
        if sides:
            name = f"{name} {' and '.join(sides)} panel"
        try:
            edges, bb = flat_edges(face)
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: no flat for {name} ({e})\n")
            continue
        base = name if name.startswith(title) else f"{title} - {name}"
        fn = _safe(f"{base} - {t:g}mm x{qty}") + ".dxf"
        k = 2
        while fn.lower() in used:
            fn = _safe(f"{base} ({k}) - {t:g}mm x{qty}") + ".dxf"
            k += 1
        used.add(fn.lower())
        open(os.path.join(folder, fn), "w", encoding="ascii", errors="replace").write(dxf_text(edges))
        written.append((fn, t, qty, f"{bb.XLength:.0f} x {bb.YLength:.0f}", title))
    return written


def write_sheet_metal(targets, folder):
    """Flat patterns of sheet metal parts (needs the SheetMetal add-on)."""
    from mechflow_gui import sheet_metal
    out = []
    try:
        if not sheet_metal.load():
            return out
    except Exception:
        return out
    seen = set()
    for objs, title in targets:
        for top in objs:
            lo = top.getLinkedObject(True) if hasattr(top, "getLinkedObject") else top
            doc = lo.Document
            if doc.Name in seen:
                continue
            sms = [o for o in doc.Objects if sheet_metal._is_sm(o) and not sheet_metal._is_unfold(o)]
            if not sms:
                continue
            seen.add(doc.Name)
            part = [o for o in sms if not any(sheet_metal._is_sm(x) and not sheet_metal._is_unfold(x)
                                               for x in o.InList)][-1]
            try:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(doc.Name, part.Name)
                fn = _safe(f"{title} - flat pattern") + ".dxf"
                path = sheet_metal.save_flat_dxf(os.path.join(folder, fn))
                if path:
                    out.append((fn, None, 1, "", title))
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: no flat pattern for {title} ({e})\n")
            finally:
                Gui.Selection.clearSelection()
    return out


# ------------------------------------------------------------ STEP

def write_step(asm, targets, folder):
    import Import
    os.makedirs(folder, exist_ok=True)
    written = []
    jobs = [([asm], f"{asm.Label} - Assembly")] + [(objs, title) for objs, title in targets]
    for objs, title in jobs:
        fn = _safe(title) + ".step"
        try:
            Import.export(objs, os.path.join(folder, fn))
            written.append(fn)
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: no STEP for {title} ({e})\n")
    return written


# ------------------------------------------------------------ lists

def write_lists(asm, folder):
    from mechflow_gui import bom
    data = bom.rows(asm)
    with open(os.path.join(folder, "BOM.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Item", "Part number", "Description", "Qty"])
        for i, (n, d, q) in enumerate(data, start=1):
            w.writerow([i, n, d, q])
    files = ["BOM.csv"]
    cut = []
    try:
        from mechflow_gui import weldments
        docs = {asm.Document.Name: asm.Document}
        for d in asm.Document.getDependentDocuments():
            docs[d.Name] = d
        for d in docs.values():
            for desc, length, a1, a2, qty in weldments.cut_items(d):
                cut.append((d.Label, desc, length, a1, a2, qty))
    except Exception:
        cut = []
    if cut:
        with open(os.path.join(folder, "Cut list.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Part", "Description", "Length (mm)", "Angle 1", "Angle 2", "Qty"])
            for row in cut:
                w.writerow(row)
        files.append("Cut list.csv")
    return files, len(data)


# ------------------------------------------------------------ the pack

def _clear_old(folder):
    """Remake an earlier pack cleanly: its own files go (only in a folder
    that has a pack's Contents.txt, and only PDF/STEP/DXF in its sub-folders)."""
    if not os.path.exists(os.path.join(folder, "Contents.txt")):
        return
    for sub, ext in (("Drawings", ".pdf"), ("STEP", ".step"), ("DXF", ".dxf")):
        d = os.path.join(folder, sub)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.lower().endswith(ext):
                    try:
                        os.remove(os.path.join(d, fn))
                    except OSError:
                        pass


def _reuse(doc, label, n, total):
    """A sheet already in doc with this name, renumbered n of total."""
    from mechflow_gui import drawing_pack
    for o in doc.Objects:
        if o.TypeId == "TechDraw::DrawPage" and o.Label == label:
            try:
                drawing_pack._fill(o.Template, {"sheet_number": f"{n}/{total}"})
            except Exception:
                pass
            return o
    return None


def _remove_page(page):
    """Delete a sheet: annotations, then views, then the sheet and its
    template (deleting a sheet before its views crashes FreeCAD)."""
    doc = page.Document
    views = list(page.Views)
    order = sorted(views, key=lambda v: 0 if ("Dim" in v.TypeId or "Balloon" in v.TypeId) else 1)
    for v in order:
        try:
            doc.removeObject(v.Name)
        except Exception:
            pass
    tmpl = page.Template
    doc.removeObject(page.Name)
    if tmpl is not None:
        try:
            doc.removeObject(tmpl.Name)
        except Exception:
            pass


def make(asm, folder, drawings=True, step=True, dxf=True, zip_it=True, sheet="A2 (ISO) - Landscape",
         progress=None):
    """Write the supplier pack into folder. Returns a summary dict."""
    from mechflow_gui import drawing_pack
    done = {"folder": folder}

    def say(text):
        if progress:
            progress(text)
    os.makedirs(folder, exist_ok=True)
    _clear_old(folder)
    say("Loading the parts...")
    drawing_pack.load_parts(asm)
    targets = drawing_pack.part_targets(asm)
    if drawings:
        # sheets made before (by a pack or Make Drawing) are used again - their
        # views follow the model, and any edits made to them are kept
        say("Drawing the assembly...")
        total = 2 + len(targets)
        doc = asm.Document
        pages = [_reuse(doc, f"{asm.Label} - Assembly", 1, total) or
                 drawing_pack.assembly_sheet(asm, sheet, 1, total)]
        say("Drawing the exploded view...")
        old = _reuse(doc, f"{asm.Label} - Exploded View", 2, total)
        if old is not None:
            _remove_page(old)              # its parts are made again, so it is too
        pages.append(drawing_pack.assembly_sheet(asm, sheet, 2, total, exploded=True))
        for n, (objs, title) in enumerate(targets, start=3):
            say(f"Drawing {title}...")
            try:
                pages.append(_reuse(objs[0].Document, f"{title} - Part", n, total) or
                             drawing_pack.part_sheet(objs, drawing_pack.AUTO, n, total, title=title))
            except Exception as e:
                App.Console.PrintWarning(f"MechFlow: no drawing for {title} ({e})\n")
        say("Saving the drawings as PDF...")
        done["pdf"] = [os.path.basename(p) for p in
                       drawing_pack.save_all_pdf(pages, os.path.join(folder, "Drawings"))]
        done["pages"] = pages
    if step:
        say("Saving STEP files...")
        done["step"] = write_step(asm, targets, os.path.join(folder, "STEP"))
    if dxf:
        say("Laying out flat plates...")
        dxf_dir = os.path.join(folder, "DXF")
        done["dxf"] = write_flats(targets, dxf_dir) + write_sheet_metal(targets, dxf_dir)
    say("Writing the BOM...")
    done["lists"], done["bom_rows"] = write_lists(asm, folder)
    _contents(asm, folder, done)
    if zip_it:
        say("Zipping...")
        z = folder.rstrip("/\\") + ".zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(folder):
                for fn in files:
                    full = os.path.join(root, fn)
                    zf.write(full, os.path.relpath(full, os.path.dirname(folder)))
        done["zip"] = z
    return done


def _contents(asm, folder, done):
    lines = [f"{asm.Label} - supplier pack", f"Made {datetime.date.today():%d/%m/%Y} with MechFlow", ""]
    if done.get("pdf"):
        lines += ["Drawings (PDF):"] + [f"  {p}" for p in done["pdf"]] + [""]
    if done.get("step"):
        lines += ["3D models (STEP):"] + [f"  {p}" for p in done["step"]] + [""]
    if done.get("dxf") is not None:
        lines.append("Flat profiles for cutting (DXF, mm, 1:1):")
        for fn, t, qty, size, _part in done["dxf"]:
            extra = f"   {t:g} mm plate, {size} mm, qty {qty}" if t else ""
            lines.append(f"  {fn}{extra}")
        if not done["dxf"]:
            lines.append("  (no flat plates found)")
        if any("panel" in d[0] for d in done["dxf"]):
            lines += ["  Panels are the walls of a plate-built part, each at its outside size:",
                      "  where walls meet they overlap by the plate thickness - set the corner",
                      "  joints (and any weld prep) before cutting."]
        lines.append("")
    lines += [f"Lists: {', '.join(done.get('lists', []))}", "",
              "Bought-in items (flanges, gaskets, pipe, fasteners) are in the BOM;",
              "they have no drawings or DXFs."]
    open(os.path.join(folder, "Contents.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")


# ------------------------------------------------------------ command

class PackDialog(QtWidgets.QDialog):
    def __init__(self, asm):
        super().__init__(Gui.getMainWindow())
        from mechflow_gui import drawings
        self.setWindowTitle("Supplier Pack")
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(
            f"Everything a fabricator needs for <b>{asm.Label}</b>, in one folder and a zip."))
        row = QtWidgets.QHBoxLayout()
        doc = asm.Document
        base = os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
        self.folder = QtWidgets.QLineEdit(os.path.normpath(
            os.path.join(base, f"{_safe(asm.Label)} - Supplier Pack")))
        row.addWidget(self.folder, 1)
        b = QtWidgets.QPushButton("Browse...")
        b.clicked.connect(self._browse)
        row.addWidget(b)
        lay.addLayout(row)
        self.pdf = QtWidgets.QCheckBox("Drawings as PDF: assembly, exploded view and each part")
        self.step = QtWidgets.QCheckBox("STEP of the assembly and each part")
        self.dxf = QtWidgets.QCheckBox("DXF flat profiles of plates and sheet metal (for plasma / laser)")
        self.zip = QtWidgets.QCheckBox("Zip it, ready to email")
        for c in (self.pdf, self.step, self.dxf, self.zip):
            c.setChecked(True)
            lay.addWidget(c)
        f = QtWidgets.QFormLayout()
        self.sheet = QtWidgets.QComboBox()
        self.sheet.addItems(list(drawings.SHEETS))
        self.sheet.setCurrentText("A2 (ISO) - Landscape")
        f.addRow("Assembly sheets", self.sheet)
        lay.addLayout(f)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.button(QtWidgets.QDialogButtonBox.Ok).setText("Make Pack")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Supplier pack folder",
                                                       os.path.dirname(self.folder.text()))
        if d:
            self.folder.setText(d)


def supplier_pack(asm=None):
    from mechflow_gui import assembly, drawings
    asm = asm or assembly.active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Supplier Pack", "Open an assembly first.")
        return None
    dlg = PackDialog(asm)
    if not dlg.exec():
        return None
    prog = QtWidgets.QProgressDialog("Supplier Pack", None, 0, 0, Gui.getMainWindow())
    prog.setWindowTitle("Supplier Pack")
    prog.setMinimumDuration(0)
    prog.show()

    def progress(text):
        prog.setLabelText(text)
        QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        asm.Document.openTransaction("Supplier Pack")
        done = make(asm, os.path.normpath(dlg.folder.text()), dlg.pdf.isChecked(), dlg.step.isChecked(),
                    dlg.dxf.isChecked(), dlg.zip.isChecked(), dlg.sheet.currentText(), progress)
        asm.Document.commitTransaction()
    except Exception as e:
        asm.Document.abortTransaction()
        QtWidgets.QApplication.restoreOverrideCursor()
        prog.close()
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Supplier Pack", f"The pack couldn't be made: {e}")
        return None
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
        prog.close()
    msg = [f"Saved in {done['folder']}", ""]
    if "pdf" in done:
        msg.append(f"{len(done['pdf'])} drawings (PDF)")
    if "step" in done:
        msg.append(f"{len(done['step'])} STEP files")
    if "dxf" in done:
        msg.append(f"{len(done['dxf'])} DXF flat profiles")
    msg.append(f"BOM ({done['bom_rows']} lines)")
    if done.get("zip"):
        msg += ["", f"Zipped: {os.path.basename(done['zip'])}"]
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Supplier Pack", "\n".join(msg))
    if done.get("pages"):
        drawings._open(done["pages"][1])
    return done
