# ruff: noqa: F403, F405  (lab script: shared names come from v2common)
"""Qwen3-TTS emotion from the model, through the shipped code path: StarDesignTTS (1.7B VoiceDesign, Star's
description + seed + the style's own instruction from star/voice/styles.py). Then the 0.6B Base clone of the designed
reference (the real-time candidate; no emotion control), with its streaming first chunk."""
import sys, time, json
from v2common import *


def main():
    import torch, soundfile as sf
    from star.voice import styles as S
    import star.voice_neural as N
    ref = sys.argv[1]
    cand = json.loads((OUT / "star-candidates.json").read_text())
    from screen_descs import DESCS
    N.STAR_VOICES.update({c["candidate"]: (DESCS[c["candidate"]], c["seed"]) for c in cand["candidates"]})
    rx, rsr = sf.read(REF_DIR / f"star-{ref}.wav"); refemb = embedder().embed(rx.astype("float32"), rsr)
    manifest, rows = [], []
    eng = N.StarDesignTTS(ref)
    eng.synthesize_float("Hello.", seed=0)

    def guarded(name, text, fn, **info):
        best = None
        for attempt in range(3):
            torch.cuda.synchronize(); t = time.time(); x, sr = fn(attempt); torch.cuda.synchronize(); el = time.time() - t
            r = check(x, sr, text, reference=refemb)
            if best is None or len(r.problems) < len(best[2].problems):
                best = (x, sr, r, el, attempt)
            if r.ok:
                break
        x, sr, r, el, attempt = best
        row = {"name": name, "seconds": round(len(x) / sr, 2), "synth_s": round(el, 2), "rtf": round(el / (len(x) / sr), 2),
               "attempts": attempt + 1, "problems": r.problems, "wer": r.metrics.get("wer"),
               "similarity": r.metrics.get("similarity")}
        rows.append(row); print(row, flush=True)
        save(name, x, sr, manifest, text=text, guard=r.problems, similarity=r.metrics.get("similarity"),
             synth_s=round(el, 2), **info)

    styles = {"warm": "warm", "excited": "excited", "sad": "sad", "playful": "playful", "whisper": "whisper",
              "sleepy": "sleepy"}
    for emo, style in styles.items():
        text = EMOTIONS[emo][0]
        instruct = S.STYLES[style].instruct
        guarded(f"emo-qwen3design-{emo}", text,
                lambda a, text=text, instruct=instruct, eng=eng: eng.synthesize_float(text, seed=a, instruct=instruct),
                group="2 Emotion: Qwen3 VoiceDesign (Star's voice + instruction)", engine="qwen3-tts 1.7B VoiceDesign",
                style=emo, instruct=instruct)
    firsts_vd = []
    for _ in range(3):
        torch.cuda.synchronize(); t = time.time()
        for chunk, sr in eng.stream(LINES["greeting"], instruct=S.STYLES["warm"].instruct):
            firsts_vd.append(round(time.time() - t, 2)); break
    vd_peak = torch.cuda.max_memory_allocated() / 1e9
    del eng; torch.cuda.empty_cache(); torch.cuda.reset_peak_memory_stats()
    clone = N.QwenCloneTTS(REF_DIR / f"star-{ref}.wav", ref_text=(REF_DIR / f"star-{ref}.txt").read_text(encoding="utf-8"))
    clone.synthesize_float("Hello there.", seed=0)
    for key in ("greeting", "comfort"):
        text = LINES[key]
        guarded(f"emo-qwen3clone-{key}", text, lambda a, text=text: clone.synthesize_float(text, seed=a),
                group="2 Emotion: Qwen3 0.6B clone (fast, streams; no emotion control)",
                engine="qwen3-tts 0.6B Base clone of the designed voice", style=key)
    firsts = []
    for _ in range(3):
        torch.cuda.synchronize(); t = time.time()
        for chunk, sr in clone.stream(LINES["greeting"], seed=0):
            firsts.append(round(time.time() - t, 2)); break
    merge_manifest(manifest)
    json.dump({"ref": ref, "design_peak_vram_gb": round(vd_peak, 2), "design_stream_first_chunk_s": firsts_vd,
               "clone_peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
               "clone_stream_first_chunk_s": firsts, "rows": rows}, open(OUT / "engine-qwen3.json", "w"), indent=1)
    print("done", firsts_vd, firsts)


if __name__ == "__main__":
    main()
