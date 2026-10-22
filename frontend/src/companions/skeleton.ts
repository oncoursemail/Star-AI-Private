/**
 * A small 2D skeletal runtime in the DragonBones/Spine mould: bones with local transforms, slots in draw
 * order, and weighted mesh attachments (each vertex keeps its position in the space of up to two bones,
 * so limbs, hair and skirts bend smoothly at the joints instead of breaking or stretching).
 * Matrices are 2D affine [a, b, c, d, tx, ty]: x' = a x + c y + tx, y' = b x + d y + ty.
 */
export type Mat = Float32Array | number[]

export type BoneData = { name: string; parent: number; x: number; y: number }
/** One bone's share of a vertex: the vertex position in that bone's setup space, and its weight. */
export type Influence = { bone: number; x: number; y: number; w: number }
export type MeshData = {
  /** Atlas page (one per character, one shared) and the vertex texture coordinates (0..1). */
  page: number
  uvs: Float32Array
  influences: Influence[][]
  triangles: Uint16Array
}
export type SlotData = {
  name: string
  bone: number
  attachment: string | null
  /** Colour multiplier, e.g. the far limbs are a touch darker. */
  shade: number
}
export type Armature = {
  bones: BoneData[]
  slots: SlotData[]
  attachments: Record<string, Record<string, MeshData>>
  /** Setup world matrices (model units). */
  setup: Float32Array
}

export const IDENTITY = (): Float32Array => new Float32Array([1, 0, 0, 1, 0, 0])

export function mul(m: Mat, n: Mat, out: Mat, o = 0) {
  const a = m[0] * n[0] + m[2] * n[1], b = m[1] * n[0] + m[3] * n[1]
  const c = m[0] * n[2] + m[2] * n[3], d = m[1] * n[2] + m[3] * n[3]
  const tx = m[0] * n[4] + m[2] * n[5] + m[4], ty = m[1] * n[4] + m[3] * n[5] + m[5]
  out[o] = a; out[o + 1] = b; out[o + 2] = c; out[o + 3] = d; out[o + 4] = tx; out[o + 5] = ty
  return out
}

export function invert(m: Mat, out: Mat = new Float32Array(6)): Mat {
  const det = m[0] * m[3] - m[1] * m[2] || 1e-9
  const a = m[3] / det, b = -m[1] / det, c = -m[2] / det, d = m[0] / det
  out[0] = a; out[1] = b; out[2] = c; out[3] = d
  out[4] = -(a * m[4] + c * m[5]); out[5] = -(b * m[4] + d * m[5])
  return out
}

/** Setup world matrices: bones carry no rotation in the setup pose, so these are translations. */
export function setupWorld(bones: readonly BoneData[]): Float32Array {
  const out = new Float32Array(bones.length * 6)
  bones.forEach((bone, i) => {
    const px = bone.parent >= 0 ? out[bone.parent * 6 + 4] : 0, py = bone.parent >= 0 ? out[bone.parent * 6 + 5] : 0
    out.set([1, 0, 0, 1, px + bone.x, py + bone.y], i * 6)
  })
  return out
}

/** Pose deltas per bone: rotation (radians), x, y, scale x - 1, scale y - 1. */
export const POSE_STRIDE = 5

export class Skeleton {
  readonly count: number
  /** Animated deltas on top of the setup pose; reset every frame by the animator. */
  readonly pose: Float32Array
  readonly world: Float32Array
  readonly attachment: (string | null)[]
  readonly alpha: Float32Array
  private readonly index = new Map<string, number>()
  private readonly slotIndex = new Map<string, number>()

  constructor(readonly data: Armature) {
    this.count = data.bones.length
    this.pose = new Float32Array(this.count * POSE_STRIDE)
    this.world = new Float32Array(this.count * 6)
    data.bones.forEach((b, i) => this.index.set(b.name, i))
    data.slots.forEach((s, i) => this.slotIndex.set(s.name, i))
    this.attachment = data.slots.map(s => s.attachment)
    this.alpha = new Float32Array(data.slots.length).fill(1)
  }

  bone(name: string): number { return this.index.get(name) ?? -1 }
  slot(name: string): number { return this.slotIndex.get(name) ?? -1 }

  resetPose() {
    this.pose.fill(0)
    this.data.slots.forEach((s, i) => { this.attachment[i] = s.attachment; this.alpha[i] = 1 })
  }

  setAttachment(slot: string, name: string | null) {
    const i = this.slot(slot)
    if (i >= 0) this.attachment[i] = name
  }

  /** Bone world matrices under `root` (model units to stage px). Bones are stored parents first. */
  updateWorld(root: Mat, from = 0) {
    const bones = this.data.bones, pose = this.pose, world = this.world
    const local = [0, 0, 0, 0, 0, 0]
    for (let i = from; i < this.count; i++) this.updateBone(i, root, local, bones, pose, world)
  }

  /** Recompute one bone from its parent (used by the physics chains bone by bone). */
  updateBone(i: number, root: Mat, local: number[] = [0, 0, 0, 0, 0, 0], bones = this.data.bones, pose = this.pose, world = this.world) {
    const bone = bones[i], p = i * POSE_STRIDE
    const r = pose[p], sx = 1 + pose[p + 3], sy = 1 + pose[p + 4]
    const cos = Math.cos(r), sin = Math.sin(r)
    local[0] = cos * sx; local[1] = sin * sx; local[2] = -sin * sy; local[3] = cos * sy
    local[4] = bone.x + pose[p + 1]; local[5] = bone.y + pose[p + 2]
    if (bone.parent < 0) mul(root, local, world, i * 6)
    else mul(world.subarray(bone.parent * 6, bone.parent * 6 + 6), local, world, i * 6)
  }

  /** A point given in model units (setup space) carried by a bone, in stage px. */
  point(bone: number, mx: number, my: number): [number, number] {
    const s = this.data.setup, w = this.world, o = bone * 6
    const lx = mx - s[o + 4], ly = my - s[o + 5]
    return [w[o] * lx + w[o + 2] * ly + w[o + 4], w[o + 1] * lx + w[o + 3] * ly + w[o + 5]]
  }

  /** Writes the skinned positions of one mesh into `out` (x, y pairs) and returns the vertex count. */
  skin(mesh: MeshData, out: Float32Array, offset = 0): number {
    const w = this.world
    const n = mesh.influences.length
    for (let v = 0; v < n; v++) {
      let x = 0, y = 0
      for (const f of mesh.influences[v]) {
        const o = f.bone * 6
        x += (w[o] * f.x + w[o + 2] * f.y + w[o + 4]) * f.w
        y += (w[o + 1] * f.x + w[o + 3] * f.y + w[o + 5]) * f.w
      }
      out[offset + v * 2] = x
      out[offset + v * 2 + 1] = y
    }
    return n
  }
}

/** Joint-blend width as a share of a segment: 50/50 at the joint, one bone only past this. */
const BLEND = 0.38
const smooth = (t: number) => t * t * (3 - 2 * t)

/**
 * Weights for a point along a chain of bones: joints[i] is where bone i starts, joints[n] is the tip.
 * Returns up to two [bone slot, weight] pairs (slot = index into `joints` segments).
 */
export function chainWeights(joints: readonly (readonly [number, number])[], x: number, y: number): [number, number][] {
  const n = joints.length - 1
  if (n <= 1) return [[0, 1]]
  let best = 0, bestU = 0, bestD = Infinity
  for (let k = 0; k < n; k++) {
    const [ax, ay] = joints[k], [bx, by] = joints[k + 1]
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy || 1e-9
    const u = ((x - ax) * dx + (y - ay) * dy) / len2
    const cu = Math.min(1, Math.max(0, u))
    const d = Math.hypot(x - (ax + dx * cu), y - (ay + dy * cu))
    if (d < bestD - 1e-9) { bestD = d; best = k; bestU = u }
  }
  const u = bestU
  if (u < BLEND && best > 0) {
    const w = 0.5 + 0.5 * smooth(Math.max(0, u) / BLEND)
    return [[best, w], [best - 1, 1 - w]]
  }
  if (u > 1 - BLEND && best < n - 1) {
    const w = 0.5 + 0.5 * smooth(Math.max(0, 1 - u) / BLEND)
    return [[best, w], [best + 1, 1 - w]]
  }
  return [[best, 1]]
}
