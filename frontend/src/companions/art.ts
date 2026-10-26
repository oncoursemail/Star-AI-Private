/**
 * The companions as layered vector parts: every part is its own painted layer (with the hidden overlap
 * painted in, so joints never gap), placed on the skeleton of its view. Coordinates are model units:
 * the figure is 100 units tall, feet at y = 0, head top near y = -100, x = 0 on the body's centre line.
 * Side views face +x; the stage mirrors them for the other way.
 *
 * Why vector parts and not split AI sheets: generated turnaround sheets did not give parts that line up
 * between views and frames; drawn parts match exactly, bend cleanly and stay crisp at any size.
 */
import type {CastId, Style} from './cast'
import {STYLES} from './cast'
import type {ChainFeel} from './physics'

export type View = 'front' | 'side'
export type Pt = [number, number]
type G = CanvasRenderingContext2D

export type BoneDef = { name: string; parent: string | null; at: Pt }
export type SlotDef = { name: string; bone: string; attachment: string | null; shade?: number }
export type PartDef = {
  slot: string
  name: string
  /** Model-space box the layer is painted in (the mesh grid covers it). */
  box: readonly [number, number, number, number]
  /** One bone (rigid) or a chain of bones with joints (joints.length = bones.length + 1). */
  bones: readonly string[]
  joints?: readonly Pt[]
  grid?: readonly [number, number]
  paint: (g: G) => void
}
export type ChainDef = { name: string; bones: readonly string[]; tip: Pt; feel: ChainFeel }
export type ViewDef = { bones: BoneDef[]; slots: SlotDef[]; parts: PartDef[]; chains: ChainDef[] }

// ---------- drawing helpers ----------
const n2 = (v: number) => (Math.round(v * 100) / 100).toString()

/** Smooth closed outline through midpoints; repeat a point to make a sharp corner (lock tips). */
export function smooth(pts: readonly Pt[], closed = true): string {
  if (pts.length < 3) return 'M' + pts.map(p => n2(p[0]) + ',' + n2(p[1])).join(' L')
  const mid = (a: Pt, b: Pt) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
  if (!closed) {
    let d = `M${n2(pts[0][0])},${n2(pts[0][1])}`
    for (let i = 1; i < pts.length - 1; i++) { const m = mid(pts[i], pts[i + 1]); d += ` Q${n2(pts[i][0])},${n2(pts[i][1])} ${n2(m[0])},${n2(m[1])}` }
    const l = pts[pts.length - 1]
    return d + ` L${n2(l[0])},${n2(l[1])}`
  }
  const start = mid(pts[pts.length - 1], pts[0])
  let d = `M${n2(start[0])},${n2(start[1])}`
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], m = mid(p, pts[(i + 1) % pts.length])
    d += ` Q${n2(p[0])},${n2(p[1])} ${n2(m[0])},${n2(m[1])}`
  }
  return d + 'Z'
}

/** Catmull-Rom points through the joints (for smooth lock spines). */
export function spline(pts: readonly Pt[], per = 4): Pt[] {
  const out: Pt[] = []
  const at = (i: number) => pts[Math.max(0, Math.min(pts.length - 1, i))]
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = at(i - 1), p1 = at(i), p2 = at(i + 1), p3 = at(i + 2)
    for (let k = 0; k < per; k++) {
      const s = k / per, s2 = s * s, s3 = s2 * s
      const c = (a: number, b: number, cc: number, d: number) => 0.5 * (2 * b + (-a + cc) * s + (2 * a - 5 * b + 4 * cc - d) * s2 + (-a + 3 * b - 3 * cc + d) * s3)
      out.push([c(p0[0], p1[0], p2[0], p3[0]), c(p0[1], p1[1], p2[1], p3[1])])
    }
  }
  out.push([...pts[pts.length - 1]] as Pt)
  return out
}

/**
 * Outline of a tapered lock (hair strand, tail, limb) around a spine: width w(u) along it, a small
 * hidden extension above the root, a pointed or round tip, and an optional wave on the edges.
 */
export function lock(spine: readonly Pt[], w: (u: number) => number, opts: { tip?: 'point' | 'round' | 'flat'; wave?: number; lead?: number; curl?: number } = {}): Pt[] {
  const pts = spline(spine, 5)
  const n = pts.length
  const left: Pt[] = [], right: Pt[] = []
  const tan = (i: number): Pt => {
    const a = pts[Math.max(0, i - 1)], b = pts[Math.min(n - 1, i + 1)]
    const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1
    return [dx / l, dy / l]
  }
  const wave = opts.wave ?? 0
  for (let i = 0; i < n; i++) {
    const u = i / (n - 1), [tx, ty] = tan(i), half = w(u) / 2
    const wv = wave * Math.sin(u * Math.PI * 3.2)
    left.push([pts[i][0] - ty * half * (1 + wv), pts[i][1] + tx * half * (1 + wv)])
    right.push([pts[i][0] + ty * half * (1 - wv), pts[i][1] - tx * half * (1 - wv)])
  }
  const [t0x, t0y] = tan(0), lead = opts.lead ?? 2
  const top: Pt[] = [[right[0][0] - t0x * lead, right[0][1] - t0y * lead], [left[0][0] - t0x * lead, left[0][1] - t0y * lead]]
  const [tx, ty] = tan(n - 1), end = pts[n - 1]
  let tip: Pt[]
  if (opts.tip === 'round') {
    const r = w(1) / 2
    tip = [[end[0] - ty * r * 0.7 + tx * r * 0.7, end[1] + tx * r * 0.7 + ty * r * 0.7], [end[0] + tx * r * 1.05, end[1] + ty * r * 1.05], [end[0] + ty * r * 0.7 + tx * r * 0.7, end[1] - tx * r * 0.7 + ty * r * 0.7]]
  } else if (opts.tip === 'flat') tip = []
  else {
    const c = opts.curl ?? 0, len = Math.max(2, w(1) * 1.3)
    const p: Pt = [end[0] + tx * len - ty * c, end[1] + ty * len + tx * c]
    tip = [p, p]
  }
  return [...top, ...left, ...tip, ...right.reverse()]
}

const path = (d: string) => new Path2D(d)

function ink(g: G, d: string | Path2D, fill: string | CanvasGradient | null, line: string | null, lw = 0.75) {
  const p = typeof d === 'string' ? path(d) : d
  if (fill) { g.fillStyle = fill; g.fill(p) }
  if (line && lw > 0) { g.lineWidth = lw; g.strokeStyle = line; g.lineJoin = 'round'; g.lineCap = 'round'; g.stroke(p) }
}
function stroke(g: G, d: string, color: string, lw: number, alpha = 1) {
  g.save(); g.globalAlpha = alpha; ink(g, d, null, color, lw); g.restore()
}
/** Paint `d` clipped inside `inside` (cel shading, highlights). */
function within(g: G, inside: string | Path2D, d: string, fill: string, alpha = 1) {
  g.save(); g.clip(typeof inside === 'string' ? path(inside) : inside); g.globalAlpha = alpha; g.fillStyle = fill; g.fill(path(d)); g.restore()
}
const ellipse = (x: number, y: number, rx: number, ry: number, rot = 0) => {
  const p = new Path2D(); p.ellipse(x, y, rx, ry, rot, 0, Math.PI * 2); return p
}
function hex(c: string): [number, number, number] {
  const v = parseInt(c.slice(1), 16)
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255]
}
export function mix(a: string, b: string, t: number): string {
  const x = hex(a), y = hex(b)
  return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, '0')).join('')
}
const box = (pts: readonly Pt[], pad = 1.5): [number, number, number, number] => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y) }
  return [x0 - pad, y0 - pad, x1 + pad, y1 + pad]
}
const mirror = (pts: readonly Pt[]): Pt[] => pts.map(([x, y]) => [-x, y])

function hairFill(g: G, s: Style): CanvasGradient {
  const grad = g.createLinearGradient(0, s.tipBand[0], 0, s.tipBand[1])
  grad.addColorStop(0, s.hair[0]); grad.addColorStop(1, s.hair[1])
  return grad
}

/** A hair lock: gradient fill, outline, a shade line down the middle and a sheen near the root. */
function paintLock(g: G, s: Style, spine: readonly Pt[], w: (u: number) => number, opts: Parameters<typeof lock>[2] = {}) {
  const outline = smooth(lock(spine, w, opts))
  ink(g, outline, hairFill(g, s), s.outline, 0.7)
  const sp = spline(spine, 5)
  const inner = sp.slice(Math.floor(sp.length * 0.18), Math.floor(sp.length * 0.92)).map(([x, y], i) => [x + Math.sin(i * 0.7) * 0.6, y] as Pt)
  if (inner.length > 2) stroke(g, smooth(inner, false), s.hairShade, 0.6, 0.55)
  const top = sp.slice(1, Math.max(3, Math.floor(sp.length * 0.3))).map(([x, y]) => [x - w(0) * 0.18, y] as Pt)
  stroke(g, smooth(top, false), '#ffffff', 0.7, 0.3)
}

// ---------- shared feel ----------
const FEEL = {
  hair: (s: Style): ChainFeel => ({stiffness: 260 * s.hairStiffness, tip: 0.55, keep: 0.965, gravity: 60, limit: 0.55, inertia: 0.45}),
  lockSide: (s: Style): ChainFeel => ({stiffness: 320 * s.hairStiffness, tip: 0.7, keep: 0.96, gravity: 50, limit: 0.5, inertia: 0.4}),
  bangs: (s: Style): ChainFeel => ({stiffness: 900 * s.hairStiffness, tip: 1, keep: 0.94, gravity: 30, limit: 0.25}),
  catEar: {stiffness: 1500, tip: 0.8, keep: 0.93, gravity: 10, limit: 0.5} as ChainFeel,
  dogEar: {stiffness: 170, tip: 0.6, keep: 0.965, gravity: 90, limit: 0.9, inertia: 0.5} as ChainFeel,
  catTail: {stiffness: 140, tip: 0.5, keep: 0.965, gravity: 8, limit: 0.7, inertia: 0.5} as ChainFeel,
  dogTail: {stiffness: 420, tip: 0.8, keep: 0.95, gravity: 12, limit: 1} as ChainFeel,
  skirt: {stiffness: 700, tip: 0.8, keep: 0.93, gravity: 25, limit: 0.45} as ChainFeel,
  cape: {stiffness: 380, tip: 0.7, keep: 0.95, gravity: 35, limit: 0.45, inertia: 0.4} as ChainFeel,
  pigtail: (s: Style): ChainFeel => ({stiffness: 200 * s.hairStiffness, tip: 0.5, keep: 0.968, gravity: 70, limit: 0.7, inertia: 0.5}),
}

/** Bones along a chain: names `${base}0..n-1` at joints[0..n-1]; joints[n] is the tip. */
function chainBones(base: string, parent: string, joints: readonly Pt[]): BoneDef[] {
  return joints.slice(0, -1).map((at, i) => ({name: base + i, parent: i ? base + (i - 1) : parent, at}))
}
const names = (base: string, joints: readonly Pt[]) => joints.slice(0, -1).map((_, i) => base + i)

// ---------- faces ----------
type Eye = { x: number; y: number; w: number; h: number; outer: -1 | 1 }

function eyeWhite(e: Eye) {
  const {x, y, w, h} = e
  return smooth([[x - w, y - h * 0.55], [x - w * 0.2, y - h * 1.02], [x + w, y - h * 0.62], [x + w * 1.02, y + h * 0.45], [x, y + h * 0.98], [x - w * 1.02, y + h * 0.45]])
}
function paintEyeWhite(g: G, s: Style, e: Eye) {
  ink(g, eyeWhite(e), '#ffffff', null)
  within(g, eyeWhite(e), `M${e.x - e.w * 1.2},${e.y - e.h * 1.2} H${e.x + e.w * 1.2} V${e.y - e.h * 0.35} H${e.x - e.w * 1.2}Z`, mix(s.skinShade, '#ffffff', 0.3), 0.8)
}
function paintIris(g: G, s: Style, e: Eye) {
  const {x, y, w, h} = e
  const iris = ellipse(x, y + h * 0.12, w * 0.84, h * 0.86)
  const grad = g.createLinearGradient(0, y - h, 0, y + h)
  grad.addColorStop(0, mix(s.eye[0], '#000000', 0.25)); grad.addColorStop(0.55, s.eye[0]); grad.addColorStop(1, s.eye[1])
  ink(g, iris, grad, mix(s.eye[0], '#000000', 0.45), 0.45)
  ink(g, ellipse(x, y + h * 0.02, w * 0.4, h * 0.46), mix(s.eye[0], '#000000', 0.6), null)
  g.save(); g.globalAlpha = 0.55; ink(g, ellipse(x, y + h * 0.55, w * 0.5, h * 0.2), s.eye[1], null); g.restore()
  ink(g, ellipse(x - w * 0.32 * e.outer * -1, y - h * 0.32, w * 0.3, h * 0.24), '#ffffff', null)
  ink(g, ellipse(x + w * 0.34 * e.outer * -1, y + h * 0.42, w * 0.13, h * 0.1), '#ffffff', null)
}
function paintLash(g: G, s: Style, e: Eye, kind: 'open' | 'half' | 'closed' | 'happy' | 'squeeze') {
  const {x, y, w, h, outer} = e
  const o = outer
  const lash = s.outline
  if (kind === 'open') {
    const d = smooth([[x - w * 1.1 * -o, y - h * 0.45], [x - w * 0.15 * -o, y - h * 1.08], [x + w * 1.08 * -o, y - h * 0.7], [x + w * 1.35 * -o, y - h * 0.5]], false)
    stroke(g, d, lash, 1.35)
    stroke(g, `M${x + w * 1.0 * -o},${y - h * 0.68} L${x + w * 1.45 * -o},${y - h * 0.92}`, lash, 0.8)
    stroke(g, smooth([[x - w * 0.5, y + h * 0.95], [x, y + h * 1.04], [x + w * 0.5, y + h * 0.95]], false), lash, 0.45, 0.7)
  } else if (kind === 'half') {
    const lid = `M${x - w * 1.4},${y - h * 1.4} H${x + w * 1.4} V${y - h * 0.05} Q${x},${y - h * 0.35} ${x - w * 1.4},${y - h * 0.05}Z`
    within(g, eyeWhite(e), lid, s.skin)
    stroke(g, smooth([[x - w * 1.1 * -o, y - h * 0.02], [x, y - h * 0.3], [x + w * 1.25 * -o, y - h * 0.1]], false), lash, 1.25)
    stroke(g, smooth([[x - w * 0.5, y + h * 0.95], [x, y + h * 1.04], [x + w * 0.5, y + h * 0.95]], false), lash, 0.45, 0.7)
  } else if (kind === 'closed') {
    stroke(g, smooth([[x - w * 1.05, y + h * 0.1], [x, y + h * 0.55], [x + w * 1.05, y + h * 0.1]], false), lash, 1.2)
    stroke(g, `M${x + w * 1.0 * -o},${y + h * 0.12} L${x + w * 1.35 * -o},${y - h * 0.05}`, lash, 0.7)
  } else if (kind === 'happy') {
    stroke(g, smooth([[x - w * 1.05, y + h * 0.35], [x, y - h * 0.35], [x + w * 1.05, y + h * 0.35]], false), lash, 1.25)
  } else {
    const a = -o
    stroke(g, `M${x - w * 0.95 * a},${y - h * 0.5} L${x + w * 0.85 * a},${y} L${x - w * 0.95 * a},${y + h * 0.5}`, lash, 1.2)
  }
}
const MOUTHS = ['smile', 'open', 'wide', 'o', 'flat', 'kiss', 'frown', 'cat'] as const
export type Mouth = typeof MOUTHS[number]
function paintMouth(g: G, s: Style, x: number, y: number, kind: Mouth, side: boolean) {
  const line = s.outline, k = side ? 0.7 : 1
  const inside = '#a3343f', tongue = '#f27f8f'
  if (kind === 'smile') stroke(g, smooth([[x - 2.2 * k, y - 0.4], [x, y + 1.1], [x + 2.2 * k, y - 0.4]], false), line, 0.75)
  else if (kind === 'flat') stroke(g, `M${x - 1.8 * k},${y} L${x + 1.8 * k},${y}`, line, 0.7)
  else if (kind === 'cat') stroke(g, `M${x - 2.4 * k},${y - 0.4} Q${x - 1.2 * k},${y + 1.2} ${x},${y - 0.1} Q${x + 1.2 * k},${y + 1.2} ${x + 2.4 * k},${y - 0.4}`, line, 0.7)
  else if (kind === 'frown') stroke(g, `M${x - 2.4 * k},${y + 0.6} Q${x - 1.2 * k},${y - 0.8} ${x},${y + 0.2} Q${x + 1.2 * k},${y - 0.8} ${x + 2.4 * k},${y + 0.6}`, line, 0.7)
  else if (kind === 'kiss') stroke(g, `M${x - 0.6},${y - 1.6} Q${x + 1.6},${y - 1} ${x},${y} Q${x + 1.6},${y + 1} ${x - 0.6},${y + 1.6}`, line, 0.75)
  else if (kind === 'o') { ink(g, ellipse(x, y + 0.4, 1.5 * k, 1.9), inside, line, 0.6); ink(g, ellipse(x, y + 1.2, 1 * k, 0.6), tongue, null) }
  else {
    const wd = (kind === 'wide' ? 3.6 : 2.7) * k, dp = kind === 'wide' ? 4.2 : 3.2
    const d = `M${x - wd},${y - 0.8} Q${x},${y - 0.2} ${x + wd},${y - 0.8} Q${x + wd * 0.85},${y + dp} ${x},${y + dp} Q${x - wd * 0.85},${y + dp} ${x - wd},${y - 0.8}Z`
    ink(g, d, inside, null)
    within(g, d, `M${x - wd},${y + dp * 0.55} Q${x},${y + dp * 0.2} ${x + wd},${y + dp * 0.55} V${y + dp + 1} H${x - wd}Z`, tongue)
    ink(g, d, null, line, 0.65)
  }
}
function paintBlush(g: G, x: number, y: number, rx: number) {
  g.save(); g.globalAlpha = 0.5
  ink(g, ellipse(x, y, rx, rx * 0.5), '#ff8fa3', null)
  g.globalAlpha = 0.6
  for (let i = -1; i <= 1; i++) stroke(g, `M${x + i * rx * 0.45 - 0.5},${y + 0.6} L${x + i * rx * 0.45 + 0.4},${y - 0.6}`, '#e0607a', 0.35)
  g.restore()
}
function paintBrow(g: G, s: Style, x: number, y: number, w: number) {
  stroke(g, smooth([[x - w, y + 0.5], [x, y - 0.7], [x + w, y + 0.5]], false), mix(s.hairShade, s.outline, 0.3), 0.75)
}

// ---------- accessories ----------
function paintBow(g: G, color: string, line: string, x: number, y: number, k = 1, tails = true) {
  const dark = mix(color, '#000000', 0.25)
  const loop = (sx: number) => `M${x},${y} C${x + sx * 2.8 * k},${y - 3.2 * k} ${x + sx * 6 * k},${y - 2.6 * k} ${x + sx * 5.6 * k},${y} C${x + sx * 6 * k},${y + 2.8 * k} ${x + sx * 2.8 * k},${y + 3 * k} ${x},${y}Z`
  if (tails) for (const sx of [-1, 1]) ink(g, `M${x},${y} L${x + sx * 1.4 * k},${y + 5 * k} L${x + sx * 2.8 * k},${y + 4.2 * k}Z`, dark, line, 0.55)
  for (const sx of [-1, 1]) { ink(g, loop(sx), color, line, 0.6); stroke(g, `M${x + sx * 1.4 * k},${y} L${x + sx * 4 * k},${y - 0.3 * k}`, dark, 0.5) }
  ink(g, ellipse(x, y, 1.3 * k, 1.5 * k), dark, line, 0.55)
}
function starPath(x: number, y: number, r: number, inner = 0.45, points = 5, rot = -Math.PI / 2): string {
  const pts: string[] = []
  for (let i = 0; i < points * 2; i++) {
    const a = rot + i * Math.PI / points, rr = i % 2 ? r * inner : r
    pts.push(n2(x + Math.cos(a) * rr) + ',' + n2(y + Math.sin(a) * rr))
  }
  return 'M' + pts.join(' L') + 'Z'
}
function paintGlasses(g: G, eyes: readonly Eye[], side: boolean, color: string) {
  for (const e of eyes) {
    const lens = ellipse(e.x, e.y + 0.3, side ? 3.6 : 5.6, side ? 5.4 : 5.2)
    g.save(); g.globalAlpha = 0.14; ink(g, lens, '#ffffff', null); g.restore()
    ink(g, lens, null, color, 0.8)
    stroke(g, `M${e.x - (side ? 1.2 : 2.6)},${e.y - 2.6} L${e.x - (side ? 0.2 : 1.2)},${e.y - 3.6}`, '#ffffff', 0.6, 0.8)
  }
  if (!side) stroke(g, `M${eyes[0].x + 5.4},${eyes[0].y - 0.8} Q0,${eyes[0].y - 2.4} ${eyes[1].x - 5.4},${eyes[1].y - 0.8}`, color, 0.8)
  else stroke(g, `M${eyes[0].x - 3.6},${eyes[0].y - 0.6} L${eyes[0].x - 14},${eyes[0].y - 2.4}`, color, 0.8)
}

// ---------- animal ears and tails ----------
/** Cat ear in its own frame: root at 0,0, pointing up (-y), 13 units long. */
function paintCatEar(g: G, s: Style, inner: string) {
  g.scale(1.12, 1.12)
  const outer = 'M-5.8,1.5 C-5.4,-4.5 -3.4,-9.6 -0.6,-13 C1.8,-9.4 5,-4.6 5.8,1.5Z'
  ink(g, outer, s.hair[0], s.outline, 0.7)
  ink(g, 'M-3.5,0.5 C-3.2,-3.4 -2,-7 -0.6,-9.4 C0.9,-6.8 2.8,-3.6 3.5,0.5Z', inner, null)
  stroke(g, 'M-1.4,-1 L-0.6,-5.4 M0.8,-1.2 L0.2,-4.6', mix(inner, '#ffffff', 0.5), 0.45, 0.8)
  within(g, outer, 'M-6,1.5 C-5.6,-4 -4,-8 -0.6,-13 L-2.2,1.5Z', s.hairShade, 0.5)
}
/** Dog ear in its own frame: root at 0,0, hanging down (+y), about 19 units long. */
function paintDogEar(g: G, s: Style) {
  const outer = 'M-3.8,-1.5 C-6.8,2.5 -8,11 -6.2,17 C-4.8,20.4 -0.4,21 1.4,17.8 C3.6,12.2 3.8,4 3.8,-1.5Z'
  g.scale(1.15, 1.15)
  // A shade darker than the hair so the ear reads against it, with a soft lighter inner flap.
  const fill = mix(mix(s.hair[0], s.hair[1], 0.2), s.hairShade, 0.4)
  ink(g, outer, fill, s.outline, 0.8)
  within(g, outer, 'M-4.8,4 C-5.6,9 -5,14 -3,17 C-1.6,15 -1.2,9 -1.6,4Z', mix(fill, s.earInner, 0.55), 0.85)
  within(g, outer, 'M-8,8 C-4,10 0,10 4,8 V22 H-8Z', mix(fill, s.hairShade, 0.45))
  within(g, outer, 'M1,-2 C2,6 1.5,13 -0.5,20 L4,20 L4,-2Z', s.hairShade, 0.35)
  stroke(g, 'M-3.6,3 C-4.6,7 -4.6,11 -3.6,14', '#ffffff', 0.6, 0.35)
}
function placed(g: G, root: Pt, tip: Pt, up: boolean, draw: () => void) {
  const dx = tip[0] - root[0], dy = tip[1] - root[1]
  g.save(); g.translate(root[0], root[1])
  g.rotate(up ? Math.atan2(dx, -dy) : Math.atan2(-dx, dy))
  draw(); g.restore()
}
function paintTail(g: G, s: Style, spine: readonly Pt[], dog: boolean) {
  if (dog) {
    const w = (u: number) => 5.2 - u * 0.6 + Math.sin(u * Math.PI) * 1.4
    const o = smooth(lock(spine, w, {tip: 'round', wave: 0.12}))
    const grad = g.createLinearGradient(spine[0][0], spine[0][1], spine[spine.length - 1][0], spine[spine.length - 1][1])
    grad.addColorStop(0, mix(s.hair[0], s.hair[1], 0.25)); grad.addColorStop(0.75, mix(s.hair[0], s.hair[1], 0.5)); grad.addColorStop(1, mix(s.hair[1], '#ffffff', 0.5))
    ink(g, o, grad, s.outline, 0.7)
    stroke(g, smooth(spline(spine, 3).slice(1, -1).map(([x, y]) => [x + 0.9, y] as Pt), false), s.hairShade, 0.55, 0.5)
    return
  }
  const w = (u: number) => 3.9 - u * 1.1
  const o = smooth(lock(spine, w, {tip: 'round'}))
  const grad = g.createLinearGradient(spine[0][0], spine[0][1], spine[spine.length - 1][0], spine[spine.length - 1][1])
  grad.addColorStop(0, s.hair[0]); grad.addColorStop(0.6, s.hair[0]); grad.addColorStop(1, s.hair[1])
  ink(g, o, grad, s.outline, 0.7)
  stroke(g, smooth(spline(spine, 3).slice(1, -1).map(([x, y]) => [x - 0.7, y - 0.4] as Pt), false), '#ffffff', 0.5, 0.25)
}

// ---------- clothing ----------
function paintArm(g: G, s: Style, joints: readonly Pt[], k = 1) {
  const puff = s.id === 'star' ? 1.25 : 1
  const w = (u: number) => (u < 0.18 ? 5.2 * puff - u * 3 : 4.7 - u * 0.9) * k
  const o = smooth(lock(joints, w, {tip: 'round', lead: 1.5}))
  ink(g, o, s.top, s.outline, 0.7)
  const sp = spline(joints, 5)
  const shadeSide = sp.map(([x, y], i) => [x + 1.2, y + (i === 0 ? 0 : 0)] as Pt)
  within(g, o, smooth([...shadeSide, [shadeSide[shadeSide.length - 1][0] + 4, shadeSide[shadeSide.length - 1][1]], [shadeSide[0][0] + 4, shadeSide[0][1]]]), s.topShade, 0.85)
  // Cuff at the wrist.
  const [a, b] = [sp[sp.length - 4], sp[sp.length - 1]]
  const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1
  const nx = -dy / l, ny = dx / l, cw = 2.5 * k
  const c0: Pt = [a[0] + dx * 0.25, a[1] + dy * 0.25]
  within(g, o, `M${c0[0] + nx * cw * 1.4},${c0[1] + ny * cw * 1.4} L${c0[0] - nx * cw * 1.4},${c0[1] - ny * cw * 1.4} L${b[0] - nx * cw * 1.6 + dx},${b[1] - ny * cw * 1.6 + dy} L${b[0] + nx * cw * 1.6 + dx},${b[1] + ny * cw * 1.6 + dy}Z`, s.cuff)
  stroke(g, `M${c0[0] + nx * cw},${c0[1] + ny * cw} L${c0[0] - nx * cw},${c0[1] - ny * cw}`, s.outline, 0.5, 0.8)
}
function paintHand(g: G, s: Style, x: number, y: number, thumb: number, kind: 'open' | 'fist') {
  const r = kind === 'fist' ? 2.3 : 2.4
  const d = kind === 'open'
    ? `M${x - r},${y - 0.6} C${x - r},${y - 2.8} ${x + r},${y - 2.8} ${x + r},${y - 0.6} C${x + r * 1.05},${y + 2.2} ${x + 0.6},${y + 3.6} ${x},${y + 3.6} C${x - 0.6},${y + 3.6} ${x - r * 1.05},${y + 2.2} ${x - r},${y - 0.6}Z`
    : `M${x - r},${y} C${x - r},${y - 2.6} ${x + r},${y - 2.6} ${x + r},${y} C${x + r},${y + 2.6} ${x - r},${y + 2.6} ${x - r},${y}Z`
  ink(g, d, s.skin, s.outline, 0.6)
  ink(g, ellipse(x + thumb * r * 0.95, y - 0.2, 1, 1.4, thumb * 0.5), s.skin, s.outline, 0.5)
  if (kind === 'open') stroke(g, `M${x - 0.8},${y + 1.4} L${x - 0.8},${y + 2.8} M${x + 0.6},${y + 1.4} L${x + 0.6},${y + 2.8}`, s.skinShade, 0.4)
}
function paintLeg(g: G, s: Style, joints: readonly Pt[], wTop: number, wEnd: number) {
  const w = (u: number) => wTop + (wEnd - wTop) * u - Math.sin(u * Math.PI * 2) * 0.25
  const o = smooth(lock(joints, w, {tip: 'flat', lead: 0}))
  ink(g, o, s.legs, s.outline, 0.65)
  const sp = spline(joints, 5)
  within(g, o, smooth([...sp.map(([x, y]) => [x + wTop * 0.22, y] as Pt), [sp[sp.length - 1][0] + 5, sp[sp.length - 1][1]], [sp[0][0] + 5, sp[0][1]]]), mix(s.legs, '#000000', 0.15), 0.9)
  if (s.legs !== s.skin) stroke(g, smooth(sp.slice(2, -3).map(([x, y]) => [x - wTop * 0.25, y] as Pt), false), '#ffffff', 0.5, 0.25)
}
function paintBootFront(g: G, s: Style, x: number) {
  const d = `M${x - 3.4},-9.6 L${x + 3.4},-9.6 L${x + 3.6},-2.8 Q${x + 4.4},0.4 ${x},0.4 Q${x - 4.4},0.4 ${x - 3.6},-2.8Z`
  ink(g, d, s.boots, s.outline, 0.7)
  within(g, d, `M${x + 1.2},-10 L${x + 5},-10 L${x + 5},1 L${x + 1.6},1Z`, mix(s.boots, '#000000', 0.2))
  ink(g, `M${x - 3.9},-10.4 L${x + 3.9},-10.4 L${x + 3.7},-8 L${x - 3.7},-8Z`, mix(s.boots, '#ffffff', 0.18), s.outline, 0.6)
  stroke(g, `M${x - 3.6},-0.8 Q${x},0.2 ${x + 3.6},-0.8`, mix(s.boots, '#000000', 0.5), 0.6)
  if (s.id === 'star') ink(g, starPath(x, -5.5, 1.5), s.bow, null)
  else stroke(g, `M${x - 1.6},-6.2 L${x + 1.6},-6.2`, '#ffffff', 0.5, 0.35)
}
function paintBootSide(g: G, s: Style, x: number) {
  const d = `M${x - 2.8},-9.6 L${x + 2.6},-9.6 L${x + 2.9},-3.6 Q${x + 6.6},-3.2 ${x + 6.8},-0.9 Q${x + 6.9},0.4 ${x + 5.2},0.4 L${x - 2.8},0.4 Q${x - 3.6},0.4 ${x - 3.4},-1.6Z`
  ink(g, d, s.boots, s.outline, 0.7)
  within(g, d, `M${x - 4},-3 L${x + 8},-3 L${x + 8},1 L${x - 4},1Z`, mix(s.boots, '#000000', 0.25))
  ink(g, `M${x - 3.3},-10.4 L${x + 3.1},-10.4 L${x + 2.9},-8 L${x - 3.1},-8Z`, mix(s.boots, '#ffffff', 0.18), s.outline, 0.6)
  stroke(g, `M${x - 3.2},-0.6 L${x + 6.2},-0.6`, mix(s.boots, '#000000', 0.5), 0.6)
  if (s.id === 'star') ink(g, starPath(x + 0.2, -5.6, 1.4), s.bow, null)
}

function paintSkirtFront(g: G, s: Style) {
  const hem = s.id === 'star' ? 13.2 : 14.6
  const d = `M-7.2,-30.5 L7.2,-30.5 L${hem},-18.6 Q0,-15.8 ${-hem},-18.6Z`
  ink(g, d, s.skirt, s.outline, 0.7)
  for (let i = -3; i <= 3; i++) {
    const x0 = i * 2.1, x1 = i * hem / 3.4
    if (i % 2) within(g, d, `M${x0},-30.5 L${x0 + 2.1},-30.5 L${x1 + hem / 3.4},-16 L${x1},-16Z`, s.skirtShade, 0.55)
    stroke(g, `M${x0},-29 L${x1},-17.4`, mix(s.skirtShade, s.outline, 0.4), 0.45, 0.7)
  }
  if (s.id === 'star') {
    ink(g, `M${-hem - 0.6},-18.9 Q0,-16 ${hem + 0.6},-18.9 L${hem + 1.4},-16.6 Q0,-13.4 ${-hem - 1.4},-16.6Z`, s.bow, s.outline, 0.6)
    for (const x of [-7, 0, 7]) ink(g, starPath(x, -23 + Math.abs(x) * 0.08, 1.3), s.bow, null)
  }
  if (s.id === 'astra') for (const [x, y] of [[-8, -21], [3, -24], [9, -20]]) ink(g, starPath(x, y, 1, 0.4, 4), '#d9c6ff', null)
  ink(g, 'M-7.6,-31.2 L7.6,-31.2 L7.4,-28.6 L-7.4,-28.6Z', s.id === 'gemini' ? '#ffffff' : s.id === 'ember' ? '#3e2318' : s.skirtShade, s.outline, 0.55)
}
function paintSkirtSide(g: G, s: Style) {
  const d = 'M-5.8,-30.5 L5.8,-30.5 L11.6,-18.4 Q0,-16.2 -12.8,-18.6Z'
  ink(g, d, s.skirt, s.outline, 0.7)
  for (let i = -2; i <= 2; i++) {
    if (i % 2) within(g, d, `M${i * 2.2},-30.5 L${i * 2.2 + 2.2},-30.5 L${i * 5 + 5},-16 L${i * 5},-16Z`, s.skirtShade, 0.55)
    stroke(g, `M${i * 2.2},-29 L${i * 4.8},-17.2`, mix(s.skirtShade, s.outline, 0.4), 0.45, 0.7)
  }
  if (s.id === 'star') ink(g, 'M-13.4,-18.9 Q0,-16.4 12.2,-18.7 L13,-16.5 Q0,-13.8 -14.2,-16.6Z', s.bow, s.outline, 0.6)
  ink(g, 'M-6.2,-31.2 L6.2,-31.2 L6,-28.6 L-6,-28.6Z', s.id === 'gemini' ? '#ffffff' : s.id === 'ember' ? '#3e2318' : s.skirtShade, s.outline, 0.55)
}
function paintTorso(g: G, s: Style, side: boolean) {
  const d = side
    ? 'M-5,-42.4 C-6.2,-38 -5.6,-32 -5.2,-27 L-5.4,-24 L5.2,-24 L5.4,-27 C6.4,-31 6.8,-36.5 5.2,-42.4 C2,-43.8 -2,-43.8 -5,-42.4Z'
    : 'M-7.6,-42 C-9.6,-41.4 -9.2,-38 -8.6,-36 L-7,-27 L-7.2,-24 L7.2,-24 L7,-27 L8.6,-36 C9.2,-38 9.6,-41.4 7.6,-42 C4,-43.2 -4,-43.2 -7.6,-42Z'
  ink(g, d, s.top, s.outline, 0.7)
  within(g, d, side ? 'M-6,-44 L-1,-44 L-2,-24 L-6,-24Z' : 'M3.5,-44 L10,-44 L10,-24 L4.5,-24Z', s.topShade, 0.8)
  if (s.id === 'ember') ink(g, side ? 'M-5.4,-33 L5.8,-33 L5.4,-27 L-5.2,-27Z' : 'M-7.6,-33 L7.6,-33 L7,-27 L-7,-27Z', '#4a2a1c', s.outline, 0.55)
  if (s.id === 'star' && !side) ink(g, 'M-4.5,-42.6 L0,-38.6 L4.5,-42.6 Q0,-43.6 -4.5,-42.6Z', '#f7f1e6', s.outline, 0.5)
}
function paintNeck(g: G, s: Style, x: number) {
  const d = `M${x - 3.1},-53 L${x + 3.1},-53 L${x + 3.3},-39.5 L${x - 3.3},-39.5Z`
  ink(g, d, s.skin, s.outline, 0.6)
  within(g, d, `M${x - 4},-54 L${x + 4},-54 L${x + 4},-45 Q${x},-43 ${x - 4},-45Z`, s.skinShade)
}
function paintCape(g: G, s: Style, side: boolean) {
  const c = s.cape
  if (!c) return
  const d = side
    ? 'M-6.8,-43.4 C-10,-40.5 -11.6,-36.4 -12.4,-31.8 Q-6,-30 0,-31.2 Q6,-30.2 11.2,-32.2 C10.2,-37 8.2,-41.2 5.2,-43.4 C1.2,-44.9 -3.8,-44.9 -6.8,-43.4Z'
    : 'M-10,-42.4 C-12.2,-40.4 -13.4,-36.4 -14,-31.8 Q-7,-29.2 -0.8,-32.6 L0,-31 L0.8,-32.6 Q7,-29.2 14,-31.8 C13.4,-36.4 12.2,-40.4 10,-42.4 C6,-44.8 -6,-44.8 -10,-42.4Z'
  ink(g, d, c.color, s.outline, 0.75)
  within(g, d, side ? 'M-14,-38 Q-6,-34 0,-36 L0,-28 L-14,-28Z' : 'M-15,-37 Q-7,-33.4 0,-36 Q7,-33.4 15,-37 V-28 H-15Z', c.shade, 0.75)
  const trim = side ? 'M-11.2,-33.2 Q-6,-31.6 0,-32.6 Q6,-31.7 10.2,-33.4' : 'M-12.8,-33.2 Q-7,-30.9 -1.2,-33.8 M1.2,-33.8 Q7,-30.9 12.8,-33.2'
  stroke(g, trim, c.trim, 0.65)
  if (!side) stroke(g, 'M0,-41 L0,-31.6', mix(c.shade, s.outline, 0.4), 0.5)
  if (s.id === 'astra') for (const [x, y] of side ? [[-8, -36], [4, -37.5]] : [[-10, -35], [-5, -39], [6, -38.5], [10.5, -34.5]]) ink(g, starPath(x, y, 1.1, 0.4, 4), '#d9c6ff', null)
}

// ---------- props and particles ----------
const WOOD = {top: '#d8a066', face: '#b77a45', line: '#5a3420'}
/** How far below its drawing the desk set sits (seated lap height). */
const DESK = 6.5
function paintCushion(g: G, s: Style) {
  const d = 'M-17,-2.2 C-18.5,-7.4 -10,-9.6 0,-9.6 C10,-9.6 18.5,-7.4 17,-2.2 C15.6,1.4 -15.6,1.4 -17,-2.2Z'
  ink(g, d, s.cushion, s.outline, 0.7)
  within(g, d, 'M-20,-3.6 Q0,-1 20,-3.6 V3 H-20Z', mix(s.cushion, '#000000', 0.22))
  stroke(g, 'M-12,-6.8 Q0,-8.6 12,-6.8', '#ffffff', 0.6, 0.35)
  for (const x of [-16.6, 16.6]) ink(g, ellipse(x, -2.4, 1.1, 1.1), mix(s.cushion, '#ffffff', 0.4), s.outline, 0.5)
}
function paintDesk(g: G) {
  ink(g, `M-20.5,-16 L-17.5,-16 L-17.8,${-DESK} L-20.6,${-DESK}Z M17.5,-16 L20.5,-16 L20.6,${-DESK} L17.8,${-DESK}Z`, WOOD.face, WOOD.line, 0.65)
  ink(g, 'M-23,-18.4 L23,-18.4 L23,-15.6 L-23,-15.6Z', WOOD.face, WOOD.line, 0.65)
  ink(g, 'M-21.6,-22 L21.6,-22 L24.2,-18.2 L-24.2,-18.2Z', WOOD.top, WOOD.line, 0.7)
  stroke(g, 'M-18,-20.6 L-4,-20.6 M6,-19.4 L19,-19.4', '#ffffff', 0.5, 0.35)
}
function paintBook(g: G) {
  ink(g, 'M-10,-20.6 L10,-20.6 L9.4,-27.6 L-9.4,-27.6Z', '#8c2f3a', WOOD.line, 0.6)
  ink(g, 'M-9,-21.4 L-0.4,-21.9 L-0.2,-27.9 L-8.4,-27.4Z', '#fffaf0', WOOD.line, 0.5)
  ink(g, 'M9,-21.4 L0.4,-21.9 L0.2,-27.9 L8.4,-27.4Z', '#fffaf0', WOOD.line, 0.5)
  for (let i = 0; i < 4; i++) stroke(g, `M-7.4,${-26 + i * 1.2} L-1.6,${-26.3 + i * 1.2} M1.6,${-26.3 + i * 1.2} L7.4,${-26 + i * 1.2}`, '#b9a98e', 0.35)
}
function paintPage(g: G) {
  ink(g, 'M0.3,-21.9 L8.6,-21.5 L8.2,-27.5 L0.2,-27.9Z', '#ffffff', WOOD.line, 0.45)
  for (let i = 0; i < 3; i++) stroke(g, `M1.8,${-26 + i * 1.3} L7.2,${-25.8 + i * 1.3}`, '#c9bba2', 0.35)
}
function paintLaptop(g: G) {
  ink(g, 'M-10.4,-19.6 L10.4,-19.6 L9.4,-21.4 L-9.4,-21.4Z', '#9aa3b2', '#3a3f4c', 0.6)
  ink(g, 'M-8.8,-21.2 L8.8,-21.2 L8.2,-33.2 L-8.2,-33.2Z', '#d5dae3', '#3a3f4c', 0.7)
  within(g, 'M-8.8,-21.2 L8.8,-21.2 L8.2,-33.2 L-8.2,-33.2Z', 'M2,-34 L10,-34 L10,-20 L4,-20Z', '#b9c0cc', 0.8)
  ink(g, starPath(0, -27.4, 2.2), '#f2c043', '#3a3f4c', 0.45)
}
function paintGlow(g: G) {
  const grad = g.createRadialGradient(0, -33, 1, 0, -33, 13)
  grad.addColorStop(0, 'rgba(160,220,255,0.85)'); grad.addColorStop(1, 'rgba(160,220,255,0)')
  g.fillStyle = grad; g.fillRect(-14, -46, 28, 24)
}
function paintNotebook(g: G) {
  ink(g, 'M-8,-20.8 L5.4,-20.8 L7,-25.6 L-6.4,-25.6Z', '#fffdf6', '#4a3b5a', 0.55)
  for (let i = 0; i < 3; i++) stroke(g, `M${-5.6 + i * 0.4},${-22 - i * 1.2} L${4.8 + i * 0.4},${-22 - i * 1.2}`, '#9fc0e6', 0.35)
  stroke(g, 'M-7.2,-21.2 L-5.8,-25.2', '#4a3b5a', 0.6)
}
function paintPencil(g: G, x: number, y: number) {
  g.save(); g.translate(x, y); g.rotate(0.6)
  ink(g, 'M-0.8,-6 L0.8,-6 L0.8,3.2 L0,5 L-0.8,3.2Z', '#f2c043', '#5a3420', 0.45)
  ink(g, 'M-0.8,-7.4 L0.8,-7.4 L0.8,-6 L-0.8,-6Z', '#f49ab0', '#5a3420', 0.4)
  ink(g, 'M-0.5,3.6 L0.5,3.6 L0,5 Z', '#3a2a2a', null)
  g.restore()
}

export type FxName = 'heart' | 'sparkle' | 'zzz' | 'sweat' | 'bang' | 'question' | 'note' | 'dust' | 'smoke' | 'twinkle'
export const FX: readonly FxName[] = ['heart', 'sparkle', 'zzz', 'sweat', 'bang', 'question', 'note', 'dust', 'smoke', 'twinkle']
const FX_LINE = '#4a2f3e'
/** Particles in the same line style, each drawn in a 12 x 12 box centred on 0,0. */
export function paintFx(g: G, name: FxName) {
  switch (name) {
    case 'heart': {
      const d = 'M0,4.6 C-5.6,1 -5.8,-3.6 -3,-4.4 C-1.4,-4.8 -0.3,-3.8 0,-2.6 C0.3,-3.8 1.4,-4.8 3,-4.4 C5.8,-3.6 5.6,1 0,4.6Z'
      ink(g, d, '#ff6f91', FX_LINE, 0.7); stroke(g, 'M-3,-2.8 Q-3.4,-1 -2.2,0.4', '#ffffff', 0.7, 0.7); break
    }
    case 'sparkle': ink(g, 'M0,-5.4 Q0.9,-0.9 5.4,0 Q0.9,0.9 0,5.4 Q-0.9,0.9 -5.4,0 Q-0.9,-0.9 0,-5.4Z', '#ffe27a', FX_LINE, 0.6); ink(g, ellipse(0, 0, 1, 1), '#ffffff', null); break
    case 'twinkle': ink(g, 'M0,-4 Q0.6,-0.6 4,0 Q0.6,0.6 0,4 Q-0.6,0.6 -4,0 Q-0.6,-0.6 0,-4Z', '#ffffff', '#9fd6ff', 0.6); break
    case 'zzz': ink(g, 'M-3.4,-3.8 L3.6,-3.8 L3.6,-2.2 L-0.8,2.4 L3.8,2.4 L3.8,4 L-3.8,4 L-3.8,2.4 L0.6,-2.2 L-3.4,-2.2Z', '#cfe3ff', FX_LINE, 0.6); break
    case 'sweat': ink(g, 'M0,-4.8 C1.8,-1.6 3.4,0.6 3.4,2.2 C3.4,4.2 1.8,5.2 0,5.2 C-1.8,5.2 -3.4,4.2 -3.4,2.2 C-3.4,0.6 -1.8,-1.6 0,-4.8Z', '#9fdcff', FX_LINE, 0.6); stroke(g, 'M-1.6,1.4 Q-1.8,3 -0.6,3.8', '#ffffff', 0.6, 0.8); break
    case 'bang': ink(g, 'M-1.6,-5.2 L1.6,-5.2 L0.9,1.4 L-0.9,1.4Z', '#ff8a5c', FX_LINE, 0.6); ink(g, ellipse(0, 3.8, 1.3, 1.3), '#ff8a5c', FX_LINE, 0.6); break
    case 'question': stroke(g, 'M-2.6,-2.6 C-2.6,-5.6 2.8,-5.6 2.8,-2.6 C2.8,-0.6 0,-0.4 0,1.6', FX_LINE, 2.6); stroke(g, 'M-2.6,-2.6 C-2.6,-5.6 2.8,-5.6 2.8,-2.6 C2.8,-0.6 0,-0.4 0,1.6', '#8fd0ff', 1.4); ink(g, ellipse(0, 4.2, 1.2, 1.2), '#8fd0ff', FX_LINE, 0.6); break
    case 'note': ink(g, 'M-1,-4.6 L4,-5.6 L4,2 M-1,-4.6 L-1,3.2', null, FX_LINE, 0.9); ink(g, ellipse(-2.4, 3.2, 1.7, 1.3, -0.4), '#ffd06a', FX_LINE, 0.6); ink(g, ellipse(2.6, 2.1, 1.7, 1.3, -0.4), '#ffd06a', FX_LINE, 0.6); break
    case 'dust': ink(g, 'M-4,2 C-5.4,2 -5.4,-0.6 -3.6,-0.8 C-3.6,-3 -0.6,-3.6 0.4,-1.8 C1.6,-3.2 4.6,-2.2 4,0.2 C5.4,0.6 5,2.4 3.6,2.4Z', '#efe6dc', '#8d7f74', 0.5); break
    case 'smoke': {
      const d = 'M-4.6,3.6 C-6.6,3.6 -6.8,0.4 -4.8,-0.2 C-5.2,-3.4 -1.6,-4.8 0,-2.8 C1.2,-5.2 5.2,-4.4 4.8,-1.2 C6.8,-0.8 6.6,3.6 4.4,3.6Z'
      ink(g, d, '#ffffff', '#b9a7c9', 0.6); within(g, d, 'M-7,1.6 Q0,3.2 7,1.6 V5 H-7Z', '#ece4f6'); break
    }
  }
}

// ---------- the views ----------
const CUSHION_BOX: [number, number, number, number] = [-20, -12, 20, 3]

export function viewDef(id: CastId, view: View): ViewDef {
  return view === 'front' ? frontDef(STYLES[id]) : sideDef(STYLES[id])
}

/** Hair layout per style, front view (F = screen left, K = screen right). */
function frontHair(s: Style) {
  const v = s.volume
  if (s.hairStyle === 'long') return {
    strands: [
      [[-19 * v, -70], [-23 * v, -53], [-25 * v, -37], [-25.5 * v, -22]],
      [[-11, -68], [-14.5 * v, -52], [-16 * v, -37], [-15.5 * v, -24]],
    ] as Pt[][],
    widths: [13 * v, 14 * v],
    lock: [[-20.5, -78], [-21.8, -64], [-22.2, -52], [-21.5, -41]] as Pt[],
    back: 'M-25,-62 C-27.5,-93 -14,-104.5 0,-104.5 C14,-104.5 27.5,-93 25,-62 L22.5,-48 L-22.5,-48Z',
  }
  if (s.hairStyle === 'bob') return {
    strands: [
      [[-15, -66], [-17.5, -56], [-18.5, -46]],
      [[-6, -66], [-6.8, -55], [-7, -45]],
    ] as Pt[][],
    widths: [11, 11],
    lock: [[-20, -77], [-21.4, -65], [-21, -50]] as Pt[],
    back: 'M-25,-62 C-27,-93 -14,-104 0,-104 C14,-104 27,-93 25,-62 L22,-52 L-22,-52Z',
  }
  return {
    strands: [] as Pt[][],
    widths: [] as number[],
    lock: [[-19.5, -76], [-20.4, -67], [-20, -58]] as Pt[],
    back: 'M-24.5,-63 C-26.5,-93 -14,-103.5 0,-103.5 C14,-103.5 26.5,-93 24.5,-63 L21,-55 L-21,-55Z',
  }
}

function crownFront(s: Style): Pt[] {
  // Outer silhouette then the bangs' tips right to left (each tip doubled to stay sharp).
  const tips: Pt[] = s.hairStyle === 'bob'
    ? [[23.5, -58], [17.5, -73], [14.5, -63], [14.5, -63], [10, -76], [5.5, -64.5], [5.5, -64.5], [1.5, -77], [-3, -65.5], [-3, -65.5], [-7, -76.5], [-11.5, -63.5], [-11.5, -63.5], [-15.5, -73], [-21, -59], [-21, -59]]
    : [[23.5, -58], [18.5, -71], [15, -63.5], [15, -63.5], [12, -75], [9, -67.5], [9, -67.5], [6, -77], [2.5, -66], [2.5, -66], [0, -76], [-3, -66.5], [-3, -66.5], [-6, -77], [-9, -67.5], [-9, -67.5], [-12, -75], [-15, -63.5], [-15, -63.5], [-18.5, -71], [-21, -58], [-21, -58]]
  return [[-24.5, -66], [-26, -86], [-16, -101.5], [0, -103], [16, -101.5], [26, -86], [24.5, -66], [23.6, -60.5], ...tips, [-23.8, -64]]
}

function frontDef(s: Style): ViewDef {
  const H = frontHair(s)
  const cat = s.catByNature
  const bones: BoneDef[] = [
    {name: 'root', parent: null, at: [0, 0]},
    {name: 'prop', parent: 'root', at: [0, 0]},
    {name: 'page', parent: 'prop', at: [0.2, -24.5 + DESK]},
    {name: 'hips', parent: 'root', at: [0, -27]},
    {name: 'chest', parent: 'hips', at: [0, -31]},
    {name: 'neck', parent: 'chest', at: [0, -41]},
    {name: 'head', parent: 'neck', at: [0, -46]},
    {name: 'browF', parent: 'head', at: [-9.5, -72]},
    {name: 'browK', parent: 'head', at: [9.5, -72]},
    {name: 'pupilF', parent: 'head', at: [-9.5, -61]},
    {name: 'pupilK', parent: 'head', at: [9.5, -61]},
    {name: 'mouth', parent: 'head', at: [0, -52]},
    {name: 'bangs', parent: 'head', at: [0, -82]},
    {name: 'armUF', parent: 'chest', at: [-8, -40]},
    {name: 'armLF', parent: 'armUF', at: [-10.4, -32.6]},
    {name: 'handF', parent: 'armLF', at: [-11.8, -26]},
    {name: 'armUK', parent: 'chest', at: [8, -40]},
    {name: 'armLK', parent: 'armUK', at: [10.4, -32.6]},
    {name: 'handK', parent: 'armLK', at: [11.8, -26]},
    {name: 'thighF', parent: 'hips', at: [-3.8, -23]},
    {name: 'shinF', parent: 'thighF', at: [-3.9, -12.5]},
    {name: 'footF', parent: 'shinF', at: [-3.9, -4]},
    {name: 'thighK', parent: 'hips', at: [3.8, -23]},
    {name: 'shinK', parent: 'thighK', at: [3.9, -12.5]},
    {name: 'footK', parent: 'shinK', at: [3.9, -4]},
  ]
  const chains: ChainDef[] = []
  const parts: PartDef[] = []
  const slots: SlotDef[] = []
  const slot = (name: string, bone: string, attachment: string | null = name, extra: Partial<SlotDef> = {}) => slots.push({name, bone, attachment, ...extra})
  const chain = (base: string, parent: string, joints: Pt[], feel: ChainFeel) => {
    bones.push(...chainBones(base, parent, joints))
    chains.push({name: base, bones: names(base, joints), tip: joints[joints.length - 1], feel})
    return names(base, joints)
  }

  // Skirt and cape chains, tails, ears (bones first so slots can point at them).
  const skirt = chain('skirt', 'hips', [[0, -29], [0, -23.5], [0, -18]], FEEL.skirt)
  const cape = s.cape ? chain('cape', 'chest', [[0, -40], [0, -35.5], [0, -31]], FEEL.cape) : []
  const catTailJ: Pt[] = [[4, -24], [12, -20.5], [20, -21.5], [26, -27.5], [28.5, -36], [26.5, -44]]
  const dogTailJ: Pt[] = [[4, -24], [11, -24.5], [16, -29.5], [17, -35.5]]
  const tailCat = chain('tailCat', 'hips', catTailJ, FEEL.catTail)
  const tailDog = chain('tailDog', 'hips', dogTailJ, FEEL.dogTail)
  const catEar = (sx: 1 | -1): Pt[] => [[-14 * sx, -92.5], [-16.6 * sx, -99.6], [-19 * sx, -106.8]]
  const dogEar = (sx: 1 | -1): Pt[] => [[-19 * sx, -86], [-23 * sx, -76], [-25.4 * sx, -65]]
  const catF = chain('catF', 'head', catEar(1), FEEL.catEar), catK = chain('catK', 'head', catEar(-1), FEEL.catEar)
  const dogF = chain('dogF', 'head', dogEar(1), FEEL.dogEar), dogK = chain('dogK', 'head', dogEar(-1), FEEL.dogEar)
  chains.push({name: 'bangs', bones: ['bangs'], tip: [0, -64], feel: FEEL.bangs(s)})

  // Hair strands behind (mirrored pairs) and the side locks.
  const strandChains: {bones: string[]; joints: Pt[]; w: number}[] = []
  H.strands.forEach((j, i) => {
    for (const sx of [1, -1] as const) {
      const joints = sx > 0 ? j : mirror(j)
      const b = chain(`hair${i}${sx > 0 ? 'F' : 'K'}`, 'head', joints, FEEL.hair(s))
      strandChains.push({bones: b, joints, w: H.widths[i]})
    }
  })
  const lockF = chain('lockF', 'head', H.lock, FEEL.lockSide(s)), lockK = chain('lockK', 'head', mirror(H.lock), FEEL.lockSide(s))
  const pigJ: Pt[] = [[-21, -66], [-25, -54], [-27.6, -42], [-27, -29]]
  const pigF = s.hairStyle === 'twin' ? chain('pigF', 'head', pigJ, FEEL.pigtail(s)) : []
  const pigK = s.hairStyle === 'twin' ? chain('pigK', 'head', mirror(pigJ), FEEL.pigtail(s)) : []
  bones.push({name: 'pencil', parent: 'handK', at: [11.8, -24]})

  const part = (p: PartDef) => parts.push(p)
  const rigid = (slotName: string, name: string, bone: string, b: [number, number, number, number], paint: (g: G) => void) =>
    part({slot: slotName, name, bones: [bone], box: b, paint})

  // --- draw order, back to front ---
  slot('cushion', 'prop', null); rigid('cushion', 'cushion', 'prop', CUSHION_BOX, g => paintCushion(g, s))
  // Back hair.
  if (pigF.length) {
    for (const [name, b, j] of [['pigK', pigK, mirror(pigJ)], ['pigF', pigF, pigJ]] as const) {
      slot(name, b[0]); part({slot: name, name, bones: b, joints: j, box: box(j, 9), grid: [3, 10], paint: g => paintLock(g, s, j, u => 8 + Math.sin(u * Math.PI) * 5 - u * 2, {wave: 0.1, curl: j[0][0] < 0 ? 1.5 : -1.5})})
    }
  }
  if (s.hairStyle === 'long') {
    const v = s.volume
    const cj: Pt[] = [[0, -70], [0, -56], [0, -42], [0, -26]]
    const curtain = chain('hairC', 'head', cj, FEEL.hair(s))
    const outline = smooth([[-22 * v, -74], [-25 * v, -60], [-27 * v, -46], [-27.5 * v, -33], [-26 * v, -24], [-22 * v, -21], [-22 * v, -21], [-17 * v, -25], [-11, -22], [-11, -22], [-5, -26], [0, -23], [0, -23], [5, -26], [11, -22], [11, -22], [17 * v, -25], [22 * v, -21], [22 * v, -21], [26 * v, -24], [27.5 * v, -33], [27 * v, -46], [25 * v, -60], [22 * v, -74]])
    slot('hairCurtain', curtain[0])
    part({slot: 'hairCurtain', name: 'hairCurtain', bones: ['head', ...curtain], joints: [[0, -84], ...cj], box: [-31 * v, -86, 31 * v, -18], grid: [5, 12], paint: g => {
      ink(g, outline, hairFill(g, s), s.outline, 0.7)
      within(g, outline, 'M-40,-80 L40,-80 L40,-15 L-40,-15Z', s.hairShade, 0.28)
      for (const x of [-20, -13, -6, 6, 13, 20]) stroke(g, `M${x * 0.8},-70 Q${x * 1.1},-48 ${x},-27`, s.hairShade, 0.55, 0.45)
    }})
  }
  slot('hairBack', 'head'); rigid('hairBack', 'hairBack', 'head', [-29, -107, 29, -46], g => {
    ink(g, H.back, hairFill(g, s), s.outline, 0.7)
    within(g, H.back, 'M-30,-70 Q0,-60 30,-70 V-40 H-30Z', s.hairShade, 0.35)
  })
  for (const sc of strandChains) {
    const name = sc.bones[0].slice(0, -1)
    slot(name, sc.bones[0])
    part({slot: name, name, bones: sc.bones, joints: sc.joints, box: box(sc.joints, sc.w), grid: [3, 10], paint: g => paintLock(g, s, sc.joints, u => sc.w * (1 - u * 0.25), {wave: s.hairStyle === 'long' ? 0.14 : 0.05, curl: sc.joints[0][0] < 0 ? 1.4 : -1.4})})
  }
  // Tails in front of the back hair, behind the body.
  slot('tailCat', 'tailCat0', cat ? 'tailCat' : null); part({slot: 'tailCat', name: 'tailCat', bones: tailCat, joints: catTailJ, box: box(catTailJ, 4), grid: [3, 14], paint: g => paintTail(g, s, catTailJ, false)})
  slot('tailDog', 'tailDog0', null); part({slot: 'tailDog', name: 'tailDog', bones: tailDog, joints: dogTailJ, box: box(dogTailJ, 5), grid: [3, 8], paint: g => paintTail(g, s, dogTailJ, true)})
  // Animal ears behind the crown (cat), legs, body.
  for (const [name, b, sx] of [['catK', catK, -1], ['catF', catF, 1]] as const) {
    const j = catEar(sx)
    slot(name, b[0], cat ? name : null)
    part({slot: name, name, bones: b, joints: j, box: box(j, 8), grid: [3, 5], paint: g => placed(g, j[0], j[2], true, () => paintCatEar(g, s, s.earInner))})
  }
  for (const [side, x] of [['K', 3.8], ['F', -3.8]] as const) {
    const j: Pt[] = [[x, -25], [x + 0.1 * Math.sign(x), -12.5], [x + 0.1 * Math.sign(x), -4], [x + 0.1 * Math.sign(x), -3]]
    slot('leg' + side, 'thigh' + side)
    part({slot: 'leg' + side, name: 'leg' + side, bones: ['thigh' + side, 'shin' + side, 'foot' + side], joints: j, box: box(j, 4), grid: [3, 10], paint: g => paintLeg(g, s, j.slice(0, 3), 5.4, 4.2)})
    slot('boot' + side, 'foot' + side)
    rigid('boot' + side, 'boot' + side, 'foot' + side, [x - 5.5, -12, x + 5.5, 2], g => paintBootFront(g, s, x + 0.1 * Math.sign(x)))
  }
  slot('neck', 'neck'); rigid('neck', 'neck', 'neck', [-5, -55, 5, -38], g => paintNeck(g, s, 0))
  slot('torso', 'chest')
  part({slot: 'torso', name: 'torso', bones: ['hips', 'chest'], joints: [[0, -22], [0, -31], [0, -44]], box: [-11, -45, 11, -22], grid: [3, 7], paint: g => paintTorso(g, s, false)})
  slot('skirt', 'skirt0')
  part({slot: 'skirt', name: 'skirt', bones: ['hips', ...skirt], joints: [[0, -33], [0, -29], [0, -23.5], [0, -15]], box: [-17, -33, 17, -13], grid: [5, 8], paint: g => paintSkirtFront(g, s)})
  // The desk sits at lap height for the seated pose (everything drawn DESK units lower).
  const low = (paint: (g: G) => void) => (g: G) => { g.translate(0, DESK); paint(g) }
  const lowBox = (b: [number, number, number, number]): [number, number, number, number] => [b[0], b[1] + DESK, b[2], b[3] + DESK]
  slot('desk', 'prop', null); rigid('desk', 'desk', 'prop', lowBox([-26, -24, 26, 1.5 - DESK]), low(paintDesk))
  slot('glow', 'prop', null); rigid('glow', 'glow', 'prop', lowBox([-15, -47, 15, -21]), low(paintGlow))
  slot('deskItem', 'prop', null)
  for (const [name, paint] of [['book', paintBook], ['notebook', paintNotebook]] as const) rigid('deskItem', name, 'prop', lowBox([-12, -30, 12, -18]), low(paint))
  rigid('deskItem', 'laptop', 'prop', lowBox([-12, -35, 12, -18]), low(paintLaptop))
  slot('page', 'page', null); rigid('page', 'page', 'page', lowBox([-1, -29.5, 10, -20]), low(paintPage))
  // Arms over the body; hands; the capelet over the shoulders.
  for (const side of ['K', 'F'] as const) {
    const sx = side === 'F' ? -1 : 1
    const j: Pt[] = [[8 * sx, -40.5], [10.4 * sx, -32.6], [11.8 * sx, -26]]
    slot('arm' + side, 'armU' + side)
    part({slot: 'arm' + side, name: 'arm' + side, bones: ['armU' + side, 'armL' + side], joints: j, box: box(j, 4.5), grid: [3, 9], paint: g => paintArm(g, s, j)})
    slot('hand' + side, 'hand' + side, 'hand' + side)
    for (const kind of ['open', 'fist'] as const) {
      const nm = kind === 'open' ? 'hand' + side : 'fist' + side
      rigid('hand' + side, nm, 'hand' + side, [11.8 * sx - 4.5, -29.5, 11.8 * sx + 4.5, -19.5], g => paintHand(g, s, 12.1 * sx, -23.6, -sx, kind))
    }
    if (side === 'K') { slot('pencil', 'pencil', null); rigid('pencil', 'pencil', 'pencil', [6, -33, 18, -16], g => paintPencil(g, 11.8, -24)) }
  }
  if (s.cape) { slot('cape', cape[0]); part({slot: 'cape', name: 'cape', bones: ['chest', ...cape], joints: [[0, -46], [0, -40], [0, -35.5], [0, -28]], box: [-16, -46, 16, -28], grid: [5, 6], paint: g => paintCape(g, s, false)}) }
  slot('bow', 'chest'); rigid('bow', 'bow', 'chest', [-8, -45, 8, -35], g => paintBow(g, s.bow, s.outline, 0, -41.6, s.cape ? 0.85 : 1))
  // Head.
  slot('face', 'head'); rigid('face', 'face', 'head', [-23, -93, 23, -44], g => {
    const d = 'M-20,-70 C-20,-84 -11,-90.5 0,-90.5 C11,-90.5 20,-84 20,-70 C20,-58 15.4,-50.6 8.4,-47.4 C4.2,-45.6 -4.2,-45.6 -8.4,-47.4 C-15.4,-50.6 -20,-58 -20,-70Z'
    ink(g, d, s.skin, s.outline, 0.75)
    within(g, d, 'M-22,-92 H22 V-71 Q14,-66 8,-70 Q0,-64 -8,-70 Q-14,-66 -22,-71Z', s.skinShade, 0.9)
    stroke(g, 'M0.2,-55.4 L0.7,-54.8', s.skinShade, 0.7)
  })
  slot('blush', 'head'); rigid('blush', 'blush', 'head', [-18, -58, 18, -51], g => { paintBlush(g, -12.6, -54.4, 3.4); paintBlush(g, 12.6, -54.4, 3.4) })
  const eyes: Eye[] = [{x: -9.5, y: -61, w: 4.6, h: 6.2, outer: -1}, {x: 9.5, y: -61, w: 4.6, h: 6.2, outer: 1}]
  eyes.forEach((e, i) => {
    const side = i ? 'K' : 'F'
    slot('white' + side, 'head'); rigid('white' + side, 'white' + side, 'head', [e.x - 6.5, e.y - 9, e.x + 6.5, e.y + 8], g => paintEyeWhite(g, s, e))
    slot('iris' + side, 'pupil' + side); rigid('iris' + side, 'iris' + side, 'pupil' + side, [e.x - 5, e.y - 7, e.x + 5, e.y + 7.5], g => paintIris(g, s, e))
    slot('lash' + side, 'head', 'open' + side)
    for (const kind of ['open', 'half', 'closed', 'happy', 'squeeze'] as const)
      rigid('lash' + side, kind + side, 'head', [e.x - 8, e.y - 10, e.x + 8, e.y + 8], g => paintLash(g, s, e, kind))
  })
  slot('mouth', 'mouth', 'smile')
  for (const m of MOUTHS) rigid('mouth', m, 'mouth', [-5, -55, 5, -46], g => paintMouth(g, s, 0, -52, m, false))
  if (s.glasses) { slot('glasses', 'head'); rigid('glasses', 'glasses', 'head', [-17, -69, 17, -53], g => paintGlasses(g, eyes, false, '#5a2e1c')) }
  else { slot('glasses', 'head', null); rigid('glasses', 'studyGlasses', 'head', [-17, -69, 17, -53], g => paintGlasses(g, eyes, false, mix(s.outline, '#ffffff', 0.25))) }
  for (const [name, b, j] of [['lockF', lockF, H.lock], ['lockK', lockK, mirror(H.lock)]] as const) {
    slot(name, b[0]); part({slot: name, name, bones: b, joints: j, box: box(j, 5), grid: [3, 7], paint: g => paintLock(g, s, j, u => 6 - u * 2, {curl: j[0][0] < 0 ? 0.8 : -0.8})})
  }
  slot('crown', 'bangs')
  const crown = smooth(crownFront(s))
  part({slot: 'crown', name: 'crown', bones: ['head', 'bangs'], joints: [[0, -106], [0, -82], [0, -56]], box: [-28, -106, 28, -56], grid: [5, 7], paint: g => {
    ink(g, crown, hairFill(g, s), s.outline, 0.75)
    within(g, crown, 'M-30,-80 Q-16,-70 -12,-60 L-30,-60Z M30,-80 Q16,-70 12,-60 L30,-60Z', s.hairShade, 0.45)
    for (const [x0, x1] of [[-14, -5], [-3.5, 5], [7, 15]]) stroke(g, `M${x0},-92 Q${(x0 + x1) / 2},-93.6 ${x1},-92`, '#ffffff', 1.1, 0.42)
    for (const x of [-18, -9, 9, 18]) stroke(g, `M${x * 0.55},-99 Q${x * 0.85},-90 ${x},-81`, s.hairShade, 0.5, 0.4)
  }})
  // Brows show through the bangs (drawn over them, half transparent).
  eyes.forEach((e, i) => {
    const side = i ? 'K' : 'F'
    slot('brow' + side, 'brow' + side); rigid('brow' + side, 'brow' + side, 'brow' + side, [e.x - 5, -75, e.x + 5, -68], g => paintBrow(g, s, e.x, -72, 3.2))
  })
  // Dog ears hang over the crown; the clip and Star's bows on top.
  for (const [name, b, sx] of [['dogK', dogK, -1], ['dogF', dogF, 1]] as const) {
    const j = dogEar(sx)
    slot(name, b[0], null)
    part({slot: name, name, bones: b, joints: j, box: box(j, 8), grid: [3, 6], paint: g => placed(g, j[0], j[2], false, () => paintDogEar(g, s))})
  }
  if (s.clip === 'star') { slot('clip', 'head'); rigid('clip', 'clip', 'head', [5, -96, 21, -79], g => { ink(g, starPath(13, -87.5, 6.4, 0.42, 4, -0.3), '#f2c043', s.outline, 0.7); stroke(g, 'M11.4,-90.6 L12.6,-88.2', '#ffffff', 0.7, 0.7) }) }
  if (s.clip === 'moon') { slot('clip', 'head'); rigid('clip', 'clip', 'head', [9, -91, 21, -77], g => { ink(g, 'M17,-89 A5,5 0 1 0 17,-79 A3.6,3.6 0 1 1 17,-89Z', '#efe6ff', s.outline, 0.6) }) }
  // Raised arms are drawn over the head and hair (a draw-order switch, same layers).
  for (const side of ['K', 'F'] as const) {
    const arm = parts.find(p => p.name === 'arm' + side)!, hands = parts.filter(p => p.slot === 'hand' + side)
    slot('arm' + side + 'Up', 'armU' + side, null); part({...arm, slot: 'arm' + side + 'Up'})
    slot('hand' + side + 'Up', 'hand' + side, null); for (const h of hands) part({...h, slot: 'hand' + side + 'Up'})
  }
  if (pigF.length) for (const [name, b, sx] of [['bowF', pigF, -1], ['bowK', pigK, 1]] as const) {
    slot(name, b[0]); rigid(name, name, b[0], [21 * sx - 7.5, -72, 21 * sx + 7.5, -60], g => paintBow(g, s.bow, s.outline, 21.2 * sx, -66.2, 0.8, false))
  }
  return {bones, slots, parts, chains}
}

function sideHair(s: Style) {
  if (s.hairStyle === 'long') {
    const v = s.volume
    return {
      strands: [
        [[-20, -66], [-23.5 * v, -53], [-24.5 * v, -40], [-23 * v, -26]],
        [[-14, -73], [-17 * v, -58], [-17.5 * v, -42], [-15.5 * v, -24]],
        [[-6, -76], [-8.5, -60], [-8.5, -44], [-6.5, -29]],
      ] as Pt[][],
      widths: [10 * v, 13 * v, 11],
      lock: [[5, -76], [5.6, -64], [5.2, -52], [6, -43]] as Pt[],
    }
  }
  if (s.hairStyle === 'bob') return {
    strands: [[[-21, -64], [-24, -55], [-24.5, -46]], [[-14, -70], [-18, -58], [-19, -47]]] as Pt[][],
    widths: [9, 10],
    lock: [[5, -77], [5.6, -64], [5.2, -50]] as Pt[],
  }
  return {strands: [] as Pt[][], widths: [] as number[], lock: [[4.6, -75], [5, -66], [5, -57.5]] as Pt[]}
}

function sideDef(s: Style): ViewDef {
  const H = sideHair(s)
  const cat = s.catByNature
  const bones: BoneDef[] = [
    {name: 'root', parent: null, at: [0, 0]},
    {name: 'hips', parent: 'root', at: [0, -27]},
    {name: 'chest', parent: 'hips', at: [0, -31]},
    {name: 'neck', parent: 'chest', at: [1, -41]},
    {name: 'head', parent: 'neck', at: [1, -46]},
    {name: 'browF', parent: 'head', at: [13.8, -72]},
    {name: 'pupilF', parent: 'head', at: [13.5, -61]},
    {name: 'mouth', parent: 'head', at: [16.6, -52]},
    {name: 'bangs', parent: 'head', at: [12, -84]},
    {name: 'armUF', parent: 'chest', at: [0.5, -40]},
    {name: 'armLF', parent: 'armUF', at: [0.5, -32.6]},
    {name: 'handF', parent: 'armLF', at: [0.5, -26]},
    {name: 'armUK', parent: 'chest', at: [0.5, -40]},
    {name: 'armLK', parent: 'armUK', at: [0.5, -32.6]},
    {name: 'handK', parent: 'armLK', at: [0.5, -26]},
    {name: 'thighF', parent: 'hips', at: [0.5, -23]},
    {name: 'shinF', parent: 'thighF', at: [0.5, -12.5]},
    {name: 'footF', parent: 'shinF', at: [0.5, -4]},
    {name: 'thighK', parent: 'hips', at: [0.5, -23]},
    {name: 'shinK', parent: 'thighK', at: [0.5, -12.5]},
    {name: 'footK', parent: 'shinK', at: [0.5, -4]},
  ]
  const chains: ChainDef[] = []
  const parts: PartDef[] = []
  const slots: SlotDef[] = []
  const slot = (name: string, bone: string, attachment: string | null = name, extra: Partial<SlotDef> = {}) => slots.push({name, bone, attachment, ...extra})
  const chain = (base: string, parent: string, joints: Pt[], feel: ChainFeel) => {
    bones.push(...chainBones(base, parent, joints))
    chains.push({name: base, bones: names(base, joints), tip: joints[joints.length - 1], feel})
    return names(base, joints)
  }
  const part = (p: PartDef) => parts.push(p)
  const rigid = (slotName: string, name: string, bone: string, b: [number, number, number, number], paint: (g: G) => void) =>
    part({slot: slotName, name, bones: [bone], box: b, paint})

  const skirt = chain('skirt', 'hips', [[0, -29], [0, -23.5], [0, -18]], FEEL.skirt)
  const cape = s.cape ? chain('cape', 'chest', [[-3, -40], [-6, -35.5], [-8, -31]], FEEL.cape) : []
  const catTailJ: Pt[] = [[-5, -25], [-12, -23], [-18, -27], [-21.5, -34.5], [-22, -43], [-19.5, -50]]
  const dogTailJ: Pt[] = [[-6, -25], [-13, -27], [-17.5, -32], [-18, -38]]
  const tailCat = chain('tailCat', 'hips', catTailJ, FEEL.catTail)
  const tailDog = chain('tailDog', 'hips', dogTailJ, FEEL.dogTail)
  const catNear: Pt[] = [[-2, -95], [-2.8, -102], [-3.6, -109]], catFar: Pt[] = [[-11, -92.5], [-13.6, -99.4], [-15.8, -106]]
  const dogNear: Pt[] = [[-5, -87], [-8, -77], [-9.6, -66]]
  const catF = chain('catF', 'head', catNear, FEEL.catEar), catK = chain('catK', 'head', catFar, FEEL.catEar)
  const dogF = chain('dogF', 'head', dogNear, FEEL.dogEar)
  chains.push({name: 'bangs', bones: ['bangs'], tip: [17, -64], feel: FEEL.bangs(s)})
  const strandChains: {bones: string[]; joints: Pt[]; w: number}[] = H.strands.map((joints, i) => ({bones: chain(`hair${i}`, 'head', joints, FEEL.hair(s)), joints, w: H.widths[i]}))
  const lockF = chain('lockF', 'head', H.lock, FEEL.lockSide(s))
  const pigJ: Pt[] = [[-13, -68], [-17, -56], [-19.2, -44], [-18.4, -31]]
  const pigFarJ: Pt[] = [[-8, -71], [-11, -59], [-12.6, -47], [-11.6, -35]]
  const pig = s.hairStyle === 'twin' ? chain('pigF', 'head', pigJ, FEEL.pigtail(s)) : []
  const pigFar = s.hairStyle === 'twin' ? chain('pigK', 'head', pigFarJ, FEEL.pigtail(s)) : []
  const FAR = 0.8

  const legJ: Pt[] = [[0.5, -25], [0.5, -12.5], [0.5, -4], [0.5, -3]]
  const armJ: Pt[] = [[0.5, -40.5], [0.5, -32.6], [0.5, -26]]
  // --- far side ---
  slot('armK', 'armUK', 'armK', {shade: FAR}); part({slot: 'armK', name: 'armK', bones: ['armUK', 'armLK'], joints: armJ, box: box(armJ, 4.5), grid: [3, 9], paint: g => paintArm(g, s, armJ)})
  slot('handK', 'handK', 'handK', {shade: FAR})
  for (const kind of ['open', 'fist'] as const) rigid('handK', kind === 'open' ? 'handK' : 'fistK', 'handK', [-4, -29.5, 5, -19.5], g => paintHand(g, s, 0.6, -23.6, 1, kind))
  slot('legK', 'thighK', 'legK', {shade: FAR}); part({slot: 'legK', name: 'legK', bones: ['thighK', 'shinK', 'footK'], joints: legJ, box: box(legJ, 4.5), grid: [3, 10], paint: g => paintLeg(g, s, legJ.slice(0, 3), 6, 4.4)})
  slot('bootK', 'footK', 'bootK', {shade: FAR}); rigid('bootK', 'bootK', 'footK', [-5, -12, 9, 2], g => paintBootSide(g, s, 0.5))
  if (pigFar.length) { slot('pigK', pigFar[0], 'pigK', {shade: 0.85}); part({slot: 'pigK', name: 'pigK', bones: pigFar, joints: pigFarJ, box: box(pigFarJ, 9), grid: [3, 10], paint: g => paintLock(g, s, pigFarJ, u => 7.5 + Math.sin(u * Math.PI) * 4.5 - u * 2, {wave: 0.1, curl: -1.4})}) }
  for (const sc of strandChains) {
    const name = sc.bones[0].slice(0, -1)
    slot(name, sc.bones[0])
    part({slot: name, name, bones: sc.bones, joints: sc.joints, box: box(sc.joints, sc.w), grid: [3, 10], paint: g => paintLock(g, s, sc.joints, u => sc.w * (1 - u * 0.25), {wave: s.hairStyle === 'long' ? 0.14 : 0.05, curl: 1.6})})
  }
  slot('hairBack', 'head'); rigid('hairBack', 'hairBack', 'head', [-28, -105, 8, -46], g => {
    const d = 'M-25,-64 C-26.5,-86 -16,-101 -3,-102 C4,-102 6.5,-90 4.5,-74 L-1,-55 L-20,-50 C-24,-54 -25.4,-58.5 -25,-64Z'
    ink(g, d, hairFill(g, s), s.outline, 0.7)
    within(g, d, 'M-30,-66 Q-12,-58 6,-66 V-46 H-30Z', s.hairShade, 0.35)
  })
  if (s.cape) { slot('capeBack', cape[0]); part({slot: 'capeBack', name: 'capeBack', bones: ['chest', ...cape], joints: [[-2, -46], [-3, -40], [-6, -35.5], [-10, -28]], box: [-15, -46, 1, -27], grid: [4, 6], paint: g => {
    const c = s.cape!
    const d = 'M-1,-44.5 C-7,-43.6 -11.6,-38 -13.4,-29.6 Q-8,-28.2 -3.4,-30.6 Z'
    ink(g, d, c.shade, s.outline, 0.7)
    if (c.hood) ink(g, 'M-1,-46 C-6,-46 -9.8,-43.6 -10.2,-39.8 C-7.6,-41.2 -4,-41.6 -0.6,-41Z', c.color, s.outline, 0.6)
  }}) }
  for (const [name, b, j] of [['catK', catK, catFar]] as const) {
    slot(name, b[0], cat ? name : null, {shade: 0.85})
    part({slot: name, name, bones: b, joints: j, box: box(j, 8), grid: [3, 5], paint: g => placed(g, j[0], j[2], true, () => paintCatEar(g, s, s.earInner))})
  }
  slot('tailCat', 'tailCat0', cat ? 'tailCat' : null); part({slot: 'tailCat', name: 'tailCat', bones: tailCat, joints: catTailJ, box: box(catTailJ, 4), grid: [3, 14], paint: g => paintTail(g, s, catTailJ, false)})
  slot('tailDog', 'tailDog0', null); part({slot: 'tailDog', name: 'tailDog', bones: tailDog, joints: dogTailJ, box: box(dogTailJ, 5), grid: [3, 8], paint: g => paintTail(g, s, dogTailJ, true)})
  // --- body ---
  slot('legF', 'thighF'); part({slot: 'legF', name: 'legF', bones: ['thighF', 'shinF', 'footF'], joints: legJ, box: box(legJ, 4.5), grid: [3, 10], paint: g => paintLeg(g, s, legJ.slice(0, 3), 6, 4.4)})
  slot('bootF', 'footF'); rigid('bootF', 'bootF', 'footF', [-5, -12, 9, 2], g => paintBootSide(g, s, 0.5))
  slot('neck', 'neck'); rigid('neck', 'neck', 'neck', [-4, -55, 6, -38], g => paintNeck(g, s, 1))
  slot('torso', 'chest'); part({slot: 'torso', name: 'torso', bones: ['hips', 'chest'], joints: [[0, -22], [0, -31], [0, -44]], box: [-8, -45, 8, -22], grid: [3, 7], paint: g => paintTorso(g, s, true)})
  slot('skirt', 'skirt0'); part({slot: 'skirt', name: 'skirt', bones: ['hips', ...skirt], joints: [[0, -33], [0, -29], [0, -23.5], [0, -15]], box: [-16, -33, 15, -13], grid: [5, 8], paint: g => paintSkirtSide(g, s)})
  // --- head ---
  slot('face', 'head'); rigid('face', 'face', 'head', [-24, -93, 24, -44], g => {
    const d = 'M-21,-68 C-21,-84 -11,-90.5 0,-90.5 C12,-90.5 20,-82.5 20.6,-70.5 C20.9,-64.5 21.9,-60.6 21.4,-57.4 C20.9,-52.4 16.4,-47.6 9.2,-46.6 C3.2,-45.8 -2,-47 -5,-50 L-12,-52 C-18,-56 -21,-62 -21,-68Z'
    ink(g, d, s.skin, s.outline, 0.75)
    within(g, d, 'M-24,-92 H24 V-72 Q16,-67 8,-71 Q-6,-64 -24,-72Z', s.skinShade, 0.9)
    within(g, d, 'M-24,-70 L2,-70 L2,-44 L-24,-44Z', s.skinShade, 0.5)
  })
  slot('blush', 'head'); rigid('blush', 'blush', 'head', [5, -58, 17, -51], g => paintBlush(g, 11.2, -54.4, 3.1))
  const eye: Eye = {x: 13.6, y: -61, w: 3.2, h: 6, outer: -1}
  slot('whiteF', 'head'); rigid('whiteF', 'whiteF', 'head', [eye.x - 5.5, eye.y - 9, eye.x + 5.5, eye.y + 8], g => paintEyeWhite(g, s, eye))
  slot('irisF', 'pupilF'); rigid('irisF', 'irisF', 'pupilF', [eye.x - 4, eye.y - 7, eye.x + 4, eye.y + 7.5], g => paintIris(g, s, {...eye, x: eye.x + 0.5}))
  slot('lashF', 'head', 'openF')
  for (const kind of ['open', 'half', 'closed', 'happy', 'squeeze'] as const)
    rigid('lashF', kind + 'F', 'head', [eye.x - 7, eye.y - 10, eye.x + 7, eye.y + 8], g => paintLash(g, s, eye, kind))
  slot('mouth', 'mouth', 'smile')
  for (const m of MOUTHS) rigid('mouth', m, 'mouth', [12, -55, 21, -46], g => paintMouth(g, s, 16.6, -52, m, true))
  if (s.glasses) { slot('glasses', 'head'); rigid('glasses', 'glasses', 'head', [-2, -68, 19, -54], g => paintGlasses(g, [eye], true, '#5a2e1c')) }
  else { slot('glasses', 'head', null); rigid('glasses', 'studyGlasses', 'head', [-2, -68, 19, -54], g => paintGlasses(g, [eye], true, mix(s.outline, '#ffffff', 0.25))) }
  for (const [name, b, j] of [['catF', catF, catNear]] as const) {
    slot(name, b[0], cat ? name : null)
    part({slot: name, name, bones: b, joints: j, box: box(j, 8), grid: [3, 5], paint: g => placed(g, j[0], j[2], true, () => paintCatEar(g, s, s.earInner))})
  }
  slot('crown', 'bangs')
  const crown = smooth([[21.6, -64.5], [22.6, -72], [21, -80], [17, -93], [4, -103.5], [-7, -102.5], [-19, -101], [-26, -90], [-25.6, -74], [-25, -65], [-22.5, -57.5], [-19, -53], [-13, -56], [-6.5, -59.5], [-3, -66], [1, -72.5], [5, -77], [5, -77], [9.5, -73], [12.5, -65], [12.5, -65], [14.5, -73.5], [17.6, -63], [17.6, -63], [19, -71.5]])
  part({slot: 'crown', name: 'crown', bones: ['head', 'bangs'], joints: [[4, -106], [12, -84], [18, -58]], box: [-29, -107, 25, -50], grid: [6, 7], paint: g => {
    ink(g, crown, hairFill(g, s), s.outline, 0.75)
    within(g, crown, 'M-30,-74 Q-14,-62 -4,-58 L-30,-50Z', s.hairShade, 0.45)
    stroke(g, 'M-12,-93.5 Q-2,-96 8,-93', '#ffffff', 1.1, 0.42)
    for (const [a, b] of [[[-16, -98], [-22, -66]], [[-6, -101], [-12, -62]], [[6, -99], [6, -76]], [[14, -94], [17, -70]]] as const) stroke(g, `M${a[0]},${a[1]} Q${(a[0] + b[0]) / 2 - 2},${(a[1] + b[1]) / 2} ${b[0]},${b[1]}`, s.hairShade, 0.55, 0.5)
  }})
  slot('browF', 'browF'); rigid('browF', 'browF', 'browF', [9, -75, 18, -68], g => paintBrow(g, s, 13.8, -72, 2.6))
  slot('lockF', lockF[0]); part({slot: 'lockF', name: 'lockF', bones: lockF, joints: H.lock, box: box(H.lock, 5), grid: [3, 7], paint: g => paintLock(g, s, H.lock, u => 6 - u * 2, {curl: 0.8})})
  if (pig.length) {
    slot('pigF', pig[0]); part({slot: 'pigF', name: 'pigF', bones: pig, joints: pigJ, box: box(pigJ, 9), grid: [3, 10], paint: g => paintLock(g, s, pigJ, u => 8 + Math.sin(u * Math.PI) * 5 - u * 2, {wave: 0.1, curl: -1.5})})
    slot('bowF', pig[0]); rigid('bowF', 'bowF', pig[0], [-20, -73, -6, -61], g => paintBow(g, s.bow, s.outline, -13, -67.6, 0.8, false))
  }
  for (const [name, b, j] of [['dogF', dogF, dogNear]] as const) {
    slot(name, b[0], null)
    part({slot: name, name, bones: b, joints: j, box: box(j, 8), grid: [3, 6], paint: g => placed(g, j[0], j[2], false, () => paintDogEar(g, s))})
  }
  if (s.clip === 'star') { slot('clip', 'head'); rigid('clip', 'clip', 'head', [-9, -98, 7, -82], g => ink(g, starPath(-1, -90, 6, 0.42, 4, -0.3), '#f2c043', s.outline, 0.7)) }
  if (s.clip === 'moon') { slot('clip', 'head'); rigid('clip', 'clip', 'head', [-8, -92, 4, -78], g => ink(g, 'M0,-90 A5,5 0 1 0 0,-80 A3.6,3.6 0 1 1 0,-90Z', '#efe6ff', s.outline, 0.6)) }
  // --- near arm in front, then the capelet over the shoulder ---
  slot('armF', 'armUF'); part({slot: 'armF', name: 'armF', bones: ['armUF', 'armLF'], joints: armJ, box: box(armJ, 4.5), grid: [3, 9], paint: g => paintArm(g, s, armJ)})
  slot('handF', 'handF', 'handF')
  for (const kind of ['open', 'fist'] as const) rigid('handF', kind === 'open' ? 'handF' : 'fistF', 'handF', [-4, -29.5, 5, -19.5], g => paintHand(g, s, 0.6, -23.6, 1, kind))
  if (s.cape) { slot('cape', cape[0]); part({slot: 'cape', name: 'cape', bones: ['chest', ...cape], joints: [[0, -46], [-3, -40], [-6, -35.5], [-9, -28]], box: [-14, -46, 13, -29], grid: [5, 6], paint: g => paintCape(g, s, true)}) }
  slot('bow', 'chest'); rigid('bow', 'bow', 'chest', [1, -45, 9, -37], g => paintBow(g, s.bow, s.outline, 5, -41.4, 0.6, true))
  return {bones, slots, parts, chains}
}
