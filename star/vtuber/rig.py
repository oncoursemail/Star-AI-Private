"""The live rig: mouth frames + mood + events -> one Pose per video frame (what the model or a VMC receiver is told).

star.stream_motion plans a whole utterance offline (<= 15 s); a camera runs forever, so this is the incremental
version of the same ideas, with the same cue names (surprise, joy, laugh, focus, nod) and the same decay curves:
  mouth      smoothed (fast attack, slower release) so speech never flickers; vowel weights are smoothed too
  eyes       blinks every 2.4-4.4 s (a quick double now and then), micro-saccades, gaze that follows a 'focus' cue
  idle       breathing, slow head sway, hair/ear/tail follow-through; louder speech moves the head a little more
  mood       emotion.current()["avatar"] = {face, cue, strength, energy}: face is held, a new cue fires once
  events     react(kind): game_danger -> surprise, game_success -> joy, video_funny -> laugh, ... (REACTIONS)
Everything is deterministic for a given seed and clock, so it is tested with a fake clock.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..stream_motion import CUES, MODES
from .lipsync import SILENT, VISEMES, MouthFrame

# event kind -> (cue, strength). The first block is the vocabulary star.stream_stage already uses.
REACTIONS: dict[str, tuple[str, float] | None] = {
    "owner_interrupt": None,
    "game_danger": ("surprise", 0.50),
    "game_success": ("joy", 0.75),
    "game_observation": ("focus", 0.35),
    "viewer_question": ("nod", 0.35),
    "viewer_comment": ("nod", 0.25),
    "ambient": None,
    # video / call / game events from the watch and play packages
    "video_funny": ("laugh", 0.8),
    "video_surprise": ("surprise", 0.7),
    "video_nice": ("joy", 0.6),
    "game_win": ("joy", 1.0),
    "game_fail": ("surprise", 0.35),
    "game_funny": ("laugh", 0.7),
    "call_greeting": ("joy", 0.7),
    "friend_joined": ("joy", 0.6),
    "heard_name": ("nod", 0.6),
    "agree": ("nod", 0.7),
}

FACE_OF_CUE = {"surprise": "stopped", "laugh": "happy", "joy": "happy"}     # StarFace mood names; see model.py
CUE_SECONDS = 1.5


@dataclass(frozen=True)
class Pose:
    t: float
    face: str                       # StarFace mood name: idle|happy|looking|oops|thinking|writing|stopped|listening
    mouth_open: float
    viseme: str                     # dominant vowel shape or "sil"
    shape: tuple                    # weights in lipsync.VISEMES order (aa, ih, ou, ee, oh), scaled by mouth_open
    eye_open_left: float
    eye_open_right: float
    smile: float
    brow_raise: float
    head_x: float
    head_y: float
    head_roll: float
    body_lean: float
    breath: float
    shoulder_lift: float
    gaze_x: float
    gaze_y: float
    hair_sway: float
    ear_left: float
    ear_right: float
    tail_sway: float

    def params(self) -> dict[str, object]:
        """Everything a binding in the model manifest can name."""
        values = {k: getattr(self, k) for k in self.__dataclass_fields__ if k not in ("shape", "viseme", "face", "t")}
        values["blink"] = 1.0 - (self.eye_open_left + self.eye_open_right) / 2.0
        values["talk"] = self.mouth_open
        for name, weight in zip(VISEMES, self.shape):
            values["v_" + name] = weight
        values["face"] = self.face
        values["viseme"] = self.viseme
        return values


def _c(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class _Active:
    start: float
    kind: str
    strength: float
    target_x: float = 0.0


@dataclass
class LiveRig:
    mode: str = "normal"
    reduced_motion: bool = False
    seed: int = 7
    _rng: random.Random = field(init=False, repr=False)
    _last_t: float | None = field(default=None, init=False)
    _mouth: float = field(default=0.0, init=False)
    _shape: list = field(default_factory=lambda: [0.0] * 5, init=False)
    _next_blink: float = field(default=0.0, init=False)
    _blink_start: float = field(default=-9.0, init=False)
    _double: bool = field(default=False, init=False)
    _face: str = field(default="idle", init=False)
    _energy: float = field(default=0.35, init=False)
    _mood_cue: str | None = field(default=None, init=False)
    _cues: list = field(default_factory=list, init=False)
    _saccade: tuple = field(default=(0.0, 0.0), init=False)
    _next_saccade: float = field(default=0.0, init=False)
    _gaze: list = field(default_factory=lambda: [0.0, 0.0], init=False)
    _phase: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError("mode must be normal, cat or puppy")
        self._rng = random.Random(self.seed)
        self._phase = (self.seed % 997) / 997.0 * 2 * math.pi

    # -- inputs ----------------------------------------------------------------------------------------------
    def set_mood(self, avatar: dict | None) -> None:
        """emotion.current()["avatar"]: hold the face, fire a cue only when it changes (not every poll)."""
        if not avatar:
            self._face, self._energy, self._mood_cue = "idle", 0.35, None
            return
        face = str(avatar.get("face") or "idle")
        self._face = face
        self._energy = _c(float(avatar.get("energy", 0.35)), 0.0, 1.0)
        cue = avatar.get("cue")
        if cue in CUES and cue != self._mood_cue and self._last_t is not None:
            self._cues.append(_Active(self._last_t, cue, _c(float(avatar.get("strength", 0.5)), 0.0, 1.0)))
        self._mood_cue = cue if cue in CUES else None

    def react(self, kind: str, strength: float = 1.0, *, target_x: float = 0.0, now: float | None = None) -> bool:
        """An event from a game, video or call. Unknown kinds and kinds with no cue are ignored (False)."""
        reaction = REACTIONS.get(kind)
        if reaction is None:
            return False
        cue, base = reaction
        start = now if now is not None else (self._last_t if self._last_t is not None else 0.0)
        self._cues.append(_Active(start, cue, _c(base * _c(strength, 0.0, 1.0) * 1.25, 0.0, 1.0), _c(target_x)))
        del self._cues[:-8]
        return True

    # -- one frame -------------------------------------------------------------------------------------------
    def step(self, t: float, mouth: MouthFrame = SILENT) -> Pose:
        dt = 1 / 30 if self._last_t is None else max(1e-4, min(0.25, t - self._last_t))
        first = self._last_t is None
        self._last_t = t
        if first:
            self._next_blink = t + 1.2 + self._rng.uniform(0.0, 1.5)
            self._next_saccade = t + 0.8

        target = mouth.open
        tau = 0.040 if target > self._mouth else 0.080
        k = 1 - math.exp(-dt / tau)
        self._mouth += (target - self._mouth) * k
        if self._mouth < 0.004:
            self._mouth = 0.0
        for i in range(5):
            self._shape[i] += (mouth.shape[i] - self._shape[i]) * (1 - math.exp(-dt / 0.05))
        weights = [w * self._mouth for w in self._shape]

        smile = brow = laugh = surprise = nod = gaze_cue = 0.0
        self._cues = [c for c in self._cues if t - c.start <= CUE_SECONDS]
        for c in self._cues:
            age = t - c.start
            if age < 0:
                continue
            if c.kind == "joy":
                smile = max(smile, c.strength * 0.60 * math.exp(-age / 1.0))
            elif c.kind == "laugh":
                pulse = math.exp(-age / 0.65)
                laugh = max(laugh, c.strength * pulse)
                smile = max(smile, 0.8 * c.strength * pulse)
            elif c.kind == "surprise":
                surprise = max(surprise, c.strength * math.exp(-age / 0.45))
                brow = max(brow, 0.85 * c.strength * math.exp(-age / 0.45))
            elif c.kind == "focus":
                gaze_cue = c.target_x * c.strength * math.exp(-age / 1.1)
            elif c.kind == "nod":
                nod += c.strength * math.exp(-age / 0.5) * math.sin(age * math.pi * 3)
        if self._face == "happy":
            smile = max(smile, 0.35)

        # blinks: a quick close-open of 150 ms, sometimes twice in a row
        if t >= self._next_blink:
            self._blink_start = t
            if self._double:
                self._double = False
                self._next_blink = t + self._rng.uniform(2.4, 4.4)
            elif self._rng.random() < 0.15:
                self._double, self._next_blink = True, t + 0.3
            else:
                self._next_blink = t + self._rng.uniform(2.4, 4.4)
        age = t - self._blink_start
        closing = max(0.0, 1.0 - abs(age - 0.075) / 0.075) if 0 <= age <= 0.15 else 0.0
        eyes = _c(1.0 - closing - 0.12 * smile, 0.0, 1.0)         # a smile squints the eyes a little

        # gaze: slow drift + micro-saccades, pulled toward a focus cue
        if t >= self._next_saccade:
            self._saccade = (self._rng.uniform(-0.12, 0.12), self._rng.uniform(-0.08, 0.08))
            self._next_saccade = t + self._rng.uniform(0.6, 2.2)
        want = (_c(gaze_cue + self._saccade[0]), self._saccade[1])
        for i in (0, 1):
            self._gaze[i] += (want[i] - self._gaze[i]) * (1 - math.exp(-dt / 0.08))

        twopi, ph = 2 * math.pi, self._phase
        speaking = min(1.0, self._mouth * 1.5)
        if self.reduced_motion:
            head_x = head_y = roll = lean = shoulder = hair = ear_l = ear_r = tail = breath = 0.0
        else:
            amp = 1.0 + 0.8 * speaking * (0.5 + self._energy)
            head_x = 0.035 * amp * math.sin(twopi * t / 5.2 + ph) + self._gaze[0] * 0.09
            head_y = 0.018 * amp * math.sin(twopi * t / 7.0 + ph) + 0.13 * nod + 0.02 * speaking * math.sin(twopi * 2.3 * t)
            head_y += 0.035 * laugh * math.sin(twopi * 4 * t)
            roll = 0.03 * math.sin(twopi * t / 6.1 + ph * 0.5) + 0.04 * self._mouth * math.sin(twopi * 1.7 * t)
            lean = 0.42 * head_x
            shoulder = 0.09 * laugh + 0.03 * surprise
            breath = 0.5 + 0.5 * math.sin(twopi * t / 4.0 + ph)
            hair = 0.07 * math.sin(twopi * t / 5.2 + ph - 0.45) + 0.11 * head_x
            if self.mode == "cat":
                tail = 0.25 * math.sin(twopi * t / 2.2 + ph) + 0.12 * laugh
                ear_l, ear_r = _c(0.28 * surprise - 0.14 * laugh), _c(0.23 * surprise - 0.10 * laugh)
            elif self.mode == "puppy":
                tail = 0.35 * math.sin(twopi * t / 1.4 + ph) * (0.25 + smile)
                ear_l, ear_r = _c(-0.15 * laugh + 0.14 * surprise), _c(-0.12 * laugh + 0.12 * surprise)
            else:
                ear_l = ear_r = tail = 0.0

        face = self._face
        if surprise > 0.45:
            face = FACE_OF_CUE["surprise"]
        elif laugh > 0.4:
            face = "happy"
        top = "sil" if self._mouth <= 0.02 else VISEMES[max(range(5), key=lambda i: weights[i])]
        return Pose(t, face, _c(self._mouth, 0, 1), top, tuple(round(w, 4) for w in weights), eyes, eyes,
                    _c(smile, 0, 1), _c(brow, 0, 1), _c(head_x), _c(head_y), _c(roll), _c(lean), _c(breath, 0, 1),
                    _c(shoulder, 0, 1), _c(self._gaze[0]), _c(self._gaze[1]), _c(hair), ear_l, ear_r, _c(tail))

    def neutral(self, t: float) -> Pose:
        """Immediate rest pose after an interrupted utterance or a stop."""
        self._mouth = 0.0
        self._shape = [0.0] * 5
        self._cues.clear()
        return self.step(t, SILENT)
