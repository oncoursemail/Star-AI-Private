# home-wiring-20261026: STAR Home wiring, notifications + availability, Discord calls, invitations (Claude)

Branch `star/home-wiring-20261026` (worktree `worktrees/home-wiring`, from origin/star/next dff4a008), board item #261, PR into
`star/next`. Owner request 2026-10-26: STAR autonomous on her own PC, all abilities connected, answers DMs and calls like a person.
Everything below is tested on fakes only (`tests/test_home_wiring.py`, 54 tests). **Nothing ran on her PC, Discord, a real sound
device, a brain or a game.**

## What is wired (all in `star/home/` unless noted)
| piece | where |
|---|---|
| plug-in list: `star.games, social, play, senses, computer, watch, vtuber` (a missing package is skipped; a package that is installed but lacks a dependency is reported in `plugin_errors`) | `activities.py` PLUGIN_MODULES, `default_registry` |
| adapters for packages that predate the hook: social (Discord), play (Roblox, Minecraft), senses (calls) | `plugins.py` `register_social/play/senses`, `ADAPTERS` |
| shared runtime: host agent, friend memory, social chat, voice, inbox, attention, invite desk | `runtime.py` `Runtime`, `build()` (used by `python -m star.home run/once/check`) |
| HostAgent protocol on the Executor (focus window, foreground title, hold, key `/`) | `hostagent.py`, `host.py` `_a_focus_window/_a_hold/_a_foreground_title` |
| `bot.js` loads `skill_runner.js` (the two lines) | `star/games/mineflayer/bot.js` |
| voice `speak()` queue (False while she talks with someone) and per-game `GameMomentWindow` passed to the play loop as `voice_window`; the window also reaches a running call | `voicelink.py` `VoiceLine`, `HomeVoice.window_for`; used in `plugins.py` `play_roblox/play_minecraft` |
| Minecraft: one Mineflayer process, two readers (friend chat of star.games, skill loop of star.play) | `plugins.py` `_Tee` |
| social chat: mood and friend memory moved out of the system message into the new user message; mood = `emotion.directive(person=, partner_adult=)` (`emotion.note_line`), no numbers, romance wording only for a stated adult, opaque `friend-<id>`; system message identical across people | `star/social/chat.py` |
| loop emotion hook fixed (it passed a dict as the event kind, so it never did anything): verified outcome -> `creative_done` / `learned_something` / `task_success`, else `task_failure` (only if the engine is on); `took_a_break` once when the pause between sessions starts | `loop.py` `_emotion`, `_feel_outcome` |
| friend events: `friend_ignored` (her call not picked up), `talked_to_friend` (call ended, DM exchange); `insulted` / `sweet_message` come from `emotion.on_message` in social chat. Not emitted (no source sees them): `left_out`, `friend_left`, `reunion` | `calls.py`, `plugins.py`, `runtime.py` `feel` |
| star.watch (#643): `ensure_interest(life)`, `configure(speak=, chat=)`, and a pause shim: the watcher's sleep ends when she is needed, the video is paused with `k`, she resumes later. `hub=` is NOT passed (no hearing hub runs in STAR Home; she watches by captions or picture) | `plugins.py` `wire_watch` |
| star.vtuber (#649): plug-in, `attach_speaker` on her speaker for lip-sync (a broken camera returns the plain speaker), `emit_event("friend_joined")`, and in a call she may run activity "camera on" (`calls.camera`: never / sometimes (close friends, not down or worn out) / always) | `voicestack.py` `attach_lipsync`, `runtime.py` `call_connected` |
| `life.record` stores `minutes`; `brain.run_session(stop=)` | `life.py`, `brain.py` |

## Notifications and availability (`notifications.py`, `attention.py`)
- Two toast sources: `WpnDatabaseSource` (read-only copy of `%LOCALAPPDATA%\Microsoft\Windows\Notifications\wpndatabase.db`; **schema checked on a real Windows 11 PC**, payload is UTF-8 toast XML, ArrivalTime a FILETIME; I looked at table definitions only, not at any message text) and `WinRTToastSource` (`winsdk`, preferred if allowed, never run). `parse_toast`: Discord DM (title = sender), server mention (`Name (#channel, Server)`), call (`incoming call` / `is calling`), Roblox. The Discord toast wording is a pattern, not a captured sample.
- `AvailabilityModel.decide`: blocked/muted never; strangers: DMs late, calls never; close friends in seconds, friends in about a minute, others minutes; sometimes much later; mid game round or video she finishes the moment first up to a bound (close 60 s, friend 120 s, other 240 s) then stops and answers; quiet hours (config `availability.quiet_hours`, **off by default**) hold DMs until morning and refuse calls; a call is answered only if the whole answer fits inside the ring; no second call while in a call; messages wait during a call. All numbers are config (`availability`).
- Interrupt: `Context.interrupt` / `Context.situation`. An activity returns `{"paused": True, "resume_state": {...}}`; `cycle()` parks it, serves what is due, then resumes it (`ctx.resumed`, `ctx.resume_state`) within `resume_within_minutes` (45). A pause is not recorded as an outcome. Brain sessions stop between steps (not resumable, they start over); Roblox/Minecraft/Discord activities and the video watcher pause cleanly.
- A friend's missed call becomes a follow-up message. Muted people are not served from toasts; the periodic Discord check still reads their DM (that is how "they talked to her first" un-mutes them).

## Invitations (`invites.py`)
`parse_invite("wanna call?" / "do you wanna play minecraft?")` -> `decide(invite, mind)`: deterministic score, no randomness: who asks (+0.25 close, +0.10 friend, -0.20 met), her interest weight (log scale, +-0.30), minutes of that game in 24 h over 2 h (down to -0.45), mood (`emotion.invite_bias` when the engine has it, bounded +-0.35 with its reason; otherwise frustration/boredom/joy), she just started something (-0.20), late at night for non-close friends (-0.15). Yes at >= 0.45, "later (12 min)" within 0.15 below, else no with the heaviest negative factor as the reason. Hard rules first: blocked, quiet hours, already in a call, a stranger asking for a call (no), mid round / mid video (later, 5 / 8 min). The decision becomes an *intent* line in the user message ("you decided yes to 'call': you will call them yourself ...") and the model only words it in her voice, so the choice is never the model's. `InviteBrain` does the same inside a call. Yes/later schedule `callout` (place the call) or `startgame` (switch the activity to Minecraft/Roblox, staying in the call, `voice_window` = the call's window).

## Calls (`calls.py`, `voicelink.py`, `voicestack.py`)
- Answer: friend only (config `close_friends` makes e.g. her owner always close), screen read must show a ringing call from the same name, Ctrl+Enter (Discord's shortcut, config `calls.call_accept_keys`), else click Accept; "connected" only if a second screen read shows it; then the senses-voice session (STAR Microphone out, the PC's sound in through WASAPI loopback).
- Place a call: Ctrl+K to the friend's DM, check the open conversation, click the call button, wait up to 40 s for the pickup (screen read), cancel otherwise.
- Leave: spoken goodbye, end the session, click Disconnect; automatic after 3 min of silence or 60 min (config).
- The clicks need a locator: `star.computer.locate(png, what)` if that package exists, else the image model's pixel answer (`vision_locator`). Accuracy of that was not measured (checklist item 6, GUI-grounding model, is still open).

## Not done / needs her PC
1. Run on her PC: `setup.cmd`, then `python -m star.home check` (lists activities, handlers, plug-in errors, voice stack status), then dry-run, then live. Voice stack (`python -m star.senses.setup`, VB-CABLE, `soundcard`) must be in place.
2. Real Discord toast text and call keybind (Ctrl+Enter) unverified; call-end detection is by silence only (no screen check while she plays).
3. The slow-loop brain and her replies use `config.brain_url` + key file (`social_model`, `voice_model` default `star-voice`); not called live (brain 1 busy).
4. No hearing hub inside STAR Home (video watching by captions/picture); no fast 4060 voice path wired into calls (`fast_brain` not passed).
5. `invite_bias` is used only if `star.emotion` has it (PR #646); until then the seven-feeling fallback applies (both tested).
6. Roblox obby sessions need `play.obby_places` in config.json; other Roblox places use `star.games.roblox`.
7. Pending messages are in memory (a restart forgets them; the periodic Discord check finds unread DMs again).
