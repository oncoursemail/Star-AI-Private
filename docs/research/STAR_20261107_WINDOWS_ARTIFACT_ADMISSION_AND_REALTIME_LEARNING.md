# STAR: verified Windows voice artifact admission + realtime intelligence research (2026-11-07)

## What this change actually implements

The self-contained NAudio 3.3 Windows loopback diagnostic was previously built in GitHub Actions, but the owner-side instructions trusted an artifact's own `manifest.json` for the executable digest. A tampered ZIP could contain a matching malicious executable and manifest. That is not an independent integrity check. The new **offline-only**, standard-library gate in `star/process_loopback_artifact_audit.py` requires four values pinned **separately from the downloaded artifact**: manifest SHA-256, EXE SHA-256, Git checkout commit, and Git source tree.

The CI packager now uses manifest schema v2; it includes the SHA-256 of README instructions, exact source commit/tree, an executable digest, and explicit *negative* claims for live capture, quiet verification, and broadcast permissions. The gate rejects stale schema v1, additional files (including side-loaded libraries), symlinks/junctions, hard links, missing/truncated files, forged manifest fields, mismatched source identity, and changes to files while reading. Read-only digest checking never runs the EXE, visits a live voice process, captures data, or launches streaming.

**Trust boundary:** the operator must obtain/check the expected hashes and commit/tree from a trusted, independent CI interface *before downloading*. The artifact cannot vouch for itself, and a matching SHA is not a digital signature, publisher attestation, sandbox safety proof, or indication a Windows device works. A malicious artifact from a compromised build can still match a compromised trusted precommit. Only inspect and self-test code that the owner explicitly trusts.

## Why this is useful for streaming

Earlier work (PRs #1044–#1054) introduced abortable native speech, an audio-quietness evidence design, process-isolated WASAPI capture and a bounded audit of stopped native JSONL telemetry. The next real test must be on a Windows device with an independently pinned dedicated Star voice process; contaminated artifact contents must be rejected **before** the operator can safely consider a local trial. A hardware rehearsal remains **blocked** until these independent prerequisites exist. This patch makes the transport/byte-integrity step reproducible instead of relying on self-declared evidence.

The new check is deliberately unable to make Star sound natural or improve model speed by itself. It also cannot prove that no sound was audible. Windows process loopback can stop producing callbacks during silence, so absent PCM packets stay *unknown* and must not be promoted into an audio stop assertion. NAudio's modern per-process recorder documentation explains that process capture uses `ActivateAudioInterfaceAsync` and `BuildAsync`.

References:
- NAudio WasapiRecorder, process loopback, capture format: https://naudio.github.io/NAudio/docs/WasapiRecorder.html
- Microsoft process loopback parameters: https://learn.microsoft.com/en-us/windows/win32/api/audioclientactivationparams/ns-audioclientactivationparams-audioclient_process_loopback_params
- GitHub Actions artifacts security and attestations: https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds

## Native private-trial sequence (not run by this PR)

1. In trusted GitHub Actions UI, confirm a green Windows build on the intended commit. Record the job's printed *manifest SHA-256*, executable SHA-256, checkout commit, and checkout tree through a separate trusted route. Do not copy them from the extracted artifact.
2. Unpack into a new dedicated, nonlinked directory containing **exactly** `Star.ProcessLoopback.exe`, `README.md`, and `manifest.json`. Before executing anything, run the standard-library Python preflight, with `--owner-approved`, `--approved-root`, `--artifact-dir`, and four independent expected values. Any mismatch blocks further use; it will print only a generic failure.
3. Only in an owner-supervised, private session, inspect the EXE provenance, run `--self-test` with no real capture, then separately verify the dedicated voice worker's process-handle identity, unchanged route, trusted binary and opt-in state. Never use a browser, game, microphone, explorer or normal desktop process as the target.
4. Separately capture a short genuine speech interval, abort TTS, check independent native packet state and audio route, and correlate OBS local recording/frame counters, game FPS and VRAM. Do **not** interpret missing callbacks as silence. Do not broadcast.
5. Audit stopped JSONL with the existing `star.process_loopback_private_audit_cli`. A positive audit is evidence of bounded diagnostic consistency only, never proof of audio quietness or authority for game actions or stream publishing.

## Highest-value intelligence/streaming research — implement after baseline measurements

The biggest quality improvements are not extra personality prompts or unchecked recursive self-training. They require **grounded real-time perception, an efficient reaction loop, trustworthy memory, and measurable evaluation under load.**

| Layer | Highest-value experiment | Quantifiable gate |
|---|---|---|
| Game reaction | Very small action-priority path at 10–30 Hz; plan asynchronously, never block input-release safety | Held-out win/progress, missed action deadlines, real-world input release, FPS while OBS runs |
| Tactical reasoning | Fast local model handles immediate reactions, bigger reasoning worker plans only when resources allow; stale answers discarded | Median and p95 capture-to-action, errors under partial vision, abstention accuracy |
| Learning | Preregistered holdout maps/seeds with independent game-state outcomes; freeze policies before eval | Paired success with confidence intervals and zero train/holdout overlap |
| Roblox creation | Inspect target objects before edits; test game runtime through Roblox Studio executable checks | OpenGameEval pass@1, pass@5 and repeated-consistency metrics, plus rollback rate |
| Voice | Compare CPU-first voice candidates to current TTS while running games and OBS | First audible chunk p95, speech intelligibility, interruptions, GPU headroom and real player feedback |
| Personality | Situation-driven speech timing and silence; log only consented and verified memories; honest AI identity | Speech timing judge, interruption recovery, incorrect game claims, viewer satisfaction without parasocial manipulation |
| Infrastructure | llama.cpp prompt caching, speculative decoding, EAGLE3, and lower model concurrency; never extrapolate from paper FPS | Same hardware prompts and load, p95 first-speakable time, VRAM, game FPS and OBS drops |

### Specific upstream evidence

- **Proact-VL (Microsoft, ICML May 2026)** separates the challenge of *when to speak* from what to say in real-time gaming contexts. Star should have a proper silence/turn-taking action—not a forced commentary action every few seconds. https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/
- **Roblox OpenGameEval (October 1, 2026)** reports 84 core tasks and 13 models. The authors find that inspecting objects relevant to intended edits associates with better success. This supports verified tool exploration and playtesting, not claiming that adding documents improves coding intelligence. https://arxiv.org/abs/2610.02563 and https://github.com/Roblox/open-game-eval
- **llama.cpp SPEED-Bench** measures prefill/decode throughput, latency and speculative acceptance. Its baseline-vs-candidate procedure can establish whether EAGLE3/draft decoding helps on Star's actual 8 GB-class hardware instead of assuming a speedup. https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md
- **Kyutai Pocket TTS** has small CPU-oriented English variants (October 2026). This may free VRAM for game rendering, but must be tested for first-audio latency and voice quality on Star's own PC. https://github.com/kyutai-labs/pocket-tts
- **NVIDIA Dynamo** supports larger multi-worker serving with KV-aware routing and cache management, but a single 8 GB GPU competing with OBS and a game is not the obvious first deployment: prove a simple local server is saturated before adding distributed overhead. https://docs.nvidia.com/dynamo

## Evidence and limitations

Synthetic source tests are not evidence of physical Windows playback, a natural voice, increased neural reasoning ability, completed Roblox game creation, or improved game performance. The Windows CI invocation checks *its own newly built files* and is **not** an independent owner-side attestation. The new module is default-off, stdlib-only, and releases no PCM, chat, games or personal data.

Near-term priority: pass the independent Windows package verification, then a private, nonbroadcast supervised process-loopback trial; only after that evaluate a complete streaming rehearsal and paired model/TTS speed improvements.
