import {BONE, BONE_COUNT} from './rig'
import type {BoneIndex, Pt, Rig} from './rig'

/**
 * One frame of a puppet. Angles in radians, offsets in sprite px.
 * (x, y) is where the sprite point (anchorX, anchorY) lands on the stage (CSS px).
 */
export type Pose = {
  x: number; y: number; anchorX: number; anchorY: number
  scale: number
  /** Horizontal scale sign and squeeze: 1 = the art's own facing (left), -1 = mirrored. */
  flip: number
  /** Squash and stretch: >1 tall and thin, <1 short and wide (area kept). */
  stretch: number
  rot: number
  bodyY: number; hipsRot: number; torsoRot: number; breath: number
  headRot: number; headX: number; headY: number
  hairL: number; hairR: number; armL: number; armR: number
  legLRot: number; legRRot: number; legLLift: number; legRLift: number
  /** Leg height factor for sitting (1 = standing). */
  legSy: number
  tail: number; earL: number; earR: number
}

export const restPose = (rig: Rig): Pose => ({
  x: 0, y: 0, anchorX: rig.centerX, anchorY: rig.footY, scale: 1, flip: 1, stretch: 1, rot: 0,
  bodyY: 0, hipsRot: 0, torsoRot: 0, breath: 1, headRot: 0, headX: 0, headY: 0,
  hairL: 0, hairR: 0, armL: 0, armR: 0, legLRot: 0, legRRot: 0, legLLift: 0, legRLift: 0, legSy: 1,
  tail: 0, earL: 0, earR: 0,
})


/** 2x3 affines [a, b, c, d, tx, ty]: x' = a x + c y + tx, y' = b x + d y + ty. */
export function multiply(m: ArrayLike<number>, n: ArrayLike<number>, out: number[] = []): number[] {
  const a = m[0] * n[0] + m[2] * n[1], b = m[1] * n[0] + m[3] * n[1]
  const c = m[0] * n[2] + m[2] * n[3], d = m[1] * n[2] + m[3] * n[3]
  const tx = m[0] * n[4] + m[2] * n[5] + m[4], ty = m[1] * n[4] + m[3] * n[5] + m[5]
  out[0] = a; out[1] = b; out[2] = c; out[3] = d; out[4] = tx; out[5] = ty
  return out
}

/** Rotate by `angle` and scale by (sx, sy) about `pivot`, then move by (dx, dy). */
export function around(pivot: Pt, angle: number, sx = 1, sy = 1, dx = 0, dy = 0): number[] {
  const cos = Math.cos(angle), sin = Math.sin(angle)
  const a = cos * sx, b = sin * sx, c = -sin * sy, d = cos * sy
  return [a, b, c, d, pivot[0] + dx - (a * pivot[0] + c * pivot[1]), pivot[1] + dy - (b * pivot[0] + d * pivot[1])]
}

export function apply(m: ArrayLike<number>, x: number, y: number): [number, number] {
  return [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]
}

const regionPivot = (rig: Rig, bone: BoneIndex, fallback: Pt): Pt =>
  rig.regions.find(region => region.bone === bone)?.pivot ?? fallback

/** The sprite-to-stage transform of the whole puppet. */
export function rootMatrix(pose: Pose): number[] {
  const sy = pose.scale * pose.stretch
  const sx = pose.scale / Math.sqrt(Math.max(0.2, pose.stretch)) * pose.flip
  const cos = Math.cos(pose.rot), sin = Math.sin(pose.rot)
  const a = cos * sx, b = sin * sx, c = -sin * sy, d = cos * sy
  return [a, b, c, d, pose.x - (a * pose.anchorX + c * pose.anchorY), pose.y - (b * pose.anchorX + d * pose.anchorY)]
}

/** World matrices of all bones (6 floats each), sprite px to stage px. */
export function computeBones(rig: Rig, pose: Pose, out = new Float32Array(BONE_COUNT * 6)): Float32Array {
  const root = rootMatrix(pose)
  const waist: Pt = [rig.centerX, rig.waistY]
  const hips = multiply(root, around(waist, pose.hipsRot, 1, 1, 0, pose.bodyY))
  const torso = multiply(hips, around([rig.centerX, rig.waistY + 6], pose.torsoRot, 1, pose.breath))
  const head = multiply(torso, around(rig.neck, pose.headRot, 1, 1, pose.headX, pose.headY))
  const leg = (hip: Pt, rot: number, lift: number) => {
    const foot: Pt = [hip[0], rig.footY]
    return multiply(root, multiply(around(hip, rot, 1, 1, 0, -lift), around(foot, 0, 1, pose.legSy)))
  }
  const put = (bone: BoneIndex, m: ArrayLike<number>) => { for (let i = 0; i < 6; i++) out[bone * 6 + i] = m[i] }
  put(BONE.hips, hips)
  put(BONE.torso, torso)
  put(BONE.head, head)
  put(BONE.hairL, multiply(head, around(regionPivot(rig, BONE.hairL, rig.neck), pose.hairL)))
  put(BONE.hairR, multiply(head, around(regionPivot(rig, BONE.hairR, rig.neck), pose.hairR)))
  put(BONE.armL, multiply(torso, around(rig.shoulderL, pose.armL)))
  put(BONE.armR, multiply(torso, around(rig.shoulderR, pose.armR)))
  put(BONE.legL, leg(rig.hipL, pose.legLRot, pose.legLLift))
  put(BONE.legR, leg(rig.hipR, pose.legRRot, pose.legRLift))
  put(BONE.tail, multiply(hips, around(regionPivot(rig, BONE.tail, rig.tailRoot), pose.tail)))
  put(BONE.earL, multiply(head, around(regionPivot(rig, BONE.earL, rig.head), pose.earL)))
  put(BONE.earR, multiply(head, around(regionPivot(rig, BONE.earR, rig.head), pose.earR)))
  return out
}
