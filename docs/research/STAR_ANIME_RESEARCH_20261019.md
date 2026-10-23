# Fast, high-quality original anime for Star AI

Research checked 19 October 2026 UTC. This is a production recommendation and development specification. No anime model was run, no dubbed performance was generated, and no episode-quality or speed claim was measured on Star during this research.

## The recommendation

Build a small, editable anime production pipeline around **original character designs, directed English performances, explicit shot timing, reusable sets, and selective AI assistance**. Give generative models bounded work: propose a board, animate between approved keys, transfer a staged performance, color a controlled sequence, or repair a particular shot. Preserve the approved result as an asset.

The first milestone should be a compelling 60-90 second scene with two characters, readable action, a quiet emotional turn, and a strong English performance. Expand into three connected short episodes after that scene survives an actual audience and production review. A continuous stream of newly generated material is a separate capacity target; it should not determine the artistic quality of the first scene.

The strongest technical experiments are ToonComposer for drawn-key control, SCAIL-2 for performance transfer, and LTX-2.5 for layout-conditioned work. These are hypotheses about fit, not a measured ranking. The baseline should be an editable OpenToonz/Blender shot, so AI must demonstrate an improvement in accepted output or correction effort. [R01-R12]

## 1. What the quality target means

For this project, define quality through observable creative results. A character has an objective, a relationship, and a reason to choose an action. The face and body communicate a change of thought. A viewer understands where the characters are and why an action succeeds or fails. Voices sound like people responding to each other. Costume construction, props, lighting, and the rules of the world stay coherent across cuts.

An attractive isolated frame is only one part of that target. A scene can look polished while its acting is generic, its joke has no setup, or its fight contains no understandable physical decision. Conversely, a deliberately held drawing can carry an excellent performance. The aim is a coherent episode that people want to continue watching.

Professional animator Naoki Yoshibe describes changing exposure within an action, including roughs on fours, passages on twos, and ones for a fast pass near the camera. His interview emphasizes spacing and rhythmic contrast. This is direct craft evidence for controlling timing instead of applying uniform smoothing. [R13]

### Delivery frames and drawing exposure

Use an exact 24 fps development timeline, subject to the eventual distributor's requirements. At this rate, a new drawing on every frame is animation on ones; holding each drawing for two frames is on twos; a three-frame exposure is on threes. The body, mouth, effects, and camera may have different exposures. A 24 fps master can contain held drawings while its camera or another layer continues moving.

Do not convert all footage to 60 fps as an automatic quality pass. Preserve authored holds, impact drawings, smears, quick direction changes, and intentional stillness. Generated inbetweens are candidates to accept, edit, or remove. Likewise, suppressing every unusual silhouette can erase deliberate exaggeration. Judge the sequence at normal speed, then inspect frames to diagnose an observed problem.

For action, plan a readable objective, anticipation, acceleration, contact, consequence, and recovery. The audience should be able to locate the danger before the camera becomes energetic. Use effects to reveal motion or weight; keep the decisive contact visible. For emotion, protect the breath, hesitation, eye movement, and listening response that carry the scene.

## 2. A production pipeline that can become faster

OpenToonz documents a workflow with timed scenes, palette-linked coloring, reusable libraries, and imported 3D renders. Its Xsheet records layer contents by frame. Blender's official materials describe Grease Pencil drawing in 3D space. Those capabilities support the following proposed division of work; they do not establish a working Star adapter. [R01-R04]

| Stage | Reviewable output | Decision before proceeding |
|---|---|---|
| Story and character intent | Short scene, objective, obstacle, change, continuity notes | Does the scene justify its duration? |
| Boards and scratch performance | Compositions, rough English acting, camera notes | Can viewers follow the action and emotional turn? |
| Animatic | Boards played with provisional sound and cut timing | Are pauses, reactions, and the payoff working? |
| Layout | Camera, set, scale, eyelines, prop positions, contacts | Will every department construct the same shot? |
| Final performance and keys | Chosen voice takes, decisive poses, exposure plan | Does the performance feel specific to this character? |
| Inbetween, cleanup, color | Controlled drawings or rig motion, palettes, mattes | Are volumes, identity, line hierarchy, and contacts sound? |
| Composite and sound | Layered final shot, separate dialogue/music/effects | Does the shot read and sound right in context? |
| Episode review | Current cut and a precise correction list | Is it worth watching, and what actually needs repair? |

Backgrounds, animation, props, and effects can proceed concurrently after their shared layout is settled. Launching them while the story and camera keep changing creates expensive rework. Keep work in progress bounded by the capacity to review and correct it.

### Build only the assets the pilot needs

Create an approved cast package: silhouette, height comparison, front/three-quarter/profile views, expressions, hands, mouth shapes, costume construction, color IDs, and a few approved examples of exaggeration. Add hidden-side and extreme-angle drawings when the actual shot list needs them. A single portrait leaves too many design decisions unresolved.

Create simple reusable 3D set geometry for camera geography and props. Finish the view with paint, line work, or a controlled model as appropriate. Keep the ability to alter a drawing for a stronger composition. A geometry scaffold supports continuity; it does not replace art direction.

Store continuity separately from appearance: which hand carries the parcel, whether a strap is fastened, what a character knows, which door is open, and where the light comes from. A retrieval prompt should supply the current state, not ask a model to invent it from the previous final frame.

### The minimum tool stack

Use **OpenToonz** for 2D levels, exposure sheets, palette work and compositing, and **Blender** for sets, cameras, props and optional Grease Pencil animation. Use a chosen audio/video editor for the final assembly and mix. Krita or Clip Studio can remain an artist's drawing preference without becoming a mandatory extra transfer step.

OpenToonz supports numbered image sequences and configurable previews; its documentation describes caching with invalidation when inputs change. Exchange rendered layers deliberately. A PNG sequence does not transfer an editable character rig, and Grease Pencil does not automatically become a real-time rig in another engine. Test a ten-frame interchange sample for alpha, color, frame numbering and dimensions before beginning the pilot. [R02-R03]

Moho 14.5, released 12 October 2026, is a targeted paid alternative for reusable performance and the live aftershow. The vendor documents webcam/gamepad control and editable recording of motion and audio. Its microphone mode is volume-driven, so it does not establish phoneme-aware dubbing. Evaluate it as an alternative to the relevant portion of the stack, not as another compulsory application. [R14]

## 3. Where the new AI tools fit

The rows below describe verified capabilities and author-reported limits. None is a demonstrated autonomous replacement for a complete anime studio, and no head-to-head test on Star's original characters has been run.

| Candidate | Useful experiment | Material limit |
|---|---|---|
| ToonComposer, ICLR 2026 | Colored reference plus artist sketches at selected frames; test a short gesture or action interval | Official example needs about 57 GB VRAM for 61 frames at 480p. Sparse control still needs line, hand and timing review. [R05-R06] |
| SCAIL-2, 2026 release | Transfer a staged performance, including character interactions, using matched references and masks | Multi-reference mode is experimental. The paper leaves accurate dialogue lip sync for future work. [R07-R08] |
| LTX-2.5 plus Layout to Render | Compare an owned 3D playblast and art-directed first frame with a conventional render of the same shot | Generative alignment needs review. The layout guide's ComfyUI route is silent; its Python route generates new audio. Preserve approved dialogue separately. [R09-R10] |
| Wan-Animate-2 Base / 10-step Distilled | Compare motion transfer with the same drivers used for SCAIL-2 | Published defaults use 8 A800 GPUs for 720p; 2 A800 at 480p was also tested. These are configurations, not universal minima. [R11] |
| AniSora V3.2 | Anime-specific reference and arbitrary-frame guidance comparison | Eight-step inference and anime specialization do not establish accepted production throughput; the guide uses 16 fps output. [R12] |
| ToonCrafter | Historical two-frame interpolation control | Released example supports up to 16 frames at 512 by 320. Its short-clip benchmark cannot be treated as episode throughput. [R15] |
| LayerInbetween | Research on editable vector inbetweens and occlusions | The recommended Depth Anything V2 Large dependency is noncommercial. The default commercial dependency stack remains unresolved. [R16-R17] |

Conform a model's output to the project timebase while preserving its intended duration. Merely interpreting 16 fps media as 24 fps makes it play 1.5 times faster and breaks the selected dub timing. Choose and review the frame mapping; do not silently change playback speed or invent intermediate drawings.

ToonComposer's actual license grants MIT terms for its code and weights and identifies the Wan dependency separately. LTX-2.5 has a community license with revenue and other conditions, rather than an unconditional MIT/Apache grant. Pin and review all model, adapter and dependency versions for the eventual deployment. [R06, R18]

### Distinguish a streaming paper from a shipped engine

Wan-Animate-2's separate Lite research configuration reports 24 fps at 400 by 720 using four GPUs and a causal pipeline. That result does not describe its public 10-step Distilled configuration, camera-to-screen latency, or an available live service. [R19]

FastH3 remains useful evidence about optimized generation, but MiniMax H3's current base license excludes the USA, EU, UK and South Korea from its standard territorial grant. It should not be selected as an immediately deployable US default without a separate grant. Other candidates allow the project to proceed. This is a material update to the earlier live-show research shortlist. [R20]

### Train only when a recurring failure justifies it

A show-specific adapter may be worth testing after the base pipeline works. Collect original approved views, poses, expressions, motion examples and explicit failure cases. Hold out difficult views and entire shots from training. Compare character recognition, costume construction, control response and correction time on the same held-out material. A style adapter can improve an appearance without learning acting or coherent fights.

Keep artist corrections and rejected outputs distinct. Automatically retraining on every generated clip can reinforce exactly the faults the production team is trying to remove. Research documents and prompt memories do not train model weights. Any later training claim needs dataset provenance, a training run, versions and a measured comparison.

## 4. Speed improvements worth engineering first

The following are proposed engineering priorities, not claimed measurements.

1. **Approve timing at low cost.** Review boards and scratch acting before final rendering. Keep proxy and final settings visibly separate.
2. **Use stable character and set assets.** Reuse designs, palettes, camera layouts, reusable actions and effects while making each performance specific.
3. **Keep audio and visual layers separable.** A changed take often affects the dialogue, alignment, mouth and some acting. It need not invalidate an unchanged background.
4. **Repair a bounded region.** Keep accepted work outside the edited interval. Recheck its boundaries, shadows, overlapping objects and temporal seams.
5. **Cache exact outputs.** Include asset hashes, frame range, model and adapter versions, renderer settings, color transform and audio dependency in the cache key. A seed alone cannot reproduce an accepted performance reliably across updates.
6. **Parallelize independent work.** Use separate workers for approved shots and independent layers. Do not assume more parallel requests will overcome a serial story decision, VRAM limit, provider quota or review queue.
7. **Measure cold and warm runs separately.** Loading, compilation, upload and output transfer can dominate a short job. A warm inference measurement cannot stand in for delivery time.
8. **Test acceleration against the final look.** Fewer denoising steps, lower precision, offloading, compilation, batching and preview resolution are configuration choices. Keep a change only if it improves time or cost after the required quality and repair effort are included.

Define dependencies explicitly. If a revised line changes duration, recalculate its mouth pass, acting beats and affected shot boundaries. If a pose changes, recheck contacts, occlusion and shadows. If the camera changes, rebuild the layout-dependent layers. Encode only after the current frame sequence and audio are complete; an encoder failure should not require generating the animation again.

## 5. Measure usable production speed

Use **accepted unique screen seconds divided by elapsed production seconds** as the main capacity measure. Also record artist/reviewer minutes, because parallel people or machines can reduce elapsed time while increasing cost. Count only the selected final timeline once: rejected takes, alternative takes, and duplicated frames in overlapping clips do not create additional story duration.

Keep four clocks: asset/setup time; generation time; job turnaround including queues and transfers; and scene turnaround including directing, corrections and review. Report median and tail latency with sample counts. A small pilot cannot establish a reliable 95th percentile or season-scale reliability.

Illustrative arithmetic: three workers, each producing 0.5 video seconds per wall second, with 50% of generated duration ultimately accepted, yield at most 0.75 accepted seconds per second before other bottlenecks. That cannot sustain continuous 1.0-times new programming. If the final scene takes an hour to produce, a 90-second scene represents 0.025-times production speed regardless of how fast the final file was encoded.

For live operation, let new-footage demand be d seconds per wall second and measured accepted supply be r. A ready buffer B drains in B / (d - r) seconds when d exceeds r, under a constant-rate assumption. A proposed 25% capacity margin is a planning target, not an observed capability. Measure burstiness and review delays before promising a live schedule.

## 6. Cost and hardware reality

Official LTX pricing checked for this report is shown below. The arithmetic assumes exactly 600 accepted final seconds and three billed take-equivalents per final second. A take-equivalent is billed duration divided by accepted duration; it is not simply an API request count. [R21]

| LTX-2.5 route | API price per second | 10 finished minutes at three take-equivalents |
|---|---:|---:|
| Fast 720p | $0.09 | $162 |
| Pro 720p | $0.12 | $216 |
| Fast 1080p | $0.13 | $234 |
| Pro 1080p | $0.17 | $306 |

These are generation-only scenarios. They exclude writing, designs, rigging, performances, review, editing, sound, storage, taxes and other tools. Minimum clip lengths, unused handles and repair billing can raise the effective cost. The same three-take assumption makes 22 minutes of Fast 720p generation $356.40. If only one fifth of those final seconds needs that generative route, its modeled share is $71.28; the remaining production still has its own costs.

For LTX text/image-to-video, the pricing basis is generated-video duration; for audio-to-video it is input-audio duration. Include silence and handles in the correct billable input measure. [R21]

The LTX pricing page currently lists hosted Retake as ltx-2-3-pro, billed by input-video duration. Do not assume a local 2.5 feature implies a hosted 2.5 endpoint, or that a two-second repair costs only two seconds. Its model guide also imposes clip-length and frame-rate constraints that a real adapter must enforce. [R21-R22]

For comparison, Google's direct Veo 3.1 page lists 720p Lite at $0.05 per second, Fast at $0.10, and Standard at $0.40. Runway lists Gen-4.5 at 12 credits per second, with credits priced at $0.01. These rates measure different services and capabilities; they are not a quality ranking. The pilot must decide whether an apparent saving survives retakes. [R23-R24]

Do not buy hardware based on a parameter count or a social-media demo. ToonComposer's published example is a high-memory workload. LTX's official local guide lists a 32 GB-plus VRAM baseline and higher recommendations. System RAM is not GPU VRAM. Quantization and offloading change the workload and need their own measured configuration. [R05, R25]

A practical budget sheet should separate setup costs from marginal episode costs: approved designs and rigs; per-shot work and revisions; model generation/GPU time; voice and music; editorial review; and delivery. Estimate each from the actual pilot logs, then produce another episode with reused assets to measure what reuse really saves.

## 7. What Star should implement next

The inspected Star main branch has Blender-to-Roblox recipe validation and related tooling; it does not establish a finished anime engine. The separate live-show draft PR provides an offline planning foundation. This research proposes the anime-specific work below without claiming it is already connected.

First, define a frame-based shot document, cast/asset package, and dub cue sheet. Next, verify one editable OpenToonz/Blender round trip and one voice-to-mouth workflow. Then implement a provider adapter for the best-performing bounded task, with explicit inputs, output files and costs. Add content-hashed caches and precise invalidation only after the real dependency boundaries have been observed.

Keep automated checks and creative decisions distinct. Software can verify frame count, missing files, mismatched versions, audio duration and some visual anomalies. An animator and intended viewers must judge acting, rhythm, emotional clarity and whether the next episode is wanted. Automatic approval records should identify the exact artifacts reviewed; a self-written label saying PASS is not independent evidence of quality.

The AniME research paper offers a useful precedent for a director coordinating specialized agents through an asset memory and dependency graph. It supports the architectural direction, but does not provide a measured guarantee of studio-quality episode throughput. Adopt the explicit artifacts and local revisions; do not treat adding more agents as a substitute for artistic judgment. [R39]

Stage expansion by results: approved performance test; finished micro-scene; three coherent short episodes; measured recurring-production schedule; then controlled live aftershows and longer anime episodes. At every stage, preserve the original source assets and measure corrections. The quality target remains ambitious, while each claim stays tied to a reviewable result.
