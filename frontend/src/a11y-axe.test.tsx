// @vitest-environment jsdom
/**
 * axe-core over the real desktop shell (fake Qt bridge, no mocked components): every page, the open menus and
 * the screen-capture dialog. Fails on any WCAG 2.x A/AA or best-practice violation axe can decide in jsdom.
 *
 * jsdom does not lay out or paint, so axe's colour-contrast rule cannot run here; contrast is checked on the
 * token pairs (see the colour-token test) and in a real browser for the PR screenshots.
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import axe from 'axe-core'
import {App} from './App'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => { desktop.reset(); try { localStorage.clear() } catch { /* storage unavailable */ } })
afterEach(cleanup)

const chats = [
  {id: 'c1', title: 'Inventory UI for Ember Hollow', created: '2026-10-13T09:00:00', updated: new Date().toISOString()},
  {id: 'c2', title: 'Why does my RemoteEvent fire twice?', created: '2026-10-12T09:00:00', updated: '2026-10-12T09:00:00'},
]
const messages = [
  {id: 'm1', mid: 1, role: 'user', text: 'Design an inventory grid for phones.', created: '2026-10-13T09:00:00'},
  {id: 'm2', mid: 2, role: 'assistant', text: '## Layout\n\nA 4×4 `UIGridLayout` with 64 px slots.\n\n| Slot | Size |\n|---|---|\n| Small | 48 |\n\n```lua\nlocal grid = script.Parent\n```', created: '2026-10-13T09:00:05'},
]

async function check(label: string) {
  const result = await axe.run(document.body, {
    runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']},
    rules: {'color-contrast': {enabled: false}},
    resultTypes: ['violations'],
  })
  const found = result.violations.map(v => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map(n => n.target.join(' ')).join(' | ')}`)
  expect(found, `axe violations on ${label}`).toEqual([])
}

async function open(boot: Record<string, unknown> = {}) {
  desktop.host({chats, active_chat: 'c1', messages, ...boot})
  const user = userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i}, {timeout: 5000})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  return user
}

describe('axe harness', () => {
  it('is not vacuous: an unnamed icon button is reported', async () => {
    render(<main><h1>Probe</h1><button type="button"><svg aria-hidden="true"/></button></main>)
    const result = await axe.run(document.body, {runOnly: {type: 'rule', values: ['button-name']}})
    expect(result.violations.map(v => v.id)).toEqual(['button-name'])
  })
})

describe('axe: pages', () => {
  it('chat with a conversation', async () => {
    await open()
    await screen.findByText('Layout')
    await check('chat')
  })

  it('a new, empty chat', async () => {
    await open({messages: [], chats: [], active_chat: ''})
    await check('empty chat')
  })

  for (const [page, more] of [['Projects', false], ['Tools', false], ['Business', false], ['Settings', false], ['Library', true], ['Analytics', true], ['Model', true]] as const) {
    it(page, async () => {
      const user = await open()
      if (more) await user.click(screen.getByRole('button', {name: 'More'}))
      await user.click(screen.getByRole('button', {name: page === 'Model' ? page : new RegExp('^' + page)}))
      const titles = await screen.findAllByRole('heading', {level: 1})
      expect(titles.map(t => t.textContent), 'one page title').toHaveLength(1)
      await check(page)
    })
  }
})

describe('axe: open menus and dialogs', () => {
  it('the + menu', async () => {
    const user = await open()
    await user.click(screen.getByRole('button', {name: 'Add files and tools'}))
    await screen.findByRole('menu')
    await check('+ menu')
  })

  it('the mode picker', async () => {
    const user = await open()
    await user.click(screen.getByRole('button', {name: /^Mode:/}))
    await check('mode picker')
  })

  it('a chat row menu and the chat options menu', async () => {
    const user = await open()
    await user.click(screen.getByRole('button', {name: 'More options for Inventory UI for Ember Hollow'}))
    await screen.findByRole('menu')
    await check('chat row menu')
    await user.keyboard('{Escape}')
    await user.click(screen.getByRole('button', {name: 'Chat options'}))
    await screen.findByRole('menu')
    await check('chat options menu')
  })

  it('the screen-capture consent dialog', async () => {
    const user = await open()
    await user.click(screen.getByRole('button', {name: 'Add files and tools'}))
    await user.click(await screen.findByRole('menuitem', {name: /look at my screen/i}))
    await screen.findByRole('dialog')
    await check('consent dialog')
  })
})

describe('keyboard', () => {
  it('starts with a skip link that moves focus to the message box', async () => {
    const user = await open()
    // body.focus() does not move focus off an element that already has it (the composer may on open)
    ;(document.activeElement as HTMLElement | null)?.blur()
    await user.tab()
    const skip = document.activeElement as HTMLElement
    expect(skip.textContent).toBe('Skip to message box')
    await user.keyboard('{Enter}')
    expect(document.activeElement).toBe(screen.getByRole('textbox', {name: /message star/i}))
  })

  it('the skip link moves focus to the page on other pages', async () => {
    const user = await open()
    await user.click(screen.getByRole('button', {name: /^Projects/}))
    ;(document.activeElement as HTMLElement | null)?.blur()
    await user.tab()
    expect(document.activeElement?.textContent).toBe('Skip to page content')
    await user.keyboard('{Enter}')
    expect(document.activeElement).toBe(screen.getByRole('main'))
  })
})
