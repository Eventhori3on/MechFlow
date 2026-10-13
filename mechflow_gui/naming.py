# SPDX-License-Identifier: LGPL-2.1-or-later
"""Give new features SOLIDWORKS-style names: Boss-Extrude1, Cut-Extrude1, Sketch1...

Only objects whose label is still FreeCAD's default (label == internal name)
are renamed, so anything you have renamed yourself is left alone. Documents
being opened from disk are never touched.

Turn off with:
    App.ParamGet("User parameter:BaseApp/Preferences/Mod/MechFlow").SetBool("FeatureNames", False)
"""

import re

import FreeCAD as App

try:
    from PySide6 import QtCore
except ImportError:
    from PySide2 import QtCore

PARAMS = "User parameter:BaseApp/Preferences/Mod/MechFlow"

NAMES = {
    "PartDesign::Pad": "Boss-Extrude",
    "PartDesign::Pocket": "Cut-Extrude",
    "PartDesign::Revolution": "Revolve",
    "PartDesign::Groove": "Cut-Revolve",
    "PartDesign::AdditivePipe": "Sweep",
    "PartDesign::SubtractivePipe": "Cut-Sweep",
    "PartDesign::AdditiveLoft": "Loft",
    "PartDesign::SubtractiveLoft": "Cut-Loft",
    "PartDesign::Fillet": "Fillet",
    "PartDesign::Chamfer": "Chamfer",
    "PartDesign::Draft": "Draft",
    "PartDesign::Thickness": "Shell",
    "PartDesign::Hole": "Hole",
    "PartDesign::LinearPattern": "LPattern",
    "PartDesign::PolarPattern": "CirPattern",
    "PartDesign::Mirrored": "Mirror",
    "PartDesign::Plane": "Plane",
    "PartDesign::Line": "Axis",
    "PartDesign::Point": "Point",
    "Sketcher::SketchObject": "Sketch",
}


def _enabled():
    return App.ParamGet(PARAMS).GetBool("FeatureNames", True)


def _next_label(doc, prefix):
    pattern = re.compile(re.escape(prefix) + r"(\d+)$")
    used = [int(m.group(1)) for o in doc.Objects
            if (m := pattern.match(o.Label))]
    return f"{prefix}{max(used, default=0) + 1}"


def _rename(doc_name, obj_name):
    doc = App.listDocuments().get(doc_name)
    obj = doc.getObject(obj_name) if doc else None
    if obj is None or obj.Label != obj.Name:
        return
    prefix = NAMES.get(obj.TypeId)
    if prefix:
        obj.Label = _next_label(doc, prefix)


# FreeCAD is Z-up, so these match what the view cube shows:
# sketching on "Front Plane" faces you in the Front view, and so on.
ORIGIN_PLANES = {
    "XZ_Plane": "Front Plane",
    "XY_Plane": "Top Plane",
    "YZ_Plane": "Right Plane",
}


# Remember which label each document's body was given, so it can follow
# the part name when the file is saved under a new name.
_body_labels = {}


def _bodies(doc):
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]


def name_body_after_part(doc):
    """SOLIDWORKS shows the part name at the top of the tree: give a
    single-body part's Body the document's name."""
    bodies = _bodies(doc)
    if len(bodies) != 1:
        return
    body = bodies[0]
    previous = _body_labels.get(doc.Name)
    if body.Label.startswith("Body") or body.Label == previous:
        body.Label = doc.Label
        _body_labels[doc.Name] = body.Label


def _setup_body(doc_name, body_name, tries=3, new_body=True):
    """Rename a new body's origin planes and expand Origin in the tree."""
    doc = App.listDocuments().get(doc_name)
    body = doc.getObject(body_name) if doc else None
    if body is not None:
        try:
            name_body_after_part(doc)
        except Exception:
            pass
    origin = getattr(body, "Origin", None) if body else None
    feats = getattr(origin, "OriginFeatures", []) if origin else []
    if not feats:
        if tries > 0:  # origin not built yet - try again shortly
            QtCore.QTimer.singleShot(
                50, lambda: _setup_body(doc_name, body_name, tries - 1, new_body))
        return

    for f in feats:
        role = getattr(f, "Role", "") or ""
        for key, label in ORIGIN_PLANES.items():
            short = key.split("_")[0]                     # "XY"
            matches = f.Name.startswith(key) or role.startswith(key) \
                or role.lower().startswith(short.lower() + "_") \
                or role.lower().startswith(short.lower() + "-")
            # Only rename while the label is still FreeCAD's default.
            default = f.Label.replace("-", "_").lower().startswith(key.lower())
            if matches and default:
                f.Label = label
                if new_body:
                    try:
                        f.ViewObject.Visibility = False   # SOLIDWORKS: planes start hidden
                    except Exception:
                        pass
        # FreeCAD 1.1's origin point is labelled "Origin001" (the folder is
        # already "Origin"); give it a clearer name.
        if f.TypeId == "App::Point" and f.Label.startswith("Origin") \
                and f.Label != "Origin Point" and f is not origin:
            try:
                f.Label = "Origin Point"
            except Exception:
                pass

    try:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(doc_name)
        gdoc.toggleTreeItem(body, 2)    # 2 = expand
        gdoc.toggleTreeItem(origin, 2)
    except Exception:
        pass


class _Observer:
    def __init__(self):
        self._restoring = set()

    def slotStartRestoreDocument(self, doc):
        self._restoring.add(doc.Name)

    def slotFinishRestoreDocument(self, doc):
        self._restoring.discard(doc.Name)

    def slotChangedDocument(self, doc, prop):
        # Saving as "Bracket.FCStd" renames the document -> rename the body too.
        if prop == "Label" and _enabled() and doc.Name not in self._restoring:
            QtCore.QTimer.singleShot(
                0, lambda d=doc.Name: _follow_part_name(d))

    def slotCreatedObject(self, obj):
        if not _enabled():
            return
        doc = obj.Document
        if doc.Name in self._restoring:
            return
        if obj.TypeId == "PartDesign::Body":
            QtCore.QTimer.singleShot(
                0, lambda d=doc.Name, n=obj.Name: _setup_body(d, n))
            return
        if obj.TypeId not in NAMES:
            return
        # Wait until FreeCAD has finished creating the object.
        QtCore.QTimer.singleShot(
            0, lambda d=doc.Name, n=obj.Name: _rename(d, n))


def _follow_part_name(doc_name):
    doc = App.listDocuments().get(doc_name)
    if doc is not None:
        name_body_after_part(doc)


_observer = None


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
