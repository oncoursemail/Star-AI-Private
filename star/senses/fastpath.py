"""The fast voice-turn path for her own PC (an RTX 4060, 8 GB): a small model on her GPU answers ordinary
conversation, brain 1 answers the hard turns. Everything is a setting; nothing runs unless asked.

Why: on a CPU-only brain the first token alone takes seconds (docs/STAR_VOICE_CALLS.md section 7), which no amount of
streaming hides. A 2B-4B model fully on the GPU starts talking in about a tenth of a second.

Contents
  FAST_MODELS / PROFILES   the model choices and what each profile keeps on the GPU
  vram_budget()            the table of what must fit in 8 GB (measured rows are marked, the rest are estimates)
  download_plan()          exactly which files to fetch (URL, size, SHA-256) for the installer to call
  server_command()         the llama.cpp server command line for a profile
  RoutedBrain              per turn: the local model for ordinary talk, the big brain for hard turns, and the big brain
                           again whenever the local server is down
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from ..voice.setup_models import ModelFile

HF = "https://huggingface.co"


@dataclass(frozen=True)
class FastModel:
    id: str
    name: str
    file: ModelFile
    weights_gb: float
    notes: str


# URLs pin the repository revision, so the file cannot change under the recorded SHA-256 (LFS object id).
FAST_MODELS = {
    "qwen3.5-4b-q4": FastModel(
        "qwen3.5-4b-q4", "Qwen3.5-4B Q4_K_M",
        ModelFile("Qwen3.5-4B-Q4_K_M.gguf",
                  f"{HF}/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf",
                  2740937888, "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
                  "Qwen3.5-4B instruct, Q4_K_M (Apache-2.0)"),
        2.74, "the default when no game is running; the model the project already ran at about 60 tokens/s on a 3060 Ti"),
    "qwen3.5-4b-q5": FastModel(
        "qwen3.5-4b-q5", "Qwen3.5-4B Q5_K_M",
        ModelFile("Qwen3.5-4B-Q5_K_M.gguf",
                  f"{HF}/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q5_K_M.gguf",
                  3143656608, "8814232b85594dcd46c50e5b8b29324a7efe9e746edbe8a3d1df3d3fce7aad39",
                  "Qwen3.5-4B instruct, Q5_K_M (Apache-2.0)"),
        3.14, "a little more faithful than Q4 for 0.4 GB more; pick it when no game runs and quality matters most"),
    "qwen3.5-2b-q4": FastModel(
        "qwen3.5-2b-q4", "Qwen3.5-2B Q4_K_M",
        ModelFile("Qwen3.5-2B-Q4_K_M.gguf",
                  f"{HF}/unsloth/Qwen3.5-2B-GGUF/resolve/f6d5376be1edb4d416d56da11e5397a961aca8ae/Qwen3.5-2B-Q4_K_M.gguf",
                  1280835840, "aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
                  "Qwen3.5-2B instruct, Q4_K_M (Apache-2.0)"),
        1.28, "game mode: about half the memory, about twice the speed, a little less depth"),
}
LLAMA_CPP = (
    ModelFile("llama-b11870-bin-win-cuda-12.4-x64.zip",
              "https://github.com/ggml-org/llama.cpp/releases/download/b11870/llama-b11870-bin-win-cuda-12.4-x64.zip",
              272663995, "0e3c2ed58e08362c37274e578b20bfaa5c73970052f333be832f139ce2ee0f48",
              "llama.cpp server b11870, CUDA 12.4 build (MIT)"),
    ModelFile("cudart-llama-bin-win-cuda-12.4-x64.zip",
              "https://github.com/ggml-org/llama.cpp/releases/download/b11870/cudart-llama-bin-win-cuda-12.4-x64.zip",
              391443627, "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
              "CUDA 12.4 runtime DLLs for llama.cpp (NVIDIA redistributable)"),
)
WHISPER_FASTER = {"distil-small.en": "Systran/faster-distil-whisper-small.en (332 MB, MIT), fetched by faster-whisper on first use"}


@dataclass(frozen=True)
class Profile:
    id: str
    summary: str
    llm: str | None            # key of FAST_MODELS, None = no local model: every turn goes to brain 1
    asr_model: str
    asr_compute: str
    ctx: int


PROFILES = {
    "dedicated": Profile("dedicated", "no game running: the 4B model, the better speech recogniser", "qwen3.5-4b-q4",
                         "small.en", "float16", 4096),
    "game": Profile("game", "a game is running (up to about 3.5 GB of VRAM): the 2B model, a lighter recogniser",
                    "qwen3.5-2b-q4", "distil-small.en", "float16", 3072),
    "game-tight": Profile("game-tight", "a heavy game (up to about 5 GB): no local model, every turn to brain 1",
                          None, "distil-small.en", "float16", 0),
}


# Expressive neural voice engines (star/voice_neural.py): allowed only when no game holds the card. In game modes the
# expressive voice still works (Kokoro + DSP styles + pre-rendered sounds, all on the CPU side of the budget).
EXPRESSIVE_GB = {"qwen3-tts": 2.9, "qwen3-design": 4.7}         # torch peak allocated, measured 2026-10-27
EXPRESSIVE_PROFILES = frozenset({"off", "dedicated"})


def expressive_allowed(profile: str, engine: str, free_gb: float | None = None, total_gb: float = 8.0) -> tuple[bool, str]:
    """(allowed, why) for loading a neural expressive engine beside the rest of the voice stack on her 8 GB card.
    Never while a game holds the card; never next to the local fast model when the budget table says they do not both
    fit (dedicated: 4B model + Qwen3-TTS is about 9.2 GB); otherwise only with the measured VRAM free right now."""
    if engine not in EXPRESSIVE_GB:
        return False, f"unknown engine {engine}"
    if profile not in EXPRESSIVE_PROFILES and profile != "auto":
        return False, f"profile {profile}: a game owns the VRAM, the live DSP voice is used instead"
    free_gb = free_vram_gb() if free_gb is None else free_gb
    if free_gb is None:
        return False, "no NVIDIA GPU found: live DSP voice"
    if profile == "auto" and pick_profile(free_gb) != "dedicated":
        return False, "auto profile without room for the dedicated set: live DSP voice"
    if profile in ("auto", "dedicated") and vram_budget("dedicated", total_gb, expressive=engine)["used_gb"] > total_gb:
        return False, (f"{engine} and the local fast model do not both fit in {total_gb:g} GB; set fast_profile off "
                       "(turns go to brain 1) to use the neural voice")
    if free_gb < EXPRESSIVE_GB[engine] + 0.3:
        return False, f"only {free_gb:.1f} GB free, {engine} needs about {EXPRESSIVE_GB[engine]} GB"
    return True, "ok"


def vram_budget(profile: str, total_gb: float = 8.0, game_gb: float = 0.0, expressive: str = "") -> dict:
    """Rows of (what, GB, basis) and the total for a profile on an 8 GB card. basis is "measured" only where this
    project measured it; everything else is an estimate to be replaced by nvidia-smi readings on her PC."""
    p = PROFILES[profile]
    llm = FAST_MODELS[p.llm] if p.llm else None
    rows = [("Windows desktop and compositor", 0.7, "estimate"),
            ("Kokoro voice on the GPU, incl. its CUDA context", 1.18, "measured on an RTX 3060 Ti (1177 MB)"),
            (f"Speech recognition {p.asr_model} {p.asr_compute}", 0.9 if p.asr_model == "small.en" else 0.6,
             "estimate (CTranslate2 weights plus workspace)")]
    if llm:
        rows.append((f"{llm.name} weights", llm.weights_gb, "file size"))
        rows.append(("llama.cpp process: CUDA context, compute buffers, KV cache at the profile context size",
                     0.8 if llm.weights_gb > 2 else 0.65, "estimate"))
    if expressive in EXPRESSIVE_GB and profile in EXPRESSIVE_PROFILES:
        rows.append((f"expressive voice {expressive} (bf16 weights, codec, CUDA graphs)", EXPRESSIVE_GB[expressive],
                     "measured on an RTX 3060 Ti (docs/agents/voice-expressive-20261026.md)"))
    used = round(sum(r[1] for r in rows), 2)
    return {"profile": profile, "rows": rows, "used_gb": used, "free_gb": round(total_gb - used, 2),
            "fits_with_game": (total_gb - used) >= game_gb, "game_gb": game_gb}


# Expected latencies on an RTX 4060 (labelled estimates: not measured on her PC; the 3060 Ti numbers are measured).
LATENCY_ESTIMATES = (
    ("speech recognition of a 3 s sentence, small.en fp16", "0.12 to 0.2 s", "3060 Ti measured 0.17 s"),
    ("local model, first token (prompt cached, about 50 new tokens)", "0.05 to 0.12 s", "estimate"),
    ("local model, speed 4B Q4 / 2B Q4", "65 to 75 / 120 to 140 tokens/s", "estimate: 272 GB/s memory bandwidth"),
    ("Kokoro, first sentence", "0.3 to 0.4 s", "3060 Ti measured 0.33 s"),
    ("sound device round trip through the virtual cable", "10 to 40 ms", "to be measured with routes.py verify"),
)


def pick_profile(free_gb: float, spare_gb: float = 0.3) -> str:
    """The richest profile that fits in the free VRAM nvidia-smi reports right now (the desktop's own share is
    already in use, so it is not counted again) and leaves `spare_gb` over."""
    for name in ("dedicated", "game"):
        if free_gb >= vram_budget(name)["used_gb"] - 0.7 + spare_gb:
            return name
    return "game-tight"


def free_vram_gb() -> float | None:
    """Free VRAM on the first NVIDIA GPU, or None when nvidia-smi is not available."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return int(out.stdout.split()[0]) / 1024.0
    except Exception:
        return None


def download_plan(profile: str = "dedicated", include_server: bool = True) -> list[ModelFile]:
    """The files the installer should fetch for a profile (server zips first, then the model). Sizes and SHA-256
    are checked by star.voice.setup_models.download before a file gets its final name."""
    plan = list(LLAMA_CPP) if include_server else []
    p = PROFILES[profile]
    if p.llm:
        plan.append(FAST_MODELS[p.llm].file)
    return plan


def setup(profile: str = "dedicated", report=print, opener=None) -> dict:
    """The installer entry point: fetch the llama.cpp server and the profile's model (size and SHA-256 checked),
    unpack the server, and return {"server", "model", "profile", "port"} for server_command(). Nothing is started."""
    import zipfile
    from ..voice import setup_models
    from ..voice.engines import models_dir
    folder = models_dir() / "fast"
    setup_models.download(folder, report, opener, files=download_plan(profile))
    unpacked = folder / "llama.cpp"
    if not (unpacked / "llama-server.exe").is_file():
        for item in LLAMA_CPP:
            with zipfile.ZipFile(folder / item.name) as archive:
                archive.extractall(unpacked)
    model = PROFILES[profile].llm
    return {"profile": profile, "server": str(unpacked / "llama-server.exe"),
            "model": str(folder / FAST_MODELS[model].file.name) if model else "", "port": 8082}


def server_command(profile: str, server_exe: str, model_path: str, port: int = 8082) -> list[str]:
    """llama.cpp server for a profile: everything on the GPU, flash attention, quantised KV cache, one slot, loopback only."""
    p = PROFILES[profile]
    if not p.llm:
        raise ValueError("this profile has no local model")
    return [server_exe, "-m", model_path, "--host", "127.0.0.1", "--port", str(port), "-ngl", "99", "-fa", "on",
            "-c", str(p.ctx), "-ctk", "q8_0", "-ctv", "q8_0", "--parallel", "1", "--jinja", "--no-webui",
            "--cache-reuse", "256"]


# -- routing -------------------------------------------------------------------------------------------------
_HARD = re.compile(
    r"\b(code|coding|script|function|debug|bug|error|compile|algorithm|regex|sql|json|python|luau|roblox|unity|godot|"
    r"explain in detail|step by step|in depth|essay|story|poem|plan|compare|analy[sz]e|research|summari[sz]e|"
    r"calculate|equation|prove|derive|translate|night school|knowledge|brain|remember when|what did we|"
    r"look up|search|latest|news|price|buy|order|schedule|email)\b", re.I)
MAX_FAST_WORDS = 35


def hard_turn(text: str) -> bool:
    """Does this turn need the big brain? Conservative: long, technical or tool-like turns go there."""
    words = re.findall(r"[A-Za-z0-9']+", text or "")
    return len(words) > MAX_FAST_WORDS or bool(_HARD.search(text or ""))


class RoutedBrain:
    """Brain protocol over two brains. mode: "auto" (route by hard_turn), "fast" (always local), "big" (never local).
    Falls back to the big brain when the local server cannot be reached, and stays on it for `cooldown` seconds."""

    def __init__(self, fast, big, mode: str = "auto", cooldown: float = 30.0, clock=None) -> None:
        import time
        self.fast, self.big, self.mode, self.cooldown = fast, big, mode, cooldown
        self.clock = clock or time.monotonic
        self._down_until = 0.0
        self.last_route = ""
        self.routes: list[str] = []

    def stream(self, messages: list[dict]):
        text = messages[-1].get("content", "") if messages else ""
        want_fast = (self.mode == "fast") or (self.mode == "auto" and not hard_turn(text))
        if want_fast and self.fast is not None and self.clock() >= self._down_until:
            try:
                stream = self.fast.stream(messages)
                self._note("fast")
                return stream
            except Exception:
                self._down_until = self.clock() + self.cooldown
        self._note("big")
        return self.big.stream(messages)

    def _note(self, route: str) -> None:
        self.last_route = route
        self.routes.append(route)
        del self.routes[:-200]

    def prime(self, messages: list[dict]) -> None:
        for brain in (self.fast, self.big):
            if brain is not None and hasattr(brain, "prime"):
                brain.prime(messages)

    def close(self) -> None:
        for brain in (self.fast, self.big):
            if brain is not None and hasattr(brain, "close"):
                brain.close()
