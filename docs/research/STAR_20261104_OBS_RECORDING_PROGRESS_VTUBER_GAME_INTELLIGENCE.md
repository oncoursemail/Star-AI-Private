# Star AI — OBS recording-progress evidence and next-generation gaming / VTuber intelligence

**Research and implementation date:** November 4, 2026.
**Status:** Implemented offline-only OBS progress verification; all other directions below are **research / engineering proposals**, not demonstrated new model intelligence or gaming performance.
**Dependency:** builds on PR #974 (active private OBS recording observation). No public-stream authority and no OBS write calls.

## 1. The concrete gap fixed in this iteration

PR #974 could observe OBS reporting an **active, unpaused recording** while OBS reported broadcasting inactive. Those two booleans can remain true even when a recording stalls, the recording is restarted, or bytes are not being produced. The protocol exposes numeric **outputDuration** (milliseconds) and **outputBytes** in `GetRecordStatus` [1].

The new optional `require_recording_progress` mode:

- Is **off by default**. Requires both the trusted host's explicit permission and private recording observation; it rejects accidental independent use.
- Validates both counters as bounded nonnegative exact integers (no booleans, coerced strings, nonintegral floats, NaN, or infinity).
- Requires recording duration to increase strictly between authenticated, ordered triplets, and rejects unphysical forward jumps larger than the independently measured elapsed time plus a 1,000 ms tolerance.
- Rejects regressing byte counters, consistent with rejecting silent recording replacement and counter resets. Buffered encoders may not emit bytes every sample, so individual equal-byte samples are allowed.
- Provides the privacy-minimal report flag **recording_progress_verified** only after at least two valid samples with a positive observed byte delta and duration growth. If bytes have not advanced across the observation window, the host returns **deferred**, not eligible.
- Preserves OBS v5 read-only request allowlist, nonce matching, broadcast-off check, zero output-changing requests, bounded sampling, and explicit credentials supplied only through a trusted host.

**Read-only host example (after someone has already started a local recording):**

```text
STAR_OBS_WEBSOCKET_PASSWORD=<set-in-private-host-environment>
python -m star.stream_obs_local_readonly_probe --observe \
  --verify-private-recording --verify-recording-progress \
  --samples 5 --interval-ms 500
```

Never put the real password into a shell command history or model prompt. This command performs a private local read-only check; it neither starts OBS nor records anything. Return fields contain only aggregate evidence, no path, file bytes, chat, audio, waveform, keys or event text.

**Important limitation:** OBS status samples—even with monotonic bytes—do not prove which final video file was saved, whether its video frames contain the game, whether Star is audible, or whether the avatar actually moves. The encoder might buffer bytes and cause a harmless deferred report. An authenticated local OBS endpoint is still not an independent file-content attestation. A real offline recording needs a separate trusted file-identification / output-track provenance step and `stream_av_recording_host.py` verification [2].

## 2. The correct full-stack rehearsal

Run privately, on an owner-authorized Windows desktop. Preserve OBS broadcast disabled throughout, use a test game / isolated Roblox Studio playtest, and keep the avatar + generated speech on isolated audio routing. Record privately and independently validate:

| Independent witness | Measurement | Acceptance required before claims |
| --- | --- | --- |
| Running OS / AI worker | verified process epoch and loaded-model origin | No stale worker output |
| Game client and action witness | actual frame timestamps, action authorization, game outcomes | Inputs obey scope; wins/score validated by environment |
| OBS read-only v5 | rendering/encoding skips, active recording, zero streaming, recording time/bytes progression | Strict sampled state and monotonicity |
| Saved recording | local path verified by host, content digest, FFprobe stream metadata | Actual stored frames/audio, no network media |
| Speech / avatar | decoded audio envelope versus rendered mouth aperture | Cross-correlated time series, measured lip-sync |
| System pressure | GPU VRAM, GPU/CPU utilization, p50/p95 speech and reaction latency | No game frame collapse or OOM |
| Privacy | no tokens, usernames, raw chats or voice dumps in telemetry | Only sanitized owner-reviewed aggregate data |

Do **not** label a private rehearsal 'passed' based only on a textual report created by the model, OBS active flag, `llama-server` token speed, or an unexamined recording file. Keep the private artifact local and owner-approved.

## 3. Intelligence, learning, and faster inference: evidence-based priorities

**Fast-path and deep-path architecture:** One small high-priority controller selects game actions within a hard real-time budget. A second agent plans strategies asynchronously. A third low-priority researcher builds and evaluates skills between sessions. The fallback for missed deadlines is safe inaction / an allowed deterministic action, never an old strategy applied to a new scene. Every controller output must bind to a fresh game-frame or scene epoch.

**Knowledge and coding:** Add retrieval of verified notes with provenance/date; confidence calibration; a sandbox to execute candidate Luau/Python/Rust code; independent tool-driven checks; and an error ledger keyed by reproducer, fix, and regression test. Best-of-N improves quality only if tests are independent and a holdout suite remains unseen. Don't retrain or alter code based on self-reported success. Keep internal offline-first Forge history, review, rollback, experiment provenance and optional GitHub publication.

**Speculative decoding:** The llama.cpp SPEED-Bench compares full request latency, prefill/decode throughput, and draft acceptance; it supports controlled baseline-versus-speculative runs [3]. Benchmark both offline and *under concurrent game + OBS + VTuber load*. A draft model using extra VRAM can be a regression on an 8 GB GPU; reserve memory for game render first. Collect accuracy and success metrics alongside latency, so faster output does not silently degrade correctness.

**CPU-first voice experiments:** Kyutai's Pocket TTS documents streaming CPU speech, 100M parameters and new October 2026 smaller English variants down to ~1.9M parameters [4]. These figures are the project's claims; quality, voice continuity, license, acoustic artifacts, first audible PCM latency and CPU contention must be measured on Star's actual computers. Compare A/B with existing voice in short-game scenarios while voice and game rendering are concurrent.

## 4. Game learning: teach Star to play well, not merely describe a game

Set up progressively harder tasks across movement, navigation, reaction timing, camera tracking, spatial reasoning, puzzle solving, resource planning, fighting, cooperating and recovery from mistakes. Start with allowed **offline/local games or explicit sandbox playtests**; do not evade anti-cheat or claim authorization for arbitrary multiplayer input.

Capture signed-by-host *observation → action → resulting state → score/reward → failure reason* transitions. Use behavioral cloning of consented successful examples initially, then curriculum learning and self-play in a controlled environment. Split training and evaluation by maps, seeds and opponents; do not let Star grade her own outputs. Unity ML-Agents documents PPO/SAC, imitation learning, curriculum, self-play and environment randomization [5]; it is a useful reference architecture, **not** a claim that it works out-of-box in Roblox.

For game creation, Roblox Studio's built-in MCP integration (March 5, 2026) and April playtest-agent beta provide an official foundation for inspect → edit → start playtest → simulate player → read errors → verify on an unfamiliar test → revert on failures [6][7]. Use feature flags, independently checked diffs, finite resource budgets and automatic regression tests. The agent's Studio plugin credentials must be least-privilege; do not distribute test-game access to public stream viewers.

### Quantitative learning gates

- Success rate across **unseen** maps/levels, held-out against the development examples.
- Average and p95 environment-verified action deadline misses; time from changed game state to valid control.
- Regression rate on previously mastered tasks after new training.
- Independent rubric score for game UX, correctness, motion, sound, lighting, accessibility, and multiplayer synchronization.
- Reproducibility: model digest, environment version, seed, code commit, tests, and one sanitized session identifier.

## 5. Making the VTuber *convincing, entertaining and grounded*

The goal should be **humanlike presentation**, not deceptive human identity. Make Star visibly AI and avoid falsely claiming subjective experiences or relationships. Build consistent personal interests, a show format, warm banter, spontaneous but grounded humor, and durable memories derived from **verified** episodes rather than fabricated experiences.

A proposed live director should compute a *speak / stay silent / respond / interrupt* policy based on actual game action, viewer turn-taking, stale-state fences, speech playback and current conversational priorities. Proact-VL (ICML 2026) specifically evaluates timely commentary and guidance instead of constant narration [8]. Preserve output origin checks and cooldowns to avoid repetitive speech. Let viewers interrupt gracefully; finish or fade out current audio based on audible output and valid turn ownership, not generated text alone.

Animation: drive eye gaze, blinks, ear/hair/physics, hand poses and emotion blendshapes from one structured event stream with confidence/priority and a reduced-motion setting. The actual microphone output track, not the intended phonemes, should drive lip-sync. Maintain a persona continuity ledger of preferences, goals, recurring jokes, game episodes, social interactions that participants approved, and uncertainty. Social memory retention, moderation, and viewer consent should be explicit, with a privacy-preserving delete path.

**First minimum viable episode:** 10-minute offline rehearsal: launch a safe local game, generate context-appropriate voiced remarks, capture actual scene and audio, react to observed successes/failures, prove avatar response and smooth game frames, collect sanitized metrics, then evaluate the stored recording. No public broadcast until owner approval.

## 6. Staged next actions

1. Verify new strict recording-progress mode on synthetic/replayed OBS responses; ensure paused, streaming, restarted, invalid and stalled cases defer or reject.
2. Run the complete offline stream/game regression, type check changed modules and cross-check published GitHub blobs against the exact tested tree.
3. With OBS explicitly configured and a private recording already started, use real OBS WebSocket to check duration and byte progression for multiple seconds. This is not yet performed by this patch.
4. Bind the OBS sampled recording session to the **finished local artifact** through a trusted OS host with fixed allowed directories and file fingerprints, then decode independently to check actual speech and mouth movement.
5. Only after an actual media+game rehearsal should Star's automatic optimizer compare paired baseline/variant results and promote improvements with rollback support.

## Sources (read November 4, 2026)

[1] OBS WebSocket v5 generated protocol (GetRecordStatus fields), https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.json
[2] FFprobe official metadata/frame inspection documentation, https://ffmpeg.org/ffprobe.html
[3] llama.cpp official SPEED-Bench README, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
[4] Kyutai Pocket TTS project documentation and October 2026 model note, https://kyutai-labs.github.io/pocket-tts/
[5] Unity ML-Agents examples, curricula and self-play, https://github.com/Unity-Technologies/ml-agents
[6] Roblox Studio built-in MCP announcement, March 5, 2026, https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
[7] Roblox Studio playtest agent beta, April 9, 2026, https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767
[8] Proact-VL paper / ICML 2026, https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
