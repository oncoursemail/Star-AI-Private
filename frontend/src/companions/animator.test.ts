import {describe, expect, it} from 'vitest'
import {compileCharacter} from './armature'
import {Animator, viseme} from './animator'
import type {Activity, Actor, Form, StageEnv} from './director'

const env = (forms: Partial<Record<'star' | 'ember' | 'astra' | 'gemini', Form>> = {}): StageEnv => ({
  platforms: [{id: 'floor', x0: 0, x1: 800, y: 400}], size: 92, app: 'idle', study: false, night: false, affection: true,
  forms: {star: 'normal', ember: 'normal', astra: 'normal', gemini: 'normal', ...forms}, still: false,
})
const actor = (act: Activity, x = 200): Actor => ({
  id: 'gemini', x, y: 400, platform: 'floor', dir: 1, act, path: [], running: false, away: false, bubble: null, blushUntil: 0, energy: 1, vx: 0,
})
const ACTS: Activity[] = [
  {kind: 'idle', until: 9, look: 0}, {kind: 'walk', tx: 900, run: false}, {kind: 'walk', tx: 900, run: true},
  {kind: 'hop', x0: 0, y0: 400, x1: 50, y1: 400, to: 'floor', t: 0.4, dur: 0.7, height: 40}, {kind: 'fall', vx: 0, vy: 10},
  {kind: 'land', until: 9, hard: true}, {kind: 'sit', until: 9, tired: false}, {kind: 'sit', until: 9, tired: true}, {kind: 'sleep', until: 9},
  {kind: 'talk', until: 9, to: null}, {kind: 'listen', until: 9, to: 'star'}, {kind: 'kiss', until: 9, to: 'star', giver: true},
  {kind: 'kiss', until: 9, to: 'star', giver: false}, {kind: 'hug', until: 9, to: 'star', giver: true}, {kind: 'highfive', until: 9, to: 'star', giver: false},
  {kind: 'blush', until: 9, to: 'star'}, {kind: 'celebrate', until: 9}, {kind: 'worried', until: 9}, {kind: 'work', until: 9},
  {kind: 'study', until: 9, nap: false}, {kind: 'study', until: 9, nap: true}, {kind: 'groom', until: 9}, {kind: 'wag', until: 9},
  {kind: 'tagged', until: 9}, {kind: 'poked', until: 9}, {kind: 'reach', until: 9}, {kind: 'dragged'},
]

describe('animator', () => {
  it('poses every activity with finite bones, travel in the side view, the rest facing us', () => {
    const anim = new Animator(compileCharacter('gemini', 0), 3)
    const partner = actor({kind: 'idle', until: 9, look: 0}, 260)
    for (const act of ACTS) {
      const a = actor(act)
      let frame = anim.frame(a, env(), 0, 1 / 60, false, {...partner, id: 'star'})
      for (let i = 0; i < 20; i++) { a.x += act.kind === 'walk' ? 1 : 0; frame = anim.frame(a, env(), i / 60, 1 / 60, false, {...partner, id: 'star'}) }
      for (const v of frame.sk.world) expect(Number.isFinite(v), act.kind).toBe(true)
      const side = act.kind === 'walk' || act.kind === 'hop' || act.kind === 'reach' || (act.kind === 'kiss' && act.giver)
      expect(frame.view, act.kind).toBe(side ? 'side' : 'front')
    }
  })

  it('plants the feet on the platform while walking', () => {
    const anim = new Animator(compileCharacter('ember', 1), 3)
    const a = actor({kind: 'walk', tx: 900, run: false})
    let lowest = 0
    for (let i = 0; i < 90; i++) {
      a.x += 0.75
      const f = anim.frame(a, env(), i / 60, 1 / 60, false)
      const sk = f.sk
      lowest = Math.max(sk.point(sk.bone('footF'), 5.8, 0.3)[1], sk.point(sk.bone('footF'), -2.3, 0.4)[1], sk.point(sk.bone('footK'), 5.8, 0.3)[1], sk.point(sk.bone('footK'), -2.3, 0.4)[1])
      expect(lowest).toBeCloseTo(400, 3)
    }
  })

  it('poofs into cat ears and a tail, then back, and Astra keeps her own', () => {
    const anim = new Animator(compileCharacter('star', 0), 3)
    const a = actor({kind: 'idle', until: 9, look: 0})
    a.id = 'star'
    let events = 0
    let f = anim.frame(a, env(), 0, 1 / 60, false)
    expect(f.sk.attachment[f.sk.slot('catF')]).toBeNull()
    for (let i = 0; i < 90; i++) { f = anim.frame(a, env({star: 'cat'}), i / 60, 1 / 60, false); events += f.events.filter(e => e.kind === 'poof').length }
    expect(events).toBeGreaterThan(0)
    expect(f.sk.attachment[f.sk.slot('catF')]).toBe('catF')
    expect(f.sk.attachment[f.sk.slot('tailCat')]).toBe('tailCat')
    for (let i = 0; i < 120; i++) f = anim.frame(a, env({star: 'normal'}), 2 + i / 60, 1 / 60, false)
    expect(f.sk.attachment[f.sk.slot('catF')]).toBeNull()

    const astra = new Animator(compileCharacter('astra', 2), 3)
    const b = actor({kind: 'idle', until: 9, look: 0}); b.id = 'astra'
    const g = astra.frame(b, env(), 0, 1 / 60, false)
    expect(g.sk.attachment[g.sk.slot('catF')]).toBe('catF')
  })

  it('brings out the study desk with a poof and puts it away again', () => {
    const anim = new Animator(compileCharacter('gemini', 0), 3)
    const a = actor({kind: 'study', until: 99, nap: false})
    let f = anim.frame(a, env(), 0, 1 / 60, false)
    expect(f.events.some(e => e.kind === 'propPoof')).toBe(true)
    for (let i = 0; i < 60; i++) f = anim.frame(a, env(), i / 60, 1 / 60, false)
    expect(f.sk.attachment[f.sk.slot('desk')]).toBe('desk')
    expect(f.sk.attachment[f.sk.slot('deskItem')]).toBe('notebook')
    expect(f.sk.attachment[f.sk.slot('glasses')]).toBe('studyGlasses')
    a.act = {kind: 'idle', until: 99, look: 0}
    f = anim.frame(a, env(), 1, 1 / 60, false)
    expect(f.events.some(e => e.kind === 'propPoof')).toBe(true)
    for (let i = 0; i < 90; i++) f = anim.frame(a, env(), 1 + i / 60, 1 / 60, false)
    expect(f.sk.attachment[f.sk.slot('desk')]).toBeNull()
  })

  it('moves the mouth with the bubble text', () => {
    expect(viseme('a')).toBe('wide')
    expect(viseme('o')).toBe('o')
    expect(viseme('m')).toBe('flat')
    expect(viseme(' ')).toBe('smile')
    const anim = new Animator(compileCharacter('gemini', 0), 3)
    const a = actor({kind: 'talk', until: 9, to: null})
    a.bubble = {text: 'Wow, so cool!', until: 9}
    const shapes = new Set<string>()
    for (let i = 0; i < 30; i++) { const f = anim.frame(a, env(), i / 60, 1 / 60, false); shapes.add(f.sk.attachment[f.sk.slot('mouth')] as string) }
    expect(shapes.size).toBeGreaterThan(2)
  })
})
