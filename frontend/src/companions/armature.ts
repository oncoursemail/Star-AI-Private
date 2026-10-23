/**
 * Compiles the drawn views (art.ts) into runtime armatures: bones in parent-local form, slots, and
 * weighted grid meshes whose texture coordinates point into a per-character atlas. Painting the atlas
 * needs a canvas; the geometry and weights do not (so they are unit-tested without one).
 */
import type {CastId} from './cast'
import {viewDef, paintFx, FX} from './art'
import type {FxName, PartDef, View, ViewDef} from './art'
import {chainWeights, setupWorld} from './skeleton'
import type {Armature, BoneData, Influence, MeshData} from './skeleton'
import {SpringChain} from './physics'

/** Atlas pixels per model unit (a 100-unit figure paints 400 px tall; it shows at ~90-180 px). */
export const PX = 4
const PAD = 3

export type Rect = { x: number; y: number; w: number; h: number }
export type Placed = { part: PartDef; rect: Rect }
export type Sheet = { width: number; height: number; placed: Placed[] }

/** Shelf packing, tallest first. */
export function pack(items: readonly PartDef[], width = 2048, scale = PX): Sheet {
  const order = items.map((part, i) => ({part, i, w: Math.ceil((part.box[2] - part.box[0]) * scale) + PAD * 2, h: Math.ceil((part.box[3] - part.box[1]) * scale) + PAD * 2}))
    .sort((a, b) => b.h - a.h || a.i - b.i)
  const placed: Placed[] = new Array(items.length)
  let x = 0, y = 0, row = 0
  for (const it of order) {
    if (x + it.w > width) { x = 0; y += row; row = 0 }
    placed[it.i] = {part: it.part, rect: {x: x + PAD, y: y + PAD, w: it.w - PAD * 2, h: it.h - PAD * 2}}
    x += it.w; row = Math.max(row, it.h)
  }
  let height = 64
  while (height < y + row) height *= 2
  return {width, height, placed}
}

export type CompiledView = { armature: Armature; def: ViewDef }
export type Character = { id: CastId; views: Record<View, CompiledView>; sheet: Sheet }

/** Builds both views of a character on one atlas page. */
export function compileCharacter(id: CastId, page: number): Character {
  const front = viewDef(id, 'front'), side = viewDef(id, 'side')
  // Copies of a part in another slot (raised arms) reuse its painted layer.
  const unique = [...front.parts, ...side.parts].filter((p, i, all) => all.findIndex(q => q.paint === p.paint) === i)
  const sheet = pack(unique)
  const byPaint = new Map(sheet.placed.map(p => [p.part.paint, p.rect]))
  const rects = new Map<PartDef, Rect>([...front.parts, ...side.parts].map(p => [p, byPaint.get(p.paint) as Rect]))
  const compile = (def: ViewDef): CompiledView => ({def, armature: compileView(def, page, rects, sheet)})
  return {id, views: {front: compile(front), side: compile(side)}, sheet}
}

export function compileView(def: ViewDef, page: number, rects: Map<PartDef, Rect>, sheet: {width: number; height: number}): Armature {
  const index = new Map<string, number>()
  def.bones.forEach((b, i) => index.set(b.name, i))
  const bones: BoneData[] = def.bones.map(b => {
    const parent = b.parent ? index.get(b.parent) ?? -1 : -1
    if (b.parent && parent < 0) throw new Error('unknown parent bone ' + b.parent)
    const p = parent >= 0 ? def.bones[parent].at : [0, 0]
    return {name: b.name, parent, x: b.at[0] - p[0], y: b.at[1] - p[1]}
  })
  bones.forEach((b, i) => { if (b.parent >= i) throw new Error('bone order: ' + b.name) })
  const setup = setupWorld(bones)
  const attachments: Armature['attachments'] = {}
  for (const part of def.parts) {
    const rect = rects.get(part)
    if (!rect) throw new Error('part not packed: ' + part.name)
    ;(attachments[part.slot] ??= {})[part.name] = buildMesh(part, page, rect, sheet, index, setup)
  }
  const slots = def.slots.map(s => {
    const bone = index.get(s.bone)
    if (bone === undefined) throw new Error('slot bone ' + s.bone)
    return {name: s.name, bone, attachment: s.attachment, shade: s.shade ?? 1}
  })
  return {bones, slots, attachments, setup}
}

function buildMesh(part: PartDef, page: number, rect: Rect, sheet: {width: number; height: number}, index: Map<string, number>, setup: Float32Array): MeshData {
  const [cols, rows] = part.grid ?? [2, 2]
  const [x0, y0, x1, y1] = part.box
  const boneIds = part.bones.map(n => {
    const i = index.get(n)
    if (i === undefined) throw new Error(`part ${part.name}: unknown bone ${n}`)
    return i
  })
  const uvs = new Float32Array(cols * rows * 2)
  const influences: Influence[][] = []
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const u = c / (cols - 1), v = r / (rows - 1)
    const mx = x0 + (x1 - x0) * u, my = y0 + (y1 - y0) * v
    const k = r * cols + c
    uvs[k * 2] = (rect.x + rect.w * u) / sheet.width
    uvs[k * 2 + 1] = (rect.y + rect.h * v) / sheet.height
    const pairs = boneIds.length === 1 || !part.joints ? [[0, 1] as [number, number]] : chainWeights(part.joints, mx, my)
    influences.push(pairs.map(([slot, w]) => {
      const b = boneIds[slot]
      return {bone: b, x: mx - setup[b * 6 + 4], y: my - setup[b * 6 + 5], w}
    }))
  }
  const tris: number[] = []
  for (let r = 0; r < rows - 1; r++) for (let c = 0; c < cols - 1; c++) {
    const a = r * cols + c, b = a + 1, d = a + cols, e = d + 1
    tris.push(a, b, d, b, e, d)
  }
  return {page, uvs, influences, triangles: new Uint16Array(tris)}
}

/** Physics chains of a compiled view, by chain name. */
export function makeChains(view: CompiledView): Map<string, SpringChain> {
  const out = new Map<string, SpringChain>()
  const index = new Map(view.armature.bones.map((b, i) => [b.name, i]))
  for (const c of view.def.chains) out.set(c.name, new SpringChain(c.bones.map(n => index.get(n) as number), c.tip, {...c.feel}))
  return out
}

/** Paints a character's sheet. */
export function paintSheet(sheet: Sheet, doc: Document = document): HTMLCanvasElement {
  const canvas = doc.createElement('canvas')
  canvas.width = sheet.width; canvas.height = sheet.height
  const g = canvas.getContext('2d') as CanvasRenderingContext2D
  for (const {part, rect} of sheet.placed) {
    g.save()
    g.beginPath(); g.rect(rect.x - PAD + 1, rect.y - PAD + 1, rect.w + PAD * 2 - 2, rect.h + PAD * 2 - 2); g.clip()
    g.translate(rect.x, rect.y)
    g.scale(PX, PX)
    g.translate(-part.box[0], -part.box[1])
    part.paint(g)
    g.restore()
  }
  return canvas
}

/** The shared particle sheet: 12 x 12 unit cells at 6 px per unit. */
export const FX_PX = 6
export function fxSheet(doc: Document = document): {canvas: HTMLCanvasElement; cells: Record<FxName, Rect>} {
  const cell = 12 * FX_PX + 4
  const canvas = doc.createElement('canvas')
  canvas.width = 1024; canvas.height = 128
  const g = canvas.getContext('2d') as CanvasRenderingContext2D
  const cells = {} as Record<FxName, Rect>
  FX.forEach((name, i) => {
    const x = i * cell + 2
    cells[name] = {x, y: 2, w: cell - 4, h: cell - 4}
    g.save(); g.translate(x + (cell - 4) / 2, 2 + (cell - 4) / 2); g.scale(FX_PX, FX_PX); paintFx(g, name); g.restore()
  })
  return {canvas, cells}
}
