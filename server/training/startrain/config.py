"""Settings of the training-data generator. Everything comes from the environment (no address, user name or key in
this repository); the defaults are the paths inside the STAR server container."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    home: Path = field(default_factory=lambda: Path(_env("STAR_TRAIN_HOME", "/opt/star/training")))
    brain_url: str = field(default_factory=lambda: _env("STAR_BRAIN_URL", "http://127.0.0.1:8080"))
    key_file: str = field(default_factory=lambda: _env("STAR_BRAIN_KEY_FILE", "/opt/star/secrets/api_keys"))
    # Teachers: the owner's own open-weight models only (Apache-2.0 weights, run on the owner's server).
    solver_model: str = field(default_factory=lambda: _env("STAR_TRAIN_SOLVER", "star-fast"))
    task_model: str = field(default_factory=lambda: _env("STAR_TRAIN_TASK_MODEL", "star-fast"))
    idea_model: str = field(default_factory=lambda: _env("STAR_TRAIN_IDEA_MODEL", "star-quick"))
    embed_model: str = field(default_factory=lambda: _env("STAR_TRAIN_EMBED_MODEL", "star-embed"))
    # Luau tools (compile and analyse come from the knowledge service install; the VM from the bench build).
    kb_app: str = field(default_factory=lambda: _env("STAR_KB_APP", "/opt/star/knowledge/app"))
    kb_db: str = field(default_factory=lambda: _env("STAR_KB_DB", "/opt/star/knowledge/data/kb.sqlite3"))
    luau_vm: str = field(default_factory=lambda: _env("STAR_LUAU_VM", "/opt/star/bench/tools/luau/build/release/luau"))
    lock_dir: str = field(default_factory=lambda: _env("STAR_LOCK_DIR", "/opt/star/lock"))
    lock_stale_s: float = field(default_factory=lambda: float(_env("STAR_LOCK_STALE_S", "1200")))
    # Politeness. Window "HH:MM-HH:MM" in UTC; empty = any time (the job yields to chats and to the lock anyway).
    window_utc: str = field(default_factory=lambda: _env("STAR_TRAIN_WINDOW_UTC", ""))
    idle_s: float = field(default_factory=lambda: float(_env("STAR_TRAIN_IDLE_S", "120")))
    poll_s: float = field(default_factory=lambda: float(_env("STAR_TRAIN_POLL_S", "3")))
    idle_poll_s: float = field(default_factory=lambda: float(_env("STAR_TRAIN_IDLE_POLL_S", "10")))   # while waiting: fewer requests to the router
    # Sandbox for every run of model-written code.
    vm_wall_s: int = 8
    vm_cpu_s: int = 6
    vm_mem_mb: int = 256
    mutant_wall_s: int = 4
    mutant_cpu_s: int = 3
    # Gate thresholds (starting values from docs/research/training-plan.md section 3.2).
    min_assertions: int = 5
    mutant_kill_rate: float = 0.70
    mutant_min_valid: int = 3
    mutant_max_valid: int = 12
    dup_jaccard: float = 0.70
    dup_cosine: float = 0.92
    decontam_jaccard: float = 0.35
    decontam_containment: float = 0.50
    decontam_code_jaccard: float = 0.50
    decontam_cosine: float = 0.88
    cluster_cap: float = 0.05
    # Optional verifier-feedback repair. Off by default until the owner enables
    # it after reviewing the generated trajectories and server cost.
    solver_repair_rounds: int = field(default_factory=lambda: max(
        0, min(3, int(_env("STAR_TRAIN_SOLVER_REPAIR_ROUNDS", "0")))
    ))
    report_every: int = 5
    seed: int = field(default_factory=lambda: int(_env("STAR_TRAIN_SEED", "20261011")))

    @property
    def data(self) -> Path:
        return self.home / "data"

    @property
    def decontam_index(self) -> Path:
        return self.home / "decontam" / "index.json"

    @property
    def pause_file(self) -> Path:
        return self.home / "PAUSE"

    def ensure_dirs(self) -> None:
        for path in (self.home, self.data, self.home / "decontam", self.home / "suites"):
            path.mkdir(parents=True, exist_ok=True)
