import {describe, expect, it} from 'vitest'
import {applyProgress, isRich, settleRun, startRun} from './activity'
import {
  applyResearchActivity, researchEventName, researchPhase, safeResearchUrl, settleResearchActivity,
} from './research-activity'
import type {ResearchActivityPayload, ResearchActivityState} from './research-activity'

type WireEvent = ResearchActivityPayload & {type?: string}
const event = (seq: number, name: string, fields: Record<string, unknown> = {}): WireEvent => ({
  type: 'research', event: name, run_id: 'research-1', event_id: `research-1:${seq}`, seq,
  phase: 'search', at: '2026-10-19T04:00:00Z', ...fields,
}) as WireEvent

function startResearch(runId = 'research-1'): ResearchActivityState {
  const result = applyResearchActivity(undefined, event(1, 'research_started', {
    run_id: runId, event_id: `${runId}:1`, queries: 0, sources_found: 0, sources_read: 0,
  }), 100)
  if (!result) throw new Error('A valid backend start event must establish the research session')
  return result
}

function apply(current: ResearchActivityState, seq: number, name: string, fields: Record<string, unknown> = {}) {
  const result = applyResearchActivity(current, event(seq, name, fields), seq * 100)
  if (!result) throw new Error('An established session must remain available')
  return result
}

describe('research events in the existing chat activity lifecycle', () => {
  it('does not create research UI for ordinary chat or a source event without a session start', () => {
    const run = startRun('chat-1', 'chat', 0)
    expect(isRich(run)).toBe(false)
    expect(run.research).toBeUndefined()
    expect(applyProgress(run, {activity: event(3, 'source_read', {source_id: 'S1'})}, 300)).toBe(run)
    expect(applyProgress(run, {activity: {type: 'research', event: 'private_thought'}}, 300).research).toBeUndefined()
  })

  it('keeps the chat run and research session identities distinct through real events and the answer', () => {
    let run = startRun('chat-1', 'chat', 0)
    run = applyProgress(run, {activity: event(1, 'research_started')}, 100)
    expect(isRich(run)).toBe(true)
    expect(run.id).toBe('chat-1')
    expect(run.research?.runId).toBe('research-1')
    expect(run.steps).toEqual([])
    run = applyProgress(run, {activity: event(2, 'source_started', {
      source_id: 'S1', title: 'Primary source', url: 'https://evidence.example/page', sources_found: 3,
    })}, 200)
    run = applyProgress(run, {activity: event(3, 'source_read', {source_id: 'S1', sources_read: 1})}, 300)
    run = applyProgress(run, {activity: event(4, 'research_finished', {status: 'completed'})}, 400)
    const sources = run.research
    run = applyProgress(run, {delta: 'The evidence shows'}, 500)
    expect(run.research).toBe(sources)
    expect(run.steps.map(step => step.title)).toEqual(['Writing the answer'])
    const settled = settleRun(run, 'done', 600)
    expect(settled.research?.outcome).toBe('completed')
    expect(settled.research?.counts).toMatchObject({found: 3, read: 1})
    expect(applyProgress(settled, {activity: event(5, 'query_started', {query_id: 'q2'})}, 700)).toBe(settled)
  })
})

describe('research event identity and input validation', () => {
  it('recognizes the agreed event envelope and ignores unknown event names', () => {
    expect(researchEventName(event(1, 'research_started'))).toBe('research_started')
    expect(researchEventName({type: 'source_read'})).toBe('source_read')
    expect(researchEventName({type: 'research', event: 'private_thought'})).toBeNull()
  })

  it('ignores duplicate events, reused event IDs, and reordered stale messages without changing counts', () => {
    const first = apply(startResearch(), 2, 'source_read', {
      source_id: 'S1', title: 'One source', sources_found: 2, sources_read: 1,
    })
    expect(apply(first, 2, 'source_read', {source_id: 'S1', sources_read: 99})).toBe(first)
    expect(apply(first, 3, 'source_read', {event_id: 'research-1:2', source_id: 'S2', sources_read: 99})).toBe(first)
    expect(apply(first, 1, 'query_started', {query_id: 'q1'})).toBe(first)
    expect(first.counts.read).toBe(1)
    expect(first.sources.map(source => source.id)).toEqual(['S1'])
  })

  it('rejects an event identity that does not match its run and sequence', () => {
    const current = startResearch()
    expect(apply(current, 2, 'query_started', {query_id: 'q1', event_id: 'different-run:2'})).toBe(current)
    expect(apply(current, 2, 'query_started', {query_id: 'q1', event_id: 'research-1:9'})).toBe(current)
  })

  it.each([
    {seq: -1}, {seq: 1.5}, {seq: NaN}, {seq: Infinity}, {seq: '2'},
    {run_id: ''}, {run_id: 'bad run'}, {event_id: ''}, {event_id: 'bad event'},
  ])('ignores malformed envelope fields: %j', fields => {
    const current = startResearch()
    expect(applyResearchActivity(current, event(2, 'query_started', {query_id: 'q1', ...fields}), 200)).toBe(current)
  })

  it('requires source/query IDs and rejects events from another established session', () => {
    const current = startResearch()
    expect(apply(current, 2, 'source_started', {title: 'Missing ID'})).toBe(current)
    expect(apply(current, 2, 'query_started')).toBe(current)
    expect(apply(current, 2, 'source_started', {source_id: 'contains whitespace'})).toBe(current)
    expect(apply(current, 2, 'research_started')).toBe(current)
    expect(apply(current, 2, 'source_read', {
      run_id: 'research-2', event_id: 'research-2:2', source_id: 'S1', sources_read: 20,
    })).toBe(current)
  })

  it('does not retain raw queries, prompts, page bodies, reasoning, or answer text from an envelope', () => {
    const current = apply(startResearch(), 2, 'query_started', {
      query_id: 'q1', ordinal: 1, query: 'private search text', prompt: 'private prompt',
      answer: 'private answer', reasoning: 'private reasoning', page_body: 'private document text',
    })
    const stored = JSON.stringify(current)
    for (const sensitive of ['private search text', 'private prompt', 'private answer', 'private reasoning', 'private document text']) {
      expect(stored).not.toContain(sensitive)
    }
  })
})

describe('source provenance and observed counters', () => {
  it('keeps discovered sources separate from successful page reads and failed reads', () => {
    let current = apply(startResearch(), 2, 'query_started', {query_id: 'q1', ordinal: 1, queries: 1})
    current = apply(current, 3, 'query_completed', {query_id: 'q1', found: 8})
    expect(current.queries[0].state).toBe('completed')
    expect(current.counts.read).toBe(0)
    current = apply(current, 4, 'source_started', {
      source_id: 'S1', title: 'Unavailable page', url: 'https://evidence.example/one', sources_found: 8,
    })
    expect(current.sources[0].state).toBe('reading')
    expect(current.counts).toMatchObject({found: 8, read: 0})
    current = apply(current, 5, 'source_failed', {source_id: 'S1', sources_failed: 1})
    expect(current.sources[0].state).toBe('failed')
    expect(current.counts.read).toBe(0)
    current = apply(current, 6, 'source_started', {source_id: 'S2', title: 'Readable page'})
    current = apply(current, 7, 'source_read', {source_id: 'S2', sources_read: 1})
    current = apply(current, 8, 'research_finished', {status: 'partial'})
    expect(current.counts).toMatchObject({found: 8, read: 1, failed: 1})
    expect(current.sources.map(source => source.state)).toEqual(['failed', 'read'])
    expect(current.outcome).toBe('partial')
  })

  it('keeps a source key stable across redirects and scopes repeated S1 labels to their own sessions', () => {
    const first = apply(startResearch(), 2, 'source_started', {
      source_id: 'S1', title: 'Original', url: 'https://evidence.example/original',
    })
    const read = apply(first, 3, 'source_read', {
      source_id: 'S1', title: 'Final title', url: 'https://publisher.example/final',
    })
    expect(read.sources).toHaveLength(1)
    expect(read.sources[0]).toMatchObject({key: first.sources[0].key, id: 'S1', title: 'Final title', url: 'https://publisher.example/final'})
    const other = applyResearchActivity(startResearch('research-2'), event(2, 'source_read', {
      run_id: 'research-2', event_id: 'research-2:2', source_id: 'S1',
    }), 200)
    expect(other?.sources[0].key).not.toBe(read.sources[0].key)
  })

  it('does not mutate previous state and retains measured elapsed/counters when later values are invalid', () => {
    const current = apply(startResearch(), 2, 'source_read', {
      source_id: 'S1', sources_found: 4, sources_read: 1, elapsed_ms: 250,
    })
    const before = JSON.stringify(current)
    Object.freeze(current)
    Object.freeze(current.counts)
    Object.freeze(current.sources)
    const next = apply(current, 3, 'query_started', {
      query_id: 'q2', sources_found: -1, sources_read: NaN, pages: Infinity, peak_concurrency: 1_000_001, elapsed_ms: -100,
    })
    expect(JSON.stringify(current)).toBe(before)
    expect(next.counts).toMatchObject({found: 4, read: 1, pages: 0, peakConcurrency: 0})
    expect(next.elapsedMs).toBe(250)
  })

  it('bounds plain titles and removes control/directional characters without interpreting markup', () => {
    const title = '<img src=x onerror=alert(1)> & evidence\u0000\u202e' + 'a'.repeat(300)
    const current = apply(startResearch(), 2, 'source_started', {source_id: 'S1', title})
    expect(current.sources[0].title).toContain('<img src=x onerror=alert(1)> & evidence')
    expect(current.sources[0].title.length).toBeLessThanOrEqual(200)
    expect(current.sources[0].title).not.toMatch(/[\u0000\u202e]/)
  })

  it('removes an unsafe replacement destination instead of retaining a stale apparently valid link', () => {
    const first = apply(startResearch(), 2, 'source_started', {source_id: 'S1', url: 'https://evidence.example/one'})
    const read = apply(first, 3, 'source_read', {source_id: 'S1', url: 'javascript:alert(1)'})
    expect(read.sources[0].url).toBe('')
  })
})

describe('research completion and cancellation', () => {
  it('allows a same-session followup while retaining source IDs and prevents a foreign-session reopen', () => {
    const completed = apply(apply(startResearch(), 2, 'source_read', {source_id: 'S1', sources_read: 1}), 3, 'research_finished', {status: 'completed'})
    expect(completed.outcome).toBe('completed')
    expect(apply(completed, 4, 'research_followup_started', {run_id: 'research-2', event_id: 'research-2:4'})).toBe(completed)
    const following = apply(completed, 4, 'research_followup_started', {phase: 'followup'})
    expect(following.outcome).toBe('running')
    expect(following.endedAt).toBeUndefined()
    expect(researchPhase(following)).toBe('Following up on evidence gaps')
    expect(following.sources).toBe(completed.sources)
    expect(apply(following, 5, 'query_started', {query_id: 'q2'}).outcome).toBe('running')
  })

  it('preserves failed reads and does not invent completion for work still running at the final event', () => {
    let current = apply(startResearch(), 2, 'query_started', {query_id: 'q1'})
    current = apply(current, 3, 'source_started', {source_id: 'S1'})
    current = apply(current, 4, 'source_failed', {source_id: 'S2'})
    const finished = apply(current, 5, 'research_finished', {status: 'partial'})
    expect(finished.sources.map(source => source.state)).toEqual(['not_read', 'failed'])
    expect(finished.queries[0].state).toBe('not_completed')
    expect(finished.counts.read).toBe(0)
    const unknown = apply(current, 5, 'research_finished', {status: 'perfect'})
    expect(unknown.outcome).toBe('interrupted')
  })

  it('treats cancellation acknowledgement as terminal and rejects all late completion/start updates', () => {
    const reading = apply(apply(startResearch(), 2, 'query_started', {query_id: 'q1'}), 3, 'source_started', {source_id: 'S1'})
    const cancelled = apply(reading, 4, 'research_finished', {status: 'cancelled'})
    expect(cancelled.queries[0].state).toBe('cancelled')
    expect(cancelled.sources[0].state).toBe('cancelled')
    for (const [name, fields] of [
      ['query_started', {query_id: 'q2'}], ['source_read', {source_id: 'S1', sources_read: 1}],
      ['research_followup_started', {}], ['research_finished', {status: 'completed'}],
    ] as const) {
      expect(apply(cancelled, 5, name, fields)).toBe(cancelled)
    }
  })

  it('settles a missing research finish honestly when the parent chat ends', () => {
    const current = apply(startResearch(), 2, 'source_started', {source_id: 'S1'})
    expect(settleResearchActivity(current, 'done', 900)?.outcome).toBe('interrupted')
    expect(settleResearchActivity(current, 'done', 900)?.sources[0].state).toBe('not_read')
    expect(settleResearchActivity(current, 'cancelled', 900)?.outcome).toBe('cancelled')
    expect(settleResearchActivity(current, 'cancelled', 900)?.sources[0].state).toBe('cancelled')
    const complete = apply(current, 3, 'research_finished', {status: 'completed'})
    expect(settleResearchActivity(complete, 'done', 900)).toBe(complete)
    expect(settleResearchActivity(undefined, 'done', 900)).toBeUndefined()
  })
})

describe('citation-reference counts', () => {
  it('requires an actual check event and keeps reference membership separate from semantic support', () => {
    const finished = apply(startResearch(), 2, 'research_finished', {status: 'completed'})
    expect(finished.citations).toBeUndefined()
    const checked = apply(finished, 3, 'research_citations_checked', {checked: 5, invalid: 2, semantic_support: 'unchecked'})
    expect(checked.citations).toEqual({checked: 5, invalid: 2, semanticSupport: 'unchecked'})
    expect(checked.outcome).toBe('completed')
    expect(checked.endedAt).toBe(finished.endedAt)
    expect(apply(finished, 3, 'research_citations_checked', {checked: 0, invalid: 0, semantic_support: 'unchecked'}).citations?.checked).toBe(0)
  })

  it.each([
    {checked: 1, invalid: 4, semantic_support: 'unchecked'},
    {checked: 1, invalid: 0, semantic_support: 'verified'},
    {checked: 1, invalid: 0},
    {checked: -1, invalid: 0, semantic_support: 'unchecked'},
    {checked: 1.2, invalid: 0, semantic_support: 'unchecked'},
    {checked: 1, invalid: NaN, semantic_support: 'unchecked'},
  ])('rejects inconsistent or unsupported citation results: %j', fields => {
    const current = startResearch()
    expect(apply(current, 2, 'research_citations_checked', fields)).toBe(current)
  })
})

describe('safe source destinations', () => {
  it('accepts explicit HTTP(S) URLs and normalizes a valid Unicode hostname', () => {
    expect(safeResearchUrl('https://evidence.example/path?q=topic#section')).toBe('https://evidence.example/path?q=topic#section')
    expect(safeResearchUrl('http://evidence.example')).toBe('http://evidence.example/')
    expect(new URL(safeResearchUrl('https://bücher.example/page')).hostname).toBe('xn--bcher-kva.example')
  })

  it.each([
    undefined, null, 42, '', '/relative/path', '//evidence.example/page',
    'javascript:alert(1)', 'data:text/html,<script>alert(1)</script>', 'file:///tmp/private',
    'https://user:password@evidence.example/', 'https://user@evidence.example/',
    'https://evidence.example/' + 'a'.repeat(2048),
  ])('does not turn an unsafe or malformed destination into a link: %s', value => {
    expect(safeResearchUrl(value)).toBe('')
  })
})
