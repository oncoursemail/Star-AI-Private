/**
 * STAR's render-agnostic expressive motion prototype.
 *
 * Separates an audio/gameplay-driven primary pose from damped, physically coupled
 * secondary motion. Produces numbers, NOT a rig, model, audio, control or stream.
 *
 * Integrators have bounded fixed substeps and never touch files, microphone,
 * broadcasts, accounts, game inputs, or model/tool permissions. Runtime adapters
 * must supply REAL measured audio envelopes and verified events. Visual quality
 * requires authored meshes, constraints and native capture review.
 */
export type Form = 'normal' | 'cat' | 'dog'
export type Attention = 'game' | 'chat' | 'idle'
export type MotionSignals = Readonly<{
  /** Seconds since preceding animation frame (the renderer's measured dt). */
  dt: number
  /** Source-audio amplitudes, 0..1. Do not infer them from text! */
  speech: number
  laughter: number
  /** Coded direct animation input, NOT a simulated physiological measurement. */
  surprise?: number
  /** Character root acceleration scaled into [-1,1], from the trusted rig host. */
  accelerationX?: number
  wind?: number
  gazeX?: number
  gazeY?: number
  /** Explicit blink weights, 0=open, 1=closed. */
  blink?: number
  attention?: Attention
  paused?: boolean
  reducedMotion?: boolean
}>

export type MotionPose = Readonly<{
  form: Form
  headTilt: number
  shoulders: number
  torso: number
  jaw: number
  mouthSmile: number
  cheekRaise: number
  eyeSquint: number
  blink: number
  gazeX: number
  gazeY: number
  hairLeft: readonly number[]
  hairRight: readonly number[]
  bangs: readonly number[]
  skirt: number
  leftRibbon: number
  rightRibbon: number
  earLeft: number
  earRight: number
  tail: number
  animalVisibility: number
}>

const TAU = 2 * Math.PI
const STEP = 1 / 120
const clamp = (v: number, lo = -1, hi = 1): number => Math.min(hi, Math.max(lo, v))
const number = (value: number | undefined, fallback = 0): number => {
  if (value === undefined) return fallback
  if (!Number.isFinite(value)) throw new TypeError('STAR motion requires finite signals')
  return value
}

/** Physically inspired second-order damped response in animation parameter space. */
class Spring {
  value = 0
  velocity = 0
  constructor(private strength: number, private damping: number) {}
  tick(target: number, dt: number): number {
    this.velocity += (this.strength * (target - this.value) - this.damping * this.velocity) * dt
    this.value += this.velocity * dt
    return this.value
  }
  set(value = 0): void { this.value = value; this.velocity = 0 }
}

/**
 * Treat left/right tails as a chain whose tip's target is its predecessor.
 * A static authored curl is still essential: these are only dynamic offsets.
 */
export class StarPerformanceMotion {
  private form: Form = 'normal'
  private time = 0
  private head = new Spring(85, 16)
  private shoulders = new Spring(95, 20)
  private torso = new Spring(68, 16)
  private gazeX = new Spring(260, 30)
  private gazeY = new Spring(260, 30)
  private jaw = new Spring(310, 32)
  private smile = new Spring(110, 20)
  private cheeks = new Spring(140, 22)
  private squint = new Spring(180, 23)
  private blink = new Spring(480, 40)
  private hairL = Array.from({length: 5}, (_, i) => new Spring(100 - i * 12, 17 - i))
  private hairR = Array.from({length: 5}, (_, i) => new Spring(93 - i * 10, 17 - i))
  private bangs = Array.from({length: 3}, (_, i) => new Spring(110 - i * 10, 18 - i))
  private skirt = new Spring(65, 14)
  private ribbonL = new Spring(80, 14)
  private ribbonR = new Spring(85, 15)
  private earL = new Spring(140, 17)
  private earR = new Spring(150, 18)
  private tail = new Spring(40, 10)
  private visibility = new Spring(120, 20)
  private pose: MotionPose = {
    form: 'normal', headTilt: 0, shoulders: 0, torso: 0, jaw: 0,
    mouthSmile: 0, cheekRaise: 0, eyeSquint: 0, blink: 0, gazeX: 0,
    gazeY: 0, hairLeft: Object.freeze([0,0,0,0,0]), hairRight: Object.freeze([0,0,0,0,0]),
    bangs: Object.freeze([0,0,0]), skirt: 0, leftRibbon: 0, rightRibbon: 0,
    earLeft: 0, earRight: 0, tail: 0, animalVisibility: 0,
  }

  /** Form changes require a human-authorized UI action, not model or chat text. */
  setForm(form: Form, ownerConfirmed = false): void {
    if (form !== 'normal' && form !== 'cat' && form !== 'dog') throw new TypeError('Unknown STAR form')
    if (form !== this.form && !ownerConfirmed) throw new Error('Owner must approve mode changes')
    this.form = form
    if (form === 'normal') { this.earL.set(); this.earR.set(); this.tail.set() }
  }

  reset(): void {
    this.time = 0
    for (const s of [this.head, this.shoulders, this.torso, this.gazeX, this.gazeY,
      this.jaw, this.smile, this.cheeks, this.squint, this.blink, this.skirt, this.ribbonL,
      this.ribbonR, this.earL, this.earR, this.tail, this.visibility,
      ...this.hairL, ...this.hairR, ...this.bangs]) s.set()
    this.pose = {...this.pose, form: this.form, headTilt: 0, shoulders: 0, torso: 0,
      jaw: 0, mouthSmile: 0, cheekRaise: 0, eyeSquint: 0, blink: 0,
      gazeX: 0, gazeY: 0, hairLeft: [0,0,0,0,0], hairRight: [0,0,0,0,0],
      bangs: [0,0,0], skirt: 0, leftRibbon: 0, rightRibbon: 0,
      earLeft: 0, earRight: 0, tail: 0, animalVisibility: 0}
  }

  snapshot(): MotionPose {
    return {...this.pose, hairLeft: [...this.pose.hairLeft], hairRight: [...this.pose.hairRight],
      bangs: [...this.pose.bangs]}
  }

  step(signals: MotionSignals): MotionPose {
    const dt = number(signals.dt)
    if (dt < 0) throw new RangeError('Negative animation timestep')
    if (signals.paused || dt === 0) return this.snapshot()
    const speech = clamp(number(signals.speech), 0, 1)
    const laugh = clamp(number(signals.laughter), 0, 1)
    const surprise = clamp(number(signals.surprise), 0, 1)
    const ax = clamp(number(signals.accelerationX))
    const wind = clamp(number(signals.wind))
    const gx = clamp(number(signals.gazeX))
    const gy = clamp(number(signals.gazeY))
    const blink = clamp(number(signals.blink), 0, 1)
    const reduced = signals.reducedMotion === true
    const attention: Attention = signals.attention ?? 'idle'
    if (!['idle','game','chat'].includes(attention)) throw new TypeError('Unknown attention state')
    // Frozen source changes and large GPU stalls do not create huge physics impulses.
    let remain = Math.min(dt, 0.1)
    while (remain > 1e-7) {
      const h = Math.min(STEP, remain)
      remain -= h
      this.time += h
      const phase = this.time * TAU
      const laughPulse = laugh * Math.sin(phase * 5)
      const breathing = reduced ? 0 : Math.sin(phase * 0.19) * 0.012
      const headTarget = reduced ? 0 : clamp(-ax * 0.12 + laughPulse * 0.08 + surprise * 0.12, -0.3, 0.3)
      const headTilt = this.head.tick(headTarget, h)
      const shoulder = this.shoulders.tick(reduced ? 0 : laugh * (0.15 + 0.13 * Math.sin(phase * 5 + 0.4)), h)
      const torso = this.torso.tick(reduced ? 0 : shoulder * 0.55 + breathing, h)
      const jaw = this.jaw.tick(Math.max(speech * 0.78, laugh * 0.78), h)
      const smile = this.smile.tick(clamp(0.18 + laugh * 0.72, 0, 1), h)
      const cheeks = this.cheeks.tick(laugh * 0.85, h)
      const squint = this.squint.tick(laugh * 0.78 + surprise * 0.08, h)
      const eyeBlink = this.blink.tick(Math.max(blink, laugh * 0.42), h)
      const microX = reduced ? 0 : 0.012 * Math.sin(phase * (attention === 'game' ? 1.16 : 0.71))
      const eyesX = this.gazeX.tick(clamp(gx + microX), h)
      const eyesY = this.gazeY.tick(gy, h)
      const hairInput = reduced ? 0 : clamp(-headTilt * 0.45 - ax * 0.25 + wind * 0.12)
      let left = hairInput
      let right = hairInput * 0.91
      for (let i = 0; i < this.hairL.length; i++) {
        left = this.hairL[i].tick(clamp(left * (1.12 - 0.03 * i)), h)
        right = this.hairR[i].tick(clamp(right * (1.09 - 0.01 * i)), h)
      }
      let bang = reduced ? 0 : -headTilt * 0.2 - ax * 0.06
      for (const s of this.bangs) bang = s.tick(clamp(bang), h)
      const skirt = this.skirt.tick(reduced ? 0 : clamp(-ax * 0.11 + torso * 0.5), h)
      const ribbonL = this.ribbonL.tick(reduced ? 0 : clamp(left * 0.88), h)
      const ribbonR = this.ribbonR.tick(reduced ? 0 : clamp(right * 0.88), h)
      const show = this.visibility.tick(this.form === 'normal' ? 0 : 1, h)
      const earLeft = this.earL.tick(reduced || this.form === 'normal' ? 0 : headTilt * 0.32 + laughPulse * 0.09, h)
      const earRight = this.earR.tick(reduced || this.form === 'normal' ? 0 : -headTilt * 0.24 + laughPulse * 0.06, h)
      const tail = this.tail.tick(reduced || this.form === 'normal' ? 0 :
        (this.form === 'dog' ? Math.sin(phase * 2.9) * (0.17 + laugh * 0.15) :
          Math.sin(phase * 0.64) * 0.15), h)
      this.pose = {
        form: this.form, headTilt, shoulders: shoulder, torso, jaw,
        mouthSmile: smile, cheekRaise: cheeks, eyeSquint: squint, blink: eyeBlink,
        gazeX: eyesX, gazeY: eyesY,
        hairLeft: this.hairL.map(s => clamp(s.value)), hairRight: this.hairR.map(s => clamp(s.value)),
        bangs: this.bangs.map(s => clamp(s.value)), skirt, leftRibbon: ribbonL,
        rightRibbon: ribbonR, earLeft, earRight, tail, animalVisibility: show,
      }
    }
    return this.snapshot()
  }
}
