# STAR 2.1 Streamer — Research and measured integration plan

**October 24, 2026. Status: new OFFLINE implementation, research and tests; not a deployed streamer, game-playing system or trained voice.**

## Decision

Build STAR as several independently tested systems rather than a large LLM doing every task on an 8 GB GPU. STAR already has a voice pipeline, approved original chibi designs, an in-progress companion animation system, Roblox Studio robot playtesting, video analysis and opt-in OBS replay support. Preserve those foundations. Extend with real event provenance, a bounded conversation/stage director, a vision-to-controls pilot, a separate gameplay learning curriculum and creator platform connectors only after permission gates.

User outcome: Star should be a recognizably original, cute, clear-voiced, thoughtful and funny AI streamer who can actually play and learn games. Make her relatable through timely reactions and reproducible progress, not a copied celebrity voice, fabricated events or claims to be a biological human. Universal likability, human-level gameplay and perfect speech cannot be guaranteed and must not be claimed.

## New technical findings

### Natural dialogue and the original voice

- NVIDIA PersonaPlex (January 2026) is a full-duplex speech conversation design with both voice conditioning and text personas. Source/code/weights have separate licenses. Focus on its turn-taking approach, not instant replacement of the existing STAR voice pipeline: https://research.nvidia.com/labs/adlr/personaplex/
- Kyutai's June 2026 post-training experiments target backchannel timing, interruption and pauses, not merely voice pitch or quality: https://kyutai.org/blog/2026-06-10-interactivity/
- Moshi is a useful open full-duplex reference; the official README warns that the standard PyTorch implementation may require about 24 GB VRAM and lacks official Windows support. The code and model weights have different licenses. Do not assume it works on an 8 GB gaming GPU: https://github.com/kyutai-labs/moshi
- Qwen3-TTS offers original description-driven voice design, streaming, and 0.6B/1.7B checkpoints, with Apache-2.0 release terms according to its maintainers. Verify checkpoint/runtime memory and voice rights before adding an engine: https://github.com/QwenLM/Qwen3-TTS and https://arxiv.org/abs/2601.15621
- Chatterbox Turbo publishes 350M-parameter expressive voice-agent research and laugh/chuckle/cough tags. Compare on the same prompts, not vendor examples: https://www.resemble.ai/products/text-to-speech
- Preserve Kokoro-82M and STAR's current ASR/turn detector as the lighter fallback. The selection target is not solely low time-to-first-byte: aim for intelligibility, character fit, comfortable sustained listening, smooth barge-in, controlled humor and independent game-frame-time stability.

**Audition acceptance:** test 12 synthetic-original candidate voices, 20 consistent prompts including quiet and intense gameplay, 3-minute long-form samples, barge-in, false interruptions, Roblox/Luau vocabulary and real Windows gaming+OBS load. Use blind listening judgments and timing metrics. No unsanctioned cloning or imitation of Neuro-sama, Kizuna AI or human streamers.

### Gameplay and learning

- Google DeepMind SIMA 2 (November 2025) is research on instruction-following, reasoning and interaction in virtual 3D worlds; not a drop-in public general-purpose game controller: https://deepmind.google/blog/sima-2-an-agent-that-plays-reasons-and-learns-with-you-in-virtual-3d-worlds/
- Voyager keeps modular executable Minecraft skills, uses an automatic curriculum and self-verifies environment feedback; valuable inspiration for skills that transfer beyond one session: https://arxiv.org/abs/2305.16291
- DreamerV3 uses a learned world model for imagined futures, but the Minecraft achievement is the outcome of serious reinforcement learning, not a tiny instant update on the streaming PC: https://www.nature.com/articles/s41586-025-08744-2
- NitroGen, CVPR 2026, trains on about 40,000 hours across 1,000+ games and maps RGB frames to gamepad actions. Fine-tuning transfer improvements reported in the paper are not general human-level control; published model governing terms are noncommercial research. Do not put that checkpoint in a monetized stream without rights review: https://openaccess.thecvf.com/content/CVPR2026/html/Magne_NitroGen_An_Open_Foundation_Model_for_Generalist_Gaming_Agents_CVPR_2026_paper.html and https://huggingface.co/nvidia/NitroGen
- Genie 3 is research toward interactive world-model environments, not a locally installable replacement for Roblox or a reliable general-purpose physics oracle: https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/

**First real experiment:** use one owner-controlled, reproducible small game; freeze a holdout suite; record permitted screen pixels, actions, frames, seeds, deaths, progress and exact build versions. Separate a fast reflex controller from a slower reasoning model. Always keep the visual controller focused on its own authorized game window. Evaluate against no-learning and simple-script baselines, then measure true performance transfer in an unseen game. Roblox's public rules prohibit cheats, exploits and disruptive bots: https://en.help.roblox.com/hc/en-us/articles/203313410-Roblox-Community-Standards

### Stream platforms and creator experience

- Project AIRI is a useful self-hosted reference for real-time voice, Minecraft, Factorio and avatars; some modules remain works in progress. Avoid copying it into STAR or treating a demo as a finished feature: https://github.com/moeru-ai/airi
- The University of Pennsylvania's February 2026 study of 15 months of Neuro-sama content analyzes transparency, emotional performance and an evolving character in perceived authenticity. Learn from audience interaction; do not copy or misrepresent the creator: https://www.asc.upenn.edu/news-events/news/what-makes-ai-livestreamer-seem-real
- Twitch recommends EventSub WebSockets for locally installed chat clients with the correct OAuth scopes. Apply AutoMod and identity boundaries; chat text never becomes a STAR command or credential: https://dev.twitch.tv/docs/chat/authenticating and https://dev.twitch.tv/docs/chat/moderation
- YouTube recommends liveChatMessages.streamList for pushed chat updates instead of aggressive polling; handle deduplication, stream resumes and moderation: https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList
- OBS 28+ includes WebSocket v5. Keep loopback/auth and verify a saved file actually exists and is decodable; an RPC acknowledgement proves only request acceptance: https://github.com/obsproject/obs-websocket
- The Live2D SDK release-license rules distinguish VTuber, AI/chatbot and distributed software uses. Existing STAR layered companion work should be tested before choosing Live2D or Inochi2D, and no rig can be called production quality without actual source layers, lip sync, art review and native rendering proof: https://www.live2d.com/en/sdk/license/

## What this PR actually adds

### star/streamer_director.py

A pure-Python event and stage-intent arbiter, intentionally disabled by default:

- A future trusted owner UI must explicitly confirm enablement.
- Known game, owner and moderated-chat events have typed source tags, opaque evidence IDs and age limits.
- Repeated IDs, stale events, unmoderated chat, unknown sources and malformed evidence are rejected.
- The queue is bounded at 48 items with low-priority drop behavior and a 256-ID dedupe window.
- A speaking/game-focus guard prevents nonessential chatter from harming gameplay; global and per-event cooldowns avoid repetitive reactions.
- Outputs only a StageCue: speaking *intent*, facial expression, animation, priority and evidence. No generated dialogue, chat text, input, file writes, model calls or external broadcasts.
- The local owner_stop cue immediately disables and clears queues; an external host must implement its own safe stop behavior.

Important security detail: the source field is NOT authentication. Future adapters must be code-owned, preauthorized and independent of all model or viewer text. Model-generated content must never call set_enabled or author verified-game event instances directly.

### star/streamer_skill_eval.py

A pure-Python evaluation of two policies on paired untouched task/seed holdout results:

- Requires 20+ matched trials across 3+ different tasks.
- Requires separately referenced evidence artifacts and rejects duplicate/missing or non-holdout entries.
- Computes baseline/candidate success rates, gained/lost trials, exact paired McNemar p-value and safety-violation totals.
- Returns a recommendation for **independent human review only** if both practical and statistical improvements are present and recorded safety does not regress.

The caller must validate that game recordings truly exist, outcomes are genuine and holdout tasks were not used for training. No test in this PR proves STAR played a real game, and no code trains weights, automatically promotes a skill, merges PRs or starts a public stream.

### Offline smoke example

~~~python
from star.streamer_director import StreamerDirector, StreamEvent

director = StreamerDirector()  # OFF by default
# Test-only human-approved session. Do not expose this method as an agent tool.
director.set_enabled(True, owner_confirmed=True)
director.ingest(
    StreamEvent("demo-1", "game_win", "verified_game", 1000, "synthetic-proof-1"),
    now_ms=1000,
)
cue = director.next_cue(now_ms=1000)
assert cue is not None and cue.intent == "celebrate_verified_win"
# Synthetic proof does not establish an actual game victory.
~~~

Tests: pytest -q tests/test_streamer_director.py tests/test_streamer_skill_eval.py; python -m compileall -q star/streamer_director.py star/streamer_skill_eval.py. Local isolated tests passed before submission; full installed Windows release and entire repo CI still require independent execution.

## Implementation backlog and honest acceptance gates

1. **Connect a verified local game adapter.** Develop on a disposable, original test game and measure event provenance; no arbitrary platform game automation. Rejected spoofed wins and secure stop behavior must be tested.
2. **Wire a read-only review screen.** Present StageCue, real observed event and intended expression in STAR Desktop. Leave voice, game input, OBS and platform tokens disconnected until reviewed.
3. **Build a measured voice audition tool.** Integrate candidate TTS engines separately and show naturalness scores, first audio latency, p95, interruptions, VRAM, voice comfort and original voice ownership.
4. **Integrate real layered animation.** Work alongside current companion PR #549; do not replace approved STAR visuals or bypass owner clip review. Lip-sync actual phonemes/audio.
5. **Run game-playing benchmarks.** Screen-to-action loop on a permitted offline game, with actual control observations, checkpoint screenshots and untouched holdout tasks. Compare baselines before trusting any learned policy.
6. **Private streamer rehearsal.** Confirm OBS capture, real audio and animation, moderator gating, disconnect/kill switch, privacy redaction and safe recovery. Power recovery must leave public broadcasts OFF.
7. **Only then propose public Twitch/YouTube.** OAuth with minimum permissions, content moderation, stream platform rules, and explicit human approval of publication. No unattended broadcasts, uploads or AI-driven permission changes.

## Original research experiments (hypotheses, not proven innovations)

- **ShadowCoach:** train a small predictor to imitate authorized demonstrations and focus improvement on prediction errors, not massive unsupervised video scraping.
- **Counterfactual Replay Surgery:** replay resettable failures with one changed decision to identify actual causal mechanics, without changing evaluation labels.
- **Skill DNA:** test transfer of abstract timing, momentum, aiming and collision skills to an entirely new test game without prior access to holdout tasks.
- **Opportunity-based speech:** decide when speaking improves the viewing experience and when silence preserves difficult gameplay; learn timing from voluntary human listening ratings, not manipulative retention metrics.
- **STAR vs Yesterday:** produce reproducible gaming challenge comparisons showing both wins and losses; performance is more interesting when it is honest.

**Boundary:** This draft PR is real research plus two new offline code modules and unit tests. It is not the finished AI streamer, universal game-playing agent, custom voice model, live avatar or public broadcast. Those remain substantial engineering tasks.
