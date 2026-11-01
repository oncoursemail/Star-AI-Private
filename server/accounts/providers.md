# Metallic accounts: turning on Google, Microsoft, Discord, GitHub, GitLab, Steam and passkeys

Owner steps. Each provider is off until its client ID is in the server's private config. Client secrets never go in
the repo: they live in files on the accounts container and on the owner's PC under `~/.metallic/accounts/`.

## How the redirect works
The launcher opens the system browser (RFC 8252, no embedded password pages) and receives the answer on a loopback
address on the player's own PC:

| Provider | Redirect URI to register | Notes |
|---|---|---|
| Google | none (Desktop app clients accept any `http://127.0.0.1:<port>`) | |
| Microsoft | `http://localhost` (any port is accepted for localhost) | the launcher uses `http://localhost:<port>/callback` |
| Discord | `http://127.0.0.1:47615/callback` | exact match required |
| GitHub | `http://127.0.0.1:47615/callback` | GitHub accepts other loopback ports too |
| GitLab | `http://127.0.0.1:47615/callback` | exact match required |
| Steam | nothing to register (OpenID 2.0); return_to is `http://127.0.0.1:47615/callback?state=...` | |

Port 47615 must be free on the player's PC for Discord, GitLab, Steam and passkeys (the launcher says so if it is not).

## 1. Google (Google Cloud console)
1. https://console.cloud.google.com/ > create or pick a project "Metallic".
2. APIs & Services > OAuth consent screen: User type External; app name Metallic; support email; scopes `openid`,
   `.../auth/userinfo.email`, `.../auth/userinfo.profile`; add yourself as a test user (or publish the app).
3. APIs & Services > Credentials > Create credentials > OAuth client ID > Application type **Desktop app**, name
   "Metallic Launcher". No redirect URI is needed.
4. Copy the Client ID and the client secret (for Desktop apps Google calls it a secret but it is not confidential;
   it still goes only in the server file).

## 2. Microsoft (Azure portal / Microsoft Entra ID)
1. https://portal.azure.com/ > Microsoft Entra ID > App registrations > New registration.
2. Name "Metallic"; Supported account types: **Accounts in any organizational directory and personal Microsoft
   accounts**.
3. Redirect URI: platform **Public client/native (mobile & desktop)**, value `http://localhost`. Register.
4. API permissions: Microsoft Graph delegated `openid`, `email`, `profile` (usually present by default).
5. Copy the Application (client) ID. No secret is needed (public client + PKCE).
   Microsoft email addresses are never used to link accounts automatically (they are not always verified).

## 3. Discord (Discord developer portal)
1. https://discord.com/developers/applications > New Application "Metallic".
2. OAuth2 > Redirects > add `http://127.0.0.1:47615/callback` > Save.
3. Copy the Client ID; Reset Secret and copy the Client Secret. Scopes used: `identify email`.

## 4. GitHub (OAuth App)
1. https://github.com/settings/developers > OAuth Apps > New OAuth App (or under the organisation's settings).
2. Application name Metallic; Homepage URL `https://metallic.club`; Authorization callback URL
   `http://127.0.0.1:47615/callback`. Register.
3. Copy the Client ID; Generate a new client secret and copy it. Scopes used: `read:user user:email`.

## 5. GitLab (gitlab.com, or a self-hosted GitLab with `base_url`)
1. https://gitlab.com/-/user_settings/applications > Add new application.
2. Name Metallic; Redirect URI `http://127.0.0.1:47615/callback`; **Confidential: unchecked** (PKCE public client);
   scopes `openid`, `profile`, `email`. Save.
3. Copy the Application ID (and the Secret if you chose Confidential).

## 6. Steam
OpenID 2.0 needs no app. For display names, get a Steam Web API key at https://steamcommunity.com/dev/apikey (domain
name: `metallic.club`). Optional: without it, new Steam players just type a username.

## 7. Passkeys (Windows Hello / security keys)
Nothing to register. Today the relying-party ID is `localhost` and the passkey page is served by the launcher at
`http://localhost:47615/passkey`, because WebAuthn does not allow a LAN IP address as an RP ID. When Metallic has its
own domain with a real certificate, set `webauthn_rp_id = "metallic.club"` and `webauthn_origins =
["https://accounts.metallic.club"]` (passkeys made for `localhost` must then be added again).

## 8. Put the values on the server
On the PC, create `~/.metallic/accounts/providers.toml` (never committed):

```toml
[providers.google]
client_id = "<google client id>"
client_secret_file = "/etc/metallic-accounts/providers/google.secret"

[providers.microsoft]
client_id = "<application (client) id>"

[providers.discord]
client_id = "<discord client id>"
client_secret_file = "/etc/metallic-accounts/providers/discord.secret"

[providers.github]
client_id = "<github client id>"
client_secret_file = "/etc/metallic-accounts/providers/github.secret"

[providers.gitlab]
client_id = "<gitlab application id>"
# base_url = "https://gitlab.example.org"   # only for a self-hosted GitLab
# client_secret_file = "/etc/metallic-accounts/providers/gitlab.secret"   # only if Confidential

[providers.steam]
enabled = true
# web_api_key_file = "/etc/metallic-accounts/providers/steam.secret"
```

and one file per secret next to it: `~/.metallic/accounts/google.secret`, `discord.secret`, `github.secret`
(`gitlab.secret`, `steam.secret` if used), each holding only the value. Then:

```
MA_B1=<user>@<brain1> MA_CT=metallic-accounts-test bash server/accounts/deploy.sh providers
```

It copies them into the container (root:maccounts 0640), points `providers_file` at them and restarts the service. The
launcher shows only the providers whose client ID is set (`GET /v1/providers`).
