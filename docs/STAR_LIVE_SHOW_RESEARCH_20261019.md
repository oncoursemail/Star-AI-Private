# STAR Live Show: research and production blueprint

Research checked 19 October 2026 UTC / 18 October 2026 America/Chicago. Prepared for Alex Fisher and STAR AI. This is a production design and an offline source prototype, not a launched channel, a finished animated episode, or evidence of audience demand. Prices are the inspected published rates; actual account entitlements, taxes, and terms must be checked before paid operation.

## 1. The recommendation

Build STAR Live Show as an original animated television production system with three cooperating parts: an episode studio, a live cast performance system, and a broadcast controller. The episode studio keeps creating the next material while approved scenes play. The cast takes audience questions after the dramatic ending. The broadcast controller keeps the stream, archive, and publishing schedule coherent even when generation fails.

This design preserves the central promise: viewers can watch a continuing show, recognize the same characters and voices, and actually interact with the cast. It also provides time to improve a weak joke, repair a broken shot, or replace a bad vocal take before transmission. A visibly live broadcast can contain a production buffer; describe that honestly rather than claiming every displayed frame was generated at the instant it was watched.

The recommended first format is one original comedy, four recurring characters, two primary sets and one occasional location, a 6-8-minute pilot, and a 2-4-minute live aftershow. These are proposed starting constraints, not platform limits. The working creative direction is Night Window, detailed in the companion creative bible. The ambition is television craft: character specificity, staging, timing, performances, and satisfying stories. No source reviewed establishes that attaching a video model to chat automatically reaches the quality of Gravity Falls, Gumball, Rick and Morty, or a leading anime.

Real-time generative video is already a credible research and product category. The open-source Reactor/FastH3 system is unusually relevant because it connects chat, scene generation, queues and live output. Its model documentation also explicitly identifies the lack of subject, framing and voice continuity across clips. The same documentation reports roughly real-time generation on multiple B200 GPUs, with clip-specific limitations. Odyssey demonstrates interactive world generation; Decart demonstrates live video transformation. These are valuable candidates for experiments, but their documented results do not establish this complete episodic production target. [R01-R03]

## 2. What viewers would experience

The Watch page opens on an actual episode, with a clear live, replay or offline state. The cast has stable names, visual identities, motivations, relationships, and recognizable ways of speaking. Episodes resolve their immediate problem while occasionally advancing a longer story. New viewers can enjoy a single episode; returning viewers notice consequences and callbacks.

A typical cycle could contain a seven-minute episode, including its cold open, a three-minute aftershow called Window Still Open, and a twenty-second transition. The cycle can vary when a story needs space. It should not expand merely to fill airtime. While one episode plays, STAR prepares later episodes and accepts suitable questions. A question about the just-aired story can be answered in the aftershow. A story-changing suggestion is considered for a later unlocked episode or a clearly bounded choice with prepared alternatives.

The show must also work when chat is quiet. The cast can perform a short prepared closing exchange, discuss an aired prop, or introduce the next episode. It must not invent viewers, messages, applause, audience numbers, or a false claim that a recorded segment responded live. A rerun is labeled as a rerun; new live commentary around it is labeled separately.

When a broadcast session finishes, the next scheduled session can begin through a controller that reconciles YouTube state. An episode ending does not require a new YouTube video. A new broadcast creates a new session identity and usually a new chat context, so avoid needless restarts. Use a permanent Watch URL to resolve the current session. YouTube's official lifecycle distinguishes the broadcast video, ingest stream, and live chat resources. [R04]

## 3. Build characters people want to return to

The useful lesson from the requested reference shows is the craft behind them. In BAFTA's interview, Gumball writers Jon Foster and James Lamont discuss emotional heart, writing for the characters, collaboration, and learning from audience response. In Toon Boom's interview, storyboard artist Tim Hodge describes rough staging, reaction shots and revising an opening after understanding the ending. These support the proposed focus on character-driven scripts and inexpensive animatic revisions. [R05-R06]

Every main character needs a stable production bible. It should contain their immediate desire, longer ambition, contradiction, fears, capabilities, flaws, relationships, vocabulary, and behavior under stress. Visual records include silhouette, proportions, palette, turnaround views, costumes, expression sheets, mouth shapes, hand poses, and limits on deformation. Audio records include an authorized voice identity, audition takes, pronunciation dictionary, pacing, and acting direction. The character is a versioned production asset, not a fresh descriptive prompt on every shot.

Use a relationship matrix with asymmetric knowledge. One coworker may know why an object matters while another only knows who brought it in. Track promises, trust changes, possessions, injuries, costumes, unresolved conflicts, and future reveals separately. A generic summary cannot reliably substitute for these facts. The aftershow sees aired facts and an approved public character brief; unreleased plot answers should not be included in its retrieval scope.

The original Night Window proposal gives the show a repeatable engine: an ordinary personal need, an object with one understandable impossible property, a bad choice, escalation, and a costly better choice. Mara wants to be indispensable; Kit wants approval; Rook protects the station but overcontrols it; Bram, an obsolete departure board, fears being unnecessary. Their relationships produce different forms of humor. The full bible includes three episode premises and a short cold open for boarding and testing. The working name and concepts still need creative selection and brand clearance before public use.

Real people can participate as guests, voice performers or agreed avatars. Record what they authorized: identity, media, scripts or improvisation scope, commercial use, duration, attribution, and any removal conditions. The ordinary cast can be fully original fictional people with their own voices. Familiar shows remain references for ambition; their characters, recordings and specific visual assets do not need to become the new show's assets. YouTube separately prohibits misleading identity and endorsement implications. [R07]

## 4. The writers' room STAR needs

Use specialist roles with separate deliverables, not an unbounded conversation between agents. Each stage has a clear input, output, revision allowance and cost budget.

| Role | Deliverable | A reason to revise |
|---|---|---|
| Showrunner | Emotional question, premise and production limits | No character has a meaningful choice |
| Story editor | Beginning, escalation, reversal and ending | The ending needs an unexplained new rule |
| Canon editor | Checked facts and reveal permissions | A character knows something they have not learned |
| Dialogue and comedy editor | Distinct voices, subtext, visual and verbal beats | Every speaker sounds interchangeable |
| Performance director | Scratch read, intentions, pauses and listener reactions | Delivery changes the intended meaning |
| Board and animatic editor | Staging, camera plan and timed rough episode | The action is confusing without explanation |
| Technical reviewers | Media, timing, continuity and rights checks | A visible or audible defect remains |
| Audience editor | Evidence from actual viewers and useful revision proposals | A score is unsupported by a concrete observation |

Generate a few genuinely different premises, then choose one. Do not spend final-render money on every draft. A useful scene contract states who wants what, what prevents it, what changes, and why the next scene follows. Require each scene to advance action, relationship, understanding, or a deliberate comic pattern. Cut explanatory dialogue when a clear action or reaction does the work.

Produce a scratch table read and a timed animatic before final assets. An animatic is a rough sequence of boards played against temporary audio, with camera timing and reactions visible. It exposes sluggish scenes, confusing geography, missing setups and redundant lines. A joke may need silence or a listener's reaction instead of another sentence. Do not enforce a universal joke-per-minute target, insert canned laughter, or smooth every performance into constant movement.

Research such as DeepMind's Dramatron supports structured, hierarchical co-writing, while its authors explicitly describe collaboration with people and limitations of the outputs. It is evidence for a workflow pattern, not proof of autonomous professional comedy. STAR should retain outlines, chosen alternatives, actual feedback and reasons for revisions so later work can improve in a traceable way. Adding these documents to a repository does not retrain STAR's underlying model. Retrieval and runtime integration must be implemented separately. [R08]

The newer Fabula paper, revised in September 2026, studies an editable hierarchy of narrative plans, scenes and beats with writer participation, including 42 experts. Its authors investigate both automated evaluation and the limits of their storytelling assumptions. This strengthens the case for inspectable plans and human feedback; it does not establish that one narrative formula fits every genre or that an automated judge can replace the audience. [R43]

## 5. Animation: control first, visual experimentation alongside it

The primary recommendation is a reusable 2D or 2.5D character stage. Authored assets retain exact silhouettes, costumes and expressions. STAR directs the scene through a structured action vocabulary. A real-time renderer turns those commands into frames, while richer generated or authored inserts are prepared asynchronously.

| Candidate | Verified capability | Proposed place in the system |
|---|---|---|
| Godot 2D | Skeleton2D, Bone2D and weighted polygon animation | First persistent stage with complete application control |
| Spine with Godot | Supported runtime, bones, slots and animation tracks | Reusable expressive cutout characters, subject to license |
| Blender Grease Pencil | Official documentation and production talks describe drawing and animation in a 3D workflow | Art development, boards, special animation and prepared assets |
| Live2D Cubism | Real-time character SDK with several target platforms | Anime closeups and cast conversations; review embedding terms |
| Runway Characters | Animated or human conversational characters, custom personality/voice, own-agent integration | Audition for the aftershow or Meet the Cast conversation |
| Hedra Avatar | Audio-driven character video with supplied speaker positions for multiple audio tracks | Audition for prepared dialogue and reaction shots; measure actual generation delay |
| Veo / Gemini Omni / Runway video | Video generation and model-dependent reference or editing controls | Finished inserts and cinematic shots that pass continuity review |
| LTX-2.5 / open-weight Wan examples | Self-hosted generation with different hardware and control requirements | Isolated GPU experiments, offline rendering and adaptation |
| FastH3 / Odyssey / Decart | Live generation or transformation patterns | Research track with measured identity, cost and reliability tests |

The documented runtime features support these roles; the selection itself is our engineering judgment. Godot's skeleton and Spine's official Godot runtime offer direct animation control. Blender asset creation does not imply that a Grease Pencil character can be exported as a working Godot rig; choose an actual interchange path such as sprites, Spine data, or an appropriate 3D asset. Live2D's terms specifically discuss AI/chatbot and expandable applications, so commercial embedding is a product decision. [R09-R12]

For the persistent stage, author a small but high-quality action library: sit, stand, walk to a mark, listen, glance, point, hand over a prop, recoil, lean, pick something up, and settle. Add contact constraints and clear ownership of props. Screen direction, eyelines and character positions must survive camera cuts. Physical comedy also needs anticipation, weight, impact, recovery and a reaction. The camera should frame a gag where its essential information is visible.

Create an asset registry that pins each model sheet, rig, texture, prop, background, voice reference and motion library version. Render jobs reference those versions. A style change is a deliberate new production profile, not accidental drift. A review of one image does not approve an unseen animation or a later modified asset. Store the final media hash as well as the script and asset manifest hashes.

Runway Characters deserves a small audition because its documented system accepts animated personas and can integrate an external agent. The setup guidance favors one clear, centered, front-facing face. That makes it a plausible conversational performance option, but does not demonstrate multi-character prop acting or unrestricted camera blocking. [R13]

Google's current documentation includes Gemini Omni Flash as well as Veo. Omni documents editing limitations, including lack of uploaded audio references and voice editing. Veo documents short generated clips, reference limits, and a request latency range from seconds to minutes. The official LTX repository now recommends LTX-2.5 and distinguishes faster and more demanding quality paths. Evaluate current tools through adapters; avoid making an entire production depend on one changing model name. [R14-R16]

### Comparable products and production approaches

Fable's current Showrunner site is a close product comparison. It describes reusable characters, sets and canon, scene creation, combining scenes, viewer remixes and editorial curation. Its About page says creators retain canonical control while viewers branch stories. Those are useful experience patterns to examine. The inspected product pages do not establish a public STAR integration, an unattended YouTube operating contract, measured production economics, or television-level quality under this show's acceptance criteria. Verify export rights, access, throughput and control before choosing a hosted platform as infrastructure. [R40]

Toonstar represents a studio approach. Its own description combines storytellers, AI production technology and direct audience development. FOX's June 2026 partnership announcement names its Ink & Pixel production system and SPOT audience technology. These are company descriptions, not independent performance measurements or an available open-source stack. The relevant lesson for STAR is to develop recognizable original entertainment and distribution together with production technology. [R41]

Hedra's current Avatar API supports audio-driven performance from a start frame, with speaker positions associated with multiple supplied audio tracks. Its documentation lists audio inputs up to 600 seconds and output prices by resolution. This makes it worth testing for prepared dialogue scenes, beyond a single static narrator. A long accepted input does not prove fast output, stable prop interaction, or reliable scene-to-scene identity; audition those with the same cast and script used for competing renderers. [R42]

These comparisons define a more credible differentiator than claiming to be the first AI show: a specific original cast, consistently enjoyable episodes, transparent live interaction, a useful archive and measured reliable operation. This research inspected documentation and first-party descriptions; it did not run a paid head-to-head creative benchmark of these products.

## 6. Voices and sound need direction

A voice ID is only the beginning. Each character needs auditioned delivery across ordinary speech, whispers, anger, surprise, interruptions, long sentences, names, and silent reactions. Use original designed voices or authorized performers. Lock the selected identity and record provider/model versions and settings. A provider outage should lead to an approved fallback segment, not a sudden unrelated voice for a lead character.

For buffered episodes, synthesize the final spoken takes first. Build mouth shapes and captions from the actual audio, then synchronize animation and editing to the audio clock. ElevenLabs' timing stream supplies character alignment; it is not already a full phoneme-to-mouth performance. Rhubarb can turn recorded speech into timed mouth shapes and can use the known dialogue script. For fast interaction, benchmark a compatible streaming mouth pipeline and its latency separately. [R17-R18]

Keep dialogue, effects, ambience and music on separate stems. Intelligibility comes before density. Use pauses deliberately; reduce music during dialogue when appropriate; preserve breaths and timing where they matter. Detect clipping, unwanted silence, truncated syllables, incorrect words and discontinuities across cuts. Check subtitles against the approved spoken take and include speaker changes and meaningful sounds.

TTS vendor latency claims describe a component under specified conditions. They exclude the viewer's network, YouTube delay, question queue, moderation, language-model response, rendering and playback. The current ElevenLabs catalog includes v4 and v4 Turbo, but the lead voices should be selected by audition and consistency rather than recency alone. Commercial rights also depend on the service plan and the actual content. [R19]

## 7. Production architecture and data boundaries

The application should have independently restartable components with narrow responsibilities. Start small, with a local database and one worker if that is sufficient; a durable workflow engine becomes useful when multi-machine jobs and recovery justify the operational overhead. Temporal documents durable workflows and retries, but external side effects still need stable operation identities and reconciliation. [R20]

| Component | Owns | Must not silently do |
|---|---|---|
| Show library | Approved canon, asset versions, production profiles | Turn viewer comments into canonical facts |
| Episode planner | Premise, script, boards, shot contracts | Grant itself publication or spending authority |
| Render workers | Voice, animation, captions, technical measurements | Alter a ready episode without invalidating review |
| Review service | Technical evidence and editorial decisions | Substitute a model's score for observed audience response |
| Playout | Ready-media queue, scene boundaries, intermission, recording | Broadcast unfinished or stale reviewed media |
| Live performer | Selected questions and aired public canon | Read private future scripts or run infrastructure commands |
| YouTube controller | OAuth, stream keys, actual session state and upload outbox | Restart around a revoked or policy-blocked channel |
| Website | Current-session pointer, public cast, archives, optional direct votes | Expose stream keys or unreleased canon in browser assets |
| Observability | Measured throughput, cost, queue depth and incidents | Fabricate audience or performance numbers |

Use distinct identifiers for show, season, episode, scene, take, asset revision, broadcast, ingest stream, live chat and upload operation. Store timestamps in UTC and media time in a consistent unit. A publication manifest connects an exact finished episode to the broadcast/video where it appeared, captions, credits and source master.

Run the production workers independently of the encoder. A render timeout must not terminate an episode already on air. Workers have bounded retries, deadlines, cancellation behavior and a spend reservation. Preserve successful outputs and their metadata so retries do not regenerate everything. A job being accepted by an API does not mean it finished, and a finished render does not mean it passed review.

The controller should have a durable outbox and a single active owner for each channel. If a create request times out after possibly succeeding, reconcile remote state before creating another broadcast or upload. Do not claim distributed exactly-once behavior merely because a local event ID is unique. Normal network recovery retries the current ingest session where possible. A completed session advances the schedule once; a revoked session stops for diagnosis.

The playout reserve contains already usable media. When it falls below a threshold, reduce new-content ambition or choose a prepared intermission/rerun. The buffer must not be filled by marking lower-quality work approved. Keep an independent emergency switch, a known-good encoder configuration, and enough approved material to survive likely outages. OBS provides documented remote-control facilities; a production adapter still needs its own scope, state handling and verification. [R21]

## 8. Two kinds of latency and one sustainability test

Episode inventory is measured in minutes of finished material. Aftershow response delay is measured in seconds from a viewer's question to a visible answer. A larger episode buffer improves resilience but means chat cannot rewrite the scene currently being watched. Present suggestions as affecting future content.

YouTube says most viewers in low-latency mode receive under ten seconds of delay and most in ultra-low mode under five seconds; the latter has tradeoffs. These are platform figures, not total response guarantees. For example, a question may take a few seconds for filtering and response generation, further time for voice/performance preparation, and then incur platform delivery delay. The actual end-to-end distribution must be measured on the selected setup. [R22]

Bound the aftershow queue. A three-minute slot cannot answer fifty twenty-second questions. Select a few relevant questions, cap each answer, avoid repeatedly selecting one participant, expire stale candidates, and show honest submission status. The performer should answer the submitted question rather than read a username or instruction string indiscriminately. Moderation reviews need to bind to the exact question text; a later edited question needs a fresh decision.

The core production measurement is accepted media seconds divided by wall-clock production seconds, including the relevant review pipeline. For a continuously new stream, an accepted production rate of 1.0 only matches average consumption and leaves no recovery margin. A proposed initial target is at least 1.25 times the intended new-content duty cycle over a representative endurance test. This is an engineering starting target, not a universal standard.

Example: 900 accepted seconds produced in 1,200 seconds gives a rate of 0.75. If the channel consumes new content at 1.0 and starts with 900 seconds of reserve, it drains that reserve after 900 / (1.0 - 0.75) = 3,600 seconds, or one hour, under those constant-rate assumptions. A fast raw model can still have poor accepted throughput if many outputs need rejection or repair. Record p50, p95 and p99 job latency, warm-up stalls, failure rate, quality yield and cost per accepted minute.

## 9. Economics and your current hardware

Continuous newly generated cinematic video has very different economics from a channel with reusable rigs, prepared animation, live conversation and reruns. The following are generation-fee calculations, not full production quotes or equal-quality comparisons.

| Published example rate | 10 minutes of new video | 24 hours of new video | 30 days of new video |
|---|---:|---:|---:|
| Veo 3.1 Lite 720p: $0.05/second | $30 | $4,320 | $129,600 |
| Veo 3.1 Fast 720p: $0.10/second | $60 | $8,640 | $259,200 |
| Veo 3.1 Standard 720p/1080p: $0.40/second | $240 | $34,560 | $1,036,800 |

These inspected Google rates include the listed model's native audio. The arithmetic assumes every generated second is usable after one successful take. It excludes successfully generated but rejected takes, other inputs, separate writing/voice services, labor, assets, encoding, hosting, storage, egress and taxes. Reruns do not require generating the same media again. If only 40% of paid generated footage is accepted, the generation cost per accepted duration is approximately 2.5 times larger, assuming comparable take lengths. [R23]

A hybrid example is thirty seconds of premium inserts inside a ten-minute episode, at $0.10/second and two paid takes: $6 for those inserts. The remaining episode still has real asset, writing, voice and rendering costs. The example demonstrates why the format matters; it is not a claim that the full episode costs $6.

Runway currently lists Characters at two credits to start and two credits per six seconds, with a credit priced at $0.01. That is about $0.20 per minute of avatar session, plus startup and any surrounding services. One character performing a three-minute aftershow is therefore about $0.62 at that pricing. Multiple simultaneous character sessions multiply usage. This is a conversational avatar product, not the same cost comparison as full cinematic video. [R24]

ElevenLabs lists $0.08 per thousand characters for v4 and $0.04 for v4 Turbo. Using an explicitly illustrative thousand characters per spoken minute, ten spoken minutes are about $0.80 or $0.40 before retakes and other charges. Actual character counts and selected plan determine the bill. A rights-cleared local TTS option such as Kokoro can be auditioned for animatics or an intentionally separate narrator; open weights still require compute and quality evaluation. [R25-R26]

Read-only device observations during this task found the following. The inspection read CPU and memory information and PCI display-device listings; it did not install anything or benchmark generation.

| Device | Observed resources | Implication for this project |
|---|---|---|
| starai | AMD EPYC 7451 24-core; about 125.6 GiB RAM; roughly 45 GiB available at inspection; Matrox G200eW3 display controller | Candidate for planning, queues, databases, some audio/encoding and storage; no suitable modern generation GPU was visible in this check |
| alexbuz1 | Intel i7-9700; about 15.4 GiB RAM; roughly 3.6 GiB available; Intel UHD 630 | Limited spare resources; benchmark any additional service under existing load |
| Main | Reported offline by the remote device listing | No native Windows/GPU or OBS verification performed |

The PCI listing is an observation of visible devices, not an exhaustive guarantee about every possible remote accelerator. It is sufficient to avoid assuming these servers can run a multiple-B200 neural video pipeline. More CPU RAM is not interchangeable with a model's GPU VRAM requirement. The official Wan2.2 TI2V-5B example, for instance, specifies a 24 GB GPU configuration; it is a documented self-host example rather than a claim about the newest Wan variant. [R27]

Keep code, manifests and small configuration in GitHub. Keep render caches and episode masters in media storage with explicit retention, checksums and backups. Do not use GitHub Actions artifacts as the channel's permanent media store. At an assumed encoded bitrate of 8 Mb/s, one stream produces about 3.6 GB/hour or 86.4 GB/day before audio/container overhead and alternate versions. Thirty days is about 2.59 TB. These are decimal-unit calculations from an assumed bitrate, not measurements of the user's encoder.

Free software can reduce license costs, but it does not create unlimited free GPU time. Trial credits and interactive notebooks are not a dependable 24/7 infrastructure contract. Begin with measured local work and bounded optional paid adapters. Reserve a maximum daily spend before issuing jobs, reconcile actual bills after completion, and stop creating new work before a budget is exhausted. No paid service was activated in this task.

## 10. YouTube, audience reaction and highlight publishing

Use the official live-chat streaming interface where suitable, with reconnect state and a bounded fallback that honors polling intervals. Current YouTube quota documentation has changed from older tutorials: separate default search and upload buckets coexist with the general daily pool. The implementation appendix records the inspected values and method costs. Credentials, actual quotas and channel eligibility still require account-specific verification. [R28-R29]

Your requested audience-loved highlight feature is feasible to design, but the signal requires care. A chat spike can be laughter, confusion, a technical complaint, a raid, or a few prolific commenters. Message publication time does not reveal each viewer's playback position. DVR, delivery delay and typing add uncertainty. YouTube retention also arrives later and does not independently prove a joke worked. [R30]

The preferred clip source is the original local program master plus a scene and dialogue ledger. Select a complete setup, reveal, reaction and exit. Reframe deliberately for vertical delivery; a center crop can remove the second character or the visual payoff. Check captions and music rights again for the shorter context. Queue the upload with a stable operation ID, explicit privacy and an association with the source episode. Native YouTube Clips and uploaded Shorts are different products; the public API documentation does not provide a general clips.insert operation. [R31-R32]

Add an optional Clip this moment button on the website that records a direct vote with the current playhead and episode. It supplies a better moment reference than guessing from a message timestamp, although it still represents a self-selected audience. The show must remain enjoyable on YouTube without requiring the website.

For proprietary metrics derived from YouTube API data, follow the applicable analytics amendment and audit route. Current additional policies explicitly discuss permitted viewer sentiment analysis after accepting the amendment, while the base restrictions remain relevant. Keep this connector disabled until its conditions are met. First-party votes and editorial analysis can operate independently. Raw comment text and other non-statistical data remain subject to the stated refresh/deletion rules; do not put raw chat into permanent model training by default. [R33]

Actual audience classification matters. General-audience animation and content directed to children are different; made-for-kids live streams lose chat features. Develop the genuine target audience and apply the correct classification. YouTube's current monetization guidance distinguishes original recurring series with meaningfully different stories from repetitive or low-value mass production. Neither disclosure nor using AI automatically determines success or eligibility. [R34-R35]

The channel should plainly explain the AI production. Realistic synthetic people/events and certain generated audio may trigger specific disclosure rules even where visibly fictional animation alone does not. Human authorship, editing and arrangement also matter to the ownership of a creative production; the U.S. Copyright Office's report distinguishes protectable human contributions from material generated without sufficient human authorship. Keep creation and rights records rather than assuming every generated asset has the same status. [R36-R37]

## 11. Website and anime expansion

The public site is an entertainment destination with Watch, Meet the Cast, Episodes, Aftershow, Clips, World, and About/Credits. The homepage should lead with the show, an appealing scene, and what is playing. The owner's technical controls belong in STAR's private interface. Show actual online/replay state and useful empty states; do not fill a prototype with invented live metrics.

Cast pages should feel like introductions to people: a strong pose, concise personality-led biography, relationships, a user-triggered voice sample and a memorable scene. Separate the fictional biography from production and performer credits. Spoiler controls must filter the data sent to the browser, not simply hide future facts with CSS. The World page can reveal aired station locations and clues without leaking the future outline.

Provide an accessible player, captions, descriptive transcripts, keyboard navigation, readable contrast, visible focus, reduced motion, and pause/hide controls for chat or parallel movement. Avoid autoplay speech on cast cards. W3C's guidance supports planning media accessibility at the production stage. YouTube's chat embed does not work on mobile web, so provide an obvious path to chat in YouTube; the user is often on a phone. [R38-R39]

Anime should become a separate show and production profile after the first format works. It needs its own character sheets, poses, acting grammar, episode structure, action choreography, compositing and sound design. A filter does not create those things. The same episode store, queue, broadcast controller and feedback infrastructure can be shared. Visual assets, voices, lore and creative evaluators remain specific to each series.

Do not start a catalogue of twenty weak shows before one cast earns repeat viewing. Expand with a short second pilot and compare its accepted production rate, cost, creative results and viewer interest. A flagship comedy and a distinct later anime can share infrastructure without collapsing into one generic aesthetic.

## 12. Rollout with concrete exit conditions

| Stage | Produce | Evidence needed to advance |
|---|---|---|
| Creative proof | Original cast sheets, auditions, a 60-90-second animatic | Target viewers understand the scene, distinguish characters and want more; craft review identifies workable staging |
| Complete pilot | One coherent 6-8-minute episode and prepared aftershow | Final playback checked for continuity, acting, voice, captions and source rights |
| Private live rehearsal | A controlled short YouTube test with actual chat and the selected encoder | Measured end-to-end delay, successful question handling, no unintended publishing and a playable local master |
| Operational rehearsal | Several hours with render, network, token and encoder failure drills | Recovery preserves session state, budgets hold, reserve material works and duplicate writes are reconciled |
| Scheduled public programme | Limited sessions and a small number of carefully edited highlights | Sustained audience response, acceptable production economics, moderation and incident handling |
| Longer operation | Expanded schedule, then a second show if justified | Reliable accepted throughput with reserve, repeat audience interest and a demonstrated maintenance process |

The initial audience panel can be small and directional, for example 15-30 consenting target viewers. Randomize comparison order and ask what they understood, where they were confused, which moment they would share, and whether they want the next episode. A small panel is not market proof. An LLM judge's numerical score is also not proof of human amusement. Keep specific observations, disagreement and confidence limits. Evaluate actual moving scenes with audio, not only attractive stills.

Before extended unattended operation, test a missing voice provider, malformed scene, bad render, expired question, prompt injection attempt, encoder restart, dropped connection, stale health report, exhausted quota, ambiguous upload result, revoked channel, and a scheduled rollover near an episode boundary. Those live rehearsals are requirements for the future system; they are not claimed as completed by the offline prototype.

## 13. Relation to the current STAR code

The repository inspected was oncoursemail/Star-AI-Private, default branch main at 0d7bfdb838435221ab60ecd83687e896d34b568e. The public oncoursemail/Star-AI repository is the separate distribution repository in the user's current setup. Some repository guidance still contains older public-source wording; this task does not alter the ongoing release migration or other agents' branches.

Relevant existing source includes star/clips_obs.py for explicit local OBS replay controls, star/clip_library.py for a selected read-only clip folder, and star/creative_review.py for exact-evidence owner review. Those are useful neighboring components; they do not already supply a live animated television system. Preserve their existing boundaries and integrate any future new adapters deliberately.

The new source foundation is an isolated offline module, star/live_show.py, with a sample manifest and focused tests. It is intended to validate episode structure, associate review records with exact input, calculate accepted throughput and generation costs, and select externally reviewed post-episode questions. Its CLI does not contact YouTube or model providers, render media, authenticate reviewers, record an audience, or start a broadcast. Runtime integration, the visual renderer, voice adapters, a public website and channel operations remain separate work. The implementation verification record accompanies the source.

## Source register

All links below are primary documentation, official project material, first-person craft interviews, or original research. Product selections, arithmetic, thresholds and creative concepts in this document are our recommendations, not promises made by the sources. Software/model/policy information was checked on 19 October 2026 UTC; older craft interviews and papers are used for their stated lessons, not as current model benchmarks.

- R01. Reactor FastH3 implementation and documented limitations: https://github.com/reactor-team/infinite-livestream/blob/main/fast-h3/README.md
- R02. Odyssey-3 announcement and research preview: https://odyssey.systems/meet-odyssey-3 ; multimodal work: https://odyssey.systems/introducing-starchild-1
- R03. Decart Lucy: https://decart.ai/lucy
- R04. YouTube Life of a Broadcast: https://developers.google.com/youtube/data/live/life-of-a-broadcast
- R05. BAFTA interview with Jon Foster and James Lamont: https://www.bafta.org/stories/jon-foster-james-lamont-interview/
- R06. Toon Boom interview with Tim Hodge: https://www.toonboom.com/tim-hodge-on-storyboarding-for-tv-animation
- R07. YouTube impersonation policy: https://support.google.com/youtube/answer/2801947?hl=en
- R08. DeepMind Dramatron, original research and limitations: https://deepmind.google/research/publications/13609/ ; https://github.com/google-deepmind/dramatron
- R09. Godot 2D skeletons: https://docs.godotengine.org/en/stable/tutorials/animation/2d_skeletons.html
- R10. Spine Godot runtime: https://esotericsoftware.com/spine-godot ; license: https://esotericsoftware.com/spine-runtimes-license
- R11. Blender official indexed Story Artist page and production presentation (direct page retrieval was unavailable during this check): https://www.blender.org/features/story-artist/ ; https://conference.blender.org/2024/presentations/3838/
- R12. Live2D SDK and licensing: https://www.live2d.com/en/sdk/about/ ; https://www.live2d.com/en/sdk/license/
- R13. Runway Characters and reference requirements: https://docs.dev.runwayml.com/characters/ ; https://docs.dev.runwayml.com/characters/create-your-own/
- R14. Gemini Omni guide: https://ai.google.dev/gemini-api/docs/omni
- R15. Veo guide: https://ai.google.dev/gemini-api/docs/veo
- R16. LTX-2 official repository and license: https://github.com/Lightricks/LTX-2 ; https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x
- R17. ElevenLabs timing stream: https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps
- R18. Rhubarb Lip Sync: https://github.com/DanielSWolf/rhubarb-lip-sync
- R19. ElevenLabs models and publishing terms: https://elevenlabs.io/docs/overview/models ; https://help.elevenlabs.io/hc/en-us/articles/13313564601361-Can-I-publish-the-content-I-generate-on-the-platform
- R20. Temporal workflow and idempotency documentation: https://docs.temporal.io/workflows ; https://docs.temporal.io/nexus/operations
- R21. OBS Remote Control Guide: https://obsproject.com/kb/remote-control-guide
- R22. YouTube latency: https://support.google.com/youtube/answer/7444635?hl=en
- R23. Google API pricing: https://ai.google.dev/gemini-api/docs/pricing
- R24. Runway API pricing: https://docs.dev.runwayml.com/guides/pricing/
- R25. ElevenLabs API pricing: https://elevenlabs.io/pricing/api
- R26. Kokoro-82M model card: https://huggingface.co/hexgrad/Kokoro-82M
- R27. Wan2.2 official implementation: https://github.com/Wan-Video/Wan2.2
- R28. YouTube chat streaming: https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/streamList
- R29. YouTube quota calculator and revisions: https://developers.google.com/youtube/data/determine_quota_cost ; https://developers.google.com/youtube/data/revision_history
- R30. YouTube message schema and retention guidance: https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages ; https://support.google.com/youtube/answer/9314415?hl=en
- R31. YouTube upload API: https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- R32. YouTube Clips and Shorts: https://support.google.com/youtube/answer/10332730?hl=en ; https://support.google.com/youtube/answer/15424877?hl=en
- R33. YouTube base policies and derived-metrics amendment: https://developers.google.com/youtube/terms/developer-policies ; https://developers.google.com/youtube/terms/derived-metrics-policy
- R34. YouTube made-for-kids and live restrictions: https://support.google.com/youtube/answer/9528076?hl=en ; https://support.google.com/youtube/answer/2853834?hl=en
- R35. YouTube monetization: https://support.google.com/youtube/answer/1311392?hl=en
- R36. YouTube generative-content disclosure: https://support.google.com/youtube/answer/14328491?hl=en
- R37. U.S. Copyright Office, AI Part 2 copyrightability report: https://copyright.gov/ai/Copyright-and-Artificial-Intelligence-Part-2-Copyrightability-Report.pdf
- R38. W3C media accessibility: https://www.w3.org/WAI/media/av/
- R39. YouTube live chat and embedding: https://support.google.com/youtube/answer/2524549?hl=en
- R40. Fable Showrunner current product and About pages: https://www.showrunnerstudio.com/ ; https://www.showrunnerstudio.com/about
- R41. Toonstar and the FOX partnership announcement: https://www.toonstar.com/ ; https://www.foxcorporation.com/news/corp-press-releases/2026/fox-advertising-and-toonstar-team-to-create-new-opportunities-for-brands-in-digital-first-animation/
- R42. Hedra Avatar API and product specification: https://www.hedra.com/develop/models/video/hedra-avatar ; https://www.hedra.com/models/video/hedra/avatar
- R43. Fabula narrative-planning research, revised September 2026: https://arxiv.org/abs/2606.14411

