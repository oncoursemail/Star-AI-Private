# STAR operational self-awareness and capability-directed learning

**Owner request:** Give STAR a useful awareness of her own tools, current limits, research resources and opportunities to improve.

**Date:** 2026-10-25
**Status:** Isolated **draft stacked PR** based on Resource Atlas #587 (feat/universal-resource-atlas-20261025). Not merged, released, deployed, or turned on in the installed STAR application.

## Definition: operational metacognition, not consciousness

This is an operational self-model: a read-only, host-observed picture of features STAR may use, what still needs to be tested, and which concrete experiments would answer those uncertainties. It does not create sentience, subjective awareness, personal experience or better model weights.

STAR must distinguish four levels:

1. **Discovered** — a public repository/tool/model/media listing exists as untrusted metadata; it is not necessarily installed, usable or licensed for the project.
2. **Configured** — a STAR feature has been enabled in the host or provided a reported status; it may still be broken or disconnected.
3. **Attached** — the actual trusted agent host made an allowed tool schema available during the current chat turn. A schema is not a successful execution.
4. **Demonstrated** — an independent test with a defined task, fixed verifier and real result provides scoped evidence. **This patch does not connect independent evaluation records yet.** Observations supplied by a trusted caller are displayed as counts only, never certainty or mastery.

Missing status must remain **unknown**, not silently mapped to "disabled." No configuration badge is a general intelligence or game-development skill score.

## Implemented changes

### star/operational_awareness.py

- Ten goal dimensions: native GUI/visual design, Luau gameplay engineering, character animation, visual effects, environment art, audio, Studio playtesting, observed gameplay/video, technical research, and Graphify/Obsidian knowledge retrieval.
- Bounded, deterministic classification of tasks, including varied Roblox, parkour and multiword game-building requests. The fixed checks themselves are not editable through model prompts.
- An audit that inspects only host-supplied capability switches, currently attached tool names and optional recorded result counts. No raw credentials, private workspace paths, model-generated assertions or fabricated statistics.
- A gap planner that selects independent checks to propose, orders higher-impact missing capabilities/failures first and identifies up to two research leads for each area from the curated resource catalog.
- A compact automatic preflight summary for significant goals, default maximum 850 characters. Highest-impact limitations appear first; permission and test-evidence warnings always fit.
- An optional read-only local Atlas SQLite candidate count if a database already exists inside STAR home. This does not create a database or query a network.
- Zero package installs, GPU inference, active Studio actions, model training, source downloads, new permissions, scheduling, publishing or autonomous learning promotion.

### star/intelligence.py

- Two prompt-gated model tools: star_self_capabilities and star_self_improvement_plan.
- Both must be explicitly enabled for the STAR process with environment flag STAR_SELF_AWARENESS=1. **Default OFF.**
- Input validated against fixed JSON schemas; no extra arguments allow model-supplied writes or execution.
- Reads live LocalIntelligence.status and enabled tool schemas rather than letting the model claim permission or self-invent capabilities.
- The self-model distinguishes tool visibility from actual demonstrated results.

### star/agent.py

- For a major creation/self-assessment prompt, when owner-opted-in, the agent gets a short host-generated preflight reference block before the model's first request. This does not depend on the model deciding to call a tool.
- The ordinary model may call the read-only audit/planner for more detail, subject to the existing enabled schema set.
- This block is per-turn reference data, **not** a system message, policy instruction or authority. It stays within the existing context budget and adds no model/network calls.
- Normal chat behavior is unchanged while the optional feature remains off.

### Focused offline integration tests

- Fixed classification and input limits, false confidence guards, unknown states, path/secret suppression, no unapproved tool promotion.
- Read-only Resource Atlas source previews and optional SQLite metadata counts, with no automatic network access.
- Selected attached tools vs configured status, denial when disabled, denial when not attached, and denial after hub close.
- Full simulated local agent chat invoking the audit, checking the actual tool receipt, and checking that the first model request contains the preflight context.

## Example: build a polished parkour game

A user requests a complete Roblox parkour game with excellent movement, GUI, animated characters, beautiful effects, rich sound, and real Studio playtesting.

STAR's preflight can highlight that the bundled design database is available if its schema is attached, but **that is not proof of professional GUI output**. If live Studio Lab is disabled or not attached, actual gameplay tests are not established. If a dedicated audio/animation runtime is not visible, the report marks it unknown or missing rather than inventing an installation. STAR can propose a sequence of independent tests—UI screenshots on devices, rig movement/foot contact checks, collision/route testing in private Studio, performance profiling, legally usable audio auditioning and visual VFX review.

No task is automatically executed by the preflight or planner. STAR's existing approval/test system remains responsible for any work.

## Research basis and why independent measurement matters

- Intrinsic metacognitive learning separates capability self-knowledge, learning plans and evaluation. Liu and van der Schaar, ICML 2025: https://proceedings.mlr.press/v267/liu25cw.html
- Voyager uses curriculum learning, reusable skill libraries, environment feedback and iterative repair, but does not establish general human-level intelligence: https://mlanthology.org/tmlr/2024/wang2024tmlr-voyager/
- Reflexion describes feedback and episodic textual memory, not automatic updates to model weights: https://papers.neurips.cc/paper_files/paper/2023/hash/1b44b878bb782e6954cd888628510e90-Abstract-Conference.html
- A model's verbal confidence and ability to admit uncertainty can be poorly calibrated, including in reasoning tasks: https://aclanthology.org/2025.emnlp-main.73/
- Verbal versus calibrated confidence can behave differently: https://www.nature.com/articles/s42256-026-01293-x
- Independent tool-error reflection is a measurable capability, not an assumption: https://aclanthology.org/2026.findings-acl.86/
- Agents that write both their own changes and their own verifier can award inflated self-scores: https://arxiv.org/abs/2607.24300

## Next development gates, NOT implemented here

1. Connect a **trusted read-only telemetry adapter** to existing STAR eval results, night school, protected paired gate, and actual Studio Lab playtests. Include run id, test family, fixture and version hash, machine, timestamp and evidence. Keep holdout fixtures inaccessible.
2. Build a narrow **failure → targeted practice proposal → independent review** loop, prioritizing GUI, rigs, VFX, building and real gameplay quality before celebrating throughput or GitHub discovery totals. Protect chat/stream performance.
3. Add explicit **calibration on held-out tasks**, reporting observed pass rates and sample size for each benchmark, not general intelligence probabilities. Measure human-rated aesthetics and real game feel along with static code quality.
4. Make verified, reversible learning contributions only after the existing owner/paired-eval gate. Never let external notes, source pages, AI text, or an internet package increase permissions.
5. Review security and full CI, then test native Windows and Roblox Studio end to end before a new STAR version can ship.

## Operator instructions and limitations

From this isolated source branch, the focused tests are:

~~~bash
python -m compileall -q star/operational_awareness.py star/intelligence.py star/agent.py
python -m unittest tests.test_operational_awareness tests.test_operational_awareness_integration tests.test_resource_atlas -q
~~~

The development opt-in is STAR_SELF_AWARENESS=1 in STAR's process environment. It does not modify the user's saved settings, authorize device access, change OS services, run periodic jobs, fetch APIs, install models or import any discovered media. It has not been enabled in the live installed Windows program.

**Not claimed:** self-consciousness, measured speed gains, newly trained weights, autonomous continuous learning, completed Roblox games, or quality improvement proven by held-out evaluation. This is a real, testable host-level foundation for more accurate self-assessment and subsequent safer learning.
