# ruff: noqa: F403, F405  (lab script: shared names come from v2common)
"""8 designed 'Star' voices (Qwen3-TTS 1.7B VoiceDesign). In VoiceDesign the seed is part of the voice, so for each
description the seed whose greeting lands nearest an adult woman's pitch (target 225 Hz, 185-265) is kept; then the
same 4 lines are rendered with it, guarded and timed, plus a 10 s reference clip for cloning engines."""
import time, json
import numpy as np, pyworld
from v2common import *
from screen_descs import ADULT, DESCS, PICK

REF_TEXT = ("Hi, it's Star. I'm really happy you're here. Tell me everything, from the very beginning, "
            "and take as long as you like. I'm listening.")

def f0med(x, sr):
    f0, _ = pyworld.harvest(x.astype(np.float64), sr, f0_floor=70, f0_ceil=700, frame_period=10)
    v = f0[f0 > 0]
    return float(np.median(v)) if v.size else 0.0

def main():
    import torch
    from star.voice_neural import QwenDesignTTS
    from star.voice.guard import cosine
    from star.voice.nonverbal import write_wav
    t0 = time.time(); eng = QwenDesignTTS(); load_s = time.time() - t0
    manifest, stats = [], []
    for key in PICK:
        instruct = DESCS[key] + ADULT
        tries = []
        for seed in range(1, 9):
            x, sr = eng.synthesize_float(LINES["greeting"], seed=seed, instruct=instruct)
            m = f0med(x, sr); tries.append((abs(m - 225), seed, round(m)))
            if 200 <= m <= 250:
                break
        tries.sort(); seed = tries[0][1]
        embs, rows = [], []
        for line_key, text in LINES.items():
            best = None
            for attempt in range(3):
                s = seed if attempt == 0 else seed + 1000 * attempt
                torch.cuda.synchronize(); t = time.time()
                x, sr = eng.synthesize_float(text, seed=s, instruct=instruct)
                torch.cuda.synchronize(); el = time.time() - t
                r = check(x, sr, text)
                if best is None or len(r.problems) < len(best[2].problems):
                    best = (x, sr, r, el, attempt)
                if r.ok:
                    break
            x, sr, r, el, attempt = best
            embs.append(embedder().embed(x, sr))
            rows.append({"line": line_key, "f0_hz": round(f0med(x, sr)), "seconds": round(len(x) / sr, 2),
                         "synth_s": round(el, 2), "rtf": round(el / (len(x) / sr), 2), "attempts": attempt + 1,
                         "problems": r.problems, "wer": r.metrics.get("wer")})
            save(f"star-{key}-{line_key}", x, sr, manifest, group=f"1 Star voice: {key}",
                 engine="qwen3-tts 1.7B VoiceDesign", style=line_key, text=text, description=instruct, seed=seed,
                 guard=r.problems, synth_s=round(el, 2), f0_hz=rows[-1]["f0_hz"])
        x, sr = eng.synthesize_float(REF_TEXT, seed=seed, instruct=instruct)
        write_wav(REF_DIR / f"star-{key}.wav", x, sr)
        (REF_DIR / f"star-{key}.txt").write_text(REF_TEXT, encoding="utf-8")
        sims = [cosine(embs[i], embs[j]) for i in range(4) for j in range(i + 1, 4)]
        torch.cuda.synchronize(); t = time.time(); first = None
        for chunk, sr, _ in eng.model.generate_voice_design_streaming(text=LINES["greeting"], instruct=instruct,
                                                                        language="English", chunk_size=8):
            if first is None:
                first = time.time() - t
        stats.append({"candidate": key, "seed": seed, "seed_search": sorted(tries, key=lambda t: t[1]),
                      "description": instruct, "identity_consistency": round(sum(sims) / len(sims), 3),
                      "min_pair": round(min(sims), 3), "stream_first_chunk_s": round(first, 2), "lines": rows})
        print(key, seed, stats[-1]["identity_consistency"], [r["f0_hz"] for r in rows], round(first, 2), flush=True)
    merge_manifest(manifest)
    (OUT / "star-candidates.json").write_text(json.dumps({"load_s": round(load_s, 1),
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2), "candidates": stats}, indent=1))
    print("done", gpu_mem())

if __name__ == "__main__":
    main()
