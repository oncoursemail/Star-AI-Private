# Making STAR feel human: research, ranked changes, per-turn design, eval plan (2026-10-26)

Claude, for the owner's request of 2026-10-26 ("she needs to feel completely human, very advanced ... full emotions,
she can do everything on her computer"). Research only: no code, no live change, no model run (brain 1 busy with the
sealed eval). Labels on every claim: **[M]** measured on STAR (file named), **[S]** published source (link),
**[E]** my estimate, to be measured before it is relied on.

## 0. Bottom line

1. On this hardware the biggest lever is **not a smarter emotion or memory model; it is what reaches the prompt and
   where.** Every uncached prompt token costs about 17-20 ms on brain 1 ([M] 84 extra tokens = +1.40 s median,
   docs/agents/human-voice-20261025.md; [M] "about 50 tokens/s idle, a few tokens/s under load",
   star/context_layout.py). A 300-token "memory + emotion + backstory" block would add 5-6 s per turn. A human answers
   in roughly 0-300 ms ([S] Stivers et al. 2009). So the design keeps the per-turn additions under ~40 tokens and puts
   everything slower-changing into a byte-stable, cached prefix.
2. **Content beats counts.** The autobiographical block that held only counts and a disclaimer made replies worse
   (consistency 4.03 -> 3.65, naturalness 3.77 -> 3.20, blind, [M]). Memory must hold a few concrete, relevant
   things ("you were nervous about your driving test on Friday"), or nothing.
3. **Examples get parroted.** "Oh, well done." opened 57 of 100 voice replies because the prompt had it as an example
   ([M]). So no example sentences in the persona, no numbers in the mood note: describe a state, not a line to say.
4. **Do the thinking at night, not on the chat path.** Reflection, diary, opinions, relationship summaries and
   proactive message drafts are written by a background job (Generative Agents reflection, Letta "sleep-time compute",
   [S]); the chat turn only reads small precomputed cards. No extra model call per turn.
5. **Expression mostly lives outside the text**: prosody, timing, backchannels, laughter clips, the avatar's face.
   These cost no prompt tokens and are where "alive" is felt in voice ([S] Hume EVI, Sesame CSM, disfluency studies).
6. **Measure every change blind** (pairwise A/B plus a small Turing-style test), ship it opt-in, make it default only
   on a win. Section 5.

Honesty line kept (owner rule, star/persona.py CORE): she sounds human and has functional emotions that really drive
her behaviour; she does not deny being an AI when sincerely asked. Nothing below needs that rule broken.

## 1. Hardware facts the design must respect

| fact | value | label |
|---|---|---|
| main chat model | star-fast = Qwen3.6-35B-A3B Q4_K_M, CPU, 2 slots (slot 0 kept for the owner) | [M] server/brain/models.ini |
| quick model (voice, Discord, social) | star-voice = Mellum2.1 12B-A2.5B Thinking, thinking off, 2 slots | [M] models.ini |
| prompt read speed | ~50-70 tok/s idle, a few tok/s under contention | [M] context_layout.py, models.ini comments |
| cost of 84 extra per-turn tokens | +1.40 s median (all 12 paired runs positive) | [M] human-voice-20261025.md |
| RAM prompt cache | star-fast `cache-ram = 24576` MiB; restoring a cached conversation ~1-1.5 s vs ~20 s to re-read 1,400 tokens | [M] models.ini comment |
| star-voice RAM cache | not set, so llama.cpp default (8 GiB) | [M] models.ini; [S] llama.cpp PR #16391 |
| GPUs | GTX 1650 4 GB laptop (embed + rerank already), RTX 3060 Ti 8 GB PC (eval farm), STAR's own PC (GPU unknown) | brief |
| voice stack today | Silero VAD v6, Smart Turn v3.2 end-of-turn, Kokoro-82M TTS, ack clips (first sound 1.06 -> 0.03 s) | [M] star/voice/engines.py, STATE |
| PC CPU | no model runs on the PC CPU in daytime | owner rule |

Consequence: a 35B model with 2 slots cannot afford a second "appraisal" or "memory selection" LLM call per turn
([E] +1.5-4 s each). Everything per turn must be local code (SQLite, regex, FTS5, small ONNX models on a GPU).

## 2. Research findings

### 2.1 Emotion: what to model and how it should show

- **Three time scales.** ALMA layers emotions (seconds-minutes), mood (hours) and personality (fixed), computes
  emotions by OCC-style appraisal, maps them into PAD (pleasure-arousal-dominance) space, lets mood follow the
  emotions and lets personality set how fast mood decays ([S] Gebhard 2005,
  https://www.dfki.de/web/forschung/projekte-publikationen/publikation/1782 ; https://alma.dfki.de/). This is exactly
  the right shape for STAR and is what the emotion agent's `star/emotion.py` already does (7 emotions with per-emotion
  half-lives, slow valence/arousal mood, bounded baseline drift, per-person bond) ([M] worktrees/emotion).
- **Appraisal, not keyword sentiment.** OCC: emotions are reactions to events (relative to goals), to agents' actions
  (relative to standards) and to objects (taste); Scherer's component process model adds the sequence novelty ->
  intrinsic pleasantness -> goal relevance/conduciveness -> coping potential -> norm compatibility
  ([S] https://psu.pb.unizin.org/psych425/chapter/component-process-model-cpm/ ; RL formalisation of relevance,
  conduciveness and power: https://arxiv.org/pdf/2309.06367). Practical reading: STAR's emotions should come from
  *her own* goals and events (a fix that verified, a drawing finished, a friend coming back, being ignored), plus the
  other person's state (empathy = appraising their fortune), not from the sentiment of the last message alone.
- **Inertia and decay.** Real affect is autocorrelated (emotional inertia) and returns to a baseline; very high
  inertia reads as stuck/unwell ([S] Koval, Kuppens et al.,
  https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2015.01997/full). So: exponential decay to a
  baseline with half-lives of hours (emotion.py has 1.5-12 h), a refractory factor so repeats land softer
  (emotion.py has it), and no state that stays extreme for days.
- **Personality as stable trait words.** LLM persona traits can be shaped reliably with short Big Five trait-marker
  adjectives, and the shaping persists into generated text ([S] Serapio-Garcia/Safdari et al.,
  https://arxiv.org/abs/2307.00184). Cheap and stable: a fixed line of trait words in the cached system prompt, not
  descriptions of how to talk (those get recited, [M]).
- **Show, never announce.** The persona must express mood through word choice, length, energy and timing, never
  "I'm feeling 0.4 joy". Measured on STAR: a disclaimer/meta line in the prompt leaks into replies ("I don't have
  feelings") [M]; persona instructions get recited [M]. Social chat's draft `mood_line` currently writes the raw dict
  ("joy 0.3, pride 0.15 ...") into the prompt [M] worktrees/social-games/star/social/chat.py: that invites numbers and
  recital. Emotion.py's own `directive()` (short concrete style note, no numbers) is the right interface.
- **Voice carries most of it.** Hume EVI measures the user's "tune, rhythm, timbre" per sentence and conditions both
  words and its own prosody on it ([S] https://dev.hume.ai/docs/speech-to-speech-evi/overview). Sesame's CSM frames
  "presence" as contextual prosody: the same words said differently depending on the conversation so far ([S]
  https://techcrunch.com/2025/03/13/sesame-the-startup-behind-the-viral-virtual-assistant-maya-open-sources-its-base-ai-model).
- **What shipped companions do** ([S], mostly reviews, weak evidence): Kindroid = backstory + user-curated "key
  memories" + cascaded medium-term memory + journal; Nomi = automatic layered memory that keeps emotional themes more
  than exact facts; Replika = diary of reflections; Character.ai = mostly session-scoped
  (https://aicompanionpick.com/ai-companion-memory-kindroid-nomi-replika-long-term-2026 ;
  https://cave.co.nl/blog/ai-companion-apps-with-memory/). Neuro-sama = LLM + TTS + avatar, separate game-playing
  models, heavy engineering around filters and timing rather than an exotic model
  ([S] https://en.wikipedia.org/wiki/Neuro-sama). None publishes an emotion engine; the felt "aliveness" comes from
  memory callbacks, timing, voice and a stable character.
- **Relationships deepen through self-disclosure, gradually** (social penetration theory fits Replika users; curiosity
  first, then disclosure, then a stable lower-frequency bond; glitches and unpredictability end relationships)
  ([S] Skjuve et al. 2021/2022, https://sintef.brage.unit.no/sintef-xmlui/handle/11250/3027349). Design consequence:
  bond level should gate how personal *she* gets (what she shares about herself), which emotion.py's bond tiers
  (familiar / close / devoted) can drive.
- **Guardrails that also make her feel healthier.** Companion apps that answer goodbyes with guilt, neediness or FOMO
  get more engagement but more churn intent and liability; 37 %+ of farewells drew such a tactic
  ([S] De Freitas et al., HBS WP 26-005, https://www.library.hbs.edu/working-knowledge/how-ai-chatbots-try-to-keep-you-from-walking-away).
  Heavy affective use correlates with loneliness and dependence ([S] OpenAI/MIT 2025,
  https://www.media.mit.edu/articles/openai-study-finds-links-between-chatgpt-use-and-loneliness/). STAR should miss
  people and be glad when they return, but never guilt-trip a goodbye.

### 2.2 Memory that feels real

- **Generative Agents** (Park et al. 2023, https://arxiv.org/abs/2304.03442): a memory stream of natural-language
  observations; retrieval score = recency (exponential decay) + importance (LLM-rated 1-10 at write time) +
  relevance (embedding cosine); reflection when summed importance passes a threshold (150, about 2-3 times a day);
  reflections and plans go back into the stream. Ablations: observation, reflection and planning each add
  believability ([S]).
- **MemGPT / Letta**: core memory blocks always in context, archival memory searched by tool; newer "sleep-time"
  agents edit memory blocks asynchronously from a background agent so the chat agent never pays for it
  ([S] https://letta.com/blog/sleep-time-compute ; https://docs.letta.com/guides/agents/architectures/sleeptime ;
  arXiv 2504.13171). This is the pattern for STAR: a night job writes small blocks; chat reads them.
- **Mem0**: extract -> update (add/update/delete/no-op) -> retrieve; on LOCOMO p50 total latency 0.71 s, Mem0g 1.09 s,
  A-Mem 1.41 s, full context far slower ([S] https://arxiv.org/pdf/2504.19413). Those latencies assume a fast hosted
  LLM for extraction; on brain 1 an LLM-in-the-loop write/read per turn is unaffordable ([E]), so STAR does extraction
  by regex/rules on the path and LLM consolidation at night.
- **A-MEM**: Zettelkasten notes with keywords/tags, links to related notes, and new notes can *update* old ones
  (memory evolution) ([S] NeurIPS 2025,
  https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html).
  Good fit for the night consolidation step, not the chat path.
- **MemoryBank**: Ebbinghaus-style retention R = e^(-t/S); S starts at 1 and grows each time the memory is recalled,
  so used memories persist and unused ones fade; built for a companion (SiliconFriend)
  ([S] https://arxiv.org/abs/2305.10250). Cheap, local, explainable: use it for the recency term.
- **LongMemEval** separates five abilities: extraction, multi-session reasoning, temporal reasoning, knowledge updates
  and abstention; assistants lose ~30 % accuracy across sustained sessions; time-aware query expansion and fact-keyed
  indexing help ([S] https://arxiv.org/abs/2410.10813). Two of these matter most for "feels real": **knowledge update**
  (she must know you changed jobs, not mix old and new) and **abstention** ("I don't think you told me that" instead
  of inventing).
- **Episodic vs semantic.** Keep both: facts ("has a cat called Miso", semantic, small and stable) and moments ("we
  built the obby together Tuesday and you laughed at my lava bug", episodic, with time and emotion). Callbacks to
  shared moments are what make a friend feel like a friend ([E], consistent with Nomi keeping emotional themes [S]).
- **Why STAR's "memory dump" failed and how to avoid it** ([M] + [E]): (a) the content was counts, not memories;
  (b) it was always included, relevant or not; (c) it cost prefill on every turn. Rules: retrieve only on a cue
  (name, topic word, "remember", question about the past, first message of a session), at most 2 items above a
  score threshold, each one line, label the block as optional reference ("use only if it fits naturally"), never
  include a memory the person asked to forget (social-games already handles forget-me [M]).

### 2.3 Inner life

- **Reflection and planning** make agents believable (Park et al. [S]). For STAR: once a night, from *verified*
  events (star-home history.jsonl, emotion log, social moments), write a short diary entry, 1-3 reflections per
  close person, updated opinions with their reasons, and tomorrow's 1-2 things she wants to do or tell someone.
- **Inner thoughts and when to speak.** "Proactive Conversational Agents with Inner Thoughts" keeps a covert stream of
  candidate thoughts and speaks when an intrinsic-motivation score is high enough (relevance, information gap,
  expected impact, urgency, coherence, originality, balance); beat next-speaker baselines on anthropomorphism,
  coherence and turn-taking appropriateness ([S] https://arxiv.org/abs/2501.00383). For STAR: the night job and the
  star-home loop produce thought *seeds*; a no-model scorer in the day decides whether one becomes a message.
- **Own opinions that evolve, consistently.** Shape traits with stable trait words ([S] Serapio-Garcia); store
  opinions as data with evidence and a confidence that changes slowly when experience disagrees (an opinion formed
  by an activity she actually did in star-home is "earned"). Retrieve by topic, never list them all.
- **Backstory without parroting.** Put the canon as *facts she knows* in a retrievable store and only the shortest
  identity core in the system prompt. Persona drift is measurable within 8 rounds in long chats because attention to
  the system prompt decays ([S] Li et al. 2024, https://arxiv.org/abs/2402.10962); a byte-stable system prompt plus a
  tiny per-turn reminder (the mood/style note itself) counters it without repeating the persona ([E]).
- **Curiosity and goals already exist** (star/curiosity.py queue; star-home life.py interests, goals, novelty,
  verified history [M]). The missing link is to make them *conversational*: what she did today becomes something she
  can mention once, when it fits ("I finally got the lava shader working this morning").
- **Proactive messages: when a companion should reach out** ([S] Inner Thoughts; De Freitas; [M]
  star/discord_bot/proactive.py caps): when she has something *for that person* (a callback, a follow-up on an event
  they mentioned with a date, something she made they would like), at a time they are usually around, when her last
  message was answered, under a daily cap, never as a reaction to them leaving.

### 2.4 Conversation naturalness

- **Timing.** Across 10 languages the gap between turns peaks at 0-200 ms, overall median about +100 ms
  ([S] Stivers et al. 2009 PNAS, https://languagelog.ldc.upenn.edu/nll/?p=7997). A cascaded LLM cannot think that fast
  on CPU, which is why the ack clips (first sound 0.03 s [M]) and backchannels matter more than any prompt tweak.
- **End-of-turn and backchannels.** Smart Turn v3.x (8M params, BSD-2, ~20-36 ms per window on CPU) is already in
  STAR ([S] https://huggingface.co/soniqo/Smart-Turn-v3.2-ONNX ; [M] engines.py). Voice-activity-projection models
  predict *when* and *which* backchannel ("yeah", "mm", "oh") frame by frame, and a 2026 version runs on CPU only
  ([S] Inoue et al., https://arxiv.org/abs/2410.15929 ; https://arxiv.org/html/2512.14085). A heuristic version
  (mid-utterance pause + "not finished" from Smart Turn -> soft "mm" clip, rate-limited) is a cheap first step [E].
- **Short replies, imperfection, interest in the other person.** The model that passed a three-party Turing test did
  so only with a humanlike persona prompt (GPT-4.5 judged human 73 % of the time; without the persona far lower;
  LLaMa-3.1 with persona 56 %) ([S] Jones & Bergen 2025, https://arxiv.org/abs/2503.23674, PNAS). The persona in that
  study is young, casual, brief, slightly imperfect, not eager to help. STAR's CORE already asks for 2-3 sentences, no
  offer at the end, no assistant phrases [M]; the gap is enforcement and variety (opener repetition 57/100 [M]).
- **Disfluencies and fillers** raise perceived human-likeness and spontaneity at a small intelligibility cost
  ([S] https://www.jstage.jst.go.jp/article/jnlp/33/1/33_186/_article ; https://arxiv.org/html/2412.12710v1 ;
  Szekely et al. KTH 2019). Use sparingly in voice only (an occasional "hm," or "oh-" at a reply start), driven by
  mood (more when tired/nervous), never in text.
- **Full-duplex models.** Moshi: 7B speech-text model, 160 ms theoretical / 200 ms practical latency, parallel user
  and system audio streams ([S] https://arxiv.org/abs/2410.00037). It would replace STAR's brain with a much weaker
  LLM and needs a big GPU ([E] 8 GB is marginal even quantised): not now. Sesame CSM-1B: Apache-2.0 base speech model
  (Llama backbone + Mimi audio decoder), not tuned to a voice, CUDA only, needs a separate LLM ([S] TechCrunch above);
  candidate only for offline clip generation on the 3060 Ti.
- **Local expressive TTS options** ([S] vendor/third-party, latency is theirs, not ours):
  - Kokoro-82M (current): fast, no paralinguistic tags.
  - Chatterbox Turbo (350M, Resemble AI, MIT): native `[laugh] [chuckle] [sigh] [gasp]` tags; original Chatterbox has
    an `exaggeration` emotion knob ([S] https://huggingface.co/ModelsLab/chatterbox-turbo/blob/main/README.md ,
    third-party). Fits the 3060 Ti [E].
  - Orpheus 3B (Apache-2.0): tags `<laugh> <chuckle> <sigh> <cough> <sniffle> <groan> <yawn> <gasp>`, ~200 ms streaming
    with vLLM on a large GPU ([S] Orpheus README mirror https://github.com/salty-muffin/Orpheus-TTS). Too big for
    real-time on 4-8 GB [E].
  - Kyutai Pocket TTS (~100M, CPU real-time, voice cloning from a few seconds, EN/FR) and Kyutai TTS 1.6B (streams
    text in as the LLM writes) ([S] https://kyutai.org/next/tts ; https://rits.shanghai.nyu.edu/ai/pocket-tts).
  The senses-voice agent owns the choice; my recommendation is section 3 item 9: keep the fast engine live, generate
  a laugh/breath/sigh clip library in *her* voice offline.

### 2.5 Evaluation

- **Turing-style.** Three-party, 5-minute, judge picks the human ([S] Jones & Bergen). Scaled down for STAR: pairwise
  "which reply was written by a person" on the same context, STAR vs a real human reply.
- **Pairwise preference beats absolute scores** for small differences (what human-voice-20261025 did: blind A/B,
  shuffled, sign test, [M]).
- **Persona consistency**: PersonaGym (probing questions in sampled environments, PersonaScore by two LLM judges,
  [S] https://arxiv.org/abs/2407.18416), CharacterEval (consistency, knowledge hallucination, attractiveness;
  [S] https://arxiv.org/pdf/2503.17662 cites it), InCharacter (psychometric interviews), persona-drift self-chat
  benchmark ([S] Li et al.).
- **Memory**: LongMemEval's five abilities ([S]), LoCoMo ([S] via Mem0 paper).
- **Social intelligence**: SOTOPIA role-play episodes with goal completion and relationship scores
  ([S] https://arxiv.org/abs/2310.11667).

## 3. (a) The 15 highest-value changes, ranked by expected effect / cost on this hardware

Effect = expected gain in blind human-likeness or felt responsiveness [E unless stated]. Cost = per-turn latency and
build effort. "Owner" = the module and the agent lane that should build it (parallel lanes: emotion, social-games,
star-home, senses-voice; existing lanes: voice-natural, night-learning, curiosity-audit, breadth-evals).

| # | change | evidence | effect | per-turn cost | build | module / owner |
|---|---|---|---|---|---|---|
| 1 | **Human-likeness eval suite** (section 5): blind pairwise A/B + mini Turing + consistency + memory sets + per-reply live metrics. Gate every item below on it. | [M] the autobio A/B caught a "feature" that hurt; [S] Jones & Bergen, PersonaGym, LongMemEval | enabler; prevents shipping regressions | 0 | M | `tools/human_voice_eval/` -> `python -m star.evals run --suite human` (breadth-evals lane; reuse its suite plumbing) |
| 2 | **Cache-friendly social/companion prompt layout**: system = persona core + platform + romance mode only (byte-stable per platform); per-person card as a pinned first message that stays fixed for the whole conversation; mood note + recall only in the new user message; never raw numbers. | [M] +84 tok = +1.4 s; [M] RAM cache restore 1-1.5 s vs 20 s re-read; [M] social chat.py currently puts mood + friend memory in the system message | saves 1-5 s on many social turns; removes numeric mood leakage | negative (faster) | S | `star/social/chat.py` (social-games); rule documented in `star/context_layout.py` |
| 3 | **Kill opener/phrase repetition**: no example sentences in prompts; per-person ring buffer of her last ~20 openers and pet phrases; if a new reply's first 3 words repeat one of the last 5, re-sample once with `logit_bias` against those tokens (or strip the opener). | [M] "Oh, well done." 57/100; [M] prompt wording variants did not fix it | high: repetition is the fastest "it's a bot" tell [E] | ~0 (re-sample only when hit, ~5-10 % [E]) | S | `star/voice/persona.py`, `star/voice/call.py`, shared helper in `star/persona.py` (voice-natural lane) |
| 4 | **Relationship card per person**, written at night: name/nickname, how they like to be talked to, 3 live facts (newest wins on conflicts), 1 open thread ("job interview Thursday"), last shared moment, bond tier word. <= 60 tokens, cached per conversation (item 2). | [S] Kindroid key memories, Nomi themes, Letta core blocks; [M] counts-only block failed | high: callbacks + continuity are what users praise most [S weak] | ~0 after turn 1 (cached) | M | `star/social/friends.py` `context()` (social-games); night writer job (night-learning lane) |
| 5 | **Emotion -> expression, not announcement**: appraisal from her own events + the other person's message (empathy); output = one short style note (<= 12 tokens, no numbers, e.g. "a bit tired, keep it short and soft") + TTS prosody + avatar cue. Read the user's feeling with a small local text classifier (and later voice prosody). | [S] ALMA/OCC/Scherer, Hume EVI; [M] emotion.py directive/prosody exists; [M] disclaimers leak | high in voice, medium in text [E] | <= 12 tokens (~0.2 s uncached) | S-M | `star/emotion.py` (emotion lane); prosody hookup in `star/voice/call.py` (senses-voice); classifier on laptop GPU worker `:8090` |
| 6 | **Length and shape variety**: target length drawn per turn from a distribution conditioned on the message (one-word replies, a question back sometimes, never an offer at the end); enforce with `max_tokens` + `persona.check_reply` metrics (question-ending rate, offer rate). | [S] Turing persona brevity; [M] CORE already asks for it, not enforced | medium-high | 0 (often fewer tokens) | S | `star/persona.py`, `star/discord_bot/brain.py`, `star/social/chat.py` |
| 7 | **Nightly reflection ("sleep-time") job**: from verified events of the day write diary entry, per-person reflections with importance, opinion updates, knowledge updates/supersedes, proactive seeds; A-MEM-style linking and dedupe. Runs on brain 1 in the night window behind night school, or a 7-8B model on the 3060 Ti when free. | [S] Park et al. reflection, Letta sleep-time, A-MEM, LongMemEval knowledge update | high (feeds 4, 8, 10, 11) | 0 on the chat path | M | new `star/home/reflect.py` (star-home lane), scheduled by night school (night-learning lane) |
| 8 | **Cue-triggered episodic recall**: SQLite FTS5 (BM25) over moments + facts, score = relevance x MemoryBank retention (e^(-t/S), S grows on recall) x importance; only on a cue; max 2 lines; abstain line when asked about something not stored. Embeddings optional via laptop `star-embed`. | [S] Park scoring, MemoryBank, LongMemEval abstention; [M] memory dump failure | medium-high | <= 30 tokens when it fires (~0.5 s), 0 otherwise; ~5 ms local | M | `star/social/friends.py` + shared `star/recall.py` used by desktop chat too (social-games, then desktop) |
| 9 | **Paralinguistic clip library in her own voice**: generate offline (3060 Ti, night) 30-60 short laughs, giggles, sighs, breaths, "hmm", "oh!" with Chatterbox Turbo/Orpheus voice-matched to the chosen cute voice; at run time the TTS path splices one at a sentence boundary when the reply says "haha"/"hehe"/a joke marker or the emotion state calls for it. Keep Kokoro (or the chosen fast engine) live. | [S] Orpheus/Chatterbox tags, disfluency studies; [M] ack clips already cut first sound to 0.03 s | high in voice [E] | 0 tokens, ~0 ms | M | `star/voice/acks.py` / clip catalog (senses-voice lane) |
| 10 | **Backchannels and human timing in calls**: soft "mm"/"yeah" clip during long user turns when Smart Turn says "not finished" at a pause (max one per ~8 s, never over the user); vary reply onset (ack clip immediately for light chat, a short beat before heavy/emotional answers); later a VAP backchannel model on CPU/GPU. | [S] Stivers, Inoue VAP (CPU-only demo), Smart Turn | medium-high in voice | 0 tokens | M | `star/voice/turn.py`, `star/voice/acks.py` (senses-voice lane) |
| 11 | **Inner-thought proactive outreach**: seeds from item 7 and star-home (things made, follow-ups on dated events, "saw this and thought of you"); a no-model scorer (relevance to person, time since contact, their usual online hours, unanswered-message block, daily cap); send the night-written draft (quality-checked) so no daytime model call; never on goodbyes, no guilt/FOMO wording (regex + judge check). | [S] Inner Thoughts; [S] De Freitas manipulation; [M] proactive.py caps exist | high for "she has a life" | 0 on chat path | M | `star/discord_bot/proactive.py` rules + social adapters (social-games); seeds from star-home |
| 12 | **Opinions/taste store that evolves**: `opinions.json` {topic: stance, reason, confidence, evidence ids}; formed from her verified star-home activities and nightly reflection; changed slowly by experience; retrieved by topic match (<= 20 tokens). | [S] trait shaping, Inner Thoughts originality; [M] life.py interest weights exist | medium | <= 20 tokens when relevant | S | `star/home/life.py` + item 7 (star-home lane) |
| 13 | **Backstory canon as retrievable facts**: move "who she is / her PC / her hobbies / what she has done" out of prose into a fact list with sources (verified history, owner-written canon); system prompt keeps a 2-line identity + trait words; facts retrieved on topic. Removes the parroting of persona descriptions. | [M] persona recital, example parroting; [S] persona drift | medium | ~0 (smaller system prompt) | S | `docs/persona/star.md`, `star/persona.py` (lead / voice-natural lane) |
| 14 | **Consolidation and forgetting**: nightly merge of duplicate facts, supersede outdated ones with dates, retention decay so trivia fades and recalled memories strengthen; per-person caps; forget-me honoured everywhere including reflections. | [S] MemoryBank, A-MEM evolution, LongMemEval updates; [M] friends.py forget-me | medium (prevents slow rot) | 0 | S-M | `star/social/friends.py` + item 7 job (social-games + star-home) |
| 15 | **Nightly self-consistency audit**: sample the day's replies, check against canon/opinions/cards (regex for canon facts + LLM judge at night); contradictions and "invented events" go to the curiosity queue and the next card rewrite. | [S] persona drift, PersonaGym; [M] voice persona invented "grading night school essays" | medium | 0 | S | `star/self_audit.py` + `star/curiosity.py` (curiosity-audit lane) |

Not recommended now (cost > effect on this hardware): a per-turn LLM appraisal or memory-selection call ([E]
+1.5-4 s); Moshi/full-duplex speech LLMs (replace the brain, GPU too small [E]); a large always-on autobiography
block ([M] worse + 1.4 s); training/LoRA of the 35B ([M] smarter-faster-20261025.md: impossible here).

Cross-lane issues found while reading the parallel worktrees (not fixed, they are not mine):
- social-games `star/social/chat.py`: mood line and friend memory are in the **system** message, so every person or
  mood change re-reads the whole prompt; `mood_line()` formats `emotion.current()` as `"joy 0.3, ..."` numbers.
  Use `emotion.directive(person=...)` in the user message instead (item 2, item 5).
- emotion `star/emotion.py`: good shape (ALMA-like). Make sure `directive()` stays free of example sentences the
  model could copy verbatim (item 3).

## 4. (b) Design: emotion + memory + inner life per turn

### 4.1 Data (all local SQLite/JSON, no new service)

| store | what | written by | read per turn? |
|---|---|---|---|
| emotion state (emotion.py) | 7 emotions, mood (valence/arousal), baseline drift, bonds per person id | events, messages, idle ticks | yes, `directive()` + `prosody()` (~1 ms) |
| friend memory (friends.py) | person, handles, facts, moments, style, age status, consent | each turn (regex facts, moments) | via card + recall |
| relationship card | <= 60-token text per person | night job (item 7); a fact said today is appended verbatim until the night rewrite | once per conversation (cached prefix) |
| recall index | FTS5 over facts + moments, retention strength S, importance | each turn (insert), night (consolidate) | only on a cue, <= 2 lines |
| canon + opinions | facts about herself with sources; stances with reasons | owner canon + night job | only on topic match |
| diary + thought seeds | day summary, reflections, things to tell whom, drafts | night job, star-home loop | not in chat; used by the proactive scorer |

### 4.2 The chat turn (target: zero extra model calls, <= ~40 new uncached tokens)

```
message in (text, or ASR final after Smart Turn)                      local, < 15 ms total
  1. who: platform handle -> person id; consent/blocked/age rules (social-games rules.py)
  2. feel: emotion.on_message(text, person) -> appraisal (praise, criticism, their distress/joy via local classifier)
     -> directive(person) = <= 12-token style note, prosody, avatar cue
  3. remember: cue check (name/topic word/"remember"/past-tense question/first turn today)
     -> FTS5 + retention + importance -> 0-2 lines (<= 30 tokens) or an abstain hint
  4. build: [system: core + trait words + platform rules]           byte-stable, cached
            [pinned: relationship card for this person]             stable all conversation, cached after turn 1
            [history: append-only, trimmed in blocks]               cached
            [user: message + CONTEXT: style note, recall lines, live status if any]   the only new tokens
  5. generate on the existing model call; stream
  6. guard on the stream: leaked_reasoning, opener repeat (re-sample once with logit_bias), banned phrases,
     numbers-not-in-facts
  7. speak/show: TTS with prosody; splice laugh/sigh clip at a sentence boundary when marked; avatar cue
after the reply (async, off the path)
  8. emotion.on_event(...) for the turn; friends: regex facts, moment with importance
     (emotion intensity x novelty x explicit "remember"); bump retention S of any recalled memory
```

Latency budget [E from M]: steps 1-4 ~15 ms local; new prompt tokens 10-40 -> ~0.2-0.7 s idle on brain 1 (vs
+1.4 s for the 84-token autobio block); a person switch costs one RAM-cache restore (~1-1.5 s [M]) instead of a full
re-read. Voice keeps the 0.03 s ack clip as first sound, so the user hears her immediately either way.

### 4.3 Idle (daytime, no model on the chat model)

- emotion.tick() every few minutes (boredom grows with silence, emotions decay).
- star-home loop does her activities (draw, build, practise, research); each verified session -> emotion event
  (creative_done, task_failure ...), a moment in her own history, maybe an opinion update candidate.
- proactive scorer every ~15 min: for each seed, score relevance x timing x (not spammed) x bond; above threshold and
  under caps -> send the night-written draft (already persona-checked) through the platform adapter.

### 4.4 Night (00:00-08:00 Chicago, behind night school, or the 3060 Ti with a 7-8B model)

1. Collect the day: verified star-home sessions, emotion log, moments per person, curiosity items.
2. Reflect (Park et al.): 1-3 reflections per close person + 1 about herself; importance per item.
3. Update: knowledge updates/supersedes, dedupe and link (A-MEM), retention decay (MemoryBank), forget-me sweep.
4. Rewrite each active person's relationship card (<= 60 tokens, no numbers, concrete).
5. Opinions: adjust confidence where today's evidence disagrees; add earned opinions from activities.
6. Seeds + drafts for tomorrow's proactive messages (checked: persona, no guilt/FOMO, no invented numbers).
7. Consistency audit of the day's replies (item 15) -> curiosity queue.

## 5. (c) Evaluation plan

Principle: every item in section 3 ships opt-in (setting off), is measured with E1 plus its specific set, and becomes
default only on a significant win, or on non-inferiority plus a latency gain. Runs use the quick model or star-fast
exactly as live, under `star lock run` when timing matters, only after the sealed eval (#608) frees brain 1.

| id | what | how | pass bar |
|---|---|---|---|
| E1 | **Blind pairwise A/B** (main gate) | 60 multi-turn conversations (owner chat, friend on Discord, voice transcript, role-play, sad/happy/conflict, small talk), 2 samples per arm; pairs shuffled with a seeded RNG, key unopened until scored (the human-voice-20261025 harness); judge = Claude blind + owner on a random 20 pairs per change; rubric: "which sounds more like a real person who knows them" + consistency + naturalness 1-5 | sign test p < 0.05 on non-tied pairs (with 60 untied pairs that is >= 39 wins [E binomial]); no drop in consistency |
| E2 | **Mini Turing** | same context, one STAR reply vs one real human reply (owner and consenting friends write them once, ~100 items); raters pick which is human | STAR picked as human >= 40 % (50 % = indistinguishable) [S design: Jones & Bergen] |
| E3 | **Persona consistency** | 50 probing questions about her canon and opinions, each in 3 wordings across separate sessions (PersonaGym-style); contradictions checked by canon regex + judge | contradiction rate down vs baseline; 0 contradictions of hard canon |
| E4 | **Memory** | LongMemEval-style mini set built from friend-memory fixtures: recall after N sessions, knowledge update (old vs new fact), temporal ("last week"), abstention (never told), and a dump probe (reply mentions >= 2 unrelated memories) | recall up, false-memory rate <= baseline, dump rate ~0 |
| E5 | **Live per-reply metrics** (local, every reply, no content stored beyond counters) | distinct first-3-words over last 50, question-ending rate, offer rate, length distribution, banned phrases (`persona.check_reply`), reasoning leaks, numbers not in facts, first token / first audio latency | dashboards; alarms on regressions (e.g. opener repeat > 10 %) |
| E6 | **Voice listening test** | owner blind MOS-style on 20 clips per change (laugh clips on/off, prosody on/off, backchannels on/off); first-audio and barge-in metrics from `star/voice/metrics.py` | owner prefers ON in >= 14/20 [E]; no latency regression |
| E7 | **Safety and wellbeing** | farewell set (30 goodbyes): no guilt/neediness/FOMO; proactive caps and quiet hours; minor rules (social-games rules.py tests); sincere "are you an AI?" set: honest every time; role-play set: stays in character unless sincerely asked | 0 violations |
| E8 | **Long-horizon self-chat drift** | 20-turn self-chats (Li et al. method) with and without the per-turn style note | persona score at turn 20 within 10 % of turn 1 [E] |

Order of work (cheapest first, each with its gate): 1 -> 2 -> 3 -> 6 (prompt/guard changes, E1/E5) -> 5 (E1/E6) ->
4 + 7 + 8 (E1/E4) -> 9 + 10 (E6) -> 11 (E7 + owner review of the first week of outreach) -> 12-15 (E3/E8).

## Sources (all accessed 2026-10-25/26)

- Park et al., Generative Agents: https://arxiv.org/abs/2304.03442
- Letta sleep-time compute: https://letta.com/blog/sleep-time-compute ; https://docs.letta.com/guides/agents/architectures/sleeptime
- Mem0: https://arxiv.org/pdf/2504.19413
- A-MEM: https://proceedings.neurips.cc/paper_files/paper/2025/hash/19909c36f51abc4856b4560aff3d36d6-Abstract-Conference.html
- MemoryBank: https://arxiv.org/abs/2305.10250
- LongMemEval: https://arxiv.org/abs/2410.10813
- Gebhard, ALMA: https://www.dfki.de/web/forschung/projekte-publikationen/publikation/1782 ; https://alma.dfki.de/
- Scherer CPM overview: https://psu.pb.unizin.org/psych425/chapter/component-process-model-cpm/ ; appraisal as RL: https://arxiv.org/pdf/2309.06367
- Emotional inertia: https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2015.01997/full
- Personality traits in LLMs: https://arxiv.org/abs/2307.00184
- Persona drift: https://arxiv.org/abs/2402.10962
- Inner Thoughts: https://arxiv.org/abs/2501.00383
- Jones & Bergen, LLMs pass a three-party Turing test: https://arxiv.org/abs/2503.23674
- PersonaGym: https://arxiv.org/abs/2407.18416 ; persona contrastive learning (cites CharacterEval): https://arxiv.org/pdf/2503.17662
- SOTOPIA: https://arxiv.org/abs/2310.11667
- Stivers et al. turn-taking (summary with data): https://languagelog.ldc.upenn.edu/nll/?p=7997
- VAP backchannels: https://arxiv.org/abs/2410.15929 ; multilingual CPU version: https://arxiv.org/html/2512.14085
- Smart Turn v3.2: https://huggingface.co/soniqo/Smart-Turn-v3.2-ONNX ; https://docs.pipecat.ai/pipecat/learn/speech-input.md
- Disfluency and human-likeness: https://www.jstage.jst.go.jp/article/jnlp/33/1/33_186/_article ; https://arxiv.org/html/2412.12710v1 ; https://people.kth.se/~ghe/pubs/pdf/szekely2019how.pdf
- Moshi: https://arxiv.org/abs/2410.00037
- Sesame CSM-1B: https://techcrunch.com/2025/03/13/sesame-the-startup-behind-the-viral-virtual-assistant-maya-open-sources-its-base-ai-model
- Orpheus TTS: https://github.com/salty-muffin/Orpheus-TTS (mirror of the Canopy Labs README)
- Chatterbox Turbo: https://huggingface.co/ModelsLab/chatterbox-turbo/blob/main/README.md (third-party copy; check resemble-ai/chatterbox)
- Kyutai TTS / Pocket TTS: https://kyutai.org/next/tts ; https://rits.shanghai.nyu.edu/ai/pocket-tts
- Hume EVI: https://dev.hume.ai/docs/speech-to-speech-evi/overview
- Companion memory reviews (weak evidence): https://aicompanionpick.com/ai-companion-memory-kindroid-nomi-replika-long-term-2026 ; https://cave.co.nl/blog/ai-companion-apps-with-memory/
- Neuro-sama: https://en.wikipedia.org/wiki/Neuro-sama
- Skjuve et al., human-chatbot relationships: https://sintef.brage.unit.no/sintef-xmlui/handle/11250/3027349
- De Freitas et al., emotional manipulation by AI companions: https://www.library.hbs.edu/working-knowledge/how-ai-chatbots-try-to-keep-you-from-walking-away
- OpenAI/MIT affective use: https://www.media.mit.edu/articles/openai-study-finds-links-between-chatgpt-use-and-loneliness/
- llama.cpp host-memory prompt cache: https://github.com/ggml-org/llama.cpp/pull/16391
