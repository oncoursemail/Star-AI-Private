# STAR Intelligence — trusted upgrade receipts and a faster, smarter gaming VTuber

Technical research and integration plan — October 29, 2026. Proposed architectures are not demonstrated model intelligence increases, gaming wins or human-quality broadcasts.

## This implementation: independently signed precommit and observation receipts

The new star/upgrade_receipt_host.py component adds an authentication boundary before the existing star/upgrade_evidence_gate.py six-domain candidate evaluation. A coordinator freezes the exact suite, baseline, candidate, scoring rule, case identities, AB/BA presentation order and time window in a canonical manifest. A separately keyed observer then signs each measurement and a SHA-256 digest of independently retained underlying evidence. The verifier checks both signatures, the manifest, unique case/variant and evidence identities, task order, timestamps and experiment binding before forwarding verified fields to the multi-domain upgrade gate.

Rejection conditions include altered result/latency/VRAM, changes in scoring rule or model identity, changed AB/BA order, missing/duplicate observations, reused evidence, observations before the manifest or after its deadline, cross-experiment replay, and a missing or expired manifest. A valid result can be **eligible for owner review** only; it never authorizes automatic deployment, live game input, OBS controls, broadcasting or changes to Star's models. OFF by default.

**The cryptographic limit is essential.** HMAC authenticates the key holder, NOT the truth of a scored event or the actual date a manifest was signed. The independent coordinator and observer must be real host processes, not model-proposed "agents" with shared credentials. Keys must live in protected host secrets (never source code, chat, plugins, traces or GitHub). The coordinator must register the random experiment nonce in a durable append-only ledger before any trials. The observer must independently inspect saved engine, game, speed and stream measurements before signing. The new module does not itself record trials or keep an anti-replay registry across processes.

Integration checklist:
1. Have trusted Core Forge host generate a CSPRNG nonce, register experiment ID in durable storage, freeze the UpgradePlan and AB/BA schedule before execution.
2. Use independent coordinator and outcome-observer secret stores; do not expose signing methods/keys as general model tools.
3. Run exactly the frozen tasks on authorized machines. Save raw evidence privately; store only its hash and metadata in the portable receipt.
4. Verify every host signature and run the existing six-domain compare_upgrade only with authenticated records. Missing or untrusted data means inconclusive.
5. After real holdout wins, offer only a tightly bounded canary for owner review; track regressions and rehearse rollback within Star Core Forge.

Synthetic unit tests prove envelope manipulation is detected; they do not prove independent host processes, real inference acceleration or game mastery.

## Faster and more useful intelligence

The objective should be **completed, independently verified work per second and per watt**, not raw tokens/sec. Split Star's workload into four lanes:
- Reflex: game control, avatar frame motion, audio VAD and interrupt acknowledgement. Bound to short local deadlines. Never await a large LLM.
- Interactive: short chat, real-time game perception and speech chunks; prioritize against OBS and Roblox frame budgets.
- Deliberation: difficult reasoning, game design, Luau analysis, knowledge retrieval, Blender/VFX and planning; run only with explicit resource grants.
- Experiment: self-generated challenges, offline evaluation, multi-agent candidates, rollback, regression and benchmark jobs; aggressively preempt during active gaming.

Route simple verified tasks to a fast model but escalate uncertain, novel or high-consequence tasks. Keep static tool/docs prefixes stable for cache reuse, prune stale visual frames and cap model context. Use load- and deadline-aware GPU/CPU admission; send heavy research to spare hardware without starving a connected speech or game loop. On an 8 GB VRAM RTX 4060, benchmark *actual* VRAM headroom with Roblox, OBS and the avatar running, rather than allocating all memory to an LLM. CPU/RAM offloading can help some setups but can also make p95 latency much worse.

llama.cpp SPEED-Bench records latency, throughput and speculative token acceptance for already-running llama-server instances. Repeat baseline vs speculative configurations under matched categories, concurrency, output limits, prompt caches and real GPU occupancy. Reject changes that only win by shortening answers or dropping requests. Official reference:
https://github.com/ggml-org/llama.cpp/blob/master/tools/server/bench/speed-bench/README.md

Suggested measurements: time to first audible word, completed useful task latency p50/p95/p99, voice interruption acknowledgement, game FPS p1 lows, OBS dropped frames, CPU/RAM pressure, GPU VRAM headroom, error count, rollback rate and heldout correctness. A new model is not "smarter" merely because it streams tokens faster.

## Real autonomous game mastery and polished game creation

GameWorld's 2026 standardized benchmark covers 34 games and 170 verifiable tasks across runner, arcade, platformer, puzzle and simulation environments. It uses internal game-state outcome checks, not only visual impression:
https://gameworld-bench.github.io/

Roblox OpenGameEval, published October 1, 2026, evaluates 84 Studio tasks inside executable stateful sessions, separating inspection from editing and assessing actual game changes:
https://arxiv.org/abs/2610.02563

Proposed Star gameplay loop: observe a permitted game with timestamps; infer goals and uncertainty; issue a bounded authorized action; inspect real post-action state; score an independently verified transition; test alternative tactics on matched seeds; store a scoped evidence-backed skill only after independent validation; test transfer on unseen maps and altered physics. Use low-latency local controllers for frame-sensitive moves rather than LLM token-by-token motor control. Explicitly record game/version, environment seed, objective, failure reason, evidence digest and skill expiry. Never promote successful practice attempts as unseen holdout outcomes.

Create a game mastery ladder: learn controls; finish familiar levels; complete held-out levels under a bounded action/error budget; transfer mechanics to unfamiliar maps; coordinate socially in cooperative modes without inappropriate interruption. Report success and failure rates, not unsupported declarations of expertise.

For creation, require inspection -> semantic geometry/dependency checks -> sandbox change -> engine regression test -> multi-client simulated playthrough -> rendered screenshot inspection -> physical gameplay success -> independent acceptance. Test mispositioned props, clipping, missing walls, texture seams, collision shape, character grip, responsive UI, accessibility, performance and story flow. Reserve blind scenes so Star cannot only memorize its own quality checker.

## A memory system that turns experience into knowledge

WorldMemArena (May 28, 2026) evaluates write-maintain-retrieve-use memory across 400 multimodal multi-session tasks, finding that storing more memories does not guarantee an agent can use them correctly:
https://arxiv.org/abs/2605.29341

Star should store typed facts with source URL or verified engine-evidence digest, timestamp, scope, uncertainty, expiry and supersession history. Use a compact current-game state plus a separate deeper general knowledge store. Detect contradictory, outdated or low-quality facts before using them. A remembered gameplay episode should be based on something Star actually observed or performed, not an invented narrative. Use short, accurately sourced personal-interest and project-history summaries to preserve an endearing, recognizable persona.

Self-practice should challenge her in knowledge sourcing, code and engine changes, math/reasoning, game vision, spatial geometry, music, art, Blender, UI, game mechanics, non-English comprehension, social timing, and error recovery. Separate generated practice tasks from untouched independent confirmation tasks. Measure transfer and calibration: being willing to say "I do not know" matters.

## Natural gaming VTuber — presence, timing, charm, and truthful continuity

A believable streamer needs synchronized attention, interactive timing, game understanding and expressive performance. Model a tiny changing attentional state: concentrating, listening, playing, reacting, joking, explaining, recovering, or idle. Give priority to urgent game inputs during hard moments. Queue nonurgent chat instead of interrupting a critical jump or boss fight. Celebrate verified successes; express frustration gently after genuine failures; laugh when the situation warrants it; remain quiet when nothing calls for commentary. Avoid repetitive canned expressions.

Synchronize her voice, laughter, mouth shapes, blinking, gaze, breathing, body pose and Star's signature flowing twin-tail hair using a common presentation clock. Validate the **recorded OBS output** rather than animation commands or generated speech intentions. Bound visual model sampling and avoid duplicate VLM inferences when the scene is static. Use natural audio turn-taking and false-interruption recovery; voice activity detection alone should not decide that a speaker has completed a thought.

LiveKit documentation describes audio turn detection (including a locally running CPU mini model) and adaptive interruptions:
https://docs.livekit.io/agents/logic/turns/turn-detector/
https://docs.livekit.io/agents/logic/turns/tuning/

VTube Studio offers a user-enabled local WebSocket plugin API for avatar parameters:
https://github.com/DenchiSoft/VTubeStudio

The stream should preserve her own authentic AI identity rather than fake a human biography or conceal that she is AI. Give her believable habits and interests grounded in projects and gaming episodes she truly completed; do not invent romantic relationships, off-stream events or human memories. Respect viewer privacy, consent, retention limits and game platform rules.

## Original experiments worth building next

| Experiment | Build | Independent acceptance |
|---|---|---|
| Causal skill notebook | Hypothesis, paired mechanic trial, scored transition, counterexample and scoped rule. | Skills transfer to unseen levels without raising failures. |
| Stream attention economy | A bounded game/audio/chat scheduling policy based on urgency and model uncertainty. | Lower p95 speech lag while game FPS/OBS quality stays healthy. |
| Grounded personality episodes | Minimal factual memory of verified games and creative work. | Accurate and timely recall, zero fabricated claims in heldout scripts. |
| Frontier gym | Self-generated harder coding, Blender, general knowledge and Roblox challenges. | Independent heldout tasks become more successful, not only practice. |
| Asset QA compiler | Geometry contracts plus render, physics and material checks. | Fewer visible defects in blind game scenes. |
| Compute microscope | End-to-end timing and GPU/CPU/RAM admission traces. | Reproducible useful speedups without quality loss. |
| Counterfactual evaluator | Ask what else could explain a "win"; test alternatives. | Reduced false skill promotions and fewer regressions. |

## Safety, visibility and next milestone

The GitHub repository called Star-AI-Private currently reports **public** visibility. Never upload secrets, real gameplay captures, user identities, private personal memories or unlicensed assets. Draft PR only; no automated merges. Star Core Forge should remain the primary local versioned development and rollback system, with GitHub used as optional review/export.

The next honest milestone is an independent signed six-domain trial using 12+ balanced matched cases per category, *real* game-engine outcomes, actual OBS/voice rendering and measured local model latency, with an owner-reviewed canary and automatic rollback on verified degradation. Until then, this implementation secures the evidence format but does not establish increased neural intelligence, faster generation, autonomous game mastery or natural live broadcasting.
