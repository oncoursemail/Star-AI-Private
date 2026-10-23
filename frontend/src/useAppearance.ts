import {useCallback, useEffect, useId, useLayoutEffect, useMemo, useState} from 'react'
import {appearanceRootVariable, DEFAULT_APPEARANCE, normalizeAppearance, readAppearance, resolveAppearance, writeAppearance} from './appearance'
import type {AppearancePreferences, AppearanceUpdate} from './appearance'
import './appearance.css'

/** Mount once in Desktop. Dialog portals receive the same palette without changing the public site.
 * `applied` false (Studio layout off) leaves the page on tokens.css; the saved choice is kept for later. */
export function useAppearance(applied = true) {
  const [preferences, setPreferences] = useState<AppearancePreferences>(() => readAppearance())
  const [persisted, setPersisted] = useState(true)
  const owner = useId()
  const resolved = useMemo(() => resolveAppearance(preferences), [preferences])
  const updateAppearance = useCallback((patch: AppearanceUpdate) => {
    setPreferences(current => normalizeAppearance({...current, ...patch, version: 1}))
  }, [])
  const resetAppearance = useCallback(() => setPreferences({...DEFAULT_APPEARANCE}), [])

  useLayoutEffect(() => {
    if (!applied) return
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
  }, [applied, owner, preferences.theme, preferences.density, resolved])

  useEffect(() => { setPersisted(writeAppearance(preferences)) }, [preferences])
  return {preferences, updateAppearance, resetAppearance, persisted}
}
