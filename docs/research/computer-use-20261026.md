# STAR uses any app: GUI grounding and computer-use agents on an 8 GB GPU (2026-10-26)

Goal (owner, 10-26): on her own PC (RTX 4060 8 GB, admin) STAR clicks anywhere and uses any app with her own mouse
and keyboard: browser, scrolling, settings, a paint program, music players, a game's menus. This page: what exists,
what fits on a 4060, what was built in `star/computer/`, what was measured, and what is not done.

Labels: **[measured]** = run by this agent on the dev PC (RTX 3060 Ti 8 GB, Windows 11, 2560x1440, **not** STAR's PC);
**[source]** = from the linked page; **[estimate]** = my reasoning, not measured.

## 1. Findings in six lines

1. Ask the app first. Windows UI Automation (UIA) gives exact names, roles and rectangles, no model, no GPU.
   **[measured]** Win11 Paint, 175 UIA nodes: 283 ms (cold), 184 ms, 155 ms per full snapshot. Vision is the
   fallback, not the default.
2. A grounding model answers "where is X" with one point. The best that fits next to a game today is UI-TARS-2B
   (ScreenSpot-v2 84.7, ScreenSpot-Pro 27.7 [source]); the best that fits on the card alone is UI-TARS-1.5-7B at 4-bit
   (ScreenSpot-Pro 49.6, OSWorld 27.5 [source]) or a Qwen3-VL-4B grounding fine-tune (63.2 ScreenSpot-Pro,
   self-reported [source]).
3. Models disagree on the coordinate system (original pixels, the model's resized image, 0-1000, 0-1), and model cards
   are easy to misread. Built: `detect_format`, which measures it on a synthetic screen with six labelled buttons.
4. A VLM in a loop is slow and brittle on real apps; benchmarks say so (OSWorld: humans 72.4%, 2024-25 agents far
   below; the newest leaderboards claim 85%+ but I could not confirm them, section 2). So `act()` plans on the UIA
   list (text, ~700 tokens) and uses the vision model only for the one control the tree lacks.
5. `SetCursorPos` does not drive XAML apps. **[measured]** Win11 Paint ignored it: a drag drew one dot instead of a
   line. Absolute `SendInput` moves (real mouse input) work and were pixel exact on a multi-monitor desktop.
6. Verification must be mechanical: control tree changed, pixels changed, expected text on screen, and for drawing a
   precision/recall check of the saved file against the plan. "The model says it worked" is never recorded as verified.

## 2. Models and benchmarks

ScreenSpot-Pro (high-resolution professional UIs; hard), ScreenSpot-v2 (everyday UIs; saturating), OSWorld (whole
tasks in a real desktop, 369 tasks; humans 72.36% [source: [snorkel summary](https://devweb26.snorkel.ai/osworld-benchmarking-multimodal-agents-for-open-ended-tasks-in-real-computer-environments/)]).

| Model | Size / licence | ScreenSpot-Pro | ScreenSpot-v2 | Other | Notes |
|---|---|---|---|---|---|
| UI-TARS-1.5-7B [card](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B) | 8B params listed, Apache-2.0 | 49.6 | n/a for 7B (1.5 full: 94.2) | OSWorld 27.5 (full 1.5: 42.5, 100 steps) | Qwen2.5-VL based; ~13 GGUF quantisations; card: not tuned for games; the full 1.5 is research-access only |
| UI-TARS-2B-SFT [card](https://huggingface.co/ByteDance-Seed/UI-TARS-2B-SFT) | 2B, Apache-2.0 | 27.7 | 84.7 | ScreenSpot 82.3 | table also lists UI-TARS-7B 35.7 / 91.6 and -72B 38.1 / 90.3 (first generation) |
| OmniParser V2 [card](https://huggingface.co/microsoft/OmniParser-v2.0) | YOLO icon detector + Florence-2 captioner | 39.6 (with GPT-4o as planner) | n/a | 0.6 s/frame A100, 0.8 s on a 4090 | Parses the whole screen into numbered boxes; `icon_detect_v3` + `icon_caption` are MIT, `icon_detect` is AGPL-3.0 |
| Qwen3-VL-2B (base) | 2B, Apache-2.0 | 43.3 (third party [page](https://friendli.ai/models/Datawall/brend-2b-260602)) | n/a | | A GRPO fine-tune of it reports 48.6 |
| Qwen3-VL-4B-Instruct [card](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) | 4B, Apache-2.0 | n/a official | n/a | report: 32B scores OSWorld 41, AndroidWorld 63.7 ([report](https://arxiv.org/abs/2511.21631)) | Card says it "operates PC/mobile GUIs"; KV-Ground-4B (a fine-tune) self-reports 63.2 / 94.6 ([card](https://featherless.ai/models/vocaela/KV-Ground-4B-BaseQw3vl)) |
| UGround-V1-7B ([paper](https://arxiv.org/abs/2410.05243)) | 7B | 31.6 | 87.6 (authors' own re-evaluation) | 10M elements, 1.3M screenshots | Table from [UI-AGILE](https://arxiv.org/pdf/2507.22025) and [V2P](https://arxiv.org/pdf/2508.13634) |
| Aguvis-7B | 7B | 20.4 | 86.0 | | same tables |
| OS-Atlas-7B / -4B ([paper](https://arxiv.org/abs/2410.23218)) | 7B / 4B, 13M elements | 18.9 / 3.7 | 84.1 / 71.9 | | same tables |
| ShowUI-2B ([paper](https://arxiv.org/abs/2411.17465)) | 2B, 256K samples | 7.7 | n/a | ScreenSpot 75.1 | Token pruning (-33% visual tokens, 1.4x faster training); weak on high resolution |

Gaps, stated plainly: I could not retrieve the official Qwen3-VL 2B/4B GUI table (the report's PDF text is not
machine-readable here), nor a UI-TARS-2 report, nor an independently confirmed top OSWorld-Verified number. One source
claims three Anthropic models at 83-85% on OSWorld-Verified by June 2026; I could not confirm it from the official
leaderboard. Cross-paper tables disagree (one table gives UGround-V1-7B 73.3 on ScreenSpot v1, another 87.6 on v2), so
treat every cell as indicative. ScreenSpot-Pro is the number that matters for her 2560x1440 screen.

**What fits on the 4060 (8 GB; game mode keeps `game_reserve_mb` = 5000 MB free):**

| Choice | Weights | Fits | Latency per "where is X" |
|---|---|---|---|
| UI-TARS-1.5-7B Q4_K_M | ~4.4 GB file, 5.4 GB loaded ([estimator](https://huggingface.co/Mungert/UI-TARS-1.5-7B-GGUF) [source]) | Alone on the card. Not beside a game (needs 5.4 GB of the 3.2 GB game mode leaves). | **[estimate]** 1-2 s: ~1,150 image tokens for a 1280x720 screenshot (28-px patches) at roughly 1,000-2,000 prefill tokens/s plus ~12 output tokens at ~35-45 tokens/s (272 GB/s memory bandwidth over 4.4 GB of weights). No 4060 number was found. |
| UI-TARS-2B / Qwen3-VL-2B Q4 | ~1.5 GB | Yes, also in game mode | **[estimate]** 0.3-0.7 s |
| Qwen3-VL-4B Q4 | ~2.8 GB | Yes in game mode if the voice LLM is not also resident | **[estimate]** 0.6-1.2 s |
| OmniParser V2 (parse all) | YOLO + Florence-2-base, small | Yes | 0.6-0.8 s per frame on A100/4090 [source]; **[estimate]** 1-2 s on a 4060, mostly the per-icon captions |

The per-click latency is acceptable because grounding is called only when the tree lacks the control; routine work
(menus, buttons, text boxes, browsers with an accessibility tree) never touches the GPU. Nothing was downloaded or run
on a GPU in this session: the numbers above are sources and estimates, and `python -m star.computer calibrate` is the
first thing to run once a model is installed (it prints the convention and the error in pixels per convention).

## 3. Windows UI Automation: the fast exact path

- One call per snapshot: `IUIAutomationElement::FindAllBuildCache(TreeScope_Descendants, ControlViewCondition, request)`
  with name, type, rectangle, enabled, offscreen, focus, password flag, automation id, class and value prefetched.
  Microsoft: caching helps most for WPF/custom providers and less for the client-side providers of classic Win32
  controls ([Caching UI Automation](https://learn.microsoft.com/en-ie/Windows/Win32/winauto/uiauto-cachingforclients)); it
  warns that walking a whole desktop subtree can reach thousands of items, so STAR snapshots only the front window.
  `ConnectionTimeout`/`TransactionTimeout` are set (4 s) so an app that does not answer cannot hang the loop.
- **[measured]** Win11 Paint (WinUI): 175 nodes in 155-283 ms, giving 125 usable elements with real names: tools
  ("Pencil", "Eraser"), every colour swatch ("Red", "Dark red", "Lavender"), the "Color 1: Black" state, menus,
  and the canvas as a group "Using Brush tool on Canvas" with automation id `image` (1536x864 at 100% zoom). The Save
  As dialog exposes an edit named "File name:".
- Where it is thin: games and custom-drawn canvases publish no providers ([UIA providers](https://learn.microsoft.com/en-us/windows/win32/WinAuto/uiauto-providersoverview));
  Chromium's UIA provider was opt-in behind `--enable-features=UiaProvider` in its documentation
  ([Chromium doc](https://chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/browser/uiautomation.md),
  possibly dated). **Not measured here**: Chrome/Edge, Discord (Electron), Spotify, Steam and games. The screen reports
  `thin` (fewer than four interactive controls) and the planner is told to use a `target` description (vision) or keys.
- A tree can lie: names are controlled by the app. They are passed to the planner as data inside a fenced block with a
  rule to ignore instructions in them (prompt-injection from web pages is the realistic risk).

## 4. Design

```
act(goal)  loop, max_steps / minutes, STOP file checked everywhere
  see()    front window -> UIA snapshot (ComtypesUia) -> elements_from() (filter, number, cap) -> Screen
           thin screen? -> note tells the planner to use a "target" description (vision) or keys
  plan     chat(system, user) -> ONE JSON action: click id|target, type, key, scroll, open, wait, ask_owner, done
  act      Hands (human-like): reaction delay + Fitts-law curved path + overshoot (star/play/humanlike.py), click
           at a gaussian point inside the control, typing with an uneven rhythm, scroll bursts, drag with one
           minimum-jerk speed profile along a corner-aware spline. Guard: only the program she works in.
  verify   after the settle time: new Screen -> tree changed? pixels changed (16 px cells)? expected text present?
           no effect -> tell the planner (no blind repeat: a repeated toggle click would undo itself); 2 in a row ->
           re-focus her window; 3 identical actions -> stuck; done needs evidence text on the final screen
```

Safety kept (owner rules): the owner's STOP file is checked before every action and every ~50 ms inside a move or
stroke (the button is released); every action is logged (`computer.*` in actions.jsonl); spending money, public posts,
account creation or deletion are not clicked (`ask_owner` queue); no typing into password fields; input only lands
while the window in front belongs to the program she is working in (`Guard`); if someone else moves the mouse more
than 30 px between actions she steps back (`watch_pointer`).

Draw: model plan (<= 40 strokes of <= 80 points on a 100x100 board, Paint swatch names) -> square in the centre of the
canvas -> per stroke: click the colour swatch found by name, check "Color 1:" changed, drag -> Ctrl+S, type the path in
"File name:", Enter -> open the saved PNG and compare its ink with the plan on a 100x100 grid after a one-cell dilation
(precision and recall, both >= 0.5 to be `verified`). The page edge is found at pixel precision: an 8-pixel error
shifted thin strokes by two grid cells and failed the check in a test (found and fixed).

## 5. Measured

Details and the failures found on the way: `docs/agents/computer-use-20261026.md`. Dev PC, throwaway windows only.
- UIA snapshot: Win11 Paint 125 elements, 283 / 184 / 155 ms; Character Map (Win32) 23 elements, 82 / 49 / 51 ms.
- Real drawing (fixed plan, black house + red door): verified, precision 1.0, recall 0.968, 23.8 s end to end.
- Real `act()` (scripted planner reading the real listing): open Paint, pick Red (verified from the tree text), pick
  Oval, done with evidence: 7.9 s, verified.
- Not measured: a vision model on a GPU, any browser, Electron app or game, the brain as planner (brain 1 busy with a
  sealed eval until ~11:00Z), STAR's own PC.

## 6. Limits

- Primary monitor only (screenshots and UIA rectangles); a second monitor at negative coordinates is not captured.
- One keyboard layout: unicode characters are typed with `KEYEVENTF_UNICODE`, key combinations by US scan codes.
- Games that read raw input or use anti-cheat may ignore or flag SendInput; this package is for menus and desktop apps
  (game play is `star/play/`).
- Elevated windows (UAC prompts, "Run as administrator" apps) block input from a non-elevated STAR; she runs elevated
  on her PC (star-home), which removes most of this.
- Krita and other paint programs: the canvas finder and the stroke painter are app-independent, the colour palette and
  Save As steps are Paint-specific. Not built, not tested.
- Drawing quality is bounded by the model's plan (strokes on a 100x100 board); there is no feedback loop that looks at
  the painting and corrects it yet.

## 7. Update (second lane, 10-26): newer 7B-class grounders and how to choose

| Model | ScreenSpot-Pro | Other | Licence / base | Source |
|---|---|---|---|---|
| Holo1.5-7B | 57.94 | ScreenSpot-v2 93.31, OSWorld-G 66.27 | Apache-2.0, Qwen2.5-VL-7B | [model card](https://huggingface.co/Hcompany/Holo1.5-7B) |
| Holo1.5-3B | 51.49 | ScreenSpot-v2 91.66, OSWorld-G 61.57 | Qwen licence | same card |
| UI-Venus-Ground-7B | 50.8 | ScreenSpot-v2 94.1 | Qwen2.5-VL | [third-party page](https://featherless.ai/models/inclusionAI/UI-Venus-Ground-7B) |
| GTA1-7B | 50.1 (2507) to 55.5 | OSWorld-G 55.1-60.1 | | [third-party page](https://featherless.ai/models/Salesforce/GTA1-7B) |
| Fara-7B | n/a (a whole web agent) | WebVoyager 73.5% vs UI-TARS-1.5-7B 66.4% | MIT, Qwen2.5-VL-7B | [model card](https://huggingface.co/microsoft/Fara-7B) |

Also named by the coordinator's research (docs/research/companion-life-20261026.md, not checked here): Holo3.1 4B/9B,
Qwen3-VL-8B, and Holo3.1-35B-A3B as a possible server-hosted grounder. Published numbers conflict between pages and
releases, so the choice is made by measurement: `star.computer.ground.bench` scores any grounder on 10-20 screenshots
of STAR's own apps (hit = the point lands in the expected rectangle; hit rate and median seconds). Grounding order in
the driver: UI Automation, then the GPU grounder, then STAR's remote image model (`star.vision.ask`). Discord exposes a
usable UIA tree only when started with `--force-renderer-accessibility` (the installer's "Discord (STAR)" shortcut).
