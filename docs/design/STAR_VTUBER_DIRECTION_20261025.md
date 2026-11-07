# Star's streamer design

The owner chose **cute anime streamer: expressive face, playful outfit, soft hair**. The formal black-and-gold gown concept was rejected. The current proposal is an adult character with charcoal-to-gold twin ponytails, honey-gold eyes, a cream top, a roomy black hoodie, shorts and chunky sneakers.

The [design sheet](../../assets/vtuber/star-streamer-design-sheet-v3.png) contains a front view, back view and three expression studies. It is proposed artwork, awaiting the owner's judgment. It is not a layered PSD, a Live2D export or a completed animated model. The existing painted mascot is preserved.

## References inspected

These are visual observations from the official character images, not claims about the performers or their rig performance. No reference artwork is copied into this repository.

| Reference | What I observed | Application to Star | What stays distinct |
|---|---|---|---|
| [Fuwawa Abyssgard](https://hololive.hololivepro.com/en/talents/fuwawa-abyssgard/) | Soft light hair surrounds the face; large dark sleeves contrast with a light torso; small accessories sit within larger shapes. | Give the face a clear light frame and use broad clothing shapes. | Star keeps her own hair color, celestial motif and streetwear; her requested animal modes use her own outfit and ear/tail designs, without a matching costume or copied face. |
| [Raora Panthera](https://hololive.hololivepro.com/en/talents/raora-panthera/) | A roomy jacket frames a fitted central outfit; saturated hair and coat dominate the silhouette; the pose feels active. | Balance an adult figure with a relaxed outer layer and expressive posture. | Star uses cream, charcoal and gold; no copied palette, tail, insignia or costume. |
| [Nerissa Ravencroft](https://hololive.hololivepro.com/en/talents/nerissa-ravencroft/) | Long dark shapes, blue accents, feathers and a staff produce a sharper, more elaborate silhouette. | Useful contrast: this visual density is farther from the owner's chosen cozy, playful direction. | Star's hoodie and softer face remain the focus. |

The new sheet uses fewer chains and small ornaments than the earlier concept, a solid neckline and larger cream areas. The face must remain recognizable when only the upper body is visible. The gold hair ends and star clip should carry identity before decorative details do.

## What the model still needs

Live2D's [facial expression tutorial](https://docs.live2d.com/4.2/en/cubism-editor-tutorials/expression/) uses separate eye and mouth artwork and deformed meshes. A flat design sheet cannot supply those concealed surfaces or keyforms automatically.

The production art needs independently painted hair sections, face base, brows, whites, irises, eyelids, lashes, mouth interior, lips, teeth, tongue, torso, sleeves and hands. Hair and clothing need hidden painted overlap so head turns reveal finished art. Keep a stable frontal face rather than repeatedly generating unrelated portraits for mouth shapes.

Use the official [standard parameter conventions](https://docs.live2d.com/4.2/en/cubism-editor-manual/standard-parametor-list/): head angles, independent eye opening, eye gaze, brow expression, mouth opening/form, body angle and breathing. Star's current CPU avatar renderer instead accepts layered PNGs plus `avatar.json`; that is a separate export target, not a Cubism model. Its closed/small/aa/ih/ou/ee/oh mouth states still need matching painted artwork.

For [VTube Studio](https://github.com/DenchiSoft/VTubeStudio), parameter injection requires an installed, authenticated plugin and a compatible loaded model. The API does not create the model art or rig.

Review the actual model in these conditions before enabling it as STAR Camera:

- At webcam scale over both bright and dark games, with the face and eyes readable.
- Head turns and tilts at the edges of their intended range, without gaps, hair clipping or doubled mouth lines.
- Closed, small and open vowel shapes while speaking, including a final closed mouth after interruption.
- Independent blinking, smiling eyes, a wink, surprise, concentration and a restrained unhappy expression.
- Hair and hoodie motion that settle instead of continuously wobbling; reduced-motion mode must work.
- A sustained Discord/OBS/game session on the actual RTX 4060, recording frame time, audio interruptions and dropped camera frames.

These are acceptance conditions, not passed results. No production rig, live Discord webcam check or RTX 4060 model benchmark was completed in this change.

## Emotes and channel identity

Four matching expression masters are supplied: laugh, love, hype and think. [Twitch's formatting requirements](https://help.twitch.tv/s/article/emote-guidelines?language=en_US&lingual=en_US) call for square transparent PNGs; manual sizes are 28, 56 and 112 pixels, each below 1 MB. All twelve exports in `assets/vtuber/emotes/upload/` were checked for size, RGBA format and file weight (about 2.6-31.8 KB). `python scripts/export_star_emotes.py` reproduces those size exports from the masters. Check the 28-pixel versions at actual size; a detailed image that looks good enlarged can still fail in chat.

The generated masters and design sheet are visual proposals. Twitch approval, emote slots, account creation, channel publication, banners, animated alerts and a finished Live2D model are not supplied by generating these images.

## Voice and performance evidence

The existing `star-cute` Kokoro recipe is retained; this change does not replace it with a performer's cloned voice. Official talent pages link to public videos, but this tool session did not provide auditory access. I did not listen to or rate those voices. Existing synthetic latency figures must not be described as new live measurements.

| Speech engine | Primary evidence | Role worth measuring on her PC |
|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | An 82-million-parameter open-weight model with Apache-licensed weights; already integrated in Star. | Keep the existing baseline and compare the actual saved `star-cute` recipe by listening. |
| [Pocket TTS](https://github.com/kyutai-labs/pocket-tts) | CPU-oriented synthesis; its October 2026 release lists 18.2M, 6.9M and 1.9M English models. | An alternative when speech competes with a game for GPU memory. Publisher speed claims are not Star measurements. |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | The 0.6B/1.7B model series supports streaming and voice design. | Compare original voice-design quality and combined GPU load before choosing it for live gameplay. |

Use the same lines for each candidate: a greeting, a quiet response, an excited reaction, a long thought, a question, a laugh and an interruption. Judge intelligibility, pronunciation, pacing and consistent character, then measure first audible response, underruns and game frame time with all processes running. None of these new head-to-head listening or device measurements was performed here.

[OBS's NVENC guide](https://obsproject.com/forum/resources/nvidia-nvenc-guide.740/) explains why game GPU saturation can interfere with streaming. Model quality therefore needs to be checked with the game, voice and camera running together. Installing a larger model on an 8 GB card does not establish better live performance.

## Generation record

Artwork was made with the built-in image-generation tool. The [saved prompt set](../../assets/vtuber/generation-prompts.json) records the design-sheet prompt and the shared emote prompt plus each expression. The sheet replaces the chest cutout with a solid cream neckline and simplifies accessories. The generated hair ornaments have five points despite the prompt specifying four; this needs a deliberate choice before final layer production. The rejected gown is excluded from the proposed asset pack.
