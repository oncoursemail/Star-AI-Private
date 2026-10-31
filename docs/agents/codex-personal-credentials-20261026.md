# STAR's own saved passwords: host helper

The owner authorized STAR to remember and reuse passwords for her own accounts.
`star/personal_credentials.py` implements the storage/fill helper for that flow.
It is deliberately separate from model tools and computer-control permissions.
The existing host password block and account-creation gates remain in place
pending independent integration review. **No actual passwords were saved and
no account was created or signed in during this work.**

## Host API

- `PersonalCredentials.create(https_origin)` generates a random 32-character
  password in the host, stores it in the native OS vault, and returns only
  `CredentialRef(credential_id, origin)`. Length can be 24–128 characters. The
  generated value includes upper/lowercase letters, digits and symbols.
- Persist that reference in owner-local settings outside source control. A new
  helper instance can reuse it after restart; no plaintext metadata/password file
  is created by this module.
- `fill(ref, observe=host_observer, fill_password=host_sink)` retrieves only the
  matching STAR entry. The observer must independently verify the current page
  and field. It supplies a `PasswordTarget` with exact top-level and field HTTPS
  origins, an opaque field identifier, password input type, visible/enabled/focused
  flags, and a monotonic timestamp no more than two seconds old. Validation runs
  immediately before the password is passed to the sink.
- The sink fills just that verified field and returns `True`. It must keep the
  page/field stable, avoid shared clipboards and logging, and never submit or
  navigate. Its result and exception details are never passed to the caller.
  The public result is only `FillReceipt(credential_id, origin, filled)`.

The observer and sink are **trusted host implementation hooks**. Passing a Python
callback does not authenticate it, establish trustworthy DOM/UIA evidence, defeat
malicious code in the process, or make navigation/fill atomic. The independently
reviewed browser/host adapter must enforce those boundaries. There is no exposed
reveal/export/list/import API and no model-facing password parameter.

## Storage and origin binding

`OSPersonalSecrets` reuses `OSProfileSecrets`' native-backend allowlist from
`star/bulk_profiles.py`. It uses a separate **STAR Personal Credentials v1** service
and an opaque credential ID plus origin hash as the lookup account. Its record
also binds the password to the canonical origin. It never enumerates, reads or
copies the user's browser passwords or other services' saved credentials.
Unavailable/unsupported storage fails closed; there is no plaintext fallback.

Only HTTPS origins are accepted. Scheme, hostname and nondefault port must match
exactly; default port 443 and case normalize canonically. Paths are ignored for
origin comparison. Userinfo, backslashes, controls/whitespace, Unicode/escaped
authorities, trailing dots and browser-ambiguous numeric hosts are rejected.
Cross-origin embedded fields, suffix lookalikes and port changes cannot receive
the saved password through this API.

Generated passwords exist temporarily as Python strings in host memory. Clearing
local references is not guaranteed memory zeroization. OS storage also does not
protect against a compromised host process or account. Site-specific password
requirements and MFA/CAPTCHA flows are not implemented here.

## Verification

73 standalone fake-store checks passed outside the repository's owned test
harness: generation and uniqueness, metadata-only results, restart reuse, exact
origins, iframe/suffix/port mismatches, malformed URLs, field flags/type, stale and
nonfinite timestamps, tampered references, sanitized errors, unsupported storage,
and rejecting secret-bearing sink results. Ruff, compilation and diff checks
passed. No harness files changed and no real keyring was used by those checks.

`python -m star.personal_credentials status` only checks whether an allowed native
backend is available; it does not read or write credentials. On this development
runtime it reported unavailable. `python -m star.personal_credentials simulate`
uses a temporary in-memory store and reports zero real passwords saved. Neither
command accepts a password argument or prints a generated password.

## Microsoft primary references checked 2026-10-25 (America/Chicago)

- [Handling passwords](https://learn.microsoft.com/en-us/windows/win32/secbp/handling-passwords)
  recommends Windows Credential Manager for OS-managed credential storage.
- [CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)
  stores a credential in the current user's credential set; STAR uses its
  existing keyring abstraction rather than introducing a plaintext store.
- [Credential Guard considerations](https://learn.microsoft.com/en-us/windows/security/identity-protection/credential-guard/considerations-known-issues)
  explains that generic application credentials are outside Credential Guard's
  protection. This helper therefore makes no claim of hardware isolation or
  protection from arbitrary software running as the same user.
