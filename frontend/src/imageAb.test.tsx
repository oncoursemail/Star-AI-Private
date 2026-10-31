// @vitest-environment jsdom
/**
 * The owner's blind A/B page for the old and the new picture pipeline.
 *
 * Contract under test: what the page sends to the host (`imageAbNext`, `imageAbPick` with the pair and the side,
 * `imageAbMake` with the prompt) and what the owner reads: two unlabelled pictures, the host's verdict unchanged, and
 * nothing that says which picture is which pipeline.
 */
import {afterEach, describe, expect, it, vi} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {ImageAbPanel} from './MediaPanel'
import type {AbPair, AbSummary} from './types'

afterEach(cleanup)

const summary = (over: Partial<AbSummary> = {}): AbSummary => ({
  picked: 0, new: 0, old: 0, tie: 0, decided: 0, new_rate: null, p: 1, waiting: 2, pairs: 2,
  verdict: 'Too few decided pairs to say anything yet (0; at least 6 are needed).', ...over})
const pair = (over: Partial<AbPair> = {}): AbPair => ({
  id: 'aaaaaaaaaaaa', prompt: 'a real cow with no weird legs', left: 'data:image/webp;base64,AAAA',
  right: 'data:image/webp;base64,BBBB', waiting: 2, ...over})

function abHost(pairs: AbPair[]) {
  const queue = pairs.slice()
  let picks = 0
  const calls: Array<{action: string; params: Record<string, unknown>}> = []
  const invoke = vi.fn(async (action: string, params: Record<string, unknown> = {}) => {
    calls.push({action, params})
    const current = () => picks === 0 ? summary({waiting: queue.length})
      : summary({picked: picks, new: picks, decided: picks, new_rate: 1, waiting: queue.length, verdict: 'No clear difference yet: new 1, old 0 (p = 1.00).'})
    if (action === 'imageAbNext') return {pair: queue[0] ?? null, summary: current()}
    if (action === 'imageAbPick') { queue.shift(); picks += 1; return {summary: current()} }
    if (action === 'imageAbMake') { queue.push(pair({id: 'cccccccccccc', prompt: String(params.prompt)})); return {made: 'cccccccccccc'} }
    return {}
  })
  return {invoke, sent: (action: string) => calls.filter(c => c.action === action)}
}

describe('picture quality blind test', () => {
  it('shows two unlabelled pictures of one prompt and nothing that says which pipeline made which', async () => {
    const host = abHost([pair()])
    render(<ImageAbPanel invoke={host.invoke}/>)
    const shown = await screen.findByLabelText(/Which picture is better for: a real cow/)
    expect(within(shown).getByRole('img', {name: 'Left picture'}).getAttribute('src')).toBe('data:image/webp;base64,AAAA')
    expect(within(shown).getByRole('img', {name: 'Right picture'}).getAttribute('src')).toBe('data:image/webp;base64,BBBB')
    expect(within(shown).getByText('2 pairs waiting')).toBeTruthy()
    expect(shown.textContent ?? '').not.toMatch(/\b(old|new)\b/i)
  })

  it('sends the side that was picked and shows the next pair and the host\'s verdict', async () => {
    const host = abHost([pair(), pair({id: 'bbbbbbbbbbbb', prompt: 'a horse galloping', waiting: 1})])
    const user = userEvent.setup()
    render(<ImageAbPanel invoke={host.invoke}/>)
    await user.click(await screen.findByRole('button', {name: 'Right is better'}))
    await waitFor(() => expect(host.sent('imageAbPick')).toHaveLength(1))
    expect(host.sent('imageAbPick')[0].params).toEqual({id: 'aaaaaaaaaaaa', side: 'right'})
    expect(await screen.findByLabelText(/Which picture is better for: a horse galloping/)).toBeTruthy()
    const result = await screen.findByRole('status', {name: 'Blind test result'})
    expect(within(result).getByText('No clear difference yet: new 1, old 0 (p = 1.00).')).toBeTruthy()
    expect(within(result).getByText(/1 picked · new 1 · old 0 · same 0 · new wins 100% of the decided pairs/)).toBeTruthy()
  })

  it('sends "same" as a tie', async () => {
    const host = abHost([pair()])
    const user = userEvent.setup()
    render(<ImageAbPanel invoke={host.invoke}/>)
    await user.click(await screen.findByRole('button', {name: 'They look the same'}))
    await waitFor(() => expect(host.sent('imageAbPick')[0]?.params).toEqual({id: 'aaaaaaaaaaaa', side: 'tie'}))
  })

  it('says so when nothing is waiting and draws a new pair from the prompt the owner typed', async () => {
    const host = abHost([])
    const user = userEvent.setup()
    render(<ImageAbPanel invoke={host.invoke}/>)
    expect(await screen.findByText('No pair waiting.')).toBeTruthy()
    const make = screen.getByRole('button', {name: /draw a new pair/i}) as HTMLButtonElement
    expect(make.disabled).toBe(true)                                   // no prompt, no button
    await user.type(screen.getByRole('textbox', {name: 'Prompt for a new pair'}), '  a horse galloping across a field ')
    await user.click(make)
    await waitFor(() => expect(host.sent('imageAbMake')).toHaveLength(1))
    expect(host.sent('imageAbMake')[0].params).toEqual({prompt: 'a horse galloping across a field'})
    expect(await screen.findByLabelText(/Which picture is better for: a horse galloping across a field/)).toBeTruthy()
  })

  it('does nothing while the page is disabled', async () => {
    const host = abHost([pair()])
    render(<ImageAbPanel invoke={host.invoke} disabled/>)
    await new Promise(resolve => setTimeout(resolve, 20))
    expect(host.invoke).not.toHaveBeenCalled()
  })
})
