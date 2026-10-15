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
  ISO 273 close / normal / loose clearance; Blind, **Up To Next** - through
  the first wall only, for tanks and hollow parts - or Through All).
- **Nozzle:** click a tank or vessel wall, flat or curved, pick the pipe
  (EN 10220 or ASME B36.10M) and its standout: the stub is shaped to meet the
  shell, the wall it sits on is bored (only that wall), and a weld neck or
  plate flange can go straight on the end. Position it exactly by typing X,
  Y, Z; point it square to the face or along an axis.
- **Linear Pattern** (with a spacing drag arrow), **Circular Pattern**,
  **Mirror**.
- **Reference Plane** (offset, at angle, mid plane, through a point, 3 points,
  normal to curve, tangent) with drag handles, and **Axis**.
- **Rollback**, **Suppress/Unsuppress**, **Section View** (up to three
  sections, drag handle - on parts and whole assemblies), **Edit Material**
  and **Mass Properties** (a body, a weldment part or a whole assembly).
- **Configurations** with a **Design Table**: one part file, several versions
  of it. Columns are named sketch dimensions, feature values (depths, wall
  thickness, hole depths, member sizes) or a feature's suppression; rows are
  configurations. Double-click one to rebuild the part to it; "Save model
  values" writes your edits back into the table.

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
- **End Cap** on tube ends (outward or inward, inset), or a bigger **base
  plate** with an anchor hole in each corner, and **Gusset** plates between
  two member faces (legs, thickness, corner relief).
- A weldment part stays **one part**: members, plates and gussets go into a
  Part container with the body (named after the file), so Insert Components
  brings the whole thing into an assembly.
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
  standard 3 view plus an isometric, at a standard scale that fits the sheet
  clear of the title block, with overall dimensions, an "n x ⌀" callout and a
  position for each size of hole, and the weldment cut list as a table.
  Projection is first-angle for ISO sheets and third-angle for ANSI.
- **Make Drawing from Assembly** (same button, with an assembly open): an
  isometric with the **BOM table** and a numbered **balloon** on every BOM
  item, plus a dimensioned sheet for each part ("Auto" picks a bigger sheet
  only when it allows a bigger scale). **Save All as PDF** writes every sheet,
  numbered, into one folder. On big assemblies bolts, nuts and washers are left
  out of the view by default (FreeCAD's drawing views slow down sharply with
  hundreds of fasteners); they stay in the BOM.
- **Supplier Pack** (Assembly and Drawing tabs): everything a fabricator
  needs from one button, in a folder and a zip - the assembly sheet, an
  **exploded view** sheet with balloons, a dimensioned sheet per part (PDF),
  STEP of the assembly and each part, **DXF flat profiles** for plasma or
  laser cutting (every flat plate, each wall of a plate-built part such as a
  tank, and sheet metal flat patterns; identical profiles - even turned over -
  are counted together and the file names give thickness and quantity), the
  BOM and weldment cut list as CSV, and a contents list.
- The title block fills in from the part: name, material, scale, author, date,
  sheet, and weight on ANSI sheets. Text too long for its box is made smaller
  to fit (also when you type straight into the drawing).
- **Title Block** (Drawing tab, or right-click the sheet): every box in a
  list - type in it, pick its font and size, bold, nudge it right or up.
  **Move to sheet** makes a box's text a note you can drag anywhere and
  restyle; **Put back in box** returns it.
- **Text Box:** type a note, pick the font, size (capital height in mm),
  bold / italic, colour and a wrap width; drag it into place. Double-click a
  note to change it; **Ctrl + mouse wheel** over a selected note makes it
  bigger or smaller.
- **Projected views drag apart:** the views are laid out once, then let go,
  so you can drag the top view up or down and the side view left or right -
  each slides along its line from the front view, so they stay aligned (drag
  the front view to move them all). **View Spacing** sets the gap between
  them all at once. **Break Alignment** (right-click a view) frees it to go
  anywhere - its dimensions go with it - and **Default Alignment** puts it
  back in line.
- **Client Sheet:** bring in a client's border and title block - **DXF**
  (lines, polylines, arcs, circles, ellipses, splines, text, MTEXT and
  blocks; block attributes become boxes to type in), **SVG**, or a
  **picture** (PNG / JPG; PDF where FreeCAD's Qt can read it). Keep it the
  size it was drawn or fit it to a standard sheet, tick any text you want to
  type over, and it's kept in your sheet formats so Make Drawing lists it.
- **Right-click on the drawing** gives the choices for what's under the
  mouse (Break / Default Alignment, View Spacing, Edit Text) and Add Text Box
  Here, Title Block and Client Sheet, above FreeCAD's own.
- The Drawing tab has Model/Projected/Section/Detail views, View Spacing,
  Break / Default Alignment, Smart Dimension, Text Box, Note, Balloon, Centre
  Mark, Hatch, Surface Finish, Weld, Sheet Format, Title Block, Client Sheet
  and Save as PDF/DXF.

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
  - **Pipe fittings:** EN 10253-2 90 deg elbows (2D, 3D, 5D), 45 deg 3D
    elbows, equal tees, concentric reducers and caps, with the EN 10220 pipe
    wall; ASME B16.9 90 and 45 deg long radius elbows, equal tees,
    concentric reducers and caps. **Outlet points** turns an elbow or tee's
    branch up, down, left, right, front or back as it's placed.
  - **Bearings:** ISO 15 deep groove ball bearings, 60xx, 62xx and 63xx.
  - Click a pipe end and a flange or fitting sizes itself to the pipe; click
    a shaft end or housing bore for a bearing. Change size or rating later in
    the properties.
  - **Flange joints:** click a flange's face - also one inside an inserted
    part, like a tank's nozzle flange - to bolt another flange (or a
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
- **Routing tab (Tube and Pipe style):**
  - **3D Sketch:** draw a pipe run straight in 3D space, renamable in the tree
    like any feature. Click a nozzle flange to start on it (the point snaps to
    the flange centre), then click along; lines lock to X, Y or Z and round to
    10 mm, Tab changes the plane, or type a direction and length. Edit any
    line's length or direction in the table and the lines after it follow.
    Click a corner to start a branch.
  - **Route Pipe:** select the 3D Sketch (or ordinary sketches) and MechFlow
    fills it in: pipe cut to length, elbows at the bends (EN 10253 2D/3D/5D or
    ASME LR; cut elbows for other angles), equal tees at branches, a gasket,
    mating flange and bolts where it starts on a flange, and plain ends, weld
    neck flanges, blinds or caps at the free ends. Edit the sketch and the
    route rebuilds.
  - **Valves & Instruments:** click a pipe to drop a ball, gate, globe, check
    or butterfly valve (EN 558 / ASME B16.10 face-to-face), a pressure gauge
    or temperature sensor on it. The pipe splits round it and flanges,
    gaskets and bolts go in. Drag the ring (degree callout, 5° steps) to turn
    it round the pipe, drag the arrow (mm callout) to slide it along, or type
    both. They stay put when the route rebuilds.
  - **Pipe Specs:** pick a spec in Route Pipe (EN carbon steel PN16, ASME CS
    Class 150 Sch 40, stainless...) and the route takes its standard,
    material, schedule (by size, for ASME), elbows, flange rating and free
    ends. Duplicate a built-in spec to make your own; change it and every
    route using it follows. The material goes on the parts and in the BOM.
  - **Change Pipe Size:** right-click a pipe of a route. The new size runs
    on downstream until the next change, with concentric reducers where it
    steps (two in a row for a bigger step). Valves and fittings after it
    take the new size. A library part with different end sizes (a DN100 x
    DN80 control valve, say) changes the size after it, and the route
    checks it's the right way round.
  - **Author Component:** open your own valve, strainer or sensor model,
    click its port edges (two for an inline part, one for a branch part),
    name it and OK: it joins the Valves & Instruments list and places, turns
    and bolts up like the built-in ones.
  - **Pipe from Scan:** reverse-engineer pipework from a 3D scan. **Import
    Scan** reads OBJ, STL or PLY meshes and XYZ / ASC / PTS point clouds of
    any size (the whole scan is kept for measuring, a lighter copy is shown;
    it's cached, so opening it again is quick). Any mesh or point cloud
    already in the document works too. In **Pipe from Scan**, click the pipe
    wall: MechFlow follows the pipe both ways, through the elbows, until it
    meets a flange, a plate (bulkhead, deck) or the end of the pipe. It
    measures the OD (and matches it to EN or ASME), the straights and the
    corners where they meet, the bend radius (3D / 2D / 5D / LR), reducers
    in line, and fits standard weld neck flanges to the scan at each end to
    find their rating and where the joint face is. It picks a pipe spec to
    match, shows the line in the view coloured by how closely it follows the
    scan, and OK makes a 3D sketch and a route of it - so it can be edited,
    have valves added and go in the BOM like any other. Pipe hangers and
    clamps along the way are stepped over, not taken for flanges.
    **Checking it:** the scan's points on the pipe are coloured by how far
    they are off the model (green close, amber check, red far), orange dots
    mark anything worth a second look (a flange only
    half seen, a hanger stepped over, a gap bridged, the line just
    stopping), and **Save report** writes a CSV of what was measured and how
    well it fits, with what each orange dot is about - the same report is kept on the route.
    **Correcting it:** drag the orange grip on either end of the line
    along its pipe, or type a length in its callout (or in the panel): the
    length is the cut length of the pipe itself - not the elbow or flange -
    so pipes come out in exact lengths. **Set an end** then click the pipe -
    the line finishes there; **Carry on past** then click where it stopped wrongly -
    it follows the pipe on; **Undo corrections** goes back. Each straight
    can be **Auto** (squared up when within 5° of X / Y / Z), **Square** or
    **As measured** - as measured, the elbows either side are cut to suit,
    so a flange sits flat against the one it bolts to. Each end can finish
    differently (a flange at one end, a plain end through a bulkhead at the
    other). Work a section at a time: one line from flange to flange.
  - **Remove from Scan:** a copy of the scan with the modelled pipe taken
    out - everything on the route's pipes, fittings, flanges and valves,
    within a margin you set - so the new pipe sits in what's left of the
    scan. The original scan is kept (hidden) and the copy can be traced
    again.
  - **Save Part As** (Routing tab, or right-click a pipe or fitting): save
    one or more parts on their own, at their own origin, as a FreeCAD part,
    STEP or both - for spool drawings or to send out. Give each a **part
    number** (or number them all: prefix, start, step) and a description;
    files are named by part number, number and description, or description,
    the saved part (and the STEP product) carries the number, and it can be
    put on the parts in the model so the BOM lists them by number.
- **Scan View** (Drawing tab): drawings can't draw a scan, so this puts a
  picture of the scan with the new pipe in it on the sheet as a labelled
  reference view - pick the view, the scan's colour and opacity and the
  pipe's colour; select it and run again to update it after changes.
  Dimensioned views of the pipework are made the usual way.
- **Interference Detection** (touching parts aren't counted, results are
  remembered so re-checking after an edit is quick).
- **Exploded View:** the biggest part stays put and every other one slides out
  along the axis it sits on (a nozzle's gasket, flanges and pipe spread out
  along the nozzle, a door comes off its side), bolts going with what they
  hold. Click again to put it back; the assembly and its mates aren't changed.

  ![Exploded View of a tank assembly](docs/screenshots/exploded.png)

![Mate panel](docs/screenshots/mate.png)

### Stress Check
SimulationXpress-style linear static check of a part or weldment, on
FreeCAD's FEM (CalculiX, which comes with FreeCAD):

1. **Material** (from the part, or pick one),
2. **Fixtures:** click the fixed faces,
3. **Loads:** a force (normal or along X/Y/Z), a pressure, **water pressure**
   (click one inside face, e.g. a tank's floor: every face the liquid
   touches is found, and each point gets ρ·g·depth) and the part's own
   weight,
4. **Mesh** quality, then **Run**.

You get a colour plot of von Mises stress, the maximum stress and where it
is, the **factor of safety** against yield (passes at 1.5 or more), and the
maximum deflection. *Leave out small holes and stubs* (on by default) skips
bolt holes and small bosses, which cost far more mesh than they change the
result on a plate or tank. The fixtures and loads are kept with the part, so
the check can be re-run after a design change. It's a linear check: stresses
at sharp internal corners and right at fixed edges read high, and when a
plate deflects more than about half its thickness the real plate is stiffer
than the result (but it needs stiffening anyway).

![Stress Check of a water tank](docs/screenshots/stress-check.png)

## Where it differs from SOLIDWORKS

MechFlow changes how FreeCAD looks and behaves, but the geometry is still
FreeCAD's, so a few things work differently:

- Drawings are stored in the part's `.FCStd` file, not a separate drawing file.
  There is no *Model Items* import of sketch dimensions: MechFlow adds overall
  and hole dimensions, and you add the rest with Smart Dimension.
- An assembly shows each part in its active configuration; two configurations
  of the same part can't be in one assembly yet.
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

`tests/` has smoke tests that drive the real FreeCAD GUI. They build parts,
use each panel the way a user would, and check the resulting geometry. On
Linux they run headless under Xvfb (`tests/run_tests.sh`); on any OS,
including Windows, they can run inside FreeCAD from the Python console:

    exec(open(App.getUserAppDataDir() + "Mod/MechFlow/tests/run_in_freecad.py").read())

See [tests/README.md](tests/README.md).

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
