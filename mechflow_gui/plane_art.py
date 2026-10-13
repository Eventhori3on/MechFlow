# SPDX-License-Identifier: LGPL-2.1-or-later
"""SOLIDWORKS-look plane graphics: thin blue outline, corner ticks, label.

Display-only Coin nodes (can't be clicked, never saved to the file).
"""

SW_BLUE = (0.29, 0.52, 0.86)
SW_ORANGE = (1.0, 0.55, 0.15)


def build(rotation, base, size, label, rgb=SW_BLUE, fill_transparency=0.92):
    """A plane drawn in its local XY, `size` across, centred on `base`."""
    from pivy import coin
    h = size / 2.0
    root = coin.SoSeparator()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    root.addChild(pick)

    tf = coin.SoTransform()
    tf.translation = (base.x, base.y, base.z)
    q = rotation.Q
    tf.rotation.setValue(q[0], q[1], q[2], q[3])
    root.addChild(tf)

    pts = [[-h, -h, 0], [h, -h, 0], [h, h, 0], [-h, h, 0]]

    if fill_transparency < 1.0:
        fill = coin.SoSeparator()
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING
        fill.addChild(hints)
        m = coin.SoMaterial()
        m.diffuseColor = rgb
        m.transparency = fill_transparency
        fill.addChild(m)
        c = coin.SoCoordinate3()
        c.point.setValues(0, 4, pts)
        fill.addChild(c)
        fs = coin.SoFaceSet()
        fs.numVertices.setValue(4)
        fill.addChild(fs)
        root.addChild(fill)

    lines = coin.SoSeparator()
    col = coin.SoBaseColor()
    col.rgb = rgb
    lines.addChild(col)
    style = coin.SoDrawStyle()
    style.lineWidth = 1.5
    lines.addChild(style)
    c = coin.SoCoordinate3()
    c.point.setValues(0, 5, pts + [pts[0]])
    lines.addChild(c)
    ls = coin.SoLineSet()
    ls.numVertices.setValue(5)
    lines.addChild(ls)
    # small handle dots at corners and mid-edges, as SOLIDWORKS draws them
    dots = coin.SoSeparator()
    ds = coin.SoDrawStyle()
    ds.pointSize = 4
    dots.addChild(ds)
    dc = coin.SoCoordinate3()
    marks = pts + [[0, -h, 0], [h, 0, 0], [0, h, 0], [-h, 0, 0]]
    dc.point.setValues(0, len(marks), marks)
    dots.addChild(dc)
    ps = coin.SoPointSet()
    dots.addChild(ps)
    lines.addChild(dots)
    root.addChild(lines)

    if label:
        txt = coin.SoSeparator()
        tcol = coin.SoBaseColor()
        tcol.rgb = rgb
        txt.addChild(tcol)
        tt = coin.SoTranslation()
        tt.translation = (-h + size * 0.03, h - size * 0.06, 0)
        txt.addChild(tt)
        font = coin.SoFont()
        font.size = 13
        font.name = "Segoe UI:Italic"
        txt.addChild(font)
        t = coin.SoText2()
        t.string = label
        txt.addChild(t)
        root.addChild(txt)
    return root


def scene():
    import FreeCADGui as Gui
    try:
        from pivy import coin  # noqa: F401  (FreeCAD needs pivy loaded first)
        return Gui.ActiveDocument.ActiveView.getSceneGraph()
    except Exception:
        return None
