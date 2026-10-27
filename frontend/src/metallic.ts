/**
 * Metallic access for STAR Desktop: the shapes the host returns (star/metallic_access.py) and the small bridge helpers
 * the sign-in screen, the Settings block and the Metallic section share.
 *
 * The access code is checked by Metallic Control only. Nothing here knows a code, stores one or decides whether one is
 * right; the page sends what was typed once and shows the host's answer. Times are unix seconds.
 */
import {useCallback, useEffect, useState} from 'react'
import {onBackendEvent, request} from './bridge'

export type MetallicStatus = {
  signed_in: boolean
  expires_at: number | null
  configured: boolean
  control_url: string
  locked_until: number | null
  secure_store: boolean
}
export type MetallicSignInError = 'wrong_code' | 'locked' | 'unreachable' | 'not_configured' | 'bad_reply'
export type MetallicSignInResult = {
  ok: boolean
  signed_in: boolean
  expires_at?: number | null
  error?: MetallicSignInError
  message: string
  attempts_left?: number
  locked_until?: number | null
}
export type MetallicRange = 'hour' | 'day' | 'week'

/* ---------- Metallic Control's State document (metallic/control-ui/src/types.ts), read-only, every field optional ---------- */
export type Fs = {mount: string; total: number; used: number; pct: number | null}
export type Gpu = {name: string; util: number | null; mem_used: number | null; mem_total: number | null; temp?: number | null}
export type MachineState = {
  id: string; name: string; role?: string; kind?: string; online: boolean; last_seen?: number | null; pending?: string
  ncpu?: number; cpu?: number | null; mem?: {total: number; used: number; pct: number}
  fs?: Fs[]; net?: {rx: number; tx: number}; gpu?: Gpu | null
}
export type NightSchool = {
  paused: boolean
  report?: {written?: string; status?: string; attempts_total?: number | null; passed_first_total?: number | null
    examples_total?: number | null; answers_per_active_hour?: number | null; lessons_active_total?: number | null}
  /** Keyed by UTC hour, "2026-10-26T14": first / first_pass / lesson / lesson_pass / validation / validation_pass. */
  hours?: Record<string, Record<string, number>>
}
export type BrainFacts = {at?: number; night_school?: NightSchool; ok?: boolean; error?: string}
export type Gen = {machine: string; model: string; slot: number; tps: number | null; n_gen?: number | null; t: number}
export type BackupRow = {
  set: string; where: string; schedule?: string; machine?: string; last_attempt_utc?: string; last_success_utc?: string
  latest_complete?: boolean; in_progress?: boolean; repository_bytes?: number
  last_error?: {at: string; action: string; message: string} | null; error?: string
}
export type DevState = {
  at?: number
  repos?: {name: string; open_issues: number; open_prs: number; releases: number; updated: string; branch: string; url: string}[]
  prs?: {repo: string; number: number; title: string; draft: boolean; updated: string; author: string; url: string}[]
  releases?: {repo: string; tag: string; name: string; published: string; url: string}[]
  runs?: {repo: string; name: string; status: string; branch: string; started: string; updated: string; url: string}[]
  runners?: {name: string; status: string; version: string; labels: string[]}[]
}
export type DevPcProject = {
  name: string; lang: string; connected: boolean; note?: string; target?: string; branch?: string; head?: string
  pending?: string[]; release?: {tag: string; date: string}
  checks?: {verdict: string; started: string; red: string[]; branch: string; seconds: number | null}[]
  queue_runs?: {started: string; target: string; seconds: number; applied: boolean; merged: string[]; entries: {branch: string; status: string}[]}[]
}
export type DevPc = {
  at: number; repo: string
  prs?: {number: number; title: string; draft: boolean; updated: string; author: string; head: string; base: string; url: string}[] | null
  runs?: {id: number; title: string; workflow: string; status: string; conclusion: string; branch: string; created: string; updated: string; url: string}[] | null
  runners?: {name: string; status: string; busy: boolean; labels: string[]}[] | null
  projects?: DevPcProject[]
}
export type MetallicState = {
  generated: number
  machines?: MachineState[]
  star?: {brains?: Record<string, BrainFacts>; generating?: Gen[]}
  dev?: DevState
  dev_pc?: DevPc | null
  runners?: {runner: string; kind: string; state: string; machine: string}[]
  backups?: BackupRow[]
  backup_pc?: {last_success_utc: string; last_attempt_utc: string; error: string | null; snapshot: string} | null
  forge_backups?: {ok: boolean; count: number; total_bytes: number; files?: {t: number; bytes: number; name: string}[]} | null
}
/** ts, avg, min, max */
export type Point = [number, number | null, number | null, number | null]
export type SeriesResponse = {range: MetallicRange; step: number; from: number; to: number; series: Record<string, Point[]>}
export type SpeedHour = {t: number; machine: string; model: string; n: number; tps_median: number; prompt_ms_median: number}
export type MetallicReply = {
  reachable: boolean
  signed_in: boolean
  expired?: boolean
  message?: string
  state?: MetallicState
  speed?: {hours: SpeedHour[]} | null
  series?: SeriesResponse | null
}

export type Asked<T> = {ok: true; data: T} | {ok: false; error: string}

/** One bridge call that may answer later: a `pending` reply is finished by the event carrying the same requestId.
 *  The listener is registered before the call, so a very fast worker cannot answer unseen. */
export function askHost<T>(action: string, payload: Record<string, unknown> = {}, timeoutMs = 45000): Promise<Asked<T>> {
  const requestId = crypto.randomUUID()
  return new Promise(resolve => {
    let done = false
    let off = () => {}
    const finish = (value: Asked<T>) => {
      if (done) return
      done = true
      off()
      window.clearTimeout(timer)
      resolve(value)
    }
    const timer = window.setTimeout(() => finish({ok: false, error: 'Metallic Control took too long to answer.'}), timeoutMs)
    off = onBackendEvent(event => {
      if (event.requestId !== requestId || event.kind === 'progress' || event.kind === 'voice') return
      if (event.kind === 'error') finish({ok: false, error: String(event.data || 'The request failed.').slice(0, 300)})
      else finish({ok: true, data: event.data as T})
    })
    void request<T>(action, payload, requestId).then(reply => {
      if (!reply.ok) finish({ok: false, error: reply.error || 'STAR could not reach its desktop host.'})
      else if (!reply.pending) finish({ok: true, data: reply.data as T})
    })
  })
}

/** Browser preview only (`?preview=1&metallic=signed|offline|empty|signin`); the Qt desktop never gets fixture data. */
export type MetallicPreview = 'signed' | 'offline' | 'empty' | 'signin'
export function metallicPreview(): MetallicPreview | null {
  if (typeof window === 'undefined' || window.qt?.webChannelTransport) return null
  const query = new URLSearchParams(window.location.search)
  if (!query.has('preview')) return null
  const value = query.get('metallic')
  return value === 'signed' || value === 'offline' || value === 'empty' || value === 'signin' ? value : null
}

const now = () => Date.now() / 1000
/** Signed in and not past the expiry the host reported. */
export const isSignedIn = (status: MetallicStatus | null | undefined) =>
  Boolean(status?.signed_in && (status.expires_at === null || status.expires_at > now()))

/** Local clock time, "14:05"; with the weekday when `withDay`. */
export function clockTime(t: number, withDay = false) {
  const d = new Date(t * 1000)
  const hm = d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false})
  return withDay ? `${d.toLocaleDateString([], {weekday: 'short'})} ${hm}` : hm
}
/** "in 12 min", "in 3 h" (or "now" once passed). */
export function untilText(t: number) {
  const s = t - now()
  if (s <= 60) return s <= 0 ? 'now' : 'in under a minute'
  if (s < 3600) return `in ${Math.round(s / 60)} min`
  return `in ${(s / 3600).toFixed(s < 36000 ? 1 : 0)} h`
}

export type MetallicSession = {
  status: MetallicStatus | null
  /** Signed in and not expired: the sidebar entry and the section's content show only while this is true. */
  signedIn: boolean
  /** The last sign-out happened because the token expired or was refused, not because the owner signed out. */
  ended: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
  /** A successful metallicSignIn result. */
  signedInWith: (result: MetallicSignInResult) => void
  /** metallicState reported signed_in false (expired, revoked, or the token file is gone). */
  markSignedOut: (expired: boolean) => void
}

const signedOutPreview: MetallicStatus = {signed_in: false, expires_at: null, configured: true, control_url: 'http://metallic-control.local:8470', locked_until: null, secure_store: true}

/** Metallic sign-in state for the whole desktop. `initial` is bootstrap's `metallic`; `inactive` is the unconnected
 *  preview, which never calls the host. Expiry hides Metallic at the reported time without waiting for a refresh. */
export function useMetallicStatus(initial: MetallicStatus | null | undefined, inactive: boolean): MetallicSession {
  const [preview] = useState(metallicPreview)
  const [status, setStatus] = useState<MetallicStatus | null>(() => {
    if (!preview) return initial ?? null
    return preview === 'signin' ? signedOutPreview : {...signedOutPreview, signed_in: true, expires_at: Math.round(now()) + 8 * 3600}
  })
  const [ended, setEnded] = useState(false)
  const [tick, setTick] = useState(0)
  useEffect(() => { if (!preview && initial) setStatus(initial) }, [initial, preview])

  const markSignedOut = useCallback((expired: boolean) => {
    setEnded(expired)
    setStatus(s => s && {...s, signed_in: false, expires_at: null})
  }, [])
  const refresh = useCallback(async () => {
    if (preview || inactive) return
    const reply = await request<MetallicStatus>('metallicStatus')
    if (reply.ok && reply.data) setStatus(reply.data)
  }, [preview, inactive])
  const signOut = useCallback(async () => {
    setEnded(false)
    // Hidden at once; the host deletes the token and reports the new status.
    setStatus(s => s && {...s, signed_in: false, expires_at: null})
    if (preview || inactive) return
    const reply = await request<MetallicStatus>('metallicSignOut')
    if (reply.ok && reply.data) setStatus(reply.data)
  }, [preview, inactive])
  const signedInWith = useCallback((result: MetallicSignInResult) => {
    setEnded(false)
    setStatus(s => ({...(s ?? signedOutPreview), signed_in: true, expires_at: result.expires_at ?? null, locked_until: null}))
  }, [])

  const expiresAt = status?.signed_in ? status.expires_at : null
  useEffect(() => {
    if (expiresAt === null) return
    const wait = expiresAt * 1000 - Date.now()
    if (wait <= 0) { setEnded(true); setStatus(s => s && {...s, signed_in: false, expires_at: null}); return }
    // Timers longer than ~24.8 days overflow; re-check then instead.
    const timer = window.setTimeout(() => setTick(t => t + 1), Math.min(wait + 250, 2 ** 31 - 1))
    return () => window.clearTimeout(timer)
  }, [expiresAt, tick])
  return {status, signedIn: isSignedIn(status), ended, refresh, signOut, signedInWith, markSignedOut}
}
