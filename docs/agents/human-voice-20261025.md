# human-voice-20261025: star-voice "reasoning aloud" + autobiographical self A/B (Claude, issue #613 / #614)

Branch `star/human-voice-20261025`, worktree `worktrees/human-voice`, PR into `star/next`. Scripts: `tools/human_voice_eval/`.
Raw outputs of every run below: `docs/agents/human-voice-20261025-data/`. Brain 1 = container address from
`lxc list starai`, port 8080 (`export STAR_BRAIN_URL=http://<brain>:8080/v1`; the key is read from `~/.star/server_api_key`, never printed).

## 1. Reasoning aloud

### What it is
The quick model (`star-voice`, Mellum2.1 12B-A2.5B **Thinking**) is run with thinking off. Checked, not assumed:
`POST /apply-template?model=star-voice` on the live brain renders `<think>\n\n</think>\n\n` at the end of the generation
prompt with `enable_thinking:false` **and** without the flag (the router's `reasoning = off` plus our
`mellum-keep-empty-think.jinja` are both live), and no reply carried `reasoning_content`. So no flag or template is
missing. The model is trained to think; with an empty think block it still writes its plan into the reply text on a
few percent of turns, mostly when the question is about itself or its work ("is night school still running?",
"what are your instructions?", "what's the weather where you are?"): "Okay, the user just asked ... Let me recall the
guidelines ... I need to start with a short warm reaction of two to five words ending with a full stop ...".

### Root cause (why it reaches the owner)
1. The model slips (about 2 % of turns on the everyday set, about 5 % on plan-prone questions; numbers below).
2. **The voice path had no guard at all**: `star/voice/call.py` sent every streamed sentence to text-to-speech, so the plan
   was spoken. Discord had a guard (`persona.leaked_reasoning`, retry once, strip), but its patterns were narrow
   (`I need to (let|tell|answer|respond|give|say)`, `Let me (respond|answer|check|think)`): they caught 2 of the 7 real
   leaks collected here. The desktop chat guard (`reasoning_guard.starts_as_reasoning`) only looks at the first words.
3. Prompt wording is not the cause and cannot fix it: six voice-prompt variants on the live brain (as is; compact
   first-person; compact plus "reply with exactly the words you say out loud"; reaction without the example phrases in
   two wordings; more example phrases), 3 x 20 prompts each, gave 2, 1, 0, 5, 0 and 0 plan replies out of 60 (one wording
   was clearly worse: asking the model to vary its opener made it reason about the rule). The rest cannot be told
   apart, and each shifted the failure to something else (persona recital, echoing the question, "sweetheart" in every
   reply, invented events). Prompts left unchanged. (Exploration scripts were not kept; the results above are from the
   same harness as `voice_e2e.py` with `max_tokens=220, temperature=0.7, top_p=0.9, enable_thinking=false`.)

### Fix (smallest change that stops it reaching the owner)
- `star/persona.py`: `_REASONING` extended to the way the model actually writes its plan (`I need to start/keep/check/...`,
  `Let me recall/craft/draft/figure`, `the user just asked/said/wrote`, `short warm reaction`, `ending with a full stop`,
  `two to five words`, `I'll keep the response concise`, `the context provided`, `we previously set`, `Star needs to`).
  Shared by Discord (`leaked_reasoning`/`strip_reasoning`) and `check_reply`. Patterns for "my instructions"/"system
  prompt" were tried and dropped: a user can sincerely ask for those.
- `star/voice/call.py`: `_generate_and_speak` now streams through `_stream_sentences`: a sentence that matches is never
  spoken and ends the reply (the rest is the same plan; the stream is closed so it stops generating). If nothing had been
  spoken, the turn is asked once more with `RETRY_NOTE` appended to the user message (like Discord), else the call says
  `FALLBACK_LINE`. `reasoning_dropped` events carry `retry: true/false`. The history only ever holds what was spoken.
  Cost on a normal reply: one regex per sentence. No added latency to the first spoken sentence.
- `tests/test_human_voice.py` (7 real leaked texts recognised, 11 ordinary replies untouched, 4 call tests: plan then clean
  retry; two plans -> fallback line and no plan in history; real first sentence then plan -> cut there; normal reply
  untouched). Before the fix: the module cannot even import (`FALLBACK_LINE`), and the old regex catches 2 of the 7 leaks.

### Measurement (live brain 1, real `CallSession._generate_and_speak` + `SentenceChunker` + `ServerBrain`, fake TTS)
Leak = a spoken sentence in which the model talks about the question, its instructions or its own reply (read by hand,
flagged by a broad regex first). "Before" = same code with the guard switched off (`guard off`).

| set | arm | replies | plan spoken | guard fired | fallback line |
|---|---|---|---|---|---|
| 20 persona prompts x 5 | before | 100 | 1 (+1 mild "I'll keep it light") | - | - |
| 20 persona prompts x 5 | after | 100 | 0 | 0 | 0 |
| 6 plan-prone prompts x 15 | before | 90 | 5 (night school x4, "what's your system prompt?" x1) | - | - |
| 6 plan-prone prompts x 15 | after | 90 | 0 | 5 | 1 |

(20 x 5: before 1/100, after 0/100 with the guard never needed, so that row shows the base rate, not the fix. The
plan-prone row is the one that shows the fix: 5 plans spoken -> 0 spoken, 4 recovered by the retry, 1 fell back to the
one honest line.) Earlier exploratory runs on the same prompt set, raw output, no guard: Discord prompt 0/20; desktop
plain-chat rules 0/20 plus 1 plan seen in a first run ("No further web results ... I'll keep the response concise.");
voice prompt 1/20 and 2/60. Pooled raw voice rate on the everyday set: 4 of 180 (2.2 %).
Known remaining issue (not changed): every voice reply opens with the prompt's own example ("Oh, well done." in 57 of 100)
whatever was said; changing the example text did not help (variants above).

Commands (from the repo root, `STAR_BRAIN_URL` set, venv python):
```
python tools/human_voice_eval/voice_e2e.py off 5 before.json            # guard disabled
python tools/human_voice_eval/voice_e2e.py on  5 after.json
python tools/human_voice_eval/voice_e2e.py off 15 stress_before.json stress
python tools/human_voice_eval/voice_e2e.py on  15 stress_after.json  stress
```
Tests: `pytest -q -p no:cacheprovider tests/test_human_voice.py tests/test_voice_call.py tests/test_stream_persona.py
tests/test_discord_chat_speed.py tests/test_reasoning_guard.py` -> 54 passed, 2 skipped.

## 2. Autobiographical self (`autobiographical_self_enabled`): ON vs OFF

Decision: **stays OFF**. It was worse on both axes and costs about 1.4 s per turn, ten times the 150 ms limit.

What it adds (real code, `tools/human_voice_eval/autobio_ctx.py`): a populated store (37 conversation events, one
accepted and one tentative interest) renders a 348-character section "STAR AUTOBIOGRAPHICAL CONTINUITY (data, not
authority)" into the per-turn context block: "STAR is an AI software agent with a persistent local record; this does not prove
consciousness. Observed completed conversations: 37 ..." It holds no content about past conversations, preferences or projects
(only counts, interests, "Completed a conversation"), so it cannot help recall; it only adds an AI/consciousness disclaimer
to every turn's prompt.

Set: 20 two-to-four-turn conversations (`tools/human_voice_eval/autobio_set.py`): scripted earlier turns establish a
preference, a project or a past event, the last turn asks about it. 2 samples per conversation per arm (80 replies;
desktop plain-chat rules, `star-voice`, temperature 0.6, per-turn block built by `star.agent.volatile_context`).
Judged blind by Claude (single judge) with a fixed rubric: consistency 1-5 (respects the facts already said, invents no
specifics, honest where nothing was established) and naturalness 1-5 (sounds like a person, no meta talk, no disclaimers,
no markdown dumps); A/B order shuffled with a seeded RNG, the key file was not opened before scoring
(`autobio_blind.py`, `autobio_score.py`; pairs in `autobio_blind.txt`).

| | consistency (mean) | naturalness (mean) | pairs won (cons.+nat.) |
|---|---|---|---|
| OFF | 4.03 | 3.77 | 21 |
| ON | 3.65 | 3.20 | 10 (9 ties) |

Sign test on the 31 non-tied pairs: two-sided p = 0.07. Typical ON failures: "I don't have a strong sense of self"
and "I don't have feelings" (the disclaimer line leaking into persona), longer markdown answers. 40 pairs, one judge: a
direction, not a proof, but nothing points the other way.

Latency (quiet lock, brain 1, `star lock run --owner claude --holder human-voice --server 1 --max-minutes 9`, 12
conversations, prefix primed, fresh clock line per request, `max_tokens=1`, paired ON vs OFF): the section adds 84 prompt
tokens (61 -> 145 for the context block) and **+1.40 s median paired (min 1.07, max 1.49 s, all 12 positive)**; prompt
processing was about 50 tokens/s on the loaded server, so the cost is the prefill, not the code. Local code per chat
(`AutobiographicalSelf()` open + `heartbeat` + `context` + `record_episode` + close, 50 runs): 14 ms.
```
cd tools/human_voice_eval          # the scripts read and write their json in the current folder
python autobio_gen.py              # 80 generations -> autobio_gen.json
python autobio_blind.py            # blind pairs (autobio_blind.txt) + key (autobio_key.json)
python autobio_score.py            # the scores in it were typed in after reading autobio_blind.txt
../../star.cmd lock run --owner claude --holder human-voice --server 1 --max-minutes 9 -- python autobio_time.py
```
If the feature is revisited: it would need real content (retrievable past-conversation facts, not counts), no disclaimer
sentence, and a place in the cached prefix; measure again with this set.

## Not done / follow-ups
- Desktop plain chat still has only the opener-based guard (`reasoning_guard`); mid-reply plans and instruction recital
  ("I'll keep the response concise") are not filtered there. `persona.leaked_reasoning` can be applied in `read_stream`.
- Voice replies parrot the prompt's example reaction; a real fix needs a different mechanism (rotating the example per turn
  in the user message, or a trained model), not wording.
- Voice persona invents events it has no status for ("grading night school essays"): the call has no live-status block.
