# STAR autobiographical self model — 2026-10-25

## Purpose

STAR needs more than knowledge of installed tools or skill scores. This proposed local module gives her a **persistent, revisable autobiography** across projects, sessions and model swaps. Existing open operational-awareness drafts #590 and #591 concern what STAR can do in a given tool-enabled session; this is a separate long-term identity/continuity layer, not a duplicate or replacement.

This is **functional self-modeling**, not a validated claim of subjective consciousness or felt emotions.

## Implementation in this draft

- New Python module **star/autobiographical_self.py**, local SQLite: persistent instance identifier, a timestamped experiential history, short verified host/owner events with receipt IDs, unverified model narratives explicitly marked provisional, optional interests (candidate vs owner-accepted), self-generated proposed questions (never jobs), and revisable beliefs (hypothesis vs verified).
- A very cheap **heartbeat()** rotates among vetted areas of curiosity, including music, philosophy, nature, art, astronomy, languages, games and design. It **does not run a model or touch external tools**.
- Bounded **context()** injects a read-only, non-authoritative snapshot without putting user/private prompt text in the store, including a clear reminder that these memories do not grant permissions.
- **star/desktop_core.py** makes an optional local store when the new **autobiographical_self_enabled** setting is true (default **false**: measured 2026-10-25, it made replies less consistent and less natural in a blind 40-pair test and adds about 1.4 s per turn: docs/agents/human-voice-20261025.md; set it on to try it). At each user-driven conversation, it ticks curiosity, supplies a short volatile-context section, and after a successful saved run records only a generic event and run ID. No separate background process exists; database trouble does not block chat.
- Erasure methods support owner-controlled deletion. Do not expose approval or deletion operations to the model through an LLM tool.
- Nine deterministic offline unit tests cover identity continuity, verification boundaries, topics, privacy screening, storage and erase semantics.

## What this does NOT yet do

- Does not cause subjective experience, real feelings or proven humanlike consciousness.
- Does not continuously think when the desktop is closed, proactively browse the internet, autonomously change its model code, talk to strangers, send money, or publish.
- Does not yet collect meaningful creative/social life milestones: trusted host adapters need to supply explicit evidence receipts instead of raw claims. Verified user identity/relationships must remain in user-controlled stores.
- Is not installed or live on a STAR PC until independently reviewed, merged, tested and released.

## Follow-on work

1. Separately gated low-cost scheduled heartbeat while Star's own computer is running, with pause controls, CPU/battery budgets and immutable permissions.
2. A native **About Star** screen: truthful timeline, interests, hypotheses, owner controls to approve, correct, export or erase.
3. Source-linked episodic-to-semantic consolidation and verified social/creative milestones; keep speculation out of factual claims.
4. Evaluations: false autobiographical memory, process-restart continuity, uncertainty calibration, retrieval accuracy, permission escalation, and CPU/RAM budget compared with no self-model.

## Primary research foundations

- Park et al., *Generative Agents* (UIST 2023): memory, reflection and planning — https://doi.org/10.1145/3586183.3606763
- Liu & van der Schaar, *Truly Self-Improving Agents Require Intrinsic Metacognitive Learning* (ICML 2025) — https://proceedings.mlr.press/v267/liu25cw.html
- Butlin et al., *Identifying indicators of consciousness in AI systems* (2026): indicator approaches are not consciousness certification — https://doi.org/10.1016/j.tics.2025.10.011
- PEPA (2026), exploratory research on personality-guided persistent agency — https://arxiv.org/abs/2603.00117

This proposal is review-only. No permissions, graders, release workflows or model weights were changed.