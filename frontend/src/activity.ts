/** Activity model for one STAR run (a chat turn, an agent task or a team).
 *
 *  This is a pure reducer over the `progress` payloads that
 *  `star/react_shell.py::sanitize_event` really emits. It never invents a
 *  step: every row below exists because the backend reported it. Elapsed time
 *  is measured from when the UI received the event, or taken from the
 *  backend's own `elapsed_ms` when it sends one.
 */

export type StepState = 'queued' | 'running' | 'waiting' | 'done' | 'failed' | 'blocked' | 'cancelled'
export type StepKind = 'search' | 'think' | 'tool' | 'agent' | 'write'
export type RunMode = 'chat' | 'team' | 'image'
export type RunOutcome = 'running' | 'done' | 'failed' | 'cancelled'

export type ActivityStep = {
  id: string
  kind: StepKind
  state: StepState
  title: string
  role?: string
  detail?: string
  startedAt?: number
  endedAt?: number
  /** Backend-measured duration; preferred over the UI clock when present. */
  elapsedMs?: number
}

export type ActivityRun = {
  id: string
  mode: RunMode
  /** Route chosen by the backend ("Agent workflow"), or the run type. */
  label: string
  outcome: RunOutcome
  startedAt: number
  endedAt?: number
  steps: ActivityStep[]
  /** Last human-readable phase sentence; used by the compact status line. */
  phase: string
  streaming: boolean
  modelCalls?: number
  toolCalls?: number
  /** The model this run was sent to; replaced by the name the server reported on the answer. */
  model?: string
  brain?: 'pc' | 'server' | 'cloud'
  firstTokenMs?: number
  tokensPerSecond?: number
  estimatedTokens?: boolean
}

/** The sanitized `activity` object from the backend. All fields are enumerated or bounded there. */
export type ActivityPayload = {
  type?: string
  group?: string
  id?: string
  role?: string
  state?: string
  tool?: string
  profile?: string
  /** A model id (route: the one asked; model: the one that answered). Validated by the host. */
  model?: string
  /** Route only: the chosen model was unavailable and the main model answers instead. */
  fallback?: boolean
  brain?: 'pc' | 'server' | 'cloud'
  first_token_ms?: number
  tokens_per_second?: number
  estimated_tokens?: boolean
  step?: number
  max_steps?: number
  elapsed_ms?: number
  model_calls?: number
  tool_calls?: number
  steps?: Array<{id?: string; role?: string; needs?: string[]}>
  /** Documentation lookup: how many passages came back. */
  passages?: number
  /** Local checked practice, only a bounded count, never code or IDs. */
  count?: number
  /** Luau check or incremental repair outcome, from the backend's fixed event codes. */
  result?: string
  repair?: boolean
  /** Incremental repair: allowlisted checker/category and bounded observed attempt. */
  checker?: string
  kind?: string
  attempt?: number
}
export type ProgressPayload = {phase?: string; delta?: string; activity?: ActivityPayload}

const ROUTES: Record<string, string> = {
  fast: 'Fast answer',
  reasoning: 'Deeper reasoning',
  roblox: 'Roblox engineering',
  vision: 'Visual analysis',
  research: 'Source-grounded research',
  agent: 'Agent workflow',
}

const ROLES: Record<string, string> = {
  planner: 'Planner',
  research: 'Researcher',
  luau: 'Luau engineer',
  ui: 'UI designer',
  animation: 'Animator',
  environment: 'Environment artist',
  review: 'Reviewer',
  integration: 'Synthesis lead',
  specialist: 'Specialist',
}

/** Mirrors the fixed, app-defined plan in star/team_service.py (SPECIALISTS + synthesis). */
const TEAM_STAGES: Record<string, {title: string; detail: string}> = {
  evidence: {title: 'Evidence', detail: 'Sorts what is supported by your project context from what is still unknown.'},
  design: {title: 'Plan', detail: 'Drafts a practical plan with dependencies, trade-offs and testable milestones.'},
  critic: {title: 'Critique', detail: 'Challenges the assumptions: security, performance, UX and reliability.'},
  synthesis: {title: 'Synthesis', detail: 'Combines the three findings into one answer and keeps disagreements visible.'},
}

const STATES: readonly StepState[] = ['queued', 'running', 'waiting', 'done', 'failed', 'blocked', 'cancelled']
const asState = (value: unknown, fallback: StepState): StepState =>
  STATES.includes(value as StepState) ? (value as StepState) : fallback
const isOpen = (state: StepState) => state === 'running' || state === 'waiting'

const REPAIR_CHECKS: Record<string, {label: string; scope: string}> = {
  'python.compile': {label: 'Python syntax check', scope: 'Checks Python syntax without running the code.'},
  'json.loads': {label: 'JSON syntax check', scope: 'Checks JSON syntax. Application behavior and schema requirements are unverified.'},
  'tomllib.loads': {label: 'TOML syntax check', scope: 'Checks TOML syntax. Application behavior and settings are unverified.'},
  'luau.lint': {label: 'Luau advisory check', scope: 'Checks selected Luau patterns. It does not compile or run the code.'},
  'tool.result': {label: 'Tool result check', scope: 'A tool result describes this call only; it does not verify the whole task.'},
  none: {label: 'Repair check', scope: 'A successful check has not been confirmed.'},
}
const REPAIR_KINDS = ['syntax', 'advisory', 'tool_error', 'unknown_outcome', 'budget']

export const roleLabel = (role?: string) => ROLES[role || ''] || 'Specialist'

/** Friendly name for a tool the backend already authorized. Unknown names are shown as-is. */
export function toolLabel(name?: string): string {
  if (!name) return 'Using a tool'
  if (name === 'star_web_search') return 'Searching the web'
  if (name.startsWith('star_github_')) return 'Reading STAR source on GitHub'
  if (name === 'workspace_write') return 'Writing to your workspace'
  if (name === 'workspace_edit') return 'Editing a workspace file'
  if (name === 'workspace_search') return 'Searching your workspace'
  if (name === 'workspace_list') return 'Listing workspace files'
  if (name.startsWith('workspace_')) return 'Reading a workspace file'
  if (name.startsWith('star_delegate')) return 'Briefing specialists'
  if (name === 'star_mcp_registry_search') return 'Searching the public MCP registry'
  if (name.startsWith('star_mcp_')) return 'Using a connected MCP tool'
  if (name.startsWith('star_toolforge_')) return 'Running a reviewed custom tool'
  if (name === 'star_skill_catalog') return 'Listing Agent Skills'
  if (name.startsWith('star_skill_')) return 'Loading an Agent Skill'
  if (name.startsWith('star_obsidian_')) return 'Reading your Obsidian notes'
  if (name.startsWith('star_graphify_')) return 'Querying the code graph'
  if (name === 'star_docs_search') return 'Searching the official documentation'
  if (name === 'star_api_lookup') return 'Checking Roblox API names'
  if (name === 'star_luau_check') return 'Checking Luau code'
  if (name.startsWith('star_roblox_docs')) return 'Reading Roblox documentation'
  if (name.startsWith('star_roblox_forum_')) return 'Searching the Roblox Developer Forum'
  if (name.startsWith('star_roblox_youtube_')) return 'Looking up video metadata'
  if (name.startsWith('star_roblox_')) return 'Looking up public Roblox game data'
  return 'Using a tool'
}

export function startRun(id: string, mode: RunMode, now: number): ActivityRun {
  return {
    id,
    mode,
    label: mode === 'team' ? 'Team of specialists' : mode === 'image' ? 'Image' : '',
    outcome: 'running',
    startedAt: now,
    steps: [],
    phase: mode === 'image' ? 'Creating your image on this PC...' : 'Sending',
    streaming: false,
  }
}

function close(step: ActivityStep, state: StepState, now: number, elapsedMs?: number): ActivityStep {
  return {...step, state, endedAt: now, ...(elapsedMs != null ? {elapsedMs} : {})}
}

/** Finish whichever model-thinking step is still open; the next real event has arrived. */
function closeThinking(steps: ActivityStep[], now: number): ActivityStep[] {
  return steps.map(step => (step.kind === 'think' && step.state === 'running' ? close(step, 'done', now) : step))
}

function listNames(ids: string[]): string {
  const names = ids.map(id => TEAM_STAGES[id]?.title || id)
  if (names.length <= 1) return names.join('')
  return names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1]
}

/** Apply one real progress event. Returns the same object when nothing changed. */
export function applyProgress(run: ActivityRun, data: ProgressPayload | string | null | undefined, now: number): ActivityRun {
  if (run.outcome !== 'running' || data == null) return run
  if (typeof data === 'string') return {...run, phase: data.slice(0, 120)}
  if (typeof data.delta === 'string' && data.delta) {
    if (run.streaming) return run
    const steps = closeThinking(run.steps, now)
    steps.push({id: 'write', kind: 'write', state: 'running', title: 'Writing the answer', startedAt: now})
    return {...run, steps, streaming: true, phase: 'Writing the answer'}
  }
  const phase = typeof data.phase === 'string' && data.phase ? data.phase.slice(0, 120) : run.phase
  const activity = data.activity
  if (!activity || typeof activity !== 'object') return phase === run.phase ? run : {...run, phase}
  let steps = run.steps
  const next: ActivityRun = {...run, phase}
  switch (activity.type) {
    case 'route':
      if (activity.profile && ROUTES[activity.profile]) next.label = ROUTES[activity.profile]
      if (typeof activity.model === 'string' && activity.model) next.model = activity.model
      next.phase = activity.fallback ? 'That model is not available. Using your main model' : 'Choosing how to answer'
      break
    case 'instant':
      if (typeof activity.model === 'string' && activity.model) next.model = activity.model
      next.phase = 'Answering on this PC'
      break
    case 'instant_fallback':
      if (typeof activity.model === 'string' && activity.model) next.model = activity.model
      next.phase = 'Using STAR Server'
      break
    case 'answer_stats':
      if (activity.brain === 'pc' || activity.brain === 'server' || activity.brain === 'cloud') next.brain = activity.brain
      if (typeof activity.model === 'string' && activity.model) next.model = activity.model
      if (typeof activity.first_token_ms === 'number') next.firstTokenMs = activity.first_token_ms
      if (typeof activity.tokens_per_second === 'number') next.tokensPerSecond = activity.tokens_per_second
      next.estimatedTokens = activity.estimated_tokens === true
      break
    case 'model':
      // The name the server itself put on the answer.
      if (typeof activity.model === 'string' && activity.model) next.model = activity.model
      break
    case 'search': {
      const found = steps.findIndex(step => step.id === 'search')
      if (activity.state === 'running' && found < 0) {
        steps = [...steps, {id: 'search', kind: 'search', state: 'running', title: 'Searching the web', startedAt: now}]
      } else if (found >= 0 && isOpen(steps[found].state)) {
        steps = steps.map((step, index) => (index === found ? close(step, 'done', now) : step))
      }
      next.phase = activity.state === 'running' ? 'Searching the web' : 'Reading the search results'
      break
    }
    case 'docs': {
      // Official documentation fetched from STAR Server before the model is asked.
      const found = steps.findIndex(step => step.id === 'docs')
      if (activity.state === 'running' && found < 0) {
        steps = [...steps, {id: 'docs', kind: 'search', state: 'running', title: 'Reading the official documentation', startedAt: now}]
        next.phase = 'Reading the official documentation'
      } else if (found >= 0 && isOpen(steps[found].state)) {
        const failed = activity.state === 'failed'
        const count = typeof activity.passages === 'number' ? activity.passages : 0
        const detail = failed
          ? 'The documentation service did not answer. STAR answers without it.'
          : count
            ? `${count} passage${count === 1 ? '' : 's'} from the official documentation`
            : 'Nothing in the indexed documentation matched.'
        steps = steps.map((step, index) =>
          index === found ? {...close(step, failed ? 'failed' : 'done', now, typeof activity.elapsed_ms === 'number' ? activity.elapsed_ms : undefined), detail} : step,
        )
        next.phase = failed ? 'Documentation unavailable' : 'Documentation ready'
      }
      break
    }
    case 'example': {
      const count = activity.count
      if (typeof count === 'number' && Number.isInteger(count) && count >= 1 && count <= 2 &&
          !steps.some(step => step.id === 'checked-example')) {
        steps = [...steps, {id: 'checked-example', kind: 'search', state: 'done',
          title: 'Used checked practice example' + (count === 1 ? '' : 's'),
          detail: 'Checked by automated practice tests, not Roblox Studio or a person.',
          startedAt: now, endedAt: now}]
        next.phase = 'Using local practice examples'
      }
      break
    }
    case 'repair': {
      if (!['detected', 'check_passed', 'blocked'].includes(activity.result || '')) break
      const checker = typeof activity.checker === 'string' && Object.prototype.hasOwnProperty.call(REPAIR_CHECKS, activity.checker)
        ? activity.checker : 'none'
      const category = REPAIR_KINDS.includes(activity.kind || '') ? activity.kind : 'unknown_outcome'
      const check = REPAIR_CHECKS[checker]
      const result = activity.result === 'check_passed' && (checker === 'none' || category === 'unknown_outcome' || category === 'budget')
        ? 'blocked' : activity.result
      const advisory = result === 'detected' && category === 'advisory' && checker === 'luau.lint'
      const state: StepState = result === 'check_passed' || advisory ? 'done' : result === 'detected' ? 'failed' : 'blocked'
      const title = result === 'check_passed'
        ? checker === 'tool.result' ? 'Tool call returned successfully' : check.label + ' passed'
        : result === 'blocked'
          ? category === 'budget' ? activity.attempt === 2 ? 'Focused repair limit reached' : 'Work paused for a repair'
            : category === 'unknown_outcome' ? 'Tool outcome needs inspection' : 'Automatic repair paused'
          : advisory ? 'Luau advisory check reported possible issues'
            : category === 'tool_error' ? 'A tool reported a problem'
            : category === 'unknown_outcome' ? 'A tool outcome is unconfirmed' : check.label + ' reported a problem'
      const count = typeof activity.count === 'number' && Number.isInteger(activity.count) && activity.count >= 1 && activity.count <= 100
        ? activity.count : 0
      const attempt = typeof activity.attempt === 'number' && Number.isInteger(activity.attempt) && activity.attempt >= 1 && activity.attempt <= 2
        ? ` Repair attempt ${activity.attempt}.` : ''
      const detail = result === 'detected'
        ? advisory
          ? `${count ? `${count} possible issue${count === 1 ? '' : 's'} reported. ` : ''}Review whether the findings apply. These patterns do not prove a defect or verify runtime behavior.`
          : `${count ? `${count} finding${count === 1 ? '' : 's'} reported. ` : ''}A repair has not yet passed a check. ${check.scope}${attempt}`
        : result === 'check_passed'
          ? `${check.scope}${attempt}`
          : category === 'unknown_outcome'
            ? 'The earlier action may have taken effect. Its result needs inspection before another mutation.'
            : category === 'budget' && activity.attempt !== 2
              ? 'Work is paused so STAR can inspect an earlier result. No fix is confirmed.'
              : `This repair is paused and its result remains unverified.${attempt}`
      // Each row records an observed outcome, never an open promise to repair it.
      // A later successful task completion cannot promote an unresolved error.
      steps = [...closeThinking(steps, now), {id: 'repair-' + steps.length, kind: 'tool', state,
        title, detail, endedAt: now}]
      next.phase = title
      break
    }
    case 'luau_check': {
      // A static check of the Luau in the answer. The code is never run.
      const found = steps.findIndex(step => step.id === 'luau-check')
      if (activity.state === 'running') {
        steps = closeThinking(steps, now)
        if (found < 0) steps = [...steps, {id: 'luau-check', kind: 'tool', state: 'running', title: 'Checking the Luau code', startedAt: now}]
        else if (activity.repair) steps = steps.map((step, index) => (index === found ? {...step, title: 'Fixing the Luau code'} : step))
        next.phase = activity.repair ? 'Fixing the Luau code' : 'Checking the Luau code'
      } else if (found >= 0 && isOpen(steps[found].state)) {
        const detail =
          activity.result === 'passed'
            ? 'Compiles and passes type analysis. Not run.'
            : activity.result === 'repaired'
              ? 'A problem was found and corrected. The corrected code passes.'
              : activity.result === 'failed'
                ? 'Problems were found. They are listed under the answer.'
                : 'The check could not run. Nothing is claimed about the code.'
        steps = steps.map((step, index) =>
          index === found ? {...close(step, activity.state === 'failed' ? 'failed' : 'done', now), title: 'Checking the Luau code', detail} : step,
        )
        next.phase = 'Luau check finished'
      }
      break
    }
    case 'turn': {
      const turn = activity.step || steps.filter(step => step.kind === 'think').length + 1
      steps = closeThinking(steps, now)
      steps.push({
        id: 'think-' + turn + '-' + steps.length,
        kind: 'think',
        state: 'running',
        title: 'Thinking',
        detail:
          activity.max_steps && activity.max_steps > 1 ? `Model call ${turn} of up to ${activity.max_steps}` : undefined,
        startedAt: now,
      })
      next.phase = 'Thinking'
      break
    }
    case 'tool': {
      const state = asState(activity.state, 'failed')
      if (state === 'running') {
        steps = closeThinking(steps, now)
        steps.push({
          id: 'tool-' + steps.length,
          kind: 'tool',
          state: 'running',
          title: toolLabel(activity.tool),
          detail: activity.tool,
          startedAt: now,
        })
        next.phase = toolLabel(activity.tool)
      } else if (state === 'blocked') {
        steps = closeThinking(steps, now)
        steps.push({
          id: 'tool-' + steps.length,
          kind: 'tool',
          state: 'blocked',
          title: 'A tool request was blocked',
          detail: 'STAR asked for a tool this task is not permitted to use. Nothing was run.',
          startedAt: now,
          endedAt: now,
        })
      } else {
        let target = -1
        for (let index = steps.length - 1; index >= 0; index--) {
          const step = steps[index]
          if (step.kind === 'tool' && step.state === 'running' && (!activity.tool || step.detail === activity.tool)) {
            target = index
            break
          }
        }
        if (target >= 0) steps = steps.map((step, index) => (index === target ? close(step, state, now) : step))
        else {
          steps = [
            ...steps,
            {id: 'tool-' + steps.length, kind: 'tool', state, title: toolLabel(activity.tool), detail: activity.tool, startedAt: now, endedAt: now},
          ]
        }
      }
      break
    }
    case 'plan': {
      const planned = (Array.isArray(activity.steps) ? activity.steps : []).filter(item => item && typeof item.id === 'string')
      const known = new Set(steps.map(step => step.id))
      const queued: ActivityStep[] = planned
        .filter(item => !known.has('agent-' + item.id))
        .map(item => {
          const stage = TEAM_STAGES[item.id as string]
          const needs = Array.isArray(item.needs) ? item.needs : []
          return {
            id: 'agent-' + item.id,
            kind: 'agent' as const,
            state: 'queued' as const,
            title: stage?.title || roleLabel(item.role),
            role: roleLabel(item.role),
            detail: (stage?.detail || '') + (needs.length ? ` Starts after ${listNames(needs)}.` : ''),
          }
        })
      if (queued.length) steps = [...steps, ...queued]
      next.phase = 'Plan ready'
      break
    }
    case 'agent': {
      if (!activity.id) break
      const id = 'agent-' + activity.id
      const state = asState(activity.state, 'failed')
      const stage = activity.group === 'team' ? TEAM_STAGES[activity.id] : undefined
      const found = steps.findIndex(step => step.id === id)
      const base: ActivityStep =
        found >= 0
          ? steps[found]
          : {
              id,
              kind: 'agent',
              state: 'queued',
              title: stage?.title || roleLabel(activity.role),
              role: stage ? roleLabel(activity.role) : 'Read-only specialist',
              detail: stage?.detail || 'Analyses the evidence it was given. It has no tools and cannot change anything.',
            }
      const updated: ActivityStep =
        state === 'running'
          ? {...base, state, startedAt: now, endedAt: undefined}
          : close(
              state === 'blocked' && !base.startedAt ? {...base, detail: 'Not started: a stage it depends on did not finish.'} : base,
              state,
              now,
              typeof activity.elapsed_ms === 'number' ? activity.elapsed_ms : undefined,
            )
      steps = found >= 0 ? steps.map((step, index) => (index === found ? updated : step)) : [...steps, updated]
      next.phase = state === 'running' ? `${updated.title} is working` : next.phase
      break
    }
    case 'finished':
      steps = closeThinking(steps, now)
      if (typeof activity.model_calls === 'number') next.modelCalls = activity.model_calls
      if (typeof activity.tool_calls === 'number') next.toolCalls = activity.tool_calls
      next.phase = 'Finishing'
      break
    case 'saved':
      next.phase = 'Saving to this chat'
      break
    default:
      break
  }
  next.steps = steps
  return next
}

/** The run ended. Open steps take the run's outcome; queued steps never started. */
export function settleRun(run: ActivityRun, outcome: Exclude<RunOutcome, 'running'>, now: number): ActivityRun {
  if (run.outcome !== 'running') return run
  const steps = run.steps.map(step => {
    if (isOpen(step.state)) return close(step, outcome === 'done' ? 'done' : outcome === 'cancelled' ? 'cancelled' : 'failed', now)
    if (step.state === 'queued') return {...step, state: 'cancelled' as const}
    return step
  })
  return {...run, steps, outcome, endedAt: now, streaming: false}
}

/** Only multi-step work earns a timeline; a plain answer keeps the one-line status. */
export function isRich(run: ActivityRun): boolean {
  if (run.mode === 'team') return true
  return (
    run.steps.some(step => step.kind === 'tool' || step.kind === 'agent' || step.kind === 'search') ||
    run.steps.filter(step => step.kind === 'think').length > 1
  )
}

export function stepElapsed(step: ActivityStep, now: number): number | null {
  if (step.elapsedMs != null) return step.elapsedMs
  if (step.startedAt == null) return null
  return Math.max(0, (step.endedAt ?? now) - step.startedAt)
}
export const runElapsed = (run: ActivityRun, now: number) => Math.max(0, (run.endedAt ?? now) - run.startedAt)

/** 0.4s · 4.2s · 42s · 1m 05s. Live values pass `live` to avoid a jittering decimal. */
export function formatElapsed(ms: number, live = false): string {
  if (!live && ms < 100) return '<0.1s'
  const seconds = ms / 1000
  if (seconds < 60) return live || seconds >= 10 ? Math.floor(seconds) + 's' : seconds.toFixed(1) + 's'
  const minutes = Math.floor(seconds / 60)
  return minutes + 'm ' + String(Math.floor(seconds % 60)).padStart(2, '0') + 's'
}

export const STATE_WORD: Record<StepState, string> = {
  queued: 'Queued',
  running: 'Running',
  waiting: 'Waiting for approval',
  done: 'Done',
  failed: 'Failed',
  blocked: 'Blocked',
  cancelled: 'Stopped',
}
/** A step the run ended before reaching is not "stopped": it never began. */
export const stateWord = (step: ActivityStep) => (step.state === 'cancelled' && step.startedAt == null ? 'Not started' : STATE_WORD[step.state])

export function countDone(run: ActivityRun) {
  return run.steps.filter(step => step.state === 'done').length
}

/** One-line summary shown on the collapsed timeline. */
export function headline(run: ActivityRun, now: number): string {
  const time = formatElapsed(runElapsed(run, now), run.outcome === 'running')
  if (run.outcome === 'running') return 'Working'
  if (run.outcome === 'done') return 'Worked for ' + time
  if (run.outcome === 'cancelled') return 'Stopped after ' + time
  return 'Stopped by an error after ' + time
}
