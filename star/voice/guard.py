"""Artefact guard: check every synthesised chunk and re-make the bad ones with a new seed.

Neural speech engines sometimes skip or garble words, loop on a syllable, leave long holes, clip, jump in loudness,
squeak in pitch or (for a cloned voice) drift away from the voice. Each check below catches one of those:

  asr        transcribe the chunk and compare with the intended words (word error rate); skipped or garbled words
  loop       repeated word n-grams in the transcript that the intended text does not have (stutter loops)
  length     duration far outside what the word count allows (a loop, a ramble, or a cut-off)
  silence    a hole longer than MAX_INNER_SILENCE inside the chunk
  clipping   too many samples at full scale
  jump       a sudden loudness jump between neighbouring 50 ms frames well above the chunk's own speech level
  pitch      pitch spikes: neighbouring voiced frames more than PITCH_JUMP_ST apart, again and again
  speaker    for a cloned or locked voice: similarity to the reference voice below `min_similarity`

GuardedTTS wraps any engine with synthesize(text, seed=...) and returns the first chunk that passes, trying up to
`attempts` seeds; if none passes it returns the attempt with the fewest problems (never silence) and counts it.
stats() gives the rejection rate; every rejection is also appended to an optional JSON-lines log.

numpy is needed for the signal checks; the ASR and speaker checks use injected objects so tests run with fakes.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_WER = 0.34
MAX_INNER_SILENCE = 1.1          # seconds
MAX_CLIP_SHARE = 0.002
JUMP_DB = 14.0
PITCH_JUMP_ST = 7.0
PITCH_JUMP_LIMIT = 3             # this many big jumps in one chunk = a squeak, not a natural leap
MIN_SECONDS_PER_WORD, MAX_SECONDS_PER_WORD = 0.12, 1.1
MIN_SIMILARITY = 0.75


def words_of(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower().replace("’", "'"))


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate (substitutions + deletions + insertions over reference words)."""
    ref, hyp = words_of(reference), words_of(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def repeated_ngrams(text: str, n: int = 2, times: int = 3) -> list[str]:
    """N-grams that occur `times` or more in a row-ish (anywhere in the text)."""
    w = words_of(text)
    counts: dict[tuple, int] = {}
    for i in range(len(w) - n + 1):
        key = tuple(w[i:i + n])
        counts[key] = counts.get(key, 0) + 1
    return [" ".join(k) for k, c in counts.items() if c >= times]


def new_loops(intended: str, heard: str) -> list[str]:
    """Loops in what was heard that the intended text does not contain itself ("no, no, no" on purpose is fine)."""
    found = []
    for n, times in ((1, 4), (2, 3), (3, 2)):
        planned = set(repeated_ngrams(intended, n, times))
        found += [g for g in repeated_ngrams(heard, n, times) if g not in planned]
    return found


@dataclass
class Report:
    ok: bool
    problems: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class ArtefactGuard:
    """Runs the checks. `asr` has transcribe(pcm16_bytes, sample_rate) -> str (16 kHz is resampled to inside the
    real ASR); `embedder` has embed(float_samples, sample_rate) -> vector. Either may be None (check skipped)."""

    def __init__(self, asr=None, embedder=None, *, max_wer: float = MAX_WER, min_similarity: float = MIN_SIMILARITY,
                 check_asr: bool = True) -> None:
        self.asr, self.embedder = asr, embedder
        self.max_wer, self.min_similarity, self.check_asr = max_wer, min_similarity, check_asr

    def check(self, samples, sr: int, text: str, *, reference=None, speech: bool = True) -> Report:
        import numpy as np
        from . import voicedsp
        x = np.asarray(samples, dtype=np.float32)
        problems, metrics = [], {}
        seconds = x.size / sr if sr else 0.0
        metrics["seconds"] = round(seconds, 3)
        if x.size == 0:
            return Report(False, ["empty"], metrics)
        clip_share = float(np.mean(np.abs(x) >= 0.999))
        metrics["clip_share"] = round(clip_share, 5)
        if clip_share > MAX_CLIP_SHARE:
            problems.append("clipping")
        levels = voicedsp.frame_db(x, sr, 0.05)
        loud = levels[levels > levels.max() - 40.0]
        speech_level = float(np.median(loud)) if loud.size else -120.0
        jumps = np.diff(levels)
        metrics["max_jump_db"] = round(float(jumps.max()) if jumps.size else 0.0, 1)
        if jumps.size and np.any((jumps > JUMP_DB) & (levels[1:] > speech_level + 9.0)):
            problems.append("jump")
        if speech:
            silence = _longest_inner_silence(levels, 0.05, speech_level - 30.0)
            metrics["inner_silence"] = round(silence, 2)
            if silence > MAX_INNER_SILENCE:
                problems.append("silence")
            n_words = len(words_of(text))
            if n_words:
                per_word = seconds / n_words
                metrics["seconds_per_word"] = round(per_word, 3)
                low = MIN_SECONDS_PER_WORD if n_words > 2 else 0.05
                high = MAX_SECONDS_PER_WORD if n_words > 2 else 2.5
                if per_word < low or per_word > high:
                    problems.append("length")
            spikes = _pitch_spikes(x, sr)
            metrics["pitch_spikes"] = spikes
            if spikes >= PITCH_JUMP_LIMIT:
                problems.append("pitch")
            if self.asr is not None and self.check_asr and n_words:
                heard = self.asr.transcribe(voicedsp.as_pcm(x), sr)
                metrics["heard"] = heard
                error = wer(text, heard)
                metrics["wer"] = round(error, 3)
                if error > (self.max_wer if n_words >= 4 else max(self.max_wer, 0.5)):
                    problems.append("asr")
                loops = new_loops(text, heard)
                if loops:
                    metrics["loops"] = loops
                    problems.append("loop")
        if reference is not None and self.embedder is not None:
            similarity = cosine(self.embedder.embed(x, sr), reference)
            metrics["similarity"] = round(similarity, 3)
            if similarity < self.min_similarity:
                problems.append("speaker")
        return Report(not problems, problems, metrics)


def cosine(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a, dtype=np.float64).ravel(), np.asarray(b, dtype=np.float64).ravel()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / denom) if denom else 0.0


def _longest_inner_silence(levels, frame: float, threshold: float) -> float:
    quiet = levels < threshold
    loud_idx = [i for i, q in enumerate(quiet) if not q]
    if len(loud_idx) < 2:
        return 0.0
    longest = run = 0
    for q in quiet[loud_idx[0]:loud_idx[-1] + 1]:
        run = run + 1 if q else 0
        longest = max(longest, run)
    return longest * frame


def _pitch_spikes(x, sr: int) -> int:
    """Count jumps larger than PITCH_JUMP_ST between neighbouring voiced 20 ms frames (autocorrelation pitch)."""
    import numpy as np
    f0 = pitch_track(x, sr)
    voiced = f0 > 0
    count = 0
    for i in range(1, f0.size):
        if voiced[i] and voiced[i - 1]:
            jump = abs(12.0 * np.log2(f0[i] / f0[i - 1]))
            # Jumps of about one or two octaves are the tracker locking onto a harmonic (measured on the clean Kokoro
            # samples: every flagged jump was 11-12 or 19-24 semitones), not a squeak in the voice.
            octave_slip = min(abs(jump - 12.0), abs(jump - 19.0), abs(jump - 24.0)) < 1.3
            if jump > PITCH_JUMP_ST and not octave_slip:
                count += 1
    return count


def pitch_track(x, sr: int, frame: float = 0.02, fmin: float = 70.0, fmax: float = 600.0):
    """Simple normalised-autocorrelation pitch per frame (0 = unvoiced). Good enough to spot squeaks."""
    import numpy as np
    size = int(frame * sr * 2)
    hop = int(frame * sr)
    x = np.asarray(x, dtype=np.float32)
    if x.size < size:
        return np.zeros(0)
    frames = np.lib.stride_tricks.sliding_window_view(x, size)[::hop]
    frames = frames - frames.mean(axis=1, keepdims=True)
    energy = np.sum(frames ** 2, axis=1)
    spec = np.fft.rfft(frames, 2 * size, axis=1)
    ac = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :size]
    lo, hi = int(sr / fmax), min(size - 1, int(sr / fmin))
    lag = lo + np.argmax(ac[:, lo:hi], axis=1)
    strength = ac[np.arange(ac.shape[0]), lag] / np.maximum(ac[:, 0], 1e-9)
    loud = energy > (np.max(energy) * 1e-3)
    f0 = np.where((strength > 0.5) & loud, sr / lag, 0.0)
    return f0


class GuardStats:
    def __init__(self, log_path: str | Path | None = None) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.chunks = self.attempts = self.rejected = self.gave_up = 0
        self.reasons: dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, text: str, attempt: int, report: Report, engine: str = "") -> None:
        with self._lock:
            self.attempts += 1
            if not report.ok:
                self.rejected += 1
                for reason in report.problems:
                    self.reasons[reason] = self.reasons.get(reason, 0) + 1
                if self.log_path:
                    self.log_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.log_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"at": round(time.time(), 1), "engine": engine, "attempt": attempt,
                                            "text": text[:200], "problems": report.problems,
                                            "metrics": {k: v for k, v in report.metrics.items() if k != "heard"}})
                                + "\n")

    def summary(self) -> dict:
        with self._lock:
            rate = self.rejected / self.attempts if self.attempts else 0.0
            return {"chunks": self.chunks, "attempts": self.attempts, "rejected": self.rejected,
                    "rejection_rate": round(rate, 3), "gave_up": self.gave_up, "reasons": dict(self.reasons)}


class GuardedTTS:
    """synthesize(text) through `engine`, checked by `guard`; bad chunks are re-made with seeds 1..attempts-1.

    `engine.synthesize_float(text, seed=...)` must return (float samples, sample_rate). `reference` is the voice
    embedding for clone/locked voices (speaker check), or None."""

    def __init__(self, engine, guard: ArtefactGuard, attempts: int = 3, stats: GuardStats | None = None,
                 reference=None, name: str = "") -> None:
        self.engine, self.guard, self.attempts = engine, guard, max(1, attempts)
        self.stats = stats or GuardStats()
        self.reference, self.name = reference, name or type(engine).__name__

    def render(self, text: str, **kwargs):
        best = None
        for attempt in range(self.attempts):
            samples, sr = self.engine.synthesize_float(text, seed=attempt, **kwargs)
            report = self.guard.check(samples, sr, text, reference=self.reference)
            self.stats.record(text, attempt, report, self.name)
            if report.ok:
                with self.stats._lock:
                    self.stats.chunks += 1
                return samples, sr, report
            if best is None or len(report.problems) < len(best[2].problems):
                best = (samples, sr, report)
        with self.stats._lock:
            self.stats.chunks += 1
            self.stats.gave_up += 1
        return best


def report_dict(report: Report) -> dict:
    return asdict(report)
