"""Installer entry point for her PC: fetch and verify the voice, hearing and fast-path files, one step at a time.

    python -m star.senses.setup                      voice files, speech-to-text models, fast path (dedicated + game profile)
    python -m star.senses.setup --list               what would be fetched, how big, what is already there (downloads nothing)
    python -m star.senses.setup --only voice,asr     any of: voice, asr, fast, server (server = the llama.cpp zips only)
    python -m star.senses.setup --profiles game      which fast profiles (default: dedicated,game; see fastpath.PROFILES)

Everything is pinned and checked: the Kokoro, voice-activity and end-of-turn files and the llama.cpp / Qwen files carry a
size and SHA-256 (star.voice.setup_models, star.senses.fastpath); the speech-to-text models are fetched at one Hugging Face
commit and their model.bin is checked against the SHA-256 below. A step that is already complete does nothing. Prints one
`OK` / `FAILED` line per step and exits 1 when any step failed (setup.ps1 reports the lines). Nothing is started.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from ..voice import setup_models
from ..voice.engines import models_dir
from . import fastpath

STEPS = ("voice", "asr", "fast", "server")


@dataclass(frozen=True)
class AsrModel:
    name: str          # the name faster-whisper and star.voice use ("small.en")
    repo: str
    revision: str      # the commit the sizes and hash below were read from
    size: int          # model.bin
    sha256: str
    what: str


# Read from the Hugging Face API on 2026-10-26; the other files in each repository are small and covered by the commit.
ASR_MODELS = {
    "small.en": AsrModel("small.en", "Systran/faster-whisper-small.en", "d1d751a5f8271d482d14ca55d9e2deeebbae577f",
                         483545366, "62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a",
                         "Whisper small.en for faster-whisper (MIT): her ears when no game runs"),
    "distil-small.en": AsrModel("distil-small.en", "Systran/faster-distil-whisper-small.en",
                                "ef77d90526ccd62cde3808ee70626a01e5cf83e4", 332308257,
                                "1187de3982cdcf962a2fb8f797e429fb4651b875b18fe9ce50b58b52fc9072b7",
                                "distil-whisper small.en (MIT): the lighter ears for game mode"),
}


def _asr_path(model: AsrModel, *, local_only: bool) -> str | None:
    from faster_whisper.utils import download_model
    try:
        return download_model(model.name, local_files_only=local_only, revision=model.revision)
    except Exception:
        if local_only:
            return None
        raise


def asr_ready(model: AsrModel) -> bool:
    path = _asr_path(model, local_only=True)
    if not path:
        return False
    weights = Path(path) / "model.bin"
    return weights.is_file() and weights.stat().st_size == model.size and setup_models.sha256_of(weights) == model.sha256


def fetch_asr(model: AsrModel, report=print) -> bool:
    """Fetch one speech model at its pinned commit and verify model.bin. False when it was already complete."""
    if asr_ready(model):
        return False
    report(f"Downloading {model.name} ({model.size / 1e6:.0f} MB): {model.what}")
    path = _asr_path(model, local_only=False)
    weights = Path(path) / "model.bin"
    if weights.stat().st_size != model.size or setup_models.sha256_of(weights) != model.sha256:
        raise RuntimeError(f"{model.name}: model.bin does not match the pinned size or SHA-256 ({weights})")
    return True


def plan(profiles: tuple[str, ...] = ("dedicated", "game")) -> list[dict]:
    """Rows of {step, name, bytes, present} for everything main() would fetch. Reads the disk only."""
    rows = []
    folder = models_dir()
    for item in setup_models.MODEL_FILES:
        rows.append({"step": "voice", "name": item.name, "bytes": item.size, "present": setup_models.is_ready(item, folder)})
    for model in ASR_MODELS.values():
        try:
            present = asr_ready(model)
        except Exception:
            present = False
        rows.append({"step": "asr", "name": model.name, "bytes": model.size, "present": present})
    fast = folder / "fast"
    seen = set()
    for profile in profiles:
        for item in fastpath.download_plan(profile):
            if item.name not in seen:
                seen.add(item.name)
                rows.append({"step": "fast" if item.name.endswith(".gguf") else "server", "name": item.name,
                             "bytes": item.size, "present": setup_models.is_ready(item, fast)})
    return rows


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    def option(flag: str, default: str) -> str:
        return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default

    only = tuple(x for x in option("--only", ",".join(STEPS)).split(",") if x)
    profiles = tuple(x for x in option("--profiles", "dedicated,game").split(",") if x)
    bad = [x for x in only if x not in STEPS] + [p for p in profiles if p not in fastpath.PROFILES]
    if bad or {"-h", "--help"} & set(args):
        print(__doc__)
        return 2 if bad else 0
    if "--list" in args:
        total = missing = 0
        for row in plan(profiles):
            if row["step"] not in only and not (row["step"] == "server" and "fast" in only):
                continue
            total += row["bytes"]
            missing += 0 if row["present"] else row["bytes"]
            print(f"{'present' if row['present'] else 'MISSING':8} {row['step']:6} {row['name']:44} {row['bytes'] / 1e6:8.0f} MB")
        print(f"to download: {missing / 1e6:.0f} MB of {total / 1e6:.0f} MB")
        return 0
    failed = 0

    def run(label: str, action) -> None:
        nonlocal failed
        try:
            detail = action()
            print(f"OK {label}: {detail}")
        except Exception as why:                    # one failed download must not stop the others
            failed += 1
            print(f"FAILED {label}: {type(why).__name__}: {why}")

    if "voice" in only:
        run("voice files (Kokoro, voice activity, end of turn)",
            lambda: f"{len(setup_models.download())} fetched, rest already there, in {models_dir()}")
    if "asr" in only:
        for model in ASR_MODELS.values():
            run(f"speech model {model.name}", lambda m=model: "fetched" if fetch_asr(m) else "already there")
    if "fast" in only:
        for profile in profiles:
            if fastpath.PROFILES[profile].llm:
                run(f"fast path, profile {profile}", lambda p=profile: fastpath.setup(p)["model"])
    if "server" in only and "fast" not in only:
        run("llama.cpp server", lambda: fastpath.setup("game-tight")["server"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
