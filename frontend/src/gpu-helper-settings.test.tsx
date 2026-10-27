// @vitest-environment jsdom
/**
 * Settings > Model > Use my GPU, through the real app root against a fake Qt bridge.
 *
 * Contract: the switch is sent to the host at once (`gpuHelperSet`, only), the status line shows what the host
 * reports (`gpuHelperStatus`), nothing is shown as on before the host confirmed it, and turning it on does not
 * make the page look unsaved.
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

const off = {state: 'off', label: 'Off', text: 'Off. Every answer comes from STAR Server.', tokens_per_second: null, enabled: false}
const starting = {state: 'starting', label: 'Starting', text: "Starting: loading STAR's code model on your graphics card. The server answers meanwhile.", tokens_per_second: null, enabled: true}
const ready = {state: 'ready', label: 'Ready', text: "Ready: STAR's code model runs on your graphics card. Last answer: 31.4 tokens per second.", tokens_per_second: 31.4, enabled: true}

async function openPanel() {
  const user = userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  await user.click(screen.getByRole('button', {name: /^settings/i}))
  const tab = await screen.findByRole('tab', {name: 'Models & speed'})
  if (tab.getAttribute('aria-selected') !== 'true') await user.click(tab)
  return {user, box: await screen.findByRole('region', {name: 'Use my GPU'})}
}

describe('Settings > Use my GPU', () => {
  it('is off by default and shows the host status', async () => {
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: off}))
    const {box} = await openPanel()
    const toggle = within(box).getByRole('checkbox', {name: 'Use my GPU'}) as HTMLInputElement
    await waitFor(() => expect(within(box).getByRole('status').textContent).toContain('Every answer comes from STAR Server'))
    expect(toggle.checked).toBe(false)
    expect(within(box).queryByText(/llama-server\.exe/)).toBeNull()
  })

  it('turning it on asks the host, then shows starting and later ready with the speed', async () => {
    let current: Record<string, unknown> = off
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: current}))
    desktop.onAction('gpuHelperSet', call => { current = call.payload.enabled === true ? starting : off; return {ok: true, data: current} })
    const {user, box} = await openPanel()
    await waitFor(() => expect(desktop.sent('gpuHelperStatus').length).toBeGreaterThan(0))
    await user.click(within(box).getByRole('checkbox', {name: 'Use my GPU'}))
    await waitFor(() => expect(within(box).getByRole('status').textContent).toContain('Starting'))
    expect(desktop.sent('gpuHelperSet').map(call => call.payload)).toEqual([{enabled: true}])
    expect((within(box).getByRole('checkbox', {name: 'Use my GPU'}) as HTMLInputElement).checked).toBe(true)
    expect(within(box).getByText(/llama-server\.exe/)).toBeTruthy()
    // The switch saves itself: the page must not ask to save.
    expect(screen.queryByText('Unsaved changes')).toBeNull()
    expect(screen.getByText('All changes saved')).toBeTruthy()
    current = ready
    await waitFor(() => expect(within(box).getByRole('status').textContent).toContain('31.4 tokens per second'), {timeout: 5000})
    await user.click(within(box).getByRole('checkbox', {name: 'Use my GPU'}))
    await waitFor(() => expect(within(box).getByRole('status').textContent).toContain('Off'))
    expect(desktop.sent('gpuHelperSet').map(call => call.payload)).toEqual([{enabled: true}, {enabled: false}])
  })

  it('"Automatically turn on at night" is on by default and saves with the page', async () => {
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: off}))
    const {user, box} = await openPanel()
    const auto = within(box).getByRole('checkbox', {name: 'Automatically turn on at night'}) as HTMLInputElement
    expect(auto.checked).toBe(true)
    await user.click(auto)
    expect(auto.checked).toBe(false)
    expect(screen.getByText('Unsaved changes')).toBeTruthy()
    expect(desktop.sent('gpuHelperSet')).toHaveLength(0)
  })

  it('a refused switch stays off and says why', async () => {
    desktop.onAction('gpuHelperStatus', () => ({ok: true, data: off}))
    desktop.onAction('gpuHelperSet', () => ({ok: false, error: 'Settings could not be saved'}))
    const {user, box} = await openPanel()
    await user.click(within(box).getByRole('checkbox', {name: 'Use my GPU'}))
    expect((await within(box).findByRole('alert')).textContent).toBeTruthy()
    expect((within(box).getByRole('checkbox', {name: 'Use my GPU'}) as HTMLInputElement).checked).toBe(false)
  })
})
