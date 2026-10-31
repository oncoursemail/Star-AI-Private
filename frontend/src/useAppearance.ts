import {useCallback, useEffect, useId, useLayoutEffect, useMemo, useState} from 'react'
import {APPEARANCE_THEMES, appearanceRootVariable, DEFAULT_APPEARANCE, normalizeAppearance, readAppearance, resolveAppearance, writeAppearance} from './appearance'
import type {AppearancePreferences, AppearanceUpdate, ThemeId} from './appearance'
import './appearance.css'

/** Set once the owner picks something on the Appearance page; until then the page keeps tokens.css. */
const CHOSEN_KEY = 'star.appearance.chosen'
function readChosen(): boolean {
  try {return window.localStorage.getItem(CHOSEN_KEY) === 'on'} catch {return false}
}
function writeChosen(on: boolean) {
  try {if (on) window.localStorage.setItem(CHOSEN_KEY, 'on'); else window.localStorage.removeItem(CHOSEN_KEY)} catch {/* session only */}
}

/** Mount once in Desktop. Dialog portals receive the same palette without changing the public site.
 * The palette is applied when `applied` is true (Studio layout on) or once the owner has picked a theme, accent or
 * spacing; otherwise the page stays on tokens.css, so people who never choose keep today's look.
 * `previewTheme` (browser preview `?theme=` only) forces a theme for screenshots and is not saved. */
export function useAppearance(applied = true, previewTheme?: string | null) {
  const forced = APPEARANCE_THEMES.some(theme => theme.id === previewTheme) ? previewTheme as ThemeId : null
  const [preferences, setPreferences] = useState<AppearancePreferences>(() => forced ? {...readAppearance(), theme: forced} : readAppearance())
  const [chosen, setChosen] = useState(() => forced !== null || readChosen())
  const active = applied || chosen
  const [persisted, setPersisted] = useState(true)
  const owner = useId()
  const resolved = useMemo(() => resolveAppearance(preferences), [preferences])
  const updateAppearance = useCallback((patch: AppearanceUpdate) => {
    setChosen(true); writeChosen(true)
    setPreferences(current => normalizeAppearance({...current, ...patch, version: 1}))
  }, [])
  const resetAppearance = useCallback(() => {setChosen(false); writeChosen(false); setPreferences({...DEFAULT_APPEARANCE})}, [])

  useLayoutEffect(() => {
    if (!active) return
    const root = document.documentElement
    const attributes: Record<string, string> = {
      'data-star-appearance': 'v1', 'data-star-theme': preferences.theme,
      'data-star-density': preferences.density, 'data-star-appearance-owner': owner,
    }
    const variables = Object.fromEntries(Object.entries(resolved.tokens).map(([key, value]) => [appearanceRootVariable(key), value]))
    variables['--star-appearance-color-scheme'] = resolved.theme.scheme
    const previousAttributes = new Map(Object.keys(attributes).map(key => [key, root.getAttribute(key)]))
    const previousVariables = new Map(Object.keys(variables).map(key => [key, {
      value: root.style.getPropertyValue(key), priority: root.style.getPropertyPriority(key),
    }]))
    for (const [key, value] of Object.entries(attributes)) root.setAttribute(key, value)
    for (const [key, value] of Object.entries(variables)) root.style.setProperty(key, value)
    return () => {
      // Another mounted app owns its own appearance. Never tear down that owner's palette.
      if (root.getAttribute('data-star-appearance-owner') !== owner) return
      for (const [key, value] of previousAttributes) {
        if (value === null) root.removeAttribute(key)
        else root.setAttribute(key, value)
      }
      for (const [key, old] of previousVariables) {
        if (old.value) root.style.setProperty(key, old.value, old.priority)
        else root.style.removeProperty(key)
      }
    }
  }, [active, owner, preferences.theme, preferences.density, resolved])

  useEffect(() => { if (!forced) setPersisted(writeAppearance(preferences)) }, [preferences, forced])
  return {preferences, updateAppearance, resetAppearance, persisted, applied: active}
}
