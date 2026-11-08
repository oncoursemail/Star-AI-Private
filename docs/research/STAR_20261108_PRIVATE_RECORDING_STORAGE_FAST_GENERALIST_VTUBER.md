# Star AI — storage-safe streaming rehearsal, faster gaming and verified generalist learning

**Research date:** 2026-11-08. **Scope:** a real recording-volume admission improvement plus an implementation plan. **Status:** disk probe / CLI wiring and offline unit tests implemented; native OBS recording, real gameplay and inference speedups are NOT established.

## A concrete infrastructure bottleneck before more models

A gaming VTuber uses disk for OBS recordings, replay clips, logs, game updates, model caches and checkpoint experiments. A healthy GPU and stable OBS process do not mean the *recording volume* can hold the next test. Recording with inadequate free space can interrupt the very observations needed to measure Star's conversational timing or learn from games.

The existing `stream_windows_private_rehearsal_cli` checks process continuity and GPU headroom. Before this change, it had **no output-volume free-space check**. A Windows rehearsal could appear "candidate" while recordings had little space left. The new optional `--recording-dir` mode samples that *specific existing local directory*, does not leak the path, and downgrades readiness when disk evidence fails.

### What is now implemented

- `RecordingDiskGuard` uses local `shutil.disk_usage` only after explicit local opt-in. It verifies an existing non-symlink absolute directory. No network, file enumeration, OBS control, process creation or media writes.
- Requirement = **8 GiB OS reserve + forecast remaining recording bytes**. Defaults are a 12 Mbps total video+audio cap over 30 minutes. Thus a recorded-rehearsal candidate requires approximately **10.5 GiB free** at the selected output directory. These are conservative engineering defaults, NOT measurements of the owner's actual OBS bitrate or recording length. They are tunable in the owner-controlled API only.
- The guard rechecks disk headroom during a recording. If the estimate is exceeded, I/O fails or measurements become malformed, it latches revoked. The advisory requests **that the trusted host stop the recording** if already active. It NEVER claims it has stopped OBS, finalized a video, or protected the OS just by checking.
- CLI output includes `recording_storage_checked`, `recording_storage_ready`, `recording_free_mib` and `recording_required_mib`. These are advisory numeric readings without user paths or recording names. Without `--recording-dir`, recording-storage readiness remains explicitly **unchecked**, even if the ordinary process/GPU candidate passes.
- Safety: owner approval remains necessary; `recording_storage_ready=true` is not recording or broadcast permission. Never infer actual volume continuity across rewrites, mount changes, software crashes or the time after the last probe.

Read-only Windows CLI syntax:

```powershell
python -m star.stream_windows_private_rehearsal_cli --observe --game-pid <trusted PID> --game-exe RobloxPlayerBeta.exe --recording-dir "D:\\StarPrivateOBS"
```

The directory must already exist. In the owner audio/OBS host, call `RecordingDiskGuard.check(owner_approved=True, recording_active=True, remaining_seconds=...)` periodically, off the real-time audio callback. A request to stop must be acted upon and independently acknowledged by the trusted OBS host. Do NOT treat this example as permission to record another person's screen or to stream publicly.

## Deep research: intelligence, low latency and genuinely better games

### 1. Optimize the *whole interaction*, not just LLM tokens/sec

An AI can decode 50 tokens/sec and still miss the moment to dodge if frame capture, vision, model queueing, action arbitration and OS input acknowledgement take too long. **Gym-Anything-RT** (2026-10-27) uses paired running/slowed/paused minigames and demonstrates a substantial gap between untimed reasoning and real-time success. Use Star's existing `game_realtime_loop`, `game_deadline_router`, `game_capture_to_action_benchmark`, `game_action_outcome_feedback` and `game_holdout_once_ledger` rather than rebuilding a second control layer. Source: https://arxiv.org/abs/2610.37567

Benchmark an explicitly authorized offline game:
1. Measure timestamped **capture→perception→decision→input-ack→game-effect** on 20+ episodes with consistent seed sets, and separately the percentage of missed deadlines, p50/p95 latency and action success.
2. Run the same task under **game only**, **game+OBS**, and **game+OBS+avatar+voice** with GPU/CPU/VRAM/storage readings. Record 1% low FPS and OBS lost frames, not only average FPS.
3. Compare a small reactive route with a slower planner route. Keep the higher-level planner off the critical interaction thread and require independently verified game-state change before recording success. A fast action that is wrong or late is worse than an honest skip.
4. Promote a routing change only if it improves heldout task outcomes without increasing frame stutter, unsafe key holds or stream instability. Quarantine unsupervised self-editing of routing, policy and evaluation fixtures.

### 2. Make Star improve at *unfamiliar* games rather than memorize tests

Use a short, reproducible learning loop for three game-mechanic types (navigation, timing, opponent response), with fixed practice/validation/holdout boundaries:
- **Observe**: frames plus independently witnessed state transitions; remove stale captures, disguised menus and leaked goal state.
- **Hypothesize**: generate a small list of mechanic hypotheses with predictions (e.g. dodge after animation onset vs earlier). Store predicted outcomes *before* trying them.
- **Experiment**: one authorized bounded action sequence at a time, count failures and release keys reliably. Do not claim the game was beaten based on generated text.
- **Compare**: same seeded challenges, success rate, input acknowledgments, deadlines, time to completion and side effects. Include unseen scenes.
- **Retain**: promote only verified skills with provenance, game version, applicable conditions and expiry. Weak performance triggers more experiments, not fabricated experience or data poisoning.

Do not feed hidden holdout trials into training. Validate on independently run unseen challenges to distinguish generalization from memorization.

### 3. More human-like VTuber presence without pretending to be human

Natural interaction depends on **when to speak**, **when not to**, **whether interruptions work**, and **what Star accurately remembers**. Proact-VL studies proactive commentary on continuous video with timing decisions; apply this as a research direction, not proof that Star can already do it. Source: https://proact-vl.github.io/

Star's streaming speech pipeline should require:
- Short, evidence-grounded reactions tied to live game events; mix with genuine silence, occasional humor and natural self-correction. No commentary made from stale clips or invented accomplishments.
- Viewer turn-taking with explicit interruption logic; always prioritize an authenticated owner interrupt and game danger over unimportant ambient chatter.
- PCM playback supervision, native audio stop/drain and **actual completion receipts** before a line becomes an episodic spoken memory. Generated TTS length alone is not spoken truth.
- Avatar expressions and mouth gestures synchronized with **played PCM timing** and verified game/social events; preserve quiet/idle motions instead of endless lip movement.
- A stable, disclosed AI persona and opt-in, revocable social memories; a genuine personal style does not justify impersonating a human, collecting private viewer details, or simulating actual sentience.

### 4. Higher speed on constrained 8 GB GPU systems

Game rendering, OBS encoding, local VLM/LLM and TTS compete for memory and compute. No single model/quantization is universally fastest under contention. Benchmark at the **owner's actual simultaneous load**, not idle decode alone. Techniques worth paired experiments:
- Reduce repetitive prefill with verified per-session prefix caching while isolating user/private and public-stream sessions.
- Route quick reactions to a smaller fast model, difficult explanations to a deeper model, and asynchronous teacher updates to idle periods. Use deadline-aware admission rather than speculative floods.
- Test prompt-cache sizing, KV quantization, CPU/GPU layer placement and speculative decoding one variable at a time; report TTFT, decode tokens/sec and *actual task deadline success*. A seemingly faster decode can regress under CPU memory spill.
- Test CPU-based speech such as Kyutai's small October 2026 Pocket TTS variants for **first audible chunk, intelligibility, prosody, interruptions and impact on game FPS**. Published speed claims are not Star's speed data. Source: https://github.com/kyutai-labs/pocket-tts
- Use a minimum disk budget before any model download, cache expansion, checkpoint write or OBS recording. Never solve a latency problem by swapping into an almost-full system volume.

### 5. Better general knowledge and Roblox game creation

Separately index vetted Roblox API references, successful *executed* code examples, project-specific facts, new research and personal episode memory. Cite sources in development reports. Unknown facts should trigger retrieval or a targeted experiment, not confident invention.

Roblox announced built-in Studio MCP playtest and input simulation on March 5, 2026; its November 4 update expanded permission-controlled Open Cloud workflows, asset import, game settings and analytics. These are useful for a complete **inspect→design→build→test→repair→retest** cycle on an owner-selected private Studio game. They are also a serious capability boundary: `open_cloud_invoke` can create permanent assets and change game state, so write access must stay per-game restricted and approved. Sources:
- https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643
- https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849
- https://create.roblox.com/docs/studio/mcp-open-cloud

## Engineering acceptance and explicit limitations

**Implemented this increment:** a read-only local storage gate, an optional CLI recording-volume check and deterministic failure tests for low space, malformed readings, missing or symlink paths, permission refusal and mid-recording space pressure.

**Not implemented this increment:** OBS stop integration, automatic cleanup, long-term model training, native Windows output verification, actual recorded rehearsal, playable game learning, new foundation model, guaranteed human-level interaction, faster measured inference, or deployment to the real streaming host.

**Next evidence gate:** execute the recording-volume check against Star's actual approved OBS output folder; ensure the host uses it before and throughout a private nonbroadcast recording, and independently attests stop/finalization. Follow with paired game+voice+OBS latency trials and a heldout gameplay curriculum. Until such evidence exists, a `candidate` report remains advisory only.
