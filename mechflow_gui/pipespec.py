# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pipe specs (SOLIDWORKS Routing "piping specs", simplified).

A spec is a named set of choices a route follows: standard (EN / ASME),
material, schedule (by size, for ASME), elbow type, flange rating and how
free ends finish. Built-in specs cover the usual cases; your own are saved
as small JSON files in "<FreeCAD user data>/MechFlow Pipe Specs" (copy the
folder to share them). Routes keep the spec's name: change the spec and
every route using it follows.
"""

import json
import os
import re

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

MATERIALS = {                         # name: density kg/m^3
    "Carbon steel P235GH": 7850.0,
    "Carbon steel P265GH": 7850.0,
    "Carbon steel A106 Gr B": 7850.0,
    "Stainless steel 1.4404 (316L)": 8000.0,
    "Stainless steel A312 TP316L": 8000.0,
    "Stainless steel 1.4301 (304)": 8000.0,
    "Duplex 1.4462": 7800.0,
}
FIELDS = ("standard", "material", "schedule", "schedule_by_size", "bend", "rating",
          "free_ends", "start_size")

BUILT_IN = [
    {"name": "EN carbon steel PN16", "standard": "EN", "material": "Carbon steel P235GH",
     "schedule": "", "schedule_by_size": {}, "bend": "3D", "rating": "PN16",
     "free_ends": "Weld neck flange", "start_size": "DN80"},
    {"name": "EN carbon steel PN40", "standard": "EN", "material": "Carbon steel P265GH",
     "schedule": "", "schedule_by_size": {}, "bend": "3D", "rating": "PN40",
     "free_ends": "Weld neck flange", "start_size": "DN80"},
    {"name": "EN stainless 316L PN16", "standard": "EN", "material": "Stainless steel 1.4404 (316L)",
     "schedule": "", "schedule_by_size": {}, "bend": "3D", "rating": "PN16",
     "free_ends": "Weld neck flange", "start_size": "DN50"},
    {"name": "ASME CS Class 150 Sch 40", "standard": "ASME", "material": "Carbon steel A106 Gr B",
     "schedule": "Sch 40", "schedule_by_size": {}, "bend": "LR", "rating": "Class 150",
     "free_ends": "Weld neck flange", "start_size": "NPS 3"},
    {"name": "ASME CS Class 300 Sch 80 (small bore)", "standard": "ASME",
     "material": "Carbon steel A106 Gr B", "schedule": "Sch 40",
     "schedule_by_size": {"NPS 1/2": "Sch 80", "NPS 3/4": "Sch 80", "NPS 1": "Sch 80",
                          "NPS 1-1/4": "Sch 80", "NPS 1-1/2": "Sch 80", "NPS 2": "Sch 80"},
     "bend": "LR", "rating": "Class 300", "free_ends": "Weld neck flange", "start_size": "NPS 2"},
    {"name": "ASME SS 316L Class 150 Sch 10", "standard": "ASME",
     "material": "Stainless steel A312 TP316L", "schedule": "Sch 10", "schedule_by_size": {},
     "bend": "LR", "rating": "Class 150", "free_ends": "Weld neck flange", "start_size": "NPS 2"},
]


def folder():
    d = os.environ.get("MF_PIPE_SPECS") or os.path.join(App.getUserAppDataDir(),
                                                        "MechFlow Pipe Specs")
    os.makedirs(d, exist_ok=True)
    return d


def _file_for(name):
    safe = re.sub(r"[^A-Za-z0-9 ._()-]+", "_", name).strip() or "spec"
    return os.path.join(folder(), safe + ".json")


def user_specs():
    out = []
    try:
        names = sorted(os.listdir(folder()))
    except Exception:
        names = []
    for n in names:
        if not n.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(folder(), n), encoding="utf-8") as f:
                s = json.load(f)
            if s.get("name"):
                s["user"] = True
                out.append(normalise(s))
        except Exception as e:
            App.Console.PrintWarning(f"MechFlow: pipe spec {n} not read ({e})\n")
    return out


def all_specs():
    seen = set()
    out = []
    for s in user_specs() + [dict(b) for b in BUILT_IN]:
        if s["name"] in seen:               # your own spec of the same name wins
            continue
        seen.add(s["name"])
        out.append(normalise(s))
    return out


def get(name):
    for s in all_specs():
        if s["name"] == name:
            return s
    return None


def normalise(s):
    s = dict(s)
    s.setdefault("standard", "EN")
    s.setdefault("material", "")
    s.setdefault("schedule", "Sch 40" if s["standard"] == "ASME" else "")
    s.setdefault("schedule_by_size", {})
    s.setdefault("bend", "LR" if s["standard"] == "ASME" else "3D")
    s.setdefault("rating", "Class 150" if s["standard"] == "ASME" else "PN16")
    s.setdefault("free_ends", "Weld neck flange")
    s.setdefault("start_size", "")
    return s


def save(spec):
    spec = normalise(spec)
    if not spec.get("name"):
        raise ValueError("give the spec a name")
    if any(b["name"] == spec["name"] for b in BUILT_IN) and not spec.get("user"):
        raise ValueError("that's a built-in spec's name - pick another")
    data = {k: spec[k] for k in ("name",) + FIELDS}
    with open(_file_for(spec["name"]), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return _file_for(spec["name"])


def delete(name):
    p = _file_for(name)
    if os.path.exists(p):
        os.remove(p)


def schedule_for(spec_or_route, size):
    """Schedule for one size (ASME): the size's own, or the spec default."""
    if isinstance(spec_or_route, dict):
        by = spec_or_route.get("schedule_by_size") or {}
        return by.get(size) or spec_or_route.get("schedule") or "Sch 40"
    by = {}
    try:
        by = json.loads(getattr(spec_or_route, "ScheduleBySize", "") or "{}")
    except Exception:
        pass
    return by.get(size) or spec_or_route.Schedule or "Sch 40"


def density(material):
    return MATERIALS.get(material, 7850.0)


# ------------------------------------------------------------ routes

def apply_to_route(route, spec):
    """Set a route's fields from a spec (doesn't rebuild)."""
    from mechflow_gui import routing
    routing.ensure_props(route)
    route.Spec = spec["name"]
    route.Standard = spec["standard"]
    route.Schedule = spec["schedule"] if spec["standard"] == "ASME" else ""
    route.ScheduleBySize = json.dumps(spec.get("schedule_by_size") or {}, sort_keys=True)
    route.Bend = spec["bend"]
    route.FlangeRating = spec["rating"]
    route.FreeEnds = spec["free_ends"]
    route.Material = spec["material"]


def update_routes(name):
    """After a spec changed: every open route using it follows."""
    from mechflow_gui import routing
    spec = get(name)
    n = 0
    if spec is None:
        return 0
    routes = [o for doc in App.listDocuments().values() for o in doc.Objects
              if routing.is_route(o) and getattr(o, "Spec", "") == name]
    for o in routes:                     # (building removes and adds objects)
        apply_to_route(o, spec)
        try:
            routing.build(o)
        except Exception as e:
            o.Error = str(e)
        n += 1
    return n


# ------------------------------------------------------------ editor

class SpecDialog(QtWidgets.QDialog):
    """Pipe Specs: pick one to look at; built-ins are fixed (Duplicate to
    make your own from one), yours can be changed and deleted."""

    def __init__(self, parent=None, select=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("Pipe Specs")
        self.resize(760, 560)
        self._editable = False
        lay = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(self._show)
        left.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        for text, fn in (("New", self._new), ("Duplicate", self._dup), ("Delete", self._delete)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            setattr(self, "b_" + text.lower(), b)
        left.addLayout(row)
        lay.addLayout(left, 2)
        right = QtWidgets.QVBoxLayout()
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        right.addWidget(self.note)
        f = QtWidgets.QFormLayout()
        self.name = QtWidgets.QLineEdit()
        f.addRow("Name", self.name)
        self.std = QtWidgets.QComboBox()
        self.std.addItems(["EN", "ASME"])
        self.std.currentTextChanged.connect(self._std_changed)
        f.addRow("Standard", self.std)
        self.material = QtWidgets.QComboBox()
        self.material.setEditable(True)
        self.material.addItems(list(MATERIALS))
        f.addRow("Material", self.material)
        self.sched = QtWidgets.QComboBox()
        f.addRow("Schedule", self.sched)
        self.bend = QtWidgets.QComboBox()
        f.addRow("Elbows", self.bend)
        self.rating = QtWidgets.QComboBox()
        f.addRow("Flange rating", self.rating)
        self.ends = QtWidgets.QComboBox()
        f.addRow("Free ends", self.ends)
        self.start = QtWidgets.QComboBox()
        f.addRow("Start size", self.start)
        right.addLayout(f)
        self.by_label = QtWidgets.QLabel("<b>Schedule by size</b> (blank: the schedule above)")
        right.addWidget(self.by_label)
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Size", "Schedule"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        right.addWidget(self.table, 1)
        self.filler = QtWidgets.QWidget()           # takes the table's room for EN specs
        right.addWidget(self.filler, 1)
        bb = QtWidgets.QDialogButtonBox()
        self.b_save = bb.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        self.b_save.clicked.connect(self._save)
        close = bb.addButton("Close", QtWidgets.QDialogButtonBox.RejectRole)
        close.clicked.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right, 3)
        self._reload(select)

    # list
    def _reload(self, select=None):
        self.specs = all_specs()
        self.list.blockSignals(True)
        self.list.clear()
        for s in self.specs:
            self.list.addItem(s["name"] + ("" if s.get("user") else "   (built-in)"))
        self.list.blockSignals(False)
        names = [s["name"] for s in self.specs]
        self.list.setCurrentRow(names.index(select) if select in names else 0)
        self._show(self.list.currentRow())

    def current(self):
        i = self.list.currentRow()
        return self.specs[i] if 0 <= i < len(self.specs) else None

    def _std_changed(self, *_):
        from mechflow_gui import routing, stdparts
        std = self.std.currentText()
        ty = routing.types_for(std)
        sched_items = (list(stdparts.ratings(ty["pipe"])) or ["Sch 40"]) if std == "ASME" \
            else ["EN 10220 wall"]
        for c, items in ((self.sched, sched_items),
                         (self.bend, routing.BENDS[std]),
                         (self.rating, stdparts.ratings(ty["flange"])),
                         (self.ends, routing.ENDS),
                         (self.start, routing.sizes_for(std))):
            keep = c.currentText()
            c.blockSignals(True)
            c.clear()
            c.addItems(items)
            if keep in items:
                c.setCurrentText(keep)
            c.blockSignals(False)
        asme = std == "ASME"
        self.sched.setEnabled(asme and self._editable)
        self.table.setVisible(asme)
        self.by_label.setVisible(asme)
        self.filler.setVisible(not asme)
        if asme:
            self._fill_table({})

    def _fill_table(self, by):
        from mechflow_gui import routing
        sizes = routing.sizes_for("ASME")
        self.table.setRowCount(len(sizes))
        for r, sz in enumerate(sizes):
            it = QtWidgets.QTableWidgetItem(sz)
            it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
            self.table.setItem(r, 0, it)
            c = QtWidgets.QComboBox()
            c.addItems(["", "Sch 10", "Sch 40", "Sch 80"])
            c.setCurrentText(by.get(sz, ""))
            c.setEnabled(self._editable)
            self.table.setCellWidget(r, 1, c)

    def _show(self, i):
        s = self.current()
        if s is None:
            return
        self._editable = bool(s.get("user"))
        self.name.setText(s["name"])
        self.std.blockSignals(True)
        self.std.setCurrentText(s["standard"])
        self.std.blockSignals(False)
        self._std_changed()
        self.material.setCurrentText(s["material"])
        for c, v in ((self.sched, s["schedule"]), (self.bend, s["bend"]), (self.rating, s["rating"]),
                     (self.ends, s["free_ends"]), (self.start, s["start_size"])):
            if v:
                c.setCurrentText(v)
        if s["standard"] == "ASME":
            self._fill_table(s.get("schedule_by_size") or {})
        for w in (self.name, self.std, self.material, self.bend, self.rating, self.ends, self.start):
            w.setEnabled(self._editable)
        self.sched.setEnabled(self._editable and s["standard"] == "ASME")
        self.b_save.setEnabled(self._editable)
        self.b_delete.setEnabled(self._editable)
        self.note.setText("A built-in spec: <b>Duplicate</b> it to make your own version."
                          if not self._editable else
                          "Your spec. <b>Save</b> and every route using it follows.")

    def gather(self):
        by = {}
        if self.std.currentText() == "ASME":
            for r in range(self.table.rowCount()):
                c = self.table.cellWidget(r, 1)
                if c is not None and c.currentText():
                    by[self.table.item(r, 0).text()] = c.currentText()
        return normalise({
            "name": self.name.text().strip(), "standard": self.std.currentText(),
            "material": self.material.currentText().strip(),
            "schedule": self.sched.currentText() if self.std.currentText() == "ASME" else "",
            "schedule_by_size": by, "bend": self.bend.currentText(),
            "rating": self.rating.currentText(), "free_ends": self.ends.currentText(),
            "start_size": self.start.currentText(), "user": True})

    # actions
    def _new(self):
        s = normalise({"name": self._unique("My pipe spec"), "user": True})
        save(s)
        self._reload(s["name"])

    def _dup(self):
        s = self.current()
        if s is None:
            return
        c = dict(s)
        c["name"] = self._unique(s["name"] + " (copy)")
        c["user"] = True
        save(c)
        self._reload(c["name"])

    def _unique(self, base):
        names = {s["name"] for s in all_specs()}
        n, k = base, 2
        while n in names:
            n = f"{base} {k}"
            k += 1
        return n

    def _delete(self):
        s = self.current()
        if s is None or not s.get("user"):
            return
        delete(s["name"])
        self._reload()

    def _save(self):
        old = self.current()
        s = self.gather()
        try:
            if old is not None and old.get("user") and old["name"] != s["name"]:
                if get(s["name"]) is not None:
                    raise ValueError(f"there's already a spec called {s['name']}")
                delete(old["name"])
            save(s)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Pipe Specs", f"Not saved: {e}")
            return False
        n = update_routes(s["name"])
        self._reload(s["name"])
        self.note.setText(f"Saved. {n} open route{'s' if n != 1 else ''} updated."
                          if n else "Saved.")
        return True


def edit_specs(select=None):
    d = SpecDialog(select=select)
    d.exec()
    return d
