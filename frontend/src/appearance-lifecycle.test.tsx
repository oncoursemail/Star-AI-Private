// @vitest-environment jsdom
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {useAppearance} from './useAppearance'
import {APPEARANCE_STORAGE_KEY} from './appearance'

function View() {
  const appearance = useAppearance()
  return <div className="shell">
    <output aria-label="View preferences">{JSON.stringify(appearance.preferences)}</output>
    <output aria-label="Preferences saved">{String(appearance.persisted)}</output>
    <button onClick={() => appearance.updateAppearance({theme: 'pearl', accent: '#123', density: 'compact'})}>Change appearance</button>
    <button onClick={appearance.resetAppearance}>Reset</button>
  </div>
}
beforeEach(() => {localStorage.clear()})
afterEach(() => {cleanup(); vi.restoreAllMocks(); localStorage.clear()})

describe('appearance owner lifecycle', () => {
  it('restores local preferences and updates root-owned values for shell and portal consumers', async () => {
    localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify({version: 1, theme: 'dusk', accent: null, density: 'compact'}))
    render(<View/>)
    const root = document.documentElement
    expect(root.getAttribute('data-star-theme')).toBe('dusk')
    expect(root.getAttribute('data-star-density')).toBe('compact')
    expect(root.style.getPropertyValue('--star-appearance-bg')).toBe('#16131C')
    expect(root.style.getPropertyValue('--star-bg')).toBe('')
    fireEvent.click(screen.getByRole('button', {name: 'Change appearance'}))
    expect(root.getAttribute('data-star-theme')).toBe('pearl')
    expect(root.style.getPropertyValue('--star-appearance-color-scheme')).toBe('light')
    await waitFor(() => expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}').accent).toBe('#112233'))
    fireEvent.click(screen.getByRole('button', {name: 'Reset'}))
    expect(root.getAttribute('data-star-theme')).toBe('obsidian')
    expect(root.getAttribute('data-star-density')).toBe('comfortable')
  })

  it('restores pre-existing root state on unmount without writing public-site semantic variables', () => {
    const root = document.documentElement
    root.setAttribute('data-star-theme', 'previous-owner')
    root.style.setProperty('--star-appearance-bg', '#ABCDEF', 'important')
    root.style.setProperty('--site-brand', '#FF6600')
    const view = render(<View/>)
    expect(root.style.getPropertyValue('--site-brand')).toBe('#FF6600')
    expect(root.style.getPropertyValue('--star-bg')).toBe('')
    view.unmount()
    expect(root.getAttribute('data-star-theme')).toBe('previous-owner')
    expect(root.style.getPropertyValue('--star-appearance-bg')).toBe('#ABCDEF')
    expect(root.style.getPropertyPriority('--star-appearance-bg')).toBe('important')
    expect(root.getAttribute('data-star-appearance')).toBeNull()
    root.removeAttribute('data-star-theme')
    root.style.removeProperty('--star-appearance-bg')
    root.style.removeProperty('--site-brand')
  })

  it('continues to personalize the current session when storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {throw new Error('storage denied')})
    render(<View/>)
    await waitFor(() => expect(screen.getByLabelText('Preferences saved').textContent).toBe('false'))
    fireEvent.click(screen.getByRole('button', {name: 'Change appearance'}))
    expect(document.documentElement.getAttribute('data-star-theme')).toBe('pearl')
    expect(screen.getByLabelText('View preferences').textContent).toContain('"accent":"#112233"')
  })
})
