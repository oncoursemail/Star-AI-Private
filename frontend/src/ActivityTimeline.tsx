import {useEffect, useId, useState} from 'react'
import {AnimatePresence, motion} from 'motion/react'
import {Ban, Check, ChevronDown, Circle, CircleSlash, LoaderCircle, ShieldQuestion, Square, X} from 'lucide-react'
import {countDone, formatElapsed, headline, runElapsed, stateWord, stepElapsed} from './activity'
import type {ActivityRun, ActivityStep, StepState} from './activity'
import {collapse, rowIn} from './motion'
import {useMotionVariants,useStarReducedMotion} from './MotionPolicy'
import {MotionSurface} from './MotionSurface'
import {StarFace} from './StarFace'
import {ResearchActivity, ResearchMark} from './ResearchActivity'

/** Re-render once a second while something is running, so elapsed times are live. */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return now
}

function Glyph({state}: {state: StepState | 'run-done' | 'run-failed' | 'run-cancelled'}) {
  const size = 15
  switch (state) {
    case 'running':
      return <LoaderCircle size={size} className="act-spin" aria-hidden="true" />
    case 'waiting':
      return <ShieldQuestion size={size} aria-hidden="true" />
    case 'done':
    case 'run-done':
      return <Check size={size} aria-hidden="true" />
    case 'failed':
    case 'run-failed':
      return <X size={size} aria-hidden="true" />
    case 'blocked':
      return <Ban size={size} aria-hidden="true" />
    case 'cancelled':
    case 'run-cancelled':
      return <CircleSlash size={size} aria-hidden="true" />
    default:
      return <Circle size={size} aria-hidden="true" />
  }
}

function Step({step, now}: {step: ActivityStep; now: number}) {
  const reduced = useStarReducedMotion()
  const rowVariants = useMotionVariants(rowIn)
  // Finished steps fold to one line; anything unfinished or unusual keeps its explanation open.
  // A tool's detail is only its technical name, so it stays folded unless the tool failed.
  const [toggled, setToggled] = useState<boolean | null>(null)
  const open = toggled ?? (step.kind === 'tool' && step.state !== 'blocked' ? step.state === 'failed' : step.state !== 'done')
  const instant = step.startedAt != null && step.startedAt === step.endedAt && step.elapsedMs == null
  const elapsed = instant ? null : stepElapsed(step, now)
  const live = step.state === 'running' || step.state === 'waiting'
  const body = (
    <>
      <span className="act-step-title">{step.title}</span>
      {step.role && <span className="act-step-role">{step.role}</span>}
    </>
  )
  return (
    <motion.li className={'act-step is-' + step.state + ' kind-' + step.kind} variants={rowVariants} initial={reduced?false:'hidden'} animate="shown">
      <span className="act-glyph">
        <Glyph state={step.state} />
      </span>
      <div className="act-step-main">
        {step.detail ? (
          <button type="button" className="act-step-line" aria-expanded={open} onClick={() => setToggled(!open)}>
            {body}
            <ChevronDown size={13} className="act-step-chevron" aria-hidden="true" />
          </button>
        ) : (
          <div className="act-step-line">{body}</div>
        )}
        {step.detail && open && <p className={'act-step-detail' + (step.kind === 'tool' && step.state !== 'blocked' ? ' is-code' : '')}>{step.detail}</p>}
      </div>
      <span className="act-step-state">{step.state === 'done' ? <span className="sr-only">Done</span> : stateWord(step)}</span>
      <span className="act-step-time">{elapsed == null ? '' : formatElapsed(elapsed, live)}</span>
    </motion.li>
  )
}

/** A calm, readable record of what a run did. Expanded while it works, folded to one line after. */
export function ActivityTimeline({run, onStop, stopping = false}: {run: ActivityRun; onStop?: () => void; stopping?: boolean}) {
  const running = run.outcome === 'running'
  const now = useNow(running)
  const [toggled, setToggled] = useState<boolean | null>(null)
  const open = toggled ?? (running || run.outcome === 'failed')
  const listId = useId()
  const done = countDone(run)
  const total = run.steps.length
  const hasDetails = total > 0 || !!run.research
  const brainLabel = run.brain === 'pc' ? 'answered on this PC'
    : run.brain === 'server' ? (run.model || 'STAR Server') : run.model ? (running ? run.model : `answered by ${run.model}`) : ''
  const researchMeta = run.research ? `${run.research.counts.found} found · ${run.research.counts.read} read` : ''
  const meta = [researchMeta || run.label, total ? (running ? `${done} of ${total} steps done` : `${total} ${total === 1 ? 'step' : 'steps'}`) : '',
    brainLabel, run.firstTokenMs != null ? `${run.firstTokenMs} ms first token` : '',
    run.tokensPerSecond != null ? `${run.estimatedTokens ? '≈' : ''}${run.tokensPerSecond.toFixed(1)} tok/s` : ''].filter(Boolean).join(' · ')
  return (
    <section className={'act act-' + run.outcome + (open ? ' is-open' : '') + (run.research ? ' has-research' : '')} aria-label="What STAR did">
      {/* A collapsed research run still announces phases. Counters, pages and clocks are never live. */}
      {run.research && <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">{stopping ? 'Stopping research' : running ? run.phase : run.outcome === 'cancelled' ? 'Research run stopped' : run.outcome === 'failed' ? 'Research run ended with an error' : 'Research answer finished'}</span>}
      <div className="act-head">
        <button type="button" className="act-toggle" aria-expanded={open} aria-controls={listId} disabled={!hasDetails} onClick={() => setToggled(!open)}>
          <span className={'act-glyph act-run-glyph is-' + run.outcome}>
            {run.research && running ? <ResearchMark /> : <Glyph state={running ? 'running' : run.outcome === 'done' ? 'run-done' : run.outcome === 'cancelled' ? 'run-cancelled' : 'run-failed'} />}
          </span>
          <span className="act-title">{run.research && running ? 'Deep research' : headline(run, now)}</span>
          {meta && <span className="act-meta">{meta}</span>}
          {hasDetails && <ChevronDown size={14} className="act-chevron" aria-hidden="true" />}
        </button>
        {running && <span className="act-clock" role="timer" aria-live="off" aria-label="Elapsed time">{formatElapsed(runElapsed(run, now), true)}</span>}
        {running && onStop && (
          <button type="button" className="act-stop" onClick={event => event.detail <= 1 && onStop()} disabled={stopping}>
            <Square size={11} fill="currentColor" aria-hidden="true" />
            {stopping ? 'Stopping' : 'Stop'}
          </button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && hasDetails && (
          <MotionSurface className="act-body" variants={collapse} id={listId}>
            {run.research && <ResearchActivity research={run.research} />}
            {total > 0 && <ol className="act-steps">
              {run.steps.map(step => (
                <Step key={step.id} step={step} now={now} />
              ))}
            </ol>}
          </MotionSurface>
        )}
      </AnimatePresence>
    </section>
  )
}

/** One quiet line for a plain answer that has not started streaming yet. */
export function RunStatus({run, label}: {run: ActivityRun; label?: string}) {
  const now = useNow(run.outcome === 'running')
  return (
    <div className="thread-status">
      <StarFace mood={label === 'Stopping' ? 'stopped' : run.mode === 'image' ? 'writing' : 'thinking'} size={40} className="thread-status-star" />
      {/* Only the phase is a live region; a ticking clock must not be re-announced every second. */}
      <span role="status" className="thread-status-phase">{label || run.phase}</span>
      <span className="thread-status-time" aria-hidden="true">{formatElapsed(runElapsed(run, now), true)}</span>
    </div>
  )
}
