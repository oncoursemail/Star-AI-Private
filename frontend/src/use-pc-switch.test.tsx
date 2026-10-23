// @vitest-environment jsdom
/**
 * The composer-bar "Use my PC" switch, through the real app root against a fake Qt bridge.
 *
 * Contract: shown only with STAR Server as the provider; role=switch, keyboard operable; it uses the same host
 * calls as Settings > Use my GPU (`gpuHelperSet` saves at once); a refusal leaves it as it was; it can be flipped
 * while an answer is running (the host finishes that answer, nothing in the UI is disabled by it).
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {backendSettings, installFakeDesktop, type FakeDesktop} from './fake-desktop'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => desktop.reset())
afterEach(cleanup)

const status = (enabled: boolean) => ({state: enabled ? 'ready' : 'off', label: enabled ? 'Ready' : 'Off', text: enabled ? 'Ready: on your graphics card.' : 'Off. Every answer comes from STAR Server.', tokens_per_second: null, enabled})

async function open(provider = 'star_server') {
  desktop.host({settings: {...backendSettings, provider}})
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
}

describe('composer "Use my PC" switch', () => {
  it('is a labelled switch beside the model chip, off until the host says on, and saves at once', async () => {
    let current = status(false)
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: current}))
    desktop.onAction('gpuHelperSet', call => { current = status(call.payload.enabled === true); return {ok: true, data: current} })
    await open()
    const user = userEvent.setup()
    const toggle = await screen.findByRole('switch', {name: 'Use my PC'})
    await waitFor(() => expect(toggle.getAttribute('title')).toContain('Every answer comes from STAR Server'))
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    toggle.focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('true'))
    expect(desktop.sent('gpuHelperSet').map(call => call.payload)).toEqual([{enabled: true}])
    expect(toggle.getAttribute('title')).toContain('Ready')
    await user.keyboard(' ')
    await waitFor(() => expect(toggle.getAttribute('aria-checked')).toBe('false'))
    expect(desktop.sent('gpuHelperSet').map(call => call.payload)).toEqual([{enabled: true}, {enabled: false}])
  })

  it('a refused change leaves it as it was', async () => {
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: status(false)}))
    desktop.onAction('gpuHelperSet', () => ({ok: false, error: 'Settings could not be saved'}))
    await open()
    const user = userEvent.setup()
    const toggle = await screen.findByRole('switch', {name: 'Use my PC'})
    await user.click(toggle)
    await waitFor(() => expect(toggle.getAttribute('title')).toContain('nothing changed'))
    expect(toggle.getAttribute('aria-checked')).toBe('false')
  })

  it('is not offered for other providers', async () => {
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: status(false)}))
    await open('local')
    expect(screen.queryByRole('switch', {name: 'Use my PC'})).toBeNull()
  })
})
