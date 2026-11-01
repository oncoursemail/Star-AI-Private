# ruff: noqa: F403, F405  (lab script: shared names come from v2common)
"""Screen VoiceDesign descriptions by measured pitch (target: adult woman, median 170-270 Hz)."""
import json
import numpy as np, pyworld
from v2common import *
ADULT = (" She is an adult woman, about twenty-six, speaking at a natural medium-low pitch like an ordinary adult woman;"
         " never squeaky, never high-pitched, not a child and not a cartoon. Clear American English.")
DESCS = {
 "a-warm-smile":   "A warm, friendly woman with a smile in her voice, natural and gently playful, relaxed pace.",
 "b-soft-breathy": "A soft, slightly breathy, intimate woman's voice, calm and affectionate, a little playful.",
 "c-lively":       "A lively, cheerful woman's voice with natural energy, expressive and playful, quick but clear.",
 "d-velvet":       "A warm, velvety, honeyed woman's voice, calm, caring and confident, with a hint of playfulness.",
 "e-gentle-cute":  "A gentle, tender, cute woman's voice with a light, soft touch, warm and sweet.",
 "f-casual":       "A woman talking casually to her closest friend, natural, conversational, warm and a little teasing.",
 "g-cozy-husky":   "A slightly husky, cozy, warm woman's voice, soft and comforting, with a gentle playful edge.",
 "h-crisp":        "A crisp, clear woman's voice with a playful lilt, witty and warm, precise articulation.",
 "i-radio-warm":   "A smooth, warm woman's voice like a late-night radio host, close, calm and kind, a little playful.",
 "j-girlfriend":   "An affectionate, warm woman's voice, natural and cosy, a playful grin, soft but confident.",
}
def f0med(x, sr):
    f0, _ = pyworld.harvest(x.astype(np.float64), sr, f0_floor=70, f0_ceil=700, frame_period=10)
    v = f0[f0 > 0]
    return float(np.median(v)) if v.size else 0.0
def main():
    from star.voice_neural import QwenDesignTTS
    eng = QwenDesignTTS()
    text = LINES["comfort"]
    res = {}
    for k, d in DESCS.items():
        meds = []
        for seed in (7, 8):
            x, sr = eng.synthesize_float(text, seed=seed, instruct=d + ADULT)
            meds.append(round(f0med(x, sr)))
        res[k] = meds
        print(k, meds, flush=True)
    json.dump({"adult": ADULT, "descs": DESCS, "f0": res}, open(OUT.parent / "screen.json", "w"), indent=1)
main()
