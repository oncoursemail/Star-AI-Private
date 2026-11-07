/**
 * The companions' behaviour director: a deterministic state machine (seeded random, time passed in)
 * that moves the cast along walkable platforms and runs their little scenes. It never renders and
 * never invents app activity: reactions only follow the work state the app hands it.
 */
import {pickBanter, pickLine} from './dialogue'
import type {Line, Situation} from './dialogue'
import type {CastId} from './cast'

export type Form = 'normal' | 'cat' | 'dog'
export type AppActivity = 'idle' | 'typing' | 'thinking' | 'streaming' | 'finished' | 'error' | 'cancelled' | 'update'

/** A walkable segment in stage px. `quiet`: nobody starts walking on it (e.g. the composer ledge while you type). */
export type Platform = { id: string; x0: number; x1: number; y: number; quiet?: boolean }

export type StageEnv = {
  platforms: readonly Platform[]
  /** Figure height in stage px; widths and speeds scale with it. */
  size: number
  app: AppActivity
  study: boolean
  night: boolean
  affection: boolean
  forms: Readonly<Record<CastId, Form>>
  /** Reduced motion or the still preference: nothing moves on its own. */
  still: boolean
}

export type Activity =
  | { kind: 'idle'; until: number; look: number }
  | { kind: 'walk'; tx: number; run: boolean }
  | { kind: 'hop'; x0: number; y0: number; x1: number; y1: number; to: string; t: number; dur: number; height: number }
  | { kind: 'fall'; vx: number; vy: number }
  | { kind: 'land'; until: number; hard: boolean }
  | { kind: 'sit'; until: number; tired: boolean }
  | { kind: 'sleep'; until: number }
  | { kind: 'talk'; until: number; to: CastId | null }
  | { kind: 'listen'; until: number; to: CastId }
  | { kind: 'kiss' | 'hug' | 'highfive'; until: number; to: CastId; giver: boolean }
  /** The tagger's hand-off reach. */
  | { kind: 'reach'; until: number }
  | { kind: 'blush'; until: number; to: CastId }
  | { kind: 'celebrate'; until: number }
  | { kind: 'worried'; until: number }
  | { kind: 'work'; until: number }
  | { kind: 'watch'; until: number; to: CastId }
  | { kind: 'study'; until: number; nap: boolean }
  | { kind: 'groom' | 'wag'; until: number }
  | { kind: 'tagged'; until: number }
  | { kind: 'poked'; until: number }
  | { kind: 'dragged' }

type Step = { type: 'walk'; x: number } | { type: 'hop'; to: string; x: number }

export type Actor = {
  id: CastId
  x: number
  y: number
  platform: string | null
  dir: -1 | 1
  act: Activity
  path: Step[]
  /** Run while following the path. */
  running: boolean
  away: boolean
  bubble: { text: string; until: number } | null
  blushUntil: number
  energy: number
  vx: number
}

export type Scene =
  | { kind: 'banter'; a: CastId; b: CastId; lines: readonly Line[]; index: number; next: number; meeting: boolean }
  | { kind: 'tag'; it: CastId; until: number; immune: CastId | null; immuneUntil: number; replan: number }
  | { kind: 'affection'; a: CastId; b: CastId; type: 'kiss' | 'hug' | 'highfive'; phase: 'approach' | 'act' | 'after'; until: number }
  | { kind: 'react'; type: 'done' | 'error' | 'stopped'; until: number }

export type StageEvent = { kind: 'dust' | 'heart' | 'sparkle' | 'sweat' | 'zzz' | 'bang' | 'question' | 'note'; id: CastId }

export type World = {
  now: number
  actors: Actor[]
  scene: Scene | null
  seed: number
  app: AppActivity
  study: boolean
  next: { banter: number; tag: number; affection: number; nightLine: number; studyBanter: number; studyNap: number }
  events: StageEvent[]
  greeted: boolean
}

export const WALK = 0.5   // figure heights per second
export const RUN = 1.45
const GRAVITY = 26        // figure heights per second squared

/** mulberry32: small, fast, deterministic. */
export function nextRandom(world: World): number {
  let t = (world.seed = (world.seed + 0x6d2b79f5) | 0)
  t = Math.imul(t ^ (t >>> 15), t | 1)
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296
}
const range = (world: World, a: number, b: number) => a + (b - a) * nextRandom(world)
const pick = <T>(world: World, items: readonly T[]): T => items[Math.floor(nextRandom(world) * items.length) % items.length]

export const actorWidth = (env: Pick<StageEnv, 'size'>) => env.size * 0.6
const platformById = (env: StageEnv, id: string | null) => env.platforms.find(p => p.id === id) ?? null
const free = (actor: Actor) => !actor.away && actor.platform !== null &&
  !['dragged', 'fall', 'hop', 'land', 'poked'].includes(actor.act.kind)
const busyApp = (app: AppActivity) => app === 'thinking' || app === 'streaming'

export function createWorld(cast: readonly CastId[], env: StageEnv, seed = 1, now = 0): World {
  const world: World = {
    now, actors: [], scene: null, seed, app: env.app, study: env.study, events: [], greeted: false,
    next: { banter: now + 9, tag: now + 70, affection: now + 45, nightLine: now + 30, studyBanter: now + 20, studyNap: now + 60 },
  }
  world.actors = cast.map(id => ({
    id, x: 0, y: 0, platform: null, dir: -1, act: { kind: 'idle', until: now + 1, look: 0 }, path: [], running: false,
    away: true, bubble: null, blushUntil: 0, energy: 1, vx: 0,
  }))
  placeAway(world, env)
  return world
}

/** Spread actors without a platform over the walkable space (largest platforms first). */
function placeAway(world: World, env: StageEnv) {
  const usable = env.platforms.filter(p => p.x1 - p.x0 >= actorWidth(env) * 0.9)
  if (!usable.length) return
  const total = usable.reduce((sum, p) => sum + p.x1 - p.x0, 0)
  const waiting = world.actors.filter(actor => actor.away || !platformById(env, actor.platform))
  waiting.forEach((actor, index) => {
    let at = total * (index + 0.5 + range(world, -0.2, 0.2)) / Math.max(1, waiting.length)
    for (const p of usable) {
      const span = p.x1 - p.x0
      if (at <= span) {
        actor.platform = p.id
        actor.x = clampInto(p, p.x0 + at, env)
        actor.y = p.y
        break
      }
      at -= span
    }
    actor.away = false
    actor.path = []
    actor.act = { kind: 'idle', until: world.now + range(world, 0.4, 2), look: 0 }
  })
}

function clampInto(p: Platform, x: number, env: Pick<StageEnv, 'size'>) {
  const half = actorWidth(env) / 2
  return p.x1 - p.x0 <= half * 2 ? (p.x0 + p.x1) / 2 : Math.min(p.x1 - half, Math.max(p.x0 + half, x))
}

export function say(world: World, actor: Actor, text: string | null, seconds = 0) {
  if (!text) return
  actor.bubble = { text, until: world.now + (seconds || 1.6 + text.length * 0.055) }
}
const sayLine = (world: World, actor: Actor, situation: Situation) =>
  say(world, actor, pickLine(situation, actor.id, () => nextRandom(world)))

function setIdle(world: World, actor: Actor, seconds?: number) {
  actor.path = []
  actor.running = false
  actor.act = { kind: 'idle', until: world.now + (seconds ?? range(world, 1.5, 4)), look: range(world, -1, 1) }
}

// ---------------------------------------------------------------- paths

/** Platforms are linked when their ends are close enough to hop between. */
function neighbours(env: StageEnv, from: Platform): Platform[] {
  const reach = env.size * 1.8
  return env.platforms.filter(p => p !== from && p.x0 - from.x1 < reach && from.x0 - p.x1 < reach)
}

function crossing(from: Platform, to: Platform, env: StageEnv): { exit: number; entry: number } {
  const inset = actorWidth(env) * 0.55
  if (to.x0 >= from.x1 - inset) return { exit: from.x1 - inset, entry: to.x0 + inset }
  if (to.x1 <= from.x0 + inset) return { exit: from.x0 + inset, entry: to.x1 - inset }
  const mid = Math.min(Math.max(from.x0 + inset, to.x0 + inset), from.x1 - inset)
  return { exit: mid, entry: clampInto(to, mid, env) }
}

/** Breadth-first route over platforms; the walk/hop steps to (platform, x). */
export function planPath(env: StageEnv, fromId: string, x: number, toId: string, tx: number): Step[] {
  const start = platformById(env, fromId), goal = platformById(env, toId)
  if (!start || !goal) return []
  const previous = new Map<string, string>()
  const queue = [start.id]
  const seen = new Set(queue)
  while (queue.length) {
    const id = queue.shift() as string
    if (id === goal.id) break
    for (const n of neighbours(env, platformById(env, id) as Platform)) {
      if (seen.has(n.id)) continue
      seen.add(n.id); previous.set(n.id, id); queue.push(n.id)
    }
  }
  if (!seen.has(goal.id)) return []
  const chain = [goal.id]
  while (chain[0] !== start.id) chain.unshift(previous.get(chain[0]) as string)
  const steps: Step[] = []
  let cursor = x
  for (let i = 0; i + 1 < chain.length; i++) {
    const a = platformById(env, chain[i]) as Platform, b = platformById(env, chain[i + 1]) as Platform
    const {exit, entry} = crossing(a, b, env)
    if (Math.abs(exit - cursor) > 1) steps.push({ type: 'walk', x: exit })
    steps.push({ type: 'hop', to: b.id, x: entry })
    cursor = entry
  }
  const end = clampInto(goal, tx, env)
  if (Math.abs(end - cursor) > 1) steps.push({ type: 'walk', x: end })
  return steps
}

function goTo(world: World, env: StageEnv, actor: Actor, platform: string, x: number, run = false) {
  if (!actor.platform) return
  actor.path = planPath(env, actor.platform, actor.x, platform, x)
  actor.running = run
  advance(world, env, actor)
}

function advance(world: World, env: StageEnv, actor: Actor) {
  const step = actor.path.shift()
  if (!step) { setIdle(world, actor); return }
  if (step.type === 'walk') {
    actor.act = { kind: 'walk', tx: step.x, run: actor.running }
    return
  }
  startHop(world, env, actor, step.to, step.x)
}

function startHop(world: World, env: StageEnv, actor: Actor, to: string, x: number) {
  const target = platformById(env, to)
  if (!target) { setIdle(world, actor); return }
  const rise = Math.max(0, actor.y - target.y)
  const height = env.size * 0.35 + rise * 0.45
  const dur = 0.42 + Math.min(0.5, (Math.abs(x - actor.x) + Math.abs(actor.y - target.y)) / (env.size * 9))
  actor.dir = x >= actor.x ? 1 : -1
  actor.act = { kind: 'hop', x0: actor.x, y0: actor.y, x1: x, y1: target.y, to, t: 0, dur, height }
  actor.platform = null
  world.events.push({ kind: 'dust', id: actor.id })
}

// ---------------------------------------------------------------- input

export function grab(world: World, id: CastId, x: number, y: number) {
  const actor = world.actors.find(a => a.id === id)
  if (!actor || actor.away) return
  if (world.scene && sceneMembers(world.scene).includes(id)) world.scene = null
  actor.act = { kind: 'dragged' }
  actor.platform = null
  actor.path = []
  actor.x = x; actor.y = y
  sayLine(world, actor, 'pickup')
}

export function dragTo(world: World, id: CastId, x: number, y: number) {
  const actor = world.actors.find(a => a.id === id)
  if (!actor || actor.act.kind !== 'dragged') return
  actor.vx = x - actor.x
  actor.x = x; actor.y = y
}

export function release(world: World, id: CastId, vx: number, vy: number) {
  const actor = world.actors.find(a => a.id === id)
  if (!actor || actor.act.kind !== 'dragged') return
  actor.act = { kind: 'fall', vx, vy }
}

export function poke(world: World, env: StageEnv, id: CastId) {
  const actor = world.actors.find(a => a.id === id)
  if (!actor || actor.away || !free(actor)) return
  if (env.still) { sayLine(world, actor, 'poke'); return }
  if (world.scene && world.scene.kind !== 'tag' && sceneMembers(world.scene).includes(id)) world.scene = null
  actor.path = []
  actor.act = { kind: 'poked', until: world.now + 0.75 }
  sayLine(world, actor, 'poke')
  world.events.push({ kind: nextRandom(world) < 0.5 ? 'heart' : 'bang', id })
}

// ---------------------------------------------------------------- the tick

const sceneMembers = (scene: Scene): CastId[] =>
  scene.kind === 'banter' || scene.kind === 'affection' ? [scene.a, scene.b] : []

export function stepWorld(world: World, env: StageEnv, dt: number) {
  world.events = []
  world.now += dt
  const now = world.now
  for (const actor of world.actors) {
    if (actor.bubble && actor.bubble.until <= now) actor.bubble = null
  }
  // Platforms come and go with the layout: actors whose ground vanished hop to the nearest one.
  if (!env.platforms.length) {
    for (const actor of world.actors) if (actor.act.kind !== 'dragged') { actor.away = true; actor.platform = null }
    return
  }
  if (world.actors.some(a => a.away)) placeAway(world, env)
  for (const actor of world.actors) {
    if (actor.platform && !platformById(env, actor.platform)) relocate(world, env, actor)
    else if (actor.platform && actor.act.kind !== 'hop') {
      const p = platformById(env, actor.platform) as Platform
      actor.y = p.y
      actor.x = clampInto(p, actor.x, env)
    }
  }
  if (env.still) {
    world.scene = null
    for (const actor of world.actors) {
      if (actor.act.kind === 'dragged') continue
      if (!actor.platform) relocate(world, env, actor)
      actor.path = []
      actor.act = { kind: 'idle', until: Infinity, look: 0 }
    }
    world.app = env.app
    world.study = env.study
    return
  }
  reactToApp(world, env)
  if (!world.greeted) {
    world.greeted = true
    const host = world.actors.find(a => a.id === 'star') ?? world.actors[0]
    if (host) sayLine(world, host, env.study ? 'study' : env.night ? 'night' : 'greet')
  }
  runScene(world, env)
  for (const actor of world.actors) updateActor(world, env, actor, dt)
  if (!world.scene) scheduleScene(world, env)
  for (const actor of world.actors) if (free(actor) && actor.act.kind === 'idle' && actor.act.until <= now) chooseIdle(world, env, actor)
}

function relocate(world: World, env: StageEnv, actor: Actor) {
  let best: Platform | null = null, bestDistance = Infinity
  for (const p of env.platforms) {
    const x = clampInto(p, actor.x, env)
    const distance = Math.hypot(x - actor.x, p.y - actor.y)
    if (distance < bestDistance) { best = p; bestDistance = distance }
  }
  if (!best) return
  actor.path = []
  if (env.still) {
    actor.platform = best.id; actor.x = clampInto(best, actor.x, env); actor.y = best.y
    return
  }
  startHop(world, env, actor, best.id, clampInto(best, actor.x, env))
}

function reactToApp(world: World, env: StageEnv) {
  const before = world.app
  world.app = env.app
  if (env.study !== world.study) {
    world.study = env.study
    world.scene = null
    for (const actor of world.actors) if (free(actor)) setIdle(world, actor, range(world, 0.1, 0.8))
    const host = world.actors.find(a => a.id === 'star') ?? world.actors[0]
    if (env.study && host) sayLine(world, host, 'study')
  }
  if (before === env.app) return
  const speaker = (preferred: CastId) => world.actors.find(a => a.id === preferred && free(a)) ?? world.actors.find(free)
  if (busyApp(env.app) && !busyApp(before)) {
    if (world.scene?.kind !== 'react') world.scene = null
    for (const actor of world.actors) if (free(actor)) setIdle(world, actor, 0.05)
    const s = speaker('star'); if (s) sayLine(world, s, 'working')
    return
  }
  const type = env.app === 'finished' ? 'done' : env.app === 'error' ? 'error' : env.app === 'cancelled' ? 'stopped' : null
  if (type) {
    world.scene = { kind: 'react', type, until: world.now + (type === 'done' ? 2.4 : 2.8) }
    for (const actor of world.actors) {
      if (!free(actor)) continue
      actor.path = []
      if (type === 'done') { actor.act = { kind: 'celebrate', until: world.now + range(world, 1.8, 2.4) }; world.events.push({ kind: 'sparkle', id: actor.id }) }
      else if (type === 'error') { actor.act = { kind: 'worried', until: world.now + 2.6 }; world.events.push({ kind: 'sweat', id: actor.id }) }
      else { actor.act = { kind: 'idle', until: world.now + 1.2, look: 0 }; world.events.push({ kind: 'question', id: actor.id }) }
    }
    const s = speaker(type === 'error' ? pick(world, ['ember', 'gemini', 'star'] as const) : 'star')
    if (s) sayLine(world, s, type)
    return
  }
  if (env.app === 'update') { const s = speaker('star'); if (s) sayLine(world, s, 'update') }
}

// ---------------------------------------------------------------- scenes

function calm(world: World, env: StageEnv) {
  return env.app === 'typing' || busyApp(env.app) || world.scene?.kind === 'react'
}

function onQuiet(env: StageEnv, actor: Actor) {
  return !!platformById(env, actor.platform)?.quiet
}

function scheduleScene(world: World, env: StageEnv) {
  const now = world.now
  const ready = world.actors.filter(a => free(a) && !onQuiet(env, a) &&
    ['idle', 'walk', 'sit', 'groom', 'wag', 'study'].includes(a.act.kind) && !(a.act.kind === 'study' && a.act.nap))
  if (env.night && now >= world.next.nightLine && !calm(world, env) && ready.length) {
    world.next.nightLine = now + range(world, 90, 180)
    sayLine(world, pick(world, ready), 'night')
  }
  if (env.study) {
    if (now >= world.next.studyBanter && ready.length >= 2 && env.app !== 'typing') {
      world.next.studyBanter = now + range(world, 35, 70)
      const [a, b] = pickPair(world, ready)
      const lines = pickBanter(a.id, b.id, () => nextRandom(world), true)
      if (lines.length) world.scene = { kind: 'banter', a: a.id, b: b.id, lines, index: 0, next: now, meeting: false }
    }
    return
  }
  if (calm(world, env) || ready.length < 2) return
  if (now >= world.next.tag && ready.length >= 2 && world.actors.length >= 2) {
    world.next.tag = now + range(world, 150, 280)
    const it = pick(world, ready)
    world.scene = { kind: 'tag', it: it.id, until: now + range(world, 16, 24), immune: null, immuneUntil: 0, replan: 0 }
    sayLine(world, it, 'tagStart')
    for (const a of ready) { a.energy = 1; a.path = []; setIdle(world, a, 0.3) }
    return
  }
  if (now >= world.next.affection) {
    world.next.affection = now + range(world, 80, 170)
    const [a, b] = pickPair(world, ready)
    // Hugs and cheek kisses follow the setting; a high five is always fine.
    const roll = nextRandom(world)
    const type = !env.affection || roll > 0.72 ? 'highfive' : roll < 0.38 ? 'kiss' : 'hug'
    if (a.platform === b.platform) {
      world.scene = { kind: 'affection', a: a.id, b: b.id, type, phase: 'approach', until: now + 9 }
      return
    }
  }
  if (now >= world.next.banter) {
    world.next.banter = now + range(world, 22, 45)
    const [a, b] = pickPair(world, ready)
    const lines = pickBanter(a.id, b.id, () => nextRandom(world))
    if (lines.length) world.scene = { kind: 'banter', a: a.id, b: b.id, lines, index: 0, next: now, meeting: a.platform === b.platform }
  }
}

/** Two different actors, the second the closest to the first (a pair that can actually meet). */
function pickPair(world: World, ready: Actor[]): [Actor, Actor] {
  const a = pick(world, ready)
  const others = ready.filter(o => o !== a).sort((p, q) => Math.abs(p.x - a.x) - Math.abs(q.x - a.x))
  return [a, nextRandom(world) < 0.7 ? others[0] : pick(world, others)]
}

function runScene(world: World, env: StageEnv) {
  const scene = world.scene
  if (!scene) return
  const now = world.now
  const get = (id: CastId) => world.actors.find(a => a.id === id)
  if (scene.kind === 'react') { if (now >= scene.until) world.scene = null; return }
  if (scene.kind === 'banter') {
    const a = get(scene.a), b = get(scene.b)
    if (!a || !b || !free(a) || !free(b) || (env.app === 'typing' && !env.study)) { world.scene = null; return }
    if (scene.meeting) {
      const gap = Math.abs(a.x - b.x)
      const want = actorWidth(env) * 1.7
      if (a.platform === b.platform && gap > want * 1.15) {
        if (a.act.kind !== 'walk') goTo(world, env, a, a.platform as string, b.x + (a.x < b.x ? -want : want))
        if (b.act.kind !== 'idle' && b.act.kind !== 'listen' && b.act.kind !== 'study') setIdle(world, b, 3)
        return
      }
      scene.meeting = false
      scene.next = now
    }
    if (now < scene.next) return
    if (scene.index >= scene.lines.length) {
      world.scene = null
      for (const actor of [a, b]) if (actor.act.kind === 'talk' || actor.act.kind === 'listen') setIdle(world, actor, range(world, 0.8, 2))
      return
    }
    const line = scene.lines[scene.index++]
    const speaker = line.who === a.id ? a : b, listener = speaker === a ? b : a
    const seconds = 1.5 + line.text.length * 0.055
    say(world, speaker, line.text, seconds)
    speaker.path = []
    if (speaker.act.kind !== 'study') speaker.act = { kind: 'talk', until: now + seconds, to: listener.id }
    if (listener.act.kind !== 'study') listener.act = { kind: 'listen', until: now + seconds + 0.3, to: speaker.id }
    face(speaker, listener.x); face(listener, speaker.x)
    scene.next = now + seconds + 0.25
    return
  }
  if (scene.kind === 'affection') runAffection(world, env, scene)
  else runTag(world, env, scene)
}

function face(actor: Actor, x: number) {
  if (Math.abs(x - actor.x) > 1) actor.dir = x > actor.x ? 1 : -1
}

function runAffection(world: World, env: StageEnv, scene: Extract<Scene, { kind: 'affection' }>) {
  const now = world.now
  const a = world.actors.find(x => x.id === scene.a), b = world.actors.find(x => x.id === scene.b)
  if (!a || !b || !free(a) || !free(b) || (!env.affection && scene.type !== 'highfive') || calm(world, env) || now > scene.until + 6) {
    world.scene = null
    return
  }
  const close = actorWidth(env) * (scene.type === 'hug' ? 0.62 : scene.type === 'kiss' ? 0.78 : 1.05)
  if (scene.phase === 'approach') {
    if (a.platform !== b.platform) { world.scene = null; return }
    const gap = Math.abs(a.x - b.x)
    if (gap > close * 1.08) {
      // Both walk to meet in the middle.
      const mid = (a.x + b.x) / 2, side = a.x < b.x ? -1 : 1
      if (a.act.kind !== 'walk') goTo(world, env, a, a.platform as string, mid + side * close / 2)
      if (b.act.kind !== 'walk' && gap > close * 1.6) goTo(world, env, b, b.platform as string, mid - side * close / 2)
      if (now > scene.until) world.scene = null
      return
    }
    face(a, b.x); face(b, a.x)
    a.path = []; b.path = []
    const length = scene.type === 'hug' ? 2.2 : scene.type === 'kiss' ? 1.6 : 1.1
    a.act = { kind: scene.type, until: now + length, to: b.id, giver: true }
    b.act = { kind: scene.type, until: now + length, to: a.id, giver: false }
    if (scene.type !== 'highfive') {
      a.blushUntil = b.blushUntil = now + length + 1.8
      world.events.push({ kind: 'heart', id: a.id }, { kind: 'heart', id: b.id })
    }
    scene.phase = 'act'
    scene.until = now + length
    return
  }
  if (scene.phase === 'act') {
    if (scene.type !== 'highfive' && nextRandom(world) < 0.06) world.events.push({ kind: 'heart', id: nextRandom(world) < 0.5 ? a.id : b.id })
    if (now < scene.until) return
    if (scene.type === 'highfive') {
      a.act = { kind: 'celebrate', until: now + 0.9 }
      b.act = { kind: 'celebrate', until: now + 0.9 }
      scene.phase = 'after'
      scene.until = now + 0.9
      return
    }
    a.act = { kind: 'blush', until: now + 1.6, to: b.id }
    b.act = { kind: 'blush', until: now + 1.6, to: a.id }
    sayLine(world, nextRandom(world) < 0.5 ? b : a, scene.type === 'kiss' ? 'kissAfter' : 'hugAfter')
    scene.phase = 'after'
    scene.until = now + 1.6
    return
  }
  if (now >= scene.until) world.scene = null
}

function runTag(world: World, env: StageEnv, scene: Extract<Scene, { kind: 'tag' }>) {
  const now = world.now
  const players = world.actors.filter(a => free(a) && !onQuiet(env, a) || a.act.kind === 'hop')
  const it = world.actors.find(a => a.id === scene.it)
  if (!it || calm(world, env) || players.length < 2) { endTag(world, env, false); return }
  if (now >= scene.until) { endTag(world, env, true); return }
  const width = actorWidth(env)
  // "It" chases the nearest player it may tag.
  const targets = players.filter(p => p !== it && !(p.id === scene.immune && now < scene.immuneUntil))
  if (!targets.length) return
  const prey = targets.sort((p, q) => Math.hypot(p.x - it.x, p.y - it.y) - Math.hypot(q.x - it.x, q.y - it.y))[0]
  if (free(it) && it.act.kind !== 'tagged' && prey.platform === it.platform && Math.abs(prey.x - it.x) < width * 0.6) {
    // Tag! The hand-off freezes the new "it" for a beat, and the old one may not be tagged straight back.
    sayLine(world, it, 'tagged')
    world.events.push({ kind: 'bang', id: prey.id })
    prey.path = []
    prey.act = { kind: 'tagged', until: now + 0.7 }
    scene.immune = it.id
    scene.immuneUntil = now + 1.6
    scene.it = prey.id
    face(it, prey.x)
    it.path = []
    it.act = { kind: 'reach', until: now + 0.45 }
    return
  }
  if (now >= scene.replan) {
    scene.replan = now + 0.35
    if (free(it) && it.act.kind !== 'tagged' && prey.platform) goTo(world, env, it, prey.platform, prey.x, true)
    for (const p of targets) {
      if (!free(p) || p.act.kind === 'tagged' || !p.platform) continue
      const danger = it.platform === p.platform ? Math.abs(it.x - p.x) : Math.hypot(it.x - p.x, it.y - p.y)
      if (danger > width * 3.2) { if (p.act.kind === 'walk' && !p.running) continue; if (p.act.kind !== 'idle') setIdle(world, p, 0.4); continue }
      const plat = platformById(env, p.platform) as Platform
      const away = it.x < p.x ? 1 : -1
      const room = away > 0 ? plat.x1 - p.x : p.x - plat.x0
      if (room > width * 1.2) goTo(world, env, p, plat.id, p.x + away * Math.min(room, width * 3), true)
      else {
        const escape = neighbours(env, plat).find(n => (n.x0 + n.x1) / 2 > p.x === away > 0) ?? neighbours(env, plat)[0]
        if (escape) goTo(world, env, p, escape.id, away > 0 ? escape.x0 + width * 2 : escape.x1 - width * 2, true)
        else if (Math.abs(it.x - p.x) < width * 1.6) startHop(world, env, p, plat.id, clampInto(plat, it.x - away * width * 1.4, env))
      }
    }
  }
}

function endTag(world: World, env: StageEnv, tired: boolean) {
  world.scene = null
  for (const actor of world.actors) {
    if (!free(actor)) continue
    actor.path = []
    actor.running = false
    if (tired && !calm(world, env)) {
      actor.act = { kind: 'sit', until: world.now + range(world, 5, 8), tired: true }
      world.events.push({ kind: 'sweat', id: actor.id })
    } else setIdle(world, actor, range(world, 0.5, 1.5))
  }
  if (tired) { const s = world.actors.find(free); if (s) sayLine(world, s, 'tired') }
}

// ---------------------------------------------------------------- idle choice

function chooseIdle(world: World, env: StageEnv, actor: Actor) {
  const now = world.now
  if (env.study) {
    const nap = env.night && now >= world.next.studyNap && nextRandom(world) < 0.35
    if (nap) { world.next.studyNap = now + range(world, 50, 110); sayLine(world, actor, 'studyNap') }
    actor.act = { kind: 'study', until: now + (nap ? range(world, 18, 30) : range(world, 12, 25)), nap }
    return
  }
  if (busyApp(env.app)) {
    if (actor.id === 'star') { actor.act = { kind: 'work', until: now + 3 }; return }
    const star = world.actors.find(a => a.id === 'star' && !a.away)
    if (star && nextRandom(world) < 0.5) { face(actor, star.x); actor.act = { kind: 'watch', until: now + range(world, 3, 6), to: 'star' }; return }
    actor.act = { kind: 'sit', until: now + range(world, 4, 8), tired: false }
    return
  }
  const quiet = onQuiet(env, actor) || env.app === 'typing'
  const form = env.forms[actor.id]
  const roll = nextRandom(world)
  if (env.night && roll < 0.18) { actor.act = { kind: 'sleep', until: now + range(world, 14, 28) }; return }
  if (form === 'cat' && roll < 0.3) { actor.act = { kind: 'groom', until: now + range(world, 2.6, 4) }; return }
  if (form === 'dog' && roll < 0.3) { actor.act = { kind: 'wag', until: now + range(world, 2, 3.2) }; return }
  if (roll < 0.42 || quiet) { setIdle(world, actor); return }
  if (roll < 0.52) { actor.act = { kind: 'sit', until: now + range(world, 6, 12), tired: false }; return }
  wander(world, env, actor)
}

function wander(world: World, env: StageEnv, actor: Actor) {
  const current = platformById(env, actor.platform)
  if (!current) return
  const options = env.platforms.filter(p => !p.quiet && p.x1 - p.x0 >= actorWidth(env))
  const platform = nextRandom(world) < 0.72 || !options.length ? current : pick(world, options)
  const width = actorWidth(env)
  let x = range(world, platform.x0 + width / 2, platform.x1 - width / 2)
  if (platform === current && Math.abs(x - actor.x) < width) x = actor.x + (x > actor.x ? 1 : -1) * width * 1.5
  goTo(world, env, actor, platform.id, x)
}

// ---------------------------------------------------------------- motion

function updateActor(world: World, env: StageEnv, actor: Actor, dt: number) {
  const act = actor.act
  const now = world.now
  const size = env.size
  switch (act.kind) {
    case 'walk': {
      const form = env.forms[actor.id]
      // In tag "it" is a little quicker than the runners, or nobody would ever be caught.
      const chasing = world.scene?.kind === 'tag' && world.scene.it === actor.id
      const speed = (act.run ? RUN * (form === 'dog' ? 1.3 : 1) * (chasing ? 1.22 : world.scene?.kind === 'tag' ? 0.9 : 1) : WALK) * size
      const delta = act.tx - actor.x
      actor.dir = delta >= 0 ? 1 : -1
      if (!act.run && blocked(world, env, actor)) { setIdle(world, actor, range(world, 0.8, 1.6)); actor.dir = actor.dir === 1 ? -1 : 1; return }
      const move = Math.min(Math.abs(delta), speed * dt)
      actor.x += Math.sign(delta) * move
      actor.vx = Math.sign(delta) * speed
      if (act.run && form === 'dog' && nextRandom(world) < dt * 1.2) world.events.push({ kind: 'dust', id: actor.id })
      if (Math.abs(act.tx - actor.x) < 0.5) { actor.vx = 0; advance(world, env, actor) }
      return
    }
    case 'hop': {
      act.t = Math.min(1, act.t + dt / act.dur)
      const t = act.t
      actor.x = act.x0 + (act.x1 - act.x0) * t
      actor.y = act.y0 + (act.y1 - act.y0) * t - 4 * act.height * t * (1 - t)
      if (t >= 1) {
        const target = platformById(env, act.to)
        if (!target) { actor.act = { kind: 'fall', vx: 0, vy: 0 }; return }
        actor.platform = target.id
        actor.y = target.y
        actor.act = { kind: 'land', until: now + 0.16, hard: false }
        world.events.push({ kind: 'dust', id: actor.id })
      }
      return
    }
    case 'fall': {
      const before = actor.y
      act.vy += GRAVITY * size * dt
      act.vx *= Math.pow(0.4, dt)
      actor.x += act.vx * dt
      actor.y += act.vy * dt
      const below = env.platforms
        .filter(p => actor.x >= p.x0 - 4 && actor.x <= p.x1 + 4 && p.y >= before - 1 && p.y <= actor.y)
        .sort((p, q) => p.y - q.y)[0]
      const lowest = Math.max(...env.platforms.map(p => p.y))
      if (below || actor.y > lowest + size * 0.5) {
        const target = below ?? env.platforms.reduce((best, p) => Math.abs(clampInto(p, actor.x, env) - actor.x) < Math.abs(clampInto(best, actor.x, env) - actor.x) ? p : best)
        actor.platform = target.id
        actor.x = clampInto(target, actor.x, env)
        actor.y = target.y
        const hard = act.vy > size * 6
        actor.act = { kind: 'land', until: now + (hard ? 0.45 : 0.2), hard }
        world.events.push({ kind: 'dust', id: actor.id })
        if (hard) sayLine(world, actor, 'drop')
      }
      return
    }
    case 'land':
      if (now < act.until) return
      if (actor.path.length) { advance(world, env, actor); return }
      setIdle(world, actor, range(world, 0.6, 1.6))
      // Landed on someone: shuffle aside.
      if (world.actors.some(o => o !== actor && o.platform === actor.platform && Math.abs(o.x - actor.x) < actorWidth(env) * 0.7)) {
        const p = platformById(env, actor.platform) as Platform
        const right = actor.x + actorWidth(env) * 1.1, left = actor.x - actorWidth(env) * 1.1
        goTo(world, env, actor, p.id, right < p.x1 - actorWidth(env) / 2 ? right : left)
      }
      return
    case 'dragged':
      return
    case 'idle':
      if (act.look !== 0 && nextRandom(world) < dt * 0.25) act.look = range(world, -1, 1)
      return
    case 'sit': case 'sleep': case 'study':
      if (act.kind === 'sleep' && nextRandom(world) < dt * 0.5) world.events.push({ kind: 'zzz', id: actor.id })
      if (act.kind === 'study' && act.nap && nextRandom(world) < dt * 0.5) world.events.push({ kind: 'zzz', id: actor.id })
      if (act.kind === 'sit' && act.tired && nextRandom(world) < dt * 0.4) world.events.push({ kind: 'sweat', id: actor.id })
      if (now >= act.until) setIdle(world, actor, range(world, 0.4, 1))
      return
    case 'work':
      if (!busyApp(env.app)) { setIdle(world, actor, 0.3); return }
      if (now >= act.until) actor.act = { kind: 'work', until: now + 3 }
      if (nextRandom(world) < dt * 0.3) world.events.push({ kind: 'note', id: actor.id })
      return
    case 'watch': case 'listen': case 'blush': {
      const other = world.actors.find(a => a.id === act.to)
      if (other) face(actor, other.x)
      if (now >= act.until) setIdle(world, actor)
      return
    }
    case 'talk': case 'kiss': case 'hug': case 'highfive':
      if (now >= act.until) setIdle(world, actor, range(world, 0.6, 1.4))
      return
    default:
      if ('until' in act && now >= act.until) setIdle(world, actor, range(world, 0.4, 1.2))
  }
}

/** Someone not part of my scene stands in the way of my walk. */
function blocked(world: World, env: StageEnv, actor: Actor): boolean {
  const act = actor.act
  if (act.kind !== 'walk') return false
  const members = world.scene ? sceneMembers(world.scene) : []
  const gap = actorWidth(env) * 1.1
  return world.actors.some(other => other !== actor && !other.away && other.platform === actor.platform &&
    !(members.includes(other.id) && members.includes(actor.id)) &&
    !(other.act.kind === 'walk' && other.dir === actor.dir) && Math.sign(other.x - actor.x) === actor.dir &&
    Math.abs(other.x - actor.x) < gap && Math.abs(act.tx - actor.x) > Math.abs(other.x - actor.x) - gap * 0.5)
}
