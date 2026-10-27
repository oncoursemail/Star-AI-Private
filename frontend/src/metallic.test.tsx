// @vitest-environment jsdom
import {afterEach, beforeAll, beforeEach, describe, expect, it, vi} from 'vitest'
import {cleanup, render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {initializeBridge} from './bridge'
import {installFakeDesktop, type FakeDesktop} from './fake-desktop'
import {SignIn} from './SignIn'
import {MetallicAccount} from './MetallicAccount'
import {MetallicSection} from './MetallicSection'
import {metallicFixtureReply} from './metallicFixtures'
import {useMetallicStatus, type MetallicStatus} from './metallic'

let desktop: FakeDesktop
beforeAll(async () => { desktop = installFakeDesktop(); await initializeBridge() })
beforeEach(() => {
  desktop.reset()
  desktop.onAction('metallicSignIn', () => ({ok: true, pending: true}))
  desktop.onAction('metallicAccountSignIn', () => ({ok: true, pending: true}))
  desktop.onAction('metallicState', () => ({ok: true, pending: true}))
})
afterEach(() => cleanup())

const now = () => Math.round(Date.now() / 1000)
const ADDRESS = 'http://metallic-control.local:8470'
const signedOut: MetallicStatus = {signed_in: false, expires_at: null, configured: true, control_url: ADDRESS, locked_until: null, secure_store: true}
const withAccounts: MetallicStatus = {...signedOut, accounts_configured: true}
const signedIn = (): MetallicStatus => ({...signedOut, signed_in: true, expires_at: now() + 8 * 3600})

/** What Desktop does: one session, the sidebar entry only while signed in, the section and the Settings block. */
function Harness({initial, show = 'section'}: {initial: MetallicStatus; show?: 'section' | 'account'}) {
  const session = useMetallicStatus(initial, false)
  return <div className="shell">
    <nav>{session.signedIn ? <button type="button">Metallic entry</button> : <span>No Metallic entry</span>}</nav>
    {show === 'section' ? <MetallicSection session={session} active /> : <MetallicAccount session={session} address={ADDRESS} onAddressChange={() => {}} />}
  </div>
}

async function submitCode(code: string) {
  await userEvent.type(screen.getByLabelText(/Metallic access code/), code)
  await userEvent.click(screen.getByRole('button', {name: /Sign in/}))
  await waitFor(() => expect(desktop.sent('metallicSignIn').length).toBeGreaterThan(0))
  return desktop.requestOf('metallicSignIn')
}

describe('Metallic sign-in screen', () => {
  it('continues into normal STAR without a code and without asking the host anything', async () => {
    const onDone = vi.fn()
    render(<div className="shell"><SignIn status={signedOut} onDone={onDone} onSignedIn={vi.fn()} /></div>)
    await userEvent.click(screen.getByRole('button', {name: 'Continue'}))
    expect(onDone).toHaveBeenCalledOnce()
    expect(desktop.sent('metallicSignIn')).toHaveLength(0)
  })

  it('shows the refusal with the tries left after a wrong code, and clears the field', async () => {
    const onSignedIn = vi.fn()
    render(<div className="shell"><SignIn status={signedOut} onDone={vi.fn()} onSignedIn={onSignedIn} /></div>)
    const id = await submitCode('not-the-code')
    expect(desktop.sent('metallicSignIn')[0].payload).toEqual({code: 'not-the-code'})
    await desktop.emitRaw(id, 'result', {ok: false, signed_in: false, error: 'wrong_code', message: 'Wrong code.', attempts_left: 3})
    expect((await screen.findByRole('alert')).textContent).toMatch(/did not accept that code\. 3 tries left/)
    expect((screen.getByLabelText(/Metallic access code/) as HTMLInputElement).value).toBe('')
    expect(onSignedIn).not.toHaveBeenCalled()
  })

  it('shows the lockout time after the fifth wrong code and blocks further tries', async () => {
    render(<div className="shell"><SignIn status={signedOut} onDone={vi.fn()} onSignedIn={vi.fn()} /></div>)
    const id = await submitCode('wrong-again')
    await desktop.emitRaw(id, 'result', {ok: false, signed_in: false, error: 'wrong_code', message: 'Wrong code.', attempts_left: 0, locked_until: now() + 900})
    expect((await screen.findByRole('alert')).textContent).toMatch(/Too many wrong codes\. Sign-in is locked until .+ \(in 15 min\)/)
    expect((screen.getByLabelText(/Metallic access code/) as HTMLInputElement).disabled).toBe(true)
    expect((screen.getByRole('button', {name: /Sign in/}) as HTMLButtonElement).disabled).toBe(true)
  })

  it('reports a right code through onSignedIn and leaves the screen', async () => {
    const onSignedIn = vi.fn()
    const onDone = vi.fn()
    render(<div className="shell"><SignIn status={signedOut} onDone={onDone} onSignedIn={onSignedIn} /></div>)
    const id = await submitCode('the-right-code')
    const expires = now() + 8 * 3600
    await desktop.emitRaw(id, 'result', {ok: true, signed_in: true, expires_at: expires, message: 'Signed in.'})
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(expect.objectContaining({ok: true, expires_at: expires})))
    expect(onDone).toHaveBeenCalledOnce()
  })
})

describe('Metallic section', () => {
  it('hides the content and the sidebar entry when the stored status is already expired', () => {
    render(<Harness initial={{...signedOut, signed_in: true, expires_at: now() - 5}} />)
    expect(screen.getByText('Your Metallic sign-in ended')).toBeTruthy()
    expect(screen.getByText('No Metallic entry')).toBeTruthy()
    expect(desktop.sent('metallicState')).toHaveLength(0)
  })

  it('signs out at once when Metallic Control says the token expired', async () => {
    render(<Harness initial={signedIn()} />)
    expect(screen.getByRole('button', {name: 'Metallic entry'})).toBeTruthy()
    await waitFor(() => expect(desktop.sent('metallicState')).toHaveLength(1))
    expect(desktop.sent('metallicState')[0].payload).toEqual({range: 'hour'})
    await desktop.emitRaw(desktop.requestOf('metallicState'), 'result', {reachable: true, signed_in: false, expired: true, message: 'Your Metallic sign-in ended. Sign in again.'})
    expect(await screen.findByText('Your Metallic sign-in ended')).toBeTruthy()
    expect(screen.getByText('No Metallic entry')).toBeTruthy()
  })

  it('shows "Not reachable from here" with the address and retries on request', async () => {
    render(<Harness initial={signedIn()} />)
    await waitFor(() => expect(desktop.sent('metallicState')).toHaveLength(1))
    await desktop.emitRaw(desktop.requestOf('metallicState'), 'result', {reachable: false, signed_in: true, message: 'Metallic Control did not answer.'})
    const panel = (await screen.findByRole('heading', {name: 'Not reachable from here'})).parentElement!
    expect(within(panel).getByText(ADDRESS)).toBeTruthy()
    expect(screen.getByRole('button', {name: 'Metallic entry'})).toBeTruthy()
    await userEvent.click(within(panel).getByRole('button', {name: /Try again/}))
    await waitFor(() => expect(desktop.sent('metallicState')).toHaveLength(2))
  })

  it('draws the stats charts with labelled axes and a legend from the data', async () => {
    const {container} = render(<Harness initial={signedIn()} />)
    await waitFor(() => expect(desktop.sent('metallicState')).toHaveLength(1))
    await desktop.emitRaw(desktop.requestOf('metallicState'), 'result', metallicFixtureReply('signed', 'hour'))
    // Projects first: forge repositories and dev PC projects merged into one list.
    expect(await screen.findByRole('heading', {name: 'Star-AI-Private'})).toBeTruthy()
    expect(screen.getByRole('heading', {name: 'Obby Builder'})).toBeTruthy()
    await userEvent.click(screen.getByRole('tab', {name: 'Stats'}))
    const cpu = screen.getByText('CPU busy by machine').closest('figure')!
    expect(within(cpu).getByText('% of all threads')).toBeTruthy()
    expect(within(cpu).getByText('Local time')).toBeTruthy()
    expect(within(cpu).getAllByText('Brain 1').length).toBeGreaterThan(0)
    expect(within(cpu).getByRole('img').getAttribute('aria-label')).toMatch(/Brain 1: latest \d+ %/)
    expect(cpu.querySelectorAll('.recharts-line').length).toBe(3)
    expect(screen.getByText(/tokens per second \(median\)/)).toBeTruthy()
    expect(screen.getByText(/First-try pass rate per hour/)).toBeTruthy()
    expect(container.querySelector('.metallic-chart-empty')).toBeNull()
    // The range switch asks again for the new range.
    await userEvent.click(screen.getByRole('radio', {name: 'Last week'}))
    await waitFor(() => expect(desktop.sent('metallicState').at(-1)?.payload).toEqual({range: 'week'}))
  }, 60000)

  it('says plainly when no eval history is reported', async () => {
    const reply = metallicFixtureReply('signed', 'day')
    for (const brain of Object.values(reply.state!.star!.brains!)) delete brain.night_school!.hours
    render(<Harness initial={signedIn()} />)
    await waitFor(() => expect(desktop.sent('metallicState')).toHaveLength(1))
    await desktop.emitRaw(desktop.requestOf('metallicState'), 'result', reply)
    await userEvent.click(await screen.findByRole('tab', {name: 'Stats'}))
    expect(screen.getByText(/No eval history is reported/)).toBeTruthy()
  }, 60000)
})

describe('Settings > Account & Metallic', () => {
  it('signs out through the host and reports signed out at once', async () => {
    desktop.onAction('metallicSignOut', () => ({ok: true, data: signedOut}))
    render(<Harness initial={signedIn()} show="account" />)
    expect(screen.getByRole('status').textContent).toMatch(/Signed in to Metallic until/)
    await userEvent.click(screen.getByRole('button', {name: /Sign out of Metallic/}))
    expect(desktop.sent('metallicSignOut')).toHaveLength(1)
    expect(screen.getByRole('status').textContent).toMatch(/Not signed in/)
    expect(screen.getByText('No Metallic entry')).toBeTruthy()
    expect(screen.getByLabelText(/Metallic access code/)).toBeTruthy()
  })
})

describe('Metallic account sign-in (one account system, access code as the fallback)', () => {
  const fill = async (user: string, password: string) => {
    await userEvent.type(screen.getByLabelText('Metallic username'), user)
    await userEvent.type(screen.getByLabelText('Metallic password'), password)
    await userEvent.click(screen.getByRole('button', {name: 'Sign in'}))
    await waitFor(() => expect(desktop.sent('metallicAccountSignIn').length).toBeGreaterThan(0))
  }

  it('offers only the access code while no accounts address is set', () => {
    render(<div className="shell"><SignIn status={signedOut} onDone={vi.fn()} onSignedIn={vi.fn()} /></div>)
    expect(screen.getByLabelText(/Metallic access code/)).toBeTruthy()
    expect(screen.queryByRole('group', {name: 'Sign in with'})).toBeNull()
    expect(screen.queryByLabelText('Metallic username')).toBeNull()
  })

  it('opens on the account form when an accounts address is set, and switches to the code and back', async () => {
    render(<div className="shell"><SignIn status={withAccounts} onDone={vi.fn()} onSignedIn={vi.fn()} /></div>)
    expect(screen.getByLabelText('Metallic username')).toBeTruthy()
    expect(screen.queryByLabelText(/Metallic access code/)).toBeNull()
    await userEvent.click(screen.getByRole('button', {name: 'Access code'}))
    expect(screen.getByLabelText(/Metallic access code/)).toBeTruthy()
    expect(screen.queryByLabelText('Metallic username')).toBeNull()
    await userEvent.click(screen.getByRole('button', {name: 'Metallic account'}))
    expect(screen.getByLabelText('Metallic password')).toBeTruthy()
  })

  it('sends the username and password once, clears the password after a refusal and says why', async () => {
    const onSignedIn = vi.fn()
    render(<div className="shell"><SignIn status={withAccounts} onDone={vi.fn()} onSignedIn={onSignedIn} /></div>)
    await fill('alex', 'wrong-password-1')
    expect(desktop.sent('metallicAccountSignIn')[0].payload).toEqual({username: 'alex', password: 'wrong-password-1'})
    await desktop.emitRaw(desktop.requestOf('metallicAccountSignIn'), 'result', {ok: false, signed_in: false, error: 'wrong_login', message: ''})
    expect((await screen.findByRole('alert')).textContent).toMatch(/Wrong username or password\./)
    expect((screen.getByLabelText('Metallic password') as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('Metallic username') as HTMLInputElement).value).toBe('alex')
    expect(onSignedIn).not.toHaveBeenCalled()
  })

  it('asks for the 2FA code when the account has one, then sends it with the same password', async () => {
    const onSignedIn = vi.fn()
    const onDone = vi.fn()
    render(<div className="shell"><SignIn status={withAccounts} onDone={onDone} onSignedIn={onSignedIn} /></div>)
    await fill('alex', 'right-password-1')
    await desktop.emitRaw(desktop.requestOf('metallicAccountSignIn'), 'result', {ok: false, signed_in: false, error: 'otp_required', message: ''})
    const code = await screen.findByLabelText('6-digit code from your authenticator app')
    await userEvent.type(code, '123456')
    await userEvent.click(screen.getByRole('button', {name: 'Sign in'}))
    await waitFor(() => expect(desktop.sent('metallicAccountSignIn')).toHaveLength(2))
    expect(desktop.sent('metallicAccountSignIn')[1].payload).toEqual({username: 'alex', password: 'right-password-1', otp: '123456'})
    const expires = now() + 8 * 3600
    await desktop.emitRaw(desktop.sent('metallicAccountSignIn')[1].requestId, 'result', {ok: true, signed_in: true, expires_at: expires, message: 'Signed in.'})
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(expect.objectContaining({ok: true, expires_at: expires})))
    expect(onDone).toHaveBeenCalledOnce()
  })

  it('can use a recovery code instead of the authenticator code', async () => {
    render(<div className="shell"><SignIn status={withAccounts} onDone={vi.fn()} onSignedIn={vi.fn()} /></div>)
    await fill('alex', 'right-password-1')
    await desktop.emitRaw(desktop.requestOf('metallicAccountSignIn'), 'result', {ok: false, signed_in: false, error: 'otp_required', message: ''})
    await userEvent.click(await screen.findByRole('button', {name: 'Use a recovery code instead'}))
    await userEvent.type(screen.getByLabelText('Recovery code'), 'abcde-12345')
    await userEvent.click(screen.getByRole('button', {name: 'Sign in'}))
    await waitFor(() => expect(desktop.sent('metallicAccountSignIn')).toHaveLength(2))
    expect(desktop.sent('metallicAccountSignIn')[1].payload).toEqual({username: 'alex', password: 'right-password-1', recovery_code: 'abcde-12345'})
  })

  it('names the cases an owner can fix: not an owner or admin, accounts offline, certificate mismatch', async () => {
    render(<div className="shell"><SignIn status={withAccounts} onDone={vi.fn()} onSignedIn={vi.fn()} /></div>)
    const cases: [string, RegExp][] = [
      ['not_allowed', /Only owner and admin accounts can/],
      ['accounts_unreachable', /Metallic accounts did not answer/],
      ['bad_certificate', /certificate does not match the fingerprint/],
    ]
    for (const [i, [error, text]] of cases.entries()) {
      if (i === 0) await userEvent.type(screen.getByLabelText('Metallic username'), 'sam')
      await userEvent.type(screen.getByLabelText('Metallic password'), 'some-password-1')
      await userEvent.click(screen.getByRole('button', {name: 'Sign in'}))
      await waitFor(() => expect(desktop.sent('metallicAccountSignIn')).toHaveLength(i + 1))
      await desktop.emitRaw(desktop.sent('metallicAccountSignIn')[i].requestId, 'result', {ok: false, signed_in: false, error, message: ''})
      expect((await screen.findByRole('alert')).textContent).toMatch(text)
    }
  })

  it('shows the accounts address and fingerprint fields in Settings and passes edits on', async () => {
    const onAccounts = vi.fn()
    const onFingerprint = vi.fn()
    const Settings = () => {
      const session = useMetallicStatus(withAccounts, false)
      return <div className="shell"><MetallicAccount session={session} address={ADDRESS} onAddressChange={() => {}}
        accountsAddress="" onAccountsAddressChange={onAccounts} fingerprint="" onFingerprintChange={onFingerprint} /></div>
    }
    render(<Settings />)
    await userEvent.type(screen.getByLabelText(/Metallic accounts address/), 'h')
    expect(onAccounts).toHaveBeenCalledWith('h')
    await userEvent.type(screen.getByLabelText(/certificate fingerprint/), 'a')
    expect(onFingerprint).toHaveBeenCalledWith('a')
    expect(screen.getByLabelText('Metallic username')).toBeTruthy()
  })
})
