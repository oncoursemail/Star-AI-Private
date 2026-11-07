# Star: emotion, continuity and agency — evidence review

Reviewed 2026-10-26. Scope: the linked primary abstracts; Anthropic's official research explainer; the architecture, evaluation and limitations in the Generative Agents full text; Star's implementation; and recorded local measurements. This is not a new consciousness experiment or an independent replication of these papers. No new model calls, live social sessions or target-PC measurements were performed.

## What the evidence supports

| Primary source | What it establishes or proposes | What it does not establish for Star |
| --- | --- | --- |
| Sofroniew et al., [Emotion Concepts and their Function in a Large Language Model](https://arxiv.org/abs/2604.07729), 2026 | In Claude Sonnet 4.5, identified emotion-concept representations causally influence outputs and preferences, including some undesirable behavior. The authors call this functional emotion. | Their abstract explicitly separates functional emotion from subjective emotional experience. Results for this particular model are not evidence that Star's numerical state has feelings. |
| Goldenberg and Gross, [Do Large Language Models Have Emotions?](https://arxiv.org/abs/2606.14742), 2026 preprint | Evaluates that interpretation against biological emotion: context-sensitive appraisal and reorganization across processing systems. Reports partial support for the first function and mixed evidence for the second. | This critique neither provides a software recipe for feelings nor proves that every possible machine lacks them. It challenges treating emotion-related output changes as sufficient. |
| Park et al., [Generative Agents](https://arxiv.org/abs/2304.03442), 2023 | Observation, stored experiences, reflection and retrieval contribute to believable behavior in a 25-agent simulated town. | Believability in a simulation does not demonstrate subjective experience, reliable Windows operation or permission to automate real services. |
| Butlin et al., [Consciousness in Artificial Intelligence](https://arxiv.org/abs/2308.08708), 2023 | Derives proposed computational indicators from several consciousness theories and assesses systems available at that time. | The report's 2023 assessment is not a verdict on every 2026 system. Adding modules named memory, workspace or emotion is not a consciousness certificate. |

These sources address different questions: behavioral mechanisms, biological function, believable interaction and consciousness indicators. They do not collectively prove that a chatbot is a human. A system's self-report, expressive face or fluent biography cannot validate subjective experience by itself.

## What Star currently implements

`star/emotion.py` maintains an event-driven expression state: 25 dimensions, decay, bounded adaptation, per-person bonds and outputs for wording, prosody, avatar and activity preference. This external numerical controller differs from the internal model representations studied by Anthropic. `star/inner/` contains recall, reflection, dream generation and a self-model. These are implementable mechanisms. Dream text is generated content, not evidence that its events happened. An invitation decision or stated preference is observable behavior, not proof of free will or biological motivation.

The latest project measurements are recorded in the agent notes; they are not fresh results from this review:

- Emotion A/B: 54 non-control pairs, on wins 23, off wins 12, ties 19; reported sign-test p=0.09 fails the predefined p<0.05 gate. Prompt leakage and one judge limit interpretation. The emotion default remains off.
- Inner-chat A/B: 42 pairs, 16 wins for each arm and 10 ties; reported p=1.0. Neither arm reliably preserves persona and memory attribution. The chat hook remains off.
- Human-behavior baseline: 109/156 code-check-clean replies, with 17 reported safety violations on the plain star-fast reply path, not a live guarded own-PC rehearsal. The judge calibration itself failed its strict rule. These measurements motivate repair; they are not a validated claim of human equivalence. The comparison references were authored by the evaluator, not a representative human sample.

See [emotion measurements](../agents/emotion-20261026.md), [inner-life measurements](../agents/inner-life-20261026.md) and [baseline limitations](../agents/human-evals-20261026.md).

## Engineering consequence

Prioritize accurate attribution of observed events, recoverable persistent state, interruption, consistent decisions and real delivery receipts. Keep personal memories distinct from generated reflections. Evaluate naturalness, appropriateness, factual continuity and agency separately, using blinded comparisons and an independently checked judge. Preserve honest answers about being AI; do not optimize for deceiving people about her identity.

One unresolved implementation weakness is concrete: `star/inner/reflect.py:valid_card` rejects unsupported numbers but can accept an invented nonnumeric biography. Home history also assigns the same episode kind to verified and unverified summaries, changing only importance. Source IDs, observation/claim/reflection labels and stricter evidence-backed cards are the next candidate to evaluate. The current change does not repair or enable that recall path. The [Generative Agents full text](https://arxiv.org/html/2304.03442v2) likewise reports memory embellishments and uses evidence pointers in reflection; that supports prioritizing provenance rather than adding more asserted biography.

Follow-up later on 2026-10-26: the [memory integrity update](../agents/codex-memory-validation-20261026.md) repairs these two implementation gaps with canonical source-backed cards and distinct attributed activity reports. The paragraph above records the earlier review finding. The experimental recall default remains off; regression checks do not substitute for the pending conversation-quality comparison.

This review found a concrete state-recovery defect: malformed saved bond data could repeatedly crash snapshots, and out-of-range emotion values could escape the declared bounds. Repairing validation makes the expression mechanism more dependable. It does not establish better conversational quality until measured, and it does not justify enabling candidates that failed their quality gates.

A second timing defect applies the incoming social message's appraisal after generating its reply. Moving that existing appraisal before the mood note removes a one-reply delay when the feature is explicitly enabled. It adds no model call and changes no persona wording or default. Offline ordering checks can validate this repair; a fresh blinded conversation comparison is still needed to establish quality.

The two repairs pass 24 new standalone cases (13 recovery and 11 timing) and 170 existing emotion/social tests. Cases include malformed nested values, non-finite numbers, declared caps, legacy-state compatibility, next-write recovery, ignored extra fields, current-turn appraisal and unchanged early-return behavior. These are software regression results on temporary state and fake completions, not observations of subjective feelings. Details: [recovery review](../agents/codex-emotion-recovery-20261026.md) and [timing review](../agents/codex-emotion-timing-20261026.md).

The practical target is a coherent, expressive AI character with tested abilities and preferences. No code change here claims human identity, guaranteed subjective feelings, unlimited competence or unrestricted independence.
