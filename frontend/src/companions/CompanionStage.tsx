/**
 * The living companions in the chat: a WebGL canvas along the bottom of the conversation where
 * Star, Ember, Astra and Gemini walk the free margins and the top edge of the composer. Decorative
 * only (aria-hidden); it stops when hidden, and stands still for reduced motion or the still choice.
 */
import {useEffect, useRef} from 'react'
import type {PetState} from '../StarPet'
import type {CompanionPreferences} from '../companion-catalog'
import {useStarReducedMotion} from '../MotionPolicy'
import {usePageVisible} from '../usePageVisible'
import {CAST} from './cast'
import type {CastId} from './cast'
import {compileCharacter} from './armature'
import {Animator} from './animator'
import type {AnimEvent, Frame} from './animator'
import {createWorld, dragTo, grab, poke, release, stepWorld} from './director'
import type {Actor, AppActivity, Form, Platform, StageEnv, StageEvent, World} from './director'
import {CompanionRenderer} from './renderer'
import type {DrawItem} from './renderer'
import './companion-stage.css'

export type CompanionStageProps = {
  app: PetState
  preferences: CompanionPreferences
  reducedMotion: boolean
  /** STAR is learning on this PC (night school), for the automatic study looks. */
  learning: boolean
  /** Empty chat: the composer sits mid-screen and the whole bottom edge is free. */
  empty: boolean
  /** Browser preview only: `?companions=` flags and a scripting handle for design review captures. */
  preview?: boolean
}

export const webgl2Available = () => typeof window !== 'undefined' && typeof window.WebGL2RenderingContext !== 'undefined'

const APP: Record<PetState, AppActivity> = {
  idle: 'idle', typing: 'typing', thinking: 'thinking', streaming: 'streaming', finished: 'finished',
  error: 'error', cancelled: 'cancelled', sleepy: 'idle', asleep: 'idle', update: 'update',
}

/** Walkable platforms in thread coordinates. */
export function measurePlatforms(thread: HTMLElement, empty: boolean, size: number, readingHistory: boolean, typing: boolean): Platform[] {
  const box = thread.getBoundingClientRect()
  const floor = box.height - 6
  const dock = thread.querySelector('.dock')?.getBoundingClientRect()
  const composer = thread.querySelector('.cmp')?.getBoundingClientRect()
  const width = size * 0.6
  if (empty || !dock || !composer || dock.bottom < box.top + box.height - size * 1.4) {
    return [{id: 'floor', x0: 8, x1: box.width - 8, y: floor}]
  }
  const left = composer.left - box.left, right = composer.right - box.left
  const platforms: Platform[] = []
  if (left - 16 >= width * 1.1) platforms.push({id: 'floor-l', x0: 6, x1: left - 10, y: floor})
  if (!readingHistory) platforms.push({id: 'ledge', x0: left + 16, x1: right - 16, y: dock.top - box.top + 3, quiet: typing})
  if (box.width - right - 16 >= width * 1.1) platforms.push({id: 'floor-r', x0: right + 10, x1: box.width - 6, y: floor})
  return platforms
}

type Bubble = { text: string; shown: number; started: number }

/** Write a style property only when it changes: every write costs the page a style recalculation. */
function setStyle(node: HTMLElement, name: 'top' | 'height' | 'width' | 'display' | 'transform' | 'maxWidth', value: string) {
  if (node.style[name] !== value) node.style[name] = value
}

export function CompanionStage({app, preferences, reducedMotion, learning, empty, preview = false}: CompanionStageProps) {
  const host = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLCanvasElement>(null)
  const bubbles = useRef(new Map<CastId, HTMLDivElement>())
  const hits = useRef(new Map<CastId, HTMLDivElement>())
  const pageVisible = usePageVisible()
  const policyReduced = useStarReducedMotion()
  const still = reducedMotion || policyReduced || preferences.motion === 'still'
  const cast = CAST.filter(id => preferences.cast.includes(id))
  const castKey = cast.join(',')
  const flags = useRef(preview ? new Set((new URLSearchParams(window.location.search).get('companions') || '').split(',')) : new Set<string>())
  const live = useRef({app, preferences, learning, empty, still, pageVisible})
  live.current = {app, preferences, learning, empty, still, pageVisible}
  const kick = useRef<() => void>(() => undefined)

  useEffect(() => { kick.current() }, [app, preferences, learning, empty, still, pageVisible])

  useEffect(() => {
    const root = host.current, surface = canvas.current
    const thread = root?.parentElement
    if (!root || !surface || !thread || !cast.length || !webgl2Available()) return
    const renderer = CompanionRenderer.create(surface)
    if (!renderer) return
    let disposed = false
    let raf = 0
    let last = 0
    let measured = 0
    let world: World | null = null
    let platforms: Platform[] = []
    let size = 92
    let readingHistory = false
    let band = {top: 0, height: 0, width: 0}
    const characters = cast.map((id, page) => compileCharacter(id, page))
    const animators = new Map(characters.map((c, index) => [c.id, new Animator(c, 97 + index * 31)]))
    const said = new Map<CastId, Bubble>()
    const frames = new Map<CastId, Frame>()
    const scroll = thread.querySelector<HTMLElement>('.thread-scroll')

    // Preview-only overrides for design review captures (forms and study switched live, to see the poof).
    const review: {forms: Partial<Record<CastId, Form>>; study: boolean | null; frozen: boolean} = {forms: {}, study: null, frozen: false}
    const env = (): StageEnv => {
      const {preferences: prefs, app: work, learning: learn, still: quiet} = live.current
      const f = flags.current
      const hour = new Date().getHours()
      const form = (id: CastId): Form => review.forms[id] ?? (f.has('cat') ? 'cat' : f.has('dog') ? 'dog' : prefs.forms[id])
      return {
        platforms, size,
        app: APP[work] ?? 'idle',
        study: review.study ?? (f.has('study') || prefs.study === 'on' || (prefs.study === 'auto' && learn)),
        night: f.has('night') || hour >= 23 || hour < 5,
        affection: prefs.affection,
        forms: {star: form('star'), ember: form('ember'), astra: form('astra'), gemini: form('gemini')},
        still: quiet,
      }
    }

    const measure = () => {
      const box = thread.getBoundingClientRect()
      size = box.width < 640 ? 74 : 92
      readingHistory = !!scroll && !live.current.empty && scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight > 80
      platforms = measurePlatforms(thread, live.current.empty, size, readingHistory, live.current.app === 'typing')
      const dragging = world?.actors.some(a => a.act.kind === 'dragged' || a.act.kind === 'fall')
      const top = dragging || !platforms.length ? 0 : Math.max(0, Math.min(...platforms.map(p => p.y)) - size * 2.3)
      band = {top, height: Math.max(1, box.height - top), width: box.width}
      setStyle(surface, 'top', top + 'px')
      setStyle(surface, 'height', band.height + 'px')
      setStyle(surface, 'width', band.width + 'px')
      renderer.resize(band.width, band.height, Math.min(2, window.devicePixelRatio || 1), 0, top)
    }

    const emit = (event: StageEvent) => {
      const frame = frames.get(event.id)
      const animator = animators.get(event.id)
      const actor = world?.actors.find(a => a.id === event.id)
      if (!frame || !animator || !actor) return
      // Offsets are in the old sprite px (about 4.7 per model unit) from the top of the head.
      const head = (dx: number, dy: number) => animator.point('head', dx / 4.7, -100 + dy / 4.7)
      const s = size / 92
      const r = () => Math.random() - 0.5
      if (event.kind === 'dust') {
        const [x, y] = [actor.x, actor.y]
        for (const side of [-1, 1]) renderer.emit({item: 'dust', x: x + side * size * 0.14, y: y - 3, vx: side * 28 * s, vy: -8, life: 0.42, size: 10 * s, spin: 0, kind: 'burst'})
      } else if (event.kind === 'heart') {
        const [x, y] = head(r() * 60, 0)
        renderer.emit({item: 'heart', x, y, vx: r() * 14, vy: -36 * s, life: 1.7, size: 17 * s, spin: Math.random() * 6, kind: 'float'})
      } else if (event.kind === 'sparkle') {
        for (let i = 0; i < 3; i++) {
          const [x, y] = head(r() * 160, 20 + r() * 80)
          renderer.emit({item: 'sparkle', x, y, vx: r() * 60, vy: -30 - Math.random() * 30, life: 0.9, size: 14 * s, spin: r() * 4, kind: 'burst'})
        }
      } else if (event.kind === 'sweat') {
        const [x, y] = head(70, 70)
        renderer.emit({item: 'sweat', x, y, vx: 8, vy: 0, life: 0.9, size: 13 * s, spin: 0, kind: 'fall'})
      } else if (event.kind === 'zzz') {
        const [x, y] = head(60, 10)
        renderer.emit({item: 'zzz', x, y, vx: 9 * s, vy: -17 * s, life: 2.4, size: 13 * s, spin: 0, kind: 'drift'})
      } else if (event.kind === 'note') {
        const [x, y] = head(r() * 100, 10)
        renderer.emit({item: 'note', x, y, vx: r() * 10, vy: -26 * s, life: 1.5, size: 14 * s, spin: Math.random() * 6, kind: 'float'})
      } else {
        const [x, y] = head(40, -30)
        renderer.emit({item: event.kind, x, y, vx: 0, vy: -6, life: 0.95, size: 22 * s, spin: 0, kind: 'pop'})
      }
    }

    const effect = (event: AnimEvent) => {
      const s = size / 92
      const burst = (count: number, speed: number) => {
        for (let i = 0; i < count; i++) {
          const a = (i / count) * Math.PI * 2 + Math.random() * 0.5
          renderer.emit({item: 'smoke', x: event.x, y: event.y, vx: Math.cos(a) * speed * s, vy: Math.sin(a) * speed * s * 0.7, life: 0.55 + Math.random() * 0.15, size: 15 * s, spin: (Math.random() - 0.5) * 3, kind: 'puff'})
        }
        for (let i = 0; i < 4; i++) {
          const a = Math.random() * Math.PI * 2
          renderer.emit({item: i % 2 ? 'sparkle' : 'twinkle', x: event.x, y: event.y, vx: Math.cos(a) * speed * 1.3 * s, vy: Math.sin(a) * speed * s - 20 * s, life: 0.7, size: 11 * s, spin: (Math.random() - 0.5) * 6, kind: 'burst'})
        }
      }
      if (event.kind === 'poof') burst(7, 70)
      else if (event.kind === 'propPoof') burst(9, 110)
      else for (let i = 0; i < 5; i++) {
        const a = (i / 5) * Math.PI * 2
        renderer.emit({item: i % 2 ? 'twinkle' : 'sparkle', x: event.x, y: event.y, vx: Math.cos(a) * 80 * s, vy: Math.sin(a) * 80 * s, life: 0.5, size: 12 * s, spin: 3, kind: 'burst'})
      }
    }

    const place = (dt: number) => {
      if (!world) return
      const e = env()
      const draws: DrawItem[] = []
      const partnerOf = (actor: Actor) => 'to' in actor.act ? world?.actors.find(a => a.id === (actor.act as {to: CastId | null}).to) ?? null : null
      const zOf = (actor: Actor) => actor.y + (actor.act.kind === 'dragged' ? 10000 : 0)
      for (const actor of world.actors) {
        const animator = animators.get(actor.id)
        if (!animator) continue
        const partner = partnerOf(actor)
        const frame = animator.frame(actor, e, world.now, dt, e.still, partner)
        frames.set(actor.id, frame)
        for (const ev of frame.events) effect(ev)
        const act = actor.act
        const giver = (act.kind === 'hug' || act.kind === 'kiss' || act.kind === 'highfive') && act.giver
        // The giver is drawn in front: the hugging arm lies over the partner's shoulders.
        draws.push({sk: frame.sk, alpha: frame.alpha, z: zOf(actor) + (giver ? 1 : 0)})
      }
      for (const event of world.events) emit(event)
      renderer.render(draws, dt)
      for (const actor of world.actors) {
        const frame = frames.get(actor.id)
        const animator = animators.get(actor.id)
        const hit = hits.current.get(actor.id), bubble = bubbles.current.get(actor.id)
        if (!frame || !animator) continue
        const box = animator.bounds()
        const [x0, y0, x1, y1] = [box.x0, box.y0, box.x1, box.y1]
        if (hit) {
          const shown = !actor.away && frame.alpha > 0.5
          setStyle(hit, 'display', shown ? '' : 'none')
          setStyle(hit, 'transform', `translate(${Math.round(Math.min(x0, x1))}px, ${Math.round(Math.min(y0, y1))}px)`)
          setStyle(hit, 'width', Math.round(Math.abs(x1 - x0)) + 'px')
          setStyle(hit, 'height', Math.round(Math.abs(y1 - y0)) + 'px')
        }
        if (!bubble) continue
        const text = actor.bubble?.text ?? ''
        let state = said.get(actor.id)
        if (!text || actor.away) {
          if (state) { said.delete(actor.id); bubble.classList.remove('is-on') }
          continue
        }
        if (!state || state.text !== text) {
          state = {text, shown: 0, started: world.now}
          said.set(actor.id, state)
          bubble.classList.add('is-on')
        }
        const count = e.still ? text.length : Math.min(text.length, Math.ceil((world.now - state.started) * 42))
        if (count !== state.shown) { state.shown = count; bubble.textContent = text.slice(0, count) }
        const [hx, hy] = [box.headX, box.headY + size * 0.02]
        const onLedge = actor.platform === 'ledge'
        const side = onLedge ? (hx > band.width / 2 ? 'left' : 'right') : 'above'
        bubble.dataset.side = side
        // In a side margin the bubble stays inside the margin, so it never covers the composer.
        const lane = platforms.find(p => p.id === actor.platform)
        const room = lane && lane.id !== 'ledge' && lane.id !== 'floor' ? lane.x1 - lane.x0 + 8 : 172
        setStyle(bubble, 'maxWidth', Math.max(92, Math.min(172, room)) + 'px')
        const bw = bubble.offsetWidth, bh = bubble.offsetHeight
        let bx = side === 'above' ? hx - bw / 2 : side === 'left' ? hx - size * 0.3 - bw : hx + size * 0.3
        if (lane && side === 'above' && lane.id !== 'floor') bx = Math.max(lane.x0 - 4, Math.min(lane.x1 + 4 - bw, bx))
        const by = side === 'above' ? hy - bh - 8 : hy + size * 0.12
        setStyle(bubble, 'transform', `translate(${Math.round(Math.max(4, Math.min(band.width - bw - 4, bx)))}px, ${Math.round(Math.max(4, by))}px)`)
      }
    }

    // Only breathing and blinking on screen: 30 frames a second is enough and halves the cost.
    const CALM = new Set(['idle', 'sit', 'sleep', 'study', 'listen', 'watch', 'work'])
    const calm = () => !!world && !renderer.particles.length && world.scene === null &&
      world.actors.every(a => CALM.has(a.act.kind) && !a.bubble)
    const tick = (time: number) => {
      raf = 0
      if (disposed || !world || review.frozen) return
      if (last && calm() && time - last < 30) { raf = requestAnimationFrame(tick); return }
      // Still mode ticks on demand: its clock follows the wall so bubbles expire on time.
      const dt = last ? Math.min(live.current.still ? 1 : 0.05, (time - last) / 1000) : 1 / 60
      last = time
      // Layout moves without resizing (the empty-chat transition, banners): look again twice a second.
      if (time - measured > 500) { measured = time; measure() }
      stepWorld(world, env(), dt)
      place(dt)
      if (!live.current.still && live.current.pageVisible) raf = requestAnimationFrame(tick)
      // Still mode draws on demand; look again so a poke's bubble also goes away.
      else if (world.actors.some(a => a.bubble)) window.setTimeout(() => kick.current(), 400)
    }

    kick.current = () => {
      if (disposed || !world) return
      measure()
      if (!raf && live.current.pageVisible) { if (!live.current.still) last = 0; raf = requestAnimationFrame(tick) }
    }

    const observer = new ResizeObserver(() => kick.current())
    observer.observe(thread)
    const dock = thread.querySelector('.dock')
    if (dock) observer.observe(dock)
    const onScroll = () => {
      const wasReading = readingHistory
      const now = !!scroll && scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight > 80
      if (now !== wasReading) kick.current()
    }
    scroll?.addEventListener('scroll', onScroll, {passive: true})

    // Pointer: press and drag to pick a companion up, release to drop; a press without a drag pokes.
    const detach: (() => void)[] = []
    for (const id of cast) {
      const hit = hits.current.get(id)
      if (!hit) continue
      let start: {x: number; y: number; t: number} | null = null
      let dragging = false
      let trail: {x: number; y: number; t: number}[] = []
      const local = (event: PointerEvent) => {
        const box = thread.getBoundingClientRect()
        return {x: event.clientX - box.left, y: event.clientY - box.top, t: event.timeStamp}
      }
      const down = (event: PointerEvent) => {
        if (event.button !== 0 || !world) return
        event.preventDefault()
        hit.setPointerCapture?.(event.pointerId)
        start = local(event); trail = [start]; dragging = false
      }
      const move = (event: PointerEvent) => {
        if (!start || !world) return
        const p = local(event)
        trail.push(p); if (trail.length > 6) trail.shift()
        if (!dragging && Math.hypot(p.x - start.x, p.y - start.y) > 6 && !live.current.still) {
          dragging = true
          grab(world, id, p.x, p.y)
          root.dataset.dragging = 'true'
          measure()
        }
        if (dragging) dragTo(world, id, p.x, p.y)
        kick.current()
      }
      const up = (event: PointerEvent) => {
        if (!start || !world) return
        const p = local(event)
        if (dragging) {
          const first = trail[0]
          const span = Math.max(16, p.t - first.t) / 1000
          release(world, id, (p.x - first.x) / span * 0.6, (p.y - first.y) / span * 0.6)
          delete root.dataset.dragging
        } else poke(world, env(), id)
        start = null; dragging = false
        kick.current()
      }
      const cancel = () => { if (dragging && world) release(world, id, 0, 0); start = null; dragging = false; delete root.dataset.dragging }
      hit.addEventListener('pointerdown', down)
      hit.addEventListener('pointermove', move)
      hit.addEventListener('pointerup', up)
      hit.addEventListener('pointercancel', cancel)
      detach.push(() => {
        hit.removeEventListener('pointerdown', down); hit.removeEventListener('pointermove', move)
        hit.removeEventListener('pointerup', up); hit.removeEventListener('pointercancel', cancel)
      })
    }

    renderer.load(characters).then(() => {
      if (disposed) return
      measure()
      world = createWorld(cast, env(), 7 + cast.length)
      stepWorld(world, env(), 0)
      if (preview) {
        (window as unknown as {__starCompanions?: unknown}).__starCompanions = {
          world, env, renderer, animators,
          /** Stop the clock; `advance` then steps it in fixed frames (frame-exact captures). */
          freeze: () => { review.frozen = true; if (raf) cancelAnimationFrame(raf); raf = 0 },
          advance: (seconds: number, fps = 30) => {
            if (!world) return
            for (let i = 0, n = Math.max(1, Math.round(seconds * fps)); i < n; i++) { stepWorld(world, env(), 1 / fps); place(1 / fps) }
          },
          setForm: (id: CastId | 'all', form: Form) => { for (const c of id === 'all' ? cast : [id]) review.forms[c] = form; kick.current() },
          setStudy: (on: boolean | null) => { review.study = on; kick.current() },
          scene: (kind: string) => {
            if (!world) return
            world.next.banter = world.next.tag = world.next.affection = Infinity
            if (kind === 'tag') world.next.tag = world.now
            if (kind === 'kiss' || kind === 'hug' || kind === 'highfive') {
              const a = world.actors.find(x => world?.actors.some(y => y !== x && y.platform === x.platform && !!x.platform))
              const b = a && world.actors.find(y => y !== a && y.platform === a.platform)
              if (a && b) { const p = platforms.find(x => x.id === a.platform); if (p) b.x = Math.min(p.x1 - size * 0.4, Math.max(p.x0 + size * 0.4, a.x + size * 1.6)) }
              if (a && b) world.scene = {kind: 'affection', a: a.id, b: b.id, type: kind, phase: 'approach', until: world.now + 9}
            }
            if (kind === 'banter') world.next.banter = world.now
            kick.current()
          },
        }
      }
      kick.current()
    }).catch(() => { /* Missing art leaves the stage empty; the chat is unaffected. */ })

    return () => {
      disposed = true
      if (raf) cancelAnimationFrame(raf)
      observer.disconnect()
      scroll?.removeEventListener('scroll', onScroll)
      detach.forEach(off => off())
      renderer.dispose()
      kick.current = () => undefined
      if (preview) delete (window as unknown as {__starCompanions?: unknown}).__starCompanions
    }
    // castKey stands for the cast list; everything else is read live from refs.
  }, [castKey, preview]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!cast.length || !webgl2Available()) return null
  return <div ref={host} className="companion-stage" aria-hidden="true" data-still={still || undefined}>
    <canvas ref={canvas} className="companion-stage__canvas"/>
    {cast.map(id => <div key={id} className="companion-stage__hit" data-companion={id}
      ref={node => { if (node) hits.current.set(id, node); else hits.current.delete(id) }}/>)}
    {cast.map(id => <div key={id} className="companion-stage__bubble" data-companion={id}
      ref={node => { if (node) bubbles.current.set(id, node); else bubbles.current.delete(id) }}/>)}
  </div>
}
