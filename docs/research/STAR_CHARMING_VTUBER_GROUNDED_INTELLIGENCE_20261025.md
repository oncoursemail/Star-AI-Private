# STAR — Charming VTuber, Grounded Knowledge, and Playback-Safe Expressions
**Research date:** 2026-10-25
**Base:** Star AI draft PR #581 (VTuber Director).
**Status:** Offline-tested architecture; not a new trained model, actual rig, OBS/Twitch broadcast, real game controls, or measured GPU inference improvement.

## The decisive design principle

Making Star feel wonderful and adorable is not a request to make every sentence sound childish. It means genuine *character continuity*: modest situational wit, warm curiosity, natural silences, specific joy after an actual victory, considerate reactions to mistakes, a coherent original appearance, soft coordinated movements, and the ability to remember a real event rather than pretend to have human life experiences.

Put different behaviors in one feedback loop:

**Host-approved game evidence / moderated viewer message → attention decision → grounded short model response → actual TTS playback → audio playback acknowledgment → time-aligned facial/body cues → cancellation if interrupted → verified session memory → independent evaluation.**

Simply generating text, queueing TTS, or receiving an unverified screenshot cannot justify marking a line as heard, animating a mouth, or celebrating a win. First audible playback is a *start* acknowledgement, not confirmation that a full sentence was spoken.

## Exactly what this increment adds

**star/stream_stage.py** connects PR #581's existing StreamDirector, stream_persona, and stream_motion into an opt-in, no-I/O stage coordinator. Events can propose dialogue, but expression cues are unavailable until the host confirms that audible audio playback actually began. Each plan has a one-shot sequence token. Old tokens cannot animate after an interruption or rig switch. The host still has to stop its audio queue and discard buffered frames itself.

**star/stream_knowledge.py** reuses STAR's project-scoped KnowledgeStore and SQLite FTS retrieval. Live stream questions can use a short knowledge record only when the corresponding notes are already reviewed, in the same project, explicitly approved to be spoken publicly for this request, recent enough, and free of oversized fields. Private source paths are represented by source digests instead of being included. Chat and visual text are still untrusted.

**Offline tests and rehearsal** cover audible confirmation, TTS failures, stale reactions, interruption races, video uncertainty, chat moderation flags, public/private knowledge boundaries, cat/puppy modes, reduced motion, and voice-synchronized motion samples. No credentials, model weights, voice cloning or networking are required.

### Host contract

1. Call StarStage.enable(owner_approved=True, mode="normal"/"cat"/"puppy") only after authorized operator approval.
2. Send typed StreamSignal objects. Viewer-originated signals must pass real host moderation before offer(moderated=True). The flag is only a host assertion, not authentication.
3. Optionally build a public_knowledge_packet with an owner-approved set of reviewed note IDs. Use it for a real viewer question, never an ambient one-liner.
4. Call prepare(). It may deliberately return no response while viewers are talking or Star is concentrating on gameplay.
5. Queue the proposed TTS with queue_audio(). This does *not* count as audible speech or unlock an expression.
6. When the output device confirms that speech was heard, call acknowledge_audible(). Only then can motion() generate matching motion samples from actual output-audio envelopes. This first-audio ack deliberately does **not** mark the whole utterance complete.
7. Confirm current(plan) before dispatching every batch; on interruption, drop old frames and apply the neutral pose returned by interrupt().
8. Call finish(plan, played_to_end=True) **only after the entire audible response completes**. A plain finish(plan) abandons an unsounded or partial response. On interruption, issue interrupt() to reset and invalidate old cues. The host must implement actual stop/cancel and device authorization; the Python stage only plans.

The playback acknowledgement can be spoofed by a malicious adapter: it is not a cryptographic/acoustic guarantee. The host must enforce permissions and confirm played audio. User-level JSON records are not by themselves prompt-injection defenses.

## Star's approved original chibi identity

Keep the established **Soft & Round** Star look, not generic new AI-generated accessories: indigo-black twin tails fading into gold, two gold ribbons, a four-point gold star hair clip on the viewer's left, amber-gold eyes, a black dress with gold trim and a bow, ankle boots, subtle blush, cream rim light, coherent cel shading, and a wholesome all-ages aesthetic.

**Normal:** attentive eye movement, subtle blinks, head tilt, smooth hair inertia and one-gesture-per-real-moment body language.

**Cat Star:** original black ears with gold inner accents and slim dark tail with a gold tip. Momentary ear motion for attentive/surprised events, gentle tail settle after a confirmed success. Never claim a purr was spoken if there was no corresponding audio.

**Puppy Star:** floppy black-to-gold ears, fluffy dark tail with a gold tip. Allow a small wag on a verified happy event, a delayed ear flop following head movement, then settle. Keep the mouth/eyes unobstructed.

**Focus:** quiet gaze, less idle motion, no forced chatter. **Accessibility:** reduced-motion mode removes hair/head/ear/tail swings but retains reasonable mouth movement and facial communication.

Cuteness should be connected to evidence; emotion labels here are *acting cues for a fictional AI persona*, not proof of human feelings or consciousness.

### Expression grammar

| Situation | Voice | Visual cue | Avoid |
| --- | --- | --- | --- |
| Verified game victory | One short, specific happy reaction | Small smile, gentle tail | Overhyped squeal for a dubious frame |
| Uncertain visual result | Admit uncertainty | No victory animation | Fake achievements |
| Confirmed danger | One useful callout or silence | Brief brow/eye surprise | Talking over intense gameplay |
| Viewer question | Relevant answer, optional cited public fact | Attentive nod | Reading offensive private messages aloud |
| Owner interruption | Yield immediately | Neutral reset | Continuing the interrupted sentence |
| Idle/repeated chat | Often remain quiet | Subtle idle | Repeated catchphrases, manufactured intimacy |
| Failed/unheard TTS | No spoken memory entry | No linked facial animation | Mouth moving to text nobody heard |

Live2D needs properly prepared deformer art, mouth and eye parameters, physics inputs/outputs, strand separation and collision checks. The PR #581 motion code only produces **normalized heuristic values**, not actual Live2D modeling, phoneme-accurate lip sync, hair physics or video output.

## Research matrix — what's promising and what it actually means

| Research | Grounded finding and reference | Testable use for STAR | Limit |
| --- | --- | --- | --- |
| NVIDIA PersonaPlex (2026) | [Official model research](https://research.nvidia.com/labs/adlr/personaplex/): full-duplex speech, persona/voice conditioning, natural turn-taking | A/B test against STAR's current ASR→LLM→TTS | Roughly 7B speech model and license acceptance; not necessarily compatible with gaming on shared 8GB VRAM |
| NVIDIA DyaPlex (2026) | [Official research](https://research.nvidia.com/labs/amri/projects/DyaPlex/): streaming synchronized speech and motion | Improve timing architecture and evaluation | Research, not plug-and-play Live2D SDK |
| Kyutai Pocket TTS | [Official implementation](https://github.com/kyutai-labs/pocket-tts): CPU-oriented streaming TTS, including October 2026 small-model variants | Try CPU speech so gaming GPU retains headroom | Latency/quality claims are publisher benchmarks, not tested on Star |
| faster-whisper | [CTranslate2 repository](https://github.com/SYSTRAN/faster-whisper): optimized ASR, INT8 options | Benchmark word error rate, CPU/RAM and p95 transcribe delay | Published measurements differ from STAR's device |
| VTube Studio | [Public API](https://github.com/DenchiSoft/VTubeStudio): authorized hotkeys, live parameter injection | Build a local adapter mapped to actual approved rig | App/plugin authorization needed; no arbitrary chat-to-hotkey execution |
| Live2D Cubism | [Parameters](https://docs.live2d.com/en/cubism-editor-manual/parameter/), [physics](https://docs.live2d.com/en/cubism-editor-manual/physics-operation/), [eye blinking](https://docs.live2d.com/en/cubism-editor-manual/eye-blink-settings/) | Twin-tail/ribbon/ear/tail physics, mouth/eye calibration | Requires real artist-authored rig |
| OBS Studio | [obs-websocket 5.x protocol](https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md) | Read OBS health/scene; explicit authorized live control later | No broadcast automation in this change |
| Twitch | [Chat APIs](https://dev.twitch.tv/docs/chat) and [EventSub](https://dev.twitch.tv/docs/eventsub/) | Moderated requests, viewer cooldowns, dedup and conversation memory | OAuth, reconnect, rate limits, privacy; event deliveries may duplicate |
| Google DeepMind SIMA 2 | [Official Nov 2025 research](https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/) | Vision→plan→act→verify and unseen-world game-transfer curricula | Research demonstration, not released as an integrated STAR gameplay model |
| Voyager | [Original paper](https://arxiv.org/abs/2305.16291): iterative skill library and automatic curriculum | Test reusable verified game skills on held-out maps | In-context/tool learning isn't base model weight training |

### Speed priorities on constrained gaming hardware

Keep the game + OBS + avatar responsive on any GPU with ~8GB VRAM. Schedule heavy research/training outside streaming, and don't load large text, vision and full-duplex speech models all onto the gaming device without benchmarked headroom.

Candidate pipeline: lightweight ASR, small/quantized cached dialogue model, CPU TTS, low-overhead staged expression cues, GPU-first gameplay renderer. Try background tasks on a separate authorized computer when available. Compare only identical tasks before enabling prefix caching changes, KV eviction policy, n-gram speculative decoding, or model offload. Memory offload can **decrease** generation speed due to bandwidth.

Collect p50/p95/p99 of end-of-turn to first *audible* speech, interruptions, queue latency, mic error rate, game 1%-low FPS, OBS dropped frames, VRAM/RAM peak and CPU usage. The performance of the new CPU planner must not be represented as neural model inference speed.

## Making STAR more knowledgeable — proven retrieval before big claims

STAR already has reviewed notes, content-addressed artifacts, source metadata and project-scoped lookup. This change avoids leaking every reviewed note onto a public stream; **private review and permission to broadcast are separate decisions**.

Proposed general-knowledge expansion:

1. Import licensed, revisioned material from owner-owned projects, official Roblox/Luau docs, reputable openly licensed reference sources and educational examples. Record date, license, scope, checksum and exact source.
2. Keep distinctions among a documented fact, a game observation, a vision hypothesis, a model suggestion, a user preference and an independently verified execution result.
3. Track contradictions, corrections, content version and expiry. Never append contradictory outdated facts as equally authoritative.
4. Build verified multimodal tasks: understand a gameplay clip, predict the next event, implement a Luau skill, run Studio checks, explain a build defect, repair and independently re-test.
5. Prefer short source-backed retrieval for timely viewer questions. If public evidence is absent, say what's unknown; don't invent human memories, player achievements or recent facts.
6. Expand coverage across math, general science, programming, language, art, animation, UI, VFX, Roblox physics and game strategy; measure each field on withheld examples.
7. Distinguish **better retrieval/reasoning workflows** from actual **trained model intelligence**. Weight updates require legal training corpora, reproducible runs, training evaluations and holdout tests.

A factual recap of Star's own game sessions can be entertaining; it must reference actual reported gameplay and make clear when results were uncertain. Never manufacture childhood memories or claim a human life.

## Gaming and self-improvement curriculum

**Stage A — Understand:** watch authorized gameplay replays, detect menus/mechanics and grounded match events, answer questions, recognize uncertainty. No input control.

**Stage B — Practice:** authorized toy levels and local Roblox Studio; observe, predict, execute, independently verify, fix stuck/repetition/positioning problems.

**Stage C — Skills:** inventory, objective tracking, timed actions, navigation, camera motion, combat strategy; record real mistakes and successful tactics.

**Stage D — Generalization:** hidden maps and game versions, novel objectives, varied control schemes, long-horizon goals and multiple independent seeds. Do not let practice leak into evaluation.

**Stage E — Streaming:** synchronized gameplay + voice + avatar + moderated chat, with owner pause, emergencies, bounded queues, frame budget, and nonrepeating commentary. No unauthorized multiplayer automation or anti-cheat bypass.

## Quality gates and measurable targets

- **Naturalness:** independent paired review of voice flow, timing, prosody, authentic contextual humor, interruption handling, repetitive phrases and useful silences. No fabricated interpersonal history.
- **Visual integrity:** no false celebratory animation for unverified outcomes, no mouth movement before audio ack, no stale frame batches after interruption, no clipping, accessible reduced-motion.
- **Grounding/privacy:** zero private knowledge entries aired without explicit public approval, no unreviewed notes, no viewer prompt injection promoted into commands, source/date accuracy.
- **Game skill:** goals per attempt, verified success/failure, recovery time, performance on held-out maps and unseen mechanics, matched input-time budget.
- **System impact:** actual game FPS/frametime, dropped OBS frames, CPU/GPU/RAM usage, audio underruns and first-audible p95.
- **Learning:** independent knowledge/coding/UI/building and game-transfer evaluations, with nontrivial baselines and no protected-answer contamination.

A release should pass a paired, reviewable, statistically adequate evaluation. Do not select the apparently fastest system if it achieved speed by staying silent or fabricating game successes.

## Implementation order

**Now (this PR stack):** offline StarStage coordination, host-audible handshake, token cancellation, tiny verified expression cues, normal/cat/puppy motion, privacy-guarded knowledge packets and tests.

**Next authorized step:** real output-audio acknowledgement, fully rigged Live2D model, local VTube Studio parameter bridge, OBS read-only integration, moderated Twitch connector, sustained end-to-end hardware and speech-quality evaluations.

**Then:** authorized real game observation and controls, transferable skill practice, expanded licensed reference coverage, better natural voice/laughter/gestures, human review and opt-in public streaming.

This design cannot claim Star has human consciousness, learned new model weights, played arbitrary games, increased inference speed or begun a stream. It is a reviewed engineering component awaiting actual integration and evaluation.
