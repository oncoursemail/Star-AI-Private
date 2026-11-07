/**
 * Turns a director actor into one frame of skeletal animation: picks the view (side for travel and
 * two-character moments, front for everything else), plays and cross-fades keyframed clips, plants the
 * feet, runs the spring chains, and drives the face (blinks, visemes from the bubble text), the animal
 * ears and tails (with the poof when the form changes) and the study props.
 */
import type {CastId} from './cast'
import {STYLES} from './cast'
import type {View} from './art'
import type {Character} from './armature'
import {makeChains} from './armature'
import {Skeleton, POSE_STRIDE} from './skeleton'
import type {SpringChain} from './physics'
import {ClipPlayer} from './clips'
import type {Clip} from './clips'
import {CLIPS, MIRRORED, RUN_STRIDE, WALK_STRIDE} from './animations'
import type {ClipName} from './animations'
import {Spring} from './spring'
import type {Actor, Form, StageEnv} from './director'

export type AnimEvent = { kind: 'poof' | 'propPoof' | 'clap'; x: number; y: number }
export type Frame = {
  view: View
  sk: Skeleton
  alpha: number
  events: AnimEvent[]
}

type ViewState = { sk: Skeleton; chains: Map<string, SpringChain>; feet: [string, number, number][] }
type Animal = 'cat' | 'dog' | null
type StudyItem = 'laptop' | 'book' | 'notebook'

const DEG = Math.PI / 180
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))

/** Small deterministic random per actor, so face timing never touches the director's seed. */
function seeded(seed: number) {
  let s = seed | 0
  return () => {
    s = (s + 0x6d2b79f5) | 0
    let t = Math.imul(s ^ (s >>> 15), s | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Mouth shape for a character of the bubble text (a rough viseme map). */
export function viseme(ch: string | undefined): string {
  if (!ch) return 'smile'
  const c = ch.toLowerCase()
  if ('a'.includes(c)) return 'wide'
  if ('ou'.includes(c)) return 'o'
  if ('eiy'.includes(c)) return 'open'
  if ('mbp'.includes(c)) return 'flat'
  if (/[\s.,!?…~-]/.test(c)) return 'smile'
  return 'open'
}

const FEET: Record<View, [string, number, number][]> = {
  front: [['footF', -6.9, 0.4], ['footF', -0.9, 0.4], ['footK', 0.9, 0.4], ['footK', 6.9, 0.4]],
  side: [['footF', -2.3, 0.4], ['footF', 5.8, 0.3], ['footK', -2.3, 0.4], ['footK', 5.8, 0.3]],
}
const STUDY_ITEM: Record<CastId, StudyItem> = {star: 'laptop', ember: 'book', astra: 'book', gemini: 'notebook'}
const HAPPY = new Set(['idle', 'celebrate', 'wag', 'walk', 'talk', 'blush'])

export class Animator {
  readonly id: CastId
  private views: Record<View, ViewState>
  private view: View = 'front'
  private base = new ClipPlayer()
  private extra = new ClipPlayer()
  private random: () => number
  private time = 0
  private phase = 0
  private flip = new Spring(1, 360, 30)
  private swap = new Spring(1, 420, 18)
  private squash = new Spring(1, 520, 12)
  private bounce = new Spring(0, 260, 9)
  private rot = new Spring(0, 60, 6)
  private hold = new Spring(0, 400, 40)
  private reachX = new Spring(0, 90, 18)
  private earScale = new Spring(0, 320, 11)
  private propScale = new Spring(0, 300, 13)
  private earTwitch = [new Spring(0, 900, 16), new Spring(0, 900, 16)]
  private shown: Animal = null
  private wanted: Animal = null
  private desk = false
  private deskShown = false
  private glassesOn = false
  private lastAct = ''
  private actStart = 0
  private lastX = 0
  private vx = 0
  private nextBlink = 2
  private blinkAt = -9
  private nextExtra = 4
  private nextTwitch = 3
  private nextPage = 3
  private pageAt = -9
  private bubbleText = ''
  private bubbleAt = 0
  private clapped = false
  private unit = 1
  private events: AnimEvent[] = []

  constructor(readonly character: Character, seed: number) {
    this.id = character.id
    this.random = seeded(seed)
    const make = (v: View): ViewState => ({sk: new Skeleton(character.views[v].armature), chains: makeChains(character.views[v]), feet: FEET[v]})
    this.views = {front: make('front'), side: make('side')}
    this.nextBlink = 1 + this.random() * 3
    const style = STYLES[this.id]
    this.wanted = this.shown = style.catByNature ? 'cat' : null
    this.earScale.set(this.shown ? 1 : 0)
  }

  get skeleton(): Skeleton { return this.views[this.view].sk }

  /** A point carried by a bone (model units in that view's setup space), in stage px. */
  point(bone: string, mx: number, my: number): [number, number] {
    const sk = this.skeleton, b = sk.bone(bone)
    return b >= 0 ? sk.point(b, mx, my) : [0, 0]
  }

  /** Top of the head and the feet, in stage px (for bubbles and the pointer hit box). */
  bounds(): {x0: number; y0: number; x1: number; y1: number; headX: number; headY: number} {
    const [hx, hy] = this.point('head', this.view === 'side' ? 0 : 0, -100)
    const [fx, fy] = this.point('root', 0, 0)
    const w = 30 * this.unit
    return {x0: Math.min(hx, fx) - w, x1: Math.max(hx, fx) + w, y0: Math.min(hy, fy), y1: Math.max(hy, fy), headX: hx, headY: hy}
  }

  frame(actor: Actor, env: StageEnv, now: number, dt: number, still: boolean, partner: Actor | null = null): Frame {
    const style = STYLES[this.id]
    this.unit = env.size * style.height / 100
    this.events = []
    const act = actor.act
    const t = (this.time += still ? 0 : dt)
    if (act.kind !== this.lastAct) { this.lastAct = act.kind; this.actStart = t; this.clapped = false }
    const since = t - this.actStart
    this.vx = dt > 0 && !still ? (actor.x - this.lastX) / dt : 0
    if (Math.abs(this.vx) > env.size * 8) this.vx = 0
    this.lastX = actor.x

    // ----- choose the view and the clip -----
    const pick = this.choose(actor, since, partner)
    const clip: Clip = pick.mirror && pick.clip in MIRRORED ? MIRRORED[pick.clip as keyof typeof MIRRORED] : CLIPS[pick.clip]
    const facing = actor.dir
    const f = still ? (this.flip.set(facing), facing) : this.flip.step(facing, dt)
    const turning = pick.view === 'side' && Math.abs(f) < 0.4
    const view: View = turning ? 'front' : pick.view
    if (turning) { pick.clip = 'idle'; pick.ground = true }
    if (view !== this.view) {
      this.view = view
      this.views[view].chains.forEach(c => c.reset())
      if (!still) this.swap.set(0.78)
      this.base.play(clip, 0, pick.from ?? 0)
    } else this.base.play(clip, pick.fade ?? 0.2, pick.from ?? 0)
    const state = this.views[view], sk = state.sk
    sk.resetPose()

    if (!still) {
      if (pick.clip === 'walk' || pick.clip === 'run') {
        // The cycle advances with the ground covered, so the planted foot does not slide.
        const stride = (pick.clip === 'run' ? RUN_STRIDE : WALK_STRIDE) * this.unit
        this.phase = (this.phase + Math.abs(this.vx) * dt / stride) % 1
        this.base.time = this.phase * this.base.clip!.dur
        this.base.advance(0)
      } else if (pick.sampleAt !== undefined) {
        this.base.time = pick.sampleAt * this.base.clip!.dur
        this.base.advance(dt)
        this.base.time = pick.sampleAt * this.base.clip!.dur
      } else this.base.advance(dt)
    }
    this.base.apply(sk)

    // Idle variations: look around, stretch, sway.
    if (act.kind === 'idle' && !still && !actor.bubble) {
      if (t >= this.nextExtra && since > 1.5) {
        const options: ClipName[] = ['lookAround', 'stretch', 'sway', 'lookAround']
        this.extra.play(CLIPS[options[Math.floor(this.random() * options.length)]], 0)
        this.nextExtra = t + 6 + this.random() * 7
      }
    } else if (this.extra.clip && act.kind !== 'idle') this.extra.clip = null
    if (this.extra.clip) {
      this.extra.advance(dt)
      if (this.extra.done) this.extra.clip = null
      else this.extra.apply(sk)
    }
    if (act.kind === 'idle') {
      this.add(sk, 'head', act.look * 5)
      this.addX(sk, 'pupilF', act.look * 0.7); this.addX(sk, 'pupilK', act.look * 0.7)
    }

    // Breathing on top of everything (slow when sleeping, quick after running).
    const breathRate = act.kind === 'sleep' || (act.kind === 'study' && act.nap) ? 4.4 : act.kind === 'sit' && act.tired ? 1 : 3.4
    const breath = still ? 0 : Math.sin(t * Math.PI * 2 / breathRate)
    this.scale(sk, 'chest', 0, breath * 0.012)
    this.addY(sk, 'head', -breath * 0.25)

    // Raised arms switch to the copies drawn over the head.
    const up = view === 'front' && (!!this.base.clip?.armsUp || !!this.extra.clip?.armsUp)
    for (const side of ['F', 'K']) {
      const hand = sk.attachment[sk.slot('hand' + side)]
      sk.setAttachment('arm' + side + 'Up', up ? 'arm' + side : null)
      sk.setAttachment('hand' + side + 'Up', up ? hand : null)
      if (up) { sk.setAttachment('arm' + side, null); sk.setAttachment('hand' + side, null) }
    }
    this.face(sk, actor, now, t, still, view)
    this.animal(sk, actor, env, t, dt, still, view)
    this.props(sk, actor, t, dt, still, view)

    // ----- root transform -----
    const swap = this.swap.step(1, dt)
    let sx = view === 'side' ? f : (turning ? 0.72 + 0.28 * Math.abs(f) / 0.4 : 1)
    if (view === 'side' && Math.abs(sx) < 0.4) sx = Math.sign(sx || 1) * 0.4
    sx *= swap
    if (act.kind === 'land' && since < dt * 1.5 && !still) { this.squash.set(act.hard ? 0.68 : 0.84); if (act.hard) this.bounce.kick(-70) }
    if ((act.kind === 'tagged' || act.kind === 'poked') && since < dt * 1.5 && !still) this.rot.kick(-actor.dir * 1.2)
    const sq = still ? 1 : this.squash.step(1, dt)
    const lift = still ? 0 : this.bounce.step(0, dt)
    const dragged = act.kind === 'dragged'
    const hold = still ? (dragged ? 1 : 0) : this.hold.step(dragged ? 1 : 0, dt)
    const rot = still ? 0 : this.rot.step(dragged ? clamp(-this.vx / env.size * 0.12, -0.6, 0.6) : 0, dt)
    const k = this.unit
    // Two-character moments: step in so the contact points meet (cheek, shoulders, palms).
    let reach = 0
    if (partner && (act.kind === 'kiss' || act.kind === 'hug' || act.kind === 'highfive')) {
      const gap = Math.abs(partner.x - actor.x) / k
      const want = act.kind === 'hug' ? 30 : act.kind === 'kiss' ? 36 : 49
      const share = act.kind === 'kiss' ? (act.giver ? 0.85 : 0.15) : 0.5
      reach = clamp((gap - want) * share, 0, 26) * Math.sign(partner.x - actor.x)
    }
    const rx = still ? reach : this.reachX.step(reach, dt)
    const cos = Math.cos(rot), sin = Math.sin(rot)
    const hx = -sin * 92 * k * hold, hy = cos * 92 * k * hold
    // Squash and stretch keep the volume: wider when squashed. Scaling is around the feet.
    const wide = sx * (1 + (1 - sq) * 0.8)
    const root = [cos * wide * k, sin * wide * k, -sin * sq * k, cos * sq * k, actor.x + rx * k + hx, actor.y + hy + lift * k * 0.1]
    sk.updateWorld(root)
    if (pick.ground && !dragged) this.plant(sk, state, actor.y + lift * k * 0.1)
    if (pick.clip === 'run' && !still) {
      // Flight phase between the strides: both feet leave the ground.
      const fly = 2.6 * Math.pow(Math.max(0, Math.cos(Math.PI * 4 * (this.phase - 0.47))), 2) * k
      for (let i = 0; i < sk.count; i++) sk.world[i * 6 + 5] -= fly
    }
    if (!still) for (const [name, chain] of state.chains) if (this.chainVisible(sk, name)) chain.apply(sk, root, dt, k)

    // High five: a clap of sparkles where the palms meet.
    if (act.kind === 'highfive' && !this.clapped && since > CLIPS.highfive.dur * 0.44) {
      this.clapped = true
      const hand = partner && partner.x < actor.x ? 'handF' : 'handK'
      const [x, y] = this.point(hand, hand === 'handF' ? -12.1 : 12.1, -23)
      this.events.push({kind: 'clap', x, y})
    }
    return {view, sk, alpha: actor.away ? 0 : 1, events: this.events}
  }

  // ---------------------------------------------------------------- choices

  private choose(actor: Actor, since: number, partner: Actor | null): {view: View; clip: ClipName; ground: boolean; fade?: number; sampleAt?: number; from?: number; mirror?: boolean} {
    const act = actor.act
    const mirror = !!partner && partner.x < actor.x
    switch (act.kind) {
      case 'walk': return {view: 'side', clip: act.run ? 'run' : 'walk', ground: true, fade: 0.15}
      case 'hop': return {view: 'side', clip: 'hop', ground: false, fade: 0.08, sampleAt: act.t}
      case 'fall': return {view: 'front', clip: 'fall', ground: false}
      case 'land': return {view: this.view, clip: 'idle', ground: true, fade: 0.25}
      case 'dragged': return {view: 'front', clip: 'dangle', ground: false, fade: 0.12}
      case 'sit':
        return {view: 'front', clip: act.tired ? 'flop' : 'sit', ground: false, fade: 0.35}
      case 'sleep': return {view: 'front', clip: 'sleep', ground: false, fade: 0.5}
      case 'study': return {view: 'front', clip: act.nap ? 'nap' : 'study', ground: false, fade: 0.4}
      case 'work': return {view: 'front', clip: 'study', ground: false, fade: 0.4}
      case 'talk': return {view: 'front', clip: 'talk', ground: true}
      case 'listen': case 'watch': return {view: 'front', clip: 'listen', ground: true, fade: 0.3}
      // Cheek kiss: the giver leans in from the side, the other faces us and gets it on the cheek.
      case 'kiss': return act.giver ? {view: 'side', clip: 'kissGive', ground: false} : {view: 'front', clip: 'kissGet', ground: true, mirror}
      // Side hug and high five face us: arm over the shoulders, palms meeting between them.
      case 'hug': return {view: 'front', clip: act.giver ? 'hugGive' : 'hugGet', ground: true, mirror}
      case 'highfive': return {view: 'front', clip: 'highfive', ground: true, mirror}
      case 'blush': return {view: 'front', clip: 'shy', ground: true, fade: 0.3}
      case 'celebrate': return {view: 'front', clip: 'cheer', ground: false, fade: 0.1}
      case 'worried': return {view: 'front', clip: 'worried', ground: true}
      case 'groom': return {view: 'front', clip: 'groom', ground: true}
      case 'wag': return {view: 'front', clip: 'wag', ground: false}
      case 'tagged': return {view: 'front', clip: 'startle', ground: false, fade: 0.05}
      case 'poked': return {view: 'front', clip: 'poked', ground: true, fade: 0.05}
      case 'reach': return {view: 'side', clip: 'reach', ground: true, fade: 0.08}
      default: return {view: 'front', clip: 'idle', ground: true, fade: since < 0.01 ? 0.3 : 0.3}
    }
  }

  // ---------------------------------------------------------------- face

  private face(sk: Skeleton, actor: Actor, now: number, t: number, still: boolean, view: View) {
    const sides = view === 'front' ? ['F', 'K'] : ['F']
    // Blinks only over open eyes (a clip may have closed them on purpose).
    if (!still && t >= this.nextBlink) { this.blinkAt = t; this.nextBlink = t + (this.random() < 0.2 ? 0.32 : 2.4 + this.random() * 3.6) }
    const b = t - this.blinkAt
    const blink = b < 0.05 ? 'half' : b < 0.11 ? 'closed' : b < 0.16 ? 'half' : null
    for (const s of sides) {
      const lash = sk.slot('lash' + s)
      if (lash < 0) continue
      let now = sk.attachment[lash] ?? ('open' + s)
      if (blink && now === 'open' + s) { now = blink + s; sk.attachment[lash] = now }
      const shut = now.startsWith('closed') || now.startsWith('happy') || now.startsWith('squeeze')
      sk.setAttachment('white' + s, shut ? null : 'white' + s)
      sk.setAttachment('iris' + s, shut ? null : 'iris' + s)
    }
    // Visemes follow the bubble text as it is revealed (same 42 characters a second as the bubble).
    const text = actor.bubble?.text ?? ''
    if (text !== this.bubbleText) { this.bubbleText = text; this.bubbleAt = t }
    const act = actor.act.kind
    if (text && act !== 'sleep' && act !== 'kiss' && !(actor.act.kind === 'study' && actor.act.nap)) {
      const i = still ? text.length : Math.floor((t - this.bubbleAt) * 42)
      if (i < text.length) sk.setAttachment('mouth', viseme(text[i]))
    }
    for (const s of sides) { const b = sk.slot('brow' + s); if (b >= 0) sk.alpha[b] = 0.7 }
    const blush = sk.slot('blush')
    if (blush >= 0) sk.alpha[blush] = clamp((actor.blushUntil - now) / 0.6, 0, 1)
  }

  // ---------------------------------------------------------------- ears, tails, poof

  private animal(sk: Skeleton, actor: Actor, env: StageEnv, t: number, dt: number, still: boolean, view: View) {
    const style = STYLES[this.id]
    const form: Form = env.forms[this.id]
    this.wanted = form === 'normal' ? (style.catByNature ? 'cat' : null) : form
    if (this.wanted !== this.shown) {
      if (still) { this.shown = this.wanted; this.earScale.set(this.shown ? 1 : 0) }
      else if (this.shown && this.earScale.value > 0.08) {
        if (this.earScale.value > 0.95 && Math.abs(this.earScale.velocity) < 1) this.poof(sk)
        this.earScale.step(-0.2, dt)
      } else {
        this.shown = this.wanted
        this.earScale.set(0)
        if (this.shown) { this.poof(sk); this.earScale.kick(2) }
        this.views.front.chains.forEach(c => c.reset()); this.views.side.chains.forEach(c => c.reset())
      }
    }
    const scale = still ? (this.shown ? 1 : 0) : (this.wanted === this.shown ? this.earScale.step(this.shown ? 1 : 0, dt) : this.earScale.value)
    const cat = this.shown === 'cat', dog = this.shown === 'dog'
    const ears = view === 'front' ? ['F', 'K'] : ['F', 'K']
    for (const s of ears) {
      sk.setAttachment('cat' + s, cat && scale > 0.01 ? 'cat' + s : null)
      sk.setAttachment('dog' + s, dog && scale > 0.01 ? 'dog' + s : null)
      this.scale(sk, 'cat' + s + '0', Math.max(0, scale) - 1, Math.max(0, scale) - 1)
      this.scale(sk, 'dog' + s + '0', Math.max(0, scale) - 1, Math.max(0, scale) - 1)
    }
    sk.setAttachment('tailCat', cat && scale > 0.01 ? 'tailCat' : null)
    sk.setAttachment('tailDog', dog && scale > 0.01 ? 'tailDog' : null)
    this.scale(sk, 'tailCat0', Math.max(0, scale) - 1, Math.max(0, scale) - 1)
    this.scale(sk, 'tailDog0', Math.max(0, scale) - 1, Math.max(0, scale) - 1)
    if (still) return
    const act = actor.act.kind
    // Cat: perky ears that twitch now and then, a slow tail swish (a wave down the tail).
    if (cat) {
      if (t >= this.nextTwitch) { this.earTwitch[Math.floor(this.random() * 2)].kick(-14); this.nextTwitch = t + 1.8 + this.random() * 4.5 }
      const flat = act === 'worried' || act === 'poked' ? 22 : 0
      this.add(sk, 'catF0', this.earTwitch[0].step(0, dt) - flat * (view === 'front' ? -1 : 1) * 0.5)
      this.add(sk, 'catK0', -this.earTwitch[1].step(0, dt) + flat * 0.5)
      const speed = act === 'walk' ? 2.6 : 1.4
      for (let i = 0; i < 5; i++) this.add(sk, 'tailCat' + i, 10 * Math.sin(t * speed - i * 0.75) + (act === 'celebrate' ? 6 * Math.sin(t * 6 - i) : 0))
    }
    // Dog: floppy ears are pure physics; the tail wags fast when happy, slow otherwise.
    if (dog) {
      const happy = HAPPY.has(act)
      const amp = act === 'wag' || act === 'celebrate' ? 30 : happy ? 18 : 6
      const rate = act === 'wag' || act === 'celebrate' ? 19 : happy ? 13 : 4
      this.add(sk, 'tailDog0', amp * Math.sin(t * rate))
      this.add(sk, 'tailDog1', amp * 0.4 * Math.sin(t * rate - 0.9))
      if (act === 'tagged' || act === 'poked') { this.add(sk, 'dogF0', view === 'front' ? 35 : -35); this.add(sk, 'dogK0', -35) }
    }
  }

  private poof(sk: Skeleton) {
    const [hx, hy] = sk.point(sk.bone('head'), 0, -86)
    const [tx, ty] = sk.point(sk.bone('hips'), 0, -24)
    this.events.push({kind: 'poof', x: hx, y: hy}, {kind: 'poof', x: tx, y: ty})
  }

  private chainVisible(sk: Skeleton, name: string): boolean {
    if (name.startsWith('cat') || name.startsWith('dog')) return sk.attachment[sk.slot(name.slice(0, 4))] !== null
    if (name === 'tailCat' || name === 'tailDog') return sk.attachment[sk.slot(name)] !== null
    return true
  }

  // ---------------------------------------------------------------- study props

  private props(sk: Skeleton, actor: Actor, t: number, dt: number, still: boolean, view: View) {
    const act = actor.act
    const desk = view === 'front' && (act.kind === 'study' || act.kind === 'work')
    const cushion = view === 'front' && (desk || act.kind === 'sleep' || (act.kind === 'sit' && !act.tired))
    if (desk !== this.desk) {
      this.desk = desk
      if (!still) { const [x, y] = this.point('root', 0, -20); this.events.push({kind: 'propPoof', x, y}) }
      if (desk) { this.deskShown = true; this.propScale.set(0); this.propScale.kick(3) }
    }
    const shown = desk || cushion
    const target = shown ? 1 : 0
    const scale = still ? target : this.propScale.step(target, dt)
    if (!desk && scale < 0.05) this.deskShown = false
    const item: StudyItem = act.kind === 'work' ? 'laptop' : STUDY_ITEM[this.id]
    const on = this.deskShown && view === 'front'
    sk.setAttachment('cushion', view === 'front' && (cushion || (on && scale > 0.05)) ? 'cushion' : null)
    sk.setAttachment('desk', on ? 'desk' : null)
    sk.setAttachment('deskItem', on ? item : null)
    sk.setAttachment('glow', on && item === 'laptop' ? 'glow' : null)
    sk.setAttachment('pencil', on && item === 'notebook' ? 'pencil' : null)
    this.scale(sk, 'prop', Math.max(0, scale) - 1, Math.max(0, scale) - 1)
    const style = STYLES[this.id]
    const glasses = on && desk && !style.glasses
    if (glasses !== this.glassesOn) { this.glassesOn = glasses }
    if (!style.glasses) sk.setAttachment('glasses', glasses && scale > 0.6 ? 'studyGlasses' : null)
    if (!on || still) { sk.setAttachment('page', null); return }
    const nap = act.kind === 'study' && act.nap
    if (item === 'laptop') {
      const g = sk.slot('glow')
      if (g >= 0) sk.alpha[g] = 0.55 + 0.25 * Math.sin(t * 2.3) + (nap ? -0.3 : 0)
      if (!nap) {
        // Typing: the hands patter on the keys.
        this.addY(sk, 'handF', -Math.max(0, Math.sin(t * 17)) * 0.9)
        this.addY(sk, 'handK', -Math.max(0, Math.sin(t * 19 + 1.3)) * 0.9)
        this.add(sk, 'head', 1.5 * Math.sin(t * 0.7))
      }
    } else if (item === 'book') {
      if (!nap && t >= this.nextPage) { this.pageAt = t; this.nextPage = t + 3 + this.random() * 3 }
      const p = (t - this.pageAt) / 0.7
      if (p >= 0 && p <= 1 && !nap) {
        sk.setAttachment('page', 'page')
        this.scale(sk, 'page', -2 * p, 0)
        this.addY(sk, 'page', -Math.sin(Math.PI * p) * 1.6)
        this.add(sk, 'armUK', 6 * Math.sin(Math.PI * p))
      } else sk.setAttachment('page', null)
      if (!nap) this.add(sk, 'head', 4 + 1.5 * Math.sin(t * 0.5))
    } else {
      sk.setAttachment('page', null)
      if (!nap) {
        // Writing with little pauses to tap the pencil and think.
        const thinking = Math.sin(t * 0.5) > 0.75
        if (thinking) { this.add(sk, 'pencil', 10 * Math.sin(t * 18)); this.add(sk, 'head', -4); this.addX(sk, 'pupilF', 0.8); this.addX(sk, 'pupilK', 0.8) }
        else { this.addX(sk, 'handK', Math.sin(t * 9) * 0.8); this.addY(sk, 'handK', Math.cos(t * 9) * 0.4); this.add(sk, 'head', 4) }
      }
    }
  }

  // ---------------------------------------------------------------- helpers

  /** Lift the skeleton so the lowest sole touches the ground (keeps planted feet on the platform). */
  private plant(sk: Skeleton, state: ViewState, ground: number) {
    let lowest = -Infinity
    for (const [bone, x, y] of state.feet) {
      const b = sk.bone(bone)
      if (b < 0) continue
      lowest = Math.max(lowest, sk.point(b, x, y)[1])
    }
    if (!Number.isFinite(lowest)) return
    const dy = ground - lowest
    for (let i = 0; i < sk.count; i++) sk.world[i * 6 + 5] += dy
  }

  private add(sk: Skeleton, bone: string, deg: number) { const b = sk.bone(bone); if (b >= 0) sk.pose[b * POSE_STRIDE] += deg * DEG }
  private addX(sk: Skeleton, bone: string, v: number) { const b = sk.bone(bone); if (b >= 0) sk.pose[b * POSE_STRIDE + 1] += v }
  private addY(sk: Skeleton, bone: string, v: number) { const b = sk.bone(bone); if (b >= 0) sk.pose[b * POSE_STRIDE + 2] += v }
  private scale(sk: Skeleton, bone: string, dx: number, dy: number) { const b = sk.bone(bone); if (b >= 0) { sk.pose[b * POSE_STRIDE + 3] += dx; sk.pose[b * POSE_STRIDE + 4] += dy } }
}

export type {Clip}
