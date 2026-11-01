// @vitest-environment jsdom
/**
 * Metallic in the real desktop shell (issue #552): the sidebar entry exists only while signed in, sign-out hides it
 * at once, and the first-launch sign-in appears only where a Metallic Control address is configured.
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => {
  desktop.reset()
  try { window.localStorage.clear() } catch { /* storage unavailable */ }
  desktop.onAction('metallicState', () => ({ok: true, pending: true}))
})
afterEach(cleanup)

const status = (signed: boolean, configured = true) => ({signed_in: signed, expires_at: signed ? Math.round(Date.now() / 1000) + 3600 : null,
  configured, control_url: configured ? 'http://metallic-control.local:8470' : '', locked_until: null, secure_store: true})
const nav = () => screen.getByRole('navigation', {name: 'Workspace'})

describe('Metallic in the desktop shell', () => {
  it('shows no Metallic entry and no sign-in screen when Metallic is not configured', async () => {
    desktop.host({metallic: status(false, false)})
    render(<App/>)
    await screen.findByRole('textbox', {name: /message star/i})
    expect(within(nav()).queryByRole('button', {name: 'Metallic'})).toBeNull()
    expect(screen.queryByRole('dialog', {name: 'Welcome to STAR'})).toBeNull()
  })

  it('offers the optional sign-in once on first launch, and Continue keeps normal STAR', async () => {
    desktop.host({metallic: status(false)})
    const user = userEvent.setup()
    render(<App/>)
    const dialog = await screen.findByRole('dialog', {name: 'Welcome to STAR'})
    await user.click(within(dialog).getByRole('button', {name: 'Continue'}))
    expect(screen.queryByRole('dialog', {name: 'Welcome to STAR'})).toBeNull()
    expect(within(nav()).queryByRole('button', {name: 'Metallic'})).toBeNull()
    cleanup()
    render(<App/>)
    await screen.findByRole('textbox', {name: /message star/i})
    expect(screen.queryByRole('dialog', {name: 'Welcome to STAR'})).toBeNull()
  })

  it('shows the Metallic entry while signed in and hides it on sign-out', async () => {
    desktop.host({metallic: status(true)})
    desktop.onAction('metallicSignOut', () => ({ok: true, data: status(false)}))
    const user = userEvent.setup()
    render(<App/>)
    await screen.findByRole('textbox', {name: /message star/i})
    await user.click(await within(nav()).findByRole('button', {name: 'Metallic'}))
    await waitFor(() => expect(desktop.sent('metallicState').length).toBeGreaterThan(0))
    await user.click(screen.getByRole('button', {name: /^settings/i}))
    await user.click(await screen.findByRole('tab', {name: 'Account & Metallic'}))
    await user.click(screen.getByRole('button', {name: /Sign out of Metallic/}))
    await waitFor(() => expect(desktop.sent('metallicSignOut').length).toBe(1))
    expect(within(nav()).queryByRole('button', {name: 'Metallic'})).toBeNull()
  })
})
