# Sources, evidence and implementation status

## Scope and method

Research checked 19 October 2026 UTC. The work covered animation craft and production tools, controllable video models, English performance and localization, lip sync, audio mixing, published hardware/price evidence, and Star's existing implementation boundaries. Sources below are first-party documentation, author repositories/papers, official releases or a first-person professional interview.

Product descriptions establish documented features and current limitations; vendor speed figures remain vendor results. Research papers establish the authors' reported experiments, not an independently reproduced Star result. Proposed architecture, pilot content, quality targets, comparison procedures and illustrative arithmetic are labeled as our design. No inference, training, voice audition, rendering or audience experiment was conducted during this research.

Blender's story-artist evidence was verified through its official search-index entry; direct retrieval returned a fetch error. No full talk, current add-on compatibility or Blender performance was inferred from that index. Other references were read directly through official pages or repositories. Volatile versions, endpoints, prices and license terms should be rechecked when an actual provider configuration is selected.

## Source register

- R01. OpenToonz, Production Workflow. Timed scenes, palette-linked colors and reusable libraries; documentation labeled 1.7.1. https://opentoonz.readthedocs.io/en/latest/production_workflow.html
- R02. OpenToonz, Working in Xsheet/Timeline. Per-frame layer timing and numbered sequence import. https://opentoonz.readthedocs.io/en/latest/working_in_xsheet.html
- R03. OpenToonz, Previewing and Rendering. Proxy settings, caching and rendering options. https://opentoonz.readthedocs.io/en/latest/rendering_the_animation.html
- R04. Blender, Story Artist. Official indexed description of Grease Pencil drawing in 3D; direct page fetch unavailable in this session. https://www.blender.org/features/story-artist/
- R05. TencentARC, ToonComposer official repository. Artist-keyed animation and published 480p memory example; ICLR 2026 project. https://github.com/TencentARC/ToonComposer
- R06. TencentARC, ToonComposer LICENSE. Actual code/weight grant and Wan dependency terms. https://github.com/TencentARC/ToonComposer/blob/main/LICENSE
- R07. Z.ai, SCAIL-2 official repository. Current controls, masks, resolutions and experimental multi-reference limits. https://github.com/zai-org/SCAIL-2
- R08. SCAIL-2 paper, version 3. Reported experiments and limitations, including future work on accurate dialogue synchronization. https://arxiv.org/html/2606.10804v3
- R09. Lightricks, LTX-2 official repository. Current LTX-2.5 recommendation and local workflow families. https://github.com/Lightricks/LTX-2
- R10. LTX, Layout to Render. Playblast-conditioned workflow, review limits and distinct audio behavior by route. https://docs.ltx.io/open-source-model/vfx-post-production/layout-to-render
- R11. Wan-Video, Wan-Animate-2 official repository. Base/Distilled public implementation and tested hardware configurations. https://github.com/Wan-Video/Wan-Animate-2
- R12. Bilibili, AniSora V3.2 inference guide. Eight-step configuration, arbitrary-frame input and 16 fps example. https://github.com/bilibili/Index-anisora/blob/main/anisoraV3.2/README.md
- R13. Celsys, Naoki Yoshibe interview, advanced animation lesson. First-person explanation of exposure and motion contrast. https://tips.clip-studio.com/en-us/articles/1293
- R14. Lost Marble, Moho 14.5 SHOWTIME release, 12 October 2026. Live character performance, recording and platform details. https://moho.lostmarble.com/blogs/news/moho-14-5-showtime-design-rig-and-animate-characters-live-all-the-power-of-moho-now-live
- R15. ToonCrafter official repository. Short cartoon interpolation baseline and released output constraints. https://github.com/Doubiiu/ToonCrafter
- R16. LayerInbetween official repository, SIGGRAPH 2026. Editable vector workflow and required dependencies. https://github.com/MarkMoHR/LayerInbetween
- R17. Depth Anything V2 Large official model card. Noncommercial terms for the recommended Large checkpoint. https://huggingface.co/depth-anything/Depth-Anything-V2-Large
- R18. Lightricks, LTX-2.5 model card. Current model-family description and community-license conditions. https://huggingface.co/Lightricks/LTX-2.5
- R19. Wan-Animate-2 paper, version 2. Separate Lite research configuration and streaming throughput. https://arxiv.org/html/2608.06009v2
- R20. MiniMax H3 base-model LICENSE. Territorial grant and exclusions; license dated 2 August 2026. https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE
- R21. LTX API Pricing. Current generation, audio-to-video, Retake and extension billing bases. https://docs.ltx.io/pricing
- R22. LTX-2.5 API model guide. Supported duration, resolution and frame-rate combinations. https://docs.ltx.io/models/ltx-2-5
- R23. Google, Gemini Developer API pricing. Direct Veo 3.1 rates and billing notes. https://ai.google.dev/gemini-api/docs/pricing
- R24. Runway, API Pricing and Costs. Credit price and current model rates. https://docs.dev.runwayml.com/guides/pricing/
- R25. LTX, System Requirements. Local hardware requirements and recommended configurations. https://docs.ltx.io/open-source-model/getting-started/system-requirements/
- R26. Netflix, Dubbing Creative Guidelines - Animation & Anime. Intent, acting, breaths and key synchronization moments. https://partnerhelp.netflixstudios.com/hc/en-us/articles/10258372720147-Dubbing-Creative-Guidelines-Animation-Anime
- R27. Netflix, Mixing Style Guide for Dubbed Content. Scene perspective, environment and creative mix continuity. https://partnerhelp.netflixstudios.com/hc/en-us/articles/360017944573-Netflix-Mixing-Style-Guide-For-Dubbed-Content
- R28. Netflix, Dubbing Premix Recording and Delivery Guidelines. Synced clean dialogue and master-project alignment. https://partnerhelp.netflixstudios.com/hc/en-us/articles/360001582228-Dubbing-Premix-Recording-and-Delivery-Guidelines
- R29. ElevenLabs, Models. Current v4/v4 Turbo and voice-model families. https://elevenlabs.io/docs/overview/models
- R30. ElevenLabs, Voice Changer. Performance conversion and the recommended speech-to-speech model. https://elevenlabs.io/docs/overview/capabilities/voice-changer
- R31. Cartesia, Sonic 3.6. Stable dated model snapshots and current language/model behavior. https://docs.cartesia.ai/build-with-cartesia/tts-models/latest
- R32. Cartesia, Volume, Speed and Emotion. Guidance controls and emotion limitations. https://docs.cartesia.ai/build-with-cartesia/capability-guides/volume-speed-emotion
- R33. Resemble, Chatterbox official repository. Nano and other current voice variants, licensing and author speed claims. https://github.com/resemble-ai/chatterbox
- R34. Resemble, DramaBox official repository. Expressive speech, hardware notes, model license and optional denoiser caveat. https://github.com/resemble-ai/DramaBox
- R35. ElevenLabs, Dubbing. v2 Alpha, legacy Studio status, editing access and production-output limitations. https://elevenlabs.io/docs/overview/capabilities/dubbing
- R36. LTX, Dub-It Beta. Replacement dialogue, single-speaker limits and version-specific instructions. https://docs.ltx.io/open-source-model/feature-guides/audio/dub-it-beta
- R37. Rhubarb Lip Sync official repository. Recorded-audio analysis, 2D mouth cues and supported interchange. https://github.com/DanielSWolf/rhubarb-lip-sync
- R38. ElevenLabs, Stream Speech with Timing. Character-level alignment output. https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps
- R39. AniME paper, version 3, SIGGRAPH Asia 2025 Posters. Director, specialized agents and asset-memory architecture. https://arxiv.org/html/2508.18781v3
- R40. VBench-2.0 paper. Multiple dimensions of video-generation evaluation; not an anime audience-quality certificate. https://arxiv.org/abs/2503.21755

## Material update to the earlier live-show research

The earlier Star live-show dossier considered the Reactor/FastH3 prototype as a research candidate. Its code availability must be separated from rights to the underlying MiniMax H3 weights. The current base-model license excludes the USA, EU, UK and South Korea from its standard grant. Therefore, this report removes H3-based routes from the ready default shortlist for those deployments without a separate grant. The previously reported timing and continuity limitations are not changed by this licensing finding. [R20]

The new research continues to favor persistent assets, buffered finished episodes, and a constrained live character stage. It adds stronger candidates for anime-specific key control, motion transfer, layout conditioning and English performance. It does not establish an end-to-end autonomous animation service.

## Reviewable Star package

This package adds four research documents (this folder), three example files in `examples/anime_production/`, and one small consumer. The documents describe the proposed pipeline, English performance workflow, original pilot, comparison method and sources. The examples contain a 90-second frame plan, fourteen planned dialogue cues, a matching CSV cue sheet and an empty benchmark record template.

The consumer is `star/anime_production.py`, reachable as `star anime-check <file>` or `python -m star.anime_production <file>`. It checks the pilot plan (contiguous half-open shot ranges ending at `total_frames`, known characters, cue windows inside their cuts, no character speaking over themselves, no selected take or audio hash on an unproduced plan), the cue sheet (exact columns and, with `--plan pilot.json`, agreement with the plan) and the benchmark record (bounded take and route limits; a `not_run` record holds no runs or summary). These are structural checks of planning material, not rendered-media or audience tests. The schema is development material and is not the schema of `star/live_show.py`. No provider adapter exists; nothing here generates animation, synthesizes speech, opens a paid service or starts a broadcast. The tool reads only the local files you name. The documents' rights notes (use only material and voices you own or are licensed to use) are guidance; the validator does not enforce them.

The inspected private source base was main commit 0d7bfdb838435221ab60ecd83687e896d34b568e. The existing live-show work remains in separate draft PR 492: https://github.com/oncoursemail/Star-AI-Private/pull/492 . Main was inspected alongside open work to keep this addition isolated. No existing runtime, authorization, evaluation harness, release workflow or other agent's branch was changed.

The model and dubbing recommendations received independent factual review. Follow-up corrections distinguish STS model IDs, audio acceptance from character-based billing, duration-preserving frame-rate conversion, and hosted endpoint versions. Example checks verify contiguous shot coverage, cue bounds, known characters, CSV agreement and unmeasured result fields. These are structural checks of planning material; they are not rendered-media or audience tests.

The unresolved work is concrete: approved art and casting; an editable app round trip; directed voice auditions; actual model comparisons; a finished pilot; measured revision labor and recurring-production capacity; and provider/live-stage integration if the results justify it. Keep this boundary visible when describing Star's capabilities.
