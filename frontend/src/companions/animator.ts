/**
 * Turns a director actor into one frame of puppet motion: walk cycle timed to the distance
 * walked, breathing, springy hair/tail/ears, squash and stretch, blinks and mouth flaps.
 */
import {figureHeight} from './rig'
import type {Rig} from './rig'
import {restPose} from './pose'
import type {Pose} from './pose'
import {Spring} from './spring'
import type {Actor, Form, StageEnv} from './director'

export type Prop = 'laptop' | 'book' | 'notebook' | null
export type Frame = {
  pose: Pose
  /** 0 open .. 1 closed, for the eye and mouth ellipses. */
  eyes: number
  mouth: number
  blush: number
  form: Form
  /** Accessory tail polyline in sprite px (root first), or null. */
  tail: [number, number][] | null
  earAngles: [number, number]
  cushion: boolean
  desk: boolean
  prop: Prop
  /** Typing / writing / page phase for the prop animation. */
  propPhase: number
  glasses: boolean
  /** Fades the actor (0..1); used when it has nowhere to stand. */
  alpha: number
}

const TAU = Math.PI * 2
const clamp = (v: number, a: number, b: number) => Math.min(b, Math.max(a, v))

/** Small deterministic random per actor so blink timing never touches the director's seed. */
function seeded(seed: number) {
  let s = seed | 0
  return () => {
    s = (s + 0x6d2b79f5) | 0
    let t = Math.imul(s ^ (s >>> 15), s | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export class Animator {
  private random: () => number
  private time = 0
  private stepPhase = 0
  private flip = new Spring(1, 520, 46)
  private stretch = new Spring(1, 340, 13)
  private sit = new Spring(0, 90, 17)
  private lean = new Spring(0, 120, 16)
  private rot = new Spring(0, 70, 5)
  private hairL = new Spring(0, 46, 4.2)
  private hairR = new Spring(0, 42, 3.8)
  private tailBase = new Spring(0, 60, 6)
  private tailCurl = new Spring(0.32, 40, 6)
  private ear = new Spring(0, 160, 9)
  private nextBlink = 1.5
  private blinkAt = -1
  private mouthClosed = 1
  private nextMouth = 0
  private lastAct = ''
  private actStart = 0
  private lastX = 0
  private vx = 0
  private earTwitch = 0
  private nextTwitch = 2
  private study: Prop = null

  constructor(readonly rig: Rig, seed: number) {
    this.random = seeded(seed)
    this.nextBlink = 1 + this.random() * 3
  }

  frame(actor: Actor, env: StageEnv, now: number, dt: number, still: boolean): Frame {
    const rig = this.rig
    const pose = restPose(rig)
    const size = env.size * rig.height
    const unit = figureHeight(rig) / size   // sprite px per stage px
    pose.scale = 1 / unit
    pose.x = actor.x
    pose.y = actor.y
    const form = env.forms[rig.id]
    const base: Frame = {
      pose, eyes: 0, mouth: 0, blush: 0, form, tail: null, earAngles: [0, 0], cushion: false, desk: false, prop: null,
      propPhase: 0, glasses: false, alpha: actor.away ? 0 : 1,
    }
    if (still) {
      pose.flip = actor.dir === 1 ? -1 : 1
      base.tail = form === 'normal' || (form === 'cat' && rig.ownTail) ? null : this.tailShape(form, 0, 0.32, 0)
      return base
    }
    const t = (this.time += dt)
    const act = actor.act
    if (act.kind !== this.lastAct) { this.lastAct = act.kind; this.actStart = t }
    const since = t - this.actStart
    this.vx = dt > 0 ? (actor.x - this.lastX) / dt : 0
    if (Math.abs(this.vx) > size * 6) this.vx = 0
    this.lastX = actor.x
    const facing = actor.dir === 1 ? -1 : 1
    const flip = this.flip.step(facing, dt)
    pose.flip = Math.sign(flip || facing) * Math.max(0.1, Math.abs(flip))
    // Sprite space runs the other way when mirrored: motion toward +x on screen is -x in the art.
    const vxSprite = this.vx * unit * Math.sign(pose.flip)

    let breathRate = 3.4, breathDepth = 0.011
    let bodyY = 0, hipsRot = 0.008 * Math.sin(t * 0.9), torsoRot = 0, headRot = 0.025 * Math.sin(t * 0.55 + rig.id.length)
    let headX = 0, headY = 0, armL = 0.03 * Math.sin(t * 0.8), armR = -0.03 * Math.sin(t * 0.8 + 0.6)
    let legLRot = 0, legRRot = 0, legLLift = 0, legRLift = 0
    let sitTarget = 0, stretchTarget = 1, rotTarget = 0, leanTarget = 0
    let eyes = 0, mouth = 0, talking = false
    let tailWag = 0, tailCurl = 0.32, earFlat = 0
    let cushion = false, desk = false, prop: Prop = null, propPhase = 0, glasses = false
    let lift = 0   // stage px upward offset (hops in place)

    const walking = act.kind === 'walk'
    if (walking) {
      const run = act.run
      const stride = size * (run ? 0.5 : 0.36)
      this.stepPhase = (this.stepPhase + Math.abs(this.vx) * dt / stride) % 2
      const p = this.stepPhase, frac = p % 1, swing = Math.sin(Math.PI * frac)
      const amp = run ? 0.3 : 0.17, liftAmp = (run ? 20 : 11) * (figureHeight(rig) / 470)
      legLLift = p < 1 ? swing * liftAmp : 0
      legRLift = p >= 1 ? swing * liftAmp : 0
      legLRot = p < 1 ? amp * swing * 0.7 : -amp * 0.25 * swing
      legRRot = p >= 1 ? amp * swing * 0.7 : -amp * 0.25 * swing
      bodyY = -(run ? 11 : 6) * swing * (figureHeight(rig) / 470)
      hipsRot = (run ? 0.05 : 0.035) * Math.sin(Math.PI * p)
      torsoRot = -(run ? 0.1 : 0.035) + 0.015 * Math.sin(Math.PI * p)
      headRot = 0.03 * Math.sin(Math.PI * p + 0.6)
      armL = (run ? 0.45 : 0.22) * Math.sin(Math.PI * p)
      armR = (run ? 0.45 : 0.22) * Math.sin(Math.PI * p)
      if (run) stretchTarget = 1 + 0.05 * Math.sin(TAU * frac)
      breathRate = run ? 0.7 : 2.4
    }
    switch (act.kind) {
      case 'hop': {
        const h = act.t
        stretchTarget = h < 0.12 ? 0.86 : h < 0.55 ? 1.12 : 1.04
        legLLift = legRLift = 9; legLRot = 0.12; legRRot = -0.1
        armL = 0.55; armR = -0.55
        eyes = h > 0.3 && h < 0.7 ? 1 : 0
        break
      }
      case 'fall':
        stretchTarget = 1 + clamp(act.vy / size * 0.012, 0, 0.14)
        armL = 0.7; armR = -0.7; legLRot = 0.2 * Math.sin(t * 16); legRRot = -0.2 * Math.sin(t * 16 + 1)
        break
      case 'land':
        if (since < dt * 1.5) this.stretch.set(act.hard ? 0.7 : 0.84)
        break
      case 'dragged': {
        // Picked up by the head: dangles and swings with the pointer, feet kicking.
        pose.anchorX = rig.centerX
        pose.anchorY = rig.topY + figureHeight(rig) * 0.18
        rotTarget = clamp(-this.vx / size * 0.08, -0.7, 0.7)
        stretchTarget = 1.07
        legLRot = 0.28 * Math.sin(t * 13); legRRot = -0.28 * Math.sin(t * 13 + 1.3)
        legLLift = 6 + 6 * Math.sin(t * 13); legRLift = 6 + 6 * Math.sin(t * 13 + 1.3)
        armL = 0.75 + 0.1 * Math.sin(t * 9); armR = -0.75 - 0.1 * Math.sin(t * 9 + 1)
        breathRate = 0.8
        break
      }
      case 'sit': case 'sleep':
        sitTarget = 1
        cushion = !(act.kind === 'sit' && act.tired)
        armL = 0.12; armR = -0.12
        if (act.kind === 'sleep') {
          eyes = 1; mouth = 1; breathRate = 4.6; breathDepth = 0.02
          headRot = 0.16 + 0.02 * Math.sin(t * 1.4); headY = 5
        } else if (act.tired) {
          breathRate = 0.9; breathDepth = 0.028; headRot = 0.06; earFlat = 0.2
        }
        break
      case 'study': case 'work': {
        sitTarget = 1; desk = true; glasses = !!rig.glasses
        prop = act.kind === 'work' ? 'laptop' : this.studyProp()
        const nap = act.kind === 'study' && act.nap
        if (nap) {
          eyes = 1; mouth = 1; headRot = 0.22; headY = 9; breathRate = 4.8; breathDepth = 0.02
        } else if (prop === 'laptop') {
          propPhase = t
          armL = 0.06 + 0.05 * Math.sin(t * 19); armR = -0.06 - 0.05 * Math.sin(t * 21 + 1)
          headRot = 0.05 + 0.015 * Math.sin(t * 5); mouth = 1
        } else if (prop === 'notebook') {
          propPhase = t
          armR = -0.08 - 0.06 * Math.sin(t * 9); armL = 0.08
          headRot = 0.08 + 0.02 * Math.sin(t * 0.7)
          if (Math.sin(t * 0.45) > 0.85) { mouth = 1; headRot = -0.06 }   // looks up, taps the pencil
        } else {
          propPhase = t
          headRot = 0.1 + 0.02 * Math.sin(t * 0.5); armL = 0.1; armR = -0.1; mouth = 1
        }
        break
      }
      case 'talk':
        talking = true
        headRot += 0.04 * Math.sin(t * 6.5)
        headY = -1.5 * Math.abs(Math.sin(t * 6.5))
        armR = -0.12 - 0.12 * (0.5 + 0.5 * Math.sin(t * 2.6))
        break
      case 'listen':
        headRot = 0.07 + 0.02 * Math.sin(t * 1.2)
        headY = Math.sin(t * 2.2) > 0.92 ? 2 : 0
        break
      case 'watch':
        headRot = 0.06; mouth = Math.sin(t * 0.8) > 0.3 ? 1 : 0
        break
      case 'kiss':
        eyes = 1; mouth = 1
        if (act.giver) {
          torsoRot = -0.17; leanTarget = 0.05; bodyY = -6
          legRLift = 14; legRRot = -0.35; armL = 0.35; armR = -0.15
        } else { torsoRot = 0.05; headRot = -0.08; armL = -0.1; armR = 0.1 }
        break
      case 'hug':
        eyes = 1; mouth = 1; torsoRot = -0.2; armL = -0.35; armR = -0.55; headRot = -0.06
        leanTarget = 0.04
        break
      case 'blush':
        eyes = since < 0.7 ? 1 : 0; mouth = 1
        headRot = 0.08 * Math.sin(t * 2); armL = -0.12; armR = 0.12
        break
      case 'celebrate': {
        const cycle = (since * 2.1) % 1
        lift = size * 0.2 * Math.sin(Math.PI * cycle)
        stretchTarget = cycle < 0.08 || cycle > 0.94 ? 0.86 : 1.1
        armL = 0.7 + 0.1 * Math.sin(t * 12); armR = -0.7 - 0.1 * Math.sin(t * 12)
        legLLift = legRLift = 6 * Math.sin(Math.PI * cycle)
        eyes = cycle > 0.25 && cycle < 0.75 ? 1 : 0
        tailWag = 1
        break
      }
      case 'worried':
        pose.x += size * 0.012 * Math.sin(t * 38) * Math.max(0, 1 - since * 1.6)
        torsoRot = 0.05; headRot = -0.09; armL = -0.18; armR = 0.18; mouth = 1; earFlat = 1
        stretchTarget = 0.97
        break
      case 'groom':
        sitTarget = 1; cushion = false
        headRot = -0.14 + 0.05 * Math.sin(t * 7); eyes = 1
        armR = -0.45 - 0.18 * Math.sin(t * 7); armL = 0.1; mouth = Math.sin(t * 7) > 0 ? 1 : 0
        tailCurl = 0.5
        break
      case 'wag': {
        eyes = 1; tailWag = 1.4
        const cycle = (since * 2.6) % 1
        lift = size * 0.05 * Math.sin(Math.PI * cycle)
        headRot = 0.1 * Math.sin(t * 4)
        break
      }
      case 'tagged':
        if (since < dt * 1.5) this.stretch.set(0.76)
        eyes = since < 0.35 ? 1 : 0
        break
      case 'poked':
        if (since < dt * 1.5) { this.stretch.set(0.82); this.rot.kick(Math.sign(pose.flip) * 1.4) }
        eyes = since < 0.45 ? 1 : 0
        headRot = 0.12
        break
      case 'idle':
        headRot += act.look * 0.08
        break
    }
    if (act.kind === 'walk' && act.run) tailWag = 0.4

    // Springs: posture, squash, sway.
    const sit = this.sit.step(sitTarget, dt)
    const legLen = rig.footY - rig.hemY
    pose.legSy = 1 - 0.55 * sit
    bodyY += legLen * 0.55 * sit * 0.92
    legLRot += 0.32 * sit; legRRot -= 0.32 * sit
    pose.stretch = this.stretch.step(stretchTarget, dt)
    pose.rot = this.rot.step(rotTarget, dt) + this.lean.step(leanTarget * Math.sign(pose.flip), dt)
    pose.y -= lift
    const breath = Math.sin(TAU * t / breathRate)
    pose.breath = 1 + breathDepth * breath
    pose.bodyY = bodyY
    pose.hipsRot = hipsRot
    pose.torsoRot = torsoRot
    pose.headRot = headRot
    pose.headX = headX
    pose.headY = headY - breath * breathDepth * 30
    pose.armL = armL + breath * 0.02
    pose.armR = armR - breath * 0.02
    pose.legLRot = legLRot; pose.legRRot = legRRot; pose.legLLift = legLLift; pose.legRLift = legRLift

    // Secondary motion: hair trails the body's movement and counter-swings against the head.
    const drag = clamp(vxSprite * 0.0006, -0.1, 0.1)
    const wind = 0.012 * Math.sin(t * 1.1) + 0.007 * Math.sin(t * 2.3)
    const bob = walking ? (act.run ? 0.04 : 0.02) * Math.sin(Math.PI * this.stepPhase * 2) : 0
    pose.hairL = this.hairL.step(drag - headRot * 0.5 + wind + bob + (act.kind === 'dragged' ? -pose.rot * 0.6 : 0), dt)
    pose.hairR = this.hairR.step(drag - headRot * 0.5 + wind * 0.8 - bob + (act.kind === 'dragged' ? -pose.rot * 0.6 : 0), dt)
    const wag = tailWag > 0 ? tailWag * 0.32 * Math.sin(t * (form === 'dog' ? 17 : 10)) : 0
    const tailBase = this.tailBase.step(drag * 1.4 + 0.1 * Math.sin(t * 1.25) + wag, dt)
    const curl = this.tailCurl.step(tailCurl, dt)
    pose.tail = rig.ownTail ? clamp(tailBase, -0.3, 0.3) : 0
    if (t >= this.nextTwitch) { this.earTwitch = t; this.nextTwitch = t + 2 + this.random() * 5 }
    const twitch = t - this.earTwitch < 0.16 ? 0.18 : 0
    const earSwing = this.ear.step(earFlat * 0.28 + clamp(-vxSprite * 0.0004, -0.1, 0.1), dt)
    pose.earL = rig.ownEars ? -earSwing - twitch : 0
    pose.earR = rig.ownEars ? earSwing : 0

    // Face: blinks unless the eyes are already closed; mouth flaps only while a line is spoken.
    let blink = 0
    if (t >= this.nextBlink) {
      this.blinkAt = t
      this.nextBlink = t + (this.random() < 0.18 ? 0.28 : 2.2 + this.random() * 4)
    }
    const sinceBlink = t - this.blinkAt
    if (sinceBlink < 0.15) blink = sinceBlink < 0.05 ? sinceBlink / 0.05 : sinceBlink < 0.09 ? 1 : 1 - (sinceBlink - 0.09) / 0.06
    const eyesTarget = Math.max(eyes, blink)
    // Anime blinks swap the eyes in one frame; a cross-fade would show both eye drawings at once.
    const eyesValue = eyesTarget >= 0.5 ? 1 : 0
    if (talking && actor.bubble) {
      if (t >= this.nextMouth) { this.mouthClosed = this.mouthClosed > 0.5 ? 0 : 1; this.nextMouth = t + 0.06 + this.random() * 0.1 }
      mouth = this.mouthClosed
    }
    return {
      ...base,
      eyes: clamp(eyesValue, 0, 1),
      mouth,
      blush: clamp((actor.blushUntil - now) / 0.6, 0, 1),
      tail: (form === 'cat' && !rig.ownTail) || form === 'dog' ? this.tailShape(form, tailBase, curl, t) : null,
      earAngles: [-earSwing - twitch, earSwing],
      cushion, desk, prop, propPhase, glasses,
    }
  }

  private studyProp(): Prop {
    if (!this.study) this.study = this.rig.id === 'star' ? 'laptop' : this.rig.id === 'gemini' ? 'notebook' : 'book'
    return this.study
  }

  /** A cat tail curls up behind; a dog tail is short and perky. Wave travels root to tip. */
  private tailShape(form: Form, base: number, curl: number, t: number): [number, number][] {
    const rig = this.rig
    const scale = figureHeight(rig) / 470
    const points: [number, number][] = [[rig.tailRoot[0], rig.tailRoot[1]]]
    const cat = form === 'cat'
    const segments = cat ? 10 : 5
    const length = (cat ? 232 : 84) * scale / segments
    let angle = (cat ? 0.32 : -0.85) - base * (cat ? 1 : 1.6)
    for (let i = 1; i <= segments; i++) {
      angle -= (cat ? curl * 0.34 : 0.1) + (cat ? 0.06 * Math.sin(t * 2.1 - i * 0.55) : 0)
      const [x, y] = points[i - 1]
      points.push([x + Math.cos(angle) * length, y + Math.sin(angle) * length])
    }
    return points
  }
}
