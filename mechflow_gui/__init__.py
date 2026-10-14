# SPDX-License-Identifier: LGPL-2.1-or-later
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(PACKAGE_DIR)
ICON_DIR = os.path.join(ADDON_DIR, "Resources", "icons")


def icon_path(name):
    return os.path.join(ICON_DIR, name)


def edge_curve(e):
    """e.Curve, or None: some edges (e.g. on ellipsoids or imported parts)
    raise 'undefined curve type' instead of having a Curve."""
    try:
        return e.Curve
    except Exception:
        return None


def curve_name(e):
    """Type name of an edge's curve ('Circle', 'Line', ...; 'NoneType' if it
    has none)."""
    return type(edge_curve(e)).__name__


def widget_alive(w):
    """False once Qt has deleted the widget (e.g. its task panel closed)."""
    if w is None:
        return False
    try:
        try:
            import shiboken6 as sb
        except ImportError:
            import shiboken2 as sb
        return sb.isValid(w)
    except Exception:
        try:
            w.objectName()
            return True
        except Exception:
            return False
