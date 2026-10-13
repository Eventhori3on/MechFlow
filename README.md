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
  **Hole Wizard** (ISO M3–M20: simple, counterbore, countersink, tapped).
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
- The Sketch tab has the full set: Centre Rectangle, 3 Point Arc, Sketch
  Chamfer, Extend/Split, Linear/Circular Sketch Pattern, Move/Copy/Scale,
  Repair Sketch.

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
- **Interference Detection**, Exploded View, Bill of Materials.

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
