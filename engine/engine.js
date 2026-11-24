// Cabinet Preview Renderer - scene builder.
// CPR.buildScene(job, materials) turns a job.json object into a THREE.Scene.
// Units are inches. World axes (plan view, north up): +x = east (right on the plan), +z = south (down on the plan), +y = up.
(function () {
  'use strict';
  const CPR = (window.CPR = window.CPR || {});

  const FACING = { N: [0, -1], S: [0, 1], E: [1, 0], W: [-1, 0] };

  const DEFAULTS = {
    boxTop: 34.5,           // top of cabinet boxes (countertop sits on this)
    frontThickness: 0.75,
    reveal: 0.125,          // gap between adjacent fronts
    frontMargin: 0.1,       // gap above/below the front stack
    stile: 2.25,            // shaker frame width
    base: { toeHeight: 2.5, toeRecess: 3, bandHeight: 2, bandProjection: 0.25 },
  };

  function merge(a, b) {
    const out = Array.isArray(a) ? a.slice() : { ...a };
    for (const k in b || {}) {
      out[k] = b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) && a && typeof a[k] === 'object' ? merge(a[k], b[k]) : b[k];
    }
    return out;
  }

  CPR.buildScene = function (job, lib) {
    const scene = new THREE.Scene();
    const D = merge(DEFAULTS, job.defaults || {});
    const F = merge({ cabinet: 'rift-white-oak-light-bleached', groove: 'bead-groove', toeKick: 'toe-kick-shadow', hardware: 'satin-nickel' }, job.finishes || {});
    const T = D.frontThickness;
    const BASE = D.base.toeHeight + D.base.bandHeight;
    const warnings = [];

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
      if (w <= 0 || h <= 0 || d <= 0) return null;
      const mesh = new THREE.Mesh(boxGeo(w, h, d, m.userData.repeat || [24, 24]), m);
      mesh.position.set(x0 + w / 2, y0 + h / 2, z0 + d / 2);
      mesh.castShadow = mesh.receiveShadow = !m.transparent;
      parent.add(mesh);
      return mesh;
    }
    const cyl = (r, len, m, seg) => { const c = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg || 16), m); c.castShadow = true; return c; };

    // ---------- fronts: local x 0..w left->right as seen from the front, y up, z 0..T toward the viewer ----------
    function grooveRect(g, x0, y0, x1, y1, z) {
      const gm = lib.get(F.groove), gw = 0.14;
      B(g, x0, x1, y0, y0 + gw, z, z + 0.02, gm); B(g, x0, x1, y1 - gw, y1, z, z + 0.02, gm);
      B(g, x0, x0 + gw, y0, y1, z, z + 0.02, gm); B(g, x1 - gw, x1, y0, y1, z, z + 0.02, gm);
    }
    function shaker(w, h, s, beadRoute) {
      s = Math.min(s || D.stile, w / 2 - 0.5, h / 2 - 0.5);
      const g = new THREE.Group(), V = lib.get(F.cabinet), H = lib.get(F.cabinet, 'h');
      B(g, 0, s, 0, h, 0, T, V); B(g, w - s, w, 0, h, 0, T, V);
      B(g, s, w - s, h - s, h, 0, T, H); B(g, s, w - s, 0, s, 0, T, H);
      B(g, s, w - s, s, h - s, 0, 0.4, V);
      if (beadRoute !== false) grooveRect(g, s - 0.42, s - 0.42, w - s + 0.42, h - s + 0.42, T);
      return g;
    }
    function slab(w, h, beadRoute) {
      const g = new THREE.Group();
      B(g, 0, w, 0, h, 0, T, lib.get(F.cabinet, 'h'));
      if (beadRoute !== false) grooveRect(g, 0.55, 0.55, w - 0.55, h - 0.55, T);
      return g;
    }
    function knob(g, x, y) {
      const m = lib.get(F.hardware);
      const b = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 0.9, 20), m);
      b.rotation.x = Math.PI / 2; b.position.set(x, y, T + 0.45);
      const k = new THREE.Mesh(new THREE.SphereGeometry(0.6, 24, 16), m);
      k.scale.z = 0.7; k.position.set(x, y, T + 1.05);
      b.castShadow = k.castShadow = true; g.add(b, k);
    }
    function bar(g, x, y, len, vertical) {
      const m = lib.get(F.hardware);
      const b = cyl(0.25, len, m); if (!vertical) b.rotation.z = Math.PI / 2;
      b.position.set(x, y, T + 1.15); g.add(b);
      for (const s of [-1, 1]) {
        const p = cyl(0.2, 1.15, m, 12); p.rotation.x = Math.PI / 2;
        p.position.set(x + (vertical ? 0 : s * (len / 2 - 0.6)), y + (vertical ? s * (len / 2 - 0.6) : 0), T + 0.58); g.add(p);
      }
    }
    function addHardware(g, w, h, hw) {
      for (const k of [].concat(hw || [])) {
        const inset = k.inset ?? (k.type === 'knob' ? 1.1 : 1.5);
        let x = k.x ?? 'center';
        if (x === 'left') x = inset; else if (x === 'right') x = w - inset; else if (x === 'center') x = w / 2;
        const y = h - (k.fromTop ?? (k.type === 'knob' ? 1.1 : 2.5));
        if (k.type === 'knob') knob(g, x, y);
        else bar(g, x, y, k.length || 6, !!k.vertical);
      }
    }
    function makeFront(f, w, h) {
      if (!f || f.style === 'none') return null;
      const g = f.style === 'slab' ? slab(w, h, f.beadRoute) : shaker(w, h, f.stile, f.beadRoute);
      addHardware(g, w, h, f.hardware);
      return g;
    }

    // ---------- cabinet runs ----------
    const runInfo = [];
    for (const run of job.runs || []) {
      const n = FACING[run.facing];
      if (!n) { warnings.push(`run ${run.id}: facing must be N, S, E or W`); continue; }
      const depth = run.depth ?? 24;
      const boxTop = run.boxTop ?? D.boxTop;
      const g = new THREE.Group();
      g.position.set(run.origin[0], 0, run.origin[1]);
      g.rotation.y = Math.atan2(n[0], n[1]);   // local +z -> facing direction, local +x -> viewer's right
      scene.add(g);
      const V = lib.get(F.cabinet), H = lib.get(F.cabinet, 'h');
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

      // base: decorative band with recessed toe kick
      if (run.base !== false) {
        const bp = D.base.bandProjection, tr = D.base.toeRecess, th = D.base.toeHeight;
        const bx0 = leftExposed ? -bp : 0, bx1 = rightExposed ? L + bp : L;
        B(g, bx0, bx1, th, BASE - 0.3, 0, depth + T + bp, H);
        B(g, bx0 - (leftExposed ? 0.2 : 0), bx1 + (rightExposed ? 0.2 : 0), BASE - 0.3, BASE, 0, depth + T + bp + 0.2, H);
        B(g, leftExposed ? tr : 0, rightExposed ? L - tr : L, 0, th, 0, depth + T - tr, lib.get(F.toeKick));
      }

      for (const p of placed) {
        const it = p.it, w = p.x1 - p.x0;
        if (it.type === 'end-panel') {
          const isLeft = p.x0 === 0;
          const panel = shaker(depth + T, boxTop - BASE, it.stile ?? 3, it.beadRoute);
          panel.rotation.y = isLeft ? -Math.PI / 2 : Math.PI / 2;
          panel.position.set(isLeft ? p.x0 + w : p.x0, BASE, isLeft ? 0 : depth + T);
          // thicker-than-T panels: fill the remainder
          if (w > T) B(g, isLeft ? p.x0 + T : p.x0, isLeft ? p.x1 : p.x1 - T, BASE, boxTop, 0, depth + T, V);
          g.add(panel);
          continue;
        }
        // carcass
        if (it.carcass !== false) {
          if (it.sinkBase) B(g, p.x0, p.x1, BASE, boxTop - (it.sinkDepth ?? 7) - 0.3, 0, depth, V);
          else B(g, p.x0, p.x1, BASE, boxTop, 0, depth, V);
        }
        if (it.type !== 'cabinet') continue;
        // fronts, rows listed top to bottom
        const r = D.reveal, fy0 = BASE + D.frontMargin, fy1 = boxTop - D.frontMargin;
        const rows = it.rows || [{ height: 'fill', fronts: [{ style: 'shaker' }] }];
        const fixed = rows.reduce((s, row) => s + (typeof row.height === 'number' ? row.height : 0), 0);
        const fills = rows.filter((row) => typeof row.height !== 'number').length;
        const fillH = fills ? (fy1 - fy0 - fixed - r * (rows.length - 1)) / fills : 0;
        if (fills === 0 && Math.abs(fixed + r * (rows.length - 1) - (fy1 - fy0)) > 0.25)
          warnings.push(`run ${run.id} item ${it.id || it.label || ''}: row heights + reveals (${(fixed + r * (rows.length - 1)).toFixed(2)}) do not equal front height ${(fy1 - fy0).toFixed(2)}`);
        let top = fy1;
        const lInset = it.inset?.[0] ?? r / 2, rInset = it.inset?.[1] ?? r / 2;
        for (const row of rows) {
          const h = typeof row.height === 'number' ? row.height : fillH;
          const fronts = row.fronts || [{ style: 'shaker' }];
          const avail = w - lInset - rInset - r * (fronts.length - 1);
          const fixedW = fronts.reduce((s, f) => s + (typeof f.width === 'number' ? f.width : 0), 0);
          const flex = fronts.filter((f) => typeof f.width !== 'number').length;
          let fx = p.x0 + lInset;
          for (const f of fronts) {
            const fw = typeof f.width === 'number' ? f.width : (avail - fixedW) / Math.max(flex, 1);
            const front = makeFront(f, fw, h);
            if (front) { front.position.set(fx, top - h, depth); g.add(front); }
            fx += fw + r;
          }
          top -= h + r;
        }
      }
      // world extents for reports
      const a = [n[1], -n[0]];
      const P = (s, t) => [run.origin[0] + a[0] * s + n[0] * t, run.origin[1] + a[1] * s + n[1] * t];
      runInfo.push({ id: run.id, length: L, backLeft: P(0, 0), backRight: P(L, 0), frontRight: P(L, depth + T), frontLeft: P(0, depth + T) });
    }

    // ---------- countertops ----------
    for (const c of job.counters || []) {
      const m = lib.get(c.material), top = c.top ?? D.boxTop + 1.5, th = c.thickness ?? 1.5;
      const cuts = c.cutouts || [];
      if (cuts.length > 1) warnings.push(`counter ${c.id}: only the first cutout is used`);
      const k = cuts[0];
      if (!k) { B(scene, c.x0, c.x1, top - th, top, c.z0, c.z1, m); continue; }
      B(scene, c.x0, k.x0, top - th, top, c.z0, c.z1, m);
      B(scene, k.x1, c.x1, top - th, top, c.z0, c.z1, m);
      B(scene, k.x0, k.x1, top - th, top, c.z0, k.z0, m);
      B(scene, k.x0, k.x1, top - th, top, k.z1, c.z1, m);
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
            const d = new THREE.Mesh(new THREE.CylinderGeometry(0.9, 0.9, 0.1, 24), lib.get('toe-kick-shadow'));
            d.position.set((o.x0 + o.x1) / 2, rim - dp + 0.25, (o.z0 + o.z1) / 2); scene.add(d);
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
          default: warnings.push(`object type "${o.type}" is not supported`);
        }
      } catch (e) { warnings.push(`object ${o.id || o.type}: ${e.message}`); }
    }

    // wall: axis-aligned slab with rectangular openings (windows / pass-throughs)
    function buildWall(o) {
      const m = lib.get(o.material || 'drywall-paint');
      const [x0, y0, z0] = o.min, [x1, y1, z1] = o.max;
      const alongX = (x1 - x0) >= (z1 - z0);
      const A0 = alongX ? x0 : z0, A1 = alongX ? x1 : z1;
      const piece = (a0, a1, b0, b1) => alongX ? B(scene, a0, a1, b0, b1, z0, z1, m) : B(scene, x0, x1, b0, b1, a0, a1, m);
      const ops = (o.openings || []).slice().sort((p, q) => p.a0 - q.a0);
      let cur = A0;
      for (const op of ops) {
        piece(cur, op.a0, y0, y1);
        piece(op.a0, op.a1, y0, op.y0);
        piece(op.a0, op.a1, op.y1, y1);
        cur = op.a1;
        // depth axis (thickness) and room-facing side
        const D0 = alongX ? z0 : x0, D1 = alongX ? z1 : x1;
        const face = op.roomSide || o.roomSide || (alongX ? 'S' : 'W');
        const roomAtMin = face === 'N' || face === 'W';
        const fFace = roomAtMin ? D0 : D1, fOut = roomAtMin ? D1 : D0, dir = roomAtMin ? -1 : 1;
        const box = (a0, a1, b0, b1, d0, d1, mm) => alongX ? B(scene, a0, a1, b0, b1, d0, d1, mm) : B(scene, d0, d1, b0, b1, a0, a1, mm);
        if (op.glass !== false) {
          const gd = fFace + (fOut - fFace) * 0.75;
          box(op.a0, op.a1, op.y0, op.y1, gd - 0.1, gd + 0.1, lib.get(op.glassMaterial || 'clear-glass'));
          const sd = fOut - dir * 25;
          box(op.a0 - 20, op.a1 + 20, op.y0 - 20, op.y1 + 20, sd, sd - dir * 1, lib.get('window-sky'));
        }
        if (op.jamb) {
          const jm = lib.get(op.jamb), j = 0.4, gd = fFace + (fOut - fFace) * 0.75;
          box(op.a0, op.a1, op.y0 - 0.01, op.y0 + j, fFace, gd, jm); box(op.a0, op.a1, op.y1 - j, op.y1, fFace, gd, jm);
          box(op.a0, op.a0 + j, op.y0, op.y1, fFace, gd, jm); box(op.a1 - j, op.a1, op.y0, op.y1, fFace, gd, jm);
        }
        if (op.trim) {
          const tm = lib.get(op.trim.material), tw = op.trim.width ?? 0.8125, tp = op.trim.projection ?? 0.6;
          const d0 = fFace, d1 = fFace + dir * tp;
          box(op.a0 - tw, op.a1 + tw, op.y0 - tw, op.y0, d0, d1, tm); box(op.a0 - tw, op.a1 + tw, op.y1, op.y1 + tw, d0, d1, tm);
          box(op.a0 - tw, op.a0, op.y0, op.y1, d0, d1, tm); box(op.a1, op.a1 + tw, op.y0, op.y1, d0, d1, tm);
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

    // ---------- lights (aimed at the centre of everything built so far, before the floor is added) ----------
    const bb = new THREE.Box3().setFromObject(scene);
    const c = bb.isEmpty() ? new THREE.Vector3() : bb.getCenter(new THREE.Vector3());
    scene.add(new THREE.HemisphereLight(0xffffff, 0xa59e90, 0.3));
    const sunDir = job.lighting?.sunFrom || [-1, 1.4, -0.4];
    const sun = new THREE.DirectionalLight(0xfff3e2, 1.1);
    sun.position.set(c.x + sunDir[0] * 160, sunDir[1] * 160, c.z + sunDir[2] * 160);
    sun.target.position.copy(c);
    sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -150, right: 150, top: 150, bottom: -150, near: 10, far: 700 });
    sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.4;
    scene.add(sun, sun.target);
    const fill = new THREE.DirectionalLight(0xeef2ff, 0.35);
    fill.position.set(c.x - 200, 90, c.z + 160); scene.add(fill);

    // ---------- floor ----------
    const fl = job.floor || {};
    if (fl.visible !== false) {
      const f = new THREE.Mesh(new THREE.PlaneGeometry(fl.size || 600, fl.size || 600), lib.get(fl.material || 'floor-neutral'));
      f.rotation.x = -Math.PI / 2; f.position.set(...(fl.center || [c.x, 0, c.z])); f.receiveShadow = true; scene.add(f);
    }

    return { scene, warnings, runs: runInfo };
  };
})();
