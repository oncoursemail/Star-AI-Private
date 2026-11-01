# ruff: noqa: F403, F405  (lab script: shared names come from v2common)
"""IndexTTS-2.5 (bilibili model licence: royalty-free under 100M MAU / RMB 1B revenue; outputs may not be used to
improve other commercial AI models): timbre from the designed Star reference, emotion from (a) the 8-way emotion vector
and (b) an emotional reference clip made by Qwen3 VoiceDesign in her voice. Guarded, timed."""
import sys, time, json, os
from v2common import *
IX = WORK / "indextts-src"
sys.path.insert(0, str(IX))
MODEL = str(WORK / "models" / "IndexTTS-2.5")
# [happy, angry, sad, afraid, disgusted, melancholic, surprised, calm]
VEC = {
    "warm":    [0.35, 0, 0, 0, 0, 0, 0, 0.45],
    "excited": [0.75, 0, 0, 0, 0, 0, 0.25, 0],
    "sad":     [0, 0, 0.6, 0, 0, 0.25, 0, 0],
    "playful": [0.55, 0, 0, 0, 0, 0, 0.15, 0.1],
    "whisper": [0, 0, 0, 0, 0, 0, 0, 0.8],
    "sleepy":  [0, 0, 0, 0, 0, 0.3, 0, 0.5],
}


def main():
    import torch, soundfile as sf
    import torchaudio

    def _save(path, wav, sr, **_k):                  # torchaudio 2.11 save()/load() need torchcodec: use soundfile
        sf.write(str(path), wav.detach().float().cpu().numpy().T, int(sr))

    def _load(path, *a, **k):
        x, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(x.T.copy()), sr
    torchaudio.save, torchaudio.load = _save, _load
    from indextts.infer_v2_5 import IndexTTS2
    import indextts.infer_v2_5 as _iv
    _iv.JapaneseG2PProcessor = lambda **k: None      # Japanese only; skips fugashi + its dictionary
    import indextts.utils.front as _front

    class _Plain:                                    # wetext's grammar download (modelscope) was rate-limited (403);
        def normalize(self, text):                   # the test lines are plain English words, so no normalisation
            return text

    def _plain_load(self):
        self.zh_normalizer = self.en_normalizer = _Plain()
    _front.TextNormalizer.load = _plain_load
    ref = sys.argv[1]
    ref_wav = str(REF_DIR / f"star-{ref}.wav")
    rx, rsr = sf.read(ref_wav); refemb = embedder().embed(rx.astype("float32"), rsr)
    t0 = time.time()
    tts = IndexTTS2(cfg_path=os.path.join(MODEL, "config.yaml"), model_dir=MODEL, use_bf16=True, use_cuda_kernel=False)
    load_s = time.time() - t0
    tmp = OUT.parent / "tmp-index.wav"

    def synth(text, **kw):
        torch.cuda.synchronize(); t = time.time()
        tts.infer(spk_audio_prompt=ref_wav, text=text, output_path=str(tmp), lang="EN", verbose=False, **kw)
        torch.cuda.synchronize(); el = time.time() - t
        x, sr = sf.read(str(tmp)); return x.astype("float32"), sr, el

    synth("Hello there, how are you?")
    manifest, rows = [], []

    def guarded(name, text, kw, **info):
        best = None
        for attempt in range(3):
            torch.manual_seed(attempt)
            x, sr, el = synth(text, **kw)
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
        save(name, x, sr, manifest, engine="indextts-2.5", text=text, guard=r.problems,
             similarity=r.metrics.get("similarity"), synth_s=round(el, 2), **info)

    guarded("emo-indextts-neutral", EMOTIONS["warm"][0], {}, group="2 Emotion: IndexTTS-2.5", style="neutral clone")
    for emo, (text, _) in EMOTIONS.items():
        guarded(f"emo-indextts-{emo}", text, {"emo_vector": VEC[emo], "emo_alpha": 1.0},
                group="2 Emotion: IndexTTS-2.5", style=emo, emotion_vector=VEC[emo])
    for emo in ("whisper", "excited", "sad"):
        emo_ref = OUT / f"emo-qwen3design-{emo}.wav"
        if emo_ref.is_file():
            text = EMOTIONS[emo][0]
            guarded(f"emo-indextts-{emo}-audioref", text, {"emo_audio_prompt": str(emo_ref), "emo_alpha": 0.9},
                    group="2 Emotion: IndexTTS-2.5", style=f"{emo} (emotion copied from the Qwen3 clip)")
    merge_manifest(manifest)
    json.dump({"ref": ref, "load_s": round(load_s, 1), "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
               "streaming": "none in this API (whole sentence; first audio = synth_s)", "rows": rows},
              open(OUT / "engine-indextts.json", "w"), indent=1)
    print("done", gpu_mem())


if __name__ == "__main__":
    main()
