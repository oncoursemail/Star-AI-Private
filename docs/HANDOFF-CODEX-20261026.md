# Handoff to Codex: STAR Home, human-like STAR, autonomy (2026-10-26)

Written by the Claude lead at the end of the 10-25/26 waves (Claude's weekly usage is at its limit until 10-28 20:00Z).
Branch state: `star/next` = `cbda62fc` (everything below is merged there). Read this file, then `AGENTS.md`, then the
notes file of whatever area you pick up (`docs/agents/<area>-20261026.md`). Tracking issue: **#613** (STAR Digital Life);
the readiness checklist is a comment there.

## 1. What the owner wants (in their words, condensed)

STAR gets her **own Windows PC** (RTX 4060 8 GB, two drives, full admin). "It is her computer completely." She is
autonomous and human-like: she picks what to do, plays games (Minecraft, Roblox, anything), draws, listens to music,
watches and reacts to YouTube, learns, chats and makes friends on her **own** Discord / Roblox / Minecraft accounts
(the owner signed them in; Discord is her real user account driven through the real app, not a bot token), answers
DMs and calls when she gets the chance (like a person, depending on the situation), calls people herself, talks in any
game or Discord call through her own Windows microphone, turns on her camera (her VTuber avatar) and shares her screen.
She has full human emotions (sad, angry, love, flirting with adults...), her own opinions, her own choices (she can say
no), memory, an inner life, real sleeping dreams, and she develops her own self over time. Voice: instant, fluent,
very cute, never glitchy. Quality and speed both matter "100%".

The owner's **first live test**: install everything in ONE folder on her second drive (`D:\STAR`), then DM her
"hey star, wanna call?"; she decides, replies, clicks call, talks; asked "wanna play Minecraft?" she may say yes or no
with a reason, and on yes plays while staying in the call. `python -m star.home acceptance --scenario dm-call` times it.

## 2. Rules that still hold (owner-approved; enforce in code, do not remove)

- Age: before any flirting she asks age; under 18, unknown, or minor signals -> friends-only, never romantic/sexual
  (also inside role-play). Roblox is always friends-only. (`star/social/rules.py`)
- Truth: she says "yes, I'm an AI" when someone SINCERELY asks out of character; she does not volunteer it; in-character
  role-play answers stay in character. (`rules.check_outgoing`)
- She can be sad/angry and say so, but never cruel, threatening, manipulative or guilt-tripping (`star/emotion_express.py`
  scans). No stored grudges.
- Real-world gates: spending money, creating new accounts, mass/cold messaging go to the owner (`star/computer/risk.py`,
  `star/home/host.py ask_owner`). Owner STOP (desktop `STAR STOP.cmd`, Ctrl+Alt+Shift+F12) + action log always work.
- Passwords never enter her model, prompts or logs. Restarts: Microsoft Autologon (owner types the password into its
  window); no lock screen, no admin consent prompt on her account (installer steps). Sessions for Discord/Roblox/
  Minecraft are signed in once by the owner with "remember me".
- Her self-model can change her personality, never the boundaries above (`star/inner/self_model.py` refuses).
- Workspace rules from `AGENTS.md`/`CLAUDE.md`: STAR's scope is everything (never call work off-topic), no censorship,
  self-improvement is automatic with integrity checks (issue #562), PC stays light while the owner is active (heavy work
  00:00-08:00 America/Chicago or when `tools/pc_guard.py` says idle), no pop-up windows, never print keys, no private
  addresses/user names in commits, never push source to the public `oncoursemail/Star-AI`, never merge to `main`.

## 3. Map of what exists (all merged in star/next; tests run on fakes unless stated)

| Area | Package / PR | Notes file | Verified for real? |
|---|---|---|---|
| Her PC runtime: elevated host agent, own goal loop, interests, history, STOP, action log | `star/home/` #636 | star-home-20261026 | dry-run only |
| Installer, one folder (`STAR_ROOT`, default first non-system drive), Autologon, no lock, no UAC prompt, OpenSSH key slot | `installer/star-home/` #641 #647 | star-home, home-acceptance | PowerShell parse only |
| Acceptance (27 checks + `--scenario dm-call`) | `star/home/acceptance.py` #647 | home-acceptance-20261026 | dry-run on dev PC |
| Wiring: plug-ins, notifications (Windows toasts), availability model, Discord calls in/out, `decide(invite)`, voice queue, game voice window | `star/home/{plugins,runtime,attention,notifications,calls,invites,voicelink}.py` #650 + inner wiring | home-wiring-20261026 | fakes (end-to-end scenario test) |
| Friends + social rules + one reply path | `star/social/` #635 | social-games-20261026 | fakes |
| Discord through the real app (computer use) | `star/social/discord_desktop.py` | social-games | not run; Discord must start with `--force-renderer-accessibility` for UI Automation |
| Minecraft (Mineflayer bot + skill library) / Roblox obby | `star/games/`, `star/play/` #635 #639 | game-play-20261026 | fakes; latency on fake frames |
| Learning games from recorded play (behaviour cloning, filtered self-improvement) | `star/play/learn/` #648 | play-learn-20261026 | synthetic game on GPU (37 -> 187/200) |
| Computer use (UI Automation first, vision grounding fallback, act loop, draw in Paint) | `star/computer/` #651 | computer-use-20261026 | real Paint drawing on dev PC; no vision model installed |
| Hearing all audio + echo cancel, STAR Microphone (VB-CABLE), cute voice `star-cute`, instant voice, 4060 fast path | `star/senses/` #640 | senses-voice-20261026 | synthetic only; no driver/model installed |
| Watch/react/learn from videos | `star/watch/` #643 | watch-videos-20261026 | fakes |
| STAR Camera (avatar as webcam), lip-sync, screen share | `star/vtuber/` #649 | vtuber-camera-20261026 | 30 fps on dev PC CPU; Discord detection of Unity Capture NOT verified |
| Emotions (25, appraisal, blends, coping, invite_bias) | `star/emotion*.py` #638 #646 | emotion-20261026, emotion-range-20261026 | default OFF until blind A/B |
| Inner life: recall, nightly reflection + friend cards, opinions, reach-out, dreams, self-model | `star/inner/` #653 | inner-life-20261026 | fakes; chat hook + reach-out default OFF |
| Human-likeness eval suite (78 scenarios, agency/yes-machine checks, blind judge) | `star/human_evals.py` #645 | human-evals-20261026 | offline grader validation only |
| Voice reasoning-leak guard | #632 | human-voice-20261025 | live: 5/90 -> 0/90 |
| Research | `docs/research/{human-like-star,game-play,play-learn,computer-use,vtuber-camera}-20261026.md` | | |

Other 10-25/26 work merged: #623 (ChatGPT VTuber stack), #624 (images #573), #627 (night-school gate fix), #629
(curiosity queue + weekly self-audit), #631 (verify_resample, +2.9 pts replay), #633 (Godot + instruction-following
suites).

## 4. Do next (in this order)

1. **Brain-1 measurements** (they wait for the sealed eval of #608 to finish; check its log first, never load brain 1
   during it): emotion A/B (`tools/emotion_eval/`, commands in emotion-20261026.md / emotion-range-20261026.md), human
   suite baseline (`python -m star.evals run --suite human`, run `judge-check` first; ~1.5 h idle brain), inner-life A/B
   + 3 dream samples (`tools/inner_life_eval/run.py` docstring), live voice latency (`python -m star.senses.bench`).
   Flip a default ON only when the decision rule in its notes file passes. Add the emotion/recall setting keys to
   `star.autoloop.LIVE_KEYS` so a PROMOTE can apply automatically.
2. **#608** (sealed eval power + integrity layer): after its run, `python -m star.sealed_eval report --set eval-power-v1
   --baseline base-1 --candidate ladder-1 --families luau-bugfix,luau-spec`, land it, then **re-freeze the sealed grader
   fingerprint** (moving `eval_runner._SETTABLE` changes it; add `verify_resample` there at the same time), add
   `integrity.py`, `sealed_eval.py`, `autoloop.py`, `promoter.py` to `PROTECTED_PATH_PATTERNS`, then land **#625**
   (autonomy loop) and wire `python -m star.autoloop cycle` to the end of eval runs + a nightly watch.
3. **Deploy to brain 1** after the sealed eval: night-school engine fix (#627, commands + undo in
   night-learning-20261025.md), curiosity/conductor (#629, `server/night_school/deploy.sh`).
4. **Her PC live install** (needs the owner: run `installer\star-home\setup.cmd` from the star/next ZIP, send the IP;
   then `python -m star.home acceptance`, fix every fail, then `--scenario dm-call` with the owner).
5. **Gaps still open** (readiness checklist on #613):
   - Persona prompts still say "nothing romantic": write the adult persona text path so romance works when
     `partner_adult is True` (emotion + rules already gate it).
   - Avatar art: the starface pack has painted mouths (no visemes); needs an owner-approved model with mouth shapes
     (owner rejected the vector companion art on 10-22; never redraw/simplify the painted style).
   - Unity Capture vs Discord: verify; fallback OBS Virtual Camera / VSeeFace over VMC.
   - Vision grounding model on the 4060 (UI-TARS-1.5-7B alone, UI-TARS-2B next to a game, run `calibrate`).
   - `star.watch` hearing hub not passed in STAR Home (captions/picture only for now).
   - Emotion events `left_out`, `friend_left`, `reunion` have no source yet.
   - Game skill needs 2-5 h of recorded owner play per course (recorder needs consent note).
   - Discord toast wording and the call-button locator need checking on the real PC.
6. Still running when Claude stopped: `voice-natural` (opener variety + desktop chat leak guard, branch
   `star/voice-natural-20261026`) and `eval-farm` (PC GPU eval farm, branch `star/eval-farm-20261025`). Check their
   branches/PRs before redoing that work.

## 5. How Claude landed work (reuse it)

- Integrator: `./star.cmd integrator take --owner codex` before landing, `release --note "head <sha>"` after.
- Merge queue (combined-tree tests, ~8 min): from a worktree that has `metallic/`, run
  `METALLIC_SRC=<wt>/metallic METALLIC_PYTHON=<venv python> PYTHONPATH=<wt>/metallic python -m metallic queue run
  --target star/next --apply --jobs 3 --json origin/<branch> ...` at below-normal priority, then push the printed
  `result` sha: `git push origin <sha>:refs/heads/star/next` (the queue does NOT push). Check the fast-forward first.
- Common gate failures seen this wave: a new module that reads source-tree files must be listed in
  `tests/test_windows_package_data.py` OTHER_FILE_ANCHORS; a new non-Python file under `star/` must be added to both
  `.github/workflows/windows-desktop.yml` and `scripts/build_windows.ps1` add-data lists; `.cmd` files keep CRLF
  (`.gitattributes` now has `whitespace=cr-at-eol`); Python 3.12 `symtable` treats a function named `top` oddly.
- Commits: `./star.cmd commit --owner codex --worktree worktrees/<wt> -F msg.txt --push` (it blocks secrets and private
  addresses).
