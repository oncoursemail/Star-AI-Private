// @vitest-environment jsdom
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {CommercePanel} from './CommercePanel'
import {initializeBridge} from './bridge'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'

let bridge: FakeDesktop
const board = {
  project: 'STAR' as const,
  data_source: 'local_app_data_only' as const,
  automation: {state: 'not_enabled', description: 'No background selling.'},
  counts: {candidates: 0, review_ready: 0, approved_for_export: 0, live_listings: 0 as const, verified_sales: null},
  platforms: [{id: 'etsy' as const, label: 'Etsy', connection: 'not_connected_in_star', note: 'OAuth required'}],
  ideas: [],
}
beforeAll(async () => {
  bridge = installFakeDesktop()
  await initializeBridge()
})
beforeEach(() => bridge.reset())
afterEach(cleanup)

describe('STAR Business integration', () => {
  it('does not claim a preview can sell products or load a private DB', () => {
    render(<CommercePanel project="STAR" preview />)
    expect(screen.getByText(/Browser preview only/)).toBeTruthy()
    expect(screen.getByText(/No sales feed connected/)).toBeTruthy()
    expect(screen.getByRole('button', {name: 'New candidate'}).hasAttribute('disabled')).toBe(true)
    expect(bridge.sent('commerceBoard')).toHaveLength(0)
  })

  it('creates a real candidate through the permitted bridge action', async () => {
    bridge.onAction('commerceBoard', () => ({ok: true, data: board}))
    bridge.onAction('commerceCreate', call => ({
      ok: true,
      data: {
        ...board,
        counts: {...board.counts, candidates: 1},
        ideas: [{
          id: 'a'.repeat(32),
          title: String(call.payload.title),
          concept: String(call.payload.concept),
          channel: 'etsy',
          status: 'draft',
          evidence: {},
          review: {ready: false, blockers: ['Rights review needed'], owner_approval_required: true, external_actions_performed: false},
          created_at: '2026-10-18T10:00:00Z',
          updated_at: '2026-10-18T10:00:00Z',
        }],
      },
    }))
    const user = userEvent.setup()
    render(<CommercePanel project="STAR" />)
    await screen.findByText('Nothing to publish yet')
    await user.click(screen.getByRole('button', {name: 'New candidate'}))
    await user.type(screen.getByRole('textbox', {name: 'Original product or service title'}), 'Quiet Signal creator pack')
    await user.type(screen.getByRole('textbox', {name: 'Creative brief / customer problem'}),
      'Original editable stream graphics for creators who need uncluttered scenes.')
    await user.click(screen.getByRole('button', {name: 'Save candidate'}))
    await screen.findByText('Quiet Signal creator pack')
    expect(bridge.sent('commerceCreate')).toHaveLength(1)
    const payload = bridge.sent('commerceCreate')[0].payload
    expect(payload).toMatchObject({channel: 'etsy', title: 'Quiet Signal creator pack'})
    expect(bridge.sent('commerceReview')).toHaveLength(0)
    expect(bridge.sent('commercePublish')).toHaveLength(0)
  })

  it('never offers publication or checkout controls even for a local candidate', async () => {
    bridge.onAction('commerceBoard', () => ({
      ok: true,
      data: {
        ...board,
        counts: {...board.counts, candidates: 1},
        ideas: [{
          id: 'b'.repeat(32), title: 'Offline creator kit',
          concept: 'A distinctive editable pack', channel: 'etsy', status: 'draft',
          evidence: {}, review: {ready: false, blockers: ['Human QA needed'],
            owner_approval_required: true, external_actions_performed: false},
          created_at: '', updated_at: '',
        }],
      },
    }))
    const user = userEvent.setup()
    render(<CommercePanel project="STAR"/>)
    await screen.findByText('Offline creator kit')
    const item = screen.getByRole('button', {name: /Offline creator kit/})
    await user.click(item)
    const approval = within(screen.getByRole('complementary', {name: 'Quality and permissions'}))
      .getByRole('button', {name: 'Approve for export'})
    // Open notes are advice: the owner's click is the only gate, so approval is available.
    expect(approval.hasAttribute('disabled')).toBe(false)
    expect(screen.queryByRole('button', {name: /Publish|Charge buyer|Send Fiverr/i})).toBeNull()
    expect(bridge.sent('commerceReview')).toHaveLength(0)
    bridge.onAction('commerceReview', () => ({ok: true, data: board}))
    await user.click(approval)
    expect(bridge.sent('commerceReview')[0].payload).toMatchObject({decision: 'approve', owner_confirmed: true})
  })
})
