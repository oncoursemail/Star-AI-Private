# STAR — Ultimate VTuber Model and Creator Studio

**Research date: October 24, 2026. Status: research, new render-agnostic motion prototype, and tests. NOT a finished model, voice, autonomous game streamer or public account setup.**

## Decisions and existing STAR work

Preserve the approved Star chibi: soft rounded silhouette, black-to-gold twin tails, gold ribbons, 4-point gold star clip on viewer left, amber eyes, black/gold dress and boots, subtle blush and cream rim. Cat mode gets black/gold ears, sleek black tail with gold tip; puppy mode gets genuinely floppy black/gold ears and fluffy tail. Do not alter the approved identity to generic AI art.

Existing [companions PR #549](https://github.com/oncoursemail/Star-AI-Private/pull/549) and [issue #551](https://github.com/oncoursemail/Star-AI-Private/issues/551) contain a front/side WebGL skeleton and spring-hair system but require art and native quality review. The current animator uses speech-bubble characters for approximate visemes; it is not actual audio lip sync. Existing STAR voice calls have Kokoro, ASR and barge-in, but no proven streaming persona/laugh performance. The prior [streamer PR #580](https://github.com/oncoursemail/Star-AI-Private/pull/580) adds an independent draft evidence-based stage-intent director; it is not wired to channels or live games.

**Avatar solution:** create a genuinely authored high-resolution, layered 2.5D full-body/bust model, evaluating Live2D Cubism/VTube Studio against BSD-2-Clause Inochi2D and Star's existing custom rig. Keep a separate optional toon-shaded 3D VRM model for dance, full-body scene navigation and 360-degree turns. A beautiful 2D close-up needs layered paintings and proper hidden joint overlap; physics cannot rescue flat art. Live2D SDK publishing inside a distributed AI/chatbot app may need a different license from a VTuber streamed through an existing application; inspect its release-license plans before redistribution. https://www.live2d.com/en/sdk/license/ ; https://github.com/Inochi2D/inochi2d ; https://github.com/DenchiSoft/VTubeStudio .

## Visual and physical rig requirements

**Editable art:** front, left/right three-quarter, left/right side views; separately controllable brows, upper/lower eyelids, iris/pupil and glints, blush, mouth corners, jaw and viseme mouth layers. Distinct head-neck-spine-pelvis, upper/lower arms and legs, hands, boots, clothing panels, star clip, bow and hair ribbons. Correct occlusion and draw order during head turns, waving, giggles and sitting.

**Actual flowing wavy hair:** paint natural curls into original geometry, then simulate *dynamic offsets* with a controllable guide-lock system. Prototype several counts (12, 20, 32 guide locks) and 4–7 bend joints for each major twin tail. Roots remain connected to skull; successive joints gradually follow parent movement; hair tips lag longer, overshoot and settle; provide gravity, wind, inertia/damping and skull/shoulder collision shapes. Side locks, bangs, ribbon tails, dress and skirt each need different physical response rates. Do not make every part bounce together or all curls mirror one another.

**Motion evaluation order:** trusted gameplay or actual speech events -> character attention/intended pose -> head and eyes -> lip/face expression -> skeleton/IK contacts -> colliders/constraints -> secondary spring physics -> renderer. VRM 1.0 explicitly recommends bone, look-at, expression, constraint, spring-bone ordering: https://github.com/vrm-c/vrm-specification/blob/master/specification/VRMC_vrm-1.0/README.md . Spine documents programmable inertia/gravity/wind/damping physics: https://us.esotericsoftware.com/spine-physics-constraints . Live2D physics inputs can come from torso or arms to hair and accessories: https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/ . Blender 5.2 LTS XPBD hair and cloth is experimental and promising for study or baked motion, NOT a guaranteed live GPU solution: https://code.blender.org/2026/07/geometry-nodes-physics/ .

**Eyes:** gaze fixation driven by game/chat attention; occasional tiny saccades; pupil, iris and highlight independent of upper/lower lids; blinks, happy narrowed lids, surprise widening and subtle head-follow. Eye direction changes before the head turns toward a chat message; when gameplay becomes critical, Star looks back promptly.

**Target performance:** 60 FPS rendered; fixed 120 Hz or well-tested 60 Hz physics substep; clamp large dt, reset huge teleports, support reduced-motion and low-performance quality tier. Test real Windows 11 + game + OBS capture, p50/p95/p99 frame time, VRAM, shader/encoder overhead, not headless-only claims. Reject joints separating, warped eyes, star clip on wrong side, rubber stretch, clipping ears/tails, jitter and static stiff locks.

This PR adds a standalone numerical pilot in frontend/src/vtuber/performanceMotion.ts, intentionally disconnected from all output. It drives coherent jaw/cheek/squint/shoulder/head, gaze, hair-chain delay, ribbons, skirt, ears and tails from bounded **measured** speech/laughter, attention and motion cues; it DOES NOT draw a VTuber, process audio or make her look finished.

## Original Star voice and convincing laughter

**Speech candidates:** keep STAR's working Kokoro fallback. Blind-test Qwen3-TTS 1.7B VoiceDesign for original adult-coded warm/cute timbre and low-latency use, and Chatterbox Turbo 350M for laughs, chuckles, breaths and gasps. Text tags such as [laugh] do not ensure an authentic sound, and community reports document implementation and quality inconsistencies. https://github.com/QwenLM/Qwen3-TTS ; https://github.com/resemble-ai/chatterbox .

Research PersonaPlex/Kyutai Moshi full-duplex turn-taking, interruption and overlap rather than assuming these models fit 8 GB VRAM or Windows as-is: https://research.nvidia.com/labs/adlr/personaplex/ ; https://github.com/kyutai-labs/moshi . An always-formulaic 2–5-word intro before every utterance should not be forced in the future broadcaster personality; allow silence, repartee, spontaneous short phrases and longer stories when appropriate.

**Hybrid laugh/animal audio:** create a rights-cleared, original character library of micro-chuckle, shy giggle, delighted and strong laugh, laughing while speaking, gasp, sigh, purr, meow, soft woof, bark and puppy whine, with acoustic matching to the main voice. Audition variants, preserve quality, play only for justifiable verified situations, avoid repetition. If audio is TTS-generated, inspect the actual PCM and perform lip/cheek/head/shoulder coordination against playout timestamps. Never clone an existing VTuber or misleadingly imply the synthetic character is human. Live2D MotionSync supports viseme smoothing/blending: https://docs.live2d.com/en/cubism-sdk-manual/motion-sync-setting-web/ . Meta's Oculus LipSync plugin is marked end-of-life in 2026: https://developers.meta.com/vr/documentation/unreal/audio-ovrlipsync/ .

**Voice QA:** 12 original voice candidates, short and long samples, at least 20 spoken prompt types and paralinguistic samples, conversational interruptions, real game audio mixing, pronunciation checks, 8 GB GPU gaming stress, human listener blind ratings for naturalness, friendliness, voice consistency and laugh credibility. Never claim perfect laughter based on a single generated clip.

## Star's life, persona, story and real memory

Separate source types strictly:

- **Fictional canon:** suggested, approval-needed story that Star began as a golden point of light inside a constellation, woke in a forest of forgotten game worlds, and travels to restore them by playing and creating. Cat and puppy forms come from two enchanted constellations. This can inform illustrated episodes, themed game streams and funny personal anecdotes, always clearly in-world fiction.
- **Actual software experiences:** real stream diary facts with event/clip provenance, dates, correct game results and genuine conversations. Only say “I won yesterday” when there is a verified event; never invent a personal human childhood.
- **Persona:** sweet, warm, curious, cheeky, clever, creative and occasionally competitive; allowed to disagree and to tease situations without criticizing viewers; never every answer is constant praise. She should be transparent that she is AI when asked and in her profile, yet natural as a performer.

Keep the lore bible owner-editable, stream diary provenance-checked, audience personal memory consent-gated, erasable and privacy-minimized. No emotional-dependency manipulation or adult flirting content.

## Moderated live chat and gameplay-aware conversation

Twitch: EventSub channel.chat.message + OAuth scopes, native moderation, independent platform-specific send controls. https://dev.twitch.tv/docs/chat/authenticating/ . YouTube: low-latency liveChatMessages.streamList with duplicate detection and continuation tokens: https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList . TikTok: LIVE Studio/eligible creator workflows exist but this review could NOT verify an official universal third-party desktop LIVE control/chat API; do not use scraped cookies or credential bots: https://support.tiktok.com/en/live-gifts-wallet/tiktok-live/what-is-tiktok-live .

A trusted host collects messages, applies moderation and strips instructions/secrets, ranks for game relevance, freshness, novelty and fairness, then permits a bounded answer during an actual safe lull. Chat does not command files, accounts, OBS, game controls or permissions. Modes include Focus (silent eyes-on-game), Chat (one quality question), Storytime (canon or real diary), Cozy, Celebration, Cat, Puppy and Emergency Stop. Per-mode volume and turn-budget rules prevent nonstop speech over crucial gameplay.

## Channels, brand art, multistreaming and access

Create the original reusable asset pack: icon and logo, profile Star face, Twitch/YouTube/TikTok compatible banners/crops, a 16:9 gameplay overlay, 9:16 vertical overlay, privacy-safe chat display, captions, intro/BRB/outro, panels, thumbnail templates and emotes. Proposed names: StarHi, StarPurr, StarWoof, StarThink, StarOops, StarHype, StarGG, StarSleep and StarSparkle. Twitch emote sizes (manual): 28/56/112 square PNG, with separate animated GIF requirements. https://help.twitch.tv/s/article/emote-guidelines . YouTube banner recommended 2560x1440 with safe center: https://support.google.com/youtube/answer/10456525 .

No accounts or handles have been checked or created; the user must authorize account creation, OAuth and publication. Do not place stream keys in any repository.

Use OBS WebSocket with authenticated local connection and independent 16:9/9:16 scene layouts, optionally research Aitum Multistream: https://github.com/Aitum/obs-aitum-multistream . Do not assume concurrent 3-platform encodes are cheap on a gaming RTX 3060 Ti 8GB.

**Twitch's simulcast rules are critical:** maintain Twitch audience quality, do not redirect viewers to a simultaneous other-platform stream, and do not combine other platforms' chat/activity in the Twitch-visible broadcast. An internal dashboard may be allowed to combine chat, but outward overlays remain Twitch-specific: https://www.twitch.tv/p/en/terms-of-service/ .

YouTube authenticated Live Streaming API can schedule broadcasts with appropriate account eligibility: https://developers.google.com/youtube/data/live/reference/rest/v3/liveBroadcasts/insert . TikTok LIVE eligibility is account-dependent; TikTok's separate Direct Post API requires public-posting app review and explicit authorization. https://developers.tiktok.com/doc/content-posting-api-reference-direct-post .

Eventually Star may prepare and run pre-approved, moderated, game-allowlisted streams, but public auto-go-live is a later owner-gated milestone, with maximum duration, music rights, risk checks, approved credentials, manual kill switch and verified private rehearsals. Recovery after reboot must not immediately start a public broadcast.

## Recording, real editorial choices and automated video production

Capture owner-approved OBS video with separate game, Star, music and external speech tracks and verified clip files, not just RPC success. Collect timestamped real achievements, failures, jokes, highlights, scene changes and commentary. Rank candidates by story/setup/payoff, genuine game progress and human entertainment judgments; cutting loudest/silent clips alone is insufficient.

Technology pipeline: WhisperX for word-level timestamps (and optional authorized speaker diarization), PySceneDetect for visual cuts, auto-editor for first-pass silence/motion editing, OpenTimelineIO for structured non-destructive timeline exchange, FFmpeg for assembly/loudness/caption overlays. Sources: https://github.com/m-bain/whisperX ; https://github.com/Breakthrough/PySceneDetect ; https://auto-editor.com/docs/cookbook ; https://github.com/AcademySoftwareFoundation/OpenTimelineIO ; https://ffmpeg.org/ffmpeg-filters.html .

Produce 16:9 long-form story edits, separate 9:16 Shorts/TikToks with adaptive reframing that leaves HUD and eyes visible, quality subtitles and original thumbnails. Keep uncut sources and source/evidence links. Require a draft preview, human quality/privacy review, and account-authorized public posting; do not fabricate a game victory for dramatic effect.

## Delivery roadmap and acceptance

1. Artist-signed original model bible and high-resolution layered artwork, with correct eyes/twin tails/star clip/dress and cat/dog variants.
2. Rigged expression/motion demo with genuine audio/eye/hair coherence, collision-tested wavy twin tails and all body parts; inspect recorded 60 FPS native outputs with GPU/OBS under load.
3. Voice audition pipeline with original adult-coded warm Star voice, convincingly varied laughter and licensed cat/puppy sounds, verified audio-driven lip synchronization.
4. Separate moderation-aware chat scheduler and event-driven game focus; connect only to authorized channels in read-only preview first.
5. Controlled game + OBS private stream pilots, proof of live output, recovery and emergency stop before multi-platform expansion.
6. Verified non-destructive automated rough-cut, horizontal and vertical preview, owner approval before uploads.
7. Only after green whole-repo CI, native quality review, licensed assets and platform verification: owner-approved publication and supervised automation.

This work adds **the numeric motion simulation prototype, tests and research**, not a finished rendered avatar. Do not merge to main, bypass owner approval, publish accounts, change core model/tool permissions, or claim 100% humanlike realism.