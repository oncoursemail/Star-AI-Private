# STAR AI — host-bound inference models and next intelligence/VTuber experiments
**Research and implementation note — November 4, 2026**

## Why the next upgrade is not another generic LLM prompt

A live VTuber sharing one 8 GiB gaming GPU with a vision model, game renderer,
OBS, avatar and possibly voice synthesis has a finite real-time budget. A false
claim that a model will run in 100 ms is worse than a slow model: Star can schedule
a response after the chance to react has passed. Earlier QoS upgrades separate
game-only from game+stream timings and model *labels*. But labels supplied on an
`InferenceJob` were not tied to a host-selected runtime or model deployment. An
incorrect caller could attach the fast route's label to a slower model and reuse
the wrong calibration. It could also underreport RAM or VRAM in the request.

## Implemented in this change (opt-in, local-only)

- `star/stream_host_model_catalog.py` adds a frozen, validated, immutable
  manifest of host-selected deployed workers. Each entry has a bounded alias,
  actual kind, fixed CPU/GPU device, runtime engine, lowercase SHA-256 weight
  manifest digest, deployed runtime-build digest, optional voice-config digest,
  and host-owned RAM/VRAM reservations.
- `HostModelRoute.route_profile` hashes all the material configuration into
  a stable opaque profile, so deploying different weights, runtime build,
  voice or memory plan cannot silently reuse the previous timings. A hash
  alone is **not attestation**.
- `HostInferenceCatalog.bind()` overwrites untrusted memory estimates and
  device requests using the manifest, and rejects self-declared profile IDs,
  incorrect kind/device, duplicate/unknown aliases, malformed hashes and
  impossible reservations.
- `StreamBrainGovernor.admit_registered(...)` passes a bound request to the
  **existing** protected QoS, deadline, pressure and host telemetry checks.
  Optional `enforce_host_route_binding=True` rejects the old unbound
  `admit()` path. Both optional settings remain OFF by default.
- Neither the catalog nor governor starts a model, downloads weights, launches
  OBS, listens to viewers, releases controls, or changes any permission. The
  trusted *execution host* must verify files/configuration at deployment,
  ensure the selected worker actually matches the route, and attest worker
  termination before releasing its ticket. Never let an LLM choose an alias
  as though it were an authorization credential.

### Integration sketch (trusted host only)

```python
# From a local owner-controlled manifest, *after verifying actual weight shards
# and executable build*. Never compute these from a generated answer/chat.
catalog = HostInferenceCatalog((
    HostModelRoute(
        alias="tts-cpu-18m", kind="speech", device="cpu",
        engine="pocket-tts", model_sha256="<verified 64-hex sha256>",
        runtime_sha256="<verified 64-hex sha256>",
        voice_sha256="<verified 64-hex sha256>",
        ram_mib=400, vram_mib=0,
    ),
))
# governor constructed with route_catalog=catalog,
# enforce_host_route_binding=True; QoS with require_route_profiles=True.
admission = governor.admit_registered(job, route_alias="tts-cpu-18m")
# Execute exactly that manifest's worker only after admission;
# acknowledge_worker_stopped only after confirmed process termination.
```

Do not use the illustration above as a ready production deployment manifest:
measure peak RAM and latency on the actual Windows host. Rebuild the catalog
on a model, voice, quantization, runtime, binary or resource configuration
change. Do not persist arbitrary viewer identifiers or weights in Git.

## Research findings and practical engineering implications

### 1. Smarter *and* faster: independently measured routing

llama.cpp's SPEED-Bench documents server-side measurement for prompt/decode
throughput, end-to-end latency and speculative-draft acceptance. Benchmark
baseline vs candidate on identical tasks and concurrency. A higher decode rate
is *not* proof of better games or dialogue: require equal/higher verified task
success, stable p95 first-audio and capture-to-action times, and no increased
1%-low FPS loss. Speculative decoding may use additional VRAM and need not
be faster on an 8 GiB Windows gaming host.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Suggested experiment: replay the same 30 short coding, Roblox tool-planning,
gaming-observation and conversation examples with the same seed and model
weights. Compare no-draft, small-draft and n-gram speculative modes with
three real workload regimes (idle, game alone, game+OBS+avatar+CPU TTS).
Record per-route p50/p95/p99 wall latency, accepted tokens/sec, peak private
GPU allocation and test correctness. Never borrow the idle calibration for
stream-time admission.

### 2. Voice: speaker synchronization and turn-taking beat nonstop chatter

Kyutai's Pocket TTS v4.0.0 release on **October 20, 2026** introduced
`english_18m_2026-10`, `english_7m_2026-10`, and experimental
`english_2m_2026-10` variants (plus reward-finetuned options). Their small
CPU footprint is worth comparing with Star's existing voice pipeline, but
the advertised speeds are not measured on Star's Windows PC. Benchmark first
audible PCM, intelligibility, emotion prosody, interruptions, glitches and
OS process contention. Preserve lip-sync and cancellation acknowledgments:
a model callback reporting speech completion is not proof that a speaker
actually finished playing sound.

Source: https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0

Microsoft Research's **Proact-VL**, presented at ICML 2026, addresses
spontaneous *when-to-speak* decisions and quality/quantity control for gaming
companions. Star should avoid commentary loops on unchanged frames, speak
after important verified events, acknowledge a viewer appropriately, keep
quiet during demanding gameplay, and synchronize facial expression to the
actual speaker playout clock rather than speculative text.

Source: https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

Recommended evaluation: blinded A/B clips; measure interruption false
positives, timely meaningful commentary, dead-air length, repetition rate,
lip/audio drift, speech intelligibility, and whether viewers understand they
are interacting with an AI character. A stable fictional persona, interests,
humor, first-person history based on actual episodes and expressive reactions
can feel natural without pretending to be a human being or inventing private
experiences.

### 3. Gameplay learning: play, verify, practice, transfer

Separate the loop into 1) deadline-bound reflexes, 2) strategic planning
between actions, 3) slower post-game lesson extraction. Do not use a long
reasoning prompt for every reaction. Learn only from independently observed
game state, not a model's self-claimed win. Train timing, movement, camera
control, inventory and map objectives progressively. Use held-out levels,
random seeds and load profiles to validate transfer; explicitly compare
baseline vs updated policy. Do not perform online multiplayer automation
where a game's rules prohibit it.

Acceptance: success on held-out levels, errors per attempt, time to goal,
death/recovery rate, actual capture-to-input latency and operator-required
rescues. Distinguish reliable wins from synthetic simulations.

### 4. Game-building intelligence: visual feedback is mandatory

**GameDevBench**, presented at ICML 2026, studies 132 game-development
tasks. Its authors report a best overall success of 54.5%, and far poorer
performance on some graphics tasks; their experiments report meaningful
gains from image/video feedback. That supports Star's existing Best-of-N
code candidate evaluation plus *visual* screenshot/frame-based verification
for animations, lighting, topology, material and HUD correctness.

Source: https://sethkarten.ai/papers/gamedevbench.html

Roblox's built-in Studio MCP server was announced on **March 5, 2026** with
playtesting and simulated input; StudioTestService additionally supports
scripted multi-client scenarios. Progress to a controlled, owner-approved
private place: inspect DataModel -> bounded implementation -> Luau/static
checks -> unit tests -> solo playtest -> multiplayer playtest -> screenshot/
video review -> rollback or promote. Keep creativity distinct from
autonomous publication.

Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://create.roblox.com/docs/reference/engine/classes/StudioTestService/AddPlayers

### 5. Long-term general intelligence and self-directed projects

Prioritize durable evidence-tagged knowledge (Roblox APIs, math, physics,
graphics, audio, design, general-purpose programming and current references);
maintain an uncertainty and source-provenance field for every memory. Use
retrieval and citation verification instead of silently assuming learned
facts. Let Star propose her own games, experiments and hobbies, but require
independent success criteria, owner-approved external/public actions,
resource budgets and rollback. Track quality at task level, not by response
length, GPU utilization or token/s alone. GitHub is an optional publishing
mirror; her internal forge should retain offline version history and
reproducible experiments.

## What remains unverified and the next high-value integration

This update has **not** measured faster token generation, won a real game,
spoken through Windows speakers, operated an OBS/VTuber rehearsal, or verified
actual downloaded weight files. Model identities become useful only when
the trusted Windows execution host supplies and enforces real verified
build/weight manifests. Do that next, then conduct a private *nonbroadcast*
rehearsal of game + avatar + OBS local recording + voice. Collect end-to-end
p95/p99, audible first PCM, frame pacing, dropped OBS frames, worker stop
and independently verified gameplay outcomes. Promote any new speed/quality
configuration only when those real metrics improve without regressions.
