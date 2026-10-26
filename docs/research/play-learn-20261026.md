# STAR learns games from recorded play: research and design (2026-10-26)

Goal (owner, 10-26): STAR plays games really well and human-like on her own PC (RTX 4060 8 GB), and gets better on
her own. The first game-play wave (`docs/research/game-play-20261026.md`) found that skill from pixels comes from
cloning recorded play, not from prompting. This page covers how to do that on one 8 GB card, how much data it needs,
how to keep it human, and how to measure it. What was built is in `star/play/learn/`.

Labels: **[measured]** = run here by this agent (dev PC, RTX 3060 Ti 8 GB, not STAR's 4060); **[source]** = from the
linked page; **[estimate]** = my reasoning, not measured.

## 1. Findings in six lines

1. **Behaviour cloning (BC) of a small per-game policy is the route that fits.** The CS:GO agent (Pearce & Zhu) is
   an EfficientNet-B0 trunk + ConvLSTM on 280x150 frames at 16 Hz. It matched a casual gamer in deathmatch on easy
   and medium bots and stayed far below a strong player. VPT shows that BC scales with data; Lumine shows that a 7B
   VLM can do it, but needs 4 server GPUs to run.
2. **Data per game: hours, not minutes.** [source] CS:GO: 95 h scraped plus 3.3 h of clean play for one map. VPT's
   inverse-dynamics model was usable at 10 h of labelled play and levelled off near 100 h. Lumine used 1,731 h after
   filtering. [estimate] For one Roblox obby, 2-5 h of the owner's play is a sensible first target. Expect
   casual-human level on that one course, not mastery and not generalisation to other courses.
3. **Model size: ~1 M parameters, not billions.** A 1.29 M-parameter IMPALA CNN on three 128x72 frames runs at
   p50 3.9 ms / p95 6.5 ms per frame in fp16 and peaks at 12.5 MB of VRAM [measured on the 3060 Ti]. That leaves the 4060 to the game and the voice stack. A 7B VLM
   policy (Lumine) does not fit next to them.
4. **Human-like comes from the data, plus a few limits.** A cloned policy inherits human timing, pauses and mistakes.
   The CS:GO agent's map coverage was much closer to humans than the built-in bot's (EMD 0.349 vs 0.643). On top
   of that: sample actions (do not take the argmax), cap mouse speed at the human 99th percentile, enforce a
   minimum key hold, and add no aim assist.
5. **Self-improvement without RL infrastructure: filtered BC.** Keep the episodes that succeeded (obby
   checkpoint, task done), fine-tune on them mixed with human replay, and promote only through an automatic eval
   gate. It is a strong, simple baseline: 71% vs 74-86% for RL on a real-robot benchmark. It sharpens what the
   policy already does sometimes; it does not invent new skills.
6. **Real RL (PPO self-play) and world models (DIAMOND) are out of reach for live games on one PC.** RL needs a
   simulator many times faster than real time. Roblox and Minecraft clients run at real time, and Pokemon-style
   RL burned 50,000 simulated hours. DIAMOND's CS:GO world model is 381 M parameters, took 12 days on an RTX 4090
   and runs at ~10 fps on a 3090. Use them only where a game can be simulated (a Godot or Luau re-implementation
   of a course), not as the default.

## 2. State of the art for learning to play from pixels

| Work | What it is | Numbers | What STAR takes |
|---|---|---|---|
| VPT, OpenAI 2022 [arXiv 2206.11795](https://arxiv.org/abs/2206.11795) ([html](https://arxiv.org/html/2206.11795)) | IDM labels web video with actions, then BC on the labelled video. Mouse and keyboard at 20 Hz; 128x128 input. | [source] 1,962 h of contractor play to train the IDM: 90.6% key accuracy, mouse R² 0.97. Usable from 10 h of IDM data, levelling off near 100 h. 70k h of clean web video labelled. Foundation model ~0.5 B params, about 9 days on 720 V100s. IDM ~0.5 B params, 4 days on 32 A100s. Mouse: 11 foveated bins per axis; 20 buttons. | 20 Hz steps, foveated mouse bins, sampling. An IDM to label YouTube video for a game is a later option once a small IDM can be trained. |
| Counter-Strike BC (Pearce & Zhu) [arXiv 2104.04258](https://arxiv.org/abs/2104.04258) ([html](https://arxiv.org/html/2104.04258)) | Pixels to actions, cloned from scraped deathmatch play plus a little clean play. | [source] 280x150 input at 16 Hz. EfficientNet-B0 (6 stages) + ConvLSTM. Mouse 19x13 bins; keys as sigmoids. Data: 5.5 M frames (95 h) scraped, 3.3 h clean on dust2; 10 minutes on a new map raises it from 0.2-0.5 to 0.7-1.0 KPM. KPM on medium bots: agent 3.72, casual gamer 3.51, strong player 7.80. Only brightness/contrast augmentation, "to keep mouse labels valid". | Architecture class, label layout, augmentation rule, and that "casual human" is the realistic ceiling. |
| Lumine, ByteDance 2025 [arXiv 2511.08892](https://arxiv.org/abs/2511.08892) ([html](https://arxiv.org/html/2511.08892v1)) | Qwen2-VL-7B. 720p frames at 5 Hz; keys in 6 chunks of 33 ms (30 Hz); mouse as dx/dy per 200 ms step. | [source] 2,424 h raw, 1,731 h after removing ~95% of idle and camera-jitter clips; 200 h of instruction data; 15 h of reasoning traces. Pre-training: 5,376-19,008 H100 GPU-hours. First action 113.9 ms on 4x H20 with W8A8, speculative decoding, KV reuse and fused CUDA graphs (25.3x faster than baseline). | Drop most idle steps before training (`keep_idle`). Do not try a 7B VLM policy on the 4060. |
| Gato, DeepMind 2022 [arXiv 2205.06175](https://arxiv.org/abs/2205.06175) | One 1.2 B decoder-only transformer over 604 tasks (Atari, robots, text), trained only by supervised imitation. | [source] Size chosen as "the operating point of model scale that allows real-time control of real-world robots". | A single generalist is a data-centre project. Per-game small policies are the practical form. |
| DIAMOND [arXiv 2405.12399](https://arxiv.org/abs/2405.12399) ([html](https://arxiv.org/html/2405.12399v2)) | Diffusion world model; the agent trains inside it. Also a playable CS:GO "neural game engine". | [source] Atari 100k mean human-normalised score 1.46; each run ~12 GB VRAM and 2.9 days on one RTX 4090; agent ~13 M params. CS:GO model 381 M params, 87 h of training data, 12 days on an RTX 4090, ~10 fps on an RTX 3090. | Not for now: too slow and too big next to a game. A future night-time research option for one game. |
| STEVE-1 [NeurIPS 2023](https://proceedings.neurips.cc/paper_files/paper/2023/hash/dd03f856fc7f2efeec8b1c796284561d-Abstract.html) | Fine-tunes VPT to follow text or visual goals (MineCLIP latents, hindsight relabelling). | [source] About $60 of compute to train. | Goal-conditioning a pretrained policy is cheap. Later: give the slow planner's goal to the policy as an input. |
| ACT (action chunking) [arXiv 2304.13705](https://arxiv.org/abs/2304.13705) | Predicts k future actions per query and blends overlapping chunks (temporal ensembling). | [source] Chunking and ensembling reduce compounding errors and handle non-Markovian demonstrations. | Next step if one-step BC drifts. Not built yet. |
| Filtered BC [Kumar et al. 2022, arXiv 2204.05618](https://arxiv.org/abs/2204.05618); [real-robot stacking, arXiv 2312.11374](https://arxiv.org/abs/2312.11374) | BC on the top-k% of trajectories by return. | [source] On real robots: filtered BC 71% vs single-task RL 74% vs multi-task RL 86%. Kumar et al.: offline RL is better in theory on noisy data, and filtered BC is a strong baseline. | `improve.py` uses it, because a game exposes success but there is no simulator to run RL in. |
| PPO on a live game: Pokemon Red (Whidden) [TechCrunch](https://techcrunch.com/2023/10/18/after-50000-hours-this-ai-can-play-pokemon-red/) | RL with hand-made rewards on an emulator. | [source] More than 50,000 hours of simulated play. | RL needs an emulator or simulator far faster than real time. Not for Roblox or Minecraft clients. |
| Human-like agents [arXiv 2505.20011](https://arxiv.org/abs/2505.20011); 2K BotPrize ([GamesBeat](https://gamesbeat.com/unreal-bots-pass-turing-test/)) | Surveys and contests on human-likeness; industry trains agents on human trajectories for believability. | [source] No agreed formal measure of "humanlike"; judges and Turing-style protocols are the norm. | Measure human-likeness with distribution checks (section 5), not claims. |

## 3. What fits on an 8 GB card in real time

| Choice | Value | Why |
|---|---|---|
| Frame | 128x72 RGB, a stack of 3 frames (synthetic tests use 2) | VPT used 128x128 and CS:GO 280x150. 16:9 at 128x72 keeps the aspect, and a 1280x720 window shrinks by exactly 10x. |
| Encoder | IMPALA CNN (3 stacks of conv + maxpool + 2 residual blocks), widths 16-32-32, then 256 units | [measured] 1,285,564 params at 128x72x9 input; inference p50 3.9 ms, p95 6.5 ms in fp16 on the 3060 Ti; CPU p50 10.5 ms (section 6). |
| Heads | Sigmoid per key and button; softmax over 11 mu-law mouse bins per axis | VPT and CS:GO layout. Bins make the multimodal mouse (stop or flick) learnable with cross-entropy. |
| Training | AdamW 3e-4, cosine, batch 64, fp16 autocast + GradScaler, grad clip 1 | [estimate] Under 1 GB VRAM. Hours of play train in under an hour at night. |
| Augment | Random shift ±4 px (DrQ/RAD) + brightness/contrast ±15% | Shift/crop is the augmentation that helps image-based control most ([DrQ](https://arxiv.org/abs/2004.13649), [RAD](https://arxiv.org/abs/2004.14990), [2305.16379](https://arxiv.org/pdf/2305.16379)); colour jitter is what CS:GO used. No flips: they would swap A/D. |
| Storage | npz shards of 2,000 steps (100 s), uint8 frames, labels as bins | [measured, synthetic] see section 6. A memory-mapped frame cache (`train --cache`) lets hours of play train without holding them in RAM. |

[estimate] The budget on STAR's 4060: the game keeps `game_reserve_mb` (5 GB) and the voice stack takes most of the
rest. A ~1.3 M-param fp16 policy needs ~10-20 MB of VRAM to run, so it fits where a YOLO detector would. Training
runs only when she is not playing.

## 4. Data: how much, what format, how to record it

- **How much.** [source] From the numbers above: a few hours of clean play reached casual-human level on one CS:GO
  map, given 95 h of noisy pretraining. VPT's IDM needed about 10 h minimum and about 100 h to saturate. [estimate]
  For one Roblox obby course (simple controls, one goal): 2-5 h of the owner's play is the first target, plus STAR's
  own successful runs once the policy works at all. For Minecraft through the real client (much broader skills),
  tens of hours per narrow skill. The Mineflayer skill route from the first wave stays the main Minecraft path.
- **Format** (`recorder.py`): per session, `session.json` (spec, who, consent note, markers, stats) plus
  `shard_NNNNN.npz` with frames (N,72,128,3) u8, keys (N,K) u1, buttons (N,B) u1, mouse bins (N,2) u1, raw delta
  (N,2) f4, t (N,) f8, gap (N,) u1.
- **Alignment.** Frame t is stored with the input made after it, during (t, t+1]: the policy learns "what the
  person did after seeing this". A tap shorter than one step still counts.
- **Consent and privacy.** A recording refuses to start without a consent note. It prints `[STAR rec]` lines when it
  starts, every 5 minutes and when it stops. It records only the game window's region and only while that window is
  in front. Only the game's own keys are labelled, and the chat box ("/", Enter or T) pauses recording until it
  closes, so typed text is never stored. STAR's own play is recorded through `SinkTap` (exactly what her actuator
  sent) and `TeeSource` (no second screen grab).
- **Idle.** Steps with no input are kept at 20% by default. Lumine removed ~95% of idle clips, and otherwise
  "stand still" dominates the labels.
- **Split.** Whole sessions go to validation. Neighbouring frames are near copies, so a random split would grade on
  frames the model has practically seen.

## 5. Human-like, not superhuman

- The cloned timing is human, reaction delays included, so no extra reaction delay is added on top. Adding one would
  make her slower than the people she learned from.
- Actions are **sampled** from the predicted probabilities, as VPT does, so she varies the way people do. Temperature
  can be set; it defaults to 1.0. [measured, synthetic] At 1.0 a policy cloned from noisy play also copies the noise
  (18.5% vs 98% at 0.5 on DotGame). Choose the temperature by the eval (0.5-1.0) for each game. Filtered BC also
  removes noise, while keeping human-like variety.
- **Mouse speed is capped** at the 99th percentile per-step movement of the recorded human play, stored in the
  checkpoint. A key or button holds its state for at least 60 ms, the lower end of human tap lengths
  (humanlike.py `tap_s`).
- Mouse moves are spread over each tick with a minimum-jerk profile and fading tremor (humanlike.py), not sent as
  one jump.
- No memory reading, no aim assist, input only into the game window (winput's window check). Roblox's Terms
  restrict automated play; the owner accepted that account risk on 10-26.
- **To measure next** [not built]: compare distributions between her play and the owner's on the same course. That
  means key-hold lengths, mouse speed histograms, reaction time to a checkpoint coming into view, and
  map-coverage EMD (the CS:GO paper's metric). A Turing-style blind check with friends would follow (BotPrize style).

## 6. Measurements this session

All on the dev PC (RTX 3060 Ti 8 GB, Windows 11). Synthetic DotGame only: no real game and no screen recording.

| What | Result |
|---|---|
| Tests | `tests/test_play_learn.py`: 22 passed with torch (train-venv, CPU only), 16.3 s. Without torch: 19 passed, 3 skipped. `tests/test_play.py` still passes. |
| CPU smoke (32x18 frames, 150 noisy demo episodes, 400 steps) | Pipeline end to end in ~60 s at below-normal priority. Base policy 27/40 successes (67.5%). After one filtered-BC round on her own recorded successes, 31/40 (77.5%), promoted by the gate. The 95% intervals overlap (52-80% vs 63-88%), so that is not yet evidence of improvement. The scripted demonstrator itself scored 40/40. |
| Inference latency, roblox_obby net (128x72, stack 3, 1.29 M params), batch 1 | CUDA fp16: p50 3.9 ms, p95 6.5 ms, 12.5 MB peak VRAM (`python -m star.play.learn bench`, n=500). CPU: p50 10.5 ms, p95 25.8 ms. That fits a 20 Hz tick (50 ms) easily. |
| Raw Input (owner recording) | Registered on a message-only window, saw both injected 1-px mouse moves (+1, -1) and stopped cleanly. The keyboard path was not exercised (no keys were injected into the owner's window). |
| GPU synthetic run, 128x72, 02:17Z with the owner idle 357 s (`synth --episodes 600 --self-episodes 400 --steps 3000 --eval-n 200 --device cuda`) | Recorded 600 noisy demo episodes (scripted player, eps 0.5) = 13,355 steps in 5.0 s, 904 KB on disk (synthetic frames compress far better than real ones). Base training: 1.28 M params, 10,138 train / 1,908 val samples, 3,000 steps in 101.7 s with fp16 AMP. Val: key accuracy 0.78, key F1 0.62, mouse bin accuracy 0.72 (0.79 within one bin). Inference p50 4.5 ms, p95 8.0 ms; 214 MB peak VRAM during training. |
| Self-improvement on the same run (200 paired attempts each, same seeds) | Scripted demonstrator 200/200. Base policy at temperature 1.0: **37/200** (18.5%, CI 14-24%); it copies the demonstrator's 50% random actions. After **one filtered-BC round** (13,618 success steps, 1,000 fine-tune steps): **187/200** (93.5%, CI 89-96%), promoted by the gate. Ablation, same 1,000 steps on ALL steps (no filter): 156/200 (78%, CI 72-83%). So filtering beats plain extra training. Ablation, base at temperature 0.5: 196/200 (98%). On noisy demos, the sampling temperature matters as much as the fine-tune. |

## 7. Honest limits

- **No real game was learned in this session**, and no real play was recorded (the brief forbids recording the
  owner's screen here). Every number in section 6 is on a fake game, which says the pipeline works, not that she
  plays any real game well.
- BC gives at best roughly the level of the play it copies. The CS:GO agent reached casual-human level, not expert.
  Filtered BC can sharpen that but cannot discover new skills.
- One-step BC drifts on long tasks (compounding error). Action chunking (ACT) and a recurrent core (CS:GO's
  ConvLSTM) are the known fixes; neither is built yet.
- A policy is tied to one game and its layout. A new obby course needs new data or at least a fine-tune (CS:GO: 10
  minutes on a new map gave 2-3x the zero-shot kill rate, still low).
- The success signal is only as good as the detector: the Roblox checkpoint check is a colour heuristic
  (roblox.py). A wrong colour means wrong "successes" and filtered BC learns the wrong thing. Check the profile on
  screenshots first.
- RawInputSource (owner recording) was checked only with two injected 1-pixel mouse moves. Keyboard capture and
  a full recording session with real play were not run.

## 8. Next steps (in order)

1. On STAR's PC: install torch (CUDA) in her runtime. Tune the obby `ObbyProfile` colours. Record 2-5 h of the owner
   playing one obby: `python -m star.play.learn record --game roblox_obby --who owner --consent "..."`.
2. Night: `python -m star.play.learn train --game roblox_obby --cache`, then an eval of N=20 attempts with
   `session_attempt(reflex_session(...))`, success = checkpoint reached.
3. Then nightly `improve()`: she plays and records herself, runs filtered BC and the eval gate, and the result is
   promoted or rolled back automatically (#562).
4. Let the eval gate also pick the sampling temperature (try 0.5, 0.75, 1.0 per game). Add the human-likeness
   distribution report (section 5), then action chunking if long runs drift.
5. Later: a small IDM trained on her own labelled recordings, to label YouTube runs of the same game (the VPT recipe
   at small scale).
