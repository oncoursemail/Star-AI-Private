import {BONE, BONE_COUNT} from './rig'
import type {Pt, Rig} from './rig'

export type PuppetMesh = {
  /** x, y rest position in sprite px. */
  positions: Float32Array
  /** u, v in 0..1 of the sprite. */
  uvs: Float32Array
  /** BONE_COUNT weights per vertex; each vertex sums to 1. */
  weights: Float32Array
  indices: Uint16Array
  vertexCount: number
}

const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)))
  return t * t * (3 - 2 * t)
}

/** Signed distance to a polygon in px: positive inside. */
export function polygonDistance(poly: readonly Pt[], x: number, y: number): number {
  let inside = false
  let best = Infinity
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j]
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside
    const dx = xi - xj, dy = yi - yj
    const t = Math.max(0, Math.min(1, ((x - xj) * dx + (y - yj) * dy) / (dx * dx + dy * dy || 1)))
    best = Math.min(best, Math.hypot(x - (xj + t * dx), y - (yj + t * dy)))
  }
  return inside ? best : -best
}

/**
 * Bone weights for one point: a vertical split (head / torso / skirt / legs) with soft bands,
 * then each painted region (hair masses, arms, ears, tail) overrides what lies under it.
 */
export function pointWeights(rig: Rig, x: number, y: number, out = new Float32Array(BONE_COUNT)): Float32Array {
  out.fill(0)
  const head = 1 - smooth(rig.neck[1] - 8, rig.neck[1] + 8, y)
  const rest = 1 - head
  let hips = rest * smooth(rig.waistY - 12, rig.waistY + 12, y)
  const torso = rest - hips
  const legs = hips * smooth(rig.hemY - 10, rig.hemY + 14, y)
  hips -= legs
  const mid = (rig.hipL[0] + rig.hipR[0]) / 2
  const right = smooth(mid - 6, mid + 6, x)
  out[BONE.head] = head
  out[BONE.torso] = torso
  out[BONE.hips] = hips
  out[BONE.legL] = legs * (1 - right)
  out[BONE.legR] = legs * right
  for (const region of rig.regions) {
    const m = smooth(-region.feather / 2, region.feather / 2, polygonDistance(region.poly, x, y))
    if (m <= 0) continue
    for (let b = 0; b < BONE_COUNT; b++) out[b] *= 1 - m
    out[region.bone] += m
  }
  return out
}

/**
 * A regular grid over the figure, cell size `step` px. Cells whose pixels are all transparent
 * (per `opaque`) are left out, so the GPU never shades empty sprite area.
 */
export function buildPuppetMesh(rig: Rig, step = 9, opaque: (x0: number, y0: number, x1: number, y1: number) => boolean = () => true): PuppetMesh {
  const [w, h] = rig.size
  const cols = Math.ceil(w / step), rows = Math.ceil(h / step)
  const vx = cols + 1, vy = rows + 1
  const positions = new Float32Array(vx * vy * 2)
  const uvs = new Float32Array(vx * vy * 2)
  const weights = new Float32Array(vx * vy * BONE_COUNT)
  const scratch = new Float32Array(BONE_COUNT)
  for (let j = 0; j < vy; j++) {
    for (let i = 0; i < vx; i++) {
      const k = j * vx + i
      const x = Math.min(w, i * step), y = Math.min(h, j * step)
      positions[k * 2] = x; positions[k * 2 + 1] = y
      uvs[k * 2] = x / w; uvs[k * 2 + 1] = y / h
      weights.set(pointWeights(rig, x, y, scratch), k * BONE_COUNT)
    }
  }
  const tris: number[] = []
  for (let j = 0; j < rows; j++) {
    for (let i = 0; i < cols; i++) {
      if (!opaque(i * step - 1, j * step - 1, (i + 1) * step + 1, (j + 1) * step + 1)) continue
      const a = j * vx + i, b = a + 1, c = a + vx, d = c + 1
      tris.push(a, c, b, b, c, d)
    }
  }
  return {positions, uvs, weights, indices: new Uint16Array(tris), vertexCount: vx * vy}
}
