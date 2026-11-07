# Owner Minecraft sign-in rehearsal, 2026-10-26

The Minecraft launcher and the Mineflayer client have separate authentication
paths. Signing into the launcher alone does not authorize this client. Run this
rehearsal in the owner's console on STAR's dedicated PC after configuring one
server whose rules permit bots.

Preview reads the selected ordinary Home server configuration. It creates no
process, connects to no server, opens no authentication cache and reads no tokens:

```powershell
python -m star.games.minecraft_setup --home D:\STAR\home --server "Own world"
```

To connect, use the same command with `--connect`. The default timeout is 300
seconds; `--timeout` accepts one to nine hundred seconds. If Microsoft asks for
device-code sign-in, an interactive console displays the validated Microsoft URL
and short-lived user code. Open that URL yourself and choose STAR's intended
account. The helper never opens a browser, accepts a password or creates an
account. A redirected console hides the code unless the owner explicitly adds
`--show-login-code`; that option can expose the code to whatever captures stdout.

The child only polls connection events. It never receives chat, movement, skill
or model commands. Observing `spawn` sets `connected: true`, then closes the
rehearsal child. This confirms an observed spawn, not continued connection,
correct account ownership, conversational ability or independent play. Errors,
server termination, timeout, Ctrl+C and Home STOP also close it.
Raw server messages and exceptions never enter the result.

The selected profile must exactly match one unique enabled
`config.json` → `social.minecraft.servers` entry and have `allows_bots: true`.
The cache passed to NodeTransport is `<home>/auth/minecraft`, shared with the
inline Home configuration adapter. Existing symlinks/reparse points in those
cache directories are refused. This wrapper does not inspect, export or encrypt
the SDK's cached tokens; keep that private local folder out of source control,
reports and distribution packages. `child_closed` records successful return from
the transport's close method, not independent inspection of process exit.

Host integration:

```python
run_setup(home, profile, connect=False, timeout=300,
          transport_factory=None, clock=time.monotonic, sleep=time.sleep,
          stopped=None, emit_auth=None)
```

`profile` is a `MinecraftServer` or its flat configuration dictionary. The
injected factory receives `(server, auth_cache=...)`; only `poll()` and `close()`
are called. `emit_auth(uri, code)` is an explicitly trusted owner-console
callback. The callback is not authenticated by this helper and must not persist
or forward its arguments. The result never contains a URI, user code, token,
username, account label or raw error. Without a callback, a new challenge ends
with `owner_console_required`. There is no model-tool registration.

Only exact HTTPS Microsoft `link` and `devicelogin` display endpoints are
accepted, with `microsoft.com` or `www.microsoft.com`. Credentials, ports, query
strings, fragments, encoded/lookalike paths and foreign hosts are rejected.
Unsupported challenge formats stop the attempt; no guessed URL is opened.

`python scripts/verify_minecraft_setup.py` covers preview, profile binding,
challenge URL/code validation, console disclosure, spawn/termination, timeout,
STOP and cleanup using only temporary configuration and fake transports. No
account sign-in, Node process, authentication cache or real game was used here.

Primary references checked:

- [Microsoft device authorization flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code): the owner enters a short user code at the verification URI; tokens belong to the client flow. This helper delegates protocol polling to the existing library.
- [Prismarine Auth API](https://github.com/PrismarineJS/prismarine-auth/blob/master/docs/API.md): device-code callback and per-flow token cache.
- [Prismarine Auth device-code implementation](https://github.com/PrismarineJS/prismarine-auth/blob/master/src/TokenManagers/LiveTokenManager.js): the callback receives the service challenge. Its optional generated message is deliberately ignored here.
- [Mineflayer API](https://github.com/PrismarineJS/mineflayer/blob/master/docs/api.md): client connection and spawn events; these do not establish higher-level play success.
