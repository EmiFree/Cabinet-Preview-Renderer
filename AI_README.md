# Cabinet Preview Renderer: instructions for AI agents

You are an AI agent (for example Claude Code) that was given this folder. Your job is to turn
cabinet **elevation / floor-plan drawings** (usually PDFs) into **3D preview renders** (PNG images and an
interactive HTML viewer) using the tools in this folder. Read this whole file before starting.

The person you work for is usually a cabinet maker, not a programmer. Do the technical work yourself,
explain results in plain words, and ask them only about design decisions the drawings do not settle.

---

## 1. Run the tools

All tools are one Python program, `tools/cpr.py`, started through a launcher. Always run commands
**from this folder** (the one containing this file).

| System | Command form | Notes |
|---|---|---|
| Windows (PowerShell) | `.\run.cmd <command> [options]` | Uses the bundled Python in `runtime/python-win-amd64/`. Nothing to install. |
| Windows (cmd.exe) | `run.cmd <command> [options]` | Same as above. |
| Windows (Git Bash) | `runtime/python-win-amd64/python.exe tools/cpr.py <command>` | Call the bundled Python directly. Bash launching `run.cmd` from a folder with a space in its path garbles quoted arguments. |
| macOS / Linux | `sh run.sh <command> [options]` | Needs `python3` (3.8+). macOS: `xcode-select --install` provides it. |

Exit code 0 = success. Errors print a line starting with `ERROR:` and exit with a non-zero code.
Do not install pip packages. The tools use only the Python standard library.

**First command, every session:**

```
.\run.cmd doctor        (Windows)
sh run.sh doctor        (macOS/Linux)
```

`doctor` reports the Python version, which browser will be used for headless rendering, texture registry
problems and the existing jobs. Rendering needs **Chrome, Edge or Chromium** installed (Edge is on every
Windows 10/11 PC) and **internet access** (three.js and pdf.js load from public CDNs).

### Command reference

| Command | What it does |
|---|---|
| `doctor` | Environment check. |
| `new-job <name> [--title "..."] [--source FILE ...]` | Creates `jobs/<name>/job.json` from the template and copies drawings into `jobs/<name>/source/`. Name: lowercase letters, digits, hyphens. |
| `add-source <job> <file> [...]` | Copies more drawings into the job's `source/` folder. |
| `pdf-snap <pdf> [--page N] [--crop fx,fy,fw,fh] [--grid] [--size WxH] [--out file.png]` | Renders a region of a PDF page to PNG so you can **look at the drawing up close**. Prints the sheet size and pixel scale for measuring. Default output is in `work/`. |
| `validate <job> [--json]` | Checks the job file and prints the **computed world coordinates of every run and cabinet**. Run it after every edit. |
| `plan <job> [--no-png]` | Draws a **top-down plan check** (`jobs/<job>/output/<job>-plan.svg` and `.png`): runs with cabinet ids and widths, door-face lines, wall cabinets (dashed), counters, walls and camera positions. Open the PNG and compare it with the architect's plan **before** rendering. |
| `capture <job> [--views all\|id,id] [--size 2400x1800] [--out FOLDER]` | Renders views to PNG with a headless browser. Files go to `jobs/<job>/output/` and are also copied to `--out` if given. `all` includes the automatic views when the job uses them (section 5.4). |
| `build <job> [--out file.html] [--inline-libs \| --cdn]` | Writes one self-contained HTML viewer (orbit, zoom, view buttons, spec card). It opens by double-click and can be emailed or published. By default three.js is put inside the file (from `vendor/`), so it also works offline and in sandboxed file previews. `--cdn` makes a smaller file that needs internet. |
| `open <job> [--no-launch]` | Builds the HTML viewer and opens it in the computer's default web browser. `--no-launch` only builds it and prints the path. |
| `vendor [--force]` | Downloads the pinned three.js and pdf.js files into `vendor/`. They ship with the project; you only need this if `vendor/` is missing. |
| `serve [--port 8765]` | Serves the project at `http://127.0.0.1:8765/` for a browser tool. It prints viewer, capture and PDF URLs, and keeps running until stopped. |
| `textures list [--json]` | Lists every material id you can use in a job. |
| `textures add <id> --file IMG --repeat W H [--category C] [--label L] [--roughness R]` | Registers a new image texture (see section 7). |
| `job-material <job> <id> --base custom-rift --color "#8a5a3b" [--gloss 0.4] [--seed N] [--grain-contrast 0.4]` | Creates or changes a **custom-coloured material inside one job** (section 7.1). `--list` shows them, `--remove` deletes one. |
| `package [--out FILE.zip] [--include-outputs] [--include-sources] [--no-runtime]` | Zips the project for handing to someone else. The zip is written outside the project folder. |

`<command> --help` shows every option.

---

## 2. The workflow

1. **Set up the job.** `new-job smith-kitchen --title "Smith Kitchen" --source "<path to drawings.pdf>"`
2. **Read the drawings.**
   - First look at the whole sheet. If your file-reading tool can open PDFs or images, read the PDF directly.
     Otherwise run `pdf-snap <pdf> --grid`.
   - Find the **floor plan**, each **elevation**, the **scale** (for example `1/2" = 1'-0"`), the schedule and
     finish notes, and any written dimensions.
   - Zoom into each area with `pdf-snap <pdf> --crop fx,fy,fw,fh --grid`, then open the PNG it saved. The grid
     labels are page fractions, so you can read off the next crop directly. Zoom until the line work is crisp.
3. **Measure** (section 4). Written dimensions always win over scaled ones. Record every assumption.
4. **Choose a coordinate origin and write `jobs/<job>/job.json`** (sections 3 and 5). Start from the
   template and copy patterns from the worked examples:
   - `jobs/moore-bar/`: a U-shaped bar with corner lazy susans, sink, tile, window, shelving and a bar top
   - `jobs/examples/example-features/` (job name `example-features`): every engine feature in one small kitchen. It has wall cabinets with a light
     rail, LEDs and a soffit; a tall oven and wine column; nested drawer columns; flush, applied and recessed
     bases; slat fronts; an angled island top with a waterfall end and legs; a rangetop with a tapered hood;
     a ridge-line window; a steel door; a sloped ceiling; wall paneling; and a shelf.
   - `jobs/example-custom-finishes/`: custom colours and gloss, plus finishes that differ per run
5. **Validate.** `validate <job>`. Fix every ERROR. Compare the printed run and item coordinates with the
   floor plan: lengths, corner positions and which way the fronts face.
6. **Plan check.** `plan <job>`, then open the PNG. Check that the runs, island and walls sit where the
   architect's plan puts them, and that every camera is inside the room looking the right way. If the
   drawing set has no floor plan, show this image to the user and ask them to confirm the layout before you
   spend time on details.
7. **Render and look.** `capture <job> --views all`, then open every PNG and compare it with the
   elevations: door and drawer counts, which side hinges and pulls are on, heights, tile extents. Fix and repeat.
8. **Deliver** (section 2.1). This is the default ending for every render job.

### 2.1 Delivering the result (default, unless the user asks for something else)

At the end of every rendering job, **give the user both of these** without being asked:

1. **One image of each cardinal view, plus an overview.** The job must have views named `north`, `east`,
   `south` and `west`, each looking toward that wall, and an `overview`. Leave out a direction only when there
   is genuinely nothing on that side, and say so. Make the cardinal views with your own cameras (section 5.4),
   or set `"autoViews": true` to add automatic ones and then check them.
   - Run `capture <job> --views all` (and `--out "<folder>"` if the user named a folder).
   - **Show the images to the user in the conversation**, using whatever your frontend supports: attach or
     send the PNG files, or display them inline. Don't just print the file paths. If you truly cannot show
     images, list the full paths, one per line.
2. **The interactive HTML viewer, opened for the user**, so they can orbit the model themselves. Pick the
   first option your tooling supports:
   - If your app can display or publish an HTML page itself (an in-app browser or preview pane, an artifact or
     canvas feature), `build <job>` and show `jobs/<job>/output/<job>.html` there. The file is self-contained
     (three.js is inside), so it works in sandboxed previews.
   - Otherwise, if you run commands on the user's own computer, `open <job>` builds it and opens it in their
     default web browser.
   - Otherwise (for example a remote or cloud sandbox), `build <job>` and give the user the HTML file to
     download, and tell them to double-click it.
   - If the user wants to orbit the live model with your own browser tool, `serve` and open the viewer URL
     (section 6).

Then tell the user, briefly, what was assumed or measured from scale, and what was left out
(`info.notes` and `info.notShown`).

### Rules for the content of a render

- Model **only what the drawings or the user specify**. Do not invent appliances, decor, upper cabinets
  or finishes. Glassware, bottles and people drawn on elevations are decoration, so leave them out.
- If a finish or detail is required but unspecified (wall paint, floor, hardware style), use the neutral
  placeholder materials and list it in `info.notShown`. Example: "Hardware: supplied by others, style TBD
  (placeholders shown)".
- When the drawings conflict, or a decision changes the look, ask the user. When the user changes something
  ("the fridge is now two drawer panels"), change only that, re-validate and re-capture.
- Put the scale used, measurement tolerance and design changes into `info.notes`.

---

## 3. Coordinate system (read carefully)

- **Units are inches** everywhere.
- **Plan view, north up:** `+x` = east = **right on the plan page**, `+z` = south = **down on the plan page**.
  This matches the PDF page (x right, y down), so plan measurements map straight across.
- `+y` = up. The floor is `y = 0`.
- Pick an origin that makes the numbers easy, usually a wall face. In the Moore example `x = 0` is the
  east wall face and `z = 0` is the north pony-wall face, so most cabinets have negative x.

### Cabinet runs

A **run** is a straight row of base cabinets that share a back line and depth.

- `facing`: the direction the **fronts point** (`N`, `S`, `E` or `W`). It is the direction you would
  walk in to back away from the cabinets. A run against the north wall faces `S`.
- `origin: [x, z]`: the **back-left corner** of the run, where "left" is as seen standing in front of
  the cabinets and looking at them.
- `items` are placed left to right, as seen from the front, starting at the origin. Each item's `width`
  is measured along the run.
- `depth`: the box depth, back to the face of the carcass, not counting doors. Doors add `0.75"`, so the
  door faces sit at `depth + 0.75` from the back line.

| facing | standing at the run you look | items run toward | depth goes toward |
|---|---|---|---|
| S | north | east (+x) | south (+z) |
| N | south | west (-x) | north (-z) |
| W | east | south (+z) | west (-x) |
| E | west | north (-z) | east (+x) |

**Corners:** let one run continue into the corner as a `blank` item (a carcass with no fronts) and start
the perpendicular run at the first run's **door face**. For a pie-cut lazy susan, model the two door leaves
as two narrow `cabinet` items, one on each run, beside the blank corner. The Moore job does this in both
corners.

---

## 4. Measuring from scaled drawings

- PDF units are points: **72 pt = 1 inch of paper**. `pdf-snap` prints the sheet size and the image scale
  in **px per pt**.
- Real inches per point at common scales:
  - `1/2" = 1'-0"`: 1 real inch = 1/24 paper inch = **3 pt**
  - `1/4" = 1'-0"`: **1.5 pt**
  - `3/8" = 1'-0"`: **2.25 pt**
  - `1" = 1'-0"`: **6 pt**
- From a `pdf-snap` image: `real inches = pixel distance / (px per pt) / (pt per real inch)`.
  `pdf-snap` prints `px per real inch` directly for 1/2" and 1/4" scales.
- Sanity checks:
  - base boxes are normally 24" deep (about 25" to the door face)
  - counter height is 36"
  - box top is 34.5"
  - toe kick is about 4"
  - standard widths come in 3" steps
  - drawer stacks add up to the box height
- Expect scaled numbers to be within about 1/2". Round to sensible shop values (1/8") and say so in
  `info.notes`.

---

## 5. job.json reference

Top-level keys (only `runs`, `views` and `info.title` are really needed):

```jsonc
{
  "schema": "cpr-job/1",
  "info": {
    "title": "Smith Kitchen",                       // viewer title and HTML title
    "subtitle": "Sheet A-4 · Kitchen elevations",
    "specs": [["Cabinets", "Painted maple, shaker"]],  // label/value rows in the spec card
    "notShown": ["Hardware style TBD"],              // what the render leaves out or guesses
    "notes": "Scaled from 1/2\" plan, +/- 1/2\"."    // for people and future agents; not drawn
  },
  "materials": {                                     // optional: custom-coloured materials for this job (section 7.1)
    "sage-rift": { "base": "custom-rift", "color": "#7d8b6a", "gloss": 0.3 }
  },
  "finishes": {                                      // material ids from `textures list` or "materials" above
    "cabinet": "rift-white-oak-light-bleached",      // doors, drawers, panels, carcasses, base
    "groove": "auto",                                // bead-route shadow lines; "auto" = darker shade of the cabinet colour
    "toeKick": "toe-kick-shadow",
    "hardware": "satin-nickel"
  },
  "defaults": {                                      // all optional
    "boxTop": 34.5,                                  // top of base cabinet boxes
    "wallBottom": 54,                                // default underside of wall (upper) cabinets
    "frontThickness": 0.75, "reveal": 0.125, "frontMargin": 0.1, "stile": 2.25,
    "base": { "toeHeight": 2.5, "toeRecess": 3, "bandHeight": 2, "bandProjection": 0.25 }
  },
  "autoViews": false,                                // true = also add automatic overview + north/east/south/west views
  "runs": [ /* section 5.1 */ ],
  "counters": [ /* section 5.2 */ ],
  "objects": [ /* section 5.3 */ ],
  "floor": { "material": "floor-neutral", "center": [x, 0, z], "size": 600, "visible": true },
  "lighting": { "exposure": 0.72, "sunFrom": [-1, 1.4, -0.4] },   // sunFrom = direction toward the sun
  "views": [ /* section 5.4 */ ],
  "captureNames": { "<view id>": "File Name.png" }  // optional PNG names for capture
}
```

### 5.1 Runs and items

```jsonc
{
  "id": "sink-wall", "label": "Sink wall, elevation 2",
  "origin": [x, z], "facing": "S", "depth": 24,
  "mount": "floor",         // "floor" (base and tall cabinets) or "wall" (upper cabinets, see below)
  "boxTop": 34.5,           // top of the boxes: 34.5 base, about 84-96 tall, top of uppers for wall runs
  "base": true,             // see "Bases" below; false = nothing under the boxes
  "finishes": { "cabinet": "plain-honey", "hardware": "black-matte" },  // optional: overrides job finishes for this run
  "soffit": { "to": 101, "flushWith": "doors" },   // optional drywall soffit from boxTop up to "to"
  "items": [ ... ]
}
```

Use run `finishes` when parts of the room differ, for example a painted island with stained perimeter
cabinets, or different hardware on the island. Anything not listed falls back to the job's `finishes`.

**Wall (upper) cabinets** are a run with `"mount": "wall"`. Settings:
- `bottom`: underside height (default 54).
- `boxTop`: top height (default `bottom + 30`).
- `depth`: default 12; 13 is common.

Wall runs have no base. Optional extras:
- `"lightRail": true` or `{ "height": 1.5 }`: a strip under the front edge.
- `"underLight": true` or `{ "color": "#fff1dc" }`: under-cabinet LEDs that glow onto the counter.

Place uppers with the same origin and facing rules as base runs. Usually that means the same back line as
the base run below them.

**Tall cabinets** (pantries, oven and fridge columns) are ordinary floor runs with a high `boxTop`
(for example 90.5). Use a separate run when the tall part sits beside base cabinets.

**Soffit:** `soffit.flushWith` sets where the soffit's front stops:
- `"doors"` (flush with the door faces, the default)
- `"box"` (flush with the carcass)
- a number (inches from the back line)

`material` defaults to `drywall-paint`.

**Bases** (`base`, floor runs only):

| value | looks like | options |
|---|---|---|
| `true` or `{ "type": "recessed" }` | decorative band with a recessed toe kick (the default) | `toeHeight` 2.5, `bandHeight` 2, `toeRecess` 3, `bandProjection` 0.25 |
| `{ "type": "flush", "height": 4, "reveal": 0.25 }` | base board flush with the door faces, a shadow reveal above it | `height`, `reveal`, `recess` |
| `{ "type": "applied", "height": 4 }` | furniture-style base moulding applied in front of the doors, wrapping exposed ends | `height`, `reveal` 0.125, `projection` 0.5 |
| `false` or `{ "type": "none" }` | nothing; boxes start at the floor (or at `height`) | `height` |

Fronts start at the top of the base, so the base choice changes the front height.

Item types:

| type | fields | meaning |
|---|---|---|
| `end-panel` | `width` (default 0.75), `style` (`shaker` default, `slab`, `slat`), `stile` (3), slat options | Finished end panel. Must be the first or last item. Its outer face is that end of the run. |
| `blank` | `width`, `carcass` (true) | Box with no fronts. Use it for hidden corners, or `carcass:false` for an empty gap (appliance opening, open knee space). |
| `filler` | `width` | A solid strip, flush with the door faces (scribe or filler strip). |
| `cabinet` | `width`, `rows`, `inset`, `sinkBase`, `sinkDepth`, `carcass` | A cabinet with fronts. |

Cabinet `rows` are listed **top to bottom**:

- Each row has a `height` in inches, or `"fill"` to share the space left over equally between fill rows.
- Each row has **either** `fronts` (listed left to right) **or** `columns`:
  - With `fronts`, a front without `width` shares the row width equally.
  - With `columns`, each column has an optional `width` and its own `rows` (again top to bottom), which can
    nest further. Use columns for mixed layouts such as a full-width drawer over a drawer stack beside a pullout:

  ```jsonc
  "rows": [
    { "height": 5.5, "fronts": [ { "style": "slab" } ] },
    { "height": "fill", "columns": [
      { "width": 17.5, "rows": [ { "height": "fill", "fronts": [{...}] }, { "height": "fill", "fronts": [{...}] } ] },
      { "rows": [ { "height": "fill", "fronts": [{...}] } ] } ] } ]
  ```
- The front height available is `boxTop - (top of base) - 2*frontMargin`, which is 29.8" for a standard base
  cabinet. `validate` prints it per run as "fronts A to B". Reveals (gaps) are added between rows, columns and
  fronts automatically.
- `inset: [left, right]` trims the outer reveal. The default is `reveal/2` on each side. Use `0` where a
  front meets an inside corner flush.
- `sinkBase: true` lowers the carcass top by `sinkDepth` (7). You rarely need it: any box under a `sink` object is
  lowered automatically to clear the bowl.

Front fields:

```jsonc
{
  "style": "shaker",       // "shaker" (frame + recessed panel), "slab" (flat), "slat" (vertical slats),
                           // "appliance" (built-in appliance face), "none" (open)
  "stile": 2.25,           // shaker frame width; "thin shaker" = 1, narrow leaves about 1.75
  "beadRoute": true,       // groove detail (shaker: inside the frame; slab: around the perimeter); false = plain
  "width": 15,             // optional fixed width
  "slatWidth": 1.5, "gap": 0.375, "depth": 0.25,   // "slat" only: slat width, groove width, groove depth
  "kind": "wall-oven",     // "appliance" only, see below
  "hardware": { "type": "knob",
                "x": "left" | "center" | "right" | <inches from the left edge>,
                "inset": 1.1,          // distance from the side edge when x is left/right
                "fromTop": 1.1,        // inches from the top edge to the hardware centre
                "length": 6,           // bar, appliance-pull, edge-pull, tab, finger-groove
                "vertical": false,     // bar, appliance-pull, edge-pull
                "finish": "brass-polished" }  // optional material for this piece ("material" also works)
}
```

Hardware types:

| type | what it is |
|---|---|
| `knob` | round knob |
| `bar` | round bar pull on two posts |
| `appliance-pull` | long, heavier bar on tall standoffs (default 18") |
| `edge-pull` | thin metal lip on the top edge, or the side edge when vertical |
| `tab` | short metal tab on the top edge (default 2.5") |
| `finger-groove` | routed finger pull along the top edge, no metal |
| `push-latch` / `none` | nothing drawn |

`hardware` may be a list for several pieces. Hinge side is shown only by where the knob or pull sits:
put it on the side opposite the hinges, as drawn on the elevation (the dashed triangle's point marks the
hinge side).

**Appliance fronts** (`"style": "appliance"`) are drawn inside their row, so they move when the cabinet
moves.

`kind` is one of:
- `wall-oven`: control strip, window and handle
- `microwave-drawer`
- `warming-drawer`
- `dishwasher`
- `wine-column`: steel frame, dark glass and a vertical handle; `handleSide: "left"|"right"`
- `refrigerator`: a flat steel door with a vertical handle
- `panel`: a plain steel face

Options:
- `material` (default `stainless`)
- `glass` (default `appliance-glass`)

Panel-ready appliances (fridge, dishwasher, fridge drawers with wood panels) are ordinary `shaker` or `slab`
fronts.

### 5.2 Counters

```jsonc
{ "id": "east-top", "material": "davinci-honed",
  "x0": -26.25, "x1": 0, "z0": 26.25, "z1": 61.75,     // plan rectangle (overhangs included)
  "top": 36, "thickness": 1.5,
  "edge": "eased",                                      // "eased" (default), "square", or {"profile": "mitered", "height": 3}
  "cutouts": [ { "x0": -19, "x1": -5, "z0": 37, "z1": 51 },     // any number
               { "x0": 30, "x1": 66, "z0": -1, "z1": 27 } ],   // may run out past the edge (rangetop notch)
  "waterfall": ["end"] }                                // "start" / "end" (along the long side) or "north" / "south" / "east" / "west"
```

```jsonc
{ "id": "island-top", "material": "fantastico-onyx-polished", "top": 36, "thickness": 1.5,
  "outline": [[50.75, 70], [134, 70], [140, 84], [134, 98], [50.75, 98]],   // any polygon, [x, z] points in order
  "cutouts": [ ... ],                                   // must sit fully inside an outline
  "waterfall": [4] }                                    // outline edges by index: edge i runs from point i to point i+1
```

- **Rectangles** take any number of cutouts, including cutouts that reach or cross the edge. Use those for
  notches and for rangetops that run to the counter edge.
- **`outline`** draws any polygon top: angled islands, clipped corners, L shapes in one piece. Its cutouts must
  sit fully inside the outline.
- **`edge`:**
  - `eased`: a softly rounded edge.
  - `square`: a sharp edge.
  - `mitered`: draws the slab at the apron `height`, so the edge reads as a thick mitered drop.
  - Rectangles whose cutouts cross the edge always draw square.
- **`waterfall`** drops the slab to the floor at those ends. Its outer face is flush with the counter edge.
  Don't build waterfalls from `box` objects any more.
- **Overhangs:** usually 1" past the door faces and about 1.25" past finished end panels.

### 5.3 Objects

| type | fields |
|---|---|
| `box` | `material`, `min: [x,y,z]`, `max: [x,y,z]`, optional `grain: "h"` for wood. Use it for walls without openings, pony walls, caps, bar tops and **tile fields** (a box about 0.35" thick on the wall face). |
| `wall` | `material`, `min`, `max`, `roomSide` (`N/S/E/W`, the side facing the room), `openings: [...]` (see below). |
| `sink` | `x0, x1, z0, z1` (bowl rectangle = counter cutout), `rim` (top of box, 34.5), `depth` (7), `material`, `drain` (default `true`: black 3.5" drain in the centre of the bowl floor; `false` hides it; `{ "diameter": 3.5, "position": [x, z], "material": "sink-drain" }` changes it). Any cabinet box under the bowl is cut down automatically to clear it, so `sinkBase` on the cabinet is optional. |
| `faucet` | `position: [x, y(counter top), z]`, `facing` = the direction the spout points, `material` |
| `outlet` | `position: [x,y,z]` (centre, on the wall or tile face), `facing` = the direction the plate faces, `orientation: "horizontal"\|"vertical"` |
| `rangetop` | `x0, x1, z0, z1` (footprint, usually matching a counter cutout), `top` (36), `facing` (the side with the knobs, toward the room), `burners` (default from width), `knobs`, `controls: "front"\|"top"`, `material` (stainless), `grateMaterial` (cast-iron) |
| `hood` | `x0, x1, z0, z1` (footprint), `bottom`, `top` (heights of the hood body), `wall` (`N/S/E/W`, the side against the wall), `shape: "box"\|"tapered"`, `band: { height, material }` (accent band at the bottom), `chimney: { shape: "round"\|"square", diameter or width/depth, to: <ceiling height> }`, `material` |
| `ceiling` | `min: [x, z]`, `max: [x, z]`, `height`, optional `slope: { axis: "x"\|"z", rise, run, from }` (height grows by rise/run per inch from `from`). **Cutaway by design:** the ceiling is visible from inside the room but disappears when the camera is above it, so overviews and orbiting from above still see into the room. It never casts shadows. `"hiddenFromAbove": false` makes it solid from above too (this blocks overview cameras). |
| `paneling` | `min`, `max` (a thin box on the wall face), `facing` (toward the room), `material`, `slatWidth`, `gap`, `depth`. Vertical slat wall paneling. |
| `shelf` | `x0, x1, z0, z1`, `y` (top of shelf), `thickness` (1), `cornerRadius`, `material` |
| `leg` | `position: [x, z]`, `height`, `size` (4), `shape: "square"\|"round"`, `y0` (0), `material` |
| `led-strip` | `from: [x,y,z]`, `to: [x,y,z]`, `color`, `facing: "down"\|"up"`, `intensity` (0.6), `reach` (48), `spacing` (30). It glows and lights nearby surfaces. A scene can have about 12 light points in total; strips past that are drawn unlit. |
| `tube-shelving` | `axis` ("z" or "x", along the wall), `front`, `back` (wall-normal coordinates of the two post rows), `posts: [...]` (positions along the axis), `top` (ceiling or soffit height), `tube` (diameter), `levels: [{ y, between: [i, j] }]`, `material`, `glass` |

**Wall openings** (`walls[].openings`). `a0` and `a1` are measured along the wall's long axis: x for walls
running east-west, z for walls running north-south.

```jsonc
{ "a0": 30, "a1": 66, "y0": 44, "y1": 92,          // rectangle; or "shape": [[a, y], ...] for any polygon (ridge-line windows)
  "kind": "window",                                  // or "door" (y0 defaults to 0)
  "glass": true, "glassMaterial": "clear-glass",     // doors: "panel": "solid" for a solid door
  "frame": { "width": 1.75, "material": "black-steel", "depth": 1.75 },   // drawn in the glass plane
  "mullions": { "vertical": [48], "horizontal": [68], "width": 1.25 },     // positions in a (along) and y; "muntins" also works
  "jamb": "mcintyre-glacier-bar-liner",              // optional lining of the opening's sides
  "trim": { "material": "...", "width": 0.8125, "projection": 0.6 },       // optional casing on the room face
  "swing": "left" }                                  // doors: draws the swing arc on the floor ("left" = hinge at a0)
```

Polygon shapes cut the wall to the outline, and frames and mullions follow the shape. A door gets a steel
frame by default.

Tile and liner materials have their real tile size built in (`repeatInches`), so a tile box of any size
shows correctly sized tiles. To leave a window clear, split the tile into boxes around the opening.

### 5.4 Views

```jsonc
{ "id": "north", "label": "North wall 3.3", "position": [x, y, z], "target": [x, y, z], "fov": 62 }
```

The first view is the default. Ids must be lowercase letters, digits and hyphens.

**Required view ids.** Every job should have an `overview` plus one view per cardinal direction: `north`,
`east`, `south` and `west`. The id is the wall the camera **looks at**, so `north` stands in the room and
faces the north wall. These are what you deliver by default (section 2.1). Put the drawing's elevation
number in the `label` ("North wall 7.1") and in `captureNames` if the user wants named files. Add extra
views (island, details) as needed.

- **Overview:** a camera about 200-260" out from the open side, at about 110" height, aimed at counter
  height, `fov` 38-42.
- **Cardinal and elevation views:** stand in the room about 40-60" in front of the wall, eye height 50-65",
  `fov` 46-64. In tight aisles, put the camera above the opposite counter. A camera outside the room is
  blocked by the walls.
- **Automatic views:** with no `views`, or with `"autoViews": true`, the viewer adds `overview`, `north`,
  `east`, `south` and `west` cameras computed from the cabinet footprint. They are a starting point. Look at
  the captures and replace any that cut things off with your own view under the same id.

---

## 6. Viewing in a browser tool (optional)

If you have your own browser tool and want to orbit the model yourself, start the server (it blocks,
so run it in the background) and open the printed URLs:

- `http://127.0.0.1:8765/`: lists jobs, viewers and source PDFs
- `http://127.0.0.1:8765/engine/viewer.html?job=<job>[&view=<id>]`: interactive viewer
- `http://127.0.0.1:8765/engine/viewer.html?job=<job>&capture=1&save=all`: renders all views and saves PNGs
  into `jobs/<job>/output/`
- `http://127.0.0.1:8765/engine/pdf.html?file=jobs/<job>/source/<file>.pdf&page=1&crop=fx,fy,fw,fh&grid=1`:
  zoomable PDF

When a viewer page finishes it sets `document.title` to `CPR READY` (capture mode) and
`window.CPR_STATUS` (`warnings`, `runs`, `saved`). On failure the title starts with `CPR ERROR:`.
Prefer the `capture` and `pdf-snap` commands when you have no browser tool. They do the same thing headlessly.

---

## 7. Textures and materials

Every material is registered in `textures/registry.json` by id. Jobs reference only ids.

| kind | how it is drawn | key fields |
|---|---|---|
| `procedural` | generated in the browser by a function in `engine/textures.js` (`GENERATORS`) | `generator` (`wood-rift` = rift / quarter sawn straight grain, `wood-plain` = plain / flat sawn cathedral grain, `stone`, `tile-grid`, `plank-offset`), `params`, `repeatInches`. `stone` params: `base`, `mottle` [r,g,b], `mottleSpread`, `vein` [r,g,b], `veinAlpha` [min,max], `veins`, `veinWidth`, `blur` (see soapstone and onyx in the registry). |
| `image` | an image file inside `textures/` | `file` (path relative to `textures/`), `repeatInches` |
| `color` | flat colour | `color` |
| `metal` | metallic colour | `color`, `roughness` |
| `glass` | transparent | `color`, `opacity` |
| `sky` | unlit colour (window daylight) | `color` |

All kinds also take `label`, `category` and `roughness` (0 = shiny, 1 = matte). Colours are normal sRGB
hex values, as you would pick them from a swatch.

**Pair the groove with the wood.** `finishes.groove` is the shadow line of the bead route. Leave it at
`"auto"` (the default), which uses a darker shade of whatever the cabinet material is, including custom
colours. Only set a fixed groove material (`bead-groove`, `walnut-groove`) to match an older job exactly.
A groove lighter than the wood reads as a light pinstripe.

### 7.1 Custom colours and gloss (job materials)

Some registry materials are **customisable bases**. They have a `"custom"` block, and `textures list`
marks them `[CUSTOMISABLE: ...]`. A job makes its own copy with a chosen colour and gloss, under a new id,
in the job's `"materials"` section. The registry is never changed, so every job can have its own colours.

| base | what it is | options |
|---|---|---|
| `custom-rift` | rift cut / quartered wood (straight grain), same pattern as the white oak | `color`, `gloss`, `seed`, `grainContrast` |
| `custom-plain` | plain sawn (flat sawn) wood with cathedral grain, two boards per panel width | `color`, `gloss`, `seed`, `grainContrast` |
| `custom-metal` | hardware and other metal | `color`, `gloss` |

Options:

- `color`: sRGB hex `#rrggbb`. For wood this is the overall stain or finish colour, and the grain is drawn
  darker and lighter around it.
- `gloss`: 0 = dead flat, 0.3-0.4 = satin, 0.6 = semi-gloss, 0.9+ = polished or high gloss.
- `seed`: a positive integer that changes the grain layout. Use different seeds when two materials of the
  same base sit side by side.
- `grainContrast`: 0-1, how dark the grain lines are (default 0.42).
- `label`: text shown in listings.

Create them with the tool, which validates the values, or write them into job.json by hand:

```
.\run.cmd job-material smith-kitchen rift-smoke --base custom-rift --color "#8c8478" --gloss 0.35
.\run.cmd job-material smith-kitchen brass-polished --base custom-metal --color "#c9a45c" --gloss 0.9
.\run.cmd job-material smith-kitchen --list
```

Then use the id anywhere a material id goes: `finishes`, a run's `finishes`, a hardware `material`, or a
`box`. Job material ids must not reuse a registry id.

Starting colours:

| finish | color | gloss |
|---|---|---|
| natural white oak | `#d8c3a0` | 0.3 |
| smoked / grey oak | `#8c8478` | 0.35 |
| honey / golden | `#c49a62` | 0.4 |
| mid walnut stain | `#6e4a33` | 0.4 |
| espresso | `#3b2a20` | 0.4 |
| polished brass | `#c9a45c` | 0.9 |
| satin brass | `#b59a62` | 0.55 |
| polished nickel | `#d8d6d0` | 0.95 |
| satin nickel | `#b9b6ae` | 0.6 |
| matte black | `#2b2b2b` | 0.15 |
| oil-rubbed bronze | `#4a3a2c` | 0.35 |

When the user gives a colour by name or sample ("make it a bit warmer", "match this swatch"), adjust the
hex, re-capture, and show them the result. `jobs/example-custom-finishes/` is a small test room using all
three custom bases, with per-run finishes and two hardware metals.

`repeatInches: [w, h]` is the real-world size of **one texture tile**. For a 4x4 tile it is `[4, 4]`. For a
wood photo covering 24" x 48" it is `[24, 48]`. Wood grain runs along the texture's vertical axis. The
engine rotates it automatically for rails and drawer fronts.

**Adding a new finish:**

- From an image (preferred when the user supplies a sample photo or scan):
  `textures add walnut-natural --file walnut.jpg --repeat 24 48 --category wood --label "Walnut, natural"`.
  The command copies the image to `textures/<category>/` and registers it. Use a seamless, tileable,
  evenly lit image.
- A variation of an existing look: copy a registry entry under a new id and change `params` (colours,
  seed). For example, a painted cabinet is `"kind": "color"`, or `wood-rift` / `wood-plain` with a different `base`.
- A brand new procedural pattern: add a generator function to `GENERATORS` in `engine/textures.js` that
  returns a THREE texture, add its name to `GENERATOR_NAMES` in `tools/cpr.py`, then reference it by name from the registry. If it is a wood grain that should
  turn sideways on rails and drawer fronts, also add its name to `GRAIN_GENERATORS`.
- To make a new entry customisable, give it a `"custom": { "color": "#...", "gloss": 0.4 }` block of
  defaults. `CPR.applyCustom` in `engine/textures.js` maps the options onto the entry.

Run `textures list` and `doctor` afterwards. They flag missing image files and bad entries.

---

## 8. Project layout

```
AI_README.md            this file
README.md               short human readme
run.cmd / run.sh        launchers
runtime/                bundled Windows Python 3.12 (embeddable; do not edit)
tools/cpr.py            all command line tools (single file, standard library only)
engine/viewer.html      3D viewer page (served mode and template for `build`)
engine/engine.js        builds the 3D scene from a job (cabinets, counters, objects, lights)
engine/textures.js      procedural texture generators + material factory
engine/pdf.html         PDF crop viewer used by pdf-snap / serve
engine/svg2png.html     converts the plan SVG to PNG (used by plan)
vendor/                 pinned three.js r147 and pdf.js 3.11 files, so everything works offline (restore with: vendor)
textures/registry.json  material registry; image textures live beside it in subfolders
templates/job.template.json   starting point for new-job
jobs/<job>/job.json     one job (the only file you normally edit)
jobs/examples/<job>/    example jobs kept in the repo; commands find them by plain name (jobs/<name> is checked first)
jobs/<job>/source/      the client's drawings
jobs/<job>/output/      PNG renders, plan check and built HTML (generated)
work/                   scratch output from pdf-snap (safe to delete)
```

Normally you only edit `jobs/<job>/job.json` and, when adding finishes, `textures/`. Change the engine only
when the job needs something it cannot express. Keep engine changes generic and document new fields in
this file.

---

## 9. Current limits

- Runs face the four compass directions only. Angled walls and runs are not supported. Counter tops can
  be any polygon (`outline`), and window openings can be polygons.
- Boxes, walls and rectangle counters are axis-aligned. Ceilings can slope in one direction (no multi-plane
  vaults).
- Corner cabinets are modelled with `blank` items plus narrow leaves (no curved lazy susan doors).
- Cutouts in `outline` counters must sit fully inside the outline. Rectangle counters whose cutouts reach the
  edge draw with square edges.
- Hardware and appliances are generic shapes, not brand models. Glass-front cabinet doors are not
  available yet.
- About 12 LED light points per scene. Lighting is a soft daylight rig, not a photoreal light simulation.
- Headless capture needs Chrome, Edge or Chromium. Everything else works offline, because `vendor/` ships
  three.js and pdf.js.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `python was not found` / Microsoft Store opens (Windows) | Use `run.cmd`, which uses the bundled runtime. Do not call bare `python`. |
| `No Chrome, Edge or Chromium found` | Install one, pass `--browser "<path>"`, or set the `CPR_BROWSER` environment variable. Or use `serve` with your own browser tool (section 6). |
| `Timed out waiting for the page` | Check `doctor`. If `vendor/` is missing, the pages fall back to the internet CDN: run `vendor` while online. Retry with `--timeout 300` for very large scenes. |
| HTML file shows `THREE is not defined` | It was built with `--cdn` and opened without internet. Rebuild with `build <job>` (three.js inside). |
| A camera shows only a wall | It is outside the room, or inside a cabinet. Check its dot on `plan <job>` and move it into the room. |
| Fronts look wrong in a nested layout | `validate` warns when rows or columns don't add up. Check that every column has rows, and that only one row per level uses "fill" when the others are fixed. |
| `Page error: Unknown material "x"` | Fix the id in job.json or register it (`textures list`). |
| Render shows a missing tile or wall face flicker | Two boxes share the same face. Move the tile box 0.35" off the wall face, as in the example. |
| Fronts overlap or leave gaps | `validate`, then check item widths add up to the run length and the rows warning. |
| PowerShell says `run.cmd is not recognized` | Use `.\run.cmd` (with `.\`). |
