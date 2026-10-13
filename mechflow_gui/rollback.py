# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-style rollback.

FreeCAD's equivalent of the rollback bar is the Body's Tip: features after the
tip are kept but not applied. MechFlow adds:
- right-click a feature -> Roll Back to Here (that feature becomes the end),
- Roll to End (back to the last feature),
- rolled-back features shown greyed in the tree,
- a banner in the 3D view while rolled back, with a Roll to End button.
New features made while rolled back are inserted at the rollback point, as in
SOLIDWORKS.
"""

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtGui, QtWidgets

_banner = None
_greyed = set()  # labels MechFlow has greyed / struck out in the tree
# Never keep tree items themselves: FreeCAD rebuilds the tree and deletes them,
# and touching a deleted item crashes FreeCAD. Look them up fresh each time.
_last_state = None


def _body_of(obj):
    for o in getattr(obj, "InList", []):
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def _solid_features(body):
    return [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature")]


def last_feature(body):
    feats = _solid_features(body)
    return feats[-1] if feats else None


def rolled_back(body):
    tip = body.Tip
    last = last_feature(body)
    return tip is not None and last is not None and tip != last


def _set_tip(body, feature):
    old = body.Tip
    doc = body.Document
    doc.openTransaction("Roll back" if feature != last_feature(body) else "Roll to end")
    try:
        body.Tip = feature
        doc.recompute()
    finally:
        doc.commitTransaction()
    for o, vis in ((old, False), (feature, True)):
        try:
            if o is not None:
                o.ViewObject.Visibility = vis
        except Exception:
            pass


def roll_back_to(feature):
    body = _body_of(feature)
    if body is None:
        return
    target = feature
    if not feature.isDerivedFrom("PartDesign::Feature"):
        # A sketch or datum: roll back to the last solid feature before it.
        group = list(body.Group)
        target = None
        for o in reversed(group[:group.index(feature)]):
            if o.isDerivedFrom("PartDesign::Feature"):
                target = o
                break
        if target is None:
            return
    _set_tip(body, target)


def roll_to_end(body=None):
    if body is None:
        body = _active_body()
    if body is None:
        return
    last = last_feature(body)
    if last is not None and body.Tip != last:
        _set_tip(body, last)


def _active_body():
    from mechflow_gui import pick_solid
    return pick_solid.active_body()


# ------------------------------------------------------------ display

def _mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


def _items(labels):
    flags = QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        for label in labels:
            try:
                yield from tree.findItems(label, flags, 0)
            except Exception:
                pass


def _ungrey():
    # Undo only what MechFlow changed (colour, italic, strike-through).
    labels = list(_greyed)
    _greyed.clear()
    for item in _items(labels):
        try:
            item.setData(0, QtCore.Qt.ForegroundRole, None)
            f = item.font(0)
            f.setStrikeOut(False)
            f.setItalic(False)
            item.setFont(0, f)
        except RuntimeError:
            pass


def _style(labels, italic=False, strike=False):
    grey = QtGui.QBrush(QtGui.QColor(140, 140, 140))
    for item in _items(labels):
        try:
            item.setForeground(0, grey)
            f = item.font(0)
            if italic:
                f.setItalic(True)
            if strike:
                f.setStrikeOut(True)
            item.setFont(0, f)
        except RuntimeError:
            pass
    _greyed.update(labels)


def _grey(labels):
    _style(labels, italic=True)


def _show_banner(text):
    global _banner
    mdi = _mdi()
    if mdi is None:
        return
    if _banner is None:
        _banner = QtWidgets.QFrame(mdi)
        _banner.setObjectName("MechFlow_Rollback")
        _banner.setStyleSheet(
            "#MechFlow_Rollback { background: rgba(200, 140, 40, 220); border-radius: 5px; }"
            "#MechFlow_Rollback QLabel { color: black; font-weight: 600; }")
        row = QtWidgets.QHBoxLayout(_banner)
        row.setContentsMargins(10, 4, 4, 4)
        _banner.label = QtWidgets.QLabel()
        row.addWidget(_banner.label)
        btn = QtWidgets.QPushButton("Roll to End")
        btn.clicked.connect(lambda: roll_to_end())
        row.addWidget(btn)
    _banner.label.setText(text)
    _banner.adjustSize()
    _banner.move(12, max(0, mdi.height() - _banner.height() - 40))
    _banner.show()
    _banner.raise_()


def _hide_banner():
    if _banner is not None:
        _banner.hide()


# ------------------------------------------------------------ suppression

def can_suppress(feature):
    return feature is not None and "Suppressed" in getattr(feature, "PropertiesList", [])


def is_suppressed(feature):
    return can_suppress(feature) and bool(feature.Suppressed)


def set_suppressed(feature, on):
    """SOLIDWORKS Suppress / Unsuppress: rebuild the part without the feature."""
    if not can_suppress(feature):
        QtWidgets.QMessageBox.information(
            Gui.getMainWindow(), "Suppress",
            "This version of FreeCAD can't suppress features.\n\n"
            "Use Roll Back to Here instead to see the part without later features.")
        return False
    doc = feature.Document
    doc.openTransaction(("Suppress " if on else "Unsuppress ") + feature.Label)
    try:
        feature.Suppressed = on
        doc.recompute()
    finally:
        doc.commitTransaction()
    # Keep the finished part on screen.
    body = _body_of(feature)
    try:
        if body is not None and body.Tip is not None:
            body.Tip.ViewObject.Visibility = True
    except Exception:
        pass
    return True


def _suppressed_labels(body):
    return [o.Label for o in body.Group if is_suppressed(o)]


def _strike(labels):
    _style(labels, strike=True)


def refresh():
    """Called a few times a second while MechFlow is active."""
    global _last_state
    body = _active_body()
    if body is None:
        if _last_state is not None:
            _ungrey()
            _hide_banner()
            _last_state = None
        return
    suppressed = _suppressed_labels(body)
    back = rolled_back(body)
    labels = []
    if back:
        group = list(body.Group)
        tip = body.Tip
        labels = [o.Label for o in group[group.index(tip) + 1:]] if tip in group else []
    state = (body.Name, getattr(body.Tip, "Name", None), tuple(labels), tuple(suppressed))
    if state != _last_state:
        _ungrey()
        _grey(labels)
        _strike(suppressed)
        _last_state = state
    if back:
        _show_banner(f"Rolled back to {body.Tip.Label}")
    else:
        _hide_banner()


def clear():
    global _last_state
    _ungrey()
    _hide_banner()
    _last_state = None
