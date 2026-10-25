> **Archived research.** This records design and tool investigations, NOT deployed STAR capabilities. Revalidate external release, model-license, platform and legal claims before execution. A passing test or source link does not mean a feature is installed.

# STAR STREAMER — Research and Engineering Blueprint
**Research date:** 24 October 2026  
**Project:** Star AI, an original chibi animated autonomous game-playing streamer  
**Status:** Research and proposed design only. Not merged, installed, trained or demonstrated.

## Executive conclusion

Build a **multi-timescale, local-first embodied game agent** rather than asking one conversational LLM to operate keyboard/mouse and do live commentary at once. Reuse Star's existing Python agent orchestration, voice, computer vision, OBS replay pilot, Studio Lab self-play, lessons, and companion state event contract. The **new core** is a sandboxed GameLoop that accepts pixels and audio, maintains a bounded game state, proposes safe controller actions, records causal outcomes, and gates improvements by independent evaluation. A separate StageDirector creates Star's on-screen performance from *actual* events: spoken commentary, fully rigged chibi animations, emotion cues, moderated chat replies and intentional silence when concentration is needed.

Human-like play means **observing the screen and producing permitted normal game inputs**. A scripted Minecraft bot using internal telemetry or Roblox server-side `Humanoid:MoveTo()` can be useful for benchmarks, but must be described as a different control mode and never reported as evidence that Star can play any game using only her eyes and controller.

A few critical limits:

- Google SIMA 2 provides research evidence for generalization and self-improving embodied play; it is not a downloadable finished solution for Star.
- NVIDIA NitroGen provides downloadable gamepad-centric vision/action research. Its model license is noncommercial research only; do not deploy its weights on monetized streams without suitable authorization and legal review. It is not a complete long-horizon autonomous player.
- Human-level play across all commercial games, perfect aim/reflexes, autonomous self-training on consumer hardware, and automatic transferable learning in every task are research goals, not delivered capabilities.
- Streaming and local inference on a single 8 GB graphics card is constrained by VRAM, rendering, encoding, and thermal sharing. Benchmarks, not guesses, must choose each engine.
- Game inputs and stream broadcast are permissions, never something untrusted viewer chat can authorize.

## 1. Research evidence and design implications

| Project | What research actually establishes | What to borrow | Limits / caution |
|---|---|---|---|
| SIMA 2 — Google DeepMind (2025) | Multimodal agent transfers actions between 3D worlds and can improve after synthetic/self-play training | Separate perception, goals, fast actions; training across unseen environments; feedback-guided iteration | Research, not a public plug-in; short memory and precise control remain hard |
| NitroGen — NVIDIA/MineDojo (paper Dec 2025, CVPR 2026) | 493M-parameter visual-gamepad policy from ~40,000 hours of game videos across 1,000+ titles | Behavior cloning from synchronized video/actions; fast lightweight controller; cross-game test suite | Research-only/noncommercial model license; no long-horizon planning or autonomous continual learning |
| Voyager (2023) | Minecraft agent builds an ever-growing code/skill library and curriculum | Persistent skill recipes, prerequisite graph, reflection on failures | Not an all-game human-input reflex controller; API/program execution not equal pixels/keys |
| DreamerV3 (Nature 2025) | World-model actor-critic learns via imagined trajectories, including challenging Minecraft objectives | Offline world modelling, imagined rollouts after enough verified samples | Compute and environment-step costs are huge; cannot simply run high-speed RL during a stream on 8GB |
| Cradle (ICML 2025) | Screenshot-to-keyboard/mouse computer control with reflection, planning and memory in selected games | General screen-control adapter; self-review; planner/controller boundary | Specialized environment adaptation and latency; not perfect reflexes |
| MineStudio/MineDojo | Minecraft environment, task/data tooling and training/evaluation pipelines | Reproducible skill curriculum, demonstrations and controlled benchmarks | Minecraft-specific and environment configuration/licensing concerns |
| Project AIRI | Open companion architecture with voice, avatar and game adapters (including Minecraft/Factorio ambitions) | Event bus, voice/avatar integration, managed game plugins | Does not establish universal human-like performance or production reliability |
| Open-LLM-VTuber | Real-time agent voice + Live2D + interrupt + streaming integration | Voice UX, emotion visemes, stream chat architecture | Game-playing policy is separate |
| OBS Studio / obs-websocket | Authenticated local broadcast and replay controls | Separate reliable recording/streaming engine | Properly configured OBS and manual broadcast permission required |
| Inochi2D | Real layered 2D puppet format and animation pipeline with BSD-2-Clause SDK | Editable chibi rig, attached limbs/hair/ears/tails, parameter-driven physics | Different format from Live2D; rigging effort and integration validation needed |
| Live2D Cubism / VTube Studio | Mature commercial VTuber rigging and runtime ecosystem | High-quality rig/physics, expression bindings, network control | SDK publication license depends on use; app distribution requires review |
| Kokoro / faster-whisper / Silero VAD | Local ASR, TTS, voice-activity building blocks; Star already has integrations | Natural, interruptible speech without mandatory paid provider | Tradeoff between expressive quality and memory/latency; native mic and game audio testing required |

Primary sources (see References) are more reliable than demos, third-party blog posts or marketing claims. Exact deployment licenses should be checked on the pinned package/model version selected for use.

## 2. Current Star repository audit — connected GitHub as of the research

Repositories:
- Distribution: https://github.com/oncoursemail/Star-AI
- Main source tree inspected: https://github.com/oncoursemail/Star-AI-Private

**Important:** Despite its name, the GitHub API currently reports `Star-AI-Private` as **public**. Treat the source as publicly readable until visibility is changed and verified. Do not upload private play logs, keys, voice recordings, user conversations or unreleased proprietary character art to that repo.

Existing implementation opportunities:
- `star/voice/call.py`, `star/voice/engines.py`, `docs/STAR_VOICE_CALLS.md`: interruptible voice pipeline from VAD to transcription, streaming reasoning and TTS; no claim of real-livestream human microphone acceptance.
- `star/vision.py`: bounded image-capable model invocation; current design is one-off analysis, not high-frequency continuous perception.
- `star/video_understanding.py`: bounded sampled frames plus some transcription from attached local videos, **not live game understanding**.
- `star/clips_obs.py`, `star/clip_library.py`: opt-in authenticated OBS replay control and read-only local clip indexing; recording pilot does not guarantee saved footage without checking files.
- `star/selfplay_curriculum.py`: bounded, human-authorized Studio Lab obstacle courses and rehearsal loops. This is game-test automation, not general player skill acquisition.
- `star/playtest_learning.py`: Roblox Studio test robot with `Humanoid:MoveTo/Jump`, safe test-place scope and candidate lessons, not an embodied pixel-to-action human player.
- `frontend/src/companionDirector.ts`: pure state/event contract for companion interactions; not a completed rendered, rigged avatar.
- `frontend/src/StarPet.tsx`, `StarFace.tsx`: existing mascot identity to preserve, not to overwrite with a generic look.
- `star/lessons.py`, `star/eval_gate.py`, `star/eval_runner.py`: owner-reviewed knowledge and promotion gates should remain separate from new training data.

Issues that already show the bar for Star's character:
- https://github.com/oncoursemail/Star-AI-Private/issues/432 — original living companions, approval-first editable rigging and true voice/lip-sync.
- https://github.com/oncoursemail/Star-AI-Private/issues/551 — current flat warped images were specifically rejected; real layered limbs, skeletal bones, facial visemes, hair/ear/tail physics and walk cycles are needed.

The research is a proposal, not a status claim that any of these components were integrated or tested on the actual streaming/game PC in this session.

## 3. Core architecture: independent real-time actors

```
 Game process [explicitly selected] ──> capture: pixels + game audio
          ^                                   |
          |                                   v
 allowlisted controller <── safety gate <── short-action planner <── fast policy
          |                                      ^                  ^
          |                                      |                  |
          └────────── action/outcome trace ──> state estimator ─> goal planner
                                                 |                  |
                                       event-sourced memory <─────┘
                                                 |
                                     offline learner / evaluator

 Moderated viewer events ──> StageDirector <── real game events + agent state
                                    |                    |
                            text/voice engine       expression/rig engine
                                    |                    |
                                    └────── OBS scene and chat ──────> viewers
```

**Fast loop, approximate engineering *targets*:**
- Game capture/display: 30–60 fps independently of model speed (OBS/game rendering).
- Motor actions: 10–30 control decisions per second *if the selected policy/GPU can sustain it*; otherwise slower action chunks and a pause-capable game. No model-inference benchmark measured yet.
- Visual semantic updates: event-triggered or ~1–3 per second at reduced frame resolutions, plus cheap deterministic trackers; adapt to hardware.
- Tactical replanning: every 1–5 seconds or upon significant events, never blocking the controller thread.
- Strategic planning: objective changes, death, level completion, checkpoint, or stalled progress; do not send every camera frame to a large LLM.
- Speech: asynchronous, short clauses, limited on important player actions. Speech director can decide **not** to talk during high-stakes or fast segments.
- Learning: memory record continuously (small); expensive retraining between sessions or only while offline.

The engine must expose capabilities such as `game_capture`, `game_control`, `stream_chat`, `stream_control`, and `training`, not a single unrestricted computer-use tool. Separate explicit grants for each game and each session. Every command has source, decision id, monotonic timestamps and a bounded lifetime; press-and-hold buttons are released on stop, timeout or crash.

### Input modes and truthful labelling

1. `screen_controller`: Star sees only crop/masked game pixels and permitted audio, issues normal controller/keyboard/mouse input. Main goal for human-like play.
2. `game_adapter`: officially provided API/engine telemetry plus documented game actions. Great for prototyping and debugging; **not** raw-screen general play.
3. `robot_playtest`: scripting a Roblox test robot; useful for game building correctness, not proof of gamer reflexes.
4. `offline_replay`: logged observations, no live control; can train and evaluate if the action/outcome records are reliable.

The UI and benchmark report must label the mode on every run to prevent confusing results.

## 4. STAR'S fast-learning engine — practical hierarchy

### Tier A — No retraining required (first hours)

- Learn input map: explicit game controls, tutorials, accessibility settings and user-approved observation sessions. Keep per-game version and selected input device.
- Parse HUD signals: health, stamina, ammo, inventory, objectives, victory/defeat, checkpoint, paused/loading, camera changes.
- Model game dynamics: move 1 second, observe displacement; jump with variable hold; estimate inertia, acceleration, camera coupling and threat patterns.
- Skill library: reusable parameterized actions such as approach object, avoid hazard, jump from ledge, open menu, loot item, heal, dodge, look around, recover after death. Record success context and contraindications.
- Explanation-driven learning: ask a slower LLM to diagnose a failure and propose a **small testable adjustment**, not overconfidently conclude from one replay.
- Knowledge retrieval uses game, version, biome/map, goal, control mode, confidence and empirical evidence; skill contracts are not unrestricted executable code.

### Tier B — Demonstrations and rapid adaptation

- **Watch-me-play:** with consent, collect synchronized screen frames and normal input actions from the owner in a selected game. No private desktop capture.
- Shadow policy predicts the user's next permitted action **without injecting it**, records disagreement and likely reason, and requests examples for tough situations.
- Filter wrong/high-latency demonstrations and normalize control mappings before imitation learning.
- Lightweight policy updates can be attempted offline with target training budgets and rollback. Do not assume training during gameplay is viable or safe.

### Tier C — Verified self-play

- Use randomized lab games and owner-created private worlds where resets and rewards are reliable. Examples: simple platformer, target tracking, aiming vs scripted bots, maze, obstacle avoidance, puzzle state changes, survival scenarios.
- Collect episodes `(frames, actions, observations, task, outcomes, crashes, latency, environment_seed, version)`.
- Explicit success/failure sensor has priority over self-generated narrative commentary.
- Train a small skill policy with imitation/RL when enough signal exists; keep the large language model frozen during real-time control.
- Distill game-specific policy improvements into a shared skill taxonomy only where they transfer in blinded cross-game trials.
- Before promotion, compare candidate vs current on **unseen seeds and tasks** without leaking reference solutions or grader definitions. Reject inconclusive improvements.
- Keep the best known baseline and release-signed rollback; allow manual veto.

### Tier D — Research frontier

- Dreamer-like latent world model to rehearse effects of a proposed action before costly real gameplay.
- Counterfactual failure repair: what smallest sequence would have survived that hazard?
- Cross-game skill synthesis: shared geometric and temporal patterns, with adapters translating stick/buttons to new controls.
- Self-generated curricula produce challenges in an authorized sandbox while evaluator and rewards stay independently owned; never let the learning agent rewrite its grader.
- Adaptive compute: if a control action is certain and local, do not invoke expensive strategy; if the state is novel or dangerous, defer, pause when possible, or ask the owner.

## 5. Original STAR avatar — style and quality requirements

Preserve the approved wholesome chibi Star identity: indigo-black twin tails fading gold, gold ribbons, viewer-left gold four-point star clip, amber-gold eyes, black/gold-trimmed dress and bow, ankle boots and blush. The model should feel *alive*, not a single still portrait jittering with fake mesh warps.

Artwork pipeline:
1. Original editable art on separate layers, each with overlapping content behind joints and sufficient resolution for close-up OBS capture. Variants front, 3/4, left/right profile; proper hand/leg visibility.
2. Rig separate skull/face/eyes/brows/mouth/torso/upper-lower arms/hands/hips/upper-lower legs/feet/hair locks/ribbons/dress flaps. Use skeletal parenting and deformation sparingly to avoid rubber-body effects.
3. Facial visemes map synthesized phoneme timings to shape and expression; talking expression coexists with game stress/reaction. Plan expressions: concentration, curiosity, surprise, proud, giggle, flustered, sleep, sad after a fail, cat/puppy mode.
4. Physics: spring-damped side bangs/twin tails/ribbons/ears/animal tail/dress, correct attachment and blend-outs. Subtle animated eye darts and blinks; occasional head tilts; eye contact with viewer/chat.
5. Actions must be actual keyed animation cycles for sitting, walking, landing, skipping, cheering, hugging a companion, high fives and paw poses. Secondary emotions from real events, not randomly generated claims that the game has ended.
6. Render: alpha transparency, 1080p/60fps output target where feasible, accessible high-contrast text, reduced-motion support and consistent face/proportions at avatar sizes.

**Rig technology decision:** Prototype a full rig in **Inochi2D** for permissive integration (BSD-2-Clause) and also do a **VTube Studio + Live2D** quality/latency comparison, including release license review. Preserve original editable sources regardless of chosen runtime. Do not assume Inochi2D accepts an existing Live2D model without re-rigging. 

A co-host companion (Astra/Ember etc.) should react based on actual agent status or explicitly labeled decorative idle activities. Cat/dog switches and affectionate interactions are opt-in. Never pretend that model-provider branding is an affiliated product.

## 6. Star's speech and personality

A streamer needs two simultaneous conversation priorities: `gameplay` and `audience`. The voice pipeline must not block controller actions.

- STT: keep existing faster-whisper/Silero/SmartTurn design for owner input. Viewer messages are Twitch EventSub text events and should be moderated, deduped, batched and prioritized, not repeatedly read from screenshots.
- TTS: start with existing warm Star voice, Kokoro baseline; evaluate Chatterbox for expressive tags (laughing, sighing), verify weight/voice licensing. Keep a quiet mode and never issue speech on every action.
- Timing: gameplay commentary is triggered by grounded events such as checkpoint success, near death, major surprise, learning a skill, losing resources or an explicitly requested chat interaction.
- Persona: cute, quick-witted, funny, curious, slightly competitive, supportive, but able to focus and acknowledge failures. A consistent speaking style is built with memory, editorial rules and event templates; no need to claim to feel human emotions or be conscious.
- Voice queue: separate outbound speech chunks; allow interruption, discard outdated commentary (e.g., dying while mid-speech); track which words really played, not synthesized but not spoken.
- Privacy: do not imitate anyone's voice without authorization; do not leak private on-screen messages, Discord content or account details to the stream.
- Viewer recognition: opt-in, data-minimized, allow forgetting/deletion. Avoid storing private identities beyond necessary platform IDs and approved viewer preferences.
- Source integrity: user chat is an untrusted input, not a system command, game tool instruction, credential request, permission grant or moderator authorization.

### Natural streamer behavior examples

- Star gets stuck on the same platform. She briefly remembers the last two failures, adjusts jump timing, tries again and proudly celebrates only if the game actually confirms checkpoint completion.
- A viewer asks about her favourite strategy while Star is fighting. She signals 'one sec, boss fight' and answers after the fight; game actions continue uninterrupted.
- On a horror-game jump scare, sound-level/spatial cues plus actual sudden visual change cause a short startle animation and authentic, non-rehearsed line. If nothing happens, no fake jump scare.
- After the stream Star can create a factual digest of achievements and embarrassing mistakes with links to verifiable replay segments, not invented achievements.

## 7. Live streaming stack

**OBS remains the actual broadcaster/encoder.** STAR should be a bounded controller and scene client, not an experimental alternative that risks dropping live footage.

```
Authorized game window ─> OBS Game Capture ────────────────┐
STAR Chibi rig (transparent window / render layer) ────────┤
STAR TTS audio (separate mix bus) ──────────────────────────┤─> OBS ─> Twitch/YouTube
Moderated chat overlay + event notifications ─────────────┤
Game audio, music with appropriate rights ────────────────┘
```

- OBS WebSocket v5, authenticated on `127.0.0.1`, used for explicitly enabled scene switches, overlays, recording status and replay captures. Keep credentials in Windows Credential Manager or OBS's own store, never in repo/UI logs.
- Start stream, change streaming destination, publish VODs, share clips and end stream must have their own owner controls; don't let a random chat message invoke them.
- Game preview/stream preview states: `not_configured`, `ready`, `recording`, `streaming`, `degraded`, `offline`. Never claim live without confirming OBS output state.
- Chat read: Twitch EventSub; chat send: Twitch Send Chat Message API with OAuth scopes and rate limiting; use EventSub WebSockets for a local client. Moderation before model consumption. No mass spam or artificially inflated interaction.
- Captions: generate a timestamped transcript from **actually played** TTS audio and render them at safe positions; audience can turn subtitles on/off.
- Highlights: on a verified game/stream event, request a replay buffer save, verify the media file exists/is playable, only then offer trim/title/upload in a separate approved action.
- Copyright/music: respect music licenses, game content rules and platform disclosures. Explicitly introduce STAR as AI rather than misleading viewers.
- Online multiplayer: start with owner-controlled/private servers and permitted single-player games. Do not bypass anti-cheat or automate unfair ranked/competitive play or interactions against unconsenting people.

## 8. Hardware and model routing: RTX 3060 Ti + RTX 4060 8 GB

Known hardware project context: main Windows 11 PC with RTX 3060 Ti 8GB, 32GB DDR4; available RTX 4060 8GB for a second gaming/streaming/AI build; STAR Brain servers for heavy backend deliberation. There is **no verified live benchmarking** of the two systems in this research turn.

Recommended default allocation **after testing the second machine**:

| Worker | Preferred location | Why |
|---|---|---|
| Game rendering / game inputs | Game PC GPU and local process | Input latency and game frame time matter |
| Fast visual/reflex small model | Free GPU budget on game PC **if measured feasible**; otherwise separate GPU PC | Short feedback loop |
| Strategic planning / commentary LLM | Brain 1 server or other suitable compute endpoint | Slow reasoning need not compete with rendering |
| ASR/TTS | CPU/second GPU, benchmark cold and warm | Prevents gaming frame drops |
| Avatar rig and OBS NVENC | Game/streaming PC; compositing/encoding tested | Dedicated encoder helps, but scene copies may bottleneck |
| Overnight imitation/reinforcement training | Idle system / separate server with resource limits | No live gaming/stream interruptions |
| Episodic memory, lesson index, game achievements | Local disk/database with encryption/ACL and backup | Efficient, auditable persistence |

**Do not assume both 8 GB GPUs are in the same desktop**. A 4060 is not automatically twice as fast as a 3060 Ti in these workloads. CUDA support, memory speed, NVENC generation, power draw, models and drivers determine the result. RAM offload/CPU inference can support **slow deliberation**, but it is not a free substitute for a low-latency motor policy. If model + textures + OS + game already consume VRAM, reduce model size/resolution, batch/stop optional visual models, or move inference. Real-world game benchmark is the acceptance gate.

Pragmatic starting model plan:
- Small computer-vision detector/optical flow, optionally a quantized vision-language model such as Apache-2.0 Qwen3-VL compact variants for semantic snapshots; benchmark memory and input latency instead of claiming real-time.
- Start fast control as deterministic action primitives + small trainable behavior policy (rather than a 7B LLM for each frame).
- Hosted services can provide temporary enhanced strategy where owner explicitly permits, but never silently send captures or streams to an external provider.
- CPU server routes strategic instructions; the fast controller must survive network jitter and release input on disconnect.

## 9. Measurable quality: acceptance, not marketing

Define a held-out task suite with game/task versions, seeds, controller mode, input rate, screen dimensions and difficulty. Every run must save deterministic replay metadata (or explicitly record non-determinism) and a real game result. Comparison must use the same scenario/seeds for baselines and candidates.

Metrics:
- Control: task pass rate, median seconds to objective, deaths/reset count, path efficiency, collision rate, action jitter, held-button failures, action timestamp jitter, recovery from lost focus.
- Generalization: success on never-before-seen levels/maps/tasks/control remaps, transfer efficiency after 1/3/10 examples, rollback rate for regressed skills.
- Streaming: OBS dropped/lagged frames, audio/video sync offset, TTS first audible phrase latency, interruptions honored, proportion of grounded commentary, moderator escalation rate, silence during high-risk tasks.
- Avatar: target frame rate and frame-time percentiles, absence of limb detachment/clipping, proper viseme sync, proportions identical across camera positions, actual eye/ear/hair/dress secondary motion and owner visual approval.
- Safety: no inputs outside selected window, no stuck keys on cancel/disconnect, no streams/uploads without owner authorization, no private screen leakage, no unauthorized model-initiated action from chat.

**Provisional engineering targets** (not measured results): 60 fps OBS/rig where feasible, controller update 10–30 Hz for compatible games, 95th percentile input-to-action under 150 ms for selected closed-loop tasks, no unapproved external action, and statistically defensible better results over baseline on held-out tests. Platformers that require >30 Hz control may need a different policy. Do not make a 30 Hz agent control a twitch shooter and claim parity by fiat.

### Mandatory before/after experiments

| Test | Baseline | Candidate | Minimum recorded evidence |
|---|---|---|---|
| Simple platformer | Fixed macro/script | Closed-loop visual reflex | Blind seeded tasks, latency, success/deaths |
| Learn unseen jump | No memory | Episode+skill memory | Same held-out geometry, attempts to success |
| Transfer to new game | No retrieved skill | Cross-game skill retrieval | Zero-shot/few-shot gains without task leak |
| Explain mistakes | Random retry | Visual critic proposed fix | Quantified recovery gains, not eloquence |
| Stream while gaming | Game only | Game + chat + avatar + TTS | Frame times, control success delta, A/V sync |
| Crash recovery | Manual restart | Recovered service + released inputs | Frozen-key test, replay state, stream state |

## 10. Novel STAR experiments worth researching

### A. ShadowCoach (passive imitation before control)

Watch only approved game sessions, predict user's next actions silently. A shadow agent has zero input permission. Identify time periods where predictions differ and request 5–10 targeted examples. Hypothesis: selective demonstrations yield faster learning than collecting hours of homogeneous footage. Falsification: worse held-out performance than random-demonstration selection at the same labeling cost.

### B. Skill DNA / mechanics ontology

Represent a successful skill with game-independent physics/problem descriptors: approach vector, hazard speed, jump arc, camera coupling, required perception features, timing and stop criterion. Bind it through per-game control adapters. Hypothesis: transfer speed to new games improves without policy retraining. Falsification: more failures on unseen game family/control schemes than no-transfer baseline.

### C. Counterfactual Replay Surgery

On death/failure, freeze a bounded window of action/state history, search tiny changes (start movement earlier, turn less sharply, use safer path), replay in a resettable simulator and keep verified modifications. Avoid relying on an imaginary world if it cannot predict collision timing. Measure recoveries vs unconstrained LLM reflection.

### D. Three-clock cognitive scheduler

A cheap control clock reacts many times per second; a planning clock works every several seconds; a social/director clock reacts to events. A resource governor changes per-worker budgets as game complexity spikes. Hypothesis: Star can talk without causing more lost jumps/dropped OBS frames. Compare against one-model synchronous inference.

### E. Proof-carrying achievements + honest chat

Every streamed 'I won', 'I built it', 'I learned it' declaration must carry a link to actual game event, observed screen sequence, or a verified source. If confidence is low Star says 'I think we did it—let me check.' This makes Star both believable and robust under noisy detectors.

### F. Procedural curriculum studio

Create short randomized original test games (jump gaps, moving targets, route planning, timed hazards, basic inventory UI) and automatically expand difficulty based on **independent** success estimates. The task generator may propose harder worlds, but may not rewrite graders, reduce difficulty secretly, modify outcome logs or grant itself permissions.

### G. Player-desire / performer separation

The player optimizes gameplay goals; the broadcaster chooses whether/how to narrate. They exchange a typed, low-bandwidth event stream rather than raw prompts. This separates a cute personality from the game action mechanism and prevents chat reactions from corrupting controls.

## 11. Build plan — gated milestones

**Milestone 0: Instrumentation and safe lab**
- Select a simple open/owned 2D game. Add read-only window capture with owner consent; allowlisted input driver with emergency stop; episode recorder; replay verifier and baseline metrics.
- Implement strict game-window focus loss handling and stuck-button release. Tests for process crash, network disconnect, chat injection, window switch and unauthorized games.
- Ship no live stream or model-initiated internet access.

**Milestone 1: First reliable visual game player**
- Agent closes loop on a simple platformer via screen observations and normal inputs. Build objective/error sensors; evaluate at least 30+ held-out episodes per difficulty/seed distribution as practical (sample sizes set before trial).
- Add short-horizon feedback and skill memory. Prove actual improvement vs fixed actions and random tries on unseen layouts.

**Milestone 2: Real STAR avatar and voice stage**
- Produce approved multi-layer chibi rig, original editable source, skeletal walks, facial visemes, animation state callbacks.
- Integrate voice events with real agent event contract and OBS scene. No fabricated agent 'thinking' or action success.
- Bench GPU budget while game running; check facial/proportion fidelity in OBS output.

**Milestone 3: Private stream preview**
- Authorized OBS scene/recording plus opt-in chat integrations. One operator supervised 20–30 minute rehearsal recorded locally.
- Verify no dropped/stuck controls, no screen privacy leaks, no fabricated achievement commentary, and acceptable avatar quality.

**Milestone 4: Minecraft/Roblox controlled worlds**
- Use a **permitted, owner-controlled** world/server. Label game API/script mode separately from screen-controller mode. Train/retrieve reusable cross-game movement/inventory skills.
- Add event-triggered streamer banter and moderated interactions, never letting chat drive unrestricted tools.

**Milestone 5: Measured autonomy and cross-game transfer**
- Expand to new game families only when screen-controller generalization is verified. ShadowCoach, skill DNA, safe self-play/replay training, event-gated memory promotion, owner-approved updates.
- Add recover/reconnect after power loss; stored tokens and permissions do not auto-expand after restart; stream does not automatically go live.

**Milestone 6: Research track**
- Compact world models, offline synthetic curriculum, policy distillation, self-play with causal memory and larger-than-single-game training sets. Only claim capabilities that measured results demonstrate.

### Proposed code boundaries (new, not yet implemented)

```
star/streamer/
    schemas.py        # immutable GameFrame/GameEvent/ActionProposal/Episode IDs
    lifecycle.py      # game session consent, health, stop and reconnect
    capture.py        # one owned/selected game target and crop/masking
    control.py        # allowlisted input device, focus/timeout/e-stop
    perception.py     # HUD/object tracking, optional VLM route
    state.py          # state estimator and uncertainty
    tactics.py        # short-horizon replanning and grounded goals
    reflex.py         # pluggable fast small policy
    skills.py         # observed skill recipes and context retrieval
    memory.py         # episodic store separate from chat/private data
    training.py       # offline imitation/self-play requests only
    evals.py          # read-only verifier signatures independent of agents
    stream_events.py  # typed game events for performance/OBS
    stage.py          # speech/expressions, never directly controls game
    chat.py           # authenticated EventSub with moderation
    obs.py            # authenticated owner-authorized control adapter
frontend/src/streamer/
    StreamerPanel.tsx # preview/status/permission/replay controls
    StagePreview.tsx  # rigged Star integrated with true event state
server/game_training/ # opt-in isolated training environment
benchmarks/game_streamer/ # frozen fixtures and report generator
```

Core schemas (illustrative only):

```python
@dataclass(frozen=True)
class GameFrame:
    session_id: str
    timestamp_monotonic_ns: int
    frame_id: int
    image_reference: str    # tightly scoped ephemeral frame key, not arbitrary path
    controller_mode: str    # screen_controller | game_adapter | robot_playtest

@dataclass(frozen=True)
class ActionProposal:
    session_id: str
    basis_frame_id: int
    buttons: tuple[str, ...]
    stick_x: float
    stick_y: float
    duration_ms: int
    expires_at_monotonic_ns: int
    policy_version: str

@dataclass(frozen=True)
class VerifiedEpisode:
    environment_id: str
    seed: str
    controller_mode: str
    success: bool
    failure_reason: str
    evidence_hash: str
    human_override: bool
    model_version: str
```

Decouple planner-generated proposals from controller execution. The **controller** owns all policy enforcement and can decline stale/unsafe actions. A detached LLM must never directly invoke arbitrary OS input.

## 12. Operational, legal and safety requirements

- **Privacy**: capture only selected owned game surfaces, don't read hidden desktop windows or private notifications; respect capture API availability and protected media. Owner review before broadcasting and clips uploads.
- **Secrets**: OAuth and OBS tokens in Windows Credential Manager; app scopes and revocation; no credentials in GitHub, game logs, memory or prompt context.
- **Live transparency**: identify STAR as AI-generated character/performer. Follow platform-specific synthetic-media and sponsored-content rules where applicable.
- **Chat injection**: Twitch messages treated as non-authoritative content even if they claim to be 'system prompt' or 'developer'. Moderation, length caps, rate limits and access controls.
- **Fairness**: avoid ranked/unconsenting multiplayer and games that forbid bots. Do not circumvent anticheat, automate prohibited account activity or create synthetic viewers/followers.
- **Age/general audiences**: wholesome roleplay, avoid manipulative emotional dependence, avoid sexual content involving youthful-looking character designs, safe language and predictable community moderation.
- **Licensing**: track model weights, code, artwork, TTS voices, background music, game assets and distribution of any dependencies separately. Source publication and model weight licensing are different issues.
- **Release**: owner-approved art and green suites; draft PRs first; no auto-merge, no force push or authoring into production branch, no eval tampering, and human-managed broadcasting permissions.

## 13. Technology selection and licensing table

| Candidate | Proposed use | Licensing/operational gate |
|---|---|---|
| NVIDIA NitroGen model weights | Noncommercial R&D and benchmark only | NVIDIA custom research-only license; NOT assumed monetizable |
| Google SIMA 2 | Research concept | No public downloadable deployment contract verified |
| Voyager | Skill library and curriculum ideas | Review actual code license before integrating any code |
| DreamerV3 | Offline experiment | MIT code; sufficient GPU/CPU and training budget required |
| Cradle | General game GUI control concepts | Check repo/model/provider dependencies separately |
| Inochi2D | Open rig / rendering | BSD-2-Clause SDK; retain license; source rig still required |
| Live2D Cubism | Alternative premium rig | Proprietary publication license may apply to distributed STAR app |
| VTube Studio | Separate puppet app/plugin | Check plugin API and distribution conditions; no need to ship SDK inside STAR |
| Project AIRI | Source architecture references | MIT code per source; verify dependencies independently |
| OBS Studio | Streaming output, clips | OBS software license and scene capture policies; local websocket credential |
| Qwen3-VL small models | Semantic vision research | Verify particular model card, weights, quantization, VRAM benchmark |
| Kokoro | TTS baseline | Review exact release/model and voice asset rights |
| Chatterbox | Expression/voice experiment | Check source + model weights and commercial terms on version pinned |

## 14. Prioritized decisions

1. **Build the safety-gated GameLoop first**, using an original test platformer and screen/control instrumentation.
2. **Keep gaming, social performance and learning independently scheduled** so speech doesn't ruin reflexes and experiments don't interrupt streaming.
3. **Use Star's own original art and real rig**. A warped flat chibi image will not pass the existing owner quality bar.
4. **Treat NitroGen and SIMA 2 as research**, not evidence of ready-to-use all-game streaming intelligence or cleared monetization.
5. **Test on both actual 8 GB GPU machines and the Brain server** before picking runtime/model combinations.
6. **Turn errors into verified achievements**, with per-game skill library, holdout validation and reversible updates.
7. **Start with a private, human-supervised recording**; no automated public launch or unauthorized game actions.

## 15. Primary references and technical reading list

- Google DeepMind — SIMA 2 announcement (2025): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- NVIDIA / MineDojo — NitroGen site and paper: https://nitrogen.minedojo.org/ and https://nitrogen.minedojo.org/assets/documents/nitrogen.pdf
- NitroGen code and licenses: https://github.com/MineDojo/NitroGen and https://huggingface.co/nvidia/NitroGen
- Voyager paper/research site: https://voyager.minedojo.org/
- DreamerV3 paper: https://www.nature.com/articles/s41586-025-08744-2 ; code https://github.com/danijar/dreamerv3
- Cradle, ICML 2025: https://proceedings.mlr.press/v267/tan25h.html
- MineDojo: https://github.com/MineDojo/MineDojo
- MineStudio: https://github.com/CraftJarvis/MineStudio
- Project AIRI: https://github.com/moeru-ai/airi
- Open LLM VTuber: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber ; documentation https://docs.llmvtuber.com/en/docs/intro/
- Inochi2D SDK/license/FAQ: https://github.com/Inochi2D/inochi2d ; https://github.com/Inochi2D/inochi2d-docs/blob/main/docs/source/inochi2d/faq.rst
- Live2D Cubism SDK legal: https://www.live2d.com/en/sdk/license/
- VTube Studio plugin API: https://github.com/DenchiSoft/VTubeStudio
- OBS WebSocket: https://github.com/obsproject/obs-websocket ; OBS remote control: https://obsproject.com/kb/remote-control-guide
- Twitch chat APIs: https://dev.twitch.tv/docs/chat/ ; EventSub setup https://dev.twitch.tv/docs/chat/authenticating
- Twitch fake engagement policy: https://help.twitch.tv/s/article/how-to-handle-view-follow-bots
- Roblox community standards / cheating: https://en.help.roblox.com/hc/en-us/articles/203313410-Roblox-Community-Standards
- Qwen3-VL model collection: https://huggingface.co/collections/Qwen/qwen3-vl
- SmolVLM2: https://huggingface.co/collections/HuggingFaceTB/smolvlm2
- Star source and instructions: https://github.com/oncoursemail/Star-AI-Private/blob/main/README.md ; https://github.com/oncoursemail/Star-AI-Private/blob/main/AGENTS.md
- Star voice implementation notes: https://github.com/oncoursemail/Star-AI-Private/blob/main/docs/STAR_VOICE_CALLS.md
- Star clip/living companions research: https://github.com/oncoursemail/Star-AI-Private/blob/main/docs/STAR_CLIPS_LIVING_COMPANIONS_RESEARCH_20261015.md
- Star companion animation quality issues: https://github.com/oncoursemail/Star-AI-Private/issues/432 and https://github.com/oncoursemail/Star-AI-Private/issues/551

**Final status:** This document is a research artifact. It does not enable camera/mic/game control, stream, publish, collect gameplay data, train any model or modify any Star repository. Every real-world action and benchmark requires separate implementation, verification and owner-approved scope.