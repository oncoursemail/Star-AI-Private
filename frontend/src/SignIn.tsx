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
          ? <MetallicCodeForm status={status} autoFocus onSignedIn={result => { onSignedIn(result); onDone() }} />
          : <p className="metallic-code-note">No Metallic Control address is set yet. You can add it later in Settings &gt; Account &amp; Metallic and sign in there.</p>}
        <div className="metallic-signin-actions">
          <button type="button" className="primary-button" onClick={onDone}>Continue</button>
          <span>{configured ? 'Continue without a code to use STAR as usual.' : 'Nothing else is needed to start.'}</span>
        </div>
      </div>
    </div>
  )
}
