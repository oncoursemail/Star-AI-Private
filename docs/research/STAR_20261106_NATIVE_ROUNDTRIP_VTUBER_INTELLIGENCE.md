# Star AI — native game roundtrip, intelligence, speed and VTuber research
**Research date:** 2026-11-06 · **Stage:** offline host adapter + tests; no live play or stream

## Key finding: the Windows worker is blocking, unlike the generic event clock
Star already has a consent-gated Windows input stack:
`windows_game_input_port.py` -> `windows_game_input_watchdog.py` ->
`windows_game_input_worker.py`. The nested process waits until a bounded
key-down/key-up is complete and the worker/watchdog respond. That return must
**not** be stamped as the instant input was submitted in
`HostMonotonicGameProbe.guarded_dispatch`. It would inflate host-submit
latency, conflate model reasoning and input worker startup, and undermine
evaluation of fast reactions. Earlier documents that said no Windows watchdog
was implemented are outdated for this branch: the existing watchdog is real
code, albeit not proof of physical input or game outcomes.

**Delivered in this change:** `NativeGameRoundtripAudit` measures three
separate stages around the existing approved port: capture-to-decision;
duration of the synchronous native send/release call; and capture-to-confirmed
host return. It rejects stale decisions before calling the port, aborted
sessions, missing key-up/focus postflight, worker failures, monotonic clock
regressions, incomplete windows and late host callbacks. It rejects the
ENTIRE batch after any failure rather than cherry-picking successful attempts.
Privacy-minimal reports contain only counts/p95 durations and explicit
`authorizes_gameplay=False`, `authorizes_broadcast=False`,
`game_effect_attested=False`, `input_release_guaranteed=False`.
Even a green result is NOT an input-submission timestamp, device proof,
a completed game objective, or an authorization to play.

### Tested / not tested
The host adapter can be exercised completely offline with a fake typed port
and deterministic clocks. No real Win32 input was generated during this run.
The real Windows watchdog remains independently scoped to the target
app/desktop and never provides cryptographic proof of OS acceptance.

## Real hardware resource observation (read-only, Nov 6, 2026)
On the connected Windows Main PC, a single `nvidia-smi` snapshot reported:
- **RTX 3060 Ti, 8,192 MiB total, 7,743 MiB used (~449 MiB free), 31% GPU utilization**.
- A `llama-server` process was present. OBS/Roblox Studio were not present
  in the process-name check. This does **not** prove what occupied VRAM.
- No model was loaded or changed, and no game, OBS stream, or TTS was started.
- The connected Linux development host still had ~12 GB free on a 218 GB
  root filesystem (~95% used), making new large model downloads inappropriate.

The mismatch (high VRAM allocation / moderate compute use) is why model
routing cannot be inferred from GPU utilization alone. A meaningful benchmark
needs synchronized idle vs loaded measurements, GPU process attribution,
prompt lengths/context, model quantization, tokens/sec, time-to-first-token,
CPU utilization, memory RSS, OBS render/encode frames, game FPS and audio p95.
Do **not** claim speed gains without matched independent A/B measurements.

## Highest-value architecture upgrades (priority order)

1. **Trusted native rehearsal:** Wire the owner-approved native port, game-state
   signed telemetry and this roundtrip audit into a private, automation-permitting
   game with a pinned HWND/PID. Collect separate monotonic *actual native
   submission* timestamps from the worker if available, rather than relabeling
   its blocking return. Require game-state deltas from a trusted game bridge;
   mark missing/late/out-of-order events unknown, not wins. Independent
   key-up and focus checks are best-effort and cannot defeat OS suspend/UIPI.
   Keep a physical owner kill switch. No public broadcasting until reviewed.
2. **Faster thought through scheduling, not invented hardware:** Protect OBS
   game/render frames and speech first, use tiny reflex logic for time-critical
   movement, medium local model for tactical planning, and deeper models for
   background replay/learning. Idle-time tasks must yield on FPS, GPU VRAM,
   TTFT, speech backlog, and OBS render/encode pressure. On this observed
   8 GB GPU snapshot, a new GPU worker is a bad default.
3. **Speculative decoding benchmarking:** llama.cpp supports draft-model and
   n-gram speculation; acceptance rate and per-stage compute overhead determine
   net throughput. Isolate per-user KV/session caches and compare matched
   requests under memory limits. Do not assert Q4/Q5 or model size fits VRAM
   without measuring concurrent context KV, rendering and OBS allocation.
4. **Speech on a constrained GPU:** Benchmark Kyutai Pocket TTS
   `english_18m_2026-10`, `english_7m_2026-10`, and experimental 2m
   using CPU-only decoding *under actual gameplay*, not alone. Score first
   audible PCM, interruption stop time, intelligibility/voice consistency
   and synchronization with the avatar against the incumbent baseline.
5. **Game skill mastery through verified practice:** A fast reflex worker
   handles a continuous control loop; strategy worker models opponent
   intents, objectives and uncertainty; offline teacher proposes drills.
   Use signed game outcomes, same-game held-out seeds, unseen-game tasks,
   adverse latency jitter and real wall-clock deadlines. Attribute reward
   to independently witnessed outcomes, not model assertions or chat cheers.
   Keep a memory of failed strategies and retest before promotion.
6. **Roblox autonomous inspect→build→test→repair:** Use official Studio MCP
   scoped by game and authorization. Inspect actual game state first; generate
   Luau and 3D assets; static-analyze with luau-lsp/Selene/StyLua; run
   executable scene/game checks and Play Solo smoke tests; collect visuals;
   run best-of-N only with fixed independent rubrics and no hidden holdout leak.
   Production changes require separate explicit permissions.
7. **Humanlike *functional* streaming behavior:** Star should be visibly
   disclosed as AI but maintain consistent non-deceptive personality,
   conversational memory with provenance, natural silence under gameplay
   danger, warm humor tied to verified events, short spontaneous observations,
   refusal to repeat private chat, owner barge-in and guest speech turn-taking,
   speech with breath/pause prosody, and time-aligned eye/face/gesture control.
   Build a real double-buffered output pipeline so talk/animation can be
   preempted when focus, VAD, scene or OBS health changes between planning and
   first PCM. Treat social rapport as conversation quality, not human identity.
8. **Knowledge and self-improvement:** Keep retrieval provenance and
   uncertainty, verify code/scientific facts against independent sources,
   self-generate training tasks with difficulty adaptation, train only on
   approved practice data, freeze validation/holdout sets and require
   regressions across coding, general knowledge, game mastery and dialogue.
   Prefer offline tests and reversible local Forge history; GitHub is for
   reviewed public publishing, not a mandatory self-improvement dependency.

## Suggested acceptance measurements before deploying any game/VTuber worker
- Report median/p95/p99 capture-to-decision and capture-to-key-up separately,
  with *all* offered frames counted (drops/timeouts are failures). Capture
  action-to-state-effect via signed in-game telemetry, distinct from OS return.
- For gameplay: report objective completion, collision/death/unsafe acts,
  previously unseen maps and uncertainty intervals; never infer wins from
  `SendInput` receipts. Include paired fast/slow variants and random seeds.
- For general knowledge: predeclared correctness, citations, refusal/unknown
  calibration, latency, cold/warm cache and memory leak tests.
- For natural voice: first audible milliseconds, missed interruptions,
  false barge-ins, unnecessary talking during critical moments, audio/video
  offset, OBS dropped/render/encode frames, and blinded preference judgements
  using the same audio level and game moments.
- Fail closed on offline telemetry or sudden resource saturation. Keep
  automated approval and public broadcasts **off** by default.

## Official / primary research checked 2026-11-06
- Microsoft GetAsyncKeyState, return-value ambiguities and inaccessible desktop:
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate
- Microsoft SendInput, UIPI and existing keyboard-state caveats:
  https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput
- Roblox OpenGameEval, executable checks and 84 curated Studio tasks (2026):
  https://github.com/Roblox/open-game-eval
- Roblox Studio MCP per-game Open Cloud permission boundary:
  https://create.roblox.com/docs/studio/mcp-open-cloud
- NVIDIA DyaPlex, synchronous duplex speech and motion (June 2026):
  https://research.nvidia.com/labs/amri/projects/DyaPlex/
- Kyutai Pocket TTS v4.0.0 Oct 20 / v4.0.1 Oct 21, 2026:
  https://github.com/kyutai-labs/pocket-tts/releases
- llama.cpp speculative decoding options and acceptance statistics:
  https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
- OBS Studio websocket with default inclusion from OBS v28:
  https://github.com/obsproject/obs-websocket

## Integration and risk notes
This is a Windows-host **measurement adapter**, not a smarter foundational
model, an OBS stream, or a game controller. Its test fake cannot prove actual
Win32 performance. The adapter's p95 includes worker/watchdog startup,
key-hold, release verification and subprocess communication — intentionally.
The existing `HostMonotonicGameProbe` remains a **separate** event-driven
recorder until a trusted worker exposes real submission lifecycle timestamps.
Do not feed these native blocking-return timestamps into that recorder as
if they were actual key-down times. No games or other desktops were modified.
