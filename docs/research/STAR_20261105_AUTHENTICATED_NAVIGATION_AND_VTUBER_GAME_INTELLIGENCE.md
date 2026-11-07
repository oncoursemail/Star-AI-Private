# STAR — authenticated navigation, game intelligence, low-latency VTuber research
Date: 2026-11-05 • Status: **code validated offline; real Windows game/voice rehearsal still required**

## 1. Evidence boundary delivered

New `star/game_navigation_source_bridge.py` closes a specific gap after the symbolic navigator:
the old `GroundedNavigationMemory.ingest(host_verified=True)` trusted a caller-provided
boolean. A model/tool could claim host verification without providing independently
authenticated frames. The new **opt-in, pinned, signed navigation bridge**:

1. Accepts a bounded frame carrying explicit source+session IDs, game/version/episode,
   sequence number, capture timestamp, actual player grid position, goal, and up to 128 tiles.
2. Verifies HMAC-SHA256 over a domain-separated, canonical payload. Use a **fresh key
   dedicated to this host/session**, not the moment-journal, Open Cloud, or model credentials.
3. Rejects missing/duplicate/unknown wire fields, fake boolean integers, invalid coordinates,
   unsafe player positions, noncanonical IDs, incorrect source/episode, replay, gap, MAC
   tampering, stale captures, and monotonic clock rewinds.
4. Samples its **own trusted host clock**, not a caller-supplied timestamp, and forwards
   `host_verified=True` only after successful authentication.
5. Atomically revokes its session and clears the map on invalid evidence. No reconnect,
   no reused receipts, no model-controlled stream or OS input. `advise()` remains symbolic.
6. Keeps developer-visible metrics restricted to accepted count and active/revoked booleans;
   it does not surface secret keys, positions, viewer data, or screenshots.

The signing helper `sign_navigation_packet` belongs solely in a **different
owner-controlled engine/test process** that reads authoritative game state. The signer cannot
establish that input came from the game on its own. A production host must pin its IPC peer
and authenticate/attest that the game state is authoritative. This update has not wired
that engine-side reader, OBS, Windows input, or a real Roblox game.

### Host-facing integration sketch (NOT executable by the LLM)

Owner starts a private engine host, pins a game/version/episode and a fresh secret,
collects true engine-sourced positions/tiles, and signs each monotonically numbered
capture. A separate trusted private host constructs the bridge with a fixed session and
reliable monotonic clock, enables it after owner permission, accepts signed packets
over a separately verified IPC transport, then requests symbolic navigation advice.
Only Star's existing `GameActionGate` and its private game-control policy may consider
dispatching input. The navigation hint **never** proves movement, learning, a win,
or permission to broadcast. Revoke all downstream control on bridge failure.

### Reproducibility and limitations

Run:
```bash
python -m pytest -q tests/test_game_navigation_source_bridge.py tests/test_game_navigation_memory.py
ruff check star/game_navigation_source_bridge.py tests/test_game_navigation_source_bridge.py
```

The offline fixture signs trusted synthetic map facts and verifies refusal under adversarial
conditions; it is not a live-machine gameplay test. Capture age/monotonicity are expressed in
milliseconds. A signed map cell only confirms the source's claim at capture time; dynamic
hazards need freshness-sensitive re-observation, and tile expiry stays enabled in the test.

## 2. Game-playing intelligence: the next evidence-driven jump

**GameWorld** (2026-04, and 2026-08 fine-control update) covers 34 browser games and 170
state-verifiable tasks. Its real-time track continues simulation while the agent infers,
making it a useful way to expose slow decisions. Use independent outcome/progress fields,
not an LLM's claim of victory:
- https://gameworld-project.github.io/
- https://github.com/gameworld-project/GameWorld

Suggested STAR curriculum: one deterministic control sandbox -> unfamiliar obstacle
layouts -> variable-speed platforms -> simple timing games -> multi-mechanic games ->
real-time benchmarks. Partition train vs held-out levels before running any trials.
Use run-level action and wall-clock budgets, randomized seeds, safe-abstention counts,
goal-completion rate, and actual success/time, not story-style self-grading. A candidate
skill is promoted only after repeated independent held-out improvements. Preserve
negative evidence and stop on unverifiable telemetry.

**Separate clocks and loops:**
- Fast reactive loop: cached deterministic policy, collision/health checks and limited
  action durations. Never wait for a large model to compute an urgent dodge.
- Tactical loop: goal decomposition, local navigation, experiment selection, post-action
  witness, new mechanics exploration.
- Slow learner: offline trajectory analysis, reusable verified strategy extraction,
  anomaly checks, practice task generation and independent comparison.
- Streaming director: game-aware selective speech, not always-on commentary; speaking
  must never block an emergency game action.

## 3. Roblox game creation: November 4 official MCP change

**Newly relevant:** Roblox's November 4, 2026 Studio MCP announcement adds
`open_cloud_invoke` with user-selected Open Cloud permissions, asset imports,
developer products/game passes, publishing/restarting, settings and analytics.
Official source:
https://devforum.roblox.com/t/studio-mcp-server-updates-open-cloud-access-in-your-mcp-client-and-asset-import-workflows/4975849

This is a *larger external-write surface*, NOT implicit authorization.
Star's existing `star/roblox_cloud.py` has its own endpoint allowlist and
owner-confirmed test-experience writes; do not bypass those controls by silently
calling newly exposed MCP functionality. Proposed follow-up: separate read-only
analytics from write tools; pin universe/place and permissions; require exact
owner approval for gamepass pricing, production publish, restart, asset import or
monetization changes; verify actual Studio/playtest changes, and keep backups.
Use Roblox's built-in Studio MCP and playtest loop for inspect/build/test/repair:
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643

## 4. Lower latency and better GPU sharing

A single 8-GB GPU cannot reliably maximize large-model inference, game FPS,
avatar rendering and OBS encoding simultaneously. Do not make unsupported tok/s
claims about model configurations. Benchmark the **whole workload** with fixed
prompts, fixed model files and identical repeatable workloads:
- p50/p95 perception-to-action, p95 speech-trigger-to-first audible chunk, input
  completion, real task accuracy and real game FPS (including 1% lows).
- peak VRAM, RAM, GPU duty cycle, CPU TTS contention, OBS dropped frames,
  prefill/decode latency and token rates measured separately.
- cache-hit vs cache-miss, KV allocation, context growth and background learning
  interference; test speculative decoding only where net speedup holds.
- when gaming/OBS begins, preempt heavy training, checkpoint experiments and
  restrict LLM concurrency instead of oversubscribing the 8-GB GPU.

Kyutai Pocket TTS October 20/21, 2026 releases added and repaired very small CPU
English voice models (18.2M / 6.9M / 1.9M parameters). Test CPU x86 builds against
Star's actual naturalness, prosody, first-chunk latency and resource demands. The
project also ships a Rust standalone runtime. These are *options*, not
installed/verified upgrades:
- https://github.com/kyutai-labs/pocket-tts
- https://github.com/kyutai-labs/pocket-tts/releases

## 5. Humanlike without deception: a distinctive AI VTuber

Star's high-quality VTuber target is a stable, **transparent AI character** with:
- Identity, expressive temperament, recurring interests, long-term project notes,
  episodic memories and consistent voice/gesture style across sessions.
- Grounded moments tied to actual signed game outcomes. Avoid fabricated
  victories, hallucinated social relationships and unverified autobiographies.
- Full-duplex interruption handling, deliberate silence, viewer-turn
  prioritization, speech cancellation on new danger, backchannels and expressive
  reaction timing. Compare lightweight speech components against PersonaPlex-like
  research only when memory fits; do not assume a 7B full-duplex model will fit
  beside an 8-GB gaming workload.
- Personality memory separated from facts: personal preferences are fictional
  character settings; factual claims require sources and freshness timestamps.
- Opt-in interaction profiles, no unsolicited DMs to people, moderation controls,
  independent mute/stop switches, avoid voice cloning without consent, and
  no public broadcasting during private rehearsals.

Candidate reference: https://github.com/NVIDIA/personaplex

## 6. Acceptance gate: Windows private rehearsal

Required before promising autonomous game-playing or improved stream performance:
run a local, private 15-minute OBS+game+avatar+TTS rehearsal with synthetic
playtest scenes and explicitly authorized Windows input. Ensure the capture source
and game process are pinned independently, record objective outcomes, capture
OBS dropped frames and exact p50/p95 delays, and confirm fail-closed behavior
when capture stalls, packets are corrupted, or user clicks Stop. Compare to a
pre-registered baseline; only ship if accuracy/reliability and frame stability
are not degraded. Public streaming and self-modifying production code remain
separate owner-controlled phases.

### Not claimed
No live engine signed-frame producer, real external-game victories, public stream,
neural fine-tuning, actual inference acceleration, or human consciousness was
demonstrated by the code in this change.
