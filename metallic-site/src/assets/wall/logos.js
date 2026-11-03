// Revival wall: the logos of the revivals Metallic lists, floating at different depths over a dark violet backdrop.
//
// A scene opts in with a "logos" block in its scene.json (scenes/revivals/scene.json); the scene's own layers draw
// the backdrop (sky, nebula, grain, vignette), then this pass draws the logos in ONE instanced draw call.
//
// Composition: no grid. A few sprite groups (far, mid, near "heroes") are scattered over a wrapping field with
// best-candidate (blue-noise) sampling, so they never line up in rows and never pile up. Depth is continuous: far
// sprites are small, slow, hazy and blurred to soft bokeh blobs (a mip level of the logo plus a wide soft edge); near
// ones are large, crisp, faster, with a rim light, a soft shadow and a glass sheen. Every logo glows faintly in its
// own colour (sampled from the icon). Each sprite drifts with the field, floats and turns a little on its own, and
// shifts with the pointer by its depth. Tiles fade out behind the hub's text column and cards.
//
// Logos: the hub's live list (setList) or, before it arrives / when it cannot (first run, offline, RC down, browser
// preview), the icons shipped in brand/revivals (icons.json). A logo shows only once its image has loaded; with no
// image at all the wall shows no tiles, just the backdrop. Never blank or letter tiles.
//
// API (engine.js): new LogoWall(gl, { redraw }, previous)   configure(json.logos | undefined)   setList(list)
//                  active   draw({ t, W, H, cam: [x, y], fade, tint, lite, still })
// The pure helpers are exported for tests/js (no DOM or WebGL needed to call them).

export const MAX_LOGOS = 64;
export const TILE = 256; // texture size of one logo
const BUNDLED = new URL('../brand/revivals/', import.meta.url);

const num = (v, d, lo, hi) => (typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d);
const pair = (v, d, lo, hi) => (Array.isArray(v) && v.length === 2 ? [num(v[0], d[0], lo, hi), num(v[1], d[1], lo, hi)] : d.slice());
const rgb = (v, d) => (Array.isArray(v) && v.length === 3 && v.every((x) => typeof x === 'number' && Number.isFinite(x)) ? v.map((x) => Math.min(2, Math.max(0, x))) : d);
const lerp = (a, b, k) => a + (b - a) * k;
const sm = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

// scene.json "logos" -> clean config, or null when the scene has none.
export function normalizeLogos(j) {
  if (!j || typeof j !== 'object') return null;
  const groups = (Array.isArray(j.groups) ? j.groups : []).slice(0, 4).filter((g) => g && typeof g === 'object').map((g) => {
    const z = pair(g.z, [0, 1], 0, 1).sort((a, b) => a - b), size = pair(g.size, [0.06, 0.1], 0.01, 0.4).sort((a, b) => a - b);
    return { count: Math.round(num(g.count, 40, 1, 400)), z, size, hero: !!g.hero };
  });
  if (!groups.length) return null;
  const dir = Array.isArray(j.dir) && j.dir.length === 2 && j.dir.every(Number.isFinite) && Math.hypot(j.dir[0], j.dir[1]) > 1e-6 ? j.dir : [-1, 0.3];
  const len = Math.hypot(dir[0], dir[1]);
  return {
    seed: Math.round(num(j.seed, 7, 0, 1e6)), dir: [dir[0] / len, dir[1] / len], domain: pair(j.domain, [4.8, 2.1], 1, 12), groups,
    speed: pair(j.speed, [0.003, 0.024], 0, 0.2), blur: pair(j.blur, [18, 0], 0, 40), bright: pair(j.bright, [0.3, 0.95], 0, 1.5),
    fog: pair(j.fog, [0.7, 0], 0, 1), parallax: pair(j.parallax, [0.004, 0.05], 0, 0.15), glow: pair(j.glow, [0.5, 0.9], 0, 2),
    float: num(j.float, 0.012, 0, 0.1), rotate: num(j.rotate, 4, 0, 30), radius: num(j.radius, 0.46, 0, 1),
    fogColor: rgb(j.fogColor, [0.08, 0.07, 0.13]), rim: rgb(j.rim, [0.75, 0.66, 1]), calm: num(j.calm, 0.8, 0, 1),
    column: pair(j.column, [560, 1320], 0, 4000), sheen: num(j.sheen, 0.1, 0, 1), grain: num(j.grain, 0.03, 0, 0.2), vignette: num(j.vignette, 0.4, 0, 1),
  };
}

const safeIcon = (u) => typeof u === 'string' && (/^https:\/\/[^\s"'()]+$/.test(u) || /^[\w][\w/.-]*\.(png|webp|jpg|jpeg)$/i.test(u)) ? u : null;

// The revival list from the hub -> [{ id, name, icon, hue }] (at most MAX_LOGOS, no duplicate ids, safe icon URLs).
export function cleanList(list) {
  const out = [], seen = new Set();
  for (const r of Array.isArray(list) ? list : []) {
    if (!r || typeof r.id !== 'string' || !r.id || seen.has(r.id)) continue;
    seen.add(r.id);
    out.push({ id: r.id, name: typeof r.name === 'string' ? r.name : '', icon: safeIcon(r.icon), hue: Number.isFinite(r.hue) ? ((r.hue % 360) + 360) % 360 : 265 });
    if (out.length >= MAX_LOGOS) break;
  }
  return out;
}

// What the wall shows: the live list when there is one, else the shipped icons. Each item gets the shipped file of
// the same revival (`local`, shown first: it is on disk) and the live icon (`icon`, replaces it when it loads).
// Revivals with neither are left out: the wall never shows a tile without a logo.
export function mergeLogos(live, bundled) {
  const files = new Map((bundled || []).filter((b) => b && b.file).map((b) => [b.id, b]));
  const base = live && live.length ? live : cleanList((bundled || []).map((b) => ({ ...b, icon: null })));
  return base.map((x) => ({ ...x, local: files.get(x.id) ? files.get(x.id).file : null })).filter((x) => x.icon || x.local);
}

// Discord icons come as ?size=128; the near tiles are bigger than that on a large screen, so ask for 256.
export const iconUrl = (u) => (/^https:\/\/cdn\.discordapp\.com\//.test(u) ? u.replace(/([?&]size=)\d+/, `$1${TILE}`) : u);

// The colour a logo glows in: the average of its vivid pixels (weighted by saturation and brightness), lifted to
// full brightness; a grey or black-and-white logo glows in the brand violet. px: RGBA bytes.
export function glowColor(px, fallback = [0.62, 0.5, 1]) {
  let r = 0, g = 0, b = 0, w = 0;
  for (let i = 0; i < px.length; i += 4) {
    const R = px[i], G = px[i + 1], B = px[i + 2], A = px[i + 3] / 255;
    const mx = Math.max(R, G, B), mn = Math.min(R, G, B);
    if (!mx) continue;
    const s = (mx - mn) / mx, k = A * s * s * (mx / 255);
    r += R * k; g += G * k; b += B * k; w += k;
  }
  if (w < (px.length / 4) * 0.02) return fallback.slice();
  const c = [r / w, g / w, b / w], m = Math.max(...c);
  return c.map((x) => +(0.15 + 0.85 * (x / m)).toFixed(3));
}

// -- composition --------------------------------------------------------------------------------------------------
function mulberry(a) {
  return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const torus = (a, b, W, H) => { const dx = Math.abs(a.x - b.x), dy = Math.abs(a.y - b.y); return Math.hypot(Math.min(dx, W - dx), Math.min(dy, H - dy)); };

// Sprites over a W x H wrapping field (screen-height units), far to near (the draw order). Within a group each new
// sprite takes the best of 30 random spots (the one furthest from the others, minus their sizes): blue noise.
// `hero` sprites get the first logos of the list in turn (the most played revivals up front); the others a random one.
export function makeSprites(cfg) {
  const rnd = mulberry(cfg.seed), [W, H] = cfg.domain, all = [];
  let heroRank = 0;
  for (const g of cfg.groups) {
    const placed = [];
    for (let i = 0; i < g.count; i++) {
      const zk = rnd(), z = lerp(g.z[0], g.z[1], zk), size = lerp(g.size[0], g.size[1], zk * 0.6 + rnd() * 0.4);
      let best = null, score = -Infinity;
      for (let k = 0; k < 30; k++) {
        const c = { x: rnd() * W, y: rnd() * H };
        let m = Infinity;
        for (const p of placed) m = Math.min(m, torus(c, p, W, H) - (p.size + size) * 0.5);
        if (m > score) { score = m; best = c; }
      }
      placed.push({ x: best.x, y: best.y, z, zg: (g.z[0] + g.z[1]) / 2, size, seed: rnd(), rot0: rnd() * 2 - 1, pick: Math.floor(rnd() * 1e6), hero: g.hero ? heroRank++ : -1 });
    }
    all.push(...placed);
  }
  return all.sort((a, b) => a.z - b.z);
}
export const logoOf = (s, n) => (n > 0 ? (s.hero >= 0 ? s.hero : s.pick) % n : -1);

// How far (screen-height units) a sprite's quad reaches from its centre at most: half size x quad reach x diagonal.
export const extentOf = (s, reach = 2.3) => (s.size / 2) * reach * Math.SQRT2;

// A sprite's centre and turn at time t (seconds). Each group drifts along cfg.dir as one piece (nearer groups faster),
// so its blue-noise spacing holds forever; the float and turn are each sprite's own. The field wraps at its edges,
// which lie outside the screen for any aspect up to 32:9, so no sprite jumps while it is seen.
export function spriteAt(s, t, cfg, cam = [0, 0], still = false) {
  const [W, H] = cfg.domain, v = lerp(cfg.speed[0], cfg.speed[1], s.zg ?? s.z);
  const wrap = (a, m) => ((a % m) + m) % m - m / 2;
  let x = wrap(s.x + cfg.dir[0] * v * t, W), y = wrap(s.y + cfg.dir[1] * v * t, H);
  let ang = (s.rot0 * cfg.rotate * Math.PI) / 360;
  if (!still) {
    const amp = cfg.float * (0.3 + 0.7 * s.z), f = 0.6 + s.seed * 0.8;
    x += Math.sin(t * 0.21 * f + s.seed * 40) * amp;
    y += Math.sin(t * 0.17 * f + s.seed * 23) * amp;
    ang += (Math.sin(t * 0.09 * f + s.seed * 17) * cfg.rotate * Math.PI * (0.3 + 0.7 * s.z)) / 360;
  }
  const p = lerp(cfg.parallax[0], cfg.parallax[1], s.z);
  return { x: x + cam[0] * p, y: y - cam[1] * p * 0.6, ang };
}

// Where the hub's text column is, as screen uv [fade in from, full from, full to, fade out by]: the hub centres its
// content at most cfg.column[1] px wide inside a 4vw gutter, and its text runs about cfg.column[0] px from the left.
export function textColumn(cssW, cfg) {
  const g = Math.min(56, Math.max(20, cssW * 0.04));
  const left = g + Math.max(0, (cssW - 2 * g - cfg.column[1]) / 2), right = left + cfg.column[0];
  return [Math.max(0, left - 140) / cssW, left / cssW, Math.min(right, cssW) / cssW, (right + 260) / cssW];
}

// How much the wall steps back for the hub's UI at a screen point (uv, y up; 0 = not at all). Mirrored in GLSL.
export function calmAt(x, y, col) {
  const left = sm(col[0], col[1], x) * (1 - sm(col[2], col[3], x)) * sm(0.3, 0.62, y); // headline and news text
  const stats = sm(0.55, 0.75, x) * sm(0.72, 0.86, y) * 0.6; // the live numbers, top right
  const low = 1 - sm(0.3, 0.56, y); // the revival cards
  return Math.max(left, stats, low * 0.85);
}

// -- images -------------------------------------------------------------------------------------------------------
const images = new Map(); // url -> Promise<img | null>; kept across scene switches and a lost GL context
function loadImage(url) {
  if (!images.has(url)) {
    images.set(url, new Promise((res) => {
      const img = new Image();
      img.crossOrigin = 'anonymous'; // Discord's CDN answers with CORS headers, so the texture upload is allowed
      img.decoding = 'async';
      img.onload = () => res(img);
      img.onerror = () => res(null);
      img.src = url;
    }));
  }
  return images.get(url);
}
let bundledList = null;
function loadBundled() {
  bundledList ??= fetch(new URL('icons.json', BUNDLED)).then((r) => (r.ok ? r.json() : null)).then((d) => (d && Array.isArray(d.revivals) ? d.revivals : []), () => []);
  return bundledList;
}

// -- shaders ------------------------------------------------------------------------------------------------------
const VS = `#version 300 es
precision highp float;
layout(location = 0) in vec4 aA; // centre xy (height units, screen centre = 0), half size, angle
layout(location = 1) in vec4 aB; // logo layer, soft edge (tile units), mip level, alpha
layout(location = 2) in vec4 aC; // brightness, haze, nearness 0..1, quad reach (tile units)
layout(location = 3) in vec4 aD; // glow colour, glow strength
uniform float uAspect;
out vec2 vP, vS;
flat out vec4 vB, vC, vD;
void main(){
  vec2 lp = (vec2(float(gl_VertexID & 1), float(gl_VertexID >> 1))*2. - 1.)*aC.w;
  float c = cos(aA.w), s = sin(aA.w);
  vec2 pos = aA.xy + vec2(c*lp.x - s*lp.y, s*lp.x + c*lp.y)*aA.z;
  gl_Position = vec4(pos.x/(uAspect*.5), pos.y*2., 0., 1.);
  vP = lp; vS = pos/vec2(uAspect, 1.) + .5;
  vB = aB; vC = aC; vD = aD;
}`;

const FS = `#version 300 es
precision highp float; precision highp sampler2DArray;
uniform sampler2DArray uTex;
uniform float uT, uFade, uAspect, uRadius, uCalm, uSheen, uGrain, uVig;
uniform vec3 uFogCol, uRim;
uniform vec4 uTint, uCol;
in vec2 vP, vS;
flat in vec4 vB, vC, vD;
out vec4 o;
float sdRR(vec2 p, float r){ vec2 q = abs(p) - (1. - r); return length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r; }
float hash(vec2 p){ p = fract(p*vec2(.1031, .1030)); p += dot(p, p.yx + 33.33); return fract((p.x + p.y)*p.x); }
float calm(vec2 s){
  float left = smoothstep(uCol.x, uCol.y, s.x)*(1. - smoothstep(uCol.z, uCol.w, s.x))*smoothstep(.3, .62, s.y);
  float stats = smoothstep(.55, .75, s.x)*smoothstep(.72, .86, s.y)*.6;
  float low = 1. - smoothstep(.3, .56, s.y);
  return max(max(left, stats), low*.85);
}
void main(){
  float aa = vB.y, near = vC.z;
  float d = sdRR(vP, uRadius);
  float a = 1. - smoothstep(-aa, aa, d);
  float k = calm(vS)*uCalm;
  float ds = sdRR(vP - vec2(0., -.08 - .12*near), uRadius);
  float sh = (1. - smoothstep(-.3, .5 + aa*2., ds))*.42*near;
  float halo = exp(-max(d, 0.)*mix(2.4, 4.2, near))*vD.w;
  vec3 c = vec3(0.);
  if (a > .001) {
    c = textureLod(uTex, vec3(vec2(vP.x, -vP.y)*.5 + .5, vB.x), vB.z).rgb;
    c *= mix(.82, 1.04, smoothstep(-1., .7, vP.y)); // lit from above
    float l = dot(c, vec3(.2126, .7152, .0722));
    c = mix(mix(c, vec3(l), vC.y*.45), uFogCol + vD.rgb*.05, vC.y); // distance: less colour, more backdrop
    float rim = smoothstep(-.1 - aa, 0., d)*(1. - smoothstep(-aa*.5, aa, d));
    float lit = .55 + .45*dot(normalize(vP + 1e-4), vec2(-.45, .89));
    c += mix(uRim, vD.rgb, .35)*rim*lit*(.06 + .3*near);
    c += .05*near*smoothstep(.1, .95, vP.y - vP.x*.2)*(1. - smoothstep(.8, 1., vP.y)); // glass gloss on top
    float sw = (vS.x*uAspect + vS.y*.8)*.55 - mod(uT*.03, 2.8) + .7; // a slow light sweep across the wall
    c += uSheen*exp(-sw*sw*50.)*(.15 + .85*near)*(.7 + .3*vP.y);
  }
  vec2 cc = vS - .5; cc.x *= uAspect*.75;
  float b = vC.x*(1. - k*.45)*(1. - smoothstep(.35, 1.05, length(cc))*uVig);
  c *= b;
  vec3 g = vD.rgb*halo*b*(1. - a);
  c = mix(c, c*uTint.rgb, uTint.a);
  g = mix(g, g*uTint.rgb, uTint.a);
  c += (hash(gl_FragCoord.xy + fract(uT*7.3)*vec2(131., 77.)) - .5)*uGrain;
  float f = vB.w*(1. - k*mix(.35, .85, near)); // behind text and cards the tiles turn to ghosts
  a *= f;
  o = vec4((c*a + g*f)*uFade, a + sh*f*(1. - a));
}`;

function program(gl) {
  const p = gl.createProgram();
  for (const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS]]) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { const e = gl.getShaderInfoLog(s); gl.deleteShader(s); throw new Error(`logos shader: ${e}`); }
    gl.attachShader(p, s);
    gl.deleteShader(s);
  }
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(`logos shader: ${gl.getProgramInfoLog(p)}`);
  const u = {};
  const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const name = gl.getActiveUniform(p, i).name; u[name] = gl.getUniformLocation(p, name); }
  return { p, u };
}

const UNIT = 8; // texture unit of the logo array (the engine uses 0-7)
const STRIDE = 16; // floats per sprite instance

export class LogoWall {
  constructor(gl, { redraw = () => {} } = {}, prev = null) {
    this.gl = gl;
    this.redraw = redraw;
    this.cfg = prev ? prev.cfg : null;
    this.live = prev ? prev.live : [];
    this.bundled = prev ? prev.bundled : null;
    this.sprites = prev ? prev.sprites : [];
    this.items = [];
    this.ready = []; // per logo: { at (ms), color } once its image is on the GPU
    this.prog = null;
    this.tex = null;
    this.key = '';
    this.token = 0;
    this._safe();
  }

  get active() { return !!this.cfg && !!this.prog && this.ready.some(Boolean); }

  configure(json) {
    this.cfg = normalizeLogos(json);
    this.sprites = this.cfg ? makeSprites(this.cfg) : [];
    this._safe();
  }

  setList(list) {
    this.live = cleanList(list);
    this._safe();
  }

  // the wall is decoration: if it cannot be built the scene's backdrop still shows
  _safe() {
    if (!this.cfg) return;
    try { this._sync(); } catch (e) { console.warn(`logo wall off: ${e && e.message}`); this.cfg = null; }
  }

  _sync() {
    const gl = this.gl;
    if (!this.prog) {
      this.prog = program(gl);
      this.vao = gl.createVertexArray();
      this.buf = gl.createBuffer();
      gl.bindVertexArray(this.vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
      for (let i = 0; i < 4; i++) {
        gl.enableVertexAttribArray(i);
        gl.vertexAttribPointer(i, 4, gl.FLOAT, false, STRIDE * 4, i * 16);
        gl.vertexAttribDivisor(i, 1);
      }
      gl.bindVertexArray(null);
      this.data = new Float32Array(0);
    }
    if (this.bundled === null) { // the shipped icons, once: the fallback list and the first image of each logo
      this.bundled = undefined;
      loadBundled().then((b) => { this.bundled = b; this._safe(); });
    }
    const items = mergeLogos(this.live, this.bundled || []);
    const key = items.map((x) => `${x.id}|${x.icon}|${x.local}`).join('\n');
    if (key === this.key) return;
    this.key = key;
    const token = ++this.token;
    this.items = items;
    this.ready = items.map(() => null);
    if (this.tex) gl.deleteTexture(this.tex);
    this.tex = null;
    if (!items.length) { this.redraw(); return; }
    gl.activeTexture(gl.TEXTURE0 + UNIT);
    this.tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D_ARRAY, this.tex);
    gl.texStorage3D(gl.TEXTURE_2D_ARRAY, Math.log2(TILE) + 1, gl.RGBA8, TILE, TILE, items.length);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const cv = document.createElement('canvas');
    cv.width = cv.height = TILE;
    const g = cv.getContext('2d', { willReadFrequently: true });
    const small = document.createElement('canvas');
    small.width = small.height = 16;
    const sg = small.getContext('2d', { willReadFrequently: true });
    const put = (i, img) => {
      if (!img || token !== this.token || gl.isContextLost()) return false;
      const w = img.naturalWidth || img.width, h = img.naturalHeight || img.height, k = TILE / Math.min(w, h);
      g.fillStyle = '#121018'; // under transparent logos
      g.fillRect(0, 0, TILE, TILE);
      g.imageSmoothingQuality = 'high';
      g.drawImage(img, (TILE - w * k) / 2, (TILE - h * k) / 2, w * k, h * k);
      let color;
      try {
        sg.drawImage(cv, 0, 0, 16, 16);
        color = glowColor(sg.getImageData(0, 0, 16, 16).data);
        gl.activeTexture(gl.TEXTURE0 + UNIT);
        gl.bindTexture(gl.TEXTURE_2D_ARRAY, this.tex);
        gl.texSubImage3D(gl.TEXTURE_2D_ARRAY, 0, 0, 0, i, TILE, TILE, 1, gl.RGBA, gl.UNSIGNED_BYTE, cv);
        gl.generateMipmap(gl.TEXTURE_2D_ARRAY);
      } catch { return false; } // a canvas tainted by an image without CORS: leave this logo out
      this.ready[i] = { at: this.ready[i] ? this.ready[i].at : performance.now(), color };
      clearTimeout(this.redrawTimer);
      this.redrawTimer = setTimeout(() => this.redraw(), 50);
      return true;
    };
    items.forEach(async (it, i) => {
      if (it.local) put(i, await loadImage(new URL(it.local, BUNDLED).href)); // on disk: at once
      if (it.icon) put(i, await loadImage(iconUrl(it.icon))); // the live icon replaces it when it arrives
    });
  }

  // Called from the engine's _draw after the scene pass (and its upscale), into the default framebuffer.
  draw({ t, W, H, cam, fade, tint, lite = false, still = false }) {
    if (!this.active) return;
    const gl = this.gl, cfg = this.cfg, { p, u } = this.prog, n = this.items.length, now = performance.now();
    const aspect = W / H;
    if (this.data.length < this.sprites.length * STRIDE) this.data = new Float32Array(this.sprites.length * STRIDE);
    const D = this.data;
    let count = 0;
    for (const s of this.sprites) {
      const li = logoOf(s, n), r = this.ready[li];
      if (!r) continue; // its image is not here (yet): no tile at all
      const reach = lite ? 1.25 : 1 + 1.05 + 0.25 * s.z;
      const e = extentOf(s, reach);
      const q = spriteAt(s, t, cfg, cam, still);
      if (Math.abs(q.x) > aspect / 2 + e || Math.abs(q.y) > 0.5 + e) continue;
      const near = sm(0.55, 0.95, s.z), half = s.size / 2, px = half * H;
      const blur = (lerp(cfg.blur[0], cfg.blur[1], sm(0, 0.8, s.z)) * H) / 1440;
      const soft = (1 + blur) / px;
      const alpha = still ? 1 : sm(0, 900, now - r.at);
      const glow = lite ? 0 : lerp(cfg.glow[0], cfg.glow[1], s.z) * 0.22;
      D.set([q.x, q.y, half, q.ang,
        li, soft, Math.max(0, Math.log2(TILE / (2 * px))) + Math.log2(1 + blur * 0.55), alpha,
        lerp(cfg.bright[0], cfg.bright[1], s.z), lerp(cfg.fog[0], cfg.fog[1], sm(0, 0.85, s.z)), lite ? 0 : near, Math.max(reach, 1 + soft * 1.6),
        r.color[0], r.color[1], r.color[2], glow], count * STRIDE);
      count++;
    }
    if (!count) return;
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(p);
    gl.bindVertexArray(this.vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, D.subarray(0, count * STRIDE), gl.STREAM_DRAW);
    gl.activeTexture(gl.TEXTURE0 + UNIT);
    gl.bindTexture(gl.TEXTURE_2D_ARRAY, this.tex);
    gl.uniform1i(u.uTex, UNIT);
    gl.uniform1f(u.uAspect, aspect);
    gl.uniform1f(u.uT, t);
    gl.uniform1f(u.uFade, fade);
    gl.uniform1f(u.uRadius, cfg.radius);
    gl.uniform1f(u.uCalm, cfg.calm);
    gl.uniform1f(u.uSheen, lite ? 0 : cfg.sheen);
    gl.uniform1f(u.uGrain, cfg.grain);
    gl.uniform1f(u.uVig, cfg.vignette);
    gl.uniform3fv(u.uFogCol, cfg.fogColor);
    gl.uniform3fv(u.uRim, cfg.rim);
    gl.uniform4f(u.uTint, tint[0], tint[1], tint[2], tint[3]);
    gl.uniform4fv(u.uCol, textColumn(typeof innerWidth === 'number' && innerWidth > 0 ? innerWidth : W, cfg));
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, count);
    gl.bindVertexArray(null);
  }
}
