import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
# Drawing sheet tools: the title block fits its boxes and can be restyled /
# its fields moved onto the sheet; text boxes (Ctrl+wheel, double-click);
# right-click menu on the sheet; projected views drag along their line,
# break and restore alignment (dimensions follow), spacing; a client's DXF /
# SVG / picture sheet with typeable boxes; Save Part As with part numbers.
from h import *
import json, shutil
from PySide6 import QtGui, QtTest
V = App.Vector
S = {}
D = OUT + "sheet-files/"
shutil.rmtree(D, ignore_errors=True)
os.makedirs(D, exist_ok=True)


KEEP = []


def gv_of(page):
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    subs = mdi.subWindowList()
    KEEP[:] = [subs]                    # a child's handle dies with its parent's
    for sub in subs:
        if page.Label in sub.windowTitle():
            if mdi.activeSubWindow() is not sub:
                mdi.setActiveSubWindow(sub)
                QtWidgets.QApplication.processEvents()
            for gv in sub.findChildren(QtWidgets.QGraphicsView):
                if "QGVPage" in gv.metaObject().className():
                    return gv


def scene_pt(gv, x, y):
    from mechflow_gui import sheet_tools
    r = sheet_tools.rez()
    return gv.mapFromScene(QtCore.QPointF(x * r, -y * r))


def edge_point(v, px, py):
    """A point to grab view v by: just left of its outline (page mm) - on an
    edge would pick the edge, under it is a dimension."""
    hx = max(max(abs(e.BoundBox.XMin), abs(e.BoundBox.XMax)) for e in v.getVisibleEdges())
    return px - hx - 2.0, py


def drag(gv, start, dx_mm, dy_mm, mods=QtCore.Qt.KeyboardModifier.NoModifier):
    vp = gv.viewport()
    tr = gv.transform().m11()
    from mechflow_gui import sheet_tools
    r = sheet_tools.rez()
    QtTest.QTest.mousePress(vp, QtCore.Qt.LeftButton, mods, start)
    q = start
    for k in range(1, 13):
        q = start + QtCore.QPoint(int(dx_mm * r * tr * k / 12), int(-dy_mm * r * tr * k / 12))
        ev = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, QtCore.QPointF(q),
                               QtCore.QPointF(vp.mapToGlobal(q)), QtCore.Qt.NoButton,
                               QtCore.Qt.LeftButton, mods)
        QtWidgets.QApplication.sendEvent(vp, ev)
        QtWidgets.QApplication.processEvents()
    QtTest.QTest.mouseRelease(vp, QtCore.Qt.LeftButton, mods, q)
    QtWidgets.QApplication.processEvents()


def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("SheetTest")
    S["doc"] = doc
    b = doc.addObject("Part::Box", "Box")
    b.Length, b.Width, b.Height = 160, 80, 60
    b.Label = "Bracket support plate long name for the title block test 1234"
    doc.recompute()
    S["b"] = b
    from mechflow_gui import drawings
    drawings.SheetDialog.exec = lambda self: True
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow").SetString(
        "DrawingSheet", "A3 (ISO) - Landscape")
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow").SetBool("DrawingIso", False)
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetString(
        "prefAuthor", "Eventhori3on Waterman Engineering")
at(setup, 2000)


def make():
    from mechflow_gui import drawings
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(S["b"])
    S["page"] = drawings.make_drawing()
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    log("active right after Make Drawing:", mdi.activeSubWindow().windowTitle())
at(make, 1000)
at(lambda: log("active 1 s later:", Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().windowTitle()), 5000)


def fitted():
    from mechflow_gui import title_block as tb
    t = S["page"].Template
    svg = open(t.PageResult, encoding="utf-8").read()
    fl = {f["name"]: f for f in tb.fields(svg)}
    import xml.etree.ElementTree as ET
    segs = tb.segments(ET.fromstring(svg.encode()))
    texts = dict(t.EditableTexts)
    res = {}
    for k in ("title", "creator"):
        f = fl[k]
        w = tb.text_width(texts[k], f["family"], f["size"], f["bold"])
        room = tb.box_width(f, segs, list(fl.values()))
        res[k] = (round(f["size"], 2), round(w, 1), round(room, 1))
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    log("active window after Make Drawing:", mdi.activeSubWindow().windowTitle())
    log("title block:", texts["title"], "|", res)
    assert res["title"][0] < 5 and res["title"][1] <= res["title"][2] + 0.2
    assert res["creator"][1] <= res["creator"][2] + 0.2
    shot("sheet_made")
at(fitted, 500)


def views_free():
    g = [v for v in S["page"].Views if v.TypeId == "TechDraw::DrawProjGroup"][0]
    S["g"] = g
    pos = {str(v.Type): (round(float(v.X), 1), round(float(v.Y), 1)) for v in g.Views}
    log("group AutoDistribute", g.AutoDistribute, "items", pos)
    assert not g.AutoDistribute and pos["Top"][0] == 0 and pos["Right"][1] == 0
at(views_free, 300)


def drag_top():
    g, page = S["g"], S["page"]
    gv = gv_of(page)
    top = [v for v in g.Views if str(v.Type) == "Top"][0]
    S["top"] = top
    x0, y0 = float(top.X), float(top.Y)
    px, py = edge_point(top, float(g.X) + x0, float(g.Y) + y0)
    from mechflow_gui import sheet_tools
    log("  top is", top.Name, "scale", float(g.Scale), "grab at", round(px, 1), round(py, 1),
        "views there", [v.Name for v in sheet_tools.views_at(gv, S["page"], scene_pt(gv, px, py), 0.0)],
        "edges x", [round(e.BoundBox.XMin, 1) for e in top.getVisibleEdges()])
    drag(gv, scene_pt(gv, px, py), 15, -20)
    S["top_moved"] = (round(float(top.X) - x0, 1), round(float(top.Y) - y0, 1))
    log("  selection after the drag:", [(o.Object.Name, o.SubElementNames) for o in Gui.Selection.getSelectionEx()])
    log("dragged the top view (+15, -20): moved", S["top_moved"])
    assert abs(S["top_moved"][0]) < 0.01 and S["top_moved"][1] < -10
at(drag_top, 800)


def drag_inside():
    """Grab the side view by its middle (FreeCAD would pick its face):
    MechFlow drags it - along its line from the front view."""
    g, page = S["g"], S["page"]
    gv = gv_of(page)
    right = [v for v in g.Views if str(v.Type) == "Right"][0]
    x0, y0 = float(right.X), float(right.Y)
    it = gv.itemAt(scene_pt(gv, float(g.X) + x0, float(g.Y) + y0))
    log("  under the middle of the side view:", type(it).__name__ if it else None,
        it.brush().style() if isinstance(it, QtWidgets.QGraphicsPathItem) else "")
    drag(gv, scene_pt(gv, float(g.X) + x0, float(g.Y) + y0), -12, 25)
    mv = (round(float(right.X) - x0, 1), round(float(right.Y) - y0, 1))
    log("dragged the side view by its middle (-12, +25): moved", mv,
        "| selected", [o.Name for o in Gui.Selection.getSelection()])
    assert mv[0] < -8 and abs(mv[1]) < 0.01
    # a click on a line still picks the line
    Gui.Selection.clearSelection()
    e = [ed for ed in right.getVisibleEdges() if abs(ed.Vertexes[0].Point.x -
                                                   ed.Vertexes[-1].Point.x) < 1e-6][0]
    px = float(g.X) + float(right.X) + e.Vertexes[0].Point.x
    py = float(g.Y) + float(right.Y)
    QtTest.QTest.mouseClick(gv.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                            scene_pt(gv, px, py))
    QtWidgets.QApplication.processEvents()
    sel = [(o.Object.Name, o.SubElementNames) for o in Gui.Selection.getSelectionEx()]
    log("click on a line of the side view picks:", sel)
    assert sel and any(n.startswith("Edge") for _o, ns in sel for n in ns)
    right.X = x0
    S["doc"].recompute()
at(drag_inside, 800)


def menu_top():
    """Right-click on the top view: MechFlow's choices and FreeCAD's."""
    g, gv, top = S["g"], gv_of(S["page"]), S["top"]
    px, py = edge_point(top, float(g.X) + float(top.X), float(g.Y) + float(top.Y))
    got = {}
    orig = QtWidgets.QMenu.exec

    def fake(self, *a, **k):
        got["acts"] = [a_.text() for a_ in self.actions() if a_.text()]
        return None
    from mechflow_gui import sheet_tools
    orig = sheet_tools.show_menu
    sheet_tools.show_menu = lambda menu, pos: fake(menu)
    try:
        pos = scene_pt(gv, px, py)
        ev = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, gv.viewport().mapToGlobal(pos))
        QtWidgets.QApplication.sendEvent(gv.viewport(), ev)
    finally:
        sheet_tools.show_menu = orig
    log("right-click on top view:", got.get("acts"))
    assert "Break Alignment" in got.get("acts", []) and "View Spacing..." in got["acts"]
    assert "Title Block..." in got["acts"]
at(menu_top, 400)


def dims_on(v):
    out = []
    for o in S["doc"].Objects:
        if o.TypeId == "TechDraw::DrawViewDimension":
            refs = o.References2D
            if any(r[0].Name == v.Name for r in refs):
                out.append(o)
    return out


def add_dim():
    top = S["top"]
    d = S["doc"].addObject("TechDraw::DrawViewDimension", "Dimension")
    d.Type = "DistanceX"
    e = [i for i, ed in enumerate(top.getVisibleEdges())
         if abs(ed.Vertexes[0].Point.y - ed.Vertexes[-1].Point.y) < 1e-6][0]
    d.References2D = [(top, f"Edge{e}")]
    S["page"].addView(d)
    S["doc"].recompute()
at(add_dim, 1000)


def break_top():
    from mechflow_gui import view_align
    top = S["top"]
    S["ndims"] = len(dims_on(top))
    label = top.Label
    new = view_align.break_alignment(top)
    S["free"] = new
    log("broke alignment:", new.Name, new.Label, new.TypeId, "dims moved over",
        len(dims_on(new)), "of", S["ndims"], "| group now", [str(v.Type) for v in S["g"].Views])
    assert new.Label == label and len(dims_on(new)) == S["ndims"] >= 1
    assert "Top" not in [str(v.Type) for v in S["g"].Views]
at(break_top, 1500)


def drag_free():
    new, gv = S["free"], gv_of(S["page"])
    x0, y0 = float(new.X), float(new.Y)
    drag(gv, scene_pt(gv, x0 + 5, y0 + 3), 30, -15)        # by its middle
    mv = (round(float(new.X) - x0, 1), round(float(new.Y) - y0, 1))
    log("dragged the free view (+30, -15): moved", mv)
    assert mv[0] > 15 and mv[1] < -5
    shot("sheet_free_view")
at(drag_free, 1000)


def restore():
    from mechflow_gui import view_align
    log("before default alignment: dims on the free view", len(dims_on(S["free"])),
        "all dims", [(o.Name, [r[0].Name for r in o.References2D]) for o in S["doc"].Objects
                     if o.TypeId == "TechDraw::DrawViewDimension"])
    it = view_align.default_alignment(S["free"])
    log("after: all dims", [(o.Name, [r[0].Name for r in o.References2D]) for o in S["doc"].Objects
                            if o.TypeId == "TechDraw::DrawViewDimension"])
    S["top"] = it
    log("default alignment:", it.TypeId, it.Label, str(it.Type), "X", round(float(it.X), 1),
        "dims back", len(dims_on(it)))
    assert it.TypeId == "TechDraw::DrawProjGroupItem" and abs(float(it.X)) < 0.01
    assert len(dims_on(it)) == S["ndims"]
at(restore, 1500)


def spacing():
    from mechflow_gui import view_align
    g = S["g"]
    right = [v for v in g.Views if str(v.Type) == "Right"][0]
    x0 = float(right.X)
    view_align.set_spacing(g, 40)
    log("spacing 40: right view X", round(x0, 1), "->", round(float(right.X), 1),
        "AutoDistribute", g.AutoDistribute)
    assert abs(float(right.X)) > abs(x0) + 10 and not g.AutoDistribute
at(spacing, 1500)


def half_scale():
    g = S["g"]
    right = [v for v in g.Views if str(v.Type) == "Right"][0]
    x0 = float(right.X)
    g.Scale = 0.5
    S["doc"].recompute()
    log("scale 1:2 - right view X", round(x0, 1), "->", round(float(right.X), 1))
    assert abs(float(right.X) - (-((abs(x0) - 40) * 0.5 + 40))) < 0.01
    g.Scale = 1.0
    S["doc"].recompute()
at(half_scale, 1500)


def tb_dialog():
    from mechflow_gui import title_block as tb
    page = S["page"]
    dlg = tb.TitleBlockDialog(page)
    rows = {r["name"]: r for r in dlg.rows}
    r = rows["creator"]
    r["font"].setEditText("DejaVu Serif")
    r["size"].setValue(3.0)
    r["bold"].setChecked(True)
    r["dx"].setValue(2.0)
    rows["supplementary_title_1"]["text"].setText("Client ref ABC-123")
    dlg.apply()
    svg = open(page.Template.PageResult, encoding="utf-8").read()
    import re
    tag = re.search(r'<text[^>]*editable="creator"[^>]*>', svg).group(0)
    log("creator after the dialog:", tag)
    assert "DejaVu Serif" in tag and "font-size:3.000px" in tag and "bold" in tag
    assert page.Template.EditableTexts["supplementary_title_1"] == "Client ref ABC-123"
    # move the drawing number onto the sheet, then back
    t = page.Template
    dn = t.EditableTexts["drawing_number"]
    note = tb.detach(t, "drawing_number")
    S["dn_note"] = note
    log("drawing number on the sheet:", note.Text, note.Font, round(float(note.TextSize), 2),
        round(float(note.X), 1), round(float(note.Y), 1), "| field now",
        repr(t.EditableTexts["drawing_number"]))
    assert list(note.Text) == [dn] and t.EditableTexts["drawing_number"] == ""
    assert 300 < float(note.X) < 380 and 10 < float(note.Y) < 40
    dlg.close()
    shot("sheet_titleblock")
at(tb_dialog, 800)


def tb_back():
    from mechflow_gui import title_block as tb
    t = S["page"].Template
    note = S["dn_note"]
    note.X = float(note.X) - 120
    S["doc"].recompute()
    tb.put_back(t, "drawing_number")
    log("put back:", repr(t.EditableTexts["drawing_number"]),
        "note gone", S["doc"].getObject(note.Name) is None if False else "TitleText" not in
        [o.Name for o in S["doc"].Objects])
    assert t.EditableTexts["drawing_number"] != ""
at(tb_back, 600)


def typed_in():
    """Typed straight into the drawing (as FreeCAD's own box does): refitted."""
    t = S["page"].Template
    e = dict(t.EditableTexts)
    e["document_type"] = "Fabrication drawing for the pipe support steelwork, phase two"
    t.EditableTexts = e
at(typed_in, 1200)


def typed_check():
    from mechflow_gui import title_block as tb
    t = S["page"].Template
    svg = open(t.PageResult, encoding="utf-8").read()
    f = [q for q in tb.fields(svg) if q["name"] == "document_type"][0]
    log("typed into the drawing - document type now", round(f["size"], 2), "mm")
    assert f["size"] < 4.5
at(typed_check, 300)


def text_box():
    from mechflow_gui import sheet_tools
    page = S["page"]
    n = sheet_tools.add_text_box(page, 80, 40, "NOTES: 1. Remove all burrs")
    S["note"] = n
    dlg = sheet_tools.TextBoxDialog(n, new=True)
    dlg.size.setValue(6.0)
    dlg.bold.setChecked(True)
    dlg.font.setEditText("DejaVu Sans")
    dlg.accept()
    log("text box:", list(n.Text), n.Font, n.TextSize, n.TextStyle)
    assert float(n.TextSize) == 6.0 and n.TextStyle == "Bold" and n.Font == "DejaVu Sans"
at(text_box, 800)


def wheel():
    n, gv = S["note"], gv_of(S["page"])
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(n)
    QtWidgets.QApplication.processEvents()
    pos = scene_pt(gv, float(n.X), float(n.Y))
    vp = gv.viewport()
    before = float(n.TextSize)
    for _ in range(2):
        ev = QtGui.QWheelEvent(QtCore.QPointF(pos), QtCore.QPointF(vp.mapToGlobal(pos)),
                               QtCore.QPoint(0, 0), QtCore.QPoint(0, 120), QtCore.Qt.NoButton,
                               QtCore.Qt.ControlModifier, QtCore.Qt.NoScrollPhase, False)
        QtWidgets.QApplication.sendEvent(vp, ev)
    log("Ctrl+wheel x2 on the text box:", before, "->", round(float(n.TextSize), 2))
    assert float(n.TextSize) > before * 1.15
    # double-click opens the text box editor
    from mechflow_gui import sheet_tools
    seen = {}
    orig = sheet_tools.TextBoxDialog.exec
    sheet_tools.TextBoxDialog.exec = lambda self: seen.setdefault("t", list(self.note.Text)) and 0
    S["orig_exec"] = orig
    QtTest.QTest.mouseDClick(vp, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, pos)
    S["seen"] = seen
at(wheel, 600)


def dbl_check():
    from mechflow_gui import sheet_tools
    sheet_tools.TextBoxDialog.exec = S["orig_exec"]
    log("double-click opened the text box editor with", S["seen"].get("t"))
    assert S["seen"].get("t") == list(S["note"].Text)
at(dbl_check, 300)


DXF = """0
SECTION
2
HEADER
9
$INSUNITS
70
4
0
ENDSEC
0
SECTION
2
BLOCKS
0
BLOCK
2
TB
10
0
20
0
0
LINE
10
0
20
0
11
180
21
0
0
LINE
10
0
20
12
11
180
21
12
0
LINE
10
0
20
24
11
180
21
24
0
LINE
10
0
20
36
11
180
21
36
0
LINE
10
60
20
0
11
60
21
36
0
LINE
10
120
20
0
11
120
21
36
0
TEXT
10
2
20
32
40
2.0
1
DRAWING No.
0
TEXT
10
62
20
32
40
2.0
1
CLIENT
0
TEXT
10
122
20
32
40
2.0
1
REV
0
ATTDEF
10
3
20
26
40
3.5
1
XX-000
2
DWG_NO
3
Drawing number
70
0
0
ENDBLK
0
ENDSEC
0
SECTION
2
ENTITIES
0
LWPOLYLINE
90
4
70
1
10
10
20
10
10
410
20
10
10
410
20
287
10
10
20
287
0
LWPOLYLINE
90
4
70
1
43
0.7
10
0
20
0
10
420
20
0
10
420
20
297
10
0
20
297
0
CIRCLE
10
30
20
270
40
8
0
ARC
10
30
20
270
40
12
50
0
51
90
0
MTEXT
10
20
20
280
40
4
71
1
1
ACME PROCESS LTD\\PPipework division
0
INSERT
2
TB
10
230
20
10
66
1
0
ATTRIB
10
233
20
36
40
3.5
1
P-1001
2
DWG_NO
70
0
0
SEQEND
0
TEXT
10
292
20
36
40
3.5
1
CLIENT NAME
0
TEXT
10
352
20
36
40
3.5
1
A
0
ENDSEC
0
EOF
"""


def client_dxf():
    from mechflow_gui import client_sheet
    p = D + "client.dxf"
    open(p, "w").write(DXF)
    items = client_sheet.read_dxf(p)
    texts = [(t["text"], t["tag"], t["editable"]) for t in items["texts"]]
    log("DXF:", len(items["lines"]), "lines,", texts)
    assert ("P-1001", "DWG_NO", True) in texts and len(items["lines"]) >= 10
    # tick the client name and the revision to type over too
    pick = {i for i, t in enumerate(items["texts"]) if t["editable"] or t["text"] in
            ("CLIENT NAME", "A")}
    svg = client_sheet.dxf_svg(items, None, "osifont", pick)
    path = client_sheet.apply_choice(svg, "ACME test sheet", S["page"], keep=True)
    t = S["page"].Template
    log("client sheet:", os.path.basename(path), float(t.Width), "x", float(t.Height),
        "fields", dict(t.EditableTexts))
    assert abs(float(t.Width) - 420) < 0.01 and "dwg_no" in t.EditableTexts
    assert t.EditableTexts["dwg_no"] == "P-1001" and "client_name" in t.EditableTexts
    e = dict(t.EditableTexts)
    e["client_name"] = "Waterman Engineering Ltd - North Sea platform upgrade"
    t.EditableTexts = e
    from mechflow_gui import drawings
    log("sheet formats now list it:", [k for k in drawings.all_sheets() if k.startswith("Client")])
    assert "Client: ACME test sheet" in drawings.all_sheets()
at(client_dxf, 1500)


def client_dxf_check():
    from mechflow_gui import title_block as tb
    t = S["page"].Template
    svg = open(t.PageResult, encoding="utf-8").read()
    f = [q for q in tb.fields(svg) if q["name"] == "client_name"][0]
    log("client name fitted to", round(f["size"], 2), "mm, was", round(3.5 / 0.72, 2))
    assert f["size"] < 3.5 / 0.72 - 0.3
    shot("sheet_client_dxf")
    from mechflow_gui import client_sheet
    pm = client_sheet.render_preview(svg, 900)
    pm.save(SHOTS + "client_dxf_render.png")
at(client_dxf_check, 800)


def client_svg_and_picture():
    from mechflow_gui import client_sheet
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="1123" height="794" viewBox="0 0 1123 794">'
           '<rect x="20" y="20" width="1083" height="754" fill="none" stroke="black" stroke-width="2"/>'
           '<text x="800" y="740" font-size="14">JOB No. 0000</text>'
           '<text x="40" y="60" font-size="20">LOGO</text></svg>')
    texts = client_sheet.svg_texts(svg)
    out = client_sheet.svg_sheet(client_sheet.svg_with_fields(svg, {0}), (420, 297))
    client_sheet.apply_choice(out, "SVG test sheet", S["page"], keep=False)
    t = S["page"].Template
    log("client SVG:", texts, "->", float(t.Width), "x", float(t.Height), dict(t.EditableTexts))
    assert "job_no_0000" in t.EditableTexts and abs(float(t.Width) - 420) < 0.01
    img = QtGui.QImage(400, 280, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor("white"))
    pa = QtGui.QPainter(img)
    pa.setPen(QtGui.QPen(QtGui.QColor("black"), 3))
    pa.drawRect(10, 10, 380, 260)
    pa.end()
    img.save(D + "border.png")
    pic = client_sheet.image_svg(D + "border.png", (297, 210))
    client_sheet.apply_choice(pic, "Picture sheet", S["page"], keep=False)
    log("picture sheet:", float(t.Width), "x", float(t.Height))
    assert abs(float(t.Width) - 297) < 0.01
at(client_svg_and_picture, 1500)


def save_parts():
    from mechflow_gui import scan_extras, bom
    doc = S["doc"]
    b2 = doc.addObject("Part::Cylinder", "Pin")
    doc.recompute()
    dlg = scan_extras.SavePartsDialog([S["b"], b2])
    dlg.prefix.setText("WE-")
    dlg.start.setValue(1001)
    dlg._number()
    dlg.table.item(1, 2).setText("Locating pin")
    dlg.folder.setText(D)
    dlg.fmt.setCurrentText("Both")
    names = [dlg.table.item(r, 3).text() for r in range(2)]
    rows = dlg.rows()
    paths = scan_extras.save_parts(rows, D, "Both", True)
    step = open([p for p in paths if p.endswith(".step") and "1002" in p][0],
                encoding="utf-8", errors="ignore").read()
    d2 = App.openDocument([p for p in paths if p.endswith(".FCStd") and "1001" in p][0])
    o = [x for x in d2.Objects if hasattr(x, "Shape")][0]
    log("saved:", [os.path.basename(p) for p in paths], "| file names", names,
        "| in the FCStd:", o.Label, o.PartNumber, "| STEP names it:", "WE-1002" in step,
        "| model:", S["b"].PartNumber, b2.PartNumber, b2.PartDescription,
        "| BOM:", bom._numbered(b2, "Pin", ""))
    assert names == ["WE-1001", "WE-1002"] and len(paths) == 4
    assert o.Label == "WE-1001" and o.PartNumber == "WE-1001" and "WE-1002" in step
    assert b2.PartNumber == "WE-1002" and bom._numbered(b2, "Pin", "")[0] == "WE-1002"
    App.closeDocument(d2.Name)
    App.setActiveDocument(doc.Name)
at(save_parts, 1500)


def reopen():
    doc = S["doc"]
    p = D + "SheetTest.FCStd"
    doc.saveAs(p)
    App.closeDocument(doc.Name)
    d = App.openDocument(p)
    S["doc"] = d
    page = [o for o in d.Objects if o.TypeId == "TechDraw::DrawPage"][0]
    t = page.Template
    from mechflow_gui import title_block as tb
    st = tb.settings_of(t)
    log("reopened: template", float(t.Width), "x", float(t.Height), "| source kept",
        os.path.exists(getattr(t, tb.SRC, "")), "| settings", sorted(st["fields"]))
    assert os.path.exists(getattr(t, tb.SRC, "")) and "creator" in st["fields"]
at(reopen, 3000)


def finish():
    App.closeDocument(S["doc"].Name)
    from mechflow_gui import client_sheet
    p = client_sheet.library().get("ACME test sheet")       # (not left in your formats)
    if p:
        os.remove(p)
at(finish, 500)
run()
