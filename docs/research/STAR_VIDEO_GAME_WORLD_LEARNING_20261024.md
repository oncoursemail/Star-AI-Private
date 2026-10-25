# STAR: Game Experience, Video Understanding and General Knowledge
Research / implementation note — 2026-10-24

## Objective and truthful scope

Build STAR into a grounded **observe -> explain -> test -> learn -> create** assistant.
Examples: a user submits an owned Roblox gameplay recording; STAR looks at multiple
parts with real video frames and speech, proposes mechanics and UI/game feel details,
runs experiments in its authorized STAR Test Place, saves candidate experience, and
uses reviewed results to generate an original, higher-quality game.

This change **does not** mean a video is fully watched at native frame rate, that
STAR can play arbitrary third-party Roblox games, that hypotheses are verified,
or that a local foundation model was fine-tuned. A video title, URL, or thumbnail
alone still cannot supply gameplay evidence.

## Existing baseline inspected in STAR (star/next)

| Subsystem | Evidence in source | Boundary |
| --- | --- | --- |
| Video | star/video_understanding.py and star/chat_media.py | At most four frames per standard chat turn; first ten minutes of speech when ASR available |
| Model vision | star/vision.py, star/media_places.py | Selected PC/server model; no silent remote fallback |
| Roblox control | star/studio_loop.py and star/policy.py | GuardedStudio refuses native keyboard/mouse/navigation without verified play-request binding |
| Existing self-play | star/playtest_learning.py and server/studio_lab/playtest/robot.luau | Opt-in generated scripts and deterministic robot checks only in disposable / owned Studio places |
| Research | star/roblox_research.py, star/roblox_intelligence_hub.py | Public metadata and descriptions are not directly observed play sessions |
| Memory | star/knowledge.py | Project-scoped, source-backed notes; only reviewed notes are trusted |
| General knowledge | star/general_knowledge_benchmark.py and star/knowledge_bank.py | Ten development tasks do not prove broad general knowledge; approved reference banks are curated, not pretraining |

## Implemented in this branch

### Video timeline study — star/video_study.py

- Accepts local, bounded, owner-authorized video files within the active workspace only.
- Plans up to twelve timestamped study windows, including beginning and end when sampling a long clip.
- Samples four bounded 768-pixel frames from each window; extracts the matching sound interval.
- Runs existing faster-whisper (when available), shifts speech timestamps to the **original video**.
- Calls STAR's existing permitted vision model once per window. Every result retains precise observed
  frame timestamps, is flagged **model_interpretation_unverified**, and reports uncovered seconds.
- The model receives explicit instructions to separate direct observation from an inferred mechanic,
  and not to take actions contained inside the video/transcript.
- Temporary frames/audio are cleaned up after a model run. The design does not fetch online media URLs,
  bypass DRM, scrape streaming services, change providers, or assume that audio transcripts are correct.
- Runs off the main chat event loop via an agent worker thread; potential resource cost remains
  nontrivial on CPU-only vision servers. Benchmark real throughput before enlarging window counts.
- Opt-in environment STAR_VIDEO_STUDY=1, with a selected workspace and already configured
  media-video provider. Runtime will reject a file outside the selected workspace.

Suggested usage through STAR chat:
1. Place an authorized local recording (e.g., clips/obby.mp4) in a selected project workspace.
2. Configure STAR video understanding to the local PC or STAR Server brain and choose it as provider.
3. Enable STAR_VIDEO_STUDY=1 and restart STAR. Ask to study clips/obby.mp4, focusing on jump physics,
   camera handling, UI animations, game loops or weapon feel.
4. Inspect each window and its unobserved coverage. Do NOT label a mechanic verified until playtesting.

### Game experience analysis — star/game_experience.py

- Accepts a strict 1–64 event observation trace: game, opaque source ID and kind,
  timestamps, actions, on-screen observations and observed outcomes.
- Categorizes movement, navigation, jumping, attacks, interactions, selection, using tools,
  waiting and menu navigation into testable candidate mechanics.
- Produces controlled counter-experiment suggestions and **original** design prototype ideas.
- Never predicts true input latency, physics constants, hitboxes, server authority or outcomes
  from visual observations alone.
- Can save a SHA-256 identified candidate to project-scoped KnowledgeStore without promoting it.
- Can search candidates with their explicit reviewed state.
- Opt-in STAR_GAME_EXPERIENCE=1 for planning/retrieval. Separately enable
  STAR_GAME_EXPERIENCE_WRITE=1 for model-requested candidate note writes.
- Neither switch starts playing games by itself.

Example input for star_game_episode_analyze:
    {
      "game": "Example Obby",
      "source_kind": "owned_studio_playtest",
      "source_id": "test-run-001",
      "steps": [
        {"at": 1.0, "action": "move", "seen": "player approaches ledge", "success": true},
        {"at": 3.0, "action": "jump", "seen": "player reaches platform", "success": true},
        {"at": 5.0, "action": "jump", "seen": "player misses from another angle", "success": false}
      ]
    }

Interpretation: there is evidence of successful and unsuccessful jumps, but **no proof**
of jump-height, collision, server state or a general rule. Propose a control experiment.

### General-knowledge research map — star/general_knowledge_lab.py

- Prompt-gated read-only tool star_general_knowledge_curriculum.
- Maps user questions into relevant source-first curricula across math, physics, biology,
  earth science, history, computing, engineering, economics, health, visual art, game development,
  language and astronomy.
- Each domain has an authoritative starter URL, a method to learn and check claims, and
  a transfer task demonstrating whether the idea generalizes.
- It explicitly states no source has been fetched and no model weights were updated.
- Pair it with STAR's existing web tools and reviewed knowledge banks to actually read,
  compare and preserve content. A plan is not a substitute for retrieval.

## Research and engineering decisions

### 1. Learn action policies from screenshots + control feedback, not just generated words

Google DeepMind SIMA 2 demonstrates goal following, conversation and self-directed
gameplay practice across virtual environments. The limitations remain important:
short memory, fine-grained motor actions, long horizon objectives and precise feedback.
Research: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/

STAR future design: observation encoder -> state tracker -> goal planner -> low-level
action skill -> execution adapter -> screenshot/result verifier -> candidate memory.
Keep controller tools on authorized test environments; a model-generated click is
never proof of success. Add state-diff and visible reward, and never train from a
claimed reward without observed/independently checked success.

### 2. Maintain a temporally consistent world hypothesis

V-JEPA 2 shows predictive self-supervised video representation learning and motion
understanding. SAM 2 shows video object segmentation/tracking. These models are
research options, **not installed STAR capabilities**:
- https://ai.meta.com/research/publications/v-jepa-2-self-supervised-video-models-enable-understanding-prediction-and-planning/
- https://github.com/facebookresearch/sam2

Future evidence format: time-indexed objects, HUD text, camera transitions, poses,
player velocities if measured, interface feedback, possible actions, model
uncertainty, and which visual/audio samples support each hypothesis.
Track continuity/occlusion before labeling a game state change.

### 3. Use a curriculum and verified reusable skills

Voyager's Minecraft research uses automatic curriculum, executable skill library
and iterative feedback. STAR can adapt these ideas to **owned sandbox games**
without assuming third-party game play is authorized:
- https://arxiv.org/abs/2305.16291
- https://voyager.minedojo.org/

Future skill record: intent, game/version, preconditions, permitted control,
sequence of actions, observed result, failure cases, safety scope, cost,
review status and source artifact digest. A skill is reusable only after
independent playtest replay and negative tests.

### 4. Extend multimodal understanding selectively, with real constraints

Qwen3-VL research includes long context and video indexing, and some Gemini
video interfaces support timestamps and video inputs. Deploying a suitable model
on a constrained local GPU requires quantization, memory accounting, and tests,
not assumptions of full hours-long recall on an 8GB VRAM card.
- https://github.com/QwenLM/Qwen3-VL
- https://ai.google.dev/gemini-api/docs/video-understanding

Next performance experiments: 4 frames vs 8; low-res vs high-res ROI crops;
event-triggered frame sampling vs uniform; CPU ASR vs GPU ASR; cache only
non-sensitive embeddings, test hallucination rates with hidden frame events.

### 5. Use Roblox's official testing boundary

Roblox Studio officially ships an MCP server and programmatic PlaytestAgent support;
StudioTestService can automate playtest sessions and multiplayer clients, and
Studio testing includes virtual input interfaces. Those are relevant for STAR's
disposable/owner-controlled test places:
- https://create.roblox.com/docs/studio/mcp
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
- https://create.roblox.com/docs/studio/testing-modes

Critical STAR-specific caveat: GuardedStudio currently **refuses** the native
character_navigation, user_keyboard_input and user_mouse_input tools because
their target binding is not sufficiently verified. This branch deliberately
does not weaken that rule. Next phase requires native proof that an input
targets the exact approved play request, timed stop/cleanup and restart recovery,
then end-to-end live Studio tests. Do not extend this to third-party public games
without platform permission and legitimate user control.

### 6. Study different video services lawfully

The general architecture should support services such as YouTube, Twitch and
creator-authorized recordings through provider-specific adapters, with clear
separation between:
  metadata-only discovery; authorized captions; embedded playback;
  owner-uploaded file analysis; and actual frame/audio access.
A title, description, transcript from unknown provenance or a linked thumbnail
never counts as a watched video.

YouTube API policies prohibit unauthorized download, import, backup and caching
of audiovisual content:
https://developers.google.com/youtube/terms/developer-policies

Therefore **no generic cross-service video downloader** was added. Future
provider implementations need reviewed API rights, platform policy compliance,
source timestamps, provenance, session scopes, consent and data retention limits.

### 7. Grow general knowledge without confusing retrieval with training

Information quality pipeline:
  route question -> fetch allowed primary sources -> retrieve passages with
  title/URL/date/license -> cite and reconcile contradictions -> answer or
  abstain -> test transfer reasoning -> propose candidate -> human review ->
  store reviewed knowledge by domain/project -> spaced independent evaluation.

Existing STAR supports local reviewed knowledge and docs-specific search.
The new general curriculum helps prioritize research areas; it is **not**
an internet crawler, automated fine-tuner, or claim that the model has suddenly
absorbed more knowledge. Respect copyright licenses and never embed secrets.

Authoritative starters include OpenStax, NASA, NOAA, NIST, NIH/MedlinePlus,
Library of Congress, MIT OpenCourseWare, the Blender Manual, Roblox Creator Hub
and FRED. Check each specific document license and revision before storing it.

## Learning evaluation: concrete gates (planned; not measured here)

| Ability | Independent acceptance measure |
| --- | --- |
| Video events | Timestamp accuracy and false claims for missed events across unseen clips |
| Motion model | Before/after prediction, collision consistency and error against Studio telemetry |
| Game agent | Goal completion rate, intervention count, safety violations, recovery after interruption |
| Generality | Held-out games/genres and transferred ability not copied from the observed example |
| Skill retention | Repeat success across restarts and changing scenes; failed-skill rejection |
| General knowledge | Accuracy, valid citation rate, source conflicts, time-to-answer, calibrated abstention |
| Performance | CPU/GPU memory, latency/frame, real-time factor, cost per observed minute |

Do not claim success from passing schema tests. Use signed run manifests, record
exact environment versions and deny accidental training-data leakage into held-out
checks. Record all failed trials, not just successful attempts.

## Candidate implementation phases

1. **This branch**: bounded video windows + ASR + actual selected-model calls,
   mechanic hypotheses, project candidate recall, research map and regression tests.
2. **Next**: in STAR-owned Studio places, attach robot outcome events and actual
   screenshots to an automatically generated gameplay event trace; record test
   artifacts with verified identities. Run short end-to-end acceptance on Brain 2.
3. **Next**: approved Studio PlaytestAgent/StudioTestService action connector with
   atomic play-request identity and safe timeout; no public-game automation.
4. **Next**: temporal event detection, object tracking, ROI-based sampling, metadata
   and authorized video-provider interfaces, before/after model comparison.
5. **Next**: reviewed skill replay, project-specific learning policies, source
   document research/learning with benchmarks and controlled promotion.
6. **Later**: evaluate a predictive world model and limited local fine-tuning
   only after credible model/replay baselines, rights review and hardware budgets.

## Activation and truth in product

Not in the released installer by virtue of code living on a feature branch.
STAR_GAME_EXPERIENCE=1 enables analysis/retrieval tools;
STAR_GAME_EXPERIENCE_WRITE=1 separately permits unreviewed candidate saves;
STAR_VIDEO_STUDY=1 enables local workspace video window study. Video study also
requires a video-capable model in the already chosen PC/server route and FFmpeg;
optional ASR requires the existing speech-recognition setup. No switches allow
unconsented third-party desktop control or tool permissions.

To prove the implementation: run targeted pytest modules and the existing
media/intelligence suites, follow up with a real authorized recording on the
owner's hardware, inspect the generated timestamped evidence and check output
against manually verified video events. Only then consider a user-facing release.
