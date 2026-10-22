import {describe, expect, it} from 'vitest'
import {actorWidth, createWorld, dragTo, grab, planPath, poke, release, stepWorld} from './director'
import type {AppActivity, Platform, StageEnv, World} from './director'
import type {CastId} from './rig'

const CAST: CastId[] = ['star', 'ember', 'astra', 'gemini']
const floor: Platform = {id: 'floor', x0: 0, x1: 1200, y: 600}
const split: Platform[] = [
  {id: 'floor-l', x0: 0, x1: 160, y: 600},
  {id: 'ledge', x0: 200, x1: 1000, y: 460},
  {id: 'floor-r', x0: 1040, x1: 1200, y: 600},
]

function env(over: Partial<StageEnv> = {}): StageEnv {
  return {
    platforms: [floor], size: 90, app: 'idle', study: false, night: false, affection: true,
    forms: {star: 'normal', ember: 'normal', astra: 'normal', gemini: 'normal'}, still: false, ...over,
  }
}

function run(world: World, e: StageEnv, seconds: number, each?: (w: World) => void) {
  for (let t = 0; t < seconds; t += 1 / 60) { stepWorld(world, e, 1 / 60); each?.(world) }
}

const onPlatform = (world: World, e: StageEnv) => world.actors.every(a =>
  a.away || a.act.kind === 'hop' || a.act.kind === 'fall' ||
  e.platforms.some(p => p.id === a.platform && a.x >= p.x0 - 1 && a.x <= p.x1 + 1 && a.y === p.y))

describe('companion director', () => {
  it('places every cast member on a walkable platform and keeps them there for minutes', () => {
    const e = env({platforms: split})
    const world = createWorld(CAST, e, 3)
    expect(world.actors.every(a => !a.away && a.platform)).toBe(true)
    let ok = true
    run(world, e, 240, w => { ok = ok && onPlatform(w, e) })
    expect(ok).toBe(true)
  })

  it('is deterministic for a seed', () => {
    const a = createWorld(CAST, env(), 11), b = createWorld(CAST, env(), 11)
    run(a, env(), 30); run(b, env(), 30)
    expect(a.actors.map(x => [x.x, x.act.kind])).toEqual(b.actors.map(x => [x.x, x.act.kind]))
  })

  it('routes across platforms with hops at the joins', () => {
    const steps = planPath(env({platforms: split}), 'floor-l', 60, 'floor-r', 1100)
    expect(steps.filter(s => s.type === 'hop').map(s => s.type === 'hop' && s.to)).toEqual(['ledge', 'floor-r'])
    expect(planPath(env({platforms: split}), 'ledge', 300, 'ledge', 900)).toEqual([{type: 'walk', x: 900}])
  })

  it('stands still with reduced motion or the still preference: no walking, no scenes', () => {
    const e = env({still: true})
    const world = createWorld(CAST, e, 5)
    const start = world.actors.map(a => a.x)
    run(world, e, 60)
    expect(world.actors.map(a => a.x)).toEqual(start)
    expect(world.scene).toBeNull()
    expect(world.actors.every(a => a.act.kind === 'idle')).toBe(true)
  })

  it('a poke while still only answers with a line', () => {
    const e = env({still: true})
    const world = createWorld(CAST, e, 5)
    stepWorld(world, e, 0.016)
    poke(world, e, 'ember')
    expect(world.actors[1].act.kind).toBe('idle')
    expect(world.actors[1].bubble?.text).toBeTruthy()
  })

  it.each([3, 21, 40])('plays tag: one is it, a tag hands it on, then everyone sits down tired (seed %i)', seed => {
    const e = env({platforms: split})
    const world = createWorld(CAST, e, seed)
    world.next.tag = 0; world.next.banter = world.next.affection = Infinity
    run(world, e, 1)
    expect(world.scene?.kind).toBe('tag')
    const its = new Set<CastId>()
    let tired = false
    run(world, e, 40, w => {
      if (w.scene?.kind === 'tag') its.add(w.scene.it)
      if (w.actors.some(a => a.act.kind === 'sit' && a.act.tired)) tired = true
    })
    expect(its.size).toBeGreaterThan(1)
    expect(tired).toBe(true)
  })

  it('runs an affection scene to the end, and never when affection is off', () => {
    const e = env()
    const world = createWorld(['ember', 'astra'], e, 4)
    world.next.tag = world.next.banter = Infinity
    world.next.affection = 0
    const kinds = new Set<string>()
    run(world, e, 20, w => w.actors.forEach(a => kinds.add(a.act.kind)))
    expect(kinds.has('kiss') || kinds.has('hug')).toBe(true)
    expect(kinds.has('blush')).toBe(true)

    const off = env({affection: false})
    const quiet = createWorld(['ember', 'astra'], off, 4)
    quiet.next.affection = 0
    const seen = new Set<string>()
    run(quiet, off, 60, w => w.actors.forEach(a => seen.add(a.act.kind)))
    expect(seen.has('kiss') || seen.has('hug')).toBe(false)
  })

  it('keeps play calm while you type or STAR works, and Star works at her laptop', () => {
    const typing = env({app: 'typing'})
    const world = createWorld(CAST, typing, 8)
    world.next.tag = world.next.affection = world.next.banter = 0
    run(world, typing, 20)
    expect(world.scene).toBeNull()
    const busy = env({app: 'streaming'})
    run(world, busy, 6)
    expect(world.actors.find(a => a.id === 'star')?.act.kind).toBe('work')
    expect(world.scene).toBeNull()
  })

  it('celebrates a finished task and looks worried on an error, with a line', () => {
    const steps: [AppActivity, string][] = [['finished', 'celebrate'], ['error', 'worried']]
    for (const [app, kind] of steps) {
      const world = createWorld(CAST, env(), 9)
      run(world, env({app: 'thinking'}), 2)
      stepWorld(world, env({app}), 1 / 60)
      expect(world.actors.filter(a => a.act.kind === kind).length).toBeGreaterThan(0)
      expect(world.actors.some(a => a.bubble)).toBe(true)
    }
  })

  it('switches to study at desks and back', () => {
    const world = createWorld(CAST, env(), 2)
    run(world, env({study: true}), 3)
    expect(world.actors.every(a => a.act.kind === 'study')).toBe(true)
    run(world, env(), 3)
    expect(world.actors.some(a => a.act.kind === 'study')).toBe(false)
  })

  it.each([6, 7, 8])('keeps walkers from walking through each other (seed %i)', seed => {
    const e = env({platforms: [{id: 'floor', x0: 0, x1: 600, y: 600}]})
    const world = createWorld(['ember', 'astra'], e, seed)
    world.next.tag = world.next.affection = world.next.banter = Infinity
    let closest = Infinity
    run(world, e, 120, w => {
      const [a, b] = w.actors
      if (a.act.kind === 'walk' || b.act.kind === 'walk') closest = Math.min(closest, Math.abs(a.x - b.x))
    })
    expect(closest).toBeGreaterThan(actorWidth(e) * 0.5)
  })

  it('picks up, swings with the pointer and drops onto the platform below', () => {
    const e = env({platforms: split})
    const world = createWorld(CAST, e, 3)
    stepWorld(world, e, 1 / 60)
    grab(world, 'gemini', 600, 200)
    dragTo(world, 'gemini', 640, 180)
    const gemini = world.actors.find(a => a.id === 'gemini')!
    expect(gemini.act.kind).toBe('dragged')
    expect(gemini.bubble).not.toBeNull()
    release(world, 'gemini', 80, 0)
    run(world, e, 2)
    expect(gemini.platform).toBe('ledge')
    expect(gemini.y).toBe(460)
  })

  it('moves companions off the composer ledge when it goes away (reading older messages)', () => {
    const e = env({platforms: split})
    const world = createWorld(CAST, e, 3)
    run(world, e, 1)
    const reading = env({platforms: split.filter(p => p.id !== 'ledge')})
    run(world, reading, 3)
    expect(world.actors.every(a => a.platform !== 'ledge')).toBe(true)
  })

  it('switching an animal form changes only that companion', () => {
    const forms = {star: 'normal', ember: 'cat', astra: 'normal', gemini: 'dog'} as const
    const e = env({forms})
    expect(e.forms.ember).toBe('cat')
    const world = createWorld(CAST, e, 12)
    world.next.tag = world.next.affection = world.next.banter = Infinity
    const kinds = new Map<CastId, Set<string>>(CAST.map(id => [id, new Set()]))
    run(world, e, 200, w => w.actors.forEach(a => kinds.get(a.id)!.add(a.act.kind)))
    expect(kinds.get('ember')!.has('groom')).toBe(true)
    expect(kinds.get('gemini')!.has('wag')).toBe(true)
    expect(kinds.get('star')!.has('groom') || kinds.get('star')!.has('wag')).toBe(false)
  })
})
