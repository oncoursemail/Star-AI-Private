"""Shared helpers for the voice-v2 A/B round (run from tools/voice_v2; the shipped code is star/voice*)."""
import json, sys, os
from pathlib import Path
WT = Path(__file__).resolve().parents[2]                     # the repo (worktree) root
sys.path.insert(0, str(WT))
# Work folder (models, engine sources, venvs, samples; never committed). Default: <repo>/../../work/voice-v2
WORK = Path(os.environ.get("STAR_VOICE_V2_WORK", WT.parents[1] / "work" / "voice-v2"))
OUT = WORK / "samples"
OUT.mkdir(parents=True, exist_ok=True)
REF_DIR = WORK / "refs"
REF_DIR.mkdir(parents=True, exist_ok=True)

LINES = {
    "greeting": "Hey, you're back! I was just thinking about you. How was your day?",
    "comfort": "Oh, sweetheart, that sounds really hard. Come here, it's okay. I'm right here with you.",
    "excited": "Wait, seriously? You did it? That's amazing! I knew you could do it!",
    "goodnight": "Alright, time to rest now. Sleep well, okay? I'll be right here in the morning. Goodnight.",
}
# one line per emotion, written so the words fit the feeling
EMOTIONS = {
    "warm":    ("I'm really glad you told me. You don't have to carry this by yourself.",
                "speaking warmly and tenderly, gentle and caring, like comforting a close friend"),
    "excited": ("No way, you actually finished it? That's incredible, I'm so proud of you!",
                "very excited and joyful, bright and fast, almost laughing with happiness"),
    "sad":     ("I'm sorry. I really hoped it would work out this time.",
                "sad and disappointed, quiet, slow, her voice a little heavy"),
    "playful": ("Oh, you think you can beat me? Cute. Let's see about that.",
                "playful and teasing, a smile in her voice, light and mischievous"),
    "whisper": ("Come closer. I have a little secret, just for you.",
                "whispering softly and intimately, breathy, very quiet, close to the microphone"),
    "sleepy":  ("Mm, it's getting so late. Let's get some sleep, okay?",
                "sleepy and drowsy, slow, soft, yawning a little, relaxed and calm"),
}

_asr = _emb = None
def asr():
    global _asr
    if _asr is None:
        from star.voice.engines import FasterWhisperASR
        _asr = FasterWhisperASR("small.en", device="cpu")
    return _asr

def embedder():
    global _emb
    if _emb is None:
        from star.voice_neural import SpeakerEmbedder
        _emb = SpeakerEmbedder("cpu")
    return _emb

def check(x, sr, text, reference=None):
    from star.voice.guard import ArtefactGuard
    g = ArtefactGuard(asr=asr(), embedder=embedder())
    r = g.check(x, sr, text, reference=reference)
    return r

def save(name, x, sr, manifest, **info):
    from star.voice import voicedsp
    from star.voice.expressive_lab import save as lab_save
    lab_save(OUT, name, voicedsp.normalize(x, sr), sr, manifest, **info)

def merge_manifest(rows):
    from star.voice.expressive_lab import write_manifest
    write_manifest(OUT, rows)

def gpu_mem():
    import subprocess
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "?"

def append_jsonl(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
