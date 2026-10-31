# STAR voice calls

Status: the call screen is in the desktop app (2026-10-13, branch `star/voice-mom-20261013`): a phone button next
to Send opens it, it asks for microphone consent, and calls are **push to talk** by default (hold the talk button or
Space; release and Star answers), with hands-free as an option. Every chat reply also has **Read aloud**, and new
replies can be read aloud automatically (off by default). The default voice is **Star (warm mum)**, `star-mum`
(section 10). You speak, Star answers out loud, and she stops talking when you press the key or talk over her.

What has been run and what has not:

| Item | Status |
|---|---|
| Whole pipeline from recorded audio files against the real STAR Server, including an interruption | Run, measured (section 7) |
| Turn logic, sentence chunking, cancellation, bridge, model download | Unit tests with fakes (`tests/test_voice_*.py`) |
| Loudspeaker echo handling | Simulation only (Star's audio mixed back into the fake microphone) |
| Push-to-talk calls from recorded audio, real engines, a local brain on the PC GPU | Run, measured (section 7.4) |
| A real microphone and real loudspeakers or headphones | **Not tested.** Nobody has spoken into it yet |
| The call screen and read-aloud in the React app | Built; tested with a fake bridge (`frontend/src/voice-call.test.tsx`); not yet clicked through in the real desktop window |

## 1. How a call works

```
microphone (16 kHz, 32 ms frames)
   -> voice activity (Silero VAD)            is someone talking?
   -> end of turn (pause + Smart Turn model)  have they finished?
   -> speech to text (faster-whisper)         starts during the pause, so it is usually ready in time
   -> brain (STAR Server, streaming)          short spoken-style reply, warm persona
   -> sentence chunker                        first sentence goes to the voice the moment it is complete
   -> text to speech (Kokoro)                 one sentence at a time
   -> speaker
```

- **Speech starts on the first sentence.** The server produces text at about speaking pace, so waiting for the whole
  reply would add many seconds. The voice prompt asks Star to open with two to five words ("Oh, well done.") so the
  first audio does not wait for a long sentence.
- **Interruption (barge-in).** If you speak for about 0.3 s while Star is talking, playback stops within one audio
  block, the request to the server is closed, and queued sentences are dropped. Only the words that were actually
  played are kept in the conversation history, so Star knows what you did and did not hear.
- **Thinking out loud.** If you pause and then carry on before Star has said anything, the half-started reply is
  cancelled and both parts of what you said are answered as one turn.
- **End of turn.** After a 0.26 s pause the transcript is started and the Smart Turn model judges whether you sounded
  finished. If yes, the turn ends once the silence reaches 0.6 s (people pause about that long between two
  sentences; ending earlier made Star start answers that then had to be thrown away). If not, the model is asked
  again every 0.19 s while the bar it must clear falls from 0.5 to 0.25; after 2 s of silence the turn ends
  regardless. Without the model (`endpointer: silence`) a turn ends after 0.64 s of silence.
- **Prompt cache.** The system prompt is short and never changes, and history is trimmed in large blocks instead of
  sliding every turn, so the server re-reads as little as possible before each reply. This matters: on the CPU
  server reading the prompt is the slowest part of a turn (section 7).

## 2. Code map

Everything lives in `star/voice/`. The first group is pure Python and always importable; the second group needs the
optional packages.

| Module | What it does |
|---|---|
| `chunker.py` | Streamed model text to speakable sentences; strips markdown, emoji, links, code |
| `turn.py` | `TurnDetector` (start, pause, resume, end of turn, barge-in rules) and `EchoGate` |
| `call.py` | `CallSession`: wires the stages, runs replies on worker threads, handles interruption and history |
| `brain.py` | `ServerBrain`: cancellable streaming client; `ScriptedBrain` for offline tests |
| `persona.py` | The voice system prompts: warm and caring (default), confident and commanding, anime-bright; one fixed prompt per style |
| `catalog.py`, `voices.json` | The voice catalog: every selectable voice, its style group, engine settings, licence and measured latency (section 9) |
| `metrics.py` | `TurnMetrics` and the latency table |
| `settings.py` | `VoiceSettings`: validated settings (voice id, engines, timings) |
| `filecall.py` | Scripted calls from WAV files with a real-time virtual microphone and speaker |
| `bridge.py` | UI actions and events (section 5) |
| `setup_models.py` | Downloads the four small model files, checked by size and SHA-256 |
| `engines.py` | Silero VAD, Smart Turn, faster-whisper, Kokoro; the registries where new engines plug in |
| `devices.py` | Real microphone and speaker (`sounddevice`) |
| `runtime.py` | Loads engines once, warms them up, builds a session |
| `__main__.py` | `python -m star.voice setup | call | file-call | make-test-audio | say | devices` |

Adding an engine: write a class with `synthesize(text) -> iterable of (pcm16_bytes, sample_rate)` (text to speech) or
`transcribe(pcm16_bytes, sample_rate) -> str` (speech to text), add one line to `make_tts` / `make_asr` in
`engines.py`, and add its name to `TTS_ENGINES` / `ASR_ENGINES` in `settings.py`. Streaming voices simply yield
several chunks; the session already plays them as they arrive and can cancel between chunks.

## 3. Setup

```
pip install -r requirements.txt -r requirements-voice.txt
python -m star.voice setup          # Kokoro, Silero VAD, Smart Turn: about 365 MB, verified by SHA-256
```

In the app a call uses the STAR Server you set up in Settings: its address, the key in the Windows credential
store, and the quick model (the quick model you chose, else the server's `star-voice`, else your one configured
model). The first three variables below are optional overrides, mainly for the command-line tools.

Environment variables:

| Variable | Meaning |
|---|---|
| `STAR_SERVER_URL` | Overrides the address from Settings, for example `http://192.168.1.20:8080/v1`. Must be an IP on your own network ending in `/v1` |
| `STAR_SERVER_API_KEY` | Overrides the saved key. Only ever sent in the Authorization header; never logged or printed |
| `STAR_VOICE_MODEL` | Overrides the model (with `STAR_SERVER_URL` set and no model given: `star-fast`) |
| `STAR_VOICE_MODELS` | Folder with the voice model files (default `%LOCALAPPDATA%\STAR\voice-models`) |
| `STAR_VOICE_<SETTING>` | Any field of `VoiceSettings`, for example `STAR_VOICE_VOICE=blend-heart-nicole` |

The speech-recognition model (`small.en`, about 460 MB) is downloaded by faster-whisper from Hugging Face the first
time it is used.

**GPU (NVIDIA, optional).** Replace `onnxruntime` with `onnxruntime-gpu[cuda,cudnn]==1.26.*`. Two traps, both
handled or documented here:

1. `kokoro-onnx` and `faster-whisper` depend on the CPU `onnxruntime` wheel, which overwrites the GPU build because
   both install the same import package. Uninstall `onnxruntime` and reinstall `onnxruntime-gpu`, or with uv add
   `override-dependencies = ["onnxruntime ; sys_platform == 'never'"]` (see `voice-lab/call-env/pyproject.toml`).
2. cuDNN 9 loads sub-libraries by name at run time. If the wheel's `nvidia/*/bin` folders are not on the DLL search
   path, the first convolution fails with "Failed to initialize CUDNN Frontend" and onnxruntime silently falls back
   to the CPU. `engines.add_nvidia_dll_dirs()` adds those folders before any model is loaded.

Measured on the RTX 3060 Ti: Kokoro about 14 times faster than real time on the GPU, about 2.2 times on the CPU (`voice-lab/kokoro-latency.json`).

## 4. Running it

Double-click launchers (real microphone; **not yet tested with a real microphone**):

- `scripts\star-voice-call.cmd`: generic. First start creates `.venv-voice` and downloads models (CPU build).
- `voice-lab\star-voice-call.cmd` (outside the repository, on the owner's PC): uses the GPU environment and models
  that are already set up there, so it starts in a few seconds.

Both read the key from `%USERPROFILE%\.star\server_api_key` without showing it. Use headphones, or pass
`--output speakers` to turn the echo gate on. Pick a voice with `--voice <id>` (ids as on the audition page).

Without a person (this is how the pipeline was tested):

```
python -m star.voice make-test-audio --out call-tests          # synthesises five caller questions + scenario.json
python -m star.voice file-call --scenario call-tests/scenario.json --out call-tests/run1 --verify
python -m star.voice file-call --scenario call-tests/scenario.json --offline-brain      # no server needed
python -m star.voice file-call --scenario call-tests/scenario.json --echo-db -15 --output speakers
```

`file-call` plays the questions into a virtual microphone in real time, lets Star answer through a virtual speaker,
talks over her in the middle of one answer, prints the latency table, and saves `user.wav`, `star.wav` (what was
audible, cut where the interruption cut it), `turns.json` and `latency.txt`. `--verify` transcribes Star's recorded
audio back to text as a sanity check that real speech came out.

## 5. Bridge contract for the call screen

The actions are registered in `star/react_shell.py` (`VOICE_ACTIONS`) and handled by `star/voice/bridge.py`. They use
the existing `starBridge.invoke(JSON)` call and answer immediately with `{"ok": true, "data": ...}` or
`{"ok": false, "error": "..."}`. Call events arrive on the existing `starBridge.event` signal as
`{"requestId": <callId>, "kind": "voice", "data": {...}}`, where `callId` is the `requestId` of the `voiceStartCall`
request.

### Actions

| Action | Payload | Immediate `data` |
|---|---|---|
| `voiceStatus` | none | `{available, missingPackages[], missingModels[], serverConfigured, inCall, callId, state, muted, speaking}` |
| `voiceGetSettings` | none | `{settings: VoiceSettings, choices: {asr_model[], endpointer[], output[]}}` |
| `voiceSaveSettings` | `{settings: {...partial}}` | `{settings}` after validation; stored in `voice.json` in the app data folder |
| `voiceListVoices` | `{style?}` | `{styles[], voices[], selected}`: the voice catalog, optionally one style (section 9) |
| `voiceSelectVoice` | `{voiceId}` | `{settings, voice, appliesToNextCall}`; saves the voice, speed, language, pauses, pitch and speaking style |
| `voiceListDevices` | none | `{devices: [{index, kind: "input"|"output", name, default}]}` |
| `voiceStartCall` | `{micConsent: true, settings?: {...partial}}` | `{callId, settings}`; loading and the call run in the background. Refused without `micConsent: true` (only the call screen's consent step sends it); stops any read-aloud |
| `voiceStopCall` | none | `{stopped: true|false}`; an `ended` event follows |
| `voiceInterrupt` | none | `{interrupted: true}` (a "stop talking" button) |
| `voiceSetMuted` | `{muted: true|false}` | `{muted}`; while muted the microphone is ignored |
| `voicePreviewVoice` | `{voiceId?, voice?, speed?, text?}` | `{previewing, voiceId}`; speaks one sample line (the style's own line for a catalog voice) when no call is active; a `preview_done` event follows |
| `voicePushToTalk` | `{down: true|false}` | `{down}`; push-to-talk calls only (a hands-free call refuses it). Down opens a turn (and interrupts Star if she is talking); up ends it after a 160 ms tail |
| `voiceSpeak` | `{text}` | `{speaking, sentences, characters, voiceId}`; read-aloud of one chat reply in the saved voice. The Markdown is turned into speech text first (`readaloud.py`); `speak_started`, then `speak_done` or `error` follow. Refused during a call |
| `voiceStopSpeaking` | none | `{stopped}`; ends a read-aloud or preview now |

Only one call can exist. `voiceStartCall` during a call returns an error. Invalid settings are rejected before
anything starts.

### Events (`data.type`)

| Type | Fields | When |
|---|---|---|
| `state` | `state`: `starting`, `listening`, `user_speaking`, `thinking`, `speaking`, `ended` | Every change. Drive the main visual from this |
| `progress` | `message` | While models load during `starting` (first call takes a few seconds) |
| `level` | `mic`, `speaker` (0 to 1) | About 12 times a second, for level meters or an orb |
| `speech_started` | `barge_in` (true if Star was cut off), `push_to_talk` (push-to-talk calls) | The user began to talk (or pressed the key) |
| `discarded` | `reason` | Push to talk: the key was held but no speech was heard |
| `partial_transcript` | `text` | Live transcript while the user talks (about once a second) |
| `final_transcript` | `turn`, `text` | The user's finished turn (empty text = nothing understood) |
| `assistant_delta` | `turn`, `text` | Raw text pieces from the brain as they stream |
| `assistant_sentence` | `turn`, `text` | A sentence has been synthesised and queued to play: use for captions |
| `interrupted` | `turn`, `reason` (`barge_in`, `push_to_talk`, `user_kept_talking`, `button`, `call_ended`), `heard_text` | A reply was cut; `heard_text` is what was audible |
| `turn_metrics` | `turn`, `user_text`, `reply_text`, `stages{...}`, `interrupted`, ... | After every turn; `stages` holds the latency breakdown in seconds |
| `error` | `message` | Something failed (server unreachable, wrong key, model file missing). The call keeps listening when it can |
| `preview_done` | `voice`, `stopped` | A voice preview finished |
| `speak_started` | `first_audio_seconds` | Read-aloud: the first audio is playing (keyed by the `voiceSpeak` request id) |
| `speak_done` | `voice`, `stopped`, `first_audio_seconds` | Read-aloud finished (`stopped`: cut short by Stop, a new read-aloud or a call) |
| `ended` | `turns[]` | The call is over; includes all turn metrics |

State flow in a normal turn: `listening -> user_speaking -> thinking -> speaking -> listening`. With an interruption:
`speaking -> user_speaking -> thinking -> speaking`. Finished turns are also written to the active chat (user text and
the words Star actually spoke), so a call appears in the conversation history like typed messages.

### Settings (`VoiceSettings`)

| Field | Default | Notes |
|---|---|---|
| `tts_engine` | `kokoro` | Only Kokoro is wired in today |
| `voice` | `af_heart:0.5+af_bella:0.25+af_nicole:0.25` | The Star mum blend; or an audition-page id (`heart`, ...) or any custom blend |
| `speed` | `0.80` | 0.6 to 1.4; under 1 reads calmer |
| `voice_style` | `warm-caring` | Speaking manner: `warm-caring`, `confident-commanding`, `anime-bright` (changes the system prompt) |
| `voice_id` | `star-mum` | Catalog id of the chosen voice; empty when `voice` is a custom recipe |
| `tts_lang` | `en-us` | `en-us` or `en-gb` (the British stock voices) |
| `sentence_gap_ms` | 120 | Silence after each spoken sentence (the commanding voices use 300 to 450) |
| `call_mode` | `push-to-talk` | `push-to-talk` (hold the talk button or Space) or `hands-free` (voice activity + end-of-turn model) |
| `read_aloud_auto` | false | Read each new chat reply aloud as soon as it is finished (never history) |
| `pitch_semitones` | 0 | Whole-voice pitch change, -6 to 6 (anime voices up, commanding down) |
| `asr_engine`, `asr_model` | `faster-whisper`, `auto` | `auto` = `small.en` on an NVIDIA GPU, `base.en` on the CPU (section 6) |
| `asr_prompt` | names such as Star, Roblox, RemoteEvent | Spellings the transcript should prefer |
| `device` | `auto` | `auto`, `cuda` or `cpu` |
| `vad`, `endpointer` | `silero`, `smart-turn` | `endpointer: silence` uses the plain silence timer |
| `output` | `headphones` | `speakers` turns the echo gate on |
| `min_end_silence_ms` | 608 | Shortest wait after you stop talking, even when the end-of-turn model is sure |
| `end_silence_ms`, `max_silence_ms`, `barge_in_ms` | 640, 2000, 288 | Turn-taking patience (silence timer without the model; hard limit; speech needed to interrupt) |
| `max_reply_tokens` | 220 | Upper bound for one spoken reply |
| `partial_transcripts` | true | Live transcript events |
| `input_device`, `output_device` | empty | Device name or index from `voiceListDevices`; empty = system default |

### Suggested screen behaviour

- Before showing a call button, call `voiceStatus`. If `available` is false, show what is missing instead
  (`missingPackages`, `missingModels`, or "STAR Server not set up").
- On `voiceStartCall`, show "getting ready" with the `progress` messages until `state: listening`.
- Show the live `partial_transcript`, replace it with `final_transcript`, then show Star's `assistant_sentence`
  captions. On `interrupted`, trim the caption to `heard_text`.
- A mute toggle (`voiceSetMuted`), a "stop talking" button (`voiceInterrupt`) and a hang-up button (`voiceStopCall`).
- Voice picker: `voiceListVoices`, `voicePreviewVoice`, `voiceSelectVoice` (section 9).

## 6. Speech recognition choice

Measured on the owner's PC (Ryzen 5 5500, RTX 3060 Ti) with `voice-lab/asr_bench.py`: 120 clips, that is 20 caller
sentences (everyday talk plus Roblox words) in 3 Kokoro stock voices, each clean and with room noise 15 dB under
the speech; 3.5 s per clip on average.

| Engine | Device | Word errors, clean | Word errors, noisy | Time per sentence (mean / 95th percentile) |
|---|---|---|---|---|
| faster-whisper `tiny.en` | GPU | 1.0% | 1.8% | 0.06 / 0.07 s |
| faster-whisper `base.en` | GPU | 1.0% | 1.6% | 0.08 / 0.12 s |
| faster-whisper `small.en` | GPU | 0.3% | 0.4% | 0.17 / 0.22 s |
| faster-whisper `distil-large-v3` | GPU | 0.9% | 1.0% | 0.27 / 0.28 s |
| faster-whisper `large-v3-turbo` | GPU | 0.15% | 0.15% | 0.29 / 0.31 s |
| Qwen3-ASR 0.6B (official `qwen-asr` package) | GPU | 0.7% | 0.7% | 1.44 / 2.05 s |
| faster-whisper `tiny.en` | CPU | 0.6% | 1.6% | 0.37 / 0.41 s |
| faster-whisper `base.en` | CPU | 1.2% | 1.8% | 0.73 / 0.84 s |
| faster-whisper `small.en` | CPU | 0.3% | 0.4% | 2.14 / 2.53 s |

How to read this: the caller is synthetic speech, which is much easier than a real microphone and a real child's
voice, so trust the ranking and the speed more than the error rates. An apostrophe in a different place ("player's"
against "players'") counts as an error, and the three small models differ by only a handful of words.

Choice: **faster-whisper**.

- On the GPU, `small.en` is the default. Transcription starts at the first 0.26 s pause and takes 0.17 s, so the
  transcript is ready before the turn ends at 0.6 s: it adds no delay. `large-v3-turbo` is the most accurate and at
  0.29 s still fits inside that wait; it is the better choice when about 1 GB more video memory is free (model
  weights at half precision: about 0.5 GB for `small.en`, about 1.6 GB for `large-v3-turbo`, from their sizes).
- On the CPU, `small.en` takes over 2 s per sentence, so `auto` picks `base.en` (0.73 s, about 0.4 s of added
  delay per turn). `tiny.en` (0.37 s) is the option when speed matters more than accuracy.
- Qwen3-ASR 0.6B was 8 times slower than `small.en` here and no more accurate on this test, so it is not wired in.
  It was measured through the official Transformers-based package only; the GGUF build under llama.cpp was not tried.

## 7. Measured latency

All numbers come from `file-call` runs on the owner's PC (Ryzen 5 5500, RTX 3060 Ti; Kokoro and `small.en` on the
GPU, Smart Turn on the CPU), 10 Oct 2026. A synthetic caller speaks five prepared lines into a virtual microphone in
real time and Star answers through a virtual speaker, so every figure is a clock reading, not an estimate. The
microphone and a real loudspeaker were never used. The files are in `voice-lab/call-tests/<run>/`
(`latency.txt`, `turns.json` with every event, `user.wav`, `star.wav`).

How to read the columns (all in seconds, per turn, from the moment the caller stops speaking):

- **end-of-turn wait**: the caller stopped; Star waits until she is sure the turn is over. It cannot be shorter than
  `min_end_silence_ms` (608 ms) even when the end-of-turn model is certain, because people pause mid-sentence.
- **transcribe**: speech recognition time that is *not* already hidden inside that wait. It starts at the first 0.26 s
  pause and takes 0.17 s on the GPU, so it is usually 0.00 to 0.08 s.
- **transcript -> first token**: the brain. **first token -> first audio**: the wait for the first clause (4 words,
  see `first_clause_words`) plus Kokoro (about 0.3 s once the clause exists).
- **TOTAL**: the caller stops talking until Star's first sound.

### 7.1 Four runs

| Run | Brain | End-of-turn wait | Speech end -> transcript | Transcript -> first token | First token -> first audio | TOTAL | Tokens/s |
|---|---|---|---|---|---|---|---|
| `run-server-3`: real server, 5 turns, 1 barge-in | `star-fast` on the server, load average 13.6 then 50.4 (other jobs) | 0.61 | 0.63 | **11.27** | **7.39** | **19.28** | 1.6 |
| `run-offline-3`: same call, `--offline-brain` | scripted: 0.9 s to first token, 4.6 tokens/s | 0.61 | 0.62 | 0.91 | 0.84 | 2.37 | 4.4 |
| `run-echo-gate-final`: echo at -15 dB, speakers, gate on | scripted | 0.61 | 0.62 | 0.91 | 0.84 | 2.37 | 4.4 |
| `run-echo-nogate-final`: echo at -15 dB, gate off (control) | scripted | 0.70 | 0.72 | 0.91 | 0.81 | 2.43 | 4.3 |

The real call, turn by turn (this is the file `run-server-3/latency.txt`):

```
turn  end-of-turn  transcribe  speech end ->  transcript ->  first token ->   TOTAL  tok/s  note
             wait                 transcript    first token     first audio
------------------------------------------------------------------------------------------------
   1         0.64        0.06           0.70          10.33            2.25   13.28    2.3  end=model, early transcript
   2         0.61        0.00           0.61           8.84            3.09   12.55    2.7  end=model, early transcript
   3         0.59        0.03           0.62          16.80           14.25   31.67    1.2  interrupted after 2.4s (barge_in)
   4         0.59        0.00           0.59          10.58           11.28   22.45    0.8  end=model, early transcript
   5         0.61        0.00           0.61           9.78            6.08   16.47    0.9  end=model, early transcript
------------------------------------------------------------------------------------------------
mean         0.61        0.02           0.63          11.27            7.39   19.28    1.6
```

What the four runs show:

1. **Star's own part is about 1.5 s.** With the scripted brain the whole chain, from the caller's last word to Star's
   first sound, takes 2.37 s, of which 0.9 s is the pretend brain. Waiting to be sure the turn is over is 0.61 s,
   speech recognition adds 0.01 s on average (it is done before the wait ends), the first 4 words arrive about
   0.5 s after the first token and Kokoro adds about 0.3 s (turn 1 of `run-offline-3`: first token, first clause and first audio at
   +0.00, +0.47 and +0.74 s).
2. **The real server was the whole problem.** On the real call the brain took 11.3 s to the first token and the
   slow token stream (0.8 to 2.7 tokens/s while the load average rose from 13.6 to 50.4) made the first clause take
   another 7.4 s. Nothing on the PC side accounts for that: transcription finished 0.00 to 0.06 s after the end of
   the turn, and Kokoro needed 0.4 to 1.4 s for each whole reply (1.5 to 9.9 s of audio). Waiting for the first
   clause took 1.8 to 2.6 s in turns 1 and 2 and 5.6 to 13.6 s in turns 3 to 5, when the token stream stalled. The server was never measured idle in this work, so this is
   the figure for a server shared with other jobs, not for the server at its best.
3. **The server probe** (`voice-lab/server_probe.py`, 15:43 UTC, load 13 to 28) explains why. The prompt cache works
   (310 and more cached tokens), but the *new* prompt tokens of each turn are read at only 1.7 to 3.4 tokens/s on
   this CPU-only host, so 27 to 34 new tokens (the caller's words plus the previous reply, which is re-read every
   turn) cost 10 to 12 s before the first token, and generation ran at 3.8 to 4.6 tokens/s. Two consequences are
   built into the call code: a request is never sent that may be thrown away (the 608 ms floor on the end-of-turn
   wait exists for this), and the history is trimmed in blocks (`CallSession._context`) so the cached prefix stays
   valid instead of changing every turn.
4. **The echo gate does its job in simulation.** The control run (speakers without the gate) lets Star hear
   herself: six turns were logged for the five caller lines, and every one was interrupted although the caller
   interrupted only once (five `barge_in` between 0.7 and 1.2 s into her reply, one `user_kept_talking`). With the
   gate on there were five turns and the only interruption was the caller's real one, after 2.6 s of the reply. Star stops talking in the same frame in which the interruption is
   confirmed (0.00 s after the `speech_started` event with headphones, 0.14 s with the gate, which waits for a few
   louder frames); the time the detector needs to confirm speech from the caller's first sound was not timed
   separately.

### 7.2 Other measurements

- **Start-up** (models already on disk): voice activity detector 2.3 s, end-of-turn model 0.1 s, speech recognition
  7.8 s, voice 5.8 s, warm-up 3.5 s: about 19 s from the command to "listening".
- **Speech recognition** `small.en` on the GPU: 0.17 s per sentence (section 6). **Voice**: Kokoro 0.33 s per
  sentence on the GPU, 1.1 s on the CPU (`voice-lab/kokoro-latency.json`).
- **Check on the audio.** `--verify` transcribed `run-offline-3/star.wav` and missed the words "First, we'll look" in
  one reply. Transcribing the same file again in 10 s windows found them, so it was a long-recording artefact of the
  check and the audio is complete (checked for that run only).

### 7.3 What this does not show

- The echo simulation mixes Star's own audio back into the virtual microphone at -15 dB and 80 ms late. That is not a
  room: a real loudspeaker adds reflections, distortion and a different delay. The gate was only run at -15 dB after
  its last change; the earlier -6 dB and -20 dB runs used the previous version of the gate and were not repeated.
- Nothing was measured with a real microphone, a real child's voice, Bluetooth output (the default output on the
  owner's PC is a Bluetooth speaker, which adds its own delay of tens to hundreds of milliseconds) or an idle
  server.
- A live-sounding call needs the brain's first token well under a second: people answer about 200 ms after the other
  person stops and a gap of 700 ms or more already reads as hesitation (`docs/research/voice.md`, section 7). With
  the server as measured here that is not reachable; with the scripted brain the chain takes 2.4 s.

### 7.4 Push to talk, real engines, a local brain on the PC (13 Oct 2026)

The server brain was off limits during these runs (the v1.0 release evaluation was using it), so the brain was a
small local model on the same graphics card: Qwen3.5-4B Q4_K_M under llama.cpp (Vulkan build b11538), thinking off,
about 57 tokens/s alone and 60 to 70 tokens/s in the call. Same five synthetic caller lines as above
(`voice-lab/call-tests/q*.wav`), voice `star-mum`, `small.en` and Kokoro on the GPU. In push-to-talk mode the
pretend caller holds the key for each line and lets go after its last frame, so **TOTAL is key release to Star's
first sound**. Whole stack peak: 6.08 GB on the card including the desktop's 1.3 GB (`vram-ptt-local.txt`).

| Run | Mode | End-of-turn wait | Speech end -> transcript | Transcript -> first token | First token -> first audio | TOTAL (mean) | TOTAL range |
|---|---|---|---|---|---|---|---|
| `run-ptt-local-1` | push to talk | 0.17 | 0.36 | 0.16 | 0.61 | **1.13** | 0.92-1.44 |
| `run-ptt-local-2` | push to talk | 0.16 | 0.38 | 0.17 | 0.50 | **1.05** | 0.84-1.19 |
| `run-handsfree-local-1` | hands-free (Smart Turn) | 0.62 | 0.63 | 0.17 | 0.45 | **1.24** | 1.17-1.33 |

- Push to talk removes the end-of-turn wait (0.16 s release tail instead of 0.61 s) but the transcript can only start
  at release (0.2 s on the GPU), so it saves about 0.1 to 0.2 s per turn. Its real gain is control: no cut-offs
  mid-thought, no false turns from room noise, and the key is an exact barge-in (turn 3 in both push-to-talk runs).
- With a fast brain Star's own part (end of turn + transcript + first clause + Kokoro) is under one second. With the
  server brain under load the brain alone took 11 s in `run-server-3`; measuring push to talk against the server
  waits for the release evaluation to finish.

## 8. Hand-off notes and open problems

- **Server provider (done).** `runtime.make_brain` builds the brain with `ServerBrain.from_settings()`:
  address from the app's Settings (`providers.validate_lan_endpoint`), key from the keyring
  (`providers.get_api_key`), model from `server_roles.quick_model`. The environment variables above still override
  them, and `voiceStatus` reports `serverConfigured` from the same lookup without any network call. A call is
  sent without a slot number, like other background requests (`providers.llama_request_fields`): it never waits
  for one slot while another is free, and the server chooses the slot. A call and a typed chat on the same model
  can therefore replace each other's cached prompt. Without a slot number the server takes the idle slot whose
  cached prompt starts like the request, otherwise the least recently used one (measured once with a probe
  script, not with a call and a typed chat running together).
- **Push to talk in the real window.** The Space bar works while the call window has focus and is ignored inside
  text fields; holding the on-screen button uses pointer capture so sliding off it still releases. Not yet tried in
  the Qt WebEngine window with a real microphone.
- **Real microphone untested.** Device opening, sample-rate negotiation on unusual audio hardware, and how the
  thresholds feel with a human voice all still need a person. `Microphone` asks PortAudio for 16 kHz mono directly.
- **Echo.** With loudspeakers the microphone hears Star. The energy echo gate (`output: speakers`) stops her
  interrupting herself in simulation, but it is not echo cancellation: the user has to speak clearly louder than the
  echo, and it has not been tried in a real room. Proper fix: WebRTC AEC3 in front of the VAD (for example the
  `pywebrtc-audio` package), or headphones.
- **Packaging.** The optional packages and models are not part of the Windows installer. `voiceStatus` reports them
  as missing rather than failing.
- **Other voices.** Only Kokoro is wired into calls. The audition page also has Chatterbox, Qwen3-TTS, Pocket TTS and
  Supertonic samples; adding one is an `engines.py` class (section 2). The catalog already lists the Qwen3-TTS and
  Chatterbox voices (with `callable: false`) so the picker can show them greyed out. See `docs/research/voice.md` and
  `docs/research/voice-styles.md` in the project folder for the measurements behind the recommendations.
- **Voice styles and young callers.** Callers can be children and teenagers. The commanding style is a firm-mentor
  tone and its prompt forbids romantic, sexual or role-play content; the picker should present it as an opt-in
  choice (not the default), and nothing in the prompts asks the brain to be flirtatious. Not tested with a live brain
  here: only the prompts' text and the settings flow are tested.
- **False end of turn between sentences.** Smart Turn sometimes ends the turn after the first of two sentences; the
  session cancels and merges, at the cost of one abandoned request to the server.
- **Server speed dominates.** Every other stage adds well under a second in total; the brain's first token and its
  tokens per second decide how the call feels.

## 9. Voice picker contract (Settings > Voice)

Three speaking styles, each a group of voices; the style also changes how Star words her replies (one fixed system
prompt per style in `persona.py`). The catalog is `star/voice/voices.json` (loaded by `catalog.py`, generated from the
audition measurements by `voice-lab/make_catalog.py`). All voices are original synthetic voices: Kokoro stock voices and
blends, voices designed from a written description (Qwen3-TTS), or Qwen / Chatterbox locked on a synthetic clip.

| Style id (`voice_style`) | Name | What it is | Voices | Live-call pick (`recommended_for: live`) | Quality pick (`quality`) |
|---|---|---|---|---|---|
| `warm-caring` | Warm and caring | The default. Includes the soft and whispery sub-style (archetype `whisper`) | 7 | none flagged (the default voice is `heart`) | none flagged |
| `confident-commanding` | Confident and commanding | Mature, calm, in control; a tone only, never explicit | 12 | `cmd-nicole-aoede` | `cmd-nicole-kore-firm-locked` |
| `anime-bright` | Anime-style | Bright adult English-dub style; includes soft East-Asian-accented voices | 10 | `ani-bella-heart-up` | `ani-genki-wide-locked` |

### What the screen calls, in order

1. **Open the picker:** `voiceListVoices {}` returns `{styles[], voices[], selected}`. `styles[]` is
   `{id, name, summary, preview_line}`. Each voice is `{id, name, label, style, archetype, engine, engine_settings,
   reference_clip, audition, licence, latency{first_audio_seconds, first_audio_kind, realtime_factor, device}, measured{pitch_hz,
   words_per_minute, pitch_range_st, ...}, recommended_for[], notes, callable, reason}`. `selected` is
   `{voiceId, voice, style, speed}` (voice id empty = a custom `voice` recipe). `voiceListVoices {"style": "anime-bright"}`
   lists one group.
2. **Show a voice:** group rows by `style`; label `recommended_for` as "Best for live calls" / "Best quality";
   show `latency.first_audio_seconds` ("0.27 s to first sound") and `licence` in a details row. A voice with
   `callable: false` (its engine is not built into calls yet: Qwen3-TTS and Chatterbox voices today) is shown disabled
   with `reason`; the same voice can be heard on the audition page (`audition` is `engine-folder/voice` there).
3. **Preview:** `voicePreviewVoice {"voiceId": "<id>"}` answers `{previewing, voiceId}` at once and speaks the style's
   own sample line (for example "Sit down. Breathe. Now show me what you built."); a `preview_done` event
   (`{type: "preview_done", voice}`, keyed by the request id) follows. It refuses while a call is running and refuses an
   uncallable voice (`ValueError`, shown as the error text). `text` may override the sample line.
4. **Choose:** `voiceSelectVoice {"voiceId": "<id>"}` stores the voice recipe, speed, language, sentence pause, pitch
   change and the speaking style in `voice.json` and answers `{settings, voice, appliesToNextCall}` (true when a call is
   running; the change takes effect on the next call, because the call already has its engine and prompt).
   Unknown ids and uncallable voices raise `ValueError` with a plain message.
5. **Call:** `voiceStartCall {}` uses the saved selection. To try a voice for one call only, pass
   `settings: {voice, speed, tts_lang, sentence_gap_ms, pitch_semitones, voice_style}` (the same fields the selection
   writes).

Settings the selection writes (all validated, see section 5): `tts_engine`, `voice` (a Kokoro recipe such as
`af_nicole:0.6+af_aoede:0.4`), `speed`, `tts_lang`, `sentence_gap_ms`, `pitch_semitones`, `voice_style`, `voice_id`.

Notes for the screen designer:

- Present the commanding style as an opt-in choice and never as the default. Its prompt forbids romantic or sexual
  content and role-play, but callers can be children and teenagers (section 8).
- "Soft and whispery" and "soft East-Asian-accented" voices were made from the owner's listening feedback on Kokoro
  Nicole; the page marks them. Their accents come from stock voices or description-designed voices only.
- Pitch shifts are resampling (the voice gets a little smaller or larger as well): kept to plus or minus 3.5 semitones,
  and only upwards for anime and downwards for commanding voices (a unit test enforces this).
- Adding an engine: write the class (section 2), add its name to `TTS_ENGINES`, and the catalog entries for that engine
  become `callable: true` with no other change.

### The screen (Settings > Star's voice)

`frontend/src/VoiceSettings.tsx`, shown on the Settings page under "Where STAR generates". What it does with the
contract above:

- One group per style, in the host's order, with the host's summary and sample line. The warm style carries
  "Default". The commanding style carries "Optional": its voices are listed only after the owner switches on
  "Offer the confident and commanding voices" (or when one of them is already the saved voice). Showing them
  chooses nothing.
- The saved voice is marked "Selected". A profile that never chose a voice has `voice_id` empty and `voice` set to
  the default recipe name (`heart`); the page treats that name as the catalog voice of the same id. Any other
  recipe is shown as "a custom recipe that is not in this list".
- Voices with `callable: false` sit under their own closed heading in each group ("7 more voices that are not usable
  in live calls yet"), each with that label and the host's `reason`; Preview and Use are off for them.
- Preview: one at a time. The row shows "Playing" from the click until the `preview_done` voice event with the same
  request id; an `error` voice event, a refusal of `voicePreviewVoice`, or no event within a minute is shown on
  that row. Nothing is reported as played before the host said so.
- Use this voice: `voiceSelectVoice`; the mark moves only when the answer carries the same `voice_id`.
- `voiceStatus.available: false` is shown as "The voice engine is not installed on this PC" with the missing
  packages and model files, and Preview is off. A voice can still be chosen. While `inCall` is true, previews wait.

Tests: `frontend/src/settings-ui.test.tsx` (against the fake Qt bridge) and the `settings` phase of
`scripts/shell_acceptance.py` (the real window and the real Kokoro engine; the loudspeaker alone is replaced by a
silent sink unless `--audible` is given).

## 10. Star's default persona, read-aloud and the 13 Oct 2026 voice round

**Persona.** Star is a warm, caring, nurturing, mum-like voice: kind, supportive, patient, proud of small wins and
honest when something will not work, never romantic, flirtatious or sexual (`persona.VOICE_SYSTEM_PROMPT`, the
`warm-caring` style). The call prompt is written for speech: one to three short sentences, a short warm opener, no
lists, headings, Markdown or emoji, numbers said as words, code and links described in a few words instead of read.

**Default voice: `star-mum`** (`voices.json`, first entry, recommended for live). Kokoro-82M blend of three stock
voices, heart 50% + bella 25% + nicole 25%, speed 0.80, 120 ms pause after each sentence. No real person is cloned
(Kokoro stock voices, Apache-2.0). Measured over the six comparison lines (`voice-lab/mom_audition.py`,
`analyze_samples.py`, `mos_estimate.py`): 186 Hz median pitch, 161 words a minute, soft falling endings (-7.6
semitones), 0.5% heard-back error, UTMOS MOS estimate 4.42, first sentence ready in 0.33 s (first audio packet
0.17 s), about 9 times faster than real time, about 1.2 GB of GPU memory. It had the best fit to the warm-voice recipe
(98 of 100) of the seven live candidates; `mom-heart-sarah-low` scored a little higher on MOS (4.50) but speaks at
181 words a minute, too brisk for the persona.

**Read-aloud.** Every assistant reply has a Read aloud button (`frontend/src/ReadAloud.tsx`). The host turns the
Markdown into speech text (`star/voice/readaloud.py`): headings and list items become short sentences, a code block
becomes "I've put the code on screen." (once), a table "There's a table on screen.", links keep their text, raw URLs
and file paths become "a link" / "a file path", emoji and `<think>` blocks are dropped, and replies over 1,600
characters stop at a sentence with "The rest is on screen." It speaks sentence by sentence and stays at most 1.5 s
ahead of the speaker, so Stop is instant. Automatic read-aloud (`read_aloud_auto`, Settings > Star's voice) reads a
reply only when it was just streamed in front of the owner, once, never history.

**The audition round.** `docs/voice-samples/ab/index.html` in the project folder (favourites in localStorage) now
opens with an engine comparison table (MOS estimate, first audio, speed, GPU memory, streaming, licence, live in STAR)
and a "Star's mum voice" group: 7 Kokoro blends (live) and 3 Qwen3-TTS VoiceDesign voices designed from written
descriptions, 2 of them locked with the Base model. Best Qwen result: `mom-calm-alto` (designed; recipe fit 100,
184 Hz, 161 wpm) and its locked version `mom-calm-alto-locked` (MOS 4.49, first audio 0.66 s, 1.7x real time, about
4.4 to 6 GB of GPU memory); Qwen is not wired into calls, so it is "best quality, not live yet". Licences re-checked
on the Hugging Face model cards on 13 Oct 2026: Kokoro-82M apache-2.0; Qwen3-TTS 12Hz 1.7B VoiceDesign/Base
apache-2.0; Chatterbox and Chatterbox Turbo mit; Fun-CosyVoice3-0.5B and CosyVoice2-0.5B apache-2.0; VoxCPM2
apache-2.0; Orpheus 3B apache-2.0 but gated; Fish Audio S2 Pro `fish-audio-research-license` (non-commercial);
IndexTTS-2 no licence tag on the card (custom bilibili licence in the repo); Pocket TTS cc-by-4.0; Supertonic 3
openrail. MOS estimates come from UTMOS22 strong (ONNX export `TigreGotico/utmos-onnx`, MIT; Saeki et al.,
Interspeech 2022): a screen, not a listening test. It favours clean neutral read speech and scores breathy voices
low (the owner-liked Nicole scores 3.0), so the owner's ears decide.

VoxCPM2 (OpenBMB, 2B, Apache-2.0, voice design from a description, streaming) was also run in this round: it filled
the card to 7.7 GB and ran about 2.8 times slower than real time, with MOS estimates 3.4 to 4.1 and large pitch drift
between lines, so it is audition-only on an 8 GB card. Full table: `docs/research/voice.md` section 9 in the project
folder.

## Expressive voice (2026-10-27, off by default)

`VoiceSettings.expressive` wraps the call's voice in `star/voice/expressive.py`: Star can mark her own words with
tags (`<whisper>`, `<caring>`, `<excited:0.8>`, `<laugh>`, `<sigh>`, `<sing>`, `<pause:400>`, `<emph>word</emph>`, ...;
list in `star/voice/styles.py`), her tone follows the conversation and her mood, ASMR mode, rare non-verbal sounds in
her own voice, role-play character voices (`star/voice/library.py`, clones of real people only with recorded consent),
songs she writes herself (`star/voice/singing.py`), loudness normalisation and an artefact guard (`star/voice/guard.py`).
The live path (Kokoro + DSP in the chosen voice) measured 0.5-0.96 s to first audio on the RTX 3060 Ti; the neural
engines (Qwen3-TTS, Chatterbox-Turbo) are quality-mode only. Details, licences, measurements and the A/B listening page:
docs/agents/voice-expressive-20261026.md.
