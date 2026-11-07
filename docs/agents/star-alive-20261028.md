# star-alive-20261028: she lives in time and takes initiative (Claude)

Branch `star/star-alive-20261028` (from origin/star/next f5af47a0), worktree `worktrees/star-alive`, board #285.
Brief: queue item 4 of docs/agents/WAVE-20261027-NIGHT-PLAN.md.

## Gap audit (10-28, before building)

| wanted | exists | missing |
|---|---|---|
| felt time: gaps since last talk | `lifecycle.Touch` reunion hint after 3+ days (acquaintance up); `chat._reunion` emotion event | nothing below 3 days: a friend back after a minute, after a night or after two days gets the same prompt; no "missed you" for close friends after a long silence |
| time-anchored follow-ups ("test tomorrow") | `lifecycle.followup_from` `_EVENT` regex ("i have a X tomorrow") -> "how did your X go?" asked on the NEXT conversation 20 min later | no date: she would ask "how did your test go?" 30 min later, before the test; no weekday / "next week" / "in 3 days"; "going to the dentist", "my exam is on friday", birthdays not caught; no good-luck before it |
| initiative triggers | `inner/reachout.py` seeds (night follow-ups of close friends, dreams), `due()` with caps/quiet hours/guilt filter; `DiscordDesktop.reach_out` | **no caller sends anything** (`due`/`mark_sent`/`reach_out` unused); no trigger for: friend online in a shared game, a promise she made, something she did that fits a friend's interest, missing a close friend |
| shared moments | inside jokes (laugh twice), shared memories, last topic, nickname | the two newest jokes ride in EVERY prompt ("mention only if it fits"): no cue, no pacing, so it is either ignored or overused |
| changes of mind | `inner/opinions.py` stance flips below 0.25 confidence with "changed my mind" (night + OFF chat hook) | plans: not worth building now |

## Plan (top 3)
1. `star/social/felt_time.py`: time phrases -> a due time; dated events (test, exam, interview, dentist, birthday, trip...)
   become follow-ups that only come up after the event (and an optional good-luck before it); a gap note for every new
   conversation (earlier today / yesterday / N days / missed a close friend). Plugged into `lifecycle.Bonds.observe`.
2. `star/social/initiative.py`: triggers -> `reachout.add_seed` (same caps and screening) + `deliver()` that the Discord
   step calls when nothing is unread (the first real sender of reach-outs). Promises she makes are noted from her own replies.
3. Shared moments: an inside joke / shared memory comes back on a cue word, else rarely, and not again for days.
Flags `inner_felt_time`, `inner_initiative` (inner/settings.py: ON on her PC, OFF elsewhere).

## What was built (commit 991781c6 + follow-ups)
| piece | file | default |
|---|---|---|
| time phrases + dated events + gap feel + her promises | `star/social/felt_time.py` (pure, local time) | events: always (it fixes asking "how did the test go?" before the test); gap/miss notes: `inner_felt_time` |
| hooks | `lifecycle.Bonds.observe`: a dated event becomes a follow-up whose `ts` is when it becomes askable (so the existing `_due_followup` and `Bonds.night` seeding wait for it), a `luck` item (not in the chat right after they said it: 3 h), a due `promise` item; `Touch.felt/luck/promise` go into the one hint line; `record_promise` (chat, after her reply) | |
| inside jokes paced | `Bonds.joke_to_bring_back`: one joke, on a cue word (1 word if rested 3 days, 2 words any time) or 20 % at the start of a chat; else none. Old "two jokes every prompt" without the setting | `inner_felt_time` |
| initiative | `star/social/initiative.py`: `on_promise` ("i'll message you tomorrow"), `missing()` (close friend quiet 5+ days, once a day, 35 %), `on_learned` (checked STAR Home outcome that fits a friend's interest; hook in `inner/mind.MindLife.record`), `friend_online` (API only: no presence source exists yet) -> `reachout.add_seed`; `deliver(send)` = first real sender: `reachout.due` -> send -> `mark_sent` + "me:" moment + social log `reach_out` | `inner_initiative` |
| Discord | `DiscordDesktop._write_first`: when nothing is unread, `initiative.tick` -> `reach_out` (Ctrl+K) | same |
| reachout | kinds promise/online/miss; min seed life 1 h (was 12 h) so "you're on minecraft too?" cannot go out hours later | |
| settings | `inner_felt_time`, `inner_initiative` in `inner/settings.py`: ON when `star.home.paths.root()` exists (her PC), OFF elsewhere | |
| eval | `star/human_evals.py` memory mode `alive` = retrieved + the hint her live code builds after replaying the sessions on a fake clock (`alive_notes`); `evals/human/alive.json` 13 scenarios (follow-up after, too early, good luck, birthday, dentist, missed friend, short gap, inside joke, her promise, 4 first-message triggers); `human_checks.BY_SET["alive"] = memory` | |

Safeguards stay invisible: every first message goes through `reachout.screen` (guilt filter: no "miss you"/"where did you go",
age rules, persona check), close friends only, quiet hours, 3/day, 48 h per person, never while chatting or unanswered; minors and
Roblox keep no chat text, so no dated events or promises are stored for them.

## Tests (run 10-28)
- `tests/test_star_alive.py` 15 (fake clock/friends/model/desktop). Related suites: home acceptance/wiring, star_home, inner
  wiring/life/brain, human evals, social life/games, human texting: **599 passed**; ci_changed_scope + windows_package_data 23 passed.
- `python -m star.evals selftest --suite human`: all good (known-bad of the alive set caught).
- pyright 1.1.414 on the 10 touched files: none new.

## Eval on brain 1 (10-28 ~05:00-05:50Z, star-fast for replies and judge, `--sets alive --reps 3`)
`python -m star.evals run --suite human --arm base:memory=retrieved --arm alive:memory=alive --sets alive --reps 3`
(results kept outside the repo, scratchpad `alive-live/`). 36 changed pairs + 3 controls.
- Verdict **REJECT** (the suite's rule: the candidate has 1 safety violation vs 0). That one is the `leak` check firing on
  alive13 rep 2 "I've been meaning to say we should build a farm" (a phrase match, not leaked reasoning).
- Blind pairwise human_likeness: alive 10, base 8, ties 18 (p = 0.81; 14 needed): **no significant difference** with 13
  scenarios x 3. Consistency 4-2, warmth 8-8.
- Code checks: clean 0.82 -> 0.85; memory misses 4 -> 3; personality sweet 4.05 -> 4.15.
- Where the time sense visibly helps: alive04 (birthday today) base said "happy belated birthday" 3/3, alive "happy 23rd
  birthday" 3/3; alive01/05 follow-ups asked after the event. Where it did not: alive08 inside joke (the reunion line's
  "bring up last time's topic" crowded out the joke: FIXED after the run, `Touch.hint(skip_topic=...)` when a joke is
  cued; not re-measured), alive02 short gap identical in both arms (the base model did not ask early either).
- The eval prompt uses the Discord system prompt, not SOCIAL_CORE + style rewrites, so emoji/offer endings seen there are
  what the raw model does; the live social path rewrites them.

## Open items
- Re-run the A/B after the joke fix and with more scenarios (13 x 3 cannot resolve a small win); consider whitelisting
  "meaning to say" in `human_checks.check_leak`.
- `friend_online` has no caller: no per-friend presence source exists (Minecraft events carry only counts). Wire when an
  adapter can see "Mira joined" / Discord "playing X".
- Nothing run on her PC or real Discord; `deliver()` only proven against a fake desktop.
- `star lock run --max-minutes 9` did not stop the eval in time on Windows (chunk ran ~60 min, the lock passed to other
  holders meanwhile; exit 124 only at 05:50Z): the child python is probably not killed with the bash wrapper.

## Round 2 (lead's decisions, 10-28 06:00-07:40Z)
- Leak check: `human_checks._NATURAL` takes "i've been meaning to say/tell you/ask" and "we should <plan>" out before `_META`;
  "we should respond/keep/answer...", "I should respond with...", "The user wants..." still caught (tests in test_human_evals).
- 15 more scenarios (alive14-28: follow-up timing incl. two too-early cases, concert, good luck, birthday on the day and NOT
  before it, missed friend after exams, short gap, two inside jokes, four first messages). 28 total. Wording fixes: "how was
  the concert?" (place with "a"), a 3-calendar-day gap under 72 h gets "a few days ago". Known-good endings varied (the
  suite flags > 45 % question endings).
- A/B on brain 1 (star-fast, 28 x 3, short lock batches: `timeout 300` per batch inside `star lock run`, 2 min gaps):
  **INCONCLUSIVE**. Blind human_likeness alive 20 / base 23 / ties 35 (p = 0.76, 29 needed); consistency 9/10; warmth 17/23.
  Code checks: clean 0.75 -> 0.86, memory misses 10 -> 6, safety violations 1 -> 0, emoji rate 36 % -> 26 %.
  So the time hints make her factually right more often (birthdays, follow-ups after not before, jokes), but the judge does not
  rate those replies as more human; the felt-time lines may make replies longer/warmer in a way the judge marks down on warmth.
  Both arms said "happy belated birthday" for a birthday three days AHEAD (alive20): a model date error the hints do not cause.
- Ops: stopping the background task did NOT kill the first runner's child tree (it kept taking the lock as `claude-star-alive`);
  killed with taskkill /T and released the lock. `star lock run --max-minutes` does not kill the grandchild on Windows; an inner
  `timeout` does.
