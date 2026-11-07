# computer-use-20261026: STAR uses any app (UI Automation first, vision grounding fallback, draw in Paint)

Branch `star/computer-use-20261026` (worktree `worktrees/computer-use`, from origin/star/next dff4a008). Owner request
10-26: on her own PC STAR clicks anywhere and uses any app with her own mouse and keyboard. Research and numbers:
`docs/research/computer-use-20261026.md`. Package: `star/computer/`. Tests: `tests/test_computer_use*.py` (3 files).

## Built
- `screen.py` Element / Screen (find by name, difference between two looks, `thin`, model listing with ids).
- `uia.py` `ComtypesUia` (FindAllBuildCache, one round trip) and the pure `elements_from()` (filter, number, cap).
- `winapi.py` `Windows` (foreground, list, focus, DPI) and `DesktopSink` (SendInput: absolute moves as real mouse
  input, buttons, wheel, scan-code keys, any Unicode character). Real-desktop only (`# pragma: no cover`).
- `grounding.py` `Grounder` interface, `VlmGrounder` (any OpenAI-compatible vision endpoint), `parse_point`,
  `smart_resize`, `to_pixels`, `detect_format` + `VlmGrounder.calibrate()` (measures the coordinate convention),
  `MODELS` (what the installer can fetch; nothing is downloaded here).
- `hands.py` human-like actions on `star/play/humanlike.py`: click / double / right, `drag` (one min-jerk profile over a
  corner-aware spline), `type_text` (uneven rhythm, no typos), `key`, `scroll`; STOP check before every action and every
  ~50 ms in a move; log line before and after; `dry_run`; `watch_pointer` (steps back if someone else moved the mouse).
- `agent.py` `Computer.see()` and `Computer.act(goal)`: observe, plan (one JSON action per turn), act, verify, recover.
  `Guard`: input only while the front window belongs to the program she works in.
- `risk.py` money / public post / account creation or deletion are queued with `ask_owner`, never clicked; no typing
  into password fields.
- `draw.py` plan validation, rendering, canvas finder (UIA canvas, tightened to the white page at pixel precision, or the
  largest white rectangle), painter (colour swatch by name, verified), Save As, and the saved-file check (precision and
  recall against the plan).
- `__init__.py` `register_home_activities`: "draw" (interest `drawing`) and "use_app" (interest `use_apps`);
  `build_computer(ctx)` wires the real backends.
- `settings.py` `<home>\computer.json` (grounder kind/url/model/format, settle time, drawing speed).
- `__main__.py` `python -m star.computer see-app|draw-test|act|calibrate` (real-desktop commands refuse to run unless
  the owner has been idle for 300 s, `--require-idle`; `--dry-run` moves nothing).

## For the lead (not done by me: outside star/computer/)
1. `star/home/activities.py` `PLUGIN_MODULES` += `"star.computer"` (home-wiring branch).
2. `star/home/life.py` `SEED_INTERESTS` needs `"use_apps"` (else `use_app` is never picked until she adds it herself with
   `set_interest`). `draw` runs under the existing `drawing` interest.
3. `installer/star-home/setup.ps1` pip line: add `comtypes numpy` (now `pillow pyautogui`). Without comtypes `see()`
   returns a thin screen with a note instead of crashing, so `act()` degrades to keys and vision only.
4. Optional vision model (not needed for Paint or any app with an accessibility tree): install a llama.cpp server
   with UI-TARS-2B (game mode) or UI-TARS-1.5-7B Q4 (alone on the card), then in `<home>\computer.json`:
   `{"grounder": {"kind": "vlm", "url": "http://127.0.0.1:8081/v1", "model": "ui-tars-2b", "format": "auto"}}`
   and run `python -m star.computer calibrate` once (it measures the convention; then set `format`).
5. `computer.json` is read per activity, `format` "auto" means "pixels" until calibrated: calibrate before use.

## Measured (dev PC, RTX 3060 Ti, Win11 2560x1440; owner idle > 5 min before each real run; own Paint window only)
All runs below used the CLI (`python -m star.computer`) in throwaway windows opened by the run itself (Paint,
Character Map); the owner had no input for >= 5 min before each (the CLI refuses otherwise, `idle_seconds`).
- **UI Automation, Win11 Paint (WinUI):** 175 nodes -> 125 elements; full snapshot 283 ms cold, 184 ms, 155 ms.
  Names and rectangles of tools, every colour swatch, "Color 1: Black", canvas group (automation id `image`).
- **UI Automation, Character Map (classic Win32):** 23 elements, 82 ms cold, 49-51 ms warm (`see-app charmap.exe`).
- **Draw, real Paint, fixed 2-stroke demo plan (a black house, a red door; NOT a model-made plan):**
  run 3 (final code): `ok true, verified true`, precision 1.0, recall 0.968, 23.8 s end to end (open Paint, 2 strokes at
  380 px/s with one colour change, Ctrl+S, path typed at 4x speed, Enter, file check, close). Picture:
  `docs/agents/computer-use-20261026-demo-house.png`. Saved file 1536x864 (the canvas at 100%).
- **act(), real Paint, scripted planner (4 steps):** open Paint -> click swatch "Red" (verified by the tree text
  "Color 1: Red") -> click "Oval" -> done with evidence "Color 1: Red" (found on the final screen): `verified true`,
  7.9 s including the 1 s wait for Paint's controls. The planner here was a script reading the real screen listing
  (the brain was not loaded, brain 1 busy); a model's choice quality is therefore NOT measured.
- **Failures found by running it for real, then fixed (each has a test or a stated check):**
  1. `SetCursorPos` moves were not seen as pointer moves by Paint: the first run painted one dot, precision 0.0.
     Fixed: absolute `SendInput` moves (pixel exact on this multi-monitor desktop, virtual desktop origin -1680).
  2. Catmull-Rom splines cut corners and ballooned sparse polylines; the fixed 50-degree corner rule still bulged a
     43-degree wall bend. Fixed: Hermite pieces with chord-length tangents, corners sharper than 30 degrees stay
     sharp (tests: triangle and house polylines stay within 1 px of the polyline).
  3. Page edge from an 8-pixel grid shifted strokes by up to two check cells: edges are refined to the pixel.
  4. `calc.exe` on this PC opens a "Get an app to open this link" Store dialog (Calculator is not installed), and a
     plain `SetForegroundWindow` could not take the focus from it: Paint then looked canvas-less and the draw run
     failed honestly ("could not find the canvas"). Fixed: focus with joined input queues, and `open_app` now reports
     "could not bring it to the front" instead of carrying on.
  5. A double click was one click (the second press came before the first release): fixed, tested.
- **Tests:** `tests/test_computer_use.py`, `_act.py`, `_draw.py`: 80 tests, fake desktop (sink, windows, UIA tree,
  screenshots; the fake Paint draws on a real image and saves a real PNG). Mutations checked: claiming success
  without evidence, the risk list and the double-click gap each make a test fail. Also green: test_star_home,
  test_play, test_no_undefined_globals, packaged/pyinstaller data, pyright findings, repo intelligence,
  github write scope (236 tests, 17 s); ruff clean. No test input touched the real desktop.

## Not done / limits
- No vision model was installed or run; GPU latencies are estimates (research doc section 2).
- Only MS Paint was driven for real. Not run: Chrome/Edge, Discord, Spotify, games, Krita; the `act()` loop was
  run only against scripted planners on a fake desktop (brain 1 was busy with a sealed eval until ~11:00Z).
- `act()` was not run on STAR's own PC (no access); `build_computer` real wiring ran only through the CLI here.
- Primary monitor only. Elevated windows ignore input from a non-elevated STAR.
- The drawing has no look-and-correct loop (plan -> paint -> check against the plan only).
