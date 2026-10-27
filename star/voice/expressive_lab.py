"""Expressive voice lab: render samples, measure them, benchmark engines, build the sound bank, serve the A/B page.

  python -m star.voice.expressive_lab bank     --home H                 # non-verbal clips in her voice -> H/sounds
  python -m star.voice.expressive_lab samples  --out DIR [--neural]     # one WAV (+MP3) per style/sound/song/character
  python -m star.voice.expressive_lab bench    --out DIR [--engines kokoro,qwen3-tts,...]
  python -m star.voice.expressive_lab measure  --out DIR                # level/spectrum table of every WAV in DIR
  python -m star.voice.expressive_lab ab-serve --out DIR [--port 8766]  # listening page; ratings -> DIR/ratings.jsonl

v1 commands (bank, samples) render the v1 round; the v2 round (Star's designed voices, model-native emotion per engine,
native non-verbals) is rendered by tools/voice_v2/ (docs/agents/voice-v2-20261027.md).

Needs the voice packages (numpy, kokoro-onnx, onnxruntime; pyworld for styles and songs; torch + faster-qwen3-tts /
chatterbox-tts for --neural). STAR_VOICE_MODELS must point at the Kokoro model folder.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

LINE = "I'm so proud of you. You worked really hard today. Do you want to tell me about it?"
STYLE_LINES = {
    "whisper": "Come here, I have a little secret for you.", "asmr": "Close your eyes. Breathe in slowly, and let it go.",
    "sleepy": "Mm, it's getting late, sweetheart. Time to rest.", "excited": "We actually did it! This is amazing!",
    "sad": "I'm sorry. I really thought it would work this time.", "sarcastic": "Oh, sure. Another bug. What a surprise.",
    "sing-song": "Time to tidy up, tidy up, tidy up.", "playful": "Oh, you think you can beat me? Let's see about that.",
}
CHARACTERS = {
    "Captain Brine": "A gruff old sea captain, a deep, gravelly man's voice, slow and dramatic.",
    "Professor Wren": "A precise, slightly nervous middle-aged woman with a British accent, quick and bright.",
    "The Dragon": "An ancient, enormous dragon: a very deep, slow, rumbling male voice, calm and menacing.",
}
SCRIPT = """Narrator: The storm rolled over the harbour as the little boat came home.
Captain Brine: Hold the line! We're nearly there!
Star: <excited> I can see the lighthouse!
Professor Wren: Remarkable. Absolutely remarkable.
Narrator: And far above the clouds, something old opened one golden eye.
The Dragon: Who dares to sail through my storm?"""


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def to_mp3(wav: Path) -> Path | None:
    exe = ffmpeg()
    if not exe:
        return None
    mp3 = wav.with_suffix(".mp3")
    subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "3", str(mp3)],
                   check=False)
    return mp3 if mp3.is_file() else None


def kokoro_mum(device: str = "auto"):
    from .engines import KokoroTTS
    from .settings import STAR_GAP_MS, STAR_SPEED, STAR_VOICE
    return KokoroTTS(STAR_VOICE, speed=STAR_SPEED, device=device, gap_ms=STAR_GAP_MS)


def collect(chunks):
    import numpy as np
    from .voicedsp import as_float
    rate, parts = 24000, []
    for pcm, rate in chunks:
        parts.append(as_float(pcm))
    return (np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)), rate


def save(out: Path, name: str, samples, rate: int, manifest: list, **info) -> None:
    from .nonverbal import write_wav
    path = out / f"{name}.wav"
    write_wav(path, samples, rate)
    mp3 = to_mp3(path)
    manifest.append({"file": path.name, "mp3": mp3.name if mp3 else "", "seconds": round(len(samples) / rate, 2), **info})
    print(f"  {name}: {len(samples) / rate:.2f} s", flush=True)


def write_manifest(out: Path, manifest: list) -> None:
    """manifest.json for the served A/B page, manifest.js for the same page opened as a plain file."""
    old = []
    if (out / "manifest.json").is_file():
        names = {m["file"] for m in manifest}
        old = [m for m in json.loads((out / "manifest.json").read_text(encoding="utf-8")) if m["file"] not in names]
    rows = old + manifest
    (out / "manifest.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (out / "manifest.js").write_text("window.MANIFEST = " + json.dumps(rows) + ";\n", encoding="utf-8")


def measure_file(path: Path) -> dict:
    import numpy as np
    from . import voicedsp
    from .guard import pitch_track
    from .nonverbal import read_wav
    x, sr = read_wav(path)
    f0 = pitch_track(x, sr)
    voiced = f0[f0 > 0]
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) if x.size else np.zeros(1)
    freqs = np.fft.rfftfreq(x.size, 1.0 / sr) if x.size else np.zeros(1)
    centroid = float((spec * freqs).sum() / max(spec.sum(), 1e-9))
    low = float(spec[freqs < 300].sum() / max(spec.sum(), 1e-9))
    frames = voicedsp.frame_db(x, sr, 0.02)
    return {"file": path.name, "seconds": round(x.size / sr, 2), "lufs": round(voicedsp.loudness(x, sr), 1),
            "peak_db": round(voicedsp.peak_db(x), 1), "clip_share": round(float(np.mean(np.abs(x) >= 0.999)), 5),
            "voiced_share": round(float((f0 > 0).mean()) if f0.size else 0.0, 2),
            "f0_median_hz": round(float(np.median(voiced)), 1) if voiced.size else 0.0,
            "f0_range_st": round(float(12 * np.log2(np.percentile(voiced, 95) / np.percentile(voiced, 5))), 1)
            if voiced.size > 4 else 0.0,
            "centroid_hz": round(centroid), "low_share": round(low, 3),
            "noise_floor_db": round(float(np.percentile(frames, 10)), 1)}


def cmd_measure(out: Path) -> list:
    rows = [measure_file(p) for p in sorted(out.glob("*.wav"))]
    (out / "measurements.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    keys = ["file", "seconds", "lufs", "peak_db", "voiced_share", "f0_median_hz", "f0_range_st", "centroid_hz"]
    print(" | ".join(keys))
    for r in rows:
        print(" | ".join(str(r[k]) for k in keys))
    return rows


def cmd_bank(home: Path, chatterbox: bool) -> None:
    from .nonverbal import build_bank
    base = kokoro_mum()
    cb = None
    if chatterbox:
        from ..voice_neural import ChatterboxTurbo, reference_clip
        cb = ChatterboxTurbo(reference_clip(base, home))
    build_bank(home / "sounds", kokoro=base, chatterbox=cb)


def cmd_samples(out: Path, home: Path, neural: bool) -> None:
    from . import styles as S
    from .expressive import ExpressiveConfig, ExpressiveTTS
    from .guard import ArtefactGuard
    from .library import CharacterLibrary
    from .nonverbal import NonverbalBank
    out.mkdir(parents=True, exist_ok=True)
    manifest: list = []
    base = kokoro_mum()
    bank = NonverbalBank(home / "sounds") if (home / "sounds").is_dir() else None
    lib = CharacterLibrary(out / "characters.json")
    for name, desc in CHARACTERS.items():
        if lib.get(name) is None:
            lib.create_designed(name, desc)
    tts = ExpressiveTTS(base, bank=bank, guard=ArtefactGuard(), library=lib, config=ExpressiveConfig(sounds=True))
    tts.policy.per_minute = tts.policy.per_reply = 99
    tts.policy.repeat_gap = 0.0
    print("styles (live: her Kokoro voice, plain since v2)")
    for style in S.STYLES:
        text = STYLE_LINES.get(style, LINE)
        tts.set_mood(None, "")
        x, sr = collect(tts.synthesize(f"<{style}:0.8> {text}"))
        save(out, f"style-{style}-kokoro", x, sr, manifest, group=f"style:{style}", engine="kokoro", style=style,
             text=text)
    from . import voicedsp
    x, sr = base.synthesize_float(LINE)
    save(out, "plain-star-mum", voicedsp.normalize(x, sr), sr, manifest, group="style:neutral", engine="kokoro (no DSP)",
         style="none", text=LINE)
    tts.set_mood(None, "")
    print("sounds")
    for sound in S.SOUNDS:
        x, sr = collect(tts.synthesize(f"<{sound}>"))
        if len(x):
            save(out, f"sound-{sound}", x, sr, manifest, group="sounds", engine=str(tts.last[-1:]), style=sound,
                 text=f"<{sound}>")
    x, sr = collect(tts.synthesize("Oh no, <gasp> did you really do that? <laugh> You're impossible, you know that."))
    save(out, "sounds-in-speech", x, sr, manifest, group="sounds", engine="kokoro+dsp+bank", style="mixed",
         text="gasp + laugh inside speech")
    print("ASMR")
    tts.config.asmr = True
    tts.set_mood(None, "")
    parts = []
    for sentence in ("Hi. I'm right here.", "Let your shoulders drop.", "Breathe in, slowly.", "And let it all go.",
                     "You did enough today."):
        parts.append(collect(tts.synthesize(sentence))[0])
    import numpy as np
    save(out, "asmr-passage", np.concatenate(parts), 24000, manifest, group="asmr", engine="kokoro+dsp", style="asmr",
         text="five ASMR sentences")
    tts.config.asmr = False
    tts.set_mood(None, "")
    print("role-play")
    x, sr = collect(tts.speak_script(SCRIPT))
    save(out, "roleplay-kokoro", x, sr, manifest, group="roleplay", engine="kokoro+dsp characters", style="roleplay",
         text=SCRIPT)
    # singing is paused (star/voice/singing.SINGING_PAUSED): no song samples
    if neural:
        _neural_samples(out, home, base, manifest)
    write_manifest(out, manifest)
    (out / "guard-summary.json").write_text(json.dumps(tts.stats.summary(), indent=1), encoding="utf-8")


def _neural_samples(out: Path, home: Path, base, manifest: list, parts=("qwen", "chatterbox", "design")) -> None:
    import gc

    import torch
    from . import styles as S
    from . import voicedsp
    from .guard import ArtefactGuard, GuardedTTS, GuardStats
    from ..voice_neural import QwenCloneTTS, SpeakerEmbedder, reference_clip
    ref = reference_clip(base, home)
    asr = _asr()
    embedder = SpeakerEmbedder()
    from .nonverbal import read_wav
    ref_x, ref_sr = read_wav(ref)
    ref_emb = embedder.embed(ref_x, ref_sr)
    stats = GuardStats(out / "guard-log.jsonl")
    guard = ArtefactGuard(asr=asr, embedder=embedder)
    summary_path = out / "guard-neural-summary.json"

    def summary() -> None:
        if stats.attempts:                       # a later run of only the unguarded parts keeps the earlier summary
            summary_path.write_text(json.dumps(stats.summary(), indent=1), encoding="utf-8")
    if "qwen" not in parts:
        return _later_parts(out, ref, manifest, parts, summary)
    print("qwen3-tts 0.6B clone of her voice, style instructions")
    qwen = QwenCloneTTS(ref)
    runner = GuardedTTS(qwen, guard, 3, stats, reference=ref_emb, name="qwen3-tts")
    for style in ("neutral", "warm", "caring", "whisper", "excited", "sad", "sleepy", "sarcastic", "playful", "asmr"):
        text = STYLE_LINES.get(style, LINE)
        spec = S.STYLES[style]
        x, sr, report = runner.render(text, instruct=spec.instruct or None)
        save(out, f"style-{style}-qwen3", voicedsp.normalize(x, sr), sr, manifest, group=f"style:{style}",
             engine="qwen3-tts-0.6b-clone", style=style, text=text, guard=report.problems,
             similarity=report.metrics.get("similarity"))
    del qwen, runner
    gc.collect(); torch.cuda.empty_cache()
    summary()
    _later_parts(out, ref, manifest, parts, summary)


def _later_parts(out: Path, ref, manifest: list, parts, summary) -> None:
    import gc

    import torch
    from . import voicedsp
    from ..voice_neural import ChatterboxTurbo, QwenDesignTTS
    if "chatterbox" in parts:
        _chatterbox_samples(out, ref, manifest, ChatterboxTurbo, voicedsp)
        gc.collect(); torch.cuda.empty_cache()
    if "design" not in parts:
        return
    print("qwen3-tts 1.7B voice design (role-play characters)")
    design = QwenDesignTTS()
    for name, desc in CHARACTERS.items():
        text = {"Captain Brine": "Hold the line! We're nearly there!", "Professor Wren": "Remarkable. Absolutely remarkable.",
                "The Dragon": "Who dares to sail through my storm?"}[name]
        x, sr = design.synthesize_float(text, seed=0, instruct=desc)
        save(out, f"character-{name.lower().replace(' ', '-')}-design", voicedsp.normalize(x, sr), sr, manifest,
             group="roleplay", engine="qwen3-tts-1.7b-voicedesign", style=name, text=text, description=desc)
    del design
    summary()


def _chatterbox_samples(out: Path, ref, manifest: list, ChatterboxTurbo, voicedsp) -> None:   # noqa: N803
    print("chatterbox-turbo native tags in her voice")
    cb = ChatterboxTurbo(ref)
    for name, text in (("laugh", "That is the funniest thing [laugh] I've heard all week."),
                       ("sigh", "[sigh] Okay. Let's try one more time."), ("cough", "Sorry [cough] excuse me."),
                       ("gasp", "[gasp] Wait, you finished it?")):
        x, sr = cb.synthesize_float(text, seed=0)
        save(out, f"native-{name}-chatterbox", voicedsp.normalize(x, sr), sr, manifest, group="sounds",
             engine="chatterbox-turbo", style=name, text=text)
    del cb


def _asr():
    from .engines import FasterWhisperASR
    return FasterWhisperASR("small.en", device="auto")


def cmd_bench(out: Path, home: Path, engines: list[str], runs: int = 5) -> dict:
    """First audio and real-time factor per engine on this machine's GPU. 'first audio' = time from text in to the
    first playable chunk out, for a short opening sentence (the chunker releases 3-6 words first)."""
    import gc
    import statistics
    import numpy as np
    from .expressive import ExpressiveConfig, ExpressiveTTS
    results: dict = {"gpu": _gpu_name(), "when": time.strftime("%Y-%m-%d %H:%M:%S"), "runs": runs, "engines": {}}
    first = "Oh, well done, love."
    longer = "You found that bug all by yourself, and I'm really proud of you."
    base = kokoro_mum()
    base.warm_up()

    def timeit(fn):
        times = []
        for _ in range(runs):
            t0 = time.perf_counter()
            fn()
            times.append(time.perf_counter() - t0)
        return round(statistics.median(times), 3), round(max(times), 3)

    if "kokoro" in engines:
        p50, worst = timeit(lambda: base.synthesize_float(first))
        x, sr = base.synthesize_float(longer)
        t0 = time.perf_counter(); base.synthesize_float(longer); rt = time.perf_counter() - t0
        results["engines"]["kokoro star-mum"] = {"first_audio_p50": p50, "first_audio_max": worst,
                                                 "rtf": round(rt / (len(x) / sr), 3), "device": base.device}
        for style in ("whisper", "excited", "sad", "asmr"):
            tts = ExpressiveTTS(base, config=ExpressiveConfig(sounds=False))

            def first_chunk(style=style, tts=tts):
                next(iter(tts.synthesize(f"<{style}:0.8> {first}")))
            p50, worst = timeit(first_chunk)
            results["engines"][f"kokoro+dsp {style}"] = {"first_audio_p50": p50, "first_audio_max": worst}
    ref = None
    if any(e.startswith("qwen") or e.startswith("chatterbox") for e in engines):
        from ..voice_neural import reference_clip
        ref = reference_clip(base, home)
    if "qwen3-tts" in engines:
        import torch
        from ..voice_neural import QwenCloneTTS
        before = torch.cuda.memory_allocated() if torch.cuda.is_available() else 0
        q = QwenCloneTTS(ref)
        q.synthesize_float(first)                       # CUDA graphs captured on first use
        vram = (torch.cuda.max_memory_allocated() - before) / 1e9 if torch.cuda.is_available() else 0
        p50, worst = timeit(lambda: q.synthesize_float(first))

        def stream_first():
            next(iter(q.stream(first)))
        s50, sworst = timeit(stream_first)
        x, sr = q.synthesize_float(longer)
        t0 = time.perf_counter(); q.synthesize_float(longer); rt = time.perf_counter() - t0
        inst50, _ = timeit(lambda: q.synthesize_float(first, instruct="Whisper very softly."))
        results["engines"]["qwen3-tts 0.6B clone"] = {"first_sentence_p50": p50, "first_sentence_max": worst,
                                                       "stream_first_chunk_p50": s50, "stream_first_chunk_max": sworst,
                                                       "with_instruct_p50": inst50, "rtf": round(rt / (len(x) / sr), 3),
                                                       "vram_peak_gb": round(vram, 2)}
        del q
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    if "chatterbox-turbo" in engines:
        import torch
        from ..voice_neural import ChatterboxTurbo
        c = ChatterboxTurbo(ref)
        c.synthesize_float(first)
        vram = torch.cuda.max_memory_allocated() / 1e9
        p50, worst = timeit(lambda: c.synthesize_float(first))
        x, sr = c.synthesize_float(longer)
        t0 = time.perf_counter(); c.synthesize_float(longer); rt = time.perf_counter() - t0
        results["engines"]["chatterbox-turbo"] = {"first_sentence_p50": p50, "first_sentence_max": worst,
                                                  "rtf": round(rt / (len(x) / sr), 3), "vram_peak_gb": round(vram, 2)}
        del c
        gc.collect(); torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    if "qwen3-tts-design" in engines:
        import torch
        from ..voice_neural import QwenDesignTTS
        d = QwenDesignTTS()
        d.synthesize_float(first, instruct="A warm adult woman.")
        vram = torch.cuda.max_memory_allocated() / 1e9
        p50, worst = timeit(lambda: d.synthesize_float(first, instruct="A warm adult woman."))
        results["engines"]["qwen3-tts 1.7B voice design"] = {"first_sentence_p50": p50, "first_sentence_max": worst,
                                                             "vram_peak_gb": round(vram, 2)}
        del d
        gc.collect(); torch.cuda.empty_cache()
    out.mkdir(parents=True, exist_ok=True)
    path = out / "bench.json"
    if path.is_file():                          # one engine per run (separate processes): merge into earlier runs
        merged = json.loads(path.read_text(encoding="utf-8"))
        merged.setdefault("engines", {}).update(results["engines"])
        merged.setdefault("runs_log", []).append({k: results[k] for k in ("gpu", "when")} |
                                                 {"engines": list(results["engines"])})
        results = merged
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))
    del np
    return results


def _gpu_name() -> str:
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "unknown"


# -- A/B listening page -------------------------------------------------------------------------------------------
def record_rating(path: Path, rating: dict) -> dict:
    """Validate and append one rating: {"file": "...wav", "score": 1..5, "group": "...", "note": "..."}."""
    file = str(rating.get("file", ""))
    score = int(rating.get("score", 0))
    if not file or "/" in file or "\\" in file or not file.endswith(".wav"):
        raise ValueError("bad file")
    if not 1 <= score <= 5:
        raise ValueError("score must be 1-5")
    row = {"at": round(time.time(), 1), "file": file, "score": score, "group": str(rating.get("group", ""))[:60],
           "note": str(rating.get("note", ""))[:300], "rater": "owner"}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def summarize_ratings(path: Path) -> dict:
    """Latest score per file, then the mean per file and per engine."""
    latest: dict = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row["file"]] = row
    return {"files": {k: v["score"] for k, v in latest.items()}, "count": len(latest)}


def cmd_ab_serve(out: Path, port: int) -> None:
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    ratings = out / "ratings.jsonl"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(out), **k)

        def do_POST(self):                        # noqa: N802
            if self.path != "/api/rate":
                self.send_error(404)
                return
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)))
                row = record_rating(ratings, body)
                data, code = json.dumps(row).encode(), 200
            except Exception as exc:
                data, code = json.dumps({"error": str(exc)}).encode(), 400
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):                         # noqa: N802
            if self.path == "/api/ratings":
                data = json.dumps(summarize_ratings(ratings)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)
                return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)        # this PC only
    print(f"A/B page: http://127.0.0.1:{port}/ab.html  (ratings -> {ratings})", flush=True)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m star.voice.expressive_lab")
    ap.add_argument("command", choices=["bank", "samples", "bench", "measure", "ab-serve"])
    ap.add_argument("--out", default="docs/design/assets/voice-expressive-20261026")
    ap.add_argument("--home", default="")
    ap.add_argument("--neural", action="store_true")
    ap.add_argument("--chatterbox", action="store_true")
    ap.add_argument("--engines", default="kokoro")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--port", type=int, default=8766)
    args = ap.parse_args(argv)
    out = Path(args.out)
    from .expressive import _default_home
    home = Path(args.home) if args.home else _default_home()
    if args.command == "bank":
        cmd_bank(home, args.chatterbox)
    elif args.command == "samples":
        cmd_samples(out, home, args.neural)
        cmd_measure(out)
    elif args.command == "bench":
        cmd_bench(out, home, [e.strip() for e in args.engines.split(",")], args.runs)
    elif args.command == "measure":
        cmd_measure(out)
    else:
        cmd_ab_serve(out, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
