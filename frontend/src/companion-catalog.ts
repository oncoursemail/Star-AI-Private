import {useCallback, useEffect, useState} from 'react'
import type {Dispatch, SetStateAction} from 'react'
import type {PetState} from './StarPet'

export type CompanionId = 'star' | 'ember' | 'astra'
export type CompanionMotion = 'subtle' | 'still'
export type CompanionPreferences = {
  version: 1
  character: CompanionId
  motion: CompanionMotion
  visible: boolean
}
export type CompanionCharacter = {
  id: CompanionId
  name: string
  image: string
  description: string
}

/** Original visual companions, independently chosen from the model or provider. */
export const COMPANIONS: readonly CompanionCharacter[] = [
  {id: 'star', name: 'Star', image: './assets/mascot/poses/stand.png', description: 'Gold bows, a little star, and a familiar face.'},
  {id: 'ember', name: 'Ember', image: './assets/companions/ember.png', description: 'Copper hair, round glasses, and a curious streak.'},
  {id: 'astra', name: 'Astra', image: './assets/companions/astra.png', description: 'Violet hair, little cat ears, and a playful spark.'},
]

export const COMPANION_PREFERENCE_KEY = 'star.companions.v1'
export const DEFAULT_COMPANION_PREFERENCES: Readonly<CompanionPreferences> = {
  version: 1, character: 'star', motion: 'subtle', visible: true,
}

export function normalizeCompanionPreferences(value: unknown): CompanionPreferences {
  const fallback = {...DEFAULT_COMPANION_PREFERENCES}
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fallback
  const stored = value as Record<string, unknown>
  if (stored.version !== 1) return fallback
  return {
    version: 1,
    character: stored.character === 'ember' || stored.character === 'astra' ? stored.character : 'star',
    motion: stored.motion === 'still' ? 'still' : 'subtle',
    visible: typeof stored.visible === 'boolean' ? stored.visible : true,
  }
}

function decodePreferences(raw: string | null): CompanionPreferences {
  if (!raw || raw.length > 2048) return {...DEFAULT_COMPANION_PREFERENCES}
  try { return normalizeCompanionPreferences(JSON.parse(raw)) }
  catch { return {...DEFAULT_COMPANION_PREFERENCES} }
}

function readPreferences(): CompanionPreferences {
  try { return decodePreferences(localStorage.getItem(COMPANION_PREFERENCE_KEY)) }
  catch { return {...DEFAULT_COMPANION_PREFERENCES} }
}

/** Device-local appearance only: never writes model, provider, or tool settings. */
export function useCompanionPreferences(): [CompanionPreferences, Dispatch<SetStateAction<CompanionPreferences>>] {
  const [preferences, setPreferences] = useState<CompanionPreferences>(readPreferences)
  const update = useCallback<Dispatch<SetStateAction<CompanionPreferences>>>(next => {
    setPreferences(previous => normalizeCompanionPreferences(typeof next === 'function' ? next(previous) : next))
  }, [])
  useEffect(() => {
    try { localStorage.setItem(COMPANION_PREFERENCE_KEY, JSON.stringify(preferences)) }
    catch { /* An unavailable preference store never blocks the workbench. */ }
  }, [preferences])
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === COMPANION_PREFERENCE_KEY || event.key === null) {
        setPreferences(decodePreferences(event.newValue))
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  return [preferences, update]
}

export function companionCharacter(id: CompanionId): CompanionCharacter {
  return COMPANIONS.find(character => character.id === id) ?? COMPANIONS[0]
}

export function companionImage(character: CompanionCharacter, state: PetState): string {
  if (character.id !== 'star') return character.image
  const poses: Partial<Record<PetState, string>> = {
    thinking: 'think', streaming: 'type-1', finished: 'wave-a',
    sleepy: 'sleep-sit', asleep: 'sleep-sit', update: 'letter',
  }
  return './assets/mascot/poses/' + (poses[state] ?? 'stand') + '.png'
}

const WORK_LABELS: Record<PetState, string> = {
  idle: 'Ready when you are', typing: 'Drafting a request',
  thinking: 'Working on your request', streaming: 'Answer in progress',
  finished: 'Answer complete', error: 'The request could not finish',
  cancelled: 'Request stopped', sleepy: 'Ready when you are',
  asleep: 'Ready when you are', update: 'An update is available',
}

/** These labels describe the app's supplied state, never a separate character/model run. */
export const companionWorkLabel = (state: PetState): string => WORK_LABELS[state] ?? WORK_LABELS.idle
