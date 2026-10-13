# SPDX-License-Identifier: LGPL-2.1-or-later
import os

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(PACKAGE_DIR)
ICON_DIR = os.path.join(ADDON_DIR, "Resources", "icons")


def icon_path(name):
    return os.path.join(ICON_DIR, name)
