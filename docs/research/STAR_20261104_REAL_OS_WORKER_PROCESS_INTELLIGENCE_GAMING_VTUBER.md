# STAR 2026-11-04 — Host OS-worker identity bridge, intelligence and VTuber research

**Scope:** Actual Python implementation + offline tests + an evidence-based engineering roadmap. Not a live gaming/OBS rehearsal, trained model, faster neural inference measurement or claim of AI consciousness. Keep stacked draft pull requests unmerged pending independent checks.

## Major infrastructure gap found and addressed

Previous work created a host model catalog, on-disk cryptographic preflight, process-epoch isolated latency, and output-reply fencing. But the HostWorkerEpochRegistry only consumed process observations supplied by a caller. It could not itself establish whether the declared process was truly running.

This iteration adds **star/stream_host_process_supervisor.py**: a read-only, disabled-by-default host bridge using psutil (already in desktop requirements). On enrollment it verifies a supervisor-selected process ID, creation time, true executable path, same file as the verified manifest runtime, and a fresh SHA-256 hash through the preflight artifact reader. It rechecks the process on both sides of hashing. On refresh it checks liveness, birth identity, executable file identity and monotonic observation order *without hashing on every gameplay frame*. Failure retires the worker epoch; stale replies cannot pass the existing HostWorkerReplyFence afterward.

**Limits:** Not an OS credential, not verified in-memory model weights or injected DLLs, not proof of executable arguments, not an audio/OBS/game controller, not an input authorization, and not a guarantee that a process cannot exit immediately after the check. Windows checks are subject to weaker file-identity guarantees than Linux descriptor-anchored paths. The trusted launcher must restrict process selection to its own launched workers.

## Primary-source research (verified on 2026-11-04)

**1. Roblox agents should inspect before editing.** Roblox OpenGameEval was initially announced with 47 curated cases in December 2025. An updated October 2026 paper/repository reports 84 human-curated tasks, 13 frontier models and 16 attempts per task, including quantitative evidence that inspecting affected objects before editing predicts stronger success. This suggests requiring scene inspection, dependency discovery, plan, diff, executable tests and visual reinspection—not simply generating longer Luau outputs. Source: https://arxiv.org/abs/2610.02563 ; https://github.com/Roblox/open-game-eval ; https://about.roblox.com/newsroom/2025/12/opengameeval-benchmark-agentic-ai-assistants-roblox-studio

**2. Game development needs visual evaluation.** The February 2026 GameDevBench preprint has 132 tasks, while the evolving repository now lists 333. These are different benchmark versions; do not transfer scores across them. Use pinned benchmark versions and evaluate shaders, sprites, animation, gameplay, and UI with screenshot/video reviews in addition to code checks. Sources: https://arxiv.org/abs/2602.11103 ; https://github.com/waynchi/gamedevbench

**3. Deliberation latency matters in moving worlds.** October 2026 RT-SAFE finds substantially more collisions during real-time embodied evaluation than static evaluation despite similar task completion. This was not a Star or gaming benchmark. The transferable principle is to measure screenshot-to-action latency, timed world changes, action acknowledgements, failure recovery, and *safety/accuracy per real-time second*. Source: https://arxiv.org/abs/2610.09294

**4. Natural VTuber speech means choosing silence.** Microsoft Proact-VL (ICML 2026) models streaming perception, voluntary speech timing and controlled content length for solo game commentary, co-commentary and guidance. Star's commentator should score novelty, relevance, urgency and recent-speech debt before speaking. The owner speaking, dangerous gameplay or lost OBS frame headroom should suppress low-priority chatter. Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

**5. Backchannels differ from real interruptions.** Microsoft's RESPOND (March 2026) introduces controllable backchannel intensity and turn-claim aggressiveness. LiveKit's adaptive interruption aims to distinguish true barge-ins from acknowledgments but its adaptive model has cloud requirements/quotas even when self-hosting; a local VAD fallback should be evaluated separately. Sources: https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/ ; https://docs.livekit.io/agents/logic/turns/adaptive-interruption-handling/

**6. CPU TTS competes with CPU, not only GPU.** Kyutai Pocket TTS now offers October 2026 English variants with approximately 18.2M, 6.9M and 1.9M parameters. Evaluate naturalness, first PCM audio delay, pronunciation, expression, real-time factor and CPU contention during actual games; do not assume the smallest model is always the best. Source: https://kyutai-labs.github.io/pocket-tts/

**7. Speed requires task-level quality measurement.** llama.cpp's SPEED-Bench reports throughput, latency and speculative-decoding acceptance. Compare prompt caching, draft models and CPU/GPU placement at fixed model, prompt, temperature, context length and load scenario. Measure correct answers/actions per second as well as tokens per second. Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

**8. Use officially supported Studio agent interfaces.** Roblox's built-in Studio MCP supports playtest control and simulated input and is preferable to ad-hoc undocumented automation when developing Roblox games. Sources: https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ; https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic

## Specific system expansion roadmap

**Reactive intelligence (milliseconds):** event detectors, bounded screen-to-input controller, verified game state, input-release watchdog, locally planned micro-actions. Never allow deep reasoning to delay release of a key or completion of a safety-critical input. Require authorized game automation and platform compliance.

**Tactical learning (seconds):** hierarchical skills for camera, movement, navigation, combat, puzzles, inventory and cooperative play. Teach via progressively difficult local/private scenarios; separate training seeds from withheld evaluation seeds; log verified action outcomes and recovery actions. Score transfer to new maps, mechanics and difficulty settings—not only number of practice attempts.

**Deep cognition and creation (idle/episode boundary):** high-quality retrieval from dated sources; best-of-N competing solutions; code analyzers (Luau, Rust, Python, TypeScript); independent unit/integration tests; Roblox Studio playtests (including multiplayer), image/video artifact inspection and rollback. Improve the reasoning harness and retrieval before claiming neural intelligence increases.

**Persistent identity, hobbies and general knowledge:** a bounded autobiographical event store holding verified episodes, personality/voice presets, user-approved memories, source provenance and explicit uncertainty. Diverse curiosity tasks (games, animation, art, music/audio, software, science, engineering and social skills). Avoid fabricating experiences or presenting performed emotions as measured subjective consciousness. Always identify the streamer as AI.

**Humanlike VTuber delivery:** choose when *not* to speak; short event-grounded callouts; interruptible spoken responses; natural hesitation only when purposeful; controlled humor; expressive voice tied to actually observable game state; lips and captions synchronized with *consumed device audio*, not completed TTS text. Always mute/flush PCM and neutralize avatar after a failed worker epoch.

**Resource scheduler for 8-GB VRAM:** game+OBS+avatar audio must outrank background rendering, training and deep research. Reserve actual free GPU memory separately from GPU utilization. When under pressure, defer lower-priority vision and move approved TTS to a measured CPU path. Benchmark idle, game-only, stream-only, game+stream, and game+stream+voice separately.

## Integration handoff and proof criteria

1. In a private Windows-only service, the owner-controlled launcher creates the approved worker and pins an OS process handle. After verifying all model/runtime/voice manifest files, it enables the new host supervisor and attaches only the PID it launched. The declared runtime artifact must be the actual executable, not merely a Python script passed as a command argument. Script argv/model-load attestation is future work.
2. Before every dispatch, refresh the worker epoch, bind the inference job via HostWorkerEpochRegistry, and admit with workload-specific QoS. Untrusted prompts, viewers, Discord and game overlays cannot supply process identity, digests or resource telemetry.
3. Before output, refresh again and require HostWorkerReplyFence, the independent pre-play snapshot and actual playback host. On process death/clock rollback, revoke the epoch and **physically flush queued PCM and captions**, release controls and neutralize the avatar. The new Python module does not perform these physical actions.
4. Run a **local, nonbroadcast Windows rehearsal**: real game observation, authorized controls, short spoken responses, visible avatar and local OBS recording. Include forced worker crash/restart, PID reuse, invalid file identity, loss of GPU headroom, missed input ACKs and owner interruptions. Verify no stale speech plays.
5. Keep new autonomy OFF by default until testing. No automatic public streaming, purchases, account creation, game input injection or social messages without existing authorization.

## Evidence scoreboard (suggested targets, not achieved results)

| Subsystem | Evidence required |
| --- | --- |
| Fast inference | First-token and full-answer p50/p95; tokens/s; correct validated tasks/s across each real load profile |
| Gaming | Holdout-level completion/win rate, frame-to-action p95, missed ACKs, safe key release, verified recovery |
| Roblox development | Pinned OpenGameEval pass@1/pass@k, Luau static analysis, Studio playtest pass, multiplayer/client/server results, independent visual checks |
| General knowledge | Source relevance, dated claim verification, contradiction checks, calibrated uncertainty on unseen questions |
| Speech | Audible-first-PCM p95, false barge-in rate, interruption recovery, word intelligibility, listener naturalness ratings |
| Streaming | OBS skipped/dropped frames, GPU/CPU frame time p95, avatar/audio synchronicity, successful private-recording test |
| Worker integrity | OS PID+birth, verified actual executable identity, post-restart stale output denial, replay protection, explicit physical output stop |

**No gaming/OBS/voice rehearsal or hardware-specific speedup was completed by this research and code change.** Main remaining technical obstacles: trusted Windows launcher integration, actual executable/process-handle attestation, model-weights-in-memory identity, PCM device callback wiring, and separately verified task outcomes.
