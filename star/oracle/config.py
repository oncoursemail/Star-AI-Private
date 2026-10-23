"""Oracle configs: one JSON file per arm, and what kind of change separates two arms.

    {
      "name": "sft",
      "model": "work/apprentice/gguf/q3-4b-2507/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
      "lora": ["work/ft20/lora/sft.gguf"],
      "bin": "work/oracle/bin",             # llama-score / llama-server; default $STAR_ORACLE_BIN
      "ngl": 99, "ctx": 8192, "threads": 0,
      "template": "chatml", "assistant_prefix": "",
      "settings": {"api_hints_enabled": false, "gold_examples_enabled": false, "worked_bank": null,
                   "luau_retry_ladder": false, "slop_check": "off"},
      "server": {"url": "http://127.0.0.1:8095", "model": "star-fast"},      # L0 against a running server, or
      "launch": {"args": ["-ngl", "99"], "env": {"GGML_RF_PIN": "1"}},      # L0 starts llama-server with these
      "eval": {"args": ["--server", "...", "--model", "star-fast"]}          # L3: extra `python -m star.evals run` args
    }

Paths are relative to the config file. Change kinds (decide which layers can see the change):
  perf    only the binary, threads, offload, launch flags or environment differ -> L0 (then L1 when not identical)
  model   model weights, LoRA or chat template differ                        -> L1 + L2
  prompt  settings that only change the prompt (api hints, example blocks)   -> L2
  loop    settings that change the agent loop (retry ladder, slop repair)    -> nothing below L3 can see them
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

PROMPT_SETTINGS = frozenset({"api_hints_enabled", "gold_examples_enabled", "worked_bank", "worked_bank_chars"})
LOOP_SETTINGS = frozenset({"luau_retry_ladder", "slop_check"})
# A setting left out of a config means the app default.
SETTING_DEFAULTS = {"api_hints_enabled": False, "gold_examples_enabled": False, "worked_bank": None,
                    "luau_retry_ladder": False, "slop_check": "off"}
_MODEL_FIELDS = ("model", "lora", "template", "assistant_prefix", "system")
_PERF_FIELDS = ("bin", "ngl", "threads", "launch")
_TOP = frozenset({"name", "model", "lora", "bin", "ngl", "ctx", "threads", "template", "assistant_prefix", "system",
                  "settings", "server", "launch", "eval"})
TEMPLATES = {"chatml": ("<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n"
                        "<|im_start|>assistant\n{assistant_prefix}", "<|im_end|>")}


@dataclass
class Config:
    name: str
    model: str = ""
    lora: list[str] = field(default_factory=list)
    bin: str = ""
    ngl: int = 0
    ctx: int = 8192
    threads: int = 0
    template: str = "chatml"
    assistant_prefix: str = ""
    system: str | None = None
    settings: dict = field(default_factory=dict)
    server: dict = field(default_factory=dict)
    launch: dict = field(default_factory=dict)
    eval: dict = field(default_factory=dict)

    def tool(self, name: str) -> str:
        folder = self.bin or os.environ.get("STAR_ORACLE_BIN", "")
        exe = name + (".exe" if os.name == "nt" else "")
        return str(Path(folder) / exe) if folder else exe


def _resolve(base: Path, value: str) -> str:
    if not value:
        return value
    path = Path(value)
    return str(path if path.is_absolute() else (base / path))


def from_dict(data: dict, base: Path = Path(".")) -> Config:
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError("config needs a name")
    unknown = set(data) - _TOP
    if unknown:
        raise ValueError(f"config {data['name']}: unknown fields {sorted(unknown)}")
    if data.get("template", "chatml") not in TEMPLATES:
        raise ValueError(f"config {data['name']}: unknown template {data.get('template')!r}")
    settings = dict(data.get("settings") or {})
    if settings.get("worked_bank"):
        settings["worked_bank"] = _resolve(base, settings["worked_bank"])
    return Config(name=data["name"], model=_resolve(base, data.get("model", "")),
                  lora=[_resolve(base, p) for p in data.get("lora") or []], bin=_resolve(base, data.get("bin", "")),
                  ngl=int(data.get("ngl", 0)), ctx=int(data.get("ctx", 8192)), threads=int(data.get("threads", 0)),
                  template=data.get("template", "chatml"), assistant_prefix=data.get("assistant_prefix", ""),
                  system=data.get("system"), settings=settings, server=dict(data.get("server") or {}),
                  launch=dict(data.get("launch") or {}), eval=dict(data.get("eval") or {}))


def load(path) -> Config:
    path = Path(path)
    return from_dict(json.loads(path.read_text(encoding="utf-8")), path.parent)


def change_kinds(base: Config, cand: Config) -> set[str]:
    """The kinds of change between two arms (empty: nothing that matters differs)."""
    kinds = set()
    if any(getattr(base, f) != getattr(cand, f) for f in _MODEL_FIELDS):
        kinds.add("model")
    if any(getattr(base, f) != getattr(cand, f) for f in _PERF_FIELDS):
        kinds.add("perf")
    for key in set(base.settings) | set(cand.settings):
        if base.settings.get(key, SETTING_DEFAULTS.get(key)) != cand.settings.get(key, SETTING_DEFAULTS.get(key)):
            kinds.add("prompt" if key in PROMPT_SETTINGS else "loop")
    return kinds
