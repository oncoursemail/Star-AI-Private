// @vitest-environment jsdom
import {useState} from 'react'
import {act, cleanup, fireEvent, render, renderHook, screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {CompanionControls, CompanionShelf} from './CompanionShelf'
import {COMPANION_PREFERENCE_KEY, DEFAULT_COMPANION_PREFERENCES, useCompanionPreferences} from './companion-catalog'
import type {CompanionPreferences} from './companion-catalog'
import type {PetState} from './StarPet'
import {MotionPolicy} from './MotionPolicy'

beforeEach(() => {
  localStorage.clear()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  // jsdom omits CSS.escape; user-event uses it to find the next native radio.
  // Hex escapes preserve the actual generated group name, including punctuation.
  vi.stubGlobal('CSS', {escape: (value: string) => Array.from(value, character => '\\' + character.codePointAt(0)!.toString(16) + ' ').join('')})
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear() })

function Example({state = 'idle', compact = false, reduced = false}: {state?: PetState; compact?: boolean; reduced?: boolean}) {
  const [preferences, setPreferences] = useState<CompanionPreferences>({...DEFAULT_COMPANION_PREFERENCES})
  return <CompanionShelf state={state} compact={compact} reducedMotion={reduced} preferences={preferences} onPreferencesChange={setPreferences}/>
}

describe('CompanionShelf', () => {
  it('shows a real original character with a native keyboard-operable choice group', async () => {
    const user = userEvent.setup()
    const {container} = render(<Example/>)
    expect(screen.getByRole('heading', {name: 'Companions'})).toBeTruthy()
    expect(screen.getByRole('radio', {name: 'Star'})).toHaveProperty('checked', true)
    expect(container.querySelector('.companion-shelf__character')?.getAttribute('src')).toBe('./assets/mascot/poses/stand.png')
    screen.getByRole('radio', {name: 'Star'}).focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('radio', {name: 'Ember'})).toHaveProperty('checked', true)
    expect(container.querySelector('.companion-shelf__character')?.getAttribute('src')).toBe('./assets/companions/ember.png')
    expect(screen.getByText('Ready when you are')).toBeTruthy()
  })
  it('renders only an actionable row until the compact shelf is opened', async () => {
    const user = userEvent.setup()
    const {container} = render(<Example compact/>)
    expect(screen.getByRole('button', {name: 'Open companions'})).toBeTruthy()
    expect(container.querySelector('.companion-shelf__stage')).toBeNull()
    await user.click(screen.getByRole('button', {name: 'Open companions'}))
    expect(screen.getByRole('group', {name: 'Choose your companion'})).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('heading', {name: 'Companions'}))
    await user.click(screen.getByRole('button', {name: 'Close companions'}))
    expect(container.querySelector('.companion-shelf__stage')).toBeNull()
    expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Open companions'}))
  })
  it('can hide and reopen the shelf without stranding keyboard focus', async () => {
    const user = userEvent.setup()
    const {container} = render(<Example/>)
    await user.click(screen.getByRole('button', {name: 'Hide companions'}))
    expect(container.querySelector('.companion-shelf__stage')).toBeNull()
    expect(document.activeElement).toBe(screen.getByRole('button', {name: 'Show companions'}))
    await user.click(screen.getByRole('button', {name: 'Show companions'}))
    expect(document.activeElement).toBe(screen.getByRole('heading', {name: 'Companions'}))
  })
  it('offers an immediate still control and preserves the active state text', async () => {
    const user = userEvent.setup()
    const {container, rerender} = render(<Example/>)
    rerender(<Example state="thinking"/>)
    expect(container.querySelector('.companion-shelf__character')?.getAttribute('data-reaction')).toBe('focus')
    await user.click(screen.getByRole('button', {name: 'Keep companions still'}))
    expect(container.querySelector('.companion-shelf')?.getAttribute('data-still')).toBe('true')
    expect(container.querySelector('.companion-shelf__character')?.hasAttribute('data-reaction')).toBe(false)
    expect(screen.getByText('Working on your request')).toBeTruthy()
  })
  it('cannot override the shared reduced-motion policy', async () => {
    const user = userEvent.setup()
    const {container} = render(<MotionPolicy reduced><Example/></MotionPolicy>)
    await user.click(screen.getByRole('button', {name: 'Keep companions still'}))
    await user.click(screen.getByRole('button', {name: 'Allow subtle companion motion'}))
    expect(container.querySelector('.companion-shelf')?.getAttribute('data-still')).toBe('true')
    expect(screen.getByText('Reduced motion is on')).toBeTruthy()
  })
  it('ends a finite reaction after its animation and does not start idle timers', () => {
    const interval = vi.spyOn(window, 'setInterval')
    const {container, rerender} = render(<Example/>)
    rerender(<Example state="finished"/>)
    const image = container.querySelector('.companion-shelf__character') as HTMLImageElement
    expect(image.dataset.reaction).toBe('complete')
    fireEvent.animationEnd(image)
    expect(image.dataset.reaction).toBeUndefined()
    expect(interval).not.toHaveBeenCalled()
  })
  it('drops decorative reactions when hidden and resumes at the current work state', () => {
    const {container, rerender} = render(<Example/>)
    rerender(<Example state="thinking"/>)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    rerender(<Example state="streaming"/>)
    expect(container.querySelector('.companion-shelf')?.getAttribute('data-still')).toBe('true')
    expect(container.querySelector('.companion-shelf__character')?.hasAttribute('data-reaction')).toBe(false)
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(screen.getByText('Answer in progress')).toBeTruthy()
    expect(container.querySelector('.companion-shelf__character')?.hasAttribute('data-reaction')).toBe(false)
  })
  it('keeps an understandable fallback when a character image cannot load', () => {
    const {container} = render(<Example/>)
    fireEvent.error(container.querySelector('.companion-shelf__character') as HTMLImageElement)
    expect(screen.getByText('Portrait unavailable')).toBeTruthy()
    expect(screen.getByRole('radio', {name: 'Astra'})).toBeTruthy()
    expect(screen.getByText('Ready when you are')).toBeTruthy()
  })
  it('exposes shared appearance controls without model settings or a fake provider selector', async () => {
    const user = userEvent.setup()
    const update = vi.fn()
    render(<CompanionControls preferences={{...DEFAULT_COMPANION_PREFERENCES}} onPreferencesChange={update} reducedMotion/>)
    await user.click(screen.getByRole('radio', {name: 'Astra'}))
    expect(update).toHaveBeenLastCalledWith({...DEFAULT_COMPANION_PREFERENCES, character: 'astra'})
    await user.selectOptions(screen.getByRole('combobox', {name: 'Companion motion'}), 'still')
    expect(update).toHaveBeenLastCalledWith({...DEFAULT_COMPANION_PREFERENCES, motion: 'still'})
    expect(screen.getByText('Your reduced-motion preference keeps companions still.')).toBeTruthy()
  })
})

describe('companion local preferences', () => {
  it('persists an explicit choice across mounts without touching the old floating-pet preference', () => {
    localStorage.setItem('star.pet.visible', 'off')
    const first = renderHook(() => useCompanionPreferences())
    act(() => first.result.current[1]({...DEFAULT_COMPANION_PREFERENCES, character: 'astra', motion: 'still', visible: false}))
    first.unmount()
    const second = renderHook(() => useCompanionPreferences())
    expect(second.result.current[0]).toEqual({...DEFAULT_COMPANION_PREFERENCES, character: 'astra', motion: 'still', visible: false})
    expect(localStorage.getItem('star.pet.visible')).toBe('off')
  })
  it('recovers from malformed storage and remains usable when persistence is unavailable', () => {
    localStorage.setItem(COMPANION_PREFERENCE_KEY, '{broken')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage blocked') })
    const {result} = renderHook(() => useCompanionPreferences())
    expect(result.current[0].visible).toBe(true)
    act(() => result.current[1](previous => ({...previous, character: 'ember'})))
    expect(result.current[0].character).toBe('ember')
  })
})
