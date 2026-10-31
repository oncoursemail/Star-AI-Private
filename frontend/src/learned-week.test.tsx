// @vitest-environment jsdom
/**
 * "What STAR learned this week" and owner corrections (W7, W8).
 *
 * Contract under test: what the page sends to the desktop host (`learnedThisWeek`, `learnedItem` and
 * `reviewCorrection` with the owner's explicit `approved`, `messageFeedback` with a `correction`) and
 * the words the owner reads. No class names.
 */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {LearnedThisWeek, stateText} from './LearnedThisWeek'
import {Message} from './components'
import type {ChatMessage, CorrectionItem, LearnedItem, LearnedWeek} from './types'

afterEach(cleanup)

const item = (over: Partial<LearnedItem>): LearnedItem => ({
  id: 1, kind: 'lesson', title: 'Clamp a stamina value with math.clamp before writing it to an attribute.',
  evidence: 'night school: fixed practice tasks P-01, P-02; validation slice 10/24 -> 15/24; paired gate PROMOTE: 9 wins / 2 losses over 24 tasks x k=2, sign test p=0.0327',
  gate: {decision: 'PROMOTE', wins: 9, losses: 2, tasks: 24, k: 2, p_better: 0.0327}, live_at: '2026-10-13T10:00:00+00:00',
  expires_at: '2026-10-27T10:00:00+00:00', days_left: 14, state: 'live', uses: 0, ...over})
const fix = (over: Partial<CorrectionItem>): CorrectionItem => ({
  id: 7, created: '2026-10-13T10:00:00+00:00', source: 'app', prompt: 'Write a script that waits and opens the door.',
  answer: 'wait(2) workspace.Door.Transparency = 1', correction: 'Use task.wait instead of wait.', cause: 'invented API name',
  status: 'candidate', task_id: '', ...over})

function host(items: LearnedItem[], corrections: CorrectionItem[], audit: unknown = null) {
  let list = items.slice()
  let fixes = corrections.slice()
  const calls: Array<{action: string; params: Record<string, unknown>}> = []
  const week = (): LearnedWeek => ({project: 'MyGame', items: list, counts: {live: list.filter(i => i.state === 'live').length}})
  const listing = () => ({project: 'MyGame', corrections: fixes, counts: {candidate: fixes.filter(f => f.status === 'candidate').length,
    approved: fixes.filter(f => f.status === 'approved').length, dismissed: 0}, suite: 'corrections-MyGame.json'})
  const invoke = vi.fn(async (action: string, params: Record<string, unknown> = {}) => {
    calls.push({action, params})
    if (action === 'learnedThisWeek') return week()
    if (action === 'listCorrections') return listing()
    if (action === 'learnedItem') {
      if (params.approved !== true) return null
      list = list.map(i => i.id !== params.id ? i : {...i, state: params.op === 'undo' ? 'undone' : params.op === 'keep' ? 'kept' : 'live',
        days_left: params.op === 'keep' ? null : i.days_left, expires_at: params.op === 'keep' ? '' : i.expires_at})
      return week()
    }
    if (action === 'reviewCorrection') {
      if (params.approved !== true) return null
      fixes = fixes.map(f => f.id !== params.id ? f : {...f, status: params.op === 'approve' ? 'approved' : 'dismissed',
        task_id: params.op === 'approve' ? 'CR-0007' : ''})
      return listing()
    }
    if (action === 'selfAudit') return {report: audit}
    return {}
  })
  return {invoke, sent: (action: string) => calls.filter(c => c.action === action)}
}

describe('what STAR learned this week', () => {
  it('shows the weekly self-audit the host stored, and nothing when there is none yet', async () => {
    const report = {generated: '2026-10-25T10:00:00Z', strengths: ['luau-typing: 83% of 12 scored tasks'],
      weaknesses: ['most common failure class: invented API name (7 failed tasks)'], missing: ['receipts']}
    const withReport = host([item({})], [], report)
    render(<LearnedThisWeek invoke={withReport.invoke} project="MyGame"/>)
    expect(await screen.findByText(/weekly self-audit/i)).toBeTruthy()
    expect(screen.getByText('luau-typing: 83% of 12 scored tasks')).toBeTruthy()
    expect(screen.getByText(/most common failure class: invented API name/)).toBeTruthy()
    expect(screen.getByText(/No data on this PC for: receipts/)).toBeTruthy()
    expect(withReport.sent('selfAudit')).toHaveLength(1)
    cleanup()
    const without = host([item({})], [])
    render(<LearnedThisWeek invoke={without.invoke} project="MyGame"/>)
    await screen.findByText(/Clamp a stamina value/)
    expect(screen.queryByText(/weekly self-audit/i)).toBeNull()
  })

  it('lists a live lesson with its evidence, days left and the gate result', async () => {
    const h = host([item({}), item({id: 2, kind: 'example', title: 'Write a Luau module that clamps stamina.', gate: {}, days_left: 3})], [])
    render(<LearnedThisWeek invoke={h.invoke} project="MyGame"/>)
    expect(await screen.findByText(/Clamp a stamina value/)).toBeTruthy()
    expect(screen.getByText('In use · 14 days left')).toBeTruthy()
    expect(screen.getByText('In use · 3 days left')).toBeTruthy()
    expect(screen.getByText(/Beat the current lessons on held-out practice: 9 wins, 2 losses over 24 tasks/)).toBeTruthy()
    expect(screen.getByText(/not a Roblox Studio test/)).toBeTruthy()
    expect(screen.getByText('2 in use')).toBeTruthy()
  })

  it('undoes with one click, then restores or keeps, always with the owner flag', async () => {
    const h = host([item({})], [])
    const user = userEvent.setup()
    render(<LearnedThisWeek invoke={h.invoke} project="MyGame"/>)
    const row = (await screen.findByText(/Clamp a stamina value/)).closest('li') as HTMLElement
    await user.click(within(row).getByRole('button', {name: /undo/i}))
    await waitFor(() => expect(h.sent('learnedItem')).toHaveLength(1))
    expect(h.sent('learnedItem')[0].params).toEqual({op: 'undo', id: 1, approved: true})
    expect(await screen.findByText('Undone: STAR does not use it')).toBeTruthy()
    await user.click(within(row).getByRole('button', {name: /restore/i}))
    await waitFor(() => expect(h.sent('learnedItem')).toHaveLength(2))
    expect(h.sent('learnedItem')[1].params).toEqual({op: 'restore', id: 1, approved: true})
    await user.click(within(row).getByRole('button', {name: /keep for good/i}))
    await waitFor(() => expect(h.sent('learnedItem')).toHaveLength(3))
    expect(h.sent('learnedItem')[2].params).toEqual({op: 'keep', id: 1, approved: true})
    expect(await screen.findByText('Kept for good')).toBeTruthy()
    expect(within(row).queryByRole('button', {name: /keep for good/i})).toBeNull()
  })

  it('says plainly when nothing was learned and describes each state', async () => {
    render(<LearnedThisWeek invoke={host([], []).invoke} project="MyGame"/>)
    expect(await screen.findByText(/Nothing new this week/)).toBeTruthy()
    expect(stateText(item({state: 'expired'}))).toMatch(/14 days ended/)
    expect(stateText(item({days_left: 1}))).toBe('In use · 1 day left')
  })
})

describe('owner corrections', () => {
  it('turns a waiting correction into a test only on the owner\'s click', async () => {
    const h = host([], [fix({}), fix({id: 8, source: 'discord', correction: 'The leaderboard is sorted the wrong way.', cause: 'wrong logic'})])
    const user = userEvent.setup()
    render(<LearnedThisWeek invoke={h.invoke} project="MyGame"/>)
    expect(await screen.findByText('Use task.wait instead of wait.')).toBeTruthy()
    expect(screen.getByText('2 waiting')).toBeTruthy()
    expect(screen.getByText('From Discord')).toBeTruthy()
    expect(screen.getByText('Looks like a made-up or outdated API')).toBeTruthy()
    const row = screen.getByText('Use task.wait instead of wait.').closest('li') as HTMLElement
    await user.click(within(row).getByRole('button', {name: /make it a test/i}))
    await waitFor(() => expect(h.sent('reviewCorrection')).toHaveLength(1))
    expect(h.sent('reviewCorrection')[0].params).toEqual({op: 'approve', id: 7, approved: true})
    expect(await screen.findByText(/never the blind exam/)).toBeTruthy()
    expect(screen.getByText(/In the corrections suite: CR-0007/)).toBeTruthy()
    const other = screen.getByText('The leaderboard is sorted the wrong way.').closest('li') as HTMLElement
    await user.click(within(other).getByRole('button', {name: /dismiss/i}))
    await waitFor(() => expect(h.sent('reviewCorrection')).toHaveLength(2))
    expect(h.sent('reviewCorrection')[1].params).toEqual({op: 'dismiss', id: 8, approved: true})
  })

  it('offers a correction box only under an answer marked not helpful', async () => {
    const user = userEvent.setup()
    const onCorrect = vi.fn(async () => true)
    const answer: ChatMessage = {id: 'a1', role: 'assistant', text: 'Use wait(2).', mid: 42, feedback: 'up'}
    const {rerender} = render(<Message entry={answer} animated={false} onFeedback={() => {}} onCorrect={onCorrect}/>)
    expect(screen.queryByRole('textbox', {name: /what was wrong/i})).toBeNull()
    rerender(<Message entry={{...answer, feedback: 'down'}} animated={false} onFeedback={() => {}} onCorrect={onCorrect}/>)
    const box = screen.getByRole('textbox', {name: /what was wrong/i})
    expect((screen.getByRole('button', {name: /save correction/i}) as HTMLButtonElement).disabled).toBe(true)
    await user.type(box, 'Use task.wait instead of wait.')
    await user.click(screen.getByRole('button', {name: /save correction/i}))
    await waitFor(() => expect(onCorrect).toHaveBeenCalledWith('Use task.wait instead of wait.'))
    // It names the section the owner can actually find (there is no "Learning panel").
    expect(await screen.findByText('Correction saved. It waits under Your corrections on the Projects page, where you can make it a test.')).toBeTruthy()
    expect(screen.queryByText(/Learning panel/)).toBeNull()
  })
})
