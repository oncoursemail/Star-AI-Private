# Starry Eye Proof Loop: Visual, Gameplay and Concept Evidence

**Research and prototype date:** 2026-10-25

**Target:** STAR development branch `star/next`
**Scope:** First working read-only, engine-neutral evidence gate and concept-diversity tool.
**Not delivered here:** a new vision foundation model, live engine adapters, independent
game generation, comprehensive video understanding, a game-quality guarantee, or a
newly trained model. Tests against synthetic saved traces are not live playtests.

## Why STAR needs a proof loop

A model may produce syntactically valid code and still make unusable UI, incorrect
collision, a dull game loop, rigid animation or a scene with incoherent composition.
A screenshot alone can't prove that an interaction works; a passing unit test
can't prove that the visible result looks professional.

**GameDevBench**, ICML 2026, evaluates 333 game-development tasks derived from web
and video tutorials. Its published paper reported best-agent success of 53.8%;
GPT-5.4 rose from 41.1% to 52.0% with visual feedback in the reported
configuration. These are **study results, not STAR results**, and the project
maintains a separately evolving leaderboard. The paper also reports a larger
deficit on 2D graphics than on gameplay tasks: precisely why visuals need their
own evidence rather than inheriting programming scores.

Primary source: https://proceedings.mlr.press/v306/chi26a.html
Open reference / benchmark: https://github.com/waynchi/gamedevbench

### The staged design

```text
Human intent + prior approved style + engine/project constraints
   |
   v
Retrieval: reviewed snippets, licensed assets, prior failures, engine docs
   |
   v
Creative planner: propose N *different* genre-consistent design contracts
   |
   +--> Concept ranker: reuse knowledge without copying entire prior concepts
   |
   v
Specialized builders: logic / scene / UI / 2D art / 3D / motion / sound
   |
   v
Authorized disposable workspace + engine-native authoring
   |
   v
Capture: native hierarchy + screenshots + timed video + runtime events
   |
   +--> Deterministic checks: clipping, contrast, routes, assertions, budgets
   +--> Vision critic: describe visible issue, cite frames/regions, mark uncertain
   +--> Gameplay critic: inspect traces, replicate failures, compare alternatives
   |
   v
Repair one verified failure, replay with same baseline & deterministic seed
   |
   v
Keep if independently measured better; owner decides final visual quality
```

A review result is not a model's reward signal by itself. Prefer deterministic
engine or browser measurements when available, preserve baseline screenshots and
run identity, and avoid letting the same model create and grade its own private
evaluation data. Report **unknown** when evidence was never collected.

## Implemented this branch

`star/starry_eye_quality.py` is a local bounded utility. `star/workspace.py`
exposes two read-only tools; neither invokes an editor, touches the network,
creates assets, alters permissions or executes generated code.

- `workspace_starry_eye_audit({ "path": "quality.json" })`:
  reuses `creative_review.capture_evidence` to hash actual screenshots/source,
  verify dimensions, and compare any owned baselines; checks user/engine-reported
  layout for viewport clipping, minimum button hit regions, pairwise overlap,
  and declared text-color contrast; tests frame differences against explicit
  motion/static expectations; examines provided run-event counts and maximum
  performance budgets; warns on nearly uniform images.
- `workspace_game_concept_rank({ "candidates": [...], "history": [...],
  "required_genre": "obby", "count": 3 })`: compares five structured
  dimensions (genre, core loop, setting, style, twist), penalizes similarity
  to historical ideas and previously selected proposals. A given *genre* can
  recur indefinitely without requiring its ideas to recur.
- Status is **automated_checks_failed**, **insufficient_evidence**, or
  **automated_checks_passed**. Checks may validate declarations but are not
  self-authenticating native execution receipts. The output always says
  `runtime_executed_by_this_tool: false` and `owner_approved: false`.
- The source, captures, optional baseline and run trace are confined to an
  explicitly selected `Workspace`. Its credential protection and path
  restrictions still apply. Old owner approvals never carry over to changed
  evidence; `star/creative_review.py` remains the trusted approval boundary.
- No model-written spec, manifest, trace or source can automatically mark a
  candidate as owner approved.

### Minimal data example

`quality.json` in an existing selected workspace (filenames are examples):

```json
{
  "project": "ObbyGame",
  "artifact": "checkpoint-menu",
  "source": "src/menu.luau",
  "sources": ["src/menu.luau", "src/theme.luau"],
  "views": {
    "desktop": {"file": "captures/desktop.png", "width": 1280, "height": 720},
    "phone": {"file": "captures/phone.png", "width": 390, "height": 844}
  },
  "layout": {
    "phone": [
      {
        "id": "Play",
        "rect": [12, 70, 130, 52],
        "interactive": true,
        "min_target_px": 44,
        "foreground": "#FFFFFF",
        "background": "#181923"
      }
    ]
  },
  "expect_events": [
    {"name": "player_spawn"},
    {"name": "checkpoint_reached", "min_count": 3},
    {"name": "level_completed"}
  ],
  "budgets": {"p95_frame_ms": {"max": 33.3}},
  "trace_file": "captures/run.json"
}
```

Run trace example, **supplied by a future trusted engine adapter** or imported
manually in a test. A user-written JSON file is *not* proof an engine was run:

```json
{
  "engine": "roblox",
  "run_finished": true,
  "events": [
    {"name": "player_spawn", "t_ms": 0},
    {"name": "checkpoint_reached", "t_ms": 850},
    {"name": "checkpoint_reached", "t_ms": 1900},
    {"name": "checkpoint_reached", "t_ms": 3050},
    {"name": "level_completed", "t_ms": 4300}
  ],
  "metrics": {"p95_frame_ms": 15.8}
}
```

Usage through an existing selected-workspace agent tool, or in offline Python:

```python
from pathlib import Path
from star.workspace import Workspace

work = Workspace(Path("my_game"))
report = work.call("workspace_starry_eye_audit", {"path": "quality.json"})
assert report["runtime_executed_by_this_tool"] is False
```

Important distinctions:
1. `rect` uses captured **image pixel coordinates**, not CSS logical pixels,
   Roblox UDim2 offsets or actual input hit-test measurements. For browser
   accessibility, use CSS px/DOM semantics separately. A viewport crop or
   transformed parent needs native geometry export. Overlap rules are
   conservative and intentionally allow declared overlay exceptions.
2. A difference between two rendered frames proves **changed pixels**, not
   that character movement looks smooth, that a run succeeded, that animation
   is in sync, or even that intended gameplay occurred.
3. Declared colors are tested for mathematical contrast, not discovered by
   computer vision from screenshots. A visual critic should cross-check them.
4. The `run_finished` boolean is untrusted JSON; an engine adapter must later
   add separately controlled run identity, signed/hashed capture linkage,
   machine-generated timestamps, completion state and preserved logs.
5. `relative_novelty` is similarity against the provided history, not global
   originality, copyright clearance or a fun-quality score.

### A tiny concept-diversity example

All three prompts can be **parkour/obby** while differing materially:

- **Glass Echo:** move through a suspended sound museum; footsteps create
  temporary crystal paths; cel-shaded monochrome with gold accents.
- **Rainforest Relay:** climb living canopy routes that change when
  co-op partners redirect water; rich hand-painted foliage.
- **Gravity Archive:** switch gravity via historical tapes in a brutalist
  observatory; minimal pixel-art render with physically tested collision.

Reusing tested `checkpoint`, `spawn`, `hazard`, `respawn` and camera
contracts is desirable. Reusing a whole aesthetic hook, scene layout, theme
and objective every time is not. The ranker catches obvious structural
repeats; an additional semantic/visual novelty critic remains future work.

## Cross-engine testing strategy (research, not new integrations)

| Target | How to inspect / author / prove | Next required work |
|---|---|---|
| Roblox | Studio's built-in MCP, selected place identity, `screen_capture`, real play mode, console logs, keyboard/mouse input, `character_navigation`, guarded Script edits. STAR already has Studio Lab / robot prototypes. | Add trusted run receipts, multiple device profiles, network/client-server assertions and linked frame captures |
| Web HTML/CSS/JS | Playwright screenshots, DOM accessibility snapshots, element bounding rects, click/keyboard actions; browser console; responsive viewports. | A sandboxed browser adapter with original DOM geometry and pixel/DPR mapping; do not treat generated HTML screenshot as interactive UI |
| Godot | Official headless editor/import/test command options; GDScript, scene graph and rendered captures. | Approved installed binary/version plus constrained project runner and real scene/interaction assertions |
| Unity | Unity Test Framework EditMode/PlayMode tests, editor scene/prefab hierarchy and captured frame; explicit editor-version match. | Constrained editor worker, no arbitrary copied plugin execution |
| Unreal | Editor automation / AutomationTool, game logs, scene/camera capture, packaged build testing. | Native editor bridge, controlled project clone, version/SDK-aware test harness |
| Blender | `bpy` inspection, render shots, rigs/UV/normal/material/animation checks, glTF handoff validation. | Render evidence plus destination engine import proof |
| 2D & pixel art | Sprite sheets, silhouette/palette/alpha checks, zoomed nearest-neighbor export review, flipbook timing. | Sprite-aware image segmentation, tile seam / animation continuity measurement |

Official/reference URLs:
- Roblox built-in Studio MCP: https://create.roblox.com/docs/studio/mcp
- Roblox Studio testing: https://create.roblox.com/docs/studio/testing-modes
- Roblox playtest virtual input announcement: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- Playwright screenshots: https://playwright.dev/docs/screenshots
- Playwright test snapshots: https://playwright.dev/docs/test-snapshots
- Playwright accessibility: https://playwright.dev/docs/accessibility-testing
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/
- Godot CLI: https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html
- Unity automated tests: https://docs.unity3d.com/Packages/com.unity.test-framework@1.4/manual/reference-command-line.html
- Unreal Editor scripting: https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-and-automating-the-unreal-editor
- Blender automation: https://docs.blender.org/api/current/info_advanced_blender_as_bpy.html

Note: W3C AA target size minimum is 24 **CSS pixels** subject to exceptions;
44 CSS px is the stricter AAA target size. The tool's per-element
`min_target_px` defaults to a **conservative 32 screenshot pixels** and is
not a stand-alone WCAG conformance test. Contrast thresholds 4.5 / 3.0 are
conditional on ordinary versus large text, with WCAG exceptions.

## How to pursue visually grounded understanding

STAR's existing vision API (`star/vision.py`) can answer bounded
questions about screenshots, but an image-model statement is a hypothesis.
An advanced Starry Eye layer should anchor each claim to:

- a source/capture hash + exact viewport, timestamp and camera;
- a rendered bounding region (and visible comparison image, when provided);
- a corresponding native scene/UI element ID, animation track or event ID;
- a reproducible test action and expected effect; and
- uncertainty, alternative interpretation, and the diagnostic to resolve it.

Move from **what pixels appear** to **what a player can do**:
`frame → screen region → native object → active behavior → user consequence`.
Use full videos when temporal patterns matter (transitions, foot skating,
contact, hitboxes, horror timing); sparse still frames lose such evidence.

For general game creation, add an explicit user-facing design contract:
primary gameplay loop, win/lose, pacing, multiplayer/security, camera, art
direction, input families, platform, target frame time and original hook.
An agent may invent the first design but must preserve owner-approved visual
identity and user restrictions thereafter.

## Model-budget and verification strategy

The owner's 8 GB GPU constraints make running every large specialist for
every iteration wasteful. Prefer:

1. Cheap static/syntax/manifest checks **every edit**; use cached project
   graph, design tokens, approved asset hashes and prior failure patterns.
2. Deterministic native playtest at milestone boundaries; capture bounded
   multi-view screenshots and relevant timed clip segments, not continuous
   full-resolution recording of every frame.
3. Invoke expensive multimodal reasoning only on changed regions, ambiguous
   defects, visual regression candidates or owner-visible review milestones.
4. Compare candidate fixes on the **same test scenes and seeds**; hold out
   fresh cases to detect overfitting, regressions and reward hacking.
5. Preserve failure evidence as candidate lessons only. Never let an agent
   alter the grading policy, silently self-approve, auto-publish or broaden
   filesystem/network privileges.

Graphify, Obsidian and long-term knowledge storage are useful for attaching
`design reason → artifact → screenshot → native object → defect → fix →
verified result`. They cannot replace engine validation or ensure an agent
understands a rendered scene.

## Roadmap and hard acceptance criteria

### Gate 1 — current branch, unit verified
- Evidence hashes and bounded files; clipped/small/overlapping controls;
  declared contrast; animated vs frozen frame checks; missing runtime events,
  missing metrics and exceeded budgets; concept-diversity ranking.
- Offline test fixtures verify failure/inconclusive states. They do not prove
  actual Studio, Godot or browser runtime passes.

### Gate 2 — trusted evidence collectors
- Bind native playtest identity, receipts, screenshots, timed trace, scene IDs,
  selected test place, platform profile and reproducible inputs.
- Fail closed on disconnect, incomplete trace or mismatched run identity.
- Separate low-cost inspection from authorized edits.

### Gate 3 — gameplay/visual critics
- Multi-perspective screenshot+video analysis, UI hierarchy verification,
  rig contact and particle timing, architecture and lighting coherence;
  pixel-art scale/palette consistency; concrete failure descriptions.
- Distinguish objective checks from taste; collect human preference data
  without silently altering approval.

### Gate 4 — autonomous creator lab
- Dispatch genre-specific expert skill packs for tycoon, obby, survival,
  horror, shooter, narrative and novel hybrids across supported engines.
- Build multiple *different* design candidates; measure player mechanics
  and visuals independently; keep prior approved elements stable.
- Evaluate on new holdout game briefs and actual owner-playtested builds.
  No "better than any AI" claim without common-task, common-budget evidence.

### Gate 5 — verified self-improvement
- Error-indexed design memory with provenance, license flags and retrieval
  by a specific skill gap, not bulk copying the internet.
- Quality-controlled practice curriculum with human review, rollback,
  exact trace preservation, independent evaluation and regression gates.

**Safety:** No live purchases, user accounts, third-party downloads or
publishing; no execution of model-written engine plugins in an uncontained
host; do not train on assets without appropriate rights. Keep all risky
new integrations opt-in and isolated by project and engine.
