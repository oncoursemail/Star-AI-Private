import {useSyncExternalStore} from 'react'

const pageVisible = () => typeof document === 'undefined' || document.visibilityState !== 'hidden'
const serverVisible = () => true
const subscribe = (notify: () => void) => {
  document.addEventListener('visibilitychange', notify)
  return () => document.removeEventListener('visibilitychange', notify)
}

/** Decorative work should stop explicitly when the application is hidden. */
export function usePageVisible() {
  return useSyncExternalStore(subscribe, pageVisible, serverVisible)
}
