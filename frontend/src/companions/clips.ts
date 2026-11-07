/**
 * Keyframed clips: per-bone tracks of rotation (degrees), offset (model units) and scale, plus slot
 * attachment keys (eyes, mouth, hands). Loops use a Catmull-Rom spline through the keys so a cycle
 * flows; one-shots ease in and out of every key (anticipation and settle come from the keys).
 */
import {POSE_STRIDE} from './skeleton'
import type {Skeleton} from './skeleton'

/** Flat [time, value, time, value, ...] with times in 0..1 of the clip. */
export type Track = readonly number[]
export type BoneTracks = { r?: Track; x?: Track; y?: Track; sx?: Track; sy?: Track }
export type Clip = {
  dur: number
  loop: boolean
  /** 'spline' (smooth through keys) or 'ease' (ease in-out per segment). */
  interp?: 'spline' | 'ease'
  /** Draw the arms over the head (raised arms in the front view). */
  armsUp?: boolean
  bones: Readonly<Record<string, BoneTracks>>
  /** Attachment switches: [time, name | null] in order. */
  slots?: Readonly<Record<string, readonly (readonly [number, string | null])[]>>
}

const DEG = Math.PI / 180
const easeInOut = (t: number) => t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2

/** Track value at normalised time u (0..1). */
export function sample(track: Track, u: number, loop: boolean, spline: boolean): number {
  const n = track.length / 2
  if (n === 0) return 0
  if (n === 1) return track[1]
  if (u <= track[0] && !loop) return track[1]
  if (u >= track[(n - 1) * 2] && !loop) return track[n * 2 - 1]
  // Find the segment [i, i + 1] around u (wrapping for loops).
  let i = n - 1
  for (let k = 0; k < n; k++) if (track[k * 2] <= u) i = k
  const t0 = track[i * 2]
  let j = i + 1, t1: number
  if (j >= n) { j = 0; t1 = track[0] + 1 } else t1 = track[j * 2]
  let uu = u
  if (uu < t0) uu += 1
  const s = t1 > t0 ? (uu - t0) / (t1 - t0) : 0
  const v1 = track[i * 2 + 1], v2 = track[j * 2 + 1]
  if (!spline) return v1 + (v2 - v1) * easeInOut(s)
  const at = (k: number) => {
    if (loop) return track[(((k % n) + n) % n) * 2 + 1]
    return track[Math.min(n - 1, Math.max(0, k)) * 2 + 1]
  }
  const v0 = at(i - 1), v3 = at(i + 2)
  const s2 = s * s, s3 = s2 * s
  return 0.5 * (2 * v1 + (-v0 + v2) * s + (2 * v0 - 5 * v1 + 4 * v2 - v3) * s2 + (-v0 + 3 * v1 - 3 * v2 + v3) * s3)
}

/** Adds `weight` x the clip at `time` seconds to the skeleton's pose deltas; sets attachments when weight >= 0.5. */
export function applyClip(sk: Skeleton, clip: Clip, time: number, weight: number) {
  const u = clip.loop ? ((time / clip.dur) % 1 + 1) % 1 : Math.min(1, Math.max(0, time / clip.dur))
  const spline = (clip.interp ?? (clip.loop ? 'spline' : 'ease')) === 'spline'
  for (const name in clip.bones) {
    const b = sk.bone(name)
    if (b < 0) continue
    const t = clip.bones[name], o = b * POSE_STRIDE
    if (t.r) sk.pose[o] += sample(t.r, u, clip.loop, spline) * DEG * weight
    if (t.x) sk.pose[o + 1] += sample(t.x, u, clip.loop, spline) * weight
    if (t.y) sk.pose[o + 2] += sample(t.y, u, clip.loop, spline) * weight
    if (t.sx) sk.pose[o + 3] += (sample(t.sx, u, clip.loop, spline) - 1) * weight
    if (t.sy) sk.pose[o + 4] += (sample(t.sy, u, clip.loop, spline) - 1) * weight
  }
  if (clip.slots && weight >= 0.5) {
    for (const slot in clip.slots) {
      const keys = clip.slots[slot]
      let value: string | null | undefined
      for (const [t, name] of keys) if (t <= u) value = name
      if (value !== undefined) sk.setAttachment(slot, value)
    }
  }
}

/** Plays one clip at a time and cross-fades to the next. */
export class ClipPlayer {
  clip: Clip | null = null
  time = 0
  private prev: Clip | null = null
  private prevTime = 0
  private fade = 0
  private fadeLen = 0.18

  play(clip: Clip, fade = 0.18, from = 0) {
    if (clip === this.clip) return
    if (this.clip && fade > 0) { this.prev = this.clip; this.prevTime = this.time; this.fade = 0; this.fadeLen = fade } else this.prev = null
    this.clip = clip
    this.time = from
  }

  advance(dt: number) {
    this.time += dt
    if (this.prev) { this.prevTime += dt; this.fade += dt; if (this.fade >= this.fadeLen) this.prev = null }
  }

  apply(sk: Skeleton, weight = 1) {
    if (!this.clip) return
    if (this.prev) {
      const w = Math.min(1, this.fade / this.fadeLen)
      applyClip(sk, this.prev, this.prevTime, (1 - w) * weight)
      applyClip(sk, this.clip, this.time, w * weight)
    } else applyClip(sk, this.clip, this.time, weight)
  }

  get done() { return !!this.clip && !this.clip.loop && this.time >= this.clip.dur }
}
