// @vitest-environment jsdom
/**
 * Settings: the voice picker and the Roblox Studio choice, through the real app root against a fake
 * Qt bridge.
 *
 * Contract under test: what the page sends to the desktop host (`voiceListVoices`, `voiceStatus`,
 * `voicePreviewVoice`, `voiceSelectVoice`, `saveSettings`, `studioHostStatus`, `discoverStudio`; never
 * `studioHostSave` or `studioHostClear`, which are not part of v0.9.0), the events it accepts back, and
 * the text the owner reads.
 * Nothing here depends on class names or markup, so the sections can be restyled freely.
 */
import {afterEach, beforeAll, beforeEach, describe, expect, it} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {App} from './App'
import {backendSettings, installFakeDesktop, type FakeDesktop, type Reply} from './fake-desktop'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await import('./Desktop') }, 60_000)
beforeEach(() => desktop.reset())
afterEach(cleanup)

const NOT_IN_CALLS = 'The qwen3-tts engine is not built into calls yet. You can hear this voice on the audition page.'
const styles = [
  {id: 'warm-caring', name: 'Warm and caring', summary: 'Gentle, motherly and patient. The default.', preview_line: 'Hi sweetheart, it\'s Star.'},
  {id: 'confident-commanding', name: 'Confident and commanding', summary: 'A mature woman who sounds completely in control.', preview_line: 'Sit down. Breathe. Now show me what you built.'},
  {id: 'anime-bright', name: 'Anime-style', summary: 'A bright adult English-dub style.', preview_line: 'Okay, okay, next step, let\'s go!'},
]
const voice = (id: string, name: string, style: string, over: Record<string, unknown> = {}) => ({
  id, name, label: name, style, archetype: 'warm', engine: 'kokoro', licence: 'Apache-2.0', notes: '', recommended_for: [],
  callable: true, reason: '', latency: {first_audio_seconds: 0.41, first_audio_kind: 'first sentence', device: 'PC GPU'}, ...over})
const voices = [
  voice('heart', 'Heart', 'warm-caring', {notes: 'The default voice. Warm and light.'}),
  voice('whisper-soft', 'Soft whisper', 'warm-caring'),
  voice('warm-designed', 'Designed warm', 'warm-caring', {engine: 'qwen3-tts', callable: false, reason: NOT_IN_CALLS}),
  voice('cmd-nicole-aoede', 'Nicole and Aoede', 'confident-commanding', {recommended_for: ['live']}),
  voice('ani-bella-heart-up', 'Bella bright', 'anime-bright', {recommended_for: ['live']}),
  voice('ani-genki-wide-locked', 'Genki wide', 'anime-bright', {engine: 'qwen3-tts', callable: false, reason: NOT_IN_CALLS, recommended_for: ['quality']}),
]
const engineReady = {available: true, missingPackages: [], missingModels: [], serverConfigured: true, inCall: false, callId: null, state: 'idle', muted: false}

/** Answer the voice actions the way star/voice/bridge.py does. */
function voiceHost(over: {selected?: Record<string, unknown>; engine?: Record<string, unknown>; list?: Reply} = {}) {
  const selected = {voiceId: 'heart', voice: 'heart', style: 'warm-caring', speed: 0.92, ...over.selected}
  desktop.onAction('voiceListVoices', () => over.list ?? {ok: true, data: {styles, voices, selected}})
  desktop.onAction('voiceStatus', () => ({ok: true, data: {...engineReady, ...over.engine}}))
  desktop.onAction('voicePreviewVoice', call => ({ok: true, data: {previewing: 'recipe', voiceId: call.payload.voiceId}}))
  desktop.onAction('voiceSelectVoice', call => ({ok: true, data: {
    settings: {voice_id: call.payload.voiceId, voice: 'af_recipe:1.0', voice_style: voices.find(v => v.id === call.payload.voiceId)?.style, speed: 0.9},
    voice: {}, appliesToNextCall: false}}))
}
/** Answer the Studio actions; `saveSettings` reports the new target like the real host and the next bootstrap agrees. */
function studioHost(over: {target?: string; host?: Record<string, unknown>} = {}) {
  const stored = {configured: false, source: 'none', ...over.host}
  if (over.target) desktop.host({settings: {...backendSettings, studio_target: over.target}})
  desktop.onAction('saveSettings', call => {
    const next = {...backendSettings, ...(call.payload.settings as Record<string, unknown>)}
    desktop.host({settings: next})
    return {ok: true, data: next}
  })
  desktop.onAction('studioHostStatus', () => ({ok: true, data: stored}))
  desktop.onAction('discoverStudio', () => ({ok: true, pending: true}))
}
async function openSettings() {
  const user = userEvent.setup()
  render(<App/>)
  await screen.findByRole('textbox', {name: /message star/i})
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  await user.click(screen.getByRole('button', {name: /^settings/i}))
  return user
}
/** Settings shows one section at a time; open the one that holds the panel under test. */
async function showSection(name: string) {
  const tab = await screen.findByRole('tab', {name})
  if (tab.getAttribute('aria-selected') !== 'true') await userEvent.setup().click(tab)
}
const voiceSection = async () => { await showSection('Images, voice & 3D'); return screen.findByRole('region', {name: 'Star\'s voice'}) }
const studioSection = async () => { await showSection('Roblox & Studio'); return screen.findByRole('region', {name: 'Roblox Studio'}) }
const report = (target: string, over: Record<string, unknown> = {}) => ({
  target, label: '', state: 'connected', checked_at: '2026-10-11T14:30:00+00:00', tool_count: 30,
  instances: [{id: 'studio-1', name: 'STAR Test Place'}], selected_id: '', selected_valid: false, reason_code: '',
  diagnostic: null, local_mcp: 'memory', server_name: 'STAR local MCP', ...over})

describe('Settings > Voice', () => {
  it('lists the voices by style, marks the saved one and the default style', async () => {
    voiceHost()
    await openSettings()
    const section = await voiceSection()
    const warm = await within(section).findByRole('group', {name: 'Warm and caring'})
    expect(within(warm).getByText('Default')).toBeTruthy()
    expect(within(warm).getByText('Heart')).toBeTruthy()
    expect(within(warm).getByText('The default voice. Warm and light.')).toBeTruthy()
    expect(within(warm).getByText('Selected')).toBeTruthy()
    expect(within(warm).getByRole('button', {name: 'Use Heart'})).toHaveProperty('disabled', true)
    expect(within(warm).getByRole('button', {name: 'Use Soft whisper'})).toHaveProperty('disabled', false)
    const anime = within(section).getByRole('group', {name: 'Anime-style'})
    expect(within(anime).getByText('Bella bright')).toBeTruthy()
    expect(within(anime).getByText('Best for live calls')).toBeTruthy()
    expect(within(anime).getByText('Best quality')).toBeTruthy()
    expect(within(section).getByText(/Current voice:/).textContent).toContain('Heart')
    expect(desktop.sent('voiceListVoices')).toHaveLength(1)
  })

  it('marks Heart on a profile that never chose a voice, and says so when the saved voice is a custom recipe', async () => {
    // A new profile has the default recipe name and no catalog id yet (star/voice/settings.py).
    voiceHost({selected: {voiceId: '', voice: 'heart'}})
    await openSettings()
    let section = await voiceSection()
    const warm = await within(section).findByRole('group', {name: 'Warm and caring'})
    expect(within(warm).getByText('Selected')).toBeTruthy()
    expect(within(warm).getByRole('button', {name: 'Use Heart'})).toHaveProperty('disabled', true)
    expect(within(section).getByText(/Current voice:/).textContent).toContain('Heart · Warm and caring')
    cleanup()
    desktop.reset()
    voiceHost({selected: {voiceId: '', voice: 'af_heart:0.7+af_nicole:0.3'}})
    await openSettings()
    section = await voiceSection()
    await within(section).findByRole('group', {name: 'Warm and caring'})
    expect(within(section).getByText(/Current voice:/).textContent).toContain('af_heart:0.7+af_nicole:0.3 · a custom recipe that is not in this list')
    expect(within(section).queryByText('Selected')).toBeNull()
    expect(within(section).getByRole('button', {name: 'Use Heart'})).toHaveProperty('disabled', false)
  })

  it('offers the commanding style as an opt-in: its voices appear only after the owner switches them on', async () => {
    voiceHost()
    const user = await openSettings()
    const section = await voiceSection()
    const commanding = await within(section).findByRole('group', {name: 'Confident and commanding'})
    expect(within(commanding).getByText('Optional')).toBeTruthy()
    expect(within(commanding).queryByText('Default')).toBeNull()
    const offer = within(commanding).getByRole('checkbox', {name: /offer the confident and commanding voices/i})
    expect(offer).toHaveProperty('checked', false)
    expect(within(commanding).queryByText('Nicole and Aoede')).toBeNull()
    expect(within(commanding).queryAllByRole('button')).toHaveLength(0)
    await user.click(offer)
    expect(within(commanding).getByText('Nicole and Aoede')).toBeTruthy()
    expect(within(commanding).getByRole('button', {name: 'Preview Nicole and Aoede'})).toHaveProperty('disabled', false)
    // Looking at the group is not choosing it: nothing was saved.
    expect(desktop.sent('voiceSelectVoice')).toHaveLength(0)
    expect(within(section).getByText(/Current voice:/).textContent).toContain('Heart')
  })

  it('shows a commanding voice that is already the saved voice without asking again', async () => {
    voiceHost({selected: {voiceId: 'cmd-nicole-aoede', voice: 'af_nicole:0.6+af_aoede:0.4', style: 'confident-commanding'}})
    await openSettings()
    const commanding = await within(await voiceSection()).findByRole('group', {name: 'Confident and commanding'})
    await waitFor(() => expect(within(commanding).getByRole('checkbox')).toHaveProperty('checked', true))
    expect(within(commanding).getByText('Selected')).toBeTruthy()
  })

  it('labels a voice that cannot be used in live calls with the host\'s reason and sends nothing for it', async () => {
    voiceHost()
    const user = await openSettings()
    const warm = await within(await voiceSection()).findByRole('group', {name: 'Warm and caring'})
    // They are kept out of the way of the voices that can be chosen, under their own heading.
    const more = within(warm).getByText('1 more voice that is not usable in live calls yet')
    expect(more.closest('details')!.contains(within(warm).getByText('Designed warm'))).toBe(true)
    expect(more.closest('details')!.contains(within(warm).getByText('Heart'))).toBe(false)
    await user.click(more)
    expect(within(warm).getByText('Not usable in live calls yet')).toBeTruthy()
    expect(within(warm).getByText(NOT_IN_CALLS)).toBeTruthy()
    const preview = within(warm).getByRole('button', {name: 'Preview Designed warm'})
    const use = within(warm).getByRole('button', {name: 'Use Designed warm'})
    expect(preview).toHaveProperty('disabled', true)
    expect(use).toHaveProperty('disabled', true)
    await user.click(preview)
    await user.click(use)
    expect(desktop.sent('voicePreviewVoice')).toHaveLength(0)
    expect(desktop.sent('voiceSelectVoice')).toHaveLength(0)
    expect(within(warm).getByText(/3 voices, 2 usable in live calls today/)).toBeTruthy()
  })

  it('previews one voice at a time and shows it as playing until the host says the line finished', async () => {
    voiceHost()
    const user = await openSettings()
    const section = await voiceSection()
    await user.click(await within(section).findByRole('button', {name: 'Preview Soft whisper'}))
    await waitFor(() => expect(desktop.sent('voicePreviewVoice')).toHaveLength(1))
    expect(desktop.sent('voicePreviewVoice')[0].payload).toEqual({voiceId: 'whisper-soft'})
    const playing = within(section).getByRole('button', {name: 'Preview Soft whisper'})
    expect(playing.textContent).toContain('Playing')
    expect(within(section).getByRole('button', {name: 'Preview Heart'})).toHaveProperty('disabled', true)
    // A voice event that belongs to another request does not end this preview.
    await desktop.emitRaw('some-other-request', 'voice', {type: 'preview_done', voice: 'x'})
    expect(within(section).getByRole('button', {name: 'Preview Soft whisper'}).textContent).toContain('Playing')
    await desktop.emitRaw(desktop.requestOf('voicePreviewVoice'), 'voice', {type: 'preview_done', voice: 'af_recipe:1.0'})
    await waitFor(() => expect(within(section).getByRole('button', {name: 'Preview Soft whisper'}).textContent).not.toContain('Playing'))
    expect(within(section).getByRole('button', {name: 'Preview Heart'})).toHaveProperty('disabled', false)
    expect(within(section).queryByRole('alert')).toBeNull()
  })

  it('says on the row when the host refuses a preview, in the host\'s words without the error class', async () => {
    voiceHost()
    desktop.onAction('voicePreviewVoice', () => ({ok: false, error: 'RuntimeError: Stop the call before previewing a voice'}))
    const user = await openSettings()
    const section = await voiceSection()
    await user.click(await within(section).findByRole('button', {name: 'Preview Heart'}))
    const alert = await within(section).findByRole('alert')
    expect(alert.textContent).toContain('Stop the call before previewing a voice')
    expect(alert.textContent).not.toContain('RuntimeError')
    expect(within(section).getByRole('button', {name: 'Preview Heart'}).textContent).not.toContain('Playing')
  })

  it('says on the row when the voice engine fails after the preview started', async () => {
    voiceHost()
    const user = await openSettings()
    const section = await voiceSection()
    await user.click(await within(section).findByRole('button', {name: 'Preview Heart'}))
    await waitFor(() => expect(desktop.sent('voicePreviewVoice')).toHaveLength(1))
    await desktop.emitRaw(desktop.requestOf('voicePreviewVoice'), 'voice', {type: 'error', message: 'No audio output device was found'})
    const alert = await within(section).findByRole('alert')
    expect(alert.textContent).toContain('No audio output device was found')
    expect(within(section).getByRole('button', {name: 'Preview Heart'}).textContent).not.toContain('Playing')
  })

  it('says what is missing when the voice engine is not installed, plays nothing, and still lets a voice be chosen', async () => {
    voiceHost({engine: {available: false, missingPackages: ['kokoro-onnx', 'sounddevice'], missingModels: ['kokoro-v1.0.onnx']}})
    const user = await openSettings()
    const section = await voiceSection()
    const state = await within(section).findByText(/voice engine is not installed on this PC/i)
    expect(state.textContent).toContain('kokoro-onnx, sounddevice')
    expect(state.textContent).toContain('kokoro-v1.0.onnx')
    const preview = within(section).getByRole('button', {name: 'Preview Heart'})
    expect(preview).toHaveProperty('disabled', true)
    await user.click(preview)
    expect(desktop.sent('voicePreviewVoice')).toHaveLength(0)
    await user.click(within(section).getByRole('button', {name: 'Use Soft whisper'}))
    await waitFor(() => expect(desktop.sent('voiceSelectVoice')).toHaveLength(1))
  })

  it('stores the chosen voice and marks it only after the host confirmed it', async () => {
    voiceHost()
    const user = await openSettings()
    const section = await voiceSection()
    await user.click(await within(section).findByRole('button', {name: 'Use Bella bright'}))
    await waitFor(() => expect(desktop.sent('voiceSelectVoice')).toHaveLength(1))
    expect(desktop.sent('voiceSelectVoice')[0].payload).toEqual({voiceId: 'ani-bella-heart-up'})
    expect(await within(section).findByText(/Bella bright is now Star's voice\./)).toBeTruthy()
    expect(within(section).getByText(/Current voice:/).textContent).toContain('Bella bright')
    expect(within(section).getByText(/Current voice:/).textContent).toContain('Anime-style')
    expect(within(section).getByRole('button', {name: 'Use Bella bright'})).toHaveProperty('disabled', true)
    expect(within(section).getByRole('button', {name: 'Use Heart'})).toHaveProperty('disabled', false)
  })

  it('keeps the earlier voice when the host does not confirm the choice', async () => {
    voiceHost()
    desktop.onAction('voiceSelectVoice', () => ({ok: false, error: 'RuntimeError: Voice settings cannot be saved here'}))
    const user = await openSettings()
    const section = await voiceSection()
    await user.click(await within(section).findByRole('button', {name: 'Use Soft whisper'}))
    expect((await within(section).findByRole('alert')).textContent).toContain('Voice settings cannot be saved here')
    expect(within(section).getByText(/Current voice:/).textContent).toContain('Heart')
    expect(within(section).queryByText(/is now Star's voice/)).toBeNull()
  })

  it('says so when the voice list cannot be read instead of showing an empty picker', async () => {
    voiceHost({list: {ok: false, error: 'ValueError: The voice catalog is damaged'}})
    await openSettings()
    const section = await voiceSection()
    expect((await within(section).findByRole('alert')).textContent).toContain('The voice catalog is damaged')
    expect(within(section).queryAllByRole('button', {name: /^Preview/})).toHaveLength(0)
  })
})

describe('Settings > Roblox Studio', () => {
  it('offers this PC and the STAR Studio server, starts on this PC and states the sandbox rule', async () => {
    studioHost()
    await openSettings()
    const section = await studioSection()
    const choice = within(section).getByRole('radiogroup', {name: 'Studio STAR works in'})
    expect(within(choice).getByRole('radio', {name: /^This PC/})).toHaveProperty('checked', true)
    expect(within(choice).getByRole('radio', {name: /^STAR Studio server/})).toHaveProperty('checked', false)
    expect(section.textContent).toContain('STAR only builds in its own test place')
    expect(section.textContent).toContain('Every other place is read-only')
    // The server fields belong to the server choice only.
    expect(within(section).queryByLabelText('Server address')).toBeNull()
    expect(desktop.sent('saveSettings')).toHaveLength(0)
    expect(desktop.sent('discoverStudio')).toHaveLength(0)
  })

  it('sits in Roblox & Studio, next to the other sections of the same Settings page', async () => {
    studioHost(); voiceHost()
    await openSettings()
    await studioSection()
    await showSection('Images, voice & 3D')
    expect(screen.getByRole('region', {name: 'Where STAR generates'})).toBeTruthy()
    expect(screen.getByRole('region', {name: 'Star\'s voice'})).toBeTruthy()
  })

  it('saves the STAR Studio server choice and then shows the state of the connection, with nothing to type', async () => {
    studioHost()
    const user = await openSettings()
    const section = await studioSection()
    await user.click(within(section).getByRole('radio', {name: /^STAR Studio server/}))
    await waitFor(() => expect(desktop.sent('saveSettings')).toHaveLength(1))
    expect(desktop.sent('saveSettings')[0].payload).toEqual({settings: {studio_target: 'host_launcher'}})
    await waitFor(() => expect(within(section).getByRole('radio', {name: /^STAR Studio server/})).toHaveProperty('checked', true))
    expect(await within(section).findByText(/No server connection is set up on this PC yet\./)).toBeTruthy()
    expect(section.textContent).toContain('set up by the operator')
    expect(section.textContent).toContain('never asks for or stores a password')
    expect(section.textContent).toContain('edit permissions were cleared')
    // v0.9.0: the page cannot store or remove a connection. No field, no Save, no Forget.
    const group = within(section).getByRole('group', {name: 'STAR Studio server connection'})
    expect(group.querySelectorAll('input, textarea, select')).toHaveLength(0)
    expect(within(section).queryByLabelText('Server address')).toBeNull()
    expect(within(section).queryByLabelText('Command on the server')).toBeNull()
    expect(within(section).queryByRole('button', {name: /save server connection/i})).toBeNull()
    expect(within(section).queryByRole('button', {name: /forget/i})).toBeNull()
  })

  it('keeps the earlier choice when the host does not confirm the new one', async () => {
    studioHost()
    desktop.onAction('saveSettings', () => ({ok: false, error: 'RuntimeError: Wait for the current task before changing connections or permissions'}))
    const user = await openSettings()
    const section = await studioSection()
    await user.click(within(section).getByRole('radio', {name: /^STAR Studio server/}))
    expect((await within(section).findByRole('alert')).textContent).toContain('Wait for the current task')
    expect(within(section).getByRole('radio', {name: /^This PC/})).toHaveProperty('checked', true)
    expect(within(section).queryByLabelText('Server address')).toBeNull()
  })

  it('says that a connection exists without showing it, and never asks the host to store or remove one', async () => {
    studioHost({target: 'host_launcher', host: {configured: true, source: 'settings'}})
    const user = await openSettings()
    const section = await studioSection()
    expect(await within(section).findByText(/A server connection is set up on this PC\. Its address and command are not shown here\./)).toBeTruthy()
    const group = within(section).getByRole('group', {name: 'STAR Studio server connection'})
    expect(group.querySelectorAll('input, textarea, select, button')).toHaveLength(0)
    // The only buttons in the section are the test and (after a good test) the link to Tools.
    expect(within(section).getAllByRole('button').map(button => button.textContent?.trim())).toEqual(['Test connection'])
    await user.click(within(section).getByRole('button', {name: 'Test connection'}))
    await waitFor(() => expect(desktop.sent('discoverStudio')).toHaveLength(1))
    expect(desktop.sent('studioHostSave')).toHaveLength(0)
    expect(desktop.sent('studioHostClear')).toHaveLength(0)
    expect(desktop.sent('studioHostStatus').every(call => Object.keys(call.payload ?? {}).length === 0)).toBe(true)
  })

  it('says when the connection file is damaged and leaves the repair to the operator', async () => {
    studioHost({target: 'host_launcher', host: {configured: false, source: 'invalid'}})
    await openSettings()
    const section = await studioSection()
    expect(await within(section).findByText(/is damaged and is not used\. The operator has to set it up again\./)).toBeTruthy()
    expect(within(section).queryByRole('button', {name: /forget|save/i})).toBeNull()
  })

  it('says when the operator\'s own setting on this PC is the one in use', async () => {
    studioHost({target: 'host_launcher', host: {configured: true, source: 'environment'}})
    await openSettings()
    const section = await studioSection()
    expect(await within(section).findByText(/set by the operator on this PC/)).toBeTruthy()
    expect(within(section).queryByRole('button', {name: /forget|save/i})).toBeNull()
  })

  it('tests the chosen Studio through the host and reports what answered', async () => {
    studioHost()
    const user = await openSettings()
    const section = await studioSection()
    expect(within(section).getByRole('status').textContent).toContain('Not tested yet')
    await user.click(within(section).getByRole('button', {name: 'Test connection'}))
    await waitFor(() => expect(desktop.sent('discoverStudio')).toHaveLength(1))
    expect(desktop.sent('discoverStudio')[0].payload).toEqual({target: 'local_pc'})
    expect(within(section).getByRole('status').textContent).toContain('Testing Roblox Studio on this PC')
    expect(within(section).getByRole('button', {name: 'Test connection'})).toHaveProperty('disabled', true)
    await desktop.emitRaw(desktop.requestOf('discoverStudio'), 'result', report('local_pc'))
    await waitFor(() => expect(within(section).getByRole('status').textContent)
      .toContain('Connected. The Studio connector answered with 30 tools. Open in Studio: STAR Test Place.'))
    expect(section.textContent).toContain('Choosing the place and allowing edits is done under Tools')
    expect(within(section).queryByRole('alert')).toBeNull()
  })

  it('tests the STAR Studio server when that is the choice and explains a failed start in plain words', async () => {
    studioHost({target: 'host_launcher', host: {configured: true, source: 'settings'}})
    const user = await openSettings()
    const section = await studioSection()
    await waitFor(() => expect(within(section).getByRole('radio', {name: /^STAR Studio server/})).toHaveProperty('checked', true))
    await user.click(within(section).getByRole('button', {name: 'Test connection'}))
    await waitFor(() => expect(desktop.sent('discoverStudio')).toHaveLength(1))
    expect(desktop.sent('discoverStudio')[0].payload).toEqual({target: 'host_launcher'})
    await desktop.emitRaw(desktop.requestOf('discoverStudio'), 'result', report('host_launcher', {
      state: 'unavailable', instances: [], tool_count: 0, reason_code: 'connection_failed', diagnostic: {stage: 'process_startup', reason: 'failed'}}))
    await waitFor(() => expect(within(section).getByRole('status').textContent).toContain('Could not connect: the command did not start'))
    expect(within(section).getByRole('status').textContent).toContain('Nothing was changed')
    expect(section.textContent).not.toContain('Connected.')
  })

  it('reports a server choice without a stored connection as not configured, not as a failure of Studio', async () => {
    studioHost({target: 'host_launcher'})
    const user = await openSettings()
    const section = await studioSection()
    await waitFor(() => expect(within(section).getByRole('radio', {name: /^STAR Studio server/})).toHaveProperty('checked', true))
    await user.click(within(section).getByRole('button', {name: 'Test connection'}))
    await waitFor(() => expect(desktop.sent('discoverStudio')).toHaveLength(1))
    await desktop.emitRaw(desktop.requestOf('discoverStudio'), 'result', report('host_launcher', {
      state: 'unconfigured', instances: [], tool_count: 0, reason_code: 'host_launcher_unavailable', diagnostic: {stage: 'configuration', reason: 'not_configured'}}))
    await waitFor(() => expect(within(section).getByRole('status').textContent).toContain('No server connection is set up on this PC, so nothing was started'))
  })

  it('does not show an answer about the other Studio, or a host error, as a successful test', async () => {
    studioHost()
    const user = await openSettings()
    const section = await studioSection()
    await user.click(within(section).getByRole('button', {name: 'Test connection'}))
    await waitFor(() => expect(desktop.sent('discoverStudio')).toHaveLength(1))
    await desktop.emitRaw(desktop.requestOf('discoverStudio'), 'result', report('host_launcher'))
    expect((await within(section).findByRole('alert')).textContent).toContain('did not return a usable result')
    expect(section.textContent).not.toContain('Connected.')
    await user.click(within(section).getByRole('button', {name: 'Test connection'}))
    await waitFor(() => expect(desktop.sent('discoverStudio')).toHaveLength(2))
    await desktop.emitRaw(desktop.requestOf('discoverStudio'), 'error', 'ValueError: Studio connection changed; test the selected connection again')
    await waitFor(() => expect(within(section).getByRole('alert').textContent).toContain('Studio connection changed; test the selected connection again'))
    expect(section.textContent).not.toContain('Connected.')
  })
})


describe('Tools > Asset Forge opt-in', () => {
  it('keeps experimental asset tools off until the owner saves an explicit choice', async () => {
    desktop.onAction('saveSettings', call => {
      const settings = {...backendSettings, ...(call.payload.settings as Record<string, unknown>)}
      desktop.host({settings})
      return {ok: true, data: settings}
    })
    const user = userEvent.setup()
    render(<App/>)
    await screen.findByRole('textbox', {name: /message star/i})
    await user.click(screen.getByRole('button', {name: /^tools$/i}))
    const toggle = await screen.findByRole('checkbox', {name: /Enable experimental Asset Forge planning/})
    expect(toggle).toHaveProperty('checked', false)
    await user.click(toggle)
    expect(desktop.sent('saveSettings')).toHaveLength(0)
    await user.click(screen.getByRole('button', {name: /save connector settings/i}))
    await waitFor(() => expect(desktop.sent('saveSettings')).toHaveLength(1))
    expect(desktop.sent('saveSettings')[0].payload.settings).toMatchObject({asset_forge_enabled: true})
  })
})


describe('Tools > Business opt-in', () => {
  it('hides the Business tab until the owner enables it and saves', async () => {
    desktop.host({settings: {...backendSettings, commerce_enabled: false}})
    desktop.onAction('saveSettings', call => {
      const settings = {...backendSettings, ...(call.payload.settings as Record<string, unknown>)}
      desktop.host({settings})
      return {ok: true, data: settings}
    })
    const user = userEvent.setup()
    render(<App/>)
    await screen.findByRole('textbox', {name: /message star/i})
    expect(screen.queryByRole('button', {name: /^business$/i})).toBeNull()
    await user.click(screen.getByRole('button', {name: /^tools$/i}))
    const toggle = await screen.findByRole('checkbox', {name: /Enable Business tools/})
    expect(toggle).toHaveProperty('checked', false)
    expect(toggle.closest('label')?.textContent).toContain('always wait for your approval')
    await user.click(toggle)
    await user.click(screen.getByRole('button', {name: /save connector settings/i}))
    await waitFor(() => expect(desktop.sent('saveSettings')[0].payload.settings).toMatchObject({commerce_enabled: true}))
    expect(await screen.findByRole('button', {name: /^business$/i})).toBeTruthy()
  })
})
