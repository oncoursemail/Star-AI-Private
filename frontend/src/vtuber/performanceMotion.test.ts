/** Contract tests; numerical motion is NOT evidence of an animated production model. */
import {describe,expect,it} from 'vitest'
import {StarPerformanceMotion} from './performanceMotion'

const frame = (overrides: Partial<Parameters<StarPerformanceMotion['step']>[0]> = {}) => ({
  dt: 1 / 60, speech: 0, laughter: 0, ...overrides,
})
const run = (controller: StarPerformanceMotion, frames: number, config = frame()) => {
  let pose = controller.snapshot()
  for (let i = 0; i < frames; i++) pose = controller.step(config)
  return pose
}

describe('Star performance rig targets', () => {
  it('starts neutral in human form without opening devices or broadcasts', () => {
    const controller = new StarPerformanceMotion()
    const pose = controller.snapshot()
    expect(pose.form).toBe('normal')
    expect(pose.animalVisibility).toBe(0)
    expect(pose.tail).toBe(0)
    expect(pose.hairLeft).toHaveLength(5)
    expect(pose.hairRight).toHaveLength(5)
    expect(pose.bangs).toHaveLength(3)
  })
  it('responds coherently to measured laughter and speech', () => {
    const p = run(new StarPerformanceMotion(), 35, frame({speech:.7,laughter:.85}))
    expect(p.jaw).toBeGreaterThan(.4)
    expect(p.mouthSmile).toBeGreaterThan(.5)
    expect(p.cheekRaise).toBeGreaterThan(.5)
    expect(p.eyeSquint).toBeGreaterThan(.4)
    expect(p.shoulders).toBeGreaterThan(0)
    expect(p.torso).toBeGreaterThan(0)
  })
  it('only pursues real measured gaze targets with bounded micro-movement', () => {
    const p = run(new StarPerformanceMotion(), 50, frame({gazeX:.7,gazeY:-.5,attention:'game'}))
    expect(p.gazeX).toBeGreaterThan(.6)
    expect(p.gazeY).toBeLessThan(-.4)
    expect(Math.abs(p.gazeX)).toBeLessThanOrEqual(1)
  })
  it('lets twin-tail tips follow after the roots instead of snapping together', () => {
    const model = new StarPerformanceMotion()
    const p = run(model, 8, frame({accelerationX:1,wind:.3}))
    expect(Math.abs(p.hairLeft[0])).toBeGreaterThan(Math.abs(p.hairLeft[4]))
    const later = run(model, 50, frame({accelerationX:1,wind:.3}))
    expect(Math.abs(later.hairLeft[4])).toBeGreaterThan(Math.abs(p.hairLeft[4]))
    expect(Math.abs(later.hairRight[4])).toBeGreaterThan(Math.abs(p.hairRight[4]))
  })
  it('does not let chat or model text force an animal transformation', () => {
    const m = new StarPerformanceMotion()
    expect(() => m.setForm('dog')).toThrow(/approve/i)
    expect(() => m.setForm('cat')).toThrow(/approve/i)
    expect(m.snapshot().form).toBe('normal')
    m.setForm('cat',true)
    expect(run(m, 50, frame()).form).toBe('cat')
    expect(m.snapshot().animalVisibility).toBeGreaterThan(.9)
    m.setForm('dog',true)
    expect(run(m, 50, frame()).form).toBe('dog')
    m.setForm('normal',true)
    expect(run(m, 50, frame()).animalVisibility).toBeLessThan(.1)
    expect(Math.abs(m.snapshot().tail)).toBeLessThan(.001)
  })
  it('uses distinct cat and dog tail behaviors after approved mode changes', () => {
    const dog = new StarPerformanceMotion(),cat = new StarPerformanceMotion()
    dog.setForm('dog',true);cat.setForm('cat',true)
    const a = run(dog,50,frame({laughter:.4})).tail
    const b = run(cat,50,frame({laughter:.4})).tail
    expect(Math.abs(a-b)).toBeGreaterThan(.015)
  })
  it('pauses without advancing physics and does not mutate returned arrays', () => {
    const m = new StarPerformanceMotion()
    run(m,8,frame({accelerationX:1}))
    const old = m.snapshot()
    const still = m.step(frame({dt:5,paused:true,accelerationX:-1}))
    expect(still).toEqual(old)
    const corrupt = m.snapshot().hairLeft as number[]
    corrupt[0] = 123
    expect(m.snapshot().hairLeft[0]).not.toBe(123)
  })
  it('limits extreme finite inputs and rejects NaNs and negative timesteps', () => {
    const m = new StarPerformanceMotion()
    const p = run(m,30,frame({speech:100,laughter:100,accelerationX:900,wind:900,gazeX:1000}))
    for (const [k,v] of Object.entries(p)) {
      if (typeof v === 'number') expect(Number.isFinite(v),String(k)).toBe(true)
    }
    expect(Math.abs(p.gazeX)).toBeLessThanOrEqual(1)
    expect(() => m.step(frame({dt:NaN}))).toThrow(/finite/i)
    expect(() => m.step(frame({dt:-.01}))).toThrow(/negative/i)
    expect(() => m.step(frame({dt:.01,laughter:Infinity}))).toThrow(/finite/i)
  })
  it('keeps deterministic state for repeatable offline review', () => {
    const a = new StarPerformanceMotion(), b = new StarPerformanceMotion()
    for (let i=0;i<90;i++) {
      const input=frame({accelerationX:i%4/4,wind:-.2,speech:i%3/3,laughter:(i%5===0?1:0)})
      expect(a.step(input)).toEqual(b.step(input))
    }
  })
  it('settles secondary movement toward neutral with reduced-motion mode', () => {
    const m = new StarPerformanceMotion()
    run(m,50,frame({wind:1,accelerationX:1,laughter:1}))
    const p = run(m,180,frame({reducedMotion:true}))
    expect(Math.abs(p.hairLeft[0])).toBeLessThan(.01)
    expect(Math.abs(p.hairLeft[4])).toBeLessThan(.01)
    expect(Math.abs(p.skirt)).toBeLessThan(.01)
  })
})
