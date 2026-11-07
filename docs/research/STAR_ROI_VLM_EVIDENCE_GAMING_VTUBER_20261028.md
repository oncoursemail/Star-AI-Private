# STAR: ROI-first local vision, real-model audit, and next intelligence milestones

**Research and implementation date:** October 28, 2026.
**Branch:** `feat/stream-roi-vlm-static-gate-20261028` stacked on #734.
**Scope:** One bounded improvement to Star's *existing* opt-in local paired-frame vision worker, followed by an evidence-based plan for game intelligence and expressive streaming.

## Why this matters

The previous worker prepared two entire game-window images for every admitted visual comparison. On a high-resolution game, downsizing a whole 1920x1080 frame to a 512-pixel edge can make a tiny health indicator, status icon, inventory count, or menu detail illegible. Even if the active task is about one HUD element, the worker still encoded all the unrelated scene pixels.

Also, when the bounded JPEG representations of two frames are identical, a model call cannot provide useful evidence of a *visible difference* at that resolution. Spending the AI's scarce inference budget on such comparisons is wasteful. Repeated visual guesses are **not** independent proof of a game mechanic or victory.

## Implemented in this branch

1. **Host-selected visual focus crop** in `LocalLlamaComparisonWorker(focus_box=(x0,y0,x1,y1))`, in normalized 0..1000 game-window coordinates. The worker crops the authorized RGB image **before** resizing to the model's image budget; both earlier/later frames use the *same* host-configured crop. This is not an arbitrary URL, model-selected screenshot, viewer-supplied rectangle, or full-desktop capture. Small, malformed, out-of-range and ambiguous boxes are rejected. The original full-window geometry and trusted capture timestamp remain on the eventual `VisualPacket`.
2. **Opt-in identical JPEG gate** using `skip_identical=True`, before a VLM HTTP request. If the bounded, encoded earlier and later views are byte-for-byte identical, the model is **not** invoked and the newer timestamp becomes the next short-lived in-memory reference. No positive visual finding is emitted. This is a hard equality check, not a probabilistic assertion that the underlying game state is unchanged.
3. **Host-only, OFF-by-default configuration**: `focus_box=None` and `skip_identical=False` preserve prior behavior and tests. No public network, game control, speech, streaming activation or memory-on-disk is added. Existing bounded prompt, response parsing, model loopback, local owner approval, worker-quarantine and hardware admission protections remain intact.
4. **Metrics**: count `identical_pairs_skipped`, `focused_pairs`, plus metadata-only `focus_enabled` and `identical_gate_enabled`; do not expose RGB content or model output.
5. **Synthetic benchmark and regression suite**, including outside-vs-inside region changes, identical reference refresh, request image decoding, original-frame provenance, malformed boxes, existing transport isolation, and timeout quarantine.

### Important fidelity trade-offs

- An ROI can improve pixel density for a small detail **but deliberately loses context outside the selected rectangle**. Only use a HUD crop for questions whose answer lives inside that crop. Change the host's active focus through a new authorized session, rather than letting the game/chat/model change the ROI in a live session.
- For a static gate, two different raw images may encode to the same bounded JPEG. That is safe only as a claim about the pixels *available to this particular model request*, not proof that the game is stationary. Engine-authoritative danger/success signals must bypass the visual-inference gate through their own trusted path.
- Crop-to-model image encoding still decodes the full raw RGB input before cropping in Pillow. It may reduce image resizing/JPEG work but is **not** a zero-copy high-speed pixel path. A later read-only stride-aware ROI extraction could further reduce CPU work and copies, with new zeroization/privacy tests.
- A JPEG equality check is cheap **after** encoding, but encoding itself still consumes CPU. The existing frame fingerprint and hardware preflight should remain earlier in the pipeline.
- The model and capture permissions are still independent. This feature cannot activate camera/window capture or streaming on its own.

## Reproducible local measurements (synthetic only)

Command: `python -m benchmarks.benchmark_stream_roi_vlm`. Twelve *pairs* of pre-generated synthetic 1280x720 RGB frames; all model responses provided by an in-process stub transport, with no HTTP. Representative run on the Star Linux development machine, October 28:

| Configuration | Median CPU time for two frames + request handling | Model requests |
| --- | ---: | ---: |
| Full-window comparison, change inside HUD | 21.706 ms | 12 |
| Fixed HUD focus ROI, change inside HUD | 5.606 ms | 12 |
| Full-window, byte-identical frames | 23.864 ms | 0 |
| Fixed HUD ROI, byte-identical frames | 5.336 ms | 0 |

The last two rows contain **23** avoided admissions each, because after the first reference, every later frame has the same bounded JPEG and refreshes the reference. Total request byte lengths were ~11,866 full and ~13,172 focused in this scene: **ROI did not reduce wire payload size here** because the crop preserved more detail. The result is an example of lower CPU preprocessing, not a claim that ROIs always shrink requests.

**What these numbers do not measure:** real model tokens/sec, model success rate, visual accuracy, Windows game FPS, OBS delivery, chat response, first audio, jitter, or perceived human-likeness. Run multiple repetitions and report distributions and model-specific differences before making any performance claim.

### Actual local multimodal smoke attempt (important negative result)

The Star Linux host has a loopback llama.cpp `star-fast` server advertised with a multimodal projector. A single authorized test with two **synthetic** 320x240 frames, downsampled to a maximum edge of 256 and a 30-second request timeout, **did not finish within the bound**. The worker returned `stopped=False`, `succeeded=False`, quarantined that request, and produced **no visual finding**; elapsed time ~30.065 seconds. This is one trial while the service had other active workloads, not a general speed estimate. It **does not establish a functioning realtime VLM**. Do not blindly re-request on timeout; independently confirm completion/recovery first.

This is a useful operational discovery: before the owner relies on the real-game vision chain, Star needs an idle-server test with explicit concurrency controls, smaller dedicated VLM candidate(s), response-schema acceptance tests and independent visibility into actual request completion. While streaming, the game must retain priority; visual commentary must be optional.

## Research integration: stronger gameplay intelligence without hype

**Visual harness (VISTA):** VISTA (October 1, 2026) reports strong gains from lossless visual memory, explicit inspection of historical frames/regions, pixel reads, and action history. Its published results are about the benchmarked models and environments, **not Star**. A next addition could provide Star's authorized game worker a RAM-bounded short-history frame store with TTL, no persistence by default, host-only inspect-region tools and encrypted opt-in long-term episode captures. Retrieval of old visual evidence should be separate from making a claim. This branch's fixed focus region is an early, narrowly scoped building block.

**Grounded, measurable gameplay learning:** Roblox's OpenGameEval has 84 core game-building tasks evaluated with executable Studio scene/play outcomes, and finds useful correlations between inspection and success. GameWorld tests 34 games / 170 state-verifiable tasks. A genuine Star gameplay improvement must improve held-out success, steps, failures, and transfers *under the same action budget*. Never count an LLM statement, screenshot color change or tool execution as an independently verified win.

**End-to-end game creation:** October 19's CEGame-Bench highlights an artifact-to-play gap: compiling a game is not the same as a player being able to launch, finish and resume it. Star's Roblox builder should use the official Studio MCP and playtest agent to run inspect -> plan -> build -> spawn player -> verify reachable goals -> fix -> retest, including UI, audio, collision and animation acceptance checks. Keep novel content generation separate from executable quality verification.

**General knowledge and autonomous intelligence:** Give Star trusted source-backed retrieval with timestamps, versioned skill snippets, testable practice problems, counterexamples, calibrated uncertainty and holdout sets. Only promote lessons to durable memory after reproducible checks. Run best-of-N builds on **genuinely hard** problems, reuse cached deterministic work, and stop early when a candidate satisfies the executable contract. Star Core Forge should preserve local diffs, experiment provenance, reproductions and rollbacks; GitHub is for optional review and publication.

## Research integration: more natural, responsible VTuber behavior

Natural behavior comes from coordinating timing and genuine experiences, not constant talking or fabricated human memories. Star can have a vivid consistent character identity and personality without claiming to be a biological person.

- **Turn timing:** distinguish viewer acknowledgments from true interruptions. LiveKit's March 19 adaptive interruption handling and the documented local CPU `v1-mini` turn detector are concrete candidates; compare a fully local implementation before relying on cloud-dependent behavior. Allow conversational pauses, rejoining mid-conversation and prompt-aware silence when focus matters.
- **Speech:** Kyutai's October 20 Pocket TTS 4.0.0 offers 18M/7M/experimental 2M variants, with CPU-oriented deployment. Test expressive naturalness, pronunciation, first-audio latency, TTS interruption recovery and CPU contention with game capture; do **not** assume small equals better. Do not imitate another person's voice without permission.
- **Animation:** treat eyes, head gaze, eyebrows, mouth, ribbons and twin-tail hair as a coordinated motion rig. Live2D wind/secondary physics and verified audio-amplitude-driven lip synchronization may be useful. Key expressions to actual accepted gaming/chat events. Never let a model-predicted victory trigger a victory motion without engine proof.
- **Personality:** retain authentic episodic context and anecdotes from game sessions, explain guesses as guesses, vary sentence lengths, and sometimes be quiet while playing. Store private friend/viewer details only with consent and reasonable retention; avoid inventing memories of offline experiences.

## Proposed staged acceptance gates

1. **Vision truth & speed:** on a dedicated *authorized* Windows game capture, compare full / focus / identical-gate modes on at least 50 held-out HUD changes and 50 negative frames. Record precision, recall, visual event latency, CPU costs, VLM actual response and rejection rates. Compare to the unchanged implementation, not only within the new version.
2. **Real visual memory and game learning:** introduce VISTA-style host-scoped inspection of a bounded number of past frames with no arbitrary network routing. Run blind GameWorld or Studio practice experiments against saved baselines; verify decisions with engine state, track action efficiency, not just screenshot plausibility.
3. **Game maker:** use a real Roblox Studio playtest with a robot player and structured acceptance checklist: no missing walls, false collisions, broken UI, unwinnable objectives, or unplayable input flows. Repeatedly evaluate until validation passes rather than producing one-shot code.
4. **VTuber experience:** implement a joined capture -> game-state verification -> response generation -> CPU TTS -> actual playback ack -> avatar expression pipeline; compare p50/p95 reaction latency, false interruptions, talk-over rate, lip-sync delay and FPS while streaming. Add a human blind review with identity disclosed as an AI streamer.
5. **Operational safety:** owner opt-in for game capture, vision, mic, OBS and posting; separate host privileges, session expiry, private-data retention, low-performance fail-quiet, and audit trails. Investigate repository visibility: GitHub currently reports `Star-AI-Private` as **public**, regardless of its name. Do not commit secrets or recordings.

## Research sources verified October 28, 2026

- VISTA, *A Visual Harness for Reasoning in an Interactive World* (posted Oct 1): https://arxiv.org/abs/2610.02200 ; https://github.com/joshhhhhan/VISTA
- Roblox OpenGameEval project and executable checks: https://github.com/Roblox/open-game-eval
- Official Roblox Studio MCP and playtest automation (Mar 5): https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- CEGame-Bench (posted Oct 19): https://arxiv.org/abs/2610.26098
- GameWorld benchmark and fine-control protocol: https://github.com/gameworld-project/GameWorld
- llama.cpp server multimodal chat-completion API and JSON schema: https://github.com/ggml-org/llama.cpp/tree/master/tools/server
- LiveKit adaptive interruptions (Mar 19): https://livekit.com/blog/adaptive-interruption-handling ; turn tuning: https://docs.livekit.io/agents/logic/turns/tuning/
- LiveKit local CPU turn-detector v1-mini: https://docs.livekit.io/agents/logic/turns/turn-detector/
- Pocket TTS v4.0.0 (Oct 20): https://github.com/kyutai-labs/pocket-tts/releases
- Live2D wind secondary motion reference: https://docs.live2d.com/en/cubism-editor-manual/cubism-ae-plugin-wind/

## Current status

**Implemented and locally verified:** focused pair preparation, optional identical-frame model-call suppression, metadata-only metrics, synthetic benchmark, offline regression tests.
**Not implemented or proven here:** real Windows game model inference, visual-memory inspection, autonomous game control, playing games skillfully, faster model tokens/sec, live OBS/VTuber integration, humanlike speech, game-builder acceptance or new general neural intelligence. All higher-risk capabilities remain behind separate owner authorizations.
