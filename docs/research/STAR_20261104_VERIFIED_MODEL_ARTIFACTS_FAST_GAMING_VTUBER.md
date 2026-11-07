# STAR AI — verify actual inference artifacts before the private VTuber rehearsal
**Research and working-code note · November 4, 2026**

## What this iteration changes, and what it does not

Earlier STAR pull requests added separate realtime performance profiles for
*game only*, *OBS stream only*, and *gaming + streaming*, then bound profiles to
owner-selected model configurations. But that catalog still relied on **declared
SHA-256 digests**, without checking what bytes were actually installed. Someone
could update a model, TTS voice, or inference runtime and inadvertently reuse an
obsolete calibration profile. This iteration adds the missing read-only **disk
preflight** before any model worker is launched.

**Implemented in this PR:** `star/stream_host_artifact_preflight.py`, a local,
dependency-free, streaming SHA-256 verifier for model weights, runtime
binary/build and optional voice configuration; deterministic multi-shard
manifests; a bounded read-only command line; 36+ focused tests. The verification
function returns an actual `HostInferenceCatalog` **only if every route matches**
its declared artifacts. It does not call OBS, the microphone, keyboard, network,
GPU, streaming platform or any external service.

**Not implemented:** reading GPU-resident model tensors or inspecting running
workers; genuine Windows OBS + avatar + TTS rehearsal; speedup measurements;
training a neural model; a stronger guarantee that an already-verified disk file
is what a particular worker loaded. A verified hash is **not remote attestation**,
and files can still change after preflight. The execution host must launch the
*exact* checked worker and keep model/configuration changes from occurring while
the session runs.

## Integration protocol for the owner-controlled host (OFF unless explicitly adopted)

1. Keep expected SHA-256 values and artifact relative paths in the owner's
   deployment configuration. Never derive these from a model response, Twitch
   message, prompt, webpage, uploaded repository, or external plugin.
2. Pause inference worker deployment, stop the old worker, and ensure no active
   model reservation can be carried into the next session.
3. Run the preflight **once per deployment, outside the real-time gameplay
   loop**. Store its redacted outcome privately. Failure means do not launch.
4. Launch the *same checked executable and weights* under supervised,
   least-privilege permissions. The host must verify the process matches its
   configured deployment and monitor process exits.
5. Build `StreamBrainGovernor(route_catalog=preflight.catalog,
   enforce_host_route_binding=True, ...)` *only after the trusted worker is
   ready*, and supply the catalog-controlled alias through
   `admit_registered(...)`. Keep the protections OFF in existing installations
   until actual Windows host integration is tested.
6. Invalidate worker readiness and latency calibration on any model, shard,
   runtime binary, voice config, quantization, backend, memory reservation, or
   runtime setting change. Any file change triggers a fresh full preflight.
7. After cancellation, independently confirm worker termination, clear
   reservations, flush/mute speech and release all game inputs. A callback or
   LLM acknowledgment is not physical evidence of stopping.

The byte reader uses 1 MiB blocks and holds **constant memory** relative to
model size. The total verification budget defaults to 64 GiB. It rejects empty
or nonregular files, path traversal, Windows drive prefixes, symlinks (including
relative parent components), suspicious length, duplicate roles, missing
routes, mismatched contents and modifications detectable during hashing.
Existing host permissions and ownership protections remain essential: a
privileged attacker can replace files after verification, and a file watcher or
mtime-only shortcut is not a cryptographic integrity check.

### Local CLI (sample with *dummy* hashes, not an operational manifest)

On the **host**, prepare a trusted JSON file with this schema, populating the
hashes from independently verified actual bytes (not the placeholder strings):

```json
{
  "routes": [{
    "alias": "star-tts-cpu",
    "kind": "speech",
    "device": "cpu",
    "engine": "pocket-tts",
    "model_sha256": "<64 lowercase hexadecimal characters>",
    "runtime_sha256": "<64 lowercase hexadecimal characters>",
    "voice_sha256": "<64 lowercase hexadecimal characters>",
    "ram_mib": 500,
    "vram_mib": 0,
    "artifacts": {
      "model_files": ["models/voice-weights.bin"],
      "runtime_file": "bin/tts-runtime.exe",
      "voice_file": "voices/star.json"
    }
  }]
}
```

```powershell
# A PRIVATE local command; it does not download, start, stream or speak.
python -m star.stream_host_artifact_preflight --root "C:\StarModels" --manifest "C:\PrivateConfig\model-routes.json"
```

The command returns JSON with `status=passed`, route count, files/bytes hashed
and elapsed time, or a redacted `failed` result and exit code 2. It never
emits model file paths, voices, fingerprints or user text. Use the programmatic
`verify_host_artifacts(root, routes, manifests)` API to obtain a verified
catalog object; **the CLI does not automatically enable any worker**.

**Digest recipe:** A single weight file uses SHA-256(file bytes). A multi-shard
model uses the hash of `b"STAR_MODEL_BUNDLE_V1\n" + JSON`, with compact JSON
list entries `[relative_file_name, byte_size, sha256_of_file]` for every shard,
in owner-manifest order; shard names and ordering affect the digest. Runtime and
voice digests are direct SHA-256 of one file each. The owner must choose the
complete set of relevant shards/config files, and avoid omitting mutable
tokenizers/adapters/configuration from the deployment description.

## Performance: the expensive part belongs at startup, not each token

Reading gigabytes of model weights per inference would destroy gaming latency.
Perform the integrity check **once at a deployment boundary**, then use the
verified worker under existing admission controls. Keep the realtime loop
restricted to resident models, ring-buffered frames/audio, and cheap state
comparisons. Optimize real-world latency, not token/s in isolation:

| Measurement | Current evidence | Recommended acceptance gate |
| --- | --- | --- |
| Full preflight wall time | Code and offline tests only | Measure on 8GB Windows host and log startup-only impact |
| 1st audible TTS PCM sample | Not measured this iteration | p95 in gaming+OBS+avatar workload, real speaker acknowledgment |
| Capture → verified input event | Existing simulation only | p95/p99 under a running game; no hidden missed acknowledgments |
| 1%-low FPS / OBS skipped frames | Some infrastructure exists | No regression vs identical hardware/load baseline |
| Model correctness | Not improved by hashing | Paired held-out benchmark: coding, factual QA, game actions |
| Gaming success | Not yet demonstrated | Game-state verified wins/progress, trials separate from training |
| Stream naturalness | Not yet demonstrated | Blind human ratings plus interruption/silence/sync metrics |

Use paired trials with identical game/build, scenario order, temperature/seed
(where supported), OBS scene and model weights. Compare **idle**, **game
only**, and **game+OBS+avatar+audio** separately; do not use idle latency
profiles during streams. Retain resource pressure and honest abstention when
real latency exceeds the game's action deadlines.

### Faster local inference: options worth controlled experiments

llama.cpp SPEED-Bench measures prompt and decode throughput, end-to-end latency
and speculative-draft acceptance for an already-running server. On shared
8 GiB GPU hardware, speculative decoding can also increase VRAM pressure.
Benchmark no-draft, small draft and n-gram options against identical tasks,
then reject any configuration that compromises game FPS, voice, or correctness.
Do not imply that a model became **smarter** because it produces tokens faster.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Kyutai Pocket TTS documented additional compact English CPU models in
**October 2026** (18.2M, 6.9M and experimental 1.9M parameters). These are
candidates for a GPU-constrained game+avatar rig, not evidence of Star's voice
quality until direct listening and first-PCM testing. Compare pronunciation,
emotional consistency, fallback under load, long-form instability, and audible
turn latency. Measure CPU contention with the active game and capture systems.

Source: https://github.com/kyutai-labs/pocket-tts

## Humanlike behavior without pretending the assistant is human

An expressive AI streamer needs **observed experiences, timing and reciprocity**,
not an always-on paragraph generator. The plan should use separate modules:

- **Perception:** capture visual/audio/game-state events with timestamps and
  source labels. Do not report guessed wins, damage or game rules as facts.
- **Reactive control:** deadline-bounded aim/movement/navigation in authorized
  supported games. Do not wait on a multi-second LLM call for each key press.
- **Tactical planner:** choose goals and skill macros from current state;
  reconsider after a failed action, not every rendered frame.
- **Practice learner:** log complete state-action-outcome trajectories and
  independently verified progress; split training from held-out levels and
  eliminate rewards inferred from Star's own narration.
- **Social director:** decide if, when and how much to speak. Normal silence,
  short acknowledgments and listening gestures matter more than constant talk.
- **Speech/avatar:** synchronize visible lip motion and expressive eyes to
  **actually played PCM**, not imagined or merely queued speech. Invalidate
  old animation when speech is interrupted.
- **Persona and memory:** store compact, appropriately consented episodic
  memories with provenance and revalidation. Interests can evolve through
  recorded choices; do not claim biological emotions or human status.
- **Safety:** owner-approved tool/game actions, moderation, protected private
  information, explicit AI disclosure, limits on chat-to-tool instruction
  injection, consent for viewer memory, and non-broadcast private rehearsals.

**Research basis:** Microsoft's **Proact-VL (ICML 2026, May)** studies
proactive video gaming companions that decide when to speak and how much; use
its commentator/guide split as a benchmark inspiration.
https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

Microsoft's **RESPOND (March 2026)** shows a controllable approach to
backchannels and proactive turn claims. Expose a bounded "acknowledgment
intensity" and "turn claim" knob instead of prompting Star to be "more human."
Neither paper proves that any such functionality is integrated into Star.
https://www.microsoft.com/en-us/research/publication/respond-responsive-engagement-strategy-for-predictive-orchestration-and-dialogue/

Research into intention-aware nonverbal listening reactions, presented in
**August 2026**, supports a low-latency animation/gesture path separate from
spoken replies; start with local, short gestures rather than a new huge model.
https://doi.org/10.1145/3820253.3831400

### Objective stream naturalness test

Run 20 private scripted sessions with ten-second windows where (a) the game is
quiet, (b) a verified surprise occurs, (c) a viewer asks a legitimate question,
(d) chat contains an instruction-injection attempt, (e) owner interrupts, and
(f) nobody says anything. Record whether a comment was **needed**, factually
supported, nonrepetitive and audible; track false interruptions, response
duration, lip-to-audio offset, speech overlapped with other humans and privacy
violations. Score two blinded evaluators; do not reward sheer word volume.
Use only synthetic or consented viewer data in the offline harness.

## General knowledge and game building

For Roblox, implement **inspect → propose multiple changes → test Luau →
run controlled Studio playtest → compare image/video/game-state →
repair or roll back**. Roblox's built-in Studio MCP is recommended over
unsupported unrestricted direct editors and supports test automation.
Its StudioTestService handles plugin-driven multiplayer test scenarios.
Official source (March 5, 2026):
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

Verified gameplay outcomes matter more than a player's self-reported win.
GameWorld's benchmark uses serialized game state; its real-time track leaves
the world running during agent inference. Keep paused and realtime results
separate, and use the held-out realtime track for Star's streaming claims.
https://gameworld-project.github.io/

The **GameDevBench ICML 2026 camera-ready report** now covers **333** Godot
tasks, not the earlier preliminary 132-task figure. Its official report
documents an improvement from **41.1% to 52.0%** for a tested agent when
visual feedback is added. These are published *benchmark* numbers, not
STAR's own results; the portable lesson is to test generated scenes visually.
https://proceedings.mlr.press/v306/chi26a.html

For broader intelligence, use retrieval of authoritative docs, provenance and
expiration dates on facts, hard "unknown" states, citations, and verifier-
approved coding/game trials; evaluate on unseen questions and projects.
Prioritize correct solved tasks per joule/sec over model size or length of
reasoning. Use the existing local-first/self-owned Forge for experiment
provenance and rollback; GitHub remains a review/export channel.

## Next acceptance milestone

Wire this verification to a real, trusted Windows model-worker launcher;
check exact downloaded binary, weights, adapters and voice assets; confirm
the running worker was launched from that verified deployment; only then
enable model-bound strict admission. Run a **private** game+OBS+avatar+voice
rehearsal and record wall-time, GPU memory, FPS, real PCM timestamps and
verifiable gameplay. Keep all changes opt-in and no publishing to a live
platform without separately authorized broadcast controls.

**Evidence this iteration:** 36+ new focused offline tests plus any reported
regression checks. No GPU game performance, new neural intelligence, actual
spoken naturalness, model-worker attestation, or real on-air game wins are
established by this patch.
