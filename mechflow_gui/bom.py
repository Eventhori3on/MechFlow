# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style Bill of Materials for an assembly.

ITEM NO. / PART NUMBER / DESCRIPTION / QTY., top level. Identical parts are
counted together: links to the same part, and Toolbox fasteners of the same
standard and size ('ISO 4762 M8x25' x 4). FreeCAD's own BOM lists each
fastener on its own row, as they are separate objects.

The table is kept in the assembly document as a spreadsheet called
"Bill of Materials"; running the command again updates it.
"""

import re

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

HEADERS = ["ITEM NO.", "PART NUMBER", "DESCRIPTION", "QTY."]
SKIP_TYPES = ("Assembly::JointGroup", "Assembly::ViewGroup", "Assembly::BomGroup",
              "Assembly::BomObject", "Spreadsheet::Sheet", "App::DocumentObjectGroup",
              "Sketcher::SketchObject", "App::Origin")


def _strip_instance(label):
    """'Plate<1>' -> 'Plate', 'Bracket001' stays (it may be a real name)."""
    return re.sub(r"\s*<\d+>$", "", label)


def _fastener_row(o):
    from mechflow_gui import toolbox
    name = toolbox.designation(o)
    desc = ""
    FC = toolbox.fasteners()
    try:
        desc = str(FC.FSScrewCommandTable[o.Type][0])
    except Exception:
        pass
    return name, desc


def _std_row(o):
    from mechflow_gui import stdparts
    desc = stdparts.description(o.StdType)
    mat = getattr(o, "MechFlowMaterial", "") or ""
    return stdparts.object_designation(o), (f"{desc}, {mat}" if mat else desc)


def _is_std(o):
    from mechflow_gui import stdparts
    return stdparts.is_std_object(o)


def _is_fastener(o):
    return hasattr(o, "Type") and hasattr(o, "Diameter") and \
        type(getattr(o, "Proxy", None)).__name__ == "FSScrewObject"


def _part_row(o):
    """(part number, description) for a component."""
    target = o
    if o.TypeId == "App::Link" and o.LinkedObject is not None:
        target = o.LinkedObject
        if isinstance(target, tuple):
            target = target[0]
    if _is_fastener(target):
        return _fastener_row(target)
    if _is_std(target):
        return _std_row(target)
    # A part kept in its own file is known by its file name, like SOLIDWORKS.
    if target.Document is not o.Document:
        name = target.Document.Label
    else:
        name = _strip_instance(target.Label if target is not o else o.Label)
    desc = getattr(target, "Label2", "") or ""
    return name, desc


def part_number(o):
    """A part number given to the part (Save Part As), if any."""
    for x in (o, getattr(o, "LinkedObject", None)):
        if isinstance(x, tuple):
            x = x[0]
        pn = (getattr(x, "PartNumber", "") or "").strip() if x is not None else ""
        if pn:
            return pn
    return ""


def _numbered(o, name, desc):
    """With a part number the number leads and what the part is moves to
    the description."""
    pn = part_number(o)
    if not pn or pn == name:
        return name, desc
    return pn, (f"{name}, {desc}" if desc and name not in desc else (desc or name))


def rows(asm):
    """[(part number, description, qty)] in tree order."""
    return rows_with_objects(asm)[0]


def rows_with_objects(asm):
    """(rows, {part number: [objects]}) - the objects let a drawing put a
    balloon on each item."""
    order, count, descs, objs = [], {}, {}, {}
    for o in asm.Group:
        if o.TypeId in SKIP_TYPES or any(o.isDerivedFrom(t) for t in SKIP_TYPES[:4]) \
                or o.isDerivedFrom("Part::Part2DObject"):
            continue                      # layout sketches (e.g. pipe routes) aren't parts
        if type(getattr(o, "Proxy", None)).__name__ in ("Joint", "GroundedJoint", "ViewProviderJoint",
                                                         "PipeRoute"):
            continue                      # mates and routes are not parts (route parts are)
        if getattr(o, "Visibility", True) is False and not _is_fastener(o) \
                and not _is_std(o) and o.TypeId != "App::Link":
            continue
        try:
            name, desc = (_fastener_row(o) if _is_fastener(o) else
                          _std_row(o) if _is_std(o) else _part_row(o))
            name, desc = _numbered(o, name, desc)
        except Exception:
            continue
        n = 1
        if o.TypeId == "App::Link":
            n = max(1, int(getattr(o, "ElementCount", 0) or 1))
        if name not in count:
            order.append(name)
            count[name] = 0
            descs[name] = desc
            objs[name] = []
        count[name] += n
        objs[name].append(o)
    return [(name, descs[name], count[name]) for name in order], objs


def _sheet(doc, asm):
    for o in doc.Objects:
        if o.TypeId == "Spreadsheet::Sheet" and getattr(o, "MechFlowBOM", "") == asm.Name:
            return o
    sh = doc.addObject("Spreadsheet::Sheet", "BOM")
    sh.addProperty("App::PropertyString", "MechFlowBOM", "Base", "Assembly this BOM lists", 4)
    sh.MechFlowBOM = asm.Name
    sh.Label = "Bill of Materials"
    return sh


def write(asm):
    """Make or update the BOM spreadsheet. Returns (sheet, rows)."""
    doc = asm.Document
    data = rows(asm)
    sh = _sheet(doc, asm)
    sh.clearAll()
    cols = "ABCD"
    for c, h in zip(cols, HEADERS):
        sh.set(f"{c}1", h)
    sh.setStyle("A1:D1", "bold")
    sh.setAlignment("A1:D1", "center")
    for i, (name, desc, qty) in enumerate(data, start=2):
        sh.set(f"A{i}", str(i - 1))
        sh.set(f"B{i}", "'" + name)
        sh.set(f"C{i}", "'" + desc if desc else "")
        sh.set(f"D{i}", str(qty))
        sh.setAlignment(f"A{i}", "center")
        sh.setAlignment(f"D{i}", "center")
    for c, w in zip(cols, (70, 220, 260, 50)):
        sh.setColumnWidth(c, w)
    doc.recompute()
    return sh, data


def show(asm, data, sheet):
    dlg = QtWidgets.QDialog(Gui.getMainWindow())
    dlg.setWindowTitle(f"Bill of Materials - {asm.Label}")
    v = QtWidgets.QVBoxLayout(dlg)
    t = QtWidgets.QTableWidget(len(data), 4)
    t.setHorizontalHeaderLabels(HEADERS)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    for r, (name, desc, qty) in enumerate(data):
        for c, val in enumerate((str(r + 1), name, desc, str(qty))):
            it = QtWidgets.QTableWidgetItem(val)
            if c in (0, 3):
                it.setTextAlignment(QtCore.Qt.AlignCenter)
            t.setItem(r, c, it)
    t.resizeColumnsToContents()
    t.horizontalHeader().setStretchLastSection(False)
    v.addWidget(t)
    note = QtWidgets.QLabel(f"Saved in the tree as <b>{sheet.Label}</b>. Run Bill of "
                            "Materials again after changing the assembly to update it. "
                            "Make Drawing puts it on a sheet with numbered balloons.")
    note.setWordWrap(True)
    v.addWidget(note)
    b = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
    b.rejected.connect(dlg.reject)
    v.addWidget(b)
    dlg.resize(640, min(520, 140 + 28 * len(data)))
    dlg.setModal(False)
    dlg.show()
    return dlg


_last = []


def bill_of_materials():
    from mechflow_gui import assembly
    asm = assembly.active_assembly()
    if asm is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Bill of Materials",
                                          "Open an assembly first.")
        return None
    asm.Document.openTransaction("Bill of Materials")
    sheet, data = write(asm)
    asm.Document.commitTransaction()
    _last[:] = [show(asm, data, sheet)]
    return data
