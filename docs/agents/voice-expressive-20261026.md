# voice-expressive-20261026: Star's voice can whisper, laugh, sing and play characters

Branch `star/voice-expressive-20261026` (from `origin/star/next` 0ee2701d), board item #271, owner Claude.
Owner request: tones and emotions, whisper/ASMR, a warm caring "mommy" voice, playful/sleepy/excited/sad/sarcastic,
laughs/giggles/sighs/gasps/hums and other human sounds, role-play character voices, her own choice of tone,
singing, an artefact guard ("nothing weird-sounding"), highest quality. Off by default (`VoiceSettings.expressive`).

Honesty line: the tone choices follow a designed emotion simulation (star/emotion.py); nothing here claims she feels.

## What was built (all in the existing voice stack, not beside it)

| Piece | File | What it does |
|---|---|---|
| Tags + mood mapping | `star/voice/styles.py` | 18 styles (`<whisper> <soft> <warm> <caring> <tender> <playful> <happy> <excited> <sleepy> <sad> <sarcastic> <sing-song> <calm> <serious> <nervous> <asmr> <sing> <neutral>`, intensity `<excited:0.8>`), 16 sounds (`<laugh> <giggle> <chuckle> <sigh> <gasp> <hum> <cough> <sneeze> <yawn> <sniff> <clear-throat> <breath-in> <breath-out> <mm-hm> <um> <uh>`), `<pause:ms>`, `<emph>`. `[laugh]` works too. Continuity rule: a style never changes mid-sentence. `style_for_context` (what was said first, then her mood), `style_for_mood`, `suggest_sound`, `SoundPolicy` (max 2 per reply, 4 per minute, no repeat within 45 s, one filler), `add_fillers`, `TAGS_PROMPT` (persona lesson). |
| Engine | `star/voice/expressive.py` | `ExpressiveTTS` wraps the call's TTS (same `synthesize(text, prosody)` interface). Live: her Kokoro voice + DSP styles. Quality: neural engine first, guarded, Kokoro fallback. Sounds from the bank, room tone, ASMR chain, loudness to -18 LUFS + style level, role-play `speak_script`, songs `sing`. `build()` assembles it from settings. |
| DSP | `star/voice/voicedsp.py` | BS.1770 loudness (within 0.1 LU of pyloudnorm at 16/24/48 kHz), soft limiter, whisper by cepstral-envelope noise resynthesis (same voice, no pitch), WORLD pitch contour (level, range, sing-song swing, yes/no question rise, emphasis), breathiness (frequency-weighted aperiodicity), shelf, compressor, crossfades, room tone. numpy only; pyworld optional. |
| Guard | `star/voice/guard.py` | ASR round-trip WER, new n-gram loops, length per word, inner silence, clipping, loudness jumps, pitch spikes, speaker similarity. `GuardedTTS` re-synthesises with a new seed (up to 3) and logs every rejection (`guard-log.jsonl`, `stats.summary()` = rejection rate). |
| Characters | `star/voice/library.py` | JSON library CRUD; designed voices (refuses real-person imitation and child voices), own voices, clones only with a complete `ConsentRecord` (name, consent statement naming them, consent recording); `revoke_consent` deletes clones; `parse_script` for narrator + characters. |
| Sounds | `star/voice/nonverbal.py` | Routing native tag -> bank clip -> words -> skip (never reads "achoo"). Bank built in her voice: Chatterbox-Turbo native tags cloned from her own Kokoro clip; breaths from her whispered voice; hums and yawns from her voice on a new pitch arc. |
| Singing | `star/voice/singing.py` | Speech-to-singing with WORLD in her own voice; `compose` writes original tunes (lullaby/happy/sad); `can_sing` allows only her own songs and the public-domain list (Twinkle Twinkle, Jane Taylor 1806); anything else gets an offer to write an original. |
| Neural | `star/voice_neural.py` | Qwen3-TTS 0.6B Base clone of her own voice (+instruct), Qwen3-TTS 1.7B VoiceDesign (characters), Chatterbox-Turbo (native tags), speaker embedder; RoPE compat patch for transformers 5.19. |
| Lab | `star/voice/expressive_lab.py` | `bank`, `samples`, `bench`, `measure`, `ab-serve` (A/B page on 127.0.0.1, ratings -> `ratings.jsonl`). |
| Wiring | `call.py`, `chunker.py`, `persona.py`, `runtime.py`, `settings.py`, `bridge.py`, `engines.py`, `senses/fastpath.py` | `CallConfig.expressive` (prompt lesson, chunker keeps tags, screen text stripped, `tts.set_mood` per reply); `speakable` now removes voice tags for plain engines; `Engines.load` wraps the TTS (so calls, read-aloud, STAR Microphone, games all get it); settings fields below; bridge actions `voiceList/Create/Update/DeleteCharacter` (clones refused there); `expressive_allowed()` + VRAM row: neural engines only in `dedicated`/`off` profiles (never in `game`/`game-tight`). |

Settings (all ordinary `VoiceSettings` keys, validated): `expressive` (False), `expressive_engine` (`kokoro` | `qwen3-tts` |
`chatterbox-turbo`), `default_style` (`warm`), `style_intensity` (0.6), `allowed_styles` ("" = all), `asmr`,
`voice_sounds` (True), `fillers` (False), `artefact_guard` (`off` | `signal` | `full`), `expressive_home`. The default
voice stays `star-mum` (Kokoro). Note: `star/senses/instant.PC_PRESET` (another lane) picks `star-cute` for her own PC;
left unchanged here.

## Licences (checked 2026-10-26 on the Hugging Face API / model cards and PyPI)

| Model / package | Licence | Used |
|---|---|---|
| Qwen3-TTS 12Hz 0.6B Base, 1.7B VoiceDesign, tokenizer | Apache-2.0, not gated | downloaded |
| faster-qwen3-tts 0.5.4, qwen-tts-hf 0.1.1.post1 | Apache-2.0 (qwen-tts), see package | installed |
| Chatterbox-Turbo (ResembleAI/chatterbox-turbo), chatterbox-tts 0.1.7 | MIT; PerTh watermark on every output (kept) | downloaded (s3gen.safetensors skipped, 3 GB) |
| Kokoro-82M | Apache-2.0 | existing |
| pyworld 0.3.5 | MIT | installed |
| Maya1 (3B) | Apache-2.0, not gated | NOT downloaded: 3B, ~6.6 GB bf16, no room beside the brain on 8 GB, no Windows fast path |
| Orpheus 3B ft | Apache-2.0 but gated (needs the owner's account) and Llama 3.2 base terms | NOT downloaded (standing rule: no sign-ins) |
| ACE-Step 1.5 (song generation) | MIT | NOT downloaded: disk had 8-13 GB free; candidate for full songs with backing music (not her voice) |
| DiffSinger voicebanks | vary per bank | not used |
| CC0 sound recordings | n/a | not used: every sound is made in her own voice (no outside recordings) |

## Measured (dev PC: RTX 3060 Ti, Ryzen 5 5500; 2026-10-27 00:05-00:50Z)
GPU window: ComfyUI was paused for this, so desktop apps held only about 1.5 GB of VRAM. The CPU ran at 100% from other
lanes the whole time (browser, ChatGPT, vitest, other pytest runs), which slows the Python-heavy neural loops. Medians
of 5 runs, short opening sentence "Oh, well done, love." (`bench.json` in the samples folder).

| Engine | First audio p50 (max) | RTF | VRAM peak | Verdict |
|---|---|---|---|---|
| Kokoro `star-mum` on GPU (onnxruntime-gpu 1.26, CUDA 12) | 0.37 s (0.95) | 0.14 | ~1.2 GB (earlier measurement) | live default |
| Kokoro + DSP `whisper` / `sad` / `asmr` / `excited` (first chunk) | 0.66 / 0.51 / 0.65 / 0.96 s (max 0.93 / 0.70 / 1.53 / 3.18) | n/a | same | **live expressive path: about 1 s or less** |
| Qwen3-TTS 0.6B Base, ICL clone of her own voice | 2.04 s sentence, **1.17 s streaming first chunk**, 2.41 s with instruct | 0.89 | 2.89 GB | quality mode only (not live on the 3060 Ti while the CPU is busy) |
| Chatterbox-Turbo, clone of her own voice | 1.80 s | 1.09 | 3.23 GB | offline: native sounds for the bank |
| Qwen3-TTS 1.7B VoiceDesign | 1.29 s | n/a | 4.5 GB | role-play characters (quality mode) |
| Kokoro on CPU, same load | 9-17 s | 4.8 | 0 | not usable when the CPU is saturated (an ordinary run measured ~1.1 s earlier) |

Under 1 s on the GPU: yes for the live path (Kokoro + DSP, 0.5-0.96 s p50). No for the neural engines on this PC under
this CPU load (best: Qwen streaming 1.17 s). Her PC's RTX 4060 with an idle CPU was not measured.

Artefact guard:
- Qwen3-TTS clone, 10 style lines, full guard (small.en round trip, speaker encoder, signal checks): 14 attempts,
  4 rejected (rejection rate 0.29; all "jump", one also "pitch"), all fixed by the next seed, 0 gave up. Final WER
  0-0.125, speaker similarity to her reference 0.88-0.94.
- Live Kokoro path while rendering the samples: 57 chunks, 14 flagged (10 "pitch", 5 "jump"). The pitch flags were the
  autocorrelation tracker slipping an octave (every flagged jump was 11-12 or 19-24 semitones on clean Kokoro audio);
  octave slips are ignored now. Re-checking the 28 finished style samples: 1 flagged (a loudness jump).
- Measured fact worth knowing: Qwen3-TTS clone does NOT whisper when told to (61% voiced frames in the "whisper"
  sample), so whisper/ASMR is always made by the DSP whisper (0% voiced frames, verified on every whisper/ASMR file).

Level/spectrum checks of the samples (`measurements.json`, 57 files): every speech file is at -18.0 +/- 0.4 LUFS plus
its style's level (soft -21.3, sleepy -20.8, whisper -22.9, ASMR -23), peaks at or below -1.0 dBFS, no clipped
samples. Style effects show up as intended: sad and sleepy have lower pitch (180 / 178 Hz against 190 neutral) and a
narrower range (6.0 / 7.6 semitones against 8.1); excited and sing-song are higher and wider (210 Hz, 11.4 st / 10.8 st);
whisper and ASMR have no voiced frames; the sung samples hold vowels (68-75% voiced against 50% for speech). Of the
designed characters, The Dragon came out deep (91 Hz) but Captain Brine measured 217 Hz, so "deep man's voice" was not
followed for him. Nobody has listened yet: these are measurements, not a quality verdict.

Samples (57 WAV + 57 MP3, about 5.8 MB): `worktrees/wt-voice-expressive/docs/design/assets/voice-expressive-20261026/`,
copied to `work/voice-expressive/samples/`. Audio is not committed (`star commit` refuses audio files); the committed
folder has `ab.html`, `manifest.json/.js`, `measurements.json`, `bench.json` and the guard summaries. Listen and rate:
`python -m star.voice.expressive_lab ab-serve --out <that folder>`, then open http://127.0.0.1:8766/ab.html.

VRAM on her 8 GB card: `fastpath.expressive_allowed` refuses the neural voice in `game`/`game-tight`, and also in
`dedicated` (the 4B fast model + Qwen3-TTS add up to about 9.2 GB). It is allowed only with `fast_profile off` (turns go
to brain 1) and enough measured free VRAM. The live expressive path needs no extra VRAM (DSP runs on the CPU).

Dev PC note: onnxruntime-gpu 1.31 needs CUDA 13; with the CUDA 12 DLLs from torch 2.11 cu128, 1.26 is the version that
runs Kokoro on the GPU (the repo already says `onnxruntime-gpu[cuda,cudnn]==1.26.*`). chatterbox-tts with `--no-deps`
also needs onnx, diffusers 0.29, pillow, spacy-pkuseg and pykakasi.

## How to run
```
set STAR_VOICE_MODELS=<folder with kokoro-v1.0.onnx>     # python -m star.voice setup
python -m star.voice.expressive_lab bank --home <home> [--chatterbox]
python -m star.voice.expressive_lab samples --home <home> --out docs/design/assets/voice-expressive-20261026 [--neural]
python -m star.voice.expressive_lab bench --engines kokoro          # then qwen3-tts, chatterbox-turbo, qwen3-tts-design
python -m star.voice.expressive_lab ab-serve --out docs/design/assets/voice-expressive-20261026   # http://127.0.0.1:8766/ab.html
```
Dev PC env: `work/voice-expressive/.venv` (Python 3.12, shares torch 2.11 cu128 + transformers 5.19 from
`tools-portable/train-venv` through a .pth file to save 3 GB of disk), models in `work/voice-expressive/models`, bank and
reference clip in `work/voice-expressive/home`.

## Open / next
- Frontend: no UI yet for the new settings and the character library (bridge actions exist).
- The owner's ears: rate the A/B page; ratings decide which styles stay and whether quality mode is worth it.
- requirements-home.txt (hash-pinned) does not yet include pyworld / the neural packages.
