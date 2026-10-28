# STAR: hardware-audible sample ledger, gaming intelligence, and natural VTuber roadmap
Research and engineering review: 2026-10-28. Experimental opt-in host adapter; not a live Windows driver, production stream, or evidence of model retraining.

## 1. What was implemented

PR #758 introduced StarPlayoutClock, which maps an authorized playback cursor to stage motion. That primitive did **not** connect to a device's sample clock. This change adds star/stream_audio_sample_host.py and offline tests. DeviceAudibleSampleHost binds a prearmed and already audible stage turn to a bounded PCM frame count and accepts *device-attested, actually played* sample counts from a host-owned backend. It converts them to seconds, passes them through StarPlayoutClock's plausibility and freshness checks, and yields revocable rig poses.

Implemented and tested synthetically:
- Owner approval and fail-closed default; no implicit streaming, capture, microphone, OBS, VTube Studio or game control.
- Identity-only audio epochs: a stale output callback from a previous utterance cannot interrupt the next one.
- Audio must already be acknowledged audible and the exact stage plan must be armed; PCM duration must match the planned track within 20 ms.
- 8,000-192,000 PCM frames per second and at most 15 seconds per utterance. A frame is a sample-time across all channels, NOT an individual scalar channel sample.
- Consumed-frame counts must be monotonic, bounded and rate-checked. First zero-frame callbacks cannot animate speech before any frame is heard. Pauses, completed speech and stalls suppress motion.
- Fresh rig frames must be rechecked with current(epoch, frame) at the final render boundary, and neutral parameters must be sent on interruption.
- Stopping or disabling active audio requires the host's positive acknowledgement that the physical output has stopped and its queue is flushed. That attestation is not physical proof.
- Aggregate counters only; no transcripts, names, voice recordings, viewer identities or raw frame payloads.

**Limitations:** no Windows sound device driver, audio playback, native VTube Studio WebSocket client or OBS client was added. The device backend must obtain *consumed* PCM frames; model-generated or merely queued PCM length is NOT a valid replacement.

### Reference integration flow (host-only, not a model tool)

1. The authorized host prepares a StarStage plan and starts real speech output. It calls StarStage.acknowledge_audible only when its physical playback path confirms audibility, never when TTS first yields bytes.
2. The host prepares an exact-duration motion track via StarPlayoutClock.arm, enables DeviceAudibleSampleHost(owner_approved=True), and binds a plan plus sample rate and total PCM frames.
3. An off-audio-thread observer reads consumed output frames with a monotonic observation timestamp and calls report_played(epoch, played_samples, sampled_at).
4. The render loop calls sample(epoch), then current(epoch, frame) immediately before transmitting rig parameters. Send neutral state instead of rejected frames.
5. On pause, output stop, underflow, focus loss, device switch or cancellation, stop/flush audio and neutralize the rig. An old epoch cannot reanimate speech.
6. On device disconnect or unknown clock, fail closed and restart with a fresh epoch.

### Critical hardware clock distinction

- **Windows WASAPI:** Microsoft's IAudioClock::GetPosition reports current stream position plus a correlated performance counter. Position units must be interpreted using GetFrequency; subtract the stream-specific origin and account for resampling. IAudioClock2::GetDevicePosition reports device frames in shared mode, which can use a different device sample rate. These are proposed integrations, not currently implemented.
- **PortAudio/sounddevice:** outputBufferDacTime describes when the *first sample of a callback output buffer will reach the DAC*, not proof the entire buffer was heard. Callback 'frames' counts queued buffers, not played frames. Do not feed them directly as audible position. Correlate stream clock with actual playhead first.
- The PortAudio callback is high-priority and deadline-sensitive. No AI inference, web I/O, file I/O or heavy renderer work in it. Send minimal timestamp/counter data to an off-real-time queue. Audio loopback calibration should be temporary and owner-approved, with no private viewer recordings.

Primary docs:
- Microsoft WASAPI clock: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock-getposition
- Microsoft IAudioClock2 device frames: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclock2-getdeviceposition
- PortAudio timestamps: https://files.portaudio.com/docs/v19-doxydocs/structPaStreamCallbackTimeInfo.html
- Python sounddevice callbacks: https://python-sounddevice.readthedocs.io/en/0.5.3/api/streams.html

## 2. Natural VTuber behavior: a technical architecture

A delightful humanlike stream is a timing, grounding, character and animation problem, not a longer persona prompt.

**Fast interaction lane:** consume trusted game events, chat-queue timestamps, turn detection and output-audio sample counts. Keep audio/render callbacks CPU-light and nonblocking.

**Deliberate thinking lane:** current objective, verified game state, next permitted action, known cooldowns and viewer questions. Use expensive vision or reasoning only when useful. Cache stable context for local inference; measure cold/warm first-token time instead of assuming KV reuse.

**Personality lane:** warm spontaneous remarks, humor and playful normal/cat/puppy modes should reflect the real scene. Star can laugh, purr or meow where appropriate, but should not fabricate a win, friendship, human identity or life event. Persistent memories should record actual digital experiences with provenance and support correction.

**Expressive rig lane:** lips synchronized to *heard* audio; artist-designed blinks, gaze, head motion and twin-tail hair/ribbon physics. Normalize parameter ranges and honor reduced motion. Allow quiet concentration so she is not continuously talking over gameplay.

**Interruption lane:** distinguish mid-sentence hesitation from a real completed user turn. On listener interruption, stop speech, revoke old expression frames and avoid stale laughter. Viewer chat never grants new tool permissions.

**Voice candidate review:** Kyutai Pocket TTS v4.0.0 introduced 18M, 7M and experimental 2M English variants Oct 20, 2026, followed by v4.0.1 Oct 21. CPU use could leave more RTX 4060 VRAM for gaming, but pronunciation, expressivity, laughter, first-audible latency and sustained listening quality need actual A/B tests. Do not clone a real voice without rights and consent.

**Avatar integration:** VTube Studio documents parameter listing and InjectParameterDataRequest. An authenticated localhost plugin may map Star's normalized motion into documented model parameters after verifying the loaded model. Do not enumerate full parameters at 60Hz. Live2D Cubism maps lip-sync IDs in .model3.json and can apply artist-authored physics for wavy hair. A 2D transform alone is not full-body physics.

Sources:
- Pocket TTS releases (Oct 20-21): https://github.com/kyutai-labs/pocket-tts/releases
- LiveKit local turn detector: https://docs.livekit.io/agents/logic/turns/turn-detector/
- VTube Studio public API: https://github.com/DenchiSoft/VTubeStudio
- Live2D lip sync (Jan 29, 2026): https://docs.live2d.com/en/cubism-sdk-manual/lipsync/

## 3. Improve Star's effective intelligence beyond parameter count

**Verified gameplay loop:** game observer -> hypothesis -> permitted action -> independent state receipt -> reward/error analysis -> hard-mechanic rehearsal -> unseen holdout game. Prior STAR paired-vision and signed-truth experiments supply some evaluation primitives; real authorized Studio/device observers, action execution and independent graders are still outstanding. Evaluators must remain separate from model predictions.

**Increasing challenge:** earn difficulty through measured competency, not model declarations. Start with deterministic timing, move through delayed rewards and interacting mechanics, then unfamiliar environments. Preserve baseline, game build, seed, action sequence, success criterion, time budget and hardware load for each trial. Randomize unseen levels and reject overfit gains.

**Game creation:** inspect Studio hierarchy before editing. Verify executable behavior, missing parts, attachment alignment, prop collisions, reachability, legible UI at multiple resolutions, animation curves, textures/UVs, sound, and FPS. Best-of-N candidate work should compete on playability, design quality and performance; accept only independently passing results. Successful Luau compilation is not sufficient.

**General knowledge:** maintain separately (a) cited external documents with license, timestamps and scope and (b) firsthand verified experiences with reproducibility metadata. Record uncertainty and use retrieval to narrow questions. Unverified web text must never gain system or tool authority.

**Core Forge:** autonomously propose experiments, execute isolated tests, score held-out cases, and keep reversible histories. Model-driven self-modification must not alter evaluator labels, critical policy, permissions or production gates. GitHub can serve as optional review/release mirror, not Star's internal development dependency.

Recent supporting research:
- VISTA active exploration and harness graph (Oct 26, 2026): https://arxiv.org/abs/2610.35051
- Roblox OpenGameEval stateful executable tests (2026): https://github.com/Roblox/open-game-eval . The 2025 Roblox newsroom's initial 47 cases differ from the 2026 paper's 84 core tasks.
- GameWorld (April 2026), 34 games / 170 verifiable tasks: https://gameworld-bench.github.io/
- llama.cpp prompt KV slots, batching, metrics and speculative decoding: https://github.com/ggml-org/llama.cpp

## 4. Performance architecture for RTX 4060 / 32 GB target

During gameplay, prioritize deadlines for game rendering and actual audio output. Visual model or video generation saturation can damage game FPS and streaming quality even when textual reasoning improves.

Recommended *experiment*, not proven speedup:
- Roblox + OBS: reserve required resources and measure 1% low FPS plus render, encoder and network losses separately.
- Fast CPU lane: device playout, turn/voice activity detector, lightweight event classifier and pose mapping.
- Opportunistic local small model: rapid game tactics/chat with stable prompt prefixes and bounded responses.
- Costly VLM/planner: event-triggered visual attention and task-aware frame selection instead of full-screen inference on every frame.
- Long-running tests: Core Forge and big image/video models only during adequate spare compute or scheduled off-stream windows; support cancellation and rollback.

Optimize **verified task success per wall-clock second while game and OBS QoS hold**, not raw tokens/s alone. Cache hit rate, first audible sound, drop rates, input-to-action p95 and owner listening score should be measured.

## 5. Real Windows acceptance gates before use on air

Current tests are synthetic, Linux-hosted, with no physical audio driver. The numbers below are proposed acceptance targets, not observed results.

1. Measure played-frame clock and rig output against authorized loopback test audio; record median and p95 lip/audible skew, device drift and stop-to-neutral latency.
2. Use at least 60 deterministic spoken clips at 15/30/60 render FPS; reject wrong-turn animation, mouth-before-audio, stale or unbounded cues.
3. Inject 50/150/400 ms output stalls, change output devices, interrupt halfway and force stream-stop. Old epochs cannot revive motion.
4. Under Roblox + OBS, compare the same game baseline against active speech/vision: FPS, 1% lows, OBS renderer/encoder/network losses, VRAM/CPU, p95 speech onset and avatar update time.
5. Run blind paired human listening for voice expressivity, laughter and pronunciation; preserve reduced-motion and OFF-by-default toggles.
6. Verify VTube Studio plugin authentication and correct neutral behavior on bad parameters or dropped WebSocket sessions.
7. Run permitted game learning with independent game-state labels and at least one completely unseen level/game, testing generalization.
8. Review repository visibility before including private media or any viewer data; draft PR and owner review before merge or deployment.

## 6. Honest outcome

This update adds a tested sample-to-playout bridge and a researched engineering plan. It does not include an actual WASAPI/PortAudio observer, real speech output, a complete avatar plugin, new model weights, autonomous gaming, higher tokens/s or proven broadcast naturalness. Real hardware, game and listening acceptance remain mandatory.
