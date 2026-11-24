// Cabinet Preview Renderer - texture generators and material factory.
// Materials are defined in textures/registry.json. This file turns a registry entry into a THREE material.
// To add a new procedural look, add a function to GENERATORS and reference it by name from the registry.
(function () {
  'use strict';
  const CPR = (window.CPR = window.CPR || {});

  function makeRng(seed) {
    let s = (seed || 1) % 2147483647;
    if (s <= 0) s += 2147483646;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  }

  function canvasTexture(w, h, draw) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    draw(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.encoding = THREE.sRGBEncoding;
    t.anisotropy = 8;
    return t;
  }

  const rgba = (rgb, a) => `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${a})`;

  // Each generator returns a THREE texture. orientation: 'v' (grain/pattern along v) or 'h' (rotated 90 deg).
  const GENERATORS = {
    // Straight-grained wood (rift / quarter sawn look).
    'wood-rift'(p, orientation) {
      const vertical = orientation !== 'h';
      const rnd = makeRng((p.seed || 7) + (vertical ? 0 : 1000));
      const dark = p.dark || [150, 126, 92], light = p.light || [245, 238, 224];
      const w = vertical ? 512 : 1024, h = vertical ? 1024 : 512;
      return canvasTexture(w, h, (g) => {
        g.fillStyle = p.base || '#dccdb2'; g.fillRect(0, 0, w, h);
        const L = vertical ? w : h;
        for (let i = 0; i < (p.lines || 420); i++) {
          const pos = rnd() * L, a = 0.04 + rnd() * 0.12, lw = 0.6 + rnd() * 2.2;
          g.strokeStyle = rnd() < 0.75 ? rgba(dark, a) : rgba(light, a * 1.4);
          g.lineWidth = lw; g.beginPath();
          for (let s = 0; s <= 20; s++) {
            const q = (s / 20) * (vertical ? h : w), d = Math.sin(s * 0.7 + pos) * 0.8;
            if (vertical) { s ? g.lineTo(pos + d, q) : g.moveTo(pos + d, q); }
            else { s ? g.lineTo(q, pos + d) : g.moveTo(q, pos + d); }
          }
          g.stroke();
        }
        for (let i = 0; i < 60; i++) {
          g.fillStyle = rgba(light, 0.15 + rnd() * 0.2);
          const x = rnd() * w, y = rnd() * h;
          vertical ? g.fillRect(x, y, 1.5, 6 + rnd() * 14) : g.fillRect(x, y, 6 + rnd() * 14, 1.5);
        }
      });
    },
    // Soft veined natural stone / quartzite.
    // params: base, mottle [r,g,b] (+-mottleSpread), vein [r,g,b], veinAlpha [min,max], veins, veinWidth, blur
    stone(p) {
      const rnd = makeRng(p.seed || 11);
      const mo = p.mottle || [220, 210, 195], ms = p.mottleSpread ?? 20, vc = p.vein || [155, 147, 135], va = p.veinAlpha || [0.15, 0.4];
      return canvasTexture(1024, 1024, (g, w, h) => {
        g.fillStyle = p.base || '#ece6da'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 900; i++) {
          g.fillStyle = `rgba(${(mo[0] - ms + rnd() * ms * 2) | 0},${(mo[1] - ms + rnd() * ms * 2) | 0},${(mo[2] - ms + rnd() * ms * 2) | 0},${p.mottleAlpha ?? 0.12})`;
          g.beginPath(); g.arc(rnd() * w, rnd() * h, 4 + rnd() * 30, 0, 7); g.fill();
        }
        g.filter = `blur(${p.blur ?? 1.2}px)`;
        for (let i = 0; i < (p.veins || 14); i++) {
          g.strokeStyle = `rgba(${(vc[0] - 15 + rnd() * 30) | 0},${(vc[1] - 15 + rnd() * 30) | 0},${(vc[2] - 15 + rnd() * 30) | 0},${va[0] + rnd() * (va[1] - va[0])})`;
          g.lineWidth = (0.6 + rnd() * 2.4) * (p.veinWidth ?? 1); g.beginPath();
          let x = rnd() * w, y = 0; g.moveTo(x, y);
          while (y < h) { x += (rnd() - 0.45) * 60; y += 30 + rnd() * 50; g.lineTo(x, y); }
          g.stroke();
        }
        g.filter = 'none';
      });
    },
    // One tile with grout on its edges; repeatInches sets the tile size.
    'tile-grid'(p) {
      const [w, h] = p.px || [256, 256], gw = p.groutPx || 6;
      return canvasTexture(w, h, (g) => {
        g.fillStyle = p.grout || '#9fa09b'; g.fillRect(0, 0, w, h);
        g.fillStyle = p.base || '#e8ebe9'; g.fillRect(gw / 2, gw / 2, w - gw, h - gw);
        const gr = g.createLinearGradient(0, 0, 0, h); // soft top-to-bottom glaze shading (works for long thin tiles too)
        gr.addColorStop(0, 'rgba(255,255,255,0.18)'); gr.addColorStop(1, 'rgba(0,0,0,0.04)');
        g.fillStyle = gr; g.fillRect(gw / 2, gw / 2, w - gw, h - gw);
      });
    },
    // Two courses of long plank tiles, second course offset by half. repeatInches = [plank length, 2 x plank height].
    'plank-offset'(p) {
      const rnd = makeRng(p.seed || 3);
      const colors = p.colors || ['#a38a6f', '#94795e', '#b09679'];
      return canvasTexture(1024, 342, (g, w, h) => {
        g.fillStyle = p.grout || '#6f5d4c'; g.fillRect(0, 0, w, h);
        const rh = h / 2;
        [[0, 0], [1, 0.5]].forEach(([r, off]) => {
          for (let k = -1; k < 2; k++) {
            const x0 = (k + off) * w;
            g.fillStyle = colors[(r + k + 3) % colors.length];
            g.fillRect(x0 + 1.5, r * rh + 1.5, w - 3, rh - 3);
            for (let i = 0; i < 40; i++) {
              g.strokeStyle = `rgba(80,60,40,${0.05 + rnd() * 0.12})`; g.lineWidth = 1 + rnd() * 2;
              const y = r * rh + 3 + rnd() * (rh - 6);
              g.beginPath(); g.moveTo(x0, y);
              g.bezierCurveTo(x0 + w * 0.3, y + (rnd() - 0.5) * 6, x0 + w * 0.7, y + (rnd() - 0.5) * 6, x0 + w, y);
              g.stroke();
            }
          }
        });
      });
    },
    // Plain sawn (flat sawn) wood: boards with cathedral arches in the middle and straight grain at the edges.
    'wood-plain'(p, orientation) {
      const rnd = makeRng(p.seed || 5);
      const dark = p.dark || [150, 126, 92], light = p.light || [245, 238, 224];
      const W = 512, H = 1024;
      const c = document.createElement('canvas'); c.width = W; c.height = H;
      const g = c.getContext('2d');
      g.fillStyle = p.base || '#cfb48a'; g.fillRect(0, 0, W, H);
      const boards = p.boards || 2, bw = W / boards;
      for (let b = 0; b < boards; b++) {
        const x0 = b * bw, cx = x0 + bw * (0.4 + rnd() * 0.2);
        g.save(); g.beginPath(); g.rect(x0, 0, bw, H); g.clip();
        // slight colour shift per board
        g.fillStyle = rnd() < 0.5 ? rgba(dark, 0.06 + rnd() * 0.06) : rgba(light, 0.05 + rnd() * 0.06);
        g.fillRect(x0, 0, bw, H);
        // straight grain toward the board edges
        for (let i = 0; i < 70; i++) {
          const edge = rnd() < 0.5 ? x0 + rnd() * bw * 0.22 : x0 + bw - rnd() * bw * 0.22;
          g.strokeStyle = rnd() < 0.7 ? rgba(dark, 0.05 + rnd() * 0.12) : rgba(light, 0.08 + rnd() * 0.1);
          g.lineWidth = 0.6 + rnd() * 1.6; g.beginPath();
          for (let s = 0; s <= 24; s++) { const y = (s / 24) * H, d = Math.sin(s * 0.5 + edge) * 1.2; s ? g.lineTo(edge + d, y) : g.moveTo(edge + d, y); }
          g.stroke();
        }
        // cathedral arches: nested curves pointing up, repeated along the board
        const stacks = 2 + Math.floor(rnd() * 2);
        for (let k = 0; k < stacks; k++) {
          const apex = H * (k + 0.3 + rnd() * 0.4) / stacks;
          const rings = 14 + Math.floor(rnd() * 8);
          for (let r = 1; r <= rings; r++) {
            const half = (r / rings) * bw * 0.48, len = 120 + r * 26 + rnd() * 30;
            g.strokeStyle = r % 2 ? rgba(dark, 0.10 + rnd() * 0.14) : rgba(light, 0.06 + rnd() * 0.1);
            g.lineWidth = 0.8 + rnd() * 2.2; g.beginPath();
            for (let s = -20; s <= 20; s++) {
              const t = s / 20, x = cx + t * half + Math.sin(r + s * 0.3) * 1.5;
              const y = apex + len * t * t + Math.sin(r * 1.7 + s) * 1.2;
              s === -20 ? g.moveTo(x, y) : g.lineTo(x, y);
            }
            g.stroke();
          }
        }
        // pores
        for (let i = 0; i < 260; i++) { g.fillStyle = rgba(dark, 0.08 + rnd() * 0.12); g.fillRect(x0 + rnd() * bw, rnd() * H, 1, 3 + rnd() * 6); }
        g.restore();
        g.fillStyle = rgba(dark, 0.18); g.fillRect(x0, 0, 1, H); // board joint
      }
      let out = c;
      if (orientation === 'h') {
        out = document.createElement('canvas'); out.width = H; out.height = W;
        const o = out.getContext('2d'); o.translate(H, 0); o.rotate(Math.PI / 2); o.drawImage(c, 0, 0);
      }
      const t = new THREE.CanvasTexture(out);
      t.wrapS = t.wrapT = THREE.RepeatWrapping; t.encoding = THREE.sRGBEncoding; t.anisotropy = 8;
      return t;
    },
  };
  CPR.GENERATORS = GENERATORS;
  const GRAIN_GENERATORS = new Set(['wood-rift', 'wood-plain']); // grain rotates for rails and drawer fronts

  // ---------- customisable materials ----------
  // A registry entry with a "custom" block (e.g. custom-rift) can be instantiated by a job under its own id:
  //   job.materials["cab-sage"] = { "base": "custom-rift", "color": "#7d8b6a", "gloss": 0.3 }
  // color: sRGB hex. gloss: 0 (matte) .. 1 (high gloss). seed: integer, changes the grain pattern.
  const hexRgb = (h) => { const n = parseInt(String(h).replace('#', ''), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const toHex = (rgb) => '#' + rgb.map((v) => v.toString(16).padStart(2, '0')).join('');
  CPR.applyCustom = function (base, opts) {
    const def = JSON.parse(JSON.stringify(base));
    const o = { ...(base.custom || {}), ...(opts || {}) };
    delete def.custom;
    const glossToRough = (gl) => Math.min(1, Math.max(0.04, 1 - gl * 0.92));
    if (def.kind === 'procedural' && GRAIN_GENERATORS.has(def.generator)) {
      if (o.color) {
        const c = hexRgb(o.color);
        def.params = { ...(def.params || {}), base: o.color, dark: mix(c, [0, 0, 0], o.grainContrast ?? 0.42), light: mix(c, [255, 255, 255], 0.3) };
      }
      if (o.seed != null) def.params = { ...(def.params || {}), seed: o.seed };
    } else if (o.color) {
      def.color = o.color;
    }
    if (o.gloss != null) def.roughness = glossToRough(o.gloss);
    if (o.label) def.label = o.label;
    return def;
  };
  CPR.grooveFor = (hex) => toHex(mix(hexRgb(hex), [0, 0, 0], 0.55)); // dark shadow colour for a given wood colour

  // Build materials from the registry. imageSource(id, entry) returns a URL or data URI for image textures.
  // jobMaterials: the job's "materials" object (custom instances); they may shadow nothing in the registry.
  CPR.createMaterialLibrary = function (registry, imageSource, jobMaterials) {
    const regDefs = registry.materials || {};
    const defs = { ...regDefs };
    for (const [id, inst] of Object.entries(jobMaterials || {})) {
      const base = regDefs[inst.base];
      if (!base) throw new Error(`Job material "${id}": base "${inst.base}" is not in textures/registry.json.`);
      if (!base.custom) throw new Error(`Job material "${id}": base "${inst.base}" is not customisable (no "custom" block).`);
      defs[id] = CPR.applyCustom(base, inst);
    }
    for (const [id, d] of Object.entries(regDefs)) if (d.custom) defs[id] = CPR.applyCustom(d, {}); // defaults when used directly
    const cache = {};
    const loader = new THREE.TextureLoader();

    // Registry colours are ordinary sRGB hex values (as picked from a swatch); the renderer works in linear light.
    const srgb = (c) => new THREE.Color(c || '#cccccc').convertSRGBToLinear();

    function build(id, orientation) {
      const def = defs[id];
      if (!def) throw new Error(`Unknown material "${id}". Add it to textures/registry.json, define it in the job's "materials", or fix the job file.`);
      const common = { envMapIntensity: 0.45, roughness: def.roughness ?? 0.6, metalness: def.metalness ?? 0 };
      let m;
      switch (def.kind) {
        case 'procedural': {
          const gen = GENERATORS[def.generator];
          if (!gen) throw new Error(`Material "${id}" uses unknown generator "${def.generator}"` +
            (def.generator === 'wood' ? ' (renamed: use "wood-rift" or "wood-plain").' : `. Available: ${Object.keys(GENERATORS).join(', ')}.`));
          m = new THREE.MeshStandardMaterial({ ...common, map: gen(def.params || {}, orientation) });
          break;
        }
        case 'image': {
          const tex = loader.load(imageSource(id, def));
          tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.encoding = THREE.sRGBEncoding; tex.anisotropy = 8;
          if (orientation === 'h') { tex.center.set(0.5, 0.5); tex.rotation = Math.PI / 2; }
          m = new THREE.MeshStandardMaterial({ ...common, map: tex });
          break;
        }
        case 'metal':
          m = new THREE.MeshStandardMaterial({ ...common, color: srgb(def.color), metalness: def.metalness ?? 1 });
          break;
        case 'glass':
          m = new THREE.MeshStandardMaterial({ color: srgb(def.color), roughness: 0.05, metalness: 0, transparent: true, opacity: def.opacity ?? 0.28 });
          break;
        case 'sky':
          m = new THREE.MeshBasicMaterial({ color: srgb(def.color) });
          break;
        case 'color':
        default:
          m = new THREE.MeshStandardMaterial({ ...common, color: srgb(def.color) });
      }
      const rep = def.repeatInches || [24, 24];
      m.userData.repeat = rep.slice();
      if (orientation === 'h' && def.kind === 'procedural' && GRAIN_GENERATORS.has(def.generator)) m.userData.repeat = [rep[1], rep[0]];
      m.userData.id = id;
      return m;
    }

    // get(id) -> material; get(id, 'h') -> rotated-grain variant (used for rails and drawer fronts).
    return {
      get(id, orientation) {
        const key = id + '|' + (orientation || 'v');
        if (!cache[key]) cache[key] = build(id, orientation || 'v');
        return cache[key];
      },
      // Shadow-line material derived from a wood/cabinet material's colour (finishes.groove = "auto").
      autoGroove(cabinetId) {
        const key = 'auto-groove|' + cabinetId;
        if (!cache[key]) {
          const d = defs[cabinetId] || {};
          const base = (d.params && d.params.base) || d.color || '#c8b89c';
          cache[key] = new THREE.MeshStandardMaterial({ envMapIntensity: 0.45, roughness: 0.8, color: srgb(CPR.grooveFor(base)) });
          cache[key].userData = { repeat: [24, 24], id: key };
        }
        return cache[key];
      },
      has: (id) => !!defs[id],
      defs,
    };
  };
})();
