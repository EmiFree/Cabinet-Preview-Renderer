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
TEXTURES = ROOT / "textures"
REGISTRY = TEXTURES / "registry.json"
ENGINE = ROOT / "engine"
WORK = ROOT / "work"
SCHEMA = "cpr-job/1"
FACINGS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
ITEM_TYPES = {"cabinet", "blank", "end-panel"}
OBJECT_TYPES = {"box", "wall", "sink", "faucet", "outlet", "tube-shelving"}
MATERIAL_KINDS = {"procedural", "image", "color", "metal", "glass", "sky"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
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
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def rel(p):
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def job_dir(name):
    if not JOB_NAME_RE.match(name or ""):
        raise CprError(f'Bad job name "{name}". Use lowercase letters, digits and hyphens, e.g. "smith-kitchen".')
    return JOBS / name


def require_job(name):
    d = job_dir(name)
    if not (d / "job.json").exists():
        have = ", ".join(sorted(p.name for p in JOBS.iterdir() if (p / "job.json").exists())) if JOBS.exists() else ""
        raise CprError(f'No job "{name}" (expected {rel(d / "job.json")}). Existing jobs: {have or "none"}.')
    return d


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
        if k == "procedural" and not d.get("generator"):
            out.append(f'material "{mid}": procedural materials need a "generator"')
        rep = d.get("repeatInches")
        if rep is not None and not (isinstance(rep, list) and len(rep) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in rep)):
            out.append(f'material "{mid}": repeatInches must be [width, height] in inches')
    return out


# ----------------------------------------------------------------------------- validation
def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_job(job, reg):
    """Return (errors, warnings, report). report holds computed world geometry for checking against drawings."""
    errors, warnings = [], []
    mats = reg["materials"]

    def need_mat(mid, where):
        if mid is None:
            return
        if mid not in mats:
            errors.append(f'{where}: unknown material "{mid}" (see "textures list")')

    if job.get("schema") != SCHEMA:
        warnings.append(f'"schema" should be "{SCHEMA}"')
    defaults = job.get("defaults", {})
    box_top = defaults.get("boxTop", 34.5)
    base = {"toeHeight": 2.5, "bandHeight": 2, **defaults.get("base", {})}
    base_h = base["toeHeight"] + base["bandHeight"]
    reveal = defaults.get("reveal", 0.125)
    margin = defaults.get("frontMargin", 0.1)
    T = defaults.get("frontThickness", 0.75)

    for role, mid in (job.get("finishes") or {}).items():
        need_mat(mid, f"finishes.{role}")

    report = {"runs": []}
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
        if not (isinstance(o, list) and len(o) == 2 and all(num(v) for v in o)):
            errors.append(f"{where}: origin must be [x, z] (back-left corner, inches)")
            continue
        depth = run.get("depth", 24)
        rtop = run.get("boxTop", box_top)
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
            if t == "cabinet":
                rows = it.get("rows") or [{"height": "fill"}]
                fixed = sum(r.get("height") for r in rows if num(r.get("height")))
                fills = sum(1 for r in rows if not num(r.get("height")))
                avail = rtop - base_h - 2 * margin
                used = fixed + reveal * (len(rows) - 1)
                if fills == 0 and abs(used - avail) > 0.25:
                    warnings.append(f"{iw}: rows + reveals = {used:.2f} but front height is {avail:.2f}; use \"fill\" on one row")
                if fills and used >= avail:
                    errors.append(f"{iw}: fixed row heights ({used:.2f}) leave no room for the fill row (front height {avail:.2f})")
                for r in rows:
                    for f in r.get("fronts") or []:
                        if f.get("style", "shaker") not in ("shaker", "slab", "none"):
                            errors.append(f"{iw}: front style must be shaker, slab or none")
                        for hw in ([f["hardware"]] if isinstance(f.get("hardware"), dict) else f.get("hardware") or []):
                            if hw.get("type") not in ("knob", "bar"):
                                errors.append(f"{iw}: hardware type must be knob or bar")
            items_out.append({"index": ii, "type": t, "id": it.get("id"), "label": it.get("label"), "width": w,
                              "from": P(s, 0), "to": P(s + w, 0)})
            s += w
        report["runs"].append({
            "id": run.get("id"), "facing": run.get("facing"), "length": round(s, 3), "depth": depth,
            "backLeft": P(0, 0), "backRight": P(s, 0), "frontLeft": P(0, depth + T), "frontRight": P(s, depth + T),
            "items": items_out,
        })

    for ci, c in enumerate(job.get("counters") or []):
        where = f'counters[{ci}] ("{c.get("id", "?")}")'
        need_mat(c.get("material"), where)
        if not all(num(c.get(k)) for k in ("x0", "x1", "z0", "z1")):
            errors.append(f"{where}: x0, x1, z0, z1 are required numbers")
        elif c["x1"] <= c["x0"] or c["z1"] <= c["z0"]:
            errors.append(f"{where}: needs x0 < x1 and z0 < z1")
        for k in c.get("cutouts") or []:
            if not all(num(k.get(q)) for q in ("x0", "x1", "z0", "z1")):
                errors.append(f"{where}: cutouts need x0, x1, z0, z1")
            elif all(num(c.get(q)) for q in ("x0", "x1", "z0", "z1")) and not (c["x0"] < k["x0"] < k["x1"] < c["x1"] and c["z0"] < k["z0"] < k["z1"] < c["z1"]):
                errors.append(f"{where}: cutout must sit fully inside the counter")
        if len(c.get("cutouts") or []) > 1:
            warnings.append(f"{where}: only one cutout per counter is supported; split the counter into pieces")

    for oi, ob in enumerate(job.get("objects") or []):
        where = f'objects[{oi}] ("{ob.get("id") or ob.get("type")}")'
        t = ob.get("type")
        if t not in OBJECT_TYPES:
            errors.append(f"{where}: type must be one of {sorted(OBJECT_TYPES)}")
            continue
        need_mat(ob.get("material"), where)
        need_mat(ob.get("glass"), where)
        if t in ("box", "wall"):
            mn, mx = ob.get("min"), ob.get("max")
            if not (isinstance(mn, list) and isinstance(mx, list) and len(mn) == 3 and len(mx) == 3 and all(num(v) for v in mn + mx)):
                errors.append(f"{where}: min and max must be [x, y, z]")
            elif any(mx[i] <= mn[i] for i in range(3)):
                errors.append(f"{where}: every max value must be larger than the matching min value")
            if t == "box" and not ob.get("material"):
                errors.append(f"{where}: material is required")
            for op in ob.get("openings") or []:
                need_mat(op.get("jamb"), where + " opening jamb")
                need_mat(op.get("glassMaterial"), where + " opening glass")
                need_mat((op.get("trim") or {}).get("material"), where + " opening trim")
                if not all(num(op.get(q)) for q in ("a0", "a1", "y0", "y1")):
                    errors.append(f"{where}: openings need a0, a1 (along the wall) and y0, y1")
        if t in ("faucet", "outlet"):
            p = ob.get("position")
            if not (isinstance(p, list) and len(p) == 3 and all(num(v) for v in p)):
                errors.append(f"{where}: position must be [x, y, z]")
            if ob.get("facing", "S") not in FACINGS:
                errors.append(f"{where}: facing must be N, S, E or W")
        if t == "sink" and not all(num(ob.get(q)) for q in ("x0", "x1", "z0", "z1")):
            errors.append(f"{where}: x0, x1, z0, z1 are required")
        if t == "tube-shelving":
            posts = ob.get("posts") or []
            for lv in ob.get("levels") or []:
                b = lv.get("between") or []
                if len(b) != 2 or not all(isinstance(i, int) and 0 <= i < len(posts) for i in b):
                    errors.append(f"{where}: level between must be two indexes into posts")

    views = job.get("views") or []
    if not views:
        warnings.append("no views defined; a default camera will be used")
    vids = set()
    for vi, v in enumerate(views):
        if v.get("id") in vids:
            errors.append(f"views[{vi}]: duplicate id {v.get('id')}")
        vids.add(v.get("id"))
        if not re.match(r"^[a-z0-9][a-z0-9-]*$", str(v.get("id", ""))):
            errors.append(f"views[{vi}]: id must be lowercase letters, digits, hyphens")
        for k in ("position", "target"):
            p = v.get(k)
            if not (isinstance(p, list) and len(p) == 3 and all(num(q) for q in p)):
                errors.append(f"views[{vi}] ({v.get('id')}): {k} must be [x, y, z]")
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
                name = urllib.parse.quote(j["name"])
                srcs = "".join(f'<li><a href="/engine/pdf.html?file={urllib.parse.quote(s)}&grid=1">{s}</a></li>' for s in j["sources"])
                rows.append(f'<h2>{j["title"]}</h2><p><a href="/engine/viewer.html?job={name}">Open 3D viewer</a> &middot; job folder jobs/{j["name"]}</p><ul>{srcs}</ul>')
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
    if not JOBS.exists():
        return out
    for d in sorted(JOBS.iterdir()):
        jf = d / "job.json"
        if not jf.is_file():
            continue
        try:
            title = load_json(jf).get("info", {}).get("title") or d.name
        except CprError:
            title = d.name + " (invalid JSON)"
        srcs = sorted(rel(p) for p in (d / "source").glob("*") if p.suffix.lower() == ".pdf") if (d / "source").exists() else []
        out.append({"name": d.name, "title": title, "sources": srcs})
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
    print(f"jobs         : {', '.join(j['name'] for j in jobs) or 'none'}")
    print("network      : the viewer loads three.js and pdf.js from cdn.jsdelivr.net / cdnjs.cloudflare.com (internet needed)")
    return 0 if ok and not probs else 1


def cmd_new_job(a):
    d = job_dir(a.name)
    if (d / "job.json").exists():
        raise CprError(f"Job {a.name} already exists at {rel(d)}.")
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
        print(f"  run {r['id']} facing {r['facing']}: length {r['length']}, depth {r['depth']}")
        print(f"    back  {r['backLeft']} -> {r['backRight']}")
        print(f"    front {r['frontLeft']} -> {r['frontRight']}  (front face of doors)")
        for it in r["items"]:
            print(f"      [{it['index']}] {it['type']:<9} w={it['width']:<7} {it['from']} -> {it['to']}  {it['label'] or it['id'] or ''}")
    return 1 if errors else 0


def cmd_serve(a):
    httpd, _ = start_server(a.port, a.host)
    base = f"http://{a.host}:{a.port}"
    print(f"Serving {ROOT} at {base}/  (Ctrl+C to stop)")
    for j in list_jobs():
        print(f"  viewer : {base}/engine/viewer.html?job={j['name']}")
        print(f"  capture: {base}/engine/viewer.html?job={j['name']}&capture=1&save=all   (saves PNGs to jobs/{j['name']}/output/)")
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


def build_standalone(name, out=None):
    d = require_job(name)
    reg = load_registry()
    job = load_json(d / "job.json")
    errors, _, _ = validate_job(job, reg)
    if errors:
        raise CprError("Fix validation errors first:\n  " + "\n  ".join(errors))
    html = (ENGINE / "viewer.html").read_text(encoding="utf-8")
    used = used_materials(job)
    images = {}
    for mid in used:
        m = reg["materials"].get(mid, {})
        if m.get("kind") == "image":
            p = TEXTURES / m["file"]
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}[p.suffix.lower().lstrip(".")]
            images[mid] = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    boot = {"job": job, "registry": {"materials": {k: v for k, v in reg["materials"].items()}}, "images": images}

    def script(js):
        return "<script>\n" + js.replace("</script", "<\\/script") + "\n</script>"
    engine_js = script((ENGINE / "textures.js").read_text(encoding="utf-8")) + "\n" + script((ENGINE / "engine.js").read_text(encoding="utf-8"))
    boot_js = script("window.CPR_BOOT = " + json.dumps(boot).replace("</", "<\\/") + ";")
    html = re.sub(r"<!--CPR:ENGINE-->.*?<!--/CPR:ENGINE-->", lambda m: engine_js, html, flags=re.S)
    html = html.replace("<!--CPR:BOOT-->", boot_js + "\n<!--CPR:BOOT-->")
    title = (job.get("info") or {}).get("title") or name
    html = re.sub(r"<title>.*?</title>", lambda m: "<title>" + title.replace("<", "") + "</title>", html, count=1)
    out = Path(out) if out else d / "output" / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return out


def used_materials(job):
    used = set((job.get("finishes") or {}).values())
    used |= {"rift-white-oak-light-bleached", "bead-groove", "toe-kick-shadow", "satin-nickel", "floor-neutral",
             "stainless", "clear-glass", "window-sky", "outlet-plate"}
    for c in job.get("counters") or []:
        used.add(c.get("material"))
    for o in job.get("objects") or []:
        for k in ("material", "glass"):
            if o.get(k):
                used.add(o[k])
        for op in o.get("openings") or []:
            used |= {op.get("jamb"), op.get("glassMaterial"), (op.get("trim") or {}).get("material")}
    if (job.get("floor") or {}).get("material"):
        used.add(job["floor"]["material"])
    used.discard(None)
    return used


def cmd_build(a):
    out = build_standalone(a.job, a.out)
    print(f"Built {rel(out)} ({out.stat().st_size // 1024} KB). It opens by double-click in any browser (internet needed for three.js).")
    return 0


def cmd_capture(a):
    d = require_job(a.job)
    reg = load_registry()
    job = load_json(d / "job.json")
    errors, warnings, _ = validate_job(job, reg)
    if errors:
        raise CprError("Fix validation errors first:\n  " + "\n  ".join(errors))
    views = [v["id"] for v in job.get("views") or []]
    want = views if a.views == "all" else [v.strip() for v in a.views.split(",") if v.strip()]
    missing = [v for v in want if v not in views]
    if missing:
        raise CprError(f"Unknown view(s): {', '.join(missing)}. Views in this job: {', '.join(views)}")
    w, h = parse_size(a.size)
    port = free_port()
    httpd, events = start_server(port)
    try:
        url = (f"http://127.0.0.1:{port}/engine/viewer.html?job={urllib.parse.quote(a.job)}&capture=1"
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
        print(f"  {mid:<34} {d.get('category', '-'):<8} {d.get('kind'):<10} {extra:<16} {d.get('label', '')}")
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

    s = sub.add_parser("new-job", help="create jobs/<name>/ from the template")
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
    s.set_defaults(fn=cmd_build)

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

    s = sub.add_parser("package", help="zip the project for handing to someone else")
    s.add_argument("--out", help="zip path (default: next to the project folder)")
    s.add_argument("--include-outputs", action="store_true", help="include jobs/*/output")
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
