# Talk to STAR on Discord: setup (owner only)

STAR uses its **own Discord bot** (an application with a bot token). It never logs into, or
automates, your personal Discord account: self-bots break Discord's terms and are not supported.
The bot answers **only your Discord user ID**, in DMs and in the server you approve.

Time needed: about 10 minutes.

## 1. Create the bot in the Developer Portal

1. Open <https://discord.com/developers/applications> and click **New Application**. Name it `STAR`.
2. **Installation** tab
   - Installation Contexts: tick **Guild Install** only (untick User Install).
   - Install Link: choose **None** (you will use the link in step 3; Discord requires this before the
     bot can be made private).
3. **Bot** tab
   - Turn **Public Bot OFF**, so only you can add it to a server.
   - Privileged Gateway Intents: leave **Presence**, **Server Members** and **Message Content** all
     **OFF**. STAR does not need them: slash commands and DMs to the bot work without them, and the
     bot never reads your server conversations.
   - Click **Reset Token**, then **Copy**. Do not paste it anywhere except the file in step 2 below.
4. **General Information** tab: copy the **Application ID** (needed for the invite link).

## 2. Put the token and your IDs on this PC (never in Git, never in a chat)

1. Open Notepad and create `%USERPROFILE%\.star\discord.env` with one line:

   ```
   DISCORD_BOT_TOKEN=paste-the-token-here
   ```

   Save it (File > Save as, "All files", name `discord.env`). This file is the only place the token lives.
2. In Discord: **User Settings > Advanced > Developer Mode** on. Right-click your own name >
   **Copy User ID**; right-click your server icon > **Copy Server ID**.
3. Open `%USERPROFILE%\.star\discord-settings.env` (created for you the first time you run
   `scripts\star_discord.cmd doctor` or start the bot, if the file is missing; an existing file is never
   overwritten; the template is in `star/discord_bot/local_config.py`) and fill in:

   ```
   DISCORD_OWNER_ID=<your user ID>
   DISCORD_GUILD_ID=<your server ID>
   ```

   The other lines are the opt-in switches (see the table below).

## 3. Invite the bot with only the permissions it needs

Replace `APP_ID` with your Application ID and open the link while logged into Discord:

```
https://discord.com/oauth2/authorize?client_id=APP_ID&scope=bot+applications.commands&permissions=52224&integration_type=0
```

`52224` = View Channels, Send Messages, Embed Links, Attach Files. Nothing else: no Administrator,
Manage Server, Manage Roles, Manage Messages, Mention Everyone or Read Message History.

Optional, only if you want STAR's voice features (`/star speak`, `/star join` and `/star say`): use
`permissions=70368747375616` instead (adds Connect, Speak and Send Voice Messages).

## 4. Start it

From the STAR checkout, in cmd (PowerShell scripts are not needed):

```
scripts\star_discord.cmd doctor     offline check: shows what is set up, never prints the token
scripts\star_discord.cmd smoke      live check: logs in, confirms the bot and your server; sends nothing
scripts\star_discord.cmd            run the bot (stop with Ctrl+C)
```

On the first start keep `STAR_DISCORD_SYNC_COMMANDS=global` so Discord learns the slash commands
(in your server and in your DM with the bot). After that first good start, set it to `0`.

The bot uses the **same model STAR Desktop uses** (Settings > model / fast model; vision model for
images), including the STAR Brain server when that is your provider. Choose those in STAR Desktop first.

## 4b. Start it automatically (optional)

Running the bot in a terminal tab works, but it stops when the tab closes. There are two ways to keep it
running. Pick one; both are off until you switch them on.

**Only one bot runs at a time.** The bot takes a lock file in `%USERPROFILE%\.star` when it starts, so a second
start (terminal, STAR Desktop or Task Scheduler) exits at once instead of answering every message twice.
A bot started before this feature existed does not take the lock: restart it once with the current code
(Ctrl+C, then `scripts\star_discord.cmd`) before you turn on either option below.

### A. With STAR Desktop (Settings > Discord)

Settings > Discord shows the bot's state (Connected, Starting, Not configured, Error, or Running in another
window), a Start and a Stop button, and the switch **Start the Discord bot with STAR** (off by default).

- With the switch on, STAR starts the bot a few seconds after it opens, starts it again after a crash (waiting
  5, 10, 20, 40, 80, 160 and then 300 seconds between tries; a run of two minutes or more resets this), and
  stops it when STAR closes. After 10 quick crashes in a row it gives up and says so; press Start to try again.
- A wrong configuration (exit code 2) or a missing Discord library (exit code 3) is not retried: the page says
  what to fix.
- The page never shows the token, your Discord IDs or the server key. The bot reads the token and IDs from
  `discord.env` / `discord-settings.env` and the STAR Server key from STAR's saved key (Windows credential
  store) or, failing that, `%USERPROFILE%\.star\server_api_key`. "Not configured" lists which setting is missing.
- Turning the switch off leaves a running bot alone (use Stop). If the bot already runs in a terminal or in Task
  Scheduler, STAR shows "Running in another window", starts nothing, and takes over only if that bot stops.
- Logs are in STAR's log folder (`%APPDATA%\STAR\logs`): `discord-bot.log` (rotating, 1 MB x 4) and
  `discord-bot-console.log` (start-up errors).
- Which Python runs the bot: `STAR_DISCORD_PYTHON` if set, else the Python STAR itself runs on when it has
  discord.py, else `.venv` in the checkout, else `discord-venv` in STAR's data folder. The installed (packaged)
  STAR cannot run the bot by itself: set `STAR_DISCORD_PYTHON` (a Python with `requirements-discord.txt`) and
  `STAR_CHECKOUT` (a STAR checkout) as Windows user environment variables.
- If STAR is killed without closing (crash, Task Manager), the bot keeps running; the next STAR start shows it as
  running in another window.

### B. At Windows sign-in, without STAR Desktop (Task Scheduler)

`scripts\star_discord_autostart.cmd` creates one scheduled task, **STAR Discord bot**, for your account. You run it
yourself; nothing installs it for you. It needs no PowerShell and no administrator rights, and stores no password.

```
scripts\star_discord_autostart.cmd print     show the task without creating anything
scripts\star_discord_autostart.cmd install   create (or replace) the task
scripts\star_discord_autostart.cmd status    is it installed, when did it last run
scripts\star_discord_autostart.cmd start     run it now         stop    end the running task
scripts\star_discord_autostart.cmd remove    delete the task
```

The task runs 30 seconds after you sign in, in your own session (`InteractiveToken`, ordinary rights), with
`pythonw.exe` so no console window appears, and Windows restarts it up to 99 times a minute apart if it fails.
It uses the Python found by the script (`STAR_DISCORD_PYTHON`, else `.venv` in the checkout, else `py -3.12`),
so run the script from the checkout you want to keep (after the code is merged, a stable one, not a temporary
worktree) and install `requirements-discord.txt` into that Python first. The log is the same `discord-bot.log`.
The task only runs while you are signed in; "run whether signed in or not" would need your Windows password
and is deliberately not used. Use A or B, or both: if both start, the second one steps aside.

### C. Run it on a STAR server (24/7, without the PC)

`server/discord/deploy.sh` runs the bot as a systemd service (`star-discord.service`) inside a STAR server's
LXD container (brain 2; not the model server). Run it from the checkout on the PC in Git Bash; the address is
yours to supply and is never stored in the repository:

```
export STAR_DISCORD_SSH=<user>@<LXD host address>
STAR_BRAIN_URL=http://<brain 1 LAN address>:8080/v1 bash server/discord/deploy.sh install   # code + venv + unit
bash server/discord/deploy.sh secrets    # copies ~/.star/discord.env, discord-settings.env, server_api_key
bash server/discord/deploy.sh doctor     # offline check on the server
```

Then move the bot: stop the PC bot first (Ctrl+C in its window, or Stop in STAR Desktop), run
`bash server/discord/deploy.sh start`, and check `bash server/discord/deploy.sh status` for
"STAR Discord bot connected (guild count: 1)". Finally create the file `%USERPROFILE%\.star\discord-runs-on-server`
(any text): while it exists every PC start (terminal, STAR Desktop, Task Scheduler) refuses to run a second copy.

- On the server: user `star-discord` (no login), code in `/opt/star/discord/releases/<commit>` with `current` and
  `previous` links, venv `/opt/star/discord/venv`, secrets in `/opt/star/discord/secrets` (folder 0700, files
  0600), STAR settings (brain address, model names) in `/opt/star/discord/state/star-ai/settings.json`. Logs go to
  the journal (`journalctl -u star-discord`). Restart on failure, started at boot, memory limit 512 MB.
- `deploy.sh install` again updates the code (restarts only a running bot); `deploy.sh rollback` swaps back to the
  previous release; `deploy.sh stop` / `start` / `status`.
- `/screen` answers that it needs the STAR app on the PC (`STAR_DISCORD_HOST=server`, set by the unit).
  Speech (`/star speak`, `/star hear`) needs the voice engines, which the server copy does not install.
  `/digest` over `STAR_DISCORD_LEARNING_REPORT_SSH` needs an ssh key on the server, which it does not have.

#### Drawing from the server: the STAR GPU worker on the PC

Pictures are still made on the PC's graphics card. A small worker on the PC connects **out** to the server with
your existing SSH key (`ssh <LXD host> lxc exec starai -- ... gpu_link relay`), so no port is opened on the PC and
nothing needs administrator rights. When a draw job arrives it starts ComfyUI on 127.0.0.1, makes the picture with
the same code as STAR Desktop's Create image, sends it back, and stops ComfyUI after 10 idle minutes. Jobs are
signed with a key only the bot and the worker hold (`~/.star/gpu-worker.key` = the server's
`secrets/gpu-worker.key`); the worker refuses unsigned, old or repeated jobs. One job at a time, prompt up to 1500
characters, picture up to 8 MB, owner-only as before. If the worker is not connected (PC off or asleep) the bot
answers at once: "My drawing GPU (your PC) is offline right now".

```
bash server/discord/deploy.sh secrets                  # creates ~/.star/gpu-worker.key and gpu-worker.env once
bash server/discord/deploy.sh stop; bash server/discord/deploy.sh start      # the bot reads the key at start
cd <checkout> && <discord venv>\Scripts\python.exe -m star.discord_bot.gpu_worker install   # task at sign-in
<discord venv>\Scripts\python.exe -m star.discord_bot.gpu_worker start      # run it now (hidden)
```

`gpu_worker status | stop | remove` show, end or delete the task "STAR GPU worker" (hidden, your account, ordinary
rights, restarted by Windows if it fails). The worker reconnects by itself after a network or server drop. Log:
`~/.star/gpu-worker.log` (job ids and timings only; no prompts, pictures or keys). The task runs the checkout it was
installed from (`-m star.discord_bot.gpu_worker run` in that folder).
- Back to the PC: `bash server/discord/deploy.sh stop`, then `ssh <host> lxc exec starai -- systemctl disable
  star-discord` (or it starts again at the server's next boot), delete `%USERPROFILE%\.star\discord-runs-on-server`,
  start the PC bot as before.

## 5. Use it

- **DM the bot** like a normal chat: click the bot in your server's member list > **Message**.
  It shows "typing…" while it thinks, answers long replies in several messages (code blocks kept
  intact), and remembers the last few turns for an hour (`/star reset` forgets them). Send `help` for
  a reminder.
- Attach **one photo or screenshot** to a DM (or use `/image`) and ask about it. Phone photos up to
  25 MB are fine: the bot shrinks them on the PC (longest side 1568 px, rotation fixed) before the
  vision model sees them. iPhone HEIC photos need `pillow-heif` (in `requirements-discord.txt`).
- Attach **two images** to an owner DM (first desired reference, second current STAR result), or use `/compare` with the two attachments. STAR produces a private local-vision critique and a proposed change list; images are normalized and not stored in chat history. A screenshot is not enough to judge motion, rig correctness, or real Studio test results.
- If `STAR_DISCORD_DM_LEARNING_CANDIDATES=1` is enabled and your previous DM was about an image, a follow-up like “I don’t like that” or “you messed up the animation” creates a review-only correction candidate, not automatic changes or training. You can also use `wrong: ...` or `remember correction: ...` explicitly.
- **Make an image**: DM `draw a dragon over a castle` (or `generate an image of ...`), or use
  `/draw prompt:`. The bot shows "Drawing…", then posts the PNG with its prompt. It is made exactly
  like STAR Desktop's **Create image**: ComfyUI on this PC (127.0.0.1 only) with FLUX.2 klein 4B on
  the graphics card. When ComfyUI is not running the bot starts the install STAR finds (the
  `media/ComfyUI` folder made by `MEDIA_HOME=<starai>/media bash scripts/media/setup_comfyui.sh all`,
  or `STAR_COMFY_HOME`), and stops it again after 10 quiet minutes. One picture at a time; the first
  picture after a start takes longest. Pictures are kept in `~/.star/discord-images/generated-images`.
- Slash commands: `/ask`, `/draw` (make an image), `/image` (look at an image), `/compare`, `/screen`,
  `/status`, `/working`, `/digest`, plus the `/star ...` group (research, speech, voice channel, reset, doctor).
  Questions such as `Hey Star, what are you working on?` get a **producer-reported** reply in the owner's DM
  (or a private `/working` reply), not a model guess. No active work is asserted without a fresh real report.

## Opt-in switches (`discord-settings.env`)

In code every switch is OFF unless set. The generated template turns on DM chat and images; lesson
candidates, screen capture and Night School DMs stay 0 until you change them.

| Switch | Default (if unset) | What it does |
|---|---|---|
| `STAR_DISCORD_DM_CHAT` | 0 (template sets 1) | Answer your DMs to the bot. |
| `STAR_DISCORD_DM_IMAGES` | 0 (template sets 1) | Look at images you send (DM or `/image`); needs a vision model in STAR Settings; refused for cloud providers. |
| `STAR_DISCORD_DM_LEARNING_CANDIDATES` | 0 | `remember: ...` in a DM proposes a lesson; you approve it in STAR Desktop; never trusted automatically. |
| `STAR_DISCORD_SCREEN_CAPTURE` | 0 | `/screen` lets STAR look at this PC's screen. **Every capture needs you to press "Capture my screen now"** (expires after 60 s, one capture per press). Nothing is saved; you see the capture privately. |
| `STAR_DISCORD_LEARNING_DM_OPT_IN` | 0 | DM a short Night School digest when the verified practice numbers change (at most one per 6 h); `/digest` shows it on demand. Report source: `STAR_DISCORD_LEARNING_REPORT_SSH` (your existing key login to the brain server) or `STAR_DISCORD_LEARNING_REPORT` (a local file). |
| `STAR_DISCORD_DRAW` | 1 | Make images (`draw ...` DMs, `/draw`) on this PC's graphics card. 0 = off; the bot then says so and how to turn it on. |
| `STAR_DISCORD_DRAW_ANYONE` | 0 | 1 = members of your approved server may use `/draw` too (rate-limited each). Strangers' DMs never reach the image engine. |
| `STAR_DISCORD_DRAW_TIMEOUT` | 420 | Seconds before a picture is cancelled in ComfyUI (30-900). |
| `STAR_DISCORD_MENTIONS` | 0 | 1 = answer `@STAR ...` in your approved server (draw requests and, for you, questions). Discord then sends the bot server message events; without the message-content intent it only sees the text of messages that mention it. |
| `STAR_DISCORD_HOST` | pc | `server` = the bot runs on a STAR server (section 4 C): drawing goes to the PC's STAR GPU worker, `/screen` answers that it needs the PC. |
| `STAR_DISCORD_RATE_LIMIT` | 30 | Requests per 10 minutes before STAR asks you to slow down. |
| `STAR_DISCORD_WORK_STATUS` | 0 | Enable read-only owner work pulse, once a trusted worker supervisor publishes reports on this bot host. No work begins automatically. |
| `STAR_DISCORD_WORK_REPORT` | empty | Absolute `.json` path to the latest trusted local worker snapshot on the bot host. No path may be supplied from Discord messages. |
| `STAR_DISCORD_LAB_STATUS` | 0 | Enable read-only owner Lab progress/screenshot reports from a trusted, pre-staged job receipt; does not control Studio or capture the host desktop. |
| `STAR_DISCORD_LAB_REPORT` | empty | Absolute path on the bot host to an operator-approved latest.json receipt and same-folder checked viewport/render screenshot. |
| `STAR_DISCORD_PRESENCE` | 0 | Optional bot-account activity while connected. Rotate only fixed, privacy-safe Playing/Watching labels. No activity is sent when off. |
| `STAR_DISCORD_PRESENCE_MINUTES` | 15 | Time between changes while online, 10–120 minutes. No rapid presence updates or changes inside `on_ready`. |
| `DISCORD_CHANNEL_IDS` | empty | Limit server use to these channels. |

## Optional live work pulse (coding, studying, testing, research)

The Discord bot is not allowed to invent its own background activities. `/working`,
`/star working`, `/star ask` with an explicit activity question, and normal owner DM
`Hey Star, what are you working on?` use a **read-only local JSON snapshot**, not
a conversation response from the model. If no configured recent worker receipt
exists, the bot will accurately say that current worker activity is unknown.

To enable it, configure the bot host's `discord-settings.env` with
`STAR_DISCORD_WORK_STATUS=1` and an **absolute** path under a trusted
private directory, e.g. `STAR_DISCORD_WORK_REPORT=C:\\StarState\\work-status.json`
on Windows or `/opt/star/discord/state/work-status.json` on Linux. The directory
and report must be writable by a trusted STAR supervisor and readable by the bot.
Never place the report under a web-served or world-writable folder. To turn it
off, set the flag to 0.

**The status feed isn't started by enabling the switch.** A real worker supervisor
must produce that JSON with `star.discord_bot.work_status.publish_work_report` or
an equivalent verified adapter on the **same host**. Connecting the Night School
engine, model agents on Brain 1, Studio/Blender on Brain 2 and remote relays
requires separate reviewed integration. No fake built-in data is provided.

Schema v1 example (illustrative only, **not** a real task receipt):

```json
{
  "version": 1,
  "updated_at": "2026-10-15T23:00:00Z",
  "workers": [
    {
      "id": "brain1-coder", "kind": "coding", "state": "working",
      "task": "Recheck Luau checker regressions",
      "last_step": "Reproduced three failures",
      "next_step": "Run verified test cases",
      "done": 3, "total": 8,
      "updated_at": "2026-10-15T22:59:55Z"
    }
  ]
}
```

The producer must refresh timestamps only after observing live work; the bot
expires a nonfinal work receipt after three minutes and stops describing it as
running. It never reads arbitrary host files, executes model-suggested jobs,
publishes private work to public channels or follows untrusted paths. Keep
reports at most 16 KiB / 12 worker entries and use private-data-free labels.
The presence rotator still uses fixed generic public labels and **does not**
claim anything about actual coding or studying.

For integration architecture, image quality and audio dubbing research, see
[STAR_DISCORD_LIVE_WORK_CREATIVE_DUBBING_20261015.md](research/STAR_DISCORD_LIVE_WORK_CREATIVE_DUBBING_20261015.md).

## Optional Studio Lab / Blender screenshot reports

STAR can answer `/star lab`, `/star labshot` and selected plain-language owner
DM questions about what the test Studio is doing, **only if an operator first
configures a trusted local job receipt**. This is NOT a new remote screen
capture tool. Nothing is fetched from Brain 2 unless an authorized Studio Lab
or Blender producer has already staged timestamped, checksum-matched evidence
on the bot host. Slash command results are private; image sending requires
an explicit owner command. See
[STAR_DISCORD_LAB_EVIDENCE_20261013.md](STAR_DISCORD_LAB_EVIDENCE_20261013.md)
for schema, security limits, integration and validation.

STAR's separate opt-in learning digest already sends owner DMs on meaningful
verified Night School changes when configured with a real report source.
These are practice results, not automatically trained neural weights or
unconditionally successful Roblox Studio builds.

## Optional bot-account activity

To show a simple STAR activity under its Discord bot profile, set `STAR_DISCORD_PRESENCE=1`
in `discord-settings.env` and restart the bot. Initially it displays
`Watching /star help`, then rotates (default every 15 minutes) through a small,
fixed set of privacy-safe activities such as `Playing STAR Intelligence`. Its
status is visible only while the bot is online. This does not change the
Discord application biography, send an MOTD, start any self-training job or
read guild messages. Use `/status` to see whether activity rotation is configured.

For privacy and reliability, activity labels cannot be generated by models or
Discord input. The bot starts the initial presence from its constructor, and
periodic changes run from a cancellable background task rather than the
repeatedly invoked Discord `on_ready` callback. Live verification still requires
the owner to start the bot and look at its actual Discord presence.

## What the bot will never do from Discord

No file writes, no Roblox Studio edits, no GitHub, no shell, no MCP tools, no passwords. Messages
and images sent to it are treated as untrusted data, never as permission. Strangers get no answer at all.

## If something is wrong

- `doctor` shows `[SETUP]` lines with the fix for each.
- `smoke` says the token was rejected: reset it in the Developer Portal and replace the line in `discord.env`.
- Slash commands missing: set `STAR_DISCORD_SYNC_COMMANDS=global`, start once, then set it back to `0`.
- To revoke everything: Developer Portal > Bot > Reset Token (the old token stops working at once),
  or remove the bot from your server.
