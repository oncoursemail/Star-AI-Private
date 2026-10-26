# STAR 2026-10-26 — Local Live2D Transport, Game Intelligence and Fast Human-Natural Streaming
**Status:** draft engineering implementation with **offline fake-transport tests**, not a deployed streamer, not a game-playing win, and not evidence of new foundation-model intelligence. **Parent:** #660 (stage-to-API playback-locked packet adapter). **This change:** `star/vtube_local_host.py` and `tests/test_vtube_local_host.py`.

## 1. What was missing, and what is now code
The previous STAR bridge could generate valid 14-channel VTube Studio packets but could not **connect to the desktop application**. This adds a deliberately narrow opt-in network boundary rather than another planning-only component.

`VTubeLocalHost` now implements:
- Explicit owner authorization; **IP-loopback-only** websocket endpoints (`127.0.0.1` or `[::1]`), no LAN/remote endpoint, DNS alias, or automatic service start.
- VTube Studio API-state query, native first-pairing consent/token request (only if separately opted in), existing-token authentication, and fail-closed API response validation (including echoed request IDs).
- Creation of the previous bridge's 14 custom controls. A repeat creation by the same plugin is supported by VTS, but a different plugin's colliding names fail; no silent hijacking.
- No disk credential storage, background streaming, microphone or OBS access. The returned VTS token must remain in a protected **local** host credential store, never in logs, chat, prompts, PRs or GitHub Actions.
- One synchronous, non-retrying send per currently authorized audible frame. It checks source-stage validity **both before and after** frame generation, checks that the caller's monotonic sample is <=100 ms old and not in the future, and lets the earlier bridge verify frame cursor, sequence, audio epoch, and rate.
- Short 100 ms socket timeout after parameter registration, to keep the live game from blocking behind the VTS connection. First-time permission prompt may use 30 seconds; all later control I/O is bounded. Malformed/error replies disconnect, without unbounded retries or replay.
- One post-device-stop neutral request via the previous bridge; a stale turn cannot reset a newer epoch. If the socket fails during this reset, VTS's own input-lost behavior remains the last-resort fallback.
- A pluggable socket factory allows fully offline tests without any live devices, network, stored secrets, broadcasting or gameplay input.

**Integration still required:** An authorized Windows host must obtain a real sound-card cursor (not text/TTS generation time), call `VTubeLive2DBridge.bind()` on an *already audible* StagePlan, and call `VTubeLocalHost.send_frame()` per sampled motion tick. It must send a neutral packet after **actual** playback stop; never infer stopped audio from an LLM response. The user/artist must map the 14 VTS input sliders to the actual original Star Live2D rig. This module does not create a Live2D model.

**Transport limitations:** A current-stage check immediately before a synchronous send narrows but cannot eliminate interruption races once a packet is on the wire. WebSocket ACK confirms application processing, not on-screen rendering, nor correctness of hair physics, visual timing, or the user's actual sound output. A private on-device rehearsal remains mandatory.

Official reference: https://github.com/DenchiSoft/VTubeStudio . VTS documents API 1.0 websocket at local port 8001 by default; permission token and AuthenticationRequest; custom parameter mapping and 100-per-plugin limit; 1-second injected-parameter refresh requirement. This module uses 14 and does not fake faceFound.

## 2. Human-natural streaming: achieve *presence*, not a deceptive human impersonation
Star should be a **disclosed AI VTuber** with an original consistent personality, not a service that falsely claims human memories or a real person's identity.

**Streaming pipeline:** permissioned game observations and moderated chat → event salience/urgency classifier → speak-or-silence arbitration → concise grounded utterance → incremental TTS → acknowledged PCM playback samples → measured mouth/eyes/ears/hair motion → VTS local socket → OBS preview/record only with explicit owner opt-in.

The key human-natural improvement is **turn economics**: respond neither at every chat message nor with arbitrary long monologues. Keep gameplay foreground. Prefer:
- brief utterances during timed combat, full sentences after safe moments, and silence when reacting would obstruct play;
- delayed surprise, self-correction, voluntary quiet, topic carryover, and callback humor grounded in real observed events;
- prosodic variation and occasional laughter/breaths **derived from an expressive TTS/voice model**, not one robotic laugh sample;
- head/gaze to actual UI landmarks; subtle blinks, independent ear/tail motion, secondary hair physics authored in Live2D; cat/puppy modes are rig profiles, not just voice effect toggles;
- fast owner interruptions, playback cancellation, and no animation for unheard text; conservative microphone echo control;
- a persona ledger that distinguishes authored backstory, role-play, observed gameplay history and real-world facts. Fictional backstory must be labeled fiction if asked.

**Model choices to benchmark, not blindly install:** Kyutai Pocket TTS supports CPU speech and October 2026 small 18.2M/6.9M/1.9M English models, but sound quality and naturalness may decline at smaller sizes. Compare baseline 100M with at least 18M/7M on Star's actual hardware. Moshi is a useful reference for duplex conversation; its GPU requirements are **not** evidence it will run well with a game on an 8 GB VRAM card.
References:
https://github.com/kyutai-labs/pocket-tts ;
https://kyutai.org/tts/ ;
https://github.com/kyutai-labs/moshi

## 3. Actual game intelligence: verified learning instead of self-reported mastery
STAR already has draft components for Studio gameplay action gating, authorized controls, independently signed outcomes and an active-practice planner. Connect them **only after host acceptance**, following:
1. **Observe:** screenshot/game state, timestamps, UI region detections, player position/health/objective and uncertain fields. Host evidence is not interchangeable with model guesses.
2. **Explain mechanics:** map controls to states; separate hypotheses ("jump timing may matter") from verified transitions and known rules.
3. **Explore safely:** choose a micro-skill, take one short authorized action, release keys, and wait for a new observation. Do not learn from stale frames.
4. **Verify:** a held-out evaluator—not the same agent that proposed actions—scores level completion, damage, time-to-goal and retry count using independent executable evidence.
5. **Retain:** store compact outcomes with task ID, seed, mechanic, controls, trace hash, uncertainty, license and limits; expire unreliable inferences.
6. **Transfer:** practice 2 distinct obbies then evaluate the skill on an unseen obby; rotate seeds and compare against a stateless baseline. Record confidence intervals and repeated failures.

For **creating** Roblox games: inspect existing scene graphs/scripts first, plan constraints and art direction, build with real Roblox meshes/PBR and coherent asset placement, run geometry/collision/anchoring checks, render screenshot and motion/animation tests, then conduct playable trials. A code-only pass is not enough: users notice protruding props, unattached walls, overlap, blurry textures, ugly UI and mechanical bugs. Use screenshot-based assessment plus engine-derived assertions.

Roblox announced its built-in Studio MCP server and start/stop playtests with simulated player input on March 5, 2026; this is the recommended first integration rather than inventing an unrestricted Roblox client.
https://devforum.roblox.com/t/assistant-updates-studio-built-in-mcp-server-and-playtest-automation/4474643 ;
https://github.com/Roblox/open-game-eval

## 4. General intelligence improvements that can be measured
**Knowledge ≠ reasoning ≠ autonomy.** More downloaded data does not automatically change model weights or generalize across games. Build a provenance-aware knowledge and skill system that can show concrete learning gains:
- Freeze a topic-diverse offline baseline: coding, math, everyday reasoning, game design, Roblox API semantics, visual layout, multimodal audio/video understanding, scientific QA and careful uncertainty.
- Store retrieval evidence with URL, author/license, fetched date, source version, claim, contradictory sources and a score indicating direct observation vs model deduction.
- Keep working-memory context small: short episode summaries, indexed successful and failed procedures, bounded temporal game state and task-specific retrieval. Long logs are searchable, not always injected into the prompt.
- Train/select new skills against **held-out** tasks and counterexamples, not the same prompts that taught them. Track contamination, false certainty, pass@1, generalization, and tool-completion reliability.
- Let the self-improvement system propose reversible patches, run offline tests, benchmark candidate improvements and open draft PRs with evidence; maintain owner control of main and no unapproved force-push or deployment.
- Use multi-sample candidate generation only for expensive problems where **independent verification** offsets the added compute cost. Measure marginal win-rate gain per second/joule.

## 5. Infrastructure + throughput on 8 GB GPUs
Do not equate "more parallel agents" with faster results when they contend for VRAM. Profile three regimes separately: idle, active game, and game+speech. STAR's previous QoS measurement modules should supply real timestamps to a paired controlled test.

| Candidate | Potential win | Common failure | Evidence gate |
| --- | --- | --- | --- |
| CPU Pocket TTS, 18M/7M | Free GPU headroom for game | Poor expression/pronunciation | Blind naturalness score + p95 first-audible latency + game 1% low FPS |
| llama.cpp n-gram or draft speculation | More decoded tokens per second | Extra VRAM and speculative overhead slow the game | Fixed seed, matched prompts, measured acceptance and end-to-end throughput |
| Cache-augmented context | Faster common tasks | Stale facts or prompt bloat | Versioned cache invalidation; cold vs warm paired tests |
| Quantization and CPU offload | Fit higher-quality target in hardware | RAM bandwidth stalls and unusable voice latency | Tokens/s, TTFT, p95 interactive latency under game load |
| Independent verification agents | Higher game-build/code correctness | Cost, contention, evaluator leakage | Held-out task pass@1 / success per compute unit |
| Bounded action & speech workers | Stable gameplay latency | Backlog and obsolete reactions | Queued-item age, deadline miss count, game frame p99 |

llama.cpp provides speculative-decoding variants and an official speed-bench client; speculation is **not** automatically faster. Compare a no-speculation baseline. 
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

## 6. Acceptance plan — before anyone claims Star is smarter or streaming naturally
1. **Offline (partially completed here):** 12 transport tests with a fake socket, invalid auth/response, token consent, 14 registrations, interrupted stages, stale/future/nonfinite frames, neutral release, reconnects and concurrent registration. Original VTS adapter remains independently tested in its parent PR.
2. **Windows owner-host smoke:** VTS installed and API toggled on; explicit plugin permission; correct Live2D model loaded; all 14 sliders manually mapped; 3-minute private rehearsal. Confirm no public stream or credentials emitted. Measure displayed animation offset against audible PCM.
3. **Stability:** 100 rapid interrupted speech turns, 1000 sampled frames, multiple disconnect/reconnect sequences, key-release independent watchdog for games, VTS token revoked mid-session; require no leaked old-turn animation and no infinite retries.
4. **Naturalness blind evaluation:** >=100 varied game sentences/interruptions/laughter lines; compare 100M/18M/7M CPU TTS with mixed excitement, irony, hesitation and pronunciation. Collect paired listener ratings; disclose AI nature.
5. **Real game learning:** 10 independent withheld games/levels with seed control, >3 repetitions per task; show measurable improvement over baseline, not self-graded victory.
6. **Inference promotion:** require statistically supported improvement in first-audible p95 or task outcomes with no gaming 1%-low-FPS regression, no new privacy leak, no higher hallucination rate.
7. **Release gate:** green full offline CI + local hardware tests + security review; **draft PR only**, owner merges to protected branch, reversible config and easy kill switch.

## 7. Explicitly not done
The linked PCs were **offline** during this run; therefore there was no actual VTube Studio socket or device, Windows screen/rig, Roblox playtest, live stream, TTS quality audition, or hardware inference benchmark. This code creates the host integration point and tests its protocol with a fake local transport only. The repository **Star-AI-Private was reported as public by GitHub** on 2026-10-26, so absolutely no owner audio, secrets, PII, game recordings or private data were uploaded.

The outcome worth pursuing is a Star who is faster, more expressive and demonstrably capable **by verified tests**, rather than claims of consciousness, superhuman mastery or unmeasured token-speed gains.
