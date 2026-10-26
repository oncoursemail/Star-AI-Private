# PR 664 independent review — 2026-10-26

Update: after this review, the integration branch merged PR 664 at `bf7246db`. The own-PC branch reconciles its two voice conflicts while preserving the current adult-peer, transcript, emotion and history safeguards. It replaces the rejected opener, keeps the experiment disabled by default and excludes adult-peer calls from its hints. The desktop guard now holds unfinished sentences, requires confirmed separators during streaming, checks final fragments, and fails closed above 4096 non-whitespace unfinished prose characters or 65536 held raw characters. Ten existing guard tests and the retained split-trigger/buffer verification pass; the original three-chunk leak now displays only `Hello.`. This historical exact-head review below describes the pre-correction source, not the final integrated behavior. Native voice quality measurements remain pending.

Reviewed [PR 664](https://github.com/oncoursemail/Star-AI-Private/pull/664), head `990b18c919fc2736d088f55b58ac886d80b44037`, targeting `star/next`. No integration, checkout change, public comment or review submission was performed.

## Observed merge and CI state

The read-only GitHub snapshot reported `CONFLICTING` / `DIRTY`, no reviews and no review decision. Its only reported check was **Generators do not edit evals, graders or the gate: SUCCESS**. This does not establish passing Python, type, Windows or frontend checks. A read-only `git merge-tree --write-tree --name-only` comparison with the current integration branch found conflicts in `star/voice/call.py` and `star/voice/persona.py`.

The PR leaves varied openers disabled by default and describes live model measurements as pending. Its author-reported focused test results were not independently rerun against an integrated tree. No naturalness or latency improvement has been established by this review.

## Reproduced findings

1. **The desktop guard can display part of a sentence it later rejects.** `star/reasoning_guard.py:78` releases an unfinished sentence once it exceeds 60 characters. When a later chunk completes a reasoning phrase, `star/agent.py:315` uses `max(emitted, ...)`, so already released text remains in the displayed and returned answer. The claim that a rejected sentence is never shown is therefore too strong.

   Reproducer: feed guarded `read_stream` these three synthetic content chunks, in order:

   ```text
   Hello.
   In preparing this answer with all of the details from this discussion, I sho
   uld check the status first.
   ```

   Both the returned answer and concatenated `assistant_delta` events were:

   ```text
   Hello. In preparing this answer with all of the details from this discussion, I sho
   ```

   The fetched PR's guard module and `read_stream` function were compiled in memory for this reproduction, using the existing module dependencies and a synthetic stream. No model, network or live conversation was used.

2. **A suggested opener triggers the existing voice reasoning filter.** The warm pool at `star/voice/persona.py:85` includes `Mm, let me think.`. Calling the existing `star.persona.leaked_reasoning` on that exact string returned `True`. `CallSession._stream_sentences` rejects such sentences, so following the suggestion can cause a retry or drop speech. The PR's pool-rotation tests do not cover this interaction.

## Minimal integration recommendation

Review the desktop guard separately from the opener experiment. Before accepting the guard, resolve the conflict between bounded buffering and rejecting any later-matching sentence: text already displayed cannot be retracted reliably. Either retain an unfinished sentence until it can be classified, or explicitly narrow the guarantee and prevent incomplete trigger phrases at release boundaries. Include a harness-owner regression for the three-chunk reproduction above. This review did not alter tests or evaluation fixtures.

For openers, remove suggestions rejected by the existing speech filter. Preserve the current call implementation's `_check_partner`, `_feel`, committed-final-transcript callback, history handling, speculative-turn behavior and output filtering. Add a default-off hint to its existing per-turn extras rather than replacing `_turn_messages` with the older PR version.

Keep `partner_adult` keyword-only and require exact `True`. Pass any new `varied` argument by keyword, and keep runtime priming consistent with the eventual call prompt. The current adult peer prompt explicitly avoids a fixed opener; do not add mother/mentor pools to that path. Leave hints off there until a separate peer design has been reviewed and measured. A whole-file conflict resolution taking the PR's older persona/call versions would discard current adult safeguards and emotion context.

Before merging, resolve both conflicts deliberately, run the existing voice, emotion, home and adult-voice checks on the combined code, obtain the required independent review and inspect current CI. Do not infer readiness from the protected-closure check alone.
