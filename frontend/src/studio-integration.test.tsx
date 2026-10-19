// @vitest-environment jsdom
import {act, cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach, beforeAll, beforeEach, describe, expect, it, vi} from 'vitest'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'
import {COMPANION_PREFERENCE_KEY} from './companion-catalog'

let desktop: FakeDesktop
let App: typeof import('./App')['App']
let resize: (compact: boolean) => void

function installResponsiveMedia() {
  let compact = false
  const queries = new Map<string, MediaQueryList>()
  const matchMedia = (query: string): MediaQueryList => {
    const existing = queries.get(query)
    if (existing) return existing
    const target = new window.EventTarget()
    Object.defineProperties(target, {
      media: {value: query},
      matches: {get: () => query === '(max-width: 1179px)' && compact},
      onchange: {value: null, writable: true},
    })
    Object.assign(target, {
      addListener: (listener: EventListener) => target.addEventListener('change', listener),
      removeListener: (listener: EventListener) => target.removeEventListener('change', listener),
    })
    const media = target as MediaQueryList
    queries.set(query, media)
    return media
  }
  vi.stubGlobal('matchMedia', matchMedia)
  return (next: boolean) => act(() => {
    compact = next
    Object.defineProperty(window, 'innerWidth', {value: next ? 768 : 1440, writable: true, configurable: true})
    const media = queries.get('(max-width: 1179px)')
    media?.dispatchEvent(new Event('change'))
  })
}

beforeAll(async () => {
  desktop = installFakeDesktop()
  // Warm the application's real lazy chunk before timing individual interactions.
  await import('./Desktop')
  ;({App} = await import('./App'))
}, 60000)
beforeEach(() => {
  desktop.reset()
  localStorage.clear()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  resize = installResponsiveMedia()
})
afterEach(() => {cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear()})

async function openDesktop() {
  const user = userEvent.setup()
  const view = render(<App/>)
  const composer = await screen.findByRole('textbox', {name: /message star/i}) as HTMLTextAreaElement
  await waitFor(() => expect(desktop.sent('bootstrap').length).toBeGreaterThan(0))
  return {user, view, composer}
}

describe('Studio workbench integration', () => {
  it('retains the actual composer, draft, caret, and focus across both layout breakpoints', async () => {
    const {user, composer} = await openDesktop()
    await user.type(composer, 'Keep this unfinished research question')
    composer.setSelectionRange(5, 17)
    composer.focus()
    resize(true)
    expect(screen.getByRole('textbox', {name: /message star/i})).toBe(composer)
    expect(composer.value).toBe('Keep this unfinished research question')
    expect(composer.selectionStart).toBe(5)
    expect(composer.selectionEnd).toBe(17)
    expect(document.activeElement).toBe(composer)
    expect(screen.getByRole('button', {name: 'Open companions'})).toBeTruthy()
    resize(false)
    expect(screen.getByRole('textbox', {name: /message star/i})).toBe(composer)
    expect(composer.selectionStart).toBe(5)
    expect(composer.selectionEnd).toBe(17)
    expect(document.activeElement).toBe(composer)
    expect(screen.getByRole('heading', {name: 'Companions'})).toBeTruthy()
    expect(desktop.sent('sendMessage')).toHaveLength(0)
  })

  it('keeps a streaming conversation and its Stop action connected after resizing', async () => {
    const {user, composer} = await openDesktop()
    await user.type(composer, 'Compare these two approaches')
    await user.keyboard('{Enter}')
    const request = await waitFor(() => desktop.requestOf('sendMessage'))
    desktop.delta(request, 'The first approach ')
    const conversation = screen.getByRole('log', {name: 'Conversation'})
    resize(true)
    desktop.delta(request, 'retains the original context.')
    expect(screen.getByRole('log', {name: 'Conversation'})).toBe(conversation)
    await waitFor(() => expect(conversation.textContent).toContain('The first approach retains the original context.'))
    expect(screen.getByRole('textbox', {name: /message star/i})).toBe(composer)
    await user.click(screen.getByRole('button', {name: 'Open companions'}))
    expect(screen.getByText('Answer in progress')).toBeTruthy()
    await user.click(screen.getByRole('button', {name: /^stop/i}))
    expect(desktop.sent('cancelMessage')).toHaveLength(1)
    desktop.fail(request, 'Request cancelled.', 'cancelled')
    expect(screen.getByText('Request stopped')).toBeTruthy()
    resize(false)
    expect(screen.getByRole('log', {name: 'Conversation'})).toBe(conversation)
    expect(desktop.sent('sendMessage')).toHaveLength(1)
  })

  it('moves companion focus to the reopen control when its focused content collapses on resize', async () => {
    const {user} = await openDesktop()
    const selected = screen.getByRole('radio', {name: 'Star'})
    selected.focus()
    expect(document.activeElement).toBe(selected)
    resize(true)
    expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Open companions'}))
    await user.click(screen.getByRole('button', {name: 'Open companions'}))
    screen.getByRole('button', {name: 'Close companions'}).focus()
    resize(false)
    expect(document.activeElement).toBe(screen.getByRole('heading', {name: 'Companions'}))
  })

  it('keeps a hidden shelf hidden across resizing and independent of the legacy floating pet', async () => {
    localStorage.setItem('star.pet.visible', 'on')
    const {user, composer} = await openDesktop()
    await user.type(composer, 'A draft that stays here')
    expect(screen.getByTestId('star-pet')).toBeTruthy()
    await user.click(screen.getByRole('button', {name: 'Hide companions'}))
    resize(true)
    expect(screen.getByRole('button', {name: 'Show companions'})).toBeTruthy()
    expect(screen.queryByRole('heading', {name: 'Companions'})).toBeNull()
    expect(screen.getByTestId('star-pet')).toBeTruthy()
    resize(false)
    expect(screen.queryByRole('heading', {name: 'Companions'})).toBeNull()
    expect(JSON.parse(localStorage.getItem(COMPANION_PREFERENCE_KEY) ?? '{}').visible).toBe(false)
    expect(localStorage.getItem('star.pet.visible')).toBe('on')
    expect(composer.value).toBe('A draft that stays here')
  })

  it('updates theme, density, and character through Appearance without submitting or replacing a draft', async () => {
    const {user, composer} = await openDesktop()
    await user.type(composer, 'Preserve this draft while I customize')
    await user.click(screen.getByRole('button', {name: 'Appearance'}))
    const drawer = await screen.findByRole('dialog')
    await user.click(within(drawer).getByRole('radio', {name: 'Pearl'}))
    await user.click(within(drawer).getByRole('radio', {name: 'Compact spacing'}))
    await user.click(within(drawer).getByRole('radio', {name: 'Astra'}))
    await user.click(within(drawer).getByRole('button', {name: 'Close appearance'}))
    expect(screen.getByRole('textbox', {name: /message star/i})).toBe(composer)
    expect(composer.value).toBe('Preserve this draft while I customize')
    expect(document.documentElement.getAttribute('data-star-theme')).toBe('pearl')
    expect(document.documentElement.getAttribute('data-star-density')).toBe('compact')
    expect(screen.getByRole('radio', {name: 'Astra'})).toHaveProperty('checked', true)
    expect(desktop.sent('sendMessage')).toHaveLength(0)
    expect(desktop.sent('saveSettings')).toHaveLength(0)
  })

  it.each(['on', 'off'])('preserves the existing Workbench home choice %s and keeps starter actions editable', async preference => {
    localStorage.setItem('star.home.workbench', preference)
    const {user, composer} = await openDesktop()
    const crafted = preference === 'on'
    expect(screen.getByRole('heading', {name: crafted ? 'Make something worth keeping.' : 'What are we making?'})).toBeTruthy()
    resize(true)
    expect(screen.getByRole('heading', {name: crafted ? 'Make something worth keeping.' : 'What are we making?'})).toBeTruthy()
    if (crafted) {
      await user.click(screen.getByRole('button', {name: /Debug a Luau script/i}))
      expect(composer.value).toContain('verification')
    }
    expect(localStorage.getItem('star.home.workbench')).toBe(preference)
    expect(desktop.sent('sendMessage')).toHaveLength(0)
    expect(screen.queryByTestId('star-pet')).toBeNull()
  })
})
