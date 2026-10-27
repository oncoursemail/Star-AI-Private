# social-life-20261026: friend lifecycle, friend requests, conversation quality, safety

Branch `star/social-life-20261026` (from origin/star/next 0ee2701d), worktree `worktrees/social-life`. Builds on
star/social + star/games (#635), star/inner (#653) and star/home (#650); nothing there was rewritten.

## What it does
- **Lifecycle** (`star/social/lifecycle.py`): met -> acquaintance -> friend -> close friend from real interactions: a new
  conversation (30 min gap) +3, lines +0.5 (cap 6 per conversation), a game together +4 (once per game and day), positive
  moments +1.5 (3/day), hostile lines -3. Each stage needs score AND separate conversations (acquaintance 8 / 1, friend 25 / 3,
  close 60 / 8 + shared games or positives). One long chat never makes a friend. Apart: no decay for 7 days, then the score halves
  every 10 / 21 / 60 / 120 days (by stage); `Bonds.decay_all` (night job) drops stages, the legacy flag
  `relationship` (`met | friend`, read by invites, calls, reach-out, attention) follows the stage, so a drifted friend is no
  longer reachable by her. First message after 3+ days apart = reunion hint ("glad to see again", last topic).
- **Per person**: nickname (first real word of the display name, or the name they asked for with "call me X"), inside jokes
  (a funny line that came back in another moment 10+ min later, both occasions kept as evidence), shared memories (games
  together, becoming friends, a strong positive line), likes (friend memory's interest facts), last topic, and one follow-up
  question ("did you beat level 5 yet?": from "trying to beat / stuck on / building ..." lines, asked once, on the NEXT
  conversation, within 14 days). Rules as in friend memory: no chat text about possible minors or from Roblox chat (only game
  names and interests); everything cascades away with "forget me" across all linked platforms.
- **Hooks into the existing systems** (no duplicates): `star.inner` nightly friend cards read the bond (`reflect.rule_card`,
  `reflect_person` notes); the night job (`run_night`) calls `Bonds.night` = decay + turns open follow-ups of close friends into
  `reachout.add_seed` (her own reach-out checks, caps and screening still apply; seeded follow-ups are not asked again in chat);
  `star.home.runtime.standing` closeness uses the stage; when the inner card is in the message only a short bond line is added.
  Optional brain stream: important memories go to `star.brain.remember/add_memory/memory_stream_add` if such a function ever exists
  (today none does: nothing happens); `sink.forget("friend-<id>")` is called on forget-me.
- **Friend requests** (`star/social/requests.py`): incoming accepted only for people she played or chatted with (Discord: also
  shared servers), after a 20 s - 15 min delay, daily caps (Roblox accept 5 / send 2 / ask 2, Discord 10 / 3 / 3, overridable in
  settings `friends`); never for blocked, muted or forgotten people; Discord: a possible minor known only from another app is
  declined. She sends only after "add me / can we be friends" (a suggestion in another app does not count) or a yes to her one question
  "want to add each other?" (once per person and month, never again after a no, only from acquaintance up with a positive
  moment, never to a possible minor on Discord). Roblox stays friends-only and is never DM'd. Minecraft: `MinecraftServer.whitelist`
  (her own server, she is operator): `/whitelist add <name>` for friends or acquaintances who asked, `/whitelist remove` for people
  who blocked her; names validated against `[A-Za-z0-9_]{3,16}`.
- **FriendDesk** (`activity.available_activities`, off by default: settings `roblox|discord.friend_requests: true`): reads the app screen
  with the vision reader, clicks accept/add through `host.click`, verifies by a second read, logs only verified accepts. Never
  run against the real UI.
- **Conversation quality** (`star/social/convo.py`): `shape_reply` (no lists/walls, <=2 sentences in games, one question, a player's
  emoji, none in Minecraft), `ChatFlow` (a line from the person she just answered counts as for her for 90 s, groups of 3+: only
  when named or a question to all (30 %), never dominates, stays out when others talk to each other), question-back hint after 3
  replies without one, leave reasons (goodbye, nobody answered twice, quiet 10 min, busy) and a short goodbye line (none after a
  chat shorter than two exchanges). Roblox, Minecraft and Discord servers use it; `SocialChat.handle(game=, channel=)`.
- **Safety** (`star/social/safety.py`, pure, tested): every outgoing message passes `rules.check_outgoing` -> `safety.protect`:
  manipulation lint for everyone (guilt, "don't leave me", clingy or FOMO hooks; a message that was only that becomes a plain
  goodbye or nothing; reach-outs go through the same function); under-18 / doubted / unknown age: also no dependency-building wording, plus
  gentle session limits (break suggestion at 45, 90, 150 min). Unchanged and still tested: truthful yes to a sincere AI question
  (also after shaping), age rules, no romance or personal questions or off-platform moves for kids, no spam (Pacer), blocks and mutes.
  Per-platform **kill switch**: `<app data>/social/kill.json` `{"all": true, "roblox": true, ...}` (unreadable = off); checked in
  `SocialChat.handle`, every activity's `ready()`, the desks and the request policy. **Owner log**: every accept, offer, send,
  stage change, joke, nudge and forget in the `social_log` table: `python -m star.social log --days 7`, `python -m star.social friends`.
  Rows about a person are deleted with them; the forget line itself carries no name.

## Platform risk (owner accepted; keep it low)
Discord forbids automating a normal user account (self-bots) and may terminate it; Roblox announced large bot-account removals on
2026-08-19. Mitigation in code: human pacing, one accept or send per step, daily caps, human delays, window checks before every
click or key, kill switch per platform, FriendDesk off by default. This lowers, not removes, the risk.

## Tests
`tests/test_social_life.py` (47: lifecycle stages/decay/reunion, nicknames, jokes, follow-ups, minors/Roblox text rules, forget-me across
platforms, request decisions with fakes, desk clicks, Minecraft whitelist, flow, shaping, safety lint, session limits, kill switch,
inner hooks). Also green: test_social_games, test_home_wiring, test_inner_life. NOT run: anything on her PC, the real Roblox/Discord UI
(navigation, button reading, Roblox send flow only works when she sees the person), real Minecraft `/whitelist`.

## Changed behaviour to know
- The old "20 remembered lines = friend" rule is gone (the stage machine replaces it).
- Roblox reply targets: besides her name, an answer to something she just said and a question in a 1-2 person chat.
- Roblox prompt no longer says "never ask anyone to add you" but "not in your own words": only the code's one question.
- Not hooked yet: star.inner `Standing` use in calls.py beyond the closeness number; brain stream (no such API exists).
