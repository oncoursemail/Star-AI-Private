# Star AI — verifiable private VTuber rehearsal artifacts and higher-quality real-time intelligence

**Researched and implemented:** November 4, 2026.
**Branch:** `feat/star-obs-recording-artifact-proof-20261104-auto71`; depends on #975, which depends on the earlier unmerged streaming infrastructure.
**Actual code in this change:** `star/stream_obs_recording_artifact_probe.py`, deterministic tests, optional real FFmpeg smoke. No live broadcast or gameplay.

## 1. The gap after authenticated OBS observation

The preceding OBS implementation checks that a *private recording* is active, bytes advance, and the broadcast is reported inactive at sampled times. OBS telemetry does **not** establish that a saved clip exists, that the container is playable, or that the audio track and pixels represent Star.

The new **explicit opt-in, read-only, offline artifact probe** requires the trusted host to affirm that the chosen recording has stopped, broadcasting is inactive, and an absolute local recording file was selected inside an approved directory. It checks:

- The file is a bounded, regular, non-symlink local MKV/MP4/MOV under a specified root. Never use network URLs or untrusted media paths. The API never returns any source path.
- FFprobe reads the *actual* container with a forced demuxer, counts video frames, and discovers an audio stream. It requires finite 4–120-second duration, plausible video dimensions/frame counts, valid audio sample rate, and an explicitly selected audio track.
- FFmpeg then **decodes the whole selected video and audio track** with strict decoding flags and no output file, using bounded run time. Headers alone cannot pass.
- A second filesystem stat rejects a recording that changed or was replaced during inspection. Metadata or bytes that continue advancing in OBS while this scan runs are not accepted as a stable stopped file.
- The result is **candidate_for_owner_review**, *not* an authenticated claim that this was Star's OBS output, that Star alone is speaking, or that gameplay/avatar appeared. There is no recording, streaming, input, speaker or scene authority.

Trusted host-only API (conceptual; do not copy recording paths into model prompts or public logs):

```python
from star.stream_obs_recording_artifact_probe import inspect_private_obs_artifact
report = inspect_private_obs_artifact(
    chosen_local_file,
    allowed_root=owner_approved_recording_folder,
    owner_approved=True,
    host_confirms_recording_stopped=True,
    host_confirms_broadcast_inactive=True,
)
assert report.local_media_decoded
assert not report.recording_origin_attested  # must be checked elsewhere
```

**Host obligations:** independently match the file to OBS's actual output file and session, keep recording off during decoding, isolate the Star-only audio bus, keep all streaming disabled, and only then run the existing `stream_av_recording_host.py` + `stream_av_sync_audit.py` with proper avatar-mouth stills. File time, recording basename, raw tracks and chat must not be published; a decodable media file by itself is a weak evidence claim. The selected file may be from an entirely unrelated application.

## 2. Private Windows end-to-end rehearsal, precisely scoped

1. Obtain owner approval for the **private** session, test game, exact game-control scope, OBS recording and selection of a local file; never infer consent to public streaming.
2. Check observed GPU resource headroom *under game load*, not an idle GPU snapshot. Reserve enough VRAM for the game and avatar first. Use CPU-only speech or a small-model route only after actual playback quality and latency benchmarking.
3. Start Star's game, voice and avatar paths in a test environment. Measure scene observation → action, user speech end → first audible PCM, response cancellation, avatar-to-audio synchrony, GPU memory and OBS skipped-render fractions.
4. Independently start an OBS **local recording**, verify authenticated no-broadcast samples and recording counter progress, stop it, and give the final file to this new **read-only** artifact verifier.
5. Visually inspect the resulting footage for game content and avatar. Verify an isolated Star-only audio track; run `stream_av_recording_host` with mouth calibration and prove clip-level lip sync from decoded samples. Repeat with interruption, loss of speech worker, game alt-tab and load spikes.
6. Record baselines, then change **one** setting (KV cache, speech model, speculative decoding, runtime backend), replay the same test, and compare p50/p95/p99 latency plus success and dropped frames. Do not claim an improvement from a single warm run.

At this stage **we have not performed steps 3–6** as a live combined Windows session, even though the source contains pieces of each pipeline.

## 3. Intelligence and speed: ideas with measurable acceptance conditions

**Memory + knowledge.** Organize Star's retrieval into verified facts, episodic game experiences, unverified hypotheses, and current external sources. Timestamp and cite retrieved claims; expire volatile content; refuse to rewrite a stable belief based only on an invented memory. Evaluate general-knowledge retrieval using unseen questions, contradiction tests, correct citations and time-to-useful-answer.

**Game mastery.** In an owner-controlled private game or Roblox Studio sandbox, sample compact game state and encode action outcomes. Use a two-rate loop: a short-horizon movement controller for deadlines and a separate slower planner for strategy. Train in progressively harder skill drills (movement, aiming, navigation, puzzles, team play), replay failed attempts, randomize seeds and reserve *unseen* maps for evaluation. Score actual game state and win rate, not Star's self-report. Keep game control explicitly scoped.

**Build-test-repair.** Roblox's built-in Studio MCP server and playtest agent enable inspection and executable scene tasks; OpenGameEval provides a strong benchmark for measuring meaningful environment inspection and independently verified fixes. Learn from test receipts without allowing Star's model to rewrite protected tests or answer keys.

**Real-time personality.** Proact-VL's proactive gaming commentary research argues for learning when to speak, what to say and how much to say instead of narrating continuously. Implement game-state- and speaker-grounded reactions, conversational overlap where safe, natural acknowledgment, varied prosody, expressive face/gesture and intentional silence. Never fake viewer interactions, human identity or gameplay outcomes. Persistent interests and memory should be based on actual, consented sessions.

**CPU/GPU co-scheduling.** Test llama.cpp SPEED-Bench for prefill throughput, decode throughput, speculative decoding acceptance and end-to-end real-turn latency at *multiple VRAM pressures*. On the observed 8 GB Windows GPU, reserve FPS/voice budgets and suspend optional heavy multi-agent inference when free memory or frame timing crosses an admission threshold. Cache stable prefixes, but separate model-worker epochs and invalidate stale replies. Report useful completed actions per second and 1% frame-time lows as well as token rate.

**Suggested quantitative gates (goals, not achieved results):** p95 response-to-first-audible PCM < 500 ms for lightweight gaming reactions, zero public streaming during private rehearsal, no stale spoken reply after a worker restart, source game FPS target >= 60 under the defined game scene if the hardware allows it, and a measurable win-rate lift on a held-out game-skill benchmark. If a target is unattainable on the active device, degrade model quality or defer noncritical background tasks before starving the game.

## 4. Freshly checked primary sources

1. FFmpeg, **FFprobe Documentation** (verified Nov 4, 2026): `-show_entries`, `-show_streams`, `-count_frames` and JSON output, https://ffmpeg.org/ffprobe.html.
2. Roblox, **Studio Built-in MCP Server and Playtest Automation** (Mar 5, 2026): official Studio integration and simulated gameplay input, https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643.
3. Roblox, **Studio Assistant & MCP Playtest Agent** (Apr 9, 2026): beta test character and scenario-based playtesting, https://devforum.roblox.com/t/studio-beta-studio-assistant-mcp-playtest-agent/4566767.
4. Roblox, **OpenGameEval** (Oct 1, 2026): 84 stateful engine tasks, executable scene and play-session checks, https://arxiv.org/abs/2610.02563.
5. Microsoft Research, **Proact-VL** (ICML 2026): proactive game commentary and guidance with latency/quality balance, https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/.
6. ggml-org, **llama.cpp SPEED-Bench** (verified Nov 4, 2026): throughput, latency and draft acceptance for running server configurations, https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md.

**Limitations:** A header probe alone is not enough, but even complete media decoding does **not** establish original OBS provenance, content authenticity, Star's voice identity, scene quality, natural conversation, skill growth or any inference speedup. This feature protects the evidence boundary for future live measurement; no public broadcast, recording state change or autonomous game session is performed.
