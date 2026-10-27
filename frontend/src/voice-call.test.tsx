// @vitest-environment jsdom
/**
 * Voice calls (push to talk first) and read-aloud, through the real app root against a fake Qt bridge.
 *
 * Contract under test (star/voice/bridge.py): `voiceStartCall` is only sent after the owner pressed Start on the
 * consent step and always carries `micConsent: true`; holding the talk button sends `voicePushToTalk` down, then
 * up; Hang up sends `voiceStopCall`; a reply's Read aloud sends `voiceSpeak` with the reply text, a second press
 * `voiceStopSpeaking`; automatic read-aloud speaks a just-finished answer once and never history.
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'
import {applyCallEvent} from './VoiceCall'
import {resetReadAloud} from './ReadAloud'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => { desktop.reset(); resetReadAloud() })
afterEach(cleanup)

const ready = {available: true, missingPackages: [], missingModels: [], serverConfigured: true, inCall: false}
function voiceHost(settings: Record<string, unknown> = {}) {
  desktop.onAction('voiceStatus', () => ({ok: true, data: ready}))
  desktop.onAction('voiceGetSettings', () => ({ok: true, data: {settings: {call_mode: 'push-to-talk', read_aloud_auto: false, ...settings}}}))
  desktop.onAction('voiceStartCall', call => ({ok: true, data: {callId: call.requestId, settings: {call_mode: 'push-to-talk'}}}))
  desktop.onAction('voiceSpeak', () => ({ok: true, data: {speaking: true}}))
}
async function openApp() {
  const user = userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  return user
}

describe('applyCallEvent', () => {
  it('builds the transcript from host events and marks what an interruption cut short', () => {
    let lines = applyCallEvent([], {type: 'final_transcript', text: 'I had a bad day'})
    lines = applyCallEvent(lines, {type: 'assistant_sentence', text: 'Oh, love.'})
    lines = applyCallEvent(lines, {type: 'assistant_sentence', text: 'Come and tell me.'})
    expect(lines).toEqual([{who: 'you', text: 'I had a bad day'}, {who: 'star', text: 'Oh, love. Come and tell me.'}])
    lines = applyCallEvent(lines, {type: 'interrupted', heard_text: 'Oh, love. Come…'})
    expect(lines[1]).toEqual({who: 'star', text: 'Oh, love. Come…', interrupted: true})
    expect(applyCallEvent(lines, {type: 'level', mic: 0.4})).toBe(lines)
  })
})

describe('Voice call', () => {
  it('asks for microphone consent first, then runs a push-to-talk call and hangs up', async () => {
    voiceHost()
    const user = await openApp()
    await user.click(screen.getByRole('button', {name: /start a voice call with star/i}))
    const dialog = await screen.findByRole('dialog', {name: /talk with star/i})
    expect(dialog.textContent).toMatch(/use your microphone only while this call is open/i)
    expect(within(dialog).getByRole('radio', {name: /push to talk/i})).toHaveProperty('checked', true)
    expect(desktop.sent('voiceStartCall')).toHaveLength(0)            // nothing listens before Start
    await waitFor(() => expect((within(dialog).getByRole('button', {name: 'Start call'}) as HTMLButtonElement).disabled).toBe(false))
    await user.click(within(dialog).getByRole('button', {name: 'Start call'}))
    await waitFor(() => expect(desktop.sent('voiceStartCall')).toHaveLength(1))
    const start = desktop.sent('voiceStartCall')[0]
    expect(start.payload).toEqual({micConsent: true, settings: {call_mode: 'push-to-talk'}})
    const id = start.requestId
    desktop.emitRaw(id, 'voice', {type: 'state', state: 'listening'})
    const live = await screen.findByRole('dialog', {name: /on a call with star/i})
    expect(within(live).getByRole('status').textContent).toMatch(/Listening/)

    const talk = screen.getByRole('button', {name: /hold to talk/i})
    fireEvent.pointerDown(talk, {pointerId: 1})
    await waitFor(() => expect(desktop.sent('voicePushToTalk').map(c => c.payload.down)).toEqual([true]))
    expect(screen.getByRole('button', {name: /let go when you are done/i})).toBeTruthy()
    fireEvent.pointerUp(talk, {pointerId: 1})
    await waitFor(() => expect(desktop.sent('voicePushToTalk').map(c => c.payload.down)).toEqual([true, false]))

    desktop.emitRaw(id, 'voice', {type: 'final_transcript', text: 'I had a really bad day'})
    desktop.emitRaw(id, 'voice', {type: 'state', state: 'speaking'})
    desktop.emitRaw(id, 'voice', {type: 'assistant_sentence', text: 'Oh, sweetheart.'})
    desktop.emitRaw(id, 'voice', {type: 'turn_metrics', stages: {total: 1.84, asr: 0.21, transcript_to_first_token: 0.9, first_token_to_first_audio: 0.4}})
    const transcript = screen.getByRole('list', {name: /call transcript/i})
    expect(transcript.textContent).toContain('I had a really bad day')
    expect(transcript.textContent).toContain('Oh, sweetheart.')
    expect(screen.getByText(/first sound 1\.84 s after you stopped talking/)).toBeTruthy()

    await user.click(screen.getByRole('button', {name: /stop talking/i}))
    expect(desktop.sent('voiceInterrupt')).toHaveLength(1)
    await user.click(screen.getByRole('button', {name: /hang up/i}))
    expect(desktop.sent('voiceStopCall').length).toBeGreaterThan(0)
  })

  it('says what is missing and cannot start when the voice engine is not installed', async () => {
    voiceHost()
    desktop.onAction('voiceStatus', () => ({ok: true, data: {...ready, available: false, missingPackages: ['faster-whisper']}}))
    const user = await openApp()
    await user.click(screen.getByRole('button', {name: /start a voice call with star/i}))
    const dialog = await screen.findByRole('dialog', {name: /talk with star/i})
    expect((await within(dialog).findByRole('alert')).textContent).toMatch(/faster-whisper/)
    expect((within(dialog).getByRole('button', {name: 'Start call'}) as HTMLButtonElement).disabled).toBe(true)
    await user.click(within(dialog).getByRole('button', {name: 'Not now'}))
    expect(desktop.sent('voiceStartCall')).toHaveLength(0)
  })
})

async function answer(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.type(screen.getByRole('textbox', {name: /message star/i}), 'hello')
  await user.keyboard('{Enter}')
  const id = await waitFor(() => desktop.requestOf('sendMessage'))
  desktop.delta(id, text.slice(0, 5))
  await screen.findByText(/Writing/)
  desktop.complete(id, text)
}

describe('Read aloud', () => {
  it('reads a reply in Star\'s voice on request and stops on a second press', async () => {
    voiceHost()
    const user = await openApp()
    await answer(user, 'Well done, love. Your shop works now.')
    const button = await screen.findByRole('button', {name: /read aloud/i})
    expect(desktop.sent('voiceSpeak')).toHaveLength(0)                // off by default: nothing is read on its own
    await user.click(button)
    await waitFor(() => expect(desktop.sent('voiceSpeak')).toHaveLength(1))
    const speak = desktop.sent('voiceSpeak')[0]
    expect(speak.payload).toEqual({text: 'Well done, love. Your shop works now.'})
    desktop.emitRaw(speak.requestId, 'voice', {type: 'speak_started', first_audio_seconds: 0.3})
    await user.click(await screen.findByRole('button', {name: /^stop$/i}))
    await waitFor(() => expect(desktop.sent('voiceStopSpeaking')).toHaveLength(1))
    expect(await screen.findByRole('button', {name: /read aloud/i})).toBeTruthy()
  })

  it('with automatic read-aloud on, speaks a just-finished answer once and never the history', async () => {
    voiceHost({read_aloud_auto: true})
    desktop.reset([{id: '', role: 'user', text: 'old question', created: ''}, {id: '', role: 'assistant', text: 'An old answer.', created: ''}])
    voiceHost({read_aloud_auto: true})
    const user = await openApp()
    await screen.findByText('An old answer.')
    await waitFor(() => expect(desktop.sent('voiceGetSettings').length).toBeGreaterThan(0))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)) })
    expect(desktop.sent('voiceSpeak')).toHaveLength(0)                // history is never read out
    await answer(user, 'Oh, sweetheart. That is a lovely idea.')
    await waitFor(() => expect(desktop.sent('voiceSpeak')).toHaveLength(1))
    expect(desktop.sent('voiceSpeak')[0].payload).toEqual({text: 'Oh, sweetheart. That is a lovely idea.'})
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 100)) })
    expect(desktop.sent('voiceSpeak')).toHaveLength(1)                // once, even after the chat reloads
  })
})

describe('Settings > read-aloud and call mode', () => {
  it('saves the two voice habits through the voice settings and reports only what the host confirmed', async () => {
    voiceHost()
    let stored: Record<string, unknown> = {call_mode: 'push-to-talk', read_aloud_auto: false}
    desktop.onAction('voiceSaveSettings', call => {
      stored = {...stored, ...(call.payload.settings as Record<string, unknown>)}
      return {ok: true, data: {settings: stored}}
    })
    const user = await openApp()
    await user.click(screen.getByRole('button', {name: /^settings/i}))
    await user.click(await screen.findByRole('tab', {name: 'Voice'}))   // one section at a time (#342)
    const group = await screen.findByRole('group', {name: /read-aloud and calls/i})
    const auto = within(group).getByRole('checkbox', {name: /read new replies aloud/i}) as HTMLInputElement
    expect(auto.checked).toBe(false)
    await user.click(auto)
    await waitFor(() => expect(desktop.sent('voiceSaveSettings').at(-1)?.payload).toEqual({settings: {read_aloud_auto: true}}))
    await waitFor(() => expect(auto.checked).toBe(true))
    await user.selectOptions(within(group).getByRole('combobox', {name: /voice calls listen/i}), 'hands-free')
    await waitFor(() => expect(desktop.sent('voiceSaveSettings').at(-1)?.payload).toEqual({settings: {call_mode: 'hands-free'}}))
    desktop.onAction('voiceSaveSettings', () => ({ok: false, error: 'ValueError: Call mode must be push-to-talk or hands-free'}))
    await user.click(auto)
    expect((await within(group).findByRole('status')).textContent).toMatch(/Call mode must be/)
    expect(auto.checked).toBe(true)                                     // unchanged: the host refused
  })
})
