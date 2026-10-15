# SPDX-License-Identifier: LGPL-2.1-or-later
"""Working on the drawing sheet with the mouse, SOLIDWORKS style.

- Text Box: type a note, pick its font, size, bold / italic, colour and how
  wide it may get; it goes where you're looking (or where you right-clicked)
  and you drag it into place. Double-click a note to change it.
- Ctrl + mouse wheel over a selected note makes it bigger or smaller (over a
  picture - a scan view - it scales the picture).
- Right-click on the drawing: the MechFlow choices for what's under the mouse
  (Break / Default Alignment and View Spacing for projected views, Edit Text
  for notes, Title Block, Client Sheet, Add Text Box Here) above FreeCAD's
  own (frames, keep updated, export, print).
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

STYLES = ["Normal", "Bold", "Italic", "Bold-Italic"]


def _mw():
    return Gui.getMainWindow()


def rez():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Rez").GetFloat(
        "Resolution", 10.0) or 10.0


# ------------------------------------------------------------ where things are

def page_views(page):
    """[(view, page X, page Y)] for every view on the page, group items too."""
    out = []
    for v in page.Views:
        try:
            x, y = float(v.X), float(v.Y)
        except Exception:
            continue
        out.append((v, x, y))
        for c in getattr(v, "Views", []) or []:
            try:
                out.append((c, x + float(c.X), y + float(c.Y)))
            except Exception:
                pass
    return out


def page_of_view(gv):
    """The DrawPage shown in a TechDraw graphics view."""
    w = gv
    title = ""
    while w is not None:
        if isinstance(w, QtWidgets.QMdiSubWindow):
            title = w.windowTitle()
            break
        w = w.parentWidget()
    doc = App.ActiveDocument
    pages = []
    for d in ([doc] if doc else []) + [d for d in App.listDocuments().values() if d is not doc]:
        pages += [o for o in d.Objects if o.TypeId == "TechDraw::DrawPage"]
    for p in pages:
        if p.Label and p.Label in title and p.Document.Label in title:
            return p
    for p in pages:
        if p.Label and p.Label in title:
            return p
    return pages[0] if len(pages) == 1 else None


def to_page(gv, pos):
    """Viewport point -> page (x, y) in mm."""
    sp = gv.mapToScene(pos)
    r = rez()
    return sp.x() / r, -sp.y() / r


def _half_size(v):
    """Half width / height (mm on the sheet) of what view v shows."""
    t = v.TypeId
    if t in ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem", "TechDraw::DrawViewSection",
             "TechDraw::DrawViewDetail") or hasattr(v, "getVisibleEdges"):
        try:
            hx = hy = 0.0
            for e in v.getVisibleEdges():
                bb = e.BoundBox
                hx = max(hx, abs(bb.XMin), abs(bb.XMax))
                hy = max(hy, abs(bb.YMin), abs(bb.YMax))
            if hx or hy:
                return hx, hy
        except Exception:
            pass
    if t == "TechDraw::DrawViewAnnotation":
        from mechflow_gui import title_block
        size = float(v.TextSize) / title_block.metrics(v.Font)[0]   # capitals -> font size
        lines = list(v.Text) or [""]
        w = max(title_block.text_width(s_, v.Font, size, "Bold" in str(v.TextStyle))
                for s_ in lines)
        if float(v.MaxWidth) > 0:
            w = min(w, float(v.MaxWidth))
        return w / 2 + 1.0, len(lines) * size * float(v.LineSpace) / 200.0 + 1.0
    if t == "TechDraw::DrawViewImage":
        try:
            from mechflow_gui import scan_extras
            w, h = scan_extras._shown_size(v)
        except Exception:
            w, h = float(v.Width) * float(v.Scale), float(v.Height) * float(v.Scale)
        return w / 2, h / 2
    return None


def views_at(gv, page, pos, slack=4.0):
    """The drawing views under the mouse, smallest first (a projected view
    before its group). Worked out from where the views are on the sheet
    and how big they are - nothing is asked of the graphics items."""
    x, y = to_page(gv, pos)
    hits = []
    for v, vx, vy in page_views(page):
        if v.TypeId == "TechDraw::DrawProjGroup":
            continue
        hs = _half_size(v)
        if hs is None:
            continue
        hx, hy = hs
        if abs(x - vx) <= hx + slack and abs(y - vy) <= hy + slack:
            hits.append(((hx + slack) * (hy + slack), v))
    hits.sort(key=lambda h: h[0])
    found = [v for _a, v in hits]
    for v in list(found):
        if v.TypeId == "TechDraw::DrawProjGroupItem":
            g = next((p for p in v.InList if p.TypeId == "TechDraw::DrawProjGroup"), None)
            if g is not None and g not in found:
                found.append(g)
    return found


def _first(views, *types):
    for v in views:
        if v.TypeId in types:
            return v
    return None


# ------------------------------------------------------------ text box

class TextBoxDialog(QtWidgets.QDialog):
    """A note's text and look, changed live on the drawing."""

    def __init__(self, note, new=False, parent=None):
        super().__init__(parent or _mw())
        self.note, self.new = note, new
        self.setWindowTitle("Text Box")
        self.old = {k: getattr(note, k) for k in ("Text", "Font", "TextSize", "TextStyle",
                                                  "TextColor", "MaxWidth", "LineSpace")}
        lay = QtWidgets.QVBoxLayout(self)
        self.text = QtWidgets.QPlainTextEdit("\n".join(note.Text))
        self.text.setMinimumHeight(110)
        lay.addWidget(self.text)
        form = QtWidgets.QFormLayout()
        self.font = QtWidgets.QFontComboBox()
        self.font.setEditable(True)
        self.font.setCurrentFont(QtGui.QFont(note.Font))
        self.font.setEditText(note.Font)
        form.addRow("Font", self.font)
        row = QtWidgets.QHBoxLayout()
        self.size = QtWidgets.QDoubleSpinBox()
        self.size.setRange(0.5, 200.0)
        self.size.setDecimals(1)
        self.size.setSingleStep(0.5)
        self.size.setSuffix(" mm")
        self.size.setValue(float(note.TextSize))
        row.addWidget(self.size)
        self.bold = QtWidgets.QCheckBox("Bold")
        self.italic = QtWidgets.QCheckBox("Italic")
        st = str(note.TextStyle)
        self.bold.setChecked("Bold" in st)
        self.italic.setChecked("Italic" in st)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        self.colour = QtWidgets.QPushButton()
        self.colour.setFixedWidth(60)
        self._col = QtGui.QColor.fromRgbF(*tuple(note.TextColor)[:3])
        self._paint_colour()
        self.colour.clicked.connect(self._pick_colour)
        row.addWidget(QtWidgets.QLabel("Colour"))
        row.addWidget(self.colour)
        row.addStretch(1)
        form.addRow("Size", row)
        self.width = QtWidgets.QDoubleSpinBox()
        self.width.setRange(0.0, 2000.0)
        self.width.setDecimals(0)
        self.width.setSuffix(" mm")
        self.width.setSpecialValueText("no limit")
        self.width.setValue(max(0.0, float(note.MaxWidth)))
        self.width.setToolTip("Lines wrap at this width")
        form.addRow("Wrap at", self.width)
        self.space = QtWidgets.QSpinBox()
        self.space.setRange(50, 400)
        self.space.setSuffix(" %")
        self.space.setValue(int(note.LineSpace))
        form.addRow("Line spacing", self.space)
        lay.addLayout(form)
        hint = QtWidgets.QLabel("Drag the text on the drawing to move it. Ctrl + mouse wheel "
                                "over it (selected) makes it bigger or smaller.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                        QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for sig in (self.text.textChanged, self.font.currentTextChanged,
                    self.size.valueChanged, self.bold.toggled, self.italic.toggled,
                    self.width.valueChanged, self.space.valueChanged):
            sig.connect(self._live)

    def _paint_colour(self):
        self.colour.setStyleSheet(f"background:{self._col.name()}")

    def _pick_colour(self):
        c = QtWidgets.QColorDialog.getColor(self._col, self, "Text colour")
        if c.isValid():
            self._col = c
            self._paint_colour()
            self._live()

    def _live(self, *_a):
        n = self.note
        lines = self.text.toPlainText().split("\n")
        n.Text = lines if any(lines) else [""]
        n.Font = self.font.currentText().strip() or self.old["Font"]
        n.TextSize = self.size.value()
        n.TextStyle = STYLES[int(self.bold.isChecked()) + 2 * int(self.italic.isChecked())]
        n.TextColor = (self._col.redF(), self._col.greenF(), self._col.blueF())
        n.MaxWidth = self.width.value() if self.width.value() > 0 else -1.0
        n.LineSpace = self.space.value()
        n.Document.recompute()

    def reject(self):
        doc = self.note.Document
        if self.new:
            try:
                for p in self.note.InList:
                    if p.TypeId == "TechDraw::DrawPage":
                        p.removeView(self.note)
                doc.removeObject(self.note.Name)
            except Exception:
                pass
        else:
            for k, v in self.old.items():
                try:
                    setattr(self.note, k, v)
                except Exception:
                    pass
        doc.recompute()
        super().reject()

    def accept(self):
        self._live()
        super().accept()


def add_text_box(page, x=None, y=None, text=""):
    """A new note on page at (x, y) mm (the middle of the sheet if not given)."""
    doc = page.Document
    n = doc.addObject("TechDraw::DrawViewAnnotation", "TextBox")
    n.Label = "Text box"
    page.addView(n)
    n.Text = [text] if text else ["Text"]
    try:
        p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
        n.Font = p.GetString("TextBoxFont", n.Font) or n.Font
        n.TextSize = p.GetFloat("TextBoxSize", 0.0) or 5.0
    except Exception:
        pass
    t = page.Template
    if x is None:
        x = float(t.Width) / 2 if t else 150.0
        y = float(t.Height) / 2 if t else 100.0
    n.X, n.Y = x, y
    doc.recompute()
    return n


def edit_text_box(note, new=False):
    doc = note.Document
    doc.openTransaction("Text Box")
    dlg = TextBoxDialog(note, new)
    if dlg.exec():
        try:
            p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow")
            p.SetString("TextBoxFont", note.Font)
            p.SetFloat("TextBoxSize", float(note.TextSize))
        except Exception:
            pass
        doc.commitTransaction()
        return True
    doc.abortTransaction()
    return False


def _visible_centre(page):
    """Page point in the middle of the drawing's window (where you're looking)."""
    mdi = _mw().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return None, None
    subs = mdi.subWindowList()            # (kept alive while their children are used)
    for sub in subs:
        if page.Label in sub.windowTitle():
            for gv in sub.findChildren(QtWidgets.QGraphicsView):
                if "QGVPage" in gv.metaObject().className():
                    return to_page(gv, gv.viewport().rect().center())
    return None, None


def text_box_command():
    """Text Box: edit the selected note, or add one where you're looking."""
    from mechflow_gui import drawings
    for o in Gui.Selection.getSelection():
        if o.TypeId == "TechDraw::DrawViewAnnotation":
            edit_text_box(o)
            return o
    page = drawings.active_page()
    if page is None:
        QtWidgets.QMessageBox.information(_mw(), "Text Box", "Open a drawing first.")
        return None
    x, y = _visible_centre(page)
    n = add_text_box(page, x, y)
    edit_text_box(n, new=True)
    return n


def scale_note(note, steps):
    """Ctrl + wheel: 10 % bigger or smaller a notch."""
    k = 1.1 ** steps
    if note.TypeId == "TechDraw::DrawViewImage":
        note.Scale = max(0.01, float(note.Scale) * k)
    else:
        note.TextSize = min(200.0, max(0.5, round(float(note.TextSize) * k, 2)))
    note.Document.recompute()


# ------------------------------------------------------------ mouse on the sheet

class _SheetFilter(QtCore.QObject):
    """On a drawing's viewport. The graphics view is looked up from the
    viewport each time: a Python handle kept on it can go stale."""

    drag = None          # the view being dragged by its inside
    replay = False       # a click handed back to FreeCAD

    def eventFilter(self, obj, ev):
        try:
            t = ev.type()
            if self.replay:
                return False
            if t == QtCore.QEvent.MouseMove:
                return self._drag_move(obj, ev) if self.drag is not None else False
            if t == QtCore.QEvent.MouseButtonRelease:
                return self._drag_end(obj, ev) if self.drag is not None else False
            if t not in (QtCore.QEvent.ContextMenu, QtCore.QEvent.Wheel,
                         QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonPress):
                return False
            self.gv = obj.parentWidget()
            if self.gv is None:
                return False
            if t == QtCore.QEvent.MouseButtonPress:
                return self._drag_start(obj, ev)
            if t == QtCore.QEvent.ContextMenu:
                return self._menu(ev)
            if t == QtCore.QEvent.Wheel and (
                    (ev.modifiers() | QtWidgets.QApplication.queryKeyboardModifiers())
                    & QtCore.Qt.ControlModifier):
                return self._wheel(ev)
            if t == QtCore.QEvent.MouseButtonDblClick and ev.button() == QtCore.Qt.LeftButton:
                return self._double(ev)
        except Exception as e:
            self.drag = None
            App.Console.PrintWarning(f"MechFlow: drawing mouse ({e})\n")
        finally:
            self.gv = None
        return False

    # -- drag a view by its inside (FreeCAD only drags it by a thin margin;
    #    inside, a click picks a face). Lines are left to FreeCAD to pick.
    PART_VIEWS = ("TechDraw::DrawViewPart", "TechDraw::DrawProjGroupItem",
                  "TechDraw::DrawViewSection", "TechDraw::DrawViewDetail")

    def _drag_start(self, vp, ev):
        if ev.button() != QtCore.Qt.LeftButton or ev.modifiers() & (
                QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            return False
        pos = self._pos(ev)
        page = page_of_view(self.gv)
        if page is None:
            return False
        under = views_at(self.gv, page, pos, slack=1.0)
        if under and under[0].TypeId not in self.PART_VIEWS + ("TechDraw::DrawProjGroup",):
            return False                        # a note or picture on top: FreeCAD's
        view = _first(under, *self.PART_VIEWS)
        if view is None or getattr(view, "LockPosition", False):
            return False
        if self._near_line(view, pos, page):
            return False
        target = view
        axis = None
        if view.TypeId == "TechDraw::DrawProjGroupItem":
            g = next((p for p in view.InList if p.TypeId == "TechDraw::DrawProjGroup"), None)
            typ = str(view.Type)
            if g is None:
                return False
            if typ == "Front":
                target = g                      # the front carries the others
            elif g.AutoDistribute:
                return False                    # FreeCAD places them itself
            elif typ in ("Top", "Bottom"):
                axis = "y"
            elif typ in ("Left", "Right", "Rear"):
                axis = "x"
            if target is g and getattr(g, "LockPosition", False):
                return False
        x, y = to_page(self.gv, pos)
        self.drag = {"view": view, "target": target, "axis": axis, "start": (x, y),
                     "xy": (float(target.X), float(target.Y)), "screen": QtCore.QPoint(pos),
                     "moving": False, "page": page,
                     "pressed": (pos, ev.globalPosition() if hasattr(ev, "globalPosition")
                                 else QtCore.QPointF(ev.globalPos()))}
        return True

    def _near_line(self, view, pos, page):
        """Within a few pixels of one of the view's lines (FreeCAD picks those)."""
        x, y = to_page(self.gv, pos)
        vx, vy = next(((px, py) for v, px, py in page_views(page) if v is view), (0.0, 0.0))
        tol = 6.0 / max(1e-6, self.gv.transform().m11() * rez())
        import Part
        for ly in (y - vy, vy - y):            # (either way up)
            p = App.Vector(x - vx, ly, 0)
            v = Part.Vertex(p)
            for e in view.getVisibleEdges():
                bb = e.BoundBox
                if not (bb.XMin - tol <= p.x <= bb.XMax + tol and
                        bb.YMin - tol <= p.y <= bb.YMax + tol):
                    continue
                try:
                    if e.distToShape(v)[0] <= tol:
                        return True
                except Exception:
                    pass
        return False

    def _drag_move(self, vp, ev):
        d = self.drag
        pos = self._pos(ev)
        if not (ev.buttons() & QtCore.Qt.LeftButton):
            self.drag = None
            return False
        if not d["moving"]:
            if (pos - d["screen"]).manhattanLength() < 5:
                return True
            d["moving"] = True
            d["target"].Document.openTransaction("Move view")
        gv = vp.parentWidget()
        x, y = to_page(gv, pos)
        dx, dy = x - d["start"][0], y - d["start"][1]
        if d["axis"] == "x":
            dy = 0.0
        elif d["axis"] == "y":
            dx = 0.0
        t = d["target"]
        t.X = d["xy"][0] + dx
        t.Y = d["xy"][1] + dy
        return True

    def _drag_end(self, vp, ev):
        d, self.drag = self.drag, None
        if d["moving"]:
            doc = d["target"].Document
            doc.commitTransaction()
            doc.recompute()
            try:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(d["view"])
            except Exception:
                pass
            return True
        # just a click: let FreeCAD have it (it picks the face)
        pos, gpos = d["pressed"]
        self.replay = True
        try:
            for et in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                e = QtGui.QMouseEvent(et, QtCore.QPointF(pos), gpos, QtCore.Qt.LeftButton,
                                      QtCore.Qt.LeftButton if et == QtCore.QEvent.MouseButtonPress
                                      else QtCore.Qt.NoButton, QtCore.Qt.NoModifier)
                QtWidgets.QApplication.sendEvent(vp, e)
        finally:
            self.replay = False
        return True

    def _pos(self, ev):
        try:
            return ev.position().toPoint()
        except AttributeError:
            return ev.pos()

    def _wheel(self, ev):
        page = page_of_view(self.gv)
        if page is None:
            return False
        sel = [o for o in Gui.Selection.getSelection()
               if o.TypeId in ("TechDraw::DrawViewAnnotation", "TechDraw::DrawViewImage")]
        if not sel:
            return False
        under = views_at(self.gv, page, self._pos(ev))
        target = next((o for o in under if o in sel), None)
        if target is None:
            return False
        d = ev.angleDelta().y()
        if d:
            scale_note(target, 1 if d > 0 else -1)
        return True

    def _double(self, ev):
        page = page_of_view(self.gv)
        if page is None:
            return False
        note = _first(views_at(self.gv, page, self._pos(ev)), "TechDraw::DrawViewAnnotation")
        if note is None:
            return False
        QtCore.QTimer.singleShot(0, lambda: edit_text_box(note))
        return True

    def _menu(self, ev):
        page = page_of_view(self.gv)
        if page is None:
            return False
        pos = ev.pos()
        under = views_at(self.gv, page, pos)
        x, y = to_page(self.gv, pos)
        menu = QtWidgets.QMenu(self.gv)
        from mechflow_gui import view_align, title_block, client_sheet
        item = _first(under, "TechDraw::DrawProjGroupItem")
        group = next((p for p in (item.InList if item is not None else [])
                      if p.TypeId == "TechDraw::DrawProjGroup"), None)
        if group is None:
            group = _first(under, "TechDraw::DrawProjGroup")
        free = next((v for v in under if hasattr(v, "MechFlowAlignment")), None)
        note = _first(under, "TechDraw::DrawViewAnnotation")
        if under:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(under[0])
        if item is not None and str(item.Type) != "Front":
            menu.addAction("Break Alignment", lambda: view_align.break_alignment(item)).setToolTip(
                "Move this view anywhere on the sheet (it stops lining up with the front view)")
        if free is not None:
            menu.addAction("Default Alignment", lambda: view_align.default_alignment(free))
        if group is not None:
            menu.addAction("View Spacing...", lambda: view_align.spacing_command(group))
        if note is not None:
            menu.addAction("Edit Text...", lambda: edit_text_box(note))
            if getattr(note, "MechFlowTitleField", ""):
                t = page.Template
                menu.addAction("Put Back in Title Block",
                               lambda: title_block.put_back(t, note.MechFlowTitleField))
        if not menu.isEmpty():
            menu.addSeparator()
        menu.addAction("Add Text Box Here", lambda: edit_text_box(add_text_box(page, x, y), True))
        menu.addAction("Title Block...", lambda: title_block.TitleBlockDialog(page).exec())
        menu.addAction("Client Sheet (border and title block)...",
                       lambda: client_sheet.client_sheet_command(page))
        theirs = self._freecad_actions()
        if theirs:
            menu.addSeparator()
            for a in theirs:
                menu.addAction(a)
        show_menu(menu, ev.globalPos())
        return True

    def _freecad_actions(self):
        """TechDraw's own right-click choices (frames, keep updated, export...)."""
        w = self.gv.parentWidget()
        while w is not None and "MDIViewPage" not in type(w).__name__ and \
                not isinstance(w, QtWidgets.QMdiSubWindow):
            w = w.parentWidget()
        if w is None:
            return []
        out = []
        act = getattr(QtGui, "QAction", None) or QtWidgets.QAction
        for a in w.findChildren(act):
            if a.text() and a.parent() is not None and \
                    not isinstance(a.parent(), QtWidgets.QMenu) and a not in out:
                out.append(a)
        return out


_filter = None


def show_menu(menu, pos):
    menu.exec(pos)


def _hook(gv):
    global _filter
    if gv.property("mechflow_sheet") or "QGVPage" not in gv.metaObject().className():
        return
    gv.setProperty("mechflow_sheet", True)
    if _filter is None:
        _filter = _SheetFilter()          # one filter, kept here, for every drawing
    gv.viewport().installEventFilter(_filter)


def hook_all():
    mdi = _mw().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return
    subs = mdi.subWindowList()
    for sub in subs:
        for gv in sub.findChildren(QtWidgets.QGraphicsView):
            try:
                _hook(gv)
            except Exception:
                pass


_installed = False


def install():
    global _installed
    if _installed:
        return
    mdi = _mw().findChild(QtWidgets.QMdiArea)
    if mdi is None:
        return
    mdi.subWindowActivated.connect(lambda _w: QtCore.QTimer.singleShot(0, hook_all))
    _installed = True
    hook_all()
