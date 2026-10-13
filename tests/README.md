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
| `t_draw` | Make Drawing from Part (ISO and ANSI), title block, Sheet Format, PDF |
| `t_splash` | MechFlow splash screen: set, restore after a FreeCAD reinstall, restore FreeCAD's, leave other branding alone (writes `branding.xml` in the test FreeCAD) |
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
