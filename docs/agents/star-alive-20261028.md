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

## Progress
- (in progress)
