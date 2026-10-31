// @vitest-environment jsdom
/**
 * Settings > Discord, through the real app root against a fake Qt bridge.
 *
 * Contract under test: the page asks `discordStatus`, sends `discordStart` / `discordStop` /
 * `discordSetAutostart` (only), shows the host's state in words, never shows a secret (the host does not
 * send one), and reports nothing as done before the host confirmed it.
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => desktop.reset())
afterEach(cleanup)

const base = {
  state: 'stopped', message: 'The bot is not running.', problem: '', missing: [], running: false, connected: false,
  external: false, wantsRunning: false, restarts: 0, crashes: 0, lastExitCode: null, retryInSeconds: null,
  logFile: 'discord-bot.log', autostart: false,
}

/** A host that keeps the state the page sets, like the real supervisor. */
function discordHost(first: Record<string, unknown> = {}) {
  let current: Record<string, unknown> = {...base, ...first}
  desktop.onAction('discordStatus', () => ({ok: true, data: current}))
  desktop.onAction('discordStart', () => {
    current = {...current, state: 'starting', running: true, wantsRunning: true, message: 'Starting. Connecting to Discord takes a few seconds.'}
    return {ok: true, data: current}
  })
  desktop.onAction('discordStop', () => {
    current = {...current, ...base, autostart: current.autostart}
    return {ok: true, data: current}
  })
  desktop.onAction('discordSetAutostart', call => {
    current = {...current, autostart: call.payload.enabled === true}
    return {ok: true, data: current}
  })
}
async function openSettings() {
  const user = userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  await user.click(screen.getByRole('button', {name: /^settings/i}))
  return user
}
/** Settings shows one section at a time (#342); Discord sits under Advanced. */
const section = async () => {
  const tab = await screen.findByRole('tab', {name: 'Advanced'})
  if (tab.getAttribute('aria-selected') !== 'true') await userEvent.setup().click(tab)
  return screen.findByRole('region', {name: 'Discord'})
}
const statusLine = (box: HTMLElement) => within(box).getByText(/^Status:/)

describe('Settings > Discord', () => {
  it('shows a stopped bot, and Start asks the host and then shows what the host reports', async () => {
    discordHost()
    const user = await openSettings()
    const box = await section()
    await waitFor(() => expect(statusLine(box).textContent).toContain('Stopped'))
    expect(within(box).getByRole('button', {name: /stop the bot/i})).toHaveProperty('disabled', true)
    await user.click(within(box).getByRole('button', {name: /start the bot/i}))
    await waitFor(() => expect(desktop.sent('discordStart')).toHaveLength(1))
    await waitFor(() => expect(statusLine(box).textContent).toContain('Starting'))
    expect(within(box).getByRole('button', {name: /start the bot/i})).toHaveProperty('disabled', true)
    await user.click(within(box).getByRole('button', {name: /stop the bot/i}))
    await waitFor(() => expect(desktop.sent('discordStop')).toHaveLength(1))
    await waitFor(() => expect(statusLine(box).textContent).toContain('Stopped'))
  })

  it('says Connected only when the host says so', async () => {
    discordHost({state: 'connected', connected: true, running: true, wantsRunning: true, message: 'STAR is connected to Discord.'})
    await openSettings()
    const box = await section()
    await waitFor(() => expect(statusLine(box).textContent).toContain('Connected'))
    expect(within(box).getByText('STAR is connected to Discord.')).toBeTruthy()
  })

  it('explains what is missing when the bot is not configured, without any value', async () => {
    discordHost({state: 'not_configured', missing: ['the bot token (discord.env)', 'your Discord user ID (discord-settings.env)'], message: 'Not set up yet.'})
    await openSettings()
    const box = await section()
    await waitFor(() => expect(statusLine(box).textContent).toContain('Not configured'))
    expect(box.textContent).toContain('the bot token (discord.env)')
    expect(box.textContent).toContain('your Discord user ID (discord-settings.env)')
    expect(box.textContent).toContain('docs/STAR_DISCORD_SETUP.md')
  })

  it('shows a crash that is being retried', async () => {
    discordHost({state: 'backoff', wantsRunning: true, restarts: 2, retryInSeconds: 20, message: 'The bot stopped unexpectedly. STAR will start it again shortly.'})
    await openSettings()
    const box = await section()
    await waitFor(() => expect(box.textContent).toContain('next try in 20 s'))
    expect(box.textContent).toContain('restarted 2 times')
  })

  it('shows an error with its reason', async () => {
    discordHost({state: 'error', problem: 'The bot settings are wrong. Run the doctor check to see what to fix, then press Start.'})
    await openSettings()
    const box = await section()
    expect((await within(box).findByRole('alert')).textContent).toContain('settings are wrong')
  })

  it('shows a bot that runs in another window and cannot be stopped from here', async () => {
    discordHost({state: 'external', external: true, running: true, message: 'The bot is running in another window (a terminal or Task Scheduler). Stop it there; STAR will not start a second one.'})
    await openSettings()
    const box = await section()
    await waitFor(() => expect(statusLine(box).textContent).toContain('another window'))
    expect(within(box).getByRole('button', {name: /stop the bot/i})).toHaveProperty('disabled', true)
  })

  it('the opt-in is off by default and the switch sends exactly discordSetAutostart', async () => {
    discordHost()
    const user = await openSettings()
    const box = await section()
    const toggle = await within(box).findByRole('checkbox', {name: /start the discord bot with star/i}) as HTMLInputElement
    expect(toggle.checked).toBe(false)
    await user.click(toggle)
    await waitFor(() => expect(desktop.sent('discordSetAutostart')).toHaveLength(1))
    expect(desktop.sent('discordSetAutostart')[0].payload).toEqual({enabled: true})
    await waitFor(() => expect((within(box).getByRole('checkbox', {name: /start the discord bot with star/i}) as HTMLInputElement).checked).toBe(true))
    expect(desktop.sent('saveSettings')).toHaveLength(0)
  })

  it('reports a refusal from the host and changes nothing on the page', async () => {
    discordHost()
    desktop.onAction('discordStart', () => ({ok: false, error: 'RuntimeError: Could not start'}))
    const user = await openSettings()
    const box = await section()
    await user.click(await within(box).findByRole('button', {name: /start the bot/i}))
    expect((await within(box).findAllByRole('alert'))[0].textContent).toContain('Could not start')
    expect(statusLine(box).textContent).toContain('Stopped')
  })

  it('shows a plain message when the host cannot read the status', async () => {
    desktop.onAction('discordStatus', () => ({ok: false, error: 'OSError: unreadable'}))
    await openSettings()
    const box = await section()
    expect((await within(box).findByRole('alert')).textContent).toContain('could not be shown')
  })
})
