# MechFlow

**A SOLIDWORKS-style workflow for FreeCAD.** Free and open source.

MechFlow is a FreeCAD workbench for mechanical engineers who know SOLIDWORKS
and don't want to relearn everything to use free software. It sits on top of
FreeCAD 1.1: you keep FreeCAD's geometry kernel, solver and file format, and
get a layout, tool names and dialogs that work the way you're used to.

![Sketch with the Relations panel](docs/screenshots/sketch-relations.png)

> MechFlow is not affiliated with or endorsed by Dassault Systèmes.
> SOLIDWORKS is a trademark of Dassault Systèmes.

## What you get

### Interface
- **CommandManager** with Features, Sketch, Evaluate, Drawing and Assembly
  tabs. It switches tab to match what you're doing (sketching, a drawing, an
  assembly).
- SOLIDWORKS names throughout: *Extruded Boss/Base*, *Convert Entities*,
  *Smart Dimension*, *Mate*, and so on.
- Floating heads-up view bar (you can drag it), **Normal To** (Ctrl+8), S-key
  shortcut bar, confirmation corner in sketches, light theme.
- Front/Top/Right planes you can hover, click and right-click → Sketch.
- Optional **MechFlow splash screen** (*MechFlow → Use MechFlow Splash
  Screen*). FreeCAD reads its splash from a small `branding.xml` next to the
  FreeCAD program, so on Windows this asks once for administrator permission.
  Updating FreeCAD removes the file; MechFlow then offers to put it back.

### Part modelling
Each feature has its own panel, and you edit it again by double-clicking.
- **Extruded Boss/Base and Cut:** end conditions, Direction 2, draft, **Thin
  Feature**, and a drag arrow with a depth box in the 3D view.
- **Revolved** Boss/Cut, **Swept** and **Lofted** Boss/Cut.
- **Fillet** and **Chamfer** on many edges at once, **Shell**, **Draft**,
  **Hole Wizard** (ISO M3–M20: simple, counterbore, countersink, tapped;
  ISO 273 close / normal / loose clearance).
- **Linear Pattern** (with a spacing drag arrow), **Circular Pattern**,
  **Mirror**.
- **Reference Plane** (offset, at angle, mid plane, through a point, 3 points,
  normal to curve, tangent) with drag handles, and **Axis**.
- **Rollback**, **Suppress/Unsuppress**, **Section View** (up to three
  sections, drag handle), **Edit Material** and **Mass Properties**.

![Extrude with the depth drag arrow](docs/screenshots/extrude-drag.png)

### Sketching
- Under-defined geometry **blue**, fully defined **black**, over-defined
  **red**. The status bar shows *Under Defined (n DOF)* / *Fully Defined* /
  *Over Defined*.
- **Relations panel:** select entities and add the relations that fit them
  (Coincident, Horizontal, Midpoint, Tangent, Concentric, Collinear, ...).
  **Display/Delete Relations** lists the existing ones.
- Smart Dimension snaps to model edges without a Convert Entities step.
- **Linear and Circular Sketch Pattern** panels. Linear: Direction 1 and 2
  (angle or a picked line, spacing, instances, reverse) for rows and grids.
  Circular: centre (origin or a picked point), angle, instances, equal
  spacing, reverse. Both preview live, and the result is constrained so it
  follows the original.
- The Sketch tab has the full set: Centre Rectangle, 3 Point Arc, Sketch
  Chamfer, Extend/Split, Move/Copy/Scale, Repair Sketch.

### Weldments
- **Structural Member** (Weldments tab): pick sketch lines - from one sketch
  or several, so 3D frames work - and a section: UKB, UKC, PFC, equal angle,
  SHS / RHS (hot finished EN 10210 or cold formed EN 10219) or CHS, in UK
  sizes. Corners are cut with **End miter**, **End butt 1** or **End butt
  2**; a member that ends on the side of another (a cross rail, a post) is cut
  square to its face. Rotate or mirror the profile; double-click to edit.
- **Trim/Extend:** trim or extend one member group's free ends to other
  members (cut square to the face) or to any body (cut to its shape).
- **End Cap** on tube ends (outward or inward, inset) and **Gusset** plates
  between two member faces (legs, thickness, corner relief).
- **Cut List:** members grouped by section and length, with the cut angles,
  plus end caps and gussets, saved as a spreadsheet.

### Sheet metal
- A **Sheet Metal** tab with SOLIDWORKS names: Base Flange/Tab, Convert to
  Sheet Metal, Edge Flange, Sketched Bend, Hem, Extend Tab, Extruded Cut,
  Corner and Bend Relief, Rip, Insert Bends, Forming Tool.
- **Flatten** shows the flat pattern (click again to fold back) and **Save
  Flat as DXF** writes it for the laser.
- Uses the free **SheetMetal Workbench** (Addon Manager); MechFlow offers to
  install it the first time.

![Weldment frames](docs/screenshots/weldments.png)

### Drawings
- **Make Drawing from Part:** pick a sheet (ISO A4–A0, ANSI A–D) and get a
  standard 3 view plus an isometric, at a standard scale that fits the sheet.
  Projection is first-angle for ISO sheets and third-angle for ANSI.
- The title block fills in from the part: name, material, scale, author, date,
  sheet, and weight on ANSI sheets.
- The Drawing tab has Model/Projected/Section/Detail views, Smart Dimension,
  Note, Balloon, Centre Mark, Hatch, Surface Finish, Weld, Sheet Format and
  Save as PDF/DXF.

![Drawing from a part](docs/screenshots/drawing.png)

### Assemblies
- **New Assembly** and **Insert Components**.
- **Mate panel:** click a face, edge or point on two parts and MechFlow suggests
  the mate (Concentric, Coincident, Tangent). Other mates: Parallel,
  Perpendicular, Lock, Distance, Angle, Hinge, Slider. **Aligned/Anti-Aligned**
  flips the part.
- Mates show in a *Mates* folder with SOLIDWORKS names.
- **Toolbox** (standard parts), browsed by category and standard:
  - **Flanges:** EN 1092-1 Type 11 weld neck, Type 01 plate and Type 05
    blind (PN16, PN25, PN40, DN10-DN600); ASME B16.5 weld neck, slip-on and
    blind, RF (Class 150 and 300, NPS 1/2-12).
  - **Pipe:** EN 10220 (ISO 4200 sizes) and ASME B36.10M (Sch 10/40/80), any
    length.
  - **Pipe fittings:** ASME B16.9 90 and 45 deg long radius elbows, equal
    tees, concentric reducers and caps.
  - **Bearings:** ISO 15 deep groove ball bearings, 60xx, 62xx and 63xx.
  - Click a pipe end and a flange or fitting sizes itself to the pipe; click
    a shaft end or housing bore for a bearing. Change size or rating later in
    the properties.
  - **Flange joints:** click a flange's face to bolt another flange (or a
    blind) to it: it turns to face it, with a gasket (EN 1514-1 IBC / ASME
    B16.21) and the bolts and nuts from the flange table.
  - **Fasteners:** ISO, DIN, EN and ASME screws, nuts, washers, pins and
    more. Click hole edges (or a face, for all its holes) and each one sizes
    itself to its hole: a 9 mm clearance hole gets M8, a 5 mm tapped hole
    gets M6. Heads sit on the counterbore floor or in the countersink, the
    length is picked from the hole depth, and you can add a washer under the
    head and a washer and nut on the far side.
  - Parts are named by standard (*ISO 4762 M8x25<1>*,
    *EN 1092-1/11/B1/DN50/PN16<1>*), move with the part they're on, and work
    in parts and assemblies.

  ![Toolbox flanges, fittings and a bearing](docs/screenshots/stdparts.png)

  ![Toolbox fasteners in Hole Wizard holes](docs/screenshots/toolbox.png)

- **Smart Fasteners:** one click fills every empty clearance and tapped hole
  with the right screw, including holes that line up through several parts:
  into a tapped hole it engages up to 1.5 x d, right through it adds a washer
  and nut. Counterbores get socket head cap screws, countersinks countersunk
  screws; change the type per group before OK.
- **Bill of Materials** with ITEM NO. / PART NUMBER / DESCRIPTION / QTY.,
  counting identical parts and fasteners together.
- **Interference Detection** and Exploded View.

![Mate panel](docs/screenshots/mate.png)

## Where it differs from SOLIDWORKS

MechFlow changes how FreeCAD looks and behaves, but the geometry is still
FreeCAD's, so a few things work differently:

- Drawings are stored in the part's `.FCStd` file, not a separate drawing file.
  There is no *Model Items* import of sketch dimensions; you dimension the
  drawing with Smart Dimension.
- FreeCAD needs an assembly to be saved before it can link parts from other
  files. It prompts you when this happens.
- Editing an existing mate, and the gear, rack-and-pinion and screw mates, use
  FreeCAD's own joint dialog.
- Mid-plane and through-point reference planes keep their position when the
  model changes. Reopen them and press OK to update.
- Flange and fitting dimensions come from published EN 1092-1, ASME B16.5,
  B16.9, B36.10M and ISO 15 tables (sources are listed in
  `mechflow_gui/stdparts_data.py`). Check critical dimensions against the
  current standard before manufacture. Bearings are modelled to their
  boundary dimensions, with simplified rings and balls.
- The Toolbox's screws, nuts and washers use the free **Fasteners Workbench**. Install it
  from the Addon Manager (MechFlow offers to open it the first time). A
  fastener is attached to its hole edge rather than held by mates, and only
  metric (ISO 273) holes are sized automatically; for inch fasteners pick the
  size yourself.
- Weldment members follow straight sketch lines (no curved members yet).
  Section dimensions come from British Steel datasheets and EN 10056-1 /
  10210 / 10219 (see `mechflow_gui/steel_data.py`).
- MechFlow is tested on **FreeCAD 1.1**. Older versions are not supported.

## Install

**Addon Manager** (once listed): *Tools → Addon Manager*, search for
**MechFlow**, then Install.

**Manual:** copy this folder into FreeCAD's `Mod` folder as `MechFlow`:

| OS | Mod folder (FreeCAD 1.1) |
|---|---|
| Windows | `%APPDATA%\FreeCAD\v1-1\Mod\` |
| macOS | `~/Library/Application Support/FreeCAD/v1-1/Mod/` |
| Linux | `~/.local/share/FreeCAD/v1-1/Mod/` |

Restart FreeCAD and choose **MechFlow** from the workbench list. The first
time, MechFlow sets itself as the workbench FreeCAD opens in (you can change
this under *Edit → Preferences → General*). For SOLIDWORKS-style mouse navigation,
apply the preference pack: *Edit → Preferences → General → Preference packs
→ MechFlow → Apply*.

## Testing

`tests/` has smoke tests that drive the real FreeCAD GUI on Linux (headless,
under Xvfb). They build parts, use each panel the way a user would, and check
the resulting geometry. See [tests/README.md](tests/README.md).

## Contributing

Issues and pull requests are welcome, especially for tools that still behave
like FreeCAD rather than SOLIDWORKS. Please run the tests before sending a
change. Two rules of the codebase:

- Don't install Qt event filters on FreeCAD's own widgets. Use timers,
  `Gui.Selection` observers and document observers instead (event filters have
  crashed FreeCAD).
- Never keep references to FreeCAD's tree items. FreeCAD rebuilds the tree,
  so look the items up again each time.

## Licence

LGPL-2.1-or-later, the same as FreeCAD. See [LICENSE](LICENSE).
