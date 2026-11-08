# STAR Intelligence — verified OBS network frames, real-time gaming, and natural VTuber research

**Date:** 2026-11-08. **Implementation:** opt-in, offline-tested Python adapters. **Not deployed.**
**Compatibility:** This patch stacks on PR #1074, which stacks on the earlier VTuber/vision draft chain. GitHub `main` is unchanged.

## New code in this change

`star/obs_stream_loss_window.py` adds `ObsStreamLossSampler`, a strictly typed, read-only adapter for the **responseData** portion of authenticated OBS WebSocket v5 `GetStreamStatus` messages. It verifies active/non-reconnecting stream state, current-session counters, monotonic observation clocks, counter increases, duration correspondence, real traffic, and interval sizes. An idle/paused/missing stream is **not** equivalent to 0% network loss. Each failure discards the baseline. It returns intervals containing attempted frames, delivered frames, dropped frames, and the drop percentage computed from each interval rather than from lifetime stream totals.

`StreamLoadHostBridge` gains opt-in `require_verified_stream_network=True` and an optional `stream_network` argument. With enforcement enabled, every host receipt needs the *matching* same-window stream evidence: counts, percentages, OBS time, and OBS window length must agree. Missing, mismatched, stale, or fabricated values disable the previously healthy resource governor. Existing disabled/default and explicitly offline rehearsal usage is not altered.

**Important trust boundary:** `host_verified=True` is **not authentication**. Only the Windows host, after authenticating its OBS WebSocket v5 connection and validating its local game/GPU/voice sources, may call the bridge. Never ingest arbitrary viewer chat, LLM-generated telemetry, remote OBS messages, stream keys, or model-provided source IDs as trusted sensor input. Do not attach a public stream until end-to-end Windows testing and explicit owner authorization.

OBS v5 schema lists `GetStreamStatus.outputActive`, `outputReconnecting`, `outputDuration`, `outputSkippedFrames`, `outputTotalFrames`, along with output congestion. For this adapter, the interval loss fraction is `Δskipped / (Δskipped + Δdelivered)`; the formula assumes the protocol's delivered-frame meaning for `outputTotalFrames`. Confirm formula against actual OBS Stats on the target version and capture output; do not claim exact network diagnostics from the counter alone.

## Highest-value research conclusions

### 1. Star must optimize end-to-end reaction deadlines, not token/s alone

The October 27, 2026 *Gym-Anything-RT* benchmark highlights the gap between reasoning with a paused game and reacting as gameplay continues. Implement a tiny, bounded reaction policy for immediate input; use heavier planners only for strategic periods. A correct answer delivered 800 ms after a 100 ms dodge window is not intelligent gameplay.

**Measured pipeline:** frame present → capture → preprocess → perception → decision → approved input → observed result. Record median, p95, p99 of each stage and missed deadlines, without private chat or raw stream frames. Compare performance on novel unseen levels, not training screenshots. Discard stale outputs before action.

Sources: https://arxiv.org/abs/2610.37567 and https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

### 2. Streaming feels natural when Star knows when *not* to speak

Microsoft's ICML 2026 Proact-VL work frames live gaming commentary around observation, the decision whether to speak, and response quality/quantity. Separate **social urgency** (owner direct question, safety, game callout) from optional idle chatter. Prioritize silence while uncertain, keep normal comments brief, support interruptions and expressive avatar gestures, and remember only host-confirmed spoken completions.

**Proposed rehearsal:** 30 minutes offline with prerecorded game events; human reviewers rate relevance, interruption rate, natural pauses, non-sequiturs, and repeated phrases. Track first audible response latency separately from LLM first token and audio playback completion.

Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

### 3. Resource-aware workloads should remain fail-closed

GPU memory contention on an 8 GB RTX 4060 can harm both OBS and game FPS. Use the verified `StreamLoadHostBridge` evidence to decline **optional** commentary and bonus vision inference under OBS render lag, output pressure, network loss, or VRAM pressure. Critical owner speech must have independent admission and audio shutdown controls. Performance optimization should never silently authorize streaming or gameplay input.

**Benchmark A/B:** game alone; game+OBS; game+OBS+TTS; game+OBS+vision and fast model; game+OBS+all with the governor. Measure OBS render/output/network interval drops, GPU headroom, game 1% low FPS, CPU p95, local LLM TTFT, voice onset, speech cutoff, and memory allocation. No performance claim without comparable matched runs.

Source: https://github.com/ggml-org/llama.cpp (cache and speculative decoding vary by model and build). OBS API: https://github.com/obsproject/obs-websocket/blob/master/docs/generated/protocol.md

### 4. Learn actual gameplay instead of claiming to learn

Star's next learning curriculum should use authorized games and contained simulations, with tasks drawn from interaction primitives: navigation, inventory, moving targets, timed dodges, teamwork, crafting, and puzzle solving. For each trial preserve *verified* event logs (state hash/time/action/reward, never identity), split training versus held-out games, compare baseline and candidate on equal budgets, and promote only demonstrated gains with rollback. Avoid exploits, multiplayer cheating, or circumventing anti-cheat; use a sandbox/approved game environment.

**Evaluation:** success %, completion time, action count, missed reaction deadlines, intervention rate, crash/recovery frequency, and transfer to new seeds. Provide negative results as well as positive examples.

### 5. Build games with verifiable loops and multi-Studio routing

Roblox Studio's April 15, 2026 agentic tools and August 19, 2026 Studio MCP update offer planning, playtesting and explicitly addressed multi-Studio sessions via `studio_id`. Couple Star's Luau code generation with syntax/static analysis, deterministic Studio Lab tests, screenshots and logs, and owner review before public publication. Isolate parallel workers to unique Studio sessions and prevent cross-project writes.

Sources: https://about.roblox.com/newsroom/2026/04/roblox-studio-going-agentic and https://devforum.roblox.com/t/studio-mcp-multi-agent-improvements-and-connected-ai-clients/4820583

### 6. Broader knowledge and personality without fabricated certainty

Keep distinct stores for factual knowledge (source, date, version, confidence), tested coding solutions (task/test evidence), gameplay skills (game/build/observation/reward), and personal conversation memories (what was *actually* heard/spoken). Add retrieval quality checks, provenance, expiration policies, and contradiction detection; don't promote model-generated guesses as facts. An engaging streamer can have continuity, humor, spontaneous hobbies, expressive voice and recognizable character behavior without pretending to be a human or hiding that she is AI.

## Windows implementation checklist / gates

1. In a private, nonbroadcast host, open an **authenticated loopback** OBS WebSocket v5 connection. Query `GetStats` and `GetStreamStatus` together with host monotonic timestamps. Do not log keys or raw video.
2. Reset both window samplers and the load governor at OBS output start, restart, reconnect, capture identity change or missing telemetry. Verify `outputDuration` against elapsed host time and confirm network drop percentage on actual OBS UI/logs before enabling live policy.
3. During recording-only trials, network stream loss may be **not applicable**, not zero measurement. Use the separately authorized private rehearsal policy; don't forge a streaming receipt.
4. Supply independently obtained game presentation p95, FPS target, VRAM usage, and local first-audio p95. Do not fill unknown data with zeros.
5. Test repeated OBS reconnects, pause/resume, high packet loss, stale stats, counter rollover, mismatched host clocks, game minimization, GPU contention, and voice stalls. Reject or disarm every invalid input.
6. Only then run matched offline A/B benchmarks; document exact Windows versions, OBS version, models, quantization, GPU, game FPS, and audio timing. Ship opt-in only after results pass thresholds.
7. **External streaming, messaging, spending, game purchases, and public project publication remain explicitly gated**; offline game practice and testing can be automated within authorized scope.

## Verification performed

Run `python -m pytest -q tests/test_obs_stream_loss_window.py tests/test_stream_verified_network_bridge.py tests/test_obs_stats_window.py tests/test_stream_load_host_bridge.py`, plus repository-compatible regression checks. No actual OBS stream, game control, model training or OBS integration is claimed by this patch.

**November 4, 2026 Studio MCP expansion:** New per-game Open Cloud permissions, `open_cloud_invoke`, and Blender/FBX/GLB asset-import workflows increase Star\x27s *potential* game-building scope; do not enable publish/monetization/servers without approval. Source: https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
