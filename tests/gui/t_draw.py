import os, sys; sys.path.insert(0, os.environ.get("MF_TESTDIR", os.getcwd()))
from h import *
import Part
V = App.Vector
S = {}
def setup():
    install_hooks()
    Gui.activateWorkbench("MechFlowWorkbench")
    doc = App.newDocument("Bracket"); S["doc"]=doc
    b = new_body(doc, "Body"); S["b"]=b
    sk = sketch(b, "XY_Plane", rect(0, 0, 120, 60)); pad = b.newObject("PartDesign::Pad","Pad"); pad.Profile=sk; pad.Length=30
    h = b.newObject("PartDesign::SubtractiveCylinder","Hole"); h.Radius=10; h.Height=30; attach_xy(h, b, 40, 30)
    doc.recompute(); sk.ViewObject.Visibility=False
    from mechflow_gui import material; material.set_material(b, "Aluminium 6061-T6", 2700)
    from mechflow_gui import drawings
    S["dlg_sheet"] = "A3 (ISO) - Landscape"
    def fake_exec(self):
        items = self.list.findItems(S["dlg_sheet"], drawings._match()); self.list.setCurrentItem(items[0])
        log("  dialog: sheet", self.list.currentItem().text(), "projection", self.proj.currentText(), "iso", self.iso.isChecked())
        return True
    drawings.SheetDialog.exec = fake_exec
    App.ParamGet("User parameter:BaseApp/Preferences/Document").SetString("prefAuthor", "G. Waterman")
at(setup, 1800)
def mk():
    Gui.Selection.clearSelection(); sel(S["b"])
    from mechflow_gui import drawings
    S["page"] = drawings.make_drawing()
at(mk, 3000)
def report(tag):
    def f():
        p = S["page"]; t = p.Template
        views = [o for o in p.Views]
        log(tag, "page", p.Label, "scale", p.Scale, "template", os.path.basename(t.Template))
        for v in views:
            log("   view", v.Label, v.TypeId.split("::")[1], "valid", v.isValid(), "X", round(float(v.X),1), "Y", round(float(v.Y),1),
                [ (c.Label, round(float(c.X),1), round(float(c.Y),1)) for c in getattr(v, "Views", [])])
        e = t.EditableTexts
        log("   title block", {k: v for k, v in e.items() if v})
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        log("   active window", mdi.activeSubWindow().windowTitle() if mdi.activeSubWindow() else None)
        shot(tag)
    return f
at(report("draw_A3"), 200)
# ANSI third angle
def mk2():
    S["dlg_sheet"] = "B (ANSI) - Landscape"
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow").SetString("DrawingProjection", "")
    Gui.Selection.clearSelection(); sel(S["b"])
    from mechflow_gui import drawings
    S["page"] = drawings.make_drawing()
at(mk2, 3000)
at(report("draw_ANSI"), 200)
# sheet format change to A2 on ANSI page
def sf():
    S["dlg_sheet"] = "A2 (ISO) - Landscape"
    Gui.Selection.clearSelection(); sel(S["page"])
    from mechflow_gui import drawings; drawings.sheet_format()
at(sf, 1500)
at(lambda: log("after sheet format:", os.path.basename(S["page"].Template.Template), "title kept:", S["page"].Template.EditableTexts.get("title")), 100)
def pdf():
    from mechflow_gui import drawings
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (OUT + "test_drawing.pdf", "PDF"))
    Gui.Selection.clearSelection(); sel(S["page"])
    drawings.save_pdf()
at(pdf, 2500)
at(lambda: log("pdf exists", os.path.exists(OUT + "test_drawing.pdf"), os.path.getsize(OUT + "test_drawing.pdf") if os.path.exists(OUT + "test_drawing.pdf") else 0), 100)
def tab():
    from mechflow_gui import command_manager as cm
    avail = set(Gui.listCommands()); missing=[]
    for t, entries in cm.TABS:
        if t != "Drawing": continue
        for e in entries:
            if e is None: continue
            items = e[1] if e[0]=="stack" else (e[2] if e[0]=="grid" else [e])
            for label, cmd in items:
                if cm._resolve(cmd, avail) is None: missing.append((label, cmd))
    log("Drawing tab missing:", missing)
    cm.select_tab("Drawing")
at(tab, 500)
at(lambda: Gui.getMainWindow().grab().copy(0, 0, 1600, 130).save(SHOTS + "drawtab.png"), 300)
run()
