// Cabinet Preview Renderer - scene builder.
// CPR.buildScene(job, materials) turns a job.json object into a THREE.Scene.
// Units are inches. World axes (plan view, north up): +x = east (right on the plan), +z = south (down on the plan), +y = up.
// The job format is documented in AI_README.md (section 5). Keep that file in sync when adding fields here.
(function () {
  'use strict';
  const CPR = (window.CPR = window.CPR || {});

  const FACING = { N: [0, -1], S: [0, 1], E: [1, 0], W: [-1, 0] };
  CPR.FACING = FACING;

  const DEFAULTS = {
    boxTop: 34.5,           // top of base cabinet boxes (countertop sits on this)
    frontThickness: 0.75,
    reveal: 0.125,          // gap between adjacent fronts
    frontMargin: 0.1,       // gap above/below the front stack
    stile: 2.25,            // shaker frame width
    wallBottom: 54,         // default underside of wall (upper) cabinets
    base: { toeHeight: 2.5, toeRecess: 3, bandHeight: 2, bandProjection: 0.25 },
  };

  function merge(a, b) {
    const out = Array.isArray(a) ? a.slice() : { ...a };
    for (const k in b || {}) {
      out[k] = b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) && a && typeof a[k] === 'object' ? merge(a[k], b[k]) : b[k];
    }
    return out;
  }
  const num = (v) => typeof v === 'number' && isFinite(v);

  // Resolve a run's base option into a concrete base description. Returns {type, height, ...}; height = where fronts start.
  CPR.resolveBase = function (runBase, D, mount) {
    if (mount === 'wall' || runBase === false) return { type: 'none', height: 0 };
    const b = runBase && typeof runBase === 'object' ? runBase : {};
    const type = b.type || 'recessed';
    if (type === 'flush') { const h = b.height ?? 4, rv = b.reveal ?? 0.25; return { type, h, reveal: rv, recess: b.recess ?? 0.25, height: h + rv }; }
    if (type === 'applied') { const h = b.height ?? 4, rv = b.reveal ?? 0.125; return { type, h, reveal: rv, projection: b.projection ?? 0.5, height: h + rv }; }
    if (type === 'none') return { type, height: b.height ?? 0 };
    const th = b.toeHeight ?? D.base.toeHeight, bh = b.bandHeight ?? D.base.bandHeight;
    return { type: 'recessed', toeHeight: th, bandHeight: bh, toeRecess: b.toeRecess ?? D.base.toeRecess, bandProjection: b.bandProjection ?? D.base.bandProjection, height: th + bh };
  };

  CPR.buildScene = function (job, lib) {
    const scene = new THREE.Scene();
    const D = merge(DEFAULTS, job.defaults || {});
    const F = merge({ cabinet: 'rift-white-oak-light-bleached', groove: 'auto', toeKick: 'toe-kick-shadow', hardware: 'satin-nickel' }, job.finishes || {});
    let CF = F; // finishes in effect for the run being built (job finishes + run.finishes)
    const grooveMat = () => (CF.groove === 'auto' ? lib.autoGroove(CF.cabinet) : lib.get(CF.groove));
    const T = D.frontThickness;
    const warnings = [];
    const pointLights = [];
    const MAX_POINT_LIGHTS = 12;

    // ---------- primitives ----------
    function boxGeo(w, h, d, rep) {
      const g = new THREE.BoxGeometry(w, h, d);
      const uv = g.attributes.uv;
      const dims = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
      const ou = Math.random(), ov = Math.random();
      for (let f = 0; f < 6; f++) for (let i = 0; i < 4; i++) {
        const k = f * 4 + i;
        uv.setXY(k, (uv.getX(k) * dims[f][0]) / rep[0] + ou, (uv.getY(k) * dims[f][1]) / rep[1] + ov);
      }
      return g;
    }
    // Axis-aligned box from min/max corners in the parent's coordinates.
    function B(parent, x0, x1, y0, y1, z0, z1, m) {
      if (x1 < x0) [x0, x1] = [x1, x0];
      if (y1 < y0) [y0, y1] = [y1, y0];
      if (z1 < z0) [z0, z1] = [z1, z0];
      const w = x1 - x0, h = y1 - y0, d = z1 - z0;
      if (w <= 1e-4 || h <= 1e-4 || d <= 1e-4) return null;
      const mesh = new THREE.Mesh(boxGeo(w, h, d, m.userData.repeat || [24, 24]), m);
      mesh.position.set(x0 + w / 2, y0 + h / 2, z0 + d / 2);
      mesh.castShadow = mesh.receiveShadow = !m.transparent && !m.userData.noShadow;
      parent.add(mesh);
      return mesh;
    }
    const cyl = (r, len, m, seg) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg || 16), m); c.castShadow = true; return c; };
    // Scale extrude/shape UVs (which are in inches) to the material's repeat size.
    function scaleUV(geo, m) {
      const rep = m.userData.repeat || [24, 24], uv = geo.attributes.uv;
      if (!uv) return geo;
      for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) / rep[0], uv.getY(i) / rep[1]);
      return geo;
    }
    // Place a local group (x = along, y = up, z = toward the room) onto a world box face. Returns group, length, height, depth.
    function onBox(min, max, facing) {
      const n = FACING[facing || 'S'];
      if (!n) throw new Error(`facing must be N, S, E or W`);
      const g = new THREE.Group();
      g.rotation.y = Math.atan2(n[0], n[1]);
      const dx = max[0] - min[0], dz = max[2] - min[2];
      const pos = { N: [max[0], min[1], max[2]], S: [min[0], min[1], min[2]], E: [min[0], min[1], max[2]], W: [max[0], min[1], min[2]] }[facing || 'S'];
      g.position.set(...pos);
      const along = facing === 'N' || facing === 'S' ? dx : dz, depth = facing === 'N' || facing === 'S' ? dz : dx;
      scene.add(g);
      return { g, w: along, h: max[1] - min[1], d: depth };
    }

    // ---------- fronts: local x 0..w left->right as seen from the front, y up, z 0..T toward the viewer ----------
    function grooveRect(g, x0, y0, x1, y1, z) {
      const gm = grooveMat(), gw = 0.14;
      B(g, x0, x1, y0, y0 + gw, z, z + 0.02, gm); B(g, x0, x1, y1 - gw, y1, z, z + 0.02, gm);
      B(g, x0, x0 + gw, y0, y1, z, z + 0.02, gm); B(g, x1 - gw, x1, y0, y1, z, z + 0.02, gm);
    }
    function shaker(w, h, s, beadRoute) {
      s = Math.min(s || D.stile, w / 2 - 0.5, h / 2 - 0.5);
      const g = new THREE.Group(), V = lib.get(CF.cabinet), H = lib.get(CF.cabinet, 'h');
      B(g, 0, s, 0, h, 0, T, V); B(g, w - s, w, 0, h, 0, T, V);
      B(g, s, w - s, h - s, h, 0, T, H); B(g, s, w - s, 0, s, 0, T, H);
      B(g, s, w - s, s, h - s, 0, 0.4, V);
      if (beadRoute !== false) grooveRect(g, s - 0.42, s - 0.42, w - s + 0.42, h - s + 0.42, T);
      return g;
    }
    function slab(w, h, beadRoute) {
      const g = new THREE.Group();
      B(g, 0, w, 0, h, 0, T, lib.get(CF.cabinet, 'h'));
      if (beadRoute !== false) grooveRect(g, 0.55, 0.55, w - 0.55, h - 0.55, T);
      return g;
    }
    // Vertical slats over a recessed back. Also used for wall paneling.
    function slats(w, h, o, matId, thick) {
      o = o || {};
      const g = new THREE.Group(), th = thick ?? T;
      const sw = o.slatWidth ?? 1.5, gap = o.gap ?? 0.375, dp = Math.min(o.depth ?? 0.25, th - 0.1);
      const V = lib.get(matId || CF.cabinet);
      B(g, 0, w, 0, h, 0, th - dp, V);
      const n = Math.max(1, Math.round((w + gap) / (sw + gap)));
      const realW = (w - gap * (n - 1)) / n;
      const gm = matId ? lib.autoGroove(matId) : grooveMat();
      for (let i = 0; i < n; i++) {
        const x0 = i * (realW + gap);
        B(g, x0, x0 + realW, 0, h, th - dp, th, V);
        if (i < n - 1) B(g, x0 + realW, x0 + realW + gap, 0, h, th - dp, th - dp + 0.02, gm);
      }
      return g;
    }
    // Built-in appliance faces drawn inside a front opening.
    function appliance(w, h, f) {
      const g = new THREE.Group(), m = lib.get(f.material || 'stainless'), glass = lib.get(f.glass || 'appliance-glass');
      const kind = f.kind || 'panel';
      const handle = (y, len, vertical, x) => {
        const hb = cyl(0.375, len, m, 20); if (!vertical) hb.rotation.z = Math.PI / 2;
        hb.position.set(x ?? w / 2, y, T + 1.9); g.add(hb);
        for (const s of [-1, 1]) {
          const p = cyl(0.25, 1.9, m, 12); p.rotation.x = Math.PI / 2;
          p.position.set((x ?? w / 2) + (vertical ? 0 : s * (len / 2 - 0.8)), y + (vertical ? s * (len / 2 - 0.8) : 0), T + 0.95); g.add(p);
        }
      };
      if (kind === 'wine-column') {
        const fr = f.frame ?? 1.75;
        B(g, 0, fr, 0, h, 0, T, m); B(g, w - fr, w, 0, h, 0, T, m);
        B(g, fr, w - fr, 0, fr * 1.6, 0, T, m); B(g, fr, w - fr, h - fr, h, 0, T, m);
        B(g, fr, w - fr, fr * 1.6, h - fr, 0.2, 0.4, glass);
        const side = f.handleSide === 'left' ? fr / 2 + 0.2 : w - fr / 2 - 0.2;
        handle(h / 2, Math.min(h * 0.6, 40), true, side);
        return g;
      }
      B(g, 0, w, 0, h, 0, T, m);
      if (kind === 'wall-oven') {
        const strip = Math.min(4, h * 0.15);
        B(g, 0.4, w - 0.4, h - strip + 0.3, h - 0.3, T, T + 0.05, glass);                     // control strip
        B(g, w * 0.12, w * 0.88, h * 0.12, h - strip - 3.2, T, T + 0.05, glass);                 // door window
        handle(h - strip - 1.6, w * 0.8, false);
      } else if (kind === 'microwave-drawer') {
        const strip = Math.min(2.5, h * 0.18);
        B(g, w * 0.1, w * 0.9, h - strip + 0.3, h - 0.4, T, T + 0.05, glass);
        B(g, w * 0.1, w * 0.9, h * 0.15, h - strip - 0.6, T, T + 0.05, glass);
      } else if (kind === 'warming-drawer') {
        handle(h - 1.8, w * 0.7, false);
      } else if (kind === 'dishwasher') {
        B(g, 0.4, w - 0.4, h - 3, h - 0.3, T, T + 0.05, glass);
        handle(h - 4.2, w * 0.75, false);
      } else if (kind === 'refrigerator') {
        handle(h / 2, Math.min(h * 0.7, 36), true, f.handleSide === 'left' ? 2 : w - 2);
      }
      return g;
    }
    function knob(g, x, y, mid) {
      const m = lib.get(mid || CF.hardware);
      const b = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 0.9, 20), m);
      b.rotation.x = Math.PI / 2; b.position.set(x, y, T + 0.45);
      const k = new THREE.Mesh(new THREE.SphereGeometry(0.6, 24, 16), m);
      k.scale.z = 0.7; k.position.set(x, y, T + 1.05);
      b.castShadow = k.castShadow = true; g.add(b, k);
    }
    function bar(g, x, y, len, vertical, mid, r, stand) {
      const m = lib.get(mid || CF.hardware);
      r = r ?? 0.25; stand = stand ?? 1.15;
      const b = cyl(r, len, m, 20); if (!vertical) b.rotation.z = Math.PI / 2;
      b.position.set(x, y, T + stand); g.add(b);
      for (const s of [-1, 1]) {
        const p = cyl(r * 0.8, stand, m, 12); p.rotation.x = Math.PI / 2;
        p.position.set(x + (vertical ? 0 : s * (len / 2 - 0.6)), y + (vertical ? s * (len / 2 - 0.6) : 0), T + stand / 2); g.add(p);
      }
    }
    function addHardware(g, w, h, hw) {
      for (const k of [].concat(hw || [])) {
        const type = k.type || 'knob';
        if (type === 'push-latch' || type === 'none') continue;
        const mid = k.finish || k.material;
        const len = k.length || (type === 'tab' ? 2.5 : type === 'appliance-pull' ? 18 : 6);
        const inset = k.inset ?? (type === 'knob' ? 1.1 : type === 'bar' || type === 'appliance-pull' ? 1.5 : len / 2 + 0.75);
        let x = k.x ?? 'center';
        if (x === 'left') x = inset; else if (x === 'right') x = w - inset; else if (x === 'center') x = w / 2;
        const y = h - (k.fromTop ?? (type === 'knob' ? 1.1 : type === 'bar' ? 2.5 : type === 'appliance-pull' ? 4 : 0));
        if (type === 'knob') knob(g, x, y, mid);
        else if (type === 'bar') bar(g, x, y, len, !!k.vertical, mid);
        else if (type === 'appliance-pull') bar(g, x, y, len, !!k.vertical, mid, 0.375, 1.9);
        else if (type === 'edge-pull' || type === 'tab') {
          // metal lip on the top edge (or the side edge when vertical), projecting slightly
          const m = lib.get(mid || CF.hardware), proj = type === 'tab' ? 1.1 : 0.6;
          // the lip stands 0.05" proud of the door edge so its outer face never shares the door's side plane
          if (k.vertical) { const ex = x >= w / 2 ? w : 0; B(g, ex ? w - 0.12 : -0.05, ex ? w + 0.05 : 0.12, y - len / 2, y + len / 2, T - 0.4, T + proj, m); }
          else B(g, x - len / 2, x + len / 2, h - 0.12, h + 0.05, T - 0.4, T + proj, m);
        } else if (type === 'finger-groove') {
          // routed finger pull along the top edge, in the cabinet colour but shadowed
          B(g, x - len / 2, x + len / 2, h - 1, h - 0.15, T - 0.02, T + 0.005, grooveMat());
        } else warnings.push(`hardware type "${type}" is not supported`);
      }
    }
    function makeFront(f, w, h) {
      if (!f || f.style === 'none') return null;
      let g;
      if (f.style === 'slab') g = slab(w, h, f.beadRoute);
      else if (f.style === 'slat') g = slats(w, h, f);
      else if (f.style === 'appliance') g = appliance(w, h, f);
      else g = shaker(w, h, f.stile, f.beadRoute);
      addHardware(g, w, h, f.hardware);
      return g;
    }

    // Lay out rows (top to bottom) inside a rectangle. A row holds "fronts" (left to right) or "columns",
    // and each column holds its own "rows". Returns nothing; adds fronts to group g at depth z.
    function layoutRows(g, rows, x0, x1, yBottom, yTop, z, where) {
      const r = D.reveal;
      rows = rows && rows.length ? rows : [{ height: 'fill', fronts: [{ style: 'shaker' }] }];
      const span = yTop - yBottom;
      const fixed = rows.reduce((s, row) => s + (num(row.height) ? row.height : 0), 0);
      const fills = rows.filter((row) => !num(row.height)).length;
      const fillH = fills ? (span - fixed - r * (rows.length - 1)) / fills : 0;
      if (fills === 0 && Math.abs(fixed + r * (rows.length - 1) - span) > 0.25)
        warnings.push(`${where}: row heights + reveals (${(fixed + r * (rows.length - 1)).toFixed(2)}) do not equal the space ${span.toFixed(2)}`);
      if (fills && fillH <= 0) warnings.push(`${where}: fixed row heights leave no room for "fill" rows`);
      let top = yTop;
      for (const row of rows) {
        const h = num(row.height) ? row.height : fillH;
        if (row.columns) {
          const cols = row.columns, avail = x1 - x0 - r * (cols.length - 1);
          const fixedW = cols.reduce((s, c) => s + (num(c.width) ? c.width : 0), 0);
          const flex = cols.filter((c) => !num(c.width)).length;
          let cx = x0;
          cols.forEach((c, i) => {
            const cw = num(c.width) ? c.width : (avail - fixedW) / Math.max(flex, 1);
            layoutRows(g, c.rows, cx, cx + cw, top - h, top, z, `${where} column ${i}`);
            cx += cw + r;
          });
        } else {
          const fronts = row.fronts || [{ style: 'shaker' }];
          const avail = x1 - x0 - r * (fronts.length - 1);
          const fixedW = fronts.reduce((s, f) => s + (num(f.width) ? f.width : 0), 0);
          const flex = fronts.filter((f) => !num(f.width)).length;
          let fx = x0;
          for (const f of fronts) {
            const fw = num(f.width) ? f.width : (avail - fixedW) / Math.max(flex, 1);
            const front = makeFront(f, fw, h);
            if (front) { front.position.set(fx, top - h, z); g.add(front); }
            fx += fw + r;
          }
        }
        top -= h + r;
      }
    }

    // ---------- cabinet runs ----------
    const runInfo = [];
    const runBoxes = new THREE.Box3();
    // Sinks cut into whatever cabinet box sits under them (automatically, whatever the item's sinkBase/sinkDepth say),
    // so the bowl never shows the carcass top through it.
    const sinkCuts = (job.objects || []).filter((o) => o.type === 'sink' && [o.x0, o.x1, o.z0, o.z1].every(num))
      .map((o) => ({ x0: Math.min(o.x0, o.x1), x1: Math.max(o.x0, o.x1), z0: Math.min(o.z0, o.z1), z1: Math.max(o.z0, o.z1), bottom: (o.rim ?? D.boxTop) - (o.depth ?? 7) }));
    for (const run of job.runs || []) {
      const n = FACING[run.facing];
      if (!n) { warnings.push(`run ${run.id}: facing must be N, S, E or W`); continue; }
      CF = merge(F, run.finishes || {});
      const mount = run.mount || 'floor';
      const depth = run.depth ?? (mount === 'wall' ? 12 : 24);
      const baseInfo = CPR.resolveBase(run.base, D, mount);
      const bottom = mount === 'wall' ? (run.bottom ?? D.wallBottom) : 0;
      const boxTop = run.boxTop ?? (mount === 'wall' ? bottom + 30 : D.boxTop);
      const BASE = mount === 'wall' ? bottom : baseInfo.height;
      const g = new THREE.Group();
      g.position.set(run.origin[0], 0, run.origin[1]);
      g.rotation.y = Math.atan2(n[0], n[1]);   // local +z -> facing direction, local +x -> viewer's right
      scene.add(g);
      const V = lib.get(CF.cabinet), H = lib.get(CF.cabinet, 'h');
      const items = run.items || [];
      let x = 0;
      const placed = [];
      for (const it of items) {
        const w = it.width ?? (it.type === 'end-panel' ? T : 0);
        placed.push({ it, x0: x, x1: x + w });
        x += w;
      }
      const L = x;
      const leftExposed = items[0] && items[0].type === 'end-panel';
      const rightExposed = items.length && items[items.length - 1].type === 'end-panel';

      // ----- base -----
      const bi = baseInfo;
      if (bi.type === 'recessed') {
        const bp = bi.bandProjection, tr = bi.toeRecess, th = bi.toeHeight;
        const bx0 = leftExposed ? -bp : 0, bx1 = rightExposed ? L + bp : L;
        B(g, bx0, bx1, th, BASE - 0.3, 0, depth + T + bp, H);
        B(g, bx0 - (leftExposed ? 0.2 : 0), bx1 + (rightExposed ? 0.2 : 0), BASE - 0.3, BASE, 0, depth + T + bp + 0.2, H);
        B(g, leftExposed ? tr : 0, rightExposed ? L - tr : L, 0, th, 0, depth + T - tr, lib.get(CF.toeKick));
      } else if (bi.type === 'flush') {
        // base board flush with the door faces, with a recessed shadow reveal above it
        B(g, 0, L, 0, bi.h, 0, depth + T, H);
        B(g, leftExposed ? bi.recess : 0, rightExposed ? L - bi.recess : L, bi.h, BASE, 0, depth + T - bi.recess, lib.get(CF.toeKick));
      } else if (bi.type === 'applied') {
        // base moulding applied in front of the door plane, wrapping exposed ends
        const p = bi.projection;
        // board below, cap moulding on top (stacked, not overlapping, so their top faces never z-fight)
        B(g, leftExposed ? -p : 0, rightExposed ? L + p : L, 0, bi.h - 0.5, 0, depth + T + p, H);
        B(g, leftExposed ? -p - 0.15 : 0, rightExposed ? L + p + 0.15 : L, bi.h - 0.5, bi.h, 0, depth + T + p + 0.15, H);
        B(g, 0, L, bi.h, BASE, 0, depth + T - 0.25, lib.get(CF.toeKick));
      }

      // ----- items -----
      for (const p of placed) {
        const it = p.it, w = p.x1 - p.x0;
        if (it.type === 'end-panel') {
          const isLeft = p.x0 === 0;
          const ph = boxTop - BASE;
          const panel = it.style === 'slat' ? slats(depth + T, ph, it) : it.style === 'slab' ? slab(depth + T, ph, it.beadRoute) : shaker(depth + T, ph, it.stile ?? 3, it.beadRoute);
          panel.rotation.y = isLeft ? -Math.PI / 2 : Math.PI / 2;
          panel.position.set(isLeft ? p.x0 + w : p.x0, BASE, isLeft ? 0 : depth + T);
          if (w > T) B(g, isLeft ? p.x0 + T : p.x0, isLeft ? p.x1 : p.x1 - T, BASE, boxTop, 0, depth + T, V);
          g.add(panel);
          continue;
        }
        if (it.type === 'filler') { B(g, p.x0, p.x1, BASE, boxTop, 0, depth + T, V); continue; }
        if (it.carcass !== false) {
          let top = it.sinkBase ? boxTop - (it.sinkDepth ?? 7) - 0.3 : boxTop;
          // world footprint of this item's box, then lower its top below any sink bowl above it
          const an = [n[1], -n[0]];
          const wx = [run.origin[0] + an[0] * p.x0, run.origin[0] + an[0] * p.x1 + n[0] * depth];
          const wz = [run.origin[1] + an[1] * p.x0, run.origin[1] + an[1] * p.x1 + n[1] * depth];
          const ix0 = Math.min(...wx), ix1 = Math.max(...wx), iz0 = Math.min(...wz), iz1 = Math.max(...wz);
          for (const s of sinkCuts) {
            if (Math.min(ix1, s.x1) - Math.max(ix0, s.x0) > 0.01 && Math.min(iz1, s.z1) - Math.max(iz0, s.z0) > 0.01 && s.bottom < top + 0.3)
              top = Math.min(top, s.bottom - 0.3);
          }
          B(g, p.x0, p.x1, BASE, Math.max(BASE + 0.5, top), 0, depth, V);
        }
        if (it.type !== 'cabinet') continue;
        const lInset = it.inset?.[0] ?? D.reveal / 2, rInset = it.inset?.[1] ?? D.reveal / 2;
        layoutRows(g, it.rows, p.x0 + lInset, p.x1 - rInset, BASE + D.frontMargin, boxTop - D.frontMargin, depth, `run ${run.id} item ${it.id || it.label || ''}`);
      }

      // ----- light rail / under-cabinet LEDs (wall runs) -----
      if (mount === 'wall' && run.lightRail) {
        const lr = typeof run.lightRail === 'object' ? run.lightRail : {};
        B(g, 0, L, bottom - (lr.height ?? 1.5), bottom, depth + T - 0.75, depth + T, H);
      }
      if (run.underLight) {
        const ul = typeof run.underLight === 'object' ? run.underLight : {};
        const y = (mount === 'wall' ? bottom : boxTop) - 0.05;
        ledStrip(g, [1, y, depth * 0.7], [L - 1, y, depth * 0.7], ul, 'down');
      }

      // ----- soffit above the run -----
      if (run.soffit) {
        const so = run.soffit, to = so.to ?? 96;
        const front = so.flushWith === 'box' ? depth : num(so.flushWith) ? so.flushWith : depth + T;
        B(g, 0, L, boxTop, to, 0, front, lib.get(so.material || 'drywall-paint'));
      }

      // world extents for reports
      const a = [n[1], -n[0]];
      const P = (s, t) => [run.origin[0] + a[0] * s + n[0] * t, run.origin[1] + a[1] * s + n[1] * t];
      runInfo.push({ id: run.id, mount, length: L, bottom, boxTop, backLeft: P(0, 0), backRight: P(L, 0), frontRight: P(L, depth + T), frontLeft: P(0, depth + T) });
      g.updateMatrixWorld(true);
      runBoxes.union(new THREE.Box3().setFromObject(g));
    }

    // ---------- countertops ----------
    for (const c of job.counters || []) {
      try { buildCounter(c); } catch (e) { warnings.push(`counter ${c.id}: ${e.message}`); }
    }
    function rectCells(x0, x1, z0, z1, cuts) {
      // rectangle minus axis-aligned cutouts (which may reach or cross the edge) as a list of rectangles
      const xs = [...new Set([x0, x1, ...cuts.flatMap((k) => [k.x0, k.x1])].filter((v) => v >= x0 && v <= x1))].sort((a, b) => a - b);
      const zs = [...new Set([z0, z1, ...cuts.flatMap((k) => [k.z0, k.z1])].filter((v) => v >= z0 && v <= z1))].sort((a, b) => a - b);
      const out = [];
      for (let j = 0; j < zs.length - 1; j++) {
        let run = null;
        for (let i = 0; i < xs.length - 1; i++) {
          const cx = (xs[i] + xs[i + 1]) / 2, cz = (zs[j] + zs[j + 1]) / 2;
          const cut = cuts.some((k) => cx > k.x0 && cx < k.x1 && cz > k.z0 && cz < k.z1);
          if (!cut) { if (run) run.x1 = xs[i + 1]; else run = { x0: xs[i], x1: xs[i + 1], z0: zs[j], z1: zs[j + 1] }; }
          else if (run) { out.push(run); run = null; }
        }
        if (run) out.push(run);
      }
      return out;
    }
    function buildCounter(c) {
      const m = lib.get(c.material);
      const edge = typeof c.edge === 'object' ? c.edge : { profile: c.edge || 'eased' };
      let th = c.thickness ?? 1.5;
      const top = c.top ?? D.boxTop + th;
      if (edge.profile === 'mitered') th = edge.height ?? 3;       // mitered apron reads as a thicker slab
      const bevel = edge.profile === 'eased' ? (edge.radius ?? 0.125) : 0;
      const cuts = c.cutouts || [];
      if (c.outline) {
        // polygon top: extrude a Shape (x, z) downward from top; cutouts become holes and must sit inside
        const shape = new THREE.Shape(c.outline.map(([x, z]) => new THREE.Vector2(x, -z)));
        for (const k of cuts) {
          const h = new THREE.Path([[k.x0, k.z0], [k.x1, k.z0], [k.x1, k.z1], [k.x0, k.z1]].map(([x, z]) => new THREE.Vector2(x, -z)));
          shape.holes.push(h);
        }
        const geo = new THREE.ExtrudeGeometry(shape, { depth: th - 2 * bevel, bevelEnabled: bevel > 0, bevelThickness: bevel, bevelSize: bevel, bevelOffset: -bevel, bevelSegments: 2, steps: 1 });
        scaleUV(geo, m);
        const mesh = new THREE.Mesh(geo, m);
        mesh.rotation.x = -Math.PI / 2;           // shape (x, -z) in XY -> XZ plane, extrusion goes up
        mesh.position.y = top - th + bevel;
        mesh.castShadow = mesh.receiveShadow = true;
        scene.add(mesh);
        const area = c.outline.reduce((s, p, i) => { const q = c.outline[(i + 1) % c.outline.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0);
        (c.waterfall || []).forEach((wf) => {
          const i = typeof wf === 'object' ? wf.edge : wf;
          if (!num(i)) { warnings.push(`counter ${c.id}: outline waterfalls are given as edge indexes (0 = first point to second point)`); return; }
          const a = c.outline[i], b = c.outline[(i + 1) % c.outline.length];
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
          const wm = new THREE.Mesh(boxGeo(len, top - th, th, m.userData.repeat || [24, 24]), m);
          // panel just inside the outline along edge a->b, outer face flush with the counter edge
          const ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
          const s = area > 0 ? 1 : -1;
          const nx = -Math.sin(ang) * s, nz = Math.cos(ang) * s;   // inward normal in x/z
          wm.position.set((a[0] + b[0]) / 2 + nx * th / 2, (top - th) / 2, (a[1] + b[1]) / 2 + nz * th / 2);
          wm.rotation.y = -ang;
          wm.castShadow = wm.receiveShadow = true; scene.add(wm);
        });
        return;
      }
      if (!(num(c.x0) && num(c.x1) && num(c.z0) && num(c.z1))) throw new Error('needs x0, x1, z0, z1 or an outline');
      const crossing = cuts.some((k) => k.x0 <= c.x0 || k.x1 >= c.x1 || k.z0 <= c.z0 || k.z1 >= c.z1);
      if (!crossing && bevel > 0) {
        return buildCounter({ ...c, outline: [[c.x0, c.z0], [c.x1, c.z0], [c.x1, c.z1], [c.x0, c.z1]], x0: undefined, waterfall: rectWaterfallEdges(c) });
      }
      for (const cell of rectCells(c.x0, c.x1, c.z0, c.z1, cuts)) B(scene, cell.x0, cell.x1, top - th, top, cell.z0, cell.z1, m);
      for (const side of normSides(c)) {
        const s = { west: [c.x0, c.x0 + th, c.z0, c.z1], east: [c.x1 - th, c.x1, c.z0, c.z1], north: [c.x0, c.x1, c.z0, c.z0 + th], south: [c.x0, c.x1, c.z1 - th, c.z1] }[side];
        B(scene, s[0], s[1], 0, top - th, s[2], s[3], m);
      }
    }
    function normSides(c) {
      const alongX = (c.x1 - c.x0) >= (c.z1 - c.z0);
      return (c.waterfall || []).map((w) => (w === 'start' ? (alongX ? 'west' : 'north') : w === 'end' ? (alongX ? 'east' : 'south') : w));
    }
    // rectangle outline order: NW, NE, SE, SW -> edges 0 = north, 1 = east, 2 = south, 3 = west
    function rectWaterfallEdges(c) {
      const idx = { north: 0, east: 1, south: 2, west: 3 };
      return normSides(c).map((s) => ({ edge: idx[s] }));
    }

    // ---------- free objects ----------
    const faceRot = { N: Math.PI, S: 0, E: Math.PI / 2, W: -Math.PI / 2 };
    for (const o of job.objects || []) {
      try {
        switch (o.type) {
          case 'box':
            B(scene, o.min[0], o.max[0], o.min[1], o.max[1], o.min[2], o.max[2], lib.get(o.material, o.grain));
            break;
          case 'wall': buildWall(o); break;
          case 'sink': {
            const m = lib.get(o.material || 'stainless'), rim = o.rim ?? D.boxTop, dp = o.depth ?? 7, t = 0.1;
            B(scene, o.x0, o.x1, rim - dp, rim - dp + 0.2, o.z0, o.z1, m);
            B(scene, o.x0, o.x0 + t, rim - dp, rim, o.z0, o.z1, m); B(scene, o.x1 - t, o.x1, rim - dp, rim, o.z0, o.z1, m);
            B(scene, o.x0, o.x1, rim - dp, rim, o.z0, o.z0 + t, m); B(scene, o.x0, o.x1, rim - dp, rim, o.z1 - t, o.z1, m);
            // drain: black disc lying on the bowl floor (default on, 3.5" dia, centred). drain: false hides it;
            // drain: { diameter, position: [x, z], material } changes it.
            if (o.drain !== false) {
              const dr = typeof o.drain === 'object' && o.drain ? o.drain : {};
              const dia = dr.diameter ?? 3.5, th = 0.06;
              const [cx, cz] = dr.position || [(o.x0 + o.x1) / 2, (o.z0 + o.z1) / 2];
              const d = new THREE.Mesh(new THREE.CylinderGeometry(dia / 2, dia / 2, th, 40), lib.get(dr.material || 'sink-drain'));
              d.position.set(cx, rim - dp + 0.2 + th / 2 + 0.005, cz);   // sits just above the bowl floor (no shared plane)
              d.receiveShadow = true; scene.add(d);
            }
            break;
          }
          case 'faucet': {
            const m = lib.get(o.material || 'stainless'), g = new THREE.Group();
            const stem = cyl(0.6, 9, m, 24); stem.position.y = 4.5; g.add(stem);
            const curve = new THREE.CatmullRomCurve3([[0, 9, 0], [0, 13, 0], [0, 15.2, 1.5], [0, 15, 4.5], [0, 13, 6.2], [0, 11.5, 6.4]].map((v) => new THREE.Vector3(...v)));
            const neck = new THREE.Mesh(new THREE.TubeGeometry(curve, 40, 0.45, 16), m); neck.castShadow = true; g.add(neck);
            const lev = cyl(0.18, 3, m, 12); lev.position.set(1.5, 6.5, 0); lev.rotation.z = Math.PI / 2.3; g.add(lev);
            g.position.set(...o.position); g.rotation.y = faceRot[o.facing || 'S']; scene.add(g);
            break;
          }
          case 'outlet': {
            const g = new THREE.Group(), pm = lib.get(o.material || 'outlet-plate'), dk = lib.get('toe-kick-shadow');
            const vert = o.orientation === 'vertical';
            const W = vert ? 2.6 : 4.6, Hh = vert ? 4.6 : 2.6;
            B(g, -W / 2, W / 2, -Hh / 2, Hh / 2, 0, 0.15, pm);
            for (const s of [-1, 1]) {
              const cx = vert ? 0 : s * 1.05, cy = vert ? s * 1.05 : 0;
              B(g, cx - 0.6, cx + 0.6, cy - 0.7, cy + 0.7, 0.15, 0.2, pm);
              B(g, cx - 0.3, cx - 0.15, cy - 0.3, cy + 0.3, 0.2, 0.22, dk); B(g, cx + 0.15, cx + 0.3, cy - 0.3, cy + 0.3, 0.2, 0.22, dk);
            }
            g.position.set(...o.position); g.rotation.y = faceRot[o.facing || 'S']; scene.add(g);
            break;
          }
          case 'tube-shelving': buildShelving(o); break;
          case 'rangetop': buildRangetop(o); break;
          case 'hood': buildHood(o); break;
          case 'ceiling': buildCeiling(o); break;
          case 'led-strip': ledStrip(scene, o.from, o.to, o, o.facing || 'down'); break;
          case 'shelf': buildShelf(o); break;
          case 'leg': buildLeg(o); break;
          case 'paneling': {
            const pl = onBox(o.min, o.max, o.facing);
            const panel = slats(pl.w, pl.h, o, o.material, pl.d);
            pl.g.add(panel);
            break;
          }
          default: warnings.push(`object type "${o.type}" is not supported`);
        }
      } catch (e) { warnings.push(`object ${o.id || o.type}: ${e.message}`); }
    }

    // wall: axis-aligned slab with openings (windows, doors, polygon-shaped windows)
    function buildWall(o) {
      const m = lib.get(o.material || 'drywall-paint');
      const [x0, y0, z0] = o.min, [x1, y1, z1] = o.max;
      const alongX = (x1 - x0) >= (z1 - z0);
      const A0 = alongX ? x0 : z0, A1 = alongX ? x1 : z1;
      const D0 = alongX ? z0 : x0, D1 = alongX ? z1 : x1;
      const piece = (a0, a1, b0, b1) => alongX ? B(scene, a0, a1, b0, b1, z0, z1, m) : B(scene, x0, x1, b0, b1, a0, a1, m);
      const box = (a0, a1, b0, b1, d0, d1, mm) => alongX ? B(scene, a0, a1, b0, b1, d0, d1, mm) : B(scene, d0, d1, b0, b1, a0, a1, mm);
      // a mesh in wall-local coords (u = along the wall, v = up, extruded `depth` through the wall from dStart) -> world.
      // Walls along z: rotating -90 deg maps local x -> +z and local z -> -x, so the group starts at the far face.
      const wallLocal = (mesh, dStart, depth) => {
        const grp = new THREE.Group();
        if (alongX) grp.position.set(0, 0, dStart);
        else { grp.rotation.y = -Math.PI / 2; grp.position.set(dStart + depth, 0, 0); }
        grp.add(mesh); scene.add(grp);
      };
      const polyArea = (pts) => pts.reduce((s, p, i) => { const q = pts[(i + 1) % pts.length]; return s + p[0] * q[1] - q[0] * p[1]; }, 0) / 2;
      const ops = (o.openings || []).map((op) => {
        if (op.shape) {
          const as = op.shape.map((p) => p[0]), ys = op.shape.map((p) => p[1]);
          return { ...op, a0: Math.min(...as), a1: Math.max(...as), y0: Math.min(...ys), y1: Math.max(...ys) };
        }
        return op.kind === 'door' ? { y0: 0, ...op } : op;
      }).sort((p, q) => p.a0 - q.a0);
      let cur = A0;
      for (const op of ops) {
        piece(cur, op.a0, y0, y1);
        piece(op.a0, op.a1, y0, op.y0);
        piece(op.a0, op.a1, op.y1, y1);
        cur = op.a1;
        const face = op.roomSide || o.roomSide || (alongX ? 'S' : 'W');
        const roomAtMin = face === 'N' || face === 'W';
        const fFace = roomAtMin ? D0 : D1, fOut = roomAtMin ? D1 : D0, dir = roomAtMin ? -1 : 1;
        const gd = fFace + (fOut - fFace) * (op.kind === 'door' ? 0.5 : 0.75);
        // polygon-shaped opening: fill the bounding box outside the polygon with wall
        if (op.shape) {
          const s = new THREE.Shape([[op.a0, op.y0], [op.a1, op.y0], [op.a1, op.y1], [op.a0, op.y1]].map(([u, v]) => new THREE.Vector2(u, v)));
          s.holes.push(new THREE.Path(op.shape.map(([u, v]) => new THREE.Vector2(u, v))));
          const geo = new THREE.ExtrudeGeometry(s, { depth: D1 - D0, bevelEnabled: false });
          scaleUV(geo, m);
          const mesh = new THREE.Mesh(geo, m); mesh.castShadow = mesh.receiveShadow = true;
          wallLocal(mesh, D0, D1 - D0);
        }
        const polyGlass = () => {
          const s = new THREE.Shape(op.shape.map(([u, v]) => new THREE.Vector2(u, v)));
          const mesh = new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: 0.2, bevelEnabled: false }), lib.get(op.glassMaterial || 'clear-glass'));
          wallLocal(mesh, gd - 0.1, 0.2);
        };
        const panel = op.panel || (op.kind === 'door' && op.glass === false ? 'solid' : 'glass');
        if (panel === 'solid') {
          box(op.a0, op.a1, op.y0, op.y1, gd - 0.875, gd + 0.875, lib.get(op.panelMaterial || (op.frame && op.frame.material) || 'black-steel'));
        } else if (op.glass !== false) {
          if (op.shape) polyGlass(); else box(op.a0, op.a1, op.y0, op.y1, gd - 0.1, gd + 0.1, lib.get(op.glassMaterial || 'clear-glass'));
          const sd = fOut - dir * 25;
          box(op.a0 - 20, op.a1 + 20, op.y0 - 20, op.y1 + 20, sd, sd - dir * 1, lib.get('window-sky'));
        }
        if (op.jamb) {
          const jm = lib.get(op.jamb), j = 0.4;
          box(op.a0, op.a1, op.y0 - 0.01, op.y0 + j, fFace, gd, jm); box(op.a0, op.a1, op.y1 - j, op.y1, fFace, gd, jm);
          box(op.a0, op.a0 + j, op.y0, op.y1, fFace, gd, jm); box(op.a1 - j, op.a1, op.y0, op.y1, fFace, gd, jm);
        }
        if (op.trim) {
          const tm = lib.get(op.trim.material), tw = op.trim.width ?? 0.8125, tp = op.trim.projection ?? 0.6;
          const d0 = fFace, d1 = fFace + dir * tp;
          box(op.a0 - tw, op.a1 + tw, op.y0 - tw, op.y0, d0, d1, tm); box(op.a0 - tw, op.a1 + tw, op.y1, op.y1 + tw, d0, d1, tm);
          box(op.a0 - tw, op.a0, op.y0, op.y1, d0, d1, tm); box(op.a1, op.a1 + tw, op.y0, op.y1, d0, d1, tm);
        }
        // frame (window/door frame), mullions and muntins, drawn in the glass plane
        const fr = op.frame || (op.kind === 'door' ? { width: 2.5 } : null);
        const fm = lib.get((fr && fr.material) || 'black-steel');
        const fd = (fr && fr.depth) ?? 1.75;
        if (fr) {
          const fw = fr.width ?? 1.5;
          if (op.shape) {
            const pts = op.shape, inward = polyArea(pts) > 0 ? 1 : -1;
            for (let i = 0; i < pts.length; i++) {
              const p = pts[i], q = pts[(i + 1) % pts.length];
              const len = Math.hypot(q[0] - p[0], q[1] - p[1]) + fw;
              // edges overlap at the corners; alternate the depth slightly so overlapping corner faces never share a plane
              const mesh = new THREE.Mesh(boxGeo(len, fw, fd - (i % 2) * 0.04, [24, 24]), fm); mesh.castShadow = true;
              const midU = (p[0] + q[0]) / 2, midV = (p[1] + q[1]) / 2, ang = Math.atan2(q[1] - p[1], q[0] - p[0]);
              const nu = -Math.sin(ang) * inward, nv = Math.cos(ang) * inward;   // points into the opening
              mesh.position.set(midU + nu * fw / 2, midV + nv * fw / 2, 0); mesh.rotation.z = ang;
              const grp = new THREE.Group(); grp.add(mesh);
              if (alongX) grp.position.set(0, 0, gd); else { grp.rotation.y = -Math.PI / 2; grp.position.set(gd, 0, 0); }
              scene.add(grp);
            }
          } else {
            // head and sill run full width; the stiles fit between them (no overlapping, coplanar corner faces)
            const bottomH = op.kind === 'door' ? (fr.threshold === false ? 0 : (fr.bottom ?? fw * 2)) : fw;
            box(op.a0, op.a1, op.y1 - fw, op.y1, gd - fd / 2, gd + fd / 2, fm);
            if (bottomH > 0) box(op.a0, op.a1, op.y0, op.y0 + bottomH, gd - fd / 2, gd + fd / 2, fm);
            box(op.a0, op.a0 + fw, op.y0 + bottomH, op.y1 - fw, gd - fd / 2, gd + fd / 2, fm);
            box(op.a1 - fw, op.a1, op.y0 + bottomH, op.y1 - fw, gd - fd / 2, gd + fd / 2, fm);
          }
        }
        const mu = op.mullions || op.muntins;
        if (mu) {
          // mullions sit slightly shallower than the frame so where they meet it no faces share a plane
          const mw = mu.width ?? 1.25, md = Math.min(fd - 0.1, mu.depth ?? 1.25);
          const spanAt = (a) => {   // vertical extent of the opening at position a (polygon aware)
            if (!op.shape) return [op.y0, op.y1];
            const ys = [];
            const pts = op.shape;
            for (let i = 0; i < pts.length; i++) {
              const p = pts[i], q = pts[(i + 1) % pts.length];
              if ((p[0] - a) * (q[0] - a) <= 0 && p[0] !== q[0]) ys.push(p[1] + (q[1] - p[1]) * (a - p[0]) / (q[0] - p[0]));
            }
            return ys.length >= 2 ? [Math.min(...ys), Math.max(...ys)] : [op.y0, op.y1];
          };
          const widthAt = (y) => {
            if (!op.shape) return [op.a0, op.a1];
            const as = [], pts = op.shape;
            for (let i = 0; i < pts.length; i++) {
              const p = pts[i], q = pts[(i + 1) % pts.length];
              if ((p[1] - y) * (q[1] - y) <= 0 && p[1] !== q[1]) as.push(p[0] + (q[0] - p[0]) * (y - p[1]) / (q[1] - p[1]));
            }
            return as.length >= 2 ? [Math.min(...as), Math.max(...as)] : [op.a0, op.a1];
          };
          for (const a of mu.vertical || []) { const [b0, b1] = spanAt(a); box(a - mw / 2, a + mw / 2, b0, b1, gd - md / 2, gd + md / 2, fm); }
          for (const y of mu.horizontal || []) { const [a0, a1] = widthAt(y); box(a0, a1, y - mw / 2, y + mw / 2, gd - md / 2, gd + md / 2, fm); }
        }
        // door swing on the floor (room side): open leaf line plus quarter-circle arc from the hinge
        if (op.kind === 'door' && op.swing) {
          const wdt = op.a1 - op.a0, roomDir = fOut > fFace ? -1 : 1, su = op.swing === 'left' ? 1 : -1;
          const hingeA = op.swing === 'left' ? op.a0 : op.a1;
          const toWorld = (u, w) => alongX ? new THREE.Vector3(hingeA + u, 0.1, fFace + w) : new THREE.Vector3(fFace + w, 0.1, hingeA + u);
          const pts = [];
          for (let i = 0; i <= 32; i++) { const t = (i / 32) * Math.PI / 2; pts.push(toWorld(Math.cos(t) * wdt * su, Math.sin(t) * wdt * roomDir)); }
          const lm = new THREE.LineBasicMaterial({ color: 0x3a3936 });
          scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lm));
          scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([toWorld(0, 0), toWorld(0, wdt * roomDir)]), lm));
        }
      }
      piece(cur, A1, y0, y1);
    }

    // tube-shelving: ceiling-hung posts (front and back rows) with glass shelves on tube rails
    function buildShelving(o) {
      const m = lib.get(o.material || 'satin-nickel'), gm = lib.get(o.glass || 'clear-glass');
      const r = (o.tube ?? 1) / 2, alongZ = (o.axis || 'z') === 'z';
      const P = (a, d, y) => alongZ ? [d, y, a] : [a, y, d];
      const lowest = Math.min(...o.levels.map((l) => l.y));
      for (const a of o.posts) for (const d of [o.front, o.back]) {
        const p = cyl(r, o.top - lowest + r, m); p.position.set(...P(a, d, (o.top + lowest - r) / 2)); scene.add(p);
        const f = cyl(1.1, 0.4, m, 20); f.position.set(...P(a, d, o.top - 0.2)); scene.add(f);
      }
      for (const lv of o.levels) {
        const a0 = o.posts[lv.between[0]], a1 = o.posts[lv.between[1]];
        for (const d of [o.front, o.back]) {
          const t = cyl(r, a1 - a0, m); if (alongZ) t.rotation.x = Math.PI / 2; else t.rotation.z = Math.PI / 2;
          t.position.set(...P((a0 + a1) / 2, d, lv.y)); scene.add(t);
          for (const a of [a0, a1]) { const c = cyl(0.75, 1.6, m); c.position.set(...P(a, d, lv.y)); scene.add(c); }
        }
        const dmin = Math.min(o.front, o.back) - r, dmax = Math.max(o.front, o.back) + r;
        if (alongZ) B(scene, dmin, dmax, lv.y + r, lv.y + r + 0.375, a0 + 0.6, a1 - 0.6, gm);
        else B(scene, a0 + 0.6, a1 - 0.6, lv.y + r, lv.y + r + 0.375, dmin, dmax, gm);
      }
    }

    // rangetop / cooktop dropped into a counter: body, grates, burner caps and front control knobs
    function buildRangetop(o) {
      const m = lib.get(o.material || 'stainless'), dark = lib.get(o.grateMaterial || 'cast-iron');
      const top = o.top ?? D.boxTop + 1.5, facing = o.facing || 'S';
      const min = [o.x0, top - 5, o.z0], max = [o.x1, top + 0.6, o.z1];
      const pl = onBox(min, max, facing);   // local: x along front, z toward the front (room)
      const w = pl.w, d = pl.d, g = pl.g, h = pl.h;
      B(g, 0, w, 0, h, 0, d, m);
      const panel = o.controls === 'top' ? 0 : 3.2;            // front control strip depth
      const burners = o.burners ?? Math.max(2, Math.round(w / 8));
      const cols = Math.ceil(burners / 2), cw = w / cols;
      // grates
      const gz0 = 1, gz1 = d - panel - 0.5;
      for (let i = 0; i <= cols; i++) B(g, Math.min(w - 0.6, i * cw + (i ? -0.3 : 0.3)), Math.min(w - 0.3, i * cw + (i ? 0.3 : 0.9)), h, h + 0.9, gz0, gz1, dark);
      for (const zz of [gz0, (gz0 + gz1) / 2, gz1 - 0.6]) B(g, 0.3, w - 0.3, h, h + 0.9, zz, zz + 0.6, dark);
      for (let i = 0; i < burners; i++) {
        const ci = Math.floor(i / 2), ri = i % 2;
        const cap = new THREE.Mesh(new THREE.CylinderGeometry(1.6, 1.8, 0.5, 24), dark);
        cap.position.set(ci * cw + cw / 2, h + 0.3, gz0 + (gz1 - gz0) * (ri ? 0.73 : 0.27)); g.add(cap);
      }
      const knobs = o.knobs ?? burners;
      for (let i = 0; i < knobs; i++) {
        const k = new THREE.Mesh(new THREE.CylinderGeometry(0.75, 0.85, 1.1, 24), lib.get(o.knobMaterial || o.material || 'stainless'));
        k.rotation.x = Math.PI / 2; k.castShadow = true;
        if (o.controls === 'top') k.position.set((i + 0.5) * w / knobs, h + 0.5, d - 1.5);
        else k.position.set((i + 0.5) * w / knobs, h - 2.2, d + 0.55);
        g.add(k);
      }
    }

    // range hood: box or tapered body, optional band, chimney (round or square) up to the ceiling
    function frustum(x0, x1, z0, z1, y0, y1, tx0, tx1, tz0, tz1, m) {
      const g = boxGeo(x1 - x0, y1 - y0, z1 - z0, m.userData.repeat || [24, 24]);
      const p = g.attributes.position;
      for (let i = 0; i < p.count; i++) {
        const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
        if (y > 0) {
          const fx = (x + (x1 - x0) / 2) / (x1 - x0), fz = (z + (z1 - z0) / 2) / (z1 - z0);
          p.setX(i, tx0 + fx * (tx1 - tx0) - (x0 + x1) / 2);
          p.setZ(i, tz0 + fz * (tz1 - tz0) - (z0 + z1) / 2);
        }
      }
      g.computeVertexNormals();
      const mesh = new THREE.Mesh(g, m);
      mesh.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
      mesh.castShadow = mesh.receiveShadow = true; scene.add(mesh); return mesh;
    }
    // wall = side of the footprint against the wall (N, S, E or W); the chimney and the tapered top hug that side.
    function buildHood(o) {
      const m = lib.get(o.material || 'stainless');
      const y0 = o.bottom, y1 = o.top, wall = o.wall || 'N';
      const ch = o.chimney || {};
      const cw = ch.diameter || ch.width || 12, cd = ch.diameter || ch.depth || cw;
      const alongX = wall === 'N' || wall === 'S';
      const ca = alongX ? (o.x0 + o.x1) / 2 : (o.z0 + o.z1) / 2;               // chimney centre along the wall
      // chimney rectangle [x0, x1, z0, z1]
      const cr = { N: [ca - cw / 2, ca + cw / 2, o.z0, o.z0 + cd], S: [ca - cw / 2, ca + cw / 2, o.z1 - cd, o.z1],
                   W: [o.x0, o.x0 + cd, ca - cw / 2, ca + cw / 2], E: [o.x1 - cd, o.x1, ca - cw / 2, ca + cw / 2] }[wall];
      // The band occupies the bottom of the hood; the body starts on top of it. They must never share a face plane,
      // or the two materials z-fight (flicker) on the underside.
      const bandH = o.band ? Math.min(o.band.height ?? 1.5, (y1 - y0) / 2) : 0;
      if (o.band) B(scene, o.x0 - 0.05, o.x1 + 0.05, y0, y0 + bandH, o.z0 - 0.05, o.z1 + 0.05, lib.get(o.band.material || 'black-steel'));
      const yb = y0 + bandH;
      if ((o.shape || 'box') === 'tapered') {
        const t = [cr[0] - 1, cr[1] + 1, cr[2] - 1, cr[3] + 1];
        if (wall === 'N') t[2] = o.z0; if (wall === 'S') t[3] = o.z1; if (wall === 'W') t[0] = o.x0; if (wall === 'E') t[1] = o.x1;
        frustum(o.x0, o.x1, o.z0, o.z1, yb, y1, t[0], t[1], t[2], t[3], m);
      } else B(scene, o.x0, o.x1, yb, y1, o.z0, o.z1, m);
      if (ch.to && ch.to > y1) {
        if ((ch.shape || 'square') === 'round') {
          const c = cyl(cw / 2, ch.to - y1, m, 40); c.position.set((cr[0] + cr[1]) / 2, (ch.to + y1) / 2, (cr[2] + cr[3]) / 2); c.receiveShadow = true; scene.add(c);
        } else B(scene, cr[0], cr[1], y1, ch.to, cr[2], cr[3], m);
      }
    }

    // ceiling: flat or sloped, drawn as a single downward-facing surface (invisible from above, so overviews still work)
    // Ceiling "cutaway" (intentional feature, on by default): the ceiling is one surface whose visible side faces
    // DOWN, so it is seen from inside the room but disappears when the camera is above it (overview / top-down).
    // This relies on three things, all enforced here so nothing else can break it:
    //   1. the triangles are wound so the face normal points down (checked and flipped if needed, whatever
    //      order min/max were given in);
    //   2. the ceiling gets its OWN material copy with side = FrontSide (other code sharing the library material,
    //      e.g. a box painted the same colour, can never change this);
    //   3. it never casts shadows, so the sun still lights the room through it.
    // Set "hiddenFromAbove": false to make a solid ceiling that is also visible from above (DoubleSide).
    function buildCeiling(o) {
      const base = lib.get(o.material || 'ceiling-paint');
      const x0 = Math.min(o.min[0], o.max[0]), x1 = Math.max(o.min[0], o.max[0]);
      const z0 = Math.min(o.min[1], o.max[1]), z1 = Math.max(o.min[1], o.max[1]);
      const s = o.slope || null;
      const yAt = (x, z) => {
        if (!s) return o.height;
        const along = s.axis === 'z' ? z : x;
        return o.height + (along - (s.from ?? (s.axis === 'z' ? z0 : x0))) * (s.rise / s.run);
      };
      let pts = [[x0, z0], [x1, z0], [x1, z1], [x0, z1]].map(([x, z]) => new THREE.Vector3(x, yAt(x, z), z));
      const faceNormal = new THREE.Vector3().subVectors(pts[1], pts[0]).cross(new THREE.Vector3().subVectors(pts[2], pts[0]));
      if (faceNormal.y > 0) pts = [pts[0], pts[3], pts[2], pts[1]];         // make the visible side face down
      const tri = [pts[0], pts[1], pts[2], pts[0], pts[2], pts[3]];
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(tri.flatMap((p) => [p.x, p.y, p.z]), 3));
      const rep = base.userData.repeat || [24, 24];
      geo.setAttribute('uv', new THREE.Float32BufferAttribute(tri.flatMap((p) => [p.x / rep[0], p.z / rep[1]]), 2));
      geo.computeVertexNormals();
      const m = base.clone();
      m.side = o.hiddenFromAbove === false ? THREE.DoubleSide : THREE.FrontSide;
      m.userData = { ...base.userData, id: (base.userData.id || 'ceiling') + '|ceiling' };
      const mesh = new THREE.Mesh(geo, m);
      mesh.receiveShadow = true; mesh.castShadow = false;
      mesh.userData.cpr = { type: 'ceiling', hiddenFromAbove: o.hiddenFromAbove !== false };
      scene.add(mesh);
    }

    // LED strip: emissive line plus a few soft point lights along it
    function ledStrip(parent, from, to, o, facing) {
      o = o || {};
      const col = new THREE.Color(o.color || '#fff1dc');
      const a = new THREE.Vector3(...from), b = new THREE.Vector3(...to);
      const len = a.distanceTo(b);
      if (len < 0.5) return;
      const mat = new THREE.MeshBasicMaterial({ color: col });
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(len, 0.15, o.width ?? 0.5), mat);
      mesh.position.copy(a.clone().add(b).multiplyScalar(0.5));
      mesh.rotation.y = -Math.atan2(b.z - a.z, b.x - a.x);
      mesh.rotation.z = Math.atan2(b.y - a.y, Math.hypot(b.x - a.x, b.z - a.z));
      parent.add(mesh);
      const count = Math.max(1, Math.round(len / (o.spacing ?? 30)));
      const off = facing === 'up' ? 3 : facing === 'down' ? -3 : 0;
      for (let i = 0; i < count; i++) {
        if (pointLights.length >= MAX_POINT_LIGHTS) { warnings.push('too many LED lights; extra strips are drawn without light'); break; }
        const pl = new THREE.PointLight(col, o.intensity ?? 0.6, o.reach ?? 48, 2);
        const t = (i + 0.5) / count;
        pl.position.copy(a.clone().lerp(b, t)); pl.position.y += off;
        parent.add(pl); pointLights.push(pl);
      }
    }

    // open shelf with optional rounded corners
    function buildShelf(o) {
      const m = lib.get(o.material || CF.cabinet);
      const r = Math.min(o.cornerRadius ?? 0, (o.x1 - o.x0) / 2 - 0.01, (o.z1 - o.z0) / 2 - 0.01);
      const th = o.thickness ?? 1;
      const sh = new THREE.Shape();
      const [x0, x1, z0, z1] = [o.x0, o.x1, -o.z1, -o.z0];
      sh.moveTo(x0 + r, z0); sh.lineTo(x1 - r, z0); if (r) sh.quadraticCurveTo(x1, z0, x1, z0 + r);
      sh.lineTo(x1, z1 - r); if (r) sh.quadraticCurveTo(x1, z1, x1 - r, z1);
      sh.lineTo(x0 + r, z1); if (r) sh.quadraticCurveTo(x0, z1, x0, z1 - r);
      sh.lineTo(x0, z0 + r); if (r) sh.quadraticCurveTo(x0, z0, x0 + r, z0);
      const geo = new THREE.ExtrudeGeometry(sh, { depth: th, bevelEnabled: false, curveSegments: 10 });
      scaleUV(geo, m);
      const mesh = new THREE.Mesh(geo, m);
      mesh.rotation.x = -Math.PI / 2; mesh.position.y = o.y - th;
      mesh.castShadow = mesh.receiveShadow = true; scene.add(mesh);
    }
    function buildLeg(o) {
      const m = lib.get(o.material || CF.cabinet);
      const [x, z] = o.position, s = o.size ?? 4, y0 = o.y0 ?? 0, h = o.height;
      if ((o.shape || 'square') === 'round') { const c = cyl(s / 2, h, m, 32); c.position.set(x, y0 + h / 2, z); c.receiveShadow = true; scene.add(c); }
      else B(scene, x - s / 2, x + s / 2, y0, y0 + h, z - s / 2, z + s / 2, m);
    }

    // ---------- lights (aimed at the centre of everything built so far, before the floor is added) ----------
    const bb = new THREE.Box3().setFromObject(scene);
    const c = bb.isEmpty() ? new THREE.Vector3() : bb.getCenter(new THREE.Vector3());
    const size = bb.isEmpty() ? new THREE.Vector3(200, 100, 200) : bb.getSize(new THREE.Vector3());
    const reach = Math.max(150, Math.max(size.x, size.z) * 0.75 + 30);
    scene.add(new THREE.HemisphereLight(0xffffff, 0xa59e90, 0.3));
    const sunDir = job.lighting?.sunFrom || [-1, 1.4, -0.4];
    const sun = new THREE.DirectionalLight(0xfff3e2, job.lighting?.sun ?? 1.1);
    const dist = Math.max(160, reach * 1.2);
    sun.position.set(c.x + sunDir[0] * dist, sunDir[1] * dist, c.z + sunDir[2] * dist);
    sun.target.position.copy(c);
    sun.castShadow = true; sun.shadow.mapSize.set(reach > 200 ? 4096 : 2048, reach > 200 ? 4096 : 2048);
    Object.assign(sun.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 10, far: dist * 3 });
    sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.4;
    scene.add(sun, sun.target);
    const fill = new THREE.DirectionalLight(0xeef2ff, 0.35);
    fill.position.set(c.x - 200, 90, c.z + 160); scene.add(fill);

    // ---------- floor ----------
    const fl = job.floor || {};
    if (fl.visible !== false) {
      const fsize = fl.size || Math.max(600, Math.max(size.x, size.z) * 3);
      const f = new THREE.Mesh(new THREE.PlaneGeometry(fsize, fsize), lib.get(fl.material || 'floor-neutral'));
      f.rotation.x = -Math.PI / 2; f.position.set(...(fl.center || [c.x, 0, c.z])); f.receiveShadow = true; scene.add(f);
    }

    // ---------- automatic views (overview + one per compass direction), used when job.views is missing or job.autoViews is true ----------
    const autoViews = [];
    {
      const rb = runBoxes.isEmpty() ? bb : runBoxes;
      const rc = rb.getCenter(new THREE.Vector3()), rs = rb.getSize(new THREE.Vector3());
      const span = Math.max(rs.x, rs.z, 60);
      autoViews.push({ id: 'overview', label: 'Overview', position: [rc.x - span * 0.9, span * 0.75 + 40, rc.z + span * 1.1], target: [rc.x, 30, rc.z], fov: 40, auto: true });
      // looking toward each compass direction from inside the cabinet footprint, at eye height
      const dirs = { north: [0, -1], east: [1, 0], south: [0, 1], west: [-1, 0] };
      for (const [name, [dx, dz]] of Object.entries(dirs)) {
        const half = dx ? rs.x / 2 : rs.z / 2;
        const back = Math.max(half * 0.6, 54);          // stays inside most rooms, far enough to see whole cabinets
        autoViews.push({
          id: name, label: name[0].toUpperCase() + name.slice(1) + ' wall', auto: true,
          position: [rc.x - dx * back, 60, rc.z - dz * back],
          target: [rc.x + dx * half, 32, rc.z + dz * half], fov: 64,
        });
      }
    }

    return { scene, warnings, runs: runInfo, autoViews };
  };
})();
