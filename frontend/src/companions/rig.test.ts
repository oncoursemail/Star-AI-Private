import {describe, expect, it} from 'vitest'
import {CAST} from './cast'
import type {CastId} from './cast'
import {compileCharacter, makeChains} from './armature'
import {chainWeights, Skeleton, POSE_STRIDE} from './skeleton'
import {SpringChain} from './physics'
import {applyClip, sample} from './clips'
import type {Clip} from './clips'
import {CLIPS, MIRRORED, mirrorClip} from './animations'

const IDENTITY = [1, 0, 0, 1, 0, 0]
const characters = Object.fromEntries(CAST.map((id, i) => [id, compileCharacter(id, i)])) as Record<CastId, ReturnType<typeof compileCharacter>>

describe('armature and weighted meshes', () => {
  it('every slot of every view has its default attachment, weights sum to one, at most two bones', () => {
    for (const id of CAST) for (const view of ['front', 'side'] as const) {
      const a = characters[id].views[view].armature
      for (const slot of a.slots) if (slot.attachment) expect(a.attachments[slot.name]?.[slot.attachment], `${id} ${view} ${slot.name}`).toBeTruthy()
      for (const meshes of Object.values(a.attachments)) for (const mesh of Object.values(meshes)) {
        for (const inf of mesh.influences) {
          expect(inf.length).toBeLessThanOrEqual(2)
          expect(inf.reduce((s, f) => s + f.w, 0)).toBeCloseTo(1, 5)
        }
        for (const t of mesh.triangles) expect(t).toBeLessThan(mesh.influences.length)
      }
    }
  })

  it('the setup pose draws every layer exactly where it was painted', () => {
    const sk = new Skeleton(characters.gemini.views.front.armature)
    sk.updateWorld(IDENTITY)
    const part = characters.gemini.views.front.def.parts.find(p => p.name === 'armF')!
    const mesh = sk.data.attachments.armF.armF
    const out = new Float32Array(mesh.influences.length * 2)
    sk.skin(mesh, out)
    expect(out[0]).toBeCloseTo(part.box[0], 4)
    expect(out[1]).toBeCloseTo(part.box[1], 4)
    expect(out[out.length - 2]).toBeCloseTo(part.box[2], 4)
    expect(out[out.length - 1]).toBeCloseTo(part.box[3], 4)
  })

  it('bends a limb smoothly at the joint: no tearing and no long stretched edges', () => {
    for (const view of ['front', 'side'] as const) {
      const sk = new Skeleton(characters.ember.views[view].armature)
      sk.pose[sk.bone('armLF') * POSE_STRIDE] = Math.PI / 2
      sk.pose[sk.bone('shinF') * POSE_STRIDE] = Math.PI / 2
      sk.updateWorld(IDENTITY)
      for (const [slot, name] of [['armF', 'armF'], ['legF', 'legF']] as const) {
        const mesh = sk.data.attachments[slot][name]
        const out = new Float32Array(mesh.influences.length * 2)
        sk.skin(mesh, out)
        // Rest edge lengths vs bent edge lengths along each triangle.
        const rest = new Float32Array(out.length)
        const flat = new Skeleton(sk.data); flat.updateWorld(IDENTITY); flat.skin(mesh, rest)
        // Only the painted limb matters: vertices within its half width of the bone line.
        const joints = characters.ember.views[view].def.parts.find(p => p.name === name)!.joints!
        const onLimb = (v: number) => Math.min(...joints.slice(0, -1).map((j, k) => segDist(rest[v * 2], rest[v * 2 + 1], j, joints[k + 1]))) < 2.8
        for (let i = 0; i < mesh.triangles.length; i += 3) {
          const t = [mesh.triangles[i], mesh.triangles[i + 1], mesh.triangles[i + 2]]
          for (let k = 0; k < 3; k++) {
            const a = t[k], b = t[(k + 1) % 3]
            if (!onLimb(a) || !onLimb(b)) continue
            const bent = Math.hypot(out[a * 2] - out[b * 2], out[a * 2 + 1] - out[b * 2 + 1])
            const flatLen = Math.hypot(rest[a * 2] - rest[b * 2], rest[a * 2 + 1] - rest[b * 2 + 1])
            expect(bent, `${view} ${slot}`).toBeLessThan(flatLen * 1.6 + 0.01)
          }
        }
      }
    }
  })

  it('blends two bones half and half exactly at a joint', () => {
    const w = chainWeights([[0, 0], [0, 10], [0, 20]], 0, 10)
    expect(w).toHaveLength(2)
    expect(w[0][1]).toBeCloseTo(0.5)
    expect(chainWeights([[0, 0], [0, 10], [0, 20]], 0, 2)).toEqual([[0, 1]])
  })

  it('ears and tails hang from the head and hip bones, so they move with them', () => {
    for (const id of CAST) for (const view of ['front', 'side'] as const) {
      const a = characters[id].views[view].armature
      const parent = (name: string) => a.bones[a.bones[a.bones.findIndex(b => b.name === name)].parent].name
      for (const ear of ['catF0', 'catK0', 'dogF0']) expect(parent(ear)).toBe('head')
      expect(parent('tailCat0')).toBe('hips')
      expect(parent('tailDog0')).toBe('hips')
      const sk = new Skeleton(a)
      sk.updateWorld(IDENTITY)
      const before = sk.point(sk.bone('catF0'), ...setupAt(a, 'catF0'))
      sk.pose[sk.bone('head') * POSE_STRIDE] = 0.4
      sk.pose[sk.bone('hips') * POSE_STRIDE + 2] = -5
      sk.updateWorld(IDENTITY)
      // The ear root keeps its place on the head: same distance from the head pivot.
      const head = sk.point(sk.bone('head'), ...setupAt(a, 'head'))
      const after = sk.point(sk.bone('catF0'), ...setupAt(a, 'catF0'))
      const headBefore = setupAt(a, 'head')
      expect(Math.hypot(after[0] - head[0], after[1] - head[1])).toBeCloseTo(Math.hypot(before[0] - headBefore[0], before[1] - headBefore[1]), 4)
    }
  })

  it('Gemini has no hair clip any more; Star and Astra keep theirs', () => {
    expect(characters.gemini.views.front.armature.slots.some(s => s.name === 'clip')).toBe(false)
    expect(characters.star.views.front.armature.slots.some(s => s.name === 'clip')).toBe(true)
    expect(characters.astra.views.side.armature.slots.some(s => s.name === 'clip')).toBe(true)
  })
})

function segDist(x: number, y: number, a: readonly [number, number], b: readonly [number, number]) {
  const dx = b[0] - a[0], dy = b[1] - a[1], u = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)))
  return Math.hypot(x - a[0] - dx * u, y - a[1] - dy * u)
}

function setupAt(a: {setup: Float32Array; bones: {name: string}[]}, name: string): [number, number] {
  const i = a.bones.findIndex(b => b.name === name)
  return [a.setup[i * 6 + 4], a.setup[i * 6 + 5]]
}

describe('spring chains', () => {
  const setup = () => {
    const view = characters.gemini.views.side
    const sk = new Skeleton(view.armature)
    const chains = makeChains(view)
    return {sk, chain: chains.get('hair1') as SpringChain}
  }
  const tipX = (sk: Skeleton, chain: SpringChain) => sk.point(chain.bones[chain.bones.length - 1], ...chain.tip)[0]
  const run = (sk: Skeleton, chain: SpringChain, seconds: number, dt: number, x: (t: number) => number) => {
    let t = 0
    while (t < seconds) {
      t += dt
      sk.resetPose()
      const root = [1, 0, 0, 1, x(t), 0]
      sk.updateWorld(root)
      chain.apply(sk, root, dt, 1)
    }
  }

  it('rests where the animation puts it (gravity only bends it a little)', () => {
    const {sk, chain} = setup()
    run(sk, chain, 3, 1 / 60, () => 0)
    sk.updateWorld(IDENTITY)
    const rest = tipX(sk, chain)
    run(sk, chain, 2, 1 / 60, () => 0)
    expect(Math.abs(tipX(sk, chain) - rest)).toBeLessThan(0.05)
  })

  it('trails behind a move, overshoots on the stop, and settles again', () => {
    const {sk, chain} = setup()
    run(sk, chain, 2, 1 / 60, () => 0)
    const still = tipX(sk, chain)
    // Walk right at 50 units/s for half a second: the tip lags (left of where it hangs at rest).
    let lag = Infinity
    for (let i = 1; i <= 30; i++) { run(sk, chain, 1 / 60, 1 / 60, () => i * 50 / 60); lag = Math.min(lag, tipX(sk, chain) - (still + i * 50 / 60)) }
    expect(lag).toBeLessThan(-0.8)
    // Stop: after a moment it swings past its rest place, then settles.
    let peak = -Infinity
    for (let i = 0; i < 40; i++) { run(sk, chain, 1 / 60, 1 / 60, () => 25); peak = Math.max(peak, tipX(sk, chain) - (still + 25)) }
    expect(peak).toBeGreaterThan(0.2)
    run(sk, chain, 4, 1 / 60, () => 25)
    expect(Math.abs(tipX(sk, chain) - (still + 25))).toBeLessThan(0.3)
  })

  it('is stable at any frame rate', () => {
    for (const dt of [1 / 30, 1 / 60, 1 / 144, 0.1]) {
      const {sk, chain} = setup()
      run(sk, chain, 3, dt, t => Math.sin(t * 7) * 30)
      for (const v of sk.world) expect(Number.isFinite(v)).toBe(true)
      expect(Math.abs(tipX(sk, chain))).toBeLessThan(120)
    }
  })
})

describe('clips', () => {
  it('passes through its keys and loops seamlessly', () => {
    const track = [0, 10, 0.5, -10]
    expect(sample(track, 0, true, true)).toBeCloseTo(10)
    expect(sample(track, 0.5, true, true)).toBeCloseTo(-10)
    expect(sample(track, 0.999, true, true)).toBeCloseTo(sample(track, 0, true, true), 0)
    expect(sample([0, 0, 1, 10], 0.5, false, false)).toBeCloseTo(5)
  })

  it('only names bones and slots that exist', () => {
    const front = characters.astra.views.front.armature, side = characters.astra.views.side.armature
    const bones = new Set([...front.bones, ...side.bones].map(b => b.name))
    const slots = new Set([...front.slots, ...side.slots].map(s => s.name))
    const all: Record<string, Clip> = {...CLIPS, ...Object.fromEntries(Object.entries(MIRRORED).map(([k, v]) => [k + 'M', v]))}
    for (const [name, clip] of Object.entries(all)) {
      for (const bone of Object.keys(clip.bones)) expect(bones.has(bone), `${name}: ${bone}`).toBe(true)
      for (const slot of Object.keys(clip.slots ?? {})) expect(slots.has(slot), `${name}: ${slot}`).toBe(true)
    }
  })

  it('mirrors a two-character clip to the other side', () => {
    const m = mirrorClip(CLIPS.hugGive)
    expect(m.bones.armUF?.r?.[3]).toBe(-(CLIPS.hugGive.bones.armUK.r[3]))
    expect(m.slots?.lashK?.[1][1]).toBe('happyK')
    expect(m.slots?.lashF?.[1][1]).toBe('happyF')
  })

  it('walks with real steps: the front foot leads at its contact key, the back foot half a cycle later', () => {
    const sk = new Skeleton(characters.star.views.side.armature)
    const foot = (name: string) => sk.point(sk.bone(name), 0.5, 0)[0]
    for (const [u, lead] of [[0, 'footF'], [0.5, 'footK']] as const) {
      sk.resetPose()
      applyClip(sk, CLIPS.walk, u, 1)
      sk.updateWorld(IDENTITY)
      const other = lead === 'footF' ? 'footK' : 'footF'
      expect(foot(lead) - foot(other)).toBeGreaterThan(8)
    }
    // Passing: the feet pass each other.
    sk.resetPose(); applyClip(sk, CLIPS.walk, 0.25, 1); sk.updateWorld(IDENTITY)
    expect(Math.abs(foot('footF') - foot('footK'))).toBeLessThan(8)
  })
})
