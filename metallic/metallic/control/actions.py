"""The admin allow-list. An action is (machine, verb); only verbs in CATALOG exist, and a machine offers only the verbs
its config lists (which must match what that host's gate.json enables: the gate refuses anything else on its own).

Brain hosts run the verb through the host gate (`ssh <host> act <verb>`); the PC runs it from its agent, which picks
pending commands up with its next push (every 10 s) and reports the result with the push after that.
No arbitrary shell, no passwords, nothing that needs sudo.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import threading
import time

# verb -> (group, label template, what happens, danger)
CATALOG: dict[str, tuple[str, str, str, str]] = {
    "restart:star-brain": ("STAR services", "Restart star-brain",
                           "Restarts the llama.cpp router: every loaded model unloads and reloads (about a minute "
                           "without chat; star-fast reload takes longest).", "high"),
    "restart:star-knowledge": ("STAR services", "Restart star-knowledge",
                               "Restarts the docs search and Luau checks service (a few seconds unavailable).", "normal"),
    "restart:star-search-gateway": ("STAR services", "Restart star-search-gateway",
                                    "Restarts the web search gateway in front of SearXNG.", "normal"),
    "restart:searxng": ("STAR services", "Restart searxng", "Restarts the local SearXNG search engine.", "normal"),
    "restart:star-night-school": ("STAR services", "Restart star-night-school",
                                  "Restarts night school; the answer it is working on is dropped.", "normal"),
    "restart:star-ns-brain": ("STAR services", "Restart star-ns-brain",
                              "Restarts brain 2's night-school model server (night school there waits for it).",
                              "normal"),
    "restart:star-discord": ("STAR services", "Restart star-discord",
                             "Restarts Star's Discord bot (offline for a few seconds; queued DMs are kept).", "normal"),
    "ns-pause": ("Night school", "Pause night school",
                 "Writes the HOLD file: night school stops after dropping its current answer.", "normal"),
    "ns-resume": ("Night school", "Resume night school", "Removes the HOLD file: night school carries on.", "normal"),
    "litha-brain:off": ("Litha", "Turn Litha off on brain 1",
                        "Unloads litha-26b on brain 1 (about 18 GB RAM back) and keeps it unloaded after restarts; "
                        "litha requests go to the GPU nodes, then star-fast. The router restarts (a few seconds).",
                        "high"),
    "litha-brain:on": ("Litha", "Turn Litha on on brain 1",
                       "Loads litha-26b on brain 1 again (cold load about a minute) and makes it the router's "
                       "fallback when the GPU nodes are busy or away. The router restarts (a few seconds).", "normal"),
    "runner-start:github": ("CI runners", "Start the GitHub runner", "Starts brain2-ci-runner (GitHub Actions).",
                            "normal"),
    "runner-stop:github": ("CI runners", "Stop the GitHub runner",
                           "Stops brain2-ci-runner; a job it is running fails and Linux jobs wait.", "high"),
    "runner-start:forge": ("CI runners", "Start the forge runner", "Starts brain2-forge-runner (Forgejo Actions).",
                           "normal"),
    "runner-stop:forge": ("CI runners", "Stop the forge runner",
                          "Stops brain2-forge-runner; a job it is running fails.", "high"),
    "runner-start:pc-win": ("CI runners", "Start the Windows runner",
                            "Starts pc-win-runner on the PC (minimised, below-normal priority).", "normal"),
    "runner-stop:pc-win": ("CI runners", "Stop the Windows runner",
                           "Stops pc-win-runner; a running Windows job fails.", "high"),
    "backup-now:starai": ("Backups", "Back up brain 1 now",
                          "Starts the hourly brain 1 backup job on brain 2 now (incremental, about a minute).", "normal"),
    "backup-now:kb": ("Backups", "Back up the knowledge base now",
                      "Starts the daily kb.sqlite3 backup now (about 2 GB read from brain 1, several minutes).",
                      "normal"),
    "backup-now:forge": ("Backups", "Back up the forge now",
                         "Starts the forge's nightly dump now (about 3 GB written on brain 1's /data).", "normal"),
    "backup-now:pc": ("Backups", "Back up the PC now", "Runs the PC's hourly recovery export and push now.", "normal"),
    "sunshine-start": ("PC", "Start Sunshine", "Starts the Sunshine streaming service on the PC.", "normal"),
    "sunshine-stop": ("PC", "Stop Sunshine", "Stops the Sunshine streaming service; a running stream ends.", "high"),
}
PC_VERBS = {"runner-start:pc-win", "runner-stop:pc-win", "backup-now:pc", "sunshine-start", "sunshine-stop"}
VERB = re.compile(r"^[a-z0-9:-]{2,48}$")


def catalog(machines: list[dict]) -> list[dict]:
    """Every action the configured machines offer, in catalog order."""
    out = []
    for verb, (group, label, detail, danger) in CATALOG.items():
        for m in machines:
            if verb in m.get("actions", []):
                out.append({"id": f"{m['id']}/{verb}", "machine": m["id"], "machine_name": m.get("name", m["id"]),
                            "verb": verb, "group": group, "label": label, "detail": detail, "danger": danger})
    return out


def find(machines: list[dict], action_id: str) -> dict | None:
    for item in catalog(machines):
        if item["id"] == action_id:
            return item
    return None


class Runner:
    """Runs allowed actions and records each one in the audit log (store) and an append-only JSONL file."""

    def __init__(self, store, machines: list[dict], ssh_base: list[str], audit_file: str | None = None,
                 run=subprocess.run, clock=time.time):
        self.store, self.machines, self.ssh_base = store, machines, ssh_base
        self.audit_file, self.run, self.clock = audit_file, run, clock
        self.pc_queue: list[dict] = []
        self.lock = threading.Lock()

    def _journal(self, entry: int) -> None:
        if not self.audit_file:
            return
        row = next((r for r in self.store.audit(50) if r["id"] == entry), None)
        if row:
            with open(self.audit_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")

    def start(self, action_id: str, actor: str, client: str) -> dict:
        item = find(self.machines, action_id)
        if item is None or not VERB.match(action_id.split("/", 1)[-1]):
            entry = self.store.audit_start(action_id[:80], "refused: not in the allow-list", "", actor, client)
            self.store.audit_finish(entry, "refused", None, "not an allowed action")
            self._journal(entry)
            return {"ok": False, "audit": entry, "text": "refused: not an allowed action"}
        machine = next(m for m in self.machines if m["id"] == item["machine"])
        entry = self.store.audit_start(action_id, f"{item['label']} ({item['machine_name']})", item["machine"],
                                       actor, client)
        if item["verb"] in PC_VERBS:
            with self.lock:
                self.pc_queue.append({"audit": entry, "verb": item["verb"], "queued": self.clock()})
            return {"ok": True, "audit": entry, "state": "pending", "text": "sent to the PC agent (next push, <= 10 s)"}
        threading.Thread(target=self._ssh, args=(entry, machine, item["verb"]), daemon=True).start()
        return {"ok": True, "audit": entry, "state": "pending", "text": "running"}

    def _ssh(self, entry: int, machine: dict, verb: str) -> None:
        try:
            proc = self.run([*self.ssh_base, machine["ssh"], "act", verb], capture_output=True, text=True,
                            timeout=180, stdin=subprocess.DEVNULL)
            try:
                result = json.loads(proc.stdout)
                text = str(result.get("text", ""))
            except ValueError:
                text = (proc.stdout or proc.stderr or "").strip()[-300:]
            self.store.audit_finish(entry, "ok" if proc.returncode == 0 else "failed", proc.returncode, text)
        except (OSError, subprocess.SubprocessError) as exc:
            self.store.audit_finish(entry, "failed", None, f"could not reach the host gate: {type(exc).__name__}")
        self._journal(entry)

    def pc_commands(self) -> list[dict]:
        """Commands for the PC agent; a command not picked up within 2 minutes fails (agent offline)."""
        now, out, keep = self.clock(), [], []
        with self.lock:
            for cmd in self.pc_queue:
                if now - cmd["queued"] > 120:
                    self.store.audit_finish(cmd["audit"], "failed", None, "the PC agent did not pick it up in 2 min")
                    self._journal(cmd["audit"])
                elif not cmd.get("sent"):
                    cmd["sent"] = now
                    out.append({"audit": cmd["audit"], "verb": cmd["verb"]})
                    keep.append(cmd)
                else:
                    keep.append(cmd)
            self.pc_queue = keep
        return out

    def pc_results(self, results: list) -> None:
        for res in results if isinstance(results, list) else []:
            if not isinstance(res, dict) or not isinstance(res.get("audit"), int):
                continue
            with self.lock:
                cmd = next((c for c in self.pc_queue if c["audit"] == res["audit"] and c.get("sent")), None)
                if cmd is None:
                    continue
                self.pc_queue.remove(cmd)
            code = res.get("exit") if isinstance(res.get("exit"), int) else None
            self.store.audit_finish(cmd["audit"], "ok" if res.get("ok") else "failed", code, str(res.get("text", ""))[:300])
            self._journal(cmd["audit"])


def write_text_owner_only(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
