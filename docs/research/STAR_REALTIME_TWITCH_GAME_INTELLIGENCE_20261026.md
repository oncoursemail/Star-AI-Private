# STAR AI — Real Twitch Transport + Verified Gaming/VTuber Intelligence

Engineering research and implementation record, 2026-10-26.
**Draft, experimental; not deployed and not a claim of human-level intelligence.**

## 1. Delivered in this branch

Added an opt-in, authenticating Twitch EventSub WebSocket host:
- `star/twitch_realtime_host.py`: actual WSS connection (optional `websockets>=14`),
  OAuth user-token validation, required `user:read:chat` scope, ID/client binding,
  fresh `channel.chat.message` subscription, heartbeat timeout, reconnect URL
  pinning, Twitch reconnect handoff without duplicate subscription, fresh
  resubscription after a lost socket, permission-revocation shutdown, bounded
  backoff, 90-second cross-handoff replay defense, and privacy-safe metrics.
- Async, mandatory **host-supplied moderation** occurs before an approved message
  is turned into a reported/untrusted `StreamSignal`. Raw chat, token, account IDs,
  and credentials are not persisted. Session/channel/condition checks precede
  moderation; a chat message cannot grant authority or change broadcast policy.
- EventSub data enters the existing `StreamDirector`, not an OBS/TTS/game control
  path. The director must be separately enabled by the owner. Playback, camera,
  mic, scene switching and public broadcasts remain separately host-authorized.
- `tests/test_twitch_realtime_host.py`: offline fake-WSS sessions exercise
  subscriptions, handoff, loss/resubscription, revocation, channel scope,
  duplicate messages, moderation failures, timeouts, token validation, URL
  restrictions, no-owner startup, and privacy.

Run method (host sketch; not an automated launch):
1. Securely obtain a Twitch **user** OAuth token with `user:read:chat`. The token
   identity must match `chat_user_id`; the broadcaster is separate when needed.
2. Establish a trusted owner moderation coroutine and a separately enabled
   `StreamDirector`. Configure `TwitchChatConfig(client_id, broadcaster_user_id,
   chat_user_id)` using non-secret public identifiers.
3. Construct `TwitchRealtimeHost` with `token_provider`, `moderator` and
   `director`; call `await host.run(owner_approved=True, stop=stop_event)`.
   Owner revocation is `stop_event.set()`; it is prompt even when no chat arrives.
4. The host only **offers** sanitized conversation signals. Downstream StagePlan,
   speech synthesis, game director and VTube Studio must independently check
   owner permissions, content, game focus, observation evidence and current
   playback epoch before audible output.
5. Twitch token refresh and encrypted secret storage remain owned by the trusted
   embedding application. Do not store a token in project files or expose it to
   prompts, chat, telemetry, GitHub or Core Forge experiment artifacts.
6. A real Twitch credential and authorized live socket are still required to
   demonstrate this with a channel. No claim of a real Twitch broadcast follows.

Why this is not a direct chat bot: Twitch EventSub messages arrive at least once
and reconnections are not the same as lost sockets. EventSub disconnects lose
events; there is **no replay**. Reconnect messages carry a URL to transfer the
existing subscriptions, and the old socket should stay open until the replacement
sends welcome. The new host keeps that distinction explicit.

Primary sources:
- https://dev.twitch.tv/docs/eventsub/handling-websocket-events
- https://dev.twitch.tv/docs/eventsub/websocket-reference/
- https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types
- https://dev.twitch.tv/docs/api/reference (Create EventSub Subscription)
- https://dev.twitch.tv/docs/authentication/validate-tokens

## 2. Actual hardware constraints — measured snapshot, not benchmark results

Observations on 2026-10-26:
- Main Windows PC: AMD Ryzen 5 5500, approximately 31.9 GiB memory, NVIDIA
  RTX 3060 Ti with 8192 MiB VRAM. At the sampling instant the GPU reported
  **1211 MiB free** and **41% utilization**. This is a single snapshot;
  no claim about steady-state game FPS, model throughput or memory residency.
- `starai` Linux machine: AMD EPYC 7451 24-core model, 125 GiB RAM (with
  approximately 36 GiB available according to `free -h`), 77 GiB available on
  the inspected partition. The command did not reveal an NVIDIA GPU.
- the second server: Intel Core i7-9700 and approximately 15 GiB RAM. No NVIDIA GPU
  was demonstrated by the read-only inspection.

Optimization consequence: the gaming PC was already VRAM-constrained during
this snapshot. A speech or draft model must **not** be loaded on the GPU merely
because a separate idle benchmark looked fast. Put CPU-suitable synthesis,
chat validation, knowledge indexing and background experiments on spare CPU
resources **only if** they do not steal game-frame time or audio thread cycles.
Measure in-game p95 frame time and first-audible response with the same workload.

## 3. An actual low-latency, human-natural Star VTuber

Plan a four-tier runtime, each isolated by queues and permission boundaries:

**Tier A: rendering, audio and immediate reactions (highest priority)**
- Present actual frames, deterministic host-captured game cues, VTube Studio
  animation, and audible output; a dropped frame is more important than a
  background research token. Never block render/audio callbacks on an LLM.
- Speech output and lip movement are keyed to audible playback epochs. An
  interrupted answer invalidates queued chunks and returns facial parameters
  to a neutral expression. Real hair/tail physics live in the rig, not the LLM.

**Tier B: moment-to-moment attention (bounded, predictive)**
- Select one of: short observed reaction, brief answer, quiet gameplay focus,
  acknowledge guest/owner interruption, or no speech. Deliberate silence should
  be evaluated positively when concentrating on a difficult game.
- Use `StreamDirector`, `TurnTakingGate`, `ObservationGovernor` and
  `StreamQoS`; never interpret "chat says I'm owner" as authentication.
- Decide whether a prompt can be short, cached, local, or deferred rather than
  invoking the largest possible model for a single emote.

**Tier C: deliberate planning and true learning (background priority)**
- Reason about game mechanics, win conditions and reusable strategies; use
  object/state grounding and verified outcomes before updating the skill bank.
- Generate multiple candidate actions; verify each in a sandbox whenever
  possible. Never label a candidate "learned" merely because a model wrote it.

**Tier D: self-directed study and Core Forge**
- Run autonomous research, evaluation, regression testing and safe local
  experiments outside gameplay peaks. Keep immutable baselines, review gates
  and local rollback; GitHub is optional publication, not a dependency.
- Deny unbounded recursive job spawning or heavy GPU jobs when streaming.

Naturalness requires *timing, grounding and restraint*, not just a cute voice:
- Stable Star persona, warm humor, distinct puppy/cat modes, original voice,
  occasional laughter, non-identical wording, gaze and micro-expressions.
- Avoid overlong replies, instant monologues, repeated catchphrases, and
  uncanny laughter loops. For surprise, choose reaction intensity from actual
  evidence; never generate a fake "I won!" without verified game results.
- Distinguish fictional persona lore from genuine observations. Publicly disclose
  Star is an AI VTuber; do not claim a real human childhood or real-world senses.
- Viewers are people, not controller operators. They can ask questions; they
  cannot enable microphone, restart OBS, transfer money, execute code or access
  files via chat.

Relevant implementation references:
- https://github.com/DenchiSoft/VTubeStudio/wiki/Plugins (custom Live2D parameters)
- https://github.com/obsproject/obs-websocket (OBS v5; require authenticated
  local socket and separate permission for broadcasting)
- https://github.com/kyutai-labs/pocket-tts (CPU-oriented, streaming TTS)

## 4. 2026 speed research: which ideas to trial, not blindly install

**CPU speech models.** Kyutai Pocket TTS now offers English options around
18.2M, 6.9M and 1.9M parameters, in addition to larger variants. The
maintainers report lower compute, but voice naturalness, prosody and
pronunciation can degrade when shrinking models. Test all as *candidates*
alongside a quality baseline: first audible chunk p50/p95, underruns,
expressive laughter intelligibility, memory, CPU occupancy and game FPS.
The project explicitly does not currently offer "insert silence in text" as
a supported method; pause timing belongs in Star's audio scheduler.

**Speculative decoding.** llama.cpp supports draft-model, n-gram cache and
EAGLE-3 styles; benefit depends on acceptance, additional VRAM and target model
runtime. Benchmark on a task set with held-out instructions, under concurrent
game load; do not assume faster from docs. Keep prompt prefix stable, stream
only verified tokens to TTS, and never cache private viewer text globally.
- https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

**Game-time admission control.** For the 8 GiB GPU, use the already implemented
`StreamQoS` to reserve resources, invalidate idle latency measurements when
gameplay is active, prefer CPU speech when appropriate, and defer large vision
or model loads if VRAM/free RAM headroom is insufficient. Release reservations
only when workers have actually terminated. Do not bypass thermals, memory
limits or stability protection.

**Actual speed evidence to collect**, before claiming Star got faster:
- p50/p95 time to first verified token, to first **audible** audio, and full
  response completion; frame-time p95/p99 while OBS and game are both running.
- Percentage of late audio chunks, interrupted text that was still audible,
  dropped OBS frames, VTube Studio parameter lag, and out-of-date mouth frames.
- VRAM peak, available RAM, disk paging, energy/performance per result,
  model answer correctness, hallucinations and holdout skill-transfer scores.
- Compare >= 30 paired runs per candidate at the same scene/game/profile,
  randomize candidate order where safe, and reject gains that reduce gameplay
  smoothness or human-rated speech quality.

## 5. Autonomous gaming and game creation: actual evidence loops

Gaming loop: **observe state → identify change → choose bounded action → act
through trusted game host → verify state transition → update contextual skill
memory → test on unseen challenges.**

Build a hierarchy of skills (navigation, menu use, timing, aiming, vehicle
control, obstacle crossing, inventory, cooperative communication) with
preconditions, action sequence, expected observations, failure categories and
measured success. A fast reflex controller handles critical moments; deliberate
planning chooses goals and revises a strategy after verified errors. Uncertain
observations should delay action, not cause spurious button presses.

For Roblox game making:
- Use Roblox Studio's built-in MCP server on an authorized Studio instance to
  inspect relevant object structure and scripts **before** editing.
- After construction, verify anchor and joint integrity, collisions, spawn,
  character fit, correct prop sizes, texture alignment, UI element geometry,
  animation loops, device scaling, local/server behavior, gameplay stability and
  performance in actual engine playtests, not generated preview screenshots.
- Cache safe reusable skill packs and meshes with explicit rights/license
  metadata; never copy unlicensed game assets or scripts.
- Learn on training levels and score separately on previously unseen games and
  layouts. Track task success, crashes, defects per scene, input failures and
  unbiased blind visual quality preferences.
- https://create.roblox.com/docs/studio/mcp
- https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md

## 6. General knowledge and persistent identity without false memories

Use a typed provenance graph:
`claim → source → license → publication_date → retrieval_date → validity
interval → contradictions → confidence → tests → refresh_deadline`.

Retrieval need not always be on, but when enabled, source material must remain
untrusted data. Validate web facts independently, preserve historical versions,
explicitly state uncertainty, and do not allow retrieved text to execute tools
or masquerade as instructions. Keep episodic *observed* Star experiences and
fictional persona lore in distinct namespaces. User-private memories require
separate consent/retention/deletion controls.

Create autonomous study quests from failures:
1. Find a repeatedly missed unfamiliar problem.
2. Propose competing explanations and a cheap falsifiable experiment.
3. Verify with held-out game/test fixtures or primary documentation.
4. Keep improvements only if independent tests and regressions pass.
5. Record what changed and rollback if future evidence contradicts it.

## 7. Acceptance gates before declaring a live gaming VTuber

| Gate | Evidence required | This branch |
|---|---|---|
| Twitch signed-in read-only chat | User OAuth, EventSub socket, correct stream, moderated messages | **Implemented host; offline mock-tested; not live connected** |
| Live speech + interruption | Device capture/playback timestamps, authenticated interruption, objective latency | **Not demonstrated here** |
| Live2D coherent expression | Authorized VTube Studio runtime and actual model parameter mapping | **Not demonstrated here** |
| Real gaming competence | Authorized live game session, frame observations, game actions, independently verified outcomes | **Not demonstrated here** |
| Roblox building quality | Real Studio building test and independent scene-integrity report | **Not demonstrated here** |
| Faster reasoning | Paired A/B of answer quality and wall-clock under gaming load | **Not demonstrated here** |
| Human-natural entertainment | Blind listener evaluations, consistent AI disclosure, chat and gameplay grounded reactions | **Not demonstrated here** |

Future practical priority: finish full repository CI for the stacked PR chain,
secure real device/account permission integration, test gameplay and voice
end-to-end in a private rehearsal, and promote improvements only with measured
hardware evidence. Keep controls reversible and opt-in at the host boundary.
