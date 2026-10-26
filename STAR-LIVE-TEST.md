# Star: first session on her PC

Use this after STAR-FIRST-START.md. Run these commands in PowerShell from `D:\STAR\app`, replacing `D:\STAR` if you chose another folder. This is a source preview, with offline regression checks. A working microphone, game connection or model response must be demonstrated on her PC before relying on it.

## Keep the first session supervised

Set the Home folder for this PowerShell session:

```powershell
$env:STAR_HOME_DIR = 'D:\STAR\home'
& D:\STAR\venv\Scripts\python.exe -m star.home check
& D:\STAR\venv\Scripts\python.exe -m star.home acceptance --quick
```

Review `home\acceptance\latest.md`. Fix missing devices, failed imports and brain connectivity first. Keep `"dry_run": true` in `home\config.json` during preview. It permits planning and logs proposed actions while suppressing execution; it does not make model requests offline. Do not run two Home loops at once. Do not restart the separate brain evaluation server.

When you are present and ready to test real input, stop Home, preserve the other settings in `home\config.json`, change `"dry_run"` to `false`, and restart Home through its installed shortcut. That change enables actual actions. Use the full acceptance check while present:

```powershell
& D:\STAR\venv\Scripts\python.exe -m star.home acceptance
```

## Prove sight, sound and STOP

1. Open a harmless local window. Check that her description matches what is visible. Ask for a simple action and check the result. Covered windows are not visible through a screenshot.
2. Select her intended input/output devices. Check that she hears a short sentence, replies once, and can be interrupted. Confirm there is no room-mic leak, feedback or duplicate playback.
3. During speech, use **STAR STOP.cmd** or **Ctrl+Alt+Shift+F12**. Try it again while a game activity is running and while speech is being prepared. No late reply or continued game input should occur. If a native driver or application stays active, end the rehearsal and inspect it before resuming.
4. Resume only as the owner. Pending or failed cleanup keeps new activities blocked; removing the STOP file does not justify starting a second loop. After cleanup, check that a fresh activity works without replaying old speech.

The offline checks verify independent cleanup scheduling and late-output rejection. A blocked native call cannot be proven cancellable without testing that device. STOP is not a substitute for the owner's ability to close an application or disconnect audio.

## First game: a server that permits this client

Use an owner-approved Minecraft Java server where automated clients are allowed. Sign-in through the Minecraft launcher does not necessarily authorize this separate client. Preview a named profile, then repeat with `--apply` to save it:

```powershell
& D:\STAR\venv\Scripts\python.exe -m star.home configure --minecraft-name Practice --minecraft-host YOUR_SERVER_HOST --minecraft-user YOUR_ACCOUNT_LABEL --minecraft-auth microsoft --server-allows-bots
& D:\STAR\venv\Scripts\python.exe -m star.home configure --minecraft-name Practice --minecraft-host YOUR_SERVER_HOST --minecraft-user YOUR_ACCOUNT_LABEL --minecraft-auth microsoft --server-allows-bots --apply
```

Replace the host and account label locally. Do not enter a password. The selected profile becomes the first Home game profile; other saved profiles remain. Restart Home after applying configuration.

Authorize and test the connection separately while Home is stopped:

```powershell
& D:\STAR\venv\Scripts\python.exe -m star.games.minecraft_setup --home D:\STAR\home --server Practice
& D:\STAR\venv\Scripts\python.exe -m star.games.minecraft_setup --home D:\STAR\home --server Practice --connect --show-login-code
```

The first command is inert. The second may start the client and display a Microsoft device-code challenge in this owner console. Complete it yourself at the displayed official Microsoft address. Keep the code private. The helper closes the client after connection; it sends no chat or movement. A connection proves sign-in and server reachability, not autonomous gameplay. Home reuses the same local authentication cache.

Then start one Home loop. Observe a short game activity, a failed action, recovery and STOP. With willing participants, check incoming text, one reply and turn-taking. Verify delivery in the actual game; a generated reply or local friend-memory entry is not proof of delivery or an accepted friend request. Start with a short supervised session, then extend the duration only after checking CPU/GPU load, voice latency and cleanup.

## Social and streaming limits to resolve

Her Discord user-account adapter has not passed native acceptance. Discord's [normal-account automation policy](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots) forbids self-bots; it gives no desktop-automation exception. No bot account was substituted for the personal account you requested. Roblox's [third-party app policy](https://en.help.roblox.com/hc/en-us/articles/37924211313044-Creator-Third-Party-App-Policy) also restricts automated gameplay, friendship changes and initiated communication. Those platforms cannot be presented as completed unattended friendship paths.

Current friend memory tracks conversations and relationships locally. It does not verify immutable platform identities or send and confirm friend requests. The proactive contact planner is not connected to a delivery loop. Making new friends independently across arbitrary services remains unfinished.

Use STAR-FIRST-START.md for OBS source selection, local scene rehearsal and read-only Twitch chat. Public spoken Twitch replies are still unwired. Check every scene and audio route before broadcasting. Cat/dog motion modes exist; their new artwork is concept art awaiting layered production rigging.

After this session, keep the acceptance report and the relevant local action log. Record what actually worked, what failed, and device names without copying passwords, login codes or private conversations into GitHub. Personality and expression controls can be developed and tested; they do not establish human consciousness or feelings.
