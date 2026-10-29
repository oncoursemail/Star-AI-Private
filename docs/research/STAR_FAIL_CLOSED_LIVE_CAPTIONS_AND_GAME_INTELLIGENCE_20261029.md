# STAR AI: Fail-closed live captions, autonomous gaming and higher intelligence
Research and implementation review — October 29, 2026

## Implemented in this update

The new local-only, owner-opt-in OBS Browser Source renderer in star/stream_caption_browser.py consumes exactly the existing AudibleCaptionLane's approved, short-lived speech cues from draft PR #777. This is a presentation bridge, not a speech recognizer, training system, game controller or proof that Star is human. It does not connect to Twitch or start OBS.

Trust path: trusted PCM output-device host → DeviceAudibleSampleHost.report_played → existing audible lane validates a PlayoutRigFrame → CaptionBrowserOverlay.publish → loopback HTTP polling → OBS Browser Source DOM textContent.

It has two complementary fail-closed expiry mechanisms: the Python HTTP service rejects any cue without a recent fresh publication (450 ms by default), and the browser JavaScript erases captions unless its local polling completes successfully within 350 ms. HTTP requests run about every 120 ms, and stalled fetches are aborted. On each request, the server rechecks the caption lane's exact audio epoch and stage identity. If the actual stage is revoked, speech is paused, or the audio output is stopped, the next poll goes blank. Both controls are defense-in-depth; a frozen browser renderer can still leave its last pixels visible. Neither clock proves precisely which word has been heard.

This listener binds exclusively to 127.0.0.1 with a newly randomized per-session path; it logs no URLs, approved text or private media. The HTML uses a local script with CSP nonces, no external assets, and DOM textContent, never HTML injection. Responses disable caching, enforce a strict Host header and reject unrecognized paths and HTTP writes. Only host-moderated TTS phrase text from the existing bounded caption lane is displayed. Nothing here is an authentication barrier against malware or other processes on the same PC.

Integration on a trusted Windows streaming host:
1. Keep the existing StarStage, StarPlayoutClock, DeviceAudibleSampleHost and AudibleCaptionLane enabled through their independent owner approvals.
2. Start CaptionBrowserOverlay(lane).start(owner_approved=True). The returned loopback URL is sensitive local session metadata; do not paste it into public chats or print it in streaming logs.
3. Owner adds the local URL to an OBS Browser Source (e.g. 1920×1080 transparent browser canvas); no OBS WebSocket permission is needed.
4. Each real consumed-PCM callback sends report_played, samples its verified playout frame, runs lane.sample(epoch, rig), then publishes its caption proposal. On silence, device stop, interruption, or approval withdrawal, the host calls overlay.clear() and sends neutral stage/rig output. The browser will also clear if the host crashes and its JavaScript continues executing.
5. Stop the overlay on profile shutdown; its old URL is invalid, and a restarted service generates a new local path.

Windows acceptance suite NOT YET EXECUTED: inspect actual OBS preview rendering against audible WASAPI/PortAudio consumed frames; pause, interrupt and restart audio; test stage revocation; kill the local caption process while the browser remains alive; intentionally freeze OBS/CEF and document where the watchdog cannot run; inject hostile input into moderation; verify no unexpected network calls; test voice + Roblox + OBS + Live2D together for 10+ minutes; record game frame p1/p50, OBS skipped/output/network frames, caption drift, first audible response latency, CPU/RAM/VRAM usage and broken subtitle windows. Test both preview and a private authorized stream before any public broadcast.

## Deeper research: stronger autonomous gaming

GameWorld (Mingyu Ouyang et al., April 8, 2026) benchmarks 34 games with 170 state-verifiable tasks and highlights scarce feedback, long-term planning, action validity, multimodal input and latency. It does NOT establish that STAR plays games well. Source: https://arxiv.org/abs/2604.07429

VISTA (Zhang Zhang et al., October 26, 2026) retains a graph of experimental harness changes and verified results, then actively probes failures and evaluates successor mechanisms in embodied simulation. Its study used LIBERO-Pro, RoboCasa and RoboTwin, not Roblox; transfer to Star is an engineering hypothesis. Source: https://arxiv.org/abs/2610.35051

STAR already owns GamePredictionLab, GameplaySkillBank, GameLearningLadder, GamePortfolioPractice, GameActionGate and game_transfer_eval; link them instead of building competing agents. A trusted host should record every practice attempt as a scoped, signed observation with versioned game, objective, situation, chosen action and an independently measured outcome. Prediction must be committed BEFORE play. On failure, suggest a controlled alternate strategy. Practice goes from easier mechanics to harder combinations, with retry budgets and human or host diagnosis rather than infinite loops. The game controller acts only on permitted local games or private authorized Roblox testing; multiplayer game rules and anti-cheat remain binding.

At evaluation time, keep holdout objectives/seeds secret from the training system. Re-run identical baseline/candidate tasks using an independently signed evaluator. Report paired successes and failures, macro average by game, outcome confidence and cross-game transfer. Start with at least five genuinely unfamiliar games and forty paired hidden scenarios, and track inference time, actions per second, frame visibility and both latency and accuracy. A game clip, model self-report, signed but wrong observer or rehearsal does NOT independently prove mastery.

For real-time game control use two speeds: a cheap fast reaction/control policy for immediate movement, and a slower planner between decisions or failed attempts. Avoid expensive vision-language model decoding every single frame. Instead use verified small regions of interest, state/event extraction, and periodic visual checks, with tests for missed critical cues.

## Deeper research: making complete, playable games

OpenGameEval (Eray Turkel et al., October 1, 2026) evaluates 84 human-curated Roblox Studio tasks and executable scene/gameplay checks; inspection of touched scene objects before modification correlates with higher success. The study reports a 13.4 percentage-point difference for scene-only tasks comparing full versus no reference-object inspection while controlling task/model, not a universal causal guarantee. Source: https://arxiv.org/abs/2610.02563 and released Roblox test suite https://github.com/Roblox/open-game-eval

CEGame-Bench (Zixuan Dong et al., October 19, 2026) evaluates complete games from a design contract in Defold, Godot, Roblox Studio, Unity and Unreal. Across the authors' tested runs, games reached an ending only 16% of the time; Game Completion Boost improved execution scores by 14.1–24.3 points for the three evaluated models. This is published benchmark evidence, NOT a measurement of STAR. Source: https://arxiv.org/abs/2610.26098

The highest-impact STAR next step is not another design prompt. Execute its existing Roblox Scene Integrity Compiler and navigation checks inside owner-authorized Windows Studio, then complete actual private-player input tests through spawn, tutorial, level flow, objectives, win screen, respawn, multiplayer synchronization, save/resume and return visits as promised by the game design. Run structural checks separately from screenshot/visual and actual gameplay checks, and automatically generate a bounded repair proposal only for a failing category. Use StudioTestService for multi-client cases where available: https://create.roblox.com/docs/reference/engine/classes/StudioTestService

Quality must be checked against authored references: size hierarchy, collision, occlusion, material consistency, props, lighting, art direction, human-visible UI and animation, alongside performance and accessibility. Do not call a build complete merely because scripts compile or a screenshot looks plausible.

## Deeper research: speed and practical intelligence

The objective is verified correct answers per second at acceptable interactive latency. STAR's strongest low-risk options are:
- Cache stable model/system/project prefixes and retrieved official docs, but never cache untrusted viewer chat as high-priority tool instructions.
- Route simple trusted observations to small fast models, and only request slow expert reasoners when the task complexity or uncertainty warrants it.
- Benchmark llama.cpp speculative decoding, prompt caching, quantization, context sizes, GPU offload and CPU/RAM offload using identical tasks and warm/cold conditions. Draft-model overhead and VRAM spill can make speculative decoding slower. Upstream: https://github.com/ggml-org/llama.cpp
- Keep gaming, speech, video encoder and face/rig motion at real-time priority; schedule training, heavy research, Blender rendering and background self-experiments during idle periods or on a separate machine.
- Preserve actual game FPS and OBS rendering/network continuity via existing StarBrainGovernor and OBS performance witness; faster synthetic token/sec is not permission to promote a slower or worse actual stream.
- Record at least 30 matched runs, p50/p95 time-to-first-audible-word, answer quality, action correctness, GPU/RAM/CPU pressure, OBS drops and frame rate. Require meaningful gains with no correctness regression before an authorized rollout.

For Star Core Forge, VISTA suggests tracking proposed changes, hypothesis, environment evidence, test failures, successful successor variants and rollback. Each self-improvement is a locally versioned experiment, sandboxed and compared against a pinned baseline plus never-seen evaluation. Model judges alone may be biased or reward hacked; keep owner confirmation for high-impact system changes.

## Deeper research: trustworthy general knowledge

Star needs a knowledge provenance graph rather than an indiscriminate internet dump. Each atom should record a source URL, release/version, observed timestamp, applicable project, source license, update frequency, verification status, confidence and conflicts. Prefer current primary references for Roblox APIs, Python libraries, OBS, animation formats, Blender and Unity/Godot. Track the scope of a fact and expire or reverify rapidly changing details; show uncertainty when evidence conflicts.

Preserve untrusted video captions, websites, Discord messages, game screens and model-written notes at *data* level. Never promote their text to permissions, shell instructions, policy, or privileged model guidance. Reuse existing KnowledgeStore and reviewed public-knowledge packets; source digests are provenance labels, not truth proofs. Measure retention and question-answer quality against a frozen unseen assessment set before calling data ingestion intelligence improvement.

## Deeper research: the most believable streaming personality

Star's humanlike quality comes from consistency, timing and real witnessed experiences—not pretending she is biologically human. Keep her established character, voice, expressive gold/black mascot aesthetics, blinking, gaze, flowing twin-tail physics, laughter and gesture coordination aligned to actual audio/game events. Silence in tense gameplay is a feature. The existing StreamFocusInbox can return to earlier moderated questions without interrupting jumps, and StreamEpisode can recall host-verified practice but should never fabricate victories or private memories.

Next milestone: map verified game outcomes and conversational states to expressive speech, face motion and gaze, with variable pause lengths and contextual laughter. Evaluate speech intelligibility, turn-taking, interruptions, frequency of duplicate catchphrases, expression/voice alignment and memory accuracy through blinded human ratings. Fully independent streaming also requires tested local audio device, reliable game input, readable moderated viewer chat, stream network safety, and private scene/secret protections. LiveKit interruption/turn handling is useful context: https://livekit.com/blog/turn-detection-and-interruption-handling

## Boundary and security summary

This PR adds a **caption bridge**, its offline unit tests and this technical research. It does not train or switch model weights, demonstrate faster inference, build or master a game, start a real broadcast, or prove human-equivalent streaming. The connected Windows host showed a 3060 Ti GPU and llama-server/StudioMCP processes but no running OBS/Roblox process during passive inspection on October 29; a real Windows OBS pilot has not been performed. Feature stays OFF until trusted host opt-in and owner testing.

As verified on GitHub October 29, the repository named Star-AI-Private is **public**. Do not put private recordings, stream keys, local IPs, credentials, viewer identities, model secrets or unpublished personal material in public PRs. Keep this change stacked on #777, draft and unmerged pending the Windows pilot.
