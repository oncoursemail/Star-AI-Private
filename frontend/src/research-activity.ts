/** Public research activity only. Search text, page bodies and model reasoning never enter this model. */
export type ResearchEventName =
  | 'research_started'
  | 'query_started' | 'query_completed' | 'query_failed'
  | 'source_started' | 'source_read' | 'source_failed'
  | 'research_followup_started' | 'research_finished' | 'research_citations_checked'

export type ResearchActivityPayload = {
  event?: string
  run_id?: string
  event_id?: string
  seq?: number
  phase?: string
  at?: string
  query_id?: string
  ordinal?: number
  source_id?: string
  source_status?: string
  title?: string
  url?: string
  status?: string
  stop_reason?: string
  queries?: number
  failed_queries?: number
  pages?: number
  sources_found?: number
  sources_read?: number
  sources_failed?: number
  peak_concurrency?: number
  elapsed_ms?: number
  checked?: number
  invalid?: number
  semantic_support?: string
  found?: number
}

export type ResearchOutcome = 'running' | 'completed' | 'partial' | 'failed' | 'cancelled' | 'timed_out' | 'interrupted'
export type ResearchQuery = {id: string; ordinal: number; state: 'running' | 'completed' | 'failed' | 'cancelled' | 'not_completed'}
export type ResearchSource = {
  /** Source IDs repeat across sessions, so every UI key includes its research run. */
  key: string
  id: string
  title: string
  url: string
  state: 'reading' | 'read' | 'failed' | 'cancelled' | 'not_read'
}

export type ResearchActivityState = {
  runId: string
  lastSeq: number
  eventIds: string[]
  outcome: ResearchOutcome
  phase: 'search' | 'read' | 'followup' | 'finished'
  startedAt: number
  endedAt?: number
  elapsedMs: number
  queries: ResearchQuery[]
  sources: ResearchSource[]
  counts: {queries: number; failedQueries: number; pages: number; found: number; read: number; failed: number; peakConcurrency: number}
  /** Checks the identity/existence of references, not whether a claim is true. */
  citations?: {checked: number; invalid: number; semanticSupport: 'unchecked'}
}

const EVENT_NAMES: ReadonlySet<string> = new Set<ResearchEventName>([
  'research_started', 'query_started', 'query_completed', 'query_failed',
  'source_started', 'source_read', 'source_failed', 'research_followup_started',
  'research_finished', 'research_citations_checked',
])
const OUTCOMES: readonly ResearchOutcome[] = ['completed', 'partial', 'failed', 'cancelled', 'timed_out']
// The backend uses a much smaller research budget. Bounds also keep malformed bridge data finite.
const MAX_RECORDS = 128
const MAX_EVENT_IDS = 512
const text = (value: unknown, limit: number) => typeof value === 'string'
  ? value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, '').trim().slice(0, limit) : ''
const id = (value: unknown) => typeof value === 'string' && /^[A-Za-z0-9_.:-]{1,160}$/.test(value) ? value : ''
const count = (value: unknown, fallback: number) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= 1_000_000 ? value : fallback

/** A page title is plain text; only credential-free HTTP(S) destinations become clickable. */
export function safeResearchUrl(value: unknown): string {
  if (typeof value !== 'string' || value.length > 2048) return ''
  try {
    const url = new URL(value)
    return (url.protocol === 'https:' || url.protocol === 'http:') && !url.username && !url.password ? url.href : ''
  } catch {
    return ''
  }
}

/** `event` is canonical; an already-sanitized host may also use the event name as `type`. */
export function researchEventName(payload: ResearchActivityPayload & {type?: string}): ResearchEventName | null {
  const name = payload.event || payload.type || ''
  return EVENT_NAMES.has(name) ? name as ResearchEventName : null
}

export function researchPhase(state: ResearchActivityState): string {
  if (state.outcome !== 'running') {
    if (state.outcome === 'completed') return state.counts.read > 0 ? 'Research sources ready' : 'Research finished without source pages'
    if (state.outcome === 'partial') return 'Research finished with limited sources'
    if (state.outcome === 'cancelled') return 'Research stopped'
    if (state.outcome === 'timed_out') return 'Research time limit reached'
    if (state.outcome === 'interrupted') return 'Research completion was not confirmed'
    return 'Research could not finish'
  }
  if (state.phase === 'read') return 'Reading source pages'
  if (state.phase === 'followup') return 'Following up on evidence gaps'
  return 'Searching for sources'
}

/** Apply one observed event. Duplicates, stale sequences and a different session cannot alter a run. */
export function applyResearchActivity(
  current: ResearchActivityState | undefined,
  payload: ResearchActivityPayload & {type?: string},
  now: number,
): ResearchActivityState | undefined {
  const event = researchEventName(payload)
  const runId = id(payload.run_id)
  const eventId = id(payload.event_id)
  const seq = payload.seq
  if (!event || !runId || !eventId || typeof seq !== 'number' || !Number.isSafeInteger(seq) || seq < 0 || eventId !== `${runId}:${seq}`) return current
  if (current && (current.runId !== runId || seq <= current.lastSeq || current.eventIds.includes(eventId))) return current
  // A cancellation acknowledgement is terminal, even if a worker delivers a late start event.
  if (current?.outcome === 'cancelled') return current
  // A started event establishes the session; unrelated source messages cannot create a research UI.
  if (!current && event !== 'research_started') return current
  if (current && event === 'research_started') return current
  const previous: ResearchActivityState = current ?? {
    runId, lastSeq: -1, eventIds: [], outcome: 'running', phase: 'search', startedAt: now,
    elapsedMs: 0, queries: [], sources: [],
    counts: {queries: 0, failedQueries: 0, pages: 0, found: 0, read: 0, failed: 0, peakConcurrency: 0},
  }
  if ((event.startsWith('query_') && !id(payload.query_id)) || (event.startsWith('source_') && !id(payload.source_id))) return current
  if (event === 'research_citations_checked' && (payload.semantic_support !== 'unchecked' ||
    count(payload.checked, -1) < 0 || count(payload.invalid, -1) < 0 || (payload.invalid ?? 0) > (payload.checked ?? 0))) return current

  const next: ResearchActivityState = {
    ...previous,
    lastSeq: seq,
    eventIds: [...previous.eventIds.slice(-(MAX_EVENT_IDS - 1)), eventId],
    elapsedMs: Math.max(previous.elapsedMs, count(payload.elapsed_ms, previous.elapsedMs)),
    counts: {
      queries: Math.max(previous.counts.queries, count(payload.queries, previous.counts.queries)),
      failedQueries: Math.max(previous.counts.failedQueries, count(payload.failed_queries, previous.counts.failedQueries)),
      pages: Math.max(previous.counts.pages, count(payload.pages, previous.counts.pages)),
      found: Math.max(previous.counts.found, count(payload.sources_found, previous.counts.found)),
      read: Math.max(previous.counts.read, count(payload.sources_read, previous.counts.read)),
      failed: Math.max(previous.counts.failed, count(payload.sources_failed, previous.counts.failed)),
      peakConcurrency: Math.max(previous.counts.peakConcurrency, count(payload.peak_concurrency, previous.counts.peakConcurrency)),
    },
  }
  switch (event) {
    case 'research_started':
      break
    case 'research_followup_started':
      next.outcome = 'running'
      next.phase = 'followup'
      next.endedAt = undefined
      break
    case 'query_started':
    case 'query_completed':
    case 'query_failed': {
      const queryId = id(payload.query_id)
      const found = previous.queries.findIndex(query => query.id === queryId)
      const state = event === 'query_started' ? 'running' : event === 'query_completed' ? 'completed' : 'failed'
      const query: ResearchQuery = {
        id: queryId,
        ordinal: count(payload.ordinal, found >= 0 ? previous.queries[found].ordinal : previous.queries.length + 1) || previous.queries.length + 1,
        state,
      }
      if (found >= 0) next.queries = previous.queries.map((item, index) => index === found ? query : item)
      else if (previous.queries.length < MAX_RECORDS) next.queries = [...previous.queries, query]
      if (event === 'query_started') {
        next.outcome = 'running'
        next.phase = payload.phase === 'followup' ? 'followup' : 'search'
        next.endedAt = undefined
      }
      break
    }
    case 'source_started':
    case 'source_read':
    case 'source_failed': {
      const sourceId = id(payload.source_id)
      const key = `${runId}:${sourceId}`
      const found = previous.sources.findIndex(source => source.key === key)
      const prior = found >= 0 ? previous.sources[found] : undefined
      const source: ResearchSource = {
        key, id: sourceId,
        title: text(payload.title, 200) || prior?.title || 'Source page',
        // An unsafe replacement URL must never keep an apparently valid stale destination.
        url: payload.url === undefined ? prior?.url || '' : safeResearchUrl(payload.url),
        state: event === 'source_started' ? 'reading' : event === 'source_read' ? 'read' : 'failed',
      }
      if (found >= 0) next.sources = previous.sources.map((item, index) => index === found ? source : item)
      else if (previous.sources.length < MAX_RECORDS) next.sources = [...previous.sources, source]
      if (event === 'source_started') {
        next.outcome = 'running'
        next.phase = 'read'
        next.endedAt = undefined
      }
      break
    }
    case 'research_finished': {
      next.outcome = OUTCOMES.includes(payload.status as ResearchOutcome) ? payload.status as ResearchOutcome : 'interrupted'
      next.phase = 'finished'
      next.endedAt = now
      // An unfinished read is never inferred to be successful when the session ends.
      next.sources = previous.sources.map(source => source.state === 'reading'
        ? {...source, state: next.outcome === 'cancelled' ? 'cancelled' : 'not_read'} : source)
      next.queries = previous.queries.map(query => query.state === 'running'
        ? {...query, state: next.outcome === 'cancelled' ? 'cancelled' : 'not_completed'} : query)
      break
    }
    case 'research_citations_checked':
      next.citations = {checked: payload.checked as number, invalid: payload.invalid as number, semanticSupport: 'unchecked'}
      break
  }
  return next
}

/** Preserve the existing chat lifecycle. A missing research finish event never turns into success. */
export function settleResearchActivity(
  state: ResearchActivityState | undefined,
  outcome: 'done' | 'failed' | 'cancelled',
  now: number,
): ResearchActivityState | undefined {
  if (!state || state.outcome !== 'running') return state
  return {
    ...state,
    outcome: outcome === 'done' ? 'interrupted' : outcome,
    phase: 'finished', endedAt: now,
    sources: state.sources.map(source => source.state === 'reading'
      ? {...source, state: outcome === 'cancelled' ? 'cancelled' : 'not_read'} : source),
    queries: state.queries.map(query => query.state === 'running'
      ? {...query, state: outcome === 'cancelled' ? 'cancelled' : 'not_completed'} : query),
  }
}
