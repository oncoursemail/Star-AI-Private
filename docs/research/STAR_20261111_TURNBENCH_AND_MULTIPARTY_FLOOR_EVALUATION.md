# STAR research: turn timing, multiparty social floor, and live streaming evaluation

**Research date:** 2026-11-11  
**Implementation branch:** `feat/multiparty-floor-control-20261110-auto11`  
**Scope:** offline evaluation only; no audio capture, microphone, diarization provider, TTS, avatar, OBS, game input, permission, or production setting is changed.

## Executive finding

A natural AI streamer must solve at least four different problems:

1. **Acoustic turn boundary:** is a speaker still talking, finishing, or interrupting?
2. **Social floor:** who is being addressed, and is STAR expected to respond?
3. **Response policy:** should STAR speak, listen, backchannel nonverbally, remain silent, or yield?
4. **Physical execution:** did audio actually start, stop, or yield on time?

These are not interchangeable. A high-quality voice activity detector can still interrupt a backchannel, answer a side conversation, miss a group handoff, or generate a response that begins too late.

STAR already has a session-scoped multiparty floor gate and a separate authenticated-owner interruption path. This pass adds an offline evaluator for the **decision layer**, so thresholds and host adapters can be compared on held-out whole conversations rather than tuned by intuition.

The evaluator is deliberately not an audio model, a diarizer, or a live integration. It scores locally produced, human-annotated labels and final decisions; actual audio-to-action performance still needs an independent host rehearsal.

## 1. Fresh benchmark research

### TurnBench: end-of-turn and interruption timing

TurnBench is a public benchmark for end-of-turn (EOT) and interruption (INT) detection in recorded two-channel human dialogue.

The published corpus contains:
- 154 dyadic conversations;
- approximately 30 hours of audio;
- 106 speakers;
- six conversation types;
- triple annotation, with consensus ground truth.

It scores event recall, false-positive rate and detection latency. The benchmark's release analysis notes that backchannel-dense speech is a particular source of interruption false positives. Its leaderboard snapshot dated 2026-11-08 listed 26 rows, with the leading external submission reporting 0.978 EOT recall, 0.077 false-positive rate and 298 ms median latency. Those are benchmark-specific external results, not STAR measurements or guaranteed targets.

Sources:
- Repository and submission protocol: https://github.com/SesameAILabs/turnbench
- Leaderboard and benchmark description: https://turnbench.sesame.com/

**How STAR should use it:** evaluate the acoustic EOT/INT detector independently using the official scorer and causality rules. Do not treat this dyadic benchmark as a complete test of group conversation or addressee awareness. The datasets are gated; do not vendor audio or labels into STAR's public repository.

### MP-Bench: multi-party participation

MP-Bench evaluates voice agents as active participants in multi-party conversations, covering turn-taking awareness, response appropriateness and comprehension. Its evaluation of 12 agents reports that real-time agents reached at most 22% on multi-party comprehension and near-chance performance on multi-party turn-taking.

Source: https://aclanthology.org/2026.findings-emnlp.1437/

**How STAR should use it:** evaluate addressee awareness, side conversations, group-addressed turns, backchannels, overlapping speakers and whether a response is socially appropriate. A speaker slot only distinguishes a voice within the current session; it is not a real-world identity.

### Model Interruption Bench: detection is not action

The EMNLP 2026 Model Interruption Bench studies content-aware interruption while a person is speaking. It reports a substantial gap: the strongest evaluated systems detected 59–67% of errors in turn-based conditions but achieved below 10% mid-speech true positives when required to interrupt in real time.

Source: https://aclanthology.org/2026.emnlp-main.2349/

**How STAR should use it:** keep separate timestamps for detection, decision, playback cancellation, physical silence and any correction. A model saying it noticed an event is not evidence that the audio pipeline yielded on time.

### Full-duplex execution and conversational history

Full-duplex systems must preserve what the listener actually heard after interruption. When playback is cut, the host should record only the audible portion in the conversation state; generated-but-never-played audio must not silently become shared conversational history.

Reference:
https://docs.livekit.io/agents/logic/turns/

## 2. New implementation: offline multiparty floor evaluator

Added:
- `benchmarks/stream_multiparty_floor_eval.py`
- `tests/test_stream_multiparty_floor_eval.py`

Run:

```bash
python -m benchmarks.stream_multiparty_floor_eval --cases ./private-evals/floor-decisions.jsonl
python -m benchmarks.stream_multiparty_floor_eval --cases ./private-evals/floor-decisions.jsonl --out ./reports/floor-eval.json
```

### Dataset contract

The evaluator accepts strict JSONL records with:
- opaque event and conversation IDs;
- a `calibration` or `holdout` split;
- human gold action and host-predicted action;
- gold and predicted addressee classes;
- gold and predicted speech-act classes;
- active speaker count;
- receipt age and decision latency;
- predicted response probability.

It rejects unknown fields, duplicate JSON keys, non-finite numbers, invalid categories, duplicate event IDs, oversized inputs and any conversation appearing in both splits. It requires both calibration and holdout data.

The schema intentionally has no transcript, audio path, speaker name, account ID, voiceprint or viewer identity field. Reports contain aggregate metrics only and never echo event/conversation IDs.

### Metrics

The report separates calibration from conversation-disjoint holdout and includes:
- action accuracy and macro-F1;
- per-action precision, recall and F1;
- response precision/recall/F1;
- false-response rate;
- responses to group-addressed turns;
- responses to side conversations;
- spoken responses to gold backchannels;
- responses during overlapping speech;
- addressee and speech-act accuracy;
- conversation-macro response F1;
- response-probability Brier score and 10-bin ECE;
- p50/p95 decision latency, response-decision latency and receipt age;
- a bounded action confusion matrix.

The evaluator does not tune policy thresholds or make live decisions. Use calibration conversations to select a candidate policy, freeze that policy, then report the holdout split once. Keep complete conversations—not random utterances—disjoint to avoid leakage from recurring context and speaker behavior.

## 3. Correct two-level evaluation protocol

Do not combine all streaming metrics into one "human-like" score.

| Layer | Evaluation | Required evidence |
|---|---|---|
| VAD / acoustic endpoint | TurnBench-compatible EOT/INT | event recall, false positives, median/p95 latency |
| Diarization | Session-local speaker slots | overlap/split/merge errors; no identity claims |
| Addressee + speech act | MP-Bench-like annotated conversations | addressee accuracy, act accuracy, confidence calibration |
| Floor policy | New STAR evaluator | response precision/recall, group/side/backchannel false responses |
| TTS scheduling | Host playback receipts | first audible PCM, cancellation and queue-flush timing |
| Avatar embodiment | Avatar state receipts | listening mouth-neutrality, lip-sync, yield-to-listen timing |
| Full session | Private game + OBS rehearsal | game frame-time p10, OBS drops, audio underruns, response p50/p95 |

A model's predicted confidence is not a calibrated probability until tested on a representative, held-out distribution. Recalibrate separately for owner speech, guests, overlap, background speech, different microphones and different noise conditions. Never infer owner identity from voice similarity; owner interruption must remain on its authenticated host path.

## 4. Recommended natural streaming state machine

Use explicit, cancellable states:

```text
LISTENING
   -> SPEECH_CANDIDATE
   -> TURN_COMPLETE
   -> ADDRESSEE_RESOLVED
   -> FLOOR_DECISION
       -> RESPOND -> TTS_QUEUED -> SPEAKING
       -> BACKCHANNEL -> NONSPOKEN_AVATAR_CUE
       -> LISTEN / SILENCE
       -> HOLD (uncertain, overlap, stale or interrupted)
   -> YIELDING (authenticated owner interruption)
   -> LISTENING
```

Important invariants:
- VAD silence is not semantic end-of-turn by itself.
- A completed utterance is not necessarily addressed to STAR.
- A backchannel is not automatically a request for spoken output.
- Group address should default to listening unless the policy has evidence that STAR has the floor.
- Overlap, stale timestamps and uncertain addressee should suppress optional speech.
- Owner interruption uses the authenticated owner path, not guest diarization.
- When speech is cancelled, flush the physical output queue and discard unheard audio from conversation history.
- Avatar listening, thinking, speaking, laughing and yielding states must be driven by actual playback and floor receipts, not merely generated text.

Natural streaming includes pauses, listening and silence. Optimize for appropriate participation and continuity, not maximum talk time. STAR remains transparently identified as AI.

## 5. Inference and workload implications

Current llama.cpp MoE cache guidance provides a machine-specific tuning script that runs multiple cache-size and CPU-share configurations, measures host/device behavior, and recommends a setting from measured speeds. The documentation explicitly says the best CPU share depends on the machine, model, cache size and memory pinning.

Source: https://github.com/ggml-org/llama.cpp/blob/master/docs/moe-cache.md

For STAR's constrained 8 GB GPU, do not copy MoE cache, speculative decoding, KV quantization or layer-offload values from another system. Benchmark:
- identical prompts and model/build;
- prompt-cache hit/miss and reused-token counts;
- TTFT, inter-token latency and end-to-end p50/p95;
- output quality on paired tasks;
- RAM, VRAM and PCIe transfer;
- game frame-time p10, OBS drops and audio underruns;
- first-audible-PCM latency under concurrent game + OBS + voice + avatar load.

A faster isolated model configuration is a regression if it stutters the game or delays audible speech. Background research and asset generation must yield to live conversation, owner interruption and physical audio stop.

## 6. Game mastery and creation

Continue extending the existing game systems rather than creating a duplicate skill bank:
- `star/gameplay_skill_bank.py`
- `star/game_skill_memory.py`
- `star/game_transfer_eval.py`

For Roblox Studio, inspect relevant hierarchy, scripts, properties and visual state before mutation. OpenGameEval's stateful Studio tasks show why inspection and actual play sessions matter; GameDevBench's 333 Godot tasks show that visual/graphics tasks remain difficult and that image/video feedback improves results.

Sources:
- https://github.com/Roblox/open-game-eval
- https://github.com/waynchi/gamedevbench

Keep a closed loop:
`observe -> plan -> isolated edit -> launch -> playtest -> visual inspection -> repair -> retest -> unseen holdout`.

Measure live-clock performance and transfer to unfamiliar maps/mechanics. Compilation or one successful run is not proof of game mastery.

## 7. General knowledge and durable learning

Score knowledge by domain and application, not a single trivia score:
- factual accuracy and source provenance;
- temporal updates and contradiction handling;
- calibrated uncertainty and abstention;
- reasoning and tool-use correctness;
- application to new projects and unfamiliar games;
- retention and transfer after a delay;
- resistance to stale or contaminated memory.

Store evidence with source, observation time, project/model version, test result and freshness. Historical success must be revalidated when the underlying code, model or game version changes.

## 8. Roblox permission boundary

Roblox Studio MCP permissions are per game and per person. The Safe, Balanced, Full and Custom access levels differ materially; Full access can include publishing, monetization, player consequences and secrets. Studio enforces the configured scopes and the client cannot grant itself new permissions.

Source: https://create.roblox.com/docs/studio/mcp-open-cloud

Keep STAR's development environment on Safe/custom least privilege, use disposable test places, and require owner review for publishing, live data writes, monetization, asset uploads and actions affecting players.

## Acceptance still required

This PR adds an offline decision evaluator and tests only. Before claiming more natural or faster streaming:
1. Run the evaluator on owner-consented, independently annotated conversations.
2. Keep whole conversations disjoint between calibration and holdout.
3. Score the acoustic EOT/INT model separately with TurnBench's official protocol.
4. Run MP-Bench-like multi-party scenarios for addressee and response appropriateness.
5. Record actual TTS queue, first audible PCM, interruption-to-silence and avatar-state receipts.
6. Run a private 30–60 minute game + OBS + TTS + avatar session on the target Windows PC.
7. Publish p50/p95 latency, false-response rates, overlap behavior, game frame-time, OBS drops, audio underruns, CPU/RAM/GPU/VRAM and task success.

No audio dataset, private viewer content, model, microphone, avatar, OBS session, gameplay input or production permission was changed in this research pass.

## 9. Fresh game-creation benchmark update

The official GameDevBench repository now publishes a 333-task Godot 4.4.1 benchmark and updated leaderboard entries. At the time of this review it lists Claude Opus 5.5 (xhigh) at 70.6%, GPT-6.1 Sol (xhigh) at 70.0%, and GPT-6 Astra (High) at 68.8% (229/333) using runtime video and strict confinement. These are external benchmark results, not STAR scores, and model/harness/effort settings differ.

The benchmark's authors report that performance drops from 51.4% on gameplay-oriented tasks to 33.0% on 2D graphics tasks. Their image/video feedback mechanism improved GPT-5.4 from 41.1% to 52.0% in the reported setup. The repository requires Godot 4.4.1 for comparable official runs and uses strict solver isolation by default.

Sources:
- Official repository and current results: https://github.com/waynchi/gamedevbench
- Paper: https://arxiv.org/abs/2602.11103

**STAR implication:** prioritize a visual feedback loop for Creator Brain. After every material UI, animation, shader, sprite or scene change, capture the actual running game, compare it with the reference/acceptance criteria, inspect logs and input behavior, then repair and retest. Keep exact engine/build versions in each result receipt. Use isolated workspaces and never let a benchmark agent read its own hidden ground-truth files. A compile-only result is not a visual quality score.
