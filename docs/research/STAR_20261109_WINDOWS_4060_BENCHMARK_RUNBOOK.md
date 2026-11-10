# STAR Windows RTX 4060 Paired Benchmark Runbook

**Purpose:** run the paired inference comparator on the actual Windows gaming/streaming PC. The connected Linux development host is CPU-only and is not a substitute for this test.

## 1. Record the exact environment

Before each run, record:

- Windows build, NVIDIA driver, GPU name, VRAM capacity, and power mode.
- Model file hash, quantization, context length, sampler settings, and model alias.
- Inference runtime name, exact build/commit, launch flags, KV-cache type, and whether multiple aliases remain resident.
- Game title, map/scenario, resolution, graphics settings, and frame limiter.
- OBS version, encoder, output resolution/FPS, and scene.
- TTS engine/voice and avatar renderer version.
- Whether the machine is idle, gaming, gaming + OBS, or running the full stack.

Do not compare runs when these identities differ. If the server loads one model at a time, model-switching time is part of the observed user experience; do not label it steady-state decode latency.

## 2. Confirm local server and GPU

Use a loopback-only OpenAI-compatible endpoint, for example:

    http://127.0.0.1:8080/v1

Confirm the aliases are available before starting the benchmark. The benchmark warms each alias, but does not start the server or verify that every model remains resident.

Record GPU telemetry in a separate PowerShell window:

    nvidia-smi --query-gpu=timestamp,name,memory.total,memory.used,utilization.gpu,utilization.memory,power.draw,temperature.gpu --format=csv -l 1 > gpu-telemetry.csv

Stop telemetry after the run with Ctrl+C. Do not upload logs that contain unrelated application or account information.

## 3. Run matched model comparisons

From the repository root, with the local model server running:

    python -m star.inference_paired_benchmark ^
      --endpoint http://127.0.0.1:8080/v1 ^
      --model star-fast ^
      --compare-model star-reasoning ^
      --repeats-per-workload 2 ^
      --seed 20261109 ^
      --output paired-idle.json

Replace aliases with the exact local names. Repeat with a different seed for a second and third round. A run with two models and two repeats uses 32 measured requests; the tool enforces a 64-request ceiling.

The report contains aggregate timings and a randomized schedule, not prompts or generated answers. Negative candidate-minus-baseline deltas mean the candidate was faster in that matched observation.

## 4. Repeat under the actual workload

Run separate, clearly labeled reports for:

1. Idle desktop.
2. Game running without OBS.
3. Game + OBS recording.
4. Game + OBS + TTS + avatar animation.
5. Full stack with live visual perception and normal background tasks.

Do not run unrelated downloads, updates, or training jobs during a comparison. Let the machine cool and return to a stable idle state between rounds.

## 5. Collect stream and game health

The paired comparator does not collect these measurements yet. Record them separately:

- Game frame-time p50/p95/p99 and 1% low FPS.
- OBS rendering lag, encoding lag, and dropped frames.
- Audio underruns, TTS first-audio time, cancellation-to-quiet time.
- Avatar first-visible reaction time and mouth/audio synchronization drift.
- CPU utilization, available RAM, GPU utilization, VRAM peak, and thermal/power limits.

Use the same capture method and time window for baseline and candidate. If a metric is unavailable, mark it unknown rather than estimating it.

## 6. Quality gate before considering a faster model

Latency alone cannot select STAR's model. Run the same held-out tasks against both models and independently score:

- General knowledge correctness and calibrated abstention.
- Multi-step reasoning.
- Luau code generation and debugging.
- Game-strategy decisions.
- Streaming commentary relevance and groundedness.
- Tool-use correctness and refusal of unsafe actions.

A candidate is only eligible for review when its quality is within a preregistered non-inferiority margin, its first-content p50 improves, its p95 does not regress materially, and game/OBS/audio health remains stable. These are proposed gates, not results from this run. Do not automatically change the configured model.

## 7. Suggested initial review gates

Use these as conservative starting thresholds to review and adjust with the owner:

- At least 10% lower paired first-content p50 across three repeated rounds.
- First-content p95 no more than 5% worse.
- Held-out task quality no more than 1 percentage point below baseline, with adequate sample size.
- No new OBS dropped frames or audio underruns.
- Game 1% low FPS and frame-time p95 no more than 5% worse.
- At least 1 GiB VRAM headroom at peak on the 8 GB card, unless the owner explicitly accepts a different trade-off.
- No unhandled request failures, stale outputs, or route-switching surprises.

If the sample count is too small or results are inconsistent, keep the existing baseline and collect more evidence.

## 8. Privacy and safety

- Run private rehearsals; do not broadcast while calibrating.
- Keep OBS WebSocket authenticated and local.
- Do not save raw viewer audio, transcripts, screenshots, or account identifiers in benchmark artifacts.
- Do not use public multiplayer or production game accounts for autonomous practice without explicit owner approval.
- Preserve the baseline report and exact environment manifest so every result is reproducible.
