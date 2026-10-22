/**
 * Hand-drawn (vector, Canvas2D) accessory and effect art, painted once into one texture atlas:
 * animal ears and tails in each character's hair colours, study props, cushions and the little
 * hearts / sparkles / sweat drops. Same family look as the sprites: dark warm outline, two-tone
 * cel shading and a soft highlight.
 */
import type {CastId, Rig} from './rig'

export type Slot = { x: number; y: number; w: number; h: number }
export type ItemName = 'heart' | 'sparkle' | 'sweat' | 'zzz' | 'bang' | 'question' | 'dust' | 'note' | 'blush'
  | 'glasses' | 'book' | 'notebook' | 'pencil' | 'laptop' | 'desk'
export type CastItem = 'catEar' | 'dogEar' | 'catTail' | 'dogTail' | 'cushion'
export type Atlas = { canvas: HTMLCanvasElement; size: number; slots: Record<string, Slot> }

export const slotKey = (item: CastItem, id: CastId) => item + ':' + id

const SHARED: Record<ItemName, [number, number, number, number]> = {
  heart: [0, 0, 72, 72], sparkle: [72, 0, 72, 72], sweat: [144, 0, 56, 72], zzz: [200, 0, 64, 72],
  bang: [264, 0, 48, 80], question: [312, 0, 60, 80], dust: [372, 0, 80, 64], note: [452, 0, 64, 72],
  blush: [516, 0, 104, 52], pencil: [620, 0, 150, 30], glasses: [620, 30, 260, 92],
  book: [0, 84, 180, 132], notebook: [180, 84, 190, 104], laptop: [370, 124, 220, 160], desk: [590, 124, 420, 150],
}
const ROW = 300, ROW_H = 180

function shadeHex(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16)
  const mix = (c: number) => Math.round(amount >= 0 ? c + (255 - c) * amount : c * (1 + amount))
  const r = mix((n >> 16) & 255), g = mix((n >> 8) & 255), b = mix(n & 255)
  return `rgb(${r},${g},${b})`
}

type Ctx = CanvasRenderingContext2D
const outline = (ctx: Ctx, color: string, width: number) => {
  ctx.lineJoin = 'round'; ctx.lineCap = 'round'; ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke()
}

function catEar(ctx: Ctx, rig: Rig) {
  const {hair, tip, inner, outline: line} = rig.palette
  ctx.beginPath()
  ctx.moveTo(8, 112); ctx.quadraticCurveTo(14, 44, 54, 6); ctx.quadraticCurveTo(84, 52, 90, 112); ctx.closePath()
  const g = ctx.createLinearGradient(0, 112, 0, 0); g.addColorStop(0, hair); g.addColorStop(0.75, hair); g.addColorStop(1, tip)
  ctx.fillStyle = g; ctx.fill(); outline(ctx, line, 4)
  ctx.beginPath()
  ctx.moveTo(26, 110); ctx.quadraticCurveTo(30, 60, 53, 28); ctx.quadraticCurveTo(70, 62, 74, 110); ctx.closePath()
  const gi = ctx.createLinearGradient(0, 110, 0, 28); gi.addColorStop(0, shadeHex(inner, -0.12)); gi.addColorStop(1, inner)
  ctx.fillStyle = gi; ctx.fill()
  ctx.strokeStyle = 'rgba(255,255,255,0.85)'; ctx.lineWidth = 2.2
  for (const [x0, y0, x1, y1] of [[40, 104, 46, 74], [52, 106, 54, 66], [62, 104, 60, 78]]) { ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke() }
  ctx.beginPath(); ctx.moveTo(18, 96); ctx.quadraticCurveTo(22, 52, 50, 16)
  ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 3; ctx.stroke()
}

function dogEar(ctx: Ctx, rig: Rig) {
  const {hair, tip, outline: line} = rig.palette
  ctx.beginPath()
  ctx.moveTo(30, 8); ctx.bezierCurveTo(66, 4, 86, 22, 84, 56)
  ctx.bezierCurveTo(84, 102, 70, 128, 46, 130); ctx.bezierCurveTo(20, 130, 8, 108, 12, 76)
  ctx.bezierCurveTo(14, 46, 14, 16, 30, 8); ctx.closePath()
  const g = ctx.createLinearGradient(0, 0, 0, 130); g.addColorStop(0, hair); g.addColorStop(0.42, hair); g.addColorStop(1, tip)
  ctx.fillStyle = g; ctx.fill()
  ctx.save(); ctx.clip()
  ctx.fillStyle = 'rgba(40,20,30,0.18)'; ctx.beginPath(); ctx.ellipse(72, 74, 20, 60, 0.1, 0, Math.PI * 2); ctx.fill()
  ctx.fillStyle = 'rgba(255,255,255,0.32)'; ctx.beginPath(); ctx.ellipse(30, 46, 7, 26, -0.15, 0, Math.PI * 2); ctx.fill()
  ctx.restore()
  outline(ctx, line, 4)
}

function tube(ctx: Ctx, rig: Rig, w: number, h: number, fluffy: boolean) {
  const {hair, tip, outline: line} = rig.palette
  const mid = h / 2
  ctx.beginPath()
  if (fluffy) {
    ctx.moveTo(0, mid - h * 0.26)
    for (let i = 1; i <= 5; i++) ctx.quadraticCurveTo(w * (i - 0.5) / 6, mid - h * (0.3 + 0.12 * (i % 2)) - i * 1.2, w * i / 6, mid - h * (0.28 + i * 0.02))
    ctx.quadraticCurveTo(w, mid - h * 0.42, w - 3, mid)
    ctx.quadraticCurveTo(w, mid + h * 0.42, w * 5 / 6, mid + h * 0.36)
    for (let i = 4; i >= 0; i--) ctx.quadraticCurveTo(w * (i + 0.5) / 6, mid + h * (0.38 + 0.1 * (i % 2)), w * i / 6, mid + h * (0.26 + i * 0.02))
  } else {
    const r = h * 0.34
    ctx.moveTo(0, mid - r * 0.85); ctx.lineTo(w - r * 1.2, mid - r)
    ctx.quadraticCurveTo(w - 2, mid - r, w - 2, mid); ctx.quadraticCurveTo(w - 2, mid + r, w - r * 1.2, mid + r)
    ctx.lineTo(0, mid + r * 0.85)
  }
  ctx.closePath()
  const g = ctx.createLinearGradient(0, 0, w, 0); g.addColorStop(0, hair); g.addColorStop(0.62, hair); g.addColorStop(1, tip)
  ctx.fillStyle = g; ctx.fill()
  ctx.save(); ctx.clip()
  ctx.fillStyle = 'rgba(30,15,30,0.2)'; ctx.fillRect(0, mid + h * 0.08, w, h)
  ctx.fillStyle = 'rgba(255,255,255,0.3)'; ctx.fillRect(w * 0.08, mid - h * 0.2, w * 0.8, h * 0.07)
  ctx.restore()
  outline(ctx, line, 3.6)
}

function cushion(ctx: Ctx, rig: Rig) {
  const color = rig.palette.cushion
  ctx.beginPath()
  ctx.moveTo(26, 40); ctx.quadraticCurveTo(128, 18, 230, 40)
  ctx.quadraticCurveTo(252, 62, 230, 86); ctx.quadraticCurveTo(128, 100, 26, 86)
  ctx.quadraticCurveTo(4, 62, 26, 40); ctx.closePath()
  const g = ctx.createLinearGradient(0, 24, 0, 96); g.addColorStop(0, shadeHex(color, 0.28)); g.addColorStop(0.55, color); g.addColorStop(1, shadeHex(color, -0.3))
  ctx.fillStyle = g; ctx.fill(); outline(ctx, rig.palette.outline, 3.5)
  ctx.beginPath(); ctx.moveTo(40, 66); ctx.quadraticCurveTo(128, 76, 216, 66)
  ctx.strokeStyle = shadeHex(color, -0.35); ctx.lineWidth = 2; ctx.setLineDash([5, 5]); ctx.stroke(); ctx.setLineDash([])
  ctx.fillStyle = shadeHex(color, -0.3); ctx.beginPath(); ctx.ellipse(128, 54, 7, 4, 0, 0, Math.PI * 2); ctx.fill()
}

function heart(ctx: Ctx, x: number, y: number, s: number) {
  ctx.beginPath()
  ctx.moveTo(x, y + s * 0.32)
  ctx.bezierCurveTo(x - s * 0.02, y - s * 0.02, x - s * 0.52, y - s * 0.02, x - s * 0.5, y + s * 0.3)
  ctx.bezierCurveTo(x - s * 0.48, y + s * 0.56, x - s * 0.14, y + s * 0.74, x, y + s * 0.9)
  ctx.bezierCurveTo(x + s * 0.14, y + s * 0.74, x + s * 0.48, y + s * 0.56, x + s * 0.5, y + s * 0.3)
  ctx.bezierCurveTo(x + s * 0.52, y - s * 0.02, x + s * 0.02, y - s * 0.02, x, y + s * 0.32)
  ctx.closePath()
}

function star4(ctx: Ctx, x: number, y: number, r: number, inner: number) {
  ctx.beginPath()
  for (let i = 0; i < 8; i++) {
    const a = -Math.PI / 2 + i * Math.PI / 4, rr = i % 2 ? inner : r
    if (i === 0) ctx.moveTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr)
    else ctx.quadraticCurveTo(x + Math.cos(a - Math.PI / 8) * inner * 0.7, y + Math.sin(a - Math.PI / 8) * inner * 0.7, x + Math.cos(a) * rr, y + Math.sin(a) * rr)
  }
  ctx.quadraticCurveTo(x + Math.cos(-Math.PI / 2 - Math.PI / 8) * inner * 0.7, y + Math.sin(-Math.PI / 2 - Math.PI / 8) * inner * 0.7, x, y - r)
  ctx.closePath()
}

function glyph(ctx: Ctx, text: string, x: number, y: number, size: number, fill: string, stroke: string) {
  ctx.font = `900 ${size}px "Segoe UI", "Arial Rounded MT Bold", system-ui, sans-serif`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.lineJoin = 'round'; ctx.lineWidth = size * 0.16; ctx.strokeStyle = stroke; ctx.strokeText(text, x, y)
  ctx.fillStyle = fill; ctx.fillText(text, x, y)
}

const DRAW: Record<ItemName, (ctx: Ctx, w: number, h: number) => void> = {
  heart: (ctx, w) => {
    heart(ctx, w / 2, 6, 60)
    const g = ctx.createLinearGradient(0, 6, 0, 62); g.addColorStop(0, '#ff8fb1'); g.addColorStop(1, '#e8436f')
    ctx.fillStyle = g; ctx.fill(); outline(ctx, '#8e1f42', 3.5)
    ctx.fillStyle = 'rgba(255,255,255,0.9)'; ctx.beginPath(); ctx.ellipse(w / 2 - 14, 22, 6, 4, -0.6, 0, Math.PI * 2); ctx.fill()
  },
  sparkle: (ctx, w, h) => {
    star4(ctx, w / 2, h / 2, 31, 9)
    const g = ctx.createRadialGradient(w / 2, h / 2, 2, w / 2, h / 2, 30); g.addColorStop(0, '#fffbe6'); g.addColorStop(1, '#ffd25a')
    ctx.fillStyle = g; ctx.fill(); outline(ctx, '#b07a12', 2.6)
  },
  sweat: (ctx, w) => {
    ctx.beginPath(); ctx.moveTo(w / 2, 6); ctx.bezierCurveTo(w / 2 + 6, 22, w - 6, 34, w - 6, 48)
    ctx.arc(w / 2, 48, w / 2 - 6, 0, Math.PI); ctx.bezierCurveTo(6, 34, w / 2 - 6, 22, w / 2, 6); ctx.closePath()
    const g = ctx.createLinearGradient(0, 6, 0, 70); g.addColorStop(0, '#d8f2ff'); g.addColorStop(1, '#7cc8f4')
    ctx.fillStyle = g; ctx.fill(); outline(ctx, '#2f7fb6', 3)
    ctx.fillStyle = 'rgba(255,255,255,0.95)'; ctx.beginPath(); ctx.ellipse(w / 2 - 7, 46, 4, 7, 0.3, 0, Math.PI * 2); ctx.fill()
  },
  zzz: (ctx, w, h) => glyph(ctx, 'z', w / 2, h / 2, 58, '#cdb8ff', '#4b3a7a'),
  bang: (ctx, w, h) => glyph(ctx, '!', w / 2, h / 2, 72, '#ffb03a', '#8a3a10'),
  question: (ctx, w, h) => glyph(ctx, '?', w / 2, h / 2, 70, '#8fd0ff', '#1f4f7a'),
  note: (ctx, w, h) => glyph(ctx, '♪', w / 2, h / 2, 62, '#fff1c4', '#5a4120'),
  dust: (ctx) => {
    ctx.beginPath()
    for (const [x, y, r] of [[22, 40, 16], [40, 30, 20], [60, 40, 15], [44, 46, 14]]) { ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, Math.PI * 2) }
    ctx.fillStyle = 'rgba(250,244,232,0.95)'; ctx.fill()
    outline(ctx, 'rgba(150,130,110,0.6)', 2.5)
  },
  blush: (ctx, w, h) => {
    const g = ctx.createRadialGradient(w / 2, h / 2, 2, w / 2, h / 2, w / 2)
    g.addColorStop(0, 'rgba(255,120,150,0.75)'); g.addColorStop(1, 'rgba(255,120,150,0)')
    ctx.fillStyle = g; ctx.beginPath(); ctx.ellipse(w / 2, h / 2, w / 2, h / 2, 0, 0, Math.PI * 2); ctx.fill()
    ctx.strokeStyle = 'rgba(214,60,96,0.75)'; ctx.lineWidth = 3; ctx.lineCap = 'round'
    for (const x of [w / 2 - 20, w / 2, w / 2 + 20]) { ctx.beginPath(); ctx.moveTo(x + 6, h / 2 - 9); ctx.lineTo(x - 6, h / 2 + 9); ctx.stroke() }
  },
  pencil: (ctx, w, h) => {
    ctx.beginPath(); ctx.moveTo(4, h / 2); ctx.lineTo(28, 5); ctx.lineTo(w - 16, 5); ctx.lineTo(w - 4, 9); ctx.lineTo(w - 4, h - 9); ctx.lineTo(w - 16, h - 5); ctx.lineTo(28, h - 5); ctx.closePath()
    ctx.fillStyle = '#ffd34d'; ctx.fill()
    ctx.fillStyle = '#f2c79a'; ctx.beginPath(); ctx.moveTo(4, h / 2); ctx.lineTo(28, 5); ctx.lineTo(28, h - 5); ctx.closePath(); ctx.fill()
    ctx.fillStyle = '#ff8fa3'; ctx.fillRect(w - 16, 5, 12, h - 10)
    ctx.beginPath(); ctx.moveTo(4, h / 2); ctx.lineTo(28, 5); ctx.lineTo(w - 16, 5); ctx.lineTo(w - 4, 9); ctx.lineTo(w - 4, h - 9); ctx.lineTo(w - 16, h - 5); ctx.lineTo(28, h - 5); ctx.closePath()
    outline(ctx, '#5a3a1a', 2.6)
  },
  glasses: (ctx, w, h) => {
    const r = 38, cy = h / 2 + 2
    for (const cx of [w / 2 - 52, w / 2 + 52]) {
      ctx.beginPath(); ctx.ellipse(cx, cy, r, r * 0.92, 0, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(200,230,255,0.16)'; ctx.fill()
      outline(ctx, '#3a2a26', 4.6)
      ctx.beginPath(); ctx.moveTo(cx - r * 0.45, cy - r * 0.15); ctx.lineTo(cx - r * 0.1, cy - r * 0.55)
      ctx.strokeStyle = 'rgba(255,255,255,0.65)'; ctx.lineWidth = 3.5; ctx.stroke()
    }
    ctx.beginPath(); ctx.moveTo(w / 2 - 15, cy - 6); ctx.quadraticCurveTo(w / 2, cy - 15, w / 2 + 15, cy - 6); outline(ctx, '#3a2a26', 4.2)
  },
  book: (ctx, w, h) => {
    ctx.beginPath(); ctx.moveTo(12, 14); ctx.quadraticCurveTo(w / 2, 4, w - 12, 14); ctx.lineTo(w - 10, h - 16); ctx.quadraticCurveTo(w / 2, h - 26, 10, h - 16); ctx.closePath()
    const g = ctx.createLinearGradient(0, 0, w, h); g.addColorStop(0, '#8e3b6e'); g.addColorStop(1, '#5b2147')
    ctx.fillStyle = g; ctx.fill(); outline(ctx, '#2f0f24', 4)
    ctx.beginPath(); ctx.moveTo(w / 2, 9); ctx.lineTo(w / 2, h - 21); ctx.strokeStyle = '#2f0f24'; ctx.lineWidth = 3; ctx.stroke()
    ctx.strokeStyle = '#e9c46a'; ctx.lineWidth = 2.6
    for (const x of [26, w / 2 + 14]) { ctx.strokeRect(x, 26, w / 2 - 40, h - 64) }
    star4(ctx, w * 0.27, h / 2 - 4, 10, 3); ctx.fillStyle = '#e9c46a'; ctx.fill()
  },
  notebook: (ctx, w, h) => {
    ctx.beginPath(); ctx.moveTo(22, 12); ctx.lineTo(w - 10, 12); ctx.lineTo(w - 26, h - 10); ctx.lineTo(8, h - 10); ctx.closePath()
    ctx.fillStyle = '#fbf7ee'; ctx.fill(); outline(ctx, '#4b3a2a', 3.4)
    ctx.strokeStyle = 'rgba(90,140,200,0.55)'; ctx.lineWidth = 2
    for (let y = 30; y < h - 16; y += 13) { ctx.beginPath(); ctx.moveTo(22 - (y - 12) * 0.16, y); ctx.lineTo(w - 14 - (y - 12) * 0.16, y); ctx.stroke() }
    ctx.strokeStyle = '#ff7aa2'; ctx.beginPath(); ctx.moveTo(42, 14); ctx.lineTo(28, h - 12); ctx.stroke()
    ctx.strokeStyle = '#5a6a8a'; ctx.lineWidth = 2.4
    ctx.beginPath(); ctx.moveTo(52, 30); ctx.quadraticCurveTo(80, 24, 104, 32); ctx.moveTo(48, 44); ctx.quadraticCurveTo(70, 40, 92, 46); ctx.stroke()
  },
  laptop: (ctx, w, h) => {
    ctx.beginPath(); ctx.roundRect(24, 6, w - 48, h - 40, 12)
    const g = ctx.createLinearGradient(0, 6, 0, h - 34); g.addColorStop(0, '#e9ecf3'); g.addColorStop(1, '#b6bccb')
    ctx.fillStyle = g; ctx.fill(); outline(ctx, '#3a3f52', 4)
    star4(ctx, w / 2, (h - 34) / 2 + 3, 20, 6)
    const sg = ctx.createRadialGradient(w / 2, h / 2 - 14, 2, w / 2, h / 2 - 14, 22); sg.addColorStop(0, '#fff6cf'); sg.addColorStop(1, '#f1c24a')
    ctx.fillStyle = sg; ctx.fill(); outline(ctx, '#9b7417', 2.2)
    ctx.beginPath(); ctx.moveTo(6, h - 30); ctx.lineTo(w - 6, h - 30); ctx.lineTo(w - 18, h - 10); ctx.lineTo(18, h - 10); ctx.closePath()
    ctx.fillStyle = '#9aa1b3'; ctx.fill(); outline(ctx, '#3a3f52', 4)
  },
  desk: (ctx, w, h) => {
    ctx.beginPath(); ctx.roundRect(8, 20, w - 16, 30, 10)
    const g = ctx.createLinearGradient(0, 20, 0, 50); g.addColorStop(0, '#e2b07a'); g.addColorStop(1, '#b97f4c')
    ctx.fillStyle = g; ctx.fill(); outline(ctx, '#4a2b16', 4)
    ctx.beginPath(); ctx.roundRect(28, 50, w - 56, 26, 6); ctx.fillStyle = '#a56c3f'; ctx.fill(); outline(ctx, '#4a2b16', 4)
    for (const x of [44, w - 72]) { ctx.beginPath(); ctx.roundRect(x, 74, 28, h - 84, 8); ctx.fillStyle = '#9a6238'; ctx.fill(); outline(ctx, '#4a2b16', 4) }
    ctx.strokeStyle = 'rgba(255,255,255,0.35)'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(26, 28); ctx.lineTo(w - 26, 28); ctx.stroke()
  },
}

const CAST_ITEMS: Record<CastItem, [number, number, number, number]> = {
  catEar: [0, 0, 98, 118], dogEar: [100, 0, 96, 136], catTail: [200, 0, 256, 52], dogTail: [200, 60, 140, 64], cushion: [460, 0, 256, 104],
}

export function buildAtlas(rigs: readonly Rig[], doc: Document = document): Atlas {
  const size = 1024
  const canvas = doc.createElement('canvas')
  canvas.width = size; canvas.height = size
  const ctx = canvas.getContext('2d')
  const slots: Record<string, Slot> = {}
  if (!ctx) return {canvas, size, slots}
  const paint = (key: string, [x, y, w, h]: [number, number, number, number], draw: (c: Ctx, w: number, h: number) => void) => {
    ctx.save(); ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip(); ctx.translate(x, y); draw(ctx, w, h); ctx.restore()
    slots[key] = {x: x + 1, y: y + 1, w: w - 2, h: h - 2}
  }
  for (const [name, rect] of Object.entries(SHARED) as [ItemName, [number, number, number, number]][]) paint(name, rect, DRAW[name])
  rigs.forEach((rig, index) => {
    const top = ROW + index * ROW_H
    const at = ([x, y, w, h]: [number, number, number, number]): [number, number, number, number] => [x, top + y, w, h]
    paint(slotKey('catEar', rig.id), at(CAST_ITEMS.catEar), c => catEar(c, rig))
    paint(slotKey('dogEar', rig.id), at(CAST_ITEMS.dogEar), c => dogEar(c, rig))
    paint(slotKey('catTail', rig.id), at(CAST_ITEMS.catTail), (c, w, h) => tube(c, rig, w, h, false))
    paint(slotKey('dogTail', rig.id), at(CAST_ITEMS.dogTail), (c, w, h) => tube(c, rig, w, h, true))
    paint(slotKey('cushion', rig.id), at(CAST_ITEMS.cushion), c => cushion(c, rig))
  })
  return {canvas, size, slots}
}
