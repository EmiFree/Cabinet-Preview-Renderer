#!/usr/bin/env python3
"""Cabinet Preview Renderer command line tools.

Standard library only (Python 3.8+). Run through the launchers so the bundled runtime is used on Windows:
    Windows:      run.cmd <command> [options]
    macOS/Linux:  sh run.sh <command> [options]
Run "<launcher> help" or "<launcher> <command> --help" for details. See AI_README.md for the full workflow.
"""
import argparse
import base64
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import zipfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
JOBS = ROOT / "jobs"
EXAMPLE_JOBS = JOBS / "examples"   # example jobs (kept in the repo); looked up after jobs/<name>
TEXTURES = ROOT / "textures"
REGISTRY = TEXTURES / "registry.json"
ENGINE = ROOT / "engine"
WORK = ROOT / "work"
SCHEMA = "cpr-job/1"
FACINGS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
ITEM_TYPES = {"cabinet", "blank", "end-panel", "filler"}
OBJECT_TYPES = {"box", "wall", "sink", "faucet", "outlet", "tube-shelving", "rangetop", "hood", "ceiling",
                "led-strip", "shelf", "leg", "paneling"}
MATERIAL_KINDS = {"procedural", "image", "color", "metal", "glass", "sky"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
# procedural texture generators defined in engine/textures.js (GENERATORS); keep in sync when adding one
GENERATOR_NAMES = {"wood-rift", "wood-plain", "stone", "tile-grid", "plank-offset"}
JOB_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


# ----------------------------------------------------------------------------- helpers
class CprError(Exception):
    """Expected failure with a message meant for the user/agent."""


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:  # -sig: accept files saved with a BOM (Notepad, PowerShell)
            return json.load(f)
    except FileNotFoundError:
        raise CprError(f"File not found: {path}")
    except json.JSONDecodeError as e:
        raise CprError(f"Invalid JSON in {path}: line {e.lineno} column {e.colno}: {e.msg}")


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    # keep coordinate lists like [48, 58, 64] on one line so job files stay readable
    text = re.sub(r"\[\s*(-?[\d.eE+-]+(?:,\s*-?[\d.eE+-]+)*)\s*\]",
                  lambda m: "[" + ", ".join(v.strip() for v in m.group(1).split(",")) + "]", text)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")


def rel(p):
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def job_dir(name):
    """Folder for a NEW job (always jobs/<name>)."""
    if not JOB_NAME_RE.match(name or "") or name == "examples":
        raise CprError(f'Bad job name "{name}". Use lowercase letters, digits and hyphens, e.g. "smith-kitchen" ("examples" is reserved).')
    return JOBS / name


def find_job(name):
    """Existing job folder: jobs/<name>, then jobs/examples/<name>. None if missing."""
    job_dir(name)
    for d in (JOBS / name, EXAMPLE_JOBS / name):
        if (d / "job.json").is_file():
            return d
    return None


def require_job(name):
    d = find_job(name)
    if not d:
        have = ", ".join(j["name"] for j in list_jobs())
        raise CprError(f'No job "{name}" (looked in jobs/{name}/ and jobs/examples/{name}/). Existing jobs: {have or "none"}.')
    return d


def job_ref(d):
    """Path of a job folder relative to jobs/, e.g. "moore-bar" or "examples/example-features" (used in viewer URLs)."""
    return Path(d).resolve().relative_to(JOBS.resolve()).as_posix()


def inside_root(p):
    p = Path(p).resolve()
    try:
        p.relative_to(ROOT)
        return True
    except ValueError:
        return False


def parse_size(s):
    m = re.match(r"^(\d+)x(\d+)$", s or "")
    if not m:
        raise CprError(f'Size must look like 2400x1800, got "{s}".')
    w, h = int(m.group(1)), int(m.group(2))
    if not (200 <= w <= 8000 and 200 <= h <= 8000):
        raise CprError("Size must be between 200 and 8000 pixels on each side.")
    return w, h


# ----------------------------------------------------------------------------- registry
def load_registry():
    reg = load_json(REGISTRY)
    if not isinstance(reg.get("materials"), dict):
        raise CprError(f"{rel(REGISTRY)} must contain an object named \"materials\".")
    return reg


def registry_problems(reg):
    out = []
    for mid, d in reg["materials"].items():
        k = d.get("kind")
        if k not in MATERIAL_KINDS:
            out.append(f'material "{mid}": kind must be one of {sorted(MATERIAL_KINDS)}')
        if k == "image":
            f = d.get("file")
            if not f or not (TEXTURES / f).is_file():
                out.append(f'material "{mid}": image file "{f}" not found in textures/')
        if k == "procedural":
            g = d.get("generator")
            if not g:
                out.append(f'material "{mid}": procedural materials need a "generator"')
            elif g == "wood":
                out.append(f'material "{mid}": generator "wood" was renamed; use "wood-rift" (straight grain) or "wood-plain" (cathedral grain)')
            elif g not in GENERATOR_NAMES:
                out.append(f'material "{mid}": unknown generator "{g}" (known: {", ".join(sorted(GENERATOR_NAMES))})')
        cu = d.get("custom")
        if cu is not None:
            if not isinstance(cu, dict):
                out.append(f'material "{mid}": "custom" must be an object of default options')
            else:
                for k, v in cu.items():
                    p = custom_option_problem(k, v)
                    if p:
                        out.append(f'material "{mid}": custom default {p}')
        rep = d.get("repeatInches")
        if rep is not None and not (isinstance(rep, list) and len(rep) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in rep)):
            out.append(f'material "{mid}": repeatInches must be [width, height] in inches')
    return out


# ----------------------------------------------------------------------------- custom materials
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
CUSTOM_OPTIONS = {
    "color": "sRGB hex like #8a5a3b",
    "gloss": "number 0 (matte) to 1 (high gloss)",
    "seed": "integer; changes the grain pattern (woods only)",
    "grainContrast": "number 0 to 1; how dark the grain lines are (woods only, default 0.42)",
    "label": "text shown in listings",
}


def custom_option_problem(k, v):
    if k not in CUSTOM_OPTIONS:
        return f'"{k}" is not a custom option (allowed: {", ".join(CUSTOM_OPTIONS)})'
    if k == "color" and not (isinstance(v, str) and HEX_RE.match(v)):
        return f'color must be a hex colour like "#8a5a3b", got {v!r}'
    if k in ("gloss", "grainContrast") and not (num(v) and 0 <= v <= 1):
        return f"{k} must be a number from 0 to 1, got {v!r}"
    if k == "seed" and not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
        return f"seed must be a positive integer, got {v!r}"
    if k == "label" and not isinstance(v, str):
        return "label must be text"
    return None


def custom_problems(jid, inst, reg):
    """Problems with one entry of a job's "materials" (a customised copy of a registry material)."""
    where = f'materials.{jid}'
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", jid):
        return [f"{where}: id must be lowercase letters, digits and hyphens"]
    if jid in reg["materials"]:
        return [f'{where}: id clashes with the registry material "{jid}"; choose another id']
    if not isinstance(inst, dict):
        return [f"{where}: must be an object like {{\"base\": \"custom-rift\", \"color\": \"#8a5a3b\"}}"]
    base = inst.get("base")
    bdef = reg["materials"].get(base)
    if not bdef:
        return [f'{where}: base "{base}" is not in the registry']
    if not isinstance(bdef.get("custom"), dict):
        custom_ids = sorted(k for k, d in reg["materials"].items() if isinstance(d.get("custom"), dict))
        return [f'{where}: base "{base}" is not customisable; use one of {", ".join(custom_ids)}']
    out = []
    for k, v in inst.items():
        if k == "base":
            continue
        p = custom_option_problem(k, v)
        if p:
            out.append(f"{where}: {p}")
        elif k in ("seed", "grainContrast") and bdef.get("kind") != "procedural":
            out.append(f"{where}: {k} only applies to wood bases")
    return out


# ----------------------------------------------------------------------------- validation
def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


FRONT_STYLES = {"shaker", "slab", "slat", "appliance", "none"}
APPLIANCE_KINDS = {"wall-oven", "microwave-drawer", "warming-drawer", "wine-column", "dishwasher", "refrigerator", "panel"}
HARDWARE_TYPES = {"knob", "bar", "appliance-pull", "edge-pull", "tab", "finger-groove", "push-latch", "none"}
BASE_TYPES = {"recessed", "flush", "applied", "none"}
AUTO_VIEW_IDS = ["overview", "north", "east", "south", "west"]


def run_front_bottom(run, defaults):
    """Height where fronts start (top of base, or underside of a wall cabinet)."""
    if run.get("mount") == "wall":
        return run.get("bottom", defaults.get("wallBottom", 54))
    b = run.get("base", True)
    if b is False:
        return 0
    b = b if isinstance(b, dict) else {}
    t = b.get("type", "recessed")
    if t == "flush":
        return b.get("height", 4) + b.get("reveal", 0.25)
    if t == "applied":
        return b.get("height", 4) + b.get("reveal", 0.125)
    if t == "none":
        return b.get("height", 0)
    db = {"toeHeight": 2.5, "bandHeight": 2, **defaults.get("base", {})}
    return b.get("toeHeight", db["toeHeight"]) + b.get("bandHeight", db["bandHeight"])


def view_ids(job):
    own = [v.get("id") for v in job.get("views") or []]
    if not own or job.get("autoViews"):
        return own + [a for a in AUTO_VIEW_IDS if a not in own]
    return own


def point_in_poly(x, z, poly):
    inside = False
    for i in range(len(poly)):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % len(poly)]
        if (z1 > z) != (z2 > z) and x < (x2 - x1) * (z - z1) / (z2 - z1) + x1:
            inside = not inside
    return inside


def on_poly_or_inside(x, z, poly):
    if point_in_poly(x, z, poly):
        return True
    for i in range(len(poly)):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % len(poly)]
        if abs((x2 - x1) * (z - z1) - (z2 - z1) * (x - x1)) < 1e-6 and min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6 and min(z1, z2) - 1e-6 <= z <= max(z1, z2) + 1e-6:
            return True
    return False


def is_pt(p, n):
    return isinstance(p, list) and len(p) == n and all(num(v) for v in p)


def coplanar_warnings(job, eps=1e-6):
    """Boxes/walls that overlap AND have a face in the same plane facing the same way flicker in the viewer
    (z-fighting: the GPU cannot decide which surface is in front). Faces that merely touch back to back are fine."""
    solids = []
    for o in job.get("objects") or []:
        if o.get("type") in ("box", "wall", "paneling") and is_pt(o.get("min"), 3) and is_pt(o.get("max"), 3):
            solids.append((o.get("id") or o.get("type"), o["min"], o["max"]))
    pairs, axes = [], "xyz"
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            (na, amin, amax), (nb, bmin, bmax) = solids[i], solids[j]
            planes = []
            for ax in range(3):
                o1, o2 = [k for k in range(3) if k != ax]
                ov = lambda k: min(amax[k], bmax[k]) - max(amin[k], bmin[k])
                if ov(o1) <= eps or ov(o2) <= eps:
                    continue
                for side, va, vb in (("min", amin[ax], bmin[ax]), ("max", amax[ax], bmax[ax])):
                    if abs(va - vb) <= eps:
                        planes.append(f"{axes[ax]}={va:g}")
            if planes:
                pairs.append(f'"{na}" + "{nb}" ({", ".join(planes)})')
    if not pairs:
        return []
    shown = pairs[:8]
    more = f" ... and {len(pairs) - 8} more pairs" if len(pairs) > 8 else ""
    return ["possible flicker (z-fighting): these objects overlap with faces in the same plane: " + "; ".join(shown) + more +
            '. Only faces you can see matter (faces hidden against a wall are harmless). Fix visible ones by moving one face about 0.05" '
            "or making the objects meet edge to edge instead of overlapping."]


def validate_job(job, reg):
    """Return (errors, warnings, report). report holds computed world geometry for checking against drawings."""
    errors, warnings = [], []
    mats = dict(reg["materials"])
    for jid, inst in (job.get("materials") or {}).items():
        errors.extend(custom_problems(jid, inst, reg))
        mats[jid] = {"kind": "custom-instance"}

    def need_mat(mid, where, allow_auto=False):
        if mid is None or (allow_auto and mid == "auto"):
            return
        if mid not in mats:
            errors.append(f'{where}: unknown material "{mid}" (see "textures list" or define it in the job\'s "materials")')

    if job.get("schema") != SCHEMA:
        warnings.append(f'"schema" should be "{SCHEMA}"')
    defaults = job.get("defaults", {})
    box_top = defaults.get("boxTop", 34.5)
    reveal = defaults.get("reveal", 0.125)
    margin = defaults.get("frontMargin", 0.1)
    T = defaults.get("frontThickness", 0.75)

    for role, mid in (job.get("finishes") or {}).items():
        need_mat(mid, f"finishes.{role}", allow_auto=(role == "groove"))

    def check_front(f, iw):
        st = f.get("style", "shaker")
        if st not in FRONT_STYLES:
            errors.append(f"{iw}: front style must be one of {sorted(FRONT_STYLES)}")
        if st == "appliance":
            if f.get("kind", "panel") not in APPLIANCE_KINDS:
                errors.append(f"{iw}: appliance kind must be one of {sorted(APPLIANCE_KINDS)}")
            need_mat(f.get("material"), iw + " appliance")
            need_mat(f.get("glass"), iw + " appliance glass")
        for k in ("slatWidth", "gap", "depth", "stile"):
            if k in f and not (num(f[k]) and f[k] > 0):
                errors.append(f"{iw}: {k} must be a positive number")
        for hw in ([f["hardware"]] if isinstance(f.get("hardware"), dict) else f.get("hardware") or []):
            if hw.get("type", "knob") not in HARDWARE_TYPES:
                errors.append(f"{iw}: hardware type must be one of {sorted(HARDWARE_TYPES)}")
            need_mat(hw.get("material"), f"{iw} hardware")
            need_mat(hw.get("finish"), f"{iw} hardware finish")

    def check_rows(rows, span, iw):
        rows = rows or [{"height": "fill"}]
        fixed = sum(r.get("height") for r in rows if num(r.get("height")))
        fills = sum(1 for r in rows if not num(r.get("height")))
        used = fixed + reveal * (len(rows) - 1)
        if fills == 0 and abs(used - span) > 0.25:
            warnings.append(f"{iw}: rows + reveals = {used:.2f} but the space is {span:.2f}; use \"fill\" on one row")
        if fills and used >= span:
            errors.append(f"{iw}: fixed row heights ({used:.2f}) leave no room for the fill row (space {span:.2f})")
        fill_h = (span - used) / fills if fills else 0
        for ri_, r in enumerate(rows):
            h = r["height"] if num(r.get("height")) else fill_h
            if "columns" in r:
                if "fronts" in r:
                    errors.append(f"{iw} row {ri_}: use either fronts or columns, not both")
                cols = r.get("columns") or []
                if not cols:
                    errors.append(f"{iw} row {ri_}: columns is empty")
                for ci_, c in enumerate(cols):
                    if "width" in c and not (num(c["width"]) and c["width"] > 0):
                        errors.append(f"{iw} row {ri_} column {ci_}: width must be a positive number")
                    check_rows(c.get("rows"), h, f"{iw} row {ri_} column {ci_}")
            else:
                for f in r.get("fronts") or []:
                    check_front(f, f"{iw} row {ri_}")

    report = {"runs": [], "counters": [], "objects": []}
    ids = set()
    for ri, run in enumerate(job.get("runs") or []):
        where = f'runs[{ri}] ("{run.get("id", "?")}")'
        if run.get("id") in ids:
            errors.append(f"{where}: duplicate id")
        ids.add(run.get("id"))
        n = FACINGS.get(run.get("facing"))
        if not n:
            errors.append(f"{where}: facing must be N, S, E or W (the direction the fronts point)")
            continue
        o = run.get("origin")
        if not is_pt(o, 2):
            errors.append(f"{where}: origin must be [x, z] (back-left corner, inches)")
            continue
        for role, mid in (run.get("finishes") or {}).items():
            need_mat(mid, f"{where} finishes.{role}", allow_auto=(role == "groove"))
        mount = run.get("mount", "floor")
        if mount not in ("floor", "wall"):
            errors.append(f'{where}: mount must be "floor" or "wall"')
        b = run.get("base")
        if isinstance(b, dict) and b.get("type", "recessed") not in BASE_TYPES:
            errors.append(f"{where}: base.type must be one of {sorted(BASE_TYPES)}")
        if mount == "wall" and isinstance(b, dict):
            warnings.append(f"{where}: wall runs have no base; base is ignored")
        so = run.get("soffit")
        if so is not None:
            if not (isinstance(so, dict) and num(so.get("to"))):
                errors.append(f'{where}: soffit needs "to" (height of the ceiling or soffit top)')
            else:
                need_mat(so.get("material"), f"{where} soffit")
        depth = run.get("depth", 12 if mount == "wall" else 24)
        bottom_front = run_front_bottom(run, defaults)
        rtop = run.get("boxTop", (bottom_front + 30) if mount == "wall" else box_top)
        if isinstance(so, dict) and num(so.get("to")) and so["to"] <= rtop:
            errors.append(f"{where}: soffit.to ({so['to']}) must be above the cabinet top ({rtop})")
        if rtop <= bottom_front:
            errors.append(f"{where}: boxTop ({rtop}) must be above the bottom of the fronts ({bottom_front})")
        a = (n[1], -n[0])
        P = lambda s, t: [round(o[0] + a[0] * s + n[0] * t, 3), round(o[1] + a[1] * s + n[1] * t, 3)]
        s = 0.0
        items_out = []
        items = run.get("items") or []
        if not items:
            warnings.append(f"{where}: has no items")
        for ii, it in enumerate(items):
            iw = f"{where} item {ii} ({it.get('id') or it.get('label') or it.get('type')})"
            t = it.get("type")
            if t not in ITEM_TYPES:
                errors.append(f"{iw}: type must be one of {sorted(ITEM_TYPES)}")
                continue
            w = it.get("width", T if t == "end-panel" else None)
            if not num(w) or w <= 0:
                errors.append(f"{iw}: width (inches) is required")
                continue
            if t == "end-panel" and 0 < ii < len(items) - 1:
                errors.append(f"{iw}: end-panel must be the first or last item of a run")
            if t == "end-panel" and it.get("style", "shaker") not in ("shaker", "slab", "slat"):
                errors.append(f"{iw}: end-panel style must be shaker, slab or slat")
            if t == "cabinet":
                check_rows(it.get("rows"), rtop - bottom_front - 2 * margin, iw)
            items_out.append({"index": ii, "type": t, "id": it.get("id"), "label": it.get("label"), "width": w,
                              "from": P(s, 0), "to": P(s + w, 0)})
            s += w
        report["runs"].append({
            "id": run.get("id"), "facing": run.get("facing"), "mount": mount, "length": round(s, 3), "depth": depth,
            "frontsFrom": round(bottom_front, 3), "boxTop": rtop,
            "backLeft": P(0, 0), "backRight": P(s, 0), "frontLeft": P(0, depth + T), "frontRight": P(s, depth + T),
            "items": items_out,
        })

    for ci, c in enumerate(job.get("counters") or []):
        where = f'counters[{ci}] ("{c.get("id", "?")}")'
        need_mat(c.get("material"), where)
        if not c.get("material"):
            errors.append(f"{where}: material is required")
        edge = c.get("edge", "eased")
        prof = edge.get("profile") if isinstance(edge, dict) else edge
        if prof not in ("eased", "square", "mitered"):
            errors.append(f'{where}: edge must be "eased", "square" or "mitered" (or {{"profile": ..., "height": ...}})')
        cuts = c.get("cutouts") or []
        for k in cuts:
            if not all(num(k.get(q)) for q in ("x0", "x1", "z0", "z1")) or k["x1"] <= k["x0"] or k["z1"] <= k["z0"]:
                errors.append(f"{where}: cutouts need x0 < x1 and z0 < z1")
        wf = c.get("waterfall") or []
        if c.get("outline") is not None:
            ol = c["outline"]
            if not (isinstance(ol, list) and len(ol) >= 3 and all(is_pt(p, 2) for p in ol)):
                errors.append(f"{where}: outline must be a list of at least 3 [x, z] points")
                continue
            for k in cuts:
                if all(num(k.get(q)) for q in ("x0", "x1", "z0", "z1")):
                    corners = ((k["x0"], k["z0"]), (k["x1"], k["z0"]), (k["x1"], k["z1"]), (k["x0"], k["z1"]))
                    if not all(point_in_poly(x, z, ol) for x, z in corners):
                        errors.append(f"{where}: on an outline counter a cutout must sit fully inside the outline")
            for w_ in wf:
                e = w_.get("edge") if isinstance(w_, dict) else w_
                if not (isinstance(e, int) and 0 <= e < len(ol)):
                    errors.append(f"{where}: outline waterfalls are edge indexes 0..{len(ol) - 1} (edge i runs from point i to point i+1)")
            report["counters"].append({"id": c.get("id"), "outline": ol, "cutouts": cuts})
        else:
            if not all(num(c.get(k)) for k in ("x0", "x1", "z0", "z1")):
                errors.append(f"{where}: give x0, x1, z0, z1 (rectangle) or an outline")
                continue
            if c["x1"] <= c["x0"] or c["z1"] <= c["z0"]:
                errors.append(f"{where}: needs x0 < x1 and z0 < z1")
            for k in cuts:
                if all(num(k.get(q)) for q in ("x0", "x1", "z0", "z1")) and (k["x1"] <= c["x0"] or k["x0"] >= c["x1"] or k["z1"] <= c["z0"] or k["z0"] >= c["z1"]):
                    errors.append(f"{where}: a cutout does not overlap the counter")
            for w_ in wf:
                if w_ not in ("start", "end", "north", "south", "east", "west"):
                    errors.append(f'{where}: rectangle waterfalls are "start", "end", "north", "south", "east" or "west"')
            report["counters"].append({"id": c.get("id"), "outline": [[c["x0"], c["z0"]], [c["x1"], c["z0"]], [c["x1"], c["z1"]], [c["x0"], c["z1"]]], "cutouts": cuts})

    for oi, ob in enumerate(job.get("objects") or []):
        where = f'objects[{oi}] ("{ob.get("id") or ob.get("type")}")'
        t = ob.get("type")
        if t not in OBJECT_TYPES:
            errors.append(f"{where}: type must be one of {sorted(OBJECT_TYPES)}")
            continue
        for k in ("material", "glass", "grateMaterial", "knobMaterial"):
            need_mat(ob.get(k), f"{where} {k}")
        rect4 = all(num(ob.get(q)) for q in ("x0", "x1", "z0", "z1"))
        if t in ("box", "wall", "paneling"):
            mn, mx = ob.get("min"), ob.get("max")
            if not (is_pt(mn, 3) and is_pt(mx, 3)):
                errors.append(f"{where}: min and max must be [x, y, z]")
            elif any(mx[i] <= mn[i] for i in range(3)):
                errors.append(f"{where}: every max value must be larger than the matching min value")
            else:
                report["objects"].append({"id": ob.get("id"), "type": t, "rect": [mn[0], mx[0], mn[2], mx[2]], "top": mx[1]})
            if t == "box" and not ob.get("material"):
                errors.append(f"{where}: material is required")
            if t == "paneling" and ob.get("facing") not in FACINGS:
                errors.append(f"{where}: paneling needs facing N, S, E or W (the side facing the room)")
            for op in ob.get("openings") or []:
                need_mat(op.get("jamb"), where + " opening jamb")
                need_mat(op.get("glassMaterial"), where + " opening glass")
                need_mat(op.get("panelMaterial"), where + " opening panel")
                need_mat((op.get("trim") or {}).get("material"), where + " opening trim")
                need_mat((op.get("frame") or {}).get("material"), where + " opening frame")
                need_mat((op.get("mullions") or op.get("muntins") or {}).get("material"), where + " opening mullions")
                if op.get("kind", "window") not in ("window", "door"):
                    errors.append(f'{where}: opening kind must be "window" or "door"')
                if op.get("shape") is not None:
                    if not (isinstance(op["shape"], list) and len(op["shape"]) >= 3 and all(is_pt(p, 2) for p in op["shape"])):
                        errors.append(f"{where}: opening shape must be at least 3 [along, height] points")
                else:
                    need = ("a0", "a1", "y1") if op.get("kind") == "door" else ("a0", "a1", "y0", "y1")
                    if not all(num(op.get(q)) for q in need):
                        errors.append(f"{where}: openings need {', '.join(need)} (a = along the wall), or a shape polygon")
                if op.get("swing") not in (None, "left", "right"):
                    errors.append(f'{where}: door swing must be "left" or "right"')
        if t in ("faucet", "outlet"):
            if not is_pt(ob.get("position"), 3):
                errors.append(f"{where}: position must be [x, y, z]")
            if ob.get("facing", "S") not in FACINGS:
                errors.append(f"{where}: facing must be N, S, E or W")
        if t in ("sink", "rangetop", "hood", "shelf"):
            if not rect4:
                errors.append(f"{where}: x0, x1, z0, z1 are required")
            else:
                report["objects"].append({"id": ob.get("id"), "type": t, "rect": [ob["x0"], ob["x1"], ob["z0"], ob["z1"]]})
        if t == "sink" and "drain" in ob:
            dr = ob["drain"]
            if isinstance(dr, dict):
                if "diameter" in dr and not (num(dr["diameter"]) and dr["diameter"] > 0):
                    errors.append(f"{where}: drain.diameter must be a positive number (inches)")
                if "position" in dr and not is_pt(dr["position"], 2):
                    errors.append(f"{where}: drain.position must be [x, z]")
                need_mat(dr.get("material"), where + " drain")
            elif not isinstance(dr, bool):
                errors.append(f"{where}: drain must be true, false or {{diameter, position, material}}")
        if t == "rangetop" and ob.get("facing", "S") not in FACINGS:
            errors.append(f"{where}: facing (the side with the control knobs) must be N, S, E or W")
        if t == "hood":
            if not (num(ob.get("bottom")) and num(ob.get("top")) and ob["top"] > ob["bottom"]):
                errors.append(f"{where}: hood needs bottom and top heights (top > bottom)")
            if ob.get("shape", "box") not in ("box", "tapered"):
                errors.append(f'{where}: hood shape must be "box" or "tapered"')
            if ob.get("wall", "N") not in FACINGS:
                errors.append(f"{where}: hood wall (side against the wall) must be N, S, E or W")
            ch = ob.get("chimney") or {}
            if ch and ch.get("shape", "square") not in ("round", "square"):
                errors.append(f'{where}: chimney shape must be "round" or "square"')
            need_mat((ob.get("band") or {}).get("material"), where + " band")
        if t == "shelf" and not num(ob.get("y")):
            errors.append(f"{where}: shelf needs y (height of the shelf top)")
        if t == "leg":
            if not (is_pt(ob.get("position"), 2) and num(ob.get("height"))):
                errors.append(f"{where}: leg needs position [x, z] and height")
            else:
                s_ = ob.get("size", 4) / 2
                report["objects"].append({"id": ob.get("id"), "type": t, "rect": [ob["position"][0] - s_, ob["position"][0] + s_, ob["position"][1] - s_, ob["position"][1] + s_]})
        if t == "ceiling":
            if not (is_pt(ob.get("min"), 2) and is_pt(ob.get("max"), 2) and num(ob.get("height"))):
                errors.append(f"{where}: ceiling needs min [x, z], max [x, z] and height")
            sl = ob.get("slope")
            if sl and not (sl.get("axis") in ("x", "z") and num(sl.get("rise")) and num(sl.get("run")) and sl["run"] != 0):
                errors.append(f'{where}: slope needs axis "x" or "z", rise and run (and optional from)')
            if "hiddenFromAbove" in ob and not isinstance(ob["hiddenFromAbove"], bool):
                errors.append(f"{where}: hiddenFromAbove must be true (cutaway, default) or false (solid from above)")
            if is_pt(ob.get("min"), 2) and is_pt(ob.get("max"), 2) and (ob["min"][0] == ob["max"][0] or ob["min"][1] == ob["max"][1]):
                errors.append(f"{where}: ceiling min and max must differ in both x and z")
        if t == "led-strip" and not (is_pt(ob.get("from"), 3) and is_pt(ob.get("to"), 3)):
            errors.append(f"{where}: led-strip needs from [x, y, z] and to [x, y, z]")
        if t == "tube-shelving":
            posts = ob.get("posts") or []
            for lv in ob.get("levels") or []:
                b_ = lv.get("between") or []
                if len(b_) != 2 or not all(isinstance(i, int) and 0 <= i < len(posts) for i in b_):
                    errors.append(f"{where}: level between must be two indexes into posts")

    warnings.extend(coplanar_warnings(job))

    views = job.get("views") or []
    if not views:
        warnings.append("no views defined; automatic overview + north/east/south/west views will be used")
    vids = set()
    for vi, v in enumerate(views):
        if v.get("id") in vids:
            errors.append(f"views[{vi}]: duplicate id {v.get('id')}")
        vids.add(v.get("id"))
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", str(v.get("id", ""))):
            errors.append(f"views[{vi}]: id must be lowercase letters, digits, hyphens")
        for k in ("position", "target"):
            if not is_pt(v.get(k), 3):
                errors.append(f"views[{vi}] ({v.get('id')}): {k} must be [x, y, z]")
    report["views"] = view_ids(job)
    return errors, warnings, report


# ----------------------------------------------------------------------------- server
class Events:
    def __init__(self):
        self.q = queue.Queue()


def make_handler(events):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def log_message(self, fmt, *args):
            if os.environ.get("CPR_HTTP_LOG"):
                super().log_message(fmt, *args)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._index()
            if u.path == "/api/jobs":
                return self._json(200, list_jobs())
            parts = u.path.strip("/").split("/")
            if parts and parts[0] in (".git", "runtime"):
                return self.send_error(HTTPStatus.NOT_FOUND)
            return super().do_GET()

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024 * 1024:
                return self._json(413, {"error": "too large"})
            data = self.rfile.read(length)
            if u.path == "/api/save":
                p = (q.get("path") or [""])[0]
                target = (ROOT / p).resolve()
                if not p or not inside_root(target) or target.suffix.lower() != ".png" or ".git" in target.parts:
                    return self._json(400, {"error": "path must be a .png inside the project"})
                if not data.startswith(b"\x89PNG"):
                    return self._json(400, {"error": "body is not a PNG"})
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                events.q.put({"kind": "saved", "path": rel(target)})
                return self._json(200, {"path": rel(target)})
            if u.path == "/api/log":
                try:
                    events.q.put(json.loads(data.decode("utf-8") or "{}"))
                except Exception:
                    events.q.put({"kind": "log", "text": data.decode("utf-8", "replace")})
                return self._json(200, {"ok": True})
            return self._json(404, {"error": "unknown endpoint"})

        def _index(self):
            rows = []
            for j in list_jobs():
                name = urllib.parse.quote(j["ref"])
                srcs = "".join(f'<li><a href="/engine/pdf.html?file={urllib.parse.quote(s)}&grid=1">{s}</a></li>' for s in j["sources"])
                rows.append(f'<h2>{j["title"]}</h2><p><a href="/engine/viewer.html?job={name}">Open 3D viewer</a> &middot; job folder jobs/{j["ref"]}</p><ul>{srcs}</ul>')
            html = ("<!doctype html><meta charset='utf-8'><title>Cabinet Preview Renderer</title>"
                    "<body style='font:14px system-ui;margin:24px'><h1>Cabinet Preview Renderer</h1>"
                    + ("".join(rows) or "<p>No jobs yet. Run new-job.</p>") + "</body>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    return Handler


def list_jobs():
    out = []
    folders = [d for root_ in (JOBS, EXAMPLE_JOBS) if root_.exists() for d in sorted(root_.iterdir()) if d.is_dir()]
    for d in folders:
        jf = d / "job.json"
        if not jf.is_file():
            continue
        try:
            title = load_json(jf).get("info", {}).get("title") or d.name
        except CprError:
            title = d.name + " (invalid JSON)"
        srcs = sorted(rel(p) for p in (d / "source").glob("*") if p.suffix.lower() == ".pdf") if (d / "source").exists() else []
        out.append({"name": d.name, "ref": job_ref(d), "example": d.parent == EXAMPLE_JOBS, "title": title, "sources": srcs})
    return out


def start_server(port, host="127.0.0.1"):
    events = Events()
    httpd = ThreadingHTTPServer((host, port), make_handler(events))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, events


# ----------------------------------------------------------------------------- headless browser
def find_browser(explicit=None):
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get("CPR_BROWSER"):
        cands.append(os.environ["CPR_BROWSER"])
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    elif sys.platform == "darwin":
        cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"):
        w = shutil.which(n)
        if w:
            cands.append(w)
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def run_headless(url, size, expect, timeout, events, browser=None):
    """Open url in a headless Chromium-family browser and wait for the page to report done/error via /api/log."""
    exe = find_browser(browser)
    if not exe:
        raise CprError("No Chrome, Edge or Chromium found for headless rendering. Install one, pass --browser PATH, "
                       "or set CPR_BROWSER. Alternative: start serve and open the printed capture URL in your own browser tool.")
    prof = tempfile.mkdtemp(prefix="cpr-browser-")
    args = [exe, "--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--hide-scrollbars",
            "--mute-audio", f"--user-data-dir={prof}", f"--window-size={size[0]},{size[1]}", url]
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(args, **kw)
    saved, result = [], None
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                ev = events.q.get(timeout=0.5)
            except queue.Empty:
                if proc.poll() is not None and result is None:
                    raise CprError(f"The browser exited early (code {proc.returncode}).")
                continue
            if ev.get("kind") == "saved":
                saved.append(ev["path"])
            elif ev.get("kind") == "error":
                raise CprError("Page error: " + str(ev.get("error")))
            elif ev.get("kind") == "done":
                result = ev
                break
        if result is None:
            raise CprError(f"Timed out after {timeout}s waiting for the page (expected {expect} image(s), got {len(saved)}). "
                           "The page loads three.js/pdf.js from a CDN, so internet access is required.")
        return result, saved
    finally:
        kill_tree(proc)
        shutil.rmtree(prof, ignore_errors=True)


def kill_tree(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ----------------------------------------------------------------------------- commands
def cmd_doctor(a):
    print(f"project root : {ROOT}")
    print(f"python       : {sys.version.split()[0]} ({sys.executable})")
    ok = sys.version_info >= (3, 8)
    print(f"python ok    : {'yes' if ok else 'NO, need 3.8+'}")
    b = find_browser(a.browser)
    print(f"browser      : {b or 'NOT FOUND (capture and pdf-snap need Chrome, Edge or Chromium)'}")
    reg = load_registry()
    probs = registry_problems(reg)
    print(f"materials    : {len(reg['materials'])} registered, {len(probs)} problem(s)")
    for p in probs:
        print("  - " + p)
    jobs = list_jobs()
    print(f"jobs         : {', '.join(j['name'] for j in jobs if not j['example']) or 'none'}")
    print(f"examples     : {', '.join(j['name'] for j in jobs if j['example']) or 'none'}   (in jobs/examples/)")
    missing = [f for f in VENDOR_FILES if not (VENDOR / f).is_file()]
    print("libraries    : " + ("vendor/ complete (works offline)" if not missing else "vendor/ missing " + ", ".join(missing) + " -> pages use the internet CDN; run: vendor"))
    return 0 if ok and not probs else 1


def cmd_new_job(a):
    d = job_dir(a.name)
    existing = find_job(a.name)
    if existing:
        raise CprError(f"Job {a.name} already exists at {rel(existing)}.")
    tmpl = load_json(ROOT / "templates" / "job.template.json")
    tmpl["info"]["title"] = a.title or a.name.replace("-", " ").title()
    save_json(d / "job.json", tmpl)
    (d / "source").mkdir(parents=True, exist_ok=True)
    (d / "output").mkdir(parents=True, exist_ok=True)
    copied = []
    for s in a.source or []:
        copied.append(copy_source(d, s))
    print(f"Created {rel(d / 'job.json')}")
    for c in copied:
        print(f"Copied source {c}")
    print("Next: read the drawings, edit job.json, then run validate.")
    return 0


def copy_source(d, src):
    sp = Path(src).expanduser()
    if not sp.is_file():
        raise CprError(f"Source file not found: {src}")
    dest = d / "source" / re.sub(r"[^A-Za-z0-9._-]+", "-", sp.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sp, dest)
    return rel(dest)


def cmd_add_source(a):
    d = require_job(a.job)
    for s in a.files:
        print(f"Copied {copy_source(d, s)}")
    return 0


def cmd_validate(a):
    d = require_job(a.job)
    reg = load_registry()
    job = load_json(d / "job.json")
    errors, warnings, report = validate_job(job, reg)
    if a.json:
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings, "report": report}, indent=2))
        return 1 if errors else 0
    print(f"Job {a.job}: {len(errors)} error(s), {len(warnings)} warning(s)")
    for e in errors:
        print("  ERROR   " + e)
    for w in warnings:
        print("  warning " + w)
    print("\nRun geometry (world inches; x = east/right on plan, z = south/down on plan):")
    for r in report["runs"]:
        print(f"  run {r['id']} ({r['mount']}) facing {r['facing']}: length {r['length']}, depth {r['depth']}, fronts {r['frontsFrom']} to {r['boxTop']}")
        print(f"    back  {r['backLeft']} -> {r['backRight']}")
        print(f"    front {r['frontLeft']} -> {r['frontRight']}  (front face of doors)")
        for it in r["items"]:
            print(f"      [{it['index']}] {it['type']:<9} w={it['width']:<7} {it['from']} -> {it['to']}  {it['label'] or it['id'] or ''}")
    print("\nViews: " + ", ".join(report["views"]) + ("   (includes automatic views)" if (not job.get("views") or job.get("autoViews")) else ""))
    return 1 if errors else 0


def cmd_serve(a):
    httpd, _ = start_server(a.port, a.host)
    base = f"http://{a.host}:{a.port}"
    print(f"Serving {ROOT} at {base}/  (Ctrl+C to stop)")
    for j in list_jobs():
        print(f"  viewer : {base}/engine/viewer.html?job={urllib.parse.quote(j['ref'])}")
        print(f"  capture: {base}/engine/viewer.html?job={urllib.parse.quote(j['ref'])}&capture=1&save=all   (saves PNGs to jobs/{j['ref']}/output/)")
        for s in j["sources"]:
            print(f"  pdf    : {base}/engine/pdf.html?file={urllib.parse.quote(s)}&grid=1")
    sys.stdout.flush()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0


VENDOR = ROOT / "vendor"
VENDOR_FILES = {
    "three.min.js": "https://cdn.jsdelivr.net/npm/three@0.147.0/build/three.min.js",
    "OrbitControls.js": "https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/controls/OrbitControls.js",
    "RoomEnvironment.js": "https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/environments/RoomEnvironment.js",
    "pdf.min.js": "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",
    "pdf.worker.min.js": "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js",
}
VIEWER_LIBS = ["three.min.js", "OrbitControls.js", "RoomEnvironment.js"]
CDN_LIBS_HTML = ('<script src="https://cdn.jsdelivr.net/npm/three@0.147.0/build/three.min.js"></script>\n'
                 '<script src="https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/controls/OrbitControls.js"></script>\n'
                 '<script src="https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/environments/RoomEnvironment.js"></script>')


def fetch_vendor(force=False, quiet=False):
    """Download the pinned browser libraries into vendor/ (skips files already there)."""
    import urllib.request
    VENDOR.mkdir(exist_ok=True)
    got = []
    for name, url in VENDOR_FILES.items():
        dest = VENDOR / name
        if dest.is_file() and dest.stat().st_size > 1000 and not force:
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
        except Exception as e:
            raise CprError(f"Could not download {url}: {e}. Check the internet connection, or copy the file into vendor/ by hand.")
        dest.write_bytes(data)
        got.append(name)
        if not quiet:
            print(f"Downloaded vendor/{name} ({len(data) // 1024} KB)")
    return got


def cmd_vendor(a):
    got = fetch_vendor(force=a.force)
    if not got:
        print("vendor/ already has every library. Use --force to download again.")
    return 0


def all_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from all_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from all_strings(v)


def used_materials(job):
    """Every registry id that the job could reference (any string value), plus bases of job materials."""
    used = set(all_strings(job))
    used |= {m.get("base") for m in (job.get("materials") or {}).values() if isinstance(m, dict)}
    used.discard(None)
    return used


def build_standalone(name, out=None, libs="auto"):
    """libs: "inline" (put three.js inside the file, works offline), "cdn" (small file, needs internet), "auto" (inline when vendor/ has the files)."""
    d = require_job(name)
    reg = load_registry()
    job = load_json(d / "job.json")
    errors, _, _ = validate_job(job, reg)
    if errors:
        raise CprError("Fix validation errors first:\n  " + "\n  ".join(errors))
    html = (ENGINE / "viewer.html").read_text(encoding="utf-8")
    images = {}
    for mid in used_materials(job):
        m = reg["materials"].get(mid, {})
        if m.get("kind") == "image":
            p = TEXTURES / m["file"]
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}[p.suffix.lower().lstrip(".")]
            images[mid] = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    boot = {"job": job, "registry": {"materials": dict(reg["materials"])}, "images": images}

    def script(js):
        return "<script>\n" + js.replace("</script", "<\\/script") + "\n</script>"
    have_vendor = all((VENDOR / f).is_file() for f in VIEWER_LIBS)
    if libs == "inline" and not have_vendor:
        fetch_vendor(quiet=True)
        have_vendor = True
    if libs == "inline" or (libs == "auto" and have_vendor):
        libs_html = "\n".join(script((VENDOR / f).read_text(encoding="utf-8")) for f in VIEWER_LIBS)
        mode = "inline"
    else:
        libs_html, mode = CDN_LIBS_HTML, "cdn"
    engine_js = script((ENGINE / "textures.js").read_text(encoding="utf-8")) + "\n" + script((ENGINE / "engine.js").read_text(encoding="utf-8"))
    boot_js = script("window.CPR_BOOT = " + json.dumps(boot).replace("</", "<\\/") + ";")
    html = re.sub(r"<!--CPR:LIBS-->.*?<!--/CPR:LIBS-->", lambda m: libs_html, html, flags=re.S)
    html = re.sub(r"<!--CPR:ENGINE-->.*?<!--/CPR:ENGINE-->", lambda m: engine_js, html, flags=re.S)
    html = html.replace("<!--CPR:BOOT-->", boot_js + "\n<!--CPR:BOOT-->")
    title = (job.get("info") or {}).get("title") or name
    html = re.sub(r"<title>.*?</title>", lambda m: "<title>" + title.replace("<", "") + "</title>", html, count=1)
    out = Path(out) if out else d / "output" / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return out, mode


def cmd_build(a):
    libs = "inline" if a.inline_libs else "cdn" if a.cdn else "auto"
    out, mode = build_standalone(a.job, a.out, libs)
    note = "three.js is inside the file: it works offline and in sandboxed file previews" if mode == "inline" else "loads three.js from the internet"
    print(f"Built {rel(out)} ({out.stat().st_size // 1024} KB); {note}. Opens by double-click in any browser.")
    return 0


def cmd_open(a):
    """Build the standalone viewer and open it in the computer's default browser."""
    import webbrowser
    out, mode = build_standalone(a.job, None, "auto")
    print(f"Built {rel(out)} ({'offline-capable' if mode == 'inline' else 'needs internet'})")
    if a.no_launch:
        print(f"File: {out.resolve()}")
        return 0
    ok = webbrowser.open(out.resolve().as_uri())
    print(("Opened in the default browser: " if ok else "Could not launch a browser. Open this file yourself: ") + str(out.resolve()))
    return 0


# ----------------------------------------------------------------------------- plan (top-down SVG)
def plan_svg(job, report, title):
    pts = []
    for r in report["runs"]:
        pts += [r["backLeft"], r["backRight"], r["frontLeft"], r["frontRight"]]
    for c in report["counters"]:
        pts += c["outline"]
    for o in report["objects"]:
        x0, x1, z0, z1 = o["rect"]
        pts += [[x0, z0], [x1, z1]]
    vids = []
    for v in job.get("views") or []:
        pts.append([v["position"][0], v["position"][2]])
        vids.append(v)
    if not pts:
        raise CprError("Nothing to draw: the job has no runs, counters or objects.")
    xs, zs = [p[0] for p in pts], [p[1] for p in pts]
    minx, maxx, minz, maxz = min(xs) - 24, max(xs) + 24, min(zs) - 24, max(zs) + 40
    S = 4.0                                     # px per inch
    W, H = (maxx - minx) * S, (maxz - minz) * S
    X = lambda x: round((x - minx) * S, 2)
    Z = lambda z: round((z - minz) * S, 2)
    poly = lambda ps: " ".join(f"{X(p[0])},{Z(p[1])}" for p in ps)
    esc = lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}" font-family="Arial, sans-serif">',
           f'<rect width="100%" height="100%" fill="#ffffff"/>']
    # 12" grid
    gx = int(minx // 12) * 12
    while gx <= maxx:
        out.append(f'<line x1="{X(gx)}" y1="0" x2="{X(gx)}" y2="{H:.0f}" stroke="#eeeeee" stroke-width="1"/>')
        gx += 12
    gz = int(minz // 12) * 12
    while gz <= maxz:
        out.append(f'<line x1="0" y1="{Z(gz)}" x2="{W:.0f}" y2="{Z(gz)}" stroke="#eeeeee" stroke-width="1"/>')
        gz += 12
    # walls / boxes / objects
    style = {"wall": ('#9a968e', '#5c5952'), "box": ('#e4e1da', '#a7a39a'), "paneling": ('#b99b7a', '#7a6248'),
             "sink": ('#ffffff', '#555555'), "rangetop": ('#cfd1d1', '#333333'), "hood": ('none', '#c03a2b'),
             "shelf": ('#e9dcc6', '#8a7350'), "leg": ('#8a7350', '#5a4a33')}
    for o in sorted(report["objects"], key=lambda o: 0 if o["type"] in ("box", "wall") else 1):
        x0, x1, z0, z1 = o["rect"]
        fill, stroke = style.get(o["type"], ('none', '#777777'))
        dash = ' stroke-dasharray="6 4"' if o["type"] == "hood" else ''
        out.append(f'<rect x="{X(x0)}" y="{Z(z0)}" width="{(x1 - x0) * S:.1f}" height="{(z1 - z0) * S:.1f}" fill="{fill}" fill-opacity="0.85" stroke="{stroke}" stroke-width="1.2"{dash}/>')
    # counters
    for c in report["counters"]:
        out.append(f'<polygon points="{poly(c["outline"])}" fill="#f3ece0" fill-opacity="0.55" stroke="#b28f5f" stroke-width="1.5" stroke-dasharray="8 4"/>')
        for k in c["cutouts"]:
            out.append(f'<rect x="{X(k["x0"])}" y="{Z(k["z0"])}" width="{(k["x1"] - k["x0"]) * S:.1f}" height="{(k["z1"] - k["z0"]) * S:.1f}" fill="#ffffff" stroke="#b28f5f" stroke-width="1"/>')
    # runs
    for r in report["runs"]:
        wall = r["mount"] == "wall"
        fill = "none" if wall else "#d8c9a8"
        dash = ' stroke-dasharray="10 5"' if wall else ""
        col = "#2b6cb0" if wall else "#5b4a2e"
        out.append(f'<polygon points="{poly([r["backLeft"], r["backRight"], r["frontRight"], r["frontLeft"]])}" fill="{fill}" fill-opacity="0.8" stroke="{col}" stroke-width="1.5"{dash}/>')
        out.append(f'<line x1="{X(r["frontLeft"][0])}" y1="{Z(r["frontLeft"][1])}" x2="{X(r["frontRight"][0])}" y2="{Z(r["frontRight"][1])}" stroke="{col}" stroke-width="4"{dash}/>')
        bl, fl = r["backLeft"], r["frontLeft"]
        dvx, dvz = fl[0] - bl[0], fl[1] - bl[1]
        for it in r["items"][1:]:
            p0 = it["from"]
            out.append(f'<line x1="{X(p0[0])}" y1="{Z(p0[1])}" x2="{X(p0[0] + dvx)}" y2="{Z(p0[1] + dvz)}" stroke="{col}" stroke-width="0.8"/>')
        for it in r["items"]:
            if it["type"] != "cabinet":
                continue
            mx = (it["from"][0] + it["to"][0]) / 2 + dvx / 2
            mz = (it["from"][1] + it["to"][1]) / 2 + dvz / 2
            out.append(f'<text x="{X(mx)}" y="{Z(mz) + 4}" font-size="10" text-anchor="middle" fill="{col}">{esc(it["id"] or "")} {it["width"]:g}"</text>')
        cx = (r["backLeft"][0] + r["frontRight"][0]) / 2
        cz = (r["backLeft"][1] + r["frontRight"][1]) / 2
        out.append(f'<text x="{X(cx)}" y="{Z(cz) - 8}" font-size="12" font-weight="bold" text-anchor="middle" fill="{col}">{esc(r["id"])}{" (wall)" if wall else ""}</text>')
    # cameras
    for v in vids:
        px, pz = v["position"][0], v["position"][2]
        tx, tz = v["target"][0], v["target"][2]
        out.append(f'<line x1="{X(px)}" y1="{Z(pz)}" x2="{X(tx)}" y2="{Z(tz)}" stroke="#c03a2b" stroke-width="1" stroke-dasharray="3 3"/>')
        out.append(f'<circle cx="{X(px)}" cy="{Z(pz)}" r="5" fill="#c03a2b"/>')
        out.append(f'<text x="{X(px) + 7}" y="{Z(pz) - 6}" font-size="11" fill="#c03a2b">{esc(v["id"])}</text>')
    # north arrow, scale bar, title
    out.append(f'<g transform="translate({W - 40:.0f},40)"><polygon points="0,-24 8,4 0,-2 -8,4" fill="#222"/><text x="0" y="20" font-size="13" text-anchor="middle">N</text></g>')
    out.append(f'<line x1="20" y1="{H - 20:.0f}" x2="{20 + 48 * S:.0f}" y2="{H - 20:.0f}" stroke="#222" stroke-width="3"/>')
    out.append(f'<text x="20" y="{H - 28:.0f}" font-size="11">0</text><text x="{20 + 48 * S:.0f}" y="{H - 28:.0f}" font-size="11" text-anchor="end">48"</text>')
    out.append(f'<text x="20" y="24" font-size="15" font-weight="bold">{esc(title)} - plan check</text>')
    out.append('<text x="20" y="42" font-size="11" fill="#555">Grid 12". Brown = floor cabinets (thick line = door faces), blue dashed = wall cabinets, tan dashed = counters, red = cameras.</text>')
    out.append("</svg>")
    return "\n".join(out)


def cmd_plan(a):
    d = require_job(a.job)
    reg = load_registry()
    job = load_json(d / "job.json")
    errors, _, report = validate_job(job, reg)
    if errors:
        raise CprError("Fix validation errors first:\n  " + "\n  ".join(errors))
    svg = plan_svg(job, report, (job.get("info") or {}).get("title") or a.job)
    out = d / "output" / f"{a.job}-plan.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(f"Wrote {rel(out)}")
    if a.no_png:
        return 0
    png_rel = rel(d / "output" / f"{a.job}-plan.png")
    port = free_port()
    httpd, events = start_server(port)
    try:
        q = urllib.parse.urlencode({"src": rel(out), "save": png_rel})
        run_headless(f"http://127.0.0.1:{port}/engine/svg2png.html?{q}", (1280, 960), 1, a.timeout, events, a.browser)
    except CprError as e:
        print(f"PNG not made ({e}). The SVG is still there.")
        return 0
    finally:
        httpd.shutdown()
    print(f"Wrote {png_rel}")
    return 0


def cmd_capture(a):
    d = require_job(a.job)
    reg = load_registry()
    job = load_json(d / "job.json")
    errors, warnings, _ = validate_job(job, reg)
    if errors:
        raise CprError("Fix validation errors first:\n  " + "\n  ".join(errors))
    views = view_ids(job)
    want = views if a.views == "all" else [v.strip() for v in a.views.split(",") if v.strip()]
    missing = [v for v in want if v not in views]
    if missing:
        raise CprError(f"Unknown view(s): {', '.join(missing)}. Views in this job: {', '.join(views)}")
    w, h = parse_size(a.size)
    port = free_port()
    httpd, events = start_server(port)
    try:
        url = (f"http://127.0.0.1:{port}/engine/viewer.html?job={urllib.parse.quote(job_ref(d))}&capture=1"
               f"&save={urllib.parse.quote(','.join(want))}&w={w}&h={h}")
        print(f"Rendering {len(want)} view(s) at {w}x{h} with a headless browser...")
        sys.stdout.flush()
        result, saved = run_headless(url, (1280, 960), len(want), a.timeout, events, a.browser)
    finally:
        httpd.shutdown()
    for wmsg in result.get("warnings") or []:
        print("  warning " + wmsg)
    final = []
    if a.out:
        dest = Path(a.out).expanduser()
        dest.mkdir(parents=True, exist_ok=True)
        for p in saved:
            tgt = dest / Path(p).name
            shutil.copy2(ROOT / p, tgt)
            final.append(str(tgt))
    else:
        final = saved
    for f in final:
        print(f"Saved {f}")
    return 0


def cmd_pdf_snap(a):
    src = Path(a.file).expanduser().resolve()
    if not src.is_file() or src.suffix.lower() != ".pdf":
        raise CprError(f"Not a PDF file: {a.file}")
    if inside_root(src):
        pdf_rel = rel(src)
    else:
        WORK.mkdir(exist_ok=True)
        tmp = WORK / ("_snap-" + re.sub(r"[^A-Za-z0-9._-]+", "-", src.name))
        shutil.copy2(src, tmp)
        pdf_rel = rel(tmp)
    try:
        crop = [float(v) for v in a.crop.split(",")]
        assert len(crop) == 4 and all(0 <= v <= 1 for v in crop) and crop[2] > 0 and crop[3] > 0
        assert crop[0] + crop[2] <= 1.0001 and crop[1] + crop[3] <= 1.0001
    except Exception:
        raise CprError("--crop must be fx,fy,fw,fh as fractions of the page between 0 and 1 (e.g. 0.05,0.03,0.3,0.3)")
    w, h = parse_size(a.size)
    out = Path(a.out).expanduser().resolve() if a.out else (WORK / f"{src.stem}-p{a.page}-{'-'.join(f'{v:g}' for v in crop)}.png")
    save_rel = rel(out) if inside_root(out) else rel(WORK / ("_out-" + out.name))
    port = free_port()
    httpd, events = start_server(port)
    try:
        q = urllib.parse.urlencode({"file": pdf_rel, "page": a.page, "crop": a.crop, "capture": 1, "save": save_rel,
                                    "w": w, "h": h, "grid": 1 if a.grid else 0})
        result, saved = run_headless(f"http://127.0.0.1:{port}/engine/pdf.html?{q}", (1280, 960), 1, a.timeout, events, a.browser)
    finally:
        httpd.shutdown()
    if not inside_root(out):
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(ROOT / save_rel), str(out))
    info = result.get("pdf") or {}
    print(f"Saved {rel(out)}")
    if info:
        print(f"Sheet: {info['pageWidthPt'] / 72:.2f} x {info['pageHeightPt'] / 72:.2f} in ({info['pageWidthPt']:.0f} x {info['pageHeightPt']:.0f} pt), "
              f"page {info['page']} of {info['pages']}")
        print(f"Image scale: {info['pxPerPt']:.4f} px per pt. At 1/2\"=1'-0\" one real inch = 3 pt = {3 * info['pxPerPt']:.3f} px; "
              f"at 1/4\"=1'-0\" one real inch = 1.5 pt = {1.5 * info['pxPerPt']:.3f} px.")
    return 0


def cmd_textures_list(a):
    reg = load_registry()
    if a.json:
        print(json.dumps(reg["materials"], indent=2))
        return 0
    for mid, d in sorted(reg["materials"].items(), key=lambda kv: (kv[1].get("category", ""), kv[0])):
        extra = d.get("generator") or d.get("file") or d.get("color") or ""
        cu = " [CUSTOMISABLE: " + ", ".join(f"{k}={v}" for k, v in d["custom"].items()) + "]" if isinstance(d.get("custom"), dict) else ""
        print(f"  {mid:<34} {d.get('category', '-'):<8} {d.get('kind'):<10} {extra:<16} {d.get('label', '')}{cu}")
    print('\nCUSTOMISABLE bases can be copied into a job with their own colour/gloss: run "job-material --help".')
    probs = registry_problems(reg)
    for p in probs:
        print("  PROBLEM " + p)
    return 1 if probs else 0


def cmd_textures_add(a):
    reg = load_registry()
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", a.id):
        raise CprError("Material id must be lowercase letters, digits and hyphens.")
    if a.id in reg["materials"] and not a.replace:
        raise CprError(f'Material "{a.id}" already exists. Pass --replace to overwrite it.')
    src = Path(a.file).expanduser()
    if not src.is_file() or src.suffix.lower() not in IMAGE_EXT:
        raise CprError(f"Image must be an existing {', '.join(sorted(IMAGE_EXT))} file: {a.file}")
    cat = a.category or "misc"
    dest = TEXTURES / cat / f"{a.id}{src.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    reg["materials"][a.id] = {
        "label": a.label or a.id, "category": cat, "kind": "image", "file": dest.relative_to(TEXTURES).as_posix(),
        "repeatInches": [a.repeat[0], a.repeat[1]], "roughness": a.roughness,
    }
    save_json(REGISTRY, reg)
    print(f'Registered "{a.id}" -> textures/{dest.relative_to(TEXTURES).as_posix()} (one image tile = {a.repeat[0]}" x {a.repeat[1]}")')
    return 0


def cmd_job_material(a):
    d = require_job(a.job)
    reg = load_registry()
    path = d / "job.json"
    job = load_json(path)
    mats = job.setdefault("materials", {})
    if a.list:
        if not mats:
            print(f"Job {a.job} has no custom materials.")
        for mid, inst in mats.items():
            print(f"  {mid:<24} " + ", ".join(f"{k}={v}" for k, v in inst.items()))
        return 0
    if not a.id:
        raise CprError("Give a material id, or --list.")
    if a.remove:
        if a.id not in mats:
            raise CprError(f'Job {a.job} has no custom material "{a.id}".')
        del mats[a.id]
        if not mats:
            job.pop("materials")
        save_json(path, job)
        print(f'Removed "{a.id}". Anything still using it will fail validation.')
        return 0
    inst = dict(mats.get(a.id, {}))
    if a.base:
        inst["base"] = a.base
    for k in ("color", "gloss", "seed", "label"):
        v = getattr(a, k)
        if v is not None:
            inst[k] = v
    if a.grain_contrast is not None:
        inst["grainContrast"] = a.grain_contrast
    if "base" not in inst:
        raise CprError("New custom materials need --base (for example custom-rift, custom-plain, custom-metal).")
    probs = custom_problems(a.id, inst, reg)
    if probs:
        raise CprError("\n  ".join(probs))
    mats[a.id] = inst
    save_json(path, job)
    print(f'Set job material "{a.id}": ' + ", ".join(f"{k}={v}" for k, v in inst.items()))
    print('Use it by id, e.g. "finishes": {"cabinet": "' + a.id + '"} or a run\'s "finishes".')
    return 0


def cmd_package(a):
    out = Path(a.out).expanduser() if a.out else ROOT.parent / f"{ROOT.name}.zip"
    if inside_root(out):
        raise CprError("Write the zip outside the project folder (it would include itself).")
    skip_dirs = {".git", "__pycache__", "work", ".cpr-tmp"}
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob("*")):
            r = p.relative_to(ROOT)
            if any(part in skip_dirs for part in r.parts):
                continue
            if not a.include_outputs and len(r.parts) >= 3 and r.parts[0] == "jobs" and r.parts[2] == "output":
                continue
            if not a.include_sources and len(r.parts) >= 3 and r.parts[0] == "jobs" and r.parts[2] == "source":
                continue
            if a.no_runtime and r.parts[0] == "runtime":
                continue
            if p.is_file():
                z.write(p, Path(ROOT.name) / r)
                n += 1
    print(f"Wrote {out} ({n} files, {out.stat().st_size // 1024} KB)")
    return 0


def cmd_help(a, parser):
    parser.print_help()
    return 0


# ----------------------------------------------------------------------------- main
def main(argv=None):
    p = argparse.ArgumentParser(prog="cpr", description="Cabinet Preview Renderer tools. See AI_README.md.")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    s = sub.add_parser("help", help="show this help")
    s.set_defaults(fn=lambda a: cmd_help(a, p))

    s = sub.add_parser("doctor", help="check python, browser, texture registry and jobs")
    s.add_argument("--browser", help="path to Chrome/Edge/Chromium")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("new-job", help="create jobs/<name>/ from the template (jobs are looked up in jobs/ and jobs/examples/)")
    s.add_argument("name", help="lowercase-hyphen name, e.g. moore-bar")
    s.add_argument("--title", help="display title")
    s.add_argument("--source", action="append", help="drawing file (PDF/image) to copy into the job's source/ folder; repeatable")
    s.set_defaults(fn=cmd_new_job)

    s = sub.add_parser("add-source", help="copy drawing files into jobs/<job>/source/")
    s.add_argument("job")
    s.add_argument("files", nargs="+")
    s.set_defaults(fn=cmd_add_source)

    s = sub.add_parser("validate", help="check a job file and print computed run geometry")
    s.add_argument("job")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("serve", help="serve the project on localhost for viewing in a browser")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--host", default="127.0.0.1")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("build", help="write a single self-contained HTML viewer for a job")
    s.add_argument("job")
    s.add_argument("--out", help="output .html path (default jobs/<job>/output/<job>.html)")
    s.add_argument("--inline-libs", action="store_true", help="put three.js inside the file (works offline / in sandboxed previews); default when vendor/ has the files")
    s.add_argument("--cdn", action="store_true", help="load three.js from the internet instead (smaller file)")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("open", help="build the HTML viewer and open it in the default web browser")
    s.add_argument("job")
    s.add_argument("--no-launch", action="store_true", help="only build and print the file path")
    s.set_defaults(fn=cmd_open)

    s = sub.add_parser("plan", help="draw a top-down plan check (SVG + PNG) of runs, counters, walls and cameras")
    s.add_argument("job")
    s.add_argument("--no-png", action="store_true", help="SVG only (no browser needed)")
    s.add_argument("--browser", help="path to Chrome/Edge/Chromium")
    s.add_argument("--timeout", type=int, default=120)
    s.set_defaults(fn=cmd_plan)

    s = sub.add_parser("vendor", help="download the pinned three.js / pdf.js files into vendor/ for offline use")
    s.add_argument("--force", action="store_true", help="download again even if present")
    s.set_defaults(fn=cmd_vendor)

    s = sub.add_parser("capture", help="render job views to PNG with a headless browser")
    s.add_argument("job")
    s.add_argument("--views", default="all", help='"all" or comma-separated view ids')
    s.add_argument("--size", default="2400x1800", help="WIDTHxHEIGHT in pixels")
    s.add_argument("--out", help="folder to copy the PNGs into (they are always written to jobs/<job>/output/ first)")
    s.add_argument("--browser", help="path to Chrome/Edge/Chromium")
    s.add_argument("--timeout", type=int, default=180)
    s.set_defaults(fn=cmd_capture)

    s = sub.add_parser("pdf-snap", help="render a region of a PDF page to PNG for reading drawings")
    s.add_argument("file", help="PDF path (inside or outside the project)")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--crop", default="0,0,1,1", help="fx,fy,fw,fh fractions of the page")
    s.add_argument("--size", default="2000x1500", help="max output WIDTHxHEIGHT; aspect follows the crop")
    s.add_argument("--grid", action="store_true", help="overlay a labelled 10%% grid (page fractions)")
    s.add_argument("--out", help="output .png path (default work/...)")
    s.add_argument("--browser", help="path to Chrome/Edge/Chromium")
    s.add_argument("--timeout", type=int, default=120)
    s.set_defaults(fn=cmd_pdf_snap)

    s = sub.add_parser("textures", help="list or add materials in textures/registry.json")
    tsub = s.add_subparsers(dest="tcmd", metavar="<list|add>")
    t = tsub.add_parser("list", help="list registered materials")
    t.add_argument("--json", action="store_true")
    t.set_defaults(fn=cmd_textures_list)
    t = tsub.add_parser("add", help="copy an image into textures/ and register it as a material")
    t.add_argument("id", help="material id, e.g. walnut-natural")
    t.add_argument("--file", required=True, help="image file (.png .jpg .jpeg .webp), ideally seamless/tileable")
    t.add_argument("--repeat", type=float, nargs=2, required=True, metavar=("W_IN", "H_IN"), help="real size of one image tile in inches")
    t.add_argument("--label")
    t.add_argument("--category", help="wood, stone, tile, metal, wall, floor, ... (also the textures/ subfolder)")
    t.add_argument("--roughness", type=float, default=0.6)
    t.add_argument("--replace", action="store_true")
    t.set_defaults(fn=cmd_textures_add)
    textures_parser = s

    s = sub.add_parser("job-material", help="add/change/remove a custom-coloured material inside a job",
                       description="Creates or updates job.materials[ID], a copy of a CUSTOMISABLE registry material "
                                   "(see 'textures list') with its own colour/gloss. Example: "
                                   "job-material smith-kitchen sage-rift --base custom-rift --color \"#7d8b6a\" --gloss 0.3")
    s.add_argument("job")
    s.add_argument("id", nargs="?", help="material id to create or change, e.g. sage-rift")
    s.add_argument("--base", help="customisable registry material: custom-rift, custom-plain, custom-metal, ...")
    s.add_argument("--color", help='sRGB hex, e.g. "#8a5a3b" (quote it in shells)')
    s.add_argument("--gloss", type=float, help="0 = matte ... 1 = high gloss")
    s.add_argument("--seed", type=int, help="woods: different grain pattern")
    s.add_argument("--grain-contrast", type=float, help="woods: 0..1 darkness of grain lines (default 0.42)")
    s.add_argument("--label", help="description")
    s.add_argument("--remove", action="store_true", help="delete this custom material from the job")
    s.add_argument("--list", action="store_true", help="list the job's custom materials")
    s.set_defaults(fn=cmd_job_material)

    s = sub.add_parser("package", help="zip the project for handing to someone else")
    s.add_argument("--out", help="zip path (default: next to the project folder)")
    s.add_argument("--include-outputs", action="store_true", help="include jobs/*/output (renders)")
    s.add_argument("--include-sources", action="store_true", help="include jobs/*/source (client drawings)")
    s.add_argument("--no-runtime", action="store_true", help="leave out the bundled Windows Python")
    s.set_defaults(fn=cmd_package)

    a = p.parse_args(argv)
    if a.cmd == "textures" and not getattr(a, "tcmd", None):
        textures_parser.print_help()
        return 0
    if not getattr(a, "fn", None):
        p.print_help()
        return 0
    try:
        return a.fn(a) or 0
    except CprError as e:
        print("ERROR: " + str(e), file=sys.stderr)
        return 2
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
