# English anime performances and dubbing

This section proposes a repeatable English performance pipeline for original Star anime and a separate path for localizing an existing master. All vendor capabilities were checked 19 October 2026. No voices were auditioned or synthesized in this research.

## 1. Choose the right starting point

For an original English-language production, write natural English, develop the scene through scratch performances and an animatic, then select the final performance early enough to shape the animation. There is no production benefit in first making a Japanese track solely to translate it back into the desired English.

If an original Japanese production is also desired, develop that version with a fluent adapter and director. A genuine English dub of a finished Japanese master is a different task: preserve the intended meaning and character, adapt the line to the visible timing, record against picture and mix the new dialogue with the music/effects master.

Netflix's anime dubbing guidance prioritizes original intent, asks for especially careful synchronization at key moments, and treats breaths, efforts and reactions as part of the performance. Its mixing guidance places dialogue within the physical and aesthetic scene. These are useful professional references; adopting this proposed workflow does not establish Netflix delivery compliance. [R26-R28]

## 2. Cast a character across a scene

Create an original voice brief for each role: age range of the fictional adult character, conversational rhythm, articulation, energy, accent if relevant, and how the character behaves under pressure. Specify what makes the delivery distinctive without requesting an imitation of an existing show's actor. Record permissions for any human performance, voice model and later commercial use at the point of casting.

Audition the same speaker in contrasting material: an ordinary exchange, a quiet admission, a joke that hides worry, a shouted warning, physical exertion, and a line delivered after an interruption. A pleasant narration sample does not establish those abilities. Listen to a complete exchange; line-by-line output may sound acceptable in isolation while its rhythm fails as a conversation.

Give an actor or model a playable intention. For example, replace the instruction "sound sad" with "keep your partner from realizing you heard the message; the word 'fine' costs you effort." Describe the listener and the immediate prior action. Emotional labels can be useful metadata, but the desired thought and action should drive the performance.

Choose two or three meaningfully different readings of a difficult line, then select one in the scene. Do not produce a large pool of near-identical takes without a clear decision. Retain unprocessed originals and the exact selected file so a later model update cannot silently change the cast.

## 3. The voice tools to audition

| Route | Appropriate role | What still needs proof |
|---|---|---|
| Directed human performance | Reference and final acting for difficult dramatic or comic material | Fit, consistency, recording conditions and the agreed usage rights |
| ElevenLabs v4 / v4 Turbo | Expressive scripted dialogue and faster response experiments | Character-specific acting, missing/extra words, stable emotion and continuity across takes [R29] |
| ElevenLabs Speech-to-Speech | Preserve a licensed source performance while testing a designed voice | Whether conversion retains timing, breaths, effort and intelligibility; the recommended model is eleven_multilingual_sts_v2 [R30] |
| Cartesia Sonic 3.6 | Fast English response and a fixed production snapshot | Emotion and exact cue fit require audition; speed settings are guidance rather than a duration guarantee [R31-R32] |
| Chatterbox Nano | Local English prototype, particularly where a production GPU is unavailable | CPU performance and acting on the actual host; the repository's speed claim is not a Star measurement [R33] |
| DramaBox | Research on stage-directed English acting and reactions | Long-clip reliability, model license, GPU cost and anime-scene performance [R34] |

Use a fixed released version when available, such as Cartesia's dated Sonic 3.6 snapshot, and save the actual selected audio regardless of provider. Voice identity is a combination of casting, performance practice, settings and retained assets. A model alias by itself is insufficient for season-long continuity. [R31]

Speech-to-speech is useful when the source performance supplies the intention and timing that text alone struggles to express. It does not remove the need for acting. Compare it blind against the source and a TTS take; keep it only if the chosen character voice adds value without damaging the performance.

Chatterbox Nano is a 110M English model; the repository advertises native reactions and an eight-core CPU speed result. That makes it a reasonable small local audition candidate, not a claim that CPU-only Star can render the full anime. DramaBox's author-reported warm H100 generation time lacks a standardized output duration, so it is not comparable with an audio real-time factor. Its optional NVIDIA reference denoiser has noncommercial terms and should be omitted from a commercial trial unless suitable rights are secured. [R33-R34]

## 4. Automatic dubbing has a narrower role

ElevenLabs now distinguishes Dubbing v2 Alpha from legacy v1 Dubbing Studio. The Studio is in maintenance mode; v2 transcript editing and regeneration through the API are Enterprise features. The current documentation says dubbing is not a live/realtime service and recommends treating its video output as a preview, retaining the original picture for production. [R35]

Use an automatic dub as a draft localization to review, not an automatic final anime performance. Preserve each character's objective, relationship, terminology and revelation. Check names and critical words manually, especially a negation that could reverse a plot point. A fluent line can still contain the wrong meaning.

LTX Dub-It Beta is another bounded experiment: its guide is single-speaker and expects supplied replacement/translated dialogue. It does not perform translation. The guide still describes 2.3 components, while the repository recommends 2.5 elsewhere; a compatible pinned configuration is required. The documented example is not proof of anime-domain performance. [R09, R36]

## 5. A cue sheet that supports good acting

For each cue, keep: scene and cut ID; character; original text if translating; adapted English; intended action; addressee; pronunciation notes; planned start/end; mouth-visible intervals; selected take ID; actual audio duration; sample rate; and revision status. A target duration is a recording constraint to assess, not a statement that a generated line fits.

The included pilot uses exact 24 fps and half-open frame ranges: start is included and end is excluded. At a 48 kHz master sample rate, one frame equals exactly 2,000 samples. If the project instead uses 24,000/1,001 fps, the relationship is 2,002 samples per frame. Keep the rational timebase explicit and preserve source-audio timing; these calculations do not define a universal perceptual tolerance.

Illustrative cue: a 72-frame window is three seconds at 24 fps. If a selected performance lasts 3.6 seconds, it is 20% longer than that window. First examine the adaptation, pause and acting. For English-original production, adjust the animatic if the performance earns the time. For a locked foreign-language master, try a concise faithful wording or another reading. Do not automatically speed every line until it fits.

The cue windows in this package are unrecorded targets. After recording, measure the actual media, revise the animatic, and regenerate downstream timing. Final subtitles and captions must follow the accepted recording, including any approved wording changes.

## 6. Lip sync for a drawn face

Rhubarb analyzes recorded WAV/OGG audio and emits timed 2D mouth-shape cues; supplying the dialogue text can help recognition. It supports six basic and three optional mouth shapes and documents interchange with OpenToonz and Moho. This makes it a useful first mouth-timing experiment. It does not supply the character art or decide the acting. [R37]

Create mouth drawings that fit each approved face angle and emotional state. Map the analysis output to that library, then correct emphasis, closures, pauses and transitions against the actual picture. Prevent the mouth from continuing to flap while the character is silently listening. A wide shouting mouth, a tight frightened reply and a relaxed smile should not be represented by the same mechanical opening cycle.

Character or word timestamps are not automatically phonemes or visemes. A viseme is a visible mouth configuration; several speech sounds can share one. Provider alignment is a starting point for the appropriate mapping, and rendered mouth results still need review. ElevenLabs' timestamp endpoint provides character alignment; it should not be mislabeled as a finished mouth animation track. [R38]

For close-ups, inspect key consonant closures and the relationship between jaw, cheeks, eyes and head. For distant or profile shots, a simpler graphic mouth can be appropriate. Respect the show's visual language instead of imposing a photoreal talking-head model on every drawn face. Review at normal speed with the scene, not only through waveform alignment.

Do a controlled retake test: change one line, retain its background and unaffected body layers, rebuild mouth timing, and inspect the join. If the emotional reading changes the gesture or breath, rebuild those dependent layers too. If a monolithic generative shot cannot preserve the accepted performance, use an editable mouth/face pass or another shot construction.

## 7. Make the sound belong to the world

Keep dialogue, music and effects in separate stems. Also retain clean selected takes, source takes, edit decisions, ambience and reaction/effort recordings. For localization, the music-and-effects mix should remain usable without the original dialogue. Do not rely on separating a flattened soundtrack when clean stems are under our control.

Netflix's premix guidance calls for synced, edited dialogue at the master project's technical settings, retaining clean material for mixing. Its mixing guide emphasizes matching perspective and environment. For Star, make the stairwell, rooftop, radio and close whispered voice perceptually distinct while keeping words intelligible. [R27-R28]

Record or generate breaths and exertion with the action context. A landing should not sound like a calm line followed by a generic grunt pasted into a gap. Keep the radio treatment reversible so the underlying performance remains available. Avoid excessive denoising that removes quiet acting detail, and keep the original audio for comparison.

Mix against the actual delivery specification rather than declaring a generic loudness number to be correct for every platform. Test the stereo result on headphones, ordinary speakers and a phone at a normal listening level. Music should support an emotional turn and can fall silent to let a line land. Preserve captions and accessibility information from the final accepted mix and edit.

## 8. The audition and acceptance process

Use the same short script and comparable loudness for every candidate. Hide provider labels when practical and randomize order. First review audio alone for character, intention, intelligibility and conversational rhythm; then review with picture for acting and synchronization. This separates a voice problem from a visual mismatch.

Have an experienced director/editor review the technical and performance faults, and invite intended viewers to explain what they understood and felt. Log missing words, extra words, wrong names, unnatural stress, inappropriate emotion, repeated voice drift and correction time. Do not translate a small preference panel into a claim about worldwide demand.

Proposed release gates: all story-critical wording is correct; voices remain identifiable; the emotional turn is understood; no distracting mouth mismatch remains in key shots; and the finished mix does not obscure dialogue. A helpful internal target is a median score of at least four out of five for acting, intelligibility and sync, with no unresolved critical fault. This is a project target, not an industry standard or a result already achieved.

Track selected audio seconds divided by total generated or processed audio seconds, plus direction and revision minutes. Record actual billed characters, minutes and total cost separately because providers meter differently. First-byte latency matters for the live aftershow; complete-scene quality and turnaround matter for an episode. Select separate configurations if those two jobs need different tradeoffs.
