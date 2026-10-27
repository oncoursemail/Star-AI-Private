import {LogOut} from 'lucide-react'
import {MetallicCodeForm} from './SignIn'
import {clockTime, untilText, type MetallicSession} from './metallic'
import './metallic.css'

/** Settings > Account & Metallic: the Metallic Control address (a normal setting, saved with the others), whether
 *  this PC is signed in and until when, and sign in / sign out. */
export function MetallicAccount({session, address, onAddressChange, disabled = false}: {
  session: MetallicSession
  /** draft.metallic_control_url */
  address: string
  onAddressChange: (value: string) => void
  /** The unconnected preview. */
  disabled?: boolean
}) {
  const {status, signedIn, ended} = session
  const saved = status?.control_url || ''
  // An empty field with a working address means the address comes from STAR_METALLIC_CONTROL_URL.
  const unsaved = address.trim() !== '' && address.trim().replace(/\/+$/, '') !== saved
  const expires = signedIn && status?.expires_at ? status.expires_at : null
  return (
    <div className="metallic-account">
      <label className="metallic-field">
        <span>Metallic Control address</span>
        <input type="url" value={address} placeholder="http://metallic-control.local:8470" spellCheck={false} autoComplete="off"
          onChange={event => onAddressChange(event.target.value)} disabled={disabled} />
      </label>
      {unsaved && <small className="metallic-hint">Save settings before signing in, so STAR uses this address.</small>}
      <p className="metallic-status-line" role="status">
        {signedIn
          ? expires ? `Signed in to Metallic until ${clockTime(expires, true)} (${untilText(expires)}).` : 'Signed in to Metallic.'
          : ended ? 'Your Metallic sign-in ended. Sign in again to see Metallic.' : 'Not signed in. STAR works the same without Metallic.'}
        {status && !status.secure_store && signedIn ? ' This PC cannot encrypt the sign-in, so it lasts until STAR closes.' : ''}
      </p>
      {signedIn
        ? <button type="button" className="secondary-button metallic-signout" onClick={() => void session.signOut()} disabled={disabled}>
            <LogOut size={14} aria-hidden="true" /> Sign out of Metallic
          </button>
        : status?.configured
          ? <MetallicCodeForm status={status} onSignedIn={session.signedInWith} disabled={disabled} />
          : <small className="metallic-hint">Enter the address and save settings to sign in.</small>}
    </div>
  )
}
