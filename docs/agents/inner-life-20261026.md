# inner-life-20261026: recall, nightly reflection, opinions, reach-out, dreams, self-model (Claude)

Branch `star/inner-life-20261026`, worktree `worktrees/inner-life`, PR into `star/next`. Code: `star/inner/`. Tests:
`tests/test_inner_life.py` (86). Eval harness: `tools/inner_life_eval/`. Design source: `docs/research/human-like-star-20261026.md`
items 4, 7, 8, 11, 12, 13, 14, 15, plus the owner's additions of 2026-10-26 (dreams, a self she revises).

## Status in one table

| piece | file | default | measured |
|---|---|---|---|
| per-turn recall + card hook | `context.py`, `recall.py` | **OFF** (`inner_chat_enabled`) | local 2.3 ms per turn [M, `run.py` fixture, 20 reps]; live blind A/B **pending** |
| nightly reflection (diary, cards, opinions, consolidation, audit) | `reflect.py` | ON (`inner_night_enabled`, background) | fake-brain tests only; no live night yet |
| opinions + backstory | `opinions.py` | with the hook | tests |
| proactive messages | `reachout.py` | **OFF** (`inner_reachout_enabled`) | tests |
| dreams | `dreams.py` | ON inside the night job | 3 live samples **pending** (below) |
| self-model | `self_model.py` | ON inside the night job; persona text not wired into any prompt yet | tests |
| night job / plug-in | `night.py` | ON | tests |

Settings live in `<app data>/settings.json`. Night job = background only, so it adds no chat latency; the two things that touch
people (the prompt hook, the messages) stay off until measured / approved.

**A/B and dream samples are pending**: brain 1 is busy with the sealed eval (#608, ETA ~11:00Z 10-26); nothing ran on it. To run
after it ends (read the harness docstring): `run.py gen 2`, `run.py blind`, judge blind, `run.py score scores.json`,
`./star.cmd lock run ... run.py time`, `run.py dreams 3`. If the hook does not win blind (sign test on non-tied pairs, the 39-of-60
rule of `star.evals`), it stays off.

## What the chat path pays

`turn_context(memory, person, text, first_turn=...)` -> `.card` (night-written, <= 240 chars, put it in the first user content of the
conversation, never the system message) and `.note` (appended to the NEW user message only). System prompt: identical for every
person and mood. Note: nothing unless the message has a cue; at most 2 lines of <= ~100 chars; whole note <= 190 chars (about 45
tokens worst case [E], typical 75-110 chars about 20-28 tokens [E]); on the 21 fixture messages (tools/inner_life_eval/convs.py) 12 got a note (longest 133
chars), 4 an honest "not stored" hint, 5 (all the small-talk ones) nothing. No model call. Latency effect of the tokens: ~17-20 ms per uncached token on brain 1 [M, human-voice
notes], so roughly 0.3-0.9 s [E] on the turns that get a note and 0 on the rest; the measurement is `run.py time`.

Rules that came from the failed autobiographical block (docs/agents/human-voice-20261025.md): content not counts; only on a cue;
labelled optional ("maybe useful, only if it fits"); no example sentences; no numbers.

## How each piece works (file:line is `grep -n "^def \|^class "` in the file)

- `store.py`: one SQLite file `<app data>/inner/inner.sqlite3`: episodes with FTS5 (porter), cards, diary, opinions, backstory,
  seeds, dreams, audits, self-model versions and journal. People are keyed `<id>.<first met>` (`person_key`) so a forgotten
  person's rows are never inherited by a new person who gets the same id; `purge_orphans` (run every night, and `delete_person`)
  removes episodes, card, seeds and dreams of anyone friend memory forgot.
- `recall.py`: cue = question about the past / "remember" / "what's my" / "where do I work" / a message that shares >= 2 content
  words with a stored memory (or one strong word) / first message (one open dated or emotional thread of the last 14 days).
  Score = word overlap x forgetting curve e^(-age/S) x importance; S = 3 + 25 x importance days, x1.7 each time a memory is used
  (`strengthen`, called by `ctx.done()`). `sync_person` copies friend facts and (for adults/unknown age, not Roblox) what they said
  into episodes: possible minors contribute only the interests friend memory already kept, never chat lines. Asking about
  something never stored gives the hint "nothing stored about this: say honestly you don't think they told you".
- `reflect.py` (nightly): `run()` = purge -> sync -> home history into episodes -> opinions from real sessions -> diary (+ opinion
  moves, only for topics in today's notes) -> per active person (max 8) a card <= 240 chars and one follow-up seed -> consolidation
  (merge duplicates, newer "my X is ..." replaces older, unrecalled trivia below retention 0.03 is forgotten) -> consistency
  audit (regex for human-life claims + a model judge against backstory and opinions; findings go to `store.audits` and the
  curiosity queue as `failed_verification`). Every model output is validated; failure keeps the old card / uses the rule-built
  one. Cards and diary may only contain numbers that are in the notes; no reasoning text; no instructions; nothing romantic unless
  `rules.romance_mode` allows it.
- `opinions.py`: opinion = stance, reason, confidence, valence. Agreeing evidence +0.08 confidence, disagreeing -0.12, stance turns
  over only below 0.25 with "changed my mind". Retrieved by topic (needs all topic words, or the "what do you think" cue). Backstory:
  9 true facts with sources, one line by cue (who are you / where do you live / what do you do), never volunteered, "I'm an AI" only
  when asked who she is.
- `reachout.py`: seeds written by `reflect` and `dreams`; `due()` is plain rules: close friend (friend, they started, >= 40 chat
  lines, heard from in the last 30 days, `rules.may_initiate`), their usual hours, never 22:00-09:00, <= 3 a day, 3 h between any two,
  48 h per person, none while they chat (20 min), none while an earlier one is unanswered, seeds expire (3 days; dreams 1 day);
  text must pass the persona check, the age rules (`rules.check_outgoing` must leave it unchanged; no other app for a non-adult)
  and a guilt filter (no "I miss you", "where did you go", "you never reply"). The adapter calls `due()`, sends, then `mark_sent()`.
- `dreams.py`: see sources below. One dream per night from 3-5 weighted fragments, brain writes it (background), vividness computed
  from the fragments. Morning fade `vividness x e^(-t/3h)` from 07:30: >= 0.55 full, >= 0.22 a gist ("something about X..."), else
  gone; `wake()` nudges mood once via `emotion.on_event` (pleasant -> `learned_something`, unsettling -> `task_failure`, scaled down;
  `star/emotion.py` has no dream kind, add one there if wanted). A remembered dream shows in chat on "how did you sleep / did you
  dream", or on the first message of a close friend who is in it; always "dream ..., not real". A message to a friend must contain
  the word dream. A dream that claims to be real or is romantic about someone the age rules do not allow is dropped.
- `self_model.py`: seed "sweet, funny, cute, curious and playful; can flirt with adults who enjoy it" + 9 traits, values, likes,
  dislikes, humour, quirks, cares, wants-to-improve, how she feels about people. `revise()` each night after reflection and dreams:
  <= 3 changes, one per field, a trait moves <= 0.05 and stays within +-0.5 of the seed, lists +-1 item, text only small edits, every
  change needs a reason; applied and refused changes are journalled (`self_journal`, mirrored to `<app data>/inner/self-journal.md`),
  every night's result is a new version (`self_versions`). `persona_for_day()` renders once per day (day starts 08:00, so the system
  prompt is byte-identical all day); trait words, no numbers, no example sentences, `FIXED_BOUNDARIES` always last. Choices read
  `trait()`, `affinity()`, `weight_multiplier()` (0.7-1.4 for star-home interest weights) and `invite_appetite()` (decide(invite)).
  **Fixed, in code**: no field for rules/safety/ages/approvals (unknown fields refused); `_BOUNDARY_ATTACK` refuses values that deny
  being an AI, flirt/romance with minors or anyone, hurt or manipulate people, hide logs or defeat the owner's stop, skip approvals,
  spend money or open accounts; `flirt_level()` is 0 unless `rules.romance_mode` is "allowed"; the age rules, truthful-AI check, home
  approval tools and owner stop are enforced where they always were (rules.py, home loop), not by the persona text.
- `night.py`: `tick()` is idempotent (does the night once in 01:00-08:00, wakes her in the morning); `python -m star.inner tick|night|
  journal|dream`; `register_home_activities` registers "inner night" (interest `inner_life`).

## Wiring others must add (not my files)

1. Social chat (`star/social/chat.py`, social-games/home-wiring): `ctx = star.inner.turn_context(self.memory, person, text,
   first_turn=not history)`; system = SOCIAL_CORE + platform + romance only; `About {name}: {ctx.card}` first in the user content;
   `ctx.with_note(...)` for the message; `ctx.done()` after the reply. Also the mood line should be `emotion.directive(person=...)`
   in the user message (research doc item 2/5).
2. Night job: `star.inner.night.tick()` from star-home's loop every few minutes (exact, idempotent), or add `star.inner` to
   `PLUGIN_MODULES` AND an `inner_life` interest in life.py (the activity is inert until that exists).
3. `self_model.persona_for_day(store)` as the persona text for the day; `weight_multiplier` in `Life.scores`; `invite_appetite` in
   decide(invite).
4. Reach-out: the Discord adapter polls `reachout.due(store, memory, enabled=flag("inner_reachout_enabled"))`.
5. After "forget me": `store.delete_person(person_key)` (before the friend row is deleted) or rely on the nightly `purge_orphans`.

## Verification actually run

- `pytest tests/test_inner_life.py`: 86 passed (~18 s, PC, below-normal not needed: tests use fakes, no model).
- Mutation check by hand (a rule removed, the suite must fail): boundary regex, trait step, card number/romance/shape checks, quiet
  hours, minors' chat lines, off-platform rule, unanswered/live-chat blocks, dream-word rule, claims-real rule, small-edit rule,
  max-changes, forgetting, nudge-once: all killed. Two were first vacuous (the person was not active that night), found by this
  check and fixed.
- `run.py show` prints both arms' prompts; they differ only as intended; the ON system message is byte-identical for every person.
- Not run: any live brain call, a real night, Discord sending, the home loop. Cards/diary/dreams are untested against real model
  output (fake brains return well-formed JSON; malformed output is covered: refused, old card kept).

## Dream sources (checked 2026-10-26)

- Schredl & Hofmann (2003), "Continuity between waking activities and dream activities", Consciousness and Cognition 12(2):298-308,
  https://pubmed.ncbi.nlm.nih.gov/12763010/ : dreams reflect waking life, unevenly (talking with friends and driving over-represented,
  reading/writing/computer use under-represented).
- Wamsley, Tucker, Payne, Benavides & Stickgold (2010), "Dreaming of a Learning Task is Associated with Enhanced Sleep-Dependent
  Memory Consolidation", Current Biology 20:850-855, https://pmc.ncbi.nlm.nih.gov/articles/PMC2869395 : task-related dream imagery
  in a nap predicted improvement; waking thoughts about the task did not. Basis for weighting recent and unfinished material (our
  weights are a design choice).
- Nielsen & Powell (1989), "The 'dream-lag' effect: a 6-day temporal delay in dream content incorporation", Psychiatric Journal of
  the University of Ottawa 14:561-565, and the 1992 review in Dreaming 2:67-77 (day-residue clear, dream-lag replication
  inconclusive): hence at most one older item, with probability 0.35.
- Honest limit: none of this says an LLM's dream "does" anything for memory; here a dream is a mood, a topic and a conversation
  seed, labelled as a dream.

## Dream samples (3, real brain): pending

`python tools/inner_life_eval/run.py dreams 3` once brain 1 is free. Paste the three here.

## Known limits / follow-ups

- Reads friend memory's private `_db` (people.created, facts, moments) because `FriendMemory` has no public accessors for them;
  one small accessor set in friends.py (social-games) would remove that.
- The self journal's "why" text is written by the model from the day's notes (no names are passed in); if a name still appears it
  is not removed by "forget me". Revisit if the owner wants a hard guarantee.
- Dream seeds use `reachout.add_seed`, so they need the person to be a close friend at night and again when `due()` runs.
- `emotion.py` has no dream event kinds (nudge uses `learned_something` / `task_failure` at low strength).
