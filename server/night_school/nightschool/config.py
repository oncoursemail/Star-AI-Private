"""Settings of night school. Everything comes from the environment: no address, user name or key in the repository.
The defaults are the paths inside the STAR server container."""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    home: Path = field(default_factory=lambda: Path(_env("STAR_NS_HOME", "/opt/star/learning")))
    brain_url: str = field(default_factory=lambda: _env("STAR_NS_BRAIN_URL", "http://127.0.0.1:8080"))
    key_file: str = field(default_factory=lambda: _env("STAR_NS_KEY_FILE", "/opt/star/secrets/api_keys"))
    model: str = field(default_factory=lambda: _env("STAR_NS_MODEL", "star-fast"))
    mode: str = field(default_factory=lambda: _env("STAR_NS_MODE", "auto"))
    # "" = the app's own default set of skill packs (STAR_SKILL_PACKS stays unset).
    packs: str = field(default_factory=lambda: _env("STAR_NS_PACKS", ""))
    luau_vm: str = field(default_factory=lambda: _env("STAR_NS_LUAU_VM", "/opt/star/bench/tools/luau/build/release/luau"))
    lock_dir: str = field(default_factory=lambda: _env("STAR_NS_LOCK_DIR", "/opt/star/lock"))
    # Politeness: the brain must have had no other client for idle_s seconds; never slot 0.
    idle_s: float = field(default_factory=lambda: float(_env("STAR_NS_IDLE_S", "600")))
    poll_s: float = field(default_factory=lambda: float(_env("STAR_NS_POLL_S", "10")))
    watch_s: float = field(default_factory=lambda: float(_env("STAR_NS_WATCH_S", "3")))
    slot: int = field(default_factory=lambda: int(_env("STAR_NS_SLOT", "1")))
    # STAR's resource planner (star/resource_planner_service.py) on this machine; "off" = only the idle gate above.
    # Planner down or without fresh data: the idle gate decides, exactly as before.
    planner_url: str = field(default_factory=lambda: _env("STAR_NS_PLANNER_URL", "http://127.0.0.1:8098"))
    # "priority": brain_url goes through STAR's priority proxy (star/priority_proxy.py, e.g. http://127.0.0.1:8097/p3),
    # which pauses night school's generation for the owner's chat and resumes it; so night school works beside other
    # clients (no idle wait, no cancel). HOLD and the quiet lock still stop it. Proxy not answering: the idle gate.
    gate: str = field(default_factory=lambda: _env("STAR_NS_GATE", "idle"))
    # Parallel practice lanes (each its own planner lease and its own slot: slot, slot + 1, ...). Lanes 2..N run only
    # while the planner admits them; with the planner off or down night school is single-lane, as before.
    # The model that drafts lessons (the "diagnose" step, 260 tokens). "" = the answer model. star-quick (its own
    # process and slots) keeps star-fast free for answers; a weak lesson costs nothing: it is kept only if the task
    # then passes.
    diagnose_model: str = field(default_factory=lambda: _env("STAR_NS_DIAGNOSE_MODEL", ""))
    lanes: int = field(default_factory=lambda: max(1, min(4, int(_env("STAR_NS_LANES", "1")))))
    # Learning rules.
    validation_percent: int = field(default_factory=lambda: int(_env("STAR_NS_VALIDATION_PERCENT", "20")))
    # W1 paired gate (star/eval_stats.py): 24 validation tasks, k samples per arm, both arms interleaved in one
    # session; only a significant improvement promotes, only a significant loss retires.
    validation_max: int = field(default_factory=lambda: int(_env("STAR_NS_VALIDATION_MAX", "24")))
    samples: int = field(default_factory=lambda: int(_env("STAR_NS_SAMPLES", "2")))
    recheck_samples: int = field(default_factory=lambda: int(_env("STAR_NS_RECHECK_SAMPLES", "2")))
    gate_alpha: float = field(default_factory=lambda: float(_env("STAR_NS_GATE_ALPHA", "0.05")))
    promote_fixes: int = field(default_factory=lambda: int(_env("STAR_NS_PROMOTE_FIXES", "2")))
    batch: int = field(default_factory=lambda: int(_env("STAR_NS_BATCH", "5")))
    recheck_every: int = field(default_factory=lambda: int(_env("STAR_NS_RECHECK_EVERY", "40")))
    retry_candidates: int = field(default_factory=lambda: int(_env("STAR_NS_RETRY_CANDIDATES", "1")))
    # Validation budget: validation answers (gates, rechecks) may take at most this share of all answer time; a gate
    # run pauses between tasks when it is used up and resumes after more practice. 0 = no limit (the old behaviour).
    # The gate itself is unchanged: only a significant paired win on the validation slice promotes.
    validation_share: float = field(default_factory=lambda: float(_env("STAR_NS_VALIDATION_SHARE", "0")))
    # A disjoint share of the practice tasks for one of several workers, "k/n" or "k1,k2/n": a task belongs to this
    # worker when sha256(id) mod n is one of the k's. "" = every task. The validation slice is not affected.
    share: str = field(default_factory=lambda: _env("STAR_NS_SHARE", ""))
    # The documentation and Luau-check service; "" = the brain's own host on the knowledge port (as before).
    knowledge_url: str = field(default_factory=lambda: _env("STAR_NS_KNOWLEDGE_URL", ""))
    # Practice tasks another worker already answered (a JSON list of ids): left out of this worker's practice, so
    # a share that moves from one worker to another is not answered twice. "" = none.
    skip_file: str = field(default_factory=lambda: _env("STAR_NS_SKIP_FILE", ""))
    # A worker outside the server (the PC's graphics card): run the unit tests in the server container's sandbox over
    # SSH (star/eval_sandbox.ContainerSandbox, "user@address"), never on this machine. "" = the local Luau VM.
    sandbox_ssh: str = field(default_factory=lambda: _env("STAR_NS_SANDBOX_SSH", ""))
    # Anti-slop check (star/slop.py) of every answer: "off" (default), "measure" (the score is recorded in the
    # attempt's checks, pass/fail unchanged) or "gate" (a slop answer fails: it cannot become a verified example).
    slop: str = field(default_factory=lambda: _env("STAR_NS_SLOP", "off"))
    slop_max: int = field(default_factory=lambda: int(_env("STAR_NS_SLOP_MAX", "30")))

    # The night conductor (conductor.py): turns last night's failures and the newest notes into new practice tasks.
    # On by default for nights; "off" (or the file data/CONDUCTOR_OFF) switches it off. Models are tried in order; a
    # model with a single slot (slot 0 is the owner's chat) is skipped, so star-deep is used only while it has a spare slot.
    conductor: str = field(default_factory=lambda: _env("STAR_NS_CONDUCTOR", "on"))
    conductor_models: str = field(default_factory=lambda: _env("STAR_NS_CONDUCTOR_MODELS", "star-deep,star-fast"))
    conductor_max_new: int = field(default_factory=lambda: int(_env("STAR_NS_CONDUCTOR_MAX_NEW", "40")))
    conductor_window: str = field(default_factory=lambda: _env("STAR_NS_CONDUCTOR_WINDOW", "18:00-09:00"))
    conductor_tz_hours: float = field(default_factory=lambda: float(_env("STAR_NS_CONDUCTOR_TZ_HOURS", "-5")))   # owner's local time vs UTC
    conductor_interval_min: int = field(default_factory=lambda: int(_env("STAR_NS_CONDUCTOR_INTERVAL_MIN", "30")))
    conductor_docs: str = field(default_factory=lambda: _env("STAR_NS_CONDUCTOR_DOCS", ""))   # "" = home/docs-recent
    conductor_tag: str = field(default_factory=lambda: _env("STAR_NS_CONDUCTOR_TAG", ""))     # "pc-": pool/conductor-pc-<night>.json

    # Curiosity queue (star/curiosity.py): the conductor turns the app's open "did not know / got wrong" items into
    # practice tasks. data/curiosity.jsonl is the app PC's snapshot (pc/turbo.py sync); the conductor's own results go to
    # data/curiosity-done.jsonl, which the PC brings back. "off" = the conductor ignores the queue.
    curiosity: str = field(default_factory=lambda: _env("STAR_NS_CURIOSITY", "on"))
    curiosity_items: int = field(default_factory=lambda: int(_env("STAR_NS_CURIOSITY_ITEMS", "6")))

    @property
    def curiosity_file(self) -> Path:
        return self.data / "curiosity.jsonl"

    @property
    def curiosity_done_file(self) -> Path:
        return self.data / "curiosity-done.jsonl"

    @property
    def app(self) -> Path:          # a copy of the repository (the folder that holds `star/`)
        return Path(_env("STAR_NS_APP", str(self.home / "app")))

    @property
    def pool(self) -> Path:
        return Path(_env("STAR_NS_POOL", str(self.home / "pool")))

    @property
    def data(self) -> Path:
        return self.home / "data"

    @property
    def report_file(self) -> Path:
        return self.home / "report" / "latest.md"

    @property
    def outbox(self) -> Path:
        return self.home / "outbox"

    @property
    def conductor_dir(self) -> Path:
        return self.home / "conductor"

    @property
    def conductor_off_file(self) -> Path:
        return self.data / "CONDUCTOR_OFF"

    @property
    def hold_file(self) -> Path:
        return self.data / "HOLD"

    def ensure_dirs(self) -> None:
        for path in (self.home, self.data, self.pool, self.outbox, self.report_file.parent):
            path.mkdir(parents=True, exist_ok=True)
