// @vitest-environment jsdom
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {AppearanceControls, AppearancePanel} from './AppearancePanel'
import {APPEARANCE_STORAGE_KEY, DEFAULT_APPEARANCE} from './appearance'
import {useAppearance} from './useAppearance'

function View() {
  const appearance = useAppearance()
  return <div className="shell"><AppearancePanel preferences={appearance.preferences} onChange={appearance.updateAppearance}
    onReset={appearance.resetAppearance} persisted={appearance.persisted} companionSettings={<button type="button">Choose a companion</button>}/></div>
}
beforeEach(() => {localStorage.clear()})
afterEach(() => {cleanup(); vi.restoreAllMocks(); localStorage.clear()})

describe('appearance drawer', () => {
  it('opens from an accessible trigger, shows real selections, and restores focus on Escape', async () => {
    const user = userEvent.setup()
    render(<View/>)
    const trigger = screen.getByRole('button', {name: 'Appearance'})
    await user.click(trigger)
    const drawer = screen.getByRole('dialog', {name: 'Make Star yours.'})
    expect(drawer.classList.contains('star-layer')).toBe(true)
    expect(within(drawer).getByRole('radio', {name: 'Obsidian'})).toHaveProperty('checked', true)
    expect(within(drawer).getAllByRole('radio')).toHaveLength(6)
    expect(within(drawer).getByRole('button', {name: 'Choose a companion'})).toBeTruthy()
    await user.click(within(drawer).getByRole('radio', {name: 'Pearl'}))
    expect(document.documentElement.getAttribute('data-star-theme')).toBe('pearl')
    expect(within(drawer).getByRole('radio', {name: 'Pearl'})).toHaveProperty('checked', true)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(document.activeElement).toBe(trigger)
  })

  it('edits custom accents live and keeps invalid input out of the applied palette', async () => {
    const user = userEvent.setup()
    render(<View/>)
    await user.click(screen.getByRole('button', {name: 'Appearance'}))
    const input = screen.getByRole('textbox', {name: 'Accent hex color'})
    await user.clear(input)
    await user.type(input, '#101113')
    await waitFor(() => expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}').accent).toBe('#101113'))
    const applied = document.documentElement.style.getPropertyValue('--star-appearance-gold')
    expect(applied).not.toBe('#101113')
    expect(screen.getByText(/to keep text readable/)).toBeTruthy()
    fireEvent.change(input, {target: {value: 'url(secret)'}})
    fireEvent.blur(input)
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByRole('alert').textContent).toContain('hex color')
    expect(document.documentElement.style.getPropertyValue('--star-appearance-gold')).toBe(applied)
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}').accent).toBe('#101113')
    await user.click(screen.getByRole('button', {name: 'Use theme accent'}))
    expect(input.getAttribute('aria-invalid')).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}').accent).toBeNull()
  })

  it('accepts shorthand on commit, supports density, and resets all appearance preferences', async () => {
    const user = userEvent.setup()
    render(<View/>)
    await user.click(screen.getByRole('button', {name: 'Appearance'}))
    await user.click(screen.getByRole('radio', {name: 'Grove'}))
    const input = screen.getByRole('textbox', {name: 'Accent hex color'})
    await user.clear(input)
    await user.type(input, '#abc')
    await user.tab()
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}').accent).toBe('#AABBCC')
    await user.click(screen.getByRole('radio', {name: 'Compact spacing'}))
    expect(document.documentElement.getAttribute('data-star-density')).toBe('compact')
    await user.click(screen.getByRole('button', {name: 'Reset appearance'}))
    expect(screen.getByRole('radio', {name: 'Obsidian'})).toHaveProperty('checked', true)
    expect(screen.getByRole('radio', {name: 'Comfortable spacing'})).toHaveProperty('checked', true)
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}')).toEqual(DEFAULT_APPEARANCE)
  })

  it('does not turn a theme into a custom accent merely by tabbing through its color field', async () => {
    const user = userEvent.setup()
    render(<View/>)
    await user.click(screen.getByRole('button', {name: 'Appearance'}))
    const input = screen.getByRole('textbox', {name: 'Accent hex color'})
    await user.click(input)
    await user.tab()
    expect(JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || '{}')).toEqual(DEFAULT_APPEARANCE)
    expect(screen.getByRole('button', {name: 'Reset appearance'})).toHaveProperty('disabled', true)
  })

  it('makes inline controls usable without a second modal and reports observed persistence failure', () => {
    render(<AppearanceControls preferences={{...DEFAULT_APPEARANCE}} onChange={() => {}} onReset={() => {}} persisted={false}/>)
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('radio', {name: 'Dusk'})).toBeTruthy()
    expect(screen.getByText(/cannot save preferences/)).toBeTruthy()
  })
})
