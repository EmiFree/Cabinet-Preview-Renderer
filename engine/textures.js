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
    wood(p, orientation) {
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
    stone(p) {
      const rnd = makeRng(p.seed || 11);
      return canvasTexture(1024, 1024, (g, w, h) => {
        g.fillStyle = p.base || '#ece6da'; g.fillRect(0, 0, w, h);
        for (let i = 0; i < 900; i++) {
          g.fillStyle = `rgba(${(200 + rnd() * 40) | 0},${(190 + rnd() * 40) | 0},${(175 + rnd() * 40) | 0},0.12)`;
          g.beginPath(); g.arc(rnd() * w, rnd() * h, 4 + rnd() * 30, 0, 7); g.fill();
        }
        g.filter = 'blur(1.2px)';
        for (let i = 0; i < (p.veins || 14); i++) {
          g.strokeStyle = `rgba(${(140 + rnd() * 30) | 0},${(132 + rnd() * 30) | 0},${(120 + rnd() * 30) | 0},${0.15 + rnd() * 0.25})`;
          g.lineWidth = 0.6 + rnd() * 2.4; g.beginPath();
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
        const gr = g.createLinearGradient(0, 0, w, h);
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
  };
  CPR.GENERATORS = GENERATORS;

  // Build materials from the registry. imageSource(id, entry) returns a URL or data URI for image textures.
  CPR.createMaterialLibrary = function (registry, imageSource) {
    const defs = registry.materials || {};
    const cache = {};
    const loader = new THREE.TextureLoader();

    // Registry colours are ordinary sRGB hex values (as picked from a swatch); the renderer works in linear light.
    const srgb = (c) => new THREE.Color(c || '#cccccc').convertSRGBToLinear();

    function build(id, orientation) {
      const def = defs[id];
      if (!def) throw new Error(`Unknown material "${id}". Add it to textures/registry.json or fix the job file.`);
      const common = { envMapIntensity: 0.45, roughness: def.roughness ?? 0.6, metalness: def.metalness ?? 0 };
      let m;
      switch (def.kind) {
        case 'procedural': {
          const gen = GENERATORS[def.generator];
          if (!gen) throw new Error(`Material "${id}" uses unknown generator "${def.generator}".`);
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
      m.userData.repeat = orientation === 'h' && def.kind !== 'image' ? rep.slice() : rep.slice();
      if (orientation === 'h' && def.kind === 'procedural' && def.generator === 'wood') m.userData.repeat = [rep[1], rep[0]];
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
      has: (id) => !!defs[id],
      defs,
    };
  };
})();
