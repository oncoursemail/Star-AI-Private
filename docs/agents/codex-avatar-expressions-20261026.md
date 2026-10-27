# Timed expressions on the live avatar

Continues the owner's request for facial control during stream moments and chat
reading. Existing `LiveRig` already supplies mood, blinks, head motion and
game/video reaction cues. `star/vtuber/expressions.py` adds a short expression
layer to that live path. It does not replace the rig or turn on the evaluated
emotion engine.

## Runtime path

`StarCamera._on_event` stamps each cue at receipt. `ExpressionTimeline` receives
that typed event immediately, while the rig's existing body-motion queue keeps
the same receipt timestamp. Each frame first computes the normal rig Pose,
then applies the expression overlay before rendering/sending it. A stalled
camera therefore does not turn an old event into a fresh surprised face.

`LocalFeed.clear()` clears speech frames and emits `owner_interrupt`; the
expression clears immediately and the rig resets on its next frame. Camera
stop clears pending cues and rejects new events. The Home facial activities
respect STOP, interruption and dry-run. Loopback delivery is cosmetic and
unacknowledged: requesting an expression is not proof the viewer saw it.

Explicit controls, with an already configured camera:

```powershell
python -m star.vtuber expression smile --seconds 1.8 --strength 0.7
python -m star.vtuber expression reading_chat --seconds 2.4
python -m star.vtuber expression neutral
```

These do not start a camera or send a chat message. The helper
`emit_expression(name, duration_s=..., strength=...)` encodes the cue into the
existing bounded local event field; it is not a new general command transport.

Named expressions: `smile`, `laugh`, `surprise`, `thinking`, `reading_chat`,
`concerned`, `proud`, plus immediate `neutral`. A cue lasts 0.4–4 seconds with a
smooth attack and release. There is one active cue and no queue to replay later.
Repeated active cues cannot extend their deadline; a 2.5-second same-cue
cooldown, 0.6-second spacing and eight-cue/20-second budget limit chatter.
Higher-priority moment cues can preempt chat-reading cues. STOP/neutral is never
blocked by that budget.

Existing typed events map to modest expressions: `viewer_question`,
`viewer_comment`, `chat_reading`, `game_danger`, `game_win`, `video_funny`, and
other fixed IDs. `chat_reading_end` clears a current reading expression. The
chat host must emit these only when it actually selects a moderated message or
observes a moment. Raw chat, viewer commands and emote strings are not parsed
as expression instructions here. This module neither authenticates EventSub
nor substitutes for its deduplication or moderation.

## Mouth and baseline behavior

Only face selection, smile, brows, eye squint and gaze are overlaid. Mouth
opening, viseme weights, speech timing and body/head movement are unchanged.
An eye already closed for a blink or wink cannot be reopened by an expression.
On expiry the overlay returns to the underlying rig/mood Pose. Thus a genuine
enabled mood can remain visible; release does not erase it or change emotion
settings. These are visual performance cues, not evidence of feelings.

Visible results depend on the model's bindings. The existing painted StarFace
pack changes whole face images and has mouths painted in; it still cannot show
independent vowel art. A layered avatar needs authored mouth shapes and facial
bindings for the full result. The VMC sink currently carries the existing
smile/blink controls, not every new face name or brow/gaze parameter. No Live2D
model, `.exp3.json` file or VTube Studio plugin connection was fabricated.

## Verification

`python scripts/verify_avatar_expressions.py` uses fake clocks, a minimal fake
renderer and memory sinks. It exercises the actual `StarCamera` feed/tick path,
expiry after a frame stall, speech independence, blink preservation, fades,
priority/cooldowns/budget, thread contention, interruption/stop and malformed
datagrams. No camera/audio device, network connection, model/GPU inference,
emotion database or external chat is used. Existing `tests/test_vtuber_camera.py`
is run unchanged. Real avatar appearance and Twitch/Discord delivery still need
the target-PC acceptance run.

## Primary-source research checked 2026-10-26 (America/Chicago)

- [Twitch receiving chat](https://dev.twitch.tv/docs/chat/send-receive-messages)
  specifies `channel.chat.message` EventSub delivery and structured message
  fragments. Those are chat data for the host to select/moderate, not cosmetic
  control authority. This change makes no Twitch subscriptions or API writes.
- [VTube Studio expression control](https://github.com/DenchiSoft/VTubeStudio#requesting-activation-or-deactivation-of-expressions)
  supports activation/deactivation with a fade time. Its documentation recommends
  hotkeys to avoid expressions users cannot turn off. The local timeline follows
  that lifecycle principle by always expiring and providing immediate neutral;
  it does not claim to implement the VTube Studio protocol.
- [Live2D expression settings](https://docs.live2d.com/en/cubism-editor-manual/setting-and-exporting-facial-expressions/)
  describes model-authored expression parameters and fades. It supports keeping
  expression controls separate from the spoken mouth track, while the exact
  visible result still requires matching art and rig bindings.
