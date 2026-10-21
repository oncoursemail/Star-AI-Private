// @vitest-environment jsdom
/**
 * Settings page layout: sections as tabs, search across all of them, the unsaved-changes bar, and the two
 * switches and keys the page added (live Roblox docs, automatic web search, Brave/Tavily keys).
 * Driven through the real app root against the fake Qt bridge; no class names are asserted.
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {backendSettings, installFakeDesktop, type FakeDesktop} from './fake-desktop'
import {matchesSearch, normalizeSearch, settingsDirty} from './SettingsPage'
import type {AppSettings} from './types'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => {
  desktop.reset()
  try { window.localStorage.clear() } catch { /* storage unavailable */ }
  desktop.onAction('saveSettings', call => {
    const next = {...backendSettings, ...(call.payload.settings as Record<string, unknown>)}
    desktop.host({settings: next})
    return {ok: true, data: next}
  })
})
afterEach(cleanup)

async function openSettings() {
  const user = userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  await user.click(screen.getByRole('button', {name: /^settings/i}))
  await screen.findByRole('tablist', {name: 'Settings sections'})
  return user
}

describe('Settings sections', () => {
  it('shows one section at a time and moves between them with the arrow keys', async () => {
    const user = await openSettings()
    const tabs = within(screen.getByRole('tablist', {name: 'Settings sections'})).getAllByRole('tab')
    expect(tabs.map(t => t.textContent)).toEqual(['General', 'Model', 'Roblox & Studio', 'Images, voice & 3D', 'Knowledge & search', 'Permissions', 'Updates'])
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tabpanel', {name: 'General'})).toBeTruthy()
    expect(screen.queryByRole('checkbox', {name: 'Allow workspace writes'})).toBeNull()

    tabs[0].focus()
    await user.keyboard('{ArrowDown}')
    expect(document.activeElement).toBe(tabs[1])
    expect(tabs[1].getAttribute('aria-selected')).toBe('true')
    expect(screen.getByRole('tabpanel', {name: 'Model'})).toBeTruthy()
    await user.keyboard('{End}')
    expect(screen.getByRole('tabpanel', {name: 'Updates'})).toBeTruthy()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('tabpanel', {name: 'General'})).toBeTruthy()

    await user.click(screen.getByRole('tab', {name: 'Permissions'}))
    expect(screen.getByRole('checkbox', {name: 'Allow workspace writes'})).toBeTruthy()
    // Only the chosen tab is in the Tab order.
    expect(tabs.filter(t => t.tabIndex === 0).map(t => t.textContent)).toEqual(['Permissions'])
  })

  it('remembers the last section on this device', async () => {
    const user = await openSettings()
    await user.click(screen.getByRole('tab', {name: 'Updates'}))
    cleanup()
    await openSettings()
    expect(screen.getByRole('tab', {name: 'Updates'}).getAttribute('aria-selected')).toBe('true')
  })
})

describe('Settings search', () => {
  it('finds a setting in any section by its words or a synonym, and says when nothing matches', async () => {
    const user = await openSettings()
    const search = screen.getByRole('searchbox', {name: 'Search settings'})
    await user.type(search, 'workspace writes')
    expect(screen.getByRole('checkbox', {name: 'Allow workspace writes'})).toBeTruthy()
    expect(screen.queryByRole('checkbox', {name: 'Show Star'})).toBeNull()
    expect(screen.queryByRole('tabpanel')).toBeNull()

    await user.clear(search)
    await user.type(search, 'animation')
    expect(screen.getByRole('checkbox', {name: 'Reduced motion'})).toBeTruthy()

    await user.clear(search)
    await user.type(search, 'zzqx')
    expect(screen.getByText(/No settings match/)).toBeTruthy()
    await user.keyboard('{Escape}')
    expect((search as HTMLInputElement).value).toBe('')
    expect(screen.getByRole('tabpanel', {name: 'General'})).toBeTruthy()
  })

  it('clicking a section while searching clears the search and opens it', async () => {
    const user = await openSettings()
    await user.type(screen.getByRole('searchbox', {name: 'Search settings'}), 'key')
    await user.click(screen.getByRole('tab', {name: 'Roblox & Studio'}))
    expect((screen.getByRole('searchbox', {name: 'Search settings'}) as HTMLInputElement).value).toBe('')
    expect(screen.getByRole('tabpanel', {name: 'Roblox & Studio'})).toBeTruthy()
  })
})

describe('Unsaved changes', () => {
  it('says when the form differs from what is saved, and Discard puts it back', async () => {
    const user = await openSettings()
    expect(screen.queryByText('Unsaved changes')).toBeNull()
    await user.click(screen.getByRole('checkbox', {name: 'Instant answers on this PC'}))
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    await user.click(screen.getByRole('button', {name: 'Discard'}))
    expect(screen.queryByText('Unsaved changes')).toBeNull()
    expect((screen.getByRole('checkbox', {name: 'Instant answers on this PC'}) as HTMLInputElement).checked).toBe(false)
  })

  it('saves the live Roblox docs and automatic web search switches', async () => {
    const user = await openSettings()
    await user.click(screen.getByRole('checkbox', {name: 'Search the web when a question needs it'}))
    await user.click(screen.getByRole('tab', {name: 'Roblox & Studio'}))
    const docs = screen.getByRole('checkbox', {name: 'Read the live Roblox documentation'}) as HTMLInputElement
    expect(docs.checked).toBe(false)
    await user.click(docs)
    await user.click(screen.getByRole('button', {name: 'Save settings'}))
    await waitFor(() => expect(desktop.sent('saveSettings').length).toBeGreaterThan(0))
    const saved = desktop.sent('saveSettings').at(-1)!.payload.settings as Record<string, unknown>
    expect(saved.roblox_docs_live_enabled).toBe(true)
    expect(saved.web_auto_search).toBe(false)
  })
})

describe('Web search keys', () => {
  it('stores a Brave key through the OS vault action and never keeps it in the page', async () => {
    desktop.onAction('saveProviderKey', () => ({ok: true, data: {connected: true}}))
    const user = await openSettings()
    await user.click(screen.getByRole('tab', {name: 'Knowledge & search'}))
    const field = screen.getByLabelText('Brave Search key') as HTMLInputElement
    expect(field.type).toBe('password')
    expect(screen.getAllByText('No key stored').length).toBe(2)
    await user.type(field, 'test-brave-key-123')
    await user.click(within(field.closest('div')!.parentElement!).getByRole('button', {name: /save/i}))
    await waitFor(() => expect(desktop.sent('saveProviderKey').length).toBe(1))
    expect(desktop.sent('saveProviderKey')[0].payload.provider).toBe('brave')
    expect(field.value).toBe('')
    expect(await screen.findByText('Brave Search key saved in Windows Credential Manager.')).toBeTruthy()
    expect(screen.getByRole('button', {name: 'Forget Brave Search key'})).toHaveProperty('disabled', false)
  })
})

describe('Scholarly research switch', () => {
  it('is off by default and saves scholarly_research_enabled when turned on', async () => {
    const user = await openSettings()
    await user.click(screen.getByRole('tab', {name: 'Knowledge & search'}))
    const box = screen.getByRole('checkbox', {name: 'Add scholarly papers to deep research'}) as HTMLInputElement
    expect(box.checked).toBe(false)
    await user.click(box)
    await user.click(screen.getByRole('button', {name: 'Save settings'}))
    await waitFor(() => expect(desktop.sent('saveSettings').length).toBeGreaterThan(0))
    expect((desktop.sent('saveSettings').at(-1)!.payload.settings as Record<string, unknown>).scholarly_research_enabled).toBe(true)
  })
})

describe('helpers', () => {
  it('matches every word, ignoring case, accents and hyphens', () => {
    expect(normalizeSearch('Résumé  Wi-Fi')).toBe('resume wi fi')
    expect(matchesSearch('Allow workspace writes', 'WRITES work')).toBe(true)
    expect(matchesSearch('Allow workspace writes', 'studio')).toBe(false)
    expect(matchesSearch('anything', '   ')).toBe(true)
  })
  it('does not count reduced motion (saved at once) as an unsaved change', () => {
    const base = backendSettings as unknown as AppSettings
    expect(settingsDirty({...base, reduced_motion: !base.reduced_motion}, base)).toBe(false)
    expect(settingsDirty({...base, max_calls: 3}, base)).toBe(true)
    expect(settingsDirty({...base, instant_route_enabled: null}, {...base, instant_route_enabled: undefined})).toBe(false)
  })
})
