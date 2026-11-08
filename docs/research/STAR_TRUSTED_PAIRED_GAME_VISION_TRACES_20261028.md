# STAR AI — Trustworthy Gameplay Vision Experiments
**October 28, 2026 | Offline integration draft | Not deployed**

## Reason for this change

STAR has authorized single-window capture, a local paired-frame VLM worker,
selective visual memory, stale-result backpressure and a *quality* comparator
(`star/stream_vision_eval.py`). The comparator can score real categorical
holdout traces, but there was no small bounded host-side contract for collecting
those predictions, freezing a cohort **before** the labels are known, and
exporting strict records. Optimizations judged solely by synthetic RGB timings
risk reducing accuracy during actual gameplay.

The new `star/stream_vision_trace_host.py` introduces an opt-in owner-only
**paired vision trace host**. A trusted host supplies a digest/sequence/time
for one captured frame, runs both baseline and candidate models against those
same bytes, submits their accepted categorical packets or explicit
failures/timeouts, and freezes *all* predictions before an independent engine
or blinded human scorer can attach categorical truth. It exports the
`VisionEvalCase` JSONL schema directly. The scorer never shares individual
holdout labels with the gameplay planner or streamed persona.

This is an offline *instrumentation* bridge — not visual recognition, autonomous
game playing, on-air content, newly trained weights or a game-engine verifier.

## Source-backed strategy

- **OpenGameEval**, October 1, 2026:
  https://arxiv.org/abs/2610.02563
  Roblox evaluates 84 tasks inside reproducible Studio worlds with executable
  scene/play checks. Its best reported single-attempt pass rate is 51.7%;
  inspecting relevant scene objects before editing correlates with better
  success. STAR should prioritize actual, verified Studio tests over generated
  code that merely parses.
- **GameWorld**, April 8, 2026:
  https://arxiv.org/abs/2604.07429
  Its 34 games and 170 tasks use serialized game state for ground truth,
  with a real-time track explicitly exposing inference delay. STAR should
  measure visual quality, first action timing and actual FPS concurrently.
- **VISTA active self-exploration**, October 26, 2026:
  https://arxiv.org/abs/2610.35051
  Candidate harness changes are tested on fresh environmental rollouts and
  tracked in an experiment graph. STAR Core Forge should use this pattern:
  hypothesis -> fresh pilot -> independent outcome -> retain/revert.
- **CEGame-Bench**, October 19, 2026:
  https://arxiv.org/abs/2610.26098
  Generated games often integrate but do not complete. STAR needs end-to-end
  playthrough, persistence, reset and restart tests for game projects.
- **Pocket TTS v4.0.1**, released October 21, 2026:
  https://github.com/kyutai-labs/pocket-tts/releases
  The Oct 20 v4.0.0 release includes small 18M, 7M and experimental 2M
  English models. Benchmark on STAR's dedicated CPU with actual first-*audible*
  audio latency, naturalness, intelligibility, CPU load and in-game FPS;
  published vendor metrics are not measurements on STAR's hardware.
- **LiveKit local turn detector**:
  https://docs.livekit.io/agents/logic/turns/turn-detector/
  Local v1-mini can inform genuine interruptions; do not treat ordinary
  breathing, a brief acknowledgment or synthetic game audio as owner speech.
- **Roblox Studio native MCP**, March 5, 2026 announcement:
  https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
  Use authorized private Studio playtests and built-in inspection tools;
  never run tests in public matchmaking or interact with other players' accounts.

## Implemented contracts

1. **No passive capture or arbitrary model tool.** The local host must
   explicitly enable collection and recheck capture permission for each frame.
   No model can start Windows capture through this module.
2. **Exact frame pairs.** A monotonically ordered frame number, timestamp and
   SHA-256 digest bind one row. Repeated hashes are rejected to avoid blindly
   inflating nominal holdout size with identical frames.
3. **Explicit physical worker completion.** Every model run must report a
   host-confirmed stopped worker; missing/failed runs cannot disappear into an
   apparently faster result. Unjoined workers do not count as stopped.
4. **Blind frozen holdout.** Both predictions are committed before the cohort
   is sealed. An isolated independent scorer can then write one final
   categorical label per case. No new predictions or rewritten truths.
5. **Bounded private records.** 1..4096 cases, categorical fields only, no
   screenshot, chat, speech, player identity, model prompt or raw text.
   Exports require owner approval, write new `.jsonl` only and restrict Unix
   permissions to 0600; the model must never have read access to the folder.
6. **No automatic promotion.** The existing `compare_vision` reports
   accuracy, freshness, worker failures and p95 latency. An eligible verdict
   authorizes only **manual pilot review**, not any deployment.

**Important trust boundary:** A Python Boolean and SHA-256 digest cannot
authenticate an independent Studio engine. The embedding application must
keep baseline/candidate capture bytes equal, isolate scorer credentials and
unseen holdout seed IDs, prove the window is an approved local/private world,
and protect files from model access. `truth_source` is a description rather
than a cryptographically verified attestation. An independent evaluator must
retain its raw receipts elsewhere and not feed them back into the model.

## Host integration outline (for authorized Windows/Roblox Studio testing)

- Use `WindowsGameCaptureHost` only after existing owner/window/PID/focus
  checks; maintain **one immutable captured frame** while sending separate
  worker copies to baseline and candidate, never substitute another capture.
- Assign one monotonic frame sequence and SHA-256 digest in the trusted host.
  Submit `HostFrameRef` to `PairedVisionTraceHost.reserve()`. The host
  must never pass the ticket to the model or to viewer chat.
- For each variant use the model's existing `VisualPacket`, measured
  monotonic request timestamps and confirmed worker stop. If inference fails,
  submit explicit `timeout`/`error`, not a fabricated empty success.
- Freeze the cohort with `seal_predictions()` before an independent engine
  check or blinded reviewer attaches labels. Evaluate untouched
  versions/levels not used in tuning. On consent withdrawal, `disable()`
  clears in-memory records and invalidates old tickets.
- Export a private JSONL outside Git repositories or accessible project folders;
  score with `python -m star.stream_vision_eval private-trace.jsonl`.
  Score separate heldout game versions and task types, not a convenient
  single static menu. Record first audible speech, OBS dropped frames and real
  gameplay FPS independently.

## Research-informed next engineering milestones

**Intelligence and mastery:** Integrate the real trace host into authorized
Windows game frame callbacks; link signed `GameTrial` outcomes to predictions,
action gates and the existing practice curriculum without leaking holdouts;
use fresh unseen game versions as independent transfer evaluations. Add
controlled A/B tests for attention ROI vs full-screen inference, and do not
promote any configuration that becomes slower or hallucinates cues.

**Game building:** Run OpenGameEval-style scene/object inspection before edits;
require real play-to-ending, respawn, save/load, collision and placement tests.
Score UI hierarchy/readability, animation physics, rig grips, asset ownership
and performance in actual Studio captures, not only code tests.

**Humanlike VTubing:** Prefer authentic reactions to verified events, voice
playback acknowledgments, soft expressive eyes, delayed hair/ribbon physics,
contextual laughter and natural silence. Use local owner-controlled
turn-taking, selective moderated viewer questions and persistent *genuine*
game experiences. Preserve STAR's chosen persona without inventing a human
offline childhood or claiming biological consciousness. Disclose she is an
AI VTuber; respect other players' privacy and game anti-cheat rules.

**Speed:** Start with CPU TTS vs GPU VLM contention and quantized model trials
under a 4060 8 GB workload. Record p50/p95 first-audible response time, VRAM,
voice backlog, true game FPS, perceptual F1 and completed objectives before
claiming a gain. Keep heavy research/long rollouts off the live game path;
allow rollback of regressions in Star Core Forge (GitHub is optional publishing).

## Verification scope

Synthetic, offline unit tests exercise the collector, privacy of output,
prediction freeze, immutable truth labels, time/frame identity, worker
failures, export protections and the existing quality scorer. This does **not**
establish that any local model is accurate or fast in actual Roblox/OBS use.
The repository `Star-AI-Private` is currently **public**, despite its name;
never upload private traces, receipts, screenshots, personal data or secrets.
