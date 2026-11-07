// @vitest-environment jsdom
import {afterEach, describe, expect, it, vi} from 'vitest'
import {act, cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import {ActivityTimeline} from './ActivityTimeline'
import {applyProgress, settleRun, startRun} from './activity'
import type {ActivityRun} from './activity'
import {MotionPolicy} from './MotionPolicy'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

/** Explicit synthetic wire events for UI tests; the product has no demo research data. */
function append(run: ActivityRun, name: string, fields: Record<string, unknown> = {}): ActivityRun {
  const seq = (run.research?.lastSeq || 0) + 1
  return applyProgress(run, {activity: {
    type: 'research', event: name, run_id: 'research-1', event_id: `research-1:${seq}`, seq,
    phase: 'search', ...fields,
  }}, Date.now())
}

function researchRun(sourceCount = 0, queryCount = 0): ActivityRun {
  let run = append(startRun('chat-1', 'chat', Date.now()), 'research_started')
  for (let ordinal = 1; ordinal <= queryCount; ordinal++) {
    run = append(run, 'query_started', {query_id: `q${ordinal}`, ordinal, queries: ordinal})
    run = append(run, 'query_completed', {query_id: `q${ordinal}`, ordinal})
  }
  for (let ordinal = 1; ordinal <= sourceCount; ordinal++) {
    run = append(run, 'source_started', {
      source_id: `S${ordinal}`, title: `Evidence page ${ordinal}`, url: `https://evidence.example/page/${ordinal}`,
      sources_found: sourceCount, pages: ordinal, sources_read: ordinal - 1,
    })
    run = append(run, 'source_read', {source_id: `S${ordinal}`, sources_read: ordinal})
  }
  return run
}

function Surface({run, onStop, stopping = false}: {run: ActivityRun; onStop?: () => void; stopping?: boolean}) {
  return <MotionPolicy reduced><main className="shell">
    <h1>Research review</h1><h2>Current run</h2>
    <ActivityTimeline run={run} onStop={onStop} stopping={stopping} />
  </main></MotionPolicy>
}

describe('research activity in the existing timeline', () => {
  it('has no research cards or sources before an actual research session starts', () => {
    render(<Surface run={startRun('ordinary-chat', 'chat', Date.now())} />)
    expect(screen.queryByRole('region', {name: 'Sources'})).toBeNull()
    expect(screen.queryByText('Deep research')).toBeNull()
    expect(screen.queryByRole('region', {name: 'Citation reference checks'})).toBeNull()
  })

  it('renders source reading state separately from the aggregate Found and Read counts', () => {
    let run = researchRun()
    run = append(run, 'source_started', {
      source_id: 'S1', title: 'Page being read', url: 'https://evidence.example/one', sources_found: 5,
    })
    const {rerender, container} = render(<Surface run={run} />)
    const counts = container.querySelector('.research-counts')!
    expect(within(counts as HTMLElement).getByText('Found').nextElementSibling?.textContent).toBe('5')
    expect(within(counts as HTMLElement).getByText('Read').nextElementSibling?.textContent).toBe('0')
    const sources = screen.getByRole('region', {name: 'Sources'})
    expect(within(sources).getByText('Reading')).toBeTruthy()
    expect(within(sources).queryByText('Read', {exact: true})).toBeNull()
    run = append(run, 'source_failed', {source_id: 'S1', sources_failed: 1})
    rerender(<Surface run={run} />)
    expect(within(sources).getByText('Could not read')).toBeTruthy()
    expect(within(counts as HTMLElement).getByText('Read').nextElementSibling?.textContent).toBe('0')
  })

  it('uses safe ordinary links, renders hostile-looking titles as text, and loads no remote icons', () => {
    const title = '<img src="https://tracking.example/pixel" onerror="alert(1)"> & evidence'
    let run = researchRun()
    run = append(run, 'source_read', {
      source_id: 'S1', title, url: 'https://evidence.example/safe', sources_found: 2, sources_read: 1,
    })
    run = append(run, 'source_failed', {source_id: 'S2', title: 'Unsafe destination', url: 'javascript:alert(1)'})
    const {container} = render(<Surface run={run} />)
    expect(screen.getByText(title)).toBeTruthy()
    const link = screen.getByRole('link', {name: /tracking\.example/})
    expect(link.getAttribute('href')).toBe('https://evidence.example/safe')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')?.split(' ')).toEqual(expect.arrayContaining(['noopener', 'noreferrer']))
    expect(link.textContent).toContain('opens in a new tab')
    expect(screen.queryByRole('link', {name: /Unsafe destination/})).toBeNull()
    expect(container.querySelector('img, iframe, script')).toBeNull()
    for (const svg of container.querySelectorAll('svg')) expect(svg.getAttribute('aria-hidden')).toBe('true')
  })

  it('offers keyboard-accessible source and query disclosures with valid control relationships', async () => {
    const user = userEvent.setup()
    render(<Surface run={researchRun(6, 5)} />)
    const sources = screen.getByRole('region', {name: 'Sources'})
    expect(within(sources).getAllByRole('listitem')).toHaveLength(4)
    const sourceToggle = within(sources).getByRole('button', {name: 'Show all 6 sources'})
    expect(sourceToggle.getAttribute('aria-expanded')).toBe('false')
    expect(document.getElementById(sourceToggle.getAttribute('aria-controls')!)).toBe(within(sources).getByRole('list'))
    sourceToggle.focus()
    await user.keyboard('{Enter}')
    expect(sourceToggle.getAttribute('aria-expanded')).toBe('true')
    expect(within(sources).getAllByRole('listitem')).toHaveLength(6)
    await user.click(within(sources).getByRole('button', {name: 'Show fewer sources'}))
    expect(within(sources).getAllByRole('listitem')).toHaveLength(4)

    const searches = screen.getByRole('list', {name: 'Search activity'})
    expect(within(searches).getAllByRole('listitem')).toHaveLength(3)
    expect(within(searches).queryByText('Search 1')).toBeNull()
    const queryToggle = screen.getByRole('button', {name: 'Show all 5 searches'})
    expect(document.getElementById(queryToggle.getAttribute('aria-controls')!)).toBe(searches)
    queryToggle.focus()
    await user.keyboard(' ')
    expect(queryToggle.getAttribute('aria-expanded')).toBe('true')
    expect(within(searches).getAllByRole('listitem')).toHaveLength(5)
    expect(within(searches).getByText('Search 1')).toBeTruthy()
  })

  it('keeps a single polite phase region mounted while clocks and source counts change', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-19T04:00:00Z'))
    let run = researchRun(1)
    const {rerender, container} = render(<Surface run={run} />)
    const status = screen.getByRole('status')
    expect(status.getAttribute('aria-live')).toBe('polite')
    expect(status.getAttribute('aria-atomic')).toBe('true')
    expect(status.textContent).toBe('Reading source pages')
    const originalClock = container.querySelector('.act-clock')?.textContent
    act(() => { vi.advanceTimersByTime(3100) })
    expect(container.querySelector('.act-clock')?.textContent).not.toBe(originalClock)
    expect(screen.getByRole('status')).toBe(status)
    expect(status.textContent).toBe('Reading source pages')
    run = append(run, 'source_read', {source_id: 'S2', title: 'Second source', sources_found: 2, sources_read: 2})
    rerender(<Surface run={run} />)
    expect(screen.getByRole('status')).toBe(status)
    expect(status.textContent).toBe('Reading source pages')
    expect(status.textContent).not.toMatch(/\d|Second source/)
    const activeLiveRegions = [...container.querySelectorAll('[aria-live], [role="status"]')]
      .filter(element => element.getAttribute('aria-live') !== 'off')
    expect(activeLiveRegions).toHaveLength(1)
    expect(screen.getByRole('timer').getAttribute('aria-live')).toBe('off')
    expect(container.querySelector('.research-counts')?.closest('[aria-live]')).toBeNull()
  })

  it('honors reduced motion and keeps the phase accessible when the research details are collapsed', async () => {
    const user = userEvent.setup()
    const {container} = render(<Surface run={researchRun(1)} />)
    expect(document.documentElement.getAttribute('data-star-reduced-motion')).toBe('true')
    expect(container.querySelector('.act-spin')).toBeNull()
    const toggle = screen.getByRole('button', {name: /Deep research/})
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(document.getElementById(toggle.getAttribute('aria-controls')!)).not.toBeNull()
    await user.click(toggle)
    await waitFor(() => expect(screen.queryByRole('region', {name: 'Sources'})).toBeNull())
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.getByRole('status').textContent).toBe('Reading source pages')
    toggle.focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('region', {name: 'Sources'})).toBeTruthy()
  })

  it('retains the existing stop acknowledgement flow for research sessions', async () => {
    const user = userEvent.setup()
    const stop = vi.fn()
    const running = researchRun(1)
    const {rerender} = render(<Surface run={running} onStop={stop} />)
    await user.click(screen.getByRole('button', {name: 'Stop'}))
    expect(stop).toHaveBeenCalledOnce()
    expect(running.outcome).toBe('running')
    rerender(<Surface run={running} onStop={stop} stopping />)
    expect(screen.getByRole('button', {name: 'Stopping'})).toHaveProperty('disabled', true)
    expect(screen.getByRole('status').textContent).toBe('Stopping research')
    const stopped = settleRun(running, 'cancelled', Date.now())
    rerender(<Surface run={stopped} onStop={stop} />)
    expect(screen.queryByRole('button', {name: 'Stop'})).toBeNull()
    expect(screen.getByRole('status').textContent).toBe('Research run stopped')
  })

  it('shows citation checks only for a real validation event and never labels them claim verification', () => {
    let run = researchRun(1)
    const {rerender} = render(<Surface run={run} />)
    expect(screen.queryByRole('region', {name: 'Citation reference checks'})).toBeNull()
    run = append(run, 'research_finished', {status: 'completed'})
    run = append(run, 'research_citations_checked', {checked: 4, invalid: 1, semantic_support: 'unchecked'})
    rerender(<Surface run={run} />)
    const checks = screen.getByRole('region', {name: 'Citation reference checks'})
    expect(within(checks).getByText('4 checked · 1 unresolved')).toBeTruthy()
    expect(checks.textContent).toContain('Whether sources support each claim has not been checked')
    expect(checks.textContent).not.toMatch(/\d+%|confidence|verified|truth score/i)
    expect(screen.getByRole('status').textContent).toBe('Checking citation references')
  })

  it('has no automatically detectable WCAG violations in the expanded research controls', async () => {
    const run = append(researchRun(6, 5), 'research_citations_checked', {checked: 3, invalid: 0, semantic_support: 'unchecked'})
    const {container} = render(<Surface run={run} onStop={() => undefined} />)
    const result = await axe.run(container, {
      runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']},
      // jsdom has no layout or paint. Color/geometry need a browser review.
      rules: {'color-contrast': {enabled: false}},
      resultTypes: ['violations'],
    })
    expect(result.violations.map(violation => ({id: violation.id, targets: violation.nodes.map(node => node.target)}))).toEqual([])
  })
})
