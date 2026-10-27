# ruff: noqa: F403, F405  (lab script: shared names come from v2common)
"""CosyVoice 3 (Fun-CosyVoice3-0.5B-2512, Apache-2.0): clone of the designed Star voice, emotion by instruction,
inline non-verbal tags. Guarded, timed."""
import sys, time, json
from v2common import *
CS = WORK / "cosyvoice-src"
sys.path.insert(0, str(CS)); sys.path.insert(0, str(CS / "third_party" / "Matcha-TTS"))
MODEL = str(WORK / "models" / "Fun-CosyVoice3-0.5B")
P = "You are a helpful assistant."
INSTR = {   # trained wording where the model has one (cosyvoice/utils/common.py), else plain English
    "warm": "Please speak warmly and tenderly, gentle and caring.",
    "excited": "请非常开心地说一句话。",
    "sad": "请非常伤心地说一句话。",
    "playful": "Please speak in a playful, teasing way, with a smile.",
    "whisper": "Please say a sentence in a very soft voice.",
    "sleepy": "请用尽可能慢地语速说一句话。",
}
NONVERBAL = {
    "laugh": "Oh my gosh, [laughter] that's so funny! [laughter] I can't believe you did that.",
    "laugh-speech": "<laughter>Stop it, you're making me laugh</laughter>, okay, okay, I'm listening.",
    "sigh": "[sigh] Okay. Long day, huh? [breath] Let's just relax for a minute.",
    "breath": "[breath] Alright. [breath] Let's try that one more time, together.",
    "cough": "Sorry, [cough] excuse me. Where were we?",
}

def main():
    import torch, numpy as np
    from cosyvoice.cli.cosyvoice import AutoModel
    import cosyvoice.cli.frontend as fe, soundfile as _sf

    def load_wav(wav, target_sr, min_sr=16000):      # torchaudio 2.11 load() needs torchcodec; read with soundfile
        x, sr = _sf.read(wav, dtype="float32", always_2d=True)
        speech = torch.from_numpy(x.mean(axis=1)).unsqueeze(0)
        if sr != target_sr:
            import torchaudio
            speech = torchaudio.transforms.Resample(sr, target_sr)(speech)
        return speech
    fe.load_wav = load_wav
    ref = sys.argv[1]
    ref_wav = str(REF_DIR / f"star-{ref}.wav"); ref_text = (REF_DIR / f"star-{ref}.txt").read_text(encoding="utf-8")
    t0 = time.time(); cv = AutoModel(model_dir=MODEL, fp16=True); load_s = time.time() - t0
    sr = cv.sample_rate
    import soundfile as sf
    rx, rsr = sf.read(ref_wav); refemb = embedder().embed(rx.astype("float32"), rsr)

    def run(gen):
        torch.cuda.synchronize(); t = time.time(); parts = []
        for j in gen:
            parts.append(j["tts_speech"].reshape(-1).float().cpu().numpy())
        torch.cuda.synchronize()
        x = np.concatenate(parts) if parts else np.zeros(0, "float32")
        return x, time.time() - t

    # warm-up
    run(cv.inference_zero_shot("Hello there, how are you?", P + "<|endofprompt|>" + ref_text, ref_wav))
    manifest, rows = [], []
    def guarded(name, text, make, **info):
        best = None
        for attempt in range(3):
            torch.manual_seed(attempt); x, el = run(make())
            r = check(x, sr, text.replace("[laughter]", "").replace("[sigh]", "").replace("[breath]", "")
                      .replace("[cough]", "").replace("<laughter>", "").replace("</laughter>", ""), reference=refemb)
            if best is None or len(r.problems) < len(best[2].problems):
                best = (x, el, r, attempt)
            if r.ok or info.get("group", "").startswith("3"):
                break
        x, el, r, attempt = best
        row = {"name": name, "seconds": round(len(x) / sr, 2), "synth_s": round(el, 2), "rtf": round(el / max(len(x) / sr, .01), 2),
               "attempts": attempt + 1, "problems": r.problems, "wer": r.metrics.get("wer"),
               "similarity": r.metrics.get("similarity"), "heard": r.metrics.get("heard")}
        rows.append(row); print(row, flush=True)
        save(name, x, sr, manifest, engine="cosyvoice3-0.5B", text=text, guard=r.problems,
             similarity=r.metrics.get("similarity"), synth_s=round(el, 2), **info)

    text0 = EMOTIONS["warm"][0]
    guarded("emo-cosyvoice3-neutral", text0, lambda: cv.inference_zero_shot(text0, P + "<|endofprompt|>" + ref_text, ref_wav),
            group="2 Emotion: CosyVoice 3", style="neutral clone")
    for emo, (text, _) in EMOTIONS.items():
        guarded(f"emo-cosyvoice3-{emo}", text,
                lambda text=text, emo=emo: cv.inference_instruct2(text, f"{P} {INSTR[emo]}<|endofprompt|>", ref_wav),
                group="2 Emotion: CosyVoice 3", style=emo, instruct=INSTR[emo])
    for nv, text in NONVERBAL.items():
        guarded(f"nv-cosyvoice3-{nv}", text,
                lambda text=text: cv.inference_zero_shot(text, P + "<|endofprompt|>" + ref_text, ref_wav),
                group="3 Non-verbal: CosyVoice 3 tags", style=nv)
    # streaming first chunk
    firsts = []
    for _ in range(3):
        torch.cuda.synchronize(); t = time.time()
        for j in cv.inference_zero_shot(LINES["greeting"], P + "<|endofprompt|>" + ref_text, ref_wav, stream=True):
            firsts.append(time.time() - t); break
    merge_manifest(manifest)
    json.dump({"ref": ref, "load_s": round(load_s, 1), "stream_first_chunk_s": [round(f, 2) for f in firsts],
               "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2), "rows": rows},
              open(OUT / "engine-cosyvoice3.json", "w"), indent=1)
    print("done", firsts, gpu_mem())

if __name__ == "__main__":
    main()
