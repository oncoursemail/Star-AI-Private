import {useId, useLayoutEffect, useRef, useState} from 'react'
import type {ReactNode} from 'react'
import type {ActivityRun} from './activity'
import './run-aura.css'

/** A visual projection of a real, currently running backend turn. No timed/fake stages. */
export type RunAuraPhase = 'idle' | 'working' | 'researching' | 'verifying' | 'stopping'

export function runAuraPhase(run: ActivityRun | null | undefined, stopping = false): RunAuraPhase {
  if (!run || run.outcome !== 'running') return 'idle'
  if (stopping) return 'stopping'
  // Only the latest active, backend-reported step determines the accent.
  // We must not show verification simply because a generic tool is running.
  let current: ActivityRun['steps'][number] | undefined
  for (let index = run.steps.length - 1; index >= 0; index--) {
    if (run.steps[index].state === 'running') {
      current = run.steps[index]
      break
    }
  }
  // The backend can emit either the dedicated luau_check progress type or a
  // tool lifecycle event with the checker name; both are real evidence.
  if (current?.kind === 'tool' && (current.id === 'luau-check' || current.detail === 'star_luau_check')) return 'verifying'
  if (current?.kind === 'search') return 'researching'
  return 'working'
}

/** Lightweight, original rim treatment for the existing Litha/STAR composer.
 * It never draws another input surface, changes the controls, or affects focus.
 * Two SVG strokes share one path; no JS animation loop, per-token rerender or
 * unlicensed BoardUI Pro code. Screen-reader status stays in ActivityTimeline.
 */
export function RunAura({phase, children}: {phase: RunAuraPhase; children: ReactNode}) {
  const root = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({width: 640, height: 96})
  const id = 'litha-aura-' + useId().replace(/[^a-zA-Z0-9_-]/g, '')

  useLayoutEffect(() => {
    const element = root.current
    if (!element) return
    const measure = () => {
      const bounds = element.getBoundingClientRect()
      const width = Math.round(bounds.width)
      const height = Math.round(bounds.height)
      if (width > 0 && height > 0) {
        setSize(previous => previous.width === width && previous.height === height
          ? previous : {width, height})
      }
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const x = 1.5
  const width = Math.max(1, size.width - x * 2)
  const height = Math.max(1, size.height - x * 2)
  const radius = Math.max(0, Math.min(12, width / 2, height / 2))
  const rect = {x, y: x, width, height, rx: radius, pathLength: 100, fill: 'none' as const}
  const gradient = id + '-gradient'
  const glow = id + '-glow'

  return (
    <div ref={root} className="litha-run-aura" data-phase={phase} data-testid="litha-run-aura">
      <span className="litha-run-aura-fx" aria-hidden="true">
        <svg width="100%" height="100%" viewBox={`0 0 ${size.width} ${size.height}`} preserveAspectRatio="none">
          <defs>
            <linearGradient id={gradient} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="var(--star-gold-soft)" />
              <stop offset="48%" stopColor="var(--star-gold-hover)" />
              <stop offset="100%" stopColor="var(--star-gold)" />
            </linearGradient>
            <filter id={glow} x="-30%" y="-100%" width="160%" height="300%">
              <feGaussianBlur stdDeviation="2.5" />
            </filter>
          </defs>
          <rect {...rect} stroke={`url(#${gradient})`} strokeWidth="5" strokeDasharray="18 82"
            filter={`url(#${glow})`} className="litha-run-aura-glow" />
          <rect {...rect} stroke={`url(#${gradient})`} strokeWidth="1.8" strokeDasharray="18 82"
            className="litha-run-aura-trace" />
        </svg>
      </span>
      {children}
    </div>
  )
}
