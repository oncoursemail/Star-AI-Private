"""WatchSession: she watches one video that is already playing in her browser.

Every tick (about once a second) it does the same few cheap things and never blocks on a model for long:
  position   browser.player(): where in the video she is, whether an ad plays (skipped, not "watched"), whether it ended
  hearing    new words from the audio path (star.senses) or the captions, and whether the video is talking right now
  frames     a screenshot every `frame_interval_s`; LiveFrameSampler keeps only the novel ones
  moments    MomentDetector: joke / surprise / question / skill / big moment from the words, the sound and the picture
  reaction   ReactionPolicy decides; Reactor writes one short line; she pauses the video (strong moment while it talks)
             or speaks over it (music / quiet), says it out loud with mood-driven prosody and writes it in the chat,
             then resumes. Density is `settings.reaction_density`; at 0 she watches in silence.
  notes      Understanding refreshes every `summary_every_s` (what is happening, who talks, key moments, how
             interested she is); two low answers after `min_watch_s` and she leaves.
Time is injected (clock, sleep), so tests run a video of minutes in milliseconds.
"""
from __future__ import annotations

import random
import time
from typing import Callable

from .frames import LiveFrameSampler
from .model import AudioState, Brain, Browser, HearingSource, Moment, Reaction, Vision, WatchResult
from .react import Decision, MomentDetector, ReactionPolicy, Reactor, tone_prosody
from .settings import WatchSettings
from .understand import Understanding


class WatchSession:
    def __init__(self, *, browser: Browser, hearing: HearingSource | None, brain: Brain | None, vision: Vision | None,
                 speak: Callable[..., bool] | None, chat: Callable[[str], None] | None, settings: WatchSettings,
                 sampler: LiveFrameSampler, mood: Callable[[], str] = lambda: "",
                 prosody: Callable[[], dict | None] = lambda: None, interests: str = "",
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 rng: random.Random | None = None, should_stop: Callable[[], bool] = lambda: False,
                 on_event: Callable[[dict], None] | None = None) -> None:
        self.browser, self.hearing, self.brain, self.vision = browser, hearing, brain, vision
        self.speak, self.chat, self.settings, self.sampler = speak, chat, settings, sampler
        self.prosody, self.interests = prosody, interests
        self.clock, self._sleep, self.should_stop = clock, sleep, should_stop
        self.on_event = on_event or (lambda event: None)
        self.policy = ReactionPolicy(settings, rng=rng)             # lives across videos: the budget is per ten minutes
        self.reactor = Reactor(brain, mood=mood) if brain is not None else None
        self._talking_until = 0.0

    # -- one reaction -----------------------------------------------------------------------------------
    def _say(self, line: str, prosody: dict | None) -> bool:
        if self.speak is None:
            return False
        try:
            return bool(self.speak(line, prosody))
        except TypeError:
            return bool(self.speak(line))

    def _react(self, moment: Moment, decision: Decision, under: Understanding, created: float,
               result: WatchResult) -> bool:
        line = self.reactor.compose(moment, under.title, under.summary, under.tail(30.0, 400)) if self.reactor else ""
        if not line or self.clock() - created > self.settings.stale_moment_s:
            return False
        paused = decision.action == "pause_and_say"
        if paused:
            self.browser.pause()
        try:
            spoken = self._say(line, tone_prosody(self.prosody(), moment.kind))
            chatted = False
            if self.settings.chat_reactions and self.chat is not None:
                self.chat(line)
                chatted = True
            hold = min(8.0, 0.5 + 0.07 * len(line)) if spoken else 0.0
            if paused and hold:
                self._sleep(hold)                  # let her finish the sentence before the video goes on
        finally:
            if paused:
                self.browser.play()
        if not (spoken or chatted):
            return False
        now = self.clock()
        self._talking_until = now + (0.0 if paused else hold)
        self.policy.reacted(now)
        result.reactions.append(Reaction(moment.at, moment.kind, line, paused, spoken, chatted))
        self.on_event({"type": "reaction", "kind": moment.kind, "text": line, "paused": paused})
        return True

    # -- the watching loop ------------------------------------------------------------------------------
    def watch(self, *, title: str = "", channel: str = "", description: str = "", chapters: list | None = None,
              max_seconds: float | None = None) -> WatchResult:
        settings = self.settings
        limit = min(max_seconds if max_seconds is not None else 1e9, settings.max_video_minutes * 60)
        state = self.browser.player()
        under = Understanding(state.title or title, state.channel or channel, description, chapters)
        result = WatchResult(url=state.url, title=under.title, channel=under.channel)
        detector = MomentDetector()
        start = last_frame = self.clock()
        pending: list[tuple[Moment, float]] = []
        ad_s = 0.0
        try:
            while True:
                now = self.clock()
                if self.should_stop():
                    result.stopped = "stop"
                    break
                if now - start - ad_s >= limit:
                    result.stopped = "time"
                    break
                state = self.browser.player()
                if state.url and not result.url:
                    result.url = state.url
                if state.ad:
                    self.browser.skip_ad()
                    ad_s += settings.tick_s
                    self._sleep(settings.tick_s)
                    continue
                if state.ended:
                    result.stopped = "ended"
                    break
                position = state.position_s
                lines = self.hearing.poll(position) if self.hearing else []
                audio = self.hearing.state(position) if self.hearing else None
                under.add_lines(lines)
                frame = None
                if now - last_frame >= settings.frame_interval_s:
                    last_frame = now
                    shot = self.browser.screenshot()
                    frame = self.sampler.offer(shot, position) if shot else None
                for moment in detector.feed(lines, audio or AudioState(), frame, position):
                    under.add_moment(moment)
                    result.moments += 1
                    pending.append((moment, now))
                self._handle_pending(pending, under, audio, now, result)
                if under.due(now, settings.summary_every_s):
                    under.update(self.brain, self.vision, self.sampler.pick(3), now, position, self.interests)
                    if under.low_streak >= 2 and now - start >= settings.min_watch_s:
                        result.stopped = "lost_interest"
                        break
                self._sleep(settings.tick_s)
        finally:
            self.browser.play()                  # never leave her video paused by a reaction
        result.watched_s = max(0.0, self.clock() - start - ad_s)
        result.duration_s = state.duration_s
        result.lines, result.frames = under.line_count, self.sampler.offered
        result.summary, result.interest = under.summary, under.interest
        result.key_moments, result.transcript = list(under.key_moments), under.tail(600.0, 3000)
        result.url = result.url or state.url
        result.title, result.channel = under.title or result.title, under.channel or result.channel
        return result

    def _handle_pending(self, pending: list, under: Understanding, audio, now: float, result: WatchResult) -> None:
        pending.sort(key=lambda item: -item[0].strength)
        keep = []
        acted = False
        talking = now < self._talking_until
        for moment, created in pending:
            if acted or now - created > self.settings.speak_over_gap_s + self.settings.stale_moment_s:
                continue
            decision = self.policy.decide(moment, now, audio or AudioState(), talking=talking)
            if decision.action == "wait":
                if now - created <= self.settings.speak_over_gap_s:
                    keep.append((moment, created))
                continue
            if decision.action in ("pause_and_say", "say_over"):
                acted = self._react(moment, decision, under, created, result)
        pending[:] = keep
