# STAR AI — 2026-11-04 Private Windows Gaming / VTuber Readiness and Intelligence Roadmap

**Status:** Research + working passive readiness command; no gaming/voice/OBS/avatar full-stack rehearsal completed. This branch stacks on draft PR #969 and must not be merged until predecessors and independent CI are reviewed.

## Why this iteration is different

The repo already contains many standalone Stage/OBS/PCM/VTube Studio/game-action/worker-epoch checks. More disconnected gates will not make Star stream naturally. The highest-value missing engineering result is **an actual measured Windows private rehearsal**. This iteration adds a single command that combines existing time-windowed NVIDIA memory + Windows process evidence and produces privacy-limited JSON blockers. It can be run without starting/stopping applications or publishing media. A positive report is only a *candidate*: it cannot assert game frames, audible voice, avatar frames or OBS recording.

### Actual connected Windows snapshot (2026-11-04)

From the authorized `Main` Windows desktop (read-only):
- NVIDIA GeForce **RTX 3060 Ti, 8192 MiB**, reporting **7624 MiB free and 0% GPU compute utilization** in a one-off `nvidia-smi` snapshot.
- OBS Studio executable installed and FFmpeg / ffprobe available in PATH.
- **No** matching OBS, Roblox, VTube Studio, or llama-server processes running at the snapshot. No conclusion about availability of VRAM once a game, renderer, model and voice generator are loaded.
- Python 3.15, `psutil` and `pytest` are available. The command uses only current stdlib plus repository's existing psutil reader.
- **Actual newly built CLI executed on Main**, 5 consecutive read-only samples spanning **5,384 ms**: `status=deferred`, **minimum free GPU memory 871 MiB**, peak GPU compute 26%, local inference model process recognized, OBS and avatar process absent, no pinned game process. It asserted `authorizes_broadcast=false` and **all four physical proof flags false**. This is distinct from the earlier one-off 7,624 MiB free observation; the machine's headroom changed while the session was being inspected. The tool did not start, stop, or reconfigure applications.

These snapshots directly explain the blockers. It is not a streaming FPS/audio/network benchmark. Never label this measured readiness as "game mastered", "faster LLM", or "stream passed".

## New operational command

On a Windows machine with STAR's repository, run:

```powershell
py -m star.stream_windows_private_rehearsal_cli
py -m star.stream_windows_private_rehearsal_cli --observe
# When an actual permitted game is running, pin its REAL PID and exact process basename:
py -m star.stream_windows_private_rehearsal_cli --observe --game-pid 1234 --game-exe RobloxPlayerBeta.exe --samples 5 --interval-ms 500
```

Default: **no host observations** and JSON `explicit_observe_flag_required`. With `--observe`, the report uses 5 samples over ~2 seconds, checks OBS/avatar/model identities, a pinned game PID and birth time, sustained GPU memory and utilization, and detects replaced/restarted processes. No process name, PID, path, VRAM UUID, credential, game text, image or audio is reported. No pin means the game prerequisite is missing; don't silently treat a generic process as a game. A PID paired with shell/interpreter/OBS/model executable is rejected. Even a `candidate` does not operate a game, verify frames, play PCM, start recording or authorize broadcast.

For security, do **not** derive `--game-pid` or `--game-exe` from untrusted Twitch chat. A local operator or trusted game launcher must choose that identity. An arbitrary exe name does **not** prove it is a game; actual on-screen frame / game event evidence must be checked separately.

## Next controlled Windows acceptance (ordered)

1. **Local no-broadcast scenario:** Preflight on Main with OBS/game/avatar/model/voice actually launched through their authorized local hosts. If any blocker appears, stop rather than spoof the missing identity. OBS Stream output must remain OFF; use a local recording with a verified output-state witness. Do not broadcast to test a hardware path.
2. **Independent physical witnesses:** Timestamp observed game frame presents, actual game input acknowledgments and outcome checks, consumed (not queued) PCM samples, VTube Studio parameter acknowledgments, and OBS recording status/file integrity. Do not infer real-world playback from text generation, an API return, or a screenshot.
3. **Load profile separation:** Repeat idle, game only, rehearsal stream only, and game+OBS+avatar+voice scenarios. Record GPU minimum free memory and maximum utilization, 1% low FPS / present gaps, event-to-control and event-to-audible-commentary P50/P95/P99 latencies, reply cancellations, and audio-avatar skew. Route model profiles and worker epochs to the correct load class.
4. **A/B optimization:** Compare baseline local CPU voice vs small Kyutai Pocket TTS candidates under the *same* concurrent game workload and actual rendered sound. Compare llama.cpp baseline vs tuned KV/prompt-cache/speculative-decoding under the **same prompts, output sizes, quality suite and measured VRAM pressure**. Prefer successful verified tasks per second, not unsupported tokens/sec projections.
5. **Generalizing gameplay:** Build isolated, permitted practice environments with deterministic success/failure receipts; add unseen holdout levels, novelty to prevent memorized routes, checkpointed curriculum, skill regression and human/automated gameplay review. Avoid automating competitive games that forbid bots.
6. **Roblox Studio game creation:** Use Studio's official built-in MCP/playtest APIs to inspect the data model first, implement candidate improvements, launch playtest/multi-client simulation, collect trace + visual evidence, and only promote code that passes functional, visual, latency and permissions checks.
7. **Natural VTuber personality:** Proactive *selective* speech (event salience, silence, fatigue/interruptions), turn-taking/backchannels, natural voice pacing and emotions linked to verified game events, lip/mouth motion tied to **consumed** PCM, scene-aware episodic memory, hobbies and context-sensitive humor. Do not overclaim consciousness or deceive viewers about Star being an AI.

## Research sources and engineering implications (accessed 2026-11-04)

- **Proact-VL, March 2026:** streaming video understanding + learned response trigger + controllable commentary. Practical idea: budget-gated event trigger, not full VLM reasoning on every frame. Evaluate false/missed commentary and social timing, not only text quality. https://proact-vl.github.io/
- **Kyutai Pocket TTS (October 2026):** CPU-targeted 18.2M/6.9M/1.9M English model variants offer potential GPU relief, but timbre, hallucinated words, prosody and English-only constraints of the smaller models require blind audio + host latency acceptance. No claimed speedup on Star's hardware without a benchmark. https://github.com/kyutai-labs/pocket-tts
- **llama.cpp SPEED-Bench (2026):** benchmark an already-running server with per-category prefill/decode throughput, end-to-end latency and speculative draft acceptance; compare baseline/speculative with identical prompts. Memory placement can turn an apparent speedup into worse GPU contention. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- **Roblox Studio built-in MCP and playtesting (March 5, 2026):** supported external AI-assisted Studio connection, start/stop playtests, simulated player input. Do not substitute undocumented mouse macros for official test loops. https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- **Roblox Studio agentic workflows (April 15, 2026):** plan, build and test feedback loops and external tools. Implement supervised isolated local tests before any live publish. https://about.roblox.com/en-nz/newsroom/2026/04/roblox-studio-going-agentic
- **Roblox Studio testing modes:** multi-client, network and device simulation should test online and low-end behavior; single-client success is insufficient. https://create.roblox.com/docs/studio/testing-modes
- **OBS WebSocket v5:** use authenticated loopback read-only `GetStats`, `GetStreamStatus` and `GetRecordStatus` plus output-change events; never infer nonbroadcast from merely seeing OBS installed. STAR already has this host component. https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

## Acceptance and honest boundaries

This branch changes *measurement/operability*, not network weights, training, recorded audio, user-facing avatar behavior or game-solving capability. Windows samples may be wrong if the driver, WDDM, or process APIs misreport metadata. Existing QoS/worker and output fencing remain opt-in. A green preflight is **not** a green stream rehearsal. No live account access, no unattended broadcast, and no automatic GitHub merge are implied.
