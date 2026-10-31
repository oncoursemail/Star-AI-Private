# Grounded call-presence emotion sources

Handoff gap: `friend_left` and `reunion` existed in the emotion engine but had no
Home call-presence source. This change connects them to the existing Discord
desktop screen reader in `star/home/calls.py`. It adds no Discord bot/API/token,
new account flow, permissions or default emotion activation.

## Evidence and behavior

- The observation must explicitly show a voice call, the same named DM as the
  active friend, and a real boolean `other_joined`. Unknown or incomplete reads,
  another DM, a hidden panel and string values such as `"false"` are ignored.
- A participant must first be observed present. Two consecutive explicit absent
  observations then emit `friend_left` once. Another absent observation adds no
  event. A valid present observation after that departure emits `reunion` once.
  Starting the first call does not invent a reunion.
- The existing watcher checks at most once per 15 seconds, only while Discord is
  already the foreground window. It never changes focus to inspect presence.
  Returning to another app or an unknown read breaks the absence confirmation.
- A process-local set of at most 100 departed handles permits a later confirmed
  reconnection to the same person. No extra names or contact details are written
  to disk. Existing Runtime converts the handle to an opaque friend identifier
  and calls the emotion engine with `only_if_enabled=True`.
- Emotion callback failures do not interrupt the call. Nothing here disconnects
  a friend, sends a message, or changes their relationship record.

This is screen-reader evidence, not verified Discord protocol presence. A
misread screenshot can still be wrong twice; native Discord observation is
required before claiming real behavior. If Discord is behind a game, presence
events wait for Discord to become visible. Capture/model inference time is not
measured here, and this patch does not move it off the existing watcher thread.

This call-presence extension does not emit `left_out`: silence, an unanswered
invitation or an unread message cannot establish exclusion. During integration,
Claude's `8155f4c9` added a separate text-channel `LeftOutWatch` heuristic. That
source was preserved; it is an expression cue, not proof of a friend's motive.
The older missed-call `friend_ignored` behavior is also unchanged.

The merge preserves Claude's spoken-goodbye source and uses a shared latch to
avoid counting the spoken and visible departure twice. A confirmed reunion
resets the latch without replaying an old goodbye from session history. The
integrated Home/emotion/social selection passed 235 tests unchanged.

## Validation

- Standalone offline exercise of the real `DiscordCalls` class: 14 assertions
  covering first observation, debounce, unknown-read reset, matching identity,
  strict booleans, once-only departure/reunion, foreground restriction,
  15-second throttle and a broken emotion callback. Passed.
- `python -m py_compile star/home/calls.py`: passed.
- `git diff --check -- star/home/calls.py`: passed.
- Existing regressions: `python -m pytest -q tests/test_home_wiring.py
  tests/test_emotion.py tests/test_emotion_range.py -p no:cacheprovider`:
  **191 passed in 46.29 seconds**.

No real Discord app, account, audio device, screen, model server or contact was
used for this validation. No evaluator, fixture or existing test was edited.
