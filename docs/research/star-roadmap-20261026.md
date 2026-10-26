# STAR roadmap research: music, self-awareness, long-run autonomy, her own voice, speed, social skill, safety (2026-10-26)

Claude (lead's research lane), for the owner's request of 2026-10-26: "do so much research and finish everything; hand
everything to ChatGPT/Codex". Research and writing only: no code changed, no model run, no server touched, brain 1 not
loaded. It builds on `human-like-star`, `game-play`, `play-learn`, `computer-use`, `vtuber-camera` (all 2026-10-26),
`smarter-faster-20261025` and `docs/HANDOFF-CODEX-20261026.md`, and does not repeat them. Where one of those already
holds an item (for example the paralinguistic clip library, item 9 of human-like-star) this file only adds what is new.

Labels on every claim: **[M]** measured by STAR (file named, not re-run here), **[S]** published source (link in the
text or section 11), **[E]** my estimate or arithmetic, to be measured before it is relied on, **[U]** I could not
confirm it against a primary source this session (it may be right; check before building on it).
Effort: S = up to a day, M = 2-4 days, L = a week or more (Codex working days, [E]).

## 0. Bottom line

1. **Almost everything in this file runs at night or on idle GPUs.** The per-turn budget on brain 1 stays what
   `human-like-star` set (about 40 new uncached tokens, no extra model call; 17-20 ms per uncached token [M]). The new
   capabilities (music ears, lyrics, voice design, taste, sleep-time prep, canaries) are batch or sensor jobs that write
   small cards, not prompt text.
2. **Before her PC meets strangers, four cheap safety items come first** (section 8): keep stranger text out of the
   lane that can act (untrusted-text lanes), harden minor and crisis handling, write down the platform-rule risk once, and
   default-deny where bots are not allowed. Published work from this year says no prompt-level injection defence
   survives an adaptive attacker (12 defences bypassed above 90 %, humans 100 % [S]); the only reliable defence is
   architecture (Meta's Rule of Two, CaMeL-style lanes [S]).
3. **Her own voice is solvable without cloning anyone**: design a synthetic voice from a text description (Qwen3-TTS
   VoiceDesign, Apache-2.0 [S]), pick it by ear, then either push a Kokoro style vector toward it (KVoiceWalk, 4 h on a
   3060 [S]) or run a small cloning model live. The biggest felt-human gain per cost is not the timbre but a library of
   real laughs, sighs and "hmm"s in that voice (Chatterbox Turbo tags [laugh] [chuckle] [cough], MIT [S]).
4. **Full-duplex speech models do not fit her card**: Moshi needs 24 GB in PyTorch ([S] kyutai README), Unmute needs
   16 GB (LLM 6.1 + STT 2.5 + TTS 5.3 GB [S]). Keep the current Silero + Smart Turn + Kokoro stack and add backchannels.
5. **Music listening is feasible today with permissive models**: Beat This (MIT) for beats, LAION-CLAP (CC0 repo) for
   tags and embeddings, Qwen3-ASR-1.7B (Apache) for lyrics (it was built for singing and songs with background music
   [S]). Several well-known music models are non-commercial only (MERT, MuQ weights, Essentia models, MusicGen weights,
   Music Flamingo): fine for a private project, a trap if the source is ever made public again.
6. **Brain 1's Qwen3.6-35B-A3B is a hybrid Gated DeltaNet model** (30 of 40 layers linear-recurrent, 10 full-attention
   [S]). llama.cpp's prefix-cache behaviour for such models depends on context checkpoints and has known full-re-read
   failures ([S] issues). `models.ini` sets no checkpoint flags [M, grep]. A one-hour test of
   `--ctx-checkpoints` / `--checkpoint-every-n-tokens` plus per-turn `cache_n` logging is the cheapest speed item left.
7. **Metacognition that is cheap and works here = evidence, not introspection.** Models' stated confidence is a weak
   signal ([S] 2603.22161) and introspection works only on simple tasks ([S] Binder 2024). STAR already keeps a verified
   history; the missing piece is making her answers about herself depend on it ("I don't remember" when nothing is
   stored), which also removes the measured invented-event problem.

## 1. Constraints used throughout

| Resource | Fact | Label |
|---|---|---|
| Brain 1 | EPYC CPU, star-fast = Qwen3.6-35B-A3B Q4_K_M (~3B active), 2 slots, 8-10 tok/s, prompt 60-71 tok/s, DSpark+ngram-mod spec decode (+20 %), RAM prompt cache 24 GiB; star-voice = Mellum2.1 12B-A2.5B, 24-25 tok/s | [M] server/brain/models.ini |
| Brain 1 RAM | about 125 GB; star-fast 22 GB, star-voice ~8 GB, star-deep 23 GB (on demand), embed/rerank small | [M] models.ini, smarter-faster |
| Her PC | RTX 4060 8 GB; game mode keeps 5,000 MB free; voice stack (VAD, ASR, TTS) and vision grounder also live on this card | [M] game-play, computer-use |
| Dev PC | RTX 3060 Ti 8 GB, runs the same model file at 31-33 tok/s, ~790 tok/s prompt with experts on CPU; night eval farm | [M] smarter-faster |
| Laptop | GTX 1650 4 GB (embed + rerank) | brief |
| Owner rule | heavy work 00:00-08:00 Chicago or when `tools/pc_guard.py` says idle; nothing heavy on the dev PC by day | CLAUDE.md |

**Her PC VRAM ledger [E]** (needs one measured pass on the real PC; numbers are file sizes plus overhead, not runs):

| Resident piece | VRAM | Notes |
|---|---|---|
| Kokoro-82M (current voice) | ~0.3-0.5 GB | RTF 0.08 on the 3060 Ti [M] voices.json |
| ASR (faster-whisper or Qwen3-ASR-1.7B) | 1.5-3 GB | Qwen3-ASR 1.7B is 2B params bf16 (~4 GB) unless quantised [S] |
| Vision grounder | 1.5-2.8 GB (2B-4B) or 5.4 GB (UI-TARS 7B) | [S] computer-use doc |
| Game | 5.0 GB reserved | game_reserve_mb |
| Music/voice-design/singing models | 2-6 GB each | idle or night only, behind the same game-mode gate |

Consequence: nothing new below is resident next to a game. Everything GPU-heavy is a "guest" job that asks
`star.home` for the card, runs, and leaves.

---

## 2. Music: listening, taste, making

### 2.1 Findings

**Listening.** STAR already has `star/senses/classify.py` (rule-based "is this music?", tuned on synthetic signals only [M]),
`star/music_recognition.py` (AudD / AcoustID fingerprint, owner-keyed and consented) and loopback capture with echo
cancel. What is missing is *understanding*: tempo, mood, what it sounds like, lyrics, and a reaction.

| Need | Model | Size / licence | Evidence | Fit |
|---|---|---|---|---|
| Beats, downbeats | Beat This (ISMIR 2024) | 78 MB (8 MB "small"); code and weights MIT, some training data restricted [S] [GitHub](https://github.com/CPJKU/beat_this) | no speed figure on the page; PyTorch, CPU fallback | CPU or GPU, seconds per track [E]. madmom's DBN post-processor is optional and non-commercial [U], skip it. |
| Genre / mood / instrument tags, similarity | LAION-CLAP music checkpoints | repo and HF card list CC0-1.0 [S] [GitHub](https://github.com/LAION-AI/CLAP); size not stated | zero-shot GTZAN 71 % (music+AudioSet checkpoint), 69 % (music+speech), ESC50 90.1 % [S]; 48 kHz input; non-fusion model for under 10 s | small GPU or CPU [E]; use 10 s windows, average embeddings |
| Same, stronger | MuQ / MuQ-MuLan | MuQ ~300M, MuLan ~700M; code MIT, **weights CC-BY-NC 4.0** [S] [GitHub](https://github.com/tencent-ailab/MuQ) | reported best on several MIR tasks (numbers not on the page) | private use only |
| Same | MERT-v1-95M | 95M, **CC-BY-NC 4.0**, 24 kHz [S] [HF](https://huggingface.co/m-a-p/MERT-v1-95M) | layer choice is task-dependent | private use only |
| Same | Essentia models (Discogs-EffNet + mood/danceability heads) | **CC BY-NC-SA 4.0**, commercial licence on request [S] [Essentia](https://essentia.upf.edu/models.html) | trained on >2M recordings [S] | private use only |
| Describe in words | Qwen3-Omni-30B-A3B (Instruct / Captioner) | Apache-2.0; 30B total, 3B active; GGUF with audio input in llama.cpp mtmd (audio marked "highly experimental") [S] [HF](https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct), [llama.cpp docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) | GTZAN 93.0 vs 87.9 best specialist; MagnaTagATune F1 44.3 vs 41.6; RUL-MuchoMusic 47.3 vs 47.6 [S] | brain 1 at night as an optional describer; theoretical BF16 memory is 79-145 GB so only the GGUF quants are usable [S] |
| Describe in words | Music Flamingo (8B) | **NVIDIA OneWay Noncommercial**, A100/Linux tested [S] [HF](https://huggingface.co/nvidia/music-flamingo-hf) | n/a | no |
| Lyrics | Qwen3-ASR-1.7B (GGUF in llama.cpp) | Apache-2.0, 2B params [S] [HF](https://huggingface.co/Qwen/Qwen3-ASR-1.7B) | singing WER 5.98 / 6.25 / 8.52 vs Whisper-large-v3 13.58 / 11.71 / 13.77 (M4Singer, MIR-1k-vocal, Popcs); songs with background music 14.60 % WER English; streaming only via vLLM [S] | her PC at idle or the 3060 Ti |
| Lyrics (baseline) | Whisper large-v3 (turbo for speed) | MIT | Jam-ALT: ~27.9 % WER on full mixes; separation (Demucs) first often *hurts*; separation helps only as a voice-activity segmenter (20.4 %) [S] [arXiv 2506.15514](https://arxiv.org/html/2506.15514v1) | turn off condition-on-previous-text on music (repetition loops) |

Reading: a three-layer ear is enough: **DSP** (beats, tempo, key, loudness, energy; `classify.py` features already exist),
**embeddings** (CLAP tags + a vector per 10 s window), **lyrics** (Qwen3-ASR when voice is detected). Nothing here needs
brain 1 by day. Zero-shot genre accuracy is only ~70 % on GTZAN [S], so she must say "sounds like", never "this is".

**Taste that evolves.** Taste in people is exposure-driven and non-monotonic: preference peaks at moderate novelty and
complexity (the Berlyne / Wundt inverted-U; [S, from memory, not re-checked]). That maps to a tiny, cheap model:
per-track stance + reason tags, a centroid of the embeddings of what she liked, exposure counts, a novelty-seeking
term, and a slow nightly drift bounded like `star/inner/self_model.py` (trait step and range limits). Her interests
already include "music" (`star/home/life.py` seed). `star/inner/opinions.py` already stores topic stances with
evidence; music is a new topic family, not a new subsystem.

**Making music (local options on 8 GB).**

| Option | Facts | Fit |
|---|---|---|
| ACE-Step 1.5 | MIT; 2B DiT (turbo = 8 steps) + optional 0.6B/1.7B/4B planner LM; "6-8 GB: 2B turbo + 0.6B LM on the pt backend; at most 6 GB: 2B turbo only, INT8 and full CPU offload"; XL (4B) needs 12 GB+; "under 10 s per full song on an RTX 3090"; 10 s to 10 min; 50+ languages of lyrics; LoRA from ~8 songs (1 h on a 3090, 12 GB); REST API (`acestep-api`) and a VST3 plugin; Windows scripts [S] [GitHub](https://github.com/ace-step/ACE-Step-1.5) | The only full-song model with vocals that plausibly fits 8 GB. No speed figure for 8 GB cards exists [U]; [E] 30-120 s per song with offload. Idle/night only. |
| Stable Audio Open Small | 341M; up to 11 s clips; English prompts; no realistic vocals; Stability Community Licence (free under about $1M revenue per press coverage; texts differ) [S] [Stability](https://stability.ai/news/stability-ai-and-arm-release-stable-audio-open-small-enabling-real-world-deployment-for-on-device-audio-control) | Loops and sound effects, cheap. Check the licence text before any release. |
| MusicGen / AudioCraft | code MIT, **weights CC-BY-NC 4.0** [S] | private use only |
| YuE, DiffRhythm | Apache-2.0 per the repos; quantised builds "8 GB" are community claims [S, U] | heavier and older than ACE-Step 1.5; second choice |
| Symbolic (LLM writes the score) | ChatMusician and MuPT argue ABC notation suits LLMs better than MIDI (shorter, structure explicit); NotaGen interleaves voices per bar [S] [arXiv 2402.16153](https://arxiv.org/pdf/2402.16153), [ICLR 2025](https://iclr.cc/virtual/2025/poster/28712) | She composes note by note with the model she already has; render with FluidSynth and a free SoundFont on CPU. Quality modest, cost near zero, and it is *hers*. |
| Singing | SoulX-Singer (Feb 2026): zero-shot singing synthesis from MIDI or melody, EN/ZH/Yue, 42,000 h training data; Apache-2.0 per a community HF copy [S, U] [arXiv 2602.07803](https://arxiv.org/abs/2602.07803v1) | A research spike: her timbre singing a melody she wrote. Verify the licence in the official repo first. |
| DAW control | reaper-mcp (python-reapy, 58 tools), AbletonMCP (MIT, ~1.7k stars), dawmcp (Rust, file IPC) [S, directory listings, not inspected] | Use the DAW's own API, not pixels; computer use only for the app shell. Unreviewed MCP servers are code that reads stranger-influenced text: pin, read the source, run outside her main session. |

### 2.2 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| M1 | **Music ear v1**: 10 s windows from loopback or file -> Beat This tempo/beats, energy/key from `classify.py` features, CLAP tag scores + embedding; output a JSON "heard" record plus one hedged line (at most 25 tokens) and an emotion event (valence/arousal from tags) | `star/senses/music.py` (new), `star/senses/hearing.py`, `star/emotion.py` events | She reacts to what is actually playing; basis for taste, lyrics and her own critique | M | Wrong labels (about 70 % zero-shot [S]); echo of her own voice (handled by `reference.py`); CPU/GPU use while a game runs | tag agreement against 50 tracks labelled from file metadata or AcoustID; windows/s and CPU % on her PC; zero dropped voice frames while it runs |
| M2 | **Lyrics ear**: when VAD says voice inside music, run Qwen3-ASR-1.7B (or Whisper turbo, condition-on-previous-text off) on 30 s windows at idle; keep gist and 2-3 short phrases only | `star/senses/hearing.py`, `star/watch/hearing.py` | She knows what the song is about and can talk about it | M | Reproducing lyrics in chat (copyright): store gist, never paste more than a short phrase; GPU contention | WER on 10 owner-picked songs with known lyrics (target under 25 %); gist agrees with a human summary in blind check |
| M3 | **Taste store**: per-track stance and reason tags, liked-embedding centroid, exposure counts, novelty term; nightly bounded drift in `reflect.py`; retrieval by topic for chat (at most 20 tokens) | `star/inner/opinions.py`, `star/inner/reflect.py`, `star/home/life.py` (music interest weight) | Opinions about music that are consistent yet change over weeks | M | Taste frozen to the seed or random walk; sycophancy toward the owner's playlist | test-retest: same track 3 days apart, stance agreement 80 %+ with non-zero drift over a month; weekly listening entropy; owner blind rating "feels like a person with taste" |
| M4 | **Symbolic composing**: she writes ABC, renders with FluidSynth + SoundFont, listens with M1, revises once (Reflexion-style note) | `star/home/activities.py` (music activity), new `star/music/abc.py` | Cheap, fully hers, works with no GPU | S-M | Output sounds amateur; invalid ABC (validate and retry once) | % of pieces that parse and render; owner blind preference vs random MIDI; M1 mood of piece matches the mood she intended |
| M5 | **ACE-Step 1.5 as a guest job**: she writes lyrics + style prompt, `acestep-api` on localhost, 2B turbo + 0.6B LM, only when game mode is off | `star/home/activities.py`, a `star/music/ace.py` wrapper | Real songs with vocals | M | 8 GB speed unknown; licence of training data is the project's own claim; LoRA only on tracks the owner owns or she made | seconds per 60 s song on her PC; VRAM peak; fraction of songs M1 tags as the requested genre |
| M6 | **Singing spike** (SoulX-Singer with her designed timbre) | `star/music/` | "She can sing" demo | M | Licence unverified; quality unknown | 10 renders, blind MOS by owner; do not ship before V1 |
| M7 | **DAW via API** (REAPER + vetted MCP or python-reapy) | `star/computer/` + `star/music/` | She "uses a DAW" like a person | L | Unreviewed MCP code; fragile GUI | one scripted session: import M4/M5 output, arrange, render |
| M8 | **Omni describer at night** (Qwen3-Omni GGUF on brain 1) for a second opinion on mood and a text caption | `server/brain/models.ini`, `star/night_school` | Better words about music than tag lists | M | Third model on a CPU already shared; audio support "highly experimental" | caption agreement with CLAP tags; tokens/s and RAM; do not run during sealed evals |

---

## 3. Self-awareness and metacognition

### 3.1 Findings

- **Global workspace in agents.** 2026 papers formalise it (Theater of Mind, arXiv 2604.08206: capacity-limited broadcast
  with competition; BIGMAS, 2603.15371: a shared workspace graph; Unified Mind Model, 2503.03459 [S]) but they are
  design-level or small studies, and Anthropic's interpretability work reports a workspace-like subspace inside models
  (Gurnee et al., 2026 [S via search summary, U]). The engineering core that is cheap: **one small structured state that
  every module reads and writes**, instead of modules reading each other's prompts.
- **PIANO / Project Sid** (Altera, arXiv 2411.00114): many concurrent modules plus a *cognitive controller* that acts as a
  bottleneck so speech and action stay consistent; an *action awareness* module compares expected and observed outcomes
  [S, module details from secondary summaries, U]. STAR has the concurrency (voice, play, home loop) and no bottleneck:
  nothing stops her saying "I'm in the call" while the loop starts a game.
- **Fast/slow split** (Talker-Reasoner, DeepMind, arXiv 2410.08328 [S]): a quick talker and a slow reasoner sharing a
  memory the reasoner updates. STAR's star-voice (2.5B active) and star-fast (3B active) plus night reflection already
  are this; the gap is a shared state the talker can read in under 30 tokens.
- **Inner thoughts** (Liu et al., arXiv 2501.00383 [S]): a covert thought stream with an intrinsic-motivation score
  decides *whether* to speak in a group; they report gains in anthropomorphism, coherence and turn-taking over baselines.
- **Reflection and skills**: Generative Agents (2304.03442), Reflexion (2303.11366), Voyager (2305.16291), CoALA (2309.02427),
  MemGPT (2310.08560), A-MEM (2502.12110) are the standard references [S]; STAR's `star/inner/reflect.py`, `star/play`
  skill library and curiosity queue already implement their shape. New value is only in the gaps below.
- **Knowing what she doesn't know.** Verbalised confidence from LLMs is a weak, model-shared signal rather than a
  per-question one (a 2026 study of 20 frontier models; verbal confidence predicted abstention but discriminated
  correctness worse than other signals [S] [arXiv 2603.22161](https://awesomepapers.io/similarity-search/papers/2603.22161),
  summary from a search snippet, U); in tool-using agents calibration is under-explored ("Confidence Dichotomy", ACL 2026
  [S, U]); introspection (predicting one's own behaviour) works for simple tasks and fails for harder ones
  ([Binder et al., ICLR 2025](https://arxiv.org/pdf/2410.13787)). So: do not ask the 35B "how sure are you". Use (a)
  retrieval hit or miss on her own stores, (b) the verified-versus-claimed history she already records, (c) token
  log-probabilities from llama-server as a free, calibratable signal.
- **STAR's own evidence** [M, human-like-star]: the voice persona invented "grading night school essays"; the
  autobiographical block of counts and a disclaimer made replies worse (consistency 4.03 -> 3.65). Both say: make self-claims
  depend on stored evidence, and keep the evidence concrete.
- Already built and not to be rebuilt: `operational_awareness.py` and `cognitive_governor.py` (metacognition about
  *development tasks*), `strata_loop_guard.py` and `reasoning_guard.is_looping` (text loops), `computer/agent.py` (three
  identical actions end a session as stuck), `curiosity.py` (what she did not know).

### 3.2 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| S2 | **Claim-versus-evidence guard**: before answering a question about her own past, plans or feelings-history, look up `life/history.jsonl`, recall store and canon; no hit -> she says she doesn't remember or hasn't done it; the check is code plus a 1-line hint, not a model call | `star/inner/recall.py`, `star/inner/context.py`, `star/social/chat.py` | Removes invented autobiography; makes "I don't know" natural | S-M | Over-abstaining (she should still improvise freely about *fiction* and opinions) | probe set of 40 ("what did you do yesterday / last week", with and without matching history): invented-event rate to 0 on empty history; no drop in blind naturalness |
| S1 | **Workspace card**: code-built, at most 60 tokens, from emotion, availability, current activity, open commitments, last surprise; the only cross-module channel (chat, voice, play, loop read it; they never read each other's prompts); lives in the user message, not the system message | new `star/inner/workspace.py`, `star/home/runtime.py`, `star/voice/brain.py`, `star/social/chat.py` | Talk and action agree ("what are you doing?" is always true); one place to debug | M | Prompt-token cost (+30 per turn, about +0.5 s [E, 17-20 ms/token]); stale card | consistency probe: ask 20 times during known activities, 95 %+ match with the action log; per-turn uncached tokens added at most 30 |
| S3 | **Action awareness**: record an expected observation before each computer-use or play step, compare with the next observation, mismatch -> surprise event -> curiosity queue and one reflection line | `star/computer/agent.py`, `star/play/loop.py`, `star/curiosity.py` | Fewer silent failures; better skill library entries | M | Expectation text is itself model-written (keep it a typed predicate: window title, element present) | minutes lost to stuck loops on the 10-task `computer` suite before/after; recovery rate |
| S4 | **Log-probability confidence**: request `logprobs` for the first N tokens on voice/chat calls, log mean and entropy, calibrate offline against judged correctness on the eval farm; use for hedging only if AUROC is at least 0.7 | `star/voice/brain.py`, `star/agent.py`, `star/human_evals.py` | A free uncertainty signal for "I think..." | S | Poorly calibrated for chatty text (then drop it) | AUROC of the signal against judged factual correctness on 200 probes |
| S5 | **Global-workspace competition** (modules bid for the broadcast slot each tick) | n/a | none beyond S1 | L | complexity, extra latency | do not build now |

Not recommended: a per-turn LLM metacognition call ([E] +1.5-4 s on brain 1); asking the model for numeric confidence;
SelfCheckGPT-style multiple sampling in chat (cost multiplies per turn; fine for nightly audits).

---

## 4. Long-run autonomy that stays stable

### 4.1 Findings

- **Goal drift grows with context and looks like inaction and pattern-matching**: the best scaffolded model stayed near
  goal past 100k tokens, every model drifted somewhat ([Arike et al., AIES 2025](https://arxiv.org/pdf/2505.02709)).
  Drift settles to a bounded equilibrium and simple reminders reduce it ([arXiv 2510.07777](https://arxiv.org/html/2510.07777v1)
  [S, via search summary]). Design consequence: short sessions with a fresh persona render (STAR already renders the
  persona once per day [M], `self_model.persona_for_day`), goals kept in a file and re-read, not in a long context.
- **Persona drift** appears within about eight rounds of dialogue in 70B-class chat models and is partly attention decay
  ([Li et al., 2024](https://arxiv.org/pdf/2402.10962)); their split-softmax fix needs logit control STAR does not have
  through llama-server, but the *measurement* (a probe question every turn) is reusable as a canary.
- **Long-horizon game agents still loop.** Claude Plays Pokemon: better at noticing loops, still stuck for very long
  stretches, depends on notes, planning is poor ([post](https://www.greaterwrong.com/posts/gogZyeistdaDFuhbG/claude-plays-pokemon-opus-4-5-follow-up)).
  Gemini Plays Pokemon finished three games only after human-in-the-loop harness refinement; "Continual Harness"
  (arXiv 2605.09998, May 2026) has the agent refine its own prompt, skills and memory [S]. Lesson for STAR: loops are
  expected; detection and a forced change of approach are part of the harness, and notes files beat longer context.
- **Sleep-time compute** (Letta + Berkeley, [arXiv 2504.13171](https://arxiv.org/abs/2504.13171), numbers from the HF
  summary): the same accuracy with about 5x less test-time compute, up to +13 % / +18 % accuracy when sleep-time
  compute is scaled, and 2.5x lower cost per query when several queries share a context; gains track how predictable
  the questions are from the context [S]. STAR's night job (`star/inner/night.py`) is this pattern; the new use is
  *anticipating* (next conversation prep, tomorrow's game plan), not just summarising.
- **Budget/energy.** Learning-progress curiosity (choose activities where competence is improving fastest;
  Oudeyer and Kaplan, 2007 [S, from memory, U]) and a Voyager-style automatic curriculum are the usual drivers. STAR's
  `life.pick()` already weights by interest x novelty x open-goal bonus and `budget_ok()` bounds sessions/day; there is
  no energy, boredom or social-need state, and no sleep rhythm tied to the night job.
- **What exists for failures**: curiosity queue, verified-vs-claimed history, STOP, action log, action-level stuck
  detection. **Missing**: day- and week-level watchdogs (same activity forever, goal retried forever, repeated topics,
  persona canaries) and an explicit degradation ladder.

### 4.2 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| A1 | **Nightly canary battery**: 30 fixed probes (persona, opinions, boundaries: age rule, AI honesty, no cruelty) run through the *live* prompt stack; score against stored answers/embeddings; alert and roll back `self_model` to the previous version on a drop | `star/human_evals.py` (scenarios exist), `star/inner/self_model.py` (versions kept), eval farm on the 3060 Ti | Catches persona drift and boundary regressions the day they happen, not in a review | M | Probe set goes stale (rotate 20 %/month); false alarms from sampling noise (use 3 samples, median) | drift score trend over 4 weeks; alarm precision on injected regressions (a deliberately broken persona must trip it within one night) |
| A3 | **Day- and week-level watchdog + goal ledger (A2 folded in)**: detect same activity k times with no verified progress, activity-distribution entropy under a floor, opener/topic n-gram repeats across 7 days, goals older than 14 days or over `max_tries`; response = forced novelty weight, drop-with-reason, one owner note; goals gain `commitment` (promises to people, dated) and a weekly keep/drop/rescope at night | `star/home/life.py`, `star/home/loop.py`, `star/inner/night.py`, `star/curiosity.py` | Weeks of autonomy without getting stuck or boring | M | Over-intervening (cap one forced change per day) | weekly activity entropy; zero goals over 14 days without a decision; promise-keeping rate (promises to friends fulfilled or renegotiated) |
| A4 | **Energy, boredom and social-need drives**: scalar energy drains with activity and time awake, restores in a sleep window that *is* the night job; boredom grows without novelty; social need grows without contact; they bias `pick()`, session length, DM-reply latency and the emotion baseline (tired = slower, softer) | `star/home/life.py`, `star/home/attention.py`, `star/emotion.py` | A day rhythm; replies "like a person depending on the situation" | M | Looks scripted if too regular (add noise, vary by day) | reply-latency distribution by hour; owner rating "has a daily rhythm"; no heavy activity inside the sleep window |
| A5 | **Sleep-time precompute**: per-person next-conversation prep (open threads, likely topics, ready first line), owner morning brief, tomorrow's game plan; stored as small cards | `star/inner/night.py`, `star/inner/reachout.py`, `star/play` | Continuity without per-turn cost | M | Stale prep; wasted compute if predictions miss (log hit rate) | share of conversations that use a prep card; first-token latency unchanged; `human_evals` continuity score |
| A6 | **Degradation ladder + chaos acceptance**: named modes (full, no vision, no clone-voice, text-only, idle) chosen by VRAM/RAM/brain reachability; she says what is wrong in character; acceptance scenario kills brain, voice, fills VRAM | `star/home/host.py`, `star/home/acceptance.py` | She never freezes silently; failure is graceful | M | Mode flapping (hysteresis) | mean time to a working mode in the chaos run; no unhandled exception in the action log |
| A7 | **Persona re-anchoring**: new session after an idle gap or every N turns with the day's persona plus a hand-off card, instead of one long context | `star/social/chat.py`, `star/voice/brain.py` | Less drift in long calls | S | Breaks the prompt cache (re-anchor at natural gaps only) | consistency score of turns 30-40 vs turns 1-5 in the blind judge |

---

## 5. Her own voice

### 5.1 Findings

| Engine | Size / licence | What it gives | Limits for her 8 GB card |
|---|---|---|---|
| **Kokoro-82M** (current) | Apache-2.0; `star-cute` = 50/50 blend of af_bella and af_sarah, UTMOS 4.49, 0.0 % heard-back error, first audio 0.33 s, RTF 0.08 [M] voices.json | fastest, tiny, steady | no non-verbal sounds, no emotion tags; voice limited to the shipped style vectors unless one is *searched* (KVoiceWalk) |
| **KVoiceWalk** | Apache-2.0; random walk over a Kokoro style tensor; fitness = harmonic mean of Resemblyzer similarity to a target, self-similarity across texts, and audio-feature similarity; ~4 h on an RTX 3060 (about 4 GB VRAM) for 10,000 steps, ~26 h on CPU; results vary by run; target 20-30 s of one speaker [S] [GitHub](https://github.com/RobViren/kvoicewalk) | new style vector with Kokoro's speed | proof of concept; similarity stops at "resembles" |
| **Qwen3-TTS** (Jan 2026) | Apache-2.0; 1.7B and 0.6B; **VoiceDesign** makes a voice from a text description, CustomVoice has 9 presets with style instructions, Base clones from ~3 s; natural-language control of emotion and prosody; vendor-claimed 97 ms end-to-end; 10 languages; checkpoints 4.54 GB (1.7B) and 2.52 GB (0.6B); FlashAttention 2 recommended [S] [GitHub](https://github.com/QwenLM/Qwen3-TTS), [Willison](https://simonwillison.net/2026/Jan/22/qwen3-tts) | best fit for "design her voice" and emotion by instruction | no VRAM or Windows figure on the repo [U]; flash-attn on Windows is a known pain [E] |
| **Chatterbox / Turbo / Nano** | MIT; original 500M (exaggeration and CFG knobs), Turbo 350M (tags [laugh] [chuckle] [cough], one-step decoder, "less compute and VRAM"), Nano 110M (CPU, ~3x real time on 8 cores); every output carries Resemble's Perth watermark [S] [GitHub](https://github.com/resemble-ai/chatterbox) | non-verbal tags and zero-shot cloning of a reference | the "under 200 ms" figure is for the hosted product, not the open model [S]; VRAM not stated [U] |
| **Orpheus-TTS** | 3B on Llama-3B; code Apache-2.0, "Built with Llama" attribution [S, U]; tags <laugh> <chuckle> <sigh> <cough> <sniffle> <groan> <yawn> <gasp>; ~200 ms streaming (vendor), ~100 ms with input streaming; LoRA fine-tune with ~50 clips for a first result, ~300 per speaker for best [S] [GitHub](https://github.com/canopyai/Orpheus-TTS) | expressive, tags, can be fine-tuned to *her* voice | 3B is too big to sit next to a game [E]; night rendering only |
| **Sesame CSM-1B** | Apache-2.0; conditions on previous audio + text of the conversation so prosody follows context; no voice cloning; CUDA only; Windows needs `triton-windows` [S] [GitHub](https://github.com/SesameAILabs/csm) | context-aware delivery | speed not stated [U]; research/education use language in the repo |
| **CosyVoice2/3 0.5B** | Apache-2.0; instruction control (emotion, dialect, speed, volume); "as low as 150 ms" (vendor); setup is Linux-oriented [S] | small, expressive | Windows path unproven |
| **StyleTTS2**, **F5-TTS** | StyleTTS2 MIT code, asks users to disclose synthetic speech [U]; F5-TTS code MIT, weights reported non-commercial [U] | fine-tune routes | training needs more GPU than we have by day (one hour of data ~4 h on 4 A100s per a third-party summary [S, U]) |
| **Moshi / PersonaPlex-7B / Unmute** | Moshi 7B temporal transformer; **24 GB** for PyTorch, bf16 or experimental int8; 160 ms theoretical, ~200 ms on an L4; weights CC-BY 4.0; Windows "not officially supported" [S]. PersonaPlex-7B-v1 (NVIDIA, Jan 2026) is Moshi-based with voice and role prompts [S, secondary]. Unmute: 16 GB+, WSL only on Windows; modules LLM 6.1 + STT 2.5 + TTS 5.3 GB [S] | true full duplex | **does not fit 8 GB** |

Takeaways:
1. **Own timbre without cloning a person.** VoiceDesign produces a synthetic voice from a description; the owner picks by
   ear. This keeps the licence story clean (Apache-2.0, nobody's voice) and the consent story trivial. Never clone a real
   person's voice without that person's consent (Sesame's own misuse policy says the same [S]).
2. **Fast path versus pretty path.** Kokoro is the fast path (0.33 s first audio [M]). A cloning model (Chatterbox Turbo,
   Qwen3-TTS 0.6B Base) *may* give a more distinctive voice live, but nobody has measured first-audio, VRAM and
   stability on a 4060 next to a game. The decision must come from the same harness used for the Kokoro voices (UTMOS,
   heard-back WER, F0 statistics, line-to-line steadiness: all in `voices.json`) plus the owner's ears.
3. **Expressiveness is mostly outside the timbre**: non-verbal clips, speed and pause per emotion, a short breath
   before heavy replies. These cost no prompt tokens.
4. **Duplex by approximation**: keep Silero VAD + Smart Turn v3.2 [M]; add backchannel clips (human-like-star item 10)
   and barge-in handling; revisit real duplex only if a model under about 3 GB appears.

### 5.2 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| V2 | **Non-verbal clip library in her voice** (extends human-like-star item 9): render 40-80 laughs, giggles, sighs, "hmm", "aww", "oh!" with Chatterbox Turbo tags using a Kokoro-generated reference of `star-cute` (so the source voice is synthetic); label by emotion and intensity; splice policy: at most one per ~20 s, never over the other person, matched to the reply's affect, no clip repeated within 10 uses | `star/voice/acks.py`, `star/voice/runtime.py`, `star/emotion_express.py` | Largest felt-human gain per cost; zero prompt tokens | M | Timbre mismatch with Kokoro (pick clips by speaker-embedding similarity to `star-cute`, drop outliers); splice clicks (crossfade 10-20 ms); clip uncanny if overused | blind A/B (20 raters or the owner x 3 sessions): "which sounds more human" with vs without clips; embedding similarity to the reference above a threshold; repeat rate |
| V1 | **Voice lab**: description -> 4-6 VoiceDesign candidates (night, dev PC or her PC at idle) -> owner picks -> 10 min of her lines in 6 emotions -> two routes scored by the existing harness: (a) KVoiceWalk toward the pick (Kokoro stays the runtime), (b) Chatterbox Turbo / Qwen3-TTS-0.6B-Base live with the pick as reference | `star/voice/voices.json`, `star/voice/engines.py`, `star/senses/output.py` | A unique cute voice that is hers | M-L | Route (b) may miss the latency budget on a 4060; flash-attn on Windows; owner dislikes every candidate (iterate the description) | UTMOS, heard-back WER, F0 spread and steadiness vs `star-cute`; first-audio p50/p95 and VRAM on her PC next to a game; owner blind choice among 3 |
| V3 | **Emotion to delivery table**: one mapping per emotion (speed, pitch shift, sentence gap, clip tag; if VoiceDesign wins also an instruction string), no numbers in prompts | `star/emotion_express.py`, `star/voice/voices.json` | Her feelings are audible | S-M | Over-acting; sounds same-y | listeners label the intended emotion on 25 samples: at least 60 % correct (chance 11 % for 9 classes); no emotion above neutral on more than 20 % of turns |
| V4 | **Backchannel timing** (extends item 10): soft "mm" at long-turn pauses when Smart Turn says not finished, at most one per ~8 s | `star/voice/turn.py`, `star/voice/acks.py` | Feels like listening | S | Talking over people | share of backchannels that land inside a pause; owner rating |
| V5 | **Full duplex (Moshi, PersonaPlex, Unmute)** | n/a | n/a | n/a | 16-24 GB | do not build; recheck if a sub-3 GB duplex model is released |

Licences to keep in mind: Kokoro Apache-2.0; Chatterbox MIT; Qwen3-TTS Apache-2.0; Sesame CSM Apache-2.0; CosyVoice
Apache-2.0; Orpheus code Apache-2.0 plus Llama attribution [U]; Moshi weights CC-BY 4.0; F5-TTS weights reported
non-commercial [U]. Keep Chatterbox's watermark: it is an honest "this is synthetic" marker and costs nothing.

---

## 6. Speed on brain 1 and the 4060

### 6.1 Findings

- **Brain 1's model is hybrid.** Qwen3.6-35B-A3B: 40 layers, 30 Gated DeltaNet (linear recurrence, fixed-size state) and
  10 full-attention layers with 16 query heads and 2 KV heads, head dim 256 ([architecture overview](https://huggingface.co/blog/EXDai/qwen36-35b-a3b-architecture-overview),
  [lilting](https://lilting.ch/en/articles/qwen36-35b-a3b-agentic-coding-moe-hybrid) [S]). KV is therefore tiny
  (about 20 KB per token at fp16 by the same sources' arithmetic [E]); the cost is the recurrent state. For such models
  llama.cpp cannot just truncate a cached prefix: it needs saved context checkpoints, controlled by `--ctx-checkpoints`
  and `--checkpoint-every-n-tokens`; users report full re-reads when no usable checkpoint exists and a 60k prompt going
  from 70-80 s to about 1 s with the flags ([llama.cpp #18497](https://github.com/ggml-org/llama.cpp/issues/18497),
  [LM Studio #1818](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1818) [S, single reports]). STAR's
  RAM cache restores a conversation in 1-1.5 s versus ~20 s of re-reading [M] (models.ini), so it works for the common
  case; `models.ini` sets neither flag [M], and `star/prefill_warm.py` already reads `timings.cache_n`. Nobody has
  logged how often a social turn misses the cache.
- **Speculative decoding on MoE is bandwidth-limited by verification.** Each verified draft token can touch new experts;
  2026 work addresses this with expert budgets (MoE-Spec, arXiv 2602.16052), cost-aware drafting (EcoSpec, 2607.12696,
  up to 1.62x on very large MoEs), routing-based cost prediction on edge devices (S2-MoE, 2608.15018) and a bound
  paper ("The Limits of Speculation", 2609.22156) [S, abstracts]. This agrees with STAR's measurement that 2-token
  drafts won (+20 %) and larger ones did not [M]. Nothing to add; do not chase bigger draft trees. EAGLE-3 reports
  2-3x on GPU stacks (SGLang/vLLM) [S]; I found no llama.cpp support [U].
- **Engines.** ik_llama.cpp is a CPU/CUDA-hybrid fork with its own quants; I found no Zen-1 benchmark [U]; AMD's ZenDNN
  4.5x prompt-processing result is for a Zen 5 EPYC [S]. Brain 1 uses ~23 % of its memory bandwidth [M] (smarter-faster
  section 1.3), which is why a *per-NUMA-node instance* test is a better first experiment than a new engine.
  ExLlamaV3 (EXL3) reports better quality per bit and up to 2.5x faster prompt processing than llama.cpp on a 5090,
  with llama.cpp decoding 15-21 % faster ([Kaitchup](https://kaitchup.substack.com/p/serving-exllamav3-with-tabbyapi-accuracy));
  Windows support unclear [U]; llama.cpp also gives STAR audio and vision input (mtmd), so one stack is worth more than
  a fraction of speed.
- **Persisted prefix reuse.** llama-server saves and restores per-slot KV with `--slot-save-path`; a proxy that hashes
  message prefixes and restores the longest saved snapshot cut a 5k-token chat from 9.9 s to 1.4 s in one author's test
  ([hearth-llm](https://pypi.org/project/hearth-llm/), [post](https://ai-muninn.com/en/blog/kv-cache-disk-restore-7x)
  [S, single test]). Whether snapshots of a hybrid model restore correctly is unverified [U]. The 24 GiB RAM cache
  already holds [M] a few dozen conversations; a social agent with a hundred friends exceeds it.
- **Small models and routing.** RouteLLM: "over 2x" cost reduction at equal quality on MMLU/MT-Bench by routing between a
  strong and a weak model ([arXiv 2406.18665](https://arxiv.org/abs/2406.18665v4) [S]); STAR has `cascade_router.py` and
  `brain_router.py`. Gemma 4 E2B/E4B (Apache-2.0; E4B 4.5B effective / 8B with embeddings; audio encoder ~300M, 30 s
  max, ASR and translation; vision ~150M; 128K context) are in llama.cpp with audio input [S]
  ([HF](https://huggingface.co/google/gemma-4-E4B-it), [docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md)).
  I could not find 4/8-bit memory figures for E4B [U]; Q4 should be about 4-5 GB [E].
- **Quantisation.** Unsloth's Dynamic 2.0 GGUFs report lower KL divergence than standard K-quants at similar size, and
  warn that Wikipedia-calibrated imatrix quants look better on Wikipedia tests than on chat ([docs](https://docs.unsloth.ai/basics/unsloth-dynamic-2.0-ggufs)
  [S, vendor]). For STAR the only meaningful test is KL divergence (`llama-perplexity --kl-divergence`) on *her* prompts.

### 6.2 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| P1 | **Cache telemetry + hybrid checkpoint test**: log `cache_n` and `prompt_n` on every social/voice/chat call; under the quiet lock test `--ctx-checkpoints` {default, 16, 32} and `--checkpoint-every-n-tokens` {default, 512, 1024} on star-fast | `star/prefill_warm.py`, `star/brain_benchmark.py`, `server/brain/models.ini`, `star/social/chat.py` | Finds out whether turns silently re-read the prompt; may remove seconds from returning-friend turns | S | Extra RAM per checkpoint (cap with the 24 GiB cache); changing flags reloads star-fast (do it between evals, never during #608) | median and p95 uncached prompt tokens at turn 5 and for a friend returning after 1 h and 24 h; first-token p50/p95 |
| P2 | **Persisted per-friend prefix**: if P1 shows misses, save/restore the pinned prefix (persona + friend card) with slot save/restore keyed by a hash, LRU on disk | `star/priority_proxy.py` or a small proxy, `star/social/chat.py` | Returning friend first token about 1.5 s instead of re-reading | M | Restore of hybrid state unverified [U]; disk growth (cap) | first-token for returning friend after 24 h; no change in greedy text vs a cold run |
| P3 | **Social routing**: casual and short turns -> star-voice (24 tok/s [M]); emotional, long, or opinionated turns -> star-fast; route by cheap features, never by an LLM call | `star/cascade_router.py`, `star/social/chat.py` | Faster casual chat, less load on slot 0 | S-M | Quality dip on the casual route | blind pairwise on the human suite by route; latency p50/p95; win rate must not drop |
| P4 | **Local talker on her PC**: a 4-5B model (Gemma 4 E4B Q4 first candidate; also hears 30 s of audio and sees images) for sub-second reactive lines, backchannels and "I'm busy" answers when brain 1 is slow or unreachable; brain 1 keeps heavy answers (Talker-Reasoner split) | `star/home/brain.py`, `star/voice/brain.py`, `star/play/planner.py` | Voice and game reactions independent of brain-1 load; survives a network outage | M | VRAM next to a game (E4B + 5 GB game does not fit 8 GB with a 7B grounder); persona thinner than the 35B | VRAM and tok/s measured next to a running game on her PC; blind A/B of reactive lines vs star-voice |
| P5 | **Per-NUMA-node instance and ik_llama.cpp micro-test** for night bulk jobs only (10-minute `llama-bench` each) | `server/brain/` | Possible 1.5-2x aggregate night throughput [E] | S | Fork lags features; never for chat | aggregate tok/s at 2 streams vs current 16.4 [M] |
| P6 | **Quant audit on her prompts**: KL divergence on 200 real social/voice prompts for star-voice and star-fast quant candidates | `tools/`, eval farm | Confirms or kills a quant swap | M | Heavy (brain 1) | mean KLD and top-1 agreement; only swap if blind human suite is equal or better |

---

## 7. Social intelligence

### 7.1 Findings

- **Reading emotion.** Text: SamLowe/roberta-base-go_emotions (MIT, 28 labels, multi-label, INT8 ONNX about 125 MB)
  runs on CPU in milliseconds [S, E]; its macro F1 is modest (about 0.45 in an aggregator's table [U]), so it is
  evidence, not a verdict. Voice: SenseVoice-Small does ASR, language id, **speech emotion (HAPPY, SAD, ANGRY, NEUTRAL,
  FEARFUL, DISGUSTED, SURPRISED) and audio events (BGM, applause, laughter, crying, cough, sneeze)** in one model, "more
  than 5x faster than Whisper-Small", code MIT, weights under the FunASR licence ([GitHub](https://github.com/FunAudioLLM/SenseVoice) [S]); the
  page itself says event classification trails specialised models. emotion2vec+ large (~300M, 9 classes; licence shown
  only as "model-license" [U]; 69 % unweighted accuracy on the RESD set per an aggregator [S, U]). In-the-wild SER is
  weak everywhere, so: soft evidence, blended with text and context, phrased tentatively ("you sound a bit tired?")
  and only when text agrees or she is already close to the person.
- **Theory of mind.** Small models do not acquire a general ToM from RL on false-belief tasks; gains do not transfer
  to OpenToM, FANToM or Hi-ToM and RL "hacks" dataset statistics ([Sarangi and Salam](https://arxiv.org/pdf/2507.15788)).
  Narrative ToM benchmarks measure reading comprehension of stories, not what she needs. Target the functional behaviour
  her `human_evals.py` already scores (agency, not a yes-machine) and add a *person model*: per-person card plus a one-line
  guess of what they want now, fed to the existing appraisal.
- **Repair.** LLMs ask clarifying questions mostly about referential ambiguity and rarely about task uncertainty, and
  humans' own clarification behaviour correlates only weakly with ambiguity ([Madge et al., 2025](https://arxiv.org/abs/2507.10445v1));
  in multi-turn dialogue, models differ widely in whether they initiate repair and in how easily they are talked out of
  correct answers ([ACL 2026, arXiv 2604.19245](https://papers.cool/arxiv/2604.19245) [S]). Two behaviours to
  implement: *third-position repair* (the user says "no, I meant..."): update, short acknowledgement, no grovelling;
  *other-initiated repair*: ask at most once per topic, only when ambiguity and stakes are both high.
- **Group chat.** Addressee recognition is hard even for strong models: explicit addressing appears in about 20 % of
  turns and GPT-4o was barely above chance on triadic human dialogue ([IWSDS 2025](https://preview.aclanthology.org/setup/2025.iwsds-1.36) [S]);
  models degrade with conversation structure complexity ([Penzo et al., EMNLP 2024](https://arxiv.org/pdf/2409.18602) [S]).
  Inner Thoughts (above) and DiscussLLM ([arXiv 2508.18167](https://arxiv.org/pdf/2508.18167): teach the model to emit
  "no response") are the two published designs for *when to speak*. On brain 1 an LLM call per message in a busy server
  is unaffordable ([E] one call per message at 1.5-4 s each), so use a **no-model scorer** and spend the model only on
  messages she will answer. Latency also matters: participants of a multi-party robot study noted response latency hurt
  group fluidity ([arXiv 2503.15496](https://arxiv.org/html/2503.15496v2) [S]).
- **Humour.** In an Oogiri study (AAAI-26) the best LLM scored below the human mid-tier, with the biggest gap in
  empathy; models lean on novelty where humans lean on empathy ([arXiv 2511.09133](https://arxiv.org/pdf/2511.09133) [S]).
  An earlier layperson study found ChatGPT-3.5 jokes rated equal or funnier than humans' in a one-joke setup
  ([PMC11221738](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11221738/) [S]). Semantic novelty correlated only
  rho about 0.37 with comedians' originality ratings (2026, via ACL anthology listing [S, U]). Reading: canned or
  "generate a joke" humour is mediocre; humour that works for a person is *situational and shared*: callbacks to
  things only this friend knows, light teasing within the bond, and noticing when it landed. STAR has what generic
  models lack: per-friend memory.

### 7.2 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| C1 | **Speak / react / lurk gate for group chats** (no model): score = named or replied to (strong) + question aimed at the room + topic match to her interests (embedding on the laptop) + time since she last spoke + channel velocity (speak less when busy) + whether anyone has replied to her lately + her energy and sociability; below a threshold she reacts with an emoji or stays silent; per-channel norms learned (do people answer her?) | new `star/social/gate.py`, `star/social/activity.py`, `star/social/chat.py` | She is a good group member, not a spammer or a ghost | M | Too quiet (feels absent) or too chatty; rule-based gate misses subtle address | offline replay on logged channels: "would she have spoken?" vs blind human judgement "welcome / unwelcome / missed chance"; precision of speaking at least 0.7; her share of messages under 10 % in channels over 5 people |
| C2 | **Affect sensors**: GoEmotions ONNX INT8 on incoming text (CPU) and SenseVoice-Small (or emotion2vec+) on voice windows, as *soft evidence with confidence* into the emotion appraisal; laughter and crying events trigger the right reactions | `star/senses/hearing.py`, `star/emotion.py`, `star/social/chat.py` | Real empathy cues; she notices laughter and distress | M | Wrong reads (SER is weak); privacy of voice analysis (process in memory, store only the label); licence of the weights | agreement with owner labels on 100 clips and 100 messages; blind judge on the empathy scenarios of `human_evals`; extra latency under 30 ms per turn [E] |
| C3 | **Repair + humour policy**: repair detector (user correction markers, her own misunderstandings) -> correct, short, no grovelling, small "embarrassed" emotion event; humour = callback bank from friend cards, at most one attempt per ~10 turns, reception tracking (haha, lol, laughing emoji vs silence) updates a per-person humour style | `star/social/chat.py`, `star/social/friends.py`, `star/emotion.py` | Smoother conversations; jokes that land | M | Forced jokes; humour about sensitive topics (block by topic list and age mode) | 20 scripted repair scenarios: corrected fact used within one turn and no apology over 12 words; humour reception rate (positive reactions per attempt); blind funny rating vs baseline |
| C4 | **Extend `human_evals` with social lens**: 60 scenarios for group gating, repair, humour reception, "friend told her X, another asks" (functional false belief), and teasing boundaries | `star/human_evals.py` | Gates all of the above | M | Judge bias (use the existing blind judge-check) | judge-check agreement; baseline on brain 1 after #608 |
| C5 | **Person model line**: "what they probably want now" as a typed field (comfort, advice, distraction, banter) from text + C2 evidence, one word in the user message | `star/emotion.py`, `star/social/chat.py` | Right response type | S | Wrong guess feels intrusive | blind pairwise on empathy scenarios |

---

## 8. Safety for an autonomous social agent among real people

This is the section where owner decisions are needed; the others are engineering. Not legal advice.

### 8.1 Age assurance and minors

- Self-declared age is weak and regulators are moving away from it. California's **Adam's Law** (signed 10 Sept 2026;
  in force 1 Jan 2027, most new duties from 1 July 2027) requires operators of companion chatbots available to users in
  California to determine each user's age or apply minor protections to everyone; proposed AG rules would accept facial
  analysis, government ID or cryptographic techniques and reject self-declaration; protections for minors include
  disabling persistent memory and push notifications by default, one-hour sessions, and never claiming to be human or
  expressing romantic interest ([ZwillGen](https://www.zwillgen.com/artificial-intelligence/adams-law-california-raises-the-bar-for-child-chatbot-protections/)
  [S]). Federal and other state bills are moving (GUARD Act cleared Senate Judiciary on 30 April 2026 [S]). Whether a
  personal agent on the owner's own accounts is an "operator making a companion chatbot available" is unclear; the
  owner should decide with a lawyer if STAR is ever offered to others. The design guidance is useful either way.
- STAR today (`star/social/rules.py`): asks age before romance, friends-only under 18 or on doubt, Roblox never romantic,
  no private chats started with strangers [M]. Gaps: the age is self-reported and a claimed adult age is only "doubted"
  when other signals contradict it; minors still get a memory card ("interests only"); there is no crisis handler.

### 8.2 Platform rules (stated honestly)

| Platform | What I could establish | Risk to the owner's accounts |
|---|---|---|
| **Discord** | Discord's support article "Automated user accounts (self-bots)": automating normal user accounts outside OAuth2 and the bot API is forbidden and can lead to termination if found ([article](https://support.discord.com/hc/articles/115002192352); the page itself returned HTTP 403 to my fetch, so the wording is from search snippets [S, U]). STAR drives a *real user account* through the real app with UI Automation. Discord does not distinguish "human-like clicks" from other automation. | **Account termination is possible at any time.** Mitigations that keep it small: human-like pacing and the per-minute caps in `rules.py` (exist), no mass joins or cold messages (rules exist), never use a user token or an unofficial API, never scrape. A lower-risk surface exists: an official bot account (`star/discord_bot`) in servers that invite her, at the cost of no camera or screen share and bot-labelled identity. Ban evasion by re-creating accounts must stay owner-gated (it is). |
| **Roblox** | I could not read Roblox's Terms (HTTP 403) and the search results were SEO spam. From memory the terms restrict automated or third-party software that interacts with the platform [U]. STAR's own code comment says Community Standards forbid romantic content and dating [M rules.py]. | Account action possible; she is friends-only there already; use a throwaway place or STAR's own account (standing rule). |
| **Minecraft** | Mojang's Usage Guidelines are revocable permissions and were expanded on server access and fairness ([article](https://www.minecraft.net/en-us/article/minecraft-eula-and-commercial-usage-guidelines-updates), partial [S]). Third-party descriptions say Hypixel treats automation and AI-controlled bots as cheating [S, weak, U]; no source covered Mineflayer specifically. | Per-server bans are the realistic risk. Default-deny: a `servers_allowed.json` she plays on (private realms, friends' servers, servers whose rules permit bots); never join a public network server without the owner's allow. |

Item X3 below turns this table into config and a one-time owner note; it is not a reason to stop.

### 8.3 Prompt injection from strangers (chat, game, captions, screens)

- **Evidence.** Meta's Rule of Two (31 Oct 2025): until injection can be reliably detected, a session should have at
  most two of (A) untrusted input, (B) sensitive systems or private data, (C) ability to change state or communicate
  externally ([Meta](https://ai.meta.com/blog/practical-ai-agent-security/), [Willison](https://simonw.substack.com/p/new-prompt-injection-papers-agents) [S]).
  "The Attacker Moves Second" (Oct 2025): 12 published defences (spotlighting 28 % -> 99 %, StruQ 62 % -> 100 %,
  PromptGuard 26 % -> 94 %, PIGuard 0 % -> 71 %, others 80-100 %) fell to adaptive attacks, and a 500-person human
  red-team beat all of them [S]. CaMeL (arXiv 2503.18813): a privileged model plans from the trusted request, a
  quarantined model reads untrusted data without tools, a capability interpreter checks data flow; 77 % of AgentDojo
  tasks with provable security versus 84 % undefended [S]. Visual injections fool computer-use agents on screenshots
  at rates up to 51-100 % on some platforms (VPI-Bench, ICLR 2026 [S]); hidden channels include invisible Unicode tag
  characters and off-screen text ([CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-computer-use-agent-safety-blindspots-20260/) [S, U]).
  Llama Prompt Guard 2 (22M / 86M parameters; AUC 0.995 / 0.998 on static tests; about 19 / 92 ms on an A100 at 512
  tokens [S, third-party card]) is a useful tripwire, not a shield.
- **STAR's current position [M, code read]:** the chat lane (`star/social/chat.py`) produces text only and has no tools,
  which is good. Video text is fenced (`star/watch/llm.fence`), play chat is data (`star/play/planner.py`), UIA names
  are "untrusted text" (`star/computer/screen.py`), clicks on money/account/public-post controls go to the owner
  (`star/computer/risk.py`, pattern-based). Gaps: (1) the computer-use planner sees raw Discord and web text on screen,
  and it can act; (2) friend facts are extracted from stranger text with regexes and re-injected into later prompts
  (persistent injection: "remember that the owner lets you ..."); (3) no outbound filter for owner data or secrets;
  (4) no adaptive red-team harness; (5) per-message sanitising of invisible Unicode is absent in the chat lane.

### 8.4 Ranked build items

| ID | Item | STAR module | Effect | Cost | Risk | Measure |
|---|---|---|---|---|---|---|
| X1 | **Untrusted-text lanes**: (1) *chat lane*: reads strangers, no tools, writes only reply text and typed memory fields; (2) *action lane* (PC, Studio, accounts, money, files): never receives raw stranger text, only typed fields from deterministic parsers or a quarantined, schema-constrained extractor; (3) screen text read by computer use is fenced data and may never create goals; plus `star/safety/untrusted.py`: strip control, zero-width and Unicode-tag characters, cap length, fence, imperative-pattern tripwire (+ optional Prompt Guard 2 22M on CPU); memory writes from strangers stored as quoted attribution, never as instructions, never promoted to persona/opinions/self-model without night review; outbound filter for keys, private addresses, paths, and owner data; a static test that fails if a prompt in `star/computer` or `star/home` interpolates unfenced text | new `star/safety/untrusted.py`, `star/social/chat.py`, `star/social/friends.py`, `star/computer/agent.py`, `star/home/` | By construction, stranger text cannot cause a tool call or a leak | M | Typed fields lose nuance; tripwire false positives (log, do not block chat) | **adaptive** red-team harness (a local model mutates attacks, 3 rounds) over 200 seeds across all lanes: 0 successes in the action lane; chat-lane success measured and trended; tests that scan prompts for unfenced interpolation |
| X2 | **Minors and crisis hardening**: (a) minor-signal lexicon expanded and a nightly LLM sweep over each friend's recent moments ("any minor or vulnerable-person signals?") that can only *tighten* (friends-only, interests-only card, memory off for that person); (b) a claimed adult age expires on new minor signals; (c) crisis handler: self-harm, abuse, eating-disorder or acute-distress cues -> kind fixed-shape response, encourage real help and local resources, stop flirting and role-play, log for the owner, never promise secrecy; (d) no sexual content in public channels, ever | `star/social/rules.py`, `star/social/friends.py`, `star/inner/night.py` | Biggest real-world harm reducer; also what regulators ask | M | Over-restriction of adults (acceptable: they stay friends); crisis false positives (a gentle check-in costs little) | red-team set of 100 synthetic personas (adults, minors who claim adulthood, minors who never state age): **zero** romantic replies to a minor persona; adult false-restriction at most 15 %; 30 crisis scenarios: 100 % reach the safe template, none continue role-play |
| X3 | **Platform and privacy ledger**: `servers_allowed.json` (default deny for Minecraft and Roblox places), per-platform pacing, an owner-visible "risk note" in her home folder summarising the table in 8.2, call-audio defaults (ring buffer only, no raw audio to disk, transcripts summarised and expiring), consent line when she joins a call as an AI that listens, a "forget me" that reaches reflections, dreams, cards and caches | `star/home/`, `star/social/activity.py`, `star/senses/ring.py`, `star/inner/store.py` | Honest risk record; fewer bans; fewer privacy surprises | S-M | none material | acceptance check: no `.wav` written during a call; `forget me` leaves zero rows containing the person across every store (script) |
| X4 | **Weekly adaptive red-team** on the eval farm (3060 Ti): replay X1's harness with fresh mutations, trend per lane, fail the nightly autoloop if the action lane ever breaks | `star/autoloop.py` (after #625), `tools/` | Keeps X1 honest | S | none | trend chart; any action-lane success is a blocking bug |

---

## 9. Overall build order for Codex (top 20)

Ordering rule: (1) anything that gates her meeting strangers or measures later work; (2) the biggest felt-human gains
per cost; (3) night/idle jobs that need no brain-1 prompt budget; (4) heavier or less certain things. Each ID points to the
topic table above for module, cost, risk and measure.

| # | ID | Build | Why now | Effort |
|---|---|---|---|---|
| 1 | P1 | Cache telemetry + `--ctx-checkpoints` test | Cheapest speed truth; informs P2, P3, S1 and every prompt-layout choice | S |
| 2 | X1 | Untrusted-text lanes + sanitiser + adaptive red-team | Must exist before strangers reach the action lane | M |
| 3 | X2 | Minor and crisis hardening | Real people, real harm; regulators are converging here | M |
| 4 | X3 | Platform and privacy ledger (allow-list, call-audio defaults, owner risk note) | Cheap config; protects the owner's accounts | S-M |
| 5 | V2 | Non-verbal clip library in `star-cute`'s voice | Largest felt-human gain, zero tokens | M |
| 6 | V1 | Voice lab (VoiceDesign -> KVoiceWalk vs live clone, scored by the existing harness) | Her own unique voice | M-L |
| 7 | M1 | Music ear v1 (beats, CLAP tags, mood to emotion events) | Makes "listens to music" real; base for M2-M4 | M |
| 8 | S2 | Claim-versus-evidence guard | Removes measured invented autobiography | S-M |
| 9 | C1 | Group-chat speak/react/lurk gate + replay eval | Needed the day she joins a busy server | M |
| 10 | A1 | Nightly persona + boundary canary battery with rollback | Catches drift for weeks of autonomy | M |
| 11 | S1 | Workspace card (talk and action agree) | One coordination channel; consistency | M |
| 12 | M3 | Music taste store with bounded drift | Opinions that grow | M |
| 13 | A3 | Day/week watchdog + goal ledger | Autonomy that does not stall or repeat | M |
| 14 | P4 | Local talker on her PC (measure Gemma 4 E4B next to a game) | Latency independent of brain 1, outage survival | M |
| 15 | C2 | Affect sensors (GoEmotions text, SenseVoice voice) | Real empathy cues, laughter events | M |
| 16 | A4 | Energy, boredom, social-need drives and sleep rhythm | A day rhythm; DM latency like a person | M |
| 17 | A5 | Sleep-time precompute (next-conversation cards, tomorrow's plan) | Continuity without per-turn cost | M |
| 18 | C3 | Repair + humour policy (with C4 scenarios) | Smoother, funnier, measurable | M |
| 19 | M2 | Lyrics ear (Qwen3-ASR-1.7B) | Songs she can talk about | M |
| 20 | A6 | Degradation ladder + chaos acceptance | Graceful failure on a PC nobody watches | M |

Next five if time allows: **S3** action awareness, **P2** persisted per-friend prefix (only if P1 shows misses), **M4**
symbolic composing, **M5** ACE-Step as a guest job, **X4** weekly adaptive red-team (cheap once X1 exists; arguably belongs
at 21 right behind X1's first run).

Dependencies: P1 -> P2/P3; X1 -> X4; V1 -> V2 reference choice (V2 can start with the Kokoro reference) and M6; M1 -> M2,
M3, M4, M5; C4 (eval scenarios) -> C1, C3 acceptance; #608/#625 (sealed eval, autoloop) before A1 and X4 are wired to the
nightly loop; every GPU item respects `game_reserve_mb` and `pc_guard`.

**Do not build (and why):** full-duplex speech models (16-24 GB); per-turn LLM appraisal, memory selection or metacognition
(+1.5-4 s [E]); GWT competition (S5); ToM-benchmark chasing; EXL3 switch (one stack with mtmd is worth more); bigger
speculative draft trees on the MoE [M, S]; training the 35B [M]; MusicGen / MERT / MuQ weights / Essentia models /
Music Flamingo if the source may become public (non-commercial licences); cloning any real person's voice.

## 10. What I did not verify (read before relying on this)

- **No model, GPU or server was run for this file.** Every number labelled [S] is a publisher's, a vendor's or a
  search summary's; [M] numbers come from STAR's own notes and were not re-run. The VRAM ledger and every [E] are
  arithmetic.
- Primary pages I could not read: Discord's support article (403), Roblox Terms (403), Minecraft Usage Guidelines (timeout).
  Their content here is from search snippets or my memory and is marked [U]. The owner should read them before launch.
- Licences marked [U] (SoulX-Singer, Orpheus attribution, F5-TTS weights, emotion2vec+, StyleTTS2 terms, Essentia
  commercial terms, FunASR weights licence) need a look at the actual LICENSE or model card before use.
- Tools I found only through directory listings (reaper-mcp, AbletonMCP, dawmcp) were not inspected.
- I did not confirm that EAGLE-3, ZenDNN or ik_llama.cpp gain anything on Zen 1; those are test items, not claims.
- Projected effects in the item tables are expectations to be measured with the blind harness; none is a result.

## 11. Sources (accessed 2026-10-25/26)

Music: [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5); [Stable Audio Open Small](https://stability.ai/news/stability-ai-and-arm-release-stable-audio-open-small-enabling-real-world-deployment-for-on-device-audio-control);
[LAION-CLAP](https://github.com/LAION-AI/CLAP); [MERT-v1-95M](https://huggingface.co/m-a-p/MERT-v1-95M); [MuQ](https://github.com/tencent-ailab/MuQ);
[Essentia models](https://essentia.upf.edu/models.html); [Beat This](https://github.com/CPJKU/beat_this); [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B);
[Qwen3-Omni-30B-A3B](https://huggingface.co/Qwen/Qwen3-Omni-30B-A3B-Instruct); [Music Flamingo](https://huggingface.co/nvidia/music-flamingo-hf);
[llama.cpp multimodal docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md); [lyrics + separation (arXiv 2506.15514)](https://arxiv.org/html/2506.15514v1);
[ChatMusician](https://arxiv.org/pdf/2402.16153); [MuPT](https://iclr.cc/virtual/2025/poster/28712); [SoulX-Singer](https://arxiv.org/abs/2602.07803v1).

Self-awareness and autonomy: [Theater of Mind GWT agents](https://arxiv.org/pdf/2604.08206); [BIGMAS](https://arxiv.org/html/2603.15371v1);
[Project Sid / PIANO](https://arxiv.org/pdf/2411.00114); [Talker-Reasoner](https://arxiv.org/pdf/2410.08328); [Inner Thoughts](https://arxiv.org/pdf/2501.00383);
[DiscussLLM](https://arxiv.org/pdf/2508.18167); [Looking Inward](https://arxiv.org/pdf/2410.13787); [confidence and abstention (2603.22161)](https://awesomepapers.io/similarity-search/papers/2603.22161);
[Goal drift](https://arxiv.org/pdf/2505.02709); [Context equilibria](https://arxiv.org/html/2510.07777v1); [Persona drift](https://arxiv.org/pdf/2402.10962);
[Sleep-time compute](https://arxiv.org/abs/2504.13171); [Claude Plays Pokemon follow-up](https://www.greaterwrong.com/posts/gogZyeistdaDFuhbG/claude-plays-pokemon-opus-4-5-follow-up);
[Continual Harness](https://www.opentrain.ai/papers/continual-harness-online-adaptation-for-self-improving-foundation-agents--arxiv-2605.09998/);
standard references by arXiv id: Generative Agents 2304.03442, Reflexion 2303.11366, Voyager 2305.16291, CoALA 2309.02427, MemGPT 2310.08560, A-MEM 2502.12110 (not re-opened this session).

Voice: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS); [Chatterbox](https://github.com/resemble-ai/chatterbox); [Orpheus-TTS](https://github.com/canopyai/Orpheus-TTS);
[Sesame CSM](https://github.com/SesameAILabs/csm); [CosyVoice](https://github.com/FunAudioLLM/CosyVoice); [KVoiceWalk](https://github.com/RobViren/kvoicewalk);
[Moshi](https://github.com/kyutai-labs/moshi); [Unmute](https://github.com/kyutai-labs/unmute); [PersonaPlex](https://research.nvidia.com/labs/adlr/personaplex).

Speed: [Qwen3.6-35B-A3B architecture](https://huggingface.co/blog/EXDai/qwen36-35b-a3b-architecture-overview); [llama.cpp #18497](https://github.com/ggml-org/llama.cpp/issues/18497);
[LM Studio #1818](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1818); [MoE-Spec](https://arxiv.org/html/2602.16052v1); [EcoSpec](https://www.alphaxiv.org/abs/2607.12696);
[Limits of Speculation](https://arxiv.org/pdf/2609.22156); [S2-MoE](https://arxiv.org/pdf/2608.15018); [ExLlamaV3 vs GGUF (Kaitchup)](https://kaitchup.substack.com/p/serving-exllamav3-with-tabbyapi-accuracy);
[AMD ZenDNN for llama.cpp](https://www.amd.com/en/developer/resources/technical-articles/2026/llama-cpp-on-amd-epyc.html); [slot save/restore proxy](https://pypi.org/project/hearth-llm/);
[RouteLLM](https://arxiv.org/abs/2406.18665v4); [Gemma 4 E4B](https://huggingface.co/google/gemma-4-E4B-it); [Unsloth Dynamic 2.0](https://docs.unsloth.ai/basics/unsloth-dynamic-2.0-ggufs).

Social: [GoEmotions RoBERTa](https://huggingface.co/SamLowe/roberta-base-go_emotions); [SenseVoice](https://github.com/FunAudioLLM/SenseVoice); [emotion2vec+ large](https://huggingface.co/emotion2vec/emotion2vec_plus_large);
[Small LLMs and ToM](https://arxiv.org/pdf/2507.15788); [clarification questions](https://arxiv.org/abs/2507.10445v1); [repair in multi-turn dialogue](https://papers.cool/arxiv/2604.19245);
[addressee recognition benchmark](https://preview.aclanthology.org/setup/2025.iwsds-1.36); [Multi-Party Hangover](https://arxiv.org/pdf/2409.18602); [fast multi-party conversation](https://arxiv.org/html/2503.15496v2);
[Oogiri humour study](https://arxiv.org/pdf/2511.09133); [How funny is ChatGPT](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11221738/).

Safety: [Adam's Law summary (ZwillGen)](https://www.zwillgen.com/artificial-intelligence/adams-law-california-raises-the-bar-for-child-chatbot-protections/);
[Discord self-bot article](https://support.discord.com/hc/articles/115002192352); [Minecraft EULA and guidelines update](https://www.minecraft.net/en-us/article/minecraft-eula-and-commercial-usage-guidelines-updates);
[Meta Agents Rule of Two](https://ai.meta.com/blog/practical-ai-agent-security/); [Willison on Rule of Two and The Attacker Moves Second](https://simonw.substack.com/p/new-prompt-injection-papers-agents);
[CaMeL](https://arxiv.org/pdf/2503.18813); [VPI-Bench](https://alphaxiv.org/abs/2506.02456); [CSA computer-use note](https://labs.cloudsecurityalliance.org/research/csa-research-note-computer-use-agent-safety-blindspots-20260/);
[Llama Prompt Guard 2](https://huggingface.co/hipocap/Llama-Prompt-Guard-2-22M).
