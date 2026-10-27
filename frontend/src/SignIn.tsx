import {useEffect, useRef, useState, type FormEvent} from 'react'
import {LoaderCircle} from 'lucide-react'
import {StarMark} from './components'
import {askHost, clockTime, metallicPreview, untilText, type MetallicSignInResult, type MetallicStatus} from './metallic'
import './metallic.css'

/** What the host's refusal means, in words. Built from the result fields so the wording never depends on the
 *  backend's English; the host's own message is used only for a reply STAR could not classify. */
export function refusalText(result: MetallicSignInResult, address: string): string {
  const until = result.locked_until
  if (result.error === 'locked' || (result.error === 'wrong_code' && result.attempts_left === 0 && until))
    return until ? `Too many wrong codes. Sign-in is locked until ${clockTime(until)} (${untilText(until)}).` : 'Too many wrong codes. Wait 15 minutes, then try again.'
  if (result.error === 'wrong_code') {
    const left = result.attempts_left
    return typeof left === 'number' ? `Metallic did not accept that code. ${left} ${left === 1 ? 'try' : 'tries'} left before a 15-minute lock.` : 'Metallic did not accept that code.'
  }
  if (result.error === 'unreachable') return `Metallic Control did not answer${address ? ` at ${address}` : ''}. Check the address or your network.`
  if (result.error === 'not_configured') return 'No Metallic Control address is set. Add it in Settings > Account & Metallic.'
  if (result.error === 'wrong_login') return 'Wrong username or password.'
  if (result.error === 'disabled') return 'This Metallic account is turned off. Ask a Metallic admin for help.'
  if (result.error === 'not_allowed') return 'This Metallic account cannot open Metallic Control. Only owner and admin accounts can.'
  if (result.error === 'account_locked') return until ? `Too many wrong tries. This account is paused until ${clockTime(until)} (${untilText(until)}).` : 'Too many wrong tries. This account is paused for a while.'
  if (result.error === 'accounts_unreachable') return 'Metallic accounts did not answer. Check the accounts address in Settings > Account & Metallic.'
  if (result.error === 'accounts_not_configured') return 'No Metallic accounts address is set. Add it in Settings > Account & Metallic.'
  if (result.error === 'bad_certificate') return 'The Metallic accounts certificate does not match the fingerprint in Settings. STAR did not connect.'
  return result.message || 'Metallic Control sent a reply STAR could not read.'
}

/** Browser preview: every code is refused, so the refusal and the lockout can be seen without any code in the app. */
let previewTries = 5
function previewSignIn(): MetallicSignInResult {
  previewTries = Math.max(0, previewTries - 1)
  const locked = previewTries === 0 ? Math.round(Date.now() / 1000) + 15 * 60 : null
  return {ok: false, signed_in: false, error: 'wrong_code', message: '', attempts_left: previewTries, locked_until: locked}
}

/** The access-code field and its button. The typed code goes to the host once and is cleared after every attempt. */
export function MetallicCodeForm({status, onSignedIn, submitLabel = 'Sign in', disabled = false, autoFocus = false}: {
  status: MetallicStatus | null
  onSignedIn: (result: MetallicSignInResult) => void
  submitLabel?: string
  disabled?: boolean
  autoFocus?: boolean
}) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [refusal, setRefusal] = useState('')
  const [lockedUntil, setLockedUntil] = useState<number | null>(status?.locked_until ?? null)
  const [, setTick] = useState(0)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
  useEffect(() => { if (status?.locked_until) setLockedUntil(status.locked_until) }, [status?.locked_until])
  const locked = lockedUntil !== null && lockedUntil * 1000 > Date.now()
  // While locked, re-render now and then so the button comes back when the lock ends.
  useEffect(() => {
    if (!locked) return
    const timer = window.setInterval(() => setTick(t => t + 1), 15000)
    return () => window.clearInterval(timer)
  }, [locked])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const typed = code
    if (!typed || busy || locked || disabled) return
    setBusy(true)
    setRefusal('')
    setCode('')
    const reply = metallicPreview()
      ? {ok: true as const, data: previewSignIn()}
      : await askHost<MetallicSignInResult>('metallicSignIn', {code: typed.slice(0, 256)})
    if (!mounted.current) return
    setBusy(false)
    if (!reply.ok) { setRefusal(reply.error); return }
    const result = reply.data
    if (result?.ok && result.signed_in) { onSignedIn(result); return }
    if (!result) { setRefusal('Metallic Control sent a reply STAR could not read.'); return }
    if (result.locked_until) setLockedUntil(result.locked_until)
    setRefusal(refusalText(result, status?.control_url || ''))
  }
  // A lock only comes from wrong codes, so it reads the same whether it started here or before the screen opened.
  const message = locked && lockedUntil ? `Too many wrong codes. Sign-in is locked until ${clockTime(lockedUntil)} (${untilText(lockedUntil)}).` : refusal
  return (
    <form className="metallic-code-form" onSubmit={event => void submit(event)}>
      <label className="metallic-code-label" htmlFor="metallic-code">Metallic access code <span>(optional)</span></label>
      <div className="metallic-code-row">
        <input id="metallic-code" type="password" autoComplete="off" spellCheck={false} maxLength={256}
          value={code} onChange={event => setCode(event.target.value)} disabled={busy || disabled || locked}
          aria-describedby="metallic-code-note" autoFocus={autoFocus} placeholder="Enter your code" />
        <button type="submit" className="secondary-button" disabled={!code || busy || locked || disabled}>
          {busy ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : null} {busy ? 'Checking' : submitLabel}
        </button>
      </div>
      <p id="metallic-code-note" className="metallic-code-note">Metallic Control checks the code. STAR keeps only the sign-in it gets back, for this Windows user.</p>
      {message && <p className="metallic-refusal" role="alert">{message}</p>}
    </form>
  )
}

function previewAccountSignIn(): MetallicSignInResult {
  return {ok: false, signed_in: false, error: 'wrong_login', message: ''}
}

/** The Metallic account form: username, password, and the second-factor code once the accounts service asks for it.
 *  The password goes to the host once and is cleared after every answer except "second factor needed / wrong code",
 *  where the same password is sent again with the code. Nothing here stores it. */
export function MetallicAccountForm({status, onSignedIn, submitLabel = 'Sign in', disabled = false, autoFocus = false}: {
  status: MetallicStatus | null
  onSignedIn: (result: MetallicSignInResult) => void
  submitLabel?: string
  disabled?: boolean
  autoFocus?: boolean
}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [second, setSecond] = useState('')
  const [needSecond, setNeedSecond] = useState(false)
  const [recovery, setRecovery] = useState(false)
  const [busy, setBusy] = useState(false)
  const [refusal, setRefusal] = useState('')
  const [lockedUntil, setLockedUntil] = useState<number | null>(status?.locked_until ?? null)
  const [, setTick] = useState(0)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])
  useEffect(() => { if (status?.locked_until) setLockedUntil(status.locked_until) }, [status?.locked_until])
  const locked = lockedUntil !== null && lockedUntil * 1000 > Date.now()
  useEffect(() => {
    if (!locked) return
    const timer = window.setInterval(() => setTick(t => t + 1), 15000)
    return () => window.clearInterval(timer)
  }, [locked])

  const ready = username.trim() !== '' && password !== '' && (!needSecond || second.trim() !== '')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!ready || busy || locked || disabled) return
    const payload: Record<string, unknown> = {username: username.trim().slice(0, 64), password: password.slice(0, 128)}
    if (needSecond && second.trim()) payload[recovery ? 'recovery_code' : 'otp'] = second.trim().slice(0, 64)
    setBusy(true)
    setRefusal('')
    setSecond('')
    const reply = metallicPreview()
      ? {ok: true as const, data: previewAccountSignIn()}
      : await askHost<MetallicSignInResult>('metallicAccountSignIn', payload)
    if (!mounted.current) return
    setBusy(false)
    const result = reply.ok ? reply.data : null
    const again = result?.error === 'otp_required' || result?.error === 'wrong_code'
    if (!again) setPassword('')
    if (!reply.ok) { setRefusal(reply.error); return }
    if (result?.ok && result.signed_in) { onSignedIn(result); return }
    if (!result) { setRefusal('Metallic sent a reply STAR could not read.'); return }
    if (result.error === 'otp_required') { setNeedSecond(true); return }
    if (result.locked_until && result.error === 'locked') setLockedUntil(result.locked_until)
    setRefusal(refusalText(result, status?.control_url || ''))
  }
  const message = locked && lockedUntil ? `Too many wrong codes. Sign-in is locked until ${clockTime(lockedUntil)} (${untilText(lockedUntil)}).` : refusal
  const off = busy || disabled || locked
  return (
    <form className="metallic-code-form" onSubmit={event => void submit(event)}>
      <label className="metallic-field"><span>Metallic username</span>
        <input type="text" autoComplete="username" spellCheck={false} maxLength={64} value={username}
          onChange={event => setUsername(event.target.value)} disabled={off || needSecond} autoFocus={autoFocus} /></label>
      <label className="metallic-field"><span>Metallic password</span>
        <input type="password" autoComplete="current-password" spellCheck={false} maxLength={128} value={password}
          onChange={event => setPassword(event.target.value)} disabled={off || needSecond} /></label>
      {needSecond && <label className="metallic-field"><span>{recovery ? 'Recovery code' : '6-digit code from your authenticator app'}</span>
        <input type="text" inputMode={recovery ? 'text' : 'numeric'} autoComplete="one-time-code" spellCheck={false} maxLength={64}
          value={second} onChange={event => setSecond(event.target.value)} disabled={off} autoFocus />
      </label>}
      {needSecond && <button type="button" className="metallic-link" onClick={() => { setRecovery(r => !r); setSecond('') }}>
        {recovery ? 'Use the authenticator code instead' : 'Use a recovery code instead'}</button>}
      <div className="metallic-code-row">
        <button type="submit" className="secondary-button" disabled={!ready || off}>
          {busy ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : null} {busy ? 'Checking' : submitLabel}
        </button>
      </div>
      <p className="metallic-code-note">Metallic accounts checks the password and gives STAR only a short sign-in for Metallic Control (owner and admin accounts). STAR does not keep the password.</p>
      {message && <p className="metallic-refusal" role="alert">{message}</p>}
    </form>
  )
}

/** Both ways in: a Metallic account (when its address is set) and, always, the access code as the fallback. */
export function MetallicSignInForm({status, onSignedIn, disabled = false, autoFocus = false}: {
  status: MetallicStatus | null
  onSignedIn: (result: MetallicSignInResult) => void
  disabled?: boolean
  autoFocus?: boolean
}) {
  const accounts = Boolean(status?.accounts_configured)
  const [mode, setMode] = useState<'account' | 'code'>(accounts ? 'account' : 'code')
  useEffect(() => { if (!accounts) setMode('code') }, [accounts])
  return (
    <div className="metallic-signin-forms">
      {accounts && <div className="metallic-mode" role="group" aria-label="Sign in with">
        <button type="button" className={mode === 'account' ? 'metallic-mode-on' : ''} aria-pressed={mode === 'account'} onClick={() => setMode('account')}>Metallic account</button>
        <button type="button" className={mode === 'code' ? 'metallic-mode-on' : ''} aria-pressed={mode === 'code'} onClick={() => setMode('code')}>Access code</button>
      </div>}
      {mode === 'account'
        ? <MetallicAccountForm key="account" status={status} onSignedIn={onSignedIn} disabled={disabled} autoFocus={autoFocus} />
        : <MetallicCodeForm key="code" status={status} onSignedIn={onSignedIn} disabled={disabled} autoFocus={autoFocus} />}
    </div>
  )
}

/** Full-screen first-launch screen. "Continue" opens normal STAR with or without a code; a code only adds Metallic.
 *  Render it inside `.shell` (it covers the window). */
export function SignIn({status, onDone, onSignedIn}: {
  status: MetallicStatus | null
  /** Leave the screen (Continue, or right after a successful sign-in). */
  onDone: () => void
  /** A successful sign-in; pass it to `session.signedInWith`. */
  onSignedIn: (result: MetallicSignInResult) => void
}) {
  const configured = status?.configured !== false
  return (
    <div className="metallic-signin" role="dialog" aria-modal="true" aria-labelledby="metallic-signin-title">
      <div className="metallic-signin-card">
        <span className="metallic-signin-mark"><StarMark size={30} /></span>
        <h1 id="metallic-signin-title">Welcome to STAR</h1>
        <p className="metallic-signin-lead">STAR works on its own: chat, projects and tools need no account. If you run Metallic, sign in to also see your Metallic projects and machines.</p>
        {configured
          ? <MetallicSignInForm status={status} autoFocus onSignedIn={result => { onSignedIn(result); onDone() }} />
          : <p className="metallic-code-note">No Metallic Control address is set yet. You can add it later in Settings &gt; Account &amp; Metallic and sign in there.</p>}
        <div className="metallic-signin-actions">
          <button type="button" className="primary-button" onClick={onDone}>Continue</button>
          <span>{configured ? 'Continue without a code to use STAR as usual.' : 'Nothing else is needed to start.'}</span>
        </div>
      </div>
    </div>
  )
}
