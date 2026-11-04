# STAR: bounded parallel commentary, grounded gaming and VTuber intelligence

**Research checked:** 2026-11-04. **Implementation:** `star/stream_parallel_commentary_prefetch.py` and deterministic tests. **Stage:** opt-in text-only infrastructure, not a real Windows TTS/OBS/game integration or measured inference speedup.

## The performance opportunity that changes the architecture

Kawamatsu et al., **IJCAI 2026** ("Low-Latency Real-Time Audio Game Commentary System via LLM-Based Parallel Text Generation") specifically identify *sequential* perception → LLM → TTS → speech playback → next generation as a cause of unnaturally large pauses. Their *study system*, generating while the prior speech is playing and buffering candidates, reduced reported mean inter-utterance silence from **9.6 s to 0.3 s** on their game videos. This is evidence for overlapping work, **not a claim that STAR achieves these values**. This research is more actionable for natural VTuber pacing than another round of general "talk faster" prompt edits.

**Source (IJCAI 2026 proceedings):** https://www.ijcai.org/proceedings/2026/972

Microsoft Research's **Proact-VL (ICML 2026)** distinguishes *whether to speak* and *how much to speak* from merely describing frames. Continuous chatter can make a VTuber less believable and hurt player performance. Parallel generation should happen only when a grounded, useful new signal exists, with explicit silence, barge-in and gameplay-priority guards.

**Source:** https://www.microsoft.com/en-us/research/publication/proact-vl-a-proactive-videollm-for-real-time-ai-companions/

## Working source added

The new opt-in `StreamParallelCommentaryPrefetch` lets a trusted host reserve **at most two** text candidates while an actual `StarStage` plan is already acknowledged audible. A separate low-priority inference worker can draft a short comment *during* playout, and the host can submit independently moderated text when complete. Nothing automatically calls a model, TTS, an audio device, OBS, a game, or a network.

Strict handoff guarantees at the Python coordinator boundary:

- Off unless `enable(owner_approved=True)`. Must reserve against `stage.current(audible_plan)`, so an unplayed/generated/queued utterance cannot manufacture a parallel-planning opportunity.
- Only **observed** `game_observation` and `game_success` signals with a pinned game scope, or upstream-moderated `viewer_question` signals. Danger is too urgent to prefetch; viewer banter/ambient spam should not consume scarce GPU resources.
- Require trusted-source moderation, host-verified event provenance and explicit spare-compute admission at reservation. The host must re-check actual GPU/OBS/TTS pressure before every workload.
- A draft may be **320 printable characters** maximum, is host-moderated before admission and expires after no more than **four seconds** by default. Silence is preferable to a stale reaction.
- Every candidate binds to a one-shot ticket object, session epoch, AI worker epoch, game scene epoch and the exact originating signal. Stale, duplicate, wrong-worker and wrong-scene tickets fail closed.
- At consumption, verify the *real* `StarStage.prepared(plan)`, exact signal ID, type, evidence, game scope, and deadline. If different commentary won stage arbitration, discard the prefetched text.
- An accepted `PreparedComment` explicitly sets `authorizes_audio_output=false` and `authorizes_broadcast=false`. The host must STILL separately queue TTS audio, check the `stream_preplay_fence`, obtain live worker/audio clearance, acknowledge PCM consumption, and only then animate lips or mark a comment spoken.
- `scene_changed()` and `disable()` discard all text; bounded metrics contain counts only, not game/chat/voice contents.

**How to integrate it on a trusted Windows VTuber host:** accept and moderate a source in `StarStage.offer()`; when a different plan is actually audible, reserve the new event and send its prompt to a low-priority/background text worker. When generation returns, validate worker provenance, do content moderation, then call `complete()`. Once the current utterance actually ends, run normal `StarStage.prepare()` and `take_for_plan()`. Use the prepared text only if the host independently checks it still answers the selected event and then executes all preplay/liveness gates. For high-risk gameplay, a new owner interruption, new OBS pressure or missing witnesses, drop the candidate instead. Never stream or record automatically based on this cache.

**Trust boundary:** The pure-Python `host_verified`, `spare_compute`, `model_epoch` and `scene_epoch` values are not cryptographic attestation. Host software MUST derive them from trusted OS/voice/game adapters and worker supervisors, not chat content, model output, or serialized remote suggestions. A forged local host or plugin can defeat this advisory layer. The current module is not wired into the live Windows worker, so no actual response-time improvement has been measured.

## Highest-value follow-on engineering

### 1. Natural, genuinely realtime VTuber behavior

Measure three distinct delays rather than one vague "latency": (a) game observation → confirmed relevant signal, (b) selected signal → generated/moderated text, and (c) selected signal → **first actually audible PCM**, plus silence after the previous utterance. Compare sequential vs parallel text generation on the same game traces, RNG seeds, audio prompts, hardware load and speech quality. Include overspeaking, answer factuality, missed owner interruptions, GPU-low-memory stalls, skipped game frames and OBS dropped frames as vetoes.

A speaking policy should prioritize actual danger, direct questions and genuinely funny/surprising moments. Keep short humanlike follow-up acknowledgments, contextual jokes and understandable reactions; also keep appropriate silence. Avoid manufactured emotional claims, fabricated game memories, fake friend relationships, or concealing that STAR is AI. A consistent persona is a behavior-and-memory system, not a single "act human" prompt.

### 2. A real private OBS + game + TTS test (still missing)

The preceding local authenticated OBS read-only probe verifies GetStats, GetStreamStatus, and GetRecordStatus snapshots, not continuous safe output state or an actual recording. STAR still needs a separately approved **private nonbroadcast recording** controller with recording-state receipts, continuous stream-inactive checks, stop/cleanup policy and real frame/audio/avatar observation. Always isolate OBS WebSocket to localhost and require auth; never treat its password as permission to broadcast.

In the last Windows readiness snapshot, GPU free memory on the 8-GiB RTX 3060 Ti fell to **871 MiB**; the full game + OBS + avatar + live speech stack was not running. A low-priority parallel text model must be suppressed unless current GPU margin and FPS permit it. Inference quality, not idle tokens/s, determines suitability.

### 3. Improve game-playing and general intelligence with verified outcomes

GameWorld/ GameWorld-RT benchmark agents against serialized outcome states while the environment can keep advancing during inference. For STAR, develop an explicitly authorized **game adapter** with state receipts for score, life/HP, checkpoints, action duration, map transitions and true completion. Give the reactive path an action deadline; run tactical search and slow reflection between active decisions. Promote a new policy only after blind held-out maps/seeds beat the old policy on *success, normalized progress, P95 action deadline misses and no-cheat compliance*, not on narrated confidence.

**Sources:** https://gameworld-project.github.io/ ; https://arxiv.org/abs/2604.07429

Roblox Studio's **built-in MCP** can inspect the project, run playtests and simulate player input. It is now the recommended connection instead of depending on the older standalone OSS MCP. Run build→test→visual-check→repair loops in isolated places, with Luau analysis and independent multiplayer/graphics checks. GameDevBench (ICML 2026, 132 tasks) reports marked performance weakness for graphics-heavy tasks and gains from visual feedback, supporting image/video verification and geometry checks rather than text-only success.

**Sources:** https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ; https://sethkarten.ai/papers/gamedevbench.html

For grounded general knowledge and sustained self-improvement, index versioned Roblox/API/docs and game manuals with source timestamps, locally verified demonstrations and uncertainty. Route easy interactive queries to a small model, complex coding/research to slower offline workers. Run best-of-N generate-and-verify with *executable* tests and held-out tasks; never mistake self-produced explanations for evidence of smarter behavior. Store artifact hashes, resource/quality metrics and rollback states in the local-first internal Forge, publishing to GitHub only as an optional review/distribution workflow.

### 4. Specific next benchmark acceptance criteria

- Counterbalanced sequential versus prefetch trials on the **same** 30+ game-commentary scenes with host-verified event timing, audible PCM, and equivalent output quality. Report median/P95 gap and p95 first-audible delay, not just text tokens/s.
- **Zero** stale-game, wrong-worker, post-interruption or replayed utterances in adversarial tests; wrong-scene and non-moderated drafts should never reach output.
- FPS, audio dropout and OBS frame skips must not regress; no background generation under GPU/stream pressure or during critical combat.
- For independent gameplay promotion, use held-out levels and genuine score/progress/action receipts. For game creation, use Studio playtest and visual inspections on independent project snapshots.
- Require real owner-controlled Windows sandbox rehearsal before treating any of these as deployed VTuber capabilities.

**Verified in this increment:** in-process event identity / epoch / moderation / fresh-stage handoff with synthetic offline tests. **Unverified:** trained AI intelligence increase, live parallel inference, first-audible audio, OBS record/rehearsal, automatic gaming skill acquisition or any reduction in real-world speaking delay.
