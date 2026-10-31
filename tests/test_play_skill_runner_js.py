"""star/play/minecraft/skill_runner.js under real Node with a fake Mineflayer bot: state stream, a skill that
changes the inventory, a refused skill, a skill calling a dependency, and a timeout."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "star" / "play" / "minecraft" / "skill_runner.js"
NODE = shutil.which("node") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")

SCRIPT = r"""
const play = require(process.argv[2])
const events = []
const emit = (e) => events.push(e)
const items = []
const bot = {
  health: 20, food: 17, entity: { position: { x: 1, y: 64, z: 2, distanceTo: () => 0 }, yaw: 0, pitch: 0, height: 1.62 },
  entities: {}, inventory: { items: () => items },
  dig: async () => { items.push({ name: 'dirt', count: 1 }) },
  look: async () => {},
  on: () => {}
}
const zombie = { name: 'zombie', type: 'hostile', position: { distanceTo: () => 4.2 } }
bot.entities = { 1: bot.entity, 2: zombie }
async function main () {
  const handle = play.install(bot, emit, { hz: 50, goals: {} })
  await new Promise((r) => setTimeout(r, 60))
  await handle({ cmd: 'run_skill', id: 'a', name: 'dig_two', code: 'await bot.dig(); await bot.dig(); return 2', timeout_ms: 2000 })
  await handle({ cmd: 'run_skill', id: 'b', name: 'evil', code: "const fs = require('fs')", timeout_ms: 2000 })
  await handle({ cmd: 'run_skill', id: 'c', name: 'uses_dep', code: "await h.skill('dig_one')", deps: { dig_one: 'await bot.dig()' }, timeout_ms: 2000 })
  await handle({ cmd: 'run_skill', id: 'd', name: 'slow', code: 'await h.sleep(5000)', timeout_ms: 100 })
  const unknown = await handle({ cmd: 'chat', text: 'hi' })
  console.log(JSON.stringify({ events, unknown }))
  process.exit(0)
}
main()
"""


@pytest.mark.skipif(not Path(NODE).exists(), reason="Node.js not installed")
def test_skill_runner_js_with_fake_bot(tmp_path):
    script = tmp_path / "drive.js"
    script.write_text(SCRIPT, encoding="utf-8")
    done = subprocess.run([NODE, str(script), str(RUNNER)], capture_output=True, text=True, timeout=30,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**os.environ})
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["unknown"] is False                         # not a play command: bot.js handles it
    states = [e for e in out["events"] if e["type"] == "state"]
    assert states and states[0]["hostiles"] == [["zombie", 4.2]] and states[0]["food"] == 17
    results = {e["id"]: e for e in out["events"] if e["type"] == "skill_result"}
    assert results["a"]["ok"] and results["a"]["before"]["inventory"] == {} and results["a"]["after"]["inventory"] == {"dirt": 2}
    assert not results["b"]["ok"] and "forbidden" in results["b"]["error"]
    assert results["c"]["ok"] and results["c"]["after"]["inventory"] == {"dirt": 3}
    assert not results["d"]["ok"] and "timeout" in results["d"]["error"]
