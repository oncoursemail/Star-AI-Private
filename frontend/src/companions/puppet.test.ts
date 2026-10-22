import {describe, expect, it} from 'vitest'
import {BONE, BONE_COUNT, CAST, RIGS, figureHeight} from './rig'
import {buildPuppetMesh, pointWeights, polygonDistance} from './mesh'
import {apply, computeBones, restPose} from './pose'
import {Animator} from './animator'
import {createWorld} from './director'
import type {Actor, StageEnv} from './director'

const env = (over: Partial<StageEnv> = {}): StageEnv => ({
  platforms: [{id: 'floor', x0: 0, x1: 1000, y: 500}], size: 92, app: 'idle', study: false, night: false, affection: true,
  forms: {star: 'normal', ember: 'normal', astra: 'normal', gemini: 'normal'}, still: false, ...over,
})

describe('puppet rigs and meshes', () => {
  it.each(CAST)('%s: every vertex weight sums to 1 and regions own their bones', id => {
    const rig = RIGS[id]
    const mesh = buildPuppetMesh(rig)
    for (let v = 0; v < mesh.vertexCount; v++) {
      let sum = 0
      for (let b = 0; b < BONE_COUNT; b++) sum += mesh.weights[v * BONE_COUNT + b]
      expect(sum).toBeCloseTo(1, 4)
    }
    for (const region of rig.regions) {
      const [x, y] = region.poly.reduce(([a, b], [px, py]) => [a + px / region.poly.length, b + py / region.poly.length], [0, 0])
      if (polygonDistance(region.poly, x, y) > region.feather) expect(pointWeights(rig, x, y)[region.bone]).toBeGreaterThan(0.9)
    }
    expect(pointWeights(rig, rig.head[0], rig.head[1])[BONE.head]).toBeGreaterThan(0.9)
    expect(pointWeights(rig, rig.hipL[0], rig.footY - 10)[BONE.legL]).toBeGreaterThan(0.9)
  })

  it('drops fully transparent cells from the mesh', () => {
    const rig = RIGS.ember
    const all = buildPuppetMesh(rig).indices.length
    const half = buildPuppetMesh(rig, 9, (x0) => x0 < rig.size[0] / 2).indices.length
    expect(half).toBeLessThan(all * 0.6)
  })

  it('the rest pose maps the feet anchor to the stage point, and mirroring flips around it', () => {
    const rig = RIGS.astra
    const pose = {...restPose(rig), x: 300, y: 400, scale: 0.2}
    const bones = computeBones(rig, pose)
    const head = bones.subarray(BONE.head * 6, BONE.head * 6 + 6)
    const [fx, fy] = apply(head, rig.centerX, rig.footY)
    expect(fx).toBeCloseTo(300, 3)
    expect(fy).toBeCloseTo(400, 3)
    const [hx] = apply(head, rig.centerX + 50, rig.footY)
    const mirrored = computeBones(rig, {...pose, flip: -1}).subarray(BONE.head * 6, BONE.head * 6 + 6)
    expect(apply(mirrored, rig.centerX + 50, rig.footY)[0]).toBeCloseTo(600 - hx, 3)
  })

  it('scales each figure to the stage size', () => {
    for (const id of CAST) {
      const rig = RIGS[id]
      const actor = createWorld([id], env(), 1).actors[0]
      const frame = new Animator(rig, 1).frame(actor, env(), 0, 1 / 60, true)
      expect(figureHeight(rig) * frame.pose.scale).toBeCloseTo(92 * rig.height, 5)
    }
  })
})

describe('animator', () => {
  const step = (animator: Animator, actor: Actor, e: StageEnv, seconds: number, still = false) => {
    let frame = animator.frame(actor, e, 0, 1 / 60, still)
    for (let t = 0; t < seconds; t += 1 / 60) frame = animator.frame(actor, e, t, 1 / 60, still)
    return frame
  }

  it('reduced motion: a still frame never breathes, blinks or sways', () => {
    const rig = RIGS.gemini
    const actor = createWorld(['gemini'], env(), 1).actors[0]
    const animator = new Animator(rig, 1)
    const frames = Array.from({length: 120}, (_, i) => animator.frame(actor, env(), i / 60, 1 / 60, true))
    expect(new Set(frames.map(f => JSON.stringify(f.pose))).size).toBe(1)
    expect(frames.every(f => f.eyes === 0 && f.mouth === 0)).toBe(true)
  })

  it('blinks within a few seconds and breathes when motion is allowed', () => {
    const actor = createWorld(['ember'], env(), 1).actors[0]
    actor.act = {kind: 'idle', until: Infinity, look: 0}
    const animator = new Animator(RIGS.ember, 3)
    let blinked = false
    const breaths = new Set<number>()
    for (let t = 0; t < 8; t += 1 / 60) {
      const f = animator.frame(actor, env(), t, 1 / 60, false)
      if (f.eyes === 1) blinked = true
      breaths.add(Math.round(f.pose.breath * 1000))
    }
    expect(blinked).toBe(true)
    expect(breaths.size).toBeGreaterThan(5)
  })

  it('forms: cat gives a tail to companions without one, dog swaps Astra to her earless art and adds a tail', () => {
    const star = createWorld(['star'], env(), 1).actors[0]
    star.act = {kind: 'idle', until: Infinity, look: 0}
    expect(step(new Animator(RIGS.star, 1), star, env(), 0.5).tail).toBeNull()
    const cat = step(new Animator(RIGS.star, 1), star, env({forms: {star: 'cat', ember: 'normal', astra: 'normal', gemini: 'normal'}}), 0.5)
    expect(cat.form).toBe('cat')
    expect(cat.tail?.length).toBeGreaterThan(5)
    const astra = createWorld(['astra'], env(), 1).actors[0]
    astra.act = {kind: 'idle', until: Infinity, look: 0}
    expect(step(new Animator(RIGS.astra, 1), astra, env({forms: {star: 'normal', ember: 'normal', astra: 'cat', gemini: 'normal'}}), 0.5).tail).toBeNull()
    const dog = step(new Animator(RIGS.astra, 1), astra, env({forms: {star: 'normal', ember: 'normal', astra: 'dog', gemini: 'normal'}}), 0.5)
    expect(dog.form).toBe('dog')
    expect(dog.tail).not.toBeNull()
    expect(RIGS.astra.plain).toMatch(/astra-plain\.png$/)
  })

  it('study puts each companion at a desk with their own prop, glasses where the art has none', () => {
    const props = CAST.map(id => {
      const actor = createWorld([id], env(), 1).actors[0]
      actor.act = {kind: 'study', until: Infinity, nap: false}
      const f = step(new Animator(RIGS[id], 1), actor, env({study: true}), 1)
      return [id, f.desk, f.prop, f.glasses]
    })
    expect(props).toEqual([['star', true, 'laptop', true], ['ember', true, 'book', false], ['astra', true, 'book', true], ['gemini', true, 'notebook', true]])
  })

  it('walking advances the step cycle with distance and lifts alternate feet', () => {
    const actor = createWorld(['gemini'], env(), 1).actors[0]
    actor.act = {kind: 'walk', tx: 2000, run: false}
    const animator = new Animator(RIGS.gemini, 1)
    let left = 0, right = 0
    for (let t = 0; t < 3; t += 1 / 60) {
      actor.x += 46 / 60
      const f = animator.frame(actor, env(), t, 1 / 60, false)
      if (f.pose.legLLift > 2) left++
      if (f.pose.legRLift > 2) right++
      expect(f.pose.legLLift > 0 && f.pose.legRLift > 0).toBe(false)
    }
    expect(left).toBeGreaterThan(20)
    expect(right).toBeGreaterThan(20)
  })
})
