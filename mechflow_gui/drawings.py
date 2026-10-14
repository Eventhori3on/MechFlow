# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style drawings on FreeCAD's TechDraw.

- Make Drawing from Part: pick a sheet size, and MechFlow makes a drawing
  sheet with a standard 3 view (Front, Top, Right) plus an isometric view at
  a standard scale that fits the sheet, and fills in the title block (part
  name, material, scale, date, author).
- First-angle projection for ISO sheets and third-angle for ANSI, as
  SOLIDWORKS does for those standards; you can change it in the dialog.
- Standard 3 View adds the views to the open drawing; Sheet Format changes the
  sheet; Save as PDF exports it.

The drawing lives in the part's FreeCAD document (FreeCAD keeps them
together, rather than in a separate .SLDDRW-style file).
"""

import datetime
import os

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"

# name: (template file under TechDraw/Templates, standard)
SHEETS = {
    "A4 (ISO) - Landscape": ("ISO/A4_Landscape_ISO5457_advanced.svg", "ISO"),
    "A4 (ISO) - Portrait": ("ISO/A4_Portrait_ISO5457_advanced.svg", "ISO"),
    "A3 (ISO) - Landscape": ("ISO/A3_Landscape_ISO5457_advanced.svg", "ISO"),
    "A2 (ISO) - Landscape": ("ISO/A2_Landscape_ISO5457_advanced.svg", "ISO"),
    "A1 (ISO) - Landscape": ("ISO/A1_Landscape_ISO5457_advanced.svg", "ISO"),
    "A0 (ISO) - Landscape": ("ISO/A0_Landscape_ISO5457_advanced.svg", "ISO"),
    "A (ANSI) - Landscape": ("ASME/ANSIA_Landscape.svg", "ANSI"),
    "B (ANSI) - Landscape": ("ASME/ANSIB_Landscape.svg", "ANSI"),
    "C (ANSI) - Landscape": ("ASME/ANSIC_Landscape.svg", "ANSI"),
    "D (ANSI) - Landscape": ("ASME/ANSID_Landscape.svg", "ANSI"),
}
DEFAULT_SHEET = "A3 (ISO) - Landscape"
FIRST, THIRD = "First angle", "Third angle"

# Standard drawing scales (sheet : part), largest first.
SCALES = [10, 5, 2, 1, 1 / 2, 1 / 5, 1 / 10, 1 / 20, 1 / 50, 1 / 100, 1 / 200]


def template_path(sheet):
    rel = SHEETS.get(sheet, SHEETS[DEFAULT_SHEET])[0]
    return os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates", *rel.split("/"))


def scale_text(s):
    if s >= 1:
        return f"{s:g}:1"
    return f"1:{1 / s:g}"


def _load_techdraw():
    for mod in ("TechDraw", "TechDrawGui"):
        try:
            __import__(mod)
        except ImportError:
            pass


# ------------------------------------------------------------ what to draw

def _drawable(o):
    try:
        if o.TypeId == "PartDesign::Body" or (o.isDerivedFrom("Part::Feature")
                                               and not o.isDerivedFrom("PartDesign::Feature")):
            return not o.Shape.isNull() and bool(o.Shape.Solids)
        if o.TypeId in ("Assembly::AssemblyObject", "App::Part"):
            return True
    except Exception:
        pass
    return False


def source_objects():
    """What to draw: the selection, else the active part, else the only part."""
    sel = [o for o in Gui.Selection.getSelection() if _drawable(o)]
    for o in Gui.Selection.getSelection():
        if not sel:
            try:
                b = o.getParentGeoFeatureGroup()
                if b is not None and _drawable(b):
                    sel = [b]
            except Exception:
                pass
    if sel:
        return sel
    try:
        b = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
        if b is not None and _drawable(b):
            return [b]
    except Exception:
        pass
    doc = App.ActiveDocument
    if doc is None:
        return []
    found = [o for o in doc.Objects if _drawable(o) and not o.InList]
    return found[:1] if len(found) == 1 else found


def _bbox(objs):
    """Bounding box of the solids (a Part's origin planes don't count)."""
    import Part
    box = None
    for o in objs:
        try:
            sh = Part.getShape(o)
            solids = sh.Solids
            bb = Part.makeCompound(solids).BoundBox if solids else sh.BoundBox
        except Exception:
            try:
                bb = o.Shape.BoundBox
            except Exception:
                continue
        box = bb if box is None else box.united(bb)
    return box


def _title_of(objs):
    o = objs[0]
    label = o.Label
    if label.lower().startswith("body") and o.Document.Label:
        label = o.Document.Label
    return label


# ------------------------------------------------------------ layout

def _sheet_area(template):
    W = float(getattr(template.Width, "Value", template.Width))
    H = float(getattr(template.Height, "Value", template.Height))
    # Margins and the title block in the bottom right (ISO 5457 / ANSI).
    return W, H, 20.0, 10.0, min(185.0, W * 0.45), 60.0


DIM_ROOM = 25.0      # space left of / under the views for dimensions


def _areas(template, with_iso):
    W, H, left, margin, tb_w, tb_h = _sheet_area(template)
    full_w = (W - left - margin) * (0.62 if with_iso else 0.9)
    return {"W": W, "H": H, "left": left, "margin": margin, "tb_w": tb_w, "tb_h": tb_h,
            "full_w": full_w, "full_h": H - 2 * margin,
            "above_h": H - 2 * margin - tb_h - 5,
            "left_w": min(full_w, W - left - margin - tb_w - 5)}


def _block(bb, scale, gap=15.0):
    sx, sy, sz = bb.XLength * scale, bb.YLength * scale, bb.ZLength * scale
    return sy + gap + sx + DIM_ROOM, sz + gap + sy + DIM_ROOM


def fit_mode(bb, scale, template, with_iso=True):
    """'above' (clear of the title block, full width), 'left' (beside it,
    full height) or None if the views don't fit at this scale."""
    a = _areas(template, with_iso)
    bw, bh = _block(bb, scale)
    if bw <= a["full_w"] and bh <= a["above_h"]:
        return "above"
    if bw <= a["left_w"] and bh <= a["full_h"]:
        return "left"
    return None


def pick_scale(objs, template, with_iso=True):
    bb = _bbox(objs)
    if bb is None:
        return 1.0
    for s in SCALES:
        if fit_mode(bb, s, template, with_iso):
            return s
    return SCALES[-1]


def sheet_fill(objs, template, scale, with_iso=True):
    """How much of the usable height the views take (0..1)."""
    bb = _bbox(objs)
    a = _areas(template, with_iso)
    bw = (bb.XLength + bb.YLength) * scale          # the views themselves
    bh = (bb.ZLength + bb.YLength) * scale
    return max(bw / a["full_w"], bh / a["full_h"])


def _place(page, template, group, iso, objs, scale, projection):
    """The 3 views clear of the title block (above it, or beside it), with
    room for dimensions, and the isometric top right."""
    bb = _bbox(objs)
    a = _areas(template, iso is not None)
    gap = 15.0                                  # FreeCAD's default view spacing
    sx, sy, sz = bb.XLength * scale, bb.YLength * scale, bb.ZLength * scale
    block_w, block_h = sy + gap + sx, sz + gap + sy
    mode = fit_mode(bb, scale, template, iso is not None) or "left"
    if mode == "above":
        bl = a["left"] + DIM_ROOM + max(0.0, (a["full_w"] - block_w - DIM_ROOM) / 2)
        floor = a["margin"] + a["tb_h"] + 5 + DIM_ROOM
        bb_y = floor + max(0.0, (a["above_h"] - block_h - DIM_ROOM) / 2)
    else:
        bl = a["left"] + DIM_ROOM + max(0.0, (a["left_w"] - block_w - DIM_ROOM) / 2)
        bb_y = a["margin"] + DIM_ROOM + max(0.0, (a["full_h"] - block_h - DIM_ROOM) / 2)
    if projection == FIRST:      # [Right][Front] / [Top] under the Front
        group.X = bl + sy + gap + sx / 2
        group.Y = bb_y + sy + gap + sz / 2
    else:                        # [Front][Right] / [Top] over the Front
        group.X = bl + sx / 2
        group.Y = bb_y + sz / 2
    if iso is not None:
        W, H, margin, tb_h = a["W"], a["H"], a["margin"], a["tb_h"]
        d = bb.DiagonalLength * scale * 0.8
        iso.X = W - margin - 10 - d / 2
        iso.Y = max(H - margin - 10 - d / 2, tb_h + margin + d / 2)


# ------------------------------------------------------------ title block

def _author():
    return App.ParamGet("User parameter:BaseApp/Preferences/Document").GetString("prefAuthor", "")


SAMPLE_VALUES = {
    "ST1", "ST2", "B. Hecate", "A. Nemesis", "RD", "AAA", "DN", "T",
    "Stainless steel Mat.No. 1.4301", "Approved 1", "Approved 2", "Checked By", "Code",
    "1234 Main St", "Company Name", "Drawing Title 1", "Drawing Title 2",
    "Drawing Title 3", "Drawn By", "Weight", "Drawing Number", "Rev", "Scale",
    "0 / 0", "Sheet n of m",
}


def _weight(objs):
    """Mass from MechFlow's material, for title blocks with a Weight box."""
    try:
        from mechflow_gui import material as mat
        _name, density = mat.get(objs[0])
        if not density:
            return ""
        vol = sum(o.Shape.Volume for o in objs)      # mm^3
        kg = vol * 1e-9 * density
        return f"{kg:.3f} kg" if kg >= 0.01 else f"{kg * 1000:.1f} g"
    except Exception:
        return ""


def fill_title_block(template, objs, scale, sheet_no=1, sheets=1):
    title = _title_of(objs) if objs else ""
    material = ""
    try:
        from mechflow_gui import material as mat
        material = mat.get(objs[0])[0] or ""
    except Exception:
        pass
    doc = objs[0].Document if objs else App.ActiveDocument
    today = datetime.date.today().strftime("%d/%m/%Y")
    values = {
        # ISO 5457 templates
        "title": title, "part_material": material, "scale": scale_text(scale),
        "creator": _author(), "date_of_issue": today,
        "sheet_number": f"{sheet_no}/{sheets}", "drawing_number": doc.Label if doc else "",
        # ANSI templates
        "DrawingTitle1": title, "DrawnBy": _author(), "Sheet": f"{sheet_no} OF {sheets}",
        "Weight": _weight(objs),
    }
    texts = dict(template.EditableTexts)
    # FreeCAD's sample entries - not real information, so clear them.
    for k, v in texts.items():
        if v.strip() in SAMPLE_VALUES:
            texts[k] = ""
    for k, v in values.items():
        if k in texts and v:
            texts[k] = v
    template.EditableTexts = texts


# ------------------------------------------------------------ building

def _page_name(doc):
    n = 1 + sum(1 for o in doc.Objects if o.TypeId == "TechDraw::DrawPage")
    return f"Drawing{n}"


def new_page(doc, sheet):
    _load_techdraw()
    label = _page_name(doc)
    page = doc.addObject("TechDraw::DrawPage", "Drawing")
    page.Label = label
    t = doc.addObject("TechDraw::DrawSVGTemplate", "Template")
    t.Template = template_path(sheet)
    page.Template = t
    return page


def add_standard_views(page, objs, projection=FIRST, with_iso=True, scale=None):
    """Front / Top / Right (and an isometric) of objs on page."""
    doc = page.Document
    t = page.Template
    scale = scale or pick_scale(objs, t, with_iso)
    g = doc.addObject("TechDraw::DrawProjGroup", "ProjGroup")
    page.addView(g)
    g.Source = objs
    g.ProjectionType = projection
    # Scale first: the group spaces its views out as they're added, and
    # spacing worked out at 1:1 isn't redone when the scale changes later
    # (a 1:20 drawing had its top and side views 2 m off the sheet).
    g.ScaleType = "Custom"
    g.Scale = scale
    for v in ("Front", "Top", "Right"):
        g.addProjection(v)
    iso = None
    if with_iso:
        iso = doc.addObject("TechDraw::DrawViewPart", "Isometric")
        page.addView(iso)
        iso.Label = "Isometric"
        iso.Source = objs
        iso.Direction = App.Vector(1, -1, 1)
        iso.XDirection = App.Vector(1, 1, 0)
        iso.ScaleType = "Custom"
        iso.Scale = scale
    _place(page, t, g, iso, objs, scale, projection)
    page.Scale = scale
    fill_title_block(t, objs, scale)
    doc.recompute()
    # and once more so the group re-spaces its views from their real sizes
    for item in list(getattr(g, "Views", [])) + [g]:
        item.touch()
    doc.recompute()
    return g, iso, scale


def _open(page):
    # opening a sheet makes FreeCAD switch to the TechDraw workbench; stay in
    # MechFlow (its Drawing tab has the drawing tools)
    try:
        wb = Gui.activeWorkbench().name()
    except Exception:
        wb = None
    try:
        vo = page.ViewObject
        if hasattr(vo, "show"):
            vo.show()
        vo.doubleClicked()
    except Exception:
        try:
            Gui.ActiveDocument.setEdit(page.Name)
        except Exception:
            pass
    if wb == "MechFlowWorkbench":
        def back():
            try:
                if Gui.activeWorkbench().name() != wb:
                    Gui.activateWorkbench(wb)
            except Exception:
                pass
        back()
        QtCore.QTimer.singleShot(0, back)


# ------------------------------------------------------------ dialogs

class SheetDialog(QtWidgets.QDialog):
    def __init__(self, title="Sheet Format/Size", parent=None, ask_views=True):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle(title)
        p = App.ParamGet(PARAMS)
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("Standard sheet size:"))
        self.list = QtWidgets.QListWidget()
        self.list.addItems(list(SHEETS))
        last = p.GetString("DrawingSheet", DEFAULT_SHEET)
        items = self.list.findItems(last if last in SHEETS else DEFAULT_SHEET, _match())
        self.list.setCurrentItem(items[0] if items else self.list.item(0))
        self.list.currentTextChanged.connect(self._sheet_changed)
        lay.addWidget(self.list)
        form = QtWidgets.QFormLayout()
        self.proj = QtWidgets.QComboBox()
        self.proj.addItems([FIRST, THIRD])
        form.addRow("Projection", self.proj)
        self.iso = QtWidgets.QCheckBox("Add an isometric view")
        self.iso.setChecked(p.GetBool("DrawingIso", True))
        if ask_views:
            form.addRow("", self.iso)
        else:
            self.iso.hide()
            self.proj.setEnabled(False)
        lay.addLayout(form)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._sheet_changed(self.list.currentItem().text())
        saved = p.GetString("DrawingProjection", "")
        if saved in (FIRST, THIRD):
            self.proj.setCurrentText(saved)

    def _sheet_changed(self, text):
        std = SHEETS.get(text, SHEETS[DEFAULT_SHEET])[1]
        self.proj.setCurrentText(FIRST if std == "ISO" else THIRD)

    def values(self):
        sheet = self.list.currentItem().text()
        p = App.ParamGet(PARAMS)
        p.SetString("DrawingSheet", sheet)
        p.SetString("DrawingProjection", self.proj.currentText())
        p.SetBool("DrawingIso", self.iso.isChecked())
        return sheet, self.proj.currentText(), self.iso.isChecked()


def _match():
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore
    return QtCore.Qt.MatchExactly


# ------------------------------------------------------------ commands

def active_page():
    """The drawing sheet that's open (or selected)."""
    for o in Gui.Selection.getSelection():
        if o.TypeId == "TechDraw::DrawPage":
            return o
        for p in getattr(o, "InList", []):
            if p.TypeId == "TechDraw::DrawPage":
                return p
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi is not None else None
        title = sub.windowTitle() if sub is not None else ""
    except Exception:
        title = ""
    doc = App.ActiveDocument
    if doc is not None and title:
        for o in doc.Objects:
            if o.TypeId == "TechDraw::DrawPage" and o.Label and o.Label in title:
                return o
    return None


def _projection():
    proj = App.ParamGet(PARAMS).GetString("DrawingProjection", FIRST)
    return proj if proj in (FIRST, THIRD) else FIRST


def _assembly_in(objs):
    for o in objs:
        if o.TypeId == "Assembly::AssemblyObject":
            return o
    try:
        from mechflow_gui import assembly
        if not objs or all(o.TypeId == "Assembly::AssemblyObject" for o in objs):
            return assembly.active_assembly()
    except Exception:
        pass
    return None


def make_drawing():
    """Make Drawing from Part / Assembly (SOLIDWORKS: File > Make Drawing
    from Part). An assembly gets the drawing pack: BOM, balloons and a sheet
    per part."""
    objs = source_objects()
    asm = _assembly_in(objs)
    if asm is not None:
        from mechflow_gui import drawing_pack
        pages = drawing_pack.make_drawing_from_assembly(asm)
        return pages[0] if pages else None
    if not objs:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Make Drawing",
            "Open or select a part (body) first.")
        return None
    dlg = SheetDialog()
    if not dlg.exec():
        return None
    sheet, projection, with_iso = dlg.values()
    doc = objs[0].Document
    doc.openTransaction("Make Drawing")
    try:
        page = new_page(doc, sheet)
        g, _iso, scale = add_standard_views(page, objs, projection, with_iso)
        doc.commitTransaction()
    except Exception as e:
        doc.abortTransaction()
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Make Drawing",
                                      f"The drawing couldn't be made:\n{e}")
        return None
    _open(page)
    if App.ParamGet(PARAMS).GetBool("DrawingAutoDims", True):
        try:
            from mechflow_gui import drawing_pack
            doc.openTransaction("Dimensions")
            wait_for_views(page)
            drawing_pack.decorate_part_page(page, g, scale)
            doc.commitTransaction()
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: automatic dimensions skipped ({e})\n")
    return page


def standard_3_view():
    page = active_page()
    if page is None:
        return make_drawing()
    objs = source_objects()
    if not objs:
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Standard 3 View",
            "Select the part to draw in the tree, then click Standard 3 View.")
        return None
    doc = page.Document
    doc.openTransaction("Standard 3 View")
    proj = App.ParamGet(PARAMS).GetString("DrawingProjection", FIRST)
    add_standard_views(page, objs, proj if proj in (FIRST, THIRD) else FIRST, True)
    doc.commitTransaction()
    return page


def sheet_format():
    page = active_page()
    if page is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Sheet Format",
                                          "Open a drawing first.")
        return
    dlg = SheetDialog("Sheet Format/Size", ask_views=False)
    if not dlg.exec():
        return
    sheet = dlg.values()[0]
    doc = page.Document
    doc.openTransaction("Sheet Format")
    old = dict(page.Template.EditableTexts)
    page.Template.Template = template_path(sheet)
    texts = dict(page.Template.EditableTexts)
    for k, v in old.items():           # keep what was filled in
        if k in texts and v:
            texts[k] = v
    page.Template.EditableTexts = texts
    doc.commitTransaction()
    doc.recompute()


def _view_state(page):
    out = []
    for v in page.Views:
        for x in [v] + list(getattr(v, "Views", [])):
            if hasattr(x, "getVisibleEdges"):
                try:
                    out.append((x.Name, len(x.getVisibleEdges()), round(float(x.X), 3), round(float(x.Y), 3)))
                except Exception:
                    out.append((x.Name, 0, 0, 0))
    return out


def wait_for_views(page, timeout=90.0):
    """TechDraw works out hidden lines in the background, so a big model's
    views can still be blank (or not yet spaced out) for a few seconds after
    they're made. Wait until every view has its lines and stops changing,
    so a PDF / DXF saved straight away isn't missing views."""
    import time
    t0 = time.time()
    last, stable = None, 0
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        while time.time() - t0 < timeout:
            QtWidgets.QApplication.processEvents()
            st = _view_state(page)
            if st and all(n > 0 for _name, n, _x, _y in st) and st == last:
                stable += 1
                if stable >= 4:
                    break
            else:
                stable = 0
            last = st
            time.sleep(0.25)
        page.Document.recompute()
        QtWidgets.QApplication.processEvents()
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()


def save_pdf():
    page = active_page()
    if page is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Save as PDF",
                                          "Open a drawing first.")
        return
    doc = page.Document
    start = os.path.join(os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~"),
                         f"{doc.Label}-{page.Label}.pdf")
    path, _ = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Save Drawing as PDF",
                                                    start, "PDF (*.pdf)")
    if path:
        import TechDrawGui
        wait_for_views(page)
        # The FreeCAD theme tints the sheet grey on screen; print it white.
        cols = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Colors")
        had = cols.GetUnsigned("PageColor", 0)
        cols.SetUnsigned("PageColor", 0xFFFFFFFF)
        try:
            TechDrawGui.exportPageAsPdf(page, path)
        finally:
            if had:
                cols.SetUnsigned("PageColor", had)
            else:
                cols.RemUnsigned("PageColor")
