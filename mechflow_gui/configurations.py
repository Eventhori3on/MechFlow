# SPDX-License-Identifier: LGPL-2.1-or-later
"""Configurations and Design Tables (SOLIDWORKS-style).

One part file, several versions of it: a Design Table (a spreadsheet in
the part) has a row per configuration and a column per parameter - a named
sketch dimension ("BaseSketch.Width"), a feature value ("Pad.Length",
"Shell.Thickness", "Nozzle.Standout"), a size ("SHS 100x100x6.3.Size") or a
feature's suppression ("Gusset.Suppressed"). Pick a configuration and the
part is rebuilt to it.

The table can be edited like any spreadsheet; the Configurations panel
adds parameters and configurations, switches between them, and copies the
model's current values back into the active row.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

TABLE_LABEL = "Design Table"
NUMERIC = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle",
           "App::PropertyFloat", "App::PropertyInteger", "App::PropertyIntegerConstraint",
           "App::PropertyFloatConstraint", "App::PropertyQuantity", "App::PropertyPercent")
DIM_TYPES = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
SKIP_PROPS = {"Placement", "Visibility", "Label", "Label2", "ExpressionEngine", "Refine",
              "MapReversed", "AttacherType", "MapPathParameter", "Offset2", "Angle2",
              "TaperAngle", "TaperAngle2", "MechFlowInstance", "Spin", "Offset", "Invert",
              "Rotation", "_Body", "AllowMultiFace", "Midplane", "Reversed", "UseCustomVector",
              "AlongSketchNormal", "Precision", "SolidTolerance", "FuzzyTolerance",
              "FirstAngle", "SecondAngle", "Angle1", "Angle3", "TipLength", "MarkerSize"}
FRIENDLY = {("PartDesign::Thickness", "Value"): "wall thickness",
            ("PartDesign::Pad", "Length"): "depth", ("PartDesign::Pocket", "Length"): "depth",
            ("PartDesign::Pad", "Length2"): "depth (2nd direction)",
            ("PartDesign::Fillet", "Radius"): "radius", ("PartDesign::Chamfer", "Size"): "size",
            ("PartDesign::Hole", "Depth"): "depth"}


# ------------------------------------------------------------ parameters

def _is_feature(o):
    if o.TypeId in ("Spreadsheet::Sheet",) or o.TypeId.startswith("TechDraw::") \
            or o.TypeId.startswith("App::Origin") or o.TypeId in ("App::Line", "App::Plane",
                                                                    "App::Point"):
        return False
    return True


def parameters(doc):
    """[(key, description, current value)] that a design table can drive."""
    out = []
    for o in doc.Objects:
        if not _is_feature(o):
            continue
        if o.TypeId == "Sketcher::SketchObject":
            for c in o.Constraints:
                if c.Name and c.Type in DIM_TYPES and c.Driving:
                    out.append((f"{o.Name}.{c.Name}", f"{o.Label}: {c.Name} ({c.Type})",
                                _datum(o, c.Name)))
            continue
        for p in o.PropertiesList:
            if p in SKIP_PROPS or o.getEditorMode(p) and "Hidden" in o.getEditorMode(p):
                continue
            t = o.getTypeIdOfProperty(p)
            if t in NUMERIC:
                if o.getGroupOfProperty(p) in ("Base", "Attachment"):
                    continue
                nice = FRIENDLY.get((o.TypeId, p), p)
                out.append((f"{o.Name}.{p}", f"{o.Label}: {nice}", _plain(getattr(o, p))))
            elif p == "Size" and t in ("App::PropertyString", "App::PropertyEnumeration"):
                out.append((f"{o.Name}.{p}", f"{o.Label}: size", str(getattr(o, p))))
        if hasattr(o, "Suppressed") and o.TypeId.startswith("PartDesign::"):
            out.append((f"{o.Name}.Suppressed", f"{o.Label}: suppressed", bool(o.Suppressed)))
    return out


def _datum(sk, name):
    try:
        q = sk.getDatum(name)
        return float(getattr(q, "Value", q))
    except Exception:
        return None


def _plain(v):
    if hasattr(v, "Value"):
        return float(v.Value)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    return str(v)


def _resolve(doc, key):
    name, attr = key.split(".", 1)
    o = doc.getObject(name)
    if o is None:
        o = next((x for x in doc.Objects if x.Label == name), None)
    return o, attr


def value_of(doc, key):
    o, attr = _resolve(doc, key)
    if o is None:
        return None
    if o.TypeId == "Sketcher::SketchObject" and attr not in o.PropertiesList:
        return _datum(o, attr)
    return _plain(getattr(o, attr, None))


def set_value(doc, key, val):
    """Push one value into the model. Returns an error string or None."""
    o, attr = _resolve(doc, key)
    if o is None:
        return f"{key}: no such object"
    try:
        if o.TypeId == "Sketcher::SketchObject" and attr not in o.PropertiesList:
            c = [x for x in o.Constraints if x.Name == attr]
            if not c:
                return f"{key}: no dimension called {attr}"
            unit = "deg" if c[0].Type == "Angle" else "mm"
            o.setDatum(attr, App.Units.Quantity(f"{float(val)} {unit}"))
            return None
        cur = getattr(o, attr)
        t = o.getTypeIdOfProperty(attr)
        if t == "App::PropertyBool" or isinstance(cur, bool):
            v = val if isinstance(val, bool) else str(val).strip().lower() in ("1", "true", "yes", "y")
        elif t in ("App::PropertyInteger", "App::PropertyIntegerConstraint", "App::PropertyPercent"):
            v = int(float(val))
        elif t in NUMERIC:
            v = float(val)
        else:
            v = str(val)
        setattr(o, attr, v)
        return None
    except Exception as e:
        return f"{key}: {e}"


# ------------------------------------------------------------ the table

def table(doc, create=False):
    for o in doc.Objects:
        if o.TypeId == "Spreadsheet::Sheet" and getattr(o, "MechFlowDesignTable", False):
            return o
    if not create:
        return None
    sh = doc.addObject("Spreadsheet::Sheet", "DesignTable")
    sh.addProperty("App::PropertyBool", "MechFlowDesignTable", "Base", "Design table", 4)
    sh.MechFlowDesignTable = True
    sh.addProperty("App::PropertyString", "ActiveConfiguration", "Configurations",
                   "The configuration the part is built to")
    sh.Label = TABLE_LABEL
    sh.set("A1", "Configuration")
    sh.setStyle("A1:A1", "bold")
    sh.setColumnWidth("A", 160)
    try:
        sh.ViewObject.Visibility = False
    except Exception:
        pass
    return sh


def _col(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(sh, ref):
    try:
        v = sh.get(ref)
    except Exception:
        return None
    if isinstance(v, str):
        return v.lstrip("'")
    return _plain(v)


def columns(sh):
    out = []
    c = 1
    while True:
        k = _cell(sh, f"{_col(c)}1")
        if not k:
            break
        out.append(str(k))
        c += 1
    return out


def configurations(sh):
    out = []
    r = 2
    while True:
        n = _cell(sh, f"A{r}")
        if n is None or n == "":
            break
        out.append(str(n))
        r += 1
    return out


def row_values(sh, name):
    keys = columns(sh)
    names = configurations(sh)
    if name not in names:
        return {}
    r = names.index(name) + 2
    return {k: _cell(sh, f"{_col(i + 1)}{r}") for i, k in enumerate(keys)}


def _write(sh, ref, v):
    if isinstance(v, bool):
        sh.set(ref, "TRUE" if v else "FALSE")
    elif isinstance(v, (int, float)):
        sh.set(ref, f"{v:g}" if isinstance(v, float) else str(v))
    elif v is None:
        sh.set(ref, "")
    else:
        sh.set(ref, "'" + str(v))


def add_parameter(doc, key):
    sh = table(doc, create=True)
    keys = columns(sh)
    if key in keys:
        return sh
    c = _col(len(keys) + 1)
    sh.set(f"{c}1", "'" + key)
    sh.setStyle(f"{c}1:{c}1", "bold")
    sh.setColumnWidth(c, max(110, 8 * len(key)))
    cur = value_of(doc, key)
    for r in range(2, len(configurations(sh)) + 2):
        _write(sh, f"{c}{r}", cur)
    doc.recompute()
    return sh


def add_configuration(doc, name, values=None):
    """A new row: the model's current values, or values {key: value}."""
    sh = table(doc, create=True)
    names = configurations(sh)
    if name in names:
        raise ValueError(f"there's already a configuration called {name}")
    r = len(names) + 2
    sh.set(f"A{r}", "'" + name)
    for i, k in enumerate(columns(sh)):
        v = values.get(k) if values and k in values else value_of(doc, k)
        _write(sh, f"{_col(i + 1)}{r}", v)
    if not sh.ActiveConfiguration:
        sh.ActiveConfiguration = name
    doc.recompute()
    return sh


def delete_configuration(doc, name):
    sh = table(doc)
    names = configurations(sh)
    if name not in names:
        return
    if len(names) == 1:
        raise ValueError("a part needs at least one configuration")
    keys = columns(sh)
    rows = [[_cell(sh, f"{_col(i)}{r}") for i in range(len(keys) + 1)]
            for r in range(2, len(names) + 2)]
    del rows[names.index(name)]
    for r in range(2, len(names) + 2):
        for i in range(len(keys) + 1):
            sh.set(f"{_col(i)}{r}", "")
    for r, vals in enumerate(rows, start=2):
        for i, v in enumerate(vals):
            if i == 0:
                sh.set(f"A{r}", "'" + str(v))
            else:
                _write(sh, f"{_col(i)}{r}", v)
    if sh.ActiveConfiguration == name:
        sh.ActiveConfiguration = rows[0][0]
        activate(doc, sh.ActiveConfiguration)
    doc.recompute()


def activate(doc, name):
    """Build the part to configuration name. Returns [errors]."""
    sh = table(doc)
    if sh is None:
        raise ValueError("this part has no design table")
    vals = row_values(sh, name)
    if not vals and name not in configurations(sh):
        raise ValueError(f"no configuration called {name}")
    errors = []
    for k, v in vals.items():
        if v is None or v == "":
            continue
        e = set_value(doc, k, v)
        if e:
            errors.append(e)
    sh.ActiveConfiguration = name
    doc.recompute()
    bad = [o.Label for o in doc.Objects if hasattr(o, "isValid") and not o.isValid()
           and o.TypeId != "Spreadsheet::Sheet"]
    if bad:
        errors.append("didn't rebuild: " + ", ".join(bad[:6]))
    return errors


def update_from_model(doc, name=None):
    """Copy the model's current values into a configuration's row."""
    sh = table(doc)
    name = name or sh.ActiveConfiguration
    names = configurations(sh)
    r = names.index(name) + 2
    for i, k in enumerate(columns(sh)):
        _write(sh, f"{_col(i + 1)}{r}", value_of(doc, k))
    doc.recompute()


# ------------------------------------------------------------ panel

class ConfigPanel:
    """SOLIDWORKS ConfigurationManager, as a task panel."""

    def __init__(self, doc):
        self.doc = doc
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Configurations")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.addWidget(QtWidgets.QLabel(f"<b>{doc.Label}</b> - double-click a configuration "
                                       "to build the part to it."))
        self.list = QtWidgets.QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self._activate())
        lay.addWidget(self.list, 1)
        g = QtWidgets.QGridLayout()
        for i, (text, fn) in enumerate((("Activate", self._activate), ("Add...", self._add),
                                        ("Delete", self._delete), ("Rename...", self._rename),
                                        ("Save model values", self._update),
                                        ("Edit table", self._edit))):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, i // 2, i % 2)
        lay.addLayout(g)
        lay.addWidget(QtWidgets.QLabel("<b>Parameters in the table</b>"))
        self.params = QtWidgets.QListWidget()
        self.params.setMaximumHeight(130)
        lay.addWidget(self.params)
        pb = QtWidgets.QPushButton("Add parameters...")
        pb.clicked.connect(self._add_params)
        lay.addWidget(pb)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("color: gray;")
        lay.addWidget(self.msg)
        self._refresh()

    def _refresh(self):
        sh = table(self.doc)
        self.list.clear()
        self.params.clear()
        if sh is None:
            self.msg.setText("No design table yet: <b>Add parameters</b> to start one - "
                             "e.g. a sketch's Width and the extrusion's depth.")
            return
        for n in configurations(sh):
            it = QtWidgets.QListWidgetItem(n + ("   (active)" if n == sh.ActiveConfiguration else ""))
            it.setData(QtCore.Qt.UserRole, n)
            if n == sh.ActiveConfiguration:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.list.addItem(it)
        for k in columns(sh):
            self.params.addItem(k)
        self.msg.setText("")

    def _current(self):
        it = self.list.currentItem()
        return it.data(QtCore.Qt.UserRole) if it else None

    def _activate(self):
        n = self._current()
        if not n:
            return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            errs = activate(self.doc, n)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self._refresh()
        self.msg.setText(("<b>Problems:</b><br>" + "<br>".join(errs)) if errs
                         else f"Built to <b>{n}</b>.")

    def _add(self):
        name, ok = QtWidgets.QInputDialog.getText(self.form, "Add Configuration",
                                                  "Name (it starts with the model's current values):")
        if ok and name.strip():
            try:
                add_configuration(self.doc, name.strip())
            except Exception as e:
                self.msg.setText(str(e))
            self._refresh()

    def _delete(self):
        n = self._current()
        if n:
            try:
                delete_configuration(self.doc, n)
            except Exception as e:
                self.msg.setText(str(e))
            self._refresh()

    def _rename(self):
        n = self._current()
        if not n:
            return
        new, ok = QtWidgets.QInputDialog.getText(self.form, "Rename Configuration", "Name:", text=n)
        if ok and new.strip() and new != n:
            sh = table(self.doc)
            r = configurations(sh).index(n) + 2
            sh.set(f"A{r}", "'" + new.strip())
            if sh.ActiveConfiguration == n:
                sh.ActiveConfiguration = new.strip()
            self.doc.recompute()
            self._refresh()

    def _update(self):
        sh = table(self.doc)
        if sh and sh.ActiveConfiguration:
            update_from_model(self.doc)
            self.msg.setText(f"Saved the model's values into <b>{sh.ActiveConfiguration}</b>.")

    def _edit(self):
        sh = table(self.doc)
        if sh:
            try:
                sh.ViewObject.doubleClicked()
            except Exception:
                Gui.ActiveDocument.setEdit(sh.Name)

    def _add_params(self):
        dlg = QtWidgets.QDialog(self.form)
        dlg.setWindowTitle("Add Parameters")
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel("Tick what the configurations should change. Name a sketch "
                                     "dimension (Smart Dimension, Name) to list it here."))
        lst = QtWidgets.QListWidget()
        have = set(columns(table(self.doc))) if table(self.doc) else set()
        for key, desc, cur in parameters(self.doc):
            it = QtWidgets.QListWidgetItem(f"{desc} = {cur}")
            it.setData(QtCore.Qt.UserRole, key)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if key in have else QtCore.Qt.Unchecked)
            lst.addItem(it)
        v.addWidget(lst)
        b = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok |
                                       QtWidgets.QDialogButtonBox.Cancel)
        b.accepted.connect(dlg.accept)
        b.rejected.connect(dlg.reject)
        v.addWidget(b)
        dlg.resize(520, 480)
        if not dlg.exec():
            return
        first = table(self.doc) is None
        for i in range(lst.count()):
            it = lst.item(i)
            if it.checkState() == QtCore.Qt.Checked:
                add_parameter(self.doc, it.data(QtCore.Qt.UserRole))
        if first and table(self.doc) is not None and not configurations(table(self.doc)):
            add_configuration(self.doc, "Default")
        self._refresh()

    def accept(self):
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close


def show():
    doc = App.ActiveDocument
    if doc is None:
        return None
    if Gui.Control.activeDialog():
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Configurations",
                                          "Finish the open dialog first.")
        return None
    p = ConfigPanel(doc)
    Gui.Control.showDialog(p)
    return p
