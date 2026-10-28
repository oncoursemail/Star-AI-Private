# STAR: Fast Exact-Pixel Vision, Measured Streaming Intelligence and Natural VTuber Acceptance

**October 28, 2026 — engineering research and implementation note — experimental / opt-in / offline-first.**

## Executive finding

STAR already has Windows game-window capture, a bounded paired-frame llama.cpp vision adapter, an optional focus crop, duplicate-JPEG rejection, stale-result shedding, game-action advisory gating and independently verified game-learning ledgers. Connecting them while preserving game FPS, low speech latency, and genuine observation quality is more valuable than adding another unmeasured model or generic agent framework.

A concrete avoidable cost remained: the paired-frame adapter **JPEG-encoded the entire captured RGB frame even when it was byte-for-byte the same image**. It then compared resulting JPEGs and correctly skipped a model request, but only *after* consuming CPU and memory on resize and JPEG work.

This change adds the host-only, opt-in **`raw_exact_fast_path`**. After validating frame geometry, timestamp and byte layout, the worker computes SHA-256 directly on the authorized RGB buffer. If the digest, source dimensions, and monotonic inter-frame window all match the previous frame, it advances the time of the existing baseline and returns a no-observation result **without PIL, JPEG encoding, or network inference**. SHA-256 here is an in-process *equality prefilter*, not a trusted game-state receipt, not a content identity for storage, and not a replacement for independent game-engine checks.

**Important boundaries:**
- Defaults remain unchanged. Hosts must enable **both** `skip_identical=True` and `raw_exact_fast_path=True`; neither switch can be set by a model, game UI or viewer.
- The new check only skips frames with exactly matching full-window RGB contents. It never treats merely *similar* screens as unchanged. A focus crop still uses the existing JPEG comparison when pixels outside the crop change; this is intentionally conservative.
- The worker does **not** assume a matching image means the game has not advanced internally. It offers **no game-success assertion, no speech event and no action authorization**. Screenshots and model observations are lower-trust evidence.
- Frame size, buffer contiguity, geometry and temporal ordering are validated before hashing; old references are still erased at disable, rejected input, or completed comparison.
- Existing loopback transport, physical-stop quarantine, owner revocation during slow inference, freshness deadline and cooldown remain in place.
- This change **cannot make a slow VLM model's token generation faster**. It only reduces CPU preparation for truly static frames, freeing headroom for gameplay, OBS and voice.

## Reproducible local synthetic benchmark

`PYTHONPATH=. python benchmarks/benchmark_vlm_raw_fast_path.py`

The benchmark feeds 48 synthetic 1280×720 RGB frames through each configuration. One scenario is exactly static, the other alternates two different synthetic images. The simulated model callback receives 24 requests in the changed scenario and no requests for the static scene. **No actual model, Roblox or OBS is running.** A local Linux measurement on October 28 reported:

| Synthetic workload | Old JPEG gate median / p95 | New SHA-256 gate median / p95 | Fake-model requests |
|---|---:|---:|---:|
| Exact static RGB | 9.165 / 13.109 ms | **1.993 / 2.610 ms** | 0 both |
| Alternating changed RGB | **9.225 / 12.408 ms** | 10.550 / 11.379 ms | 24 each |

The new path had **4.60× lower median host CPU time for exact-static frames**, but its median was about **14% higher when screens kept changing** in this single run. Neither result is a reliable estimate of typical real-game movement or a general speedup. This suggests enabling the feature selectively for static menus/paused windows and measuring it under user-approved moving-game conditions before a rollout. There is no demonstrated improvement in token throughput, game FPS, model accuracy or voice response speed.

Use p50/p95/p99 rather than only peak throughput. Measure the total frame-to-spoken-reaction path, including game capture, CPU preprocessing, model queue, VLM inference, evidence acceptance, speech generation, first audible sample, avatar visemes and actual OBS render performance.

## Next engineering experiments, ordered by measurable value

### 1. Real VLM latency attribution (P0)

A prior local paired-image request exceeded 30 seconds under competing workloads. Before adding another vision model, measure server queueing, HTTP completion, prefill, decode, prompt-cache hit rate and resources separately. llama.cpp exposes `/metrics` and slot/process diagnostics, but choose endpoints and requests by local host configuration rather than accepting viewer/model-provided URLs. Do not issue a heavy benchmark to a live gaming host without owner-approved capacity.

Evaluate several *compatible* small quantized VLMs and image resolutions on actual hardware, with fixed prerecorded **authorized synthetic or consented** scenes. Compare precision for HUD text and hazards separately from throughput. Downscale static regions; use ROI when a tiny inventory text changes; don't assume a 512-pixel full-frame model can read the same text as a native crop. The RTX 4060 has 8 GB VRAM in the planned setup, so preserve headroom for Roblox, OBS and avatar render rather than saturating GPU with a single giant VLM.

### 2. Verified game-learning loop (P0/P1)

For a curated Roblox Studio minigame: host captures a window, model produces candidate **descriptions**, a trusted game-state adapter produces independently attested state, and the game-action advisor suggests only host-allowlisted actions. Separately log the *precommitted prediction*, frame identity, chosen action, confirmed input release and signed outcome. Rerun candidate skills on held-out maps, different starting seeds, lag and alternate HUD layouts.

Use **OpenGameEval** to test game-building abilities via executable checks rather than only static code or attractive screenshots. Its October 2026 project describes 84 core tasks across 13 frontier models, and shows that relevant scene inspection is associated with success. Visual quality requires an additional human-reviewed track for UI, animation, VFX, sound, placement, collision and usable multiplayer behavior. Avoid assuming one failed playtest reflects the whole game's quality; record reproducible failure receipts.

### 3. Humanlike live performance without invented personal history (P1)

Natural streaming requires a *director* that chooses when **not** to speak:
1. Owner stop/interrupt and actual host permission always outrank social engagement.
2. Gameplay attention takes priority during high-precision movement or fast reactions.
3. Fresh verified game events outrank stale visual guesses.
4. Addressed chat messages and brief acknowledgements outrank repetitive unprompted small talk.
5. Lighthearted initiative and pauses should be varied but bounded, not random constant noise.

Separate audio-generation start, actual audible audio clock and animation timing. Visemes, gaze, head tilts, twin-tail spring motion and ribbon movement should be triggered by audio/verified events rather than immediately by the model's text output. Test laughter, giggles, thoughtful silence, interruptions and repairs **with human raters**. Maintain a clearly disclosed AI VTuber persona with a consistent fictional biography and real, verified digital experiences. Neither pleasant voice nor episodic continuity proves consciousness or human identity.

**Voice tradeoff:** Kyutai's official Pocket TTS repository documents October 2026 CPU-friendly models at roughly 18M, 7M and 2M parameters; compare CPU first-audio p95 and expressiveness on Star's own PC. Faster/smaller is not automatically more natural. LiveKit documents a local CPU `v1-mini` turn detector; treat it as a candidate for opt-in evaluation, not an installed component or a guarantee of natural dialog. Ensure chat content cannot speak as the owner or modify system policy.

### 4. General knowledge and self-improvement (P1/P2)

A large scraped document cache is not automatically higher intelligence. Star needs source/date/license metadata, revision/retraction handling, provenance spans, a retrieval-vs-no-retrieval held-out benchmark, and a contradiction checker that can say "uncertain." Put verified examples into a scoped knowledge index, not unrestricted permanent memory. Keep public game chat and web content lower-trust and minimize personal data retention.

Star Core Forge should remain the authoritative **local** experimentation ledger: generate multiple candidate patches, run deterministic tests, independently verify held-out cases, profile CPU/VRAM and game FPS, retain rollback snapshots, and promote only measured improvements. GitHub is an optional reviewed publication mirror, not required for local self-improvement. The repository named `Star-AI-Private` is currently visible as **public**; do not upload private streams, player identities, voice recordings, credentials or unredacted logs.

## Acceptance gate for the new optimization

- Offline: exact-static no-model behavior, one-pixel mutation, ROI changes outside selected crop, malformed/released buffers, old/gapped frames, revoked sessions and uncertain network stops.
- Performance: compare the synthetic old path to new path with a separately reproducible CPU-only benchmark; claim improvement only for the exact-still workload measured.
- Windows integration (not yet done): evaluate authorization and scoped capture on a temporary test window, then user-approved Roblox/OBS rehearsal. Report overall p95 frame-to-audio, gaming FPS/1%-low, OBS drops, VRAM, voice naturalness and false visual-event narrations. Keep all new switches OFF if performance or correctness regresses.

## References checked October 28, 2026

- llama.cpp server official documentation — https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- Roblox OpenGameEval repo — https://github.com/Roblox/open-game-eval — and preprint https://arxiv.org/abs/2610.02563
- Kyutai Pocket TTS official README — https://github.com/kyutai-labs/pocket-tts/blob/main/README.md
- LiveKit local/default turn-detection guidance — https://docs.livekit.io/agents/logic/turns/turn-detector/
- LiveKit interruption and turn behavior — https://docs.livekit.io/agents/logic/turns/
- Live2D physics documentation — https://docs.live2d.com/en/cubism-editor-manual/physics-operation/

## Explicit nonclaims

This PR does not install new models, control Roblox, train weights, start OBS, capture private screenshots, deploy speech synthesis, give Star human consciousness, improve general-knowledge accuracy, or certify game mastery. It adds one host CPU fast path with offline tests, a reproducible synthetic benchmark, and research-backed integration criteria.
