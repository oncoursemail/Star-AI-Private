# life-extras-20261026: STAR's life extras (scrapbook, goals, studio, mood weather)

Branch `star/life-extras-20261026` (worktree `worktrees/life-extras`, from origin/star/next 0ee2701d). Package `star/life/`,
tests `tests/test_life_extras.py`. Umbrella: #613. Honesty line: the feelings, goals and "taste" are a designed simulation
that shapes her behaviour; nothing here claims she is conscious. Built and tested on fakes only: nothing ran on her PC, no
real ComfyUI picture, no real singing, no Studio place, no real widget window was opened.

## What is where

| Piece | File | Default | What the code enforces |
|---|---|---|---|
| Shared scrapbook + anniversaries | `scrapbook.py` | ON (`life_scrapbook_enabled`) | a moment needs a `source`, a date not in the future, a unique source, and (for a "first") no earlier moment with the same `first_key`. Anniversary only for a stored moment whose date is 1/3/6/12... months back (grace 2 days), text built from stored fields by a template; 1 a day, 2 a week, once per (moment, milestone); marked only after the reply (`Note.done()`) |
| Goals, streaks, skill confidence | `goals.py` | ON (`life_goals_enabled`) | lifecycle open -> active -> done (needs PROOF) or abandoned (needs a reason). Proof = screenshot/clip file that exists, is non-empty, is newer than the goal and was not used for another goal; or a test result with `passed is True`, a name and a time after the goal. Overdue + 7 days untouched = abandoned with that reason. Max 3 open, no two of one domain, dropped/done goals are not re-proposed for 14 days |
| Creative studio + gallery | `studio.py` | ON (`life_studio_enabled`) | five kinds (drawing, story, journal, song, roblox), `verified` = file exists and is non-empty, her commentary (why / what to improve) comes from the brain or stays pending (`fill_commentary` later), never templated. Variety (kinds she made lately weigh less), novelty (a theme overlapping the last 20 pieces is skipped), 2 pieces a day, 3 h apart |
| Mood weather | `mood.py` | pure mapping | sunny / cloudy / stormy / starry / off from `emotion.current()` + `emotion.history()`; the why-line comes from a fixed table keyed by event KIND, never the free-text detail |
| Personal style (her PC only) | `style.py` | ON (`life_style_enabled`), and only where `her_pc()` | wallpaper (SystemParametersInfo + Desktop style), accent colour (DWM/Explorer registry), cursor (her own .cur/.ani), sounds (her own .wav, 4 whitelisted events), up to 3 desktop stickers, avatar outfit/accessory/expression; each is one PowerShell script through the Executor's `shell` action (STOP, action log, dry run apply) and is `applied` only when the readback shows her value (dry run / failure are recorded as such). Values are validated first (hex colours, whitelisted events, paths inside her workspace, no quote/shell characters). Taste = `style_prefs` (15 cute traits, [0.05, 1], at most 0.1 per experience, use-up for variety, drift back to rest, owner praise/dislike via `owner_reaction`). Limits: wallpaper/accent daily (earlier for a new occasion), cursor/sounds/stickers weekly, avatar twice a day. History table = "wallpaper of the week", shown on the journal page ("MY STYLE") with each why (built only from the facts that drove the pick) |
| Status API (her PC) | `api.py` | OFF (`life_api_enabled`) | GET only, Bearer token (random, in `<home>/life/extras/api_token`, constant-time compare, never printed), `/life/mood` + `/life/journal`; listens on `life_api_host` (default 127.0.0.1) / `life_api_port` (8765) |
| Desktop widget (owner's PC) | `widget.py` | OFF (`life_widget_enabled`) | stdlib tkinter 220x74, optional always-on-top, click = journal page opened from the API, right click menu. Reads only the API; offline is shown as offline, never as a guessed mood |

Data: `<home>/life/extras/life.sqlite3` (moments, anniversaries, goals, goal_log, skills, works), her style notes
`<home>/life/extras/style-notes.md`, work files under `<home>/life/extras/studio/<kind>/`. `<home>` = STAR Home's folder on her PC,
else the app data folder. (STAR Home's own `<home>/life/` JSON files are untouched.)

## How it plugs into what the other agents built

- `star.home.activities.PLUGIN_MODULES` gained `"star.life"`; `star.life.register_home_activities` adds the interests
  `creative_studio` and `personal_goals` (only if missing) and three activities: "creative studio" (story, journal, song,
  roblox), "studio drawing" (`gpu_mb=6000`, so game mode keeps her game's video memory) and "pursue a goal".
- `star/home/loop.py`: `_life_tick` (each cycle: sweep goals, set at most one goal a day via `goals.propose` from her weak
  skills then her interest weights, write pending commentary) and `_life_after` (after each session: save the moment the
  activity reports in `outcome["moment"]` if `with_owner`, count the session as practice for the open goal of that interest,
  finish it only when `goals.proof_from_outcome` finds real proof). Both wrapped, never fail the loop.
- Practice is delegated, not rebuilt: "pursue a goal" runs the registered activity of the goal's interest (star.play's
  roblox/minecraft for obby/game goals, `practice` for Luau tricks, `draw` for drawing...) with the goal as its goal, and
  a goal she could not do goes to the curiosity queue (`star/curiosity.py`, kind `failed_verification`), which night school
  studies. A goal is mirrored into star-home's `Life` goals when its interest exists there (so `goal_for(interest)` hands it
  to the session) and closed there on done/abandon.
- Self-model: `star/inner/night.py` passes `goals.evidence_text()` (finished goals, given-up goals with reasons, skill
  confidence lowest/highest) into the nightly `self_model.revise` evidence. It is only evidence: the bounded revision in
  `star/inner/self_model.py` is unchanged, and a goal can never touch the fixed boundaries.
- Emotion: `creative_done` (finished drawings/music/builds and studio pieces that are not drafts) and `task_success` (other
  goals) through `emotion.on_event(..., only_if_enabled=True)`; the widget reads `emotion.current()/history()` through the API only.
- Singing: studio looks for `sing(lyrics, title, folder) -> Path | None` in `star.voice.singing` or `star.senses.singing`
  (`studio.find_singer`). It does not exist in this tree yet; until it does, songs are text-only "lyrics_draft" gallery entries.
- Roblox experiments: written to `.luau`, linted with `star.luau_lint`, and "finished" only if a `studio_runner(code, name)`
  (Studio Lab / dev tool, her own throwaway place) is passed in and answers ok; otherwise a draft that says so. Nothing is
  published and no account or place of the owner is touched.

### Style details and limits (owner add-on 10-26)

- Wallpaper source: a gallery drawing that fits her mood/season/occasion/traits (>= 0.3 overlap), else a new drawing through
  `studio.make_work` (so it lands in the gallery with her commentary), else any unused gallery drawing. Files are copied into
  `<workspace>/style/wallpapers` (Executor refuses commands that mention its control folder, so nothing under `<home>` is used).
- Avatar: the VTuber lane has no outfit/accessory interface. The look is always written to `<home>/life/extras/avatar-style.json`
  ({outfit, accessory, expression, mood, season, occasions}); `star.vtuber.apply_style(style) -> bool` is called if it ever
  exists, until then the history says `recorded`, never `applied`. Assets come from `<root>/assets/avatar/{outfits,accessories}`
  if present, else a built-in cute catalogue (so the names are wishes until real assets exist). New outfit ideas:
  `style.design_outfit_idea` draws them into the gallery (`outfit_idea` history rows).
- Not done: icon arrangement (no stable API to move single desktop icons), real desktop widgets (no third-party API on Windows 11;
  only stickers). Cursor/sounds/stickers do nothing until she has her own files in `<workspace>/cursors|sounds|stickers`
  (sound names: notification*.wav, asterisk*.wav, exclamation*.wav, question*.wav). The accent registry writes were NOT run on a real Windows desktop: fake-host tests only, so try `python -m star.home`
  dry-run first on her PC.
- `life.style.owner_reaction(store, text)` is not called by any chat path yet (same owner-identification gap as the chat note).

## Not wired yet (real gaps, in order)

1. **Chat hook.** `star.life.chat_note(home, owner=True)` returns the note (anniversary or a finished goal with its proof)
   for the NEW user message of the OWNER's chat, `note.done()` after the reply. Nothing calls it yet: star/social has no
   owner identification and the desktop chat runs on the owner's PC, so I did not edit `desktop_core.py` or `social/chat.py`
   (other agents are in them, and the scrapbook must never reach a friend's chat). Wire it where the owner is known.
2. **Moments come from outside.** `life.on_event({...with_owner: True, source, title, ...})`, an activity's `outcome["moment"]`,
   or by hand: `python -m star.life moment <kind> <title> <source> [media]`. No call/game code emits them yet.
3. **API as a background job.** `api.background_job(home)` is ready for `Runtime.background()`; not added (runtime.py is
   being extended). Until then: `python -m star.life serve` on her PC with `life_api_enabled: true`. For the widget on the
   owner's PC: `life_api_host` = her LAN address, copy `api_token` (path printed by `python -m star.life token`) to the owner's
   PC, write `<owner app data>/life/widget.json` ({"url", "token_file", "poll_s", "always_on_top"}) and set
   `life_widget_enabled: true`, then `python -m star.life widget`.
4. Drawing needs ComfyUI on her PC (`star.image_gen`); without it the drawing maker reports `MakerUnavailable` and records nothing.
5. The studio activities record a not-verified session (and so a `failed_verification` curiosity item) when a pipeline is
   missing; harmless but noisy until the pipelines exist.

## Checks run

`tests/test_life_extras.py` (52 tests) and `tests/test_life_style.py` (17 tests, fake host), all fakes: moment refusals, anniversary only from real dated memories (day before, grace,
too late, no source, future row, rate limit, no repeat, month-end, year), chat note owner-only and marked after the reply,
goal lifecycle + every proof refusal + proof reuse + abandon reason + sweep + streaks + skill confidence + proof_from_outcome
+ after_session + the goal activity through a home activity + night-school hand-off, gallery records with commentary / pending
commentary / style notes / unavailable pipeline / unverified file / song with and without singing / roblox draft vs run /
variety, novelty and schedule, weather mapping (10 cases), why-line never leaks detail, API auth and read-only, widget state
mapping and offline, tick once a day. Full suite: see the PR.
