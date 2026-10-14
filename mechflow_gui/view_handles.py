# SPDX-License-Identifier: LGPL-2.1-or-later
"""Drag handles and editable callouts in the 3D view (SOLIDWORKS-style).

Arrow  - drag along a direction (distance)
Disc   - drag round a hinge line (angle)
ViewBox - a small number box that floats next to a point in the 3D view
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets


def scene():
    try:
        from pivy import coin  # noqa: F401  (FreeCAD needs pivy loaded first)
        return Gui.ActiveDocument.ActiveView.getSceneGraph()
    except Exception:
        return None


def mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


class ViewBox(QtWidgets.QDoubleSpinBox):
    """Number box floating in the 3D view."""

    def __init__(self, suffix, lo, hi, dec=2):
        super().__init__(mdi())
        self.setObjectName("MechFlow_ViewBox")
        self.setRange(lo, hi)
        self.setDecimals(dec)
        self.setSuffix(suffix)
        self.setKeyboardTracking(False)
        self.setFixedWidth(100)
        self.setStyleSheet(
            "#MechFlow_ViewBox { background: rgba(255,255,255,235); color: #000;"
            " border: 1px solid #569de5; border-radius: 3px; padding: 1px 3px; }")
        self.hide()

    def set_quiet(self, v):
        if abs(self.value() - v) > 1e-9:
            self.blockSignals(True)
            self.setValue(v)
            self.blockSignals(False)

    def place(self, world_pt, dx=18, dy=-12):
        """Move next to a 3D point (call regularly: the camera moves)."""
        area = self.parentWidget()
        if area is None:
            return
        try:
            view = Gui.ActiveDocument.ActiveView
            fn = getattr(view, "getPointOnViewport", None) or view.getPointOnScreen
            x, y = fn(world_pt)
            sub = area.activeSubWindow()
            w = sub.widget() if sub is not None else area
            h = view.getSize()[1] if hasattr(view, "getSize") else w.height()
            pt = w.mapTo(area, QtCore.QPoint(int(x) + dx, int(h - y) + dy))
            pt.setX(max(0, min(pt.x(), area.width() - self.width())))
            pt.setY(max(0, min(pt.y(), area.height() - self.height())))
            self.move(pt)
        except Exception:
            self.move(12, 40)
        if not self.isVisible():
            self.show()
        self.raise_()

    def remove(self):
        try:
            self.hide()
            self.setParent(None)
            self.deleteLater()
        except Exception:
            pass


def _on_top(root):
    """Draw this handle over the model, so it can't hide inside the part."""
    try:
        from pivy import coin
        db = coin.SoDepthBuffer()
        db.test = False
        db.write = False
        root.addChild(db)
    except Exception:
        pass


class _Handle:
    def __init__(self):
        self.sg = None
        self.root = None

    def _attach(self, root):
        self.sg = scene()
        self.root = root
        if self.sg is not None:
            self.sg.addChild(root)

    def remove(self):
        try:
            if self.sg is not None and self.root is not None:
                self.sg.removeChild(self.root)
        except Exception:
            pass
        self.sg = self.root = None


class Arrow(_Handle):
    """Drag along `direction` from `origin`; value() is the signed distance."""

    def __init__(self, origin, direction, value, scale):
        super().__init__()
        from pivy import coin
        self.origin = App.Vector(origin)
        self.dir = App.Vector(direction).normalize()
        self.scale = scale
        root = coin.SoSeparator()
        _on_top(root)
        tf = coin.SoTransform()
        tf.translation = (origin.x, origin.y, origin.z)
        self._tf = tf
        q = App.Rotation(App.Vector(1, 0, 0), self.dir).Q
        tf.rotation.setValue(q[0], q[1], q[2], q[3])
        root.addChild(tf)
        sc = coin.SoScale()
        sc.scaleFactor = (scale, scale, scale)
        root.addChild(sc)
        self.dragger = coin.SoTranslate1Dragger()
        root.addChild(self.dragger)
        self._attach(root)
        self.set_value(value)

    def value(self):
        return self.dragger.translation.getValue()[0] * self.scale

    def set_value(self, d):
        self.dragger.translation.setValue(d / self.scale, 0, 0)
        self.last = d

    def moved(self):
        """New value if the user dragged it since last time, else None."""
        try:
            d = self.value()
        except Exception:
            return None
        if abs(d - self.last) > 1e-6:
            self.last = d
            return d
        return None

    def tip(self):
        return self.origin + self.dir * self.last

    def move_origin(self, p):
        """Shift the whole arrow (its value stays)."""
        p = App.Vector(p)
        if (p - self.origin).Length < 1e-6:
            return
        self.origin = p
        self._tf.translation = (p.x, p.y, p.z)


def _ring(rgb, alpha, r0=0.82, r1=1.0, n=72):
    """A flat ring band in the XY plane (radius r0..r1)."""
    from pivy import coin
    sep = coin.SoSeparator()
    mat = coin.SoMaterial()
    mat.diffuseColor = rgb
    mat.emissiveColor = tuple(c * 0.6 for c in rgb)
    mat.transparency = alpha
    sep.addChild(mat)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
    sep.addChild(hints)
    pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        pts.append((r0 * math.cos(a), r0 * math.sin(a), 0.0))
        pts.append((r1 * math.cos(a), r1 * math.sin(a), 0.0))
    co = coin.SoCoordinate3()
    co.point.setValues(0, len(pts), pts)
    sep.addChild(co)
    idx = []
    for i in range(n):
        a, b = 2 * i, 2 * ((i + 1) % n)
        idx += [a, b, b + 1, a + 1, -1]
    fs = coin.SoIndexedFaceSet()
    fs.coordIndex.setValues(0, len(idx), idx)
    sep.addChild(fs)
    return sep


def _ring_parts(dragger):
    """Give a SoRotateDiscDragger a coloured ring band instead of its whole-disc
    geometry: only the band can be grabbed, so handles inside the circle (a
    slide arrow) stay reachable, and it shows up on light backgrounds."""
    try:
        dragger.setPart("rotator", _ring((0.95, 0.55, 0.1), 0.25))
        dragger.setPart("rotatorActive", _ring((1.0, 0.75, 0.2), 0.0))
    except Exception:
        pass


class Disc(_Handle):
    """Drag round the line through `centre` along `axis`; value() in degrees."""

    def __init__(self, centre, axis, angle, scale):
        super().__init__()
        from pivy import coin
        self.centre = App.Vector(centre)
        self.axis = App.Vector(axis).normalize()
        root = coin.SoSeparator()
        _on_top(root)
        tf = coin.SoTransform()
        tf.translation = (centre.x, centre.y, centre.z)
        q = App.Rotation(App.Vector(0, 0, 1), self.axis).Q
        tf.rotation.setValue(q[0], q[1], q[2], q[3])
        root.addChild(tf)
        sc = coin.SoScale()
        sc.scaleFactor = (scale, scale, scale)
        root.addChild(sc)
        self.dragger = coin.SoRotateDiscDragger()
        _ring_parts(self.dragger)
        root.addChild(self.dragger)
        self.scale = scale
        self._attach(root)
        self.set_value(angle)

    def value(self):
        r = self.dragger.rotation.getValue()
        q = r.getValue()
        if len(q) == 4:
            a = math.degrees(2.0 * math.atan2(q[2], q[3]))
        else:                                    # (axis, radians)
            ax, rad = q
            a = math.degrees(rad) * (1 if ax[2] >= 0 else -1)
        while a > 180.0:
            a -= 360.0
        while a <= -180.0:
            a += 360.0
        return a

    def set_value(self, deg):
        from pivy import coin
        self.dragger.rotation.setValue(coin.SbVec3f(0, 0, 1), math.radians(deg))
        self.last = self.value()

    def moved(self):
        try:
            a = self.value()
        except Exception:
            return None
        if abs(a - self.last) > 1e-4:
            self.last = a
            return a
        return None

    def label_point(self):
        # Off to one side of the hinge, so the box doesn't hide the disc.
        perp = self.axis.cross(App.Vector(0, 0, 1))
        if perp.Length < 1e-6:
            perp = self.axis.cross(App.Vector(1, 0, 0))
        return self.centre + perp.normalize() * self.scale * 1.3


class ArrowControl:
    """A drag arrow plus a floating number box, tied to a spin box in a panel.

    show(origin, direction, scale) puts the arrow up (or just syncs its value
    if it's already there); the arrow's length is spin.value() / factor (e.g.
    factor 2 for a mid-plane depth, where the arrow shows one half). Dragging
    or typing in the 3D box updates the spin box quietly, then calls on_change
    once the mouse settles, so the model rebuilds without stutter.
    """

    def __init__(self, spin, on_change, factor=1.0):
        self.spin = spin
        self.on_change = on_change
        self.factor = factor
        self.arrow = None
        self.box = None
        self._key = None
        self._settle = QtCore.QTimer()
        self._settle.setSingleShot(True)
        self._settle.setInterval(120)
        self._settle.timeout.connect(self._settled)
        self._ticker = QtCore.QTimer()
        self._ticker.setInterval(60)
        self._ticker.timeout.connect(self._tick)

    def show(self, origin, direction, scale, factor=None):
        if factor is not None:
            self.factor = factor
        key = (tuple(round(x, 5) for x in origin), tuple(round(x, 5) for x in direction),
               round(scale, 5), self.factor)
        length = self.spin.value() / self.factor
        if key == self._key and self.arrow is not None:
            if abs(self.arrow.last - length) > 1e-6:
                self.arrow.set_value(length)
            self.box.set_quiet(self.spin.value())
            return
        self.hide()
        self._key = key
        self.arrow = Arrow(origin, direction, length, scale)
        self.box = ViewBox(self.spin.suffix(), self.spin.minimum(), self.spin.maximum(),
                           self.spin.decimals())
        self.box.set_quiet(self.spin.value())
        self.box.valueChanged.connect(self._typed)
        self._ticker.start()

    def hide(self):
        self._ticker.stop()
        for h in (self.arrow, self.box):
            if h is not None:
                h.remove()
        self.arrow = self.box = None
        self._key = None

    def close(self):
        self._settle.stop()
        self.hide()

    def _typed(self, v):
        self.spin.setValue(v)           # the panel reacts as if typed there

    def _tick(self):
        try:
            if self.arrow is None:
                return
            d = self.arrow.moved()
            if d is not None:
                v = d * self.factor
                lo = self.spin.minimum()
                if v < lo:
                    v = lo
                    self.arrow.set_value(lo / self.factor)
                self.spin.blockSignals(True)
                self.spin.setValue(v)
                self.spin.blockSignals(False)
                self.box.set_quiet(v)
                self._settle.start()
            self.box.place(self.arrow.tip())
        except Exception:
            pass

    def _settled(self):
        try:
            self.on_change()
        except Exception:
            pass
