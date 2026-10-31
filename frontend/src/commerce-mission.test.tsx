// @vitest-environment jsdom
import {afterEach, describe, expect, it, vi} from 'vitest'
import {cleanup, render, screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {CommerceMissionControl, type MissionSnapshot} from './CommerceMissionControl'

afterEach(cleanup)

const business = {
  id: 'a'.repeat(32), name: 'Northline Studio', niche: 'Editable gaming creator graphics',
  channel: 'etsy', paused: true, candidate_count: 2, queued_checks: 1,
  created_at: '2026-10-18T13:00:00Z',
}
const second = {
  id: 'b'.repeat(32), name: 'Sound Lab', niche: 'Original musical asset packs',
  channel: 'shopify', paused: false, candidate_count: 3, queued_checks: 2,
  created_at: '2026-10-18T13:00:00Z',
}
const snapshot: MissionSnapshot = {
  businesses: [business, second],
  preflight_jobs: [
    {id: 'c'.repeat(32), business_id: second.id, idea_id: 'd'.repeat(32),
      title: 'Synth texture pack', status: 'queued', blockers: [],
      created_at: '2026-10-18T13:00:00Z', checked_at: null},
    {id: 'e'.repeat(32), business_id: business.id, idea_id: 'f'.repeat(32),
      title: 'Overlay scenes', status: 'needs_evidence',
      blockers: ['Review original rights'], created_at: '2026-10-18T13:00:00Z',
      checked_at: '2026-10-18T14:00:00Z'},
  ],
  job_counts: {queued: 3, review_ready: 0, needs_evidence: 1, stale: 0, cancelled: 0},
  recent_activity: [{action: 'preflight_queued', at: '2026-10-18T13:00:00Z',
    business_id: second.id, job_id: 'c'.repeat(32)}],
  mission_control: {
    scope: 'private_local_project',
    execution_mode: 'manual_batch_deterministic_preflight_only',
    auto_start: false, marketplace_write_access: false, real_sales_feed: false,
    maximum_businesses: 100, maximum_checks_per_batch: 20,
  },
}
const props = {
  board: snapshot, preview: false, busy: false, selectedBusinessId: '',
}

describe('Star Mission Control', () => {
  it('displays actual local records and no invented account connections or revenue', () => {
    const onAction = vi.fn()
    render(<CommerceMissionControl {...props} onSelectBusiness={vi.fn()} onAction={onAction}/>)
    expect(screen.getByText('Every business. One view.')).toBeTruthy()
    expect(screen.getByText('Northline Studio')).toBeTruthy()
    expect(screen.getByText('Sound Lab')).toBeTruthy()
    expect(screen.getByText('External selling remains disconnected')).toBeTruthy()
    expect(screen.getByText('Synth texture pack')).toBeTruthy()
    expect(screen.getByText('1 evidence checks outstanding')).toBeTruthy()
    expect(screen.queryByText(/\$[0-9]/)).toBeNull()
    expect(onAction).not.toHaveBeenCalled()
  })

  it('creates businesses as paused local records, not marketplace shops', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()
    render(<CommerceMissionControl {...props} onSelectBusiness={vi.fn()} onAction={onAction}/>)
    await user.click(screen.getByRole('button', {name: 'Add business'}))
    await user.type(screen.getByRole('textbox', {name: 'Business name'}), 'Arcadia Packs')
    await user.type(screen.getByRole('textbox', {name: 'Customer niche'}), 'Original creator files')
    await user.selectOptions(screen.getByRole('combobox', {name: 'Planned marketplace'}), 'printify')
    await user.click(screen.getByRole('button', {name: 'Save locally'}))
    expect(onAction).toHaveBeenCalledWith('commerceCreateBusiness',
      {name:'Arcadia Packs', niche:'Original creator files', channel:'printify'},
      expect.stringContaining('paused'))
    expect(onAction.mock.calls.some(call => call[0] === 'commercePublish')).toBe(false)
  })

  it('filters 100-shop portfolios and lets owner pause one without touching others', async () => {
    const onAction = vi.fn()
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<CommerceMissionControl {...props} onSelectBusiness={onSelect} onAction={onAction}/>)
    await user.type(screen.getByRole('searchbox', {name: 'Find business'}), 'sound')
    expect(screen.getByText('Sound Lab')).toBeTruthy()
    expect(screen.queryByText('Northline Studio')).toBeNull()
    await user.click(screen.getByRole('button', {name: 'Filter candidates for Sound Lab'}))
    expect(onSelect).toHaveBeenCalledWith(second.id)
    await user.click(screen.getByRole('button', {name: 'Pause checks for Sound Lab'}))
    expect(onAction).toHaveBeenCalledWith('commercePauseBusiness',
      {id: second.id, paused:true},expect.any(String))
  })

  it('runs a bounded explicit local preflight batch, never publishes', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()
    render(<CommerceMissionControl {...props} onSelectBusiness={vi.fn()} onAction={onAction}/>)
    await user.click(screen.getByRole('button', {name: 'Run up to 8 checks'}))
    expect(onAction).toHaveBeenCalledWith('commerceRunPreflight',{limit:8},
      expect.stringContaining('Nothing was published'))
    await user.click(screen.getByRole('button', {name: 'Cancel checklist for Synth texture pack'}))
    expect(onAction).toHaveBeenCalledWith('commerceCancelPreflight',{id:'c'.repeat(32)},expect.any(String))
    expect(onAction.mock.calls.some(call => /Publish|Spend|SendMessage/.test(call[0]))).toBe(false)
  })

  it('respects preview and an entirely paused portfolio', () => {
    const onAction = vi.fn()
    const {rerender} = render(<CommerceMissionControl {...props} preview
      onSelectBusiness={vi.fn()} onAction={onAction}/>)
    expect(screen.getByRole('button', {name:'Add business'}).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', {name:'Run up to 8 checks'}).hasAttribute('disabled')).toBe(true)
    rerender(<CommerceMissionControl {...props}
      board={{...snapshot,businesses:[business]}} onSelectBusiness={vi.fn()} onAction={onAction}/>)
    expect(screen.getByRole('button', {name:'Run up to 8 checks'}).hasAttribute('disabled')).toBe(true)
    expect(onAction).not.toHaveBeenCalled()
  })

  it('reveals only real local history when requested', async () => {
    const user = userEvent.setup()
    render(<CommerceMissionControl {...props} onSelectBusiness={vi.fn()} onAction={vi.fn()}/>)
    const button = screen.getByRole('button', {name:/Show local audit history/})
    await user.click(button)
    expect(button.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByRole('region', {name:'Local audit history'}).textContent).toContain('preflight queued')
  })
})
