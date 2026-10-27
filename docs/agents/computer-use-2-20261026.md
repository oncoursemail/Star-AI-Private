# computer-use-2-20261026: reliable, general computer use on STAR's own PC (driver, skills, stop, gates, identity)

Branch `star/computer-use-20261026` (worktree `worktrees/computer-use`, fast-forwarded to origin/star/next 0ee2701d; the
first lane of the same name, #651, is merged and its notes stay in `computer-use-20261026.md`). This lane EXTENDS
`star/computer/`; nothing parallel. Tests: `tests/test_computer_driver.py` (27, fake desktops).

## Built (all in star/computer/)
- `driver.py` `Driver.run(Step)`: observe (screenshot + UIA tree + window list = `Observation`) -> ground -> act
  (the existing human-paced `Hands`) -> verify (`Expect`: text appears / gone, window in front / opened / closed, switch
  on/off, focus on an edit, typed text visible, or at least a tree/pixel change) -> retry. On a mismatch: if the screen
  changed, wait longer and look again (slow apps); then the next alternative target (`target=("A", "B")`, the replan
  hook skills use); a click or key that changed something is never repeated (toggles); no effect = re-focus her window
  and retry. Uses `Computer.see/open_app/aim_point/ask_owner`; `act()` still plans, the driver executes skills.
- `ground.py` `GroundingChain`: `UiaFinder` (name match >= 0.85) -> `VisionFinder(local VlmGrounder)` on her GPU ->
  `VisionFinder(StarVisionGrounder)` = `star.vision.ask` on the brain (star-fast vision role) when `remote_vision` is on.
  A vision point inside a UIA control snaps to that control (real name for the gates, better aim). A model server that
  is down is a miss, not a crash. `bench(cases, grounders)`: STAR's own grounding benchmark (hit = point inside the
  expected rect; hit rate + median seconds); CLI `python -m star.computer bench cases.json`.
- `skills.py` (`run_skill(driver, name, **args)`): open_app (aliases + computer.json `apps`; already running = focus),
  focus_window, browser_go / browser_search (Ctrl+L, type, Enter), discord_dm (Ctrl+K switcher) / discord_reply,
  roblox_join (`roblox://experiences/start?placeId=`, same link as star/games/roblox.py) / roblox_leave (Esc, L, Enter,
  then the Leave buttons), settings_toggle (`ms-settings:<page>`, reads the switch, clicks only if needed),
  install (.msi via `msiexec /qn`; .exe: accept the licence, untick bundled offers, Next/Install/Finish; a serial,
  password or payment screen goes to the owner). Discord alias = the installer's "Discord (STAR).lnk" in Startup, which
  starts Discord with `--force-renderer-accessibility` (without it Discord's UIA tree is thin and vision takes over).
- `gates.py`: gated (recorded with `ask_owner`, step refused): money / accounts / public posts (risk.py, now also on the
  vision target words), passwords and secrets (password fields; fields named password/PIN/card/CVV/2FA/serial/product
  key; text that is a Luhn-valid card number or a key/token), mass messaging (limits.py). Never: CAPTCHA / "verify you
  are human" on screen (she stops and tells the owner), cheat engines / injectors / executors / spoofers / autoclickers,
  non-allowlisted link schemes (javascript:, mailto: ...). `act()` now uses the same gates and chain.
- `limits.py` `RateLimits`: actions/minute 60, messages/hour 30, different people/day 20, same text to > 2 people
  refused (computer.json `limits`).
- `identity.py`: `python -m star.computer enroll --star-pc` (owner, on her PC) writes `<home>\machine.json` = role
  "star-pc" + SHA-256 of the Windows MachineGuid (never the GUID). `Driver`, `build_computer` and every real-desktop CLI
  command refuse anywhere else (`WrongMachine`, exit 4): no profile, another role, another machine (copied folder,
  STAR_HOME_DIR pointed at a copy). STAR's actions cannot write the home folder, so she cannot enroll a machine.
- `stopswitch.py`: one STOP file for all three owner stops: file, Ctrl+Alt+Shift+F12 (control.hotkey_watch; started
  by the CLI, the Home loop already runs it), HTTP API `GET /status`, `POST /stop`, `POST /resume` with header
  `X-Owner-Token` (token in `<home>\owner_token`, created on first start; default 127.0.0.1:8767, `stop_api.host`
  0.0.0.0 to stop her from the owner's PC). The driver also plugs the switch into `Hands`, so a stop lands within ~50 ms
  inside a move.
- `actionlog.py`: `<home>\computer-log\<yyyymmdd>\steps.jsonl` + `<n>-before.jpg` / `<n>-after.jpg` per attempt
  (max 1280 px, JPEG 70, 7 days kept; act() writes it too). Text redacted with control._short.
- Small changes: `Element.toggle` / `RawNode.toggle` (UIA TogglePattern, property 30086, read in the same cached call;
  "on"/"off" in the planner listing; part of the screen signature so a flipped switch counts as a change); settings
  keys `remote_vision apps limits stop_api log_keep_days log_screenshots`; `build_driver(ctx)`; `use_app` runs through
  it; CLI `enroll check-machine skill bench`.

## Tests and checks (what ran)
- `tests/test_computer_driver.py` 27 passed; with the 3 older computer-use files 107 passed (11 s). Covered: wrong
  machine (no profile / other GUID / other role / garbage), grounding order (UIA first, vision never asked when the tree
  has it; local -> remote; snap; server down), StarVisionGrounder scaling, bench, retry on no effect, no repeat after a
  change, alternatives, give-up detail, STOP file before any input, trip mid-move, stop API token (403 without / wrong,
  resume owner-only), buy gated + approvals.jsonl, password / card / key typing refused, CAPTCHA + cheat tools + bad
  scheme, mass messaging and recipient caps, action pace, log screenshots + pruning, skills on fake Settings / Edge /
  Discord / installer / Roblox.
- Mutations checked: removing the identity check, the "no repeat after a change" break, or the click gate each makes a
  test fail. ruff clean. Full pytest (14,064 tests, longer than the 90-min timeout in one run): the first ~84% ran in
  one go with 2 failures, in tests/test_doc_grounding.py / tests/test_luau_run_*.py (timing tests; those files pass
  alone: 139 passed, 5 skipped); the remaining 129 files ran separately: 2139 passed, 134 skipped.
- NOT run: anything on a real desktop in this lane (owner's PC is never a target; her PC is not reachable from here), no
  vision model, no real Discord/Edge/Roblox/installer. Real-app names (Edge address bar, Discord quick switcher, Roblox
  leave keys, installer button names) are from the apps' usual UI, not measured.

## Research update (short; full table in docs/research/computer-use-20261026.md section 7)
- Grounding models that fit 8 GB: Holo1.5-7B (ScreenSpot-Pro 57.94, -v2 93.31, OSWorld-G 66.27, Apache-2.0,
  Qwen2.5-VL-7B base) and Holo1.5-3B (51.49) [card](https://huggingface.co/Hcompany/Holo1.5-7B); UI-Venus-Ground-7B 50.8
  [page](https://featherless.ai/models/inclusionAI/UI-Venus-Ground-7B); GTA1-7B 50.1-55.5 depending on release
  [page](https://featherless.ai/models/Salesforce/GTA1-7B); UI-TARS-1.5-7B 49.6 (#651 table); Fara-7B is a whole web agent
  (MIT, WebVoyager 73.5%) rather than a grounder [card](https://huggingface.co/microsoft/Fara-7B).
- Coordinator's research (docs/research/companion-life-20261026.md): candidates Holo3.1 4B/9B, UI-TARS-1.5-7B Q4
  (~5.4 GB loaded), Qwen3-VL-8B; published scores conflict, so pick with a small benchmark of STAR's own tasks (10-20
  real app actions with fixtures) = `ground.bench`. Holo3.1-35B-A3B shares the brain's model family: a possible
  server-hosted grounder, untimed. (Holo3.1 numbers not checked by me.)
- UIA stays primary (no GPU, exact); vision only for what the tree lacks (games, canvases, Discord without the flag).

## Owner steps on HER PC (in order)
1. Enroll once: `python -m star.computer enroll --star-pc` (from the STAR root venv). Check: `python -m star.computer
   check-machine` prints "this is STAR's PC". Without this, use_app/draw/skills refuse (that is the wrong-machine rule).
2. Vision model (optional; UIA works without it): `setup.cmd -Only grounder -Grounder ui-tars-2b` (2.3 GB, fits beside
   a game) or `-Grounder ui-tars-1.5-7b` (5.2 GB, whole GPU). Then run `tools\start-grounder.cmd`, copy
   `home\computer.vlm.json` over `home\computer.json` (or merge its "grounder" block), and run
   `python -m star.computer calibrate`; put the printed format into `grounder.format`.
   Holo1.5 / Holo3.1 / Qwen3-VL-8B are not in pins.json yet: a GGUF + mmproj of the same family run by the same
   llama-server command (`-m model.gguf --mmproj mmproj.gguf --host 127.0.0.1 --port 8081 -ngl 99 -c 4096`) works with
   the same computer.json block; add a pins.json row to make it an installer choice.
3. Remote fallback (optional): `"remote_vision": true` in computer.json uses STAR's image model on the brain.
4. Benchmark: record 10-20 screenshots of her real apps with the expected rectangle per question into a folder with
   `cases.json` (`[{"image": "discord-1.png", "query": "the message box", "rect": [l, t, r, b]}]`), then
   `python -m star.computer bench <folder>\cases.json`; keep the grounder with the best hit rate at an acceptable time.
5. Owner stop from his PC (optional): computer.json `"stop_api": {"host": "0.0.0.0"}` + firewall rule for port 8767,
   token from `<home>\owner_token`: `curl -X POST -H "X-Owner-Token: <token>" http://<her-pc>:8767/stop`.
6. Try a skill: `python -m star.computer skill settings_toggle --args "{\"page\": \"nightlight\", \"name\": \"Night
   light\", \"on\": true}"` (refuses within 300 s of the owner's last input unless `--require-idle 0`).

## For the lead (outside star/computer/)
- `installer/star-home/setup.ps1`: add the enroll call (`python -m star.computer enroll --star-pc`) as a step that runs
  only on her PC, or keep it as owner step 1.
- `star/social/discord_desktop.py` still uses the HostAgent path (screenshots + image model); it could call
  `skills.discord_reply` through a Driver for UIA-grounded, verified, rate-limited sends.

## Limits
- Primary monitor only (unchanged). Driver steps are one window at a time; `act()` keeps its own loop (now with the
  shared gates, chain, log and pace) rather than calling `Driver.run` per action.
- Pattern gates are a safety net, not a proof. Same-text detection is exact after whitespace/case normalisation.
- Installer flow knows common button names (English UI only).
