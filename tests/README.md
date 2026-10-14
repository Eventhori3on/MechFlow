# MechFlow tests

GUI smoke tests that drive MechFlow inside a real FreeCAD 1.1 window (on
Linux headless under Xvfb, or inside a running FreeCAD on any OS). Each test builds parts, uses a panel the way a user would (picks
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
| `t_weld2` | Trim/Extend posts to a frame, End Caps, Gusset (no overlaps), cut list with plates, save and reopen |
| `t_sm` | Sheet Metal tab: Base Flange from an open sketch, Edge Flange, Flatten and fold back, Save Flat as DXF. Needs the SheetMetal Workbench; skipped without it |
| `t_draw` | Make Drawing from Part (ISO and ANSI), title block, Sheet Format, PDF |
| `t_splash` | MechFlow splash screen: set, restore after a FreeCAD reinstall, restore FreeCAD's, leave other branding alone (writes `branding.xml` in the test FreeCAD) |
| `t_hole` | Hole Wizard sizes: ISO 273 clearance (close / normal / loose), counterbore, tapped, blind, re-edit |
| `t_toolbox` | Toolbox: hole recognition (clearance, tapped, counterbore, countersink), seating, lengths, washer + nut, labels, assembly (follows the part), Bill of Materials. Needs the Fasteners Workbench; skipped without it |
| `t_stdparts` | Toolbox standard parts: EN weld neck and blind flanges, ASME slip-on, 90 deg elbow and bearings placed on edges and sized to them, pipe at the origin, rating change, parts follow a moved part, BOM names, save and reopen. Runs with or without the Fasteners Workbench |
| `t_joint` | Flange joints: EN weld neck to weld neck and ASME slip-on to blind, with gasket, bolts and nuts, checked for clashes |
| `t_smart` | Smart Fasteners: clearance into tapped, counterbore, through bolt with nut, countersink, blind tapped, skips a blind clearance hole, in a document and in an assembly |
| `t_toolbox2` | Toolbox on Hole Wizard holes in a part (pick a face: all its holes) |
| `t_asm` | New Assembly, Insert Components, Mate (Concentric, Coincident, Distance, flip, cancel), Interference Detection |
| `t_mass` | Mass Properties of parts, weldments and assemblies |
| `t_nozzle` | Nozzle on a tank wall: flanged stub, follows edits, flange joint on it |
| `t_pack` | Make Drawing from Assembly: BOM table, balloons, dimensioned part sheets, Save All as PDF |
| `t_route` | Route Pipe: pipe, elbows, tee and flanges along sketches, rebuild after a sketch edit, save and reopen |
| `t_config` | Configurations and the design table |
| `t_stress` | Stress Check: cantilever against hand calculation (deflection and stress), study kept with the part |
| `t_supplier` | Supplier Pack: PDFs incl. exploded view, STEP, DXF flat of a plate (holes), BOM, zip; Exploded View on and off |
| `t_sketch3d` | 3D Sketch: starts snapped on a flange, mouse lines lock to X and round to 10 mm, typed lines, length edit moves later lines, branch, rename; Route Pipe follows it and rebuilds on edit |
| `t_valves` | Valves & Instruments: ball, gate, butterfly valves and a gauge on a route; pipe splits, flanges and bolts, ring drag to 90°, slide, refusal when there's no room, reopen |
| `t_author` | Author Component: a turned strainer (2 ports) and a level switch (1 port) saved to the routing library, then placed and bolted on a route |
| `t_sizes` | Pipe specs and size changes: spec material on parts and in the BOM, a reducer part way along a run and after an elbow, two reducers for a big step, Change Pipe Size from a selected pipe, a DN100 x DN80 library valve changing the size after it (refused turned round), editing a spec updates the route |

## Running

```bash
# FreeCAD 1.1 for Linux: download the AppImage, then
./FreeCAD_1.1.x-Linux-x86_64-py311.AppImage --appimage-extract
FREECAD=$PWD/squashfs-root/usr/bin/freecad tests/run_tests.sh          # all
FREECAD=$PWD/squashfs-root/usr/bin/freecad tests/run_tests.sh t_draw   # one
```

On Windows or macOS, run them inside FreeCAD: open *View → Panels → Python
console* and enter

```python
exec(open(App.getUserAppDataDir() + "Mod/MechFlow/tests/run_in_freecad.py").read())
```

(or set `MF_ONLY = ["t_stress", "t_pack"]` first to run some). They run one
after another in that window and close the documents they make; results go to
`MechFlow Test Results` in FreeCAD's user folder (`summary.txt`, a log per
test, screenshots).

Logs, screenshots and FreeCAD output go to `$MF_OUT` (default
`/tmp/mechflow-tests`). Each `<test>.log` shows the values checked, and the
expected figures are written next to them in the log.
