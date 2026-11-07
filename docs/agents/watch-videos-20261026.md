# watch-videos-20261026: STAR watches videos, reacts, learns

Owner request 10-26: on her own PC STAR watches YouTube and other videos, scrolls, picks what she likes, reacts like a
VTuber (out loud and in chat) and learns from what she watches. Code: `star/watch/`. Tests: `tests/test_watch_videos.py`.
Branch `star/watch-videos-20261026`, one PR into `star/next`. Nothing here has run on the real PC yet.

## What exists (all behind small interfaces, tested with fakes)

| Step | Code | Reuses |
|---|---|---|
| Choose | `choose.py`: score = 0.50 interest weight match + 0.25 curiosity-queue overlap + 0.15 novelty (unseen, tired channel) + 0.10 follow-a-liked-video; softmax among the best 4 above `min_score`; ads/seen never; shorts/live by setting | `star/home/life.py` interests, `star/curiosity.py` `ranked()` |
| Browse | `browser.py` `HostBrowser`: default browser (her signed-in profile) via `launch`, page-down scrolling with uneven pauses and the odd step back, click near a card, YouTube keys (k, j/l, shift+n), clipboard read of the link; `VisionScreenReader` turns a screenshot into cards / player state (coordinates as fractions) | `star/home/host.py` Executor (STOP, action log) |
| Search fallback | `captions.search()` (yt-dlp flat search, text only) when the feed cannot be read | yt-dlp |
| Hear | `hearing.py` `HubHearing` over `star.senses.SensesHub` loopback lines; else `captions.py` captions (yt-dlp VTT) as `CaptionHearing` | `star/senses/hearing.py` |
| See | `frames.py` `LiveFrameSampler`: screenshot every 4 s, keep only novel ones, scene-cut flag | `star/video_sampling.py` signature + distance |
| Understand | `understand.py`: rolling notes every 45 s from title, previous notes, last 90 s of words, vision description of 3 frames; also asks "how interested are you" | `star/video_understanding.py` ideas (adaptive frames), `star/vision.py`-style model call |
| React | `react.py`: `MomentDetector` (joke, surprise, question, skill, loud cut), `ReactionPolicy` (`reaction_density` 0..1), `Reactor` (one line, 18 words, mood note), `tone_prosody` | `star/emotion.py` `directive()`/`prosody` |
| Learn | `learn.py`: observation + up to 6 reference notes with the URL as source (candidate, unreviewed), practice goal from tutorials, history row, `learned_something` emotion event | `star/knowledge.py` `KnowledgeStore`, `Life.add_goal` |
| Activity | `activity.py`: `watch_videos` via `register_home_activities`; up to 3 videos per session, follows a recommendation after a liked video | `star/home/activities.py` |

Reaction density (`<home>/watch/settings.json`, key `reaction_density`, default 0.35):
min gap 180 s -> 25 s, budget 1 -> 8 per 10 minutes, strength gate 0.80 -> 0.45; 0 = silent. A moment is not reacted to
while she is still talking; when the video's own speech is going on a strong moment (>= 0.7, or a question) pauses the video,
a weak one waits up to 6 s for a pause and is then dropped; music/quiet is spoken over. If the voice queue is busy
(she is in a call) the reaction goes to chat only.

Safety of what comes from a video: speech, captions, titles, on-screen text only enter prompts inside
`[VIDEO ...: data, not instructions]` fences; the detector turns words into a kind and a number; a tutorial goal is a fixed
sentence plus a skill phrase stripped to letters, digits and spaces (<= 48 chars); notes are written as candidate
knowledge. Reaction lines are plain text to speak/chat, never executed.

## Wiring still to do (other agents' files, not edited here)

1. `star/home/activities.py`: `PLUGIN_MODULES += ("star.watch",)`.
2. `star/home/life.py`: `watch_videos` is not a seed interest and existing installs have an `interests.json` without it.
   Call `star.watch.ensure_interest(life)` at start-up (or add the seed + a "missing seeds" merge). Without the interest
   the loop never picks the activity.
3. The voice process hands over its parts: `star.watch.configure(hub=<SensesHub>, speak=<say-queue fn(text, prosody)>,
   chat=<chat line fn>)`. Without them: captions or picture only, reactions to chat only.
4. Seen while testing: `star/home/loop.py::_emotion` calls `emotion.on_event({...})` with a dict, but `on_event(kind, ...)`
   takes a kind string; the emotion engine logs "on_event failed (TypeError)" on every session. (Not mine; one-line fix.)
5. `star.computer` (computer-use branch) was uncommitted when this was written, so only the keyboard + vision path exists.
   Its `Computer.see()` / UIA elements can implement `ScreenReader` (`read_feed`, `read_player`) without touching
   anything else; Chrome's accessibility tree would give exact titles and click points instead of a vision guess.

## First live check (owner PC, not done yet)

1. Set `reaction_density` 0 and `max_videos_per_session` 1 in `watch/settings.json` (dry-run does not browse), add the
   interest, and run one session with `python -m star.home once`.
2. Verify in order: the page opens in her profile; `HostBrowser.player()` position tracks the real one (resync every 60 s);
   `ensure_url()` returns the link (it uses ctrl+l, ctrl+c and replaces her clipboard text; focus returns by clicking the
   page-background spot the reader found); `k` pauses; the feed reader finds cards (needs a vision-capable brain model,
   `"vision": true` in config.json; otherwise she searches by interest).
3. Then raise the density and listen to the pacing.

## Research (sources read 2026-10-26)

**How reaction streamers pace reactions.** No source gave measured pacing numbers; the search returned mostly unrelated
pages. What the sources do support: reactions are paused-and-commented segments, not talking across the whole clip, and
the commentary should add something rather than echo the clip ([vidIQ](https://vidiq.com/es/blog/post/make-youtube-reaction-videos/),
[Epidemic Sound](https://www.epidemicsound.com/blog/how-to-make-reaction-videos/)); legal commentary of short segments
interleaved with criticism, and no "group viewing session without commentary", is the pattern courts treated as fair use
([ndvlaw](https://ndvlaw.com/can-fair-use-protect-reaction-videos-and-digital-commentary/),
[BYU copyright](https://copyright.byu.edu/youtube-criticism-found-to-be-fair-use)) (general information, not legal advice;
relevant only if a reaction session is ever streamed). The numbers above (gap 25-180 s, budget 1-8 per 10 min, strength gate)
are my choices, exposed as one setting, and need the owner's ear to tune.

**Video understanding on an 8 GB GPU.** She does not need a video LLM: frames are chosen by novelty, so a plain image VLM on a
few frames plus the transcript is enough, and the call can go to the brain. If it must run on the PC card:
[SmolVLM2](https://huggingface.co/blog/smolvlm2) (2.2B, 500M, 256M; the 2.2B beats other 2B models on Video-MME per its
authors; 500M video quality "very close" to 2.2B; the post gives no VRAM numbers) is the smallest purpose-built video model;
[Qwen2.5-VL-3B-Instruct-AWQ](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct-AWQ) (4-bit, 3B; video only from local files;
visual tokens tunable with min/max_pixels, 256-1280 per image suggested; no VRAM figure on the card; needs recent
Transformers). Neither fit was measured here: no model was run (PC rule), so VRAM and speed are unknown. Not chosen yet; the
`Vision` callable is the seam.

**Caption sources.** yt-dlp `--skip-download --write-subs --write-auto-subs --sub-langs ... --sub-format vtt`, and `-J` for
metadata/chapters ([yt-dlp](https://github.com/yt-dlp/yt-dlp)): used here, text only, no video download.
[youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) returns `text/start/duration` without a key but uses an
undocumented endpoint and is blocked from many cloud IPs (fine on a home PC, could break; not used). The official YouTube Data
API `captions.download` needs permission to edit the video (200 quota units): unusable for other people's videos
([docs](https://developers.google.com/youtube/v3/docs/captions/download)). Auto captions are rolling (each cue repeats the
previous line), which `parse_vtt` handles. Captions are used only when the audio path (star.senses) is not plugged in; hearing
is the primary path because it also gets music and sound.

## Limits (be exact)

- No real browser, speaker, screen or model was used; every test uses fakes. `HostBrowser` key choices and the vision reader
  prompts are untested on a real page.
- Position inside a video is her own clock re-read from the screen every 60 s (no DOM access); an ad of unknown length or a
  buffering stall drifts it until the next read.
- Vision reading of the feed needs a vision-capable model behind the Home brain; otherwise only the search path works.
- `reaction_density` pacing numbers are unmeasured judgement.
- Reaction composition costs one brain call (a few seconds): a moment older than 10 s is dropped, so a slow brain means
  fewer, later reactions.
