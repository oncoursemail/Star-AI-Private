/**
 * Spring chains for the parts that should move on their own: hair strands, animal ears, tails, skirt
 * and cape. Each joint is a Verlet point pulled toward where the animation puts it, kept at its bone
 * length, with gravity and drag. The chain's bones are then turned to follow the points, so the parts
 * trail behind steps, overshoot on stops and bounce on hops. Works in stage px (after the root
 * transform), so walking across the screen is what makes the hair lag.
 */
import type {Mat, Skeleton} from './skeleton'

export type ChainFeel = {
  /** Pull toward the animated pose, 1/s^2, at the root joint; `tip` scales it at the last joint. */
  stiffness: number
  tip: number
  /** Velocity kept per 1/120 s step (0..1, lower is calmer). */
  keep: number
  /** Gravity in model units/s^2 (scaled to px by the caller). */
  gravity: number
  /** Largest turn away from the animated pose per bone, radians. */
  limit: number
  /** Share of a sudden body move the joints resist (0 = carried along, 1 = full lag). */
  inertia?: number
}

const STEP = 1 / 120
const wrap = (a: number) => a - Math.PI * 2 * Math.round(a / (Math.PI * 2))

export class SpringChain {
  /** Simulated joints 1..n (joint 0 is pinned to the first bone), current and previous positions. */
  private p: Float32Array
  private q: Float32Array
  private target: Float32Array
  private ready = false
  private carry = 0
  private rootX = 0
  private rootY = 0

  /**
   * @param bones chain bones, each the parent of the next
   * @param tip the chain's end point in model units (setup space)
   */
  constructor(readonly bones: readonly number[], readonly tip: readonly [number, number], public feel: ChainFeel) {
    const n = bones.length
    this.p = new Float32Array(n * 2 + 2)
    this.q = new Float32Array(n * 2 + 2)
    this.target = new Float32Array(n * 2 + 2)
  }

  reset() { this.ready = false }

  /** Joint i of the animated pose (i = n is the tip). */
  private joint(sk: Skeleton, i: number): [number, number] {
    const n = this.bones.length
    if (i < n) { const o = this.bones[i] * 6; return [sk.world[o + 4], sk.world[o + 5]] }
    return sk.point(this.bones[n - 1], this.tip[0], this.tip[1])
  }

  /** Simulate `dt` seconds and bend the bones. Call after `sk.updateWorld(root)`. */
  apply(sk: Skeleton, root: Mat, dt: number, unit: number) {
    const n = this.bones.length, p = this.p, q = this.q, t = this.target
    for (let i = 0; i <= n; i++) { const [x, y] = this.joint(sk, i); t[i * 2] = x; t[i * 2 + 1] = y }
    if (!this.ready) { p.set(t); q.set(t); this.ready = true; this.carry = 0; this.rootX = t[0]; this.rootY = t[1] }
    // A big jump (picked up, placed, a new view) restarts the chain; otherwise part of the body's move
    // is carried straight to the joints, so a fast drag swings the hair without flinging it.
    const mx = t[0] - this.rootX, my = t[1] - this.rootY
    this.rootX = t[0]; this.rootY = t[1]
    if (Math.hypot(mx, my) > unit * 40) { p.set(t); q.set(t) }
    else {
      const carry = 1 - (this.feel.inertia ?? 0.5)
      for (let i = 1; i <= n; i++) { p[i * 2] += mx * carry; p[i * 2 + 1] += my * carry; q[i * 2] += mx * carry; q[i * 2 + 1] += my * carry }
    }
    const {stiffness, tip, keep, gravity} = this.feel
    const vmax = unit * 3
    const g = gravity * unit * STEP * STEP
    this.carry = Math.min(this.carry + dt, 0.1)
    while (this.carry >= STEP) {
      this.carry -= STEP
      p[0] = t[0]; p[1] = t[1]; q[0] = t[0]; q[1] = t[1]
      for (let i = 1; i <= n; i++) {
        const k = stiffness * (1 + (tip - 1) * (i - 1) / Math.max(1, n - 1)) * STEP * STEP
        const x = p[i * 2], y = p[i * 2 + 1]
        // Velocity per step, capped so nothing whips around.
        let vx = (x - q[i * 2]) * keep, vy = (y - q[i * 2 + 1]) * keep
        const sp = Math.hypot(vx, vy)
        if (sp > vmax) { vx *= vmax / sp; vy *= vmax / sp }
        p[i * 2] = x + vx + (t[i * 2] - x) * k
        p[i * 2 + 1] = y + vy + (t[i * 2 + 1] - y) * k + g
        q[i * 2] = x; q[i * 2 + 1] = y
      }
      // Keep every link at its animated length (the length follows squash and the poof scale).
      for (let i = 1; i <= n; i++) {
        const len = Math.hypot(t[i * 2] - t[i * 2 - 2], t[i * 2 + 1] - t[i * 2 - 1])
        const dx = p[i * 2] - p[i * 2 - 2], dy = p[i * 2 + 1] - p[i * 2 - 1]
        const d = Math.hypot(dx, dy) || 1e-6
        p[i * 2] = p[i * 2 - 2] + dx / d * len
        p[i * 2 + 1] = p[i * 2 - 1] + dy / d * len
      }
    }
    // Turn each bone toward its simulated child joint, root first, refreshing the bones below it.
    const local = [0, 0, 0, 0, 0, 0]
    for (let i = 0; i < n; i++) {
      const b = this.bones[i], o = b * 6
      const [jx, jy] = [sk.world[o + 4], sk.world[o + 5]]
      const [cx, cy] = this.joint(sk, i + 1)
      const want = Math.atan2(p[i * 2 + 3] - jy, p[i * 2 + 2] - jx)
      const have = Math.atan2(cy - jy, cx - jx)
      let delta = wrap(want - have)
      delta = Math.max(-this.feel.limit, Math.min(this.feel.limit, delta))
      // A mirrored parent turns the other way.
      const parent = sk.data.bones[b].parent
      const m = parent >= 0 ? sk.world.subarray(parent * 6, parent * 6 + 6) : root
      const mirrored = m[0] * m[3] - m[1] * m[2] < 0
      sk.pose[b * 5] += mirrored ? -delta : delta
      for (let j = i; j < n; j++) sk.updateBone(this.bones[j], root, local)
    }
  }
}
