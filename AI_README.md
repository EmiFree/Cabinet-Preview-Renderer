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
| Windows (Git Bash / WSL) | `cmd.exe /c run.cmd <command>` or `runtime/python-win-amd64/python.exe tools/cpr.py <command>` | |
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
| `capture <job> [--views all\|id,id] [--size 2400x1800] [--out FOLDER]` | Renders views to PNG with a headless browser. Files go to `jobs/<job>/output/` and are also copied to `--out` if given. |
| `build <job> [--out file.html]` | Writes one self-contained HTML viewer (orbit, zoom, view buttons, spec card). It opens by double-click and can be emailed or published. |
| `serve [--port 8765]` | Serves the project at `http://127.0.0.1:8765/` for a browser tool. It prints viewer, capture and PDF URLs, and keeps running until stopped. |
| `textures list [--json]` | Lists every material id you can use in a job. |
| `textures add <id> --file IMG --repeat W H [--category C] [--label L] [--roughness R]` | Registers a new image texture (see section 7). |
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
   template and look at `jobs/moore-bar/job.json`, a complete worked example (a U-shaped bar with corner
   lazy susans, sink, tile, window, shelving and a bar top).
5. **Validate.** `validate <job>`. Fix every ERROR. Compare the printed run and item coordinates with the
   floor plan: lengths, corner positions and which way the fronts face.
6. **Render and look.** `capture <job> --views all`, then open every PNG and compare it with the
   elevations: door and drawer counts, which side hinges and pulls are on, heights, tile extents. Fix and repeat.
7. **Deliver.**
   - Copy PNGs to wherever the user wants with `capture <job> --out "<folder>"`.
   - For an interactive version, `build <job>` gives `jobs/<job>/output/<job>.html`. If your environment can
     publish HTML pages (for example a Claude artifact), publish that file.
   - Tell the user what was assumed and what was left out (`info.notes` and `info.notShown`).

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
  "finishes": {                                      // material ids from `textures list`
    "cabinet": "rift-white-oak-light-bleached",      // doors, drawers, panels, carcasses, base
    "groove": "bead-groove",                         // bead-route shadow lines
    "toeKick": "toe-kick-shadow",
    "hardware": "satin-nickel"
  },
  "defaults": {                                      // all optional
    "boxTop": 34.5,                                  // top of cabinet boxes
    "frontThickness": 0.75, "reveal": 0.125, "frontMargin": 0.1, "stile": 2.25,
    "base": { "toeHeight": 2.5, "toeRecess": 3, "bandHeight": 2, "bandProjection": 0.25 }
  },
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
  "boxTop": 34.5,           // optional per-run override
  "base": true,             // false = no toe kick or base band
  "items": [ ... ]
}
```

Item types:

| type | fields | meaning |
|---|---|---|
| `end-panel` | `width` (default 0.75), `stile` (3) | Finished shaker end panel. Must be the first or last item. Its outer face is that end of the run. |
| `blank` | `width`, `carcass` (true) | Box with no fronts. Use it for hidden corners and fillers, or `carcass:false` for an empty gap. |
| `cabinet` | `width`, `rows`, `inset`, `sinkBase`, `sinkDepth`, `carcass` | A base cabinet with fronts. |

Cabinet `rows` are listed **top to bottom**:

- Each row has a `height` in inches, or `"fill"` to share the space left over equally between fill rows.
- Each row has `fronts`, listed left to right. A front without `width` shares the row width equally.
- The front height available is `boxTop - (toeHeight + bandHeight) - 2*frontMargin`, which is 29.8" with the
  defaults. Reveals (gaps) are added between rows and fronts automatically.
- `inset: [left, right]` trims the outer reveal. The default is `reveal/2` on each side. Use `0` where a
  front meets an inside corner flush.
- `sinkBase: true` lowers the carcass top by `sinkDepth` (7) so an undermount sink bowl shows through the
  counter cutout.

Front fields:

```jsonc
{
  "style": "shaker",       // "shaker" (frame + recessed panel), "slab" (flat), "none" (open)
  "stile": 2.25,           // shaker frame width (use about 1.75 on narrow leaves)
  "beadRoute": true,       // groove detail (shaker: inside the frame; slab: around the perimeter)
  "width": 15,             // optional fixed width
  "hardware": { "type": "knob" | "bar",
                "x": "left" | "center" | "right" | <inches from the left edge>,
                "inset": 1.1,          // distance from the side edge when x is left/right
                "fromTop": 1.1,        // inches from the top edge to the hardware centre
                "length": 6,           // bar pulls only
                "vertical": false }    // bar pulls only
}
```

`hardware` may be a list for several pieces. Hinge side is shown only by where the knob or pull sits:
put it on the side opposite the hinges, as drawn on the elevation (the dashed triangle's point marks the
hinge side).

### 5.2 Counters

```jsonc
{ "id": "east-top", "material": "davinci-honed",
  "x0": -26.25, "x1": 0, "z0": 26.25, "z1": 61.75,     // plan rectangle (overhangs included)
  "top": 36, "thickness": 1.5,
  "cutouts": [ { "x0": -19, "x1": -5, "z0": 37, "z1": 51 } ] }   // max 1 cutout per counter
```

Counters are rectangles. Split L and U shapes into several rectangles. Usual overhang is 1" past the
door faces and about 1.25" past finished end panels.

### 5.3 Objects

| type | fields |
|---|---|
| `box` | `material`, `min: [x,y,z]`, `max: [x,y,z]`, optional `grain: "h"` for wood. Use it for walls without openings, pony walls, caps, bar tops, waterfall ends, soffits and **tile fields** (a box about 0.35" thick on the wall face). |
| `wall` | `material`, `min`, `max`, `roomSide` (`N/S/E/W`, the side facing the room), `openings: [{ a0, a1, y0, y1, glass (true), glassMaterial, jamb: <material>, trim: { material, width, projection } }]`. `a0`/`a1` are measured along the wall's long axis (x for walls running east-west, z for walls running north-south). Windows get glass and daylight behind. |
| `sink` | `x0, x1, z0, z1` (bowl rectangle = counter cutout), `rim` (top of box, 34.5), `depth` (7), `material` |
| `faucet` | `position: [x, y(counter top), z]`, `facing` = the direction the spout points, `material` |
| `outlet` | `position: [x,y,z]` (centre, on the wall or tile face), `facing` = the direction the plate faces, `orientation: "horizontal"\|"vertical"` |
| `tube-shelving` | `axis` ("z" or "x", along the wall), `front`, `back` (wall-normal coordinates of the two post rows), `posts: [...]` (positions along the axis), `top` (ceiling or soffit height), `tube` (diameter), `levels: [{ y, between: [i, j] }]`, `material`, `glass` |

Tile and liner materials have their real tile size built in (`repeatInches`), so a tile box of any size
shows correctly sized tiles. To leave a window clear, split the tile into boxes around the opening.

### 5.4 Views

```jsonc
{ "id": "north", "label": "North wall 3.3", "position": [x, y, z], "target": [x, y, z], "fov": 62 }
```

The first view is the default. Ids must be lowercase letters, digits and hyphens.

- **Overview:** a camera about 200-260" out from the open side, at about 110" height, aimed at counter
  height, `fov` 38.
- **Elevation-style:** stand in the room about 40-60" in front of the wall, eye height 50-65", `fov`
  46-62. In tight aisles, put the camera above the opposite counter.
- Name views after the drawing's elevation numbers so the user can match them up.

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
| `procedural` | generated in the browser by a function in `engine/textures.js` (`GENERATORS`) | `generator` (`wood`, `stone`, `tile-grid`, `plank-offset`), `params`, `repeatInches` |
| `image` | an image file inside `textures/` | `file` (path relative to `textures/`), `repeatInches` |
| `color` | flat colour | `color` |
| `metal` | metallic colour | `color`, `roughness` |
| `glass` | transparent | `color`, `opacity` |
| `sky` | unlit colour (window daylight) | `color` |

All kinds also take `label`, `category` and `roughness` (0 = shiny, 1 = matte). Colours are normal sRGB
hex values, as you would pick them from a swatch.

**Pair the groove with the wood.** `finishes.groove` is the shadow line of the bead route. Use a colour
clearly darker than the cabinet finish: `bead-groove` for light woods (oak), `walnut-groove` for
`walnut-natural`. A groove lighter than the wood reads as a light pinstripe.

`repeatInches: [w, h]` is the real-world size of **one texture tile**. For a 4x4 tile it is `[4, 4]`. For a
wood photo covering 24" x 48" it is `[24, 48]`. Wood grain runs along the texture's vertical axis. The
engine rotates it automatically for rails and drawer fronts.

**Adding a new finish:**

- From an image (preferred when the user supplies a sample photo or scan):
  `textures add walnut-natural --file walnut.jpg --repeat 24 48 --category wood --label "Walnut, natural"`.
  The command copies the image to `textures/<category>/` and registers it. Use a seamless, tileable,
  evenly lit image.
- A variation of an existing look: copy a registry entry under a new id and change `params` (colours,
  seed). For example, a painted cabinet is `"kind": "color"`, or `wood` with a different `base`.
- A brand new procedural pattern: add a generator function to `GENERATORS` in `engine/textures.js` that
  returns a THREE texture, then reference it by name from the registry.

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
textures/registry.json  material registry; image textures live beside it in subfolders
templates/job.template.json   starting point for new-job
jobs/<job>/job.json     one job (the only file you normally edit)
jobs/<job>/source/      the client's drawings
jobs/<job>/output/      PNG renders and built HTML (generated)
work/                   scratch output from pdf-snap (safe to delete)
```

Normally you only edit `jobs/<job>/job.json` and, when adding finishes, `textures/`. Change the engine only
when the job needs something it cannot express. Keep engine changes generic and document new fields in
this file.

---

## 9. Current limits

- Base cabinet runs only: no wall or upper cabinets, tall pantries or angled runs yet. Model tall boxes with
  `box` objects if essential and tell the user.
- Runs face the four compass directions only. Counters and boxes are axis-aligned rectangles.
- One cutout per counter. Eased or waterfall edges are drawn square.
- Hardware is generic (round knob, round bar pull).
- Needs internet for three.js and pdf.js (CDN). Headless capture needs Chrome, Edge or Chromium.

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `python was not found` / Microsoft Store opens (Windows) | Use `run.cmd`, which uses the bundled runtime. Do not call bare `python`. |
| `No Chrome, Edge or Chromium found` | Install one, pass `--browser "<path>"`, or set the `CPR_BROWSER` environment variable. Or use `serve` with your own browser tool (section 6). |
| `Timed out waiting for the page` | Usually no internet (CDN). Check with `doctor`, retry with `--timeout 300`. |
| `Page error: Unknown material "x"` | Fix the id in job.json or register it (`textures list`). |
| Render shows a missing tile or wall face flicker | Two boxes share the same face. Move the tile box 0.35" off the wall face, as in the example. |
| Fronts overlap or leave gaps | `validate`, then check item widths add up to the run length and the rows warning. |
| PowerShell says `run.cmd is not recognized` | Use `.\run.cmd` (with `.\`). |
