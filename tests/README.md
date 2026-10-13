# MechFlow tests

GUI smoke tests that drive MechFlow inside a real FreeCAD 1.1 window (headless,
under Xvfb). Each test builds parts, uses a panel the way a user would (picks
faces, sets values, drags handles, OK / Cancel, re-edits), and logs the result:
volumes, placements, which buttons appear. The runner fails a test if it
crashes or hangs, raises a Python error, shows a feature error in a panel, or
pops up an unexpected dialog.

| Test | Covers |
|---|---|
| `t_tabs` | every CommandManager button resolves to a real command |
| `t_pat` | Linear / Circular Pattern, Mirror (create, edit, cancel) |
| `t_dress` | Shell (inward, faces clicked on the preview), Draft |
| `t_sweep` | Sweep, Cut-Sweep, Loft (3 profiles, ruled), Cut-Loft |
| `t_thin` | Thin Feature (open sketch, outside / inside / mid-plane), Material, Mass Properties |
| `t_handles` | Extrude depth arrow and Linear Pattern spacing arrow |
| `t_rel` | Sketch Relations panel and Under / Fully / Over Defined status |
| `t_tab` | Sketch tab and the Display/Delete Relations toggle |
| `t_cpat` | Circular Sketch Pattern: preview, instances, cancel, OK (fully defined, follows the seed), one undo, reverse / non-equal spacing |
| `t_lpat` | Linear Sketch Pattern: one direction and a grid, direction picked from a line, reverse, cancel, OK (fully defined, follows the seed), one undo |
| `t_weld` | Weldments: SHS frame with a middle post (miter and butt corners, square cut against a member's face), UKB portal frame on a vertical plane, edit, Cut List lengths and angles |
| `t_draw` | Make Drawing from Part (ISO and ANSI), title block, Sheet Format, PDF |
| `t_splash` | MechFlow splash screen: set, restore after a FreeCAD reinstall, restore FreeCAD's, leave other branding alone (writes `branding.xml` in the test FreeCAD) |
| `t_hole` | Hole Wizard sizes: ISO 273 clearance (close / normal / loose), counterbore, tapped, blind, re-edit |
| `t_toolbox` | Toolbox: hole recognition (clearance, tapped, counterbore, countersink), seating, lengths, washer + nut, labels, assembly (follows the part), Bill of Materials. Needs the Fasteners Workbench; skipped without it |
| `t_stdparts` | Toolbox standard parts: EN weld neck and blind flanges, ASME slip-on, 90 deg elbow and bearings placed on edges and sized to them, pipe at the origin, rating change, parts follow a moved part, BOM names, save and reopen. Runs with or without the Fasteners Workbench |
| `t_joint` | Flange joints: EN weld neck to weld neck and ASME slip-on to blind, with gasket, bolts and nuts, checked for clashes |
| `t_smart` | Smart Fasteners: clearance into tapped, counterbore, through bolt with nut, countersink, blind tapped, skips a blind clearance hole, in a document and in an assembly |
| `t_toolbox2` | Toolbox on Hole Wizard holes in a part (pick a face: all its holes) |
| `t_asm` | New Assembly, Insert Components, Mate (Concentric, Coincident, Distance, flip, cancel), Interference Detection |

## Running

```bash
# FreeCAD 1.1 for Linux: download the AppImage, then
./FreeCAD_1.1.x-Linux-x86_64-py311.AppImage --appimage-extract
FREECAD=$PWD/squashfs-root/usr/bin/freecad tests/run_tests.sh          # all
FREECAD=$PWD/squashfs-root/usr/bin/freecad tests/run_tests.sh t_draw   # one
```

Logs, screenshots and FreeCAD output go to `$MF_OUT` (default
`/tmp/mechflow-tests`). Each `<test>.log` shows the values checked, and the
expected figures are written next to them in the log.
