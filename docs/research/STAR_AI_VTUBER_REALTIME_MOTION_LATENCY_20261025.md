# STAR realtime intelligence, speech–motion, and latency research
**Research date:** 2026-10-25 (UTC) · **Scope:** follow-up to draft PR #581, independent of any live broadcast or production deployment.

## Executive decisions

1. STAR needs one **verified realtime path** for hearing, seeing, speaking, playing, and animated expression rather than five heavyweight model loops contending for 8 GB of VRAM. The game stays responsive first; conversational quality and creative work come after it.
2. A humanlike streamer is more than a natural TTS voice: turn-taking, interruptions, timing, referential grounding, physically coordinated expressions, appropriate silence, and continuity each need their own acceptance tests. Represent her as **an AI VTuber**, never an undisclosed human.
3. Implement cheap local visual feedback now using a *deterministic motion-planning fallback* fed by actual output-audio envelope and approved event cues. Do not claim this replaces a Live2D physics rig or research-grade speech-motion generation.
4. To improve speed, **measure time to first audible speech and per-stage p95** before swapping models. Prefix caching, partial text streaming, direct speech-to-speech, model offload and speculative decoding must each pass A/B comparison on the owner's actual hardware.
5. Game-playing intelligence comes from the **plan → observe → act → verify → revise** loop in explicitly authorized test environments; videos and model opinions are not execution evidence.

## Primary sources and what they actually establish

| Source | Evidence | Applicability / caveat |
| --- | --- | --- |
| NVIDIA PersonaPlex (Jan 15, 2026): https://research.nvidia.com/labs/adlr/personaplex/ | Full-duplex role/voice-conditioned speech, listener interruptions and backchannels. | Investigate as a voice candidate; do not equate a demo with STAR's measured real-time quality or assume it fits an 8-GB GPU. Licensing and voice usage require separate review. |
| NVIDIA DyaPlex (June 2026): https://research.nvidia.com/labs/amri/publication/nagano2026dyaplex/ | Causal simultaneous speech + motion for dyadic interaction; learned coupling between utterance, body and interlocutor. | Strong design direction for expressive STAR, **not** shipped or reproduced here. Needs hardware, accessible weights, latency and identity-fit validation. |
| NVIDIA Audio2Face-3D v2 architecture: https://docs.nvidia.com/ace/audio2face-3d-microservice/2.0/text/architecture/audio2face-ms.html | Outputs facial blendshape motion from audio but explicitly **does not animate head motion or eye look direction**. | A separate gaze, head and expressive motion channel is essential even if neural facial lip-sync is used; check current licensing and distribution status. |
| VTube Studio official API: https://github.com/DenchiSoft/VTubeStudio | Authenticated opt-in local WebSocket; `InjectParameterDataRequest` can feed mapped tracking parameters. | Host must request plugin API access, authenticate, confirm loaded model and parameter IDs, clamp weights and be able to revoke. This patch does not connect. |
| LiveKit audio turn detector and tuning: https://docs.livekit.io/agents/logic/turns/turn-detector/ and https://docs.livekit.io/agents/logic/turns/tuning/ | Semantic/acoustic endpointing and adaptive interruption help avoid speaking over a person or cutting off natural pauses. Local `v1-mini` exists. | Test endpointing error rate and false barge-in alongside p95 latency. Do not activate billable models without approval. |
| OBS websocket: https://github.com/obsproject/obs-websocket | OBS exposes a password-protected control API. | Integrate status read + private preview first; starting a real broadcast is a separate explicit owner action, never an automatic rehearsal consequence. |
| vLLM speculative decoding (v0.21 docs): https://docs.vllm.ai/en/v0.21.0/features/speculative_decoding/ | Model-compatible speculative methods can reduce inter-token latency for memory-bound, low-QPS workloads. | Compare full-TTS response latency and VRAM, not token speed alone. Test model-dependent speculation; do not presume universal gain. |
| vLLM automatic prefix caching: https://docs.vllm.ai/en/latest/design/prefix_caching/ | Common stable prompt prefixes can reuse KV blocks. | Keep static persona/permissions at beginning, place event data at end, use per-user safe cache scoping and measure TTFT hit rate. |
| KV cache external tiers study (Sep 10, 2026): https://arxiv.org/abs/2609.11744 | CPU/NVMe offload helps some long-context workloads but can lose to recompute on other hardware. | Benchmark under VRAM pressure; no blanket "disk cache makes AI faster" claim. |
| Google DeepMind SIMA 2 (Nov 2025): https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/ | Generalist game agent research: instruction following, reasoning and action grounded in environment feedback. | Conceptual reference only; no SIMA 2 model or arbitrary-game access is included. |
| Roblox Studio built-in MCP / playtesting (Mar–Apr 2026): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 and https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767 | Native Studio MCP and beta Playtest Agent can reproduce QA tasks in Studio. | Bind tool calls to exact approved local test place/instance and log before/after gameplay proof. Don't grant uncontrolled keyboard or published experience access. |
| Speech-and-body multimodal motion (ECCV 2026): https://feifeifeiliu.github.io/MOCO/ | Research into coordinating different body regions under speech, text and trajectory controls. | Research/animation design inspiration; not a production-ready drop-in. |

## Gap analysis against STAR's existing and proposed modules

- Baseline `star/live_show.py` produces bounded episode plans, not a live VTuber.
- Draft #579 `star/video_study.py` and `star/game_experience.py` address observed frames/mechanic hypotheses, not verified game control.
- Draft #580 `star/streamer_director.py` and `star/streamer_skill_eval.py` offer a separate alternative live intent pipeline and holdout evaluation.
- Draft #581 `star/stream_director.py`, `star/stream_persona.py`, `star/stream_budget.py` already prioritize events, ground language and advise on stream VRAM.
- **This follow-up** adds `star/stream_motion.py` (offline speech-envelope-aligned rig frame targets) and `star/stream_latency.py` (bounded, privacy-minimal p50/p95 telemetry). It extends #581's offline rehearsal to demonstrate both. **It does not create another competing event director.**
- Before any merge, choose **one** canonical director between #580 and #581 and adapt imports/tests. Avoid duplicated policy engines silently disagreeing on interruption priorities.

## Motion planner design, input trust and actual behavior

`star/stream_motion.py` accepts up to 15 seconds of ordered normalized audio RMS samples and at most 32 explicit cues. At 15/30/60 fps it produces suggested normalized facial/head/body, eye, lip, hair, cat ear, puppy ear and tail controls. Its deliberately inexpensive bounded calculation uses no GPU, no imported ML libraries, no media, no network, no background threads, and no persistent listener.

**What is synchronized:** lip aperture reacts to real host-supplied output-audio levels, with bounded attack and decay; mouth cannot open *before* an unseen audio sample and decays after data stops. Expressive cues such as joy, surprise and laugh have bounded decay envelopes. Idle blink and sway derive deterministically from a seed; movements remain subtle. Default mode has no animal ears/tail; cat and puppy modes add low-amplitude movement. Accessibility mode suppresses idle body and tail motion while keeping mouth and communicative face. `neutral_frame` is an immediate reset target after cancelled output.

**What is not synchronized:** there is no phoneme-to-viseme aligner, voice emotion recognizer, 3D skeletal IK, hair cloth/rigid-body solver, or predictive inference. Sampling and timestamps must come from the **actual audio playback clock**. Appending `SpeechIntent` context to a system prompt would not make it secure or audio-grounded. Trusted host integration must handle backpressure, cancellations, audio/visual clock drift, and all real VTube Studio/Live2D parameter mappings.

**Laughter:** laughter cues must derive from a verified approved performance path (user-approved expressive TTS event or measured audible laughter), not randomly injected in any answer. Avatar mouth and shoulders can then respond; this does not train or prove natural-sounding laughter.

**Personality continuity:** STAR may keep clearly fictional on-stream lore with an explicit `fictional_canon` label and grounded memories of *observed* streams, but must not present invented childhood or fabricated offline human life as real. Keep viewer chat untrusted and never create voice clones of people without permission.

## Latency instrumentation and performance hypotheses

`star/stream_latency.py` stores only numeric local-monotonic milestone timing and outcome enums in a bounded ring buffer (default 256 turns); no raw transcript, names, chat messages, model prompts, videos or audio are retained. It reports **time to first audible speech** p50/p95 using nearest-rank statistics, completeness, failures/cancellations and per-stage p95 where timestamps exist. It explicitly handles missing stages (such as direct speech-to-speech), and labels p95 evaluation **insufficient** below 20 completed samples. By design, one 900 ms default target is an adjustable engineering budget, not an observed STAR result or SLA.

To actually make STAR faster, host benchmarks should run paired before/after sessions on the same Windows hardware, model build, quantization, game scenario, voice preset, network, seed where controllable, and GPU load. Collect:

1. Input-end/turn decision → first audible p50/p95/p99, interruption cancellation time, false interruption rate.
2. Perception → first token → first audio chunk → audible output timestamps from one monotonic clock domain.
3. Actual game 1% low FPS and frame-time p95 with recording/VTuber/voice enabled; available VRAM/CPU/RAM and dropped speech/avatar frames.
4. Retrieval/context cache hit rates, time spent moving model layers, batching overhead, prefill vs decode; speech quality blind listening scores, privacy/identity compliance.
5. Evidence-grounded gameplay objective success and failures, with sealed holdouts; compiler/test quality for generated Luau, plus human visual review.

Never mix raw host clocks across Brain 1 and Brain 2: synchronize explicitly or measure cross-host spans using one coordinator's roundtrip timestamps. A low text-token latency can still be a worse VTuber if TTS starts late or OBS frame drops rise.

## High-leverage intelligence experiments (proposals, NOT implemented)

- **Causal gameplay episodes:** For each allowed own-game challenge, capture `observation → goal → chosen action → predicted result → actual result → uncertainty`; persist only with consent and replay provenance. Hypotheses must pass independent randomized test seeds before entering a reusable skill library.
- **Failure-focused curriculum:** Choose next authorized playtest by expected information gain: repeat whether a change fixed an error, generate a discriminating test when uncertain, and keep unseen validation scenarios separate from learning.
- **Selective stream attention:** Treat visual perception as a limited-budget resource; raise sampling for a verified high-stakes moment and defer background research/training if FPS or speech backlog worsens. With 8-GB GPUs, do not load two large models concurrently without measured headroom.
- **Multi-agent evidence debate:** Local fast planner proposes action, verifier independently checks game state against goal before claiming success; promote only observed success and log abstention.
- **Expressive audio / rig architecture:** Later benchmark PersonaPlex or other authorized duplex voice option against a cascaded STT/LLM/TTS path; evaluate DyaPlex-like causal motion versus Audio2Face blendshapes plus curated Live2D physics. Don't copy identities or blindly deploy research weights.
- **Live lore and correction:** Use versioned, provenance-linked fictional lore, session recaps and immediately reversible personal facts. Let STAR say "I don't know" if chat references events outside observed recording coverage.

## Acceptance gates and stop conditions

1. **Offline gate now:** run `PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_stream*.py' -q`, `python3 -m compileall`, and `python3 -m examples.streamer_rehearsal`. They exercise synthetic inputs only.
2. **Integration gate later:** approved adapter must map known rig IDs (query VTube Studio's loaded model), clamp every parameter, authenticate, and stop all queued motion/audio on owner interrupt. Never send stale avatar motion after stop.
3. **Hardware gate later:** instrument p50/p95/p99 at fixed game loads and compare baseline against proposed change; grade identity-consistency, natural laughter, speech artifacts, lip sync offset, animation coherence and 1% low FPS. Collect reviewer judgments across uncued/surprise/chat/gameplay conditions.
4. **Gameplay gate later:** use approved owner test games through Studio MCP with per-action capability scope, read-only default and bounded undo; evaluate independent holdout mechanics. No third-party game terms violations or automated competitive matchmaking.
5. **Streaming gate later:** private OBS preview, confirmation gate before `StartStream`, AI disclosure, no unmoderated viewer content in actions or audio, panic-stop, privacy review and clear logs. Require full repository CI and review before integration or release.

**Explicit limits:** this patch has no new trained weights, measurable live latency reduction, working TTS engine, playable game controller, broadcast integration, actual hair physics, or authorization to deploy. It creates observable, testable components so those ambitions can be evaluated rather than asserted.
