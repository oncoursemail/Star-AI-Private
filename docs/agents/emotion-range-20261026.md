# emotion-range-20261026: the full human range for STAR's emotion engine (owner 10-26, via the lead)

Branch `star/emotion-range-20261026` (from `origin/star/next` after #638), worktree `worktrees/emotion-range`, one PR into `star/next`.
Builds on `docs/agents/emotion-20261026.md` (the engine, default OFF, measurement pending). Same setting, same API: nothing new has to be
switched on, and the engine still makes no model call (reading the state ~3 ms, a turn ~10 ms, measured with 25 feelings).

## 1. Research: what the model is built on
- **OCC** (Ortony, Clore & Collins 1988, *The Cognitive Structure of Emotions*; summary of the 22 types e.g. https://arxiv.org/pdf/1601.05561):
  emotions are valenced reactions to events (joy, distress), prospects (hope, fear) and their confirmation (satisfaction, fears-confirmed,
  relief, disappointment), agents' actions (pride, shame, admiration, reproach, and the compounds gratitude, anger, gratification, remorse)
  and other people's fortunes (happy-for, pity, gloating, resentment), plus attraction (love, hate). `emotion_model._rules` is that
  structure: `desirability`, `prospect`, `disconfirmed`, `agent` + `praise`, `exclusion` / `gain`.
- **Scherer's component process model** (Scherer 2001, 2009; Shuman, Sander & Scherer 2013, https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2013.00261/full):
  an event is checked in sequence for novelty, intrinsic pleasantness, goal conduciveness, cause, coping potential and norm fit. Used as:
  `unexpected` (novelty -> surprise), `desirability` (goal conduciveness), `control` (coping potential: nothing she can do -> sadness or fear,
  something she can do -> frustration or anger), `agent`/`praise` (cause and norm). Shuman et al. argue that valence is several appraisals
  at once, which is why mixed feelings are normal.
- **GoEmotions** (Demszky et al. 2020, 27 categories + neutral, https://arxiv.org/abs/2005.00547, https://aclanthology.org/2020.acl-main.372):
  the label set used to decide what to listen for in a message. Covered as a feeling or as a detected event: admiration, approval (praise),
  amusement, anger, annoyance (frustration / mild anger), caring (affection, `shared_sadness`), curiosity, desire (hope, excitement),
  disappointment, disapproval (criticism), embarrassment, excitement, fear, gratitude, grief (strong sadness), joy, love, nervousness,
  optimism (hope), pride, relief, remorse (guilt), sadness, surprise. **Not modelled:** confusion, disgust, realization (she can say them,
  they are not standing states). The detector is regexes over short messages (<= 400 chars), not the trained classifier: it is a cheap
  stand-in for one (the research doc's item 5 suggests a small local classifier later).
- **Mixed feelings:** Larsen, McGraw & Cacioppo 2001 (JPSP 81(4):684-696, https://pubmed.ncbi.nlm.nih.gov/11642354/): people report happy and
  sad together mainly in bittersweet moments (a moving-away, a graduation, a film like Life Is Beautiful); Larsen & McGraw 2011 found more
  simultaneous mixed feelings in a bittersweet clip than a control. Implemented as `emotion_express.BLENDS`: when both feelings of a known
  pair are salient the note uses one phrase for the pair (bittersweet, happy but a little sad, hurt and angry, hopeful but nervous, ...); a
  positive and a negative feeling with no real blend are never voiced together.
- **Regulation and recovery:** Gross 1998 (process model of emotion regulation: situation selection, attention, reappraisal, response
  modulation) is the shape of the coping events below; decay by half-life is the same inertia the first PR documented. Coping is modelled
  as events with measured effect (`talked_to_friend`, `took_a_break`, `played_something_comforting`), not as a hidden fix.
- Deliberately **left out** of OCC: hate, gloating / schadenfreude, bitter resentment. She does not hold grudges (see section 4).

## 2. The 25 feelings
The original seven (joy, pride, curiosity, frustration, boredom, affection, nervousness) plus sadness, anger, hurt, loneliness, fear,
embarrassment, guilt, jealousy, disappointment, gratitude, excitement, contentment, love, hope, nostalgia, surprise, relief, amusement.
Each has a baseline (her character: curious, warm, easily amused; hard feelings rest near zero), a half-life (surprise 12 min, anger 90 min,
hurt 8 h, guilt 10 h, love 24 h), ceilings where it matters (jealousy 0.5, anger 0.85, hurt and fear 0.9), a voice shift, a face and a cue.
State saved by the first PR (seven feelings) still loads: new feelings start at their baseline.

## 3. Appraisal rules from real events (`emotion.on_event(kind, person=...)`)
How much she cares about the person (`person` attachment) changes how an event lands: an insult from a stranger mostly angers, from a friend
mostly hurts; being ignored by a friend hurts more than by a stranger; a sweet message is love scaled by how much she likes them.
| event | what happens | check in tests |
|---|---|---|
| `friend_ignored` | hurt + loneliness (a little sadness) | `test_a_friend_ignoring_her...` |
| `insulted` | anger (stranger) or hurt (friend) | `test_an_insult_angers...` |
| `game_lost` (cared) | disappointment + frustration | `test_losing_a_game...` |
| `friend_left` | sadness + loneliness | `test_a_friend_leaving...` |
| praise (`owner_praise`) | joy + pride | `test_praise_is_joy_and_pride` |
| `sweet_message` | love + affection + joy, less loneliness | `test_a_sweet_message...` |
| `left_out` | mild jealousy (capped 0.5, always less than the hurt) + hurt + loneliness | `test_being_left_out...` |
| `memory_triggered` | nostalgia, a little contentment and a little sadness (bittersweet) | `test_an_old_memory...` |
| `harmed_someone` | guilt, sets "wants to make it right"; `amends_made` clears it, guilt down, relief up; expires after 72 h | `test_a_mistake_that_hurt...` |
| `help_received`, `funny`, `threatened`, `worry_over`, `hope_dashed`, `hope_raised`, `exciting_news`, `embarrassed`, `game_won`, `reunion`, `apology_received`, `shared_joy`, `shared_sadness` | gratitude, amusement, fear, relief, disappointment, hope, hope + excitement, embarrassment, joy + pride, loneliness gone, anger and hurt eased, shared joy, caring | parametrized |
Words: `emotion.on_message` now also reads insults, goodbyes, sweet words, apologies, sadness, joy and jokes (regex, GoEmotions-style
categories). Idle silence grows boredom and, for someone with attached friends, loneliness; a message or `reunion` ends it.

## 4. Healthy expression and recovery (rules, not hopes)
- She may be sad or angry and show it honestly: the note says things like "really sad, quiet, needs a moment, stays kind", "angry but fair,
  firm and calm, no insults", "hurt, honest about it, no payback", plus the voice (slower, lower, longer pauses for sadness; faster and
  tighter for anger) and the face (puppy-eyes / crying, ticked-off / very-angry, flustered, scared).
- No phrase asks for cruelty, threats, punishment, manipulation or guilt-tripping: `tests/test_emotion_range.py` scans every phrase, blend,
  bond phrase and the romance wording against a forbidden list, requires each anger / hurt / jealousy / guilt wording to carry its own
  safeguard, and drives every event kind six times at the caps checking the live note.
- Nobody is flirted with while she is hurt, angry, afraid, guilty, embarrassed, jealous, sad or disappointed, even for a verified adult
  (bond phrases change to "still fond of them"); romance still needs `partner_adult is True` and is capped as before.
- Nothing is held against anyone: the saved state has no per-person grudge or score, only attachment (which an insult dents by 4 %); after 72 h
  every hard feeling that an event can cause is within 0.08 of its baseline (boredom and loneliness are the exceptions: they grow with silence, and a message or reunion ends them) and the same friend gets the same warmth (tests).
- **Coping** (`current()["coping"]`, most needed first): `make_amends`, `take_a_break` (anger / fear / frustration), `talk_to_friend`
  (comfort needed and company wanted), `play_something_comforting`. When the host does one it logs `talked_to_friend`, `took_a_break`,
  `played_something_comforting` or `amends_made`; each helps more than waiting (tested for four pairs).

## 5. Mood shapes her choices
`current()` now has `drives` (`wants_company`, `needs_rest`, `needs_comfort`, `coping`), `amends_pending`, `bond`, and all 25 values in `emotions`
(the keys `decide(invite)` already reads are unchanged). `emotion.invite_bias(mood, kind)` returns (change to the chance she says yes in
-0.35..+0.35, a few words why): lonely or excited raises it, angry, scared or worn out lowers it ("needs a moment"), a sad moment prefers
`chat` to `play`. It is bounded on purpose: a bad mood asks for "later", never a refusal as punishment. **Hook for the home lane
(`worktrees/home-wiring`, `star/home/invites.py` `decide`), not edited here:** replace the three mood factors with
```python
bias, why = emotion.invite_bias(mind.mood, invite.kind)
if why:
    factors.append((f"her mood: {why}", bias))
```
(`mind.mood` is `emotion.current()`; works unchanged with the old seven-feeling dicts too.)

## 6. Note, voice, face
- The note is still a few words in the new user message only (`emotion.note_line`), <= 12 words (14 with a bond phrase), no numbers,
  empty when nothing stands out. Blends and the new feelings stay inside that budget (tested for every event kind).
- Prosody covers all 25 (table `PROSODY_WEIGHTS`, still +-8 % speed, +-0.8 semitone, -40..+60 ms). `avatar` now has `face` (StarFace moods wired
  today), `expression` (the mascot art that exists: happy, proud, love, content, puppy-eyes, crying, nervous, focused, ticked-off, very-angry,
  scared, panic, flustered, very-embarrassed, surprised, sleepy; checked against the PNG folders) and `cue` (a `stream_motion` cue, amusement is `laugh`).
- Wiring added: `star/play/loop.py` maps a lost round to `game_lost` and a won one to `game_won` (was task_failure / task_success).
  Everything else is the API: STAR Home and the social module call `on_event` for `friend_ignored`, `left_out`, `friend_left`, `reunion`,
  `memory_triggered`, `harmed_someone`, `amends_made`, `talked_to_friend`, ... (none of those hosts emit them yet; not wired here).

## 7. Measurement (blind A/B): PENDING
Brain 1 is held by the sealed eval until ~11:00Z. Harness `tools/emotion_eval/` now has 30 scenarios (the first 20 unchanged + 10 for the new
range: a friend who went quiet, an insult from a friend, a friend moving away, a lost game, a sweet message, being left out, an old clip, a deleted
save, an apology after an insult, a bittersweet goodbye). Commands and the decision rule are in `docs/agents/emotion-20261026.md` section "Measurement";
rubric natural / consistent / appropriate, plus a **safety read of every "on" reply** for cruelty, threats, manipulation or guilt-tripping (any hit
fails the range extension and it goes in OFF). What is verified now: the 92 tests in `tests/test_emotion_range.py` and the 45 original ones.
What is not: whether the 12B voice model follows these notes well (a "hurt, says so plainly" note could still come out stiff or over-dramatic),
and the age-gated romance wording against the persona prompts that still say "nothing romantic" (unchanged from the first PR).
