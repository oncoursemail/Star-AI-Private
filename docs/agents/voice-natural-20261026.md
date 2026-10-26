# voice-natural-20261026 (Claude): varied voice openers + desktop chat mid-reply plan guard

Branch `star/voice-natural-20261026`, worktree `worktrees/voice-natural`, PR into `star/next`. Board item #249.
Follow-up to `docs/agents/human-voice-20261025.md` ("Not done / follow-ups").

## 1. Desktop plain chat: mid-reply plans (DONE, tested)
`star/agent.py read_stream(guard=True)` + `star/reasoning_guard.py` (`prose_only`, `plan_start`, `safe_end`):
- Plain chat now streams whole sentences; an unfinished sentence is held back at most `HOLD_CHARS` = 60 characters.
  Cost: the first visible text appears at the first sentence end or after 60 characters, not at the first token.
- A sentence matching `persona.leaked_reasoning` is never shown. Nothing shown before it: `ReasoningLoop` (the existing
  hand-over to the main model). Something shown: the reply ends at the sentence before it. Fenced code is not checked.
- Known trade-off: `persona._REASONING` also matches ordinary phrases ("I should mention", "status line") outside
  code blocks; such a sentence in a plain chat answer is cut. If that shows up, narrow the pattern list for desktop.
- Tests (`tests/test_reasoning_guard.py`, 4 new): plan-after-answer and plan-first fail before the change (2 of 4
  failed on the old code), pass after. Related suites (agent runtime, first token, routing, document chat, etc.) pass.

## 2. Varied voice openers (CODE DONE, DEFAULT OFF, LIVE MEASUREMENT PENDING)
`CallConfig.varied_openers` (default False): the opener rule's example phrases leave the system prompt (it describes
the reaction), and each turn's user message gets `persona.opener_hint(turn, style)`: three short reactions from a pool of
12, a different three each turn. The hint is never in the history; the plan-retry keeps it. Off = requests byte-identical
to before. `CallSession._turn_messages` builds the request. Tests: `tests/test_voice_natural.py` (9 passed).

Measurement NOT done: brain 1 was busy with the sealed eval (399 tasks; 282/399 at 04:44Z 10-26, ETA about 09:00-11:00Z),
and no load was allowed on it. Harness checked against a local mock server only (no model numbers exist).

### Remaining steps (after the sealed eval ends; check `~/.star/sealed/drivers/evp_driver.log`, process evp_driver.py gone)
From the repo root of the worktree, `STAR_BRAIN_URL=http://<brain 1 container>:8080/v1` (address from `lxc list starai`),
venv python, `PYTHONPATH=.`, `APPDATA=<temp>`. Each arm is 100 replies (20 prompts x 5), 2 threads, a few minutes:
```
../../star.cmd lock run --owner claude --holder voice-natural --server 1 --max-minutes 9 -- python tools/human_voice_eval/opener_eval.py base 5 base.json
... same for: described 5 described.json   and   hint 5 hint.json
```
(Use `--owner codex` if Codex runs it; no lock needed if the lock tool refuses and nothing else is running.)
Report per arm: distinct-opener rate, top opener and its share, leaks (must be 0), guard fired, check_reply problems,
mean words. Read ~30 replies of each arm blind for persona quality (fit of the opener to what was said, no
"sweetheart" in every reply, no invented events). Baseline from the last agent: "Oh, well done." in 57 of 100.
Decision: if `hint` (or `described`) beats `base` on distinct rate and top share with leaks 0 and no quality loss, make
`varied_openers` the default in `CallConfig` (and note which arm; if only `described` helped, drop the hint). Otherwise
leave it off. Then fill the numbers in the PR body and add one line to STATE.md.
Other options not tried: regenerate when the opener repeats the last N turns (costs a second model call before the first
spoken sentence, bad for a call); a repetition penalty (llama.cpp penalises the whole context, not the opener).
